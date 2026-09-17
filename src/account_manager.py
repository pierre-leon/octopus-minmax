import time
from datetime import date, datetime
from typing import Optional, List, Dict
import logging
import config
import web_session
from account_info import AccountInfo
from tariff import Tariff, match_known_tariff
from query_service import QueryService
from octopus_web import (
    OctopusWebClient,
    ineligibility_reasons,
    matching_candidate,
    offered_product_code,
)
from queries import (
    get_terms_version_query,
    accept_terms_query,
    account_query,
    consumption_query,
    enrolment_query
)

logger = logging.getLogger('octobot.account_manager')

class AccountManager:
    _instance: Optional['AccountManager'] = None

    def __init__(self, query_service: QueryService, available_tariffs: List[Tariff]):
        """
        Initializes the AccountManager. This should only be called once via get_instance.
        Args:
            query_service: The service instance for executing API queries.
            available_tariffs: A list of all Tariff objects that the system knows about,
            used to match against the account's current tariff.
        """
        logger.debug(f"Initialising {__class__.__name__}")
        if hasattr(self, '_initialized') and self._initialized:
            return

        self.query_service: QueryService = query_service
        self.config = config
        self.available_tariffs: List[Tariff] = available_tariffs

        self._current_account_info: Optional[AccountInfo] = None
        self.mpan: Optional[str] = None
        self.device_id: Optional[str] = None
        self.region_code: Optional[str] = None

        self._initialized: bool = True

    @classmethod
    def get_instance(cls, query_service: QueryService = None, available_tariffs: List[Tariff] = None) -> 'AccountManager':
        """
        Gets the singleton instance of AccountManager.
        The query_service and available_tariffs must be provided on the first call.
        """
        if cls._instance is None:
            if query_service is None or available_tariffs is None:
                raise ValueError("QueryService and available_tariffs must be provided for the first instantiation of AccountManager.")
            cls._instance = cls(query_service, available_tariffs)
        return cls._instance

    def _get_agreement_terms_version(self, product_code: str) -> Dict[str, int]:
        """Fetches the major and minor version of terms and conditions for a product."""
        query = get_terms_version_query.format(product_code=product_code)
        result = self.query_service.execute_gql_query(query)
        terms_version_str = result.get('termsAndConditionsForProduct', {}).get('version', "1.0").split('.')
        return {'major': int(terms_version_str[0]), 'minor': int(terms_version_str[1])}

    def fetch_current_account_info(self) -> AccountInfo:
        """
        Fetches comprehensive information about the current electricity account,
        including tariff, consumption, MPAN, and device ID.
        Stores key details like MPAN, device ID, and region code as instance attributes.
        """
        query = account_query.format(acc_number=self.config.ACC_NUMBER)
        result = self.query_service.execute_gql_query(query)

        import_agreement = None
        for agreement in result.get("account", {}).get("electricityAgreements", []):
            meter_point_data = agreement.get("meterPoint", {})
            if meter_point_data.get("direction") == "IMPORT":
                import_agreement = agreement
                break

        if not import_agreement:
            raise Exception("ERROR: No IMPORT meter point found in account data")

        tariff_data = import_agreement.get("tariff") or {}
        tariff_code = tariff_data.get("tariffCode")
        if not tariff_code:
            typename = tariff_data.get("__typename")
            raise Exception(
                f"ERROR: No tariff information found for the IMPORT meter"
                + (f" (GraphQL type: {typename})" if typename else "")
            )

        current_standing_charge = tariff_data.get("standingCharge")
        # A standing charge can be 0.0, so check for None explicitly
        if current_standing_charge is None:
            raise Exception("ERROR: No standing charge found for the IMPORT meter tariff")

        self.region_code = tariff_code[-1]

        meter_point_details = import_agreement.get("meterPoint", {})
        self.mpan = meter_point_details.get("mpan")
        if not self.mpan:
            raise Exception("ERROR: No MPAN found for the IMPORT meter")

        # Reset device_id before trying to find it
        self.device_id = None
        for meter in meter_point_details.get("meters", []):
            for device in meter.get("smartDevices", []):
                if "deviceId" in device:
                    self.device_id = device["deviceId"]
                    break
            if self.device_id:
                break

        if not self.device_id:
            raise Exception("ERROR: No device ID found for the IMPORT meter")

        matching_tariff_obj = match_known_tariff(tariff_code)
        if matching_tariff_obj is None:
            display_name = tariff_data.get("displayName") or tariff_data.get("fullName")
            matching_tariff_obj = Tariff.unrecognised(
                tariff_code=tariff_code,
                product_code=tariff_data.get("productCode"),
                display_name=display_name,
            )
            logger.info(
                f"Current tariff '{tariff_code}' ({tariff_data.get('__typename')}) is not a known "
                f"switchable product; running comparison-only as '{matching_tariff_obj.display_name}'."
            )
        elif matching_tariff_obj not in self.available_tariffs:
            logger.info(
                f"Current tariff '{matching_tariff_obj.id}' is not in TARIFFS config; "
                "still using it as the comparison baseline."
            )

        # Get consumption for today
        consumption_gql_query = consumption_query.format(
            device_id=self.device_id,
            start_date=f"{date.today()}T00:00:00Z",
            end_date=f"{date.today()}T23:59:59Z"
        )
        consumption_result = self.query_service.execute_gql_query(consumption_gql_query)
        consumption_data = consumption_result.get('smartMeterTelemetry', [])

        self._current_account_info = AccountInfo(
            current_tariff=matching_tariff_obj,
            standing_charge=current_standing_charge,
            region_code=self.region_code,
            consumption=consumption_data,
            mpan=self.mpan
        )
        return self._current_account_info

    def _web_client(self) -> OctopusWebClient:
        cookie = web_session.cookie()
        if not cookie:
            raise Exception(
                "No Octopus website session stored, so a switch cannot be started. "
                "The bot renews this by logging in with a browser; check the session renewal notifications."
            )
        return OctopusWebClient(cookie, self.config.ACC_NUMBER)

    def prepare_tariff_switch(self, target_tariff: Tariff) -> Dict:
        """Resolve and validate everything a switch needs, without starting one.

        Octopus picks the product for a journey, and that product is sometimes a
        fixed-term one. Refusing any product the comparison did not choose is what
        keeps the bot from enrolling onto a fix.
        """
        if not target_tariff.journey:
            raise Exception(
                f"{target_tariff.display_name} has no enrolment journey, so the bot cannot switch to it."
            )
        if not target_tariff.product_code:
            raise Exception("ERROR: product_code is missing.")
        if not self.mpan:
            logger.info("MPAN not readily available, fetching account details first...")
            self.fetch_current_account_info()
            if not self.mpan:
                raise Exception("ERROR: MPAN could not be determined. Cannot switch tariff.")

        client = self._web_client()
        data = client.enrolment_data(target_tariff.journey, target_tariff.journey_variant)

        property_id = data.get("propertyId")
        if not property_id:
            raise Exception(f"Octopus did not return a propertyId for the {target_tariff.journey} journey.")
        # start-enrolment wants a number here and answers a quoted one with
        # 422 "Invalid body", so don't pass through whatever type came back.
        try:
            property_id = int(property_id)
        except (TypeError, ValueError):
            raise Exception(f"Octopus returned an unusable propertyId ({property_id!r}).")

        candidate = matching_candidate(data, self.mpan)
        if candidate is None:
            raise Exception(f"Meter {self.mpan} is not an enrolment candidate for {target_tariff.display_name}.")

        if not data.get("isEligible") or not candidate.get("isEligible"):
            reasons = ineligibility_reasons(data, candidate)
            detail = f" Reasons: {'; '.join(reasons)}" if reasons else ""
            raise Exception(
                f"Octopus says the account is not eligible for {target_tariff.display_name} today."
                f"{detail} This is also what an open enrolment looks like."
            )

        offered = offered_product_code(data)
        if offered != target_tariff.product_code:
            raise Exception(
                f"Refusing to switch: the {target_tariff.journey} journey would enrol onto '{offered}', "
                f"but the comparison chose '{target_tariff.product_code}'. "
                "Octopus has changed what this journey sells (often to a fixed-term product)."
            )

        return {
            "client": client,
            "journey": target_tariff.journey,
            "variant": target_tariff.journey_variant,
            "property_id": property_id,
            "mpan": self.mpan,
            "product_code": offered,
            "candidate": candidate,
        }

    def initiate_tariff_switch(self, target_tariff: Tariff) -> Optional[str]:
        """Start the switch through the same enrolment API the website uses."""
        plan = self.prepare_tariff_switch(target_tariff)
        plan["client"].start_enrolment(
            journey=plan["journey"],
            property_id=plan["property_id"],
            mpan=plan["mpan"],
        )
        return self.find_pending_enrolment_id(plan["product_code"])

    def find_pending_enrolment_id(self, product_code: str, attempts: int = 6,
                                  delay_seconds: int = 10) -> Optional[str]:
        """Look up the enrolment the REST call just created.

        The enrolment API does not return an id, but acceptTermsAndConditions
        needs one, so we read it back from GraphQL once Octopus has recorded it.
        """
        query = enrolment_query.format(acc_number=self.config.ACC_NUMBER)
        for attempt in range(1, attempts + 1):
            result = self.query_service.execute_gql_query(query)
            enrolments = result.get("productEnrolments") or []
            for enrolment in enrolments:
                if (enrolment.get("product") or {}).get("code") == product_code:
                    logger.info(
                        f"Found enrolment {enrolment.get('id')} for {product_code} "
                        f"(status {enrolment.get('status')})"
                    )
                    return enrolment.get("id")
            logger.info(f"No enrolment for {product_code} yet (attempt {attempt}/{attempts})")
            if attempt < attempts:
                time.sleep(delay_seconds)
        return None

    def accept_new_agreement(self, product_code: str, enrolment_id: str) -> Optional[str]:
        # get terms and conditions version
        version = self._get_agreement_terms_version(product_code)
        # accept terms and conditions
        query = accept_terms_query.format(account_number=self.config.ACC_NUMBER,
                                            enrolment_id=enrolment_id,
                                            version_major=version['major'],
                                            version_minor=version['minor'])
        result = self.query_service.execute_gql_query(query)
        return result.get('acceptTermsAndConditions', {}).get('acceptedVersion', "unknown version")

    def verify_new_agreement_status(self) -> bool:
        """Verifies if the new tariff agreement is active as of today."""
        query = account_query.format(acc_number=self.config.ACC_NUMBER)
        result = self.query_service.execute_gql_query(query)

        today_date = datetime.now().date()
        for agreement in result.get("account", {}).get("electricityAgreements", []):
            valid_from_str = agreement.get('validFrom')
            if valid_from_str:
                try:
                    # API might return a full datetime string or just a date string
                    if 'T' in valid_from_str:
                        agreement_start_date = datetime.fromisoformat(valid_from_str.replace('Z', '+00:00')).date()
                    else:
                        agreement_start_date = date.fromisoformat(valid_from_str)

                    if agreement_start_date == today_date:
                        return True
                except ValueError:
                    logger.warning(f"Could not parse agreement 'validFrom' date: {valid_from_str}")
                    continue
        return False