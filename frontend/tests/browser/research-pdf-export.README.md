# Research PDF browser acceptance

This harness mounts the production `DossierViewer.vue` and `ForecastReport.vue`. The only wrapper controls select a fixture or unmount its component. PDF buttons, API clients, polling, request guards, and browser downloads are unchanged production code.

Run from the worktree's `frontend` directory, using an existing Node installation:

```sh
node tests/browser/research-pdf-export.mjs --check
node --test tests/browser/research-pdf-export.guard.test.mjs
node tests/browser/research-pdf-export.mjs --api-url http://127.0.0.1:PORT --output-dir /tmp/research-pdf-browser-acceptance
```

The parent must first start its isolated `backend/tests/fixtures/research_pdf_browser_server.py`. Use that process's emitted URL and fresh fixture storage. This runner never starts Flask, providers, or shared application services. It creates and closes its own loopback Vite server and temporary-profile Chromium instance. Playwright comes from existing local/bundled packages; `--playwright-module` and `--browser-executable` permit explicit overrides. No dependency or browser installation is performed. `--check` compiles the real Vue components and checks Chromium without contacting any backend; it is not end-to-end acceptance.

## Fixture server read-only endpoints

The server owns fixture source bytes and must return those same bytes through these read-only display APIs. No browser export response may be fabricated.

| GET route | Minimum JSON response |
|---|---|
| `/api/research/pipe_pdf_en/dossier`, `/api/research/pipe_pdf_zh/dossier` | `{success:true,data:{report:"complete fixture Markdown",has_report:true,sealed:true,actors:null,sources:[],timeline:null,charts:[]}}` |
| `/api/report/report_pdf_en`, `/api/report/report_pdf_zh` | `{success:true,data:{report_id:"matching id",status:"completed",markdown_content:"complete fixture Markdown",translation_status:{source_lang:"en or zh"}}}` |
| `/api/report/<id>/viz-manifest` | `{success:true,data:[],count:0}` |
| `/api/report/<id>/forecast` (may carry `?lang=en` or `?lang=zh`) | `{success:true,data:{report_id:"matching id",forecast:null,available:false}}` |
| `/api/report/<id>/official-data` (may carry `?lang=en` or `?lang=zh`) | `{success:true,data:{report_id:"matching id",available:false,indicators:[]}}` |

If fixture Markdown contains image references, its existing source-specific chart GET must serve the corresponding image read-only. Empty structured-display responses do not remove body charts from the actual PDF source snapshot. The source should have an H1 title; downloaded text must contain it. The two Mandarin primaries should contain at least five extractable Han characters. All four exports request `{lang:null}`; source language comes from the real server snapshot, not the requested URL.

The real export endpoints are the contract's POST `/api/research/<id>/dossier/pdf-export` and POST `/api/report/<id>/pdf-export`, corresponding status GETs, and completed-job download GETs. They must invoke the actual job service, export agent, and native renderer, with only model transport controlled by the fixture server. No extra receipt endpoint or test-only response fields are required.

## Eight checks and output

1. Four cases click each actual resource's PDF button twice synchronously. Each must issue one POST, exhibit a busy/disabled UI and a pending real backend job, then download the completed PDF. Each case checks kind, resource ID, primary selection, actual language, source digest, source title and extractable language text. Browser PDF SHA-256 must match an independent GET of the same completed job's renewed-admission download route.
2. Four cases rejoin the completed English dossier/forecast jobs and change resource or unmount while a real POST response is delayed at the browser boundary. Releasing those unchanged real responses must not trigger status polling/download for the old resource. The replacement component must remain usable. These cases test observer invalidation, not backend cancellation or canonical source mutation.

The output directory holds `receipt.json`, each downloaded PDF, extracted text, completion/failure screenshots, and Playwright traces. Requests, job states, UI observations, source/PDF hashes, and failures are retained per case. External requests and writes outside the four fixture PDF-start routes are blocked before dispatch. Delayed API fetches cannot follow redirects; stale cases validate the held completed generation and await delivery settlement. A failed delivery is accepted only with a matching browser cancellation event, and no subsequent old-job status or download request is allowed. A fresh backend fixture directory is required for the four pending-job cases; rerunning against already-completed fixture jobs intentionally fails that pending-work assertion.

Limitations are explicit: primary-language cases do not prove translated-variant admission, native content/layout review remains the real renderer/agent's responsibility, and controlled model transport provides no live-provider quality evidence. Production source/server tamper, interrupted-worker recovery, and provider capability acceptance remain with the parent suites.
