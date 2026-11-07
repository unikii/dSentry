from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, StringConstraints, create_model

from app.constants import MAX_TAG_LENGTH

T = TypeVar("T")

# max_length on list[str] limits the number of tags, not each tag; constrain
# the element type as well.
TagStr = Annotated[str, StringConstraints(max_length=MAX_TAG_LENGTH)]


class APIResponse(BaseModel, Generic[T]):
    status: int = 0
    message: str = ""
    notify: bool = False
    payload: T | None = None

    @classmethod
    def ok(cls, payload: T = None) -> "APIResponse[T]":
        return cls(status=0, payload=payload)

    @classmethod
    def fail(cls, message: str = "", status: int = 1, notify: bool = False) -> "APIResponse":
        return cls(status=status, message=message, notify=notify)


class PaginatedPayload(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    limit: int
    pages: int


Resp = APIResponse


def NamedResp(title: str, payload_type: type) -> type:
    return create_model(
        title,
        status=(int, 0),
        message=(str, ""),
        notify=(bool, False),
        payload=(payload_type | None, None),
    )
