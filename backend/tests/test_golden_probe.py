"""EVAL-12 (P05): golden-set contamination probes (backend/scripts/golden_probe.py).

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


def test_recall_parser_is_strict_and_caps_details():
    assert gp.parse_recall({"knows": True, "stated_outcome": "yes", "details": "x " * 100}) == {
        "knows": True, "stated_outcome": "YES", "details": " ".join(["x"] * gp.DETAILS_MAX_WORDS)}
    assert gp.parse_recall({"knows": "maybe", "stated_outcome": "YES"}) is None
    assert gp.parse_recall({"knows": False, "stated_outcome": "PROBABLY"}) is None
    assert gp.parse_recall("UNKNOWN") is None


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


def test_cli_provider_stamped_never_none_detected(tmp_path):
    report, _ = _run(tmp_path, closed_book=False)
    assert report["closed_book_attested"] is False
    assert report["summary"]["status"] == "inconclusive"
    assert report["summary"]["inconclusive_reasons"] == ["not_closed_book_attested"]


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


def _cli_args(tmp_path, **over):
    args = dict(live=False, provider="deepseek", model="scripted-1", arms="nd,recall", out=str(tmp_path / "cli"),
                golden=ge.GOLDEN_PATH, meta=gp.META_PATH)
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


def test_knobs_default_and_documented():
    assert (Config.GOLDEN_PROBE_ENABLED, Config.GOLDEN_PROBE_MAX_CALLS, Config.GOLDEN_PROBE_CONFIDENT_P) == (
        False, 120, 0.85)
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    text = open(os.path.join(root, ".env.example"), encoding="utf-8").read()
    for line in ("# GOLDEN_PROBE_ENABLED=false", "# GOLDEN_PROBE_MAX_CALLS=120", "# GOLDEN_PROBE_CONFIDENT_P=0.85"):
        assert line in text
