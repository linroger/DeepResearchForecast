"""REPORT-7: research-side figure verification in the v3 engine (C11 phase 1a).

With RESEARCH_VERIFIED_FACTS (default on; RESEARCH-4's knob, which also labels
each quantitative row's ``verification``) finalize

* keeps each quantitative row's positional ``source_ref``, stamps
  ``future_dated`` on an actual dated after the as-of and ``evidence_window``
  on a verified row;
* publishes the page sentences that state a verified figure next to >= 2 of
  its metric words as sources.json ``supports`` windows (<= 360 chars, cleaned
  like web text, <= 2 per figure, <= 8 per source) through the one supports
  writer ``_merge_supports``;
* writes handoff verified_facts.json (``drf.verified_facts/v1``), which the
  parent SHA-manifests with the research artifacts.

Off, every research artifact is byte-identical.  Offline: the scripted model,
injected search/fetch and real bridge of ``test_research_engine_v3``.
"""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import sys
import types

import pytest

import test_research_engine_v3 as v3
from test_orchestrator_research_wiring import _launch_capturing_child

# The shared fixtures (hermetic env, real bridge with network steps stubbed).
_hermetic_env = v3._hermetic_env
bridge = v3.bridge
lr = v3.lr
dr = v3.dr
rg = v3.rg
po = v3.po

AS_OF = dt.date(2026, 9, 28)
LATER = (AS_OF + dt.timedelta(days=30)).isoformat()
NEXT_DAY = (AS_OF + dt.timedelta(days=1)).isoformat()
NEW_ROW_KEYS = {"source_ref", "evidence_window", "future_dated"}
VERIFY_KEYS = {"verification", "verified"}

# The harness page (v3.page_text): "Installed data-centre capacity reached 176 GW
# in 2023, up from 150 GW in 2022, according to the national energy agency's
# annual survey of operators."
HARNESS_WINDOW = ("Installed data-centre capacity reached 176 GW in 2023, up from 150 GW in 2022, according "
                  "to the national energy agency's annual survey of operators.")


@pytest.fixture
def fixed_as_of(monkeypatch):
    """The plan's as-of date (UTC today in production) pinned for stable dates."""
    monkeypatch.setattr(lr, "_utc_date", lambda: AS_OF.isoformat())


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")


def _row(metric, value, unit, ref, *, as_of_date="2023-12-31", value_type="actual", **extra):
    return {"metric": metric, "value": value, "unit": unit, "as_of_date": as_of_date, "value_type": value_type,
            "source_ref": ref, **extra}


class FactsWorld(v3.World):
    """The standard world whose facts reply is built from the sources.json
    finalize wrote before extraction (``quant(sources)`` → the rows)."""

    def __init__(self, out_dir, quant, **kwargs) -> None:
        super().__init__(**kwargs)
        self.out_dir = out_dir
        self.quant = quant
        self.sources: list[dict] = []

    def facts(self, call):
        self.sources = _load(self.out_dir / "sources.json")
        return v3.ai(json.dumps({"key_events": [], "quantitative_facts": self.quant(self.sources),
                                 "contested_claims": []}))


# ---------------------------------------------------------------- a long page

def _long_page() -> str:
    """A 5,000-char page whose only sentence stating 176 GW next to the
    metric sits near char 4,000 (with a page-own ``[S1]`` label); an earlier
    sentence has the same number but none of the metric's words, and two
    chrome lines state the metric and number but are never evidence."""
    parts = ["# Annual survey of operators", "",
             "The survey archive lists 176 GW of filings in 2023 across many unrelated dockets.", ""]
    filler = ("Regional operators filed {n} maintenance notices and routine outage schedules with the "
              "regulator during the review.")
    n = 11
    while len("\n".join(parts)) < 3500:
        parts += [filler.format(n=n), ""]
        n += 1
    parts += ["© 2026 National Energy Agency: installed capacity 176 GW in 2023, all figures provisional.", "",
              "Cookies help us improve this website; installed capacity data (176 GW in 2023) is updated yearly.",
              ""]
    while len("\n".join(parts)) < 3960:
        parts += [filler.format(n=n), ""]
        n += 1
    parts += ["Installed data-centre capacity reached 176 GW in 2023 according to the agency survey [S1] of "
              "operators.", ""]
    while len("\n".join(parts)) < 5000:
        parts += [filler.format(n=n), ""]
        n += 1
    return "\n".join(parts)


LONG_PAGE = _long_page()
LONG_WINDOW = ("Installed data-centre capacity reached 176 GW in 2023 according to the agency survey [page-S1] of "
               "operators.")


# =================================================================== pure helpers

def test_merge_supports_is_ordered_deduplicated_and_capped():
    entry = {"supports": ["first", " first ", "", None]}
    added = lr._merge_supports(entry, ["second", "first", "  ", "third", "second", "fourth"], 3)
    assert entry["supports"] == ["first", "second", "third"] and added == ["second", "third"]
    assert lr._merge_supports(entry, ["fifth"], 3) == [] and entry["supports"] == ["first", "second", "third"]
    empty = {}
    assert lr._merge_supports(empty, [], 8) == [] and empty == {"supports": []}


@pytest.mark.parametrize("ref, expected", [("S2", "S2"), ("[S2]", "S2"), ("2", "S2"), ("s1", "S1"),
                                           ("S9", None), ("", None), (None, None)])
def test_normalize_quant_keeps_the_normalised_ref_only_when_asked(ref, expected):
    sources = [{"url": "https://a.example.org/1", "tier": "S1", "title": "A"},
               {"url": "https://b.example.org/2", "tier": "S2", "title": "B"}]
    item = {"metric": "Installed capacity", "value": "176", "unit": "GW", "source_ref": ref}
    (kept,) = lr.normalize_quant([dict(item)], sources, keep_ref=True)
    (plain,) = lr.normalize_quant([dict(item)], sources)
    assert kept.get("source_ref") == expected and "source_ref" not in plain
    assert {k: v for k, v in kept.items() if k != "source_ref"} == plain


def test_window_selection():
    """The verified number near char 4,000 in a sentence sharing its metric
    words is the one window; an earlier sentence with the number but no
    metric word and the chrome lines are never selected; the page-own [S1]
    label is defused."""
    assert len(LONG_PAGE) >= 5000 and 3800 <= LONG_PAGE.index("Installed data-centre") <= 4200
    early = LONG_PAGE.index("The survey archive lists 176 GW")
    sentences = lr.evidence_sentences(LONG_PAGE)
    assert not any("©" in s.text or "Cookies" in s.text for s in sentences)   # chrome never qualifies
    windows = lr.select_evidence_windows(sentences, "176 GW", "Installed capacity")
    assert [text for _, _, text in windows] == [LONG_WINDOW]
    ((score, index, text),) = windows
    assert score == 2 and len(text) <= lr.EVIDENCE_WINDOW_CHARS and "[S1]" not in text
    assert early < LONG_PAGE.index("Installed data-centre")
    # A finding anchors on its own words: the early sentence shares only "survey".
    finding = "Installed capacity reached 176 GW in 2023 per the agency survey"
    assert [text for _, _, text in lr.select_evidence_windows(sentences, finding, finding)] == [LONG_WINDOW]
    # No metric words, no window: a number alone never selects a sentence.
    assert lr.select_evidence_windows(sentences, "176 GW", "Hyperscaler procurement") == []


def test_windows_per_figure_are_capped_and_ranked():
    page = "\n\n".join([
        "Installed capacity rose to 555 MW.",                                     # 2 anchors
        "Installed generating capacity at the new site reached 555 MW this spring.",   # 4 anchors
        "Installed capacity of generating units reached 555 MW.",                  # 4 anchors
        "Installed capacity in the northern region was 555 MW.",                   # 3 anchors (region)
    ])
    sentences = lr.evidence_sentences(page)
    ranked = lr.select_evidence_windows(sentences, "555 MW", "Installed generating capacity reached, by region")
    assert [index for _, index, _ in ranked] == [1, 2]            # best score first, then page order
    assert [score for score, _, _ in ranked] == [4, 4]
    assert len(lr.select_evidence_windows(sentences, "555 MW", "Installed capacity", limit=3)) == 3


def test_window_of_a_long_sentence_is_centred_and_whole():
    words = " ".join(f"word{i:03d}" for i in range(80))
    sentence = f"{words} installed capacity reached 1,234.5 GW in the survey {words}."
    page = sentence + "\n"
    ((_, _, window),) = lr.select_evidence_windows(lr.evidence_sentences(page), "1,234.5 GW", "Installed capacity")
    assert len(window) <= lr.EVIDENCE_WINDOW_CHARS
    assert window.startswith("…") and window.endswith("…")
    assert "installed capacity reached 1,234.5 GW" in window
    inner = window.strip("…").split()
    assert all(token in sentence.split() for token in inner)      # cut at word boundaries


def test_cjk_windows_anchor_on_bigrams():
    page = "全国数据中心装机容量在2023年达到176吉瓦。\n\n另有176个项目在2023年排队等待并网。\n"
    windows = lr.select_evidence_windows(lr.evidence_sentences(page), "176吉瓦 2023", "数据中心装机容量")
    assert [text for _, _, text in windows] == ["全国数据中心装机容量在2023年达到176吉瓦。"]


# ============================================================ engine (stubbed)

def _stub(tmp_path, pages: dict[str, str | None]):
    """A minimal engine for :meth:`_Engine._verified_evidence`: a real ledger
    (``pages``: url → stored page text, None = cited only), sources.json rows
    in the given order and the report's citation order; no findings."""
    ledger = rg.SourceLedger(tmp_path / "ledger.json")
    texts: dict[int, str] = {}
    sources, order = [], []
    for url, text in pages.items():
        row = ledger.register(url, "Title", "")
        if text is not None:
            ledger.mark_fetched(row["sid"], content_sha256="x", chars=len(text),
                                page_path=str(tmp_path / f"{row['sid']}.txt"))
            texts[row["sid"]] = text
        order.append(row["sid"])
        sources.append({"source_id": f"src_{row['sid']}", "url": url,
                        "source_origin": "fetched" if text is not None else "cited", "supports": []})
    engine = types.SimpleNamespace(
        ledger=ledger, tools=types.SimpleNamespace(page_text=texts.get), records={}, kiqs=[],
        plan=types.SimpleNamespace(as_of=AS_OF.isoformat()), qa={"report_sha256": "f" * 64})
    return engine, sources, order


def _verified(metric, value, unit, url, **extra):
    return {"metric": metric, "value": value, "unit": unit, "source_url": url, "verification": "verified",
            "verified": True, **extra}


def test_verified_number_only(tmp_path):
    """A verified row whose number no sentence states next to its metric
    gets basis number_only and adds no supports window."""
    url = "https://www.agency.example.org/survey"
    engine, sources, order = _stub(tmp_path, {url: HARNESS_WINDOW})
    quant = [_verified("Hyperscaler procurement volume", "176", "GW", url, source_ref="S1")]
    evidence = lr._Engine._verified_evidence(engine, quant, sources, order, AS_OF)
    assert evidence["stamps"] == [{"evidence_window": {"text": None, "basis": "number_only"}}]
    assert evidence["windows"] == {} and evidence["payload"]["counts"]["windows"] == 0
    assert evidence["payload"]["quant"] == [{"row": 0, "metric": "Hyperscaler procurement volume",
                                             "verification": "verified", "source_ref": "S1", "future_dated": False,
                                             "evidence_window": {"text": None, "basis": "number_only"}}]
    assert quant[0].get("evidence_window") is None      # nothing stamped before the step applies it


def test_supports_are_capped_per_source_in_page_order(tmp_path):
    url = "https://www.agency.example.org/regions"
    page = "\n\n".join(f"Installed capacity in region {k} reached {100 + k} GW in 2023." for k in range(1, 13))
    engine, sources, order = _stub(tmp_path, {url: page, "https://www.cited.example.org/x": None})
    shuffled = (12, 3, 7, 1, 9, 5, 11, 2, 8, 4, 10, 6)
    quant = [_verified("Installed capacity", str(100 + k), "GW", url, source_ref="S1") for k in shuffled]
    evidence = lr._Engine._verified_evidence(engine, quant, sources, order, AS_OF)
    expected = [f"Installed capacity in region {k} reached {100 + k} GW in 2023." for k in range(1, 9)]
    assert evidence["windows"] == {1: expected}                     # page order, capped at 8
    assert evidence["payload"]["counts"]["windows"] == lr.EVIDENCE_WINDOWS_PER_SOURCE
    # Every verified row keeps its own window, published or not.
    assert all(stamp["evidence_window"]["basis"] == "number_and_anchor" for stamp in evidence["stamps"])
    assert evidence["stamps"][0]["evidence_window"]["text"] == (
        "Installed capacity in region 12 reached 112 GW in 2023.")


def test_findings_are_projected_as_claims(tmp_path):
    fetched, cited, uncited = ("https://www.agency.example.org/a", "https://www.cited.example.org/b",
                               "https://www.other.example.org/c")
    engine, sources, order = _stub(tmp_path, {fetched: HARNESS_WINDOW, cited: None})
    extra = engine.ledger.register(uncited, "Not cited in the report", "")
    sid_a, sid_b = order
    engine.records = {
        "K1": {"facts": [
            {"kiq": "K1", "text": f"Installed capacity reached 176 GW in 2023 per the agency survey [S{sid_a}]",
             "sids": [sid_a], "tag": "VERIFIED", "verified_numbers": True},
            {"kiq": "K1", "text": f"Operators plan 250 GW by 2030 [S{sid_a}][S{extra['sid']}]",
             "sids": [sid_a, extra["sid"]], "tag": "UNVERIFIED", "missing_numbers": ["250", "2030"]},
        ]},
        "K2": {"facts": [{"kiq": "K2", "text": f"Analysts expect 12% growth [S{sid_b}]", "sids": [sid_b],
                          "tag": "REPORTED"}]},
        "K9": {"facts": [{"kiq": "K9", "text": "an unplanned KIQ", "sids": [], "tag": "REPORTED"}]},
    }
    engine.kiqs = [types.SimpleNamespace(id="K2"), types.SimpleNamespace(id="K1")]
    evidence = lr._Engine._verified_evidence(engine, [], sources, order, AS_OF)
    facts = evidence["payload"]["facts"]
    assert [fact["claim_id"] for fact in facts] == ["K2-F1", "K1-F1", "K1-F2"]   # plan order
    reported, verified, unverified = facts
    assert verified == {
        "claim_id": "K1-F1", "kiq": "K1", "text_plain": "Installed capacity reached 176 GW in 2023 per the agency "
                                                        "survey",
        "status": "verified", "numbers": ["176", "2023"], "missing_numbers": [], "source_refs": ["S1"],
        "source_ids": [f"src_{sid_a}"], "citable": True,
        "spans": [{"source_ref": "S1", "span_text": HARNESS_WINDOW,
                   "span_sha256": hashlib.sha256(HARNESS_WINDOW.encode("utf-8")).hexdigest()}]}
    # Only sources in sources.json are refs; an unverified finding is never citable.
    assert unverified["source_refs"] == ["S1"] and unverified["citable"] is False
    assert unverified["missing_numbers"] == ["250", "2030"] and unverified["spans"] == []
    # A snippet-only source is a ref but no span.
    assert reported["status"] == "reported" and reported["source_refs"] == ["S2"] and reported["citable"] is True
    assert reported["spans"] == []
    assert evidence["windows"] == {1: [HARNESS_WINDOW]}
    assert evidence["payload"]["counts"] == {"facts": 3, "verified": 1, "quant_verified": 0,
                                             "quant_unverified": 0, "quant_snippet_only": 0, "quant_none": 0,
                                             "windows": 1}


def test_future_dated_uses_the_publication_bound(tmp_path):
    """An actual dated after the day after the plan's as-of is future-dated
    (a run crossing UTC midnight can cite a source published the next day);
    targets, partial dates and past dates never are."""
    engine, _, _ = _stub(tmp_path, {})
    bound = AS_OF + dt.timedelta(days=1)
    rows = [{"metric": "m", "value": "1", "value_type": "actual", "as_of_date": LATER},
            {"metric": "m", "value": "1", "value_type": "actual", "as_of_date": NEXT_DAY},
            {"metric": "m", "value": "1", "value_type": "target", "as_of_date": LATER},
            {"metric": "m", "value": "1", "value_type": "actual", "as_of_date": "2027-03"},
            {"metric": "m", "value": "1", "value_type": "actual", "as_of_date": "2023-12-31"}]
    evidence = lr._Engine._verified_evidence(engine, rows, [], [], bound)
    assert evidence["stamps"] == [{"future_dated": True}, {}, {}, {}, {}]
    assert [row["future_dated"] for row in evidence["payload"]["quant"]] == [True, False, False, False, False]


# ================================================================ engine end to end

def test_labels(tmp_path, bridge, fixed_as_of):
    """RESEARCH-4's labels with the kept positional ref, the evidence window
    and future_dated, mirrored in verified_facts.json."""
    out = tmp_path / "out"

    def quant(sources):
        cited = next(i for i, s in enumerate(sources, 1) if s["source_origin"] == "cited")
        return [_row("Installed capacity", "176", "GW", "S2"),                       # on the fetched page
                _row("Installed capacity", "999", "GW", "S2"),                       # fetched, not on the page
                _row("Installed capacity", "176", "GW", f"S{cited}"),                # never fetched
                _row("Installed capacity", "176", "GW", ""),                         # no source
                _row("Installed capacity", "150", "GW", "S2", as_of_date=LATER),     # an actual after as-of
                _row("Installed capacity", "150", "GW", "S2", as_of_date=NEXT_DAY),  # within the bound
                _row("Hyperscaler procurement volume", "150", "GW", "S2")]           # verified, no anchored sentence

    world = FactsWorld(out, quant)
    rc, meta, _, _, _ = v3.run_engine(tmp_path, bridge, world, out_dir=out)
    assert rc == 0, meta.get("error")
    assert world.sources[1]["source_origin"] == "fetched"
    cited = next(i for i, s in enumerate(world.sources, 1) if s["source_origin"] == "cited")
    rows = _load(out / "quantitative.json")
    assert [row.get("verification") for row in rows] == [
        "verified", "unverified", "snippet_only", "none", "verified", "verified", "verified"]
    assert [row.get("source_ref") for row in rows] == ["S2", "S2", f"S{cited}", None, "S2", "S2", "S2"]
    assert [row.get("future_dated") for row in rows] == [None, None, None, None, True, None, None]
    assert rows[0]["evidence_window"] == {"text": HARNESS_WINDOW, "basis": "number_and_anchor"}
    assert rows[4]["evidence_window"] == {"text": HARNESS_WINDOW, "basis": "number_and_anchor"}
    assert rows[6]["evidence_window"] == {"text": None, "basis": "number_only"}
    assert not any("evidence_window" in row for row in rows[1:4])
    payload = _load(out / lr.VERIFIED_FACTS_FILENAME)
    assert [(q["row"], q["verification"], q["source_ref"], q["future_dated"]) for q in payload["quant"]] == [
        (0, "verified", "S2", False), (1, "unverified", "S2", False), (2, "snippet_only", f"S{cited}", False),
        (3, "none", None, False), (4, "verified", "S2", True), (5, "verified", "S2", False),
        (6, "verified", "S2", False)]
    assert [q["evidence_window"] for q in payload["quant"]] == [row.get("evidence_window") for row in rows]
    counts = payload["counts"]
    assert (counts["quant_verified"], counts["quant_unverified"], counts["quant_snippet_only"],
            counts["quant_none"]) == (4, 1, 1, 1)
    assert meta["verified_facts"] == counts


def test_window_selection_end_to_end(tmp_path, bridge, fixed_as_of):
    """Every fetched page is the long page: the sentence near char 4,000 is
    the one supports window of each fetched source, defused and <= 360 chars."""
    out = tmp_path / "out"
    world = FactsWorld(out, lambda sources: [_row("Installed capacity", "176", "GW", "S1")])
    rc, meta, _, _, _ = v3.run_engine(tmp_path, bridge, world, out_dir=out, fetch=lambda url: LONG_PAGE)
    assert rc == 0, meta.get("error")
    sources = _load(out / "sources.json")
    fetched = [row for row in sources if row["source_origin"] == "fetched"]
    assert fetched and all(row["supports"] == [LONG_WINDOW] for row in fetched)
    assert all(row["supports"] == [] for row in sources if row["source_origin"] != "fetched")
    # The 1,200-char excerpt never reaches the figure: the window is the only span stating it.
    assert all("reached 176 GW" not in row["excerpt"] for row in fetched)
    (row,) = _load(out / "quantitative.json")
    assert row["evidence_window"] == {"text": LONG_WINDOW, "basis": "number_and_anchor"}


def test_end_to_end_and_idempotent(tmp_path, bridge, monkeypatch, fixed_as_of):
    out = tmp_path / "out"
    rc, meta, plog, _, _ = v3.run_engine(tmp_path, bridge, v3.World(), out_dir=out)
    assert rc == 0, meta.get("error")
    payload = _load(out / lr.VERIFIED_FACTS_FILENAME)
    assert list(payload) == ["schema", "as_of", "report_sha256", "quantitative_sha256", "facts", "quant", "counts"]
    assert payload["schema"] == "drf.verified_facts/v1" and payload["as_of"] == AS_OF.isoformat()
    assert payload["report_sha256"] == hashlib.sha256((out / "research_report.md").read_bytes()).hexdigest()
    assert payload["quantitative_sha256"] == hashlib.sha256((out / "quantitative.json").read_bytes()).hexdigest()
    counts = payload["counts"]
    assert counts["facts"] == len(payload["facts"]) > 0 and counts["verified"] >= 1 and counts["windows"] >= 1
    assert meta["verified_facts"] == counts and _load(out / "meta.json")["verified_facts"] == counts

    sources = _load(out / "sources.json")
    windows = [span for row in sources for span in row["supports"]]
    assert len(windows) == counts["windows"]
    for row in sources:
        assert len(row["supports"]) <= lr.EVIDENCE_WINDOWS_PER_SOURCE
        assert row["supports"] == [] or row["source_origin"] == "fetched"
    for span in windows:
        # <= 360 chars, the verified number and >= 2 metric anchors in the window itself.
        assert len(span) <= lr.EVIDENCE_WINDOW_CHARS
        assert "176" in span
        assert len(lr.evidence_anchor_terms("Installed capacity")[0] & lr.evidence_anchor_terms(span)[0]) >= 2
    verified = [fact for fact in payload["facts"] if fact["status"] == "verified"]
    assert verified and all(fact["spans"] and fact["citable"] for fact in verified)
    for fact in verified:
        for span in fact["spans"]:
            position = int(span["source_ref"][1:])
            assert span["span_text"] in sources[position - 1]["supports"]
            assert span["span_sha256"] == hashlib.sha256(span["span_text"].encode("utf-8")).hexdigest()
    # actors.json carries the rows without the window text (budgeted actor context packs).
    quant_rows = _load(out / "quantitative.json")
    actor_rows = _load(out / "actors.json")["quantitative_facts"]
    assert quant_rows[0]["evidence_window"]["basis"] == "number_and_anchor"
    assert actor_rows == [{k: v for k, v in row.items() if k != "evidence_window"} for row in quant_rows]
    assert actor_rows[0]["source_ref"] == quant_rows[0]["source_ref"]
    assert any(m.startswith("v3: added ") and "evidence window" in m for m in plog.of("ok"))
    assert any(m.startswith(f"wrote {lr.VERIFIED_FACTS_FILENAME} (") for m in plog.of("ok"))

    # The parent registers it in the handoff manifest with its sha256.
    manifest: dict = {}
    monkeypatch.setattr(po.Config, "PIPELINE_VALIDATE_ARTIFACTS", True, raising=False)
    monkeypatch.setattr(po.PipelineManager, "load_artifact_manifest", classmethod(lambda cls, pid: dict(manifest)))
    monkeypatch.setattr(po.PipelineManager, "write_artifact_manifest",
                        classmethod(lambda cls, pid, value: manifest.update(value)))
    state = po.PipelineState(pipeline_id="pipe-vf-e2e", prompt="x", handoff_dir=str(out))
    po.PipelineOrchestrator.__new__(po.PipelineOrchestrator)._record_stage_artifacts(state, po.STAGE_RESEARCH)
    assert manifest["verified_facts"]["sha256"] == hashlib.sha256(
        (out / lr.VERIFIED_FACTS_FILENAME).read_bytes()).hexdigest()
    assert manifest["verified_facts"]["schema_ok"] is True

    first = {name: (out / name).read_bytes() for name in ("sources.json", "quantitative.json",
                                                         lr.VERIFIED_FACTS_FILENAME)}
    silent = v3.ScriptedModel(lambda call: pytest.fail(f"unexpected model call: {v3.role_of(call)}"))
    rc, meta, _, model, _ = v3.run_engine(tmp_path, bridge, v3.World(), out_dir=out, model=silent)
    assert rc == 0 and model.calls == []
    assert {name: (out / name).read_bytes() for name in first} == first
    assert meta["verified_facts"] == counts


@pytest.mark.parametrize("raw", ["false", "0"])
def test_flag_off_identical(tmp_path, bridge, monkeypatch, fixed_as_of, raw):
    """Off: sources.json is exactly the rows finalize built (supports []),
    quantitative.json exactly what normalize → enrich → annotate produced
    before, no verified_facts.json and no new meta; the evidence step never
    runs.  Flipped off on a flag-on out dir (a resumed finalize: same ledger,
    citation order and extraction memo), the artifacts differ from the
    flag-on ones only by the additions, and the stale projection goes."""
    built: list[bytes] = []
    real_rows = lr._Engine._source_rows

    def source_rows(self, order):
        rows = real_rows(self, order)
        built.append(_dump(rows))
        return rows

    monkeypatch.setattr(lr._Engine, "_source_rows", source_rows)
    calls = []
    real = lr._Engine._verified_evidence
    monkeypatch.setattr(lr._Engine, "_verified_evidence",
                        lambda self, *args: calls.append(args) or real(self, *args))
    names = ("sources.json", "quantitative.json", "actors.json", "timeline.json", "contested.json")

    out = tmp_path / "out"
    rc, on_meta, _, _, _ = v3.run_engine(tmp_path, bridge, v3.World(), out_dir=out)
    assert rc == 0 and (out / lr.VERIFIED_FACTS_FILENAME).is_file() and len(calls) == 1
    on_bytes = {name: (out / name).read_bytes() for name in names}
    assert on_bytes["sources.json"] != built[-1]            # on: the windows were published

    monkeypatch.setenv("RESEARCH_VERIFIED_FACTS", raw)
    silent = v3.ScriptedModel(lambda call: pytest.fail(f"unexpected model call: {v3.role_of(call)}"))
    rc, meta, plog, model, _ = v3.run_engine(tmp_path, bridge, v3.World(), out_dir=out, model=silent)
    assert rc == 0 and model.calls == [] and len(calls) == 1
    assert (out / "sources.json").read_bytes() == built[-1]
    assert not (out / lr.VERIFIED_FACTS_FILENAME).exists()
    assert "verified_facts" not in meta and "verified_facts" not in _load(out / "meta.json")
    assert not any(lr.VERIFIED_FACTS_FILENAME in m or "evidence window" in m for m in plog.of("ok"))
    sources = _load(out / "sources.json")
    assert all(row["supports"] == [] for row in sources)
    on_sources = json.loads(on_bytes["sources.json"])
    assert any(row["supports"] for row in on_sources)
    assert _dump([dict(row, supports=[]) for row in on_sources]) == built[-1]

    facts = json.loads(v3.World().facts(None).content)["quantitative_facts"]
    baseline = dr.enrich_quantitative_rows(lr.normalize_quant(copy.deepcopy(facts), sources))
    dr.annotate_recency_rows(baseline, AS_OF, lr.DEFAULT_STALE_DAYS, date_key="as_of_date")
    assert (out / "quantitative.json").read_bytes() == _dump(baseline)
    assert not any((NEW_ROW_KEYS | VERIFY_KEYS) & set(row) for row in baseline)
    on_quant = json.loads(on_bytes["quantitative.json"])
    assert [{k: v for k, v in row.items() if k not in NEW_ROW_KEYS | VERIFY_KEYS} for row in on_quant] == baseline
    for name in ("timeline.json", "contested.json"):
        assert (out / name).read_bytes() == on_bytes[name]
    on_actors = json.loads(on_bytes["actors.json"])
    on_actors["quantitative_facts"] = [{k: v for k, v in row.items() if k not in NEW_ROW_KEYS | VERIFY_KEYS}
                                       for row in on_actors["quantitative_facts"]]
    assert (out / "actors.json").read_bytes() == _dump(on_actors)

    # A fresh run with the knob off never publishes anything either.
    fresh = tmp_path / "fresh"
    rc, meta, _, _, _ = v3.run_engine(tmp_path, bridge, v3.World(), out_dir=fresh)
    assert rc == 0 and len(calls) == 1 and "verified_facts" not in meta
    assert (fresh / "sources.json").read_bytes() == built[-1] and not (fresh / lr.VERIFIED_FACTS_FILENAME).exists()
    assert on_meta["verified_facts"]["windows"] >= 1


def test_evidence_failure_degrades_safe(tmp_path, bridge, monkeypatch, fixed_as_of):
    def broken(self, *args):
        raise RuntimeError("page store unreadable")

    monkeypatch.setattr(lr._Engine, "_verified_evidence", broken)
    rc, meta, plog, _, out = v3.run_engine(tmp_path, bridge, v3.World())
    assert rc == 0 and meta["status"] == "completed"
    assert {"helper": "verified_facts", "error": "RuntimeError: page store unreadable"} in meta["analytics_errors"]
    assert any(m.startswith("v3: verified facts failed (RuntimeError") for m in plog.of("warn"))
    assert not (out / lr.VERIFIED_FACTS_FILENAME).exists() and "verified_facts" not in meta
    assert all(row["supports"] == [] for row in _load(out / "sources.json"))
    (row,) = _load(out / "quantitative.json")
    assert row["verification"] == "verified" and not {"evidence_window", "future_dated"} & set(row)


def test_publish_failure_degrades_safe(tmp_path, bridge, monkeypatch, fixed_as_of):
    out = tmp_path / "out"
    rc, _, _, _, _ = v3.run_engine(tmp_path, bridge, v3.World(), out_dir=out)
    assert rc == 0 and (out / lr.VERIFIED_FACTS_FILENAME).is_file()
    real = lr._Engine.write_json

    def write_json(self, path, obj, *, internal=True):
        if path.name == lr.VERIFIED_FACTS_FILENAME:
            raise OSError("disk full")
        return real(self, path, obj, internal=internal)

    monkeypatch.setattr(lr._Engine, "write_json", write_json)
    silent = v3.ScriptedModel(lambda call: pytest.fail(f"unexpected model call: {v3.role_of(call)}"))
    rc, meta, plog, _, _ = v3.run_engine(tmp_path, bridge, v3.World(), out_dir=out, model=silent)
    assert rc == 0 and meta["status"] == "completed"
    assert {"helper": "verified_facts:publish", "error": "OSError: disk full"} in meta["analytics_errors"]
    # No stale projection of the earlier attempt survives, and meta claims none.
    assert not (out / lr.VERIFIED_FACTS_FILENAME).exists() and "verified_facts" not in meta


# ================================================================== parent wiring

def test_orchestrator_wiring(tmp_path, monkeypatch):
    """verified_facts.json is a research stage artifact (SHA-manifested and
    reuse-validated); the knob reaches the v3 child from Config."""
    handoff = tmp_path / "handoff"
    handoff.mkdir()
    state = po.PipelineState(pipeline_id="pipe-vf", prompt="x", handoff_dir=str(handoff))
    specs = po.PipelineOrchestrator._stage_artifact_specs(state, po.STAGE_RESEARCH)
    assert ("verified_facts", str(handoff / "verified_facts.json")) in specs
    assert ("RESEARCH_VERIFIED_FACTS", "bool") in po.RESEARCH_CHILD_V3_KNOBS
    assert all(name != "RESEARCH_VERIFIED_FACTS" for name, _ in po.RESEARCH_CHILD_KNOBS)

    manifest: dict = {}
    monkeypatch.setattr(po.Config, "PIPELINE_VALIDATE_ARTIFACTS", True, raising=False)
    monkeypatch.setattr(po.PipelineManager, "load_artifact_manifest", classmethod(lambda cls, pid: dict(manifest)))
    monkeypatch.setattr(po.PipelineManager, "write_artifact_manifest",
                        classmethod(lambda cls, pid, value: manifest.update(value)))
    body = _dump({"schema": "drf.verified_facts/v1", "facts": [], "quant": [], "counts": {}})
    (handoff / "verified_facts.json").write_bytes(body)
    orch = po.PipelineOrchestrator.__new__(po.PipelineOrchestrator)
    orch._record_stage_artifacts(state, po.STAGE_RESEARCH)
    assert state.artifacts["verified_facts"] == str(handoff / "verified_facts.json")
    entry = manifest["verified_facts"]
    assert entry["sha256"] == hashlib.sha256(body).hexdigest() and entry["schema_ok"] is True
    assert orch._validate_reuse(state, po.STAGE_RESEARCH) is True
    (handoff / "verified_facts.json").write_bytes(body.replace(b"[]", b"[1]", 1))
    assert orch._validate_reuse(state, po.STAGE_RESEARCH) is False

    for name, value, expected in (("on", True, "true"), ("off", False, "false")):
        (tmp_path / name).mkdir()
        monkeypatch.setattr(po.Config, "RESEARCH_ENGINE", "v3", raising=False)
        monkeypatch.setattr(po.Config, "RESEARCH_VERIFIED_FACTS", value, raising=False)
        monkeypatch.setenv("RESEARCH_VERIFIED_FACTS", "false" if value else "true")   # ambient env never decides
        child = _launch_capturing_child(monkeypatch, tmp_path / name, timeout=900)
        assert child["env"]["RESEARCH_VERIFIED_FACTS"] == expected


def test_extract_only_salvage_drops_the_v3_verified_facts_counts(tmp_path, monkeypatch):
    """The parent salvages a killed v3 run with the legacy extract-only path,
    which rewrites quantitative.json: the v3 counts must not survive into the
    salvage meta (verified_facts.json binds the file it indexed by hash)."""
    (tmp_path / dr.REPORT_FILENAME).write_text("x" * 1000, encoding="utf-8")
    prior = {"status": "running", "research_engine": "v3",
             "verified_facts": {"facts": 3, "verified": 1, "quant_verified": 2, "quant_unverified": 0,
                                "quant_snippet_only": 0, "quant_none": 0, "windows": 2},
             "research_quality": {"score": 0.61}, "quantitative_count": 2}
    (tmp_path / "meta.json").write_text(json.dumps(prior), encoding="utf-8")
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key-not-used")
    seen = {}

    def fake_extract_only(question, out_dir, args, meta, plog, write_meta):
        seen["meta"] = dict(meta)
        plog.close()
        return 0

    monkeypatch.setattr(dr, "run_extract_only", fake_extract_only)
    monkeypatch.setattr(sys, "argv", ["deerflow_research.py", "--extract-only", "--model", "minimax",
                                      "--out-dir", str(tmp_path), "--prompt", "Q"])
    assert dr.main() == 0
    meta = seen["meta"]
    assert meta["salvage"]["mode"] == "extract_only" and "verified_facts" not in meta
    assert meta["research_quality"] == prior["research_quality"] and meta["quantitative_count"] == 2
    assert "verified_facts" not in _load(tmp_path / "meta.json")
