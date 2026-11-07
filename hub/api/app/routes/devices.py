from fastapi import APIRouter, Depends, Query

from app.dependencies import get_current_user, get_db
from app.metrics import MetricsQueryError
from app.models.common import APIResponse, NamedResp, PaginatedPayload, Resp
from app.models.event import EventResponse
from app.models.device import DeviceResponse, RawDetail, RawListItem, DeviceUpdateRequest
from app.services.device import (
    clear_device_last_event,
    delete_device,
    get_device,
    get_device_events,
    get_device_raw,
    get_device_raws,
    list_devices,
    update_device_tags,
)
from app.services.metrics_store import get_device_metrics
from app.services.vendor_guess import guess_vendor
from app.utils import page_count, parse_json_array, parse_json_object, parse_ts

router = APIRouter(prefix="/devices", tags=["devices"])


def _build_device_ext(raw_ext: dict | None) -> dict | None:
    if not raw_ext:
        return None
    return parse_json_object(raw_ext)


def _device_to_response(d: dict) -> DeviceResponse:
    tags_val = parse_json_array(d.get("tags"))

    return DeviceResponse(
        id=d["id"],
        user_id=d["user_id"],
        device_hash=d["device_hash"],
        meta_hash=d["meta_hash"],
        device_name=d.get("device_name", ""),
        device_type=d["device_type"],
        using_protocol=d.get("using_protocol"),
        device_ext=_build_device_ext(d.get("device_ext")),
        smart_available=bool(d.get("smart_available")) if d.get("smart_available") is not None else None,
        smart_enabled=bool(d.get("smart_enabled")) if d.get("smart_enabled") is not None else None,
        smart_status=d.get("smart_status"),
        threshold_status=d.get("threshold_status"),
        last_event_at=parse_ts(d.get("last_event_at")),
        tags=tags_val,
        serial_number=d["serial_number"],
        model_name=d["model_name"],
        vendor=d.get("vendor"),
        total_capacity_bytes=d["total_capacity_bytes"],
        firmware_version=d.get("firmware_version"),
        vendor_guess=guess_vendor(d),
        archived=bool(d.get("archived", 0)),
        reg_at=parse_ts(d.get("reg_at")) or "",
    )


@router.get("", response_model=NamedResp("DeviceList", PaginatedPayload[DeviceResponse]), operation_id="list_devices")
async def get_devices(
    plimit: int = Query(50, ge=1, le=200),
    pnum: int = Query(1, ge=1),
    node_id: int | None = Query(None),
    device_type: str | None = Query(None),
    archived: bool | None = Query(None),
    keyword: str | None = Query(None, description="Search model name or tags"),
    sort_by: str = Query("reg_at"),
    sort_order: str = Query("desc"),
    user_id: int = Depends(get_current_user),
    db=Depends(get_db),
):
    devices, total = await list_devices(
        db, user_id, plimit, pnum, node_id,
        device_type=device_type, archived=archived, keyword=keyword,
        sort_by=sort_by, sort_order=sort_order,
    )
    pages = page_count(total, plimit)

    return APIResponse.ok(
        PaginatedPayload(
            items=[_device_to_response(d) for d in devices],
            total=total,
            page=pnum,
            limit=plimit,
            pages=pages,
        )
    )


@router.get("/{device_id}", response_model=NamedResp("Device", DeviceResponse), operation_id="get_device")
async def get_device_endpoint(
    device_id: int,
    user_id: int = Depends(get_current_user),
    db=Depends(get_db),
):
    device = await get_device(db, device_id, user_id)
    if device is None:
        return APIResponse.fail("Device not found", status=100)

    return APIResponse.ok(_device_to_response(device))


@router.patch("/{device_id}", response_model=NamedResp("Device", DeviceResponse), operation_id="update_device")
async def patch_device(
    device_id: int,
    body: DeviceUpdateRequest,
    user_id: int = Depends(get_current_user),
    db=Depends(get_db),
):
    device = await get_device(db, device_id, user_id)
    if device is None:
        return APIResponse.fail("Device not found", status=100)

    # Only touch tags when the client supplied them. The UI sends
    # clear_last_event on its own, and treating a missing tags field as []
    # would silently erase the user's tags.
    if body.tags is not None:
        device = await update_device_tags(db, device_id, user_id, body.tags)
        if device is None:
            return APIResponse.fail("Device not found", status=100)

    if body.clear_last_event:
        await clear_device_last_event(db, device_id, user_id)
        await db.commit()
        device = await get_device(db, device_id, user_id)
        if device is None:
            return APIResponse.fail("Device not found", status=100)

    return APIResponse.ok(_device_to_response(device))


@router.delete("/{device_id}", response_model=Resp, operation_id="archive_device")
async def delete_device_endpoint(
    device_id: int,
    user_id: int = Depends(get_current_user),
    db=Depends(get_db),
):
    deleted = await delete_device(db, device_id, user_id)
    if not deleted:
        return APIResponse.fail("Device not found", status=100)

    return APIResponse.ok()


@router.post("/{device_id}/unarchive", response_model=Resp, operation_id="unarchive_device")
async def unarchive_device(
    device_id: int,
    user_id: int = Depends(get_current_user),
    db=Depends(get_db),
):
    cursor = await db.execute(
        "UPDATE device SET archived = 0 WHERE id = ? AND user_id = ? AND archived = 1 RETURNING id",
        (device_id, user_id),
    )
    row = await cursor.fetchone()
    await db.commit()
    if row is None:
        return APIResponse.fail("Device not found or not archived", status=100)
    return APIResponse.ok()


@router.get("/{device_id}/metrics", response_model=Resp, operation_id="get_device_metrics")
async def get_device_metrics_endpoint(
    device_id: int,
    period: str = Query("day"),
    start: str | None = Query(None),
    end: str | None = Query(None),
    metric: str | None = Query(None),
    user_id: int = Depends(get_current_user),
    db=Depends(get_db),
):
    try:
        data = await get_device_metrics(db, device_id, user_id, period, start, end, metric)
    except MetricsQueryError:
        # Do not turn a metrics-backend failure into an empty chart; the UI
        # shows an error toast for a non-zero envelope status instead.
        return APIResponse.fail("Metrics backend unavailable", status=1)
    except ValueError as exc:
        return APIResponse.fail(str(exc), status=1)
    if data is None:
        return APIResponse.fail("Device not found", status=100)

    return APIResponse.ok(data)


@router.get("/{device_id}/raws", response_model=NamedResp("RawList", list[RawListItem]), operation_id="get_device_raws")
async def get_device_raws_endpoint(
    device_id: int,
    start: str | None = Query(None),
    end: str | None = Query(None),
    user_id: int = Depends(get_current_user),
    db=Depends(get_db),
):
    raws = await get_device_raws(db, device_id, user_id, start, end)
    if raws is None:
        return APIResponse.fail("Device not found", status=100)

    return APIResponse.ok(raws)


@router.get("/{device_id}/raws/{raw_id}", response_model=NamedResp("RawDetailResp", RawDetail), operation_id="get_device_raw")
async def get_device_raw_endpoint(
    device_id: int,
    raw_id: int,
    user_id: int = Depends(get_current_user),
    db=Depends(get_db),
):
    raw = await get_device_raw(db, raw_id, device_id, user_id)
    if raw is None:
        return APIResponse.fail("Raw entry not found", status=100)

    return APIResponse.ok(raw)


@router.get("/{device_id}/events", response_model=NamedResp("DeviceEventList", list[EventResponse]), operation_id="get_device_events")
async def get_device_events_endpoint(
    device_id: int,
    user_id: int = Depends(get_current_user),
    db=Depends(get_db),
):
    events = await get_device_events(db, device_id, user_id)
    if events is None:
        return APIResponse.fail("Device not found", status=100)

    return APIResponse.ok(events)
