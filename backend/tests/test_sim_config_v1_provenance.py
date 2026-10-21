"""Fail-closed actor-intelligence/v1 boundaries in simulation configuration.

These tests use contradictory legacy sentinels to prove that the canonical
actor-context/v1 projection is the only behavior authority for named v1
actors, decision-facing incentive fields, and shared runtime world knowledge.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import json

import pytest

from app.config import Config
from app.services.actor_context import (
    ACTOR_CONTEXT_VERSION,
    ACTOR_INTELLIGENCE_VERSION,
    canonical_json_sha256,
)
from app.services.decision_channel import _agent_meta_map
from app.services.simulation_config_generator import (
    ACTOR_CONFIG_EVIDENCE_GAP_AUDIT_KEY,
    AgentActivityConfig,
    SimulationConfigGenerator,
    TimeSimulationConfig,
)
from app.services.zep_entity_reader import EntityNode
from scripts.run_parallel_simulation import _inject_world_brief


FLAT_SENTINELS = (
    "FLAT ROLE SENTINEL",
    "FLAT SUPPORTIVE STANCE SENTINEL",
    "FLAT HIGH INFLUENCE SENTINEL",
    "FLAT MEMORY SENTINEL",
    "FLAT GAINS SENTINEL",
    "FLAT LOSSES SENTINEL",
)


def _claim(
    text: str,
    *,
    evidence_type: str = "verified_fact",
    visibility: str = "public",
    qualifiers: dict | None = None,
) -> dict:
    return {
        "claim": text,
        "evidence_type": evidence_type,
        "as_of_date": "2026-07-01",
        "confidence": "high",
        "source_refs": ["src_primary"],
        "visibility": visibility,
        "qualifiers": dict(qualifiers or {}),
    }


def _actor(actor_id: str, name: str, public_fact: str) -> dict:
    return {
        "actor_id": actor_id,
        "name": name,
        "type": "Organization",
        "role": FLAT_SENTINELS[0],
        "stance": FLAT_SENTINELS[1],
        "influence": FLAT_SENTINELS[2],
        "memory": FLAT_SENTINELS[3],
        "incentives": [{
            "gains_if": FLAT_SENTINELS[4],
            "loses_if": FLAT_SENTINELS[5],
        }],
        "intelligence": {
            "schema_version": ACTOR_INTELLIGENCE_VERSION,
            "dimensions": {
                "current_actions": [
                    _claim(public_fact, qualifiers={"project": f"{name} public project"})
                ],
                "future_plans": [
                    _claim(
                        f"{name} PRIVATE BOARD PLAN SENTINEL",
                        visibility="actor_internal",
                    )
                ],
                "motivations": [
                    _claim(
                        f"{name} MODEL ONLY INFERENCE SENTINEL",
                        evidence_type="analyst_inference",
                    )
                ],
                "incentives": [
                    _claim(
                        f"{name} source-bound incentive",
                        qualifiers={
                            "driver": "permit timing",
                            "gains_if": f"{name} CANONICAL GAINS",
                            "loses_if": f"{name} CANONICAL LOSSES",
                            "intensity": "high",
                        },
                    )
                ],
                "capabilities": [
                    _claim(f"{name} can deploy its documented operating team")
                ],
            },
            "evidence_gaps": {},
        },
    }


def _pack(
    actor: dict,
    *,
    dossier: dict | None = None,
    relationships: list[dict] | None = None,
    events: list[dict] | None = None,
) -> dict:
    intelligence = actor["intelligence"]
    intelligence_sha = canonical_json_sha256(intelligence)
    source = {
        "actor_intelligence_contract_version": ACTOR_INTELLIGENCE_VERSION,
        "actor_intelligence_sha256": intelligence_sha,
    }
    bound_dossier = dossier if dossier is not None else _dossier(actor)
    source["actors_sha256"] = canonical_json_sha256(bound_dossier)
    return {
        "schema_version": ACTOR_CONTEXT_VERSION,
        "actor_id": actor["actor_id"],
        "actor_name": actor["name"],
        "actor_intelligence": deepcopy(intelligence),
        "source": source,
        "relationships": deepcopy(relationships or []),
        "events": deepcopy(events or []),
        "relevant_sections": [],
    }


def _dossier(*actors: dict) -> dict:
    return {
        "actor_intelligence_contract": {
            "schema_version": ACTOR_INTELLIGENCE_VERSION,
        },
        "situation_brief": {
            "current_situation": "RAW SITUATION PRIVATE SENTINEL",
            "dynamics": "RAW MODEL INFERENCE SENTINEL",
        },
        "hot_topics": ["RAW HOT TOPIC SENTINEL"],
        "actors": list(actors),
    }


def _entity(name: str) -> EntityNode:
    return EntityNode(
        uuid=f"uuid:{name}",
        name=name,
        labels=["Entity", "Organization"],
        summary=f"Structural graph identity for {name}",
        attributes={},
    )


def _generator() -> SimulationConfigGenerator:
    generator = SimulationConfigGenerator.__new__(SimulationConfigGenerator)
    generator.provider = "offline"
    generator._profile_override = None
    generator._run_hot_topics = []
    generator._temporal_timeline = None
    generator._agent_batch_stats = {
        "llm_batches": 0,
        "rule_batches": 0,
        "rule_agents": 0,
    }
    return generator


def test_canonical_config_is_deterministic_and_never_calls_graph_routed_llm():
    actor = _actor("actor_alpha", "Alpha", "Alpha PUBLIC SHARED FACT")
    dossier = _dossier(actor)
    packs = {actor["actor_id"]: _pack(actor)}
    generator = _generator()
    generator._call_llm_with_retry = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("canonical per-agent config must not call an LLM")
    )
    [config] = generator._generate_agent_configs_batch(
        context="unused",
        entities=[_entity("Alpha")],
        start_idx=0,
        simulation_requirement="Will the permit be approved?",
        actors=dossier,
        actor_context_packs=packs,
    )

    serialized = str(asdict(config))
    for sentinel in FLAT_SENTINELS:
        assert sentinel not in serialized
    assert config.stance == "neutral"
    assert config.influence_weight == 1.0
    assert config.entity_type == "Actor"
    assert "Alpha PUBLIC SHARED FACT" in config.actor_context_digest
    assert config.gains_if == "Alpha CANONICAL GAINS"
    assert config.loses_if == "Alpha CANONICAL LOSSES"

    roster = _agent_meta_map([asdict(config)])[0]
    assert roster["stance"] == "neutral"
    assert roster["gains_if"] == "Alpha CANONICAL GAINS"
    assert roster["loses_if"] == "Alpha CANONICAL LOSSES"
    assert all(sentinel not in str(roster) for sentinel in FLAT_SENTINELS)


def test_canonical_gap_audit_is_typed_persisted_and_never_enters_llm_or_behavior():
    actor = _actor("actor_alpha", "Alpha", "Alpha PUBLIC SHARED FACT")
    actor["intelligence"]["dimensions"]["future_plans"] = []
    gap = {
        "reason": "No public target date was found.",
        "attempted_queries": [
            "Alpha target date filing",
            "Alpha capital schedule",
        ],
        "receipt_ids": ["receipt_alpha_1", "receipt_alpha_2"],
        "result_ids": ["result_alpha_1", "result_alpha_2"],
        "attempt_count": 2,
        "exhausted": True,
    }
    actor["intelligence"]["evidence_gaps"]["future_plans"] = [gap]
    dossier = _dossier(actor)
    generator = _generator()
    generator._call_llm_with_retry = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("canonical typed-gap config must not call an LLM")
    )

    [config] = generator._generate_agent_configs_batch(
        context="unused",
        entities=[_entity("Alpha")],
        start_idx=0,
        simulation_requirement="Will a target date be announced?",
        actors=dossier,
        actor_context_packs={
            actor["actor_id"]: _pack(actor, dossier=dossier)
        },
    )

    audit = config.actor_context_evidence_gap_audit
    assert audit["schema_version"] == "actor-config-evidence-gap-audit/v1"
    assert audit["evidence_gaps"]["future_plans"] == [gap]
    assert ACTOR_CONFIG_EVIDENCE_GAP_AUDIT_KEY not in config.actor_context_digest
    for private_value in (
        *gap["attempted_queries"],
        *gap["receipt_ids"],
        *gap["result_ids"],
    ):
        assert private_value not in config.actor_context_digest


def test_canonical_rule_fallback_and_audience_distribution_ignore_flat_behavior(
    monkeypatch,
):
    monkeypatch.setattr(Config, "SIM_RULE_FALLBACK_STANCE", True)
    actor = _actor("actor_alpha", "Alpha", "Alpha PUBLIC SHARED FACT")
    dossier = _dossier(actor)
    generator = _generator()
    generator._call_llm_with_retry = lambda *args, **kwargs: (_ for _ in ()).throw(
        RuntimeError("offline rule path")
    )
    [config] = generator._generate_agent_configs_batch(
        context="unused",
        entities=[_entity("Alpha")],
        start_idx=0,
        simulation_requirement="question",
        actors=dossier,
        actor_context_packs={actor["actor_id"]: _pack(actor)},
    )

    assert config.stance == "neutral"
    assert config.influence_weight == 1.0
    assert config.gains_if == "Alpha CANONICAL GAINS"
    distribution = generator._audience_stance_distribution(
        dossier, main_agent_configs=[config]
    )
    assert distribution["neutral"] == 1.0
    assert distribution["supportive"] == 0.0


def test_canonical_agent_config_is_invariant_to_graph_type_and_summary():
    actor = _actor("actor_alpha", "Alpha", "Alpha PUBLIC SHARED FACT")
    dossier = _dossier(actor)
    packs = {actor["actor_id"]: _pack(actor, dossier=dossier)}
    government = _entity("Alpha")
    government.labels = ["Entity", "Government"]
    government.summary = "RAW GOVERNMENT SUMMARY SENTINEL"
    student = _entity("Alpha")
    student.labels = ["Entity", "Student"]
    student.summary = "RAW STUDENT SUMMARY SENTINEL"

    configs = []
    for entity in (government, student):
        generator = _generator()
        generator._call_llm_with_retry = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("canonical config must not call an LLM")
        )
        [config] = generator._generate_agent_configs_batch(
            "unused",
            [entity],
            0,
            "question",
            actors=dossier,
            actor_context_packs=packs,
        )
        configs.append(asdict(config))

    assert configs[0] == configs[1]
    assert configs[0]["entity_type"] == "Actor"
    assert configs[0]["influence_weight"] == 1.0
    assert configs[0]["stance"] == "neutral"
    assert "RAW GOVERNMENT" not in str(configs)
    assert "RAW STUDENT" not in str(configs)


def test_canonical_selected_actor_requires_exact_context_pack():
    actor = _actor("actor_alpha", "Alpha", "Alpha PUBLIC SHARED FACT")
    dossier = _dossier(actor)
    generator = _generator()
    generator._call_llm_with_retry = lambda *args, **kwargs: {"agent_configs": []}

    with pytest.raises(ValueError, match="requires a sealed actor-context/v1 pack"):
        generator._generate_agent_configs_batch(
            "", [_entity("Alpha")], 0, "question", actors=dossier,
            actor_context_packs=None,
        )

    tampered = _pack(actor)
    tampered["actor_intelligence"]["dimensions"]["current_actions"][0][
        "claim"
    ] = "tampered"
    with pytest.raises(ValueError, match="intelligence mismatch"):
        generator._generate_agent_configs_batch(
            "", [_entity("Alpha")], 0, "question", actors=dossier,
            actor_context_packs={actor["actor_id"]: tampered},
        )

    wrong_name = _pack(actor)
    wrong_name["actor_name"] = "Different Actor"
    with pytest.raises(ValueError, match="name mismatch"):
        generator._generate_agent_configs_batch(
            "", [_entity("Alpha")], 0, "question", actors=dossier,
            actor_context_packs={actor["actor_id"]: wrong_name},
        )


def test_unversioned_actor_keeps_exact_flat_compatibility_behavior(monkeypatch):
    monkeypatch.setattr(Config, "SIM_RULE_FALLBACK_STANCE", True)
    monkeypatch.setattr(Config, "SIM_SYNTH_SEED_POSTS", True)
    actor = {
        "name": "Legacy Alpha",
        "type": "Organization",
        "role": FLAT_SENTINELS[0],
        "stance": "supportive " + FLAT_SENTINELS[1],
        "influence": "high " + FLAT_SENTINELS[2],
        "memory": FLAT_SENTINELS[3],
        "incentives": [{
            "gains_if": FLAT_SENTINELS[4],
            "loses_if": FLAT_SENTINELS[5],
        }],
    }
    generator = _generator()
    captured = {}

    def fail_after_capture(prompt, system_prompt):
        captured["prompt"] = prompt
        raise RuntimeError("offline rule path")

    generator._call_llm_with_retry = fail_after_capture
    [config] = generator._generate_agent_configs_batch(
        "", [_entity("Legacy Alpha")], 0, "question",
        actors={"actors": [actor]},
    )
    assert all(sentinel in captured["prompt"] for sentinel in FLAT_SENTINELS[:4])
    assert config.stance == "supportive"
    assert config.influence_weight == 2.5
    assert config.gains_if == FLAT_SENTINELS[4]
    assert config.loses_if == FLAT_SENTINELS[5]

    event = generator._parse_event_config(
        {"hot_topics": [], "initial_posts": []},
        actors={
            "actors": [actor],
            "hot_topics": ["RAW HOT TOPIC SENTINEL"],
        },
    )
    assert event.hot_topics == ["RAW HOT TOPIC SENTINEL"]
    assert len(event.initial_posts) == 1
    assert "RAW HOT TOPIC SENTINEL" in event.initial_posts[0]["content"]
    assert FLAT_SENTINELS[1] in event.initial_posts[0]["content"]


class _Message:
    def __init__(self, content: str):
        self.content = content

    def create_new_instance(self, content: str):
        return _Message(content)


class _Agent:
    def __init__(self, name: str):
        self._original_system_message = _Message("ROLE " + name)
        self._system_message = None

    def _generate_system_message_for_output_language(self):
        return self._original_system_message

    def init_messages(self):
        return None


class _Graph:
    def __init__(self):
        self.rows = [(0, _Agent("Alpha")), (1, _Agent("Beta"))]

    def get_agents(self):
        return self.rows


def test_canonical_world_brief_shares_public_rows_without_private_omniscience(
    monkeypatch,
):
    monkeypatch.setattr(Config, "SIM_WORLD_BRIEF", True)
    monkeypatch.setattr(Config, "ADAPTIVE_CONTEXT", False)
    monkeypatch.setattr(Config, "SIM_SYNTH_SEED_POSTS", True)
    alpha = _actor("actor_alpha", "Alpha", "Alpha PUBLIC SHARED FACT")
    beta = _actor("actor_beta", "Beta", "Beta PUBLIC SHARED FACT")
    alpha["intelligence"]["dimensions"]["likely_actions"] = [
        _claim(
            "Alpha PUBLIC CONTESTED SIGNAL",
            evidence_type="contested",
            visibility="public",
        )
    ]
    dossier = _dossier(alpha, beta)
    packs = {
        alpha["actor_id"]: _pack(alpha, dossier=dossier),
        beta["actor_id"]: _pack(beta, dossier=dossier),
    }
    generator = _generator()

    brief = generator._build_world_brief(
        "Will the permit be approved?",
        dossier,
        ["RAW HOT TOPIC SENTINEL"],
        prediction_markets=[{
            "question": "RAW MARKET SENTINEL",
            "implied_yes_prob": 0.9,
        }],
        actor_context_packs=packs,
    )
    graph = _Graph()
    _inject_world_brief(graph, brief, lambda message: None)
    alpha_prompt = graph.rows[0][1]._original_system_message.content
    unrelated_beta_prompt = graph.rows[1][1]._original_system_message.content

    for prompt in (brief, alpha_prompt, unrelated_beta_prompt):
        assert "Alpha PUBLIC SHARED FACT" in prompt
        assert "Beta PUBLIC SHARED FACT" in prompt
        assert "Alpha PUBLIC CONTESTED SIGNAL" in prompt
        assert "[contested; not established fact]" in prompt
        assert "PRIVATE BOARD PLAN SENTINEL" not in prompt
        assert "MODEL ONLY INFERENCE SENTINEL" not in prompt
        assert "RAW SITUATION PRIVATE SENTINEL" not in prompt
        assert "RAW MODEL INFERENCE SENTINEL" not in prompt
        assert "RAW HOT TOPIC SENTINEL" not in prompt
        assert "RAW MARKET SENTINEL" not in prompt
        assert all(sentinel not in prompt for sentinel in FLAT_SENTINELS)

    context = generator._build_context(
        "Will the permit be approved?",
        "WHOLE DEEP RESEARCH REPORT SENTINEL",
        [_entity("Alpha"), _entity("Beta")],
        actors=dossier,
        actor_context_packs=packs,
    )
    assert "Alpha PUBLIC SHARED FACT" in context
    assert "WHOLE DEEP RESEARCH REPORT SENTINEL" not in context
    assert "Structural graph identity" not in context
    assert "PRIVATE BOARD PLAN SENTINEL" not in context
    assert all(sentinel not in context for sentinel in FLAT_SENTINELS)

    captured = {}

    def event_llm(prompt, system_prompt):
        captured["prompt"] = prompt
        return {"initial_posts": [], "hot_topics": [], "reasoning": "offline"}

    generator._call_llm_with_retry = event_llm
    generator._generate_event_config(
        context,
        "Will the permit be approved?",
        [_entity("Alpha"), _entity("Beta")],
        actors=dossier,
        actor_context_packs=packs,
    )
    assert "Alpha PUBLIC SHARED FACT" in captured["prompt"]
    assert "WHOLE DEEP RESEARCH REPORT SENTINEL" not in captured["prompt"]
    assert "Structural graph identity" not in captured["prompt"]
    assert "PRIVATE BOARD PLAN SENTINEL" not in captured["prompt"]
    assert all(sentinel not in captured["prompt"] for sentinel in FLAT_SENTINELS)

    event = generator._parse_event_config(
        {"hot_topics": [], "initial_posts": []},
        actors=dossier,
        actor_context_packs=packs,
    )
    serialized_event = str({
        "hot_topics": event.hot_topics,
        "initial_posts": event.initial_posts,
    })
    assert event.hot_topics == []
    assert len(event.initial_posts) == 2
    assert "Alpha source-bound incentive" in serialized_event
    assert "Beta source-bound incentive" in serialized_event
    assert "PRIVATE BOARD PLAN SENTINEL" not in serialized_event
    assert "MODEL ONLY INFERENCE SENTINEL" not in serialized_event
    assert "RAW HOT TOPIC SENTINEL" not in serialized_event
    assert all(sentinel not in serialized_event for sentinel in FLAT_SENTINELS)


def test_canonical_world_brief_retains_task_boundary_without_public_evidence(
    monkeypatch,
):
    monkeypatch.setattr(Config, "SIM_WORLD_BRIEF", True)
    actor = _actor("actor_alpha", "Alpha", "not public")
    for claims in actor["intelligence"]["dimensions"].values():
        for claim in claims:
            claim["visibility"] = "actor_internal"
    dossier = _dossier(actor)
    dossier["as_of_date"] = "2026-07-01"
    dossier["forecast_horizon"] = "through 2029"
    generator = _generator()
    brief = generator._build_world_brief(
        "question",
        dossier,
        ["RAW HOT TOPIC SENTINEL"],
        actor_context_packs={actor["actor_id"]: _pack(actor, dossier=dossier)},
    )
    graph = _Graph()
    _inject_world_brief(graph, brief, lambda message: None)
    prompts = [brief, *[
        agent._original_system_message.content for _agent_id, agent in graph.rows
    ]]
    for prompt in prompts:
        assert "question" in prompt
        assert dossier["as_of_date"] in prompt
        assert dossier["forecast_horizon"] in prompt
        for private_value in (
            "not public", "PRIVATE BOARD PLAN SENTINEL",
            "MODEL ONLY INFERENCE SENTINEL", "source-bound incentive",
            "CANONICAL GAINS", "CANONICAL LOSSES",
            "RAW SITUATION PRIVATE SENTINEL", "RAW MODEL INFERENCE SENTINEL",
            "RAW HOT TOPIC SENTINEL", *FLAT_SENTINELS,
        ):
            assert private_value not in prompt


def test_canonical_relationships_and_events_use_only_dossier_bound_visible_packs():
    alpha = _actor("actor_alpha", "Alpha", "Alpha PUBLIC SHARED FACT")
    beta = _actor("actor_beta", "Beta", "Beta PUBLIC SHARED FACT")
    gamma = _actor("actor_gamma", "Gamma", "Gamma PUBLIC SHARED FACT")
    dossier = _dossier(alpha, beta, gamma)
    dossier["as_of_date"] = "2026-07-01"

    public_relation = {
        "source": "Alpha",
        "target": "Beta",
        "type": "INFLUENCES",
        "valence": "adversarial",
        "strength": "high",
        "visibility": "public",
        "evidence_type": "verified_fact",
        "basis": "Public source-bound influence relation",
        "source_refs": ["src_public_relation"],
    }
    owner_local_relation = {
        "source": "Alpha",
        "target": "Gamma",
        "type": "REGULATES",
        "visibility": "actor_internal",
        "actor_knows": True,
        "evidence_type": "verified_fact",
        "basis": "Alpha-local monitoring relation",
        "source_refs": ["src_local_relation"],
    }
    counterparty_local_relation = {
        "source": "Alpha",
        "target": "Gamma",
        "type": "INFLUENCES",
        "valence": "adversarial",
        "visibility": "actor_internal",
        "actor_knows": True,
        "evidence_type": "verified_fact",
        "basis": "Alpha-private relation must not drive Gamma",
        "source_refs": ["src_private_relation"],
    }
    raw_unselected_relation = {
        "source": "Beta",
        "target": "Gamma",
        "type": "DEPENDS_ON",
        "valence": "allied",
        "visibility": "public",
        "evidence_type": "verified_fact",
        "basis": "RAW RELATIONSHIP BYPASS SENTINEL",
        "source_refs": ["src_raw_only_relation"],
    }
    dossier["relationships"] = [
        public_relation,
        owner_local_relation,
        counterparty_local_relation,
        raw_unselected_relation,
    ]

    public_event = {
        "date": "2026-09-15",
        "event": "Alpha PUBLIC SEALED EVENT",
        "visibility": "public",
        "evidence_type": "verified_fact",
        "source_refs": ["src_public_event"],
    }
    private_event = {
        "date": "2026-10-15",
        "event": "ACTOR PRIVATE EVENT SENTINEL",
        "visibility": "actor_internal",
        "evidence_type": "verified_fact",
        "source_refs": ["src_private_event"],
    }
    raw_unselected_event = {
        "date": "2026-11-15",
        "event": "RAW EVENT BYPASS SENTINEL",
        "visibility": "public",
        "evidence_type": "verified_fact",
        "source_refs": ["src_raw_only_event"],
    }
    dossier["key_events"] = [
        public_event,
        private_event,
        raw_unselected_event,
    ]
    packs = {
        alpha["actor_id"]: _pack(
            alpha,
            dossier=dossier,
            relationships=[
                public_relation,
                owner_local_relation,
                counterparty_local_relation,
            ],
            events=[public_event, private_event],
        ),
        beta["actor_id"]: _pack(
            beta,
            dossier=dossier,
            relationships=[public_relation],
        ),
        gamma["actor_id"]: _pack(gamma, dossier=dossier),
    }
    agents = [
        AgentActivityConfig(
            agent_id=index,
            entity_uuid=f"uuid:{name}",
            entity_name=name,
            entity_type="Organization",
            stance=("supportive", "opposing", "neutral")[index],
            interested_topics=[("alpha", "beta", "gamma")[index]],
        )
        for index, name in enumerate(("Alpha", "Beta", "Gamma"))
    ]
    generator = _generator()

    projection = generator._actor_context_config_projection(
        packs[alpha["actor_id"]], max_chars=10_000
    )
    projection_blob = json.dumps(projection, ensure_ascii=False)
    assert "Public source-bound influence relation" in projection_blob
    assert "Alpha-local monitoring relation" not in projection_blob
    assert "Alpha-private relation must not drive Gamma" not in projection_blob

    follows = generator._build_initial_follows(
        agents,
        [],
        dossier,
        actor_context_packs=packs,
    )
    assert {tuple(pair) for pair in follows} == {(1, 0)}
    assert generator._relation_sentiment_nudge(
        "Alpha", dossier, packs
    ) < 0
    assert generator._relation_sentiment_nudge(
        "Gamma", dossier, packs
    ) == 0
    echo_follows = generator._build_echo_chamber_follows(
        agents,
        actors=dossier,
        actor_context_packs=packs,
    )
    assert (0, 2) not in echo_follows
    assert (1, 2) not in echo_follows
    assert (2, 1) not in echo_follows

    events = generator._build_scheduled_events(
        dossier,
        TimeSimulationConfig(total_simulation_hours=24, minutes_per_round=60),
        agents,
        max_rounds=24,
        actor_context_packs=packs,
    )
    assert len(events) == 1
    assert events[0]["content"] == "Alpha PUBLIC SEALED EVENT"
    assert "ACTOR PRIVATE EVENT SENTINEL" not in str(events)
    assert "RAW EVENT BYPASS SENTINEL" not in str(events)

    assert generator._build_initial_follows(agents, [], dossier) == []
    assert generator._build_scheduled_events(
        dossier,
        TimeSimulationConfig(total_simulation_hours=24, minutes_per_round=60),
        agents,
    ) == []

    tampered = deepcopy(packs)
    tampered[alpha["actor_id"]]["relationships"][0][
        "basis"
    ] = "TAMPERED RELATIONSHIP SENTINEL"
    with pytest.raises(ValueError, match="not dossier-bound"):
        generator._build_initial_follows(
            agents,
            [],
            dossier,
            actor_context_packs=tampered,
        )
