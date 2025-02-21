import os

from playwright.sync_api import sync_playwright
import requests
from datetime import datetime, date
from gql import gql, Client
from gql.transport.aiohttp import AIOHTTPTransport
import time
import traceback
import config
import tariff
from account_info import AccountInfo
from queries import *
from tariff import Tariff

gql_transport = None
gql_client = None

tariffs = []


def send_discord_message(content):
    print(content)
    if config.DISCORD_WEBHOOK is not None:
        content = f"`{content}`"
        data = {
            "content": content
        }
        requests.post(config.DISCORD_WEBHOOK, json=data)


def accept_new_agreement():
    query = gql(enrolment_query.format(acc_number=config.ACC_NUMBER))
    result = gql_client.execute(query)
    try:
        enrolment_id = next(entry['id'] for entry in result['productEnrolments'] if entry['status'] == "IN_PROGRESS")
    except StopIteration:
        # Strangely sometimes the enrolment skips 'IN_PROGRESS' and just auto-accepts, so we check if it's completed with today's date
        today = datetime.now().date()

        for entry in result['productEnrolments']:
            for stage in entry['stages']:
                if stage['name'] == 'post-enrolment':
                    last_step_date = datetime.fromisoformat(
                        stage['steps'][-1]['updatedAt'].replace('Z', '+00:00')).date()
                    if last_step_date == today and stage['status'] == 'COMPLETED':
                        send_discord_message("Post-enrolment automatically completed with today's date.")
                        return

        raise Exception("ERROR: No completed post-enrolment found today and no in-progress enrolment.")
    query = gql(accept_terms_query.format(account_number=config.ACC_NUMBER, enrolment_id=enrolment_id))
    result = gql_client.execute(query)


def get_acc_info() -> AccountInfo:
    query = gql(account_query.format(acc_number=config.ACC_NUMBER))
    result = gql_client.execute(query)

    tariff_code = next(agreement['tariff']['tariffCode']
                       for agreement in result['account']['electricityAgreements']
                       if 'tariffCode' in agreement['tariff'])
    region_code = tariff_code[-1]
    device_id = next(device['deviceId']
                     for agreement in result['account']['electricityAgreements']
                     for meter in agreement['meterPoint']['meters']
                     for device in meter['smartDevices']
                     if 'deviceId' in device)
    curr_stdn_charge = next(agreement['tariff']['standingCharge']
                            for agreement in result['account']['electricityAgreements']
                            if 'standingCharge' in agreement['tariff'])

    matching_tariff = next((tariff for tariff in tariffs if tariff.matches(tariff_code)), None)
    if matching_tariff is None:
        raise Exception(f"ERROR: Found no matching tariff for code {tariff_code}")

    # Get consumption for today
    result = gql_client.execute(
        gql(consumption_query.format(device_id=device_id, start_date=f"{date.today()}T00:00:00Z",
                                     end_date=f"{date.today()}T23:59:59Z")))
    consumption = result['smartMeterTelemetry']

    return AccountInfo(matching_tariff, curr_stdn_charge, region_code, consumption)


def get_potential_tariff_rates(tariff, region_code):
    all_products = rest_query(f"{config.BASE_URL}/products")
    tariff_code = next(
        product["code"] for product in all_products['results']
        if product['display_name'] == tariff
        and product['direction'] == "IMPORT"
        and product['brand'] == "OCTOPUS_ENERGY"
    )
    # Residential tariffs are always E-1R (i think, lol)    
    product_code = f"E-1R-{tariff_code}-{region_code}"

    today = date.today()
    unit_rates = rest_query(
        f"{config.BASE_URL}/products/{tariff_code}/electricity-tariffs/{product_code}/standard-unit-rates/?period_from={today}T00:00:00Z&period_to={today}T23:59:59Z")
    standing_charge = rest_query(
        f"{config.BASE_URL}/products/{tariff_code}/electricity-tariffs/{product_code}/standing-charges/")

    return standing_charge['results'][0]['value_inc_vat'], unit_rates['results']


def rest_query(url):
    response = requests.get(url)
    if response.ok:
        data = response.json()
        return data
    else:
        raise Exception(f"ERROR: rest_query failed querying `{url}` with {response.status_code}")


def calculate_potential_costs(consumption_data, rate_data):
    period_costs = []
    for consumption in consumption_data:
        read_time = consumption['readAt'].replace('+00:00', 'Z')
        matching_rate = next(
            rate for rate in rate_data
            if rate['valid_from'] <= read_time <= rate['valid_to']
        )

        consumption_kwh = float(consumption['consumptionDelta']) / 1000
        cost = float("{:.4f}".format(consumption_kwh * matching_rate['value_inc_vat']))

        period_costs.append({
            'period_end': read_time,
            'consumption_kwh': consumption_kwh,
            'rate': matching_rate['value_inc_vat'],
            'calculated_cost': cost,
        })
    return period_costs


def get_token():
    transport = AIOHTTPTransport(url=f"{config.BASE_URL}/graphql/")
    client = Client(transport=transport, fetch_schema_from_transport=True)
    query = gql(token_query.format(api_key=config.API_KEY))
    result = client.execute(query)
    return result['obtainKrakenToken']['token']


def switch_tariff(target_tariff):
    with sync_playwright() as playwright:
        browser = None
        try:
            browser = playwright.chromium.launch(
                headless=True)
        except Exception as e:
            print(e)  # Should print out if its not working
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()
        page.goto("https://octopus.energy/")
        page.wait_for_timeout(1000)
        page.get_by_label("Log in to my account").click()
        page.wait_for_timeout(1000)
        page.get_by_placeholder("Email address").click()
        page.wait_for_timeout(1000)
        # replace w env
        page.get_by_placeholder("Email address").fill(config.OCTOPUS_LOGIN_EMAIL)
        page.wait_for_timeout(1000)
        page.get_by_placeholder("Email address").press("Tab")
        page.wait_for_timeout(1000)
        page.get_by_placeholder("Password").fill(config.OCTOPUS_LOGIN_PASSWD)
        page.wait_for_timeout(1000)
        page.get_by_placeholder("Password").press("Enter")
        page.wait_for_timeout(1000)
        # replace with env
        page.goto(f"https://octopus.energy/smart/{target_tariff.lower()}/sign-up/?accountNumber={config.ACC_NUMBER}")
        page.wait_for_timeout(10000)
        page.locator("section").filter(has_text="Already have a SMETS2 or “").get_by_role("button").click()
        page.wait_for_timeout(10000)
        # check if url has success
        context.close()
        browser.close()


def verify_new_agreement():
    query = gql(account_query.format(acc_number=config.ACC_NUMBER))
    result = gql_client.execute(query)
    today = datetime.now().date()
    valid_from = next(datetime.fromisoformat(agreement['validFrom']).date()
                      for agreement in result['account']['electricityAgreements']
                      if 'validFrom' in agreement)

    # For some reason, sometimes the agreement has no end date so I'm not not sure if this bit is still relevant?
    # valid_to = datetime.fromisoformat(result['account']['electricityAgreements'][0]['validTo']).date()
    # next_year = valid_from.replace(year=valid_from.year + 1)
    return valid_from == today


def setup_gql(token):
    global gql_transport, gql_client
    gql_transport = AIOHTTPTransport(url=f"{config.BASE_URL}/graphql/", headers={'Authorization': f'{token}'})
    gql_client = Client(transport=gql_transport, fetch_schema_from_transport=True)


def compare_and_switch():
    welcome_message = "DRY RUN: " if config.DRY_RUN else ""
    welcome_message += "Octobot on. Starting comparison of today's costs..."
    send_discord_message(welcome_message)

    costs = {}

    account_info = get_acc_info()
    current_tariff = account_info.current_tariff

    total_curr_cost = sum(float(entry['costDeltaWithTax']) for entry in account_info.consumption) \
                      + account_info.standing_charge

    costs[current_tariff] = total_curr_cost

    for tariff in tariffs:
        if tariff == current_tariff:
            continue  # Skip if you're already on that tariff

        (potential_std_charge, potential_unit_rates) = \
            get_potential_tariff_rates(tariff.api_display_name, account_info.region_code)
        potential_costs = calculate_potential_costs(account_info.consumption, potential_unit_rates)
        total_potential_calculated = sum(period['calculated_cost'] for period in potential_costs) + potential_std_charge

        costs[tariff.id] = total_potential_calculated

    summary = f"Current tariff {current_tariff.display_name}: £{total_curr_cost / 100:.2f}\n"
    for tariff in costs.keys():
        cost = costs[tariff]
        summary += f"Potential cost on {tariff}: £{cost / 100:.2f}\n"

    ##TODO: Filter out not switchable tariffs

    # Find the cheapest tariffs that is in the list and switchable
    curr_cost = costs.get(current_tariff, float('inf'))
    cheapest_tariff = min(costs, key=costs.get)
    cheapest_cost = costs[cheapest_tariff]

    if cheapest_tariff == current_tariff:
        send_discord_message(f"You are already on the cheapest tariff: {cheapest_tariff.display_name} at £{cheapest_cost / 100:.2f}")
        return

    savings = curr_cost - cheapest_cost

    # 2p buffer because cba
    if savings < 2:
        switch_message = "{summary}\nInitiating Switch to {new_tariff}".format(summary=summary,
                                                                               new_tariff=cheapest_tariff.display_name)
        send_discord_message(switch_message)

        if config.DRY_RUN:
            dry_run_message = "DRY RUN: Not going through with switch today."
            send_discord_message(dry_run_message)
            return None

        switch_tariff(cheapest_tariff.url_tariff_name)
        send_discord_message("Tariff switch requested successfully.")
        # Give octopus some time to generate the agreement
        time.sleep(60)
        accept_new_agreement()
        send_discord_message("Accepted agreement. Switch successful.")

        if verify_new_agreement():
            send_discord_message("Verified new agreement successfully. Process finished.")
        else:
            send_discord_message("Unable to accept new agreement. Please check your emails.")
    else:
        send_discord_message("Not switching today. " + summary)


def load_tariffs_from_ids(tariff_ids: str):
    # Convert the input string into a set of lowercase tariff IDs
    requested_ids = set(tariff_ids.lower().split(","))

    # Get all predefined tariffs from the Tariffs class
    all_tariffs = tariff.TARIFFS

    # Match requested tariffs to predefined ones
    matched_tariffs = []
    for tariff_id in requested_ids:
        matched = next((tariff for t in all_tariffs if t.id == tariff_id), None)

        if matched is not None:
            matched_tariffs.append(matched)
        else:
            send_discord_message(f"Warning: No tariff found for ID '{tariff_id}'")

    return matched_tariffs


def run_tariff_compare():
    try:
        setup_gql(get_token())
        load_tariffs_from_ids(config.TARIFFS)
        if gql_transport is not None and gql_client is not None:
            compare_and_switch()
        else:
            raise Exception("ERROR: setup_gql has failed")
    except Exception:
        send_discord_message(traceback.format_exc())


load_tariffs_from_ids(config.TARIFFS)
