"""Per-call SH-03 Pipecat runtime, shared by native and Exotel transports."""
from __future__ import annotations
import asyncio
import logging
from collections.abc import Awaitable, Callable
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.transports.base_input import BaseInputTransport
from pipecat.transports.websocket.fastapi import FastAPIWebsocketInputTransport, FastAPIWebsocketParams, FastAPIWebsocketTransport
from pipecat.workers.runner import WorkerRunner

logger = logging.getLogger(__name__)


class ExternallyFedInputTransport(FastAPIWebsocketInputTransport):
    """Pipecat input that keeps its audio queue but never reads the provider socket."""
    async def start(self, frame):
        await BaseInputTransport.start(self, frame)
        await self.set_transport_ready(frame)


class CallPipelineHandle:
    def __init__(
        self,
        websocket,
        call_id: str,
        on_output: Callable[[object], Awaitable[None]] | None = None,
        externally_fed: bool = False,
        stt_provider=None,
        on_transcript: Callable[[object], Awaitable[None]] | None = None,
    ):
        self.transport = FastAPIWebsocketTransport(websocket, FastAPIWebsocketParams(audio_in_enabled=True, audio_out_enabled=True))
        self.input, self.output = self.transport.input(), self.transport.output()
        if externally_fed:
            self.input = ExternallyFedInputTransport(self.transport, self.transport._client, self.transport._params, name=self.transport._input_name)
            self.transport._input = self.input
        self.worker = PipelineWorker(Pipeline([self.input, self.output]), params=PipelineParams(), conversation_id=call_id)
        self.runner = WorkerRunner(handle_sigint=False)
        self._task = None
        self._cleaned = False
        if on_output:
            original = self.output.write_audio_frame
            async def write(frame):
                await on_output(frame)
                return await original(frame)
            self.output.write_audio_frame = write

        # SH-04: optional Deepgram STT side-channel
        self._stt_provider = stt_provider
        self._on_transcript = on_transcript
        self._call_id = call_id
        self._stt_bridge = None  # set in start() after session is open

    async def start(self):
        await self.runner.add_workers(self.worker)
        self._task = asyncio.create_task(self.runner.run())

        # SH-04: open the STT session and attach the bridge after the pipeline is running
        if self._stt_provider is not None:
            await self._attach_stt(self._stt_provider)

    async def _attach_stt(self, provider) -> None:
        """Open an STT session and patch push_audio_frame to feed audio into it."""
        from stt_bridge import SttBridge
        from packages.providers.stt import SttError
        try:
            session = await provider.open_session(self._call_id)
        except SttError as exc:
            # STT failure must never crash the voice pipeline.
            logger.warning(
                "STT session failed to open; continuing without STT",
                extra={"call_id": self._call_id, "error": str(exc)},
            )
            return

        bridge = SttBridge(session, self._call_id, on_transcript=self._on_transcript)
        bridge.start()
        self._stt_bridge = bridge

        # Intercept push_audio_frame to forward audio to Deepgram.
        # The original Pipecat queue is still called so the pipeline is unaffected.
        original_push = self.input.push_audio_frame

        async def _push_with_stt(frame):
            await bridge.handle_audio(frame.audio)
            return await original_push(frame)

        self.input.push_audio_frame = _push_with_stt

    async def cleanup(self):
        if self._cleaned:
            return
        self._cleaned = True
        # SH-04: close the STT session first so it can flush the final transcript.
        if self._stt_bridge is not None:
            try:
                await self._stt_bridge.close()
            except Exception:
                pass
        await self.transport.cleanup()
        if self._task:
            self._task.cancel()
