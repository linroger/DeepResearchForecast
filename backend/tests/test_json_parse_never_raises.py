"""FU-12: the model-reply JSON parsers never raise on hostile replies.

LLMClient._parse_json_response is documented as never raising, and the v3 research
gateway's parse_json_object returns None for an unparseable reply. Before FU-12 an
integer literal past Python's int-string digit limit (a plain ValueError, not a
JSONDecodeError) or nesting deeper than the decoder's recursion limit (RecursionError)
escaped both, and a tool call carrying such arguments escaped chat_with_tools. Each now
takes the parse-failure path its callers already handle (the JSON repair turn / retry
note, ``arguments_error``). The first-'{'-to-last-'}' extraction is linear-time.
No network, no real LLM.
"""

import random
import re
import sys
import time
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from app.config import Config
from app.utils import llm_client as lc
from tests.test_research_gateway import FakeModel, ai, gateway, msgs, rg

_DIGITS = "9" * 5000           # past the default 4300-digit int-string limit
_DEEP = 100_000                # far past the decoder's recursion limit
# The chat_json repair-turn tests live in test_numeric_nonfinite.py and the tool-call
# argument test in test_llm_transport_normalization.py, next to their fixtures.

HOSTILE = {
    "bare_huge_int": _DIGITS,
    "bare_deep_array": "[" * _DEEP + "]" * _DEEP,
    "huge_int": '{"a": ' + _DIGITS + "}",
    "huge_int_in_prose": "Here it is: {\"a\": " + _DIGITS + "} done",
    "huge_int_fenced": "```json\n{\"a\": [1, " + _DIGITS + "]}\n```",
    "huge_int_truncated": '{"a": 1, "b": ' + _DIGITS,
    "deep_array": '{"a": ' + "[" * _DEEP + "]" * _DEEP + "}",
    "deep_array_truncated": '{"a": ' + "[" * _DEEP,
    "deep_objects": '{"a":' * 30_000,
    "deep_objects_closed": '{"a":' * 30_000 + "1" + "}" * 30_000,
}


@contextmanager
def default_int_digit_limit():
    """Python's default int-string limit (4300 digits) while the block runs: the hostile
    integers above assume it, and PYTHONINTMAXSTRDIGITS may change it."""
    previous = sys.get_int_max_str_digits()
    sys.set_int_max_str_digits(4300)
    try:
        yield
    finally:
        sys.set_int_max_str_digits(previous)


@pytest.fixture(autouse=True)
def _int_digit_limit():
    with default_int_digit_limit():
        yield


# ------------------------------------------------------------------ llm_client parser
@pytest.mark.parametrize("strict", [True, False])
@pytest.mark.parametrize("name", sorted(HOSTILE))
def test_llm_parser_returns_unparsed_instead_of_raising(monkeypatch, strict, name):
    monkeypatch.setattr(Config, "LLM_JSON_STRICT_NUMBERS", strict, raising=False)
    text = HOSTILE[name]
    sentinel = object()
    assert lc.LLMClient._parse_json_response_ex(text, unparsed=sentinel) == (sentinel, False)
    assert lc.LLMClient._parse_json_response_detail(text, unparsed=sentinel) == (sentinel, False, False)
    assert lc.LLMClient._parse_json_response(text) is None


@pytest.mark.parametrize("text, expected", [
    ('{"p": 0.35, "s": "x"}', ({"p": 0.35, "s": "x"}, False)),
    ('Sure: {"a": {"b": 1}} ok', ({"a": {"b": 1}}, False)),
    ('```json\n{"a": [1, 2.5]}\n```', ({"a": [1, 2.5]}, False)),
    ('{"a": [1, {"b": "c"', ({"a": [1, {"b": "c"}]}, True)),
    ('x {"a": 1} y {"b": 2}', ("UNPARSED", False)),   # first '{' .. last '}' is not one object
    ('{"a": 1,', ({"a": 1}, True)),
    ("no braces at all", ("UNPARSED", False)),
    ('} {"a": 1', ({"a": 1}, True)),                    # a '}' only before the first '{'
    ('{"a": ' + "9" * 4300 + "}", ({"a": int("9" * 4300)}, False)),  # at the limit: parses
])
def test_llm_parser_results_unchanged_for_parseable_replies(text, expected):
    assert lc.LLMClient._parse_json_response_ex(text, unparsed="UNPARSED") == expected


def test_object_span_is_what_the_replaced_regex_matched():
    """The parser takes cleaned[first '{' : last '}' + 1] when a '}' follows the first '{';
    that is exactly what re.search(r'\\{[\\s\\S]*\\}') matched, and no match otherwise."""
    rng = random.Random(1212)
    alphabet = '{}[]" a,:\n1'
    for _ in range(3000):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 40)))
        match = re.search(r"\{[\s\S]*\}", text)
        first, last = text.find("{"), text.rfind("}")
        if 0 <= first < last:
            assert match is not None and match.group() == text[first:last + 1]
        else:
            assert match is None


def test_object_extraction_is_linear_time():
    # The replaced regex took tens of seconds here (quadratic in the count of '{' with no '}').
    text = "{ " * 100_000
    started = time.perf_counter()
    assert lc.LLMClient._parse_json_response_ex(text, unparsed="UNPARSED") == ("UNPARSED", False)
    assert time.perf_counter() - started < 3.0


# ------------------------------------------------------------------ research gateway
@pytest.mark.parametrize("strict", ["true", "false"])
@pytest.mark.parametrize("name", sorted(set(HOSTILE) - {"huge_int_truncated"}))
def test_gateway_parse_returns_none_instead_of_raising(monkeypatch, strict, name):
    monkeypatch.setenv("RESEARCH_JSON_STRICT_NUMBERS", strict)
    text = HOSTILE[name]
    assert rg.parse_json_object(text) is None
    assert rg.parse_json_object(text, ("a",)) is None
    assert isinstance(rg._describe_json_failure(text, ("a",), False), str)


@pytest.mark.parametrize("strict", ["true", "false"])
def test_gateway_truncation_repair_drops_a_cut_huge_integer(monkeypatch, strict):
    # The cut value is dropped at the last complete boundary, as for any truncated reply
    # (before FU-12 the oversized literal raised out of the element-drop repair instead).
    monkeypatch.setenv("RESEARCH_JSON_STRICT_NUMBERS", strict)
    assert rg.parse_json_object(HOSTILE["huge_int_truncated"], ("a",)) == {"a": 1}


def test_gateway_names_the_nesting_as_the_reason():
    for name in ("deep_array", "deep_array_truncated", "deep_objects", "deep_objects_closed"):
        assert rg._describe_json_failure(HOSTILE[name], ("a",), False) \
            == "JSON is nested too deeply to parse"


def test_gateway_names_an_overlong_integer_as_the_reason():
    for name in ("huge_int", "huge_int_in_prose", "bare_huge_int"):
        assert rg._describe_json_failure(HOSTILE[name], ("a",), False) \
            == "a number has more digits than JSON parsing allows"
    # at the limit the number decodes, so the reason is the missing key, not the digits
    assert rg._describe_json_failure('{"b": ' + "9" * 4300 + "}", ("a",), False) == "missing keys: a"


def test_gateway_tool_arguments_and_page_json_never_raise():
    deep = '{"q": ' + "[" * _DEEP + "]" * _DEEP + "}"
    message = SimpleNamespace(tool_calls=[{"name": "web_search", "args": deep, "id": "c1"},
                                          {"name": "web_search", "args": '{"q": "ok"}', "id": "c2"}],
                              invalid_tool_calls=[])
    bad, good = rg._normalize_tool_calls(message)
    assert bad["args"] == {} and bad["error"] == "tool arguments were not a JSON object"
    assert good["args"] == {"q": "ok"} and "error" not in good
    assert rg._json_object(deep) is None and rg._json_object('{"a": 1}') == {"a": 1}


def test_gateway_parse_unchanged_for_parseable_replies(monkeypatch):
    monkeypatch.delenv("RESEARCH_JSON_STRICT_NUMBERS", raising=False)
    assert rg.parse_json_object('pre [S3] {"a": 1, "b": [1, 2]} post', ("a",)) == {"a": 1, "b": [1, 2]}
    assert rg.parse_json_object('{"a": [{"x": 1}, {"},{"y": 2}]}', ("a",)) == {"a": [{"x": 1}, {"y": 2}]}
    assert rg.parse_json_object('{"a": {"b": 1, "c": [1, 2', ("a",)) == {"a": {"b": 1, "c": [1]}}
    assert rg.parse_json_object('{"a": ' + "9" * 4300 + "}") == {"a": int("9" * 4300)}


def test_gateway_json_retry_recovers_from_a_hostile_reply(monkeypatch):
    monkeypatch.delenv("RESEARCH_JSON_STRICT_NUMBERS", raising=False)
    model = FakeModel([ai(HOSTILE["deep_array"]), ai('{"kiqs": [], "p": 0.3}')])
    gw, _plog = gateway(model)
    notes = []
    obj = gw.json(lambda note: notes.append(note) or msgs(f"task {note or ''}"),
                  label="plan", required_keys=("kiqs", "p"))
    assert obj == {"kiqs": [], "p": 0.3}
    assert notes[1].startswith(
        "Your previous reply was not valid JSON (JSON is nested too deeply to parse).")
    stubborn = FakeModel([ai(HOSTILE["huge_int"]), ai(HOSTILE["deep_objects"])])
    gw2, _plog2 = gateway(stubborn)
    with pytest.raises(rg.JsonUnparseable):
        gw2.json(lambda note: msgs(f"task {note or ''}"), label="plan", required_keys=("kiqs",))
