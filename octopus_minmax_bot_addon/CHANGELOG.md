## v1.0.16-PL - Pasted Octopus session
The Octopus session is now pasted in by hand, because Octopus has closed every automated route.

## What changed at Octopus

Login moved to `auth.octopus.energy` behind hCaptcha, which serves a full image challenge to any automated browser — Chromium, Firefox, headless or headed alike. None of the credentials the bot can mint substitute for a website session either:

- password grants to `obtainKrakenToken` are refused (`KT-CT-1161`)
- OAuth tokens are rejected by the enrolment API (`OE-0102`)
- customers cannot issue pre-signed scoped tokens (`KT-CT-1111`), including `MANAGE_PRODUCT_SWITCH`
- a Kraken JWT in the `accessToken` cookie is read, but never counts as logged in

Only the `octosession` cookie sets `isLoggedIn`, and only a human clearing the captcha can create one.

## How switching works now

Open **Octopus Session** on the dashboard, log in at octopus.energy as normal, and paste the `octosession` cookie from developer tools (**Application → Cookies**). The bot checks it with Octopus before storing it, so a bad paste fails immediately rather than at 11pm on a switch night. The bare value, `octosession=…`, or a whole cookie header are all accepted.

The session lasts 7 days and cannot be renewed automatically, so the bot warns you at the end of each nightly run once fewer than `SESSION_RENEWAL_LEAD_DAYS` remain, with distinct messages for missing, expiring and expired sessions. Comparisons are unaffected throughout — they run on your API key, and only switching depends on the session.

## Config

`OCTOPUS_EMAIL` and `OCTOPUS_PASSWORD` are **removed**; delete them from `options` and `schema` if you added them for v1.0.15-PL. `SESSION_RENEWAL_LEAD_DAYS` stays and now controls how early you are warned rather than when a renewal runs.

## Notes

Playwright and the stored credentials are gone, which takes Chromium back out of the image: builds are faster, the image is smaller, and the 32-bit architecture limitation from v1.0.15-PL no longer applies. Switching itself is unchanged — the eligibility pre-flight and the product-code guard that keeps fixed tariffs off the table both still run.

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