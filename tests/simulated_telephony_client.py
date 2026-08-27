"""Phase 5 — simulated telephony media client.

Speaks the exact same WebSocket contract Exotel's real Voice Streaming
applet uses (see services/voice-gateway/voice_pipeline.py's module
docstring): a JSON "start" handshake pipecat's own
pipecat.runner.utils.parse_telephony_websocket auto-detects as "exotel",
followed by JSON "media" events carrying base64 PCM16 mono audio at 8kHz —
the same contract pipecat.serializers.exotel.ExotelFrameSerializer produces
and consumes. This is not a mock of the Voice Gateway — it is a real
WebSocket client exercising the real, deployed /ws/{call_id} endpoint,
standing in only for the telephony provider Exotel would otherwise be.
"""

from __future__ import annotations

import asyncio
import base64
import json
import wave
from dataclasses import dataclass, field

import websockets

SAMPLE_RATE = 8000
CHUNK_MS = 20
CHUNK_BYTES = CHUNK_MS * SAMPLE_RATE // 1000 * 2  # 16-bit mono


def load_wav_8k_mono16(path: str) -> bytes:
    with wave.open(path, "rb") as w:
        if w.getframerate() != SAMPLE_RATE or w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise ValueError(
                f"{path}: expected {SAMPLE_RATE}Hz mono 16-bit, got "
                f"{w.getframerate()}Hz, {w.getnchannels()}ch, {w.getsampwidth()*8}-bit"
            )
        return w.readframes(w.getnframes())


@dataclass
class SimulatedCall:
    """One simulated telephony session against a running Voice Gateway."""

    call_id: str
    base_url: str = "ws://127.0.0.1:9000"
    stream_sid: str = "sim-stream"
    call_sid: str = "sim-call-sid"
    account_sid: str = "sim-account"
    from_number: str = "+911111111111"
    to_number: str = "+917314623519"

    received_media: list[bytes] = field(default_factory=list, init=False)
    received_other: list[dict] = field(default_factory=list, init=False)
    _ws: websockets.ClientConnection | None = field(default=None, init=False)
    _recv_task: asyncio.Task | None = field(default=None, init=False)
    _send_task: asyncio.Task | None = field(default=None, init=False)
    _send_queue: asyncio.Queue | None = field(default=None, init=False)

    async def connect(self) -> None:
        uri = f"{self.base_url}/ws/{self.call_id}"
        self._ws = await websockets.connect(uri, open_timeout=10)
        await self._ws.send(
            json.dumps(
                {
                    "event": "start",
                    "start": {
                        "stream_sid": self.stream_sid,
                        "call_sid": self.call_sid,
                        "account_sid": self.account_sid,
                        "from": self.from_number,
                        "to": self.to_number,
                        "custom_parameters": "",
                    },
                }
            )
        )
        self._recv_task = asyncio.create_task(self._receive_loop())
        self._send_queue = asyncio.Queue()
        self._send_task = asyncio.create_task(self._send_loop())

    async def _send_loop(self) -> None:
        """Continuously streams media frames for the life of the call —
        real speech when queued via say()/send_media_bytes(), filler
        silence otherwise.

        A real telephony line never goes idle: Exotel streams audio
        continuously from the moment the call connects. Two things in the
        real Voice Gateway depend on that continuity, and silently break if
        the client instead sends a burst then goes quiet (as an earlier,
        simpler version of this client did):
          1. pipecat.runner.utils.parse_telephony_websocket peeks at a
             second WebSocket message before returning from the initial
             handshake — with nothing further arriving, that peek just
             hangs, and everything downstream (StartFrame, the greeting)
             is blocked until it does.
          2. STTProcessor's end-of-turn detector counts consecutive silent
             frames; if the stream stops instead of continuing with real
             silence, the count freezes short of the threshold and the
             turn never flushes, silently absorbing the next turn's speech
             into the same buffer.
        """
        assert self._ws is not None
        assert self._send_queue is not None
        silence_chunk = b"\x00" * CHUNK_BYTES
        try:
            while True:
                try:
                    chunk = self._send_queue.get_nowait()
                    self._send_queue.task_done()
                except asyncio.QueueEmpty:
                    chunk = silence_chunk
                payload = base64.b64encode(chunk).decode("ascii")
                await self._ws.send(json.dumps({"event": "media", "media": {"payload": payload}}))
                await asyncio.sleep(0.002)
        except websockets.exceptions.ConnectionClosed:
            pass

    async def _receive_loop(self) -> None:
        assert self._ws is not None
        try:
            async for raw in self._ws:
                msg = json.loads(raw)
                if msg.get("event") == "media":
                    self.received_media.append(base64.b64decode(msg["media"]["payload"]))
                else:
                    self.received_other.append(msg)
        except websockets.exceptions.ConnectionClosed as exc:
            print(
                f"[client] receive loop ended: ConnectionClosed code={exc.code} "
                f"reason={exc.reason!r}",
                flush=True,
            )

    async def send_media_bytes(self, pcm16_8k_mono: bytes) -> None:
        """Queues raw PCM as 20ms frames (matching Exotel's actual chunking)
        for the continuous _send_loop to stream out in order."""
        assert self._send_queue is not None
        for i in range(0, len(pcm16_8k_mono), CHUNK_BYTES):
            await self._send_queue.put(pcm16_8k_mono[i : i + CHUNK_BYTES])

    async def send_silence(self, ms: int) -> None:
        assert self._send_queue is not None
        silence_chunk = b"\x00" * CHUNK_BYTES
        for _ in range(0, ms, CHUNK_MS):
            await self._send_queue.put(silence_chunk)

    async def say(self, wav_path: str, *, trailing_silence_ms: int = 700) -> None:
        """Queues one fixture WAV as caller speech, then enough explicit
        silence to trigger the gateway's end-of-turn detection (see
        services/voice-gateway/conversation.py::STTProcessor) — on top of
        the continuous filler silence _send_loop already streams between
        calls, so the turn boundary is unambiguous. Waits for the queue to
        drain so callers can rely on say() meaning "the audio has been
        sent"."""
        assert self._send_queue is not None
        pcm = load_wav_8k_mono16(wav_path)
        await self.send_media_bytes(pcm)
        await self.send_silence(trailing_silence_ms)
        while not self._send_queue.empty():
            await asyncio.sleep(0.01)

    async def wait_for_reply_audio(self, *, timeout: float = 15.0, quiet_for: float = 1.0) -> bytes:
        """Waits until media frames stop arriving for `quiet_for` seconds
        (the assistant's turn has finished), returns the concatenated PCM."""
        start_count = len(self.received_media)
        deadline = asyncio.get_event_loop().time() + timeout
        last_growth = asyncio.get_event_loop().time()
        last_seen = start_count
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.1)
            if len(self.received_media) > last_seen:
                last_seen = len(self.received_media)
                last_growth = asyncio.get_event_loop().time()
            elif len(self.received_media) > start_count and (
                asyncio.get_event_loop().time() - last_growth
            ) >= quiet_for:
                break
        return b"".join(self.received_media[start_count:])

    async def stop_and_disconnect(self) -> None:
        if self._send_task is not None:
            self._send_task.cancel()
        if self._recv_task is not None:
            self._recv_task.cancel()
        if self._ws is not None:
            await self._ws.close()
