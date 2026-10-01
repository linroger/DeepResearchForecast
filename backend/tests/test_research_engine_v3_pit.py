"""TIME-9: point-in-time citation wall and research audit of a gated v3 hindcast.

Under TIME-8's gates (``tools.pit``) the report cites only sources admissible as
of the as-of date: ``_citable_sids`` (hence renumbering, References and
sources.json), the evidence digest (FU-2: a line carrying any marker of an
inadmissible source left out whole, SOURCE INDEX filtered) and the deterministic
fallback sections (a finding left out when one of its claims keeps no admissible
source, else stripped of its inadmissible markers) apply the wall.  Finalize
writes ``point_in_time.json`` (the gates' search/fetch streams summed over the
run's attempts, an independent re-check of the published sources.json dates,
the wall's counts, the parametric suspects and the verdict) and mirrors it into
``meta.point_in_time.audit``.  A live run writes no audit and builds its digest
exactly as before.  Offline: scripted model, injected search/fetch, zero network.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import threading
import types

import pytest

import test_research_engine_v3 as v3
from app.services import hindcast_policy as hp

# The shared fixtures (hermetic env, real bridge with network steps stubbed).
_hermetic_env = v3._hermetic_env
bridge = v3.bridge
lr = v3.lr
rg = v3.rg

AS_OF = "2024-06-01"
POLICY = rg.PitPolicy(as_of=dt.date(2024, 6, 1))
_PIT_ENV = ("RESEARCH_PIT_GATES", "RESEARCH_PIT_SAME_DAY", "RESEARCH_PIT_UNDATED",
            "RESEARCH_PIT_PROVIDER_BOUNDS", "RESEARCH_PIT_OVERFETCH", "RESEARCH_SOURCE_DATES",
            "RESEARCH_SOURCE_DATE_TEXT_FALLBACK", "RESEARCH_AS_OF")
_TITLE_SID_RE = r"^\[S(\d+)\] {title} "


@pytest.fixture(autouse=True)
def _pit_env(monkeypatch):
    for name in _PIT_ENV:
        monkeypatch.delenv(name, raising=False)


def pit_search(query: str, n: int) -> str:
    """Per query: an undated brief (shown labelled undated; never admissible
    under ``drop``), a release dated late by its URL path, a survey dated
    before the as-of and a note dated on it (late under ``exclude``)."""
    digest = int(hashlib.sha1(query.encode("utf-8")).hexdigest(), 16) % 10**8
    rows = [
        {"title": f"Undated brief {digest}", "url": f"https://undated-{digest}.example/brief",
         "content": "Capacity statistics: 176 GW installed; brief."},
        {"title": f"Late release {digest}", "url": f"https://late-{digest}.example/2024/07/01/release",
         "content": "Capacity statistics: 190 GW installed; release."},
        {"title": f"Dated survey {digest}", "url": f"https://dated-{digest}.example/survey",
         "content": "Capacity statistics: 176 GW installed; survey.", "published": "2024-04-15"},
        {"title": f"Same-day note {digest}", "url": f"https://sameday-{digest}.example/note",
         "content": "Capacity statistics: 180 GW installed; note.", "published": AS_OF},
    ]
    return json.dumps({"query": query, "results": rows})


class PitWorld(v3.World):
    """Each KIQ agent searches, fetches the undated brief (withheld under
    ``drop``) and the dated survey (admitted), then writes notes with a
    finding cited only by the brief, one cited only by the survey and a
    mixed finding and conflict.  Writers also cite a withheld brief."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.briefs: set[int] = set()
        self._brief_lock = threading.Lock()

    @staticmethod
    def _sid(texts, title: str) -> int | None:
        for text in texts:
            match = re.search(_TITLE_SID_RE.format(title=re.escape(title)), text, re.M)
            if match:
                return int(match.group(1))
        return None

    @staticmethod
    def _url(texts, host: str) -> str | None:
        for text in texts:
            match = re.search(rf"https://{host}-\d+\.example/\S+", text)
            if match:
                return match.group(0)
        return None

    def agent(self, call):
        messages = call["messages"]
        tool_results = [content for kind, content in messages if kind == "tool"]
        last_kind, last = messages[-1]
        kid = re.search(r"Investigate (\S+):", messages[2][1]).group(1)
        if last_kind == "human" and last.startswith("STOP"):
            return v3.ai(self.notes(tool_results))
        if not tool_results:
            return v3.ai(tool_calls=[{"name": "web_search", "args": {"query": f"{kid} capacity survey"},
                                      "id": f"{kid}-c1"}])
        for step, host in ((1, "undated"), (2, "dated")):
            if len(tool_results) == step:
                url = self._url(tool_results[:1], host)
                if url:
                    return v3.ai(tool_calls=[{"name": "web_fetch", "args": {"url": url, "focus": "capacity"},
                                              "id": f"{kid}-c{step + 1}"}])
        return v3.ai(self.notes(tool_results))

    def notes(self, tool_results) -> str:
        brief = self._sid(tool_results, "Undated brief")
        survey = self._sid(tool_results, "Dated survey")
        if brief is None or survey is None:
            return super().notes(tool_results)
        with self._brief_lock:
            self.briefs.add(brief)
        return "\n".join([
            "## Findings",
            f"- Installed capacity reached 176 GW in 2023 per the survey [S{survey}] (REPORTED)",
            f"- A brief says operators plan 250 GW of capacity by 2030 [S{brief}] (REPORTED)",
            f"- Analysts expect 12% annual demand growth through 2027 [S{brief}][S{survey}] (REPORTED)",
            "## Conflicts",
            f"- Sources differ on 2030 capacity [S{brief}][S{survey}]",
            "## Open questions",
            "- Grid connection timelines remain unclear",
        ])

    def writer(self, call):
        reply = super().writer(call)
        withheld = min(self.briefs) if self.briefs else None
        if withheld is None:
            return reply
        guess = f"\n\nA later brief put installed capacity at 300 GW [S{withheld}]."
        return v3.ai(re.sub(r"(\n\n## |\Z)", lambda m: guess + m.group(1), reply.content, count=1), out=1500)

    def facts(self, call):
        return v3.ai(json.dumps({
            "key_events": [{"date": "2023-12-31", "event": "Capacity reached 176 GW"},
                           {"date": "2024-09-15", "event": "A record hyperscaler order was announced"}],
            "quantitative_facts": [
                {"metric": "Installed capacity", "value": "176", "unit": "GW", "as_of_date": "2023-12-31",
                 "value_type": "actual", "source_ref": "S1"},
                {"metric": "Installed capacity", "value": "195", "unit": "GW", "as_of_date": "2024-08",
                 "value_type": "actual", "source_ref": "S1"},
                {"metric": "Grid queue", "value": "41", "unit": "months", "as_of_date": "2024-07-15",
                 "source_ref": "S1"},
                {"metric": "Installed capacity", "value": "250", "unit": "GW", "as_of_date": "2027",
                 "value_type": "forecast", "source_ref": "S1"},
            ],
            "contested_claims": [],
        }))


class SilentWriterWorld(PitWorld):
    """Every section writer returns nothing, so each section of the report is
    the deterministic fallback built from the KIQ records."""

    def writer(self, call):
        return v3.ai("")


def run_pit_engine(root, bridge, monkeypatch, *, gated: bool = True, undated: str = "drop",
                   world_cls: type[PitWorld] = PitWorld):
    monkeypatch.setenv("RESEARCH_LINEAR_WORKERS", "1")
    monkeypatch.setattr(lr, "_utc_date", lambda: "2026-10-01")
    if gated:
        monkeypatch.setenv("RESEARCH_AS_OF", AS_OF)
        monkeypatch.setenv("RESEARCH_PIT_GATES", "true")
        monkeypatch.setenv("RESEARCH_PIT_UNDATED", undated)
    world = world_cls()
    out = root / "out"
    out.mkdir(parents=True, exist_ok=True)
    model = v3.ScriptedModel(world)
    plog = v3.FakePlog()
    meta = {"status": "running", "question": "q", "research_engine": "v3"}

    def write_meta():
        (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

    def gateway_factory(args, plog_arg, bridge_arg, preset):
        return rg.ModelGateway(model, plog_arg, max_concurrency=preset.workers, budget_units=preset.budget_units,
                               reserve_share=lr.RESERVE_SHARE, sleep=lambda seconds: None)

    def tools_factory(ledger, pages_dir, bridge_arg, plog_arg, limits):
        # Built like production (_default_tools_factory), with offline search/fetch.
        return rg.ResearchTools(ledger, pages_dir, search_fn=pit_search, fetch_fn=v3.page_text,
                                bridge=bridge_arg, plog=plog_arg, limits=limits,
                                vintage_as_of=lr._hindcast_as_of(os.environ), pit=lr._pit_policy(os.environ))

    question = "Will global data-centre capacity exceed 250 GW by the end of 2027?"
    rc = lr.run(question, out, v3.make_args(), meta, plog, write_meta, bridge=bridge,
                gateway_factory=gateway_factory, tools_factory=tools_factory)
    return rc, meta, plog, world, out


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _spy_digest(monkeypatch):
    calls = []
    real = lr.build_digest

    def spy(*args, **kwargs):
        result = real(*args, **kwargs)
        calls.append((args, kwargs, result))
        return result

    monkeypatch.setattr(lr, "build_digest", spy)
    return calls, real


def _independent_cited(sources):
    """The cited stream recomputed here from the source_dates module directly."""
    sd = rg._source_dates()
    counts = {"checked": 0, "admitted": 0, "same_day": 0, "unverifiable": 0, "late": 0}
    names = {"admit": "admitted", "same_day": "same_day", "unverifiable": "unverifiable", "late": "late"}
    for row in sources:
        days = [sd.availability(row.get("date"), row.get("modified_at")), sd.url_date(row.get("url"))]
        known = [day for day in days if day is not None]
        counts["checked"] += 1
        counts[names[sd.gate(max(known) if known else None, AS_OF, same_day="exclude")]] += 1
    return counts


# =============================================================== the wall, end to end

def test_gated_hindcast_report_cites_only_admissible_sources(tmp_path, bridge, monkeypatch):
    calls, real_digest = _spy_digest(monkeypatch)
    rc, meta, plog, world, out = run_pit_engine(tmp_path, bridge, monkeypatch)
    assert rc == 0, meta.get("error")
    ledger = {row["sid"]: row for row in _load(out / "v3" / "sources_ledger.json")}
    sources = _load(out / "sources.json")
    report = (out / "research_report.md").read_text(encoding="utf-8")

    # The scripted agents fetched every brief: withheld undated, never stored.
    assert world.briefs and {ledger[sid]["pit_status"] for sid in world.briefs} == {"undated_withheld"}
    # A writer cited a withheld brief; renumbering removed it, so neither the report,
    # its References nor sources.json name any brief, late release or same-day note.
    assert "A later brief put installed capacity at 300 GW." in report
    for text in (report, json.dumps(sources)):
        assert not any(domain in text for domain in ("undated-", "//late-", "sameday-"))
    # Every [S<n>] marker (body and References) is positional into sources.json, and
    # every published source is admissible as of the as-of date.
    markers = {int(n) for n in re.findall(r"\[S(\d+)\]", report)}
    assert markers == set(range(1, len(sources) + 1))
    by_url = {row["url"]: row for row in ledger.values()}
    assert all(lr.pit_row_admissible(by_url[row["url"]], POLICY) for row in sources)
    assert {row["pit_status"] for row in sources} <= {"admitted", None}
    assert all(lr.pit_date_verdict(row.get("date"), row.get("modified_at"), row["url"], POLICY) == "admit"
               for row in sources)

    # The digest (FU-2): the brief-only finding, and the mixed finding and conflict that
    # cite the brief and the survey together ("[brief][survey]"), are left out whole; the
    # survey-only finding is kept as it is, and the SOURCE INDEX lists no brief.
    (args, kwargs, (digest_text, _dropped)), = calls
    assert kwargs["admissible"] is not None
    digest = (out / "v3" / "digest.md").read_text(encoding="utf-8")
    assert digest == digest_text
    assert "250 GW of capacity by 2030" not in digest
    assert "Analysts expect 12% annual demand growth" not in digest
    assert "Sources differ on 2030 capacity" not in digest
    assert len(re.findall(r"^- Installed capacity reached 176 GW in 2023 per the survey \[S\d+\] \(REPORTED\)$",
                          digest, re.M)) == len(world.briefs)
    assert not any(f"[S{sid}]" in digest for sid in world.briefs)
    index = digest.split("SOURCE INDEX", 1)[1]
    assert re.findall(r"^\[S(\d+)\]", index, re.M)
    assert all(lr.pit_row_admissible(ledger[int(sid)], POLICY) for sid in re.findall(r"^\[S(\d+)\]", index, re.M))
    # Without the wall the same records would have shown the briefs.
    unwalled, _ = real_digest(*args, **{key: value for key, value in kwargs.items() if key != "admissible"})
    assert unwalled != digest and any(f"[S{sid}]" in unwalled for sid in world.briefs)


def test_deterministic_sections_publish_only_admissible_findings(tmp_path, bridge, monkeypatch):
    """With every writer failing, the fallback bullets are built from walled
    records: a finding only a withheld brief backs is never published (uncited
    after renumbering), and a mixed finding keeps only its survey marker."""
    rc, meta, plog, world, out = run_pit_engine(tmp_path, bridge, monkeypatch, world_cls=SilentWriterWorld)
    assert rc == 0, meta.get("error")
    synth = _load(out / "v3" / "synth.json")
    origins = {section["origin"] for section in synth["sections"]}
    assert "fallback" in origins and "writer" not in origins
    report = (out / "research_report.md").read_text(encoding="utf-8")
    sources = _load(out / "sources.json")
    assert world.briefs
    assert "250 GW of capacity by 2030" not in report
    assert not any(domain in report + json.dumps(sources) for domain in ("undated-", "//late-", "sameday-"))
    # Each mixed finding is published with exactly one marker: its survey's.
    tails = re.findall(r"Analysts expect 12% annual demand growth through 2027(.*)$", report, re.M)
    assert tails
    for tail in tails:
        position = re.fullmatch(r" \[S(\d+)\]", tail)
        assert position, tail
        assert "//dated-" in sources[int(position.group(1)) - 1]["url"]
    # Every sentence of a fallback bullet carries a citation (no claim left unsourced).
    bullets = [line for line in report.splitlines() if line.startswith("- ") and "GW" in line]
    assert bullets and all(re.search(r"\[S\d+\]", line) for line in bullets)
    audit = _load(out / lr.POINT_IN_TIME_FILENAME)
    assert audit["status"] == "date_verified"
    assert audit["streams"]["cited"] == _independent_cited(sources)


def test_point_in_time_json_records_the_exact_counters_of_the_run(tmp_path, bridge, monkeypatch):
    rc, meta, plog, world, out = run_pit_engine(tmp_path, bridge, monkeypatch)
    assert rc == 0, meta.get("error")
    audit = _load(out / lr.POINT_IN_TIME_FILENAME)
    sources = _load(out / "sources.json")
    gates = meta["tools"]["pit"]
    kiqs = len(world.briefs)
    assert kiqs == meta["kiqs"]["completed"] >= 4

    assert list(audit) == ["schema", "as_of", "same_day_policy", "undated_policy", "streams", "wall",
                           "parametric_suspects", "leak_guard", "parametric_knowledge", "live_page_text",
                           "status"]
    assert (audit["schema"], audit["as_of"], audit["same_day_policy"], audit["undated_policy"]) == (
        "drf-point-in-time/v1", AS_OF, "exclude", "drop")
    assert (audit["leak_guard"], audit["parametric_knowledge"], audit["live_page_text"]) == (
        "source_publication_dates_only", "not_guarded", "labelled_not_archived")

    # Search: every fresh search showed one undated brief and one dated survey and
    # dropped the late release and the same-day note.
    searches = meta["tools"]["searches"] - meta["tools"]["cached_searches"]
    assert searches > kiqs
    assert audit["streams"]["search"] == {
        "checked": 4 * searches, "admitted": searches, "same_day": 0, "unverifiable": searches,
        "late": 2 * searches, "no_in_window_results": 0, "bounded_queries": 0, "unbounded_queries": searches,
        "scope": "run", "attempts_counted": 1, "attempts_started": 1}
    # Fetch: per KIQ, the brief withheld undated and the survey admitted.
    assert audit["streams"]["fetch"] == {
        "checked": 2 * kiqs, "admitted": kiqs, "same_day": 0, "unverifiable": kiqs, "late": 0,
        "undated_withheld": kiqs, "undated_admitted": 0, "refused_before_fetch": 0, "withheld_repeats": 0,
        "scope": "run", "attempts_counted": 1, "attempts_started": 1}
    assert (gates["search_admitted_shown"], gates["fetch_undated_withheld"]) == (searches, kiqs)
    # Cited: an independent re-check of sources.json; every cited survey predates the as-of.
    assert audit["streams"]["cited"] == _independent_cited(sources) == {
        "checked": len(sources), "admitted": len(sources), "same_day": 0, "unverifiable": 0, "late": 0}
    # The wall: each KIQ's brief cited by its findings was kept out; per KIQ the
    # brief-only finding, the mixed finding and the conflict (each carries the brief's
    # marker) left the digest whole, so no marker was stripped (FU-2).
    assert audit["wall"] == {"sids_withheld": kiqs, "digest_lines_dropped": 3 * kiqs,
                             "digest_markers_stripped": 0}
    assert _load(out / "v3" / "state.json")[lr.PIT_DIGEST_WALL_KEY] == lr.PIT_DIGEST_WALL_RULE
    assert audit["status"] == "date_verified"
    assert meta["point_in_time"]["audit"] == {key: value for key, value in audit.items()
                                              if key not in ("schema", "as_of")}
    # TIME-7's block is extended, not replaced.
    assert {key: meta["point_in_time"][key] for key in ("as_of", "hindcast", "markets")} == {
        "as_of": AS_OF, "hindcast": True, "markets": "withheld"}
    assert any("wrote point_in_time.json (date_verified" in message for kind, message in plog.lines if kind == "ok")
    assert not any("counts are partial" in message for kind, message in plog.lines)
    # The parent records the audit the engine wrote, bytes as on disk.
    raw = (out / lr.POINT_IN_TIME_FILENAME).read_bytes()
    pin = {"as_of": AS_OF, "pit": {"gates": True, "same_day": "exclude", "undated": "drop"}}
    assert hp.research_audit_record(json.loads(raw), hashlib.sha256(raw).hexdigest(), pin=pin) == {
        "status": "date_verified", "sha256": hashlib.sha256(raw).hexdigest()}


def test_parametric_suspects_are_counted_and_kept(tmp_path, bridge, monkeypatch):
    rc, meta, plog, world, out = run_pit_engine(tmp_path, bridge, monkeypatch)
    assert rc == 0, meta.get("error")
    audit = _load(out / lr.POINT_IN_TIME_FILENAME)
    # The event of 2024-09-15, the actual dated 2024-08 and the untyped row dated
    # 2024-07-15; never the 2023 actual or the 2027 forecast.
    assert audit["parametric_suspects"] == {"timeline": 1, "quant": 2}
    quant = _load(out / "quantitative.json")
    timeline = _load(out / "timeline.json")
    assert sorted(row["as_of_date"] for row in quant) == ["2023-12-31", "2024-07-15", "2024-08", "2027"]
    assert sorted(row["date"] for row in timeline) == ["2023-12-31", "2024-09-15"]


def test_undated_flag_policy_labels_the_verdict(tmp_path, bridge, monkeypatch):
    rc, meta, plog, world, out = run_pit_engine(tmp_path, bridge, monkeypatch, undated="flag")
    assert rc == 0, meta.get("error")
    audit = _load(out / lr.POINT_IN_TIME_FILENAME)
    sources = _load(out / "sources.json")
    assert audit["undated_policy"] == "flag"
    # Stored undated briefs may be cited; the re-check counts them undated.
    assert audit["streams"]["cited"] == _independent_cited(sources)
    assert audit["streams"]["cited"]["unverifiable"] >= 1 and audit["streams"]["cited"]["late"] == 0
    assert audit["streams"]["fetch"]["undated_admitted"] == len(world.briefs)
    assert audit["status"] == "date_verified_with_unverifiable"
    raw = (out / lr.POINT_IN_TIME_FILENAME).read_bytes()
    pin = {"as_of": AS_OF, "pit": {"gates": True, "same_day": "exclude", "undated": "flag"}}
    assert hp.research_audit_record(json.loads(raw), "ab", pin=pin) == {
        "status": "date_verified_with_unverifiable", "sha256": "ab"}


def test_a_late_row_in_sources_json_is_re_audited_as_violated(tmp_path, bridge, monkeypatch):
    rc, meta, plog, world, out = run_pit_engine(tmp_path, bridge, monkeypatch)
    assert rc == 0, meta.get("error")
    audit = _load(out / lr.POINT_IN_TIME_FILENAME)
    sources = _load(out / "sources.json")
    assert lr.pit_audit_status(lr.pit_cited_audit(sources, POLICY), "drop") == audit["status"] == "date_verified"
    injected = sources + [{"url": "https://wire.example/story", "date": "2024-07-02"}]
    (out / "sources.json").write_text(json.dumps(injected), encoding="utf-8")
    cited = lr.pit_cited_audit(_load(out / "sources.json"), POLICY)
    assert cited["late"] == 1 and cited["checked"] == len(sources) + 1
    assert lr.pit_audit_status(cited, "drop") == "violated"
    reaudit = lr.point_in_time_payload(POLICY, gate_counts=meta["tools"]["pit"], sources=injected,
                                       suspects=audit["parametric_suspects"], wall=audit["wall"])
    assert reaudit["status"] == "violated"
    assert reaudit["streams"]["search"] == audit["streams"]["search"]


_LATE_ROW = {"url": "https://wire.example/2024/07/02/x", "date": "2024-07-02"}


@pytest.mark.parametrize("where", ["rows", "disk"])
def test_the_engine_audit_re_checks_the_published_sources_json(tmp_path, bridge, monkeypatch, where):
    """finalize's own audit re-reads sources.json as published: a late-dated row that
    reached it (built into the rows, or written over the file later in finalize) is
    counted late whatever the gates decided, and the verdict is violated."""
    if where == "rows":
        real_rows = lr._Engine._source_rows
        monkeypatch.setattr(lr._Engine, "_source_rows", lambda self, order: [*real_rows(self, order), dict(_LATE_ROW)])
    else:
        real_analytics = lr._Engine._analytics

        def analytics_then_rewrite(self, sources, actors_obj):
            real_analytics(self, sources, actors_obj)
            path = self.out_dir / "sources.json"
            path.write_text(json.dumps([*_load(path), dict(_LATE_ROW)]), encoding="utf-8")

        monkeypatch.setattr(lr._Engine, "_analytics", analytics_then_rewrite)
    rc, meta, plog, world, out = run_pit_engine(tmp_path, bridge, monkeypatch)
    assert rc == 0, meta.get("error")
    sources = _load(out / "sources.json")
    assert sources[-1] == _LATE_ROW
    audit = _load(out / lr.POINT_IN_TIME_FILENAME)
    assert audit["streams"]["cited"] == _independent_cited(sources)
    assert audit["streams"]["cited"]["late"] == 1 and audit["streams"]["cited"]["checked"] == len(sources)
    assert audit["status"] == meta["point_in_time"]["audit"]["status"] == "violated"
    assert any("wrote point_in_time.json (violated" in message for kind, message in plog.lines if kind == "warn")


def test_a_resumed_attempt_audits_the_gate_counts_of_the_whole_run(tmp_path, bridge, monkeypatch):
    rc, meta, plog, world, out = run_pit_engine(tmp_path, bridge, monkeypatch)
    assert rc == 0, meta.get("error")
    first = _load(out / lr.POINT_IN_TIME_FILENAME)
    saved = _load(out / "v3" / lr.PIT_COUNTS_FILENAME)
    assert saved == {"attempts": 1, "attempts_closed": 1, "counts_complete": True,
                     "counts": lr.pit_sum_counts(meta["tools"]["pit"])}
    assert _load(out / "v3" / "state.json")[lr.PIT_ATTEMPTS_KEY] == 1
    assert first["streams"]["search"]["checked"] > 0 and first["streams"]["fetch"]["checked"] > 0
    # A second attempt resumes the work dir: it reuses every research phase (no search,
    # no fetch, so its own gate counts are all zero) and finalizes again.
    rc, meta, plog, world, out = run_pit_engine(tmp_path, bridge, monkeypatch)
    assert rc == 0, meta.get("error")
    assert meta["tools"]["searches"] == meta["tools"]["fetches"] == 0
    assert not any(meta["tools"]["pit"].values())
    second = _load(out / lr.POINT_IN_TIME_FILENAME)
    for stream in ("search", "fetch"):
        assert second["streams"][stream] == dict(first["streams"][stream], attempts_counted=2, attempts_started=2)
        assert second["streams"][stream]["scope"] == "run"
    assert second["streams"]["cited"] == first["streams"]["cited"]
    assert second["wall"] == first["wall"]
    assert second["status"] == first["status"] == "date_verified"
    assert _load(out / "v3" / lr.PIT_COUNTS_FILENAME) == {"attempts": 2, "attempts_closed": 2,
                                                          "counts_complete": True, "counts": saved["counts"]}
    assert not any("counts are partial" in message for kind, message in plog.lines)


def test_a_digest_reused_from_an_earlier_build_leaves_its_wall_counts_unknown(tmp_path, bridge, monkeypatch):
    """A resumed attempt reuses digest.md byte for byte; when state.json does not record
    that it was built with the current wall rule (an earlier build wrote it), the audit
    reports its digest counts as unknown instead of recounting a rule the writers did not
    see, and its verdict is unaffected."""
    rc, meta, plog, world, out = run_pit_engine(tmp_path, bridge, monkeypatch)
    assert rc == 0, meta.get("error")
    first = _load(out / lr.POINT_IN_TIME_FILENAME)
    digest = (out / "v3" / "digest.md").read_bytes()
    state_path = out / "v3" / "state.json"
    state = _load(state_path)
    del state[lr.PIT_DIGEST_WALL_KEY]
    state_path.write_text(json.dumps(state), encoding="utf-8")
    rc, meta, plog, world, out = run_pit_engine(tmp_path, bridge, monkeypatch)
    assert rc == 0, meta.get("error")
    second = _load(out / lr.POINT_IN_TIME_FILENAME)
    assert (out / "v3" / "digest.md").read_bytes() == digest
    assert second["wall"] == {"sids_withheld": first["wall"]["sids_withheld"], "digest_lines_dropped": None,
                              "digest_markers_stripped": None}
    assert meta["point_in_time"]["audit"]["wall"] == second["wall"]
    assert second["status"] == first["status"] == "date_verified"
    assert any("leaves its digest counts unknown" in message for kind, message in plog.lines if kind == "warn")


class _Killed(BaseException):
    """Stands in for a SIGKILL (the research watchdog, a user cancel): the attempt stops
    where it is and never reaches its exit path."""


def test_a_killed_attempt_leaves_partial_not_whole_run_counts(tmp_path, bridge, monkeypatch):
    with monkeypatch.context() as patch:
        def killed(self):
            raise _Killed()

        patch.setattr(lr._Engine, "phase_synthesize", killed)
        patch.setattr(lr._Engine, "attach_telemetry", lambda self: None)
        with pytest.raises(_Killed):
            run_pit_engine(tmp_path, bridge, monkeypatch)
    out = tmp_path / "out"
    # Every phase exit and KIQ record saved the killed attempt's counts; it never closed them.
    saved = _load(out / "v3" / lr.PIT_COUNTS_FILENAME)
    assert (saved["attempts"], saved["attempts_closed"], saved["counts_complete"]) == (1, 0, True)
    assert saved["counts"]["search_admitted_shown"] > 0 and saved["counts"]["fetch_admitted"] > 0
    assert _load(out / "v3" / "state.json")[lr.PIT_ATTEMPTS_KEY] == 1
    # The resumed attempt finishes finalize: its audit keeps the killed attempt's counts
    # but says they are partial (a lower bound), and its verdict is unaffected.
    rc, meta, plog, world, out = run_pit_engine(tmp_path, bridge, monkeypatch)
    assert rc == 0, meta.get("error")
    audit = _load(out / lr.POINT_IN_TIME_FILENAME)
    expected = lr.pit_gate_streams(lr.pit_sum_counts(saved["counts"], meta["tools"]["pit"]), attempts=2,
                                   attempts_started=2, complete=False)
    for stream in ("search", "fetch"):
        assert audit["streams"][stream] == expected[stream]
        assert audit["streams"][stream]["scope"] == "partial" and audit["streams"][stream]["checked"] > 0
    assert audit["status"] == "date_verified"
    assert meta["point_in_time"]["audit"]["streams"]["search"]["scope"] == "partial"
    assert any("counts are partial (0 of the 1 earlier attempts saved their final counts)" in message
               for kind, message in plog.lines if kind == "warn")
    assert any("search and fetch counts partial" in message for kind, message in plog.lines)
    # Partial stays partial: a later attempt still cannot vouch for the whole run.
    rc, meta, plog, world, out = run_pit_engine(tmp_path, bridge, monkeypatch)
    assert rc == 0, meta.get("error")
    third = _load(out / lr.POINT_IN_TIME_FILENAME)
    assert {key: third["streams"]["search"][key] for key in ("scope", "attempts_counted", "attempts_started")} == {
        "scope": "partial", "attempts_counted": 3, "attempts_started": 3}
    assert any("already lost" in message for kind, message in plog.lines if kind == "warn")


@pytest.mark.parametrize("loss", ["missing", "truncated"])
def test_lost_earlier_counts_are_reported_partial(tmp_path, bridge, monkeypatch, loss):
    rc, meta, plog, world, out = run_pit_engine(tmp_path, bridge, monkeypatch)
    assert rc == 0, meta.get("error")
    first = _load(out / lr.POINT_IN_TIME_FILENAME)
    path = out / "v3" / lr.PIT_COUNTS_FILENAME
    if loss == "missing":
        path.unlink()
    else:
        path.write_text("{truncated", encoding="utf-8")
    rc, meta, plog, world, out = run_pit_engine(tmp_path, bridge, monkeypatch)
    assert rc == 0, meta.get("error")
    second = _load(out / lr.POINT_IN_TIME_FILENAME)
    # Only this attempt's (zero) counts are known: never reported as the whole run's.
    for stream in ("search", "fetch"):
        assert second["streams"][stream]["checked"] == 0
        assert {key: second["streams"][stream][key] for key in ("scope", "attempts_counted", "attempts_started")} \
            == {"scope": "partial", "attempts_counted": 1, "attempts_started": 2}
    assert second["status"] == first["status"] == "date_verified"
    reason = f"no {lr.PIT_COUNTS_FILENAME}" if loss == "missing" else f"{lr.PIT_COUNTS_FILENAME} unreadable"
    assert any(reason in message for kind, message in plog.lines if kind == "warn")
    assert _load(path)["counts_complete"] is False
    # The loss is remembered by the next attempt.
    rc, meta, plog, world, out = run_pit_engine(tmp_path, bridge, monkeypatch)
    assert rc == 0, meta.get("error")
    third = _load(out / lr.POINT_IN_TIME_FILENAME)
    assert {key: third["streams"]["fetch"][key] for key in ("scope", "attempts_counted", "attempts_started")} == {
        "scope": "partial", "attempts_counted": 2, "attempts_started": 3}


_SAVED = {"attempts": 2, "attempts_closed": 2, "counts_complete": True, "counts": {"fetch_admitted": 3}}


@pytest.mark.parametrize("saved, resumed, before, expected, why", [
    # A fresh work dir starts from nothing, complete.
    (None, False, None, lr.PitPriorCounts(started=1), ""),
    (json.dumps(_SAVED), True, 2, lr.PitPriorCounts(attempts=2, closed=2, counts={"fetch_admitted": 3}, started=3),
     ""),
    (None, True, 1, lr.PitPriorCounts(started=2, complete=False), "no pit_counts.json"),
    ("{truncated", True, 1, lr.PitPriorCounts(started=2, complete=False), "pit_counts.json unreadable"),
    # The last attempt was killed after saving at a phase exit, or before saving at all.
    (json.dumps(dict(_SAVED, attempts_closed=1)), True, 2,
     lr.PitPriorCounts(attempts=2, closed=1, counts={"fetch_admitted": 3}, started=3, complete=False),
     "1 of the 2 earlier attempts saved their final counts"),
    (json.dumps(_SAVED), True, 3,
     lr.PitPriorCounts(attempts=2, closed=2, counts={"fetch_admitted": 3}, started=4, complete=False),
     "2 of the 3 earlier attempts saved their final counts"),
    (json.dumps(dict(_SAVED, counts_complete=False)), True, 2,
     lr.PitPriorCounts(attempts=2, closed=2, counts={"fetch_admitted": 3}, started=3, complete=False),
     "already lost"),
    # No counter in state.json: never fewer attempts started than counted.
    (json.dumps(_SAVED), True, None,
     lr.PitPriorCounts(attempts=2, closed=2, counts={"fetch_admitted": 3}, started=3, complete=False),
     "state.json records no pit_attempts_started"),
] + [(json.dumps(dict(_SAVED, **bad)), True, 2, lr.PitPriorCounts(started=3, complete=False), "unreadable")
     for bad in ({"attempts": 0}, {"attempts": True}, {"attempts_closed": 3}, {"attempts_closed": -1},
                 {"counts_complete": "yes"}, {"counts": [1]})])
def test_pit_prior_counts(saved, resumed, before, expected, why):
    prior, reason = lr.pit_prior_counts(saved, resumed=resumed, started_before=before)
    assert prior == expected
    assert (why in reason) if why else reason == ""


def test_pit_sum_counts():
    assert lr.pit_sum_counts({"a": 1, "b": 2}, None, {"a": 3, "c": True, "d": -1, "e": "4", 5: 1}) == {
        "a": 4, "b": 2, "c": 0, "d": 0, "e": 0}
    assert lr.pit_sum_counts() == {}


def test_a_failed_audit_leaves_no_point_in_time_json(tmp_path, bridge, monkeypatch):
    (tmp_path / "out").mkdir(parents=True)
    # An earlier attempt's audit never survives this attempt's finalize.
    (tmp_path / "out" / lr.POINT_IN_TIME_FILENAME).write_text('{"status": "date_verified"}', encoding="utf-8")

    def boom(*args, **kwargs):
        raise RuntimeError("audit exploded")

    monkeypatch.setattr(lr, "point_in_time_payload", boom)
    rc, meta, plog, world, out = run_pit_engine(tmp_path, bridge, monkeypatch)
    assert rc == 0, meta.get("error")
    assert not (out / lr.POINT_IN_TIME_FILENAME).exists()
    assert meta["point_in_time"]["audit"] == {"status": "unavailable"}
    assert any(error["helper"] == "point_in_time" for error in meta["analytics_errors"])


# =============================================================== live runs unchanged

def test_live_run_writes_no_audit_and_an_unwalled_digest(tmp_path, bridge, monkeypatch):
    calls, real_digest = _spy_digest(monkeypatch)
    rc, meta, plog, world, out = run_pit_engine(tmp_path, bridge, monkeypatch, gated=False)
    assert rc == 0, meta.get("error")
    assert not (out / lr.POINT_IN_TIME_FILENAME).exists()
    assert not (out / "v3" / lr.PIT_COUNTS_FILENAME).exists()
    state = _load(out / "v3" / "state.json")
    assert lr.PIT_ATTEMPTS_KEY not in state and lr.PIT_DIGEST_WALL_KEY not in state
    assert "point_in_time" not in meta and "pit" not in meta["tools"]
    sources = _load(out / "sources.json")
    assert sources and all("pit_status" not in row for row in sources)
    # The live digest is the pre-TIME-9 call's bytes: no wall is passed.
    (args, kwargs, (digest_text, _dropped)), = calls
    assert kwargs == {"dates": False, "admissible": None}
    assert real_digest(*args, dates=False) == (digest_text, _dropped)
    assert (out / "v3" / "digest.md").read_text(encoding="utf-8") == digest_text
    # Live, the briefs and the late releases are ordinary sources.
    assert "undated-" in digest_text and "//late-" in json.dumps(_load(out / "v3" / "sources_ledger.json"))


@pytest.mark.parametrize("gates", [None, "false"])
def test_pinned_run_without_gates_builds_an_unwalled_digest(tmp_path, bridge, monkeypatch, gates):
    """A hindcast pin (RESEARCH_AS_OF) with RESEARCH_PIT_GATES unset or false has no
    citation wall: the digest is the unwalled call's bytes and no audit is written."""
    monkeypatch.setenv("RESEARCH_AS_OF", AS_OF)
    if gates is not None:
        monkeypatch.setenv("RESEARCH_PIT_GATES", gates)
    calls, real_digest = _spy_digest(monkeypatch)
    rc, meta, plog, world, out = run_pit_engine(tmp_path, bridge, monkeypatch, gated=False)
    assert rc == 0, meta.get("error")
    assert meta["point_in_time"]["as_of"] == AS_OF and "audit" not in meta["point_in_time"]
    assert not (out / lr.POINT_IN_TIME_FILENAME).exists()
    state = _load(out / "v3" / "state.json")
    assert lr.PIT_ATTEMPTS_KEY not in state and lr.PIT_DIGEST_WALL_KEY not in state
    (args, kwargs, (digest_text, dropped)), = calls
    assert kwargs == {"dates": False, "admissible": None}
    assert real_digest(*args, dates=False) == (digest_text, dropped)
    assert (out / "v3" / "digest.md").read_text(encoding="utf-8") == digest_text
    # Unwalled, the briefs' findings reach the digest with their markers.
    assert "undated-" in digest_text and "250 GW of capacity by 2030" in digest_text
    assert "Analysts expect 12% annual demand growth" in digest_text


# =============================================================== pure helpers

def _row(sid, url, **fields):
    return {"sid": sid, "url": url, "fetched": False, **fields}


@pytest.mark.parametrize("row, undated, expected", [
    (_row(1, "https://a.example/x", published="2024-04-15"), "drop", True),
    (_row(2, "https://a.example/x"), "drop", False),                             # snippet-only, undated
    (_row(3, "https://a.example/x"), "flag", True),
    (_row(4, "https://a.example/2024/03/02/x"), "drop", True),                   # URL date admits
    (_row(5, "https://a.example/2024/07/02/x"), "flag", False),                  # URL date late
    (_row(6, "https://a.example/x", published="2024-06-01"), "flag", False),     # same day, excluded
    (_row(7, "https://a.example/x", published="2024-03-01", modified_at="2024-06-20"), "flag", False),
    (_row(8, "https://a.example/x", pit_status="late", published="2024-01-01"), "flag", False),
    (_row(9, "https://a.example/x", pit_status="undated_withheld"), "flag", False),
    (_row(10, "https://a.example/x", pit_status="admitted", fetched=True), "drop", True),
    (_row(11, "https://a.example/x", pit_status="unverifiable", fetched=True), "drop", True),
])
def test_pit_row_admissible(row, undated, expected):
    assert lr.pit_row_admissible(row, rg.PitPolicy(as_of=dt.date(2024, 6, 1), undated=undated)) is expected


def test_same_day_include_admits_the_as_of_day():
    row = _row(1, "https://a.example/x", published="2024-06-01")
    include = rg.PitPolicy(as_of=dt.date(2024, 6, 1), same_day="include")
    assert lr.pit_row_admissible(row, include)
    assert lr.pit_cited_audit([{"url": row["url"], "date": "2024-06-01"}], include) == {
        "checked": 1, "admitted": 0, "same_day": 1, "unverifiable": 0, "late": 0}


def test_pit_audit_status():
    clean = {"checked": 2, "admitted": 2, "same_day": 0, "unverifiable": 0, "late": 0}
    assert lr.pit_audit_status(clean, "drop") == "date_verified"
    assert lr.pit_audit_status(clean, "flag") == "date_verified_with_unverifiable"
    assert lr.pit_audit_status(dict(clean, unverifiable=1), "drop") == "date_verified_with_unverifiable"
    assert lr.pit_audit_status(dict(clean, late=1, unverifiable=1), "flag") == "violated"
    assert lr.pit_cited_audit(["not a row"], POLICY)["unverifiable"] == 1
    # A report the wall left without any source verified no date: never date_verified.
    nothing = lr.pit_cited_audit([], POLICY)
    assert nothing == {"checked": 0, "admitted": 0, "same_day": 0, "unverifiable": 0, "late": 0}
    assert lr.pit_audit_status(nothing, "drop") == "date_verified_with_unverifiable"
    assert lr.pit_audit_status({}, "drop") == "date_verified_with_unverifiable"


def test_build_digest_wall_leaves_out_every_line_with_an_inadmissible_marker():
    """FU-2: a line carrying a withheld source's marker is left out of the digest whole, even
    beside an admissible marker: the markers do not say which part of it each source backs."""
    ledger = {1: {"sid": 1, "title": "Survey", "domain": "a.example", "tier": "S2", "fetched": True},
              2: {"sid": 2, "title": "Brief", "domain": "b.example", "tier": "S3", "fetched": False}}
    record = {"id": "K1", "question": "What is capacity?",
              "facts": [{"text": "Capacity reached 176 GW [S1][S2]", "tag": "VERIFIED", "sids": [1, 2]},
                        {"text": "A brief claims 250 GW [S2]", "tag": "REPORTED", "sids": [2]},
                        {"text": "Imports fell 5% [S1]", "tag": "VERIFIED", "sids": [1]},
                        {"text": "No marker here", "tag": "REPORTED"}],
              "conflicts": ["Sources differ [S2]", "Scope differs [S1] and [S2]"],
              "open_questions": ["Grid timelines?"]}
    text, dropped = lr.build_digest([record], ledger.get, 20000, "English", admissible=lambda sid: sid == 1)
    assert dropped == 0
    assert "- Imports fell 5% [S1] (VERIFIED)" in text and "Grid timelines?" in text
    assert "176 GW" not in text and "250 GW" not in text and "[S2]" not in text
    assert "Sources differ" not in text and "Scope differs" not in text
    assert text.split("SOURCE INDEX\n", 1)[1] == "[S1] Survey — a.example (" + rg.tier_label("S2") + ", fetched)"
    assert record["facts"][0]["text"] == "Capacity reached 176 GW [S1][S2]"   # the record is unchanged
    # Everything admissible: byte-identical to the digest without the wall.
    assert lr.build_digest([record], ledger.get, 20000, "English", admissible=lambda sid: True) == \
        lr.build_digest([record], ledger.get, 20000, "English")
    walled, lines, markers = lr.pit_wall_record(record, lambda sid: sid == 1)
    assert (lines, markers) == (4, 0)
    assert [fact["text"] for fact in walled["facts"]] == ["Imports fell 5% [S1]", "No marker here"]
    assert walled["conflicts"] == [] and walled["open_questions"] == ["Grid timelines?"]
    # Claim by claim (the deterministic sections' rule) the co-cited finding keeps S1.
    walled, lines, markers = lr.pit_wall_record(record, lambda sid: sid == 1, per_claim=True)
    assert (lines, markers) == (3, 1) and walled["facts"][0]["text"] == "Capacity reached 176 GW [S1]"


def test_a_question_quoting_a_withheld_marker_is_withheld_too():
    """FU-2: a gap follow-up's question can quote an open question with its markers; the digest
    header then shows the KIQ id alone, so the writers never read the withheld source's claim
    there.  A question left whole keeps the old header, also in a live run without one."""
    ledger = {1: {"sid": 1, "title": "Survey", "domain": "a.example", "tier": "S2", "fetched": True},
              2: {"sid": 2, "title": "Brief", "domain": "b.example", "tier": "S3", "fetched": False}}
    record = {"id": "G1F1", "question": "Does the 250 GW brief projection hold [S2]?",
              "facts": [{"text": "Imports fell 5% [S1]", "tag": "VERIFIED", "sids": [1]}]}
    text, _ = lr.build_digest([record], ledger.get, 20000, "English", admissible=lambda sid: sid == 1)
    assert "### G1F1\n" in text and "250 GW" not in text and "[S2]" not in text
    walled, lines, markers = lr.pit_wall_record(record, lambda sid: sid == 1)
    assert (walled["question"], walled["question_withheld"], lines, markers) == ("", True, 1, 0)
    assert record["question"] == "Does the 250 GW brief projection hold [S2]?"   # the record is unchanged
    # Admissible question: the header is unchanged; a record without a question keeps the old form.
    kept = dict(record, question="Does capacity reach 200 GW [S1]?")
    assert "### G1F1 — Does capacity reach 200 GW [S1]?" in lr.build_digest(
        [kept], ledger.get, 20000, "English", admissible=lambda sid: sid == 1)[0]
    bare = {"id": "K9", "facts": [{"text": "Imports fell 5% [S1]", "tag": "VERIFIED", "sids": [1]}]}
    assert "### K9 — \n" in lr.build_digest([bare], ledger.get, 20000, "English")[0]


def _wall_counts_engine(record, admissible, state):
    """The attributes :meth:`_Engine._pit_wall_counts` reads; ``state`` is state.json's data."""
    logs = []
    engine = types.SimpleNamespace(
        _pit_admissible=admissible, records={"K1": record}, kiqs=[types.SimpleNamespace(id="K1")],
        _evidence_sids=lambda: [1, 2, 3], state=lr._RunState(None, state, lambda path, text: None),
        log=lambda kind, message: logs.append((kind, message)))
    return engine, logs


def test_digest_never_shows_a_withheld_claim_beside_or_under_an_admissible_marker():
    """FU-2 (TIME-9 open issue): with S2 withheld, stripping its marker would show the brief's
    250 GW under [S1] or beside it uncited, and a writer restating it with [S1] would publish
    a withheld source's claim looking properly cited."""
    ledger = {1: {"sid": 1, "title": "Survey", "domain": "a.example", "tier": "S2", "fetched": True},
              2: {"sid": 2, "title": "Brief", "domain": "b.example", "tier": "S3", "fetched": False},
              3: {"sid": 3, "title": "Census", "domain": "c.example", "tier": "S1", "fetched": True}}
    mixed = ["Capacity reached 176 GW [S1], while a brief projects 250 GW [S2]",       # interleaved
             "Capacity reached 176 GW, while a brief projects 250 GW by 2030 [S1][S2]",  # trailing co-citation
             "Capacity reached 176 GW and operators plan 250 GW by 2030 [S1], [S2]",
             "Capacity 176 GW [S1] - [S2]: 250 GW planned",
             "装机容量达176GW[S1]，简报预测250GW[S2]",
             "Demand grew 12% [S3][S2]"]
    record = {"id": "K1", "facts": [{"text": text, "tag": "REPORTED", "sids": [1, 2, 3]} for text in mixed]
              + [{"text": "Imports fell 5% [S3]", "tag": "VERIFIED", "sids": [3]}],
              "conflicts": ["Census and brief differ on 2030 [S3][S2]"]}
    text, _ = lr.build_digest([record], ledger.get, 20000, "English", admissible=lambda sid: sid != 2)
    assert "250" not in text and "176" not in text and "Demand grew" not in text and "differ" not in text
    assert "- Imports fell 5% [S3] (VERIFIED)" in text and "[S2]" not in text
    # The wall counters recount the rule the digest was built with (state.json records it).
    engine, logs = _wall_counts_engine(record, lambda sid: sid != 2,
                                       {lr.PIT_DIGEST_WALL_KEY: lr.PIT_DIGEST_WALL_RULE})
    assert lr._Engine._pit_wall_counts(engine) == {
        "sids_withheld": 1, "digest_lines_dropped": 7, "digest_markers_stripped": 0}
    assert logs == []


@pytest.mark.parametrize("state", [{}, {lr.PIT_DIGEST_WALL_KEY: "per_claim"}])
def test_wall_counts_are_unknown_for_a_digest_built_under_another_rule(state):
    """A resumed attempt reuses digest.md as written (the writers' shared prefix); when
    state.json does not record that it was built with the current rule, the digest counts
    in point_in_time.json are unknown rather than recounted with a rule the writers did
    not see."""
    record = {"id": "K1", "facts": [{"text": "Capacity reached 176 GW [S1][S2]", "tag": "VERIFIED"}]}
    engine, logs = _wall_counts_engine(record, lambda sid: sid != 2, state)
    assert lr._Engine._pit_wall_counts(engine) == {
        "sids_withheld": 1, "digest_lines_dropped": None, "digest_markers_stripped": None}
    assert [kind for kind, message in logs if "leaves its digest counts unknown" in message] == ["warn"]


def _walled_fallback_engine(records, admissible):
    """The attributes the deterministic-section helpers read, under the gates."""
    engine = types.SimpleNamespace(
        records=records, language="English", pit=POLICY, _pit_admissible=admissible,
        _outline=lambda index: lr.OutlineSection(index=index, title=f"Capacity {index}", kiq_ids=["K1"],
                                                 focus="capacity"),
        log=lambda kind, message: None)
    for name in ("_report_records", "_fallback_section", "_refill_emptied"):
        setattr(engine, name, types.MethodType(getattr(lr._Engine, name), engine))
    return engine


def test_deterministic_sections_draw_on_walled_records():
    record = {"id": "K1", "facts": [
        {"text": "Capacity reached 176 GW [S1][S2]", "tag": "VERIFIED", "sids": [1, 2]},
        {"text": "A brief claims 250 GW [S2]", "tag": "REPORTED", "sids": [2]}]}
    engine = _walled_fallback_engine({"K1": record}, lambda sid: sid == 1)
    assert engine._fallback_section(engine._outline(1)) == "- Capacity reached 176 GW [S1]"
    emptied = [{"index": 1, "title": "Capacity 1", "is_scenario": False, "body": "", "origin": "writer"}]
    assert engine._refill_emptied(emptied) == []
    assert (emptied[0]["body"], emptied[0]["origin"]) == ("- Capacity reached 176 GW [S1]", "fallback")
    # The walled finding is already published, so an emptied section is dropped rather
    # than refilled with a copy of it (the dedup keys are those of the walled texts).
    sections = [{"index": 1, "title": "Capacity 1", "is_scenario": False, "origin": "fallback",
                 "body": "- Capacity reached 176 GW [S1]"},
                {"index": 2, "title": "Capacity 2", "is_scenario": False, "body": "", "origin": "writer"}]
    assert engine._refill_emptied(sections) == ["Capacity 2"]
    assert (sections[1]["body"], sections[1]["origin"]) == ("", "dropped")
    assert record["facts"][0]["text"] == "Capacity reached 176 GW [S1][S2]"   # the record is unchanged
    # Nothing admissible: the no-evidence line, never an uncited claim.
    blind = _walled_fallback_engine({"K1": record}, lambda sid: False)
    assert blind._fallback_section(blind._outline(1)) == f"- {lr._text('English', 'no_evidence')}"
    # Without the gates the records are used as they are.
    assert lr._Engine._report_records(types.SimpleNamespace(records={"K1": record}, pit=None)) == {"K1": record}


def test_citation_clusters_group_the_markers_of_one_claim():
    assert lr._citation_clusters("a [S1][S2], b [S3], [S4]; c [S5] d") == [[1, 2], [3, 4], [5]]
    assert lr._citation_clusters("电量 [S1]，[S2] 增长 [S3]") == [[1, 2], [3]]
    assert lr._citation_clusters("no markers") == []


def test_published_findings_keep_no_claim_only_an_inadmissible_source_backs():
    """Claim by claim (``per_claim``, the deterministic sections) a finding is kept only
    when each of its claims keeps an admissible source, so a sub-claim only a withheld
    source backs is never published uncited next to an admissible marker; by default
    (the digest and its counters, FU-2) every finding carrying a withheld marker is left
    out whole."""
    interleaved = {"text": "Capacity reached 176 GW [S1], while a brief projects 250 GW [S2]", "tag": "REPORTED",
                   "sids": [1, 2]}
    leading = {"text": "A brief projects 250 GW [S2]; capacity reached 176 GW [S1]", "tag": "REPORTED",
               "sids": [1, 2]}
    shared = {"text": "Capacity reached 176 GW [S1] and demand grew 12% [S3][S2]", "tag": "VERIFIED",
              "sids": [1, 2, 3]}
    record = {"id": "K1", "facts": [interleaved, leading, shared]}

    def admissible(sid):
        return sid != 2

    walled, dropped, stripped = lr.pit_wall_record(record, admissible, per_claim=True)
    assert [fact["text"] for fact in walled["facts"]] == ["Capacity reached 176 GW [S1] and demand grew 12% [S3]"]
    assert (dropped, stripped) == (2, 1)
    digest, dropped, stripped = lr.pit_wall_record(record, admissible)
    assert (digest["facts"], dropped, stripped) == ([], 3, 0)
    engine = _walled_fallback_engine({"K1": record}, admissible)
    body = engine._fallback_section(engine._outline(1))
    assert body == "- Capacity reached 176 GW [S1] and demand grew 12% [S3]"
    assert "250 GW" not in body
    # Everything admissible: neither rule changes anything.
    for per_claim in (False, True):
        unchanged, dropped, stripped = lr.pit_wall_record(record, lambda sid: True, per_claim=per_claim)
        assert (unchanged["facts"], dropped, stripped) == (record["facts"], 0, 0)


@pytest.mark.parametrize("typing", [False, True])
def test_parametric_suspects_count_post_as_of_claims_only(typing):
    timeline = [{"date": "2024-07-01", "event": "a"}, {"date": "2024", "event": "b"},
                {"date": "2024-06-01", "event": "c"}, {"date": "Q3 2024", "event": "d"}]
    quant = [{"metric": "m", "value": 1, "as_of_date": "2024-08", "value_type": "actual"},
             {"metric": "m", "value": 1, "as_of_date": "2024-08"},
             {"metric": "m", "value": 1, "as_of_date": "2025", "value_type": "forecast"},
             {"metric": "m", "value": 1, "as_of_date": "2024-05", "value_type": "actual"},
             {"metric": "m", "value": 1, "as_of_date": "2024-08", "period_end": "2023", "value_type": "estimate"}]
    counts = lr.parametric_suspects(timeline, quant, dt.date(2024, 6, 1), typing=typing)
    # A reported estimate published after the as-of is a claimed actual only to the classifier.
    assert counts == {"timeline": 2, "quant": 3 if typing else 2}
