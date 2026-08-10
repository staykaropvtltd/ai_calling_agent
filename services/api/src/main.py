import asyncio
import json
import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from typing import Optional

import redis
import requests
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import create_access_token, get_current_user
from src.config import (
    API_PASSWORD,
    API_USERNAME,
    BLAND_API_KEY,
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


def _save_session(call_id: str, data: dict) -> None:
    if not _redis:
        return
    try:
        _redis.set(f"call:{call_id}", json.dumps(data), ex=3600)
    except redis.RedisError as exc:
        logger.warning("Redis write error for call:%s — %s", call_id, exc)


def _get_session(call_id: str) -> Optional[dict]:
    if not _redis:
        return None
    try:
        raw = _redis.get(f"call:{call_id}")
        return json.loads(raw) if raw else None
    except redis.RedisError as exc:
        logger.warning("Redis read error for call:%s — %s", call_id, exc)
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


# ── Bland AI (blocking — called via asyncio.to_thread) ───────────────────────


def _trigger_bland_call(request: CallerRequest) -> dict:
    if not BLAND_API_KEY:
        return {"status": "error", "message": "BLAND_API_KEY not configured"}

    url = "https://api.bland.ai/v1/calls"
    # Bland AI requires lowercase "authorization" header without "Bearer " prefix
    headers = {"authorization": BLAND_API_KEY, "Content-Type": "application/json"}
    payload = {
        "phone_number": request.phone_number,
        "task": (
            f"You are a polite hotel receptionist from Staykaro.\n"
            f"Call the customer named {request.customer_name}.\n"
            f"Tell them they have a reservation at {request.hotel_name}.\n"
            f"Check-in: {request.check_in_date}. Check-out: {request.check_out_date}.\n"
            "Confirm their stay or offer to have a hotel executive contact them if needed."
        ),
    }
    logger.info(
        "Bland AI request: phone=%s hotel=%s", request.phone_number, request.hotel_name
    )
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.Timeout:
        logger.error("Bland AI request timed out")
        return {"status": "error", "message": "Bland AI request timed out"}
    except requests.exceptions.HTTPError as exc:
        body = exc.response.text if exc.response is not None else ""
        code = exc.response.status_code if exc.response is not None else None
        logger.error("Bland AI HTTP %s: %s", code, body)
        return {"status": "error", "message": f"Bland AI returned HTTP {code}", "detail": body}
    except requests.exceptions.RequestException as exc:
        logger.error("Bland AI request failed: %s", exc)
        return {"status": "error", "message": str(exc)}
    except ValueError:
        return {"status": "error", "message": "Invalid JSON response from Bland AI"}

    call_id = data.get("call_id")
    logger.info("Bland AI response: call_id=%s", call_id)

    if not call_id:
        return {
            "status": "error",
            "message": "Bland AI did not return call_id",
            "bland_response": data,
        }

    _save_session(
        call_id,
        {
            "customer_name": request.customer_name,
            "phone_number": request.phone_number,
            "hotel_name": request.hotel_name,
            "check_in_date": request.check_in_date,
            "check_out_date": request.check_out_date,
            "call_status": "initiated",
        },
    )
    return data


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
    # Admin user always gets admin role; extend this if/when a real user table exists
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

    bland_result = await asyncio.to_thread(_trigger_bland_call, request)

    call_id = bland_result.get("call_id")
    is_error = bland_result.get("status") == "error"
    call_status = "failed" if is_error else "pending"
    session = _get_session(call_id) if call_id else None

    return {
        "status": call_status,
        "db_record_id": caller.id,
        "call_id": call_id,
        "bland": bland_result,
        "session": session,
    }
