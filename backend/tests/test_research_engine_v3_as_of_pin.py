"""TIME-1: the v3 actors.json as_of_date is pinned to the plan's as-of.

The as-of in actors.json becomes the graph's valid_at/reference_time and the
simulation calendar anchor, and the actor-extraction model has reported its
training cutoff as the as-of.  With RESEARCH_AS_OF_PIN on (the default) the
engine always writes the plan's as-of (the UTC date fixed at plan time) and
records a different model value only in meta.as_of_model_disagreement; off,
the model's YYYY-MM-DD value is adopted exactly as before.  Offline: the
scripted model, injected search/fetch and real bridge of
``test_research_engine_v3``.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys

import pytest

import test_research_engine_v3 as v3

# The shared fixtures (hermetic env, real bridge with network steps stubbed).
_hermetic_env = v3._hermetic_env
bridge = v3.bridge
lr = v3.lr
dr = v3.dr

PLAN_AS_OF = "2026-10-01"
MODEL_AS_OF = "2026-09-27"      # what the scripted actor extraction returns
_OMIT = object()
# meta.json keys that differ between two runs of the same code (wall clock).
_VOLATILE_META = frozenset({"finished_at", "phases"})


@pytest.fixture(autouse=True)
def plan_as_of(monkeypatch):
    """The plan's as-of (UTC today in production) fixed after the model's date,
    and the knob unset so the engine default decides unless a test sets it."""
    monkeypatch.setattr(lr, "_utc_date", lambda: PLAN_AS_OF)
    monkeypatch.delenv("RESEARCH_AS_OF_PIN", raising=False)


class AsOfWorld(v3.World):
    """The standard world whose actor extraction returns ``as_of_date``
    (``_OMIT`` drops the key)."""

    def __init__(self, as_of_date=MODEL_AS_OF, **kwargs) -> None:
        super().__init__(**kwargs)
        self.as_of_date = as_of_date

    def actors(self, call):
        reply = json.loads(super().actors(call).content)
        if self.as_of_date is _OMIT:
            reply.pop("as_of_date", None)
        else:
            reply["as_of_date"] = self.as_of_date
        return v3.ai(json.dumps(reply))


def _run(tmp_path, bridge, monkeypatch, *, pin: str | None, as_of_date=MODEL_AS_OF, name: str = "run"):
    # One worker: KIQs run in plan order, so two runs of the same fake model
    # cite their sources in the same order and are comparable byte for byte.
    monkeypatch.setenv("RESEARCH_LINEAR_WORKERS", "1")
    if pin is None:
        monkeypatch.delenv("RESEARCH_AS_OF_PIN", raising=False)
    else:
        monkeypatch.setenv("RESEARCH_AS_OF_PIN", pin)
    root = tmp_path / name
    rc, meta, plog, _model, out = v3.run_engine(root, bridge, AsOfWorld(as_of_date))
    assert rc == 0, meta.get("error")
    return meta, plog, out


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _pin_warnings(plog) -> list[str]:
    return [line for line in plog.of("warn") if "pinned to the plan date" in line]


def _stable_meta(meta: dict) -> dict:
    return {key: value for key, value in meta.items() if key not in _VOLATILE_META}


# =============================================================== engine runs

def test_default_pins_the_plan_date_and_records_the_model_date(tmp_path, bridge, monkeypatch):
    meta, plog, out = _run(tmp_path, bridge, monkeypatch, pin=None)

    assert _load(out / "v3" / "plan.json")["as_of"] == PLAN_AS_OF
    actors = _load(out / "actors.json")
    assert actors["as_of_date"] == PLAN_AS_OF
    # The disagreement lives only in meta (actors.json keeps its contract keys).
    assert "as_of_model_disagreement" not in actors and "model_as_of" not in json.dumps(actors)
    expected = {"plan_as_of": PLAN_AS_OF, "model_as_of": MODEL_AS_OF}
    assert meta["as_of_model_disagreement"] == expected
    assert _load(out / "meta.json")["as_of_model_disagreement"] == expected
    assert meta["as_of_date"] == PLAN_AS_OF
    assert _pin_warnings(plog) == [f"v3: extraction as_of_date {MODEL_AS_OF} differs from the plan as-of "
                                   f"{PLAN_AS_OF}; pinned to the plan date"]


@pytest.mark.parametrize("pin", ["true", "1", "yes", "on", "", "maybe"])
def test_every_non_false_knob_value_pins(tmp_path, bridge, monkeypatch, pin):
    meta, _plog, out = _run(tmp_path, bridge, monkeypatch, pin=pin)
    assert _load(out / "actors.json")["as_of_date"] == PLAN_AS_OF
    assert meta["as_of_model_disagreement"]["model_as_of"] == MODEL_AS_OF


def test_pin_off_adopts_the_model_date_and_records_nothing(tmp_path, bridge, monkeypatch):
    meta, plog, out = _run(tmp_path, bridge, monkeypatch, pin="false")

    assert _load(out / "actors.json")["as_of_date"] == MODEL_AS_OF
    assert "as_of_model_disagreement" not in meta
    assert "as_of_model_disagreement" not in _load(out / "meta.json")
    assert _pin_warnings(plog) == []


def test_pin_off_differs_from_pin_on_only_in_the_pinned_fields(tmp_path, bridge, monkeypatch):
    """Flag-off is the previous output: against a pinned run of the same fake
    model, actors.json differs only in as_of_date, which holds the model's
    YYYY-MM-DD value exactly as the previous code wrote it, and meta.json only
    in the disagreement record; the other artifacts are untouched."""
    on_meta, _on_plog, on_out = _run(tmp_path, bridge, monkeypatch, pin="true", name="on")
    off_meta, _off_plog, off_out = _run(tmp_path, bridge, monkeypatch, pin="false", name="off")

    on_actors = _load(on_out / "actors.json")
    assert on_actors["as_of_date"] == PLAN_AS_OF
    previous = {**on_actors, "as_of_date": MODEL_AS_OF}
    assert (off_out / "actors.json").read_bytes() == json.dumps(previous, ensure_ascii=False,
                                                                indent=2).encode("utf-8")
    on_disk, off_disk = _load(on_out / "meta.json"), _load(off_out / "meta.json")
    assert on_disk.pop("as_of_model_disagreement") == {"plan_as_of": PLAN_AS_OF, "model_as_of": MODEL_AS_OF}
    assert _stable_meta(on_disk) == _stable_meta(off_disk)
    assert _stable_meta(off_meta) == _stable_meta({k: v for k, v in on_meta.items()
                                                   if k != "as_of_model_disagreement"})
    for name in ("timeline.json", "quantitative.json", "contested.json", "sources.json", "research_report.md"):
        assert (on_out / name).read_bytes() == (off_out / name).read_bytes(), name


def test_model_echoing_the_plan_date_writes_identical_bytes_either_way(tmp_path, bridge, monkeypatch):
    on_meta, on_plog, on_out = _run(tmp_path, bridge, monkeypatch, pin="true", as_of_date=PLAN_AS_OF, name="on")
    off_meta, _off_plog, off_out = _run(tmp_path, bridge, monkeypatch, pin="false", as_of_date=PLAN_AS_OF,
                                        name="off")

    assert "as_of_model_disagreement" not in on_meta and _pin_warnings(on_plog) == []
    assert (on_out / "actors.json").read_bytes() == (off_out / "actors.json").read_bytes()
    assert _load(on_out / "actors.json")["as_of_date"] == PLAN_AS_OF
    assert _stable_meta(_load(on_out / "meta.json")) == _stable_meta(_load(off_out / "meta.json"))


@pytest.mark.parametrize("model_value, recorded", [
    ("Jan 2026", "Jan 2026"),                    # not a date the old code adopted either
    ("  2026-01-15  ", "2026-01-15"),            # a training-cutoff date, whitespace collapsed
    (20260115, "20260115"),                      # a non-string reply
])
def test_pin_on_records_any_differing_model_value(tmp_path, bridge, monkeypatch, model_value, recorded):
    meta, plog, out = _run(tmp_path, bridge, monkeypatch, pin=None, as_of_date=model_value)
    assert _load(out / "actors.json")["as_of_date"] == PLAN_AS_OF
    assert meta["as_of_model_disagreement"] == {"plan_as_of": PLAN_AS_OF, "model_as_of": recorded}
    assert len(_pin_warnings(plog)) == 1


def test_pin_on_caps_a_runaway_model_value(tmp_path, bridge, monkeypatch):
    meta, _plog, _out = _run(tmp_path, bridge, monkeypatch, pin=None, as_of_date="as of " + "very " * 40 + "late")
    recorded = meta["as_of_model_disagreement"]["model_as_of"]
    assert len(recorded) <= 40 and recorded.endswith("…")


def test_pin_off_keeps_the_previous_fallback_for_a_non_date(tmp_path, bridge, monkeypatch):
    meta, plog, out = _run(tmp_path, bridge, monkeypatch, pin="false", as_of_date="Jan 2026")
    assert _load(out / "actors.json")["as_of_date"] == PLAN_AS_OF
    assert "as_of_model_disagreement" not in meta and _pin_warnings(plog) == []


@pytest.mark.parametrize("model_value", [_OMIT, "", None, "   "])
def test_a_missing_model_date_is_no_disagreement(tmp_path, bridge, monkeypatch, model_value):
    meta, plog, out = _run(tmp_path, bridge, monkeypatch, pin=None, as_of_date=model_value)
    assert _load(out / "actors.json")["as_of_date"] == PLAN_AS_OF
    assert "as_of_model_disagreement" not in meta and _pin_warnings(plog) == []


# =============================================================== knob parsing

@pytest.mark.parametrize("raw, default, expected", [
    ("true", False, True), ("1", False, True), ("yes", False, True), ("on", False, True),
    ("false", True, False), ("0", True, False), ("off", True, False), ("no", True, False),
    ("", True, True), ("", False, False), ("maybe", True, True), ("maybe", False, False),
    (None, True, True), (None, False, False),
])
def test_env_flag_table(raw, default, expected):
    env = {} if raw is None else {"RESEARCH_AS_OF_PIN": raw}
    assert lr._env_flag(env, "RESEARCH_AS_OF_PIN", default) is expected


@pytest.mark.parametrize("raw, expected", [
    (None, True), ("", True), ("true", True), ("1", True), ("yes", True), ("maybe", True),
    ("false", False), ("0", False), ("No", False), (" OFF ", False),
])
def test_config_parses_the_pin_fail_closed_like_the_engine(monkeypatch, raw, expected):
    """The orchestrator forwards Config's verdict as an explicit true/false, so
    Config parses the knob like the engine's _env_flag(..., True): '1' or a typo
    must not turn the honesty fix off before the child ever sees it."""
    import app.config  # noqa: F401 — its import-time env defaults are set once, before the probe

    if raw is None:
        monkeypatch.delenv("RESEARCH_AS_OF_PIN", raising=False)
    else:
        monkeypatch.setenv("RESEARCH_AS_OF_PIN", raw)
    spec = importlib.util.spec_from_file_location("_time1_config_probe",
                                                  os.path.join(v3._BACKEND, "app", "config.py"))
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)       # a fresh Config; app.config itself is untouched
    assert probe.Config.RESEARCH_AS_OF_PIN is expected
    assert lr._env_flag({} if raw is None else {"RESEARCH_AS_OF_PIN": raw}, "RESEARCH_AS_OF_PIN", True) is expected


# =============================================================== salvage meta

def test_extract_only_salvage_drops_the_v3_as_of_disagreement(tmp_path, monkeypatch):
    """The parent salvages a killed v3 run with the legacy extract-only path,
    which rewrites actors.json with its own as-of: the v3 run's record of its
    extraction's disagreement must not survive into the salvage meta."""
    (tmp_path / dr.REPORT_FILENAME).write_text("x" * 1000, encoding="utf-8")
    prior = {"status": "running", "research_engine": "v3",
             "as_of_model_disagreement": {"plan_as_of": PLAN_AS_OF, "model_as_of": MODEL_AS_OF},
             "research_quality": {"score": 0.61}, "as_of_date": PLAN_AS_OF}
    (tmp_path / "meta.json").write_text(json.dumps(prior), encoding="utf-8")
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key-not-used")
    seen = {}

    def fake_extract_only(question, out_dir, args, meta, plog, write_meta):
        seen["meta"] = dict(meta)
        plog.close()
        return 0

    monkeypatch.setattr(dr, "run_extract_only", fake_extract_only)
    monkeypatch.setattr(sys, "argv", ["deerflow_research.py", "--extract-only", "--model", "minimax",
                                      "--out-dir", str(tmp_path), "--prompt", "Q"])
    assert dr.main() == 0
    meta = seen["meta"]
    assert meta["salvage"]["mode"] == "extract_only" and meta["research_engine"] == "v3"
    assert "as_of_model_disagreement" not in meta
    # The rest of the v3 meta is still carried over.
    assert meta["research_quality"] == prior["research_quality"] and meta["as_of_date"] == PLAN_AS_OF
