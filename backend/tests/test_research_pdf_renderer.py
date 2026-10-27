"""Real PDF adapter tests through a private package; no app bootstrap or providers.

Run with the guarded runner or a PDF-capable Python plus existing mistune. The
private package loader executes only renderer.py and contracts.py, not app imports.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from copy import deepcopy

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "app/services/research_pdf"
NAME = "_private_research_pdf_tests"
package = types.ModuleType(NAME)
package.__path__ = [str(PACKAGE)]
sys.modules[NAME] = package
spec = importlib.util.spec_from_file_location(NAME + ".renderer", PACKAGE / "renderer.py")
renderer = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = renderer
spec.loader.exec_module(renderer)
PdfExportError = renderer.PdfExportError


def sha(data):
    return hashlib.sha256(data).hexdigest()


class RendererTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="research-pdf-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "snapshot"
        self.source.mkdir()
        from PIL import Image
        (self.source / "charts").mkdir()
        Image.new("RGB", (600, 240), (38, 115, 149)).save(self.source / "charts/forecast.png")

    def snapshot(self, markdown=None, language="en"):
        if markdown is None:
            markdown = (ROOT / "tests/fixtures/research_pdf_full.md").read_text()
        path = self.source / "source.md"
        path.write_text(markdown, encoding="utf-8")
        return {"schema": "research-pdf-source/v1", "kind": "forecast", "resource_id": "fixture",
                "requested_lang": None, "language": language, "source_digest": "a" * 64,
                "markdown_sha256": sha(markdown.encode()), "markdown": markdown,
                "folder": str(self.source), "markdown_path": str(path),
                "title": "Conditional research" if language == "en" else "条件研究报告",
                "publisher": "DeepResearchForecast", "report_type": "Forecast report" if language == "en" else "预测报告",
                "date": "2026-10-26", "citations": {"S1": {"url": "https://example.org/filing"}},
                "assets": [{"relative_path": "charts/forecast.png", "sha256": sha((self.source / "charts/forecast.png").read_bytes())}],
                "admission": {"publishable": True}}

    def prepared(self, snapshot=None):
        return renderer.prepare_document(snapshot or self.snapshot(), self.root / "prepared")

    def test_selected_language_source_inventory_and_complete_pdf(self):
        snapshot = self.snapshot()
        prepared = self.prepared(snapshot)
        self.assertEqual(prepared["report"]["title"], {"en": snapshot["title"]})
        self.assertEqual(prepared["report"]["authors"], [])
        inventory = json.loads(Path(prepared["inventory_path"]).read_text())
        self.assertEqual(inventory["source_markdown"], snapshot["markdown"])
        self.assertEqual(inventory["source_metadata"]["citations"], snapshot["citations"])
        result = renderer.render_document(prepared, self.root / "render")
        self.assertTrue(all(result["qa"]["checks"].values()))
        self.assertEqual(result["qa"]["figure_occurrences"], 1)
        self.assertGreater(result["qa"]["inline_links_checked"], 3)
        self.assertEqual(result["qa"]["status"], "awaiting_agent_review")
        self.assertNotIn("visual_review", result["qa"])
        self.assertFalse((self.root / "render/report.zh-CN.pdf").exists())
        for page in result["pages"]:
            self.assertEqual(sha(Path(page["path"]).read_bytes()), page["sha256"])

    def test_mandarin_primary_preserves_punctuation_and_footnotes(self):
        prepared = self.prepared(self.snapshot("# 中文研究\n\n预计收入 USD 1,250.50；下行情景为 -12.5%。这不是已报告事实。[^风险]\n\n| 项目 | 数值 |\n|---|---:|\n| 收入 | 1,250.50 |\n| 限定 | 未经审计 |\n\n[^风险]: 假设可能不成立，损失可能扩大。\n", "zh-CN"))
        result = renderer.render_document(prepared, self.root / "render")
        self.assertEqual(result["language"], "zh-CN")
        self.assertNotIn("en", prepared["report"]["title"])
        self.assertTrue(result["qa"]["checks"]["used_fonts_embedded"])

    def test_long_table_exact_cells_and_all_pages(self):
        rows = "\n".join(f"| Row {i} | {i}.25 | qualifier {i} |" for i in range(100))
        prepared = self.prepared(self.snapshot("# Long table\n\n| Row | USD | Notes |\n|---|---:|---|\n" + rows + "\n"))
        result = renderer.render_document(prepared, self.root / "render", {"table_font_size": 7.5})
        self.assertGreater(len(result["pages"]), 2)
        self.assertTrue(result["qa"]["checks"]["component_text_regions"])
        self.assertEqual(result["qa"]["pages"], len(result["pages"]))

    def test_asset_map_and_immutable_original(self):
        snapshot = self.snapshot("# Chart\n\n![same source](http://localhost/api/report/fixture/charts/forecast.png)\n")
        snapshot["asset_map"] = {"http://localhost/api/report/fixture/charts/forecast.png": "charts/forecast.png"}
        before = sha((self.source / "charts/forecast.png").read_bytes())
        prepared = self.prepared(snapshot)
        result = renderer.render_document(prepared, self.root / "render")
        self.assertEqual(result["qa"]["figure_occurrences"], 1)
        self.assertEqual(before, sha((self.source / "charts/forecast.png").read_bytes()))

    def test_unsupported_required_content_fails_actionably(self):
        for markdown, code in [("```mermaid\ngraph TD\nA-->B\n```", "pdf_diagram_unsupported"),
                               ("$$\nx^2\n$$", "pdf_math_unsupported"),
                               ("<table><tr><td>visible</td></tr></table>", "pdf_html_unsupported"),
                               ("![chart](https://example.org/remote.png)", "pdf_asset_not_captured"),
                               ("[unsafe](file:///etc/passwd)", "pdf_link_unsupported"),
                               ("[missing](#not-present)", "pdf_link_unresolved")]:
            with self.subTest(markdown=markdown):
                snapshot = self.snapshot(markdown)
                with self.assertRaises(PdfExportError) as error:
                    self.prepared(snapshot)
                self.assertEqual(error.exception.code, code)
                self.assertFalse((self.root / "prepared").exists())

    def test_source_and_prepared_tampering_rejected(self):
        snapshot = self.snapshot()
        snapshot["markdown"] += "changed"
        with self.assertRaisesRegex(PdfExportError, "hash"):
            self.prepared(snapshot)
        prepared = self.prepared()
        Path(prepared["inventory_path"]).write_text("{}")
        with self.assertRaisesRegex(PdfExportError, "inventory"):
            renderer.render_document(prepared, self.root / "render")

    def test_layout_is_bounded_and_does_not_mutate_input(self):
        prepared = self.prepared(self.snapshot("# Layout\n\nText.\n"))
        original = deepcopy(prepared)
        for layout in ({"body_font_size": 1}, {"title": "rewrite"}, {"page_break_before": ["missing"]}, {"body_font_size": float("nan")}):
            with self.assertRaises(PdfExportError):
                renderer.render_document(prepared, self.root / "render", layout)
        renderer.render_document(prepared, self.root / "render", {"body_font_size": 9.5})
        self.assertEqual(original, prepared)

    def test_upstream_manifest_complete(self):
        manifest = json.loads((renderer.SKILL_DIR / "upstream-manifest.json").read_text())
        for rel, digest in manifest["files"].items():
            self.assertEqual(sha((renderer.SKILL_DIR / "upstream" / rel).read_bytes()), digest)
        self.assertEqual((renderer.SKILL_DIR / "requirements.txt").read_bytes(), (renderer.SKILL_DIR / "upstream/requirements.txt").read_bytes())

    def test_link_labels_cannot_swap_destinations(self):
        prepared = self.prepared(self.snapshot("# Links\n\n[Alpha](https://example.org/a) and [Beta](https://example.org/b).\n"))
        result = renderer.render_document(prepared, self.root / "render")
        core = renderer._core()
        changed = self.root / "swapped-links.pdf"
        with core.fitz.open(result["pdf_path"]) as doc:
            page = doc[0]
            links = page.get_links()
            links[0]["uri"], links[1]["uri"] = links[1]["uri"], links[0]["uri"]
            for link in links:
                page.update_link(link)
            doc.save(changed)
        with self.assertRaisesRegex(PdfExportError, "label/destination"):
            renderer._check_links(core, prepared["report"], changed, result["qa"]["component_draws"])

    def test_internal_link_target_on_same_page_is_checked(self):
        prepared = self.prepared(self.snapshot("# Links\n\n[First](#first) and [Second](#second).\n\n## First\n\nFirst body.\n\n## Second\n\nSecond body.\n"))
        result = renderer.render_document(prepared, self.root / "render")
        core = renderer._core()
        changed = self.root / "swapped-anchors.pdf"
        with core.fitz.open(result["pdf_path"]) as doc:
            page = doc[0]
            links = page.get_links()
            links[0]["to"], links[1]["to"] = links[1]["to"], links[0]["to"]
            for link in links:
                page.update_link(link)
            doc.save(changed)
        with self.assertRaisesRegex(PdfExportError, "label/destination"):
            renderer._check_links(core, prepared["report"], changed, result["qa"]["component_draws"])

    def test_crlf_source_spans_and_unreferenced_footnotes(self):
        source = "# Source\r\n\r\nA paragraph.\r\n\r\n[^unused]: Preserve this qualification.\r\n"
        prepared = self.prepared(self.snapshot(source))
        for component in prepared["components"]:
            if "source_span" in component:
                span = component["source_span"]
                self.assertEqual(component["source_text"], source[span["start"]:span["end"]])
        self.assertIn("Preserve this qualification.", "\n".join(c["render_text"] for c in prepared["components"]))
        renderer.render_document(prepared, self.root / "render")

    def test_wrapped_links_rich_emphasis_task_lists_and_repeated_headers(self):
        rows = "\n".join(f"| row {i} | {i}.25 |" for i in range(80))
        source = ("# Linked records\n\n[" + "Long **label** with qualifiers " * 10 + "](https://example.org/long)\n\n"
                  "- [x] Complete\n- [ ] Pending\n\n| [Source](https://example.org/head) | USD |\n|---|---:|\n" + rows + "\n")
        prepared = self.prepared(self.snapshot(source))
        result = renderer.render_document(prepared, self.root / "render")
        self.assertTrue(result["qa"]["checks"]["inline_link_regions"])

    def test_frozen_asset_and_in_memory_report_cannot_be_rewritten(self):
        prepared = self.prepared()
        prepared["report"]["title"]["en"] = "Replacement"
        with self.assertRaisesRegex(PdfExportError, "in-memory"):
            renderer.render_document(prepared, self.root / "render")
        prepared["report"] = json.loads(Path(prepared["report_path"]).read_text())
        Path(prepared["assets"][0]["path"]).write_bytes(b"changed")
        with self.assertRaisesRegex(PdfExportError, "dependency"):
            renderer.render_document(prepared, self.root / "render")

    def test_missing_glyph_is_not_silently_replaced(self):
        prepared = self.prepared(self.snapshot("# Glyph\n\nMissing glyph: \U0010ffff\n"))
        with self.assertRaisesRegex(PdfExportError, "No glyph"):
            renderer.render_document(prepared, self.root / "render")

    def test_commonmark_entities_and_url_query_keys_are_not_corrupted(self):
        snapshot = self.snapshot("# Ampersands\n\nRevenue &notional matters; &amp; and &#38; mean ampersand. [source](https://example.org/?a=1&notional=2)\n")
        prepared = self.prepared(snapshot)
        text = "\n".join(c["render_text"] for c in prepared["components"])
        self.assertIn("Revenue &notional matters; & and & mean ampersand", text)
        result = renderer.render_document(prepared, self.root / "render")
        self.assertIn("https://example.org/?a=1&notional=2", result["qa"]["hyperlinks"])

    def test_unused_footnotes_share_references_and_math_policy(self):
        source = "# Notes\n\nBody.\n\n[^unused]: See [method][method].\n\n[method]: https://example.org/method\n"
        prepared = self.prepared(self.snapshot(source))
        result = renderer.render_document(prepared, self.root / "render")
        self.assertIn("https://example.org/method", result["qa"]["hyperlinks"])
        with self.assertRaisesRegex(PdfExportError, "mathematics"):
            renderer.prepare_document(self.snapshot("# Notes\n\nBody.\n\n[^unused]: $x^2$\n"), self.root / "math-prepared")

    def test_chart_qualification_cannot_be_separated_by_layout(self):
        prepared = self.prepared(self.snapshot("# Figure\n\n![Forecast](charts/forecast.png)\n\nSource: ABC. All values are hypothetical.\n"))
        figure = next(b for b in prepared["report"]["blocks"] if b["type"] == "figure")
        note_id = prepared["report"]["figure_groups"][figure["id"]][0]
        with self.assertRaisesRegex(PdfExportError, "cannot separate"):
            renderer.render_document(prepared, self.root / "render", {"page_break_before": [note_id]})
        result = renderer.render_document(prepared, self.root / "render", {"page_break_before": [figure["id"]]})
        self.assertTrue(result["qa"]["checks"]["figure_attributions_bound"])

    def test_citation_map_and_forecast_marker_ledger_resolve_destinations(self):
        snapshot = self.snapshot("# Citations\n\nClaim [S1, S2-a].\n")
        snapshot["citations"] = {"markers": [{"tag": "S1", "url": "https://example.org/a", "url_valid": True},
                                               {"tag": "S2-a", "url": "https://example.org/b", "url_valid": True}]}
        prepared = self.prepared(snapshot)
        result = renderer.render_document(prepared, self.root / "render")
        self.assertEqual(result["qa"]["hyperlinks"], ["https://example.org/a", "https://example.org/b"])
        missing = self.snapshot("# Citations\n\nClaim [S99].\n")
        with self.assertRaisesRegex(PdfExportError, "citation S99"):
            renderer.prepare_document(missing, self.root / "missing-prepared")

    def test_numbered_headings_and_nested_list_hierarchy_survive(self):
        prepared = self.prepared(self.snapshot("# Conditions\n\nSee [first](#first-condition).\n\n5. ## First condition\n6. ## Second condition\n   - Nested qualifier.\n"))
        text = "\n".join(c["render_text"] for c in prepared["components"])
        self.assertIn("5. First condition", text)
        self.assertIn("6. Second condition", text)
        result = renderer.render_document(prepared, self.root / "render")
        with renderer._core().fitz.open(result["pdf_path"]) as doc:
            self.assertGreater(doc[0].search_for("Nested qualifier")[0].x0, 60)

    def test_mandarin_punctuation_breaking_is_local_to_renderer(self):
        import reportlab.lib.textsplit as textsplit
        import reportlab.platypus.paragraph as paragraph
        original = (textsplit.ALL_CANNOT_START, paragraph.ALL_CANNOT_START, paragraph.Paragraph.breakLinesCJK)
        paragraphs = ["甲"*n + "，" + "乙"*n + "；这是限定条件。" for n in range(46, 55)]
        paragraphs += ["**" + "甲"*n + "**，" + "乙"*n + "；这是限定条件。" for n in range(46, 55)]
        prepared = self.prepared(self.snapshot("# 中文标点\n\n" + "\n\n".join(paragraphs), "zh-CN"))
        result = renderer.render_document(prepared, self.root / "render")
        self.assertEqual(original, (textsplit.ALL_CANNOT_START, paragraph.ALL_CANNOT_START, paragraph.Paragraph.breakLinesCJK))
        with renderer._core().fitz.open(result["pdf_path"]) as doc:
            for page in doc:
                for block in page.get_text("dict")["blocks"]:
                    for line in block.get("lines", []):
                        text = "".join(s["text"] for s in line["spans"]).strip()
                        self.assertFalse(text and text[0] in "，；：？！％”’》〉】〕}", text)


if __name__ == "__main__":
    unittest.main()
