"""Source-preserving, selected-language adapter for the vendored PDF skill.

This module deliberately imports no application configuration, storage, providers
or service bootstrap. Caller-owned snapshots are the only source authority.
"""
from __future__ import annotations

import copy
import hashlib
import html
import importlib.util
import json
import re
import shutil
import threading
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .contracts import PdfExportError

SKILL_DIR = Path(__file__).resolve().parents[2] / "skills" / "equity-research-pdf"
VERSION = "research-pdf-renderer/v1"
_RENDER_LOCK = threading.RLock()
_CORE = None
LAYOUT_SCHEMA = {
    "body_font_size": {"minimum": 9, "maximum": 11},
    "table_font_size": {"minimum": 7, "maximum": 9},
    "figure_max_height": {"minimum": 180, "maximum": 360},
    "page_break_before": "unique existing component IDs, excluding first",
    "table_column_weights": "table ID -> one weight per column, each 0.5..4",
}


def _error(code, message):
    raise PdfExportError(code, message)


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _core():
    global _CORE
    with _RENDER_LOCK:
        if _CORE is None:
            try:
                spec = importlib.util.spec_from_file_location(
                    "_research_pdf_vendored_export", SKILL_DIR / "scripts" / "export_report.py")
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
            except ImportError as exc:
                _error("pdf_dependencies_missing", "PDF dependencies are missing: install the backend's declared PDF dependencies (reportlab, pypdf, PyMuPDF, Pillow).")
            _CORE = module
    return _CORE


def _new_dir(directory, source_folder=None):
    directory = Path(directory).absolute()
    if directory.is_symlink() or directory.exists():
        _error("pdf_generation_exists", "Use a new private PDF generation directory; existing generations are immutable.")
    directory = directory.resolve()
    if source_folder and (directory.is_relative_to(source_folder) or source_folder.is_relative_to(directory)):
        _error("pdf_generation_unsafe", "PDF derivatives must use a separate private generation outside the snapshot directory.")
    directory.mkdir(parents=True)
    return directory


def _inside(folder, relative):
    rel = Path(relative)
    path = (folder / rel).resolve()
    if rel.is_absolute() or not path.is_relative_to(folder) or not path.is_file():
        _error("pdf_asset_unsafe", "A PDF source asset is missing or escapes the private snapshot; capture it inside the snapshot first.")
    return path


def _url(value, *, internal=True):
    # Mistune already decodes Markdown link destinations. A second HTML decode
    # would corrupt query keys such as &notional= into the semicolonless &not.
    try:
        parsed = urlsplit(value)
    except ValueError:
        _error("pdf_link_unsafe", "A report hyperlink is malformed; correct the source destination before exporting.")
    if internal and value.startswith("#") and len(value) > 1:
        return value
    if (parsed.scheme not in ("http", "https", "mailto") or
            (parsed.scheme != "mailto" and not parsed.hostname) or parsed.username or parsed.password or
            any(c.isspace() or ord(c) < 32 for c in value)):
        _error("pdf_link_unsupported", "A required link has an unsafe or local-only destination. Supply a supported HTTP(S), mailto or internal heading link; local interactive charts need an inventoried static image.")
    return value


def _parse(markdown):
    try:
        import mistune
        from mistune.plugins import import_plugin
    except ImportError:
        _error("pdf_parser_missing", "Install the backend's declared mistune >=3.3.4,<4 dependency to inventory Markdown.")

    class PositionState(mistune.BlockState):
        def add_paragraph(self, text):
            old = len(self.tokens)
            super().add_paragraph(text)
            if len(self.tokens) > old:
                self.tokens[-1]["_start"] = self.cursor

    class PositionParser(mistune.BlockParser):
        state_cls = PositionState

        def parse_method(self, match, state):
            start = state.cursor
            old = {id(t) for t in state.tokens}
            end = super().parse_method(match, state)
            if end:
                for token in state.tokens:
                    if id(token) not in old:
                        token.setdefault("_start", start)
                        token.setdefault("_end", end)
            return end

    parser = mistune.Markdown(block=PositionParser(), plugins=[import_plugin(p) for p in
        ("table", "footnotes", "strikethrough", "url", "task_lists", "math")])
    tokens, state = parser.parse(markdown)
    # Footnote definitions not referenced in the body remain source content.
    # Mistune normally removes them from the rendered token stream.
    used = {n["attrs"]["key"] for t in tokens if t["type"] == "footnotes" for n in t["children"]}
    extra = []
    from mistune.plugins.footnotes import parse_footnote_item
    for key in state.env.get("ref_footnotes", {}):
        if key not in used:
            extra.append(parse_footnote_item(parser.block, key, len(used)+len(extra)+1, state))
    if extra:
        footer_state = mistune.BlockState(parent=state)
        footer_state.tokens = [{"type": "footnotes", "children": extra}]
        tokens.extend(parser.render_state(footer_state))
    return tokens, state.env, mistune.__version__


class _Adapter:
    def __init__(self, snapshot, directory, tokens):
        self.snapshot, self.directory, self.tokens = snapshot, directory, tokens
        self.language = snapshot["language"]
        self.blocks, self.components, self.inline, self.anchors = [], [], {}, {}
        self.figure_groups = {}
        self.chart_link_adaptations = []
        self.figure_assets = {}
        citations = snapshot.get("citations", {})
        if isinstance(citations, dict) and isinstance(citations.get("markers"), list):
            citations = {row["tag"]: row for row in citations["markers"] if isinstance(row, dict) and row.get("tag")}
        self.citations = {str(key).strip("[]").upper(): value for key, value in citations.items()} if isinstance(citations, dict) else {}
        self.images, self.used_assets, self.pending_links = {}, [], []
        self.heading_counts, self.heading_targets = {}, {}
        self.assets = {a["relative_path"]: a for a in snapshot.get("assets", [])}
        if len(self.assets) != len(snapshot.get("assets", [])):
            _error("pdf_snapshot_invalid", "The snapshot contains duplicate asset paths; capture a unique immutable asset inventory.")
        self.folder = Path(snapshot["folder"]).resolve()
        self.asset_map = snapshot.get("asset_map", {})
        self.figure_hint = None
        self.comment_records = []
        self.footnote_labels = {re.sub(r"\s+", " ", key).strip().upper(): key
                               for key in re.findall(r"(?m)^ {0,3}\[\^([^\]]+)\]:", snapshot["markdown"])}
        # Root offsets are in Mistune's newline-normalized input. Retain a map
        # back to original character offsets so CRLF source bytes stay intact.
        original = snapshot["markdown"]
        offsets, cursor = [0], 0
        while cursor < len(original):
            cursor += 2 if original[cursor:cursor+2] == "\r\n" else 1
            offsets.append(cursor)
        starts = [(i, offsets[min(t["_start"], len(offsets)-1)])
                  for i, t in enumerate(tokens) if isinstance(t.get("_start"), int)]
        self.root_spans = {i: (start, end) for (i, start), (_, end)
                           in zip(starts, starts[1:] + [(len(tokens), len(original))], strict=False)}

    def loc(self, value):
        return {self.language: value}

    def runs(self, nodes, style=None):
        style = dict(style or {})
        result = []
        for node in nodes:
            kind = node["type"]
            attrs = node.get("attrs", {})
            if kind == "text":
                # CommonMark entities require a semicolon; html.unescape alone
                # also consumes ordinary prose such as "&notional".
                text = re.sub(r"&(?:#[0-9]{1,7}|#[xX][0-9a-fA-F]{1,6}|[A-Za-z][A-Za-z0-9]{1,31});",
                              lambda m: html.unescape(m[0]), node.get("raw", ""))
                result.append({"text": text, **style})
            elif kind in ("softbreak", "linebreak"):
                result.append({"text": "\n" if kind == "linebreak" else " ", **style})
            elif kind in ("strong", "emphasis", "strikethrough"):
                result.extend(self.runs(node["children"], {**style, {"strong": "bold", "emphasis": "italic", "strikethrough": "strike"}[kind]: True}))
            elif kind == "codespan":
                result.append({"text": node["raw"], **style, "code": True})
            elif kind == "link":
                raw = attrs["url"]
                local_chart = self._chart_reference(raw)
                url = raw if local_chart else _url(raw)
                link_style = {**style, "url": url}
                if local_chart:
                    link_style["chart_href"] = raw
                result.extend(self.runs(node["children"], link_style))
            elif kind == "footnote_ref":
                key = node["raw"]
                label = self.footnote_labels.get(key, key)
                result.append({"text": f"[^{label}]", **style, "url": "#footnote-" + _sha(key.encode())[:12]})
            elif kind == "inline_html" and re.fullmatch(r"<br\s*/?>", node["raw"], re.I):
                result.append({"text": "\n", **style})
            elif kind == "inline_html" and re.fullmatch(r"<!--.*?-->", node["raw"], re.S):
                self.comment_records.append(node["raw"])
            elif kind in ("inline_math", "block_math"):
                _error("pdf_math_unsupported", "Required mathematics needs a verified static equation representation captured as a snapshot asset; export will not substitute raw formula code.")
            else:
                _error("pdf_markdown_unsupported", f"Required Markdown inline structure {kind!r} is unsupported. Supply a source-preserving supported representation before exporting.")
        return result

    def field(self, bid, name, runs):
        ident = f"{bid}.{name}"
        resolved = []
        for run in runs:
            if run.get("url") or run.get("code"):
                resolved.append(run)
                continue
            start = 0
            for marker in re.finditer(r"\[S\d+(?:-[A-Za-z])?(?:,\s*S\d+(?:-[A-Za-z])?)*\]", run["text"]):
                resolved.append({**run, "text": run["text"][start:marker.start()]})
                inner = marker[0]
                tags = list(re.finditer(r"S\d+(?:-[A-Za-z])?", inner))
                position = 0
                for tag in tags:
                    record = self.citations.get(tag[0].upper())
                    value = record.get("url") if isinstance(record, dict) else record
                    if not isinstance(value, str) or not value or (isinstance(record, dict) and record.get("url_valid") is False):
                        _error("pdf_citation_unresolved", f"Required citation {tag[0]} has no admitted source URL in the snapshot citation map; capture its source reference before exporting.")
                    url = _url(value, internal=False)
                    if len(tags) == 1:
                        resolved.append({**run, "text": inner, "url": url})
                    else:
                        resolved.append({**run, "text": inner[position:tag.start()]})
                        resolved.append({**run, "text": tag[0], "url": url})
                        position = tag.end()
                if len(tags) > 1:
                    resolved.append({**run, "text": inner[position:]})
                start = marker.end()
            resolved.append({**run, "text": run["text"][start:]})
        runs = [r for r in resolved if r["text"]]
        self.inline[ident] = runs
        return self.loc("".join(r["text"] for r in runs))

    def add(self, kind, locator, *, text=None, prefix="", **fields):
        bid = f"c{len(self.blocks)+1:05d}"
        block = {"id": bid, "type": kind, **fields}
        indentation = len(prefix) - len(prefix.lstrip(" "))
        if indentation:
            block["indent"] = indentation * 10
        if text is not None:
            runs = ([{"text": prefix}] if prefix else []) + text
            block["text"] = self.field(bid, "text", runs)
        self.blocks.append(block)
        self.components.append({"id": bid, "kind": kind, "source_locator": locator,
                                "source_text": "", "render_text": ""})
        return block

    def image(self, node, locator):
        raw = node["attrs"]["url"]
        rel = self.asset_map.get(raw)
        if rel is None:
            parsed = urlsplit(raw)
            if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
                _error("pdf_asset_not_captured", "A required image has no source-bound snapshot mapping. Capture the resource-local chart and map its original reference; remote image fetches are disabled.")
            rel = unquote(raw)
        if rel not in self.assets:
            _error("pdf_asset_not_captured", "A required chart is absent from the immutable snapshot asset inventory; capture it before export.")
        src = _inside(self.folder, rel)
        data = src.read_bytes()
        if _sha(data) != self.assets[rel]["sha256"]:
            _error("pdf_source_changed", "A snapshot chart changed after capture; create a fresh export snapshot.")
        core = _core()
        try:
            from PIL import Image
            with Image.open(src) as im:
                if im.format not in ("PNG", "JPEG"):
                    _error("pdf_image_unsupported", "A required chart is not PNG/JPEG. Capture a verified static PNG/JPEG derivative in the snapshot or add a bounded private converter.")
                im.verify()
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            if isinstance(exc, PdfExportError):
                raise
            _error("pdf_image_invalid", "A captured chart is damaged or not a supported static image; replace it with verified source pixels.")
        dest_rel = "assets/" + self.assets[rel]["sha256"] + src.suffix.lower()
        dest = self.directory / dest_rel
        dest.parent.mkdir(exist_ok=True)
        if not dest.exists():
            dest.write_bytes(data)
        caption_runs = self.runs(node.get("children", []))
        block = self.add("figure", locator, files={self.language: dest_rel})
        if caption_runs and any(r["text"] for r in caption_runs):
            block["caption"] = self.field(block["id"], "caption", caption_runs)
        title = node["attrs"].get("title")
        if title:
            block["title"] = self.field(block["id"], "title", [{"text": title}])
        self.components[-1].update({"asset_reference": raw, "asset_sha256": _sha(data),
                                   "figure_association": self.figure_hint})
        self.used_assets.append({"id": block["id"], "language": self.language, "path": str(dest), "sha256": core.digest(dest), "source_reference": raw})
        self.figure_assets[block["id"]] = rel
        self.figure_hint = None

    def _chart_reference(self, raw):
        """Only captured charts/*.html companions may be adapted, never executed."""
        try:
            parsed = urlsplit(raw)
        except ValueError:
            return None
        relative = unquote(parsed.path)
        path = Path(relative)
        if (parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or path.is_absolute()
                or "\\" in relative or ".." in path.parts or not path.parts or path.parts[0] != "charts"
                or path.suffix.lower() != ".html"):
            return None
        relative = path.as_posix()
        if relative not in self.assets:
            _error("pdf_chart_link_missing", "A local interactive chart link is not in the captured asset inventory; capture its HTML and static companion before export.")
        return relative

    def _manifest_companion(self, relative):
        manifest = self.snapshot.get("chart_manifest", [])
        if isinstance(manifest, dict):
            manifest = manifest.get("items", [])
        pairs = []
        for row in manifest if isinstance(manifest, list) else []:
            if not isinstance(row, dict):
                continue
            if row.get("html_path") == relative:
                pairs.append((row.get("path"), row))
            elif row.get("path") == relative and row.get("png_path"):
                pairs.append((row["png_path"], row))
        candidates = {path for path, _ in pairs if isinstance(path, str)}
        if len(candidates) > 1:
            _error("pdf_chart_binding_ambiguous", "The captured chart manifest assigns conflicting static companions to one interactive chart.")
        return next(((path, row) for path, row in pairs if path in candidates), (None, None))

    def _link_locator(self, owner, href):
        def find(node, path):
            if node.get("type") == "link" and node.get("attrs", {}).get("url") == href:
                return path
            for i, child in enumerate(node.get("children", [])):
                found = find(child, path + [i])
                if found is not None:
                    return found
            return None
        locator = find(self._node(owner["source_locator"]), owner["source_locator"])
        if locator is None:
            _error("pdf_chart_binding_invalid", "An interactive chart adaptation lacks its original source link locator.")
        return locator

    def _bind_chart_links(self):
        # Iterate a snapshot: a manifest-backed link-only chart can append one
        # derived figure, but cannot recursively create additional adaptations.
        for ident, original_runs in list(self.inline.items()):
            if not any(r.get("chart_href") for r in original_runs):
                continue
            bid, field = ident.split(".", 1)
            owner = next(c for c in self.components if c["id"] == bid)
            rewritten, index = [], 0
            while index < len(original_runs):
                run = original_runs[index]
                href = run.get("chart_href")
                if not href:
                    rewritten.append(run)
                    index += 1
                    continue
                group = []
                while index < len(original_runs) and original_runs[index].get("chart_href") == href:
                    group.append(original_runs[index])
                    index += 1
                relative = self._chart_reference(href)
                html_path = _inside(self.folder, relative)
                html_bytes = html_path.read_bytes()
                if _sha(html_bytes) != self.assets[relative]["sha256"]:
                    _error("pdf_source_changed", "The captured interactive chart changed; capture a fresh source snapshot.")
                static, manifest_row = self._manifest_companion(relative)
                candidates = []
                owner_index = next(i for i, b in enumerate(self.blocks) if b["id"] == bid)
                for i, figure in enumerate(self.blocks):
                    asset = self.figure_assets.get(figure["id"])
                    if asset is None:
                        continue
                    if static is not None:
                        matches = asset == static
                    else:
                        matches = Path(asset).with_suffix("") == Path(relative).with_suffix("")
                        allowed = {figure.get(k, {}).get(self.language) for k in ("title", "caption")}
                        between = self.blocks[min(i, owner_index)+1:max(i, owner_index)]
                        matches = matches and all(b.get("figure_id") == figure["id"] or
                            (b["type"] in ("paragraph", "quote") and b.get("text", {}).get(self.language) in allowed)
                            for b in between)
                    if matches:
                        candidates.append((abs(i-owner_index), figure, asset))
                derived = False
                locator = self._link_locator(owner, href)
                label = "".join(r["text"] for r in group)
                if not candidates and static is not None:
                    if static not in self.assets or Path(static).suffix.lower() not in (".png", ".jpg", ".jpeg"):
                        _error("pdf_chart_static_missing", "The manifest's static chart companion was not captured as a supported PNG/JPEG image.")
                    title = manifest_row.get("title") or label
                    self.image({"type": "image", "attrs": {"url": static},
                                "children": [{"type": "text", "raw": title}]}, locator)
                    figure, component = self.blocks.pop(), self.components.pop()
                    component.update(derived=True, derivation="static companion from captured chart manifest")
                    self.blocks.insert(owner_index+1, figure)
                    self.components.insert(owner_index+1, component)
                    candidates = [(1, figure, static)]
                    derived = True
                if not candidates:
                    _error("pdf_chart_binding_missing", "An interactive chart needs an adjacent same-stem rendered static figure or an explicit captured chart-manifest pair. No HTML is executed.")
                candidates.sort(key=lambda item: item[0])
                if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
                    _error("pdf_chart_binding_ambiguous", "An interactive chart link has multiple equally adjacent static figures; provide unambiguous source placement.")
                _, figure, static = candidates[0]
                anchor = "figure-" + figure["id"]
                self.anchors.setdefault(figure["id"] + ".image", [])
                if anchor not in self.anchors[figure["id"] + ".image"]:
                    self.anchors[figure["id"] + ".image"].append(anchor)
                for item in group:
                    rewritten.append({k: v for k, v in {**item, "url": "#" + anchor}.items() if k != "chart_href"})
                note = (f"（PDF 静态图；原交互链接：{href}）" if self.language == "zh-CN" else
                        f" (static PDF chart; original interactive destination: {href})")
                rewritten.append({"text": note})
                adaptation = {"component_id": bid, "field": ident, "source_locator": locator,
                    "original_label": label, "original_destination": href, "pdf_destination": "#"+anchor,
                    "figure_id": figure["id"], "static_asset": static,
                    "html_sha256": _sha(html_bytes), "static_sha256": self.assets[static]["sha256"],
                    "binding": "captured_chart_manifest" if manifest_row is not None else "adjacent_source_companion",
                    "manifest_entry": manifest_row, "derived_figure": derived, "visible_adaptation": note}
                self.chart_link_adaptations.append(adaptation)
                owner.setdefault("adaptations", []).append(adaptation)
                if derived:
                    next(c for c in self.components if c["id"] == figure["id"]).setdefault("adaptations", []).append(adaptation)
                companion = self.directory / "companions" / (_sha(html_bytes) + ".html")
                companion.parent.mkdir(exist_ok=True)
                if not companion.exists():
                    companion.write_bytes(html_bytes)
                    self.used_assets.append({"id": bid, "kind": "interactive_source_only", "language": self.language,
                        "path": str(companion), "sha256": _sha(html_bytes), "source_reference": href})
            self.inline[ident] = rewritten
            block = next(b for b in self.blocks if b["id"] == bid)
            value = self.loc("".join(r["text"] for r in rewritten))
            if field.startswith("header."):
                block["columns"][int(field.split(".")[1])] = value
            elif field.startswith("cell."):
                _, row, column = field.split(".")
                block["rows"][int(row)][int(column)] = value
            else:
                block[field] = value

    def paragraph(self, node, locator, prefix="", quote=False):
        nodes = node.get("children", [])
        current = []
        for index, child in enumerate(nodes):
            if child["type"] == "image":
                if current:
                    self.add("quote" if quote else "paragraph", locator, text=self.runs(current), prefix=prefix)
                    current, prefix = [], ""
                elif prefix:
                    self.add("quote" if quote else "paragraph", locator, text=[{"text": prefix.rstrip()}])
                    prefix = ""
                self.image(child, locator + [index])
            else:
                current.append(child)
        if current:
            runs = self.runs(current)
            if any(r["text"].strip() for r in runs):
                self.add("quote" if quote else "paragraph", locator, text=runs, prefix=prefix)

    def walk(self, nodes, path=(), *, prefix="", quote=False, depth=0):
        for index, node in enumerate(nodes):
            locator = [*path, index]
            kind, attrs = node["type"], node.get("attrs", {})
            if kind == "blank_line":
                continue
            if prefix and kind not in ("paragraph", "block_text", "heading", "block_quote"):
                self.add("quote" if quote else "paragraph", locator, text=[{"text": prefix.rstrip()}])
                prefix = ""
            if kind in ("paragraph", "block_text"):
                self.paragraph(node, locator, prefix, quote)
                prefix = ""
            elif kind == "heading":
                heading_runs = self.runs(node["children"])
                source_heading = "".join(run["text"] for run in heading_runs)
                block = self.add("heading", locator, text=heading_runs, prefix=prefix, level=attrs["level"])
                prefix = ""
                slug = re.sub(r"[^\w\- ]", "", source_heading.lower()).replace(" ", "-")
                count = self.heading_counts.get(slug, 0)
                self.heading_counts[slug] = count + 1
                slug = slug + (f"-{count}" if count else "")
                anchor = "heading-" + block["id"]
                self.heading_targets[slug] = anchor
                self.anchors[block["id"] + ".text"] = [anchor]
            elif kind == "list":
                for offset, item in enumerate(node["children"]):
                    marker = f"{attrs.get('start', 1) + offset}. " if attrs.get("ordered") else "• "
                    if item["type"] == "task_list_item":
                        marker += "[x] " if item["attrs"]["checked"] else "[ ] "
                    self.walk(item["children"], [*locator, offset], prefix="  " * depth + marker, quote=quote, depth=depth+1)
            elif kind == "block_quote":
                self.walk(node["children"], locator, prefix=prefix, quote=True, depth=depth)
            elif kind == "table":
                head, body = node["children"]
                columns, rows = head["children"], body["children"]
                if not columns or len(columns) > 10:
                    _error("pdf_table_too_wide", "A required table exceeds 10 columns. Split it in the source with repeated row identifiers/units before exporting; columns will not be omitted.")
                block = self.add("table", locator, columns=[], rows=[], alignments=[c.get("attrs", {}).get("align") for c in columns])
                bid = block["id"]
                for ci, col in enumerate(columns):
                    block["columns"].append(self.field(bid, f"header.{ci}", self.runs(col["children"])))
                for ri, row in enumerate(rows):
                    if len(row["children"]) != len(columns):
                        _error("pdf_table_shape", "A source table row has a mismatched cell count; repair the source before export.")
                    block["rows"].append([self.field(bid, f"cell.{ri}.{ci}", self.runs(c["children"])) for ci, c in enumerate(row["children"])])
            elif kind == "block_code":
                info = attrs.get("info", "")
                if info.lower().split(" ")[0] in ("mermaid", "dot", "graphviz", "plantuml", "math", "latex", "tex"):
                    _error("pdf_diagram_unsupported", "A required diagram/equation has no verified static representation. Capture its rendered PNG/JPEG as a snapshot figure; diagram code is not a substitute. Conversion may only run in a private generation with a bounded approved converter.")
                block = self.add("code", locator, text=[{"text": node.get("raw", "").rstrip("\n"), "code": True}])
                if info:
                    block["title"] = self.loc(info)
            elif kind == "block_math":
                _error("pdf_math_unsupported", "A required equation needs a verified static equation representation captured as a snapshot asset; raw formula code cannot substitute for the equation.")
            elif kind == "thematic_break":
                self.add("separator", locator)
            elif kind == "block_html":
                raw = node["raw"].strip()
                if re.fullmatch(r"(?:<!--.*?-->\s*)+", raw, re.S):
                    self.comment_records.append(raw)
                    match = re.search(r"<!--\s*viz:(.*?)\s*-->", raw)
                    if match:
                        self.figure_hint = match[1]
                else:
                    _error("pdf_html_unsupported", "Required raw HTML is unsupported by the source-preserving PDF adapter. Convert it to supported Markdown/static figures in the authoritative source; active HTML is never executed.")
            elif kind == "footnotes":
                for fi, item in enumerate(node["children"]):
                    key = item["attrs"]["key"]
                    before = len(self.blocks)
                    label = f"[^{self.footnote_labels.get(key, key)}]"
                    first = next((n for n in item["children"] if n["type"] != "blank_line"), {})
                    if first.get("type") not in ("paragraph", "block_text") or any(
                            n["type"] == "image" for n in first.get("children", [])):
                        self.add("paragraph", [*locator, fi], text=[{"text": label}])
                        self.walk(item["children"], [*locator, fi])
                    else:
                        self.walk(item["children"], [*locator, fi], prefix=label + " ")
                    if len(self.blocks) == before:
                        _error("pdf_footnote_empty", "A required footnote has no renderable source content.")
                    ident = self.blocks[before]["id"] + ".text"
                    self.anchors.setdefault(ident, []).append("footnote-" + _sha(key.encode())[:12])
            else:
                _error("pdf_markdown_unsupported", f"Required Markdown structure {kind!r} has no supported PDF representation; preserve it in a verified static asset or extend the adapter.")

    def finish(self):
        # Keep explicitly labelled attribution/qualifier paragraphs attached to
        # their chart. The source remains a separate inventory component.
        figure = None
        for block in self.blocks:
            if block["type"] == "figure":
                figure = block["id"]
            elif figure and block["type"] in ("paragraph", "quote") and re.match(
                    r"^\s*(?:Sources?|Notes?|Footnotes?|Caption|Units?|Qualifications?|Disclaimer|"
                    r"来源|资料来源|数据来源|注|备注|单位|说明|限定|免责声明)\s*[:：]",
                    block["text"][self.language], re.I):
                self.figure_groups.setdefault(figure, []).append(block["id"])
                block["figure_id"] = figure
            else:
                figure = None
        self._bind_chart_links()
        anchors = {a for values in self.anchors.values() for a in values}
        for runs in self.inline.values():
            for run in runs:
                url = run.get("url", "")
                if url.startswith("#"):
                    target = unquote(url[1:])
                    target = self.heading_targets.get(target, target)
                    if target not in anchors:
                        _error("pdf_link_unresolved", "A required internal heading/footnote link has no rendered target; correct the source cross-reference.")
                    run["url"] = "#" + target
        for block, component in zip(self.blocks, self.components, strict=True):
            values = []
            for field in ("title", "text", "caption", "source", "notes"):
                if field in block:
                    values.append(block[field][self.language])
            if block["type"] == "table":
                values.extend(c[self.language] for c in block["columns"])
                values.extend(c[self.language] for row in block["rows"] for c in row)
            component["render_text"] = "\n".join(values)
            span = self.root_spans.get(component["source_locator"][0])
            if span:
                start, end = span
                component["source_span"] = {"start": start, "end": end,
                    "line_start": self.snapshot["markdown"][:start].count("\n") + 1,
                    "line_end": self.snapshot["markdown"][:end].count("\n") + 1}
                component["source_text"] = self.snapshot["markdown"][start:end]
            else:
                # Footnote plugin moves definitions to its trailing token tree;
                # their original definition text remains in the complete source
                # and reference environment, not an invented positional span.
                component["source_text"] = json.dumps(self._node(component["source_locator"]), ensure_ascii=False)
            component["links"] = [r["url"] for ident, runs in self.inline.items() if ident.startswith(block["id"] + ".") for r in runs if "url" in r]
            component["source_node_sha256"] = _sha(json.dumps(self._node(component["source_locator"]), ensure_ascii=False, sort_keys=True).encode())

    def _node(self, locator):
        nodes = self.tokens
        node = None
        for index in locator:
            node = nodes[index]
            nodes = node.get("children", [])
        return node


def prepare_document(snapshot: dict, directory: Path) -> dict:
    """Freeze full source, map every supported visible component, select one language."""
    if snapshot.get("schema") != "research-pdf-source/v1" or snapshot.get("language") not in ("en", "zh-CN"):
        _error("pdf_snapshot_invalid", "Expected a source-bound research PDF snapshot with language en or zh-CN.")
    markdown = snapshot.get("markdown")
    if not isinstance(markdown, str) or not markdown.strip():
        _error("pdf_source_empty", "The selected report has no Markdown content to export.")
    raw = markdown.encode("utf-8")
    if _sha(raw) != snapshot.get("markdown_sha256"):
        _error("pdf_source_changed", "Snapshot Markdown does not match its captured hash; prepare a fresh source snapshot.")
    folder = Path(snapshot["folder"]).resolve()
    source = Path(snapshot["markdown_path"]).resolve()
    if not source.is_relative_to(folder) or not source.is_file() or source.read_bytes() != raw:
        _error("pdf_source_changed", "The private snapshot source file is missing or differs from the supplied Markdown.")
    tokens, env, parser_version = _parse(markdown)
    directory = _new_dir(directory, folder)
    try:
        (directory / "source.md").write_bytes(raw)
        adapter = _Adapter(snapshot, directory, tokens)
        adapter.walk(tokens)
        adapter.finish()
        if not adapter.blocks:
            _error("pdf_source_empty", "The selected source contains no visible supported report components.")
        language = snapshot["language"]
        loc = adapter.loc
        report = {"schema": "equity-report-selected/v1", "language": language,
                  "source": {"path": "source.md", "sha256": _sha(raw)},
                  "title": loc(snapshot["title"]), "publisher": loc(snapshot["publisher"]),
                  "report_type": loc(snapshot["report_type"]), "date": snapshot["date"],
                  "authors": [], "snapshot": [], "blocks": adapter.blocks,
                  "source_inventory": [b["id"] for b in adapter.blocks],
                  "inline": adapter.inline, "anchors": adapter.anchors,
                  "figure_groups": adapter.figure_groups,
                  "chart_link_adaptations": adapter.chart_link_adaptations}
        inventory = {"schema": "research-pdf-inventory/v1", "source_digest": snapshot["source_digest"],
                     "source_markdown_sha256": _sha(raw), "source_markdown": markdown,
                     "source_metadata": {k: copy.deepcopy(v) for k, v in snapshot.items() if k != "markdown"},
                     "parser": {"name": "mistune", "version": parser_version},
                     "tokens": tokens, "reference_environment": env,
                     "components": adapter.components, "hidden_comments": adapter.comment_records,
                     "assets": adapter.used_assets, "chart_link_adaptations": adapter.chart_link_adaptations}
        report_path, inventory_path = directory / "report.json", directory / "source-inventory.json"
        _json(report_path, report)
        _json(inventory_path, inventory)
        frozen = {str(p.relative_to(directory)): _sha(p.read_bytes()) for p in sorted(directory.rglob("*")) if p.is_file()}
        manifest_path = directory / "input-manifest.json"
        _json(manifest_path, {"schema": "research-pdf-input/v1", "files": frozen, "source_digest": snapshot["source_digest"]})
        if source.read_bytes() != raw:
            _error("pdf_source_changed", "The snapshot Markdown changed during preparation; capture a fresh snapshot.")
        for asset in snapshot.get("assets", []):
            if _sha(_inside(folder, asset["relative_path"]).read_bytes()) != asset["sha256"]:
                _error("pdf_source_changed", "A snapshot asset changed during preparation; capture a fresh snapshot.")
        return {"report": report, "components": adapter.components, "source_digest": snapshot["source_digest"],
                "input_sha256": _sha(report_path.read_bytes()), "report_path": str(report_path), "language": language,
                "inventory_path": str(inventory_path), "inventory_sha256": _sha(inventory_path.read_bytes()),
                "manifest_path": str(manifest_path), "manifest_sha256": _sha(manifest_path.read_bytes()),
                "assets": adapter.used_assets, "layout_schema": copy.deepcopy(LAYOUT_SCHEMA)}
    except BaseException:
        shutil.rmtree(directory)
        raise


def _verify_prepared(prepared):
    report_path = Path(prepared["report_path"]).resolve()
    base = report_path.parent
    for name in ("manifest", "inventory"):
        path = Path(prepared[name + "_path"]).resolve()
        if not path.is_relative_to(base) or not path.is_file() or _sha(path.read_bytes()) != prepared[name + "_sha256"]:
            _error("pdf_input_changed", "The prepared source inventory or manifest changed; prepare a new generation.")
    manifest = json.loads(Path(prepared["manifest_path"]).read_text())
    for rel, sha in manifest["files"].items():
        if _sha(_inside(base, rel).read_bytes()) != sha:
            _error("pdf_input_changed", "A prepared input dependency changed; prepare a new generation.")
    if _sha(report_path.read_bytes()) != prepared["input_sha256"]:
        _error("pdf_input_changed", "The normalized report changed after preparation.")
    report = json.loads(report_path.read_text())
    inventory = json.loads(Path(prepared["inventory_path"]).read_text())
    if (prepared["report"] != report or prepared["components"] != inventory["components"] or
            prepared["source_digest"] != inventory["source_digest"] or prepared["language"] != report["language"]):
        _error("pdf_input_changed", "Prepared in-memory content differs from the frozen source inventory.")
    return report, base, inventory


def _layout(layout, report):
    if layout is None:
        return {}
    if not isinstance(layout, dict) or set(layout) - LAYOUT_SCHEMA.keys():
        _error("pdf_layout_invalid", "Unsupported PDF layout control; use the documented bounded layout schema.")
    result = copy.deepcopy(layout)
    for name in ("body_font_size", "table_font_size", "figure_max_height"):
        if name in result:
            value = result[name]
            limits = LAYOUT_SCHEMA[name]
            if type(value) not in (int, float) or not limits["minimum"] <= value <= limits["maximum"]:
                _error("pdf_layout_invalid", f"{name} must be between {limits['minimum']} and {limits['maximum']}.")
    breaks = result.get("page_break_before", [])
    ids = report["source_inventory"]
    if not isinstance(breaks, list) or any(not isinstance(b, str) for b in breaks) or len(set(breaks)) != len(breaks) or any(b not in ids[1:] for b in breaks):
        _error("pdf_layout_invalid", "Page breaks must identify unique existing blocks after the first block.")
    associated = {bid for members in report.get("figure_groups", {}).values() for bid in members}
    if associated.intersection(breaks):
        _error("pdf_layout_invalid", "A page break cannot separate a chart from its source attribution or qualifications; break before the figure instead.")
    weights = result.get("table_column_weights", {})
    tables = {b["id"]: b for b in report["blocks"] if b["type"] == "table"}
    if not isinstance(weights, dict):
        _error("pdf_layout_invalid", "Table column weights must be an object keyed by table ID.")
    for bid, row in weights.items():
        if bid not in tables or not isinstance(row, list) or len(row) != len(tables[bid]["columns"]) or any(type(w) not in (int, float) or not .5 <= w <= 4 for w in row):
            _error("pdf_layout_invalid", "Table weights require one value in 0.5..4 for every existing column.")
    return result


def _check_links(core, report, pdf, log):
    """Bind every visible link label to its destination and drawn text region."""
    def joined(pairs):
        groups = []
        for destination, text in pairs:
            text = core.normalized(text)
            if not text:
                continue
            if groups and groups[-1][0] == destination:
                groups[-1][1] += text
            else:
                groups.append([destination, text])
        return groups

    anchors = {anchor: ident for ident, names in report["anchors"].items() for anchor in names}
    headers = {f"{b['id']}.header.{i}" for b in report["blocks"] if b["type"] == "table" for i in range(len(b["columns"]))}
    with core.fitz.open(pdf) as doc:
        chars = {}
        for page_index, page in enumerate(doc):
            chars[page_index] = [char for block in page.get_text("rawdict")["blocks"]
                for line in block.get("lines", []) for span in line.get("spans", []) for char in span["chars"]]
        count = 0
        for ident, runs in report["inline"].items():
            expected = joined((r["url"], r["text"]) for r in runs if r.get("url"))
            regions = [r for r in log if r["id"] == ident]
            actual, seen = [], set()
            for region in regions:
                page_index = region["page"]-1
                page = doc[page_index]
                rect = core.fitz.Rect(region["rect"])
                for link in sorted(page.get_links(), key=lambda item: (round(item["from"].y0, 1), item["from"].x0)):
                    box = link["from"]
                    key = (page_index, link["xref"])
                    if key in seen or not rect.intersects(box):
                        continue
                    seen.add(key)
                    label = "".join(c["c"] for c in chars[page_index]
                        if box.x0 - .1 <= (c["bbox"][0]+c["bbox"][2])/2 <= box.x1 + .1
                        and box.y0 - .5 <= (c["bbox"][1]+c["bbox"][3])/2 <= box.y1 + .5)
                    destination = link.get("uri")
                    if destination is None:
                        point = link.get("to")
                        candidates = []
                        for anchor, target in anchors.items():
                            for draw in log:
                                if draw["id"] == target and link.get("page") == draw["page"]-1 and point is not None:
                                    x0, y0, x1, y1 = draw["rect"]
                                    if abs(point.y-y0) < 1 and abs(point.x-x0) < 1:
                                        candidates.append("#" + anchor)
                        destination = next((url for url, _ in expected if url in candidates), None)
                    actual.append((destination, label))
            wanted = expected * (len(regions) if ident in headers else 1)
            if joined(actual) != joined(wanted):
                _error("pdf_link_qa_failed", f"A hyperlink label/destination in {ident} is missing, extra, or misplaced in the PDF.")
            count += len(wanted)
        return count


def _check_figure_groups(report, log):
    for figure in (b for b in report["blocks"] if b["type"] == "figure"):
        bid = figure["id"]
        image = next(r for r in log if r["id"] == bid + ".image")
        fields = [bid + "." + name for name in ("title", "caption", "source") if name in figure]
        fields += [note + ".text" for note in report.get("figure_groups", {}).get(bid, [])]
        figure_index = report["blocks"].index(figure)
        headings = []
        for previous in reversed(report["blocks"][:figure_index]):
            if previous["type"] != "heading":
                break
            headings.append(previous["id"] + ".text")
        fields += headings
        for field in fields:
            regions = [r for r in log if r["id"] == field]
            if not regions or any(r["page"] != image["page"] for r in regions):
                _error("pdf_figure_qa_failed", "A chart's title, attribution or qualification was separated from its pixels; use a smaller figure or an explicit source-preserving layout.")
            if field != bid + ".title" and field not in headings and any(r["rect"][1] < image["rect"][3] - 1 for r in regions):
                _error("pdf_figure_qa_failed", "A chart's attribution or qualification is misplaced relative to its pixels.")


def render_document(prepared: dict, directory: Path, layout: dict | None = None) -> dict:
    """Build and check real PDF bytes; review/publication belong to the caller."""
    report, base, inventory = _verify_prepared(prepared)
    layout = _layout(layout, report)
    directory = _new_dir(directory, base)
    core = _core()
    try:
        with _RENDER_LOCK:
            fonts = core.Fonts(code=any(r.get("code") for runs in report["inline"].values() for r in runs))
            language = prepared["language"]
            for _, value in core.text_fields(report, language):
                # The upstream strict validator rejects empty fields. Selected mode
                # retains genuinely empty Markdown table cells, with drawn regions.
                if value:
                    core.plain(value, "source text")
                    fonts.markup(value, language)
            pdf = directory / f"report.{language}.pdf"
            core.build_pdf(report, base, language, pdf, fonts, layout=layout)
            with core.fitz.open(pdf) as document:
                page_count = len(document)
            draws = core.build_pdf(report, base, language, pdf, fonts, total_pages=page_count, layout=layout)
            qa = core.check_pdf(report, base, language, pdf, draws, directory / "pages" / language)
            qa["inline_links_checked"] = _check_links(core, report, pdf, draws)
            qa["checks"]["inline_link_regions"] = True
            _check_figure_groups(report, draws)
            qa["checks"]["figure_attributions_bound"] = True
            qa["chart_link_adaptations"] = report.get("chart_link_adaptations", [])
            qa["checks"]["local_chart_links_bound"] = True
            qa.update({"schema": "research-pdf-qa/v1", "status": "awaiting_agent_review", "language": language,
                       "source_digest": prepared["source_digest"], "input_sha256": prepared["input_sha256"],
                       "inventory_sha256": prepared["inventory_sha256"], "font_sources": fonts.paths,
                       "layout": layout, "component_count": len(prepared["components"])})
            for font in fonts.paths.values():
                if core.digest(Path(font["path"])) != font["sha256"]:
                    _error("pdf_font_changed", "A PDF font changed during rendering; retry with stable font files.")
            _verify_prepared(prepared)
            qa_path = directory / "qa.json"
            _json(qa_path, qa)
            return {"pdf_path": str(pdf), "pdf_sha256": core.digest(pdf), "qa_path": str(qa_path), "qa": qa,
                    "pages": qa["page_images"], "language": language, "input_sha256": prepared["input_sha256"],
                    "source_digest": prepared["source_digest"], "component_count": len(prepared["components"])}
    except core.ExportError as exc:
        _error("pdf_render_qa_failed", str(exc))
    except (OSError, ValueError, RuntimeError) as exc:
        if isinstance(exc, PdfExportError):
            raise
        _error("pdf_render_failed", "PDF rendering failed in the private generation; inspect the source assets/fonts and the documented bounded layout controls.")
