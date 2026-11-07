"""VictoriaMetrics client and line-protocol helpers.

dSentry stores SMART metrics as one line-protocol sample per device.
VictoriaMetrics ingests that format through its compatible write endpoint and
expands each field into a Prometheus-style series. For example::

    device_metric,device_id=42 temperature_celsius=33.5,total_bytes_written=123i
    -> device_metric_temperature_celsius{device_id="42"} 33.5
    -> device_metric_total_bytes_written{device_id="42"} 123

Queries use VictoriaMetrics' PromQL/MetricsQL API. The rest of the application
only deals with plain rows, so this module keeps the transport details here.
"""

import json
import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger("dsentry.metrics")


class MetricsQueryError(RuntimeError):
    """VictoriaMetrics failed or rejected a query."""


def _base_url() -> str:
    return settings.victoriametrics_url.rstrip("/")


def _auth() -> tuple[str, str] | None:
    if settings.victoriametrics_username:
        return (
            settings.victoriametrics_username,
            settings.victoriametrics_password,
        )
    return None


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=settings.victoriametrics_timeout_seconds,
        auth=_auth(),
    )


async def _get_json(path: str, params: dict[str, Any]) -> dict:
    url = f"{_base_url()}{path}"
    try:
        async with _client() as client:
            resp = await client.get(url, params=params)
    except Exception as exc:
        raise MetricsQueryError(f"VictoriaMetrics request failed: {exc}") from exc

    if resp.status_code != 200:
        raise MetricsQueryError(
            f"VictoriaMetrics query failed ({resp.status_code}): {resp.text[:200]}"
        )
    try:
        payload = resp.json()
    except ValueError as exc:
        raise MetricsQueryError("VictoriaMetrics returned invalid JSON") from exc

    if payload.get("status") != "success":
        raise MetricsQueryError(
            f"VictoriaMetrics query failed: {payload.get('error', payload)}"
        )
    return payload


async def vm_query(
    query: str,
    at: float | None = None,
    max_lookback: str | None = None,
) -> list[dict]:
    """Run an instant query and return its raw result vector.

    ``max_lookback`` overrides VictoriaMetrics' default 5m instant-selector
    lookback. It is needed when reading the timestamp of a sparse series.
    """
    params: dict[str, Any] = {"query": query}
    if at is not None:
        params["time"] = f"{at:.3f}"
    if max_lookback is not None:
        params["max_lookback"] = max_lookback
    payload = await _get_json("/api/v1/query", params)
    return (payload.get("data") or {}).get("result", [])


async def vm_query_range(
    query: str,
    start: float,
    end: float,
    step: str,
) -> list[dict]:
    """Run a range query and return its raw result matrix."""
    payload = await _get_json(
        "/api/v1/query_range",
        {
            "query": query,
            "start": f"{start:.3f}",
            "end": f"{end:.3f}",
            "step": step,
        },
    )
    return (payload.get("data") or {}).get("result", [])


async def vm_export(
    match: str,
    start: float | None = None,
    end: float | None = None,
) -> list[dict]:
    """Export raw samples in VictoriaMetrics' JSON-line format."""
    params: dict[str, Any] = {"match[]": match}
    if start is not None:
        params["start"] = f"{start:.3f}"
    if end is not None:
        params["end"] = f"{end:.3f}"

    url = f"{_base_url()}/api/v1/export"
    try:
        async with _client() as client:
            resp = await client.get(url, params=params)
    except Exception as exc:
        raise MetricsQueryError(f"VictoriaMetrics export failed: {exc}") from exc

    if resp.status_code != 200:
        raise MetricsQueryError(
            f"VictoriaMetrics export failed ({resp.status_code}): {resp.text[:200]}"
        )

    rows: list[dict] = []
    for line in resp.text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError as exc:
            raise MetricsQueryError(
                "VictoriaMetrics export returned invalid JSON"
            ) from exc
    return rows


async def write_metrics(payload: str) -> bool:
    """Write line-protocol metrics to VictoriaMetrics."""
    url = f"{_base_url()}/api/v2/write"
    try:
        async with _client() as client:
            resp = await client.post(
                url,
                params={"precision": "s"},
                headers={"Content-Type": "text/plain"},
                content=payload,
            )
    except Exception as exc:
        logger.error("VictoriaMetrics write failed: %s", exc)
        return False

    if resp.status_code not in (200, 204):
        logger.warning(
            "VictoriaMetrics write error %s: %s",
            resp.status_code,
            resp.text[:200],
        )
        return False
    return True


async def write_metrics_best_effort(payload: str, context: str) -> None:
    """Write metrics without stalling SQLite writers; log on failure."""
    if not await write_metrics(payload):
        logger.warning("Failed to write %s to VictoriaMetrics", context)


async def metrics_health() -> bool:
    """Check whether VictoriaMetrics is reachable."""
    try:
        async with _client() as client:
            resp = await client.get(f"{_base_url()}/health")
        return resp.status_code == 200
    except Exception:
        return False


def _escape_measurement(s: str) -> str:
    return s.replace("\\", "\\\\").replace(" ", "\\ ").replace(",", "\\,")


def _escape_token(s: str) -> str:
    """Escape a tag key/value or field key per the line protocol spec."""
    return (
        s.replace("\\", "\\\\")
        .replace(" ", "\\ ")
        .replace(",", "\\,")
        .replace("=", "\\=")
    )


def _format_field_value(v: object) -> str | None:
    """Format a field value for line protocol; None means "drop this field".

    Node-supplied values must never be interpolated raw: strings are quoted
    and escaped so a value containing a newline cannot inject additional
    points, and non-scalar values are dropped instead of corrupting the line.
    """
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return f"{v}i"
    if isinstance(v, float):
        if v != v or v in (float("inf"), float("-inf")):
            return None
        return repr(v)
    if isinstance(v, str):
        escaped = (
            v.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", "\\r")
        )
        return f'"{escaped}"'
    return None


def _build_line_protocol(
    measurement: str,
    tags: dict[str, str],
    fields: dict[str, object],
    ts_s: int | None = None,
) -> str:
    tag_str = ",".join(
        f"{_escape_token(str(k))}={_escape_token(str(v))}"
        for k, v in tags.items()
        if v is not None
    )
    field_parts = []
    for k, v in fields.items():
        formatted = _format_field_value(v)
        if formatted is None:
            continue
        field_parts.append(f"{_escape_token(str(k))}={formatted}")
    if not field_parts:
        # A line-protocol point needs at least one field; returning "" lets
        # callers skip it instead of failing the whole batch write.
        return ""
    field_str = ",".join(field_parts)
    line = f"{_escape_measurement(measurement)},{tag_str} {field_str}"
    if ts_s is not None:
        line += f" {ts_s}"
    return line
