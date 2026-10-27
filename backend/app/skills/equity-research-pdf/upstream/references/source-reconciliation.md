# Source inventory and authority review

## Establish authority before conversion

Identify the actual report version and language, author-provided data and figure originals, and applicable disclosures. Freeze their byte hashes. Distinguish original evidence from extracted text, OCR, translations, re-created charts, and normalized JSON. A file called “final” is not proof of authority; conflicting versions need a source-owner decision. Preserve every original file.

Read the full source, including cover fields, table cells, chart annotations, small-print units/sources, footnotes, appendices and references. Native DOCX tables, text boxes and footnotes may need separate extraction. For PDFs, inspect page images alongside text; image-only pages can contain a full report while yielding almost no text. OCR is a derivative to check against the image, not automatic authority.

The renderer accepts one hashed source file. For multiple input files, retain all originals and hashes in the external inventory, then create an explicitly identified consolidated intake record containing the complete source text/tables, figure references, and provenance to each original. Hash that record for `source`. Never imply its digest authenticates a missing original or proves completeness. Do not insert arbitrary provenance keys into the strict JSON.

## Keep a separate mapping record

Record the source-to-output mapping before comparing it with the JSON inventory. A useful compact table contains:

| Source locator | Component and scope | Output locator | Authority / review |
|---|---|---|---|
| Markdown path + hash + line range | Complete paragraph or table including every row | Stable block ID, or exact metadata field | Original / checked extraction / translation |
| PDF hash + page + region | Figure, caption, legend, units and source note | Figure ID and language asset paths | Original image or checked reconstruction |
| DOCX hash + heading/table/cell locator | Footnote, endnote, cell or text box | Block ID and cell/paragraph index | Checked against native source |

Use physical source locators as well as semantic labels: a heading alone can repeat. Include cover metadata even though it is not in `source_inventory`. Record layout-only page breaks as such. For source figures, include image hashes and the data/axis authority where available. Never reconstruct unseen data from a chart and present it as supplied numbers.

Reconcile in both directions: every original component has an output destination, and every output assertion has an original source or an explicitly identified translation. Compare full paragraph text and tables cell by cell; check figure values, axes, legends and labels separately from captions. Verify links and footnote callouts. An ID check only verifies the normalized model against its own manifest.

The example's generated [reconciliation record](../assets/example/reconciliation.md) helps locate text and chart data. Its generation from the same model is deliberately not an independent completeness audit. A reviewer must open the full [source](../assets/example/source.md), both chart assets, and later both actual PDF outputs.

## Bilingual review and readiness

Compare all localized fields, including cover metadata, table headings/cells, footnotes, references and disclosures. Compare figure pixels or editable chart labels and data, not only JSON. Keep Arabic numeric tokens, dates, signs, percentage points, currency and scale aligned; distinguish actuals from estimates and assumptions from reported observations. Matching tokens cannot detect a reversed conclusion, shifted period, different denominator, or mistranslated condition.

Review Mandarin meaning and typography together: CJK punctuation, mixed-script spacing, parentheses for losses, currency signs, and line wrapping must remain legible. Unsupported glyphs or missing translations keep the report in draft. Do not conceal an unresolved translation by copying English into a Chinese field. A legitimate proper noun, URL, acronym, or unit may remain unchanged.

When an omission is explicitly authorized, preserve that decision and the original in the external record, prepare the authorized revised source, and inventory that source completely. There is no auto-omission feature. If required source material, authority, or approval remains unresolved, stop at draft and state the concrete gap.

After genuine source comparison, translation review, and visual review of all output pages, complete the generated hash-bound review template. Record who reviewed what, which source version they used, and any limited scope. A hash detects changed bytes; it does not certify truth, independence, or compliance.
