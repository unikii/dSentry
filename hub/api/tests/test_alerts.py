"""CRUD, validation, and sending for the /alerts endpoints."""

from urllib.parse import parse_qs, urlsplit

import pytest
from httpx import AsyncClient

from app.database import open_db
from app.services.alerts import _build_apprise_url, _validate_alert_target


async def _create(
    client: AsyncClient,
    headers: dict,
    alert_type: str = "generic_webhook",
    target: str = "json://example.com/hook",
    name: str | None = "hook-1",
) -> dict:
    resp = await client.post(
        "/alerts",
        json={"alert_type": alert_type, "alert_target": target, "alert_name": name},
        headers=headers,
    )
    body = resp.json()
    assert body["status"] == 0, body
    return body["payload"]


async def _delete(client: AsyncClient, headers: dict, alert_id: int) -> None:
    body = (await client.delete(f"/alerts/{alert_id}", headers=headers)).json()
    assert body["status"] == 0, body


async def test_alert_crud(client: AsyncClient, auth_headers: dict):
    created = await _create(client, auth_headers)
    assert created["alert_type"] == "generic_webhook"
    assert created["alert_target"] == "json://example.com/hook"
    assert created["enabled"] is False

    listed = (await client.get("/alerts", headers=auth_headers)).json()
    assert listed["status"] == 0
    assert any(a["id"] == created["id"] for a in listed["payload"])

    updated = (
        await client.patch(
            f"/alerts/{created['id']}",
            json={"enabled": True, "alert_name": "renamed"},
            headers=auth_headers,
        )
    ).json()
    assert updated["status"] == 0, updated
    assert updated["payload"]["enabled"] is True
    assert updated["payload"]["alert_name"] == "renamed"

    await _delete(client, auth_headers, created["id"])
    body = (await client.delete(f"/alerts/{created['id']}", headers=auth_headers)).json()
    assert body["status"] == 1
    assert "not found" in body["message"]


async def test_alert_rejects_invalid_type(client: AsyncClient, auth_headers: dict):
    body = (
        await client.post(
            "/alerts",
            json={"alert_type": "pigeon", "alert_target": "x"},
            headers=auth_headers,
        )
    ).json()
    assert body["status"] == 1
    assert "Invalid alert type" in body["message"]


async def test_alert_rejects_invalid_target(client: AsyncClient, auth_headers: dict):
    bad = [
        ("email", "not-an-email"),
        ("email", "   "),
        ("generic_webhook", "not-a-url"),
        ("generic_webhook", "json://127.0.0.1/hook"),
        ("generic_webhook", "http://127.0.0.1/hook"),
        ("generic_webhook", "ftp://example.com/hook"),
        ("discord", "https://example.com/hook"),
        ("gotify", "gotify://127.0.0.1/token"),
        ("email", "mailto://user:pass@127.0.0.1"),
        ("sms", "abc"),
        ("ntfy", ""),
    ]
    for alert_type, target in bad:
        body = (
            await client.post(
                "/alerts",
                json={"alert_type": alert_type, "alert_target": target},
                headers=auth_headers,
            )
        ).json()
        assert body["status"] == 1, (alert_type, target, body)
    # whitespace is stripped
    created = await _create(
        client, auth_headers, alert_type="email",
        target="  someone@example.com  ", name="mail-ws",
    )
    try:
        assert created["alert_target"] == "someone@example.com"
    finally:
        await _delete(client, auth_headers, created["id"])


def test_private_alert_targets_require_explicit_opt_in(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "alert_allow_private_targets", False)
    with pytest.raises(ValueError, match="Private alert destinations"):
        _validate_alert_target("gotify", "gotify://127.0.0.1/token")

    # MS Teams workflow URLs also carry a user-controlled host: Apprise builds
    # https://{host}/workflows/{id}/... from it, so they must be covered by the
    # same private-network check as the other target types.
    with pytest.raises(ValueError, match="Private alert destinations"):
        _validate_alert_target(
            "msteams", "workflow://127.0.0.1:8443/workflows/ABC/signature"
        )
    with pytest.raises(ValueError, match="Private alert destinations"):
        _validate_alert_target(
            "msteams", "workflows://localhost/workflows/ABC/signature"
        )

    monkeypatch.setattr(settings, "alert_allow_private_targets", True)
    assert _validate_alert_target("gotify", "gotify://127.0.0.1/token")
    assert _validate_alert_target(
        "msteams", "workflow://127.0.0.1:8443/workflows/ABC/signature"
    )


def test_invalid_stored_alert_targets_are_not_sent(monkeypatch):
    monkeypatch.setattr("app.services.alerts.settings.alert_allow_private_targets", False)
    assert _build_apprise_url("generic_webhook", "json://127.0.0.1/hook") == ""


def test_dns_resolved_private_targets_are_rejected(monkeypatch):
    from app.config import settings
    import app.services.alerts as alerts

    monkeypatch.setattr(settings, "alert_allow_private_targets", False)
    monkeypatch.setattr(
        alerts.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("127.0.0.1", 0))],
    )
    with pytest.raises(ValueError, match="Private alert destinations"):
        _validate_alert_target("generic_webhook", "json://internal.example/hook")


def test_matrix_credentials_are_allowed(monkeypatch):
    from app.config import settings
    import app.services.alerts as alerts

    monkeypatch.setattr(settings, "alert_allow_private_targets", False)
    monkeypatch.setattr(
        alerts.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("93.184.216.34", 0))],
    )
    assert _validate_alert_target(
        "matrix", "matrix://user:pass@matrix.example/#room"
    )


async def test_alert_update_rejects_invalid_target(
    client: AsyncClient, auth_headers: dict
):
    created = await _create(client, auth_headers)
    try:
        body = (
            await client.patch(
                f"/alerts/{created['id']}",
                json={"alert_target": "not-a-url"},
                headers=auth_headers,
            )
        ).json()
        assert body["status"] == 1, body
    finally:
        await _delete(client, auth_headers, created["id"])


async def test_alert_email_enable_requires_smtp(client: AsyncClient, auth_headers: dict):
    created = await _create(
        client, auth_headers, alert_type="email", target="someone@example.com", name="mail"
    )
    try:
        body = (
            await client.patch(
                f"/alerts/{created['id']}", json={"enabled": True}, headers=auth_headers
            )
        ).json()
        assert body["status"] == 1
        assert "SMTP_URL" in body["message"]
    finally:
        await _delete(client, auth_headers, created["id"])


async def test_alert_enable_limit(client: AsyncClient, auth_headers: dict):
    ids = []
    try:
        for i in range(3):
            a = await _create(
                client, auth_headers, target=f"json://example.com/hook-{i}", name=f"h{i}"
            )
            ids.append(a["id"])
        for alert_id in ids[:2]:
            body = (
                await client.patch(
                    f"/alerts/{alert_id}", json={"enabled": True}, headers=auth_headers
                )
            ).json()
            assert body["status"] == 0, body
        body = (
            await client.patch(
                f"/alerts/{ids[2]}", json={"enabled": True}, headers=auth_headers
            )
        ).json()
        assert body["status"] == 1
        assert "Maximum 2" in body["message"]
    finally:
        for alert_id in ids:
            await client.delete(f"/alerts/{alert_id}", headers=auth_headers)


class _FakeApprise:
    instances: list["_FakeApprise"] = []

    def __init__(self, *args, **kwargs):
        self.urls: list[str] = []
        _FakeApprise.instances.append(self)

    def add(self, url: str) -> None:
        self.urls.append(url)

    def __len__(self) -> int:
        return len(self.urls)

    def notify(self, title: str = "", body: str = "") -> bool:
        return True


@pytest.fixture
def fake_apprise(monkeypatch):
    _FakeApprise.instances.clear()
    monkeypatch.setattr("app.services.alerts.apprise.Apprise", _FakeApprise)
    return _FakeApprise


class _FailingApprise(_FakeApprise):
    def notify(self, title: str = "", body: str = "") -> bool:
        return False


@pytest.fixture
def failing_apprise(monkeypatch):
    _FailingApprise.instances.clear()
    monkeypatch.setattr("app.services.alerts.apprise.Apprise", _FailingApprise)
    return _FailingApprise


async def test_test_alert_endpoint(
    client: AsyncClient, auth_headers: dict, fake_apprise
):
    created = await _create(client, auth_headers)
    try:
        body = (
            await client.post(f"/alerts/{created['id']}/test", headers=auth_headers)
        ).json()
        assert body["status"] == 0, body
        assert fake_apprise.instances and fake_apprise.instances[-1].urls
    finally:
        await _delete(client, auth_headers, created["id"])

    body = (await client.post("/alerts/999999/test", headers=auth_headers)).json()
    assert body["status"] == 1


async def test_test_alert_reports_delivery_failure(
    client: AsyncClient, auth_headers: dict, failing_apprise
):
    created = await _create(client, auth_headers)
    try:
        body = (
            await client.post(f"/alerts/{created['id']}/test", headers=auth_headers)
        ).json()
        assert body["status"] == 1, body
    finally:
        await _delete(client, auth_headers, created["id"])


async def test_send_event_alerts_skips_alert_at_on_failure(
    client: AsyncClient, auth_headers: dict, failing_apprise
):
    from app.services.alerts import insert_event, send_event_alerts

    async with open_db() as db:
        cursor = await db.execute("SELECT id FROM users WHERE username = 'admin'")
        admin_id = (await cursor.fetchone())[0]

    created = await _create(client, auth_headers)
    try:
        body = (
            await client.patch(
                f"/alerts/{created['id']}", json={"enabled": True}, headers=auth_headers
            )
        ).json()
        assert body["status"] == 0, body
        async with open_db() as db:
            event = await insert_event(db, admin_id, "device_smart_fail", note="disk bad")
            await db.commit()
            await send_event_alerts(
                db, admin_id, "device_smart_fail", note="disk bad", event_id=event["id"]
            )
            cursor = await db.execute(
                "SELECT alert_at FROM events WHERE id = ?", (event["id"],)
            )
            assert (await cursor.fetchone())[0] is None
            await db.execute("DELETE FROM events WHERE id = ?", (event["id"],))
            await db.commit()
    finally:
        await _delete(client, auth_headers, created["id"])

    body = (await client.post("/alerts/999999/test", headers=auth_headers)).json()
    assert body["status"] == 1


async def test_send_event_alerts_sets_alert_at(
    client: AsyncClient, auth_headers: dict, fake_apprise
):
    from app.services.alerts import insert_event, send_event_alerts

    async with open_db() as db:
        cursor = await db.execute("SELECT id FROM users WHERE username = 'admin'")
        admin_id = (await cursor.fetchone())[0]

    created = await _create(client, auth_headers)
    try:
        body = (
            await client.patch(
                f"/alerts/{created['id']}", json={"enabled": True}, headers=auth_headers
            )
        ).json()
        assert body["status"] == 0, body
        async with open_db() as db:
            event = await insert_event(db, admin_id, "device_smart_fail", note="disk bad")
            await send_event_alerts(
                db, admin_id, "device_smart_fail", note="disk bad", event_id=event["id"]
            )
            cursor = await db.execute(
                "SELECT alert_at FROM events WHERE id = ?", (event["id"],)
            )
            alert_at = (await cursor.fetchone())[0]
            assert alert_at, "alert_at should be stamped after sending"
            await db.execute("DELETE FROM events WHERE id = ?", (event["id"],))
            await db.commit()
    finally:
        await _delete(client, auth_headers, created["id"])


def test_email_recipient_is_encoded_and_cannot_inject_options(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(
        settings,
        "smtp_url",
        "mailto://alert-user:placeholder@smtp.example.com?mode=starttls",
    )

    url = _build_apprise_url("email", "user+tag@example.com")
    query = parse_qs(urlsplit(url).query)
    assert query["to"] == ["user+tag@example.com"]
    assert query["mode"] == ["starttls"]

    with pytest.raises(ValueError, match="Invalid email address"):
        _validate_alert_target(
            "email", "user@example.com&smtp=attacker.example.com&mode=insecure"
        )


def test_generic_webhook_requires_json_scheme(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "alert_allow_private_targets", True)
    assert (
        _validate_alert_target("generic_webhook", "json://example.com/hook")
        == "json://example.com/hook"
    )
    with pytest.raises(ValueError, match="Unsupported URL scheme"):
        _validate_alert_target("generic_webhook", "https://example.com/hook")


def test_webhook_url_cannot_reenable_redirects():
    url = _build_apprise_url(
        "generic_webhook", "json://example.com/hook?redirect=yes&x=1"
    )
    query = parse_qs(urlsplit(url).query)
    assert query["redirect"] == ["no"]
    assert query["x"] == ["1"]


# One representative, Apprise-valid target per declared alert type. If a type
# is added or an Apprise upgrade drops a plugin, this mapping and the test
# below force the mismatch to be handled explicitly.
ALERT_TYPE_TARGETS = {
    "email": "user@example.com",
    "discord": "discord://123456789012345678/abcdefghijklmnop",
    "telegram": "tgram://123456:ABCDEF/123456789",
    "slack": "slack://tokenA/tokenB/tokenC/#general",
    "google_chat": "gchat://workspace/key/token",
    "matrix": "matrix://user:pass@matrix.example/#room",
    "mattermost": "mmost://mattermost.example/token",
    "wechat_work": "wechat://corpid:corpsecret@1000002",
    "dingtalk": "dingtalk://token/123456789",
    "feishu": "feishu://token",
    "pushover": "pover://user@token",
    "pushbullet": "pbul://accesstoken",
    "ntfy": "ntfy://topic",
    "gotify": "gotify://gotify.example/token",
    "prowl": "prowl://" + "a" * 40,
    "generic_webhook": "json://example.com/hook",
    "ifttt": "ifttt://webhook_key/event",
    "msteams": "workflow://example.webhook.office.com/webhookb2/abc/DEF",
    "linenotify": "line://token",
}


def test_declared_alert_types_are_supported_by_installed_apprise(monkeypatch):
    import app.services.alerts as alerts
    from app.config import settings

    monkeypatch.setattr(settings, "alert_allow_private_targets", True)
    monkeypatch.setattr(
        settings,
        "smtp_url",
        "mailto://alert-user:placeholder@smtp.example.com?mode=starttls",
    )

    assert set(ALERT_TYPE_TARGETS) == alerts.VALID_ALERT_TYPES
    for alert_type, target in ALERT_TYPE_TARGETS.items():
        url = _build_apprise_url(alert_type, target)
        assert url, alert_type
        assert alerts._apprise_client().add(url), (alert_type, url)


@pytest.mark.parametrize(
    ("alert_type", "target"),
    [
        ("faast", "faast://authorizationtoken"),
        ("wechat_mp", "wechatmp://appid/appsecret"),
        ("wechat_work", "wxwork://corpid/corpsecret/1000002"),
        ("msteams", "msteams://tokenA/tokenB/tokenC"),
    ],
)
def test_removed_alert_types_and_schemes_are_rejected(alert_type, target):
    with pytest.raises(ValueError, match="Invalid alert type|Unsupported URL scheme"):
        _validate_alert_target(alert_type, target)


@pytest.mark.parametrize(
    ("alert_type", "target"),
    [("sms", "+15551234567"), ("web_push", "https://push.example.com/endpoint")],
)
def test_unsupported_alert_types_are_rejected(alert_type, target):
    with pytest.raises(ValueError, match="Invalid alert type"):
        _validate_alert_target(alert_type, target)


def test_apprise_redirects_are_disabled(monkeypatch):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    import app.services.alerts as alerts
    from app.config import settings

    monkeypatch.setattr(settings, "alert_allow_private_targets", True)
    hits: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def _redirect(self):
            hits.append(self.path)
            self.send_response(302)
            self.send_header("Location", "/sink")
            self.end_headers()

        do_GET = _redirect
        do_POST = _redirect

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = alerts._build_apprise_url(
            "generic_webhook",
            f"json://127.0.0.1:{server.server_port}/hook?rto=1&cto=1",
        )
        assert "redirect=no" in url
        client = alerts._apprise_client()
        assert client.add(url)
        client.notify(title="review", body="redirect check")
        assert "/hook" in hits
        assert "/sink" not in hits
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


async def test_queued_alert_is_retried_and_deleted_after_success(
    client: AsyncClient, auth_headers: dict, failing_apprise, monkeypatch
):
    import app.services.alerts as alerts
    from app.services.alerts import (
        enqueue_event_alert,
        insert_event,
        process_pending_event_alerts,
    )

    async with open_db() as db:
        cursor = await db.execute("SELECT id FROM users WHERE username = 'admin'")
        admin_id = (await cursor.fetchone())[0]

    created = await _create(client, auth_headers)
    try:
        body = (
            await client.patch(
                f"/alerts/{created['id']}", json={"enabled": True}, headers=auth_headers
            )
        ).json()
        assert body["status"] == 0, body

        async with open_db() as db:
            event = await insert_event(
                db, admin_id, "device_smart_fail", note="disk bad"
            )
            await enqueue_event_alert(
                db, admin_id, event["id"], "device_smart_fail", None, "disk bad"
            )
            await db.commit()

            delivered = await process_pending_event_alerts(
                db, event_id=event["id"], limit=1
            )
            assert delivered == 0
            cursor = await db.execute(
                "SELECT attempts, next_at FROM event_alert_queue WHERE event_id = ?",
                (event["id"],),
            )
            queued = await cursor.fetchone()
            assert queued["attempts"] == 1
            cursor = await db.execute(
                "SELECT alert_at FROM events WHERE id = ?", (event["id"],)
            )
            assert (await cursor.fetchone())["alert_at"] is None

            # Make the retry immediately due, then let the next attempt succeed.
            await db.execute(
                "UPDATE event_alert_queue SET next_at = datetime('now', '-1 second') "
                "WHERE event_id = ?",
                (event["id"],),
            )
            await db.commit()
            monkeypatch.setattr(alerts.apprise, "Apprise", _FakeApprise)
            delivered = await process_pending_event_alerts(
                db, event_id=event["id"], limit=1
            )
            assert delivered == 1
            cursor = await db.execute(
                "SELECT COUNT(*) FROM event_alert_queue WHERE event_id = ?",
                (event["id"],),
            )
            assert (await cursor.fetchone())[0] == 0
            cursor = await db.execute(
                "SELECT alert_at FROM events WHERE id = ?", (event["id"],)
            )
            assert (await cursor.fetchone())["alert_at"] is not None

            await db.execute("DELETE FROM events WHERE id = ?", (event["id"],))
            await db.commit()
    finally:
        await _delete(client, auth_headers, created["id"])
