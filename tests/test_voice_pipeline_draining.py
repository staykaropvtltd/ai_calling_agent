"""
NH-17 — deployment draining, at the voice_pipeline.py router level.

Infrastructure & Operations Guide §7: "stops accepting new calls, lets
active calls finish naturally." Full acceptance ("verified against a real
active call") needs a live voice pipeline — blocked on SH-04/06/08's
provider API keys, same as the rest of the voice pipeline (see PROGRESS.md).
What's testable without one: the mechanism itself — new connections are
rejected while draining, and the active-call counter used to decide when a
drain is complete is paired correctly around every connection, including
ones that fail before a real call ever starts.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

_VG = str((Path(__file__).parent.parent / "services" / "voice-gateway").resolve())
if _VG not in sys.path:
    sys.path.insert(0, _VG)

from voice_pipeline import build_voice_router  # noqa: E402


class _FakeSessionManager:
    """Minimal stand-in — draining is checked before any session lookup, so
    these tests never need it to return anything real."""

    def __init__(self):
        self.calls: list[str] = []

    def get(self, call_id: str):
        self.calls.append(("get", call_id))
        return None

    def create(self, call_id, tenant_id, agent_id):
        self.calls.append(("create", call_id))

    def end(self, call_id):
        self.calls.append(("end", call_id))

    def remove(self, call_id):
        self.calls.append(("remove", call_id))

    def add_turn(self, call_id, role, text):
        pass


def _build_app(*, is_draining, on_call_started=None, on_call_ended=None, allow_unresolved=True):
    app = FastAPI()
    app.include_router(
        build_voice_router(
            _FakeSessionManager(),
            stt_provider=None,
            ai_provider=None,
            tts_provider=None,
            allow_unresolved_sessions=allow_unresolved,
            is_draining=is_draining,
            on_call_started=on_call_started or (lambda: None),
            on_call_ended=on_call_ended or (lambda: None),
        )
    )
    return app


def test_new_connection_rejected_while_draining():
    app = _build_app(is_draining=lambda: True)
    client = TestClient(app)

    with pytest.raises(WebSocketDisconnect) as exc_info, client.websocket_connect("/ws/some-call-id"):
        pass

    assert exc_info.value.code == 1013


def test_draining_check_happens_before_any_session_lookup():
    session_manager = _FakeSessionManager()
    app = FastAPI()
    app.include_router(
        build_voice_router(
            session_manager,
            stt_provider=None,
            ai_provider=None,
            tts_provider=None,
            is_draining=lambda: True,
        )
    )
    client = TestClient(app)

    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws/some-call-id"):
        pass

    assert session_manager.calls == []


def test_not_draining_allows_connection_past_the_gate():
    """When not draining, the pre-existing unknown-call_id rejection (a
    different code, 4404) still fires — proving the draining check didn't
    accidentally swallow or replace that unrelated gate."""
    app = _build_app(is_draining=lambda: False, allow_unresolved=False)
    client = TestClient(app)

    with pytest.raises(WebSocketDisconnect) as exc_info, client.websocket_connect("/ws/some-call-id"):
        pass

    assert exc_info.value.code == 4404


def test_on_call_started_and_ended_are_paired_even_on_early_failure():
    """A connection that gets past the draining/unknown-call_id gates but
    then fails before a real call starts (no telephony handshake sent) must
    still decrement — otherwise the drain loop in src/main.py would wait
    forever for a call that never really existed."""
    events: list[str] = []
    app = _build_app(
        is_draining=lambda: False,
        on_call_started=lambda: events.append("started"),
        on_call_ended=lambda: events.append("ended"),
        allow_unresolved=True,
    )
    client = TestClient(app)

    # Connects (allow_unresolved_sessions=True creates a session), then the
    # `with` block exits without sending the telephony "start" handshake —
    # parse_telephony_websocket raises ValueError, hitting voice_pipeline.py's
    # early-return path.
    with client.websocket_connect("/ws/some-call-id"):
        pass

    assert events == ["started", "ended"]
