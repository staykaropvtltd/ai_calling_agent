"""Internal call lifecycle API consumed by the voice gateway (not user-facing)."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Call, PhoneNumberRoute
from src.tenant import get_internal_service_db

logger = logging.getLogger("staykaro.internal")

router = APIRouter(prefix="/internal/v1", tags=["internal"])


# ── Schemas ───────────────────────────────────────────────────────────────────


class CallCreateRequest(BaseModel):
    call_id: str
    tenant_id: str
    agent_id: str
    started_at: datetime
    provider_call_id: Optional[str] = None


class CallCreateResponse(BaseModel):
    call_id: str
    tenant_id: str
    agent_id: str
    status: str
    started_at: datetime

    model_config = {"from_attributes": True}


class CallStateResponse(BaseModel):
    call_id: str
    tenant_id: str
    agent_id: str
    provider_call_id: Optional[str]
    status: str
    started_at: datetime
    ended_at: Optional[datetime]
    end_reason: Optional[str]

    model_config = {"from_attributes": True}


class FinalizeRequest(BaseModel):
    ended_at: datetime
    end_reason: str


class FinalizeResponse(BaseModel):
    call_id: str
    status: str
    ended_at: datetime
    end_reason: str


class PhoneRouteResponse(BaseModel):
    tenant_id: str
    agent_id: str
    provider: str


# ── Routes ────────────────────────────────────────────────────────────────────


@router.post("/calls", response_model=CallCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_call(
    body: CallCreateRequest,
    db: AsyncSession = Depends(get_internal_service_db),
) -> Call:
    existing = await db.get(Call, body.call_id)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Call {body.call_id} already exists",
        )
    call = Call(
        call_id=body.call_id,
        tenant_id=body.tenant_id,
        agent_id=body.agent_id,
        provider_call_id=body.provider_call_id,
        started_at=body.started_at,
        status="active",
    )
    db.add(call)
    await db.commit()
    await db.refresh(call)
    logger.info("Call created: call_id=%s tenant_id=%s", call.call_id, call.tenant_id)
    return call


@router.get("/calls/{call_id}", response_model=CallStateResponse)
async def get_call(
    call_id: str,
    db: AsyncSession = Depends(get_internal_service_db),
) -> Call:
    call = await db.get(Call, call_id)
    if call is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found")
    return call


@router.post("/calls/{call_id}/finalize", response_model=FinalizeResponse)
async def finalize_call(
    call_id: str,
    body: FinalizeRequest,
    db: AsyncSession = Depends(get_internal_service_db),
) -> FinalizeResponse:
    call = await db.get(Call, call_id)
    if call is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found")

    if call.ended_at is not None:
        # Already finalized — idempotent: return current persisted state.
        return FinalizeResponse(
            call_id=call.call_id,
            status=call.status,
            ended_at=call.ended_at,
            end_reason=call.end_reason or "",
        )

    call.ended_at = body.ended_at
    call.end_reason = body.end_reason
    call.status = "failed" if body.end_reason == "provider_failure" else "completed"
    await db.commit()
    await db.refresh(call)
    logger.info(
        "Call finalized: call_id=%s status=%s reason=%s",
        call.call_id,
        call.status,
        call.end_reason,
    )
    return FinalizeResponse(
        call_id=call.call_id,
        status=call.status,
        ended_at=call.ended_at,
        end_reason=call.end_reason,
    )


@router.get("/phone-routes/{number}", response_model=PhoneRouteResponse)
async def get_phone_route(
    number: str,
    db: AsyncSession = Depends(get_internal_service_db),
) -> PhoneRouteResponse:
    route = await db.get(PhoneNumberRoute, number)
    if route is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Phone number route not found"
        )
    return PhoneRouteResponse(
        tenant_id=route.tenant_id,
        agent_id=route.agent_id,
        provider=route.provider or "exotel",
    )
