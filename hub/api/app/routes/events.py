from fastapi import APIRouter, Depends, Query

from app.dependencies import get_current_user, get_db
from app.models.common import APIResponse, NamedResp, PaginatedPayload, Resp
from app.models.event import EventResponse
from app.services.event_service import act_on_event, list_events
from app.utils import page_count

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=NamedResp("EventList", PaginatedPayload[EventResponse]), operation_id="list_events")
async def get_events(
    plimit: int = Query(50, ge=1, le=200),
    pnum: int = Query(1, ge=1),
    user_id: int = Depends(get_current_user),
    db=Depends(get_db),
):
    events, total = await list_events(db, user_id, plimit, pnum)
    pages = page_count(total, plimit)

    return APIResponse.ok(
        PaginatedPayload(
            items=[EventResponse(**e) for e in events],
            total=total,
            page=pnum,
            limit=plimit,
            pages=pages,
        )
    )


@router.patch("/{event_id}/act", response_model=Resp, operation_id="act_event")
async def act_event(
    event_id: int,
    user_id: int = Depends(get_current_user),
    db=Depends(get_db),
):
    ok = await act_on_event(db, event_id, user_id)
    if not ok:
        return APIResponse.fail("Event not found or already acted", status=1)
    return APIResponse.ok()
