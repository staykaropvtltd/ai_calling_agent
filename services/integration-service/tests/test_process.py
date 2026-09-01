"""Phase 6 — integration-service unit tests.

Covers: the real internal /internal/v1/process contract — auth enforcement,
successful processing, validation failure, and the documented
_test_force_failure hook used to exercise Phase 6's retry/exhaustion
behavior against a genuine HTTP failure (see src/main.py's process_event()
docstring) rather than a mocked one.

Loads services/integration-service/src/main.py under a private module name
(no relative/package-internal imports here, unlike services/worker, so no
package-context setup is needed — see tests/test_gateway_callbacks.py for
why this repo needs private names at all: services/api/tests/conftest.py
already claims the plain name `src` in this pytest session).
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Plain assignment, not setdefault: services/api/tests/conftest.py (which
# may run earlier in the same pytest session) already sets INTERNAL_API_TOKEN
# to its own different value, and this module needs its own deterministic
# value at the exact moment _IS.main is exec'd below — each private-loaded
# module gets its own independent copy of module-level state, so this
# doesn't affect any other test file's already-imported modules.
_TEST_TOKEN = "test-integration-token"
os.environ["INTERNAL_API_TOKEN"] = _TEST_TOKEN
os.environ["REDIS_URL"] = ""  # not_configured is a valid, tested state

_IS_MAIN = (Path(__file__).parent.parent / "src" / "main.py").resolve()
_spec = importlib.util.spec_from_file_location("_integration_service_main", str(_IS_MAIN))
_IS = importlib.util.module_from_spec(_spec)
sys.modules["_integration_service_main"] = _IS
_spec.loader.exec_module(_IS)  # type: ignore[union-attr]

client = TestClient(_IS.app)
_TOKEN = _TEST_TOKEN


def test_health_returns_ok_shape():
    response = client.get("/health")
    assert response.status_code in (200, 503)
    body = response.json()
    assert body["service"] == "staykaro-integration-service"
    assert "redis" in body


def test_process_requires_internal_token():
    response = client.post(
        "/internal/v1/process",
        json={"job_id": "j1", "event_type": "connected", "payload": None},
    )
    assert response.status_code == 401


def test_process_rejects_wrong_token():
    response = client.post(
        "/internal/v1/process",
        headers={"X-Internal-API-Token": "wrong"},
        json={"job_id": "j1", "event_type": "connected", "payload": None},
    )
    assert response.status_code == 401


def test_process_succeeds_with_valid_token():
    response = client.post(
        "/internal/v1/process",
        headers={"X-Internal-API-Token": _TOKEN},
        json={
            "job_id": "j1",
            "tenant_id": "t1",
            "call_id": "c1",
            "event_type": "connected",
            "payload": {"dialed_number": "+911234567890"},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processed"
    assert "j1" in body["detail"]


def test_process_succeeds_with_null_payload():
    response = client.post(
        "/internal/v1/process",
        headers={"X-Internal-API-Token": _TOKEN},
        json={"job_id": "j2", "event_type": "terminal", "payload": None},
    )
    assert response.status_code == 200


def test_process_rejects_empty_event_type():
    response = client.post(
        "/internal/v1/process",
        headers={"X-Internal-API-Token": _TOKEN},
        json={"job_id": "j3", "event_type": "   ", "payload": None},
    )
    assert response.status_code == 422


def test_process_test_force_failure_hook_returns_503():
    """The explicit, documented failure-injection path Phase 6's retry/
    exhaustion tests rely on — a real HTTP 503, not a mock."""
    response = client.post(
        "/internal/v1/process",
        headers={"X-Internal-API-Token": _TOKEN},
        json={
            "job_id": "j4",
            "event_type": "connected",
            "payload": {"_test_force_failure": True},
        },
    )
    assert response.status_code == 503


def test_process_without_force_failure_flag_succeeds():
    """Confirms the hook is opt-in — an ordinary payload dict never
    accidentally triggers it."""
    response = client.post(
        "/internal/v1/process",
        headers={"X-Internal-API-Token": _TOKEN},
        json={
            "job_id": "j5",
            "event_type": "connected",
            "payload": {"dialed_number": "+911234567890", "call_status": "completed"},
        },
    )
    assert response.status_code == 200


@pytest.mark.parametrize("force_value", [False, 0, None, ""])
def test_process_falsy_force_failure_values_do_not_trigger(force_value):
    response = client.post(
        "/internal/v1/process",
        headers={"X-Internal-API-Token": _TOKEN},
        json={
            "job_id": "j6",
            "event_type": "connected",
            "payload": {"_test_force_failure": force_value},
        },
    )
    assert response.status_code == 200


def test_process_event_function_directly_success():
    """process_event() is a plain function independent of the FastAPI
    request/response cycle — worth testing directly too, not only through
    the HTTP layer above."""
    body = _IS.ProcessEventRequest(job_id="j7", event_type="connected", payload=None)
    result = _IS.process_event(body)
    assert result.status == "processed"


# ── outbound_dial handler ─────────────────────────────────────────────────────


def test_outbound_dial_missing_caller_id_returns_422():
    """outbound_dial without caller_id in payload is a client error, not retryable."""
    response = client.post(
        "/internal/v1/process",
        headers={"X-Internal-API-Token": _TOKEN},
        json={
            "job_id": "od-1",
            "event_type": "outbound_dial",
            "payload": {"phone_number": "+917001234567", "tenant_id": "1"},
        },
    )
    assert response.status_code == 422


def test_outbound_dial_missing_phone_number_returns_422():
    response = client.post(
        "/internal/v1/process",
        headers={"X-Internal-API-Token": _TOKEN},
        json={
            "job_id": "od-2",
            "event_type": "outbound_dial",
            "payload": {"caller_id": 42, "tenant_id": "1"},
        },
    )
    assert response.status_code == 422


def test_outbound_dial_simulation_fails_closed_when_api_unreachable(monkeypatch):
    """When API_BASE_URL is unreachable, outbound_dial returns 503 so the worker
    retries rather than silently dropping the call.  No Exotel creds are set,
    so this exercises the simulation code path (no real Exotel call)."""
    monkeypatch.setenv("API_BASE_URL", "http://localhost:19999")
    for key in ("EXOTEL_API_KEY", "EXOTEL_API_TOKEN", "EXOTEL_ACCOUNT_SID", "EXOTEL_CALLER_ID"):
        monkeypatch.delenv(key, raising=False)

    # Re-import os inside the module so the patched values are visible
    # The module reads env vars at call-time (not import-time), so no reload needed.
    response = client.post(
        "/internal/v1/process",
        headers={"X-Internal-API-Token": _TOKEN},
        json={
            "job_id": "od-3",
            "event_type": "outbound_dial",
            "payload": {
                "caller_id": 42,
                "phone_number": "+917001234567",
                "tenant_id": "1",
                "campaign_id": "camp-1",
                "campaign_contact_id": "cc-1",
            },
        },
    )
    # 503: internal API unreachable → worker should schedule a retry, not drop the job
    assert response.status_code == 503
