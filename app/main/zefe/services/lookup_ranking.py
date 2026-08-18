"""One shared ranking path for the FIRS product and service lookup.

Both surfaces that let a user attach a classification code use this module:

* the Items page classification lookup (`routes/item_routes.py`), and
* the invoice wizard one-off line lookup (`routes/wizard_routes.py`).

Keeping the query expansion, synonym table, code detection, product versus
service biasing, de-duplication and scoring in one place means both surfaces
rank identically, and the whole ranker can be regression tested offline with
representative candidate rows (see `app/main/smoke_tests.py`).

FIRS / NRS constraints are preserved as-is: a product carries an HS code in
`XXXX.XX` form, a service carries a 4 digit ISIC code, and a hit is never both.
This module only orders candidates, it never invents or rewrites a code.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional, TypedDict

logger = logging.getLogger(__name__)


class LookupHit(TypedDict):
    """A ranked classification candidate.

    kind is either "product" (HS code) or "service" (ISIC code).
    """

    kind: str
    code: str
    label: str
    category: str


PRODUCT_KIND = "product"
SERVICE_KIND = "service"

#: FIRS HS codes are typed as XXXX.XX, ISIC service codes as 4 digits.
HS_CODE_RE = re.compile(r"^\s*(\d{2,4})\.(\d{1,2})\s*$")
ISIC_CODE_RE = re.compile(r"^\s*(\d{4})\s*$")

#: Dropped from a query before scoring, they carry no classification signal.
STOPWORDS: frozenset[str] = frozenset(
    {
        "the",
        "a",
        "an",
        "of",
        "for",
        "and",
        "or",
        "with",
        "to",
        "in",
        "on",
        "at",
        "by",
        "is",
        "are",
        "be",
        "this",
        "that",
        "per",
        "our",
        "your",
    }
)

#: Everyday wording mapped onto the vocabulary the FIRS catalogs actually use.
#: Multi word values are matched as phrases, single words as tokens.
SYNONYMS: dict[str, list[str]] = {
    # pharmaceutical
    "drug": ["pharmaceutical", "medicament", "medicine"],
    "drugs": ["pharmaceutical", "medicament", "medicine"],
    "pharmacy": ["pharmaceutical", "medicament"],
    "pharmaceutical": ["medicament"],
    "medicine": ["pharmaceutical", "medicament"],
    # computing hardware
    "computer": ["data processing", "automatic data", "machines"],
    "computers": ["data processing", "automatic data", "machines"],
    "laptop": ["portable", "data processing"],
    "laptops": ["portable", "data processing"],
    "desktop": ["data processing", "automatic data"],
    "tablet": ["portable", "data processing"],
    "printer": ["printing machine", "printing", "ink-jet", "laser"],
    "printers": ["printing machine", "printing"],
    "monitor": ["display", "monitor"],
    "monitors": ["display", "monitor"],
    # telephony and displays
    "phone": ["telephone", "cellular"],
    "phones": ["telephone", "cellular"],
    "smartphone": ["telephone", "cellular"],
    "smartphones": ["telephone", "cellular"],
    "mobile": ["cellular", "telephone"],
    "tv": ["television"],
    "television": ["television"],
    # appliances
    "fridge": ["refrigerator", "refrigerating"],
    "refrigerator": ["refrigerating"],
    "freezer": ["refrigerating", "refrigerator"],
    "dispenser": ["cooler", "container"],
    "water dispenser": ["water cooler", "cooler"],
    # footwear and apparel
    "shoe": ["footwear"],
    "shoes": ["footwear"],
    "sneaker": ["footwear"],
    "sneakers": ["footwear"],
    "boot": ["footwear"],
    "boots": ["footwear"],
    "sandal": ["footwear"],
    "sandals": ["footwear"],
    "clothing": ["apparel", "garments"],
    "apparel": ["apparel", "garments"],
    "garment": ["apparel", "garments"],
    "garments": ["apparel", "garments"],
    "fabric": ["textile", "fabrics"],
    "fabrics": ["textile", "fabrics"],
    "textile": ["textile", "fabrics"],
    # professional services
    "consulting": ["consultancy", "management consultancy"],
    "consultancy": ["management consultancy"],
    "consult": ["consultancy"],
    "advisor": ["consultancy", "management consultancy"],
    "advisory": ["consultancy", "management consultancy"],
    "accounting": ["bookkeeping", "auditing"],
    "accountant": ["bookkeeping", "auditing"],
    "audit": ["auditing"],
    "tax": ["tax consultancy", "bookkeeping"],
    "legal": ["legal activities"],
    "lawyer": ["legal", "legal activities"],
    "law": ["legal", "legal activities"],
    "advertising": ["advertising"],
    "marketing": ["advertising", "market research"],
    "branding": ["advertising", "specialized design"],
    # software and design
    "software": ["computer programming", "software publishing"],
    "saas": ["computer programming", "software publishing"],
    "app": ["computer programming", "software publishing"],
    "programming": ["computer programming"],
    "developer": ["computer programming"],
    "development": ["computer programming", "software publishing"],
    "design": ["specialized design"],
    "graphic": ["specialized design"],
    "graphics": ["specialized design"],
    # education
    "training": ["education", "training"],
    "education": ["education"],
    "course": ["education"],
    "courses": ["education"],
    "tutoring": ["education"],
    # movement of goods
    "transport": ["transport", "freight"],
    "transportation": ["transport", "freight"],
    "logistics": ["freight", "transport"],
    "shipping": ["freight", "transport"],
    "delivery": ["freight", "transport", "courier"],
    "courier": ["postal", "courier"],
    # renting and facilities
    "rent": ["renting", "leasing"],
    "rental": ["renting", "leasing"],
    "lease": ["renting", "leasing"],
    "leasing": ["renting", "leasing"],
    "construction": ["construction"],
    "building": ["construction"],
    "cleaning": ["cleaning"],
    "janitorial": ["cleaning"],
    "security": ["security"],
    "guard": ["security"],
    # hospitality and food
    "food": ["food preparations", "prepared food"],
    "catering": ["food service", "food preparations"],
    "restaurant": ["restaurants", "food service"],
    "hotel": ["accommodation", "hotels"],
    "lodging": ["accommodation", "hotels"],
    # agriculture and groceries
    "rice": ["rice", "cereals", "paddy"],
    "paddy": ["rice", "cereals"],
    "yam": ["yams", "tubers"],
    "yams": ["yam", "tubers"],
    "cassava": ["manioc", "tubers", "starch"],
    "manioc": ["cassava", "tubers"],
    "potato": ["potatoes", "vegetable"],
    "potatoes": ["potato", "vegetable"],
    "cereal": ["cereals", "grain", "wheat", "rice"],
    "cereals": ["cereal", "grain", "wheat", "rice"],
    "grain": ["cereals", "grains"],
    "grains": ["cereals", "grains"],
    "wheat": ["cereals", "meslin"],
    "maize": ["cereals", "corn"],
    "corn": ["maize", "cereals"],
    "millet": ["cereals", "millet"],
    "sorghum": ["cereals", "sorghum"],
    "beans": ["leguminous vegetables", "pulses"],
    "bean": ["leguminous vegetables", "pulses"],
    "fish": ["fish", "fillets"],
    "meat": ["meat", "edible offal"],
    "poultry": ["poultry", "meat"],
    "chicken": ["poultry", "meat"],
    "egg": ["eggs"],
    "eggs": ["eggs"],
    "milk": ["dairy", "milk"],
    "dairy": ["dairy", "milk"],
    "vegetable": ["vegetables"],
    "vegetables": ["vegetable"],
    "fruit": ["fruits", "edible"],
    "fruits": ["fruit", "edible"],
    "tomato": ["tomatoes", "vegetable"],
    "tomatoes": ["tomato", "vegetable"],
    "onion": ["onions", "vegetable"],
    "onions": ["onion", "vegetable"],
    "pepper": ["pepper", "spices"],
    "salt": ["salt", "sodium"],
    "sugar": ["sugar", "sucrose"],
    "flour": ["flour", "cereals"],
    "bread": ["bread", "bakers"],
    "agricultural": ["agriculture", "agric"],
    "agriculture": ["agricultural", "agric"],
    "agric": ["agricultural", "agriculture"],
    "farming": ["agriculture", "agric"],
    "livestock": ["live animals", "animal"],
    # fuels and vehicles
    "oil": ["oils", "petroleum"],
    "fuel": ["petroleum", "fuel"],
    "petrol": ["petroleum", "fuel"],
    "diesel": ["petroleum", "fuel"],
    "vehicle": ["motor vehicle", "vehicles"],
    "car": ["motor vehicle", "vehicles"],
    "cars": ["motor vehicle", "vehicles"],
    "tyre": ["tyres", "rubber"],
    "tyres": ["tyres", "rubber"],
    "tire": ["tyres", "rubber"],
    "tires": ["tyres", "rubber"],
    # print, paper, media
    "book": ["books", "printed"],
    "books": ["book", "printed"],
    "paper": ["paper", "stationery"],
    "stationery": ["paper", "stationery"],
    # technical services
    "repair": ["repair", "maintenance"],
    "maintenance": ["repair", "maintenance"],
    "installation": ["installation"],
    "hosting": ["hosting", "data processing"],
    "internet": ["telecommunications", "internet"],
    "telecom": ["telecommunications"],
    "telecoms": ["telecommunications"],
    "insurance": ["insurance"],
    "banking": ["financial", "banking"],
    "finance": ["financial"],
    "real estate": ["real estate"],
    "property": ["real estate"],
}

#: A query token here leans the ranking towards HS product results.
PRODUCT_HINTS: frozenset[str] = frozenset(
    {
        "computer",
        "computers",
        "laptop",
        "laptops",
        "desktop",
        "tablet",
        "printer",
        "printers",
        "monitor",
        "monitors",
        "phone",
        "phones",
        "smartphone",
        "smartphones",
        "mobile",
        "tv",
        "television",
        "fridge",
        "refrigerator",
        "freezer",
        "shoe",
        "shoes",
        "sneaker",
        "sneakers",
        "footwear",
        "boot",
        "boots",
        "sandal",
        "sandals",
        "dispenser",
        "cooler",
        "bottle",
        "bottled",
        "rice",
        "paddy",
        "yam",
        "yams",
        "cassava",
        "manioc",
        "potato",
        "potatoes",
        "cereal",
        "cereals",
        "grain",
        "grains",
        "wheat",
        "maize",
        "corn",
        "millet",
        "sorghum",
        "bean",
        "beans",
        "fish",
        "meat",
        "poultry",
        "chicken",
        "egg",
        "eggs",
        "milk",
        "dairy",
        "vegetable",
        "vegetables",
        "fruit",
        "fruits",
        "tomato",
        "tomatoes",
        "onion",
        "onions",
        "pepper",
        "salt",
        "sugar",
        "flour",
        "bread",
        "drug",
        "drugs",
        "pharmaceutical",
        "medicine",
        "medicament",
        "machine",
        "machines",
        "device",
        "equipment",
        "vehicle",
        "vehicles",
        "car",
        "cars",
        "tyre",
        "tyres",
        "tire",
        "tires",
        "fuel",
        "petrol",
        "diesel",
        "oil",
        "fabric",
        "fabrics",
        "textile",
        "clothing",
        "apparel",
        "garment",
        "garments",
        "paper",
        "book",
        "books",
        "food",
        "water",
    }
)

#: A query token here leans the ranking towards ISIC service results.
SERVICE_HINTS: frozenset[str] = frozenset(
    {
        "consulting",
        "consultancy",
        "consult",
        "advisor",
        "advisory",
        "accounting",
        "accountant",
        "audit",
        "auditing",
        "tax",
        "legal",
        "lawyer",
        "law",
        "advertising",
        "marketing",
        "branding",
        "training",
        "education",
        "tutoring",
        "transport",
        "transportation",
        "logistics",
        "shipping",
        "delivery",
        "courier",
        "rent",
        "rental",
        "lease",
        "leasing",
        "cleaning",
        "janitorial",
        "security",
        "guard",
        "design",
        "graphic",
        "graphics",
        "programming",
        "development",
        "hosting",
        "internet",
        "telecom",
        "telecoms",
        "insurance",
        "banking",
        "finance",
        "service",
        "services",
        "maintenance",
        "repair",
        "installation",
        "support",
        "catering",
        "restaurant",
        "hotel",
        "lodging",
        "accommodation",
    }
)

# Scoring weights. Exact and prefix matches dominate, the bias only breaks
# ties between comparable candidates so a product query cannot be won by an
# unrelated service (and the other way round).
SCORE_EXACT = 120.0
SCORE_LABEL_PREFIX = 40.0
SCORE_FIRST_SEGMENT = 18.0
SCORE_FULL_PHRASE = 25.0
SCORE_CODE_PREFIX = 15.0
SCORE_PHRASE = 12.0
SCORE_TOKEN_LABEL = 6.0
SCORE_TOKEN_CATEGORY = 4.0
SCORE_TOKEN_SUBSTRING = 1.5
BIAS_MATCH_BONUS = 18.0
BIAS_MISMATCH_PENALTY = 14.0
MIN_KEEP_SCORE = 12.0

DEFAULT_RESULT_LIMIT = 20
DEFAULT_TERM_LIMIT = 6
DEFAULT_PER_TERM_LENGTH = 30

_word_re_cache: dict[str, re.Pattern[str]] = {}


def _norm(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def tokenize(query: str) -> list[str]:
    """Meaningful lowercase tokens of a query, stopwords removed."""
    return [
        tok
        for tok in re.split(r"[^a-z0-9]+", _norm(query).lower())
        if tok and tok not in STOPWORDS and len(tok) >= 2
    ]


def singular(token: str) -> str:
    """Very small English de-pluraliser, good enough for catalog wording."""
    if len(token) > 4 and token.endswith("ies"):
        return f"{token[:-3]}y"
    if len(token) > 4 and token.endswith("es") and not token.endswith("ses"):
        return token[:-2]
    if len(token) > 4 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _word_re(token: str) -> re.Pattern[str]:
    """Word start match. Tokens of 3+ chars also match a longer word."""
    if token not in _word_re_cache:
        if len(token) >= 3:
            pattern = r"\b" + re.escape(token)
        else:
            pattern = r"\b" + re.escape(token) + r"\b"
        _word_re_cache[token] = re.compile(pattern, re.IGNORECASE)
    return _word_re_cache[token]


def detect_code_kind(query: str) -> Optional[str]:
    """ "product" for an HS shaped code, "service" for an ISIC one."""
    raw = _norm(query)
    if HS_CODE_RE.match(raw):
        return PRODUCT_KIND
    if ISIC_CODE_RE.match(raw):
        return SERVICE_KIND
    return None


def is_code_query(query: str) -> bool:
    return detect_code_kind(query) is not None


def detect_bias(query: str) -> str:
    """ "product", "service" or "neutral" for a query."""
    code_kind = detect_code_kind(query)
    if code_kind:
        return code_kind
    tokens = tokenize(query)
    product_score = 0
    service_score = 0
    for tok in tokens:
        variants = {tok, singular(tok)}
        if variants & PRODUCT_HINTS:
            product_score += 1
        if variants & SERVICE_HINTS:
            service_score += 1
    if product_score > service_score:
        return PRODUCT_KIND
    if service_score > product_score:
        return SERVICE_KIND
    return "neutral"


def _synonyms_for(token: str) -> list[str]:
    out = list(SYNONYMS.get(token, []))
    sing = singular(token)
    if sing != token:
        out.extend(SYNONYMS.get(sing, []))
    return out


def expand_search_terms(
    query: str, limit: int = DEFAULT_TERM_LIMIT
) -> list[str]:
    """Terms to send upstream: the query, its tokens and their synonyms."""
    terms: list[str] = []
    seen: set[str] = set()

    def add(term: object) -> None:
        text = _norm(term)
        if len(text) < 2:
            return
        key = text.lower()
        if key in seen:
            return
        seen.add(key)
        terms.append(text)

    raw = _norm(query)
    if not raw:
        return []
    add(raw)
    lower = raw.lower()
    for tok in tokenize(raw):
        add(tok)
        sing = singular(tok)
        if sing != tok and len(sing) >= 4:
            add(sing)
        for syn in _synonyms_for(tok):
            add(syn)
    for syn in SYNONYMS.get(lower, []):
        add(syn)
    return terms[: max(1, limit)]


def _scoring_terms(query: str) -> tuple[list[str], list[str]]:
    """(tokens, phrases) used for scoring a candidate."""
    raw = _norm(query)
    lower = raw.lower()
    tokens: list[str] = []
    phrases: list[str] = []

    def add(term: object) -> None:
        text = _norm(term).lower()
        if len(text) < 2:
            return
        if " " in text:
            if text not in phrases:
                phrases.append(text)
        elif text not in tokens:
            tokens.append(text)

    if " " in lower:
        phrases.append(lower)
    for tok in tokenize(raw):
        add(tok)
        sing = singular(tok)
        if sing != tok and len(sing) >= 4:
            add(sing)
        for syn in _synonyms_for(tok):
            add(syn)
    for syn in SYNONYMS.get(lower, []):
        add(syn)
    return tokens, phrases


def normalize_product_hits(rows: object) -> list[LookupHit]:
    """Upstream HS rows to LookupHit, dropping anything without a code."""
    out: list[LookupHit] = []
    for row in rows or []:  # type: ignore[union-attr]
        if not isinstance(row, dict):
            continue
        code = _norm(row.get("hscode") or row.get("code") or "")
        if not code:
            continue
        label = _norm(row.get("description") or row.get("label") or "")
        category = _norm(
            row.get("product_category") or row.get("category") or label
        )
        out.append(
            {
                "kind": PRODUCT_KIND,
                "code": code,
                "label": label,
                "category": category,
            }
        )
    return out


def normalize_service_hits(rows: object) -> list[LookupHit]:
    """Upstream ISIC rows to LookupHit, dropping anything without a code."""
    out: list[LookupHit] = []
    for row in rows or []:  # type: ignore[union-attr]
        if not isinstance(row, dict):
            continue
        code = _norm(row.get("code") or "")
        if not code:
            continue
        label = _norm(row.get("description") or row.get("label") or "")
        category = _norm(row.get("category") or label)
        out.append(
            {
                "kind": SERVICE_KIND,
                "code": code,
                "label": label,
                "category": category,
            }
        )
    return out


def merge_hits(*groups: list[LookupHit]) -> list[LookupHit]:
    """De-duplicate on (kind, code), first occurrence wins."""
    merged: dict[tuple[str, str], LookupHit] = {}
    for group in groups:
        for hit in group or []:
            key = (str(hit.get("kind") or ""), str(hit.get("code") or ""))
            if not key[1]:
                continue
            if key not in merged:
                merged[key] = hit
    return list(merged.values())


def score_hit(
    hit: LookupHit,
    *,
    lower_query: str,
    tokens: list[str],
    phrases: list[str],
    query_tokens: list[str],
    bias: str,
) -> Optional[float]:
    """Relevance of one candidate, or None when it should be dropped."""
    label = (hit.get("label") or "").lower()
    category = (hit.get("category") or "").lower()
    code = (hit.get("code") or "").lower()
    blob = f"{label} || {category}"
    compact = lower_query.replace(" ", "")

    score = 0.0
    if lower_query and (label == lower_query or code == lower_query):
        score += SCORE_EXACT
    if lower_query and label.startswith(lower_query):
        score += SCORE_LABEL_PREFIX
    first_segment = label.split(";", 1)[0]
    if lower_query and lower_query in first_segment:
        score += SCORE_FIRST_SEGMENT
    if " " in lower_query and lower_query in blob:
        score += SCORE_FULL_PHRASE
    if (
        compact
        and code
        and code.replace(".", "").startswith(compact.replace(".", ""))
    ):
        score += SCORE_CODE_PREFIX
    for phrase in phrases:
        if phrase and phrase in blob:
            score += SCORE_PHRASE

    matched = 0
    for tok in tokens:
        pattern = _word_re(tok)
        if pattern.search(label):
            score += SCORE_TOKEN_LABEL
            matched += 1
        elif pattern.search(category):
            score += SCORE_TOKEN_CATEGORY
            matched += 1
        elif tok in blob:
            score += SCORE_TOKEN_SUBSTRING
            matched += 1

    if query_tokens and matched == 0 and score < MIN_KEEP_SCORE:
        return None

    if bias == PRODUCT_KIND or bias == SERVICE_KIND:
        if hit.get("kind") == bias:
            score += BIAS_MATCH_BONUS
        else:
            score -= BIAS_MISMATCH_PENALTY

    if score <= 0:
        return None
    return score


def rank_hits(
    query: str,
    hits: list[LookupHit],
    limit: int = DEFAULT_RESULT_LIMIT,
) -> list[LookupHit]:
    """Rank already normalized and de-duplicated candidates."""
    raw = _norm(query)
    lower = raw.lower()
    if not lower or not hits:
        return []
    query_tokens = tokenize(raw)
    tokens, phrases = _scoring_terms(raw)
    bias = detect_bias(raw)

    scored: list[tuple[float, LookupHit]] = []
    for hit in hits:
        score = score_hit(
            hit,
            lower_query=lower,
            tokens=tokens,
            phrases=phrases,
            query_tokens=query_tokens,
            bias=bias,
        )
        if score is None:
            continue
        scored.append((score, hit))

    scored.sort(
        key=lambda pair: (
            -pair[0],
            (pair[1].get("label") or "").lower(),
            pair[1].get("code") or "",
        )
    )
    return [hit for _score, hit in scored[: max(1, limit)]]


def rank_lookup_results(
    query: str,
    product_rows: object = None,
    service_rows: object = None,
    limit: int = DEFAULT_RESULT_LIMIT,
) -> list[LookupHit]:
    """Normalize, de-duplicate and rank raw upstream rows in one call."""
    merged = merge_hits(
        normalize_product_hits(product_rows),
        normalize_service_hits(service_rows),
    )
    return rank_hits(query, merged, limit=limit)


async def search_and_rank_classifications(
    token: str,
    query: str,
    *,
    session_id: Optional[str] = None,
    limit: int = DEFAULT_RESULT_LIMIT,
    term_limit: int = DEFAULT_TERM_LIMIT,
    per_term_length: int = DEFAULT_PER_TERM_LENGTH,
) -> list[LookupHit]:
    """Search the FIRS product and service catalogs, then rank the hits.

    The upstream API calls are unchanged: `search_products` and
    `search_services` are still the only endpoints used, once per expanded
    term. A failing term contributes nothing rather than failing the search.
    """
    raw = _norm(query)
    if len(raw) < 2:
        return []

    from services import api_client

    terms = expand_search_terms(raw, term_limit)
    if not terms:
        return []

    async def fetch_products(term: str) -> list:
        try:
            return await api_client.search_products(
                token, term, length=per_term_length, session_id=session_id
            )
        except Exception:
            logger.exception("lookup: search_products failed for %r", term)
            return []

    async def fetch_services(term: str) -> list:
        try:
            return await api_client.search_services(
                token, term, length=per_term_length, session_id=session_id
            )
        except Exception:
            logger.exception("lookup: search_services failed for %r", term)
            return []

    product_results, service_results = await asyncio.gather(
        asyncio.gather(
            *[fetch_products(t) for t in terms], return_exceptions=True
        ),
        asyncio.gather(
            *[fetch_services(t) for t in terms], return_exceptions=True
        ),
    )

    product_rows: list = []
    for res in product_results:
        if isinstance(res, Exception) or not res:
            continue
        product_rows.extend(res)
    service_rows: list = []
    for res in service_results:
        if isinstance(res, Exception) or not res:
            continue
        service_rows.extend(res)

    ranked = rank_lookup_results(raw, product_rows, service_rows, limit=limit)
    logger.info(
        "lookup ranked query=%r terms=%d candidates=%d results=%d bias=%s",
        raw,
        len(terms),
        len(product_rows) + len(service_rows),
        len(ranked),
        detect_bias(raw),
    )
    return ranked
