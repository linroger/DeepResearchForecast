#!/usr/bin/env python3
"""Build the complete fictional bilingual input fixture; never render or approve PDFs."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import unicodedata

from PIL import Image, ImageDraw, ImageFont, PngImagePlugin


LANGUAGES = ("en", "zh-CN")
PERIODS = ("2024A", "2025A", "2026E", "2027E")
NUMBERS = re.compile(r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?")
LONG_URL = (
    "https://example.com/fictional-research/lattice-harbor-components/2026-10-26/"
    "methodology?currency=USD&scale=million&scenario=illustrative"
    "&language=en-and-zh-CN&purpose=layout-validation"
)


def localized(en: str, zh: str | None = None) -> dict[str, str]:
    return {"en": en, "zh-CN": en if zh is None else zh}


def text_block(block_id: str, en: str, zh: str, *, heading: bool = False) -> dict:
    block = {"id": block_id, "type": "heading" if heading else "paragraph", "text": localized(en, zh)}
    if heading:
        block["level"] = 1
    return block


def make_report() -> dict:
    """The authored fixture is wholly synthetic; numeric strings have one shared origin."""
    financials = [
        ("Revenue", "收入", ("120.0", "132.0", "145.2", "159.7")),
        ("Gross profit", "毛利润", ("36.0", "42.2", "49.4", "57.5")),
        ("EBITDA", "EBITDA", ("14.4", "17.2", "21.8", "25.6")),
        ("EBITDA margin", "EBITDA利润率", ("12.0%", "13.0%", "15.0%", "16.0%")),
        ("Net income", "净利润", ("(2.4)", "3.3", "7.3", "9.6")),
        ("Operating cash flow", "经营现金流", ("8.0", "12.0", "16.0", "20.0")),
        ("Capital expenditure", "资本支出", ("(11.0)", "(10.0)", "(9.0)", "(10.0)")),
        ("Free cash flow", "自由现金流", ("(3.0)", "2.0", "7.0", "10.0")),
        ("Debt", "债务", ("24.0", "22.0", "20.0", "18.0")),
        ("Cash", "现金", ("8.0", "9.0", "10.0", "12.0")),
    ]
    blocks = [
        text_block(
            "fixture-status",
            "Fictional illustration. Lattice Harbor Components, the publisher and all financial data in this report are invented solely to exercise bilingual document export. This is not research on a real security and contains no investment recommendation.",
            "虚构示例。本报告中的栅港组件、发布方及全部财务数据均为双语文档导出演示而创作。本报告不研究真实证券，也不提供投资建议。",
        ),
        text_block("thesis-heading", "Thesis: cash conversion determines the recovery", "核心论点：现金转化决定复苏质量", heading=True),
        text_block(
            "thesis-demand",
            "The fictional manufacturer supplies precision connectors to industrial equipment makers. The scenario assumes that repeat orders support a gradual recovery, while customers retain the ability to defer deliveries. Revenue rises from USD 132.0 million in 2025A to USD 145.2 million in 2026E; this is an illustrative assumption, not an observed order book.",
            "这家虚构制造商向工业设备厂商供应精密连接器。情景假设重复订单支持逐步复苏，但客户仍可推迟交付。收入由2025A的USD 132.0 million增至2026E的USD 145.2 million；这是示例假设，并非已观察到的在手订单。",
        ),
        text_block(
            "thesis-cash",
            "The central question is whether production efficiency reaches cash generation. Illustrative free cash flow improves from USD (3.0) million in 2024A to USD 7.0 million in 2026E. Lower capital spending contributes alongside operating cash flow; the model does not attribute the entire improvement to pricing power. See Footnote 1 for sign conventions.",
            "核心问题在于生产效率能否转化为现金。示例自由现金流由2024A的USD (3.0) million改善至2026E的USD 7.0 million。资本支出下降与经营现金流共同促成改善；模型并未将全部改善归因于定价能力。符号约定见脚注1。",
        ),
        {"id": "catalysts", "type": "bullets", "items": [
            localized("Catalyst: repeat orders convert into deliveries without longer payment terms.", "催化因素：重复订单转化为交付，同时付款账期没有延长。"),
            localized("Watchpoint: inventory and receivables absorb the expected cash recovery.", "观察重点：存货及应收账款是否占用预期恢复的现金。"),
            localized("Invalidation: sustained customer deferrals or weaker cash collection undermine the scenario.", "失效条件：客户持续推迟交付或回款转弱，将削弱本情景。"),
        ]},
        {"id": "break-financials", "type": "page_break"},
        text_block("financials-heading", "Financial model and definitions", "财务模型与定义", heading=True),
        {"id": "financial-table", "type": "table",
         "title": localized("Exhibit 1. Illustrative financial model (USD million)", "图表1：示例财务模型（USD million）"),
         "columns": [localized("Metric", "指标")] + [localized(period) for period in PERIODS],
         "rows": [[localized(en, zh)] + [localized(value) for value in values] for en, zh, values in financials],
         "source": localized("Source: original fictional dataset authored for this export example.", "来源：为本导出示例原创的虚构数据集。"),
         "notes": localized("A = illustrative historical period; E = illustrative estimate. All periods are fictional. Percentages are shown only in the margin row.", "A＝示例历史期间；E＝示例预测。全部期间均为虚构。百分比仅用于利润率行。")},
        text_block(
            "footnote-signs",
            "Footnote 1. Figures use USD million unless a percentage is shown. Parentheses indicate negative amounts: (3.0) means -3.0. Capital expenditure is recorded as an outflow; free cash flow equals operating cash flow plus the signed capital expenditure. Totals may reflect rounding to one decimal place.",
            "脚注1：除百分比外，数值单位均为USD million（百万美元）。括号表示负数：(3.0)即-3.0。资本支出列为流出；自由现金流等于经营现金流加带符号的资本支出。合计数可能受到保留一位小数的舍入影响。",
        ),
        text_block(
            "footnote-profit",
            "Footnote 2. EBITDA is a model subtotal before interest, tax, depreciation and amortization; it is not a substitute for cash flow. The illustrative 2024A net loss of USD (2.4) million includes depreciation and financing costs absent from EBITDA. No audited financial statements underlie this fixture.",
            "脚注2：EBITDA为模型中的息税折旧摊销前小计，不能替代现金流。2024A的示例净亏损USD (2.4) million包含EBITDA未计入的折旧及融资成本。本测试材料不以经审计财务报表为依据。",
        ),
        {"id": "break-valuation", "type": "page_break"},
        text_block("valuation-heading", "Cash profile and illustrative valuation", "现金表现与示例估值", heading=True),
        {"id": "cash-chart", "type": "figure",
         "title": localized("Exhibit 2. Growth and cash recovery (USD million)", "图表2：增长与现金恢复（USD million）"),
         "caption": localized("Revenue and free cash flow use separate vertical scales. Data labels reproduce Exhibit 1. Outlined bars denote E periods; filled bars denote A periods. The negative cash bar crosses below zero.", "收入与自由现金流使用各自独立的纵轴刻度。数据标签对应图表1。描边柱表示E期间，实心柱表示A期间。负现金流柱位于零线下方。"),
         "source": localized("Source: Exhibit 1, original fictional dataset; no external market data.", "来源：图表1的原创虚构数据集；未使用外部市场数据。"),
         "files": {"en": "chart.en.png", "zh-CN": "chart.zh-CN.png"}},
        text_block(
            "valuation-method",
            "For illustration, applying 8.0x to 2026E EBITDA of USD 21.8 million gives enterprise value of USD 174.4 million. Deducting assumed net debt of USD 10.0 million yields equity value of USD 164.4 million. Dividing by 20.0 million assumed shares gives $8.22 per share. This is scenario arithmetic, not a target price or a quoted market price.",
            "作为示例，对2026E的EBITDA USD 21.8 million采用8.0x倍数，得到企业价值USD 174.4 million。扣除假设净债务USD 10.0 million后，股权价值为USD 164.4 million。除以假设的20.0 million股，得到每股$8.22。这是情景算术结果，不是目标价或市场报价。",
        ),
        text_block(
            "valuation-sensitivity",
            "Holding EBITDA, net debt and share count constant, 7.0x implies $7.13 per share and 9.0x implies $9.31. These multiples are chosen to test sensitivity; they are not sourced trading comparables. The exercise gives no probability weights and does not establish fair value.",
            "在EBITDA、净债务及股数不变时，7.0x对应每股$7.13，9.0x对应每股$9.31。选择这些倍数是为了检验敏感性，它们并非来自可比公司的市场交易数据。本练习不赋予概率权重，也不据此认定公允价值。",
        ),
        {"id": "break-risks", "type": "page_break"},
        text_block("risks-heading", "Risks, source notes and disclosure", "风险、来源说明与披露", heading=True),
        {"id": "risks", "type": "bullets", "items": [
            localized("Demand: customers can postpone equipment purchases; repeat orders are not guaranteed revenue.", "需求：客户可能推迟设备采购，重复订单并不保证收入实现。"),
            localized("Execution: yield losses and expedited freight can absorb the modeled margin improvement.", "执行：良率损失及加急运费可能抵消模型中的利润率改善。"),
            localized("Liquidity: slower collection or higher inventory can reverse positive free cash flow despite accounting profit.", "流动性：即使有会计利润，回款放缓或存货上升仍可能使正自由现金流转负。"),
            localized("Valuation: the illustrative multiple is an assumption and can change independently of operating results.", "估值：示例倍数属于假设，可能独立于经营结果发生变化。"),
        ]},
        text_block(
            "source-authority",
            "Source authority. This complete bilingual original and its localized chart images are the source for the example JSON. Every financial value is authored for this fixture. The reference destination below tests a long clickable HTTPS link and provides no evidence for the company, estimates or valuation.",
            "来源权威性。本完整双语原稿及配套本地化图表构成示例JSON的来源。每个财务数值均为本测试材料原创。下列引用地址用于测试较长的可点击HTTPS链接，不为公司、预测或估值提供证据。",
        ),
        {"id": "reference-methodology", "type": "reference",
         "text": localized(f"Illustrative methodology link (link-format test only): {LONG_URL}", f"示例方法说明链接（仅用于链接格式测试）：{LONG_URL}"),
         "url": LONG_URL},
        text_block(
            "fixture-disclosure",
            "Disclosure for this fictional example. Example Research Studio and the illustrative editorial team are neutral invented identities, with no claimed connection to a bank or real issuer. The text makes no analyst certification, independence assertion or real-world conflicts declaration. It is an export demonstration and must not be reused as disclosure language for an actual investment report.",
            "本虚构示例的披露。示例研究工作室与示例编辑团队均为中性的虚构身份，不声称与任何银行或真实发行人有关联。本文不作分析师认证、独立性声明或现实中的利益冲突声明。本材料仅用于导出演示，不得将其作为真实投资报告的披露措辞重复使用。",
        ),
    ]
    return {
        "schema": "equity-report/v1",
        "source": {"path": "source.md", "sha256": ""},
        "title": localized("Lattice Harbor Components", "栅港组件"),
        "subtitle": localized("Cash conversion determines the recovery", "现金转化决定复苏质量"),
        "publisher": localized("Example Research Studio (fictional)", "示例研究工作室（虚构）"),
        "report_type": localized("Fictional equity research exercise", "虚构股票研究示例"),
        "date": "2026-10-26",
        "authors": [localized("Illustrative editorial team", "示例编辑团队")],
        "snapshot": [
            {"label": localized("Identity", "身份"), "value": localized("Fictional manufacturer", "虚构制造商")},
            {"label": localized("Financial unit", "财务单位"), "value": localized("USD million", "USD million（百万美元）")},
            {"label": localized("2026E revenue", "2026E收入"), "value": localized("145.2")},
            {"label": localized("2026E free cash flow", "2026E自由现金流"), "value": localized("7.0")},
        ],
        "blocks": blocks,
        "source_inventory": [block["id"] for block in blocks],
    }


def font_file(env: str, candidates: list[Path]) -> Path:
    explicit = os.environ.get(env)
    if explicit:
        candidates = [Path(explicit).expanduser()]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"No local chart font found; set {env} to a licensed font file. No font is copied.")


def fonts() -> dict[str, Path]:
    runtime = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/native"
    libreoffice = runtime / "libreoffice-headless/libreoffice/LibreOfficeDev.app/Contents/Resources/fonts/truetype"
    return {
        "latin": font_file("EQUITY_EXAMPLE_LATIN_FONT", [Path("/Library/Fonts/DejaVuSans.ttf"), libreoffice / "DejaVuSans.ttf"]),
        "bold": font_file("EQUITY_EXAMPLE_LATIN_BOLD_FONT", [Path("/Library/Fonts/DejaVuSans-Bold.ttf"), libreoffice / "DejaVuSans-Bold.ttf"]),
        "cjk": font_file("EQUITY_EXAMPLE_CJK_FONT", [Path("/System/Library/Fonts/STHeiti Light.ttc")]),
    }


def chart_data(report: dict) -> dict:
    table = next(block for block in report["blocks"] if block["id"] == "financial-table")
    rows = {row[0]["en"]: row[1:] for row in table["rows"]}
    return {"periods": list(PERIODS), "unit": "USD million", "series": {
        key: [cell["en"] for cell in rows[key]] for key in ("Revenue", "Free cash flow")
    }}


def number(value: str) -> float:
    return -float(value[1:-1]) if value.startswith("(") else float(value)


def make_chart(path: Path, language: str, data: dict, font_paths: dict[str, Path]) -> None:
    """Render two legible panels from the exact canonical financial table values."""
    image = Image.new("RGB", (1400, 650), "white")
    draw = ImageDraw.Draw(image)
    navy, blue, gray, rule = "#17364D", "#276A94", "#455A64", "#D7E0E7"
    cjk = language == "zh-CN"
    title_font = ImageFont.truetype(str(font_paths["cjk" if cjk else "bold"]), 30)
    label_font = ImageFont.truetype(str(font_paths["cjk" if cjk else "latin"]), 23)
    numeric_font = ImageFont.truetype(str(font_paths["latin"]), 23)
    value_font = ImageFont.truetype(str(font_paths["bold"]), 25)
    captions = {
        "en": ("Revenue", "Free cash flow", "A: illustrative historical", "E: illustrative estimate", "Fictional data | Separate vertical scales | USD million"),
        "zh-CN": ("收入", "自由现金流", "A：示例历史", "E：示例预测", "虚构数据 | 各图纵轴刻度独立 | USD million"),
    }[language]

    def label(x: float, y: float, text: str, font: ImageFont.FreeTypeFont, color: str, anchor: str = "lt") -> None:
        box = draw.textbbox((x, y), text, font=font, anchor=anchor)
        if box[0] < 0 or box[1] < 0 or box[2] > image.width or box[3] > image.height:
            raise ValueError(f"Chart label outside image: {language}: {text}")
        draw.text((x, y), text, font=font, fill=color, anchor=anchor)

    for panel, (series, low, high, ticks) in enumerate([
        ("Revenue", 0.0, 180.0, (0, 40, 80, 120, 160)),
        ("Free cash flow", -5.0, 12.0, (-5, 0, 5, 10)),
    ]):
        left = 105 + panel * 685
        right, top, bottom = left + 515, 112, 470
        label(left, 30, captions[panel], title_font, navy)
        label(left, 78, data["unit"], numeric_font, gray)

        def y(value: float) -> float:
            return bottom - (value - low) / (high - low) * (bottom - top)

        for tick in ticks:
            draw.line((left, y(tick), right, y(tick)), fill=rule, width=2)
            label(left - 15, y(tick), str(tick), numeric_font, gray, "rm")
        draw.line((left, y(0), right, y(0)), fill=gray, width=3)
        for index, (period, value) in enumerate(zip(data["periods"], data["series"][series], strict=True)):
            center = left + 65 + index * 125
            raw = number(value)
            upper, lower = sorted((y(0), y(raw)))
            draw.rectangle((center - 34, upper, center + 34, lower), fill=blue if index < 2 else "#E9F1F6", outline=blue, width=3)
            label(center, y(raw) - 10 if raw >= 0 else y(raw) + 12, value, value_font, navy, "mb" if raw >= 0 else "mt")
            label(center, 500, period, numeric_font, navy, "mt")
    draw.rectangle((105, 552, 125, 572), fill=blue)
    label(137, 548, captions[2], label_font, gray)
    draw.rectangle((650, 552, 670, 572), fill="#E9F1F6", outline=blue, width=2)
    label(682, 548, captions[3], label_font, gray)
    label(105, 605, captions[4], label_font, gray)
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("fixture_language", language)
    metadata.add_text("fixture_data", json.dumps(data, ensure_ascii=False, sort_keys=True))
    metadata.add_text("fixture_labels", json.dumps(captions, ensure_ascii=False))
    image.save(path, pnginfo=metadata)


def markdown_block(block: dict, language: str) -> list[str]:
    kind = block["type"]
    if kind == "heading":
        return ["#" * (block["level"] + 2) + " " + block["text"][language]]
    if kind == "paragraph":
        return [block["text"][language]]
    if kind == "bullets":
        return ["- " + item[language] for item in block["items"]]
    if kind == "table":
        lines = [block["title"][language], "", "| " + " | ".join(cell[language] for cell in block["columns"]) + " |",
                 "| " + " | ".join("---" for _ in block["columns"]) + " |"]
        lines += ["| " + " | ".join(cell[language] for cell in row) + " |" for row in block["rows"]]
        lines += ["", block["source"][language]]
        if "notes" in block:
            lines += ["", block["notes"][language]]
        return lines
    if kind == "figure":
        return [block["title"][language], "", f"![{block['title'][language]}]({block['files'][language]})", "", block["caption"][language], "", block["source"][language]]
    if kind == "reference":
        return [f"[{block['text'][language]}]({block['url']})"]
    raise ValueError(f"Unexpected source block: {kind}")


def write_source(report: dict, output: Path) -> list[tuple[str, int, int]]:
    lines = [f"# {report['title']['en']} / {report['title']['zh-CN']}", ""]
    spans = []
    for language in LANGUAGES:
        start = len(lines) + 1
        lines += ["## " + ("English metadata" if language == "en" else "简体中文元数据"), ""]
        for key in ("title", "subtitle", "publisher", "report_type"):
            lines.append(f"- {key}: {report[key][language]}")
        lines += [f"- date: {report['date']}", "- authors: " + "; ".join(author[language] for author in report["authors"])]
        lines += ["- " + item["label"][language] + ": " + item["value"][language] for item in report["snapshot"]]
        spans.append((f"metadata.{language}", start, len(lines)))
        lines.append("")
    for block in report["blocks"]:
        start = len(lines) + 1
        lines += [f"<!-- block: {block['id']} -->", ""]
        if block["type"] == "page_break":
            lines.append("---")
        else:
            for language in LANGUAGES:
                lines += ["## " + ("English" if language == "en" else "简体中文"), ""]
                lines += markdown_block(block, language) + [""]
        lines.append(f"<!-- /block: {block['id']} -->")
        spans.append((block["id"], start, len(lines)))
        lines.append("")
    (output / "source.md").write_text("\n".join(lines), encoding="utf-8")
    return spans


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_fixture(report: dict, output: Path) -> dict:
    """Focused fixture checks, independent of the exporter and without publication claims."""
    def keys(value: dict, required: set[str], optional: set[str] | None = None) -> None:
        if not isinstance(value, dict) or not required <= value.keys() or value.keys() - required - (optional or set()):
            raise ValueError(f"Unexpected/missing fixture fields; required={sorted(required)}")

    def numeric_tokens(value: str) -> Counter:
        # Chinese commas delimit values; only grouping commas within numeric tokens disappear.
        normalized = unicodedata.normalize("NFKC", value.replace("，", ";").replace("、", ";")).replace("−", "-")
        return Counter(token.replace(",", "") for token in NUMBERS.findall(normalized))

    def pair(value: dict) -> None:
        keys(value, set(LANGUAGES))
        if not all(isinstance(text, str) and text.strip() for text in value.values()):
            raise ValueError("An empty or non-string localized value was found")
        if numeric_tokens(value["en"]) != numeric_tokens(value["zh-CN"]):
            raise ValueError(f"Bilingual numeric mismatch: {value}")

    keys(report, {"schema", "source", "title", "subtitle", "publisher", "report_type", "date", "authors", "snapshot", "blocks", "source_inventory"})
    keys(report["source"], {"path", "sha256"})
    if report["schema"] != "equity-report/v1" or report["source"]["path"] != "source.md":
        raise ValueError("Unexpected fixture schema or source path")
    if digest(output / "source.md") != report["source"]["sha256"]:
        raise ValueError("Source digest mismatch")
    for key in ("title", "subtitle", "publisher", "report_type"):
        pair(report[key])
    for author in report["authors"]:
        pair(author)
    for item in report["snapshot"]:
        keys(item, {"label", "value"})
        pair(item["label"])
        pair(item["value"])
    ids = [block["id"] for block in report["blocks"]]
    if ids != report["source_inventory"] or len(ids) != len(set(ids)) or not all(isinstance(i, str) and i for i in ids):
        raise ValueError("Inventory/order/ID mismatch")
    fields = {
        "heading": {"text", "level"}, "paragraph": {"text"}, "bullets": {"items"},
        "table": {"title", "columns", "rows", "source"}, "figure": {"title", "caption", "source", "files"},
        "reference": {"text", "url"}, "page_break": set(),
    }
    for block in report["blocks"]:
        kind = block["type"]
        if kind not in fields:
            raise ValueError(f"Unknown block type: {kind}")
        keys(block, {"id", "type"} | fields[kind], {"notes"} if kind == "table" else set())
        for key in ("text", "title", "caption", "source", "notes"):
            if key in block:
                pair(block[key])
        if kind == "heading" and (type(block["level"]) is not int or block["level"] not in (1, 2)):
            raise ValueError("Invalid heading level")
        if kind == "bullets":
            if not block["items"]:
                raise ValueError("Empty bullet list")
            for item in block["items"]:
                pair(item)
        if kind == "table":
            if not 1 <= len(block["columns"]) <= 10 or not block["rows"]:
                raise ValueError("Invalid table dimensions")
            for cell in block["columns"]:
                pair(cell)
            for row in block["rows"]:
                if len(row) != len(block["columns"]):
                    raise ValueError("Ragged table")
                for cell in row:
                    pair(cell)
        if kind == "reference" and not block["url"].startswith("https://"):
            raise ValueError("Reference must use HTTPS")
        if kind == "figure":
            keys(block["files"], set(LANGUAGES))
            for language, filename in block["files"].items():
                with Image.open(output / filename) as asset:
                    if asset.format != "PNG" or asset.info.get("fixture_language") != language:
                        raise ValueError("Wrong fixture image type or language")
                    if json.loads(asset.info["fixture_data"]) != chart_data(report):
                        raise ValueError("Chart data differ from financial table")
                    asset.verify()
    return {"source_sha256": report["source"]["sha256"], "blocks": len(ids),
            "page_sections": 1 + sum(block["type"] == "page_break" for block in report["blocks"]),
            "table_rows": sum(len(block["rows"]) for block in report["blocks"] if block["type"] == "table"),
            "chart_data_equal": True, "numeric_tokens_equal": True, "finite_fields_only": True}


def write_reconciliation(report: dict, output: Path, spans: list[tuple[str, int, int]]) -> None:
    lines = [
        "# Fictional fixture reconciliation map", "",
        "This generated map locates the complete authored bilingual source. It is not an independent source audit or a publication approval. Read the full source, all table cells and both PNGs; after rendering, inspect every page of both PDFs and perform the separate hash-bound review.", "",
        f"Source: [source.md](source.md). SHA-256: `{report['source']['sha256']}`.", "",
        "The source Markdown contains all original text, metadata, footnotes, references, complete tables and embedded local figure references. Both chart datasets come from Exhibit 1. English and Mandarin labels share the same financial values and units. Page-break spans are layout instructions only.", "",
        "| Output component | Inclusive source lines | Authority |", "|---|---|---|",
    ]
    lines += [f"| `{component}` | {start}–{end} | Authored fictional original |" for component, start, end in spans]
    lines += ["", "## Chart authority", "", "The original data are the Revenue and Free cash flow rows of `financial-table`, in period order 2024A, 2025A, 2026E, 2027E. USD million is the unit in both panels. Parentheses denote negative amounts. Filled columns denote A and outlined columns E. The separate axes are intentional.", ""]
    for language in LANGUAGES:
        name = f"chart.{language}.png"
        lines.append(f"- [{name}]({name}): `{digest(output / name)}`; 1400 × 650 pixels.")
    lines += ["", "Charts were rasterized with Pillow using local DejaVu Sans and STHeiti Light (or explicitly configured equivalents). No font files are copied into this fixture. PNG metadata records language, labels and canonical data for fixture diagnostics; that metadata is not a substitute for checking visible labels.", "",
              "## Review status", "", "No PDF has been created or reviewed by this generator. No source-reconciliation, semantic or visual publication approval is asserted. The fixture is designed as four short page sections; actual pagination requires the parent's renderer and page inspection.", "",
              "The HTTPS reference uses example.com only to exercise long-link rendering. It is not financial evidence. All identities, periods and values are fictional, and this example's disclosure must not be carried into a real report.", ""]
    (output / "reconciliation.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True, help="Dedicated directory for the five fictional fixture files")
    args = parser.parse_args()
    output = args.output_dir.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = make_report()
    font_paths = fonts()
    data = chart_data(report)
    for language in LANGUAGES:
        make_chart(output / f"chart.{language}.png", language, data, font_paths)
    spans = write_source(report, output)
    report["source"]["sha256"] = digest(output / "source.md")
    checks = validate_fixture(report, output)
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_reconciliation(report, output, spans)
    print(json.dumps({"output_dir": str(output), "fixture_checks": checks, "pdfs_created": False}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
