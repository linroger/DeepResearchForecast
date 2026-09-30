"""REPORT-8 — labelled verified-figures block (REPORT_VERIFIED_FACTS_BLOCK).

With research quantitative rows carrying RESEARCH-4 / REPORT-7 page-check labels
(``verification``), the report background replaces the unlabelled key-metrics table
with a deterministic verified-figures block (verified reported values; verified
projections labelled "not an outcome"; everything else only counted), and the Part-2
synthesis prompt receives the same block plus the "present conflicts side by side,
never reconcile" rule. Tags come only from the report citation index. Knob off, or no
labelled row (legacy engine / reused research) → today's table and prompts byte for
byte. Offline: fake LLM, faked PipelineManager / Gamma, pinned market clock.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import os
import random
import re
import subprocess
import sys
from datetime import date, datetime, timezone

import pytest

from app.config import Config
from app.services import verified_facts as vf
from app.services.report_agent import ReportAgent
from app.utils import prediction_markets as pm
from tests.conftest import FakeLLMClient

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AS_OF = date(2026, 6, 30)
_TAG_TOKEN_RE = re.compile(r"[\[【]\s*S[\d?#][^\]】]*[\]】]")
PART2_RULE = (" When stating an exact figure, use the verified-figures table and keep its [S#]; "
              "if sources conflict, present both with their sources and never a reconciled number.")
PART2_LABEL = "[Verified-on-page figures — exact numbers and their sources]\n"


def _row(metric, **over):
    row = {"metric": metric, "value": "10", "unit": "GW", "as_of_date": "2026-05-01",
           "value_type": "actual", "tier": "S2", "source": f"{metric} source",
           "verification": "verified", "verified": True}
    row.update(over)
    return row


def _no_tags(_row):
    return None


def _build(rows, *, tag_for=_no_tags, lang="zh", max_rows=40, max_chars=6000):
    return vf.build_verified_figures_block(rows, tag_for=tag_for, lang=lang, max_rows=max_rows,
                                           max_chars=max_chars, as_of=AS_OF)


@pytest.fixture
def knob(monkeypatch):
    """Setter for REPORT_VERIFIED_FACTS_BLOCK (the default, on, is set up front)."""
    def _set(on):
        monkeypatch.setattr(Config, "REPORT_VERIFIED_FACTS_BLOCK", on, raising=False)
    _set(True)
    monkeypatch.setattr(Config, "REPORT_VERIFIED_FACTS_MAX_ROWS", 40, raising=False)
    monkeypatch.setattr(Config, "REPORT_VERIFIED_FACTS_MAX_CHARS", 6000, raising=False)
    return _set


# ------------------------------------------------------------------ admission
def _mixed_rows():
    return [
        _row("Installed capacity", source_ref="S1"),
        _row("Capacity outlook", value_type="forecast", target_date="2030-12-31", source="IEA"),
        _row("Grid target", value_type="target", period_end="2035", source="NEA"),
        _row("Unverified figure", verification="unverified", verified=False),
        _row("Weird label", verification="half_checked"),
        _row("Relayed figure", verification="snippet_only", verified=False),
        _row("Orphan figure", verification="none", verified=False),
        {key: value for key, value in _row("Unchecked figure").items()
         if key not in ("verification", "verified")},
        _row("Future actual", future_dated=True),
        _row("Future reported", epistemic_flags=["future_dated_reported"]),
        _row("Untyped figure", value_type=None),
    ]


def test_admission():
    result = _build(_mixed_rows())
    assert [row["metric"] for row in result["rows"]] == ["Installed capacity"]
    assert sorted(row["metric"] for row in result["projections"]) == ["Capacity outlook", "Grid target"]
    labels = {row["metric"]: row["label"] for row in result["projections"]}
    assert labels["Capacity outlook"] == "IEA的预期，目标期 2030-12-31——不是已发生的结果"
    assert labels["Grid target"] == "NEA的预期，目标期 2035——不是已发生的结果"
    assert result["excluded"] == {"unverified": 2, "snippet_only": 1, "none": 1, "unchecked": 1,
                                  "future_dated": 2, "unclassified": 1}
    rendered = result["rendered"]
    assert rendered.startswith("## 已核验指标（研究期在所引网页上核验到数字——引用时保持数值、时点与 [S#]）\n"
                               "核验仅表示该数字出现在所引来源页面，不代表指标口径已人工确认。")
    # unverified 2 + none 1 + unchecked 1 are "未核验"; snippet_only is "仅转述"; the verified
    # rows in neither table (future_dated 2 + unclassified 1) are the third count.
    assert "（本表未收录：未核验 4 条、仅转述 1 条、时点晚于研究时点或无法区分实际与预期 3 条）。" in rendered
    assert ("(left out of this table: 4 unverified, 1 reported only, 3 dated after the research or "
            "not typed as outcome or projection).") in _build(_mixed_rows(), lang="en")["rendered"]
    assert "### 预测/目标值（具名来源的预期，不是已发生的结果）" in rendered
    for excluded in ("Unverified figure", "Weird label", "Relayed figure", "Orphan figure",
                     "Unchecked figure", "Future actual", "Future reported", "Untyped figure"):
        assert excluded not in rendered
    assert result["sha256"] == hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def test_admission_english_and_estimate_years():
    rows = [_row("Revenue", source_ref="S1"),
            _row("Revenue 2030", value_type="estimate", period_end="2030", source="Analyst X")]
    result = _build(rows, lang="English")
    assert result["rendered"].startswith("## Verified-on-page figures (numbers found on the cited page")
    assert "never reconcile them into a new number" in result["rendered"]
    assert "(left out of this table: 0 unverified, 0 reported only)." in result["rendered"]
    assert [row["label"] for row in result["projections"]] == [
        "expectation by Analyst X, target 2030 — not an outcome"]
    assert "| metric | value | unit | as of | tier | source |" in result["rendered"]


def test_rows_without_any_label_render_nothing():
    rows = [{key: value for key, value in _row(f"m{i}").items() if key not in ("verification", "verified")}
            for i in range(3)]
    result = _build(rows)
    assert result["rendered"] == "" and result["sha256"] == ""
    assert result["rows"] == [] and result["projections"] == []
    assert _build(None)["rendered"] == "" and _build("not a list")["rendered"] == ""


def test_labelled_but_nothing_admitted_still_replaces_the_table():
    rows = [_row("A", verification="unverified"), _row("B", verification="snippet_only")]
    rendered = _build(rows)["rendered"]
    assert "（本表未收录：未核验 1 条、仅转述 1 条）。" in rendered     # no third count when it is 0
    assert rendered.endswith("（本次研究没有在所引页面核验通过的数字。）")
    assert "| 指标 |" not in rendered


# ------------------------------------------------------------------ tags
def test_tags_never_invented():
    tag_map = {"S1": {"title": "One", "url": "https://one.example"},
               "S4": {"title": "Four", "url": "https://four.example"},
               "S7": {"title": "Seven", "url": "https://seven.example"}}
    rows = [
        _row("In index", source_ref="S4", source_url="https://four.example", as_of_date="2026-06-01"),
        _row("By url", source_ref="S9", source_url="https://seven.example", as_of_date="2026-05-01"),
        _row("Title only", source_ref="S12", source_url="https://other.example",
             source="Reuters [S12] wire", as_of_date="2026-04-01"),
        _row("Metric [S3] text", source="Plain source", as_of_date="2026-03-01"),
    ]
    result = _build(rows, tag_for=vf.citation_tag_resolver(tag_map))
    sources = {row["metric"]: row["source"] for row in result["rows"]}
    assert sources["In index"] == "[S4]"
    assert sources["By url"] == "[S7]"
    assert sources["Title only"] == "Reuters wire"
    assert sources["Metric text"] == "Plain source"
    rendered = result["rendered"]
    assert set(re.findall(r"\[S\d+\]", rendered)) == {"[S4]", "[S7]"}
    assert all(token in ("[S4]", "[S7]", "[S#]") for token in _TAG_TOKEN_RE.findall(rendered))


def test_tag_resolver_contract():
    resolve = vf.citation_tag_resolver({"S1-a": {"url": "https://a.example"},
                                        "S2": {"url": "https://b.example"},
                                        "S3": {"url": "https://b.example"},
                                        "S4": {"title": "No url"}})
    assert resolve({"source_ref": "S1", "source_url": "https://a.example"}) == "S1-a"
    assert resolve({"source_ref": "[s2]"}) == "S2"
    assert resolve({"source_ref": "S2", "source_url": "https://b.example"}) == "S2"
    assert resolve({"source_url": "https://b.example"}) == "S2"      # first in index order
    assert resolve({"source_ref": "S9"}) is None
    # A ref whose indexed url contradicts the row's own url (a renumbered ledger) is not
    # trusted: the row's url decides, and a url outside the index resolves to nothing.
    assert resolve({"source_ref": "S2", "source_url": "https://a.example"}) == "S1-a"
    assert resolve({"source_ref": "S2", "source_url": "https://moved.example"}) is None
    assert resolve({"source_ref": "S4", "source_url": "https://any.example"}) == "S4"   # nothing to contradict
    assert resolve({}) is None
    assert vf.citation_tag_resolver(None)({"source_ref": "S1"}) is None


def test_non_tag_from_tag_for_is_never_rendered_as_a_tag():
    result = _build([_row("A", source="Agency")], tag_for=lambda row: "S4]; see [S99")
    assert result["rows"][0]["source"] == "Agency"
    assert "S99" not in result["rendered"] and "[S4]" not in result["rendered"]


# ------------------------------------------------------------------ determinism & caps
def _cap_rows():
    rows = [_row(f"current {i:02d}", tier=("S1", "S2", "S3", "", "S4")[i % 5],
                 as_of_date=f"2026-0{1 + i % 6}-{10 + i:02d}") for i in range(10)]
    rows += [_row(f"stale {i}", as_of_date=f"2024-0{i + 1}-01", is_stale=True) for i in range(2)]
    rows.append(_row("stale by days", as_of_date="2025-01-01", staleness_days=400))
    rows += [_row(f"projection {i}", value_type="forecast", target_date=f"203{i}",
                  as_of_date=f"2026-0{i + 1}-15", source=f"Agency {i}") for i in range(3)]
    return rows


def test_deterministic_and_caps():
    rows = _cap_rows()
    digest = _build(rows)["sha256"]
    for seed in range(5):
        shuffled = list(rows)
        random.Random(seed).shuffle(shuffled)
        assert _build(shuffled)["sha256"] == digest
    assert _build(rows + [dict(rows[0])])["sha256"] == digest       # an exact duplicate row renders once

    full = _build(rows)
    assert len(full["rows"]) == 13 and len(full["projections"]) == 3 and full["omitted"] == 0
    tiers = [row["tier"] for row in full["rows"] if not row["stale"]]
    order = {"S1": 0, "S2": 1, "S3": 2, "": 3, "S4": 4}
    assert tiers == sorted(tiers, key=order.__getitem__)
    assert "⚠ = 陈旧数据（研究标记为陈旧，或距研究时点逾 180 天）" in full["rendered"]

    # Row cap: projections go first, then stale rows, then the oldest.
    capped = _build(rows, max_rows=11)
    assert capped["projections"] == [] and capped["omitted"] == 5
    assert [row["metric"] for row in capped["rows"] if row["stale"]] == ["⚠ stale by days"]
    assert capped["rendered"].endswith("…（另有 5 条已核验数字因篇幅上限未列出）")
    oldest_current = _build(rows, max_rows=9)
    kept = {row["metric"] for row in oldest_current["rows"]}
    current = sorted((row for row in rows if row["metric"].startswith("current")),
                     key=lambda row: row["as_of_date"])
    assert current[0]["metric"] not in kept and all(row["metric"] in kept for row in current[1:])

    # Char cap: one character short drops exactly the lowest-priority row (the oldest projection).
    trimmed = _build(rows, max_chars=len(full["rendered"]) - 1)
    assert len(trimmed["rendered"]) <= len(full["rendered"]) - 1
    assert trimmed["omitted"] == 1 and len(trimmed["rows"]) == 13
    assert sorted(row["metric"] for row in trimmed["projections"]) == ["projection 1", "projection 2"]

    # The header and rule are never cut: a tiny cap keeps them and drops every row.
    tiny = _build(rows, max_chars=10)
    assert tiny["rows"] == [] and tiny["projections"] == [] and tiny["omitted"] == 16
    assert tiny["rendered"].startswith("## 已核验指标") and "…（另有 16 条" in tiny["rendered"]


def test_near_duplicates_are_order_independent():
    """Rows with the same cells but different as-of dates render once, and which one is kept
    (it decides the sort position and what the caps keep) never depends on input order."""
    rows = [
        _row("Outlook", value_type="forecast", target_date="2030", source="IEA", as_of_date="2026-01-01"),
        _row("Outlook", value_type="forecast", target_date="2030", source="IEA", as_of_date="2026-06-01"),
        _row("Other outlook", value_type="forecast", target_date="2031", source="IEA", as_of_date="2026-03-01"),
        # The same reported figure, dated only through period_end in one copy.
        _row("Capacity", as_of_date="", period_end="2026-05-01"),
        _row("Capacity", as_of_date="2026-05-01"),
        _row("Older figure", as_of_date="2026-03-01"),
    ]
    full = {_build(list(perm))["sha256"] for perm in itertools.permutations(rows)}
    assert len(full) == 1
    result = _build(rows)
    assert [row["metric"] for row in result["rows"]] == ["Capacity", "Older figure"]
    assert [row["metric"] for row in result["projections"]] == ["Outlook", "Other outlook"]
    # Under a cap the newest copy's date decides: "Outlook" (2026-06-01) outranks "Other outlook".
    for cap in (1, 3):
        kept = {json.dumps([_build(list(perm), max_rows=cap)[key] for key in ("rows", "projections")])
                for perm in itertools.permutations(rows)}
        assert len(kept) == 1
    one_projection = _build([rows[1], rows[0], rows[2]], max_rows=1)
    assert [row["metric"] for row in one_projection["projections"]] == ["Outlook"]
    assert _build([rows[0], rows[2]], max_rows=1)["projections"][0]["metric"] == "Other outlook"


def test_cells_are_table_safe_and_capped():
    result = _build([_row("x|y " + "long " * 40, value="1\n2")])
    [row] = result["rows"]
    assert row["metric"].startswith("x\\|y") and len(row["metric"]) == 90 and row["metric"].endswith("…")
    assert row["value"] == "1 2"


# ------------------------------------------------------------------ report agent wiring
_SOURCES = [{"title": "Energy agency annual review", "url": "https://agency.example/review", "tier": "S1"},
            {"title": "Wire story", "url": "https://wire.example/story", "tier": "S3"}]


def _labelled_rows():
    return [_row("Installed capacity", source_ref="S1", source_url="https://agency.example/review"),
            _row("Capacity outlook", value_type="forecast", target_date="2030", source="Agency",
                 source_ref="S2", source_url="https://wire.example/story"),
            _row("Unverified figure", verification="unverified")]


def _unlabelled_rows():
    return [{key: value for key, value in row.items() if key not in ("verification", "verified")}
            for row in _labelled_rows()]


def _bare(**over):
    a = ReportAgent.__new__(ReportAgent)
    attrs = {"scenario_label": "", "situation_brief": "Situation brief.",
             "actors": {"as_of_date": AS_OF.isoformat()}, "sources": list(_SOURCES),
             "research_report": "", "quantitative": None, "output_language": "Chinese"}
    attrs.update(over)
    for key, value in attrs.items():
        setattr(a, key, value)
    return a


def test_background_fallback(knob, monkeypatch):
    labelled = _bare(quantitative=_labelled_rows())
    block = labelled._build_background_block()
    assert "## 已核验指标" in block and "关键量化指标" not in block
    assert "| Installed capacity | 10 | GW | 2026-05-01 | S2 | [S1] |" in block
    assert labelled._verified_figures["rendered"] in block

    # Unlabelled research: the key-metrics table, byte for byte what the knob-off path renders.
    unlabelled = _bare(quantitative=_unlabelled_rows())
    monkeypatch.setattr(ReportAgent, "_build_sources_index",
                        lambda self: pytest.fail("unlabelled rows must not build a tag map"))
    legacy_on = unlabelled._build_background_block()
    assert unlabelled._verified_figures is None
    knob(False)
    legacy_off = _bare(quantitative=_unlabelled_rows())._build_background_block()
    assert legacy_on == legacy_off
    assert _bare(quantitative=_unlabelled_rows())._build_key_metrics_block() in legacy_off
    assert "## 关键量化指标" in legacy_off and "已核验指标" not in legacy_off

    # Knob off with labelled rows: the legacy table.
    off = _bare(quantitative=_labelled_rows())
    off_block = off._build_background_block()
    assert "## 关键量化指标" in off_block and "已核验指标" not in off_block
    assert getattr(off, "_verified_figures", None) is None


def test_background_block_degrades_to_the_legacy_table(knob, monkeypatch):
    def _boom(*_args, **_kwargs):
        raise RuntimeError("renderer failed")

    monkeypatch.setattr(vf, "build_verified_figures_block", _boom)
    agent = _bare(quantitative=_labelled_rows())
    block = agent._build_background_block()
    assert "## 关键量化指标" in block and "已核验指标" not in block
    assert agent._verified_figures is None


def _constructed(**kwargs):
    return ReportAgent(graph_id="g1", simulation_id="sim_rep8",
                       simulation_requirement="Will installed capacity exceed 20 GW by 2030?",
                       llm_client=FakeLLMClient(responses=["Synthesis paragraph. " * 20]),
                       zep_tools=object(), situation_brief="Situation brief.",
                       actors={"as_of_date": AS_OF.isoformat()}, sources=list(_SOURCES), **kwargs)


def test_same_block_in_every_section_and_part2_prompt(knob):
    agent = _constructed(quantitative=_labelled_rows())
    rendered = agent._verified_figures["rendered"]
    assert rendered and agent._verified_figures["sha256"] == hashlib.sha256(rendered.encode()).hexdigest()
    assert set(agent._citation_index) == {"S1", "S2"}      # __init__ order unchanged
    prompts = [agent._prepend_research_background("PROMPT", section_title=title)
               for title in ("Background and timeline", "Risks", "Scenario forecasts")]
    for prompt in prompts:
        assert prompt.count(rendered) == 1 and "关键量化指标" not in prompt
    agent._forecast_spine = None
    agent._market_pack = ""
    assert agent._build_part2_synthesis("## Outlook\nCapacity grows steadily.\n")
    part2 = agent.llm.calls[-1]["messages"][0]["content"]
    assert part2.count(rendered) == 1 and PART2_RULE in part2
    assert set(re.findall(r"\[S\d+\]", rendered)) <= {f"[{tag}]" for tag in agent._citation_index}


def test_constructor_survives_a_failing_renderer(knob, monkeypatch):
    def _boom(*_args, **_kwargs):
        raise RuntimeError("renderer failed")

    monkeypatch.setattr(vf, "build_verified_figures_block", _boom)
    agent = _constructed(quantitative=_labelled_rows())
    assert agent._verified_figures is None
    assert "## 关键量化指标" in agent._background_block


def _part2_prompt(verified=None, **over):
    agent = _bare(llm=FakeLLMClient(responses=["Synthesis paragraph. " * 20]), output_language="English",
                  simulation_requirement="", _forecast_spine=None, _market_pack="", **over)
    if verified is not None:
        agent._verified_figures = verified
    assert agent._build_part2_synthesis("## Outlook\nCapacity grows steadily.\n")
    return agent.llm.calls[-1]["messages"][0]["content"]


def test_part2_injection(knob):
    verified = _build(_labelled_rows(), lang="English")
    absent = _part2_prompt()
    with_block = _part2_prompt(verified)
    assert with_block == (absent.replace("the real world.\n\n", "the real world." + PART2_RULE + "\n\n", 1)
                          + "\n\n" + PART2_LABEL + verified["rendered"])
    # No block (never built, empty, or the knob off) → the prompt is byte-identical.
    assert _part2_prompt(_build(_unlabelled_rows())) == absent
    knob(False)
    assert _part2_prompt(verified) == absent
    assert PART2_RULE not in absent and "Verified-on-page" not in absent


def test_part2_without_other_inputs_is_still_skipped(knob):
    agent = _bare(llm=FakeLLMClient(), output_language="English", simulation_requirement="",
                  _forecast_spine=None, _market_pack="",
                  _verified_figures=_build(_labelled_rows(), lang="English"))
    assert agent._build_part2_synthesis("") == ""
    assert agent.llm.calls == []


# ------------------------------------------------------------------ semantic citation regression
def test_semantic_support_regression():
    """A figure beyond the 1,200-char excerpt cut is supported only through its supports window."""
    excerpt = ("Operators across the region continued commissioning new wind and solar assets while "
               "transmission upgrades lagged behind schedule in several provinces and ") * 12
    assert len(excerpt) > 1200 and "." not in excerpt
    excerpt += "installed renewable capacity reached 42.7 gigawatts at the end of the year"
    window = "Installed renewable capacity reached 42.7 gigawatts at the end of the year, the agency said."
    md = "Installed renewable capacity reached 42.7 gigawatts in the region [S1]."

    def _repair(supports):
        source = {"title": "Regional energy review", "url": "https://agency.example/review",
                  "excerpt": excerpt, "supports": supports}
        agent = ReportAgent.__new__(ReportAgent)
        agent.sources = [source]
        agent._citation_index = {"S1": source}
        return agent._repair_semantic_citations(md)

    kept, info = _repair([window])
    assert "[S1]" in kept and info["kept"] == 1 and info["stripped"] == 0
    stripped, info = _repair([])
    assert "[S1]" not in stripped and info["stripped"] == 1


# ------------------------------------------------------------------ EVAL-6 market provenance
class _FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_market_rows_carry_eval6_provenance(monkeypatch, tmp_path):
    """After _load_prediction_markets every row has EVAL-6's snapshot_as_of; only the
    successfully requoted row has quoted_at (REPORT-8 adds no market field of its own)."""
    from app.services.pipeline_orchestrator import PipelineManager

    quote_time = datetime(2026, 9, 30, 9, 15, tzinfo=timezone.utc)
    snapshot_as_of = "2026-09-28T06:00:00+00:00"
    monkeypatch.setenv("PREDICTION_MARKETS_ENABLED", "true")
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_ENABLED", True, raising=False)
    monkeypatch.setattr(Config, "MARKET_ANCHOR_PRICE_TIME", True, raising=False)
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_REQUOTE", True, raising=False)
    monkeypatch.setattr(pm, "_backoff_sleep", lambda attempt: None)
    monkeypatch.setattr(pm, "market_clock_now", lambda: quote_time)
    fresh = {"id": "m1", "question": "Will m1 happen?", "closed": False, "outcomes": '["Yes","No"]',
             "outcomePrices": json.dumps(["0.4100", "0.5900"])}
    monkeypatch.setattr(pm.httpx, "get", lambda *a, **k: _FakeResponse([fresh]))
    monkeypatch.setattr(PipelineManager, "list_pipelines", classmethod(lambda cls: [{"pipeline_id": "p1"}]))
    monkeypatch.setattr(PipelineManager, "load", classmethod(
        lambda cls, pid: {"simulation_id": "sim1", "handoff_dir": str(tmp_path)}))
    markets = [{"market_id": mid, "exchange": "polymarket", "question": f"Will {mid} happen?",
                "implied_yes_prob": 0.34, "end_date": "2026-12-31T00:00:00Z", "volume": 9000}
               for mid in ("m1", "m2")]
    (tmp_path / "prediction_markets.json").write_text(
        json.dumps({"as_of": snapshot_as_of, "markets": markets}), encoding="utf-8")
    agent = _bare(simulation_id="sim1", simulation_requirement="q", actors={}, hindcast=None,
                  _hindcast_pin_cache=None, _market_pack="", _prediction_markets=[], _markets_stale=False)
    rows = {row["market_id"]: row for row in agent._load_prediction_markets()}
    assert {mid: row["snapshot_as_of"] for mid, row in rows.items()} == {"m1": snapshot_as_of,
                                                                         "m2": snapshot_as_of}
    assert rows["m1"]["quoted_at"] == quote_time.isoformat() and rows["m1"]["implied_yes_prob"] == 0.41
    assert rows["m2"]["requote_failed"] is True and "quoted_at" not in rows["m2"]
    assert all("price_at_research_as_of" not in row for row in rows.values())


# ------------------------------------------------------------------ knobs
_DEFAULTS_CHILD = r"""
import json, os
import dotenv
dotenv.load_dotenv = lambda *a, **k: False
for key in ("REPORT_VERIFIED_FACTS_BLOCK", "REPORT_VERIFIED_FACTS_MAX_ROWS", "REPORT_VERIFIED_FACTS_MAX_CHARS"):
    os.environ.pop(key, None)
from app.config import Config
print("<<<JSON>>>" + json.dumps([Config.REPORT_VERIFIED_FACTS_BLOCK, Config.REPORT_VERIFIED_FACTS_MAX_ROWS,
                                 Config.REPORT_VERIFIED_FACTS_MAX_CHARS]))
"""


def test_knob_defaults_and_documentation():
    names = ("REPORT_VERIFIED_FACTS_BLOCK", "REPORT_VERIFIED_FACTS_MAX_ROWS", "REPORT_VERIFIED_FACTS_MAX_CHARS")
    env = {key: value for key, value in os.environ.items() if key not in names}
    proc = subprocess.run([sys.executable, "-c", _DEFAULTS_CHILD], cwd=_BACKEND, env=env,
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    [payload] = [line for line in proc.stdout.splitlines() if line.startswith("<<<JSON>>>")]
    assert json.loads(payload[len("<<<JSON>>>"):]) == [True, 40, 6000]
    with open(os.path.join(os.path.dirname(_BACKEND), ".env.example"), encoding="utf-8") as handle:
        text = handle.read()
    for line in ("# REPORT_VERIFIED_FACTS_BLOCK=true ", "# REPORT_VERIFIED_FACTS_MAX_ROWS=40 ",
                 "# REPORT_VERIFIED_FACTS_MAX_CHARS=6000 "):
        assert line in text
