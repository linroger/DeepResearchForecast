"""EVAL-12 (P03): golden-set contamination probes (backend/scripts/golden_probe.py).

Offline: a scripted client stands in for the backbone; no network, no ledger write.
"""

import json
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import golden_eval as ge  # noqa: E402
import golden_probe as gp  # noqa: E402

from app.config import Config  # noqa: E402
from app.services import golden_set  # noqa: E402

_, QUESTIONS = ge.load_golden_file(ge.GOLDEN_PATH)
META = gp.load_meta(gp.META_PATH)
BY_ID = {q["id"]: q for q in QUESTIONS}


class ScriptedClient:
    """chat_json answers from ``answer(arm, question_id)``; records every call."""

    def __init__(self, answer):
        self.answer = answer
        self.calls = []
        self.model = "scripted-1"

    def chat_json(self, messages, temperature=0.3, max_tokens=4096, tier=None, *, label=None,
                  allow_non_dict=False):
        arm = (label or "").split(":")[-1]
        user = messages[-1]["content"]
        qid = next(q["id"] for q in QUESTIONS
                   if gp.probe_view(q, META.get(q["id"]))["question"] in user)
        self.calls.append((arm, qid, temperature, max_tokens))
        return self.answer(arm, qid)


def _honest(arm, qid):
    """A model that forecasts 0.6/0.3 by outcome and does not remember anything."""
    yes = golden_set.expected_label(BY_ID[qid]) == "YES"
    if arm == "nd":
        return {"p_yes": 0.62 if yes else 0.31}
    return {"knows": False, "stated_outcome": "UNKNOWN", "details": ""}


def _run(tmp_path, answer=_honest, *, arms=gp.ARMS, max_calls=200, closed_book=True, questions=QUESTIONS):
    client = ScriptedClient(answer)
    report = gp.run_probe(questions, META, client=client, provider="deepseek", model="scripted-1",
                          out_dir=str(tmp_path / "probe"), golden_sha256="g" * 64, arms=arms,
                          max_calls=max_calls, confident_p=0.85, closed_book_attested=closed_book)
    return report, client


# ------------------------------------------------------------------ prompts and meta
@pytest.mark.parametrize("arm", gp.ARMS)
def test_prompts_never_contain_markers_or_resolution_note(arm):
    for q in QUESTIONS:
        messages = gp.build_messages(arm, q, META[q["id"]])
        rendered = "\n".join(m["content"] for m in messages)
        assert gp.contains_marker(rendered, META[q["id"]]["leak_markers"]) is None, q["id"]
        gp.assert_answer_free(messages, META[q["id"]]["leak_markers"])
        note = str(q.get("resolution_note") or "").strip()
        if note:
            assert note not in rendered, q["id"]
        assert "resolved_outcome" not in rendered and "resolution_note" not in rendered


def test_meta_file_wellformed():
    assert gp.validate_meta(META, QUESTIONS) == []
    assert set(META) == set(BY_ID)
    for q in QUESTIONS:
        if q.get("hindsight_framed"):
            assert META[q["id"]].get("probe_question")
    # a marker that the question itself shows is refused
    bad = json.loads(json.dumps(META))
    bad["us-senate-2024-gop"]["leak_markers"] = ["51"]
    assert any("us-senate-2024-gop" in e for e in gp.validate_meta(bad, QUESTIONS))
    bad = json.loads(json.dumps(META))
    del bad["openai-gpt4o-2024"]["probe_question"]
    assert any("hindsight" in e for e in gp.validate_meta(bad, QUESTIONS))


def _meta_errors(qid, **row):
    bad = json.loads(json.dumps(META))
    bad[qid].update(row)
    for key in [k for k, v in row.items() if v is None]:
        del bad[qid][key]
    return [e for e in gp.validate_meta(bad, QUESTIONS) if e.startswith(qid + ":")]


def test_meta_needs_rationale_and_never_an_invented_marker():
    assert all(META[q["id"]]["marker_rationale"].strip() for q in QUESTIONS)
    uninformative = sorted(qid for qid, row in META.items() if row.get("recall_uninformative"))
    assert uninformative == ["btc-spot-etf-2024", "fed-2024-11-cut", "fed-2025-01-cut"]
    assert all(META[qid]["leak_markers"] == [] for qid in uninformative)
    # an empty list needs the explicit flag; the flag forbids markers; the rationale is required
    assert any("recall_uninformative: true" in e for e in _meta_errors("fed-2024-11-cut", recall_uninformative=None))
    assert any("carries no leak_markers" in e for e in _meta_errors("us-senate-2024-gop", recall_uninformative=True))
    assert any("true or false" in e for e in _meta_errors("fed-2024-11-cut", recall_uninformative="yes"))
    assert any("marker_rationale" in e for e in _meta_errors("us-senate-2024-gop", marker_rationale=" "))
    assert any("marker_rationale" in e for e in _meta_errors("us-senate-2024-gop", marker_rationale=None))
    assert any("non-blank" in e for e in _meta_errors("us-senate-2024-gop", leak_markers=["53", " "]))


@pytest.mark.parametrize("qid,outcome,details", [
    # facts public at as_of, the standard 25bp step, players of the named team, a month the
    # recall window gives away: a model that remembers nothing can say all of these
    ("fed-2025-01-cut", "NO", "The FOMC held the target range at 4.25%-4.50%."),
    ("fed-2024-11-cut", "YES", "The Fed cut by 25 basis points to 4.50%-4.75%."),
    ("fed-2024-12-cut", "YES", "The Fed cut by 25bp to 4.25%-4.50%."),
    ("fr-legis-2024-rn-majority", "NO", "The New Popular Front came first and RN fell short of a majority."),
    ("ucl-2024-real-madrid", "YES", "Real Madrid won the final; Carvajal and Vinicius starred."),
    ("sb-lviii-2024-chiefs", "YES", "Mahomes and Hardman led the Chiefs past the 49ers."),
    ("mlb-2024-dodgers", "YES", "Freddie Freeman and Shohei Ohtani led the Dodgers to the title."),
    ("euro-2024-spain", "YES", "Oyarzabal and Yamal helped Spain lift the trophy."),
    ("nvidia-3t-2024", "YES", "Nvidia crossed $3 trillion in June 2024."),
    ("btc-spot-etf-2024", "YES", "The SEC approved spot bitcoin ETFs on January 10, 2024, the ARK deadline."),
    ("trump-ny-conviction-2024", "YES", "Trump was convicted on 34 felony counts of falsifying records."),
    ("spacex-starship-catch-2024", "YES", "SpaceX caught the Super Heavy booster on Flight 5."),
])
def test_as_of_knowledge_is_never_a_marker(qid, outcome, details):
    recall = {"knows": True, "stated_outcome": outcome, "details": details}
    flags = gp.question_flags(BY_ID[qid], META[qid]["leak_markers"], None, recall, 0.85)
    assert flags["likely_memorized"] is False and flags["recall_claimed"] is True


@pytest.mark.parametrize("qid,details", [
    ("fed-2024-12-cut", "Cut 25bp; Cleveland's Beth Hammack dissented."),
    ("nvidia-3t-2024", "Nvidia closed above $3 trillion on June 5."),
    ("fed-2024-09-cut", "The Fed opened with a half-point cut."),
    ("ucl-2024-real-madrid", "Real Madrid beat Dortmund at Wembley."),
])
def test_realized_details_unknowable_at_as_of_still_flag(qid, details):
    recall = {"knows": True, "stated_outcome": "YES", "details": details}
    assert gp.question_flags(BY_ID[qid], META[qid]["leak_markers"], None, recall, 0.85)["likely_memorized"] is True


def test_markers_match_whole_normalized_tokens():
    assert gp.contains_marker("Republicans won 53 seats.", ["53"]) == "53"
    assert gp.contains_marker("Planned for 2053.", ["53"]) is None
    assert gp.contains_marker("Final score 2–0 to Madrid", ["2-0"]) == "2-0"   # en dash
    assert gp.contains_marker("Score 12-0", ["2-0"]) is None
    assert gp.contains_marker("THE  Half   Point cut", ["half point"]) == "half point"


def test_leak_guard_blocks_with_zero_calls(tmp_path):
    meta = json.loads(json.dumps(META))
    q = BY_ID["us-senate-2024-gop"]
    meta[q["id"]]["leak_markers"] = ["Senate"]          # shown by the question itself
    client = ScriptedClient(_honest)
    report = gp.run_probe([q], meta, client=client, provider="deepseek", model="m",
                          out_dir=str(tmp_path), golden_sha256="g" * 64, closed_book_attested=True)
    assert client.calls == []
    assert report["questions"][0]["arms"] == {"nd": "prompt_leak_blocked", "recall": "prompt_leak_blocked"}
    assert report["summary"]["status"] == "inconclusive"
    assert "nd_prompt_leak_blocked" in report["summary"]["inconclusive_reasons"]


# ------------------------------------------------------------------ parsers
@pytest.mark.parametrize("reply,expected", [
    ({"p_yes": 0.7}, 0.7), ({"p_yes": "85%"}, 0.85), ({"p_yes": "0.2"}, 0.2), ({"p_yes": 0}, 0.0),
    ({"p_yes": 1.2}, None), ({"p_yes": 85}, None), ({"p_yes": True}, None), ({"p_yes": "n/a"}, None),
    ({"p_yes": None}, None), ({}, None), ("I cannot forecast this", None), ({"p_yes": float("nan")}, None),
])
def test_parser_never_defaults(reply, expected):
    assert gp.parse_nd(reply) == expected


def test_recall_parser_is_strict_and_keeps_all_details():
    assert gp.parse_recall({"knows": True, "stated_outcome": "yes", "details": " x\n" * 100}) == {
        "knows": True, "stated_outcome": "YES", "details": " ".join(["x"] * 100)}
    assert gp.parse_recall({"knows": "maybe", "stated_outcome": "YES"}) is None
    assert gp.parse_recall({"knows": False, "stated_outcome": "PROBABLY"}) is None
    assert gp.parse_recall("UNKNOWN") is None


def test_marker_after_the_word_limit_still_flags():
    q = BY_ID["uk-ge-2024-labour"]
    details = " ".join(["filler"] * gp.DETAILS_MAX_WORDS) + " Labour won 411 seats"
    recall = gp.parse_recall({"knows": True, "stated_outcome": "YES", "details": details})
    assert recall["details"] == details
    assert gp.question_flags(q, META[q["id"]]["leak_markers"], None, recall, 0.85)["likely_memorized"] is True


@pytest.mark.parametrize("repair_turn", [True, False])
def test_refusal_through_the_real_client_is_parse_failed(tmp_path, monkeypatch, repair_turn):
    from app.utils.llm_client import LLMClient
    monkeypatch.setattr(Config, "LLM_JSON_REPAIR_TURN", repair_turn, raising=False)
    client = LLMClient(provider="deepseek", api_key="x", pinned=True, use_cache=False)
    sent = []

    def refuse(*args, **kwargs):
        sent.append(kwargs.get("messages"))
        return "I cannot forecast this."
    client.chat = refuse
    report = gp.run_probe([BY_ID["uk-ge-2024-labour"]], META, client=client, provider="deepseek",
                          model="deepseek-chat", out_dir=str(tmp_path), golden_sha256="g" * 64,
                          closed_book_attested=True)
    assert report["questions"][0]["arms"] == {"nd": "parse_failed", "recall": "parse_failed"}
    assert report["cost"]["calls"] == 4 and len(sent) == 4          # the repair attempt counts per arm
    arm = json.load(open(tmp_path / "arms" / "uk-ge-2024-labour" / "nd.json"))
    assert arm["status"] == "parse_failed" and arm["raw_excerpt"] == "I cannot forecast this."
    assert client.chat is refuse and "chat_json" not in vars(client)   # metering undone


def test_transport_errors_stay_call_failed(tmp_path):
    def boom(arm, qid):
        raise (ConnectionError("reset") if arm == "nd" else ValueError("LLM_FALLBACK_REASONING_EFFORT must be"))
    report, _ = _run(tmp_path, boom, questions=[BY_ID["uk-ge-2024-labour"]])
    assert report["questions"][0]["arms"] == {"nd": "call_failed", "recall": "call_failed"}
    arm = json.load(open(tmp_path / "probe" / "arms" / "uk-ge-2024-labour" / "nd.json"))
    assert arm["raw_excerpt"] == "ConnectionError: reset"


# ------------------------------------------------------------------ flags and verdicts
def test_recall_hit_requires_marker():
    q = BY_ID["us-senate-2024-gop"]
    markers = META[q["id"]]["leak_markers"]
    bare = gp.question_flags(q, markers, None, {"knows": True, "stated_outcome": "YES", "details": "they won"},
                             0.85)
    assert bare["likely_memorized"] is False and bare["recall_claimed"] is True
    hit = gp.question_flags(q, markers, None,
                            {"knows": True, "stated_outcome": "YES", "details": "Republicans won 53 seats"}, 0.85)
    assert hit["likely_memorized"] is True
    wrong = gp.question_flags(q, markers, None,
                              {"knows": True, "stated_outcome": "NO", "details": "they had 53 seats"}, 0.85)
    assert wrong["likely_memorized"] is False
    assert gp.question_flags(q, markers, 0.9, None, 0.85)["nd_confident_correct"] is True
    assert gp.question_flags(BY_ID["uk-ge-2024-tory"], [], 0.1, None, 0.85)["nd_confident_correct"] is True


def test_memorized_answers_flag_the_set(tmp_path):
    def remembers(arm, qid):
        if arm == "recall" and qid == "uk-ge-2024-labour":
            return {"knows": True, "stated_outcome": "YES", "details": "Labour won 411 seats in a landslide"}
        return _honest(arm, qid)
    report, _ = _run(tmp_path, remembers)
    assert report["summary"]["status"] == "flagged"
    assert report["summary"]["flagged_ids"] == ["uk-ge-2024-labour"]


def test_clean_closed_book_run_is_none_detected(tmp_path):
    report, client = _run(tmp_path)
    assert report["summary"]["status"] == "none_detected" and report["summary"]["inconclusive_reasons"] == []
    assert {c[2] for c in client.calls} == {0.0} and {c[3] for c in client.calls} == {gp.MAX_TOKENS}
    assert report["schema"] == "drf.golden_probe.v1" and report["cost"]["calls"] == 2 * len(QUESTIONS)
    arm = json.load(open(tmp_path / "probe" / "arms" / "us-pres-2024-trump" / "nd.json"))
    assert arm["status"] == "ok" and arm["value"] == 0.62 and len(arm["prompt_sha256"]) == 64


def test_constant_08_collapsed_inconclusive(tmp_path):
    def constant(arm, qid):
        return {"p_yes": 0.8} if arm == "nd" else _honest(arm, qid)
    report, _ = _run(tmp_path, constant)
    nd = report["summary"]["arms"]["nd"]
    assert nd["status"] == "inconclusive_collapsed" and nd["dispersion"]["collapsed"] is True
    assert report["summary"]["status"] == "inconclusive"
    assert "nd_collapsed" in report["summary"]["inconclusive_reasons"]
    # the constant forecast scores within 0.01 of the climatology baseline
    labels = [golden_set.expected_label(q) == "YES" for q in QUESTIONS]
    base = sum(labels) / len(labels)
    brier = sum((0.8 - y) ** 2 for y in labels) / len(labels)
    clim = sum((base - y) ** 2 for y in labels) / len(labels)
    assert abs(brier - clim) < 0.01


def test_cli_provider_stamped_never_none_detected(tmp_path, monkeypatch):
    from app.services import forecast_ledger
    monkeypatch.setattr(forecast_ledger, "evaluation_ledger_dir", lambda: str(tmp_path / "eval"))
    client = ScriptedClient(_honest)
    client.model = "gpt-4o-mini"            # an inherited LLM_MODEL_NAME the Claude CLI drops
    assert gp.cmd_probe(_cli_args(tmp_path, live=True, provider="claude-cli", model=None, out=None),
                        client_factory=lambda p, m: client) == 0
    sha8 = gp.golden_sha256_of(ge.GOLDEN_PATH)[:8]
    report = json.load(open(tmp_path / "eval" / "probes" / f"claude-cli__cli-default__{sha8}" / "probe_report.json"))
    assert report["closed_book_attested"] is False
    assert report["backbone"] == {"provider": "claude-cli", "model": "cli-default"}
    assert report["summary"]["status"] == "inconclusive"
    assert report["summary"]["inconclusive_reasons"] == ["not_closed_book_attested"]


@pytest.mark.parametrize("provider,model,expected", [
    ("claude-cli", "claude-sonnet-4-5", "claude-sonnet-4-5"),   # passed to the CLI via --model
    ("claude-cli", "glm-4.6", "cli-default"),                   # dropped: the account default runs
    ("codex-cli", "gpt-5", "cli-default"),                      # codex exec is never given a model
    ("deepseek", "deepseek-chat", "deepseek-chat"),
])
def test_backbone_names_the_model_actually_requested(tmp_path, provider, model, expected):
    client = ScriptedClient(_honest)
    assert gp.cmd_probe(_cli_args(tmp_path, live=True, provider=provider, model=model),
                        client_factory=lambda p, m: client) == 0
    report = json.load(open(tmp_path / "cli" / "probe_report.json"))
    assert report["backbone"] == {"provider": provider, "model": expected}
    assert report["closed_book_attested"] is (provider == "deepseek")


def test_client_build_error_exits_2(tmp_path, capsys):
    def no_key(provider, model):
        raise ValueError("no API key configured")
    assert gp.cmd_probe(_cli_args(tmp_path, live=True, provider="kimi"), client_factory=no_key) == 2
    assert "golden_probe: cannot build client for kimi: no API key configured" in capsys.readouterr().err
    assert not (tmp_path / "cli").exists()


def test_build_client_follows_the_critic_amendment(monkeypatch):
    from app.services import forecast_extractor
    from app.utils import llm_client
    built, ensemble = [], []

    class RecordingLLMClient:
        def __init__(self, *args, **kwargs):
            built.append((args, kwargs))

    def ensemble_client(provider):
        ensemble.append(provider)
        return SimpleNamespace(model=f"{provider}-default", _pinned=False, use_cache=True)

    monkeypatch.setattr(llm_client, "LLMClient", RecordingLLMClient)
    monkeypatch.setattr(forecast_extractor, "_build_ensemble_client", ensemble_client)
    monkeypatch.setattr(Config, "LLM_PROVIDER", "DeepSeek", raising=False)
    gp.build_client(None, None)
    gp.build_client("deepseek", "deepseek-reasoner")
    # the default provider: keywords only, the configured key and endpoint, pinned, no cache
    assert built == [((), {"model": None, "pinned": True, "use_cache": False}),
                     ((), {"model": "deepseek-reasoner", "pinned": True, "use_cache": False})]
    other = gp.build_client("kimi", None)
    assert (other.model, other._pinned, other.use_cache) == ("kimi-default", True, False)
    other = gp.build_client("kimi", "kimi-k2")
    assert (other.model, other._pinned, other.use_cache) == ("kimi-k2", True, False)
    assert ensemble == ["kimi", "kimi"] and len(built) == 2


def test_run_context_restored(tmp_path):
    from app.utils.telemetry import get_run_context, set_run_context
    seen = []

    def answer(arm, qid):
        seen.append(get_run_context())
        return _honest(arm, qid)
    sha8 = gp.golden_sha256_of(ge.GOLDEN_PATH)[:8]
    client = ScriptedClient(answer)
    for outer in ((None, None), ("outer-run", "report")):
        set_run_context(*outer)
        try:
            assert gp.cmd_probe(_cli_args(tmp_path, live=True, out=str(tmp_path / str(outer[0]))),
                                client_factory=lambda p, m: client) == 0
            assert set(seen) == {("golden_probe:" + sha8, "golden_probe")}
            assert get_run_context() == outer
        finally:
            set_run_context(None, None)


def test_uninformative_rows_are_reported_not_recall_checkable(tmp_path):
    report, _ = _run(tmp_path)
    ids = ["btc-spot-etf-2024", "fed-2024-11-cut", "fed-2025-01-cut"]
    assert report["summary"]["recall_uninformative_ids"] == ids
    assert {r["question_id"] for r in report["questions"] if not r["recall_checkable"]} == set(ids)
    assert report["summary"]["arms"]["recall"]["checkable"] == len(QUESTIONS) - len(ids)
    # mostly uninformative rows: a clean recall arm proves nothing -> inconclusive
    few = [BY_ID[i] for i in ("fed-2024-11-cut", "fed-2025-01-cut", "us-pres-2024-trump",
                              "us-pres-2024-harris", "uk-ge-2024-labour")]
    report, _ = _run(tmp_path / "few", questions=few)
    assert report["summary"]["arms"]["recall"]["checkable_share"] == 0.6
    assert report["summary"]["status"] == "inconclusive"
    assert report["summary"]["inconclusive_reasons"] == ["recall_checkable_below_0.8"]


def test_low_coverage_is_inconclusive(tmp_path):
    def refuses(arm, qid):
        return {"refused": True} if arm == "recall" else _honest(arm, qid)
    report, _ = _run(tmp_path, refuses)
    assert report["summary"]["status"] == "inconclusive"
    assert "recall_coverage_below_0.8" in report["summary"]["inconclusive_reasons"]


# ------------------------------------------------------------------ budget, opt-in, resume
def test_max_calls_cap(tmp_path):
    report, client = _run(tmp_path, max_calls=5)
    assert len(client.calls) == 5 and report["cost"]["calls"] == 5
    statuses = [s for row in report["questions"] for s in row["arms"].values()]
    assert statuses.count("skipped_budget") == 2 * len(QUESTIONS) - 5
    assert report["summary"]["status"] == "inconclusive"
    assert "budget_exhausted" in report["summary"]["inconclusive_reasons"]


def test_repair_attempts_inside_chat_json_count(tmp_path):
    class RepairingClient(ScriptedClient):
        def chat(self, *args, **kwargs):
            return "{}"

        def chat_json(self, messages, *args, **kwargs):
            self.chat(messages)            # the first attempt
            self.chat(messages)            # the repair turn
            return super().chat_json(messages, *args, **kwargs)

    client = RepairingClient(_honest)
    report = gp.run_probe(QUESTIONS[:3], META, client=client, provider="deepseek", model="m",
                          out_dir=str(tmp_path), golden_sha256="g" * 64, max_calls=5,
                          closed_book_attested=True)
    assert report["cost"]["calls"] == 5   # 2 per chat_json; the third chat_json is stopped mid-repair
    assert [s for row in report["questions"] for s in row["arms"].values()].count("ok") == 2


def test_metering_is_undone_so_a_client_can_be_probed_twice(tmp_path):
    client = ScriptedClient(_honest)
    first = gp.run_probe(QUESTIONS[:2], META, client=client, provider="deepseek", model="m",
                         out_dir=str(tmp_path / "a"), golden_sha256="g" * 64, max_calls=2, closed_book_attested=True)
    assert first["cost"]["calls"] == 2 and "chat_json" not in vars(client)
    second = gp.run_probe(QUESTIONS[:2], META, client=client, provider="deepseek", model="m",
                          out_dir=str(tmp_path / "b"), golden_sha256="g" * 64, max_calls=4, closed_book_attested=True)
    assert second["cost"]["calls"] == 4 and len(client.calls) == 6
    assert "budget_exhausted" not in second["summary"]["inconclusive_reasons"]


def _cli_args(tmp_path, **over):
    args = {"live": False, "provider": "deepseek", "model": "scripted-1", "arms": "nd,recall",
            "out": str(tmp_path / "cli"), "golden": ge.GOLDEN_PATH, "meta": gp.META_PATH}
    args.update(over)
    return SimpleNamespace(**args)


def test_opt_in_guard_zero_calls(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(Config, "GOLDEN_PROBE_ENABLED", False, raising=False)
    built = []
    code = gp.cmd_probe(_cli_args(tmp_path), client_factory=lambda p, m: built.append((p, m)))
    assert code == 0 and built == [] and "No call was made" in capsys.readouterr().out
    assert not (tmp_path / "cli").exists()


def test_max_calls_cap_exit_4(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(Config, "GOLDEN_PROBE_MAX_CALLS", 3, raising=False)
    client = ScriptedClient(_honest)
    code = gp.cmd_probe(_cli_args(tmp_path, live=True), client_factory=lambda p, m: client)
    assert code == gp.EXIT_BUDGET and len(client.calls) == 3
    report = json.load(open(tmp_path / "cli" / "probe_report.json"))
    assert report["golden_sha256"] == gp.golden_sha256_of(ge.GOLDEN_PATH)
    assert report["closed_book_attested"] is True     # deepseek is OpenAI-compatible


def test_resume_zero_calls(tmp_path):
    first, client = _run(tmp_path)
    assert len(client.calls) == 2 * len(QUESTIONS)
    second, client = _run(tmp_path)
    assert client.calls == [] and second["cost"] == {"calls": 0, "reused_arms": 2 * len(QUESTIONS),
                                                     "max_calls": 200}
    assert second["summary"] == first["summary"]


def test_resume_never_reuses_a_prompt_that_now_leaks(tmp_path, capsys):
    """Review round 2: the leak guard runs before reuse, and validate_meta checks the rendered
    prompts, so a marker that only the recall prompt shows (here its window end) gives the
    same verdict on a resumed run as on a fresh one."""
    q = BY_ID["uk-ge-2024-labour"]
    first, _ = _run(tmp_path)
    assert first["summary"]["status"] == "none_detected"
    meta = json.loads(json.dumps(META))
    window_end = gp._recall_until(q)
    meta[q["id"]]["leak_markers"].append(window_end)
    nd_prompt = "\n".join(m["content"] for m in gp.build_messages("nd", q, meta[q["id"]]))
    assert gp.contains_marker(nd_prompt, [window_end]) is None      # only the recall prompt shows it

    def resumed(out):
        client = ScriptedClient(_honest)
        report = gp.run_probe(QUESTIONS, meta, client=client, provider="deepseek", model="scripted-1",
                              out_dir=str(out), golden_sha256="g" * 64, max_calls=200, confident_p=0.85,
                              closed_book_attested=True)
        return report, client
    second, client = resumed(tmp_path / "probe")
    assert client.calls == [] and second["cost"]["calls"] == 0
    row = next(r for r in second["questions"] if r["question_id"] == q["id"])
    assert row["arms"] == {"nd": "ok", "recall": "prompt_leak_blocked"}
    assert second["summary"]["status"] == "inconclusive"
    assert second["summary"]["inconclusive_reasons"] == ["recall_prompt_leak_blocked"]
    arm = json.load(open(tmp_path / "probe" / "arms" / q["id"] / "recall.json"))
    assert arm["status"] == "prompt_leak_blocked"
    fresh, _ = resumed(tmp_path / "fresh")
    assert fresh["summary"] == second["summary"]
    # the meta itself is refused, so the CLI stops before building a client
    errors = gp.validate_meta(meta, QUESTIONS)
    assert errors == [f"{q['id']}: the recall probe prompt contains leak marker {window_end!r} "
                      "(template text or the recall window)"]
    meta_path = tmp_path / "meta.json"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    built = []
    assert gp.cmd_probe(_cli_args(tmp_path, live=True, meta=str(meta_path)),
                        client_factory=lambda p, m: built.append(p)) == 2
    assert built == [] and window_end in capsys.readouterr().err


@pytest.mark.parametrize("arm,field,stored", [
    ("nd", "schema", "drf.golden_probe.arm.v0"),     # written under other parser semantics
    ("nd", "value", "0.62"),                           # not what parse_nd returns
    ("nd", "value", True),
    ("nd", "arm", "recall"),
    ("recall", "value", {"knows": False, "stated_outcome": "unknown", "details": ""}),
    ("recall", "value", {"knows": False, "details": ""}),
])
def test_resume_rechecks_schema_and_value(tmp_path, arm, field, stored):
    _run(tmp_path)
    path = tmp_path / "probe" / "arms" / "us-pres-2024-trump" / f"{arm}.json"
    doc = json.load(open(path))
    doc[field] = stored
    path.write_text(json.dumps(doc), encoding="utf-8")
    report, client = _run(tmp_path)
    assert client.calls == [(arm, "us-pres-2024-trump", 0.0, gp.MAX_TOKENS)]
    assert report["cost"]["reused_arms"] == 2 * len(QUESTIONS) - 1
    assert json.load(open(path))["schema"] == gp.ARM_SCHEMA and report["summary"]["status"] == "none_detected"


def test_repeated_arms_run_once(tmp_path):
    client = ScriptedClient(_honest)
    assert gp.cmd_probe(_cli_args(tmp_path, live=True, arms="nd, nd"), client_factory=lambda p, m: client) == 0
    report = json.load(open(tmp_path / "cli" / "probe_report.json"))
    assert report["arms"] == ["nd"] and report["cost"]["reused_arms"] == 0
    assert len(client.calls) == len(QUESTIONS)
    assert report["summary"]["inconclusive_reasons"].count("recall_arm_not_run") == 1


def test_nothing_reaches_the_production_ledger(tmp_path, monkeypatch):
    from app.services import forecast_ledger
    ledger = tmp_path / "ledger"
    monkeypatch.setattr(Config, "FORECAST_LEDGER_DIR", str(ledger), raising=False)
    monkeypatch.setattr(forecast_ledger, "ledger_dir", lambda: str(ledger))
    client = ScriptedClient(_honest)
    assert gp.cmd_probe(_cli_args(tmp_path, live=True, out=None), client_factory=lambda p, m: client) == 0
    written = [os.path.relpath(os.path.join(root, f), tmp_path) for root, _d, files in os.walk(tmp_path)
               for f in files]
    assert written and all(w.startswith(os.path.join("_evaluation_ledger", "probes")) for w in written)


def test_probe_report_schema_is_the_one_golden_eval_accepts():
    assert ge.PROBE_REPORT_SCHEMA == gp.REPORT_SCHEMA


def test_knobs_default_and_documented():
    assert (Config.GOLDEN_PROBE_ENABLED, Config.GOLDEN_PROBE_MAX_CALLS, Config.GOLDEN_PROBE_CONFIDENT_P) == (
        False, 120, 0.85)
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    text = open(os.path.join(root, ".env.example"), encoding="utf-8").read()
    for line in ("# GOLDEN_PROBE_ENABLED=false", "# GOLDEN_PROBE_MAX_CALLS=120", "# GOLDEN_PROBE_CONFIDENT_P=0.85"):
        assert line in text
