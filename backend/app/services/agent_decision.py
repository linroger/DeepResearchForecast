"""Structured per-round strategic decisions for simulation actors (design §2.4).

An actor's round used to be one free-text post.  This module gives every
deciding actor a realistic, motivated option set and elicits ONE structured
decision per round:

* ``AGENCY_CLASSES`` and ``infer_agency_class`` map a researched actor
  (government, regulator, firm, union, NGO, individual leader…) to the levers it
  realistically holds.
* ``ACTION_CATALOG`` lists the catalogued action templates per agency class
  (kind, capacity cost, lag until the effect lands, reversibility).
* ``build_option_menu`` grounds the menu in the world: responses to moves aimed
  at the actor, the actor's own documented plans, class options filtered by the
  capacity it has left, and ``hold_position``.
* ``build_decision_prompt`` / ``parse_decision`` turn the menu into a bounded
  JSON contract and validate the model's answer; any failure degrades to
  ``hold_position`` with a typed status (``failed`` / ``invalid`` /
  ``language_mismatch``) so a dead decision step is never mistaken for
  strategic patience.  A public statement whose script does not match the run
  language (CJK vs Latin) is rejected for publication the same way, and every
  typed non-decision carries its ``problems`` into ``world_actions.jsonl``.

Pure except for the injected ``llm.chat_json`` call in ``elicit_decision``.
"""

from __future__ import annotations

import json
import logging
import json
import re
import unicodedata
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ..utils.llm_errors import describe_llm_error
from .world_model import (ActorState, FULFILLMENT_ACTION_COST, FULFILLMENT_PREFIX,
                          INTERACTION_TERMS_MAX_CHARS, PROPOSAL_OPTION_IDS, WorldModel,
                          _text, normalize_label, validate_operative_terms)

logger = logging.getLogger(__name__)

DECISION_CONTRACT_VERSION = "world-decision/v1"
ABSTAIN = "abstain"
HOLD_OPTION_ID = "hold_position"
MAX_OPTIONS = 10
# 2026-10-21: 取消 UI 可见文本的截断（用户明确要求 digest/feed/moves/consequences 不裁剪）。
# 480→4000：public_statement 直接进 feed 帖子与世界状态事件语句，此前 480+"…" 截断
# 到处可见。上限保留为病理防护，正常声明（数百字符）永不触顶。
STATEMENT_MAX_CHARS = 4000
RATIONALE_MAX_CHARS = 2000
LANGUAGE_MISMATCH = "language_mismatch"
DECISION_STATUSES = ("ok", "invalid", "failed", LANGUAGE_MISMATCH)
MAX_PROBLEMS = 6
DECISION_ERROR_SNIPPET_CHARS = 200

# Script heuristic for the run-language check: CJK ideographs / kana / hangul against Latin
# letters.  One CJK character carries about three Latin letters' worth of text — the same
# weighting the runner uses to infer the run language from the forecast question — so a
# Latin statement that merely quotes a Chinese name stays Latin, and vice versa.
_CJK_CHAR_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]")
_LATIN_CHAR_RE = re.compile(r"[A-Za-z\u00c0-\u024f]")
_CJK_LANGUAGE_CODES = ("zh", "cn", "ja", "jp", "ko", "kr")
_CJK_LANGUAGE_WORDS = ("chinese", "mandarin", "cantonese", "japanese", "korean", "中文", "汉语", "汉文", "普通话",
                       "简体", "繁體", "繁体", "日本語", "日语", "한국어", "韩语")
_LATIN_LANGUAGE_CODES = ("en", "es", "fr", "de", "pt", "it", "nl")
_LATIN_LANGUAGE_WORDS = ("english", "spanish", "español", "espanol", "french", "français", "francais", "german",
                         "deutsch", "portuguese", "português", "portugues", "italian", "italiano", "dutch",
                         "nederlands", "英文", "英语")

ACTION_KINDS = ("policy", "economic", "coalition", "communication", "legal", "coercive",
                "operational", "wait")

AGENCY_CLASSES: Tuple[str, ...] = (
    "sovereign_government", "regulator_agency", "legislature", "central_bank", "judiciary",
    "political_party", "firm", "state_owned_enterprise", "financial_institution",
    "industry_coalition", "labor_union", "ngo_advocacy", "international_org",
    "research_institution", "individual_leader", "public_collective", "media_outlet",
    "other_actor",
)

DEFAULT_CAPACITY_BY_CLASS: Dict[str, int] = {
    "sovereign_government": 3, "regulator_agency": 2, "legislature": 2, "central_bank": 2,
    "judiciary": 1, "political_party": 2, "firm": 2, "state_owned_enterprise": 2,
    "financial_institution": 2, "industry_coalition": 2, "labor_union": 2, "ngo_advocacy": 1,
    "international_org": 2, "research_institution": 1, "individual_leader": 2,
    "public_collective": 1, "media_outlet": 1, "other_actor": 2,
}

# (keywords, class) — first match wins; order from specific to generic.
_AGENCY_HINTS: Tuple[Tuple[Tuple[str, ...], str], ...] = (
    (("central bank", "federal reserve", "the fed", "fed", "fomc", "ecb", "people's bank", "pboc", "boj",
      "bank of england", "monetary authority", "央行", "中央银行", "人民银行", "联储"), "central_bank"),
    (("supreme court", "court of", "tribunal", "judiciary", "judge", "法院", "法官", "仲裁"), "judiciary"),
    (("regulator", "regulatory", "commission", "authority", "agency", "administration", "fcc", "sec ",
      "ftc", "doj", "antitrust", "watchdog", "监管", "管理局", "委员会", "总局", "监察"), "regulator_agency"),
    (("parliament", "congress", "senate", "senator", "congressman", "congresswoman", "lawmaker",
      "house of representatives", "legislature", "legislator", "assembly", "bundestag", "diet",
      "议会", "国会", "参议院", "众议院", "立法", "议员"), "legislature"),
    (("government", "ministry", "minister", "president", "prime minister", "cabinet", "white house",
      "administration of", "state council", "kremlin", "treasury", "department of", "政府", "国务院",
      "部长", "总统", "总理", "内阁", "财政部", "外交部", "商务部"), "sovereign_government"),
    (("party", "campaign", "candidate", "coalition government", "政党", "候选人", "竞选"), "political_party"),
    (("imf", "world bank", "united nations", " un ", "wto", "oecd", "nato", "european union",
      "european commission", "asean", "opec", "g7", "g20", "国际组织", "联合国", "世贸", "欧盟", "欧佩克"),
     "international_org"),
    (("union", "workers", "labor", "labour", "federation of", "guild", "工会", "工人"), "labor_union"),
    (("association", "alliance", "industry group", "chamber of commerce", "consortium", "trade group",
      "lobby", "协会", "商会", "联盟", "行业组织"), "industry_coalition"),
    (("ngo", "non-profit", "nonprofit", "foundation", "advocacy", "watch", "activist", "rights group",
      "greenpeace", "amnesty", "非政府", "基金会", "公益", "维权"), "ngo_advocacy"),
    (("university", "institute", "laboratory", "lab ", "research", "think tank", "academy", "大学",
      "研究所", "研究院", "实验室", "智库"), "research_institution"),
    (("newspaper", "news", "media", "broadcaster", "journalist", "reporter", "press", "times",
      "post", "journal", "媒体", "报", "新闻", "记者", "电视台"), "media_outlet"),
    (("bank", "fund", "capital", "asset management", "investors", "insurer", "exchange", "brokerage",
      "银行", "基金", "资本", "投资者", "交易所", "保险"), "financial_institution"),
    (("state-owned", "state owned", "soe", "national oil", "国企", "国有", "中石", "国家电网"),
     "state_owned_enterprise"),
    (("corporation", "company", "inc", "ltd", "llc", "plc", "group", "holdings", "technologies",
      "motors", "semiconductor", "manufacturer", "supplier", "startup", "firm", "enterprise",
      "公司", "集团", "企业", "厂商", "制造商"), "firm"),
    (("ceo", "founder", "chairman", "executive", "governor", "mayor", "senator", "secretary",
      "leader", "director", "spokesperson", "influencer", "commentator", "person",
      "首席执行官", "创始人", "董事长", "州长", "市长", "参议员", "领导人", "个人"), "individual_leader"),
    (("public", "consumers", "voters", "citizens", "residents", "community", "fans", "users",
      "households", "farmers", "patients", "students", "公众", "消费者", "选民", "市民", "居民",
      "用户", "农民", "学生", "网民"), "public_collective"),
)

_INDIVIDUAL_TYPES = {"person", "individual", "politician", "executive", "leader", "official",
                     "professor", "expert", "ceo", "founder", "candidate", "个人", "人物"}
_COLLECTIVE_TYPES = {"collective", "group", "community", "public", "audience", "群体", "公众"}


class ActionTemplate:
    """One catalogued action an agency class can realistically take."""

    __slots__ = ("id", "label", "kind", "cost", "lag", "reversibility", "targets_actor")

    def __init__(self, id: str, label: str, kind: str, cost: int = 1, lag: int = 0,
                 reversibility: str = "reversible", targets_actor: bool = False) -> None:
        self.id = id
        self.label = label
        self.kind = kind if kind in ACTION_KINDS else "communication"
        self.cost = max(0, int(cost))
        self.lag = max(0, int(lag))
        self.reversibility = reversibility if reversibility in ("reversible", "sticky", "irreversible") else "reversible"
        self.targets_actor = bool(targets_actor)

    def to_option(self, **extra: Any) -> Dict[str, Any]:
        d = {"id": self.id, "label": self.label, "kind": self.kind, "cost": self.cost,
             "lag": self.lag, "reversibility": self.reversibility, "targets_actor": self.targets_actor}
        d.update(extra)
        return d


def _t(id: str, label: str, kind: str, cost: int = 1, lag: int = 0, rev: str = "reversible",
       targets: bool = False) -> ActionTemplate:
    return ActionTemplate(id, label, kind, cost, lag, rev, targets)


_COMMON: Tuple[ActionTemplate, ...] = (
    _t("public_statement", "Issue a public statement or warning", "communication", 1, 0),
    _t("open_talks", "Open or join negotiations with another actor", "coalition", 1, 1, "reversible", True),
    _t("form_alliance", "Form or deepen an alliance / joint initiative", "coalition", 2, 1, "sticky", True),
    _t("break_alliance", "Withdraw from an alliance or agreement", "coalition", 2, 0, "sticky", True),
    _t("signal_concession", "Offer a concession or compromise", "communication", 1, 0, "reversible", True),
    _t("escalate_pressure", "Escalate pressure on another actor (campaign, threat, retaliation)",
       "coercive", 2, 1, "sticky", True),
)

ACTION_CATALOG: Dict[str, Tuple[ActionTemplate, ...]] = {
    "sovereign_government": _COMMON + (
        _t("impose_measure", "Impose or raise a tariff, sanction, export control or restriction",
           "policy", 3, 1, "sticky", True),
        _t("lift_measure", "Lift, delay or soften a restriction", "policy", 2, 1, "sticky", True),
        _t("subsidize", "Announce subsidies, procurement or an investment programme", "economic", 3, 2, "sticky"),
        _t("legislate", "Introduce legislation, decree or regulation", "policy", 3, 2, "sticky"),
        _t("sign_agreement", "Sign a bilateral or multilateral agreement", "coalition", 3, 1, "irreversible", True),
        _t("security_action", "Deploy security, enforcement or military-adjacent measures", "coercive", 3, 1, "sticky", True),
    ),
    "regulator_agency": _COMMON + (
        _t("open_inquiry", "Open an investigation, review or inquiry", "legal", 2, 1, "sticky", True),
        _t("issue_ruling", "Issue a ruling, approval, fine or licence decision", "legal", 2, 1, "irreversible", True),
        _t("propose_rule", "Propose or finalise a rule / standard", "policy", 2, 2, "sticky"),
        _t("grant_waiver", "Grant an exemption, waiver or extension", "policy", 1, 0, "reversible", True),
    ),
    "legislature": _COMMON + (
        _t("introduce_bill", "Introduce or advance a bill", "policy", 2, 2, "sticky"),
        _t("hold_hearing", "Hold a hearing or demand testimony", "legal", 1, 0, "reversible", True),
        _t("pass_vote", "Hold a decisive vote (budget, confirmation, resolution)", "policy", 3, 1, "irreversible"),
        _t("block_measure", "Block, delay or condition a measure", "policy", 2, 0, "reversible", True),
    ),
    "central_bank": _COMMON + (
        _t("rate_move", "Change the policy rate or guidance", "policy", 2, 1, "sticky"),
        _t("liquidity_tool", "Deploy or withdraw a liquidity / balance-sheet tool", "economic", 2, 1, "sticky"),
        _t("macroprudential", "Tighten or ease macroprudential rules", "policy", 2, 2, "sticky"),
    ),
    "judiciary": (
        _t("public_statement", "Publish an opinion or procedural order", "communication", 1, 0),
        _t("issue_ruling", "Issue a ruling or injunction", "legal", 1, 0, "irreversible", True),
        _t("schedule_review", "Schedule or expedite a review", "legal", 1, 1, "reversible", True),
    ),
    "political_party": _COMMON + (
        _t("campaign_push", "Launch a campaign push or mobilisation", "communication", 2, 0),
        _t("platform_shift", "Shift a platform position or policy pledge", "policy", 2, 1, "sticky"),
        _t("endorse_oppose", "Endorse or oppose a measure or candidate", "communication", 1, 0, "sticky", True),
    ),
    "firm": _COMMON + (
        _t("invest_capex", "Commit capital: new plant, capacity, R&D programme", "economic", 2, 2, "sticky"),
        _t("cut_or_delay", "Cut, delay or divest a project", "economic", 2, 1, "sticky"),
        _t("price_move", "Change pricing, terms or supply allocation", "economic", 1, 0, "reversible", True),
        _t("product_launch", "Launch a product, service or technology milestone", "operational", 2, 1, "irreversible"),
        _t("partnership_deal", "Sign a partnership, supply or licensing deal", "economic", 2, 1, "sticky", True),
        _t("lobby", "Lobby or petition policymakers", "communication", 1, 1, "reversible", True),
        _t("litigate", "File or threaten litigation", "legal", 2, 1, "sticky", True),
        _t("relocate_supply", "Shift sourcing, production or markets", "operational", 3, 2, "sticky"),
    ),
    "state_owned_enterprise": _COMMON + (
        _t("invest_capex", "Commit capital under state direction", "economic", 3, 2, "sticky"),
        _t("price_move", "Change pricing, output or allocation", "economic", 1, 0, "reversible", True),
        _t("partnership_deal", "Sign a supply or partnership deal", "economic", 2, 1, "sticky", True),
        _t("relocate_supply", "Shift sourcing, production or markets", "operational", 3, 2, "sticky"),
    ),
    "financial_institution": _COMMON + (
        _t("reprice_risk", "Reprice risk: lending terms, ratings, exposure limits", "economic", 1, 0, "reversible", True),
        _t("fund_or_withdraw", "Provide or withdraw financing / investment", "economic", 2, 1, "sticky", True),
        _t("market_call", "Publish a market view or forecast", "communication", 1, 0),
    ),
    "industry_coalition": _COMMON + (
        _t("industry_position", "Publish an industry position or standard", "communication", 1, 0),
        _t("lobby", "Lobby or petition policymakers", "communication", 1, 1, "reversible", True),
        _t("coordinate_members", "Coordinate member action (pledge, boycott, standard adoption)", "coalition", 2, 1, "sticky"),
    ),
    "labor_union": _COMMON + (
        _t("strike_action", "Call or threaten a strike / work stoppage", "coercive", 2, 0, "sticky", True),
        _t("bargain", "Enter or escalate collective bargaining", "coalition", 2, 1, "reversible", True),
        _t("mobilize", "Mobilise members or allies", "communication", 1, 0),
    ),
    "ngo_advocacy": _COMMON + (
        _t("publish_report", "Publish a report, exposé or scorecard", "communication", 1, 0),
        _t("campaign", "Launch a public campaign or petition", "communication", 1, 0, "reversible", True),
        _t("legal_challenge", "File a legal or regulatory complaint", "legal", 2, 1, "sticky", True),
    ),
    "international_org": _COMMON + (
        _t("issue_assessment", "Issue an assessment, forecast or recommendation", "communication", 1, 0),
        _t("convene", "Convene members or mediate", "coalition", 2, 1, "reversible", True),
        _t("program_decision", "Approve, condition or suspend a programme / financing", "economic", 3, 1, "sticky", True),
    ),
    "research_institution": (
        _t("publish_findings", "Publish findings or a forecast", "communication", 1, 0),
        _t("advise", "Advise or brief a decision-maker", "communication", 1, 0, "reversible", True),
        _t("launch_program", "Launch a research programme or pilot", "operational", 2, 2, "sticky"),
    ),
    "individual_leader": _COMMON + (
        _t("set_agenda", "Set the agenda: announce a priority or plan", "communication", 1, 0),
        _t("broker_deal", "Broker a deal or meeting between actors", "coalition", 2, 1, "reversible", True),
        _t("commit_resources", "Commit resources or make a binding pledge", "economic", 2, 1, "sticky"),
    ),
    "public_collective": (
        _t("public_statement", "Voice collective sentiment", "communication", 1, 0),
        _t("mobilize", "Mobilise: protest, boycott or turnout", "coercive", 1, 0, "reversible", True),
        _t("shift_behavior", "Shift behaviour: demand, adoption, savings", "economic", 1, 1, "sticky"),
    ),
    "media_outlet": (
        _t("publish_report", "Publish an investigation or editorial", "communication", 1, 0),
    ),
    "other_actor": _COMMON,
}

HOLD_TEMPLATE = _t(HOLD_OPTION_ID, "Hold position: wait, observe, keep current course", "wait", 0, 0)


# ---------------------------------------------------------------------------
# agency class inference
# ---------------------------------------------------------------------------

_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def _hay(*texts: Any) -> str:
    """Searchable haystack: camelCase/underscore type names are split into words
    (``MediaOutlet`` → ``media outlet``) so word-boundary hints can see them."""
    parts = []
    for t in texts:
        if not t:
            continue
        raw = str(t).replace("_", " ").replace("-", " ")
        parts.append(_CAMEL_RE.sub(" ", raw))
    joined = unicodedata.normalize("NFKC", " ".join(parts)).casefold()
    return f" {' '.join(joined.split())} "


_HINT_CACHE: Dict[str, "re.Pattern[str]"] = {}


def _hint_matches(hay: str, hint: str) -> bool:
    """ASCII hints match on word boundaries ("nato" must not hit "senator");
    CJK hints (no word boundaries in Chinese) match as substrings."""
    if any(ord(ch) > 127 for ch in hint):
        return hint in hay
    pattern = _HINT_CACHE.get(hint)
    if pattern is None:
        pattern = re.compile(r"(?<![a-z0-9])" + re.escape(hint.strip()) + r"(?![a-z0-9])")
        _HINT_CACHE[hint] = pattern
    return pattern.search(hay) is not None


def infer_agency_class(type_name: Any = "", *texts: Any, archetype: str = "") -> str:
    """Deterministic agency class from an entity type, role text and archetype.

    Explicit values that already name a class win.  The archetype ``collective``
    without a stronger hint maps to ``public_collective``; media stays
    ``media_outlet`` (not an agent); anything else falls back to ``firm`` for
    organisation-like types, ``individual_leader`` for person types and
    ``other_actor`` otherwise.  Never raises.
    """
    try:
        for candidate in (type_name, *texts):
            c = str(candidate or "").strip().casefold()
            if c in AGENCY_CLASSES:
                return c
        hay = _hay(type_name, *texts)
        for hints, klass in _AGENCY_HINTS:
            if any(_hint_matches(hay, h) for h in hints):
                return klass
        tname = str(type_name or "").strip().casefold()
        if tname in _INDIVIDUAL_TYPES:
            return "individual_leader"
        if str(archetype or "").casefold() == "collective" or tname in _COLLECTIVE_TYPES:
            return "public_collective"
        if tname in ("organization", "organisation", "company", "org", "机构", "组织"):
            return "firm"
        return "other_actor"
    except Exception:  # noqa: BLE001
        return "other_actor"


def default_capacity(agency_class: str) -> int:
    return DEFAULT_CAPACITY_BY_CLASS.get(str(agency_class or ""), DEFAULT_CAPACITY_BY_CLASS["other_actor"])


def catalog_for(agency_class: str) -> Tuple[ActionTemplate, ...]:
    return ACTION_CATALOG.get(str(agency_class or ""), ACTION_CATALOG["other_actor"])


# ---------------------------------------------------------------------------
# option menu
# ---------------------------------------------------------------------------

_PLAN_KIND_HINTS = (
    (("invest", "capex", "plant", "factory", "capacity", "fund", "acquire", "acquisition", "spend",
      "投资", "扩产", "建厂", "收购", "融资"), "economic", 3, 2),
    (("tariff", "sanction", "ban", "restrict", "control", "regulat", "rule", "law", "bill", "policy",
      "关税", "制裁", "禁令", "限制", "法规", "政策", "立法"), "policy", 3, 1),
    (("alliance", "partner", "agreement", "deal", "coalition", "cooperat", "joint", "treaty",
      "联盟", "合作", "协议", "伙伴", "合资"), "coalition", 2, 1),
    (("sue", "lawsuit", "litig", "court", "appeal", "complaint", "permit", "licen", "filing", "file a",
      "file an", "petition", "ruling", "inquiry", "诉讼", "起诉", "上诉", "许可", "申诉", "备案"), "legal", 2, 1),
    (("strike", "protest", "boycott", "pressure", "retaliat", "罢工", "抗议", "抵制", "报复"), "coercive", 2, 0),
    (("launch", "ship", "deploy", "roll out", "produce", "build", "expand", "发布", "部署", "投产", "量产"),
     "operational", 2, 1),
)


def _plan_kind(text: str) -> Tuple[str, int, int]:
    low = unicodedata.normalize("NFKC", text).casefold()
    for hints, kind, cost, lag in _PLAN_KIND_HINTS:
        if any(h in low for h in hints):
            return kind, cost, lag
    return "communication", 1, 0


def _fair_menu(options: List[Dict[str, Any]], round_num: int, limit: int) -> List[Dict[str, Any]]:
    """Reserve fulfillment, substantive coverage and complete offer-response groups."""
    if type(limit) is not int or limit < 1:
        raise ValueError("max_options must be a positive integer")
    slots = limit - 1
    chosen: List[Dict[str, Any]] = []
    def take(row):
        if len(chosen) < slots and row not in chosen:
            chosen.append(row)
    deliveries = [o for o in options if o["id"].startswith(FULFILLMENT_PREFIX)]
    substantive = [o for o in options if ":" not in o["id"] and o["kind"] not in ("communication", "wait")]
    offset = max(0, round_num - 1) % len(substantive) if substantive else 0
    substantive = substantive[offset:] + substantive[:offset]
    if deliveries:
        take(deliveries[0])
    if substantive:
        take(substantive[0])
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for opt in options:
        if "interaction_id" in opt:
            groups.setdefault(opt["interaction_id"], []).append(opt)
    offers = list(groups.values())
    minimum = 1 + bool(deliveries) + bool(substantive) + (max(map(len, offers)) if offers else 0)
    if limit < minimum:
        raise ValueError(f"max_options must be at least {minimum} to preserve delivery, action and offer coverage")
    if offers:
        offset = max(0, round_num - 1) % len(offers)
        for group in offers[offset:] + offers[:offset]:
            if len(group) <= slots - len(chosen):
                for opt in group:
                    take(opt)
                break
    for opt in deliveries[1:] + substantive[1:] + options:
        if "interaction_id" not in opt:
            take(opt)
    for group in offers:
        if not any(o in chosen for o in group) and len(group) <= slots - len(chosen):
            for opt in group:
                take(opt)
    return chosen + [HOLD_TEMPLATE.to_option(why="strategic patience is a legitimate choice")]


def build_option_menu(actor: ActorState, world: WorldModel, round_num: int,
                      *, max_options: int = MAX_OPTIONS) -> List[Dict[str, Any]]:
    """Deterministic, world-grounded option menu for one actor in one round.

    Order of priority: responses to moves aimed at the actor last period,
    documented plans, agency-class options the actor can still afford, and
    always ``hold_position`` last.  Irreversible moves already taken are not
    offered again; options above the remaining capacity are dropped (the actor
    may still take cheap moves).
    """
    strict = world.mechanics_policy("action_policy")
    operative = world.mechanics_policy("agreement_policy")
    options: List[Dict[str, Any]] = []
    seen: set = set()
    remaining = actor.capacity_remaining
    last_round = max(0, int(round_num) - 1)

    def push(opt: Dict[str, Any]) -> None:
        if opt["id"] in seen or (not strict and len(options) >= max_options):
            return
        seen.add(opt["id"])
        options.append(opt)

    # Due promises must remain reachable even when incoming offers fill the menu.
    if remaining >= FULFILLMENT_ACTION_COST:
        deliverable = [c for c in actor.commitments
                       if world.delivery_commitment(actor.agent_id, c.get("id"), round_num) is not None]
        for c in sorted(deliverable, key=lambda item: ((not world.commitment_timing(item, round_num)[0],
                            world.commitment_deadline_label(item), item["id"]) if operative else
                            (int(item["due_round"]), item["id"])))[:3]:
            push({"id": FULFILLMENT_PREFIX + c["id"],
                  "label": f"Deliver commitment [{c['id']}]: {_text(c.get('description'), 220)}",
                  "kind": "operational", "cost": FULFILLMENT_ACTION_COST, "lag": 0,
                  "reversibility": "reversible", "targets_actor": False,
                  "suggested_targets": world.delivery_targets(actor.agent_id, c), "commitment_id": c["id"],
                  "commitment_target_ids": world.delivery_target_ids(actor.agent_id, c),
                  **({"operative_terms": c["operative_terms"], "accepted_terms_hash": c["operative_terms_hash"]}
                     if "operative_terms" in c else {}),
                  "why": "attempt this specific promise's delivery now; only explicit arbiter confirmation fulfils it"})

    # 0) OFFERS: answers owed on open offers — the only way an agreement can come about
    open_offers = world.open_interactions_for(actor.agent_id)
    for it in (open_offers if strict else open_offers[:3]):
        if operative and world.interaction_expired(it, round_num):
            continue
        who = world.actor_name(it.proposer)
        until = world.interaction_deadline_label(it)
        for verb, label, kind, cost, lag in (
            ("accept", f"Accept {who}'s offer [{it.id}] on exactly these terms: {_text(it.terms, 110)} — binds both sides",
             "coalition", 1, 1),
            ("counter", f"Counter {who}'s offer [{it.id}] with your own terms (state them in `terms`)", "coalition", 1, 0),
            ("reject", f"Reject {who}'s offer [{it.id}]", "communication", 1, 0),
            ("defer", f"Defer your answer to {who}'s offer [{it.id}] (open until {until})", "communication", 0, 0),
        ):
            if operative and verb == "accept" and world.agreement_admission(
                    world.round, actor.agent_id, f"accept:{it.id}", accepted_terms_hash=it.operative_terms_hash):
                continue
            if cost <= remaining:
                why = f"an offer from {who} awaits your answer (lapses after {until})"
                if verb == "accept":
                    # mirror-image rule (world_model.terms_restate_offer): accept adopts the offer verbatim
                    why += ("; accept adopts the offer's terms verbatim — leave `terms` null or restate them; "
                            "an accept whose terms differ materially is recorded as a counter-offer, not an agreement")
                push({"id": f"{verb}:{it.id}", "label": label, "kind": kind, "cost": cost, "lag": lag,
                      "reversibility": "sticky" if verb == "accept" else "reversible", "targets_actor": False,
                      "suggested_targets": [who], "interaction_id": it.id, "why": why,
                      **({"operative_terms": it.operative_terms, "accepted_terms_hash": it.operative_terms_hash}
                         if operative else {})})
    # 1) responses to what was aimed at this actor last period (offers are answered above)
    aimed = [e for e in world.events_in_round(last_round)
             if actor.name in e.targets and e.kind not in ("offer", "agreement", "breach")
             and e.option_id not in PROPOSAL_OPTION_IDS] if last_round > 0 else []
    # RED LINES: a crossing is the sharper reading of the move that crossed it — answer it first and
    # do not offer a second set of responses to the same actor's plain move
    crossed_by = {e.actors[0] for e in aimed if e.kind == "red_line" and e.actors}
    aimed = sorted((e for e in aimed if e.kind != "action" or not (e.actors and e.actors[0] in crossed_by)),
                   key=lambda e: 0 if e.kind == "red_line" else 1)
    for idx, ev in enumerate(aimed[:3]):
        if ev.source == "shock" and not ev.actors:
            # EXOGENOUS SHOCKS: nobody moved — the actor contains, adapts to or answers what happened
            what = _text(ev.description, 80)
            for tmpl_id, label, kind in (
                (f"respond_{idx + 1}_contain", f"Contain the fallout of: {what}", "operational"),
                (f"respond_{idx + 1}_adapt", f"Adjust your plans to: {what}", "economic"),
                (f"respond_{idx + 1}_accommodate", f"Publicly answer: {what}", "communication"),
            ):
                if remaining >= 1:
                    push({"id": tmpl_id, "label": label, "kind": kind, "cost": 1, "lag": 0,
                          "reversibility": "reversible", "targets_actor": False,
                          "why": "a researched risk materialised last period and hit you"})
            continue
        who = ev.actors[0] if ev.actors else "another actor"
        who_id = world.resolve_actor(who)
        for tmpl_id, label, kind, cost in (
            (f"respond_{idx + 1}_counter", f"Counter {who}'s move ({_text(ev.description, 80)})", "coercive", 2),
            (f"respond_{idx + 1}_negotiate", f"Seek talks with {who} over its move", "coalition", 1),
            (f"respond_{idx + 1}_accommodate", f"Accommodate or publicly answer {who}'s move", "communication", 1),
        ):
            if cost <= remaining:
                push({"id": tmpl_id, "label": label, "kind": kind, "cost": cost, "lag": 0,
                      "reversibility": "reversible", "targets_actor": True,
                      "suggested_targets": [who] if who_id is not None else [],
                      # RED LINES: a crossing reads as one, so the answer can be weighed against it
                      "why": (f"{who} crossed your red line last period" if ev.kind == "red_line"
                              else "responds to a move aimed at you last period")})
    # 2) documented plans (research-grounded)
    for idx, plan in enumerate(actor.documented_plans[:4]):
        kind, cost, lag = _plan_kind(plan)
        if strict and cost > remaining:
            continue
        if cost > remaining:
            cost = min(cost, max(1, remaining)) if remaining else cost
        push({"id": f"plan_{idx + 1}", "label": f"Advance your documented plan: {_text(plan, 120)}",
              "kind": kind, "cost": cost, "lag": lag, "reversibility": "sticky", "targets_actor": False,
              "why": "a plan or likely action documented in your dossier"})
    # 3) class catalogue filtered by capacity and prior irreversible moves
    taken_irreversible = set(getattr(actor, "irreversible_option_ids", []) or [])
    for tmpl in catalog_for(actor.agency_class):
        if tmpl.id in taken_irreversible:
            continue
        if tmpl.cost > max(remaining, 0):
            continue
        push(tmpl.to_option())
    if operative:
        for opt in options:
            opt["agreement_policy"] = "operative-deadline-v1"
    if strict:
        return _fair_menu(options, int(round_num), max_options)
    if len(options) >= max_options:
        options = options[: max_options - 1]
    options.append(HOLD_TEMPLATE.to_option(why="strategic patience is a legitimate choice"))
    return options


def deciding_roster(agent_configs: Sequence[Dict[str, Any]], active_ids: Iterable[int], *,
                    max_actors: int = 24, audience_type: str = "Audience") -> List[int]:
    """Who decides this round: principals always, then active named actors by influence."""
    principals: List[Tuple[float, int]] = []
    sampled: List[Tuple[float, int]] = []
    active = set(int(a) for a in active_ids)
    for cfg in agent_configs or []:
        if not isinstance(cfg, dict) or cfg.get("agent_id") is None:
            continue
        try:
            aid = int(cfg["agent_id"])
            infl = float(cfg.get("influence_weight", 1.0) or 0.0)
        except (TypeError, ValueError):
            continue
        if str(cfg.get("entity_type") or "") == audience_type:
            continue
        if str(cfg.get("cadence") or "sampled") == "principal":
            principals.append((-infl, aid))
        elif aid in active:
            sampled.append((-infl, aid))
    ordered = [aid for _, aid in sorted(principals)] + [aid for _, aid in sorted(sampled)]
    out: List[int] = []
    for aid in ordered:
        if aid not in out:
            out.append(aid)
        if len(out) >= max(1, int(max_actors)):
            break
    return out


# ---------------------------------------------------------------------------
# prompt and parsing
# ---------------------------------------------------------------------------

def _render_options(options: List[Dict[str, Any]]) -> str:
    lines = []
    for o in options:
        bits = [f"[{o['id']}] {o['label']}", f"kind={o['kind']}", f"cost={o['cost']}"]
        if o.get("lag"):
            bits.append(f"effect lands in {o['lag']} period(s)")
        if o.get("reversibility") and o["reversibility"] != "reversible":
            bits.append(o["reversibility"])
        if o.get("targets_actor"):
            bits.append("needs a target actor")
        if o["id"].startswith(FULFILLMENT_PREFIX):
            # Render the actual stored binding, including [] for self promises.
            # The parser must keep rejecting recipients inferred from prose.
            bits.append("targets=" + json.dumps(o.get("commitment_target_ids") or []))
            if o.get("suggested_targets"):
                bits.append("stored counterparty=" + json.dumps(o["suggested_targets"], ensure_ascii=False))
        if o.get("operative_terms") is not None:
            bits.append("operative_terms=" + json.dumps(o["operative_terms"], ensure_ascii=False, sort_keys=True))
            bits.append("accepted_terms_hash=" + str(o["accepted_terms_hash"]))
        if o.get("why"):
            bits.append(o["why"])
        lines.append("- " + " · ".join(bits))
    return "\n".join(lines)


def build_decision_prompt(actor: ActorState, *, world_clock: str, public_brief: str,
                          private_brief: str, options: List[Dict[str, Any]],
                          scenarios: Sequence[str], cast_names: Sequence[str],
                          language: str = "", recent_discourse: str = "") -> str:
    """User-turn prompt for the structured decision (the actor's role brief is the system turn)."""
    sc = "; ".join(str(s) for s in scenarios) or "(none)"
    cast = ", ".join(str(n) for n in cast_names[:30]) or "(the other actors in this simulation)"
    goals = "; ".join(actor.goals) if actor.goals else ""
    inc = []
    if actor.incentives.get("gains_if"):
        inc.append(f"you gain if: {actor.incentives['gains_if']}")
    if actor.incentives.get("loses_if"):
        inc.append(f"you lose if: {actor.incentives['loses_if']}")
    lang_rule = f"Write public_statement in {language}." if language else ""
    parts = [
        world_clock.strip(),
        public_brief.strip(),
        private_brief.strip(),
    ]
    if recent_discourse.strip():
        parts.append(recent_discourse.strip())
    if any(o.get("agreement_policy") == "operative-deadline-v1" for o in options):
        parts.append(
            "OPERATIVE AGREEMENTS: an offer or counteroffer must include operative_terms with "
            'schema_version="operative-terms/v1" and an exact fulfillment_condition. Optional fields: '
            "offer_expires_on, effective_on, delivery_deadline (ISO YYYY-MM-DD dates or null), and "
            "duration_days (positive integer, requires effective_on). A duration is NOT a delivery deadline. "
            "Use only dates and conditions you actually offer, never extract an arbitrary prose date as a deadline. "
            "No deadline means the obligation stays pending until explicit delivery or withdrawal. "
            "For accept, copy that menu entry's accepted_terms_hash exactly; leave terms/operative_terms null "
            "or repeat them exactly. Any change requires counter, with a complete new operative_terms object."
        )
    parts.append(
        f"# DECIDE YOUR MOVE FOR THIS PERIOD — {actor.name}\n"
        "Act strictly as this real-world actor. Choose the ONE most consequential move you actually "
        "take over the whole period, grounded in your documented goals, incentives, capabilities, "
        "constraints, alliances and red lines. Realistic options for you:\n"
        f"{_render_options(options)}\n"
        + (f"Your documented goals: {goals}\n" if goals else "")
        + (("Your incentives: " + "; ".join(inc) + "\n") if inc else "")
        + "Rules: pick an option id from the list (or \"custom\" with a kind from "
        f"{', '.join(ACTION_KINDS)} when none fits); name real targets from the cast when the option "
        "needs one; magnitude 0-1 is how far you go; public_statement is what you publicly say or "
        "announce this period (1-3 sentences, concrete: decision, numbers, dates, conditions); "
        "private_rationale is for your own record; terms states the exact terms when your move makes "
        "an offer to another actor or counters one (what you give, what you expect, by when) — an "
        "offer binds nobody until the other side accepts it, and an accept answer adopts the offer's terms "
        "verbatim (leave terms null or restate them — an accept whose terms differ materially is recorded as a "
        "counter-offer, not an agreement); a fulfill:<commitment_id> option attempts delivery of that exact "
        "stored promise. Choose its exact id, copy that option's targets list of integer agent IDs exactly "
        "(self promises use []; agreement promises list the stored counterparty ID), and describe what was actually delivered. "
        "Do not add recipients inferred from the promise's wording; "
        "an unrelated action, another offer, an announcement or partial progress does not discharge it. "
        "The consequence arbiter must confirm delivery. commitment is what you bind yourself to and when "
        "(due_periods ≥ 1) or null; alliance_moves lists any alliance you propose/strengthen/break; "
        "scenario_commitment names which candidate scenario your move pushes toward, or \"abstain\" "
        f"if your move has no real bearing on the outcome. Candidate scenarios: {sc}.\n"
        f"Cast: {cast}.\n"
        f"{lang_rule}\n"
        "Return ONLY JSON:\n"
        '{"option_id": "<id or custom>", "custom_action": {"kind": "...", "label": "..."} | null, '
        '"targets": ["<actor name>" | <integer agent_id from fulfill targets>, ...], "magnitude": 0.0-1.0, '
        '"public_statement": "...", "private_rationale": "...", "terms": "<offer or counter-offer terms> | null", '
        '"commitment": {"description": "...", "due_periods": 1} | null, '
        '"alliance_moves": [{"target": "<actor name>", "move": "propose|strengthen|break|oppose"}], '
        '"expected_reactions": [{"actor": "<actor name>", "reaction": "..."}], '
        '"scenario_commitment": {"scenario": "<candidate or abstain>", "confidence": 0.0-1.0}}'
    )
    return "\n\n".join(p for p in parts if p)


def expected_script(language: Any) -> str:
    """``"cjk"`` / ``"latin"`` for a run language, ``""`` when it is unset or unknown."""
    low = str(language or "").strip().casefold()
    if not low or low == "auto":
        return ""
    code = re.split(r"[-_ (/]", low, maxsplit=1)[0]          # "zh-CN" / "en_US" / "English (US)" → code
    if code in _CJK_LANGUAGE_CODES or any(w in low for w in _CJK_LANGUAGE_WORDS):
        return "cjk"
    if code in _LATIN_LANGUAGE_CODES or any(w in low for w in _LATIN_LANGUAGE_WORDS):
        return "latin"
    return ""


def text_script(text: Any) -> str:
    """Dominant script of a statement: ``"cjk"``, ``"latin"`` or ``""`` (no letters at all)."""
    s = str(text or "")
    cjk = len(_CJK_CHAR_RE.findall(s))
    latin = len(_LATIN_CHAR_RE.findall(s))
    if not cjk and not latin:
        return ""
    return "cjk" if cjk * 3 >= latin else "latin"


def statement_matches_language(text: Any, language: Any) -> bool:
    """False only when the run language and the statement both have a known script and they differ."""
    want, have = expected_script(language), text_script(text)
    return not want or not have or want == have


class AgentDecision:
    """A validated structured decision (or a typed non-decision)."""

    def __init__(self, agent_id: int, actor_name: str, option: Dict[str, Any], *, targets: List[str],
                 magnitude: float, public_statement: str, private_rationale: str = "",
                 commitment: Optional[Dict[str, Any]] = None,
                 alliance_moves: Optional[List[Dict[str, str]]] = None,
                 expected_reactions: Optional[List[Dict[str, str]]] = None,
                 scenario: Optional[str] = None, scenario_confidence: float = 0.0,
                 status: str = "ok", round_num: int = 0, period_end: Optional[str] = None,
                 raw_option_id: str = "", problems: Optional[List[str]] = None, terms: str = "",
                 operative_terms: Optional[Dict[str, Any]] = None, accepted_terms_hash: Optional[str] = None) -> None:
        self.agent_id = int(agent_id)
        self.operative_terms = validate_operative_terms(operative_terms) if operative_terms is not None else None
        self.accepted_terms_hash = accepted_terms_hash
        if operative_terms is not None or accepted_terms_hash is not None:
            if type(terms) is not str or len(terms) > INTERACTION_TERMS_MAX_CHARS:
                raise ValueError("operative terms must be bounded exact prose")
            self.terms = terms
        else:
            self.terms = _text(terms, INTERACTION_TERMS_MAX_CHARS)
        self.actor_name = actor_name
        self.option = dict(option)
        self.targets = list(targets)
        self.magnitude = max(0.0, min(1.0, float(magnitude)))
        self.public_statement = public_statement
        self.private_rationale = private_rationale
        self.commitment = commitment
        self.alliance_moves = list(alliance_moves or [])
        self.expected_reactions = list(expected_reactions or [])
        self.scenario = scenario
        self.scenario_confidence = max(0.0, min(1.0, float(scenario_confidence)))
        self.status = status
        self.round = int(round_num)
        self.period_end = period_end
        self.raw_option_id = raw_option_id
        # why a typed non-decision is not a move (validation / provider detail), for the record
        self.problems = [_text(p, 300) for p in (problems or []) if _text(p, 300)][:MAX_PROBLEMS]

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": DECISION_CONTRACT_VERSION,
            "round": self.round, "period_end": self.period_end,
            "agent_id": self.agent_id, "actor_name": self.actor_name,
            "option": dict(self.option), "targets": list(self.targets),
            "magnitude": round(self.magnitude, 3),
            "public_statement": self.public_statement, "private_rationale": self.private_rationale,
            "terms": self.terms,
            **({"operative_terms": json.loads(json.dumps(self.operative_terms))} if self.operative_terms is not None else {}),
            **({"accepted_terms_hash": self.accepted_terms_hash} if self.accepted_terms_hash is not None else {}),
            "commitment": self.commitment, "alliance_moves": list(self.alliance_moves),
            "expected_reactions": list(self.expected_reactions),
            "scenario": self.scenario, "scenario_confidence": round(self.scenario_confidence, 3),
            "status": self.status, "raw_option_id": self.raw_option_id,
            "problems": list(self.problems),
        }

    def scenario_commitment(self, outcome_power: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """Row for ``worldstate.commitments_from_decisions`` (None when abstaining)."""
        if not self.ok or not self.scenario or self.scenario == ABSTAIN:
            return None
        row: Dict[str, Any] = {"agent_id": self.agent_id, "scenario": self.scenario,
                               "magnitude": round(max(0.1, self.magnitude), 3),
                               "confidence": round(self.scenario_confidence, 3), "round": self.round}
        if outcome_power is not None:
            row["outcome_power"] = outcome_power
        if self.period_end:
            row["period_end"] = self.period_end
        return row


def hold_decision(actor: ActorState, *, status: str, round_num: int, period_end: Optional[str],
                  raw_option_id: str = "", problems: Optional[List[str]] = None) -> AgentDecision:
    return AgentDecision(actor.agent_id, actor.name, HOLD_TEMPLATE.to_option(), targets=[], magnitude=0.0,
                         public_statement="", status=status, round_num=round_num, period_end=period_end,
                         raw_option_id=raw_option_id, problems=problems)


def _match_scenario(raw: Any, scenarios: Sequence[str]) -> Optional[str]:
    text = normalize_label(raw)
    if not text:
        return None
    if text in (ABSTAIN, "弃权", "none", "no bearing"):
        return ABSTAIN
    for s in scenarios:
        if normalize_label(s) == text:
            return str(s)
    for s in scenarios:
        ns = normalize_label(s)
        if len(ns) >= 4 and (ns in text or text in ns):
            return str(s)
    return None


def parse_decision(raw: Any, *, actor: ActorState, world: WorldModel, options: List[Dict[str, Any]],
                   scenarios: Sequence[str], round_num: int, period_end: Optional[str] = None,
                   language: str = "") -> AgentDecision:
    """Validate the model's JSON against the menu, the cast and the scenario set.

    Unknown option ids, missing payloads or malformed structures degrade to a
    ``hold_position`` decision with ``status="invalid"``.  Targets are resolved
    to cast names; unknown names are dropped.  A ``custom`` option must carry a
    catalogued kind and a label.  When ``language`` (the run language) is set, a
    move whose ``public_statement`` is written in the wrong script (CJK vs Latin)
    is rejected for publication the same way, with ``status="language_mismatch"``
    and the rejected text in ``problems``; the actor then posts organically.
    """
    if not isinstance(raw, dict):
        return hold_decision(actor, status="invalid", round_num=round_num, period_end=period_end)
    by_id = {o["id"]: o for o in options}
    raw_option = _text(raw.get("option_id") or raw.get("option"), 64)
    option: Optional[Dict[str, Any]] = None
    if raw_option in by_id:
        option = dict(by_id[raw_option])
    elif raw_option.casefold() == "custom":
        custom = raw.get("custom_action") if isinstance(raw.get("custom_action"), dict) else {}
        kind = _text(custom.get("kind"), 24).casefold()
        label = _text(custom.get("label"), 140)
        if kind in ACTION_KINDS and label:
            option = {"id": "custom", "label": label, "kind": kind, "cost": 2 if kind != "wait" else 0,
                      "lag": 1 if kind in ("economic", "policy", "legal") else 0,
                      "reversibility": "sticky" if kind in ("economic", "policy", "legal", "coercive") else "reversible",
                      "targets_actor": kind in ("coalition", "coercive", "legal")}
    else:
        # tolerate the model echoing the label instead of the id
        wanted = normalize_label(raw_option)
        for o in options:
            if o["id"].startswith(FULFILLMENT_PREFIX):
                continue  # Delivery identity must be exact, never a label-prefix match.
            if wanted and normalize_label(o["label"]).startswith(wanted[:40]):
                option = dict(o)
                break
    if option is None:
        return hold_decision(actor, status="invalid", round_num=round_num, period_end=period_end,
                             raw_option_id=raw_option)
    targets: List[str] = []
    for t in (raw.get("targets") or [])[:6] if isinstance(raw.get("targets"), list) else []:
        aid = world.resolve_actor(t)
        if aid is not None and aid != actor.agent_id:
            name = world.actor_name(aid)
            if name not in targets:
                targets.append(name)
    if not targets and option.get("suggested_targets"):
        targets = list(option["suggested_targets"])[:2]
    if option["id"].startswith(FULFILLMENT_PREFIX):
        c = world.delivery_commitment(actor.agent_id, option["id"][len(FULFILLMENT_PREFIX):], round_num)
        if (c is None or actor.capacity_remaining < FULFILLMENT_ACTION_COST
                or not world.delivery_targets_match(actor.agent_id, c, raw.get("targets"))):
            return hold_decision(actor, status="invalid", round_num=round_num, period_end=period_end,
                                 raw_option_id=raw_option, problems=["invalid commitment delivery binding"])
        targets = world.delivery_targets(actor.agent_id, c)
    try:
        magnitude = float(raw.get("magnitude", 0.5))
    except (TypeError, ValueError):
        magnitude = 0.5
    statement = _text(raw.get("public_statement"), STATEMENT_MAX_CHARS)
    if option["id"] != HOLD_OPTION_ID and statement and not statement_matches_language(statement, language):
        # the statement is what gets published: a wrong-script one is treated like an invalid
        # decision (typed hold → organic post) and stays visible in world_actions.jsonl
        return hold_decision(actor, status=LANGUAGE_MISMATCH, round_num=round_num, period_end=period_end,
                             raw_option_id=raw_option,
                             problems=[f"public_statement is {text_script(statement)}-script but the run "
                                       f"language is {_text(language, 40)}: \"{_text(statement, 100)}\""])
    rationale = _text(raw.get("private_rationale"), RATIONALE_MAX_CHARS)
    if world.mechanics_policy("agreement_policy"):
        supplied_terms = raw.get("terms")
        if (supplied_terms is not None and (type(supplied_terms) is not str
                or len(supplied_terms) > INTERACTION_TERMS_MAX_CHARS)):
            return hold_decision(actor, status="invalid", round_num=round_num, period_end=period_end,
                                 raw_option_id=raw_option, problems=["operative terms must be bounded exact prose"])
        terms = supplied_terms or ""
    else:
        terms = _text(raw.get("terms"), INTERACTION_TERMS_MAX_CHARS)
    commitment = None
    rc = raw.get("commitment")
    if isinstance(rc, dict) and _text(rc.get("description"), 220):
        try:
            due = max(1, int(rc.get("due_periods", 1) or 1))
        except (TypeError, ValueError):
            due = 1
        commitment = {"description": _text(rc["description"], 220), "due_periods": min(due, 12)}
    moves: List[Dict[str, str]] = []
    for m in (raw.get("alliance_moves") or [])[:4] if isinstance(raw.get("alliance_moves"), list) else []:
        if not isinstance(m, dict):
            continue
        aid = world.resolve_actor(m.get("target"))
        verb = _text(m.get("move"), 16).casefold()
        if aid is not None and aid != actor.agent_id and verb in ("propose", "strengthen", "break", "oppose",
                                                                 "join", "support", "distance", "sanction"):
            moves.append({"target": world.actor_name(aid), "move": verb})
    reactions: List[Dict[str, str]] = []
    for r in (raw.get("expected_reactions") or [])[:4] if isinstance(raw.get("expected_reactions"), list) else []:
        if isinstance(r, dict) and _text(r.get("actor"), 80) and _text(r.get("reaction"), 160):
            reactions.append({"actor": _text(r["actor"], 80), "reaction": _text(r["reaction"], 160)})
    scenario = None
    confidence = 0.0
    sc_raw = raw.get("scenario_commitment")
    if isinstance(sc_raw, dict):
        scenario = _match_scenario(sc_raw.get("scenario"), scenarios)
        try:
            confidence = float(sc_raw.get("confidence", 0.6))
        except (TypeError, ValueError):
            confidence = 0.6
    elif isinstance(sc_raw, str):
        scenario = _match_scenario(sc_raw, scenarios)
        confidence = 0.6
    if option["id"] != HOLD_OPTION_ID and not statement:
        # a move without any public trace is still a move, but we need something to publish
        statement = f"{actor.name}: {option['label']}" + (f" ({', '.join(targets)})" if targets else "")
    if option["id"].startswith(FULFILLMENT_PREFIX):
        commitment, moves, terms = None, [], ""  # Delivery is not a fresh pledge, alliance or offer.
    operative_terms = None
    accepted_hash = None
    if world.mechanics_policy("agreement_policy"):
        operative_terms = raw.get("operative_terms")
        accepted_hash = raw.get("accepted_terms_hash")
        error = world.agreement_admission(round_num, actor.agent_id, option["id"], terms=terms,
            operative_terms=operative_terms, accepted_terms_hash=accepted_hash)
        if error:
            return hold_decision(actor, status="invalid", round_num=round_num, period_end=period_end,
                                 raw_option_id=raw_option, problems=[error])
        if option["id"] not in PROPOSAL_OPTION_IDS and not option["id"].startswith("counter:"):
            operative_terms = None
        if not option["id"].startswith("accept:"):
            accepted_hash = None
    result = AgentDecision(actor.agent_id, actor.name, option, targets=targets, magnitude=magnitude,
                         public_statement=statement, private_rationale=rationale, commitment=commitment,
                         alliance_moves=moves, expected_reactions=reactions, scenario=scenario,
                         scenario_confidence=confidence, status="ok", round_num=round_num,
                         period_end=period_end, raw_option_id=raw_option, terms=terms,
                         operative_terms=operative_terms, accepted_terms_hash=accepted_hash)
    admission = world.decision_admission(round_num, result.to_dict())
    if admission["status"] != "ok":
        return hold_decision(actor, status="invalid", round_num=round_num, period_end=period_end,
                             raw_option_id=raw_option, problems=[admission["reason"]])
    return result


def elicit_decision(llm: Any, *, system_message: str, user_prompt: str, actor: ActorState,
                    world: WorldModel, options: List[Dict[str, Any]], scenarios: Sequence[str],
                    round_num: int, period_end: Optional[str] = None,
                    temperature: float = 0.4, max_tokens: int = 1200, language: str = "") -> AgentDecision:
    """One structured LLM call → validated decision; failures become typed holds.

    ``llm.chat_json`` is the backend ``LLMClient`` surface: a content-filter or other
    non-retryable 4xx rejection is retried once on the configured fallback provider by the
    client itself before it raises; what survives is recorded in ``problems`` with the
    provider's error class, HTTP status / code, a bounded snippet and the failover outcome.
    """
    if llm is None:
        return hold_decision(actor, status="failed", round_num=round_num, period_end=period_end,
                             problems=["no llm client"])
    messages: List[Dict[str, str]] = []
    if system_message:
        messages.append({"role": "system", "content": str(system_message)})
    messages.append({"role": "user", "content": user_prompt})
    try:
        raw = llm.chat_json(messages=messages, temperature=temperature, max_tokens=max_tokens)
    except Exception as exc:  # noqa: BLE001 — the round loop must survive a failed decision
        detail = describe_llm_error(exc, max_chars=DECISION_ERROR_SNIPPET_CHARS)
        logger.warning("decision step failed for %s (status=failed): %s", actor.name, detail)
        return hold_decision(actor, status="failed", round_num=round_num, period_end=period_end,
                             problems=[f"llm error: {detail}"])
    return parse_decision(raw, actor=actor, world=world, options=options, scenarios=scenarios,
                          round_num=round_num, period_end=period_end, language=language)


def decision_memory_note(decision: AgentDecision, period_label: str = "") -> str:
    """Private USER memory note so later rounds and the reaction step stay consistent."""
    if not decision.ok:
        return ""
    head = f"# YOUR MOVE THIS PERIOD{(' — ' + period_label) if period_label else ''}"
    lines = [head, f"You chose: {decision.option.get('label') or decision.option.get('id')}"]
    if str(decision.option.get("id", "")).startswith(FULFILLMENT_PREFIX):
        lines.append("This was a delivery attempt; only the consequence arbiter can confirm fulfilment.")
    if decision.targets:
        lines.append("Directed at: " + ", ".join(decision.targets))
    if decision.public_statement:
        lines.append(f'You announced: "{decision.public_statement}"')
    if decision.commitment:
        lines.append(f"You committed to: {decision.commitment.get('description')} "
                     f"(within {decision.commitment.get('due_periods')} period(s))")
    if decision.private_rationale:
        lines.append(f"Your private reasoning: {decision.private_rationale}")
    lines.append("In the response step, defend or build on this move; do not contradict it.")
    return "\n".join(lines)


def summarize_decisions(decisions: Iterable[AgentDecision]) -> Dict[str, int]:
    counts = dict.fromkeys(DECISION_STATUSES, 0)
    counts["hold"] = 0
    for d in decisions:
        if d.status in counts:
            counts[d.status] += 1
        if d.option.get("id") == HOLD_OPTION_ID:
            counts["hold"] += 1
    return counts
