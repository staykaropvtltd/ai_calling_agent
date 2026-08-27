"""Phase 5 — STT -> AI -> TTS pipeline processors.

Three FrameProcessors, inserted into the same Pipecat Pipeline the transport
already uses (services/voice-gateway/voice_pipeline.py) — no second pipeline
or parallel architecture. Each processor owns exactly one stage and talks to
its provider only through the Protocol interfaces in stt_provider.py /
ai_provider.py / tts_provider.py, so swapping a local provider for a cloud
one later never touches this file's control flow.

Turn detection: energy-based silence detection (RMS threshold). No VAD
model/extra dependency — Pipecat ships several (Silero etc.) but adding one
wasn't justified for this phase's CP bar. Documented as a real, working, but
intentionally simple approach in the Phase 5 report.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Protocol

from ai_provider import AIError, AIProvider, ConversationTurn
from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    Frame,
    InputAudioRawFrame,
    OutputAudioRawFrame,
    StartFrame,
    TextFrame,
    TranscriptionFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from stt_provider import WHISPER_SAMPLE_RATE, STTError, STTProvider
from tts_provider import TTSError, TTSProvider

logger = logging.getLogger("staykaro.voice-gateway.conversation")


class SessionTurnStore(Protocol):
    """The subset of _GatewaySessionManager this module needs."""

    def get(self, call_id: str) -> dict | None: ...
    def add_turn(self, call_id: str, role: str, text: str) -> None: ...


class STTProcessor(FrameProcessor):
    """Buffers caller audio, detects end-of-turn via silence, transcribes."""

    def __init__(
        self,
        provider: STTProvider,
        *,
        silence_rms_threshold: float = 0.02,
        silence_frames_to_end_turn: int = 15,
        max_buffer_seconds: float = 20.0,
    ) -> None:
        super().__init__()
        self._provider = provider
        self._silence_threshold = silence_rms_threshold
        self._silence_frames_to_end_turn = silence_frames_to_end_turn
        self._max_buffer_bytes = int(max_buffer_seconds * WHISPER_SAMPLE_RATE * 2)

        self._buffer = bytearray()
        self._silence_run = 0
        self._speaking = False

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, InputAudioRawFrame):
            await self._handle_audio(frame)
            return  # consumed here — raw audio doesn't need to reach AI/TTS

        if isinstance(frame, EndFrame | CancelFrame):
            self._buffer.clear()

        await self.push_frame(frame, direction)

    async def _handle_audio(self, frame: InputAudioRawFrame) -> None:
        import numpy as np

        samples = np.frombuffer(frame.audio, dtype=np.int16).astype(np.float32) / 32768.0
        energy = float(np.sqrt(np.mean(samples**2))) if len(samples) else 0.0
        is_silent = energy < self._silence_threshold

        if not is_silent:
            self._speaking = True
            self._silence_run = 0
            self._buffer.extend(frame.audio)
        elif self._speaking:
            self._silence_run += 1
            self._buffer.extend(frame.audio)
            if self._silence_run >= self._silence_frames_to_end_turn:
                await self._flush_turn()
                return

        if len(self._buffer) >= self._max_buffer_bytes:
            logger.warning("STTProcessor: max buffer reached, flushing early")
            await self._flush_turn()

    async def _flush_turn(self) -> None:
        audio = bytes(self._buffer)
        self._buffer.clear()
        self._speaking = False
        self._silence_run = 0
        if not audio:
            return

        try:
            text = await self._provider.transcribe(audio, WHISPER_SAMPLE_RATE)
        except STTError as exc:
            # Never crash the call over one bad transcription — the caller
            # just gets no response for this turn and can try again.
            logger.warning("STT failed for this turn, skipping: %s", exc)
            return

        text = text.strip()
        if not text:
            return

        await self.push_frame(
            TranscriptionFrame(
                text=text,
                user_id="caller",
                timestamp=datetime.now(UTC).isoformat(),
                finalized=True,
            )
        )


class AIProcessor(FrameProcessor):
    """Turns a TranscriptionFrame into an assistant TextFrame, using and
    updating the call's turn history in the existing session store."""

    def __init__(self, provider: AIProvider, session_store: SessionTurnStore, call_id: str) -> None:
        super().__init__()
        self._provider = provider
        self._session_store = session_store
        self._call_id = call_id
        self._greeted = False

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, StartFrame):
            await self.push_frame(frame, direction)
            await self._maybe_greet()
            return

        if isinstance(frame, TranscriptionFrame):
            await self._handle_user_turn(frame.text)
            return

        await self.push_frame(frame, direction)

    async def _maybe_greet(self) -> None:
        if self._greeted:
            return
        self._greeted = True
        await self._respond(turns=[])

    async def _handle_user_turn(self, text: str) -> None:
        self._session_store.add_turn(self._call_id, role="user", text=text)
        session = self._session_store.get(self._call_id) or {}
        turns: list[ConversationTurn] = session.get("turns", [])
        await self._respond(turns=turns)

    async def _respond(self, turns: list[ConversationTurn]) -> None:
        try:
            response = await self._provider.generate_response(turns)
        except AIError as exc:
            logger.warning("AI response generation failed: %s", exc)
            response = "I'm sorry, something went wrong on my end. Could you repeat that?"

        self._session_store.add_turn(self._call_id, role="assistant", text=response)
        await self.push_frame(TextFrame(text=response))


class TTSProcessor(FrameProcessor):
    """Turns an assistant TextFrame into an OutputAudioRawFrame."""

    def __init__(self, provider: TTSProvider) -> None:
        super().__init__()
        self._provider = provider

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, TextFrame):
            await self._handle_text(frame.text)
            return

        await self.push_frame(frame, direction)

    async def _handle_text(self, text: str) -> None:
        if not text.strip():
            return
        try:
            audio, sample_rate = await self._provider.synthesize(text)
        except TTSError as exc:
            # Same policy as STT failures: log and skip rather than crash the
            # call or push a system-level ErrorFrame with side effects this
            # module doesn't need to take on.
            logger.warning("TTS failed, caller gets no audio for this response: %s", exc)
            return

        await self.push_frame(OutputAudioRawFrame(audio=audio, sample_rate=sample_rate, num_channels=1))
