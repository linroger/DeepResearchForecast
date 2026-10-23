"""Fail-closed OASIS persona boundary for actor-intelligence/v1.

These tests exercise the exact Reddit ``persona`` and Twitter ``user_char``
fields, not only the intermediate actor-role contract.  Canonical v1 actors
must never recover source-less legacy behavior through persona generation,
rule fallbacks, entity summaries, or later profile mutation.
"""

from __future__ import annotations

import csv
import json
import os
import sys

import pytest


_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from app.services.actor_role_prompt import build_actor_role_contract, _build_legacy_actor_role_contract  # noqa: E402
from app.services.oasis_profile_generator import (  # noqa: E402
    OasisProfileGenerator,
    canonical_reddit_system_message,
)
from app.services import actor_context as ac
from app.services.zep_entity_reader import EntityNode  # noqa: E402
from scripts.run_parallel_simulation import (  # noqa: E402
    _attest_canonical_reddit_system_messages,
    _enforce_canonical_reddit_system_messages,
    _inject_behavior_hint,
    _inject_calendar_vocabulary,
    _inject_world_brief,
)


FLAT_SENTINELS = (
    "UNBOUND FLAT DESCRIPTION",
    "UNBOUND FLAT ROLE",
    "UNBOUND FLAT STANCE",
    "UNBOUND FLAT GOAL",
    "UNBOUND FLAT RESOURCE",
    "UNBOUND FLAT MEMORY",
    "UNBOUND FLAT PLAN",
    "UNBOUND FLAT ACTION",
    "UNBOUND FLAT INVESTMENT",
    "UNBOUND FLAT LIKELY ACTION",
    "UNBOUND FLAT WORLDVIEW",
    "UNBOUND FLAT INCENTIVE",
    "UNBOUND DOSSIER SITUATION",
    "UNBOUND DOSSIER RELATIONSHIP",
    "UNBOUND ENTITY SUMMARY",
    "UNBOUND ENTITY ATTRIBUTE",
    "UNBOUND GRAPH CONTEXT",
)
CANONICAL_PLAN = "CANONICAL SOURCED PLAN: file a permit response in 2027."
CANONICAL_KNOWLEDGE = "CANONICAL SOURCED KNOWLEDGE: its own filing calendar."


def _actor() -> dict:
    return {
        "actor_id": "actor_grounded_boundary",
        "name": "Grounded Boundary Corp",
        "type": "Organization",
        "description": FLAT_SENTINELS[0],
        "role": FLAT_SENTINELS[1],
        "stance": FLAT_SENTINELS[2],
        "goals": [FLAT_SENTINELS[3]],
        "resources": [FLAT_SENTINELS[4]],
        "memory": FLAT_SENTINELS[5],
        "plans": [FLAT_SENTINELS[6]],
        "future_plans": [FLAT_SENTINELS[6]],
        "current_actions": [FLAT_SENTINELS[7]],
        "investments": [FLAT_SENTINELS[8]],
        "likely_actions": [FLAT_SENTINELS[9]],
        "worldview": {"beliefs": [FLAT_SENTINELS[10]]},
        "incentives": [{"driver": FLAT_SENTINELS[11]}],
        "intelligence": {
            "schema_version": "actor-intelligence/v1",
            "dimensions": {
                "future_plans": [{
                    "claim": CANONICAL_PLAN,
                    "visibility": "public",
                    "evidence_type": "actor_stated_claim",
                    "as_of_date": "2026-07-01",
                    "confidence": "high",
                    "source_refs": ["src_canonical_plan"],
                }],
                "knowledge_state": [{
                    "claim": CANONICAL_KNOWLEDGE,
                    "evidence_type": "verified_fact",
                    "as_of_date": "2026-07-01",
                    "confidence": "high",
                    "source_refs": ["src_canonical_knowledge"],
                    "qualifiers": {"actor_knows": True},
                }],
            },
            "evidence_gaps": {
                "current_actions": ["No sourced current action survives."],
            },
        },
    }


def _dossier(actor: dict) -> dict:
    return {
        "actors": [actor],
        "situation_brief": {"current_situation": FLAT_SENTINELS[12]},
        "relationships": [{
            "source": actor["name"],
            "target": "Counterparty",
            "type": "ALLIED_WITH",
            "basis": FLAT_SENTINELS[13],
        }],
    }


def _entity() -> EntityNode:
    return EntityNode(
        uuid="entity-grounded-boundary",
        name="Grounded Boundary Corp",
        labels=["Entity", "Organization"],
        summary=FLAT_SENTINELS[14],
        attributes={"description": FLAT_SENTINELS[15]},
    )


def _generator() -> OasisProfileGenerator:
    generator = OasisProfileGenerator.__new__(OasisProfileGenerator)
    generator.persona_language = "en"
    return generator



def _seal(tmp_path, actor, generator):
    dossier = _dossier(actor)
    report = "# Grounded Boundary Corp\nGrounded Boundary Corp plans its permit response."
    gaps = actor["intelligence"]["evidence_gaps"]
    for dimension in ac.INTELLIGENCE_DIMENSIONS:
        if not actor["intelligence"]["dimensions"].get(dimension):
            gaps.setdefault(dimension, ["No sourced claim."])
    dossier["actor_intelligence_contract"] = {
        "schema_version": "actor-intelligence/v1", "generated_at": "2026-07-01",
        "report_sha256": ac.text_sha256(report), "dossier_sha256": ac.text_sha256("dossier"),
        "sources_sha256": ac.text_sha256("sources"),
        "actor_ids_sha256": ac.canonical_json_sha256({actor["actor_id"]: 1}),
        "actor_count": 1, "source_count": 2, "tier_1_2_actor_count": 1,
        "dimensions": list(ac.INTELLIGENCE_DIMENSIONS), "coverage": {},
    }
    packs, manifest, sha = ac.build_actor_context_artifacts(str(tmp_path), dossier, [actor], report)
    generator.actor_context_bindings = ac.context_binding_by_actor_id(manifest)
    generator.actor_context_manifest_sha256 = sha
    generator.actor_context_report_sha256 = ac.text_sha256(report)
    generator.actor_context_packs = packs
    return dossier, packs[actor["actor_id"]]

def _explode(*_args, **_kwargs):
    raise AssertionError("canonical v1 crossed a forbidden legacy persona path")


class _Message:
    def __init__(self, content: str):
        self.content = content

    def create_new_instance(self, content: str):
        return _Message(content)


class _Agent:
    def __init__(self):
        self._original_system_message = _Message("OASIS GENERATED DEFAULT")
        self._system_message = self._original_system_message

    def _generate_system_message_for_output_language(self):
        return self._original_system_message

    def init_messages(self):
        return None


class _AgentGraph:
    def __init__(self):
        self.agent = _Agent()

    def get_agents(self):
        return [(0, self.agent)]


@pytest.mark.parametrize("use_llm", [True, False])
def test_v1_bypasses_llm_graph_context_and_rule_persona_paths(use_llm, tmp_path):
    actor = _actor()
    generator = _generator()
    dossier, pack = _seal(tmp_path, actor, generator)
    generator._build_entity_context = _explode
    generator._generate_profile_with_llm = _explode
    generator._generate_profile_rule_based = _explode

    profile = generator.generate_profile_from_entity(
        entity=_entity(),
        user_id=7,
        use_llm=use_llm,
        actor=actor,
        actors=dossier,
        context_pack=pack,
    )

    assert profile.generation_path == "canonical_role"
    assert profile.persona == profile.role_prompt
    assert profile.persona == profile._canonical_role_only_persona()
    assert profile.persona_design is None
    assert profile.bio == "Organization: Grounded Boundary Corp"
    assert CANONICAL_PLAN in profile.persona
    assert CANONICAL_KNOWLEDGE in profile.persona
    serialized = json.dumps(profile.to_dict(), ensure_ascii=False)
    for sentinel in FLAT_SENTINELS:
        assert sentinel not in serialized


def test_v1_exact_platform_fields_are_role_only_and_resist_base_persona_mutation(
    tmp_path,
):
    actor = _actor()
    generator = _generator()
    dossier, pack = _seal(tmp_path, actor, generator)
    profile = generator.generate_profile_from_entity(
        entity=_entity(),
        user_id=0,
        use_llm=False,
        actor=actor,
        actors=dossier,
        context_pack=pack,
    )
    expected_role = profile.role_prompt
    profile.persona = "UNBOUND POST-GENERATION BASE PERSONA"

    reddit_path = str(tmp_path / "reddit_profiles.json")
    twitter_path = str(tmp_path / "twitter_profiles.csv")
    generator.save_profiles([profile], reddit_path, platform="reddit")
    generator.save_profiles([profile], twitter_path, platform="twitter")

    reddit = json.loads((tmp_path / "reddit_profiles.json").read_text())
    with open(twitter_path, encoding="utf-8") as handle:
        twitter = list(csv.DictReader(handle))
    assert reddit[0]["persona"] == expected_role
    assert reddit[0]["age"] == ""
    assert reddit[0]["gender"] == ""
    assert reddit[0]["mbti"] == ""
    assert reddit[0]["country"] == ""
    assert twitter[0]["user_char"] == expected_role.replace("\n", " ")
    assert profile.bio not in twitter[0]["user_char"]
    assert "UNBOUND POST-GENERATION" not in reddit[0]["persona"]
    assert "UNBOUND POST-GENERATION" not in twitter[0]["user_char"]
    assert CANONICAL_PLAN in reddit[0]["persona"]
    assert CANONICAL_PLAN in twitter[0]["user_char"]
    system_message = canonical_reddit_system_message(
        reddit[0]["username"], reddit[0]["persona"]
    )
    assert "years old, with an MBTI personality type" not in system_message
    reddit_manifest = generator.validate_role_prompt_manifest(reddit_path)
    [role_row] = reddit_manifest["roles"]
    assert role_row["reddit_base_system_message_chars"] == len(system_message)


def test_v1_rule_fallback_stub_is_still_exactly_the_canonical_role(tmp_path):
    actor = _actor()
    generator = _generator()
    dossier, pack = _seal(tmp_path, actor, generator)
    profile = generator._error_stub_profile(
        entity=_entity(),
        user_id=0,
        actor=actor,
        actors=dossier,
        context_pack=pack,
    )

    assert profile.generation_path == "error_stub"
    assert profile.persona == profile.role_prompt
    assert CANONICAL_PLAN in profile.persona
    for sentinel in FLAT_SENTINELS:
        assert sentinel not in profile.persona


def test_v1_reddit_final_effective_system_message_is_exactly_attested(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("SIM_WORLD_BRIEF", "true")
    actor = _actor()
    generator = _generator()
    dossier, pack = _seal(tmp_path, actor, generator)
    profile = generator.generate_profile_from_entity(
        entity=_entity(),
        user_id=0,
        use_llm=False,
        actor=actor,
        actors=dossier,
        context_pack=pack,
    )
    profile_path = str(tmp_path / "reddit_profiles.json")
    generator.save_profiles([profile], profile_path, platform="reddit")
    graph = _AgentGraph()

    runtime_rows = _enforce_canonical_reddit_system_messages(
        graph, profile_path
    )
    config = {
        "world_brief": "SEALED PUBLIC WORLD BRIEF",
        "temporal_config": {"mode": "calendar", "unit": "month"},
    }
    _inject_world_brief(graph, config["world_brief"], lambda _message: None)
    _inject_calendar_vocabulary(
        graph, config["temporal_config"], lambda _message: None
    )
    _attest_canonical_reddit_system_messages(
        graph,
        profile_path,
        config,
        runtime_rows,
        "a" * 64,
    )

    attestation = json.loads(
        (tmp_path / "reddit_runtime_system_messages.json").read_text(
            encoding="utf-8"
        )
    )
    assert attestation["actor_count"] == 1
    assert attestation["simulation_config_manifest_sha256"] == "a" * 64
    actual = graph.agent._original_system_message.content
    assert "SEALED PUBLIC WORLD BRIEF" in actual
    assert "one calendar month" in actual
    assert "years old, with an MBTI personality type" not in actual

    assert _inject_behavior_hint(graph.agent, "UNSEALED BEHAVIOR SUFFIX")
    with pytest.raises(ValueError, match="differs from sealed composition"):
        _attest_canonical_reddit_system_messages(
            graph,
            profile_path,
            config,
            runtime_rows,
            "a" * 64,
        )


def test_v1_direct_legacy_helpers_fail_closed():
    actor = _actor()
    generator = _generator()

    with pytest.raises(ValueError, match="deterministic role-only"):
        generator._generate_profile_with_llm(
            entity_name=actor["name"],
            entity_type="Organization",
            entity_summary=FLAT_SENTINELS[14],
            entity_attributes={"description": FLAT_SENTINELS[15]},
            context=FLAT_SENTINELS[16],
            actor=actor,
            actors=_dossier(actor),
        )
    with pytest.raises(ValueError, match="deterministic role-only"):
        generator._generate_profile_rule_based(
            entity_name=actor["name"],
            entity_type="Organization",
            entity_summary=FLAT_SENTINELS[14],
            entity_attributes={"description": FLAT_SENTINELS[15]},
            actor=actor,
            actors=_dossier(actor),
        )
    assert generator._design_from_actor(
        actor,
        actor["name"],
        actors=_dossier(actor),
    ) is None


def test_legacy_v2_role_promotes_only_public_hard_relationships_with_epistemics():
    actor = _actor()
    public = {
        "source": actor["name"],
        "target": "Public Counterparty",
        "type": "PARTNERS_WITH",
        "basis": "PUBLIC VERIFIED RELATIONSHIP",
        "evidence_type": "verified_fact",
        "visibility": "public",
        "actor_knows": True,
        "source_refs": ["src_public_relation"],
    }
    private = {
        **public,
        "target": "Private Counterparty",
        "basis": "PRIVATE RELATIONSHIP SENTINEL",
        "visibility": "actor_internal",
        "source_refs": ["src_private_relation"],
    }
    model_only = {
        **public,
        "target": "Model Counterparty",
        "basis": "MODEL RELATIONSHIP SENTINEL",
        "evidence_type": "analyst_inference",
        "source_refs": ["src_model_relation"],
    }
    actor["intelligence"]["dimensions"]["alliances"] = [
        {
            "claim": "PUBLIC ALLIANCE CLAIM",
            "evidence_type": "actor_stated_claim",
            "visibility": "public_record",
            "source_refs": ["src_public_alliance"],
        },
        {
            "claim": "PRIVATE ALLIANCE SENTINEL",
            "evidence_type": "verified_fact",
            "visibility": "private_actor_knowledge",
            "source_refs": ["src_private_alliance"],
        },
    ]
    context_pack = {
        "schema_version": "actor-context/v1",
        "actor_id": actor["actor_id"],
        "actor_name": actor["name"],
        "source": {
            "actor_intelligence_contract_version": "actor-intelligence/v1",
        },
        "relationships": [public, private, model_only],
    }

    contract = _build_legacy_actor_role_contract(
        actor, _dossier(actor), context_pack=context_pack
    )
    relationships = contract["relationships"]
    serialized = json.dumps(relationships, ensure_ascii=False)

    assert "Public Counterparty" in serialized
    assert "PUBLIC VERIFIED RELATIONSHIP" in serialized
    assert "PUBLIC ALLIANCE CLAIM" in serialized
    assert "verified_fact" in serialized
    assert "public" in serialized
    assert "src_public_relation" in serialized
    assert "PRIVATE RELATIONSHIP SENTINEL" not in serialized
    assert "MODEL RELATIONSHIP SENTINEL" not in serialized
    assert "PRIVATE ALLIANCE SENTINEL" not in serialized


def test_explicit_unknown_intelligence_schema_cannot_downgrade_to_legacy():
    actor = _actor()
    actor["intelligence"] = {
        "schema_version": "actor-intelligence/v2",
        "dimensions": {},
    }
    dossier = _dossier(actor)
    generator = _generator()
    generator._build_entity_context = _explode
    generator._generate_profile_with_llm = _explode
    generator._generate_profile_rule_based = _explode

    # The contract compiler itself must not reinterpret a future schema as a
    # pre-versioned actor, even if legacy flat behavior is still present.
    assert build_actor_role_contract(actor, dossier) is None
    with pytest.raises(ValueError, match="unsupported actor intelligence schema"):
        generator.generate_profile_from_entity(
            entity=_entity(),
            user_id=0,
            use_llm=True,
            actor=actor,
            actors=dossier,
        )
    with pytest.raises(ValueError, match="unsupported actor intelligence schema"):
        generator._error_stub_profile(
            entity=_entity(),
            user_id=0,
            actor=actor,
            actors=dossier,
        )


def test_pre_v1_actor_keeps_legacy_persona_generation_contract():
    class LegacyLLM:
        def __init__(self):
            self.calls = 0

        def chat(self, **_kwargs):
            self.calls += 1
            return json.dumps({
                "bio": "Legacy generated bio",
                "persona": "Legacy generated base persona",
            })

    actor = {
        "name": "Legacy Actor",
        "type": "Organization",
        "role": "Legacy documented role",
        "goals": ["Legacy documented goal"],
        "memory": "Legacy documented memory",
        # Early migration rows used the additive dictionary before a schema
        # marker existed; absence of an explicit version remains compatible.
        "intelligence": {"likely_actions": ["Legacy documented action"]},
    }
    generator = _generator()
    generator.llm = LegacyLLM()
    generator._build_entity_context = lambda _entity: ""
    entity = EntityNode(
        uuid="entity-legacy",
        name="Legacy Actor",
        labels=["Organization"],
        summary="Legacy summary",
        attributes={},
    )

    profile = generator.generate_profile_from_entity(
        entity=entity,
        user_id=0,
        use_llm=True,
        actor=actor,
        actors={"actors": [actor]},
    )

    assert generator.llm.calls == 1
    assert profile.generation_path == "llm"
    assert profile.persona.startswith("Legacy generated base persona")
    assert profile.persona.endswith(profile.role_prompt)
