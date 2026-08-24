"""
SH-03 gateway wiring — Exotel callback integration tests.

Covers all required scenarios:
  - Router registration
  - JSON and form-urlencoded callbacks
  - Valid / missing / wrong webhook authentication
  - Call creation via internal API
  - Duplicate callback deduplication
  - Completion and provider-failure callbacks
  - Call finalization
  - Session create / end / remove lifecycle
  - Failure responses (no routing, bad payload)
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

# Make services/voice-gateway modules importable (exotel_routes, internal_calls, dev_routing).
_VG = str((Path(__file__).parent.parent / "services" / "voice-gateway").resolve())
if _VG not in sys.path:
    sys.path.insert(0, _VG)

from exotel_routes import build_exotel_router  # noqa: E402

# ── Shared fixtures ───────────────────────────────────────────────────────────

_TOKEN = "test-webhook-token"
_AUTH_HDR = {"X-Exotel-Webhook-Token": _TOKEN}
_FORM_HDR = {**_AUTH_HDR, "content-type": "application/x-www-form-urlencoded"}


class _Settings:
    webhook_token = _TOKEN


class _Calls:
    def __init__(self) -> None:
        self.created = None
        self.finalized = None

    async def create(self, call) -> None:
        self.created = call

    async def get(self, call_id: str):
        return None

    async def finalize(self, call_id: str, finalization) -> None:
        self.finalized = (call_id, finalization)


class _Sessions:
    def __init__(self) -> None:
        self._store: dict = {}

    def create(self, call_id: str, tenant_id: str, agent_id: str) -> None:
        self._store[call_id] = {"tenant_id": tenant_id, "agent_id": agent_id, "status": "active"}

    def get(self, call_id: str) -> dict | None:
        return self._store.get(call_id)

    def end(self, call_id: str) -> None:
        if call_id in self._store:
            self._store[call_id]["status"] = "ended"

    def remove(self, call_id: str) -> None:
        self._store.pop(call_id, None)


class _Routing:
    async def resolve(self, number: str) -> tuple[str, str]:
        return ("tenant-1", "agent-1")


def _make_client(*, calls: _Calls | None = None, routing=None):
    calls = calls or _Calls()
    sessions = _Sessions()
    fastapi_app = FastAPI()
    fastapi_app.include_router(build_exotel_router(sessions, _Settings(), calls, routing))
    return TestClient(fastapi_app), sessions, calls


# ── 1. Router registration ────────────────────────────────────────────────────


def test_callback_route_is_registered():
    """build_exotel_router places the callback endpoint at the expected path."""
    client, _, _ = _make_client()
    paths = {r.path for r in client.app.routes}
    assert "/telephony/exotel/callback" in paths


# ── 2. Webhook authentication ─────────────────────────────────────────────────


def test_missing_auth_header_returns_401():
    client, _, _ = _make_client(routing=_Routing())
    r = client.post(
        "/telephony/exotel/callback",
        json={"CallSid": "c1", "EventType": "connected", "Called": "+919"},
    )
    assert r.status_code == 401


def test_wrong_auth_token_returns_401():
    client, _, _ = _make_client(routing=_Routing())
    r = client.post(
        "/telephony/exotel/callback",
        headers={"X-Exotel-Webhook-Token": "wrong-token"},
        json={"CallSid": "c1", "EventType": "connected", "Called": "+919"},
    )
    assert r.status_code == 401


def test_valid_auth_token_is_accepted_json():
    calls = _Calls()
    client, _, _ = _make_client(calls=calls, routing=_Routing())
    r = client.post(
        "/telephony/exotel/callback",
        headers=_AUTH_HDR,
        json={"CallSid": "c1", "EventType": "connected", "Called": "+919"},
    )
    assert r.status_code == 200
    assert calls.created is not None


def test_valid_auth_token_is_accepted_form():
    calls = _Calls()
    client, _, _ = _make_client(calls=calls, routing=_Routing())
    r = client.post(
        "/telephony/exotel/callback",
        headers=_FORM_HDR,
        data={"CallSid": "c1", "EventType": "connected", "Called": "+919"},
    )
    assert r.status_code == 200
    assert calls.created is not None


# ── 3. JSON callback — start events ──────────────────────────────────────────


def test_json_start_creates_call_and_session():
    calls = _Calls()
    client, sessions, _ = _make_client(calls=calls, routing=_Routing())
    r = client.post(
        "/telephony/exotel/callback",
        headers=_AUTH_HDR,
        json={"CallSid": "exo-j-1", "EventType": "answered", "Called": "+919"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "session_started"
    call_id = body["call_id"]
    assert calls.created.call_id == call_id
    assert calls.created.provider_call_id == "exo-j-1"
    assert calls.created.tenant_id == "tenant-1"
    assert calls.created.agent_id == "agent-1"
    assert sessions.get(call_id) is not None


def test_json_start_no_routing_returns_503():
    client, _, _ = _make_client(routing=None)
    r = client.post(
        "/telephony/exotel/callback",
        headers=_AUTH_HDR,
        json={"CallSid": "c1", "EventType": "connected", "Called": "+919"},
    )
    assert r.status_code == 503


def test_json_start_missing_called_returns_422():
    client, _, _ = _make_client(routing=_Routing())
    r = client.post(
        "/telephony/exotel/callback",
        headers=_AUTH_HDR,
        json={"CallSid": "c1", "EventType": "connected"},
    )
    assert r.status_code == 422


def test_json_missing_call_sid_returns_422():
    client, _, _ = _make_client(routing=_Routing())
    r = client.post(
        "/telephony/exotel/callback",
        headers=_AUTH_HDR,
        json={"EventType": "connected", "Called": "+919"},
    )
    assert r.status_code == 422


# ── 4. Form-urlencoded callback — start events ────────────────────────────────


def test_form_start_creates_call_and_session():
    calls = _Calls()
    client, sessions, _ = _make_client(calls=calls, routing=_Routing())
    r = client.post(
        "/telephony/exotel/callback",
        headers=_FORM_HDR,
        data={"CallSid": "exo-f-1", "EventType": "answered", "Called": "+919"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "session_started"
    call_id = body["call_id"]
    assert calls.created.call_id == call_id
    assert calls.created.provider_call_id == "exo-f-1"
    assert sessions.get(call_id) is not None


def test_form_missing_auth_returns_401():
    client, _, _ = _make_client(routing=_Routing())
    r = client.post(
        "/telephony/exotel/callback",
        headers={"content-type": "application/x-www-form-urlencoded"},
        data={"CallSid": "c1", "EventType": "answered", "Called": "+919"},
    )
    assert r.status_code == 401


def test_form_missing_call_sid_returns_422():
    client, _, _ = _make_client(routing=_Routing())
    r = client.post(
        "/telephony/exotel/callback",
        headers=_FORM_HDR,
        data={"EventType": "answered", "Called": "+919"},
    )
    assert r.status_code == 422


def test_form_missing_called_returns_422():
    client, _, _ = _make_client(routing=_Routing())
    r = client.post(
        "/telephony/exotel/callback",
        headers=_FORM_HDR,
        data={"CallSid": "c1", "EventType": "answered"},
    )
    assert r.status_code == 422


# ── 5. Completion callbacks ───────────────────────────────────────────────────


def test_json_completion_finalizes_and_cleans_session():
    calls = _Calls()
    client, sessions, _ = _make_client(calls=calls, routing=_Routing())

    start = client.post(
        "/telephony/exotel/callback",
        headers=_AUTH_HDR,
        json={"CallSid": "exo-j-fin", "EventType": "answered", "Called": "+919"},
    )
    call_id = start.json()["call_id"]

    end = client.post(
        "/telephony/exotel/callback",
        headers=_AUTH_HDR,
        json={"CallSid": "exo-j-fin", "EventType": "completed"},
    )
    assert end.status_code == 200
    assert end.json()["status"] == "session_cleaned"
    assert calls.finalized is not None
    assert calls.finalized[0] == call_id
    assert calls.finalized[1].end_reason == "caller_hangup"
    assert sessions.get(call_id) is None  # removed, not just ended


def test_form_completion_finalizes_and_cleans_session():
    calls = _Calls()
    client, sessions, _ = _make_client(calls=calls, routing=_Routing())

    start = client.post(
        "/telephony/exotel/callback",
        headers=_FORM_HDR,
        data={"CallSid": "exo-f-fin", "EventType": "started", "Called": "+919"},
    )
    call_id = start.json()["call_id"]

    end = client.post(
        "/telephony/exotel/callback",
        headers=_FORM_HDR,
        data={"CallSid": "exo-f-fin", "EventType": "completed"},
    )
    assert end.status_code == 200
    assert end.json()["status"] == "session_cleaned"
    assert calls.finalized[1].end_reason == "caller_hangup"
    assert sessions.get(call_id) is None


def test_provider_failure_event_maps_to_failed_reason():
    calls = _Calls()
    client, _, _ = _make_client(calls=calls, routing=_Routing())

    start = client.post(
        "/telephony/exotel/callback",
        headers=_AUTH_HDR,
        json={"CallSid": "exo-fail", "EventType": "answered", "Called": "+919"},
    )
    call_id = start.json()["call_id"]

    end = client.post(
        "/telephony/exotel/callback",
        headers=_AUTH_HDR,
        json={"CallSid": "exo-fail", "EventType": "failed"},
    )
    assert end.status_code == 200
    assert calls.finalized[0] == call_id
    assert calls.finalized[1].end_reason == "provider_failure"


def test_disconnected_event_maps_to_hangup_reason():
    calls = _Calls()
    client, _, _ = _make_client(calls=calls, routing=_Routing())

    client.post(
        "/telephony/exotel/callback",
        headers=_AUTH_HDR,
        json={"CallSid": "exo-disc", "EventType": "answered", "Called": "+919"},
    )

    end = client.post(
        "/telephony/exotel/callback",
        headers=_AUTH_HDR,
        json={"CallSid": "exo-disc", "EventType": "disconnected"},
    )
    assert end.status_code == 200
    assert calls.finalized[1].end_reason == "caller_hangup"


# ── 6. Duplicate callback deduplication ──────────────────────────────────────


def test_duplicate_start_event_is_ignored():
    calls = _Calls()
    client, sessions, _ = _make_client(calls=calls, routing=_Routing())

    first = client.post(
        "/telephony/exotel/callback",
        headers=_AUTH_HDR,
        json={"CallSid": "exo-dup", "EventType": "answered", "Called": "+919"},
    )
    assert first.json()["status"] == "session_started"
    call_id = first.json()["call_id"]

    second = client.post(
        "/telephony/exotel/callback",
        headers=_AUTH_HDR,
        json={"CallSid": "exo-dup", "EventType": "answered", "Called": "+919"},
    )
    assert second.json()["status"] == "duplicate"
    assert second.json()["call_id"] == call_id


def test_duplicate_json_and_form_events_share_dedup_state():
    """JSON and form-encoded callbacks for the same (call_sid, event) are deduplicated."""
    calls = _Calls()
    client, _, _ = _make_client(calls=calls, routing=_Routing())

    # JSON first
    first = client.post(
        "/telephony/exotel/callback",
        headers=_AUTH_HDR,
        json={"CallSid": "exo-xfmt", "EventType": "start", "Called": "+919"},
    )
    call_id = first.json()["call_id"]

    # Form-encoded duplicate of same event
    second = client.post(
        "/telephony/exotel/callback",
        headers=_FORM_HDR,
        data={"CallSid": "exo-xfmt", "EventType": "start", "Called": "+919"},
    )
    assert second.json()["status"] == "duplicate"
    assert second.json()["call_id"] == call_id


# ── 7. Session lifecycle ──────────────────────────────────────────────────────


def test_session_create_end_remove_lifecycle():
    """Session is created on start, fully removed (not merely marked ended) on completion."""
    calls = _Calls()
    client, sessions, _ = _make_client(calls=calls, routing=_Routing())

    start = client.post(
        "/telephony/exotel/callback",
        headers=_AUTH_HDR,
        json={"CallSid": "exo-lc", "EventType": "start", "Called": "+919"},
    )
    call_id = start.json()["call_id"]
    assert sessions.get(call_id) is not None  # created

    client.post(
        "/telephony/exotel/callback",
        headers=_AUTH_HDR,
        json={"CallSid": "exo-lc", "EventType": "completed"},
    )
    assert sessions.get(call_id) is None  # removed


# ── 8. Unknown events are ignored ─────────────────────────────────────────────


def test_unknown_event_returns_ignored():
    client, _, _ = _make_client(routing=_Routing())
    r = client.post(
        "/telephony/exotel/callback",
        headers=_AUTH_HDR,
        json={"CallSid": "c1", "EventType": "ringing", "Called": "+919"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "ignored"


def test_end_event_without_prior_start_returns_ignored():
    """A completion event with no known call_id is silently ignored."""
    client, _, _ = _make_client(routing=_Routing())
    r = client.post(
        "/telephony/exotel/callback",
        headers=_AUTH_HDR,
        json={"CallSid": "unknown-sid", "EventType": "completed"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "ignored"
