"""Build an offline, bilingual preview of already-rendered PDF bytes.

The caller owns PDF generation and the review decision. This module only checks
byte integrity and presents that decision; it never approves report content.
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
import os
from pathlib import Path
import re
from string import Template
import tempfile

import fitz


_LANGUAGES = ("en", "zh-CN")
_DEFAULT_REASON = "Source reconciliation, semantic review, and visual review are required before export."
_PREVIEW_DPI = 120

_CSS = """
:root { color-scheme: light; --navy: #142c46; --ink: #203247; --muted: #536478;
  --line: #d9e1e9; --paper: #fff; --wash: #f3f5f8; --accent: #315d87; }
* { box-sizing: border-box; }
body { margin: 0; background: var(--wash); color: var(--ink);
  font: 15px/1.65 -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; }
button, a { -webkit-tap-highlight-color: transparent; }
button { font: inherit; }
a { color: var(--navy); }
:focus-visible { outline: 3px solid #c07512; outline-offset: 4px; }
.skip { position: absolute; top: -80px; left: 20px; padding: 12px 20px; background: white; z-index: 2; }
.skip:focus { top: 10px; }
.masthead { border-top: 5px solid var(--navy); background: var(--paper); border-bottom: 1px solid var(--line); }
.masthead-inner { max-width: 1180px; margin: auto; padding: 20px 36px; display: flex; flex-wrap: wrap;
  gap: 8px 24px; justify-content: space-between; align-items: center; }
.wordmark { color: var(--navy); font-size: 13px; font-weight: 750; letter-spacing: .14em; text-transform: uppercase; }
.edition { color: var(--muted); font-size: 12px; letter-spacing: .06em; }
main { max-width: 1180px; margin: auto; padding: 52px 36px 36px; }
.eyebrow { color: var(--accent); font-size: 11px; font-weight: 750; letter-spacing: .17em; text-transform: uppercase; margin: 0 0 14px; }
h1 { font-family: Georgia, "Times New Roman", serif; font-size: clamp(30px, 4vw, 46px); font-weight: 500;
  line-height: 1.15; letter-spacing: -.025em; margin: 0; max-width: 920px; overflow-wrap: anywhere; }
.translated-title { font-size: 19px; margin: 16px 0 0; color: var(--muted); overflow-wrap: anywhere; }
.intro { max-width: 700px; margin: 20px 0 30px; color: var(--muted); }
.review { border: 1px solid var(--line); border-left: 4px solid var(--navy); background: white;
  padding: 17px 22px; margin-bottom: 28px; }
.review[data-state="draft"] { border-left-color: #9a6518; }
.review[data-state="error"] { border-left-color: #a03131; }
.review strong { font-size: 14px; }
.review p { margin: 3px 0 0; font-size: 13px; color: var(--muted); overflow-wrap: anywhere; }
.languages { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 22px; }
.language { background: var(--paper); border: 1px solid var(--line); padding: 28px; min-width: 0; }
.language-top { display: flex; align-items: start; justify-content: space-between; gap: 16px; }
.language h2 { font-size: 23px; line-height: 1.3; font-weight: 650; margin: 4px 0; }
.language-code { color: var(--accent); font-size: 11px; letter-spacing: .1em; font-weight: 700; border: 1px solid var(--line); padding: 5px 9px; }
.metadata { color: var(--muted); font-size: 13px; margin: 10px 0 22px; }
.actions { display: grid; gap: 10px; }
button { min-height: 46px; border: 1px solid var(--navy); cursor: pointer; padding: 10px 16px;
  background: var(--navy); color: white; font-size: 14px; font-weight: 650; border-radius: 3px; }
button:hover:not(:disabled) { background: #244969; }
button.preview { background: white; color: var(--navy); }
button.preview:hover:not(:disabled), button.preview[aria-pressed="true"] { background: #eef3f8; }
button:disabled { cursor: not-allowed; background: #e9edf2; color: #566477; border-color: #d5dde6; }
details { margin-top: 20px; font-size: 12px; color: var(--muted); }
summary { cursor: pointer; padding: 3px 0; }
.digest { display: block; margin-top: 8px; font: 11px/1.6 ui-monospace, SFMono-Regular, monospace; overflow-wrap: anywhere; }
.viewer { background: white; border: 1px solid var(--line); margin-top: 30px; }
.viewer-bar { padding: 18px 24px; border-bottom: 1px solid var(--line); display: flex; flex-wrap: wrap;
  justify-content: space-between; gap: 8px 20px; align-items: center; }
.viewer-bar h2 { font-size: 16px; margin: 0; }
.viewer-bar span { font-size: 12px; color: var(--muted); }
.viewer-note { padding: 12px 24px; margin: 0; font-size: 12px; color: var(--muted); }
.page-preview { padding: 24px; background: #e9edf2; }
.page-preview[hidden] { display: none; }
.page-preview figure { max-width: 1020px; margin: 0 auto 28px; }
.page-preview figure:last-child { margin-bottom: 0; }
.page-preview figcaption { margin-bottom: 10px; color: var(--muted); font-size: 12px; }
.page-preview img { display: block; width: 100%; height: auto; background: white;
  box-shadow: 0 2px 10px #142c461a; }
.viewer-placeholder { text-align: center; color: var(--muted); padding: 70px 24px; }
footer { margin-top: 28px; padding-top: 20px; border-top: 1px solid var(--line); font-size: 12px; color: var(--muted); }
footer p { margin: 4px 0; }
noscript p { padding: 18px; border: 1px solid #9a6518; background: white; }
@media (max-width: 680px) {
  .masthead-inner { padding: 18px 20px; } main { padding: 32px 20px; }
  .languages { grid-template-columns: 1fr; gap: 16px; } .language { padding: 22px; }
  .page-preview { padding: 12px; } .viewer-bar, .viewer-note { padding-left: 18px; padding-right: 18px; }
}
@media (prefers-reduced-motion: reduce) { * { scroll-behavior: auto; } }
"""

_JS = """
(() => {
  'use strict';
  const review = document.getElementById('review');
  const status = document.getElementById('status');
  const reason = document.getElementById('reason');
  const integrity = document.getElementById('integrity');
  const viewer = document.getElementById('page-preview');
  const placeholder = document.getElementById('viewer-placeholder');
  const viewerLabel = document.getElementById('viewer-label');
  const keys = ['en', 'zh-CN'];
  const labels = {en: 'English', 'zh-CN': '简体中文'};
  const verified = new Map();
  let data;

  function fail() {
    for (const key of keys) {
      document.getElementById('export-' + key).disabled = true;
      const button = document.getElementById('preview-' + key);
      button.disabled = true;
      button.setAttribute('aria-pressed', 'false');
    }
    viewer.replaceChildren();
    viewer.hidden = true;
    placeholder.hidden = false;
    placeholder.textContent = 'Preview unavailable until the embedded files and page images can be verified.';
    for (const item of verified.values()) URL.revokeObjectURL(item.url);
    verified.clear();
    review.dataset.state = 'error';
    status.textContent = 'File verification failed · 文件校验失败';
    reason.textContent = 'Export is disabled. Rebuild this preview from the reviewed PDFs, or open it in a browser with local SHA-256 support.';
    integrity.textContent = 'Embedded PDFs or page images could not be verified.';
    review.setAttribute('aria-busy', 'false');
  }

  function show(key) {
    if (!verified.has(key)) return;
    viewer.replaceChildren();
    viewer.lang = key;
    viewer.dataset.language = key;
    viewer.setAttribute('aria-label', labels[key] + ' report pages');
    const pages = data.languages[key].pages;
    for (const [index, entry] of verified.get(key).images.entries()) {
      const label = key === 'zh-CN' ? '简体中文报告，第 ' + (index + 1) + ' 页，共 ' + pages + ' 页'
        : 'English report, page ' + (index + 1) + ' of ' + pages;
      const figure = document.createElement('figure');
      const caption = document.createElement('figcaption');
      caption.textContent = label;
      const image = document.createElement('img');
      image.alt = label;
      image.width = entry.width;
      image.height = entry.height;
      image.loading = index === 0 ? 'eager' : 'lazy';
      image.src = entry.url;
      image.addEventListener('error', fail, {once: true});
      figure.append(caption, image);
      viewer.append(figure);
    }
    viewer.hidden = false;
    placeholder.hidden = true;
    const count = key === 'zh-CN' ? pages + ' 页' : pages + (pages === 1 ? ' page' : ' pages');
    viewerLabel.textContent = labels[key] + ' · ' + count;
    for (const language of keys) {
      document.getElementById('preview-' + language).setAttribute('aria-pressed', String(language === key));
    }
  }

  async function verifyBytes(base64, expected) {
    const bytes = Uint8Array.from(atob(base64), character => character.charCodeAt(0));
    const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', bytes));
    const actual = Array.from(digest, byte => byte.toString(16).padStart(2, '0')).join('');
    if (actual !== expected) throw new Error('Embedded byte digest mismatch');
    return bytes;
  }

  async function initialize() {
    try {
      data = JSON.parse(document.getElementById('report-data').textContent);
      if (!globalThis.crypto || !globalThis.crypto.subtle) throw new Error('SHA-256 unavailable');
      // Page images are rendered from these exact PDF bytes during the build.
      // Verify both PDFs and every image before enabling either language.
      for (const key of keys) {
        const entry = data.languages[key];
        const bytes = await verifyBytes(entry.base64, entry.sha256);
        if (bytes.length !== entry.bytes) throw new Error('PDF byte length mismatch');
        if (!Array.isArray(entry.images) || entry.images.length !== entry.pages) throw new Error('Page images missing');
        const images = [];
        for (const image of entry.images) {
          await verifyBytes(image.base64, image.sha256);
          images.push({url: 'data:image/png;base64,' + image.base64, width: image.width, height: image.height});
        }
        const blob = new Blob([bytes], {type: 'application/pdf'});
        verified.set(key, {url: URL.createObjectURL(blob), images});
      }
      for (const key of keys) {
        const preview = document.getElementById('preview-' + key);
        preview.disabled = false;
        preview.addEventListener('click', () => show(key));
        const button = document.getElementById('export-' + key);
        button.disabled = data.ready !== true;
        button.addEventListener('click', () => {
          if (data.ready !== true || !verified.has(key)) return;
          const anchor = document.createElement('a');
          anchor.href = verified.get(key).url;
          anchor.download = data.languages[key].filename;
          document.body.appendChild(anchor);
          anchor.click();
          anchor.remove();
        });
      }
      review.dataset.state = data.ready === true ? 'ready' : 'draft';
      status.textContent = data.ready === true ? 'Ready to export · 可导出' : 'Review required · 待审核';
      reason.textContent = data.ready === true
        ? 'Marked reviewed by the publishing workflow. Both embedded PDFs passed the local integrity check.'
        : data.reason;
      integrity.textContent = 'PDFs and page images verified locally · PDF 与页面图像均已完成本地校验';
      review.setAttribute('aria-busy', 'false');
      show('en');
    } catch {
      fail();
    }
  }
  // Keep URLs alive for repeat downloads and back/forward cache restoration.
  // The browser releases the document's Blob URLs when the document is destroyed.
  initialize();
})();
"""

_DOCUMENT = Template("""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="$csp">
<meta name="referrer" content="no-referrer">
<title>$english_title — Research PDF export</title>
<style>$css</style>
</head>
<body>
<a class="skip" href="#main">Skip to report exports</a>
<header class="masthead"><div class="masthead-inner">
  <span class="wordmark">Equity Research</span><span class="edition">REPORT LIBRARY &nbsp; / &nbsp; PDF EXPORT</span>
</div></header>
<main id="main">
  <p class="eyebrow">Bilingual research edition</p>
  <h1>$english_title</h1>
  <p class="translated-title" lang="zh-CN">$chinese_title</p>
  <p class="intro">Preview the report in English or Simplified Chinese, then save the reviewed edition. Both files are included in this page for offline use.</p>
  <section class="review" id="review" data-state="$state" role="status" aria-live="polite" aria-atomic="true" aria-busy="true" aria-labelledby="status">
    <strong id="status">$status</strong><p id="reason">$reason</p>
    <p id="integrity">Checking the integrity of the embedded PDFs…</p>
  </section>
  <noscript><p>JavaScript is required to verify the embedded PDFs. Preview and export remain disabled. <span lang="zh-CN">需要启用 JavaScript 才能校验文件；预览和导出当前不可用。</span></p></noscript>
  <div class="languages" aria-label="Report language editions">$cards</div>
  <section class="viewer" aria-labelledby="viewer-heading">
    <div class="viewer-bar"><h2 id="viewer-heading">Report preview <span lang="zh-CN">/ 报告预览</span></h2>
      <span id="viewer-label" aria-live="polite">Awaiting file verification</span></div>
    <p class="viewer-note" id="viewer-note">All report pages are shown below as embedded images. After review, export the original PDF for selectable text and links. <span lang="zh-CN">以下为完整页面图像；审核后可导出原始 PDF，使用文本选择和链接。</span></p>
    <p class="viewer-placeholder" id="viewer-placeholder">Verifying the embedded report files…</p>
    <div class="page-preview" id="page-preview" role="region" aria-label="Report pages" aria-describedby="viewer-note" hidden></div>
  </section>
  <footer><p>Local document package · Embedded PDFs · No external services</p>
    <p>Integrity checks confirm file bytes. Content accuracy and translation quality require source reconciliation and human review.</p></footer>
</main>
<script id="report-data" type="application/json">$data</script>
<script>$javascript</script>
</body>
</html>
""")


def _script_json(value: dict) -> str:
    """JSON escaping alone does not stop an HTML parser's </script> token."""
    return (
        json.dumps(value, ensure_ascii=True, separators=(",", ":"))
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def _csp_hash(text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return "'sha256-" + base64.b64encode(digest).decode("ascii") + "'"


def _page_images(raw: bytes, *, pages: int, language: str) -> list[dict]:
    """Rasterize the verified in-memory bytes, never a second read of the path."""
    try:
        with fitz.open(stream=raw, filetype="pdf") as document:
            if not document.is_pdf or document.needs_pass:
                raise ValueError("an unencrypted PDF is required")
            if document.page_count != pages:
                raise ValueError(f"page count mismatch: expected {pages}, found {document.page_count}")
            images = []
            for page in document:
                pixmap = page.get_pixmap(dpi=_PREVIEW_DPI, colorspace=fitz.csRGB, alpha=False)
                png = pixmap.tobytes("png")
                images.append({
                    "base64": base64.b64encode(png).decode("ascii"),
                    "sha256": hashlib.sha256(png).hexdigest(),
                    "width": pixmap.width,
                    "height": pixmap.height,
                })
            return images
    except (ValueError, RuntimeError) as error:
        raise ValueError(f"{language}: cannot render PDF page previews: {error}") from error


def write_preview(
    output_path: Path,
    *,
    title: dict[str, str],
    languages: dict[str, dict],
    ready: bool,
    reason: str = "",
) -> None:
    """Atomically write a standalone HTML preview of two hash-verified files.

    ``ready`` is supplied by the publishing workflow after review. Draft files
    can be previewed but cannot be exported through the page's export buttons.
    This UI gate is not access control: the HTML necessarily contains the bytes.
    Every page is rasterized locally from the verified PDF bytes at 120 DPI.
    Page counts are checked; language semantics and review remain the caller's
    responsibility. Source PDFs are never modified or fetched over a network.

    Invalid metadata or mismatched bytes raises ``ValueError``; filesystem errors
    propagate. A failed build leaves an existing output file unchanged.
    """
    output_path = Path(output_path)
    if type(ready) is not bool or not isinstance(reason, str):
        raise ValueError("ready must be a bool and reason must be a string")
    if not isinstance(title, dict) or any(
        not isinstance(title.get(key), str) or not title[key].strip() for key in _LANGUAGES
    ):
        raise ValueError("title must contain nonempty en and zh-CN strings")
    if not isinstance(languages, dict) or set(languages) != set(_LANGUAGES):
        raise ValueError("languages must contain exactly en and zh-CN")

    entries = {}
    for key in _LANGUAGES:
        entry = languages[key]
        if not isinstance(entry, dict):
            raise ValueError(f"{key}: language metadata must be an object")
        source = entry.get("path")
        if not isinstance(source, (str, Path)) or not Path(source).is_absolute():
            raise ValueError(f"{key}: path must be an absolute local PDF path")
        source = Path(source)
        if output_path.resolve() == source.resolve():
            raise ValueError("preview output must not overwrite a source PDF")
        expected = entry.get("sha256")
        if not isinstance(expected, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", expected):
            raise ValueError(f"{key}: sha256 must be a 64-character hexadecimal digest")
        pages = entry.get("pages")
        if type(pages) is not int or pages < 1:
            raise ValueError(f"{key}: pages must be a positive integer")
        raw = source.read_bytes()
        if not raw or hashlib.sha256(raw).hexdigest() != expected.lower():
            raise ValueError(f"{key}: PDF bytes do not match the supplied SHA-256 (or file is empty)")
        stem = re.sub(r"[^\w.-]+", "-", title[key], flags=re.UNICODE).strip(".-_")[:80].rstrip(".-_")
        entries[key] = {
            "base64": base64.b64encode(raw).decode("ascii"),
            "sha256": expected.lower(),
            "pages": pages,
            "bytes": len(raw),
            "filename": f"{stem or 'research-report'}.{key}.pdf",
            "images": _page_images(raw, pages=pages, language=key),
        }

    effective_reason = reason.strip() or _DEFAULT_REASON
    payload = _script_json({"ready": ready, "reason": effective_reason, "languages": entries})
    cards = []
    for key in _LANGUAGES:
        entry = entries[key]
        english = key == "en"
        label = "English" if english else "简体中文"
        preview_label = "Preview English" if english else "预览中文"
        export_label = "Export English PDF" if english else "导出中文 PDF"
        page_label = "page" if entry["pages"] == 1 else "pages"
        metadata = f'{entry["pages"]} {page_label}' if english else f'{entry["pages"]} 页'
        cards.append(f"""<section class="language" lang="{key}" aria-labelledby="heading-{key}">
  <div class="language-top"><h2 id="heading-{key}">{label}</h2><span class="language-code">{key.upper()}</span></div>
  <p class="metadata">PDF · {metadata} · {entry['bytes'] / 1024:,.1f} KB</p>
  <div class="actions">
    <button class="preview" type="button" id="preview-{key}" aria-controls="page-preview" aria-pressed="false" aria-describedby="integrity" disabled>{preview_label}</button>
    <button type="button" id="export-{key}" aria-describedby="status reason integrity" disabled>{export_label}</button>
  </div>
  <details><summary>{'File integrity · SHA-256' if english else '文件校验 · SHA-256'}</summary>
    <code class="digest">{entry['sha256']}</code></details>
</section>""")

    csp = (
        "default-src 'none'; base-uri 'none'; form-action 'none'; "
        f"script-src {_csp_hash(_JS)}; style-src {_csp_hash(_CSS)}; "
        "img-src data:; frame-src 'none'; object-src 'none'; connect-src 'none'"
    )
    document = _DOCUMENT.substitute(
        csp=html.escape(csp, quote=True),
        css=_CSS,
        javascript=_JS,
        english_title=html.escape(title["en"], quote=True),
        chinese_title=html.escape(title["zh-CN"], quote=True),
        state="checking" if ready else "draft",
        status="Checking embedded PDFs · 正在校验文件" if ready else "Review required · 待审核",
        reason=html.escape("Exports unlock after local integrity verification." if ready else effective_reason, quote=True),
        cards="".join(cards),
        data=payload,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=output_path.parent,
                                         prefix=f".{output_path.name}.", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(document)
        os.replace(temporary, output_path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
