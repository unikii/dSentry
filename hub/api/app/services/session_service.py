"""DB-backed login sessions.

JWTs are stateless, so revocation needs a server-side record: each token
carries a `jti` that maps to a row here. Logout revokes one session, a
password change revokes all of them. Expired rows are deleted lazily on
each login, which keeps the table bounded without a background job.
"""

import secrets
from datetime import datetime, timedelta, timezone

from aiosqlite import Connection

from app.config import settings
from app.services.auth import create_jwt


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def create_session(db: Connection, user_id: int) -> str:
    """Create a session row and return a JWT bound to it via `jti`."""
    session_id = secrets.token_urlsafe(24)
    expires = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    await db.execute("DELETE FROM sessions WHERE expires_at < ?", (_now(),))
    await db.execute(
        "INSERT INTO sessions (id, user_id, expires_at) VALUES (?, ?, ?)",
        (session_id, user_id, expires.isoformat()),
    )
    await db.commit()
    return create_jwt(user_id, session_id)


async def revoke_session(db: Connection, session_id: str) -> bool:
    cursor = await db.execute(
        "UPDATE sessions SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
        (_now(), session_id),
    )
    await db.commit()
    return cursor.rowcount > 0


async def revoke_all_sessions(db: Connection, user_id: int, except_session: str | None = None) -> None:
    """Revoke every live session of a user, optionally sparing one (the
    session that performed the revoking action, e.g. a password change)."""
    if except_session is None:
        await db.execute(
            "UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
            (_now(), user_id),
        )
    else:
        await db.execute(
            "UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL AND id != ?",
            (_now(), user_id, except_session),
        )
    await db.commit()
