import json
import re
from datetime import datetime, timezone
from typing import Any

from app.models.user import UserResponse


def parse_ts(val: Any) -> str | None:
    if val is None:
        return None
    return str(val)


def parse_json_array(raw: Any) -> list[Any] | None:
    if raw is None:
        return None
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
        return parsed if isinstance(parsed, list) else None
    return None


def parse_json_object(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def stringify_timestamps(row: dict[str, Any], *fields: str) -> dict[str, Any]:
    """Stringify SQLite timestamp columns consistently across formatters."""
    for field in fields:
        if row.get(field):
            row[field] = str(row[field])
    return row


def parse_utc_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def page_count(total: int, limit: int) -> int:
    return (total + limit - 1) // limit if total > 0 else 0


_USERNAME_WS_RE = re.compile(r"\s+")


def normalize_username(raw: str | None) -> str:
    """Canonical username form: trimmed, lowercased, whitespace -> "_".

    Deliberately lenient beyond that (no charset whitelist) so display
    names with accents/CJK survive. Raises ValueError when nothing remains.
    """
    if raw is None:
        raise ValueError("Invalid username")
    name = _USERNAME_WS_RE.sub("_", raw.strip().lower())
    if not name:
        raise ValueError("Invalid username")
    return name


def sort_direction(sort_order: str) -> str:
    return "DESC" if sort_order.lower() == "desc" else "ASC"


def paginate_offset(pnum: int, plimit: int) -> int:
    return (pnum - 1) * plimit


def device_limit_exceeded(device_limit: int, count: int) -> bool:
    """Soft limit check for one push payload (not lifetime registrations)."""
    return device_limit > 0 and count > device_limit


def build_user_response(
    user: dict[str, Any],
    node_limit: int | None = None,
    device_limit: int | None = None,
) -> UserResponse:
    return UserResponse(
        id=user["id"],
        username=user.get("username"),
        oauth_provider=user.get("oauth_provider"),
        node_limit=node_limit,
        node_device_limit=device_limit,
        status=user.get("status", 0),
        reg_at=str(user.get("reg_at", "")),
        has_password=bool(user.get("password_hash")),
    )
