"""Official FIRS / UN-ECE Recommendation 20 unit-of-measure codes.

FIRS (via the PASCA / Peppol BIS Billing 3.0 pipeline) requires the invoice
line ``price.price_unit`` field to be a short 2-3 character UN/ECE code, NOT
free text. Legacy Zetamind builds sent values like ``"NGN per 1"`` which the
gateway rejects (or silently mangles), so every code path that produces a
``price_unit`` now funnels through :func:`coerce_unit_code`.
"""

from __future__ import annotations

import re

# Canonical code -> human readable label.
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

_CODE_RE = re.compile(r"^[A-Z0-9]{2,3}$")

#: Legacy free text (and common shorthand) mapped onto compliant codes.
LEGACY_UNIT_ALIASES: dict[str, str] = {
    # legacy Zetamind defaults
    "NGN PER 1": "C62",
    "NGNPER1": "C62",
    "NAIRA PER 1": "C62",
    "NAIRA PER UNIT": "C62",
    "PER UNIT": "C62",
    "PER 1": "C62",
    # each / piece
    "EACH": "C62",
    "UNIT": "C62",
    "UNITS": "C62",
    "PIECE": "C62",
    "PIECES": "C62",
    "PCS": "C62",
    "PC": "C62",
    "NO": "C62",
    "ONE": "C62",
    # weight
    "KG": "KGM",
    "KGS": "KGM",
    "KILO": "KGM",
    "KILOS": "KGM",
    "KILOGRAM": "KGM",
    "KILOGRAMS": "KGM",
    # length
    "M": "MTR",
    "METRE": "MTR",
    "METRES": "MTR",
    "METER": "MTR",
    "METERS": "MTR",
    # volume (liquid)
    "L": "LTR",
    "LT": "LTR",
    "LITRE": "LTR",
    "LITRES": "LTR",
    "LITER": "LTR",
    "LITERS": "LTR",
    # area
    "M2": "MTK",
    "SQM": "MTK",
    "SQ M": "MTK",
    "SQUARE METRE": "MTK",
    "SQUARE METER": "MTK",
    # volume (cubic)
    "M3": "MTQ",
    "CBM": "MTQ",
    "CUBIC METRE": "MTQ",
    "CUBIC METER": "MTQ",
    # time
    "HR": "HUR",
    "HRS": "HUR",
    "HOUR": "HUR",
    "HOURS": "HUR",
    "DAYS": "DAY",
    # packaging
    "BOXES": "BOX",
    "BAGS": "BAG",
    "BOTTLE": "BTL",
    "BOTTLES": "BTL",
    "CARTON": "CTN",
    "CARTONS": "CTN",
    "SETS": "SET",
}


def sorted_unit_codes() -> list[str]:
    """Codes in a stable order, useful for error messages and lookups."""
    return sorted(VALID_UNIT_CODES)


def unit_code_options() -> list[dict[str, str]]:
    """Lookup-friendly ``[{"code": ..., "name": ...}]`` payload."""
    return [
        {"code": code, "name": UNIT_CODES[code]} for code in sorted_unit_codes()
    ]


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
    alias = LEGACY_UNIT_ALIASES.get(compact)
    if alias:
        return alias
    return None


def is_valid_unit_code(value: object) -> bool:
    raw = "" if value is None else str(value).strip().upper()
    return bool(_CODE_RE.match(raw)) and raw in VALID_UNIT_CODES


def coerce_unit_code(value: object, default: str = DEFAULT_UNIT_CODE) -> str:
    """Best-effort normalization used on assembly paths (never raises)."""
    return normalize_unit_code(value) or default


def validate_unit_code(value: object) -> str:
    """Strict normalization used by request schemas.

    Raises:
        ValueError: when the value cannot be mapped to an official code.
    """
    code = normalize_unit_code(value)
    if code is None:
        raise ValueError(
            "price_unit must be an official 2-3 character unit code "
            f"(one of: {', '.join(sorted_unit_codes())})."
        )
    return code
