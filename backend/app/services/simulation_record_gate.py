"""Deterministic gate for the Simulation After-Action Record (ADR 0003; design §3.2).

``audit_record(sim_dir, record)`` checks a ``simulation-record/v1`` record for
*fidelity to the simulation's own artifacts* — it cannot check truth — and writes
``simulation_record_audit.json`` with ``{sha256, hard_issues, warnings,
publication_status}``.  A record is served by the API and linked from the report
only when the audit exists and passed (``simulation_record_contract.is_published``).
The gate never blocks report publication and never raises on bad input.

Checks (hard unless stated):

* shape — :func:`simulation_record_contract.validate_shape` problems.
* G1 — exactly one period per committed round of the artifacts; none missing, none extra.
* G2 — every numeric and date token in the record traces to an artifact value (after
  rounding to the rendered precision; percent tokens are matched against ratios), to a
  structural count (round indices, list lengths, commitment status counts) or to the
  path-spread statistics recomputed from ``world_paths.json``; final shares match the
  trajectory within the rendered precision.
* G3 — structured actor fields (moves, held positions, offers, red lines, alliances,
  track records) and every declared entity are in the artifact allowlist (cast names
  and aliases, variable names, scenario names, period labels); undeclared capitalised
  multi-word tokens in authored prose are *warnings* in this version (soft launch).
* G4 — every ``ref`` resolves to an artifact row; a move's actor and public statement
  match the referenced action row; the narrative is the stored arbiter narrative;
  every quoted statement in authored prose is a substring of a stored public
  statement (or an exact declared entity / period label); every synthesis paragraph
  has at least one resolving ref (its ``claims`` entry, else the periods whose label
  it names).
* G5 — no ``[S#]`` / ``【S#】`` citation marker anywhere; no evidence verbs in authored prose.
* G6 — no ``private_rationale`` text from any ``world_actions.jsonl`` row (the gate
  reads those rows only to compare; the text never enters the record or the audit).
* G7 — banner byte-exact; ``health`` agrees with ``run_summary.json`` and the
  trajectory's validity verdict.
* G8 — "probability" / 「概率」 is never applied to shares; share keys are scenario names.
* G9 — language purity of authored prose for the record's language
  (``report_lint.detect_language_contamination``); contamination inside a verbatim
  arbiter narrative is a warning.

Input contract: only files inside ``sim_dir`` are opened (regular files, symlinks
refused); nothing is imported from the report or research planes except the lint's
language scan.  The compiler (``simulation_record.py``) imports this module; this module
never imports the compiler.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from . import simulation_record_contract as rc

AUDIT_SCHEMA = "simulation-record-audit/v1"
GATE_VERSION = "simulation_record_gate/1.0"

# Record keys whose values are identifiers, provenance pointers or structure, never
# reader-facing numbers.  They are excluded from the numeric scan (G2) and from the
# full-text scans (G5/G6 still see every string value).
_NUMERIC_EXEMPT_KEYS = frozenset({
    "ref", "refs", "id", "path", "file", "round", "schema", "record_class", "epistemic_status",
    "simulation_id", "pipeline_id", "config_hash", "generated_at", "generator_version", "banner",
    "sha256", "agent_id", "rounds_planned", "rounds_committed", "synthesis_dropped", "generator",
    "paragraph", "stub", "mechanical_only", "mechanical_only_rounds", "kind", "status", "previous",
    "provenance", "agency_class", "k",
})
_ARTIFACT_FILES = (
    "world_state.json", "world_state_history.jsonl", "world_digest.jsonl", "world_actions.jsonl",
    "decisions.jsonl", "world_state_trajectory.json", "world_paths.json", "run_summary.json",
    "simulation_config.json", "actor_cast_manifest.json", "state.json", "world_result.json",
    "world_spec.json",
)

_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}|\d{4}-W\d{2}|\d{4}-Q[1-4]|\d{4}-H[12]|\d{4}-\d{2}(?!\d)")
_NUM_RE = re.compile(r"(?<![\w.])[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?%?|(?<![\w.,])[-+]?\d+(?:\.\d+)?%?")
_CITATION_RE = re.compile(r"\[S\d+|【S\d+")
_EVIDENCE_VERB_RE = re.compile(
    r"\b(?:the\s+)?evidence\s+(?:shows|indicates|suggests|demonstrates|confirms)\b|证据(?:表明|显示|证明|说明)",
    re.IGNORECASE)
_PROBABILITY_RE = re.compile(r"\bprobabilit(?:y|ies)\b|概率", re.IGNORECASE)
_QUOTE_RE = re.compile(r"“([^”\n]{8,})”|「([^」\n]{6,})」|\"([^\"\n]{12,})\"")
_CAP_TOKEN_RE = re.compile(
    r"\b[A-Z][\w'’\-]*(?:\s+(?:of|the|and|for|de|la|du|von|van|al)\s+)?(?:\s+[A-Z][\w'’\-]*)+")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。！？;；])\s*")
_MIN_PRIVATE_FRAGMENT = 24
_SHARE_TOLERANCE = Decimal("0.0005")


# ── small helpers ───────────────────────────────────────────────────────────────────────

def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def record_bytes(record: Dict[str, Any]) -> bytes:
    """Canonical bytes of ``simulation_record.json`` (shared with the writer so the
    audit's SHA-256 is the file's SHA-256)."""
    return (json.dumps(record, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def record_sha256(record: Dict[str, Any]) -> str:
    return hashlib.sha256(record_bytes(record)).hexdigest()


def _as_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _decimal(value: Any) -> Optional[Decimal]:
    try:
        if isinstance(value, bool) or value is None:
            return None
        if isinstance(value, int):
            return Decimal(value)
        if isinstance(value, float):
            if value != value or value in (float("inf"), float("-inf")):
                return None
            return Decimal(repr(value))
        return Decimal(str(value).replace(",", "").rstrip("%"))
    except (InvalidOperation, ValueError):
        return None


def _strip_ellipsis(text: str) -> str:
    return str(text or "").strip().rstrip("…").rstrip(".").strip()


def _walk_strings(value: Any, *, skip_keys: Iterable[str] = ()) -> Iterable[str]:
    skip = set(skip_keys)
    if isinstance(value, dict):
        for key, item in value.items():
            if key in skip:
                continue
            yield from _walk_strings(item, skip_keys=skip)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_strings(item, skip_keys=skip)
    elif isinstance(value, str):
        yield value


def _walk_numbers(value: Any, *, skip_keys: Iterable[str] = ()) -> Iterable[Decimal]:
    skip = set(skip_keys)
    if isinstance(value, dict):
        for key, item in value.items():
            if key in skip:
                continue
            yield from _walk_numbers(item, skip_keys=skip)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_numbers(item, skip_keys=skip)
    elif _is_number(value):
        dec = _decimal(value)
        if dec is not None:
            yield dec


def _tokens(text: str) -> Tuple[List[str], List[Tuple[Decimal, bool, int]]]:
    """(date tokens, numeric tokens) of a text; numeric tokens as (value, is_percent, decimals)."""
    text = str(text or "")
    dates = _DATE_RE.findall(text)
    rest = _DATE_RE.sub(" ", text)
    numbers: List[Tuple[Decimal, bool, int]] = []
    for raw in _NUM_RE.findall(rest):
        pct = raw.endswith("%")
        body = raw.rstrip("%").replace(",", "")
        dec = _decimal(body)
        if dec is None:
            continue
        decimals = len(body.split(".")[1]) if "." in body else 0
        numbers.append((dec, pct, decimals))
    return dates, numbers


def _quantize(value: Decimal, decimals: int) -> Decimal:
    try:
        return value.quantize(Decimal(1).scaleb(-decimals))
    except InvalidOperation:
        return value


# ── artifact sources (sim_dir only) ─────────────────────────────────────────────────────

class _Sources:
    """The simulation directory's artifacts as the gate sees them: public views only,
    plus the private-rationale texts kept apart for the G6 comparison."""

    def __init__(self, sim_dir: str) -> None:
        self.ok = bool(sim_dir) and os.path.isdir(sim_dir)
        self.dir = os.path.realpath(sim_dir) if self.ok else ""
        self.run_summary = self._json("run_summary.json")
        self.world_state = self._json("world_state.json")
        self.trajectory = self._json("world_state_trajectory.json")
        self.world_paths = self._json("world_paths.json")
        self.cast_manifest = self._json("actor_cast_manifest.json")
        self.state = self._json("state.json")
        self.world_result = self._json("world_result.json")
        self.world_spec = self._json("world_spec.json")
        config = self._json("simulation_config.json")
        self.temporal = config.get("temporal_config") if isinstance(config.get("temporal_config"), dict) else {}
        self.world_seed = config.get("world_state_seed") if isinstance(config.get("world_state_seed"), dict) else {}
        self.history = self._jsonl("world_state_history.jsonl")
        self.digest = self._jsonl("world_digest.jsonl")
        self.actions: List[Dict[str, Any]] = []
        self.private_texts: List[Tuple[str, str]] = []   # (private_rationale, public text of the same row)
        for row in self._jsonl("world_actions.jsonl"):
            public = {k: row[k] for k in rc.ACTION_PUBLIC_FIELDS if k in row}
            self.actions.append(public)
            private = str(row.get("private_rationale") or "").strip()
            if private:
                self.private_texts.append((private, json.dumps(public, ensure_ascii=False)))

    def path(self, name: str) -> Optional[str]:
        if not self.ok:
            return None
        candidate = os.path.join(self.dir, name)
        try:
            if os.path.commonpath([os.path.realpath(candidate), self.dir]) != self.dir:
                return None
        except ValueError:
            return None
        if os.path.islink(candidate) or not os.path.isfile(candidate):
            return None
        return candidate

    def exists(self, name: str) -> bool:
        return self.path(name) is not None

    def _json(self, name: str) -> Dict[str, Any]:
        path = self.path(name)
        if path is None:
            return {}
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _jsonl(self, name: str) -> List[Dict[str, Any]]:
        path = self.path(name)
        if path is None:
            return []
        rows: List[Dict[str, Any]] = []
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(row, dict):
                        rows.append(row)
        except OSError:
            return []
        return rows

    # ── derived views ──
    @property
    def world(self) -> Dict[str, Any]:
        world = self.world_state.get("world")
        return world if isinstance(world, dict) else {}

    @property
    def summary(self) -> Dict[str, Any]:
        summary = self.world_state.get("summary")
        return summary if isinstance(summary, dict) else {}

    def history_by_round(self) -> Dict[int, Dict[str, Any]]:
        out: Dict[int, Dict[str, Any]] = {}
        for row in self.history:
            rnd = _as_int(row.get("round"))
            if rnd is None or rnd <= 0 or row.get("scenario_round_status") not in (None, "committed"):
                continue
            out[rnd] = row
        return out

    def digest_by_round(self) -> Dict[int, Dict[str, Any]]:
        out: Dict[int, Dict[str, Any]] = {}
        for row in self.digest:
            rnd = _as_int(row.get("round"))
            if rnd is not None and rnd > 0:
                out[rnd] = row
        return out

    def committed_rounds(self, engine: str) -> List[int]:
        if engine == "world-v1":
            committed = _as_int(self.world_result.get("committedRound")) or 0
            return list(range(1, committed + 1))
        if engine == "oasis-reflexive":
            return sorted(self.history_by_round())
        return sorted(self.digest_by_round())

    def action(self, rnd: int, agent_id: Any) -> Optional[Dict[str, Any]]:
        for row in self.actions:
            if _as_int(row.get("round")) == rnd and str(row.get("agent_id")) == str(agent_id):
                return row
        return None

    def actions_in_round(self, rnd: int) -> List[Dict[str, Any]]:
        return [row for row in self.actions if _as_int(row.get("round")) == rnd]

    def variables(self) -> Dict[str, Dict[str, Any]]:
        return {str(v.get("id")): v for v in (self.world.get("variables") or []) if isinstance(v, dict)}

    def interactions(self) -> Dict[str, Dict[str, Any]]:
        return {str(i.get("id")): i for i in (self.world.get("interactions") or []) if isinstance(i, dict)}

    def events_by_round(self) -> Dict[int, List[Dict[str, Any]]]:
        out: Dict[int, List[Dict[str, Any]]] = {}
        for event in self.world.get("events") or []:
            if isinstance(event, dict) and _as_int(event.get("round")) is not None:
                out.setdefault(int(event["round"]), []).append(event)
        return out

    def world_v1_names(self) -> Dict[str, str]:
        names: Dict[str, str] = {}
        for actor in self.world_spec.get("actors") or []:
            if isinstance(actor, dict) and actor.get("actorId"):
                names[str(actor["actorId"])] = str(actor.get("name") or actor["actorId"])
        return names

    def allowlist(self) -> Set[str]:
        """Cast names and aliases, variable names and ids, scenario names, period labels."""
        names: Set[str] = set()

        def add(value: Any) -> None:
            text = str(value or "").strip()
            if text:
                names.add(text)

        for actor in self.world.get("actors") or []:
            if isinstance(actor, dict):
                add(actor.get("name"))
                for alias in actor.get("aliases") or []:
                    add(alias)
        for decision in self.cast_manifest.get("decisions") or []:
            if isinstance(decision, dict):
                add(decision.get("actor_name"))
        for name in self.cast_manifest.get("selected_actor_names") or []:
            add(name)
        for row in self.actions:
            add(row.get("actor_name"))
            for target in row.get("targets") if isinstance(row.get("targets"), list) else []:
                add(target)
        for agent in self.run_summary.get("top_agents") or []:
            if isinstance(agent, dict):
                add(agent.get("agent_name"))
        for var in self.world.get("variables") or []:
            if isinstance(var, dict):
                add(var.get("name"))
                add(var.get("id"))
        for scenario in (self.world.get("scenarios") or self.trajectory.get("scenarios")
                         or self.world_seed.get("scenarios") or []):
            add(scenario)
        for shock in self.world.get("shocks") or []:
            if isinstance(shock, dict):
                add(shock.get("event"))
                add(shock.get("name"))
                add(shock.get("id"))
        for row in self.history:
            add(row.get("period_label"))
            period = row.get("period") if isinstance(row.get("period"), dict) else {}
            add(period.get("label"))
            add(period.get("period_end"))
        for label in (self.world.get("period_labels") or {}).values() if isinstance(self.world.get("period_labels"), dict) else []:
            add(label)
        for row in self.digest:
            add(row.get("period_end"))
        for name in self.world_v1_names().values():
            add(name)
        for row in self.world_result.get("trajectory") or []:
            if isinstance(row, dict):
                add(str(row.get("simulatedAt") or "")[:10])
        for period in self.world_spec.get("periods") or []:
            if isinstance(period, dict):
                add(str(period.get("end") or "")[:10])
        for bucket in ("metrics", "rules"):
            world = self.world_result.get("world") if isinstance(self.world_result.get("world"), dict) else {}
            values = world.get(bucket) if isinstance(world.get(bucket), dict) else {}
            for key in values:
                add(key)
        return names

    def public_statements(self) -> List[str]:
        out: List[str] = []
        for row in self.actions:
            text = str(row.get("public_statement") or "").strip()
            if text:
                out.append(text)
        for event in self.world.get("events") or []:
            if isinstance(event, dict) and event.get("statement"):
                out.append(str(event["statement"]))
        for inter in self.interactions().values():
            for key in ("terms", "response"):
                if inter.get(key):
                    out.append(str(inter[key]))
        return out

    def public_corpus(self) -> Dict[str, Any]:
        """Everything the gate may count as an artifact value: public views only."""
        return {
            "run_summary": self.run_summary, "world_state": self.world_state, "trajectory": self.trajectory,
            "world_paths": self.world_paths, "cast_manifest": self.cast_manifest, "temporal": self.temporal,
            "world_seed": self.world_seed, "history": self.history, "digest": self.digest,
            "actions": self.actions, "world_result": self.world_result, "world_spec": self.world_spec,
        }


# ── numeric universe (G2) ───────────────────────────────────────────────────────────────

class _Universe:
    def __init__(self, src: _Sources, record: Dict[str, Any]) -> None:
        self.numbers: Set[Decimal] = set()
        self.dates: Set[str] = set()
        corpus = src.public_corpus()
        for dec in _walk_numbers(corpus):
            self._add(dec)
        for text in _walk_strings(corpus):
            dates, numbers = _tokens(text)
            self.dates.update(dates)
            for dec, _pct, _decimals in numbers:
                self._add(dec)
        for date in list(self.dates):
            year = _decimal(date[:4])
            if year is not None:
                self.numbers.add(year)
        # path-spread statistics are a deterministic function of world_paths.json
        paths = src.world_paths.get("paths") if isinstance(src.world_paths.get("paths"), list) else []
        if paths:
            try:
                from .world_paths import share_distribution
                scenarios = src.world.get("scenarios") or src.trajectory.get("scenarios") or []
                per_path = [p.get("shares") for p in paths if isinstance(p, dict) and isinstance(p.get("shares"), dict)]
                for dec in _walk_numbers(share_distribution(per_path, list(scenarios))):
                    self._add(dec)
            except Exception:  # noqa: BLE001 — the universe is only ever smaller for it
                pass
        # structural counts: round indices, list lengths, commitment status counts
        planned = _as_int(record.get("rounds_planned")) or 0
        committed = _as_int(record.get("rounds_committed")) or 0
        for n in range(0, max(planned, committed, len(src.history), len(src.digest)) + 2):
            self.numbers.add(Decimal(n))
        for length in self._list_lengths(record):
            self.numbers.add(Decimal(length))
        for actor in src.world.get("actors") or []:
            if not isinstance(actor, dict):
                continue
            counts: Dict[str, int] = {}
            for commitment in actor.get("commitments") or []:
                if isinstance(commitment, dict):
                    status = str(commitment.get("status") or "")
                    counts[status] = counts.get(status, 0) + 1
            for value in counts.values():
                self.numbers.add(Decimal(value))
            self.numbers.add(Decimal(len([c for c in actor.get("commitments") or [] if isinstance(c, dict)])))
        self.ratios = {x for x in self.numbers if Decimal(0) <= x <= Decimal(1)}

    @staticmethod
    def _list_lengths(value: Any) -> Iterable[int]:
        if isinstance(value, dict):
            for item in value.values():
                yield from _Universe._list_lengths(item)
        elif isinstance(value, list):
            yield len(value)
            for item in value:
                yield from _Universe._list_lengths(item)

    def _add(self, dec: Decimal) -> None:
        self.numbers.add(dec)
        for decimals in range(0, 5):
            self.numbers.add(_quantize(dec, decimals))

    def has_number(self, dec: Decimal, *, percent: bool, decimals: int) -> bool:
        if dec in self.numbers:
            return True
        if percent:
            for ratio in self.ratios:
                if _quantize(ratio * 100, decimals) == dec:
                    return True
        return False

    def has_date(self, token: str) -> bool:
        return token in self.dates


# ── reference resolution (G4) ───────────────────────────────────────────────────────────

_PATH_RE = re.compile(r"world\.(\w+)\[([^\]]+)\](?:\.history\[round=(\d+)\])?")


def _resolve_ref(ref: Any, src: _Sources, engine: str, committed: Sequence[int]) -> Optional[str]:
    """None when the ref resolves, else the reason it does not."""
    if not isinstance(ref, dict):
        return "ref is not an object"
    file = str(ref.get("file") or "")
    if file not in _ARTIFACT_FILES:
        return f"unknown artifact file {file!r}"
    if not src.exists(file):
        return f"artifact {file} is absent"
    rnd = _as_int(ref.get("round"))
    ident = str(ref.get("id") or "")
    path = str(ref.get("path") or "")
    if rnd is not None and rnd != 0 and rnd not in committed:
        return f"round {rnd} is not committed"
    if file == "world_state_history.jsonl":
        if rnd is None or rnd not in src.history_by_round():
            return f"no committed history row for round {rnd}"
        if ident and ident not in (f"round:{rnd}", f"h{rnd}"):
            return f"unknown history id {ident!r}"
        return None
    if file == "world_digest.jsonl":
        if rnd is None or rnd not in src.digest_by_round():
            return f"no digest row for round {rnd}"
        return None
    if file == "world_actions.jsonl":
        match = re.fullmatch(r"agent:(.+)", ident) or re.fullmatch(r"a(\d+)_(.+)", ident)
        if not match:
            return f"unknown action id {ident!r}"
        agent = match.group(match.lastindex or 1)
        if match.lastindex == 2 and _as_int(match.group(1)) != rnd:
            return f"action id {ident!r} names another round"
        if rnd is None or src.action(rnd, agent) is None:
            return f"no action row for agent {agent} in round {rnd}"
        return None
    if file == "world_state.json":
        if path:
            match = _PATH_RE.fullmatch(path)
            if not match:
                return f"unknown world_state path {path!r}"
            section, key, hist_round = match.group(1), match.group(2), match.group(3)
            items = src.world.get(section)
            if not isinstance(items, list):
                return f"world.{section} is absent"
            found = None
            if key.isdigit() and int(key) < len(items):
                found = items[int(key)]
            else:
                for item in items:
                    if isinstance(item, dict) and str(item.get("id")) == key:
                        found = item
                        break
            if found is None:
                return f"world.{section}[{key}] not found"
            if hist_round is not None:
                history = found.get("history") if isinstance(found, dict) else None
                if not any(isinstance(h, dict) and _as_int(h.get("round")) == int(hist_round) for h in history or []):
                    return f"{path}: no history entry for round {hist_round}"
            return None
        if ident.startswith("var:"):
            return None if ident[4:] in src.variables() else f"variable {ident[4:]!r} not found"
        if ident.startswith("interaction:"):
            return None if ident[12:] in src.interactions() else f"interaction {ident[12:]!r} not found"
        match = re.fullmatch(r"event:(\d+):(\d+)", ident)
        if match:
            events = src.events_by_round().get(int(match.group(1)), [])
            return None if int(match.group(2)) < len(events) else f"event {ident!r} not found"
        if ident in ("", f"round:{rnd}", "seed", "summary"):
            return None if src.world_state else "world_state.json is empty"
        return f"unknown world_state id {ident!r}"
    if file == "world_state_trajectory.json":
        return None if src.trajectory else "trajectory is empty"
    if file == "run_summary.json":
        return None if src.run_summary else "run_summary is empty"
    if file == "world_paths.json":
        return None if src.world_paths else "world_paths is empty"
    if file in ("world_result.json", "world_spec.json"):
        result = src.world_result
        if not result:
            return "world_result is empty"
        if ident in ("", f"round:{rnd}"):
            return None
        for bucket in ("metrics", "rules"):
            if ident.startswith(bucket + ":"):
                key = ident[len(bucket) + 1:]
                for row in result.get("trajectory") or []:
                    values = row.get(bucket) if isinstance(row, dict) and isinstance(row.get(bucket), dict) else {}
                    if key in values:
                        return None
                return f"{ident!r} not found in the world-v1 trajectory"
        for event in result.get("events") or []:
            if isinstance(event, dict) and str(event.get("eventId")) == ident:
                return None
        world = result.get("world") if isinstance(result.get("world"), dict) else {}
        for section in ("interactions", "commitments"):
            values = world.get(section) if isinstance(world.get(section), dict) else {}
            if ident in values:
                return None
        return f"unknown world-v1 id {ident!r}"
    if file in ("simulation_config.json", "actor_cast_manifest.json", "state.json", "decisions.jsonl"):
        return None
    return f"unresolvable ref {ref!r}"


# ── the audit ───────────────────────────────────────────────────────────────────────────

def _authored_prose(record: Dict[str, Any]) -> List[str]:
    """Text the compiler or the synthesis wrote (as opposed to verbatim artifact text)."""
    out: List[str] = []
    overall = record.get("overall") if isinstance(record.get("overall"), dict) else {}
    synthesis = overall.get("synthesis") if isinstance(overall.get("synthesis"), dict) else {}
    if synthesis.get("text"):
        out.append(str(synthesis["text"]))
    for tp in overall.get("turning_points") or []:
        if isinstance(tp, dict) and tp.get("why"):
            out.append(str(tp["why"]))
    limits = record.get("limits") if isinstance(record.get("limits"), dict) else {}
    for note in limits.get("notes") or []:
        out.append(str(note))
    return out


def _narratives(record: Dict[str, Any]) -> List[str]:
    return [str(p.get("narrative")) for p in record.get("periods") or []
            if isinstance(p, dict) and p.get("narrative")]


def _share_keys(record: Dict[str, Any]) -> List[str]:
    overall = record.get("overall") if isinstance(record.get("overall"), dict) else {}
    shares = overall.get("shares") if isinstance(overall.get("shares"), dict) else {}
    final = shares.get("final") if isinstance(shares.get("final"), dict) else {}
    return [str(k) for k in final]


def audit_record(sim_dir: str, record: Any, *, write: bool = True) -> Dict[str, Any]:
    """Audit ``record`` against the artifacts in ``sim_dir``; write the audit file when
    ``write`` is true.  Never raises; a record that is not an object fails closed."""
    hard: List[str] = []
    warnings: List[str] = []
    checks: Dict[str, int] = {}

    def fail(code: str, text: str) -> None:
        hard.append(f"{code}: {text}")
        checks[code] = checks.get(code, 0) + 1

    def warn(code: str, text: str) -> None:
        warnings.append(f"{code}: {text}")

    try:
        _audit(sim_dir, record, fail, warn)
    except Exception as exc:  # noqa: BLE001 — a gate crash is a failed audit, never a pipeline failure
        fail("gate", f"audit crashed: {type(exc).__name__}: {str(exc)[:200]}")

    # bounded, deterministic order
    hard = sorted(set(hard))[:200]
    warnings = sorted(set(warnings))[:200]
    sha = record_sha256(record) if isinstance(record, dict) else hashlib.sha256(b"").hexdigest()
    if write and isinstance(record, dict):
        on_disk = rc.record_paths(sim_dir)["json"]
        try:
            if os.path.isfile(on_disk) and not os.path.islink(on_disk):
                with open(on_disk, "rb") as fh:
                    disk_sha = hashlib.sha256(fh.read()).hexdigest()
                if disk_sha != sha:
                    hard.append("G7: the written simulation_record.json differs from the audited record")
        except OSError:
            pass
    audit = {
        "schema": AUDIT_SCHEMA,
        "gate_version": GATE_VERSION,
        "simulation_id": str(record.get("simulation_id") or "") if isinstance(record, dict) else "",
        "sha256": sha,
        "hard_issues": hard,
        "warnings": warnings,
        "publication_status": "passed" if not hard else "failed",
        "checks": checks,
        "audited_at": _utcnow(),
    }
    if write:
        try:
            _atomic_write(rc.record_paths(sim_dir)["audit"],
                          (json.dumps(audit, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        except OSError:
            pass
    return audit


def _atomic_write(path: str, data: bytes) -> None:
    tmp = f"{path}.tmp-{os.getpid()}"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)


def _audit(sim_dir: str, record: Any, fail, warn) -> None:  # noqa: C901 — one check per block, kept flat on purpose
    for problem in rc.validate_shape(record):
        fail("shape", problem)
    if not isinstance(record, dict):
        return
    src = _Sources(sim_dir)
    if not src.ok:
        fail("G1", f"simulation directory is not readable: {sim_dir!r}")
        return
    engine = str(record.get("engine") or "")
    lang = "zh" if str(record.get("language") or "").lower().startswith("zh") else "en"
    periods = [p for p in (record.get("periods") or []) if isinstance(p, dict)] if isinstance(record.get("periods"), list) else []
    overall = record.get("overall") if isinstance(record.get("overall"), dict) else {}

    # ── G1: one period per committed round ──
    committed = src.committed_rounds(engine)
    record_rounds = [_as_int(p.get("round")) for p in periods]
    missing = [r for r in committed if r not in record_rounds]
    extra = [r for r in record_rounds if r not in committed]
    if missing:
        fail("G1", f"committed rounds without a period section: {missing}")
    if extra:
        fail("G1", f"period sections for rounds that were not committed: {extra}")
    if len(record_rounds) != len(set(record_rounds)):
        fail("G1", "duplicate period sections")

    # ── G2: numeric and date fidelity ──
    universe = _Universe(src, record)
    scan = {k: v for k, v in record.items() if k not in ("banner",)}
    for dec in _walk_numbers(scan, skip_keys=_NUMERIC_EXEMPT_KEYS):
        if not universe.has_number(dec, percent=False, decimals=0):
            fail("G2", f"numeric value {dec} does not trace to any artifact row")
    for text in _walk_strings(scan, skip_keys=_NUMERIC_EXEMPT_KEYS):
        dates, numbers = _tokens(text)
        for date in dates:
            if not universe.has_date(date):
                fail("G2", f"date token {date!r} does not trace to any artifact row")
        for dec, pct, decimals in numbers:
            if not universe.has_number(dec, percent=pct, decimals=decimals):
                fail("G2", f"numeric token {'%s%%' % dec if pct else dec} does not trace to any artifact row")
    shares = overall.get("shares") if isinstance(overall.get("shares"), dict) else {}
    final = shares.get("final") if isinstance(shares.get("final"), dict) else {}
    if final:
        outcome = src.trajectory.get("outcome") if isinstance(src.trajectory.get("outcome"), dict) else {}
        stored = outcome.get("shares") if isinstance(outcome.get("shares"), dict) else src.world.get("scenario_shares")
        if not isinstance(stored, dict) or not stored:
            fail("G2", "the record carries final shares but the trajectory stores none")
        else:
            for name, value in final.items():
                mine, theirs = _decimal(value), _decimal(stored.get(name))
                if theirs is None:
                    fail("G2", f"share for {name!r} has no counterpart in the trajectory")
                elif mine is None or abs(mine - theirs) > _SHARE_TOLERANCE:
                    fail("G2", f"share for {name!r} ({value}) differs from the trajectory ({stored.get(name)})")

    # ── G3: entity allowlist ──
    allow = src.allowlist()
    declared = [str(e) for e in (record.get("entities_declared") or []) if isinstance(e, str)]
    for entity in declared:
        if entity not in allow:
            fail("G3", f"declared entity {entity!r} is not in the artifact allowlist")
    declared_set = set(declared) | allow

    def check_actor(value: Any, where: str) -> None:
        text = str(value or "").strip()
        if text and text not in declared_set:
            fail("G3", f"{where}: actor {text!r} is not in the cast allowlist")

    for p in periods:
        for move in p.get("moves") or []:
            if isinstance(move, dict):
                check_actor(move.get("actor"), f"round {p.get('round')} move")
                for target in move.get("targets") if isinstance(move.get("targets"), list) else []:
                    if str(target).strip() and str(target).strip() not in declared_set:
                        warn("G3", f"round {p.get('round')} move target {target!r} is not a declared entity")
        for held in p.get("held_position") or []:
            check_actor(held, f"round {p.get('round')} held position")
        for offer in p.get("offers") or []:
            if isinstance(offer, dict):
                for key in ("from_actor", "to_actor", "from", "to"):
                    if offer.get(key):
                        for name in str(offer[key]).split(", "):
                            check_actor(name, f"round {p.get('round')} offer {key}")
        for crossed in p.get("red_lines_crossed") or []:
            if isinstance(crossed, dict):
                check_actor(crossed.get("actor"), f"round {p.get('round')} red line")
                check_actor(crossed.get("by"), f"round {p.get('round')} red line crossed by")
        for shift in p.get("alliances") or []:
            if isinstance(shift, dict):
                for key in ("actor", "source", "target"):
                    check_actor(shift.get(key), f"round {p.get('round')} alliance {key}")
    for track in overall.get("track_records") or []:
        if isinstance(track, dict):
            check_actor(track.get("actor"), "track record")
    for text in _authored_prose(record):
        for token in _CAP_TOKEN_RE.findall(text):
            token = token.strip()
            if token in declared_set or any(token in e or e in token for e in declared_set if len(e) > 3):
                continue
            warn("G3", f"undeclared capitalised token {token!r} in authored prose")

    # ── G4: refs, statements, narratives, synthesis paragraphs ──
    def check_ref(ref: Any, where: str) -> bool:
        reason = _resolve_ref(ref, src, engine, committed)
        if reason:
            fail("G4", f"{where}: ref does not resolve ({reason})")
            return False
        return True

    history = src.history_by_round()
    for p in periods:
        rnd = _as_int(p.get("round"))
        refs = p.get("refs") if isinstance(p.get("refs"), list) else []
        if not refs:
            fail("G4", f"round {rnd}: period carries no ref")
        for ref in refs:
            check_ref(ref, f"round {rnd} period")
        narrative = str(p.get("narrative") or "").strip()
        if narrative and engine == "oasis-reflexive":
            stored = str((history.get(rnd) or {}).get("narrative") or "")
            if _strip_ellipsis(narrative) not in stored:
                fail("G4", f"round {rnd}: narrative is not the stored arbiter narrative")
        if narrative and engine != "oasis-reflexive":
            fail("G4", f"round {rnd}: engine {engine} records no arbiter narrative")
        for move in p.get("moves") or []:
            if not isinstance(move, dict):
                continue
            ref = move.get("ref")
            if ref is None:
                fail("G4", f"round {rnd}: move by {move.get('actor')!r} carries no ref")
                continue
            if not check_ref(ref, f"round {rnd} move"):
                continue
            match = re.fullmatch(r"agent:(.+)", str(ref.get("id") or "")) or re.fullmatch(r"a\d+_(.+)", str(ref.get("id") or ""))
            row = src.action(rnd, match.group(1)) if match and rnd is not None else None
            if row is None:
                continue
            if str(row.get("actor_name") or "") != str(move.get("actor") or ""):
                fail("G4", f"round {rnd}: move actor {move.get('actor')!r} differs from the referenced action row")
            statement = _strip_ellipsis(str(move.get("public_statement") or ""))
            if statement and statement not in str(row.get("public_statement") or ""):
                fail("G4", f"round {rnd}: public statement of {move.get('actor')!r} is not a substring of the stored public_statement")
        for fact in p.get("facts_changed") or []:
            if isinstance(fact, dict) and fact.get("ref") is not None:
                check_ref(fact["ref"], f"round {rnd} fact {fact.get('variable')!r}")
        for event in p.get("events") or []:
            if isinstance(event, dict) and event.get("ref") is not None:
                check_ref(event["ref"], f"round {rnd} event")
        for offer in p.get("offers") or []:
            if isinstance(offer, dict) and offer.get("ref") is not None:
                check_ref(offer["ref"], f"round {rnd} offer")
    for tp in overall.get("turning_points") or []:
        if isinstance(tp, dict) and tp.get("ref") is not None:
            check_ref(tp["ref"], f"turning point round {tp.get('round')}")
    statements = src.public_statements()
    entity_quotes = declared_set | {str(p.get("label") or "") for p in periods}
    for text in _authored_prose(record):
        for match in _QUOTE_RE.finditer(text):
            quoted = next(g for g in match.groups() if g is not None).strip()
            if quoted in entity_quotes:
                continue
            if not any(_strip_ellipsis(quoted) in s for s in statements):
                fail("G4", f"quoted statement is not a substring of any stored public_statement: {quoted[:60]!r}")
    synthesis = overall.get("synthesis") if isinstance(overall.get("synthesis"), dict) else {}
    text = str(synthesis.get("text") or "").strip()
    if text:
        paragraphs = [para.strip() for para in re.split(r"\n\s*\n", text) if para.strip()]
        claims = synthesis.get("claims") if isinstance(synthesis.get("claims"), list) else []
        by_paragraph: Dict[int, List[Any]] = {}
        for claim in claims:
            if isinstance(claim, dict) and isinstance(claim.get("refs"), list):
                idx = _as_int(claim.get("paragraph"))
                if idx is not None:
                    by_paragraph.setdefault(idx, []).extend(claim["refs"])
        labels = {str(p.get("label") or ""): p for p in periods if p.get("label")}
        for i, para in enumerate(paragraphs):
            refs = by_paragraph.get(i) or [r for label, p in labels.items() if label in para
                                             for r in (p.get("refs") if isinstance(p.get("refs"), list) else [])]
            if not refs:
                limits = record.get("limits") if isinstance(record.get("limits"), dict) else {}
                if limits.get("stub") and i == 0:
                    continue   # the health-stub sentence refers to the run as a whole
                fail("G4", f"synthesis paragraph {i + 1} carries no ref and names no period label")
                continue
            if not any(_resolve_ref(r, src, engine, committed) is None for r in refs):
                fail("G4", f"synthesis paragraph {i + 1}: none of its refs resolve")

    # ── G5: citation markers and evidence verbs ──
    for text in _walk_strings(record):
        if _CITATION_RE.search(text):
            fail("G5", f"citation marker in record text: {text[:60]!r}")
    for text in _authored_prose(record):
        if _EVIDENCE_VERB_RE.search(text):
            fail("G5", f"evidence verb applied to simulated content: {text[:60]!r}")

    # ── G6: private rationale ──
    blob = "\n".join(_walk_strings(record))
    for private, public in src.private_texts:
        fragments = [private] + [f.strip() for f in _SENTENCE_SPLIT_RE.split(private) if len(f.strip()) >= _MIN_PRIVATE_FRAGMENT]
        for fragment in fragments:
            if fragment and fragment in blob and fragment not in public:
                fail("G6", "private_rationale text appears in the record")
                break

    # ── G7: banner and health ──
    if record.get("banner") != rc.banner_for(lang):
        fail("G7", "banner is not byte-exact")
    health = record.get("health") if isinstance(record.get("health"), dict) else {}
    stored_health = str(src.run_summary.get("simulation_health") or "").strip()
    if src.run_summary and stored_health and str(health.get("simulation_health")) != stored_health:
        fail("G7", f"health {health.get('simulation_health')!r} differs from run_summary ({stored_health!r})")
    stored_validity = src.trajectory.get("validity") if isinstance(src.trajectory.get("validity"), str) else None
    if stored_validity and engine != "world-v1" and str(health.get("validity")) != stored_validity:
        fail("G7", f"validity {health.get('validity')!r} differs from the trajectory ({stored_validity!r})")
    stored_failed = _as_int(src.summary.get("arbiter_failed_rounds"))
    if stored_failed is not None and _as_int(health.get("arbiter_failed_rounds")) not in (None, stored_failed):
        warn("G7", f"arbiter_failed_rounds {health.get('arbiter_failed_rounds')} differs from the world summary ({stored_failed})")

    # ── G8: shares are shares ──
    for text in _authored_prose(record):
        if _PROBABILITY_RE.search(text):
            fail("G8", f"'probability' applied to simulated content: {text[:60]!r}")
    for text in _walk_strings(shares):
        if _PROBABILITY_RE.search(text):
            fail("G8", f"'probability' inside the shares block: {text[:60]!r}")

    def keys_of(value: Any) -> Iterable[str]:
        if isinstance(value, dict):
            for key, item in value.items():
                yield str(key)
                yield from keys_of(item)
        elif isinstance(value, list):
            for item in value:
                yield from keys_of(item)

    for key in keys_of(shares):
        if _PROBABILITY_RE.search(key):
            fail("G8", f"share key named {key!r}")
    scenarios = {str(s) for s in (src.world.get("scenarios") or src.trajectory.get("scenarios")
                                  or src.world_seed.get("scenarios") or [])}
    for name in _share_keys(record):
        if scenarios and name not in scenarios:
            fail("G8", f"share key {name!r} is not a scenario of the run")
    for p in periods:
        if "shares" in p or "scenario_shares" in p:
            fail("G8", f"round {p.get('round')}: period section carries scenario shares")

    # ── G9: language purity ──
    # Hard for text the compiler or the synthesis wrote; the arbiter narratives are verbatim
    # artifact text the record cannot change, so contamination there is reported as a warning.
    try:
        from .report_lint import detect_language_contamination
        authored = "\n".join(_authored_prose(record))
        if authored.strip():
            found = detect_language_contamination(authored, lang)
            if found.get("lines"):
                fail("G9", f"{found['lines']} authored line(s) in the other language; e.g. {found.get('samples', [''])[0]!r}")
        narratives = "\n".join(_narratives(record))
        if narratives.strip():
            found = detect_language_contamination(narratives, lang)
            if found.get("lines"):
                warn("G9", f"{found['lines']} arbiter narrative line(s) in the other language")
    except ImportError:
        warn("G9", "report_lint unavailable; language purity not checked")
