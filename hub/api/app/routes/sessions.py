import asyncio
import ipaddress

from fastapi import APIRouter, Depends, Request

from app.config import settings
from app.dependencies import get_current_session, get_db
from app.models.common import APIResponse, NamedResp, Resp
from app.models.user import LoginRequest, LoginResponse
from app.services.node import get_effective_limits
from app.services.ratelimit import LoginRateLimiter
from app.services.auth import verify_dummy_password, verify_password
from app.services.session_service import create_session as create_user_session
from app.services.session_service import revoke_session
from app.utils import build_user_response

router = APIRouter(prefix="/sessions", tags=["sessions"])

_login_limiter = LoginRateLimiter(max_failures=5, window_seconds=15 * 60)
# Per-IP aggregate limit: the per-account key alone lets one client try
# unlimited distinct usernames at five attempts each.
_login_ip_limiter = LoginRateLimiter(max_failures=30, window_seconds=15 * 60)


async def _login_response(db, user_id: int) -> APIResponse[LoginResponse]:
    node_limit, device_limit = await get_effective_limits(db, user_id)
    cursor = await db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user_row = await cursor.fetchone()
    user_dict = dict(user_row)

    token = await create_user_session(db, user_dict["id"])
    return APIResponse.ok(
        LoginResponse(
            token=token,
            user=build_user_response(user_dict, node_limit, device_limit),
        )
    )


def _valid_ip(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def _client_ip(request: Request) -> str:
    if settings.trust_proxy_headers:
        # X-Real-IP is written by the bundled nginx proxy. Prefer it because
        # nginx overwrites an incoming value with $remote_addr.
        real_ip = _valid_ip(request.headers.get("x-real-ip"))
        if real_ip:
            return real_ip

        # nginx appends the peer address to X-Forwarded-For. The right-most
        # valid entry is therefore the closest address the edge proxy saw;
        # taking the left-most entry would trust an attacker-supplied prefix.
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            for candidate in reversed(forwarded.split(",")):
                ip = _valid_ip(candidate)
                if ip:
                    return ip

    return request.client.host if request.client else "unknown"


def _login_limit_key(request: Request, username: str) -> str:
    return f"{_client_ip(request)}|{username}"


def _record_login_failure(account_key: str, ip_key: str) -> None:
    _login_limiter.record_failure(account_key)
    _login_ip_limiter.record_failure(ip_key)


@router.post("", response_model=NamedResp("Login", LoginResponse), operation_id="login")
async def create_session(
    body: LoginRequest,
    request: Request,
    db=Depends(get_db),
):
    # Public instances are OAuth-only: password credentials are never accepted
    # there, including for accounts that still carry a hash from an earlier
    # private-mode deployment. OAuth sign-in completes through
    # /oauth/providers/{provider}/callback instead of this endpoint.
    if settings.run_mode != "private":
        return APIResponse.fail(
            "Password sign-in is disabled in public mode; use GitHub or Google",
            status=1,
        )

    username = body.username or "admin"

    key = _login_limit_key(request, username)
    ip_key = _client_ip(request)
    retry_after = max(
        _login_limiter.retry_after(key),
        _login_ip_limiter.retry_after(ip_key),
    )
    if retry_after > 0:
        minutes = max(1, int(retry_after // 60) + 1)
        return APIResponse.fail(
            f"Too many failed login attempts, try again in {minutes} minute(s)",
            status=1,
            notify=True,
        )

    cursor = await db.execute(
        "SELECT * FROM users WHERE username = ?", (username,)
    )
    user = await cursor.fetchone()
    if user is None:
        # Spend the same Argon2 time as a real account to avoid a timing
        # side channel that reveals whether the username exists.
        await asyncio.to_thread(verify_dummy_password, body.password or "")
        _record_login_failure(key, ip_key)
        return APIResponse.fail("Invalid credentials", status=1)

    user_dict = dict(user)

    if user_dict.get("status", 0) != 0:
        await asyncio.to_thread(verify_dummy_password, body.password or "")
        _record_login_failure(key, ip_key)
        return APIResponse.fail("Invalid credentials", status=1)

    password_hash = user_dict.get("password_hash")
    if not password_hash:
        # No local password set. In private mode a local account without a
        # password signs in without one; once the owner sets a password
        # under Settings it becomes required. OAuth-linked accounts must
        # still use their provider.
        if user_dict.get("oauth_provider"):
            await asyncio.to_thread(verify_dummy_password, body.password or "")
            _record_login_failure(key, ip_key)
            return APIResponse.fail("Invalid credentials", status=1)
    else:
        if not body.password:
            return APIResponse.fail("Username and password required", status=1)
        valid = await asyncio.to_thread(verify_password, password_hash, body.password)
        if not valid:
            _record_login_failure(key, ip_key)
            return APIResponse.fail("Invalid credentials", status=1)

    _login_limiter.reset(key)
    _login_ip_limiter.reset(ip_key)
    return await _login_response(db, user_dict["id"])


@router.delete("", response_model=Resp, operation_id="logout")
async def delete_session(
    session: tuple[int, str] = Depends(get_current_session),
    db=Depends(get_db),
):
    """Revoke the session carried by the presented token."""
    _, session_id = session
    await revoke_session(db, session_id)
    return APIResponse.ok()
