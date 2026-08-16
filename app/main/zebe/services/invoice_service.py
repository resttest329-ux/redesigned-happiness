import io
import re
import base64
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

import qrcode

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from utils.models import InvoiceLog, IRNSequence

TAX_RATE = 0.075

#: FIRS/NRS always reports VAT in Naira, whatever the document currency is.
#: PASCA requires it on every invoice and expects it camelCased on the wire
#: (``taxCurrencyCode``) — see :class:`utils.schema.InvoiceSchema`.
TAX_CURRENCY_CODE = "NGN"


# ---------------------------------------------------------------------------
# Official unit codes (UN/ECE Recommendation 20 subset accepted by FIRS)
# ---------------------------------------------------------------------------
#: FIRS requires the invoice line ``price.price_unit`` to be a short official
#: 2-3 character UN/ECE code, never free text. There is deliberately **no**
#: legacy alias table: unmappable input falls back to :data:`DEFAULT_UNIT_CODE`
#: on the assembly path and is rejected outright by the request schemas.
UNIT_CODES: dict[str, str] = {
    "EA": "Each",
    "KGM": "Kilogram",
    "MTR": "Metre",
    "LTR": "Litre",
    "MTK": "Square metre",
    "MTQ": "Cubic metre",
    "HUR": "Hour",
    "DAY": "Day",
    "BOX": "Box",
    "BAG": "Bag",
    "BTL": "Bottle",
    "CTN": "Carton",
    "SET": "Set",
}

VALID_UNIT_CODES: frozenset[str] = frozenset(UNIT_CODES)

#: The single official default unit code ("each").
DEFAULT_UNIT_CODE = "EA"

#: Readability alias used by the invoice assembly path.
DEFAULT_PRICE_UNIT = DEFAULT_UNIT_CODE

_UNIT_CODE_RE = re.compile(r"^[A-Z0-9]{2,3}$")
_PREFERRED_UNIT_ORDER = ["EA", "KGM", "LTR", "MTR", "HUR", "DAY"]


def sorted_unit_codes() -> list[str]:
    """Codes in a stable order (common first), for options and messages."""
    rest = sorted(c for c in VALID_UNIT_CODES if c not in _PREFERRED_UNIT_ORDER)
    return [c for c in _PREFERRED_UNIT_ORDER if c in VALID_UNIT_CODES] + rest


def unit_code_options() -> list[dict[str, str]]:
    """Lookup-friendly ``[{"code": ..., "name": ...}]`` payload."""
    return [
        {"code": code, "name": UNIT_CODES[code]} for code in sorted_unit_codes()
    ]


def unit_code_label(code: object) -> str:
    return UNIT_CODES.get(str(code or "").strip().upper(), "")


def normalize_unit_code(value: object) -> str | None:
    """Return the official code for ``value``, or ``None`` when invalid."""
    if value is None:
        return None
    raw = " ".join(str(value).strip().upper().split())
    if not raw:
        return None
    if raw in VALID_UNIT_CODES:
        return raw
    compact = raw.replace(" ", "")
    if compact in VALID_UNIT_CODES:
        return compact
    return None


def is_valid_unit_code(value: object) -> bool:
    raw = "" if value is None else str(value).strip().upper()
    return bool(_UNIT_CODE_RE.match(raw)) and raw in VALID_UNIT_CODES


def coerce_unit_code(value: object, default: str = DEFAULT_UNIT_CODE) -> str:
    """Best-effort normalization used on assembly paths (never raises)."""
    return normalize_unit_code(value) or default


def validate_unit_code(value: object) -> str:
    """Strict normalization used by request schemas.

    Raises:
        ValueError: when the value is not an official unit code.
    """
    code = normalize_unit_code(value)
    if code is None:
        raise ValueError(
            "price_unit must be an official 2-3 character unit code "
            f"(one of: {', '.join(sorted_unit_codes())})."
        )
    return code


# ---------------------------------------------------------------------------
# IRN generation / reservation
# ---------------------------------------------------------------------------
#: The FIRS IRN pattern is ``INV{sequence}-{ServiceID}-{YYYYMMDD}``. The
#: sequence is owned by the server: persisted per (business_id, date_segment)
#: in ``irn_sequence``, floored by the highest sequence already present in
#: ``invoice_log``, and advanced past any local collision.
IRN_MIN_SEQUENCE = 3180
IRN_MAX_LENGTH = 50
MAX_COLLISION_PROBES = 500

IRN_RE = re.compile(r"^INV(\d+)-([A-Z0-9]{1,12})-(\d{8})$")


class IRNError(ValueError):
    """Raised for malformed input while building or reserving an IRN."""


def normalize_service_segment(service_id: str | None) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]", "", service_id or "")
    return cleaned.upper()[:12] or "SERVICE0"


def date_segment_for(issue_date: str | None) -> str:
    """Convert an ``YYYY-MM-DD`` issue date to the IRN ``YYYYMMDD`` segment."""
    raw = (issue_date or "").strip()
    if not raw:
        raise IRNError("issue_date is required to build an IRN.")
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y%m%d")
        except ValueError:
            continue
    raise IRNError("issue_date must be a valid YYYY-MM-DD date.")


def parse_irn(irn: str | None) -> tuple[int, str, str] | None:
    """Return ``(sequence, service_segment, date_segment)`` or ``None``."""
    if not irn:
        return None
    m = IRN_RE.match(str(irn).strip().upper())
    if not m:
        return None
    try:
        sequence = int(m.group(1))
    except ValueError:
        return None
    return sequence, m.group(2), m.group(3)


def build_irn(sequence: int, service_segment: str, date_segment: str) -> str:
    irn = f"INV{sequence}-{service_segment}-{date_segment}"
    if len(irn) > IRN_MAX_LENGTH:
        raise IRNError(f"Generated IRN exceeds {IRN_MAX_LENGTH} characters.")
    return irn


def irn_matches_issue_date(irn: str | None, issue_date: str | None) -> bool:
    parsed = parse_irn(irn)
    if not parsed:
        return False
    try:
        return parsed[2] == date_segment_for(issue_date)
    except IRNError:
        logger.exception("irn_matches_issue_date: bad issue_date")
        return False


def _max_logged_sequence(db: Session, business_id: str) -> int:
    """Highest ``INV{n}`` sequence already recorded for this business."""
    highest = 0
    try:
        rows = (
            db.query(InvoiceLog.irn)
            .filter(InvoiceLog.business_id == business_id)
            .all()
        )
    except Exception:
        logger.exception("_max_logged_sequence: invoice log scan failed")
        return 0
    for (irn,) in rows:
        parsed = parse_irn(irn)
        if parsed and parsed[0] > highest:
            highest = parsed[0]
    return highest


def _taken_irns(db: Session, business_id: str, date_segment: str) -> set[str]:
    try:
        rows = (
            db.query(InvoiceLog.irn)
            .filter(
                InvoiceLog.business_id == business_id,
                InvoiceLog.irn.like(f"%-{date_segment}"),
            )
            .all()
        )
    except Exception:
        logger.exception("_taken_irns: invoice log scan failed")
        return set()
    return {(irn or "").strip().upper() for (irn,) in rows}


def _irn_sequence_row(
    db: Session, business_id: str, date_segment: str
) -> IRNSequence | None:
    return (
        db.query(IRNSequence)
        .filter(
            IRNSequence.business_id == business_id,
            IRNSequence.date_segment == date_segment,
        )
        .first()
    )


def peek_next_irn(
    db: Session,
    *,
    business_id: str,
    service_id: str | None,
    issue_date: str,
    minimum: int = 0,
) -> tuple[str, int]:
    """Compute the next IRN without persisting the reservation."""
    date_segment = date_segment_for(issue_date)
    service_segment = normalize_service_segment(service_id)
    row = _irn_sequence_row(db, business_id, date_segment)
    floor = max(
        IRN_MIN_SEQUENCE - 1,
        row.last_sequence if row else 0,
        _max_logged_sequence(db, business_id),
        int(minimum or 0),
    )
    taken = _taken_irns(db, business_id, date_segment)
    candidate = floor + 1
    for _ in range(MAX_COLLISION_PROBES):
        irn = build_irn(candidate, service_segment, date_segment)
        if irn not in taken:
            return irn, candidate
        candidate += 1
    raise IRNError(
        "Could not find a free IRN sequence for today — please contact support."
    )


def reserve_next_irn(
    db: Session,
    *,
    business_id: str,
    service_id: str | None,
    issue_date: str,
    minimum: int = 0,
) -> tuple[str, int]:
    """Reserve and persist the next IRN sequence for a business/day."""
    date_segment = date_segment_for(issue_date)
    irn, sequence = peek_next_irn(
        db,
        business_id=business_id,
        service_id=service_id,
        issue_date=issue_date,
        minimum=minimum,
    )
    now = datetime.now(timezone.utc)
    row = _irn_sequence_row(db, business_id, date_segment)
    if row is None:
        row = IRNSequence(
            business_id=business_id,
            date_segment=date_segment,
            last_sequence=sequence,
            updated_at=now,
        )
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            logger.exception("reserve_next_irn: concurrent insert, retrying")
            db.rollback()
            return reserve_next_irn(
                db,
                business_id=business_id,
                service_id=service_id,
                issue_date=issue_date,
                minimum=sequence,
            )
    else:
        if sequence > row.last_sequence:
            row.last_sequence = sequence
        row.updated_at = now
        db.commit()
    logger.info(
        "Reserved IRN sequence %s for business=***%s date=%s",
        sequence,
        (business_id or "")[-4:],
        date_segment,
    )
    return irn, sequence


#: NRS `invoice_kind` values. Derived, never asked for.
INVOICE_KIND_B2B = "B2B"
INVOICE_KIND_B2C = "B2C"

#: NRS `payment_status` on creation is always PENDING; later transitions go
#: through the dedicated status-update endpoint, never through assembly.
INITIAL_PAYMENT_STATUS = "PENDING"

_IRN_RE = re.compile(r"^INV\d+-[A-Z0-9]{1,12}-(\d{8})$")
_TIN_RE = re.compile(r"^\d{8}-\d{4}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_HSN_RE = re.compile(r"^\d{4}\.\d{2}$")
_ISIC_RE = re.compile(r"^\d{4}$")

AMENDMENT_INVOICE_TYPE_CODES = {"380", "384", "385"}
_TOTAL_TOLERANCE = 0.01


def derive_invoice_kind(wizard: dict) -> str:
    """Derive the NRS ``invoice_kind`` from the customer identity.

    A customer TIN means a business counterparty (``B2B``). ``B2C`` is only
    ever produced if a no-TIN customer path exists — today every invoice
    requires a customer TIN, so this is defensive rather than user-facing.
    """
    if not isinstance(wizard, dict):
        return INVOICE_KIND_B2B
    tin = str(wizard.get("customer_tin") or "").strip()
    return INVOICE_KIND_B2B if tin else INVOICE_KIND_B2C


def derive_tax_currency_code(wizard: dict | None = None) -> str:
    """Derive the NRS ``taxCurrencyCode``. Always NGN, never user input."""
    return TAX_CURRENCY_CODE


def derive_tax_point_date(issue_date) -> str | None:
    """Derive the NRS/Peppol ``tax_point_date`` (BT-7) from the issue date."""
    raw = str(issue_date or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _safe_float(val, default=0.0):
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _adjusted_line_extension(line: dict) -> float:
    qty = _safe_float(line.get("invoiced_quantity", 0))
    unit_price = _safe_float(line.get("price_amount", 0))
    base_amount = qty * unit_price
    discount_amount = _safe_float(line.get("discount_amount"))
    discount_rate = _safe_float(line.get("discount_rate"))
    fee_amount = _safe_float(line.get("fee_amount"))
    fee_rate = _safe_float(line.get("fee_rate"))
    discount = (
        discount_amount
        if discount_amount
        else (base_amount * discount_rate / 100)
    )
    fee = fee_amount if fee_amount else (base_amount * fee_rate / 100)
    return base_amount - discount + fee


def compute_totals(lines: list[dict]) -> dict:
    taxable_amount = sum(_adjusted_line_extension(line) for line in lines)
    tax_total_amount = taxable_amount * TAX_RATE
    return {
        "line_extension_amount": taxable_amount,
        "tax_amount": tax_total_amount,
        "tax_exclusive_amount": taxable_amount,
        "tax_inclusive_amount": taxable_amount + tax_total_amount,
        "payable_amount": taxable_amount + tax_total_amount,
    }


def build_invoice_schema(wizard: dict, business_id: str) -> dict:
    def get(key, default=None):
        return wizard.get(key, default)

    def party(prefix: str) -> dict:
        postal = {
            "street_name": get(f"{prefix}_street_name"),
            "city_name": get(f"{prefix}_city_name"),
            "postal_zone": get(f"{prefix}_postal_zone"),
            "country": get(f"{prefix}_country"),
            "state": get(f"{prefix}_state"),
        }
        # LGA stays stored on the profile / customer record, but empty optional
        # values are omitted from the outbound payload (NRS rejects blanks).
        lga = str(get(f"{prefix}_lga") or "").strip()
        if lga:
            postal["lga"] = lga
        return {
            "tin": get(f"{prefix}_tin"),
            "party_name": get(f"{prefix}_party_name"),
            "email": get(f"{prefix}_email"),
            "telephone": get(f"{prefix}_telephone"),
            "postal_address": postal,
        }

    supplier = party("supplier")
    customer = party("customer")

    invoice_lines = []
    lines = wizard.get("step3", {}).get("lines", [])
    for line in lines:
        hsn_code = line.get("hsn_code") or None
        product_category = (
            (line.get("product_category") or line.get("name") or None)
            if hsn_code
            else None
        )
        isic_code = line.get("isic_code") or None
        service_category = (
            (line.get("service_category") or line.get("name") or None)
            if isic_code
            else None
        )

        item_dict = {"name": line.get("name")}
        desc = line.get("description")
        if desc:
            item_dict["description"] = desc
        sku = line.get("sellers_item_identification")
        if sku:
            item_dict["sellers_item_identification"] = sku

        line_dict = {
            "item": item_dict,
            "price": {
                "price_amount": _safe_float(line.get("price_amount", 0)),
                "price_unit": coerce_unit_code(
                    line.get("price_unit"), DEFAULT_PRICE_UNIT
                ),
                "base_quantity": max(
                    _safe_float(line.get("base_quantity", ""), 1.0), 1.0
                ),
            },
            "hsn_code": hsn_code,
            "product_category": product_category,
            "invoiced_quantity": _safe_float(line.get("invoiced_quantity", 0)),
            "line_extension_amount": _adjusted_line_extension(line),
            "isic_code": isic_code,
            "service_category": service_category,
        }
        disc_rate = _safe_float(line.get("discount_rate"))
        if disc_rate:
            line_dict["discount_rate"] = disc_rate
        disc_amt = _safe_float(line.get("discount_amount"))
        if disc_amt:
            line_dict["discount_amount"] = disc_amt
        fee_rate = _safe_float(line.get("fee_rate"))
        if fee_rate:
            line_dict["fee_rate"] = fee_rate
        fee_amt = _safe_float(line.get("fee_amount"))
        if fee_amt:
            line_dict["fee_amount"] = fee_amt
        invoice_lines.append(line_dict)

    computed = wizard.get("computed", {})
    tax_total = [
        {
            "tax_amount": computed.get("tax_amount", 0),
            "tax_subtotal": [
                {
                    "taxable_amount": computed.get("tax_exclusive_amount", 0),
                    "tax_amount": computed.get("tax_amount", 0),
                    "tax_category": {
                        "id": "STANDARD_VAT",
                        "percent": TAX_RATE * 100,
                    },
                }
            ],
        }
    ]

    legal_monetary_total = {
        "line_extension_amount": computed.get("line_extension_amount", 0),
        "tax_exclusive_amount": computed.get("tax_exclusive_amount", 0),
        "tax_inclusive_amount": computed.get("tax_inclusive_amount", 0),
        "payable_amount": computed.get("payable_amount", 0),
    }

    result = {
        "irn": (get("irn") or "").upper(),
        # business_id must be passed through untouched (FIRS templates are
        # registered against the strictly lowercase UUID).
        "business_id": (business_id or "").strip(),
        "issue_date": get("issue_date"),
        "issue_time": datetime.now().strftime("%H:%M:%S"),
        "due_date": get("due_date") or None,
        "invoice_type_code": get("invoice_type_code"),
        # Derived NRS/PASCA fields — never collected from the user.
        "invoice_kind": derive_invoice_kind(wizard),
        "tax_point_date": derive_tax_point_date(get("issue_date")),
        "payment_status": INITIAL_PAYMENT_STATUS,
        "document_currency_code": get("document_currency_code"),
        # PASCA requires the tax currency on every invoice; it is derived, not
        # collected, and is serialized as ``taxCurrencyCode``.
        "tax_currency_code": derive_tax_currency_code(wizard),
        "payment_means": [
            {
                "payment_means_code": get("payment_means_code"),
                "payment_due_date": get("due_date") or get("issue_date"),
            }
        ]
        if get("payment_means_code")
        else [],
        "accounting_customer_party": customer,
        "accounting_supplier_party": supplier,
        "tax_total": tax_total,
        "legal_monetary_total": legal_monetary_total,
        "invoice_line": invoice_lines,
    }

    br_irn = get("billing_reference_irn")
    br_date = get("billing_reference_issue_date")
    if br_irn and br_date:
        result["billing_reference"] = [
            {"irn": br_irn.upper(), "issue_date": br_date}
        ]

    logger.info(
        "Invoice built [irn=%s bus=%s kind=%s lines=%s amt=%s]",
        result.get("irn", ""),
        (result.get("business_id") or "")[-4:],
        result.get("invoice_kind", ""),
        len(result.get("invoice_line", [])),
        result.get("legal_monetary_total", {}).get("payable_amount", 0),
    )
    return result


def generate_qr_b64(irn: str, amount: float, date: str) -> str:
    payload = f"IRN:{irn}|AMT:{amount}|DATE:{date}"
    img = qrcode.make(payload)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return base64.b64encode(buffer.read()).decode("utf-8")


def _validate_irn(irn: str, errors: list[str]) -> None:
    if not irn:
        errors.append("IRN is required.")
        return
    m = _IRN_RE.match(irn.strip().upper())
    if not m:
        errors.append(
            "IRN must follow the FIRS pattern INV{sequence}-{ServiceID}-{YYYYMMDD}."
        )
        return
    try:
        datetime.strptime(m.group(1), "%Y%m%d")
    except ValueError:
        errors.append("IRN date segment must be a valid date in YYYYMMDD form.")


def _validate_party(role: str, wizard: dict, errors: list[str]) -> None:
    prefix = f"{role}_"
    name = (wizard.get(f"{prefix}party_name") or "").strip()
    tin = (wizard.get(f"{prefix}tin") or "").strip()
    email = (wizard.get(f"{prefix}email") or "").strip()
    label = role.title()
    if not name:
        errors.append(f"{label} party name is required.")
    if not tin:
        errors.append(f"{label} TIN is required.")
    elif not _TIN_RE.match(tin):
        errors.append(
            f"{label} TIN must follow FIRS format NNNNNNNN-NNNN (e.g. 12345678-0001)."
        )
    if not email:
        errors.append(f"{label} email is required.")
    elif not _EMAIL_RE.match(email):
        errors.append(f"{label} email is not a valid address.")
    for fld, fld_label in (
        ("street_name", "street"),
        ("city_name", "city"),
        ("country", "country"),
        ("state", "state"),
    ):
        if not (wizard.get(f"{prefix}{fld}") or "").strip():
            errors.append(f"{label} {fld_label} is required.")


def _validate_line(idx: int, line: dict, errors: list[str]) -> None:
    if not isinstance(line, dict):
        errors.append(f"Line {idx}: invalid line payload.")
        return
    name = (line.get("name") or "").strip()
    if not name:
        errors.append(f"Line {idx}: item name is required.")

    hsn = (line.get("hsn_code") or "").strip()
    isic = (line.get("isic_code") or "").strip()
    if hsn and isic:
        errors.append(
            f"Line {idx}: a line must be either a product (HS code) or a service (ISIC code), not both."
        )
    elif not hsn and not isic:
        errors.append(
            f"Line {idx}: either an HS code (product) or ISIC code (service) is required."
        )
    else:
        if hsn and not _HSN_RE.match(hsn):
            errors.append(
                f"Line {idx}: HS code must use FIRS format XXXX.XX (e.g. 1006.10)."
            )
        if isic and not _ISIC_RE.match(isic):
            errors.append(
                f"Line {idx}: ISIC code must be exactly 4 digits (e.g. 0112)."
            )

    try:
        qty = float(line.get("invoiced_quantity", 0) or 0)
    except (TypeError, ValueError):
        errors.append(f"Line {idx}: quantity must be numeric.")
        qty = 0.0
    if qty <= 0:
        errors.append(f"Line {idx}: quantity must be greater than zero.")

    try:
        price = float(line.get("price_amount", 0) or 0)
    except (TypeError, ValueError):
        errors.append(f"Line {idx}: unit price must be numeric.")
        price = 0.0
    if price <= 0:
        errors.append(f"Line {idx}: unit price must be greater than zero.")

    price_unit_raw = line.get("price_unit")
    if price_unit_raw is not None and str(price_unit_raw).strip() != "":
        if normalize_unit_code(price_unit_raw) is None:
            errors.append(
                f"Line {idx}: price unit '{price_unit_raw}' is not an official "
                f"unit code (expected one of: {', '.join(sorted_unit_codes())})."
            )

    base_qty_raw = line.get("base_quantity")
    if base_qty_raw is not None and str(base_qty_raw).strip() != "":
        try:
            base_qty_val = float(base_qty_raw)
            if base_qty_val == 0.0:
                errors.append(
                    f"Line {idx}: base quantity must be greater than zero."
                )
            elif base_qty_val < 0.0:
                errors.append(
                    f"Line {idx}: base quantity must be greater than zero."
                )
        except (TypeError, ValueError):
            errors.append(f"Line {idx}: base quantity must be numeric.")
    else:
        pass


def validate_wizard(wizard: dict) -> list[str]:
    errors: list[str] = []
    if not isinstance(wizard, dict):
        return ["Wizard payload is missing or malformed."]

    irn = (wizard.get("irn") or "").strip()
    _validate_irn(irn, errors)

    issue_date = (wizard.get("issue_date") or "").strip()
    if not issue_date:
        errors.append("Issue date is required.")
    else:
        try:
            datetime.strptime(issue_date, "%Y-%m-%d")
        except ValueError:
            errors.append("Issue date must be a valid YYYY-MM-DD date.")

    due_date = (wizard.get("due_date") or "").strip()
    if due_date:
        try:
            d_due = datetime.strptime(due_date, "%Y-%m-%d")
            if issue_date:
                try:
                    d_issue = datetime.strptime(issue_date, "%Y-%m-%d")
                    if d_due < d_issue:
                        errors.append(
                            "Due date cannot be earlier than the issue date."
                        )
                except ValueError:
                    pass
        except ValueError:
            errors.append("Due date must be a valid YYYY-MM-DD date.")

    if irn and issue_date:
        m = _IRN_RE.match(irn.strip().upper())
        if m:
            try:
                expected = datetime.strptime(issue_date, "%Y-%m-%d").strftime(
                    "%Y%m%d"
                )
                if m.group(1) != expected:
                    errors.append(
                        "The IRN date segment must match the invoice issue "
                        f"date ({expected}). Regenerate the IRN after "
                        "changing the issue date."
                    )
            except ValueError:
                pass

    inv_type = (wizard.get("invoice_type_code") or "").strip()
    if not inv_type:
        errors.append("Invoice type is required.")

    if inv_type in AMENDMENT_INVOICE_TYPE_CODES:
        br_irn = (wizard.get("billing_reference_irn") or "").strip()
        br_date = (wizard.get("billing_reference_issue_date") or "").strip()
        if not br_irn:
            errors.append(
                f"Original invoice IRN is required for invoice type {inv_type} "
                "(credit note / debit note / self-billed)."
            )
        if not br_date:
            errors.append(
                f"Original invoice issue date is required for invoice type {inv_type}."
            )
        else:
            try:
                d_br = datetime.strptime(br_date, "%Y-%m-%d")
                if issue_date:
                    try:
                        d_issue = datetime.strptime(issue_date, "%Y-%m-%d")
                        if d_br > d_issue:
                            errors.append(
                                "Original invoice date cannot be after this invoice's issue date."
                            )
                    except ValueError:
                        pass
            except ValueError:
                errors.append(
                    "Billing reference issue date must be a valid YYYY-MM-DD date."
                )

    if not (wizard.get("document_currency_code") or "").strip():
        errors.append("Document currency is required.")
    if not (wizard.get("payment_means_code") or "").strip():
        errors.append("Payment means is required.")

    _validate_party("supplier", wizard, errors)
    _validate_party("customer", wizard, errors)

    lines = (wizard.get("step3", {}) or {}).get("lines", []) or []
    if not lines:
        errors.append("At least one invoice line is required.")
    else:
        for i, line in enumerate(lines, start=1):
            _validate_line(i, line, errors)

    return errors


def validate_totals_consistency(
    computed: dict, lines: list, currency: str = "NGN"
) -> list[str]:
    errors: list[str] = []
    try:
        expected_subtotal = sum(_adjusted_line_extension(l) for l in lines)
        expected_tax = expected_subtotal * TAX_RATE
        expected_payable = expected_subtotal + expected_tax
        sub = float(computed.get("tax_exclusive_amount", 0) or 0)
        tax = float(computed.get("tax_amount", 0) or 0)
        pay = float(computed.get("payable_amount", 0) or 0)
        line_ext = float(computed.get("line_extension_amount", 0) or 0)
        tol = _TOTAL_TOLERANCE

        if abs(sub - expected_subtotal) > tol:
            errors.append(
                f"Subtotal {sub:.2f} does not match sum of line extensions "
                f"{expected_subtotal:.2f}."
            )
        if abs(line_ext - expected_subtotal) > tol:
            errors.append(
                f"Line extension total {line_ext:.2f} does not match expected "
                f"{expected_subtotal:.2f}."
            )
        if abs(tax - expected_tax) > tol:
            errors.append(
                f"Tax {tax:.2f} does not match expected VAT {expected_tax:.2f} "
                f"({TAX_RATE * 100:.1f}% of subtotal)."
            )
        if abs(pay - expected_payable) > tol:
            errors.append(
                f"Payable {pay:.2f} does not match subtotal + tax "
                f"{expected_payable:.2f}."
            )
        if pay < 0 or sub < 0:
            errors.append("Monetary totals cannot be negative.")
    except Exception:
        logger.exception("validate_totals_consistency failed")
        errors.append("Could not validate monetary totals.")
    return errors
