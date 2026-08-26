"""Voice Gateway — production FastAPI application (Docker entrypoint: uvicorn src.main:app)."""

from __future__ import annotations

import contextlib
import json
import logging
import os
from dataclasses import dataclass

import redis as _redis_lib
from fastapi import FastAPI

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("staykaro.voice-gateway")

app = FastAPI(title="StayKaro Voice Gateway", version="0.2.0")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "staykaro-voice-gateway"}


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


class _GatewaySessionManager:
    """In-memory + Redis call session store for the production voice-gateway app.

    Satisfies the duck-typed session_manager expected by build_exotel_router():
    create() / get() / end() / remove().  Does not depend on any cross-service
    package; uses the redis library directly (already in requirements.txt).
    """

    def __init__(self) -> None:
        self._mem: dict[str, dict] = {}
        url = os.environ.get("REDIS_URL")
        try:
            self._r: _redis_lib.Redis | None = (
                _redis_lib.Redis.from_url(url, decode_responses=True) if url else None
            )
        except Exception as exc:
            logger.warning("Redis unavailable for session manager: %s", exc)
            self._r = None

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
    from internal_calls import InternalCallsClient  # noqa: PLC0415

    settings = _ExotelConfig(webhook_token=token)
    internal_api_url = os.environ.get("INTERNAL_API_URL", "http://api:8000")
    calls = InternalCallsClient(base_url=internal_api_url)
    session_manager = _GatewaySessionManager()

    routing = None
    if os.environ.get("EXOTEL_DEV_ROUTING", "").lower() in ("1", "true", "yes"):
        from dev_routing import TestExotelRoutingStub  # noqa: PLC0415

        routing = TestExotelRoutingStub()
        logger.warning("EXOTEL_DEV_ROUTING=true — only +917314623519 will be routed")

    app.include_router(build_exotel_router(session_manager, settings, calls, routing))
    logger.info(
        "Exotel callback router registered at /telephony/exotel/callback (internal_api=%s)",
        internal_api_url,
    )


try:
    _register_exotel_router()
except Exception as exc:
    logger.warning("Exotel router not registered: %s — set EXOTEL_WEBHOOK_TOKEN to enable.", exc)
