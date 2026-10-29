"""ASGI application shell; API routes are added in the endpoint task."""
from fastapi import FastAPI

app = FastAPI(title="Invoice AI API")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
