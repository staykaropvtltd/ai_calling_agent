"""Small provider-neutral contract required by the voice gateway."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, Field


class ProviderError(RuntimeError):
    """A safe, typed failure returned by a telephony provider."""


class TelephonyCallRequest(BaseModel):
    call_id: str = Field(min_length=1)
    to_number: str = Field(min_length=1)
    from_number: str = Field(min_length=1)
    voice_callback_url: str = Field(min_length=1)


class TelephonyCallResult(BaseModel):
    provider_call_id: str = Field(min_length=1)
    status: str


class TelephonyProvider(Protocol):
    async def start_call(self, request: TelephonyCallRequest) -> TelephonyCallResult: ...


@dataclass(frozen=True)
class ExotelSettings:
    api_key: str
    api_secret: str
    sid: str
    subdomain: str
    caller_id: str
    webhook_token: str
    timeout_seconds: float = 10.0

    @classmethod
    def from_environment(cls) -> "ExotelSettings":
        names = {
            "api_key": "EXOTEL_API_KEY", "api_secret": "EXOTEL_API_SECRET",
            "sid": "EXOTEL_SID", "subdomain": "EXOTEL_SUBDOMAIN",
            "caller_id": "EXOTEL_CALLER_ID", "webhook_token": "EXOTEL_WEBHOOK_TOKEN",
        }
        values = {field: os.getenv(name, "").strip() for field, name in names.items()}
        missing = [name for field, name in names.items() if not values[field]]
        if missing:
            raise ProviderError("Missing required Exotel configuration: " + ", ".join(missing))
        return cls(**values, timeout_seconds=float(os.getenv("EXOTEL_TIMEOUT_SECONDS", "10")))
