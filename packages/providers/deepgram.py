"""Deepgram streaming STT implementation of the SttProvider/SttSession contract."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from urllib.parse import urlencode

import websockets
import websockets.exceptions

from .stt import DeepgramSettings, SttError, SttSession, TranscriptEvent

logger = logging.getLogger(__name__)

_DEEPGRAM_WSS_BASE = "wss://api.deepgram.com/v1/listen"

# Deepgram closes an idle connection after ~10 s of silence.
# We send a KeepAlive message at this interval when no audio flows.
_KEEPALIVE_INTERVAL_S = 5.0


def _build_url(settings: DeepgramSettings) -> str:
    """Construct the Deepgram live-transcription WebSocket URL from settings."""
    params: dict[str, Any] = {
        "model": settings.model,
        "language": settings.language,
        "encoding": settings.encoding,
        "sample_rate": settings.sample_rate,
        "channels": settings.channels,
        "interim_results": str(settings.interim_results).lower(),
        "smart_format": str(settings.smart_format).lower(),
    }
    return f"{_DEEPGRAM_WSS_BASE}?{urlencode(params)}"


def _parse_transcript(message: str, call_id: str) -> TranscriptEvent | None:
    """Parse a Deepgram JSON message into a TranscriptEvent.

    Returns None for non-transcript messages (metadata, speech-started, etc.).
    Raises SttError on malformed JSON.  Never logs raw message content.
    """
    try:
        data: dict[str, Any] = json.loads(message)
    except (json.JSONDecodeError, ValueError) as exc:
        raise SttError("Deepgram sent a non-JSON message") from exc

    msg_type = data.get("type")
    if msg_type != "Results":
        # Metadata, SpeechStarted, UtteranceEnd, CloseStream — intentionally ignored.
        return None

    channel = (data.get("channel") or {})
    alternatives = channel.get("alternatives") or []
    if not alternatives:
        return None

    best = alternatives[0]
    transcript: str = best.get("transcript") or ""
    confidence: float = float(best.get("confidence") or 0.0)
    is_final: bool = bool(data.get("is_final", False))

    return TranscriptEvent(
        call_id=call_id,
        transcript=transcript,
        is_final=is_final,
        confidence=confidence,
        raw=data,
    )


class DeepgramSttSession:
    """Single-call streaming session backed by a Deepgram WebSocket."""

    def __init__(
        self,
        ws: websockets.WebSocketClientProtocol,
        call_id: str,
    ) -> None:
        self._ws = ws
        self._call_id = call_id
        self._closed = False

    async def send_audio(self, audio_bytes: bytes) -> None:
        """Forward a raw PCM audio chunk to Deepgram.  Never logged."""
        if self._closed:
            return
        try:
            await self._ws.send(audio_bytes)
        except websockets.exceptions.ConnectionClosed as exc:
            raise SttError("Deepgram connection closed while sending audio") from exc

    async def receive(self) -> TranscriptEvent | None:
        """Block until the next JSON message arrives; parse and return a TranscriptEvent.

        Returns None for non-transcript messages (metadata, keep-alive acks).
        Returns None when the connection is cleanly closed.
        Raises SttError on provider errors or malformed messages.
        """
        if self._closed:
            return None
        try:
            message = await self._ws.recv()
        except websockets.exceptions.ConnectionClosedOK:
            return None
        except websockets.exceptions.ConnectionClosedError as exc:
            raise SttError(f"Deepgram connection closed with error: {exc.code}") from exc
        except websockets.exceptions.WebSocketException as exc:
            raise SttError("Deepgram WebSocket error") from exc

        if isinstance(message, bytes):
            # Deepgram does not send binary frames in the live API; ignore defensively.
            return None
        return _parse_transcript(message, self._call_id)

    async def close(self) -> None:
        """Gracefully close the Deepgram WebSocket session."""
        if self._closed:
            return
        self._closed = True
        try:
            # Send Deepgram's CloseStream signal so it flushes the final transcript.
            await self._ws.send(json.dumps({"type": "CloseStream"}))
        except Exception:
            pass  # Already closed — nothing to do.
        try:
            await self._ws.close()
        except Exception:
            pass


class DeepgramSttProvider:
    """Opens per-call DeepgramSttSession instances."""

    def __init__(self, settings: DeepgramSettings) -> None:
        self._settings = settings

    async def open_session(self, call_id: str) -> DeepgramSttSession:
        """Connect to Deepgram and return a ready-to-use session.

        Raises SttError on connection failure or timeout.
        The API key is passed via HTTP Authorization header, not the URL.
        """
        url = _build_url(self._settings)
        headers = {"Authorization": f"Token {self._settings.api_key}"}
        # Never log headers — they contain the API key.
        try:
            ws = await asyncio.wait_for(
                websockets.connect(url, extra_headers=headers),
                timeout=self._settings.connect_timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise SttError("Deepgram connection timed out") from exc
        except websockets.exceptions.WebSocketException as exc:
            raise SttError("Deepgram connection failed") from exc
        except OSError as exc:
            raise SttError("Deepgram connection failed") from exc
        logger.info("Deepgram STT session opened", extra={"call_id": call_id})
        return DeepgramSttSession(ws, call_id)
