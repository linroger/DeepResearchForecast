"""Reflexive world-model kernel for the calendar simulation (design §2.3).

The simulation used to carry one piece of inter-round state: a probability
distribution over the forecast scenarios (``worldstate.WorldState``).  Agents
never observed a concrete world, so nothing they did had consequences they could
see.  This module is the pure, serialisable world that the round loop now
evolves and shows to every agent:

* ``StateVariable`` — named facts with a value, unit, kind, provenance and a
  bounded causal history (who/what changed it, in which round).
* ``ActorState`` — per-actor capacity, posture, documented plans, red lines,
  pending commitments and the last structured move.
* ``Relationship`` — valenced edges (allies, rivals, regulators, suppliers…)
  whose polarity drifts with coalition and antagonistic moves.
* ``PendingEffect`` — delayed consequences resolved with a seeded RNG when due.
* ``WorldEvent`` — the per-round record of actions, scheduled events,
  consequences, emergent events and resolutions.

Kernel invariants (design §2.3):

* I-1 agent-facing text never carries scenario shares; the scenario
  distribution is mirrored here for the record only and is never rendered.
* I-2 every variable change carries a cause; arbiter changes are clamped to a
  fraction of the current magnitude per round (``max_change_ratio``).
* I-3 unknown outcome power stays unknown; capacity comes from the agency
  class, never from visibility.
* I-4 no LLM, no I/O, no ``Config`` access.  Randomness is injected.
"""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from typing import Any, Dict, Iterable, List, Optional, Tuple

WORLD_MODEL_STATE_VERSION = "world-model-state/v1"

VARIABLE_KINDS = ("numeric", "categorical", "boolean", "text")
# Type names a model may echo into a variable's ``unit`` field ("yes boolean",
# "2027-03-10 date").  A unit belongs to numeric facts only, and a kind name is never a
# unit: such units are blanked at validation, in the kernel and by ``format_value``.
_KIND_NAME_UNITS = frozenset(VARIABLE_KINDS) | frozenset((
    "number", "num", "int", "integer", "float", "decimal", "bool", "flag", "string", "str",
    "category", "enum", "date", "datetime", "timestamp",
))
PROVENANCES = ("research", "official", "seed", "arbiter", "effect", "action")
VALENCES = ("allied", "adversarial", "transactional", "directional", "neutral")
EVENT_KINDS = ("action", "scheduled", "consequence", "emergent", "resolution", "system",
               "offer", "agreement", "breach")
# OFFERS (ported from the world-v1 engine's consent mechanics): a move of one of these
# options aimed at another actor opens an offer that only the recipient's answer can settle.
PROPOSAL_OPTION_IDS = frozenset({"open_talks", "form_alliance", "signal_concession", "sign_agreement",
                                 "partnership_deal", "bargain", "convene", "program_decision"})
RESPONSE_PREFIXES = ("accept:", "reject:", "counter:", "defer:")
INTERACTION_TTL_PERIODS = 2          # an unanswered offer lapses after this many periods
INTERACTION_MAX_DEFERRALS = 2        # a deferral moves the deadline one period, at most this often
INTERACTION_TERMS_MAX_CHARS = 300
INTERACTION_LIMIT = 200
COMMITMENT_STATUSES = ("pending", "due", "fulfilled", "lapsed", "withdrawn")

DEFAULT_CAPACITY_PER_ROUND = 2
HISTORY_LIMIT = 48
EVENT_LIMIT = 400
DEFAULT_MAX_CHANGE_RATIO = 0.5
PUBLIC_BRIEF_MAX_CHARS = 2400
PRIVATE_BRIEF_MAX_CHARS = 900

# polarity thresholds that re-label a relationship after a nudge
_ALLIED_AT = 0.25
_ADVERSARIAL_AT = -0.25

_SCALE_WORDS = (
    ("trillion", 1e12), ("tn", 1e12), ("万亿", 1e12),
    ("billion", 1e9), ("bn", 1e9), ("亿", 1e8),
    ("million", 1e6), ("mn", 1e6), ("m", 1e6),
    ("thousand", 1e3), ("k", 1e3), ("万", 1e4),
)
_CURRENCY_PREFIX = re.compile(r"^(?:us\$|usd|eur|gbp|cny|rmb|jpy|hk\$|a\$|c\$|[$€£¥￥]|美元|人民币|元)\s*",
                              re.IGNORECASE)
_NUMBER_RE = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def is_kind_name_unit(unit: Any) -> bool:
    """True when ``unit`` is a type / kind name rather than a unit of measure."""
    return str(unit or "").strip().casefold() in _KIND_NAME_UNITS


def _text(value: Any, max_chars: int = 240) -> str:
    """Collapse whitespace and bound a free-text value (never raises)."""
    if value is None:
        return ""
    try:
        s = " ".join(str(value).split())
    except Exception:  # noqa: BLE001
        return ""
    if max_chars > 0 and len(s) > max_chars:
        return s[: max(0, max_chars - 1)].rstrip() + "…"
    return s


def _items(values: Any, limit: int = 6, max_chars: int = 200) -> List[str]:
    out: List[str] = []
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, (list, tuple)):
        return out
    for v in values:
        if isinstance(v, dict):
            v = v.get("claim") or v.get("text") or v.get("description") or ""
        t = _text(v, max_chars)
        if t and t.casefold() not in {o.casefold() for o in out}:
            out.append(t)
        if len(out) >= limit:
            break
    return out


def normalize_label(value: Any) -> str:
    """Case/width-insensitive key for names and aliases."""
    s = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(s.split())


def slugify(name: Any, max_len: int = 64) -> str:
    """Stable variable id from a display name (CJK letters are kept)."""
    s = unicodedata.normalize("NFKC", str(name or "")).casefold()
    out: List[str] = []
    prev_us = False
    for ch in s:
        if ch.isalnum():
            out.append(ch)
            prev_us = False
        elif not prev_us:
            out.append("_")
            prev_us = True
    slug = "".join(out).strip("_")[:max_len].strip("_")
    if not slug:
        slug = "var_" + hashlib.sha1(str(name or "").encode("utf-8")).hexdigest()[:8]
    return slug


def parse_quantity(raw: Any) -> Tuple[Optional[float], str]:
    """Best-effort ``(number, unit)`` from a researched value string.

    Handles currency prefixes, thousands separators, percentage signs and the
    common scale words (k/m/bn/trillion, 万/亿/万亿).  Returns ``(None, "")``
    when no number is present so the caller can keep the fact as text.
    """
    if isinstance(raw, bool):
        return None, ""
    if isinstance(raw, (int, float)):
        if isinstance(raw, float) and (math.isnan(raw) or math.isinf(raw)):
            return None, ""
        return float(raw), ""
    s = _text(raw, 160)
    if not s:
        return None, ""
    unit = ""
    currency = _CURRENCY_PREFIX.match(s)
    if currency:
        unit = currency.group(0).strip()
        s = s[currency.end():]
    m = _NUMBER_RE.search(s)
    if not m:
        return None, ""
    try:
        number = float(m.group(0).replace(",", ""))
    except ValueError:
        return None, ""
    tail = s[m.end():].strip()
    low = tail.casefold()
    if low.startswith("%") or low.startswith("percent") or low.startswith("pct"):
        return number, "%"
    for word, scale in _SCALE_WORDS:
        if low.startswith(word) and (len(low) == len(word) or not low[len(word)].isalpha()):
            number *= scale
            tail = tail[len(word):].strip()
            break
    tail_unit = _text(tail, 24).strip(" ,;:")
    # keep an explicit unit word (GW, tons, units…) but not a sentence fragment
    if tail_unit and len(tail_unit.split()) <= 2 and len(tail_unit) <= 16:
        unit = (unit + " " + tail_unit).strip() if unit else tail_unit
    return number, unit


def _fmt_number(v: float) -> str:
    av = abs(v)
    if av >= 1e12:
        return f"{v / 1e12:.2f} trillion"
    if av >= 1e9:
        return f"{v / 1e9:.2f} billion"
    if av >= 1e6:
        return f"{v / 1e6:.2f} million"
    if av >= 1e4:
        return f"{v:,.0f}"
    if float(v).is_integer():
        return f"{int(v)}"
    return f"{v:.2f}".rstrip("0").rstrip(".")


def format_value(value: Any, unit: str = "") -> str:
    """Human rendering of a variable value with its unit."""
    if isinstance(value, bool):
        s = "yes" if value else "no"
    elif isinstance(value, (int, float)):
        s = _fmt_number(float(value))
    else:
        s = _text(value, 120)
    u = _text(unit, 24)
    if not u or is_kind_name_unit(u):
        return s
    if u == "%":
        return f"{s}%"
    if _is_currency_unit(u):
        return f"{u}{s}"
    return f"{s} {u}"


_CURRENCY_CODES = {"usd", "eur", "gbp", "cny", "rmb", "jpy", "hkd", "aud", "cad", "美元", "人民币", "元"}


def _is_currency_unit(unit: str) -> bool:
    u = str(unit or "").strip()
    if not u:
        return False
    if any(sym in u for sym in ("$", "€", "£", "¥", "￥")):
        return True
    return u.casefold() in _CURRENCY_CODES


# ---------------------------------------------------------------------------
# entities
# ---------------------------------------------------------------------------

class StateVariable:
    """A named world fact with a bounded causal history (I-2)."""

    def __init__(self, var_id: str, name: str, value: Any, *, unit: str = "",
                 kind: str = "numeric", as_of: Optional[str] = None,
                 provenance: str = "seed", rationale: str = "",
                 history: Optional[List[Dict[str, Any]]] = None) -> None:
        self.id = str(var_id)
        self.name = _text(name, 140) or self.id
        self.kind = kind if kind in VARIABLE_KINDS else "text"
        self.value = self._coerce(value)
        # a unit belongs to numeric facts only, and a kind name is never a unit
        self.unit = "" if self.kind != "numeric" or is_kind_name_unit(unit) else _text(unit, 24)
        self.as_of = _text(as_of, 40) or None
        self.provenance = provenance if provenance in PROVENANCES else "seed"
        self.rationale = _text(rationale, 240)
        self.history: List[Dict[str, Any]] = list(history or [])
        if not self.history:
            self.history.append({"round": 0, "value": self.value, "cause": "seed",
                                 "source": self.provenance})

    def _coerce(self, value: Any) -> Any:
        if self.kind == "numeric":
            num, _ = parse_quantity(value)
            if num is None:
                self.kind = "text"
                return _text(value, 160)
            return num
        if self.kind == "boolean":
            if isinstance(value, bool):
                return value
            low = _text(value, 16).casefold()
            if low in ("true", "yes", "1", "是"):
                return True
            if low in ("false", "no", "0", "否"):
                return False
            self.kind = "text"
            return _text(value, 160)
        return _text(value, 160)

    def set_value(self, value: Any, *, round_num: int, source: str, cause: str,
                  max_change_ratio: Optional[float] = None) -> bool:
        """Apply a change with provenance; numeric changes may be clamped.

        Returns True when the stored value actually changed.
        """
        new = self._coerce(value)
        if self.kind != "numeric":
            self.unit = ""  # a numeric fact that became text keeps no unit
        if self.kind == "numeric" and isinstance(new, (int, float)) and max_change_ratio:
            cur = float(self.value) if isinstance(self.value, (int, float)) else 0.0
            cap = abs(cur) * float(max_change_ratio) if cur != 0 else None
            if cap is not None and abs(float(new) - cur) > cap:
                new = cur + math.copysign(cap, float(new) - cur)
        if new == self.value:
            return False
        self.value = new
        self.provenance = source if source in PROVENANCES else self.provenance
        self.history.append({"round": int(round_num), "value": new,
                             "cause": _text(cause, 200), "source": source})
        if len(self.history) > HISTORY_LIMIT:
            self.history = self.history[-HISTORY_LIMIT:]
        return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "value": self.value, "unit": self.unit,
            "kind": self.kind, "as_of": self.as_of, "provenance": self.provenance,
            "rationale": self.rationale, "history": list(self.history),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "StateVariable":
        return cls(d.get("id") or slugify(d.get("name")), d.get("name") or d.get("id"),
                   d.get("value"), unit=d.get("unit") or "", kind=d.get("kind") or "text",
                   as_of=d.get("as_of"), provenance=d.get("provenance") or "seed",
                   rationale=d.get("rationale") or "", history=d.get("history") or None)


class ActorState:
    """Per-actor world state: capacity, posture, plans, commitments, last move."""

    def __init__(self, agent_id: int, name: str, *, agency_class: str = "other_actor",
                 archetype: str = "actor", capacity_per_round: int = DEFAULT_CAPACITY_PER_ROUND,
                 outcome_power: Optional[float] = None, posture: str = "",
                 documented_plans: Optional[List[str]] = None,
                 red_lines: Optional[List[str]] = None, aliases: Optional[List[str]] = None,
                 goals: Optional[List[str]] = None, incentives: Optional[Dict[str, str]] = None,
                 reputation: float = 0.5) -> None:
        self.agent_id = int(agent_id)
        self.name = _text(name, 160) or f"Agent_{agent_id}"
        self.agency_class = _text(agency_class, 48) or "other_actor"
        self.archetype = _text(archetype, 32) or "actor"
        try:
            self.capacity_per_round = max(1, int(capacity_per_round))
        except (TypeError, ValueError):
            self.capacity_per_round = DEFAULT_CAPACITY_PER_ROUND
        self.capacity_used = 0
        self.outcome_power = None
        if outcome_power is not None:
            try:
                self.outcome_power = max(0.0, float(outcome_power))
            except (TypeError, ValueError):
                self.outcome_power = None
        self.posture = _text(posture, 200)
        self.documented_plans = _items(documented_plans, 6, 200)
        self.red_lines = _items(red_lines, 4, 160)
        self.goals = _items(goals, 4, 160)
        self.incentives = {k: _text(v, 220) for k, v in (incentives or {}).items() if _text(v, 220)}
        self.aliases = [a for a in _items(aliases, 8, 80)]
        self.reputation = _clamp(float(reputation), 0.0, 1.0)
        self.commitments: List[Dict[str, Any]] = []
        self.last_action: Optional[Dict[str, Any]] = None
        self.irreversible_option_ids: List[str] = []

    # -- helpers --------------------------------------------------------------
    @property
    def capacity_remaining(self) -> int:
        return max(0, self.capacity_per_round - self.capacity_used)

    def name_keys(self) -> List[str]:
        keys = [normalize_label(self.name)]
        keys.extend(normalize_label(a) for a in self.aliases)
        return [k for k in keys if k]

    def add_commitment(self, description: str, *, made_round: int, due_round: int,
                       source: str = "decision") -> Dict[str, Any]:
        row = {
            "id": f"c{self.agent_id}_{made_round}_{len(self.commitments) + 1}",
            "description": _text(description, 220),
            "made_round": int(made_round),
            "due_round": int(due_round),
            "status": "pending",
            "source": _text(source, 40),
        }
        self.commitments.append(row)
        if len(self.commitments) > 24:
            self.commitments = self.commitments[-24:]
        return row

    def pending_commitments(self) -> List[Dict[str, Any]]:
        return [c for c in self.commitments if c.get("status") in ("pending", "due")]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id, "name": self.name, "agency_class": self.agency_class,
            "archetype": self.archetype, "capacity_per_round": self.capacity_per_round,
            "capacity_used": self.capacity_used, "outcome_power": self.outcome_power,
            "posture": self.posture, "documented_plans": list(self.documented_plans),
            "red_lines": list(self.red_lines), "goals": list(self.goals),
            "incentives": dict(self.incentives), "aliases": list(self.aliases),
            "reputation": round(self.reputation, 4), "commitments": list(self.commitments),
            "last_action": self.last_action, "irreversible_option_ids": list(self.irreversible_option_ids),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ActorState":
        a = cls(d.get("agent_id", 0), d.get("name") or "", agency_class=d.get("agency_class") or "other_actor",
                archetype=d.get("archetype") or "actor",
                capacity_per_round=d.get("capacity_per_round") or DEFAULT_CAPACITY_PER_ROUND,
                outcome_power=d.get("outcome_power"), posture=d.get("posture") or "",
                documented_plans=d.get("documented_plans"), red_lines=d.get("red_lines"),
                aliases=d.get("aliases"), goals=d.get("goals"), incentives=d.get("incentives"),
                reputation=d.get("reputation", 0.5) if isinstance(d.get("reputation"), (int, float)) else 0.5)
        try:
            a.capacity_used = max(0, int(d.get("capacity_used") or 0))
        except (TypeError, ValueError):
            a.capacity_used = 0
        a.commitments = [c for c in (d.get("commitments") or []) if isinstance(c, dict)]
        a.last_action = d.get("last_action") if isinstance(d.get("last_action"), dict) else None
        a.irreversible_option_ids = [str(x) for x in (d.get("irreversible_option_ids") or [])
                                     if str(x).strip()]
        return a


class Relationship:
    """A valenced, directed edge between two cast members."""

    def __init__(self, source: int, target: int, *, kind: str = "RELATES_TO",
                 valence: str = "neutral", polarity: Optional[float] = None,
                 strength: Optional[float] = None, basis: str = "",
                 last_changed_round: int = 0, history: Optional[List[Dict[str, Any]]] = None) -> None:
        self.source = int(source)
        self.target = int(target)
        self.kind = _text(kind, 40).upper() or "RELATES_TO"
        self.valence = valence if valence in VALENCES else "neutral"
        if polarity is None:
            polarity = {"allied": 0.4, "adversarial": -0.4, "transactional": 0.15}.get(self.valence, 0.0)
        self.polarity = _clamp(float(polarity), -1.0, 1.0)
        self.strength = _clamp(float(strength), 0.0, 1.0) if strength is not None else min(1.0, abs(self.polarity) + 0.3)
        self.basis = _text(basis, 200)
        self.last_changed_round = int(last_changed_round)
        self.history: List[Dict[str, Any]] = list(history or [])

    @property
    def key(self) -> Tuple[int, int]:
        return (self.source, self.target)

    def involves(self, agent_id: int) -> bool:
        return agent_id in (self.source, self.target)

    def nudge(self, delta: float, *, round_num: int, cause: str) -> float:
        """Move polarity by ``delta`` (bounded), relabel valence, record cause."""
        before = self.polarity
        self.polarity = _clamp(self.polarity + _clamp(float(delta), -0.5, 0.5), -1.0, 1.0)
        if self.polarity >= _ALLIED_AT:
            self.valence = "allied"
        elif self.polarity <= _ADVERSARIAL_AT:
            self.valence = "adversarial"
        elif self.valence in ("allied", "adversarial"):
            self.valence = "neutral"
        self.strength = _clamp(0.7 * self.strength + 0.3 * min(1.0, abs(self.polarity) + 0.3), 0.0, 1.0)
        self.last_changed_round = int(round_num)
        self.history.append({"round": int(round_num), "from": round(before, 4),
                             "to": round(self.polarity, 4), "cause": _text(cause, 160)})
        if len(self.history) > HISTORY_LIMIT:
            self.history = self.history[-HISTORY_LIMIT:]
        return self.polarity - before

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source, "target": self.target, "kind": self.kind,
            "valence": self.valence, "polarity": round(self.polarity, 4),
            "strength": round(self.strength, 4), "basis": self.basis,
            "last_changed_round": self.last_changed_round, "history": list(self.history),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Relationship":
        return cls(d.get("source", 0), d.get("target", 0), kind=d.get("kind") or "RELATES_TO",
                   valence=d.get("valence") or "neutral", polarity=d.get("polarity"),
                   strength=d.get("strength"), basis=d.get("basis") or "",
                   last_changed_round=d.get("last_changed_round") or 0, history=d.get("history"))


class PendingEffect:
    """A delayed consequence resolved when its round comes."""

    def __init__(self, effect_id: str, *, due_round: int, description: str,
                 variable_id: Optional[str] = None, op: str = "set", value: Any = None,
                 probability: float = 1.0, source: str = "", actor_id: Optional[int] = None,
                 targets: Optional[List[str]] = None, created_round: int = 0) -> None:
        self.id = str(effect_id)
        self.due_round = int(due_round)
        self.description = _text(description, 220)
        self.variable_id = str(variable_id) if variable_id else None
        self.op = op if op in ("set", "add", "mul") else "set"
        self.value = value
        try:
            self.probability = _clamp(float(probability), 0.0, 1.0)
        except (TypeError, ValueError):
            self.probability = 1.0
        self.source = _text(source, 80)
        self.actor_id = int(actor_id) if actor_id is not None else None
        self.targets = _items(targets, 6, 80)
        self.created_round = int(created_round)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "due_round": self.due_round, "description": self.description,
            "variable_id": self.variable_id, "op": self.op, "value": self.value,
            "probability": self.probability, "source": self.source, "actor_id": self.actor_id,
            "targets": list(self.targets), "created_round": self.created_round,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PendingEffect":
        return cls(d.get("id") or "fx", due_round=d.get("due_round") or 0,
                   description=d.get("description") or "", variable_id=d.get("variable_id"),
                   op=d.get("op") or "set", value=d.get("value"),
                   probability=d.get("probability", 1.0), source=d.get("source") or "",
                   actor_id=d.get("actor_id"), targets=d.get("targets"),
                   created_round=d.get("created_round") or 0)


class Interaction:
    """An offer from one actor to another that only the recipient's answer can settle.

    Ported from the world-v1 engine's consent rule: speech cannot create an agreement.  A
    proposal (``kind="proposal"``) or a counter-offer (``kind="counter"``) stays ``open`` (or
    ``deferred``) until the recipient accepts, rejects or counters it, or it lapses after
    ``INTERACTION_TTL_PERIODS`` periods.  Acceptance binds *both* parties with commitments
    (``obligations``: commitment ids, source ``agreement:<id>``); a lapsed obligation or an
    explicit withdrawal is a ``breach`` with reputation and relationship consequences.
    """

    def __init__(self, iid: str, *, proposer: int, recipient: int, option_id: str, terms: str,
                 opened_round: int, expires_round: int, kind: str = "proposal", status: str = "open",
                 parent_id: str = "", resolved_round: Optional[int] = None, response: str = "",
                 obligations: Optional[List[str]] = None, deferrals: int = 0) -> None:
        self.id = _text(iid, 40)
        self.deferrals = max(0, int(deferrals or 0))
        self.proposer = int(proposer)
        self.recipient = int(recipient)
        self.option_id = _text(option_id, 64)
        self.terms = _text(terms, INTERACTION_TERMS_MAX_CHARS)
        self.opened_round = int(opened_round)
        self.expires_round = int(expires_round)
        self.kind = kind if kind in ("proposal", "counter") else "proposal"
        self.status = status if status in ("open", "deferred", "accepted", "rejected", "countered",
                                           "lapsed", "breached") else "open"
        self.parent_id = _text(parent_id, 40)
        self.resolved_round = int(resolved_round) if resolved_round is not None else None
        self.response = _text(response, 200)
        self.obligations = [str(o) for o in (obligations or []) if str(o)][:4]

    def is_open(self) -> bool:
        return self.status in ("open", "deferred")

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "proposer": self.proposer, "recipient": self.recipient,
                "option_id": self.option_id, "terms": self.terms, "opened_round": self.opened_round,
                "expires_round": self.expires_round, "status": self.status, "parent_id": self.parent_id,
                "resolved_round": self.resolved_round, "response": self.response,
                "obligations": list(self.obligations), "deferrals": self.deferrals}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Interaction":
        return cls(d.get("id") or "", proposer=d.get("proposer") or 0, recipient=d.get("recipient") or 0,
                   option_id=d.get("option_id") or "", terms=d.get("terms") or "",
                   opened_round=d.get("opened_round") or 0, expires_round=d.get("expires_round") or 0,
                   kind=d.get("kind") or "proposal", status=d.get("status") or "open",
                   parent_id=d.get("parent_id") or "", resolved_round=d.get("resolved_round"),
                   response=d.get("response") or "", obligations=d.get("obligations"),
                   deferrals=d.get("deferrals") or 0)


class WorldEvent:
    """One dated world event (action, scheduled, consequence, emergent, resolution, offer, agreement, breach)."""

    def __init__(self, round_num: int, kind: str, description: str, *,
                 actors: Optional[List[str]] = None, targets: Optional[List[str]] = None,
                 source: str = "", variable_ids: Optional[List[str]] = None,
                 statement: str = "", option_id: str = "", action_kind: str = "",
                 period_label: str = "") -> None:
        self.round = int(round_num)
        self.kind = kind if kind in EVENT_KINDS else "system"
        self.description = _text(description, 320)
        self.actors = _items(actors, 8, 120)
        self.targets = _items(targets, 8, 120)
        self.source = _text(source, 60)
        self.variable_ids = [str(v) for v in (variable_ids or []) if v][:8]
        self.statement = _text(statement, 320)
        self.option_id = _text(option_id, 64)
        self.action_kind = _text(action_kind, 32)
        self.period_label = _text(period_label, 40)

    def to_dict(self) -> Dict[str, Any]:
        d = {"round": self.round, "kind": self.kind, "description": self.description,
             "actors": list(self.actors), "targets": list(self.targets), "source": self.source,
             "variable_ids": list(self.variable_ids)}
        if self.statement:
            d["statement"] = self.statement
        if self.option_id:
            d["option_id"] = self.option_id
        if self.action_kind:
            d["action_kind"] = self.action_kind
        if self.period_label:
            d["period_label"] = self.period_label
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "WorldEvent":
        return cls(d.get("round") or 0, d.get("kind") or "system", d.get("description") or "",
                   actors=d.get("actors"), targets=d.get("targets"), source=d.get("source") or "",
                   variable_ids=d.get("variable_ids"), statement=d.get("statement") or "",
                   option_id=d.get("option_id") or "", action_kind=d.get("action_kind") or "",
                   period_label=d.get("period_label") or "")


# ---------------------------------------------------------------------------
# the world
# ---------------------------------------------------------------------------

class WorldModel:
    """The shared, evolving world every agent observes and acts upon."""

    def __init__(self, *, question: str = "", as_of_date: Optional[str] = None,
                 horizon_date: Optional[str] = None, scenarios: Iterable[str] = (),
                 settings: Optional[Dict[str, Any]] = None) -> None:
        self.question = _text(question, 400)
        self.as_of_date = _text(as_of_date, 40) or None
        self.horizon_date = _text(horizon_date, 40) or None
        self.scenarios = [str(s) for s in scenarios if str(s).strip()]
        self.settings: Dict[str, Any] = dict(settings or {})
        self.variables: Dict[str, StateVariable] = {}
        self.actors: Dict[int, ActorState] = {}
        self.relationships: Dict[Tuple[int, int], Relationship] = {}
        self.pending_effects: List[PendingEffect] = []
        self.events: List[WorldEvent] = []
        self.round = 0
        self.committed_round = 0
        self.period: Optional[Dict[str, Any]] = None
        self.scenario_shares: Dict[str, float] = {}
        self.period_labels: Dict[int, str] = {}
        self._effect_seq = 0
        self._name_index: Dict[str, int] = {}
        # OFFERS: id → Interaction (open offers, agreements and their outcomes)
        self.interactions: Dict[str, Interaction] = {}
        self._interaction_seq = 0
        # MODELLING GAPS reported by the seed (what the research could not ground)
        self.seed_gaps: List[Dict[str, Any]] = []

    # -- construction -----------------------------------------------------------
    @classmethod
    def from_seed(cls, seed: Dict[str, Any], agent_configs: Optional[List[Dict[str, Any]]] = None,
                  *, scenarios: Iterable[str] = ()) -> "WorldModel":
        """Build the initial world from the PREPARE-time ``world_model`` block.

        ``agent_configs`` (``simulation_config.agent_configs``) supplies names for
        cast members the seed does not describe, so every agent has an actor state.
        """
        seed = seed if isinstance(seed, dict) else {}
        world = cls(question=seed.get("question") or "", as_of_date=seed.get("as_of_date"),
                    horizon_date=seed.get("horizon_date"), scenarios=scenarios or seed.get("scenarios") or (),
                    settings=seed.get("settings") if isinstance(seed.get("settings"), dict) else None)
        world.seed_gaps = [g for g in (seed.get("gaps") or []) if isinstance(g, dict)][:32]
        seeded: Dict[int, Dict[str, Any]] = {}
        for row in seed.get("actors") or []:
            if isinstance(row, dict) and row.get("agent_id") is not None:
                try:
                    seeded[int(row["agent_id"])] = row
                except (TypeError, ValueError):
                    continue
        for cfg in agent_configs or []:
            if not isinstance(cfg, dict) or cfg.get("agent_id") is None:
                continue
            try:
                aid = int(cfg["agent_id"])
            except (TypeError, ValueError):
                continue
            row = seeded.get(aid, {})
            world.add_actor(ActorState(
                aid, row.get("name") or cfg.get("entity_name") or f"Agent_{aid}",
                agency_class=row.get("agency_class") or cfg.get("agency_class") or "other_actor",
                archetype=row.get("archetype") or cfg.get("archetype") or "actor",
                capacity_per_round=row.get("capacity_per_round") or DEFAULT_CAPACITY_PER_ROUND,
                outcome_power=row.get("outcome_power", cfg.get("outcome_power")),
                posture=row.get("posture") or cfg.get("stance") or "",
                documented_plans=row.get("documented_plans"), red_lines=row.get("red_lines"),
                aliases=row.get("aliases"), goals=row.get("goals"),
                incentives=row.get("incentives") or {
                    k: v for k, v in (("gains_if", cfg.get("gains_if")), ("loses_if", cfg.get("loses_if"))) if v
                },
            ))
        for aid, row in seeded.items():
            if aid not in world.actors:
                world.add_actor(ActorState(
                    aid, row.get("name") or f"Agent_{aid}", agency_class=row.get("agency_class") or "other_actor",
                    archetype=row.get("archetype") or "actor",
                    capacity_per_round=row.get("capacity_per_round") or DEFAULT_CAPACITY_PER_ROUND,
                    outcome_power=row.get("outcome_power"), posture=row.get("posture") or "",
                    documented_plans=row.get("documented_plans"), red_lines=row.get("red_lines"),
                    aliases=row.get("aliases"), goals=row.get("goals"), incentives=row.get("incentives")))
        for row in seed.get("state_variables") or []:
            if not isinstance(row, dict):
                continue
            name = row.get("name") or row.get("metric")
            if not name:
                continue
            world.add_variable(name, row.get("value"), unit=row.get("unit") or "",
                               kind=row.get("kind") or "numeric", as_of=row.get("as_of") or row.get("as_of_date"),
                               provenance=row.get("provenance") or "research",
                               rationale=row.get("rationale") or row.get("source") or "",
                               var_id=row.get("id"))
        for row in seed.get("relationships") or []:
            if not isinstance(row, dict):
                continue
            s = world.resolve_actor(row.get("source_agent_id", row.get("source")))
            t = world.resolve_actor(row.get("target_agent_id", row.get("target")))
            if s is None or t is None or s == t:
                continue
            world.add_relationship(Relationship(
                s, t, kind=row.get("kind") or row.get("type") or "RELATES_TO",
                valence=row.get("valence") or "neutral", polarity=row.get("polarity"),
                strength=row.get("strength") if isinstance(row.get("strength"), (int, float)) else None,
                basis=row.get("basis") or ""))
        return world

    def add_actor(self, actor: ActorState) -> None:
        self.actors[actor.agent_id] = actor
        for key in actor.name_keys():
            self._name_index.setdefault(key, actor.agent_id)

    def add_variable(self, name: Any, value: Any, *, unit: str = "", kind: str = "numeric",
                     as_of: Optional[str] = None, provenance: str = "research", rationale: str = "",
                     var_id: Optional[str] = None, initial_round: int = 0,
                     initial_cause: str = "") -> str:
        """Register (or update) a variable; returns its id.  Duplicate names merge."""
        vid = slugify(var_id or name)
        if vid in self.variables:
            self.variables[vid].set_value(value, round_num=self.round, source=provenance,
                                          cause="re-seeded")
            return vid
        if kind == "numeric":
            num, parsed_unit = parse_quantity(value)
            if num is None:
                kind = "text"
            elif not unit and parsed_unit:
                unit = parsed_unit
        self.variables[vid] = StateVariable(vid, name, value, unit=unit, kind=kind, as_of=as_of,
                                            provenance=provenance, rationale=rationale)
        self.variables[vid].history = [{
            "round": int(initial_round),
            "value": self.variables[vid].value,
            "cause": _text(initial_cause, 200) or ("seed" if int(initial_round) == 0 else provenance),
            "source": provenance,
        }]
        return vid

    def add_relationship(self, rel: Relationship) -> None:
        self.relationships[rel.key] = rel

    def resolve_actor(self, ref: Any) -> Optional[int]:
        """Resolve an agent id or a (possibly aliased, partial) actor name."""
        if ref is None or isinstance(ref, bool):
            return None
        if isinstance(ref, int) and ref in self.actors:
            return ref
        if isinstance(ref, float) and ref.is_integer() and int(ref) in self.actors:
            return int(ref)
        text = str(ref).strip()
        if not text:
            return None
        if text.isdigit() and int(text) in self.actors:
            return int(text)
        key = normalize_label(text)
        if key in self._name_index:
            return self._name_index[key]
        # containment either way (e.g. "Alpha" vs "Alpha Systems"), longest match wins
        best: Optional[Tuple[int, int]] = None
        for name_key, aid in self._name_index.items():
            if len(name_key) < 3:
                continue
            if name_key in key or key in name_key:
                score = len(name_key)
                if best is None or score > best[0]:
                    best = (score, aid)
        return best[1] if best else None

    def actor_name(self, agent_id: Any) -> str:
        a = self.actors.get(agent_id) if isinstance(agent_id, int) else None
        return a.name if a else str(agent_id)

    def relationships_of(self, agent_id: int) -> List[Relationship]:
        return [r for r in self.relationships.values() if r.involves(agent_id)]

    def _relationship_between(self, a: int, b: int) -> Optional[Relationship]:
        return self.relationships.get((a, b)) or self.relationships.get((b, a))

    def _ensure_relationship(self, a: int, b: int, *, kind: str, round_num: int, basis: str) -> Relationship:
        rel = self._relationship_between(a, b)
        if rel is None:
            rel = Relationship(a, b, kind=kind, valence="neutral", polarity=0.0, strength=0.3,
                               basis=basis, last_changed_round=round_num)
            self.add_relationship(rel)
        return rel

    def _next_effect_id(self, round_num: int) -> str:
        self._effect_seq += 1
        return f"fx{round_num}_{self._effect_seq}"

    def _add_event(self, event: WorldEvent) -> WorldEvent:
        self.events.append(event)
        if len(self.events) > EVENT_LIMIT:
            self.events = self.events[-EVENT_LIMIT:]
        return event

    # -- round mechanics -----------------------------------------------------------
    def set_period_labels(self, labels: Dict[Any, Any]) -> None:
        """Known round → period label map (1-based rounds) for due-date rendering."""
        for k, v in (labels or {}).items():
            try:
                self.period_labels[int(k)] = _text(v, 40)
            except (TypeError, ValueError):
                continue

    def start_round(self, round_num: int, period: Optional[Dict[str, Any]]) -> None:
        """Open round ``round_num`` (1-based): reset capacity, mark due commitments."""
        self.round = int(round_num)
        self.period = dict(period) if isinstance(period, dict) else None
        if self.period and self.period.get("label"):
            self.period_labels[self.round] = _text(self.period["label"], 40)
        for actor in self.actors.values():
            actor.capacity_used = 0
            for c in actor.commitments:
                if c.get("status") == "pending" and int(c.get("due_round", 0)) <= self.round:
                    c["status"] = "due"

    def register_scheduled_events(self, round_num: int, fired_events: Iterable[Dict[str, Any]]) -> List[WorldEvent]:
        out: List[WorldEvent] = []
        seen = set()
        label = str((self.period or {}).get("label") or "")
        for ev in fired_events or []:
            if not isinstance(ev, dict):
                continue
            content = _text(ev.get("content") or ev.get("event") or ev.get("description"), 320)
            if not content:
                continue
            key = (str(ev.get("date") or ""), content)
            if key in seen:
                continue
            seen.add(key)
            actors = []
            poster = ev.get("poster_name")
            if poster:
                actors.append(str(poster))
            out.append(self._add_event(WorldEvent(round_num, "scheduled", content, actors=actors,
                                                  source="research_timeline", period_label=label)))
        return out

    def register_decisions(self, round_num: int, decisions: Iterable[Dict[str, Any]]) -> List[WorldEvent]:
        """Apply the deterministic part of the actors' structured decisions.

        Each decision row (``agent_decision.AgentDecision.to_dict``) carries
        ``agent_id``, ``option`` (id/label/kind/cost/lag/reversibility), ``targets``
        (agent ids), ``magnitude``, ``public_statement``, ``commitment``,
        ``alliance_moves`` and ``status``.  Capacity is consumed, commitments
        registered, coalition/antagonistic moves nudge relationships, and an
        ``action`` event is recorded.  Decisions whose status is not ``ok`` only
        record a ``hold`` event.
        """
        out: List[WorldEvent] = []
        label = str((self.period or {}).get("label") or "")
        for d in decisions or []:
            if not isinstance(d, dict):
                continue
            aid = self.resolve_actor(d.get("agent_id"))
            if aid is None:
                continue
            actor = self.actors[aid]
            option = d.get("option") if isinstance(d.get("option"), dict) else {}
            kind = _text(option.get("kind"), 32) or "communication"
            option_id = _text(option.get("id"), 64) or "hold_position"
            try:
                magnitude = _clamp(float(d.get("magnitude", 0.5) or 0.0), 0.0, 1.0)
            except (TypeError, ValueError):
                magnitude = 0.5
            targets = [t for t in (self.resolve_actor(x) for x in (d.get("targets") or [])) if t is not None and t != aid]
            target_names = [self.actor_name(t) for t in targets]
            status = _text(d.get("status"), 24) or "ok"
            try:
                cost = max(0, int(option.get("cost", 1) or 0))
            except (TypeError, ValueError):
                cost = 1
            try:
                lag = max(0, int(option.get("lag", 0) or 0))
            except (TypeError, ValueError):
                lag = 0
            actor.capacity_used = min(actor.capacity_per_round, actor.capacity_used + cost)
            description = _text(option.get("label"), 160) or option_id
            if target_names:
                description += " → " + ", ".join(target_names[:4])
            actor.last_action = {
                "round": int(round_num), "option_id": option_id, "kind": kind,
                "label": _text(option.get("label"), 160), "targets": target_names,
                "magnitude": round(magnitude, 3), "status": status, "resolution": None,
                "reversibility": _text(option.get("reversibility"), 24),
            }
            event_kind = "action"
            if option_id == "hold_position" or status != "ok":
                description = (f"{actor.name} holds position" if status == "ok"
                               else f"{actor.name} makes no recorded move ({status})")
            out.append(self._add_event(WorldEvent(
                round_num, event_kind, description, actors=[actor.name], targets=target_names,
                source="decision", statement=d.get("public_statement") or "",
                option_id=option_id, action_kind=kind, period_label=label)))
            if status != "ok":
                continue
            if option_id.startswith(RESPONSE_PREFIXES):
                # OFFERS: the recipient's answer settles the offer; nothing else in this decision
                # can create an agreement (consent rule)
                verb, _, iid = option_id.partition(":")
                out.extend(self.resolve_interaction(round_num, iid, verb, aid,
                                                    statement=d.get("public_statement") or "",
                                                    terms=d.get("terms") or "", magnitude=magnitude, lag=lag))
                continue
            if option.get("reversibility") == "irreversible" and option_id != "hold_position":
                if option_id not in actor.irreversible_option_ids:
                    actor.irreversible_option_ids.append(option_id)
            if option_id != "hold_position":
                # a commitment that fell due this period is honoured by acting on it; a holder
                # lets it lapse (see lapse_overdue_commitments) — mechanical, no LLM judgement
                for c in actor.commitments:
                    if c.get("status") == "due":
                        c["status"] = "fulfilled"
                        c["fulfilled_round"] = int(round_num)
            commitment = d.get("commitment") if isinstance(d.get("commitment"), dict) else None
            if commitment and _text(commitment.get("description"), 220):
                try:
                    due_periods = max(0, int(commitment.get("due_periods", lag) or 0))
                except (TypeError, ValueError):
                    due_periods = lag
                actor.add_commitment(commitment["description"], made_round=round_num,
                                     due_round=round_num + max(1, due_periods))
            elif lag > 0 and option_id != "hold_position" and option_id not in PROPOSAL_OPTION_IDS:
                # (a proposing move's pending item is the offer itself, not an announced commitment)
                actor.add_commitment(f"{_text(option.get('label'), 120) or option_id} (announced)",
                                     made_round=round_num, due_round=round_num + lag, source="option_lag")
            # relationship dynamics: coalition moves pull closer, antagonistic ones push apart
            for move in d.get("alliance_moves") or []:
                if not isinstance(move, dict):
                    continue
                other = self.resolve_actor(move.get("target"))
                if other is None or other == aid:
                    continue
                verb = _text(move.get("move"), 24).casefold()
                delta = {"propose": 0.2, "strengthen": 0.15, "join": 0.2, "support": 0.15,
                         "break": -0.35, "oppose": -0.25, "sanction": -0.3, "distance": -0.15}.get(verb)
                if delta is None:
                    continue
                rel = self._ensure_relationship(aid, other, kind="ALLY_OF" if delta > 0 else "OPPOSES",
                                                round_num=round_num, basis=f"{verb} move in round {round_num}")
                rel.nudge(delta * (0.5 + 0.5 * magnitude), round_num=round_num,
                          cause=f"{actor.name} {verb} {self.actor_name(other)}")
            if kind in ("coalition",) and targets:
                for other in targets:
                    rel = self._ensure_relationship(aid, other, kind="PARTNERS_WITH", round_num=round_num,
                                                    basis=description)
                    rel.nudge(0.12 * (0.5 + 0.5 * magnitude), round_num=round_num, cause=description)
            elif kind in ("legal", "coercive") and targets:
                for other in targets:
                    rel = self._ensure_relationship(aid, other, kind="OPPOSES", round_num=round_num,
                                                    basis=description)
                    rel.nudge(-0.15 * (0.5 + 0.5 * magnitude), round_num=round_num, cause=description)
            # OFFERS: a proposing move aimed at another actor opens an offer the recipient must
            # answer; withdrawing from an agreement in force is an explicit breach
            if option_id in PROPOSAL_OPTION_IDS and targets:
                terms = (_text(d.get("terms"), INTERACTION_TERMS_MAX_CHARS)
                         or _text(d.get("public_statement"), INTERACTION_TERMS_MAX_CHARS) or description)
                for other in targets[:2]:
                    out.append(self.open_interaction(round_num, aid, other, option_id, terms))
            elif option_id == "break_alliance" and targets:
                for other in targets[:2]:
                    out.extend(self.breach_agreements_between(round_num, aid, other,
                                                              cause=f"{actor.name} withdrew: {description}"))
        return out

    # -- offers and agreements (consent rule) ----------------------------------------
    def open_interaction(self, round_num: int, proposer: int, recipient: int, option_id: str, terms: str, *,
                         kind: str = "proposal", parent_id: str = "") -> WorldEvent:
        """Record an offer from ``proposer`` to ``recipient``; returns its ``offer`` event."""
        self._interaction_seq += 1
        iid = f"i{int(round_num)}_{self._interaction_seq}"
        inter = Interaction(iid, proposer=proposer, recipient=recipient, option_id=option_id, terms=terms,
                            opened_round=round_num, expires_round=int(round_num) + INTERACTION_TTL_PERIODS,
                            kind=kind, parent_id=parent_id)
        self.interactions[iid] = inter
        if len(self.interactions) > INTERACTION_LIMIT:
            for old_id in [i for i, it in self.interactions.items() if not it.is_open()]:
                del self.interactions[old_id]
                if len(self.interactions) <= INTERACTION_LIMIT:
                    break
        pname, rname = self.actor_name(proposer), self.actor_name(recipient)
        what = "counter-offer" if kind == "counter" else "offer"
        return self._add_event(WorldEvent(
            round_num, "offer",
            f"{pname} made an {what} to {rname} [{iid}]: {inter.terms} "
            f"(answer due by {self._period_label_for_round(inter.expires_round)})",
            actors=[pname], targets=[rname], source="interaction", option_id=option_id,
            period_label=str((self.period or {}).get("label") or "")))

    def open_interactions_for(self, agent_id: int) -> List[Interaction]:
        """Offers the actor still has to answer, oldest first."""
        return sorted((it for it in self.interactions.values() if it.recipient == int(agent_id) and it.is_open()),
                      key=lambda it: (it.opened_round, it.id))

    def agreements_between(self, a: int, b: int) -> List[Interaction]:
        return [it for it in self.interactions.values() if it.status == "accepted"
                and {it.proposer, it.recipient} == {int(a), int(b)}]

    def resolve_interaction(self, round_num: int, iid: str, verb: str, actor_id: int, *, statement: str = "",
                            terms: str = "", magnitude: float = 0.5, lag: int = 0) -> List[WorldEvent]:
        """The recipient's answer: accept (binds both parties), reject, counter or defer."""
        inter = self.interactions.get(str(iid))
        name = self.actor_name(actor_id)
        if inter is None or inter.recipient != int(actor_id) or not inter.is_open():
            return [self._add_event(WorldEvent(round_num, "system",
                                               f"{name} answered an offer that is no longer open ({iid})",
                                               actors=[name], source="interaction"))]
        pname, rname = self.actor_name(inter.proposer), self.actor_name(inter.recipient)
        inter.response = _text(statement, 200)
        inter.resolved_round = int(round_num)
        label = str((self.period or {}).get("label") or "")
        events: List[WorldEvent] = []
        if verb == "accept":
            inter.status = "accepted"
            due = int(round_num) + max(1, int(lag or 0))
            for party, other in ((inter.proposer, inter.recipient), (inter.recipient, inter.proposer)):
                row = self.actors[party].add_commitment(
                    f"Honour the agreement with {self.actor_name(other)}: {inter.terms}",
                    made_round=round_num, due_round=due, source=f"agreement:{inter.id}")
                row["counterparty"] = int(other)
                inter.obligations.append(row["id"])
            rel = self._ensure_relationship(inter.proposer, inter.recipient, kind="PARTNERS_WITH",
                                            round_num=round_num, basis=f"agreement {inter.id}")
            rel.nudge(0.25 * (0.5 + 0.5 * magnitude), round_num=round_num,
                      cause=f"{rname} accepted {pname}'s offer")
            events.append(self._add_event(WorldEvent(
                round_num, "agreement",
                f"Agreement [{inter.id}]: {rname} accepted {pname}'s offer — {inter.terms} "
                f"(both sides' obligations due {self._period_label_for_round(due)})",
                actors=[rname, pname], targets=[pname], source="interaction", statement=statement,
                option_id=inter.option_id, period_label=label)))
        elif verb == "reject":
            inter.status = "rejected"
            rel = self._ensure_relationship(inter.proposer, inter.recipient, kind="RELATES_TO",
                                            round_num=round_num, basis=f"offer {inter.id} rejected")
            rel.nudge(-0.1 * (0.5 + 0.5 * magnitude), round_num=round_num,
                      cause=f"{rname} rejected {pname}'s offer")
            events.append(self._add_event(WorldEvent(
                round_num, "offer", f"{rname} rejected {pname}'s offer [{inter.id}]: {inter.terms}",
                actors=[rname], targets=[pname], source="interaction", statement=statement,
                option_id=inter.option_id, period_label=label)))
        elif verb == "counter":
            inter.status = "countered"
            new_terms = (_text(terms, INTERACTION_TERMS_MAX_CHARS)
                         or _text(statement, INTERACTION_TERMS_MAX_CHARS) or inter.terms)
            events.append(self._add_event(WorldEvent(
                round_num, "offer", f"{rname} countered {pname}'s offer [{inter.id}]",
                actors=[rname], targets=[pname], source="interaction", statement=statement,
                option_id=inter.option_id, period_label=label)))
            events.append(self.open_interaction(round_num, inter.recipient, inter.proposer, inter.option_id,
                                                new_terms, kind="counter", parent_id=inter.id))
        else:  # defer: the deadline moves one period, at most twice — then the offer lapses
            inter.deferrals += 1
            if inter.deferrals > INTERACTION_MAX_DEFERRALS:
                inter.status = "lapsed"
                events.append(self._add_event(WorldEvent(
                    round_num, "offer",
                    f"{pname}'s offer to {rname} [{inter.id}] lapsed after repeated deferral: {inter.terms}",
                    actors=[rname], targets=[pname], source="interaction", statement=statement,
                    option_id=inter.option_id, period_label=label)))
            else:
                inter.status = "deferred"
                inter.expires_round = max(inter.expires_round, int(round_num) + 1)
                events.append(self._add_event(WorldEvent(
                    round_num, "offer",
                    f"{rname} deferred its answer to {pname}'s offer [{inter.id}] "
                    f"(open until {self._period_label_for_round(inter.expires_round)})",
                    actors=[rname], targets=[pname], source="interaction", statement=statement,
                    option_id=inter.option_id, period_label=label)))
        return events

    def lapse_expired_interactions(self, round_num: int) -> List[Dict[str, Any]]:
        """Offers nobody answered in time lapse (visible to everyone)."""
        lapsed: List[Dict[str, Any]] = []
        for inter in self.interactions.values():
            if inter.is_open() and inter.expires_round < int(round_num):
                inter.status = "lapsed"
                inter.resolved_round = int(round_num)
                pname, rname = self.actor_name(inter.proposer), self.actor_name(inter.recipient)
                self._add_event(WorldEvent(round_num, "offer",
                                           f"{pname}'s offer to {rname} [{inter.id}] lapsed unanswered: {inter.terms}",
                                           actors=[pname], targets=[rname], source="interaction",
                                           option_id=inter.option_id,
                                           period_label=str((self.period or {}).get("label") or "")))
                lapsed.append(inter.to_dict())
        return lapsed

    def breach_agreements_between(self, round_num: int, breacher: int, other: int, *, cause: str) -> List[WorldEvent]:
        """An explicit withdrawal from every agreement in force between two actors."""
        events: List[WorldEvent] = []
        for inter in self.agreements_between(breacher, other):
            events.append(self._breach(round_num, inter, breacher, cause))
        return events

    def _breach(self, round_num: int, inter: Interaction, breacher: int, cause: str) -> WorldEvent:
        inter.status = "breached"
        inter.resolved_round = int(round_num)
        other = inter.recipient if inter.proposer == int(breacher) else inter.proposer
        for party in (inter.proposer, inter.recipient):
            actor = self.actors.get(party)
            if actor is None:
                continue
            for c in actor.commitments:
                if c.get("id") not in inter.obligations:
                    continue
                if party == int(breacher) and c.get("status") in ("pending", "due", "lapsed"):
                    c["status"] = "breached"
                elif party != int(breacher) and c.get("status") in ("pending", "due"):
                    c["status"] = "released"
        bname, oname = self.actor_name(breacher), self.actor_name(other)
        actor = self.actors.get(int(breacher))
        if actor is not None:
            actor.reputation = _clamp(actor.reputation - 0.15, 0.0, 1.0)
        rel = self._ensure_relationship(int(breacher), other, kind="OPPOSES", round_num=round_num,
                                        basis=f"breach of {inter.id}")
        rel.nudge(-0.3, round_num=round_num, cause=f"{bname} breached the agreement with {oname}")
        return self._add_event(WorldEvent(
            round_num, "breach", f"Breach [{inter.id}]: {bname} broke its agreement with {oname} — {cause}",
            actors=[bname], targets=[oname], source="interaction", option_id=inter.option_id,
            period_label=str((self.period or {}).get("label") or "")))

    def apply_arbiter_update(self, round_num: int, update: Dict[str, Any]) -> Dict[str, Any]:
        """Apply a *validated* arbiter update (see ``world_update.validate_arbiter_update``).

        Returns a summary ``{variables_changed, variables_added, events, relationships_changed,
        effects_added, resolutions}`` for the round record.
        """
        summary = {"variables_changed": [], "variables_added": [], "events": 0,
                   "relationships_changed": [], "effects_added": 0, "resolutions": 0}
        if not isinstance(update, dict):
            return summary
        ratio = self.settings.get("max_change_ratio", DEFAULT_MAX_CHANGE_RATIO)
        try:
            ratio = float(ratio) if ratio is not None else None
        except (TypeError, ValueError):
            ratio = DEFAULT_MAX_CHANGE_RATIO
        label = str((self.period or {}).get("label") or "")
        for ch in update.get("variable_changes") or []:
            if not isinstance(ch, dict):
                continue
            var = self.variables.get(str(ch.get("variable_id") or ""))
            if var is None:
                continue
            before = var.value
            if ch.get("new_value") is not None:
                target = ch["new_value"]
            elif ch.get("delta") is not None and var.kind == "numeric" and isinstance(var.value, (int, float)):
                try:
                    target = float(var.value) + float(ch["delta"])
                except (TypeError, ValueError):
                    continue
            else:
                continue
            if var.set_value(target, round_num=round_num, source="arbiter",
                             cause=ch.get("rationale") or "arbiter", max_change_ratio=ratio):
                summary["variables_changed"].append({"id": var.id, "name": var.name, "from": before,
                                                     "to": var.value, "unit": var.unit})
        for nv in update.get("new_variables") or []:
            if not isinstance(nv, dict) or not nv.get("name"):
                continue
            vid = slugify(nv.get("id") or nv.get("name"))
            if vid in self.variables:
                continue
            self.add_variable(nv["name"], nv.get("value"), unit=nv.get("unit") or "",
                              kind=nv.get("kind") or "numeric", as_of=str((self.period or {}).get("period_end") or ""),
                              provenance="arbiter", rationale=nv.get("rationale") or "", var_id=vid,
                              initial_round=round_num, initial_cause=nv.get("rationale") or "")
            summary["variables_added"].append({"id": vid, "name": self.variables[vid].name,
                                               "value": self.variables[vid].value,
                                               "unit": self.variables[vid].unit})
        for ev in update.get("events") or []:
            if not isinstance(ev, dict) or not _text(ev.get("description"), 320):
                continue
            kind = ev.get("kind") if ev.get("kind") in ("emergent", "consequence", "resolution") else "emergent"
            self._add_event(WorldEvent(round_num, kind, ev["description"], actors=ev.get("actors"),
                                       targets=ev.get("targets"), source="arbiter",
                                       variable_ids=ev.get("variable_ids"), period_label=label))
            summary["events"] += 1
        for rc in update.get("relationship_changes") or []:
            if not isinstance(rc, dict):
                continue
            a = self.resolve_actor(rc.get("source"))
            b = self.resolve_actor(rc.get("target"))
            if a is None or b is None or a == b:
                continue
            direction = _text(rc.get("direction"), 16).casefold()
            delta = {"closer": 0.15, "farther": -0.15, "further": -0.15, "break": -0.35, "ally": 0.25}.get(direction)
            if delta is None:
                continue
            rel = self._ensure_relationship(a, b, kind="ALLY_OF" if delta > 0 else "OPPOSES",
                                            round_num=round_num, basis=rc.get("rationale") or "arbiter")
            moved = rel.nudge(delta, round_num=round_num, cause=rc.get("rationale") or "arbiter")
            summary["relationships_changed"].append({"source": self.actor_name(a), "target": self.actor_name(b),
                                                     "valence": rel.valence, "delta": round(moved, 4)})
        for fx in update.get("pending_effects") or []:
            if not isinstance(fx, dict) or not _text(fx.get("description"), 220):
                continue
            try:
                due = round_num + max(1, int(fx.get("due_periods", 1) or 1))
            except (TypeError, ValueError):
                due = round_num + 1
            vid = fx.get("variable_id")
            if vid is not None and str(vid) not in self.variables:
                vid = None
            op = "add" if fx.get("delta") is not None and fx.get("new_value") is None else "set"
            value = fx.get("delta") if op == "add" else fx.get("new_value")
            self.pending_effects.append(PendingEffect(
                self._next_effect_id(round_num), due_round=due, description=fx["description"],
                variable_id=str(vid) if vid else None, op=op, value=value,
                probability=fx.get("probability", 1.0), source="arbiter",
                targets=fx.get("targets"), created_round=round_num))
            summary["effects_added"] += 1
        for res in update.get("action_resolutions") or []:
            if not isinstance(res, dict):
                continue
            aid = self.resolve_actor(res.get("actor") if res.get("actor") is not None else res.get("agent_id"))
            if aid is None:
                continue
            actor = self.actors[aid]
            outcome = _text(res.get("outcome"), 16).casefold() or "pending"
            if actor.last_action and actor.last_action.get("round") == round_num:
                actor.last_action["resolution"] = outcome
                actor.last_action["resolution_rationale"] = _text(res.get("rationale"), 200)
            if outcome in ("success", "fulfilled"):
                actor.reputation = _clamp(actor.reputation + 0.02, 0.0, 1.0)
            elif outcome in ("blocked", "failed"):
                actor.reputation = _clamp(actor.reputation - 0.05, 0.0, 1.0)
            summary["resolutions"] += 1
        return summary

    def fire_due_effects(self, round_num: int, rng: Any) -> List[Dict[str, Any]]:
        """Resolve pending effects whose round has come (probability via ``rng``)."""
        fired: List[Dict[str, Any]] = []
        keep: List[PendingEffect] = []
        label = str((self.period or {}).get("label") or "")
        for fx in self.pending_effects:
            if fx.due_round > round_num:
                keep.append(fx)
                continue
            roll = 0.0
            if fx.probability < 1.0:
                try:
                    roll = float(rng.random())
                except Exception:  # noqa: BLE001
                    roll = 0.0
            happened = roll < fx.probability
            desc = fx.description if happened else f"Did not materialise: {fx.description}"
            var_ids: List[str] = []
            if happened and fx.variable_id and fx.variable_id in self.variables:
                var = self.variables[fx.variable_id]
                if fx.op == "set":
                    target = fx.value
                elif var.kind == "numeric" and isinstance(var.value, (int, float)):
                    try:
                        target = (float(var.value) + float(fx.value) if fx.op == "add"
                                  else float(var.value) * float(fx.value))
                    except (TypeError, ValueError):
                        target = None
                else:
                    target = None
                if target is not None and var.set_value(target, round_num=round_num, source="effect",
                                                        cause=fx.description):
                    var_ids.append(var.id)
            self._add_event(WorldEvent(round_num, "consequence", desc, targets=fx.targets,
                                       source=fx.source or "effect", variable_ids=var_ids,
                                       period_label=label))
            fired.append({"id": fx.id, "description": desc, "happened": happened,
                          "variable_ids": var_ids})
        self.pending_effects = keep
        return fired

    def lapse_overdue_commitments(self, round_num: int) -> List[Dict[str, Any]]:
        """Commitments due before this round that were never resolved lapse (visible)."""
        lapsed: List[Dict[str, Any]] = []
        for actor in list(self.actors.values()):
            for c in actor.commitments:
                if c.get("status") == "due" and int(c.get("due_round", 0)) < round_num:
                    c["status"] = "lapsed"
                    lapsed.append({"actor": actor.name, **c})
                    self._add_event(WorldEvent(round_num, "consequence",
                                               f"{actor.name}'s commitment lapsed: {c.get('description')}",
                                               actors=[actor.name], source="commitment"))
                    source = str(c.get("source") or "")
                    if source.startswith("agreement:"):
                        # OFFERS: an obligation under an agreement that lapses is a breach
                        inter = self.interactions.get(source.split(":", 1)[1])
                        if inter is not None and inter.status == "accepted":
                            self._breach(round_num, inter, actor.agent_id,
                                         cause=f"its obligation lapsed: {c.get('description')}")
        return lapsed

    def commit_round(self, round_num: int) -> None:
        self.committed_round = int(round_num)

    # -- observation ---------------------------------------------------------------
    def snapshot(self) -> Dict[str, Any]:
        """Compact, comparable view of the world (used for diffs and the record)."""
        return {
            "round": self.round,
            "period": dict(self.period) if self.period else None,
            "variables": {vid: {"name": v.name, "value": v.value, "unit": v.unit, "kind": v.kind}
                          for vid, v in self.variables.items()},
            "relationships": {f"{r.source}->{r.target}": {"valence": r.valence,
                                                           "polarity": round(r.polarity, 4)}
                              for r in self.relationships.values()},
            "pending_effects": len(self.pending_effects),
            "commitments_pending": sum(len(a.pending_commitments()) for a in self.actors.values()),
            "interactions": {iid: it.status for iid, it in self.interactions.items()},
        }

    def diff(self, previous: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Changes since ``previous`` (a ``snapshot()``)."""
        prev_vars = (previous or {}).get("variables") or {}
        prev_rels = (previous or {}).get("relationships") or {}
        changed: List[Dict[str, Any]] = []
        added: List[Dict[str, Any]] = []
        for vid, v in self.variables.items():
            before = prev_vars.get(vid)
            if before is None:
                if previous is not None:
                    added.append({"id": vid, "name": v.name, "value": v.value, "unit": v.unit})
                continue
            if before.get("value") != v.value:
                changed.append({"id": vid, "name": v.name, "from": before.get("value"),
                                "to": v.value, "unit": v.unit})
        rel_changes: List[Dict[str, Any]] = []
        for r in self.relationships.values():
            key = f"{r.source}->{r.target}"
            before = prev_rels.get(key)
            if before is None:
                if previous is not None:
                    rel_changes.append({"source": self.actor_name(r.source), "target": self.actor_name(r.target),
                                        "from": None, "to": r.valence, "polarity": round(r.polarity, 4)})
                continue
            if abs(float(before.get("polarity", 0.0)) - r.polarity) > 1e-9 or before.get("valence") != r.valence:
                rel_changes.append({"source": self.actor_name(r.source), "target": self.actor_name(r.target),
                                    "from": before.get("valence"), "to": r.valence,
                                    "polarity": round(r.polarity, 4),
                                    "direction": "closer" if r.polarity > float(before.get("polarity", 0.0)) else "farther"})
        prev_inter = (previous or {}).get("interactions") or {}
        inter_changes: List[Dict[str, Any]] = []
        for iid, it in self.interactions.items():
            before = prev_inter.get(iid)
            if before == it.status or (before is None and previous is None):
                continue
            inter_changes.append({"id": iid, "from": before, "to": it.status, "kind": it.kind,
                                  "proposer": self.actor_name(it.proposer), "recipient": self.actor_name(it.recipient),
                                  "terms": it.terms})
        return {"variables_changed": changed, "variables_added": added, "relationships_changed": rel_changes,
                "interactions_changed": inter_changes}

    def events_in_round(self, round_num: int, kinds: Optional[Iterable[str]] = None) -> List[WorldEvent]:
        ks = set(kinds) if kinds else None
        return [e for e in self.events if e.round == round_num and (ks is None or e.kind in ks)]

    def _period_label_for_round(self, round_num: int) -> str:
        label = self.period_labels.get(int(round_num))
        if label:
            return label
        if self.period and self.round == round_num and self.period.get("label"):
            return str(self.period["label"])
        return f"period {round_num}"

    def render_public_brief(self, *, upto_round: Optional[int] = None,
                            previous: Optional[Dict[str, Any]] = None,
                            max_chars: int = PUBLIC_BRIEF_MAX_CHARS) -> str:
        """Agent-facing WORLD STATE text (shared by all actors; herding guard I-1).

        ``upto_round`` is the last committed round whose moves/consequences are
        reported; ``previous`` is the snapshot taken before that round so deltas
        can be shown.  Scenario shares are never rendered.
        """
        r = int(upto_round if upto_round is not None else self.committed_round)
        as_of = str((self.period or {}).get("period_end") or self.as_of_date or "")
        label = str((self.period or {}).get("label") or "")
        head = f"# WORLD STATE — as of {as_of}" if as_of else "# WORLD STATE"
        if label and r > 0:
            head += f" (after {label})"
        lines: List[str] = [head]
        diff = self.diff(previous) if previous is not None else {"variables_changed": [], "variables_added": [],
                                                                  "relationships_changed": []}
        changed_ids = {c["id"]: c for c in diff["variables_changed"]}
        if self.variables:
            lines.append("## Key facts")
            ordered = sorted(self.variables.values(),
                             key=lambda v: (0 if v.id in changed_ids else 1,
                                            -(v.history[-1].get("round", 0) if v.history else 0), v.name))
            for v in ordered[:14]:
                line = f"- {v.name}: {format_value(v.value, v.unit)}"
                ch = changed_ids.get(v.id)
                if ch is not None:
                    line += f" (was {format_value(ch['from'], v.unit)} last period)"
                elif v.as_of and v.provenance in ("research", "official"):
                    line += f" (as of {v.as_of})"
                lines.append(line)
        moves = self.events_in_round(r, ("action",)) if r > 0 else []
        if moves:
            lines.append("## Moves last period")
            for e in moves[:10]:
                who = e.actors[0] if e.actors else "An actor"
                stmt = f' — "{_text(e.statement, 160)}"' if e.statement else ""
                lines.append(f"- {who}: {e.description}{stmt}")
        consequences = self.events_in_round(r, ("scheduled", "consequence", "emergent", "resolution")) if r > 0 else []
        if consequences:
            lines.append("## Consequences and events")
            for e in consequences[:10]:
                lines.append(f"- {e.description}")
        rels = diff["relationships_changed"]
        if rels:
            lines.append("## Alliances and rivalries")
            for rc in rels[:8]:
                word = {"allied": "allied", "adversarial": "adversarial", "neutral": "neutral",
                        "transactional": "transactional", "directional": "linked"}.get(rc.get("to"), rc.get("to"))
                direction = rc.get("direction")
                suffix = f" ({direction})" if direction else ""
                lines.append(f"- {rc['source']} — {rc['target']}: now {word}{suffix}")
        deals = self.events_in_round(r, ("offer", "agreement", "breach")) if r > 0 else []
        open_offers = [it for it in self.interactions.values() if it.is_open()]
        if deals or open_offers:
            lines.append("## Offers and agreements")
            for e in deals[:8]:
                lines.append(f"- {e.description}")
            for it in open_offers[:6]:
                if not any(f"[{it.id}]" in e.description for e in deals):
                    lines.append(f"- Open: {self.actor_name(it.proposer)} → {self.actor_name(it.recipient)} [{it.id}]: "
                                 f"{it.terms} (answer due by {self._period_label_for_round(it.expires_round)})")
        pending: List[str] = []
        for actor in self.actors.values():
            for c in actor.pending_commitments():
                pending.append(f"- {actor.name}: {c.get('description')} (due {self._period_label_for_round(int(c.get('due_round', 0)))})")
        for fx in self.pending_effects:
            if fx.description:
                pending.append(f"- Expected: {fx.description} (around {self._period_label_for_round(fx.due_round)})")
        if pending:
            lines.append("## Pending and announced")
            lines.extend(pending[:8])
        return _bound_lines(lines, max_chars)

    def render_private_brief(self, agent_id: int, *, upto_round: Optional[int] = None,
                             max_chars: int = PRIVATE_BRIEF_MAX_CHARS) -> str:
        """Actor-private situation note (its own commitments, consequences aimed at it)."""
        actor = self.actors.get(agent_id)
        if actor is None:
            return ""
        r = int(upto_round if upto_round is not None else self.committed_round)
        lines = [f"# YOUR SITUATION — {actor.name}",
                 f"- Capacity this period: {actor.capacity_remaining}/{actor.capacity_per_round} action units"]
        if actor.last_action:
            la = actor.last_action
            res = la.get("resolution")
            tail = f"; outcome so far: {res}" if res else ""
            lines.append(f"- Your last move ({self._period_label_for_round(int(la.get('round', 0)))}): "
                         f"{la.get('label') or la.get('option_id')}{tail}")
        pend = actor.pending_commitments()
        if pend:
            lines.append("- Your open commitments:")
            for c in pend[:5]:
                flag = " (DUE NOW)" if c.get("status") == "due" else ""
                lines.append(f"  · {c.get('description')} — due {self._period_label_for_round(int(c.get('due_round', 0)))}{flag}")
        offers = self.open_interactions_for(agent_id)
        if offers:
            lines.append("- Offers awaiting YOUR answer (accept, reject, counter or defer this period; unanswered offers lapse):")
            for it in offers[:3]:
                lines.append(f"  · [{it.id}] from {self.actor_name(it.proposer)}: {it.terms} "
                             f"(open until {self._period_label_for_round(it.expires_round)})")
        own = [it for it in self.interactions.values() if it.proposer == agent_id and it.is_open()]
        if own:
            lines.append("- Your offers awaiting an answer: " + "; ".join(
                f"to {self.actor_name(it.recipient)} [{it.id}]: {_text(it.terms, 80)}" for it in own[:3]))
        aimed = [e for e in self.events_in_round(r) if actor.name in e.targets] if r > 0 else []
        if aimed:
            lines.append("- Aimed at you last period:")
            for e in aimed[:5]:
                who = e.actors[0] if e.actors else "someone"
                lines.append(f"  · {who}: {e.description}")
        allies, rivals, changed = [], [], []
        for rel in self.relationships_of(agent_id):
            other = rel.target if rel.source == agent_id else rel.source
            name = self.actor_name(other)
            if rel.valence == "allied":
                allies.append(name)
            elif rel.valence == "adversarial":
                rivals.append(name)
            if rel.last_changed_round == r and r > 0:
                changed.append(f"{name} ({rel.valence})")
        if allies:
            lines.append("- Allies / partners: " + ", ".join(sorted(set(allies))[:8]))
        if rivals:
            lines.append("- Rivals / opponents: " + ", ".join(sorted(set(rivals))[:8]))
        if changed:
            lines.append("- Relationships that moved last period: " + ", ".join(changed[:6]))
        if actor.red_lines:
            lines.append("- Your red lines: " + "; ".join(actor.red_lines[:3]))
        return _bound_lines(lines, max_chars)

    # -- persistence ---------------------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": WORLD_MODEL_STATE_VERSION,
            "question": self.question,
            "as_of_date": self.as_of_date,
            "horizon_date": self.horizon_date,
            "scenarios": list(self.scenarios),
            "settings": dict(self.settings),
            "round": self.round,
            "committed_round": self.committed_round,
            "period": dict(self.period) if self.period else None,
            "scenario_shares": dict(self.scenario_shares),
            "period_labels": {str(k): v for k, v in self.period_labels.items()},
            "variables": [v.to_dict() for v in self.variables.values()],
            "actors": [a.to_dict() for a in self.actors.values()],
            "relationships": [r.to_dict() for r in self.relationships.values()],
            "pending_effects": [fx.to_dict() for fx in self.pending_effects],
            "events": [e.to_dict() for e in self.events[-EVENT_LIMIT:]],
            "effect_seq": self._effect_seq,
            "interactions": [it.to_dict() for it in self.interactions.values()],
            "interaction_seq": self._interaction_seq,
            "seed_gaps": list(self.seed_gaps),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "WorldModel":
        if not isinstance(d, dict):
            raise ValueError("world model state must be an object")
        world = cls(question=d.get("question") or "", as_of_date=d.get("as_of_date"),
                    horizon_date=d.get("horizon_date"), scenarios=d.get("scenarios") or (),
                    settings=d.get("settings") if isinstance(d.get("settings"), dict) else None)
        for row in d.get("actors") or []:
            if isinstance(row, dict):
                world.add_actor(ActorState.from_dict(row))
        for row in d.get("variables") or []:
            if isinstance(row, dict):
                var = StateVariable.from_dict(row)
                world.variables[var.id] = var
        for row in d.get("relationships") or []:
            if isinstance(row, dict):
                world.add_relationship(Relationship.from_dict(row))
        world.pending_effects = [PendingEffect.from_dict(x) for x in (d.get("pending_effects") or []) if isinstance(x, dict)]
        world.events = [WorldEvent.from_dict(x) for x in (d.get("events") or []) if isinstance(x, dict)]
        for row in d.get("interactions") or []:
            if isinstance(row, dict) and row.get("id"):
                inter = Interaction.from_dict(row)
                world.interactions[inter.id] = inter
        world.seed_gaps = [g for g in (d.get("seed_gaps") or []) if isinstance(g, dict)][:32]
        try:
            world.round = int(d.get("round") or 0)
            world.committed_round = int(d.get("committed_round") or 0)
            world._effect_seq = int(d.get("effect_seq") or 0)
            world._interaction_seq = int(d.get("interaction_seq") or 0)
        except (TypeError, ValueError):
            pass
        world.period = dict(d["period"]) if isinstance(d.get("period"), dict) else None
        shares = d.get("scenario_shares")
        if isinstance(shares, dict):
            world.scenario_shares = {str(k): float(v) for k, v in shares.items()
                                     if isinstance(v, (int, float))}
        if isinstance(d.get("period_labels"), dict):
            world.set_period_labels(d["period_labels"])
        return world


def _bound_lines(lines: List[str], max_chars: int) -> str:
    """Join lines and truncate on a line boundary (never mid-line)."""
    out: List[str] = []
    total = 0
    for line in lines:
        line = str(line)
        if total + len(line) + 1 > max_chars:
            if not out:
                return line[: max(0, max_chars - 1)]
            break
        out.append(line)
        total += len(line) + 1
    return "\n".join(out)
