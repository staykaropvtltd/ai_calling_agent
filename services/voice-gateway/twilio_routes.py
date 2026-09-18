"""Twilio HTTP boundary: the TwiML voice URL + the status callback.

Twilio splits what Exotel's single Passthru callback does into two separate
requests, so this module (unlike exotel_routes.py) needs two endpoints:

  * /telephony/twilio/twiml   — the request Twilio blocks on, synchronously,
    to learn what to do with the call. This is where the internal Call
    record + gateway session get created (the same job exotel_routes.py's
    "connected" branch does) and where the TwiML pointing at this gateway's
    media-stream WebSocket is returned.

  * /telephony/twilio/status  — an independent, asynchronous webhook Twilio
    fires as the call progresses (queued/ringing/in-progress/completed/...).
    Records a Phase 6 CallJob event for every status, and on a terminal
    status also finalizes the Call and tears down the session (the same job
    exotel_routes.py's "terminal" branch does).

No Twilio audio/media logic lives here — see voice_pipeline.py for the
WebSocket media path this endpoint's TwiML points at.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, Response, status
from internal_calls import CallCreation, CallFinalization, InternalApiError, InternalCalls
from twilio.twiml.voice_response import Connect, VoiceResponse
from twilio_signature import validate_twilio_request


class PhoneRouting(Protocol):
    async def resolve(self, dialed_number: str) -> tuple[str, str]: ...


class CallStore(Protocol):
    """Persistent mapping from Twilio CallSid to internal call_id.

    Same contract exotel_routes.py's CallStore Protocol defines — kept as a
    separate (structurally identical) Protocol here rather than imported
    from exotel_routes.py, so the Twilio integration has no dependency on
    the Exotel module and can be read/maintained/removed independently.
    """

    def set(self, provider_call_id: str, call_id: str) -> None: ...
    def get(self, provider_call_id: str) -> str | None: ...
    def delete(self, provider_call_id: str) -> None: ...


class _DictCallStore:
    """In-memory fallback CallStore — not restart-safe. Same role as
    exotel_routes.py's own _DictCallStore; duplicated rather than imported
    for the same independence reason as the Protocol above."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def set(self, provider_call_id: str, call_id: str) -> None:
        self._store[provider_call_id] = call_id

    def get(self, provider_call_id: str) -> str | None:
        return self._store.get(provider_call_id)

    def delete(self, provider_call_id: str) -> None:
        self._store.pop(provider_call_id, None)


class EventRecorder(Protocol):
    """Phase 6 durable idempotency — identical contract to
    exotel_routes.py's EventRecorder Protocol. Both Twilio's status values
    and Exotel's event-type strings share the same (provider_call_id,
    event_type) unique index in services/api's call_jobs table; this is
    safe because provider_call_id values from the two providers are drawn
    from disjoint ID spaces (Twilio CallSids vs Exotel CallSids) and never
    collide, even where the strings happen to overlap (e.g. "completed",
    "failed" are used by both providers as event_type values)."""

    async def record(
        self,
        *,
        provider_call_id: str,
        event_type: str,
        tenant_id: str | None = None,
        call_id: str | None = None,
        payload: dict | None = None,
    ) -> bool: ...


class _InMemoryEventRecorder:
    """Non-durable fallback — same role as exotel_routes.py's own, and same
    caveat: this dedup state is lost on restart, which is exactly the gap a
    real (HTTP-backed) EventRecorder exists to close."""

    def __init__(self) -> None:
        self._seen: set[tuple[str, str]] = set()

    async def record(
        self,
        *,
        provider_call_id: str,
        event_type: str,
        tenant_id: str | None = None,
        call_id: str | None = None,
        payload: dict | None = None,
    ) -> bool:
        key = (provider_call_id, event_type)
        if key in self._seen:
            return True
        self._seen.add(key)
        return False


@dataclass(frozen=True)
class TwilioWebhookSettings:
    """Minimal settings the Twilio router needs at runtime — same narrowing
    pattern services/voice-gateway/src/main.py's _ExotelConfig uses for the
    Exotel router: only what build_twilio_router() actually reads, not the
    full packages.providers.telephony.TwilioSettings (which is the outbound
    REST provider's own config — account_sid/auth_token there authenticate
    *outgoing* API calls; auth_token here validates *incoming* webhooks,
    same value, different job).

    gateway_wss_host: hostname only, no scheme (e.g. "abc123.ngrok-free.app"
    or "voice.staykaro.org"), never "https://..." or "wss://...". This
    module is the reason for that convention: it needs the SAME host to
    build both a wss:// media-stream URL (below) and, if a future caller
    ever needs it, an https:// URL — that only works cleanly from a
    scheme-less value. TWILIO_TWIML_URL / TWILIO_STATUS_CALLBACK_URL are
    the opposite: full https:// URLs, because they're used directly and
    unmodified as REST parameters / RequestValidator inputs / Twilio Console
    webhook fields, never scheme-swapped.
    """

    auth_token: str
    twiml_url: str
    status_callback_url: str
    gateway_wss_host: str


# Twilio's documented CallStatus values that mean the call is over — the
# same role exotel_routes.py's "completed"/"failed"/"disconnected"/
# "terminal" set plays, just Twilio's own vocabulary.
_TERMINAL_STATUSES = {"completed", "busy", "failed", "no-answer", "canceled"}


def _stream_twiml(call_id: str, gateway_wss_host: str) -> Response:
    """<Connect><Stream> (not <Start><Stream>) — Connect hands call control
    to the media stream for the life of the call, which is what this
    gateway's bidirectional conversational pipeline (Phase 5) needs;
    <Start><Stream> is for one-way parallel streaming alongside other TwiML
    verbs, not this use case.

    The stream URL reuses the existing /ws/{call_id} route unchanged —
    voice_pipeline.py already auto-detects Twilio vs Exotel from the first
    WebSocket message via pipecat.runner.utils.parse_telephony_websocket, so
    no new WebSocket route is needed for Twilio.
    """
    vr = VoiceResponse()
    connect = Connect()
    connect.stream(url=f"wss://{gateway_wss_host}/ws/{call_id}")
    vr.append(connect)
    return Response(content=str(vr), media_type="application/xml")


def build_twilio_router(
    session_manager: object,
    settings: TwilioWebhookSettings,
    calls: InternalCalls,
    routing: PhoneRouting,
    call_store: CallStore | None = None,
    events: EventRecorder | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/telephony/twilio", tags=["Twilio"])
    _store: CallStore = call_store if call_store is not None else _DictCallStore()
    _events: EventRecorder = events if events is not None else _InMemoryEventRecorder()

    async def _validated_form(request: Request, expected_url: str) -> dict[str, str]:
        """Twilio POSTs application/x-www-form-urlencoded with an
        X-Twilio-Signature header computed over `expected_url` + the form
        fields — see twilio_signature.py for why `expected_url` must be the
        configured TWILIO_TWIML_URL / TWILIO_STATUS_CALLBACK_URL, not
        anything derived from this request."""
        form = await request.form()
        params = {k: str(v) for k, v in form.items()}
        signature = request.headers.get("X-Twilio-Signature", "")
        if not validate_twilio_request(
            auth_token=settings.auth_token,
            url=expected_url,
            params=params,
            signature=signature,
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid Twilio request signature",
            )
        return params

    @router.post("/twiml")
    async def twiml(request: Request) -> Response:
        params = await _validated_form(request, settings.twiml_url)

        provider_call_id = params.get("CallSid")
        if not provider_call_id:
            raise HTTPException(status_code=422, detail="Twilio request is missing CallSid")

        # Twilio retries this request (e.g. on a slow/failed response) using
        # the same CallSid — call_store is the durable (Redis-backed in
        # production, via _RedisCallStore in src/main.py) CallSid -> call_id
        # mapping that makes this endpoint idempotent: a retry gets back the
        # *same* call_id and Stream URL, never a second Call row or a second
        # gateway session.
        existing_call_id = _store.get(provider_call_id)
        if existing_call_id is not None:
            return _stream_twiml(existing_call_id, settings.gateway_wss_host)

        dialed_number = params.get("To")
        if not dialed_number:
            raise HTTPException(status_code=422, detail="Twilio request is missing To")

        if routing is None:
            raise HTTPException(
                status_code=503,
                detail="phone-number routing API dependency is unavailable",
            )
        try:
            tenant_id, agent_id = await routing.resolve(dialed_number)
        except InternalApiError as exc:
            raise HTTPException(status_code=404, detail="phone-number route not found") from exc

        call_id = str(uuid4())
        try:
            await calls.create(
                CallCreation(
                    call_id=call_id,
                    tenant_id=tenant_id,
                    agent_id=agent_id,
                    started_at=datetime.now(UTC),
                    provider_call_id=provider_call_id,
                )
            )
        except InternalApiError as exc:
            raise HTTPException(
                status_code=503, detail="internal call creation unavailable"
            ) from exc

        session_manager.create(call_id, tenant_id, agent_id)
        _store.set(provider_call_id, call_id)
        return _stream_twiml(call_id, settings.gateway_wss_host)

    @router.post("/status")
    async def twilio_status(request: Request) -> dict[str, str]:
        params = await _validated_form(request, settings.status_callback_url)

        provider_call_id = params.get("CallSid")
        call_status = (params.get("CallStatus") or "").strip().lower()
        if not provider_call_id or not call_status:
            raise HTTPException(
                status_code=422,
                detail="Twilio status callback is missing CallSid/CallStatus",
            )

        # Phase 6: durably records this one (provider_call_id, event_type)
        # event — the authoritative idempotency guarantee (partial unique
        # index in call_jobs), same mechanism exotel_routes.py's callback
        # uses, not an in-memory set. A retried status callback (Twilio does
        # retry on timeout/5xx) is reported back as a duplicate and never
        # double-processed below.
        try:
            is_duplicate = await _events.record(
                provider_call_id=provider_call_id,
                event_type=call_status,
                payload={"call_status": call_status},
            )
        except InternalApiError as exc:
            raise HTTPException(
                status_code=503, detail="durable event recording unavailable"
            ) from exc
        if is_duplicate:
            return {"status": "duplicate", "call_id": _store.get(provider_call_id) or ""}

        if call_status not in _TERMINAL_STATUSES:
            # Non-terminal progress event (queued/ringing/in-progress/...) —
            # already durably recorded above for Phase 6 processing; no
            # Call/session side effect until the call actually ends.
            return {"status": "ignored", "call_id": _store.get(provider_call_id) or ""}

        call_id = _store.get(provider_call_id)
        if not call_id:
            # A terminal status for a CallSid this gateway instance has no
            # session mapping for (e.g. arrived after a restart with no
            # durable mapping, or an out-of-band Twilio call) — safe no-op,
            # matching exotel_routes.py's identical "ignored" behavior.
            return {"status": "ignored", "call_id": ""}

        end_reason = "caller_hangup" if call_status == "completed" else "provider_failure"
        try:
            await calls.finalize(
                call_id,
                CallFinalization(ended_at=datetime.now(UTC), end_reason=end_reason),
            )
        except InternalApiError as exc:
            raise HTTPException(
                status_code=503, detail="internal call finalization unavailable"
            ) from exc

        session = session_manager.get(call_id)
        if session is not None:
            session_manager.end(call_id)
            session_manager.remove(call_id)
        # Delete only after successful finalization — if finalize() raised
        # above, the mapping is preserved so the end event can be retried
        # (same ordering exotel_routes.py uses for the same reason).
        _store.delete(provider_call_id)
        return {"status": "session_cleaned", "call_id": call_id}

    return router
