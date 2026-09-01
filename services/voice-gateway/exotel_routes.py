"""Exotel HTTP boundary; no Exotel details leak into the Pipecat pipeline."""

from __future__ import annotations

import hmac
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Protocol
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, Request, status
from internal_calls import (
    CallCreation,
    CallFinalization,
    InternalApiError,
    InternalCalls,
)
from pydantic import BaseModel, Field, ValidationError, model_validator

if TYPE_CHECKING:
    from packages.providers.telephony import ExotelSettings


class PhoneRouting(Protocol):
    async def resolve(self, dialed_number: str) -> tuple[str, str]: ...


class CallStore(Protocol):
    """Persistent mapping from Exotel provider_call_id to internal call_id.

    Implementations must survive gateway restarts so that end events (completed /
    failed / disconnected) arriving after a process restart can still be matched
    to their internal call record and finalized correctly.
    """

    def set(self, provider_call_id: str, call_id: str) -> None: ...
    def get(self, provider_call_id: str) -> str | None: ...
    def delete(self, provider_call_id: str) -> None: ...


class _DictCallStore:
    """In-memory fallback CallStore used when no external store is provided.

    Not restart-safe: the mapping is lost when the process exits.  Used as the
    default so that existing code and tests that don't supply a call_store
    continue to work without modification.
    """

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def set(self, provider_call_id: str, call_id: str) -> None:
        self._store[provider_call_id] = call_id

    def get(self, provider_call_id: str) -> str | None:
        return self._store.get(provider_call_id)

    def delete(self, provider_call_id: str) -> None:
        self._store.pop(provider_call_id, None)


class EventRecorder(Protocol):
    """Phase 6 — durable idempotency for one webhook event.

    Replaces the in-memory (provider_call_id, event_type) set this router
    used to keep as its only dedup guard: that set is lost on every gateway
    restart, so a webhook retried after a restart (which Exotel, like most
    telephony providers, will do on a failure/timeout) could be processed a
    second time. record() must return True for a genuine duplicate — the
    caller must not repeat any side effect (call creation/finalization,
    session mutation) when it does.
    """

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
    """Non-durable fallback used only when no real EventRecorder is wired in
    (existing tests/direct router construction, or a dev run without
    services/api reachable). NOT authoritative — this dedup state is lost on
    restart, exactly the gap a real (HTTP-backed) EventRecorder exists to
    close. Kept only so existing callers of build_exotel_router() that don't
    pass events= continue to work unmodified.
    """

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


class ExotelCallback(BaseModel):
    provider_call_id: str = Field(min_length=1)
    event: str = Field(min_length=1)
    dialed_number: str | None = None
    # Exotel's documented StatusCallback carries the actual outcome here
    # (completed/failed/busy/no-answer) separately from EventType, which is
    # only ever "terminal" or "answered" — see translate_exotel_fields.
    call_status: str | None = None

    @model_validator(mode="before")
    @classmethod
    def translate_exotel_fields(cls, value: object) -> object:
        if isinstance(value, dict):
            return {
                "provider_call_id": value.get("CallSid"),
                "event": value.get("EventType"),
                # Exotel's documented field for the dialed/called number is
                # `To` (StatusCallback) / lowercase `to` (V3 JSON). `Called`
                # was this project's original, never-sandbox-verified guess —
                # accepted too rather than dropped, since it's unconfirmed
                # which the real configured callback actually sends.
                "dialed_number": value.get("To") or value.get("to") or value.get("Called"),
                "call_status": value.get("Status") or value.get("status"),
            }
        return value


def build_exotel_router(
    session_manager: object,
    settings: ExotelSettings,
    calls: InternalCalls,
    routing: PhoneRouting | None = None,
    call_store: CallStore | None = None,
    events: EventRecorder | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/telephony/exotel", tags=["Exotel"])
    _store: CallStore = call_store if call_store is not None else _DictCallStore()
    _events: EventRecorder = events if events is not None else _InMemoryEventRecorder()

    @router.api_route("/callback", methods=["GET", "POST"])
    async def callback(
        request: Request,
        x_exotel_webhook_token: Annotated[str | None, Header()] = None,
    ) -> dict[str, str]:
        # Exotel's Passthru applet (the documented mechanism for this
        # integration style) delivers a GET with the payload as a query
        # string, not a POST body — and documents no custom-header auth
        # mechanism at all, meaning a header-only check would reject every
        # real callback outright. Accept the token via the header (kept for
        # StatusCallback-style POST delivery, and in case a header can be
        # configured) OR a `token` query param (the realistic option for a
        # Passthru URL, since Exotel can't attach custom headers there).
        token = x_exotel_webhook_token or request.query_params.get("token")
        if not token or not hmac.compare_digest(token, settings.webhook_token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid Exotel callback authentication",
            )

        # Query params first (covers GET+query-string delivery outright, and
        # a URL-embedded token for POST too), then merge in a body if present
        # — never overriding a query param with an empty/absent body field.
        raw: dict = dict(request.query_params)
        raw.pop("token", None)
        try:
            if request.method == "POST":
                content_type = request.headers.get("content-type", "")
                if "application/x-www-form-urlencoded" in content_type:
                    form = await request.form()
                    raw.update({k: v for k, v in dict(form).items() if v not in (None, "")})
                elif content_type.startswith("application/json"):
                    body = await request.json()
                    if isinstance(body, dict):
                        raw.update({k: v for k, v in body.items() if v not in (None, "")})
            payload = ExotelCallback.model_validate(raw)
        except (ValueError, ValidationError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid request body",
            ) from exc

        # Phase 6: the durable event record is now the *authoritative*
        # idempotency guarantee (not the in-memory set this used to be —
        # that state didn't survive a gateway restart, so a webhook retried
        # after one could be processed twice). A real EventRecorder backs
        # this with a database-level unique constraint; failing to reach it
        # must not silently fall through to reprocessing, so this fails
        # closed with 503 (same pattern as the calls.create/finalize
        # failures below) rather than risk a duplicate side effect.
        try:
            is_duplicate = await _events.record(
                provider_call_id=payload.provider_call_id,
                event_type=payload.event.lower(),
                payload={
                    "dialed_number": payload.dialed_number,
                    "call_status": payload.call_status,
                },
            )
        except InternalApiError as exc:
            raise HTTPException(
                status_code=503, detail="durable event recording unavailable"
            ) from exc
        if is_duplicate:
            return {
                "status": "duplicate",
                "call_id": _store.get(payload.provider_call_id) or "",
            }

        if payload.event.lower() in {"connected", "start", "answered", "started"}:
            if routing is None:
                raise HTTPException(
                    status_code=503,
                    detail="phone-number routing API dependency is unavailable",
                )
            if not payload.dialed_number:
                raise HTTPException(
                    status_code=422,
                    detail="Exotel callback is missing dialed number",
                )
            try:
                tenant_id, agent_id = await routing.resolve(payload.dialed_number)
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
                        provider_call_id=payload.provider_call_id,
                    )
                )
            except InternalApiError as exc:
                raise HTTPException(
                    status_code=503, detail="internal call creation unavailable"
                ) from exc

            session_manager.create(call_id, tenant_id, agent_id)
            _store.set(payload.provider_call_id, call_id)
            return {"status": "session_started", "call_id": call_id}

        # "terminal" is Exotel's actual documented EventType for call end (the
        # original "completed"/"failed"/"disconnected" values are kept too —
        # unconfirmed which this project's real configured callback sends).
        # When it's "terminal", the outcome (success vs failure) is carried
        # separately in Status/call_status, not in EventType itself.
        if payload.event.lower() in {"completed", "failed", "disconnected", "terminal"}:
            call_id = _store.get(payload.provider_call_id)
            if not call_id:
                return {"status": "ignored", "call_id": ""}
            call_status = (payload.call_status or "").lower()
            is_failure = payload.event.lower() == "failed" or call_status in {
                "failed",
                "busy",
                "no-answer",
            }
            end_reason = "provider_failure" if is_failure else "caller_hangup"
            try:
                await calls.finalize(
                    call_id,
                    CallFinalization(
                        ended_at=datetime.now(UTC),
                        end_reason=end_reason,
                    ),
                )
            except InternalApiError as exc:
                raise HTTPException(
                    status_code=503, detail="internal call finalization unavailable"
                ) from exc

            session = session_manager.get(call_id)
            if session is not None:
                session_manager.end(call_id)
                session_manager.remove(call_id)
            # Delete only after successful finalization — if finalize() raised above,
            # the mapping is preserved so the end event can be retried.
            _store.delete(payload.provider_call_id)
            return {"status": "session_cleaned", "call_id": call_id}

        return {"status": "ignored", "call_id": ""}

    # ── Outbound call status callbacks ─────────────────────────────────────────
    # Exotel posts events to this URL (configured as StatusCallback when the
    # integration-service places the outbound dial).  Outbound calls differ
    # from inbound in one key way: the Call record already exists before the
    # first webhook arrives (created by the integration-service), so we look
    # it up by provider_call_id rather than creating a new one.

    @router.api_route("/outbound-callback", methods=["GET", "POST"])
    async def outbound_callback(
        request: Request,
        x_exotel_webhook_token: Annotated[str | None, Header()] = None,
    ) -> dict[str, str]:
        token = x_exotel_webhook_token or request.query_params.get("token")
        if not token or not hmac.compare_digest(token, settings.webhook_token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid Exotel outbound callback authentication",
            )

        raw: dict = dict(request.query_params)
        raw.pop("token", None)
        try:
            if request.method == "POST":
                content_type = request.headers.get("content-type", "")
                if "application/x-www-form-urlencoded" in content_type:
                    form = await request.form()
                    raw.update({k: v for k, v in dict(form).items() if v not in (None, "")})
                elif content_type.startswith("application/json"):
                    body = await request.json()
                    if isinstance(body, dict):
                        raw.update({k: v for k, v in body.items() if v not in (None, "")})
            payload = ExotelCallback.model_validate(raw)
        except (ValueError, ValidationError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid outbound callback body",
            ) from exc

        # Dedup via durable EventRecorder (same guarantee as inbound callback).
        try:
            is_duplicate = await _events.record(
                provider_call_id=payload.provider_call_id,
                event_type="outbound_" + payload.event.lower(),
                payload={
                    "dialed_number": payload.dialed_number,
                    "call_status": payload.call_status,
                },
            )
        except InternalApiError as exc:
            raise HTTPException(
                status_code=503, detail="durable event recording unavailable"
            ) from exc
        if is_duplicate:
            return {"status": "duplicate", "provider_call_id": payload.provider_call_id}

        # Resolve the pre-existing Call record via the provider call ID.
        try:
            call_state = await calls.get_by_provider_id(payload.provider_call_id)
        except InternalApiError as exc:
            raise HTTPException(
                status_code=503, detail="internal calls API unavailable"
            ) from exc

        if call_state is None:
            # Not a call we placed — could be a delayed retry of an inbound
            # webhook that was mis-routed here. Ignore safely.
            return {"status": "ignored", "detail": "unknown outbound provider_call_id"}

        event_lower = payload.event.lower()

        # "connected"/"answered" — remote party picked up; no Pipecat session
        # is started for outbound campaigns (AI voice is a separate pipeline
        # concern).  We simply acknowledge the event so Exotel doesn't retry.
        if event_lower in {"connected", "start", "answered", "started"}:
            return {"status": "acknowledged", "call_id": call_state.call_id}

        # Terminal events — finalize the Call record.  _finalize_outbound_caller
        # (inside services/api's finalize endpoint) cascades the status update
        # to the linked Caller, CampaignContact, and Campaign counters.
        if event_lower in {"completed", "failed", "disconnected", "terminal"}:
            call_status = (payload.call_status or "").lower()
            is_failure = event_lower == "failed" or call_status in {
                "failed", "busy", "no-answer"
            }
            end_reason = "provider_failure" if is_failure else "caller_hangup"
            if call_status == "no-answer":
                end_reason = "no_answer"

            try:
                await calls.finalize(
                    call_state.call_id,
                    CallFinalization(
                        ended_at=datetime.now(UTC),
                        end_reason=end_reason,
                    ),
                )
            except InternalApiError as exc:
                raise HTTPException(
                    status_code=503, detail="internal call finalization unavailable"
                ) from exc

            return {"status": "finalized", "call_id": call_state.call_id}

        return {"status": "ignored", "call_id": call_state.call_id}

    return router
