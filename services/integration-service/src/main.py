import os

from fastapi import FastAPI

app = FastAPI(title="Staykaro Integration Service", version="0.1.0")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "staykaro-integration-service"}


@app.get("/")
async def root():
    return {"service": "staykaro-integration-service", "status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=int(os.getenv("INTEGRATION_SERVICE_PORT", 8002)),
        log_level=os.getenv("LOG_LEVEL", "info"),
    )
