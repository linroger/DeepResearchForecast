"""Historical replay and shared-helper boundaries; parent guard executes these.

The fixture contains three complete CLOSED historical traces. Tests use fresh
temporary stores, never an original evaluation directory or database. Scripted
zero usage verifies semantic replay; it does not replay historical billing.
"""
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest


pytestmark = pytest.mark.guarded_runner
QUANTITY_CASE = "m5-e2-investment-v3-s0-external-feedback-ablation"
WRONG_ID_CASE = "m5-investment-v2-s0-reflexive"
ALTERED_TERMS_CASE = "m5-investment-v1-s0-external-feedback-ablation"
FIXTURE_SHA256 = "4244407a0f4cd312ff19c8e5dc65f17febebe7afde800779ea7b37237dc9db1b"
EXPECTED = {
    QUANTITY_CASE: {
        "revision": "f09b1e3781287db33f9a6f72de70ce0d876f5db8314852db09113bb6a5575165",
        "intentId": "7bab2f8fe03e57e3a54f0ea79ad97b40", "slot": "4:proposal:buyer", "records": 19,
        "round": 4, "actorId": "buyer", "code": "invalid_input", "explanation": "Input above declared maximum",
    },
    WRONG_ID_CASE: {
        "revision": "d917eafbb90d103c03b441b63db84d8cf836ddf5aeb9c2b68943f72ff46d9a0b",
        "intentId": "4cfab7d76d2f58ebb72e714d01358ed3", "slot": "2:response:producer", "records": 20,
        "round": 2, "actorId": "producer", "code": "unavailable_offer", "explanation": "Offer is unavailable to this actor",
    },
    ALTERED_TERMS_CASE: {
        "revision": "1bef5cf14d1df1048c5f353033189e8c4e0d93a199842d6b1102c6ab9dab8eee",
        "intentId": "329e0dda03ad5e0db019e903a4b410a4", "slot": "2:response:producer", "records": 20,
        "round": 2, "actorId": "producer", "code": "invalid_input",
        "explanation": "Responses must reference exact terms without replacing them",
    },
}


@pytest.fixture
def api():
    from app.services.world_simulation import controller
    from app.services.world_simulation.contracts import WorldError, canonical_json, digest
    from app.services.world_simulation.kernel import _input_values
    from app.services.world_simulation.store import WorldStore

    return SimpleNamespace(controller=controller, Error=WorldError, canonical=canonical_json,
                           digest=digest, input_values=_input_values, Store=WorldStore)


@pytest.fixture
def historical(api, case_id):
    data = Path(__file__).with_name("fixtures").joinpath("world_rejected_replay_v2.json").read_bytes()
    assert len(data) < 8 * 1024 * 1024
    assert hashlib.sha256(data).hexdigest() == FIXTURE_SHA256
    collection = json.loads(data)
    assert collection["schemaVersion"] == "world-historical-replay-fixture/v2"
    assert len(collection["cases"]) == 3
    assert {case["caseId"] for case in collection["cases"]} == set(EXPECTED)
    fixture = next(case for case in collection["cases"] if case["caseId"] == case_id)
    expected = EXPECTED[case_id]
    assert fixture["schemaVersion"] == "world-historical-replay-fixture/v1"
    spec, trace, provenance = fixture["spec"], fixture["trace"], fixture["provenance"]
    assert api.digest(spec) == provenance["specCanonicalSha256"] == trace["head"]["specHash"]
    assert api.digest(trace) == provenance["traceCanonicalSha256"] == provenance["closedCaseReceipt"]["traceHash"]
    assert provenance["closedCaseReceipt"]["status"] == "completed"
    assert provenance["closedCaseReceipt"]["completedRound"] == 4
    assert provenance["closedCaseReceipt"]["errorCode"] is None
    assert provenance["closedCaseReceipt"]["evaluationId"] == case_id
    assert trace["head"]["revision"] == provenance["semanticHeadRevision"] == expected["revision"]
    assert len(trace["history"]) == 5 and len(trace["rounds"]) == 4
    assert len(trace["records"]) == expected["records"]
    assert [item["round"] for item in trace["history"]] == [0, 1, 2, 3, 4]
    by_slot = {record["slot"]: record for record in trace["records"]}
    assert len(by_slot) == expected["records"]
    record = by_slot[expected["slot"]]
    rejected = next(intent for intent in record["decision"]["intents"] if intent["intentId"] == expected["intentId"])
    if case_id == QUANTITY_CASE:
        assert rejected["parameters"] == {"price": "12", "quantity": "12"}
        purchase = next(item for item in spec["actionCatalog"] if item["templateId"] == "purchase")
        assert purchase["inputs"]["quantity"]["max"] == "10"
    elif case_id == WRONG_ID_CASE:
        assert rejected["operation"] == "accept" and rejected["parameters"] == {}
        assert rejected["interactionId"] == "f8e02d723e0454b6134dc3b36dcb1b"
        assert rejected["interactionId"] not in {item["interactionId"] for item in record["observation"]["inbox"]}
        assert record["observation"]["inbox"]
    else:
        assert rejected["operation"] == "accept"
        assert rejected["parameters"] == {"price": "2", "quantity": "2"}
        offer = next(item for item in record["observation"]["inbox"] if item["interactionId"] == rejected["interactionId"])
        assert rejected["termsVersion"] == offer["termsVersion"]
    assert [item for round_record in trace["rounds"] for item in round_record["resolutions"] if not item["accepted"]] == [{
        **{key: expected[key] for key in ("round", "actorId", "code", "explanation", "intentId")}, "accepted": False,
    }]
    return fixture


def _raw_decision(normalized):
    """Remove only fields synthesized by validate_decision, preserving inputs."""
    raw = deepcopy(normalized)
    for key in ("decisionId", "round", "phase"):
        raw.pop(key)
    for intent in raw["intents"]:
        for key in ("intentId", "actorId", "phase"):
            intent.pop(key)
    return raw


class ScriptedReplayPolicy:
    external = False

    def __init__(self, records):
        self.records = {record["slot"]: deepcopy(record) for record in records}
        self.calls = []
        self._lock = threading.Lock()

    def decide(self, observation):
        slot = f"{observation['round']}:{observation['phase']}:{observation['actorId']}"
        record = self.records[slot]
        assert observation == record["observation"], slot
        with self._lock:
            assert slot not in self.calls, f"Historical replay unexpectedly retried {slot}"
            self.calls.append(slot)
        return _raw_decision(record["decision"])


def _assert_committed_trace(store, historical):
    trace = historical["trace"]
    expected = EXPECTED[historical["caseId"]]
    assert store.head() == trace["head"]
    assert store.head()["revision"] == expected["revision"]
    assert store.history() == trace["history"]
    assert store.rounds() == trace["rounds"]
    expected_events = trace["history"][0].get("initialEvents", []) + [
        event for item in trace["rounds"] for event in item["events"]]
    expected_resolutions = [resolution for item in trace["rounds"] for resolution in item["resolutions"]]
    assert store.events() == expected_events
    assert store.resolutions() == expected_resolutions
    for record in trace["records"]:
        assert store.observation(record["slot"]) == record["observation"]
        assert store.decision(record["slot"]) == record["decision"]
    rejected = next(item for item in store.resolutions() if item["intentId"] == expected["intentId"])
    assert rejected["round"] == expected["round"] and rejected["accepted"] is False
    assert rejected["code"] == expected["code"] and rejected["explanation"] == expected["explanation"]


@pytest.mark.parametrize("case_id,cache_fourth_round", [
    (QUANTITY_CASE, False), (WRONG_ID_CASE, False), (ALTERED_TERMS_CASE, False), (QUANTITY_CASE, True),
], ids=["v2-quantity", "original-wrong-id", "original-altered-accept-terms", "v2-cached-rejected-decision"])
def test_closed_historical_rejections_replay_exactly_through_controller_and_store(
        api, historical, tmp_path, monkeypatch, case_id, cache_fourth_round):
    import httpx

    trace, spec = historical["trace"], historical["spec"]
    assert historical["caseId"] == case_id
    assert not cache_fourth_round or case_id == QUANTITY_CASE
    fixture_before = api.canonical(historical)
    by_slot = {record["slot"]: record for record in trace["records"]}
    http_calls = []

    def forbid_http(*args, **kwargs):
        http_calls.append("send")
        raise AssertionError("Historical replay must never dispatch HTTP")

    monkeypatch.setattr(httpx.Client, "send", forbid_http)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbid_http)
    generated_slots = []
    observation_lock = threading.Lock()
    original_builder = api.controller.build_observation

    def checked_observation(*args, **kwargs):
        observation = original_builder(*args, **kwargs)
        slot = f"{observation['round']}:{observation['phase']}:{observation['actorId']}"
        assert observation == by_slot[slot]["observation"], slot
        with observation_lock:
            generated_slots.append(slot)
        return observation

    monkeypatch.setattr(api.controller, "build_observation", checked_observation)
    policy = ScriptedReplayPolicy(trace["records"])
    path = tmp_path / "historical-replay.sqlite3"
    with api.Store(path, deepcopy(spec)) as store:
        fence = store.acquire_writer("historical-replay")
        assert store.head() == trace["history"][0]
        for round_index in range(1, 4 if cache_fourth_round else 5):
            head = api.controller.run_round(store, policy, fence)
            assert head == trace["history"][round_index]
            assert store.rounds() == trace["rounds"][:round_index]
        if cache_fourth_round:
            # Seed successful tentative receipts, then reopen before committing.
            # This uses public persistence APIs and the unmodified captured
            # rejected decision, never edits SQLite or an original saved run.
            fourth = [record for record in trace["records"] if record["decision"]["round"] == 4]
            assert len(fourth) == 4 and all(record["decision"]["phase"] == "proposal" for record in fourth)
            store.freeze_phase(4, "proposal", [record["decision"]["actorId"] for record in fourth], fence)
            for record in fourth:
                slot = record["slot"]
                obs = checked_observation(store.spec, store.head(), record["decision"]["actorId"], 4, "proposal")
                store.save_observation(slot, obs, fence)
                attempt = store.reserve_attempt(slot, fence)
                store.finish_attempt(attempt, "succeeded", {"tokens": 0, "costUsd": "0"}, fence)
                store.save_decision(slot, deepcopy(record["decision"]), fence)
            assert store.head() == trace["history"][3]
            before_resume_budget = store.budget_summary()
            assert len(before_resume_budget["attempts"]) == len(by_slot)
        else:
            _assert_committed_trace(store, historical)

    if cache_fourth_round:
        class CachedOnlyPolicy:
            external = False

            def decide(self, observation):
                pytest.fail("Cached historical decisions must not be dispatched or repaired")

        with api.Store(path) as resumed:
            fence = resumed.acquire_writer("historical-cached-resume")
            assert api.controller.run_round(resumed, CachedOnlyPolicy(), fence) == trace["head"]
            assert resumed.budget_summary() == before_resume_budget
            _assert_committed_trace(resumed, historical)

    with api.Store(path, read_only=True) as reopened:
        _assert_committed_trace(reopened, historical)
        budget = reopened.budget_summary()
        assert len(budget["attempts"]) == len(by_slot)
        assert all(item["status"] == "succeeded" for item in budget["attempts"])
        assert budget["actual"] == budget["unknown"] == {"tokens": 0, "costUsd": "0"}
    assert Counter(policy.calls) == Counter(slot for slot in by_slot if not cache_fourth_round or not slot.startswith("4:"))
    assert Counter(generated_slots) == Counter({slot: 2 if cache_fourth_round and slot.startswith("4:") else 1 for slot in by_slot})
    assert http_calls == []
    assert api.canonical(historical) == fixture_before


def test_none_actor_mode_skips_only_roster_membership(api):
    template = {"inputs": {"recipient": {"type": "actor", "required": True}}}
    intent = {"operation": "execute", "parameters": {"recipient": "unlisted"}}
    assert api.input_values(template, intent, None, 20) == {"recipient": "unlisted"}
    assert api.input_values(template, intent, {"unlisted": {}}, 20) == {"recipient": "unlisted"}
    for actors in ({"known": {}}, {}):
        with pytest.raises(api.Error, match="Unknown actor input") as error:
            api.input_values(template, intent, actors, 20)
        assert error.value.code == "invalid_input"


@pytest.mark.parametrize("field,parameters,max_chars,code,message", [
    ({"type": "integer"}, {"value": True}, 20, "invalid_input", "Integer input required"),
    ({"type": "boolean"}, {"value": 1}, 20, "invalid_input", "Boolean input required"),
    ({"type": "string"}, {"value": 3}, 20, "invalid_input", "String input required"),
    ({"type": "decimal"}, {"value": 1.5}, 20, "invalid_quantity", "Quantities must be decimal strings or integers"),
    ({"type": "string"}, {"value": "long"}, 3, "invalid_input", "Action text exceeds declared limit"),
    ({"type": "decimal", "min": "1"}, {"value": "0.5"}, 20, "invalid_input", "Input below declared minimum"),
    ({"type": "decimal", "max": "10"}, {"value": "12"}, 20, "invalid_input", "Input above declared maximum"),
    ({"type": "integer", "min": 2}, {"value": 1}, 20, "invalid_input", "Input below declared minimum"),
    ({"type": "string", "enum": ["allowed"]}, {"value": "other"}, 20, "invalid_input", "Input is outside the declared choices"),
    ({"type": "decimal", "enum": ["1.00"]}, {"value": "2"}, 20, "invalid_input", "Input is outside the declared choices"),
    ({"type": "decimal", "required": True}, {}, 20, "invalid_input", "Required action input is missing"),
    ({"type": "string"}, {"extra": "not-declared"}, 20, "invalid_input", "Unsupported action input"),
    ({"type": "string"}, [], 20, "invalid_input", "Unsupported action input"),
], ids=["integer-type", "boolean-type", "string-type", "decimal-float", "length", "minimum", "maximum",
        "integer-minimum", "enum", "decimal-enum", "required", "unknown-field", "parameters-type"])
def test_helper_grammar_rejections_are_identical_for_none_normal_and_empty_actor_maps(
        api, field, parameters, max_chars, code, message):
    template = {"inputs": {"value": field}}
    intent = {"operation": "execute", "parameters": parameters}
    before = deepcopy((template, intent))
    for actors in (None, {"known": {}}, {}):
        with pytest.raises(api.Error, match=message) as error:
            api.input_values(template, intent, actors, max_chars)
        assert error.value.code == code
        assert (template, intent) == before


@pytest.mark.parametrize("field,value,max_chars,message", [
    ({"type": "actor"}, 3, 20, "String input required"),
    ({"type": "actor"}, "long", 3, "Action text exceeds declared limit"),
    ({"type": "actor", "min": "2"}, "a", 20, "Input below declared minimum"),
    ({"type": "actor", "max": "3"}, "long", 20, "Input above declared maximum"),
    ({"type": "actor", "enum": ["known"]}, "other", 20, "Input is outside the declared choices"),
], ids=["type", "length", "minimum", "maximum", "enum"])
def test_none_actor_mode_still_validates_actor_field_grammar(api, field, value, max_chars, message):
    template = {"inputs": {"recipient": field}}
    intent = {"operation": "execute", "parameters": {"recipient": value}}
    # Membership is deliberately satisfied in the normal-mode comparison, so
    # both failures must come from the shared public grammar restriction.
    for actors in (None, {value: {}}):
        with pytest.raises(api.Error, match=message) as error:
            api.input_values(template, intent, actors, max_chars)
        assert error.value.code == "invalid_input"


def test_decimal_normalization_and_non_actor_success_do_not_depend_on_actor_mode(api):
    template = {"inputs": {"amount": {"type": "decimal", "min": "1", "max": "2", "enum": ["1.00"], "required": True},
                           "count": {"type": "integer"}, "support": {"type": "boolean"}, "text": {"type": "string"}}}
    intent = {"operation": "execute", "parameters": {"amount": "1.000", "count": 2, "support": True, "text": "ok"}}
    before = deepcopy((template, intent))
    for actors in (None, {"known": {}}, {}):
        assert api.input_values(template, intent, actors, 20) == {"amount": "1", "count": 2, "support": True, "text": "ok"}
    assert (template, intent) == before


@pytest.mark.parametrize("operation", ["accept", "reject", "defer", "withdraw"])
def test_none_actor_mode_preserves_exact_consent_input_rules(api, operation):
    template = {"inputs": {"quantity": {"type": "decimal", "required": True, "min": "1", "max": "10"}}}
    for actors in (None, {"known": {}}, {}):
        assert api.input_values(template, {"operation": operation, "parameters": {}}, actors, 20) == {}
        with pytest.raises(api.Error, match="Responses must reference exact terms without replacing them") as error:
            api.input_values(template, {"operation": operation, "parameters": {"quantity": "1"}}, actors, 20)
        assert error.value.code == "invalid_input"
