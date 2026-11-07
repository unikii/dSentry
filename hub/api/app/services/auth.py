import logging
import secrets
import time
from pathlib import Path
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import (
    InvalidHashError,
    UnsupportedParametersError,
    VerificationError,
)

from app.config import settings

logger = logging.getLogger("dsentry.auth")

ph = PasswordHasher()

# A valid hash used to equalize login timing for unknown/disabled accounts.
# Verifying it takes the same Argon2 work as a real password check, so an
# attacker cannot enumerate accounts by response time.
_DUMMY_PASSWORD_HASH = ph.hash("dsentry-timing-equalizer")


def hash_password(password: str) -> str:
    return ph.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    try:
        return ph.verify(stored_hash, password)
    except (VerificationError, InvalidHashError, UnsupportedParametersError):
        # InvalidHashError/UnsupportedParametersError are ValueError
        # subclasses, not VerificationError; a corrupted or old-format hash
        # must reject the login instead of raising a 500.
        return False


def verify_dummy_password(password: str) -> None:
    """Burn the same Argon2 cost as a real verification (timing defense)."""
    try:
        ph.verify(_DUMMY_PASSWORD_HASH, password or "")
    except (VerificationError, InvalidHashError, UnsupportedParametersError):
        pass


# Secrets that look configured but are publicly known; treated as unset.
_WELL_KNOWN_SECRETS = {"", "change-me-in-production"}


def jwt_secret_is_configured() -> bool:
    return settings.jwt_secret not in _WELL_KNOWN_SECRETS


def resolve_jwt_secret() -> str:
    """Resolve the JWT signing secret, generating and persisting one if unset.

    Without this, an instance started with the well-known default secret (or
    none at all) lets anyone mint a token for any user_id. Single-instance
    deployments (private and public) get a random secret persisted next to
    the SQLite file (data/jwt_secret); set JWT_SECRET explicitly if you
    prefer managed secrets.
    """
    if jwt_secret_is_configured():
        return settings.jwt_secret

    secret_file = Path(settings.sqlite_path).parent / "jwt_secret"
    if secret_file.exists():
        settings.jwt_secret = secret_file.read_text().strip()
        if settings.jwt_secret:
            logger.warning("JWT_SECRET not set — using generated secret from %s", secret_file)
            return settings.jwt_secret

    settings.jwt_secret = secrets.token_urlsafe(48)
    try:
        secret_file.parent.mkdir(parents=True, exist_ok=True)
        secret_file.write_text(settings.jwt_secret)
        secret_file.chmod(0o600)
        logger.warning(
            "JWT_SECRET not set — generated a random secret and saved it to %s "
            "(deleting the file invalidates all issued tokens)", secret_file
        )
    except OSError as e:
        logger.warning("JWT_SECRET not set — generated a random secret for this run (could not persist to %s: %s)", secret_file, e)
    return settings.jwt_secret


def create_jwt(user_id: int, session_id: str) -> str:
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        # Binds the token to its sessions-table row, enabling logout and
        # revocation; verified on every request by get_current_user.
        "jti": session_id,
        "iat": now,
        "exp": now + settings.jwt_expire_minutes * 60,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_jwt(token: str) -> dict[str, Any]:
    return jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
        options={"require": ["exp", "sub", "jti"]},
    )
