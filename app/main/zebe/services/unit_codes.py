"""Official FIRS / UN-ECE Recommendation 20 unit-of-measure codes.

FIRS (via the PASCA / Peppol BIS Billing 3.0 pipeline) requires the invoice
line ``price.price_unit`` field to be a short 2-3 character UN/ECE code, NOT
free text. Legacy Zetamind builds sent values like ``"NGN per 1"`` which the
gateway rejects (or silently mangles), so every code path that produces a
``price_unit`` now funnels through :func:`coerce_unit_code`.

The canonical implementation now lives in :mod:`services.invoice_service` — all
unit-code and IRN helpers were consolidated there. This module is kept only as a
stable import path and simply re-exports them. Only official codes are accepted:
the legacy free-text aliases (``"NGN per 1"``, ``"each"``, …) and the legacy
``C62`` code have been removed, and the single default is ``EA`` ("each").
"""

from __future__ import annotations

from services.invoice_service import (  # noqa: F401  (re-exported API)
    DEFAULT_UNIT_CODE,
    UNIT_CODES,
    VALID_UNIT_CODES,
    coerce_unit_code,
    is_valid_unit_code,
    normalize_unit_code,
    sorted_unit_codes,
    unit_code_label,
    unit_code_options,
    validate_unit_code,
)

__all__ = [
    "DEFAULT_UNIT_CODE",
    "UNIT_CODES",
    "VALID_UNIT_CODES",
    "coerce_unit_code",
    "is_valid_unit_code",
    "normalize_unit_code",
    "sorted_unit_codes",
    "unit_code_label",
    "unit_code_options",
    "validate_unit_code",
]
