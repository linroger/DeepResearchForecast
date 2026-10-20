"""Offers, consent and obligations in the reflexive world model (ported from the world-v1
engine's consent rule: speech cannot create an agreement).

Pins: a proposing move aimed at another actor opens an offer with terms; the recipient's
menu carries accept / counter / reject / defer answers bound to the offer and the generic
"respond" entries are not duplicated for it; accepting binds both parties with obligations
and pulls them closer, rejecting pushes them apart, countering opens a counter-offer the
proposer must answer, deferring keeps it open; unanswered offers lapse after the TTL; a
lapsed obligation under an agreement, or an explicit withdrawal, is a breach that costs
reputation and the relationship; everything survives a save/load round-trip and shows up
in the briefs, the digest, the arbiter prompt and the round record.  Mirror-image rule: an
``accept:`` answer adopts the offer's terms verbatim — acceptor ``terms`` that differ materially
are recorded as a counter-offer, never as an agreement (``world_model.terms_restate_offer``).
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services import world_model as wm  # noqa: E402
from app.services import world_update as wu  # noqa: E402
from app.services.agent_decision import build_decision_prompt, build_option_menu, parse_decision  # noqa: E402


def _world():
    w = wm.WorldModel(question="Will a deal be signed?", as_of_date="2026-09-30", scenarios=("Deal", "No deal"))
    w.add_actor(wm.ActorState(0, "Ministry", agency_class="sovereign_government", capacity_per_round=3))
    w.add_actor(wm.ActorState(1, "Agency", agency_class="regulator_agency", capacity_per_round=3))
    w.add_actor(wm.ActorState(2, "Union", agency_class="labor_union", capacity_per_round=3))
    w.set_period_labels({1: "2026-10", 2: "2026-11", 3: "2026-12", 4: "2027-01", 5: "2027-02"})
    return w


def _decision(agent_id, option_id, *, targets=(), terms="", statement="", kind="coalition", lag=1, status="ok"):
    return {"agent_id": agent_id, "option": {"id": option_id, "label": option_id.replace("_", " "), "kind": kind,
                                             "cost": 1, "lag": lag, "reversibility": "reversible"},
            "targets": list(targets), "magnitude": 0.6, "public_statement": statement, "terms": terms,
            "status": status}


def _round(w, n, decisions):
    return wu.deterministic_round_update(w, n, {"label": w.period_labels.get(n, f"period {n}")}, decisions, [], None)


# ----------------------------------------------------------------------------- opening and answering
def test_proposal_opens_an_offer_the_recipient_must_answer():
    w = _world()
    det = _round(w, 1, [_decision(0, "open_talks", targets=["Agency"], terms="Lift the ban in exchange for audits")])
    assert len(det["offers_opened"]) == 1 and "[i1_1]" in det["offers_opened"][0]
    inter = w.interactions["i1_1"]
    assert (inter.proposer, inter.recipient, inter.status, inter.expires_round) == (0, 1, "open", 3)
    assert inter.terms == "Lift the ban in exchange for audits"
    w.commit_round(1)
    # the recipient's menu: four bound answers first, no duplicated generic "respond" entries
    w.start_round(2, {"label": "2026-11"})
    menu = build_option_menu(w.actors[1], w, 2)
    ids = [o["id"] for o in menu]
    assert ids[:4] == ["accept:i1_1", "counter:i1_1", "reject:i1_1", "defer:i1_1"]
    assert not any(i.startswith("respond_") for i in ids)
    assert menu[0]["suggested_targets"] == ["Ministry"] and menu[0]["interaction_id"] == "i1_1"
    assert "Lift the ban" in menu[0]["label"] and "binds both sides" in menu[0]["label"]
    assert "on exactly these terms" in menu[0]["label"]
    assert "adopts the offer's terms verbatim" in menu[0]["why"] and "recorded as a counter-offer" in menu[0]["why"]
    assert "counter-offer" not in menu[1]["why"]
    # the proposer's menu carries no answer entry
    assert not any(":" in o["id"] for o in build_option_menu(w.actors[0], w, 2))
    # briefs
    pub = w.render_public_brief(upto_round=1)
    assert "## Offers and agreements" in pub and "Ministry made an offer to Agency [i1_1]" in pub
    priv = w.render_private_brief(1, upto_round=1)
    assert "Offers awaiting YOUR answer" in priv and "[i1_1] from Ministry: Lift the ban" in priv
    assert "Your offers awaiting an answer: to Agency [i1_1]" in w.render_private_brief(0, upto_round=1)


def test_accept_binds_both_parties_and_moves_the_relationship():
    w = _world()
    _round(w, 1, [_decision(0, "form_alliance", targets=["Agency"], terms="Joint task force by December")])
    w.commit_round(1)
    det = _round(w, 2, [_decision(1, "accept:i1_1", statement="We accept the joint task force.", lag=1)])
    inter = w.interactions["i1_1"]
    assert inter.status == "accepted" and inter.resolved_round == 2 and inter.response.startswith("We accept")
    assert len(det["offers_answered"]) == 1 and det["offers_answered"][0].startswith("Agreement [i1_1]: Agency accepted")
    for aid in (0, 1):
        pend = w.actors[aid].pending_commitments()
        assert len(pend) == 1 and pend[0]["source"] == "agreement:i1_1" and pend[0]["due_round"] == 3
        assert pend[0]["counterparty"] == 1 - aid and "Honour the agreement with" in pend[0]["description"]
    assert set(inter.obligations) == {w.actors[0].commitments[0]["id"], w.actors[1].commitments[0]["id"]}
    rel = w._relationship_between(0, 1)
    assert rel is not None and rel.polarity > 0 and rel.last_changed_round == 2
    assert w.agreements_between(0, 1) == [inter]
    # the agreement is visible in the digest and the record diff
    digest = wu.build_round_digest(w, 2, w.snapshot(), [])
    assert "Offers and agreements:" in digest and "Agreement [i1_1]" in digest
    # Unrelated statements do not deliver the obligation; it stays due this period.
    w.commit_round(2)
    _round(w, 3, [_decision(0, "public_statement", kind="communication", lag=0),
                  _decision(1, "public_statement", kind="communication", lag=0)])
    assert all(c["status"] == "due" for a in (0, 1) for c in w.actors[a].commitments)
    assert not w.events_in_round(3, ("breach",))


def test_reject_counter_and_defer():
    w = _world()
    _round(w, 1, [_decision(0, "open_talks", targets=["Agency"], terms="A"),
                  _decision(2, "bargain", targets=["Agency"], terms="B")])
    w.commit_round(1)
    polarity_after_offer = w._relationship_between(0, 1).polarity      # the offer itself pulled them closer
    det = _round(w, 2, [_decision(1, "reject:i1_1", statement="No.")])
    assert w.interactions["i1_1"].status == "rejected" and det["offers_answered"][0].startswith("Agency rejected Ministry's offer")
    assert w._relationship_between(0, 1).polarity < polarity_after_offer
    # defer keeps the second offer open, then a counter opens a counter-offer back to the Union
    w.commit_round(2)
    det = _round(w, 3, [_decision(1, "defer:i1_2")])
    assert w.interactions["i1_2"].status == "deferred" and w.interactions["i1_2"].is_open()
    assert "deferred its answer" in det["offers_answered"][0]
    assert [o["id"] for o in build_option_menu(w.actors[1], w, 4)][:4] == ["accept:i1_2", "counter:i1_2", "reject:i1_2", "defer:i1_2"]
    w.commit_round(3)
    det = _round(w, 4, [_decision(1, "counter:i1_2", terms="B minus the clause", statement="Counter.")])
    assert w.interactions["i1_2"].status == "countered"
    child = w.interactions["i4_3"]
    assert (child.kind, child.proposer, child.recipient, child.parent_id, child.terms) == ("counter", 1, 2, "i1_2", "B minus the clause")
    assert len(det["offers_opened"]) == 1 and "counter-offer to Union [i4_3]" in det["offers_opened"][0]
    assert [o["id"] for o in build_option_menu(w.actors[2], w, 5)][0] == "accept:i4_3"
    # an answer to an offer that is not open is recorded, not applied
    w.commit_round(4)
    _round(w, 5, [_decision(0, "accept:i1_1")])
    assert w.interactions["i1_1"].status == "rejected"
    assert any("no longer open" in e.description for e in w.events_in_round(5, ("system",)))


def test_unanswered_offers_lapse_after_the_ttl():
    w = _world()
    _round(w, 1, [_decision(0, "open_talks", targets=["Agency"], terms="T")])
    for n in (2, 3):
        w.commit_round(n - 1)
        det = _round(w, n, [])
        assert det["offers_lapsed"] == [] and w.interactions["i1_1"].is_open()
    w.commit_round(3)
    det = _round(w, 4, [])
    assert w.interactions["i1_1"].status == "lapsed" and det["offers_lapsed"] == ["Ministry → Agency: T"]
    assert any("lapsed unanswered" in e.description for e in w.events_in_round(4, ("offer",)))
    assert build_option_menu(w.actors[1], w, 4)[0]["id"].startswith(("plan_", "public_statement", "respond_"))


def test_lapsed_obligation_and_withdrawal_are_breaches():
    w = _world()
    _round(w, 1, [_decision(0, "sign_agreement", targets=["Agency"], terms="Deliver audits in November")])
    w.commit_round(1)
    _round(w, 2, [_decision(1, "accept:i1_1", lag=1)])                 # obligations due round 3
    w.commit_round(2)
    rep_before = w.actors[1].reputation
    w.start_round(3, {"label": "2026-12"})
    promise = w.actors[0].pending_commitments()[0]
    move = parse_decision({"option_id": "fulfill:" + promise["id"],
                           "public_statement": "We delivered the promised audited schedule."},
                          actor=w.actors[0], world=w, options=build_option_menu(w.actors[0], w, 3),
                          scenarios=w.scenarios, round_num=3)
    _round(w, 3, [move.to_dict()])
    update, problems = wu.validate_arbiter_update({"action_resolutions": [{"actor": "Ministry", "outcome": "success",
        "commitment_id": promise["id"], "action_round": 3, "rationale": "The promised audited schedule was delivered."}]}, w)
    assert not problems
    w.apply_arbiter_update(3, update)  # Ministry delivers; Agency still owes its own obligation.
    w.commit_round(3)
    det = _round(w, 4, [])                                               # Agency's obligation lapses → breach
    assert w.interactions["i1_1"].status == "breached"
    assert len(det["breaches"]) == 1 and det["breaches"][0].startswith("Breach [i1_1]: Agency broke its agreement with Ministry")
    assert w.actors[1].reputation < rep_before
    assert w.actors[1].commitments[0]["status"] == "breached"
    assert w._relationship_between(0, 1).valence in ("adversarial", "neutral", "transactional")
    # explicit withdrawal from an agreement in force
    w2 = _world()
    _round(w2, 1, [_decision(0, "form_alliance", targets=["Union"], terms="Pact")])
    w2.commit_round(1)
    _round(w2, 2, [_decision(2, "accept:i1_1", lag=3)])
    w2.commit_round(2)
    det = _round(w2, 3, [_decision(0, "break_alliance", targets=["Union"])])
    assert w2.interactions["i1_1"].status == "breached" and len(det["breaches"]) == 1
    assert w2.actors[0].commitments[0]["status"] == "breached" and w2.actors[2].commitments[0]["status"] == "released"
    assert "Ministry withdrew" in det["breaches"][0]


def test_answering_an_unrelated_offer_does_not_discharge_a_due_obligation():
    """New consent is distinct from delivery of the actor's earlier accepted promise."""
    w = _world()
    _round(w, 1, [_decision(0, "sign_agreement", targets=["Agency"], terms="Deliver audits in November"),
                  _decision(2, "open_talks", targets=["Agency"], terms="Joint hearing in December")])
    w.commit_round(1)
    _round(w, 2, [_decision(1, "accept:i1_1", lag=1)])                 # Agency's obligation to Ministry due round 3
    w.commit_round(2)
    assert w.actors[1].pending_commitments()[0]["due_round"] == 3
    # round 3: the Ministry acts; the Agency's only move is its answer to the Union's open offer
    det = _round(w, 3, [_decision(0, "public_statement", kind="communication", lag=0),
                        _decision(1, "accept:i1_2", lag=1)])
    assert w.interactions["i1_2"].status == "accepted"
    assert all(c["status"] == "due" for c in w.actors[1].commitments if c.get("source") == "agreement:i1_1")
    assert not det["breaches"] and not w.events_in_round(3, ("breach",))
    w.commit_round(3)
    det4 = _round(w, 4, [_decision(0, "public_statement", kind="communication", lag=0),
                         _decision(1, "public_statement", kind="communication", lag=0)])
    assert w.interactions["i1_1"].status == "breached" and det4["breaches"]
    assert w.interactions["i1_2"].status == "accepted"


# ----------------------------------------------------------------------------- contract, prompt, persistence
def test_decision_contract_carries_terms_and_bound_answers_parse():
    w = _world()
    _round(w, 1, [_decision(0, "open_talks", targets=["Agency"], terms="T")])
    w.commit_round(1)
    w.start_round(2, {"label": "2026-11"})
    actor = w.actors[1]
    menu = build_option_menu(actor, w, 2)
    prompt = build_decision_prompt(actor, world_clock="# CLOCK", public_brief=w.render_public_brief(upto_round=1),
                                   private_brief=w.render_private_brief(1, upto_round=1), options=menu,
                                   scenarios=w.scenarios, cast_names=["Ministry", "Agency", "Union"])
    assert '"terms": "<offer or counter-offer terms> | null"' in prompt and "binds nobody until the other side accepts" in prompt
    assert "an accept answer adopts the offer's terms verbatim" in prompt
    assert "an accept whose terms differ materially is recorded as a counter-offer, not an agreement" in prompt
    assert "[counter:i1_1]" in prompt
    d = parse_decision({"option_id": "counter:i1_1", "terms": "  T minus clause 3  ", "public_statement": "We counter.",
                        "magnitude": 0.7}, actor=actor, world=w, options=menu, scenarios=w.scenarios, round_num=2)
    assert d.ok and d.option["id"] == "counter:i1_1" and d.terms == "T minus clause 3" and d.targets == ["Ministry"]
    assert d.to_dict()["terms"] == "T minus clause 3"
    assert parse_decision({"option_id": "accept:i9_9"}, actor=actor, world=w, options=menu, scenarios=w.scenarios,
                          round_num=2).status == "invalid"


def test_arbiter_prompt_lists_offers_and_state_round_trips():
    w = _world()
    det = _round(w, 1, [_decision(0, "open_talks", targets=["Agency"], terms="T")])
    prompt = wu.build_arbiter_prompt(w, 1, {"label": "2026-10"}, [], det, w.scenarios)
    assert "## Offers and agreements (settled only by the parties' answers — never assume consent)" in prompt
    assert "Ministry made an offer to Agency [i1_1]: T" in prompt and "Still open: Ministry → Agency [i1_1]: T" in prompt
    w.commit_round(1)
    before = w.snapshot()
    _round(w, 2, [_decision(1, "accept:i1_1", lag=1)])
    diff = w.diff(before)
    assert diff["interactions_changed"] == [{"id": "i1_1", "from": "open", "to": "accepted", "kind": "proposal",
                                             "proposer": "Ministry", "recipient": "Agency", "terms": "T"}]
    again = wm.WorldModel.from_dict(w.to_dict())
    assert again.interactions["i1_1"].to_dict() == w.interactions["i1_1"].to_dict()
    assert again._interaction_seq == w._interaction_seq
    assert again.actors[0].commitments == w.actors[0].commitments
    # a fresh offer after loading continues the id sequence
    again.start_round(3, {"label": "2026-12"})
    ev = again.open_interaction(3, 2, 0, "bargain", "X")
    assert ev.description.startswith("Union made an offer to Ministry [i3_2]")


# ----------------------------------------------------------------------------- accept on different terms (mirror-image rule)
_OFFER = "Compensation conformity in exchange for a 2027 baseline anchored to 4.87 mb/d"
_NARROWED = "The Secretariat records the conformity data submitted and circulates it to members"


@pytest.mark.parametrize("answer, restates", [
    ("", True),                                                                   # no terms: adopts the offer
    (_OFFER, True),                                                               # verbatim
    ("a 2027 baseline anchored to 4.87 mb/d", True),                             # a fragment of the offer
    ("Accepted as proposed.", True),                                              # a bare acknowledgement
    ("We accept the offer [i1_1] as stated.", True),                              # boilerplate plus the offer id
    ("Agreed: compensation conformity for a 2027 baseline anchored at 4.87 mb/d", True),   # a restatement
    (_NARROWED, False),                                                           # the live narrowing (sim_1838cf014c0b)
    (_OFFER + ", plus $2bn in compensation", False),                              # an added figure
    ("Compensation conformity in exchange for a 2028 baseline anchored to 4.87 mb/d", False),   # a changed date
    ("Conformity data first; the baseline question goes to the ministerial", False),         # different substance
])
def test_terms_restate_offer_rule(answer, restates):
    assert wm.terms_restate_offer(_OFFER, answer) is restates


def test_terms_restate_offer_compares_cjk_text_as_character_bigrams():
    offer = "十二月前成立联合工作组"
    assert wm.terms_restate_offer(offer, "我们接受：十二月前成立联合工作组") is True
    assert wm.terms_restate_offer(offer, "成立联合工作组") is True
    assert wm.terms_restate_offer(offer, "仅记录贵方提交的数据并转发成员国") is False
    assert wm._terms_tokens("2027年基线 [i3_4]") == ["2027", "年基", "基线"]
    assert wm.ACCEPT_TERMS_OVERLAP_MIN == 0.6 and wm.ACCEPT_TERMS_MIN_TOKENS == 3


def test_accept_on_materially_different_terms_is_recorded_as_a_counter():
    w = _world()
    _round(w, 1, [_decision(2, "open_talks", targets=["Agency"], terms=_OFFER)])
    w.commit_round(1)
    before = w.snapshot()
    polarity = w._relationship_between(2, 1).polarity
    det = _round(w, 2, [_decision(1, "accept:i1_1", statement="We take note of the conformity data.", terms=_NARROWED)])
    inter = w.interactions["i1_1"]
    # no agreement: no obligations on either side, no acceptance bonus to the relationship
    assert inter.status == "countered" and inter.resolved_round == 2 and inter.obligations == []
    assert inter.response == "We take note of the conformity data."
    assert not w.events_in_round(2, ("agreement",)) and w.agreements_between(1, 2) == []
    assert all(a.commitments == [] for a in w.actors.values())
    assert w._relationship_between(2, 1).polarity == polarity
    # the round record says what happened and why
    [answered] = det["offers_answered"]
    assert answered.startswith("Agency answered Union's offer [i1_1] with different terms")
    assert "recorded as a counter-offer, not an acceptance" in answered and "adopts the offer's terms verbatim" in answered
    # a counter-offer carrying the acceptor's terms goes back to the proposer
    child = w.interactions["i2_2"]
    assert (child.kind, child.proposer, child.recipient, child.parent_id, child.status) == ("counter", 1, 2, "i1_1", "open")
    assert child.terms == _NARROWED
    assert len(det["offers_opened"]) == 1 and "counter-offer to Union [i2_2]" in det["offers_opened"][0]
    changed = {c["id"]: (c["from"], c["to"]) for c in w.diff(before)["interactions_changed"]}
    assert changed["i1_1"] == ("open", "countered") and changed["i2_2"][1] == "open"
    digest = wu.build_round_digest(w, 2, before, [])
    assert "recorded as a counter-offer" in digest and "Agreement" not in digest
    # the proposer now owes the answer; the acceptor has nothing left to answer
    w.commit_round(2)
    assert [o["id"] for o in build_option_menu(w.actors[2], w, 3)][:4] == ["accept:i2_2", "counter:i2_2", "reject:i2_2", "defer:i2_2"]
    assert not any(":" in o["id"] for o in build_option_menu(w.actors[1], w, 3))
    # accepting the counter as it stands binds both sides to the acceptor's terms
    det = _round(w, 3, [_decision(2, "accept:i2_2", lag=1)])
    assert w.interactions["i2_2"].status == "accepted"
    assert det["offers_answered"][0].startswith("Agreement [i2_2]: Union accepted Agency's offer — The Secretariat records")
    for aid in (1, 2):
        pend = w.actors[aid].pending_commitments()
        assert len(pend) == 1 and pend[0]["source"] == "agreement:i2_2" and _NARROWED in pend[0]["description"]


@pytest.mark.parametrize("terms", ["", "Joint task force by December", "joint task force",
                                   "Agreed — joint task force by December.", "Accepted as proposed.",
                                   "We accept your offer [i1_1]."])
def test_accept_with_empty_or_restated_terms_binds_as_an_acceptance(terms):
    w = _world()
    _round(w, 1, [_decision(0, "form_alliance", targets=["Agency"], terms="Joint task force by December")])
    w.commit_round(1)
    det = _round(w, 2, [_decision(1, "accept:i1_1", terms=terms, lag=1)])
    inter = w.interactions["i1_1"]
    assert inter.status == "accepted" and len(inter.obligations) == 2 and len(w.interactions) == 1
    assert det["offers_opened"] == [] and len(det["offers_answered"]) == 1
    assert det["offers_answered"][0].startswith("Agreement [i1_1]: Agency accepted Ministry's offer — Joint task force by December")
    # both obligations carry the offer's terms, never the acceptor's wording
    for aid in (0, 1):
        pend = w.actors[aid].pending_commitments()
        assert len(pend) == 1 and pend[0]["description"].endswith("Joint task force by December")
