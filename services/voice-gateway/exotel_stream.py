"""Thin Exotel Voicebot JSON/PCM WebSocket adapter."""
from __future__ import annotations
import base64, binascii
from dataclasses import dataclass
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pipecat.frames.frames import InputAudioRawFrame, OutputAudioRawFrame
from internal_calls import CallCreation, CallFinalization, InternalCalls
from exotel_routes import PhoneRouting
from datetime import datetime, timezone
from uuid import uuid4
from pipeline_handle import CallPipelineHandle

def decode_media(payload: str) -> InputAudioRawFrame:
    try: audio = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc: raise ValueError("invalid Exotel media payload") from exc
    if len(audio) % 2: raise ValueError("invalid 16-bit PCM payload")
    return InputAudioRawFrame(audio=audio, sample_rate=8000, num_channels=1)

def encode_media(stream_sid: str, frame: OutputAudioRawFrame) -> dict:
    if frame.sample_rate != 8000 or frame.num_channels != 1: raise ValueError("Exotel requires 8kHz mono PCM")
    return {"event":"media", "stream_sid":stream_sid, "media":{"payload":base64.b64encode(frame.audio).decode("ascii")}}

@dataclass
class StreamState:
    call_id: str | None = None; stream_sid: str | None = None; stopped: bool = False

def build_exotel_stream_router(session_manager: object, calls: InternalCalls, routing: PhoneRouting | None) -> APIRouter:
    router=APIRouter()
    @router.websocket('/telephony/exotel/stream')
    async def stream(ws: WebSocket):
        await ws.accept(); state=StreamState(); handle=None
        async def cleanup(reason: str):
            if state.stopped: return
            state.stopped=True
            if state.call_id:
                await calls.finalize(state.call_id, CallFinalization(ended_at=datetime.now(timezone.utc), end_reason=reason))
                if session_manager.get(state.call_id): session_manager.end(state.call_id); session_manager.remove(state.call_id)
            if handle: await handle.cleanup()
        try:
            while True:
                event=await ws.receive_json(); kind=event.get('event')
                if kind=='start':
                    start=event.get('start') or {}; to=start.get('to')
                    if routing is None or not to: await ws.close(code=1011); return
                    tenant,agent=await routing.resolve(to); state.call_id=str(uuid4()); state.stream_sid=start.get('stream_sid') or event.get('stream_sid')
                    await calls.create(CallCreation(call_id=state.call_id,tenant_id=tenant,agent_id=agent,started_at=datetime.now(timezone.utc)))
                    session_manager.create(state.call_id,tenant,agent)
                    async def outbound(frame):
                        if state.stream_sid: await ws.send_json(encode_media(state.stream_sid, frame))
                    handle=CallPipelineHandle(ws, state.call_id, outbound, externally_fed=True); await handle.start()
                elif kind=='media':
                    if handle is None: continue
                    await handle.input.push_audio_frame(decode_media((event.get('media') or {}).get('payload','')))
                elif kind=='stop': await cleanup('caller_hangup'); await ws.close(); return
                # connected/dtmf/mark/clear/unknown are intentionally harmless.
        except WebSocketDisconnect: await cleanup('caller_hangup')
    return router
