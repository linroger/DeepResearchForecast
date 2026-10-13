"""Real sealed actor packs → canonical public selector/world brief denial checks."""
from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import unicodedata

import pytest

from app.config import Config
from app.services import actor_context as ac
from app.services import simulation_config_generator as scg
from test_actor_context_runtime import REPORT, _dossier
from test_actor_roster_producer_consumer import produce_bundle as _producer_bundle_fixture
from test_pipeline_actor_contract import dr  # noqa: F401

produce_bundle = _producer_bundle_fixture  # pytest fixture injection name


@pytest.fixture(autouse=True)
def _bind_reviewed_sources():
    guard = sys.modules.get("main_offline_guard")
    if guard:
        base = Path(__file__).resolve().parents[2]
        for relative in (
            "backend/app/services/simulation_config_generator.py",
            "backend/app/services/actor_context.py",
            "backend/app/services/actor_role_prompt.py",
            "backend/app/services/pipeline_orchestrator.py",
            "backend/app/utils/actors.py",
            "backend/tests/test_actor_context_runtime.py",
            "backend/tests/test_actor_roster_producer_consumer.py",
            "backend/tests/test_pipeline_actor_contract.py",
            "deerflow_bridge/deerflow_research.py",
        ):
            path = base / relative
            # Preserve the first observed hash so later cases cannot hide drift.
            guard.source_hashes.setdefault(str(path), hashlib.sha256(path.read_bytes()).hexdigest())


def _claim(text, *, identity="", denial=None, visibility="public"):
    row = {"claim": text, "evidence_type": "verified_fact", "as_of_date": "2026-07-01",
           "source_refs": ["src_knowledg"], "visibility": visibility}
    if identity:
        row["claim_id"] = identity
    if denial == "top":
        row["actor_knows"] = False
        row["qualifiers"] = {"actor_knows": True}
    elif denial == "qualifier":
        row["actor_knows"] = True
        row["qualifiers"] = {"actor_knows": False}
    return row


def _packs(tmp_path, first, second=()):
    dossier = _dossier()
    for actor, rows in zip(dossier["actors"], (first, second), strict=True):
        # Keep real coverage for every dimension, changing only knowledge rows.
        actor["intelligence"]["dimensions"]["knowledge_state"] = list(rows) or [
            _claim("Private supporting baseline", visibility="private")]
    return dossier, _produce_and_validate(tmp_path, dossier, REPORT)


def _produce_and_validate(tmp_path, dossier, report):
    directory = tmp_path / "context"
    actors = dossier["actors"]
    packs, manifest, seal = ac.build_actor_context_artifacts(str(directory), dossier, actors, report)
    verified, loaded = ac.validate_actor_context_artifacts(
        str(directory), expected_count=len(actors), expected_manifest_sha256=seal,
        expected_report_sha256=ac.text_sha256(report),
        expected_actors_sha256=ac.canonical_json_sha256(dossier),
        expected_actor_ids=[ac.actor_id_for(actor) for actor in actors])
    assert verified == manifest and loaded == packs
    for actor in actors:
        pack = loaded[ac.actor_id_for(actor)]
        assert pack["source"]["actors_sha256"] == ac.canonical_json_sha256(dossier)
        assert pack["source"]["sources_sha256"] == dossier["actor_intelligence_contract"]["sources_sha256"]
        assert pack["actor_intelligence"] == actor["intelligence"]
    return loaded


def _shared(dossier, packs, monkeypatch):
    gen = object.__new__(scg.SimulationConfigGenerator)
    monkeypatch.setattr(Config, "SIM_WORLD_BRIEF", True)
    monkeypatch.setattr(gen, "_world_brief_max_chars", lambda: 20000)
    monkeypatch.setattr(gen, "_english_output", lambda: True)
    rows = gen._canonical_public_world_rows(dossier, packs)
    # Actual routing and canonical public builder remain production methods.
    brief = gen._build_world_brief("Question", dossier, [], actor_context_packs=packs)
    context = gen._build_context("Question", "UNBOUND REPORT", [], dossier, packs)
    assert "UNBOUND REPORT" not in context
    return rows, brief, context


@pytest.mark.parametrize("denial", ["top", "qualifier"])
def test_explicit_false_overrides_public_and_opposite_true(tmp_path, monkeypatch, denial):
    dossier, packs = _packs(tmp_path, [_claim("DENIED_MARKER", denial=denial), _claim("ALLOWED_PUBLIC")])
    rows, brief, context = _shared(dossier, packs, monkeypatch)
    assert [row["claim"] for row in rows] == ["ALLOWED_PUBLIC"]
    assert "DENIED_MARKER" not in brief + context
    assert "ALLOWED_PUBLIC" in brief and "ALLOWED_PUBLIC" in context


@pytest.mark.parametrize("denial", ["top", "qualifier"])
@pytest.mark.parametrize("match", ["identity", "text", "normalized_text", "identity_text_chain"])
@pytest.mark.parametrize("deny_first", [False, True])
def test_denial_blocks_duplicates_across_admitted_packs(tmp_path, monkeypatch, denial, match, deny_first):
    denied = _claim("Secret Permit VALUE", identity="claim_shared", denial=denial, visibility="private")
    if match == "identity":
        allowed = [_claim("Alternate rendering", identity="claim_shared")]
    elif match == "text":
        allowed = [_claim("Secret Permit VALUE", identity="claim_other")]
    elif match == "normalized_text":
        allowed = [_claim("  ＳＥＣＲＥＴ\tpermit\nvalue  ", identity="claim_other")]
    else:
        allowed = [_claim("Alias rendering", identity="claim_shared"),
                   _claim("  ALIAS  RENDERING ", identity="claim_other")]
    allowed.append(_claim("ALLOWED_PUBLIC", identity="claim_allowed"))
    first, second = ([denied], allowed) if deny_first else (allowed, [denied])
    dossier, packs = _packs(tmp_path, first, second)
    rows, brief, context = _shared(dossier, packs, monkeypatch)
    assert [row["claim"] for row in rows] == ["ALLOWED_PUBLIC"]
    assert "ALLOWED_PUBLIC" in brief and "ALLOWED_PUBLIC" in context
    def normalized(text):
        return " ".join(unicodedata.normalize("NFKC", text).casefold().split())
    for raw in [denied, *allowed[:-1]]:
        assert normalized(raw["claim"]) not in normalized(brief)
        assert normalized(raw["claim"]) not in normalized(context)


def test_full_text_denial_matching_precedes_display_truncation(tmp_path, monkeypatch):
    prefix = "Common extended evidence detail " * 20
    dossier, packs = _packs(tmp_path,
        [_claim(prefix + "denied tail", denial="top")],
        [_claim(prefix + "allowed distinct tail")])
    rows, brief, context = _shared(dossier, packs, monkeypatch)
    # Distinct full claims sharing the 520-char display prefix are not aliases.
    assert len(rows) == 1 and rows[0]["actor_name"] == "Beta Union"
    assert "Beta Union" in brief and "Beta Union" in context


@pytest.mark.parametrize("flag", [None, True, "false", 0])
def test_only_literal_json_false_denies_public_evidence(tmp_path, monkeypatch, flag):
    allowed = _claim("ALLOWED_PUBLIC")
    allowed["actor_knows"] = flag
    dossier, packs = _packs(tmp_path, [allowed])
    rows, brief, context = _shared(dossier, packs, monkeypatch)
    assert [row["claim"] for row in rows] == ["ALLOWED_PUBLIC"]
    assert "ALLOWED_PUBLIC" in brief and "ALLOWED_PUBLIC" in context


@pytest.mark.parametrize("tamper", ["intelligence", "dossier_binding"])
def test_invalid_pack_cannot_contribute_a_denial(tmp_path, monkeypatch, tamper):
    dossier, packs = _packs(tmp_path, [_claim("ALLOWED_PUBLIC")], [_claim("ALLOWED_PUBLIC", denial="top")])
    pack = packs[ac.actor_id_for(dossier["actors"][1])]
    if tamper == "intelligence":
        pack["actor_intelligence"]["dimensions"]["knowledge_state"][0]["claim"] = "tampered"
    else:
        pack["source"]["actors_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="mismatch"):
        _shared(dossier, packs, monkeypatch)


def test_missing_unadmitted_pack_cannot_veto_public_claim(tmp_path, monkeypatch):
    dossier, packs = _packs(tmp_path, [_claim("ALLOWED_PUBLIC")], [_claim("ALLOWED_PUBLIC", denial="top")])
    del packs[ac.actor_id_for(dossier["actors"][1])]
    rows, brief, _ = _shared(dossier, packs, monkeypatch)
    assert [row["claim"] for row in rows] == ["ALLOWED_PUBLIC"]
    assert "ALLOWED_PUBLIC" in brief


def test_bridge_finalizer_to_validated_pack_to_shared_brief(produce_bundle, tmp_path, monkeypatch):
    import test_pipeline_actor_contract as producer
    original = producer._producer_raw_claim
    def with_access(name, dimension):
        claim = original(name, dimension)
        if dimension == "knowledge_state":
            claim["qualifiers"] = {"visibility": "public", "actor_knows": False}
        elif dimension == "current_actions":
            claim["qualifiers"] = {"visibility": "public"}
        return claim
    # Plan A's ledger and Plan B's extraction must have the same projection.
    monkeypatch.setattr(producer, "_producer_raw_claim", with_access)
    bundle = produce_bundle()
    dossier = bundle["actors"]
    packs = _produce_and_validate(tmp_path, dossier, bundle["report"])
    for actor in dossier["actors"]:
        assert actor["intelligence"]["dimensions"]["knowledge_state"][0]["qualifiers"]["actor_knows"] is False
    rows, brief, context = _shared(dossier, packs, monkeypatch)
    assert len(rows) == 2
    assert all(row["dimension"] == "current_actions" for row in rows)
    assert "knowledge_state evidence" not in brief + context
    assert "current_actions evidence" in brief and "current_actions evidence" in context


@pytest.mark.parametrize("public", [True, False])
def test_official_statistics_join_the_canonical_brief_without_reopening_denials(tmp_path, monkeypatch, public):
    """G1: canonical v1 simulations receive the binding-verified official snapshot as
    its own delimited block (even with no public actor rows); denied and private
    claims stay out and the hash-bound packs are unchanged."""
    from app.services import official_data
    from official_data_replay import publish, replay
    rows = [_claim("DENIED_MARKER", denial="top"), _claim("PRIVATE_MARKER", visibility="private")]
    if public:
        rows.append(_claim("ALLOWED_PUBLIC"))
    dossier = _dossier()
    # The run's as-of follows the official retrieval (2026-10-11), so no look-ahead cutoff applies.
    dossier["as_of_date"] = "2026-10-12"
    dossier["actors"][0]["intelligence"]["dimensions"]["knowledge_state"] = rows
    dossier["actors"][1]["intelligence"]["dimensions"]["knowledge_state"] = [
        _claim("Private supporting baseline", visibility="private")]
    packs = _produce_and_validate(tmp_path, dossier, REPORT)
    carrier = official_data.load_official_data(publish([replay("fred_unrate_2024", tmp_path)], tmp_path / "handoff"))
    gen = object.__new__(scg.SimulationConfigGenerator)
    monkeypatch.setattr(Config, "SIM_WORLD_BRIEF", True)
    monkeypatch.setattr(gen, "_world_brief_max_chars", lambda: 3000)
    monkeypatch.setattr(gen, "_english_output", lambda: True)
    sealed = {key: dict(pack) for key, pack in packs.items()}
    brief = gen._build_world_brief("Question", dossier, [], actor_context_packs=packs, official_data=carrier)
    assert packs == sealed
    assert ("ALLOWED_PUBLIC" in brief) is public
    assert "DENIED_MARKER" not in brief and "PRIVATE_MARKER" not in brief
    assert "Unemployment Rate — United States | 4.1% | 2024-12 |" in brief and "[S1]" in brief
    assert brief.endswith("END UNTRUSTED RESEARCH DATA — official public historical statistics")
    without = gen._build_world_brief("Question", dossier, [], actor_context_packs=packs)
    assert ("ALLOWED_PUBLIC" in without) is public and "Official historical data" not in without
    if not public:
        assert without == ""  # unchanged fail-closed result without official data


@pytest.mark.parametrize("english", [True, False])
def test_official_snapshot_room_never_cuts_a_canonical_evidence_line(tmp_path, monkeypatch, english):
    """Sharing the brief with the official snapshot drops whole canonical evidence lines,
    never part of one: every shared row keeps its uncertainty label and its source binding
    (a cut line read 'CLAIM … word37…' with neither), exactly as the whole-line selection
    without official data does."""
    from app.services import official_data
    from official_data_replay import publish, replay
    names = ("fred_unrate_2024", "fred_dgs10_daily", "fred_dfedtaru_daily_step", "wb_wdi_gdp_growth_usa",
             "bis_ws_tc_us_770", "usgov_debt_to_penny_daily", "usgov_mts_deficit_2024")
    carrier = official_data.load_official_data(
        publish([replay(name, tmp_path) for name in names], tmp_path / "handoff"))
    filler = " ".join(f"word{index}" for index in range(60))[:300]
    rows = []
    for index in range(6):
        row = _claim(f"CLAIM{index} {filler}")
        row["evidence_type"] = "contested"
        rows.append(row)
    dossier = _dossier()
    dossier["as_of_date"] = "2026-10-12"
    dossier["actors"][0]["intelligence"]["dimensions"]["knowledge_state"] = rows
    dossier["actors"][1]["intelligence"]["dimensions"]["knowledge_state"] = [
        _claim("Private supporting baseline", visibility="private")]
    packs = _produce_and_validate(tmp_path, dossier, REPORT)
    gen = object.__new__(scg.SimulationConfigGenerator)
    monkeypatch.setattr(Config, "SIM_WORLD_BRIEF", True)
    monkeypatch.setattr(gen, "_world_brief_max_chars", lambda: 1400)
    monkeypatch.setattr(gen, "_english_output", lambda: english)
    question = "Will US unemployment exceed 5% in 2027?"
    brief = gen._build_world_brief(question, dossier, [], actor_context_packs=packs, official_data=carrier)
    alone = gen._build_world_brief(question, dossier, [], actor_context_packs=packs)
    assert len(brief) <= 1400 and "END UNTRUSTED RESEARCH DATA — official public historical statistics" in brief
    shared = [line for line in brief.splitlines() if "CLAIM" in line]
    assert shared, "some public evidence still shares the brief with the snapshot"
    assert set(shared) <= {line for line in alone.splitlines() if "CLAIM" in line}
    assert all("[contested; not established fact] [sources=" in line and line.endswith("]") for line in shared)
