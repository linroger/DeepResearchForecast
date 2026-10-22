"""Scripted real-world drift cases against the model-led default translator.

No real provider is called. Whole readable sections, parser checks, separate
fixture-known semantic review and one bounded repair exercise the native research
translation entry point. Introduced numbers remain unpublishable; no skeleton,
filter ladder or lint rewrite is the default. Direct contamination/protection
helper tests are retained explicitly as historical compatibility controls.
"""

import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services import report_lint as _rl  # noqa: E402
from app.services.report_agent import ReportAgent  # noqa: E402
from model_translation_fakes import model_protocol, preserve_carriers  # noqa: E402


# --------------------------------------------------------------------------------------
# A scripted MiniMax-class translator.  It "translates" by mapping ASCII words to CJK
# glyphs while preserving ⟦…⟧ placeholders and alnum proper nouns, and it DRIFTS exactly
# the way MiniMax does in the field: on the free-form whole-unit call it drops a heading,
# CJK-izes a number and leaves an English sentence; on the number-protected impurity call
# it tries to add a stray decimal (which the guard must neutralise).
# --------------------------------------------------------------------------------------
def _cjk_word(word: str) -> str:
    # U+4E07 is 万, a Chinese magnitude: "160 hours" must not become "160 万…", which
    # reads as 1.6 million.  Real translations never put a magnitude there.
    glyphs = "".join(
        (chr(0x4E00 + (ord(ch.lower()) - 97) % 40) if ch.lower() != "h" else "丨")
        for ch in word[:3] if ch.isalpha()
    )
    return glyphs or "词"


def _zhify(value: str) -> str:
    """Translate ASCII words to CJK glyphs, leaving ⟦…⟧ placeholders and \\x00 masks."""
    parts = re.split(r"(⟦[^⟧]*⟧|\x00LP\d+\x00|\x00[A-Z0-9_]+\x00)", value)
    out = []
    for part in parts:
        if part.startswith("⟦") or part.startswith("\x00"):
            out.append(part)
        else:
            out.append(
                re.sub(
                    r"(?<![A-Za-z0-9])[A-Za-z]{2,}(?![A-Za-z0-9])",
                    lambda m: _cjk_word(m.group(0)),
                    part,
                )
            )
    return "".join(out)


class MiniMaxDriftStub:
    """Drifts on the free-form whole-unit call; tries to inject a stray number on the
    (now protected) impurity call.  ``echo_english_slots`` names slot cores that the
    slot-batch model refuses to translate (returns verbatim English) so the structure-
    preserving path emits residual English lines that the contamination pass must fix."""

    model = "minimax-drift-stub"
    provider = "fake"

    def __init__(self, *, introduce_number: bool = False, echo_english=()):
        self.calls = []
        self.skeleton_batches = 0
        self.introduce_number = introduce_number
        self.echo_english = set(echo_english)

    # unified chat entry — dispatches by system-prompt fingerprint
    def chat(self, messages=None, temperature=0.0, max_tokens=4096, tier="strong", **kw):
        system = messages[0]["content"]
        user = messages[-1]["content"]
        self.calls.append(("chat", tier))
        if "same alphabetic keys" in system:
            # structure-preserving slot-batch protocol
            self.skeleton_batches += 1
            req = json.loads(user)
            out = {}
            for key, core in req.items():
                if core.strip() in self.echo_english:
                    out[key] = core  # refuse → English echo → residual contamination
                else:
                    out[key] = _zhify(core)
            return json.dumps(out, ensure_ascii=False)
        if "one Markdown prose fragment" in system:
            core = user
            if core.strip() in self.echo_english:
                return core
            return _zhify(core)
        # Free-form whole-unit translator → DRIFT so the structural guard rejects it and
        # falls back to the skeleton translator: drop one placeholder, CJK-ize a bare
        # number, and leave the block otherwise "translated".
        drifted = _zhify(user)
        drifted = re.sub(r"⟦[^⟧]*⟧", "", drifted, count=1)  # drop an immutable token
        return drifted

    def chat_json(self, messages=None, temperature=0.0, max_tokens=4096, tier="fast", **kw):
        self.calls.append(("chat_json", tier))
        user = messages[-1]["content"]
        out = {}
        for line in user.splitlines():
            m = re.match(r"^(\d+)\.\s+(.*)$", line)
            if not m:
                continue
            translated = _zhify(m.group(2))
            if self.introduce_number:
                # A pathological model hallucinating a bare figure the guard must reject.
                translated = translated + "（约 0.4）"
            out[m.group(1)] = translated
        return out


class BatchEchoSingleFragmentSuccessStub(MiniMaxDriftStub):
    """Batch repair echoes deterministically; the guarded fragment call succeeds."""

    def chat_json(self, messages=None, temperature=0.0, max_tokens=4096, tier="fast", **kw):
        self.calls.append(("chat_json_echo", tier))
        out = {}
        for line in messages[-1]["content"].splitlines():
            match = re.match(r"^(\d+)\.\s+(.*)$", line)
            if match:
                out[match.group(1)] = match.group(2)
        return out

    def chat(self, messages=None, temperature=0.0, max_tokens=4096, tier="strong", **kw):
        if "one Markdown prose fragment" in messages[0]["content"]:
            self.calls.append(("single_fragment", tier))
            return _zhify(messages[-1]["content"])
        return super().chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            tier=tier,
            **kw,
        )


def _worker(stub):
    w = ReportAgent.__new__(ReportAgent)
    w.llm = stub
    w.output_language = "Chinese"
    w._forecast_spine = None
    return w


# A compact English forecast body: H1 + summary blockquote, two H2 sections with prose
# numbers, a numeric table, and a long English sentence chosen to be left untranslated.
SOURCE_MD = """# Grid Storage Outlook 2040

> Global grid-scale battery storage scales past 300 GW by 2030 with 82% probability.

## Part 1 — Baseline

Annual additions reach 180 GW by 2030 and 500 GW by 2040, up from 100 GW in 2025.
Non-lithium long-duration storage captures at least 20% of grid capacity by 2041.

Iron-air stacks target US$200-400/MWh at durations of 36-160 hours by 2035.

## Part 2 — Regional

| Region | 2030 Share | 2040 Share |
| --- | --- | --- |
| China | 45% | 42% |
| United States | 30% | 27% |
| Rest of World | 25% | 31% |

Australia is the regional case where the behind-the-meter segment outpaces the grid-scale segment through 2040.
"""

# Deterministically choose the residual-English cores the slot model refuses (contamination).
_ECHO = [
    "Australia is the regional case where the behind-the-meter segment outpaces the grid-scale segment through 2040.",
]


def _raw_zh(value):
    return preserve_carriers(value, lambda text: _zhify(text.replace("## References", "## 参考来源")))


class _RawDriftStub:
    """Drop structure/echo prose once, or persistently invent a numeric claim.

    The review oracle is the separate known faithful renderer, never the corrupt
    generation function. Thus each deliberate defect receives a false verdict.
    """

    model = "raw-scripted-drift"
    provider = "offline"

    def __init__(self, *, introduce_number=False):
        self.calls = []
        self.introduce_number = introduce_number

    def chat(self, messages=None, **_kwargs):
        payload = json.loads(messages[-1]["content"])
        self.calls.append(payload)
        assert "⟦" not in messages[-1]["content"]

        def generate(source):
            target = _raw_zh(source)
            if self.introduce_number:
                return target.rstrip() + "（约 0.4）" if "Annual additions" in source else target
            if not payload.get("repair"):
                if "Annual additions" in source:
                    return re.sub(r"(?m)^#{1,6}[^\n]*(?:\n|$)", "", target, count=1)
                for residual in _ECHO:
                    if residual in source:
                        target = target.replace(_raw_zh(residual), residual)
            return target

        response = model_protocol(messages, generate, expected_fn=_raw_zh)
        assert response is not None, "native default used an obsolete translation protocol"
        return response

    def chat_json(self, messages=None, **kwargs):
        return json.loads(self.chat(messages, **kwargs))


def _run_default(worker, source_md):
    # Exercise the real default instead of replicating an obsolete auto sequence.
    return worker.translate_research_markdown(source_md, label="research::sessionb-drift")


def test_scripted_drift_is_repaired_once_by_native_model_review():
    stub = _RawDriftStub()
    result = _run_default(_worker(stub), SOURCE_MD)
    audit, final_md = result["audit"], result["translated_md"]

    assert result["available"] and audit["hard_passed"], audit["issues"]
    assert audit["fact_fidelity"]["passed"] and audit["section_parity"]["passed"]
    assert final_md == _raw_zh(SOURCE_MD).strip() + "\n"
    assert ReportAgent._translation_table_signature(final_md) == ReportAgent._translation_table_signature(SOURCE_MD)
    assert ReportAgent._translation_number_multiset(final_md) == ReportAgent._translation_number_multiset(SOURCE_MD)
    assert _ECHO[0] not in final_md
    repairs = [payload for payload in stub.calls if payload.get("repair")]
    assert len(repairs) == 1
    assert len(repairs[0]["entries"]) == 2  # dropped heading + echoed Regional prose
    assert all("# Grid Storage Outlook" not in source for source in repairs[0]["entries"].values())
    assert any("pairs" in payload for payload in stub.calls)


def test_impurity_batch_echo_escalates_to_guarded_single_fragment():
    stub = BatchEchoSingleFragmentSuccessStub()
    worker = _worker(stub)
    contaminated = (
        "# 标题\n\n"
        "The NDRC capacity-payment reform remains decisive for storage deployment in 2040.\n"
    )

    repaired = worker._repair_variant_contamination(
        contaminated,
        target_is_cjk=True,
        target_language_name="简体中文（Simplified Chinese）",
    )

    assert _rl.detect_language_contamination(repaired, "Chinese")["lines"] == 0
    assert any(kind == "chat_json_echo" for kind, _tier in stub.calls)
    assert any(kind == "single_fragment" for kind, _tier in stub.calls)


def test_default_introduced_number_is_rejected_after_one_semantic_repair():
    stub = _RawDriftStub(introduce_number=True)
    result = _run_default(_worker(stub), SOURCE_MD)
    audit = result["audit"]

    assert result["available"] is False and audit["hard_passed"] is False
    assert audit["fact_fidelity"]["passed"] is False
    assert audit["model_translation"]["complete"] is False
    assert any("semantic review rejected" in issue for details in audit["model_translation"]["issues"].values()
               for issue in details)
    repairs = [payload for payload in stub.calls if payload.get("repair")]
    assert len(repairs) == 1 and len(repairs[0]["entries"]) == 1
    # The rejected candidate is not promoted as an accepted section or receipt.
    baseline = next(row for row in audit["model_translation"]["sections"] if "Annual additions" in row["source"])
    assert baseline["receipt"] is None
    assert "约 0.4" not in result["translated_md"]


def test_default_sends_raw_sections_without_legacy_protection_or_rewrite(monkeypatch):
    stub = _RawDriftStub()

    def obsolete(*_args, **_kwargs):
        raise AssertionError("native default entered legacy skeleton/protection/lint")
    for name in ("_translate_section", "_translate_from_source_skeleton", "_protect_translation_tokens",
                 "_repair_variant_contamination", "_lint_variant_to_audit_fixed_point"):
        monkeypatch.setattr(ReportAgent, name, obsolete)

    result = _run_default(_worker(stub), SOURCE_MD)
    assert result["available"] and result["audit"]["fact_fidelity"]["passed"]
    raw_entries = [text for payload in stub.calls if "entries" in payload for text in payload["entries"].values()]
    assert any("US$200-400/MWh" in text and "36-160 hours" in text for text in raw_entries)
    assert any(_ECHO[0] in text for text in raw_entries)
    assert all("⟦" not in text for text in raw_entries)
    assert len([payload for payload in stub.calls if payload.get("repair")]) == 1


def test_number_in_prose_and_table_cell_round_trip_byte_exact():
    """(c) Number-in-prose and number-in-table-cell protection round-trips byte-exact and
    preserves the numeric multiset through a placeholder-preserving translation."""
    worker = _worker(MiniMaxDriftStub())
    prose_and_table = (
        "Additions reach 180 GW by 2030 and US$200-400/MWh by 2035, up 27.6% from 2025.\n\n"
        "| Region | 2030 | 2040 |\n| --- | --- | --- |\n| China | 45% | 1,293,546 |\n"
    )
    protected, mapping = worker._protect_translation_tokens(prose_and_table)
    # No bare Arabic numeral survives in what the model would see.
    assert not re.search(r"(?<![A-Za-z0-9⟧_])\d", re.sub(r"⟦[^⟧]*⟧", "", protected)), \
        "a bare number leaked past protection"
    # A placeholder-preserving translation restores to the exact source numeric multiset.
    translated_like = _zhify(protected)
    restored, issues = worker._restore_translation_tokens(translated_like, mapping)
    assert not issues, f"placeholder restore reported issues: {issues}"
    assert worker._translation_number_multiset(restored) == \
        worker._translation_number_multiset(prose_and_table)
    # And a pure round-trip (identity translation) reproduces the source bytes exactly.
    identity, _i2 = worker._restore_translation_tokens(protected, mapping)
    assert identity == prose_and_table


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
