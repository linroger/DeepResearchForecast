"""Golden tests for the security helpers (EXECPLAN2 I-7-3, guards F-13-1/F-8-1/F-13-2)."""

import socket

import pytest

from app.utils import security
from app.utils.security import (
    quote_env_value,
    redact_secrets,
    redact_text,
    sanitize_env_value,
    validate_safe_url,
)


def test_redact_secrets_masks_sensitive_keys():
    out = redact_secrets({"api_key": "sk-x", "token": "t", "provider": "minimax",
                          "nested": {"password": "p", "ok": 1}})
    assert out["api_key"] == "***REDACTED***"
    assert out["token"] == "***REDACTED***"
    assert out["provider"] == "minimax"
    assert out["nested"]["password"] == "***REDACTED***"
    assert out["nested"]["ok"] == 1


def test_redact_secrets_does_not_overmatch():
    out = redact_secrets({"monkey": "fine", "donkey_count": 3})
    assert out == {"monkey": "fine", "donkey_count": 3}


def test_redact_text_scrubs_inline_tokens():
    assert "***REDACTED***" in redact_text("key is sk-abcdefgh12345 here")
    assert "sk-abcdefgh12345" not in redact_text("key is sk-abcdefgh12345 here")


def test_sanitize_env_value_rejects_newlines():
    with pytest.raises(ValueError):
        sanitize_env_value("a\nINJECT=evil")
    assert sanitize_env_value("  sk-ok  ") == "sk-ok"


def test_quote_env_value():
    assert quote_env_value("MiniMax-M3") == "MiniMax-M3"
    assert quote_env_value("a b") == '"a b"'
    assert quote_env_value("a#b") == '"a#b"'


def test_validate_safe_url_allows_public_and_loopback(monkeypatch):
    # Offline (INFRA-12 egress guard): resolve the public host from a fixed table
    # instead of live DNS; the check under test only inspects the returned IPs.
    resolved = {"api.openai.com": "162.159.140.245", "localhost": "127.0.0.1"}
    monkeypatch.setattr(
        security.socket, "getaddrinfo",
        lambda host, port, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (resolved[host], port))])
    assert validate_safe_url("https://api.openai.com/v1")
    assert validate_safe_url("http://localhost:11434/v1")  # local LLM allowed by default


def test_validate_safe_url_blocks_metadata_and_bad_scheme():
    with pytest.raises(ValueError):
        validate_safe_url("http://169.254.169.254/latest/meta-data")
    with pytest.raises(ValueError):
        validate_safe_url("ftp://example.com")


def test_validate_safe_url_block_private_mode():
    with pytest.raises(ValueError):
        validate_safe_url("http://localhost:11434/v1", block_private=True)
    with pytest.raises(ValueError):
        validate_safe_url("http://10.0.0.5/v1", block_private=True)
