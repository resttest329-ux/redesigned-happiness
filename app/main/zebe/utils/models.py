from typing import Optional
from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    String,
    DateTime,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from utils import database
from datetime import datetime, timezone

Base = database.Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(50), index=True)
    email: Mapped[str] = mapped_column(String(120), index=True, unique=True)
    hashed_password: Mapped[str] = mapped_column(String)
    business_id: Mapped[str] = mapped_column(String, index=True)
    service_id: Mapped[str] = mapped_column(String, index=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    date: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    user_secret: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, default=None
    )
    certificate: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, default=None
    )
    public_key: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, default=None
    )
    tin: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, default=None
    )
    party_name: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, default=None
    )
    telephone: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, default=None
    )
    street_name: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, default=None
    )
    city_name: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, default=None
    )
    postal_zone: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, default=None
    )
    country: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, default=None
    )
    state: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, default=None
    )
    lga: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, default=None
    )

    def __repr__(self):
        return f"Company: {self.username} | business ID: {self.business_id} | is active?: {self.is_active}"


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    business_id: Mapped[str] = mapped_column(String, index=True)
    tin: Mapped[str]
    party_name: Mapped[str]
    email: Mapped[str]
    telephone: Mapped[str]
    street_name: Mapped[str]
    city_name: Mapped[str]
    postal_zone: Mapped[str]
    country: Mapped[str]
    state: Mapped[str]
    lga: Mapped[Optional[str]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class InvoiceLog(Base):
    __tablename__ = "invoice_log"
    __table_args__ = (
        UniqueConstraint(
            "business_id", "irn", name="uq_invoice_log_business_irn"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    business_id: Mapped[str] = mapped_column(String, index=True)
    irn: Mapped[str] = mapped_column(String, index=True)
    issue_date: Mapped[str]
    customer_name: Mapped[str]
    currency: Mapped[str]
    payment_status: Mapped[str] = mapped_column(default="PENDING")
    payable_amount: Mapped[float]
    transmitted: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class Item(Base):
    """Business-scoped catalog item or service.

    Each row must carry EXACTLY ONE FIRS classification: either an HS code
    (product) or an ISIC code (service), never both and never neither. That
    invariant is enforced at three layers: Pydantic schema, application
    service, and a DB-level CHECK constraint.
    """

    __tablename__ = "items"
    __table_args__ = (
        UniqueConstraint("business_id", "sku", name="uq_items_business_sku"),
        CheckConstraint(
            "(hsn_code IS NOT NULL AND isic_code IS NULL) OR "
            "(hsn_code IS NULL AND isic_code IS NOT NULL)",
            name="ck_items_exactly_one_code",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    business_id: Mapped[str] = mapped_column(String, index=True)
    sku: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String, index=True)
    description: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, default=None
    )
    hsn_code: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, default=None, index=True
    )
    hsn_category: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, default=None
    )
    isic_code: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, default=None, index=True
    )
    isic_category: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, default=None
    )
    unit_price: Mapped[Optional[float]] = mapped_column(
        nullable=True, default=None
    )
    price_unit: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class SessionState(Base):
    __tablename__ = "session_state"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    jwt_token: Mapped[str]
    user_secret: Mapped[str] = mapped_column(default="")
    username: Mapped[str]
    business_id: Mapped[str]
    expires_at: Mapped[str]
    wizard_json: Mapped[Optional[str]] = mapped_column(nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
