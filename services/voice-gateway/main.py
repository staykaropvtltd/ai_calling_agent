from __future__ import annotations

import os

from fastapi import FastAPI, WebSocket
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)
from pipecat.workers.runner import WorkerRunner

from call_session import CallSessionManager
from exotel_routes import build_exotel_router
from internal_calls import InternalCallsClient
from exotel_stream import build_exotel_stream_router
from pipeline_handle import CallPipelineHandle
from packages.providers.telephony import ExotelSettings, ProviderError, TwilioSettings
from twilio_routes import build_twilio_router
from transcript_handler import make_transcript_handler


app = FastAPI(title="StayKaro Voice Gateway")

session_manager = CallSessionManager()

# SH-04: load Deepgram STT provider once at startup (optional — missing key
# keeps the gateway running without STT; sandbox deployments must configure it).
_stt_provider = None
try:
    from packages.providers.stt import DeepgramSettings, SttError
    from packages.providers.deepgram import DeepgramSttProvider
    _stt_provider = DeepgramSttProvider(DeepgramSettings.from_environment())
except (SttError, Exception):
    pass

try:
    routing = None
    if os.getenv("EXOTEL_ROUTING_STUB_ENABLED", "false").lower() == "true" and os.getenv("ENVIRONMENT", "development").lower() in ("local", "development", "test"):
        from dev_routing import TestExotelRoutingStub
        routing = TestExotelRoutingStub()
    app.include_router(build_exotel_router(session_manager, ExotelSettings.from_environment(), InternalCallsClient(os.getenv("INTERNAL_API_BASE_URL", "http://api:8000")), routing))
    app.include_router(build_exotel_stream_router(session_manager, InternalCallsClient(os.getenv("INTERNAL_API_BASE_URL", "http://api:8000")), routing, stt_provider=_stt_provider))
except ProviderError:
    # Exotel is optional for local SH-03-only startup; sandbox deployments must configure it.
    pass

try:
    twilio_routing = None
    if os.getenv("TWILIO_ROUTING_STUB_ENABLED", "false").lower() == "true" and os.getenv("ENVIRONMENT", "development").lower() in ("local", "development", "test"):
        from dev_routing import TestExotelRoutingStub
        twilio_routing = TestExotelRoutingStub()
    app.include_router(build_twilio_router(session_manager, TwilioSettings.from_environment(), InternalCallsClient(os.getenv("INTERNAL_API_BASE_URL", "http://api:8000")), twilio_routing))
except ProviderError:
    # Twilio is optional for local SH-03-only startup; sandbox deployments must configure it.
    pass


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.websocket("/ws/{call_id}")
async def voice_websocket(websocket: WebSocket, call_id: str) -> None:
    await websocket.accept()

    session_manager.create(
        call_id=call_id,
        tenant_id="unknown",
        agent_id="unknown",
    )

    handle = CallPipelineHandle(
        websocket, call_id,
        stt_provider=_stt_provider,
        on_transcript=make_transcript_handler(call_id),
    )
    await handle.start()

    try:
        if handle._task:
            await handle._task
    finally:
        session = session_manager.get(call_id)

        if session is not None:
            session_manager.end(call_id)
            session_manager.remove(call_id)

        await handle.cleanup()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=9000,
    )