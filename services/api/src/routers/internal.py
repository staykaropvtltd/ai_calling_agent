"""Internal call lifecycle API consumed by the voice gateway (not user-facing)."""

from __future__ import annotations

import hmac
import logging
from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import INTERNAL_API_TOKEN
from src.models import Call, Caller, Campaign, CampaignContact, PhoneNumberRoute
from src.tenant import get_internal_service_db

logger = logging.getLogger("staykaro.internal")

# Maps every known end_reason the voice gateway may send to the correct
# (call_status, connection_status) pair.
#
# connection_status reflects what happened at the telephony layer:
#   connected         — remote party answered and conversation began
#   attempted         — we dialled but nobody answered (or voicemail)
#   failed_pre_connect — technical failure before ring/answer
#   not_attempted      — the call was cancelled before we dialled
#
# call_status is the terminal lifecycle state for the calls table.
#
# Any end_reason NOT in this dict is handled by the _unknown fallback at
# the bottom of finalize_call, which maps to ("failed", "failed_pre_connect")
# and logs a warning so we can add the missing value without silent data loss.
_END_REASON_MAP: dict[str, tuple[str, str]] = {
    # Natural conversation endings — call was connected and completed normally
    "caller_hangup": ("completed", "connected"),
    "agent_finished": ("completed", "connected"),
    # Remote party did not answer
    "no_answer": ("no_answer", "attempted"),
    # Call reached voicemail instead of a live person
    "voicemail": ("voicemail", "attempted"),
    # Bad destination number — failure before any ring
    "invalid_number": ("failed", "failed_pre_connect"),
    # Transient network / media failure
    "network_error": ("failed", "failed_pre_connect"),
    # Telephony provider infrastructure failure
    "provider_failure": ("failed", "failed_pre_connect"),
    # Work-item was cancelled before the call was placed
    "cancelled": ("cancelled", "not_attempted"),
    # Simulation variants — produced by the local dev/test pipeline
    "simulation_complete": ("completed", "connected"),
    "simulation_cancelled": ("cancelled", "not_attempted"),
    "simulation_no_answer": ("no_answer", "attempted"),
}


async def verify_internal_token(
    x_internal_api_token: Annotated[str | None, Header()] = None,
) -> None:
    """Shared-secret guard for the service-to-service /internal/v1/* surface.

    These routes have no JWT/user identity to authenticate (see
    get_internal_service_db) — without this, any caller reachable on the
    Docker network (or through a misconfigured public proxy — see
    infrastructure/nginx/nginx*.conf's explicit block on this prefix) could
    create/read/finalize call records for any tenant with zero credentials.
    Empty/unset INTERNAL_API_TOKEN fails closed: every request is rejected,
    never accidentally left open.
    """
    if (
        not INTERNAL_API_TOKEN
        or not x_internal_api_token
        or not hmac.compare_digest(x_internal_api_token, INTERNAL_API_TOKEN)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing internal API token",
        )


router = APIRouter(
    prefix="/internal/v1",
    tags=["internal"],
    dependencies=[Depends(verify_internal_token)],
)


# ── Schemas ───────────────────────────────────────────────────────────────────


class CallCreateRequest(BaseModel):
    call_id: str
    tenant_id: str
    agent_id: str
    started_at: datetime
    provider_call_id: Optional[str] = None
    # False = real telephony carrier; True = local dev/test simulation.
    # The gateway MUST set this accurately — a simulated call marked as real
    # will appear in client analytics as a genuine call. Defaults to False for
    # backward-compat with gateway versions that pre-date Phase 1.
    is_simulation: bool = False
    # Outbound-call extensions: set by the integration service, never by the
    # inbound voice gateway (which sets connection_status via its server_default).
    # connection_status "not_attempted" signals that the Call record was created
    # before the call was actually answered — correct for outbound dials where
    # we record the attempt the moment the Exotel API accepts the request.
    connection_status: str = "connected"
    # FK to call_requests.id — links an outbound campaign call to its work-item.
    call_request_id: Optional[int] = None


class CallCreateResponse(BaseModel):
    call_id: str
    tenant_id: str
    agent_id: str
    status: str
    is_simulation: bool
    started_at: datetime

    model_config = {"from_attributes": True}


class CallStateResponse(BaseModel):
    call_id: str
    tenant_id: str
    agent_id: str
    provider_call_id: Optional[str]
    status: str
    is_simulation: bool
    connection_status: str
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
    connection_status: str
    is_simulation: bool
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
        is_simulation=body.is_simulation,
        connection_status=body.connection_status,
        call_request_id=body.call_request_id,
    )
    db.add(call)
    await db.commit()
    await db.refresh(call)
    logger.info(
        "Call created: call_id=%s tenant_id=%s is_simulation=%s",
        call.call_id,
        call.tenant_id,
        call.is_simulation,
    )
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
            connection_status=call.connection_status,
            is_simulation=call.is_simulation,
            ended_at=call.ended_at,
            end_reason=call.end_reason or "",
        )

    new_status, new_connection_status = _END_REASON_MAP.get(body.end_reason, (None, None))
    if new_status is None:
        # Unknown end_reason from the gateway — warn loudly (triggers monitoring
        # alert) and fail safely. "failed" / "failed_pre_connect" are the most
        # conservative choice: they flag the call for human review rather than
        # silently marking it completed, which would pollute analytics with
        # false-positive call records.
        logger.warning(
            "finalize_call: unknown end_reason %r for call_id=%s — "
            "mapping to failed/failed_pre_connect. "
            "Add this end_reason to _END_REASON_MAP in routers/internal.py.",
            body.end_reason,
            call_id,
        )
        new_status, new_connection_status = "failed", "failed_pre_connect"

    call.ended_at = body.ended_at
    call.end_reason = body.end_reason
    call.status = new_status
    call.connection_status = new_connection_status

    # ── Cascade to Caller + CampaignContact + Campaign (outbound calls only) ──
    # call_request_id is set only for outbound campaign calls (never for inbound).
    if call.call_request_id is not None:
        await _finalize_outbound_caller(db, call)

    await db.commit()
    await db.refresh(call)
    logger.info(
        "Call finalized: call_id=%s status=%s connection_status=%s reason=%s is_simulation=%s",
        call.call_id,
        call.status,
        call.connection_status,
        call.end_reason,
        call.is_simulation,
    )
    return FinalizeResponse(
        call_id=call.call_id,
        status=call.status,
        connection_status=call.connection_status,
        is_simulation=call.is_simulation,
        ended_at=call.ended_at,
        end_reason=call.end_reason,
    )


_CALL_STATUS_TO_CALLER: dict[str, str] = {
    "completed": "completed",
    "failed": "failed",
    "no_answer": "no_answer",
    "voicemail": "voicemail",
    "cancelled": "cancelled",
}

_CALL_STATUS_TO_CONTACT: dict[str, str] = {
    "completed": "completed",
    "failed": "failed",
    "no_answer": "no_answer",
    "voicemail": "no_answer",
    "cancelled": "skipped",
}


async def _finalize_outbound_caller(db: AsyncSession, call: Call) -> None:
    """Update the Caller work-item and its linked CampaignContact + Campaign
    when an outbound call reaches a terminal state.  Called only when
    Call.call_request_id is not None (outbound campaign calls exclusively).
    Must be called *before* the parent transaction commits so all updates land
    atomically with the Call finalization."""
    caller = await db.get(Caller, call.call_request_id)
    if caller is None:
        logger.warning("finalize_outbound_caller: caller_id=%s not found", call.call_request_id)
        return

    caller.status = _CALL_STATUS_TO_CALLER.get(call.status, "failed")
    caller.connection_status = call.connection_status
    if call.status != "completed":
        caller.failure_reason = call.end_reason
    logger.info(
        "Caller updated: caller_id=%s status=%s connection_status=%s",
        caller.id, caller.status, caller.connection_status,
    )

    # ── CampaignContact ───────────────────────────────────────────────────────
    contact_result = await db.execute(
        select(CampaignContact).where(CampaignContact.call_request_id == caller.id)
    )
    contact = contact_result.scalar_one_or_none()
    if contact is None:
        return

    contact.status = _CALL_STATUS_TO_CONTACT.get(call.status, "failed")
    contact.attempts = (contact.attempts or 0) + 1

    # ── Campaign counters ─────────────────────────────────────────────────────
    campaign = await db.get(Campaign, contact.campaign_id)
    if campaign is None:
        return

    campaign.queued_count = max(0, (campaign.queued_count or 0) - 1)
    if call.status == "completed":
        campaign.completed_count = (campaign.completed_count or 0) + 1
    elif call.status == "failed":
        campaign.failed_count = (campaign.failed_count or 0) + 1
    elif call.status in ("no_answer", "voicemail"):
        campaign.no_answer_count = (campaign.no_answer_count or 0) + 1

    # Auto-complete the campaign when every contact has a terminal status
    if campaign.queued_count == 0 and campaign.status == "running":
        done = (
            (campaign.completed_count or 0)
            + (campaign.failed_count or 0)
            + (campaign.no_answer_count or 0)
        )
        if done >= (campaign.total_contacts or 0) and campaign.total_contacts > 0:
            campaign.status = "completed"
            logger.info("Campaign auto-completed: campaign_id=%s", campaign.id)

    logger.info(
        "Campaign counters updated: campaign_id=%s queued=%s completed=%s failed=%s no_answer=%s",
        campaign.id, campaign.queued_count, campaign.completed_count,
        campaign.failed_count, campaign.no_answer_count,
    )


# ── Caller status update (called by integration-service after outbound dial) ──


class CallerDialedRequest(BaseModel):
    """Sent by integration-service immediately after Exotel accepts the dial.
    Stores the provider-assigned call ID and marks the work-item as 'dialing'."""
    telephony_call_id: str
    is_simulation: bool = False


@router.patch("/call-requests/{caller_id}/dialed", status_code=status.HTTP_200_OK)
async def mark_caller_dialed(
    caller_id: int,
    body: CallerDialedRequest,
    db: AsyncSession = Depends(get_internal_service_db),
) -> dict:
    """Update a Caller (call_request) record once the outbound dial is
    accepted by Exotel.  Sets status='dialing', links the telephony Call
    record UUID, and propagates is_simulation so that simulation calls
    are never counted as real calls in analytics."""
    caller = await db.get(Caller, caller_id)
    if caller is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Caller not found")
    caller.status = "dialing"
    caller.telephony_call_id = body.telephony_call_id
    caller.is_simulation = body.is_simulation
    await db.commit()
    logger.info(
        "Caller marked dialed: caller_id=%s telephony_call_id=%s is_simulation=%s",
        caller_id, body.telephony_call_id, body.is_simulation,
    )
    return {"caller_id": caller_id, "status": "dialing"}


# ── Call lookup by provider_call_id (for outbound webhook resolution) ─────────


class CallByProviderResponse(BaseModel):
    call_id: str
    tenant_id: str
    agent_id: str
    provider_call_id: Optional[str]
    status: str
    connection_status: str
    is_simulation: bool
    call_request_id: Optional[int]

    model_config = {"from_attributes": True}


@router.get("/calls/by-provider/{provider_call_id}", response_model=CallByProviderResponse)
async def get_call_by_provider_id(
    provider_call_id: str,
    db: AsyncSession = Depends(get_internal_service_db),
) -> Call:
    """Look up a Call record by the telephony provider's own call identifier
    (Exotel CallSid).  Used by the outbound webhook handler to map provider
    events to our internal call records without keeping in-process state that
    would not survive a gateway restart."""
    call = (
        await db.execute(select(Call).where(Call.provider_call_id == provider_call_id))
    ).scalar_one_or_none()
    if call is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found")
    return call


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
