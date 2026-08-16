"""Official FIRS / UN-ECE Recommendation 20 unit-of-measure codes (frontend).

This mirrors the consolidated unit-code helpers in
``zebe/services/invoice_service.py`` so the FastHTML frontend can render
compliant dropdowns and never submit free text such as ``"NGN per 1"``.
The backend remains the authority — it validates every value — but the UI must
only ever offer official 2-3 character codes. Legacy aliases and the legacy
``C62`` code have been removed; ``EA`` ("each") is the single default.
"""

from __future__ import annotations

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

#: Default when nothing usable was supplied. ``EA`` == "each" (NRS/PASCA usage).
DEFAULT_UNIT_CODE = "EA"

#: Stable display order — most common first, then alphabetical.
_PREFERRED_ORDER = ["EA", "KGM", "LTR", "MTR", "HUR", "DAY"]


def sorted_unit_codes() -> list[str]:
    rest = sorted(c for c in VALID_UNIT_CODES if c not in _PREFERRED_ORDER)
    return [c for c in _PREFERRED_ORDER if c in VALID_UNIT_CODES] + rest


def unit_code_options() -> list[tuple[str, str]]:
    """``[(code, label)]`` pairs for a ``<select>``."""
    return [(code, UNIT_CODES[code]) for code in sorted_unit_codes()]


def unit_code_label(code: str) -> str:
    return UNIT_CODES.get((code or "").strip().upper(), "")


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


def coerce_unit_code(value: object, default: str = DEFAULT_UNIT_CODE) -> str:
    """Best-effort normalization for display / submission (never raises)."""
    return normalize_unit_code(value) or default
