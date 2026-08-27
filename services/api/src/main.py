import json
import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from typing import Optional

import redis
from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import (
    _ROLE_PERMISSIONS,
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    get_current_user,
    verify_password,
)
from src.config import (
    API_ADMIN_EMAIL,
    API_ADMIN_FULL_NAME,
    API_CORS_ORIGINS,
    API_PASSWORD,
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES,
    REDIS_URL,
    validate_startup_config,
)
from src.database import engine, get_db
from src.models import Caller, User
from src.routers.admin import router as admin_router
from src.routers.internal import router as internal_router
from src.tenant import get_login_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("staykaro.api")

# ── App lifespan ──────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Schema is owned by Alembic (NK-02, Database Design §9) and applied by
    # docker-entrypoint.sh / CI before this process starts — never create_all()
    # here. This just confirms the migrated schema is actually reachable.
    validate_startup_config()
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1 FROM admin_users LIMIT 1"))
        logger.info("Database schema reachable (migrations applied)")
    except Exception as exc:
        logger.error(
            "Database schema check failed — has `alembic upgrade head` been run? %s", exc
        )
    yield
    await engine.dispose()


app = FastAPI(title="Staykaro API", version="0.3.0", lifespan=lifespan)

# API_CORS_ORIGINS is documented in .env.example for exactly this — without
# it, a browser-based client (apps/admin-dashboard, apps/client-dashboard)
# calling this API's own origin directly (not through nginx's same-origin
# /api/ path) is blocked by the browser regardless of whether its JWT is
# valid. Explicit origin allowlist, never a wildcard, since Authorization
# headers are involved. No-op (no CORS headers at all) when unconfigured.
if API_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=API_CORS_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(admin_router)
app.include_router(internal_router)

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


class LoginRequest(BaseModel):
    email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class MeResponse(BaseModel):
    user_id: str
    email: str
    full_name: str
    role: str
    tenant_id: Optional[int]
    permissions: list[str]


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


# ── Routes ────────────────────────────────────────────────────────────────────


@app.get("/health")
async def health(response: Response, db: AsyncSession = Depends(get_db)) -> dict:
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
        # Redis is an optional dependency (session persistence only) — absent
        # by deliberate configuration, not a failure, so it must not flip the
        # HTTP status code below the way an actual "unreachable" does.
        checks["redis"] = "not_configured"

    # db unreachable or a configured-but-failing redis are real outages; a
    # non-2xx status here is what Docker's HEALTHCHECK (`curl -f`, which only
    # inspects the status code, never the JSON body) and any `depends_on:
    # condition: service_healthy` actually key off — returning 200 with
    # "status": "degraded" in the body previously made both blind to a real
    # database/Redis outage.
    is_healthy = checks["db"] == "ok" and checks["redis"] != "unreachable"
    if not is_healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    overall = "ok" if is_healthy else "degraded"
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


@app.post("/auth/login", response_model=TokenResponse, tags=["auth"])
async def login(body: LoginRequest, db: AsyncSession = Depends(get_login_db)) -> TokenResponse:
    # NK-05: admin_users is the real credential store — password_hash is
    # bcrypt, never plaintext (Database Design §2). API_ADMIN_EMAIL/API_PASSWORD
    # is kept only as a break-glass bootstrap login for the very first deploy,
    # before any admin_users row exists; it never overrides a matching DB user.
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if user is not None:
        if user.status != "active" or not user.password_hash:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if not verify_password(body.password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return TokenResponse(
            access_token=create_access_token(
                user.id,
                role=user.role or "agent",
                client_id=user.tenant_id,
                email=user.email,
                full_name=user.full_name,
            ),
            refresh_token=create_refresh_token(
                user.id,
                role=user.role or "agent",
                email=user.email,
                full_name=user.full_name,
            ),
            expires_in=JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    if API_ADMIN_EMAIL and API_PASSWORD and body.email == API_ADMIN_EMAIL:
        if body.password != API_PASSWORD:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return TokenResponse(
            access_token=create_access_token(
                body.email,
                role="super_admin",
                email=body.email,
                full_name=API_ADMIN_FULL_NAME,
            ),
            refresh_token=create_refresh_token(
                body.email,
                role="super_admin",
                email=body.email,
                full_name=API_ADMIN_FULL_NAME,
            ),
            expires_in=JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


@app.post("/auth/refresh", response_model=TokenResponse, tags=["auth"])
async def refresh_token(body: RefreshRequest) -> TokenResponse:
    payload = decode_refresh_token(body.refresh_token)
    subject = payload["sub"]
    role = payload.get("role", "agent")
    email = payload.get("email", "")
    full_name = payload.get("full_name", "")
    return TokenResponse(
        access_token=create_access_token(subject, role=role, email=email, full_name=full_name),
        refresh_token=create_refresh_token(subject, role=role, email=email, full_name=full_name),
        expires_in=JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@app.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT, tags=["auth"])
async def logout(_user: dict = Depends(get_current_user)) -> None:
    # Stateless logout: the client discards its tokens. Server-side token
    # revocation (Redis denylist) is deferred to NK-05.
    return None


@app.get("/auth/me", response_model=MeResponse, tags=["auth"])
async def me(user: dict = Depends(get_current_user)) -> MeResponse:
    role = user.get("role", "agent")
    return MeResponse(
        user_id=user["sub"],
        email=user.get("email", ""),
        full_name=user.get("full_name", ""),
        role=role,
        tenant_id=user.get("client_id"),
        permissions=_ROLE_PERMISSIONS.get(role, []),
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
