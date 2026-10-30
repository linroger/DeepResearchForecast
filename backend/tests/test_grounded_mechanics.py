"""Real OASIS reducers/menus with pinned causal mechanics; no provider boundary."""
from copy import deepcopy
import json

import pytest

from app.services import agent_decision as ad
from app.services.world_model import StateVariable, WorldModel

PINS = {"action_policy": "affordable-menu-v2", "agreement_policy": "operative-deadline-v1"}


def world(settings=None, capacity=3):
    w = WorldModel.from_seed({"settings": PINS if settings is None else settings,
        "as_of_date": "2026-01-01", "horizon_date": "2026-06-30", "actors": [
            {"agent_id": 0, "name": "Alpha", "agency_class": "sovereign_government",
             "capacity_per_round": capacity, "documented_plans": ["Invest in a factory"]},
            {"agent_id": 1, "name": "Beta", "agency_class": "firm", "capacity_per_round": capacity}]})
    w.start_round(1, {"period_start": "2026-01-02", "period_end": "2026-01-31"})
    return w


def period(w, n, start, end):
    w.commit_round(n - 1)
    w.start_round(n, {"period_start": start, "period_end": end})
    w.lapse_overdue_commitments(n)
    w.lapse_expired_interactions(n)


def terms(**kw):
    return {"schema_version": "operative-terms/v1", "effective_on": "2026-03-01",
            "delivery_deadline": "2026-05-15", "fulfillment_condition": "Both parties deliver the agreed report.", **kw}


def move(w, aid=0, oid="open_talks", **kw):
    actor = w.actors[aid]
    opts = ad.build_option_menu(actor, w, w.round, max_options=512)
    raw = {"option_id": oid, "targets": ["Beta" if aid == 0 else "Alpha"],
           "public_statement": "We take this action.", **kw}
    return ad.parse_decision(raw, actor=actor, world=w, options=opts, scenarios=[], round_num=w.round).to_dict()


def open_offer(w, operative=None):
    d = move(w, terms="Deliver the agreed report.", operative_terms=operative or terms())
    assert d["status"] == "ok"
    w.register_decisions(w.round, [d])
    return next(reversed(w.interactions.values()))


@pytest.mark.parametrize("key", list(PINS))
@pytest.mark.parametrize("value", [None, "future", True, {}])
def test_unknown_explicit_policy_rejected(key, value):
    with pytest.raises(ValueError, match="policy"):
        world({key: value})


def test_no_discounted_plans_custom_overspend_or_forged_catalog_cost():
    w = world(capacity=1)
    menu = ad.build_option_menu(w.actors[0], w, 1)
    assert "plan_1" not in {o["id"] for o in menu}
    d = move(w, oid="custom", custom_action={"kind": "economic", "label": "Invest"})
    assert d["status"] == "invalid"
    forged = {"agent_id": 0, "round": 1, "status": "ok", "targets": [1],
              "option": {"id": "security_action", "kind": "coercive", "cost": 0, "lag": 0},
              "commitment": {"description": "Spend", "due_periods": 1},
              "alliance_moves": [{"target": "Beta", "move": "break"}]}
    before = w.actors[0].to_dict()
    w.register_decisions(1, [forged])
    assert w.actors[0].to_dict() == before and not w.relationships and not w.interactions
    assert w.last_decision_admissions[0]["status"] == "invalid"


def test_valid_then_over_capacity_has_no_actor_mutations_in_pinned_and_unpinned_worlds():
    w = world(capacity=2)
    d = move(w, oid="custom", custom_action={"kind": "operational", "label": "Deliver supplies"})
    assert d["status"] == "ok"
    w.register_decisions(1, [d])
    assert w.actors[0].capacity_used == 2
    before = deepcopy(w.actors[0].to_dict())
    w.register_decisions(1, [d])
    assert w.actors[0].to_dict() == before
    assert w.last_decision_admissions[0]["status"] == "invalid"
    old = world({}, capacity=1)
    old_before = deepcopy(old.actors[0].to_dict())
    old.register_decisions(1, [d])
    # C11's unconditional feasibility fix supersedes the old unpinned cost
    # clamp/plan discount. Explicit menu policy still owns fulfill semantics.
    assert old.actors[0].capacity_used == old_before["capacity_used"]
    assert old.actors[0].commitments == old_before["commitments"]
    assert not old.relationships
    assert old.actors[0].action_rejections and old.actors[0].last_action["status"] == "invalid"
    assert old.last_decision_admissions[0]["status"] == "invalid"
    assert "plan_1" not in {o["id"] for o in ad.build_option_menu(old.actors[0], old, 1)}


def test_fair_menu_keeps_urgent_delivery_offer_choices_and_rotates_substantive_actions():
    w = world()
    for _ in range(3):
        w.open_interaction(1, 1, 0, "open_talks", "Deliver the agreed report.", operative_terms=terms())
    c = w.actors[0].add_commitment("Deliver own report", made_round=1, due_round=2)
    period(w, 2, "2026-02-01", "2026-02-28")
    menu = ad.build_option_menu(w.actors[0], w, 2)
    ids = {o["id"] for o in menu}
    assert len(menu) <= 10 and menu[-1]["id"] == "hold_position"
    assert "fulfill:" + c["id"] in ids
    assert any(o["kind"] not in ("communication", "wait") and ":" not in o["id"] for o in menu)
    for iid in {o["interaction_id"] for o in menu if "interaction_id" in o}:
        assert {f"{verb}:{iid}" for verb in ("accept", "counter", "reject", "defer")} <= ids
    seen = set()
    for n in range(2, 18):
        seen.update(o["id"] for o in ad.build_option_menu(w.actors[0], w, n))
    assert {"security_action", "sign_agreement"} <= seen


def test_typed_agreement_exact_consent_deadline_and_checkpoint(tmp_path):
    w = world()
    inter = open_offer(w)
    period(w, 2, "2026-02-01", "2026-02-28")
    invalid = move(w, 1, "accept:" + inter.id, accepted_terms_hash="0" * 64)
    assert invalid["status"] == "invalid" and inter.status == "open"
    d = move(w, 1, "accept:" + inter.id, accepted_terms_hash=inter.operative_terms_hash)
    assert d["status"] == "ok"
    w.register_decisions(2, [d])
    assert inter.status == "accepted"
    for a in w.actors.values():
        assert a.commitments[0]["due_round"] is None
        assert a.commitments[0]["operative_terms"] == terms()
    path = tmp_path / "checkpoint.json"
    path.write_text(json.dumps(w.to_dict()))
    w = WorldModel.from_dict(json.loads(path.read_text()))
    period(w, 3, "2026-03-01", "2026-03-31")
    assert w.actors[0].commitments[0]["status"] == "pending"
    period(w, 4, "2026-05-01", "2026-05-31")
    c = w.actors[0].commitments[0]
    assert c["status"] == "due" and w.delivery_commitment(0, c["id"], 4)
    assert w.commitment_timing(c, 4) == (True, False)
    assert "2026-05-15" in w.render_private_brief(0, upto_round=4)
    menu = ad.build_option_menu(w.actors[0], w, 4)
    delivery = next(o for o in menu if o["id"] == "fulfill:" + c["id"])
    assert delivery["operative_terms"]["fulfillment_condition"] == terms()["fulfillment_condition"]
    assert delivery["accepted_terms_hash"] == c["operative_terms_hash"]
    period(w, 5, "2026-06-01", "2026-06-30")
    assert w.actors[0].commitments[0]["status"] == "breached"


@pytest.mark.parametrize("operative", [terms(delivery_deadline="2027-05-01"),
    terms(delivery_deadline=None, duration_days=90)])
def test_beyond_horizon_and_duration_without_deadline_remain_pending(operative):
    w = world()
    inter = open_offer(w, operative)
    period(w, 2, "2026-02-01", "2026-02-28")
    w.register_decisions(2, [move(w, 1, "accept:" + inter.id, accepted_terms_hash=inter.operative_terms_hash)])
    period(w, 3, "2026-06-01", "2026-06-30")
    assert all(a.commitments[0]["status"] == "pending" for a in w.actors.values())


def test_anchor_metadata_is_detached_immutable_and_survives_changes_and_reload():
    anchor = {"series_id": "source:capacity", "value": 10, "unit": "MW", "provenance": {"status": "observed"}}
    w = world()
    w.add_variable("Capacity", 10, unit="MW", provenance="official", research_evidence=anchor)
    anchor["provenance"]["status"] = "modified"
    v = w.variables["capacity"]
    expected = {**anchor, "provenance": {"status": "observed"}}
    v.set_value(12, round_num=1, source="arbiter", cause="simulated change")
    record = v.to_dict()
    assert record["provenance"] == "arbiter" and record["research_evidence"] == expected
    record["research_evidence"]["value"] = 999
    assert v.to_dict()["research_evidence"] == expected
    w = WorldModel.from_dict(json.loads(json.dumps(w.to_dict())))
    assert w.variables["capacity"].to_dict()["research_evidence"] == expected
    assert "research_evidence" not in StateVariable("old", "Old", 1).to_dict()


@pytest.mark.parametrize("anchor", [[1], {"x": float("nan")}, {1: "bad"}, {"x": object()}])
def test_anchor_metadata_rejects_non_json(anchor):
    with pytest.raises(ValueError, match="research_evidence"):
        StateVariable("x", "X", 1, research_evidence=anchor)


def test_zero_capacity_is_preserved_and_fulfillment_never_spends_missing_capacity():
    w = world(capacity=0)
    c = w.actors[0].add_commitment("Deliver own report", made_round=0, due_round=2)
    assert w.actors[0].capacity_per_round == 0
    assert [o["id"] for o in ad.build_option_menu(w.actors[0], w, 1)] == ["hold_position"]
    d = {"agent_id": 0, "round": 1, "status": "ok", "targets": [],
         "option": {"id": "fulfill:" + c["id"], "kind": "operational", "cost": 1, "lag": 0}}
    before = deepcopy(w.actors[0].to_dict())
    w.register_decisions(1, [d])
    assert w.actors[0].to_dict() == before
    restored = WorldModel.from_dict(json.loads(json.dumps(w.to_dict())))
    assert restored.actors[0].capacity_per_round == 0


def test_fulfillment_binding_is_exact_and_positive_attempt_survives_reload():
    w = world()
    c = w.actors[0].add_commitment("Deliver own report", made_round=0, due_round=2)
    forged = move(w, oid="fulfill:" + c["id"], targets=[1])
    assert forged["status"] == "invalid"
    good = move(w, oid="fulfill:" + c["id"], targets=[])
    assert good["status"] == "ok"
    w.register_decisions(1, [good])
    assert w.actors[0].capacity_used == 1 and c["last_fulfillment_attempt"]["outcome"] == "unverified"
    w = WorldModel.from_dict(json.loads(json.dumps(w.to_dict())))
    before = deepcopy(w.actors[0].to_dict())
    w.register_decisions(1, [good])
    assert w.actors[0].to_dict() == before
    assert w.last_decision_admissions[0]["status"] == "invalid"


def test_counteroffer_requires_new_typed_terms_and_exact_acceptance_reference():
    w = world()
    inter = open_offer(w)
    period(w, 2, "2026-02-01", "2026-02-28")
    changed = terms(delivery_deadline="2026-06-15")
    bad = move(w, 1, "accept:" + inter.id, accepted_terms_hash=inter.operative_terms_hash,
               operative_terms=changed)
    assert bad["status"] == "invalid"
    d = move(w, 1, "counter:" + inter.id, terms="Deliver a revised agreed report.", operative_terms=changed)
    assert d["status"] == "ok"
    w.register_decisions(2, [d])
    counter = list(w.interactions.values())[-1]
    assert inter.status == "countered" and counter.operative_terms == changed
    assert counter.operative_terms_hash != inter.operative_terms_hash
    period(w, 3, "2026-03-01", "2026-03-31")
    assert move(w, 0, "accept:" + counter.id, accepted_terms_hash=inter.operative_terms_hash)["status"] == "invalid"
    accepted = move(w, 0, "accept:" + counter.id, accepted_terms_hash=counter.operative_terms_hash)
    w.register_decisions(3, [accepted])
    assert counter.status == "accepted"
    assert w.actors[0].commitments[0]["operative_terms"]["delivery_deadline"] == "2026-06-15"


def test_offer_expiry_is_separate_from_duration_and_delivery_deadline():
    w = world()
    inter = open_offer(w, terms(offer_expires_on="2026-03-15"))
    period(w, 4, "2026-03-01", "2026-03-31")
    assert inter.is_open()  # explicit date supersedes the generic two-round TTL
    w.resolve_interaction(4, inter.id, "defer", 1)
    assert inter.operative_terms["offer_expires_on"] == "2026-03-15"
    period(w, 5, "2026-04-01", "2026-04-30")
    assert inter.status == "lapsed" and not w.actors[0].commitments


@pytest.mark.parametrize("change", [
    {"delivery_deadline": "2026-01-01"}, {"effective_on": "2026-2-1"}, {"duration_days": True},
    {"duration_days": 90, "effective_on": None}, {"fulfillment_condition": ""}, {"unknown": 1}])
def test_invalid_operative_offer_rejected_before_sequence_or_actor_mutation(change):
    w = world()
    before = w.to_dict()
    with pytest.raises(ValueError):
        w.open_interaction(1, 0, 1, "open_talks", "Terms", operative_terms=terms(**change))
    assert w.to_dict() == before
    d = move(w, operative_terms=terms(**change), terms="Terms")
    assert d["status"] == "invalid"
    w.register_decisions(1, [d])
    assert not w.interactions and w.actors[0].capacity_used == 0


def test_checkpoint_rejects_changed_operative_binding_and_present_unknown_policy():
    w = world()
    inter = open_offer(w)
    period(w, 2, "2026-02-01", "2026-02-28")
    w.register_decisions(2, [move(w, 1, "accept:" + inter.id, accepted_terms_hash=inter.operative_terms_hash)])
    saved = w.to_dict()
    cases = []
    bad = deepcopy(saved); bad["settings"]["action_policy"] = "future"; cases.append(bad)
    bad = deepcopy(saved); bad["interactions"][0]["operative_terms"]["delivery_deadline"] = "2026-06-01"; cases.append(bad)
    bad = deepcopy(saved); del bad["interactions"][0]["operative_terms_hash"]; cases.append(bad)
    bad = deepcopy(saved); bad["actors"][0]["commitments"][0]["operative_terms"]["delivery_deadline"] = "2026-06-01"; cases.append(bad)
    for bad in cases:
        with pytest.raises(ValueError):
            WorldModel.from_dict(bad)


def test_observed_reference_keeps_full_native_unit_source_status_period_and_bundle():
    unit = "millions of inflation-adjusted national currency units (base year 2020)"
    evidence = {"bundle_sha256": "b" * 64, "source_refs": ["source-1", "source-2"],
                "status": "preliminary", "period": {"start": "2025-01-01", "end": "2025-12-31"},
                "unit": unit, "value": 12}
    w = WorldModel.from_seed({"state_variables": [{"id": "real_output", "name": "Real output", "value": 12,
        "unit": unit, "provenance": "official", "research_evidence": evidence}]})
    v = w.variables["real_output"]
    assert callable(v.research_anchor) and v.unit == unit
    for i in range(60):
        v.set_value(13 + i, round_num=i + 1, source="effect", cause="simulated")
    assert v.research_evidence == evidence
    copy = v.research_evidence; copy["source_refs"].clear()
    with pytest.raises(AttributeError):
        v.research_evidence = {}
    with pytest.raises(ValueError, match="immutable"):
        w.add_variable("Real output", 5, var_id="real_output", research_evidence={"value": 5})
    restored = WorldModel.from_dict(json.loads(json.dumps(w.to_dict())))
    assert restored.variables["real_output"].unit == unit
    assert restored.variables["real_output"].research_evidence == evidence


def test_actor_prompts_render_exact_operative_terms_and_prose_dates_do_not_become_deadlines():
    w = world()
    op = terms(delivery_deadline=None, duration_days=90)
    d = move(w, terms="On April 15 we will review the 90-day pause.", operative_terms=op)
    w.register_decisions(1, [d]); inter = next(iter(w.interactions.values()))
    period(w, 2, "2026-02-01", "2026-02-28")
    opts = ad.build_option_menu(w.actors[1], w, 2)
    prompt = ad.build_decision_prompt(w.actors[1], world_clock="February", public_brief="", private_brief="",
                                      options=opts, scenarios=[], cast_names=["Alpha", "Beta"])
    assert inter.operative_terms_hash in prompt and "fulfillment_condition" in prompt
    assert '"duration_days": 90' in prompt and '"delivery_deadline": null' in prompt
    assert "duration is NOT a delivery deadline" in prompt
    assert inter.operative_terms["delivery_deadline"] is None


def test_wait_cannot_create_free_commitments_or_alliance_effects():
    w = world()
    d = move(w, oid="hold_position", commitment={"description": "Unfunded pledge", "due_periods": 1},
             alliance_moves=[{"target": "Beta", "move": "break"}])
    w.register_decisions(1, [d])
    assert w.actors[0].capacity_used == 0
    assert not w.actors[0].commitments and not w.relationships


def test_current_checkpoint_cannot_downgrade_operative_terms_or_reset_spending():
    w = world()
    open_offer(w)
    data = w.to_dict()
    bad = deepcopy(data); del bad["settings"]["agreement_policy"]
    with pytest.raises(ValueError, match="policy"):
        WorldModel.from_dict(bad)
    for invalid in (-1, True, "0", 100):
        bad = deepcopy(data); bad["actors"][0]["capacity_used"] = invalid
        with pytest.raises(ValueError, match="capacity_used"):
            WorldModel.from_dict(bad)


def test_unpinned_direct_offer_ignores_new_metadata_and_keeps_old_serialization():
    old = world({})
    old.open_interaction(1, 0, 1, "open_talks", "Historic terms", operative_terms=terms())
    inter = next(iter(old.interactions.values()))
    assert "operative_terms" not in inter.to_dict()
    assert "operative_terms_hash" not in inter.to_dict()
    assert "operative_terms" not in move(old, oid="public_statement", operative_terms=terms())


def test_pruning_preserves_retained_typed_agreement_bindings():
    from app.services.world_model import INTERACTION_LIMIT
    w = world()
    inter = open_offer(w)
    period(w, 2, "2026-02-01", "2026-02-28")
    w.register_decisions(2, [move(w, 1, "accept:" + inter.id, accepted_terms_hash=inter.operative_terms_hash)])
    for _ in range(INTERACTION_LIMIT + 2):
        w.open_interaction(2, 0, 1, "open_talks", "Another offer", operative_terms=terms())
    assert inter.id in w.interactions
    restored = WorldModel.from_dict(json.loads(json.dumps(w.to_dict())))
    period(restored, 3, "2026-03-01", "2026-03-31")
    c = restored.actors[0].commitments[0]
    assert restored.delivery_commitment(0, c["id"], 3)


def test_raw_acceptance_terms_cannot_be_truncated_into_exact_consent():
    from app.services.world_model import INTERACTION_TERMS_MAX_CHARS
    w = world()
    original = "x" * (INTERACTION_TERMS_MAX_CHARS - 1) + "…"
    d = move(w, terms=original, operative_terms=terms())
    assert d["status"] == "ok"
    w.register_decisions(1, [d]); inter = next(iter(w.interactions.values()))
    assert inter.terms == original
    period(w, 2, "2026-02-01", "2026-02-28")
    changed = move(w, 1, "accept:" + inter.id, terms=original + " except we do not deliver", accepted_terms_hash=inter.operative_terms_hash)
    assert changed["status"] == "invalid"
    assert move(w, 1, "accept:" + inter.id, terms=[original], accepted_terms_hash=inter.operative_terms_hash)["status"] == "invalid"
    assert inter.status == "open" and not w.actors[0].commitments


def test_typed_offer_preserves_raw_prose_without_whitespace_normalization():
    w = world()
    original = "Deliver the  report.\n  Keep the annex attached."
    d = move(w, terms=original, operative_terms=terms())
    w.register_decisions(1, [d])
    inter = next(iter(w.interactions.values()))
    assert inter.terms == original
    period(w, 2, "2026-02-01", "2026-02-28")
    altered = move(w, 1, "accept:" + inter.id, terms=" ".join(original.split()), accepted_terms_hash=inter.operative_terms_hash)
    assert altered["status"] == "invalid"
    assert move(w, 1, "accept:" + inter.id, terms=original, accepted_terms_hash=inter.operative_terms_hash)["status"] == "ok"


def test_checkpoint_rejects_missing_typed_commitment_metadata():
    w = world()
    inter = open_offer(w)
    period(w, 2, "2026-02-01", "2026-02-28")
    w.register_decisions(2, [move(w, 1, "accept:" + inter.id, accepted_terms_hash=inter.operative_terms_hash)])
    for fields in (("operative_terms",), ("operative_terms", "operative_terms_hash")):
        bad = deepcopy(w.to_dict())
        for field in fields:
            del bad["actors"][0]["commitments"][0][field]
        with pytest.raises(ValueError, match="operative_terms"):
            WorldModel.from_dict(bad)


@pytest.mark.parametrize("delivery,limit", [(False, 5), (True, 6)])
def test_small_menu_budget_rejects_instead_of_silently_starving_offers(delivery, limit):
    w = world()
    w.open_interaction(1, 1, 0, "open_talks", "Terms", operative_terms=terms())
    if delivery:
        w.actors[0].add_commitment("Deliver", made_round=0, due_round=2)
    with pytest.raises(ValueError, match="max_options"):
        ad.build_option_menu(w.actors[0], w, 1, max_options=limit)
    menu = ad.build_option_menu(w.actors[0], w, 1, max_options=limit + 1)
    ids = {o["id"] for o in menu}
    assert {"accept:i1_1", "counter:i1_1", "reject:i1_1", "defer:i1_1"} <= ids


def test_mixed_response_groups_budget_for_largest_group_and_rotate():
    w = world()
    w.open_interaction(1, 1, 0, "open_talks", "Earlier offer", operative_terms=terms(delivery_deadline="2026-03-15"))
    period(w, 2, "2026-02-01", "2026-02-28")
    w.open_interaction(2, 1, 0, "open_talks", "Later offer", operative_terms=terms())
    period(w, 3, "2026-03-01", "2026-03-31")
    with pytest.raises(ValueError, match="max_options"):
        ad.build_option_menu(w.actors[0], w, 3, max_options=5)
    seen = set()
    for presented_round in (3, 4):
        menu = ad.build_option_menu(w.actors[0], w, presented_round, max_options=6)
        seen.update(o["id"] for o in menu)
    assert {"reject:i1_1", "accept:i2_2", "counter:i2_2", "reject:i2_2", "defer:i2_2"} <= seen
