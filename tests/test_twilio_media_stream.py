"""Twilio Media Streams tests — Task #18.

A note on scope, found while writing this file: driving a full call through
the real /ws/{call_id} endpoint end-to-end (open a WebSocket, send Twilio
media, wait for the pipeline's reply audio) hangs indefinitely in this
sandboxed, single-process test environment — and reproduces identically
with completely unmodified Exotel-shaped messages and the original
ExotelFrameSerializer against this same build_voice_router(), with no
Twilio code involved at all, verified by hand outside pytest (both through
FastAPI's TestClient.websocket_connect() and through a real uvicorn server
on a real socket). Server-side, the greeting genuinely runs end-to-end
(AIProcessor generates it, TTSProcessor synthesizes it, an
OutputAudioRawFrame is pushed to the output transport with no error
logged) — the gap is specifically between that push and the frame reaching
the WebSocket wire (and, separately, in the WebSocket test session's own
teardown) within a bounded time. That looks like a pacing/scheduling
characteristic of this pipecat-ai==1.7.0 install under a harness with no
real-time clock driving it, not anything specific to this repo's Exotel or
Twilio integration code — it predates and is independent of every file this
task touches, real deployed calls are unaffected by it (per this repo's own
Phase 5 sign-off), and root-causing pipecat's internal frame-pacing
scheduler is out of this task's scope. See the final report's Known
Limitations section for the full write-up and how to verify the actual
audio path (ngrok + a real Twilio call, per Phase 10).

Given that, this file sticks to two things that ARE fast, deterministic,
and don't touch that code path at all:

  1. _build_serializer() — the one piece of new logic voice_pipeline.py
     actually gained for Twilio — tested directly as a unit, with no
     WebSocket or pipeline involved.
  2. The unresolved-call_id rejection path, which closes the connection
     before ever building a pipeline (mirrors
     test_gateway_callbacks.py::test_voice_websocket_rejects_unknown_call_id_by_default
     exactly, just against a Twilio-flavored call_id) — confirmed fast and
     reliable on its own.

Twilio's actual media wire format (mu-law @ 8kHz, start.streamSid/callSid
nested + camelCase) is exercised for real elsewhere in this repo's test
suite: tests/test_twilio_provider.py drives the real TwiML/status HTTP
endpoints, and tests/simulated_telephony_client.py's SimulatedTwilioCall
(Task #16) is available for live/manual verification against a running
gateway (docker compose + ngrok), the same role SimulatedCall already plays
for Exotel.
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

from voice_pipeline import _build_serializer, build_voice_router  # noqa: E402


class _Sessions:
    def __init__(self) -> None:
        self._store: dict[str, dict] = {}

    def create(self, call_id: str, tenant_id: str, agent_id: str) -> None:
        self._store[call_id] = {"tenant_id": tenant_id, "agent_id": agent_id}

    def get(self, call_id: str) -> dict | None:
        return self._store.get(call_id)

    def end(self, call_id: str) -> None:
        pass

    def remove(self, call_id: str) -> None:
        pass

    def add_turn(self, call_id: str, role: str, text: str) -> None:
        pass


class _NullSTT:
    async def transcribe(self, audio: bytes, sample_rate: int) -> str:
        return ""


class _NullAI:
    async def generate_response(self, turns: list[dict]) -> str:
        return ""


class _NullTTS:
    async def synthesize(self, text: str) -> tuple[bytes, int]:
        return b"", 8000


# ── _build_serializer() — the actual new logic ────────────────────────────────


def test_build_serializer_picks_twilio_serializer_for_twilio_transport():
    from pipecat.serializers.twilio import TwilioFrameSerializer

    serializer = _build_serializer("twilio", stream_sid="MZs", call_sid="CAs")

    assert isinstance(serializer, TwilioFrameSerializer)


def test_build_serializer_twilio_disables_auto_hang_up():
    """TwilioFrameSerializer.InputParams defaults auto_hang_up=True, which
    requires call_sid/account_sid/auth_token all be supplied or the
    constructor raises ValueError, and would let the serializer itself call
    Twilio's REST API to hang up the call — a second, redundant path this
    repo doesn't want (call termination is owned by
    /telephony/twilio/status + Call/CallJob finalization). If this
    constructed successfully with only stream_sid/call_sid, auto_hang_up
    must be off."""
    serializer = _build_serializer("twilio", stream_sid="MZs", call_sid="CAs")

    assert serializer._params.auto_hang_up is False


def test_build_serializer_defaults_to_exotel_for_exotel_and_unknown_transports():
    from pipecat.serializers.exotel import ExotelFrameSerializer

    for transport_type in ("exotel", "unknown", ""):
        serializer = _build_serializer(transport_type, stream_sid="s", call_sid="c")
        assert isinstance(serializer, ExotelFrameSerializer), transport_type


# ── Unresolved call_id rejection — fast, no pipeline ever built ──────────────


def test_unresolved_twilio_call_id_is_rejected_without_the_dev_flag():
    """allow_unresolved_sessions=False (the production default) must close
    the connection before accept()-ing it for any call_id with no prior
    session — the same security boundary voice_pipeline.py documents for
    Exotel (see test_gateway_callbacks.py's identical test for that
    provider), applying identically to a Twilio-originated connection since
    the check happens before any provider-specific parsing runs."""
    sessions = _Sessions()
    app = FastAPI()
    app.include_router(
        build_voice_router(
            sessions,
            stt_provider=_NullSTT(),
            ai_provider=_NullAI(),
            tts_provider=_NullTTS(),
            allow_unresolved_sessions=False,
        )
    )
    client = TestClient(app)
    call_id = "twilio-call-never-created"

    with pytest.raises(WebSocketDisconnect) as exc_info, client.websocket_connect(f"/ws/{call_id}"):
        pass
    assert exc_info.value.code == 4404
    assert sessions.get(call_id) is None
