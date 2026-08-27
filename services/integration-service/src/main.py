"""Phase 6 — Integration Service.

Receives one HTTP call per job from services/worker and performs "the
integration operation" for that event. This repository defines no external
vendor contract (no real Exotel/CRM/notification API is wired up anywhere),
so per the Phase 6 scope this endpoint implements and tests the real
*internal* contract only: validating the event and acknowledging it,
deterministically and idempotently. The provider boundary is this one
endpoint — a real external integration later replaces only what's inside
`process_event()` below, never the worker or the job/event API around it.

Owns no PostgreSQL persistence of its own (Constraint #1/#2 — application
data stays owned by services/api); it is intentionally stateless about job
history and reports success/failure back to the caller synchronously.
"""

from __future__ import annotations

import hmac
import logging
import os
from typing import Optional

import redis
from fastapi import Depends, FastAPI, Header, HTTPException, Response, status
from pydantic import BaseModel

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "info").upper(),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("staykaro.integration-service")

app = FastAPI(title="Staykaro Integration Service", version="0.2.0")

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
    except Exception as exc:  # noqa: BLE001 - never let a bad REDIS_URL crash startup
        logger.warning("Redis unavailable at startup: %s", exc)
else:
    logger.warning("REDIS_URL is not set — /health will report redis as not_configured")


async def _verify_internal_token(
    x_internal_api_token: Optional[str] = Header(default=None),
) -> None:
    """Same shared-secret guard as services/api/src/routers/internal.py —
    this endpoint has no JWT/user identity and must not be reachable by an
    untrusted caller. Empty/unset token fails closed."""
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


def process_event(body: ProcessEventRequest) -> ProcessEventResponse:
    """The real internal operation: validates and acknowledges the event.

    `_test_force_failure` is a documented, explicit test/failure-injection
    hook — the same pattern this repository already uses for
    EXOTEL_DEV_ROUTING (services/voice-gateway/dev_routing.py): a real,
    working code path that is only ever triggered by a caller that
    deliberately asks for it, never something that fires on its own. It
    lets Phase 6's retry/exhaustion behavior be exercised against a real
    HTTP failure from this service, not a mocked one.
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

    # Binding 0.0.0.0 is required here, not incidental: this must be
    # reachable from other containers (worker, nginx) on the Docker bridge
    # network — equivalent to every other service's Dockerfile CMD
    # (`uvicorn ... --host 0.0.0.0`), which bandit never sees since it's a
    # shell string, not Python. Not internet-facing either way:
    # docker-compose.prod.yml gives this service `ports: []`, so no host
    # port is ever published for it.
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",  # nosec B104
        port=int(os.getenv("INTEGRATION_SERVICE_PORT", 8002)),
        log_level=os.getenv("LOG_LEVEL", "info"),
    )
