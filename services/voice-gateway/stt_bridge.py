"""STT side-channel bridge that feeds audio from the Pipecat pipeline into
a DeepgramSttSession and emits TranscriptEvents asynchronously.

This module has NO pipecat imports. It works purely with:
  - raw bytes (audio)
  - SttSession protocol (send_audio / receive / close)
  - TranscriptEvent (pydantic model from packages.providers.stt)
  - asyncio

The bridge is attached to a CallPipelineHandle by intercepting
push_audio_frame at the handle.input level. It runs a background receive
loop so transcript delivery never blocks audio ingestion.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from packages.providers.stt import SttError, SttSession, TranscriptEvent

logger = logging.getLogger(__name__)


class SttBridge:
    """Connects an SttSession to a single call's audio stream.

    Audio path:
      push_audio_frame(frame)
        → _audio_queue.put(frame.audio)
        → _send_loop() → session.send_audio(bytes)

    Transcript path:
      _recv_loop() → session.receive() → on_transcript(TranscriptEvent)

    Both loops run as independent asyncio tasks so neither blocks the other
    or the Pipecat pipeline's audio queue.
    """

    def __init__(
        self,
        session: SttSession,
        call_id: str,
        on_transcript: Callable[[TranscriptEvent], Awaitable[None]] | None = None,
    ) -> None:
        self._session = session
        self._call_id = call_id
        self._on_transcript = on_transcript
        self._audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._send_task: asyncio.Task | None = None
        self._recv_task: asyncio.Task | None = None
        self._closed = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def handle_audio(self, audio_bytes: bytes) -> None:
        """Accept a raw PCM chunk from the pipeline. Non-blocking."""
        if not self._closed:
            await self._audio_queue.put(audio_bytes)

    def start(self) -> None:
        """Spawn the send and receive loops. Call once after session is open."""
        self._send_task = asyncio.create_task(
            self._send_loop(), name=f"stt-send-{self._call_id}"
        )
        self._recv_task = asyncio.create_task(
            self._recv_loop(), name=f"stt-recv-{self._call_id}"
        )

    async def close(self) -> None:
        """Shut down both loops and close the underlying STT session."""
        if self._closed:
            return
        self._closed = True
        # Signal the send loop to exit.
        await self._audio_queue.put(None)
        for task in (self._send_task, self._recv_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        try:
            await self._session.close()
        except Exception:
            pass
        logger.info("STT bridge closed", extra={"call_id": self._call_id})

    # ------------------------------------------------------------------
    # Internal loops
    # ------------------------------------------------------------------

    async def _send_loop(self) -> None:
        """Drain the audio queue and forward bytes to Deepgram."""
        try:
            while True:
                chunk = await self._audio_queue.get()
                if chunk is None:
                    # Sentinel — bridge is closing.
                    break
                try:
                    await self._session.send_audio(chunk)
                except SttError as exc:
                    logger.warning(
                        "STT send error; stopping send loop",
                        extra={"call_id": self._call_id, "error": str(exc)},
                    )
                    break
        except asyncio.CancelledError:
            pass

    async def _recv_loop(self) -> None:
        """Poll the STT session for transcript events until it closes."""
        try:
            while not self._closed:
                try:
                    event = await self._session.receive()
                except SttError as exc:
                    logger.warning(
                        "STT receive error; stopping receive loop",
                        extra={"call_id": self._call_id, "error": str(exc)},
                    )
                    break
                if event is None:
                    # Clean close from provider.
                    break
                if self._on_transcript is not None:
                    try:
                        await self._on_transcript(event)
                    except Exception as exc:
                        # Never let a downstream consumer crash the loop.
                        logger.warning(
                            "on_transcript callback raised",
                            extra={"call_id": self._call_id, "error": str(exc)},
                        )
        except asyncio.CancelledError:
            pass
