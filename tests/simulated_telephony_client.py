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

SimulatedTwilioCall (below) is the same idea for Twilio's Media Streams
contract, which is materially different on the wire — not just different
field names. Every shape below was read directly out of the installed
pipecat-ai==1.7.0 source (pipecat/serializers/twilio.py,
pipecat/runner/utils.py), not from Twilio's own docs, so it matches what
this repo's TwilioFrameSerializer/parse_telephony_websocket actually parse:

  * "start" handshake: streamSid/callSid live nested under `start` in
    camelCase (`start.streamSid`, `start.callSid`), NOT top-level and NOT
    snake_case — this, not message order, is how pipecat tells Twilio and
    Exotel apart (parse_telephony_websocket only inspects the first two WS
    messages; the optional "connected" event before "start" is never
    itself inspected).
  * "media" events carry G.711 mu-law-encoded audio (audio/x-mulaw) at
    8000 Hz mono in `media.payload` — Exotel's is raw PCM16 at 8kHz. This
    client mu-law encodes/decodes with the stdlib `audioop` module, the
    same codec TwilioFrameSerializer itself uses
    (pipecat/audio/utils.py: audioop.lin2ulaw / audioop.ulaw2lin) — so a
    round trip through this client exercises the real codec path, not a
    stand-in for it.
  * Outbound (gateway -> "Twilio") media/clear frames carry `streamSid` at
    the TOP level of the JSON object, not nested under `media` — the
    opposite of the inbound shape.
"""

from __future__ import annotations

import asyncio
import audioop  # noqa: PLC2801 — stdlib G.711 codec; see module docstring
import base64
import contextlib
import json
import wave
from dataclasses import dataclass, field

import websockets

SAMPLE_RATE = 8000
CHUNK_MS = 20
CHUNK_BYTES = CHUNK_MS * SAMPLE_RATE // 1000 * 2  # 16-bit mono
TWILIO_CHUNK_SAMPLES = CHUNK_MS * SAMPLE_RATE // 1000  # 1 byte/sample once mu-law encoded


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
            elif (
                len(self.received_media) > start_count
                and (asyncio.get_event_loop().time() - last_growth) >= quiet_for
            ):
                break
        return b"".join(self.received_media[start_count:])

    async def stop_and_disconnect(self) -> None:
        if self._send_task is not None:
            self._send_task.cancel()
        if self._recv_task is not None:
            self._recv_task.cancel()
        if self._ws is not None:
            await self._ws.close()


@dataclass
class SimulatedTwilioCall:
    """One simulated Twilio Media Streams session against a running Voice
    Gateway — the Twilio-shaped counterpart of SimulatedCall above (see this
    module's docstring for the verified wire-format differences). A real
    WebSocket client exercising the real /ws/{call_id} endpoint and the
    real TwilioFrameSerializer codec path, standing in only for Twilio
    Media Streams itself.
    """

    call_id: str
    base_url: str = "ws://127.0.0.1:9000"
    stream_sid: str = "MZsimulatedstream"
    call_sid: str = "CAsimulatedcallsid"
    account_sid: str = "ACsimulatedaccount"
    from_number: str = "+911111111111"
    to_number: str = "+917314623519"

    received_media: list[bytes] = field(default_factory=list, init=False)
    received_other: list[dict] = field(default_factory=list, init=False)
    _ws: websockets.ClientConnection | None = field(default=None, init=False)
    _recv_task: asyncio.Task | None = field(default=None, init=False)
    _send_task: asyncio.Task | None = field(default=None, init=False)
    _send_queue: asyncio.Queue | None = field(default=None, init=False)
    _seq: int = field(default=0, init=False)
    _chunk_counter: int = field(default=0, init=False)

    def _next_seq(self) -> str:
        self._seq += 1
        return str(self._seq)

    async def connect(self) -> None:
        uri = f"{self.base_url}/ws/{self.call_id}"
        self._ws = await websockets.connect(uri, open_timeout=10)
        # Real Twilio sends "connected" before "start" — included here for
        # wire fidelity, even though pipecat's own detection (see module
        # docstring) only ever inspects the "start" message's shape.
        await self._ws.send(
            json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"})
        )
        await self._ws.send(
            json.dumps(
                {
                    "event": "start",
                    "sequenceNumber": self._next_seq(),
                    "streamSid": self.stream_sid,
                    "start": {
                        "accountSid": self.account_sid,
                        "streamSid": self.stream_sid,
                        "callSid": self.call_sid,
                        "tracks": ["inbound"],
                        "mediaFormat": {
                            "encoding": "audio/x-mulaw",
                            "sampleRate": SAMPLE_RATE,
                            "channels": 1,
                        },
                        "customParameters": {
                            "from_number": self.from_number,
                            "to_number": self.to_number,
                        },
                    },
                }
            )
        )
        self._recv_task = asyncio.create_task(self._receive_loop())
        self._send_queue = asyncio.Queue()
        self._send_task = asyncio.create_task(self._send_loop())

    async def _send_loop(self) -> None:
        """Continuously streams mu-law media frames for the life of the
        call — see SimulatedCall._send_loop's docstring for why continuous
        streaming (rather than bursts) is required; the same two reasons
        apply identically to the Twilio path."""
        assert self._ws is not None
        assert self._send_queue is not None
        silence_chunk_pcm = b"\x00" * CHUNK_BYTES
        try:
            while True:
                try:
                    chunk_pcm = self._send_queue.get_nowait()
                    self._send_queue.task_done()
                except asyncio.QueueEmpty:
                    chunk_pcm = silence_chunk_pcm
                chunk_ulaw = audioop.lin2ulaw(chunk_pcm, 2)
                self._chunk_counter += 1
                payload = base64.b64encode(chunk_ulaw).decode("ascii")
                await self._ws.send(
                    json.dumps(
                        {
                            "event": "media",
                            "sequenceNumber": self._next_seq(),
                            "streamSid": self.stream_sid,
                            "media": {
                                "track": "inbound",
                                "chunk": str(self._chunk_counter),
                                "timestamp": str(self._chunk_counter * CHUNK_MS),
                                "payload": payload,
                            },
                        }
                    )
                )
                await asyncio.sleep(0.002)
        except websockets.exceptions.ConnectionClosed:
            pass

    async def _receive_loop(self) -> None:
        """Decodes inbound mu-law media back to PCM16 so callers see the
        same PCM16-bytes contract SimulatedCall.received_media exposes,
        regardless of which provider's wire codec produced it."""
        assert self._ws is not None
        try:
            async for raw in self._ws:
                msg = json.loads(raw)
                if msg.get("event") == "media":
                    ulaw = base64.b64decode(msg["media"]["payload"])
                    self.received_media.append(audioop.ulaw2lin(ulaw, 2))
                else:
                    self.received_other.append(msg)
        except websockets.exceptions.ConnectionClosed as exc:
            print(
                f"[client] receive loop ended: ConnectionClosed code={exc.code} "
                f"reason={exc.reason!r}",
                flush=True,
            )

    async def send_media_bytes(self, pcm16_8k_mono: bytes) -> None:
        """Queues raw PCM16 as 20ms frames; _send_loop mu-law encodes each
        chunk immediately before it goes on the wire (matching how a real
        Twilio media stream is continuously encoded, not pre-encoded in
        bulk)."""
        assert self._send_queue is not None
        for i in range(0, len(pcm16_8k_mono), CHUNK_BYTES):
            await self._send_queue.put(pcm16_8k_mono[i : i + CHUNK_BYTES])

    async def send_silence(self, ms: int) -> None:
        assert self._send_queue is not None
        silence_chunk = b"\x00" * CHUNK_BYTES
        for _ in range(0, ms, CHUNK_MS):
            await self._send_queue.put(silence_chunk)

    async def send_dtmf(self, digit: str) -> None:
        assert self._ws is not None
        await self._ws.send(
            json.dumps(
                {
                    "event": "dtmf",
                    "streamSid": self.stream_sid,
                    "dtmf": {"track": "inbound_track", "digit": digit},
                }
            )
        )

    async def say(self, wav_path: str, *, trailing_silence_ms: int = 700) -> None:
        """Same contract as SimulatedCall.say() — see its docstring."""
        assert self._send_queue is not None
        pcm = load_wav_8k_mono16(wav_path)
        await self.send_media_bytes(pcm)
        await self.send_silence(trailing_silence_ms)
        while not self._send_queue.empty():
            await asyncio.sleep(0.01)

    async def wait_for_reply_audio(self, *, timeout: float = 15.0, quiet_for: float = 1.0) -> bytes:
        """Same contract as SimulatedCall.wait_for_reply_audio() — see its
        docstring. Returned bytes are PCM16 (already decoded in
        _receive_loop above), not raw mu-law."""
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

    async def send_stop(self) -> None:
        """Real Twilio sends a "stop" event when the call ends, before the
        WebSocket closes. Not read by pipecat (see module docstring) — sent
        here only for wire fidelity / to exercise the gateway's handling of
        a close that follows an explicit stop, same as a real hangup."""
        assert self._ws is not None
        await self._ws.send(
            json.dumps(
                {
                    "event": "stop",
                    "sequenceNumber": self._next_seq(),
                    "streamSid": self.stream_sid,
                    "stop": {"accountSid": self.account_sid, "callSid": self.call_sid},
                }
            )
        )

    async def stop_and_disconnect(self) -> None:
        if self._ws is not None:
            with contextlib.suppress(websockets.exceptions.ConnectionClosed):
                await self.send_stop()
        if self._send_task is not None:
            self._send_task.cancel()
        if self._recv_task is not None:
            self._recv_task.cancel()
        if self._ws is not None:
            await self._ws.close()
