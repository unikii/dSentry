import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

from aiosqlite import Connection

from app.config import settings
from app.utils import paginate_offset, parse_utc_datetime, sort_direction

logger = logging.getLogger("dsentry.node")


async def get_effective_limits(db: Connection, user_id: int) -> tuple[int, int]:
    cursor = await db.execute(
        "SELECT node_limit, node_device_limit FROM users WHERE id = ?",
        (user_id,),
    )
    row = await cursor.fetchone()
    node_limit = settings.global_node_per_user
    device_limit = settings.global_device_per_node
    if row:
        if row[0] is not None:
            node_limit = row[0]
        if row[1] is not None:
            device_limit = row[1]
    return node_limit, device_limit


async def create_node(db: Connection, user_id: int) -> dict:
    push_key = str(uuid.uuid4())
    cursor = await db.execute(
        "INSERT INTO node (user_id, push_key) VALUES (?, ?) RETURNING id, push_key",
        (user_id, push_key),
    )
    row = await cursor.fetchone()
    return dict(row)


async def get_node(db: Connection, node_id: int) -> dict | None:
    cursor = await db.execute("SELECT * FROM node WHERE id = ?", (node_id,))
    row = await cursor.fetchone()
    return dict(row) if row else None


_ALLOWED_NODE_SORT_COLUMNS = {
    "reg_at": "reg_at",
    "last_metrics_push": "last_metrics_push",
}


async def list_nodes(
    db: Connection,
    user_id: int,
    plimit: int = 50,
    pnum: int = 1,
    keyword: str | None = None,
    sort_by: str = "reg_at",
    sort_order: str = "desc",
) -> tuple[list[dict], int]:
    offset = paginate_offset(pnum, plimit)
    conditions = ["user_id = ?", "reg_at IS NOT NULL"]
    params: list = [user_id]

    if keyword:
        kw = f"%{keyword}%"
        conditions.append("(hostname LIKE ? OR tags LIKE ?)")
        params.extend([kw, kw])

    where = " AND ".join(conditions)

    cursor = await db.execute(
        f"SELECT COUNT(*) FROM node WHERE {where}",
        params,
    )
    row = await cursor.fetchone()
    total = row[0] if row else 0

    # Sort column comes from a whitelist, never from raw user input.
    sort_column = _ALLOWED_NODE_SORT_COLUMNS.get(sort_by, "reg_at")
    direction = sort_direction(sort_order)

    cursor = await db.execute(
        f"SELECT * FROM node WHERE {where} "
        f"ORDER BY {sort_column} {direction} LIMIT ? OFFSET ?",
        params + [plimit, offset],
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows], total


async def register_node(
    db: Connection,
    push_key: str,
    hostname: str | None,
    host_os: str | None,
) -> dict | None:
    await db.execute("BEGIN IMMEDIATE")
    try:
        cursor = await db.execute(
            "SELECT id, reg_at FROM node WHERE push_key = ?",
            (push_key,),
        )
        existing = await cursor.fetchone()
        if existing is None:
            await db.rollback()
            return None

        now = datetime.now(timezone.utc).isoformat()
        if existing["reg_at"] is None:
            # First registration stamps reg_at.
            cursor = await db.execute(
                "UPDATE node SET hostname = ?, host_os = ?, reg_at = ? WHERE id = ? "
                "RETURNING id, user_id, push_key, hostname, host_os, reg_at",
                (hostname, host_os, now, existing["id"]),
            )
        else:
            # Idempotent re-registration: the node keeps its identity (and
            # devices) when only its endpoint or state file changed. Refresh
            # the reported host details but keep the original reg_at.
            cursor = await db.execute(
                "UPDATE node SET hostname = ?, host_os = ? WHERE id = ? "
                "RETURNING id, user_id, push_key, hostname, host_os, reg_at",
                (hostname, host_os, existing["id"]),
            )
        row = await cursor.fetchone()
        await db.commit()
        return dict(row) if row else None
    except Exception:
        await db.rollback()
        raise


async def update_node(
    db: Connection,
    node_id: int,
    hostname: str | None = None,
    host_os: str | None = None,
    tags: list[str] | None = None,
) -> dict | None:
    fields = []
    args = []

    if hostname is not None:
        fields.append("hostname = ?")
        args.append(hostname)
    if host_os is not None:
        fields.append("host_os = ?")
        args.append(host_os)
    if tags is not None:
        fields.append("tags = ?")
        # ensure_ascii=False: keep non-ASCII tags as raw UTF-8, same as devices.
        args.append(json.dumps(tags, ensure_ascii=False))

    if not fields:
        cursor = await db.execute("SELECT * FROM node WHERE id = ?", (node_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

    args.append(node_id)
    query = f"UPDATE node SET {', '.join(fields)} WHERE id = ? RETURNING *"
    cursor = await db.execute(query, args)
    row = await cursor.fetchone()
    await db.commit()
    return dict(row) if row else None


async def delete_node(db: Connection, node_id: int) -> bool:
    cursor = await db.execute(
        "DELETE FROM node WHERE id = ? RETURNING id", (node_id,)
    )
    row = await cursor.fetchone()
    await db.commit()
    return row is not None


async def delete_user_cascade(db: Connection, user_id: int) -> dict[str, int]:
    cursor = await db.execute("SELECT COUNT(*) FROM node WHERE user_id = ?", (user_id,))
    nodes_deleted = (await cursor.fetchone())[0]

    cursor = await db.execute("SELECT COUNT(*) FROM device WHERE user_id = ?", (user_id,))
    devices_deleted = (await cursor.fetchone())[0]

    cursor = await db.execute("SELECT COUNT(*) FROM events WHERE user_id = ?", (user_id,))
    events_deleted = (await cursor.fetchone())[0]

    cursor = await db.execute("SELECT COUNT(*) FROM device_raw WHERE device_id IN (SELECT id FROM device WHERE user_id = ?)", (user_id,))
    raws_deleted = (await cursor.fetchone())[0]

    cursor = await db.execute("SELECT COUNT(*) FROM user_alert WHERE user_id = ?", (user_id,))
    alerts_deleted = (await cursor.fetchone())[0]

    await db.execute("DELETE FROM device_raw WHERE device_id IN (SELECT id FROM device WHERE user_id = ?)", (user_id,))
    await db.execute("DELETE FROM event_alert_queue WHERE user_id = ?", (user_id,))
    await db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    await db.execute("DELETE FROM events WHERE user_id = ?", (user_id,))
    await db.execute("DELETE FROM device WHERE user_id = ?", (user_id,))
    await db.execute("DELETE FROM node WHERE user_id = ?", (user_id,))
    await db.execute("DELETE FROM user_alert WHERE user_id = ?", (user_id,))
    await db.execute("DELETE FROM users WHERE id = ?", (user_id,))

    return {
        "nodes_deleted": nodes_deleted,
        "devices_deleted": devices_deleted,
        "raws_deleted": raws_deleted,
        "events_deleted": events_deleted,
        "alerts_deleted": alerts_deleted,
    }


def compute_push_raw(
    node: dict,
    now: datetime | None = None,
) -> bool:
    if now is None:
        now = datetime.now(timezone.utc)

    base = settings.global_raw_push_base.lower()
    if base == "never":
        return False

    freq = settings.global_raw_push_freq
    if freq <= 0:
        freq = 1

    last_raw_dt = parse_utc_datetime(node.get("last_raw_push"))

    if last_raw_dt is None:
        return True

    if base == "day":
        return (last_raw_dt + timedelta(days=freq)) < now
    elif base == "push":
        return (last_raw_dt + timedelta(minutes=settings.global_push_interval * freq)) < now

    logger.warning("Unknown GLOBAL_RAW_PUSH_BASE value '%s', defaulting to never push raw", base)
    return False


async def get_node_config(db: Connection, node_id: int) -> dict | None:
    cursor = await db.execute("SELECT * FROM node WHERE id = ?", (node_id,))
    row = await cursor.fetchone()
    if row is None:
        return None

    node = dict(row)
    push_raw = compute_push_raw(node)
    _, device_limit = await get_effective_limits(db, node["user_id"])

    last_metrics_push = node.get("last_metrics_push")
    if last_metrics_push:
        parsed = parse_utc_datetime(last_metrics_push)
        last_metrics_push = parsed.isoformat() if parsed else None

    return {
        "push_interval": settings.global_push_interval,
        "push_raw": push_raw,
        "push_raw_plain": settings.global_raw_push_plain,
        "device_limit": device_limit,
        "last_metrics_push": last_metrics_push,
        "server_time": datetime.now(timezone.utc).isoformat(),
    }
