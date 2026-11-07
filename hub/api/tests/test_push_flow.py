import asyncio
import json

from httpx import AsyncClient

from app.database import open_db

DEVICE = {
    "device_hash": "hash-base",
    "meta_hash": "meta-1",
    "device_meta": {
        "device_name": "/dev/sda",
        "serial_number": "SER123",
        "model_name": "Test Disk",
        "vendor": "TestVendor",
        "total_capacity_bytes": 500107862016,
        "device_type": "ata_ssd",
        "smart_status": 0,
    },
    "initial_metrics": {"TemperatureCelsius": 31},
}


def _device(node_id: int) -> dict:
    # Device hashes are scoped to the node that registered them, so tests
    # that create a fresh node must also use a fresh hash.
    return {**DEVICE, "device_hash": f"hash-{node_id}"}


def _hash(node_id: int) -> str:
    return f"hash-{node_id}"


async def _create_registered_node(client: AsyncClient, auth_headers) -> tuple[int, str]:
    resp = await client.put("/nodes", headers=auth_headers)
    body = resp.json()
    assert body["status"] == 0, body
    push_key = body["payload"]["push_key"]

    resp = await client.post(
        "/nodes",
        json={"push_key": push_key, "hostname": "test-host", "host_os": "linux"},
    )
    body = resp.json()
    assert body["status"] == 0, body
    return body["payload"]["node_id"], push_key


def _push_headers(push_key: str) -> dict:
    # Node push endpoints authenticate with the node's push key as Bearer.
    return {"Authorization": f"Bearer {push_key}"}


async def test_device_can_move_between_nodes(
    client, auth_headers, metrics_writes
):
    """Devices belong to the user, not to the node that first saw them.

    The same physical disk (stable device_hash) must be re-usable from a new
    node without deleting the old one or re-registering the device.
    """
    node_a, key_a = await _create_registered_node(client, auth_headers)
    node_b, key_b = await _create_registered_node(client, auth_headers)
    try:
        first = await client.post(
            f"/nodes/{node_a}/devices",
            json={"devices": [_device(node_a)]},
            headers=_push_headers(key_a),
        )
        first_body = first.json()
        assert first_body["status"] == 0, first_body
        device_id = first_body["payload"][0]["device_id"]

        second = await client.post(
            f"/nodes/{node_b}/devices",
            json={"devices": [_device(node_a)]},
            headers=_push_headers(key_b),
        )
        second_body = second.json()
        assert second_body["status"] == 0, second_body
        assert second_body["payload"][0]["device_id"] == device_id

        before = len(metrics_writes)
        metrics = await client.post(
            f"/nodes/{node_b}/metrics",
            json={
                "metrics": [
                    {"device_hash": _hash(node_a), "TemperatureCelsius": 44}
                ]
            },
            headers=_push_headers(key_b),
        )
        assert metrics.json()["status"] == 0, metrics.json()
        assert len(metrics_writes) > before, "node B could not push the moved device"

        # The node filter is a soft "last reported by" view, not ownership.
        resp = await client.get(
            f"/devices?node_id={node_b}", headers=auth_headers
        )
        items = resp.json()["payload"]["items"]
        assert [d["id"] for d in items].count(device_id) == 1
    finally:
        # Keep the per-user node limit available for the rest of the file.
        await client.delete(f"/nodes/{node_a}", headers=auth_headers)
        await client.delete(f"/nodes/{node_b}", headers=auth_headers)


async def test_deleting_a_node_keeps_its_devices(
    client, auth_headers, metrics_writes
):
    node_a, key_a = await _create_registered_node(client, auth_headers)
    node_b = None
    try:
        resp = await client.post(
            f"/nodes/{node_a}/devices",
            json={"devices": [_device(node_a)]},
            headers=_push_headers(key_a),
        )
        body = resp.json()
        assert body["status"] == 0, body
        device_id = body["payload"][0]["device_id"]

        resp = await client.delete(f"/nodes/{node_a}", headers=auth_headers)
        assert resp.json()["status"] == 0, resp.json()

        # The device survives its node.
        resp = await client.get(f"/devices/{device_id}", headers=auth_headers)
        assert resp.json()["status"] == 0, resp.json()

        # A new node re-uses the existing row instead of creating a duplicate.
        node_b, key_b = await _create_registered_node(client, auth_headers)
        resp = await client.post(
            f"/nodes/{node_b}/devices",
            json={"devices": [_device(node_a)]},
            headers=_push_headers(key_b),
        )
        body = resp.json()
        assert body["status"] == 0, body
        assert body["payload"][0]["device_id"] == device_id
    finally:
        await client.delete(f"/nodes/{node_a}", headers=auth_headers)
        if node_b is not None:
            await client.delete(f"/nodes/{node_b}", headers=auth_headers)


async def test_register_devices_then_push_metrics(client, auth_headers, metrics_writes):
    node_id, push_key = await _create_registered_node(client, auth_headers)
    push = _push_headers(push_key)

    resp = await client.post(
        f"/nodes/{node_id}/devices", json={"devices": [_device(node_id)]}, headers=push
    )
    body = resp.json()
    assert body["status"] == 0, body
    device_id = body["payload"][0]["device_id"]

    # Initial metrics reach VictoriaMetrics only after the registration committed.
    assert len(metrics_writes) == 1
    assert f"device_metric,device_id={device_id} " in metrics_writes[0]

    resp = await client.post(
        f"/nodes/{node_id}/metrics",
        json={"metrics": [{"device_hash": _hash(node_id), "TemperatureCelsius": 33}]},
        headers=push,
    )
    body = resp.json()
    assert body["status"] == 0, body
    assert len(metrics_writes) == 2
    assert "temperature_celsius=33" in metrics_writes[1]

    # The device is visible through the user-facing API.
    resp = await client.get("/devices", headers=auth_headers)
    items = resp.json()["payload"]["items"]
    matching = [d for d in items if d["device_hash"] == _hash(node_id)]
    assert len(matching) == 1
    assert matching[0]["id"] == device_id


async def test_clear_last_event_preserves_device_tags(client, auth_headers, metrics_writes):
    node_id, push_key = await _create_registered_node(client, auth_headers)
    push = _push_headers(push_key)

    resp = await client.post(
        f"/nodes/{node_id}/devices", json={"devices": [_device(node_id)]}, headers=push
    )
    device_id = resp.json()["payload"][0]["device_id"]

    resp = await client.patch(
        f"/devices/{device_id}", json={"tags": ["prod", "db"]}, headers=auth_headers
    )
    assert resp.json()["payload"]["tags"] == ["prod", "db"]

    # The UI acknowledges events with clear_last_event only; that must not
    # silently replace the tags with an empty list.
    resp = await client.patch(
        f"/devices/{device_id}", json={"clear_last_event": True}, headers=auth_headers
    )
    body = resp.json()
    assert body["status"] == 0, body
    assert body["payload"]["tags"] == ["prod", "db"]


async def test_empty_node_filter_returns_no_devices(client, auth_headers):
    node_id, _ = await _create_registered_node(client, auth_headers)

    resp = await client.get(
        f"/devices?node_id={node_id}", headers=auth_headers
    )
    body = resp.json()
    assert body["status"] == 0, body
    assert body["payload"]["items"] == []
    assert body["payload"]["total"] == 0


async def test_push_interval_enforced(client, auth_headers, metrics_writes):
    node_id, push_key = await _create_registered_node(client, auth_headers)
    push = _push_headers(push_key)

    resp = await client.post(
        f"/nodes/{node_id}/devices", json={"devices": [_device(node_id)]}, headers=push
    )
    assert resp.json()["status"] == 0

    resp = await client.post(
        f"/nodes/{node_id}/metrics",
        json={"metrics": [{"device_hash": _hash(node_id), "TemperatureCelsius": 33}]},
        headers=push,
    )
    assert resp.json()["status"] == 0

    resp = await client.post(
        f"/nodes/{node_id}/metrics",
        json={"metrics": [{"device_hash": _hash(node_id), "TemperatureCelsius": 34}]},
        headers=push,
    )
    body = resp.json()
    assert body["status"] == 1
    assert "not elapsed" in body["message"]
    assert len(metrics_writes) == 2  # no extra VictoriaMetrics write for the rejected push


async def test_metrics_for_unknown_device_are_ignored(client, auth_headers, metrics_writes):
    node_id, push_key = await _create_registered_node(client, auth_headers)

    resp = await client.post(
        f"/nodes/{node_id}/metrics",
        json={"metrics": [{"device_hash": "no-such-hash", "TemperatureCelsius": 1}]},
        headers=_push_headers(push_key),
    )
    body = resp.json()
    # A distinct non-fatal status tells the node to re-register its devices;
    # acknowledging silently would leave it pushing into the void forever.
    assert body["status"] == 2
    assert "re-register" in body["message"]
    assert metrics_writes == []

    # The interval must not be armed by a push that matched no device.
    node = (await client.get(f"/nodes/{node_id}", headers=auth_headers)).json()
    assert node["payload"]["last_metrics_push"] is None


async def test_node_push_key_is_required(client):
    resp = await client.post("/nodes", json={"push_key": "", "hostname": "h"})
    body = resp.json()
    assert body["status"] == 1
    assert "push_key required" in body["message"]


async def test_wrong_push_key_rejected(client, auth_headers):
    node_id, _ = await _create_registered_node(client, auth_headers)

    resp = await client.post(
        f"/nodes/{node_id}/devices",
        json={"devices": [_device(node_id)]},
        headers=_push_headers("not-a-real-key"),
    )
    assert resp.status_code == 401


async def test_concurrent_writers_do_not_interleave(client, auth_headers, metrics_writes):
    """Concurrent BEGIN IMMEDIATE across per-request connections must queue,
    not crash with 'cannot start a transaction within a transaction'."""
    nodes = [await _create_registered_node(client, auth_headers) for _ in range(4)]

    async def register(i: int):
        node_id, push_key = nodes[i]
        return await client.post(
            f"/nodes/{node_id}/devices",
            json={"devices": [_device(node_id)]},
            headers=_push_headers(push_key),
        )

    responses = await asyncio.gather(*(register(i) for i in range(4)))
    for i, resp in enumerate(responses):
        body = resp.json()
        assert body["status"] == 0, (i, body)

    resp = await client.get("/devices", headers=auth_headers)
    hashes = {d["device_hash"] for d in resp.json()["payload"]["items"]}
    assert {_hash(node_id) for node_id, _ in nodes}.issubset(hashes)


async def test_metrics_timestamp_override(client, auth_headers, metrics_writes):
    """A node-provided TimestampUTC stamps the VictoriaMetrics sample, so
    outbox replays keep their original collection time."""
    from datetime import datetime

    node_id, push_key = await _create_registered_node(client, auth_headers)
    push = _push_headers(push_key)

    resp = await client.post(
        f"/nodes/{node_id}/devices", json={"devices": [_device(node_id)]}, headers=push
    )
    assert resp.json()["status"] == 0

    stamp = "2026-01-15T10:30:00+00:00"
    expected_ts = int(datetime.fromisoformat(stamp).timestamp())

    resp = await client.post(
        f"/nodes/{node_id}/metrics",
        json={"metrics": [
            {"device_hash": _hash(node_id), "TemperatureCelsius": 33, "TimestampUTC": stamp},
            {"device_hash": _hash(node_id), "TemperatureCelsius": 34},
        ]},
        headers=push,
    )
    assert resp.json()["status"] == 0

    lines = metrics_writes[-1].strip().splitlines()
    assert len(lines) == 2
    assert lines[0].endswith(f" {expected_ts}")
    # Points without a TimestampUTC fall back to push time (recent epoch).
    assert int(lines[1].split()[-1]) > expected_ts
    # The override key itself never leaks into the stored fields.
    assert "TimestampUTC" not in metrics_writes[-1]


async def test_metrics_schema_version_enforced(client, auth_headers, metrics_writes):
    node_id, push_key = await _create_registered_node(client, auth_headers)
    push = _push_headers(push_key)

    resp = await client.post(
        f"/nodes/{node_id}/devices", json={"devices": [_device(node_id)]}, headers=push
    )
    assert resp.json()["status"] == 0

    resp = await client.post(
        f"/nodes/{node_id}/metrics",
        json={"schema_version": 99, "metrics": [{"device_hash": _hash(node_id), "TemperatureCelsius": 1}]},
        headers=push,
    )
    body = resp.json()
    assert body["status"] == 1
    assert "schema version" in body["message"]
    assert len(metrics_writes) == 1  # only the registration's initial metrics

    resp = await client.post(
        f"/nodes/{node_id}/metrics",
        json={"schema_version": 1, "metrics": [{"device_hash": _hash(node_id), "TemperatureCelsius": 35}]},
        headers=push,
    )
    assert resp.json()["status"] == 0
    assert len(metrics_writes) == 2


async def test_malformed_push_payloads_fail_validation(client, auth_headers, metrics_writes):
    """Push bodies are schema-validated: garbage input must fail with 422,
    never surface as a 500 from deep inside the services."""
    node_id, push_key = await _create_registered_node(client, auth_headers)
    push = _push_headers(push_key)

    resp = await client.post(
        f"/nodes/{node_id}/metrics", json={"metrics": ["not-an-object"]}, headers=push
    )
    assert resp.status_code == 422

    resp = await client.post(
        f"/nodes/{node_id}/devices",
        json={"devices": [{"device_hash": 5, "meta_hash": "m"}]},
        headers=push,
    )
    assert resp.status_code == 422

    resp = await client.post(
        f"/nodes/{node_id}/metas", json={"metas": [{"device_hash": ["x"]}]}, headers=push
    )
    assert resp.status_code == 422

    resp = await client.post("/nodes", json={"push_key": 123})
    assert resp.status_code == 422

    assert metrics_writes == []


async def test_non_numeric_metric_values_are_dropped(client, auth_headers, metrics_writes):
    """Metric values must be numeric; a string value must neither crash the
    write nor poison the VictoriaMetrics batch with a non-numeric field."""
    node_id, push_key = await _create_registered_node(client, auth_headers)
    push = _push_headers(push_key)

    resp = await client.post(
        f"/nodes/{node_id}/devices", json={"devices": [_device(node_id)]}, headers=push
    )
    assert resp.json()["status"] == 0

    resp = await client.post(
        f"/nodes/{node_id}/metrics",
        json={"metrics": [{
            "device_hash": _hash(node_id),
            "TemperatureCelsius": 40,
            "TotalBytesWritten": "not-a-number\ninjected=1",
        }]},
        headers=push,
    )
    assert resp.json()["status"] == 0

    line = metrics_writes[-1].strip()
    assert "temperature_celsius=40" in line
    assert "total_bytes_written" not in line
    assert "injected" not in line


async def test_metrics_not_acknowledged_when_metrics_write_fails(
    client, auth_headers, metrics_writes, monkeypatch
):
    from app.routes import push as push_routes

    node_id, push_key = await _create_registered_node(client, auth_headers)
    push = _push_headers(push_key)
    await client.post(
        f"/nodes/{node_id}/devices", json={"devices": [_device(node_id)]}, headers=push
    )

    async def fail(_payload: str) -> bool:
        return False

    monkeypatch.setattr(push_routes, "write_metrics", fail)
    payload = {"metrics": [{"device_hash": _hash(node_id), "TemperatureCelsius": 33}]}
    resp = await client.post(f"/nodes/{node_id}/metrics", json=payload, headers=push)
    body = resp.json()
    assert body["status"] == 1
    assert "unavailable" in body["message"]

    config = (await client.get(f"/nodes/{node_id}/configs", headers=push)).json()["payload"]
    assert config["last_metrics_push"] is None

    async def succeed(_payload: str) -> bool:
        return True

    monkeypatch.setattr(push_routes, "write_metrics", succeed)
    retry = await client.post(f"/nodes/{node_id}/metrics", json=payload, headers=push)
    assert retry.json()["status"] == 0


async def test_replay_points_are_limited_by_devices_not_points(
    client, auth_headers, metrics_writes
):
    node_id, push_key = await _create_registered_node(client, auth_headers)
    push = _push_headers(push_key)
    await client.post(
        f"/nodes/{node_id}/devices", json={"devices": [_device(node_id)]}, headers=push
    )

    points = [
        {"device_hash": _hash(node_id), "TemperatureCelsius": 30 + (i % 10)}
        for i in range(100)
    ]
    resp = await client.post(
        f"/nodes/{node_id}/metrics", json={"metrics": points}, headers=push
    )
    body = resp.json()
    assert body["status"] == 0, body
    assert len(metrics_writes[-1].strip().splitlines()) == 100


async def test_event_batch_limit_counts_unique_devices(client, auth_headers):
    node_id, push_key = await _create_registered_node(client, auth_headers)
    push = _push_headers(push_key)
    await client.post(
        f"/nodes/{node_id}/devices", json={"devices": [_device(node_id)]}, headers=push
    )

    events = [
        {
            "event_type": "device_smart_fail",
            "device_hash": _hash(node_id),
            "summary": f"event {i}",
        }
        for i in range(100)
    ]
    resp = await client.post(
        f"/nodes/{node_id}/events",
        files={"events": (None, json.dumps(events))},
        headers=push,
    )
    body = resp.json()
    assert body["status"] == 0, body

    listed = (await client.get("/events?plimit=200", headers=auth_headers)).json()
    assert listed["status"] == 0
    assert listed["payload"]["total"] == 100


async def test_push_raws_stores_snapshot_and_respects_schedule(
    client, auth_headers, metrics_writes
):
    """Regression: /raws used to raise NameError (HTTP 500) on every push."""
    node_id, push_key = await _create_registered_node(client, auth_headers)
    push = _push_headers(push_key)

    registered = (
        await client.post(
            f"/nodes/{node_id}/devices",
            json={"devices": [_device(node_id)]},
            headers=push,
        )
    ).json()
    assert registered["status"] == 0, registered
    device_id = registered["payload"][0]["device_id"]

    payload = {
        "meta": json.dumps(
            {
                "devices": [
                    {
                        "device_id": device_id,
                        "collected_at": "2020-01-02T03:04:05+00:00",
                    }
                ]
            }
        )
    }
    files = {str(device_id): ("raw.brotli", b"raw-snapshot", "application/octet-stream")}

    resp = await client.post(
        f"/nodes/{node_id}/raws", data=payload, files=files, headers=push
    )
    body = resp.json()
    assert body["status"] == 0, body

    # Add a newer row in SQLite's default (space) format: ordering and the
    # end-date filter must compare instants, not the literal first character.
    async with open_db() as db:
        await db.execute(
            "INSERT INTO device_raw (device_id, raw_output, add_at) VALUES (?, ?, ?)",
            (device_id, b"newer", "2020-01-02 23:00:00"),
        )
        await db.commit()

    listed = (
        await client.get(
            f"/devices/{device_id}/raws",
            params={"start": "2020-01-02", "end": "2020-01-02"},
            headers=auth_headers,
        )
    ).json()
    assert listed["status"] == 0, listed
    rows = listed["payload"]
    assert len(rows) == 2, rows
    assert rows[0]["add_at"] == "2020-01-02 23:00:00"
    assert rows[1]["add_at"] == "2020-01-02T03:04:05+00:00"

    # The detail endpoint decompresses off the event loop and still answers.
    detail = (
        await client.get(
            f"/devices/{device_id}/raws/{rows[1]['id']}", headers=auth_headers
        )
    ).json()
    assert detail["status"] == 0, detail

    # The raw interval is consumed: the next push is a scheduling rejection,
    # not a 500 and not a duplicate insert.
    resp = await client.post(
        f"/nodes/{node_id}/raws", data=payload, files=files, headers=push
    )
    body = resp.json()
    assert body["status"] == 1, body
    assert "not required" in body["message"]
