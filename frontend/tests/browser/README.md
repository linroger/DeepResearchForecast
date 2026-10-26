# Real-browser translation fixture acceptance

This harness mounts the actual production Vue components and API modules against
one guarded real Flask fixture at `http://127.0.0.1:18761`. It never mocks a
frontend module, fulfills an API request, starts a production service, or targets
port 5001. The controlled CJK model proves workflow wiring and source admission,
not real-provider translation quality. The fixture's real exporter uses a
PyMuPDF renderer, so downloaded PDF language and transport are checked here;
Pandoc/XeLaTeX typography remains a separate acceptance check.

## Files and ownership

- `BrowserHarness.vue`, `main.js`, and `index.html` expose seven named tabs:
  dossier, forecast, graph, oasis, world-state, world, and record. The last tab
  mounts the actual completed-record branch of `SimulationView`.
- `build.mjs` builds the harness and all real imports with installed Vite/Vue.
  It forces same-origin API URLs and emits source/output SHA-256 receipts. The
  output must be an empty disposable directory outside the repository; the
  script never deletes an existing output tree.
- `run.mjs` launches installed Google Chrome with a new profile in the evidence
  directory, drives actual buttons, records API requests/responses and errors,
  takes screenshots, and saves/downloads/parses/renders the actual PDFs.
- Parent owns the guarded Flask server, common/source components, and all fixes
  outside this directory. A failure here is reported with receipts first.

## Run

No dependency or browser installation is needed. The runner uses Playwright at
`/opt/homebrew/lib/node_modules/mcp-jobs/node_modules/playwright`, Chrome at
`/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`, and installed
Poppler tools at `/opt/homebrew/bin/`.

```sh
node frontend/tests/browser/build.mjs --out-dir /private/tmp/<new-run>/www
# Parent starts backend/tests/fixtures/translation_browser_server.py under its
# required isolated interpreter/guard, with that static directory and port 18761.
node frontend/tests/browser/run.mjs --evidence-dir /private/tmp/<new-run>/browser
```

Use `--smoke` for read-only mounting/screenshots of all seven surfaces. Use
`--surfaces dossier,forecast` to restrict a debugging run. `--headed` is optional;
headless Chromium is the default. `--budget-ms 600000` is the default total budget.
Evidence directories must be new, so reruns cannot overwrite earlier failures.
Fresh full acceptance requires a fresh server root: successful translations are
persisted by the real service and should not be deleted merely to rerun tests.

## Server contract used

`GET /__fixture/bootstrap` returns `{dossier, graph, ids:{pipeline, report, oasis,
world, record}}`. The graph contains 1,000 node summaries plus one edge fact.
Real API GET/POST resource routes must already be mounted.

The only fixture control POSTs used are:

```json
{"action":"fail_provider","value":true}
{"action":"fail_provider","value":false}
{"action":"delay_provider","seconds":0.15}
{"action":"delay_provider","seconds":0.015}
{"action":"fail_get","path":"<exact translation GET path>","count":1}
```

`GET /__fixture/receipt` supplies provider call/failure counts, durable tasks,
request receipts, seven blocked server negative controls, and guard/source-drift
state. The runner does not call generic job retry/cancel, supply job identity as
an authorization assertion, or shut down the parent-owned server.

Each full surface flow captures source prose, injects a provider failure, clicks
its real translation control, captures the enabled retry, resumes explicitly,
injects one subsequent translation GET failure, captures reconnect feedback,
checks translated body/provenance/record text, and restores source language.
Graph acceptance checks all 1,001 entries and exactly five successful
continuation POSTs after retry. Dossier and Forecast each download primary
English and admitted Mandarin PDFs, checking language labels, source digest in
the request, MIME, filename, PDF magic, extracted language/body text, replacement
glyph absence, and a rendered first-page PNG.

## Evidence and interpretation

`result.json` reports per-surface results, downloaded file SHA-256 hashes, source
drift, and semantic limits. `passed` is the executed browser-case outcome;
`acceptance_ready` additionally requires all seven full cases and no source/build
drift. Intermediate debug passes against a changing checkout cannot satisfy the
frozen acceptance gate. Smoke passes do not prove translation or download flows.

`network.json` and `network/*.json` retain requests and JSON responses.
`screenshots/` contains real Chromium screenshots and matching visible-text
captures. `downloads/` contains the actual PDFs and extracted text; `pdf-pages/`
contains their first-page renders. `trace.zip`, `console.json`, `page-errors.json`,
`browser-events.json`, and server receipts preserve failure context.

Chromium routing allows only the exact fixture origin; service workers and
WebSockets are blocked and background network/DNS features are disabled. An
explicit empty-payload fetch to `https://translation-fixture.invalid/blocked`
must be intercepted, fail, and receive no response. This expected negative
control is separated from unexpected blocked requests and page errors. These
browser controls are not a host-wide firewall.

## Independent server and browser per surface

Use `run-all.mjs --evidence-dir /private/tmp/<new-suite> --static-dir /private/tmp/<build>/www` for final acceptance. It starts the guarded Flask fixture itself, uses a new backend data root and Chrome profile for every surface, and preserves every failure and shutdown receipt. Port18761 must be free initially. A surface failure cannot close another case or reuse its accepted translations. `--surfaces graph` selects one debugging case without waiving the others.

The host sent external Quit AppleEvents to installed Google Chrome during two graph runs; those failures remain recorded. The final runner therefore also accepts `--browser-executable /absolute/path/to/headless_shell`. A matching Playwright Chromium headless shell was provisioned only under the disposable evidence directory using the already installed Playwright CLI. No repository dependencies or user browser data were changed. The same origin allowlist, negative control, source hashes, real APIs, screenshots and five-page assertion apply to either browser executable.
