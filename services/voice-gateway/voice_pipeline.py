"""SH-03 + Phase 5: Pipecat pipeline + session manager — the WebSocket voice endpoint.

Exotel's Voice Streaming applet opens a WebSocket to /ws/{call_id} for the
audio of a call whose metadata was already created by the /telephony/exotel/
callback handler (exotel_routes.py) — this module only owns the audio path.
Twilio's Media Streams (opened by the TwiML <Connect><Stream> this gateway's
/telephony/twilio/twiml endpoint returns — see twilio_routes.py) use the
exact same /ws/{call_id} route; no separate WebSocket route exists per
provider.

Phase 5 adds the real STT -> AI -> TTS pipeline (conversation.py) between
transport.input() and transport.output(). The media contract for Exotel is
Exotel's own documented Media Streams protocol, unchanged from what Pipecat
already ships support for (pipecat.serializers.exotel.ExotelFrameSerializer,
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

Twilio's Media Streams wire format is materially different (μ-law-encoded
audio, a "connected" message before "start", a "stop" message instead of a
clean close, sequence numbers) — see
pipecat.serializers.twilio.TwilioFrameSerializer, which Pipecat ships as a
first-party sibling of ExotelFrameSerializer, handling that entire contract
(including the 8kHz μ-law <-> pipeline-rate PCM conversion) the same way
ExotelFrameSerializer already does for Exotel. This module does not
hand-roll Twilio's audio encode/decode itself — see _build_serializer()
below, the only place this file differs per provider.

A simulated telephony client (tests/) speaks this exact same contract so it
exercises the real transport/serializer code, not a parallel test-only path.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol

from ai_provider import AIProvider
from conversation import AIProcessor, STTProcessor, TTSProcessor
from fastapi import APIRouter, WebSocket
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.runner.utils import parse_telephony_websocket
from pipecat.serializers.exotel import ExotelFrameSerializer
from pipecat.serializers.twilio import TwilioFrameSerializer
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


def _build_serializer(transport_type: str, *, stream_sid: str, call_sid: str):
    """Picks the wire-format serializer by the provider parse_telephony_websocket
    already detected from the first WebSocket message. Exotel is the default
    for any transport_type this gateway doesn't have a specific serializer
    for (preserves the exact previous behavior for Exotel, and for any
    not-yet-supported provider, rather than raising and dropping the call).

    This is the only call site that differs per provider — every line below
    it (STT/AI/TTS pipeline construction) is provider-agnostic and unchanged
    for Twilio.
    """
    if transport_type == "twilio":
        # TwilioFrameSerializer.InputParams defaults auto_hang_up=True, which
        # makes the serializer itself call the Twilio REST API to hang up the
        # call under certain pipeline conditions — and raises ValueError at
        # construction unless call_sid, account_sid, AND auth_token are all
        # supplied. This repo already owns call termination through
        # /telephony/twilio/status + Call/CallJob finalization
        # (twilio_routes.py's terminal-status branch), not through this
        # serializer, so auto_hang_up is explicitly disabled here rather than
        # threading TWILIO_ACCOUNT_SID/AUTH_TOKEN into the WS handler to
        # enable a second, redundant hang-up path.
        return TwilioFrameSerializer(
            stream_sid=stream_sid,
            call_sid=call_sid,
            params=TwilioFrameSerializer.InputParams(auto_hang_up=False),
        )
    return ExotelFrameSerializer(stream_sid=stream_sid, call_sid=call_sid)


def build_voice_router(
    session_manager: SessionManager,
    *,
    stt_provider: STTProvider,
    ai_provider: AIProvider,
    tts_provider: TTSProvider,
    allow_unresolved_sessions: bool = False,
    is_draining: Callable[[], bool] = lambda: False,
    on_call_started: Callable[[], None] = lambda: None,
    on_call_ended: Callable[[], None] = lambda: None,
) -> APIRouter:
    """allow_unresolved_sessions: dev/test-only escape hatch (wire it to the
    same EXOTEL_DEV_ROUTING flag src/main.py already uses for the routing
    stub — same trust boundary: "no real Exotel/routing backing this call").
    Applies identically to a Twilio-originated connection: a call_id with no
    session already created via an authenticated path (either provider's
    webhook, or the internal API in tests) is rejected unless this is set.

    Phase 4 makes this endpoint reachable from the public internet (Exotel's
    Voice Streaming applet, or Twilio's Media Streams, connects here
    directly). Without this gate, a connection to ANY call_id — not just a
    guessed real one, any string the caller picks — silently created a live
    session with no authenticated call/routing behind it, which is a free
    way to make this gateway create arbitrary session state. Rejecting
    instead of falling back closes that off in a real deployment (where the
    flag is unset) while preserving the documented dev/test convenience of
    connecting without a prior callback when the flag is explicitly set.

    is_draining / on_call_started / on_call_ended: NH-17 deployment
    draining hooks (wired to src/main.py's SIGTERM handler). A telephony
    platform retries a rejected connection against whatever instance is
    next in rotation, so refusing new connections here is what "stops
    accepting new calls" (Infrastructure & Operations Guide §7) actually
    means for a WebSocket endpoint — there is no listen-socket-level
    equivalent of an HTTP server simply closing its port, since existing
    calls hold their own already-accepted connections regardless.
    """
    router = APIRouter(tags=["voice"])

    @router.websocket("/ws/{call_id}")
    async def voice_websocket(websocket: WebSocket, call_id: str) -> None:
        if is_draining():
            # 1013 "Try Again Later" — the standard WS close code for
            # exactly this: a healthy server that just can't take this
            # connection right now. Rejected *before* accept() so the
            # telephony platform sees a clean handshake failure to retry
            # elsewhere, not a connection that opened and then dropped.
            await websocket.close(code=1013, reason="server draining for deploy")
            return

        # A session normally already exists here — created by the Exotel
        # "connected" callback, the Twilio TwiML request (twilio_routes.py),
        # or the internal API in tests — before the telephony platform opens
        # this audio stream. Checked *before* accept() so an unresolved
        # call_id is rejected at the handshake, never gets a live pipeline.
        existing = session_manager.get(call_id)
        if existing is None:
            if not allow_unresolved_sessions:
                await websocket.close(code=4404, reason="unknown call_id")
                return
            session_manager.create(call_id=call_id, tenant_id="unknown", agent_id="unknown")

        await websocket.accept()
        on_call_started()
        try:
            # Consumes the WS's first (handshake) message(s) to learn the
            # telephony platform's own stream_sid/call_sid, and which provider
            # this is — required to construct the right serializer. Everything
            # after this point (media/dtmf events) is read by the transport
            # itself, untouched by this call (see parse_telephony_websocket's
            # docstring: the underlying receive stream is only ever consumed
            # once).
            try:
                transport_type, call_data = await parse_telephony_websocket(websocket)
                stream_sid = call_data.stream_id or call_id
                provider_call_sid = call_data.call_id
            except ValueError as exc:
                # WS closed before sending a handshake message at all.
                logger.warning("call_id=%s: no telephony handshake received: %s", call_id, exc)
                if session_manager.get(call_id) is not None:
                    session_manager.end(call_id)
                    session_manager.remove(call_id)
                return

            serializer = _build_serializer(
                transport_type, stream_sid=stream_sid, call_sid=provider_call_sid
            )
            logger.info("call_id=%s: telephony transport detected as %r", call_id, transport_type)

            transport = FastAPIWebsocketTransport(
                websocket,
                FastAPIWebsocketParams(
                    audio_in_enabled=True,
                    audio_out_enabled=True,
                    # Whisper's native rate — each serializer resamples its own
                    # provider's native rate (Exotel and Twilio are both 8kHz)
                    # to this automatically (see each serializer's own setup()).
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

            await runner.run()
        finally:
            # Paired unconditionally with on_call_started() above, regardless
            # of which return path above was taken — NH-17's drain loop
            # (src/main.py) polls this count down to zero and must never see
            # it get stuck above zero because one exit path forgot to
            # decrement.
            on_call_ended()

    return router


async def _run_call(
    websocket: WebSocket,
    call_id: str,
    *,
    session_manager: SessionManager,
    stt_provider: STTProvider,
    ai_provider: AIProvider,
    tts_provider: TTSProvider,
) -> None:
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
