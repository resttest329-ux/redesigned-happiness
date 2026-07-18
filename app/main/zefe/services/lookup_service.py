from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable, Optional

from services import api_client

logger = logging.getLogger(__name__)

CACHE_TTL = 3600

_cache: dict[str, list[dict[str, Any]]] = {}
_cache_ts: dict[str, float] = {}


class LookupServiceError(Exception):
    pass


async def _fetch(key: str, fetcher: Callable[[], Awaitable[list]]) -> list:
    now = time.monotonic()
    if key in _cache and (now - _cache_ts.get(key, 0)) < CACHE_TTL:
        return _cache[key]
    try:
        result = await fetcher()
    except api_client.APIError as e:
        logging.exception("lookup '%s' upstream failure", key)
        raise LookupServiceError(f"API error during lookup '{key}': {e}")
    _cache[key] = result if isinstance(result, list) else []
    _cache_ts[key] = time.monotonic()
    return _cache[key]


async def safe_lookup(coro: Awaitable[list]) -> Optional[list]:
    try:
        return await coro
    except LookupServiceError:
        logging.exception("safe_lookup swallowed LookupServiceError")
        return None


async def get_invoice_types(
    token: str, session_id: Optional[str] = None
) -> list:
    return await _fetch(
        "invoice_types",
        lambda: api_client.get_invoice_types(token, session_id=session_id),
    )


async def get_payment_means(
    token: str, session_id: Optional[str] = None
) -> list:
    return await _fetch(
        "payment_means",
        lambda: api_client.get_payment_means(token, session_id=session_id),
    )


async def get_currencies(token: str, session_id: Optional[str] = None) -> list:
    return await _fetch(
        "currencies",
        lambda: api_client.get_currencies(token, session_id=session_id),
    )


async def get_tax_categories(
    token: str, session_id: Optional[str] = None
) -> list:
    return await _fetch(
        "tax_categories",
        lambda: api_client.get_tax_categories(token, session_id=session_id),
    )


async def get_state_codes(token: str, session_id: Optional[str] = None) -> list:
    return await _fetch(
        "state_codes",
        lambda: api_client.get_state_codes(token, session_id=session_id),
    )


async def get_lga_codes(token: str, session_id: Optional[str] = None) -> list:
    return await _fetch(
        "lga_codes",
        lambda: api_client.get_lga_codes(token, session_id=session_id),
    )


async def get_countries(token: str, session_id: Optional[str] = None) -> list:
    return await _fetch(
        "countries",
        lambda: api_client.get_countries(token, session_id=session_id),
    )


async def get_units_of_measurement(
    token: str, session_id: Optional[str] = None
) -> list:
    return await _fetch(
        "units_of_measurement",
        lambda: api_client.get_units_of_measurement(
            token, session_id=session_id
        ),
    )