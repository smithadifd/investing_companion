"""Trigger playbook endpoints - standing orders with live signals."""

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, require_not_demo
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.trigger import (
    TriggerCreate,
    TriggerExecute,
    TriggerResponse,
    TriggerUpdate,
)
from app.services.trigger import TriggerService

logger = logging.getLogger(__name__)

router = APIRouter()


def get_trigger_service(db: AsyncSession = Depends(get_db)) -> TriggerService:
    return TriggerService(db)


@router.get("", response_model=List[TriggerResponse])
async def list_triggers(
    include_retired: bool = Query(False),
    current_user: User = Depends(get_current_user),
    service: TriggerService = Depends(get_trigger_service),
) -> List[TriggerResponse]:
    return await service.list_triggers(include_retired=include_retired)


@router.post("", response_model=TriggerResponse, status_code=status.HTTP_201_CREATED)
async def create_trigger(
    data: TriggerCreate,
    _demo_guard: None = Depends(require_not_demo),
    current_user: User = Depends(get_current_user),
    service: TriggerService = Depends(get_trigger_service),
) -> TriggerResponse:
    try:
        return await service.create_trigger(data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))


@router.get("/{trigger_id}", response_model=TriggerResponse)
async def get_trigger(
    trigger_id: int,
    current_user: User = Depends(get_current_user),
    service: TriggerService = Depends(get_trigger_service),
) -> TriggerResponse:
    trigger = await service.get_trigger(trigger_id)
    if not trigger:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trigger not found")
    return trigger


@router.put("/{trigger_id}", response_model=TriggerResponse)
async def update_trigger(
    trigger_id: int,
    data: TriggerUpdate,
    _demo_guard: None = Depends(require_not_demo),
    current_user: User = Depends(get_current_user),
    service: TriggerService = Depends(get_trigger_service),
) -> TriggerResponse:
    try:
        trigger = await service.update_trigger(trigger_id, data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    if not trigger:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trigger not found")
    return trigger


@router.delete("/{trigger_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_trigger(
    trigger_id: int,
    _demo_guard: None = Depends(require_not_demo),
    current_user: User = Depends(get_current_user),
    service: TriggerService = Depends(get_trigger_service),
) -> None:
    deleted = await service.delete_trigger(trigger_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trigger not found")


@router.post("/{trigger_id}/execute", response_model=TriggerResponse)
async def execute_trigger(
    trigger_id: int,
    data: TriggerExecute,
    _demo_guard: None = Depends(require_not_demo),
    current_user: User = Depends(get_current_user),
    service: TriggerService = Depends(get_trigger_service),
) -> TriggerResponse:
    """Mark the pre-committed action as taken."""
    trigger = await service.execute_trigger(trigger_id, note=data.note)
    if not trigger:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trigger not found")
    return trigger


@router.post("/{trigger_id}/rearm", response_model=TriggerResponse)
async def rearm_trigger(
    trigger_id: int,
    _demo_guard: None = Depends(require_not_demo),
    current_user: User = Depends(get_current_user),
    service: TriggerService = Depends(get_trigger_service),
) -> TriggerResponse:
    trigger = await service.rearm_trigger(trigger_id)
    if not trigger:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trigger not found")
    return trigger
