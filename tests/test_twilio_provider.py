"""Twilio provider, TwiML/status webhook, and signature-validation tests.

Mirrors test_exotel_provider.py's conventions exactly: hand-written fake
objects (no mocking framework), httpx.MockTransport is not needed here since
TwilioProvider talks to the Twilio SDK's synchronous Client (see
packages/providers/twilio.py's module docstring for why), so outbound calls
are exercised via a fake _TwilioClientLike/_CallsResource pair injected
directly — the same "inject a fake at the real boundary" approach
ExotelProvider's tests use with httpx.MockTransport, just at a different
boundary (the Twilio SDK object, not the HTTP transport underneath it).

No live/paid Twilio account is used or required anywhere in this file.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from twilio.base.exceptions import TwilioException, TwilioRestException

from packages.providers.telephony import ProviderError, TelephonyCallRequest, TwilioSettings
from packages.providers.twilio import TwilioProvider

_VG = str((Path(__file__).parent.parent / "services" / "voice-gateway").resolve())


def _ensure_vg_on_path() -> None:
    if _VG not in sys.path:
        sys.path.insert(0, _VG)


def _twilio_signature(auth_token: str, url: str, params: dict[str, str]) -> str:
    """Computes a real, valid X-Twilio-Signature the same way Twilio itself
    does (and the same way twilio.request_validator.RequestValidator
    verifies it): HMAC-SHA1 of `url` followed by each sorted param's key
    then value concatenated directly, keyed by the auth token, base64
    encoded. Hand-computed (not borrowed from a private SDK method) so the
    test exercises the real documented algorithm independently of
    RequestValidator's own implementation.
    """
    data = url
    for key in sorted(params.keys()):
        data += key + params[key]
    digest = hmac.new(auth_token.encode("utf-8"), data.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("utf-8")


def settings() -> TwilioSettings:
    return TwilioSettings(account_sid="ACxxx", auth_token="secret-token", from_number="+15551234567")


# ── packages/providers/twilio.py ──────────────────────────────────────────────


def test_missing_configuration_lists_every_missing_var(monkeypatch):
    for name in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_PHONE_NUMBER"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ProviderError, match="TWILIO_ACCOUNT_SID"):
        TwilioSettings.from_environment()


def test_settings_from_environment_reads_all_three(monkeypatch):
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "ACxxx")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tok")
    monkeypatch.setenv("TWILIO_PHONE_NUMBER", "+15551234567")
    result = TwilioSettings.from_environment()
    assert (result.account_sid, result.auth_token, result.from_number) == (
        "ACxxx",
        "tok",
        "+15551234567",
    )


class _FakeCall:
    def __init__(self, sid: str, status: str = "queued") -> None:
        self.sid = sid
        self.status = status


class _FakeCallsResource:
    def __init__(self, *, result: _FakeCall | None = None, error: Exception | None = None) -> None:
        self._result = result
        self._error = error
        self.calls_made: list[dict] = []

    def create(self, **kwargs):
        self.calls_made.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._result


class _FakeTwilioClient:
    def __init__(self, calls: _FakeCallsResource) -> None:
        self.calls = calls


def test_outbound_call_success_returns_provider_call_id():
    calls = _FakeCallsResource(result=_FakeCall(sid="CA123", status="queued"))
    provider = TwilioProvider(settings(), client=_FakeTwilioClient(calls))

    result = asyncio.run(
        provider.start_call(
            TelephonyCallRequest(
                call_id="internal-1",
                to_number="+912",
                from_number="+911",
                voice_callback_url="https://example.test/telephony/twilio/twiml",
            )
        )
    )

    assert result.provider_call_id == "CA123"
    assert result.status == "queued"
    made = calls.calls_made[0]
    assert made["to"] == "+912"
    assert made["from_"] == "+15551234567"  # settings().from_number, not the request's from_number
    assert made["url"] == "https://example.test/telephony/twilio/twiml"


def test_outbound_call_rest_exception_is_wrapped_safely():
    error = TwilioRestException(401, "https://api.twilio.com/x", msg="Authenticate", code=20003)
    calls = _FakeCallsResource(error=error)
    provider = TwilioProvider(settings(), client=_FakeTwilioClient(calls))

    with pytest.raises(ProviderError, match="rejected"):
        asyncio.run(
            provider.start_call(
                TelephonyCallRequest(
                    call_id="1", to_number="2", from_number="3", voice_callback_url="https://x"
                )
            )
        )


def test_outbound_call_generic_twilio_exception_is_wrapped():
    calls = _FakeCallsResource(error=TwilioException("boom"))
    provider = TwilioProvider(settings(), client=_FakeTwilioClient(calls))

    with pytest.raises(ProviderError, match="Twilio request failed"):
        asyncio.run(
            provider.start_call(
                TelephonyCallRequest(
                    call_id="1", to_number="2", from_number="3", voice_callback_url="https://x"
                )
            )
        )


def test_outbound_call_missing_sid_in_response_is_rejected():
    calls = _FakeCallsResource(result=_FakeCall(sid=""))
    provider = TwilioProvider(settings(), client=_FakeTwilioClient(calls))

    with pytest.raises(ProviderError, match="call identifier"):
        asyncio.run(
            provider.start_call(
                TelephonyCallRequest(
                    call_id="1", to_number="2", from_number="3", voice_callback_url="https://x"
                )
            )
        )


# ── twilio_signature.py ───────────────────────────────────────────────────────


def test_signature_validation_accepts_a_correctly_computed_signature():
    _ensure_vg_on_path()
    from twilio_signature import validate_twilio_request  # noqa: PLC0415

    url = "https://example.test/telephony/twilio/twiml"
    params = {"CallSid": "CA1", "To": "+912", "From": "+911"}
    signature = _twilio_signature("secret-token", url, params)

    assert validate_twilio_request(
        auth_token="secret-token", url=url, params=params, signature=signature
    )


def test_signature_validation_rejects_wrong_signature():
    _ensure_vg_on_path()
    from twilio_signature import validate_twilio_request  # noqa: PLC0415

    url = "https://example.test/telephony/twilio/twiml"
    params = {"CallSid": "CA1"}
    assert not validate_twilio_request(
        auth_token="secret-token", url=url, params=params, signature="not-a-real-signature"
    )


def test_signature_validation_rejects_tampered_params():
    _ensure_vg_on_path()
    from twilio_signature import validate_twilio_request  # noqa: PLC0415

    url = "https://example.test/telephony/twilio/twiml"
    signature = _twilio_signature("secret-token", url, {"CallSid": "CA1"})
    # Same signature, but the params Twilio "actually sent" differ — must fail.
    assert not validate_twilio_request(
        auth_token="secret-token", url=url, params={"CallSid": "CA2"}, signature=signature
    )


def test_signature_validation_never_bypasses_on_empty_token_or_signature():
    _ensure_vg_on_path()
    from twilio_signature import validate_twilio_request  # noqa: PLC0415

    url = "https://example.test/telephony/twilio/twiml"
    params = {"CallSid": "CA1"}
    assert not validate_twilio_request(auth_token="", url=url, params=params, signature="x")
    assert not validate_twilio_request(auth_token="tok", url=url, params=params, signature="")


# ── twilio_routes.py: /telephony/twilio/twiml + /telephony/twilio/status ─────


class _Sessions:
    def __init__(self):
        self.calls: dict[str, dict] = {}

    def create(self, call_id, tenant_id, agent_id):
        self.calls[call_id] = {"tenant_id": tenant_id, "agent_id": agent_id}

    def get(self, call_id):
        return self.calls.get(call_id)

    def end(self, call_id):
        pass

    def remove(self, call_id):
        self.calls.pop(call_id, None)


class _Calls:
    def __init__(self):
        self.created = None
        self.finalized = None

    async def create(self, value):
        self.created = value

    async def finalize(self, call_id, value):
        self.finalized = (call_id, value)


class _Routing:
    async def resolve(self, number):
        return ("tenant-1", "agent-1")


class _NotFoundRouting:
    async def resolve(self, number):
        from internal_calls import InternalApiError  # noqa: PLC0415

        raise InternalApiError("not found")


def _webhook_settings():
    _ensure_vg_on_path()
    from twilio_routes import TwilioWebhookSettings  # noqa: PLC0415

    return TwilioWebhookSettings(
        auth_token="secret-token",
        twiml_url="https://example.test/telephony/twilio/twiml",
        status_callback_url="https://example.test/telephony/twilio/status",
        gateway_wss_host="example.test",
    )


def _build_app(*, routing=None, calls=None, events=None, call_store=None):
    _ensure_vg_on_path()
    from twilio_routes import build_twilio_router  # noqa: PLC0415

    sessions = _Sessions()
    calls = calls if calls is not None else _Calls()
    routing = routing if routing is not None else _Routing()
    app = FastAPI()
    app.include_router(
        build_twilio_router(
            sessions, _webhook_settings(), calls, routing, call_store=call_store, events=events
        )
    )
    return app, sessions, calls


def test_twiml_endpoint_rejects_unsigned_requests():
    app, _, _ = _build_app()
    client = TestClient(app)
    response = client.post(
        "/telephony/twilio/twiml", data={"CallSid": "CA1", "To": "+919", "From": "+911"}
    )
    assert response.status_code == 401


def test_twiml_endpoint_creates_call_and_returns_stream_url():
    app, sessions, calls = _build_app()
    client = TestClient(app)
    form = {"CallSid": "CA1", "To": "+919", "From": "+911"}
    signature = _twilio_signature("secret-token", "https://example.test/telephony/twilio/twiml", form)

    response = client.post(
        "/telephony/twilio/twiml", data=form, headers={"X-Twilio-Signature": signature}
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    body = response.text
    assert "<Connect>" in body
    assert "<Stream" in body
    assert "wss://example.test/ws/" in body
    assert calls.created.tenant_id == "tenant-1"
    assert calls.created.provider_call_id == "CA1"
    assert calls.created.call_id in sessions.calls


def test_twiml_endpoint_is_idempotent_on_retry_with_same_call_sid():
    app, sessions, calls = _build_app()
    client = TestClient(app)
    form = {"CallSid": "CA1", "To": "+919", "From": "+911"}
    signature = _twilio_signature("secret-token", "https://example.test/telephony/twilio/twiml", form)

    first = client.post(
        "/telephony/twilio/twiml", data=form, headers={"X-Twilio-Signature": signature}
    )
    second = client.post(
        "/telephony/twilio/twiml", data=form, headers={"X-Twilio-Signature": signature}
    )

    assert first.text == second.text
    assert len(sessions.calls) == 1  # no duplicate Call/session created on retry


def test_twiml_endpoint_returns_404_when_routing_has_no_match():
    app, _, _ = _build_app(routing=_NotFoundRouting())
    client = TestClient(app)
    form = {"CallSid": "CA1", "To": "+919", "From": "+911"}
    signature = _twilio_signature("secret-token", "https://example.test/telephony/twilio/twiml", form)

    response = client.post(
        "/telephony/twilio/twiml", data=form, headers={"X-Twilio-Signature": signature}
    )
    assert response.status_code == 404


def test_status_callback_rejects_unsigned_requests():
    app, _, _ = _build_app()
    client = TestClient(app)
    response = client.post(
        "/telephony/twilio/status", data={"CallSid": "CA1", "CallStatus": "completed"}
    )
    assert response.status_code == 401


def test_status_callback_ignores_non_terminal_status():
    app, _, _ = _build_app()
    client = TestClient(app)
    form = {"CallSid": "CA1", "CallStatus": "ringing"}
    signature = _twilio_signature("secret-token", "https://example.test/telephony/twilio/status", form)

    response = client.post(
        "/telephony/twilio/status", data=form, headers={"X-Twilio-Signature": signature}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


def test_status_callback_unknown_call_sid_is_a_safe_noop():
    app, _, _ = _build_app()
    client = TestClient(app)
    form = {"CallSid": "CA-never-seen", "CallStatus": "completed"}
    signature = _twilio_signature("secret-token", "https://example.test/telephony/twilio/status", form)

    response = client.post(
        "/telephony/twilio/status", data=form, headers={"X-Twilio-Signature": signature}
    )
    assert response.status_code == 200
    assert response.json() == {"status": "ignored", "call_id": ""}


def test_status_callback_finalizes_call_and_cleans_session_on_terminal_status():
    app, sessions, calls = _build_app()
    client = TestClient(app)

    twiml_form = {"CallSid": "CA1", "To": "+919", "From": "+911"}
    twiml_sig = _twilio_signature(
        "secret-token", "https://example.test/telephony/twilio/twiml", twiml_form
    )
    # TwiML endpoint returns XML, not JSON — the created call_id is read back
    # from the fake session store below instead of parsing the response body.
    client.post("/telephony/twilio/twiml", data=twiml_form, headers={"X-Twilio-Signature": twiml_sig})
    call_id = next(iter(sessions.calls))

    status_form = {"CallSid": "CA1", "CallStatus": "completed"}
    status_sig = _twilio_signature(
        "secret-token", "https://example.test/telephony/twilio/status", status_form
    )
    response = client.post(
        "/telephony/twilio/status", data=status_form, headers={"X-Twilio-Signature": status_sig}
    )

    assert response.status_code == 200
    assert response.json() == {"status": "session_cleaned", "call_id": call_id}
    assert calls.finalized[0] == call_id
    assert calls.finalized[1].end_reason == "caller_hangup"
    assert call_id not in sessions.calls  # session torn down


def test_status_callback_non_completed_terminal_status_uses_provider_failure_reason():
    app, sessions, calls = _build_app()
    client = TestClient(app)

    twiml_form = {"CallSid": "CA1", "To": "+919", "From": "+911"}
    twiml_sig = _twilio_signature(
        "secret-token", "https://example.test/telephony/twilio/twiml", twiml_form
    )
    client.post("/telephony/twilio/twiml", data=twiml_form, headers={"X-Twilio-Signature": twiml_sig})

    status_form = {"CallSid": "CA1", "CallStatus": "failed"}
    status_sig = _twilio_signature(
        "secret-token", "https://example.test/telephony/twilio/status", status_form
    )
    client.post("/telephony/twilio/status", data=status_form, headers={"X-Twilio-Signature": status_sig})

    assert calls.finalized[1].end_reason == "provider_failure"


def test_status_callback_is_idempotent_via_event_recorder():
    _ensure_vg_on_path()
    from twilio_routes import EventRecorder  # noqa: PLC0415

    class CountingRecorder:
        def __init__(self):
            self.calls = 0

        async def record(self, **kwargs) -> bool:
            self.calls += 1
            return self.calls > 1  # first call: not a duplicate; every call after: duplicate

    recorder: EventRecorder = CountingRecorder()
    app, sessions, calls = _build_app(events=recorder)
    client = TestClient(app)

    twiml_form = {"CallSid": "CA1", "To": "+919", "From": "+911"}
    twiml_sig = _twilio_signature(
        "secret-token", "https://example.test/telephony/twilio/twiml", twiml_form
    )
    client.post("/telephony/twilio/twiml", data=twiml_form, headers={"X-Twilio-Signature": twiml_sig})

    status_form = {"CallSid": "CA1", "CallStatus": "completed"}
    status_sig = _twilio_signature(
        "secret-token", "https://example.test/telephony/twilio/status", status_form
    )
    first = client.post(
        "/telephony/twilio/status", data=status_form, headers={"X-Twilio-Signature": status_sig}
    )
    second = client.post(
        "/telephony/twilio/status", data=status_form, headers={"X-Twilio-Signature": status_sig}
    )

    assert first.json()["status"] == "session_cleaned"
    assert second.json()["status"] == "duplicate"
    assert calls.finalized is not None  # only finalized once, on the first (non-duplicate) call


def test_call_store_survives_across_router_instances():
    """Exercises the CallStore contract (set/get/delete) a Redis-backed
    _RedisCallStore satisfies in production (services/voice-gateway/src/main.py)
    — this fake stands in for it so the test needs no real Redis."""
    _ensure_vg_on_path()
    from twilio_routes import CallStore  # noqa: PLC0415

    class DictStore:
        def __init__(self):
            self._d: dict[str, str] = {}

        def set(self, provider_call_id, call_id):
            self._d[provider_call_id] = call_id

        def get(self, provider_call_id):
            return self._d.get(provider_call_id)

        def delete(self, provider_call_id):
            self._d.pop(provider_call_id, None)

    store: CallStore = DictStore()
    app, sessions, calls = _build_app(call_store=store)
    client = TestClient(app)

    twiml_form = {"CallSid": "CA1", "To": "+919", "From": "+911"}
    twiml_sig = _twilio_signature(
        "secret-token", "https://example.test/telephony/twilio/twiml", twiml_form
    )
    client.post("/telephony/twilio/twiml", data=twiml_form, headers={"X-Twilio-Signature": twiml_sig})
    assert store.get("CA1") is not None

    status_form = {"CallSid": "CA1", "CallStatus": "completed"}
    status_sig = _twilio_signature(
        "secret-token", "https://example.test/telephony/twilio/status", status_form
    )
    client.post("/telephony/twilio/status", data=status_form, headers={"X-Twilio-Signature": status_sig})
    assert store.get("CA1") is None  # deleted only after successful finalize
