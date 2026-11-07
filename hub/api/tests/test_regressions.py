"""Regression tests for the review findings fixed in this change set."""

import asyncio
import base64
import json
import uuid

from pydantic import ValidationError
import pytest

from app.config import Settings
from app.database import open_db
from app.services.vendor_guess import guess_vendor


def _push_headers(push_key: str) -> dict:
    return {"Authorization": f"Bearer {push_key}"}


@pytest.fixture(autouse=True)
async def _raise_node_limit():
    """These tests create several nodes; the shared admin default is 20."""
    from app.database import init_sqlite

    await init_sqlite()
    async with open_db() as db:
        await db.execute("UPDATE users SET node_limit = 1000 WHERE id = 1")
        await db.commit()
    yield
    async with open_db() as db:
        await db.execute("UPDATE users SET node_limit = NULL WHERE id = 1")
        await db.commit()


async def _create_node(client, auth_headers):
    body = (await client.put("/nodes", headers=auth_headers)).json()
    assert body["status"] == 0, body
    push_key = body["payload"]["push_key"]
    registered = (
        await client.post(
            "/nodes",
            json={"push_key": push_key, "hostname": "host-a", "host_os": "linux"},
        )
    ).json()
    assert registered["status"] == 0, registered
    return registered["payload"]["node_id"], push_key


async def _create_device(client, auth_headers, node_id, push_key, device_hash=None):
    device_hash = device_hash or f"dev-{uuid.uuid4().hex}"
    body = (
        await client.post(
            f"/nodes/{node_id}/devices",
            json={
                "devices": [
                    {
                        "device_hash": device_hash,
                        "meta_hash": "meta-1",
                        "device_meta": {
                            "device_name": "/dev/sda",
                            "serial_number": "SER-1",
                            "model_name": "Test Disk",
                            "device_type": "ata_ssd",
                            "total_capacity_bytes": 1000,
                            "smart_status": 0,
                        },
                    }
                ]
            },
            headers=_push_headers(push_key),
        )
    ).json()
    assert body["status"] == 0, body
    return body["payload"][0]["device_id"]


async def test_reregistering_a_registered_push_key_is_idempotent(client, auth_headers):
    node_id, push_key = await _create_node(client, auth_headers)

    second = (
        await client.post(
            "/nodes",
            json={"push_key": push_key, "hostname": "renamed-host", "host_os": "bsd"},
        )
    ).json()
    assert second["status"] == 0, second
    assert second["payload"]["node_id"] == node_id

    node = (await client.get(f"/nodes/{node_id}", headers=auth_headers)).json()
    assert node["payload"]["hostname"] == "renamed-host"
    assert node["payload"]["host_os"] == "bsd"


async def test_unknown_push_key_still_rejected(client):
    body = (await client.post("/nodes", json={"push_key": "does-not-exist"})).json()
    assert body["status"] == 101


async def test_corrupted_password_hash_is_invalid_credentials(client):
    from app.services.auth import verify_password

    assert verify_password("not-a-hash", "pw") is False

    async with open_db() as db:
        await db.execute(
            "UPDATE users SET password_hash = 'not-a-hash' WHERE username = 'admin'"
        )
        await db.commit()
    try:
        body = (
            await client.post("/sessions", json={"username": "admin", "password": "pw"})
        ).json()
        assert body["status"] == 1
        assert body["message"] == "Invalid credentials"
    finally:
        async with open_db() as db:
            await db.execute(
                "UPDATE users SET password_hash = NULL WHERE username = 'admin'"
            )
            await db.commit()


def test_retention_validator_enforces_victoriametrics_minimum():
    with pytest.raises(ValidationError):
        Settings(victoriametrics_retention="1h")
    with pytest.raises(ValidationError):
        Settings(victoriametrics_retention="23h")
    assert Settings(victoriametrics_retention="24h").victoriametrics_retention == "24h"
    assert Settings(victoriametrics_retention="1d").victoriametrics_retention == "1d"


def test_vendor_guess_accepts_json_string_device_ext():
    base = {"model_name": "PM9A1", "device_type": "nvme"}
    as_dict = {**base, "device_ext": {"pci_vendor_id": "0x144D"}}
    as_string = {**base, "device_ext": '{"pci_vendor_id":"0x144D"}'}
    assert guess_vendor(as_dict) == "Samsung"
    assert guess_vendor(as_string) == "Samsung"


async def test_tag_length_is_bounded_per_item(client, auth_headers):
    node_id, _ = await _create_node(client, auth_headers)
    response = await client.patch(
        f"/nodes/{node_id}",
        json={"tags": ["x" * 51]},
        headers=auth_headers,
    )
    assert response.status_code == 422


async def test_event_and_raw_timestamps_are_preserved(client, auth_headers):
    node_id, push_key = await _create_node(client, auth_headers)
    device_id = await _create_device(client, auth_headers, node_id, push_key)
    collected_at = "2020-01-02T03:04:05+00:00"

    events = [
        {
            "device_id": device_id,
            "event_type": "device_smart_fail",
            "summary": "failed",
            "collected_at": collected_at,
        },
        {
            "device_id": device_id,
            "event_type": "device_threshold_critical",
            "summary": "critical",
            "collected_at": collected_at,
        },
    ]
    resp = await client.post(
        f"/nodes/{node_id}/events",
        data={
            "events": json.dumps(events),
            "meta": json.dumps(
                {"devices": [{"device_id": device_id, "collected_at": collected_at}]}
            ),
        },
        files={"%d" % device_id: ("raw.brotli", b"raw-bytes", "application/octet-stream")},
        headers=_push_headers(push_key),
    )
    assert resp.json()["status"] == 0, resp.json()

    async with open_db() as db:
        cursor = await db.execute(
            "SELECT add_at FROM events WHERE device_id = ? ORDER BY id", (device_id,)
        )
        event_times = [row["add_at"] for row in await cursor.fetchall()]
        cursor = await db.execute(
            "SELECT add_at FROM device_raw WHERE device_id = ?", (device_id,)
        )
        raw_times = [row["add_at"] for row in await cursor.fetchall()]

    assert len(event_times) == 2
    assert all(t.startswith("2020-01-02T03:04:05") for t in event_times)
    # Two events for the same disk in one payload must store its raw once.
    assert len(raw_times) == 1
    assert raw_times[0].startswith("2020-01-02T03:04:05")


async def test_recovery_event_does_not_mark_device_critical(client, auth_headers):
    node_id, push_key = await _create_node(client, auth_headers)
    device_id = await _create_device(client, auth_headers, node_id, push_key)

    resp = await client.post(
        f"/nodes/{node_id}/events",
        data={"events": json.dumps([
            {"device_id": device_id, "event_type": "device_smart_success", "summary": "ok"}
        ])},
        files={"dummy": ("dummy", b"")},
        headers=_push_headers(push_key),
    )
    assert resp.json()["status"] == 0, resp.json()

    device = (await client.get(f"/devices/{device_id}", headers=auth_headers)).json()
    # A recovery event must not leave the unacknowledged "critical" marker.
    assert device["payload"]["last_event_at"] is None

    resp = await client.post(
        f"/nodes/{node_id}/events",
        data={"events": json.dumps([
            {"device_id": device_id, "event_type": "device_smart_fail", "summary": "failed"}
        ])},
        files={"dummy": ("dummy", b"")},
        headers=_push_headers(push_key),
    )
    assert resp.json()["status"] == 0, resp.json()
    device = (await client.get(f"/devices/{device_id}", headers=auth_headers)).json()
    assert device["payload"]["last_event_at"] is not None


async def test_archived_devices_remain_editable_and_stay_archived(client, auth_headers):
    node_id, push_key = await _create_node(client, auth_headers)
    device_id = await _create_device(
        client, auth_headers, node_id, push_key, device_hash="reg-hash-archived"
    )

    assert (
        await client.delete(f"/devices/{device_id}", headers=auth_headers)
    ).json()["status"] == 0

    # Tag edits work while archived.
    body = (
        await client.patch(
            f"/devices/{device_id}", json={"tags": ["cold-storage"]}, headers=auth_headers
        )
    ).json()
    assert body["status"] == 0, body
    assert body["payload"]["tags"] == ["cold-storage"]

    # A node re-registering the same hash must not undo the archive decision.
    again = (
        await client.post(
            f"/nodes/{node_id}/devices",
            json={"devices": [{"device_hash": "reg-hash-archived", "meta_hash": "meta-2"}]},
            headers=_push_headers(push_key),
        )
    ).json()
    assert again["status"] == 0, again
    device = (await client.get(f"/devices/{device_id}", headers=auth_headers)).json()
    assert device["payload"]["archived"] is True


async def test_events_push_is_bounded_before_validation(client, auth_headers):
    node_id, push_key = await _create_node(client, auth_headers)
    events = json.dumps([{}] * 501)
    resp = await client.post(
        f"/nodes/{node_id}/events",
        data={"events": events},
        files={"dummy": ("dummy", b"")},
        headers=_push_headers(push_key),
    )
    body = resp.json()
    assert body["status"] == 201
    assert "Too many events" in body["message"]


async def test_per_ip_login_limit_blocks_username_rotation(client):
    for i in range(30):
        body = (
            await client.post(
                "/sessions", json={"username": f"nobody-{i}", "password": "x"}
            )
        ).json()
        assert body["status"] == 1, body

    body = (await client.post("/sessions", json={"username": "admin"})).json()
    assert "Too many failed login attempts" in body["message"]


async def test_concurrent_metrics_pushes_are_serialized(
    client, auth_headers, metrics_writes
):
    node_id, push_key = await _create_node(client, auth_headers)
    device_hash = f"concurrent-{uuid.uuid4().hex}"
    await _create_device(
        client, auth_headers, node_id, push_key, device_hash=device_hash
    )
    payload = {
        "metrics": [{"device_hash": device_hash, "TemperatureCelsius": 30}]
    }

    async def push():
        return (
            await client.post(
                f"/nodes/{node_id}/metrics",
                json=payload,
                headers=_push_headers(push_key),
            )
        ).json()

    first, second = await asyncio.gather(push(), push())
    statuses = sorted([first["status"], second["status"]])
    # Exactly one request may consume the interval; the other is rejected,
    # never both accepting (which used to double-write and double-advance).
    assert statuses == [0, 1], (first, second)
    assert "not elapsed" in (first["message"] + second["message"])


async def test_metric_export_range_is_capped(client, auth_headers):
    node_id, push_key = await _create_node(client, auth_headers)
    device_id = await _create_device(client, auth_headers, node_id, push_key)

    resp = await client.get(
        f"/devices/{device_id}/metrics",
        params={
            "start": "2000-01-01T00:00:00Z",
            "end": "2030-01-01T00:00:00Z",
            "metric": "TemperatureCelsius",
        },
        headers=auth_headers,
    )
    body = resp.json()
    assert body["status"] == 1
    assert "maximum" in body["message"]


async def test_registration_does_not_store_raw_snapshots(client, auth_headers):
    """Registration is metadata/metrics only; raws belong to the raw push."""
    node_id, push_key = await _create_node(client, auth_headers)
    device_hash = f"reg-raw-{uuid.uuid4().hex}"
    body = (
        await client.post(
            f"/nodes/{node_id}/devices",
            json={
                "devices": [
                    {
                        "device_hash": device_hash,
                        "meta_hash": "meta-1",
                        "device_meta": {
                            "device_name": "/dev/sda",
                            "serial_number": "SER-1",
                            "model_name": "Test Disk",
                            "device_type": "ata_ssd",
                            "total_capacity_bytes": 1000,
                            "smart_status": 0,
                        },
                        # Older beta nodes sent this field; it must be ignored
                        # rather than stored as a second snapshot.
                        "raw_brotli": base64.b64encode(
                            b"legacy-registration-raw"
                        ).decode(),
                    }
                ]
            },
            headers=_push_headers(push_key),
        )
    ).json()
    assert body["status"] == 0, body
    device_id = body["payload"][0]["device_id"]

    async with open_db() as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM device_raw WHERE device_id = ?", (device_id,)
        )
        count = (await cursor.fetchone())[0]
    assert count == 0


async def test_event_listing_orders_mixed_timestamp_formats(client, auth_headers):
    """ISO and SQLite-default rows must sort by instant, not by string."""
    async with open_db() as db:
        for add_at in ("2031-01-02T10:00:00+00:00", "2031-01-02 11:00:00"):
            await db.execute(
                "INSERT INTO events (user_id, event_type, add_at) "
                "VALUES (1, 'device_smart_fail', ?)",
                (add_at,),
            )
        await db.commit()

    body = (
        await client.get("/events", params={"plimit": 200}, headers=auth_headers)
    ).json()
    assert body["status"] == 0, body
    times = [item["add_at"] for item in body["payload"]["items"]]
    # Lexicographic order (old behavior) put the ISO row first because "T"
    # sorts after " ", even though 10:00 is earlier than 11:00.
    assert times.index("2031-01-02 11:00:00") < times.index(
        "2031-01-02T10:00:00+00:00"
    )
