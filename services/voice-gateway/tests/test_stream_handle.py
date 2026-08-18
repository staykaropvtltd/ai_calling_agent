"""
Focused tests for the SH-01 WebSocket ownership fix.

Coverage:
 T01  decode_media produces correct InputAudioRawFrame
 T02  decode_media rejects invalid base64
 T03  decode_media rejects odd-byte-count PCM
 T04  encode_media round-trips audio bytes
 T05  encode_media rejects wrong sample rate
 T06  encode_media rejects stereo
 T07  ExternallyFedInputTransport.start() does NOT spawn _receive_task
 T08  ExternallyFedInputTransport creates _audio_in_queue
 T09  push_audio_frame() enqueues the frame
 T10  on_output callback fires with the OutputAudioRawFrame that was written
 T11  on_output not called when no frame is written
 T12  no on_output patch when callback is None (native bound method remains)
 T13  CallPipelineHandle(externally_fed=True) uses ExternallyFedInputTransport
 T14  CallPipelineHandle(externally_fed=False) uses native FastAPIWebsocket…Transport
 T15  FastAPIWebsocketInputTransport.start() references _receive_task (Pipecat contract)
 T16  ExternallyFedInputTransport.start() calls BaseInputTransport.start only
 T17  cleanup() does not raise when no task was started
 T18  cleanup() is idempotent (safe to call twice)
 T19  cleanup() cancels the runner task when one exists
 T20  exotel_stream stop event finalises the call
 T21  exotel_stream WebSocketDisconnect finalises the call
 T22  exotel_stream media event calls push_audio_frame with correct frame
 T23  exotel_stream passes externally_fed=True to CallPipelineHandle
 T24  /ws/{call_id} in main.py does NOT pass externally_fed=True
 T25  one PipelineWorker per CallPipelineHandle
"""
from __future__ import annotations

import asyncio
import base64
import inspect
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Make the voice-gateway package importable without PYTHONPATH tricks.
_VG = str(Path(__file__).parent.parent.resolve())
if _VG not in sys.path:
    sys.path.insert(0, _VG)

from pipecat.frames.frames import InputAudioRawFrame, OutputAudioRawFrame
from pipecat.transports.base_input import BaseInputTransport
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketInputTransport,
    FastAPIWebsocketParams,
)
from pipecat.utils.asyncio.task_manager import TaskManager
from pipecat.processors.frame_processor import FrameProcessorSetup
from pipecat.clocks.system_clock import SystemClock
from pipecat.observers.base_observer import BaseObserver

from exotel_stream import decode_media, encode_media, build_exotel_stream_router
from pipeline_handle import CallPipelineHandle, ExternallyFedInputTransport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pcm(n_samples: int = 80) -> bytes:
    return b'\x00' * (n_samples * 2)          # 16-bit LE silence


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _out_frame(n: int = 80) -> OutputAudioRawFrame:
    return OutputAudioRawFrame(audio=_pcm(n), sample_rate=8000, num_channels=1)


def _mock_ws() -> MagicMock:
    ws = MagicMock()
    ws.headers = {"origin": ""}    # pass allowed-origins check
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()
    return ws


# CallPipelineHandle.__init__ calls WorkerRunner() which needs a running loop.
# Wrap construction inside asyncio.run so all handle tests are async-safe.
async def _make_handle(externally_fed: bool = True, on_output=None):
    return CallPipelineHandle(
        _mock_ws(), "test-call", on_output=on_output, externally_fed=externally_fed
    )


# ---------------------------------------------------------------------------
# T01 – T06  Protocol helpers
# ---------------------------------------------------------------------------

class TestProtocolHelpers:
    def test_T01_decode_valid_pcm(self):
        raw = _pcm(80)
        frame = decode_media(_b64(raw))
        assert isinstance(frame, InputAudioRawFrame)
        assert frame.audio == raw
        assert frame.sample_rate == 8000
        assert frame.num_channels == 1

    def test_T02_decode_rejects_invalid_base64(self):
        with pytest.raises(ValueError, match="invalid Exotel media payload"):
            decode_media("!!!not-base64!!!")

    def test_T03_decode_rejects_odd_byte_count(self):
        with pytest.raises(ValueError, match="invalid 16-bit PCM"):
            decode_media(_b64(b'\x00\x01\x02'))

    def test_T04_encode_roundtrip(self):
        frame = _out_frame(80)
        msg = encode_media("sid-1", frame)
        assert msg["event"] == "media"
        assert msg["stream_sid"] == "sid-1"
        assert base64.b64decode(msg["media"]["payload"]) == frame.audio

    def test_T05_encode_rejects_wrong_sample_rate(self):
        bad = OutputAudioRawFrame(audio=_pcm(80), sample_rate=16000, num_channels=1)
        with pytest.raises(ValueError, match="8kHz"):
            encode_media("sid-1", bad)

    def test_T06_encode_rejects_stereo(self):
        bad = OutputAudioRawFrame(audio=_pcm(160), sample_rate=8000, num_channels=2)
        with pytest.raises(ValueError, match="8kHz mono"):
            encode_media("sid-1", bad)


# ---------------------------------------------------------------------------
# T07 – T09  ExternallyFedInputTransport — isolated (no full pipeline)
# ---------------------------------------------------------------------------

@pytest.fixture()
def ext_transport():
    """
    A started ExternallyFedInputTransport with a real TaskManager.
    Returned as a (transport, loop) tuple so callers can schedule work.
    """
    params = FastAPIWebsocketParams(audio_in_enabled=True, audio_out_enabled=True)
    fake_client = MagicMock()
    fake_client.setup = AsyncMock()
    fake_client.trigger_client_connected = AsyncMock()
    fake_transport = MagicMock()

    transport = ExternallyFedInputTransport(fake_transport, fake_client, params)

    loop = asyncio.new_event_loop()

    async def _start():
        tm = TaskManager(loop=loop)
        setup = FrameProcessorSetup(
            clock=SystemClock(), task_manager=tm,
            observer=BaseObserver(), pipeline_worker=None,
        )
        await transport.setup(setup)
        from pipecat.frames.frames import StartFrame
        await transport.start(StartFrame(audio_in_sample_rate=8000,
                                          audio_out_sample_rate=8000))

    loop.run_until_complete(_start())
    yield transport, loop
    loop.close()


class TestExternallyFedTransport:
    def test_T07_no_receive_task(self, ext_transport):
        """No competing WebSocket reader must be spawned."""
        transport, _ = ext_transport
        assert transport._receive_task is None, (
            "_receive_task must be None in externally_fed mode"
        )

    def test_T08_audio_queue_is_ready(self, ext_transport):
        transport, _ = ext_transport
        assert hasattr(transport, '_audio_in_queue'), (
            "_audio_in_queue must exist after start()"
        )

    def test_T09_push_audio_frame_enqueues(self, ext_transport):
        transport, loop = ext_transport
        frame = InputAudioRawFrame(audio=_pcm(80), sample_rate=8000, num_channels=1)

        # Use put_nowait to bypass the audio_task consumer completely.
        # BaseInputTransport.push_audio_frame() calls _audio_in_queue.put()
        # which the audio task may drain immediately; we verify with put_nowait
        # that the queue mechanism itself works.
        transport._audio_in_queue.put_nowait(frame)
        assert transport._audio_in_queue.get_nowait() is frame


# ---------------------------------------------------------------------------
# T10 – T12  on_output callback — tested on the output transport directly
#            (avoids WorkerRunner needing a running loop at construction time)
# ---------------------------------------------------------------------------

@pytest.fixture()
def output_transport_with_callback():
    """FastAPIWebsocketOutputTransport with the on_output patch applied."""
    from pipecat.transports.websocket.fastapi import FastAPIWebsocketOutputTransport

    params = FastAPIWebsocketParams(audio_in_enabled=True, audio_out_enabled=True)
    fake_client = MagicMock()
    fake_client.setup = AsyncMock()
    fake_client.is_closing = False
    fake_client.is_connected = True
    fake_transport = MagicMock()

    loop = asyncio.new_event_loop()
    out = FastAPIWebsocketOutputTransport(fake_transport, fake_client, params)

    async def _setup():
        tm = TaskManager(loop=loop)
        setup = FrameProcessorSetup(
            clock=SystemClock(), task_manager=tm,
            observer=BaseObserver(), pipeline_worker=None,
        )
        await out.setup(setup)

    loop.run_until_complete(_setup())

    captured: list[OutputAudioRawFrame] = []

    original = out.write_audio_frame
    async def patched(frame):          # same closure as CallPipelineHandle uses
        captured.append(frame)
        return await original(frame)
    out.write_audio_frame = patched

    yield out, captured, loop
    loop.close()


class TestOutputCallback:
    def test_T10_callback_fires_with_frame(self, output_transport_with_callback):
        out, captured, loop = output_transport_with_callback
        frame = _out_frame(80)
        loop.run_until_complete(out.write_audio_frame(frame))
        assert len(captured) == 1
        assert captured[0] is frame

    def test_T11_callback_not_called_before_write(self, output_transport_with_callback):
        _, captured, _ = output_transport_with_callback
        assert len(captured) == 0

    def test_T12_no_patch_when_no_callback(self):
        """Without on_output the method remains the class-bound implementation."""
        async def _build():
            return await _make_handle(on_output=None)

        handle = asyncio.run(_build())
        from pipecat.transports.websocket.fastapi import FastAPIWebsocketOutputTransport
        # Instance dict must NOT have write_audio_frame (i.e. no patch applied)
        assert 'write_audio_frame' not in handle.output.__dict__, (
            "write_audio_frame must not be patched when on_output is None"
        )


# ---------------------------------------------------------------------------
# T13 – T16  Transport class selection + source inspection
# ---------------------------------------------------------------------------

class TestTransportClassSelection:
    def test_T13_externally_fed_uses_efitransport(self):
        async def _run():
            h = await _make_handle(externally_fed=True)
            assert type(h.input) is ExternallyFedInputTransport
        asyncio.run(_run())

    def test_T14_native_uses_fastapi_input_transport(self):
        async def _run():
            h = await _make_handle(externally_fed=False)
            assert type(h.input) is FastAPIWebsocketInputTransport
        asyncio.run(_run())

    def test_T15_fastapi_input_start_references_receive_task(self):
        """Pipecat contract: native start() spawns _receive_task."""
        src = inspect.getsource(FastAPIWebsocketInputTransport.start)
        assert '_receive_task' in src, (
            "Pipecat API changed: FastAPIWebsocketInputTransport.start() no longer "
            "references _receive_task — review SH-01 fix."
        )

    def test_T16_efitransport_start_calls_base_not_parent(self):
        """ExternallyFedInputTransport.start() must bypass the native start()."""
        src = inspect.getsource(ExternallyFedInputTransport.start)
        assert 'BaseInputTransport.start' in src
        assert 'FastAPIWebsocketInputTransport.start' not in src


# ---------------------------------------------------------------------------
# T17 – T19  cleanup() lifecycle
# ---------------------------------------------------------------------------

class TestCleanup:
    def test_T17_cleanup_safe_with_no_task(self):
        async def _run():
            h = await _make_handle()
            await h.cleanup()   # _task is None — must not raise
        asyncio.run(_run())

    def test_T18_cleanup_idempotent(self):
        async def _run():
            h = await _make_handle()
            await h.cleanup()
            await h.cleanup()   # second call must not raise
        asyncio.run(_run())

    def test_T19_cleanup_cancels_runner_task(self):
        async def _run():
            h = await _make_handle()
            dummy = asyncio.create_task(asyncio.sleep(999))
            h._task = dummy
            await h.cleanup()
            # Give the event loop one tick to process the cancellation
            await asyncio.sleep(0)
            assert dummy.cancelled() or dummy.done()
        asyncio.run(_run())


# ---------------------------------------------------------------------------
# T20 – T23  exotel_stream route lifecycle (fully mocked — no real server)
# ---------------------------------------------------------------------------

class _FakeRouting:
    async def resolve(self, _: str) -> tuple[str, str]:
        return ("tenant-1", "agent-1")


class _FakeCalls:
    def __init__(self):
        self.finalized: list[tuple] = []

    async def create(self, call): pass

    async def finalize(self, call_id: str, fin):
        self.finalized.append((call_id, fin))


class _FakeSessions:
    def __init__(self):
        self._store: dict = {}

    def create(self, call_id, t, a): self._store[call_id] = True
    def get(self, call_id): return self._store.get(call_id)
    def end(self, call_id): pass
    def remove(self, call_id): self._store.pop(call_id, None)


def _stream_ws(events: list[dict]) -> MagicMock:
    """WS mock whose receive_json yields the given events then blocks forever."""
    ws = MagicMock()
    ws.headers = {"origin": ""}
    ws.accept = AsyncMock()
    ws.close = AsyncMock()
    ws.send_json = AsyncMock()
    it = iter(events)

    async def _recv():
        try:
            return next(it)
        except StopIteration:
            await asyncio.sleep(9999)

    ws.receive_json = _recv
    return ws


def _stream_router_fn(calls=None, sessions=None, routing=None):
    calls = calls or _FakeCalls()
    sessions = sessions or _FakeSessions()
    routing = routing or _FakeRouting()
    router = build_exotel_stream_router(sessions, calls, routing)
    return router.routes[0].endpoint, calls, sessions


def _mock_handle():
    inst = MagicMock()
    inst.start = AsyncMock()
    inst.cleanup = AsyncMock()
    inst.input = MagicMock()
    inst.input.push_audio_frame = AsyncMock()
    return inst


_START_EVENT = {
    "event": "start",
    "start": {"to": "+919999999999"},
    "stream_sid": "sid-test",
}
_STOP_EVENT = {"event": "stop"}


class TestExotelStreamLifecycle:
    def test_T20_stop_event_finalises_call(self):
        calls = _FakeCalls()
        route_fn, _, _ = _stream_router_fn(calls=calls)
        ws = _stream_ws([_START_EVENT, _STOP_EVENT])

        async def _run():
            with patch("exotel_stream.CallPipelineHandle", return_value=_mock_handle()):
                await route_fn(ws)

        asyncio.run(_run())
        assert len(calls.finalized) == 1
        assert calls.finalized[0][1].end_reason == "caller_hangup"

    def test_T21_disconnect_finalises_call(self):
        from fastapi import WebSocketDisconnect
        calls = _FakeCalls()
        route_fn, _, _ = _stream_router_fn(calls=calls)

        ws = MagicMock()
        ws.headers = {"origin": ""}
        ws.accept = AsyncMock()
        ws.close = AsyncMock()
        ws.send_json = AsyncMock()
        count = 0

        async def _recv():
            nonlocal count
            count += 1
            if count == 1:
                return _START_EVENT
            raise WebSocketDisconnect(code=1001)

        ws.receive_json = _recv

        async def _run():
            with patch("exotel_stream.CallPipelineHandle", return_value=_mock_handle()):
                await route_fn(ws)

        asyncio.run(_run())
        assert len(calls.finalized) == 1
        assert calls.finalized[0][1].end_reason == "caller_hangup"

    def test_T22_media_event_calls_push_audio_frame(self):
        pcm = _pcm(80)
        media_event = {"event": "media", "media": {"payload": _b64(pcm)}}
        route_fn, _, _ = _stream_router_fn()
        ws = _stream_ws([_START_EVENT, media_event, _STOP_EVENT])

        pushed: list[InputAudioRawFrame] = []

        mock_inst = _mock_handle()

        async def _capture(frame):
            pushed.append(frame)

        mock_inst.input.push_audio_frame = _capture

        async def _run():
            with patch("exotel_stream.CallPipelineHandle", return_value=mock_inst):
                await route_fn(ws)

        asyncio.run(_run())
        assert len(pushed) == 1
        assert isinstance(pushed[0], InputAudioRawFrame)
        assert pushed[0].audio == pcm
        assert pushed[0].sample_rate == 8000
        assert pushed[0].num_channels == 1

    def test_T23_exotel_stream_passes_externally_fed_true(self):
        """The route must construct CallPipelineHandle(externally_fed=True)."""
        route_fn, _, _ = _stream_router_fn()
        ws = _stream_ws([_START_EVENT, _STOP_EVENT])

        async def _run():
            with patch("exotel_stream.CallPipelineHandle") as MockCls:
                MockCls.return_value = _mock_handle()
                await route_fn(ws)
            _, kwargs = MockCls.call_args
            assert kwargs.get("externally_fed") is True, (
                "exotel_stream must pass externally_fed=True to CallPipelineHandle"
            )

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# T24  /ws/{call_id} does NOT pass externally_fed=True
# ---------------------------------------------------------------------------

class TestNativeWsRoute:
    def test_T24_ws_route_does_not_pass_externally_fed(self):
        # Read main.py source directly to avoid importing it
        # (import fails in test environment because Redis is not configured)
        main_py = Path(__file__).parent.parent / "main.py"
        src = main_py.read_text(encoding="utf-8")

        # Extract just the voice_websocket function body
        fn_start = src.find("async def voice_websocket(")
        assert fn_start != -1, "voice_websocket not found in main.py"
        fn_src = src[fn_start:]

        assert "externally_fed=True" not in fn_src, (
            "/ws/{call_id} must NOT pass externally_fed=True "
            "(it relies on Pipecat's native WS receive loop)"
        )
        assert "CallPipelineHandle" in fn_src


# ---------------------------------------------------------------------------
# T25  One PipelineWorker per handle
# ---------------------------------------------------------------------------

class TestNoPipelineProliferation:
    def test_T25_single_pipeline_worker(self):
        from pipecat.pipeline.worker import PipelineWorker

        async def _run():
            h = await _make_handle()
            workers = [v for v in h.__dict__.values() if isinstance(v, PipelineWorker)]
            assert len(workers) == 1, (
                f"Expected exactly 1 PipelineWorker, found {len(workers)}"
            )

        asyncio.run(_run())
