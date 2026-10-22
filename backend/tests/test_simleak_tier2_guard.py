"""Tier-2 leakage rewrite with a stub LLM (ADR 0003, S0.5 and its review fix).

The existing repair tests build the agent without an LLM, so Tier-2 never ran
and the undefined-alias regression went unseen.  These tests drive the guard
with canned rewrites and pin accept/reject outcomes.
"""
from __future__ import annotations

from app.config import Config
from app.services.report_agent import ReportAgent


class _StubLLM:
    def __init__(self, reply):
        self.reply = reply
        self.calls = 0

    def chat(self, messages, **_kw):
        self.calls += 1
        return self.reply


def _agent(reply, **over):
    a = ReportAgent.__new__(ReportAgent)
    a.sources = []
    a.research_report = ""
    a.situation_brief = ""
    a._background_block = ""
    a._outline_summary = ""
    a.output_language = "English"
    a.llm = _StubLLM(reply)
    for k, v in over.items():
        setattr(a, k, v)
    return a


PARA = ("Real demand grew 12% in 2025 [S4]. "
        "The simulation shows regulators will approve the merger with a 62% chance by 2028 [S7]. "
        "Supply stays tight through 2027 [S5].")


def test_deleting_the_simulated_sentence_is_accepted():
    a = _agent("Real demand grew 12% in 2025 [S4]. Supply stays tight through 2027 [S5].")
    out = a._simleak_rewrite_paragraph(PARA, "English")
    assert out == "Real demand grew 12% in 2025 [S4]. Supply stays tight through 2027 [S5]."
    assert a.llm.calls == 1


def test_keeping_a_cited_claim_with_all_its_numbers_is_accepted():
    a = _agent("Real demand grew 12% in 2025 [S4]. Regulators will approve the merger with a 62% chance "
               "by 2028 [S7]. Supply stays tight through 2027 [S5].")
    assert a._simleak_rewrite_paragraph(PARA, "English") is not None


def test_kept_but_stripped_claim_is_rejected():
    # The simulated sentence survives (same wording) but its 62% is gone: drift by omission.
    a = _agent("Real demand grew 12% in 2025 [S4]. Regulators will approve the merger by 2028 [S7]. "
               "Supply stays tight through 2027 [S5].")
    assert a._simleak_rewrite_paragraph(PARA, "English") is None


def test_surviving_simulated_sentence_without_citation_is_rejected():
    para = "Real demand grew 12% in 2025 [S4]. The simulation shows regulators will approve the merger by 2028."
    a = _agent("Real demand grew 12% in 2025 [S4]. Regulators will approve the merger by 2028.")
    assert a._simleak_rewrite_paragraph(para, "English") is None


def test_dropping_a_number_from_a_clean_sentence_is_rejected():
    a = _agent("Real demand grew in 2025 [S4]. Supply stays tight through 2027 [S5].")
    assert a._simleak_rewrite_paragraph(PARA, "English") is None


def test_inventing_a_number_is_rejected():
    a = _agent("Real demand grew 12% in 2025 [S4]. Supply stays tight through 2027 [S5], near 95%.")
    assert a._simleak_rewrite_paragraph(PARA, "English") is None


def test_growth_is_rejected():
    a = _agent(PARA + " " + "An extra clause with no digits at all that lengthens the paragraph.")
    assert a._simleak_rewrite_paragraph(PARA, "English") is None


def test_llm_failure_falls_back_to_none():
    class _Boom:
        def chat(self, *a, **k):
            raise RuntimeError("provider down")
    a = _agent(None)
    a.llm = _Boom()
    assert a._simleak_rewrite_paragraph(PARA, "English") is None


def test_repair_pass_with_an_llm_present_rewrites_without_raising(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_SIMLEAK_REPAIR", True, raising=False)
    monkeypatch.setattr(Config, "REPORT_SIMLEAK_MAX_LLM_PARAGRAPHS", 12, raising=False)
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE_MIN_COVERAGE", 0.0, raising=False)
    a = _agent("Solid claim [S1].")
    md = "Solid claim [S1]. The simulation surfaced this in round 2 with 30 actions.\n"
    new_md, info = a._repair_simulation_leakage(md)
    assert info["paragraphs_rewritten"] == 1
    assert "round 2" not in new_md and "Solid claim [S1]." in new_md
    forecast = {"citation_audit": {"coverage": 1.0, "quantitative_claims": 0}, "quality": {}}
    out = a._run_repair_passes("rid_t2", forecast, md, report=None)
    assert "round 2" not in out
    passes = forecast["quality"]["repair"]["passes"]
    assert any(p["dimension"] == "simulation_leakage" and p.get("paragraphs_rewritten") == 1 for p in passes)
