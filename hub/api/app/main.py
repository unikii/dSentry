import asyncio
import logging
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import init_sqlite, open_db
from app.metrics import metrics_health
from app.models.common import APIResponse
from app.services.alerts import process_pending_event_alerts
from app.services.auth import resolve_jwt_secret
import app.routes.devices as devices
import app.routes.events as events
import app.routes.nodes as nodes
import app.routes.push as push
import app.routes.alerts as alerts
import app.routes.oauth as oauth
import app.routes.sessions as sessions
import app.routes.users as users

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("dsentry")


async def _ensure_private_admin(db) -> None:
    """Create the default admin account on a fresh database, nothing more.

    If any user already exists the bootstrap is skipped entirely. The admin
    starts without a password and signs in without one; the owner may set a
    password under Settings, from which point it is required.
    """
    cursor = await db.execute("SELECT COUNT(*) AS n FROM users")
    row = await cursor.fetchone()
    if row and row["n"] > 0:
        logger.info("Users already exist — skipping admin bootstrap")
        return

    await db.execute(
        "INSERT INTO users (id, username, password_hash) VALUES (1, 'admin', NULL)",
    )
    await db.commit()
    logger.info("Default admin user created (no password set)")


async def _alert_retry_worker() -> None:
    """Retry alerts persisted by the event transaction but not yet delivered."""
    while True:
        await asyncio.sleep(60)
        try:
            async with open_db() as db:
                delivered = await process_pending_event_alerts(db)
                if delivered:
                    logger.info("Retried %d queued alert(s) successfully", delivered)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Alert retry worker failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"dSentry starting in {settings.run_mode} mode")
    await init_sqlite()

    # Single-instance setup: auto-generate + persist the JWT secret when unset,
    # in both private and public modes. Set JWT_SECRET explicitly if you prefer
    # managed secrets; deleting data/jwt_secret invalidates all issued tokens.
    resolve_jwt_secret()

    if settings.run_mode == "private":
        async with open_db() as db:
            await _ensure_private_admin(db)

    try:
        if await metrics_health():
            logger.info("VictoriaMetrics connected")
        else:
            logger.warning("VictoriaMetrics unavailable — metrics will not be stored")
    except Exception:
        logger.warning("VictoriaMetrics unavailable — metrics will not be stored")

    retry_task = asyncio.create_task(_alert_retry_worker())
    try:
        yield
    finally:
        retry_task.cancel()
        await asyncio.gather(retry_task, return_exceptions=True)
        logger.info("dSentry shut down")


_docs_kwargs = {}
if not settings.api_docs_enabled:
    _docs_kwargs = {"docs_url": None, "redoc_url": None, "openapi_url": None}

app = FastAPI(
    title="dSentry",
    description="Self-hosted storage health monitoring service",
    version=settings.app_version,
    lifespan=lifespan,
    **_docs_kwargs,
)

cors_origins = [o.strip() for o in settings.cors_allowed_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content=APIResponse.fail(
            message=str(exc.detail),
            status=1,
        ).model_dump(),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # Do not log Pydantic's "input" field: malformed requests can contain
    # credentials or other user data.
    safe_errors = [
        {"loc": e.get("loc"), "type": e.get("type"), "msg": e.get("msg")}
        for e in exc.errors()
    ]
    logger.warning("Validation error: %s", safe_errors)
    return JSONResponse(
        status_code=422,
        content=APIResponse.fail(
            message="Request validation failed",
            status=1,
        ).model_dump(),
    )


@app.exception_handler(404)
async def not_found_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=404,
        content=APIResponse.fail(
            message="Not found",
            status=1,
        ).model_dump(),
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled error: {exc}")
    return JSONResponse(
        status_code=500,
        content=APIResponse.fail(
            message="Internal server error",
            status=1,
        ).model_dump(),
    )


app.include_router(sessions.router)
app.include_router(oauth.router)
app.include_router(users.router)
app.include_router(nodes.router)
app.include_router(push.router)
app.include_router(devices.router)
app.include_router(events.router)
app.include_router(alerts.router)


def _retention_text(value: str) -> str:
    if value == "100y":
        return "Forever"
    match = re.fullmatch(r"(\d+)([hdwMy]?)", value)
    if match is None:
        return value
    amount = int(match.group(1))
    unit = match.group(2)
    if unit == "y":
        return f"{amount} year(s)"
    if unit in ("", "M"):
        return f"{amount} month(s)"
    if unit == "w":
        return f"{amount} week(s)"
    if unit == "d":
        return f"{amount} day(s)"
    return f"{amount} hour(s)"


@app.get("/envs", operation_id="get_envs")
async def get_envs():
    retention_text = _retention_text(settings.victoriametrics_retention)
    return APIResponse.ok({
        "run_mode": settings.run_mode,
        "metrics_data_lifespan": retention_text,
        "global_push_interval": settings.global_push_interval,
        "global_node_per_user": settings.global_node_per_user,
        "global_device_per_node": settings.global_device_per_node,
        "global_raw_push_base": settings.global_raw_push_base,
        "global_raw_push_plain": settings.global_raw_push_plain,
        "smtp_enabled": bool(settings.smtp_url),
        "login_notify_banner": settings.login_notify_banner or None,
    })
