import logging
import os

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("staykaro.config")

# ── Redis ─────────────────────────────────────────────────────────────────────
REDIS_URL: str = os.getenv("REDIS_URL", "")

# ── Database — Supabase PostgreSQL ────────────────────────────────────────────
# docker-compose injects DATABASE_URL; SUPABASE_DB_URL is honoured when
# running locally (load_dotenv picks it up from .env).
_raw_db_url: str = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL") or ""


def to_asyncpg_url(url: str) -> str:
    """Normalise any postgres:// variant to postgresql+asyncpg:// for asyncpg."""
    if not url or "+asyncpg" in url:
        return url
    for prefix in ("postgresql+", "postgres+"):
        if url.startswith(prefix):
            driver_end = url.index("://", len(prefix))
            url = "postgresql+asyncpg" + url[driver_end:]
            return url
    url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


DATABASE_URL: str = to_asyncpg_url(_raw_db_url)
# Supabase mandates TLS; default true. Set DB_SSL_REQUIRED=false only for
# local non-Supabase dev.
DB_SSL_REQUIRED: bool = os.getenv("DB_SSL_REQUIRED", "true").lower() == "true"

# ── JWT ───────────────────────────────────────────────────────────────────────
JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "")
JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
JWT_REFRESH_TOKEN_EXPIRE_MINUTES: int = int(
    os.getenv("JWT_REFRESH_TOKEN_EXPIRE_MINUTES", "10080")
)  # 7 days

# ── CORS ──────────────────────────────────────────────────────────────────────
# Comma-separated browser origins allowed to call this API directly (bypassing
# the /api/ same-origin path through nginx) — the admin/client dashboards
# (apps/admin-dashboard, apps/client-dashboard) call NEXT_PUBLIC_API_URL from
# the browser with an Authorization header, which needs explicit CORS origins;
# without this the browser blocks every cross-origin request regardless of
# whether the JWT itself is valid. Empty means no cross-origin browser access
# at all (still fine for server-to-server or same-origin /api/ calls).
API_CORS_ORIGINS: list[str] = [
    origin.strip() for origin in os.getenv("API_CORS_ORIGINS", "").split(",") if origin.strip()
]

# ── Internal service-to-service API ───────────────────────────────────────────
# Shared secret the voice gateway must present (X-Internal-API-Token header) to
# call /internal/v1/* — these routes have no JWT/user identity (see
# src/tenant.py::get_internal_service_db) and are otherwise reachable by any
# caller on the Docker network with no authentication at all. Same
# hmac.compare_digest pattern already used for EXOTEL_WEBHOOK_TOKEN
# (services/voice-gateway/exotel_routes.py). Empty/unset fails closed — every
# internal request is rejected, never accidentally left open.
INTERNAL_API_TOKEN: str = os.getenv("INTERNAL_API_TOKEN", "")

# ── Admin credentials ─────────────────────────────────────────────────────────
# docker-compose does not forward API_USERNAME / API_PASSWORD to the container,
# but it does forward API_SECRET_KEY. Fall back to API_SECRET_KEY so the
# /auth/login endpoint stays functional in Docker without touching compose.
API_USERNAME: str = os.getenv("API_USERNAME", "admin")
API_PASSWORD: str = os.getenv("API_PASSWORD") or os.getenv("API_SECRET_KEY", "")
# Email and display name embedded in JWTs issued at /auth/login.
# Replace with DB lookup when NK-05 delivers the user table.
API_ADMIN_EMAIL: str = os.getenv("API_ADMIN_EMAIL", "admin@staykaro.com")
API_ADMIN_FULL_NAME: str = os.getenv("API_ADMIN_FULL_NAME", "System Admin")


def validate_startup_config() -> None:
    """Fail fast on missing critical env vars; warn on degraded-feature vars."""
    critical_missing = []
    if not DATABASE_URL:
        critical_missing.append("DATABASE_URL / SUPABASE_DB_URL")
    if not JWT_SECRET_KEY:
        critical_missing.append("JWT_SECRET_KEY")

    if critical_missing:
        raise RuntimeError(
            f"Critical env vars missing — cannot start: {', '.join(critical_missing)}"
        )

    if not REDIS_URL:
        logger.warning("REDIS_URL not set — call sessions will not be persisted")
    if not API_PASSWORD:
        logger.warning("API_SECRET_KEY not set — /auth/login will be non-functional")
    if not INTERNAL_API_TOKEN:
        logger.warning(
            "INTERNAL_API_TOKEN not set — /internal/v1/* will reject every request "
            "(fail closed), so the voice gateway cannot reach it until this is set"
        )
