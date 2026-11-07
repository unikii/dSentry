from pydantic import BaseModel, Field


class AlertCreateRequest(BaseModel):
    alert_name: str | None = Field(default=None, max_length=200)
    alert_type: str = Field(max_length=50)
    alert_target: str = Field(max_length=2000)


class AlertUpdateRequest(BaseModel):
    alert_name: str | None = Field(default=None, max_length=200)
    alert_target: str | None = Field(default=None, max_length=2000)
    enabled: bool | None = None


class AlertResponse(BaseModel):
    id: int
    user_id: int
    alert_name: str | None
    alert_type: str
    alert_target: str
    enabled: bool
    edit_at: str | None
    add_at: str
