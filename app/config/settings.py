from dotenv import load_dotenv
import os

load_dotenv()

BLAND_API_KEY = os.getenv("BLAND_API_KEY")

DATABASE_URL = os.getenv("DATABASE_URL")

REDIS_URL = os.getenv("REDIS_URL")

# --- Auth / JWT ---
# Secret is intentionally NOT given a real default: signing/verifying with an
# empty or guessable secret is worse than failing loudly at first use.
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")

JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")

JWT_ACCESS_TOKEN_EXPIRE_MINUTES = int(
    os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "30")
)