import json
import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from typing import Optional

import redis
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import create_access_token, get_current_user
from src.config import (
    API_PASSWORD,
    API_USERNAME,
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES,
    REDIS_URL,
    validate_startup_config,
)
from src.database import Base, engine, get_db
from src.models import Caller
from src.routers.admin import router as admin_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("staykaro.api")

# ── App lifespan ──────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_startup_config()
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database schema ready (call_requests + clients tables)")
    except Exception as exc:
        logger.error("DB init failed at startup — continuing: %s", exc)
    yield
    await engine.dispose()


app = FastAPI(title="Staykaro API", version="0.3.0", lifespan=lifespan)
app.include_router(admin_router)

# ── Request logging middleware ─────────────────────────────────────────────────


@app.middleware("http")
async def request_logging(request: Request, call_next):
    request_id = str(uuid.uuid4())[:8]
    request.state.request_id = request_id
    start = time.monotonic()
    response = await call_next(request)
    elapsed_ms = round((time.monotonic() - start) * 1000)
    logger.info(
        "[%s] %s %s → %d (%dms)",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    response.headers["X-Request-Id"] = request_id
    return response


# ── Redis client ──────────────────────────────────────────────────────────────

_redis = redis.Redis.from_url(REDIS_URL, decode_responses=True) if REDIS_URL else None


def _save_session(session_id: str, data: dict) -> None:
    if not _redis:
        return
    try:
        _redis.set(f"call:{session_id}", json.dumps(data), ex=3600)
    except redis.RedisError as exc:
        logger.warning("Redis write error for call:%s — %s", session_id, exc)


def _get_session(session_id: str) -> Optional[dict]:
    if not _redis:
        return None
    try:
        raw = _redis.get(f"call:{session_id}")
        return json.loads(raw) if raw else None
    except redis.RedisError as exc:
        logger.warning("Redis read error for call:%s — %s", session_id, exc)
        return None


# ── Schemas ───────────────────────────────────────────────────────────────────

_E164_RE = re.compile(r"^\+[1-9]\d{7,14}$")


class CallerRequest(BaseModel):
    customer_name: str
    phone_number: str
    hotel_name: str
    check_in_date: str
    check_out_date: str

    @field_validator("phone_number")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        cleaned = re.sub(r"[\s\-\(\)]", "", v)
        if not _E164_RE.match(cleaned):
            raise ValueError("phone_number must be E.164 format (e.g. +919876543210)")
        return cleaned


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


# ── Routes ────────────────────────────────────────────────────────────────────


@app.get("/health")
async def health(db: AsyncSession = Depends(get_db)) -> dict:
    checks: dict[str, str] = {}

    try:
        await db.execute(text("SELECT 1"))
        checks["db"] = "ok"
    except Exception as exc:
        logger.warning("Health DB check failed: %s", exc)
        checks["db"] = "unreachable"

    if _redis:
        try:
            _redis.ping()
            checks["redis"] = "ok"
        except Exception as exc:
            logger.warning("Health Redis check failed: %s", exc)
            checks["redis"] = "unreachable"
    else:
        checks["redis"] = "not_configured"

    overall = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return {"status": overall, "service": "staykaro-api", "version": "0.3.0", **checks}


@app.get("/")
async def root() -> dict:
    return {"service": "staykaro-api", "status": "ok", "version": "0.3.0"}


@app.get("/keepalive", tags=["ops"])
async def keepalive(db: AsyncSession = Depends(get_db)) -> dict:
    """Runs SELECT 1 against Supabase to prevent free-tier inactivity pausing."""
    try:
        await db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception as exc:
        logger.warning("keepalive DB ping failed: %s", exc)
        db_status = "unreachable"

    redis_status = "ok"
    if _redis:
        try:
            _redis.ping()
        except Exception as exc:
            logger.warning("keepalive Redis ping failed: %s", exc)
            redis_status = "unreachable"
    else:
        redis_status = "not_configured"

    return {
        "status": "ok",
        "service": "staykaro-api",
        "db": db_status,
        "redis": redis_status,
    }


# Auth ─────────────────────────────────────────────────────────────────────────


@app.post("/auth/token", response_model=TokenResponse, tags=["auth"])
async def login(form: OAuth2PasswordRequestForm = Depends()) -> TokenResponse:
    if not API_USERNAME or not API_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication not configured",
        )
    if form.username != API_USERNAME or form.password != API_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    role = "admin" if form.username == API_USERNAME else "user"
    return TokenResponse(
        access_token=create_access_token(form.username, role=role),
        expires_in=JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


# Calls (JWT-protected) ────────────────────────────────────────────────────────


@app.post("/call", tags=["calls"])
async def make_call(
    request: CallerRequest,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
) -> dict:
    caller = Caller(
        customer_name=request.customer_name,
        phone_number=request.phone_number,
        hotel_name=request.hotel_name,
        check_in_date=request.check_in_date,
        check_out_date=request.check_out_date,
    )
    db.add(caller)
    await db.commit()
    await db.refresh(caller)

    session_id = str(uuid.uuid4())
    _save_session(
        session_id,
        {
            "customer_name": request.customer_name,
            "phone_number": request.phone_number,
            "hotel_name": request.hotel_name,
            "check_in_date": request.check_in_date,
            "check_out_date": request.check_out_date,
        },
    )

    return {
        "status": "success",
        "database": "Saved",
        "redis_session": session_id if _redis else None,
    }
