"""Phase 6 — worker unit tests.

Covers: JobsClient/IntegrationClient HTTP wrapper behavior (status-code
handling, error wrapping — via httpx.MockTransport, no real network) and
process_one()'s orchestration (successful processing, retryable failure,
terminal failure via a fake JobsClient/IntegrationClient — real-infrastructure
verification of the whole worker loop against real Docker Postgres/Redis/api/
integration-service is a separate, mandatory pass documented in the Phase 6
report, not repeated here as a slow/flaky unit test).

Loads services/worker/src as a privately-named package so its modules (which
use relative imports, matching the Docker CMD's `python -m src.main`) don't
collide with services/api's and services/integration-service's own `src`
packages already imported under the plain name `src` elsewhere in the same
pytest session — see tests/test_gateway_callbacks.py for the first place
this repo hit and solved the same problem, for services/voice-gateway.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

import httpx
import pytest

_WORKER_SRC = (Path(__file__).parent.parent / "src").resolve()

if "_worker_src" not in sys.modules:
    _pkg_spec = importlib.util.spec_from_file_location(
        "_worker_src",
        str(_WORKER_SRC / "__init__.py"),
        submodule_search_locations=[str(_WORKER_SRC)],
    )
    _pkg = importlib.util.module_from_spec(_pkg_spec)
    sys.modules["_worker_src"] = _pkg
    _pkg_spec.loader.exec_module(_pkg)  # type: ignore[union-attr]

worker_main = importlib.import_module("_worker_src.main")
jobs_client_mod = importlib.import_module("_worker_src.jobs_client")
integration_client_mod = importlib.import_module("_worker_src.integration_client")

Job = jobs_client_mod.Job
JobsApiError = jobs_client_mod.JobsApiError
JobsClient = jobs_client_mod.JobsClient
IntegrationClient = integration_client_mod.IntegrationClient
IntegrationError = integration_client_mod.IntegrationError
process_one = worker_main.process_one


def _job(**overrides) -> Job:
    base = {
        "job_id": "job-1",
        "tenant_id": "tenant-1",
        "call_id": "call-1",
        "provider_call_id": "provider-1",
        "event_type": "connected",
        "payload": None,
        "status": "processing",
        "attempts": 1,
        "max_attempts": 5,
        "last_error": None,
    }
    base.update(overrides)
    return Job(**base)


def _jobs_client(handler) -> JobsClient:
    http = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://fake-api")
    return JobsClient(base_url="http://fake-api", client=http)


def _integration_client(handler) -> IntegrationClient:
    http = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://fake-integration")
    return IntegrationClient(base_url="http://fake-integration", client=http)


# ── JobsClient (HTTP wrapper) ────────────────────────────────────────────────


def test_jobs_client_claim_returns_job_on_200():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/internal/v1/events/job-1/claim"
        return httpx.Response(200, json=_job().model_dump())

    client = _jobs_client(handler)
    result = client.claim("job-1")
    assert result is not None
    assert result.job_id == "job-1"
    assert result.status == "processing"


def test_jobs_client_claim_returns_none_on_409():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"detail": "not claimable"})

    assert _jobs_client(handler).claim("job-1") is None


def test_jobs_client_claim_returns_none_on_404():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "not found"})

    assert _jobs_client(handler).claim("job-1") is None


def test_jobs_client_claim_raises_on_5xx():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "boom"})

    with pytest.raises(JobsApiError):
        _jobs_client(handler).claim("job-1")


def test_jobs_client_sends_internal_auth_header(monkeypatch):
    monkeypatch.setattr(jobs_client_mod, "_INTERNAL_API_TOKEN", "test-token-123")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["token"] = request.headers.get("X-Internal-API-Token")
        return httpx.Response(200, json={"reaped": []})

    _jobs_client(handler).reap()
    assert seen["token"] == "test-token-123"


def test_jobs_client_health_true_on_200():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok"})

    assert _jobs_client(handler).health() is True


def test_jobs_client_health_false_on_transport_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    assert _jobs_client(handler).health() is False


def test_jobs_client_fail_sends_error_and_retry_flag():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content
        return httpx.Response(200, json=_job(status="retrying").model_dump())

    result = _jobs_client(handler).fail("job-1", error="boom", retry=True)
    assert result.status == "retrying"
    assert b'"error":"boom"' in seen["body"]
    assert b'"retry":true' in seen["body"]


def test_jobs_client_list_eligible_parses_events():
    def handler(request: httpx.Request) -> httpx.Response:
        assert dict(request.url.params).get("limit") == "10"
        return httpx.Response(
            200, json={"events": [_job(job_id="a").model_dump(), _job(job_id="b").model_dump()]}
        )

    results = _jobs_client(handler).list_eligible(["queued", "retrying"], limit=10)
    assert [j.job_id for j in results] == ["a", "b"]


# ── IntegrationClient (HTTP wrapper) ─────────────────────────────────────────


def test_integration_client_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/internal/v1/process"
        return httpx.Response(200, json={"status": "processed", "detail": "ok"})

    result = _integration_client(handler).process(
        job_id="j1", tenant_id="t1", call_id="c1", event_type="connected", payload=None
    )
    assert result.status == "processed"


def test_integration_client_raises_on_5xx():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="down")

    with pytest.raises(IntegrationError):
        _integration_client(handler).process(
            job_id="j1", tenant_id=None, call_id=None, event_type="x", payload=None
        )


def test_integration_client_raises_on_4xx():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, text="bad event")

    with pytest.raises(IntegrationError):
        _integration_client(handler).process(
            job_id="j1", tenant_id=None, call_id=None, event_type="x", payload=None
        )


def test_integration_client_transport_error_wrapped():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with pytest.raises(IntegrationError):
        _integration_client(handler).process(
            job_id="j1", tenant_id=None, call_id=None, event_type="x", payload=None
        )


# ── process_one() orchestration ─────────────────────────────────────────────


class _FakeJobsClient:
    def __init__(self, job: Job | None):
        self._job = job
        self.completed: list[str] = []
        self.failed: list[tuple[str, str, bool]] = []

    def claim(self, job_id: str) -> Job | None:
        return self._job

    def complete(self, job_id: str) -> None:
        self.completed.append(job_id)

    def fail(self, job_id: str, error: str, retry: bool = True) -> Job:
        self.failed.append((job_id, error, retry))
        attempts = self._job.attempts
        if retry and attempts < self._job.max_attempts:
            return _job(job_id=job_id, status="retrying", attempts=attempts)
        return _job(job_id=job_id, status="failed", attempts=attempts)


class _FakeIntegrationClient:
    def __init__(self, should_fail: bool = False):
        self.should_fail = should_fail
        self.calls: list[dict] = []

    def process(self, **kwargs):
        self.calls.append(kwargs)
        if self.should_fail:
            raise IntegrationError("simulated failure")
        return integration_client_mod.ProcessResult(status="processed", detail="ok")


def test_process_one_claims_processes_and_completes_on_success():
    job = _job(job_id="j1")
    jobs = _FakeJobsClient(job)
    integration = _FakeIntegrationClient(should_fail=False)

    process_one(jobs, integration, "j1")

    assert jobs.completed == ["j1"]
    assert jobs.failed == []
    assert integration.calls[0]["job_id"] == "j1"
    assert integration.calls[0]["event_type"] == "connected"


def test_process_one_skips_when_job_not_claimable():
    jobs = _FakeJobsClient(None)  # claim() returns None
    integration = _FakeIntegrationClient()

    process_one(jobs, integration, "j1")

    assert jobs.completed == []
    assert jobs.failed == []
    assert integration.calls == []  # never even attempted


def test_process_one_reports_failure_to_jobs_client_on_integration_error():
    job = _job(job_id="j1", attempts=1, max_attempts=5)
    jobs = _FakeJobsClient(job)
    integration = _FakeIntegrationClient(should_fail=True)

    process_one(jobs, integration, "j1")

    assert jobs.completed == []
    assert len(jobs.failed) == 1
    failed_job_id, error, retry = jobs.failed[0]
    assert failed_job_id == "j1"
    assert "simulated failure" in error
    assert retry is True


def test_process_one_never_completes_a_job_that_failed_integration():
    """The core "no premature ack" guarantee — complete() must only be
    called after the integration call actually returns success."""
    job = _job(job_id="j1")
    jobs = _FakeJobsClient(job)
    integration = _FakeIntegrationClient(should_fail=True)

    process_one(jobs, integration, "j1")

    assert "j1" not in jobs.completed
