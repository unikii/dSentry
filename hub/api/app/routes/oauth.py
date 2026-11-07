import logging
import random
import secrets
import string
import time
from hmac import compare_digest
from urllib.parse import urlencode, urlsplit

import httpx
import jwt
from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import RedirectResponse

from app.config import settings
from app.dependencies import get_db
from app.models.common import APIResponse
from app.models.user import LoginResponse
from app.services.node import get_effective_limits
from app.services.session_service import create_session
from app.utils import build_user_response, normalize_username

router = APIRouter(prefix="/oauth", tags=["oauth"])

logger = logging.getLogger("dsentry.oauth")

OAUTH_STATE_COOKIE = "dsentry_oauth_state"
OAUTH_STATE_MAX_AGE = 600

OAUTH_CONFIGS = {
    "github": {
        "authorize_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "userinfo_url": "https://api.github.com/user",
        "client_id": settings.github_client_id,
        "client_secret": settings.github_client_secret,
        "scope": "read:user",
    },
    "google": {
        "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "userinfo_url": "https://www.googleapis.com/oauth2/v2/userinfo",
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "scope": "openid email profile",
    },
}

def _parse_origin(uri: str) -> tuple[str, str, int | None] | None:
    parsed = urlsplit(uri)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return None
    if parsed.username or parsed.password:
        return None
    try:
        port = parsed.port
    except ValueError:
        return None

    scheme = parsed.scheme.lower()
    if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        port = None
    return scheme, parsed.hostname.rstrip(".").lower(), port


ALLOWED_REDIRECT_ORIGINS = {
    parsed
    for origin in settings.oauth_allowed_origins.split(",")
    if (parsed := _parse_origin(origin.strip())) is not None
}


def _validate_redirect_uri(uri: str) -> bool:
    parsed = _parse_origin(uri)
    return parsed is not None and parsed in ALLOWED_REDIRECT_ORIGINS


def _random_username() -> str:
    return "".join(random.choices(string.ascii_lowercase, k=10))


def _sign_state(provider: str, redirect_uri: str, nonce: str) -> str:
    payload = {
        "provider": provider,
        "redirect_uri": redirect_uri,
        "nonce": nonce,
        "exp": int(time.time()) + 600,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _verify_state(token: str, provider: str) -> dict | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        if payload.get("provider") != provider:
            return None
        return payload
    except Exception:
        return None


def _state_matches_cookie(state_data: dict, cookie_nonce: str | None) -> bool:
    state_nonce = state_data.get("nonce")
    return (
        isinstance(state_nonce, str)
        and bool(cookie_nonce)
        and compare_digest(state_nonce, cookie_nonce)
    )


@router.get("/providers/{provider}/login", operation_id="oauth_login")
async def oauth_login(provider: str, redirect_uri: str = Query(...)):
    # In private mode the UI hides OAuth buttons; enforce the same rule on the
    # API so configured provider credentials cannot silently become a public
    # sign-up path.
    if settings.run_mode != "public":
        return APIResponse.fail("OAuth sign-in is disabled in private mode", status=1)

    cfg = OAUTH_CONFIGS.get(provider)
    if not cfg:
        return APIResponse.fail(f"Unknown provider: {provider}", status=1)
    if not cfg["client_id"] or not cfg["client_secret"]:
        return APIResponse.fail(f"{provider} OAuth is not configured", status=1)
    if not _validate_redirect_uri(redirect_uri):
        return APIResponse.fail("Invalid redirect_uri", status=1)

    nonce = secrets.token_urlsafe(32)
    state = _sign_state(provider, redirect_uri, nonce)

    params = {
        "client_id": cfg["client_id"],
        "redirect_uri": redirect_uri,
        "scope": cfg["scope"],
        "response_type": "code",
        "state": state,
    }
    redirect = RedirectResponse(f"{cfg['authorize_url']}?{urlencode(params)}")
    redirect.set_cookie(
        OAUTH_STATE_COOKIE,
        nonce,
        max_age=OAUTH_STATE_MAX_AGE,
        httponly=True,
        secure=urlsplit(redirect_uri).scheme.lower() == "https",
        samesite="lax",
        path="/",
    )
    return redirect


@router.get("/providers/{provider}/callback", operation_id="oauth_callback")
async def oauth_callback(
    request: Request,
    response: Response,
    provider: str,
    code: str = Query(...),
    state: str = Query(...),
    redirect_uri: str = Query(...),
    db=Depends(get_db),
):
    cfg = OAUTH_CONFIGS.get(provider)
    if not cfg:
        return APIResponse.fail(f"Unknown provider: {provider}", status=1)

    state_data = _verify_state(state, provider)
    if state_data is None:
        return APIResponse.fail("Invalid state parameter — possible CSRF attack", status=1)

    if not _state_matches_cookie(state_data, request.cookies.get(OAUTH_STATE_COOKIE)):
        return APIResponse.fail("Invalid OAuth session — please try signing in again", status=1)

    response.delete_cookie(OAUTH_STATE_COOKIE, path="/")

    if not _validate_redirect_uri(redirect_uri):
        return APIResponse.fail("Invalid redirect_uri", status=1)

    if state_data.get("redirect_uri") != redirect_uri:
        return APIResponse.fail("redirect_uri mismatch", status=1)

    async with httpx.AsyncClient() as client:
        token_data = {
            "grant_type": "authorization_code",
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "code": code,
            "redirect_uri": state_data["redirect_uri"],
        }
        token_resp = await client.post(
            cfg["token_url"],
            data=token_data,
            headers={"Accept": "application/json"},
        )
        if token_resp.status_code != 200:
            logger.warning(
                "OAuth token exchange failed for %s (HTTP %s)",
                provider,
                token_resp.status_code,
            )
            return APIResponse.fail("Failed to get access token", status=1)
        token_data = token_resp.json()
        access_token = token_data.get("access_token")
        if not access_token:
            return APIResponse.fail("Failed to get access token", status=1)

        user_resp = await client.get(
            cfg["userinfo_url"],
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if user_resp.status_code != 200:
            logger.warning(
                "OAuth userinfo request failed for %s (HTTP %s)",
                provider,
                user_resp.status_code,
            )
            return APIResponse.fail("Failed to get OAuth user profile", status=1)
        user_data = user_resp.json()

    oauth_id = str(user_data.get("id") or "")
    if not oauth_id:
        return APIResponse.fail("OAuth provider did not return a user id", status=1)
    raw_username = user_data.get("login") or user_data.get("name") or _random_username()
    try:
        username = normalize_username(raw_username)
    except ValueError:
        username = _random_username()
    email = user_data.get("email")

    cursor = await db.execute(
        "SELECT * FROM users WHERE oauth_provider = ? AND oauth_id = ?",
        (provider, oauth_id),
    )
    existing = await cursor.fetchone()

    if existing:
        user_dict = dict(existing)
        if user_dict.get("status", 0) != 0:
            return APIResponse.fail("Account is disabled", status=1)
    else:
        if settings.run_mode != "public":
            # Linking an existing OAuth identity is allowed above; creating a
            # new account in private mode is not.
            return APIResponse.fail("OAuth sign-up is disabled in private mode", status=1)
        user_dict = None
        import sqlite3
        for attempt in range(4):
            name_to_try = username
            if attempt > 0:
                suffix = "".join(random.choices(string.ascii_lowercase, k=5))
                base = username[:45] if len(username) > 45 else username
                name_to_try = base + "_" + suffix

            try:
                cursor = await db.execute(
                    "INSERT INTO users (oauth_provider, oauth_id, username) "
                    "VALUES (?, ?, ?) RETURNING *",
                    (provider, oauth_id, name_to_try),
                )
                user_dict = dict(await cursor.fetchone())
                await db.commit()
                break
            except sqlite3.IntegrityError:
                if attempt == 3:
                    raise
                continue

        if user_dict is None:
            raise RuntimeError("Failed to create user after retries")

        if email:
            from app.services.alerts import create_alert

            try:
                await create_alert(
                    db, user_dict["id"],
                    alert_name="OAuth Email",
                    alert_type="email",
                    alert_target=email,
                )
            except ValueError as exc:
                # The account already exists at this point; an unusable
                # provider email must not turn a successful login into a 500.
                logger.warning("Could not add OAuth email alert: %s", exc)

    node_limit, device_limit = await get_effective_limits(db, user_dict["id"])

    token = await create_session(db, user_dict["id"])

    return APIResponse.ok(
        LoginResponse(
            token=token,
            user=build_user_response(user_dict, node_limit, device_limit),
        )
    )
