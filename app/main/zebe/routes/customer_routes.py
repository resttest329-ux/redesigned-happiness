import logging
from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from pydantic import ValidationError
from sqlalchemy.orm import Session
from sqlalchemy import or_

from utils import schema
from utils.models import Customer
from deps import get_db, get_current_user_obj
from auth import oauth2_scheme
from services.import_utils import (
    MAX_IMPORT_ROWS,
    format_validation_error,
    normalize_row,
    parse_import_file,
    row_label,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/customers", tags=["Customers"])

CUSTOMER_FIELDS = (
    "tin",
    "party_name",
    "email",
    "telephone",
    "street_name",
    "city_name",
    "postal_zone",
    "country",
    "state",
    "lga",
)

IMPORT_COLUMNS = list(CUSTOMER_FIELDS)


def _coerce_int(value, default: int) -> int:
    """Normalize a paging value for direct Python calls.

    Under FastAPI the declared ``Query(...)`` default is replaced by the parsed
    request value, so this is a no-op. When a route is called directly from
    Python (tests, internal helpers) the unresolved marker object can leak
    through as the default, so coerce it back to the documented default.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_str(value) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _coerce_bool(value, default: bool | None) -> bool | None:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
        return default
    return default


def _scoped(db: Session, business_id: str):
    return db.query(Customer).filter(Customer.business_id == business_id)


def _get_owned(db: Session, cid: int, business_id: str) -> Customer:
    customer = _scoped(db, business_id).filter(Customer.id == cid).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


def _find_by_tin(
    db: Session, business_id: str, tin: str | None
) -> Customer | None:
    if not tin:
        return None
    return _scoped(db, business_id).filter(Customer.tin == tin).first()


def _apply_payload(customer: Customer, data: dict) -> None:
    for field in CUSTOMER_FIELDS:
        if field in data:
            setattr(customer, field, data[field])
    customer.updated_at = datetime.now(timezone.utc)


@router.get("", response_model=schema.CustomerPage)
def list_customers(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Session = Depends(get_db),
    search: Optional[str] = None,
    active: Optional[bool] = True,
    offset: int = 0,
    limit: int = Query(50, ge=1, le=500),
):
    user = get_current_user_obj(token, db)
    search = _coerce_str(search)
    active = _coerce_bool(active, True)
    offset = max(0, _coerce_int(offset, 0))
    limit = min(500, max(1, _coerce_int(limit, 50)))
    query = _scoped(db, user.business_id)

    if active is not None:
        query = query.filter(Customer.is_active == active)

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
    customer = Customer(
        **data.model_dump(),
        business_id=user.business_id,
        is_active=True,
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


@router.post("/import", response_model=schema.CustomerImportResult)
async def import_customers(
    token: Annotated[str, Depends(oauth2_scheme)],
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Bulk create or update customers from a spreadsheet.

    Rows are matched on TIN inside the workspace: a known TIN is updated (and
    reactivated), an unknown TIN is created. Invalid rows are skipped with a
    concise reason and never abort the import.
    """
    user = get_current_user_obj(token, db)
    raw = await file.read()
    rows = parse_import_file(file.filename or "", raw)
    if not rows:
        raise HTTPException(
            status_code=400,
            detail=(
                "No rows found. Expected a CSV/XLSX file with the columns: "
                + ", ".join(IMPORT_COLUMNS)
            ),
        )
    if len(rows) > MAX_IMPORT_ROWS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Too many rows, import at most {MAX_IMPORT_ROWS} at a time."
            ),
        )
    return _process_import_rows(rows, db=db, business_id=user.business_id)


def _process_import_rows(
    rows: list[dict], db: Session, business_id: str
) -> schema.CustomerImportResult:
    created = 0
    updated = 0
    skipped = 0
    errors: list[str] = []
    now = datetime.now(timezone.utc)
    label_keys = ("party_name", "tin", "email")

    for index, raw_row in enumerate(rows, start=1):
        payload_raw = normalize_row(raw_row, CUSTOMER_FIELDS)
        try:
            parsed = schema.CustomerCreate(**payload_raw)
        except ValidationError as exc:
            # A rule violation in a user spreadsheet is a normal outcome, so
            # report one concise line and never a traceback.
            logging.exception("Unexpected error")
            detail = format_validation_error(exc)
            label = row_label(index, raw_row, label_keys)
            logger.info(
                "customer import row skipped (validation): %s: %s",
                label,
                detail,
            )
            skipped += 1
            errors.append(f"{label}: {detail}")
            continue
        except Exception as exc:
            logging.exception("Unexpected error")
            label = row_label(index, raw_row, label_keys)
            logger.warning(
                "customer import row skipped (unparseable): %s: %s",
                label,
                exc,
            )
            skipped += 1
            errors.append(f"{label}: could not be parsed")
            continue

        data = parsed.model_dump()
        try:
            existing = _find_by_tin(db, business_id, data.get("tin"))
            if existing is not None:
                _apply_payload(existing, data)
                existing.is_active = True
                db.commit()
                updated += 1
            else:
                customer = Customer(
                    business_id=business_id, is_active=True, **data
                )
                customer.created_at = customer.created_at or now
                db.add(customer)
                db.commit()
                created += 1
        except Exception as exc:
            db.rollback()
            label = row_label(index, raw_row, label_keys)
            logger.exception(
                "customer import row skipped (write failed): %s", label
            )
            skipped += 1
            errors.append(f"{label}: could not be saved")

    return schema.CustomerImportResult(
        created=created,
        updated=updated,
        skipped=skipped,
        errors=errors[:100],
    )


@router.post("/bulk-delete")
def bulk_delete_customers(
    body: schema.CustomerBulkAction,
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Session = Depends(get_db),
):
    """Deactivate by default, ``hard=true`` removes the rows permanently."""
    user = get_current_user_obj(token, db)
    ids = list(dict.fromkeys(body.ids))
    if not ids:
        raise HTTPException(
            status_code=400, detail="Select at least one customer to delete."
        )
    customers = _scoped(db, user.business_id).filter(Customer.id.in_(ids)).all()
    now = datetime.now(timezone.utc)
    deleted = 0
    for customer in customers:
        if body.hard:
            db.delete(customer)
        elif customer.is_active:
            customer.is_active = False
            customer.updated_at = now
        deleted += 1
    db.commit()
    return {
        "deleted": deleted,
        "requested": len(ids),
        "mode": "hard" if body.hard else "soft",
    }


@router.post("/bulk-activate")
def bulk_activate_customers(
    body: schema.CustomerBulkAction,
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Session = Depends(get_db),
):
    user = get_current_user_obj(token, db)
    ids = list(dict.fromkeys(body.ids))
    if not ids:
        raise HTTPException(
            status_code=400, detail="Select at least one customer to restore."
        )
    customers = _scoped(db, user.business_id).filter(Customer.id.in_(ids)).all()
    now = datetime.now(timezone.utc)
    restored = 0
    for customer in customers:
        if not customer.is_active:
            customer.is_active = True
            customer.updated_at = now
        restored += 1
    db.commit()
    return {"activated": restored, "requested": len(ids)}


@router.post("/{id}/restore", response_model=schema.CustomerOut)
def restore_customer(
    id: int,
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Session = Depends(get_db),
):
    user = get_current_user_obj(token, db)
    customer = _get_owned(db, id, user.business_id)
    if not customer.is_active:
        customer.is_active = True
        customer.updated_at = datetime.now(timezone.utc)
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
    _apply_payload(customer, data.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(customer)
    return customer


@router.delete("/{id}", response_model=schema.CustomerOut)
def delete_customer(
    id: int,
    token: Annotated[str, Depends(oauth2_scheme)],
    *,
    db: Session = Depends(get_db),
    hard: bool = False,
):
    """Deactivate the customer (soft delete). ``?hard=true`` removes the row."""
    hard = bool(_coerce_bool(hard, False))
    user = get_current_user_obj(token, db)
    customer = _get_owned(db, id, user.business_id)
    if hard:
        snapshot = schema.CustomerOut.model_validate(customer)
        db.delete(customer)
        db.commit()
        return snapshot
    customer.is_active = False
    customer.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(customer)
    return customer
