# Activation issues

## OS-ACT-1 — Active checkout contains only the Oddsense study

Status: Closed on 2026-10-22.

The original implementation was merged into main, but the running application used the dirty `claude-reflexive-world-state-model` checkout at `495000e`. The approved provider, research tools, evidence/report consumers and frontend panel were reconciled into that checkout. Its branch, HEAD, staging and peer work were preserved. The deployed bridge now matches the active source, and the restarted idle backend reports both tools through its real preflight endpoint. See `acceptance.json`, `activation.json` and `gather-proof.json`.

## OS-ACT-2 — NewsAPI cannot be reached from the current host

Status: Open; environment/source availability, not an authentication verdict.

One bounded native NewsAPI request on 2026-10-22 returned `timeout / transport_timeout` and zero items. The request used the privately configured credential and no model or saved run. A separate credential-free TCP/TLS diagnostic timed out connecting to `newsapi.org:443`; DNS resolution succeeded and no system/environment proxy was configured. The failure occurred before an authenticated response, so neither credential validity nor account entitlement has been established. The first receipt is retained in `live-compatibility.json`.

The workflow preserves the timeout and missing coverage explicitly, continues with its other sources, and does not interpret missing news as neutral evidence. No unchanged-key retry loop, larger timeout, bypassed TLS or speculative proxy was introduced.

Closure: establish working outbound access to `newsapi.org:443`, then run `scripts/oddsense_live_probe.py` once with an inherited private key and a fresh private output directory. Require an actual provider response; record its status/items separately from the controlled end-to-end acceptance. No paid-model forecast is required to close this source-availability check.
