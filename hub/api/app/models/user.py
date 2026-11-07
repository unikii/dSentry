from pydantic import BaseModel, Field


class UserResponse(BaseModel):
    id: int
    username: str | None
    oauth_provider: str | None
    node_limit: int | None = None
    node_device_limit: int | None = None
    status: int = 0
    reg_at: str
    # Whether the account has a local password (drives the Settings UI).
    has_password: bool = False


class UserUpdateRequest(BaseModel):
    username: str | None = Field(default=None, max_length=100)
    password: str | None = Field(default=None, min_length=6, max_length=256)
    # Required when changing an existing password.
    current_password: str | None = Field(default=None, max_length=256)


class LoginRequest(BaseModel):
    username: str | None = Field(default=None, max_length=100)
    password: str | None = Field(default=None, max_length=256)


class UserDeleteRequest(BaseModel):
    username: str = Field(max_length=100)


class LoginResponse(BaseModel):
    token: str
    user: UserResponse
