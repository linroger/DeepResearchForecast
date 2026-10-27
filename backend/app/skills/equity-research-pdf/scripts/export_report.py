#!/usr/bin/env python3
"""Render source-bound bilingual research PDFs; publish only reviewed bytes."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import types
import unicodedata
from urllib.parse import urlsplit

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, Frame, Image, PageBreak, PageTemplate, Paragraph,
    Spacer, Table, TableStyle, HRFlowable, KeepTogether,
)
import reportlab.lib.textsplit as rl_textsplit
import reportlab.platypus.paragraph as rl_paragraph
import pymupdf as fitz
from pypdf import PdfReader

LANGUAGES = ("en", "zh-CN")
NAVY = colors.HexColor("#15364D")
BLUE = colors.HexColor("#267395")
INK = colors.HexColor("#202C34")
GRAY = colors.HexColor("#657681")
PALE = colors.HexColor("#EDF3F6")
WIDTH, HEIGHT = letter
LEFT, RIGHT, TOP, BOTTOM = 48, 48, 76, 49
BODY_WIDTH = WIDTH - LEFT - RIGHT


def _local_function(function, **overrides):
    """Clone a pinned ReportLab helper's globals without changing its module.

    ReportLab 4.5.1 has separate single-fragment and mixed-fragment CJK breakers.
    Give only our paragraph subclass the upstream skill's Mandarin kinsoku set.
    Concurrent application renderers and unrelated ReportLab callers are unchanged.
    """
    result = types.FunctionType(function.__code__, {**function.__globals__, **overrides},
                                function.__name__, function.__defaults__, function.__closure__)
    result.__kwdefaults__ = function.__kwdefaults__
    return result


_CJK_EXTRA = "，；：？！％”’》〉】〕}"
_LOCAL_DUMB_SPLIT = _local_function(rl_textsplit.dumbSplit,
    ALL_CANNOT_START=rl_textsplit.ALL_CANNOT_START + _CJK_EXTRA)
_LOCAL_WORD_SPLIT = _local_function(rl_textsplit.wordSplit, dumbSplit=_LOCAL_DUMB_SPLIT)
_LOCAL_FRAG_SPLIT = _local_function(rl_paragraph.cjkFragSplit,
    ALL_CANNOT_START=rl_paragraph.ALL_CANNOT_START + _CJK_EXTRA)
_LOCAL_CJK_BREAK = _local_function(Paragraph.breakLinesCJK,
    wordSplit=_LOCAL_WORD_SPLIT, cjkFragSplit=_LOCAL_FRAG_SPLIT)


class ExportError(ValueError):
    """An actionable input, rendering, or review failure."""


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_read(path: Path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ExportError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique,
                          parse_constant=lambda value: (_ for _ in ()).throw(
                              ExportError(f"Non-finite JSON number: {value}")))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ExportError(f"Cannot read JSON {path}: {exc}") from exc


def json_write(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def require(condition, message):
    if not condition:
        raise ExportError(message)


def keys(obj, required, optional=(), where="object"):
    require(isinstance(obj, dict), f"{where} must be an object")
    missing, extra = set(required) - obj.keys(), obj.keys() - set(required) - set(optional)
    require(not missing, f"{where}: missing fields {sorted(missing)}")
    require(not extra, f"{where}: unsupported fields {sorted(extra)}; content would be omitted")


def plain(value, where):
    require(isinstance(value, str) and value.strip(), f"{where}: nonempty text required")
    require(not any(unicodedata.category(c) == "Cc" and c not in "\n\t" for c in value),
            f"{where}: unsupported control character")
    require("\ufffd" not in value, f"{where}: replacement character indicates damaged text")
    require(not re.search(r"\[(?:TODO|TBD|INSERT|PLACEHOLDER)\]|<placeholder>", value, re.I),
            f"{where}: unresolved placeholder")
    return value


def numeric_tokens(value):
    # Currency/scale equivalence still needs semantic review; do not claim otherwise.
    # Chinese punctuation separates quantities; never join adjacent numbers by deleting it.
    value = unicodedata.normalize("NFKC", value.replace("，", ";").replace("、", ";")).replace("−", "-")
    value = re.sub(r"\(\s*(\d[\d,]*(?:\.\d+)?%?)\s*\)", r"-\1", value)
    tokens = re.findall(r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?", value)
    return Counter(token.replace(",", "") for token in tokens)


def localized(value, where, *, numbers=True):
    keys(value, LANGUAGES, where=where)
    for lang in LANGUAGES:
        plain(value[lang], f"{where}.{lang}")
    if numbers:
        require(numeric_tokens(value["en"]) == numeric_tokens(value["zh-CN"]),
                f"{where}: bilingual numeric tokens differ; preserve numbers or reconcile explicitly")
    return value


def local_file(base, value, where):
    plain(value, where)
    rel = Path(value)
    require(not rel.is_absolute(), f"{where}: use a relative path inside the input bundle")
    path = (base / rel).resolve()
    require(path.is_relative_to(base.resolve()), f"{where}: path escapes input bundle")
    require(path.is_file(), f"{where}: missing local file {value}")
    return path


def validate_report(path: Path):
    report = json_read(path)
    keys(report, ["schema", "source", "title", "subtitle", "publisher", "report_type", "date",
                  "authors", "snapshot", "blocks", "source_inventory"], where="report")
    require(report["schema"] == "equity-report/v1", "Unsupported report schema")
    base = path.resolve().parent
    keys(report["source"], ["path", "sha256"], where="source")
    source = local_file(base, report["source"]["path"], "source.path")
    require(digest(source) == report["source"]["sha256"], "Source file changed: SHA-256 mismatch")
    for name in ("title", "subtitle", "publisher", "report_type"):
        localized(report[name], name)
    try:
        date.fromisoformat(report["date"])
    except (ValueError, TypeError):
        raise ExportError("date must be an ISO YYYY-MM-DD date") from None
    require(isinstance(report["authors"], list) and report["authors"], "authors must be a nonempty list")
    for i, value in enumerate(report["authors"]):
        localized(value, f"authors[{i}]")
    require(isinstance(report["snapshot"], list), "snapshot must be a list; use [] when inapplicable")
    for i, item in enumerate(report["snapshot"]):
        keys(item, ["label", "value"], where=f"snapshot[{i}]")
        localized(item["label"], f"snapshot[{i}].label")
        localized(item["value"], f"snapshot[{i}].value")
    require(isinstance(report["blocks"], list) and report["blocks"], "blocks must be nonempty")
    ids, assets = [], []
    specs = {
        "heading": (["text", "level"], []), "paragraph": (["text"], []),
        "bullets": (["items"], []), "table": (["title", "columns", "rows", "source"], ["notes"]),
        "figure": (["title", "caption", "source", "files"], []),
        "reference": (["text", "url"], []), "page_break": ([], []),
    }
    for index, block in enumerate(report["blocks"]):
        require(isinstance(block, dict), f"blocks[{index}] must be an object")
        kind = block.get("type")
        require(isinstance(kind, str) and kind in specs, f"blocks[{index}]: unsupported type {kind!r}")
        req, opt = specs[kind]
        keys(block, ["id", "type", *req], opt, f"blocks[{index}]")
        bid = plain(block["id"], f"blocks[{index}].id")
        require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,100}", bid), f"Invalid component ID: {bid}")
        require(bid not in ids, f"Duplicate component ID: {bid}")
        ids.append(bid)
        for field in ("text", "title", "caption", "source", "notes"):
            if field in block:
                localized(block[field], f"{bid}.{field}")
        if kind == "heading":
            require(type(block["level"]) is int and block["level"] in (1, 2), f"{bid}: heading level must be 1 or 2")
        if kind == "bullets":
            require(isinstance(block["items"], list) and block["items"], f"{bid}: items must be nonempty")
            for i, item in enumerate(block["items"]):
                localized(item, f"{bid}.items[{i}]")
        if kind == "table":
            cols, rows = block["columns"], block["rows"]
            require(isinstance(cols, list) and 1 <= len(cols) <= 10, f"{bid}: support 1–10 columns; split wider tables explicitly")
            require(isinstance(rows, list) and rows, f"{bid}: rows must be nonempty")
            for i, col in enumerate(cols):
                localized(col, f"{bid}.columns[{i}]")
            for ri, row in enumerate(rows):
                require(isinstance(row, list) and len(row) == len(cols), f"{bid}.rows[{ri}]: column count mismatch")
                for ci, cell in enumerate(row):
                    localized(cell, f"{bid}.rows[{ri}][{ci}]")
        if kind == "figure":
            keys(block["files"], LANGUAGES, where=f"{bid}.files")
            for lang in LANGUAGES:
                asset = local_file(base, block["files"][lang], f"{bid}.files.{lang}")
                try:
                    with PILImage.open(asset) as im:
                        require(im.format in ("PNG", "JPEG"), f"{bid}: only PNG/JPEG supported; render other assets explicitly")
                        require(im.width > 0 and im.height > 0, f"{bid}: empty image")
                        im.verify()
                except (OSError, PILImage.DecompressionBombError) as exc:
                    raise ExportError(f"{bid}: invalid image: {exc}") from exc
                assets.append({"id": bid, "language": lang, "path": str(asset), "sha256": digest(asset)})
        if kind == "reference":
            plain(block["url"], f"{bid}.url")
            try:
                url = urlsplit(block["url"])
            except ValueError as exc:
                raise ExportError(f"{bid}: malformed HTTPS reference URL: {exc}") from exc
            require(url.scheme == "https" and url.hostname and not url.username and not url.password,
                    f"{bid}: reference requires an HTTPS URL without credentials")
            require(not any(c.isspace() for c in block["url"]), f"{bid}: whitespace in URL")
    require(report["source_inventory"] == ids,
            "Source inventory differs from ordered output components; reconcile missing/reordered content")
    require(any(b["type"] != "page_break" for b in report["blocks"]), "Report contains only page breaks")
    require(report["blocks"][0]["type"] != "page_break" and report["blocks"][-1]["type"] != "page_break",
            "Leading/trailing page breaks create empty pages")
    require(not any(a["type"] == b["type"] == "page_break" for a, b in zip(report["blocks"], report["blocks"][1:], strict=False)),
            "Consecutive page breaks create empty pages")
    return report, assets


def text_fields(report, lang):
    fields = []
    for name in ("title", "subtitle", "publisher", "report_type"):
        if name in report:
            fields.append((name, report[name][lang]))
    fields.append(("date", report["date"]))
    fields.extend((f"author.{i}", a[lang]) for i, a in enumerate(report["authors"]))
    for i, item in enumerate(report["snapshot"]):
        fields.extend((f"snapshot.{i}.{key}", item[key][lang]) for key in ("label", "value"))
    for block in report["blocks"]:
        bid = block["id"]
        for field in ("text", "title", "caption", "source", "notes"):
            if field in block:
                fields.append((f"{bid}.{field}", block[field][lang]))
        for i, item in enumerate(block.get("items", [])):
            fields.append((f"{bid}.item.{i}", item[lang]))
        for ci, col in enumerate(block.get("columns", [])):
            fields.append((f"{bid}.header.{ci}", col[lang]))
        for ri, row in enumerate(block.get("rows", [])):
            fields.extend((f"{bid}.cell.{ri}.{ci}", cell[lang]) for ci, cell in enumerate(row))
        if "url" in block:
            fields.append((f"{bid}.url", block["url"]))
    return fields


class Fonts:
    def __init__(self, *, code=False):
        choices = {
            "Latin": ("EQUITY_PDF_LATIN_FONT", ["/Library/Fonts/DejaVuSerif.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"]),
            "LatinBold": ("EQUITY_PDF_LATIN_BOLD", ["/Library/Fonts/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]),
            "CJK": ("EQUITY_PDF_CJK_FONT", ["/System/Library/Fonts/STHeiti Light.ttc", "/usr/share/fonts/truetype/arphic/uming.ttc"]),
            "CJKBold": ("EQUITY_PDF_CJK_BOLD", ["/System/Library/Fonts/STHeiti Medium.ttc", "/usr/share/fonts/truetype/arphic/uming.ttc"]),
        }
        if code:
            choices["Mono"] = ("EQUITY_PDF_MONO_FONT", ["/Library/Fonts/DejaVuSansMono.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"])
        self.paths = {}
        self.chars = {}
        for name, (env, defaults) in choices.items():
            candidates = [os.environ[env]] if os.environ.get(env) else defaults
            path = next((Path(p) for p in candidates if Path(p).is_file()), None)
            require(path is not None, f"Missing {name} font. Set {env} to a licensed embeddable TrueType font (CJK fonts must include Chinese).")
            try:
                font = TTFont(name, str(path), subfontIndex=0)
                pdfmetrics.registerFont(font)
            except Exception as exc:
                raise ExportError(f"Cannot embed font {path}: {exc}; use a TrueType-outline TTF/TTC") from exc
            self.paths[name] = {"path": str(path), "sha256": digest(path)}
            self.chars[name] = font.face.charToGlyph

    def markup(self, value, lang, bold=False, code=False):
        primary = ("CJK" if lang == "zh-CN" else "Latin") + ("Bold" if bold else "")
        fallback = ("Latin" if lang == "zh-CN" else "CJK") + ("Bold" if bold else "")
        if code:
            primary, fallback = "Mono", "CJK"
        runs, buf, current = [], [], None
        for char in value:
            if char in "\n\t":
                chosen = current or primary
            elif ord(char) in self.chars[primary]:
                chosen = primary
            elif ord(char) in self.chars[fallback]:
                chosen = fallback
            else:
                raise ExportError(f"No glyph for {char!r} (U+{ord(char):04X}); provide a covering font or an explicit supported representation")
            if chosen != current and buf:
                runs.append((current, "".join(buf)))
                buf = []
            current = chosen
            buf.append(char)
        if buf:
            runs.append((current, "".join(buf)))
        return "".join(f'<font name="{name}">{html.escape(text).replace(chr(10), "<br/>").replace(chr(9), "    ")}</font>' for name, text in runs)


class AuditedParagraph(Paragraph):
    breakLinesCJK = _LOCAL_CJK_BREAK

    def __init__(self, *args, **kwargs):
        self.audit_id = kwargs.pop("audit_id", None)
        self.outline = kwargs.pop("outline", None)
        self.anchors = kwargs.pop("anchors", [])
        super().__init__(*args, **kwargs)

    def split(self, availWidth, availHeight):
        pieces = super().split(availWidth, availHeight)
        for i, piece in enumerate(pieces):
            piece.audit_id = self.audit_id
            piece.outline = self.outline if i == 0 else None
            piece.anchors = self.anchors if i == 0 else []
        return pieces

    def draw(self):
        if self.audit_id:
            x, y = self.canv.absolutePosition(0, 0)
            self.canv._component_log.append({"id": self.audit_id, "page": self.canv.getPageNumber(),
                "kind": "text", "rect": [x, HEIGHT - y - self.height, x + self.width, HEIGHT - y]})
        for anchor in self.anchors:
            self.canv.bookmarkHorizontal(anchor, 0, self.height)
        if self.outline:
            key, title, level = self.outline
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(title, key, level=level, closed=False)
        super().draw()


class AuditedImage(Image):
    def __init__(self, *args, audit_id, anchors=(), **kwargs):
        self.audit_id = audit_id
        self.anchors = anchors
        super().__init__(*args, **kwargs)

    def draw(self):
        x, y = self.canv.absolutePosition(0, 0)
        for anchor in self.anchors:
            self.canv.bookmarkHorizontal(anchor, 0, self.drawHeight)
        self.canv._component_log.append({"id": self.audit_id, "page": self.canv.getPageNumber(),
            "kind": "figure", "rect": [x, HEIGHT - y - self.drawHeight, x + self.drawWidth, HEIGHT - y]})
        super().draw()


class AuditedRule(HRFlowable):
    def __init__(self, *args, audit_id, **kwargs):
        self.audit_id = audit_id
        super().__init__(*args, **kwargs)

    def draw(self):
        x, y = self.canv.absolutePosition(0, 0)
        self.canv._component_log.append({"id": self.audit_id, "page": self.canv.getPageNumber(),
            "kind": "rule", "rect": [x, HEIGHT-y-self.height, x+self._width, HEIGHT-y]})
        super().draw()


def styles(lang):
    font = "CJK" if lang == "zh-CN" else "Latin"
    bold = "CJKBold" if lang == "zh-CN" else "LatinBold"
    common = {"fontName":font, "fontSize":10.1, "leading":15.1 if lang == "en" else 16.2,
              "textColor":INK, "spaceAfter":8, "wordWrap":"CJK" if lang == "zh-CN" else None,
              "splitLongWords":True, "allowWidows":0, "allowOrphans":0}
    base = ParagraphStyle("body", **common)
    result = {
        "body": base,
        "title": ParagraphStyle("title", parent=base, fontName=bold, fontSize=25, leading=31, textColor=NAVY, spaceAfter=9),
        "subtitle": ParagraphStyle("subtitle", parent=base, fontSize=12, leading=18, textColor=GRAY, spaceAfter=16),
        "h1": ParagraphStyle("h1", parent=base, fontName=bold, fontSize=15, leading=20, textColor=NAVY, spaceBefore=12, spaceAfter=8, keepWithNext=True),
        "h2": ParagraphStyle("h2", parent=base, fontName=bold, fontSize=11, leading=16, textColor=BLUE, spaceBefore=8, spaceAfter=6, keepWithNext=True),
        "caption": ParagraphStyle("caption", parent=base, fontName=bold, fontSize=9, leading=13, textColor=NAVY, spaceBefore=7, spaceAfter=5, keepWithNext=True),
        "small": ParagraphStyle("small", parent=base, fontSize=8, leading=11, textColor=GRAY, spaceAfter=6),
        "cell": ParagraphStyle("cell", parent=base, fontSize=8.1, leading=11.5, spaceAfter=0, spaceBefore=0, allowWidows=1, allowOrphans=1),
        "cellhead": ParagraphStyle("cellhead", parent=base, fontName=bold, fontSize=8.1, leading=11.5, textColor=colors.white, spaceAfter=0, spaceBefore=0, allowWidows=1, allowOrphans=1),
    }
    if lang == "zh-CN":
        # ReportLab's CJK line breaker can hang closing punctuation outside its
        # nominal line width. Reserve one em inside every actual cell/frame.
        for style in result.values():
            style.rightIndent = style.fontSize + 1
    return result


def build_pdf(report, base, lang, output, fonts, total_pages=None, layout=None):
    layout = layout or {}
    sty = styles(lang)
    if layout:
        for name in ("body",):
            size = layout.get("body_font_size", sty[name].fontSize)
            sty[name].leading *= size / sty[name].fontSize
            sty[name].fontSize = size
        for name in ("cell", "cellhead"):
            size = layout.get("table_font_size", sty[name].fontSize)
            sty[name].leading *= size / sty[name].fontSize
            sty[name].fontSize = size
        if lang == "zh-CN":
            for style in sty.values():
                style.rightIndent = style.fontSize + 1
    if report.get("schema") == "equity-report-selected/v1" and lang == "en":
        # Mixed link/font fragments can retain a trailing space beyond the line
        # width even when the following URL wraps. Reserve half an em inside the
        # actual frame/cell rather than deleting source whitespace or weakening QA.
        for style in sty.values():
            style.rightIndent = max(style.rightIndent, style.fontSize * .5 + 1)
    sty["code"] = ParagraphStyle("code", parent=sty["body"], fontSize=8.5, leading=12, backColor=PALE, leftIndent=8, rightIndent=8)
    sty["quote"] = ParagraphStyle("quote", parent=sty["body"], leftIndent=12, rightIndent=12, textColor=GRAY)
    log = []
    def para(text, ident, style="body", bold=False, link=None, outline=None, indent=0):
        runs = report.get("inline", {}).get(ident)
        if runs is None:
            markup = fonts.markup(text, lang, bold)
        else:
            parts = []
            for run in runs:
                part = fonts.markup(run["text"], lang, bold or run.get("bold", False), code=run.get("code", False))
                if run.get("code"):
                    part = re.sub(r">([^<]*)<", lambda m: ">" + m[1].replace(" ", "&#160;") + "<", part)
                if run.get("strike"):
                    part = "<strike>" + part + "</strike>"
                if run.get("italic"):
                    part = '<font color="#435662">' + part + '</font>'
                if run.get("url"):
                    part = '<link href="' + html.escape(run["url"], quote=True) + '" color="#267395">' + part + '</link>'
                parts.append(part)
            markup = "".join(parts)
        if link:
            markup = f'<link href="{html.escape(link, quote=True)}" color="#267395">{markup}</link>'
        paragraph_style = sty[style]
        if indent:
            paragraph_style = ParagraphStyle(f"indent-{ident}", parent=paragraph_style,
                leftIndent=paragraph_style.leftIndent+indent)
        return AuditedParagraph(markup, paragraph_style, audit_id=ident, outline=outline,
                                anchors=report.get("anchors", {}).get(ident, []))

    def furniture(canvas, doc):
        canvas._component_log = log
        canvas.saveState()
        canvas.setStrokeColor(NAVY)
        canvas.setLineWidth(1.2)
        canvas.line(LEFT, HEIGHT-57, WIDTH-RIGHT, HEIGHT-57)
        pub = para(report["publisher"][lang], "publisher", "small", bold=True)
        pw, ph = pub.wrap(BODY_WIDTH * .59, 35)
        require(ph <= 28, "Publisher name exceeds header space; shorten publisher display name")
        pub.drawOn(canvas, LEFT, HEIGHT-48)
        date_line = para(report["date"], "date", "small")
        date_line.style = ParagraphStyle("date-right",parent=sty["small"],alignment=TA_RIGHT)
        date_line.wrap(BODY_WIDTH*.35,20)
        date_line.drawOn(canvas, WIDTH-RIGHT-BODY_WIDTH*.35, HEIGHT-48)
        canvas.setFont("CJK" if lang == "zh-CN" else "Latin", 7.5)
        canvas.setFillColor(GRAY)
        canvas.setLineWidth(.4)
        canvas.setStrokeColor(colors.HexColor("#BDCAD1"))
        canvas.line(LEFT, 37, WIDTH-RIGHT, 37)
        footer = "RESEARCH REPORT" if lang == "en" else "研究报告"
        canvas.drawString(LEFT, 24, footer)
        count = f"{doc.page} / {total_pages}" if total_pages else str(doc.page)
        canvas.drawRightString(WIDTH-RIGHT, 24, count)
        canvas.restoreState()

    doc = BaseDocTemplate(str(output), pagesize=letter, leftMargin=LEFT, rightMargin=RIGHT,
        topMargin=TOP, bottomMargin=BOTTOM, title=report["title"][lang],
        author="; ".join(a[lang] for a in report["authors"]), creator="equity-research-pdf",
        pageCompression=1, allowSplitting=1)
    frame = Frame(LEFT, BOTTOM, BODY_WIDTH, HEIGHT-TOP-BOTTOM,
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates(PageTemplate(id="research", frames=[frame], onPage=furniture))
    story = [para(report["report_type"][lang], "report_type", "small", bold=True),
             para(report["title"][lang], "title", "title", bold=True)]
    if "subtitle" in report:
        story.append(para(report["subtitle"][lang], "subtitle", "subtitle"))
    for i, author in enumerate(report["authors"]):
        story.append(para(author[lang], f"author.{i}", "small"))
    if report["snapshot"]:
        rows = [[para(item["label"][lang], f"snapshot.{i}.label", "cell", bold=True),
                 para(item["value"][lang], f"snapshot.{i}.value", "cell")]
                for i, item in enumerate(report["snapshot"])]
        table = Table(rows, colWidths=[BODY_WIDTH*.38, BODY_WIDTH*.62], hAlign="LEFT", splitByRow=1)
        table.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,-1), PALE),
            ("VALIGN", (0,0), (-1,-1), "TOP"), ("LEFTPADDING", (0,0), (-1,-1), 10),
            ("RIGHTPADDING", (0,0), (-1,-1), 10), ("TOPPADDING", (0,0), (-1,-1), 7),
            ("BOTTOMPADDING", (0,0), (-1,-1), 7)]))
        story.extend([table, Spacer(1, 14)])
    outline_level = -1
    associated_ids = {bid for members in report.get("figure_groups", {}).values() for bid in members}
    block_by_id = {b["id"]: b for b in report["blocks"]}
    pending_figure_headings = []
    for block_index, block in enumerate(report["blocks"]):
        bid, kind = block["id"], block["type"]
        if bid in associated_ids:
            continue
        if bid in layout.get("page_break_before", []):
            story.append(PageBreak())
        if kind == "heading":
            level = min(block["level"]-1, outline_level+1)
            outline_level = level
            heading = para(block["text"][lang], f"{bid}.text", f"h{min(block['level'], 2)}", bold=True,
                           outline=(bid, block["text"][lang], level))
            following = report["blocks"][block_index+1:]
            next_non_heading = next((b for b in following if b["type"] != "heading"), None)
            if next_non_heading and next_non_heading["type"] == "figure":
                # Markdown figure headings are source components, separate from
                # image title attributes. Include them in the same atomic group.
                pending_figure_headings.append(heading)
            else:
                story.append(heading)
        elif kind in ("paragraph", "code", "quote"):
            if "title" in block:
                story.append(para(block["title"][lang], f"{bid}.title", "small"))
            story.append(para(block["text"][lang], f"{bid}.text", kind if kind in ("code", "quote") else "body", indent=block.get("indent", 0)))
        elif kind == "separator":
            story.append(AuditedRule(width="100%", thickness=.5, color=GRAY, spaceBefore=6, spaceAfter=6, audit_id=f"{bid}.rule"))
        elif kind == "bullets":
            for i, item in enumerate(block["items"]):
                story.append(para("• " + item[lang], f"{bid}.item.{i}"))
        elif kind == "reference":
            story.append(para(block["text"][lang], f"{bid}.text", "small", link=block["url"]))
            story.append(para(block["url"], f"{bid}.url", "small", link=block["url"]))
        elif kind == "page_break":
            story.append(PageBreak())
        elif kind == "table":
            if "title" in block:
                story.append(para(block["title"][lang], f"{bid}.title", "caption", bold=True))
            cols = len(block["columns"])
            weights = [1.9] + [1.0]*(cols-1) if cols > 1 else [1]
            weights = layout.get("table_column_weights", {}).get(bid, weights)
            widths = [BODY_WIDTH*w/sum(weights) for w in weights]
            headers = []
            for ci,c in enumerate(block["columns"]):
                head = para(c[lang], f"{bid}.header.{ci}", "cellhead", bold=True)
                align = block.get("alignments", [None]*cols)[ci]
                if ci or align:
                    head.style = ParagraphStyle(f"header-{bid}-{ci}", parent=sty["cellhead"], alignment={"left":TA_LEFT,"center":TA_CENTER,"right":TA_RIGHT}.get(align, TA_RIGHT))
                headers.append(head)
            cells = [headers]
            for ri, row in enumerate(block["rows"]):
                cr = []
                for ci, value in enumerate(row):
                    p = para(value[lang], f"{bid}.cell.{ri}.{ci}", "cell")
                    # Keep numeric cells aligned; preserve text in descriptive columns.
                    if ci and re.fullmatch(r"[\s\d.,()+%−/\-$¥€£x]+", value[lang]):
                        p.style = ParagraphStyle(f"number-{bid}-{ri}-{ci}", parent=sty["cell"], alignment=TA_RIGHT)
                    align = block.get("alignments", [None]*cols)[ci]
                    if align:
                        p.style = ParagraphStyle(f"cell-{bid}-{ri}-{ci}", parent=sty["cell"], alignment={"left":TA_LEFT,"center":TA_CENTER,"right":TA_RIGHT}[align])
                    cr.append(p)
                cells.append(cr)
            t = Table(cells, colWidths=widths, repeatRows=1, splitByRow=1, splitInRow=1,
                      hAlign="LEFT", spaceAfter=5)
            t.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), NAVY),
                ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, PALE]),
                ("VALIGN", (0,0), (-1,-1), "TOP"),
                ("LINEBELOW", (0,-1), (-1,-1), .6, NAVY),
                ("LEFTPADDING", (0,0), (-1,-1), 5), ("RIGHTPADDING", (0,0), (-1,-1), 5),
                ("TOPPADDING", (0,0), (-1,-1), 6), ("BOTTOMPADDING", (0,0), (-1,-1), 6)]))
            story.append(t)
            if "source" in block:
                story.append(para(block["source"][lang], f"{bid}.source", "small"))
            if "notes" in block:
                story.append(para(block["notes"][lang], f"{bid}.notes", "small"))
        elif kind == "figure":
            # One grouping boundary includes the title as well as pixels and
            # notes. Keeping the title outside a nested KeepTogether allows
            # ReportLab to strand it when only the remaining group moves pages.
            figure, pending_figure_headings = pending_figure_headings, []
            if "title" in block:
                figure.append(para(block["title"][lang], f"{bid}.title", "caption", bold=True))
            path = local_file(base, block["files"][lang], f"{bid}.files.{lang}")
            with PILImage.open(path) as im:
                scale = min(BODY_WIDTH/im.width, layout.get("figure_max_height", 270)/im.height)
                w, h = im.width*scale, im.height*scale
            imflow = AuditedImage(str(path), width=w, height=h, audit_id=f"{bid}.image", hAlign="LEFT", mask="auto",
                anchors=report.get("anchors", {}).get(f"{bid}.image", []))
            figure.extend([imflow, Spacer(1, 5)])
            for field in ("caption", "source"):
                if field in block:
                    figure.append(para(block[field][lang], f"{bid}.{field}", "small"))
            for note_id in report.get("figure_groups", {}).get(bid, []):
                note = block_by_id[note_id]
                figure.append(para(note["text"][lang], f"{note_id}.text", "small"))
            story.append(KeepTogether(figure))
    try:
        doc.build(story)
    except Exception as exc:
        raise ExportError(f"{lang} layout failed: {exc}; split oversized content explicitly") from exc
    return log


def normalized(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text)).replace("\u00ad", "")


def image_signature(image):
    rgba = image.convert("RGBA")
    rgb = PILImage.alpha_composite(PILImage.new("RGBA",rgba.size,"white"),rgba).convert("RGB")
    return (rgb.width, rgb.height, hashlib.sha256(rgb.tobytes()).hexdigest())


def check_pdf(report, base, lang, path, log, pages_dir):
    require(path.read_bytes().startswith(b"%PDF-"), f"{lang}: missing PDF signature")
    doc = fitz.open(path)
    require(len(doc) > 0, f"{lang}: PDF has no pages")
    text = "\n".join(page.get_text("text", sort=False) for page in doc)
    expected = text_fields(report, lang)
    drawn = Counter(row["id"] for row in log)
    missing_draws = [key for key,_ in expected if not drawn[key]]
    require(not missing_draws, f"{lang}: components lack actual draw evidence: {missing_draws[:10]}")
    bullet_keys = {f"{b['id']}.item.{i}" for b in report["blocks"] if b["type"]=="bullets" for i in range(len(b["items"]))}
    repeated_keys = {"publisher","date"} | {f"{b['id']}.header.{i}" for b in report["blocks"] if b["type"]=="table" for i in range(len(b["columns"]))}
    # Verify each value in its own drawn region, preserving table row/cell associations.
    misplaced = []
    for key, value in expected:
        regions = [row for row in log if row["id"] == key]
        parts = []
        for row in regions:
            x0,y0,x1,y1 = row["rect"]
            parts.append(doc[row["page"]-1].get_text("text", sort=False,
                clip=fitz.Rect(x0-.6,y0-3,x1+.6,y1+3)))
        wanted = normalized(value)
        if key in bullet_keys:
            wanted = "•" + wanted
        repeated = key in repeated_keys
        matches = all(normalized(part) == wanted for part in parts) if repeated else normalized("\n".join(parts)) == wanted
        if not matches:
            misplaced.append(key)
    require(not misplaced, f"{lang}: omitted, extra, or damaged text in component regions: {misplaced[:10]}")
    # Every figure occurrence is matched to decoded PDF pixels, not an aggregate image count.
    actual_images = []
    links, font_records, page_images = [], {}, []
    for i, page in enumerate(doc, 1):
        body_text = [b for b in page.get_text("blocks") if b[1] >= TOP-2 and b[3] <= HEIGHT-BOTTOM+2 and b[6] == 0]
        has_figure = any(row["kind"] == "figure" and row["page"] == i for row in log)
        require(body_text or has_figure, f"{lang}: page {i} has no report content")
        for lineblock in page.get_text("dict")["blocks"]:
            for line in lineblock.get("lines", []):
                for span in line.get("spans", []):
                    x0,y0,x1,y1 = span["bbox"]
                    require(x0 >= LEFT-2 and x1 <= WIDTH-RIGHT+2 and y0 >= 10 and y1 <= HEIGHT-12,
                            f"{lang}: text outside safe page bounds on page {i}: {span['text'][:60]}")
                    require("\ufffd" not in span["text"], f"{lang}: damaged glyph on page {i}")
        seen_xrefs = set()
        for item in page.get_images(full=True):
            xref = item[0]
            if xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)
            import io
            with PILImage.open(io.BytesIO(doc.extract_image(xref)["image"])) as im:
                rgba = im.convert("RGBA")
                if item[1]:
                    with PILImage.open(io.BytesIO(doc.extract_image(item[1])["image"])) as mask:
                        rgba.putalpha(mask.convert("L"))
                sig = image_signature(rgba)
            actual_images.extend({"page":i,"rect":list(rect),"signature":sig} for rect in page.get_image_rects(xref))
        links.extend(link.get("uri") for link in page.get_links() if link.get("uri"))
        for f in page.get_fonts(full=True):
            name, ext, typ, data = doc.extract_font(f[0])
            # ReportLab may register unused Helvetica; require embedding only for used fonts below.
            font_records[f[3]] = {"name": name, "extension": ext, "embedded": bool(data)}
        for lineblock in page.get_text("dict")["blocks"]:
            for line in lineblock.get("lines", []):
                for span in line.get("spans", []):
                    used = span["font"].replace(" ", "")
                    matches = [v for k,v in font_records.items() if used in k.replace(" ", "") or used in v["name"].replace(" ", "")]
                    require(matches and any(v["embedded"] for v in matches), f"{lang}: used font is not embedded: {used}")
        pages_dir.mkdir(parents=True, exist_ok=True)
        png = pages_dir/f"page-{i:03}.png"
        page.get_pixmap(matrix=fitz.Matrix(1.5,1.5), alpha=False).save(png)
        page_images.append({"page": i, "path": str(png), "sha256": digest(png)})
    assignments = []
    unmatched_images = set(range(len(actual_images)))
    for b in report["blocks"]:
        if b["type"] == "figure":
            figure_id = f"{b['id']}.image"
            require(drawn[figure_id] == 1, f"{lang}: figure {b['id']} not drawn exactly once")
            with PILImage.open(local_file(base,b["files"][lang],b["id"])) as im:
                sig = image_signature(im)
            row = next(row for row in log if row["id"]==figure_id and row["kind"]=="figure")
            match = next((idx for idx in unmatched_images if actual_images[idx]["signature"]==sig
                and actual_images[idx]["page"]==row["page"]
                and all(abs(a-bb)<.1 for a,bb in zip(actual_images[idx]["rect"],row["rect"], strict=True))),None)
            require(match is not None, f"{lang}: figure {b['id']} pixels/position do not match its caption component")
            unmatched_images.remove(match)
            assignments.append({"id":b["id"],"page":row["page"],"rect":row["rect"],"pixel_sha256":sig[2]})
    require(not unmatched_images, f"{lang}: unassigned image occurrences in PDF")
    for block in report["blocks"]:
        if block["type"] == "separator":
            ident = block["id"] + ".rule"
            require(drawn[ident] == 1, f"{lang}: required separator {ident} was not drawn exactly once")
            row = next(row for row in log if row["id"] == ident)
            x0, y0, x1, y1 = row["rect"]
            lines = [item for drawing in doc[row["page"]-1].get_drawings() for item in drawing["items"] if item[0] == "l"]
            require(any(abs(item[1].x-x0)<.1 and abs(item[2].x-x1)<.1 and abs(item[1].y-y1)<.1 and abs(item[2].y-y0)<.1 for item in lines),
                    f"{lang}: required separator {ident} is missing from PDF vector content")
    for b in report["blocks"]:
        if b["type"] == "reference":
            require(b["url"] in links, f"{lang}: hyperlink destination missing: {b['id']}")
    # Check the geometric boxes emitted by individual paragraphs/cells/figures.
    overlaps = []
    for i,a in enumerate(log):
        if a["id"] in ("publisher","date"):
            continue
        ax0,ay0,ax1,ay1 = a["rect"]
        require(ay0 >= TOP-1 and ay1 <= HEIGHT-BOTTOM+1 and ax0 >= LEFT-1 and ax1 <= WIDTH-RIGHT+1,
                f"{lang}: component {a['id']} exceeds body bounds on page {a['page']}")
        for b in log[i+1:]:
            if a["page"] != b["page"] or b["id"] in ("publisher","date"):
                continue
            bx0,by0,bx1,by1 = b["rect"]
            if min(ax1,bx1)-max(ax0,bx0) > 1 and min(ay1,by1)-max(ay0,by0) > 1:
                overlaps.append((a["id"],b["id"],a["page"]))
    require(not overlaps, f"{lang}: overlapping component boxes: {overlaps[:8]}")
    # Independent parser is deliberately separate from rendering/extraction.
    reader = PdfReader(path, strict=True)
    require(len(reader.pages) == len(doc), f"{lang}: parser page-count disagreement")
    for i,page in enumerate(doc,1):
        require(f"{i} / {len(doc)}" in page.get_text(), f"{lang}: incorrect page numbering on page {i}")
    result = {"path": str(path), "sha256": digest(path), "pages": len(doc),
        "text_components": len(expected), "component_draws": log, "figure_occurrences": len(assignments),
        "figure_assignments":assignments,
        "hyperlinks": sorted(set(links)), "fonts": list(font_records.values()), "page_images": page_images,
        "checks": {"all_text_present": True, "all_components_drawn": True, "figure_pixels_present": True,
                   "links_present": True, "used_fonts_embedded": True, "safe_bounds": True,
                   "no_component_overlap": True, "component_text_regions": True,
                   "independent_parser": True, "page_numbers": True}}
    doc.close()
    return result


def render(input_path, output_dir):
    input_path, output_dir = input_path.resolve(), output_dir.resolve()
    report, assets = validate_report(input_path)
    require(not output_dir.exists(), f"Output directory already exists: {output_dir}; use a new generation directory")
    fonts = Fonts()
    for lang in LANGUAGES:
        for _, value in text_fields(report, lang):
            fonts.markup(value, lang)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}-", dir=output_dir.parent))
    try:
        qa = {"schema": "equity-pdf-qa/v1", "status": "draft", "created_at": datetime.now(timezone.utc).isoformat(),
              "input": {"path": str(input_path), "sha256": digest(input_path)},
              "source": {"path": str(local_file(input_path.parent,report['source']['path'],'source')), "sha256": report['source']['sha256']},
              "assets": assets, "font_sources": fonts.paths, "title": report["title"], "languages": {}}
        for lang in LANGUAGES:
            pdf = stage/f"report.{lang}.pdf"
            build_pdf(report,input_path.parent,lang,pdf,fonts)
            with fitz.open(pdf) as doc:
                pages = len(doc)
            log = build_pdf(report,input_path.parent,lang,pdf,fonts,total_pages=pages)
            qa["languages"][lang] = check_pdf(report,input_path.parent,lang,pdf,log,stage/"pages"/lang)
        # Rebase only actual artifact paths; serialized string replacement corrupts Unicode paths.
        for result in qa["languages"].values():
            result["path"] = str(output_dir / Path(result["path"]).relative_to(stage))
            for item in result["page_images"]:
                item["path"] = str(output_dir / Path(item["path"]).relative_to(stage))
        json_write(stage/"qa.json",qa)
        template = {"schema":"equity-pdf-review/v1", "input_sha256": qa["input"]["sha256"],
            "pdf_sha256": {l:q["sha256"] for l,q in qa["languages"].items()},
            "source_reconciled":False, "semantic_review":False, "visual_review":False,
            "reviewer":"", "notes":""}
        json_write(stage/"review-template.json",template)
        from preview import write_preview
        write_preview(stage/"preview.html",title=report["title"],languages={l:{**q,"path":stage/f"report.{l}.pdf"} for l,q in qa["languages"].items()},
                      ready=False,reason="Draft: source, bilingual meaning, and every rendered page require review. / 草稿：须核对源文件、双语含义及全部页面。")
        # Detect input/source/asset races before promoting the whole candidate directory.
        verify_inputs(qa)
        stage.rename(output_dir)
        return {"status":"draft", "output_dir":str(output_dir), "pages":{l:q["pages"] for l,q in qa["languages"].items()}}
    except BaseException:
        shutil.rmtree(stage,ignore_errors=True)
        raise


def verify_inputs(qa):
    for obj in [qa["input"],qa["source"],*qa["assets"],*qa["font_sources"].values()]:
        path = Path(obj["path"])
        require(path.is_file() and digest(path)==obj["sha256"], f"Input dependency changed or missing: {path}")


def validate_qa(qa):
    keys(qa,["schema","status","created_at","input","source","assets","font_sources","title","languages"],where="qa")
    require(qa["schema"]=="equity-pdf-qa/v1", "Unsupported QA receipt")
    require(isinstance(qa["assets"],list),"qa.assets must be a list")
    require(isinstance(qa["font_sources"],dict) and qa["font_sources"],"qa.font_sources must be a nonempty object")
    for obj in [qa["input"],qa["source"],*qa["assets"],*qa["font_sources"].values()]:
        require(isinstance(obj,dict),"qa dependency must be an object")
        plain(obj.get("path"),"qa dependency.path")
        require(isinstance(obj.get("sha256"),str) and re.fullmatch(r"[0-9a-f]{64}",obj["sha256"]),"qa dependency has invalid sha256")
    keys(qa["languages"],LANGUAGES,where="qa.languages")
    localized(qa["title"],"qa.title")
    for lang,q in qa["languages"].items():
        require(isinstance(q,dict),f"qa.languages.{lang} must be an object")
        for field in ("path","sha256","pages","checks","page_images","component_draws"):
            require(field in q,f"qa.languages.{lang}: missing {field}")
        require(type(q["pages"]) is int and q["pages"]>0,f"{lang}: invalid QA page count")
        require(isinstance(q["page_images"],list) and len(q["page_images"])==q["pages"],f"{lang}: incomplete page review inventory")
        require(isinstance(q["component_draws"],list) and q["component_draws"],f"{lang}: missing component geometry")
        require(isinstance(q["checks"],dict) and q["checks"],f"{lang}: missing automated checks")
        for image in q["page_images"]:
            keys(image,["page","path","sha256"],where=f"{lang}.page_image")
            plain(image["path"],f"{lang}.page_image.path")
        require([im["page"] for im in q["page_images"]]==list(range(1,q["pages"]+1)),f"{lang}: reordered/duplicate page review inventory")
        for draw in q["component_draws"]:
            keys(draw,["id","page","kind","rect"],where=f"{lang}.draw")
            plain(draw["id"],f"{lang}.draw.id")
            require(type(draw["page"]) is int and 1<=draw["page"]<=q["pages"],f"{lang}: invalid draw page")
            require(isinstance(draw["rect"],list) and len(draw["rect"])==4 and all(type(v) in (int,float) for v in draw["rect"]),f"{lang}: invalid draw rectangle")


def publish(output_dir, review_path):
    output_dir = output_dir.resolve()
    qa = json_read(output_dir/"qa.json")
    review = json_read(review_path)
    validate_qa(qa)
    keys(review,["schema","input_sha256","pdf_sha256","source_reconciled","semantic_review","visual_review","reviewer","notes"],where="review")
    require(review["schema"]=="equity-pdf-review/v1", "Unsupported review schema")
    for key in ("source_reconciled","semantic_review","visual_review"):
        require(review[key] is True, f"Review incomplete: {key}; perform the review before enabling export")
    plain(review["reviewer"],"reviewer")
    plain(review["notes"],"review.notes")
    require(review["input_sha256"]==qa["input"]["sha256"], "Review belongs to another input generation")
    keys(review["pdf_sha256"],LANGUAGES,where="review.pdf_sha256")
    verify_inputs(qa)
    report, _ = validate_report(Path(qa["input"]["path"]))
    languages = {}
    for lang in LANGUAGES:
        q = qa["languages"][lang]
        pdf = output_dir/f"report.{lang}.pdf"
        require(digest(pdf)==q["sha256"]==review["pdf_sha256"][lang], f"{lang}: reviewed PDF hash mismatch")
        require(all(v is True for v in q["checks"].values()), f"{lang}: automated checks failed")
        for im in q["page_images"]:
            path=Path(im["path"])
            require(path.is_relative_to(output_dir) and path.is_file() and digest(path)==im["sha256"], f"{lang}: page review evidence changed")
        # Re-run PDF checks against current report; a forged/edited success flag is insufficient.
        with tempfile.TemporaryDirectory(prefix="equity-publish-") as tmp:
            check_pdf(report,Path(qa["input"]["path"]).parent,lang,pdf,q["component_draws"],Path(tmp))
        languages[lang]={"path":pdf,"sha256":q["sha256"],"pages":q["pages"]}
    from preview import write_preview
    receipt_path, preview_path = output_dir/"release.json", output_dir/"preview.html"
    for path in (receipt_path,preview_path):
        require(not path.is_symlink() and (not path.exists() or path.is_file()),f"Publication destination is not a regular file: {path}")
    old_receipt = receipt_path.read_bytes() if receipt_path.exists() else None
    # All expensive/fallible writes happen before making export visible. The ready
    # preview is the final commit marker; a receipt failure leaves the draft intact.
    with tempfile.TemporaryDirectory(prefix=".publish-",dir=output_dir) as staging:
        stage=Path(staging)
        pending_page,pending_receipt=stage/"preview.html",stage/"release.json"
        write_preview(pending_page,title=qa["title"],languages=languages,ready=True)
        release={"schema":"equity-pdf-release/v1","status":"reviewed","published_at":datetime.now(timezone.utc).isoformat(),
                 "input_sha256":qa["input"]["sha256"],"review":review,"preview_sha256":digest(pending_page),
                 "pdf_sha256":review["pdf_sha256"],"limitations":"Review applies to these exact bytes. It is not a guarantee of factual accuracy or future exports."}
        json_write(pending_receipt,release)
        verify_inputs(qa)
        pending_receipt.replace(receipt_path)
        try:
            pending_page.replace(preview_path)
        except BaseException:
            if old_receipt is None:
                receipt_path.unlink(missing_ok=True)
            else:
                rollback=stage/"rollback.json"
                rollback.write_bytes(old_receipt)
                rollback.replace(receipt_path)
            raise
    return {"status":"reviewed","preview":str(output_dir/"preview.html")}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest="command",required=True)
    r=sub.add_parser("render",help="Create checked draft PDFs and disabled export preview")
    r.add_argument("input",type=Path);r.add_argument("--output-dir",required=True,type=Path)
    p=sub.add_parser("publish",help="Enable downloads for a completely reviewed generation")
    p.add_argument("--output-dir",required=True,type=Path);p.add_argument("--review",required=True,type=Path)
    args=parser.parse_args()
    try:
        result=render(args.input,args.output_dir) if args.command=="render" else publish(args.output_dir,args.review)
    except (ExportError,OSError,KeyError,TypeError) as exc:
        print(json.dumps({"status":"error","message":str(exc)},ensure_ascii=False),file=sys.stderr)
        return 1
    print(json.dumps(result,ensure_ascii=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
