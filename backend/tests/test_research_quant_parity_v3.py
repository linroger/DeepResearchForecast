"""TIME-4: v3 quantitative sanity parity with the legacy engine.

RESEARCH_QUANT_RECONCILE (default on, forwarded to every research child) runs
the bridge's ``reconcile_quantitative`` and ``flag_implausible_quant`` in the
v3 finalize and in the extract-only salvage:

* rows on the same (metric, unit) that disagree become contested.json claims
  (origin ``quant_reconcile``; v3 adds at most QUANT_RECONCILE_MAX_CONTESTED),
  a ~1000x gap is also a probable unit-scale error in meta.quant_unit_warnings;
* claimed actuals dated after the as-of are listed in meta.quant_implausible
  (v3: typed rows by epistemic_class, otherwise value_type actual or absent);
* quantitative.json never changes, actors.json keeps the extracted claims, and
  with the knob off every artifact and meta are byte-identical to before.

Offline: the scripted model, injected search/fetch and real bridge of
``test_research_engine_v3``.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

import test_research_engine_v3 as v3

# The shared fixtures (hermetic env, real bridge with network steps stubbed).
_hermetic_env = v3._hermetic_env
bridge = v3.bridge
lr = v3.lr
dr = v3.dr

AS_OF = dt.date(2026, 9, 28)
KNOB = "RESEARCH_QUANT_RECONCILE"
NEW_META_KEYS = {"quant_unit_warnings", "quant_implausible", "quant_reconcile_contested"}
SANITY_HELPERS = ("reconcile_quantitative", "flag_implausible_quant")
MODEL_CONTESTED = [{"claim": "2030 capacity", "positions": [{"stance": "250 GW", "sources": ["S1"]}],
                    "status": "contested", "why_they_differ": "scope"}]


def _fact(metric, value, unit, as_of_date, value_type="actual"):
    row = {"metric": metric, "value": value, "unit": unit, "as_of_date": as_of_date, "source_ref": "S1"}
    if value_type is not None:
        row["value_type"] = value_type
    return row


# Two readings of one metric 1000x apart (a probable unit-scale error), an
# actual dated after the as-of and a forecast dated after it whose metric has
# no projection word (only the claimed-actual filter keeps it out).
PARITY_FACTS = [
    _fact("Data-centre electricity use", "1.2", "TWh", "2025-12-31"),
    _fact("Data-centre electricity use", "1200", "TWh", "2025-12-31"),
    _fact("Operating capacity", "185", "GW", "2027-06-30"),
    _fact("Installed capacity", "260", "GW", "2030-12-31", "forecast"),
]
# The bound is the day after the plan's as-of (typing's publication bound).
FUTURE_ACTUAL_FLAG = ("Operating capacity: as_of 2027-06-30 is AFTER research cutoff 2026-09-29 "
                      "(claimed-actual with future date)")


@pytest.fixture
def fixed_as_of(monkeypatch):
    """The plan's as-of date (UTC today in production) pinned for stable dates."""
    monkeypatch.setattr(lr, "_utc_date", lambda: AS_OF.isoformat())


class QuantWorld(v3.World):
    """The standard world with a scripted facts reply."""

    def __init__(self, quant: list[dict], **kwargs) -> None:
        super().__init__(**kwargs)
        self.quant = quant

    def facts(self, call):
        return v3.ai(json.dumps({
            "key_events": [{"date": "2023-12-31", "event": "Capacity reached 176 GW"}],
            "quantitative_facts": self.quant,
            "contested_claims": MODEL_CONTESTED,
        }))


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _run(tmp_path: Path, bridge, name: str, quant: list[dict] = PARITY_FACTS):
    rc, meta, plog, _model, out = v3.run_engine(tmp_path / name, bridge, QuantWorld(copy.deepcopy(quant)))
    assert rc == 0, meta.get("error")
    return meta, plog, out


def _model_contested(out: Path) -> list[dict]:
    """contested.json as the engine wrote it before TIME-4: the normalized model claims."""
    return lr.normalize_contested(copy.deepcopy(MODEL_CONTESTED), _load(out / "sources.json"))


def _dump(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")


# =============================================================== v3 engine

def test_v3_run_records_unit_scale_error_and_future_dated_actual(tmp_path, bridge, fixed_as_of):
    """Knob unset (default on): the ~1000x disagreement is a unit warning and a
    contested.json claim; the future-dated actual is implausible, the
    future-dated forecast is not."""
    meta, plog, out = _run(tmp_path, bridge, "on")

    assert meta["quant_unit_warnings"] == [{"metric": "Data-centre electricity use", "unit": "TWh",
                                            "ratio": 1000.0, "values": ["1.2", "1200"]}]
    assert meta["quant_implausible"] == [FUTURE_ACTUAL_FLAG]
    assert not any("Installed capacity" in flag for flag in meta["quant_implausible"])
    assert meta["quant_reconcile_contested"] == 1

    contested = _load(out / "contested.json")
    assert contested[:-1] == _model_contested(out)
    reconciled = contested[-1]
    assert reconciled["origin"] == "quant_reconcile" and reconciled["status"] == "contested"
    assert reconciled["claim"] == "Data-centre electricity use"
    assert [position["stance"].split(" (")[0] for position in reconciled["positions"]] == ["1.2 TWh", "1200 TWh"]
    assert "probable unit-scale error" in reconciled["why_they_differ"]
    assert meta["contested_count"] == len(contested) == 2
    # actors.json keeps the extracted claims (the legacy engine's split).
    assert _load(out / "actors.json")["contested_claims"] == _model_contested(out)

    written = _load(out / "meta.json")
    assert {key: written[key] for key in NEW_META_KEYS} == {key: meta[key] for key in NEW_META_KEYS}
    assert "v3: quant reconcile: 1 probable unit-scale (~1000x) disagreement(s)" in plog.of("warn")
    assert "v3: quant reconcile: +1 contested claim(s) from numeric disagreement" in plog.of("ok")
    assert any(line.startswith("v3: quant sanity: 1 implausible/future-dated fact(s)") for line in plog.of("warn"))
    assert not any(error["helper"] in SANITY_HELPERS for error in meta.get("analytics_errors", []))


def test_quantitative_json_unchanged_and_flag_off_byte_identical(tmp_path, bridge, monkeypatch, fixed_as_of):
    """The step is read-only: every artifact but contested.json is byte-equal
    with the knob on and off; off, contested.json holds only the model claims,
    no helper runs and meta gains no key."""
    monkeypatch.setenv("RESEARCH_LINEAR_WORKERS", "1")   # deterministic runs: the artifacts compare
    meta_on, _, on = _run(tmp_path, bridge, "on")

    monkeypatch.setenv(KNOB, "false")
    for helper in SANITY_HELPERS:
        monkeypatch.setattr(bridge, helper, lambda *_a, _name=helper, **_k: pytest.fail(f"{_name} ran"))
    meta_off, plog_off, off = _run(tmp_path, bridge, "off")

    for name in ("quantitative.json", "actors.json", "timeline.json", "sources.json", "research_report.md",
                 lr.VERIFIED_FACTS_FILENAME):
        assert (on / name).read_bytes() == (off / name).read_bytes(), name
    quant = _load(off / "quantitative.json")
    assert [(row["metric"], row["value"]) for row in quant] == [(f["metric"], f["value"]) for f in PARITY_FACTS]
    assert not any(key in row for row in quant for key in ("origin", "positions"))

    assert (off / "contested.json").read_bytes() == _dump(_model_contested(off))
    assert _load(on / "contested.json")[:-1] == _load(off / "contested.json")
    assert NEW_META_KEYS.isdisjoint(meta_off) and NEW_META_KEYS <= set(meta_on)
    assert set(meta_on) - set(meta_off) == NEW_META_KEYS
    assert meta_off["contested_count"] == 1
    assert not any("quant reconcile" in line or "quant sanity" in line for _kind, line in plog_off.lines)
    assert not any(error["helper"] in SANITY_HELPERS for error in meta_off.get("analytics_errors", []))


@pytest.mark.parametrize("mode", ["missing", "raising"])
def test_sanity_helpers_degrade_safe(tmp_path, bridge, monkeypatch, fixed_as_of, mode):
    """A bridge without (or with failing) helpers: analytics_errors records
    them, contested.json keeps the model claims and the run completes."""
    for helper in SANITY_HELPERS:
        if mode == "missing":
            monkeypatch.delattr(bridge, helper)
        else:
            def boom(*_args, **_kwargs):
                raise RuntimeError("helper broke")
            monkeypatch.setattr(bridge, helper, boom)
    meta, plog, out = _run(tmp_path, bridge, mode)

    expected = "unavailable" if mode == "missing" else "RuntimeError: helper broke"
    errors = [error for error in meta["analytics_errors"] if error["helper"] in SANITY_HELPERS]
    assert errors == [{"helper": helper, "error": expected} for helper in SANITY_HELPERS]
    assert _load(out / "meta.json")["analytics_errors"] == meta["analytics_errors"]
    assert NEW_META_KEYS.isdisjoint(meta)
    assert (out / "contested.json").read_bytes() == _dump(_model_contested(out))
    assert meta["status"] == "completed"


def test_reconciled_contested_rows_are_capped(tmp_path, bridge, fixed_as_of):
    """Twelve disagreeing metrics: contested.json gains the first ten; a 2x gap
    is a disagreement but no unit-scale warning."""
    metrics = [f"Regional capacity {chr(ord('A') + index)}" for index in range(12)]
    facts = [_fact(metric, value, "GW", "2025-12-31") for metric in metrics for value in ("10", "20")]
    meta, plog, out = _run(tmp_path, bridge, "capped", facts)

    assert lr.QUANT_RECONCILE_MAX_CONTESTED == 10
    contested = _load(out / "contested.json")
    assert contested[:1] == _model_contested(out)
    assert [row["claim"] for row in contested[1:]] == metrics[:10]
    assert all(row["origin"] == "quant_reconcile" for row in contested[1:])
    assert meta["quant_reconcile_contested"] == 10 and meta["contested_count"] == 11
    assert "quant_unit_warnings" not in meta and "quant_implausible" not in meta
    assert ("v3: quant reconcile: +10 contested claim(s) from numeric disagreement (the first 10 of 12)"
            in plog.of("ok"))


# Typed rows are claimed by epistemic_class; untyped ones by value_type.
TYPED_FACTS = [
    _fact("Operating capacity", "185", "GW", "2027-06-30"),                 # future actual: always flagged
    _fact("Installed capacity", "260", "GW", "2030-12-31", "forecast"),     # projected: never
    _fact("Capacity growth", "180", "% YoY", "2025-12-31", "estimate"),     # typed reported: flagged
    _fact("Rack density", "40", "kW", "2027-01-15", None),                  # untyped, no value_type: flagged
]


@pytest.mark.parametrize("typing, expected", [
    (False, [FUTURE_ACTUAL_FLAG,
             "Rack density: as_of 2027-01-15 is AFTER research cutoff 2026-09-29 (claimed-actual with future date)"]),
    (True, [FUTURE_ACTUAL_FLAG, "Capacity growth: 180 % yoy — extreme growth (>150%); verify vs parent total"]),
])
def test_claimed_actuals_follow_quant_typing(tmp_path, bridge, monkeypatch, fixed_as_of, typing, expected):
    monkeypatch.setenv("RESEARCH_QUANT_TYPING", "true" if typing else "false")
    meta, _, out = _run(tmp_path, bridge, "typed" if typing else "untyped", TYPED_FACTS)
    assert meta["quant_implausible"] == expected
    classes = [row.get("epistemic_class") for row in _load(out / "quantitative.json")]
    assert classes == (["unknown", "projected", "reported", "unknown"] if typing else [None] * 4)


def test_an_actual_published_the_day_after_the_plan_date_is_not_implausible(tmp_path, bridge, fixed_as_of):
    """plan.as_of is the UTC date fixed at plan time; a run that crosses UTC
    midnight can cite a number published the next day (as typing allows)."""
    next_day, day_after = ((AS_OF + dt.timedelta(days=days)).isoformat() for days in (1, 2))
    facts = [_fact("Operating capacity", "185", "GW", next_day), _fact("Grid queue", "40", "months", day_after)]
    meta, _, _ = _run(tmp_path, bridge, "midnight", facts)
    assert meta["quant_implausible"] == [
        f"Grid queue: as_of {day_after} is AFTER research cutoff {next_day} (claimed-actual with future date)"]


# =============================================================== pure parts

@pytest.mark.parametrize("row, claimed", [
    ({"value_type": "actual"}, True),
    ({}, True),
    ({"value_type": "estimate"}, False),
    ({"value_type": "forecast"}, False),
    ({"value_type": "target"}, False),
    ({"value_type": "actual", "epistemic_class": "reported"}, True),
    ({"value_type": "estimate", "epistemic_class": "reported"}, True),
    ({"value_type": "actual", "epistemic_class": "unknown",
      "epistemic_flags": ["future_dated_reported", "published_after_as_of"]}, True),
    ({"epistemic_class": "unknown", "epistemic_flags": ["published_after_as_of"]}, False),
    ({"value_type": "actual", "epistemic_class": "unknown", "epistemic_flags": ["period_unparsed"]}, False),
    ({"value_type": "forecast", "epistemic_class": "projected", "epistemic_flags": ["as_of_is_target"]}, False),
])
def test_claimed_actual(row, claimed):
    assert lr._claimed_actual(row) is claimed


class _SanityStub:
    """The engine surface _quant_sanity uses: bridge_call, meta, log."""

    bridge_call = lr._Engine.bridge_call

    def __init__(self, bridge) -> None:
        self.bridge = bridge
        self.meta: dict = {}
        self.analytics_errors: list[dict] = []
        self.lines: list[tuple[str, str]] = []

    def log(self, kind, message):
        self.lines.append((kind, message))


ROWS = [{"metric": "Capacity", "value": "1", "unit": "GW", "as_of_date": "2025-12-31", "value_type": "actual"}]


@pytest.mark.parametrize("reconcile, implausible", [
    ([["claim"], []], "not a list"),
    ((["claim"],), {"flags": ["x"]}),
    (([{"claim": "x"}], "not a list"), None),
    (None, []),
])
def test_quant_sanity_ignores_results_of_another_shape(reconcile, implausible):
    stub = _SanityStub(types.SimpleNamespace(reconcile_quantitative=lambda rows: reconcile,
                                             flag_implausible_quant=lambda rows, as_of: implausible))
    assert lr._Engine._quant_sanity(stub, copy.deepcopy(ROWS), AS_OF) == []
    assert stub.meta == {} and stub.analytics_errors == [] and stub.lines == []


def test_quant_sanity_is_read_only_and_caps_every_list():
    """The helpers get copies (a helper that writes its input changes no row),
    non-dict contested rows are dropped and each meta list keeps 20 entries."""
    seen: dict = {}

    def reconcile(rows):
        seen["reconcile"] = rows
        rows[0]["value"] = "rewritten"
        found = [{"claim": f"m{index}", "origin": "quant_reconcile"} for index in range(12)]
        return ["junk", *found], [{"metric": f"m{index}"} for index in range(25)]

    def flag(rows, as_of):
        seen["flag"] = (rows, as_of)
        rows[0]["value_type"] = "rewritten"
        return [f"flag {index}" for index in range(25)]

    stub = _SanityStub(types.SimpleNamespace(reconcile_quantitative=reconcile, flag_implausible_quant=flag))
    rows = copy.deepcopy(ROWS) + [{"metric": "Target", "value": "9", "value_type": "target"}]
    before = copy.deepcopy(rows)
    extra = lr._Engine._quant_sanity(stub, rows, AS_OF)

    assert rows == before
    assert seen["flag"][1] == AS_OF and [row["metric"] for row in seen["flag"][0]] == ["Capacity"]
    assert extra == [{"claim": f"m{index}", "origin": "quant_reconcile"} for index in range(10)]
    assert stub.meta == {"quant_unit_warnings": [{"metric": f"m{index}"} for index in range(20)],
                         "quant_reconcile_contested": 10,
                         "quant_implausible": [f"flag {index}" for index in range(20)]}
    assert lr.QUANT_SANITY_MAX_FLAGS == 20


# =============================================================== Config

_CONFIG_CHILD = r"""
import importlib, json, os, sys
import dotenv
dotenv.load_dotenv = lambda *a, **k: False  # the repo .env must not decide
import app.config as config_module
out = []
for raw in json.loads(sys.argv[1]):
    if raw is None:
        os.environ.pop("RESEARCH_QUANT_RECONCILE", None)
    else:
        os.environ["RESEARCH_QUANT_RECONCILE"] = raw
    out.append(importlib.reload(config_module).Config.RESEARCH_QUANT_RECONCILE)
print("<<<JSON>>>" + json.dumps(out))
"""


def test_config_parses_the_knob_like_the_bridge(monkeypatch):
    """Config reads RESEARCH_QUANT_RECONCILE as the bridge always has (blank =
    true, else 1/true/yes/on), so forwarding it changes no engine's reading.
    A clean child process: app.config loads the repo .env at import."""
    raws = [None, "", "  ", "true", " TRUE ", "1", "yes", "on", "false", "0", "no", "off", "maybe"]
    bridge_reads = []
    for raw in raws:
        if raw is None:
            monkeypatch.delenv(KNOB, raising=False)
        else:
            monkeypatch.setenv(KNOB, raw)
        bridge_reads.append(dr._env_flag(KNOB, True))
    assert bridge_reads == [True, True, True, True, True, True, True, True, False, False, False, False, False]
    backend = Path(__file__).resolve().parents[1]
    proc = subprocess.run([sys.executable, "-c", _CONFIG_CHILD, json.dumps(raws)],
                          cwd=str(backend), capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    line = [ln for ln in proc.stdout.splitlines() if ln.startswith("<<<JSON>>>")][-1]
    assert json.loads(line[len("<<<JSON>>>"):]) == bridge_reads


# =============================================================== extract-only salvage

class _Log:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str]] = []

    def write(self, kind, message):
        self.rows.append((kind, str(message)))

    def close(self):
        pass

    def of(self, kind: str) -> list[str]:
        return [message for k, message in self.rows if k == kind]


def _utc_today() -> dt.date:
    return dt.datetime.now(dt.timezone.utc).date()


EXTRACT_FACTS = [
    {"metric": "Data-centre electricity use", "value": "1.2", "unit": "TWh", "as_of_date": "2025-12-31"},
    {"metric": "Data-centre electricity use", "value": "1200", "unit": "TWh", "as_of_date": "2025-12-31"},
    {"metric": "Operating capacity", "value": "185", "unit": "GW", "as_of_date": "2099-06-30"},
    # The bridge's check reads projection words: a forecast is never implausible for its date.
    {"metric": "Installed capacity forecast", "value": "260", "unit": "GW", "as_of_date": "2099-12-31"},
]


def _extract_only(tmp_path: Path, monkeypatch, *, as_of_date, facts=EXTRACT_FACTS):
    out = tmp_path
    out.mkdir(parents=True, exist_ok=True)
    (out / dr.REPORT_FILENAME).write_text("# Report\n\n" + "evidence " * 100, encoding="utf-8")
    obj = {"actors": [{"name": "Acme", "type": "Organization"}],
           "quantitative_facts": copy.deepcopy(facts),
           "contested_claims": copy.deepcopy(MODEL_CONTESTED)}
    if as_of_date is not None:
        obj["as_of_date"] = as_of_date
    monkeypatch.setattr(dr, "extract_complete_structured_tool_free", lambda *_a, **_k: ("{}", obj, [], False))
    monkeypatch.setattr(dr, "_collect_prediction_markets", lambda *_a, **_k: None)
    monkeypatch.setattr(dr, "_render_research_charts", lambda *_a, **_k: {})
    meta: dict = {}
    log = _Log()
    args = types.SimpleNamespace(no_actors=False, target_language="English", model="glm", depth="standard")
    rc = dr.run_extract_only("Q", out, args, meta, log, lambda: None)
    assert rc == 0 and meta["status"] == "completed", meta.get("error")
    return meta, log, out


def test_extract_only_records_unit_warnings_and_implausible_facts(tmp_path, monkeypatch):
    as_of = (_utc_today() - dt.timedelta(days=3)).isoformat()
    meta, log, out = _extract_only(tmp_path / "on", monkeypatch, as_of_date=as_of)

    assert meta["quant_unit_warnings"] == [{"metric": "Data-centre electricity use", "unit": "TWh",
                                            "ratio": 1000.0, "values": ["1.2", "1200"]}]
    assert meta["quant_implausible"] == [
        f"Operating capacity: as_of 2099-06-30 is AFTER research cutoff {as_of} (claimed-actual with future date)"]
    contested = _load(out / dr.CONTESTED_FILENAME)
    assert contested[0] == MODEL_CONTESTED[0] and contested[1]["origin"] == "quant_reconcile"
    assert meta["contested_count"] == 2
    assert "extract-only: quant reconcile: 1 probable unit-scale (~1000x) disagreement(s)" in log.of("warn")
    assert any(line.startswith(f"extract-only: quant sanity: 1 implausible/future-dated fact(s) against {as_of}")
               for line in log.of("warn"))

    # Knob off: the salvage writes what it wrote before (no reconciled claim, no new meta).
    monkeypatch.setenv(KNOB, "false")
    meta_off, log_off, off = _extract_only(tmp_path / "off", monkeypatch, as_of_date=as_of)
    assert NEW_META_KEYS.isdisjoint(meta_off)
    assert _load(off / dr.CONTESTED_FILENAME) == MODEL_CONTESTED
    quant_bytes = (out / dr.QUANTITATIVE_FILENAME).read_bytes()
    assert quant_bytes == (off / dr.QUANTITATIVE_FILENAME).read_bytes()
    assert [row["metric"] for row in json.loads(quant_bytes)] == [row["metric"] for row in EXTRACT_FACTS]
    assert not any("quant reconcile" in line or "quant sanity" in line for line in log_off.of("warn"))


def test_extract_only_reference_date_defaults_to_today_and_is_clamped(tmp_path, monkeypatch):
    """No extracted as_of_date: the reference is today (UTC).  A stale one (a
    model's training cutoff) is clamped to the run date, as in the full legacy
    run, so a past actual after it is no false positive."""
    meta, _, _ = _extract_only(tmp_path / "none", monkeypatch, as_of_date=None)
    (flag,) = meta["quant_implausible"]
    assert flag.startswith("Operating capacity: as_of 2099-06-30 is AFTER research cutoff 20")

    past_actual = [{"metric": "Grid capacity", "value": "90", "unit": "GW", "as_of_date": "2024-06-30"}]
    meta, _, _ = _extract_only(tmp_path / "stale", monkeypatch, as_of_date="2020-01-15", facts=past_actual)
    assert "quant_implausible" not in meta


def test_extract_only_sanity_failure_is_additive(tmp_path, monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("sanity broke")

    monkeypatch.setattr(dr, "flag_implausible_quant", boom)
    meta, log, out = _extract_only(tmp_path, monkeypatch, as_of_date=None)
    assert "quant_implausible" not in meta and len(meta["quant_unit_warnings"]) == 1
    assert "extract-only: quant sanity check skipped (non-fatal): sanity broke" in log.of("warn")
    assert _load(out / dr.CONTESTED_FILENAME)[-1]["origin"] == "quant_reconcile"
