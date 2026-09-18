"""Sync-under-the-hood Twilio implementation of the narrow telephony
provider contract (packages/providers/telephony.py).

Uses the official `twilio` SDK's synchronous REST client (twilio.rest.Client),
not its create_async()/AsyncTwilioHttpClient path. That async path has a
known, documented hang specifically under FastAPI's event loop
(twilio/twilio-python#731, unresolved) and is deliberately not used here.
The synchronous client is instead run off the event loop via
asyncio.to_thread() — the same "blocking work belongs in an executor"
pattern this repository already applies to pyttsx3 (tts_provider.py) and
faster-whisper (stt_provider.py), for the same reason: don't stall the
single asyncio event loop every concurrent call on this gateway shares.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Protocol

from twilio.base.exceptions import TwilioException, TwilioRestException
from twilio.rest import Client as TwilioClient

from .telephony import ProviderError, TelephonyCallRequest, TelephonyCallResult, TwilioSettings

logger = logging.getLogger(__name__)


class _CallsResource(Protocol):
    """The one twilio.rest.Client surface this module actually calls —
    narrowed to a Protocol so tests can inject a fake client (matching
    ExotelProvider's `client: httpx.AsyncClient | None` injection point)
    without needing real Twilio credentials or network access."""

    def create(self, **kwargs: Any) -> Any: ...


class _TwilioClientLike(Protocol):
    calls: _CallsResource


class TwilioProvider:
    """Outbound-call provider backed by the Twilio REST API.

    Mirrors ExotelProvider's shape: one start_call() entry point
    implementing the TelephonyProvider protocol, translating this repo's
    provider-neutral TelephonyCallRequest/TelephonyCallResult into Twilio's
    request/response shape. request.voice_callback_url becomes the `url=`
    Twilio calls back for TwiML instructions once the callee answers — the
    same role Exotel's `Url` payload field plays in exotel.py, and the same
    URL services/voice-gateway/twilio_routes.py's /telephony/twilio/twiml
    endpoint serves.

    Pass client= to inject a fake/mock for tests (ExotelProvider's
    `client: httpx.AsyncClient | None` convention). When omitted, a real
    twilio.rest.Client is constructed — this makes no network call by
    itself, so it's safe to do eagerly in __init__.
    """

    def __init__(self, settings: TwilioSettings, client: _TwilioClientLike | None = None) -> None:
        self._settings = settings
        self._client: _TwilioClientLike = client or TwilioClient(
            settings.account_sid, settings.auth_token
        )

    async def start_call(self, request: TelephonyCallRequest) -> TelephonyCallResult:
        try:
            call = await asyncio.to_thread(
                self._client.calls.create,
                to=request.to_number,
                from_=self._settings.from_number,
                url=request.voice_callback_url,
            )
        except TwilioRestException as exc:
            # TwilioRestException carries structured, safe fields (status,
            # Twilio's own numeric error code) — logged instead of str(exc),
            # which can embed the request URI/params. Never carries or logs
            # auth_token; the SDK does not echo credentials back on error.
            logger.warning(
                "Twilio rejected call request",
                extra={"status_code": exc.status, "twilio_code": exc.code},
            )
            raise ProviderError("Twilio rejected call request") from exc
        except TwilioException as exc:
            # Base class for SDK-level failures (auth/transport/timeout) not
            # already a TwilioRestException. Deliberately not including
            # str(exc) in the raised message — see ProviderError docstring:
            # callers only ever see this safe, typed failure.
            raise ProviderError("Twilio request failed") from exc

        provider_call_id = getattr(call, "sid", None)
        if not provider_call_id:
            raise ProviderError("Twilio response did not include a call identifier")
        return TelephonyCallResult(
            provider_call_id=str(provider_call_id),
            status=str(getattr(call, "status", None) or "queued"),
        )
