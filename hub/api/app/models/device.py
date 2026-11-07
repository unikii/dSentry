from typing import Any

from pydantic import BaseModel, Field

from app.constants import MAX_TAGS
from app.models.common import TagStr


DeviceExtUnion = dict[str, Any] | None


class DeviceResponse(BaseModel):
    id: int
    user_id: int
    device_hash: str
    meta_hash: str
    device_name: str | None
    device_type: str
    using_protocol: str | None
    device_ext: DeviceExtUnion
    smart_available: bool | None
    smart_enabled: bool | None
    smart_status: int | None
    threshold_status: int | None
    last_event_at: str | None = None
    tags: list[str] | None
    serial_number: str
    model_name: str
    vendor: str | None
    total_capacity_bytes: int
    firmware_version: str | None
    vendor_guess: str | None
    archived: bool = False
    reg_at: str


class RawListItem(BaseModel):
    id: int
    device_id: int
    add_at: str | None = None


class RawDetail(RawListItem):
    raw_output: str


class DeviceUpdateRequest(BaseModel):
    tags: list[TagStr] | None = Field(default=None, max_length=MAX_TAGS)
    # Set by the UI when the user views a device's latest alert: clears the
    # "has unhandled event" marker (last_event_at).
    clear_last_event: bool | None = None

