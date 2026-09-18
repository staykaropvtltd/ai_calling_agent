"""Twilio webhook signature validation.

Phase 9 requires the official Twilio mechanism, not custom HMAC logic — this
wraps twilio.request_validator.RequestValidator so twilio_routes.py doesn't
need to import the SDK directly for this one call, matching the separation
exotel_routes.py already has between webhook auth (hmac.compare_digest on
EXOTEL_WEBHOOK_TOKEN, inline in that module) and everything else.
"""

from __future__ import annotations

from twilio.request_validator import RequestValidator


def validate_twilio_request(
    *, auth_token: str, url: str, params: dict[str, str], signature: str
) -> bool:
    """Returns True iff `signature` (the request's X-Twilio-Signature header)
    is valid for `url` + `params` under `auth_token`.

    `url` must be the exact, fully-qualified URL Twilio was configured to
    call (TWILIO_TWIML_URL / TWILIO_STATUS_CALLBACK_URL) — RequestValidator
    recomputes the expected signature from this value, not from the
    request's own Host/URL. Reconstructing it from request headers instead
    would be wrong behind ngrok or any reverse proxy (the Host the gateway
    sees is not necessarily the public host Twilio signed against), which is
    exactly why this repo requires those two URLs as explicit configuration
    rather than deriving them at request time.

    An empty auth_token or empty signature is always invalid — never treated
    as "skip validation". There is no dev bypass here: local testing already
    goes through a real ngrok tunnel with a real Twilio account hitting real
    URLs with real signatures, so there is no legitimate case where this
    should be skipped.
    """
    if not auth_token or not signature:
        return False
    validator = RequestValidator(auth_token)
    return validator.validate(url, params, signature)
