"""VIZ-1 钩子 + PDF-1 导出的离线测试（无 pandoc / 无网络依赖）。

覆盖：
  * ReportAgent._inject_visualizations / _place_visualizations —— 由结构化工件确定性生成图表并
    注入成稿：Mermaid 按章节关键词就地插入、PNG + 未匹配图归入「Visual Annex」、逐图标记幂等、
    PNG 相对路径、REPORT_VISUALIZATIONS 关闭即 no-op；
  * ReportAgent._match_section —— placement_hint 关键词 → 章节标题模糊匹配；
  * ReportManager._rewrite_chart_paths_for_pdf —— 相对 charts 路径 → 绝对（绝对路径不受影响）；
  * ReportManager._markdown_to_basic_html —— 极简 md→HTML（标题/列表/图片/代码/转义）；
  * ReportManager.export_pdf —— content-addressed cache + pandoc failure fallback (mocked,
    绝不依赖真实 pandoc/xelatex）。

真实 pandoc 端到端路径不在此（需二进制），已在交付说明的 scratchpad 验证中单独跑过。
"""

import os
import json
import subprocess
import threading
import time

import pytest

from app.config import Config
from app.services.report_agent import ReportAgent, ReportManager


@pytest.fixture(autouse=True)
def _no_png_export(monkeypatch):
    """GATE-W9：本文件测注入编排，不测 kaleido PNG 导出——每次导出要起一次 Chromium
    （慢 ~50s 且 choreographer 退出线程偶发挂死 pytest 收尾）。统一关掉走
    「HTML + matplotlib 回退 PNG」路径；kaleido 专项见 test_wave9_visualizer.py。"""
    from app.services.report_visualizer import ReportVisualizer
    monkeypatch.setattr(ReportVisualizer, "_png_export_ok", lambda self: False)


# ---------------------------------------------------------------- fixtures

class _ReportStub:
    def __init__(self, md):
        self.markdown_content = md


def _agent(**attrs):
    """__new__ 构造（与既有 report 测试同模式），只挂被测方法所需属性。"""
    a = ReportAgent.__new__(ReportAgent)
    a.output_language = attrs.pop("output_language", "English")
    a.actors = attrs.pop("actors", None)
    a.simulation_id = attrs.pop("simulation_id", "sim_test")
    a._forecast_spine = attrs.pop("_forecast_spine", None)
    for k, v in attrs.items():
        setattr(a, k, v)
    return a


@pytest.fixture
def report_folder(tmp_path, monkeypatch):
    """把 ReportManager._get_report_folder 钉到 tmp_path，隔离磁盘副作用。"""
    monkeypatch.setattr(ReportManager, "_get_report_folder",
                        classmethod(lambda cls, rid: str(tmp_path)))
    # These are low-level renderer/cache tests. The API publication barrier has
    # its own end-to-end suite; isolate PDF mechanics here with an approved
    # artifact contract.
    monkeypatch.setattr(
        ReportManager, "is_publishable",
        classmethod(lambda cls, report_id, lang=None: True),
    )
    return tmp_path


# ---------------------------------------------------------------- VIZ-1: placement

def test_match_section_keyword_fuzzy():
    """placement_hint 的关键词命中章节标题即返回该标题行号；无命中 → None。"""
    headings = [(3, "drivers and causal mechanisms"),
                (10, "key actors and coalitions"),
                (18, "conclusion")]
    assert ReportAgent._match_section(headings, "actors") == 10
    assert ReportAgent._match_section(headings, "drivers") == 3
    assert ReportAgent._match_section(headings, "calibration") is None
    assert ReportAgent._match_section(headings, "") is None
    assert ReportAgent._match_section([], "actors") is None


def test_place_visualizations_inline_and_annex(report_folder):
    """所有图按 hint 就地插入匹配章节；未匹配图入 Visual Annex；
    PNG 用相对路径；逐图标记幂等（重跑不变）。"""
    charts = report_folder / "charts"
    charts.mkdir()
    (charts / "actor_network.mmd").write_text(
        "```mermaid\ngraph TD\n    a-->b\n```", encoding="utf-8")
    (charts / "scenario_probabilities.png").write_bytes(b"\x89PNG\r\n")
    manifest = [
        {"path": "charts/actor_network.mmd", "type": "mermaid", "source": "actors",
         "caption": "Actor Network", "placement_hint": "actors"},
        {"path": "charts/scenario_probabilities.png", "type": "png", "source": "forecast",
         "caption": "Scenario Probabilities", "placement_hint": "scenarios"},
        {"path": "charts/orphan.mmd", "type": "mermaid", "source": "timeline",
         "caption": "Orphan Timeline", "placement_hint": "timeline"},  # 无匹配章节 → annex
    ]
    (charts / "orphan.mmd").write_text("```mermaid\ntimeline\n    x : y\n```", encoding="utf-8")

    a = _agent()
    md = ("# Report\n\n## Key Actors and Coalitions\n\nActor body.\n\n"
          "## Scenario Analysis\n\nScenario body.\n\n"
          "## Conclusion\n\nEnd.\n")
    new_md = a._place_visualizations(md, str(report_folder), manifest)

    # Mermaid（actors）就地插到「Key Actors」标题后（在 Conclusion 之前）。
    assert "<!-- viz:charts/actor_network.mmd -->" in new_md
    actors_pos = new_md.index("## Key Actors")
    concl_pos = new_md.index("## Conclusion")
    assert actors_pos < new_md.index("<!-- viz:charts/actor_network.mmd -->") < concl_pos
    # PNG 同样按 hint 就地插入情景章节，而非统一倾倒进附录。
    scenario_pos = new_md.index("## Scenario Analysis")
    scenario_marker = new_md.index("<!-- viz:charts/scenario_probabilities.png -->")
    annex_pos = new_md.index("## Visual Annex")
    assert scenario_pos < scenario_marker < annex_pos

    # Visual Annex 仅承接未匹配的 orphan timeline。
    assert "## Visual Annex" in new_md
    assert "![Scenario Probabilities](charts/scenario_probabilities.png)" in new_md
    assert "<!-- viz:charts/orphan.mmd -->" in new_md

    # 幂等：以新成稿为输入再跑一次，全部图已带标记 → 原样返回。
    assert a._place_visualizations(new_md, str(report_folder), manifest) == new_md


def test_place_visualizations_html_items(report_folder):
    """GATE-W9 回归：schema v2 的 plotly 'html' 项必须被注入（此前无 html 分支 → 图整族孤儿）。
    有 png_path 静态对 → 仅内嵌 PNG（交互链接由 manifest 驱动的前端统一附一次）；
    无 png_path → Markdown 内退化为纯链接。
    匹配到章节的 HTML 就地插入，未匹配项才进入 Visual Annex。"""
    charts = report_folder / "charts"
    charts.mkdir()
    (charts / "scenario_probabilities.html").write_text("<html></html>", encoding="utf-8")
    (charts / "scenario_probabilities.png").write_bytes(b"\x89PNG\r\n")
    (charts / "actor_network.html").write_text("<html></html>", encoding="utf-8")
    manifest = [
        {"path": "charts/scenario_probabilities.html", "type": "html", "source": "forecast",
         "caption": "Scenario Probabilities", "placement_hint": "scenarios",
         "png_path": "charts/scenario_probabilities.png"},
        {"path": "charts/actor_network.html", "type": "html", "source": "actors",
         "caption": "Actor Network", "placement_hint": "actors"},  # 无 png_path → 链接降级
    ]
    a = _agent()
    md = "# Report\n\n## Scenarios\n\nbody\n"
    out = a._place_visualizations(md, str(report_folder), manifest)
    assert "<!-- viz:charts/scenario_probabilities.html -->" in out
    assert "![Scenario Probabilities](charts/scenario_probabilities.png)" in out
    assert "(charts/scenario_probabilities.html)" not in out  # 避免与前端交互链接重复
    assert "<!-- viz:charts/actor_network.html -->" in out
    assert "(charts/actor_network.html)" in out
    assert "![Actor Network]" not in out  # 无静态对 → 不嵌图
    assert "## Visual Annex" in out
    assert out.index("## Scenarios") < out.index(
        "<!-- viz:charts/scenario_probabilities.html -->") < out.index("## Visual Annex")
    # 幂等重跑：原样返回。
    assert a._place_visualizations(out, str(report_folder), manifest) == out


def test_scenario_comparison_uses_outcomes_not_agent_activity(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path), raising=False)
    for sim_id, shares in (
        ("sim_base", {"Policy passes": 0.4, "Policy fails": 0.6}),
        ("sim_scenario", {"Policy passes": 0.65, "Policy fails": 0.35}),
    ):
        folder = tmp_path / sim_id
        folder.mkdir()
        (folder / "world_state_trajectory.json").write_text(json.dumps({
            "outcome": {"shares": shares},
            # Deliberate mechanics junk must never enter the comparison.
            "n_rounds": 36,
            "decisions": [{"agent_name": "Actor", "total_actions": 99}],
        }), encoding="utf-8")
    agent = ReportAgent.__new__(ReportAgent)
    agent.base_simulation_id = "sim_base"
    agent.simulation_id = "sim_scenario"
    agent.scenario_label = "Alternative policy"

    result = agent._scenario_diff_structured()

    assert result is not None
    rendered = json.dumps(result, ensure_ascii=False)
    assert "Policy passes" in rendered and "+25.0 pp" in rendered
    assert "round" not in rendered.lower()
    assert "Agent" not in rendered and "动作" not in rendered


def test_scenario_comparison_skips_when_outcome_distribution_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path), raising=False)
    (tmp_path / "sim_base").mkdir()
    (tmp_path / "sim_base" / "world_state_trajectory.json").write_text(
        json.dumps({"outcome": {"shares": {"A": 1.0}}}), encoding="utf-8")
    agent = ReportAgent.__new__(ReportAgent)
    agent.base_simulation_id = "sim_base"
    agent.simulation_id = "sim_missing"

    assert agent._scenario_diff_structured() is None








def test_place_visualizations_bilingual_annex_zh(report_folder):
    """中文报告语言 → 附录标题用中文「可视化附录」。"""
    charts = report_folder / "charts"
    charts.mkdir()
    (charts / "c.png").write_bytes(b"\x89PNG\r\n")
    manifest = [{"path": "charts/c.png", "type": "png", "source": "forecast",
                 "caption": "情景概率", "placement_hint": "scenarios"}]
    a = _agent(output_language="中文")
    out = a._place_visualizations("# 报告\n\n## 结论\n\n正文。\n", str(report_folder), manifest)
    assert "## 可视化附录（Visual Annex）" in out


def test_inject_visualizations_disabled_is_noop(report_folder, monkeypatch):
    """REPORT_VISUALIZATIONS 关闭 → 不生成图、不改成稿（degrade-safe）。"""
    monkeypatch.setattr(Config, "REPORT_VISUALIZATIONS", False, raising=False)
    a = _agent(actors={"relationships": [{"source": "A", "target": "B", "type": "ALLIES"}]})
    rep = _ReportStub("# R\n\n## Actors\n\nbody\n")
    before = rep.markdown_content
    a._inject_visualizations("rid", rep)
    assert rep.markdown_content == before
    assert not (report_folder / "charts").exists()


def test_inject_visualizations_end_to_end(report_folder, monkeypatch):
    """开总开关 → build_all 由 actors/forecast 落图并注入；成稿含标记 + Visual Annex；幂等。"""
    monkeypatch.setattr(Config, "REPORT_VISUALIZATIONS", True, raising=False)
    # timeline 定位走 best-effort，测试里强制 None，避免触碰 PipelineManager。
    monkeypatch.setattr(ReportAgent, "_locate_timeline", lambda self: None)
    import json
    (report_folder / "forecast.json").write_text(json.dumps({
        "scenarios": [{"name": "Esc", "probability": 0.4},
                      {"name": "Status quo", "probability": 0.6}]}), encoding="utf-8")
    a = _agent(actors={"relationships": [
        {"source": "US", "target": "China", "type": "RIVALS", "sign": "-"}]})
    rep = _ReportStub("# Report\n\n## Key Actors\n\nbody\n\n## Scenarios\n\nbody\n")
    a._inject_visualizations("rid", rep)
    md = rep.markdown_content
    assert "<!-- viz:" in md
    assert (report_folder / "viz_manifest.json").exists()
    # 幂等重跑：成稿不变。
    snapshot = rep.markdown_content
    a._inject_visualizations("rid", rep)
    assert rep.markdown_content == snapshot


# ---------------------------------------------------------------- PDF-1: preprocessing

def test_rewrite_chart_paths_to_absolute(tmp_path):
    """相对图片 → 绝对；普通 HTML 链接和已是绝对的图片不受影响。"""
    folder = str(tmp_path / "reports" / "rid")
    charts = tmp_path / "reports" / "rid" / "charts"
    charts.mkdir(parents=True)
    (charts / "scenario.png").write_bytes(b"png")
    (charts / "model_vs_market.png").write_bytes(b"png")
    md = ("![a](charts/scenario.png)\n"
          "![b](./charts/model_vs_market.png)\n"
          "[Interactive](charts/actor_network.html)\n"
          "![c](/already/abs/charts/x.png)\n")
    out = ReportManager._rewrite_chart_paths_for_pdf(md, folder)
    abs_charts = os.path.join(os.path.abspath(folder), "charts")
    assert f"![a]({os.path.join(abs_charts, 'scenario.png')})" in out
    assert f"![b]({os.path.join(abs_charts, 'model_vs_market.png')})" in out
    # 绝对路径原样保留（不匹配 (./)?charts/ 的相对模式）。
    assert "![c](/already/abs/charts/x.png)" in out
    assert "[Interactive](charts/actor_network.html)" in out
    assert "[Interactive](/" not in out


def test_rewrite_chart_paths_rejects_traversal_and_symlinks(tmp_path):
    folder = tmp_path / "reports" / "rid"
    charts = folder / "charts"
    charts.mkdir(parents=True)
    outside = tmp_path / "private.png"
    outside.write_bytes(b"secret")
    os.symlink(outside, charts / "linked.png")
    md = ("![traversal](charts/../../private.png)\n"
          "![encoded](charts/%2e%2e/private.png)\n"
          "![link](charts/linked.png)\n"
          "![missing](charts/missing.png)\n")

    out = ReportManager._rewrite_chart_paths_for_pdf(md, str(folder))

    assert out == md
    assert str(outside) not in out


def test_markdown_to_basic_html_covers_core_forms():
    """极简 md→HTML：标题、列表、图片、代码块、行内粗体、HTML 转义。"""
    md = ("# 标题 Title\n\n"
          "段落 with <angle> & amp.\n\n"
          "- 项目一\n- 项目二\n\n"
          "![alt](charts/x.png)\n\n"
          "```\ncode & <b>\n```\n\n"
          "**粗体** 结尾。\n")
    html = ReportManager._markdown_to_basic_html(md)
    assert "<h1>标题 Title</h1>" in html
    assert "<ul>" in html and "<li>项目一</li>" in html
    assert '<img src="charts/x.png"' in html
    assert "&lt;angle&gt; &amp; amp" in html          # 段落文本转义
    assert "<pre><code>code &amp; &lt;b&gt;" in html  # 代码块转义
    assert "<b>粗体</b>" in html


# ---------------------------------------------------------------- PDF-1: export + cache

def _install_fake_pandoc(monkeypatch, calls):
    """把 pandoc 解析钉成可用，并 mock subprocess.run —— 往 -o 目标写一个最小有效 PDF，
    记录调用次数。绝不触碰真实 pandoc/xelatex。"""
    monkeypatch.setattr(ReportManager, "_resolve_pandoc",
                        classmethod(lambda cls: ("/fake/pandoc", "/fake/xelatex")))
    monkeypatch.setattr(
        ReportManager,
        "_resolve_pdf_fonts",
        classmethod(lambda cls: {
            "main": {"family": "Fake Sans", "file": __file__},
            "cjk": {"family": "Fake CJK", "file": __file__},
            "mono": {"family": "Fake Mono", "file": __file__},
        }),
    )

    def _fake_run(cmd, *args, **kwargs):
        calls.append(cmd)
        out = cmd[cmd.index("-o") + 1]
        with open(out, "wb") as f:
            f.write(b"%PDF-1.4\n%%EOF\n")

        class _P:
            returncode = 0
            stderr = b""
        return _P()

    monkeypatch.setattr(subprocess, "run", _fake_run)
    monkeypatch.setattr(
        ReportManager,
        "_validate_pdf_content",
        staticmethod(lambda pdf_path, markdown: (True, {
            "page_count": 1,
            "issues": [],
            "replacement_glyphs": 0,
            "missing_protected_glyphs": {},
        })),
    )


def test_export_pdf_builds_then_content_caches(report_folder, monkeypatch):
    """Exact dependencies hit cache; changed Markdown bytes force a rebuild."""
    monkeypatch.setattr(Config, "REPORT_PDF_EXPORT", True, raising=False)
    (report_folder / "full_report.md").write_text("# R\n\n中文 text\n", encoding="utf-8")
    calls = []
    _install_fake_pandoc(monkeypatch, calls)

    pdf = ReportManager.export_pdf("rid")
    assert pdf and os.path.exists(pdf)
    assert len(calls) == 1                       # 构建一次
    with open(pdf, "rb") as f:
        assert f.read(5) == b"%PDF-"

    # Exact input/output manifest → cache hit; renderer is not called again.
    pdf2 = ReportManager.export_pdf("rid")
    assert pdf2 == pdf
    assert len(calls) == 1

    # Markdown bytes change even without relying on mtime ordering → rebuild.
    md_path = report_folder / "full_report.md"
    md_path.write_text("# R\n\n中文 text changed\n", encoding="utf-8")
    pdf3 = ReportManager.export_pdf("rid")
    assert pdf3 != pdf  # A new dependency set receives an immutable cache path.
    assert len(calls) == 2                        # 重新构建


def test_export_pdf_force_rebuilds(report_folder, monkeypatch):
    """force=True 忽略缓存强制重建。"""
    monkeypatch.setattr(Config, "REPORT_PDF_EXPORT", True, raising=False)
    (report_folder / "full_report.md").write_text("# R\n", encoding="utf-8")
    calls = []
    _install_fake_pandoc(monkeypatch, calls)
    ReportManager.export_pdf("rid")
    ReportManager.export_pdf("rid", force=True)
    assert len(calls) == 2


def test_export_pdf_rebuilds_when_cached_bytes_are_tampered(report_folder, monkeypatch):
    monkeypatch.setattr(Config, "REPORT_PDF_EXPORT", True, raising=False)
    (report_folder / "full_report.md").write_text("# R\n\nbody\n", encoding="utf-8")
    calls = []
    _install_fake_pandoc(monkeypatch, calls)
    pdf = ReportManager.export_pdf("rid")
    assert pdf and len(calls) == 1

    with open(pdf, "ab") as handle:
        handle.write(b"tampered")
    assert ReportManager.export_pdf("rid") == pdf
    assert len(calls) == 2


def test_export_pdf_is_single_flight_per_report_language(report_folder, monkeypatch):
    monkeypatch.setattr(Config, "REPORT_PDF_EXPORT", True, raising=False)
    (report_folder / "full_report.md").write_text("# R\n\nbody\n", encoding="utf-8")
    calls = []

    def _fake_pandoc(cls, report_id, md, folder, pdf_path):
        calls.append((report_id, pdf_path))
        time.sleep(0.05)
        with open(pdf_path, "wb") as handle:
            handle.write(b"%PDF-1.4 fake")
        return True

    monkeypatch.setattr(ReportManager, "_export_pdf_pandoc", classmethod(_fake_pandoc))
    monkeypatch.setattr(
        ReportManager,
        "_validate_pdf_content",
        staticmethod(lambda path, md: (True, {"page_count": 1, "issues": []})),
    )
    from app.services.translation.artifacts import ArtifactError
    results, conflicts = [], []
    def export():
        try:
            results.append(ReportManager.export_pdf("rid"))
        except ArtifactError as exc:
            conflicts.append(exc)
    threads = [threading.Thread(target=export) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        # Renderer fingerprinting and font discovery can legitimately take a
        # few seconds on a cold macOS host.  The product invariant here is one
        # render for five concurrent callers, not a two-second latency cap.
        thread.join(timeout=10)

    assert len(results) + len(conflicts) == 5 and len(set(results)) == 1
    assert all(error.code == "artifact_busy" and error.status_code == 409 for error in conflicts)
    assert len(calls) == 1


def test_rich_markdown_never_uses_structurally_degraded_fallback(
    report_folder, monkeypatch,
):
    monkeypatch.setattr(Config, "REPORT_PDF_EXPORT", True, raising=False)
    (report_folder / "full_report.md").write_text(
        "# R\n\n| Scenario | Probability |\n|---|---:|\n| Base | 60% |\n",
        encoding="utf-8",
    )
    fallback_calls = []
    monkeypatch.setattr(
        ReportManager,
        "_export_pdf_pandoc",
        classmethod(lambda cls, report_id, md, folder, pdf_path: False),
    )
    monkeypatch.setattr(
        ReportManager,
        "_export_pdf_pymupdf",
        classmethod(lambda cls, md, folder, pdf_path: fallback_calls.append(md) or True),
    )

    assert ReportManager.export_pdf("rid") is None
    assert fallback_calls == []


@pytest.mark.parametrize("delimiter", ["--- | ---", ":--- | ---:"])
def test_gfm_tables_without_outer_pipes_still_require_pandoc(delimiter):
    markdown = f"Scenario | Probability\n{delimiter}\nBase | 60%\n"
    assert ReportManager._markdown_requires_pandoc(markdown) is True


def test_pdf_content_gate_rejects_missing_unicode_and_han(tmp_path):
    import fitz

    path = tmp_path / "lossy.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "CO2 95 percent")
    document.save(path)
    document.close()

    source = "CO₂ ≥95% 中文预测报告需要保留所有中文字符和比较符号。"
    valid, audit = ReportManager._validate_pdf_content(str(path), source)
    assert valid is False
    assert audit["missing_protected_glyphs"]["₂"] == {"expected": 1, "actual": 0}
    assert audit["missing_protected_glyphs"]["≥"] == {"expected": 1, "actual": 0}
    assert "PDF text extraction lost representative Han content" in audit["issues"]


def test_pdf_content_gate_accepts_parseable_plain_text(tmp_path):
    import fitz

    path = tmp_path / "plain.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Plain report body")
    document.save(path)
    document.close()

    valid, audit = ReportManager._validate_pdf_content(str(path), "Plain report body")
    assert valid is True
    assert audit["page_count"] == 1
    assert audit["issues"] == []


@pytest.mark.parametrize("defect", [None, "numeric_claim", "url_target"])
def test_wrapped_visible_url_uses_exact_uri_carrier_without_relaxing_numeric_claims(tmp_path, defect):
    import fitz
    url = "https://example.test/copper-forecast-2027/60727111/"
    source = "# Outlook\n\nThe market forecast retains 25 MW of capacity.\n\n[" + url + "](" + url + ")\n"
    path = tmp_path / "wrapped-url.pdf"
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((72, 72), "Outlook")
        page.insert_text((72, 110), "The market forecast retains " + ("26" if defect == "numeric_claim" else "25") + " MW of capacity.")
        page.insert_text((72, 150), url[:-8])
        page.insert_text((72, 170), url[-8:])
        target = url.replace("60727111", "60727112") if defect == "url_target" else url
        for top in (138, 158):
            page.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(70, top, 500, top + 18), "uri": target})
        document.save(path)
    valid, audit = ReportManager._validate_pdf_content(str(path), source)
    assert valid is (defect is None), audit
    if defect == "numeric_claim":
        assert "25" in audit["missing_numeric_tokens"]
    elif defect == "url_target":
        assert audit["missing_url_sha256"] and "PDF lost visible URL destinations" in audit["issues"]
    else:
        assert audit["visible_url_carriers"] == 1 and not audit["missing_numeric_tokens"]


@pytest.mark.parametrize("rendered", ["12345.67892026-09", "12345.6789 2027-09"])
def test_numeric_cell_collisions_and_changed_values_remain_rejected(tmp_path, rendered):
    import fitz
    source = "# Measurements\n\nValue 12345.6789, period 2026-09.\n"
    path = tmp_path / "bad-cells.pdf"
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((72, 72), "Measurements")
        page.insert_text((72, 110), "Value " + rendered + " period.")
        document.save(path)
    valid, audit = ReportManager._validate_pdf_content(str(path), source)
    assert valid is False and "2026" in audit["missing_numeric_tokens"], audit
    if rendered == "12345.67892026-09":
        assert "12345.6789" in audit["missing_numeric_tokens"]


def test_changed_visible_url_cannot_supply_a_missing_operating_number(tmp_path):
    import fitz
    url = "https://example.test/copper/25/60727111/"
    source = "# Outlook\n\nThe forecast retains 25 MW of capacity.\n\n[" + url + "](" + url + ")\n"
    path = tmp_path / "changed-url-missing-claim.pdf"
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((72, 72), "Outlook")
        page.insert_text((72, 110), "The forecast retains MW of capacity.")
        page.insert_text((72, 150), url.replace("60727111", "60727112"))
        page.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(70, 138, 500, 158), "uri": url})
        document.save(path)
    valid, audit = ReportManager._validate_pdf_content(str(path), source)
    assert valid is False, audit
    assert audit["missing_visible_url_sha256"] and not audit["missing_url_sha256"]


@pytest.mark.parametrize("missing_claim", [False, True])
def test_prefix_url_labels_are_removed_longest_first_without_masking_claims(tmp_path, missing_claim):
    import fitz
    urls = ["https://example.test/", "https://example.test/2026"]
    source = "# Outlook\n\nThe delivery year is 2026. Capacity remains 25 MW.\n\n" + "\n\n".join(
        "[" + url + "](" + url + ")" for url in urls)
    path = tmp_path / "prefix-urls.pdf"
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((72, 72), "Outlook")
        page.insert_text((72, 110), "The delivery year is " + ("" if missing_claim else "2026") + ". Capacity remains 25 MW.")
        for y, url in zip((150, 180), urls):
            page.insert_text((72, y), url)
            page.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(70, y - 12, 400, y + 5), "uri": url})
        document.save(path)
    valid, audit = ReportManager._validate_pdf_content(str(path), source)
    assert valid is (not missing_claim), audit
    assert not audit["missing_visible_url_sha256"] and not audit["missing_url_sha256"]
    if missing_claim:
        assert "2026" in audit["missing_numeric_tokens"]


def test_native_renderer_uses_exact_trusted_wide_table_filter_and_cleans_it(report_folder, monkeypatch):
    calls = []
    _install_fake_pandoc(monkeypatch, calls)
    original_run = subprocess.run
    filters = []
    def inspect(cmd, **kwargs):
        argument = next(value for value in cmd if value.startswith("--lua-filter="))
        path = argument.split("=", 1)[1]
        with open(path, encoding="utf-8") as stream:
            text = stream.read()
        assert text == ReportManager._PDF_WIDE_TABLE_FILTER
        assert '#tbl.colspecs >= 7' in text and '\\begin{landscape}' in text
        assert 'pdflscape' in ' '.join(cmd)
        assert '--from=markdown-smart' in cmd
        filters.append(path)
        return original_run(cmd, **kwargs)
    monkeypatch.setattr(subprocess, "run", inspect)
    source = "# Measurements\n\n| A | B | C | D | E | F | G | H |\n|---|---|---|---|---|---|---|---|\n| a | b | 12345.6789 | 2026-09 | 25 | 35 | g | h |\n"
    assert ReportManager.export_document_pdf(source, str(report_folder), str(report_folder / "dense.pdf"))
    assert len(filters) == 1 and not os.path.exists(filters[0])


def test_rejected_export_logs_bounded_audit_codes_and_counts_without_content(report_folder, monkeypatch):
    from app.services import report_agent as module
    source = "# Private fixture heading\n\nDO_NOT_LOG_SOURCE_TOKEN_8364\n"
    calls, messages = [], []
    _install_fake_pandoc(monkeypatch, calls)
    monkeypatch.setattr(module.logger, "warning", lambda fmt, *args, **kwargs:
                        messages.append(fmt % args if args else fmt))
    monkeypatch.setattr(ReportManager, "_validate_pdf_content", staticmethod(lambda path, md: (False, {
        "page_count": 4,
        "issues": ["PDF lost visible numeric tokens", "PDF is missing 1 rendered section headings",
                   "DO_NOT_LOG_UNTRUSTED_DETAIL_7362"],
        "missing_numeric_tokens": {"DO_NOT_LOG_NUMERIC_KEY_6253": {"expected": 3, "actual": 1}},
        "missing_heading_sha256": ["DO_NOT_LOG_HEADING_5234"],
        "latin_word_coverage": .99,
    })))
    assert ReportManager.export_document_pdf(source, str(report_folder), str(report_folder / "private.pdf"),
        label="DO_NOT_LOG_LABEL_4215") is None
    audits = [line for line in messages if line.startswith("PDF content audit rejected ")]
    assert len(audits) == 1, messages
    message = audits[0]
    assert "numeric_tokens_missing" in message and "headings_missing" in message
    assert '"missing_numeric_token_kinds": 1' in message and '"page_count": 4' in message
    assert "DO_NOT_LOG" not in message and "Private fixture heading" not in message
    assert str(report_folder) not in message and len(message) < 1800


@pytest.mark.parametrize("omit_fragment", [False, True])
def test_pdf_short_han_fragment_does_not_require_whole_report_contiguity(tmp_path, omit_fragment):
    """Real PDF with a short CJK marker moved by table/footnote reading order."""
    import fitz
    path = tmp_path / "english-with-han.pdf"
    source = ("# Capacity outlook\n\n"
              "The forecast projects steady demand growth across the regional markets.\n\n"
              "| Region | Value |\n|---|---:|\n| Base | 25 MW |\n\n中文验证完成\n")
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((72, 72), "Capacity outlook")
        if not omit_fragment:
            page.insert_text((72, 105), "中文验证完成", fontname="china-s")
        page.insert_text((72, 145), "The forecast projects steady demand growth across the regional markets.")
        page.insert_text((72, 185), "Region   Value\nBase     25 MW")
        document.save(path)
    valid, audit = ReportManager._validate_pdf_content(str(path), source)
    assert valid is (not omit_fragment), audit
    assert not audit["missing_numeric_tokens"] and not audit["missing_heading_sha256"]
    if omit_fragment:
        assert audit["missing_han_chars"] and "PDF text extraction lost visible Han content" in audit["issues"]


@pytest.mark.parametrize("omit_fragment", [False, True])
def test_pdf_short_latin_fragment_does_not_require_whole_chinese_document_contiguity(tmp_path, omit_fragment):
    import fitz
    path = tmp_path / "chinese-with-latin.pdf"
    body = "全球电力系统正在重构，电池成本下降推动长期储能部署。区域政策和并网瓶颈共同决定商业化速度。"
    source = "# 储能展望\n\n" + body + "\n\nAlpha Beta\n"
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((72, 72), "储能展望", fontname="china-s")
        page.insert_text((72, 105), "Alpha" if omit_fragment else "Alpha Beta")
        page.insert_textbox(fitz.Rect(72, 145, 520, 400), body, fontname="china-s")
        document.save(path)
    valid, audit = ReportManager._validate_pdf_content(str(path), source)
    assert valid is (not omit_fragment), audit
    if omit_fragment:
        assert "PDF text extraction lost visible Latin content" in audit["issues"]


def test_visible_text_omits_defined_footnote_keys_but_preserves_prose_and_literal_code():
    markdown = ("正文[^audit]。\n\n[^audit]: Footnote body remains visible.\n\n"
                "`[^literal]`\n\n```text\n[^code]: a code example\n```\n\n"
                "An undefined [^undefined] stays literal.\n")
    visible = ReportManager._markdown_visible_text(markdown)
    assert "audit" not in visible
    assert "Footnote body remains visible." in visible
    assert "[^literal]" in visible and "[^code]: a code example" in visible
    assert "[^undefined]" in visible


@pytest.mark.parametrize("omit_body", [False, True])
def test_pdf_footnote_identifiers_are_not_visible_latin_but_body_is_required(tmp_path, omit_body):
    import fitz
    path = tmp_path / "footnote.pdf"
    source = "# 产能展望\n\n这份中文报告保留完整的可见内容，脚注使用编号呈现[^audit]。\n\n[^audit]: Footnote evidence.\n"
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((72, 72), "产能展望", fontname="china-s")
        page.insert_textbox(fitz.Rect(72, 110, 520, 300),
                           "这份中文报告保留完整的可见内容，脚注使用编号呈现1。", fontname="china-s")
        if not omit_body:
            page.insert_text((72, 340), "1 Footnote evidence.")
        document.save(path)
    valid, audit = ReportManager._validate_pdf_content(str(path), source)
    assert valid is (not omit_body), audit
    if omit_body:
        assert "PDF text extraction lost visible Latin content" in audit["issues"]


def test_pdf_content_gate_rejects_truncated_sections_numbers_and_citations(tmp_path):
    import fitz

    path = tmp_path / "truncated.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Executive Summary")
    document.save(path)
    document.close()

    source = (
        "# Global Forecast\n\n"
        "## Executive Summary\n\n"
        "Deployment reaches 42% by 2035 according to the cited baseline [S1].\n\n"
        "## Regional Outlook\n\n"
        "Europe and Asia follow materially different infrastructure pathways.\n\n"
        "## References\n\n1. [S1] Published baseline.\n"
    )
    valid, audit = ReportManager._validate_pdf_content(str(path), source)
    assert valid is False
    assert audit["missing_numeric_tokens"]["42%"] == {"expected": 1, "actual": 0}
    assert audit["missing_numeric_tokens"]["2035"] == {"expected": 1, "actual": 0}
    assert audit["missing_citation_markers"]["S1"]["actual"] == 0
    assert len(audit["missing_heading_sha256"]) >= 2
    assert "PDF text extraction lost substantial Latin content" in audit["issues"]


def test_pdf_content_gate_rejects_duplicated_partial_han_text(tmp_path):
    import fitz

    path = tmp_path / "partial-han.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text(
        (72, 72),
        "全球电力系统全球电力系统全球电力系统全球电力系统",
        fontname="china-s",
    )
    document.save(path)
    document.close()

    source = (
        "# 全球储能预测\n\n"
        "全球电力系统正在重构，电池成本下降推动长期储能部署。"
        "区域政策、并网瓶颈、循环寿命和制造能力共同决定商业化速度。"
    )
    valid, audit = ReportManager._validate_pdf_content(str(path), source)
    assert valid is False
    assert audit["extracted_han_chars"] >= 20
    assert audit["han_bigram_coverage"] < 0.72
    assert "PDF text extraction lost representative Han content" in audit["issues"]


def test_export_pdf_falls_back_when_pandoc_bad(report_folder, monkeypatch):
    """pandoc 吐出非 PDF（%PDF 门失败）→ 回退 PyMuPDF；无 pymupdf 时整体 None。"""
    monkeypatch.setattr(Config, "REPORT_PDF_EXPORT", True, raising=False)
    (report_folder / "full_report.md").write_text("# R\n\nbody\n", encoding="utf-8")
    monkeypatch.setattr(ReportManager, "_resolve_pandoc",
                        classmethod(lambda cls: ("/fake/pandoc", "/fake/xelatex")))
    monkeypatch.setattr(
        ReportManager,
        "_resolve_pdf_fonts",
        classmethod(lambda cls: {
            "main": {"family": "Fake Sans", "file": __file__},
            "cjk": {"family": "Fake CJK", "file": __file__},
            "mono": {"family": "Fake Mono", "file": __file__},
        }),
    )

    def _bad_run(cmd, *args, **kwargs):
        out = cmd[cmd.index("-o") + 1]
        with open(out, "wb") as f:
            f.write(b"<html>not a pdf</html>")   # 非 %PDF → _is_pdf_file 拦截

        class _P:
            returncode = 0
            stderr = b""
        return _P()

    monkeypatch.setattr(subprocess, "run", _bad_run)
    fb_called = {"n": 0}

    def _fake_fb(cls, md, folder, pdf_path):
        fb_called["n"] += 1
        with open(pdf_path, "wb") as f:
            f.write(b"%PDF-1.4\n%%EOF\n")
        return True

    monkeypatch.setattr(ReportManager, "_export_pdf_pymupdf", classmethod(_fake_fb))
    monkeypatch.setattr(
        ReportManager,
        "_validate_pdf_content",
        staticmethod(lambda pdf_path, markdown: (True, {"page_count": 1, "issues": []})),
    )
    pdf = ReportManager.export_pdf("rid")
    assert pdf and os.path.exists(pdf)
    assert fb_called["n"] == 1                    # pandoc 失败后走了回退


def test_export_pdf_disabled_returns_none(report_folder, monkeypatch):
    """REPORT_PDF_EXPORT 关闭 → None（端点据此 404）。"""
    monkeypatch.setattr(Config, "REPORT_PDF_EXPORT", False, raising=False)
    (report_folder / "full_report.md").write_text("# R\n", encoding="utf-8")
    assert ReportManager.export_pdf("rid") is None


def test_export_pdf_missing_markdown_returns_none(report_folder, monkeypatch):
    """无 full_report.md → None（degrade-safe）。"""
    monkeypatch.setattr(Config, "REPORT_PDF_EXPORT", True, raising=False)
    assert ReportManager.export_pdf("rid") is None
