# Report input and CLI contract

## Serialization

The schema tag is exactly `equity-report/v1`. Save UTF-8 JSON. Text is plain Unicode, without embedded HTML or Markdown styling. Every localized object has exactly two nonempty string fields: `en` and `zh-CN`. Do not attach source spans, approvals, omitted-content lists, chart data, or arbitrary metadata to the report JSON. Keep those in a separate reconciliation record.

Required top-level fields:

| Field | Value |
|---|---|
| `schema` | The literal `equity-report/v1` |
| `source` | An object containing only `path` (relative source file path) and `sha256` (SHA-256 hex digest of its original bytes) |
| `title`, `subtitle`, `publisher`, `report_type` | Localized objects |
| `date` | ISO date, `YYYY-MM-DD` |
| `authors` | A list of localized objects; the current renderer requires at least one supplied identity. If absent, surface the source gap rather than inventing an author |
| `snapshot` | A list of objects containing only `label` and `value`, both localized |
| `blocks` | An ordered list of the supported blocks below |
| `source_inventory` | The exact ordered list of all block IDs, independently reconciled with the source |

Resolve source and figure paths relative to the input JSON file. Use local files and portable relative paths that remain inside that input bundle. The source must exist and its byte hash must match. Every block ID is a unique nonempty string; the current renderer accepts the pattern `[A-Za-z0-9][A-Za-z0-9_.-]{0,100}`. Every source component must survive normalization; matching two generated ID lists alone is not evidence of this. `blocks` is nonempty, contains content, and has no leading, trailing, or consecutive page breaks. Use `snapshot: []` when inapplicable.

## Blocks: finite keys only

All blocks contain `id` and `type`. The following table lists every other allowed field; all are required except `table.notes`.

| `type` | Other fields |
|---|---|
| `heading` | `text` (localized), `level` (integer `1` or `2`) |
| `paragraph` | `text` (localized) |
| `bullets` | `items` (nonempty list of localized objects) |
| `table` | `title` (localized), `columns` (nonempty list of localized objects, maximum 10), `rows` (nonempty list of rows), `source` (localized); optional `notes` (localized) |
| `figure` | `title`, `caption`, `source` (localized); `files` (exactly `en` and `zh-CN` relative PNG/JPEG paths) |
| `reference` | `text` (localized), `url` (HTTPS destination) |
| `page_break` | No additional fields |

Each table row has exactly as many cells as `columns`; each cell is a localized object, including financial values. Preserve the same Arabic numbers, signs, currencies, scales, and estimate labels in both languages. For example, use `USD 145.2 million` / `USD 145.2 million（百万美元）`, not a rescaled Chinese amount. Keep accounting parentheses and the definition of negatives. Split tables exceeding 10 columns deliberately with repeated identifiers/units; do not rely on automatic truncation. Represent an actual source footnote or disclosure with a paragraph block; do not invent a `footnote` or `disclosure` type.

Each figure language uses its matching asset. Identical paths are appropriate only for language-neutral images. Hashes and occurrences are recorded by output QA; do not add them to figure blocks. SVG, HTML and network image execution are unsupported. A `reference.url` is the exact PDF hyperlink destination, even when `text` is a readable label. Visible cross-references must resolve after pagination.

Unknown keys/types, missing translations/assets, empty required text/cells, mismatched rows, unresolved references, inventory mismatch, and source hash mismatch must fail validation. Do not “repair” an unknown field by dropping its contents. Map its content to an approved type or stop for a contract decision.

## Runtime setup

The installed skill contains [requirements.txt](../requirements.txt), which pins the tested `reportlab`, `pypdf`, `PyMuPDF`, and `Pillow` versions. It does not contain a virtual environment. Reuse a compatible active project `.venv` when available, or create a separate environment outside the skill package:

```bash
cd "${CODEX_HOME:-$HOME/.codex}/skills/equity-research-pdf"
python3 -m venv "$HOME/.local/share/equity-research-pdf/venv"
source "$HOME/.local/share/equity-research-pdf/venv/bin/activate"
python -m pip install -r requirements.txt
python scripts/export_report.py --help
```

For a source checkout or custom installation, replace the first `cd` with the actual directory containing `SKILL.md`, `requirements.txt`, and `scripts/`. With an existing compatible environment, skip creation and activate it or use its Python explicitly for the install and export commands. In later sessions, reactivate the chosen environment and return to the skill directory. No dependency is installed globally by these commands.

PDF font overrides are `EQUITY_PDF_LATIN_FONT`, `EQUITY_PDF_LATIN_BOLD`, `EQUITY_PDF_CJK_FONT`, and `EQUITY_PDF_CJK_BOLD`. Default local choices are DejaVu Serif / DejaVu Sans Bold and STHeiti Light / Medium. Fonts are not supplied by pip: ensure the default files exist or set all necessary overrides to licensed local fonts before rendering. Validate actual glyph coverage and embedding for the supplied report. Do not copy system fonts into the package. The chart-only fixture generator needs just Pillow and its separately documented local font paths.

## Commands and outputs

Use the prepared environment's Python from the skill directory. `INPUT.json`, `OUTPUT`, and `REVIEW.json` are user-chosen paths; absolute paths let source and output files remain in the user's working directory instead of the installed skill package.

Render:

```bash
python scripts/export_report.py render INPUT.json --output-dir OUTPUT
```

`OUTPUT` receives `report.en.pdf`, `report.zh-CN.pdf`, `qa.json`, `review-template.json`, all page PNGs in `pages/en/` and `pages/zh-CN/`, and draft `preview.html`. QA must reopen the PDFs, reconcile every textual component, record figure draws, check hyperlinks, embedded fonts and text bounds, and render every page. The standalone HTML embeds both verified PDFs plus locally rendered page images, so viewing needs no browser PDF plugin or adjacent files; the downloaded PDFs retain their original bytes. Both language inputs are required in this release. Render success is draft completion only.

Use the actual generated review template, preserving its exact hash-field structure. Its only keys are `schema` (literal `equity-pdf-review/v1`), `input_sha256`, `pdf_sha256` (exactly `en` and `zh-CN` hashes), `source_reconciled`, `semantic_review`, `visual_review`, `reviewer`, and `notes`. The generated template starts with false review flags and empty reviewer/notes. A valid review binds the input and both PDF hashes, contains nonempty `reviewer` and `notes`, and contains actual boolean `true` values for all three flags after the respective work has been performed. Strings such as `"true"` are not approvals.

```bash
python scripts/export_report.py publish --output-dir OUTPUT --review REVIEW.json
```

Publish revalidates the hashes, makes the local preview ready, and writes a release receipt. It is not remote publication. The standalone preview embeds the exact local PDF bytes, uses `preview-en` / `preview-zh-CN` for previews and `export-en` / `export-zh-CN` for downloads, and requires no network. Draft export controls remain disabled with a visible reason. Downloaded PDF bytes must match the reviewed language's hash.

## Rebuild only the fictional input

```bash
python scripts/make_example.py --output-dir assets/example
```

This command writes `source.md`, `report.json`, `reconciliation.md`, `chart.en.png`, and `chart.zh-CN.png`; it creates no PDFs or review approvals. Use a dedicated output directory: those five generated fixture paths are replaced. Other files are preserved. The script checks the finite report fields, source digest, ordered IDs, table shape, bilingual numeric tokens, and image data parity. Its checks are fixture checks, not a replacement for the exporter's validation or a publication review.

Pillow is required to regenerate charts. The script uses local DejaVu Sans and `/System/Library/Fonts/STHeiti Light.ttc` without copying font files. It also accepts `EQUITY_EXAMPLE_LATIN_FONT`, `EQUITY_EXAMPLE_LATIN_BOLD_FONT`, and `EQUITY_EXAMPLE_CJK_FONT` environment paths to licensed local equivalents. The checked-in PNGs need no chart-generation fonts to be consumed. Font choice for PDF text remains a separate renderer responsibility.
