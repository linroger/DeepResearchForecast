"""SESSION-B: REAL-LLM (MiniMax) Mandarin translation must pass the variant audit.

These tests reproduce the exact failure signature seen on a completed report
(report_54f0a34a90b6): a MiniMax-class model that drifts numbers, leaves residual
English lines, and would otherwise trip the final editorial lint, producing the three
hard-audit failures:

  1. "translation numeric-token multiset differs from primary"
  2. "translation would still be rewritten by final editorial lint"
  3. "translation contains N target-language contamination lines"

The root cause was that the on-demand / auto translation's CONTAMINATION-REPAIR pass
(`_translate_impurity_segments`) re-translated residual prose WITHOUT placeholder-
protecting the numbers/citations inside it, so the model was free to drop, introduce,
or CJK-ize a figure.  The fix routes that pass through the same byte-exact token
protection used by the structure-preserving translator, adds a per-line numeric
fail-closed guard, and lints the variant to the audit's exact body-view fixed point
BEFORE auditing.

No network / real LLM: a scripted MiniMax-drift fake speaks every translation protocol
(whole-unit, slot-batch, single-fragment, impurity-JSON) and deliberately drifts.
"""

import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services import report_lint as _rl  # noqa: E402
from app.services.report_agent import ReportAgent, _REFS_HEADINGS  # noqa: E402


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


def _run_auto_sequence(worker, source_md, *, spine=None):
    """Replicate the on-demand / auto post-translation sequence exactly:
    per-H2 free-form translation (with skeleton fallback) -> contamination repair ->
    lint-before-audit fixed point -> isolated variant audit."""
    chunks = ReportAgent._split_markdown_h2_sections(source_md)
    tgt_name = "简体中文（Simplified Chinese）"
    translated = []
    for ch in chunks:
        first = ch.split("\n", 1)[0].strip()
        if first in _REFS_HEADINGS:
            translated.append(worker._localize_translation_references(ch, "zh"))
        else:
            translated.append(worker._translate_section(ch, tgt_name))
    translated_md = "\n\n".join(translated).strip() + "\n"
    translated_md = worker._repair_variant_contamination(translated_md, True, tgt_name).strip() + "\n"
    translated_md = worker._lint_variant_to_audit_fixed_point(translated_md, "Chinese", spine)
    audit, _cp = worker._audit_translation_variant(
        "report_test", source_md, translated_md, "en", "zh", {}, enforce_citations=False
    )
    return audit, translated_md


def test_reallm_drift_variant_passes_audit():
    """(a) A realistic MiniMax-drift model (drops a heading level & placeholder on the
    whole-unit call, CJK-izes numbers, leaves an English line) is fully repaired: the
    guards restore numeric parity, clear contamination, and the post-lint audit passes."""
    stub = MiniMaxDriftStub(echo_english=_ECHO)
    worker = _worker(stub)
    audit, final_md = _run_auto_sequence(worker, SOURCE_MD)

    assert audit["number_parity"]["passed"], (
        "numeric multiset drifted: "
        f"source-variant={_missing(audit)} variant-source={_extra(audit)}"
    )
    assert audit["section_parity"]["passed"], "heading-level sequence drifted"
    assert audit["table_parity"]["passed"], "table row/column shape drifted"
    contamination = (audit["language_lint"].get("language_contamination") or {}).get("lines", 0)
    assert contamination == 0, f"{contamination} residual English lines remained"
    assert not audit["language_lint"].get("changed"), "final lint would still rewrite the variant"
    assert audit["hard_passed"], f"variant audit failed: {audit['issues']}"
    assert audit["issues"] == []


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


def test_reallm_introduced_number_never_corrupts_numeric_multiset():
    """The numeric invariant is fail-closed: even a pathological model that INSISTS on
    adding a bare decimal to every repaired segment can never corrupt the numeric
    multiset — the guard rejects the drifted candidate, so numbers stay byte-identical."""
    stub = MiniMaxDriftStub(introduce_number=True, echo_english=_ECHO)
    worker = _worker(stub)
    audit, _final = _run_auto_sequence(worker, SOURCE_MD)
    # Numbers must NEVER drift, regardless of whether contamination could be cleared.
    assert audit["number_parity"]["passed"], (
        "a model-introduced number corrupted the multiset: "
        f"source-variant={_missing(audit)} variant-source={_extra(audit)}"
    )
    assert "translation numeric-token multiset differs from primary" not in audit["issues"]


def test_auto_path_routes_through_structure_preserving_protection():
    """(b) The auto / on-demand path provably routes through the structure-preserving
    translator: a drifting whole-unit candidate is rejected and the skeleton slot-batch
    protocol (which protects numbers/citations by construction) is invoked."""
    stub = MiniMaxDriftStub(echo_english=_ECHO)
    worker = _worker(stub)

    called = {"skeleton": 0, "protect": 0}
    real_skeleton = worker._translate_from_source_skeleton
    real_protect = worker._protect_translation_tokens.__func__

    def spy_skeleton(markdown, name):
        called["skeleton"] += 1
        return real_skeleton(markdown, name)

    worker._translate_from_source_skeleton = spy_skeleton
    worker._translate_section(SOURCE_MD.split("## Part 1", 1)[1], "简体中文（Simplified Chinese）")

    assert called["skeleton"] >= 1, "whole-unit drift did not fall back to the skeleton translator"
    assert stub.skeleton_batches >= 1, "structure-preserving slot-batch protocol was never called"


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


def _missing(audit):
    from collections import Counter
    np = audit["number_parity"]
    return dict(Counter(np["source"]) - Counter(np["variant"]))


def _extra(audit):
    from collections import Counter
    np = audit["number_parity"]
    return dict(Counter(np["variant"]) - Counter(np["source"]))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
