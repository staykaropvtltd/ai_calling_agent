from __future__ import annotations

from fastapi import FastAPI, WebSocket
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)
from pipecat.workers.runner import WorkerRunner

from call_session import CallSessionManager


app = FastAPI(title="StayKaro Voice Gateway")

session_manager = CallSessionManager()


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

    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)

    try:
        await runner.run()
    finally:
        session = session_manager.get(call_id)

        if session is not None:
            session_manager.end(call_id)
            session_manager.remove(call_id)

        await transport.cleanup()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=9000,
    )