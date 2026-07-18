import logging
import time
from typing import Any, Optional
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from utils import schema
from utils.utility import get_request, get_request_app
from auth import oauth2_scheme

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/lookup", tags=["Lookup / Resources"])

_cache: dict[str, Any] = {}
_cache_ts: dict[str, float] = {}
CACHE_TTL = 3600

_search_cache: dict[tuple[str, tuple[tuple[str, str], ...]], list] = {}
_search_cache_ts: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
SEARCH_CACHE_TTL = 600
SEARCH_CACHE_MAX_ENTRIES = 512


def _normalize_search_params(
    params: Optional[dict],
) -> tuple[tuple[str, str], ...]:
    if not params:
        return tuple()
    norm: list[tuple[str, str]] = []
    for k, v in params.items():
        if v is None:
            continue
        s = str(v).strip()
        if s == "":
            continue
        if k == "search":
            s = s.lower()
        norm.append((k, s))
    norm.sort(key=lambda kv: kv[0])
    return tuple(norm)


def _search_cache_get(
    endpoint: str, params_key: tuple[tuple[str, str], ...]
) -> Optional[list]:
    key = (endpoint, params_key)
    return _search_cache.get(key)


def _search_cache_get_fresh(
    endpoint: str, params_key: tuple[tuple[str, str], ...]
) -> Optional[list]:
    key = (endpoint, params_key)
    if key not in _search_cache:
        return None
    if (time.monotonic() - _search_cache_ts.get(key, 0)) >= SEARCH_CACHE_TTL:
        return None
    return _search_cache[key]


def _search_cache_set(
    endpoint: str,
    params_key: tuple[tuple[str, str], ...],
    value: list,
) -> None:
    key = (endpoint, params_key)
    if (
        key not in _search_cache
        and len(_search_cache) >= SEARCH_CACHE_MAX_ENTRIES
    ):
        try:
            oldest_key = min(
                _search_cache_ts, key=lambda k: _search_cache_ts[k]
            )
            _search_cache.pop(oldest_key, None)
            _search_cache_ts.pop(oldest_key, None)
        except ValueError:
            pass
    _search_cache[key] = value
    _search_cache_ts[key] = time.monotonic()


SUPPORTED_INVOICE_TYPE_LABELS = {
    "commercial invoice",
    "credit note",
    "debit note",
    "self billed invoice",
    "factored invoice",
    "statement of account",
}

FALLBACK_INVOICE_TYPES = [
    {"code": "381", "value": "Commercial Invoice"},
    {"code": "380", "value": "Credit Note"},
    {"code": "384", "value": "Debit Note"},
    {"code": "385", "value": "Self Billed Invoice"},
    {"code": "388", "value": "Factored Invoice"},
    {"code": "389", "value": "Statement of Account"},
]


async def _cached_get(key: str, fetcher, endpoint: str):
    now = time.monotonic()
    if key in _cache and (now - _cache_ts.get(key, 0)) < CACHE_TTL:
        return _cache[key]
    try:
        result = await fetcher(endpoint=endpoint)
    except Exception as e:
        logging.exception("shared lookup '%s' upstream failure", key)
        if key in _cache:
            logger.warning(
                "shared lookup '%s' transient failure: %s — serving stale cache",
                key,
                e,
            )
            return _cache[key]
        raise
    _cache[key] = result
    _cache_ts[key] = time.monotonic()
    return result


@router.get("/types-of-invoice", response_model=list[schema.InvoiceTypes])
async def invoice_types(token: Annotated[str, Depends(oauth2_scheme)]):
    endpoint: str = "/api/v1/invoice/resources/invoice-types"
    try:
        result = await _cached_get("invoice_types", get_request, endpoint)
        data = result.get("data", []) or []
        filtered = [
            item
            for item in data
            if isinstance(item, dict)
            and (item.get("value") or "").strip().lower()
            in SUPPORTED_INVOICE_TYPE_LABELS
        ]
        if filtered:
            return filtered
        logger.warning(
            "types-of-invoice: live lookup returned %d rows but none matched "
            "supported semantics; using safe fallback.",
            len(data),
        )
        return FALLBACK_INVOICE_TYPES
    except Exception as e:
        logging.exception("Unexpected error")
        logger.error(
            f"types-of-invoice lookup failed: {e}; using safe fallback"
        )
        return FALLBACK_INVOICE_TYPES


@router.get("/payment-means", response_model=list[schema.PaymentMeans])
async def payment_means(token: Annotated[str, Depends(oauth2_scheme)]):
    endpoint: str = "/api/v1/invoice/resources/payment-means"
    try:
        result = await _cached_get("payment_means", get_request, endpoint)
        return result.get("data", [])
    except Exception as e:
        logging.exception("Unexpected error")
        logger.error(f"payment-means lookup failed: {e}")
        raise HTTPException(
            status_code=502, detail="External lookup API unavailable"
        )


@router.get("/tax-categories", response_model=list[schema.TaxCategoryLookUp])
async def tax_category(token: Annotated[str, Depends(oauth2_scheme)]):
    endpoint: str = "/api/v1/invoice/resources/tax-categories"
    try:
        result = await _cached_get("tax_categories", get_request, endpoint)
        return result.get("data", [])
    except Exception as e:
        logging.exception("Unexpected error")
        logger.error(f"tax-categories lookup failed: {e}")
        raise HTTPException(
            status_code=502, detail="External lookup API unavailable"
        )


@router.get("/get-currency", response_model=list[schema.Currency])
async def get_currency(token: Annotated[str, Depends(oauth2_scheme)]):
    endpoint: str = "/api/v1/invoice/resources/currencies"
    try:
        result = await _cached_get("currencies", get_request, endpoint)
        return result.get("data", [])
    except Exception as e:
        logging.exception("Unexpected error")
        logger.error(f"get-currency lookup failed: {e}")
        raise HTTPException(
            status_code=502, detail="External lookup API unavailable"
        )


@router.get("/product-codes", response_model=list[schema.ProductCodes])
async def get_product_codes(token: Annotated[str, Depends(oauth2_scheme)]):
    endpoint: str = "/api/v1/invoice/resources/hs-codes"
    try:
        result = await _cached_get("product_codes", get_request, endpoint)
        return result.get("data", [])
    except Exception as e:
        logging.exception("Unexpected error")
        logger.error(f"product-codes lookup failed: {e}")
        raise HTTPException(
            status_code=502, detail="External lookup API unavailable"
        )


@router.get("/service-codes", response_model=list[schema.ServiceCode])
async def get_service_codes(token: Annotated[str, Depends(oauth2_scheme)]):
    endpoint: str = "/api/v1/invoice/resources/services-codes"
    try:
        result = await _cached_get("service_codes", get_request, endpoint)
        return result.get("data", [])
    except Exception as e:
        logging.exception("Unexpected error")
        logger.error(f"service-codes lookup failed: {e}")
        raise HTTPException(
            status_code=502, detail="External lookup API unavailable"
        )


@router.get("/lga-codes", response_model=list[schema.LocalGovernment])
async def get_lgas(token: Annotated[str, Depends(oauth2_scheme)]):
    endpoint: str = "/api/v1/invoice/resources/lgas"
    try:
        result = await _cached_get("lga_codes", get_request, endpoint)
        return result.get("data", [])
    except Exception as e:
        logging.exception("Unexpected error")
        logger.error(f"lga-codes lookup failed: {e}")
        raise HTTPException(
            status_code=502, detail="External lookup API unavailable"
        )


@router.get("/state-codes", response_model=list[schema.StateCode])
async def get_states(token: Annotated[str, Depends(oauth2_scheme)]):
    endpoint: str = "/api/v1/invoice/resources/states"
    try:
        result = await _cached_get("state_codes", get_request, endpoint)
        return result.get("data", [])
    except Exception as e:
        logging.exception("Unexpected error")
        logger.error(f"state-codes lookup failed: {e}")
        raise HTTPException(
            status_code=502, detail="External lookup API unavailable"
        )


@router.get("/countries", response_model=list[schema.Country])
async def get_countries(token: Annotated[str, Depends(oauth2_scheme)]):
    endpoint: str = "/api/v1/invoice/resources/countries"
    try:
        result = await _cached_get("countries", get_request, endpoint)
        return result.get("data", [])
    except Exception as e:
        logging.exception("Unexpected error")
        logger.error(f"countries lookup failed: {e}")
        raise HTTPException(
            status_code=502, detail="External lookup API unavailable"
        )


@router.get("/products", response_model=list[schema.ProductSearchItem])
async def get_products(
    token: Annotated[str, Depends(oauth2_scheme)],
    search: Optional[str] = Query(None),
    start: Optional[int] = Query(None),
    length: Optional[int] = Query(None),
    hscode: Optional[str] = Query(None),
):
    endpoint: str = "/api/v1/einvoice/resources/products"
    params = {
        k: v
        for k, v in {
            "search": search,
            "start": start,
            "length": length,
            "hscode": hscode,
        }.items()
        if v is not None
    }
    params_key = _normalize_search_params(params)
    fresh = _search_cache_get_fresh(endpoint, params_key)
    if fresh is not None:
        logger.info(
            "products lookup cache hit (search=%r, items=%d)",
            search,
            len(fresh),
        )
        return fresh
    try:
        result = await get_request_app(endpoint=endpoint, params=params)
        data = result.get("data", []) or []
        _search_cache_set(endpoint, params_key, data)
        logger.info(
            "products lookup live success (search=%r, items=%d)",
            search,
            len(data),
        )
        return data
    except Exception as e:
        logging.exception("Unexpected error")
        stale = _search_cache_get(endpoint, params_key)
        if stale is not None:
            logger.warning(
                "products lookup transient failure (search=%r): %s — "
                "serving stale cache (items=%d)",
                search,
                e,
                len(stale),
            )
            return stale
        logger.warning(
            "products lookup transient failure (search=%r): %s — "
            "no cache available, returning []",
            search,
            e,
        )
        return []


@router.get("/services", response_model=list[schema.ServiceSearchItem])
async def get_services(
    token: Annotated[str, Depends(oauth2_scheme)],
    search: Optional[str] = Query(None),
    start: Optional[int] = Query(None),
    length: Optional[int] = Query(None),
    code: Optional[str] = Query(None),
):
    endpoint: str = "/api/v1/einvoice/resources/services"
    params = {
        k: v
        for k, v in {
            "search": search,
            "start": start,
            "length": length,
            "code": code,
        }.items()
        if v is not None
    }
    params_key = _normalize_search_params(params)
    fresh = _search_cache_get_fresh(endpoint, params_key)
    if fresh is not None:
        logger.info(
            "services lookup cache hit (search=%r, items=%d)",
            search,
            len(fresh),
        )
        return fresh
    try:
        result = await get_request_app(endpoint=endpoint, params=params)
        data = result.get("data", []) or []
        _search_cache_set(endpoint, params_key, data)
        logger.info(
            "services lookup live success (search=%r, items=%d)",
            search,
            len(data),
        )
        return data
    except Exception as e:
        logging.exception("Unexpected error")
        stale = _search_cache_get(endpoint, params_key)
        if stale is not None:
            logger.warning(
                "services lookup transient failure (search=%r): %s — "
                "serving stale cache (items=%d)",
                search,
                e,
                len(stale),
            )
            return stale
        logger.warning(
            "services lookup transient failure (search=%r): %s — "
            "no cache available, returning []",
            search,
            e,
        )
        return []


@router.get("/units-of-measurement")
async def get_units_of_measurement(
    token: Annotated[str, Depends(oauth2_scheme)],
):
    endpoint: str = "/api/v1/einvoice/resources/units-of-measurement"
    try:
        result = await _cached_get(
            "units_of_measurement", get_request_app, endpoint
        )
        raw_rows: list = (
            result if isinstance(result, list) else result.get("data", [])
        )
        normalized = []
        for row in raw_rows:
            if isinstance(row, str):
                normalized.append({"code": row, "name": row})
            elif isinstance(row, dict):
                code = (
                    row.get("code")
                    or row.get("Code")
                    or row.get("value")
                    or row.get("id")
                )
                if not code:
                    continue
                name = (
                    row.get("value")
                    or row.get("name")
                    or row.get("Name")
                    or row.get("description")
                    or row.get("Description")
                    or row.get("label")
                    or row.get("text")
                    or code
                )
                normalized.append({"code": code, "name": name})
        return normalized
    except Exception as e:
        logging.exception("Unexpected error")
        logger.error(f"units-of-measurement lookup failed: {e}")
        raise HTTPException(
            status_code=502, detail="External lookup API unavailable"
        )