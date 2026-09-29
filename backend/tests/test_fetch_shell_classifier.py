"""RESEARCH-1: the fetch-layer extraction-shell classifier and its provenance wall.

Reader shells ("Markdown Content: undefined"), "page unavailable" pages, bot
walls and short paywall teasers used to count as successful reads: 3 of 77
stored pages of the live deep run pipe_6c4190b31f0b were shells, and the NIST
shell was published in sources.json as a fetched S1 source.  These tests cover
the pure classifier, the cached_fetch wiring (cache, failover, cache-read
revalidation), the v3 engine's provenance wall at finalize, and the
RESEARCH_FETCH_SHELL_DETECTION=false kill switch (byte-identical legacy
behaviour).  Offline: providers, search and fetch are injected fakes.
"""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import json
import os
import re
import sys
import threading
import time
import types

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BRIDGE = os.path.join(os.path.dirname(_BACKEND), "deerflow_bridge")
if _BRIDGE not in sys.path:
    sys.path.insert(0, _BRIDGE)

import cached_fetch as cf  # noqa: E402
import test_research_engine_v3 as v3  # noqa: E402

# The engine harness's shared fixtures (hermetic env, real bridge with the
# network-bound finalize steps stubbed).
_hermetic_env = v3._hermetic_env
bridge = v3.bridge
lr = v3.lr
rg = v3.rg

# Verbatim shape of the live Jina PDF shell (pipe_6c4190b31f0b/handoff/v3/pages/1835a33589d97d0c.txt).
JINA_PDF_SHELL = (
    "# Untitled\n\n"
    "Title: NIST IR 8547 initial public draft, Transition to Post-Quantum Cryptography Standards\n"
    "URL Source: https://nvlpubs.nist.gov/nistpubs/ir/2024/NIST.IR.8547.ipd.pdf\n"
    "Published Time: Fri, 08 Nov 2024 19:04:22 GMT\n"
    "Markdown Content:\n"
    "undefined"
)
# The live BusinessWire page (68aba587c723b2d3.txt), client IP and phone replaced by same-length placeholders.
UNAVAILABLE_PAGE = (
    "# Page Unavailable\n\n---\n\n"
    "Please be advised that this page is unavailable.\n\n"
    "Call +1.800.555.0199 for our Web Support team or [open a support ticket]"
    "(mailto:websupport@businesswire.com) if you need further assistance.\n\n"
    "Reference Error ID: `0.d137cb17.1790622686.4bd702ab`\n\n"
    "Client IP: 203.0.113.241"
)
_PROSE = ("Grid operators in the region reported 12 GW of new connection requests in 2025, and the "
          "regulator expects transmission upgrades worth 4.2 billion dollars to be approved by 2027. ")


def prose(chars: int) -> str:
    """Deterministic article text of exactly ``chars`` characters."""
    return (_PROSE * (chars // len(_PROSE) + 1))[:chars]


def article(chars: int, *, title: str = "# Regional grid outlook", insert: str = "", at: float = 0.5,
            tail: str = "") -> str:
    """A ``chars``-long page: a title line, prose, ``insert`` at fraction ``at`` of the body and ``tail``."""
    head = f"{title}\n\n"
    body = prose(chars - len(head) - len(insert) - len(tail))
    cut = int(len(body) * at)
    text = head + body[:cut] + insert + body[cut:] + tail
    assert len(text) == chars
    return text


PAYWALL_TEASER = article(900, title="# Utilities race to connect data centres",
                         tail="\n\nSubscribe to continue reading. Already a subscriber? Sign in.")


@pytest.fixture
def shells_on(monkeypatch):
    monkeypatch.delenv("RESEARCH_FETCH_SHELL_DETECTION", raising=False)


@pytest.fixture
def isolated_fetch_chain(monkeypatch, tmp_path):
    """cached_fetch with a private cache dir, no budget ledger, Exa keyed, no Firecrawl/direct."""
    monkeypatch.setenv("RESEARCH_SOURCE_CACHE_DIR", str(tmp_path / "source-cache"))
    monkeypatch.setenv("RESEARCH_SOURCE_CACHE_TTL_H", "72")
    for name in ("RESEARCH_BUDGET_DB", "FIRECRAWL_API_KEY", "RESEARCH_DIRECT_FETCH_FALLBACK",
                 "RESEARCH_FETCH_SHELL_DETECTION"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("EXA_API_KEY", "test-exa-key")
    return tmp_path / "source-cache"


def _cached_texts(cache_dir) -> list[str]:
    if not cache_dir.exists():
        return []
    return [json.loads(path.read_text("utf-8"))["content"] for path in cache_dir.glob("*.json")]


# ============================================================== classifier

def test_jina_pdf_shell_is_empty_extraction():
    assert len(JINA_PDF_SHELL) == 252  # the live file's length
    assert cf.extraction_failure_reason(JINA_PDF_SHELL) == "empty_extraction"


def test_page_unavailable_page_is_unavailable_page():
    assert len(UNAVAILABLE_PAGE) == 295
    assert cf.extraction_failure_reason(UNAVAILABLE_PAGE) == "unavailable_page"


def test_short_paywall_teaser_is_paywalled():
    assert len(PAYWALL_TEASER) == 900
    assert cf.extraction_failure_reason(PAYWALL_TEASER) == "paywalled"


def test_plain_200_char_text_is_not_a_shell():
    assert cf.extraction_failure_reason("X" * 200) is None
    assert cf.extraction_failure_reason("X" * 199) == "empty_extraction"


def test_blank_line_padding_is_not_content():
    """Review round 1: boilerplate split by blank lines passed the 200-char rule
    on its line breaks; only visible characters count now."""
    padded = "\n\n".join(["Accept cookies"] * 14)       # 196 visible chars
    assert len(padded) >= 200                            # what the old length rule measured
    reader = "Title: Cookie notice\nURL Source: https://example.org/\nMarkdown Content:\n\n" + padded
    plain = "# Cookie notice\n\n" + padded
    assert cf.extraction_failure_reason(reader) == "empty_extraction"
    assert cf.extraction_failure_reason(plain) == "empty_extraction"
    assert cf.extraction_failure_reason(" \r\n\t\n".join(["Accept cookies"] * 14)) == "empty_extraction"
    longer = "\n\n".join(["Accept cookies"] * 15)        # 210 visible chars
    assert cf.extraction_failure_reason("Markdown Content:\n\n" + longer) is None
    assert cf.extraction_failure_reason("# Cookie notice\n\n" + longer) is None


def test_gateway_shell_reasons_match_the_classifier():
    """research_gateway recognises "Error: fetch returned <reason>" by its own
    copy of the reason set; a reason added to the classifier must reach it."""
    returned = set(re.findall(r'return "([a-z_]+)"', inspect.getsource(cf.extraction_failure_reason)))
    assert returned == set(cf.SHELL_REASONS) == rg._SHELL_REASONS
    bot_wall = "# Just a moment...\n\nChecking your browser before accessing example.org. " + prose(300)
    samples = (JINA_PDF_SHELL, UNAVAILABLE_PAGE, bot_wall, PAYWALL_TEASER)
    assert [cf.extraction_failure_reason(text) for text in samples] == list(cf.SHELL_REASONS)


def test_long_article_mentioning_a_bot_check_is_not_a_shell():
    text = article(9400, insert=" Checking your browser before accessing the portal is now routine. ")
    assert "Checking your browser" in text
    assert cf.extraction_failure_reason(text) is None


def test_long_article_with_a_subscribe_footer_is_not_a_shell():
    text = article(6000, tail="\n\nSubscribe to continue receiving our weekly grid briefing.")
    assert cf.extraction_failure_reason(text) is None


def test_abstract_followed_by_a_sign_in_wall_is_paywalled():
    """Documented, accepted false positive: a short abstract ahead of a login wall
    is not enough page to ground a claim on."""
    text = prose(2400) + "\n\nSign in to continue reading"
    assert len(text) < 3000
    assert cf.extraction_failure_reason(text) == "paywalled"


@pytest.mark.parametrize("text, expected", [
    (None, None),
    (b"x" * 500, None),
    ("", None),
    ("   \n  ", None),
    ("Error: Jina primary failed: ReadTimeout", None),
    # reader envelope bodies
    ("# Untitled\n\nTitle: A\nMarkdown Content:\nnull", "empty_extraction"),
    ("Title: A\nURL Source: https://a.org\nMarkdown Content:\n   NONE  ", "empty_extraction"),
    ("Markdown Content:\n" + prose(150), "empty_extraction"),
    ("Title: Full report\nMarkdown Content:\n" + prose(400), None),
    # only the FIRST "#" line is a title; later headings are content
    ("# Title\n" + "\n".join(f"## Heading {i:03d} of the outlook" for i in range(12)), None),
    ("# Title\nWarning: Target URL returned error 429\n" + prose(150), "empty_extraction"),
    # bot walls
    ("# Just a moment...\n\nChecking your browser before accessing example.org. " + prose(300), "bot_wall"),
    ("# Access Denied\n\nYou don't have permission to access this server. " + prose(300), "bot_wall"),
    (article(1600, insert=" Please complete the captcha. "), None),  # outside the 1,500-char window
    # unavailable pages
    ("# Page not found\n\nSorry, the page could not be found. " + prose(300), "unavailable_page"),
    (article(1600, insert=" This product is no longer available. "), None),
    # paywalls, including the CJK markers
    ("# 深度报道\n\n" + "数据中心装机容量在2023年达到176吉瓦。" * 20 + "付费阅读全文", "paywalled"),
    (article(3000, tail=" To continue reading, subscribe."), None),  # 3,000 chars: outside the window
])
def test_classifier_rules_and_windows(text, expected):
    assert cf.extraction_failure_reason(text) == expected


def test_classifier_scans_a_bounded_prefix_only():
    """A long text is classified from its first 3,000 chars (linear, no regex)."""
    assert cf.extraction_failure_reason(prose(3500) + "\nMarkdown Content:\nundefined") is None
    assert cf.extraction_failure_reason(prose(2900) + "\nMarkdown Content:\nundefined") == "empty_extraction"
    assert cf.extraction_failure_reason("Title: A\n" * 400 + prose(300)) is None  # unscanned tail is content


# ============================================================== _is_cacheable

def test_existing_is_cacheable_expectations_hold_with_default_flags(shells_on):
    # test_bridge_search_and_cache.py::test_is_cacheable_rules
    assert cf._is_cacheable("X" * 200) is True
    assert cf._is_cacheable("X" * 199) is False
    assert cf._is_cacheable("Error: boom" + "y" * 500) is False
    assert cf._is_cacheable("") is False
    assert cf._is_cacheable("   ") is False
    assert cf._is_cacheable(None) is False
    assert cf._is_cacheable(b"x" * 500) is False
    # test_loop007_research_budget.py::test_access_denied_body_is_not_positive_evidence
    assert cf._is_cacheable("Access denied. " + "blocked " * 80) is False


def test_is_cacheable_rejects_every_shell_kind(shells_on):
    for shell in (JINA_PDF_SHELL, UNAVAILABLE_PAGE, PAYWALL_TEASER):
        assert cf._is_cacheable(shell) is False
    assert cf._is_cacheable(json.dumps({"error": "x", "message": "m" * 400})) is False  # envelope check kept
    assert cf._is_cacheable(article(1200)) is True


def test_captcha_mention_early_in_a_long_article_depends_on_the_flag(monkeypatch):
    text = article(3000, insert=" The login form added a captcha last year. ", at=0.05)
    assert "captcha" in text[:1200].lower()
    monkeypatch.delenv("RESEARCH_FETCH_SHELL_DETECTION", raising=False)
    assert cf._is_cacheable(text) is True           # length-windowed markers
    monkeypatch.setenv("RESEARCH_FETCH_SHELL_DETECTION", "false")
    assert cf._is_cacheable(text) is False          # legacy unwindowed prefix markers
    monkeypatch.setenv("RESEARCH_FETCH_SHELL_DETECTION", "true")
    assert cf._is_cacheable(text) is True


def test_flag_off_keeps_legacy_is_cacheable_verdicts(monkeypatch):
    monkeypatch.setenv("RESEARCH_FETCH_SHELL_DETECTION", "false")
    assert cf._is_cacheable(JINA_PDF_SHELL) is True       # the pre-fix behaviour: shells were cached
    assert cf._is_cacheable(UNAVAILABLE_PAGE) is True
    assert cf._is_cacheable(PAYWALL_TEASER) is True
    assert cf._is_cacheable("Access denied. " + "blocked " * 80) is False


@pytest.mark.parametrize("raw, expected", [
    (None, True), ("", True), ("true", True), ("1", True), ("banana", True),
    ("false", False), ("0", False), ("No", False), (" off ", False),
])
def test_shell_detection_knob_fails_closed(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("RESEARCH_FETCH_SHELL_DETECTION", raising=False)
    else:
        monkeypatch.setenv("RESEARCH_FETCH_SHELL_DETECTION", raw)
    assert cf._shell_detection_on() is expected


@pytest.mark.parametrize("raw, expected", [
    (None, True), ("", True), ("true", True), ("1", True), ("yes", True), ("banana", True),
    ("false", False), ("0", False), ("No", False), (" OFF ", False),
])
def test_config_shell_detection_knob_fails_closed_like_the_bridge(monkeypatch, raw, expected):
    """Review round 1: the orchestrator forwards Config's verdict as an explicit
    true/false, so Config must parse the knob fail-closed too ('1' or a typo
    used to turn the check off before the bridge ever saw it)."""
    import app.config  # noqa: F401 — its import-time env defaults are set once, before the probe

    if raw is None:
        monkeypatch.delenv("RESEARCH_FETCH_SHELL_DETECTION", raising=False)
    else:
        monkeypatch.setenv("RESEARCH_FETCH_SHELL_DETECTION", raw)
    spec = importlib.util.spec_from_file_location("_research1_config_probe",
                                                  os.path.join(_BACKEND, "app", "config.py"))
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)       # a fresh Config; app.config itself is untouched
    assert probe.Config.RESEARCH_FETCH_SHELL_DETECTION is expected
    assert cf._shell_detection_on() is expected


# ============================================================== failover + cache

def test_jina_shell_fails_over_to_exa_and_is_never_cached(monkeypatch, isolated_fetch_chain):
    exa_page = "# Exa evidence\n\n" + prose(900)
    calls: list[str] = []

    async def jina(url):
        calls.append("jina")
        return JINA_PDF_SHELL

    async def exa(url):
        calls.append("exa")
        return exa_page

    monkeypatch.setattr(cf, "_jina_delegate_fetch", jina)
    monkeypatch.setattr(cf, "_exa_fetch", exa)
    result = asyncio.run(cf.cached_fetch("https://example.test/report.pdf", cf._resilient_fetch))
    assert result == exa_page and calls == ["jina", "exa"]
    assert _cached_texts(isolated_fetch_chain) == [exa_page]


def test_every_provider_returning_a_shell_is_an_error(monkeypatch, isolated_fetch_chain):
    async def jina(url):
        return JINA_PDF_SHELL

    async def exa(url):
        return PAYWALL_TEASER

    monkeypatch.setattr(cf, "_jina_delegate_fetch", jina)
    monkeypatch.setattr(cf, "_exa_fetch", exa)
    result = asyncio.run(cf.cached_fetch("https://example.test/walled", cf._resilient_fetch))
    assert result == "Error: fetch returned paywalled"  # the last provider's text was the teaser
    assert _cached_texts(isolated_fetch_chain) == []


def test_final_json_envelope_passes_through_unchanged(monkeypatch, isolated_fetch_chain):
    """Critic amendment: an envelope's own error must reach the tool layer."""
    envelope = json.dumps({"error": "research_budget_exhausted", "tool": "web_fetch"})
    monkeypatch.delenv("EXA_API_KEY")

    async def jina(url):
        return envelope

    monkeypatch.setattr(cf, "_jina_delegate_fetch", jina)
    assert asyncio.run(cf._resilient_fetch("https://example.test/a")) == envelope
    assert asyncio.run(cf.cached_fetch("https://example.test/a", cf._resilient_fetch)) == envelope
    assert _cached_texts(isolated_fetch_chain) == []


def test_flag_off_returns_and_caches_the_shell_like_before(monkeypatch, isolated_fetch_chain):
    monkeypatch.setenv("RESEARCH_FETCH_SHELL_DETECTION", "false")
    monkeypatch.delenv("EXA_API_KEY")

    async def jina(url):
        return JINA_PDF_SHELL

    monkeypatch.setattr(cf, "_jina_delegate_fetch", jina)
    assert asyncio.run(cf.cached_fetch("https://example.test/report.pdf", cf._resilient_fetch)) == JINA_PDF_SHELL
    assert _cached_texts(isolated_fetch_chain) == [JINA_PDF_SHELL]


def _write_entry(cache_dir, url: str, content: str, fetched_at: float | None = None):
    path = cache_dir / (cf._cache_key(url) + ".json")
    cache_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"url": url, "content": content, "fetched_at": fetched_at or time.time(),
                                "content_len": len(content)}), encoding="utf-8")
    return path


def test_cached_shell_is_a_miss_and_is_removed(isolated_fetch_chain):
    path = _write_entry(isolated_fetch_chain, "https://example.test/old-shell", JINA_PDF_SHELL)
    assert cf._read_cache(str(path), 72 * 3600.0) is None
    assert not path.exists()
    page = article(800)
    good = _write_entry(isolated_fetch_chain, "https://example.test/page", page)
    assert cf._read_cache(str(good), 72 * 3600.0) == page and good.exists()


def test_cached_shell_is_refetched_through_the_chain(monkeypatch, isolated_fetch_chain):
    url = "https://example.test/old-shell"
    _write_entry(isolated_fetch_chain, url, UNAVAILABLE_PAGE)
    page = "# Current page\n\n" + prose(700)

    async def jina(_url):
        return page

    monkeypatch.setattr(cf, "_jina_delegate_fetch", jina)
    assert asyncio.run(cf.cached_fetch(url, cf._resilient_fetch)) == page
    assert _cached_texts(isolated_fetch_chain) == [page]


def test_flag_off_cache_read_serves_the_stored_shell(monkeypatch, isolated_fetch_chain):
    monkeypatch.setenv("RESEARCH_FETCH_SHELL_DETECTION", "false")
    path = _write_entry(isolated_fetch_chain, "https://example.test/old-shell", JINA_PDF_SHELL)
    assert cf._read_cache(str(path), 72 * 3600.0) == JINA_PDF_SHELL and path.exists()


# ============================================================== v3 engine

class _ShellOnce:
    """Page text for every URL except the first one requested, which gets ``shell``."""

    def __init__(self, shell: str) -> None:
        self.shell = shell
        self.shell_url: str | None = None
        self._lock = threading.Lock()

    def __call__(self, url: str) -> str:
        with self._lock:
            if self.shell_url is None:
                self.shell_url = url
            if url == self.shell_url:
                return self.shell
        return v3.page_text(url)


def _sources(out) -> list[dict]:
    return json.loads((out / "sources.json").read_text(encoding="utf-8"))


def _ledger_rows(out, url: str) -> list[dict]:
    """The persisted v3 ledger rows of ``url`` (none when it was never registered)."""
    rows = json.loads((out / "v3" / "sources_ledger.json").read_text(encoding="utf-8"))
    return [row for row in rows if row["canonical"] == rg.canonical_url(url)]


def test_engine_rejects_a_shell_at_the_tool_layer(tmp_path, bridge):
    fetch = _ShellOnce(JINA_PDF_SHELL)
    rc, meta, plog, _, out = v3.run_engine(tmp_path, bridge, v3.World(), fetch=fetch)
    assert rc == 0, meta.get("error")
    sources = _sources(out)
    fetched = [row for row in sources if row["source_origin"] == "fetched"]
    assert fetched and not any("Markdown Content" in (row.get("excerpt") or "") for row in fetched)
    # The shell URL was requested, and whether it is in the ledger (seen in a
    # search) or not (the shell was never registered), it is never fetched.
    assert fetch.shell_url is not None
    assert all(row["fetched"] is False and row["page_path"] is None
               for row in _ledger_rows(out, fetch.shell_url))
    assert all(row["source_origin"] == "cited" for row in sources if row["url"] == fetch.shell_url)
    assert not any("fetch_status" in row for row in sources)
    pages = list((out / "v3" / "pages").glob("*.txt"))
    assert pages and not any("Markdown Content" in path.read_text("utf-8") for path in pages)
    assert meta["fetch_shells"] == {"rejected": {"empty_extraction": 1}, "sources_demoted": 0}
    assert "[result] web_fetch → FETCH_FAILED(empty_extraction)" in plog.text()


def test_engine_flag_off_publishes_the_shell_as_before(tmp_path, bridge, monkeypatch):
    monkeypatch.setenv("RESEARCH_FETCH_SHELL_DETECTION", "false")
    fetch = _ShellOnce(JINA_PDF_SHELL)
    rc, meta, _, _, out = v3.run_engine(tmp_path, bridge, v3.World(), fetch=fetch)
    assert rc == 0, meta.get("error")
    shell_rows = [row for row in _sources(out) if row["url"] == fetch.shell_url]
    assert shell_rows and shell_rows[0]["source_origin"] == "fetched"
    assert "Markdown Content" in shell_rows[0]["excerpt"]
    assert "fetch_status" not in shell_rows[0] and "fetch_shells" not in meta


class _PreFixTools(rg.ResearchTools):
    """Tools of a work dir written before the fix: the tool layer stores shells."""

    @property
    def shell_detection(self) -> bool:
        return False

    @shell_detection.setter
    def shell_detection(self, value: bool) -> None:
        pass


def _run_with_prefix_tools(tmp_path, bridge, fetch):
    tools: list[rg.ResearchTools] = []

    def tools_factory(ledger, pages_dir, bridge_arg, plog_arg, limits):
        tools.append(_PreFixTools(ledger, pages_dir, search_fn=v3.fake_search, fetch_fn=fetch,
                                  bridge=bridge_arg, plog=plog_arg, limits=limits))
        return tools[0]

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    meta = {"status": "running", "question": "q", "research_engine": "v3"}
    model = v3.ScriptedModel(v3.World())

    def gateway_factory(args, plog_arg, bridge_arg, preset):
        return rg.ModelGateway(model, plog_arg, max_concurrency=preset.workers, budget_units=preset.budget_units,
                               reserve_share=lr.RESERVE_SHARE, sleep=lambda seconds: None)

    rc = lr.run("Will global data-centre capacity exceed 250 GW by the end of 2027?", out_dir,
                v3.make_args(), meta, v3.FakePlog(), lambda: None, bridge=bridge,
                gateway_factory=gateway_factory, tools_factory=tools_factory)
    return rc, meta, out_dir, tools[0]


def test_stored_shell_marked_fetched_is_published_as_cited(tmp_path, bridge):
    fetch = _ShellOnce(JINA_PDF_SHELL)
    rc, meta, out, tools = _run_with_prefix_tools(tmp_path, bridge, fetch)
    assert rc == 0, meta.get("error")
    ledger_row = tools.ledger.find(fetch.shell_url)
    assert ledger_row["fetched"] is True            # the pre-fix store marked the shell fetched
    sources = _sources(out)
    shell_rows = [row for row in sources if row["url"] == fetch.shell_url]
    assert len(shell_rows) == 1
    shell_row = shell_rows[0]
    assert shell_row["source_origin"] == "cited" and shell_row["reachable"] is None
    assert shell_row["fetch_status"] == "shell:empty_extraction"
    assert "excerpt" not in shell_row and "content_sha256" not in shell_row
    fetched = sum(1 for row in sources if row["source_origin"] == "fetched")
    ledger_fetched = sum(1 for row in sources if tools.ledger.find(row["url"])["fetched"])
    assert fetched == ledger_fetched - 1 and fetched >= 1   # only the shell was demoted
    assert meta["fetched_sources_count"] == fetched
    assert meta["research_quality"]["components"]["grounding"] == round(fetched / len(sources), 3)
    assert meta["fetch_shells"] == {"rejected": {}, "sources_demoted": 1}


def _resume_after_prefix_run(tmp_path, bridge):
    """A work dir whose pre-fix tool layer stored the shell and marked it
    fetched, plus one reloaded fact VERIFIED only by that shell (what a pre-fix
    agent could write).  Returns ``(fetch, first_meta, out, shell_sid)``."""
    fetch = _ShellOnce(JINA_PDF_SHELL)
    rc, meta, out, tools = _run_with_prefix_tools(tmp_path, bridge, fetch)
    assert rc == 0, meta.get("error")
    shell = tools.ledger.find(fetch.shell_url)
    assert shell["fetched"] is True
    kiq_path = out / "v3" / "kiq" / "K1.json"
    record = json.loads(kiq_path.read_text(encoding="utf-8"))
    record["facts"].append({"kiq": record["id"], "text": "The draft sets the migration deadline.",
                            "sids": [shell["sid"]], "tag": "VERIFIED", "verified_numbers": None})
    kiq_path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    return fetch, meta, out, shell["sid"]


def _silent_model():
    return v3.ScriptedModel(lambda call: pytest.fail(f"unexpected model call: {v3.role_of(call)}"))


def test_resumed_work_dir_unmarks_a_stored_shell(tmp_path, bridge):
    """Review round 1: a shell an earlier run stored and marked fetched is
    un-marked once when the run resumes with the check on, so it is never served
    as a stored copy, never VERIFIED evidence and published as cited."""
    fetch, first_meta, out, shell_sid = _resume_after_prefix_run(tmp_path, bridge)
    rc, meta, plog, model, _ = v3.run_engine(tmp_path, bridge, v3.World(), out_dir=out, model=_silent_model())
    assert rc == 0 and model.calls == [], meta.get("error")
    assert "1 stored page(s) of the resumed work dir are extraction shells" in plog.text()
    (row,) = _ledger_rows(out, fetch.shell_url)
    assert row["fetched"] is False and row["page_path"] is None and row["content_sha256"] is None
    shell_row = next(r for r in _sources(out) if r["url"] == fetch.shell_url)
    assert shell_row["source_origin"] == "cited" and shell_row["reachable"] is None
    assert shell_row["fetch_status"] == "shell:empty_extraction" and "excerpt" not in shell_row
    assert meta["fetch_shells"] == {"rejected": {}, "sources_demoted": 1}
    # Reloaded facts VERIFIED only through the shell are REPORTED now.
    fetched = {r["sid"] for r in json.loads((out / "v3" / "sources_ledger.json").read_text("utf-8"))
               if r["fetched"]}
    shell_only = sum(1 for path in (out / "v3" / "kiq").glob("*.json")
                     for fact in json.loads(path.read_text("utf-8"))["facts"]
                     if fact["tag"] == "VERIFIED" and shell_sid in fact["sids"]
                     and not fetched & set(fact["sids"]))
    assert shell_only >= 1
    assert meta["kiqs"]["verified"] == first_meta["kiqs"]["verified"] + 1 - shell_only
    # The tool layer fetches the URL again instead of serving the stored shell.
    ledger = rg.SourceLedger(out / "v3" / "sources_ledger.json")
    requested: list[str] = []

    def refetch(url: str) -> str:
        requested.append(url)
        return v3.page_text(url)

    tools = rg.ResearchTools(ledger, out / "v3" / "pages", fetch_fn=refetch)
    tools.shell_detection = True
    answer = tools.fetch(fetch.shell_url, agent_id="K9")
    assert requested == [fetch.shell_url] and "Markdown Content" not in answer
    assert ledger.find(fetch.shell_url)["fetched"] is True
    assert "Markdown Content" not in tools.page_text(shell_sid)


def test_resumed_work_dir_keeps_stored_shells_with_the_flag_off(tmp_path, bridge, monkeypatch):
    fetch, _, out, shell_sid = _resume_after_prefix_run(tmp_path, bridge)
    monkeypatch.setenv("RESEARCH_FETCH_SHELL_DETECTION", "false")
    rc, meta, plog, _, _ = v3.run_engine(tmp_path, bridge, v3.World(), out_dir=out, model=_silent_model())
    assert rc == 0, meta.get("error")
    assert "extraction shells" not in plog.text() and "fetch_shells" not in meta
    (row,) = _ledger_rows(out, fetch.shell_url)
    assert row["fetched"] is True and row["sid"] == shell_sid
    shell_row = next(r for r in _sources(out) if r["url"] == fetch.shell_url)
    assert shell_row["source_origin"] == "fetched" and "Markdown Content" in shell_row["excerpt"]


def test_reloaded_fact_verified_only_by_an_unmarked_shell_is_reported():
    rows = {1: {"fetched": False}, 2: {"fetched": True}, 3: {"fetched": False}}
    engine = types.SimpleNamespace(stored_shells={1: "empty_extraction"},
                                   ledger=types.SimpleNamespace(get=rows.get))
    record = {"facts": [
        {"text": "a", "sids": [1], "tag": "VERIFIED", "verified_numbers": True},
        {"text": "b", "sids": [1, 2], "tag": "VERIFIED", "verified_numbers": True},
        {"text": "c", "sids": [3], "tag": "VERIFIED", "verified_numbers": None},
        {"text": "d", "sids": [1], "tag": "REPORTED", "verified_numbers": None},
    ]}
    lr._Engine._demote_shell_facts(engine, record)
    assert [(f["tag"], f.get("verification"), f["verified_numbers"]) for f in record["facts"]] == [
        ("REPORTED", "no_fetched_source", None),   # only the shell backed it
        ("VERIFIED", None, True),                   # another fetched page still does
        ("VERIFIED", None, None),                   # not a shell this sweep found
        ("REPORTED", None, None),
    ]
