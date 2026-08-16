"""Server-side IRN generation / reservation.

The FIRS IRN pattern is ``INV{sequence}-{ServiceID}-{YYYYMMDD}``. Historically
the frontend derived this string by scanning the invoice log, which is racy and
cannot reserve anything. This module owns the whole concern:

* the sequence is persisted per (business_id, date_segment) in ``irn_sequence``
* it is additionally floored by the highest sequence seen in ``invoice_log``
  (safe derivation when the sequence table is empty or was reset)
* candidates that already exist locally are skipped (collision handling)
* ``regenerate`` advances strictly past a caller-supplied IRN
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from utils.models import InvoiceLog, IRNSequence

logger = logging.getLogger(__name__)

#: Staging/production templates were provisioned from this sequence upwards.
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
        logging.exception("Unexpected error")
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


def _sequence_row(
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
    row = _sequence_row(db, business_id, date_segment)
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
    row = _sequence_row(db, business_id, date_segment)
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
