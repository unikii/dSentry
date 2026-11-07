"""Device metrics queries against VictoriaMetrics."""

import pytest

from app.config import settings
from app.metrics import MetricsQueryError
from app.services import metrics_store as device_service


def _device_payload(name: str) -> dict:
    return {
        "device_hash": f"metrics-{name}",
        "meta_hash": "meta-1",
        "device_meta": {
            "device_name": "/dev/sda",
            "serial_number": f"SER-{name}",
            "model_name": "Test Disk",
            "vendor": "TestVendor",
            "total_capacity_bytes": 500107862016,
            "device_type": "ata_ssd",
            "smart_status": 0,
        },
        "initial_metrics": {"TemperatureCelsius": 31},
    }


@pytest.fixture
async def device_id(client, auth_headers, metrics_writes, request):
    resp = await client.put("/nodes", headers=auth_headers)
    push_key = resp.json()["payload"]["push_key"]

    resp = await client.post(
        "/nodes",
        json={"push_key": push_key, "hostname": "metrics-host", "host_os": "linux"},
    )
    node_id = resp.json()["payload"]["node_id"]

    resp = await client.post(
        f"/nodes/{node_id}/devices",
        json={"devices": [_device_payload(request.node.name)]},
        headers={"Authorization": f"Bearer {push_key}"},
    )
    body = resp.json()
    assert body["status"] == 0, body
    try:
        yield body["payload"][0]["device_id"]
    finally:
        await client.delete(f"/nodes/{node_id}", headers=auth_headers)


@pytest.fixture
def fake_metrics(monkeypatch):
    state: dict = {
        "calls": [],
        "error": None,
        "range": [],
        "export": [],
        "latest_stamp": 1793008426,
    }

    async def fake_query(query, at=None, max_lookback=None):
        state["calls"].append((query, at, max_lookback))
        if state["error"] is not None:
            raise state["error"]
        if query.startswith("last_over_time"):
            return [{
                "metric": {
                    "__name__": "device_metric_temperature_celsius",
                    "device_id": "42",
                },
                "value": [state["latest_stamp"], "33.5"],
            }]
        if query.startswith("timestamp"):
            # Mirror VictoriaMetrics' default 5m instant-selector lookback:
            # a sparse series has no timestamp unless max_lookback is widened.
            if max_lookback is None:
                return []
            return [{
                "metric": {
                    "__name__": "device_metric_temperature_celsius",
                    "device_id": "42",
                },
                "value": [state["latest_stamp"], str(state["latest_stamp"])],
            }]
        if query.startswith("max_over_time"):
            return [{"metric": {}, "value": [state["latest_stamp"], "3600"]}]
        return []

    async def fake_range(query, start, end, step):
        state["calls"].append((query, start, end, step))
        if "increase(" in query and "total_bytes_written" in query:
            return [{
                "metric": {"__name__": "device_metric_total_bytes_written"},
                "values": [[state["latest_stamp"], "1000"]],
            }]
        if "increase(" in query:
            return [{
                "metric": {"__name__": "device_metric_total_bytes_read"},
                "values": [[state["latest_stamp"], "2000"]],
            }]
        return state["range"]

    async def fake_export(match, start=None, end=None):
        state["calls"].append((match, start, end))
        return state["export"]

    monkeypatch.setattr(device_service, "vm_query", fake_query)
    monkeypatch.setattr(device_service, "vm_query_range", fake_range)
    monkeypatch.setattr(device_service, "vm_export", fake_export)
    return state


async def test_latest_query_uses_victoriametrics(
    client, auth_headers, device_id, fake_metrics
):
    resp = await client.get(
        f"/devices/{device_id}/metrics",
        params={"period": "latest"},
        headers=auth_headers,
    )
    body = resp.json()
    assert body["status"] == 0, body
    item = body["payload"]["items"][0]
    assert item["temperature_celsius"] == 33.5
    assert item["time"].startswith("2026-")

    queries = [call[0] for call in fake_metrics["calls"]]
    assert any("last_over_time" in query and "[48h]" in query for query in queries)
    assert any(query.startswith("timestamp(") for query in queries)
    assert any("keep_metric_names" in query for query in queries)

    timestamp_call = next(
        call for call in fake_metrics["calls"] if call[0].startswith("timestamp(")
    )
    assert timestamp_call[2] == "48h"


async def test_latest_lookback_is_configurable(
    client, auth_headers, device_id, fake_metrics, monkeypatch
):
    monkeypatch.setattr(settings, "latest_metrics_lookback_hours", 12)

    resp = await client.get(
        f"/devices/{device_id}/metrics",
        params={"period": "latest"},
        headers=auth_headers,
    )
    assert resp.json()["status"] == 0

    queries = [call[0] for call in fake_metrics["calls"]]
    assert any("[12h]" in query for query in queries)
    timestamp_call = next(
        call for call in fake_metrics["calls"] if call[0].startswith("timestamp(")
    )
    assert timestamp_call[2] == "12h"


async def test_latest_backend_failure_is_not_an_empty_success(
    client, auth_headers, device_id, fake_metrics
):
    fake_metrics["error"] = MetricsQueryError("backend unavailable")

    resp = await client.get(
        f"/devices/{device_id}/metrics",
        params={"period": "latest"},
        headers=auth_headers,
    )
    body = resp.json()
    assert body["status"] != 0
    assert "backend unavailable" in body["message"]


async def test_history_query_uses_metricsql_aggregation(
    client, auth_headers, device_id, fake_metrics
):
    fake_metrics["range"] = [{
        "metric": {"__name__": "device_metric_temperature_celsius"},
        "values": [
            [1793008426, "33.5"],
            [1793008526, "34.5"],
        ],
    }]

    resp = await client.get(
        f"/devices/{device_id}/metrics",
        params={"period": "day", "metric": "temperature_celsius"},
        headers=auth_headers,
    )
    body = resp.json()
    assert body["status"] == 0, body
    items = body["payload"]["items"]
    assert [item["temperature_celsius"] for item in items] == [33.5, 34.5]

    query = fake_metrics["calls"][0][0]
    assert query.startswith("avg_over_time(")
    assert "[1d]" in query


async def test_raw_range_merges_victoriametrics_series(
    client, auth_headers, device_id, fake_metrics
):
    fake_metrics["export"] = [
        {
            "metric": {"__name__": "device_metric_temperature_celsius"},
            "values": [33.5, 34.5],
            "timestamps": [1793008426000, 1793008486000],
        },
        {
            "metric": {"__name__": "device_metric_power_on_hours"},
            "values": [100, 101],
            "timestamps": [1793008426000, 1793008486000],
        },
    ]

    resp = await client.get(
        f"/devices/{device_id}/metrics",
        params={
            "start": "2026-10-26T00:00:00Z",
            "end": "2026-10-27T00:00:00Z",
        },
        headers=auth_headers,
    )
    body = resp.json()
    assert body["status"] == 0, body
    items = body["payload"]["items"]
    assert len(items) == 2
    assert items[0]["temperature_celsius"] == 33.5
    assert items[0]["power_on_hours"] == 100
    assert items[1]["temperature_celsius"] == 34.5
    assert items[1]["power_on_hours"] == 101


async def test_io_usage_uses_increase(
    client, auth_headers, device_id, fake_metrics
):
    resp = await client.get(
        f"/devices/{device_id}/metrics",
        params={"period": "day", "metric": "io_usage"},
        headers=auth_headers,
    )
    body = resp.json()
    assert body["status"] == 0, body
    item = body["payload"]["items"][0]
    assert item["data_written"] == 1000
    assert item["data_read"] == 2000

    queries = [call[0] for call in fake_metrics["calls"]]
    assert all("increase(" in query for query in queries)


async def test_speed_uses_max_minus_min(
    client, auth_headers, device_id, fake_metrics
):
    resp = await client.get(
        f"/devices/{device_id}/metrics",
        params={"period": "hour", "metric": "speed"},
        headers=auth_headers,
    )
    body = resp.json()
    assert body["status"] == 0, body
    assert body["payload"]["speed"]["avg_write_speed_bytes"] == 1
    assert body["payload"]["speed"]["avg_read_speed_bytes"] == 1

    queries = [call[0] for call in fake_metrics["calls"]]
    assert all("max_over_time(" in query and "min_over_time(" in query for query in queries)
