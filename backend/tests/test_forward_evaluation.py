"""Prospective CLI scenarios with the real publication registry; synthetic outcomes only."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import backtest_eval as cli
from app.services import backtest as service
from app.services import forecast_feedback as registry

pytestmark = pytest.mark.guarded_runner
ENROLLED = "2026-01-01T00:00:00+00:00"
PUBLISHED = "2026-01-02T00:00:00+00:00"
RESOLVED = "2026-03-01T00:00:00+00:00"


@pytest.fixture
def clock(monkeypatch):
    clock = [ENROLLED]
    monkeypatch.setattr(service, "_evaluation_now", lambda: clock[0])
    return clock


def design(n=1, kind="equal_cost_investigation"):
    return {"cohort_id": "pilot-v1", "policy_version": "diagnostic-only/v1",
            "arms": [{"id": "baseline", "method": "pivotal-claim gap selector", "budget_usd": 10},
                     {"id": "candidate", "method": "simulation-guided investigation", "budget_usd": 10}],
            "contrast": {"kind": kind, "baseline": "baseline", "candidate": "candidate",
                         "cost_tolerance_usd": 0.5, "practical_brier_margin": 0.02},
            "questions": [
                {"question_id": f"q{i}", "event_family_id": "one-shared-event", "statement": f"Event {i}",
                 "resolution_criteria": f"Event {i} settles YES by March 2",
                 "forecast_due_at": "2026-01-05T00:00:00Z", "outcome_not_before": "2026-03-01T00:00:00Z",
                 "resolution_date": "2026-03-02",
                 "resolution_source": {"kind": "market_binary", "anchor": {
                     "market_id": f"m{i}", "resolution_equivalence": "exact"}}} for i in range(n)]}


def costs(total=5):
    return {k: total if k == "acquisition" else 0 for k in service.EVALUATION_COST_COMPONENTS}


def publish(tmp_path, q, arm, probability=0.7, **changes):
    row = {"id": "F1", "statement": q["statement"], "resolution_criteria": q["resolution_criteria"],
           "probability": probability, "resolution_date": q["resolution_date"],
           "market_anchor" if q["resolution_source"]["kind"] == "market_binary" else "data_anchor":
               q["resolution_source"]["anchor"]}
    row.update(changes)
    rid = f"r-{q['question_id']}-{arm}"
    registry.record_published_forecast({"binary_forecasts": [row]}, report_id=rid,
                                     created_at=PUBLISHED, d=tmp_path / "registry")
    return {"question_id": q["question_id"], "arm": arm, "status": "published", "report_id": rid,
            "forecast_id": "F1", "costs_usd": costs(), "evidence_sha256": "a" * 64,
            "forecast_request_sha256": "b" * 64}


def settle(tmp_path, trial, q, outcome=True, resolved_at=RESOLVED):
    p = registry.read_published_forecast(trial["report_id"], d=tmp_path / "registry")["forecast"]["binary_forecasts"][0]["probability"]
    evidence = {"report_id": trial["report_id"], "forecast_id": "F1", "model_p": p,
                "market_id": q["resolution_source"]["anchor"]["market_id"], "resolved_outcome": outcome,
                "resolved_yes_price": 1.0 if outcome else 0.0, "resolved_at": resolved_at}
    result = registry.reconcile_published_resolutions(trial["report_id"], market_rows=[evidence],
                                                     data_rows=[], d=tmp_path / "registry")
    assert result["accepted"] == 1


def invoke(tmp_path, capsys, command, payload=None, **kwargs):
    args = [command, "--enrollment", str(tmp_path / "enrollment.jsonl")]
    if payload is not None:
        key = "design" if command == "forward-enroll" else "trial"
        source = tmp_path / f"{key}.json"
        source.write_text(json.dumps(payload))
        args += [f"--{key}", str(source)]
    args += ["--ledger-dir", str(tmp_path / "registry")]
    for key, value in kwargs.items():
        args += [f"--{key.replace('_', '-')}", str(value)]
    code = cli.main(args)
    captured = capsys.readouterr()
    return code, json.loads(captured.out) if code == 0 and captured.out.startswith("{") else captured.err


def test_cli_full_denominator_registry_join_and_no_unknown_as_no(tmp_path, clock, capsys):
    spec = design(7)
    code, enrollment = invoke(tmp_path, capsys, "forward-enroll", spec)
    assert code == 0 and enrollment["enrolled_at"] == ENROLLED
    clock[0] = PUBLISHED
    trials = []
    for i in (0, 1):
        for arm in ("baseline", "candidate"):
            trial = publish(tmp_path, spec["questions"][i], arm)
            assert invoke(tmp_path, capsys, "forward-record", trial)[0] == 0
            trials.append(trial)
    for i, status in enumerate(("failed", "void", "abstained", "disputed"), 2):
        trial = {"question_id": f"q{i}", "arm": "baseline", "status": status,
                 "reason": f"documented {status}", "costs_usd": costs(2)}
        assert invoke(tmp_path, capsys, "forward-record", trial)[0] == 0
    code, pending = invoke(tmp_path, capsys, "forward-score")
    assert code == 0 and pending["enrolled_trials"] == 14
    assert pending["arms"]["baseline"]["dispositions"] == {
        "unresolved": 2, "failed": 1, "void": 1, "abstained": 1, "disputed": 1, "pending": 1}
    for trial in trials[:2]:
        settle(tmp_path, trial, spec["questions"][0])
    clock[0] = "2026-03-03T00:00:00Z"
    before = (tmp_path / "registry/published_forecasts.jsonl").read_bytes()
    code, scored = invoke(tmp_path, capsys, "forward-score")
    assert code == 0 and scored["enrolled_trials"] == 14 and scored["event_families"] == 1
    assert scored["arms"]["baseline"]["dispositions"] == {
        "resolved": 1, "overdue": 2, "failed": 1, "void": 1, "abstained": 1, "disputed": 1}
    assert scored["arms"]["baseline"]["metrics"]["mean_brier"] == 0.09
    assert scored["arms"]["baseline"]["coverage"] == 1 / 7
    assert scored["arms"]["baseline"]["known_cost_usd"] == 18
    assert scored["arms"]["baseline"]["unknown_cost_trials"] == 1
    assert len(scored["comparison"]["excluded_pairs"]) == 6
    assert all("outcome" not in row and "brier" not in row for row in scored["questions"] if row["status"] != "resolved")
    assert (tmp_path / "registry/published_forecasts.jsonl").read_bytes() == before


def test_equal_cost_family_aggregation_and_frozen_revisions(tmp_path, clock, capsys):
    spec = design(2)
    assert invoke(tmp_path, capsys, "forward-enroll", spec)[0] == 0
    clock[0] = PUBLISHED
    trials = []
    for q in spec["questions"]:
        for arm, p in (("baseline", 0.6), ("candidate", 0.8)):
            trial = publish(tmp_path, q, arm, p)
            assert invoke(tmp_path, capsys, "forward-record", trial)[0] == 0
            trials.append((q, trial))
    raw = (tmp_path / "enrollment.jsonl").read_bytes()
    assert invoke(tmp_path, capsys, "forward-record", trials[0][1])[0] == 0
    revised = {**trials[0][1], "report_id": "a-more-favorable-revision"}
    assert invoke(tmp_path, capsys, "forward-record", revised)[0] == 2
    assert (tmp_path / "enrollment.jsonl").read_bytes() == raw
    for q, trial in trials:
        settle(tmp_path, trial, q)
    clock[0] = RESOLVED
    report = invoke(tmp_path, capsys, "forward-score")[1]
    comp = report["comparison"]
    assert comp["enrolled_pairs"] == comp["eligible_pairs"] == 2
    assert comp["eligible_event_families"] == 1
    assert comp["mean_family_brier_delta"] == pytest.approx(-0.12)
    assert comp["probability_lift_established"] is False


@pytest.mark.parametrize("perturb", [None, "evidence_sha256", "forecast_request_sha256", "probability"])
def test_same_evidence_diagnostic_never_claims_probability_lift(tmp_path, clock, capsys, perturb):
    spec = design(kind="same_evidence_diagnostic")
    invoke(tmp_path, capsys, "forward-enroll", spec)
    clock[0] = PUBLISHED
    trials = []
    for arm in ("baseline", "candidate"):
        trial = publish(tmp_path, spec["questions"][0], arm,
                        0.9 if arm == "candidate" and perturb == "probability" else 0.7)
        if arm == "candidate" and perturb in ("evidence_sha256", "forecast_request_sha256"):
            trial[perturb] = "c" * 64
        assert invoke(tmp_path, capsys, "forward-record", trial)[0] == 0
        trials.append(trial)
    for trial in trials:
        settle(tmp_path, trial, spec["questions"][0])
    clock[0] = RESOLVED
    comp = invoke(tmp_path, capsys, "forward-score")[1]["comparison"]
    assert comp["diagnostic_only"] is True and comp["probability_lift_established"] is False
    assert "cannot imply probability lift" in comp["interpretation"]
    assert comp["mean_family_brier_delta"] is None and comp["family_brier_deltas"] == {}
    check = comp["invariance"][0]
    assert check["checked"]
    assert check["same_evidence"] == (perturb != "evidence_sha256")
    assert check["same_request"] == (perturb != "forecast_request_sha256")
    assert check["same_probability"] == (perturb != "probability")


@pytest.mark.parametrize("cost, reason", [(3, "unequal_total_cost"), (11, "over_budget"), (None, "unknown_total_cost")])
def test_same_cost_rejects_cheaper_overbudget_unknown_totals(tmp_path, clock, capsys, cost, reason):
    spec = design()
    invoke(tmp_path, capsys, "forward-enroll", spec)
    clock[0] = PUBLISHED
    trials = []
    for arm in ("baseline", "candidate"):
        trial = publish(tmp_path, spec["questions"][0], arm)
        if arm == "candidate":
            trial["costs_usd"] = costs(cost)
        assert invoke(tmp_path, capsys, "forward-record", trial)[0] == 0
        trials.append(trial)
    for trial in trials:
        settle(tmp_path, trial, spec["questions"][0])
    clock[0] = RESOLVED
    comp = invoke(tmp_path, capsys, "forward-score")[1]["comparison"]
    assert comp["eligible_pairs"] == 0 and comp["excluded_pairs"][0]["reason"] == reason


@pytest.mark.parametrize("probability, eligible", [(0.7, 1), (0.9, 0)])
def test_equal_cost_diagnostics_require_fixed_probabilities(tmp_path, clock, capsys, probability, eligible):
    spec = design(kind="equal_cost_diagnostic")
    invoke(tmp_path, capsys, "forward-enroll", spec)
    clock[0] = PUBLISHED
    trials = []
    for arm in ("baseline", "candidate"):
        trial = publish(tmp_path, spec["questions"][0], arm, probability if arm == "candidate" else 0.7)
        # Same complete cost despite different allocation: saved acquisition
        # budget may be spent on review, retries and verification.
        if arm == "candidate":
            trial["costs_usd"] = {"acquisition": 1, "simulation": 1, "verification": 1,
                                  "retries": 1, "failures": 0.5, "synthesis": 0.5}
        assert invoke(tmp_path, capsys, "forward-record", trial)[0] == 0
        trials.append(trial)
    for trial in trials:
        settle(tmp_path, trial, spec["questions"][0])
    clock[0] = RESOLVED
    report = invoke(tmp_path, capsys, "forward-score")[1]
    comp = report["comparison"]
    assert comp["eligible_pairs"] == eligible
    assert comp["diagnostic_only"] and comp["mean_family_brier_delta"] is None
    assert report["arms"]["candidate"]["known_cost_usd"] == 5


@pytest.mark.parametrize("mutation", ["late", "outcome", "duplicate_id", "duplicate_contract", "budget", "wide_tolerance"])
def test_cli_enrollment_rejects_invalid_designs(tmp_path, clock, capsys, mutation):
    spec = design()
    if mutation == "late":
        clock[0] = RESOLVED
    elif mutation == "outcome":
        spec["questions"][0]["resolved_outcome"] = False
    elif mutation.startswith("duplicate"):
        spec["questions"].append(deepcopy(spec["questions"][0]))
        if mutation == "duplicate_contract":
            spec["questions"][1]["question_id"] = "alias"
    elif mutation == "budget":
        spec["arms"][0]["budget_usd"] = 20
    else:
        spec["contrast"]["cost_tolerance_usd"] = 9
    assert invoke(tmp_path, capsys, "forward-enroll", spec)[0] == 2


def test_design_idempotence_and_frozen_contract(tmp_path, clock, capsys):
    spec = design()
    invoke(tmp_path, capsys, "forward-enroll", spec)
    raw = (tmp_path / "enrollment.jsonl").read_bytes()
    clock[0] = RESOLVED
    assert invoke(tmp_path, capsys, "forward-enroll", spec)[0] == 0
    spec["questions"][0]["statement"] = "A different event"
    assert invoke(tmp_path, capsys, "forward-enroll", spec)[0] == 2
    assert (tmp_path / "enrollment.jsonl").read_bytes() == raw


@pytest.mark.parametrize("mutation", ["unpublished", "statement", "anchor", "late", "resolved", "bad_cost", "backdate", "unenrolled"])
def test_cli_publication_binding_controls(tmp_path, clock, capsys, mutation):
    spec = design()
    invoke(tmp_path, capsys, "forward-enroll", spec)
    clock[0] = PUBLISHED
    extra = {"statement": "wrong entity"} if mutation == "statement" else {}
    if mutation == "anchor":
        extra = {"market_anchor": {"market_id": "foreign", "resolution_equivalence": "exact"}}
    trial = publish(tmp_path, spec["questions"][0], "baseline", **extra)
    if mutation == "unpublished":
        trial["report_id"] = "unknown"
    elif mutation == "late":
        clock[0] = "2026-01-05T00:00:00Z"
    elif mutation == "resolved":
        settle(tmp_path, trial, spec["questions"][0])
    elif mutation == "bad_cost":
        trial["costs_usd"].pop("failures")
    elif mutation == "backdate":
        trial["recorded_at"] = ENROLLED
    elif mutation == "unenrolled":
        trial["question_id"] = "not-enrolled"
    raw = (tmp_path / "enrollment.jsonl").read_bytes()
    assert invoke(tmp_path, capsys, "forward-record", trial)[0] == 2
    assert (tmp_path / "enrollment.jsonl").read_bytes() == raw


def test_conflicting_outcomes_and_early_resolution_do_not_become_lift(tmp_path, clock, capsys):
    spec = design(2)
    invoke(tmp_path, capsys, "forward-enroll", spec)
    clock[0] = PUBLISHED
    trials = []
    for q in spec["questions"]:
        for arm in ("baseline", "candidate"):
            trial = publish(tmp_path, q, arm)
            assert invoke(tmp_path, capsys, "forward-record", trial)[0] == 0
            trials.append((trial, q, arm))
    for trial, q, arm in trials:
        settle(tmp_path, trial, q, outcome=arm == "baseline",
               resolved_at="2026-02-01T00:00:00Z" if q["question_id"] == "q1" else RESOLVED)
    clock[0] = RESOLVED
    report = invoke(tmp_path, capsys, "forward-score")[1]
    assert report["comparison"]["eligible_pairs"] == 0
    assert report["comparison"]["excluded_pairs"][0]["reason"] == "conflicting_outcomes"
    assert report["arms"]["baseline"]["dispositions"]["disputed"] == 1


def test_corrupt_enrollment_fails_closed(tmp_path, clock, capsys):
    invoke(tmp_path, capsys, "forward-enroll", design())
    with (tmp_path / "enrollment.jsonl").open("ab") as stream:
        stream.write(b'{"incomplete":')
    code, error = invoke(tmp_path, capsys, "forward-score")
    assert code == 2 and "torn tail" in error


@pytest.mark.parametrize("vintage, resolved", [("2026-03-01", True), ("2026-03-02", False), ("", False)])
def test_official_data_outcome_reuses_registry_validator(tmp_path, clock, capsys, vintage, resolved):
    from app.services import official_data
    spec = design()
    q = spec["questions"][0]
    anchor = {"series": "fred:UNRATE", "comparator": ">", "threshold": 4,
              "units": "Percent", "observation": "2026-02", "frequency": "M"}
    q["resolution_source"] = {"kind": "official_data_binary", "anchor": anchor, "outcome_vintage": "2026-03-01"}
    invoke(tmp_path, capsys, "forward-enroll", spec)
    clock[0] = PUBLISHED
    trial = publish(tmp_path, q, "baseline")
    assert invoke(tmp_path, capsys, "forward-record", trial)[0] == 0
    dataset = {"series": "fred:UNRATE", "units": "Percent", "frequency": "M", "retrieved_at": RESOLVED,
               "source_url": "https://fred.stlouisfed.org/series/UNRATE",
               "observations": [{"date": "2026-02-01", "value": 4.2, "flag": ""}], "vintage": vintage}
    decision = official_data.resolve_data_anchor(anchor, dataset, as_of=RESOLVED)
    evidence = {"report_id": trial["report_id"], "forecast_id": "F1", "series": "fred:UNRATE", "model_p": 0.7,
                "resolved_outcome": decision["outcome"], "resolved_at": RESOLVED,
                "observation": decision["observation"], "data_anchor": anchor,
                "dataset_snapshot": dataset, "dataset_sha256": registry._digest(dataset),
                "units": "Percent", "transform": "", "source_url": dataset["source_url"],
                "retrieved_at": RESOLVED, "vintage": vintage}
    assert registry.reconcile_published_resolutions(trial["report_id"], market_rows=[], data_rows=[evidence],
                                                    d=tmp_path / "registry")["accepted"] == 1
    clock[0] = RESOLVED
    result = invoke(tmp_path, capsys, "forward-score")[1]
    assert result["arms"]["baseline"]["metrics"]["mean_brier"] == (0.09 if resolved else None)
    assert result["arms"]["baseline"]["dispositions"] == {"resolved" if resolved else "disputed": 1}
    assert result["arms"]["candidate"]["metrics"]["n"] == 0


def test_partial_failed_costs_preserve_known_lower_bound(tmp_path, clock, capsys):
    invoke(tmp_path, capsys, "forward-enroll", design())
    partial = costs(12)
    partial["retries"] = None
    trial = {"question_id": "q0", "arm": "baseline", "status": "failed", "reason": "meter lost",
             "costs_usd": partial}
    assert invoke(tmp_path, capsys, "forward-record", trial)[0] == 0
    result = invoke(tmp_path, capsys, "forward-score")[1]
    assert result["arms"]["baseline"]["known_cost_usd"] == 12
    assert result["arms"]["baseline"]["unknown_cost_trials"] == 1
    assert result["arms"]["baseline"]["over_budget_trials"] == 1
    assert result["questions"][0]["cost_usd"] is None


def test_explicit_publication_deadline_cannot_change_enrolled_question(tmp_path, clock, capsys):
    spec = design()
    invoke(tmp_path, capsys, "forward-enroll", spec)
    clock[0] = PUBLISHED
    trial = publish(tmp_path, spec["questions"][0], "baseline", resolution_date="2026-12-31")
    assert invoke(tmp_path, capsys, "forward-record", trial)[0] == 2


def test_market_paraphrases_cannot_create_independent_families(tmp_path, clock, capsys):
    spec = design(2)
    spec["questions"][1]["resolution_source"] = deepcopy(spec["questions"][0]["resolution_source"])
    spec["questions"][1]["event_family_id"] = "same-settlement-under-new-name"
    assert invoke(tmp_path, capsys, "forward-enroll", spec)[0] == 2


def test_official_enrollment_requires_supported_vintage(tmp_path, clock, capsys):
    spec = design()
    spec["questions"][0]["resolution_source"] = {"kind": "official_data_binary", "anchor": {
        "series": "fred:UNRATE", "comparator": ">", "threshold": 4, "units": "Percent", "observation": "2026-02"}}
    assert invoke(tmp_path, capsys, "forward-enroll", spec)[0] == 2


@pytest.mark.parametrize("frequency", [None, "M"])
def test_official_period_aliases_cannot_split_one_settlement_family(tmp_path, clock, capsys, frequency):
    spec = design(2)
    for i, q in enumerate(spec["questions"]):
        q["event_family_id"] = f"alias-family-{i}"
        q["resolution_source"] = {"kind": "official_data_binary", "outcome_vintage": "2026-03-01", "anchor": {
            "series": "fred:UNRATE", "comparator": ">", "threshold": 4, "units": "Percent",
            **({"observation": "2026-02"} if i == 0 else {"period": "2026-02-01"})}}
        if frequency:
            q["resolution_source"]["anchor"]["frequency"] = frequency
    assert invoke(tmp_path, capsys, "forward-enroll", spec)[0] == 2


@pytest.mark.parametrize("status", ["void", "disputed"])
def test_published_question_can_be_withheld_without_replacing_prediction(tmp_path, clock, capsys, status):
    spec = design()
    invoke(tmp_path, capsys, "forward-enroll", spec)
    clock[0] = PUBLISHED
    original = publish(tmp_path, spec["questions"][0], "baseline")
    assert invoke(tmp_path, capsys, "forward-record", original)[0] == 0
    clock[0] = RESOLVED
    disposition = {"question_id": "q0", "arm": "baseline", "status": status,
                   "reason": "Documented settlement cancellation or dispute", "costs_usd": costs()}
    assert invoke(tmp_path, capsys, "forward-record", disposition)[0] == 0
    assert invoke(tmp_path, capsys, "forward-record", disposition)[0] == 0
    report = invoke(tmp_path, capsys, "forward-score")[1]
    row = report["questions"][0]
    assert row["status"] == status and row["probability"] == 0.7 and row["report_id"] == original["report_id"]
    assert "outcome" not in row and report["enrolled_trials"] == 2
    assert invoke(tmp_path, capsys, "forward-record", {**original, "report_id": "revision"})[0] == 2


def test_real_cli_guarded_child_restart(tmp_path, clock, capsys):
    """Restart invokes the script's real __main__; only a named child fixture is allowed."""
    guard = sys.modules.get("main_offline_guard")
    if guard is None:
        pytest.fail("run through main_offline_pytest.py")
    invoke(tmp_path, capsys, "forward-enroll", design())
    child = tmp_path / "forward_cli_child.py"
    script = Path(cli.__file__).resolve()
    child.write_text("import runpy, sys\n" +
                     f"sys.argv = [{str(script)!r}, 'forward-score', '--enrollment', " +
                     f"{str(tmp_path / 'enrollment.jsonl')!r}, '--ledger-dir', {str(tmp_path / 'registry')!r}]\n" +
                     f"runpy.run_path({str(script)!r}, run_name='__main__')\n")
    guard.allow_python_script(child)
    result = subprocess.run([sys.executable, str(child)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["enrolled_trials"] == 2 and report["arms"]["baseline"]["dispositions"] == {"overdue": 1}


def old_market_publication(tmp_path, *, market_id="m0", outcome=True, terminal_anchor=None):
    """Different publication/forecast identity, same externally settled event."""
    anchor = {"market_id": market_id, "resolution_equivalence": "exact", **(terminal_anchor or {})}
    registry.record_published_forecast({"binary_forecasts": [{
        "id": "OLD-F1", "statement": "Old wording", "resolution_criteria": "Earlier contract wording",
        "probability": 0.7, "market_anchor": anchor}]}, report_id="OLD",
        created_at="2025-01-01T00:00:00Z", d=tmp_path / "registry")
    if outcome is not None:
        result = registry.reconcile_published_resolutions("OLD", market_rows=[{
            "report_id": "OLD", "forecast_id": "OLD-F1", "market_id": market_id,
            "model_p": 0.7, "resolved_outcome": outcome, "resolved_yes_price": float(outcome),
            "resolved_at": "2025-02-01T00:00:00Z"}], data_rows=[], d=tmp_path / "registry")
        assert result["accepted"] == 1


@pytest.mark.parametrize("outcome", [True, False])
def test_machine_known_market_rejects_fresh_enrollment(tmp_path, clock, capsys, monkeypatch, outcome):
    from app.config import Config
    monkeypatch.setattr(Config, "FORECAST_LEDGER_DIR", str(tmp_path / "registry"))
    old_market_publication(tmp_path, outcome=outcome)
    before = (tmp_path / "registry/published_forecasts.jsonl").read_bytes()
    code, error = invoke(tmp_path, capsys, "forward-enroll", design())
    assert code == 2 and "known settlement" in error
    assert (tmp_path / "registry/published_forecasts.jsonl").read_bytes() == before


@pytest.mark.parametrize("outcome", [True, False])
def test_machine_known_market_rejects_new_report_but_keeps_late_failure(tmp_path, clock, capsys, outcome):
    spec = design()
    assert invoke(tmp_path, capsys, "forward-enroll", spec)[0] == 0
    old_market_publication(tmp_path, outcome=outcome)
    clock[0] = PUBLISHED
    trial = publish(tmp_path, spec["questions"][0], "baseline")
    before = (tmp_path / "enrollment.jsonl").read_bytes()
    code, error = invoke(tmp_path, capsys, "forward-record", trial)
    assert code == 2 and "known settlement" in error
    assert (tmp_path / "enrollment.jsonl").read_bytes() == before
    clock[0] = "2026-04-01T00:00:00Z"
    failure = {"question_id": "q0", "arm": "baseline", "status": "failed", "reason": "outcome already known",
               "costs_usd": costs(2)}
    assert invoke(tmp_path, capsys, "forward-record", failure)[0] == 0
    report = invoke(tmp_path, capsys, "forward-score")[1]
    assert report["enrolled_trials"] == 2 and report["arms"]["baseline"]["dispositions"] == {"failed": 1}
    assert report["arms"]["baseline"]["known_cost_usd"] == 2 and "outcome" not in report["questions"][0]


@pytest.mark.parametrize("field,value", [("closed", True), ("resolved", True), ("resolved_outcome", True),
                                        ("resolved_outcome", False), ("resolved_outcome", "No")])
def test_terminal_market_anchor_rejects_enrollment(tmp_path, clock, capsys, field, value):
    spec = design()
    spec["questions"][0]["resolution_source"]["anchor"][field] = value
    code, error = invoke(tmp_path, capsys, "forward-enroll", spec)
    assert code == 2 and "terminal market anchor" in error


def test_terminal_market_in_another_publication_rejects_prediction(tmp_path, clock, capsys):
    spec = design()
    assert invoke(tmp_path, capsys, "forward-enroll", spec)[0] == 0
    old_market_publication(tmp_path, outcome=None, terminal_anchor={"resolved_outcome": False})
    clock[0] = PUBLISHED
    trial = publish(tmp_path, spec["questions"][0], "baseline")
    code, error = invoke(tmp_path, capsys, "forward-record", trial)
    assert code == 2 and "known settlement" in error


def test_unrelated_known_market_and_explicit_unresolved_flags_remain_admissible(tmp_path, clock, capsys, monkeypatch):
    from app.config import Config
    monkeypatch.setattr(Config, "FORECAST_LEDGER_DIR", str(tmp_path / "registry"))
    old_market_publication(tmp_path, market_id="different")
    spec = design()
    spec["questions"][0]["resolution_source"]["anchor"].update(closed=False, resolved=False, resolved_outcome=None)
    assert invoke(tmp_path, capsys, "forward-enroll", spec)[0] == 0
    clock[0] = PUBLISHED
    assert invoke(tmp_path, capsys, "forward-record", publish(tmp_path, spec["questions"][0], "baseline"))[0] == 0


def old_official_resolution(tmp_path):
    from app.services import official_data
    q = design()["questions"][0]
    # A legacy published anchor can omit frequency and use the alternate period
    # spelling; admitted dataset metadata provides its authoritative frequency.
    anchor = {"series": "fred:UNRATE", "period": "2026-02-01", "units": "Percent",
              "comparator": ">", "threshold": 4}
    q["resolution_source"] = {"kind": "official_data_binary", "anchor": anchor}
    trial = publish(tmp_path, q, "OLD")
    dataset = {"series": "fred:UNRATE", "units": "Percent", "frequency": "M", "vintage": "2026-03-01",
               "retrieved_at": RESOLVED, "source_url": "https://fred.stlouisfed.org/series/UNRATE",
               "observations": [{"date": "2026-02-01", "value": 4.2, "flag": ""}]}
    decision = official_data.resolve_data_anchor(anchor, dataset, as_of=RESOLVED)
    evidence = {"report_id": trial["report_id"], "forecast_id": "F1", "series": "fred:UNRATE", "model_p": 0.7,
                "resolved_outcome": decision["outcome"], "resolved_at": RESOLVED,
                "observation": decision["observation"], "data_anchor": anchor,
                "dataset_snapshot": dataset, "dataset_sha256": registry._digest(dataset),
                "units": "Percent", "transform": "", "source_url": dataset["source_url"],
                "retrieved_at": RESOLVED, "vintage": "2026-03-01"}
    assert registry.reconcile_published_resolutions(trial["report_id"], market_rows=[], data_rows=[evidence],
                                                    d=tmp_path / "registry")["accepted"] == 1


@pytest.mark.parametrize("admission", ["enroll", "record"])
@pytest.mark.parametrize("variation,known", [("same", True), ("threshold", True), ("comparator", True),
                                           ("future_vintage", False), ("series", False), ("period", False)])
def test_machine_known_official_snapshot_determines_new_predicates(tmp_path, clock, capsys, admission, variation, known):
    spec = design()
    q = spec["questions"][0]
    source = {"kind": "official_data_binary", "outcome_vintage": "2026-03-01", "anchor": {
        "series": "fred:UNRATE", "observation": "2026-02", "frequency": "M", "units": "Percent",
        "comparator": ">", "threshold": 4}}
    if variation == "threshold":
        source["anchor"]["threshold"] = 4.1
    elif variation == "comparator":
        source["anchor"]["comparator"] = "<"
    elif variation == "future_vintage":
        source["outcome_vintage"] = "2026-03-02"
    elif variation == "series":
        source["anchor"]["series"] = "fred:CIVPART"
    elif variation == "period":
        source["anchor"]["observation"] = "2026-01"
    q["resolution_source"] = source
    if admission == "record":
        assert invoke(tmp_path, capsys, "forward-enroll", spec)[0] == 0
    old_official_resolution(tmp_path)
    if admission == "enroll":
        code, result = invoke(tmp_path, capsys, "forward-enroll", spec)
    else:
        clock[0] = PUBLISHED
        # The new report belongs to a legitimate enrolled arm; its external
        # report identity differs from the source of the known observation.
        code, result = invoke(tmp_path, capsys, "forward-record", publish(tmp_path, q, "baseline"))
    assert code == (2 if known else 0)
    if known:
        assert "known settlement" in result
