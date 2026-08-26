import os

from dotenv import load_dotenv

load_dotenv()

# ── External APIs ─────────────────────────────────────────────────────────────
BLAND_API_KEY = os.getenv("BLAND_API_KEY")

# ── Redis (unchanged) ─────────────────────────────────────────────────────────
REDIS_URL = os.getenv("REDIS_URL")

# ── Database — Supabase PostgreSQL (async) ────────────────────────────────────
# Accept any of these formats and normalise to asyncpg driver scheme:
#   postgresql://...          (Supabase default format)
#   postgresql+asyncpg://...  (already correct)
#   postgres://...            (legacy Heroku/Railway style)
_raw_db_url: str = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL") or ""


def _to_asyncpg_url(url: str) -> str:
    """Convert any postgresql:// URL to the asyncpg driver scheme."""
    if not url or "+asyncpg" in url:
        return url
    # Order matters: replace the shorter prefix last to avoid double-replace
    url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


DATABASE_URL: str = _to_asyncpg_url(_raw_db_url)

# Supabase requires SSL. Set DB_SSL_REQUIRED=false only for local dev.
DB_SSL_REQUIRED: bool = os.getenv("DB_SSL_REQUIRED", "true").lower() == "true"

# ── JWT ───────────────────────────────────────────────────────────────────────
JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "")
JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "30"))

# ── Admin credentials ─────────────────────────────────────────────────────────
# Temporary: validates against env vars.
# Replace with database user lookup once NK-05 users table is live.
API_USERNAME: str = os.getenv("API_USERNAME", "")
API_PASSWORD: str = os.getenv("API_PASSWORD", "")
