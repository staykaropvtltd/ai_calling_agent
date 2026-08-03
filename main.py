from fastapi import FastAPI
from app.routers.home import router as home_router

from app.database.database import engine, Base
from app.models.caller import Caller

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Staykaro AI Caller",
    version="1.0.0"
)

app.include_router(home_router)