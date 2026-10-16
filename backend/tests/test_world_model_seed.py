"""PREPARE-time ``world_model`` seed (design §2.7, acceptance A8) and ontology agency metadata.

Offline.  Pins: variables from quantitative facts + official series (as-of cutoff, cap),
agency class resolution order, canonical dossiers read only validated pack rows (no
analyst inference), relationships restricted to the cast with allies/rivals, audience
excluded, config emission + sealing, agent-config additive fields, ontology normalisation.
"""

import json
from dataclasses import asdict

import pytest

from app.services import world_model_seed as wms
from app.services.agent_decision import AGENCY_CLASSES
from app.services.ontology_generator import OntologyGenerator
from app.services.simulation_config_generator import AgentActivityConfig, SimulationParameters
from app.services.world_model import WorldModel


def _legacy_actors():
    return {
        "as_of_date": "2026-07-01",
        "central_question": "Will the grid permit unlock deployment by 2027?",
        "actors": [
            {"name": "Alpha Systems", "type": "Organization", "role": "grid developer", "aliases": ["Alpha"],
             "stance": "supportive", "influence": "high", "goals": ["Shape the permit timetable"],
             "future_plans": ["Build the Aurora line by 2027"], "likely_actions": ["File a permit response"],
             "red_lines": ["No unfinanced mandate"], "outcome_power": 1.5},
            {"name": "Beta Union", "type": "Organization", "role": "workers union", "stance": "opposing",
             "incentives": [{"gains_if": "members keep jobs", "loses_if": "automation accelerates"}]},
            {"name": "Grid Regulator", "type": "GovernmentAgency", "role": "state regulator", "stance": "neutral"},
            {"name": "Daily Wire", "type": "MediaOutlet", "role": "newspaper"},
        ],
        "relationships": [
            {"source": "Alpha Systems", "target": "Beta Union", "type": "OPPOSES", "strength": "high", "basis": "timetable"},
            {"source": "Grid Regulator", "target": "Alpha Systems", "type": "REGULATES"},
            {"source": "Alpha Systems", "target": "Unknown Co", "type": "PARTNERS_WITH"},
        ],
        "quantitative_facts": [
            {"metric": "Alpha planned investment", "value": "US$2 billion", "as_of_date": "2026-06-30",
             "source": "10-K", "definition": "capex guidance"},
            {"metric": "Permit status", "value": "pending"},
            {"metric": "", "value": "9"},
        ],
        "forecast_inputs": {
            "scenarios": [{"name": "Permit granted", "probability_band": "55-65%"}, {"name": "Permit delayed"}],
            "indicators": [{"indicator": "Permit docket activity", "direction": "up = granted"}],
        },
    }


def _official():
    return {"series": [
        {"title": "Regional capacity", "units": "MW", "provider_name": "EIA", "observations": [
            {"date": "2026-03-31", "value": 110}, {"date": "2026-06-30", "value": 120}, {"date": "2026-09-30", "value": 999}]},
        {"title": "No numbers", "units": "x", "observations": [{"date": "2026-01-01", "value": None}]},
        {"series": "ignored-no-units", "observations": [{"date": "2026-01-01", "value": 1}]},
    ]}


def _cfgs(include_audience=True):
    rows = [
        {"agent_id": 0, "entity_name": "Alpha Systems", "entity_type": "Organization", "stance": "supportive",
         "gains_if": "timetable holds", "loses_if": ""},
        {"agent_id": 1, "entity_name": "Beta Union", "entity_type": "Organization", "stance": "opposing"},
        {"agent_id": 2, "entity_name": "Grid Regulator", "entity_type": "GovernmentAgency", "stance": "neutral"},
        {"agent_id": 3, "entity_name": "Daily Wire", "entity_type": "MediaOutlet", "stance": "neutral"},
    ]
    if include_audience:
        rows.append({"agent_id": 4, "entity_name": "Audience 1", "entity_type": "Audience", "stance": "neutral"})
    return rows


class _Timeline:
    as_of_date = "2026-07-01"
    horizon_date = "2027-03-31"


def test_state_variables_from_research_and_official_with_cutoff():
    rows = wms.state_variables_from_research(_legacy_actors(), _official(), max_variables=24)
    by_id = {r["id"]: r for r in rows}
    inv = by_id["alpha_planned_investment"]
    assert inv["value"] == 2e9 and inv["unit"] == "US$" and inv["kind"] == "numeric"
    assert inv["as_of"] == "2026-06-30" and inv["provenance"] == "research"
    assert "capex guidance; 10-K" == inv["rationale"]
    assert by_id["permit_status"]["kind"] == "text" and by_id["permit_status"]["value"] == "pending"
    cap = by_id["regional_capacity"]
    assert cap["value"] == 120.0 and cap["as_of"] == "2026-06-30"          # 2026-09-30 is after the as-of cutoff
    assert cap["provenance"] == "official" and cap["rationale"] == "EIA" and cap["unit"] == "MW"
    assert "no_numbers" not in by_id and len(rows) == 3
    assert wms.state_variables_from_research(_legacy_actors(), _official(), max_variables=1)[0]["id"] == "alpha_planned_investment"
    assert wms.state_variables_from_research(None, None) == []


def test_resolve_agency_class_order():
    assert wms.resolve_agency_class({"agency_class": "labor_union"}, "Organization") == "labor_union"
    assert wms.resolve_agency_class({"name": "X"}, "Organization", ontology_class="central_bank") == "central_bank"
    assert wms.resolve_agency_class({"name": "Grid Regulator", "role": "state regulator"}, "GovernmentAgency") == "regulator_agency"
    assert wms.resolve_agency_class({"name": "Daily Wire"}, "MediaOutlet") == "media_outlet"
    assert wms.resolve_agency_class(None, "Person") == "individual_leader"
    assert wms.resolve_agency_class({"agency_class": "bogus"}, "Organization") == "firm"


def test_build_seed_from_legacy_dossier():
    block = wms.build_world_model_seed(_legacy_actors(), _cfgs(), question="Will the permit unlock deployment?",
                                       official_data=_official(), temporal_timeline=_Timeline())
    assert block["schema_version"] == wms.WORLD_MODEL_SEED_VERSION
    assert block["as_of_date"] == "2026-07-01" and block["horizon_date"] == "2027-03-31"
    assert block["scenarios"] == ["Permit granted", "Permit delayed"]
    assert block["scenario_indicators"] == [{"indicator": "Permit docket activity", "direction": "up = granted"}]
    actors = {a["agent_id"]: a for a in block["actors"]}
    assert set(actors) == {0, 1, 2, 3}                                     # audience excluded
    alpha = actors[0]
    assert alpha["agency_class"] == "firm" and alpha["capacity_per_round"] == 2
    assert alpha["outcome_power"] == 1.5 and actors[1]["outcome_power"] is None
    assert alpha["documented_plans"] == ["Build the Aurora line by 2027", "File a permit response"]
    assert alpha["red_lines"] == ["No unfinanced mandate"] and alpha["goals"] == ["Shape the permit timetable"]
    assert alpha["incentives"] == {"gains_if": "timetable holds"} and alpha["aliases"] == ["Alpha"]
    assert alpha["rivals"] == ["Beta Union"] and actors[1]["rivals"] == ["Alpha Systems"]
    assert actors[2]["agency_class"] == "regulator_agency" and actors[2]["capacity_per_round"] == 2
    assert actors[3]["agency_class"] == "media_outlet" and actors[3]["capacity_per_round"] == 1
    rels = block["relationships"]
    assert [(r["source"], r["target"], r["valence"]) for r in rels] == [
        ("Alpha Systems", "Beta Union", "adversarial"), ("Grid Regulator", "Alpha Systems", "directional")]
    assert rels[0]["polarity"] == -0.4 and rels[0]["source_agent_id"] == 0
    assert block["settings"] == {"arbiter_enabled": True, "max_change_ratio": 0.5, "barrier_timeout_s": 1800.0}
    # the block seeds a working world
    world = WorldModel.from_seed(block, _cfgs())
    assert world.variables["regional_capacity"].value == 120.0
    assert world.relationships[(0, 1)].valence == "adversarial"
    assert world.actors[0].documented_plans[0].startswith("Build the Aurora")
    assert world.actors[4].agency_class == "other_actor"                    # audience agent still has a state


def test_canonical_dossier_uses_only_validated_pack_rows():
    from test_actor_context_runtime import REPORT, _dossier
    from app.services import actor_context as ac
    dossier = _dossier()
    packs = {}
    for row in dossier["actors"]:
        pack = ac.build_actor_context_pack(dossier, row, REPORT)
        packs[row["actor_id"]] = pack
    cfgs = [{"agent_id": 0, "entity_name": "Alpha Systems", "entity_type": "Actor"},
            {"agent_id": 1, "entity_name": "Beta Union", "entity_type": "Actor"}]
    block = wms.build_world_model_seed(dossier, cfgs, actor_context_packs=packs, temporal_timeline=None)
    alpha = block["actors"][0]
    assert alpha["documented_plans"] == [
        "Alpha Systems plans a 2027 multi-site Project Aurora expansion.",
        "Alpha Systems is likely to file a permit response.",
        "Alpha Systems is executing Project Aurora now.",
        "Alpha Systems plans a $2 billion Project Aurora investment.",
    ]
    assert alpha["red_lines"] == ["Alpha Systems will not accept an unfinanced immediate mandate."]
    # motivations are analyst inference in the fixture → skipped; values remain
    assert alpha["goals"] == ["Alpha Systems values operational reliability."]
    assert alpha["agency_class"] == "firm"
    # the flat legacy fields of a canonical actor are not read
    dossier2 = _dossier()
    dossier2["actors"][0]["future_plans"] = ["FLAT LEAK"]
    block2 = wms.build_world_model_seed(dossier2, cfgs, actor_context_packs=packs)
    assert "FLAT LEAK" not in json.dumps(block2)
    # without a pack a canonical actor gets no plans at all (never the flat fields)
    block3 = wms.build_world_model_seed(dossier2, cfgs, actor_context_packs=None)
    assert block3["actors"][0]["documented_plans"] == []


def test_seed_degrades_on_garbage():
    block = wms.build_world_model_seed("not a dict", [{"agent_id": "x"}, None, {"agent_id": 1, "entity_name": "Z"}])
    assert block["actors"][0]["name"] == "Z" and block["state_variables"] == [] and block["relationships"] == []
    assert wms.world_model_seed_summary(block) == "world model: 0 variables, 1 actors, 0 relationships"


def test_agent_activity_config_additive_fields_and_parameters_emit_block():
    cfg = AgentActivityConfig(agent_id=0, entity_uuid="u", entity_name="X", entity_type="Org",
                              agency_class="firm", archetype="actor", outcome_power=2.0)
    d = asdict(cfg)
    assert d["agency_class"] == "firm" and d["archetype"] == "actor" and d["outcome_power"] == 2.0
    d0 = asdict(AgentActivityConfig(agent_id=1, entity_uuid="u", entity_name="Y", entity_type="Org"))
    assert d0["agency_class"] == "" and d0["archetype"] == "" and d0["outcome_power"] is None
    params = SimulationParameters(simulation_id="s", project_id="p", graph_id="g", simulation_requirement="q")
    assert "world_model" not in params.to_dict()                           # omitted when absent (legacy bytes)
    params.world_model = {"schema_version": wms.WORLD_MODEL_SEED_VERSION, "actors": [{"agent_id": 0}]}
    assert params.to_dict()["world_model"]["actors"][0]["agent_id"] == 0
    assert json.loads(params.to_json())["world_model"]["schema_version"] == wms.WORLD_MODEL_SEED_VERSION


def test_ontology_normalization_fills_agency_class():
    result = {
        "entity_types": [
            {"name": "GovernmentMinistry", "description": "Ministries that set trade policy", "archetype": "actor"},
            {"name": "LaborUnion", "description": "", "archetype": "collective", "agency_class": "labor_union"},
            {"name": "NewsOutlet", "description": "", "archetype": "source"},
            {"name": "Chipmaker", "description": "Semiconductor manufacturers", "agency_class": "bogus"},
        ],
        "edge_types": [{"name": "SANCTIONS"}],
    }
    OntologyGenerator._normalize_rich_schema(result)
    ents = {e["name"]: e for e in result["entity_types"]}
    assert ents["GovernmentMinistry"]["agency_class"] == "sovereign_government"
    assert ents["LaborUnion"]["agency_class"] == "labor_union"
    assert "agency_class" not in ents["NewsOutlet"]                       # sources are not agents
    assert ents["Chipmaker"]["archetype"] == "actor" and ents["Chipmaker"]["agency_class"] == "firm"
    assert all(e.get("agency_class") in AGENCY_CLASSES for e in result["entity_types"] if "agency_class" in e)
    assert result["edge_types"][0]["family"] == "antagonism"


def test_sealed_config_carries_world_model_block(tmp_path):
    from app.services.simulation_manager import build_simulation_config_seal, validate_simulation_config_seal
    block = wms.build_world_model_seed(_legacy_actors(), _cfgs(False), temporal_timeline=_Timeline())
    cfg = {"simulation_id": "sim_wm", "agent_configs": _cfgs(False),
           "temporal_config": {"mode": "calendar", "unit": "quarter", "n_rounds": 3, "round_dates": []},
           "world_model": block}
    (tmp_path / "simulation_config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    config_sha, manifest_sha = build_simulation_config_seal(
        str(tmp_path), simulation_id="sim_wm", actor_cast_manifest_sha256=None,
        actor_context_manifest_sha256=None, actor_role_manifest_sha256={})
    validate_simulation_config_seal(str(tmp_path), expected_manifest_sha256=manifest_sha,
                                    expected_config_sha256=config_sha, expected_simulation_id="sim_wm", require=True)
    reloaded = json.loads((tmp_path / "simulation_config.json").read_text(encoding="utf-8"))
    assert reloaded["world_model"]["actors"][0]["agency_class"] == "firm"
    # tampering with the block breaks the seal
    reloaded["world_model"]["actors"][0]["agency_class"] = "sovereign_government"
    (tmp_path / "simulation_config.json").write_text(json.dumps(reloaded, ensure_ascii=False, indent=2), encoding="utf-8")
    with pytest.raises(ValueError):
        validate_simulation_config_seal(str(tmp_path), expected_manifest_sha256=manifest_sha,
                                        expected_config_sha256=config_sha, expected_simulation_id="sim_wm",
                                        require=True)


# ----------------------------------------------------------------------------- research engine v3 rows
def _v3_actors():
    """Research engine v3 ``actors.json`` rows (deerflow_bridge/linear_research.py ACTOR EXTRACTION
    TASK), shaped like the live pipe_d569f211eb14 dossier: goals / constraints / stated_vs_revealed /
    memory / incentives / worldview, and none of the legacy plan or red-line keys."""
    return {
        "as_of_date": "2026-10-16",
        "central_question": "What is the state of US–China trade restrictions on 30 June 2027?",
        "actors": [
            {"name": "Donald Trump", "type": "Person", "role": "US President; sets tariff levels personally",
             "stance": "Seeks a bigger deal", "description": "Personally authorized chip sales in December 2025.",
             "stated_vs_revealed": ("States 'fair and reciprocal relationship'; revealed record shows willingness "
                                    "to override security hawks and will escalate when cornered."),
             "memory": ("Escalated to 126.1 percent average tariffs in May 2025, then cut to 51.7 percent at "
                        "Geneva; announced a Beijing summit scheduled for April 2027."),
             "influence": "high", "simulation_tier": 1, "role_class": "principal", "aliases": ["President Trump"],
             "goals": ["Conclude a 'bigger deal' with China before the January 10, 2027 truce expiry",
                       "Preserve tariff leverage while claiming wins",
                       "Possibly reinstate the Affiliates Rule",
                       "Keep Nvidia/AMD chip sales and profit-sharing",
                       "Impose Section 232 duties on legacy chips"],
             "constraints": ["November 3, 2026 midterm elections",
                             "Will not accept a deal without verified soybean purchases",
                             "Post-IEEPA legal limits forcing Section 301/232 instruments",
                             "Rules out any tariff cut below 20 percent before the midterms",
                             "No clear majority in the Senate for a tariff bill"],
             "assets": ["Executive authority over tariffs"],
             "vulnerabilities": ["Will escalate if the truce collapses"],
             "incentives": [{"driver": "Political credit", "gains_if": "Framework converts to signed text",
                             "loses_if": "Truce collapses", "intensity": "high"}],
             "worldview": {"values": ["Reciprocity"], "beliefs": ["Tariff leverage extracts concessions"],
                           "identity": "Dealmaker president", "frame": "Trade as transactional negotiation"},
             "risk_tolerance": "high", "salience": {"tier": 1, "score": 0.95, "basis": "Sets tariff levels"}},
            {"name": "Xi Jinping", "type": "Person", "role": "President of China", "stance": "Willing to extend truce",
             "stated_vs_revealed": ("Commits to purchases and fentanyl-precursor controls; revealed practice is "
                                    "uneven follow-through."),
             "memory": "April 2025 controls followed by November 2025 suspension under deal pressure.",
             "influence": "high", "simulation_tier": 1, "role_class": "principal", "aliases": [],
             "goals": ["Prolong truce to stabilize economy", "Preserve rare-earth chokepoint leverage"],
             "constraints": ["US imports of rare earths never recovered — leverage costs export revenue",
                             "Soybean pace at 'almost half' of commitment draws US criticism"],
             "incentives": [{"driver": "Leverage", "gains_if": "Tariff cuts continue", "loses_if": "Re-escalation",
                             "intensity": "high"}],
             "worldview": {"values": [], "beliefs": [], "identity": "", "frame": ""}, "risk_tolerance": "medium",
             "salience": {"tier": 1, "score": 0.9, "basis": "Controls rare-earth instruments"}},
            {"name": "PIIE", "type": "Organization", "role": "Think tank", "stance": "Neutral measurement",
             "stated_vs_revealed": "Neutral scholarly measurement.", "memory": "Documented the 2018-2026 chronology.",
             "influence": "low", "simulation_tier": 4, "role_class": "arbiter", "aliases": [],
             "goals": ["Accurate bilateral tariff measurement"], "constraints": None, "incentives": [],
             "worldview": {}, "risk_tolerance": "low", "salience": {"tier": 4, "score": 0.2, "basis": "Benchmark"}},
            {"name": "商务部", "type": "Government", "role": "中国商务部", "stance": "维持暂停措施",
             "stated_vs_revealed": "公开承诺扩大采购；实际执行不均", "memory": "2025年10月出台管制措施，11月暂停。",
             "influence": "high", "simulation_tier": 1, "role_class": "principal", "aliases": ["MOFCOM"],
             "goals": ["推动签署阶段性协议", "维持现有关税水平", "可能收紧稀土许可"],
             "constraints": ["绝不接受无核查的采购承诺", "2026年11月10日法律到期需发布编号公告"],
             "incentives": [], "worldview": {}, "risk_tolerance": "medium",
             "salience": {"tier": 1, "score": 0.8, "basis": "管制工具"}},
        ],
        "relationships": [{"source": "Donald Trump", "target": "Xi Jinping", "type": "COMPETES_WITH",
                           "valence": "adversarial", "polarity": -0.5, "strength": 0.7, "basis": "tariffs"}],
        "quantitative_facts": [{"metric": "Average US tariff on imports from China", "value": "35.2",
                                "unit": "percent", "as_of_date": "2026-09-30", "source": "PIIE"}],
        "forecast_inputs": {"scenarios": [{"name": "Deal deepens"}, {"name": "Truce holds"}]},
    }


def _v3_cfgs():
    return [{"agent_id": 0, "entity_name": "Donald Trump", "entity_type": "Person", "stance": "Seeks a bigger deal"},
            {"agent_id": 1, "entity_name": "Xi Jinping", "entity_type": "Person"},
            {"agent_id": 2, "entity_name": "PIIE", "entity_type": "Organization"},
            {"agent_id": 3, "entity_name": "商务部", "entity_type": "Government"}]


def test_v3_plans_come_from_stated_commitments_and_action_phrased_goals():
    trump, xi, piie, mofcom = _v3_actors()["actors"]
    assert wms.derive_v3_plans(trump) == [
        "Conclude a 'bigger deal' with China before the January 10, 2027 truce expiry",   # action verb
        "Impose Section 232 duties on legacy chips",                                       # action verb
        "announced a Beijing summit scheduled for April 2027",                             # memory commitment
    ]
    # postures ("Preserve", "Keep"), hedges ("Possibly"), the stance-only stated clause, the revealed half,
    # vulnerabilities and incentives are never promoted; "May 2025" is a month, not a hedge
    assert wms.derive_v3_plans(xi) == ["Commits to purchases and fentanyl-precursor controls",
                                       "Prolong truce to stabilize economy"]
    assert wms.derive_v3_plans(piie) == []                                      # noun-phrase goal, no commitment
    assert wms.derive_v3_plans(mofcom) == ["公开承诺扩大采购", "推动签署阶段性协议"]
    assert wms.derive_v3_plans(None) == [] and wms.derive_v3_plans({"goals": "Sign the deal"}) == ["Sign the deal"]
    many = {"goals": [f"Impose duty {i}" for i in range(6)]}
    assert len(wms.derive_v3_plans(many)) == wms.MAX_PLANS


def test_v3_red_lines_come_from_non_negotiable_wording_only():
    trump, xi, piie, mofcom = _v3_actors()["actors"]
    assert wms.derive_v3_red_lines(trump) == ["Will not accept a deal without verified soybean purchases",
                                              "Rules out any tariff cut below 20 percent before the midterms"]
    assert wms.derive_v3_red_lines(xi) == []                                    # "never recovered" is history
    assert wms.derive_v3_red_lines(piie) == []                                  # constraints: null
    assert wms.derive_v3_red_lines(mofcom) == ["绝不接受无核查的采购承诺"]       # the procedural expiry is not one
    refusal = {"stated_vs_revealed": "Says it will not accept chip-control floors; in fact it wavers",
               "goals": ["Rule out any tariff cut before verification"]}
    assert wms.derive_v3_red_lines(refusal) == ["Says it will not accept chip-control floors"]   # goals are not read
    assert wms.derive_v3_plans(refusal) == []                                  # a refusal is never a plan
    assert wms.derive_v3_red_lines({"constraints": ["Might refuse to sign", "Trump's signature needed",
                                                    "No clear majority in the Senate", "Not yet ratified",
                                                    "不得不接受现有关税水平"]}) == []        # hedged / absence / "has to"
    # "U.S." is an abbreviation, not a sentence end; the revealed clause after ";" stays out
    ustr = {"stated_vs_revealed": "U.S. Trade Representative commits to publishing the tariff-cut list; "
                                  "privately doubts China's follow-through"}
    assert wms.derive_v3_plans(ustr) == ["U.S. Trade Representative commits to publishing the tariff-cut list"]


def test_build_seed_from_v3_dossier_yields_plans_and_red_lines():
    from app.services.agent_decision import build_option_menu
    block = wms.build_world_model_seed(_v3_actors(), _v3_cfgs(), question="US–China trade?", temporal_timeline=_Timeline())
    actors = {a["agent_id"]: a for a in block["actors"]}
    trump = actors[0]
    assert trump["documented_plans"] == [
        "Conclude a 'bigger deal' with China before the January 10, 2027 truce expiry",
        "Impose Section 232 duties on legacy chips",
        "announced a Beijing summit scheduled for April 2027"]
    assert trump["red_lines"] == ["Will not accept a deal without verified soybean purchases",
                                  "Rules out any tariff cut below 20 percent before the midterms"]
    assert trump["goals"][0].startswith("Conclude a 'bigger deal'") and trump["aliases"] == ["President Trump"]
    assert actors[1]["documented_plans"][0] == "Commits to purchases and fentanyl-precursor controls"
    assert actors[1]["red_lines"] == [] and actors[2]["documented_plans"] == [] and actors[2]["red_lines"] == []
    assert actors[3]["red_lines"] == ["绝不接受无核查的采购承诺"]
    dumped = json.dumps(block, ensure_ascii=False)
    for leak in ("will escalate when cornered", "Will escalate if the truce collapses",          # revealed / vulnerability
                 "Tariff leverage extracts concessions", "Framework converts to signed text",   # worldview / incentive
                 "实际执行不均"):
        assert leak not in dumped, leak
    promoted = json.dumps([(a["documented_plans"], a["red_lines"]) for a in block["actors"]], ensure_ascii=False)
    for posture in ("Possibly reinstate", "Preserve tariff leverage", "Keep Nvidia/AMD", "维持现有关税水平"):
        assert posture not in promoted, posture                              # goals stay goals, never plans
    assert trump["rivals"] == ["Xi Jinping"] and block["state_variables"][0]["value"] == 35.2
    # the derived plans reach the option menu of the running world
    world = WorldModel.from_seed(block, _v3_cfgs())
    labels = [o["label"] for o in build_option_menu(world.actors[0], world, 1)]
    assert any(label.startswith("Advance your documented plan: Conclude a 'bigger deal'") for label in labels)
    # explicit legacy keys still win over the derivation
    dossier = _v3_actors()
    dossier["actors"][0]["future_plans"] = ["FLAT PLAN"]
    dossier["actors"][0]["red_lines"] = ["EXPLICIT LINE"]
    row = wms.build_world_model_seed(dossier, _v3_cfgs())["actors"][0]
    assert row["documented_plans"] == ["FLAT PLAN"] and row["red_lines"] == ["EXPLICIT LINE"]
