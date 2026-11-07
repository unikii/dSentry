from datetime import datetime, timezone

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.database import open_db
from app.services.auth import decode_jwt
from app.utils import parse_utc_datetime

bearer_scheme = HTTPBearer(auto_error=False)


async def get_db():
    async with open_db() as db:
        yield db


async def _authenticate(
    credentials: HTTPAuthorizationCredentials | None,
    db,
) -> tuple[int, str]:
    """Validate a bearer token and its session row; returns (user_id, jti)."""
    if credentials is None:
        raise HTTPException(status_code=401, detail="Missing authorization token")

    try:
        payload = decode_jwt(credentials.credentials)
        user_id = int(payload["sub"])
        session_id = payload.get("jti", "")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    if not session_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    cursor = await db.execute(
        "SELECT user_id, expires_at, revoked_at FROM sessions WHERE id = ?",
        (session_id,),
    )
    row = await cursor.fetchone()
    if row is None or row["revoked_at"] is not None:
        raise HTTPException(status_code=401, detail="Session is no longer valid")
    if row["user_id"] != user_id:
        raise HTTPException(status_code=401, detail="Session is no longer valid")
    expires = parse_utc_datetime(row["expires_at"])
    if expires is None or expires <= datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Session is no longer valid")

    cursor = await db.execute("SELECT id, status FROM users WHERE id = ?", (user_id,))
    row = await cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="User not found")
    if row["status"] != 0:
        raise HTTPException(status_code=403, detail="Account is disabled")

    return user_id, session_id


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db=Depends(get_db),
) -> int:
    user_id, _ = await _authenticate(credentials, db)
    return user_id


async def get_current_session(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db=Depends(get_db),
) -> tuple[int, str]:
    """Like get_current_user, but also returns the session id (jti), for
    routes that act on the session itself (logout, password change)."""
    return await _authenticate(credentials, db)


async def get_current_node(
    node_id: int,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db=Depends(get_db),
) -> dict:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Missing authorization token")

    push_key = credentials.credentials

    node = await db.execute(
        "SELECT n.id, n.user_id, n.push_key, n.reg_at, n.last_metrics_push, "
        "n.last_raw_push, u.status AS user_status FROM node n "
        "JOIN users u ON u.id = n.user_id "
        "WHERE n.push_key = ?",
        (push_key,),
    )
    row = await node.fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="Invalid push key")

    node_dict = dict(row)
    if node_dict["id"] != node_id:
        raise HTTPException(status_code=401, detail="Node ID mismatch")
    if node_dict.get("user_status", 0) != 0:
        raise HTTPException(status_code=403, detail="Account is disabled")

    return node_dict
