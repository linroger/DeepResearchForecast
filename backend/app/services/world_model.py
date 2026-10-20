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
from datetime import date
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
PROVENANCES = ("research", "official", "seed", "arbiter", "effect", "action", "shock")
VALENCES = ("allied", "adversarial", "transactional", "directional", "neutral")
EVENT_KINDS = ("action", "scheduled", "consequence", "emergent", "resolution", "system",
               "offer", "agreement", "breach", "red_line")
# RED LINES (realism, 2026-10-20): a move the arbiter finds crossing another actor's documented red
# line becomes a ``red_line`` event aimed at that actor (who gets response options next period) and
# pushes the relationship apart.  The reported text must match one of the actor's own red lines.
RED_LINE_MATCH_MIN = 0.5             # share of the red line's content tokens the report must repeat
RED_LINE_NUDGE = -0.25
# TRENDS: a numeric fact that moved the same way in consecutive periods is marked in the public brief
TREND_MIN_PERIODS = 2
# EXOGENOUS SHOCKS (design §2.12, 2026-10-20): researched risks from the seed (``world_model_seed.
# shocks_from_research``) are rolled once per period with the injected RNG at the probability their
# documented per-day hazard gives for the period's length; a fired shock is an ``emergent`` event
# (source ``shock``) whose documented effects move tracked facts under the change clamp, bounded
# against each fact's value before this period's shocks, never across zero.  A shock fires once
# unless the dossier documents it as recurring.  ``settings["shocks_enabled"] is False`` stops firing.
SHOCK_EVENT_SUFFIX = " — a researched risk materialised"
# OFFERS (ported from the world-v1 engine's consent mechanics): a move of one of these
# options aimed at another actor opens an offer that only the recipient's answer can settle.
PROPOSAL_OPTION_IDS = frozenset({"open_talks", "form_alliance", "signal_concession", "sign_agreement",
                                 "partnership_deal", "bargain", "convene", "program_decision"})
RESPONSE_PREFIXES = ("accept:", "reject:", "counter:", "defer:")
FULFILLMENT_PREFIX = "fulfill:"
FULFILLMENT_ACTION_COST = 1
MAX_ACTION_RESOLUTIONS = 24
# OFFERS, mirror-image rule: an ``accept:`` answer adopts the offer's terms verbatim.  When the
# acceptor writes its own ``terms`` the kernel compares them with the offer (``terms_restate_offer``).
# Terms that are empty, a word-bounded fragment of the offer, or too short to state terms of their
# own (fewer than ACCEPT_TERMS_MIN_TOKENS content tokens — "Accepted as proposed") bind as an
# acceptance, as do terms whose content tokens overlap the offer's by at least
# ACCEPT_TERMS_OVERLAP_MIN and that introduce no figure (token with a digit) the offer lacks.
# Anything else — a narrowing, an added condition, a changed number or date — is recorded as a
# counter-offer back to the proposer, never as an agreement.  Live finding 2026-10-17
# (sim_1838cf014c0b): the OPEC Secretariat chose ``accept:`` on Iraq's baseline bargain with terms
# that only acknowledged conformity data, and the kernel bound it to a baseline it never agreed to.
# 0.6 is deliberately strict: a wrongly recorded counter costs one round (the proposer can accept
# it); a wrongly recorded acceptance binds an actor to terms it did not consent to.
ACCEPT_TERMS_OVERLAP_MIN = 0.6
ACCEPT_TERMS_MIN_TOKENS = 3
INTERACTION_TTL_PERIODS = 2          # an unanswered offer lapses after this many periods
INTERACTION_MAX_DEFERRALS = 2        # a deferral moves the deadline one period, at most this often
INTERACTION_TERMS_MAX_CHARS = 300
INTERACTION_LIMIT = 200
COMMITMENT_STATUSES = ("pending", "due", "fulfilled", "lapsed", "withdrawn")

DEFAULT_CAPACITY_PER_ROUND = 2
HISTORY_LIMIT = 48
# ANNOUNCED SETTINGS (realism, 2026-10-20): the change clamp (``max_change_ratio``) keeps the arbiter
# from inventing jumps, but it also made an actor's own announced instrument setting (a tariff raised
# from 20% to 145% in one month, a quota cut to a stated level) take several periods to land.  An
# arbiter change attributed (``caused_by``) to an actor whose move this period was of one of these
# kinds and whose statement or terms state the new value — or the size of the change — applies in
# full; it never crosses zero.  Everything else stays clamped.
ANNOUNCING_KINDS = frozenset({"policy", "economic", "legal", "coalition", "operational"})
ANNOUNCED_FIGURE_TOLERANCE = 0.005   # relative tolerance when matching an announced figure
EVENT_LIMIT = 400
DEFAULT_MAX_CHANGE_RATIO = 0.5
# (raised 2026-10-20 from 2400 / 900 for the track-record and expectation lines)
PUBLIC_BRIEF_MAX_CHARS = 3200
PRIVATE_BRIEF_MAX_CHARS = 1300
# TRACK RECORDS and EXPECTATIONS (reflexivity, 2026-10-20): how an actor's past conduct reads to
# others, and what each actor expected the others to do next.
RESOLUTION_COUNTED = ("success", "partial", "blocked", "failed")
EXPECTATION_LIMIT = 8                 # stored per actor (newest kept)
EXPECTATION_TEXT_MAX_CHARS = 160

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

# terms comparison (``terms_restate_offer``): CJK ideographs / kana / hangul carry no word spaces,
# so they are compared as character bigrams; everything else as casefolded word / digit runs
_CJK_RANGE = "\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af"
_CJK_CHAR_RE = re.compile(f"[{_CJK_RANGE}]")
_TERMS_TOKEN_RE = re.compile(f"[{_CJK_RANGE}]|[^\\W_{_CJK_RANGE}]+")
_OFFER_ID_RE = re.compile(r"\[?\bi\d+_\d+\]?")
# function words and acceptance boilerplate: saying yes to an offer is not stating terms of one's own
_TERMS_STOPWORDS = frozenset((
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "at", "by", "for", "with", "as", "is", "are",
    "be", "will", "that", "this", "it", "its", "we", "our", "you", "your", "i", "s",
    "accept", "accepts", "accepted", "accepting", "acceptance", "agree", "agreed", "agrees", "yes", "ok",
    "okay", "offer", "offers", "proposal", "proposed", "terms", "stated",
    "我们", "我方", "贵方", "对方", "接受", "同意",
    "要约", "提议", "条款", "按照", "如上", "所述",
))


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


def _terms_tokens(text: Any) -> List[str]:
    """Comparable units of an offer's or an answer's terms: NFKC-casefolded word and digit runs,
    CJK runs as character bigrams (a lone character stays itself); offer ids such as ``[i1_1]``
    are dropped so that quoting the id never counts as new content."""
    norm = _OFFER_ID_RE.sub(" ", unicodedata.normalize("NFKC", str(text or "")).casefold())
    out: List[str] = []
    run: List[str] = []

    def flush() -> None:
        if len(run) == 1:
            out.append(run[0])
        elif run:
            out.extend(a + b for a, b in zip(run, run[1:], strict=False))   # bigrams: lengths differ by one
        run.clear()

    for tok in _TERMS_TOKEN_RE.findall(norm):
        if _CJK_CHAR_RE.fullmatch(tok):
            run.append(tok)
        else:
            flush()
            out.append(tok)
    flush()
    return out


def terms_restate_offer(offer_terms: Any, answer_terms: Any) -> bool:
    """True when an acceptor's ``terms`` adopt the offer (so ``accept`` binds), False when they
    differ materially (so the answer is recorded as a counter-offer).  Deterministic, see the
    comment at ``ACCEPT_TERMS_OVERLAP_MIN`` / ``ACCEPT_TERMS_MIN_TOKENS``."""
    answer = _terms_tokens(answer_terms)
    if not answer:
        return True
    offer = _terms_tokens(offer_terms)
    if f" {' '.join(answer)} " in f" {' '.join(offer)} ":      # identical, a prefix or a fragment
        return True
    content = {t for t in answer if t not in _TERMS_STOPWORDS}
    if len(content) < ACCEPT_TERMS_MIN_TOKENS:                  # a bare acknowledgement
        return True
    offered = set(offer)
    if any(t not in offered and any(ch.isdigit() for ch in t) for t in content):
        return False                                            # a figure or date the offer lacks
    return len(content & offered) / len(content) >= ACCEPT_TERMS_OVERLAP_MIN


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


def announced_figures(text: Any) -> List[float]:
    """Every figure a statement states, scaled like ``parse_quantity`` ("145%" → 145,
    "US$2 billion" → 2e9, "1.5 million barrels" → 1.5e6); bounded to the first 24."""
    s = _text(text, 800)
    out: List[float] = []
    for m in _NUMBER_RE.finditer(s):
        num, _ = parse_quantity(s[m.start(): m.start() + 40])
        if num is not None:
            out.append(num)
        if len(out) >= 24:
            break
    return out


def _is_non_move(description: str) -> bool:
    """An ``action`` event that records no move (a hold or a typed non-decision)."""
    return description.endswith(" holds position") or " makes no recorded move" in description


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= 1e-9 + ANNOUNCED_FIGURE_TOLERANCE * max(abs(a), abs(b))


def period_days(period: Optional[Dict[str, Any]]) -> Optional[int]:
    """Calendar days a period covers (both ends included), None when its dates are missing or
    unreadable (same rule as ``decision_channel._period_days``)."""
    if not isinstance(period, dict):
        return None
    try:
        start = date.fromisoformat(str(period.get("period_start") or "")[:10])
        end = date.fromisoformat(str(period.get("period_end") or "")[:10])
    except ValueError:
        return None
    days = (end - start).days + 1
    return days if days > 0 else None


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

    def values_by_round(self) -> Dict[int, Any]:
        """The value at the end of each round in which it was recorded (the last write wins)."""
        out: Dict[int, Any] = {}
        for h in self.history:
            if isinstance(h, dict):
                try:
                    out[int(h.get("round") or 0)] = h.get("value")
                except (TypeError, ValueError):
                    continue
        return out

    def trend(self, upto_round: int) -> Tuple[str, int]:
        """TRENDS: ``("rising" | "falling", n)`` when the value moved the same way in each of the
        ``n`` consecutive periods ending at ``upto_round``; ``("", 0)`` otherwise."""
        if self.kind != "numeric":
            return "", 0
        by_round = self.values_by_round()
        rounds = sorted(by_round)
        direction, n, r = "", 0, int(upto_round)
        while r in by_round:
            earlier = [x for x in rounds if x < r]
            if not earlier:
                break
            before, after = by_round[earlier[-1]], by_round[r]
            if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (before, after)):
                break
            step = "rising" if after > before else "falling" if after < before else ""
            if not step or (direction and step != direction):
                break
            direction, n, r = step, n + 1, r - 1
        return direction, n

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
        # TRACK RECORDS: how the arbiter resolved this actor's moves (counts per outcome)
        self.outcomes: Dict[str, int] = {}
        # EXPECTATIONS: what this actor expected others to do in response to its moves
        # ({round, about, reaction}), compared with what they did in the next period
        self.expectations: List[Dict[str, Any]] = []

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
        sequence = len(self.commitments) + 1
        existing = {c.get("id") for c in self.commitments if isinstance(c.get("id"), str)}
        while f"c{self.agent_id}_{made_round}_{sequence}" in existing:
            sequence += 1
        row = {
            "id": f"c{self.agent_id}_{made_round}_{sequence}",
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

    def track_record(self) -> Dict[str, Any]:
        """TRACK RECORDS: this actor's conduct as the world recorded it — commitments kept / lapsed /
        broken (``released`` ones were the other side's breach), open commitments, how the arbiter
        resolved its moves, and ``reliability`` = kept / resolved (None until one resolves).
        Deterministic; reads only recorded state (the 24 newest commitments)."""
        counts = {"kept": 0, "lapsed": 0, "broken": 0, "released": 0, "open": 0}
        for c in self.commitments:
            key = {"fulfilled": "kept", "lapsed": "lapsed", "breached": "broken", "released": "released",
                   "pending": "open", "due": "open"}.get(c.get("status"))
            if key:
                counts[key] += 1
        resolved = counts["kept"] + counts["lapsed"] + counts["broken"]
        return {**counts, "resolved": resolved,
                "reliability": round(counts["kept"] / resolved, 3) if resolved else None,
                "outcomes": {k: int(self.outcomes[k]) for k in RESOLUTION_COUNTED if self.outcomes.get(k)},
                "reputation": round(self.reputation, 3)}

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
            "outcomes": dict(self.outcomes), "expectations": list(self.expectations),
            # derived (from_dict ignores it): for the /world-state API and the panel
            "track_record": self.track_record(),
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
        outcomes = d.get("outcomes") if isinstance(d.get("outcomes"), dict) else {}
        a.outcomes = {k: int(v) for k, v in outcomes.items()
                      if k in RESOLUTION_COUNTED and isinstance(v, int) and not isinstance(v, bool) and v > 0}
        a.expectations = [e for e in (d.get("expectations") or []) if isinstance(e, dict)][-EXPECTATION_LIMIT:]
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


class Shock:
    """EXOGENOUS SHOCKS: a researched risk that may materialise in any period (seed ``shocks``)."""

    def __init__(self, shock_id: str, *, event: str, hazard_per_day: float,
                 base_rate: Optional[Dict[str, Any]] = None, source: str = "",
                 effects: Optional[List[Dict[str, Any]]] = None, affects: Optional[List[str]] = None,
                 recurring: bool = False, fired_rounds: Optional[List[int]] = None) -> None:
        self.id = _text(shock_id, 64) or "shock"
        self.event = _text(event, 200)
        try:
            hazard = float(hazard_per_day)
        except (TypeError, ValueError):
            hazard = 0.0
        self.hazard_per_day = hazard if math.isfinite(hazard) and hazard > 0 else 0.0
        self.base_rate = dict(base_rate) if isinstance(base_rate, dict) else {}
        self.source = _text(source, 160)
        self.effects = [dict(e) for e in (effects or []) if isinstance(e, dict) and e.get("variable_id")][:4]
        self.affects = _items(affects, 6, 160)
        self.recurring = recurring is True
        self.fired_rounds = [int(r) for r in (fired_rounds or []) if isinstance(r, int) and not isinstance(r, bool)]

    def period_probability(self, days: float) -> float:
        """Probability of firing in a period of ``days`` under the documented constant hazard."""
        return 1.0 - math.exp(-self.hazard_per_day * max(0.0, float(days)))

    def base_rate_text(self) -> str:
        """The documented base rate as written, with its window ("5% per month")."""
        text = _text(self.base_rate.get("text"), 80)
        window = _text(self.base_rate.get("window"), 24).replace("_", " ")
        if not window or window.split(" ")[-1] in text.casefold():
            return text
        if window == "horizon":
            suffix = "over the forecast horizon"
        elif window[:1].isdigit():
            suffix = f"over {window}s"
        else:
            suffix = f"per {window}"
        return f"{text} {suffix}".strip()

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "event": self.event, "hazard_per_day": self.hazard_per_day,
                "base_rate": dict(self.base_rate), "source": self.source,
                "effects": [dict(e) for e in self.effects], "affects": list(self.affects),
                "recurring": self.recurring, "fired_rounds": list(self.fired_rounds)}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Shock":
        return cls(d.get("id") or "", event=d.get("event") or "", hazard_per_day=d.get("hazard_per_day") or 0.0,
                   base_rate=d.get("base_rate"), source=d.get("source") or "", effects=d.get("effects"),
                   affects=d.get("affects"), recurring=d.get("recurring") is True,
                   fired_rounds=d.get("fired_rounds"))


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
        # EXOGENOUS SHOCKS: researched risks rolled once per period (fire_shocks)
        self.shocks: List[Shock] = []

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
        world.shocks = [Shock.from_dict(s) for s in (seed.get("shocks") or []) if isinstance(s, dict)][:8]
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

    def _exact_actor_ids(self, ref: Any) -> set:
        """Candidates for an identity claim, without substring guesses or object coercion."""
        if type(ref) is int:
            return {ref} if ref in self.actors else set()
        if type(ref) is not str:
            return set()
        key = normalize_label(ref)
        if not key:
            return set()
        # Scan all registered names/aliases: the general first-match index hides
        # collisions, which cannot establish a unique delivery identity.
        return {aid for aid, actor in self.actors.items()
                if key == str(aid) or key in actor.name_keys()}

    def resolve_actor(self, ref: Any, *, exact: bool = False) -> Optional[int]:
        """Resolve an agent id or a (possibly aliased, partial) actor name."""
        if exact:
            matches = self._exact_actor_ids(ref)
            return next(iter(matches)) if len(matches) == 1 else None
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

    def delivery_commitment(self, actor_id: int, commitment_id: Any, round_num: int) -> Optional[Dict[str, Any]]:
        """An exact owned open promise, never a semantic guess from a new action."""
        if type(round_num) is not int or round_num != self.round:
            return None
        actor = self.actors.get(actor_id)
        if actor is None or not isinstance(commitment_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,56}", commitment_id):
            return None
        matches = [c for c in actor.commitments if c.get("id") == commitment_id]
        if len(matches) != 1:
            return None
        c = matches[0]
        if (c.get("status") not in ("pending", "due") or not isinstance(c.get("description"), str)
                or not c["description"].strip() or len(c["description"]) > 220):
            return None
        if any(not (type(c.get(key)) is int or isinstance(c.get(key), str) and c[key].isdigit())
               for key in ("made_round", "due_round")):
            return None
        try:
            made, due = int(c["made_round"]), int(c["due_round"])
        except (KeyError, TypeError, ValueError, OverflowError):
            return None
        if isinstance(c["made_round"], bool) or isinstance(c["due_round"], bool) or not (0 <= made < round_num <= due):
            return None
        if str(c.get("source") or "").startswith("agreement:"):
            inter = self.interactions.get(c["source"].split(":", 1)[1])
            if (inter is None or inter.status != "accepted" or actor_id not in (inter.proposer, inter.recipient)
                    or commitment_id not in inter.obligations):
                return None
            other = inter.recipient if actor_id == inter.proposer else inter.proposer
            if (other not in self.actors or type(c.get("counterparty", other)) is not int
                    or c.get("counterparty", other) != other):
                return None
        return c

    def delivery_target_ids(self, actor_id: int, commitment: Dict[str, Any]) -> List[int]:
        source = str(commitment.get("source") or "")
        if source.startswith("agreement:"):
            inter = self.interactions[source.split(":", 1)[1]]
            other = inter.recipient if actor_id == inter.proposer else inter.proposer
            return [other]
        return []

    def delivery_targets(self, actor_id: int, commitment: Dict[str, Any]) -> List[str]:
        return [self.actor_name(aid) for aid in self.delivery_target_ids(actor_id, commitment)]

    def delivery_targets_match(self, actor_id: int, commitment: Dict[str, Any], raw_targets: Any) -> bool:
        if raw_targets is None or raw_targets == []:
            return True  # Omission selects the stored counterparty, never a guessed one.
        if not isinstance(raw_targets, list) or len(raw_targets) > 6:
            return False
        targets = [self.resolve_actor(t, exact=True) for t in raw_targets]
        source = str(commitment.get("source") or "")
        expected = set()
        if source.startswith("agreement:"):
            inter = self.interactions.get(source.split(":", 1)[1])
            if inter is None or actor_id not in (inter.proposer, inter.recipient):
                return False
            expected = {inter.recipient if actor_id == inter.proposer else inter.proposer}
        return all(t is not None and t != actor_id for t in targets) and set(targets) == expected

    def delivery_resolution_target(self, actor_id: int, commitment_id: Any, round_num: int,
                                   action_round: Any) -> Optional[Dict[str, Any]]:
        actor = self.actors.get(actor_id)
        action = actor.last_action if actor is not None else None
        if (type(round_num) is not int or round_num != self.round
                or type(action_round) is not int or action_round != round_num or not action
                or action.get("round") != round_num or action.get("status") != "ok"
                or action.get("commitment_reviewed") or action.get("commitment_id") != commitment_id
                or action.get("option_id") != FULFILLMENT_PREFIX + str(commitment_id)):
            return None
        c = self.delivery_commitment(actor_id, commitment_id, round_num)
        if c is None or action.get("targets") != self.delivery_targets(actor_id, c):
            return None
        if ("commitment_target_ids" in action
                and not self._delivery_target_ids_match(actor_id, c, action["commitment_target_ids"])):
            return None
        attempt = c.get("last_fulfillment_attempt") or {}
        if (not isinstance(attempt, dict) or attempt.get("round") != round_num
                or attempt.get("option_id") != action["option_id"] or attempt.get("outcome") != "unverified"):
            return None
        return c

    def _delivery_target_ids_match(self, actor_id: int, commitment: Dict[str, Any], target_ids: Any) -> bool:
        return (isinstance(target_ids, list) and all(type(aid) is int for aid in target_ids)
                and target_ids == self.delivery_target_ids(actor_id, commitment))

    def resolution_actor(self, row: Dict[str, Any]) -> Tuple[Optional[int], set]:
        """Require exact identity claims; ambiguous aliases implicate every matching actor."""
        refs = [row[key] for key in ("actor", "agent_id") if key in row]
        matches = [self._exact_actor_ids(ref) for ref in refs]
        implicated = set().union(*matches)
        valid = bool(refs) and all(len(ids) == 1 for ids in matches) and len(implicated) == 1
        return (next(iter(implicated)) if valid else None), implicated

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
            delivery = None
            if option_id.startswith(FULFILLMENT_PREFIX):
                if self.resolve_actor(d.get("agent_id"), exact=True) != aid:
                    continue  # A guessed actor reference cannot bind or spend an owned promise.
                if (type(round_num) is not int or round_num != self.round
                        or type(d.get("round")) is not int or d["round"] != round_num):
                    continue  # Never relabel a saved decision as a new delivery attempt.
                if any(isinstance(c.get("last_fulfillment_attempt"), dict)
                       and c["last_fulfillment_attempt"].get("round") == int(round_num) for c in actor.commitments):
                    continue  # Re-registration cannot reset a reviewed attempt or spend/credit it twice.
                delivery = self.delivery_commitment(aid, option_id[len(FULFILLMENT_PREFIX):], int(round_num))
                targets_match = delivery is not None and self.delivery_targets_match(aid, delivery, d.get("targets"))
                if delivery is not None and "commitment_target_ids" in option:
                    # Parsed decisions carry names for display and IDs for binding.
                    # A canonical display name may be shared, but it never replaces
                    # the exact stored counterparty ID or legitimizes a guessed name.
                    targets_match = (self._delivery_target_ids_match(aid, delivery, option["commitment_target_ids"])
                                     and (targets_match or d.get("targets") == self.delivery_targets(aid, delivery)))
                if (status != "ok" or delivery is None or actor.capacity_remaining < FULFILLMENT_ACTION_COST
                        or not targets_match):
                    delivery = None
                    status = status if status != "ok" else "invalid"
                else:
                    target_names = self.delivery_targets(aid, delivery)
                    targets = self.delivery_target_ids(aid, delivery)
                option = {"id": option_id, "label": f"Deliver commitment [{option_id[len(FULFILLMENT_PREFIX):]}]: "
                          + (_text(delivery.get("description"), 220) if delivery else "invalid delivery attempt"),
                          "kind": "operational", "cost": FULFILLMENT_ACTION_COST if delivery else 0,
                          "lag": 0, "reversibility": "reversible"}
                kind = "operational"
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
            announced_terms = _text(d.get("terms"), INTERACTION_TERMS_MAX_CHARS)
            if not announced_terms and option_id.startswith("accept:"):
                # an acceptance adopts the offer's terms verbatim (mirror-image rule)
                accepted = self.interactions.get(option_id.partition(":")[2])
                announced_terms = accepted.terms if accepted is not None else ""
            actor.last_action = {
                "round": int(round_num), "option_id": option_id, "kind": kind,
                "label": _text(option.get("label"), 160), "targets": target_names,
                "magnitude": round(magnitude, 3), "status": status, "resolution": None,
                "reversibility": _text(option.get("reversibility"), 24),
                "statement": _text(d.get("public_statement"), 320), "terms": announced_terms,
            }
            if delivery is not None:
                actor.last_action.update(commitment_id=delivery["id"],
                                         commitment_description=delivery.get("description"),
                                         commitment_target_ids=self.delivery_target_ids(aid, delivery), resolution="pending")
                delivery["last_fulfillment_attempt"] = {"round": int(round_num), "option_id": option_id,
                                                       "outcome": "unverified"}
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
            self._record_expectations(actor, round_num, d.get("expected_reactions"))
            if delivery is not None:
                # Selection is an attempt, not delivery or a fresh pledge/alliance.
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
        accept_as_counter = False
        if verb == "accept" and not terms_restate_offer(inter.terms, terms):
            # OFFERS, mirror-image rule: an acceptance on materially different terms is a
            # counter-offer — the acceptor never agreed to the proposer's text (ACCEPT_TERMS_*)
            verb, accept_as_counter = "counter", True
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
            if accept_as_counter:
                # (the round record lists this under offers_answered: no " made an " in the text)
                description = (f"{rname} answered {pname}'s offer [{inter.id}] with different terms — recorded "
                               f"as a counter-offer, not an acceptance, because accept adopts the offer's terms "
                               f"verbatim")
            else:
                description = f"{rname} countered {pname}'s offer [{inter.id}]"
            events.append(self._add_event(WorldEvent(
                round_num, "offer", description,
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

    # -- track records and expectations (reflexivity) -------------------------------
    def _record_expectations(self, actor: ActorState, round_num: int, raw: Any) -> None:
        """EXPECTATIONS: keep what ``actor`` expects named cast members to do in response."""
        for row in (raw if isinstance(raw, list) else [])[:4]:
            if not isinstance(row, dict):
                continue
            about = self.resolve_actor(row.get("actor"))
            reaction = _text(row.get("reaction"), EXPECTATION_TEXT_MAX_CHARS)
            if about is None or about == actor.agent_id or not reaction:
                continue
            actor.expectations.append({"round": int(round_num), "about": self.actor_name(about),
                                       "reaction": reaction})
        actor.expectations = actor.expectations[-EXPECTATION_LIMIT:]

    def track_record(self, agent_id: int) -> Dict[str, Any]:
        """TRACK RECORDS for ``agent_id`` (``ActorState.track_record``); {} for an unknown actor."""
        actor = self.actors.get(agent_id)
        return actor.track_record() if actor is not None else {}

    def track_record_text(self, agent_id: int) -> str:
        """One line for briefs and the arbiter, "" while nothing has been resolved."""
        rec = self.track_record(agent_id)
        parts: List[str] = []
        if rec.get("resolved"):
            failed = [f"{rec[k]} {word}" for k, word in (("lapsed", "lapsed"), ("broken", "broken")) if rec.get(k)]
            parts.append(f"kept {rec['kept']} of {rec['resolved']} commitments"
                         + (f" ({', '.join(failed)})" if failed else ""))
        outcomes = rec.get("outcomes") or {}
        if outcomes:
            words = {"success": "succeeded", "partial": "partly succeeded", "blocked": "blocked", "failed": "failed"}
            parts.append("moves " + ", ".join(f"{n} {words[k]}" for k, n in outcomes.items()))
        return "; ".join(parts)

    def expectation_checks(self, agent_id: int, upto_round: int) -> List[Dict[str, Any]]:
        """EXPECTATIONS vs what happened: what ``agent_id`` expected others to do after its moves
        in period ``upto_round - 1``, next to what they did in ``upto_round`` (the reaction comes
        one period later: moves within a period are simultaneous)."""
        actor = self.actors.get(agent_id)
        if actor is None or upto_round < 2:
            return []
        out: List[Dict[str, Any]] = []
        for exp in actor.expectations:
            if int(exp.get("round") or 0) != int(upto_round) - 1:
                continue
            about = str(exp.get("about") or "")
            moves = [e for e in self.events_in_round(upto_round, ("action", "offer", "agreement", "breach"))
                     if e.actors and e.actors[0] == about]
            moved = [e for e in moves if not (e.kind == "action" and _is_non_move(e.description))]
            actual = moved or moves
            out.append({"made_round": int(exp.get("round") or 0), "about": about,
                        "expected": str(exp.get("reaction") or ""),
                        "actual": "; ".join(_text(e.description, 140) for e in actual[:2]) or "made no recorded move",
                        "reacted": bool(moved),
                        "aimed_at_you": any(actor.name in e.targets for e in moved)})
        return out

    # -- red lines --------------------------------------------------------------------
    def match_red_line(self, agent_id: int, text: Any) -> Optional[str]:
        """The documented red line of ``agent_id`` that ``text`` refers to, else None: the text equals
        or contains it, is a fragment covering at least 60% of it, or repeats at least
        RED_LINE_MATCH_MIN of its content tokens."""
        actor = self.actors.get(agent_id)
        wanted = normalize_label(text)
        if actor is None or not wanted:
            return None
        said = {t for t in _terms_tokens(wanted) if t not in _TERMS_STOPWORDS}
        best: Optional[Tuple[float, str]] = None
        for line in actor.red_lines:
            key = normalize_label(line)
            # the report quotes the whole red line, or most of it (a bare keyword is not a red line)
            if key == wanted or key in wanted or (wanted in key and len(wanted) >= 0.6 * len(key)):
                return line
            tokens = {t for t in _terms_tokens(key) if t not in _TERMS_STOPWORDS}
            if tokens:
                share = len(tokens & said) / len(tokens)
                if share >= RED_LINE_MATCH_MIN and (best is None or share > best[0]):
                    best = (share, line)
        return best[1] if best else None

    def cross_red_line(self, round_num: int, actor_ref: Any, by_ref: Any, red_line: Any, *,
                       rationale: str = "") -> Optional[Dict[str, Any]]:
        """RED LINES: record that ``by`` crossed ``actor``'s documented red line with its move this
        period.  Returns the record, or None when the report does not hold up (unknown or identical
        actors, ``by`` made no move this period, or the text matches none of the actor's red lines)."""
        aid, bid = self.resolve_actor(actor_ref), self.resolve_actor(by_ref)
        if aid is None or bid is None or aid == bid:
            return None
        move = self.actors[bid].last_action
        if (not isinstance(move, dict) or int(move.get("round") or 0) != int(round_num)
                or move.get("status") != "ok" or move.get("option_id") == "hold_position"):
            return None
        line = self.match_red_line(aid, red_line)
        if line is None:
            return None
        aname, bname = self.actor_name(aid), self.actor_name(bid)
        rel = self._ensure_relationship(bid, aid, kind="OPPOSES", round_num=round_num,
                                        basis=f"crossed a red line in round {round_num}")
        rel.nudge(RED_LINE_NUDGE, round_num=round_num, cause=f"{bname} crossed {aname}'s red line")
        why = _text(rationale, 160)
        self._add_event(WorldEvent(
            round_num, "red_line", f"{bname} crossed {aname}'s red line: {line}" + (f" — {why}" if why else ""),
            actors=[bname], targets=[aname], source="arbiter", option_id=_text(move.get("option_id"), 64),
            period_label=str((self.period or {}).get("label") or "")))
        return {"actor": aname, "by": bname, "red_line": line}

    def change_ratio(self) -> Optional[float]:
        """Per-period bound on how far the arbiter or a delayed effect may move a numeric fact."""
        ratio = self.settings.get("max_change_ratio", DEFAULT_MAX_CHANGE_RATIO)
        try:
            return float(ratio) if ratio is not None else None
        except (TypeError, ValueError):
            return DEFAULT_MAX_CHANGE_RATIO

    def _announced_by(self, caused_by: Any, var: StateVariable, target: Any,
                      round_num: int) -> Optional[ActorState]:
        """The actor whose move this period announced ``target`` for ``var`` (ANNOUNCED SETTINGS),
        else None.  Requires: ``caused_by`` resolves to an actor whose recorded move this period is
        ok, not a hold and of an ``ANNOUNCING_KINDS`` kind; its statement or terms state the new
        value or the size of the change; and the change does not cross zero."""
        if caused_by is None or var.kind != "numeric" or not isinstance(var.value, (int, float)):
            return None
        aid = self.resolve_actor(caused_by)
        actor = self.actors.get(aid) if aid is not None else None
        move = actor.last_action if actor is not None else None
        if (not isinstance(move, dict) or int(move.get("round") or 0) != int(round_num)
                or move.get("status") != "ok" or move.get("option_id") == "hold_position"
                or move.get("kind") not in ANNOUNCING_KINDS):
            return None
        try:
            new, cur = float(target), float(var.value)
        except (TypeError, ValueError):
            return None
        if (cur > 0 > new) or (cur < 0 < new):
            return None
        figures = announced_figures(f"{move.get('statement') or ''} {move.get('terms') or ''}")
        wanted = (new, abs(new - cur))
        if any(_close(f, w) for f in figures for w in wanted if w != 0 or f == 0):
            return actor
        return None

    def apply_arbiter_update(self, round_num: int, update: Dict[str, Any]) -> Dict[str, Any]:
        """Apply a *validated* arbiter update (see ``world_update.validate_arbiter_update``).

        Returns a summary ``{variables_changed, variables_added, events, relationships_changed,
        effects_added, resolutions}`` for the round record.
        """
        summary = {"variables_changed": [], "variables_added": [], "events": 0,
                   "relationships_changed": [], "effects_added": 0, "resolutions": 0,
                   "commitments_fulfilled": 0, "red_lines_crossed": []}
        if not isinstance(update, dict):
            return summary
        ratio = self.change_ratio()
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
            announcer = self._announced_by(ch.get("caused_by"), var, target, round_num)
            if announcer is not None:
                # ANNOUNCED SETTINGS: the actor's own stated figure lands in full this period
                changed = var.set_value(target, round_num=round_num, source="action",
                                        cause=f"{announcer.name} announced it: {ch.get('rationale') or 'arbiter'}")
            else:
                changed = var.set_value(target, round_num=round_num, source="arbiter",
                                        cause=ch.get("rationale") or "arbiter", max_change_ratio=ratio)
            if changed:
                row = {"id": var.id, "name": var.name, "from": before, "to": var.value, "unit": var.unit}
                if announcer is not None:
                    row["announced_by"] = announcer.name
                summary["variables_changed"].append(row)
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
        for rl in update.get("red_line_crossings") or []:
            crossed = self.cross_red_line(round_num, rl.get("actor"), rl.get("by"), rl.get("red_line"),
                                          rationale=rl.get("rationale") or "") if isinstance(rl, dict) else None
            if crossed is not None:
                summary["red_lines_crossed"].append(crossed)
        resolutions = update.get("action_resolutions") or []
        if not isinstance(resolutions, list) or len(resolutions) > MAX_ACTION_RESOLUTIONS:
            resolutions = []
        counts: Dict[int, int] = {}
        for res in resolutions:
            if isinstance(res, dict):
                _, implicated = self.resolution_actor(res)
                for aid in implicated:
                    counts[aid] = counts.get(aid, 0) + 1
        for res in resolutions:
            if not isinstance(res, dict):
                continue
            aid, _ = self.resolution_actor(res)
            if aid is None or counts.get(aid) != 1:
                continue
            actor = self.actors[aid]
            outcome = _text(res.get("outcome"), 16).casefold() or "pending"
            rationale = _text(res.get("rationale"), 200)
            delivery = None
            is_delivery = bool(actor.last_action and str(actor.last_action.get("option_id", "")).startswith(FULFILLMENT_PREFIX))
            if is_delivery or res.get("commitment_id") is not None:
                delivery = self.delivery_resolution_target(aid, res.get("commitment_id"), round_num, res.get("action_round"))
                if (delivery is None or not isinstance(res.get("rationale"), str) or not rationale
                        or not isinstance(res.get("outcome"), str) or not res["outcome"].strip()
                        or outcome not in ("success", "partial", "blocked", "pending", "failed")):
                    continue  # A rejected attestation cannot earn generic reputation credit.
                evidence = {"round": int(round_num), "agent_id": aid, "commitment_id": delivery["id"],
                            "option_id": actor.last_action["option_id"], "outcome": outcome, "rationale": rationale}
                actor.last_action["commitment_reviewed"] = True
                delivery["last_fulfillment_attempt"] = dict(evidence)
                if outcome == "success":
                    delivery.update(status="fulfilled", fulfilled_round=int(round_num), fulfillment_evidence=dict(evidence))
                    self._add_event(WorldEvent(round_num, "resolution",
                        f"{actor.name} fulfilled commitment [{delivery['id']}]: {delivery.get('description')}",
                        actors=[actor.name], targets=self.delivery_targets(aid, delivery), source="commitment",
                        option_id=actor.last_action["option_id"], period_label=label))
                    summary["commitments_fulfilled"] += 1
                    summary["events"] += 1
            if actor.last_action and actor.last_action.get("round") == round_num:
                actor.last_action["resolution"] = outcome
                actor.last_action["resolution_rationale"] = _text(res.get("rationale"), 200)
            if outcome in RESOLUTION_COUNTED:
                actor.outcomes[outcome] = int(actor.outcomes.get(outcome, 0)) + 1
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
                # a delayed consequence is as bounded as an immediate one (the clamp used to be
                # skipped here, so a scheduled effect could move a fact without limit)
                if target is not None and var.set_value(target, round_num=round_num, source="effect",
                                                        cause=fx.description,
                                                        max_change_ratio=self.change_ratio()):
                    var_ids.append(var.id)
            self._add_event(WorldEvent(round_num, "consequence", desc, targets=fx.targets,
                                       source=fx.source or "effect", variable_ids=var_ids,
                                       period_label=label))
            fired.append({"id": fx.id, "description": desc, "happened": happened,
                          "variable_ids": var_ids})
        self.pending_effects = keep
        return fired

    def fire_shocks(self, round_num: int, rng: Any) -> List[Dict[str, Any]]:
        """EXOGENOUS SHOCKS: roll every eligible shock once for this period (seed order, one draw each,
        so a given RNG reproduces the same firings); a fired shock becomes an ``emergent`` event and
        applies its documented effects (see the comment at ``SHOCK_EVENT_SUFFIX``).  Returns one row per
        fired shock for the round record and the arbiter."""
        if not self.shocks or self.settings.get("shocks_enabled", True) is False:
            return []
        days = period_days(self.period)
        if days is None:
            return []
        ratio = self.change_ratio()
        label = str((self.period or {}).get("label") or "")
        base: Dict[str, Any] = {}
        fired: List[Dict[str, Any]] = []
        for shock in self.shocks:
            if shock.fired_rounds and not shock.recurring:
                continue
            p = shock.period_probability(days)
            try:
                roll = float(rng.random())
            except Exception:  # noqa: BLE001
                continue
            if roll >= p:
                continue
            shock.fired_rounds.append(int(round_num))
            changed: List[Dict[str, Any]] = []
            var_ids: List[str] = []
            to_size: List[str] = []
            for fx in shock.effects:
                var = self.variables.get(str(fx.get("variable_id") or ""))
                if var is None:
                    continue
                if fx.get("op") not in ("set", "add", "mul"):
                    if fx.get("direction") in ("up", "down"):
                        to_size.append(f"{var.name} {fx['direction']}")   # documented direction only
                    continue
                before = var.value
                target = _shock_target(var, fx["op"], fx.get("value"), base.setdefault(var.id, var.value), ratio)
                if target is not None and var.set_value(target, round_num=round_num, source="shock",
                                                        cause=f"shock: {shock.event}", max_change_ratio=ratio):
                    var_ids.append(var.id)
                    changed.append({"id": var.id, "name": var.name, "from": before, "to": var.value,
                                    "unit": var.unit})
            targets = [self.actor_name(a) for a in (self.resolve_actor(n) for n in shock.affects) if a is not None]
            self._add_event(WorldEvent(round_num, "emergent", f"{shock.event}{SHOCK_EVENT_SUFFIX}", targets=targets,
                                       source="shock", variable_ids=var_ids, period_label=label))
            fired.append({"id": shock.id, "event": shock.event, "probability": round(p, 6),
                          "base_rate": shock.base_rate_text(), "source": shock.source,
                          "variables_changed": changed, "to_size": to_size, "affects": targets})
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
                notes: List[str] = []
                ch = changed_ids.get(v.id)
                if ch is not None:
                    notes.append(f"was {format_value(ch['from'], v.unit)} last period")
                elif v.as_of and v.provenance in ("research", "official"):
                    notes.append(f"as of {v.as_of}")
                direction, periods = v.trend(r) if r > 0 else ("", 0)
                if periods >= TREND_MIN_PERIODS:
                    notes.append(f"{direction} {periods} periods running")
                lines.append(f"- {v.name}: {format_value(v.value, v.unit)}" + (f" ({'; '.join(notes)})" if notes else ""))
        moves = self.events_in_round(r, ("action",)) if r > 0 else []
        if moves:
            lines.append("## Moves last period")
            for e in moves[:10]:
                who = e.actors[0] if e.actors else "An actor"
                stmt = f' — "{_text(e.statement, 160)}"' if e.statement else ""
                lines.append(f"- {who}: {e.description}{stmt}")
        consequences = (self.events_in_round(r, ("scheduled", "consequence", "emergent", "resolution", "red_line"))
                        if r > 0 else [])
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
        records = []
        for actor in self.actors.values():
            text = self.track_record_text(actor.agent_id)
            if text:
                rec = self.track_record(actor.agent_id)
                records.append((-(rec.get("lapsed", 0) + rec.get("broken", 0)), -rec.get("resolved", 0),
                                actor.name, text))
        if records:
            # TRACK RECORDS: counterparts discount the threats and promises of actors who broke theirs
            lines.append("## Track records")
            lines.extend(f"- {name}: {text}" for _, _, name, text in sorted(records)[:6])
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
                 f"- Capacity this period: {actor.capacity_remaining}/{actor.capacity_per_round} action units",
                 f"- Your simulated credibility (0–1): {actor.reputation:.2f}"]
        # Outcome evidence precedes expandable promises, so it survives the
        # normal private-brief budget even when the actor has many open duties.
        outcomes = [e for e in self.events_in_round(r, ("resolution", "consequence", "breach"))
                    if (e.source == "commitment" or e.kind == "breach")
                    and (actor.name in e.actors or actor.name in e.targets)] if r > 0 else []
        if outcomes:
            lines.append("- Your commitment outcomes last period:")
            lines.extend(f"  · {_text(e.description, 220)}" for e in reversed(outcomes[-2:]))
        if actor.last_action:
            la = actor.last_action
            res = la.get("resolution")
            tail = f"; outcome so far: {res}" if res else ""
            lines.append(f"- Your last move ({self._period_label_for_round(int(la.get('round', 0)))}): "
                         f"{la.get('label') or la.get('option_id')}{tail}")
        record = self.track_record_text(agent_id)
        if record:
            lines.append(f"- Your track record as others see it: {record}")
        pend = actor.pending_commitments()
        if pend:
            lines.append("- Your open commitments:")
            for c in pend[:5]:
                flag = (" (OVERDUE)" if int(c.get("due_round", 0)) < self.round else " (DUE NOW)") if c.get("status") == "due" else ""
                lines.append(f"  · [{c.get('id')}] {c.get('description')} — due {self._period_label_for_round(int(c.get('due_round', 0)))}{flag}")
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
                if e.source == "shock" and not e.actors:
                    lines.append(f"  · {e.description}")   # EXOGENOUS SHOCKS: nobody's move
                    continue
                who = e.actors[0] if e.actors else "someone"
                lines.append(f"  · {who}: {e.description}")
        checks = self.expectation_checks(agent_id, r)
        if checks:
            # EXPECTATIONS: the actor learns where its picture of the others was wrong
            lines.append("- What you expected vs what happened:")
            for c in checks[:3]:
                lines.append(f"  · {c['about']}: you expected \"{_text(c['expected'], 100)}\"; "
                             f"it did: {_text(c['actual'], 140)}")
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
            # EXOGENOUS SHOCKS: only when the seed documented some (a world without shocks serialises
            # exactly as before)
            **({"shocks": [s.to_dict() for s in self.shocks]} if self.shocks else {}),
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
        world.shocks = [Shock.from_dict(s) for s in (d.get("shocks") or []) if isinstance(s, dict)][:8]
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


def _shock_target(var: StateVariable, op: str, value: Any, base_value: Any, ratio: Optional[float]) -> Any:
    """EXOGENOUS SHOCKS: the value a documented effect moves ``var`` to, bounded against the value
    before this period's shocks (``base_value``) by the change clamp and never across zero; None when
    the effect cannot apply to this fact."""
    if var.kind != "numeric" or not isinstance(var.value, (int, float)):
        return _text(value, 160) or None if op == "set" else None
    try:
        size, cur = float(value), float(var.value)
    except (TypeError, ValueError):
        return None
    target = size if op == "set" else cur + size if op == "add" else cur * size
    if not math.isfinite(target):
        return None
    base = float(base_value) if isinstance(base_value, (int, float)) and not isinstance(base_value, bool) else cur
    if ratio and base != 0:
        cap = abs(base) * float(ratio)
        target = _clamp(target, base - cap, base + cap)
    if (base > 0 > target) or (base < 0 < target):
        target = 0.0
    return target


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
