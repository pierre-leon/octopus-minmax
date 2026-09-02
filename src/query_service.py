import requests
from queries import *
import time
import logging
import threading
from typing import Optional

import config
import session_store

logger = logging.getLogger('octobot.query_service')
MAX_RETRIES = 5
BASE_WAIT_BEFORE_RETRY_SECONDS = 30

_token_lock = threading.RLock()


class QueryService:
    _shared_token = None
    _auth_source = None  # 'customer' | 'api_key'

    def __init__(self, api_key: str, base_url: str):
        logger.debug(f"Initialising {__class__.__name__}")
        self.base_url = base_url
        self.api_key = api_key
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/605.1.15 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/605.1.15',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Content-Type': 'application/json'
        }
        self.graphql_endpoint = f"{self.base_url}/graphql/"

    @classmethod
    def invalidate_token_cache(cls) -> None:
        with _token_lock:
            cls._shared_token = None
            cls._auth_source = None

    @staticmethod
    def has_switch_auth() -> bool:
        return session_store.can_switch()

    def _post_graphql(self, query: str, variables: Optional[dict] = None, token: Optional[str] = None) -> dict:
        headers = self.headers.copy()
        if token:
            headers["Authorization"] = token
        payload = {"query": query, "variables": variables or {}}
        response = requests.post(
            self.graphql_endpoint,
            headers=headers,
            json=payload,
            timeout=60
        )
        response.raise_for_status()
        return response.json()

    def obtain_kraken_token(self, **input_fields) -> dict:
        """Call obtainKrakenToken. input_fields are ObtainJSONWebTokenInput members."""
        token_input = {key: value for key, value in input_fields.items() if value}
        result = self._post_graphql(token_mutation, {"input": token_input})
        if "errors" in result:
            raise Exception(f"GQL errors: {result['errors']}")
        data = (result.get("data") or {}).get("obtainKrakenToken")
        if not data or not data.get("token"):
            raise Exception("GQL token missing from response")
        return data

    def login_with_password(self, email: str, password: str) -> dict:
        data = self.obtain_kraken_token(email=email, password=password)
        if not data.get("refreshToken"):
            raise Exception("Login succeeded but Octopus did not return a refresh token")
        session = session_store.session_from_token_response(data, can_switch=True)
        session_store.save(session)
        with _token_lock:
            QueryService._shared_token = data["token"]
            QueryService._auth_source = "customer"
        logger.info(f"Logged in as Octopus customer ({session.get('email') or email})")
        return session_store.public_status()

    def _get_token(self):
        logger.debug("Getting token")
        try:
            session = session_store.load()
            if session and session.get("refresh_token"):
                try:
                    data = self.obtain_kraken_token(refreshToken=session["refresh_token"])
                    token = data["token"]
                    if data.get("refreshToken"):
                        updated = session_store.session_from_token_response(
                            data, can_switch=bool(session.get("can_switch"))
                        )
                        # Keep switch capability from the original customer login.
                        updated["can_switch"] = bool(session.get("can_switch"))
                        if not updated.get("email"):
                            updated["email"] = session.get("email")
                        session_store.save(updated)
                    QueryService._auth_source = "customer" if session.get("can_switch") else "api_key"
                    logger.info("Acquired token via refresh token")
                    return token
                except Exception as e:
                    logger.warning(f"Refresh token failed: {e}")
                    if session.get("can_switch"):
                        session_store.clear()
                        raise Exception(
                            "Octopus login expired. Open the dashboard Octopus Login page and sign in again."
                        ) from e

            if config.OCTOPUS_EMAIL and config.OCTOPUS_PASSWORD:
                self.login_with_password(config.OCTOPUS_EMAIL, config.OCTOPUS_PASSWORD)
                logger.info("Bootstrapped customer session from OCTOPUS_EMAIL")
                return QueryService._shared_token

            if self.api_key:
                data = self.obtain_kraken_token(APIKey=self.api_key)
                QueryService._auth_source = "api_key"
                logger.info("Acquired token via API key (comparison only; switching needs Octopus Login)")
                return data["token"]

            raise Exception("No Octopus credentials. Set API_KEY and/or complete Octopus Login in the dashboard.")
        except Exception as e:
            logger.error(f"Failed to get token: {type(e).__name__} - {e}")
            raise Exception(f"Failed to get token: {e}")

    def execute_gql_query(self, query: str):
        logger.debug(f"Executing GQL query: '{query}'")
        retry = 0
        token_refreshed = False
        while retry < MAX_RETRIES:
            headers = self.headers.copy()

            with _token_lock:
                if QueryService._shared_token is None or (
                    session_store.can_switch() and QueryService._auth_source != "customer"
                ):
                    QueryService._shared_token = self._get_token()

            if self._shared_token:
                headers["Authorization"] = self._shared_token

            payload = {
                "query": query,
                "variables": {}
            }
            try:
                response = requests.post(
                    self.graphql_endpoint,
                    headers=headers,
                    json=payload,
                    timeout=60
                )

                logger.debug(f"GQL query response: status={response.status_code} | body={response.json()}")
                if response.ok:
                    result = response.json()
                    if "errors" in result:
                        error_codes = [e.get("extensions", {}).get("errorCode") for e in result.get("errors", [])]
                        if "KT-CT-1124" in error_codes and not token_refreshed:
                            logger.debug("JWT expired, refreshing token...")
                            try:
                                QueryService._shared_token = self._get_token()
                                token_refreshed = True
                                continue  # Retry with new token
                            except Exception as e:
                                logger.warning(f"Failed to refresh token: {e}")
                        if "KT-CT-1111" in error_codes:
                            raise Exception(f"GQL errors: {result['errors']}")
                        raise Exception(f"GQL errors: {result['errors']}")

                    data = result.get("data")
                    if data and isinstance(data, dict) and len(data) > 0:
                        return data
                    else:
                        raise Exception("No 'data' returned from GraphQL query")

                if response.status_code in [401, 403] and not token_refreshed:
                    logger.debug("Authentication failed, refreshing token...")
                    try:
                        QueryService._shared_token = self._get_token()
                        token_refreshed = True
                        continue

                    except Exception as e:
                        logger.warning(f"Failed to refresh token: {e}")

            except Exception as e:
                logger.warning(f"Request exception on attempt {retry + 1}/{MAX_RETRIES}: {type(e).__name__} - {e}")
                if retry == MAX_RETRIES - 1:
                    raise Exception(f"GQL query failed after {MAX_RETRIES} attempts: {e}")
                if "KT-CT-1111" in str(e):
                    raise Exception(f"GQL query failed: {e}")

            if retry == MAX_RETRIES - 1:
                logger.warning(f"GQL query failed after {MAX_RETRIES} attempts: {response.status_code}: {response.text}")
                raise Exception(f"GQL query failed after {MAX_RETRIES} attempts: {response.status_code}: {response.text}")


            # Calculate wait time with exponential backoff
            wait_time = BASE_WAIT_BEFORE_RETRY_SECONDS * (2 ** retry)
            logger.debug(f"Request failed with status {response.status_code}. Retrying in {wait_time} seconds... (attempt {retry + 1}/{MAX_RETRIES})")
            retry += 1
            time.sleep(wait_time)

    def execute_rest_query(self, url: str):
        logger.info(f"Executing REST query: {url}")
        try:
            response = requests.get(url, timeout=60)
            logger.debug(f"REST query response: status={response.status_code} | body={response.json() if response.headers.get('content-type', '').startswith('application/json') else response.text[:200]}")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.exception(f"Request failed for {url}: {type(e).__name__} - {e}")
            raise Exception(f"ERROR: Request failed for {url}: {type(e).__name__} - {e}")
