import asyncio

from fastapi import APIRouter, Depends

from app.config import settings
from app.dependencies import get_current_session, get_current_user, get_db
from app.models.common import APIResponse, NamedResp
from app.models.user import UserDeleteRequest, UserResponse, UserUpdateRequest
from app.services.auth import hash_password, verify_password
from app.services.node import delete_user_cascade, get_effective_limits
from app.services.session_service import revoke_all_sessions
from app.utils import build_user_response, normalize_username

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/{user_id}", response_model=NamedResp("User", UserResponse), operation_id="get_user")
async def get_user(
    user_id: int,
    current_user_id: int = Depends(get_current_user),
    db=Depends(get_db),
):
    if current_user_id != user_id:
        return APIResponse.fail("Forbidden", status=1)

    cursor = await db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = await cursor.fetchone()
    if row is None:
        return APIResponse.fail("User not found", status=1)

    user = dict(row)
    node_limit, device_limit = await get_effective_limits(db, user_id)
    return APIResponse.ok(build_user_response(user, node_limit, device_limit))


@router.patch("/{user_id}", response_model=NamedResp("User", UserResponse), operation_id="update_user")
async def update_user(
    user_id: int,
    body: UserUpdateRequest,
    session: tuple[int, str] = Depends(get_current_session),
    db=Depends(get_db),
):
    current_user_id, current_session_id = session
    if current_user_id != user_id:
        return APIResponse.fail("Forbidden", status=1)

    # Public instances are OAuth-only: a local password could never be used
    # to sign in, so refuse to create or change one.
    if body.password and settings.run_mode != "private":
        return APIResponse.fail(
            "Password sign-in is disabled in public mode; use your OAuth provider",
            status=1,
        )

    cursor = await db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = await cursor.fetchone()
    if row is None:
        return APIResponse.fail("User not found", status=1)
    user_row = dict(row)

    if body.password:
        stored_hash = user_row.get("password_hash")
        if stored_hash:
            # Changing an existing password requires proving you know the
            # current one, so a stolen token alone cannot take over the account.
            if not body.current_password:
                return APIResponse.fail("Current password required to change password", status=1)
            valid = await asyncio.to_thread(verify_password, stored_hash, body.current_password)
            if not valid:
                return APIResponse.fail("Current password is incorrect", status=1)

    await db.execute("BEGIN IMMEDIATE")
    try:
        if body.username:
            try:
                new_username = normalize_username(body.username)
            except ValueError:
                await db.rollback()
                return APIResponse.fail("Invalid username", status=1)
            # Re-checked inside the write transaction so concurrent username
            # changes queue behind the lock instead of racing to a 500.
            cursor = await db.execute(
                "SELECT id FROM users WHERE username = ? AND id != ?",
                (new_username, user_id),
            )
            existing = await cursor.fetchone()
            if existing:
                await db.rollback()
                return APIResponse.fail("Username already taken", status=1)
            await db.execute(
                "UPDATE users SET username = ? WHERE id = ?",
                (new_username, user_id),
            )

        if body.password:
            pw_hash = await asyncio.to_thread(hash_password, body.password)
            await db.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (pw_hash, user_id),
            )

        await db.commit()
    except Exception:
        await db.rollback()
        raise

    if body.password:
        # A new password invalidates every other issued session.
        await revoke_all_sessions(db, user_id, except_session=current_session_id)

    cursor = await db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user = dict(await cursor.fetchone())
    node_limit, device_limit = await get_effective_limits(db, user_id)
    return APIResponse.ok(build_user_response(user, node_limit, device_limit))


@router.delete("/{user_id}", response_model=NamedResp("Delete", dict), operation_id="delete_user")
async def delete_user(
    user_id: int,
    body: UserDeleteRequest,
    session: tuple[int, str] = Depends(get_current_session),
    db=Depends(get_db),
):
    current_user_id, _ = session
    if settings.run_mode == "private":
        return APIResponse.fail("Account deletion is only available in public mode", status=1)

    if current_user_id != user_id:
        return APIResponse.fail("Forbidden", status=1)

    cursor = await db.execute("SELECT username FROM users WHERE id = ?", (user_id,))
    row = await cursor.fetchone()
    if row is None:
        return APIResponse.fail("User not found", status=1)

    try:
        confirm = normalize_username(body.username)
    except ValueError:
        return APIResponse.fail("Username does not match", status=1)

    if row["username"] != confirm:
        return APIResponse.fail("Username does not match", status=1)

    await db.execute("BEGIN IMMEDIATE")
    try:
        result = await delete_user_cascade(db, user_id)
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return APIResponse.ok({**result})
