"""
SH-03 / SH-04 gateway wiring — Exotel callback integration tests.

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
  - CallStore persistence: set on start, get on end, delete after finalization
  - Simulated gateway restart: router B finalizes a call started by router A
  - _RedisCallStore unit tests via _FakeRedis
  - Voice WebSocket endpoint (/ws/{call_id}) sharing the same session_manager
    as the Exotel callback router — the CP1 "empty call lifecycle" path
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

# Make services/voice-gateway modules importable (exotel_routes, internal_calls, dev_routing).
_VG = str((Path(__file__).parent.parent / "services" / "voice-gateway").resolve())
if _VG not in sys.path:
    sys.path.insert(0, _VG)

from exotel_routes import build_exotel_router  # noqa: E402
from voice_pipeline import build_voice_router  # noqa: E402

# services/api/tests/conftest.py imports `from src.main import app` during collection,
# placing services/api/src/main into sys.modules under the name "src.main".  A direct
# `from src.main import _RedisCallStore` would therefore resolve to the wrong module.
# Load the gateway's src/main.py explicitly under a private module name to avoid that.
#
# src/main.py builds its module-level `session_manager`/`_shared_redis` from
# REDIS_URL at import time, and the websocket tests below exercise that real
# session_manager directly (unlike the Exotel callback tests in this file,
# which build their own router with _FakeRedis and never touch it). Match the
# project's "no real DB/Redis needed for unit tests" convention (see
# services/api/tests/conftest.py's REDIS_URL comment) by forcing REDIS_URL
# unset for this one import, so session_manager falls back to its already-
# supported in-memory-only mode instead of trying to reach a real Redis that
# isn't running in CI. Without this, session_manager.get()/.create() block on
# a real (unbounded, synchronous) connection attempt to an unreachable Redis,
# which previously caused test_voice_websocket_creates_and_removes_session to
# fail nondeterministically depending on which of two independent, similarly
# slow Redis calls (this test's own session_manager.get() vs. the websocket
# handler's) happened to time out and fall back to None first.
_saved_redis_url = os.environ.pop("REDIS_URL", None)
try:
    _gw_main_path = Path(_VG) / "src" / "main.py"
    _gw_spec = importlib.util.spec_from_file_location("_voice_gateway_main", str(_gw_main_path))
    _GW_MAIN = importlib.util.module_from_spec(_gw_spec)
    # Register before exec_module so that @dataclass can resolve the module's __dict__.
    sys.modules["_voice_gateway_main"] = _GW_MAIN
    _gw_spec.loader.exec_module(_GW_MAIN)  # type: ignore[union-attr]
finally:
    if _saved_redis_url is not None:
        os.environ["REDIS_URL"] = _saved_redis_url

# ── CallStore test helpers ────────────────────────────────────────────────────


class _FakeCallStore:
    """Shared in-memory CallStore for testing persistent store behavior.

    Instances are shared across router instances to simulate a real external
    store (e.g. Redis) that survives process restarts.
    """

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def set(self, provider_call_id: str, call_id: str) -> None:
        self._store[provider_call_id] = call_id

    def get(self, provider_call_id: str) -> str | None:
        return self._store.get(provider_call_id)

    def delete(self, provider_call_id: str) -> None:
        self._store.pop(provider_call_id, None)


class _FakeEventRecorder:
    """Phase 6 — shared durable EventRecorder double, mirroring
    _FakeCallStore above: instances can be shared across router instances to
    simulate a real external store (services/api's call_jobs table via
    EventsClient) that survives a gateway restart, unlike
    exotel_routes.py's own default _InMemoryEventRecorder fallback.
    """

    def __init__(self) -> None:
        self._seen: set[tuple[str, str]] = set()
        self.calls: list[dict] = []

    async def record(
        self,
        *,
        provider_call_id: str,
        event_type: str,
        tenant_id: str | None = None,
        call_id: str | None = None,
        payload: dict | None = None,
    ) -> bool:
        self.calls.append(
            {
                "provider_call_id": provider_call_id,
                "event_type": event_type,
                "tenant_id": tenant_id,
                "call_id": call_id,
                "payload": payload,
            }
        )
        key = (provider_call_id, event_type)
        if key in self._seen:
            return True
        self._seen.add(key)
        return False


class _FailingEventRecorder:
    """Always reports the durable store as unreachable — exercises the
    fail-closed 503 path (see exotel_routes.py's callback handler)."""

    async def record(self, **kwargs) -> bool:
        from internal_calls import InternalApiError

        raise InternalApiError("events API unavailable")


class _FakeRedis:
    """Minimal Redis substitute for testing _RedisCallStore without a real server.

    Only implements the operations used by _RedisCallStore: set (with optional
    ex TTL — ignored here), get, and delete (variadic).
    """

    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._data[key] = value

    def get(self, key: str) -> str | None:
        return self._data.get(key)

    def delete(self, *keys: str) -> int:
        deleted = 0
        for k in keys:
            if k in self._data:
                del self._data[k]
                deleted += 1
        return deleted


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


def _make_client(*, calls: _Calls | None = None, routing=None, call_store=None, events=None):
    calls = calls or _Calls()
    sessions = _Sessions()
    fastapi_app = FastAPI()
    fastapi_app.include_router(
        build_exotel_router(sessions, _Settings(), calls, routing, call_store, events)
    )
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


# ── 6b. Phase 6 — durable EventRecorder wiring ───────────────────────────────
#
# The in-memory dedup set exercised above (via _make_client's default
# _InMemoryEventRecorder) is no longer the authoritative idempotency
# mechanism — a real EventRecorder (EventsClient, backed by services/api's
# call_jobs table) is. These tests wire in a fake EventRecorder to prove the
# router actually defers to it, the same way _FakeCallStore above proves the
# router defers to CallStore rather than its own state.


def test_event_recorder_is_called_with_provider_call_id_and_event_type():
    events = _FakeEventRecorder()
    client, _, _ = _make_client(routing=_Routing(), events=events)
    client.post(
        "/telephony/exotel/callback",
        headers=_AUTH_HDR,
        json={"CallSid": "exo-events-1", "EventType": "answered", "Called": "+919"},
    )
    assert len(events.calls) == 1
    assert events.calls[0]["provider_call_id"] == "exo-events-1"
    assert events.calls[0]["event_type"] == "answered"


def test_event_recorder_duplicate_short_circuits_before_any_side_effect():
    """When the durable recorder itself reports a duplicate, the router must
    not repeat call creation/finalization or touch the session — the
    guarantee Constraint #7 asks for, proven at the call-side-effect level,
    not just the HTTP response shape."""
    events = _FakeEventRecorder()
    calls = _Calls()
    client, sessions, _ = _make_client(calls=calls, routing=_Routing(), events=events)

    first = client.post(
        "/telephony/exotel/callback",
        headers=_AUTH_HDR,
        json={"CallSid": "exo-events-2", "EventType": "answered", "Called": "+919"},
    )
    assert first.json()["status"] == "session_started"
    assert calls.created is not None
    created_call_id = calls.created.call_id

    calls.created = None  # reset to prove the duplicate doesn't re-create
    second = client.post(
        "/telephony/exotel/callback",
        headers=_AUTH_HDR,
        json={"CallSid": "exo-events-2", "EventType": "answered", "Called": "+919"},
    )
    assert second.json()["status"] == "duplicate"
    assert second.json()["call_id"] == created_call_id
    assert calls.created is None  # calls.create() was never called again
    assert sessions.get(created_call_id) is not None  # untouched, still active


def test_event_recorder_unavailable_fails_closed_with_503():
    """The durable store is now authoritative (Constraint #7) — if it can't
    be reached, the router must not silently fall through to reprocessing
    (or to silently dropping) the event; it fails closed, the same pattern
    already used for calls.create/finalize failures below."""
    events = _FailingEventRecorder()
    calls = _Calls()
    client, _, _ = _make_client(calls=calls, routing=_Routing(), events=events)

    response = client.post(
        "/telephony/exotel/callback",
        headers=_AUTH_HDR,
        json={"CallSid": "exo-events-3", "EventType": "answered", "Called": "+919"},
    )
    assert response.status_code == 503
    assert calls.created is None  # never reached the create step


def test_event_recorder_durable_dedup_survives_simulated_restart():
    """The exact scenario the durable recorder exists to fix: router A
    handles an event, router B (a fresh instance — simulating a gateway
    restart, empty in-memory state) shares the same durable recorder and
    must still recognize the event as a duplicate. With the OLD in-memory-
    only design (this router's own default fallback), router B would have
    processed it a second time."""
    shared_events = _FakeEventRecorder()

    calls_a = _Calls()
    client_a, _, _ = _make_client(calls=calls_a, routing=_Routing(), events=shared_events)
    first = client_a.post(
        "/telephony/exotel/callback",
        headers=_AUTH_HDR,
        json={"CallSid": "exo-events-restart", "EventType": "answered", "Called": "+919"},
    )
    assert first.json()["status"] == "session_started"

    # Router B: fresh instance, no in-memory dedup state of its own — but
    # the same durable recorder as router A.
    calls_b = _Calls()
    client_b, _, _ = _make_client(calls=calls_b, routing=_Routing(), events=shared_events)
    second = client_b.post(
        "/telephony/exotel/callback",
        headers=_AUTH_HDR,
        json={"CallSid": "exo-events-restart", "EventType": "answered", "Called": "+919"},
    )
    assert second.json()["status"] == "duplicate"
    assert calls_b.created is None  # router B never re-created the call


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


# ── 9. CallStore persistence ──────────────────────────────────────────────────


def test_call_store_set_on_start_event():
    """Start event writes provider_call_id → call_id into the call store."""
    store = _FakeCallStore()
    calls = _Calls()
    client, _, _ = _make_client(calls=calls, routing=_Routing(), call_store=store)

    r = client.post(
        "/telephony/exotel/callback",
        headers=_AUTH_HDR,
        json={"CallSid": "exo-ps-1", "EventType": "answered", "Called": "+919"},
    )
    assert r.status_code == 200
    call_id = r.json()["call_id"]
    assert store.get("exo-ps-1") == call_id


def test_persistent_store_survives_router_restart():
    """Simulate gateway restart: router A handles the start, router B handles the end.

    Router B has an empty in-memory state but shares the same persistent store as A.
    The end event must finalize — NOT return {"status": "ignored"}.
    """
    store = _FakeCallStore()

    # Router A: receives the start event and writes to the shared store
    calls_a = _Calls()
    client_a, _, _ = _make_client(calls=calls_a, routing=_Routing(), call_store=store)
    start = client_a.post(
        "/telephony/exotel/callback",
        headers=_AUTH_HDR,
        json={"CallSid": "exo-restart", "EventType": "answered", "Called": "+919"},
    )
    assert start.status_code == 200
    call_id = start.json()["call_id"]
    assert store.get("exo-restart") == call_id  # mapping persisted

    # Router B: fresh instance (no in-memory provider_calls), same persistent store
    calls_b = _Calls()
    client_b, _, _ = _make_client(calls=calls_b, routing=_Routing(), call_store=store)
    end = client_b.post(
        "/telephony/exotel/callback",
        headers=_AUTH_HDR,
        json={"CallSid": "exo-restart", "EventType": "completed"},
    )
    assert end.status_code == 200
    assert end.json()["status"] == "session_cleaned"
    assert calls_b.finalized is not None
    assert calls_b.finalized[0] == call_id
    assert calls_b.finalized[1].end_reason == "caller_hangup"


def test_call_store_deleted_after_finalization():
    """Mapping is removed from the store only after successful finalization."""
    store = _FakeCallStore()
    client, _, _ = _make_client(routing=_Routing(), call_store=store)

    client.post(
        "/telephony/exotel/callback",
        headers=_AUTH_HDR,
        json={"CallSid": "exo-del", "EventType": "answered", "Called": "+919"},
    )
    assert store.get("exo-del") is not None

    end = client.post(
        "/telephony/exotel/callback",
        headers=_AUTH_HDR,
        json={"CallSid": "exo-del", "EventType": "completed"},
    )
    assert end.json()["status"] == "session_cleaned"
    assert store.get("exo-del") is None


def test_call_store_not_deleted_when_finalization_fails():
    """If finalization raises InternalApiError the mapping is preserved for retry."""
    from internal_calls import InternalApiError

    class _FailingCalls:
        async def create(self, call) -> None:
            pass

        async def get(self, call_id: str):
            return None

        async def finalize(self, call_id: str, finalization) -> None:
            raise InternalApiError("downstream API unavailable")

    store = _FakeCallStore()
    client, _, _ = _make_client(calls=_FailingCalls(), routing=_Routing(), call_store=store)

    client.post(
        "/telephony/exotel/callback",
        headers=_AUTH_HDR,
        json={"CallSid": "exo-nodel", "EventType": "answered", "Called": "+919"},
    )
    assert store.get("exo-nodel") is not None  # mapping stored

    end = client.post(
        "/telephony/exotel/callback",
        headers=_AUTH_HDR,
        json={"CallSid": "exo-nodel", "EventType": "completed"},
    )
    assert end.status_code == 503
    # Mapping preserved — not deleted — so the end event can be retried
    assert store.get("exo-nodel") is not None


def test_call_store_none_uses_in_memory_fallback():
    """call_store=None falls back to an in-memory dict (backward compatibility)."""
    calls = _Calls()
    client, sessions, _ = _make_client(calls=calls, routing=_Routing(), call_store=None)

    r = client.post(
        "/telephony/exotel/callback",
        headers=_AUTH_HDR,
        json={"CallSid": "exo-compat", "EventType": "answered", "Called": "+919"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "session_started"
    call_id = r.json()["call_id"]

    end = client.post(
        "/telephony/exotel/callback",
        headers=_AUTH_HDR,
        json={"CallSid": "exo-compat", "EventType": "completed"},
    )
    assert end.json()["status"] == "session_cleaned"
    assert end.json()["call_id"] == call_id


def test_duplicate_callback_still_works_with_call_store():
    """Duplicate dedup returns the stored call_id even when using a persistent store."""
    store = _FakeCallStore()
    calls = _Calls()
    client, _, _ = _make_client(calls=calls, routing=_Routing(), call_store=store)

    first = client.post(
        "/telephony/exotel/callback",
        headers=_AUTH_HDR,
        json={"CallSid": "exo-dup-ps", "EventType": "answered", "Called": "+919"},
    )
    assert first.json()["status"] == "session_started"
    call_id = first.json()["call_id"]

    second = client.post(
        "/telephony/exotel/callback",
        headers=_AUTH_HDR,
        json={"CallSid": "exo-dup-ps", "EventType": "answered", "Called": "+919"},
    )
    assert second.json()["status"] == "duplicate"
    assert second.json()["call_id"] == call_id


# ── 10. _RedisCallStore unit tests ────────────────────────────────────────────


def test_redis_call_store_set_get_delete():
    """Basic set / get / delete round-trip via _FakeRedis."""
    store = _GW_MAIN._RedisCallStore(_FakeRedis())

    store.set("exo-r1", "call-uuid-1")
    assert store.get("exo-r1") == "call-uuid-1"

    store.delete("exo-r1")
    assert store.get("exo-r1") is None


def test_redis_call_store_uses_namespaced_key():
    """Keys stored in Redis are prefixed with voice_gateway:provider_call:"""
    r = _FakeRedis()
    store = _GW_MAIN._RedisCallStore(r)
    store.set("exo-ns", "call-uuid-ns")

    keys = list(r._data.keys())
    assert len(keys) == 1
    assert keys[0] == "voice_gateway:provider_call:exo-ns"


def test_redis_call_store_get_missing_returns_none():
    store = _GW_MAIN._RedisCallStore(_FakeRedis())
    assert store.get("does-not-exist") is None


def test_redis_call_store_redis_error_is_handled_gracefully():
    """RedisError in get / set / delete does not propagate to the caller."""
    import redis as _redis_pkg

    class _ErrorRedis:
        def set(self, key, value, **kwargs):
            raise _redis_pkg.RedisError("connection refused")

        def get(self, key):
            raise _redis_pkg.RedisError("connection refused")

        def delete(self, *keys):
            raise _redis_pkg.RedisError("connection refused")

    store = _GW_MAIN._RedisCallStore(_ErrorRedis())
    assert store.get("x") is None  # does not raise
    store.set("x", "y")  # does not raise (warning logged)
    store.delete("x")  # does not raise


# ── 10. Phase 4 — Exotel's documented real field/event names ───────────────
# developer.exotel.com's StatusCallback reference and Pipecat's own Exotel
# integration guide (checked directly, not assumed) both give `To` for the
# dialed number and `terminal`/`Status` for call end — not this project's
# original `Called`/`completed`|`failed`|`disconnected` guess. Both forms
# are accepted (see translate_exotel_fields) since it's unconfirmed which
# this project's actual configured callback sends without a real sandbox.


def test_json_start_accepts_documented_to_field():
    calls = _Calls()
    client, sessions, _ = _make_client(calls=calls, routing=_Routing())
    r = client.post(
        "/telephony/exotel/callback",
        headers=_AUTH_HDR,
        json={"CallSid": "exo-to-1", "EventType": "answered", "To": "+919"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "session_started"
    assert calls.created.tenant_id == "tenant-1"


def test_terminal_event_with_completed_status_finalizes_as_caller_hangup():
    calls = _Calls()
    client, sessions, _ = _make_client(calls=calls, routing=_Routing())
    client.post(
        "/telephony/exotel/callback",
        headers=_AUTH_HDR,
        json={"CallSid": "exo-term-1", "EventType": "answered", "To": "+919"},
    )
    r = client.post(
        "/telephony/exotel/callback",
        headers=_AUTH_HDR,
        json={"CallSid": "exo-term-1", "EventType": "terminal", "Status": "completed"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "session_cleaned"
    assert calls.finalized[1].end_reason == "caller_hangup"


def test_terminal_event_with_failed_status_finalizes_as_provider_failure():
    calls = _Calls()
    client, sessions, _ = _make_client(calls=calls, routing=_Routing())
    client.post(
        "/telephony/exotel/callback",
        headers=_AUTH_HDR,
        json={"CallSid": "exo-term-2", "EventType": "answered", "To": "+919"},
    )
    r = client.post(
        "/telephony/exotel/callback",
        headers=_AUTH_HDR,
        json={"CallSid": "exo-term-2", "EventType": "terminal", "Status": "no-answer"},
    )
    assert r.status_code == 200
    assert calls.finalized[1].end_reason == "provider_failure"


def test_callback_accepts_get_with_query_string():
    """Exotel's Passthru applet — the documented mechanism for this
    integration style — delivers a GET with the payload as a query string,
    not a POST body."""
    calls = _Calls()
    client, sessions, _ = _make_client(calls=calls, routing=_Routing())
    r = client.get(
        "/telephony/exotel/callback",
        params={
            "token": _TOKEN,
            "CallSid": "exo-get-1",
            "EventType": "answered",
            "To": "+919",
        },
    )
    assert r.status_code == 200
    assert r.json()["status"] == "session_started"


def test_callback_query_param_token_accepted_without_header():
    """Passthru URLs can't carry custom headers — a `token` query param on
    the configured callback URL is the realistic auth mechanism."""
    calls = _Calls()
    client, sessions, _ = _make_client(calls=calls, routing=_Routing())
    r = client.post(
        f"/telephony/exotel/callback?token={_TOKEN}",
        json={"CallSid": "exo-qtok-1", "EventType": "answered", "To": "+919"},
    )
    assert r.status_code == 200


def test_callback_wrong_query_token_and_no_header_rejected():
    client, _, _ = _make_client(routing=_Routing())
    r = client.post(
        "/telephony/exotel/callback?token=wrong",
        json={"CallSid": "exo-qtok-2", "EventType": "answered", "To": "+919"},
    )
    assert r.status_code == 401


# ── 9. Voice WebSocket endpoint (SH-03) ─────────────────────────────────────────
# Exercises the real production app (_GW_MAIN.app), not an isolated router —
# this is what proves the WebSocket handler and the Exotel callback router
# actually share one session_manager instance.


def test_voice_websocket_route_is_registered():
    # A pre-existing session (as the Exotel callback or internal API would
    # create) is required to connect since the Phase 4 unresolved-call_id
    # rejection landed — see test_voice_websocket_rejects_unknown_call_id_by_default.
    call_id = "test-ws-route"
    _GW_MAIN.session_manager.create(call_id, tenant_id="t", agent_id="a")
    client = TestClient(_GW_MAIN.app)
    with client.websocket_connect(f"/ws/{call_id}"):
        pass


def test_voice_websocket_rejects_unknown_call_id_by_default():
    """Phase 4: /ws/{call_id} is reachable from the public internet (Exotel
    connects here directly), so a call_id with no session already created via
    an authenticated path (Exotel callback or the internal API) must be
    rejected, not silently turned into a free, unauthenticated way to create
    live session state for any caller-chosen call_id. _GW_MAIN.app is built
    with EXOTEL_DEV_ROUTING unset (see module setup above), i.e. the
    production default: allow_unresolved_sessions=False."""
    client = TestClient(_GW_MAIN.app)
    call_id = "test-ws-unresolved-rejected"

    # close() before accept() means TestClient raises on connect itself, not
    # on a subsequent receive — there's no accepted connection to enter.
    with pytest.raises(WebSocketDisconnect) as exc_info, client.websocket_connect(f"/ws/{call_id}"):
        pass
    assert exc_info.value.code == 4404

    assert _GW_MAIN.session_manager.get(call_id) is None


def test_voice_websocket_dev_flag_allows_fallback_session():
    """The documented dev/test convenience (connect without any prior
    callback) still works when explicitly opted into via
    allow_unresolved_sessions=True (wired to EXOTEL_DEV_ROUTING in
    src/main.py) — verified here against an isolated router, not _GW_MAIN.app,
    so it doesn't depend on env state at module-import time."""
    class _NullSTT:
        async def transcribe(self, audio: bytes, sample_rate: int) -> str:
            return ""

    class _NullAI:
        async def generate_response(self, turns) -> str:
            return ""

    class _NullTTS:
        async def synthesize(self, text: str):
            return b"", 8000

    sessions = _Sessions()
    fastapi_app = FastAPI()
    fastapi_app.include_router(
        build_voice_router(
            sessions,
            stt_provider=_NullSTT(),
            ai_provider=_NullAI(),
            tts_provider=_NullTTS(),
            allow_unresolved_sessions=True,
        )
    )
    client = TestClient(fastapi_app)
    call_id = "test-ws-dev-flag-fallback"

    with client.websocket_connect(f"/ws/{call_id}"):
        session = sessions.get(call_id)
        assert session is not None
        assert session["tenant_id"] == "unknown"
        assert session["status"] == "active"

    assert sessions.get(call_id) is None


def test_voice_websocket_reuses_session_created_by_callback():
    """A session already created via the Exotel callback path (tenant/agent
    resolved) is the same one the WebSocket handler sees and cleans up —
    proving the shared session_manager wiring, not two divergent stores."""
    call_id = "test-ws-reuse"
    _GW_MAIN.session_manager.create(call_id, tenant_id="acme", agent_id="agent-1")

    client = TestClient(_GW_MAIN.app)
    with client.websocket_connect(f"/ws/{call_id}"):
        session = _GW_MAIN.session_manager.get(call_id)
        assert session["tenant_id"] == "acme"
        assert session["agent_id"] == "agent-1"

    assert _GW_MAIN.session_manager.get(call_id) is None
