import pytest
from httpx import AsyncClient


async def _login(client: AsyncClient, username="admin", password=None):
    body: dict = {"username": username}
    if password is not None:
        body["password"] = password
    return await client.post("/sessions", json=body)


@pytest.fixture
async def passworded_admin():
    """Give the shared admin a known password for the duration of a test.

    The admin row lives in the shared per-run DB file, so the hash is
    cleared again afterwards to keep other tests on a passwordless admin.
    """
    from app.database import open_db
    from app.services.auth import hash_password

    async with open_db() as db:
        await db.execute(
            "UPDATE users SET password_hash = ? WHERE username = 'admin'",
            (hash_password("test-admin-password"),),
        )
        await db.commit()
    try:
        yield "test-admin-password"
    finally:
        async with open_db() as db:
            await db.execute("UPDATE users SET password_hash = NULL WHERE username = 'admin'")
            await db.commit()


async def test_login_without_password(client: AsyncClient):
    """The fresh private-mode admin has no password: empty password signs in."""
    body = (await _login(client)).json()
    assert body["status"] == 0, body
    assert body["payload"]["token"]
    assert body["payload"]["user"]["username"] == "admin"
    assert body["payload"]["user"]["has_password"] is False


async def test_login_passwordless_account_ignores_password(client: AsyncClient):
    """An account with no password set signs in with or without one."""
    body = (await _login(client, password="anything")).json()
    assert body["status"] == 0, body


async def test_login_accepts_set_password(client: AsyncClient, passworded_admin: str):
    """Once a password is set it works — and is reported via has_password."""
    body = (await _login(client, password=passworded_admin)).json()
    assert body["status"] == 0, body
    assert body["payload"]["user"]["has_password"] is True


async def test_login_rejects_wrong_password(client: AsyncClient, passworded_admin: str):
    body = (await _login(client, password="wrong")).json()
    assert body["status"] == 1
    assert body["message"] == "Invalid credentials"


async def test_login_unknown_user_is_invalid_credentials(client: AsyncClient):
    body = (await _login(client, username="nobody", password="x")).json()
    assert body["status"] == 1
    assert body["message"] == "Invalid credentials"


async def test_login_oauth_account_without_password_rejected(client: AsyncClient):
    """OAuth-linked accounts without a local password must use their provider."""
    from app.database import open_db

    async with open_db() as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (username, oauth_provider, oauth_id)"
            " VALUES ('oauthuser', 'github', '123')"
        )
        await db.commit()

    body = (await _login(client, username="oauthuser")).json()
    assert body["status"] == 1
    # Generic message: do not reveal that the account exists / is OAuth-only.
    assert body["message"] == "Invalid credentials"


async def test_login_rate_limited_after_repeated_failures(
    client: AsyncClient, passworded_admin: str
):
    for _ in range(5):
        body = (await _login(client, password="wrong")).json()
        assert body["message"] == "Invalid credentials"

    # Even the correct password is refused while the limiter is tripped.
    body = (await _login(client, password=passworded_admin)).json()
    assert body["status"] == 1
    assert "Too many failed login attempts" in body["message"]
    assert body["notify"] is True


async def test_successful_login_resets_failure_count(
    client: AsyncClient, passworded_admin: str
):
    for _ in range(4):
        await _login(client, password="wrong")
    assert (await _login(client, password=passworded_admin)).json()["status"] == 0

    # Failure budget is back to full: five more failures before the lockout.
    for _ in range(5):
        body = (await _login(client, password="wrong")).json()
        assert body["message"] == "Invalid credentials"
    assert "Too many failed login attempts" in (await _login(client, password=passworded_admin)).json()["message"]


async def test_login_missing_password_rejected_for_passworded_account(
    client: AsyncClient, passworded_admin: str
):
    resp = await client.post("/sessions", json={"username": "admin", "password": None})
    body = resp.json()
    assert body["status"] == 1
    assert body["message"] == "Username and password required"


async def test_public_mode_rejects_password_login(
    client: AsyncClient, passworded_admin: str, monkeypatch
):
    """Public mode is OAuth-only: password credentials are never accepted."""
    from app.config import settings

    monkeypatch.setattr(settings, "run_mode", "public")

    # Even the correct password for an existing account is refused.
    body = (await _login(client, password=passworded_admin)).json()
    assert body["status"] == 1
    assert "disabled in public mode" in body["message"]

    # A blank/passwordless attempt gets the same treatment.
    body = (await _login(client)).json()
    assert body["status"] == 1
    assert "disabled in public mode" in body["message"]


async def test_bootstrap_skips_when_users_exist(client: AsyncClient):
    """Startup never touches existing rows — no admin is added, none modified."""
    from app.database import open_db
    from app.main import _ensure_private_admin

    async with open_db() as db:
        cursor = await db.execute("SELECT COUNT(*) AS n, MAX(id) AS max_id FROM users")
        before = await cursor.fetchone()
        await _ensure_private_admin(db)
        cursor = await db.execute("SELECT COUNT(*) AS n, MAX(id) AS max_id FROM users")
        after = await cursor.fetchone()
        cursor = await db.execute("SELECT password_hash FROM users WHERE username = 'admin'")
        admin_hash = (await cursor.fetchone())["password_hash"]

    assert after["n"] == before["n"] >= 1
    assert after["max_id"] == before["max_id"]
    assert admin_hash is None
