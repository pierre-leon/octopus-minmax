import time
from datetime import date, datetime, timedelta, time as dt_time
from typing import List, Dict, Optional, Tuple
import random
import config
import web_session
from account_info import AccountInfo
from account_manager import AccountManager
from queries import *
from tariff import Tariff, TARIFFS
from query_service import QueryService
from comparison_engine import ComparisonEngine, ComparisonResult, TariffComparison
from demand_model import forecast_consumption, load_consumption_history
from hop import (
    decide_hop,
    saving_pence,
)
from notification_service import NotificationService
from chart import create_tariff_comparison_chart
import logging
logger = logging.getLogger('octobot.bot_orchestrator')

def get_timestamp():
    return datetime.now().strftime("%d/%m/%Y %H:%M")

def time_minus_hours(hhmm: str, hours: int = 1) -> str:
    hour, minute = (int(part) for part in hhmm.split(":", 1))
    shifted = datetime(2000, 1, 1, hour, minute) - timedelta(hours=hours)
    return shifted.strftime("%H:%M")

def early_execution_time() -> Optional[str]:
    if not config.EARLY_RUN:
        return None
    early = time_minus_hours(config.EXECUTION_TIME, 1)
    if early == config.EXECUTION_TIME:
        return None
    return early

def _total(comparison: Optional[TariffComparison]) -> Optional[float]:
    if comparison is None or not comparison.is_valid:
        return None
    return comparison.total_cost

def early_switch_threshold_pence() -> float:
    """Never below the normal threshold, or the early run would switch on
    savings the final run would reject."""
    return max(config.EARLY_SWITCH_THRESHOLD, config.SWITCH_THRESHOLD)

def octopus_login_url() -> str:
    if config.DASHBOARD_URL:
        return f"{config.DASHBOARD_URL}/auth"
    return f"http://localhost:{config.WEB_PORT}/auth"

def switch_login_needed_message() -> str:
    return (
        "Tariff switching needs an Octopus website session. The enrolment API refuses API keys, "
        "OAuth tokens and scoped tokens, and Octopus guards the login form with a captcha, so the "
        "session has to be copied in by hand.\n"
        "Log in at octopus.energy, copy the octosession cookie, and paste it into the dashboard.\n"
        f"Dashboard: {octopus_login_url()}"
    )

class BotOrchestrator:
    def __init__(self):
        logger.debug(f"Initialising {__class__.__name__}")
        self.query_service = None
        self.account_manager = None
        self.tariffs = []
        self.last_early_datetime = None
        self.last_final_datetime = None
        self.switched_on_date = None
        self.notification_service = None

    def start(self) -> None:
        self.notification_service = NotificationService(config.NOTIFICATION_URLS, config.BATCH_NOTIFICATIONS)
        ns = self.notification_service

        mode_msg = self._startup_mode_message()
        ns.send_notification(f"[{get_timestamp()}] Octobot {config.BOT_VERSION} - {mode_msg} \n Check port {config.WEB_PORT} for dashboard.")
        self._warn_if_session_expiring()

        while True:
            if config.ONE_OFF_RUN and not config.ONE_OFF_EXECUTED:
                ns.send_notification(f"[{get_timestamp()}] Octobot {config.BOT_VERSION} - Running one-off comparison")
                self._run_tariff_compare(phase="final")
                config.ONE_OFF_EXECUTED = True
            elif not config.ONE_OFF_RUN:
                self._tick_schedule()

            time.sleep(30)

    def _startup_mode_message(self) -> str:
        if config.ONE_OFF_RUN:
            return "ONE_OFF mode enabled"
        early = early_execution_time()
        if early:
            return (
                f"Scheduled mode, early check at {early}, final run at {config.EXECUTION_TIME}. "
                f"Agile for tomorrow needs a predicted saving over "
                f"£{config.FORWARD_SWITCH_THRESHOLD / 100:.2f}."
            )
        return f"Scheduled mode, running at {config.EXECUTION_TIME}"

    def _tick_schedule(self) -> None:
        ns = self.notification_service
        now = datetime.now()
        current_time = now.strftime("%H:%M")
        current_minute = now.replace(second=0, microsecond=0)
        today = now.date()
        early = early_execution_time()

        if early and current_time == early and self.last_early_datetime != current_minute:
            self.last_early_datetime = current_minute
            delay = random.randint(10, 900)
            ns.send_notification(
                f"[{get_timestamp()}] Octobot {config.BOT_VERSION} - "
                f"Initiating early comparison in {delay/60:.1f} minutes"
            )
            time.sleep(delay)
            if self._run_tariff_compare(phase="early"):
                self.switched_on_date = today
            return

        if current_time != config.EXECUTION_TIME or self.last_final_datetime == current_minute:
            return

        self.last_final_datetime = current_minute
        if self.switched_on_date == today:
            logger.info("Skipping final run - already switched after the early check")
            ns.send_notification(
                f"[{get_timestamp()}] Octobot {config.BOT_VERSION} - "
                f"Skipping {config.EXECUTION_TIME} run; already switched after the early check."
            )
            return

        delay = random.randint(10, 900)
        ns.send_notification(
            f"[{get_timestamp()}] Octobot {config.BOT_VERSION} - "
            f"Initiating comparison in {delay/60:.1f} minutes"
        )
        time.sleep(delay)
        if self._run_tariff_compare(phase="final"):
            self.switched_on_date = today

    def _warn_if_session_expiring(self) -> None:
        """Nag before the session dies, not after a switch has failed.

        Octopus issues it for 7 days, never extends it, and no credential the
        bot holds can mint a new one - so the only fix is a human pasting a
        fresh cookie, and that needs warning ahead of time.
        """
        ns = self.notification_service
        status = web_session.public_status()

        if not status["connected"]:
            ns.send_notification(switch_login_needed_message(), title="Octopus Session Needed", batchable=False)
            return

        remaining = status.get("remaining_days")
        if status["expired"]:
            ns.send_notification(
                "The Octopus session has expired, so tariff switching is offline. Comparisons "
                f"continue as normal.\n{switch_login_needed_message()}",
                title="Octopus Session Expired",
                is_error=True,
                batchable=False,
            )
            return

        if web_session.needs_renewal(config.SESSION_RENEWAL_LEAD_DAYS):
            ns.send_notification(
                f"The Octopus session runs out in {remaining:.1f} days and cannot renew itself.\n"
                f"{switch_login_needed_message()}",
                title="Octopus Session Expiring",
                batchable=False,
            )
            return

        logger.info(f"Website session valid for another {remaining:.1f} days")

    def _initialize(self) -> None:
        logger.debug(f"{__name__}")
        self._load_tariffs_from_ids(config.TARIFFS)
        self.query_service = QueryService(config.API_KEY, config.BASE_URL)
        self.account_manager = AccountManager.get_instance(self.query_service, self.tariffs)


    def _load_tariffs_from_ids(self, tariff_ids: str) -> None:
        """Load tariffs from comma-separated string of IDs."""
        requested_ids = set(tariff_ids.lower().split(","))
        logger.debug(f" Requested tariff IDs - {requested_ids}")
        matched_tariffs = []
        for tariff_id in requested_ids:
            matched = next((t for t in TARIFFS if t.id == tariff_id), None)

            if matched is not None:
                matched_tariffs.append(matched)
            else:
                self.notification_service.send_notification(f"Warning: No tariff found for ID '{tariff_id}'")

        self.tariffs = matched_tariffs

    def _run_tariff_compare(self, phase: str = "final") -> bool:
        ns = self.notification_service
        switched = False
        try:
            self._initialize()
            if self.query_service is None:
                raise Exception("ERROR: QueryService initialization failed")

            switched = self._compare_and_switch(phase)
        except Exception as e:
            ns.send_notification(message=str(e), title="Octobot Error", is_error=True)
        finally:
            if config.BATCH_NOTIFICATIONS:
                ns.send_batch_notification()
            # Last thing of the night, so the warning lands next to the comparison
            # results rather than at some hour nobody is watching. Skip it on an
            # early check that deferred, because the final run still has to fire.
            if phase == "final" or switched:
                self._warn_if_session_expiring()
        return switched

    def _format_comparison_summary(self, result: ComparisonResult) -> str:
        lines = []

        # Current consumption
        current = result.current_tariff_comparison
        if current.cost_breakdown:
            lines.append(f"Total Consumption today: {current.cost_breakdown.total_kwh:.4f} kWh")
            lines.append(
                f"Current tariff {current.tariff.display_name}: "
                f"£{current.cost_breakdown.total_cost_pounds:.2f} "
                f"(£{current.cost_breakdown.consumption_cost_pounds:.2f} con + "
                f"£{current.cost_breakdown.standing_charge_pounds:.2f} s/c)"
            )

        for comparison in result.alternative_comparisons:
            if comparison.is_valid:
                lines.append(
                    f"Potential cost on {comparison.tariff.display_name}: "
                    f"£{comparison.cost_breakdown.total_cost_pounds:.2f} "
                    f"(£{comparison.cost_breakdown.consumption_cost_pounds:.2f} con + "
                    f"£{comparison.cost_breakdown.standing_charge_pounds:.2f} s/c)"
                )
            else:
                lines.append(f"No cost for {comparison.tariff.display_name}")

        return "\n".join(lines)

    def _format_no_switch_message(self, result: ComparisonResult) -> str:
        current = result.current_tariff_comparison.tariff
        current_cost = ""
        if result.current_tariff_comparison.cost_breakdown:
            current_cost = f" at £{result.current_tariff_comparison.cost_breakdown.total_cost_pounds:.2f}"

        if not current.can_leave:
            if result.cheapest_tariff is None:
                return (
                    f"Comparison only - current tariff ({current.display_name}) cannot be switched "
                    f"from automatically."
                )
            if result.potential_savings > 0:
                return (
                    f"Comparison only - staying on {current.display_name}{current_cost}. "
                    f"Cheapest switchable tariff today is {result.cheapest_tariff.display_name} "
                    f"(£{result.potential_savings / 100:.2f} cheaper)."
                )
            return (
                f"Comparison only - current tariff {current.display_name}{current_cost} is cheaper "
                f"than the switchable alternatives today."
            )

        if result.cheapest_tariff == current:
            return f"You are already on the cheapest tariff: {current.display_name}{current_cost}"

        if result.cheapest_tariff is None:
            return "Not switching today - no cheaper switchable tariff was found."

        return (
            f"Not switching today - savings of (£{result.potential_savings / 100:.2f}) "
            f"on the cheapest tariff {result.cheapest_tariff.display_name} are below your "
            f"threshold of £{config.SWITCH_THRESHOLD / 100:.2f}"
        )

    def _compare_and_switch(self, phase: str = "final") -> bool:
        ns = self.notification_service
        phase_prefix = "Early check: " if phase == "early" else ""
        welcome_message = (
            f"{'DRY RUN: ' if config.DRY_RUN else ''}{phase_prefix}"
            f"Starting comparison of today's costs..."
        )
        ns.send_notification(welcome_message)

        account_info = self.account_manager.fetch_current_account_info()

        comparison_engine = ComparisonEngine(self.query_service)
        results = comparison_engine.compare_tariffs(account_info, self.tariffs)

        summary = self._format_comparison_summary(results)
        ns.send_notification(message=summary)
        if config.SEND_COMPARISON_CHART:
            try:
                cost_chart = create_tariff_comparison_chart(results)
            except Exception as e:
                logger.warning(f"Failed to create comparison chart: {e}")
                cost_chart = None
            if cost_chart:
                ns.send_notification(message="", image_path=cost_chart, batchable=False)

        pair = self._agile_cosy_pair()
        if pair and account_info.current_tariff.id in ("agile", "cosy"):
            agile, cosy = pair
            prediction, prediction_error = self._predict_tomorrow(
                comparison_engine, account_info, agile, cosy
            )
            ns.send_notification(self._format_prediction(prediction, prediction_error))
            return self._decide_hop(results, prediction, agile, cosy, phase)

        if phase == "early":
            return self._decide_early_switch(results, account_info)
        return self._decide_final_switch(results, account_info)

    def _agile_cosy_pair(self) -> Optional[Tuple[Tariff, Tariff]]:
        by_id = {tariff.id: tariff for tariff in self.tariffs}
        agile, cosy = by_id.get("agile"), by_id.get("cosy")
        if agile and cosy:
            return agile, cosy
        return None

    def _predict_tomorrow(self, engine: ComparisonEngine, account_info: AccountInfo,
                          agile: Tariff, cosy: Tariff):
        tomorrow = date.today() + timedelta(days=1)
        try:
            if not self.account_manager.device_id:
                raise Exception("No device ID, so consumption history cannot be loaded.")
            history = load_consumption_history(
                self.account_manager.device_id,
                self.account_manager.fetch_consumption_between,
            )
            profile, info = forecast_consumption(
                history,
                tomorrow,
                account_info.region_code,
                latitude=config.LATITUDE,
                longitude=config.LONGITUDE,
            )
        except Exception as e:
            logger.warning(f"Could not predict tomorrow: {e}")
            return None, str(e)

        if not profile:
            return None, info.get("detail") or "No consumption history to predict tomorrow from."

        return {
            "tomorrow": tomorrow,
            "days": info.get("days"),
            "method": info.get("method"),
            "detail": info.get("detail") or "",
            "walk_forward_daily_kwh": info.get("walk_forward_daily_kwh"),
            "agile": engine.price_consumption(agile, account_info.region_code, tomorrow, profile),
            "cosy": engine.price_consumption(cosy, account_info.region_code, tomorrow, profile),
        }, None

    def _format_prediction(self, prediction: Optional[dict], error: Optional[str]) -> str:
        if error or not prediction:
            return f"No prediction for tomorrow. {error or ''}".strip()
        if prediction.get("method") == "ensemble":
            err = prediction.get("walk_forward_daily_kwh")
            err_txt = f" Recent daily error about {err:.2f} kWh." if err is not None else ""
            head = f"Tomorrow, from the half-hour ensemble trained on {prediction['days']} days.{err_txt}"
        else:
            detail = prediction.get("detail") or ""
            head = f"Tomorrow, from the same-slot average of {prediction['days']} days. {detail}".strip()
        lines = [head]
        for key in ("agile", "cosy"):
            priced = prediction[key]
            if priced.is_valid:
                lines.append(
                    f"{priced.tariff.display_name}: £{priced.cost_breakdown.total_cost_pounds:.2f}"
                )
            else:
                lines.append(f"{priced.tariff.display_name}: {priced.error}")
        return "\n".join(lines)

    @staticmethod
    def _comparison_cost(results: ComparisonResult, tariff_id: str) -> Optional[float]:
        current = results.current_tariff_comparison
        if current.tariff.id == tariff_id:
            return current.total_cost
        for comparison in results.alternative_comparisons:
            if comparison.tariff.id == tariff_id:
                return comparison.total_cost
        return None

    def _decide_hop(self, results: ComparisonResult, prediction: Optional[dict],
                    agile: Tariff, cosy: Tariff, phase: str) -> bool:
        ns = self.notification_service
        current_id = results.current_tariff_comparison.tariff.id
        today_saving = saving_pence(
            self._comparison_cost(results, "agile"),
            self._comparison_cost(results, "cosy"),
        )
        today_cosy_cheaper = (
            today_saving is not None and today_saving > config.SWITCH_THRESHOLD
        )

        tomorrow_saving = None
        tomorrow_agile_cheaper = False
        if prediction:
            tomorrow_saving = saving_pence(
                _total(prediction["cosy"]),
                _total(prediction["agile"]),
            )
            tomorrow_agile_cheaper = (
                tomorrow_saving is not None
                and tomorrow_saving > config.FORWARD_SWITCH_THRESHOLD
            )

        targets = [agile if tariff_id == "agile" else cosy
                   for tariff_id in decide_hop(current_id, today_cosy_cheaper, tomorrow_agile_cheaper)]
        ns.send_notification(self._format_hop_plan(
            current_id, today_saving, today_cosy_cheaper, tomorrow_saving,
            tomorrow_agile_cheaper, targets, phase,
        ))
        if phase == "early" or not targets:
            return False
        return self._perform_hop(targets)

    def _format_hop_plan(self, current_id: str, today_saving: Optional[float],
                         today_cosy_cheaper: bool, tomorrow_saving: Optional[float],
                         tomorrow_agile_cheaper: bool, targets: list, phase: str) -> str:
        lines = []
        if today_saving is None:
            lines.append("Today: could not compare Agile and Cosy.")
        elif today_cosy_cheaper:
            lines.append(
                f"Today: Cosy is £{today_saving / 100:.2f} cheaper than Agile "
                f"(over the £{config.SWITCH_THRESHOLD / 100:.2f} bar)."
            )
        elif today_saving > 0:
            lines.append(
                f"Today: Cosy is only £{today_saving / 100:.2f} cheaper, below the "
                f"£{config.SWITCH_THRESHOLD / 100:.2f} bar."
            )
        else:
            lines.append(f"Today: Agile is £{-today_saving / 100:.2f} cheaper than Cosy.")

        if tomorrow_saving is None:
            lines.append("Tomorrow: no Agile prediction, so not joining Agile.")
        elif tomorrow_agile_cheaper:
            lines.append(
                f"Tomorrow: Agile is £{tomorrow_saving / 100:.2f} cheaper than Cosy "
                f"(over the £{config.FORWARD_SWITCH_THRESHOLD / 100:.2f} bar)."
            )
        elif tomorrow_saving > 0:
            lines.append(
                f"Tomorrow: Agile is only £{tomorrow_saving / 100:.2f} cheaper, below the "
                f"£{config.FORWARD_SWITCH_THRESHOLD / 100:.2f} bar."
            )
        else:
            lines.append(f"Tomorrow: Cosy is £{-tomorrow_saving / 100:.2f} cheaper than Agile.")

        if current_id == "agile" and not today_cosy_cheaper:
            if tomorrow_agile_cheaper or tomorrow_saving is None:
                lines.append("Staying on Agile.")
            else:
                lines.append(
                    "Staying on Agile. A Cosy day tomorrow can be switched once it has been metered."
                )
        elif not targets:
            lines.append(f"Staying on {current_id.title()}.")
        else:
            names = " then ".join(tariff.display_name for tariff in targets)
            lines.append(f"Switching to {names}.")

        if phase == "early" and targets:
            lines.append(f"Not switching yet. This runs at {config.EXECUTION_TIME}.")
        return "\n".join(lines)

    def _perform_hop(self, targets: list) -> bool:
        ns = self.notification_service
        if config.DRY_RUN:
            for index, target in enumerate(targets):
                if index:
                    ns.send_notification(
                        "DRY RUN: after the previous switch completed, the next request would be:"
                    )
                self._preview_switch(target)
            return True
        if not QueryService.has_switch_auth():
            ns.send_notification(switch_login_needed_message(), title="Octopus Login Required", batchable=False)
            return False

        submitted = False
        for index, target in enumerate(targets):
            if index:
                ns.send_notification(
                    f"First switch completed. Switching to {target.display_name} for tomorrow."
                )
            status = self._execute_switch(target)
            if status == "failed":
                if index:
                    ns.send_notification(
                        f"Could not switch on to {target.display_name}. "
                        "Tomorrow stays on the tariff just started."
                    )
                return submitted
            submitted = True
            if status != "completed" and index + 1 < len(targets):
                ns.send_notification(
                    f"{target.display_name} did not finish, so the follow-on switch was not started."
                )
                return True
        return True

    def _decide_early_switch(self, results: ComparisonResult, account_info: AccountInfo) -> bool:
        ns = self.notification_service
        bar = early_switch_threshold_pence()
        cheapest_name = results.cheapest_tariff.display_name if results.cheapest_tariff else "none"

        if results.should_switch and results.potential_savings > bar:
            ns.send_notification(
                f"Early check: savings of £{results.potential_savings / 100:.2f} on {cheapest_name} "
                f"are over the £{bar / 100:.2f} early-switch threshold. "
                f"Switching now rather than waiting until {config.EXECUTION_TIME}."
            )
            return self._perform_switch(results, account_info)

        if results.should_switch:
            ns.send_notification(
                f"Early check: savings of £{results.potential_savings / 100:.2f} on {cheapest_name} "
                f"are below the £{bar / 100:.2f} early-switch threshold. "
                f"Waiting until {config.EXECUTION_TIME} to confirm."
            )
            return False

        ns.send_notification(
            f"Early check: {self._format_no_switch_message(results)} "
            f"Rechecking at {config.EXECUTION_TIME}."
        )
        return False

    def _decide_final_switch(self, results: ComparisonResult, account_info: AccountInfo) -> bool:
        ns = self.notification_service
        if results.should_switch:
            ns.send_notification(f"Initiating Switch to {results.cheapest_tariff.display_name}")
            return self._perform_switch(results, account_info)
        ns.send_notification(self._format_no_switch_message(results))
        return False

    def _perform_switch(self, results: ComparisonResult, account_info: AccountInfo) -> bool:
        ns = self.notification_service
        target = results.cheapest_tariff
        if config.DRY_RUN:
            self._preview_switch(target)
            return True
        if not QueryService.has_switch_auth():
            ns.send_notification(switch_login_needed_message(), title="Octopus Login Required", batchable=False)
            return False
        # Submitted counts: the final run must not send the same enrolment again.
        return self._execute_switch(target) != "failed"

    def _preview_switch(self, target_tariff: Tariff) -> None:
        """Run every pre-flight check and show the request, without sending it."""
        ns = self.notification_service
        if not QueryService.has_switch_auth():
            ns.send_notification(
                "DRY RUN: no valid Octopus website session, so a real switch would be skipped."
            )
            return
        try:
            plan = self.account_manager.prepare_tariff_switch(target_tariff)
        except Exception as e:
            ns.send_notification(f"DRY RUN: a real switch would have failed here - {e}")
            return

        ns.send_notification(
            "DRY RUN: not switching today. The request would have been:\n"
            f"journey={plan['journey']} propertyId={plan['property_id']} mpan={plan['mpan']}\n"
            f"product={plan['product_code']} (matches the tariff the comparison chose)"
        )

    @staticmethod
    def _wait_before_accepting(default_wait: int = 120, margin: int = 30) -> int:
        """Wait before accepting the terms, but never past midnight.

        Octopus dates the agreement from the day the terms were accepted.
        """
        now = datetime.now()
        midnight = datetime.combine(now.date() + timedelta(days=1), dt_time())
        remaining = (midnight - now).total_seconds() - margin
        if remaining <= 0:
            logger.warning(f"{(midnight - now).total_seconds():.0f}s until midnight - accepting terms now")
            return 0
        return int(min(default_wait, remaining))

    def _execute_switch(self, target_tariff: Tariff) -> str:
        """Returns 'completed', 'submitted', or 'failed'.

        'submitted' means the enrolment was sent but not confirmed, so a follow-on
        switch must not start and the same enrolment must not be sent again.
        """
        ns = self.notification_service

        enrolment_id = self.account_manager.initiate_tariff_switch(target_tariff)
        if not enrolment_id:
            ns.send_notification("ERROR: Couldn't get enrolment ID")
            return "failed"

        wait_time = self._wait_before_accepting()
        if wait_time:
            ns.send_notification(
                f"Switch requested, enrolment {enrolment_id}. "
                f"Waiting {wait_time}s before accepting the agreement."
            )
            # Give octopus some time to generate the agreement
            time.sleep(wait_time)
        else:
            ns.send_notification(
                f"Switch requested, enrolment {enrolment_id}. Accepting immediately - "
                f"midnight is too close to wait."
            )

        accepted_version = self.account_manager.accept_new_agreement(target_tariff.product_code, enrolment_id)
        ns.send_notification(f"Accepted agreement (v.{accepted_version}) for enrolment {enrolment_id}.")

        state = self.account_manager.wait_for_enrolment_to_complete(enrolment_id)
        if state and (state["agreement_status"] == "COMPLETED" or state["status"] == "COMPLETED"):
            ns.send_notification(f"Verified {target_tariff.display_name}. Enrolment {enrolment_id} completed.")
            return "completed"

        ns.send_notification(
            f"Unable to verify {target_tariff.display_name} after retry. "
            f"Please check your account and emails.\n"
            f"https://octopus.energy/dashboard/new/accounts/{config.ACC_NUMBER}/messages"
        )
        return "submitted"
