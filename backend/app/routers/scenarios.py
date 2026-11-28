import datetime as dt
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import get_current_business_id
from app.db import get_db
from app.models import Business, ScheduledEvent
from app.schemas import (
    ScenarioOptionItemOut,
    ScenarioOptionsResponse,
    ScenarioRequest,
    ScenarioResponse,
)
from app.services import finance, scenario
from app.services.finance import q4

router = APIRouter(prefix="/scenarios", tags=["scenarios"])
MAX_OPTIONS = 20


@router.get("/options", response_model=ScenarioOptionsResponse)
def get_scenario_options(
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
) -> ScenarioOptionsResponse:
    """Return deterministically sorted, capped targets for Scenario Lab controls."""
    as_of = dt.date.today()
    business = db.get(Business, business_id)
    assert business is not None

    rec_items = [
        tx
        for tx in finance.get_receivables(db, business_id, as_of=as_of)["open_transactions"]  # type: ignore[attr-defined]
        if tx.overdue
    ]
    rec_items.sort(
        key=lambda t: (t.due_date or dt.date.max, -t.balance_due, str(t.transaction_id))
    )

    pay_items = list(
        finance.get_payables(db, business_id, as_of=as_of)["open_transactions"]  # type: ignore[attr-defined]
    )
    pay_items.sort(
        key=lambda t: (t.due_date or dt.date.max, -t.balance_due, str(t.transaction_id))
    )

    reorder_rows = (
        db.query(ScheduledEvent)
        .filter(
            ScheduledEvent.business_id == business_id,
            ScheduledEvent.status == "active",
            ScheduledEvent.direction == "outflow",
        )
        .order_by(
            ScheduledEvent.expected_on.asc(),
            ScheduledEvent.amount.desc(),
            ScheduledEvent.id.asc(),
        )
        .limit(MAX_OPTIONS)
        .all()
    )

    receivables_out = [
        ScenarioOptionItemOut(
            id=tx.transaction_id,
            kind="receivable",
            label=(
                f"{tx.party_name or 'Customer'} · {tx.balance_due} {business.currency}"
                + (f" (due {tx.due_date})" if tx.due_date else "")
            ),
            party_name=tx.party_name or "Customer",
            amount=tx.balance_due,
            due_on=tx.due_date,
        )
        for tx in rec_items[:MAX_OPTIONS]
    ]

    payables_out = [
        ScenarioOptionItemOut(
            id=tx.transaction_id,
            kind="payable",
            label=(
                f"{tx.party_name or 'Supplier/Expense'} · {tx.balance_due} {business.currency}"
                + (f" (due {tx.due_date})" if tx.due_date else "")
            ),
            party_name=tx.party_name or "Supplier/Expense",
            amount=tx.balance_due,
            due_on=tx.due_date,
        )
        for tx in pay_items[:MAX_OPTIONS]
    ]

    reorders_out = [
        ScenarioOptionItemOut(
            id=ev.id,
            kind="scheduled_reorder",
            label=f"{ev.label} · {q4(ev.amount)} {business.currency} (on {ev.expected_on})",
            party_name=ev.label,
            amount=q4(ev.amount),
            due_on=ev.expected_on,
        )
        for ev in reorder_rows
    ]

    return ScenarioOptionsResponse(
        currency=business.currency,
        as_of=as_of,
        receivables=receivables_out,
        payables=payables_out,
        reorders=reorders_out,
    )


@router.post("", response_model=ScenarioResponse)
def run_scenario_endpoint(
    payload: ScenarioRequest,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
) -> ScenarioResponse:
    """Run a read-only what-if scenario against baseline (server sets as_of)."""
    return scenario.run_scenario(db=db, business_id=business_id, req=payload)
