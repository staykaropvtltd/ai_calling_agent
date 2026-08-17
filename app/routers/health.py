import redis
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.database.database import engine
from app.services.redis_service import redis_client

router = APIRouter(
    prefix="/api/v1",
    tags=["Health"]
)


@router.get("/health")
def health():
    return {
        "status": "ok"
    }


@router.get("/health/ready")
async def readiness():
    checks = {
        "postgresql": "ok",
        "redis": "ok"
    }

    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        checks["postgresql"] = "error"

    try:
        redis_client.ping()
    except redis.RedisError:
        checks["redis"] = "error"

    if checks["postgresql"] != "ok" or checks["redis"] != "ok":
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "checks": checks
            }
        )

    return {
        "status": "ready",
        "checks": checks
    }
