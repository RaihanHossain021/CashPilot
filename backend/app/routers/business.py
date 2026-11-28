from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_current_business, get_current_user
from app.db import get_db
from app.models import Business, User
from app.schemas import BusinessCreate, BusinessOut

router = APIRouter(prefix="/business", tags=["business"])


@router.get("", response_model=BusinessOut)
def get_business(business: Business = Depends(get_current_business)) -> Business:
    """Return the authenticated user's business profile (404 if not yet created)."""
    return business


@router.post("", response_model=BusinessOut, status_code=status.HTTP_201_CREATED)
def create_business(
    payload: BusinessCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Business:
    """Create the authenticated user's single business profile."""
    existing = db.query(Business).filter(Business.owner_id == current_user.id).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Business profile already exists for this user",
        )

    business = Business(
        owner_id=current_user.id,
        name=payload.name.strip(),
        vertical=payload.vertical,
        currency=payload.currency.strip().upper(),
        min_cash_reserve=payload.min_cash_reserve,
        slow_stock_days_threshold=payload.slow_stock_days_threshold,
    )
    db.add(business)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Business profile already exists for this user",
        ) from exc
    db.refresh(business)
    return business
