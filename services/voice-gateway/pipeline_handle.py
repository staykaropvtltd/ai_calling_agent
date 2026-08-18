"""Per-call SH-03 Pipecat runtime, shared by native and Exotel transports."""
from __future__ import annotations
import asyncio
from collections.abc import Awaitable, Callable
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.transports.base_input import BaseInputTransport
from pipecat.transports.websocket.fastapi import FastAPIWebsocketInputTransport, FastAPIWebsocketParams, FastAPIWebsocketTransport
from pipecat.workers.runner import WorkerRunner

class ExternallyFedInputTransport(FastAPIWebsocketInputTransport):
    """Pipecat input that keeps its audio queue but never reads the provider socket."""
    async def start(self, frame):
        await BaseInputTransport.start(self, frame)
        await self.set_transport_ready(frame)

class CallPipelineHandle:
    def __init__(self, websocket, call_id: str, on_output: Callable[[object], Awaitable[None]] | None = None, externally_fed: bool = False):
        self.transport = FastAPIWebsocketTransport(websocket, FastAPIWebsocketParams(audio_in_enabled=True, audio_out_enabled=True))
        self.input, self.output = self.transport.input(), self.transport.output()
        if externally_fed:
            self.input = ExternallyFedInputTransport(self.transport, self.transport._client, self.transport._params, name=self.transport._input_name)
            self.transport._input = self.input
        self.worker = PipelineWorker(Pipeline([self.input, self.output]), params=PipelineParams(), conversation_id=call_id)
        self.runner = WorkerRunner(handle_sigint=False); self._task=None; self._cleaned=False
        if on_output:
            original=self.output.write_audio_frame
            async def write(frame):
                await on_output(frame); return await original(frame)
            self.output.write_audio_frame=write
    async def start(self):
        await self.runner.add_workers(self.worker); self._task=asyncio.create_task(self.runner.run())
    async def cleanup(self):
        if self._cleaned: return
        self._cleaned=True
        await self.transport.cleanup()
        if self._task: self._task.cancel()
