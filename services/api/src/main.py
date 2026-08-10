import os

from fastapi import FastAPI

app = FastAPI(title="Staykaro API", version="0.1.0")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "staykaro-api"}


@app.get("/")
async def root():
    return {"service": "staykaro-api", "status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.main:app",
        host=os.getenv("API_HOST", "0.0.0.0"),
        port=int(os.getenv("API_PORT", 8000)),
        log_level=os.getenv("LOG_LEVEL", "info"),
    )
