from fastapi import FastAPI

from app.routers.home import router as home_router
from app.routers.health import router as health_router


app = FastAPI(
    title="Staykaro AI Caller",
    version="1.0.0"
)

app.include_router(home_router)
app.include_router(health_router)