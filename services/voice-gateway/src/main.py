import os

import uvicorn
from fastapi import FastAPI

app = FastAPI(title="Staykaro Voice Gateway", version="0.1.0")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "staykaro-voice-gateway"}


@app.get("/")
async def root():
    return {"service": "staykaro-voice-gateway", "status": "ok"}


if __name__ == "__main__":
    uvicorn.run(
        "src.main:app",
        host=os.getenv("VOICE_GATEWAY_HOST", "0.0.0.0"),
        port=int(os.getenv("VOICE_GATEWAY_PORT", 9000)),
        log_level=os.getenv("LOG_LEVEL", "info"),
    )
