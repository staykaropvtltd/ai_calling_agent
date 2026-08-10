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


def _to_asyncpg_url(url: str) -> str:
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


DATABASE_URL: str = _to_asyncpg_url(_raw_db_url)
# Supabase mandates TLS; default true. Set DB_SSL_REQUIRED=false only for
# local non-Supabase dev.
DB_SSL_REQUIRED: bool = os.getenv("DB_SSL_REQUIRED", "true").lower() == "true"

# ── JWT ───────────────────────────────────────────────────────────────────────
JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "")
JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "30"))

# ── Admin credentials ─────────────────────────────────────────────────────────
# docker-compose does not forward API_USERNAME / API_PASSWORD to the container,
# but it does forward API_SECRET_KEY. Fall back to API_SECRET_KEY so the
# /auth/token endpoint stays functional in Docker without touching compose.
API_USERNAME: str = os.getenv("API_USERNAME", "admin")
API_PASSWORD: str = os.getenv("API_PASSWORD") or os.getenv("API_SECRET_KEY", "")


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
        logger.warning("API_SECRET_KEY not set — /auth/token will be non-functional")
