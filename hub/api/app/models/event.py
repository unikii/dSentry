from pydantic import BaseModel


class EventResponse(BaseModel):
    id: int
    user_id: int
    event_type: str
    device_id: int | None
    note: str | None
    alert_at: str | None
    act_at: str | None
    add_at: str
    device_name: str | None = None
