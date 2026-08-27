"""SH-03 + Phase 5: Pipecat pipeline + session manager — the WebSocket voice endpoint.

Exotel's Voice Streaming applet opens a WebSocket to /ws/{call_id} for the
audio of a call whose metadata was already created by the /telephony/exotel/
callback handler (exotel_routes.py) — this module only owns the audio path.

Phase 5 adds the real STT -> AI -> TTS pipeline (conversation.py) between
transport.input() and transport.output(). The media contract is Exotel's own
documented Media Streams protocol, unchanged from what Pipecat already ships
support for (pipecat.serializers.exotel.ExotelFrameSerializer,
pipecat.runner.utils.parse_telephony_websocket) — nothing invented here:

  1. First WS message is a JSON "start" handshake:
     {"event": "start", "start": {"stream_sid": ..., "call_sid": ...,
       "account_sid": ..., "from": ..., "to": ..., "custom_parameters": ...}}
  2. Subsequent messages are JSON "media" events with base64 PCM16 mono
     audio at 8kHz: {"event": "media", "media": {"payload": "<base64>"}}
  3. Optional "dtmf" events.
  4. Server -> caller: the same "media" event shape, plus an Exotel "clear"
     event ({"event": "clear", "streamSid": ...}) used for barge-in (see
     conversation.py's interruption handling).

A simulated telephony client (tests/) speaks this exact same contract so it
exercises the real transport/serializer code, not a parallel test-only path.
"""

from __future__ import annotations

import logging
from typing import Protocol

from ai_provider import AIProvider
from conversation import AIProcessor, STTProcessor, TTSProcessor
from fastapi import APIRouter, WebSocket
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.runner.utils import parse_telephony_websocket
from pipecat.serializers.exotel import ExotelFrameSerializer
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)
from pipecat.workers.runner import WorkerRunner
from stt_provider import WHISPER_SAMPLE_RATE, STTProvider
from tts_provider import TTSProvider

logger = logging.getLogger("staykaro.voice-gateway.pipeline")


class SessionManager(Protocol):
    def create(self, call_id: str, tenant_id: str, agent_id: str) -> None: ...
    def get(self, call_id: str) -> dict | None: ...
    def end(self, call_id: str) -> None: ...
    def remove(self, call_id: str) -> None: ...
    def add_turn(self, call_id: str, role: str, text: str) -> None: ...


def build_voice_router(
    session_manager: SessionManager,
    *,
    stt_provider: STTProvider,
    ai_provider: AIProvider,
    tts_provider: TTSProvider,
    allow_unresolved_sessions: bool = False,
) -> APIRouter:
    """allow_unresolved_sessions: dev/test-only escape hatch (wire it to the
    same EXOTEL_DEV_ROUTING flag src/main.py already uses for the routing
    stub — same trust boundary: "no real Exotel/routing backing this call").

    Phase 4 makes this endpoint reachable from the public internet (Exotel's
    Voice Streaming applet connects here directly). Without this gate, a
    connection to ANY call_id — not just a guessed real one, any string the
    caller picks — silently created a live session with no authenticated
    call/routing behind it, which is a free way to make this gateway create
    arbitrary session state. Rejecting instead of falling back closes that
    off in a real deployment (where the flag is unset) while preserving the
    documented dev/test convenience of connecting without a prior callback
    when the flag is explicitly set.
    """
    router = APIRouter(tags=["voice"])

    @router.websocket("/ws/{call_id}")
    async def voice_websocket(websocket: WebSocket, call_id: str) -> None:
        # A session normally already exists here — created by the Exotel
        # "connected" callback (or the internal API, in tests) before the
        # telephony platform opens this audio stream. Checked *before*
        # accept() so an unresolved call_id is rejected at the handshake,
        # never gets a live pipeline.
        existing = session_manager.get(call_id)
        if existing is None:
            if not allow_unresolved_sessions:
                await websocket.close(code=4404, reason="unknown call_id")
                return
            session_manager.create(call_id=call_id, tenant_id="unknown", agent_id="unknown")

        await websocket.accept()

        # Consumes the WS's first (handshake) message(s) to learn Exotel's
        # own stream_sid/call_sid — required to construct the serializer.
        # Everything after this point (media/dtmf events) is read by the
        # transport itself, untouched by this call (see parse_telephony_websocket's
        # docstring: the underlying receive stream is only ever consumed once).
        try:
            _transport_type, call_data = await parse_telephony_websocket(websocket)
            stream_sid = call_data.stream_id or call_id
            provider_call_sid = call_data.call_id
        except ValueError as exc:
            # WS closed before sending a handshake message at all.
            logger.warning("call_id=%s: no telephony handshake received: %s", call_id, exc)
            if session_manager.get(call_id) is not None:
                session_manager.end(call_id)
                session_manager.remove(call_id)
            return

        serializer = ExotelFrameSerializer(stream_sid=stream_sid, call_sid=provider_call_sid)

        transport = FastAPIWebsocketTransport(
            websocket,
            FastAPIWebsocketParams(
                audio_in_enabled=True,
                audio_out_enabled=True,
                # Whisper's native rate — the serializer resamples Exotel's
                # 8kHz audio to this automatically (see its own setup()).
                audio_in_sample_rate=WHISPER_SAMPLE_RATE,
                serializer=serializer,
            ),
        )

        stt = STTProcessor(stt_provider)
        ai = AIProcessor(ai_provider, session_manager, call_id)
        tts = TTSProcessor(tts_provider)

        pipeline = Pipeline(
            [
                transport.input(),
                stt,
                ai,
                tts,
                transport.output(),
            ]
        )

        worker = PipelineWorker(
            pipeline,
            params=PipelineParams(),
            conversation_id=call_id,
        )

        # FastAPIWebsocketTransport does not stop the pipeline by itself on a
        # client disconnect — without this handler runner.run() blocks forever
        # after the caller hangs up, so the session (and its Redis key) never
        # gets cleaned up. Cancelling the worker is what lets auto_end (the
        # WorkerRunner default) return from run() below.
        @transport.event_handler("on_client_disconnected")
        async def _on_client_disconnected(_transport, _websocket) -> None:
            await worker.cancel(reason="client disconnected")

        runner = WorkerRunner(handle_sigint=False)
        await runner.add_workers(worker)

        try:
            await runner.run()
        finally:
            if session_manager.get(call_id) is not None:
                session_manager.end(call_id)
                session_manager.remove(call_id)
            await transport.cleanup()

    return router
