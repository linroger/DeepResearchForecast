# Layout and publication review

## Transferable reference findings

The supplied design study inventoried 11 reports totaling 196 pages and visually inspected 22 pages, including every cover and selected analytical, table, chart and disclosure pages. It was not a complete visual audit or authentication of their claims. Catalog filenames in Chinese did not establish Mandarin body content. Some complete-looking pages yielded sparse text extraction.

The observed hierarchy supports an original neutral masthead, report date/category, clear thesis headline, restrained navy/blue/gray rules, compact supplied snapshot fields, numbered exhibits, nearby source notes, running headers and page numbers. Sampled English body text was generally 10–11 pt. These are design observations, not a mandate to copy bank identity, proprietary typefaces, report prose or certification language.

Use the source's actual length and structure. The bundled example is designed as four short report sections; its page count is not a limit on user reports. Calibrate Mandarin independently rather than mechanically shrinking English typography. Wide tables need deliberate splits with repeated identifiers/units or an explicitly supported landscape workflow; do not add an unapproved JSON field for orientation. The current schema permits at most 10 table columns.

## Review the actual output

Check every page of both languages at readable size. A contact sheet helps navigation but cannot replace inspection of small labels and cells.

| Area | Evidence to inspect |
|---|---|
| Narrative | Complete sentences and qualifications; no clipping, overlap, unintended blank pages or stranded headings; source order preserved |
| Tables | Every column and row; repeated headers across pages; readable values; no clipped cells; dates, signs, decimals, estimate labels, currency and scales intact |
| Figures | Correct language image; chart data and labels agree with the source; visible legends, axes, units, source notes and footnotes; no illegible scaling |
| CJK and symbols | Real readable glyphs, punctuation, mixed Chinese/English spacing, `$`, `%`, decimal points and accounting negatives; fonts embedded for PDF text |
| References | Exact HTTPS destinations clickable; long visible URLs wrap; in-document references point to the actual output location |
| Page furniture | Correct report identity, language, running titles, date, navigation and page numbers |
| Disclosures | Complete source-specific text; no substituted bank boilerplate or invented analyst/conflict assertions |

Raster chart labels do not become embedded PDF text merely because PDF fonts pass inspection. Check those labels in the PNG itself, and retain their data and provenance. Do not copy system fonts into a distributable package; use appropriately licensed fonts for any actual distribution.

## Three separate review assertions

- `source_reconciled: true` means the reviewer actually compared the full authoritative source and mapping to the report, including metadata, tables, figures, footnotes, citations and appendices.
- `semantic_review: true` means the reviewer actually checked both languages for preserved meaning and aligned financial quantities/units. Automated numeric comparison supports this work; it cannot replace it.
- `visual_review: true` means the reviewer inspected every rendered page in each language for the issues above.

Use genuine JSON booleans, a real reviewer identity, substantive notes and the exact generated input/PDF hashes. Do not manufacture a review record to enable buttons. If review discovers a defect, repair the authorized source normalization or layout, rerender, and review the resulting new outputs. Earlier approvals do not transfer to changed bytes.

After `publish`, open the standalone preview, use both download buttons, and compare each downloaded file's bytes with the reviewed PDF hash. Record the actual check and distinguish local readiness from any subsequent external publication. Deliver a factual account of the checks, without guarantees that the source research contains no errors.

## Technical references

The renderer uses [ReportLab paragraph flow and inline font handling](https://docs.reportlab.com/reportlab/userguide/ch6_paragraphs/) and [PyMuPDF page text, image, link, and rendering APIs](https://pymupdf.readthedocs.io/en/latest/page.html). Its completeness gates compare exact text in each component's recorded regions and bind each figure's decoded pixels to its page and location. These checks supplement the source/semantic/visual review; they do not establish it by themselves.
