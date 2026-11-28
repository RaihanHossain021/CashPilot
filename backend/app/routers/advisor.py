import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.advisor.agent import ask_advisor
from app.auth import get_current_business_id, get_current_user
from app.db import get_db
from app.models import AdvisorLog, User
from app.schemas import AdvisorAskRequest, AdvisorAskResponse, AdvisorLogOut

router = APIRouter(prefix="/advisor", tags=["advisor"])


@router.post("/ask", response_model=AdvisorAskResponse)
def ask_advisor_endpoint(
    payload: AdvisorAskRequest,
    business_id: uuid.UUID = Depends(get_current_business_id),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AdvisorAskResponse:
    """Answer a financial question using strictly read-only, tenant-scoped tools."""
    return ask_advisor(
        db=db,
        business_id=business_id,
        user_id=current_user.id,
        question=payload.question,
    )


@router.get("/history", response_model=list[AdvisorLogOut])
def advisor_history_endpoint(
    limit: int = Query(default=20, ge=1, le=50),
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
) -> list[AdvisorLog]:
    """Return recent advisor exchanges for the authenticated business."""
    return (
        db.query(AdvisorLog)
        .filter(AdvisorLog.business_id == business_id)
        .order_by(AdvisorLog.created_at.desc())
        .limit(limit)
        .all()
    )
