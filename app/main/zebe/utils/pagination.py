"""Reusable pagination helpers for zebe list endpoints.

All list endpoints in zebe should route their SQLAlchemy queries through
`paginate_query` so that pagination semantics (offset/limit clamping,
total counts, response shape) stay identical across resources.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Query

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def clamp_pagination(
    offset: Optional[int],
    limit: Optional[int],
    *,
    default_limit: int = DEFAULT_LIMIT,
    max_limit: int = MAX_LIMIT,
) -> tuple[int, int]:
    """Clamp raw offset/limit query params into safe bounds."""
    try:
        off = int(offset) if offset is not None else 0
    except (TypeError, ValueError):
        logger.debug(
            "clamp_pagination: invalid offset=%r, defaulting to 0", offset
        )
        off = 0
    try:
        lim = int(limit) if limit is not None else default_limit
    except (TypeError, ValueError):
        logger.debug(
            "clamp_pagination: invalid limit=%r, defaulting to %d",
            limit,
            default_limit,
        )
        lim = default_limit
    off = max(0, off)
    lim = max(1, min(lim, max_limit))
    return off, lim


def apply_search(
    query: Query, search: Optional[str], columns: Iterable[Any]
) -> Query:
    """ILIKE %search% across the given columns, joined by OR.

    Silently returns the original query when `search` is falsy so callers can
    unconditionally pipe through this helper.
    """
    term = (search or "").strip()
    if not term:
        return query
    like = f"%{term}%"
    return query.filter(or_(*[col.ilike(like) for col in columns]))


def paginate_query(
    query: Query,
    *,
    offset: Optional[int] = 0,
    limit: Optional[int] = DEFAULT_LIMIT,
    default_limit: int = DEFAULT_LIMIT,
    max_limit: int = MAX_LIMIT,
) -> dict:
    """Execute a paginated fetch against a SQLAlchemy query.

    Returns the canonical page envelope: total / offset / limit / items.
    """
    off, lim = clamp_pagination(
        offset, limit, default_limit=default_limit, max_limit=max_limit
    )
    total = query.count()
    items = query.offset(off).limit(lim).all()
    return {"total": total, "offset": off, "limit": lim, "items": items}
