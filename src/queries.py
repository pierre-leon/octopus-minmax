token_mutation = """
mutation obtainKrakenToken($input: ObtainJSONWebTokenInput!) {
  obtainKrakenToken(input: $input) {
    token
    refreshToken
    refreshExpiresIn
    payload
  }
}
"""

accept_terms_query = """mutation {{
    acceptTermsAndConditions(input: {{
        accountNumber: "{account_number}",
        enrolmentId: "{enrolment_id}",
        termsVersion: {{
            versionMajor: {version_major},
            versionMinor: {version_minor}
        }}
    }})
    {{
    acceptedVersion
  }}
}}"""

get_terms_version_query = """query {{
    termsAndConditionsForProduct(productCode: "{product_code}") {{
        name
        version
    }}
}}"""

# Live half-hours from the home device. A start older than 30 days is rejected
# (KT-GB-4051). Longer history uses measurements_query, which is what the
# usage page requests. A week of half-hours fits in one page.
consumption_query = """query {{
    smartMeterTelemetry(
        deviceId: "{device_id}"
        grouping: HALF_HOURLY
        start: "{start_date}"
        end: "{end_date}"
    ) {{
    readAt
    consumptionDelta
    costDeltaWithTax
  }}
}}"""

account_query = """query{{
    account(
        accountNumber: "{acc_number}"
    ) {{
    electricityAgreements(active: true) {{
        validFrom
        validTo
        meterPoint {{
            meters(includeInactive: false) {{
                smartDevices {{
                    deviceId
                }}
            }}
            mpan
            direction
        }}
        tariff {{
            __typename
            ... on HalfHourlyTariff {{
                id
                displayName
                fullName
                productCode
                tariffCode
                standingCharge
            }}
            ... on StandardTariff {{
                id
                displayName
                fullName
                productCode
                tariffCode
                standingCharge
            }}
            ... on DayNightTariff {{
                id
                displayName
                fullName
                productCode
                tariffCode
                standingCharge
            }}
            ... on ThreeRateTariff {{
                id
                displayName
                fullName
                productCode
                tariffCode
                standingCharge
            }}
            ... on FourRateEvTariff {{
                id
                displayName
                fullName
                productCode
                tariffCode
                standingCharge
            }}
            ... on PrepayTariff {{
                id
                displayName
                fullName
                productCode
                tariffCode
                standingCharge
            }}
        }}
        }}
    }}
}}"""
measurements_query = """query getMeasurements(
    $accountNumber: String!
    $first: Int!
    $utilityFilters: [UtilityFiltersInput!]
    $startAt: DateTime
    $endAt: DateTime
    $timezone: String
    $cursor: String
) {
    account(accountNumber: $accountNumber) {
        properties {
            measurements(
                first: $first
                utilityFilters: $utilityFilters
                startAt: $startAt
                endAt: $endAt
                timezone: $timezone
                after: $cursor
            ) {
                edges {
                    node {
                        value
                        unit
                        ... on IntervalMeasurementType {
                            startAt
                            endAt
                            durationInSeconds
                        }
                    }
                }
                pageInfo {
                    hasNextPage
                    endCursor
                }
            }
        }
    }
}"""

enrolment_query = """query {{
    productEnrolments(accountNumber: "{acc_number}") {{
        id
        status
        product {{
            code
            displayName
        }}
    stages {{
      name
      status
      steps {{
        displayName
        status
        updatedAt
      }}
    }}
  }}
}}"""

# startOnboardingProcess used to start switches, but Octopus now refuses it for every
# customer credential (KT-CT-1111), including OAuth tokens carrying manage:product-enrolment.
# Switches go through the website's enrolment API instead - see octopus_web.py.