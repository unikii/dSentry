"""Username normalization: lowercase + whitespace -> underscore."""

import pytest
from httpx import AsyncClient

from app.database import open_db
from app.utils import normalize_username


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("admin", "admin"),
        ("ADMIN", "admin"),
        ("Alice L", "alice_l"),
        ("  Alice  ", "alice"),
        ("a  b\tc\nd", "a_b_c_d"),
        ("already_snake", "already_snake"),
        ("git-hub.user", "git-hub.user"),
        ("Alice   L", "alice_l"),
    ],
)
def test_normalize_username_cases(raw: str, expected: str) -> None:
    assert normalize_username(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "\t\n ", None])
def test_normalize_username_rejects_blank(raw) -> None:
    with pytest.raises(ValueError):
        normalize_username(raw)


async def test_login_honors_exact_input(client: AsyncClient):
    # Only the canonical stored form signs in; variants are rejected.
    for variant in ("ADMIN", " Admin ", "AdMiN"):
        body = (await client.post("/sessions", json={"username": variant})).json()
        assert body["status"] == 1, (variant, body)
    body = (await client.post("/sessions", json={"username": "admin"})).json()
    assert body["status"] == 0, body
    assert body["payload"]["user"]["username"] == "admin"


async def test_rename_normalizes_and_restores(client: AsyncClient, auth_headers: dict):
    me = (
        await client.post("/sessions", json={"username": "admin"})
    ).json()["payload"]["user"]
    try:
        updated = (
            await client.patch(
                f"/users/{me['id']}", json={"username": "New Name"}, headers=auth_headers
            )
        ).json()
        assert updated["status"] == 0, updated
        assert updated["payload"]["username"] == "new_name"

        body = (await client.post("/sessions", json={"username": "new_name"})).json()
        assert body["status"] == 0, body

        # Raw variants do not match the canonical stored name.
        mismatch = (await client.post("/sessions", json={"username": "NEW NAME"})).json()
        assert mismatch["status"] == 1

        blank = (
            await client.patch(
                f"/users/{me['id']}", json={"username": "   "}, headers=auth_headers
            )
        ).json()
        assert blank["status"] == 1
    finally:
        restored = (
            await client.patch(
                f"/users/{me['id']}", json={"username": "admin"}, headers=auth_headers
            )
        ).json()
        assert restored["status"] == 0, restored
        assert restored["payload"]["username"] == "admin"


async def test_cli_create_normalizes(client: AsyncClient):
    import argparse

    import manage_users

    args = argparse.Namespace(username="Mixed Case", password="secret123", no_password=False)
    assert manage_users.cmd_create(args) == 0
    try:
        async with open_db() as db:
            cur = await db.execute(
                "SELECT username FROM users WHERE username = 'mixed_case'"
            )
            assert await cur.fetchone() is not None
    finally:
        async with open_db() as db:
            await db.execute("DELETE FROM users WHERE username = 'mixed_case'")
            await db.commit()
