"""回收 uploads/reports 的磁盘占用（owner 于 2026-08-18 签核的 1.57GB 回收）。

两个独立操作（默认 dry-run，加 --apply 才动盘）：

1) --purge-backups：删除 reports/<id>/.codex-backup-<UTC时间戳>/ 快照目录。
   这些是 2026-07-10/11 一次 codex 编辑会话留下的整目录时间点副本（35 个、共 ~1.41GB），
   活报告目录就是最终态，快照纯冗余。安全闸：名字必须精确匹配
   ^\\.codex-backup-\\d{8}T\\d{6}Z$、必须是目录、必须恰好位于 reports/<id>/ 一级之下；
   其余一概不碰。

2) --deinline-charts：把旧报告 charts/*.html 里内联的 ~4.6MB plotly 包抽出为
   目录级共享 plotly.min.js（i1 的 directory 模式），HTML 里替换成
   <script src="plotly.min.js"></script>。serve 路径不受影响：utils/chart_html.py 的
   inline_plotly_bundle 在服务时把 sibling 包拼回去（API 行为不变），浏览器直接打开
   目录里的 HTML 也照常工作。fail-closed：每个文件必须恰好识别出一个 >1MB 且头部带
   plotly.js 签名的 <script> 块，且改写后仍含图形负载，否则跳过并警告，绝不改写。
   抽出的包按首个抽取写入（同目录图表来自同一渲染批次，版本一致；后续文件只校验
   尺寸一致，不一致则该文件跳过）。

用法：
    .venv/bin/python scripts/reclaim_report_space.py                    # dry-run 全部
    .venv/bin/python scripts/reclaim_report_space.py --apply --purge-backups --deinline-charts
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from pathlib import Path

BACKUP_RE = re.compile(r"^\.codex-backup-\d{8}T\d{6}Z$")
# plotly.py 各版本写法不同：v5 era `<script type="text/javascript">`，v6 era 裸 `<script>`。
# 统一按 `<script` 起扫，标签体内不得含 src=（外链脚本不是内联包）。
SCRIPT_PREFIX = "<script"
SCRIPT_CLOSE = "</script>"
DIRECTORY_TAG = '<script src="plotly.min.js"></script>'
MIN_BUNDLE_CHARS = 1_000_000
SIGNATURE_WINDOW = 4_000


def _reports_root() -> Path:
    backend = Path(__file__).resolve().parents[1]
    return backend / "uploads" / "reports"


def find_backup_dirs(root: Path) -> list[Path]:
    out: list[Path] = []
    for report_dir in sorted(root.iterdir() if root.is_dir() else []):
        if not report_dir.is_dir():
            continue
        for child in sorted(report_dir.iterdir()):
            if child.is_dir() and not child.is_symlink() and BACKUP_RE.match(child.name):
                out.append(child)
    return out


def _dir_bytes(path: Path) -> int:
    total = 0
    for dirpath, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.lstat(os.path.join(dirpath, name)).st_size
            except OSError:
                pass
    return total


def purge_backups(root: Path, apply: bool) -> tuple[int, int]:
    """返回 (目录数, 字节数)。apply=False 只测量。"""
    dirs = find_backup_dirs(root)
    total = sum(_dir_bytes(d) for d in dirs)
    for d in dirs:
        print(f"  {'DELETE' if apply else 'would delete'}  {d.relative_to(root)}")
        if apply:
            shutil.rmtree(d)
    return len(dirs), total


def extract_inline_bundle(html: str) -> tuple[str, str] | None:
    """定位唯一的内联 plotly 包块。返回 (改写后的 html, 包内容)；识别不唯一/缺失 → None。

    不用正则吞 4MB 串——按 find 游标扫 <script type="text/javascript">…</script> 跨度，
    候选 = 内容 >1MB 且头部 4KB 含 'plotly.js' 签名。"""
    spans: list[tuple[int, int, str]] = []  # (start, end_after_close, content)
    cursor = 0
    while True:
        start = html.find(SCRIPT_PREFIX, cursor)
        if start < 0:
            break
        tag_end = html.find(">", start)
        if tag_end < 0:
            break
        tag = html[start:tag_end + 1]
        content_start = tag_end + 1
        end = html.find(SCRIPT_CLOSE, content_start)
        if end < 0:
            break
        content = html[content_start:end]
        if ("src=" not in tag
                and len(content) >= MIN_BUNDLE_CHARS
                and "plotly.js" in content[:SIGNATURE_WINDOW]):
            spans.append((start, end + len(SCRIPT_CLOSE), content))
        cursor = end + len(SCRIPT_CLOSE)
    if len(spans) != 1:
        return None
    start, end, content = spans[0]
    return html[:start] + DIRECTORY_TAG + html[end:], content


def deinline_charts(root: Path, apply: bool) -> tuple[int, int, int]:
    """返回 (改写文件数, 跳过数, 回收字节数)。"""
    converted = skipped = freed = 0
    for charts_dir in sorted(root.glob("*/charts")):
        bundle_path = charts_dir / "plotly.min.js"
        bundle_size = bundle_path.stat().st_size if bundle_path.exists() else None
        for html_path in sorted(charts_dir.glob("*.html")):
            try:
                html = html_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                print(f"  SKIP (unreadable) {html_path.name}: {exc}")
                skipped += 1
                continue
            if DIRECTORY_TAG in html:
                continue  # 已是 directory 模式
            result = extract_inline_bundle(html)
            if result is None:
                if len(html) > MIN_BUNDLE_CHARS:
                    print(f"  SKIP (no unique plotly bundle) {charts_dir.parent.name}/{html_path.name}")
                    skipped += 1
                continue
            new_html, bundle = result
            # 改写后仍须含图形负载（fail-closed，绝不产出空壳 HTML）。
            if "Plotly.newPlot" not in new_html and "plotly-graph-div" not in new_html:
                print(f"  SKIP (no figure payload after rewrite) {html_path.name}")
                skipped += 1
                continue
            if bundle_size is not None and bundle_size != len(bundle.encode("utf-8")):
                print(f"  SKIP (bundle size mismatch vs existing plotly.min.js) {html_path.name}")
                skipped += 1
                continue
            saved = len(html) - len(new_html)
            print(f"  {'REWRITE' if apply else 'would rewrite'} "
                  f"{charts_dir.parent.name}/{html_path.name} (−{saved / 1e6:.1f}MB)")
            if apply:
                if bundle_size is None:
                    tmp_b = bundle_path.with_suffix(".js.tmp")
                    tmp_b.write_text(bundle, encoding="utf-8")
                    os.replace(tmp_b, bundle_path)
                    bundle_size = bundle_path.stat().st_size
                tmp = html_path.with_suffix(".html.tmp")
                tmp.write_text(new_html, encoding="utf-8")
                os.replace(tmp, html_path)
            converted += 1
            freed += saved
    return converted, skipped, freed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="实际执行（缺省 dry-run）")
    parser.add_argument("--purge-backups", action="store_true")
    parser.add_argument("--deinline-charts", action="store_true")
    parser.add_argument("--root", default=None, help="覆盖 reports 根目录（测试用）")
    args = parser.parse_args(argv)
    do_all = not (args.purge_backups or args.deinline_charts)
    root = Path(args.root) if args.root else _reports_root()
    if not root.is_dir():
        print(f"reports root 不存在: {root}", file=sys.stderr)
        return 1
    mode = "APPLY" if args.apply else "DRY-RUN"
    total_freed = 0
    if do_all or args.purge_backups:
        print(f"[{mode}] purge .codex-backup-* snapshots under {root}")
        n, b = purge_backups(root, args.apply)
        print(f"  → {n} dirs, {b / 1e9:.2f} GB")
        total_freed += b
    if do_all or args.deinline_charts:
        print(f"[{mode}] de-inline plotly bundles under {root}/*/charts")
        c, s, b = deinline_charts(root, args.apply)
        print(f"  → {c} rewritten, {s} skipped, {b / 1e6:.0f} MB")
        total_freed += b
    print(f"[{mode}] total {'reclaimed' if args.apply else 'reclaimable'}: "
          f"{total_freed / 1e9:.2f} GB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
