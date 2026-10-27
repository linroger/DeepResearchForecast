# Selected-language application integration

The application adapter uses `equity-report-selected/v1` with exactly one language,
`en` or `zh-CN`. It never manufactures the other language or an author identity.
The upstream bilingual CLI and review protocol remain available. The complete
original package is in `upstream/`, checked by `upstream-manifest.json`.

`prepare_document(snapshot, directory)` freezes full source bytes, parser tokens,
source metadata, asset hashes and ordered source-to-block mappings in a new private
directory. `render_document(prepared, directory, layout=None)` creates a new render
generation and returns its checked PDF, QA and every page image. Neither function
publishes or claims semantic, visual or manual review. The export agent must review
the exact returned hashes before the parent publishes.

Layout controls are deliberately finite and apply to one invocation only:
`body_font_size` (9–11), `table_font_size` (7–9), `figure_max_height` (180–360 points),
`page_break_before` (unique existing block IDs, excluding the first), and
`table_column_weights` (table ID to positive weights, one per column, each 0.5–4).
Unknown keys, invalid IDs and out-of-range values fail. Content edits, omissions,
page size changes and font replacement through model layout decisions are forbidden.

Runtime: Python 3.12; upstream pins reportlab 4.5.1, pypdf 6.4.0,
PyMuPDF 1.26.6 and Pillow 12.3.0; parser mistune >=3.3.4,<4 is already a backend
dependency. Fonts use EQUITY_PDF_LATIN_FONT, EQUITY_PDF_LATIN_BOLD,
EQUITY_PDF_CJK_FONT, EQUITY_PDF_CJK_BOLD. Ordinary code and code spans additionally
use EQUITY_PDF_MONO_FONT (default DejaVuSansMono.ttf). TrueType-outline TTF/TTC with actual glyph
coverage is required; fonts are never copied into the package. Default local
DejaVu Serif / DejaVu Sans Bold and STHeiti Light / Medium work on this machine.

The application lock intentionally retains the existing backend-compatible
Pillow 10.3.0 (<11 because of camel-ai), PyMuPDF 1.28.2, and pypdf 6.20.0.
The upstream standalone `requirements.txt` is preserved byte-for-byte; its
Pillow 12.3.0 pin must not override the application's dependency constraints.

## Renderer worker continuity record

2026-10-26: Read approved PLANS and integration contract. Scope is renderer.py,
this vendored package and focused renderer fixtures/tests. Parent owns shared
handoff, config, dependencies and final delivery. Work is in progress. Acceptance
requires source preservation, single-language output, exact cell/image/link QA,
font embedding, all-page rasters, negative unsupported/unsafe cases, immutable
input checks and unchanged upstream standalone behavior. No application imports,
providers, shared environments or services are required for focused tests.


## Supported source and explicit stopping conditions

The adapter uses the application's Mistune dialect (tables, footnotes, strike and
bare URLs), plus task lists and math detection. It preserves all heading levels,
paragraphs, ordered/nested/task lists, quotes, empty table cells, cell alignment,
ordinary fenced/indented code, inline code, link labels/destinations, heading and
footnote targets, reference definitions, source citation markers, figure titles,
alt captions, visualization association comments, and the complete citation ledger
in the independent inventory. CRLF source offsets refer to original source bytes
through character offsets and line spans; synthetic footnote nodes instead retain
explicit parser locators and the complete definition environment.

Only snapshot-inventoried PNG/JPEG images are rendered. The snapshot `asset_map`
resolves original absolute/API references to captured local files. Other remote
images, missing/damaged images, path escapes, unbound local interactive-HTML links, raw
HTML beyond comments/line breaks, unsupported math, Mermaid/Graphviz/PlantUML and
other required diagram code stop with actionable errors. No converters, providers,
network fetches or service starts occur. A future converter must write only in the
private generation and bind its derivative to source hashes. An unsupported
required diagram must not be presented as ordinary code. Figure-language review
remains necessary: a translated caption does not certify labels inside an image.

Every source byte, parsed token, reference environment, metadata field, asset hash
and component mapping is sealed in `source-inventory.json`. A separate input
manifest freezes all copied dependencies. Rendering verifies them before and after
building. The PDF checker validates text by its own component/cell rectangle,
image pixels at their actual draw locations, hyperlink labels and destinations,
embedded glyph fonts, bounds/overlaps, page numbers, a second parser and every page
raster. These automated checks do not assert independent semantic or visual review.

## Verification ledger

2026-10-26: Initial 8 real-PDF tests passed with the standalone pinned interpreter
and again with the backend dependency versions. The full 34 upstream standalone
PDF/review regressions passed against the adapted active helpers. After additional
link and source-inventory hardening, 14 renderer tests passed under the existing
CPython audit runner using the new isolated backend environment. The runner is an
audit boundary, not an OS sandbox. ReportLab attempted two optional home-directory
configuration reads (`.reportlab_mods` and `.reportlab_settings`); both were denied.
No child processes or providers were admitted. Evidence:
`/private/tmp/research-pdf-renderer-native-20261026-2/{completed.json,junit.xml}`.

Command from the worktree, with a fresh canonical evidence path each run:

```sh
backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py \
  --evidence-dir /private/tmp/research-pdf-renderer-native-NEW \
  -- backend/tests/test_research_pdf_renderer.py -q
```

Before the isolated backend environment was available, focused tests used the
standalone PDF interpreter with only the backend site-packages path appended for
Mistune; reversing path order exercised deployed Pillow/PyMuPDF/pypdf while
supplying missing ReportLab from the standalone environment. This was a private
module test boundary with no `app` bootstrap; nothing was installed globally.


2026-10-26 independent review found and reproduced entity double-decoding,
unreferenced footnote environment drift, detached figure attribution, unresolved
citation-map destinations and list-heading marker loss. These are fixed with
semicolon-terminated CommonMark entity decoding, unchanged parser URLs, the same
parser/reference environment for every footnote, explicit figure groups protected
from page-break repairs, source-map citation hyperlinks (both direct maps and
forecast markers ledgers), and retained list prefixes/indentation. The renderer
now verifies each link's label and destination at its own position, and verifies
chart titles/captions/attributions remain on the chart's page. Missing admitted
citation URLs fail explicitly. The complete citation ledger remains in inventory.

Mandarin line breaking preserves the original skill's punctuation policy through
local copies of ReportLab 4.5.1's single- and mixed-fragment helpers attached only
to the audited paragraph subclass. ReportLab modules and their punctuation sets
are not modified. Source-derived list indentation is retained. Thematic rules
have actual draw records and independent vector-line verification. These changes
are per-renderer behavior; models cannot modify the policy or source content.


2026-10-26 final renderer acceptance: 20 focused tests passed under the existing
main offline runner with the isolated worktree backend interpreter (10.92 seconds).
The final 34 upstream PDF/review compatibility tests passed on the same deployed
dependency stack (23.127 seconds). Independent review rechecked all reproduced
findings, including original heading anchors inside numbered lists, and reported
no remaining blockers. Its separate-process CJK probe covered 12 punctuation/font
fragment combinations and confirmed both upstream-equivalent line breaking and
unchanged shared ReportLab state. Machine-readable source hashes, dependency
versions, audit events and limits are in [verification.json](verification.json).
The original two-page fixture was visually inspected during implementation; this
was developer QA, not a fabricated human or export-agent review receipt. Final
publication still requires the parent's actual automated review workflow.

Renderer worker scope is complete. Shared API/job/UI acceptance, any live provider
smoke check, shared documentation/feature bookkeeping, commit and push belong to
the parent. No shared Config/dependency file, global skill installation, accepted
report or service was modified by this worker.


2026-10-26T09:27:59.689347+00:00 follow-up: renderer worker owns native
acceptance of parent-provided private copies of an existing dossier and forecast.
The parent retains source admission/copy ownership and will provide source hashes.
The worker will inventory the actual Markdown structures and links, render both
complete reports, verify every PDF page and input hash, and record any required
narrow compatibility repairs. Canonical reports remain read-only; this acceptance
uses no model calls, providers, service starts or app bootstrap. Source-copy paths
are pending. Font overrides are direct EQUITY_PDF_* environment inputs. Current
relative interactive-link refusal must be tested against the copied sources before
choosing any extension; no unsupported formats will be added speculatively.


2026-10-26 integration repair: the parent's 400×180 chart fixture exposed a
pagination defect absent from the original 600×240 fixture. The chart title was
outside the KeepTogether containing pixels/caption/attribution. It is now inside
one complete figure group; the exact figure-association QA remains unchanged.
The parent's agent fixture was not edited. The combined existing native-agent case
and renderer suite passed 21 tests under the guarded isolated backend interpreter.
The native agent case now succeeds on render-0 using its original layout, without
model repair. Before/after PDF hashes and page assignments are in verification.json.


## Captured interactive chart companions

The optional server-owned `snapshot.chart_manifest` accepts the existing dossier
list (`path` = static image, `html_path` = companion) or forecast manifest object
with `items` (`path` = HTML, `png_path` = static image). Both assets must be captured
inside the snapshot and match their inventory hashes. A same-stem, adjacent
already-rendered PNG/JPEG is also acceptable source evidence. Filename similarity
without adjacency or explicit manifest provenance is insufficient.

The original link label points to the static image's exact internal PDF anchor.
An explicit localized note displays the original relative HTML destination. The
inventory and QA record the original label/destination, HTML/static hashes, binding
provenance, target component, and visible adaptation. Existing figures are reused.
When only the HTML link appears in Markdown, an explicit manifest pair may create
one derived static figure immediately after that link, with its source locator and
manifest provenance recorded. No HTML is executed, no HTTP origin is invented, and
no external image is fetched. Missing, changed or ambiguous companions fail.

These host-declared static-chart adaptations and their explanatory notes are
intentional export furniture; semantic reconciliation must assess the recorded
source-to-static mapping, not mistake the visible adaptation for research authored
by the formatting agent. Source Markdown remains byte-identical.

## Full saved-report native acceptance

2026-10-26: Ran actual prepare/render on the parent's private copies of the complete
English copper forecast and dossier, using the isolated worktree backend interpreter
and the private renderer package loader. The forecast passed with 38 pages, 9 tables,
392 table cells and 6 figures. The dossier passed with 30 pages, 16 tables, 374 cells
and 4 figures. Every copied input hash remained unchanged before and after.
All 68 final pages were visually covered, carrying forward only identical rendered
page hashes after the final repair; dense charts were additionally inspected at 3x.
The dossier timeline link reuses the existing PNG and preserves the original HTML
href visibly and in inventory. Native source dates came from supplied metadata:
forecast created_at (2026-10-25), dossier as_of_date (2026-10-24).

The native run exposed two further renderer defects: English inline fragments could
hang a trailing space beyond the safe page boundary, and Markdown headings directly
before figures could be stranded on a prior page. Selected-English styles now reserve
a small internal inset without deleting text or weakening QA. All adjacent figure
headings join the atomic figure group, with their original text/IDs/outlines and an
explicit same-page QA condition. Both complete native reports passed after repair.

Private source/PDF/page artifacts remain outside Git. Full receipt:
`/Users/rogerlin/Documents/Codex/evidence/research-pdf-export-20261026/native-results/native-acceptance.json`
SHA-256: `2d0e871493a78ead9bca0f88b29edbf6d067ca4f74d627b03d291c9bf96bb8e0`.
This is native rendering/developer layout acceptance, not a live-model, application
UI/API, human review, publication or deployment verdict. The existing dense tables
and pre-abbreviated image labels were preserved; static chart export does not claim
interactive-hover equivalence. Per the parent's instruction, no further broad test
sweep was run after this native acceptance.


2026-10-26T11:18:00.541807+00:00 final receipt freeze: re-opened forecast pages 12–15 at
full resolution and verified their hashes. All four pass layout inspection. The
earlier manifest's pages_to_inspect field was a review-plan remnant; it is preserved
as history rather than rewritten. The authoritative completed review records all
68 pages as inspected, with zero pending pages. PDFs, source inputs and renderer
implementation bytes are unchanged. Final receipt:
`/Users/rogerlin/Documents/Codex/evidence/research-pdf-export-20261026/native-results/native-acceptance.final.json`
SHA-256: `ec7aea69ea38ff670e97debb6b68e3e97576708f79a41a5110da103257586a2b`.

The guarded renderer receipt records two attempted and denied optional ReportLab
user-configuration reads: `<IDENTITY>/.reportlab_mods` and
`<IDENTITY>/.reportlab_settings`. Classify these as blocked library probes, not zero
attempts. The raw blocked:external_read events remain unchanged. Neither the guard
policy nor HOME was modified; disabling ambient configuration is a separate parent
investigation. No tests or provider calls were rerun for this receipt-only freeze.
