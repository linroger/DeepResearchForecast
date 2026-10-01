"""EVAL-20 (P07 part 2/2): label-free block-movement study over frozen bundles
(app/services/value_add_stats.py + backend/scripts/value_add_eval.py). Offline: fake
clients only (the real build_client is only constructed, never called), bundles written
with eval_bundle.write_bundle under tmp_path."""

import json
import os
import random

import pytest

from app import config as config_module
from app.config import Config
from app.services import eval_bundle as eb
from app.services import value_add_stats as vas
from app.services.forecast_ledger import evaluation_ledger_dir
from app.utils.telemetry import set_run_context
from scripts import value_add_eval as vae

BLOCK_TEXT = {"brief": "Demand is rising.", "forecast_inputs": "Base rate 30%.", "dossier": "# Dossier\nBody.",
              "quant": "Demand 150 GW.", "graph": "EIA: demand 150 GW.", "sim": "Signals: wait-and-see.",
              "market": "| 1 | Will X? | 0.40 |"}
MARKET_TITLE = "[Prediction-market signals]"
OUTPUT_FILES = {"study.json", "elicitations.jsonl", "run_meter.jsonl", "scores.json", "report.md"}
KNOB_DEFAULTS = {"VALUE_ADD_EVAL_ENABLED": "false", "EVAL_ARM_REPLICATES": "3", "EVAL_STUDY_MAX_CALLS": "600",
                 "EVAL_TARGETS_PER_BUNDLE": "2", "EVAL_PROBE_FIDELITY_MAX": "0.10", "EVAL_INERT_MARGIN": "0.02",
                 "EVAL_BOOTSTRAP_RESAMPLES": "2000"}


def _bundle(root, report, *, unavailable=(), pre_market=(0.4, 0.6), as_of="2026-06-30"):
    blocks = {name: (None if name in unavailable else text) for name, text in BLOCK_TEXT.items()}
    statuses = {name: (eb.unavailable("not_captured") if name in unavailable else eb.STATUS_OK)
                for name in BLOCK_TEXT}
    targets = [{"target_id": f"F{i + 1}", "statement": f"{report} statement {i + 1}",
                "resolution_criteria": f"criteria {i + 1}", "resolution_date": "2027-12-31",
                "published_probability": p, "pre_market_probability": p}
               for i, p in enumerate(pre_market)]
    path = os.path.join(str(root), report, eb.BUNDLE_DIRNAME)
    eb.write_bundle(path, blocks=blocks, statuses=statuses, targets=targets,
                    meta={"capture": eb.CAPTURE_BACKFILL, "ids": {"report": report}, "as_of": as_of,
                          "created_at": "2026-07-01T00:00:00Z"})
    return path


class FakeClient:
    """Base p per target (0.4 / 0.6) plus uniform noise of +-0.01; ``market_shift`` is added
    whenever the market block is shown (the injected M effect). ``reply`` replaces the reply
    text; with ``fail_every`` = n, every call whose number is not a multiple of n raises."""

    def __init__(self, spec, *, market_shift=0.0, seed=7, cached_on_call=None, reply=None, fail_every=None):
        self.provider, _, self.model = spec.partition(":")
        self.market_shift = market_shift
        self.rng = random.Random(seed)
        self.calls = 0
        self.cached_on_call = cached_on_call
        self.reply = reply
        self.fail_every = fail_every

    def chat(self, messages, temperature=0.7, max_tokens=4096, response_format=None, tier="strong"):
        assert max_tokens == vae.MAX_TOKENS and response_format == {"type": "json_object"}
        self.calls += 1
        if self.fail_every and self.calls % self.fail_every:
            raise RuntimeError("transient")
        if self.reply is not None:
            return self.reply
        user = messages[-1]["content"]
        p = 0.4 if "statement 1" in user else 0.6
        if MARKET_TITLE in user:
            p += self.market_shift
        return json.dumps({"probability": p + self.rng.uniform(-0.01, 0.01), "rationale": "fixture"})

    def last_call_meta(self):
        served = "cache" if self.cached_on_call == self.calls else "primary"
        return {"served_by": served, "served_model": self.model or None,
                "usage": {"prompt_tokens": 100, "completion_tokens": 20}}


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
    monkeypatch.setattr(Config, "EVAL_PROBE_FIDELITY_MAX", 0.10)
    monkeypatch.setattr(Config, "EVAL_INERT_MARGIN", 0.02)
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


def _report(out, study_id):
    with open(os.path.join(str(out), study_id, "report.md"), encoding="utf-8") as f:
        return f.read()


def _verdicts(model):
    return {name: stats["verdict"] for name, stats in model["blocks"].items()}


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

    # the same bundle given twice (directly and through --bundles-root) is planned once
    code = vae.main(["plan", "--bundle", bundle, "--bundle", bundle, "--bundles-root", str(tmp_path / "b"),
                     "--model", "fake:x", "--model", "fake:y", "--out-root", str(out)])
    assert code == 0
    again = json.loads(capsys.readouterr().out)
    assert again["planned_calls"] == 132 and again["study_id"] == printed["study_id"]
    assert not out.exists()


def test_study_inputs_validated(tmp_path, monkeypatch, capsys):
    out = tmp_path / "out"
    first = _bundle(tmp_path / "a", "r1")
    second = _bundle(tmp_path / "b", "r1", pre_market=(0.3, 0.7))     # another bundle of report r1
    undated = _bundle(tmp_path / "c", "r2", as_of=None)
    refusals = [
        ["plan", "--bundle", first, "--bundle", second],
        ["plan", "--bundle", undated],
        ["plan", "--bundle", first, "--replicates", "0"],
        ["plan", "--bundle", first, "--replicates", "-2"],
        ["plan", "--bundle", first, "--targets-per-bundle", "0"],
        ["plan"],
        ["run", "--live", "--bundle", first, "--replicates", "-1"],
    ]
    for argv in refusals:
        assert vae.main(argv + ["--model", "fake:x", "--out-root", str(out)]) == vae.EXIT_REFUSED, argv
        assert "nothing was asked or written" in capsys.readouterr().err
    monkeypatch.setattr(Config, "EVAL_ARM_REPLICATES", 0)
    assert vae.main(["plan", "--bundle", first, "--model", "fake:x", "--out-root", str(out)]) == vae.EXIT_REFUSED
    assert not out.exists()

    # score: a missing study, and knobs out of range, are refused with a message
    assert _score(out, "va_missing") == vae.EXIT_REFUSED
    assert "no readable study.json" in capsys.readouterr().err
    monkeypatch.setattr(Config, "EVAL_ARM_REPLICATES", 3)
    assert _run([first], out, Factory()) == 0
    study_id = _study_id(out)
    for name, value in (("EVAL_BOOTSTRAP_RESAMPLES", 0), ("EVAL_INERT_MARGIN", -0.1),
                        ("EVAL_PROBE_FIDELITY_MAX", 1.5)):
        with monkeypatch.context() as m:
            m.setattr(Config, name, value)
            assert _score(out, study_id) == vae.EXIT_REFUSED
            assert name in capsys.readouterr().err
    assert not os.path.exists(os.path.join(str(out), study_id, "scores.json"))


# ------------------------------------------------------------------ run guards
def test_opt_in_guard_and_max_calls_refusal(tmp_path, monkeypatch, capsys):
    bundle = _bundle(tmp_path / "b", "r1")
    out = tmp_path / "out"
    factory = Factory()
    assert vae.cmd_run(_args("run", [bundle], out), client_factory=factory) == vae.EXIT_REFUSED
    captured = capsys.readouterr()
    assert "VALUE_ADD_EVAL_ENABLED" in captured.err and captured.out == ""
    assert factory.clients == {} and not out.exists()

    monkeypatch.setattr(Config, "EVAL_STUDY_MAX_CALLS", 10)
    assert _run([bundle], out, factory) == vae.EXIT_REFUSED
    assert factory.clients == {} and not out.exists()

    assert _run([bundle], out, factory, "--max-calls", "66") == 0
    assert factory.calls() == 66
    assert Config.LLM_CACHE_ENABLED is False

    # the knob opts in without --live
    monkeypatch.setattr(Config, "VALUE_ADD_EVAL_ENABLED", True)
    monkeypatch.setattr(Config, "EVAL_STUDY_MAX_CALLS", 600)
    enabled = tmp_path / "enabled"
    assert vae.cmd_run(_args("run", [bundle], enabled), client_factory=Factory()) == 0
    assert len(_rows(enabled, _study_id(enabled))) == 2 * 9 * 3


UNPINNED_SPECS = ["claude-cli:opus-4.5", "claude-cli:Claude-Opus-4", "claude-cli:sonnet-4", "claude-cli:Sonnet",
                  "claude-cli:haiku3", "claude-cli:gpt-4o-mini", "codex-cli:anything", "codex-cli:claude-x",
                  ":gpt-4o-mini", ":"]


@pytest.mark.parametrize("spec", UNPINNED_SPECS)
def test_cli_model_the_cli_drops_is_unpinned(spec, monkeypatch):
    monkeypatch.setattr(Config, "LLM_PROVIDER", "claude-cli")
    monkeypatch.setattr(Config, "LLM_MODEL_NAME", "gpt-4o-mini")
    client = vae.build_client(spec)
    provider = client.provider
    assert provider in ("claude-cli", "codex-cli")
    assert vae.model_identity(client) == (f"{provider}:cli-default", True)


def test_cli_unpinned_model_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "LLM_PROVIDER", "claude-cli")
    monkeypatch.setattr(Config, "LLM_MODEL_NAME", "gpt-4o-mini")
    bundle = _bundle(tmp_path / "b", "r1")
    # the real clients are built (no call), and refused before anything is written
    for spec in ("claude-cli:opus-4.5", "codex-cli:anything", ":gpt-4o-mini"):
        out = tmp_path / ("real_" + spec.replace(":", "_"))
        assert vae.cmd_run(_args("run", [bundle], out, "--live", models=(spec,))) == vae.EXIT_REFUSED
        assert not out.exists()
    for spec, key in (("claude-cli:sonnet", "claude-cli:sonnet"), (":opus", "claude-cli:opus"),
                      ("claude-cli:claude-opus-4-5", "claude-cli:claude-opus-4-5")):
        assert vae.model_identity(vae.build_client(spec)) == (key, False)
    # two specs that resolve to one served model are refused
    twins = tmp_path / "twins"
    assert vae.cmd_run(_args("run", [bundle], twins, "--live", models=("claude-cli:sonnet", ":sonnet"))) \
        == vae.EXIT_REFUSED
    assert not twins.exists()

    out = tmp_path / "out"
    factory = Factory()
    assert _run([bundle], out, factory, models=("claude-cli:gpt-4o-mini",)) == vae.EXIT_REFUSED
    assert factory.calls() == 0 and not out.exists()

    assert _run([bundle], out, factory, "--allow-unpinned", models=("claude-cli:gpt-4o-mini",)) == 0
    study_id = _study_id(out)
    rows = _rows(out, study_id)
    assert rows and all(r["model_unpinned"] is True for r in rows)
    assert {r["model_key"] for r in rows} == {"claude-cli:cli-default"}       # never the dropped name
    assert _score(out, study_id) == 0
    model = _scores(out, study_id)["models"]["claude-cli:cli-default"]
    assert model["model_unpinned"] is True and vas.REASON_MODEL_UNPINNED in model["advisory_reasons"]
    assert model["evidence"] == [] and all(stats["advisory"] is True for stats in model["blocks"].values())
    assert "Model unpinned: True" in _report(out, study_id)

    pinned = tmp_path / "pinned"
    assert _run([bundle], pinned, Factory(), models=("claude-cli:sonnet",)) == 0
    pinned_rows = _rows(pinned, _study_id(pinned))
    assert all("model_unpinned" not in r for r in pinned_rows)
    assert {r["model_key"] for r in pinned_rows} == {"claude-cli:sonnet"}

    def no_key(spec):
        raise ValueError("no API key")

    keyless = tmp_path / "keyless"
    assert _run([bundle], keyless, no_key, models=("deepseek:deepseek-chat",)) == vae.EXIT_REFUSED
    assert not keyless.exists()


def test_build_client_pinned_cache_free(monkeypatch):
    """Critic amendment: keywords for the default provider (its configured key and endpoint);
    any other provider through _build_ensemble_client plus model / _pinned / use_cache overrides."""
    monkeypatch.setattr(Config, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(Config, "LLM_API_KEY", "sk-test-primary")
    monkeypatch.setattr(Config, "LLM_BASE_URL", "http://gateway.test/v1")
    monkeypatch.setattr(Config, "LLM_MODEL_NAME", "gpt-configured")
    for spec, model in (("openai:gpt-4o", "gpt-4o"), (":gpt-4o", "gpt-4o"), ("openai:", "gpt-configured")):
        client = vae.build_client(spec)
        assert (client.provider, client.model, client.api_key, client.base_url) == (
            "openai", model, "sk-test-primary", "http://gateway.test/v1")
        assert client._pinned is True and client.use_cache is False and client._routing_pinned() is True
        assert vae.model_identity(client) == (f"openai:{model}", False)

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-deepseek")
    meta = Config.PROVIDER_META["deepseek"]
    for spec, model in (("deepseek:deepseek-reasoner", "deepseek-reasoner"), ("deepseek:", meta["default_model"])):
        client = vae.build_client(spec)
        assert (client.provider, client.model, client.api_key, client.base_url) == (
            "deepseek", model, "sk-test-deepseek", meta["default_base"])
        assert client._pinned is True and client.use_cache is False and client._routing_pinned() is True
        assert vae.model_identity(client) == (f"deepseek:{model}", False)

    with pytest.raises(ValueError):
        vae.build_client("no-such-provider:x")


# ------------------------------------------------------------------ study scoring
def test_aa_fixture_inert_or_inconclusive_ci_contains_zero(tmp_path):
    bundles = [_bundle(tmp_path / "b", f"r{i}") for i in range(6)]
    out = tmp_path / "out"
    assert _run(bundles, out, Factory(), "--max-calls", "1000") == 0
    study_id = _study_id(out)
    assert _score(out, study_id) == 0
    scores = _scores(out, study_id)
    assert scores["valid"] is True and scores["characterization_only"] is False
    assert scores["completeness"]["fake:x"] == {"expected": 6 * 2 * 9 * 3, "ok": 6 * 2 * 9 * 3, "missing": 0,
                                                "call_failed": 0, "parse_failed": 0, "stale_prompt": 0,
                                                "model_keys": ["fake:x"]}
    model = scores["models"]["fake:x"]
    assert model["aa"]["n_targets"] == 12 and model["aa"]["ci_contains_zero"] is True
    assert set(_verdicts(model).values()) <= {vas.VERDICT_INERT, vas.VERDICT_INCONCLUSIVE}
    assert model["probe_fidelity_status"] == vas.FIDELITY_OK and model["advisory_reasons"] == []
    assert model["evidence"] == [vas.EVIDENCE_LABELS[b] for b in ("G", "S")
                                 if model["blocks"][b]["verdict"] == vas.VERDICT_INERT]
    assert model["withheld_evidence"] == []
    # the floor arms are reported (descriptive): R and the closed-book floors answer alike here
    assert model["floor"][vas.ARM_FLOOR]["n_targets"] == model["floor"][vas.ARM_FLOOR_SC]["n_targets"] == 12
    assert model["floor"][vas.ARM_FLOOR]["mean_abs_diff"] < 0.02
    report = _report(out, study_id)
    assert "fake:x" in report and "Movement, not accuracy" in report and "R vs floor_sc" in report
    assert "## Completeness" in report


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

    assert vas.fidelity_status(None, 0.10) == vas.FIDELITY_UNMEASURED
    assert vas.fidelity_status(0.11, 0.10) == vas.FIDELITY_NOT_REPRESENTATIVE
    assert vas.fidelity_status(0.10, 0.10) == vas.FIDELITY_OK


def test_cached_row_invalidates_study(tmp_path):
    bundles = [_bundle(tmp_path / "b", f"r{i}") for i in range(3)]
    out = tmp_path / "out"
    assert _run(bundles, out, Factory(**{"fake:x": {"cached_on_call": 5}}), "--max-calls", "1000") == 0
    study_id = _study_id(out)
    assert sum(1 for r in _rows(out, study_id) if r["cached"]) == 1
    assert _score(out, study_id) == vae.EXIT_INVALID
    scores = _scores(out, study_id)
    assert scores["valid"] is False and scores["invalid_reasons"] == ["cached_elicitation"]
    model = scores["models"]["fake:x"]
    assert set(_verdicts(model).values()) == {vas.VERDICT_INVALID}
    assert all(stats["advisory"] is True and "would_be_verdict" in stats for stats in model["blocks"].values())
    assert model["evidence"] == [] and vas.REASON_STUDY_INVALID in model["advisory_reasons"]
    assert "Valid: False (cached_elicitation)" in _report(out, study_id)

    clean = tmp_path / "clean"
    assert _run(bundles, clean, Factory(), "--max-calls", "1000") == 0
    clean_id = _study_id(clean)
    vae._append_row(os.path.join(str(clean), clean_id, "run_meter.jsonl"), {"meter_cached_calls": 2})
    assert _score(clean, clean_id) == vae.EXIT_INVALID
    scores = _scores(clean, clean_id)
    assert scores["invalid_reasons"] == ["meter_reported_cached_calls"]
    assert scores["models"]["fake:x"]["evidence"] == []


def test_edited_study_json_refused(tmp_path, monkeypatch):
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

    # a changed probe prompt changes the registered prompt hashes: resuming is refused
    fresh = tmp_path / "fresh"
    assert _run(bundles, fresh, Factory(), "--max-calls", "1000") == 0
    fresh_id = _study_id(fresh)
    original = vae.build_messages

    def reworded(*a, **kw):
        messages = original(*a, **kw)
        messages[0]["content"] += " Think twice."
        return messages

    monkeypatch.setattr(vae, "build_messages", reworded)
    factory = Factory()
    assert _run(bundles, fresh, factory, "--max-calls", "1000", "--study-id", fresh_id) == vae.EXIT_STUDY_MISMATCH
    assert factory.calls() == 0
    monkeypatch.setattr(vae, "build_messages", original)

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
        def chat(self, messages, temperature=0.7, max_tokens=4096, response_format=None, tier="strong"):
            seen.append(messages[-1]["content"])
            return super().chat(messages, temperature, max_tokens, response_format, tier)

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
    assert vae.parse_reply('```json\n{"probability": 0.3}\n```') == {"probability": 0.3}
    assert vae.parse_reply("[0.3]") is None and vae.parse_reply(None) is None
    # a reply without a usable probability, JSON or not, is parse_failed (one call, no repair turn)
    for name, reply in (("nojson", "maybe 40%"), ("noprob", '{"answer": "maybe"}')):
        failed = tmp_path / name
        factory = Factory(**{"fake:x": {"reply": reply}})
        assert _run([bundle], failed, factory) == 0
        rows = _rows(failed, _study_id(failed))
        assert {r["status"] for r in rows} == {"parse_failed"} and all(r["p"] is None for r in rows)
        assert factory.calls() == 60


def test_probe_fidelity_over_threshold_advisory(tmp_path):
    bundles = [_bundle(tmp_path / "b", f"r{i}", pre_market=(0.9, 0.1)) for i in range(3)]
    out = tmp_path / "out"
    assert _run(bundles, out, Factory(), "--max-calls", "1000") == 0
    study_id = _study_id(out)
    assert _score(out, study_id) == 0
    model = _scores(out, study_id)["models"]["fake:x"]
    assert model["probe_fidelity"] > Config.EVAL_PROBE_FIDELITY_MAX
    assert model["probe_not_representative"] is True
    assert model["probe_fidelity_status"] == vas.FIDELITY_NOT_REPRESENTATIVE
    assert all(stats.get("advisory") is True for stats in model["blocks"].values())
    assert model["evidence"] == [] and vas.REASON_PROBE_NOT_REPRESENTATIVE in model["advisory_reasons"]

    close = tmp_path / "close"
    assert _run([_bundle(tmp_path / "c", f"r{i}") for i in range(3)], close, Factory(), "--max-calls", "1000") == 0
    close_id = _study_id(close)
    assert _score(close, close_id) == 0
    model = _scores(close, close_id)["models"]["fake:x"]
    assert model["probe_fidelity"] <= Config.EVAL_PROBE_FIDELITY_MAX
    assert model["probe_not_representative"] is False
    assert not any("advisory" in stats for stats in model["blocks"].values())


def test_probe_fidelity_unmeasured_fails_closed(tmp_path):
    """No market block anywhere: R+M is never asked, so fidelity cannot be measured and every
    verdict is advisory with its evidence labels withheld."""
    bundles = [_bundle(tmp_path / "b", f"r{i}", unavailable=("market",), pre_market=(0.9, 0.1))
               for i in range(6)]
    out = tmp_path / "out"
    assert _run(bundles, out, Factory(), "--max-calls", "1000") == 0
    study_id = _study_id(out)
    assert _score(out, study_id) == 0
    scores = _scores(out, study_id)
    assert scores["valid"] is True and scores["characterization_only"] is False
    model = scores["models"]["fake:x"]
    assert model["probe_fidelity"] is None and model["probe_fidelity_status"] == vas.FIDELITY_UNMEASURED
    assert model["probe_not_representative"] is True
    assert model["advisory_reasons"] == [vas.REASON_PROBE_FIDELITY_UNMEASURED]
    assert all(stats["advisory"] is True for stats in model["blocks"].values())
    assert model["blocks"]["M"]["verdict"] == vas.VERDICT_UNAVAILABLE
    inert = [vas.EVIDENCE_LABELS[b] for b in ("G", "S") if model["blocks"][b]["verdict"] == vas.VERDICT_INERT]
    assert inert and model["evidence"] == [] and model["withheld_evidence"] == inert
    report = _report(out, study_id)
    assert "(unmeasured)" in report and "Withheld (not evidence)" in report


def test_incomplete_study_is_characterization_only(tmp_path):
    bundles = [_bundle(tmp_path / "b", f"r{i}") for i in range(3)]
    out = tmp_path / "out"
    assert _run(bundles, out, Factory(**{"fake:x": {"fail_every": 3}}), "--max-calls", "1000") == 0
    study_id = _study_id(out)
    rows = _rows(out, study_id)
    failed = sum(1 for r in rows if r["status"].startswith("call_failed:"))
    ok = sum(1 for r in rows if r["status"] == "ok")
    assert failed and ok
    assert _score(out, study_id) == 0
    scores = _scores(out, study_id)
    assert scores["valid"] is True and scores["characterization_only"] is True
    assert scores["characterization_reasons"] == ["incomplete"]
    entry = scores["completeness"]["fake:x"]
    assert entry["expected"] == 3 * 2 * 9 * 3 and entry["ok"] == ok
    assert entry["missing"] == entry["expected"] - ok and entry["call_failed"] == failed
    model = scores["models"]["fake:x"]
    assert set(_verdicts(model).values()) == {vas.VERDICT_CHARACTERIZATION}
    assert model["evidence"] == [] and vas.REASON_CHARACTERIZATION in model["advisory_reasons"]
    assert "Characterization only: True (incomplete)" in _report(out, study_id)

    # resume asks only the missing cells, after which the study is complete
    resume = Factory()
    assert _run(bundles, out, resume, "--max-calls", "1000") == 0
    assert resume.calls() == sum(3 if r["arm"] == vas.ARM_FLOOR_SC else 1 for r in rows if r["status"] != "ok")
    assert _score(out, study_id) == 0
    scores = _scores(out, study_id)
    assert scores["characterization_only"] is False and scores["completeness"]["fake:x"]["missing"] == 0
    assert scores["completeness"]["fake:x"]["call_failed"] == failed       # attempts stay visible


def test_score_uses_only_the_registered_design(tmp_path):
    bundles = [_bundle(tmp_path / "b", f"r{i}") for i in range(3)]
    out = tmp_path / "out"
    assert _run(bundles, out, Factory(), "--max-calls", "1000") == 0
    study_id = _study_id(out)
    assert _score(out, study_id) == 0
    before = _scores(out, study_id)
    rows_path = os.path.join(str(out), study_id, "elicitations.jsonl")
    template = next(r for r in _rows(out, study_id) if r["arm"] == "R+M")
    # an ok row under another prompt, and one outside the registered replicates, never pool in
    vae._append_row(rows_path, dict(template, prompt_sha256="0" * 64, p=0.99))
    vae._append_row(rows_path, dict(template, replicate=7, p=0.99))
    assert _score(out, study_id) == 0
    after = _scores(out, study_id)
    assert after["completeness"]["fake:x"]["stale_prompt"] == 1
    assert after["rows_scored"] == before["rows_scored"] and after["rows"] == before["rows"] + 2
    assert after["models"] == before["models"]

    # a model whose kept rows carry two model keys changed identity mid-study: invalid
    vae._append_row(rows_path, dict(template, model_key="fake:other"))
    assert _score(out, study_id) == vae.EXIT_INVALID
    assert _scores(out, study_id)["invalid_reasons"] == ["model_identity_drift"]


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
    assert _run([_bundle(tmp_path / "c", f"r{i}") for i in range(3)], few, Factory()) == 0
    few_id = _study_id(few)
    assert _score(few, few_id) == 0
    scores = _scores(few, few_id)
    assert scores["characterization_only"] is True and scores["characterization_reasons"] == ["replicates_below_min"]
    model = scores["models"]["fake:x"]
    assert set(_verdicts(model).values()) == {vas.VERDICT_CHARACTERIZATION}
    assert model["evidence"] == [] and all(stats["advisory"] is True for stats in model["blocks"].values())


# ------------------------------------------------------------------ outputs and defaults
def test_outputs_only_under_evaluation_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "FORECAST_LEDGER_DIR", str(tmp_path / "data" / "_forecast_ledger"))
    bundle = _bundle(tmp_path / "bundles", "r1")
    before = {os.path.join(d, f) for d, _, files in os.walk(str(tmp_path)) for f in files}
    argv = ["--bundle", bundle, "--model", "fake:x"]
    assert vae.main(["plan", *argv]) == 0
    assert vae.cmd_run(vae.build_parser().parse_args(["run", *argv, "--live"]), client_factory=Factory()) == 0
    study_root = os.path.join(evaluation_ledger_dir(), "value_add")
    (study_id,) = os.listdir(study_root)
    assert vae.main(["score", "--study-id", study_id]) == 0
    created = {os.path.join(d, f) for d, _, files in os.walk(str(tmp_path)) for f in files} - before
    study_dir = os.path.join(study_root, study_id)
    assert study_dir.startswith(str(tmp_path / "data" / "_evaluation_ledger"))
    assert created == {os.path.join(study_dir, name) for name in OUTPUT_FILES}


def test_shipped_defaults_are_safe():
    """The literal defaults config.py ships (read from its source, not the test-patched
    Config) and the .env.example documentation: the study is off by default."""
    for name, default in KNOB_DEFAULTS.items():
        assert config_module.CONFIG_KNOBS[name]["default"] == default, name
    assert config_module.CONFIG_KNOBS["VALUE_ADD_EVAL_ENABLED"]["kind"] == "bool"
    env_example = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".env.example")
    with open(env_example, encoding="utf-8") as f:
        documented = {line.split("#", 2)[1].split()[0] for line in f if line.startswith("# EVAL_")
                      or line.startswith("# VALUE_ADD_EVAL_ENABLED")}
    assert {f"{name}={default}" for name, default in KNOB_DEFAULTS.items()} <= documented
