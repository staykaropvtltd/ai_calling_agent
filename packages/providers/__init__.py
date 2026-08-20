"""Provider integrations isolated from application services."""

from .telephony import (
    ExotelSettings,
    ProviderError,
    TelephonyCallRequest,
    TelephonyCallResult,
    TelephonyProvider,
    TwilioSettings,
)
from .twilio import TwilioProvider
from .stt import (
    DeepgramSettings,
    SttError,
    SttProvider,
    SttSession,
    TranscriptEvent,
)
from .deepgram import DeepgramSttProvider, DeepgramSttSession

__all__ = [
    # Telephony (SH-01 / SH-02)
    "ExotelSettings",
    "ProviderError",
    "TelephonyCallRequest",
    "TelephonyCallResult",
    "TelephonyProvider",
    "TwilioProvider",
    "TwilioSettings",
    # STT (SH-04)
    "DeepgramSettings",
    "DeepgramSttProvider",
    "DeepgramSttSession",
    "SttError",
    "SttProvider",
    "SttSession",
    "TranscriptEvent",
]
