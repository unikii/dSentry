import logging

from fastapi import APIRouter, Depends, Query

from app.constants import MAX_DEVICES_PER_PUSH
from app.dependencies import get_current_node, get_current_user, get_db
from app.metrics import write_metrics_best_effort
from app.models.common import APIResponse, NamedResp, PaginatedPayload, Resp
from app.models.node import (
    NodeConfigResponse,
    NodeCreateResponse,
    NodeResponse,
    NodeUpdateRequest,
    RegisterNodePayload,
)
from app.models.push import RegisterDevicesRequest, RegisterNodeRequest
from app.services.device import register_devices
from app.services.node import (
    create_node,
    delete_node,
    get_effective_limits,
    get_node_config,
    list_nodes,
    register_node,
    update_node,
)
from app.utils import device_limit_exceeded, page_count, parse_json_array, parse_ts

logger = logging.getLogger("dsentry.routes.nodes")

router = APIRouter(prefix="/nodes", tags=["nodes"])

def _node_to_response(node: dict) -> NodeResponse:
    return NodeResponse(
        id=node["id"],
        user_id=node["user_id"],
        hostname=node.get("hostname"),
        host_os=node.get("host_os"),
        push_key=str(node["push_key"]),
        push_count=node.get("push_count", 0),
        tags=parse_json_array(node.get("tags")),
        last_raw_push=parse_ts(node.get("last_raw_push")),
        last_metrics_push=parse_ts(node.get("last_metrics_push")),
        last_device_push=parse_json_array(node.get("last_device_push")),
        reg_at=parse_ts(node.get("reg_at")),
        add_at=parse_ts(node.get("add_at")),
    )


@router.get("", response_model=NamedResp("NodeList", PaginatedPayload[NodeResponse]), operation_id="list_nodes")
async def get_nodes(
    plimit: int = Query(50, ge=1, le=200),
    pnum: int = Query(1, ge=1),
    keyword: str | None = Query(None),
    sort_by: str = Query("reg_at"),
    sort_order: str = Query("desc"),
    user_id: int = Depends(get_current_user),
    db=Depends(get_db),
):
    nodes, total = await list_nodes(db, user_id, plimit, pnum, keyword=keyword, sort_by=sort_by, sort_order=sort_order)
    pages = page_count(total, plimit)

    return APIResponse.ok(
        PaginatedPayload(
            items=[_node_to_response(n) for n in nodes],
            total=total,
            page=pnum,
            limit=plimit,
            pages=pages,
        )
    )


@router.get("/{node_id}", response_model=NamedResp("Node", NodeResponse), operation_id="get_node")
async def get_node(
    node_id: int,
    user_id: int = Depends(get_current_user),
    db=Depends(get_db),
):
    from app.services.node import get_node as svc_get_node

    node = await svc_get_node(db, node_id)
    if node is None or node["user_id"] != user_id:
        return APIResponse.fail("Node not found", status=100)

    return APIResponse.ok(_node_to_response(node))


@router.put("", response_model=NamedResp("NodeCreate", NodeCreateResponse), operation_id="create_node")
async def create_new_node(
    user_id: int = Depends(get_current_user),
    db=Depends(get_db),
):
    await db.execute("BEGIN IMMEDIATE")
    try:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM node WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        count = row[0] if row else 0

        limit, _ = await get_effective_limits(db, user_id)
        if count >= limit:
            await db.rollback()
            return APIResponse.fail(f"Node limit reached ({limit})", status=1)

        cursor = await db.execute(
            "SELECT id, push_key FROM node WHERE user_id = ? AND reg_at IS NULL LIMIT 1",
            (user_id,),
        )
        existing = await cursor.fetchone()
        if existing:
            await db.commit()
            return APIResponse.ok(NodeCreateResponse(id=existing["id"], push_key=str(existing["push_key"])))

        node = await create_node(db, user_id)
        await db.commit()
        return APIResponse.ok(NodeCreateResponse(id=node["id"], push_key=str(node["push_key"])))
    except Exception:
        await db.rollback()
        raise


@router.post("", response_model=NamedResp("NodeRegister", RegisterNodePayload), operation_id="register_node")
async def register_smart_node(
    body: RegisterNodeRequest,
    db=Depends(get_db),
):
    if not body.push_key:
        return APIResponse.fail("push_key required", status=1)

    node = await register_node(
        db,
        body.push_key,
        body.hostname,
        body.host_os,
    )
    if node is None:
        return APIResponse.fail("Invalid push key", status=101)

    return APIResponse.ok(RegisterNodePayload(node_id=node["id"]))


@router.patch("/{node_id}", response_model=NamedResp("Node", NodeResponse), operation_id="update_node")
async def patch_node(
    node_id: int,
    body: NodeUpdateRequest,
    user_id: int = Depends(get_current_user),
    db=Depends(get_db),
):
    cursor = await db.execute(
        "SELECT id, user_id FROM node WHERE id = ?",
        (node_id,),
    )
    existing = await cursor.fetchone()
    if existing is None:
        return APIResponse.fail("Node not found", status=1)

    if existing["user_id"] != user_id:
        return APIResponse.fail("Forbidden", status=1)

    node = await update_node(
        db,
        node_id,
        hostname=body.hostname,
        host_os=body.host_os,
        tags=body.tags,
    )
    if node is None:
        return APIResponse.fail("Node not found", status=1)

    return APIResponse.ok(_node_to_response(node))


@router.delete("/{node_id}", response_model=Resp, operation_id="delete_node")
async def delete_node_endpoint(
    node_id: int,
    user_id: int = Depends(get_current_user),
    db=Depends(get_db),
):
    cursor = await db.execute(
        "SELECT * FROM node WHERE id = ?",
        (node_id,),
    )
    node = await cursor.fetchone()
    if node is None:
        return APIResponse.fail("Node not found", status=1)

    if node["user_id"] != user_id:
        return APIResponse.fail("Forbidden", status=1)

    await delete_node(db, node_id)
    return APIResponse.ok()


@router.get("/{node_id}/configs", response_model=NamedResp("NodeConfig", NodeConfigResponse), operation_id="get_node_config")
async def get_node_configs(
    node_id: int,
    _node: dict = Depends(get_current_node),
    db=Depends(get_db),
):
    config = await get_node_config(db, node_id)
    if config is None:
        return APIResponse.fail("Node not found", status=101)

    return APIResponse.ok(
        NodeConfigResponse(
            push_interval=config["push_interval"],
            push_raw=config["push_raw"],
            push_raw_plain=config["push_raw_plain"],
            device_limit=config["device_limit"],
            last_metrics_push=config["last_metrics_push"],
            server_time=config["server_time"],
        )
    )


@router.post("/{node_id}/devices", response_model=Resp, operation_id="register_devices")
async def register_node_devices(
    node_id: int,
    body: RegisterDevicesRequest,
    node: dict = Depends(get_current_node),
    db=Depends(get_db),
):
    devices = [d.model_dump() for d in body.devices]
    if not devices:
        return APIResponse.fail("No devices provided", status=1)
    if len(devices) > MAX_DEVICES_PER_PUSH:
        return APIResponse.fail("Too many devices in one push", status=201)

    _, device_limit = await get_effective_limits(db, node["user_id"])
    # Soft per-push limit by design: it bounds one request, not lifetime
    # registrations. The absolute cap above protects against giant payloads.
    if device_limit_exceeded(device_limit, len(devices)):
        return APIResponse.fail(f"Exceeds device limit ({device_limit})", status=201)

    await db.execute("BEGIN IMMEDIATE")
    try:
        results, metric_lines = await register_devices(db, node["user_id"], devices)
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    if metric_lines:
        # Best-effort, outside the SQLite write lock.
        await write_metrics_best_effort("\n".join(metric_lines), "initial metrics")

    return APIResponse.ok(results)


