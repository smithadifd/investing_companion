"""Trusted-proxy-aware client IP resolution (rate-limit identity, fix #3).

X-Forwarded-For is only honored when the direct peer is a configured trusted
proxy — otherwise a client could spoof its rate-limit key. DB-free.
"""

from starlette.requests import Request

from app.core.config import settings as app_settings
from app.core.dependencies import get_client_ip


def _req(peer, xff=None):
    headers = []
    if xff is not None:
        headers.append((b"x-forwarded-for", xff.encode()))
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "scheme": "http",
        "headers": headers,
        "client": (peer, 12345) if peer else None,
        "server": ("test", 80),
    }
    return Request(scope)


def test_untrusted_peer_xff_is_ignored(monkeypatch):
    """Spoofed XFF from a direct, untrusted client must NOT be honored."""
    monkeypatch.setattr(app_settings, "TRUSTED_PROXIES", [])
    req = _req("203.0.113.9", xff="1.2.3.4")  # attacker claims to be 1.2.3.4
    assert get_client_ip(req) == "203.0.113.9"  # real peer wins


def test_trusted_proxy_xff_is_honored(monkeypatch):
    monkeypatch.setattr(app_settings, "TRUSTED_PROXIES", ["10.0.0.1"])
    req = _req("10.0.0.1", xff="198.51.100.7")
    assert get_client_ip(req) == "198.51.100.7"


def test_trusted_proxy_returns_rightmost_untrusted_in_chain(monkeypatch):
    """With trusted proxies appended, the real client is the rightmost address
    that is not itself a trusted proxy."""
    monkeypatch.setattr(app_settings, "TRUSTED_PROXIES", ["10.0.0.0/8"])
    # client -> edge proxy (10.x) -> app proxy (10.x); XFF: client, edge
    req = _req("10.0.0.2", xff="198.51.100.7, 10.0.0.9")
    assert get_client_ip(req) == "198.51.100.7"


def test_cidr_trusted_proxy(monkeypatch):
    monkeypatch.setattr(app_settings, "TRUSTED_PROXIES", ["172.16.0.0/12"])
    req = _req("172.16.5.5", xff="8.8.8.8")
    assert get_client_ip(req) == "8.8.8.8"


def test_peer_not_in_trusted_list_ignores_xff(monkeypatch):
    monkeypatch.setattr(app_settings, "TRUSTED_PROXIES", ["10.0.0.1"])
    req = _req("192.0.2.50", xff="8.8.8.8")
    assert get_client_ip(req) == "192.0.2.50"


def test_no_client_no_xff_returns_none(monkeypatch):
    monkeypatch.setattr(app_settings, "TRUSTED_PROXIES", [])
    req = _req(None)
    assert get_client_ip(req) is None


def test_trusted_proxy_no_xff_falls_back_to_peer(monkeypatch):
    monkeypatch.setattr(app_settings, "TRUSTED_PROXIES", ["10.0.0.1"])
    req = _req("10.0.0.1")
    assert get_client_ip(req) == "10.0.0.1"


def test_malformed_trusted_proxy_entry_is_ignored(monkeypatch):
    monkeypatch.setattr(app_settings, "TRUSTED_PROXIES", ["not-an-ip", "10.0.0.1"])
    req = _req("10.0.0.1", xff="8.8.8.8")
    assert get_client_ip(req) == "8.8.8.8"  # malformed entry skipped, valid one honored
