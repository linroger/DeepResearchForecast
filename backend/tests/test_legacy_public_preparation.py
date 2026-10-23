"""Default report-only actors: real persona request, output and reload contract."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

import pytest

from app.services import actor_context as ac
from app.services import actor_role_prompt as role
from app.services.oasis_profile_generator import OasisProfileGenerator
from app.services.research_preparation import compile_preparation_context, write_preparation_context
from app.services.zep_entity_reader import EntityNode
from test_actor_role_prompt import ACTOR_A, DOSSIER, _generator


@pytest.fixture(autouse=True)
def record_sources():
    guard = sys.modules.get("main_offline_guard")
    if guard:
        for name in ("actor_context", "actor_role_prompt", "oasis_profile_generator", "research_preparation"):
            path = Path(__file__).resolve().parents[1] / "app/services" / (name + ".py")
            guard.source_hashes.setdefault(str(path), hashlib.sha256(path.read_bytes()).hexdigest())


class CaptureLLM:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def chat(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        if self.fail:
            raise RuntimeError("scripted provider failure")
        return json.dumps({"bio": "Grid investor", "persona": "Generated legacy qualitative persona."})


def fixture(tmp_path, *, oversized=False):
    dossier = deepcopy(DOSSIER)
    actor = dossier["actors"][0]
    actor["actor_id"] = "legacy_northstar"
    # Private quantities exist only in the preparation sidecar, never in the
    # established qualitative input being preserved by this compatibility path.
    facts = [
        {"metric": "PUBLIC_CAPACITY_BASELINE", "entity": actor["name"], "value": 12.75,
         "unit": "GW", "as_of_date": "2026-06-30", "period_end": "2026-06-30",
         "value_type": "observed", "visibility": "public", "source_refs": ["PUBLIC-SOURCE-1"]},
        {"metric": "PRIVATE_NUMERIC_SENTINEL", "actor_id": "legacy_northstar", "value": 91,
         "unit": "USD billion", "as_of_date": "2026-06-30", "period_end": "2026-06-30",
         "value_type": "observed", "visibility": "actor_known", "actor_knows": True,
         "source_refs": ["PRIVATE-SOURCE-1"]},
    ]
    if oversized:
        facts[0]["conditions"] = ["COMPLETE_CONDITION " + "detail " * 400]
    report = "# Northstar Energy\nNorthstar Energy pursues its documented grid plan."
    packs, manifest, sha = ac.build_actor_context_artifacts(str(tmp_path), dossier, dossier["actors"], report)
    bundle = compile_preparation_context(question="PUBLIC_CAPACITY_BASELINE outlook", research_report=report,
        actors=dossier, actor_context_packs=packs, report_artifacts={"quantitative.json": facts})
    gen = _generator()
    gen._build_entity_context = lambda _: "dense graph material " * 1000
    gen._print_generated_profile = lambda *_: None
    gen.actor_context_packs = packs
    gen.actor_context_bindings = ac.context_binding_by_actor_id(manifest)
    gen.actor_context_manifest_sha256 = sha
    gen.actor_context_report_sha256 = ac.text_sha256(report)
    gen.llm = CaptureLLM()
    entity = EntityNode(uuid="northstar", name=actor["name"], labels=["Organization"],
                        summary="Grid investor", attributes={})
    return dossier, actor, packs, bundle, gen, entity


def generate(data, *, use_llm=True, preparation=True):
    dossier, actor, packs, bundle, gen, entity = data
    return gen.generate_profile_from_entity(entity, 0, use_llm=use_llm, actor=actor, actors=dossier,
        context_pack=packs[ac.actor_id_for(actor)], preparation_context=bundle if preparation else None,
        actor_context_packs=packs)


def test_legacy_actual_request_and_platform_fields_include_public_baseline(tmp_path):
    data = fixture(tmp_path)
    profile = generate(data)
    _, _, _, bundle, gen, _ = data
    assert gen.llm.calls
    request = gen.llm.calls[0]["messages"][1]["content"]
    for text in (request, profile.to_reddit_format()["persona"], profile.to_twitter_format()["persona"]):
        for expected in ("PUBLIC_CAPACITY_BASELINE", "12.75", "GW", "2026-06-30", "observed", "PUBLIC-SOURCE-1"):
            assert expected in text
        assert "PRIVATE_NUMERIC_SENTINEL" not in text
        assert "PRIVATE-SOURCE-1" not in text
        assert "Retain generation share" in text
    assert profile.role_contract["preparation_extension_version"] == "legacy-public-preparation/v1"
    assert "admission_policy_version" not in profile.role_contract
    assert profile.role_contract["preparation_context"]["audience"] == "public"
    assert profile.role_contract["preparation_context"]["content_sha256"] == bundle["content_sha256"]
    block = role.legacy_public_preparation_block(profile.role_contract)
    assert request.endswith(block)
    assert len(block) <= 1200
    generate(data, preparation=False)
    plain_request = gen.llm.calls[-1]["messages"][1]["content"]
    assert request == plain_request + "\n\n" + block
    assert len(request) - len(plain_request) <= 1202


@pytest.mark.parametrize("mode", ["rule", "llm_failure", "stub"])
def test_legacy_fallbacks_keep_identical_extension(tmp_path, monkeypatch, mode):
    data = fixture(tmp_path)
    expected = generate(data, use_llm=False)
    dossier, actor, packs, bundle, gen, entity = data
    if mode == "llm_failure":
        gen.llm = CaptureLLM(fail=True)
        monkeypatch.setattr("time.sleep", lambda _: None)
        profile = generate(data)
        assert profile.generation_path == "rule_fallback"
    elif mode == "stub":
        profile = gen._error_stub_profile(entity, 0, actor, dossier, packs[actor["actor_id"]],
                                         preparation_context=bundle, actor_context_packs=packs)
    else:
        profile = generate(data, use_llm=False)
    assert profile.role_prompt == expected.role_prompt
    assert "PUBLIC_CAPACITY_BASELINE" in profile.persona


def test_legacy_extension_reload_and_old_absent_extension_bytes(tmp_path):
    data = fixture(tmp_path)
    dossier, actor, packs, bundle, gen, entity = data
    # Profiles cover both selected context packs, as required by the existing seal.
    profiles = [generate(data)]
    other = dossier["actors"][1]
    other_entity = EntityNode(uuid="other", name=other["name"], labels=["Organization"], summary="Advocate", attributes={})
    profiles.append(gen.generate_profile_from_entity(other_entity, 1, use_llm=False, actor=other, actors=dossier,
        context_pack=packs[ac.actor_id_for(other)], preparation_context=bundle, actor_context_packs=packs))
    write_preparation_context(tmp_path, bundle)
    for platform, filename in (("reddit", "reddit_profiles.json"), ("twitter", "twitter_profiles.csv")):
        path = tmp_path / filename
        gen.save_profiles(profiles, str(path), platform=platform)
        before = path.read_bytes()
        manifest = gen.validate_role_prompt_manifest(str(path))
        assert manifest["roles"][0]["preparation_extension_version"] == "legacy-public-preparation/v1"
        assert path.read_bytes() == before
        changed = deepcopy(bundle)
        changed["scope"]["question"] = "changed"
        changed["source"]["question_sha256"] = ac.text_sha256("changed")
        changed["content_sha256"] = ac.canonical_json_sha256({k:v for k,v in changed.items() if k != "content_sha256"})
        with pytest.raises(ValueError, match="fingerprint|mismatch"):
            gen.validate_role_prompt_manifest(str(path), preparation_context=changed)
    (tmp_path / "research_preparation_manifest.json").unlink()
    with pytest.raises((ValueError, FileNotFoundError)):
        gen.validate_role_prompt_manifest(str(tmp_path / "reddit_profiles.json"))
    old = generate(data, use_llm=False, preparation=False)
    baseline = role._build_legacy_actor_role_contract(actor, dossier, packs[actor["actor_id"]])
    assert old.role_prompt == role.compile_actor_role_prompt(baseline)
    assert "preparation_extension_version" not in old.role_contract


def test_unmatched_extra_gets_no_fabricated_role(tmp_path):
    *_, bundle, gen, _entity = fixture(tmp_path)
    extra = EntityNode(uuid="extra", name="Unmatched Extra", labels=["Organization"], summary="Extra", attributes={})
    profile = gen.generate_profile_from_entity(extra, 9, use_llm=False, preparation_context=bundle)
    assert profile.role_contract is None
    assert "PUBLIC_CAPACITY_BASELINE" not in profile.persona


def test_legacy_small_role_budget_omits_extension_whole(tmp_path):
    profile = generate(fixture(tmp_path), use_llm=False)
    prompt = role.compile_actor_role_prompt(profile.role_contract, max_chars=1800)
    assert len(prompt) <= 1800
    assert "Northstar Energy" in prompt
    assert "Public preparation omitted" in prompt
    assert "PUBLIC_CAPACITY_BASELINE" not in prompt
    assert "END UNTRUSTED DOSSIER DATA" in prompt


def test_legacy_oversized_quantity_omitted_whole_from_actual_request(tmp_path):
    data = fixture(tmp_path, oversized=True)
    profile = generate(data)
    request = data[4].llm.calls[0]["messages"][1]["content"]
    for text in (request, profile.persona):
        # The forecast question may name the metric; the evidence row and its
        # native value/source must be omitted together with its long condition.
        assert '"metric":"PUBLIC_CAPACITY_BASELINE"' not in text
        assert "12.75" not in text
        assert "PUBLIC-SOURCE-1" not in text
        assert "COMPLETE_CONDITION" not in text
        assert "Omitted rows:" in text
    assert len(role.legacy_public_preparation_block(profile.role_contract)) <= 1200


def test_legacy_wrong_generation_fails_before_graph_or_model_request(tmp_path):
    data = fixture(tmp_path)
    dossier, actor, packs, bundle, gen, entity = data
    changed = deepcopy(bundle)
    changed["source"]["actors_sha256"] = "0" * 64
    changed["content_sha256"] = ac.canonical_json_sha256({k:v for k,v in changed.items() if k != "content_sha256"})
    gen._build_entity_context = lambda _: pytest.fail("unbound preparation reached graph retrieval")
    with pytest.raises(ValueError, match="generation|binding|mismatch"):
        gen.generate_profile_from_entity(entity, 0, use_llm=True, actor=actor, actors=dossier,
            context_pack=packs[actor["actor_id"]], actor_context_packs=packs, preparation_context=changed)
    assert gen.llm.calls == []


def test_legacy_missing_individual_pack_rejected_before_graph_or_model(tmp_path):
    dossier, actor, packs, bundle, gen, entity = fixture(tmp_path)
    gen._build_entity_context = lambda _: pytest.fail("missing actor pack reached graph retrieval")
    with pytest.raises(ValueError, match="context pack"):
        gen.generate_profile_from_entity(entity, 0, use_llm=True, actor=actor, actors=dossier,
            actor_context_packs=packs, preparation_context=bundle)
    assert gen.llm.calls == []
