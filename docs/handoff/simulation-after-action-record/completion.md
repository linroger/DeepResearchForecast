# Simulation/forecast boundary completion

Status: implementation verified; source delivery in progress on `codex/simulation-report-boundary`, recovered from Claude integration commit `579c1acf`.

## Architectural decision

The forecast is an evidence-based estimate about an unknown future. Its historical/current claims require sources, and its probabilities require explicit assumptions and calibration; the future outcome itself cannot be presented as an observed fact. The simulation is a conditional exploration of mechanisms, interactions and paths. Fidelity to its inputs and committed trajectory is testable, but this is not evidence of real-world truth or calibrated predictive skill.

The application therefore produces two related deliverables: a public-only Simulation After-Action Record at Stage 5, and the evidence-based forecast report at Stage 6. One deterministic, visibly labelled report section describes the simulation under `diagnostic_only`. Under `no_update`, that section and its links/charts disappear; the separate Simulation tab remains available. Simulated shares are labelled separately from forecast probabilities and cannot update them. A future probability-updating policy would require prospective, held-out evaluation against a research-only baseline.

## Actual workflow

| Stage | Authority and output | Downstream role |
|---|---|---|
| Research | Prompt, research questions, retrieved sources and dated observations produce the dossier, source ledger and structured forecasting inputs. | Supplies direct evidence to ontology, actor selection, graph and report. |
| Ontology | Research and the forecasting question define entity and relationship types. | Gives the graph and actor-selection process a consistent structure. |
| Graph | Research-backed actors, relations and eligible dated observations produce the knowledge graph. | Supports grounded retrieval and preparation; a graph relation is not a new independent source. |
| Prepare | Selected cast, actor context, role/knowledge limits, temporal horizon, scenario assumptions and world seed produce executable simulation inputs. | Establishes the conditions under which the simulated exercise runs. |
| Run | Agent decisions and public statements, arbiter updates, commitments and shocks evolve the world over committed periods. | Produces a separately audited record of what the model did, including limitations and failed/degraded periods. |
| Report | The bound research generation, sources, official data and evidence-derived forecast spine produce probabilities, narrative and charts. | A deterministic bridge is inserted after prose stabilization; final audits and publication are separate from stage completion. |

The persistent pipeline state belongs to `PipelineOrchestrator`/`PipelineManager`; progress percentages are not publication proof. OASIS and the opt-in world engine have different terminal paths, so record finalization must be tested through each actual consumer. The opted-in world engine retains its existing conditional-pathway appendix in version 1.

## Defects found in the recovered implementation

- Outline planning and writer tools still admitted simulated outcomes despite the empty signal pack. The original isolation test returned empty tool responses and missed this.
- Record publication relied on a weak audit/existence check; report consumers could expose changed content after the gate.
- `no_update` could still surface a record link or simulated chart.
- A hollow raw-artifact fallback could narrate partial dynamics, and malformed bridge markers could evade the block count.
- Structured red-line ranking selected the owner of the red line instead of its recorded crosser.
- Stage lifecycle, derivative reuse and generic artifact access had missing or bypassing record paths; these are repaired with producer-to-consumer tests.

## Verification evidence and limits

Evidence is retained privately at `/Users/rogerlin/.local/share/DeepResearchForecast/verification/simulation-report-boundary/`. The original failed tests are retained alongside later fixes. The guarded runner preserves system identity and blocks network, provider credentials, original saved data and writes outside its test root. Its managed-worktree adjustment has 25 passing actual-operation controls; blocked negative-control attempts are intentional and are not described as zero attempts.

A deterministic replay of the complete saved nine-period `sim_3ec25e64209e` run passed the compiler, record gate and verified reload, with 106 public moves, 51 state changes and zero audit warnings. Eleven input artifacts were privately copied and hashed; the original saved run was not modified. The replay is fidelity evidence, not a new provider-backed forecast or simulation-quality result.

Final verification: feature branch 883 backend passes, 2 explicit skips and 11 expected failures; its amended context fixtures pass 58/58 and frontend passes 321/321. The combined candidate preserving the Mandarin work passes 981 backend tests, 1 explicit Git-history skip and 11 expected failures, plus 379 frontend tests and the production build. The build retains a 526.71 kB chunk warning. The skip is a historical `git show HEAD` comparison blocked by the offline guard; production fixtures and actual consumer tests are not skipped.

The compound suite intentionally blocks font discovery and unrelated subprocess probes; those are retained as blocked attempts in verification.json. It permits only named, hashed Python fixtures under the same child guard. No network/provider access or original saved-run writes were permitted.

The newer, uncommitted Mandarin translator required a small compatibility adapter: its model receipts cover exactly the translated prose, while the deterministic bridge and full public document retain their own checks. The specific adjustments are recorded in translation-compatibility.patch. This patch is a review/continuity artifact for the already composed working tree, not an instruction to apply blindly to a checkout without that translator. The peer translation implementation itself is not included in the feature commit.

See verification.json for exact receipts, source hashes, independent reviews and browser artifacts. Delivery results follow after the active checkout and managed services are reconciled.
