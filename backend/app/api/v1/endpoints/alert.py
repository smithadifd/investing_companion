"""Alert endpoints."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, require_not_demo
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.alert import (
    AlertCreate,
    AlertHistoryResponse,
    AlertResponse,
    AlertStats,
    AlertUpdate,
    AlertWithHistoryResponse,
)
from app.schemas.common import DataResponse
from app.services.alert import AlertService
from app.services.notifications.discord import discord_service, get_discord_service_configured

router = APIRouter(prefix="/alerts", tags=["alerts"])


def get_alert_service(db: AsyncSession = Depends(get_db)) -> AlertService:
    """Dependency to get alert service instance."""
    return AlertService(db)


@router.get("", response_model=DataResponse[List[AlertResponse]])
async def list_alerts(
    active_only: bool = False,
    equity_id: Optional[int] = None,
    ratio_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    service: AlertService = Depends(get_alert_service),
) -> DataResponse[List[AlertResponse]]:
    """
    List all alerts.

    - **active_only**: Only return active alerts
    - **equity_id**: Filter by equity
    - **ratio_id**: Filter by ratio
    """
    data = await service.list_alerts(
        active_only=active_only,
        equity_id=equity_id,
        ratio_id=ratio_id,
    )
    return DataResponse(data=data)


@router.post("", response_model=DataResponse[AlertResponse], status_code=status.HTTP_201_CREATED)
async def create_alert(
    data: AlertCreate,
    _demo_guard: None = Depends(require_not_demo),
    current_user: User = Depends(get_current_user),
    service: AlertService = Depends(get_alert_service),
) -> DataResponse[AlertResponse]:
    """
    Create a new alert.

    Specify either `equity_symbol` or `ratio_id` as the alert target.

    Condition types:
    - `above`: Triggers when value > threshold
    - `below`: Triggers when value < threshold
    - `crosses_above`: Triggers when value crosses above threshold
    - `crosses_below`: Triggers when value crosses below threshold
    - `percent_up`: Triggers when value increases by threshold % (requires comparison_period)
    - `percent_down`: Triggers when value decreases by threshold % (requires comparison_period)
    """
    try:
        alert = await service.create_alert(data)
        return DataResponse(data=alert)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get("/stats", response_model=DataResponse[AlertStats])
async def get_alert_stats(
    current_user: User = Depends(get_current_user),
    service: AlertService = Depends(get_alert_service),
) -> DataResponse[AlertStats]:
    """
    Get alert statistics summary.
    """
    stats = await service.get_stats()
    return DataResponse(data=stats)


@router.get("/history", response_model=DataResponse[List[AlertHistoryResponse]])
async def get_all_alert_history(
    limit: int = 100,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    service: AlertService = Depends(get_alert_service),
) -> DataResponse[List[AlertHistoryResponse]]:
    """
    Get all alert trigger history.

    - **limit**: Maximum number of records to return
    - **offset**: Number of records to skip
    """
    history = await service.get_all_history(limit=limit, offset=offset)
    return DataResponse(data=history)


@router.get("/{alert_id}", response_model=DataResponse[AlertWithHistoryResponse])
async def get_alert(
    alert_id: int,
    current_user: User = Depends(get_current_user),
    service: AlertService = Depends(get_alert_service),
) -> DataResponse[AlertWithHistoryResponse]:
    """
    Get a single alert by ID with recent history.
    """
    alert = await service.get_alert_with_history(alert_id)
    if not alert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alert with id {alert_id} not found",
        )
    return DataResponse(data=alert)


@router.put("/{alert_id}", response_model=DataResponse[AlertResponse])
async def update_alert(
    alert_id: int,
    data: AlertUpdate,
    _demo_guard: None = Depends(require_not_demo),
    current_user: User = Depends(get_current_user),
    service: AlertService = Depends(get_alert_service),
) -> DataResponse[AlertResponse]:
    """
    Update an alert.
    """
    alert = await service.update_alert(alert_id, data)
    if not alert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alert with id {alert_id} not found",
        )
    return DataResponse(data=alert)


@router.delete("/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert(
    alert_id: int,
    _demo_guard: None = Depends(require_not_demo),
    current_user: User = Depends(get_current_user),
    service: AlertService = Depends(get_alert_service),
) -> None:
    """
    Delete an alert.
    """
    deleted = await service.delete_alert(alert_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alert with id {alert_id} not found",
        )


@router.post("/{alert_id}/toggle", response_model=DataResponse[AlertResponse])
async def toggle_alert(
    alert_id: int,
    _demo_guard: None = Depends(require_not_demo),
    current_user: User = Depends(get_current_user),
    service: AlertService = Depends(get_alert_service),
) -> DataResponse[AlertResponse]:
    """
    Toggle an alert's active state.
    """
    alert = await service.toggle_alert(alert_id)
    if not alert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alert with id {alert_id} not found",
        )
    return DataResponse(data=alert)


@router.get("/{alert_id}/history", response_model=DataResponse[List[AlertHistoryResponse]])
async def get_alert_history(
    alert_id: int,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    service: AlertService = Depends(get_alert_service),
) -> DataResponse[List[AlertHistoryResponse]]:
    """
    Get trigger history for a specific alert.
    """
    # Verify alert exists
    alert = await service.get_alert(alert_id)
    if not alert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alert with id {alert_id} not found",
        )

    history = await service.get_alert_history(alert_id, limit=limit)
    return DataResponse(data=history)


@router.post("/{alert_id}/check", response_model=DataResponse[dict])
async def check_alert(
    alert_id: int,
    notify: bool = False,
    current_user: User = Depends(get_current_user),
    service: AlertService = Depends(get_alert_service),
) -> DataResponse[dict]:
    """
    Manually check an alert's condition.

    - **notify**: If True and condition is met, send a real notification (ignores cooldown)
    """
    from app.db.models.alert import Alert
    from sqlalchemy import select

    stmt = select(Alert).where(Alert.id == alert_id)
    result = await service.db.execute(stmt)
    alert = result.scalar_one_or_none()

    if not alert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alert with id {alert_id} not found",
        )

    check_result = await service.check_alert(alert)

    # If notify=True and condition is met, send notification
    notification_result = None
    if notify and check_result.is_triggered:
        target_info = await service._get_target_info(alert)
        if target_info:
            success, error = await discord_service.send_alert_notification(
                alert_name=alert.name,
                target_symbol=target_info.symbol,
                target_name=target_info.name,
                condition_type=alert.condition_type,
                threshold_value=alert.threshold_value,
                current_value=check_result.current_value,
                comparison_period=alert.comparison_period,
                is_ratio=(target_info.type.value == "ratio"),
                notes=alert.notes,
            )
            notification_result = {"sent": success, "error": error}

    response_data = check_result.model_dump()
    if notification_result is not None:
        response_data["notification"] = notification_result

    return DataResponse(data=response_data)


# Discord notification endpoints

@router.post("/notifications/test", response_model=DataResponse[dict])
async def test_discord_notification(
    _demo_guard: None = Depends(require_not_demo),
    current_user: User = Depends(get_current_user),
) -> DataResponse[dict]:
    """
    Send a test notification to Discord.
    Useful for verifying webhook configuration.
    """
    # Clear cache to pick up any recent settings changes
    discord_service.clear_cache()

    if not await get_discord_service_configured():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Discord webhook URL not configured. Set it in Settings or environment.",
        )

    success, error = await discord_service.send_test_notification()
    return DataResponse(
        data={
            "success": success,
            "error": error,
        }
    )


@router.get("/notifications/status", response_model=DataResponse[dict])
async def get_notification_status(
    current_user: User = Depends(get_current_user),
) -> DataResponse[dict]:
    """
    Get notification service status.
    """
    # Clear cache to get fresh status
    discord_service.clear_cache()

    return DataResponse(
        data={
            "discord": {
                "configured": await get_discord_service_configured(),
            }
        }
    )
