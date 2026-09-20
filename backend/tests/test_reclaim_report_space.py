"""scripts/reclaim_report_space.py 的安全闸回归（owner 签核的 1.57GB 回收工具）。

钉住：备份清除的名字/位置白名单（只有 reports/<id>/.codex-backup-<ts>/ 一级目录）、
de-inline 的唯一包识别 + fail-closed 跳过、幂等、dry-run 不动盘。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "reclaim_report_space.py"
spec = importlib.util.spec_from_file_location("reclaim_report_space", _SCRIPT)
assert spec and spec.loader
rrs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rrs)


def _mk_bundle_html(payload: str = "Plotly.newPlot('div1', data);") -> str:
    bundle = "/* plotly.js v2.27.0 fake bundle */" + ("x" * rrs.MIN_BUNDLE_CHARS)
    return (
        "<html><head>"
        '<script type="text/javascript">window.PlotlyConfig = {};</script>'
        f'<script type="text/javascript">{bundle}</script>'
        "</head><body><div id=\"div1\" class=\"plotly-graph-div\"></div>"
        f'<script type="text/javascript">{payload}</script>'
        "</body></html>"
    )


def _mk_report(root: Path, rid: str) -> Path:
    d = root / rid
    (d / "charts").mkdir(parents=True)
    return d


def test_backup_finder_whitelist(tmp_path):
    rep = _mk_report(tmp_path, "report_aaa")
    good = rep / ".codex-backup-20260710T222108Z"
    good.mkdir()
    (rep / ".codex-backup-notatimestamp").mkdir()        # 名字不匹配 → 不碰
    (rep / "charts" / ".codex-backup-20260710T222108Z").mkdir()  # 层级过深 → 不碰
    (tmp_path / ".codex-backup-20260710T222108Z").mkdir()        # 根层 → 不碰
    found = rrs.find_backup_dirs(tmp_path)
    assert found == [good]


def test_purge_backups_dry_run_then_apply(tmp_path):
    rep = _mk_report(tmp_path, "report_aaa")
    b = rep / ".codex-backup-20260710T222108Z"
    b.mkdir()
    (b / "big.bin").write_bytes(b"z" * 1000)
    n, size = rrs.purge_backups(tmp_path, apply=False)
    assert (n, size) == (1, 1000) and b.exists()          # dry-run 不动盘
    n2, _ = rrs.purge_backups(tmp_path, apply=True)
    assert n2 == 1 and not b.exists()
    assert rrs.purge_backups(tmp_path, apply=True) == (0, 0)  # 幂等


def test_deinline_converts_and_is_idempotent(tmp_path):
    rep = _mk_report(tmp_path, "report_bbb")
    h = rep / "charts" / "trend.html"
    h.write_text(_mk_bundle_html(), encoding="utf-8")
    before = h.stat().st_size

    c, s, freed = rrs.deinline_charts(tmp_path, apply=True)
    assert (c, s) == (1, 0) and freed > rrs.MIN_BUNDLE_CHARS
    out = h.read_text(encoding="utf-8")
    assert rrs.DIRECTORY_TAG in out
    assert "Plotly.newPlot" in out                        # 图形负载保留
    assert h.stat().st_size < before // 10
    bundle = rep / "charts" / "plotly.min.js"
    assert bundle.exists() and "plotly.js v2.27.0" in bundle.read_text(encoding="utf-8")[:200]
    # 幂等：已是 directory 模式 → 不再改写
    assert rrs.deinline_charts(tmp_path, apply=True) == (0, 0, 0)


def test_deinline_fails_closed_on_ambiguity_and_missing_payload(tmp_path):
    rep = _mk_report(tmp_path, "report_ccc")
    # 两个候选包 → 不唯一 → 跳过
    twin = _mk_bundle_html() .replace("</body>",
        f'<script type="text/javascript">/* plotly.js second */{"y" * rrs.MIN_BUNDLE_CHARS}</script></body>')
    (rep / "charts" / "twin.html").write_text(twin, encoding="utf-8")
    # 无图形负载 → 跳过（绝不产出空壳）
    bare = _mk_bundle_html(payload="console.log('nofigure')").replace(
        'class="plotly-graph-div"', 'class="x"')
    (rep / "charts" / "bare.html").write_text(bare, encoding="utf-8")

    c, s, _ = rrs.deinline_charts(tmp_path, apply=True)
    assert c == 0 and s == 2
    assert "plotly.js second" in (rep / "charts" / "twin.html").read_text(encoding="utf-8")
    assert not (rep / "charts" / "plotly.min.js").exists()


def test_small_html_without_bundle_untouched(tmp_path):
    rep = _mk_report(tmp_path, "report_ddd")
    h = rep / "charts" / "note.html"
    h.write_text("<html><body>static</body></html>", encoding="utf-8")
    assert rrs.deinline_charts(tmp_path, apply=True) == (0, 0, 0)
    assert h.read_text(encoding="utf-8") == "<html><body>static</body></html>"


def test_deinline_handles_bare_script_tags_plotly_v6(tmp_path):
    """真实 v6 图表用裸 <script>（无 type 属性）——检测器必须两种都认。"""
    rep = _mk_report(tmp_path, "report_eee")
    bundle = "/**\n* plotly.js v3.6.0\n*/" + ("z" * rrs.MIN_BUNDLE_CHARS)
    html = ("<html><head><meta charset=\"utf-8\" /></head><body>"
            "<script>window.PlotlyConfig = {MathJaxConfig: 'local'};</script>"
            f"<script>{bundle}</script>"
            "<div id=\"d\" class=\"plotly-graph-div\"></div>"
            "<script>Plotly.newPlot('d', []);</script>"
            "</body></html>")
    h = rep / "charts" / "v6.html"
    h.write_text(html, encoding="utf-8")
    c, s, freed = rrs.deinline_charts(tmp_path, apply=True)
    assert (c, s) == (1, 0) and freed > rrs.MIN_BUNDLE_CHARS
    out = h.read_text(encoding="utf-8")
    assert rrs.DIRECTORY_TAG in out and "Plotly.newPlot" in out
    # 外链 <script src=...> 绝不会被当成内联包再抽一次（幂等再跑 0 改写）
    assert rrs.deinline_charts(tmp_path, apply=True) == (0, 0, 0)
