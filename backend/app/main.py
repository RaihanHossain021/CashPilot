from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.db import check_db_connection

app = FastAPI(
    title="CashPilot API",
    description="Small Business Financial Intelligence API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["system"])
def health() -> JSONResponse:
    """Return service and database connectivity status."""
    db_ok, db_error = check_db_connection()
    payload: dict[str, str] = {
        "status": "ok" if db_ok else "degraded",
        "database": "connected" if db_ok else "disconnected",
    }
    if db_error:
        payload["detail"] = db_error
    return JSONResponse(status_code=200 if db_ok else 503, content=payload)
