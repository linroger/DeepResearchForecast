"""Provider-agnostic LLM error description (``app.utils.llm_errors``) and the failover note
``LLMClient.chat`` attaches when the fallback provider cannot take a call over.

Offline: the real LLMClient runs with scripted transports (conftest ``scripted_failover``).
"""

import pytest

from app.utils import llm_errors as le
from tests.conftest import content_filter_error


def test_describe_content_filter_error_from_sdk_attributes():
    exc = content_filter_error()
    assert le.error_status(exc) == 400 and le.error_code(exc) == "1301"
    assert le.is_content_filter_error(exc) and le.is_non_retryable_request_error(exc)
    assert le.classify_llm_error(exc) == "content filter"
    text = le.describe_llm_error(exc, max_chars=60)
    head = "BadRequestError (HTTP 400, provider code 1301, content filter): "
    assert text.startswith(head + "Error code: 400 - {'contentFilter'")
    assert len(text) <= len(head) + 60
    details = le.llm_error_details(exc)
    assert details["type"] == "BadRequestError" and details["status"] == 400 and details["code"] == "1301"
    assert details["kind"] == "content filter" and details["failover"] == ""


def test_describe_falls_back_to_message_parsing():
    class Weird(Exception):
        pass

    exc = Weird('Error code: 422 - {"error": {"code": "new_sensitive", "message": "blocked"}}')
    assert le.error_status(exc) == 422 and le.error_code(exc) == "new_sensitive"
    assert le.is_content_filter_error(exc) and le.classify_llm_error(exc) == "content filter"
    plain = RuntimeError("arbiter provider down")
    assert le.error_status(plain) is None and le.error_code(plain) == "" and le.classify_llm_error(plain) == ""
    assert le.describe_llm_error(plain) == "RuntimeError: arbiter provider down"
    assert not le.is_non_retryable_request_error(plain)
    quota = RuntimeError("HTTP 429 rate_limit: slow down")
    assert le.classify_llm_error(quota) == "quota/rate limit" and not le.is_non_retryable_request_error(quota)
    auth = RuntimeError("Error code: 401 - invalid authentication credentials")
    assert le.classify_llm_error(auth) == "authentication" and le.is_non_retryable_request_error(auth)
    assert le.describe_llm_error(RuntimeError("")) == "RuntimeError: RuntimeError('')"


def test_failover_notes_reach_the_description(scripted_failover):
    primary_error = content_filter_error()
    llm, transports = scripted_failover(primary_error, fallback_error=content_filter_error("assistant"))
    with pytest.raises(type(primary_error)) as info:
        llm.chat_json([{"role": "user", "content": "q"}])
    note = le.failover_notes(info.value)
    assert note.startswith("fallback kimi: failed (BadRequestError (HTTP 400, provider code 1301, content filter): ")
    assert transports == [("glm", False), ("kimi", True)]
    assert "; " + note in le.describe_llm_error(info.value)

    unconfigured, transports2 = scripted_failover(content_filter_error(), fallback_provider=None)
    with pytest.raises(type(primary_error)) as info2:
        unconfigured.chat_json([{"role": "user", "content": "q"}])
    assert le.failover_notes(info2.value) == "fallback: not configured (LLM_FALLBACK_PROVIDER unset)"
    assert transports2 == [("glm", False)]


def test_failover_note_is_attached_once(scripted_failover):
    err = content_filter_error()
    llm, _ = scripted_failover(err, fallback_provider=None)
    for _ in range(2):
        with pytest.raises(type(err)):
            llm.chat_json([{"role": "user", "content": "q"}])
    assert len([n for n in (getattr(err, "__notes__", None) or []) if str(n).startswith("fallback")]) == 1
