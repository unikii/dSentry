import base64
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from pydantic import TypeAdapter, ValidationError

from app.config import settings
from app.constants import (
    MAX_DEVICES_PER_PUSH,
    MAX_EVENTS_PER_PUSH,
    MAX_METAS_PER_PUSH,
    MAX_METRICS_PER_PUSH,
    MAX_RAW_COMPRESSED_SIZE,
)
from app.dependencies import get_current_node, get_db
from app.metrics import write_metrics
from app.models.common import APIResponse, Resp
from app.models.push import (
    METRICS_SCHEMA_VERSION,
    NodeEventItem,
    PushMetasRequest,
    PushMetricsRequest,
)
from app.services.alerts import (
    enqueue_event_alert,
    insert_event,
    process_pending_event_alerts,
    user_has_enabled_alerts,
)
from app.services.device import (
    any_device_hash_known,
    device_owned,
    push_metas,
    push_raws,
)
from app.services.metrics_store import resolve_push_metrics
from app.services.node import compute_push_raw, get_effective_limits
from app.utils import device_limit_exceeded, parse_utc_datetime

logger = logging.getLogger("dsentry.routes.push")

router = APIRouter(prefix="/nodes", tags=["nodes"])

_EVENT_ITEMS = TypeAdapter(list[NodeEventItem])

_EVENT_TYPES = {
    "device_smart_fail",
    "device_smart_success",
    "device_threshold_warning",
    "device_threshold_critical",
    "device_missing",
    "device_online",
}



async def _read_form_json(value: Any) -> Any | None:
    try:
        raw = value if isinstance(value, str) else await value.read()
        return json.loads(raw)
    except (AttributeError, json.JSONDecodeError, TypeError, UnicodeDecodeError):
        return None


def _collected_at(value: Any) -> str | None:
    """Normalize a node-supplied collection timestamp; ignore invalid values."""
    parsed = parse_utc_datetime(value)
    return parsed.isoformat() if parsed else None


async def _read_raw_parts(form: Any, devices_meta: Any) -> dict[int, tuple[bytes, str | None]]:
    if not isinstance(devices_meta, list):
        return {}

    raws: dict[int, tuple[bytes, str | None]] = {}
    for device_meta in devices_meta:
        if not isinstance(device_meta, dict):
            continue
        device_id = device_meta.get("device_id")
        if not isinstance(device_id, int):
            continue

        part = form.get(str(device_id))
        if part is None:
            continue
        data = part.encode() if isinstance(part, str) else await part.read()
        if len(data) > MAX_RAW_COMPRESSED_SIZE:
            logger.warning("Skipping oversized raw part for device %s", device_id)
            continue
        raws[device_id] = (data, _collected_at(device_meta.get("collected_at")))
    return raws




@router.post("/{node_id}/metrics", response_model=Resp, operation_id="push_metrics")
async def push_node_metrics(
    node_id: int,
    body: PushMetricsRequest,
    node: dict = Depends(get_current_node),
    db=Depends(get_db),
):
    if (
        body.schema_version is not None
        and body.schema_version != METRICS_SCHEMA_VERSION
    ):
        return APIResponse.fail(
            f"Unsupported metrics schema version: {body.schema_version}", status=1
        )

    push_interval = settings.global_push_interval
    now = datetime.now(timezone.utc)

    last_push = parse_utc_datetime(node.get("last_metrics_push"))
    if last_push is not None:
        if (last_push + timedelta(minutes=push_interval)) > now:
            return APIResponse.fail("Push interval not elapsed", status=1, notify=False)

    metrics_list = [m.model_dump() for m in body.metrics]
    if not metrics_list:
        return APIResponse.fail("No metrics provided", status=1)
    if len(metrics_list) > MAX_METRICS_PER_PUSH:
        return APIResponse.fail("Too many metrics in one push", status=201)

    user_id = node["user_id"]
    _, device_limit = await get_effective_limits(db, user_id)

    # The device limit bounds devices, not historical points. A replayed
    # backlog for one disk commonly contains dozens of points and must not be
    # rejected for exceeding the per-node device count.
    unique_hashes = {
        m.get("DeviceHash") or m.get("device_hash")
        for m in metrics_list
        if (m.get("DeviceHash") or m.get("device_hash"))
    }
    if device_limit_exceeded(device_limit, len(unique_hashes)):
        return APIResponse.fail(f"Exceeds device limit ({device_limit})", status=201)

    lines, pushed_device_ids = await resolve_push_metrics(
        db, user_id, metrics_list
    )
    pushed_device_ids = list(dict.fromkeys(pushed_device_ids))

    if not pushed_device_ids:
        hashes = list(dict.fromkeys(
            (m.get("DeviceHash") or m.get("device_hash") or "") for m in metrics_list
        ))
        hashes = [h for h in hashes if h]
        if hashes and not await any_device_hash_known(db, user_id, hashes):
            # None of these hashes exist (even archived). Do not arm the
            # interval; this tells the node to re-register its devices instead
            # of pushing into the void forever after a hub restore.
            return APIResponse.fail(
                "No known devices; re-register required", status=2, notify=False
            )

    # Serialize the interval check with BEGIN IMMEDIATE: checking it before
    # the transaction let two concurrent pushes both pass and both write.
    await db.execute("BEGIN IMMEDIATE")
    try:
        cursor = await db.execute(
            "SELECT push_count, last_metrics_push, last_device_push "
            "FROM node WHERE id = ?",
            (node_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            await db.rollback()
            return APIResponse.fail("Node not found", status=101)

        db_last_push = parse_utc_datetime(row["last_metrics_push"])
        if db_last_push is not None and (
            db_last_push + timedelta(minutes=push_interval)
        ) > now:
            await db.rollback()
            return APIResponse.fail("Push interval not elapsed", status=1, notify=False)

        previous = (
            row["push_count"],
            row["last_metrics_push"],
            row["last_device_push"],
        )
        if pushed_device_ids:
            await db.execute(
                "UPDATE node SET push_count = push_count + 1, last_metrics_push = ?, last_device_push = ? WHERE id = ?",
                (now.isoformat(), json.dumps(pushed_device_ids), node_id),
            )
        else:
            await db.execute(
                "UPDATE node SET push_count = push_count + 1, last_metrics_push = ? WHERE id = ?",
                (now.isoformat(), node_id),
            )
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    if lines:
        # Do not keep the interval consumed when the points never reached
        # VictoriaMetrics; restore the previous values so the node retries.
        if not await write_metrics("\n".join(lines)):
            await db.execute(
                "UPDATE node SET push_count = ?, last_metrics_push = ?, last_device_push = ? WHERE id = ?",
                (previous[0], previous[1], previous[2], node_id),
            )
            await db.commit()
            return APIResponse.fail(
                "Metrics storage unavailable; retry later", status=1, notify=False
            )

    return APIResponse.ok()


@router.post("/{node_id}/raws", response_model=Resp, operation_id="push_raws")
async def push_node_raws(
    node_id: int,
    request: Request,
    node: dict = Depends(get_current_node),
    db=Depends(get_db),
):
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" not in content_type:
        return APIResponse.fail("Multipart form-data required", status=1)

    form = await request.form()

    meta_raw = form.get("meta")
    if meta_raw is None:
        return APIResponse.fail("Missing meta field", status=1)

    meta = await _read_form_json(meta_raw)
    if not isinstance(meta, dict):
        return APIResponse.fail("Invalid meta JSON", status=1)

    devices_meta = meta.get("devices", [])
    if isinstance(devices_meta, list) and len(devices_meta) > MAX_DEVICES_PER_PUSH:
        return APIResponse.fail("Too many devices in one push", status=201)
    raws = await _read_raw_parts(form, devices_meta)

    if not raws:
        return APIResponse.fail("No raw data provided", status=1)

    now = datetime.now(timezone.utc)

    await db.execute("BEGIN IMMEDIATE")
    try:
        cursor = await db.execute(
            "SELECT last_raw_push, last_device_push, user_id FROM node WHERE id = ?",
            (node_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            await db.rollback()
            return APIResponse.fail("Node not found", status=101)

        fresh_node = dict(row)
        push_raw = compute_push_raw(fresh_node, now)

        if not push_raw:
            await db.rollback()
            return APIResponse.fail("Raw push not required at this time", status=1)

        _, device_limit = await get_effective_limits(db, fresh_node["user_id"])
        if device_limit_exceeded(device_limit, len(raws)):
            await db.rollback()
            return APIResponse.fail(f"Exceeds device limit ({device_limit})", status=201)

        valid_raws: dict[int, bytes] = {}
        raw_times: dict[int, str] = {}
        for device_id, (raw_data, collected_at) in raws.items():
            if len(raw_data) <= MAX_RAW_COMPRESSED_SIZE:
                valid_raws[device_id] = raw_data
                if collected_at:
                    raw_times[device_id] = collected_at

        if not valid_raws:
            await db.rollback()
            return APIResponse.fail("No valid raw data provided", status=1)

        await push_raws(db, fresh_node["user_id"], valid_raws, raw_times)

        await db.execute(
            "UPDATE node SET last_raw_push = ? WHERE id = ?",
            (now.isoformat(), node_id),
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return APIResponse.ok()


@router.post("/{node_id}/events", response_model=Resp, operation_id="push_events")
async def push_node_events(
    node_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    node: dict = Depends(get_current_node),
    db=Depends(get_db),
):
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" not in content_type:
        return APIResponse.fail("Multipart form-data required", status=1)

    form = await request.form()

    events_raw = form.get("events")
    if events_raw is None:
        return APIResponse.fail("Missing events field", status=1)

    events = await _read_form_json(events_raw)
    if not isinstance(events, list):
        return APIResponse.fail("Invalid events JSON", status=1)
    # Bound the work before running per-item validation over a huge array.
    if len(events) > MAX_EVENTS_PER_PUSH:
        return APIResponse.fail("Too many events in one push", status=201)

    try:
        events = [e.model_dump() for e in _EVENT_ITEMS.validate_python(events)]
    except ValidationError:
        return APIResponse.fail("Invalid events JSON", status=1)

    meta_raw = form.get("meta")
    meta = await _read_form_json(meta_raw) if meta_raw else None
    devices_meta = meta.get("devices", []) if isinstance(meta, dict) else []
    if isinstance(devices_meta, list) and len(devices_meta) > MAX_DEVICES_PER_PUSH:
        return APIResponse.fail("Too many devices in one push", status=201)
    raws_by_device = await _read_raw_parts(form, devices_meta)

    cursor = await db.execute(
        "SELECT last_device_push, user_id FROM node WHERE id = ?",
        (node_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        return APIResponse.fail("Node not found", status=101)

    _, device_limit = await get_effective_limits(db, row["user_id"])
    # An event batch can contain several events per disk (SMART failure,
    # threshold warning, recovery, ...). Count distinct devices, not events,
    # or a healthy-size fleet can be rejected permanently.
    event_devices = set()
    for evt in events:
        device_id = evt.get("device_id")
        if device_id is not None:
            event_devices.add(("id", device_id))
        elif evt.get("device_hash"):
            event_devices.add(("hash", evt["device_hash"]))
    if device_limit_exceeded(device_limit, len(event_devices)):
        return APIResponse.fail(f"Exceeds device limit ({device_limit})", status=201)

    triggered_events: list[tuple[int, str, int | None, str | None]] = []
    has_alerts = await user_has_enabled_alerts(db, node["user_id"])
    inserted_raw_devices: set[int] = set()

    await db.execute("BEGIN IMMEDIATE")
    try:
        for evt in events:
            event_type = evt.get("event_type")
            if event_type not in _EVENT_TYPES:
                continue
            device_id = evt.get("device_id")
            note = evt.get("summary", "")
            device_hash = evt.get("device_hash", "")
            collected_at = _collected_at(evt.get("collected_at"))

            if device_hash and not device_id:
                cursor = await db.execute(
                    "SELECT id FROM device WHERE device_hash = ? AND user_id = ? "
                    "AND archived = 0",
                    (device_hash, node["user_id"]),
                )
                dev = await cursor.fetchone()
                if dev:
                    device_id = dev["id"]

            if device_id:
                # device_id comes from the node's payload: only accept it if
                # the device belongs to the authenticated user, otherwise the
                # event is recorded without a device association.
                if not await device_owned(db, device_id, node["user_id"]):
                    device_id = None

            result = await insert_event(
                db, node["user_id"], event_type,
                device_id=device_id, note=note, collected_at=collected_at,
            )
            triggered_events.append((result["id"], event_type, device_id, note))
            if has_alerts:
                await enqueue_event_alert(
                    db,
                    node["user_id"],
                    result["id"],
                    event_type,
                    device_id,
                    note,
                )

            if event_type == "device_smart_fail" and device_id:
                await db.execute(
                    "UPDATE device SET smart_status = 1 WHERE id = ? AND user_id = ?",
                    (device_id, node["user_id"]),
                )
            elif event_type == "device_smart_success" and device_id:
                await db.execute(
                    "UPDATE device SET smart_status = 0 WHERE id = ? AND user_id = ?",
                    (device_id, node["user_id"]),
                )

            if event_type == "device_threshold_warning" and device_id:
                await db.execute(
                    "UPDATE device SET threshold_status = 1 WHERE id = ? AND user_id = ?",
                    (device_id, node["user_id"]),
                )
            elif event_type == "device_threshold_critical" and device_id:
                await db.execute(
                    "UPDATE device SET threshold_status = 2 WHERE id = ? AND user_id = ?",
                    (device_id, node["user_id"]),
                )

            # A cycle can produce several events for one disk (SMART failure,
            # threshold critical, ...). Store its raw snapshot only once.
            if device_id and device_id in raws_by_device and device_id not in inserted_raw_devices:
                raw_bytes, raw_collected_at = raws_by_device[device_id]
                if len(raw_bytes) > MAX_RAW_COMPRESSED_SIZE:
                    continue
                if await device_owned(db, device_id, node["user_id"]):
                    if raw_collected_at:
                        await db.execute(
                            "INSERT INTO device_raw (device_id, raw_output, add_at) VALUES (?, ?, ?)",
                            (device_id, raw_bytes, raw_collected_at),
                        )
                    else:
                        await db.execute(
                            "INSERT INTO device_raw (device_id, raw_output) VALUES (?, ?)",
                            (device_id, raw_bytes),
                        )
                    inserted_raw_devices.add(device_id)
            elif device_id and evt.get("raw_data") and device_id not in inserted_raw_devices:
                try:
                    raw_bytes = base64.b64decode(evt["raw_data"])
                    if len(raw_bytes) > MAX_RAW_COMPRESSED_SIZE:
                        continue
                    if await device_owned(db, device_id, node["user_id"]):
                        if collected_at:
                            await db.execute(
                                "INSERT INTO device_raw (device_id, raw_output, add_at) VALUES (?, ?, ?)",
                                (device_id, raw_bytes, collected_at),
                            )
                        else:
                            await db.execute(
                                "INSERT INTO device_raw (device_id, raw_output) VALUES (?, ?)",
                                (device_id, raw_bytes),
                            )
                        inserted_raw_devices.add(device_id)
                except Exception:
                    pass
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    if has_alerts:
        for event_id, _event_type, _device_id, _note in triggered_events:
            background_tasks.add_task(
                _bg_send_alerts,
                node["user_id"],
                event_id=event_id,
            )

    return APIResponse.ok()


async def _bg_send_alerts(user_id: int, event_id: int | None = None) -> None:
    from app.database import open_db

    if event_id is None or user_id is None:
        return
    async with open_db() as db:
        await process_pending_event_alerts(db, event_id=event_id, limit=1)


@router.post("/{node_id}/metas", response_model=Resp, operation_id="push_metas")
async def push_node_metas(
    node_id: int,
    body: PushMetasRequest,
    node: dict = Depends(get_current_node),
    db=Depends(get_db),
):
    metas = [m.model_dump() for m in body.metas]
    if not metas:
        return APIResponse.fail("No metas provided", status=1)
    if len(metas) > MAX_METAS_PER_PUSH:
        return APIResponse.fail("Too many metas in one push", status=201)

    await db.execute("BEGIN IMMEDIATE")
    try:
        results = await push_metas(db, node["user_id"], metas)
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return APIResponse.ok({"results": results})
