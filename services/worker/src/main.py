"""Phase 6 — background worker.

Consumes durable jobs recorded by services/api's internal job/event API
(created by services/voice-gateway from Exotel webhook events), asks
services/integration-service to perform the actual integration operation,
and reports the outcome back — the worker itself never touches PostgreSQL
directly and owns no application-data persistence of its own (Postgres stays
solely owned by services/api; see jobs_client.py). Redis is only ever used as
a wake-up hint (BLPOP): if a message is dropped, the periodic poll of
services/api's "list eligible jobs" endpoint is what actually guarantees no
job is lost, since Postgres — not Redis — is the source of truth for job
state.

Single-threaded and single-job-at-a-time per process; Phase 6 achieves
concurrency, if needed, by running multiple worker replicas rather than
in-process threading — WORKER_CONCURRENCY is not consumed here (kept as a
documented placeholder for a future replica count, not intra-process
threads), which is the simplest mechanism consistent with "don't build an
elaborate distributed queue" for what this repository actually needs.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time
from types import FrameType

import httpx
import redis

from .integration_client import IntegrationClient, IntegrationError
from .jobs_client import Job, JobsApiError, JobsClient

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "info").upper(),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("staykaro-worker")

REDIS_URL = os.environ.get("REDIS_URL", "")
INTERNAL_API_URL = os.environ.get("INTERNAL_API_URL", "http://api:8000")
INTEGRATION_SERVICE_URL = os.environ.get(
    "INTEGRATION_SERVICE_URL", "http://integration-service:8002"
)

# Redis is only the wake-up hint (see module docstring) — this key holds
# job_ids pushed by services/api right after a job is durably created.
WORKER_QUEUE_KEY = os.environ.get("WORKER_QUEUE_KEY", "staykaro:jobs:queue")

# How long BLPOP blocks waiting for a wake-up before the loop falls through
# to a Postgres poll anyway. Also bounds how long graceful shutdown can take
# to notice a signal while idle — kept well under Docker's default 10s
# SIGTERM grace period.
BLPOP_TIMEOUT_SECONDS = int(os.environ.get("WORKER_BLPOP_TIMEOUT_SECONDS", "5"))
# Backoff between Postgres polls when there was nothing to do, so an idle
# worker doesn't spin: each empty BLPOP already waits BLPOP_TIMEOUT_SECONDS,
# and a failed connection additionally sleeps this long before retrying.
RETRY_BACKOFF_SECONDS = float(os.environ.get("WORKER_RETRY_BACKOFF_SECONDS", "5"))
REAP_INTERVAL_SECONDS = float(os.environ.get("WORKER_REAP_INTERVAL_SECONDS", "60"))

_shutdown = False


def _handle_signal(signum: int, _frame: FrameType | None) -> None:
    global _shutdown
    logger.info("Received signal %s — finishing current job, then shutting down", signum)
    _shutdown = True


def _connect_redis() -> redis.Redis:
    # socket_timeout intentionally left at its default (no timeout) — BLPOP's
    # own `timeout=` argument is what should govern how long the call blocks;
    # a socket-level timeout shorter than that would make the client raise
    # spuriously while genuinely waiting on a legitimate blocking command.
    return redis.Redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=5.0)


def process_one(jobs: JobsClient, integration: IntegrationClient, job_id: str) -> None:
    """Claims one job by id and drives it through processing -> completed or
    processing -> retrying/failed. Never marks a job completed before the
    integration call has actually returned success (no premature ack)."""
    job: Job | None = jobs.claim(job_id)
    if job is None:
        logger.debug("job_id=%s not claimable right now (already handled or not due yet)", job_id)
        return

    logger.info(
        "Processing job_id=%s event_type=%s attempt=%d/%d",
        job.job_id,
        job.event_type,
        job.attempts,
        job.max_attempts,
    )
    try:
        integration.process(
            job_id=job.job_id,
            tenant_id=job.tenant_id,
            call_id=job.call_id,
            event_type=job.event_type,
            payload=job.payload,
        )
    except IntegrationError as exc:
        logger.warning("job_id=%s integration failed: %s", job.job_id, exc)
        try:
            updated = jobs.fail(job.job_id, error=str(exc), retry=True)
        except JobsApiError as report_exc:
            # The job stays 'processing' in Postgres if we can't even report
            # the failure — reap() will fold it back into retrying/failed on
            # its next sweep rather than leaving it silently stuck forever.
            logger.error("job_id=%s: could not report failure: %s", job.job_id, report_exc)
            return
        if updated.status == "failed":
            logger.error(
                "job_id=%s permanently failed after %d/%d attempts",
                job.job_id,
                updated.attempts,
                updated.max_attempts,
            )
        else:
            logger.info("job_id=%s scheduled for retry (attempt %d)", job.job_id, updated.attempts)
        return

    try:
        jobs.complete(job.job_id)
    except JobsApiError as exc:
        # The integration side effect already succeeded — the risk here is
        # under-reporting success, not duplicating a side effect, and
        # complete() is idempotent server-side, so it's safe to just log and
        # let a later reap()/reconciliation pass find and correct this.
        logger.error("job_id=%s: integration succeeded but complete() failed: %s", job.job_id, exc)
        return
    logger.info("job_id=%s completed", job.job_id)


def _startup_checks(jobs: JobsClient, r: redis.Redis) -> None:
    """Validates the dependencies this worker actually uses — Redis (the
    queue) and the internal API (the durable job store's HTTP surface).
    PostgreSQL is deliberately not checked directly here: the worker never
    opens its own connection to it (see module docstring), so a direct DB
    ping would be validating a dependency this process doesn't actually
    have. Logs and continues rather than exiting non-zero on failure — a
    dependency that's briefly unready at container start is not fatal, the
    main loop already retries both continuously."""
    try:
        r.ping()
        logger.info("Startup check: Redis reachable")
    except redis.RedisError as exc:
        logger.warning("Startup check: Redis unreachable (%s) — will keep retrying", exc)

    if jobs.health():
        logger.info("Startup check: internal API reachable")
    else:
        logger.warning("Startup check: internal API unreachable — will keep retrying")


def main() -> None:
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    if not REDIS_URL:
        logger.error("REDIS_URL is not set — worker cannot start")
        sys.exit(1)

    # One persistent httpx.Client per downstream service for the worker's
    # whole lifetime — process_one() runs on every loop iteration, so
    # opening a fresh TCP connection per HTTP call (the default when no
    # client= is passed) would be wasteful for a long-running poller.
    with httpx.Client(timeout=10.0) as jobs_http, httpx.Client(timeout=10.0) as integration_http:
        jobs = JobsClient(INTERNAL_API_URL, client=jobs_http)
        integration = IntegrationClient(INTEGRATION_SERVICE_URL, client=integration_http)
        r = _connect_redis()

        _startup_checks(jobs, r)
        logger.info(
            "Staykaro worker started (queue=%s blpop_timeout=%ss reap_interval=%ss)",
            WORKER_QUEUE_KEY,
            BLPOP_TIMEOUT_SECONDS,
            REAP_INTERVAL_SECONDS,
        )
        _run_loop(jobs, integration, r)

    logger.info("Worker shutdown complete")


def _run_loop(jobs: JobsClient, integration: IntegrationClient, r: redis.Redis) -> None:
    last_reap = 0.0
    while not _shutdown:
        now = time.monotonic()
        if now - last_reap >= REAP_INTERVAL_SECONDS:
            try:
                reaped = jobs.reap()
                if reaped:
                    logger.warning("Reaped stale job(s): %s", reaped)
            except JobsApiError as exc:
                logger.warning("reap() failed: %s", exc)
            last_reap = now

        job_id: str | None = None
        try:
            popped = r.blpop([WORKER_QUEUE_KEY], timeout=BLPOP_TIMEOUT_SECONDS)
            if popped is not None:
                _key, job_id = popped
        except redis.RedisError as exc:
            logger.warning("Redis BLPOP failed (%s) — backing off before retrying", exc)
            time.sleep(RETRY_BACKOFF_SECONDS)

        if job_id is not None:
            try:
                process_one(jobs, integration, job_id)
            except JobsApiError as exc:
                # A transport-level failure talking to the internal API for
                # this specific job — don't crash the whole worker over one
                # bad job; the job (if claimed) is recovered by reap(), and
                # (if not yet claimed) remains queued for the next attempt.
                logger.error("job_id=%s: unrecoverable API error this cycle: %s", job_id, exc)
            continue

        # No Redis wake-up this cycle (timeout, or Redis itself was down) —
        # fall back to asking Postgres (via the internal API) what's
        # actually eligible right now. This is what keeps Redis a hint
        # rather than the source of truth: a lost RPUSH does not lose a job.
        try:
            for eligible in jobs.list_eligible(["queued", "retrying"], limit=10):
                if _shutdown:
                    break
                process_one(jobs, integration, eligible.job_id)
        except JobsApiError as exc:
            logger.warning("list_eligible() failed: %s", exc)
            time.sleep(RETRY_BACKOFF_SECONDS)


if __name__ == "__main__":
    main()
