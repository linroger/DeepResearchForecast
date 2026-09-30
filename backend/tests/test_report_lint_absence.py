"""REPORT-4 (F): a typed absence marker copied from a prompt into the report is a leak.

The marker texts (app/utils/absence.py) carry sentinel phrases that appear nowhere
else; report_lint counts them in leakage_hits and final-mode lint deletes the
sentence that carries one.  Pure functions, offline.
"""

from __future__ import annotations

import pytest

from app.services import report_lint as rl
from app.services.report_lint import lint_report
from app.utils import absence


def test_pattern_is_registered():
    assert "absence_marker_leak" in [name for name, _pat in rl.LEAKAGE_PATTERNS]


@pytest.mark.parametrize("phrase", absence.MARKER_SENTINELS)
def test_every_sentinel_is_counted(phrase):
    assert "absence_marker_leak" in rl.leakage_hits(f"Some prose {phrase} here.")


@pytest.mark.parametrize("status", [absence.not_run("x"), absence.empty("x"),
                                    absence.unavailable("x")])
@pytest.mark.parametrize("lang", ["zh", "en"])
def test_every_marker_text_is_a_leak(status, lang):
    assert "absence_marker_leak" in rl.leakage_hits(absence.absence_marker("slot", status, lang))


def test_english_leak_sentence_removed_in_final_mode():
    md = ("## Markets\n\n"
          "Tariff odds sit near 30% [S1]. The market table is not an empty finding. "
          "Analysts expect a rise [S2].\n")
    assert rl.leakage_hits(md).count("absence_marker_leak") == 1
    out, rep = lint_report(md, "English", mode="final")
    assert "not an empty finding" not in out
    assert "Tariff odds sit near 30% [S1]." in out and "Analysts expect a rise [S2]." in out
    assert rep["simulation_mechanics"]["sentences_removed"] >= 1
    assert rep["leakage_flags"] == 0


def test_chinese_leak_sentence_removed_in_final_mode():
    md = ("## 市场\n\n"
          "关税上调的概率约为三成[S1]。预测市场信号不是空结果，不可据此推断任何结论。"
          "分析师预计将继续上升[S2]。\n")
    assert "absence_marker_leak" in rl.leakage_hits(md)
    out, _rep = lint_report(md, "Chinese", mode="final")
    assert "不是空结果" not in out
    assert "关税上调的概率约为三成[S1]。" in out and "分析师预计将继续上升[S2]。" in out


def test_ordinary_absence_wording_is_not_flagged():
    md = "The search found no equivalent market, so no market anchor is shown [S3].\n"
    assert "absence_marker_leak" not in rl.leakage_hits(md)


def test_natural_chinese_absence_of_evidence_prose_is_kept():
    # '不代表现实中不存在' alone is ordinary analytical prose; only the empty marker's full
    # tail ('这是检索结果，不代表现实中不存在') is a sentinel.
    sentence = "未检索到直接证据不代表现实中不存在该风险[S4]。"
    md = "## 风险\n\n" + sentence + "监管机构仍在评估[S5]。\n"
    assert "absence_marker_leak" not in rl.leakage_hits(md)
    out, _rep = lint_report(md, "Chinese", mode="final")
    assert sentence in out


def test_chinese_empty_marker_tail_is_still_a_leak():
    md = ("## 市场\n\n"
          "相关合约已执行检索但未找到可用结果——这是检索结果，不代表现实中不存在。"
          "分析师预计将继续上升[S2]。\n")
    assert "absence_marker_leak" in rl.leakage_hits(md)
    out, _rep = lint_report(md, "Chinese", mode="final")
    assert "这是检索结果" not in out and "分析师预计将继续上升[S2]。" in out
