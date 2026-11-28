from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import app.models  # noqa: F401 - register ORM models on Base.metadata
from app.config import settings
from app.db import Base, check_db_connection, engine
from app.routers import auth, business, master_data


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Create database tables on application startup when PostgreSQL is reachable."""
    db_ok, _ = check_db_connection()
    if db_ok:
        Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="CashPilot API",
    description="Small Business Financial Intelligence API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_V1_PREFIX = "/api/v1"
app.include_router(auth.router, prefix=API_V1_PREFIX)
app.include_router(business.router, prefix=API_V1_PREFIX)
app.include_router(master_data.router, prefix=API_V1_PREFIX)


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
