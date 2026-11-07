from app.config import settings
from app.services.auth import jwt_secret_is_configured, resolve_jwt_secret


def test_resolve_generates_and_persists(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "sqlite_path", str(tmp_path / "db.sqlite"))
    monkeypatch.setattr(settings, "jwt_secret", "")

    secret = resolve_jwt_secret()
    assert len(secret) >= 32

    secret_file = tmp_path / "jwt_secret"
    assert secret_file.exists()
    assert secret_file.read_text() == secret
    assert oct(secret_file.stat().st_mode & 0o777) == "0o600"

    # A second resolution reuses the persisted secret.
    monkeypatch.setattr(settings, "jwt_secret", "")
    assert resolve_jwt_secret() == secret


def test_explicit_secret_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "sqlite_path", str(tmp_path / "db.sqlite"))
    monkeypatch.setattr(settings, "jwt_secret", "configured-secret")
    assert resolve_jwt_secret() == "configured-secret"
    assert not (tmp_path / "jwt_secret").exists()


def test_well_known_secrets_treated_as_unset(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", "change-me-in-production")
    assert not jwt_secret_is_configured()
    monkeypatch.setattr(settings, "jwt_secret", "")
    assert not jwt_secret_is_configured()
    monkeypatch.setattr(settings, "jwt_secret", "real-secret")
    assert jwt_secret_is_configured()


def test_tokens_signed_with_generated_secret_roundtrip(tmp_path, monkeypatch):
    from app.services.auth import create_jwt, decode_jwt

    monkeypatch.setattr(settings, "sqlite_path", str(tmp_path / "db.sqlite"))
    monkeypatch.setattr(settings, "jwt_secret", "")
    resolve_jwt_secret()

    token = create_jwt(42, "session-1")
    decoded = decode_jwt(token)
    assert decoded["sub"] == "42"
    assert decoded["jti"] == "session-1"
