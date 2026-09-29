"""Offline tests for app/utils/llm_text.py (INFRA-1): content flattening, think stripping
and finish-reason normalization, pinned to the research gateway's vocabulary."""

import os
import sys
import time
from types import SimpleNamespace

import pytest

from app.utils.llm_text import (
    FINISH_REASONS,
    flatten_content,
    has_dangling_think,
    normalize_finish_reason,
    strip_think,
)

# Same bridge import pattern as test_research_gateway.py, used only to read the gateway's
# finish-reason frozensets so the two transports keep one vocabulary.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_BRIDGE_DIR = os.path.join(_REPO_ROOT, "deerflow_bridge")
if _BRIDGE_DIR not in sys.path:
    sys.path.insert(0, _BRIDGE_DIR)

import research_gateway as rg  # noqa: E402


# ---------------------------------------------------------------- flatten_content
def test_flatten_content_str_and_none():
    assert flatten_content("hello") == "hello"
    assert flatten_content("") == ""
    assert flatten_content(None) == ""


def test_flatten_content_list_of_dict_parts_keeps_text_only():
    parts = [
        {"type": "text", "text": "alpha"},
        {"type": "reasoning", "text": "hidden chain"},
        {"type": "output_text", "text": "beta"},
        {"text": "gamma"},  # a missing type counts as text
        {"type": "image_url", "image_url": {"url": "x"}},
        {"type": "text", "text": 42},  # non-string text is skipped
        "delta",
    ]
    assert flatten_content(parts) == "alpha beta gamma delta"


def test_flatten_content_list_of_objects():
    parts = [
        SimpleNamespace(type="text", text="one"),
        SimpleNamespace(type="thinking", thinking="nope", text="nope"),
        SimpleNamespace(text="two"),
    ]
    assert flatten_content(parts) == "one two"
    assert flatten_content(()) == ""


def test_flatten_content_joins_parts_with_a_space_like_the_gateway():
    # research_gateway._flatten_content semantics: text parts only, joined with " ".
    assert flatten_content([{"type": "text", "text": "a"}, {"type": "tool_use"}, "b"]) == "a b"
    assert flatten_content(12) == "12"


# ---------------------------------------------------------------- strip_think
def test_strip_think_closed_block():
    assert strip_think("<think>x</think>answer") == ("answer", True)
    assert strip_think("<THINK>x</Think>  answer  ") == ("answer", True)


def test_strip_think_leading_unterminated_block_returns_empty():
    assert strip_think("<think>unterminated reasoning") == ("", True)
    assert strip_think("<think>") == ("", True)


def test_strip_think_orphan_closer_and_trailing_dangling_opener():
    assert strip_think("reasoning</think>answer") == ("answer", True)
    assert strip_think("answer <think> cut mid-reasoning") == ("answer", True)


def test_strip_think_without_think_is_unchanged():
    assert strip_think("plain answer") == ("plain answer", False)
    # whitespace trimming alone is not a think change
    assert strip_think("  padded  ") == ("padded", False)
    assert strip_think("") == ("", False)


@pytest.mark.parametrize("raw, clean", [
    # Expected values are research_gateway._strip_think's output for the same input.
    ("<think>a</think>b", "b"),
    ("x</think>y", "y"),
    ("q <think> r", "q"),
    ("<think>a<think>b</think>c</think>d", "d"),
    ("a</think>b<think>c</think>d", "bd"),
])
def test_strip_think_gateway_semantics(raw, clean):
    assert strip_think(raw) == (clean, True)


def test_strip_think_is_linear_time():
    started = time.monotonic()
    clean, changed = strip_think("<think>" * 200_000)
    assert (clean, changed) == ("", True)
    assert time.monotonic() - started < 1.0


def test_has_dangling_think():
    assert has_dangling_think("<think>cut")
    assert has_dangling_think("answer <think> cut")
    assert not has_dangling_think("<think>a</think>answer")
    assert not has_dangling_think("reasoning</think>answer")
    assert not has_dangling_think("plain")
    assert not has_dangling_think("")


# ---------------------------------------------------------------- finish reasons
@pytest.mark.parametrize("raw, expected", [
    ("stop", "stop"), ("end_turn", "stop"), ("stop_sequence", "stop"), ("eos", "stop"),
    ("length", "length"), ("max_tokens", "length"), ("MAX_TOKENS", "length"),
    ("max_output_tokens", "length"),
    ("tool_calls", "tool_calls"), ("function_call", "tool_calls"), ("tool_use", "tool_calls"),
    ("content_filter", "content_filter"), ("safety", "content_filter"),
    ("SAFETY", "content_filter"), ("sensitive", "content_filter"),
    ("content_filtered", "content_filter"),
    ("error", "error"), ("network_error", "error"), ("aborted", "error"),
    (None, "unknown"), ("", "unknown"), ("something_new", "unknown"),
])
def test_normalize_finish_reason(raw, expected):
    assert normalize_finish_reason(raw) == expected


def test_normalize_finish_reason_reads_enum_value():
    assert normalize_finish_reason(SimpleNamespace(value="MAX_TOKENS")) == "length"


def test_normalize_finish_reason_output_vocabulary():
    assert set(FINISH_REASONS) == {"stop", "length", "tool_calls", "content_filter", "error", "unknown"}


def test_every_gateway_finish_reason_maps_to_a_known_value():
    assert all(normalize_finish_reason(r) == "content_filter"
               for r in rg._CONTENT_FILTER_FINISH_REASONS)
    assert all(normalize_finish_reason(r) == "length" for r in rg._TRUNCATION_FINISH_REASONS)
    assert all(normalize_finish_reason(r) == "error" for r in rg._ABORTED_FINISH_REASONS)
