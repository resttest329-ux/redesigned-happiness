import logging
from typing import Annotated, Optional
from fastapi import APIRouter, HTTPException, Depends, status
from sqlalchemy.orm import Session
from sqlalchemy import func, case
from utils import schema
from utils.models import InvoiceLog
from deps import get_db, get_current_user_obj
from auth import oauth2_scheme

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/invoice-log", tags=["Invoice Log"])


@router.get("/stats", response_model=schema.InvoiceLogStats)
def get_invoice_log_stats(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Session = Depends(get_db),
):
    user = get_current_user_obj(token, db)
    row = (
        db.query(
            func.count(InvoiceLog.id).label("total"),
            func.coalesce(func.sum(InvoiceLog.payable_amount), 0).label(
                "revenue"
            ),
            func.coalesce(
                func.sum(
                    case((InvoiceLog.payment_status == "PENDING", 1), else_=0)
                ),
                0,
            ).label("pending"),
            func.coalesce(
                func.sum(
                    case((InvoiceLog.payment_status == "PAID", 1), else_=0)
                ),
                0,
            ).label("paid"),
            func.coalesce(
                func.sum(
                    case((InvoiceLog.payment_status == "REJECTED", 1), else_=0)
                ),
                0,
            ).label("rejected"),
            func.coalesce(
                func.sum(
                    case((InvoiceLog.payment_status == "PARTIAL", 1), else_=0)
                ),
                0,
            ).label("partial"),
        )
        .filter(InvoiceLog.business_id == user.business_id)
        .one()
    )

    currency_rows = (
        db.query(
            InvoiceLog.currency,
            func.coalesce(func.sum(InvoiceLog.payable_amount), 0).label(
                "total"
            ),
        )
        .filter(InvoiceLog.business_id == user.business_id)
        .group_by(InvoiceLog.currency)
        .all()
    )

    revenue_by_currency = {
        r.currency: float(r.total) for r in currency_rows if r.currency
    }

    return schema.InvoiceLogStats(
        total=row.total,
        revenue=float(row.revenue),
        pending=row.pending,
        paid=row.paid,
        rejected=row.rejected,
        partial=row.partial,
        revenue_by_currency=revenue_by_currency,
    )


@router.get("", response_model=schema.InvoiceLogPage)
def list_invoice_log(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Session = Depends(get_db),
    limit: int = 20,
    offset: int = 0,
    order: str = "desc",
    search: Optional[str] = None,
):
    user = get_current_user_obj(token, db)
    query = db.query(InvoiceLog).filter(
        InvoiceLog.business_id == user.business_id
    )

    if search:
        like = f"%{search}%"
        query = query.filter(
            InvoiceLog.irn.ilike(like) | InvoiceLog.customer_name.ilike(like)
        )

    total = query.count()

    if order == "desc":
        query = query.order_by(InvoiceLog.created_at.desc())
    else:
        query = query.order_by(InvoiceLog.created_at.asc())

    logs = query.offset(offset).limit(limit).all()
    return {"total": total, "offset": offset, "limit": limit, "items": logs}


@router.post(
    "", response_model=schema.InvoiceLogOut, status_code=status.HTTP_201_CREATED
)
def create_invoice_log(
    data: schema.InvoiceLogCreate,
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Session = Depends(get_db),
):
    user = get_current_user_obj(token, db)

    existing = (
        db.query(InvoiceLog)
        .filter(
            InvoiceLog.irn == data.irn,
            InvoiceLog.business_id == user.business_id,
        )
        .first()
    )
    if existing:
        return existing

    log = InvoiceLog(**data.model_dump(), business_id=user.business_id)
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


@router.patch("/{irn}/transmitted", response_model=schema.InvoiceLogOut)
def mark_invoice_transmitted(
    irn: str,
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Session = Depends(get_db),
):
    user = get_current_user_obj(token, db)
    log = (
        db.query(InvoiceLog)
        .filter(
            InvoiceLog.irn == irn, InvoiceLog.business_id == user.business_id
        )
        .first()
    )
    if not log:
        raise HTTPException(status_code=404, detail="Invoice log not found")

    log.transmitted = True
    db.commit()
    db.refresh(log)
    return log


@router.get("/{irn}", response_model=schema.InvoiceLogOut)
def get_invoice_log_by_irn(
    irn: str,
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Session = Depends(get_db),
):
    user = get_current_user_obj(token, db)
    log = (
        db.query(InvoiceLog)
        .filter(
            InvoiceLog.irn == irn, InvoiceLog.business_id == user.business_id
        )
        .first()
    )
    if not log:
        raise HTTPException(status_code=404, detail="Invoice log not found")

    return log


@router.patch("/{irn}/status", response_model=schema.InvoiceLogOut)
def update_invoice_log_status(
    irn: str,
    body: schema.InvoiceStatusUpdate,
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Session = Depends(get_db),
):
    user = get_current_user_obj(token, db)
    log = (
        db.query(InvoiceLog)
        .filter(
            InvoiceLog.irn == irn, InvoiceLog.business_id == user.business_id
        )
        .first()
    )
    if not log:
        raise HTTPException(status_code=404, detail="Invoice log not found")

    log.payment_status = body.payment_status.value
    db.commit()
    db.refresh(log)
    return log