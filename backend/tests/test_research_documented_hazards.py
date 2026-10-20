"""Documented hazards: the v3 research that gives ``forecast_inputs.risks`` something to keep.

Pins (docs/handoff/research-risks/documented-hazards.md): with method skills the reference-class
skill's Plan words the risks KIQ "Documented hazards (外生风险概率): which sources publish a
probability and window for <2-3 exogenous events>?"; such a KIQ — and only such a KIQ — gets
``_HAZARD_KIQ_NOTE`` (record what a source publishes, as printed, with its window and marker; never
estimate, count, convert or derive one; say so when none is published), and every section writer gets
``_HAZARD_SECTION_RULE`` (one sentence per published probability, naming no scenario, not bold or a
heading). Neither text ever asks for a probability of the model's own. A published hazard in the KIQ
notes then reaches ``actors.json`` ``forecast_inputs.risks`` (and the world-model seed's shocks); a
hazard no source publishes ends with ``risks: []`` even when the extraction model offers a number.
With ``RESEARCH_SKILLS=off`` none of the text appears.

Offline and deterministic: the scripted model and ``run_engine`` harness of ``test_research_engine_v3``
(injected search/fetch, the real bridge module with prediction markets and charts stubbed), no
network, no LLM, no sleeps.
"""

from __future__ import annotations

import json
import re

import pytest

import test_research_engine_v3 as v3
from app.services import world_model_seed as wms

# The shared fixtures (hermetic env, real bridge with network steps stubbed).
_hermetic_env = v3._hermetic_env
bridge = v3.bridge
lr = v3.lr

import research_skills as rs  # noqa: E402  (on sys.path through test_research_engine_v3)

_ZERO = dict.fromkeys(lr._FRAME_RISK_CHECKS, 0)
_CFGS = [{"agent_id": 0, "entity_name": "Grid operator", "entity_type": "Organization"},
         {"agent_id": 1, "entity_name": "Hyperscaler A", "entity_type": "Organization"}]
_TIMELINE = {"as_of_date": "2026-09-27", "horizon_date": "2027-12-31"}

HAZARD_KIQ = ("Documented hazards: which sources publish a probability and window for a connection moratorium "
              "on new data-centre load or a cooling-water ban?")
HAZARD_KIQ_ZH = "外生风险概率：哪些来源发布了新增数据中心负荷接入暂停的概率及其时间窗口？"
PUBLISHED = ("The grid regulator's 2026 risk register puts the probability of a connection moratorium on new "
             "data-centre load at 10% per year.")
MORATORIUM = "Connection moratorium on new data-centre load"


def _plan_text() -> str:
    return rs.load_library().skills[rs.CROSS_CUTTING].section("Plan")


def _never_asks_for_an_estimate(text: str) -> None:
    """Every word that would ask for a probability of the model's own stands in a "never" clause."""
    for match in re.finditer(r"\b(?:estimat|count|convert|deriv|comput|calculat|assess|judg)\w*", text, re.I):
        sentence = re.split(r"(?<=[.;:])\s", text[:match.start()])[-1]
        assert re.search(r"\bnever\b", sentence, re.I), (match.group(0), sentence)


# =============================================================== the prompt text

def test_the_reference_class_plan_words_the_risks_kiq_as_documented_hazards():
    plan = _plan_text()
    line = next(line for line in plan.splitlines() if "Documented hazards" in line)
    assert line.startswith("- **Word the risks KIQ** ")
    template = re.search(r'"(Documented hazards .+?)"', line).group(1)
    assert template == ("Documented hazards (外生风险概率): which sources publish a probability and window for "
                        "<2-3 exogenous events: disaster, disruption, ruling, default>?")
    assert line.endswith(", never the outcome or a scenario.")
    _never_asks_for_an_estimate(line)
    # The wording routes the engine's hazard note, and is no base-rate KIQ: the 30-year data prefetch,
    # the catalog fallback seed and the "count comparable episodes" note stay with base-rate KIQs.
    assert lr._HAZARD_KIQ_RE.search(template) and not lr._BASE_RATE_RE.search(template)
    # The rest of the Plan still teaches base-rate KIQs, the weighting and the calendar KIQ.
    for text in ('worded "base rate", "historically", "how often" or "precedent"', "wb:IMF_WEO_PCPIPCH/USA",
                 "**Weight scenarios base-rate-first:**", "(4) name the anchor in each thesis",
                 "**Split on the decisive variable**", "need a calendar KIQ"):
        assert text in plan, text


def test_the_kiq_note_asks_only_for_probabilities_sources_publish():
    note = lr._HAZARD_KIQ_NOTE
    assert note.startswith("DOCUMENTED HAZARDS: for each exogenous event this question names")
    for text in ("a probability that a source itself publishes for it", "a risk register",
                 "a catastrophe-model return period", "a rating agency's default study",
                 "the probability and the window it refers to exactly as the source prints them",
                 "the publisher's [S<n>] marker",
                 "Never estimate, count, convert or derive a probability yourself",
                 "never record a scenario weight or a forecast of the research question's own outcome as one",
                 "When no source publishes a probability for an event, say so under ## Open questions."):
        assert text in note, text
    _never_asks_for_an_estimate(note)
    assert not re.search(r"\d", note)          # no example figure the agent could copy


def test_the_writer_rule_states_published_probabilities_on_one_checkable_line():
    rule = lr._HAZARD_SECTION_RULE
    assert rule.startswith("- Documented hazards: ")    # one more line of the writer's Rules list
    for text in ("a probability that a source publishes for a risk event", "in a sentence of its own",
                 "names no scenario and is not bold or a heading",
                 "the probability and its window exactly as the evidence gives them, and the marker",
                 "Never give a risk event a probability the evidence does not publish",
                 # only where the evidence itself records it, so runs without a hazards KIQ get no such lines
                 "where the evidence records that none was published for an event, say so."):
        assert text in rule, text
    _never_asks_for_an_estimate(rule)


@pytest.mark.parametrize("question, hazard", [
    (HAZARD_KIQ, True),
    ("Published hazard rates of an interconnector outage: who publishes them, for which window?", True),
    (HAZARD_KIQ_ZH, True),
    ("哪些机构公布了电网事故的风险概率？", True),
    ("What natural hazards do data-centre sites face?", False),        # a topic, not the hazards KIQ
    ("Which hazardous-materials rules apply to battery storage?", False),
    ("Base rate: how often did grid queues exceed 36 months?", False),
    ("What are the main constraints and risks to the build-out?", False),
    ("约束与风险：哪些风险可能改变结果？", False),
])
def test_only_the_documented_hazards_kiq_matches(question, hazard):
    assert bool(lr._HAZARD_KIQ_RE.search(question)) is hazard


def test_why_the_rule_names_no_scenario_and_no_bold_item():
    """A published probability written beside a scenario name is "restated" to the scenario's weight
    by fix_scenario_weights (and the hazard lost); a bold item with a percentage in the scenario
    section is read as an extra scenario. The sentence the rule asks for survives both."""
    frame = [lr.Scenario("Base case", 50, "a"), lr.Scenario("Accelerated build-out", 30, "b"),
             lr.Scenario("Stalled expansion", 20, "c")]
    row = {"event": "Connection moratorium", "probability": "10%", "per": "per year", "source": "S1"}
    sources = [{"title": "Grid regulator risk register", "url": "https://regulator.example/register"}]

    beside = "Stalled expansion (10%) follows a connection moratorium per year [S1]."
    fixed, fixes = lr.fix_scenario_weights(beside, frame)
    assert fixes and "(20%)" in fixed
    assert lr.normalize_frame_risks({"risks": [row]}, fixed, [], sources, frame)[0] == []

    canonical = "\n".join(f"- **{s.name} ({s.weight}% probability):** {s.thesis}" for s in frame)
    bold = "- **Connection moratorium (10% per year):** the regulator's risk register [S1]"
    assert len(lr.parse_report_scenarios(f"## Scenarios and Probabilities\n\n{canonical}\n{bold}\n")) == 4

    sentence = ("The grid regulator's risk register puts the probability of a connection moratorium at 10% "
                "per year [S1].")
    assert lr.fix_scenario_weights(sentence, frame) == (sentence, [])
    assert lr.strip_extra_scenario_probabilities(sentence, frame) == (sentence, [])
    report = f"## Scenarios and Probabilities\n\n{canonical}\n\n{sentence}\n"
    assert lr.parse_report_scenarios(report) == [{"name": s.name, "probability": s.weight / 100} for s in frame]
    risks, checks = lr.normalize_frame_risks({"risks": [row]}, report, [], sources, frame)
    assert [(r["probability"], r["per"], r["source"]) for r in risks] == [
        ("10%", "per year", "Grid regulator risk register [S1]")]
    assert checks["kept"] == 1


# =============================================================== scripted engine runs

def _digest_line(context: str, *words: str) -> str | None:
    return next((line for line in context.splitlines() if all(w in line for w in words)), None)


class HazardWorld(v3.World):
    """The scripted planner adds a documented-hazards KIQ (a live planner rewords its risks KIQ so,
    following the reference-class Plan); that KIQ's agent finds the
    regulator's published probability for a moratorium and none for a cooling-water ban; a writer
    that was given the hazard rule states what the evidence publishes in the scenario section
    (where the scenario post-processing runs) and says what it does not; the extraction model also
    offers a probability for the ban that no source published."""

    published = True

    def plan(self, call):
        reply = super().plan(call)
        plan = json.loads(reply.content.split("```json\n", 1)[1].split("\n```", 1)[0])
        plan["kiqs"].append({"question": HAZARD_KIQ_ZH if self.zh() else HAZARD_KIQ,
                             "queries": ["grid moratorium probability"], "kind": "general"})
        plan["sections"][4]["kiqs"] = [4, 5]        # Grid Constraints
        return v3.ai("```json\n" + json.dumps(plan, ensure_ascii=False) + "\n```")

    def agent(self, call):
        reply = super().agent(call)
        task = call["messages"][2][1]
        if reply.tool_calls or ("Documented hazards" not in task and "外生风险" not in task):
            return reply
        cite = re.search(r"\[S(\d+)\] \(VERIFIED\)", reply.content).group(1)   # the page it fetched
        findings = [f"- {PUBLISHED[:-1]} [S{cite}] (VERIFIED)"] if self.published else []
        open_questions = ["- No published probability found for a cooling-water ban"]
        if not self.published:
            open_questions.append(f"- No published probability found for a {MORATORIUM[0].lower()}{MORATORIUM[1:]}")
        notes = reply.content.replace("## Findings\n", "## Findings\n" + "".join(f + "\n" for f in findings), 1)
        notes = notes.replace("## Open questions\n", "## Open questions\n" + "\n".join(open_questions) + "\n", 1)
        return v3.ai(notes)

    def writer(self, call):
        reply = super().writer(call)
        task, context = call["messages"][-1][1], call["messages"][2][1]
        heading = "## Scenarios and Probabilities\n\n"
        if lr._HAZARD_SECTION_RULE not in task or heading not in reply.content:
            return reply
        sentences = []
        line = _digest_line(context, "connection moratorium", "10%")
        if line:
            sentences.append(re.sub(r"\s*\((?:VERIFIED|REPORTED)\)$", "", line[2:]) + ".")
        for line in context.splitlines():
            if line.startswith("- No published probability found for "):
                sentences.append("No published probability was found for " + line.split(" for ", 1)[1] + ".")
        return v3.ai(reply.content.replace(heading, heading + "\n\n".join(sentences) + "\n\n", 1), out=1500)

    def frame(self, call):
        report = call["messages"][2][1]
        line = next((line for line in report.splitlines() if "moratorium" in line and "10%" in line), "")
        marker = (re.search(r"\[S(\d+)\]", line) or re.search(r"\[S(\d+)\]", report)).group(1)
        return v3.ai(json.dumps({
            "base_rates": [], "drivers": [],
            "risks": [{"event": MORATORIUM, "probability": "10%", "per": "per year", "source": f"S{marker}",
                       "affects": ["Grid operator", "Hyperscaler A"], "recurring": True},
                      {"event": "Cooling-water ban", "probability": "5%", "per": "per year", "source": f"S{marker}"}],
        }))


class UnpublishedWorld(HazardWorld):
    """The same run, but no source publishes a probability for either event."""

    published = False


def _publishing_page(url: str) -> str:
    return v3.page_text(url) + "\n\n" + PUBLISHED


def _hazard_tasks(model) -> dict[str, str]:
    tasks = {}
    for call in v3.calls_of(model, "agent"):
        task = call["messages"][2][1]
        kid = re.search(r"Investigate (\S+):", task).group(1)
        tasks[kid] = task
    return tasks


def test_e2e_a_published_hazard_in_the_kiq_notes_reaches_forecast_inputs_risks(tmp_path, bridge):
    rc, meta, _, model, out = v3.run_engine(tmp_path, bridge, HazardWorld(), fetch=_publishing_page)
    assert rc == 0, meta.get("error")
    plan = json.loads((out / "v3" / "plan.json").read_text(encoding="utf-8"))
    assert plan["kiqs"][-1]["question"] == HAZARD_KIQ and rs.CROSS_CUTTING in plan["skills"]

    # Only the documented-hazards KIQ gets the note, last in its task; every writer gets the rule.
    tasks = _hazard_tasks(model)
    hazard_kid = plan["kiqs"][-1]["id"]
    assert tasks[hazard_kid].endswith("\n" + lr._HAZARD_KIQ_NOTE)
    assert all(lr._HAZARD_KIQ_NOTE not in task for kid, task in tasks.items() if kid != hazard_kid)
    writers = [call["messages"][-1][1] for call in v3.calls_of(model, "SECTION WRITING TASK")]
    assert writers and all(lr._HAZARD_SECTION_RULE in task for task in writers)
    assert all(task.index(lr._HAZARD_SECTION_RULE) > task.index(lr._SECTION_RULES) for task in writers)

    # The published probability is a verified finding of that KIQ, in the evidence every writer reads.
    context = v3.calls_of(model, "SECTION WRITING TASK")[0]["messages"][2][1]
    finding = _digest_line(context, "connection moratorium", "10% per year")
    assert finding and finding.endswith("(VERIFIED)")

    # The report states it on one line in the scenario section, which the scenario checks left intact.
    body = lr.strip_references((out / "research_report.md").read_text(encoding="utf-8"))
    scenario_part = body.split("## Scenarios and Probabilities", 1)[1]
    line = next(line for line in scenario_part.splitlines() if "moratorium" in line)
    assert line.startswith(PUBLISHED[:-1] + " [S") and line.endswith("].")
    assert "No published probability was found for a cooling-water ban." in scenario_part
    number = int(re.search(r"\[S(\d+)\]", line).group(1))
    source = json.loads((out / "sources.json").read_text(encoding="utf-8"))[number - 1]

    actors = json.loads((out / "actors.json").read_text(encoding="utf-8"))
    assert actors["forecast_inputs"]["risks"] == [
        {"event": MORATORIUM, "probability": "10%", "per": "per year",
         "source": f"{lr._collapse(source['title'], 120)} [S{number}]",
         **{key: source[k] for key, k in (("source_url", "url"), ("tier", "tier")) if source.get(k)},
         "effects": [], "affects": ["Grid operator", "Hyperscaler A"], "recurring": True}]
    # the ban's number came from the extraction model, not from a source: dropped and counted
    assert json.loads((out / "meta.json").read_text(encoding="utf-8"))["forecast_risks"] == {
        **_ZERO, "extracted": 2, "kept": 1, "probability_not_stated": 1}

    block = wms.build_world_model_seed(actors, _CFGS, temporal_timeline=_TIMELINE)
    [shock] = block["shocks"]
    assert shock["event"] == MORATORIUM and shock["source"].endswith(f"[S{number}]")
    assert shock["base_rate"] == {"probability": 0.1, "window": "year", "window_days": 365.25, "text": "10%"}
    assert not [gap for gap in block["gaps"] if gap["kind"] in ("no_documented_shocks", "shock_without_window",
                                                                 "shock_without_source")]


def test_e2e_a_hazard_no_source_publishes_ends_with_an_empty_list(tmp_path, bridge):
    rc, meta, _, model, out = v3.run_engine(tmp_path, bridge, UnpublishedWorld())
    assert rc == 0, meta.get("error")
    context = v3.calls_of(model, "SECTION WRITING TASK")[0]["messages"][2][1]
    assert not _digest_line(context, "moratorium", "10%")
    assert _digest_line(context, "No published probability found for a connection moratorium")
    body = lr.strip_references((out / "research_report.md").read_text(encoding="utf-8"))
    assert "No published probability was found for a connection moratorium on new data-centre load." in body
    assert not re.search(r"moratorium[^\n]*\d+%", body)

    # The extraction model offered 10% and 5%; the report states neither, so nothing is kept.
    actors = json.loads((out / "actors.json").read_text(encoding="utf-8"))
    assert actors["forecast_inputs"]["risks"] == []
    assert json.loads((out / "meta.json").read_text(encoding="utf-8"))["forecast_risks"] == {
        **_ZERO, "extracted": 2, "probability_not_stated": 2}
    block = wms.build_world_model_seed(actors, _CFGS, temporal_timeline=_TIMELINE)
    assert block["shocks"] == [] and block["gaps"][0]["kind"] == "no_documented_shocks"


def test_e2e_a_chinese_documented_hazards_kiq_gets_the_note(tmp_path, bridge):
    rc, meta, _, model, out = v3.run_engine(tmp_path, bridge, HazardWorld(language="Chinese"),
                                            question="到2027年底全球数据中心装机容量会超过250吉瓦吗？",
                                            fetch=_publishing_page)
    assert rc == 0, meta.get("error")
    plan = json.loads((out / "v3" / "plan.json").read_text(encoding="utf-8"))
    assert plan["kiqs"][-1]["question"] == HAZARD_KIQ_ZH
    tasks = _hazard_tasks(model)
    assert tasks[plan["kiqs"][-1]["id"]].endswith("\n" + lr._HAZARD_KIQ_NOTE)
    assert sum(lr._HAZARD_KIQ_NOTE in task for task in tasks.values()) == 1


def test_e2e_without_method_skills_no_hazard_text_and_no_risks(tmp_path, bridge, monkeypatch):
    monkeypatch.setenv("RESEARCH_SKILLS", "off")
    rc, meta, _, model, out = v3.run_engine(tmp_path, bridge, HazardWorld(), fetch=_publishing_page)
    assert rc == 0, meta.get("error")
    prompts = [text for call in model.calls for _, text in call["messages"]]
    assert not any("DOCUMENTED HAZARDS" in text or "Documented hazards: when" in text for text in prompts)
    assert not v3.calls_of(model, "FORECAST FRAME EXTRACTION TASK")
    assert "moratorium" not in (out / "research_report.md").read_text(encoding="utf-8").split(
        "## Scenarios and Probabilities", 1)[1].split("\n## ", 1)[0]
    assert json.loads((out / "actors.json").read_text(encoding="utf-8"))["forecast_inputs"]["risks"] == []
    assert "forecast_risks" not in json.loads((out / "meta.json").read_text(encoding="utf-8"))
