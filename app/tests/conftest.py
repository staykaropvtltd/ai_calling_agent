"""
Test environment bootstrap.

The project has no committed .env (by design — see .gitignore), and
app/config/settings.py reads its values as module-level constants at
import time. pytest loads conftest.py in this directory before any test
module, so these defaults are set before `main`/`app.config.settings`
get imported anywhere in the suite.

DATABASE_URL/REDIS_URL point at hosts that are never actually contacted
in the existing tests (engine.connect / redis_client.ping are mocked),
so a syntactically valid but unreachable URL is sufficient. JWT_SECRET_KEY
is a fixed test-only value — never used outside this suite.
"""

import os

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg2://test:test@localhost:5432/test"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-not-for-production")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "30")
