"""Request models for node push endpoints.

Nodes are untrusted network clients: every push body is schema-validated
here so malformed payloads fail with 422 instead of surfacing as 500s deep
in the services. Field names mirror the node's wire format exactly (Go
field names for metrics, snake_case for the rest), so validation never
rejects a well-formed node push.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.constants import (
    MAX_DEVICES_PER_PUSH,
    MAX_EVENTS_PER_PUSH,
    MAX_METAS_PER_PUSH,
    MAX_METRICS_PER_PUSH,
    MAX_RAW_BASE64_CHARS,
)

# Bumped when the metrics item shape changes in a breaking way. Nodes stamp
# their pushes with this version; the hub accepts the current version and
# nothing else.
METRICS_SCHEMA_VERSION = 1


class RegisterNodeRequest(BaseModel):
    push_key: str = Field(max_length=200)
    hostname: str | None = Field(default=None, max_length=255)
    host_os: str | None = Field(default=None, max_length=255)


class RegisterDeviceItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    device_hash: str = Field(default="", max_length=200)
    meta_hash: str = Field(default="", max_length=200)
    device_meta: dict[str, Any] | None = None
    initial_metrics: dict[str, Any] | None = None


class RegisterDevicesRequest(BaseModel):
    devices: list[RegisterDeviceItem] = Field(default_factory=list, max_length=MAX_DEVICES_PER_PUSH)


class DeviceMetricsItem(BaseModel):
    # extra="allow": metric fields are schema-driven (schemas/metrics_schema.json)
    # and read by name downstream, so unknown keys must survive validation.
    model_config = ConfigDict(extra="allow")

    DeviceHash: str = ""
    device_hash: str = ""
    TimestampUTC: str | None = None


class PushMetricsRequest(BaseModel):
    schema_version: int | None = None
    metrics: list[DeviceMetricsItem] = Field(default_factory=list, max_length=MAX_METRICS_PER_PUSH)


class PushMetaItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    device_hash: str = Field(default="", max_length=200)
    meta_hash: str = Field(default="", max_length=200)
    device_meta: dict[str, Any] | None = None


class PushMetasRequest(BaseModel):
    metas: list[PushMetaItem] = Field(default_factory=list, max_length=MAX_METAS_PER_PUSH)


class NodeEventItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    event_type: str | None = Field(default=None, max_length=100)
    device_id: int | None = None
    summary: str | None = Field(default=None, max_length=10_000)
    device_hash: str | None = Field(default=None, max_length=200)
    collected_at: str | None = Field(default=None, max_length=64)
    raw_data: str | None = Field(default=None, max_length=MAX_RAW_BASE64_CHARS)
