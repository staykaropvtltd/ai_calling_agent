"""Async Twilio implementation of the narrow telephony provider contract."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .telephony import ProviderError, TelephonyCallRequest, TelephonyCallResult, TwilioSettings

logger = logging.getLogger(__name__)

_TWILIO_API_BASE = "https://api.twilio.com/2010-04-01"


class TwilioProvider:
    """Implements TelephonyProvider against the Twilio REST Calls API."""

    def __init__(self, settings: TwilioSettings, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._client = client

    @property
    def endpoint(self) -> str:
        return f"{_TWILIO_API_BASE}/Accounts/{self._settings.account_sid}/Calls.json"

    async def start_call(self, request: TelephonyCallRequest) -> TelephonyCallResult:
        payload = {
            "To": request.to_number,
            "From": request.from_number,
            "Url": request.voice_callback_url,
            "StatusCallback": request.voice_callback_url,
            "StatusCallbackMethod": "POST",
        }
        auth = (self._settings.account_sid, self._settings.auth_token)
        try:
            if self._client is None:
                async with httpx.AsyncClient(timeout=self._settings.timeout_seconds) as client:
                    response = await client.post(self.endpoint, data=payload, auth=auth)
            else:
                response = await self._client.post(self.endpoint, data=payload, auth=auth)
            response.raise_for_status()
            body: dict[str, Any] = response.json()
        except httpx.TimeoutException as exc:
            raise ProviderError("Twilio request timed out") from exc
        except httpx.HTTPStatusError as exc:
            logger.warning("Twilio rejected call request", extra={"status_code": exc.response.status_code})
            raise ProviderError("Twilio rejected call request") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError("Twilio request failed") from exc

        provider_call_id = body.get("sid") or body.get("Sid")
        if not provider_call_id:
            raise ProviderError("Twilio response did not include a call identifier")
        return TelephonyCallResult(
            provider_call_id=str(provider_call_id),
            status=str(body.get("status", "queued")),
        )
