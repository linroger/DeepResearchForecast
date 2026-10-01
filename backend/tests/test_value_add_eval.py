"""EVAL-20 (P07 part 2/2): label-free block-movement study over frozen bundles
(app/services/value_add_stats.py + backend/scripts/value_add_eval.py). Offline: fake
clients only (the real build_client is only constructed, never called), bundles written
with eval_bundle.write_bundle under tmp_path, and every study written under an evaluation
ledger in tmp_path (Config.FORECAST_LEDGER_DIR; the CLI has no other output root)."""

import contextlib
import json
import os
import random
import signal

import pytest

from app import config as config_module
from app.config import Config
from app.services import eval_bundle as eb
from app.services import value_add_stats as vas
from app.services.forecast_ledger import evaluation_ledger_dir
from app.utils.telemetry import BudgetExceeded, LLMMeter, get_run_context, set_run_context
from scripts import value_add_eval as vae

BLOCK_TEXT = {"brief": "Demand is rising.", "forecast_inputs": "Base rate 30%.", "dossier": "# Dossier\nBody.",
              "quant": "Demand 150 GW.", "graph": "EIA: demand 150 GW.", "sim": "Signals: wait-and-see.",
              "market": "| 1 | Will X? | 0.40 |"}
MARKET_TITLE = "[Prediction-market signals]"
OUTPUT_FILES = {"study.json", "elicitations.jsonl", "run_meter.jsonl", "scores.json", "report.md"}
# Enough reports for a scored (not characterization-only) verdict on every block.
SCORED_BUNDLES = vas.MIN_CLUSTERS
CALLS_PER_BUNDLE = 2 * (8 + 3) * 3      # per model: 2 targets x (8 arms + floor_sc K=3) x 3 replicates
SCORING = {"alpha": vas.ALPHA, "inert_margin": 0.02, "fidelity_max": 0.10, "resamples": 500,
           "min_clusters": vas.MIN_CLUSTERS}
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
    text; with ``fail_every`` = n, every call whose number is not a multiple of n raises.

    Like LLMClient.chat, every answered call is recorded in the real LLMMeter under the
    calling run context when LLM_TELEMETRY_ENABLED is on (``meter=False`` skips it), a cache
    hit as cached. Call ``cached_on_call`` is a cache hit (its meta says so, and the meter
    counts it cached); call ``meter_cached_on_call`` is counted cached by the meter only. Call
    ``budget_on_call`` is metered and then raises BudgetExceeded, as check_budget does after a
    paid call. ``served_switch`` = (n, id): from call n on the provider reports serving ``id``."""

    def __init__(self, spec, *, market_shift=0.0, seed=7, cached_on_call=None, meter_cached_on_call=None,
                 reply=None, fail_every=None, budget_on_call=None, served_switch=None, meter=True):
        self.provider, _, self.model = spec.partition(":")
        self.market_shift = market_shift
        self.rng = random.Random(seed)
        self.calls = 0
        self.cached_on_call = cached_on_call
        self.meter_cached_on_call = meter_cached_on_call
        self.reply = reply
        self.fail_every = fail_every
        self.budget_on_call = budget_on_call
        self.served_switch = served_switch
        self.meter = meter
        self.contexts = set()

    def chat(self, messages, temperature=0.7, max_tokens=4096, response_format=None, tier="strong"):
        assert max_tokens == vae.MAX_TOKENS and response_format == {"type": "json_object"}
        self.calls += 1
        self.contexts.add(get_run_context())
        if self.fail_every and self.calls % self.fail_every:
            raise RuntimeError("transient")
        if self.meter and Config.LLM_TELEMETRY_ENABLED:
            cached = self.calls in (self.cached_on_call, self.meter_cached_on_call)
            LLMMeter.record(self.provider, self.model or "default", 0 if cached else 100, 0 if cached else 20,
                            1.0, cached=cached)
        if self.budget_on_call == self.calls:
            raise BudgetExceeded("run exceeded token budget: 9999 > 1000")
        if self.reply is not None:
            return self.reply
        user = messages[-1]["content"]
        p = 0.4 if "statement 1" in user else 0.6
        if MARKET_TITLE in user:
            p += self.market_shift
        return json.dumps({"probability": p + self.rng.uniform(-0.01, 0.01), "rationale": "fixture"})

    def last_call_meta(self):
        served = "cache" if self.cached_on_call == self.calls else "primary"
        served_model = self.model or None
        if self.served_switch and self.calls >= self.served_switch[0]:
            served_model = self.served_switch[1]
        return {"served_by": served, "served_model": served_model,
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
def _isolated(monkeypatch, tmp_path):
    # Nothing a test runs can reach the real ledger; cmd_run's forced Config switches are undone.
    monkeypatch.setattr(Config, "FORECAST_LEDGER_DIR", str(tmp_path / "default_ledger" / "_forecast_ledger"))
    monkeypatch.setattr(Config, "LLM_CACHE_ENABLED", True)
    monkeypatch.setattr(Config, "LLM_TELEMETRY_ENABLED", False)
    monkeypatch.setattr(Config, "VALUE_ADD_EVAL_ENABLED", False)
    monkeypatch.setattr(Config, "EVAL_STUDY_MAX_CALLS", 600)
    monkeypatch.setattr(Config, "EVAL_ARM_REPLICATES", 3)
    monkeypatch.setattr(Config, "EVAL_TARGETS_PER_BUNDLE", 2)
    monkeypatch.setattr(Config, "EVAL_BOOTSTRAP_RESAMPLES", 500)
    monkeypatch.setattr(Config, "EVAL_PROBE_FIDELITY_MAX", 0.10)
    monkeypatch.setattr(Config, "EVAL_INERT_MARGIN", 0.02)
    yield
    set_run_context(None)


@contextlib.contextmanager
def _ledger(out):
    """Point the evaluation ledger at ``out``: evaluation_ledger_dir() is the
    '_evaluation_ledger' sibling of FORECAST_LEDGER_DIR, so studies land in _root(out)."""
    saved = Config.FORECAST_LEDGER_DIR
    Config.FORECAST_LEDGER_DIR = os.path.join(str(out), "_forecast_ledger")
    try:
        yield
    finally:
        Config.FORECAST_LEDGER_DIR = saved


def _root(out):
    return os.path.join(str(out), "_evaluation_ledger", "value_add")


def _main(out, argv):
    with _ledger(out):
        return vae.main(argv)


def _args(cmd, bundles, *extra, models=("fake:x",)):
    argv = [cmd]
    for path in bundles:
        argv += ["--bundle", path]
    for model in models:
        argv += ["--model", model]
    return vae.build_parser().parse_args(argv + list(extra))


def _run(bundles, out, factory, *extra, models=("fake:x",)):
    with _ledger(out):
        return vae.cmd_run(_args("run", bundles, "--live", *extra, models=models), client_factory=factory)


def _score(out, study_id):
    return _main(out, ["score", "--study-id", study_id])


def _study_id(out):
    (study_id,) = os.listdir(_root(out))
    return study_id


def _path(out, study_id, name):
    return os.path.join(_root(out), study_id, name)


def _rows(out, study_id):
    return vae._read_rows(_path(out, study_id, "elicitations.jsonl"))


def _meters(out, study_id):
    return vae._read_rows(_path(out, study_id, "run_meter.jsonl"))


def _load(out, study_id, name):
    with open(_path(out, study_id, name), encoding="utf-8") as f:
        return json.load(f) if name.endswith(".json") else f.read()


def _scores(out, study_id):
    return _load(out, study_id, "scores.json")


def _report(out, study_id):
    return _load(out, study_id, "report.md")


def _restamp(out, study_id, study):
    """Write an edited study.json and re-stamp every row with its new sha (so score accepts it)."""
    with open(_path(out, study_id, "study.json"), "w", encoding="utf-8") as f:
        json.dump(study, f)
    sha = vae.study_sha(study)
    rows = _rows(out, study_id)
    with open(_path(out, study_id, "elicitations.jsonl"), "w", encoding="utf-8") as f:
        f.writelines(json.dumps(dict(row, study_sha=sha)) + "\n" for row in rows)


def _verdicts(model):
    return {name: stats["verdict"] for name, stats in model["blocks"].items()}


def _computed(model):
    """Each block's computed verdict (the would-be one when a gate replaced it)."""
    return {name: stats.get("would_be_verdict", stats["verdict"]) for name, stats in model["blocks"].items()}


# ------------------------------------------------------------------ plan
def test_plan_counts_and_zero_calls(tmp_path, monkeypatch, capsys):
    bundle = _bundle(tmp_path / "b", "r1")
    monkeypatch.setattr(vae, "build_client", lambda spec: pytest.fail("plan must not build a client"))
    out = tmp_path / "out"
    code = _main(out, ["plan", "--bundle", bundle, "--model", "fake:x", "--model", "fake:y"])
    assert code == 0
    printed = json.loads(capsys.readouterr().out)
    # per target and model: 8 single-sample arms + floor_sc K=3, times 3 replicates
    assert printed["planned_calls"] == 2 * 2 * (8 + 3) * 3 == 132
    assert printed["skipped_arms"] == []
    # the scoring parameters and seed the run will pre-register
    assert printed["seed"] == vas.BOOTSTRAP_SEED
    assert printed["scoring"] == SCORING
    # the clusters (bundles) each model gets per block, and which blocks that leaves under the minimum
    assert printed["clusters_per_model"] == {spec: {"Q": 1, "G": 1, "S": 1, "M": 1} for spec in ("fake:x", "fake:y")}
    assert printed["blocks_below_min_clusters"] == ["Q", "G", "S", "M"]
    assert not out.exists()

    # the same bundle given twice (directly and through --bundles-root) is planned once
    code = _main(out, ["plan", "--bundle", bundle, "--bundle", bundle, "--bundles-root", str(tmp_path / "b"),
                       "--model", "fake:x", "--model", "fake:y"])
    assert code == 0
    again = json.loads(capsys.readouterr().out)
    assert again["planned_calls"] == 132 and again["study_id"] == printed["study_id"]
    assert not out.exists()


def test_study_inputs_validated(tmp_path, monkeypatch, capsys):
    out = tmp_path / "out"
    first = _bundle(tmp_path / "a", "r1")
    second = _bundle(tmp_path / "b", "r1", pre_market=(0.3, 0.7))     # another bundle of report r1
    undated = _bundle(tmp_path / "c", "r2", as_of=None)
    targetless = _bundle(tmp_path / "e", "r3", pre_market=())
    escaped = tmp_path / "escaped"
    refusals = [
        ["plan", "--bundle", first, "--bundle", second],
        ["plan", "--bundle", undated],
        ["plan", "--bundle", targetless],
        ["plan", "--bundles-root", str(tmp_path / "no_such_dir")],
        ["plan", "--bundle", first, "--replicates", "0"],
        ["plan", "--bundle", first, "--replicates", "-2"],
        ["plan", "--bundle", first, "--targets-per-bundle", "0"],
        ["plan"],
        ["run", "--live", "--bundle", first, "--replicates", "-1"],
        # a path-like study id would write outside evaluation_ledger_dir()/value_add/
        ["run", "--live", "--bundle", first, "--study-id", str(escaped)],
        ["run", "--live", "--bundle", first, "--study-id", "../escaped"],
        ["plan", "--bundle", first, "--study-id", "a/b"],
        ["plan", "--bundle", first, "--study-id", ".hidden"],
        ["plan", "--bundle", first, "--study-id", ""],
        ["plan", "--bundle", first, "--study-id", "x" * 65],
    ]
    for argv in refusals:
        assert _main(out, argv + ["--model", "fake:x"]) == vae.EXIT_REFUSED, argv
        assert "nothing was asked or written" in capsys.readouterr().err
    for argv in (["score", "--study-id", str(escaped)], ["score", "--study-id", "../escaped"]):
        assert _main(out, argv) == vae.EXIT_REFUSED
        assert "--study-id must be" in capsys.readouterr().err
    for name, value in (("EVAL_ARM_REPLICATES", 0), ("EVAL_INERT_MARGIN", -0.1), ("EVAL_PROBE_FIDELITY_MAX", 1.5),
                        ("EVAL_BOOTSTRAP_RESAMPLES", 0)):
        with monkeypatch.context() as m:
            m.setattr(Config, name, value)
            assert _main(out, ["plan", "--bundle", first, "--model", "fake:x"]) == vae.EXIT_REFUSED
            assert name in capsys.readouterr().err
    assert not out.exists() and not escaped.exists() and not (tmp_path / "escaped").exists()
    # --out-root is gone: the evaluation ledger is the only output root
    with pytest.raises(SystemExit):
        vae.build_parser().parse_args(["score", "--study-id", "va_x", "--out-root", str(tmp_path)])
    capsys.readouterr()

    # score: a missing study, and knobs out of range, are refused with a message
    assert _score(out, "va_missing") == vae.EXIT_REFUSED
    assert "no readable study.json" in capsys.readouterr().err
    assert _run([first], out, Factory()) == 0
    study_id = _study_id(out)
    for name, value in (("EVAL_BOOTSTRAP_RESAMPLES", 0), ("EVAL_INERT_MARGIN", -0.1),
                        ("EVAL_PROBE_FIDELITY_MAX", 1.5)):
        with monkeypatch.context() as m:
            m.setattr(Config, name, value)
            assert _score(out, study_id) == vae.EXIT_REFUSED
            assert name in capsys.readouterr().err
    assert not os.path.exists(_path(out, study_id, "scores.json"))

    # an unreadable registered study.json: run refuses before any call, score refuses to score
    for garbage in ("{not json", "[1, 2]"):
        with open(_path(out, study_id, "study.json"), "w", encoding="utf-8") as f:
            f.write(garbage)
        factory = Factory()
        assert _run([first], out, factory) == vae.EXIT_STUDY_MISMATCH
        assert factory.calls() == 0
        assert _score(out, study_id) == vae.EXIT_REFUSED
        assert "no readable study.json" in capsys.readouterr().err
    assert not os.path.exists(_path(out, study_id, "scores.json"))


# ------------------------------------------------------------------ run guards
def test_opt_in_guard_and_max_calls_refusal(tmp_path, monkeypatch, capsys):
    bundle = _bundle(tmp_path / "b", "r1")
    out = tmp_path / "out"
    factory = Factory()
    with _ledger(out):
        assert vae.cmd_run(_args("run", [bundle]), client_factory=factory) == vae.EXIT_REFUSED
    captured = capsys.readouterr()
    assert "VALUE_ADD_EVAL_ENABLED" in captured.err and captured.out == ""
    assert factory.clients == {} and not out.exists()

    monkeypatch.setattr(Config, "EVAL_STUDY_MAX_CALLS", 10)
    assert _run([bundle], out, factory) == vae.EXIT_REFUSED
    assert factory.clients == {} and not out.exists()

    assert _run([bundle], out, factory, "--max-calls", "66") == 0
    assert factory.calls() == 66
    # this process only: the cache is off and the meter on (the fixture started them the other way)
    assert Config.LLM_CACHE_ENABLED is False and Config.LLM_TELEMETRY_ENABLED is True

    # the knob opts in without --live
    monkeypatch.setattr(Config, "VALUE_ADD_EVAL_ENABLED", True)
    monkeypatch.setattr(Config, "EVAL_STUDY_MAX_CALLS", 600)
    enabled = tmp_path / "enabled"
    with _ledger(enabled):
        assert vae.cmd_run(_args("run", [bundle]), client_factory=Factory()) == 0
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
        with _ledger(out):
            assert vae.cmd_run(_args("run", [bundle], "--live", models=(spec,))) == vae.EXIT_REFUSED
        assert not out.exists()
    for spec, key in (("claude-cli:sonnet", "claude-cli:sonnet"), (":opus", "claude-cli:opus"),
                      ("claude-cli:claude-opus-4-5", "claude-cli:claude-opus-4-5")):
        assert vae.model_identity(vae.build_client(spec)) == (key, False)
    # two specs that resolve to one served model are refused
    twins = tmp_path / "twins"
    with _ledger(twins):
        assert vae.cmd_run(_args("run", [bundle], "--live", models=("claude-cli:sonnet", ":sonnet"))) \
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
    pinned_id = _study_id(pinned)
    pinned_rows = _rows(pinned, pinned_id)
    assert all("model_unpinned" not in r for r in pinned_rows)
    assert {r["model_key"] for r in pinned_rows} == {"claude-cli:sonnet"}
    # a CLI ignores temperature and max_tokens: rows, registration and scores say so (informational)
    assert all(r["sampling_params_ignored"] is True for r in pinned_rows)
    assert _load(pinned, pinned_id, "study.json")["model_keys"] == {
        "claude-cli:sonnet": {"model_key": "claude-cli:sonnet", "unpinned": False, "sampling_params_ignored": True}}
    assert _score(pinned, pinned_id) == 0
    cli_model = _scores(pinned, pinned_id)["models"]["claude-cli:sonnet"]
    assert cli_model["sampling_params_ignored"] is True and cli_model["advisory_reasons"] == []
    assert "floor_sc is not temperature-matched" in _report(pinned, pinned_id)

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
def test_aa_fixture_inert_or_inconclusive_ci_contains_zero(tmp_path, capsys):
    bundles = [_bundle(tmp_path / "b", f"r{i}") for i in range(SCORED_BUNDLES)]
    out = tmp_path / "out"
    assert _run(bundles, out, Factory(), "--max-calls", str(SCORED_BUNDLES * CALLS_PER_BUNDLE)) == 0
    assert "characterization only" not in capsys.readouterr().err      # every block has enough clusters
    study_id = _study_id(out)
    assert _score(out, study_id) == 0
    scores = _scores(out, study_id)
    assert scores["valid"] is True and scores["characterization_only"] is False
    expected = SCORED_BUNDLES * 2 * 9 * 3
    assert scores["completeness"]["fake:x"] == {"expected": expected, "ok": expected, "missing": 0,
                                                "call_failed": 0, "parse_failed": 0, "stale_prompt": 0,
                                                "model_keys": ["fake:x"], "served_models": ["x"],
                                                "served_model_count": 1}
    assert scores["incomplete_models"] == [] and scores["served_model_drift"] == []
    # scored with the pre-registered parameters and seed, and says so
    assert scores["scoring"] == dict(SCORING, seed=vas.BOOTSTRAP_SEED, preregistered=True, overrides={})
    model = scores["models"]["fake:x"]
    assert model["sampling_params_ignored"] is False and model["characterization_reasons"] == []
    assert model["blocks_below_min_clusters"] == []
    assert all(stats["n_clusters"] == SCORED_BUNDLES for stats in model["blocks"].values())
    assert model["aa"]["n_targets"] == 2 * SCORED_BUNDLES and model["aa"]["ci_contains_zero"] is True
    assert set(_verdicts(model).values()) <= {vas.VERDICT_INERT, vas.VERDICT_INCONCLUSIVE}
    assert model["probe_fidelity_status"] == vas.FIDELITY_OK and model["advisory_reasons"] == []
    assert model["evidence"] == [vas.EVIDENCE_LABELS[b] for b in ("G", "S")
                                 if model["blocks"][b]["verdict"] == vas.VERDICT_INERT]
    assert model["withheld_evidence"] == []
    # the floor arms are reported (descriptive): R and the closed-book floors answer alike here
    assert model["floor"][vas.ARM_FLOOR]["n_targets"] == model["floor"][vas.ARM_FLOOR_SC]["n_targets"] \
        == 2 * SCORED_BUNDLES
    assert model["floor"][vas.ARM_FLOOR]["mean_abs_diff"] < 0.02
    report = _report(out, study_id)
    assert "fake:x" in report and "Movement, not accuracy" in report and "R vs floor_sc" in report
    assert "## Completeness" in report
    assert (f"Scoring: alpha {vas.ALPHA}, inert margin 0.02, probe-fidelity max 0.1, bootstrap resamples 500, "
            f"minimum clusters per block {vas.MIN_CLUSTERS}, seed {vas.BOOTSTRAP_SEED} (as pre-registered)") in report
    assert f"Blocks under the minimum of {vas.MIN_CLUSTERS} clusters (characterization only): none" in report


def test_injected_market_movement_moves_only_for_model_x(tmp_path):
    # Fake seeds: a null block 'moves' by chance about 6% of the time at the cluster minimum
    # (test_null_calibration_at_min_clusters); at fake:y seed 2 its G block does here.
    bundles = [_bundle(tmp_path / "b", f"r{i}", pre_market=(0.55, 0.75)) for i in range(SCORED_BUNDLES)]
    out = tmp_path / "out"
    factory = Factory(**{"fake:x": {"market_shift": 0.15, "seed": 1}, "fake:y": {"seed": 3}})
    assert _run(bundles, out, factory, "--max-calls", str(2 * SCORED_BUNDLES * CALLS_PER_BUNDLE),
                models=("fake:x", "fake:y")) == 0
    study_id = _study_id(out)
    assert _score(out, study_id) == 0
    models = _scores(out, study_id)["models"]
    x, y = models["fake:x"], models["fake:y"]
    assert x["advisory_reasons"] == [] and x["blocks_below_min_clusters"] == []
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
    # the row says it was served from the cache, and the run's meter counted it cached too
    assert scores["valid"] is False and scores["invalid_reasons"] == ["cached_elicitation",
                                                                      "meter_reported_cached_calls"]
    model = scores["models"]["fake:x"]
    assert set(_verdicts(model).values()) == {vas.VERDICT_INVALID}
    assert all(stats["advisory"] is True and "would_be_verdict" in stats for stats in model["blocks"].values())
    assert model["evidence"] == [] and vas.REASON_STUDY_INVALID in model["advisory_reasons"]
    assert "Valid: False (cached_elicitation, meter_reported_cached_calls)" in _report(out, study_id)


def test_meter_reported_cached_call_invalidates_through_run_context(tmp_path):
    """The cached call is visible to the real LLMMeter only (its row says 'primary'): chat()
    records it under the run context cmd_run set, and the snapshot of that run invalidates."""
    bundles = [_bundle(tmp_path / "b", f"r{i}") for i in range(3)]
    out = tmp_path / "out"
    factory = Factory(**{"fake:x": {"meter_cached_on_call": 7}})
    assert _run(bundles, out, factory, "--max-calls", "1000") == 0
    study_id = _study_id(out)
    assert factory.clients["fake:x"].contexts == {("valueadd__" + study_id, "eval")}
    assert get_run_context() == (None, None)          # the run context ends with the run
    assert not any(r["cached"] for r in _rows(out, study_id))
    (meter,) = _meters(out, study_id)
    assert meter["run_id"] == "valueadd__" + study_id and meter["telemetry_enabled"] is True
    assert meter["meter_cached_calls"] == 1 and meter["meter_calls"] == meter["calls_answered"] == 3 * 2 * 11 * 3
    assert _score(out, study_id) == vae.EXIT_INVALID
    scores = _scores(out, study_id)
    assert scores["invalid_reasons"] == ["meter_reported_cached_calls"]
    assert scores["models"]["fake:x"]["evidence"] == []


def test_meter_must_vouch_for_every_answered_call(tmp_path):
    bundles = [_bundle(tmp_path / "b", f"r{i}") for i in range(3)]
    # a transport that never reached the meter: the meter cannot vouch for the calls
    blind = tmp_path / "blind"
    assert _run(bundles, blind, Factory(**{"fake:x": {"meter": False}}), "--max-calls", "1000") == 0
    blind_id = _study_id(blind)
    (meter,) = _meters(blind, blind_id)
    assert meter["meter_calls"] == 0 and meter["calls_answered"] == meter["calls_made"] == 198
    assert _score(blind, blind_id) == vae.EXIT_INVALID
    assert _scores(blind, blind_id)["invalid_reasons"] == ["meter_unavailable"]

    # a metered run (LLM_TELEMETRY_ENABLED is off in this test process: the run turns it on)
    clean = tmp_path / "clean"
    assert _run(bundles, clean, Factory(), "--max-calls", "1000") == 0
    clean_id = _study_id(clean)
    (meter,) = _meters(clean, clean_id)
    assert meter["telemetry_enabled"] is True and meter["meter_calls"] == meter["calls_answered"] == 198
    assert {r["attempt"] for r in _rows(clean, clean_id)} == {meter["attempt"]}
    assert _score(clean, clean_id) == 0
    # rows of an attempt that left no meter record (a run killed before its finally block)
    os.remove(_path(clean, clean_id, "run_meter.jsonl"))
    assert _score(clean, clean_id) == vae.EXIT_INVALID
    assert _scores(clean, clean_id)["invalid_reasons"] == ["meter_unavailable"]
    # a meter record that says the meter was off
    vae._append_row(_path(clean, clean_id, "run_meter.jsonl"), dict(meter, telemetry_enabled=False))
    assert _score(clean, clean_id) == vae.EXIT_INVALID
    assert _scores(clean, clean_id)["invalid_reasons"] == ["meter_unavailable"]


def test_killed_attempt_is_asked_again_and_the_study_recovers(tmp_path, capsys):
    """An attempt killed before it wrote its meter record (SIGKILL, a power loss): score is
    invalid while its rows are scored, a resume asks its cells again (and says so) but not the
    cells of the attempt the meter vouches for, and the new rows supersede the killed ones."""
    bundles = [_bundle(tmp_path / "b", f"r{i}") for i in range(3)]
    out = tmp_path / "out"
    # attempt 1 stops on the run budget at its 10th call: its meter record is written
    assert _run(bundles, out, Factory(**{"fake:x": {"budget_on_call": 10}}), "--max-calls", "1000") \
        == vae.EXIT_REFUSED
    study_id = _study_id(out)
    (first,) = _meters(out, study_id)
    first_rows = _rows(out, study_id)
    # attempt 2 answers more cells, then "dies" without a record (it is dropped from the file)
    assert _run(bundles, out, Factory(**{"fake:x": {"budget_on_call": 20}}), "--max-calls", "1000") \
        == vae.EXIT_REFUSED
    killed = [r for r in _rows(out, study_id) if r["attempt"] != first["attempt"]]
    assert killed and all(r["status"] == "ok" for r in killed)
    with open(_path(out, study_id, "run_meter.jsonl"), "w", encoding="utf-8") as f:
        f.write(json.dumps(first) + "\n")
    capsys.readouterr()
    assert _score(out, study_id) == vae.EXIT_INVALID
    assert _scores(out, study_id)["invalid_reasons"] == ["meter_unavailable"]

    resume = Factory()
    assert _run(bundles, out, resume, "--max-calls", "1000") == 0
    assert f"{len(killed)} answered cells come only from attempts the LLM meter cannot vouch for" \
        in capsys.readouterr().err
    assert resume.calls() == 198 - sum(3 if r["arm"] == vas.ARM_FLOOR_SC else 1 for r in first_rows)
    assert _score(out, study_id) == 0
    scores = _scores(out, study_id)
    assert scores["valid"] is True and scores["completeness"]["fake:x"]["missing"] == 0
    assert scores["rows"] == len(killed) + 162 and scores["rows_scored"] == 162
    study = _load(out, study_id, "study.json")
    vouched = vae.vouched_attempts(_meters(out, study_id))
    assert first["attempt"] in vouched and not {r["attempt"] for r in killed} & vouched
    kept = vae.select_rows(study, _rows(out, study_id), vouched)["rows"]
    assert not {r["attempt"] for r in kept} & {r["attempt"] for r in killed}

    # a vouched row is never replaced by a later row of an unvouched attempt (two runs at once)
    before = scores["models"]
    vae._append_row(_path(out, study_id, "elicitations.jsonl"), dict(kept[0], attempt="unrecorded", p=0.99))
    assert _score(out, study_id) == 0
    assert _scores(out, study_id)["models"] == before


@pytest.mark.parametrize("signame", ["SIGTERM", "SIGHUP"])
def test_termination_signal_still_writes_the_meter_record(tmp_path, signame):
    """SIGTERM / SIGHUP during a run raise SystemExit, so the attempt's meter record is still
    written and its rows stay vouched for; the previous handler is restored afterwards."""
    signum = getattr(signal, signame)
    previous = signal.getsignal(signum)
    bundle = _bundle(tmp_path / "b", "r1")
    out = tmp_path / "out"

    class Terminated(FakeClient):
        def chat(self, messages, **kwargs):
            if self.calls == 4:
                # cmd_run's handler is in place (otherwise the signal would end this test process)
                assert signal.getsignal(signum) not in (previous, signal.SIG_DFL, signal.SIG_IGN)
                os.kill(os.getpid(), signum)
            return super().chat(messages, **kwargs)

    with pytest.raises(SystemExit) as raised:
        _run([bundle], out, Terminated)
    assert raised.value.code == 128 + signum
    assert signal.getsignal(signum) == previous
    assert get_run_context() == (None, None)
    study_id = _study_id(out)
    (meter,) = _meters(out, study_id)
    rows = _rows(out, study_id)
    assert meter["calls_made"] == 5 and len(rows) == 3          # floor x 3; floor_sc died in its 2nd sample
    assert vae.vouched_attempts([meter]) == {meter["attempt"]}
    assert {r["attempt"] for r in rows} == {meter["attempt"]}
    resume = Factory()
    assert _run([bundle], out, resume) == 0
    assert resume.calls() == 66 - 3
    assert _score(out, study_id) == 0 and _scores(out, study_id)["valid"] is True


def test_budget_exceeded_stops_the_run(tmp_path, capsys):
    bundle = _bundle(tmp_path / "b", "r1")
    out = tmp_path / "out"
    factory = Factory(**{"fake:x": {"budget_on_call": 3}})
    assert _run([bundle], out, factory) == vae.EXIT_REFUSED
    assert "run budget is spent" in capsys.readouterr().err
    assert factory.calls() == 3                        # no further paid call after the budget is spent
    study_id = _study_id(out)
    assert len(_rows(out, study_id)) == 2 and all(r["status"] == "ok" for r in _rows(out, study_id))
    (meter,) = _meters(out, study_id)
    assert (meter["calls_made"], meter["calls_answered"], meter["meter_calls"]) == (3, 2, 3)
    # resume continues where the budget stopped it
    resume = Factory()
    assert _run([bundle], out, resume) == 0
    assert resume.calls() == 66 - 2
    assert _score(out, study_id) == 0
    assert _scores(out, study_id)["incomplete_models"] == []


def test_edited_study_json_refused(tmp_path, monkeypatch):
    bundles = [_bundle(tmp_path / "b", f"r{i}") for i in range(2)]
    out = tmp_path / "out"
    assert _run(bundles, out, Factory(), "--max-calls", "1000") == 0
    study_id = _study_id(out)
    path = _path(out, study_id, "study.json")
    with open(path, encoding="utf-8") as f:
        study = json.load(f)
    study["replicates"] = 5
    with open(path, "w", encoding="utf-8") as f:
        json.dump(study, f)
    assert _score(out, study_id) == vae.EXIT_STUDY_MISMATCH
    assert not os.path.exists(_path(out, study_id, "scores.json"))
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
        argv = [cmd, "--bundle", bundles[0], "--model", "fake:x", "--live"]
        assert _main(tmp_path / "t", argv[:-1] if cmd == "plan" else argv) == vae.EXIT_STUDY_MISMATCH
    assert not (tmp_path / "t").exists()


def test_unavailable_block_arm_skipped_with_reason(tmp_path, capsys):
    bundle = _bundle(tmp_path / "b", "r1", unavailable=("graph",))
    out = tmp_path / "out"
    assert _main(out, ["plan", "--bundle", bundle, "--model", "fake:x"]) == 0
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
    study_id = _study_id(out)
    rows = _rows(out, study_id)
    assert "R+G" not in {r["arm"] for r in rows} and len(seen) == 60
    assert not any("[Knowledge-graph facts" in text for text in seen)
    assert any("[Quantitative facts]" in text for text in seen)   # FULL keeps every available block
    # the scored artifacts say why G could not be judged
    assert _score(out, study_id) == 0
    scores = _scores(out, study_id)
    assert scores["skipped_arms"] == printed["skipped_arms"]
    assert scores["skipped_by_block"] == {"G": {"targets": 2, "reasons": ["unavailable:graph"]}}
    graph = scores["models"]["fake:x"]["blocks"]["G"]
    assert graph["verdict"] == vas.VERDICT_UNAVAILABLE and graph["n_targets"] == 0
    assert "- Block G skipped: 2 targets (unavailable:graph)" in _report(out, study_id)

    no_research = _bundle(tmp_path / "c", "r2", unavailable=("dossier",))
    study = vae.build_study(_args("plan", [no_research]))
    plan = vae.planned_calls(study)
    assert {s["arm"] for s in plan["skipped_arms"]} == {"R", "R+Q", "R+G", "R+S", "R+M", "FULL", "FULL_AA"}
    assert {s["reason"] for s in plan["skipped_arms"]} == {"unavailable:dossier"}
    assert vae.skipped_by_block(plan["skipped_arms"]) == {
        block: {"targets": 2, "reasons": ["unavailable:dossier"]} for block in vas.BLOCKS}
    assert vae.planned_clusters(study) == dict.fromkeys(vas.BLOCKS, 0)
    assert vae.planned_clusters(vae.build_study(_args("plan", [bundle, no_research]))) == {
        "Q": 1, "G": 0, "S": 1, "M": 1}

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


def test_malformed_replies_are_parse_failed_not_fatal(tmp_path):
    """A reply the parser cannot take is a parse_failed row, never an aborted attempt: an
    integer too large for a float, one over Python's int-string limit, nesting deeper than the
    recursion limit. A lone surrogate (an emoji cut at max_tokens) is hashed and kept."""
    assert vae.parse_probability({"probability": 10 ** 400}) is None
    assert vae.parse_probability({"probability": -(10 ** 400)}) is None
    assert vae.parse_probability({"probability": "1" * 400}) is None
    assert vae.parse_probability({"probability": float("nan")}) is None
    assert vae.parse_probability({"probability": float("inf")}) is None
    assert vae.parse_probability({"probability": True}) is None
    assert vae.parse_probability({"probability": 1}) == vae.P_MAX
    over_limit = '{"probability": ' + "1" * 5000 + "}"
    deep = '{"probability": ' + "[" * 100000 + "}"
    assert vae.parse_reply(over_limit) is None and vae.parse_reply(deep) is None
    assert vae.parse_reply('{"probability": ' + "1" * 400 + "}")["probability"] == int("1" * 400)

    bundle = _bundle(tmp_path / "b", "r1")
    cases = {"huge_int": ('{"probability": ' + "1" * 400 + "}", "parse_failed"),
             "over_limit": (over_limit, "parse_failed"), "deep": (deep, "parse_failed"),
             "surrogate": ('{"probability": 0.4, "rationale": "cut at \ud83d"}', "ok")}
    for name, (reply, status) in cases.items():
        out = tmp_path / name
        factory = Factory(**{"fake:x": {"reply": reply}})
        assert _run([bundle], out, factory) == 0, name
        rows = _rows(out, _study_id(out))
        assert factory.calls() == 66 and len(rows) == 2 * 9 * 3, name
        assert {r["status"] for r in rows} == {status}, name
        assert all(len(r["raw_sha256"]) == 64 for r in rows)
    assert {r["p"] for r in _rows(tmp_path / "surrogate", _study_id(tmp_path / "surrogate"))} == {0.4}


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
    assert model["probe_not_representative"] is False and model["advisory_reasons"] == []
    # 3 reports are under the cluster minimum: each block is characterization only for that
    # reason alone, its computed verdict kept and its evidence label withheld
    assert model["blocks_below_min_clusters"] == list(vas.BLOCKS)
    for stats in model["blocks"].values():
        assert stats["n_clusters"] == 3 and stats["verdict"] == vas.VERDICT_CHARACTERIZATION
        assert stats["characterization_reasons"] == [vas.REASON_TOO_FEW_CLUSTERS] and stats["advisory"] is True
        assert stats["would_be_verdict"] in (vas.VERDICT_INERT, vas.VERDICT_INCONCLUSIVE)
    assert model["evidence"] == []
    assert model["withheld_evidence"] == [vas.EVIDENCE_LABELS[b] for b in ("G", "S")
                                          if _computed(model)[b] == vas.VERDICT_INERT]
    report = _report(close, close_id)
    assert f"Blocks under the minimum of {vas.MIN_CLUSTERS} clusters (characterization only): Q, G, S, M" in report
    assert "| G | 6 | 3 |" in report


def test_probe_fidelity_unmeasured_fails_closed(tmp_path):
    """No market block anywhere: R+M is never asked, so fidelity cannot be measured and every
    verdict is advisory with its evidence labels withheld. (Enough reports for the cluster
    minimum, and this fixture's A/A CI contains 0, so unmeasured fidelity is the only reason.)"""
    bundles = [_bundle(tmp_path / "b", f"r{i}", unavailable=("market",), pre_market=(0.9, 0.1))
               for i in range(SCORED_BUNDLES)]
    out = tmp_path / "out"
    assert _run(bundles, out, Factory(**{"fake:x": {"seed": 8}}), "--max-calls", "2000") == 0
    study_id = _study_id(out)
    assert _score(out, study_id) == 0
    scores = _scores(out, study_id)
    assert scores["valid"] is True and scores["characterization_only"] is False
    model = scores["models"]["fake:x"]
    assert model["aa"]["ci_contains_zero"] is True
    assert model["probe_fidelity"] is None and model["probe_fidelity_status"] == vas.FIDELITY_UNMEASURED
    assert model["probe_not_representative"] is True
    assert model["advisory_reasons"] == [vas.REASON_PROBE_FIDELITY_UNMEASURED]
    assert model["blocks_below_min_clusters"] == []
    assert all(stats["advisory"] is True for stats in model["blocks"].values())
    assert model["blocks"]["M"]["verdict"] == vas.VERDICT_UNAVAILABLE
    inert = [vas.EVIDENCE_LABELS[b] for b in ("G", "S") if model["blocks"][b]["verdict"] == vas.VERDICT_INERT]
    assert inert and model["evidence"] == [] and model["withheld_evidence"] == inert
    report = _report(out, study_id)
    assert "(unmeasured)" in report and "Withheld (not evidence)" in report


def test_incomplete_model_is_characterization_only(tmp_path):
    """Completeness is judged per model: the model with unanswered cells is characterization
    only, the complete one keeps its verdicts."""
    bundles = [_bundle(tmp_path / "b", f"r{i}") for i in range(SCORED_BUNDLES)]
    out = tmp_path / "out"
    models = ("fake:x", "fake:y")
    cap = str(2 * SCORED_BUNDLES * CALLS_PER_BUNDLE)
    factory = Factory(**{"fake:x": {"fail_every": 3}, "fake:y": {"seed": 3}})
    assert _run(bundles, out, factory, "--max-calls", cap, models=models) == 0
    study_id = _study_id(out)
    rows = _rows(out, study_id)
    x_rows = [r for r in rows if r["model_key_spec"] == "fake:x"]
    failed = sum(1 for r in x_rows if r["status"].startswith("call_failed:"))
    ok = sum(1 for r in x_rows if r["status"] == "ok")
    assert failed and ok
    assert all(r["status"] == "ok" for r in rows if r["model_key_spec"] == "fake:y")
    assert _score(out, study_id) == 0
    scores = _scores(out, study_id)
    assert scores["valid"] is True and scores["characterization_only"] is False
    assert scores["characterization_reasons"] == [] and scores["incomplete_models"] == ["fake:x"]
    entry = scores["completeness"]["fake:x"]
    assert entry["expected"] == SCORED_BUNDLES * 2 * 9 * 3 and entry["ok"] == ok
    assert entry["missing"] == entry["expected"] - ok and entry["call_failed"] == failed
    assert scores["completeness"]["fake:y"]["missing"] == 0
    x, y = scores["models"]["fake:x"], scores["models"]["fake:y"]
    assert set(_verdicts(x).values()) == {vas.VERDICT_CHARACTERIZATION}
    assert x["characterization_reasons"] == ["incomplete"]
    assert x["evidence"] == [] and vas.REASON_CHARACTERIZATION in x["advisory_reasons"]
    assert y["characterization_reasons"] == [] and vas.REASON_CHARACTERIZATION not in y["advisory_reasons"]
    assert y["blocks_below_min_clusters"] == [] and vas.VERDICT_CHARACTERIZATION not in _verdicts(y).values()
    assert not any("would_be_verdict" in stats for stats in y["blocks"].values())
    report = _report(out, study_id)
    assert "Characterization only: False" in report
    assert "Incomplete models (characterization only): fake:x" in report

    # resume asks only fake:x's missing cells, after which no model is incomplete
    resume = Factory()
    assert _run(bundles, out, resume, "--max-calls", cap, models=models) == 0
    assert resume.clients["fake:y"].calls == 0
    assert resume.calls() == sum(3 if r["arm"] == vas.ARM_FLOOR_SC else 1 for r in x_rows if r["status"] != "ok")
    assert _score(out, study_id) == 0
    scores = _scores(out, study_id)
    assert scores["incomplete_models"] == [] and scores["completeness"]["fake:x"]["missing"] == 0
    assert scores["completeness"]["fake:x"]["call_failed"] == failed       # attempts stay visible
    assert scores["models"]["fake:x"]["characterization_reasons"] == []


def test_scoring_parameters_preregistered_and_recorded(tmp_path, monkeypatch, capsys):
    # 6 reports: with 3 clusters the bootstrap has only 10 distinct resamples, and its percentile
    # CI comes out the same whatever the seed
    bundles = [_bundle(tmp_path / "b", f"r{i}") for i in range(6)]
    out = tmp_path / "out"
    assert _run(bundles, out, Factory(), "--max-calls", "1000") == 0
    study_id = _study_id(out)
    study = _load(out, study_id, "study.json")
    assert study["seed"] == vas.BOOTSTRAP_SEED
    assert study["scoring"] == SCORING
    assert _score(out, study_id) == 0
    registered = _scores(out, study_id)
    assert registered["scoring"]["inert_margin"] == 0.02 and registered["scoring"]["preregistered"] is True
    assert registered["models"]["fake:x"]["advisory_reasons"] == []

    # another margin at score time: used and recorded as an override; every verdict advisory
    monkeypatch.setattr(Config, "EVAL_INERT_MARGIN", 0.5)
    assert _score(out, study_id) == 0
    overridden = _scores(out, study_id)
    assert overridden["valid"] is True
    assert overridden["scoring"]["inert_margin"] == 0.5 and overridden["scoring"]["preregistered"] is False
    assert overridden["scoring"]["overrides"] == {"inert_margin": {"registered": 0.02, "used": 0.5}}
    model = overridden["models"]["fake:x"]
    assert model["advisory_reasons"] == [vae.ADVISORY_SCORING_OVERRIDE]
    assert all(stats["advisory"] is True for stats in model["blocks"].values())
    assert set(_computed(model).values()) == {vas.VERDICT_INERT}
    assert model["evidence"] == [] and model["withheld_evidence"] == [vas.EVIDENCE_LABELS["G"],
                                                                      vas.EVIDENCE_LABELS["S"]]
    assert "NOT as pre-registered: inert_margin registered 0.02, used 0.5" in _report(out, study_id)
    # and a resume under the changed knob meets the registration: refused before any call
    factory = Factory()
    assert _run(bundles, out, factory, "--max-calls", "1000") == vae.EXIT_STUDY_MISMATCH
    assert factory.calls() == 0 and "differs from this plan in scoring" in capsys.readouterr().err
    monkeypatch.setattr(Config, "EVAL_INERT_MARGIN", 0.02)

    # the registered seed drives every bootstrap: another seed (re-stamped) gives other CIs
    _restamp(out, study_id, dict(study, seed=study["seed"] + 1))
    assert _score(out, study_id) == 0
    reseeded = _scores(out, study_id)
    assert reseeded["scoring"]["seed"] == vas.BOOTSTRAP_SEED + 1 and reseeded["scoring"]["preregistered"] is True

    def cis(scores):
        model = scores["models"]["fake:x"]
        return [model["aa"]["ci"]] + [stats["ci"] for stats in model["blocks"].values()]

    assert cis(reseeded) != cis(registered)
    assert reseeded["models"]["fake:x"]["blocks"]["M"]["mean_d"] == registered["models"]["fake:x"]["blocks"]["M"][
        "mean_d"]
    # the cluster minimum is pre-registered too: a study registered under another one is scored
    # with the code's minimum, and the difference is an override (every verdict advisory)
    _restamp(out, study_id, dict(study, scoring=dict(study["scoring"], min_clusters=4)))
    assert _score(out, study_id) == 0
    lowered = _scores(out, study_id)
    assert lowered["scoring"]["overrides"] == {"min_clusters": {"registered": 4, "used": vas.MIN_CLUSTERS}}
    assert lowered["models"]["fake:x"]["advisory_reasons"] == [vae.ADVISORY_SCORING_OVERRIDE]
    # a study.json without an integer seed cannot be scored
    _restamp(out, study_id, dict(study, seed="20261001"))
    assert _score(out, study_id) == vae.EXIT_REFUSED
    assert "seed" in capsys.readouterr().err


def test_resume_under_another_model_refused_before_any_call(tmp_path, capsys):
    """study.json registers what each --model spec resolved to; a resume whose environment
    resolves the spec to another model is refused before any paid call."""
    bundle = _bundle(tmp_path / "b", "r1")
    out = tmp_path / "out"
    assert _run([bundle], out, Factory()) == 0
    study_id = _study_id(out)
    assert _load(out, study_id, "study.json")["model_keys"] == {
        "fake:x": {"model_key": "fake:x", "unpinned": False, "sampling_params_ignored": False}}

    class Drifted(Factory):
        def __call__(self, spec):
            client = super().__call__(spec)
            client.model = "x-other"       # e.g. LLM_MODEL_NAME changed under an ':' spec
            return client

    for extra in ((), ("--study-id", study_id)):
        drifted = Drifted()
        assert _run([bundle], out, drifted, *extra) == vae.EXIT_STUDY_MISMATCH
        assert drifted.calls() == 0 and "differs from this plan in model_keys" in capsys.readouterr().err
    assert os.listdir(_root(out)) == [study_id]


def test_served_model_change_makes_model_advisory(tmp_path):
    """An alias that moves to a new snapshot mid-study pools two served models under one key:
    the provider-reported served ids are collected per model and more than one is advisory."""
    bundles = [_bundle(tmp_path / "b", f"r{i}") for i in range(3)]
    out = tmp_path / "out"
    factory = Factory(**{"fake:x": {"served_switch": (100, "x-2026-09")}})
    assert _run(bundles, out, factory, "--max-calls", "1000", models=("fake:x", "fake:y")) == 0
    study_id = _study_id(out)
    assert _score(out, study_id) == 0
    scores = _scores(out, study_id)
    assert scores["valid"] is True and scores["served_model_drift"] == ["fake:x"]
    assert scores["completeness"]["fake:x"]["served_models"] == ["x", "x-2026-09"]
    assert scores["completeness"]["fake:x"]["served_model_count"] == 2
    assert scores["completeness"]["fake:y"]["served_models"] == ["y"]
    x, y = scores["models"]["fake:x"], scores["models"]["fake:y"]
    assert vae.ADVISORY_SERVED_MODEL_DRIFT in x["advisory_reasons"] and x["evidence"] == []
    assert vae.ADVISORY_SERVED_MODEL_DRIFT not in y["advisory_reasons"]
    assert "| x, x-2026-09 |" in _report(out, study_id)


def _synthetic_rows(aa_shift, clusters=SCORED_BUNDLES):
    """``clusters`` reports x 2 targets x every arm x 3 replicates, p = 0.5 + noise; FULL_AA is
    shifted by ``aa_shift`` (a systematic FULL vs FULL_AA difference: the A/A floor is not null)."""
    rng = random.Random(11)
    rows = []
    for cluster in range(clusters):
        for target in ("F1", "F2"):
            for arm in vae.ARMS:
                for _ in range(3):
                    p = 0.5 + rng.uniform(-0.005, 0.005) + (aa_shift if arm == vas.ARM_FULL_AA else 0.0)
                    rows.append({"status": "ok", "p": p, "model_key": "m:1", "cluster_id": f"c{cluster}",
                                 "target_id": target, "arm": arm})
    return rows


def _pre_market(clusters=SCORED_BUNDLES):
    return {(f"c{cluster}", target): 0.5 for cluster in range(clusters) for target in ("F1", "F2")}


def test_aa_floor_not_null_is_advisory():
    pre_market = _pre_market()
    kwargs = {"pre_market": pre_market, "resamples": 300, "inert_margin": 0.02, "fidelity_max": 0.10}
    null = vas.score_study(_synthetic_rows(0.0), **kwargs)["m:1"]
    assert null["aa"]["ci_contains_zero"] is True and null["advisory_reasons"] == []
    assert null["evidence"] == [vas.EVIDENCE_LABELS["G"], vas.EVIDENCE_LABELS["S"]]

    shifted = vas.score_study(_synthetic_rows(0.1), **kwargs)["m:1"]
    assert shifted["aa"]["ci_contains_zero"] is False
    assert shifted["advisory_reasons"] == [vas.REASON_AA_FLOOR_NOT_NULL]
    assert all(stats["advisory"] is True for stats in shifted["blocks"].values())
    assert shifted["evidence"] == [] and shifted["withheld_evidence"] == [vas.EVIDENCE_LABELS["G"],
                                                                          vas.EVIDENCE_LABELS["S"]]
    # informational only: a CLI model ignores temperature, yet nothing is made advisory by it
    cli = vas.score_study(_synthetic_rows(0.0), sampling_params_ignored={"m:1"}, **kwargs)["m:1"]
    assert cli["sampling_params_ignored"] is True and cli["advisory_reasons"] == []


def test_block_under_min_clusters_is_characterization_only():
    """MIN_CLUSTERS gates each block on its own clusters: under it the block is
    characterization only (would_be_verdict kept, label withheld); the other blocks keep
    their verdicts; at the minimum every block is scored."""
    kwargs = {"resamples": 300, "inert_margin": 0.02, "fidelity_max": 0.10}
    labels = [vas.EVIDENCE_LABELS["G"], vas.EVIDENCE_LABELS["S"]]
    full = vas.score_study(_synthetic_rows(0.0), pre_market=_pre_market(), **kwargs)["m:1"]
    assert full["blocks_below_min_clusters"] == [] and full["advisory_reasons"] == []
    assert all(stats["n_clusters"] == vas.MIN_CLUSTERS for stats in full["blocks"].values())
    assert not any("would_be_verdict" in stats or "advisory" in stats for stats in full["blocks"].values())
    assert full["evidence"] == labels and full["withheld_evidence"] == []

    short_n = vas.MIN_CLUSTERS - 1
    short = vas.score_study(_synthetic_rows(0.0, clusters=short_n), pre_market=_pre_market(short_n),
                            **kwargs)["m:1"]
    assert short["blocks_below_min_clusters"] == list(vas.BLOCKS)
    assert short["advisory_reasons"] == [] and short["characterization_reasons"] == []
    for stats in short["blocks"].values():
        assert stats["verdict"] == vas.VERDICT_CHARACTERIZATION and stats["would_be_verdict"] == vas.VERDICT_INERT
        assert stats["characterization_reasons"] == [vas.REASON_TOO_FEW_CLUSTERS] and stats["advisory"] is True
    assert short["evidence"] == [] and short["withheld_evidence"] == labels
    # the study's registered minimum is what applies
    assert vas.score_study(_synthetic_rows(0.0, clusters=short_n), pre_market=_pre_market(short_n),
                           min_clusters=short_n, **kwargs)["m:1"]["evidence"] == labels

    # only the block that is short: R+S missing in two reports
    rows = [r for r in _synthetic_rows(0.0) if not (r["arm"] == "R+S" and r["cluster_id"] in ("c0", "c1"))]
    mixed = vas.score_study(rows, pre_market=_pre_market(), **kwargs)["m:1"]
    assert mixed["blocks_below_min_clusters"] == ["S"] and mixed["advisory_reasons"] == []
    assert mixed["blocks"]["S"]["verdict"] == vas.VERDICT_CHARACTERIZATION
    assert {name: stats["verdict"] for name, stats in mixed["blocks"].items() if name != "S"} == dict.fromkeys(
        ("Q", "G", "M"), vas.VERDICT_INERT)
    assert mixed["evidence"] == [vas.EVIDENCE_LABELS["G"]]
    assert mixed["withheld_evidence"] == [vas.EVIDENCE_LABELS["S"]]


def test_null_calibration_at_min_clusters():
    """Seeded synthetic null data at MIN_CLUSTERS reports (every block null; 2 targets per
    report, 3 replicates): the familywise rate of non-advisory 'moves' over the four blocks
    stays at or below 0.08 (nominal 5%; about 9-15% at 6-10 reports). 400 resamples keep the
    test fast; at this size the rate is about 6% with 400 and with the default 2000."""
    n, sims = vas.MIN_CLUSTERS, 600
    arms = (vas.ARM_R, *vas.BLOCK_ARMS.values(), vas.ARM_FULL, vas.ARM_FULL_AA)
    rng = random.Random(20261002)
    false_moves = 0
    for sim in range(sims):
        rows = [{"status": "ok", "p": 0.5 + rng.gauss(0, 0.03), "model_key": "m", "cluster_id": f"c{cluster}",
                 "target_id": target, "arm": arm}
                for cluster in range(n) for target in ("F1", "F2") for arm in arms for _ in range(3)]
        model = vas.score_study(rows, pre_market=_pre_market(n), resamples=400, inert_margin=0.02,
                                fidelity_max=1.0, seed=sim)["m"]
        assert model["blocks_below_min_clusters"] == []
        false_moves += not model["advisory_reasons"] and vas.VERDICT_MOVES in _verdicts(model).values()
    assert false_moves / sims <= 0.08


def test_score_uses_only_the_registered_design(tmp_path):
    bundles = [_bundle(tmp_path / "b", f"r{i}") for i in range(3)]
    out = tmp_path / "out"
    assert _run(bundles, out, Factory(), "--max-calls", "1000") == 0
    study_id = _study_id(out)
    assert _score(out, study_id) == 0
    before = _scores(out, study_id)
    rows_path = _path(out, study_id, "elicitations.jsonl")
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
    # so do rows that all carry one key, when it is not the key the study registered
    study = _load(out, study_id, "study.json")
    clean_rows = [r for r in _rows(out, study_id) if r["model_key"] == "fake:x"]
    assert vae.select_rows(study, clean_rows)["identity_drift"] == []
    moved = dict(study, model_keys={"fake:x": dict(study["model_keys"]["fake:x"], model_key="fake:z")})
    assert vae.select_rows(moved, clean_rows)["identity_drift"] == ["fake:x"]


def test_resume_zero_calls(tmp_path, monkeypatch):
    bundle = _bundle(tmp_path / "b", "r1")
    out = tmp_path / "out"
    first = Factory()
    assert _run([bundle], out, first) == 0
    study_id = _study_id(out)
    rows = _rows(out, study_id)
    assert first.calls() == 66 and len(rows) == 2 * 9 * 3
    with open(_path(out, study_id, "study.json"), encoding="utf-8") as f:
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
