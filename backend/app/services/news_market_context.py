"""Read-only, lazy access to sealed contextual evidence from the fixed bridge.

Missing old/off captures are compatible. Present invalid evidence always raises;
readers never acquire sources or search for another generation by graph identity.
"""
from __future__ import annotations

import hashlib
import html
import importlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import threading
from urllib.parse import urlsplit

CONTEXT_FILENAME = "news_market_context.json"
_MAX_BYTES = 2_000_000
_IMPORT_LOCK = threading.RLock()


def _bridge_api():
    bridge = Path(__file__).resolve().parents[3] / "deerflow_bridge"
    with _IMPORT_LOCK:
        if "deerflow_bridge" not in sys.modules:
            spec = importlib.machinery.ModuleSpec("deerflow_bridge", loader=None, is_package=True)
            spec.submodule_search_locations = [str(bridge)]
            sys.modules["deerflow_bridge"] = importlib.util.module_from_spec(spec)
        try:
            module = importlib.import_module("deerflow_bridge.news_signals")
        except (ImportError, OSError) as exc:
            raise ValueError("News context bridge unavailable") from exc
        if Path(module.__file__).resolve() != bridge / "news_signals.py":
            raise ValueError("News context bridge source mismatch")
        return module


def _validated_copy(context):
    """Bound and detach JSON input before it reaches prompts or report storage."""
    if context is None or context == {}:
        return {}
    if not isinstance(context, dict):
        raise ValueError("News context must be an envelope")
    try:
        chunks, size = [], 0
        for chunk in json.JSONEncoder(ensure_ascii=False, sort_keys=True,
                                      separators=(",", ":"), allow_nan=False).iterencode(context):
            size += len(chunk.encode("utf-8"))
            if size > _MAX_BYTES:
                raise ValueError("News context exceeds size limit")
            chunks.append(chunk)
        copied = json.loads("".join(chunks))
    except (TypeError, OverflowError, RecursionError, UnicodeError) as exc:
        raise ValueError("News context is not bounded JSON") from exc
    required = {"schema_version", "generation_id", "question_sha256", "language", "as_of",
                "created_at", "sealed", "providers", "queries", "items", "sha256"}
    if (not required <= copied.keys() or type(copied["schema_version"]) is not int
            or copied["schema_version"] != 1 or copied["sealed"] is not True
            or not isinstance(copied["generation_id"], str) or not copied["generation_id"]
            or not isinstance(copied["language"], str)
            or not isinstance(copied["created_at"], str)
            or copied["as_of"] is not None and not isinstance(copied["as_of"], str)
            or not isinstance(copied["providers"], dict)
            or not isinstance(copied["queries"], list) or len(copied["queries"]) > 32
            or not isinstance(copied["items"], list) or len(copied["items"]) > 120
            or not re.fullmatch(r"[0-9a-f]{64}", str(copied["question_sha256"]))
            or not re.fullmatch(r"[0-9a-f]{64}", str(copied["sha256"]))):
        raise ValueError("News context envelope is invalid or unsealed")
    nested_items = []
    for query in copied["queries"]:
        if (not isinstance(query, dict) or not isinstance(query.get("status"), dict)
                or not isinstance(query["status"].get("attempted"), bool)
                or not isinstance(query.get("items"), list)
                or not re.fullmatch(r"[0-9a-f]{64}", str(query.get("request_id", "")))):
            raise ValueError("News context query is invalid")
        nested_items.extend(query["items"])
    for item in copied["items"] + nested_items:
        if (not isinstance(item, dict)
                or item.get("kind") not in {"news_snippet", "social_post", "market_quote", "community_forecast"}
                or not isinstance(item.get("id"), str) or not item["id"]
                or not isinstance(item.get("provider"), str) or not item["provider"]
                or not item["id"].startswith(item["provider"] + ":")
                or not isinstance(item.get("eligibility"), dict)
                or item["eligibility"].get("context_only") is not True
                or item["eligibility"].get("anchor") is not False
                or item["eligibility"].get("resolution") is not False):
            raise ValueError("News context item is invalid or not context-only")
    digest = copied.pop("sha256")
    canonical = json.dumps(copied, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"), allow_nan=False).encode("utf-8")
    if hashlib.sha256(canonical).hexdigest() != digest:
        raise ValueError("News context digest mismatch")
    copied["sha256"] = digest
    return copied


def load_context(handoff_dir) -> dict:
    """Missing snapshot returns {}; malformed/tampered present proof raises."""
    path = Path(handoff_dir) / CONTEXT_FILENAME
    # lexists distinguishes an absent capture from a broken symbolic link.
    if not os.path.lexists(path):
        return {}
    context = _bridge_api().load_context(handoff_dir, require_sealed=True)
    if not context:
        raise ValueError("Present news context has no valid sealed envelope")
    return _validated_copy(context)


def merge_contexts(input_dirs, output_dir) -> dict:
    """Delegate deterministic sealed-generation merge to its single owner."""
    return _validated_copy(_bridge_api().merge_contexts(input_dirs, output_dir))


def render_context(context, lang="en", max_items=12) -> str:
    """Render stable direct links, preserving the capture's reference namespace.

    A sealed source_ref belongs to its research ledger, not the final report's
    positional S namespace. Do not reuse or rewrite it in report Markdown.
    """
    copied = _validated_copy(context)
    if not copied:
        return ""
    chinese = str(lang).lower().startswith("zh")

    def text(value, limit=300):
        value = html.escape(" ".join(str(value if value is not None else "").split())[:limit], quote=False)
        for char in ("\\", "|", "[", "]", "*", "`"):
            value = value.replace(char, "\\" + char)
        return value

    def link(value):
        if not isinstance(value, str) or len(value) > 4096 or any(ord(char) < 32 for char in value):
            return None
        try:
            parts = urlsplit(value)
            if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
                return None
        except ValueError:
            return None
        return value.replace("(", "%28").replace(")", "%29").replace("<", "%3C").replace(">", "%3E").replace(" ", "%20").replace("|", "%7C").replace("\\", "%5C")

    lines = ["### 新闻与市场背景" if chinese else "### News and market context",
             ("仅供背景参考，不是概率锚点或结算证据。新闻摘要尚未获取全文；发布日期不能证明历史时点可得性。链接直接指向原来源；快照中的引用编号属于原研究账本。" if chinese else
              "Context only; not probability anchors or resolution evidence. News snippets are not fetched full text. Publication dates do not establish historical availability. Links identify original sources directly; stored citation identifiers belong to the original research ledger."),
             "", ("| 提供方／类型／标识 | 来源 | 发布／检索时间 | 状态／原始报价 |" if chinese else
                    "| Provider / kind / identity | Source | Published / retrieved | Status / source quote |"),
             "| --- | --- | --- | --- |"]
    for provider, status in sorted(copied["providers"].items()):
        if isinstance(status, dict):
            state = text(status.get("state") or "unavailable", 40)
            reason = text(status.get("reason"), 120)
            lines.append(f"| {text(provider)} | — | — | {state}{' (' + reason + ')' if reason else ''} |")
    shown = 0
    for item in copied["items"][:max(0, min(12, int(max_items)))]:
        url = link(item.get("url"))
        title = text(item.get("title") or item["id"])
        source = f"[{title}]({url})" if url else title
        basis = "context_only"
        if item["kind"] == "news_snippet" and item.get("snippet"):
            # A headline is not the captured snippet. Keep its bounded content
            # available to writers with the same context-only eligibility.
            snippet = " ".join(str(item["snippet"]).split())
            basis += "; snippet=" + text(snippet, 600)
            if len(snippet) > 600:
                basis += " [摘要已截断]" if chinese else " [snippet truncated]"
        if item["kind"] in {"market_quote", "community_forecast"}:
            details = []
            def stored(name, value, limit=180):
                # Preserve typed zero and null distinctly; no inferred price,
                # probability, timestamp, outcome or community dollar volume.
                details.append(f"{name}={text(value, limit) if value is not None else 'unknown'}")
            # Native names remain visible. Generic aliases, when explicitly
            # supplied by an adapter, are additional values rather than a reason
            # to infer a missing literal-Yes quote or replace a real zero.
            for name in ("yes_bid", "yes_ask", "last_price", "bid", "ask", "last", "probability"):
                if name in item or name in {"yes_bid", "yes_ask", "last_price"}:
                    stored(name, item.get(name))
            stored("price_unit", item.get("price_unit", item.get("units")))
            if "quote_units" in item:
                stored("quote_units", item["quote_units"])
            stored("quote_basis", item.get("quote_basis"))
            stored("probability_basis", item.get("probability_basis"))
            stored("outcome", item.get("outcome"))
            stored("quote_at", item.get("quote_at"))
            stored("rules_primary", item.get("rules_primary"), 1200)
            stored("rules_secondary", item.get("rules_secondary"), 1200)
            for name in ("end_date", "floor_strike", "cap_strike", "strike_type"):
                if name in item:
                    stored(name, item[name])
            for name in ("forecaster_count", "forecasters", "volume", "volume_unit"):
                if name in item:
                    stored(name, item[name])
            basis = "; ".join(details)
        row = f"| {text(item['provider'])} / {text(item['kind'])} / {text(item['id'])} | {source} | {text(item.get('published_at') or 'unknown')} / {text(item.get('retrieved_at') or 'unknown')} | {basis} |"
        if sum(len(line) + 1 for line in lines) + len(row) > 23500:
            break
        lines.append(row)
        shown += 1
    omitted = len(copied["items"]) - shown
    if omitted:
        lines.append(f"\n另有 {omitted} 条记录保留在封存快照中。" if chinese else
                     f"\n{omitted} additional records remain in the sealed capture.")
    return "\n".join(lines)


def load_for_simulation(simulation_id) -> dict | None:
    """Use only the exact consumed generation verified by the official binding."""
    from .official_data import simulation_research_binding
    proof = simulation_research_binding(simulation_id)
    if not isinstance(proof, dict) or proof.get("status") not in {"valid", "missing"}:
        raise ValueError("Simulation research binding is invalid")
    if proof["status"] == "missing":
        return None
    if not isinstance(proof.get("handoff_dir"), str) or not proof["handoff_dir"]:
        raise ValueError("Simulation research binding has no handoff")
    context = load_context(proof["handoff_dir"])
    if simulation_research_binding(simulation_id) != proof:
        raise ValueError("Simulation research binding changed during context read")
    return context or None
