"""Official FIRS / UN-ECE Recommendation 20 unit-of-measure codes (frontend).

This mirrors ``zebe/services/unit_codes.py`` so the FastHTML frontend can
render compliant dropdowns and never submit free text such as ``"NGN per 1"``.
The backend remains the authority — it normalizes/validates every value — but
the UI must only ever offer official 2-3 character codes.
"""

from __future__ import annotations

UNIT_CODES: dict[str, str] = {
    "C62": "One (each / piece)",
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

#: Default when nothing usable was supplied. ``C62`` == "one / each".
DEFAULT_UNIT_CODE = "C62"

#: Legacy free text (and common shorthand) mapped onto compliant codes.
LEGACY_UNIT_ALIASES: dict[str, str] = {
    "NGN PER 1": "C62",
    "NGNPER1": "C62",
    "NAIRA PER 1": "C62",
    "NAIRA PER UNIT": "C62",
    "PER UNIT": "C62",
    "PER 1": "C62",
    "EACH": "C62",
    "UNIT": "C62",
    "UNITS": "C62",
    "PIECE": "C62",
    "PIECES": "C62",
    "PCS": "C62",
    "PC": "C62",
    "NO": "C62",
    "ONE": "C62",
    "KG": "KGM",
    "KGS": "KGM",
    "KILO": "KGM",
    "KILOS": "KGM",
    "KILOGRAM": "KGM",
    "KILOGRAMS": "KGM",
    "M": "MTR",
    "METRE": "MTR",
    "METRES": "MTR",
    "METER": "MTR",
    "METERS": "MTR",
    "L": "LTR",
    "LT": "LTR",
    "LITRE": "LTR",
    "LITRES": "LTR",
    "LITER": "LTR",
    "LITERS": "LTR",
    "M2": "MTK",
    "SQM": "MTK",
    "SQ M": "MTK",
    "SQUARE METRE": "MTK",
    "SQUARE METER": "MTK",
    "M3": "MTQ",
    "CBM": "MTQ",
    "CUBIC METRE": "MTQ",
    "CUBIC METER": "MTQ",
    "HR": "HUR",
    "HRS": "HUR",
    "HOUR": "HUR",
    "HOURS": "HUR",
    "DAYS": "DAY",
    "BOXES": "BOX",
    "BAGS": "BAG",
    "BOTTLE": "BTL",
    "BOTTLES": "BTL",
    "CARTON": "CTN",
    "CARTONS": "CTN",
    "SETS": "SET",
}

#: Stable display order — most common first, then alphabetical.
_PREFERRED_ORDER = ["C62", "EA", "KGM", "LTR", "MTR", "HUR", "DAY"]


def sorted_unit_codes() -> list[str]:
    rest = sorted(c for c in VALID_UNIT_CODES if c not in _PREFERRED_ORDER)
    return [c for c in _PREFERRED_ORDER if c in VALID_UNIT_CODES] + rest


def unit_code_options() -> list[tuple[str, str]]:
    """``[(code, label)]`` pairs for a ``<select>``."""
    return [(code, UNIT_CODES[code]) for code in sorted_unit_codes()]


def unit_code_label(code: str) -> str:
    return UNIT_CODES.get((code or "").strip().upper(), "")


def normalize_unit_code(value: object) -> str | None:
    """Return a compliant code for ``value``, or ``None`` when unmappable."""
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    upper = " ".join(raw.upper().split())
    if upper in VALID_UNIT_CODES:
        return upper
    alias = LEGACY_UNIT_ALIASES.get(upper)
    if alias:
        return alias
    compact = upper.replace(" ", "")
    if compact in VALID_UNIT_CODES:
        return compact
    return LEGACY_UNIT_ALIASES.get(compact)


def coerce_unit_code(value: object, default: str = DEFAULT_UNIT_CODE) -> str:
    """Best-effort normalization for display / submission (never raises)."""
    return normalize_unit_code(value) or default
