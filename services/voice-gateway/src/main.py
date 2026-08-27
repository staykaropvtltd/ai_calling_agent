"""Voice Gateway — production FastAPI application (Docker entrypoint: uvicorn src.main:app)."""

from __future__ import annotations

import contextlib
import json
import logging
import os
from dataclasses import dataclass

import redis as _redis_lib
from fastapi import FastAPI, Response, status

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("staykaro.voice-gateway")

app = FastAPI(title="StayKaro Voice Gateway", version="0.2.0")


@app.get("/health")
async def health(response: Response) -> dict[str, str]:
    # `session_manager` (module global, built further down) is looked up at
    # call time, not at route-definition time, so this is safe even though
    # it's assigned later in this same module.
    #
    # Same fix as services/api/src/main.py::health: a static "ok" here means
    # Docker's HEALTHCHECK (and any depends_on: condition: service_healthy)
    # can never detect a Redis outage, even though Redis is this service's
    # only durable session store (SH-03). Redis being unconfigured is a
    # deliberate degraded-but-functional mode (in-memory-only sessions), not
    # a failure, so only a configured-but-unreachable Redis flips the status.
    redis_status = "not_configured"
    if session_manager.redis is not None:
        try:
            session_manager.redis.ping()
            redis_status = "ok"
        except _redis_lib.RedisError as exc:
            logger.warning("Health Redis check failed: %s", exc)
            redis_status = "unreachable"

    is_healthy = redis_status != "unreachable"
    if not is_healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ok" if is_healthy else "degraded",
        "service": "staykaro-voice-gateway",
        "redis": redis_status,
    }


@app.get("/")
async def root() -> dict[str, str]:
    return {"service": "staykaro-voice-gateway", "status": "ok"}


# ── Exotel callback dependencies ──────────────────────────────────────────────


@dataclass(frozen=True)
class _ExotelConfig:
    """Minimal settings object for the Exotel callback router.

    build_exotel_router() only accesses settings.webhook_token at runtime,
    so we read only that field here rather than importing the full
    packages.providers.telephony.ExotelSettings (outside Docker build context).
    """

    webhook_token: str


# redis-py's default connect/socket timeouts are unbounded (OS TCP-stack
# dependent, observed 4s+ locally and potentially much longer elsewhere) —
# calls here are synchronous and made directly from async request handlers
# with no executor offload, so an unreachable Redis would otherwise stall
# the entire event loop (all in-flight calls on this gateway instance) for
# however long the OS takes to give up on the connection.
_REDIS_SOCKET_TIMEOUT_SECS = 2.0


class _GatewaySessionManager:
    """In-memory + Redis call session store for the production voice-gateway app.

    Satisfies the duck-typed session_manager expected by build_exotel_router():
    create() / get() / end() / remove().  Does not depend on any cross-service
    package; uses the redis library directly (already in requirements.txt).

    Pass redis_client to reuse an existing connection instead of opening a new one.
    When redis_client is None the manager reads REDIS_URL from the environment.
    """

    def __init__(self, redis_client: _redis_lib.Redis | None = None) -> None:
        self._mem: dict[str, dict] = {}
        if redis_client is not None:
            self._r: _redis_lib.Redis | None = redis_client
        else:
            url = os.environ.get("REDIS_URL")
            try:
                self._r = (
                    _redis_lib.Redis.from_url(
                        url,
                        decode_responses=True,
                        socket_connect_timeout=_REDIS_SOCKET_TIMEOUT_SECS,
                        socket_timeout=_REDIS_SOCKET_TIMEOUT_SECS,
                    )
                    if url
                    else None
                )
            except Exception as exc:
                logger.warning("Redis unavailable for session manager: %s", exc)
                self._r = None

    @property
    def redis(self) -> _redis_lib.Redis | None:
        return self._r

    def _key(self, call_id: str) -> str:
        return f"call_session:{call_id}"

    def create(self, call_id: str, tenant_id: str, agent_id: str) -> None:
        from datetime import UTC, datetime

        now = datetime.now(UTC).isoformat()
        data = {
            "call_id": call_id,
            "tenant_id": tenant_id,
            "agent_id": agent_id,
            "started_at": now,
            "status": "active",
        }
        self._mem[call_id] = data
        if self._r is not None:
            with contextlib.suppress(_redis_lib.RedisError):
                self._r.set(self._key(call_id), json.dumps(data), ex=3600)

    def get(self, call_id: str) -> dict | None:
        if call_id in self._mem:
            return self._mem[call_id]
        if self._r is not None:
            try:
                raw = self._r.get(self._key(call_id))
                if raw:
                    data = json.loads(raw)
                    self._mem[call_id] = data
                    return data
            except _redis_lib.RedisError:
                pass
        return None

    def end(self, call_id: str) -> None:
        if call_id in self._mem:
            self._mem[call_id]["status"] = "ended"
        if self._r is not None:
            try:
                raw = self._r.get(self._key(call_id))
                if raw:
                    data = json.loads(raw)
                    data["status"] = "ended"
                    self._r.set(self._key(call_id), json.dumps(data), ex=3600)
            except _redis_lib.RedisError:
                pass

    def remove(self, call_id: str) -> None:
        self._mem.pop(call_id, None)
        if self._r is not None:
            with contextlib.suppress(_redis_lib.RedisError):
                self._r.delete(self._key(call_id))

    def add_turn(self, call_id: str, role: str, text: str) -> None:
        """Phase 5: append one conversation turn to the session's own state.

        Per the Phase 5 design, conversation history lives in this Redis
        session (the existing source of active-call state), not a new store
        and not PostgreSQL — call_turns (services/api/src/models.py) is a
        later ticket's (SH-11) table, not written here.
        """
        from datetime import UTC, datetime

        session = self.get(call_id)
        if session is None:
            return
        turns = session.get("turns", [])
        turns.append({"role": role, "text": text, "at": datetime.now(UTC).isoformat()})
        session["turns"] = turns
        self._mem[call_id] = session
        if self._r is not None:
            with contextlib.suppress(_redis_lib.RedisError):
                self._r.set(self._key(call_id), json.dumps(session), ex=3600)


_PROVIDER_CALL_KEY_PREFIX = "voice_gateway:provider_call:"
_PROVIDER_CALL_TTL = 86400  # 24 hours


class _RedisCallStore:
    """Redis-backed CallStore: persists provider_call_id → call_id across restarts.

    Key format: voice_gateway:provider_call:{provider_call_id}
    TTL: 24 hours — stale mappings expire automatically; Exotel calls rarely last longer.

    All RedisErrors are suppressed with a warning.  If Redis is unavailable when
    set() is called, the mapping is NOT persisted.  A subsequent end event will
    find nothing in get() and return {"status": "ignored"} — the same degraded
    behavior as before persistence was added.  The warning log makes this visible.
    """

    def __init__(self, r: _redis_lib.Redis) -> None:
        self._r = r

    def _key(self, provider_call_id: str) -> str:
        return f"{_PROVIDER_CALL_KEY_PREFIX}{provider_call_id}"

    def set(self, provider_call_id: str, call_id: str) -> None:
        try:
            self._r.set(self._key(provider_call_id), call_id, ex=_PROVIDER_CALL_TTL)
        except _redis_lib.RedisError as exc:
            logger.warning(
                "CallStore: Redis write failed for provider_call_id=%s — "
                "end event will not survive a gateway restart: %s",
                provider_call_id,
                exc,
            )

    def get(self, provider_call_id: str) -> str | None:
        try:
            value = self._r.get(self._key(provider_call_id))
            return value or None
        except _redis_lib.RedisError:
            return None

    def delete(self, provider_call_id: str) -> None:
        with contextlib.suppress(_redis_lib.RedisError):
            self._r.delete(self._key(provider_call_id))


# ── Shared session manager (SH-03 / SH-01) ────────────────────────────────────
#
# One instance, shared between the Exotel callback router (creates/ends
# sessions from call lifecycle events) and the voice WebSocket router (reads
# the same session when the audio stream connects). Built unconditionally —
# CP1 (empty call lifecycle) must hold even with no telephony provider
# configured yet.

_redis_url = os.environ.get("REDIS_URL")
_shared_redis: _redis_lib.Redis | None = None
if _redis_url:
    try:
        _shared_redis = _redis_lib.Redis.from_url(
            _redis_url,
            decode_responses=True,
            socket_connect_timeout=_REDIS_SOCKET_TIMEOUT_SECS,
            socket_timeout=_REDIS_SOCKET_TIMEOUT_SECS,
        )
    except Exception as exc:
        logger.warning("Redis unavailable — sessions will be in-memory only: %s", exc)
else:
    logger.warning("REDIS_URL is not set — sessions will be in-memory only.")

session_manager = _GatewaySessionManager(redis_client=_shared_redis)

# Phase 5 — STT/AI/TTS providers, built once at import time (not per-call):
# the local Whisper model load alone is a ~15-20s one-time cost that must not
# repeat on every WebSocket connection. No STT/AI/TTS API credentials
# (DEEPGRAM_API_KEY / GROQ_API_KEY / OPENAI_API_KEY — all wired into
# docker-compose.yml but empty in this environment) are available, so these
# are the local/offline implementations behind each Protocol; a cloud
# provider is a drop-in replacement here, nowhere else.
from ai_provider import LocalRuleBasedAIProvider  # noqa: E402
from stt_provider import LocalWhisperSTTProvider  # noqa: E402
from tts_provider import LocalPyttsx3TTSProvider  # noqa: E402
from voice_pipeline import build_voice_router  # noqa: E402

_stt_provider = LocalWhisperSTTProvider()
_ai_provider = LocalRuleBasedAIProvider()
_tts_provider = LocalPyttsx3TTSProvider()

# Same flag _register_exotel_router() below reads for the dev routing stub —
# both mean "no real Exotel/routing backing this call, dev/test only". A
# call_id with no session already created via an authenticated path
# (Exotel callback or the internal API) is rejected unless this is set.
_ws_allow_unresolved = os.environ.get("EXOTEL_DEV_ROUTING", "").lower() in ("1", "true", "yes")
app.include_router(
    build_voice_router(
        session_manager,
        stt_provider=_stt_provider,
        ai_provider=_ai_provider,
        tts_provider=_tts_provider,
        allow_unresolved_sessions=_ws_allow_unresolved,
    )
)
logger.info(
    "Voice WebSocket router registered at /ws/{call_id} (allow_unresolved_sessions=%s)",
    _ws_allow_unresolved,
)


# ── Router registration ───────────────────────────────────────────────────────


def _register_exotel_router() -> None:
    """Wire the Exotel callback router into the running app.

    Called once at module load time.  Raises if EXOTEL_WEBHOOK_TOKEN is absent;
    the caller wraps this in a try/except so the app still starts (without the
    callback endpoint) when Exotel is not yet configured.
    """
    token = os.environ.get("EXOTEL_WEBHOOK_TOKEN", "").strip()
    if not token:
        raise ValueError("EXOTEL_WEBHOOK_TOKEN is not set")

    from exotel_routes import build_exotel_router  # noqa: PLC0415
    from internal_calls import (  # noqa: PLC0415
        EventsClient,
        InternalCallsClient,
        InternalPhoneRoutingClient,
    )

    settings = _ExotelConfig(webhook_token=token)
    internal_api_url = os.environ.get("INTERNAL_API_URL", "http://api:8000")
    calls = InternalCallsClient(base_url=internal_api_url)
    # Phase 6: the real, durable idempotency guarantee (services/api's
    # call_jobs table) — see exotel_routes.py::EventRecorder's docstring for
    # why this replaced the router's old in-memory dedup set.
    events = EventsClient(base_url=internal_api_url)

    call_store: _RedisCallStore | None = None
    if _shared_redis is not None:
        call_store = _RedisCallStore(_shared_redis)
    else:
        logger.warning(
            "REDIS_URL is not set or Redis is unreachable — "
            "provider_call_id mappings are in-memory only and will not survive a restart."
        )

    if os.environ.get("EXOTEL_DEV_ROUTING", "").lower() in ("1", "true", "yes"):
        from dev_routing import TestExotelRoutingStub  # noqa: PLC0415

        routing = TestExotelRoutingStub()
        logger.warning("EXOTEL_DEV_ROUTING=true — only +917314623519 will be routed")
    else:
        routing = InternalPhoneRoutingClient(internal_api_url)

    app.include_router(
        build_exotel_router(session_manager, settings, calls, routing, call_store, events)
    )
    logger.info(
        "Exotel callback router registered at /telephony/exotel/callback (internal_api=%s)",
        internal_api_url,
    )


try:
    _register_exotel_router()
except Exception as exc:
    logger.warning("Exotel router not registered: %s — set EXOTEL_WEBHOOK_TOKEN to enable.", exc)
