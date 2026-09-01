"""Integration Service — outbound calling pipeline.

Receives one HTTP call per job from services/worker.  For outbound_dial jobs
it calls the Exotel API (or simulates when credentials are absent) and then
calls back to services/api's internal API to update the Caller record and
create the voice-gateway Call record.

The provider boundary is this service: the worker, job queue, and webhook
routing never change; only what is inside process_event() changes as we wire
up real external APIs.

Owns no PostgreSQL persistence of its own — application data stays owned by
services/api; this service reaches it exclusively via the internal HTTP API.
"""

from __future__ import annotations

import hmac
import logging
import os
import uuid
from datetime import UTC, datetime
from typing import Optional

import httpx
import redis
from fastapi import Depends, FastAPI, Header, HTTPException, Response, status
from pydantic import BaseModel

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "info").upper(),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("staykaro.integration-service")

app = FastAPI(title="Staykaro Integration Service", version="0.3.0")

INTERNAL_API_TOKEN = os.environ.get("INTERNAL_API_TOKEN", "")
_REDIS_URL = os.environ.get("REDIS_URL", "")
_REDIS_SOCKET_TIMEOUT_SECS = 2.0

_redis_client: redis.Redis | None = None
if _REDIS_URL:
    try:
        _redis_client = redis.Redis.from_url(
            _REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=_REDIS_SOCKET_TIMEOUT_SECS,
            socket_timeout=_REDIS_SOCKET_TIMEOUT_SECS,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis unavailable at startup: %s", exc)
else:
    logger.warning("REDIS_URL is not set — /health will report redis as not_configured")


async def _verify_internal_token(
    x_internal_api_token: Optional[str] = Header(default=None),
) -> None:
    if (
        not INTERNAL_API_TOKEN
        or not x_internal_api_token
        or not hmac.compare_digest(x_internal_api_token, INTERNAL_API_TOKEN)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing internal API token",
        )


@app.get("/health")
async def health(response: Response) -> dict[str, str]:
    redis_status = "not_configured"
    if _redis_client is not None:
        try:
            _redis_client.ping()
            redis_status = "ok"
        except redis.RedisError as exc:
            logger.warning("Health Redis check failed: %s", exc)
            redis_status = "unreachable"

    is_healthy = redis_status != "unreachable"
    if not is_healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ok" if is_healthy else "degraded",
        "service": "staykaro-integration-service",
        "redis": redis_status,
    }


@app.get("/")
async def root() -> dict[str, str]:
    return {"service": "staykaro-integration-service", "status": "ok"}


# ── Internal processing contract ──────────────────────────────────────────────


class ProcessEventRequest(BaseModel):
    job_id: str
    tenant_id: Optional[str] = None
    call_id: Optional[str] = None
    event_type: str
    payload: Optional[dict] = None


class ProcessEventResponse(BaseModel):
    status: str
    detail: str


# ── Outbound dial helpers ──────────────────────────────────────────────────────


def _internal_headers() -> dict[str, str]:
    return {"X-Internal-API-Token": INTERNAL_API_TOKEN} if INTERNAL_API_TOKEN else {}


def _internal_post(base_url: str, path: str, body: dict, timeout: float = 10.0) -> dict:
    """Synchronous POST to services/api's /internal/v1/* surface."""
    url = base_url.rstrip("/") + path
    try:
        r = httpx.post(url, json=body, headers=_internal_headers(), timeout=timeout)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Internal API call failed ({path}): {exc}") from exc


def _internal_patch(base_url: str, path: str, body: dict, timeout: float = 10.0) -> dict:
    url = base_url.rstrip("/") + path
    try:
        r = httpx.patch(url, json=body, headers=_internal_headers(), timeout=timeout)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Internal API PATCH failed ({path}): {exc}") from exc


def _place_exotel_call(
    *,
    api_key: str,
    api_token: str,
    account_sid: str,
    caller_id: str,
    to_number: str,
    status_callback_url: str,
) -> str:
    """Call the Exotel outbound dial API and return the provider CallSid.

    Exotel's connect.json endpoint places a call from `caller_id` (an Exotel
    virtual number) to `to_number` (the customer).  Authentication uses HTTP
    Basic with the API key and token (not the account SID).
    Raises RuntimeError on any API failure so the worker can retry the job.
    """
    url = (
        f"https://api.exotel.com/v1/Accounts/{account_sid}/Calls/connect.json"
    )
    data: dict[str, str] = {
        "From": to_number,
        "To": caller_id,
        "CallerId": caller_id,
        "TimeLimit": "3600",  # 1-hour safety cap; real calls rarely hit this
    }
    if status_callback_url:
        data["StatusCallback"] = status_callback_url

    try:
        r = httpx.post(
            url,
            data=data,
            auth=(api_key, api_token),
            timeout=15.0,
        )
        r.raise_for_status()
        payload = r.json()
        call_sid: str | None = (
            payload.get("Call", {}).get("Sid")
            or payload.get("CallSid")
            or payload.get("call_sid")
        )
        if not call_sid:
            raise RuntimeError(f"Exotel response missing CallSid: {payload!r}")
        logger.info("Exotel call placed: CallSid=%s to=%s", call_sid, to_number)
        return call_sid
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Exotel API request failed: {exc}") from exc


def _handle_outbound_dial(body: ProcessEventRequest) -> ProcessEventResponse:
    """Place an outbound call via Exotel (or simulate when credentials are
    absent) and update services/api's database via the internal HTTP API.

    The sequence is:
      1. Call Exotel API → get provider CallSid (or generate simulation ID)
      2. POST /internal/v1/calls  — create a Call record linked to the Caller
      3. PATCH /internal/v1/call-requests/{id}/dialed  — set Caller.status=dialing
      4. (Simulation only) POST /internal/v1/calls/{id}/finalize immediately
         with end_reason='simulation_complete' so the Caller reaches a terminal
         state that is clearly labelled as simulated in the dashboard.

    All HTTP failures propagate as RuntimeError → the worker marks the job for
    retry rather than permanently failing a call that was never attempted.
    """
    payload = body.payload or {}
    caller_id: int | None = payload.get("caller_id")
    phone_number: str = payload.get("phone_number", "")
    tenant_id: str = payload.get("tenant_id") or body.tenant_id or ""


    if caller_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="outbound_dial payload missing caller_id",
        )
    if not phone_number:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="outbound_dial payload missing phone_number",
        )

    api_base_url = os.environ.get("API_BASE_URL", "http://api:8000")
    exotel_key = os.environ.get("EXOTEL_API_KEY", "")
    exotel_token = os.environ.get("EXOTEL_API_TOKEN", "")
    exotel_sid = os.environ.get("EXOTEL_ACCOUNT_SID", "")
    exotel_caller_id = os.environ.get("EXOTEL_CALLER_ID", "")
    status_callback_url = os.environ.get("EXOTEL_OUTBOUND_CALLBACK_URL", "")

    is_simulation = not all([exotel_key, exotel_token, exotel_sid, exotel_caller_id])

    if is_simulation:
        logger.warning(
            "SIMULATION MODE: Exotel credentials not configured. "
            "Call for caller_id=%s will be marked is_simulation=True. "
            "Set EXOTEL_API_KEY, EXOTEL_API_TOKEN, EXOTEL_ACCOUNT_SID, "
            "EXOTEL_CALLER_ID to enable real outbound calling.",
            caller_id,
        )
        provider_call_id = f"sim-{uuid.uuid4()}"
    else:
        try:
            provider_call_id = _place_exotel_call(
                api_key=exotel_key,
                api_token=exotel_token,
                account_sid=exotel_sid,
                caller_id=exotel_caller_id,
                to_number=phone_number,
                status_callback_url=status_callback_url,
            )
        except RuntimeError as exc:
            # Propagate so the worker can retry this job — do NOT silently
            # mark the call as anything other than failed/retrying.
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            ) from exc

    # Create a Call record in services/api so the webhook handler can resolve
    # provider events back to our internal IDs, and so the transcript endpoint
    # has somewhere to attach CallTurn rows if a voice session is later added.
    call_uuid = str(uuid.uuid4())
    try:
        _internal_post(
            api_base_url,
            "/internal/v1/calls",
            {
                "call_id": call_uuid,
                "tenant_id": tenant_id,
                "agent_id": "campaign-dialer",
                "started_at": datetime.now(UTC).isoformat(),
                "provider_call_id": provider_call_id,
                "is_simulation": is_simulation,
                "connection_status": "not_attempted",
                "call_request_id": caller_id,
            },
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    # Link the Caller work-item to the Call record and mark it as dialing.
    try:
        _internal_patch(
            api_base_url,
            f"/internal/v1/call-requests/{caller_id}/dialed",
            {"telephony_call_id": call_uuid, "is_simulation": is_simulation},
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    logger.info(
        "Outbound dial %s: caller_id=%s call_uuid=%s provider_call_id=%s is_simulation=%s",
        "simulated" if is_simulation else "placed",
        caller_id, call_uuid, provider_call_id, is_simulation,
    )

    # For simulation: immediately finalize the Call so dashboards reflect a
    # terminal state rather than leaving it perpetually in "dialing".  The
    # is_simulation flag ensures these are never shown as real calls.
    if is_simulation:
        try:
            _internal_post(
                api_base_url,
                f"/internal/v1/calls/{call_uuid}/finalize",
                {
                    "ended_at": datetime.now(UTC).isoformat(),
                    "end_reason": "simulation_complete",
                },
            )
        except RuntimeError as exc:
            # Non-fatal: the call record exists, and the worker job still
            # completes successfully.  The Caller may stay in "dialing" until
            # the next reap cycle resolves it, but no data is lost.
            logger.warning("Simulation finalize failed (non-fatal): %s", exc)

    mode = "simulation" if is_simulation else "live"
    return ProcessEventResponse(
        status="processed",
        detail=(
            f"outbound_dial {mode}: caller_id={caller_id} "
            f"provider_call_id={provider_call_id}"
        ),
    )


def process_event(body: ProcessEventRequest) -> ProcessEventResponse:
    """Route incoming jobs to the appropriate handler.

    `_test_force_failure` — documented failure-injection hook used by Phase 6
    retry/exhaustion tests (same pattern as EXOTEL_DEV_ROUTING): triggered
    only when a caller explicitly sets payload._test_force_failure=True, never
    on its own.
    """
    if isinstance(body.payload, dict) and body.payload.get("_test_force_failure"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="forced failure for testing (payload._test_force_failure)",
        )

    if not body.event_type.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="event_type must not be empty",
        )

    if body.event_type == "outbound_dial":
        return _handle_outbound_dial(body)

    logger.info(
        "Processed event: job_id=%s event_type=%s tenant_id=%s call_id=%s",
        body.job_id,
        body.event_type,
        body.tenant_id,
        body.call_id,
    )
    return ProcessEventResponse(
        status="processed",
        detail=f"event {body.event_type!r} acknowledged for job {body.job_id}",
    )


@app.post(
    "/internal/v1/process",
    response_model=ProcessEventResponse,
    dependencies=[Depends(_verify_internal_token)],
)
async def process(body: ProcessEventRequest) -> ProcessEventResponse:
    return process_event(body)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",  # nosec B104
        port=int(os.getenv("INTEGRATION_SERVICE_PORT", 8002)),
        log_level=os.getenv("LOG_LEVEL", "info"),
    )
