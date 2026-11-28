import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.seed import seed_grocery_demo

router = APIRouter(prefix="/dev", tags=["dev"])


@router.post("/seed")
def seed_demo_endpoint(
    today: dt.date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Idempotently seed demo data (development environments only)."""
    if not settings.is_dev:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Seed endpoint is disabled outside development mode",
        )
    try:
        result = seed_grocery_demo(db, today=today)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
