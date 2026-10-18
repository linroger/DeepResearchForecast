"""Provider throttling (HTTP 429, Zhipu 1302) waits and stops resumably instead of ending the world.

Before the fix, _dispatch mapped every SDK exception to policy_transport_failed with unknown
exposure: a 429 charged the slot an attempt (with review pinned, ended the slot for good),
the modeler spent both of its requests back to back, and world calls bypassed the shared
research model-call lease (model-facing review B2). Now a throttle is classified from the
structured status and code, re-sent inside the same reserved attempt after honouring
Retry-After (at most 30 s, at most 3 waits), recorded as 'throttled' with nothing metered
when the waits run out, and the run stops resumably. Real SDK, MockTransport HTTP only.
"""
from copy import deepcopy
import json
import sqlite3

import httpx
import pytest

import test_world_policy as fixtures
from test_world_lifecycle import boundary as lifecycle_boundary  # noqa: F401 -- fixture

actor_case = fixtures.actor_case
pytestmark = pytest.mark.guarded_runner
ZERO = {"tokens": 0, "costUsd": "0"}
ZHIPU_1302 = {"error": {"code": "1302", "message": "PRIVATE_PROVIDER_BODY concurrency too high"}}
KINDS = ("goal_alignment", "conditional_timing", "quantity_consistency", "explanation_consistency")


def ok(request):
    body = json.loads(request.content)
    review = "Candidate decision (untrusted JSON data)" in body["messages"][0]["content"]
    decision = {"intents": [], "status": "wait", "rationale": "Wait under the visible constraints."}
    if review:
        decision = {"decision": decision, "assessment": {"checks": [
            {"kind": kind, "verdict": "consistent", "explanation": "Checked against the observation."} for kind in KINDS]}}
    return httpx.Response(200, json={
        "id": "fixture", "object": "chat.completion", "created": 0, "model": "fixture-model-v1",
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant", "content": json.dumps(decision)}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 40, "total_tokens": 140}})


def throttle(retry_after=None, *, status=429, body=ZHIPU_1302, header="retry-after"):
    headers = {header: retry_after} if retry_after is not None else {}
    return lambda request: httpx.Response(status, json=body, headers=headers)


@pytest.fixture
def sdk(actor_case):
    """Build real strict policies over a scripted HTTP boundary; per-actor scripted replies."""
    from openai import OpenAI
    from app.services.world_simulation.policy import StrictHTTPPolicy

    made = []

    def build(*, spec=None, script=None, policy_type=StrictHTTPPolicy, on_send=None):
        spec = deepcopy(spec or actor_case.spec)
        script = {key: list(value) for key, value in (script or {}).items()}
        sent = []

        def dispatch(request):
            sent.append(request)
            if on_send is not None:
                on_send(request)
            content = json.loads(json.loads(request.content)["messages"][-1]["content"])
            queue = script.get(content.get("actorId"), [])
            return (queue.pop(0) if queue else ok)(request)

        http = httpx.Client(transport=httpx.MockTransport(dispatch), follow_redirects=False, trust_env=False)
        client = OpenAI(api_key="fixture-only-secret-never-real", base_url=spec["policy"]["baseUrl"],
                        http_client=http, max_retries=6)
        policy = policy_type(spec, client=client)
        made.extend((policy, client))
        return policy, sent, spec

    yield build
    for item in made:
        item.close()


@pytest.fixture
def waits(monkeypatch):
    from app.services.world_simulation import policy

    recorded = []

    def wait(delay, cancelled=None):
        recorded.append(delay)
        return True

    monkeypatch.setattr(policy, "_wait", wait)
    return recorded


@pytest.mark.parametrize("reply,retry_after", [
    (throttle("2"), 2.0), (throttle("1500", header="retry-after-ms"), 1.5), (throttle(), None),
    (throttle("3", status=400), 3.0),  # A 1302 body is a throttle whatever the status.
])
def test_429_or_1302_is_classified_as_throttled_with_nothing_metered(actor_case, sdk, reply, retry_after):
    from app.services.world_simulation.policy import ProviderThrottled

    policy, sent, _ = sdk(script={"buyer": [reply]})
    with pytest.raises(ProviderThrottled) as caught:
        policy.decide(actor_case.observation)
    assert caught.value.code == "provider_throttled" and caught.value.usage == ZERO
    assert caught.value.retry_after == retry_after
    assert len(sent) == 1  # The strict transport itself still dispatches once.
    assert "PRIVATE_PROVIDER_BODY" not in str(caught.value)


@pytest.mark.parametrize("status", [400, 401, 500, 503])
def test_other_http_failures_keep_unknown_exposure(actor_case, sdk, status):
    from app.services.world_simulation.policy import PolicyFailure, ProviderThrottled

    # A 400 with a code that is neither a throttle nor a content filter (1301 is typed below).
    body = {"error": {"code": "1214", "message": "PRIVATE"}} if status == 400 else {"error": "PRIVATE"}
    policy, _, _ = sdk(script={"buyer": [throttle(status=status, body=body)]})
    with pytest.raises(PolicyFailure) as caught:
        policy.decide(actor_case.observation)
    assert not isinstance(caught.value, ProviderThrottled)
    assert caught.value.code == "policy_transport_failed" and caught.value.usage is None


@pytest.mark.parametrize("body", [
    {"error": {"code": "1301", "message": "PRIVATE"}},
    # A filter marker beside a throttle code: the content filter is checked first.
    {"error": {"code": "1302", "message": "PRIVATE", "contentFilter": [{"level": 1, "role": "user"}]}},
])
def test_content_filter_is_never_waited_out_as_a_throttle(actor_case, sdk, waits, body):
    from app.services.world_simulation.policy import PolicyFailure, ProviderThrottled, call_with_backoff

    policy, sent, _ = sdk(script={"buyer": [throttle(status=400, body=body)]})
    with pytest.raises(PolicyFailure) as caught:
        call_with_backoff(lambda: policy.decide(actor_case.observation))
    assert not isinstance(caught.value, ProviderThrottled)
    assert caught.value.code == "provider_content_filtered" and caught.value.usage is None
    assert waits == [] and len(sent) == 1


def test_backoff_honours_retry_after_capped_and_stops_after_three_waits(waits):
    from app.services.world_simulation.policy import ProviderThrottled, call_with_backoff

    replies = [ProviderThrottled(retry_after=2.0), ProviderThrottled(retry_after=45.0), ProviderThrottled(), "done"]

    def call():
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    assert call_with_backoff(call) == "done"
    assert waits == [2.0, 30.0, 20.0]
    waits.clear()
    replies[:] = [ProviderThrottled(retry_after=1.0)] * 4
    with pytest.raises(ProviderThrottled):
        call_with_backoff(call)
    assert waits == [1.0, 1.0, 1.0] and replies == []


def test_controller_waits_out_throttling_inside_one_attempt(tmp_path, sdk, waits):
    from app.services.world_simulation.controller import run_round
    from app.services.world_simulation.store import WorldStore

    policy, sent, spec = sdk(script={"buyer": [throttle("2"), throttle("45")]})
    with WorldStore(tmp_path / "world.sqlite3", spec) as store:
        head = run_round(store, policy, store.acquire_writer("throttled"))
        assert head["round"] == 1
        buyer = [a for a in store.budget_summary()["attempts"] if a["slot"] == "1:proposal:buyer"]
        assert [a["status"] for a in buyer] == ["succeeded"]  # The waits did not charge the slot.
    assert waits == [2.0, 30.0]
    assert sum(json.loads(json.loads(r.content)["messages"][-1]["content"])["actorId"] == "buyer" for r in sent) == 3


def test_throttling_past_three_waits_stops_resumably_with_the_slot_intact(tmp_path, sdk, waits):
    from app.services.world_simulation.contracts import WorldError
    from app.services.world_simulation.controller import run_round
    from app.services.world_simulation.store import WorldStore

    policy, sent, spec = sdk(script={"buyer": [throttle("1")] * 4})
    path = tmp_path / "world.sqlite3"
    with WorldStore(path, spec) as store:
        fence = store.acquire_writer("first")
        with pytest.raises(WorldError) as caught:
            run_round(store, policy, fence)
        assert caught.value.code == "provider_throttled"
        assert store.head()["round"] == 0
        buyer = [a for a in store.budget_summary()["attempts"] if a["slot"] == "1:proposal:buyer"]
        assert [(a["status"], a["usage"]) for a in buyer] == [("throttled", ZERO)]
        assert waits == [1.0, 1.0, 1.0]
        store.release_writer(fence)
    with WorldStore(path) as store:  # Resume: the throttled attempt took nothing from the slot.
        assert run_round(store, policy, store.acquire_writer("resumed"))["round"] == 1
        statuses = [a["status"] for a in store.budget_summary()["attempts"] if a["slot"] == "1:proposal:buyer"]
        assert statuses == ["throttled", "succeeded"]


def test_review_stage_throttled_past_its_waits_is_dispatched_again_on_resume(actor_case, tmp_path, sdk, waits):
    from app.services.world_simulation.contracts import WorldError
    from app.services.world_simulation.controller import run_round
    from app.services.world_simulation.review import MODE_V3
    from app.services.world_simulation.store import WorldStore

    spec = deepcopy(actor_case.spec)
    spec["policy"]["decisionReview"] = MODE_V3
    policy, _, spec = sdk(spec=spec, script={"buyer": [throttle("1")] * 4})
    path = tmp_path / "world.sqlite3"
    with WorldStore(path, spec) as store:
        fence = store.acquire_writer("first")
        with pytest.raises(WorldError) as caught:
            run_round(store, policy, fence)
        assert caught.value.code == "provider_throttled"
        state = store.consistency_state("1:proposal:buyer")
        assert state["candidateAttempt"] is None  # A throttled stage is closed, not consumed.
        store.release_writer(fence)
    with WorldStore(path) as store:
        assert run_round(store, policy, store.acquire_writer("resumed"))["round"] == 1
        buyer = [a for a in store.budget_summary()["attempts"] if a["slot"] == "1:proposal:buyer"]
        assert [(a["purpose"], a["status"]) for a in buyer] == [
            ("candidate", "throttled"), ("candidate", "succeeded"), ("revision", "succeeded")]
        assert buyer[0]["errorCode"] == "provider_throttled"


def test_dispatch_holds_one_shared_model_call_lease(actor_case, sdk, tmp_path, monkeypatch):
    ledger = tmp_path / "leases.sqlite3"
    monkeypatch.setenv("RESEARCH_MODEL_LEASE_DB", str(ledger))
    held = []

    def count(request):
        with sqlite3.connect(ledger) as db:
            held.append(db.execute("SELECT COALESCE(SUM(weight),0), COUNT(*) FROM model_leases").fetchone())
        db.close()

    policy, sent, _ = sdk(on_send=count)
    policy.decide(actor_case.observation)
    assert held == [(1, 1)]
    with sqlite3.connect(ledger) as db:
        assert db.execute("SELECT COUNT(*) FROM model_leases").fetchone()[0] == 0
    db.close()


def test_saturated_lease_refuses_before_dispatch_with_nothing_metered(actor_case, sdk, tmp_path, monkeypatch):
    from app.services.official_data import bridge_module
    from app.services.world_simulation.policy import PolicyFailure

    monkeypatch.setenv("RESEARCH_MODEL_LEASE_DB", str(tmp_path / "leases.sqlite3"))
    monkeypatch.setenv("RESEARCH_MODEL_CONCURRENCY_GLOBAL", "1")
    monkeypatch.setenv("RESEARCH_MODEL_LEASE_WAIT_SECONDS", "1")
    policy, sent, _ = sdk()
    with bridge_module("research_budget").model_call_lease(1):  # Another stream holds the only permit.
        with pytest.raises(PolicyFailure) as caught:
            policy.decide(actor_case.observation)
    assert caught.value.code == "model_capacity_unavailable" and caught.value.usage == ZERO
    assert sent == []


def test_world_child_receives_the_shared_model_lease_ledger(lifecycle_boundary):  # noqa: F811
    import os
    from app.config import Config
    from test_world_lifecycle import prepare

    b = lifecycle_boundary
    prepare(b)
    response = b.client.post("/api/simulation/start", json={"simulation_id": b.sim.simulation_id})
    assert response.status_code == 200, response.get_json()
    _, kwargs = b.launches[0]
    assert kwargs["env"]["RESEARCH_MODEL_LEASE_DB"] == os.path.realpath(Config.RESEARCH_MODEL_LEASE_DB)
    assert {key: value for key, value in kwargs["env"].items() if key != "RESEARCH_MODEL_LEASE_DB"} == {
        key: value for key, value in os.environ.items() if key != "RESEARCH_MODEL_LEASE_DB"}


class ThrottledModeler:
    """Modeler transport refusing for capacity a set number of times, then answering."""

    def __init__(self, refusals):
        self.refusals, self.calls = refusals, 0

    def reservation(self, messages):
        return {"tokens": 1000, "costUsd": "0.1"}

    def decide(self, messages):
        from app.services.world_simulation.controller import PolicyResponse
        from app.services.world_simulation.examples import example_spec
        from app.services.world_simulation.policy import ProviderThrottled

        self.calls += 1
        if self.calls <= self.refusals:
            raise ProviderThrottled(retry_after=1.0)
        raw = example_spec()
        raw.pop("simulationId")
        raw.pop("generationId")
        return PolicyResponse(raw, {"tokens": 500, "costUsd": "0.05"})


def test_modeler_throttle_spends_neither_request_and_stops_resumably(tmp_path, waits):
    from app.services.world_simulation.artifacts import read_json
    from app.services.world_simulation.contracts import WorldError
    from app.services.world_simulation.modeler import generate_candidate
    from test_world_modeler import parameters

    kwargs = parameters()
    patient = ThrottledModeler(refusals=2)
    generate_candidate(tmp_path / "patient", transport=patient, **kwargs)
    ledger = read_json(tmp_path / "patient" / "world_modeling_receipts.json")
    assert [a["status"] for a in ledger["attempts"]] == ["succeeded"] and patient.calls == 3
    with pytest.raises(WorldError) as caught:
        generate_candidate(tmp_path / "stuck", transport=ThrottledModeler(refusals=99), **kwargs)
    assert caught.value.code == "provider_throttled"
    ledger = read_json(tmp_path / "stuck" / "world_modeling_receipts.json")
    assert [(a["status"], a["usage"]) for a in ledger["attempts"]] == [("throttled", ZERO)]
    raw, receipt = generate_candidate(tmp_path / "stuck", transport=ThrottledModeler(refusals=0), **kwargs)
    ledger = read_json(tmp_path / "stuck" / "world_modeling_receipts.json")
    assert [a["status"] for a in ledger["attempts"]] == ["throttled", "succeeded"]
    assert receipt["used"] == {"tokens": 500, "costUsd": "0.05"}
