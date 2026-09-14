## v1.0.15-PL - Browser login for tariff switching
Switching works again, through the same enrolment API the Octopus website uses.

Octopus refuses `startOnboardingProcess` for every customer credential with `KT-CT-1111`, including OAuth tokens that carry `manage:product-enrolment`. Their website goes through `/smart/api/enrolment/` instead, and that accepts only a website login session. So the bot logs in with a real browser and keeps the session alive itself.

## Signing in

Open **Octopus Login** on the dashboard, enter your Octopus email and password, and the bot signs in headlessly and stores the session. There is nothing to copy out of developer tools and no tokens to paste. Save the credentials (or set `OCTOPUS_EMAIL` / `OCTOPUS_PASSWORD`) and it renews itself.

The session lasts 7 days and Octopus never extends it, so the bot checks at the end of each nightly run and signs in again once fewer than `SESSION_RENEWAL_LEAD_DAYS` remain. The outcome arrives in the same notification batch as your comparison results, and a failure still leaves that many nights to fix it.

## Fixed tariffs stay off the table

The enrolment API is journey-based, so Octopus decides which product a journey currently sells and that is sometimes a fixed-term one. Before enrolling, the bot compares the product Octopus offers against the product your comparison chose and refuses to continue if they differ. It also checks eligibility first, so an account with an open enrolment stops cleanly rather than firing a request.

`DRY_RUN` now runs every one of those checks and reports the request it would have sent.

## Config

New optional settings: `OCTOPUS_EMAIL`, `OCTOPUS_PASSWORD`, `SESSION_RENEWAL_LEAD_DAYS` (default 2). `OAUTH_CLIENT_ID` is gone.

## Notes

The OAuth client, session store and token paste flow are removed. Your API key still handles comparisons and accepting terms. The image now ships Playwright with Chromium, so it is larger and needs amd64 or arm64 — 32-bit `armhf` and `armv7` have no browser builds and cannot switch.

## v1.0.9 - v1.0.9
## What's Changed
* Update Addon Configuration to v1.0.8 by @github-actions[bot] in https://github.com/eelmafia/octopus-minmax/pull/163
* Incorrect port number in readme.md by @Morph-Ed in https://github.com/eelmafia/octopus-minmax/pull/165
* Add new tariff option by @eelmafia in https://github.com/eelmafia/octopus-minmax/pull/177

## New Contributors
* @Morph-Ed made their first contribution in https://github.com/eelmafia/octopus-minmax/pull/165

**Full Changelog**: https://github.com/eelmafia/octopus-minmax/compare/v1.0.8...v1.0.9

## v1.0.8 - v1.0.8
## What's Changed
* Update Addon Configuration to v1.0.7 by @github-actions[bot] in https://github.com/eelmafia/octopus-minmax/pull/159
* Update SWITCH_THRESHOLD type to int in config.yaml (fixes #160) by @DJBenson in https://github.com/eelmafia/octopus-minmax/pull/161
* Log notifications regardless regardless if apprise exists by @eelmafia in https://github.com/eelmafia/octopus-minmax/pull/162


**Full Changelog**: https://github.com/eelmafia/octopus-minmax/compare/v1.0.7...v1.0.8

## v1.0.7 - v1.0.7
## What's Changed
* Update Addon Configuration to v1.0.6 by @github-actions[bot] in https://github.com/eelmafia/octopus-minmax/pull/157
* Fix indents by @eelmafia in https://github.com/eelmafia/octopus-minmax/pull/158


**Full Changelog**: https://github.com/eelmafia/octopus-minmax/compare/v1.0.6...v1.0.7

## v1.0.6 - v1.0.6
## What's Changed
* Update Addon Configuration to v1.0.5 by @github-actions[bot] in https://github.com/eelmafia/octopus-minmax/pull/148
* Restore legacy:true to config.yaml (fixes #141) by @DJBenson in https://github.com/eelmafia/octopus-minmax/pull/154
* Update notification_service.py by @DJBenson in https://github.com/eelmafia/octopus-minmax/pull/156


**Full Changelog**: https://github.com/eelmafia/octopus-minmax/compare/v1.0.5...v1.0.6

## v1.0.5 - v1.0.5
## What's Changed
* Update Addon Configuration to v1.0.4 by @github-actions[bot] in https://github.com/eelmafia/octopus-minmax/pull/146
* Ingress fixes by @DJBenson in https://github.com/eelmafia/octopus-minmax/pull/147


**Full Changelog**: https://github.com/eelmafia/octopus-minmax/compare/v1.0.4...v1.0.5

## v1.0.4 - v1.0.4
## What's Changed
* Update Addon Configuration to v1.0.3 by @github-actions[bot] in https://github.com/eelmafia/octopus-minmax/pull/143
* Add missing authentication fields by @DJBenson in https://github.com/eelmafia/octopus-minmax/pull/145


**Full Changelog**: https://github.com/eelmafia/octopus-minmax/compare/v1.0.3...v1.0.4

## v1.0.3 - v1.0.3
## What's Changed
* Update Addon Configuration to v1.0.1 by @github-actions[bot] in https://github.com/eelmafia/octopus-minmax/pull/138
* Update Addon Configuration to v1.0.2 by @github-actions[bot] in https://github.com/eelmafia/octopus-minmax/pull/139
* Fix web dashboard paths in HA by @eelmafia in https://github.com/eelmafia/octopus-minmax/pull/142


**Full Changelog**: https://github.com/eelmafia/octopus-minmax/compare/v1.0.2...v1.0.3

## v1.0.2 - v1.0.2
**Full Changelog**: https://github.com/eelmafia/octopus-minmax/compare/v1.0.1...v1.0.2
## v1.0.1 - v1.0.1
## What's Changed
* Update Addon Configuration to v1.0.0 by @github-actions[bot] in https://github.com/eelmafia/octopus-minmax/pull/136
* Fix path in workflow script by @eelmafia in https://github.com/eelmafia/octopus-minmax/pull/137


**Full Changelog**: https://github.com/eelmafia/octopus-minmax/compare/v1.0.0...v1.0.1

## v1.0.0 - v1.0.0
## What's Changed
* Refactor code and add web UI by @eelmafia in https://github.com/eelmafia/octopus-minmax/pull/128


**Full Changelog**: https://github.com/eelmafia/octopus-minmax/compare/v0.8.5...v1.0.0

## v0.8.5 - v0.8.5
## What's Changed
* Improve cosy regex to avoid fixed tariff by @eelmafia in https://github.com/eelmafia/octopus-minmax/pull/119


**Full Changelog**: https://github.com/eelmafia/octopus-minmax/compare/v0.8.4...v0.8.5

## v0.8.4 - v0.8.4
## What's Changed
* Update Addon Configuration to v0.8.3 by @github-actions[bot] in https://github.com/eelmafia/octopus-minmax/pull/112
* Fix switch threshold type by @eelmafia in https://github.com/eelmafia/octopus-minmax/pull/115


**Full Changelog**: https://github.com/eelmafia/octopus-minmax/compare/v0.8.3...v0.8.4

## v0.8.3 - v0.8.3
## What's Changed
* Add config entry/environment variable for switch threshold, defaults to 2p by @DJBenson in https://github.com/eelmafia/octopus-minmax/pull/111

## New Contributors
* @DJBenson made their first contribution in https://github.com/eelmafia/octopus-minmax/pull/111

**Full Changelog**: https://github.com/eelmafia/octopus-minmax/compare/v0.8.2...v0.8.3

## v0.8.2 - v0.8.2
## What's Changed
* Update tariff.py by @adyoull in https://github.com/eelmafia/octopus-minmax/pull/99


**Full Changelog**: https://github.com/eelmafia/octopus-minmax/compare/v0.8.1...v0.8.2

## v0.8.1 - v0.8.1
## What's Changed
* Replace gql with requests by @eelmafia in https://github.com/eelmafia/octopus-minmax/pull/88

## New Contributors

**Full Changelog**: https://github.com/eelmafia/octopus-minmax/compare/v0.8.0...v0.8.1

## v0.8.0 - v0.8.0
## What's Changed
* Update README.md by @adyoull in https://github.com/eelmafia/octopus-minmax/pull/75
* Add HA Addon Config by @joeShuff in https://github.com/eelmafia/octopus-minmax/pull/76
* Add option to batch notifications by @lilongwe in https://github.com/eelmafia/octopus-minmax/pull/77
* Fix timeout errors by @eelmafia in https://github.com/eelmafia/octopus-minmax/pull/84


**Full Changelog**: https://github.com/eelmafia/octopus-minmax/compare/v0.7.2...v0.8.0

## Initial Release

This is the initial release of Octopus MinMax Bot