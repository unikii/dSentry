import os
import tempfile

# Configure the environment before any app module (and its settings
# singleton) is imported by the test modules.
_TEST_DIR = tempfile.mkdtemp(prefix="dsentry-tests-")
os.environ["SQLITE_PATH"] = os.path.join(_TEST_DIR, "test.db")
os.environ["RUN_MODE"] = "private"
# Nothing listens here; tests that reach VictoriaMetrics mock it, and the
# lifespan health check fails fast against this address.
os.environ["VICTORIAMETRICS_URL"] = "http://127.0.0.1:1"
# Empty (not unset) so a developer's local .env cannot leak a real secret in.
os.environ["JWT_SECRET"] = ""
# OAuth login refuses to start when the provider is not configured; tests
# only exercise redirect/state handling, never the provider itself.
os.environ["GITHUB_CLIENT_ID"] = "test-client"
os.environ["GITHUB_CLIENT_SECRET"] = "test-secret"
os.environ["GOOGLE_CLIENT_ID"] = "test-client"
os.environ["GOOGLE_CLIENT_SECRET"] = "test-secret"

import httpx  # noqa: E402
import pytest  # noqa: E402

from app.database import init_sqlite  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
async def client():
    await init_sqlite()

    from app.routes.sessions import _login_ip_limiter, _login_limiter
    _login_limiter._failures.clear()
    _login_ip_limiter._failures.clear()

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            yield c


@pytest.fixture
async def auth_headers(client):
    resp = await client.post(
        "/sessions",
        json={"username": "admin"},
    )
    body = resp.json()
    assert body["status"] == 0, body
    return {"Authorization": f"Bearer {body['payload']['token']}"}


@pytest.fixture
def metrics_writes(monkeypatch):
    """Capture VictoriaMetrics writes issued by the routes (never touches network)."""
    calls: list[str] = []

    from app.routes import nodes as nodes_routes
    from app.routes import push as push_routes

    async def fake_write_metrics(payload: str) -> bool:
        calls.append(payload)
        return True

    async def fake_write_metrics_best_effort(payload: str, context: str = "") -> None:
        calls.append(payload)

    monkeypatch.setattr(push_routes, "write_metrics", fake_write_metrics)
    monkeypatch.setattr(nodes_routes, "write_metrics_best_effort", fake_write_metrics_best_effort)
    return calls
