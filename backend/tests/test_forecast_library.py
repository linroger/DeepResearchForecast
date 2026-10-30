"""Real library/journal persistence with synthetic sources; no live accuracy claim."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from app.services import forecast_feedback as feedback
from app.services import forecast_ledger as ledger
from app.services import forecast_library as library
from app.services.official_data import bridge_module, resolve_data_anchor


pytestmark = pytest.mark.guarded_runner


def entry(kind="mechanism"):
    contents = {
        "mechanism": {"template": "linear", "parameters": {"coefficients": [1.0], "intercept": {"low": 0, "high": 1}}},
        "reference_class": {"series": "fred:UNRATE", "units": "Percent",
                            "comparator": {"operator": "gt", "threshold": 4},
                            "sampleSize": 10, "eventCount": 3,
                            "windowStart": "2025-01-01", "windowEnd": "2026-01-01"},
        "actor": {"name": "Synthetic statistics office", "actorClass": "publisher",
                  "levers": ["release"], "record": "Released a dated statistical observation."},
    }
    return {"kind": kind, "title": "Synthetic unemployment context", "nodeTerms": ["unemployment", "growth"],
            "asOf": "2026-02-02", "evidenceDate": "2026-01-01", "availableAt": "2026-02-01",
            "sources": [{"sourceId": "S1", "url": "https://fred.stlouisfed.org/series/UNRATE",
                         "title": "Synthetic fixture observation", "publishedAt": "2026-01-15",
                         "retrievedAt": "2026-02-01", "originCluster": "synthetic-office",
                         "tier": "primary", "fetched": True, "passage": "Synthetic unemployment is 4.2 percent."}],
            "provenance": {"caseId": "first-case", "caseHash": "a" * 64, "recordId": "record-1", "basis": "observed"},
            "uncertainty": "Synthetic sample; transferability is unknown.", "gaps": [], "content": contents[kind]}


def select(root, **changes):
    return library.select_entries(root, **dict({"as_of": "2026-04-01", "node_terms": ["unemployment"]}, **changes))


def saved_path(root, item, identity):
    return root / item["kind"] / (identity + ".json")


def case_fixture():
    return json.loads((Path(__file__).parent / "fixtures/target_case.json").read_text())


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def outcome_entry(tmp_path, monkeypatch, *, large=False):
    journal = tmp_path / "journal"
    monkeypatch.setattr(ledger, "ledger_dir", lambda: str(journal))
    anchor = {"series": "fred:UNRATE", "comparator": ">", "threshold": 4,
              "units": "Percent", "observation": "2026-01"}
    forecast = {"binary_forecasts": [{"id": "F1", "statement": "Unemployment above 4 percent",
                                      "probability": 0.6, "resolution_criteria": "January 2026 unemployment >4",
                                      "data_anchor": anchor}]}
    feedback.record_published_forecast(forecast, report_id="r1", created_at="2026-01-01", d=journal)
    resolved = "2026-03-01T00:00:00Z"
    dataset = {"series": "fred:UNRATE", "units": "Percent", "frequency": "M",
               "retrieved_at": resolved, "source_url": "https://fred.stlouisfed.org/series/UNRATE",
               "observations": [{"date": "2026-01-01", "value": 4.2, "flag": ""}]}
    if large:
        dataset["description"] = "x" * 270000
    decision = resolve_data_anchor(anchor, dataset, as_of=resolved)
    assert decision["status"] == "resolved"
    evidence = {"report_id": "r1", "forecast_id": "F1", "series": "fred:UNRATE",
                "resolved_outcome": decision["outcome"], "model_p": 0.6, "resolved_at": resolved,
                "observation": decision["observation"], "data_anchor": anchor,
                "dataset_snapshot": dataset, "dataset_sha256": digest(dataset),
                "units": "Percent", "transform": "", "source_url": dataset["source_url"],
                "retrieved_at": resolved, "vintage": ""}
    receipt = feedback.reconcile_published_resolutions("r1", market_rows=[], data_rows=[evidence], d=journal)
    assert receipt["accepted"] == 1
    row = feedback.read_published_resolutions("r1", d=journal)[0]
    item = entry("reference_class")
    item.update(asOf="2026-03-01", availableAt="2026-03-01", evidenceDate="2026-01-01")
    item["sources"][0]["retrievedAt"] = resolved
    item["content"].update(sampleSize=1, eventCount=int(row["outcome"]),
                           windowStart=row["evidence"]["observation"]["date"],
                           windowEnd=row["evidence"]["observation"]["date"])
    item["provenance"].update(basis="journal_outcome", journalProof={
        "reportId": "r1", "forecastId": "F1", "publicationSha256": row["publication_sha256"],
        "eventSha256": digest({"schema_version": 1, "type": "outcome", "record": row})})
    return item, journal


def test_second_case_reuses_base_rate_and_mechanism_with_original_provenance(tmp_path):
    root = tmp_path / "_library"
    original = [entry("reference_class"), entry()]
    ids = {library.record_entry(root, row) for row in original}
    second_case = {"caseId": "second-case", "asOf": "2026-04-01", "nodeTerms": ["UNEMPLOYMENT"]}
    rows = library.select_entries(root, as_of=second_case["asOf"], node_terms=second_case["nodeTerms"])
    assert {r["entryId"] for r in rows} == ids
    assert {r["kind"] for r in rows} == {"reference_class", "mechanism"}
    assert all(r["provenance"]["caseId"] == "first-case" and r["sources"] == original[0]["sources"] for r in rows)
    rows[0]["sources"][0]["passage"] = "changed copy"
    assert select(root)[0]["sources"][0]["passage"] != "changed copy"
    assert not list(root.rglob("*.jsonl"))


def test_ids_are_immutable_deterministic_and_kind_separated(tmp_path):
    first = entry()
    first_id = library.record_entry(tmp_path, first)
    before = saved_path(tmp_path, first, first_id).read_bytes()
    assert library.record_entry(tmp_path, dict(reversed(list(first.items())))) == first_id
    first["content"]["parameters"]["intercept"]["high"] = 2
    changed_id = library.record_entry(tmp_path, first)
    assert changed_id != first_id
    assert saved_path(tmp_path, first, first_id).read_bytes() == before
    actor_id = library.record_entry(tmp_path, entry("actor"))
    assert len({first_id, changed_id, actor_id}) == 3
    # A kind transplant cannot retain the original identity or bypass validation.
    transplanted = tmp_path / "actor" / (first_id + ".json")
    transplanted.write_bytes(before)
    with pytest.raises(library.LibraryError, match="entry_hash_mismatch"):
        select(tmp_path)


def test_concurrent_idempotent_writes_leave_one_complete_row(tmp_path):
    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(lambda _: library.record_entry(tmp_path, entry()), range(16)))
    assert len(set(ids)) == 1
    assert len(select(tmp_path)) == 1
    assert len(list(tmp_path.rglob("*json"))) == 1
    assert not list(tmp_path.rglob(".pending-*"))


@pytest.mark.parametrize("damage", ["content", "duplicate_key", "truncated", "symlink"])
def test_tamper_is_rejected_on_read_and_idempotent_write(tmp_path, damage):
    item = entry()
    identity = library.record_entry(tmp_path, item)
    path = saved_path(tmp_path, item, identity)
    raw = path.read_text()
    if damage == "content":
        row = json.loads(raw)
        row["title"] = "tampered"
        path.write_text(json.dumps(row))
    elif damage == "duplicate_key":
        path.write_text('{"title":"ignored",' + raw[1:])
    elif damage == "truncated":
        path.write_text(raw[:-3])
    else:
        target = tmp_path / "elsewhere.json"
        target.write_text(raw)
        path.unlink()
        path.symlink_to(target)
    for operation in (lambda: select(tmp_path), lambda: library.record_entry(tmp_path, item)):
        with pytest.raises(library.LibraryError):
            operation()


def test_cutoff_is_exact_in_utc_and_retrieval_is_not_publication(tmp_path):
    item = entry()
    item.update(asOf="2026-02-02T00:00:00Z", availableAt="2026-02-02T00:00:00Z")
    item["sources"][0]["retrievedAt"] = "2026-02-02T01:00:00+01:00"
    library.record_entry(tmp_path, item)
    assert select(tmp_path, as_of="2026-02-01T23:59:59Z") == []
    assert len(select(tmp_path, as_of="2026-02-02T00:00:00Z")) == 1
    assert select(tmp_path, as_of="2026-01-01") == []


@pytest.mark.parametrize("field", ["asOf", "availableAt", "evidenceDate", "retrievedAt", "publishedAt"])
def test_future_dates_are_rejected(tmp_path, field):
    item = entry()
    destination = item["sources"][0] if field in ("retrievedAt", "publishedAt") else item
    destination[field] = "2099-01-01"
    with pytest.raises(library.LibraryError):
        library.record_entry(tmp_path, item)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("change", ["naive", "source_late", "publication_late", "availability_late", "unknown_publication"])
def test_invalid_availability_and_missing_dates_fail_closed(tmp_path, change):
    item = entry()
    if change == "naive":
        item["availableAt"] = "2026-02-01T01:00:00"
    elif change == "source_late":
        item["sources"][0]["retrievedAt"] = "2026-02-02"
    elif change == "publication_late":
        item["sources"][0]["publishedAt"] = "2026-02-02"
    elif change == "availability_late":
        item["availableAt"] = "2026-02-03"
    else:
        item["sources"][0]["publishedAt"] = None
    with pytest.raises(library.LibraryError):
        library.record_entry(tmp_path, item)


def test_unknown_publication_date_stays_unknown_with_explicit_gap(tmp_path):
    item = entry()
    item["sources"][0]["publishedAt"] = None
    item["gaps"] = ["Publication date unknown; observation period is independently known."]
    library.record_entry(tmp_path, item)
    assert select(tmp_path)[0]["sources"][0]["publishedAt"] is None


@pytest.mark.parametrize("change", ["simulation", "verified_flag", "score", "missing_proof", "unexpected_proof", "nonfinite", "tuple", "actor_assumption"])
def test_unsafe_json_and_unverified_promotion_are_rejected(tmp_path, change):
    item = entry("actor" if change == "actor_assumption" else "mechanism")
    if change == "simulation":
        item["provenance"]["basis"] = "simulation"
    elif change == "verified_flag":
        item["content"]["hindcastValidated"] = True
    elif change == "score":
        item["content"]["brier"] = 0.01
    elif change == "missing_proof":
        item["provenance"]["basis"] = "journal_outcome"
    elif change == "unexpected_proof":
        item["provenance"]["journalProof"] = {"verified": True}
    elif change == "nonfinite":
        item["content"]["parameters"]["intercept"] = float("nan")
    elif change == "tuple":
        item["nodeTerms"] = ("unemployment",)
    else:
        item["provenance"]["basis"] = "assumed"
        item["gaps"] = ["Simulated behavior is not a real-world record."]
    with pytest.raises(library.LibraryError):
        library.record_entry(tmp_path, item)


@pytest.mark.parametrize("rehashed", [False, True])
def test_outcome_proof_is_revalidated_and_never_leaks_before_resolution(tmp_path, monkeypatch, rehashed):
    item, journal = outcome_entry(tmp_path, monkeypatch)
    root = tmp_path / "_library"
    identity = library.record_entry(root, item)
    assert select(root, as_of="2026-02-28") == []
    rows = select(root, as_of="2026-03-01")
    assert rows[0]["entryId"] == identity
    assert "score" not in json.dumps(rows)
    path = journal / "published_forecasts.jsonl"
    lines = path.read_text().splitlines()
    event = json.loads(lines[-1])
    event["event"]["record"]["outcome"] = False
    if rehashed:
        event["sha256"] = digest(event["event"])
    lines[-1] = json.dumps(event)
    path.write_text("\n".join(lines) + "\n")
    with pytest.raises(library.LibraryError, match="invalid_outcome_journal"):
        select(root)


@pytest.mark.parametrize("change", ["hash", "publication", "forecast", "counts", "sample", "comparator", "window", "source", "backdate"])
def test_journal_proof_cannot_launder_changed_claims(tmp_path, monkeypatch, change):
    item, _ = outcome_entry(tmp_path, monkeypatch)
    if change in ("hash", "publication"):
        item["provenance"]["journalProof"]["eventSha256" if change == "hash" else "publicationSha256"] = "b" * 64
    elif change == "forecast":
        item["provenance"]["journalProof"]["forecastId"] = "missing"
    elif change == "counts":
        item["content"]["eventCount"] = 0
    elif change == "sample":
        item["content"]["sampleSize"] = 2
    elif change == "comparator":
        item["content"]["comparator"]["threshold"] = 5
    elif change == "window":
        item["content"]["windowStart"] = "2025-12-01"
    elif change == "source":
        item["sources"][0]["url"] = "https://example.test/other"
    else:
        item.update(asOf="2026-02-02", availableAt="2026-02-01")
        item["sources"][0]["retrievedAt"] = "2026-02-01"
    with pytest.raises(library.LibraryError):
        library.record_entry(tmp_path / "_library", item)


def test_large_valid_journal_snapshot_does_not_inherit_library_size_cap(tmp_path, monkeypatch):
    item, _ = outcome_entry(tmp_path, monkeypatch, large=True)
    library.record_entry(tmp_path / "_library", item)
    assert len(select(tmp_path / "_library")) == 1


def named_actor_outcome_entry(tmp_path, monkeypatch):
    journal = tmp_path / "journal"
    monkeypatch.setattr(ledger, "ledger_dir", lambda: str(journal))
    binary = {"id": "F1", "statement": "The office issues a release", "probability": 0.6,
              "resolution_criteria": "The office publishes the scheduled release by January end",
              "resolution_contract": {"kind": "named_source_event", "deadline": "2026-01-31",
                                      "publisher": "Synthetic office", "event": "Scheduled release"}}
    feedback.record_published_forecast({"binary_forecasts": [binary]}, report_id="actor-report",
                                       created_at="2026-01-01", d=journal)
    evidence = {"text": "The office issued the scheduled release.", "url": "https://example.test/office",
                "publisher": "Synthetic office", "published_at": "2026-02-01T00:00:00Z",
                "retrieved_at": "2026-02-01T01:00:00Z", "adjudicator": "Synthetic fixture adjudicator"}
    row = feedback.resolve_published_binary("actor-report", "F1", outcome=True, evidence=evidence,
                                            contract_sha256=feedback.binary_resolution_contract_sha256(binary),
                                            resolved_at="2026-02-01T02:00:00Z", d=journal)
    item = entry("actor")
    item["content"]["record"] = evidence["text"]
    item["sources"][0].update(url=evidence["url"], passage=evidence["text"],
                               publishedAt=evidence["published_at"], retrievedAt=evidence["retrieved_at"])
    item["provenance"].update(basis="journal_outcome", journalProof={
        "reportId": "actor-report", "forecastId": "F1", "publicationSha256": row["publication_sha256"],
        "eventSha256": digest({"schema_version": 1, "type": "outcome", "record": row})})
    return item, journal


@pytest.mark.parametrize("operation", ["write", "select"])
@pytest.mark.parametrize("kind", ["actor", "mechanism"])
@pytest.mark.parametrize("outcome_kind", ["named_source_event", "official_data_binary"])
def test_unbound_journal_learning_fails_closed(tmp_path, monkeypatch, operation, kind, outcome_kind):
    """An authenticated event/URL cannot validate a new actor claim or coefficient."""
    producer = named_actor_outcome_entry if outcome_kind == "named_source_event" else outcome_entry
    item, _ = producer(tmp_path, monkeypatch)
    item["kind"] = kind
    item["content"] = entry(kind)["content"]
    if kind == "actor":
        item["content"].update(name="Unrelated company", actorClass="company",
                               record="This unrelated actor honoured all of its real-world commitments.")
    else:
        item["content"]["parameters"] = {"coefficients": [99], "intercept": 42}
    root = tmp_path / "_library"
    if operation == "select":
        # Exact pre-repair wire form: a real journal proof and matching content ID,
        # but no independently admitted actor/behaviour or mechanism binding.
        item["schemaVersion"] = library.SCHEMA
        identity = "fl1-" + digest(item)
        path = saved_path(root, item, identity)
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(item))
    with pytest.raises(library.LibraryError, match="unsupported_journal_" + kind + "_proof"):
        if operation == "write":
            library.record_entry(root, item)
        else:
            select(root)
    if operation == "write":
        assert not root.exists()


def test_verbatim_named_event_text_is_not_typed_actor_behaviour_proof(tmp_path, monkeypatch):
    item, _ = named_actor_outcome_entry(tmp_path, monkeypatch)
    assert item["content"]["record"] == item["sources"][0]["passage"]
    with pytest.raises(library.LibraryError, match="unsupported_journal_actor_proof"):
        library.record_entry(tmp_path / "_library", item)


@pytest.mark.parametrize("basis", ["observed", "assumed"])
@pytest.mark.parametrize("nested", [False, True])
def test_parameter_basis_cannot_claim_journal_validation(tmp_path, basis, nested):
    item = entry()
    item["provenance"]["basis"] = basis
    if basis == "assumed":
        item["gaps"] = ["The mechanism and its parameters remain assumptions."]
    parameter = {"low": 0, "high": 1, "basis": "journal_outcome"}
    item["content"]["parameters"]["intercept"] = [[parameter]] if nested else parameter
    with pytest.raises(library.LibraryError, match="unsupported_journal_mechanism_proof"):
        library.record_entry(tmp_path / "_library", item)
    assert not (tmp_path / "_library").exists()


def test_manually_observed_source_backed_actor_record_remains_supported(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("A manually observed actor record must not acquire journal authority")

    monkeypatch.setattr(feedback, "read_published_resolutions", forbidden)
    item = entry("actor")
    identity = library.record_entry(tmp_path / "_library", item)
    row = select(tmp_path / "_library", kinds=["actor"])[0]
    assert row["entryId"] == identity
    assert row["provenance"]["basis"] == "observed" and "journalProof" not in row["provenance"]
    assert row["content"] == item["content"] and row["sources"] == item["sources"]


def test_exact_journal_reference_observation_remains_supported(tmp_path, monkeypatch):
    item, _ = outcome_entry(tmp_path, monkeypatch)
    identity = library.record_entry(tmp_path / "_library", item)
    row = select(tmp_path / "_library")[0]
    assert row["entryId"] == identity and row["provenance"] == item["provenance"]
    assert row["content"] == item["content"]
    assert row["content"]["sampleSize"] == row["content"]["eventCount"] == 1
    assert select(tmp_path / "_library", as_of="2026-02-28") == []


def test_unjournaled_or_legacy_outcome_cannot_authorize_learning(tmp_path, monkeypatch):
    item, journal = outcome_entry(tmp_path, monkeypatch)
    # Native and legacy rows, even copied byte-for-byte, are not journal authority.
    path = journal / "published_forecasts.jsonl"
    events = [json.loads(line) for line in path.read_text().splitlines()]
    path.write_text(json.dumps(events[0]) + "\n")
    (journal / "ledger.jsonl").write_text(json.dumps(events[1]["event"]["record"]) + "\n")
    with pytest.raises(library.LibraryError, match="verified_external_outcome_required"):
        library.record_entry(tmp_path / "_library", item)


def test_directory_sync_failure_propagates_and_retry_resyncs_parent(tmp_path, monkeypatch):
    root = tmp_path / "_library"
    real_sync = library._sync_directory
    observed = []

    def failing(directory):
        observed.append(directory)
        raise OSError("synthetic fsync failure")

    with monkeypatch.context() as patch:
        patch.setattr(library, "_sync_directory", failing)
        with pytest.raises(OSError, match="fsync failure"):
            library.record_entry(root, entry())
    assert observed == [tmp_path]
    assert not list(root.rglob("*.json"))
    observed.clear()

    def recording(directory):
        observed.append(directory)
        real_sync(directory)

    monkeypatch.setattr(library, "_sync_directory", recording)
    library.record_entry(root, entry())
    assert observed == [tmp_path, root, root / "mechanism"]
    assert len(select(root)) == 1


def test_missing_library_read_is_pure_and_selection_is_bounded(tmp_path):
    missing = tmp_path / "missing"
    assert select(missing) == []
    assert not missing.exists()
    for kind in library.KINDS:
        library.record_entry(tmp_path, entry(kind))
    assert len(select(tmp_path, limit=2)) == 2
    assert [r["kind"] for r in select(tmp_path, kinds=["actor"])] == ["actor"]
    assert select(tmp_path, node_terms=["unrelated"]) == []
    assert select(tmp_path, limit=0) == []
    for changes in ({"limit": True}, {"limit": -1}, {"limit": 101}, {"node_terms": "growth"}, {"kinds": ["../actor"]}):
        with pytest.raises(library.LibraryError):
            select(tmp_path, **changes)


def test_case_producer_then_actual_second_case_selects_source_aware_mechanism(tmp_path):
    first = case_fixture()
    before = deepcopy(first)
    receipt = library.publish_case_mechanisms(tmp_path, first)
    assert first == before
    assert receipt["caseHash"] == bridge_module("forecast_case").case_hash(first)
    assert receipt["entries"] and receipt["skips"] == [{"mechanismId": "growth-sum", "reason": "private_node"}]
    second = deepcopy(first)
    second["caseId"] = "second-related-spending-case"
    second["asOf"] = "2026-10-28"
    second = bridge_module("forecast_case").validate_case(second)
    rows = library.select_entries(tmp_path, as_of=second["asOf"], node_terms=["spending"])
    assert {r["entryId"] for r in rows} == {r["entryId"] for r in receipt["entries"]}
    assert rows[0]["sources"] == first["sources"]
    assert rows[0]["provenance"]["caseId"] == first["caseId"]
    assert rows[0]["content"]["parameters"] == first["mechanisms"][1]["parameters"]
    assert "value" not in rows[0]["content"]["outputNode"]
    assert all(r["kind"] == "mechanism" for r in rows)
    assert library.publish_case_mechanisms(tmp_path, first) == receipt
    assert library.select_entries(tmp_path, as_of="2026-10-26", node_terms=["spending"]) == []


def test_producer_preserves_assumptions_and_skips_unsourced_rows(tmp_path):
    case = case_fixture()
    # Visibility is intentionally changed in this synthetic case so both source paths are exercised.
    case["nodes"][4]["visibility"] = "public"
    receipt = library.publish_case_mechanisms(tmp_path, case)
    assert len(receipt["entries"]) == 2
    rows = library.select_entries(tmp_path, as_of=case["asOf"], node_terms=["growth"])
    assumed = next(r for r in rows if r["provenance"]["recordId"] == "growth-sum")
    assert assumed["provenance"]["basis"] == "assumed"
    assert "journalProof" not in assumed["provenance"]
    assert assumed["content"]["parameters"] == case["mechanisms"][0]["parameters"]
    assert case["mechanisms"][0]["gap"] in assumed["gaps"]
    assert any("do not validate" in gap for gap in assumed["gaps"])
    assert "no hindcast or outcome validation is asserted" in assumed["uncertainty"]
    # Retain a valid case but make all its source records unfetched and its settled node contested.
    case["sources"][0]["fetched"] = False
    case["nodes"][0]["status"] = "contested"
    case["claims"][0]["status"] = "reported"
    empty = library.publish_case_mechanisms(tmp_path / "unsourced", case)
    assert empty["entries"] == []
    assert {r["reason"] for r in empty["skips"]} == {"no_fetched_source_evidence"}
    assert not (tmp_path / "unsourced").exists()


def test_invalid_case_producer_writes_nothing(tmp_path):
    case = case_fixture()
    case["mechanisms"][0]["sourceIds"] = ["S999"]
    with pytest.raises(ValueError):
        library.publish_case_mechanisms(tmp_path, case)
    assert list(tmp_path.iterdir()) == []


def test_producer_preserves_parameter_vectors_and_individual_bases(tmp_path):
    case = case_fixture()
    case["nodes"][4]["visibility"] = "public"
    mechanism = case["mechanisms"][0]
    mechanism.update(kind="linear", parameters={"coefficients": [1, 1, 1, 1],
                                                "intercept": {"low": 0, "high": 0.01, "basis": "assumed",
                                                              "gap": "Interaction contribution is unknown."}})
    case["mechanisms"][1]["basis"] = "estimated"
    receipt = library.publish_case_mechanisms(tmp_path, case)
    assert len(receipt["entries"]) == 2
    rows = library.select_entries(tmp_path, as_of=case["asOf"], node_terms=["growth"])
    by_record = {r["provenance"]["recordId"]: r for r in rows}
    assert by_record["growth-sum"]["content"]["parameters"] == mechanism["parameters"]
    assert by_record["spending-growth"]["provenance"]["basis"] == "estimated"


def test_producer_retains_parameter_and_output_only_source_associations(tmp_path):
    case = case_fixture()
    case["nodes"][4]["visibility"] = "public"
    case["sources"].append(dict(case["sources"][0], sourceId="S2", title="Parameter evidence", publishedAt=None))
    case["nodes"][5].update(sourceIds=["S2"], vintage="2026-10-26")
    mechanism = case["mechanisms"][0]
    mechanism.update(kind="linear", parameters={"coefficients": [1, 1, 1, 1],
                                                "intercept": {"low": 0, "high": 0.01, "basis": "estimated",
                                                              "sourceIds": ["S2"]}})
    receipt = library.publish_case_mechanisms(tmp_path, case)
    assert len(receipt["entries"]) == 2 and receipt["skips"] == []
    rows = library.select_entries(tmp_path, as_of=case["asOf"], node_terms=["growth"])
    row = next(r for r in rows if r["provenance"]["recordId"] == "growth-sum")
    assert row["content"]["parameters"] == mechanism["parameters"]
    assert row["content"]["outputNode"]["sourceIds"] == ["S2"]
    assert row["sources"] == case["sources"]
    assert any("Publication date unknown for S2" in gap for gap in row["gaps"])
