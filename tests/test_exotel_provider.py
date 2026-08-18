import asyncio
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from packages.providers.exotel import ExotelProvider
from packages.providers.telephony import ExotelSettings, ProviderError, TelephonyCallRequest


def settings() -> ExotelSettings:
    return ExotelSettings("key", "secret", "sid", "api.in.exotel.com", "+911", "token")


def test_missing_configuration_is_clear(monkeypatch):
    for name in ("EXOTEL_API_KEY", "EXOTEL_API_SECRET", "EXOTEL_SID", "EXOTEL_SUBDOMAIN", "EXOTEL_CALLER_ID", "EXOTEL_WEBHOOK_TOKEN", "EXOTEL_TENANT_ID", "EXOTEL_AGENT_ID"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ProviderError, match="EXOTEL_API_KEY"):
        ExotelSettings.from_environment()


def test_exotel_request_and_response_translation():
    observed = {}
    async def handler(request):
        observed["url"] = str(request.url)
        observed["body"] = request.content.decode()
        return httpx.Response(200, json={"Call": {"Sid": "exo-1", "Status": "queued"}})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await ExotelProvider(settings(), client).start_call(TelephonyCallRequest(call_id="internal-1", to_number="+912", from_number="+911", voice_callback_url="https://example.test/callback"))
    result = asyncio.run(run())
    assert observed["url"].endswith("/v1/Accounts/sid/Calls/connect.json")
    assert "To=%2B912" in observed["body"]
    assert result.provider_call_id == "exo-1"


def test_provider_http_and_timeout_failures_are_safe():
    async def rejected(request): return httpx.Response(401, request=request)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(rejected)) as client:
            with pytest.raises(ProviderError, match="rejected"):
                await ExotelProvider(settings(), client).start_call(TelephonyCallRequest(call_id="1", to_number="2", from_number="3", voice_callback_url="https://x"))
    asyncio.run(run())


def test_provider_timeout_is_safe():
    async def timed_out(request):
        raise httpx.ReadTimeout("slow", request=request)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(timed_out)) as client:
            with pytest.raises(ProviderError, match="timed out"):
                await ExotelProvider(settings(), client).start_call(TelephonyCallRequest(call_id="1", to_number="2", from_number="3", voice_callback_url="https://x"))
    asyncio.run(run())


def test_callback_authentication_idempotency_and_lifecycle():
    import sys
    from pathlib import Path
    sys.path.insert(0, str((Path(__file__).parent.parent / "services" / "voice-gateway").resolve()))
    # pyrefly: ignore [missing-import]
    from exotel_routes import build_exotel_router

    class Sessions:
        def __init__(self): self.calls = set()
        def create(self, call_id, tenant_id, agent_id): self.calls.add(call_id)
        def get(self, call_id): return call_id if call_id in self.calls else None
        def end(self, call_id): pass
        def remove(self, call_id): self.calls.discard(call_id)
    class Calls:
        async def create(self, call): pass
        async def finalize(self, call_id, finalization): pass
    sessions = Sessions(); app = FastAPI(); app.include_router(build_exotel_router(sessions, settings(), Calls())); client = TestClient(app)
    assert client.post("/telephony/exotel/callback", json={"CallSid":"c1", "EventType":"connected"}).status_code == 401
    assert client.post("/telephony/exotel/callback", headers={"X-Exotel-Webhook-Token":"token"}, json={"CallSid":"c1", "EventType":"connected", "Called":"+919"}).status_code == 503


def test_callback_uses_internal_call_contract_when_routing_is_available():
    import sys
    from pathlib import Path
    sys.path.insert(0, str((Path(__file__).parent.parent / "services" / "voice-gateway").resolve()))
    # pyrefly: ignore [missing-import]
    from exotel_routes import build_exotel_router
    class Sessions:
        def create(self, *args): self.call_id = args[0]
        def get(self, call_id): return object()
        def end(self, call_id): pass
        def remove(self, call_id): pass
    class Calls:
        def __init__(self): self.created = self.finalized = None
        async def create(self, value): self.created = value
        async def finalize(self, call_id, value): self.finalized = (call_id, value)
    class Routing:
        async def resolve(self, number): return ("tenant-1", "agent-1")
    calls = Calls(); app = FastAPI(); app.include_router(build_exotel_router(Sessions(), settings(), calls, Routing())); client = TestClient(app)
    started = client.post("/telephony/exotel/callback", headers={"X-Exotel-Webhook-Token":"token"}, json={"CallSid":"exo-1", "EventType":"connected", "Called":"+919"}).json()
    assert calls.created.call_id == started["call_id"] and calls.created.tenant_id == "tenant-1"
    assert client.post("/telephony/exotel/callback", headers={"X-Exotel-Webhook-Token":"token"}, json={"CallSid":"exo-1", "EventType":"completed"}).json()["status"] == "session_cleaned"
    assert calls.finalized[0] == started["call_id"] and calls.finalized[1].end_reason == "caller_hangup"


def test_dev_routing_stub_is_explicit_and_never_uses_callback_identities():
    import sys
    from pathlib import Path
    sys.path.insert(0, str((Path(__file__).parent.parent / "services" / "voice-gateway").resolve()))
    # pyrefly: ignore [missing-import]
    from dev_routing import TestExotelRoutingStub
    # pyrefly: ignore [missing-import]
    from internal_calls import InternalApiError
    route = TestExotelRoutingStub()
    assert asyncio.run(route.resolve("+917314623519")) == ("test-tenant", "test-agent")
    with pytest.raises(InternalApiError, match="not found"):
        asyncio.run(route.resolve("07314623518"))
    with pytest.raises(InternalApiError, match="not found"):
        asyncio.run(route.resolve("07314623519"))


def test_stub_routing_generates_a_new_internal_call_id_and_ignores_callback_ids():
    import sys
    from pathlib import Path
    sys.path.insert(0, str((Path(__file__).parent.parent / "services" / "voice-gateway").resolve()))
    # pyrefly: ignore [missing-import]
    from dev_routing import TestExotelRoutingStub
    # pyrefly: ignore [missing-import]
    from exotel_routes import build_exotel_router
    class Sessions:
        def create(self, *args): self.values = args
        def get(self, call_id): return None
    class Calls:
        async def create(self, value): self.value = value
        async def finalize(self, call_id, value): pass
    sessions, calls = Sessions(), Calls(); app = FastAPI()
    app.include_router(build_exotel_router(sessions, settings(), calls, TestExotelRoutingStub()))
    response = TestClient(app).post("/telephony/exotel/callback", headers={"X-Exotel-Webhook-Token": "token"}, json={"CallSid":"exo-call", "EventType":"start", "Called":"+917314623519", "tenant_id":"attacker", "agent_id":"attacker"})
    assert response.status_code == 200
    assert calls.value.call_id != "exo-call"
    assert (calls.value.tenant_id, calls.value.agent_id) == ("test-tenant", "test-agent")


def test_stub_loading_environment_conditions(monkeypatch):
    import sys
    from unittest.mock import MagicMock
    for mod in ['pipecat', 'pipecat.pipeline', 'pipecat.pipeline.pipeline', 'pipecat.pipeline.worker', 'pipecat.transports', 'pipecat.transports.base_input', 'pipecat.transports.websocket', 'pipecat.transports.websocket.fastapi', 'pipecat.workers', 'pipecat.workers.runner', 'pipecat.frames', 'pipecat.frames.frames']:
        m = MagicMock()
        m.__path__ = []
        sys.modules[mod] = m
    from pathlib import Path
    sys.path.insert(0, str((Path(__file__).parent.parent / "services" / "voice-gateway").resolve()))
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
    import main
    import importlib
    
    # local/test + stub enabled -> stub works
    monkeypatch.setenv("EXOTEL_ROUTING_STUB_ENABLED", "true")
    monkeypatch.setenv("ENVIRONMENT", "local")
    importlib.reload(main)
    assert type(main.routing).__name__ == "TestExotelRoutingStub"

    # production + stub enabled -> stub is NOT loaded
    monkeypatch.setenv("EXOTEL_ROUTING_STUB_ENABLED", "true")
    monkeypatch.setenv("ENVIRONMENT", "production")
    importlib.reload(main)
    assert main.routing is None
