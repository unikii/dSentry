from pydantic import BaseModel, Field

from app.constants import MAX_TAGS
from app.models.common import TagStr


class NodeResponse(BaseModel):
    id: int
    user_id: int
    hostname: str | None
    host_os: str | None
    push_key: str
    push_count: int
    tags: list[str] | None
    last_raw_push: str | None
    last_metrics_push: str | None
    last_device_push: list[int] | None
    reg_at: str | None
    add_at: str | None


class NodeCreateResponse(BaseModel):
    id: int
    push_key: str


class NodeUpdateRequest(BaseModel):
    hostname: str | None = Field(default=None, max_length=255)
    host_os: str | None = Field(default=None, max_length=255)
    tags: list[TagStr] | None = Field(default=None, max_length=MAX_TAGS)


class NodeConfigResponse(BaseModel):
    push_interval: int
    push_raw: bool
    push_raw_plain: bool
    device_limit: int
    last_metrics_push: str | None = None
    server_time: str


class RegisterNodePayload(BaseModel):
    node_id: int
