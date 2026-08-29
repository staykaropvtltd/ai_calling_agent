"""Phase 6 — internal durable job/event API.

Consumed by services/voice-gateway (creates jobs from webhook events) and
services/worker (claims, completes, fails, and reconciles them). No JWT/user
identity — same trust boundary as routers/internal.py, protected by the same
verify_internal_token shared secret and always operating with the
__all_tenants__ bypass sentinel (see src/tenant.py::get_internal_service_db):
this is a trusted, network-internal surface, not a tenant-facing one.

PostgreSQL is the sole durable source of truth for job state (Constraint #1
in the Phase 6 plan) — the worker and integration-service never open their
own connection to it; every state transition below is a single atomic SQL
UPDATE guarded by a WHERE clause on the row's current status, which is what
makes claim() safe against two workers claiming the same job concurrently
(Constraint #10) without needing SELECT ... FOR UPDATE SKIP LOCKED: Postgres
serializes concurrent UPDATEs to the same row, and the second writer's WHERE
clause simply no longer matches once the first has committed the transition.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated, Optional

import redis
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import case, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from src.config import REDIS_URL
from src.models import CallJob
from src.routers.internal import verify_internal_token
from src.tenant import get_internal_service_db

logger = logging.getLogger("staykaro.jobs")

router = APIRouter(
    prefix="/internal/v1/events",
    tags=["internal-jobs"],
    dependencies=[Depends(verify_internal_token)],
)

# Redis is only ever the worker's wake-up hint, never the source of truth
# (Constraint #12) — a job is fully durable in Postgres the moment this
# router's create_event() commits, whether or not this RPUSH below ever
# reaches Redis or Redis is configured at all. A failed/absent push just
# means the worker finds the job on its next periodic poll instead of
# immediately, never that the job is lost.
WORKER_QUEUE_KEY = "staykaro:jobs:queue"

# Short timeout deliberately — this is a best-effort optimization on the
# create_event() request path (see the comment above), so every call must
# fail fast rather than hold up the caller's response for multiple seconds
# whenever Redis is unreachable: redis-py has no successful connection to
# reuse in that case, so every RPUSH pays this timeout in full, not just the
# first one.
_REDIS_NOTIFY_TIMEOUT_SECS = 0.5

_redis: redis.Redis | None = None
if REDIS_URL:
    try:
        _redis = redis.Redis.from_url(
            REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=_REDIS_NOTIFY_TIMEOUT_SECS,
            socket_timeout=_REDIS_NOTIFY_TIMEOUT_SECS,
        )
    except Exception as exc:  # noqa: BLE001 - never let a bad REDIS_URL break startup
        logger.warning("Redis unavailable for job queue wake-up signal: %s", exc)


def _notify_worker(job_id: str) -> None:
    if _redis is None:
        return
    try:
        _redis.rpush(WORKER_QUEUE_KEY, job_id)
    except redis.RedisError as exc:
        logger.warning(
            "Failed to push job_id=%s wake-up to Redis (worker will poll instead): %s", job_id, exc
        )


# Error text is persisted (last_error) and may end up in operator-facing
# tooling later — bounded so a pathological/adversarial error string can't
# grow the row (and the table) without limit. Never expected to carry raw
# audio or transcript content: callers pass short, typed failure reasons.
_MAX_ERROR_CHARS = 2000

# A job stuck in 'processing' longer than this almost certainly means the
# worker that claimed it crashed or lost connectivity mid-work — reap() folds
# it back into the retry/failed lifecycle instead of leaving it stranded.
_STALE_PROCESSING_SECONDS = 120

_TERMINAL_STATUSES = {"completed", "failed"}
_CLAIMABLE_STATUSES = ("queued", "retrying")

_BASE_BACKOFF_SECONDS = 5
_MAX_BACKOFF_SECONDS = 300


def _backoff_seconds(attempts: int) -> int:
    """Exponential backoff, capped — deterministic and bounded per Constraint #11."""
    return min(_BASE_BACKOFF_SECONDS * (2 ** max(attempts - 1, 0)), _MAX_BACKOFF_SECONDS)


def _truncate_error(error: str) -> str:
    if len(error) <= _MAX_ERROR_CHARS:
        return error
    return error[:_MAX_ERROR_CHARS] + "...(truncated)"


# ── Schemas ──────────────────────────────────────────────────────────────────


class EventCreateRequest(BaseModel):
    event_type: str = Field(min_length=1, max_length=50)
    provider_call_id: Optional[str] = None
    tenant_id: Optional[str] = None
    call_id: Optional[str] = None
    payload: Optional[dict] = None
    max_attempts: Optional[int] = Field(default=None, ge=1, le=20)


class EventFailRequest(BaseModel):
    error: str = Field(min_length=1)
    retry: bool = True


class EventResponse(BaseModel):
    job_id: str
    tenant_id: Optional[str]
    call_id: Optional[str]
    provider_call_id: Optional[str]
    event_type: str
    payload: Optional[dict]
    status: str
    attempts: int
    max_attempts: int
    last_error: Optional[str]
    created_at: datetime
    updated_at: datetime
    available_at: datetime
    processed_at: Optional[datetime]

    model_config = {"from_attributes": True}


class EventCreateResponse(EventResponse):
    duplicate: bool = False


class EventListResponse(BaseModel):
    events: list[EventResponse]


class ReapResponse(BaseModel):
    reaped: list[str]


# ── Routes ───────────────────────────────────────────────────────────────────


@router.post("", response_model=EventCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_event(
    body: EventCreateRequest,
    db: AsyncSession = Depends(get_internal_service_db),
) -> EventCreateResponse:
    """Durably records one operational event, idempotently.

    The authoritative idempotency guarantee (Constraint #7): a second call
    with the same (provider_call_id, event_type) hits the partial unique
    index added in the Phase 6 migration and is reported back as the
    existing row (duplicate=True), never inserted twice — replacing the
    in-memory set exotel_routes.py used to rely on, which could not survive
    a gateway restart.
    """
    job = CallJob(
        tenant_id=body.tenant_id,
        call_id=body.call_id,
        provider_call_id=body.provider_call_id,
        event_type=body.event_type,
        payload=body.payload,
        **({"max_attempts": body.max_attempts} if body.max_attempts is not None else {}),
    )
    db.add(job)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        if body.provider_call_id is None:
            raise  # not a dedup collision — something else is wrong
        existing = await db.scalar(
            select(CallJob).where(
                CallJob.provider_call_id == body.provider_call_id,
                CallJob.event_type == body.event_type,
            )
        )
        if existing is None:
            raise
        logger.info(
            "Duplicate event ignored: provider_call_id=%s event_type=%s existing_job_id=%s",
            body.provider_call_id,
            body.event_type,
            existing.job_id,
        )
        return EventCreateResponse(
            duplicate=True, **EventResponse.model_validate(existing).model_dump()
        )

    await db.refresh(job)
    logger.info("Event recorded: job_id=%s event_type=%s", job.job_id, job.event_type)
    # Only after the durable row is committed — the wake-up signal is purely
    # an optimization (see WORKER_QUEUE_KEY note above), never a substitute
    # for the row actually existing.
    _notify_worker(job.job_id)
    return EventCreateResponse(duplicate=False, **EventResponse.model_validate(job).model_dump())


@router.get("", response_model=EventListResponse)
async def list_eligible_events(
    statuses: Annotated[list[str], Query(alias="status")] = ["queued", "retrying"],  # noqa: B006
    limit: int = Query(default=20, ge=1, le=200),
    db: AsyncSession = Depends(get_internal_service_db),
) -> EventListResponse:
    """Lists jobs eligible for claiming right now — the worker's periodic
    poll fallback (Constraint #12: Redis is only a wake-up hint, never the
    source of truth, so a dropped/lost Redis message must still be
    recoverable by asking Postgres directly)."""
    rows = await db.scalars(
        select(CallJob)
        .where(CallJob.status.in_(statuses))
        .where(CallJob.available_at <= func.now())
        .order_by(CallJob.available_at.asc())
        .limit(limit)
    )
    return EventListResponse(events=[EventResponse.model_validate(r) for r in rows.all()])


@router.get("/{job_id}", response_model=EventResponse)
async def get_event(job_id: str, db: AsyncSession = Depends(get_internal_service_db)) -> CallJob:
    # populate_existing=True (also used by every other db.get(CallJob, ...)
    # in this module): forces a fresh SELECT even if this job_id's row is
    # already in the session's identity map from an earlier call — without
    # it, a row left expired by reap_stale_jobs()'s synchronize_session=
    # "fetch" would return stale/unpopulated attributes here, and FastAPI's
    # response serialization runs outside the async context needed to lazy-
    # load them (a bare AttributeError-adjacent MissingGreenlet failure).
    job = await db.get(CallJob, job_id, populate_existing=True)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
    return job


@router.post("/{job_id}/claim", response_model=EventResponse)
async def claim_event(job_id: str, db: AsyncSession = Depends(get_internal_service_db)) -> CallJob:
    """Atomically transitions queued|retrying -> processing.

    A single UPDATE guarded by the row's current status and availability —
    Postgres's row-level locking on UPDATE is what makes this safe against
    two workers claiming the same job_id concurrently (Constraint #10): the
    second UPDATE to reach this row blocks behind the first's row lock, then
    re-evaluates its WHERE clause once the first commits — status is no
    longer 'queued'/'retrying' by then, so it matches zero rows.
    """
    stmt = (
        update(CallJob)
        .execution_options(synchronize_session=False)
        .where(CallJob.job_id == job_id)
        .where(CallJob.status.in_(_CLAIMABLE_STATUSES))
        .where(CallJob.available_at <= func.now())
        .values(status="processing", attempts=CallJob.attempts + 1, updated_at=func.now())
        .returning(CallJob)
    )
    result = await db.execute(stmt)
    job = result.scalar_one_or_none()
    if job is None:
        await db.rollback()
        existing = await db.get(CallJob, job_id, populate_existing=True)
        if existing is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"job not claimable in status={existing.status!r}",
        )
    await db.commit()
    await db.refresh(job)
    logger.info("Job claimed: job_id=%s attempts=%d", job.job_id, job.attempts)
    return job


@router.post("/{job_id}/complete", response_model=EventResponse)
async def complete_event(
    job_id: str, db: AsyncSession = Depends(get_internal_service_db)
) -> CallJob:
    """Transitions processing -> completed. Idempotent: completing an
    already-completed job (e.g. the worker's HTTP call succeeded but the
    response was lost, and it retries) is a safe no-op, not an error —
    required so a network blip on the *reporting* call never causes a
    completed job to be mistaken for a failure and retried."""
    existing = await db.get(CallJob, job_id, populate_existing=True)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
    if existing.status == "completed":
        return existing
    if existing.status != "processing":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"cannot complete job in status={existing.status!r}",
        )
    stmt = (
        update(CallJob)
        .execution_options(synchronize_session=False)
        .where(CallJob.job_id == job_id)
        .where(CallJob.status == "processing")
        .values(status="completed", processed_at=func.now(), updated_at=func.now())
        .returning(CallJob)
    )
    result = await db.execute(stmt)
    job = result.scalar_one_or_none()
    if job is None:
        # Raced with something else since the check above — re-read and
        # report the current state rather than silently pretending success.
        await db.rollback()
        current = await db.get(CallJob, job_id, populate_existing=True)
        if current is not None and current.status == "completed":
            return current
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="job state changed concurrently"
        )
    await db.commit()
    await db.refresh(job)
    logger.info("Job completed: job_id=%s", job.job_id)
    return job


@router.post("/{job_id}/fail", response_model=EventResponse)
async def fail_event(
    job_id: str, body: EventFailRequest, db: AsyncSession = Depends(get_internal_service_db)
) -> CallJob:
    """Transitions processing -> retrying (bounded) or -> failed (terminal).

    Bounded, deterministic retry per Constraint #11: retrying is only chosen
    when the caller asks for it AND attempts < max_attempts; once attempts
    has reached max_attempts the job always lands in the terminal 'failed'
    state on this call, regardless of `retry`, so a job can never retry
    forever.
    """
    existing = await db.get(CallJob, job_id, populate_existing=True)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
    if existing.status in _TERMINAL_STATUSES:
        # Idempotent: a duplicate failure report about an already-terminal
        # job changes nothing.
        return existing
    if existing.status != "processing":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"cannot fail job in status={existing.status!r}",
        )

    sanitized_error = _truncate_error(body.error)
    can_retry = body.retry and existing.attempts < existing.max_attempts
    if can_retry:
        new_status = "retrying"
        # Computed in Python, not SQL (e.g. Postgres's make_interval()) —
        # keeps this portable to the SQLite-backed unit test suite and
        # avoids a dialect-specific function for what's just simple
        # arithmetic on a value we already have in hand.
        new_available_at = datetime.now(UTC) + timedelta(
            seconds=_backoff_seconds(existing.attempts)
        )
        processed_at_value = None
    else:
        new_status = "failed"
        new_available_at = CallJob.available_at  # unchanged — terminal, never claimed again
        processed_at_value = func.now()

    stmt = (
        update(CallJob)
        .execution_options(synchronize_session=False)
        .where(CallJob.job_id == job_id)
        .where(CallJob.status == "processing")
        .values(
            status=new_status,
            last_error=sanitized_error,
            available_at=new_available_at,
            updated_at=func.now(),
            **({"processed_at": processed_at_value} if processed_at_value is not None else {}),
        )
        .returning(CallJob)
    )
    result = await db.execute(stmt)
    job = result.scalar_one_or_none()
    if job is None:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="job state changed concurrently"
        )
    await db.commit()
    await db.refresh(job)
    logger.info(
        "Job %s: job_id=%s attempts=%d/%d error=%s",
        "will retry" if new_status == "retrying" else "permanently failed",
        job.job_id,
        job.attempts,
        job.max_attempts,
        sanitized_error[:200],
    )
    return job


@router.post("/reap", response_model=ReapResponse)
async def reap_stale_jobs(db: AsyncSession = Depends(get_internal_service_db)) -> ReapResponse:
    """Recovers jobs orphaned by a worker crash/restart mid-processing
    (Constraint #12 / "no orphaned processing state remains"): a job stuck
    in 'processing' well past any plausible processing time is folded back
    into 'retrying' (if attempts remain) or 'failed' (if exhausted) — never
    left silently stuck, and never re-attempted unboundedly either. Safe to
    call repeatedly/concurrently: each affected row is only ever touched by
    one of the racing UPDATEs, same guard pattern as claim/complete/fail.
    """
    # Computed in Python for the same portability reason as fail_event()'s
    # backoff above — no Postgres-specific interval function.
    stale_cutoff = datetime.now(UTC) - timedelta(seconds=_STALE_PROCESSING_SECONDS)
    stmt = (
        update(CallJob)
        # This is a multi-row, criteria-based bulk update, unlike
        # claim/complete/fail's single-row-by-job_id updates elsewhere in
        # this module. SQLAlchemy's default "evaluate" sync strategy
        # re-checks the WHERE clause against in-memory ORM objects in
        # Python, which breaks on SQLite backends where a
        # DateTime(timezone=True) column round-trips as a naive datetime
        # (can't compare it to the timezone-aware `stale_cutoff` above).
        # "fetch" instead runs a real SELECT to find affected rows — no
        # Python-side datetime comparison — and correctly expires any of
        # those rows already loaded elsewhere in this session, which a bare
        # synchronize_session=False would silently leave stale.
        .execution_options(synchronize_session="fetch")
        .where(CallJob.status == "processing")
        .where(CallJob.updated_at < stale_cutoff)
        .values(
            status=case(
                (CallJob.attempts < CallJob.max_attempts, "retrying"),
                else_="failed",
            ),
            available_at=func.now(),
            processed_at=case(
                (CallJob.attempts < CallJob.max_attempts, None),
                else_=func.now(),
            ),
            last_error=func.coalesce(
                CallJob.last_error, "reaped: worker did not report completion in time"
            ),
            updated_at=func.now(),
        )
        .returning(CallJob.job_id)
    )
    result = await db.execute(stmt)
    reaped = [row[0] for row in result.all()]
    await db.commit()
    if reaped:
        logger.warning("Reaped %d stale processing job(s): %s", len(reaped), reaped)
    return ReapResponse(reaped=reaped)
