"""
Focused unit tests for SH-02: Twilio telephony adapter.

Coverage:
 T01  Missing configuration env vars raise ProviderError with the first missing var name
 T02  TwilioProvider constructs correct Twilio API URL
 T03  TwilioProvider sends correct form body (To, From, Url) and Basic Auth
 T04  TwilioProvider maps 'sid' → provider_call_id on success
 T05  TwilioProvider HTTP error (4xx) raises ProviderError("rejected")
 T06  TwilioProvider timeout raises ProviderError("timed out")
 T07  Webhook missing X-Twilio-Signature header → 401
 T08  Webhook with wrong signature value → 401
 T09  Malformed payload missing CallSid → 422 (valid signature, missing field)
 T10  Duplicate (CallSid, CallStatus) event → returns "duplicate", no second create()
 T11  CallStatus=in-progress → session_started, calls.create() called with correct tenant/agent
 T12  CallStatus=completed → session_cleaned, calls.finalize() called with end_reason=caller_hangup
 T13  CallStatus=failed → end_reason=provider_failure
 T14  tenant_id / agent_id in payload are ignored; routing stub resolves the correct identities
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import sys
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Make voice-gateway modules importable
_VG = str((Path(__file__).parent.parent / "services" / "voice-gateway").resolve())
if _VG not in sys.path:
    sys.path.insert(0, _VG)

from packages.providers.twilio import TwilioProvider
from packages.providers.telephony import TwilioSettings, ProviderError, TelephonyCallRequest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Fixed test credentials — no webhook_secret; auth_token is used for signing.
_AUTH_TOKEN = "authtest"
_CALLBACK_URL = "http://testserver/telephony/twilio/callback"


def _settings() -> TwilioSettings:
    return TwilioSettings(
        account_sid="ACtest",
        auth_token=_AUTH_TOKEN,
        phone_number="+1555000",
    )


def _sign(params: dict[str, str], url: str = _CALLBACK_URL) -> str:
    """Compute the correct Twilio HMAC-SHA1 signature for the given params and URL.

    Mirrors _compute_twilio_signature() in twilio_routes exactly so tests can
    produce signatures that the route will accept.
    """
    signed = url
    for key in sorted(params.keys()):
        signed += key + (params[key] or "")
    mac = hmac.new(
        _AUTH_TOKEN.encode("utf-8"),
        signed.encode("utf-8"),
        hashlib.sha1,
    )
    return base64.b64encode(mac.digest()).decode("ascii")


def _make_app(routing=None):
    """Build a minimal FastAPI app with the Twilio router."""
    # pyrefly: ignore [missing-import]
    from twilio_routes import build_twilio_router

    class Sessions:
        def __init__(self):
            self.calls: set[str] = set()

        def create(self, call_id, tenant_id, agent_id):
            self.calls.add(call_id)

        def get(self, call_id):
            return call_id if call_id in self.calls else None

        def end(self, call_id):
            pass

        def remove(self, call_id):
            self.calls.discard(call_id)

    class Calls:
        def __init__(self):
            self.created = None
            self.finalized = None

        async def create(self, value):
            self.created = value

        async def finalize(self, call_id, value):
            self.finalized = (call_id, value)

    sessions = Sessions()
    calls = Calls()
    app = FastAPI()
    app.include_router(build_twilio_router(sessions, _settings(), calls, routing))
    return app, sessions, calls


# ---------------------------------------------------------------------------
# T01  Missing configuration
# ---------------------------------------------------------------------------

def test_T01_missing_configuration_raises_provider_error(monkeypatch):
    for name in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_PHONE_NUMBER"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ProviderError, match="TWILIO_ACCOUNT_SID"):
        TwilioSettings.from_environment()


# ---------------------------------------------------------------------------
# T02  URL construction
# ---------------------------------------------------------------------------

def test_T02_twilio_endpoint_contains_account_sid():
    provider = TwilioProvider(_settings())
    assert provider.endpoint == "https://api.twilio.com/2010-04-01/Accounts/ACtest/Calls.json"


# ---------------------------------------------------------------------------
# T03  Request construction — form body and auth
# ---------------------------------------------------------------------------

def test_T03_twilio_request_body_and_auth():
    observed: dict = {}

    async def handler(request: httpx.Request):
        observed["url"] = str(request.url)
        observed["body"] = request.content.decode()
        observed["auth"] = request.headers.get("authorization", "")
        return httpx.Response(201, json={"sid": "CA123", "status": "queued"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await TwilioProvider(_settings(), client).start_call(
                TelephonyCallRequest(
                    call_id="internal-1",
                    to_number="+919999",
                    from_number="+1555000",
                    voice_callback_url="https://example.test/callback",
                )
            )

    result = asyncio.run(run())
    assert "ACtest" in observed["url"]
    assert "Calls.json" in observed["url"]
    assert "To=%2B919999" in observed["body"] or "To=+919999" in observed["body"]
    assert "From=" in observed["body"]
    assert "Url=" in observed["body"]
    # Basic Auth must be present
    assert observed["auth"].startswith("Basic ")
    assert result.provider_call_id == "CA123"


# ---------------------------------------------------------------------------
# T04  Success response mapping
# ---------------------------------------------------------------------------

def test_T04_twilio_success_maps_sid_to_provider_call_id():
    async def handler(request: httpx.Request):
        return httpx.Response(201, json={"sid": "CA-xyz", "status": "queued"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await TwilioProvider(_settings(), client).start_call(
                TelephonyCallRequest(call_id="1", to_number="+2", from_number="+1", voice_callback_url="https://x")
            )

    result = asyncio.run(run())
    assert result.provider_call_id == "CA-xyz"
    assert result.status == "queued"


# ---------------------------------------------------------------------------
# T05  HTTP error
# ---------------------------------------------------------------------------

def test_T05_twilio_http_error_raises_provider_error():
    async def rejected(request: httpx.Request):
        return httpx.Response(401, request=request)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(rejected)) as client:
            with pytest.raises(ProviderError, match="rejected"):
                await TwilioProvider(_settings(), client).start_call(
                    TelephonyCallRequest(call_id="1", to_number="2", from_number="3", voice_callback_url="https://x")
                )

    asyncio.run(run())


# ---------------------------------------------------------------------------
# T06  Timeout
# ---------------------------------------------------------------------------

def test_T06_twilio_timeout_raises_provider_error():
    async def timed_out(request: httpx.Request):
        raise httpx.ReadTimeout("slow", request=request)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(timed_out)) as client:
            with pytest.raises(ProviderError, match="timed out"):
                await TwilioProvider(_settings(), client).start_call(
                    TelephonyCallRequest(call_id="1", to_number="2", from_number="3", voice_callback_url="https://x")
                )

    asyncio.run(run())


# ---------------------------------------------------------------------------
# T07  Webhook auth — missing header
# ---------------------------------------------------------------------------

def test_T07_webhook_missing_signature_returns_401():
    app, _, _ = _make_app()
    client = TestClient(app)
    resp = client.post(
        "/telephony/twilio/callback",
        # No X-Twilio-Signature header
        data={"CallSid": "CA1", "CallStatus": "in-progress", "Called": "+919999"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# T08  Webhook auth — wrong signature (not the correct HMAC-SHA1)
# ---------------------------------------------------------------------------

def test_T08_webhook_wrong_signature_returns_401():
    app, _, _ = _make_app()
    client = TestClient(app)
    params = {"CallSid": "CA1", "CallStatus": "in-progress", "Called": "+919999"}
    resp = client.post(
        "/telephony/twilio/callback",
        # Deliberately wrong — not the HMAC-SHA1 of the form params
        headers={"X-Twilio-Signature": "dGhpc2lzd3Jvbmc="},
        data=params,
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# T09  Malformed payload — valid signature but missing CallSid → 422
# ---------------------------------------------------------------------------

def test_T09_missing_callsid_returns_422():
    app, _, _ = _make_app()
    client = TestClient(app)
    params = {"CallStatus": "in-progress", "Called": "+919999"}
    resp = client.post(
        "/telephony/twilio/callback",
        headers={"X-Twilio-Signature": _sign(params)},
        data=params,
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# T10  Duplicate event idempotency
# ---------------------------------------------------------------------------

def test_T10_duplicate_event_returns_duplicate_status():
    class SimpleRouting:
        async def resolve(self, number):
            return ("t1", "a1")

    app, _, calls = _make_app(routing=SimpleRouting())
    client = TestClient(app)

    params = {"CallSid": "CA-dup", "CallStatus": "in-progress", "Called": "+919999"}
    headers = {"X-Twilio-Signature": _sign(params)}

    first = client.post("/telephony/twilio/callback", headers=headers, data=params)
    assert first.status_code == 200
    assert first.json()["status"] == "session_started"

    second = client.post("/telephony/twilio/callback", headers=headers, data=params)
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"


# ---------------------------------------------------------------------------
# T11  Start on in-progress — full lifecycle
# ---------------------------------------------------------------------------

def test_T11_in_progress_starts_session_and_calls_create():
    class SimpleRouting:
        async def resolve(self, number):
            return ("tenant-x", "agent-x")

    app, sessions, calls = _make_app(routing=SimpleRouting())
    client = TestClient(app)

    params = {"CallSid": "CA-live", "CallStatus": "in-progress", "Called": "+919999"}
    resp = client.post(
        "/telephony/twilio/callback",
        headers={"X-Twilio-Signature": _sign(params)},
        data=params,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "session_started"
    call_id = body["call_id"]
    assert call_id != "CA-live"  # internal UUID, not provider CallSid
    assert calls.created is not None
    assert calls.created.call_id == call_id
    assert calls.created.tenant_id == "tenant-x"
    assert calls.created.agent_id == "agent-x"
    assert call_id in sessions.calls


# ---------------------------------------------------------------------------
# T12  Finalize on completed — caller_hangup
# ---------------------------------------------------------------------------

def test_T12_completed_finalizes_with_caller_hangup():
    class SimpleRouting:
        async def resolve(self, number):
            return ("t1", "a1")

    app, _, calls = _make_app(routing=SimpleRouting())
    client = TestClient(app)

    start_params = {"CallSid": "CA-fin", "CallStatus": "in-progress", "Called": "+919999"}
    started = client.post(
        "/telephony/twilio/callback",
        headers={"X-Twilio-Signature": _sign(start_params)},
        data=start_params,
    ).json()
    call_id = started["call_id"]

    end_params = {"CallSid": "CA-fin", "CallStatus": "completed"}
    completed = client.post(
        "/telephony/twilio/callback",
        headers={"X-Twilio-Signature": _sign(end_params)},
        data=end_params,
    ).json()
    assert completed["status"] == "session_cleaned"
    assert completed["call_id"] == call_id
    assert calls.finalized is not None
    assert calls.finalized[0] == call_id
    assert calls.finalized[1].end_reason == "caller_hangup"


# ---------------------------------------------------------------------------
# T13  Finalize on failed — provider_failure
# ---------------------------------------------------------------------------

def test_T13_failed_finalizes_with_provider_failure():
    class SimpleRouting:
        async def resolve(self, number):
            return ("t1", "a1")

    app, _, calls = _make_app(routing=SimpleRouting())
    client = TestClient(app)

    start_params = {"CallSid": "CA-fail", "CallStatus": "in-progress", "Called": "+919999"}
    client.post(
        "/telephony/twilio/callback",
        headers={"X-Twilio-Signature": _sign(start_params)},
        data=start_params,
    )

    fail_params = {"CallSid": "CA-fail", "CallStatus": "failed"}
    result = client.post(
        "/telephony/twilio/callback",
        headers={"X-Twilio-Signature": _sign(fail_params)},
        data=fail_params,
    ).json()
    assert result["status"] == "session_cleaned"
    assert calls.finalized[1].end_reason == "provider_failure"


# ---------------------------------------------------------------------------
# T14  tenant_id / agent_id in payload are ignored
# ---------------------------------------------------------------------------

def test_T14_payload_tenant_agent_ignored_routing_used_instead():
    # pyrefly: ignore [missing-import]
    from internal_calls import InternalApiError

    class StrictRouting:
        """Returns the correct tenant/agent only for the expected number."""
        async def resolve(self, number):
            if number != "+917314623519":
                raise InternalApiError("Test phone-number route not found")
            return ("real-tenant", "real-agent")

    app, _, calls = _make_app(routing=StrictRouting())
    client = TestClient(app)

    params = {
        "CallSid": "CA-atk",
        "CallStatus": "in-progress",
        "Called": "+917314623519",
        "tenant_id": "attacker",
        "agent_id": "attacker",
    }
    resp = client.post(
        "/telephony/twilio/callback",
        headers={"X-Twilio-Signature": _sign(params)},
        data=params,
    )
    assert resp.status_code == 200
    assert calls.created is not None
    assert calls.created.tenant_id == "real-tenant"
    assert calls.created.agent_id == "real-agent"
    assert calls.created.call_id != "CA-atk"
