"""EVAL-20 (P07 part 2/2): label-free block-movement study over frozen bundles
(app/services/value_add_stats.py + backend/scripts/value_add_eval.py). Offline: fake
clients only, bundles written with eval_bundle.write_bundle under tmp_path."""

import json
import os
import random

import pytest

from app.config import Config
from app.services import eval_bundle as eb
from app.services import value_add_stats as vas
from app.utils.telemetry import set_run_context
from scripts import value_add_eval as vae

BLOCK_TEXT = {"brief": "Demand is rising.", "forecast_inputs": "Base rate 30%.", "dossier": "# Dossier\nBody.",
              "quant": "Demand 150 GW.", "graph": "EIA: demand 150 GW.", "sim": "Signals: wait-and-see.",
              "market": "| 1 | Will X? | 0.40 |"}
MARKET_TITLE = "[Prediction-market signals]"


def _bundle(root, report, *, unavailable=(), pre_market=(0.4, 0.6)):
    blocks = {name: (None if name in unavailable else text) for name, text in BLOCK_TEXT.items()}
    statuses = {name: (eb.unavailable("not_captured") if name in unavailable else eb.STATUS_OK)
                for name in BLOCK_TEXT}
    targets = [{"target_id": f"F{i + 1}", "statement": f"{report} statement {i + 1}",
                "resolution_criteria": f"criteria {i + 1}", "resolution_date": "2027-12-31",
                "published_probability": p, "pre_market_probability": p}
               for i, p in enumerate(pre_market)]
    path = os.path.join(str(root), report, eb.BUNDLE_DIRNAME)
    eb.write_bundle(path, blocks=blocks, statuses=statuses, targets=targets,
                    meta={"ids": {"report": report}, "as_of": "2026-06-30", "created_at": "2026-07-01T00:00:00Z"})
    return path


class FakeClient:
    """Base p per target (0.4 / 0.6) plus uniform noise of +-0.01; ``market_shift`` is added
    whenever the market block is shown (the injected M effect)."""

    def __init__(self, spec, *, market_shift=0.0, seed=7, cached_on_call=None, reply=None):
        self.provider, _, self.model = spec.partition(":")
        self.market_shift = market_shift
        self.rng = random.Random(seed)
        self.calls = 0
        self.cached_on_call = cached_on_call
        self.reply = reply

    def chat_json(self, messages, temperature=0.3, max_tokens=4096, tier="strong", *, label=None):
        assert max_tokens == vae.MAX_TOKENS
        self.calls += 1
        if self.reply is not None:
            return dict(self.reply)
        user = messages[-1]["content"]
        p = 0.4 if "statement 1" in user else 0.6
        if MARKET_TITLE in user:
            p += self.market_shift
        return {"probability": p + self.rng.uniform(-0.01, 0.01), "rationale": "fixture"}

    def last_call_meta(self):
        served = "cache" if self.cached_on_call == self.calls else "primary"
        return {"served_by": served, "usage": {"prompt_tokens": 100, "completion_tokens": 20}}


class Factory:
    def __init__(self, **per_model):
        self.per_model = per_model
        self.clients = {}

    def __call__(self, spec):
        client = FakeClient(spec, **self.per_model.get(spec, {}))
        self.clients[spec] = client
        return client

    def calls(self):
        return sum(c.calls for c in self.clients.values())


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.setattr(Config, "LLM_CACHE_ENABLED", True)
    monkeypatch.setattr(Config, "VALUE_ADD_EVAL_ENABLED", False)
    monkeypatch.setattr(Config, "EVAL_STUDY_MAX_CALLS", 600)
    monkeypatch.setattr(Config, "EVAL_ARM_REPLICATES", 3)
    monkeypatch.setattr(Config, "EVAL_TARGETS_PER_BUNDLE", 2)
    monkeypatch.setattr(Config, "EVAL_BOOTSTRAP_RESAMPLES", 500)
    yield
    set_run_context(None)


def _args(cmd, bundles, out, *extra, models=("fake:x",)):
    argv = [cmd]
    for path in bundles:
        argv += ["--bundle", path]
    for model in models:
        argv += ["--model", model]
    return vae.build_parser().parse_args(argv + ["--out-root", str(out), *extra])


def _run(bundles, out, factory, *extra, models=("fake:x",)):
    return vae.cmd_run(_args("run", bundles, out, "--live", *extra, models=models), client_factory=factory)


def _score(out, study_id):
    return vae.main(["score", "--study-id", study_id, "--out-root", str(out)])


def _study_id(out):
    (study_id,) = os.listdir(str(out))
    return study_id


def _rows(out, study_id):
    return vae._read_rows(os.path.join(str(out), study_id, "elicitations.jsonl"))


def _scores(out, study_id):
    with open(os.path.join(str(out), study_id, "scores.json"), encoding="utf-8") as f:
        return json.load(f)


# ------------------------------------------------------------------ plan
def test_plan_counts_and_zero_calls(tmp_path, monkeypatch, capsys):
    bundle = _bundle(tmp_path / "b", "r1")
    monkeypatch.setattr(vae, "build_client", lambda spec: pytest.fail("plan must not build a client"))
    out = tmp_path / "out"
    code = vae.main(["plan", "--bundle", bundle, "--model", "fake:x", "--model", "fake:y",
                     "--out-root", str(out)])
    assert code == 0
    printed = json.loads(capsys.readouterr().out)
    # per target and model: 8 single-sample arms + floor_sc K=3, times 3 replicates
    assert printed["planned_calls"] == 2 * 2 * (8 + 3) * 3 == 132
    assert printed["skipped_arms"] == []
    assert not out.exists()


# ------------------------------------------------------------------ run guards
def test_opt_in_guard_and_max_calls_refusal(tmp_path, monkeypatch):
    bundle = _bundle(tmp_path / "b", "r1")
    out = tmp_path / "out"
    factory = Factory()
    assert vae.cmd_run(_args("run", [bundle], out), client_factory=factory) == 0
    assert factory.clients == {} and not out.exists()

    monkeypatch.setattr(Config, "EVAL_STUDY_MAX_CALLS", 10)
    assert _run([bundle], out, factory) == vae.EXIT_REFUSED
    assert factory.clients == {} and not out.exists()

    assert _run([bundle], out, factory, "--max-calls", "66") == 0
    assert factory.calls() == 66
    assert Config.LLM_CACHE_ENABLED is False


def test_cli_unpinned_model_refused(tmp_path):
    bundle = _bundle(tmp_path / "b", "r1")
    out = tmp_path / "out"
    factory = Factory()
    assert _run([bundle], out, factory, models=("claude-cli:gpt-4o-mini",)) == vae.EXIT_REFUSED
    assert factory.clients == {} and not out.exists()

    assert _run([bundle], out, factory, "--allow-unpinned", models=("claude-cli:gpt-4o-mini",)) == 0
    rows = _rows(out, _study_id(out))
    assert rows and all(r["model_unpinned"] is True for r in rows)

    pinned = tmp_path / "pinned"
    assert _run([bundle], pinned, Factory(), models=("claude-cli:sonnet",)) == 0
    assert all("model_unpinned" not in r for r in _rows(pinned, _study_id(pinned)))

    def no_key(spec):
        raise ValueError("no API key")

    keyless = tmp_path / "keyless"
    assert _run([bundle], keyless, no_key, models=("deepseek:deepseek-chat",)) == vae.EXIT_REFUSED
    assert not keyless.exists()


# ------------------------------------------------------------------ study scoring
def test_aa_fixture_inert_or_inconclusive_ci_contains_zero(tmp_path):
    bundles = [_bundle(tmp_path / "b", f"r{i}") for i in range(6)]
    out = tmp_path / "out"
    assert _run(bundles, out, Factory(), "--max-calls", "1000") == 0
    study_id = _study_id(out)
    assert _score(out, study_id) == 0
    scores = _scores(out, study_id)
    assert scores["valid"] is True and scores["characterization_only"] is False
    model = scores["models"]["fake:x"]
    assert model["aa"]["n_targets"] == 12 and model["aa"]["ci_contains_zero"] is True
    assert {stats["verdict"] for stats in model["blocks"].values()} <= {vas.VERDICT_INERT,
                                                                      vas.VERDICT_INCONCLUSIVE}
    assert model["evidence"] == [vas.EVIDENCE_LABELS[b] for b in ("G", "S")
                                 if model["blocks"][b]["verdict"] == vas.VERDICT_INERT]
    report = open(os.path.join(str(out), study_id, "report.md"), encoding="utf-8").read()
    assert "fake:x" in report and "Movement, not accuracy" in report


def test_injected_market_movement_moves_only_for_model_x(tmp_path):
    bundles = [_bundle(tmp_path / "b", f"r{i}", pre_market=(0.55, 0.75)) for i in range(6)]
    out = tmp_path / "out"
    factory = Factory(**{"fake:x": {"market_shift": 0.15, "seed": 1}, "fake:y": {"seed": 2}})
    assert _run(bundles, out, factory, "--max-calls", "2000", models=("fake:x", "fake:y")) == 0
    study_id = _study_id(out)
    assert _score(out, study_id) == 0
    models = _scores(out, study_id)["models"]
    x, y = models["fake:x"], models["fake:y"]
    assert x["blocks"]["M"]["verdict"] == vas.VERDICT_MOVES
    assert x["blocks"]["M"]["ci"][0] > 0 and x["blocks"]["M"]["p_holm"] < vas.ALPHA
    assert all(x["blocks"][b]["verdict"] != vas.VERDICT_MOVES for b in ("Q", "G", "S"))
    assert all(stats["verdict"] != vas.VERDICT_MOVES for stats in y["blocks"].values())
    # the shift reaches FULL and FULL_AA alike, so the A/A floor stays at noise level
    assert x["aa"]["ci_contains_zero"] is True and y["aa"]["ci_contains_zero"] is True


def test_holm_ordering_and_mde_arithmetic():
    adjusted = vas.holm({"Q": 0.01, "G": 0.04, "S": 0.03, "M": None})
    assert adjusted["Q"] == pytest.approx(0.03)
    assert adjusted["S"] == pytest.approx(0.06)
    assert adjusted["G"] == pytest.approx(0.06)      # monotone: max(0.06, 1 x 0.04)
    assert adjusted["M"] is None
    assert vas.holm({"Q": 0.02, "G": 0.6}) == {"Q": pytest.approx(0.04), "G": pytest.approx(0.6)}
    assert vas.holm({"Q": 0.6, "G": 0.7}) == {"Q": 1.0, "G": 1.0}    # capped at 1, then monotone

    rows = [{"cluster": "a", "d": 0.1}, {"cluster": "a", "d": 0.3}, {"cluster": "b", "d": 0.0},
            {"cluster": "c", "d": 0.4}]
    # cluster means 0.2, 0.0, 0.4 -> sd 0.2; (1.96 + 0.84) * 0.2 / sqrt(3)
    assert vas.mde(rows) == pytest.approx(2.8 * 0.2 / 3 ** 0.5)
    assert vas.mde([{"cluster": "a", "d": 0.1}, {"cluster": "a", "d": 0.2}]) is None

    assert vas.verdict(0.01, [0.01, 0.2], 0.02) == vas.VERDICT_MOVES
    assert vas.verdict(0.01, [-0.01, 0.2], 0.02) == vas.VERDICT_INCONCLUSIVE
    assert vas.verdict(0.40, [-0.01, 0.015], 0.02) == vas.VERDICT_INERT
    assert vas.verdict(None, None, 0.02) == vas.VERDICT_UNAVAILABLE


def test_cached_row_invalidates_study(tmp_path):
    bundles = [_bundle(tmp_path / "b", f"r{i}") for i in range(2)]
    out = tmp_path / "out"
    assert _run(bundles, out, Factory(**{"fake:x": {"cached_on_call": 5}}), "--max-calls", "1000") == 0
    study_id = _study_id(out)
    assert sum(1 for r in _rows(out, study_id) if r["cached"]) == 1
    assert _score(out, study_id) == 0
    scores = _scores(out, study_id)
    assert scores["valid"] is False and scores["invalid_reasons"] == ["cached_elicitation"]

    clean = tmp_path / "clean"
    assert _run(bundles, clean, Factory(), "--max-calls", "1000") == 0
    clean_id = _study_id(clean)
    vae._append_row(os.path.join(str(clean), clean_id, "run_meter.jsonl"), {"meter_cached_calls": 2})
    assert _score(clean, clean_id) == 0
    assert _scores(clean, clean_id)["invalid_reasons"] == ["meter_reported_cached_calls"]


def test_edited_study_json_refused(tmp_path):
    bundles = [_bundle(tmp_path / "b", f"r{i}") for i in range(2)]
    out = tmp_path / "out"
    assert _run(bundles, out, Factory(), "--max-calls", "1000") == 0
    study_id = _study_id(out)
    path = os.path.join(str(out), study_id, "study.json")
    with open(path, encoding="utf-8") as f:
        study = json.load(f)
    study["replicates"] = 5
    with open(path, "w", encoding="utf-8") as f:
        json.dump(study, f)
    assert _score(out, study_id) == vae.EXIT_STUDY_MISMATCH
    assert not os.path.exists(os.path.join(str(out), study_id, "scores.json"))
    # a rerun under the same id refuses the edited registration too
    assert _run(bundles, out, Factory(), "--max-calls", "1000", "--study-id", study_id) == vae.EXIT_STUDY_MISMATCH

    # a bundle edited after capture is refused before any client is built or any call is made
    with open(os.path.join(bundles[0], "blocks", "market.txt"), "a", encoding="utf-8") as f:
        f.write(" edited")
    for cmd in ("plan", "run"):
        argv = [cmd, "--bundle", bundles[0], "--model", "fake:x", "--out-root", str(tmp_path / "t"), "--live"]
        assert vae.main(argv[:-1] if cmd == "plan" else argv) == vae.EXIT_STUDY_MISMATCH
    assert not (tmp_path / "t").exists()


def test_unavailable_block_arm_skipped_with_reason(tmp_path, capsys):
    bundle = _bundle(tmp_path / "b", "r1", unavailable=("graph",))
    out = tmp_path / "out"
    assert vae.main(["plan", "--bundle", bundle, "--model", "fake:x", "--out-root", str(out)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert {(s["target"], s["arm"], s["reason"]) for s in printed["skipped_arms"]} == {
        ("F1", "R+G", "unavailable:graph"), ("F2", "R+G", "unavailable:graph")}
    assert printed["planned_calls"] == 2 * (7 + 3) * 3

    seen = []

    class Recorder(FakeClient):
        def chat_json(self, messages, temperature=0.3, max_tokens=4096, tier="strong", *, label=None):
            seen.append(messages[-1]["content"])
            return super().chat_json(messages, temperature, max_tokens, tier, label=label)

    assert _run([bundle], out, lambda spec: Recorder(spec)) == 0
    rows = _rows(out, _study_id(out))
    assert "R+G" not in {r["arm"] for r in rows} and len(seen) == 60
    assert not any("[Knowledge-graph facts" in text for text in seen)
    assert any("[Quantitative facts]" in text for text in seen)   # FULL keeps every available block

    no_research = _bundle(tmp_path / "c", "r2", unavailable=("dossier",))
    plan = vae.planned_calls(vae.build_study(_args("plan", [no_research], out)))
    assert {s["arm"] for s in plan["skipped_arms"]} == {"R", "R+Q", "R+G", "R+S", "R+M", "FULL", "FULL_AA"}
    assert {s["reason"] for s in plan["skipped_arms"]} == {"unavailable:dossier"}

    assert vae.parse_probability({"probability": "not a number"}) is None
    assert vae.parse_probability({"probability": 1.4}) is None
    assert vae.parse_probability({"probability": "35%"}) == 0.35
    assert vae.parse_probability({"probability": 0.0}) == vae.P_MIN
    failed = tmp_path / "failed"
    assert _run([bundle], failed, lambda spec: FakeClient(spec, reply={"answer": "maybe"})) == 0
    rows = _rows(failed, _study_id(failed))
    assert {r["status"] for r in rows} == {"parse_failed"} and all(r["p"] is None for r in rows)


def test_probe_fidelity_over_threshold_advisory(tmp_path):
    bundles = [_bundle(tmp_path / "b", f"r{i}", pre_market=(0.9, 0.1)) for i in range(3)]
    out = tmp_path / "out"
    assert _run(bundles, out, Factory(), "--max-calls", "1000") == 0
    study_id = _study_id(out)
    assert _score(out, study_id) == 0
    model = _scores(out, study_id)["models"]["fake:x"]
    assert model["probe_fidelity"] > Config.EVAL_PROBE_FIDELITY_MAX
    assert model["probe_not_representative"] is True
    assert all(stats.get("advisory") is True for stats in model["blocks"].values())

    close = tmp_path / "close"
    assert _run([_bundle(tmp_path / "c", f"r{i}") for i in range(3)], close, Factory(), "--max-calls", "1000") == 0
    close_id = _study_id(close)
    assert _score(close, close_id) == 0
    model = _scores(close, close_id)["models"]["fake:x"]
    assert model["probe_fidelity"] <= Config.EVAL_PROBE_FIDELITY_MAX
    assert model["probe_not_representative"] is False
    assert not any("advisory" in stats for stats in model["blocks"].values())


def test_resume_zero_calls(tmp_path, monkeypatch):
    bundle = _bundle(tmp_path / "b", "r1")
    out = tmp_path / "out"
    first = Factory()
    assert _run([bundle], out, first) == 0
    study_id = _study_id(out)
    rows = _rows(out, study_id)
    assert first.calls() == 66 and len(rows) == 2 * 9 * 3
    with open(os.path.join(str(out), study_id, "study.json"), encoding="utf-8") as f:
        sha = vae.study_sha(json.load(f))
    assert {r["study_sha"] for r in rows} == {sha}

    second = Factory()
    assert _run([bundle], out, second) == 0
    assert second.calls() == 0 and len(_rows(out, study_id)) == len(rows)

    monkeypatch.setattr(Config, "EVAL_ARM_REPLICATES", 2)
    few = tmp_path / "few"
    assert _run([bundle], few, Factory()) == 0
    few_id = _study_id(few)
    assert _score(few, few_id) == 0
    assert _scores(few, few_id)["characterization_only"] is True
