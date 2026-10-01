"""RESEARCH-9: v3 QA citation stats (detection-only telemetry).

RESEARCH_V3_CITATION_STATS (default true) makes the QA phase record qa.json
``citation_stats`` (schema v3-citation-stats/1): markers before QA and in the
published body, the orphan markers positional renumbering drops (occurrences,
distinct sids, a sample), stale citation groups, cited fetched vs snippet
sources and the snippet marker share, unused fetched pages, writer
bibliographies and prompt-scaffold echo lines, and prose numbers that no
VERIFIED / REPORTED finding, cited fetched page or cited snippet traces.  It
is mirrored into meta.research_qa and meta.research_quality.  Nothing is
stripped: research_report.md and sources.json are byte-identical with the flag
on or off, and off writes no key.

Offline: the scripted model, injected search/fetch and real bridge of
``test_research_engine_v3``.
"""

from __future__ import annotations

import json
import os
import random
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import test_research_engine_v3 as v3

# The shared fixtures (hermetic env, real bridge with network steps stubbed).
_hermetic_env = v3._hermetic_env
bridge = v3.bridge
lr = v3.lr
rg = v3.rg
po = v3.po

BACKEND = Path(__file__).resolve().parents[1]
ORPHAN_SENTENCE = "Independent tallies put the build-out well ahead of the agency schedule [S999]."
# 8,642 is on no page, in no finding and in no search snippet; 40 is on every
# fetched page (v3.page_text) but in no finding.
UNTRACED_SENTENCE = "Survey respondents counted 8,642 idle racks across the sampled campuses"
PAGE_SENTENCE = "Grid connection queues exceed 40 months in several regions"


class CitationWorld(v3.World):
    """The standard world, plus a Market Baseline writer that cites a source
    the ledger never had ([S999]) and appends its own list-shaped
    ``### References`` block, and an executive summary that opens with an
    untraced figure and a figure only a fetched page states."""

    def writer(self, call):
        reply = super().writer(call)
        text = str(reply.content)
        heading = "## Market Baseline\n\n"
        if heading not in text:
            return reply
        start = text.index(heading) + len(heading)
        end = text.find("\n\n## ", start)
        end = len(text) if end < 0 else end
        sid = re.search(r"\[S(\d+)\]", text[start:end]).group(1)
        section = (f"{ORPHAN_SENTENCE}\n\n{text[start:end]}\n\n### References\n\n"
                   f"- [S{sid}] Capacity report of the national agency\n"
                   "- https://www.agency1.org/data/capacity-report")
        return v3.ai(text[:start] + section + text[end:], out=1500)

    def exec_summary(self, call):
        reply = super().exec_summary(call)
        text = str(reply.content)
        sid = (re.findall(r"\[S(\d+)\]", text) or ["1"])[0]
        heading, body = text.split("\n\n", 1)
        return v3.ai(f"{heading}\n\n{UNTRACED_SENTENCE} [S{sid}]. {PAGE_SENTENCE} [S{sid}]. {body}")


def _run(tmp_path: Path, bridge, monkeypatch, name: str, *, stats: bool | None):
    """One deterministic engine run in ``tmp_path/name``; ``stats`` None
    leaves RESEARCH_V3_CITATION_STATS unset (the default)."""
    monkeypatch.setenv("RESEARCH_LINEAR_WORKERS", "1")   # deterministic runs: the bytes compare
    if stats is None:
        monkeypatch.delenv("RESEARCH_V3_CITATION_STATS", raising=False)
    else:
        monkeypatch.setenv("RESEARCH_V3_CITATION_STATS", "true" if stats else "false")
    rc, meta, plog, model, out = v3.run_engine(tmp_path, bridge, CitationWorld(), out_dir=tmp_path / name)
    assert rc == 0 and meta["status"] == "completed", meta.get("error")
    return meta, plog, out


def _read(out: Path, name: str):
    return json.loads((out / name).read_text(encoding="utf-8"))


# ================================================================ renumber_citations

def test_renumber_citations_reports_every_dropped_marker():
    dropped: list[int] = []
    text, order = lr.renumber_citations("In [2024] it rose [S99] [S3]", {3}.__contains__, dropped=[])
    assert "[2024]" in text and "[S99]" not in text and order == [3]
    text, order = lr.renumber_citations("In [2024] it rose [S99] [S3]", {3}.__contains__, dropped)
    assert dropped == [99] and text == "In [2024] it rose [S1]"
    # One ledger sid per dropped occurrence, in text order.
    dropped = []
    lr.renumber_citations("a [S99] b [S7] c [S99] d [S3]", {3}.__contains__, dropped)
    assert dropped == [99, 7, 99]


@pytest.mark.parametrize("text", [
    "In [2024] it rose [S99] [S3]",
    "Plain prose with no markers at all.",
    "  Lead [S5]  spaces [S12], kept [S5]; dropped [S8] .\n[S99]\n- item [S12]",
])
def test_renumber_citations_without_dropped_is_byte_identical(text):
    known = {3, 5, 12}.__contains__
    assert lr.renumber_citations(text, known) == lr.renumber_citations(text, known, None)
    assert lr.renumber_citations(text, known, []) == lr.renumber_citations(text, known)


# ================================================================ detectors

def test_writer_bibliographies_counts_only_list_shaped_reference_blocks():
    assert lr.writer_bibliographies("### References\n\n- [S1] A report\n- https://x.org/a\n") == 1
    assert lr.writer_bibliographies("#### Sources ####\n1. First\n2) Second\n[S3] Third\nwww.x.org/b\n") == 1
    assert lr.writer_bibliographies("**Bibliography**\n* One\n\n* Two\n") == 1
    assert lr.writer_bibliographies("参考文献：\n- 来源一\n") == 1
    assert lr.writer_bibliographies("References:\n- a\n## Next\nprose after\n### Works cited\n- b\n") == 2
    # Not a writer bibliography: an H2 (the engine's own heading level), a
    # label that is no exact references key, a block with a prose line, an
    # empty block, a mid-sentence label and anything inside a code fence.
    assert lr.writer_bibliographies("## References\n- [S1] A\n") == 0
    assert lr.writer_bibliographies("### Referenced works\n- a\n") == 0
    assert lr.writer_bibliographies("### Sources\n- a\nThe agency said so.\n") == 0
    assert lr.writer_bibliographies("### Sources\n\n## Next\n- a\n") == 0
    assert lr.writer_bibliographies("The sources: several agencies.\n- a\n") == 0
    assert lr.writer_bibliographies("```\n### References\n- a\n```\n") == 0
    assert lr.writer_bibliographies("### References\n- a\n```\n- b\n```\n") == 0


def _bibliographies_by_definition(text: str) -> int:
    """The detector's definition read literally (quadratic): every opener's
    block to the next heading, re-read from the next line when it fails."""
    lines = text.splitlines()
    fenced = lr._fenced_lines(lines)
    found = i = 0
    while i < len(lines):
        label = None if fenced[i] else lr._bibliography_label(lines[i])
        if label is None or lr._norm_key(label) not in lr._REFERENCE_HEADING_KEYS:
            i += 1
            continue
        end = i + 1
        while end < len(lines) and (fenced[end] or not lr._ANY_HEADING_RE.match(lines[end])):
            end += 1
        items = [j for j in range(i + 1, end) if lines[j].strip()]
        if items and all(not fenced[j] and lr._BIBLIOGRAPHY_ITEM_RE.match(lines[j]) for j in items):
            found, i = found + 1, end
        else:
            i += 1
    return found


def test_writer_bibliographies_match_their_definition():
    vocab = ["### References", "#### Sources ####", "## Next", "**Bibliography**", "References:", "Sources:",
             "- Sources:", "1. References:", "参考文献：", "- [S1] item", "* item", "2) second", "[S3] third",
             "https://x.org/a", "", "The agency said so.", "```", "~~~", "### Referenced works"]
    rng = random.Random(9)
    texts = ["\n".join(rng.choice(vocab) for _ in range(rng.randint(0, 12))) for _ in range(3000)]
    assert sum(1 for text in texts if _bibliographies_by_definition(text)) > 300
    for text in texts:
        assert lr.writer_bibliographies(text) == _bibliographies_by_definition(text), text


class _CountingPattern:
    """A compiled pattern that counts its ``match`` calls."""

    def __init__(self, pattern):
        self.pattern, self.calls = pattern, 0

    def match(self, *args, **kwargs):
        self.calls += 1
        return self.pattern.match(*args, **kwargs)


@pytest.mark.parametrize("tail, expected", [("", 0), ("\n- [S1] a", 1), ("\nThe agency said so.", 0)])
def test_writer_bibliographies_is_linear_in_repeated_openers(monkeypatch, tail, expected):
    """A writer repetition loop of opener lines: every failing block resumes at
    its first non-list line, so each line is read a bounded number of times."""
    heading = _CountingPattern(lr._ANY_HEADING_RE)
    item = _CountingPattern(lr._BIBLIOGRAPHY_ITEM_RE)
    monkeypatch.setattr(lr, "_ANY_HEADING_RE", heading)
    monkeypatch.setattr(lr, "_BIBLIOGRAPHY_ITEM_RE", item)
    lines = 5000
    assert lr.writer_bibliographies("\n".join(["Sources:"] * lines) + tail) == expected
    assert heading.calls + item.calls <= 4 * (lines + 1)


def test_scaffold_echo_lines_are_exact_full_lines():
    text = "\n".join([
        "SOURCE INDEX", "  EVIDENCE DIGEST  ", "SECTION WRITING TASK", "RUN BRIEF",
        f"{rg.UNTRUSTED_BEGIN} — research evidence", rg.UNTRUSTED_END, lr.BRIEF_REFERENCES_LINE,
        "The SOURCE INDEX lists sources.", "RUN BRIEF (planning stage)", "- §1 Market Baseline",
    ])
    assert lr.scaffold_echo_lines(text) == 7
    assert lr.scaffold_echo_lines("") == 0


def test_brief_references_line_is_the_rendered_outline_line():
    assert lr.BRIEF_REFERENCES_LINE == "- [References: generated by the engine from the citation markers]"


def test_untraced_numbers_read_prose_as_verified_findings_are_read():
    body = "\n".join([
        "# Question with 250 GW in 2027",
        "## Section 7",
        "Capacity reached 176 GW [S1]. Survey counted 8,642 racks [S2].",
        "- Growth of 12% a year, see [link 555](https://x.org/report-777) and https://y.org/p/9999",
        "```",
        "code 31415",
        "```",
        "| Metric | 4,321 |",
    ])
    sentences = lr.prose_sentences(body)
    assert sentences == ["Capacity reached 176 GW [S1].", "Survey counted 8,642 racks [S2].",
                         "Growth of 12% a year, see link 555 and", "| Metric | 4,321 |"]
    traced = lr.page_number_set("Installed 176 GW; demand up 12% per year; 555 sites")
    assert lr.untraced_numbers(sentences, traced) == [("Survey counted 8,642 racks [S2].", ["8642"]),
                                                      ("| Metric | 4,321 |", ["4321"])]
    # 12 on a page but not as a percentage does not trace "12%".
    assert lr.untraced_numbers(["Growth of 12% a year."], lr.page_number_set("12 sites")) == \
        [("Growth of 12% a year.", ["12"])]


def _stats_engine(rows: list[dict], pages: dict[int, str], *, shell_detection: bool = True,
                  stored_shells: dict[int, str] | None = None, weights: tuple[int, ...] = ()):
    """The engine state _unused_fetched_sids / _traced_numbers read, nothing more."""
    engine = SimpleNamespace(
        ledger=SimpleNamespace(rows=lambda: list(rows), get={row["sid"]: row for row in rows}.get),
        tools=SimpleNamespace(page_text=pages.get), shell_detection=shell_detection,
        stored_shells=dict(stored_shells or {}), records={},
        plan=SimpleNamespace(scenarios=[SimpleNamespace(weight=weight) for weight in weights]))
    engine._published_page = lambda sid, row: lr._Engine._published_page(engine, sid, row)
    engine.page_numbers = lambda sid: lr.page_number_set(pages.get(sid) or "")
    return engine


SHELL_PAGE = "Title: Loading\n\nMarkdown Content:\n"


def test_unused_fetched_sids_read_fetched_as_sources_json_publishes_it(monkeypatch):
    monkeypatch.setattr(rg, "_extraction_failure_reason",
                        lambda text: "empty_extraction" if text == SHELL_PAGE else None)
    rows = [{"sid": 1, "fetched": True}, {"sid": 2, "fetched": True}, {"sid": 3, "fetched": True},
            {"sid": 4, "fetched": False}, {"sid": 5, "fetched": False}, {"sid": 6, "fetched": True}]
    pages = {1: "Cited page with 176 GW.", 2: "Uncited page with 40 months.", 3: SHELL_PAGE, 6: SHELL_PAGE}
    engine = _stats_engine(rows, pages, stored_shells={5: "empty_extraction"})
    # 1 is cited; 3 is an uncited shell (sources.json would publish it as a
    # snippet) and 6 a cited one; 4 and 5 were never fetched.
    assert lr._Engine._unused_fetched_sids(engine, {1, 6}) == [2]
    assert lr._Engine._published_page(engine, 6, rows[5])[0] is False
    # Without shell detection sources.json publishes a shell as fetched: so do the stats.
    engine = _stats_engine(rows, pages, shell_detection=False)
    assert lr._Engine._unused_fetched_sids(engine, {1, 6}) == [2, 3]


def test_scenario_weights_trace_only_as_percentages():
    engine = _stats_engine([], {}, weights=(50, 35, 15))
    traced = lr._Engine._traced_numbers(engine, [], set())
    assert {"%50", "%35", "%15"} <= traced and not {"35", "=35", "50", "=50"} & traced
    sentences = ["The base case holds at 35%.", "It stays near 50 percent.", "The agency counted 35 new plants."]
    assert lr.untraced_numbers(sentences, traced) == [("The agency counted 35 new plants.", ["35"])]


# ================================================================ engine run

def test_engine_run_records_citation_stats_and_changes_no_published_byte(tmp_path, bridge, monkeypatch):
    monkeypatch.setattr(lr, "UNTRACED_SAMPLE", 1000)      # every untraced sentence in the sample
    meta_off, _, out_off = _run(tmp_path, bridge, monkeypatch, "off", stats=False)
    meta_on, _, out_on = _run(tmp_path, bridge, monkeypatch, "on", stats=None)

    # Detection only: the published report and sources are the same bytes.
    for name in ("research_report.md", "sources.json"):
        assert (out_on / name).read_bytes() == (out_off / name).read_bytes(), name
    report = (out_on / "research_report.md").read_text(encoding="utf-8")
    assert "[S999]" not in report and "### References" in report   # renumbering dropped it; the block stays

    qa = _read(out_on, "v3/qa.json")
    stats = qa["citation_stats"]
    assert stats["schema"] == "v3-citation-stats/1" and stats["policy"] == "labelled"
    assert stats["n_orphans_stripped"] >= 1 and 999 in stats["orphan_ledger_sids"]
    assert stats["n_orphan_sids_distinct"] <= stats["n_orphans_stripped"]
    assert stats["writer_bibliographies_detected"] == 1
    assert stats["scaffold_echo_lines_detected"] == 0

    # Marker accounting against the published body and sources.json.
    body = lr.strip_references(report)
    sources = _read(out_on, "sources.json")
    assert stats["markers_final"] == len(re.findall(r"\[S\d+\]", body))
    # The world writes canonical markers only: renumbering is the only marker loss.
    assert stats["markers_pre_qa"] == stats["markers_final"] + stats["n_orphans_stripped"]
    assert stats["n_stale_groups_stripped"] == 0
    assert stats["cited_sources"] == len(sources) == len(qa["citation_order"])
    assert stats["cited_fetched"] + stats["cited_snippet"] == len(sources)
    assert stats["cited_fetched"] == sum(1 for row in sources if row["source_origin"] == "fetched")
    snippet_positions = {i for i, row in enumerate(sources, 1) if row["source_origin"] != "fetched"}
    markers = [int(n) for n in re.findall(r"\[S(\d+)\]", body)]
    assert stats["snippet_marker_share"] == round(
        sum(1 for n in markers if n in snippet_positions) / len(markers), 4)
    ledger = _read(out_on, "v3/sources_ledger.json")
    unused = [row["sid"] for row in ledger if row.get("fetched") and row["sid"] not in qa["citation_order"]]
    assert stats["unused_fetched_sids"] == {"count": len(unused), "sample": unused[:20]}

    # Untraced numbers: the writer's 8,642 counts, the fetched page's 40 does not
    # (no finding states 40: the cited page traces it).
    untraced = stats["untraced_prose_numbers"]
    sample = untraced["sample"]
    assert untraced["sentences"] == len(sample) >= 1
    assert untraced["tokens"] == sum(len(row["numbers"]) for row in sample)
    assert any(UNTRACED_SENTENCE in row["sentence"] and row["numbers"] == ["8642"] for row in sample)
    assert not any(PAGE_SENTENCE in row["sentence"] for row in sample)
    assert not any("40" in row["numbers"] or "176" in row["numbers"] for row in sample)
    findings = [fact["text"] for path in sorted((out_on / "v3" / "kiq").glob("*.json"))
                for fact in json.loads(path.read_text(encoding="utf-8")).get("facts") or []]
    assert findings and not any(re.search(r"\b40\b", text) for text in findings)
    assert any(PAGE_SENTENCE in sentence for sentence in lr.prose_sentences(body))

    # Mirrored into meta (memory and disk) as research_qa and research_quality.
    disk_meta = _read(out_on, "meta.json")
    for source in (meta_on, disk_meta):
        assert source["research_qa"]["citation_stats"] == stats
        assert source["research_quality"]["citation_stats"] == stats

    # Off: no key anywhere.
    qa_off = _read(out_off, "v3/qa.json")
    assert "citation_stats" not in qa_off
    for source in (meta_off, _read(out_off, "meta.json")):
        assert "citation_stats" not in source["research_qa"]
        assert "citation_stats" not in source["research_quality"]
    assert {key: value for key, value in qa.items() if key not in ("citation_stats", "created_at")} == \
        {key: value for key, value in qa_off.items() if key != "created_at"}


def test_resume_of_a_qa_json_without_the_stats_finalizes(tmp_path, bridge, monkeypatch):
    """A qa.json an older engine wrote has no citation_stats: the resumed run
    reuses it, finalizes and simply has no stats."""
    _, _, out = _run(tmp_path, bridge, monkeypatch, "run", stats=None)
    report = (out / "research_report.md").read_bytes()
    qa_path = out / "v3" / "qa.json"
    qa = json.loads(qa_path.read_text(encoding="utf-8"))
    del qa["citation_stats"]
    qa_path.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")

    silent = v3.ScriptedModel(lambda call: pytest.fail(f"unexpected model call: {v3.role_of(call)}"))
    rc, meta, plog, model, _ = v3.run_engine(tmp_path, bridge, CitationWorld(), out_dir=out, model=silent)
    assert rc == 0 and meta["status"] == "completed" and model.calls == []
    assert "[resume] research:v3:qa reused" in plog.text()
    assert (out / "research_report.md").read_bytes() == report
    assert "citation_stats" not in meta["research_qa"]
    assert "citation_stats" not in meta["research_quality"]


def test_citation_stats_failure_never_fails_the_qa_phase(tmp_path, bridge, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("stats exploded")

    monkeypatch.setattr(lr, "writer_bibliographies", boom)
    meta, plog, out = _run(tmp_path, bridge, monkeypatch, "run", stats=True)
    assert "citation_stats" not in _read(out, "v3/qa.json")
    assert "citation_stats" not in meta["research_qa"] and "citation_stats" not in meta["research_quality"]
    assert "v3: citation stats failed (RuntimeError: stats exploded)" in plog.text()


# ================================================================ knob

def test_knob_defaults_on_and_is_forwarded_to_the_v3_child_only():
    assert ("RESEARCH_V3_CITATION_STATS", "bool") in po.RESEARCH_CHILD_V3_KNOBS
    assert all(name != "RESEARCH_V3_CITATION_STATS" for name, _kind in po.RESEARCH_CHILD_KNOBS)
    names = [name for name, _kind in po.RESEARCH_CHILD_V3_KNOBS]
    assert names == sorted(names)
    assert "RESEARCH_V3_CITATION_STATS" in v3._ENV_EXACT
    env = {key: value for key, value in os.environ.items() if key != "RESEARCH_V3_CITATION_STATS"}
    env["DRF_TEST_PROCESS"] = "1"
    probe = subprocess.run([sys.executable, "-c", "from app.config import Config; "
                            "print(repr(Config.RESEARCH_V3_CITATION_STATS))"],
                           cwd=BACKEND, env=env, capture_output=True, text=True, timeout=60, check=True)
    assert probe.stdout.strip().splitlines()[-1] == "True"
    child: dict[str, str] = {}
    po._forward_research_knobs(child, po.RESEARCH_CHILD_V3_KNOBS)
    assert child["RESEARCH_V3_CITATION_STATS"] == "true"
    env_example = (BACKEND.parent / ".env.example").read_text(encoding="utf-8")
    assert re.search(r"^# RESEARCH_V3_CITATION_STATS=true\s+# ", env_example, re.M)
