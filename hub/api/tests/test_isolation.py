"""Cross-user isolation tests.

For a multi-user hub the most valuable security property is that neither
another user's session nor a rogue node payload can touch another user's
data. These tests exercise exactly that: user-vs-user reads and the
node-event path that historically accepted arbitrary device ids.
"""

import pytest
from httpx import AsyncClient

from app.database import open_db
from app.services.auth import hash_password

USER_B_PASSWORD = "user-b-password-2"

DEVICE_A = {
    "device_hash": "hash-a",
    "meta_hash": "meta-a",
    "device_meta": {
        "device_name": "/dev/sda",
        "serial_number": "SER-A",
        "model_name": "Disk A",
        "vendor": "VendorA",
        "total_capacity_bytes": 500107862016,
        "device_type": "ata_ssd",
        "smart_status": 0,
    },
}

DEVICE_B = {
    "device_hash": "hash-b",
    "meta_hash": "meta-b",
    "device_meta": {
        "device_name": "/dev/sdb",
        "serial_number": "SER-B",
        "model_name": "Disk B",
        "vendor": "VendorB",
        "total_capacity_bytes": 500107862016,
        "device_type": "ata_ssd",
        "smart_status": 0,
    },
}


async def _login(client: AsyncClient, username: str, password: str) -> dict:
    resp = await client.post("/sessions", json={"username": username, "password": password})
    body = resp.json()
    assert body["status"] == 0, body
    return {"Authorization": f"Bearer {body['payload']['token']}"}


async def _create_node_with_device(client: AsyncClient, headers: dict, device: dict) -> tuple[int, str, int]:
    """Returns (node_id, push_key, device_id) for the given user."""
    resp = await client.put("/nodes", headers=headers)
    body = resp.json()
    assert body["status"] == 0, body
    node_id, push_key = body["payload"]["id"], body["payload"]["push_key"]

    resp = await client.post(
        "/nodes", json={"push_key": push_key, "hostname": "h", "host_os": "linux"}
    )
    assert resp.json()["status"] == 0, resp.json()

    resp = await client.post(
        f"/nodes/{node_id}/devices", json={"devices": [device]},
        headers={"Authorization": f"Bearer {push_key}"},
    )
    body = resp.json()
    assert body["status"] == 0, body
    return node_id, push_key, body["payload"][0]["device_id"]


@pytest.fixture
async def two_users(client):
    async with open_db() as db:
        # OR IGNORE: the SQLite file is shared by all tests in a run, so a
        # second test using this fixture must not collide on the username.
        await db.execute(
            "INSERT OR IGNORE INTO users (username, password_hash) VALUES (?, ?)",
            ("userb", hash_password(USER_B_PASSWORD)),
        )
        await db.commit()

    headers_a = {"Authorization": f"Bearer {(await client.post('/sessions', json={'username': 'admin'})).json()['payload']['token']}"}
    headers_b = await _login(client, "userb", USER_B_PASSWORD)
    try:
        yield headers_a, headers_b
    finally:
        # Later test files assert exact device lists for the admin user, so
        # remove everything these tests created.
        async with open_db() as db:
            await db.execute(
                "DELETE FROM events WHERE user_id = (SELECT id FROM users WHERE username = 'userb') "
                "OR device_id IN (SELECT id FROM device WHERE device_hash IN ('hash-a', 'hash-b'))"
            )
            await db.execute("DELETE FROM device WHERE device_hash IN ('hash-a', 'hash-b')")
            await db.execute(
                "DELETE FROM node WHERE user_id = (SELECT id FROM users WHERE username = 'userb')"
            )
            await db.commit()


async def test_user_cannot_read_another_users_node_or_device(client, two_users):
    headers_a, headers_b = two_users
    node_a, _, device_a = await _create_node_with_device(client, headers_a, DEVICE_A)

    resp = await client.get(f"/nodes/{node_a}", headers=headers_b)
    body = resp.json()
    assert body["status"] != 0, body

    resp = await client.get(f"/devices/{device_a}", headers=headers_b)
    body = resp.json()
    assert body["status"] != 0, body

    resp = await client.get(f"/devices/{device_a}/raws", headers=headers_b)
    body = resp.json()
    assert body["status"] != 0, body

    # The device never appears in B's list either.
    resp = await client.get("/devices", headers=headers_b)
    hashes = [d["device_hash"] for d in resp.json()["payload"]["items"]]
    assert "hash-a" not in hashes


async def test_node_event_cannot_touch_another_users_device(client, two_users):
    """The historic authz gap: a node pushing an event with someone else's
    device_id must not stamp last_event_at, update statuses, or leak the
    device name into the event list."""
    headers_a, headers_b = two_users
    _, _, device_a = await _create_node_with_device(client, headers_a, DEVICE_A)
    _, push_key_b, _ = await _create_node_with_device(client, headers_b, DEVICE_B)
    node_b = await _node_id_of(client, headers_b)

    # Push an event from B's node that references A's device id.
    resp = await client.post(
        f"/nodes/{node_b}/events",
        files={"events": (None, f'[{{"event_type": "device_threshold_warning", "device_id": {device_a}, "summary": "rogue"}}]')},
        headers={"Authorization": f"Bearer {push_key_b}"},
    )
    body = resp.json()
    assert body["status"] == 0, body

    # A's device is untouched.
    resp = await client.get(f"/devices/{device_a}", headers=headers_a)
    dev = resp.json()["payload"]
    assert dev["last_event_at"] is None, dev
    assert dev["threshold_status"] == 0, dev

    # A's event list does not contain the rogue event.
    resp = await client.get("/events", headers=headers_a)
    assert resp.json()["payload"]["total"] == 0, resp.json()

    # B's event was recorded, but with no device association.
    resp = await client.get("/events", headers=headers_b)
    items = resp.json()["payload"]["items"]
    assert len(items) == 1, items
    assert items[0]["device_id"] is None, items
    assert items[0]["device_name"] is None, items


async def _node_id_of(client: AsyncClient, headers: dict) -> int:
    resp = await client.get("/nodes", headers=headers)
    return resp.json()["payload"]["items"][0]["id"]
