from aiosqlite import Connection


async def list_events(
    db: Connection,
    user_id: int,
    plimit: int = 50,
    pnum: int = 1,
) -> tuple[list[dict], int]:
    offset = (pnum - 1) * plimit
    cursor = await db.execute(
        "SELECT COUNT(*) FROM events WHERE user_id = ?",
        (user_id,),
    )
    row = await cursor.fetchone()
    total = row[0] if row else 0

    cursor = await db.execute(
        "SELECT e.*, d.model_name AS device_name "
        "FROM events e "
        "LEFT JOIN device d ON e.device_id = d.id "
        "WHERE e.user_id = ? "
        "ORDER BY datetime(e.add_at) DESC, e.id DESC LIMIT ? OFFSET ?",
        (user_id, plimit, offset),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows], total


async def act_on_event(db: Connection, event_id: int, user_id: int) -> bool:
    cursor = await db.execute(
        "UPDATE events SET act_at = datetime('now') WHERE id = ? AND user_id = ? AND act_at IS NULL RETURNING id",
        (event_id, user_id),
    )
    row = await cursor.fetchone()
    await db.commit()
    return row is not None
