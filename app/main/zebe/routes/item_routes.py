"""CRUD + import routes for business-scoped catalog items/services."""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timezone
from typing import Annotated, Any, Iterable, Optional

from typing import Annotated

from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth import oauth2_scheme
from deps import get_current_user_obj, get_db
from utils import schema
from utils.models import Item
from utils.pagination import apply_search, paginate_query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/items", tags=["Items & Services"])

# ---- Import limits -------------------------------------------------------
# Cap the raw upload size so a malicious/misconfigured client cannot exhaust
# server memory or disk. FastAPI's UploadFile is a SpooledTemporaryFile that
# spills to disk beyond ~1MB, so we combine that with a hard byte cap and a
# per-request row cap.
MAX_IMPORT_BYTES = 10 * 1024 * 1024  # 10 MiB
MAX_IMPORT_ROWS = 10_000
CSV_READ_CHUNK_BYTES = 64 * 1024

_CSV_MIME = {"text/csv", "application/csv", "application/vnd.ms-excel"}
_XLSX_MIME = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/octet-stream",
}


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _row_to_payload(row: dict) -> dict:
    """Normalise a raw CSV/Excel dict into the ItemCreate schema shape.

    - Keys are lowercased and stripped so 'SKU', ' sku ', 'Sku' all map.
    - Empty strings become None so Pydantic optional validation kicks in.
    - Only known fields are forwarded — unknown columns are silently ignored.
    """
    known = {
        "sku",
        "name",
        "description",
        "hsn_code",
        "hsn_category",
        "isic_code",
        "isic_category",
        "unit_price",
        "price_unit",
    }
    out: dict = {}
    for raw_key, raw_val in row.items():
        if raw_key is None:
            continue
        key = str(raw_key).strip().lower().replace(" ", "_")
        if key not in known:
            continue
        if raw_val is None:
            out[key] = None
            continue
        val = str(raw_val).strip()
        if val == "":
            out[key] = None
            continue
        if key == "unit_price":
            try:
                out[key] = float(val)
            except ValueError:
                raise ValueError("unit_price must be a number.")
        else:
            out[key] = val
    return out


def _stringify_pydantic_errors(exc: ValidationError) -> str:
    """Turn a ValidationError into a compact, user-friendly message.

    Deliberately avoids echoing the offending input value so we do not leak
    partial secrets uploaded by mistake in a CSV column.
    """
    parts: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(x) for x in err.get("loc", ()) if x != "__root__")
        msg = err.get("msg", "invalid value")
        parts.append(f"{loc}: {msg}" if loc else msg)
    return "; ".join(parts) or "invalid row"


def _iter_csv_rows(
    upload: UploadFile,
) -> Iterable[dict]:
    """Yield dict rows from an uploaded CSV file, streaming.

    Uses csv.DictReader on a TextIOWrapper wrapping the SpooledTemporaryFile
    exposed by UploadFile.file. This never loads the full file into memory —
    csv reads a line at a time.

    Raises HTTPException(400) on malformed encoding or missing header.
    """
    try:
        upload.file.seek(0)
    except Exception:
        logger.exception("_iter_csv_rows: seek failed")
    try:
        text = io.TextIOWrapper(
            upload.file, encoding="utf-8-sig", newline="", errors="strict"
        )
    except Exception as e:
        logger.exception("_iter_csv_rows: text wrap failed")
        raise HTTPException(
            status_code=400,
            detail="Uploaded file is not valid UTF-8 text.",
        ) from e

    reader = csv.DictReader(text)
    if not reader.fieldnames:
        raise HTTPException(
            status_code=400,
            detail="CSV must include a header row with at least 'sku' and 'name' columns.",
        )
    normalized_headers = {
        (h or "").strip().lower().replace(" ", "_") for h in reader.fieldnames
    }
    if "sku" not in normalized_headers or "name" not in normalized_headers:
        raise HTTPException(
            status_code=400,
            detail="CSV header must include 'sku' and 'name' columns.",
        )

    try:
        for row in reader:
            yield row
    except UnicodeDecodeError as e:
        logger.exception("_iter_csv_rows: unicode decode error mid-stream")
        raise HTTPException(
            status_code=400,
            detail="CSV contains bytes that are not valid UTF-8.",
        ) from e
    except csv.Error as e:
        logger.exception("_iter_csv_rows: csv parse error mid-stream")
        raise HTTPException(
            status_code=400,
            detail=f"CSV parse error: {e}",
        ) from e


def _iter_xlsx_rows(upload: UploadFile) -> Iterable[dict]:
    """Yield dict rows from an uploaded XLSX file using openpyxl read_only mode.

    read_only=True + iter_rows is streaming — cells are yielded row by row
    without loading the whole sheet into memory.
    """
    try:
        from openpyxl import load_workbook
    except ImportError as e:  # pragma: no cover - environment-dependent
        logger.exception("_iter_xlsx_rows: openpyxl not installed")
        raise HTTPException(
            status_code=400,
            detail=(
                "Excel (.xlsx) uploads require the openpyxl package to be "
                "installed on the server. Please upload a CSV instead."
            ),
        ) from e

    try:
        upload.file.seek(0)
    except Exception:
        logger.exception("_iter_xlsx_rows: seek failed")
    try:
        wb = load_workbook(upload.file, read_only=True, data_only=True)
    except Exception as e:
        logger.exception("_iter_xlsx_rows: load_workbook failed")
        raise HTTPException(
            status_code=400,
            detail="Uploaded file is not a valid .xlsx workbook.",
        ) from e

    try:
        ws = wb.active
        if ws is None:
            raise HTTPException(
                status_code=400,
                detail="The workbook has no active sheet.",
            )

        headers: list[str] = []
        row_iter = ws.iter_rows(values_only=True)
        for first in row_iter:
            headers = [
                str(c).strip().lower().replace(" ", "_")
                if c is not None
                else ""
                for c in first
            ]
            break

        if "sku" not in headers or "name" not in headers:
            raise HTTPException(
                status_code=400,
                detail="Excel header must include 'sku' and 'name' columns.",
            )

        for row in row_iter:
            if row is None:
                continue
            if all((c is None or str(c).strip() == "") for c in row):
                continue
            yield {
                headers[i]: row[i] if i < len(row) else None
                for i in range(len(headers))
                if headers[i]
            }
    finally:
        try:
            wb.close()
        except Exception:
            logger.exception("_iter_xlsx_rows: workbook close failed")


def _persist_upload_to_spool(upload: UploadFile) -> int:
    """Enforce MAX_IMPORT_BYTES while draining upload into its spool.

    Returns the total byte count read. Raises HTTP 413 if the cap is exceeded.
    The SpooledTemporaryFile behind UploadFile keeps memory bounded (spills to
    disk after ~1MB), so this preserves streaming semantics.
    """
    total = 0
    try:
        upload.file.seek(0)
    except Exception:
        logger.exception("_persist_upload_to_spool: initial seek failed")
    while True:
        chunk = upload.file.read(CSV_READ_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_IMPORT_BYTES:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"Upload exceeds the maximum allowed size of "
                    f"{MAX_IMPORT_BYTES // (1024 * 1024)} MiB."
                ),
            )
    try:
        upload.file.seek(0)
    except Exception:
        logger.exception("_persist_upload_to_spool: rewind seek failed")
    return total


def _detect_kind(upload: UploadFile) -> str:
    name = (upload.filename or "").lower()
    ctype = (upload.content_type or "").lower()
    if name.endswith(".csv") or ctype in _CSV_MIME:
        return "csv"
    if name.endswith(".xlsx") or ctype in _XLSX_MIME:
        return "xlsx"
    raise HTTPException(
        status_code=400,
        detail="Unsupported file type. Please upload a .csv or .xlsx file.",
    )


# --------------------------------------------------------------------------
# CRUD routes
# --------------------------------------------------------------------------


@router.get("", response_model=schema.ItemPage)
def list_items(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Session = Depends(get_db),
    search: Optional[str] = None,
    kind: Annotated[
        Optional[str],
        Query(
            description=(
                "Filter by classification: 'product' (has HS code) or "
                "'service' (has ISIC code)."
            ),
        ),
    ] = None,
    offset: int = 0,
    limit: int = 50,
):
    user = get_current_user_obj(token, db)
    query = db.query(Item).filter(Item.business_id == user.business_id)
    query = apply_search(query, search, [Item.sku, Item.name, Item.description])
    if kind == "product":
        query = query.filter(Item.hsn_code.isnot(None))
    elif kind == "service":
        query = query.filter(Item.isic_code.isnot(None))
    elif kind is not None:
        raise HTTPException(
            status_code=400,
            detail="`kind` must be either 'product' or 'service'.",
        )
    query = query.order_by(Item.name.asc())
    return paginate_query(query, offset=offset, limit=limit)


@router.post(
    "",
    response_model=schema.ItemOut,
    status_code=status.HTTP_201_CREATED,
)
def create_item(
    data: schema.ItemCreate,
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Session = Depends(get_db),
):
    user = get_current_user_obj(token, db)
    existing = (
        db.query(Item)
        .filter(Item.business_id == user.business_id, Item.sku == data.sku)
        .first()
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=f"An item with SKU '{data.sku}' already exists in your workspace.",
        )
    item = Item(**data.model_dump(), business_id=user.business_id)
    db.add(item)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        logger.exception("create_item: integrity error")
        raise HTTPException(
            status_code=409,
            detail="Could not create item — SKU may already be in use or classification is invalid.",
        )
    db.refresh(item)
    return item


@router.get("/{item_id}", response_model=schema.ItemOut)
def get_item(
    item_id: int,
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Session = Depends(get_db),
):
    user = get_current_user_obj(token, db)
    item = (
        db.query(Item)
        .filter(Item.id == item_id, Item.business_id == user.business_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Item not found.")
    return item


@router.patch("/{item_id}", response_model=schema.ItemOut)
def update_item(
    item_id: int,
    data: schema.ItemUpdate,
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Session = Depends(get_db),
):
    user = get_current_user_obj(token, db)
    item = (
        db.query(Item)
        .filter(Item.id == item_id, Item.business_id == user.business_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Item not found.")

    if data.sku != item.sku:
        clash = (
            db.query(Item)
            .filter(
                Item.business_id == user.business_id,
                Item.sku == data.sku,
                Item.id != item.id,
            )
            .first()
        )
        if clash is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Another item with SKU '{data.sku}' already exists.",
            )

    for field, value in data.model_dump().items():
        setattr(item, field, value)
    item.updated_at = datetime.now(timezone.utc)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        logger.exception("update_item: integrity error")
        raise HTTPException(
            status_code=409,
            detail="Could not update item — SKU may already be in use or classification is invalid.",
        )
    db.refresh(item)
    return item


@router.delete("/{item_id}")
def delete_item(
    item_id: int,
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Session = Depends(get_db),
):
    user = get_current_user_obj(token, db)
    item = (
        db.query(Item)
        .filter(Item.id == item_id, Item.business_id == user.business_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Item not found.")
    db.delete(item)
    db.commit()
    return {"ok": True}


@router.post("/bulk-delete")
def bulk_delete_items(
    body: schema.ItemBulkDelete,
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Session = Depends(get_db),
):
    user = get_current_user_obj(token, db)
    ids = [i for i in (body.ids or []) if isinstance(i, int) and i > 0]
    if not ids:
        raise HTTPException(
            status_code=400,
            detail="Provide at least one item id to delete.",
        )
    # Scope strictly to caller's business to prevent cross-tenant deletion.
    deleted = (
        db.query(Item)
        .filter(Item.business_id == user.business_id, Item.id.in_(ids))
        .delete(synchronize_session=False)
    )
    db.commit()
    return {"ok": True, "deleted": int(deleted), "requested": len(ids)}


# --------------------------------------------------------------------------
# Import: CSV/Excel
# --------------------------------------------------------------------------


def _parse_import_row(
    raw: dict,
) -> tuple[Optional[schema.ItemCreate], Optional[str], Optional[str]]:
    """Parse a single raw row dict into a validated :class:`schema.ItemCreate`.

    Returns a ``(item, sku, error)`` triple:

    * ``item`` — the validated model on success, else ``None``.
    * ``sku`` — the best-effort SKU from the raw row (may be ``None``).
    * ``error`` — a user-facing error message on validation/coercion failure,
      else ``None``. This function NEVER logs tracebacks for expected user
      data errors (Pydantic ValidationError from schema.ItemCreate,
      ValueError from numeric coercion in ``_row_to_payload``). Unexpected
      parse exceptions are still logged and surfaced as a generic message.
    """
    row_sku: Optional[str] = None
    try:
        payload = _row_to_payload(raw)
    except ValueError as ve:
        # Expected: non-numeric unit_price or similar coercion failure.
        # Do not log — this is user data, not a server bug.
        return None, row_sku, str(ve)
    except Exception:
        logger.exception("_parse_import_row: unexpected parse error")
        return None, row_sku, "Unexpected error while parsing this row."

    row_sku = payload.get("sku")
    try:
        return schema.ItemCreate(**payload), row_sku, None
    except ValidationError as ve:
        # Expected: schema-level validation failure. No traceback logging.
        logging.exception("Unexpected error")
        return None, row_sku, _stringify_pydantic_errors(ve)
    except ValueError as ve:
        # Expected: a validator raised ValueError (still user data).
        return None, row_sku, str(ve)
    except Exception:
        logger.exception("_parse_import_row: unexpected schema error")
        return None, row_sku, "Unexpected error while validating this row."


def _upsert_item(
    item_data: schema.ItemCreate,
    *,
    db: Session,
    business_id: str,
) -> tuple[bool, Optional[str]]:
    """Insert or update a single item within an ongoing transaction.

    Returns ``(created, error)``:

    * ``created`` — True if a new row was added, False if an existing row was
      updated in place. Undefined when ``error`` is set.
    * ``error`` — a user-facing message when persistence failed, else
      ``None``. Database failures ARE logged with a traceback (they are
      server-side conditions, not user data errors).
    """
    try:
        existing = (
            db.query(Item)
            .filter(
                Item.business_id == business_id,
                Item.sku == item_data.sku,
            )
            .first()
        )
        if existing is None:
            db.add(Item(**item_data.model_dump(), business_id=business_id))
            return True, None
        for field, value in item_data.model_dump().items():
            setattr(existing, field, value)
        existing.updated_at = datetime.now(timezone.utc)
        return False, None
    except IntegrityError:
        db.rollback()
        logger.exception(
            "_upsert_item: integrity error for sku=%s", item_data.sku
        )
        return False, "Row conflicts with an existing record."
    except Exception:
        db.rollback()
        logger.exception("_upsert_item: db error for sku=%s", item_data.sku)
        return False, "Could not persist this row."


def _process_import_rows(
    rows: Iterable[dict],
    *,
    db: Session,
    business_id: str,
    max_rows: int = MAX_IMPORT_ROWS,
) -> schema.ItemImportResult:
    """Consume an iterator of raw row dicts and upsert them by (business_id, sku).

    Streaming-friendly: never materialises the whole iterable in memory. Each
    row is validated via :func:`_parse_import_row` and, if valid, upserted via
    :func:`_upsert_item`. Commits are batched so the DB transaction log stays
    bounded even on very large imports.

    Expected row-level errors (Pydantic ``ValidationError`` from
    ``schema.ItemCreate`` and ``ValueError`` from numeric coercion) are
    appended to ``result.errors`` and skipped silently — no traceback is
    logged for them. Unexpected parse exceptions and database persistence
    failures are still logged with full stack traces.
    """
    result = schema.ItemImportResult()
    batch = 0
    BATCH_SIZE = 200

    for i, raw in enumerate(rows, start=2):  # row 1 is the header
        result.total_rows += 1
        if result.total_rows > max_rows:
            result.errors.append(
                schema.ItemImportRowError(
                    row=i,
                    sku=None,
                    error=(
                        f"Import truncated: file contains more than the "
                        f"{max_rows} allowed rows."
                    ),
                )
            )
            break

        item_data, row_sku, parse_error = _parse_import_row(raw)
        if parse_error is not None or item_data is None:
            result.errors.append(
                schema.ItemImportRowError(
                    row=i,
                    sku=row_sku,
                    error=parse_error or "Invalid row.",
                )
            )
            result.skipped += 1
            continue

        created, upsert_error = _upsert_item(
            item_data, db=db, business_id=business_id
        )
        if upsert_error is not None:
            batch = 0
            result.errors.append(
                schema.ItemImportRowError(
                    row=i,
                    sku=item_data.sku,
                    error=upsert_error,
                )
            )
            result.skipped += 1
            continue

        if created:
            result.created += 1
        else:
            result.updated += 1

        batch += 1
        if batch >= BATCH_SIZE:
            try:
                db.commit()
            except Exception:
                db.rollback()
                logger.exception(
                    "_process_import_rows: batch commit failed at row=%d", i
                )
                raise HTTPException(
                    status_code=500,
                    detail=(
                        "Import partially failed while saving. Some rows "
                        "may not have been written."
                    ),
                )
            batch = 0

    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("_process_import_rows: final commit failed")
        raise HTTPException(
            status_code=500,
            detail="Import partially failed while saving. Some rows may not have been written.",
        )
    return result


@router.post("/import", response_model=schema.ItemImportResult)
async def import_items(
    token: Annotated[str, Depends(oauth2_scheme)],
    file: UploadFile = File(..., description="A .csv or .xlsx file."),
    db: Session = Depends(get_db),
):
    """Bulk import items from CSV or XLSX.

    Row semantics:
      * Row 1 must be a header. Required columns: `sku`, `name`. At least one
        of `hsn_code` (product) or `isic_code` (service) is required per row.
      * Existing items are matched by (business_id, sku) and updated in place.
        New SKUs are inserted.
      * Rows that fail validation are reported in `errors[]` with the row
        number and a human-readable message. The rest of the import continues.
    """
    user = get_current_user_obj(token, db)

    _persist_upload_to_spool(file)
    kind = _detect_kind(file)

    try:
        if kind == "csv":
            rows_iter = _iter_csv_rows(file)
        else:
            rows_iter = _iter_xlsx_rows(file)
        return _process_import_rows(
            rows_iter,
            db=db,
            business_id=user.business_id,
        )
    except HTTPException:
        # Expected client-facing error (e.g. bad file type, missing header) —
        # re-raise without logging a stack trace.
        logging.exception("Unexpected error")
        raise
    except Exception:
        logger.exception("import_items: unexpected failure")
        raise HTTPException(
            status_code=500,
            detail="Import failed due to an unexpected server error.",
        )
    finally:
        try:
            await file.close()
        except Exception:
            logger.exception("import_items: file close failed")
