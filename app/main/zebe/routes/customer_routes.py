import logging
from typing import Annotated, Optional
from fastapi import APIRouter, HTTPException, Depends, status
from sqlalchemy.orm import Session
from sqlalchemy import or_
from utils import schema
from utils.models import Customer
from deps import get_db, get_current_user_obj
from auth import oauth2_scheme

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/customers", tags=["Customers"])


@router.get("", response_model=schema.CustomerPage)
def list_customers(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Session = Depends(get_db),
    search: Optional[str] = None,
    offset: int = 0,
    limit: int = 50,
):
    user = get_current_user_obj(token, db)
    query = db.query(Customer).filter(Customer.business_id == user.business_id)

    if search:
        like = f"%{search}%"
        query = query.filter(
            or_(
                Customer.party_name.ilike(like),
                Customer.tin.ilike(like),
                Customer.email.ilike(like),
            )
        )

    total = query.count()
    customers = (
        query.order_by(Customer.party_name).offset(offset).limit(limit).all()
    )
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": customers,
    }


@router.post(
    "", response_model=schema.CustomerOut, status_code=status.HTTP_201_CREATED
)
def create_customer(
    data: schema.CustomerCreate,
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Session = Depends(get_db),
):
    user = get_current_user_obj(token, db)
    customer = Customer(**data.model_dump(), business_id=user.business_id)
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


@router.get("/{id}", response_model=schema.CustomerOut)
def get_customer(
    id: int,
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Session = Depends(get_db),
):
    user = get_current_user_obj(token, db)
    customer = (
        db.query(Customer)
        .filter(Customer.id == id, Customer.business_id == user.business_id)
        .first()
    )
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


@router.patch("/{id}", response_model=schema.CustomerOut)
def update_customer(
    id: int,
    data: schema.CustomerUpdate,
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Session = Depends(get_db),
):
    user = get_current_user_obj(token, db)
    customer = (
        db.query(Customer)
        .filter(Customer.id == id, Customer.business_id == user.business_id)
        .first()
    )
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(customer, field, value)
    db.commit()
    db.refresh(customer)
    return customer


@router.delete("/{id}")
def delete_customer(
    id: int,
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Session = Depends(get_db),
):
    user = get_current_user_obj(token, db)
    customer = (
        db.query(Customer)
        .filter(Customer.id == id, Customer.business_id == user.business_id)
        .first()
    )
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    db.delete(customer)
    db.commit()
    return {"ok": True}