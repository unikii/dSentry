import asyncio
import ipaddress
import logging
import re
import socket
from urllib.parse import parse_qs, urlencode, urlparse, urlsplit, urlunparse

import apprise
from aiosqlite import Connection

from app.config import settings
from app.constants import MAX_ENABLED_ALERTS, UNHANDLED_EVENT_TYPES
from app.utils import parse_utc_datetime, stringify_timestamps

logger = logging.getLogger("dsentry.alert")

EVENT_LABELS = {
    "device_smart_fail": "SMART Failure",
    "device_smart_success": "SMART Recovery",
    "device_threshold_warning": "Threshold Warning",
    "device_threshold_critical": "Threshold Critical",
    "device_missing": "Device Missing",
    "device_online": "Device Online",
}

VALID_ALERT_TYPES = {
    "email",
    "discord", "telegram", "slack", "google_chat", "matrix", "mattermost",
    "wechat_work", "dingtalk", "feishu",
    "pushover", "pushbullet", "ntfy", "gotify", "prowl",
    "generic_webhook", "ifttt", "msteams", "linenotify",
}

# Only accept the URL schemes belonging to the selected Apprise service.
# Apprise 2.x uses `wechat` for WeChat Work and `workflow` for MS Teams, and
# no longer provides the `wechatmp` or `faast` plugins.
# Generic webhooks use Apprise's JSON plugin; private-address validation and
# disabled redirects keep that user-controlled destination from becoming an
# SSRF primitive.
ALERT_SCHEMES = {
    "email": set(),
    "generic_webhook": {"json", "jsons"},
    "discord": {"discord"},
    "telegram": {"telegram", "tgram"},
    "slack": {"slack"},
    "ntfy": {"ntfy", "ntfys"},
    "gotify": {"gotify", "gotifys"},
    "pushover": {"pover"},
    "pushbullet": {"pbul"},
    "google_chat": {"gchat"},
    "matrix": {"matrix", "matrixs"},
    "mattermost": {"mmost", "mmosts"},
    "msteams": {"workflow", "workflows"},
    "wechat_work": {"wechat"},
    "dingtalk": {"dingtalk"},
    "feishu": {"feishu"},
    "prowl": {"prowl"},
    "ifttt": {"ifttt"},
    "linenotify": {"line"},
}

# These services put a user-controlled host in their Apprise URL. Private
# addresses are useful for self-hosted notifications, but must be an explicit
# operator choice rather than an accidental SSRF path on a public instance.
PRIVATE_TARGET_TYPES = {
    "generic_webhook", "msteams", "ntfy", "gotify", "matrix", "mattermost",
}
PRIVATE_HOSTNAMES = {"localhost", "localhost.localdomain", "ip6-localhost"}


# Deliberately pragmatic rather than RFC-complete: reject characters that can
# alter the Apprise query string, while still allowing plus-addressing.
_EMAIL_RE = re.compile(
    r"^[A-Za-z0-9._%+\-]+@"
    r"[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?)+$"
)
_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*$")

# Apprise follows HTTP redirects by default and re-sends credentials to the
# new origin. Alert destinations are user-controlled, so redirects are
# disabled globally rather than validated after the fact.
_APPRISE_ASSET = apprise.AppriseAsset(http_redirects=False)


def _apprise_client() -> apprise.Apprise:
    return apprise.Apprise(asset=_APPRISE_ASSET)


def _validate_alert_target(alert_type: str, alert_target: str) -> str:
    """Strip and validate an alert target before it reaches Apprise."""
    if alert_type not in VALID_ALERT_TYPES:
        raise ValueError(f"Invalid alert type: {alert_type}")

    target = (alert_target or "").strip()
    if not target:
        raise ValueError("Alert target must not be empty")

    if "://" in target:
        try:
            parsed = urlsplit(target)
            scheme = parsed.scheme.lower()
            host = parsed.hostname
        except ValueError as exc:
            raise ValueError("Invalid alert target URL") from exc

        if not _SCHEME_RE.match(scheme) or scheme not in ALERT_SCHEMES[alert_type]:
            allowed = ", ".join(sorted(ALERT_SCHEMES[alert_type]))
            raise ValueError(
                f"Unsupported URL scheme for {alert_type}; use {allowed or 'a plain value'}"
            )
        if alert_type in PRIVATE_TARGET_TYPES:
            # Matrix URLs carry the account credentials in the URL itself, so
            # allow them for that service only.
            _validate_network_target(
                parsed, host, allow_credentials=(alert_type == "matrix")
            )
        return target

    if alert_type == "email":
        if len(target) > 254 or not _EMAIL_RE.match(target):
            raise ValueError("Invalid email address — use user@example.com")
        return target

    raise ValueError(f"{alert_type} target must be a complete Apprise URL")


def _validate_network_target(
    parsed, host: str | None, *, allow_credentials: bool = False
) -> None:
    if not host:
        raise ValueError("Alert target must include a hostname")
    if not allow_credentials and (parsed.username or parsed.password):
        raise ValueError("Alert target must not include embedded credentials")
    if settings.alert_allow_private_targets:
        return

    normalized_host = host.rstrip(".").lower()
    if normalized_host in PRIVATE_HOSTNAMES or normalized_host.endswith((".localhost", ".local")):
        raise ValueError(
            "Private alert destinations are disabled; set ALERT_ALLOW_PRIVATE_TARGETS=true "
            "only for a trusted self-hosted target"
        )

    try:
        addresses = socket.getaddrinfo(normalized_host, None)
    except (OSError, UnicodeError):
        # Some Apprise URLs (e.g. ntfy://topic) use the host position for a
        # non-hostname token. If DNS cannot resolve it, Apprise cannot reach a
        # private address through it either, so leave validation to Apprise.
        return
    if not addresses:
        return

    private_message = (
        "Private alert destinations are disabled; set ALERT_ALLOW_PRIVATE_TARGETS=true "
        "only for a trusted self-hosted target"
    )
    for info in addresses:
        address_text = info[4][0]
        try:
            address = ipaddress.ip_address(address_text)
        except ValueError:
            continue
        if not address.is_global:
            raise ValueError(private_message)


async def _validate_alert_target_async(alert_type: str, alert_target: str) -> str:
    """Validation performs DNS lookups; keep them off the event loop."""
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_validate_alert_target, alert_type, alert_target),
            timeout=5.0,
        )
    except asyncio.TimeoutError as exc:
        raise ValueError("Alert target DNS lookup timed out") from exc


async def create_alert(
    db: Connection,
    user_id: int,
    alert_name: str | None,
    alert_type: str,
    alert_target: str,
) -> dict:
    if alert_type not in VALID_ALERT_TYPES:
        raise ValueError(f"Invalid alert type: {alert_type}")
    alert_target = await _validate_alert_target_async(alert_type, alert_target)

    cursor = await db.execute(
        "INSERT INTO user_alert (user_id, alert_name, alert_type, alert_target) "
        "VALUES (?, ?, ?, ?) RETURNING *",
        (user_id, alert_name, alert_type, alert_target),
    )
    row = await cursor.fetchone()
    await db.commit()
    return _format_alert(dict(row))


async def list_alerts(db: Connection, user_id: int) -> list[dict]:
    cursor = await db.execute(
        "SELECT * FROM user_alert WHERE user_id = ? ORDER BY add_at DESC, id DESC",
        (user_id,),
    )
    rows = await cursor.fetchall()
    return [_format_alert(dict(r)) for r in rows]


async def update_alert(
    db: Connection,
    alert_id: int,
    user_id: int,
    enabled: bool | None = None,
    alert_name: str | None = None,
    alert_target: str | None = None,
) -> dict | None:
    cursor = await db.execute(
        "SELECT * FROM user_alert WHERE id = ? AND user_id = ?",
        (alert_id, user_id),
    )
    existing_row = await cursor.fetchone()
    if existing_row is None:
        return None

    existing = dict(existing_row)

    if enabled is True:
        if existing["alert_type"] == "email":
            smtp_url = settings.smtp_url
            if not smtp_url:
                raise ValueError("SMTP_URL is not configured — email alerts unavailable")

    fields = []
    args = []

    if alert_name is not None:
        fields.append("alert_name = ?")
        args.append(alert_name)
    if alert_target is not None:
        alert_target = await _validate_alert_target_async(existing["alert_type"], alert_target)
        fields.append("alert_target = ?")
        args.append(alert_target)
    if enabled is not None:
        fields.append("enabled = ?")
        args.append(1 if enabled else 0)

    if not fields:
        return _format_alert(existing)

    fields.append("edit_at = datetime('now')")
    args.extend([alert_id, user_id])

    where = "id = ? AND user_id = ?"
    if enabled is True:
        # Check-and-enable in one statement: two concurrent enables cannot
        # both pass a separate COUNT check and produce a third enabled alert.
        where += (
            " AND (SELECT COUNT(*) FROM user_alert "
            "WHERE user_id = ? AND enabled = 1 AND id != ?) < ?"
        )
        args.extend([user_id, alert_id, MAX_ENABLED_ALERTS])

    cursor = await db.execute(
        f"UPDATE user_alert SET {', '.join(fields)} WHERE {where} RETURNING *",
        args,
    )
    row = await cursor.fetchone()
    await db.commit()
    if row is None:
        if enabled is True:
            raise ValueError(f"Maximum {MAX_ENABLED_ALERTS} enabled alert methods per user")
        return None
    return _format_alert(dict(row))


async def delete_alert(db: Connection, alert_id: int, user_id: int) -> bool:
    cursor = await db.execute(
        "DELETE FROM user_alert WHERE id = ? AND user_id = ? RETURNING id",
        (alert_id, user_id),
    )
    row = await cursor.fetchone()
    await db.commit()
    return row is not None


async def get_enabled_alerts_for_user(db: Connection, user_id: int) -> list[dict]:
    cursor = await db.execute(
        "SELECT * FROM user_alert WHERE user_id = ? AND enabled = 1",
        (user_id,),
    )
    rows = await cursor.fetchall()
    return [_format_alert(dict(r)) for r in rows]


async def insert_event(
    db: Connection,
    user_id: int,
    event_type: str,
    device_id: int | None = None,
    note: str | None = None,
    collected_at: str | None = None,
) -> dict:
    collected = parse_utc_datetime(collected_at)
    if collected is not None:
        cursor = await db.execute(
            "INSERT INTO events (user_id, event_type, device_id, note, add_at) "
            "VALUES (?, ?, ?, ?, ?) RETURNING *",
            (user_id, event_type, device_id, note, collected.isoformat()),
        )
    else:
        cursor = await db.execute(
            "INSERT INTO events (user_id, event_type, device_id, note) "
            "VALUES (?, ?, ?, ?) RETURNING *",
            (user_id, event_type, device_id, note),
        )
    row = await cursor.fetchone()
    result = dict(row)

    if device_id and event_type in UNHANDLED_EVENT_TYPES:
        # Recovery/online events must not paint a healthy disk as critical;
        # only failure/warning-type events leave the unacknowledged marker.
        # Scoped by user_id: device_id may come from a node payload, and a
        # node must never be able to touch another user's device. Use the
        # original collection time when the event was queued offline.
        if collected is not None:
            await db.execute(
                "UPDATE device SET last_event_at = ? WHERE id = ? AND user_id = ?",
                (collected.isoformat(), device_id, user_id),
            )
        else:
            await db.execute(
                "UPDATE device SET last_event_at = datetime('now') WHERE id = ? AND user_id = ?",
                (device_id, user_id),
            )

    return result


async def send_event_alerts(
    db: Connection,
    user_id: int,
    event_type: str,
    device_id: int | None = None,
    note: str | None = None,
    event_id: int | None = None,
) -> bool:
    """Deliver one event's alerts. Returns False only for a retryable failure."""
    alerts = await get_enabled_alerts_for_user(db, user_id)
    if not alerts:
        return True

    device_name = None
    if device_id:
        cursor = await db.execute(
            "SELECT model_name, serial_number FROM device WHERE id = ? AND user_id = ? AND archived = 0",
            (device_id, user_id),
        )
        dev = await cursor.fetchone()
        if dev:
            device_name = f"{dev['model_name']} ({dev['serial_number']})"

    label = EVENT_LABELS.get(event_type, event_type)
    title = f"dSentry: {label}"

    body_parts = []
    if device_name:
        body_parts.append(f"Device: {device_name}")
    if note:
        body_parts.append(f"Summary: {note}")
    body = "\n".join(body_parts) if body_parts else label

    apobj = _apprise_client()
    for n in alerts:
        url = await _build_apprise_url_async(n["alert_type"], n["alert_target"])
        if not url:
            logger.warning(
                f"Skipping {n['alert_type']} alert id={n['id']}: "
                "target is invalid or the required server configuration is missing"
            )
            continue
        try:
            # add() returns False for URLs Apprise cannot handle; None
            # (returned by some test doubles) means "accepted".
            if apobj.add(url) is False:
                logger.warning(f"Skipping alert id={n['id']}: Apprise rejected target URL")
        except Exception as e:
            logger.warning(f"Skipping alert id={n['id']}: {e}")

    if len(apobj) == 0:
        # No configured target is deliverable. Retrying cannot fix that, so
        # treat it as a permanent (non-retryable) outcome.
        logger.warning(f"No deliverable alerts for event {event_type} (user {user_id})")
        return True
    try:
        delivered = await asyncio.to_thread(apobj.notify, title=title, body=body)
    except Exception as e:
        logger.error(f"Failed to send alerts: {e}")
        return False
    if not delivered:
        logger.error(f"Alert delivery failed for event {event_type} (user {user_id})")
        return False
    if event_id:
        await db.execute(
            "UPDATE events SET alert_at = datetime('now') WHERE id = ?",
            (event_id,),
        )
        await db.commit()
    logger.info(f"Sent {len(apobj)} alert(s) for event {event_type}")
    return True


async def user_has_enabled_alerts(db: Connection, user_id: int) -> bool:
    cursor = await db.execute(
        "SELECT 1 FROM user_alert WHERE user_id = ? AND enabled = 1 LIMIT 1",
        (user_id,),
    )
    return await cursor.fetchone() is not None


async def enqueue_event_alert(
    db: Connection,
    user_id: int,
    event_id: int,
    event_type: str,
    device_id: int | None,
    note: str | None,
) -> None:
    """Persist alert delivery in the same transaction as its event."""
    await db.execute(
        "INSERT OR IGNORE INTO event_alert_queue "
        "(event_id, user_id, event_type, device_id, note) VALUES (?, ?, ?, ?, ?)",
        (event_id, user_id, event_type, device_id, note),
    )


# Attempts are spaced 1, 5, 15, 60, and 300 seconds apart, then given up on.
ALERT_RETRY_BACKOFF_SECONDS = (1, 5, 15, 60, 300)
ALERT_MAX_ATTEMPTS = len(ALERT_RETRY_BACKOFF_SECONDS) + 1


async def process_pending_event_alerts(
    db: Connection, *, event_id: int | None = None, limit: int = 10
) -> int:
    """Deliver due queued alerts. Returns the number of successful deliveries."""
    sql = (
        "SELECT id FROM event_alert_queue "
        "WHERE attempts < ? AND next_at <= datetime('now')"
    )
    args: list[object] = [ALERT_MAX_ATTEMPTS]
    if event_id is not None:
        sql += " AND event_id = ?"
        args.append(event_id)
    sql += " ORDER BY id LIMIT ?"
    args.append(limit)

    cursor = await db.execute(sql, args)
    candidates = [int(row["id"]) for row in await cursor.fetchall()]
    delivered_count = 0

    for queue_id in candidates:
        # Claim atomically so the immediate background task and the periodic
        # retry worker cannot both send the same alert.
        claim = await db.execute(
            "UPDATE event_alert_queue "
            "SET next_at = datetime('now', '+10 minutes') "
            "WHERE id = ? AND attempts < ? AND next_at <= datetime('now') "
            "RETURNING *",
            (queue_id, ALERT_MAX_ATTEMPTS),
        )
        row = await claim.fetchone()
        await db.commit()
        if row is None:
            continue

        item = dict(row)
        try:
            ok = await send_event_alerts(
                db,
                item["user_id"],
                item["event_type"],
                device_id=item["device_id"],
                note=item["note"],
                event_id=item["event_id"],
            )
        except Exception as exc:
            logger.exception("Alert delivery raised for event %s", item["event_id"])
            ok = False
            item["last_error"] = str(exc)

        if ok:
            await db.execute(
                "DELETE FROM event_alert_queue WHERE id = ?", (queue_id,)
            )
            await db.commit()
            delivered_count += 1
            continue

        attempts = int(item["attempts"]) + 1
        if attempts >= ALERT_MAX_ATTEMPTS:
            logger.error(
                "Giving up on alert for event %s after %d attempts",
                item["event_id"],
                attempts,
            )
            await db.execute(
                "DELETE FROM event_alert_queue WHERE id = ?", (queue_id,)
            )
        else:
            delay = ALERT_RETRY_BACKOFF_SECONDS[attempts - 1]
            await db.execute(
                "UPDATE event_alert_queue "
                "SET attempts = ?, next_at = datetime('now', ?), last_error = ? "
                "WHERE id = ?",
                (
                    attempts,
                    f"+{delay} seconds",
                    item.get("last_error") or "delivery failed",
                    queue_id,
                ),
            )
        await db.commit()

    return delivered_count


async def send_test_alert(
    db: Connection,
    alert_id: int,
    user_id: int,
) -> bool:
    cursor = await db.execute(
        "SELECT * FROM user_alert WHERE id = ? AND user_id = ?",
        (alert_id, user_id),
    )
    row = await cursor.fetchone()
    if row is None:
        return False

    n = _format_alert(dict(row))
    url = await _build_apprise_url_async(n["alert_type"], n["alert_target"])
    if not url:
        return False

    apobj = _apprise_client()
    try:
        if apobj.add(url) is False:
            logger.error(f"Test alert {alert_id}: Apprise rejected target URL")
            return False
    except Exception as e:
        logger.error(f"Test alert failed: {e}")
        return False

    try:
        delivered = await asyncio.to_thread(
            apobj.notify,
            title="dSentry: Test Alert",
            body="This is a test alert from dSentry. If you see this, your alert method is configured correctly.",
        )
        if not delivered:
            logger.error(f"Test alert {alert_id}: delivery failed")
            return False
        return True
    except Exception as e:
        logger.error(f"Test alert failed: {e}")
        return False


async def _build_apprise_url_async(alert_type: str, alert_target: str) -> str:
    """Build a URL without blocking the event loop on DNS validation."""
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_build_apprise_url, alert_type, alert_target),
            timeout=5.0,
        )
    except asyncio.TimeoutError:
        logger.warning("Skipping %s alert target: DNS lookup timed out", alert_type)
        return ""


def _build_apprise_url(alert_type: str, alert_target: str) -> str:
    try:
        target = _validate_alert_target(alert_type, alert_target)
    except ValueError as exc:
        logger.warning("Skipping invalid %s alert target: %s", alert_type, exc)
        return ""

    if alert_type == "email":
        smtp_url = settings.smtp_url
        if not smtp_url:
            return ""

        parsed = urlparse(smtp_url)
        # Preserve every operator-supplied parameter and encode the recipient
        # as a single value. Concatenating it raw would let an address such as
        # `user@example.com&smtp=attacker` override the SMTP host.
        params = parse_qs(parsed.query, keep_blank_values=True)
        params["to"] = [target]
        query = urlencode(params, doseq=True)
        return urlunparse(parsed._replace(query=query))

    if "://" in target:
        # Force the per-URL redirect policy too. Apprise lets a URL override
        # the asset default, so a stored target containing `redirect=yes`
        # must not be able to re-enable redirects.
        parsed = urlparse(target)
        params = parse_qs(parsed.query, keep_blank_values=True)
        params["redirect"] = ["no"]
        query = urlencode(params, doseq=True)
        return urlunparse(parsed._replace(query=query))

    return target


def _format_alert(row: dict) -> dict:
    return stringify_timestamps(row, "add_at", "edit_at")
