import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from app.routes.oauth import (
    OAUTH_STATE_COOKIE,
    _parse_origin,
    _sign_state,
    _state_matches_cookie,
    _validate_redirect_uri,
    _verify_state,
)


class RedirectOriginTests(unittest.TestCase):
    def test_redirect_uri_matches_origin_without_prefix_bypass(self) -> None:
        allowed = _parse_origin("https://dashboard.example")
        if allowed is None:
            self.fail("expected a valid origin")

        with patch("app.routes.oauth.ALLOWED_REDIRECT_ORIGINS", {allowed}):
            self.assertTrue(_validate_redirect_uri("https://dashboard.example/oauth/callback"))
            self.assertFalse(_validate_redirect_uri("https://dashboard.example.evil/oauth/callback"))


async def test_oauth_login_binds_state_to_browser_cookie(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "run_mode", "public")
    allowed = _parse_origin("http://testserver")
    assert allowed is not None

    with patch("app.routes.oauth.ALLOWED_REDIRECT_ORIGINS", {allowed}):
        response = await client.get(
            "/oauth/providers/github/login",
            params={"redirect_uri": "http://testserver/oauth/callback/github"},
            follow_redirects=False,
        )

    assert response.status_code == 307
    cookie_nonce = response.cookies.get(OAUTH_STATE_COOKIE)
    assert cookie_nonce
    state = parse_qs(urlsplit(response.headers["location"]).query)["state"][0]
    state_data = _verify_state(state, "github")
    assert state_data is not None
    assert _state_matches_cookie(state_data, cookie_nonce)
    assert "HttpOnly" in response.headers["set-cookie"]


async def test_oauth_login_rejected_in_private_mode(client):
    allowed = _parse_origin("http://testserver")
    assert allowed is not None

    with patch("app.routes.oauth.ALLOWED_REDIRECT_ORIGINS", {allowed}):
        response = await client.get(
            "/oauth/providers/github/login",
            params={"redirect_uri": "http://testserver/oauth/callback/github"},
            follow_redirects=False,
        )

    body = response.json()
    assert body["status"] == 1
    assert "private mode" in body["message"]


async def test_oauth_callback_rejects_state_from_another_browser(client):
    allowed = _parse_origin("http://testserver")
    assert allowed is not None

    state = _sign_state(
        "github",
        "http://testserver/oauth/callback/github",
        "another-browser-nonce",
    )
    with patch("app.routes.oauth.ALLOWED_REDIRECT_ORIGINS", {allowed}):
        response = await client.get(
            "/oauth/providers/github/callback",
            params={
                "code": "oauth-code",
                "state": state,
                "redirect_uri": "http://testserver/oauth/callback/github",
            },
        )

    body = response.json()
    assert body["status"] == 1
    assert "OAuth session" in body["message"]


if __name__ == "__main__":
    unittest.main()
