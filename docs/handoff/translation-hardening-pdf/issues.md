# Translation redesign issue disposition

The approved user task remains in progress until browser/native-PDF acceptance, current-source integration, activation and scoped delivery finish. The detailed red/green histories are in review-core.md and the worker notes.

| Issue | State | Evidence / disposition |
|---|---|---|
| Generic review errors, unnecessary retranslations and lost restart progress | Resolved in scoped core | 108-case independent freeze, atomic translation/review checkpoints, scoped seeds and original missing-section fixtures. |
| Cross-section link/footnote loss, returned-batch crash loss, action races, timeout accounting and input-budget mismatch | Resolved in scoped core | Independent regressions transferred to backend/tests/test_translation_core_review_regressions.py and parent recovery/action tests. |
| Overlay full coverage, visible-source authority, refresh preservation, delayed duplicate POST and crash/retry generations | Resolved in scoped overlay | 80-case owned final gate, source hash freeze and independent review. |
| Report/research generation publication, snapshot PDF export and mixed-script PDF admission | Scoped fixtures pass; real-report PDF acceptance open | 347-case frozen gate and real renderer follow-up; final native/browser observations remain separate. |
| Executive-brief reader still assumes a mutable translation sidecar | Resolved | Admitted generation brief/digest readers and caches verified by current report/brief suite. |
| Static export reader still assumes old translation sidecars | Resolved | Admitted generation readers and refresh discovery pass58independent/consumer cases, with2pre-existing demo-asset checks excluded. No static site publication is requested. |
| Pre-existing demo asset manifests reference absent local files | Outside this task; recorded for follow-up | Existing unchanged test_export_demo_site_data.py fails its two whole-bundle asset checks: docs/demos/ev-2035/research_log.txt and docs/demos/datacenter-2030/charts/binary_forecast_dotplot.png are absent and not tracked at those paths. This task has not deleted or rewritten demo assets. The translated-generation consumer gate excludes those two fixture-availability checks explicitly; it does not claim the site bundles are complete. |

Follow-up prompt for the unrelated demo issue: Restore or regenerate the existing demo bundles from their authoritative saved runs, validate every manifest hash and link, and publish only after a separate site-delivery request. Do not fabricate missing logs/charts or alter manifest expectations merely to pass tests.

Required live acceptance issue: English and Mandarin PDF downloads for report_8f0bea34ec96 return503 after successful Pandoc rendering. The corresponding live Mandarin translation is complete and source-preserving. Native verifier is investigating exact private copies; preserve factual/content gates and correct a demonstrated render/extraction mismatch, rather than suppressing the audit.

Closure: ActualcopperPDFlayout/URIissues arefixed and independentlyverified. LiveEnglish/Mandarin endpoints nowreturn200,35/28pages withsiximages each; translationswere notrerun. The unrelatedstatic-demo assetissue is filed as https://github.com/linroger/DeepResearchForecast/issues/9 in the activeconfiguredrepository. Attempting issuecreation on archivedorigin returned403; no archive/settingschange wasmade.
