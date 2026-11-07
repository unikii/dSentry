from starlette.requests import Request

from app.config import settings
from app.routes.sessions import _client_ip


def _request(headers: dict[str, str], peer: str = "10.0.0.5") -> Request:
    return Request(
        {
            "type": "http",
            "headers": [(k.encode(), v.encode()) for k, v in headers.items()],
            "client": (peer, 12345),
        }
    )


def test_forwarded_headers_are_ignored_when_not_trusted(monkeypatch):
    monkeypatch.setattr(settings, "trust_proxy_headers", False)
    request = _request(
        {"x-forwarded-for": "198.51.100.9, 203.0.113.7", "x-real-ip": "192.0.2.1"}
    )
    assert _client_ip(request) == "10.0.0.5"


def test_real_ip_wins_over_forwarded_for(monkeypatch):
    monkeypatch.setattr(settings, "trust_proxy_headers", True)
    request = _request(
        {"x-forwarded-for": "198.51.100.9, 203.0.113.7", "x-real-ip": "192.0.2.1"}
    )
    assert _client_ip(request) == "192.0.2.1"


def test_rightmost_forwarded_address_is_used(monkeypatch):
    monkeypatch.setattr(settings, "trust_proxy_headers", True)
    request = _request({"x-forwarded-for": "198.51.100.9, 203.0.113.7"})
    assert _client_ip(request) == "203.0.113.7"


def test_invalid_proxy_values_fall_back_to_peer(monkeypatch):
    monkeypatch.setattr(settings, "trust_proxy_headers", True)
    request = _request(
        {"x-forwarded-for": "not-an-ip, also-bad", "x-real-ip": "still-bad"}
    )
    assert _client_ip(request) == "10.0.0.5"
