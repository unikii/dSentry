from fastapi import APIRouter, Depends

from app.dependencies import get_current_user, get_db
from app.models.alert import AlertCreateRequest, AlertResponse, AlertUpdateRequest
from app.models.common import APIResponse, NamedResp, Resp
from app.services.alerts import (
    create_alert,
    delete_alert,
    list_alerts,
    send_test_alert,
    update_alert,
)

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=NamedResp("AlertList", list[AlertResponse]), operation_id="list_alerts")
async def get_alerts(
    user_id: int = Depends(get_current_user),
    db=Depends(get_db),
):
    alerts = await list_alerts(db, user_id)
    return APIResponse.ok(alerts)


@router.post("", response_model=NamedResp("Alert", AlertResponse), operation_id="create_alert")
async def create_alert_endpoint(
    body: AlertCreateRequest,
    user_id: int = Depends(get_current_user),
    db=Depends(get_db),
):
    try:
        result = await create_alert(db, user_id, body.alert_name, body.alert_type, body.alert_target)
    except ValueError as e:
        return APIResponse.fail(str(e), status=1)
    return APIResponse.ok(result)


@router.patch("/{alert_id}", response_model=NamedResp("Alert", AlertResponse), operation_id="update_alert")
async def update_alert_endpoint(
    alert_id: int,
    body: AlertUpdateRequest,
    user_id: int = Depends(get_current_user),
    db=Depends(get_db),
):
    try:
        result = await update_alert(db, alert_id, user_id, body.enabled, body.alert_name, body.alert_target)
    except ValueError as e:
        return APIResponse.fail(str(e), status=1)
    if result is None:
        return APIResponse.fail("Alert method not found", status=1)
    return APIResponse.ok(result)


@router.delete("/{alert_id}", response_model=Resp, operation_id="delete_alert")
async def delete_alert_endpoint(
    alert_id: int,
    user_id: int = Depends(get_current_user),
    db=Depends(get_db),
):
    deleted = await delete_alert(db, alert_id, user_id)
    if not deleted:
        return APIResponse.fail("Alert method not found", status=1)
    return APIResponse.ok()


@router.post("/{alert_id}/test", response_model=Resp, operation_id="test_alert")
async def test_alert_endpoint(
    alert_id: int,
    user_id: int = Depends(get_current_user),
    db=Depends(get_db),
):
    success = await send_test_alert(db, alert_id, user_id)
    if not success:
        return APIResponse.fail("Test alert failed — check target and configuration", status=1)
    return APIResponse.ok()
