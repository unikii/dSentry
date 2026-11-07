"""Logout, session revocation, and password-change re-authentication."""

import pytest
from httpx import AsyncClient


async def _login(client: AsyncClient):
    resp = await client.post("/sessions", json={"username": "admin"})
    body = resp.json()
    assert body["status"] == 0, body
    return body["payload"]["token"]


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_logout_revokes_session(client: AsyncClient):
    token = await _login(client)

    resp = await client.delete("/sessions", headers=_headers(token))
    assert resp.json()["status"] == 0, resp.json()

    # The revoked token no longer authenticates anything.
    resp = await client.get("/users/1", headers=_headers(token))
    assert resp.status_code == 401

    # A fresh login works.
    token2 = await _login(client)
    resp = await client.get("/users/1", headers=_headers(token2))
    assert resp.json()["status"] == 0


async def test_revoked_session_cannot_logout_again(client: AsyncClient):
    token = await _login(client)
    assert (await client.delete("/sessions", headers=_headers(token))).json()["status"] == 0
    resp = await client.delete("/sessions", headers=_headers(token))
    assert resp.status_code == 401


async def test_password_change_requires_current_password(client: AsyncClient):
    token = await _login(client)

    # Setting a first password needs no current password.
    body = (
        await client.patch("/users/1", json={"password": "initial-pw"}, headers=_headers(token))
    ).json()
    assert body["status"] == 0, body

    body = (
        await client.patch("/users/1", json={"password": "totally-new"}, headers=_headers(token))
    ).json()
    assert body["status"] == 1
    assert "Current password required" in body["message"]

    body = (
        await client.patch(
            "/users/1",
            json={"password": "totally-new", "current_password": "wrong"},
            headers=_headers(token),
        )
    ).json()
    assert body["status"] == 1
    assert "incorrect" in body["message"]

    # The just-set password still works — nothing was changed.
    body = (await client.post("/sessions", json={"username": "admin", "password": "initial-pw"})).json()
    assert body["status"] == 0


async def test_password_change_revokes_other_sessions(client: AsyncClient):
    token_old = await _login(client)
    token_new = await _login(client)  # the session that changes the password

    body = (
        await client.patch(
            "/users/1",
            json={"password": "brand-new-pw"},
            headers=_headers(token_new),
        )
    ).json()
    assert body["status"] == 0, body

    # Every other session is dead.
    resp = await client.get("/users/1", headers=_headers(token_old))
    assert resp.status_code == 401
    # ...but the one that performed the change survives.
    resp = await client.get("/users/1", headers=_headers(token_new))
    assert resp.json()["status"] == 0


async def test_public_mode_rejects_password_changes(client: AsyncClient, monkeypatch):
    """Public mode is OAuth-only, so local passwords cannot be set or changed."""
    from app.config import settings

    token = await _login(client)
    monkeypatch.setattr(settings, "run_mode", "public")

    body = (
        await client.patch(
            "/users/1",
            json={"password": "not-allowed"},
            headers=_headers(token),
        )
    ).json()
    assert body["status"] == 1
    assert "disabled in public mode" in body["message"]


@pytest.fixture(autouse=True)
async def _restore_passwordless_admin(client):
    """Password tests must not leak a hash into other tests (the admin row
    lives in the shared per-run DB file)."""
    yield
    from app.database import open_db

    async with open_db() as db:
        await db.execute("UPDATE users SET password_hash = NULL WHERE id = 1")
        await db.commit()
