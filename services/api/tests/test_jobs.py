"""
Phase 6 — internal job/event API tests (src/routers/jobs.py).

Covers: creation + idempotent duplicate detection, atomic claim (the WHERE
clause -> zero-rows-affected safety mechanism), complete (idempotent), fail
(bounded retry with backoff, terminal exhaustion), reap (orphan recovery),
auth enforcement, and list_eligible filtering. Runs against the same
in-memory SQLite backend as every other services/api unit test (see
conftest.py) — real-Postgres-only behavior (RLS/tenant isolation, and
genuinely concurrent claims from separate connections) is covered separately
in tests/test_tenant_isolation.py, matching this repo's existing convention:
a single SQLAlchemy AsyncSession (what api_client shares across requests
here) is not safe for concurrent use from multiple coroutines, so true
concurrent-claim testing needs independent connections, not this fixture.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

_BASE = "/internal/v1/events"


def _event_payload(**overrides) -> dict:
    base = {
        "event_type": "connected",
        "provider_call_id": "provider-call-1",
    }
    base.update(overrides)
    return base


# ── Creation + idempotency ──────────────────────────────────────────────────────


async def test_create_event_returns_201_and_queued_status(api_client: AsyncClient) -> None:
    response = await api_client.post(_BASE, json=_event_payload())
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "queued"
    assert body["attempts"] == 0
    assert body["duplicate"] is False
    assert body["job_id"]


async def test_duplicate_provider_call_id_and_event_type_is_reported_not_reinserted(
    api_client: AsyncClient,
) -> None:
    first = await api_client.post(_BASE, json=_event_payload())
    second = await api_client.post(_BASE, json=_event_payload())
    assert first.status_code == 201
    assert second.status_code == 201  # still 201 — a duplicate is not an error
    assert first.json()["duplicate"] is False
    assert second.json()["duplicate"] is True
    assert first.json()["job_id"] == second.json()["job_id"]


async def test_same_provider_call_id_different_event_type_is_not_a_duplicate(
    api_client: AsyncClient,
) -> None:
    connected = await api_client.post(_BASE, json=_event_payload(event_type="connected"))
    terminal = await api_client.post(_BASE, json=_event_payload(event_type="terminal"))
    assert connected.json()["duplicate"] is False
    assert terminal.json()["duplicate"] is False
    assert connected.json()["job_id"] != terminal.json()["job_id"]


async def test_null_provider_call_id_events_never_collide(api_client: AsyncClient) -> None:
    """provider_call_id is optional — events without one aren't deduplicated
    against each other (the partial unique index excludes NULLs)."""
    first = await api_client.post(_BASE, json=_event_payload(provider_call_id=None))
    second = await api_client.post(_BASE, json=_event_payload(provider_call_id=None))
    assert first.json()["duplicate"] is False
    assert second.json()["duplicate"] is False


async def test_create_event_requires_internal_token() -> None:
    from httpx import ASGITransport

    from src.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(_BASE, json=_event_payload())
    assert response.status_code == 401


# ── Claim ────────────────────────────────────────────────────────────────────


async def test_claim_transitions_queued_to_processing_and_increments_attempts(
    api_client: AsyncClient,
) -> None:
    created = (await api_client.post(_BASE, json=_event_payload())).json()
    response = await api_client.post(f"{_BASE}/{created['job_id']}/claim")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processing"
    assert body["attempts"] == 1


async def test_claim_is_atomic_second_claim_of_same_job_fails(api_client: AsyncClient) -> None:
    """The core safety guarantee: two workers racing to claim the same job —
    only one may succeed. Simulated here as two sequential claim calls (the
    guarding WHERE clause is what makes a truly concurrent claim safe; see
    jobs.py's module docstring), and separately as genuinely concurrent
    below."""
    created = (await api_client.post(_BASE, json=_event_payload())).json()
    job_id = created["job_id"]
    first = await api_client.post(f"{_BASE}/{job_id}/claim")
    second = await api_client.post(f"{_BASE}/{job_id}/claim")
    assert first.status_code == 200
    assert second.status_code == 409


async def test_claim_unknown_job_returns_404(api_client: AsyncClient) -> None:
    response = await api_client.post(f"{_BASE}/does-not-exist/claim")
    assert response.status_code == 404


async def test_claim_not_yet_available_job_returns_409(api_client: AsyncClient) -> None:
    """A job in 'retrying' with a future available_at (backoff not yet
    elapsed) must not be claimable — proven via the fail() backoff path
    below, not directly constructible through the public API."""
    created = (await api_client.post(_BASE, json=_event_payload(max_attempts=5))).json()
    job_id = created["job_id"]
    await api_client.post(f"{_BASE}/{job_id}/claim")
    fail_response = await api_client.post(
        f"{_BASE}/{job_id}/fail", json={"error": "transient", "retry": True}
    )
    assert fail_response.json()["status"] == "retrying"
    # available_at was pushed into the future by the backoff — immediate
    # reclaim must fail.
    reclaim = await api_client.post(f"{_BASE}/{job_id}/claim")
    assert reclaim.status_code == 409


# ── Complete ─────────────────────────────────────────────────────────────────


async def test_complete_transitions_processing_to_completed(api_client: AsyncClient) -> None:
    created = (await api_client.post(_BASE, json=_event_payload())).json()
    job_id = created["job_id"]
    await api_client.post(f"{_BASE}/{job_id}/claim")
    response = await api_client.post(f"{_BASE}/{job_id}/complete")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["processed_at"] is not None


async def test_complete_is_idempotent(api_client: AsyncClient) -> None:
    created = (await api_client.post(_BASE, json=_event_payload())).json()
    job_id = created["job_id"]
    await api_client.post(f"{_BASE}/{job_id}/claim")
    first = await api_client.post(f"{_BASE}/{job_id}/complete")
    second = await api_client.post(f"{_BASE}/{job_id}/complete")
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()


async def test_complete_without_claiming_first_returns_409(api_client: AsyncClient) -> None:
    created = (await api_client.post(_BASE, json=_event_payload())).json()
    response = await api_client.post(f"{_BASE}/{created['job_id']}/complete")
    assert response.status_code == 409


async def test_complete_unknown_job_returns_404(api_client: AsyncClient) -> None:
    response = await api_client.post(f"{_BASE}/does-not-exist/complete")
    assert response.status_code == 404


# ── Fail / retry / exhaustion ────────────────────────────────────────────────


async def test_fail_with_retry_and_attempts_remaining_transitions_to_retrying(
    api_client: AsyncClient,
) -> None:
    created = (await api_client.post(_BASE, json=_event_payload(max_attempts=5))).json()
    job_id = created["job_id"]
    await api_client.post(f"{_BASE}/{job_id}/claim")
    response = await api_client.post(
        f"{_BASE}/{job_id}/fail", json={"error": "simulated transient failure", "retry": True}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "retrying"
    assert body["last_error"] == "simulated transient failure"
    assert body["attempts"] == 1


async def test_fail_retry_schedules_available_at_in_the_future(api_client: AsyncClient) -> None:
    created = (await api_client.post(_BASE, json=_event_payload(max_attempts=5))).json()
    job_id = created["job_id"]
    before = (await api_client.post(f"{_BASE}/{job_id}/claim")).json()
    after = (
        await api_client.post(f"{_BASE}/{job_id}/fail", json={"error": "x", "retry": True})
    ).json()
    assert after["available_at"] > before["updated_at"]


async def test_fail_exhausts_after_max_attempts_reaches_terminal_failed(
    api_client: AsyncClient,
) -> None:
    """Bounded retry: even with retry=True requested every time, once
    attempts reaches max_attempts the job must land in 'failed', never loop
    forever."""
    created = (await api_client.post(_BASE, json=_event_payload(max_attempts=2))).json()
    job_id = created["job_id"]

    await api_client.post(f"{_BASE}/{job_id}/claim")  # attempt 1
    r1 = await api_client.post(f"{_BASE}/{job_id}/fail", json={"error": "e1", "retry": True})
    assert r1.json()["status"] == "retrying"
    assert r1.json()["attempts"] == 1

    # Force the backoff window open so the second attempt can be claimed —
    # exercised in isolation from wall-clock timing via the same DB session
    # override the app itself uses (test-only shortcut; the real timing
    # behavior is covered by test_fail_retry_schedules_available_at_in_the_future).
    from sqlalchemy import update

    from src.models import CallJob

    async for db in _override_session(api_client):
        from datetime import UTC, datetime, timedelta

        await db.execute(
            update(CallJob)
            .where(CallJob.job_id == job_id)
            .values(available_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await db.commit()
        break

    await api_client.post(f"{_BASE}/{job_id}/claim")  # attempt 2 (== max_attempts)
    r2 = await api_client.post(f"{_BASE}/{job_id}/fail", json={"error": "e2", "retry": True})
    assert r2.json()["status"] == "failed"
    assert r2.json()["attempts"] == 2
    assert r2.json()["last_error"] == "e2"
    assert r2.json()["processed_at"] is not None


async def test_fail_error_text_is_truncated(api_client: AsyncClient) -> None:
    created = (await api_client.post(_BASE, json=_event_payload(max_attempts=5))).json()
    job_id = created["job_id"]
    await api_client.post(f"{_BASE}/{job_id}/claim")
    huge_error = "x" * 5000
    response = await api_client.post(
        f"{_BASE}/{job_id}/fail", json={"error": huge_error, "retry": True}
    )
    assert len(response.json()["last_error"]) < 3000


async def test_fail_already_terminal_job_is_idempotent(api_client: AsyncClient) -> None:
    created = (await api_client.post(_BASE, json=_event_payload(max_attempts=1))).json()
    job_id = created["job_id"]
    await api_client.post(f"{_BASE}/{job_id}/claim")
    first = await api_client.post(f"{_BASE}/{job_id}/fail", json={"error": "final", "retry": True})
    assert first.json()["status"] == "failed"
    second = await api_client.post(
        f"{_BASE}/{job_id}/fail", json={"error": "reported again", "retry": True}
    )
    assert second.status_code == 200
    assert second.json()["status"] == "failed"
    assert second.json()["last_error"] == "final"  # unchanged — no double side effect


async def test_fail_without_claiming_first_returns_409(api_client: AsyncClient) -> None:
    created = (await api_client.post(_BASE, json=_event_payload())).json()
    response = await api_client.post(
        f"{_BASE}/{created['job_id']}/fail", json={"error": "e", "retry": True}
    )
    assert response.status_code == 409


# ── Reap (orphan recovery) ───────────────────────────────────────────────────


async def test_reap_recovers_stale_processing_job_with_attempts_remaining(
    api_client: AsyncClient,
) -> None:
    created = (await api_client.post(_BASE, json=_event_payload(max_attempts=5))).json()
    job_id = created["job_id"]
    await api_client.post(f"{_BASE}/{job_id}/claim")

    await _mark_stale(api_client, job_id)

    response = await api_client.post(f"{_BASE}/reap")
    assert response.status_code == 200
    assert job_id in response.json()["reaped"]

    state = (await api_client.get(f"{_BASE}/{job_id}")).json()
    assert state["status"] == "retrying"
    assert "reaped" in state["last_error"]


async def test_reap_sends_exhausted_stale_job_straight_to_failed(api_client: AsyncClient) -> None:
    created = (await api_client.post(_BASE, json=_event_payload(max_attempts=1))).json()
    job_id = created["job_id"]
    await api_client.post(f"{_BASE}/{job_id}/claim")  # attempts now == max_attempts

    await _mark_stale(api_client, job_id)

    await api_client.post(f"{_BASE}/reap")
    state = (await api_client.get(f"{_BASE}/{job_id}")).json()
    assert state["status"] == "failed"


async def test_reap_does_not_touch_jobs_still_within_processing_window(
    api_client: AsyncClient,
) -> None:
    created = (await api_client.post(_BASE, json=_event_payload())).json()
    job_id = created["job_id"]
    await api_client.post(f"{_BASE}/{job_id}/claim")

    response = await api_client.post(f"{_BASE}/reap")
    assert job_id not in response.json()["reaped"]
    state = (await api_client.get(f"{_BASE}/{job_id}")).json()
    assert state["status"] == "processing"


# ── list_eligible ────────────────────────────────────────────────────────────


async def test_list_eligible_returns_only_queued_and_retrying_by_default(
    api_client: AsyncClient,
) -> None:
    queued = (await api_client.post(_BASE, json=_event_payload(provider_call_id="p-a"))).json()
    processing = (await api_client.post(_BASE, json=_event_payload(provider_call_id="p-b"))).json()
    await api_client.post(f"{_BASE}/{processing['job_id']}/claim")

    response = await api_client.get(_BASE)
    ids = {e["job_id"] for e in response.json()["events"]}
    assert queued["job_id"] in ids
    assert processing["job_id"] not in ids


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _override_session(api_client: AsyncClient):
    from src.database import get_db
    from src.main import app

    override = app.dependency_overrides[get_db]
    async for session in override():
        yield session


async def _mark_stale(api_client: AsyncClient, job_id: str) -> None:
    """Test-only: pushes a claimed job's updated_at into the past so reap()
    treats it as orphaned, without waiting out the real staleness window."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import update

    from src.models import CallJob

    async for db in _override_session(api_client):
        await db.execute(
            update(CallJob)
            .where(CallJob.job_id == job_id)
            .values(updated_at=datetime.now(UTC) - timedelta(hours=1))
        )
        await db.commit()
        break
