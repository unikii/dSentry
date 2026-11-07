import re

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    run_mode: str = "private"
    app_version: str = "0.1.0"
    api_docs_enabled: bool = True

    sqlite_path: str = "data/dsentry.db"

    victoriametrics_url: str = "http://localhost:8428"
    victoriametrics_username: str = ""
    victoriametrics_password: str = ""
    victoriametrics_timeout_seconds: float = 30.0

    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440

    global_node_per_user: int = 20
    global_device_per_node: int = 99
    global_push_interval: int = 30
    global_raw_push_base: str = "day"
    global_raw_push_freq: int = 1
    global_raw_push_plain: bool = True

    # Lookback for the "latest sample" query. It only needs to cover a few
    # push intervals; keep it modest so the instant query stays cheap.
    latest_metrics_lookback_hours: int = 48

    smtp_url: str = ""

    github_client_id: str = ""
    github_client_secret: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""
    oauth_allowed_origins: str = ""

    login_notify_banner: str = ""

    # VictoriaMetrics' -retentionPeriod value. A bare number means months;
    # d/w/M/y suffixes are supported (for example 12, 1y, 100y).
    victoriametrics_retention: str = "12"

    cors_allowed_origins: str = ""
    alert_allow_private_targets: bool = False
    # Trust X-Forwarded-For / X-Real-IP for client identification. Enable
    # only when the API is reachable exclusively through a reverse proxy.
    trust_proxy_headers: bool = False

    @field_validator("run_mode")
    @classmethod
    def _validate_run_mode(cls, value: str) -> str:
        if value not in {"private", "public"}:
            raise ValueError("RUN_MODE must be 'private' or 'public'")
        return value

    @field_validator("jwt_algorithm")
    @classmethod
    def _validate_jwt_algorithm(cls, value: str) -> str:
        if value not in {"HS256", "HS384", "HS512"}:
            raise ValueError("JWT_ALGORITHM must be HS256, HS384, or HS512")
        return value

    @field_validator("latest_metrics_lookback_hours")
    @classmethod
    def _validate_latest_lookback(cls, value: int) -> int:
        if not 1 <= value <= 720:
            raise ValueError(
                "LATEST_METRICS_LOOKBACK_HOURS must be between 1 and 720"
            )
        return value

    @field_validator("victoriametrics_retention")
    @classmethod
    def _validate_retention(cls, value: str) -> str:
        value = value.strip()
        match = re.fullmatch(r"(\d+)([hdwMy]?)", value)
        if match is None or int(match.group(1)) <= 0:
            raise ValueError(
                "VICTORIAMETRICS_RETENTION must be a positive number with an "
                "optional h/d/w/M/y suffix (for example 12, 1y, or 100y)"
            )
        # VictoriaMetrics refuses to start with -retentionPeriod < 24h
        # (vmstorage Fatalf). Bare numbers and M/d/w/y units are >= 1 day.
        if match.group(2) == "h" and int(match.group(1)) < 24:
            raise ValueError(
                "VICTORIAMETRICS_RETENTION must be at least 24h/1d: "
                "VictoriaMetrics does not support shorter retention"
            )
        return value


settings = Settings()
