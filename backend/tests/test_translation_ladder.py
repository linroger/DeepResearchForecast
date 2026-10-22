"""2026-10-21: translation compliance ladder + artifact overlay caches."""

import json

from app.services.translation_tools import chat_translate, is_content_filter_error, translate_pairs


class _FakeLLM:
    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def chat(self, messages, temperature=0.1, max_tokens=None, tier=None):
        self.calls += 1
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


class _FilterErr(Exception):
    pass


def test_is_content_filter_error():
    assert is_content_filter_error(_FilterErr("Error code: 400 {'code': '1301'}"))
    assert is_content_filter_error(_FilterErr("contentFilter level 1"))
    assert is_content_filter_error(_FilterErr("系统检测到敏感内容"))
    assert not is_content_filter_error(_FilterErr("Connection error"))


def test_ladder_l1_rescues_content_filter():
    llm = _FakeLLM([
        _FilterErr("Error code: 400 {'error': {'code': '1301'}}"),
        "译文第一章",
    ])
    out, level = chat_translate(llm, "SYS", "Chapter one\n\nChapter two is here",
                                max_tokens=100)
    assert out == "译文第一章" and level == 1 and llm.calls == 2


def test_ladder_l2_fragments_and_degrades_per_fragment():
    llm = _FakeLLM([
        _FilterErr("1301"),
        _FilterErr("contentFilter"),
        "片段一译",
        _FilterErr("1301"),
    ])
    out, level = chat_translate(llm, "SYS", "para one\n\npara two", max_tokens=100)
    assert level == 2
    assert "片段一译" in out and "para two" in out


def test_ladder_non_filter_error_fails_fast():
    llm = _FakeLLM([RuntimeError("Connection error")])
    out, level = chat_translate(llm, "SYS", "text", max_tokens=100)
    assert out == "" and level == 0 and llm.calls == 1


def test_translate_pairs_batch_and_fallback():
    llm = _FakeLLM([
        json.dumps({"a": "甲", "b": "乙"}, ensure_ascii=False),
    ])
    mapping, level = translate_pairs(llm, [("a", "one"), ("b", "two")], "简体中文")
    assert mapping == {"a": "甲", "b": "乙"} and level == 0
    llm2 = _FakeLLM(["not json"])
    mapping2, _ = translate_pairs(llm2, [("a", "one")], "简体中文")
    assert mapping2 == {}


def test_simulation_overlay_cache_incremental(tmp_path, monkeypatch):
    from app.services import artifact_translation as at

    sim_dir = tmp_path / "sim_test123"
    sim_dir.mkdir()
    world = {"world": {
        "question": "Who governs France?",
        "scenarios": [{"name": "Muddle through"}, {"name": "Crisis"}],
        "variables": [
            {"id": "v1", "name": "Deficit pct", "rationale": "Official estimate from INSEE",
             "history": [{"cause": "seed"}]},
        ],
    }}
    (sim_dir / "world_state.json").write_text(json.dumps(world), encoding="utf-8")
    monkeypatch.setattr(at, "_sim_dir", lambda sid: str(sim_dir) if sid == "sim_test123" else None)

    llm = _FakeLLM([
        json.dumps({
            "world:question": "谁治理法国？",
            "scenario:0": "勉力维持",
            "scenario:1": "危机",
            "var:v1:name": "赤字率",
            "var:v1:rationale": "INSEE 官方估计",
        }, ensure_ascii=False),
    ])
    monkeypatch.setattr("app.utils.llm_client.LLMClient", lambda: llm)
    result = at.simulation_translation("sim_test123", "zh")
    assert result["status"] == "available"
    ov = result["overlay"]
    assert ov["world:question"] == "谁治理法国？"
    assert ov["var:v1:name"] == "赤字率"
    cache_path = sim_dir / "translations" / "zh.json"
    assert cache_path.exists()

    llm2 = _FakeLLM([])
    monkeypatch.setattr("app.utils.llm_client.LLMClient", lambda: llm2)
    result2 = at.simulation_translation("sim_test123", "zh")
    assert result2["cached"] == result2["total_candidates"] and llm2.calls == 0

    world["world"]["question"] = "Who governs France now?"
    (sim_dir / "world_state.json").write_text(json.dumps(world), encoding="utf-8")
    llm3 = _FakeLLM([json.dumps({"world:question": "现在谁治理法国？"}, ensure_ascii=False)])
    monkeypatch.setattr("app.utils.llm_client.LLMClient", lambda: llm3)
    result3 = at.simulation_translation("sim_test123", "zh")
    assert llm3.calls == 1
    assert result3["overlay"]["world:question"] == "现在谁治理法国？"


# ---- 2026-10-21: unclipped sim text + flat direction + hedged-commitment plans ----

def test_statement_cap_no_longer_clips_normal_statements():
    from app.services import agent_decision as ad
    assert ad.STATEMENT_MAX_CHARS >= 4000
    s = ad._text("word " * 300, ad.STATEMENT_MAX_CHARS)  # 1500 chars — full
    assert not s.endswith("…") and len(s) >= 1400


def test_flat_relationship_direction_is_accepted():
    from app.services.world_update import validate_arbiter_update
    from app.services.world_model import ActorState, WorldModel

    world = WorldModel(question="q")
    world.add_actor(ActorState(1, "A"))
    world.add_actor(ActorState(2, "B"))
    raw = {"relationship_changes": [
        {"source": "A", "target": "B", "direction": "flat", "rationale": "explicit hold"},
        {"source": "A", "target": "B", "direction": "sideways"},
    ]}
    update, problems = validate_arbiter_update(raw, world, [])
    dirs = [rc["direction"] for rc in update["relationship_changes"]]
    assert dirs == ["flat"]
    assert any("unknown relationship direction 'sideways'" in p for p in problems)
    assert not any("'flat'" in p for p in problems)


def test_hedged_commitment_in_stance_becomes_plan():
    from app.services.world_model_seed import derive_v3_plans
    actor = {
        "name": "Leader",
        "stance": "Agreed 'in principle' to trilateral talks after 10 Nov 2026; skeptical of details",
        "goals": ["Preserve leverage"],
    }
    plans = derive_v3_plans(actor, 4)
    assert any("trilateral talks" in p for p in plans)
    # hedge stays verbatim — the reservation is visible, nothing rewritten
    assert any("'in principle'" in p for p in plans)


# ---- 2026-10-22: boolean lexicon + horizon floor ----

def test_boolean_lexicon_coerces_decisive_phrases():
    from app.services.world_update import validate_arbiter_update
    from app.services.world_model import ActorState, WorldModel

    world = WorldModel(question="q")
    world.add_variable("Trilateral talks agenda agreed", False, kind="boolean")
    raw = {"variable_changes": [
        {"id": "trilateral_talks_agenda_agreed", "new_value": "agreed in principle"},
        {"id": "trilateral_talks_agenda_agreed", "new_value": "nonsense free text"},
    ]}
    # run twice (dedupe blocks same var twice in one update)
    u1, p1 = validate_arbiter_update({"variable_changes": [
        {"id": "trilateral_talks_agenda_agreed", "new_value": "agreed in principle"}]}, world, [])
    assert u1["variable_changes"][0]["new_value"] is True
    u2, p2 = validate_arbiter_update({"variable_changes": [
        {"id": "trilateral_talks_agenda_agreed", "new_value": "pending agenda confirmation"}]}, world, [])
    assert u2["variable_changes"][0]["new_value"] is False
    _, p3 = validate_arbiter_update({"variable_changes": [
        {"id": "trilateral_talks_agenda_agreed", "new_value": "perhaps a formulation of words"}]}, world, [])
    assert any("non-boolean" in p for p in p3)


def test_near_horizon_from_question_is_floored():
    from datetime import date
    from app.utils import sim_timeline
    h = sim_timeline.extract_horizon("developments in October 2026", date(2026, 10, 22))
    assert h is not None and h.source == "anchored_period"
    gap = (date.fromisoformat(h.horizon_date) - date(2026, 10, 22)).days
    assert 0 < gap < 60  # exactly the news-window artifact class the floor rejects
