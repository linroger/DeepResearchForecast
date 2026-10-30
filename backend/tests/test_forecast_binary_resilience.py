"""Content-filter-safe binary extraction (report stage) and the truncation lint refinement.

Live defect: glm-5.3 content-filtered the single 48k-character extraction prompt
(HTTP 400 code 1301), no fallback provider was configured, binary_count stayed 0 and
the publish gate failed the whole report.  Pins: chunked retry skips filtered chunks
and merges the rest; the scenario-partition fallback is deterministic, labelled and
consistent with the partition; non-filter errors still propagate; a complete table
cell ending after a parenthesis is not a truncation while a real width cut still is.
"""

import json

import pytest

from app.services import forecast_binary_resilience as fbr
from app.services import report_lint as rl
from app.services.forecast_extractor import audit_proposition_consistency
from tests.conftest import FakeLLMClient


def test_fresh_binary_extraction_accepts_justified_ambiguity_without_forced_spread(monkeypatch):
    from app.services import forecast_extractor as fe
    monkeypatch.setattr(fe, "_cfg", lambda name, default=None: "fail" if name == "REPORT_PUBLISH_GATE_MODE" else default)
    rows = [{"statement": f"Agency measure {i} exceeds 10 GW by 2027-06-30",
             "probability": 0.5, "resolution_criteria": "Agency measured operational capacity > 10 GW on 2027-06-30",
             "resolution_source": "Agency annual capacity register", "theme": "capacity"}
            for i in range(5)]
    llm = FakeLLMClient(json_responses=[{"binary_forecasts": rows}])
    result = fe.extract_binary_forecasts("Evidence is balanced and uncertain.", llm, min_count=5)
    quality = result["binary_quality"]
    assert quality["passed"] and quality["distribution_diagnostics"]
    assert quality["policy_version"] == fe.BINARY_QUALITY_POLICY
    assert len(llm.calls) == 1
    prompt = llm.calls[0]["messages"][0]["content"]
    assert "justified uncertainty" in prompt and "CONTRARIAN FRAMING" not in prompt
    assert "do not cluster" not in prompt
    # The real report-agent recomputation consumes these persisted rows.
    assert fe._binary_quality(result["binary_forecasts"], min_count=5)["passed"]
    bad = [{**row, "criteria_sharp": False} for row in result["binary_forecasts"]]
    assert not fe._binary_quality(bad, min_count=5)["passed"]
    old = [{k: v for k, v in row.items() if k != "quality_policy"} for row in result["binary_forecasts"]]
    assert not fe._binary_quality(old, min_count=5)["passed"]


def test_binary_quality_keeps_probability_and_policy_validation(monkeypatch):
    from app.services import forecast_extractor as fe
    monkeypatch.setattr(fe, "_cfg", lambda name, default=None: "fail" if name == "REPORT_PUBLISH_GATE_MODE" else default)
    row = {"probability": 0.5, "criteria_sharp": True, "quality_policy": fe.BINARY_QUALITY_POLICY}
    assert not fe._binary_quality([{**row, "probability": 1.2}], min_count=1)["passed"]
    assert not fe._binary_quality([row, {**row, "quality_policy": "unknown/v99"}], min_count=1)["passed"]


def _balanced_rows(count=5, prefix="Capacity"):
    return [{"statement": f"{prefix} measure {i} exceeds 10 GW by 2027-06-30",
             "probability": 0.5, "resolution_criteria": "Agency operational capacity > 10 GW on 2027-06-30",
             "resolution_source": "Agency register", "theme": "capacity"} for i in range(count)]


def _assert_evidence_prompts(calls):
    assert calls
    for call in calls:
        prompt = "\n".join(row["content"] for row in call["messages"])
        for quota in ("do not cluster", "CONTRARIAN FRAMING", "40-50%", "0.05-0.35 range",
                      "express genuine CONVICTION", "genuine conviction, not hedging"):
            assert quota not in prompt


def test_actual_topup_and_ensemble_requests_keep_evidence_policy(monkeypatch):
    from app.services import forecast_extractor as fe
    monkeypatch.setattr(fe, "_cfg", lambda name, default=None: "second" if name == "FORECAST_ENSEMBLE_MODELS" else default)
    primary = FakeLLMClient(json_responses=[{"binary_forecasts": []}, {"binary_forecasts": _balanced_rows()}])
    secondary = FakeLLMClient(json_responses=[{"binary_forecasts": _balanced_rows()}], provider="second")
    result = fe.extract_binary_forecasts("Fixed evidence supports a balanced assessment.", primary, min_count=5,
                                        ensemble_client_factory=lambda *args, **kwargs: secondary)
    assert len(primary.calls) == 2 and len(secondary.calls) == 1
    _assert_evidence_prompts(primary.calls + secondary.calls)
    assert all(row["quality_policy"] == fe.BINARY_QUALITY_POLICY for row in result["binary_forecasts"])
    text = fe.render_binary_forecasts_block(result)
    assert "near 0.5 can be justified" in text and "not hedging" not in text


def test_actual_chunked_recovery_requests_never_force_spread(monkeypatch):
    from app.services import forecast_extractor as fe
    monkeypatch.setattr(fe, "_cfg", lambda name, default=None: default)

    class FilteredClient(FakeLLMClient):
        def chat_json(self, messages, **kwargs):
            self.calls.append({"messages": messages})
            if len(messages[0]["content"]) > 16000:
                raise _ContentFilterError(_FILTER_TEXT)
            return {"binary_forecasts": _balanced_rows(3, prefix=f"Chunk {len(self.calls)}")}

    client = FilteredClient()
    result = fbr.extract_binary_forecasts_resilient(_report(6, 3500), client, min_count=5, chunk_chars=4500, max_chunks=3)
    assert result["recovery"]["mode"] == "chunked_after_content_filter"
    assert result["binary_quality"]["policy_version"] == fe.BINARY_QUALITY_POLICY
    _assert_evidence_prompts(client.calls)


def test_explicit_legacy_requests_retain_old_distribution_policy(monkeypatch):
    from app.services import forecast_extractor as fe
    monkeypatch.setattr(fe, "_cfg", lambda name, default=None: "fail" if name == "REPORT_PUBLISH_GATE_MODE" else default)
    client = FakeLLMClient(json_responses=[{"binary_forecasts": _balanced_rows()}, {"binary_forecasts": []}])
    result = fe.extract_binary_forecasts("Same fixed evidence.", client, min_count=5,
                                        binary_quality_policy=fe.LEGACY_BINARY_QUALITY_POLICY)
    assert len(client.calls) == 2
    assert "CONTRARIAN FRAMING" in client.calls[0]["messages"][0]["content"]
    assert "0.05-0.35 range" in client.calls[1]["messages"][0]["content"]
    assert not result["binary_quality"]["passed"]
    assert "not hedging" in fe.render_binary_forecasts_block(result)


class _ContentFilterError(Exception):
    pass


_FILTER_TEXT = ("Error code: 400 - {'contentFilter': [{'level': 1, 'role': 'user'}], 'error': "
                "{'code': '1301', 'message': '系统检测到输入或生成内容可能包含不安全或敏感内容'}}")


def _report(sections=6, size=4000):
    return "\n".join(f"## Section {i}\n" + (f"Paragraph {i} about trade policy. " * (size // 36)) for i in range(sections))


_SCENARIOS = [
    {"name": "Fragile truce holds", "probability": 0.38,
     "resolution_criteria": "By 2027-06-30: average US tariff on Chinese imports is between 30% and 45%",
     "base_rate_anchor": "n=7 episodes", "adjustment_rationale": "regressed from 0.45"},
    {"name": "Deal deepens", "probability": 0.27, "resolution_criteria": "By 2027-06-30: tariff below 30%"},
    {"name": "Collapse into escalation", "probability": 0.2, "resolution_criteria": "By 2027-06-30: tariff above 45%"},
    {"name": "Status quo drift", "probability": 0.15, "resolution_criteria": "By 2027-06-30: no agreement in force"},
]


def _row(statement, prob, theme="trade"):
    return {"statement": statement, "probability": prob, "resolution_criteria": "PIIE average tariff by 2027-06-30 above 40%",
            "theme": theme, "horizon_year": 2027}


# ----------------------------------------------------------------------------- chunking
def test_split_markdown_chunks_packs_sections_and_keeps_head_and_tail():
    md = _report(sections=10, size=3000)
    chunks = fbr.split_markdown_chunks(md, chunk_chars=7000, max_chunks=4)
    assert 1 <= len(chunks) <= 4
    assert chunks[0].startswith("## Section 0")
    assert "## Section 9" in chunks[-1]
    assert all(len(c) <= 7000 for c in chunks)
    assert fbr.split_markdown_chunks("", chunk_chars=5000) == []
    big = "## Only\n" + "x" * 20000
    assert all(len(c) <= 5000 for c in fbr.split_markdown_chunks(big, chunk_chars=5000, max_chunks=0))


# ----------------------------------------------------------------------------- chunked retry
def test_chunked_retry_skips_filtered_chunks_and_merges_rows():
    calls = []

    def extractor(markdown, llm, *, min_count, **kwargs):
        calls.append((len(markdown), min_count))
        if len(markdown) > 10000:
            raise _ContentFilterError(_FILTER_TEXT)                 # the whole dossier is rejected
        if "Section 1" in markdown and "Section 2" not in markdown:
            raise _ContentFilterError(_FILTER_TEXT)                 # one chunk is sensitive
        n = int(markdown.split("## Section ")[1].split("\n")[0])
        rows = [_row(f"Tariff statement {n} above {40 + n}% by 2027-06-30", 0.2 + 0.05 * n),
                _row("Shared statement across chunks", 0.6)]
        return {"binary_forecasts": rows, "binary_quality": {"passed": True},
                "market_comparison": {"comparisons": [{"id": f"m{n}"}]}}

    md = _report(sections=4, size=4500)
    res = fbr.extract_binary_forecasts_resilient(md, FakeLLMClient(), min_count=10, chunk_chars=5000,
                                                 max_chunks=4, extractor=extractor, scenarios=_SCENARIOS,
                                                 themes=["trade"])
    rows = res["binary_forecasts"]
    assert [r["id"] for r in rows] == [f"F{i}" for i in range(1, len(rows) + 1)]
    statements = [r["statement"] for r in rows]
    assert statements.count("Shared statement across chunks") == 1                 # merged by statement key
    assert not any("statement 1 " in s for s in statements)                          # filtered chunk skipped
    assert res["recovery"]["mode"] == "chunked_after_content_filter"
    assert res["recovery"]["filtered_chunks"] == 1 and res["recovery"]["failed_chunks"] == 0
    assert res["recovery"]["primary_error"].startswith("_ContentFilterError")
    assert calls[0][1] == 10 and all(c[1] == 3 for c in calls[1:])                  # per-chunk minimum
    assert len(res["market_comparison"]["comparisons"]) >= 2
    # F1 moves the publication verdict out of the binary sharpness scorecard.
    assert "sharpness" in res["binary_quality"] and "legacy_passed" in res["binary_quality"]


def test_non_filter_errors_propagate_and_empty_results_pass_through():
    def boom(markdown, llm, *, min_count, **kwargs):
        raise RuntimeError("provider down")

    with pytest.raises(RuntimeError):
        fbr.extract_binary_forecasts_resilient("## A\ntext", FakeLLMClient(), min_count=5, extractor=boom)

    def empty(markdown, llm, *, min_count, **kwargs):
        return {"binary_forecasts": [], "binary_quality": {"passed": False}}

    res = fbr.extract_binary_forecasts_resilient("## A\ntext", FakeLLMClient(), min_count=5, extractor=empty)
    assert res["binary_forecasts"] == [] and "recovery" not in res


# ----------------------------------------------------------------------------- scenario fallback
def test_scenario_partition_fallback_is_deterministic_labelled_and_consistent():
    def always_filtered(markdown, llm, *, min_count, **kwargs):
        raise _ContentFilterError(_FILTER_TEXT)

    res = fbr.extract_binary_forecasts_resilient(_report(sections=3), FakeLLMClient(), min_count=10,
                                                 extractor=always_filtered, scenarios=_SCENARIOS,
                                                 horizon_date="2027-06-30", language="English")
    rows = res["binary_forecasts"]
    assert len(rows) == 4 and [r["id"] for r in rows] == ["F1", "F2", "F3", "F4"]
    assert rows[0]["statement"] == 'By 2027-06-30, the realized outcome falls within the scenario "Fragile truce holds".'
    assert rows[0]["probability"] == 0.38 and rows[0]["source"] == "scenario-partition"
    assert rows[0]["theme"] == "scenario" and rows[0]["horizon_year"] == 2027
    assert rows[0]["scenario_membership"]["derivable"] is True
    assert rows[0]["scenario_membership"]["yes_scenarios"] == ["Fragile truce holds"]
    assert rows[0]["criteria_sharp"] is True
    assert rows[0]["base_rate_anchor"] == "n=7 episodes"
    assert res["binary_quality"]["passed"] is False
    assert any("情景分区" in issue for issue in res["binary_quality"]["issues"])
    assert res["recovery"]["mode"] == "scenario_partition_fallback" and res["recovery"]["rows"] == 4
    # the derived rows satisfy the proposition-consistency audit by construction
    audit = audit_proposition_consistency({"scenarios": _SCENARIOS, "binary_forecasts": rows})
    assert audit["passed"] is True and audit["checked"] == 4
    # deterministic
    again = fbr.extract_binary_forecasts_resilient(_report(sections=3), FakeLLMClient(), min_count=10,
                                                   extractor=always_filtered, scenarios=_SCENARIOS,
                                                   horizon_date="2027-06-30", language="English")
    assert json.dumps(again["binary_forecasts"], sort_keys=True) == json.dumps(rows, sort_keys=True)


def test_scenario_partition_rows_in_chinese_and_without_horizon():
    rows = fbr.scenario_partition_binaries(_SCENARIOS[:1], horizon_date=None, language="Chinese")
    assert rows[0]["statement"] == "到预测判定日，实际结果落入情景「Fragile truce holds」。"
    assert rows[0]["horizon_year"] is None
    assert fbr.scenario_partition_binaries([{"name": "", "probability": 0.3}, {"name": "x", "probability": "n/a"}, None]) == []


# ----------------------------------------------------------------------------- truncation lint
_COMPLETE_CELL = ("Average US tariff stays in the 30-45% band; the BIS case-by-case H200 regime survives, "
                  "hemmed in but not reversed; at least one implementation pillar (soybeans, general licences, "
                  "tariff-cut lists) demonstrably incomplete")
_CUT_CELL = ("Average US tariff stays in the 30-45% band; the BIS case-by-case H200 regime survives, hemmed in "
             "but not reversed; at least one implementation pillar (soybeans, general licences, tariff-cut lists) "
             "demonstrably incomplete and the")


def test_complete_cell_ending_after_parenthesis_is_not_truncated_but_width_cuts_are():
    assert rl._ends_mid_clause(_COMPLETE_CELL) is False
    assert rl._ends_mid_clause(_CUT_CELL) is True                                 # dangling "the"
    assert rl._ends_mid_clause("Unbalanced (parenthesis never closed in this very long cell of text") is True
    assert rl._ends_mid_clause("x" * 200) is True                                  # machine-length token
    md = "| Scenario | Criteria |\n| --- | --- |\n| A | " + _COMPLETE_CELL + " |\n| B | " + _CUT_CELL + " |\n"
    flagged = rl.detect_table_cell_truncation(md)
    assert len(flagged) == 1 and flagged[0].endswith("and the")
