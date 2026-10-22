"""Mandarin numeric boundaries and source-bound dashboard language truth."""
import copy
import json
import re

import pytest

from app.services.report_agent import ReportAgent, ReportManager
from tests.test_report_forecast_localization import _seal_forecast, Translator, _agent


SOURCE = "The Q1 2027 forecast follows H1 2025 and H1 2026. The Oct27 89.24 print remains quoted."
FUSED = "Q12027的预测参考H12025和H12026的情况。Oct2789.24的报价保持不变。"


def test_source_proven_boundary_repair_keeps_digits_and_native_final_audit():
    repaired, changes = ReportAgent._repair_translation_numeric_boundaries(SOURCE, FUSED)
    assert len(changes) == 4
    assert "Q1 2027" in repaired and "Oct27 89.24" in repaired
    assert ReportAgent._translation_fact_multiset(repaired) == ReportAgent._translation_fact_multiset(SOURCE)
    assert re.sub(r"\s", "", repaired) == re.sub(r"\s", "", FUSED)
    agent = ReportAgent.__new__(ReportAgent)
    agent._forecast_spine = None
    audit, _ = agent._audit_translation_variant("report_boundary", SOURCE, repaired,
                                               "en", "zh", {}, enforce_citations=False)
    assert audit["number_parity"]["passed"] is True
    assert "translation numeric-token multiset differs from primary" not in audit["issues"]


@pytest.mark.parametrize("candidate", [FUSED.replace("89.24", "89.25"), FUSED.replace("2027", "2028")])
def test_real_value_or_year_changes_are_never_excused(candidate):
    repaired, _ = ReportAgent._repair_translation_numeric_boundaries(SOURCE, candidate)
    assert ReportAgent._translation_fact_multiset(repaired) != ReportAgent._translation_fact_multiset(SOURCE)


def test_genuine_ids_and_protected_spans_are_not_split():
    source = "The ID Q12027 remains literal. Q1 2027 also appears. `H12025` https://example.org/Oct2789.24"
    candidate = "标识Q12027保持原样。Q12027也存在。`H12025` https://example.org/Oct2789.24"
    fixed, repairs = ReportAgent._repair_translation_numeric_boundaries(source, candidate)
    assert fixed == candidate and repairs == []


@pytest.mark.parametrize("source,candidate,expected", [
    ("The 10–11 October ceasefire failed.", "10–10月11日停火失败。", "10月10日–11日停火失败。"),
    ("The 17–18 October 2026 attack was recorded.", "17–2026年10月18日的袭击已有记录。",
     "2026年10月17日–18日的袭击已有记录。"),
    ("The 17–18 October 2026 attack was recorded.", "17 日至 2026年10月18日的袭击已有记录。",
     "2026年10月17日–18日的袭击已有记录。"),
])
def test_legacy_date_range_repair_preserves_source_endpoints(source, candidate, expected):
    fixed, repairs = ReportAgent._repair_translation_numeric_boundaries(source, candidate)
    assert fixed == expected and len(repairs) == 1
    assert ReportAgent._translation_fact_multiset(source) == ReportAgent._translation_fact_multiset(fixed)


@pytest.mark.parametrize("candidate", ["17–2027年10月18日", "17–2026年11月18日", "16–2026年10月18日"])
def test_changed_date_components_cannot_be_recovered(candidate):
    source = "The 17–18 October 2026 attack was recorded."
    fixed, repairs = ReportAgent._repair_translation_numeric_boundaries(source, candidate)
    assert fixed == candidate and not repairs
    assert ReportAgent._translation_fact_multiset(source) != ReportAgent._translation_fact_multiset(fixed)


def test_missing_range_connector_requires_regeneration():
    source = "The 10–11 October ceasefire failed."
    candidate = "10月11日的10能源停火失败。"
    fixed, repairs = ReportAgent._repair_translation_numeric_boundaries(source, candidate)
    assert fixed == candidate and not repairs
    assert ReportAgent._translation_fact_multiset(source) != ReportAgent._translation_fact_multiset(fixed)


def test_unarmed_unit_keeps_adjacent_restored_identifiers_separate():
    class Model:
        def chat(self, messages, **kwargs):
            tokens = re.findall(r"⟦[^⟧]+⟧", messages[-1]["content"])
            return "所列时期和报价分别为" + "".join(tokens) + "，事实保留。"

    agent = ReportAgent.__new__(ReportAgent)
    agent.llm = Model()
    result = agent._translate_markdown_unit(SOURCE, "简体中文")
    assert ReportAgent._translation_fact_multiset(result) == ReportAgent._translation_fact_multiset(SOURCE)
    assert "Q12027" not in result and "Oct2789.24" not in result


@pytest.fixture
def reports(tmp_path, monkeypatch):
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"))


def test_already_mandarin_forecast_is_complete_without_a_variant_or_model(reports):
    source = {"headline": "预测总结", "scenarios": [{"name": "基准情景", "probability": .7,
               "summary": "供给约束持续。"}], "binary_forecasts": []}
    _seal_forecast("report_already_zh", source, "# 预测总结\n\n## 结论\n\n供给约束持续。\n")
    forecast, info = ReportManager.load_localized_forecast("report_already_zh", "zh")
    assert forecast == source and info["complete"] and info["already_target"]
    assert info["localized"] is False


@pytest.mark.parametrize("source", [
    "THE COMMITTEE WILL NOT APPROVE THE PROPOSAL.",
    "目前的判断仅供参考。" * 10 + "The committee will not approve the proposal.",
])
def test_source_prose_cannot_claim_mandarin_completeness_from_case_or_prefix(reports, source):
    from model_translation_fakes import model_protocol
    target = source.replace("THE COMMITTEE WILL NOT APPROVE THE PROPOSAL.", "委员会不会批准该提案。").replace(
        "The committee will not approve the proposal.", "委员会不会批准该提案。")
    rid = "report_language_not_proven"
    _seal_forecast(rid, {"headline": source, "scenarios": [], "binary_forecasts": []},
                   "# Outlook\n\n## Decision\n\nThe committee has not decided.\n")
    _, initial = ReportManager.load_localized_forecast(rid, "zh")
    assert initial["complete"] is False and initial["already_target"] is False
    class Model:
        def chat(self, messages, **kwargs):
            return model_protocol(messages, lambda text: target if text == source else text)
    _agent(Model())._ensure_localized_forecast(rid, "zh")
    variant, info = ReportManager.load_localized_forecast(rid, "zh")
    assert info["complete"] is True and variant["headline"] == target
    assert variant["localization"]["receipts"]["headline"]["review"]["target_language"] is True


def test_english_proper_name_is_allowed_by_review_without_forced_rewriting(reports):
    from model_translation_fakes import model_protocol
    rid = "report_reviewed_name"
    _seal_forecast(rid, {"headline": "NVIDIA", "scenarios": [], "binary_forecasts": []},
                   "# Outlook\n\n## Decision\n\nSupply remains constrained.\n")
    assert ReportManager.load_localized_forecast(rid, "zh")[1]["complete"] is False
    class Model:
        def chat(self, messages, **kwargs):
            return model_protocol(messages, lambda text: text)
    _agent(Model())._ensure_localized_forecast(rid, "zh")
    variant, info = ReportManager.load_localized_forecast(rid, "zh")
    assert info["complete"] is True and variant["headline"] == "NVIDIA"


@pytest.mark.parametrize("path,value", [("probability", .9), ("id", "CHANGED")])
def test_bound_variant_cannot_mutate_probability_or_identity(reports, path, value):
    source = {"headline": "Capacity outlook", "scenarios": [{"name": "Base", "probability": .7,
               "summary": "Capacity remains tight."}],
              "binary_forecasts": [{"id": "F1", "statement": "Capacity grows", "probability": .6}]}
    rid = "report_variant_" + path
    _seal_forecast(rid, source, "# Capacity\n\n## Outlook\n\nCapacity remains tight.\n")
    _agent(Translator())._ensure_localized_forecast(rid, "zh")
    variant_path = ReportManager._get_report_localized_forecast_path(rid, "zh")
    variant = json.loads(open(variant_path).read())
    before = copy.deepcopy(source)
    variant["binary_forecasts"][0][path] = value
    with open(variant_path, "w") as handle:
        json.dump(variant, handle)
    result, info = ReportManager.load_localized_forecast(rid, "zh")
    assert result == before and info["localized"] is False


def test_reader_incomplete_verdict_overrides_stale_complete_cache_metadata(reports):
    source = {"headline": "Capacity remains constrained.", "scenarios": [], "binary_forecasts": []}
    rid = "report_stale_complete"
    sha = _seal_forecast(rid, source, "# Capacity\n\n## Decision\n\nCapacity remains constrained.\n")
    value = {**source, "localization": {"lang": "zh", "source_forecast_sha256": sha, "complete": True}}
    with open(ReportManager._get_report_localized_forecast_path(rid, "zh"), "w") as handle:
        json.dump(value, handle)
    _, before = ReportManager.load_localized_forecast(rid, "zh")
    assert before["complete"] is False
    model = Translator()
    _agent(model)._ensure_localized_forecast(rid, "zh")
    result, info = ReportManager.load_localized_forecast(rid, "zh")
    assert info["complete"] is True and result["headline"] != source["headline"]
    assert model.bypass_seen and all(model.bypass_seen)


def test_localized_scenario_labels_keep_membership_and_values_joined(reports):
    source = {"headline": "Capacity outlook", "scenarios": [{"name": "Base", "probability": .7,
               "summary": "Capacity remains tight."}],
              "binary_forecasts": [{"id": "F1", "statement": "Capacity grows", "probability": .6,
                                    "scenario_membership": {"yes_scenarios": ["Base"]}}]}
    rid = "report_membership_zh"
    _seal_forecast(rid, source, "# Capacity\n\n## Outlook\n\nCapacity remains tight.\n")
    _agent(Translator())._ensure_localized_forecast(rid, "zh")
    result, info = ReportManager.load_localized_forecast(rid, "zh")
    assert info["localized"] and info["complete"]
    assert result["binary_forecasts"][0]["scenario_membership"]["yes_scenarios"] == [result["scenarios"][0]["name"]]
    assert result["scenarios"][0]["probability"] == .7
    assert result["binary_forecasts"][0]["id"] == "F1"


@pytest.mark.parametrize("damage", ["unit", "identifier", "url", "currency"])
def test_reader_rejects_changed_protected_facts_in_prose(reports, damage):
    source = {"headline": "Capacity outlook", "scenarios": [], "binary_forecasts": [
        {"id": "F1", "statement": "GDP_USD capacity reaches 25 MW for $3.7 billion. https://example.org/a",
         "probability": .7}]}
    rid = "report_prose_damage_" + damage
    sha = _seal_forecast(rid, source, "# Outlook\n\n## Decision\n\nCapacity reaches 25 MW.\n")
    statement = "GDP_USD产能达到25 MW，投入37亿美元。https://example.org/a"
    before, after = {"unit": ("MW", "GW"), "identifier": ("GDP_USD", "CPI_USD"),
                     "url": ("/a", "/b"), "currency": ("美元", "欧元")}[damage]
    value = copy.deepcopy(source)
    value["headline"] = "产能展望"
    value["binary_forecasts"][0]["statement"] = statement.replace(before, after)
    value["localization"] = {"lang": "zh", "source_forecast_sha256": sha, "complete": True}
    with open(ReportManager._get_report_localized_forecast_path(rid, "zh"), "w") as handle:
        json.dump(value, handle)
    observed, info = ReportManager.load_localized_forecast(rid, "zh")
    assert not info["localized"] and observed == source


def test_forecast_generation_preserves_units_ids_and_equivalent_localized_dates_amounts():
    source = {"headline": "GDP_USD capacity reaches 25 MW by October 31, 2026 for $3.7 billion.",
              "scenarios": [], "binary_forecasts": []}
    localized, info = _agent(Translator())._localize_forecast(source, "zh")
    assert "GDP_USD" in localized["headline"] and "MW" in localized["headline"]
    assert "2026年10月31日" in localized["headline"] and "37亿美元" in localized["headline"]
    assert ReportAgent._forecast_text_facts_preserved(source["headline"], localized["headline"])
    assert info["unresolved"] == []


@pytest.mark.parametrize("source,target", [
    ("The plant supplies 25 kW.", "该设施供应25 W。"),
    ("Budget is $3.7 billion with €2 billion reserves.", "预算为37亿欧元，储备为20亿美元。"),
    ("The balance is -3.7 billion.", "余额为37亿。"),
    ("Use `not flag` to decide.", "使用`notflag`来决定。"),
])
def test_real_reader_rejects_si_sign_currency_binding_and_code_damage(reports, source, target):
    forecast = {"headline": "Capacity outlook", "scenarios": [], "binary_forecasts": [
        {"id": "F1", "statement": source, "probability": .7}]}
    rid = "report_factual_association"
    sha = _seal_forecast(rid, forecast, "# Outlook\n\n## Decision\n\nCapacity remains constrained.\n")
    variant = copy.deepcopy(forecast)
    variant["headline"] = "产能展望"
    variant["binary_forecasts"][0]["statement"] = target
    variant["localization"] = {"lang": "zh", "source_forecast_sha256": sha, "complete": True}
    with open(ReportManager._get_report_localized_forecast_path(rid, "zh"), "w") as handle:
        json.dump(variant, handle)
    observed, info = ReportManager.load_localized_forecast(rid, "zh")
    assert not info["localized"] and observed == forecast


@pytest.mark.parametrize("source,target", [
    ("The balance is -3.7 billion.", "余额为-37亿。"),
    ("Budget is $3.7 billion with €2 billion reserves.", "预算为37亿美元，储备为20亿欧元。"),
    ("Use `not flag` to decide.", "使用`not flag`来决定。"),
])
def test_protected_associations_allow_faithful_localization(source, target):
    assert ReportAgent._forecast_text_facts_preserved(source, target)


@pytest.mark.parametrize("unit", ["kW", "W", "mW", "µW", "kWh"])
def test_forecast_producer_preserves_native_si_units_and_negative_amounts(unit):
    source = {"headline": f"GDP_USD capacity is 25 {unit} with -3.7 billion balance.",
              "scenarios": [], "binary_forecasts": []}
    localized, info = _agent(Translator())._localize_forecast(source, "zh")
    assert unit in localized["headline"] and "GDP_USD" in localized["headline"]
    assert "-37亿" in localized["headline"] and not info["unresolved"]
    assert ReportAgent._forecast_text_facts_preserved(source["headline"], localized["headline"])


def test_rate_circuit_is_not_a_content_filter_or_a_publishable_translation():
    from app.utils.llm_errors import is_content_filter_error
    error = RuntimeError("LLM 调用失败：主提供方 glm 处于 422/429 熔断冷却，且回退提供方不可用")
    assert not is_content_filter_error(error)
    class Unavailable:
        def chat(self, **kwargs):
            raise error
    result = _agent(Unavailable()).translate_research_markdown(
        "# Capacity outlook\n\n## Decision\n\nThe committee delayed its planned decision.\n")
    assert not result["available"]
    assert not result.get("audit", {}).get("verbatim_chunks")


@pytest.mark.parametrize("source", [
    "-200–-50 million", "$-200–-50 million", "$1.5–0.0005 million",
    "0.1–0.000001 million", "-2亿–-5000万美元",
])
def test_native_mixed_magnitude_ranges_pass_generation_and_fact_admission(source):
    from app.services import translation_quantities as quantities
    amounts = quantities.find_quantities(source)
    assert len(amounts) == 1 and len(amounts[0].values) == 2
    target = quantities.render_quantity(amounts[0], "zh")
    assert ReportAgent._forecast_text_facts_preserved(source, target)
    forecast = {"headline": "The balance ranges from " + source + ".", "scenarios": [], "binary_forecasts": []}
    localized, summary = _agent(Translator())._localize_forecast(forecast, "zh")
    assert summary["complete"] and not summary["unresolved"], {"localized": localized, "summary": summary}
    assert ReportAgent._forecast_text_facts_preserved(forecast["headline"], localized["headline"])


def test_mixed_ranges_never_inherit_across_words_or_conflicting_currencies():
    from app.services import translation_quantities as quantities
    values = quantities.find_quantities("$2 billion–€3 billion")
    assert len(values) == 2 and [q.currency for q in values] == ["USD", "EUR"]
    values = quantities.find_quantities("2 billion — 42 days later")
    assert len(values) == 1 and len(values[0].values) == 1


def test_public_report_and_pair_transport_share_admission(monkeypatch):
    import threading
    import time
    from app.services import translation_tools as tools
    from tests.test_translation_pairs_integrity import Translator as PairTranslator

    monkeypatch.setenv("DRF_TRANSLATION_MAX_CONCURRENCY", "1")
    entered, release = threading.Event(), threading.Event()
    lock = threading.Lock()
    counts = {"active": 0, "max": 0}
    class Observed:
        def __init__(self, model): self.model = model
        def chat(self, *args, **kwargs):
            with lock:
                counts["active"] += 1
                counts["max"] = max(counts["max"], counts["active"])
                entered.set()
            try:
                assert release.wait(3)
                return self.model.chat(*args, **kwargs)
            finally:
                with lock: counts["active"] -= 1

    report_model, pair_model = Observed(Translator()), Observed(PairTranslator())
    agent = _agent(report_model)
    results = {}
    def report():
        results["report"] = agent.translate_research_markdown(
            "# Capacity outlook\n\n## Decision\n\nCapacity remains constrained.\n")
    def pair():
        results["pair"] = tools.translate_pairs(pair_model, [("a", "Capacity remains constrained.")], "简体中文")
    threads = [threading.Thread(target=report), threading.Thread(target=pair)]
    for thread in threads: thread.start()
    try:
        assert entered.wait(2)
        deadline = time.monotonic() + 2
        queued = False
        while time.monotonic() < deadline:
            with tools._TRANSLATION_ADMISSION.condition:
                queued = bool(tools._TRANSLATION_ADMISSION.waiters)
            if queued: break
            time.sleep(.005)
        assert queued and counts["max"] == 1
    finally:
        release.set()
        for thread in threads: thread.join(4)
    assert not any(thread.is_alive() for thread in threads)
    assert results["report"]["available"] and "a" in results["pair"][0]
    assert counts == {"active": 0, "max": 1}
    assert agent.llm is report_model
