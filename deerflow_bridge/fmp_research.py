"""Immutable, question-bound FMP MCP research captures; no provider I/O on read.

The MCP client owns transport, schema validation and redaction. This module owns
the sanitized envelope the model consumed. Financial data remains vendor
evidence, separate from official statistical observations and simulation truth.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import time
from contextlib import contextmanager

ENDPOINT = "https://financialmodelingprep.com/mcp"
TOOL_NAMES = ("fmp_search_tools", "fmp_call")
GUIDANCE = (
    "FMP MCP RESEARCH: For company, industry financials, securities or market questions, "
    "prioritize the discovered FMP financial-data AND relevant news tools before web fallback. "
    "Use fmp_search_tools(query) to inspect actual official names and inputSchema, then "
    "fmp_call(tool, arguments) with those exact names and schema-valid arguments (arguments is a JSON object string). "
    "Grouped tools require an endpoint enum selector: also supply the fields marked required for that "
    "selected endpoint in its discovered description. Never invent aliases or arbitrary endpoint URLs. "
    "Match company/ticker/exchange, fiscal period, currency, units and filing/publication/quote dates; "
    "separate reported values from estimates and forecasts. FMP is vendor evidence, not official_data "
    "observations, resolution evidence, anchors or simulation truth. News snippets require web_fetch "
    "of the original publisher page before factual claims. Cite the stored response and retain its "
    "retrieval time and limitations. Missing/forbidden data is a coverage gap, never zero. "
    "On resume and during synthesis use captured evidence only; do not refresh providers."
)
SCHEMAS = [
    {"type": "function", "function": {"name": "fmp_search_tools",
     "description": "Discover official FMP MCP tool names and schemas for financial data or news.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}},
                    "required": ["query"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "fmp_call",
     "description": "Call a discovered official FMP tool; capture its response as citable vendor evidence.",
     "parameters": {"type": "object", "properties": {"tool": {"type": "string"},
                    "arguments": {"type": "string", "description": "JSON object matching discovered inputSchema"}},
                    "required": ["tool", "arguments"], "additionalProperties": False}}},
]


class CaptureIntegrityError(ValueError):
    """A stored generation cannot be proven to match its original consumer."""


def client_api():
    return importlib.import_module(f"{__package__}.fmp_mcp" if __package__ else "fmp_mcp")


def configured(env=None):
    return client_api().configured(env)


def relevant(text):
    return bool(re.search(r"\b(company|companies|stock|equity|earnings|revenue|profit|margin|"
                         r"valuation|financial|finance|market|industry|sector|investment|investor|"
                         r"balance sheet|cash flow|dividend|ticker|nasdaq|nyse|ipo|bond|commodity|"
                         r"capex|semiconductor|semiconductors|nvidia|apple|microsoft|tesla|amazon|"
                         r"alphabet|tsmc|asml|samsung|hyperscaler|hyperscalers)\b"
                         r"|\b(?:forecast|outlook|value|price)\s+(?-i:[A-Z]{1,5})\b"
                         r"|公司|财务|营收|利润|估值|股票|股价|证券|金融|市场|行业|产业|投资|上市", str(text), re.I))


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(encoded(value).encode("utf-8")).hexdigest()


def question_digest(question):
    return hashlib.sha256(" ".join(question.split()).encode("utf-8")).hexdigest()


def sensitive_input(value, secret=""):
    if isinstance(value, dict):
        return any(re.fullmatch(r"api[-_]?key|access[-_]?token|token|secret|password|authorization|credentials?",
                                str(key), re.I) or sensitive_input(child, secret) for key, child in value.items())
    if isinstance(value, list):
        return any(sensitive_input(child, secret) for child in value)
    return isinstance(value, str) and (bool(secret and secret in value)
                                      or bool(re.search(r"(?i)[?&](api[-_]?key|token|secret|password)=", value)))


def discovery_projection(response, *, max_chars=14000, max_tools=8):
    """Whole schemas only, with an explicit omission count; never slice JSON."""
    result = {key: response.get(key) for key in ("provider", "source_url", "status", "retrieved_at")}
    result["tools"] = []
    tools = response.get("tools") or []
    for tool in tools:
        if len(result["tools"]) >= max_tools:
            break
        candidate = {**result, "tools": result["tools"] + [tool]}
        if len(encoded(candidate)) <= max_chars - 150:
            result = candidate
    result["omitted_tools"] = max(0, len(tools) - len(result["tools"]))
    if result["omitted_tools"]:
        result["note"] = "Narrow fmp_search_tools query for omitted tools or large schemas. Full response is captured."
    return encoded(result)


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".fmp-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(encoded(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class CaptureStore:
    """One writer per run; each admitted request is captured once, including errors.

    The separate binding detects a deleted/replaced manifest. Consumers may bind
    ``proof`` into their checkpoint as well. Replay never constructs a client.
    """
    def __init__(self, root, question, *, env=None, replay=False, client=None, expected=None):
        if Path(root).is_symlink():
            raise CaptureIntegrityError("fmp_capture_corrupt: unsafe capture root")
        self.root = Path(root).resolve()
        self.directory = self.root / "fmp"
        self.path = self.directory / "captures.json"
        self.binding = self.root / "fmp_research_binding.json"
        self.question_sha256 = question_digest(question) if question is not None else ""
        self.env = dict(os.environ if env is None else env)
        self.client = client
        self.replay = replay
        self.frozen = replay
        self.lock = threading.RLock()
        if question is None:
            self.question_sha256 = self._read(self.path).get("question_sha256")
            if not isinstance(self.question_sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", self.question_sha256):
                raise CaptureIntegrityError("fmp_capture_corrupt: missing question identity")
        self.data = {"schema": "fmp-research/v1", "question_sha256": self.question_sha256,
                     "source_url": ENDPOINT, "captures": {}}
        if self.path.exists() or self.binding.exists() or expected:
            self.validate(expected=expected)
        elif not replay:
            self._save()

    def _read(self, path):
        if path.is_symlink() or not path.resolve().is_relative_to(self.root):
            raise CaptureIntegrityError("fmp_capture_corrupt: unsafe capture path")
        try:
            return json.loads(path.read_text("utf-8"))
        except (OSError, ValueError):
            raise CaptureIntegrityError("fmp_capture_corrupt: missing or invalid capture") from None

    def proof(self):
        return {"schema": "fmp-research-binding/v1", "question_sha256": self.question_sha256,
                "sha256": digest(self.data)}

    def _save(self):
        if self.directory.is_symlink() or not self.directory.resolve().is_relative_to(self.root):
            raise CaptureIntegrityError("fmp_capture_corrupt: unsafe capture directory")
        _write(self.path, self.data)
        _write(self.binding, self.proof())

    def validate(self, *, expected=None):
        with self.lock:
            data = self._read(self.path)
            if (not isinstance(data, dict) or data.get("schema") != "fmp-research/v1"
                    or data.get("question_sha256") != self.question_sha256
                    or data.get("source_url") != ENDPOINT or not isinstance(data.get("captures"), dict)):
                raise CaptureIntegrityError("fmp_capture_corrupt: question or source identity changed")
            proof = {"schema": "fmp-research-binding/v1", "question_sha256": self.question_sha256,
                     "sha256": digest(data)}
            if self._read(self.binding) != proof or (expected is not None and expected != proof):
                raise CaptureIntegrityError("fmp_capture_corrupt: bound manifest changed")
            for key, item in data["captures"].items():
                if (not isinstance(item, dict) or item.get("request_sha256") != digest(item.get("request"))
                        or key != digest({"request": item.get("request"), "response_sha256": item.get("sha256")})):
                    raise CaptureIntegrityError("fmp_capture_corrupt: request changed")
                if item.get("file") != f"fmp/{key}.json":
                    raise CaptureIntegrityError("fmp_capture_corrupt: file identity changed")
                if (item.get("capture_id") != key or item.get("url") != ENDPOINT + "?drf_fmp_capture=" + key
                        or item["request"].get("question_sha256") not in
                        [self.question_sha256, *data.get("source_questions", [])]
                        or item["request"].get("source_url") != ENDPOINT):
                    raise CaptureIntegrityError("fmp_capture_corrupt: capture identity changed")
                response = self._read(self.root / item["file"])
                if (digest(response) != item.get("sha256") or response.get("provider") != "fmp"
                        or response.get("source_url") != ENDPOINT):
                    raise CaptureIntegrityError("fmp_capture_corrupt: response changed")
            self.data = data
            return proof

    def freeze(self):
        self.frozen = True  # Signal-safe admission close; in-flight captures may finish.

    def close(self):
        self.freeze()
        if self.client is not None:
            self.client.close()

    @contextmanager
    def admission(self, deadline):
        """Lock waiting consumes the caller's deadline, before any provider work."""
        if deadline is None:
            deadline = time.monotonic() + 20.0
        remaining = max(0.0, deadline - time.monotonic())
        acquired = remaining > 0 and self.lock.acquire(timeout=remaining)
        try:
            yield acquired
        finally:
            if acquired:
                self.lock.release()

    def request(self, operation, payload, *, deadline=None, reserve=lambda: True):
        with self.admission(deadline) as admitted:
            if not admitted:
                return self.failure("timeout", "research_deadline_exhausted"), None
            if sensitive_input(payload, str(self.env.get("FMP_API_KEY") or "")):
                return self.failure("invalid_input", "sensitive_request_rejected"), None
            request = {"operation": operation, "payload": payload,
                       "question_sha256": self.question_sha256, "source_url": ENDPOINT}
            request_key = digest(request)
            if self.path.exists() or self.binding.exists():
                self.validate()
            elif self.data["captures"]:
                raise CaptureIntegrityError("fmp_capture_corrupt: manifest disappeared")
            matches = [item for item in self.data["captures"].values() if item["request_sha256"] == request_key]
            if len(matches) > 1:
                return self.failure("disabled", "multiple_captures_use_source_identity"), None
            if matches:
                item = matches[0]
                return self._read(self.root / item["file"]), dict(item)
            if self.frozen:
                return self.failure("disabled", "stored_only"), None
            if deadline is not None and deadline <= time.monotonic():
                return self.failure("timeout", "research_deadline_exhausted"), None
            if not reserve():
                return self.failure("disabled", "research_budget_exhausted"), None
            if self.client is None:
                self.client = client_api().FmpMcpClient(env=self.env)
            # Request metadata can itself contain credentials; persist only the
            # sanitized copy, never repr(exception) or raw tool arguments.
            safe_request = self.client.sanitize(request)
            if safe_request != request:
                return self.failure("invalid_input", "sensitive_request_rejected"), None
            response = (self.client.discover(payload["query"], deadline=deadline) if operation == "discover"
                        else self.client.call(payload["tool"], payload["arguments"], deadline=deadline))
            if (not isinstance(response, dict) or response.get("provider") != "fmp"
                    or response.get("source_url") != ENDPOINT):
                return self.failure("unavailable", "invalid_provider_envelope"), None
            # Exact sanitized response, with no excerpting or normalization of data.
            text = encoded(response)
            key = digest({"request": request, "response_sha256": digest(response)})
            path = self.directory / f"{key}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                raise CaptureIntegrityError("fmp_capture_corrupt: unbound response already exists")
            with path.open("x", encoding="utf-8") as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            item = {"request": request, "request_sha256": request_key,
                    "file": f"fmp/{key}.json", "sha256": digest(response),
                    "capture_id": key, "retrieved_at": response.get("retrieved_at"),
                    "url": ENDPOINT + "?drf_fmp_capture=" + key}
            if operation == "call":
                descriptions = [tool.get("description", "") for _, discovery in self.captures()
                                for tool in discovery.get("tools", []) if tool.get("name") == payload["tool"]]
                item["kind"] = ("news_snippet" if re.search(r"news|press.?release|headline|article",
                                                           payload["tool"] + " " + " ".join(descriptions), re.I)
                                else "financial_data")
            self.data["captures"][key] = item
            self._save()
            return response, dict(item)

    @staticmethod
    def failure(state, reason):
        return {"provider": "fmp", "source_url": ENDPOINT, "status": {"state": state, "reason": reason}}

    def captures(self):
        if self.path.exists() or self.binding.exists():
            self.validate()
        return [(dict(item), self._read(self.root / item["file"]))
                for item in self.data["captures"].values()]


def metadata(item):
    news = item.get("kind") == "news_snippet"
    return {"provider": "fmp", "source_origin": "fmp_news_snippet" if news else "fmp_vendor",
            "kind": item.get("kind", "financial_data"), "fmp_capture": item,
            "source_url": ENDPOINT, "capture_path": item["file"], "capture_sha256": item["sha256"],
            "citation_basis": "captured MCP response; correlation URL is not a public article",
            "response_captured": True, "publisher_fetched": False,
            "retrieved_at": item.get("retrieved_at"),
            "eligibility": {"vendor_evidence": True, "context_only": news, "official_data": False,
                            "anchor": False, "resolution": False, "simulation_truth": False}}


def capture_artifacts(root):
    """Validated bytes for parent promotion/binding; never contacts a provider."""
    root = Path(root)
    present = any((root / name).exists() for name in ("fmp", "fmp_research_binding.json"))
    sources = root / "sources.json"
    if not present and sources.exists():
        try:
            present = any(isinstance(row, dict) and row.get("fmp_capture")
                          for row in json.loads(sources.read_text("utf-8")))
        except (ValueError, OSError, TypeError):
            pass
    if not present:
        return {}
    store = CaptureStore(root, None, env={}, replay=True)
    store.validate()
    names = ["fmp/captures.json", "fmp_research_binding.json"]
    names += [item["file"] for item in store.data["captures"].values()]
    result = {name: (store.root / name).read_bytes() for name in names}
    store.validate()
    return result


def merge_captures(directories, destination, question):
    """Merge validated lane responses without changing their request identities."""
    stores = []
    for root in directories:
        if capture_artifacts(root):
            stores.append(CaptureStore(root, None, env={}, replay=True))
    if not stores:
        return None
    destination = Path(destination)
    merged = {"schema": "fmp-research/v1", "question_sha256": question_digest(question),
              "source_url": ENDPOINT, "captures": {}, "source_questions": [], "origins": []}
    for store in stores:
        merged["source_questions"].extend([store.question_sha256, *store.data.get("source_questions", [])])
        merged["origins"].append(store.proof())
        for key, item in store.data["captures"].items():
            if key in merged["captures"] and merged["captures"][key] != item:
                raise CaptureIntegrityError("fmp_capture_corrupt: conflicting lane capture")
            merged["captures"][key] = item
    merged["source_questions"] = sorted(set(merged["source_questions"]))
    if (destination / "fmp/captures.json").exists() or (destination / "fmp_research_binding.json").exists():
        result = CaptureStore(destination, question, env={}, replay=True)
        if result.data != merged:
            raise CaptureIntegrityError("fmp_capture_corrupt: merged generation replacement")
        return result
    result = CaptureStore(destination, question, env={}, replay=True)
    if result.directory.is_symlink() or not result.directory.resolve().is_relative_to(result.root):
        raise CaptureIntegrityError("fmp_capture_corrupt: unsafe merge directory")
    result.directory.mkdir(parents=True, exist_ok=True)
    for store in stores:
        for item in store.data["captures"].values():
            target = result.root / item["file"]
            raw = (store.root / item["file"]).read_bytes()
            if target.exists():
                if target.is_symlink() or target.read_bytes() != raw:
                    raise CaptureIntegrityError("fmp_capture_corrupt: merged payload replacement")
            else:
                with target.open("xb") as stream:
                    stream.write(raw)
    result.data = merged
    result._save()
    result.validate()
    return result
