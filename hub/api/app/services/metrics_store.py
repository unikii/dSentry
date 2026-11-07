"""VictoriaMetrics storage/query helpers for device metrics."""

import logging
import re
import time as _time
from datetime import datetime, timezone
from typing import Any

from aiosqlite import Connection

from app.config import settings
from app.constants import MAX_METRIC_EXPORT_DAYS, MAX_METRIC_EXPORT_POINTS
from app.metrics import (
    MetricsQueryError,
    vm_export,
    vm_query,
    vm_query_range,
)
from app.services.device import _metric_meta, _metrics_to_line_protocol, get_device

logger = logging.getLogger("dsentry.metrics_store")

_SAFE_VALUE_RE = re.compile(r'^[a-zA-Z0-9_\-:\.\+\s]+$')

def _entry_timestamp(metrics: dict[str, Any], default_ts: int) -> int:
    """Point time from the node, so queued (outbox) pushes replay history
    with their original collection time instead of the flush time."""
    raw = metrics.get("TimestampUTC")
    if isinstance(raw, str):
        try:
            return int(datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp())
        except ValueError:
            pass
    return default_ts


async def resolve_push_metrics(
    db: Connection,
    user_id: int,
    metrics_list: list[dict[str, Any]],
) -> tuple[list[str], list[int]]:
    """Map pushed metrics to registered devices and build line protocol.

    DB-only by design: callers run it inside their write transaction and send
    the returned lines to VictoriaMetrics after committing, so the network call
    never holds the SQLite write lock.
    """
    hashes = [
        m.get("DeviceHash") or m.get("device_hash") or ""
        for m in metrics_list
    ]
    if not any(hashes):
        return [], []

    placeholders = ", ".join("?" for _ in hashes)
    cursor = await db.execute(
        f"SELECT id, device_hash FROM device "
        f"WHERE device_hash IN ({placeholders}) AND user_id = ? AND archived = 0",
        (*hashes, user_id),
    )
    rows = await cursor.fetchall()
    hash_to_id = {r["device_hash"]: r["id"] for r in rows}

    pushed_device_ids: list[int] = []
    line_buf: list[str] = []
    ts_s = int(_time.time())

    for m in metrics_list:
        dh = m.get("DeviceHash") or m.get("device_hash") or ""
        device_id = hash_to_id.get(dh)
        if device_id is None:
            continue
        pushed_device_ids.append(device_id)
        line = _metrics_to_line_protocol(device_id, user_id, m, ts_s=_entry_timestamp(m, ts_s))
        if line:
            line_buf.append(line)

    return line_buf, pushed_device_ids


_MEASUREMENT = "device_metric"
_METRIC_PREFIX = f"{_MEASUREMENT}_"


def _metric_series_name(metric: str) -> str:
    return f"{_METRIC_PREFIX}{metric}"


def _selector(device_id: int, metric: str | None = None) -> str:
    if metric is not None:
        return f'{{__name__="{_metric_series_name(metric)}",device_id="{device_id}"}}'
    return f'{{__name__=~"{_METRIC_PREFIX}.*",device_id="{device_id}"}}'


def _vm_time_seconds(value: float | int) -> float:
    """Query API timestamps are seconds; export timestamps are milliseconds."""
    value = float(value)
    return value / 1000.0 if value > 1e12 else value


def _iso_time(value: float | int) -> str:
    return (
        datetime.fromtimestamp(_vm_time_seconds(value), tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _pair_value(pair: Any) -> float | None:
    try:
        value = float(pair[1])
    except (IndexError, TypeError, ValueError):
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return value


def _coerce_metric_value(metric: str, value: float) -> int | float:
    meta = _metric_meta(metric)
    if meta is not None and meta.get("type") == "int":
        return int(round(value))
    return float(value)


def _parse_query_time(value: str | None) -> float | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


async def _latest_metrics_row(
    device_id: int,
    metric: str | None = None,
) -> dict | None:
    """Return the latest values for all fields as one row.

    VictoriaMetrics stores each field as a separate series, so the two
    queries below are joined by series name. ``timestamp()`` uses
    ``keep_metric_names`` because the function otherwise drops ``__name__``.
    """
    lookback = settings.latest_metrics_lookback_hours
    selector = _selector(device_id, metric)

    values = await vm_query(f"last_over_time({selector}[{lookback}h])")
    if not values:
        return None

    stamps = await vm_query(
        f"timestamp({selector}) keep_metric_names",
        max_lookback=f"{lookback}h",
    )
    stamp_by_name: dict[str, float] = {}
    for series in stamps:
        name = series.get("metric", {}).get("__name__")
        if not name:
            continue
        stamp = _pair_value(series.get("value", []))
        if stamp is not None:
            stamp_by_name[name] = stamp

    row: dict[str, Any] = {"time": None, "device_id": str(device_id)}
    newest = 0.0
    for series in values:
        name = series.get("metric", {}).get("__name__", "")
        if not name.startswith(_METRIC_PREFIX):
            continue
        metric = name[len(_METRIC_PREFIX):]
        if _metric_meta(metric) is None:
            continue
        value = _pair_value(series.get("value", []))
        if value is None:
            continue
        row[metric] = _coerce_metric_value(metric, value)
        stamp = stamp_by_name.get(name)
        if stamp is not None:
            newest = max(newest, stamp)

    if len(row) <= 2:
        return None
    row["time"] = _iso_time(newest) if newest else _iso_time(_time.time())
    return row


_AGG_WINDOWS: dict[str, tuple[int, str, int]] = {
    "hour": (24 * 3600, "1h", 3600),
    "day": (30 * 86400, "1d", 86400),
    "week": (52 * 7 * 86400, "1w", 7 * 86400),
    # VictoriaMetrics has no calendar-month step; 30d is the closest fixed
    # bucket. The UI's "month" range is one year, so this yields ~12 points.
    "month": (365 * 86400, "30d", 30 * 86400),
}

_USAGE_WINDOWS: dict[str, tuple[int, str, int]] = {
    "hour": (24 * 3600, "1h", 3600),
    "day": (30 * 86400, "1d", 86400),
    "week": (52 * 7 * 86400, "1w", 7 * 86400),
    "month": (365 * 86400, "30d", 30 * 86400),
    "year": (3650 * 86400, "365d", 365 * 86400),
}


async def _history_metrics_rows(
    device_id: int,
    metric: str,
    period: str,
) -> list[dict]:
    meta = _metric_meta(metric)
    if meta is None:
        return []
    lookback, step, step_seconds = _AGG_WINDOWS.get(period, _AGG_WINDOWS["day"])
    aggregate = str(meta.get("aggregate", "avg")).lower()
    function = {
        "avg": "avg_over_time",
        "max": "max_over_time",
        "min": "min_over_time",
        "sum": "sum_over_time",
    }.get(aggregate, "avg_over_time")

    # End the range on a step boundary. Otherwise query_range stops one step
    # short when the lookback is not an exact multiple of the step (30d/365d).
    end = _time.time()
    steps = max(1, (lookback + step_seconds - 1) // step_seconds)
    start = end - steps * step_seconds
    query = f"{function}({_selector(device_id, metric)}[{step}])"
    series = await vm_query_range(query, start, end, step)

    rows: list[dict] = []
    for item in series:
        for pair in item.get("values", []):
            value = _pair_value(pair)
            if value is None:
                continue
            rows.append({
                "time": _iso_time(float(pair[0])),
                "device_id": str(device_id),
                metric: _coerce_metric_value(metric, value),
            })
    rows.sort(key=lambda row: row["time"])
    return rows


async def _raw_metrics_rows(
    device_id: int,
    metric: str | None,
    start: str,
    end: str,
) -> list[dict]:
    start_ts = _parse_query_time(start)
    end_ts = _parse_query_time(end)
    if start_ts is None or end_ts is None or start_ts > end_ts:
        return []

    series = await vm_export(_selector(device_id, metric), start=start_ts, end=end_ts)
    rows_by_ts: dict[int, dict] = {}
    for item in series:
        name = item.get("metric", {}).get("__name__", "")
        if not name.startswith(_METRIC_PREFIX):
            continue
        field = name[len(_METRIC_PREFIX):]
        if _metric_meta(field) is None:
            continue
        timestamps = item.get("timestamps", [])
        values = item.get("values", [])
        for timestamp, value in zip(timestamps, values):
            try:
                timestamp_ms = int(timestamp)
                numeric_value = float(value)
            except (TypeError, ValueError):
                continue
            if len(rows_by_ts) >= MAX_METRIC_EXPORT_POINTS and timestamp_ms not in rows_by_ts:
                logger.warning(
                    "Raw metric export truncated at %d points for device %s",
                    MAX_METRIC_EXPORT_POINTS,
                    device_id,
                )
                break
            row = rows_by_ts.setdefault(
                timestamp_ms,
                {"time": _iso_time(timestamp_ms), "device_id": str(device_id)},
            )
            row[field] = _coerce_metric_value(field, numeric_value)

    return [rows_by_ts[timestamp] for timestamp in sorted(rows_by_ts)]


async def _speed_metrics(
    device_id: int,
    period: str,
    start: str | None,
    end: str | None,
) -> dict:
    start_ts = _parse_query_time(start)
    end_ts = _parse_query_time(end)

    if start_ts is not None and end_ts is not None:
        seconds = int(end_ts - start_ts)
        at = end_ts
    elif start_ts is not None:
        at = _time.time()
        seconds = int(at - start_ts)
    elif end_ts is not None:
        at = end_ts
        seconds = {"hour": 3600, "day": 86400, "week": 604800}.get(period, 86400)
    else:
        at = _time.time()
        seconds = {"hour": 3600, "day": 86400, "week": 604800}.get(period, 86400)

    if seconds <= 0:
        return {}

    result: dict[str, int] = {}
    for metric, key in (
        ("total_bytes_written", "avg_write_speed_bytes"),
        ("total_bytes_read", "avg_read_speed_bytes"),
    ):
        selector = _selector(device_id, metric)
        query = (
            f"max_over_time({selector}[{seconds}s]) - "
            f"min_over_time({selector}[{seconds}s])"
        )
        series = await vm_query(query, at=at)
        if not series:
            continue
        value = _pair_value(series[0].get("value", []))
        if value is not None:
            result[key] = round(value / seconds)
    return result


async def _io_usage_rows(device_id: int, period: str) -> list[dict]:
    lookback, step, step_seconds = _USAGE_WINDOWS.get(period, _USAGE_WINDOWS["day"])
    end = _time.time()
    steps = max(1, (lookback + step_seconds - 1) // step_seconds)
    start = end - steps * step_seconds

    rows_by_ts: dict[int, dict] = {}
    for metric, key in (
        ("total_bytes_written", "data_written"),
        ("total_bytes_read", "data_read"),
    ):
        query = f"increase({_selector(device_id, metric)}[{step}])"
        series = await vm_query_range(query, start, end, step)
        for item in series:
            for pair in item.get("values", []):
                value = _pair_value(pair)
                if value is None:
                    continue
                timestamp = int(float(pair[0]))
                row = rows_by_ts.setdefault(
                    timestamp,
                    {
                        "time": _iso_time(timestamp),
                        "device_id": str(device_id),
                        "data_written": 0,
                        "data_read": 0,
                    },
                )
                row[key] = max(0, int(round(value)))

    return [rows_by_ts[timestamp] for timestamp in sorted(rows_by_ts)]


async def get_device_metrics(
    db: Connection,
    device_id: int,
    user_id: int,
    period: str = "day",
    start: str | None = None,
    end: str | None = None,
    metric: str | None = None,
) -> dict | None:
    device = await get_device(db, device_id, user_id)
    if device is None:
        return None

    if start and not _SAFE_VALUE_RE.match(start):
        start = None
    if end and not _SAFE_VALUE_RE.match(end):
        end = None
    start_dt = end_dt = None
    if start:
        try:
            start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            start = None
    if end:
        try:
            end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            end = None
    if start_dt is not None and start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)
    if end_dt is not None and end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=timezone.utc)
    if start_dt and end_dt and end_dt > start_dt:
        max_range = MAX_METRIC_EXPORT_DAYS * 24 * 3600
        if (end_dt - start_dt).total_seconds() > max_range:
            raise ValueError(
                f"Requested range exceeds the maximum of {MAX_METRIC_EXPORT_DAYS} days"
            )
    if metric and not _SAFE_VALUE_RE.match(metric):
        metric = None
    if metric and metric not in {"io_usage", "speed"} and _metric_meta(metric) is None:
        metric = None

    if period == "latest":
        if metric in {"io_usage", "speed"}:
            metric = None
        try:
            row = await _latest_metrics_row(device_id, metric)
            return {"items": [row] if row is not None else [], "speed": None}
        except MetricsQueryError:
            logger.exception("VictoriaMetrics latest metrics query failed")
            raise

    # Return counter deltas rather than the lifetime totals used by the
    # regular metric history query.
    if metric == "io_usage":
        try:
            results = await _io_usage_rows(device_id, period)
            return {"items": results, "speed": None}
        except MetricsQueryError:
            logger.exception("I/O usage query failed")
            raise

    if metric == "speed":
        try:
            speed = await _speed_metrics(device_id, period, start, end)
            return {"items": [], "speed": speed or None}
        except MetricsQueryError:
            logger.exception("Speed query failed")
            raise

    if start and end:
        try:
            results = await _raw_metrics_rows(device_id, metric, start, end)
            return {"items": results, "speed": None}
        except MetricsQueryError:
            logger.exception("VictoriaMetrics metrics query failed")
            raise

    if metric is None:
        return {"items": [], "speed": None}

    try:
        results = await _history_metrics_rows(device_id, metric, period)
        return {"items": results, "speed": None}
    except MetricsQueryError:
        logger.exception("VictoriaMetrics metrics query failed")
        raise


