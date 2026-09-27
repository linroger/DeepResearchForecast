"""Linear research engine v2 — linear control plane, agentic data plane.

WHY (2026-09-18 post-mortem, condensed)
---------------------------------------
The legacy multi-pass agentic loop burned, on one question, **46.6M prompt
tokens against 2.5M completion tokens (19:1), 1,771 tool calls, 396 billable
searches and 22 full from-zero restarts**. Root causes: (a) every tool
round-trip re-sent the whole growing conversation; (b) pass results lived only
in LangGraph thread memory, so any downstream gate failure forced a full
replay; (c) the fail-closed LLM self-judge never converged; (d) dropped
provider streams deadlocked the sync-async bridge with no timeout.

V1 replaced all of that with a strictly linear stateless pipeline: predictable
(~30 calls, ~0.6M prompt tokens, hard ledger), durable (every phase is a disk
artifact; resume = skip), mechanically QA'd. Its honest weakness: no
mid-flight discovery — the plan was frozen at t=0.

V2 (this file) restores the agentic loop's virtues *inside* the linear
skeleton, so adaptivity no longer costs unbounded context or replay:

* **Agentic plan** — the planner sees a scoped search snapshot before freezing
  the outline.
* **Per-KIQ bounded mini-agents** — each KIQ gets an agent with a small tool
  envelope (web_search / web_fetch, ≤ N steps) that decides what to dig into.
  Its context stays LOCAL (one KIQ, compacted tool results, hard char cap) so
  prompt tokens stay linear in evidence, not quadratic in conversation.
* **Persisted mid-flight memory** — every tool action lands in the KIQ's
  ``memory.jsonl`` immediately. A crashed or resumed agent restarts WITH its
  prior working memory injected ("you already found …") instead of re-paying
  for it. Discoveries (``discoveries.jsonl``) survive the same way.
* **Discovery gap pass** — after round-1 extraction, one bounded review may
  spawn up to K follow-up KIQs (mid-flight discovery, persisted, budgeted),
  extracted by their own mini-agents.
* **5-way parallelism per phase** — ``RESEARCH_LINEAR_WORKERS`` (default 5)
  concurrent mini-agents / synthesis chunks / fetches, behind a global
  model-call semaphore so the provider never sees more streams than it can
  hold (the v0 wedge lesson).
* **Context management** — tool results truncated on injection; conversation
  compacted above a char cap; synthesis sees bounded evidence notes + a source
  index, never raw pages; per-phase token sub-ledgers stop one greedy phase
  from eating the run.
* **Robustness** — bounded retries with backoff on every call, per-phase
  wall-clock deadlines, per-KIQ partial-failure tolerance (>50% of KIQs must
  survive), and a deterministic QA gate with one bounded repair. The LLM judge
  is advisory-only; publication is decided by mechanical gates (or degrades
  honestly with a ``research_qa`` annotation instead of re-burning the budget).

Interface contract with the orchestrator is byte-compatible with the legacy
stage: research_report.md / actors.json / sources.json / timeline.json /
meta.json in ``out_dir``, exit 0 on success.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Optional

import deerflow_research as _dr  # noqa: E402  (deployed next to this file)

_STATE_FILENAME = "state.json"
_LINEAR_DIRNAME = "linear"
_MEMORY_DIRNAME = "memory"

_DEFAULTS = {
    # Cap rationale (v2.1, raised from the defensive v2 calibration): with
    # compaction + per-phase ledgers + disk artifacts in place, each cap below
    # is a *quality* lever whose cost is bounded by the machinery, not a
    # safety valve against runaway spend. glm-5.3's 200K-token window leaves
    # large headroom; what caps buy is per-step token discipline.
    "max_kiqs": 10,
    "plan_searches": 8,             # planner's own exploration budget (agentic scoping)
    "planner_max_steps": 4,         # tool round-trips the planner may use before planning
    "max_searches": 100,            # firecrawl cost governor (disk cache + dedup absorb repeats)
    "max_fetches": 120,
    "fetch_char_cap": 20000,        # stored fetch text (S1 filings run long; 12K cut tables)
    "agent_char_cap": 16000,        # per tool-result injection (compacted away after ~2 steps)
    "conversation_char_cap": 64000, # hard compaction threshold (~20-25K tokens working set)
    "agent_max_steps": 12,          # enough for search→fetch→conflict→primary→verify chains
    "max_followup_kiqs": 5,         # discovery budget per gap round
    "max_gap_rounds": 3,            # adaptive extract→gap iterations ("complete" or budget-out)
    "synth_chunks": 5,
    "synth_context_cap": 64000,     # each writer sees the full evidence corpus
    "workers": 5,
    "model_concurrency": 5,
    "repair_attempts": 2,           # mechanical repair, adopt-on-improvement
    "critique_enabled": 1,          # advisory LLM critique → ONE targeted improvement call
    "budget_prompt_tokens": 4_000_000,
    "phase_deadline_s": 2700,       # per-phase wall clock
}

_LLM_ERROR_MARKERS = (
    "research tool budget exhausted", "content filter", "rate limit",
    "insufficient_quota", "ERROR:", "Traceback (most recent call last)",
)


def _opt(name: str, default: Any) -> Any:
    raw = (os.environ.get(f"RESEARCH_LINEAR_{name.upper()}") or "").strip()
    if not raw:
        return default
    try:
        return type(default)(raw)
    except (TypeError, ValueError):
        return default


class PhaseDeadlineExceeded(RuntimeError):
    pass


class _Deadline:
    """Per-phase wall clock. Checked between LLM calls; never kills mid-call."""

    def __init__(self, seconds: int) -> None:
        self.end = time.monotonic() + max(60, int(seconds))

    def check(self) -> None:
        if time.monotonic() > self.end:
            raise PhaseDeadlineExceeded("phase wall-clock deadline exceeded")


# ---------------------------------------------------------------------------
# Budget / concurrency gateway — every LLM call in the engine goes through it
# ---------------------------------------------------------------------------

class _Gateway:
    """Retries, global semaphore, token ledger, per-phase sub-ledgers."""

    def __init__(self, model, plog) -> None:
        self.model = model
        self.plog = plog
        self.used = 0
        self.calls = 0
        self.cap = max(0, _opt("budget_prompt_tokens", _DEFAULTS["budget_prompt_tokens"]))
        self.sem = threading.Semaphore(
            max(1, _opt("model_concurrency", _DEFAULTS["model_concurrency"])))
        self._lock = threading.Lock()
        self._phase_used = 0
        self._phase_cap = 0

    def open_phase(self, share: float = 0.45) -> None:
        """Ring-fence a share of the remaining budget for the next phase."""
        with self._lock:
            self._phase_used = 0
            self._phase_cap = int(max(0, self.cap - self.used) * min(1.0, max(0.05, share)))

    @staticmethod
    def _prompt_tokens(msg) -> int:
        meta = getattr(msg, "usage_metadata", None) or {}
        if isinstance(meta, dict) and meta.get("input_tokens"):
            return int(meta["input_tokens"])
        rm = getattr(msg, "response_metadata", None) or {}
        tu = rm.get("token_usage") or {}
        if isinstance(tu, dict):
            return int(tu.get("prompt_tokens") or 0)
        return 0

    def invoke(self, messages, label: str, tools: Any = None,
               attempts: int = 3):
        """One model call: semaphore + backoff + ledger. Returns AIMessage."""
        delay = 5.0
        model = self.model.bind_tools(tools) if tools else self.model
        for i in range(1, attempts + 1):
            with self.sem:
                try:
                    msg = model.invoke(messages)
                except Exception as exc:  # noqa: BLE001 — transient transport
                    if i >= attempts:
                        raise
                    self.plog.write(
                        "warn", f"linear:{label}: call {i}/{attempts} failed "
                                f"({type(exc).__name__}) — retry in {delay:.0f}s")
                    time.sleep(delay)
                    delay = min(delay * 3, 60.0)
                    continue
            prompt = self._prompt_tokens(msg)
            with self._lock:
                self.calls += 1
                self.used += prompt
                self._phase_used += prompt
            if self.cap and self.used > self.cap:
                raise RuntimeError(
                    f"linear research prompt-token budget exhausted "
                    f"({self.used} > {self.cap})")
            if self._phase_cap and self._phase_used > self._phase_cap:
                raise RuntimeError(
                    f"linear:{label}: phase token sub-budget exhausted "
                    f"({self._phase_used} > {self._phase_cap})")
            return msg
        raise RuntimeError("unreachable")

    def text(self, messages, label: str, **kw) -> str:
        msg = self.invoke(messages, label, **kw)
        return _dr._message_text(getattr(msg, "content", msg))


# ---------------------------------------------------------------------------
# Durable state
# ---------------------------------------------------------------------------

def _load_state(linear_dir: Path) -> dict:
    try:
        return json.loads((linear_dir / _STATE_FILENAME).read_text("utf-8"))
    except (OSError, ValueError):
        return {"phases": {}}


def _save_state(linear_dir: Path, state: dict) -> None:
    tmp = linear_dir / (_STATE_FILENAME + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), "utf-8")
    tmp.replace(linear_dir / _STATE_FILENAME)


class _PhaseLog:
    def __init__(self, linear_dir: Path, plog) -> None:
        self.linear_dir = linear_dir
        self.plog = plog

    def done(self, state: dict, name: str, detail: str = "") -> None:
        state.setdefault("phases", {})[name] = {
            "status": "done", "at": _dr._utcnow(), "detail": detail[:400]}
        _save_state(self.linear_dir, state)
        self.plog.write("stage", f"linear:{name}: done" + (f" ({detail})" if detail else ""))

    def mark(self, state: dict, name: str, status: str, detail: str = "") -> None:
        state.setdefault("phases", {})[name] = {
            "status": status, "at": _dr._utcnow(), "detail": detail[:400]}
        _save_state(self.linear_dir, state)
        self.plog.write("stage", f"linear:{name}: {status}" + (f" ({detail})" if detail else ""))


def _phase_status(state: dict, name: str) -> Optional[dict]:
    return (state.get("phases") or {}).get(name)


# ---------------------------------------------------------------------------
# JSON / context plumbing
# ---------------------------------------------------------------------------

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.DOTALL)


def _extract_json(text: str):
    text = str(text or "")
    m = _JSON_BLOCK_RE.search(text)
    if m:
        try:
            return json.loads(m.group(1))
        except ValueError:
            pass
    start = None
    for i, ch in enumerate(text):
        if ch in "{[":
            start = i
            break
    if start is not None:
        opener = text[start]
        closer = "}" if opener == "{" else "]"
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except ValueError:
                        return None
    return None


def _call_json(gateway: _Gateway, system: str, user: str, label: str,
               retries: int = 2):
    last_err = ""
    for attempt in range(retries + 1):
        tail = (f"\n\nYour previous reply was not valid JSON ({last_err}). "
                "Reply with ONLY the JSON object." if attempt else "")
        text = gateway.text(_dr._stage1_model_messages(
            system, f"{label} request", user + tail), f"{label}:json{attempt or ''}")
        data = _extract_json(text)
        if data is not None:
            return data
        last_err = (text[:120] or "empty").replace("\n", " ")
        gateway.plog.write("warn", f"linear:{label}: JSON parse retry {attempt + 1}")
    raise RuntimeError(f"linear:{label}: model never returned valid JSON")


def _clip(text: str, cap: int) -> str:
    text = str(text or "").strip()
    return text if len(text) <= cap else text[:cap] + "\n[...truncated...]"


# ---------------------------------------------------------------------------
# Shared source ledger (stable IDs across agents/rounds; durable immediately)
# ---------------------------------------------------------------------------

_TIER1 = (".gov", "iea.org", "ec.europa.eu", "stats.gov.cn", "nea.gov.cn", "miit.gov.cn", "sec.gov")
_TIER2 = ("nvidia.com", "microsoft.com", "google", "amazon.com", "apple.com", "meta.com",
          "alibaba.com", "tencent.com", "baidu.com", "delloro.com", "srgresearch.com",
          "mckinsey.com", "jll.com", "cbre.com", "idc.com", "gartner.com", "trendforce.com")
_TIER3 = ("reuters.com", "bloomberg.com", "ft.com", "wsj.com", "caixin.com",
          "yicai.com", "36kr.com", "ftchinese.com")


def _tier(url: str) -> int:
    u = str(url).lower()
    if any(t in u for t in _TIER1):
        return 1
    if any(t in u for t in _TIER2):
        return 2
    if any(t in u for t in _TIER3):
        return 3
    return 4


class _SourceLedger:
    """Thread-safe, disk-durable registry: stable [S#] ids keyed by URL."""

    def __init__(self, linear_dir: Path, plog) -> None:
        self.path = linear_dir / "source_ledger.json"
        self.plog = plog
        self._lock = threading.Lock()
        try:
            self.rows = json.loads(self.path.read_text("utf-8"))
        except (OSError, ValueError):
            self.rows = []
        self.max_fetches = _opt("max_fetches", _DEFAULTS["max_fetches"])

    def _flush(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.rows, ensure_ascii=False, indent=1), "utf-8")
        tmp.replace(self.path)

    def register(self, url: str, title: str, via: str) -> Optional[dict]:
        url = str(url or "").strip()
        if not url:
            return None
        with self._lock:
            for row in self.rows:
                if row["url"] == url:
                    return row
            fetched = sum(1 for r in self.rows if r.get("fetched"))
            if fetched >= self.max_fetches and via == "fetch":
                self.plog.write("warn", "linear: fetch ledger at cap — not fetching new pages")
                return None
            row = {"id": len(self.rows) + 1, "url": url,
                   "title": str(title or url)[:200], "tier": _tier(url),
                   "via": via, "fetched": False}
            self.rows.append(row)
            self._flush()
            return row

    def mark_fetched(self, sid: int) -> None:
        with self._lock:
            for row in self.rows:
                if row["id"] == sid:
                    row["fetched"] = True
                    break
            self._flush()

    def as_list(self) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self.rows]


# ---------------------------------------------------------------------------
# Mini-agent tool plumbing (search + fetch with injection caps + memory)
# ---------------------------------------------------------------------------

class _KiqMemory:
    """Durable per-KIQ working memory: every tool action is appended at once."""

    def __init__(self, memory_dir: Path, kiq_id: str) -> None:
        memory_dir.mkdir(parents=True, exist_ok=True)
        self.path = memory_dir / f"{kiq_id}.jsonl"
        self._lock = threading.Lock()

    def append(self, kind: str, detail: str) -> None:
        row = {"t": _dr._utcnow(), "kind": kind, "detail": _clip(detail, 400)}
        with self._lock:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    def summary(self, cap: int = 4000) -> str:
        try:
            lines = self.path.read_text("utf-8").splitlines()
        except OSError:
            return ""
        rows = []
        for ln in lines[-60:]:
            try:
                r = json.loads(ln)
                rows.append(f"- [{r['kind']}] {r['detail'][:160]}")
            except ValueError:
                continue
        return _clip("\n".join(rows), cap)


def _run_coroutine_sync(coro):
    """Drive one coroutine to completion from the engine's synchronous code.

    Mini-agents run on plain ThreadPoolExecutor workers and the planner on the
    main thread; none of them owns an event loop, so ``asyncio.run`` is the
    normal path. If a loop is already running on the calling thread, run the
    coroutine on a private thread instead of raising.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _fetch_page_text(url: str) -> str:
    """Fetch one page through the bridge's cached ``web_fetch`` tool.

    ``cached_fetch.web_fetch_tool`` is a LangChain ``StructuredTool`` built by
    ``@tool`` over an ``async def``. It is not callable (langchain-core 1.x has
    no ``BaseTool.__call__``) and has no sync implementation (``.invoke``
    raises NotImplementedError), so ``web_fetch_tool(url)`` always raised and
    every linear-engine fetch failed. Drive it the way the harness and
    ``cached_fetch._jina_delegate_fetch`` do: ``ainvoke`` with a dict input.
    The cache, source policy and shared fetch budget then apply unchanged.
    """
    from cached_fetch import web_fetch_tool
    if web_fetch_tool is None:  # cached_fetch sets None when langchain is absent
        raise RuntimeError("cached_fetch.web_fetch_tool is unavailable")
    return str(_run_coroutine_sync(web_fetch_tool.ainvoke({"url": url})) or "")


def _is_page_text(text: str) -> bool:
    """True only for real page content, not a failure or control result.

    ``web_fetch`` reports failures as text: ``Error: ...`` sentinels, JSON
    envelopes for budget denials, source-policy rejections and repeat fetches,
    and provider error pages. Some of these exceed 200 characters, so a bare
    length check would cite them as fetched sources. Apply the same tests the
    fetch cache (``cached_fetch._is_cacheable``) and the legacy engine's source
    ledger (``_dr._is_dead_fetch``) use.
    """
    from cached_fetch import _is_cacheable
    return _is_cacheable(text) and not _dr._is_dead_fetch(text)


class _AgentTools:
    """The two tools every mini-agent gets. Results are compacted on injection."""

    def __init__(self, ledger: _SourceLedger, searches_left: threading.Semaphore):
        self.ledger = ledger
        self.searches_left = searches_left
        self.search_calls = 0
        self.fetch_calls = 0
        self._lock = threading.Lock()

    def schema(self) -> list[dict]:
        return [
            {"type": "function", "function": {
                "name": "web_search",
                "description": "Search the web. Returns titles, urls and short snippets.",
                "parameters": {"type": "object", "properties": {
                    "query": {"type": "string"}}, "required": ["query"]}}},
            {"type": "function", "function": {
                "name": "web_fetch",
                "description": "Fetch one web page and return its readable text.",
                "parameters": {"type": "object", "properties": {
                    "url": {"type": "string"}}, "required": ["url"]}}},
        ]

    def search(self, query: str) -> str:
        from search_tools import web_search_impl
        with self._lock:
            self.search_calls += 1
        acquired = self.searches_left.acquire(blocking=False)
        if not acquired:
            return '{"error": "search budget for this run is exhausted; work with what you have or finish now"}'
        try:
            raw = web_search_impl(str(query or "").strip(), 5)
            try:
                payload = json.loads(raw)
            except ValueError:
                return '{"error": "search backend unavailable"}'
            rows = payload.get("results") or []
            out = []
            for r in rows:
                row = self.ledger.register(r.get("url"), r.get("title"), "search")
                if row:
                    out.append(f"[S{row['id']}] {row['title']} (tier{row['tier']}) "
                               f"{row['url']} :: {_clip(r.get('content') or '', 280)}")
            return _clip("\n".join(out) or '{"results": []}', 2600) \
                or '{"results": []}'
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"error": f"search failed: {type(exc).__name__}"})

    def fetch(self, url: str) -> str:
        with self._lock:
            self.fetch_calls += 1
        row = self.ledger.register(url, url, "fetch")
        if row is None:
            return '{"error": "fetch ledger at cap; cite the search snippet instead"}'
        if not row.get("fetched"):
            try:
                text = _fetch_page_text(row["url"])
            except Exception as exc:  # noqa: BLE001
                return json.dumps({"error": f"fetch failed: {type(exc).__name__}"})
            if _is_page_text(text):
                row["fetched_text_chars"] = len(text)
                self.ledger.mark_fetched(row["id"])
                return f"[S{row['id']}] {row['title']}\n" + _clip(
                    text, _opt("agent_char_cap", _DEFAULTS["agent_char_cap"]))
            return json.dumps({"error": "page empty or unreadable"})
        return (f'[S{row["id"]}] (already fetched earlier this run) {row["title"]}\n'
                "If you need its content again, rely on your earlier reading of it "
                "recorded in your notes.")


def _compact_messages(messages: list, char_cap: int) -> list:
    """Drop the bodies of the OLDEST tool results once the conversation is fat.

    Keeps head (system+task) and tail (recent exchanges) intact; replaced tool
    payloads point at the durable memory instead. This is what keeps a
    mini-agent's context flat instead of quadratic.
    """
    total = sum(len(str(getattr(m, "content", ""))) for m in messages)
    if total <= char_cap:
        return messages
    tool_idx = [i for i, m in enumerate(messages)
                if getattr(m, "type", "") == "tool" and i > 1]
    for i in tool_idx:
        if total <= char_cap:
            break
        m = messages[i]
        body = str(getattr(m, "content", ""))
        if len(body) > 200:
            total -= len(body) - 60
            try:
                m.content = "[compacted — full result already recorded in your notes]"
            except Exception:  # noqa: BLE001 — immutable message impl
                pass
    return messages


_AGENT_SYSTEM = (
    "You are a scoped evidence investigator for one research question (a KIQ) "
    "inside a larger forecast project. You have exactly two tools: web_search "
    "and web_fetch. Work in a tight loop: search → fetch the 1-3 most "
    "authoritative results → verify the load-bearing numbers against the page "
    "text → search again ONLY for what is still missing. Cite every fact as "
    "[S<id>] using the markers given in tool output. Fetch primary sources "
    "(official filings, regulator/agency, company releases) over commentary. "
    "When you have dense evidence or your tool budget runs out, STOP calling "
    "tools and write your final evidence notes (in the KIQ's language): every "
    "load-bearing fact with number, unit, as-of date, [S<id>] citation; mark "
    "VERIFIED (read on the fetched page) vs REPORTED (snippet only); flag "
    "conflicts instead of averaging. If you discovered an important angle "
    "OUTSIDE your KIQ that the project should pursue, add a final line "
    "'DISCOVERED: <one-sentence new sub-question>'. Do not pad. 500-1000 words."
)


def _run_mini_agent(gateway: _Gateway, tools: _AgentTools, memory: _KiqMemory,
                    kiq: dict, deadline: _Deadline,
                    system: str = _AGENT_SYSTEM) -> str:
    """One bounded, restartable mini-agent. Returns final evidence notes."""
    from langchain_core.messages import HumanMessage, ToolMessage
    kiq_id = str(kiq.get("id"))
    prior = memory.summary()
    opener = (
        f"KIQ {kiq_id}: {kiq.get('question')}\n\n"
        + (f"YOUR PREVIOUS SESSION'S WORKING MEMORY (you already did this — do "
           f"NOT repeat it, build on it):\n{prior}\n\n" if prior else "")
        + "Begin. Call tools until you can write the notes, or write them now "
          "if the memory above already suffices."
    )
    messages: list = _dr._stage1_model_messages(system, f"kiq {kiq_id}", opener)
    max_steps = max(1, _opt("agent_max_steps", _DEFAULTS["agent_max_steps"]))
    char_cap = _opt("conversation_char_cap", _DEFAULTS["conversation_char_cap"])
    last_text = ""
    for step in range(1, max_steps + 1):
        deadline.check()
        msg = gateway.invoke(messages, f"agent:{kiq_id}:{step}",
                             tools=tools.schema())
        calls = list(getattr(msg, "tool_calls", None) or [])
        if not calls:
            last_text = _dr._message_text(getattr(msg, "content", msg))
            break
        messages.append(msg)
        for call in calls:
            name = str(call.get("name") or "")
            args = call.get("args") or {}
            deadline.check()
            if name == "web_search":
                result = tools.search(str(args.get("query") or ""))
                memory.append("search", f"{args.get('query')} → {result[:200]}")
            elif name == "web_fetch":
                result = tools.fetch(str(args.get("url") or ""))
                memory.append("fetch", f"{args.get('url')} → {result[:200]}")
            else:
                result = json.dumps({"error": f"unknown tool {name}"})
            messages.append(ToolMessage(content=result, tool_call_id=str(call.get("id") or "")))
        messages = _compact_messages(messages, char_cap)
    else:
        # Step budget exhausted without a final message: force it now.
        messages.append(HumanMessage(content=(
            "Tool budget exhausted. Produce your FINAL answer now, exactly as "
            "your instructions specify. No more tool calls.")))
        deadline.check()
        msg = gateway.invoke(messages, f"agent:{kiq_id}:final")
        last_text = _dr._message_text(getattr(msg, "content", msg))
    if not last_text.strip():
        raise RuntimeError(f"agent:{kiq_id}: produced no notes")
    memory.append("final", last_text[:400])
    return last_text


def _extract_discoveries(text: str) -> list[str]:
    return [m.group(1).strip() for m in
            re.finditer(r"DISCOVERED:\s*(.+)", text or "")][:5]


# ---------------------------------------------------------------------------
# Phases
# ---------------------------------------------------------------------------

_PLANNER_SYSTEM = (
    "You are the research director for a forecasting dossier. You have the "
    "same two tools as your investigators (web_search, web_fetch) and a small "
    "exploration budget. EXPLORE FIRST: run a few searches, read one or two "
    "anchor pages, and let what you find shape the plan — do not plan blind. "
    "Then STOP calling tools and reply with ONLY the final JSON plan: "
    '{"kiqs":[{"id":"K1","question":"...","queries":["..."]}],'
    '"outline":["Section 1 title"],'
    '"scenario_frame":{"scenarios":[{"name":"...","weight":25,"thesis":"..."}]}} '
    "Rules: at most {max_kiqs} KIQs, each with 2-5 high-signal queries (mix "
    "English and the question's language; name the authoritative sources you "
    "actually saw). The outline must cover what your exploration showed "
    "matters (10-16 sections: executive summary early, market size/segments, "
    "US and China chapters, power/cooling/servers, risks, scenarios, binary "
    "forecasts, References last). scenario_frame: ONE MECE set summing to 100 "
    "— it is restated verbatim everywhere later."
)


def _phase_plan(question: str, gateway: _Gateway, ledger: _SourceLedger,
                memory_dir: Path, plog) -> dict:
    """Agentic planning: the director explores with tools, then freezes the plan.

    v2.1 — replaces the deterministic snapshot-scoped planner. The director's
    tool calls register into the shared source ledger, so pages it anchors on
    are already cited sources when the investigators start.
    """
    tools = _AgentTools(ledger, threading.Semaphore(
        max(1, _opt("plan_searches", _DEFAULTS["plan_searches"]))))
    steps = max(0, _opt("planner_max_steps", _DEFAULTS["planner_max_steps"]))
    raw = ""
    if steps:
        try:
            saved = _DEFAULTS.get("agent_max_steps", 6)
            os.environ["RESEARCH_LINEAR_AGENT_MAX_STEPS"] = str(steps)
            try:
                raw = _run_mini_agent(
                    gateway, tools, _KiqMemory(memory_dir, "PLANNER"),
                    {"id": "PLANNER",
                     "question": f"Scope this forecast question like a research "
                                 f"director: {question}\nExplore with your "
                                 f"tools, then emit the final JSON plan as "
                                 f"instructed."},
                    _Deadline(900))
            finally:
                os.environ["RESEARCH_LINEAR_AGENT_MAX_STEPS"] = str(saved)
        except Exception as exc:  # noqa: BLE001 — exploration is best-effort
            plog.write("warn", f"linear:plan: director exploration failed "
                               f"({type(exc).__name__}); planning without it")
    data = _extract_json(raw) if raw else None
    if data is None:
        data = _call_json(gateway, _PLAN_FALLBACK_SYSTEM.format(
            max_kiqs=_opt("max_kiqs", _DEFAULTS["max_kiqs"])),
            f"FORECAST QUESTION:\n{question}", "plan")
    kiqs = [k for k in (data.get("kiqs") or [])
            if isinstance(k, dict) and k.get("question")][:_opt("max_kiqs", _DEFAULTS["max_kiqs"])]
    outline = [str(s) for s in (data.get("outline") or []) if str(s).strip()]
    scenarios = [s for s in ((data.get("scenario_frame") or {}).get("scenarios") or [])
                 if isinstance(s, dict) and s.get("name") is not None]
    if len(kiqs) < 3 or len(outline) < 8 or not scenarios:
        raise RuntimeError("linear:plan: incomplete plan (kiqs/outline/scenarios)")
    for i, k in enumerate(kiqs, 1):
        k.setdefault("id", f"K{i}")
    return {"kiqs": kiqs, "outline": outline,
            "scenario_frame": {"scenarios": scenarios}}


_PLAN_FALLBACK_SYSTEM = (
    "You are a research planner for a forecasting dossier. Reply with ONLY a "
    "JSON object: "
    '{"kiqs":[{"id":"K1","question":"...","queries":["..."]}],'
    '"outline":["Section 1 title"],'
    '"scenario_frame":{"scenarios":[{"name":"...","weight":25,"thesis":"..."}]}} '
    "10-16 sections; ONE MECE scenario frame summing to 100."
)


def _phase_seed_search(plan: dict, ledger: _SourceLedger,
                       gateway: _Gateway, plog) -> None:
    """Deterministic seed: the planner's queries, cached + throttled."""
    from search_tools import web_search_impl
    seen: set[str] = set()
    queries: list[str] = []
    for k in plan["kiqs"]:
        for q in (k.get("queries") or []):
            n = re.sub(r"\s+", " ", str(q or "").strip().lower())
            if n and n not in seen:
                seen.add(n)
                queries.append(str(q).strip())
    cap = _opt("max_searches", _DEFAULTS["max_searches"])
    queries = queries[:cap]
    done = 0
    for q in queries:
        try:
            raw = web_search_impl(q, 5)
            payload = json.loads(raw)
        except Exception:  # noqa: BLE001
            continue
        for r in (payload.get("results") or []):
            ledger.register(r.get("url"), r.get("title"), "search")
        done += 1
        if done % 10 == 0:
            plog.write("stage", f"linear:seed-search: {done}/{len(queries)}")
    plog.write("ok", f"linear:seed-search: {done} queries → ledger holds "
                      f"{len(ledger.as_list())} candidate sources")


def _extract_round(gateway: _Gateway, ledger: _SourceLedger, memory_dir: Path,
                   kiqs: list[dict], state: dict, phaselog: _PhaseLog,
                   round_name: str, plog) -> dict[str, str]:
    """Run mini-agents over the KIQ set. Per-KIQ durable; >50% must survive."""
    workers = max(1, _opt("workers", _DEFAULTS["workers"]))
    deadline = _Deadline(_opt("phase_deadline_s", _DEFAULTS["phase_deadline_s"]))
    tools = _AgentTools(ledger, threading.Semaphore(
        max(1, _opt("max_searches", _DEFAULTS["max_searches"]))))
    kiq_state = state.setdefault("kiqs", {})
    notes: dict[str, str] = {}
    failures: list[str] = []
    pending = [k for k in kiqs
               if (kiq_state.get(str(k.get("id"))) or {}).get(round_name) != "done"]

    def one(kiq: dict) -> tuple[str, str]:
        return str(kiq.get("id")), _run_mini_agent(gateway, tools, _KiqMemory(
            memory_dir, str(kiq.get("id"))), kiq, deadline)

    if pending:
        with ThreadPoolExecutor(max_workers=min(workers, len(pending))) as ex:
            futs = {ex.submit(one, k): k for k in pending}
            for fut in as_completed(futs):
                kiq = futs[fut]
                kid = str(kiq.get("id"))
                try:
                    kid, text = fut.result()
                    notes[kid] = text
                    kiq_state.setdefault(kid, {})[round_name] = "done"
                    plog.write("ok", f"linear:{round_name}: {kid} → {len(text)} chars "
                                      f"(agent searches={tools.search_calls} fetches={tools.fetch_calls})")
                except Exception as exc:  # noqa: BLE001 — per-KIQ isolation
                    failures.append(kid)
                    kiq_state.setdefault(kid, {})[round_name] = f"failed: {type(exc).__name__}"
                    plog.write("warn", f"linear:{round_name}: {kid} failed "
                                        f"({type(exc).__name__}: {exc})")
                _save_state(memory_dir.parent, state)
    # reload durable notes for KIQs completed in earlier rounds/attempts
    for k in kiqs:
        kid = str(k.get("id"))
        if kid in notes:
            continue
        text_path = memory_dir.parent / "04_evidence" / f"{kid}.md"
        if text_path.is_file():
            notes[kid] = text_path.read_text("utf-8")
    # persist this round's notes
    ev_dir = memory_dir.parent / "04_evidence"
    ev_dir.mkdir(exist_ok=True)
    for kid, text in notes.items():
        (ev_dir / f"{kid}.md").write_text(text, "utf-8")
    if len(failures) > len(kiqs) / 2:
        raise RuntimeError(
            f"linear:{round_name}: {len(failures)}/{len(kiqs)} KIQs failed: {failures}")
    phaselog.done(state, round_name,
                  f"{len(notes)}/{len(kiqs)} KIQs ok, {len(failures)} degraded")
    return notes


_GAP_SYSTEM = (
    "You are a research coverage auditor. You receive a forecast question, "
    "the KIQ list with its evidence notes (possibly degraded), and DISCOVERED "
    "leads the investigators flagged mid-flight. Reply ONLY with JSON: "
    '{"follow_ups":[{"id":"F1","question":"...","queries":["..."]}],'
    '"verdict":"complete"|"gaps"} . Add at most {max_follow} follow-up KIQs — '
    "ONLY for load-bearing angles that are genuinely missing or thin (not "
    "nice-to-have depth). If coverage is sufficient, return an empty list. "
    "Judge like an editor deciding whether the dossier would embarrass us."
)


def _phase_gap(question: str, plan: dict, notes: dict[str, str],
               discoveries: list[str], gateway: _Gateway, plog) -> list[dict]:
    corpus = "\n\n".join(
        f"### {kid}\n{_clip(txt, 2500)}" for kid, txt in sorted(notes.items()))
    disc = "\n".join(f"- {d}" for d in discoveries) or "(none)"
    data = _call_json(gateway, _GAP_SYSTEM.format(
        max_follow=_opt("max_followup_kiqs", _DEFAULTS["max_followup_kiqs"])),
        f"FORECAST QUESTION:\n{question}\n\nKIQ EVIDENCE:\n{_clip(corpus, 26000)}"
        f"\n\nDISCOVERED LEADS:\n{disc}", "gap")
    follow = [f for f in (data.get("follow_ups") or [])
              if isinstance(f, dict) and f.get("question")]
    follow = follow[:_opt("max_followup_kiqs", _DEFAULTS["max_followup_kiqs"])]
    for i, f in enumerate(follow, 1):
        f.setdefault("id", f"F{i}")
        f.setdefault("queries", [])
    plog.write("ok", f"linear:gap: verdict={data.get('verdict')} "
                      f"follow_ups={len(follow)}")
    return follow


_SYNTH_SYSTEM = (
    "You are a senior forecast analyst writing one chunk of a larger report. "
    "You receive the full outline, the canonical SCENARIO FRAME, and the "
    "evidence notes. Write ONLY the sections assigned to this chunk, in the "
    "question's language, MarkDown '## ' headings exactly as the outline "
    "names them. Hard rules: (1) restate scenario names/weights ONLY from the "
    "canonical frame, verbatim — same names, same weights, same count, every "
    "time; (2) every load-bearing number carries [S<id>] citations from the "
    "notes; (3) 400-900 words per section, evidence-dense, no padding; "
    "(4) do not write any other section, any whole-report executive summary, "
    "or any References section (those belong to other chunks)."
)


def _phase_synth(question: str, plan: dict, notes: dict[str, str],
                 ledger: _SourceLedger, gateway: _Gateway, plog) -> str:
    workers = max(1, _opt("workers", _DEFAULTS["workers"]))
    outline = plan["outline"]
    frame = json.dumps(plan["scenario_frame"], ensure_ascii=False)
    corpus = "\n\n".join(f"### {kid}\n{txt}" for kid, txt in sorted(notes.items()))
    ctx = _clip(corpus, _opt("synth_context_cap", _DEFAULTS["synth_context_cap"]))
    n_chunks = max(1, min(_opt("synth_chunks", _DEFAULTS["synth_chunks"]), len(outline)))
    chunks = [outline[i::n_chunks] for i in range(n_chunks)]
    deadline = _Deadline(_opt("phase_deadline_s", _DEFAULTS["phase_deadline_s"]))

    def one(i_sections: tuple[int, list[str]]) -> tuple[int, str]:
        i, sections = i_sections
        deadline.check()
        user = (f"FORECAST QUESTION:\n{question}\n\nFULL OUTLINE:\n"
                + "\n".join(f"- {s}" for s in outline)
                + f"\n\nCANONICAL SCENARIO FRAME (verbatim reuse only):\n{frame}"
                + "\n\nTHIS CHUNK — write exactly these sections:\n"
                + "\n".join(f"- {s}" for s in sections)
                + f"\n\nEVIDENCE NOTES:\n{ctx}")
        text = gateway.text(_dr._stage1_model_messages(
            _SYNTH_SYSTEM, f"synthesis chunk {i + 1}/{n_chunks}", user),
            f"synth:{i + 1}")
        if not text.strip():
            raise RuntimeError(f"linear:synth: chunk {i + 1} empty")
        return i, text.strip()

    parts: dict[int, str] = {}
    with ThreadPoolExecutor(max_workers=min(workers, n_chunks)) as ex:
        futs = [ex.submit(one, (i, secs)) for i, secs in enumerate(chunks)]
        for fut in as_completed(futs):
            i, text = fut.result()
            parts[i] = text
            plog.write("ok", f"linear:synth: chunk {i + 1}/{n_chunks} → {len(text)} chars")
    report = "\n\n".join(parts[i] for i in sorted(parts))
    refs = "\n".join(f"- [S{s['id']}] {s['title']} — {s['url']} (tier S{s['tier']})"
                     for s in ledger.as_list())
    return report + "\n\n## References\n\n" + refs


# ---------------------------------------------------------------------------
# Deterministic QA (+ one bounded repair)
# ---------------------------------------------------------------------------

_PCT_NEAR_RE = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")


def _qa_report(question: str, report: str, plan: dict | None) -> tuple[list[str], list[str]]:
    failures: list[str] = []
    notes: list[str] = []
    words = (_dr.count_prose_words(report) if hasattr(_dr, "count_prose_words")
             else len(re.findall(r"[\w\u4e00-\u9fff]+", report)))
    if words < _opt("min_words", 6000):
        failures.append(f"report too short ({words} prose words)")
    max_words = _opt("max_words", 0) or int(
        os.environ.get("RESEARCH_SYNTHESIS_MAX_WORDS", "36000") or 36000)
    if max_words and words > max_words:
        failures.append(f"report over word ceiling ({words} > {max_words})")
    headings = re.findall(r"^##\s+(.+)$", report, re.MULTILINE)
    if len(headings) < 8:
        failures.append(f"too few sections ({len(headings)} '##' headings)")
    if not any(re.search(r"摘要|Summary|Executive", h, re.IGNORECASE) for h in headings):
        failures.append("no executive-summary section")
    if not any(re.search(r"References|来源|Sources", h, re.IGNORECASE) for h in headings):
        failures.append("no references section")
    for marker in _LLM_ERROR_MARKERS:
        if marker.lower() in report.lower():
            failures.append(f"LLM error marker present: {marker!r}")
            break
    frame_scenarios = ((plan or {}).get("scenario_frame") or {}).get("scenarios") or []
    frame_status = "checked"
    if not frame_scenarios:
        frame_status = ("frame_unavailable (no authoritative plan frame; scenario "
                        "consistency not machine-checked)")
    else:
        for s in frame_scenarios:
            name = str(s.get("name") or "").strip()
            weight = float(s.get("weight") or -1)
            if not name or weight < 0:
                continue
            for m in re.finditer(re.escape(name), report):
                window = report[max(0, m.start() - 60):m.end() + 60]
                pcts = _PCT_NEAR_RE.findall(window)
                if pcts and not any(abs(float(p) - weight) < 0.01 for p in pcts):
                    failures.append(
                        f"scenario '{name}' restated with weight(s) {pcts} ≠ frame weight {weight:g}")
                    break
    if frame_status != "checked":
        notes.append(frame_status)
    seen: set[str] = set()
    out = []
    for f in failures:
        key = f.split("(")[0]
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out[:10], notes


_REPAIR_SYSTEM = (
    "You are a report repair editor. You receive a forecast report and a list "
    "of SPECIFIC mechanical defects found by deterministic QA. Return the "
    "COMPLETE corrected report with exactly those defects fixed and nothing "
    "else changed: same sections, same citations, same language. Make every "
    "scenario restatement use the canonical names, weights and count exactly "
    "as defined in the executive summary. Reply with the full report only."
)


_CRITIQUE_SYSTEM = (
    "You are an advisory reviewer for a forecast dossier. You do NOT decide "
    "publication — deterministic gates do. Name ONLY concrete, actionable "
    "weaknesses: claims lacking citations, numbers without as-of dates, "
    "sections thinner than their evidence, contradictions between sections, "
    "scenario logic gaps. Reply ONLY with JSON: "
    '{"weaknesses":[{"section":"<outline heading>","issue":"...","fix":"..."}]}. '
    "Empty list if the report is sound. Max 6 items, highest-leverage first."
)


def _phase_critique(question: str, report: str, outline: list[str],
                    gateway: _Gateway, plog) -> list[dict]:
    """Advisory LLM critique → concrete fix list. Publication stays mechanical."""
    data = _call_json(gateway, _CRITIQUE_SYSTEM,
                      f"FORECAST QUESTION:\n{question}\n\nOUTLINE:\n"
                      + "\n".join(f"- {s}" for s in outline)
                      + f"\n\nREPORT:\n{_clip(report, 55000)}", "critique")
    weak = [w for w in (data.get("weaknesses") or [])
            if isinstance(w, dict) and w.get("section") and w.get("fix")]
    plog.write("ok", f"linear:critique: {len(weak)} advisory weaknesses")
    return weak[:6]


_TARGETED_FIX_SYSTEM = (
    "You are a surgical report editor. You receive a report and a list of "
    "specific weaknesses from an advisory review. Fix exactly those, touching "
    "the smallest possible surface: patch the named sections, add the missing "
    "citations/dates from the existing evidence, resolve the named "
    "contradictions. Do NOT rewrite untouched sections, do NOT change the "
    "scenario frame, keep every existing [S<id>] citation. Return the COMPLETE "
    "report."
)


def _phase_targeted_fix(report: str, weaknesses: list[dict],
                        gateway: _Gateway, plog) -> str:
    user = ("WEAKNESSES:\n"
            + "\n".join(f"- [{w['section']}] {w['issue']} → fix: {w['fix']}"
                        for w in weaknesses)
            + f"\n\nREPORT:\n{report}")
    return gateway.text(_dr._stage1_model_messages(
        _TARGETED_FIX_SYSTEM, "targeted fix", user), "targeted-fix")


def _phase_qa(question: str, report: str, plan: dict | None,
              gateway: _Gateway, plog) -> tuple[str, list[str], list[str]]:
    failures, notes = _qa_report(question, report, plan)
    attempts = max(0, _opt("repair_attempts", _DEFAULTS["repair_attempts"]))
    for i in range(attempts):
        if not failures:
            break
        plog.write("stage", f"linear:qa: repair {i + 1}/{attempts} — {failures}")
        try:
            fixed = gateway.text(_dr._stage1_model_messages(
                _REPAIR_SYSTEM, "report to repair",
                "DEFECTS:\n" + "\n".join(f"- {f}" for f in failures)
                + f"\n\nREPORT:\n{report}"), "qa-repair")
        except Exception as exc:  # noqa: BLE001 — keep the unrepaired report
            plog.write("warn", f"linear:qa: repair call failed ({type(exc).__name__}); "
                               "shipping unrepaired report")
            break
        if fixed.strip() and not any(m in fixed for m in ("ERROR", "Traceback")):
            new_failures, _ = _qa_report(question, fixed, plan)
            if len(new_failures) < len(failures):
                report, failures = fixed, new_failures
    return report, failures, notes


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def tools_ledger_count(ledger: "_SourceLedger") -> int:
    return len(ledger.as_list())


def run(question: str, out_dir: Path, args, meta: dict, plog,
        write_meta: Callable[[], None]) -> int:
    """Run the v2 engine to completion; returns the process exit code."""
    linear_dir = out_dir / _LINEAR_DIRNAME
    linear_dir.mkdir(parents=True, exist_ok=True)
    memory_dir = linear_dir / _MEMORY_DIRNAME
    state = _load_state(linear_dir)
    phaselog = _PhaseLog(linear_dir, plog)

    mode = (os.environ.get("RESEARCH_LINEAR_MODE", "") or "fresh").strip().lower()
    report_path = out_dir / _dr.REPORT_FILENAME
    min_chars = (_dr._extract_only_min_chars()
                 if hasattr(_dr, "_extract_only_min_chars") else 400)

    from deerflow.models import create_chat_model
    gateway = _Gateway(create_chat_model(args.model, thinking_enabled=False), plog)

    report = ""
    if mode == "salvage" and report_path.is_file() \
            and len(report_path.read_text("utf-8").strip()) >= min_chars:
        report = report_path.read_text("utf-8")
        for name in ("plan", "seed-search", "extract-r1", "gap-r1", "extract-r2",
                     "gap-r2", "extract-r3", "synthesize"):
            phaselog.mark(state, name, "skipped", "salvage mode")
    else:
        if mode == "salvage":
            plog.write("stage", "linear:salvage: no reusable report — fresh run")

        ledger = _SourceLedger(linear_dir, plog)

        if (_phase_status(state, "plan") or {}).get("status") != "done":
            gateway.open_phase(0.10)
            plan = _phase_plan(question, gateway, ledger, memory_dir, plog)
            (linear_dir / "01_plan.json").write_text(
                json.dumps(plan, ensure_ascii=False, indent=2), "utf-8")
            phaselog.done(state, "plan",
                          f"{len(plan['kiqs'])} KIQs, {len(plan['outline'])} sections "
                          f"(director explored {tools_ledger_count(ledger)} sources)")
        plan = json.loads((linear_dir / "01_plan.json").read_text("utf-8"))

        if (_phase_status(state, "seed-search") or {}).get("status") != "done":
            _phase_seed_search(plan, ledger, gateway, plog)
            phaselog.done(state, "seed-search", f"{len(ledger.as_list())} candidates")

        # ---- adaptive extract→gap loop (the agentic heart) -----------------
        # Round 1 mini-agents (5-way parallel, persisted memory), then up to
        # max_gap_rounds of: coverage audit → follow-up KIQs → their own
        # mini-agents. Each round is a durable phase artifact; resume skips
        # completed rounds. The auditor decides when coverage is complete —
        # mid-flight discovery, bounded by budget instead of fear.
        notes: dict[str, str] = {}
        if (_phase_status(state, "extract-r1") or {}).get("status") != "done":
            gateway.open_phase(0.35)
            notes = _extract_round(gateway, ledger, memory_dir, plan["kiqs"],
                                   state, phaselog, "extract-r1", plog)
        else:
            notes = {p.stem: p.read_text("utf-8") for p in
                     sorted((linear_dir / "04_evidence").glob("*.md"))}

        disc_path = linear_dir / "discoveries.jsonl"
        follow: list[dict] = []
        max_rounds = max(1, _opt("max_gap_rounds", _DEFAULTS["max_gap_rounds"]))
        for rnd in range(1, max_rounds + 1):
            r_name = f"gap-r{rnd}"
            if (_phase_status(state, r_name) or {}).get("status") != "done":
                discoveries: list[str] = []
                for text in notes.values():
                    discoveries.extend(_extract_discoveries(text))
                with disc_path.open("a", encoding="utf-8") as fh:
                    for d in discoveries:
                        fh.write(json.dumps({"t": _dr._utcnow(), "round": rnd,
                                             "lead": d}, ensure_ascii=False) + "\n")
                gateway.open_phase(0.05)
                follow = _phase_gap(question, plan, notes, discoveries,
                                    gateway, plog)
                (linear_dir / f"06_followups_r{rnd}.json").write_text(
                    json.dumps(follow, ensure_ascii=False, indent=2), "utf-8")
                phaselog.done(state, r_name, f"{len(follow)} follow-ups")
            else:
                fpath = linear_dir / f"06_followups_r{rnd}.json"
                follow = (json.loads(fpath.read_text("utf-8"))
                          if fpath.is_file() else [])
            if not follow:
                break
            x_name = f"extract-r{rnd + 1}"
            if (_phase_status(state, x_name) or {}).get("status") != "done":
                gateway.open_phase(0.25)
                notes.update(_extract_round(gateway, ledger, memory_dir, follow,
                                            state, phaselog, x_name, plog))
            else:
                for p in sorted((linear_dir / "04_evidence").glob("*.md")):
                    notes.setdefault(p.stem, p.read_text("utf-8"))

        if (_phase_status(state, "synthesize") or {}).get("status") != "done":
            gateway.open_phase(0.20)
            report = _phase_synth(question, plan, notes, ledger, gateway, plog)
            (linear_dir / "05_report.md").write_text(report, "utf-8")
            phaselog.done(state, "synthesize", f"{len(report)} chars")
        else:
            report = (linear_dir / "05_report.md").read_text("utf-8")

    # Publication pipeline: mechanical gates decide; the LLM critiques and
    # patches but can never fail the run by itself (the v0 judge-roulette fix).
    #   1. mechanical QA → bounded repairs (adopt-on-improvement)
    #   2. advisory critique → ONE targeted surgical fix (adopted only if it
    #      does not regress the mechanical gates or the word budget)
    #   3. final mechanical QA → pass, or degrade honestly with annotations
    plan = None
    plan_path = linear_dir / "01_plan.json"
    if plan_path.is_file():
        try:
            plan = json.loads(plan_path.read_text("utf-8"))
        except ValueError:
            plan = None
    gateway.open_phase(0.10)
    final_report, failures, qa_notes = _phase_qa(question, report, plan, gateway, plog)

    if (_opt("critique_enabled", _DEFAULTS["critique_enabled"])
            and final_report.strip()):
        try:
            outline = (plan or {}).get("outline") or []
            weaknesses = _phase_critique(question, final_report, outline,
                                         gateway, plog)
            if weaknesses:
                patched = _phase_targeted_fix(final_report, weaknesses,
                                              gateway, plog)
                if patched.strip() and not any(
                        m in patched for m in ("ERROR", "Traceback")):
                    new_failures, _ = _qa_report(question, patched, plan)
                    if len(new_failures) <= len(failures):
                        final_report = patched
                        failures = new_failures
                        plog.write("ok", "linear:critique: targeted fix adopted")
                    else:
                        plog.write("warn", "linear:critique: targeted fix would "
                                           "regress mechanical gates; kept prior report")
        except Exception as exc:  # noqa: BLE001 — critique is advisory only
            plog.write("warn", f"linear:critique: skipped ({type(exc).__name__}: {exc})")

    (linear_dir / "qa.json").write_text(json.dumps({
        "failures": failures, "notes": qa_notes, "checked_at": _dr._utcnow(),
    }, ensure_ascii=False, indent=2), "utf-8")
    phaselog.mark(state, "qa", "done" if not failures else "degraded",
                  "; ".join(failures) or "all mechanical gates passed")

    _dr._atomic_write_text(report_path, final_report)
    meta.update({
        "research_engine": "linear-v2",
        "linear_mode": mode,
        "research_qa": {"passed": not failures, "failures": failures},
        "report_chars": len(final_report),
        "linear_stats": {"llm_calls": gateway.calls,
                         "prompt_tokens": gateway.used},
        "finished_research_at": _dr._utcnow(),
    })
    write_meta()
    plog.write("ok", f"linear: wrote {report_path.name} ({len(final_report)} chars; "
                     f"llm_calls={gateway.calls}, prompt_tokens={gateway.used})")

    if failures and (os.environ.get("RESEARCH_LINEAR_QA_MODE", "degrade")
                     .strip().lower() == "strict"):
        meta.update(status="failed",
                    error=f"linear QA strict failures: {failures}",
                    finished_at=_dr._utcnow())
        write_meta()
        return 2

    # Structured artifacts for downstream — same primitive the watchdog
    # salvage path uses. NOTE: it closes the shared plog; no plog after this.
    try:
        rc = _dr.run_extract_only(question, out_dir, args, meta, plog, write_meta)
    except Exception as exc:  # noqa: BLE001
        meta.update(status="failed", error=f"structured extraction failed: {exc}",
                    finished_at=_dr._utcnow())
        write_meta()
        return 2
    if rc:
        return rc

    meta.update(status="completed", finished_at=_dr._utcnow())
    write_meta()
    return 0
