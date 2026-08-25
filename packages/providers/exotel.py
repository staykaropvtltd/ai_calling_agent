"""Async Exotel implementation of the narrow telephony provider contract."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .telephony import ExotelSettings, ProviderError, TelephonyCallRequest, TelephonyCallResult

logger = logging.getLogger(__name__)


class ExotelProvider:
    def __init__(self, settings: ExotelSettings, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._client = client

    @property
    def endpoint(self) -> str:
        return (
            f"https://{self._settings.subdomain}"
            f"/v1/Accounts/{self._settings.sid}/Calls/connect.json"
        )

    async def start_call(self, request: TelephonyCallRequest) -> TelephonyCallResult:
        payload = {
            "From": request.from_number,
            "To": request.to_number,
            "CallerId": self._settings.caller_id,
            "Url": request.voice_callback_url,
        }
        try:
            if self._client is None:
                async with httpx.AsyncClient(timeout=self._settings.timeout_seconds) as client:
                    response = await client.post(
                        self.endpoint,
                        data=payload,
                        auth=(self._settings.api_key, self._settings.api_secret),
                    )
            else:
                response = await self._client.post(
                    self.endpoint,
                    data=payload,
                    auth=(self._settings.api_key, self._settings.api_secret),
                    timeout=self._settings.timeout_seconds,
                )
            response.raise_for_status()
            body: dict[str, Any] = response.json()
        except httpx.TimeoutException as exc:
            raise ProviderError("Exotel request timed out") from exc
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "Exotel rejected call request",
                extra={"status_code": exc.response.status_code},
            )
            raise ProviderError("Exotel rejected call request") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError("Exotel request failed") from exc

        call = body.get("Call") or body.get("call") or {}
        provider_call_id = call.get("Sid") or call.get("sid")
        if not provider_call_id:
            raise ProviderError("Exotel response did not include a call identifier")
        return TelephonyCallResult(
            provider_call_id=str(provider_call_id),
            status=str(call.get("Status", "queued")),
        )
