from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.auth.router import router as auth_router
from app.database.database import Base, engine
from app.routers.health import router as health_router
from app.routers.home import router as home_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure all ORM tables exist in Supabase on startup.
    # create_all is idempotent — safe to run on every restart.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Cleanly close all pooled connections on shutdown.
    await engine.dispose()


app = FastAPI(
    title="Staykaro AI Caller",
    version="1.0.0",
    lifespan=lifespan,
)
app.include_router(auth_router)
app.include_router(home_router)
app.include_router(health_router)
