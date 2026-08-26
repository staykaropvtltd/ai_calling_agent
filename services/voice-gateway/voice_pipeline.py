"""SH-03: Pipecat pipeline + session manager — the WebSocket voice endpoint.

Exotel's Voice Streaming applet opens a WebSocket to /ws/{call_id} for the
audio of a call whose metadata was already created by the /telephony/exotel/
callback handler (exotel_routes.py) — this module only owns the audio path.

The pipeline itself is currently transport-in -> transport-out (no STT/LLM/TTS
yet — those land with SH-04/SH-06/SH-08). Its job right now is exactly the
Phase 0 / CP1 bar: an empty call connects and disconnects cleanly through one
production entrypoint, with the call's lifecycle recorded in the same session
manager the Exotel callback path already uses.
"""

from __future__ import annotations

import logging
from typing import Protocol

from fastapi import APIRouter, WebSocket
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)
from pipecat.workers.runner import WorkerRunner

logger = logging.getLogger("staykaro.voice-gateway.pipeline")


class SessionManager(Protocol):
    def create(self, call_id: str, tenant_id: str, agent_id: str) -> None: ...
    def get(self, call_id: str) -> dict | None: ...
    def end(self, call_id: str) -> None: ...
    def remove(self, call_id: str) -> None: ...


def build_voice_router(session_manager: SessionManager) -> APIRouter:
    router = APIRouter(tags=["voice"])

    @router.websocket("/ws/{call_id}")
    async def voice_websocket(websocket: WebSocket, call_id: str) -> None:
        await websocket.accept()

        # A session normally already exists here — created by the Exotel
        # "connected" callback before the telephony platform opens this audio
        # stream. Fall back to creating one (tenant/agent unresolved) so the
        # endpoint is still independently testable/usable without a prior
        # callback, e.g. direct WebSocket clients in dev or tests.
        existing = session_manager.get(call_id)
        if existing is None:
            session_manager.create(call_id=call_id, tenant_id="unknown", agent_id="unknown")

        transport = FastAPIWebsocketTransport(
            websocket,
            FastAPIWebsocketParams(
                audio_in_enabled=False,
                audio_out_enabled=False,
            ),
        )

        pipeline = Pipeline(
            [
                transport.input(),
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
