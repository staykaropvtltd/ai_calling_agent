"""Twilio HTTP webhook boundary; no Twilio details leak into the Pipecat pipeline."""

from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, Request, status

from internal_calls import CallCreation, CallFinalization, InternalApiError, InternalCalls
from packages.providers.telephony import TwilioSettings


class PhoneRouting(Protocol):
    async def resolve(self, dialed_number: str) -> tuple[str, str]: ...


# Twilio CallStatus values that signal an answered/live call.
_START_STATUSES = {"in-progress"}

# Twilio CallStatus values that signal call completion (any terminal state).
_FINAL_STATUSES = {"completed", "failed", "busy", "no-answer", "canceled"}


def _compute_twilio_signature(auth_token: str, url: str, params: dict[str, str]) -> str:
    """Compute Twilio's canonical HMAC-SHA1 webhook signature.

    Algorithm per https://www.twilio.com/docs/usage/webhooks/webhooks-security:
      1. Start with the full request URL.
      2. For each POST parameter, sort by key (byte order) and append key+value
         with no separator.
      3. HMAC-SHA1 sign with the Twilio auth token as the key.
      4. Base64-encode the raw digest.

    Secrets are never logged here.
    """
    signed = url
    for key in sorted(params.keys()):
        signed += key + (params[key] or "")
    mac = hmac.new(
        auth_token.encode("utf-8"),
        signed.encode("utf-8"),
        hashlib.sha1,
    )
    return base64.b64encode(mac.digest()).decode("ascii")


def build_twilio_router(
    session_manager: object,
    settings: TwilioSettings,
    calls: InternalCalls,
    routing: PhoneRouting | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/telephony/twilio", tags=["Twilio"])
    handled_events: set[tuple[str, str]] = set()
    provider_calls: dict[str, str] = {}

    @router.post("/callback")
    async def callback(
        request: Request,
        x_twilio_signature: str | None = Header(default=None),
    ) -> dict[str, str]:
        # Parse form data first: needed both for signature verification and processing.
        # Twilio sends webhook POST bodies as application/x-www-form-urlencoded.
        form = await request.form()
        form_params: dict[str, str] = {k: str(v) for k, v in form.items()}

        # --- Twilio Signature Validation ---
        # Reject missing header immediately; do not log header value or auth_token.
        if not x_twilio_signature:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="missing Twilio webhook signature",
            )
        expected = _compute_twilio_signature(
            settings.auth_token, str(request.url), form_params
        )
        if not hmac.compare_digest(expected, x_twilio_signature):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid Twilio webhook signature",
            )

        # Extract fields after auth passes. Do NOT trust tenant_id / agent_id
        # from the payload — routing always resolves identities from the phone number.
        provider_call_id = form_params.get("CallSid", "").strip()
        call_status = form_params.get("CallStatus", "").strip().lower()
        # "Called" is the dialed number on outbound; "To" covers inbound.
        dialed_number = (form_params.get("Called") or form_params.get("To") or "").strip()

        if not provider_call_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Twilio callback is missing CallSid",
            )

        key = (provider_call_id, call_status)
        if key in handled_events:
            return {"status": "duplicate", "call_id": provider_calls.get(provider_call_id, "")}
        handled_events.add(key)

        if call_status in _START_STATUSES:
            if routing is None:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="phone-number routing API dependency is unavailable",
                )
            if not dialed_number:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Twilio callback is missing dialed number",
                )
            try:
                tenant_id, agent_id = await routing.resolve(dialed_number)
            except InternalApiError as exc:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="phone-number route not found",
                ) from exc
            call_id = str(uuid4())
            try:
                await calls.create(
                    CallCreation(
                        call_id=call_id,
                        tenant_id=tenant_id,
                        agent_id=agent_id,
                        started_at=datetime.now(timezone.utc),
                    )
                )
            except InternalApiError as exc:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="internal call creation unavailable",
                ) from exc
            session_manager.create(call_id, tenant_id, agent_id)
            provider_calls[provider_call_id] = call_id
            return {"status": "session_started", "call_id": call_id}

        if call_status in _FINAL_STATUSES:
            call_id = provider_calls.get(provider_call_id)
            if not call_id:
                return {"status": "ignored", "call_id": ""}
            end_reason = "provider_failure" if call_status == "failed" else "caller_hangup"
            try:
                await calls.finalize(
                    call_id,
                    CallFinalization(ended_at=datetime.now(timezone.utc), end_reason=end_reason),
                )
            except InternalApiError as exc:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="internal call finalization unavailable",
                ) from exc
            session = session_manager.get(call_id)
            if session is not None:
                session_manager.end(call_id)
                session_manager.remove(call_id)
            return {"status": "session_cleaned", "call_id": call_id}

        return {"status": "ignored", "call_id": ""}

    return router
