"""Auth gate vs. proxied requests (EXECPLAN2 F-13-0 hardening).

The Vite dev server proxies /api to Flask over loopback, which the gate trusts
without a token. When Vite is exposed to the network (FRONTEND_HOST), the proxy
forwards the real client address in X-Forwarded-For; the gate must then treat
the request as non-loopback. Forwarding headers may only lower trust, never
raise it.
"""

import pytest
from werkzeug.datastructures import Headers

from app import _forwarded_client_addrs, _has_forwarded_remote_client, _is_loopback_addr
from app.config import Config

PROBE = "/api/__auth_gate_probe__"  # 不存在的 /api 路由：过闸 → 404，被拦 → 401/403


@pytest.fixture
def client():
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _get(client, remote="127.0.0.1", headers=None):
    return client.get(PROBE, headers=headers or {}, environ_base={"REMOTE_ADDR": remote})


@pytest.mark.parametrize("addr", [
    "127.0.0.1", "127.8.9.10", "::1", "localhost", "::ffff:127.0.0.1",
    "[::1]:4711", "127.0.0.1:5555",
])
def test_loopback_addresses(addr):
    assert _is_loopback_addr(addr) is True


@pytest.mark.parametrize("addr", [
    "", None, "192.168.1.20", "10.0.0.5:80", "2001:db8::1", "[2001:db8::1]:4711",
    "::ffff:192.168.1.20", "unknown", "_hidden", "0.0.0.0",
])
def test_non_loopback_addresses(addr):
    assert _is_loopback_addr(addr) is False


def test_forwarded_addrs_cover_all_header_styles():
    headers = Headers([
        ("X-Forwarded-For", "127.0.0.1, 192.0.2.7"),
        ("X-Real-IP", "198.51.100.3"),
        ("Forwarded", 'for="[2001:db8::1]:4711";proto=http, for=127.0.0.1'),
    ])
    assert _forwarded_client_addrs(headers) == [
        "127.0.0.1", "192.0.2.7", "198.51.100.3", '"[2001:db8::1]:4711"', "127.0.0.1",
    ]
    assert _has_forwarded_remote_client(headers) is True
    assert _has_forwarded_remote_client(Headers([("X-Forwarded-For", "::1, 127.0.0.1")])) is False


def test_local_request_without_forwarding_passes(client, monkeypatch):
    monkeypatch.setattr(Config, "APP_API_TOKEN", "")
    assert _get(client).status_code == 404


@pytest.mark.parametrize("xff", ["127.0.0.1", "::1", "::ffff:127.0.0.1"])
def test_local_browser_through_vite_proxy_passes(client, monkeypatch, xff):
    monkeypatch.setattr(Config, "APP_API_TOKEN", "")
    assert _get(client, headers={"X-Forwarded-For": xff}).status_code == 404


@pytest.mark.parametrize("headers", [
    {"X-Forwarded-For": "192.0.2.2"},
    {"X-Forwarded-For": "127.0.0.1,192.0.2.2"},  # 客户端伪造的环回前缀被代理追加真实地址
    {"X-Forwarded-For": "garbage"},
    {"X-Real-IP": "192.0.2.2"},
    {"Forwarded": "for=192.0.2.2"},
])
def test_lan_client_through_proxy_is_not_trusted_without_token(client, monkeypatch, headers):
    monkeypatch.setattr(Config, "APP_API_TOKEN", "")
    resp = _get(client, headers=headers)
    assert resp.status_code == 403
    assert "loopback-only" in resp.get_json()["error"]


def test_lan_client_through_proxy_needs_valid_token(client, monkeypatch):
    monkeypatch.setattr(Config, "APP_API_TOKEN", "s3cret")
    xff = {"X-Forwarded-For": "192.0.2.2"}
    assert _get(client, headers=xff).status_code == 401
    assert _get(client, headers={**xff, "X-API-Token": "wrong"}).status_code == 401
    assert _get(client, headers={**xff, "X-API-Token": "s3cret"}).status_code == 404


def test_forwarding_headers_never_upgrade_a_remote_peer(client, monkeypatch):
    monkeypatch.setattr(Config, "APP_API_TOKEN", "")
    resp = _get(client, remote="192.0.2.9", headers={"X-Forwarded-For": "127.0.0.1"})
    assert resp.status_code == 403
