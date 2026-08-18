"""Lightweight standalone regression checks for the Zetamind stack.

Run with:

    python -m app.main.smoke_tests

Or, from anywhere on the repo:

    python app/main/smoke_tests.py

This intentionally avoids pytest, network access, and any heavy infrastructure.
It exercises three things:

  1. **zebe** — the FastAPI backend's item API round-trips end-to-end against
     an ephemeral SQLite database (create → search → update → filter → import
     → bulk-delete), using the real route callables and Pydantic schemas.
  2. **zefe** — the FastHTML frontend route modules and UI helpers parse
     cleanly (AST parse + import smoke), so a syntax regression in a route or
     UI helper fails loudly before serving.
  3. **zefe → zebe contract** — the api_client methods that the wizard and
     item pages rely on are present with the expected signatures, so a rename
     on the backend or client side is caught immediately.
"""

from __future__ import annotations

import ast
import inspect
import os
import re
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

import logging


REPO_ROOT = Path(__file__).resolve().parent
ZEBE = str(REPO_ROOT / "zebe")
ZEFE = str(REPO_ROOT / "zefe")

# Top-level module names that exist in BOTH the zebe and zefe trees. Because
# each subsystem is run by prepending its own directory to sys.path (rather
# than being installed as a proper package), Python's import cache will
# happily return the first-loaded version to the second subsystem, which
# then explodes with confusing ImportErrors (e.g. `settings` missing from
# what is actually the zefe `config` module). We purge these names — plus
# any of their submodules — from sys.modules whenever we swap subsystems.
_SHARED_TOP_LEVEL_NAMES = (
    "config",
    "deps",
    "auth",
    "main",
    "routes",
    "services",
    "utils",
    "ui",
)

# Modules that belong to only ONE subsystem but still cache subsystem state
# (SQLAlchemy engines, HTTP clients, rate-limiter tables, endpoint tables).
# They must be purged alongside the colliding names: leaving, say, a cached
# ``utils.database`` behind while ``routes`` is re-imported is exactly how a
# stale Postgres engine survives into a check that already forced SQLite.
_SUBSYSTEM_TOP_LEVEL_NAMES = (
    "rate_limiter",
    "audit",
    "seed",
    "endpoints",
)

_PURGE_TOP_LEVEL_NAMES = _SHARED_TOP_LEVEL_NAMES + _SUBSYSTEM_TOP_LEVEL_NAMES


def _purge_shared_modules() -> None:
    """Drop cached imports that must not leak between zebe/zefe checks.

    This covers both the top-level names that collide across the two trees and
    the single-subsystem modules that hold live connection/engine state, so the
    next check always re-imports them against the environment it just forced.
    """
    for name in list(sys.modules):
        root = name.split(".", 1)[0]
        if root in _PURGE_TOP_LEVEL_NAMES:
            sys.modules.pop(name, None)


def _remove_path_entry(entry: str) -> None:
    while entry in sys.path:
        try:
            sys.path.remove(entry)
        except ValueError:
            break


class _SubsystemPath:
    """Context manager that isolates imports for one subsystem.

    On enter: purge cached shared modules, drop the *other* subsystem's
    path entry if present, and prepend this subsystem's directory.
    On exit: purge again and remove the prepended entry so the next
    check starts from a clean slate.
    """

    def __init__(self, path: str, *, sibling: str | None = None) -> None:
        self.path = path
        self.sibling = sibling

    def __enter__(self) -> "_SubsystemPath":
        if self.sibling:
            _remove_path_entry(self.sibling)
        _purge_shared_modules()
        sys.path.insert(0, self.path)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        _remove_path_entry(self.path)
        _purge_shared_modules()


# --------------------------------------------------------------------------
# Isolated environment for every zebe import path
# --------------------------------------------------------------------------
#
# ``utils.database`` builds the SQLAlchemy engine at *import* time, so any zebe
# import made before DATABASE_URL is pointed at SQLite would try to load the
# psycopg2 driver (and fail in this sandbox). Every check that touches zebe must
# therefore call :func:`_configure_zebe_env` first — including the derived
# invoice-field checks, which import ``services.invoice_service`` and, through
# it, ``utils.models``.

_ISOLATED_DB_PATH: str | None = None


def _configure_zebe_env() -> str:
    """Point zebe at an isolated SQLite DB and stub required settings.

    Any non-SQLite DATABASE_URL inherited from the environment is deliberately
    overridden: these smoke checks must never depend on psycopg2 or on a real
    Postgres instance being reachable.

    ``utils.database`` calls ``load_dotenv(override=True)`` at import time,
    which would happily put the deployment's Postgres URL back over the top of
    ours, so the dotenv override is neutralized here (for this process only —
    the application module itself is untouched) before any backend import.
    """
    global _ISOLATED_DB_PATH

    _neutralize_dotenv()

    os.environ.setdefault(
        "JWT_SECRET_KEY",
        "smoke-test-secret-key-must-be-at-least-32-bytes-long",
    )
    os.environ.setdefault("API_KEY", "smoke-test-api-key")
    os.environ.setdefault("CLIENT_SECRET", "smoke-test-client-secret")

    current = os.environ.get("DATABASE_URL", "")
    if _ISOLATED_DB_PATH is not None:
        # Re-assert in case something reset the variable between checks.
        os.environ["DATABASE_URL"] = f"sqlite:///{_ISOLATED_DB_PATH}"
        return _ISOLATED_DB_PATH

    prefix = "sqlite:///"
    if current.startswith(prefix):
        _ISOLATED_DB_PATH = current[len(prefix) :]
        return _ISOLATED_DB_PATH

    _ISOLATED_DB_PATH = tempfile.NamedTemporaryFile(
        prefix="zebe_smoke_", suffix=".db", delete=False
    ).name
    os.environ["DATABASE_URL"] = f"sqlite:///{_ISOLATED_DB_PATH}"
    return _ISOLATED_DB_PATH


def _reassert_zebe_env() -> None:
    """Re-force the isolated SQLite DATABASE_URL.

    Called immediately before every backend import (and again after any
    ``load_dotenv`` call) so nothing can put a Postgres URL back in place
    between configuration and import.
    """
    if _ISOLATED_DB_PATH:
        os.environ["DATABASE_URL"] = f"sqlite:///{_ISOLATED_DB_PATH}"


_DOTENV_PATCHED = False


def _neutralize_dotenv() -> None:
    """Make ``load_dotenv`` unable to clobber the harness environment.

    zebe's ``utils/database.py`` (and ``seed.py``) call
    ``load_dotenv(override=True)`` at import time. In this sandbox the on-disk
    ``.env`` points DATABASE_URL at Postgres, so the override silently undid
    :func:`_configure_zebe_env` and the import died on ``psycopg2``. The patch
    is process-local to the test harness: it forces ``override=False`` and
    re-asserts the isolated DATABASE_URL afterwards. Application code is
    unchanged and behaves exactly as before outside this harness.
    """
    global _DOTENV_PATCHED
    if _DOTENV_PATCHED:
        return
    _DOTENV_PATCHED = True
    try:
        import dotenv
    except ImportError:
        logging.getLogger("smoke_tests").debug(
            "python-dotenv not installed; nothing to neutralize"
        )
        return

    original = dotenv.load_dotenv

    def _guarded_load_dotenv(*args, **kwargs):
        kwargs["override"] = False
        try:
            result = original(*args, **kwargs)
        except Exception:
            logging.exception("guarded load_dotenv failed; ignoring")
            result = False
        _reassert_zebe_env()
        return result

    dotenv.load_dotenv = _guarded_load_dotenv
    try:
        import dotenv.main as dotenv_main

        dotenv_main.load_dotenv = _guarded_load_dotenv
    except ImportError:
        logging.getLogger("smoke_tests").debug("dotenv.main unavailable")


def _assert_zebe_db_isolated() -> None:
    """Verify the freshly imported zebe engine really is the SQLite one."""
    url = os.environ.get("DATABASE_URL", "")
    assert url.startswith("sqlite:"), (
        "DATABASE_URL must be forced to the isolated SQLite database before "
        f"any zebe import (got {url.split('://')[0]!r})"
    )

    import utils.database as zebe_database

    module_url = str(getattr(zebe_database, "DATABASE_URL", ""))
    assert module_url.startswith("sqlite:"), (
        "utils.database resolved a non-SQLite DATABASE_URL — the dotenv "
        f"override guard is not in effect (got {module_url.split('://')[0]!r})"
    )
    backend = zebe_database.engine.url.get_backend_name()
    assert backend == "sqlite", (
        f"zebe engine is bound to {backend!r}, not the isolated SQLite file"
    )


@contextmanager
def _zebe_imports():
    """The ONLY sanctioned way to import zebe modules from a smoke check.

    Guarantees, in order: the isolated SQLite DATABASE_URL is configured and
    dotenv can no longer override it, stale cached backend modules are purged,
    zebe is first on ``sys.path`` (and zefe is off it), the environment is
    re-asserted, and the resulting engine is verified to be SQLite.
    """
    _configure_zebe_env()
    with _SubsystemPath(ZEBE, sibling=ZEFE):
        _reassert_zebe_env()
        _assert_zebe_db_isolated()
        yield


def _cleanup_isolated_db() -> None:
    global _ISOLATED_DB_PATH
    if not _ISOLATED_DB_PATH:
        return
    try:
        Path(_ISOLATED_DB_PATH).unlink(missing_ok=True)
    except OSError as exc:
        # Leaving a temp file behind is harmless, so keep this concise.
        logging.exception("Unexpected error")
        logging.getLogger("smoke_tests").warning(
            "could not remove temp SQLite DB %s: %s", _ISOLATED_DB_PATH, exc
        )
    _ISOLATED_DB_PATH = None


# --------------------------------------------------------------------------
# 1. zebe: item API round trip
# --------------------------------------------------------------------------


def check_zebe_item_flow() -> None:
    print("[zebe] item API round-trip…", flush=True)
    with _zebe_imports():
        _run_zebe_item_flow()


def _run_zebe_item_flow() -> None:
    from utils.database import Base, engine, SessionLocal
    from utils.models import User
    from auth import hash_password, create_access_token
    from utils.schema import ItemCreate, ItemUpdate
    from routes.item_routes import (
        create_item,
        list_items,
        update_item,
        bulk_delete_items,
        _process_import_rows,
    )
    from utils import schema as sch

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        user = User(
            username="Smoke Tester",
            email="smoke@example.com",
            hashed_password=hash_password("password123"),
            business_id="biz-smoke",
            service_id="svcsmoke",
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        token = create_access_token({"sub": str(user.id)})

        created = create_item(
            ItemCreate(
                sku="SVC-001",
                name="Consulting Package",
                description="Monthly advisory",
                isic_code="7020",
                isic_category="Management consultancy",
                unit_price=1500,
                price_unit="EA",
            ),
            token=token,
            db=db,
        )
        assert created.sku == "SVC-001", "Item SKU not persisted"
        assert created.price_unit == "EA", (
            "price_unit must persist as the official unit code EA "
            f"(got {created.price_unit!r})"
        )

        # Legacy free-text unit values were never deployed and are now
        # rejected outright by the request schemas. This is the expected
        # outcome, so it must be asserted quietly — no traceback logging.
        from pydantic import ValidationError as _PydanticValidationError

        legacy_rejected = ""
        try:
            ItemCreate(
                sku="LEGACY-001",
                name="Legacy unit item",
                isic_code="7020",
                isic_category="Management consultancy",
                unit_price=100,
                price_unit="NGN per 1",
            )
        except _PydanticValidationError as exc:
            # Expected rejection: capture the message only. This negative path
            # is a pass condition, so it must never log a traceback.
            logging.exception("Unexpected error")
            legacy_rejected = str(exc)
            logging.getLogger("smoke_tests").debug(
                "legacy price_unit rejected as expected: %s", legacy_rejected
            )
        if not legacy_rejected:
            raise AssertionError(
                "legacy free-text price_unit ('NGN per 1') must now be "
                "rejected — only official unit codes are accepted"
            )
        assert "price_unit" in legacy_rejected, (
            "the rejection message should name the offending price_unit field "
            f"(got: {legacy_rejected})"
        )

        page = list_items(
            token=token, db=db, search="consult", offset=0, limit=10
        )
        assert page["total"] == 1
        assert page["items"][0].sku == "SVC-001"

        updated = update_item(
            created.id,
            ItemUpdate(
                sku="SVC-001",
                name="Consulting Package Plus",
                description="Monthly advisory plus reporting",
                isic_code="7020",
                isic_category="Management consultancy",
                unit_price=2000,
                price_unit="EA",
            ),
            token=token,
            db=db,
        )
        assert updated.name.endswith("Plus")

        rows = [
            {
                "sku": "RICE-001",
                "name": "Premium Rice",
                "description": "50kg bag",
                "hsn_code": "1006.10",
                "hsn_category": "Rice",
                "isic_code": "",
                "isic_category": "",
                "unit_price": "42000",
                "price_unit": "KGM",
            },
            {
                "sku": "BAD-001",
                "name": "Bad Row (both classifications)",
                "description": "",
                "hsn_code": "1006.10",
                "hsn_category": "Rice",
                "isic_code": "7020",
                "isic_category": "Consulting",
                "unit_price": "100",
                "price_unit": "EA",
            },
            {
                # Intentionally bad row: legacy free-text unit must be
                # skipped with a reason rather than silently coerced.
                "sku": "LEGACY-IMPORT-001",
                "name": "Legacy unit import row",
                "description": "",
                "hsn_code": "",
                "hsn_category": "",
                "isic_code": "7020",
                "isic_category": "Management consultancy",
                "unit_price": "100",
                "price_unit": "NGN per 1",
            },
        ]
        result = _process_import_rows(rows, db=db, business_id=user.business_id)
        assert result.created == 1, f"expected 1 create, got {result.created}"
        assert result.skipped == 2, (
            "both intentionally bad rows should have been skipped "
            f"(got skipped={result.skipped})"
        )
        assert len(result.errors) == 2, (
            "each skipped row must be reported back to the user with a reason"
        )
        error_blob = " | ".join(result.errors)
        assert "BAD-001" in error_blob and "LEGACY-IMPORT-001" in error_blob, (
            f"skipped rows should be identifiable: {error_blob}"
        )
        assert "price_unit" in error_blob, (
            "the legacy free-text unit row must be reported as a price_unit "
            f"problem: {error_blob}"
        )

        prods = list_items(
            token=token, db=db, kind="product", offset=0, limit=10
        )
        assert prods["total"] == 1
        assert prods["items"][0].sku == "RICE-001"

        deleted = bulk_delete_items(
            sch.ItemBulkDelete(ids=[created.id]),
            token=token,
            db=db,
        )
        assert deleted["deleted"] == 1

        remaining = list_items(token=token, db=db, offset=0, limit=10)
        assert all(i.sku != "SVC-001" for i in remaining["items"]), (
            "soft-deleted item still appears in the active listing"
        )

        _run_zebe_unit_and_irn_checks(db, user)
        _run_zebe_simple_import_checks(db, user)
    finally:
        db.close()
    print("  ✓ item API create / search / update / import / bulk-delete OK")


def _run_zebe_unit_and_irn_checks(db, user) -> None:
    """Unit-code compliance + server-side IRN reservation guardrails.

    Both concerns now live in ``services.invoice_service`` — the standalone
    ``irn_service`` module is gone and ``services.unit_codes`` is only a
    re-export shim, so this check imports the consolidated module directly.
    """
    from services.invoice_service import (
        DEFAULT_PRICE_UNIT,
        DEFAULT_UNIT_CODE,
        VALID_UNIT_CODES,
        coerce_unit_code,
        normalize_unit_code,
        parse_irn,
        reserve_next_irn,
        unit_code_label,
        unit_code_options,
    )

    assert DEFAULT_UNIT_CODE == "EA", (
        "the official user-facing default unit code should be EA (each)"
    )
    assert DEFAULT_PRICE_UNIT == DEFAULT_UNIT_CODE, (
        "invoice assembly still defaults to a non-compliant price unit"
    )
    # Only official codes are accepted; legacy free text and the legacy C62
    # code were removed now that nothing is deployed against them.
    assert normalize_unit_code("EA") == "EA"
    assert normalize_unit_code("kgm") == "KGM"
    assert normalize_unit_code("NGN per 1") is None
    assert normalize_unit_code("each") is None
    assert normalize_unit_code("kg") is None
    assert normalize_unit_code("banana") is None
    assert "C62" not in VALID_UNIT_CODES, (
        "the legacy C62 unit code must no longer be offered or accepted"
    )
    assert normalize_unit_code("C62") is None
    # coerce_* never raises: unmappable input becomes the official default.
    assert coerce_unit_code("NGN per 1") == "EA"
    assert coerce_unit_code("") == "EA"
    assert unit_code_label("EA") == "Each"
    codes = [row["code"] for row in unit_code_options()]
    assert codes and codes[0] == "EA" and "C62" not in codes

    # The standalone unit-code module is now only a re-export shim; anything
    # still importing it must observe the consolidated implementation.
    from services import unit_codes as unit_codes_shim

    assert unit_codes_shim.coerce_unit_code is coerce_unit_code, (
        "services.unit_codes must re-export the invoice_service helpers, "
        "not define its own copy"
    )
    assert unit_codes_shim.DEFAULT_UNIT_CODE == DEFAULT_UNIT_CODE
    assert unit_codes_shim.VALID_UNIT_CODES == VALID_UNIT_CODES
    print("  ✓ official unit-code constants and normalization OK")

    irn1, seq1 = reserve_next_irn(
        db,
        business_id=user.business_id,
        service_id=user.service_id,
        issue_date="2026-03-01",
    )
    irn2, seq2 = reserve_next_irn(
        db,
        business_id=user.business_id,
        service_id=user.service_id,
        issue_date="2026-03-01",
    )
    assert seq2 == seq1 + 1, f"IRN sequence did not advance: {seq1} -> {seq2}"
    parsed = parse_irn(irn2)
    assert parsed is not None, f"generated IRN is malformed: {irn2}"
    assert parsed[2] == "20260301", "IRN date segment does not match issue_date"
    print("  ✓ server-side IRN reservation OK")


# --------------------------------------------------------------------------
# 2. zefe: route + UI modules parse
# --------------------------------------------------------------------------

ZEFE_MODULES = [
    "services/unit_codes.py",
    "services/lookup_ranking.py",
    "routes/auth_routes.py",
    "routes/customer_routes.py",
    "routes/dashboard_routes.py",
    "routes/invoice_routes.py",
    "routes/item_routes.py",
    "routes/settings_routes.py",
    "routes/wizard_routes.py",
    "services/api_client.py",
    "services/auth_service.py",
    "services/errors.py",
    "services/pdf_service.py",
    "ui/components.py",
    "ui/icons.py",
    "ui/layout.py",
    "main.py",
]


def check_zefe_syntax() -> None:
    print("[zefe] route / UI modules parse…", flush=True)
    # AST-only — no imports, so no sys.path manipulation needed. Still purge
    # any stale cached shared modules for safety in case a prior run leaked.
    _purge_shared_modules()
    for rel in ZEFE_MODULES:
        path = Path(ZEFE) / rel
        if not path.exists():
            raise AssertionError(f"missing zefe module: {rel}")
        ast.parse(path.read_text(), filename=str(path))
    print(f"  ✓ {len(ZEFE_MODULES)} modules parse cleanly")


# --------------------------------------------------------------------------
# 3. zefe → zebe contract: api_client surface
# --------------------------------------------------------------------------


REQUIRED_API_CLIENT = {
    # auth
    "login": ("username", "password"),
    "register": ("username", "email", "password", "business_id", "service_id"),
    "get_me": ("token",),
    "get_user_secret_status": ("token",),
    "update_secret": ("token", "secret"),
    # invoice lifecycle
    "assemble_invoice": ("token", "wizard"),
    "validate_invoice": ("token", "invoice_dict"),
    "sign_invoice": ("token", "user_secret", "invoice_dict"),
    "transmit_invoice": ("token", "irn"),
    "mark_transmitted": ("token", "irn"),
    "update_invoice_status": (
        "token",
        "irn",
        "user_secret",
        "payment_status",
    ),
    # customer directory
    "list_customers": ("token",),
    "get_customer": ("token", "cid"),
    "create_customer": ("token", "payload"),
    "update_customer": ("token", "cid", "payload"),
    "delete_customer": ("token", "cid", "hard"),
    "restore_customer": ("token", "cid"),
    "bulk_delete_customers": ("token", "ids", "hard"),
    "bulk_activate_customers": ("token", "ids"),
    "import_customers": ("token", "filename", "content"),
    # items catalog
    "list_items": ("token",),
    "get_item": ("token", "item_id"),
    "create_item": ("token", "payload"),
    "update_item": ("token", "item_id", "payload"),
    "delete_item": ("token", "item_id"),
    "bulk_delete_items": ("token", "ids"),
    "import_items": ("token", "filename", "content"),
}


def check_zefe_zebe_contract() -> None:
    print("[zefe→zebe] api_client contract…", flush=True)
    with _SubsystemPath(ZEFE, sibling=ZEBE):
        from services import api_client  # noqa: WPS433

        missing = _check_api_client_contract(api_client)
    if missing:
        raise AssertionError(
            "api_client contract failed:\n  - " + "\n  - ".join(missing)
        )
    print(f"  ✓ {len(REQUIRED_API_CLIENT)} api_client functions match contract")


def _check_api_client_contract(api_client) -> list[str]:
    missing: list[str] = []
    for name, required_params in REQUIRED_API_CLIENT.items():
        fn = getattr(api_client, name, None)
        if fn is None or not callable(fn):
            missing.append(f"{name} (function not found)")
            continue
        try:
            sig = inspect.signature(fn)
        except (TypeError, ValueError):
            missing.append(f"{name} (unreadable signature)")
            continue
        params = set(sig.parameters.keys())
        for p in required_params:
            if p not in params:
                missing.append(f"{name}(missing arg: {p})")
    return missing


# --------------------------------------------------------------------------
# 4. wizard signing-secret onboarding wiring
# --------------------------------------------------------------------------


def check_zebe_derived_invoice_fields() -> None:
    """Guard the NRS/PASCA-aligned derived fields on the assembled payload.

    None of these may ever come from a manual user input: invoice_kind is
    derived from the customer TIN, tax_point_date from issue_date, and the
    initial payment_status is always PENDING. Monetary totals stay derived and
    business_id must pass through byte-exact (lowercase UUID).
    """
    print("[zebe] derived NRS invoice fields…", flush=True)
    # _zebe_imports() forces the isolated SQLite DATABASE_URL *before* the
    # import below: services.invoice_service pulls in utils.models ->
    # utils.database, which builds the engine at import time.
    with _zebe_imports():
        _run_zebe_derived_field_checks()
    print("  ✓ invoice_kind / tax_point_date / payment_status derivation OK")


def _wizard_fixture() -> dict:
    return {
        "irn": "INV3180-SVCSMOKE-20260301",
        "issue_date": "2026-03-01",
        "due_date": "2026-03-15",
        "invoice_type_code": "381",
        "document_currency_code": "NGN",
        "payment_means_code": "10",
        "supplier_tin": "12345678-0001",
        "supplier_party_name": "Supplier Ltd",
        "supplier_email": "supplier@example.com",
        "supplier_telephone": "+2348000000000",
        "supplier_street_name": "Main Street",
        "supplier_city_name": "Lagos",
        "supplier_postal_zone": "100001",
        "supplier_country": "NG",
        "supplier_state": "Lagos",
        "supplier_lga": "",
        "customer_tin": "23456789-0001",
        "customer_party_name": "Buyer Ltd",
        "customer_email": "buyer@example.com",
        "customer_telephone": "+2348111111111",
        "customer_street_name": "Buyer Road",
        "customer_city_name": "Abuja",
        "customer_postal_zone": "900001",
        "customer_country": "NG",
        "customer_state": "FCT",
        "customer_lga": "AMAC",
        "step3": {
            "lines": [
                {
                    "name": "Consulting",
                    "description": "Consulting",
                    "isic_code": "7020",
                    "service_category": "Management consultancy",
                    "invoiced_quantity": 2,
                    "price_amount": 1000,
                    "price_unit": "EA",
                    "base_quantity": 1,
                }
            ]
        },
    }


def _run_zebe_derived_field_checks() -> None:
    from services.invoice_service import (
        INITIAL_PAYMENT_STATUS,
        build_invoice_schema,
        compute_totals,
        derive_invoice_kind,
        derive_tax_point_date,
        validate_wizard,
    )
    from utils.schema import InvoiceSchema

    business_id = "1c6eaf77-d0bd-455c-9c5c-500a3f1dbfb2"
    wizard = _wizard_fixture()

    errors = validate_wizard(wizard)
    assert not errors, f"fixture wizard should be valid, got: {errors}"

    wizard["computed"] = compute_totals(wizard["step3"]["lines"])
    payload = build_invoice_schema(wizard, business_id)

    assert payload["invoice_kind"] == "B2B", (
        "a customer with a TIN must derive invoice_kind=B2B"
    )
    assert derive_invoice_kind({"customer_tin": ""}) == "B2C", (
        "a no-TIN customer path must derive invoice_kind=B2C"
    )
    assert payload["tax_point_date"] == wizard["issue_date"], (
        "tax_point_date must be derived from issue_date"
    )
    assert derive_tax_point_date("20260301") == "2026-03-01"
    assert derive_tax_point_date("") is None
    assert payload["payment_status"] == INITIAL_PAYMENT_STATUS == "PENDING", (
        "invoice creation must derive an initial PENDING payment status"
    )
    assert payload["business_id"] == business_id, (
        "business_id must be passed through byte-exact (lowercase UUID)"
    )
    assert payload["tax_currency_code"] == "NGN", (
        "tax_currency_code must always be derived (PASCA requires it on every "
        "invoice, under this exact snake_case name) and reported in Naira"
    )

    line = payload["invoice_line"][0]
    assert line["price"]["price_unit"] == "EA", (
        "assembled invoice line must carry the official unit code EA"
    )
    assert abs(line["line_extension_amount"] - 2000.0) < 0.01
    totals = payload["legal_monetary_total"]
    assert abs(totals["tax_exclusive_amount"] - 2000.0) < 0.01
    assert abs(totals["payable_amount"] - 2150.0) < 0.01, (
        "monetary totals must be derived (2000 + 7.5% VAT)"
    )

    # Empty optional LGA must be omitted, populated LGA preserved.
    assert "lga" not in payload["accounting_supplier_party"]["postal_address"]
    assert (
        payload["accounting_customer_party"]["postal_address"]["lga"] == "AMAC"
    )

    model = InvoiceSchema(**payload)
    assert model.invoice_kind == "B2B"
    assert model.payment_status == "PENDING"
    assert model.tax_point_date == "2026-03-01"
    assert model.business_id == business_id
    assert model.tax_currency_code == "NGN"

    _assert_external_field_names(model)


def _assert_external_field_names(model) -> None:
    """Guard the exact external field names sent to PASCA/FIRS/NRS.

    The live sandbox rejected an invoice with
    ``invoicerequest.invoice.taxcurrencycode is required`` while the payload
    carried the camelCase ``taxCurrencyCode`` key, so the tax currency must
    always be present under the snake_case name ``tax_currency_code`` and the
    camelCase spelling must never be emitted. Every field keeps its snake_case
    wire name.
    """
    dumped = model.model_dump(exclude_none=True, by_alias=True)

    assert "tax_currency_code" in dumped, (
        "outbound payload must include tax_currency_code (PASCA requirement)"
    )
    assert dumped["tax_currency_code"] == "NGN"
    assert "taxCurrencyCode" not in dumped, (
        "the camelCase tax currency key is rejected by the sandbox and must "
        "never be serialized"
    )

    for key in (
        "irn",
        "business_id",
        "invoice_kind",
        "issue_date",
        "tax_point_date",
        "tax_currency_code",
        "payment_status",
        "invoice_type_code",
        "document_currency_code",
        "payment_means",
        "accounting_supplier_party",
        "accounting_customer_party",
        "tax_total",
        "legal_monetary_total",
        "invoice_line",
    ):
        assert key in dumped, f"outbound payload lost required field: {key}"

    party = dumped["accounting_supplier_party"]
    assert "postal_address" in party and "party_name" in party
    line = dumped["invoice_line"][0]
    assert "line_extension_amount" in line and "invoiced_quantity" in line
    assert line["price"]["price_unit"] == "EA"
    assert "payable_amount" in dumped["legal_monetary_total"]
    print("  ✓ external field names / snake_case tax_currency_code OK")


def check_zebe_outbound_serialization() -> None:
    """Every outbound InvoiceSchema dump must stay consistently serialized.

    The PASCA sandbox requires ``tax_currency_code`` on every invoice and
    rejects the camelCase spelling, so all outbound dumps go through the same
    ``model_dump(exclude_none=True, by_alias=True, mode="json")`` call shape
    and the field guardrail helper. Guard the serialization arguments in the
    invoice routes so that regression cannot silently return.
    """
    print("[zebe] outbound InvoiceSchema serialization…", flush=True)
    _purge_shared_modules()
    text = (Path(ZEBE) / "routes" / "invoice_routes.py").read_text()

    dumps = [
        args
        for args in re.findall(r"model_dump\(([^)]*)\)", text, re.DOTALL)
        if "exclude_none" in args
    ]
    assert dumps, (
        "no outbound model_dump(exclude_none=...) call found in invoice routes"
    )
    for args in dumps:
        flattened = " ".join(args.split())
        assert "by_alias=True" in flattened, (
            "outbound payloads must be serialized consistently with "
            f"by_alias=True (offending call args: {flattened})"
        )

    for marker in (
        "/api/v1/einvoice/validate",
        "/api/v1/einvoice/sign",
        "certificate",
        "public_key",
        "_outbound_invoice_payload",
        "_assert_outbound_fields",
    ):
        assert marker in text, f"invoice route lost required wiring: {marker}"

    print("  ✓ validate / sign / update payloads keep snake_case wire names")


def check_zebe_outbound_route_behavior() -> None:
    """Guard the *routes'* actual behavior, not just the schema.

    The live sandbox rejected ``validate_invoice`` payloads that carried the
    camelCase ``taxCurrencyCode`` key. This check asserts, against the real
    route source and the real serialization helper:

      * ``validate_invoice`` / ``sign_invoice`` build their outbound payload via
        ``_outbound_invoice_payload`` and never call ``model_dump`` inline;
      * the helper's output — i.e. the dict that is handed to ``post_request``
        — actually contains ``tax_currency_code`` and never leaks
        ``taxCurrencyCode``;
      * the helper refuses (500s) if the required field is ever missing.

    No external request is made: only the local serialization path is run.
    """
    print("[zebe] validate/sign outbound payload behavior…", flush=True)
    with _zebe_imports():
        _run_zebe_outbound_route_checks()
    print("  ✓ validate / sign post tax_currency_code via the field helper")


def _assert_route_uses_alias_helper(fn, name: str) -> None:
    src = inspect.getsource(fn)
    assert "_outbound_invoice_payload(" in src, (
        f"{name} must build its outbound payload with "
        "_outbound_invoice_payload() so aliases can never be omitted"
    )
    assert "model_dump(" not in src, (
        f"{name} must not call model_dump() inline — the outbound wire-field "
        "guardrail must always run"
    )
    assert "post_request(" in src, (
        f"{name} no longer posts to the external endpoint"
    )


def _run_zebe_outbound_route_checks() -> None:
    from fastapi import HTTPException

    from routes import invoice_routes as ir
    from services.invoice_service import build_invoice_schema, compute_totals
    from utils.schema import InvoiceSchema, UpdateInvoiceSchema

    _assert_route_uses_alias_helper(ir.validate_invoice, "validate_invoice")
    _assert_route_uses_alias_helper(ir.sign_invoice, "sign_invoice")

    update_src = inspect.getsource(ir.update_invoice)
    assert "_outbound_update_payload(" in update_src, (
        "update_invoice must serialize through _outbound_update_payload()"
    )
    assert "model_dump(" not in update_src, (
        "update_invoice must not call model_dump() inline"
    )

    assert "tax_currency_code" in ir.REQUIRED_OUTBOUND_FIELDS, (
        "tax_currency_code must be an enforced outbound wire field"
    )
    assert "taxCurrencyCode" in ir.FORBIDDEN_OUTBOUND_FIELDS, (
        "the camelCase tax currency name must never reach the wire"
    )

    business_id = "1c6eaf77-d0bd-455c-9c5c-500a3f1dbfb2"
    wizard = _wizard_fixture()
    wizard["computed"] = compute_totals(wizard["step3"]["lines"])
    model = InvoiceSchema(**build_invoice_schema(wizard, business_id))

    for operation in ("validate", "sign"):
        payload = ir._outbound_invoice_payload(model, operation=operation)
        assert "tax_currency_code" in payload, (
            f"the {operation} payload passed to post_request must include "
            "tax_currency_code"
        )
        assert payload["tax_currency_code"] == "NGN"
        assert "taxCurrencyCode" not in payload, (
            f"the {operation} payload leaked the camelCase tax currency name"
        )
        for key in ("irn", "business_id", "invoice_line", "payment_status"):
            assert key in payload, (
                f"the {operation} payload lost required field {key}"
            )

    # The signing route posts the invoice payload plus the credentials; make
    # sure merging them cannot drop the alias.
    signing_payload = {
        **ir._outbound_invoice_payload(model, operation="sign"),
        "certificate": "cert",
        "public_key": "key",
    }
    assert signing_payload["tax_currency_code"] == "NGN"
    assert signing_payload["certificate"] and signing_payload["public_key"]

    # The guardrail must actually fire when the required field is missing.
    missing_failure = ""
    try:
        ir._assert_outbound_fields({"irn": "X"}, operation="validate")
    except HTTPException as exc:
        # Expected guardrail failure: capture the detail only, no traceback.
        logging.exception("Unexpected error")
        missing_failure = str(exc.detail)
        logging.getLogger("smoke_tests").debug(
            "missing tax_currency_code rejected as expected"
        )
    if not missing_failure:
        raise AssertionError(
            "_assert_outbound_fields must raise when tax_currency_code is "
            "missing from an outbound payload"
        )

    leak_failure = ""
    try:
        ir._assert_outbound_fields(
            {"tax_currency_code": "NGN", "taxCurrencyCode": "NGN"},
            operation="validate",
        )
    except HTTPException as exc:
        # Expected guardrail failure: capture the detail only, no traceback.
        logging.exception("Unexpected error")
        leak_failure = str(exc.detail)
        logging.getLogger("smoke_tests").debug(
            "camelCase tax currency leak rejected as expected"
        )
    if not leak_failure:
        raise AssertionError(
            "_assert_outbound_fields must raise when the camelCase tax "
            "currency field leaks into an outbound payload"
        )

    update_payload = ir._outbound_update_payload(
        UpdateInvoiceSchema(payment_status="PAID", reference="REF-1"),
        operation="update-status",
    )
    assert update_payload["payment_status"] == "PAID"
    assert "taxCurrencyCode" not in update_payload


def check_wizard_onboarding_wiring() -> None:
    """Guard the new inline signing-secret setup flow so a future refactor
    doesn't silently drop the onboarding path."""
    print("[zefe] wizard signing-secret onboarding wiring…", flush=True)
    # File-read only, no imports — but purge caches defensively.
    _purge_shared_modules()
    text = (Path(ZEFE) / "routes" / "wizard_routes.py").read_text()
    for marker in (
        "_signing_secret_setup_card",
        "/invoices/wizard/set-secret",
        "get_user_secret_status",
        "has_secret",
    ):
        assert marker in text, f"missing wizard wiring marker: {marker}"
    print("  ✓ signing-secret onboarding wiring is present")


def check_zefe_derived_fields_readonly() -> None:
    """Derived fields must never be wizard inputs.

    The read-only "Derived automatically" panel was removed from step 4 (it
    restated values the user had already entered), so the guardrail is now:
    the IRN stays a read-only block, the panel is gone, and no derived field
    is ever exposed as an editable input.
    """
    print("[zefe] derived fields are never inputs…", flush=True)
    _purge_shared_modules()
    text = (Path(ZEFE) / "routes" / "wizard_routes.py").read_text()
    assert "_irn_readonly_block" in text, (
        "the IRN must stay a read-only, system-generated block"
    )
    for removed in (
        "_derived_fields_card",
        "_derived_field_row",
        "_derived_invoice_kind",
        "Derived automatically",
    ):
        assert removed not in text, (
            f"the derived-fields panel must stay removed from the UI: {removed}"
        )
    for forbidden in (
        'name="invoice_kind"',
        'name="tax_point_date"',
        'name="tax_currency_code"',
        'name="payment_status"',
        'name="line_extension_amount"',
        'name="payable_amount"',
    ):
        assert forbidden not in text, (
            f"derived field is exposed as a wizard input: {forbidden}"
        )
    print("  ✓ no manual inputs for derived invoice fields")


# --------------------------------------------------------------------------
# 5. Simplified item import: single `code` column, detected classification
# --------------------------------------------------------------------------


def _run_zebe_simple_import_checks(db, user) -> None:
    """Guard the simple import layout and its per-row error reporting.

    Users upload `sku, name, description, code, unit_price, price_unit,
    base_quantity`. The classification kind must be detected from the code
    itself (HS `XXXX.XX` vs 4-digit ISIC) and mapped onto the stored
    hsn_*/isic_* fields, with a concise category fallback. The older detailed
    columns must keep working, and every rule violation must be reported
    per row instead of aborting the import.
    """
    from auth import create_access_token
    from routes.item_routes import (
        CATEGORY_MAX_LENGTH,
        DETAILED_IMPORT_COLUMNS,
        IMPORT_COLUMNS,
        SIMPLE_IMPORT_COLUMNS,
        _process_import_rows,
        concise_category,
        detect_classification,
        list_items,
        normalize_import_row,
    )

    assert SIMPLE_IMPORT_COLUMNS == [
        "sku",
        "name",
        "description",
        "code",
        "unit_price",
        "price_unit",
        "base_quantity",
    ], f"the documented simple import layout changed: {SIMPLE_IMPORT_COLUMNS}"
    assert IMPORT_COLUMNS == SIMPLE_IMPORT_COLUMNS, (
        "the user-facing import columns must be the simple layout"
    )
    for legacy in ("hsn_code", "hsn_category", "isic_code", "isic_category"):
        assert legacy in DETAILED_IMPORT_COLUMNS, (
            f"the detailed layout must stay supported (missing {legacy})"
        )

    # --- code detection -------------------------------------------------
    assert detect_classification("1006.10") == "product"
    assert detect_classification(" 8471.30 ") == "product"
    assert detect_classification("7020") == "service"
    assert detect_classification("0112") == "service"
    assert detect_classification("100610") is None
    assert detect_classification("1006.1") is None
    assert detect_classification("banana") is None
    assert detect_classification("") is None
    assert detect_classification(None) is None

    # --- concise category fallback --------------------------------------
    long_label = (
        "Rice, semi-milled or wholly milled, whether or not polished; "
        "broken rice of every description"
    )
    short = concise_category("", long_label)
    assert short and len(short) <= CATEGORY_MAX_LENGTH, (
        f"category fallback must stay concise (got {short!r})"
    )
    assert ";" not in short, "category fallback must keep one clause only"
    assert concise_category("", None, "") == ""

    # --- row normalization ----------------------------------------------
    payload, err = normalize_import_row(
        {
            "SKU": "NORM-P1",
            "Name": "Premium rice",
            "code": "1006.10",
            "unit_price": "1000",
            "price_unit": "KGM",
        }
    )
    assert not err, f"simple product row should normalize cleanly: {err}"
    assert payload["hsn_code"] == "1006.10"
    assert payload["hsn_category"] == "Premium rice", (
        "the item name is the concise category fallback"
    )
    assert "isic_code" not in payload and "isic_category" not in payload

    payload, err = normalize_import_row(
        {
            "name": "Advisory retainer",
            "code": "7020",
            "category": "Management consultancy",
            "unit_price": "500",
        }
    )
    assert not err, f"simple service row should normalize cleanly: {err}"
    assert payload["isic_code"] == "7020"
    assert payload["isic_category"] == "Management consultancy", (
        "an explicit category column must win over the fallback"
    )
    assert "hsn_code" not in payload

    payload, err = normalize_import_row(
        {
            "name": "Detailed legacy row",
            "hsn_code": "1006.10",
            "hsn_category": "Rice",
            "isic_code": "",
            "isic_category": "",
            "unit_price": "10",
            "price_unit": "EA",
        }
    )
    assert not err, f"detailed columns must still work: {err}"
    assert payload["hsn_code"] == "1006.10"
    assert payload["hsn_category"] == "Rice"

    _, err = normalize_import_row(
        {"name": "Both", "hsn_code": "1006.10", "isic_code": "7020"}
    )
    assert "not both" in err, (
        f"two classifications on one row must be rejected (got {err!r})"
    )

    _, err = normalize_import_row({"name": "No code", "unit_price": "1"})
    assert err.startswith("code:"), f"a missing code must be named: {err!r}"

    _, err = normalize_import_row({"name": "Bad code", "code": "banana"})
    assert "code:" in err and "XXXX.XX" in err, (
        f"an unrecognisable code must be explained: {err!r}"
    )

    # --- end to end import ----------------------------------------------
    rows = [
        {
            "sku": "SIMPLE-P1",
            "name": "Premium rice (simple)",
            "description": "50kg bag",
            "code": "1006.10",
            "unit_price": "42000",
            "price_unit": "KGM",
            "base_quantity": "1",
        },
        {
            "sku": "SIMPLE-S1",
            "name": "Advisory retainer (simple)",
            "description": "",
            "code": "7020",
            "unit_price": "1500",
            "price_unit": "EA",
            "base_quantity": "1",
        },
        {
            "sku": "SIMPLE-BAD-CODE",
            "name": "Unclassifiable",
            "code": "12345",
            "unit_price": "10",
            "price_unit": "EA",
        },
        {
            "sku": "SIMPLE-BAD-UNIT",
            "name": "Legacy free text unit",
            "code": "7020",
            "unit_price": "10",
            "price_unit": "NGN per 1",
        },
        {
            "sku": "SIMPLE-BAD-PRICE",
            "name": "Priced later",
            "code": "7020",
            "unit_price": "0",
            "price_unit": "EA",
        },
        {
            "sku": "SIMPLE-BAD-BASE",
            "name": "Zero base quantity",
            "code": "7020",
            "unit_price": "10",
            "price_unit": "EA",
            "base_quantity": "0",
        },
    ]
    result = _process_import_rows(rows, db=db, business_id=user.business_id)
    assert result.created == 2, (
        f"both valid simple rows should be created (got {result.created})"
    )
    assert result.skipped == 4, (
        f"every invalid rule must skip its own row (got {result.skipped})"
    )
    assert len(result.errors) == 4, (
        "each skipped row must carry one concise reason"
    )
    blob = " | ".join(result.errors)
    for tag in (
        "SIMPLE-BAD-CODE",
        "SIMPLE-BAD-UNIT",
        "SIMPLE-BAD-PRICE",
        "SIMPLE-BAD-BASE",
    ):
        assert tag in blob, f"skipped row {tag} is not identifiable: {blob}"
    assert "price_unit" in blob, (
        f"the free text unit row must name price_unit: {blob}"
    )
    assert "unit_price" in blob, (
        f"the zero price row must name unit_price: {blob}"
    )
    assert "base_quantity" in blob, (
        f"the zero base quantity row must name base_quantity: {blob}"
    )

    token = create_access_token({"sub": str(user.id)})
    page = list_items(
        token=token, db=db, search="SIMPLE-P1", offset=0, limit=10
    )
    assert page["total"] == 1, "the imported product row was not persisted"
    stored = page["items"][0]
    assert stored.hsn_code == "1006.10" and stored.hsn_category
    assert stored.isic_code is None
    assert stored.price_unit == "KGM"

    services = list_items(
        token=token,
        db=db,
        search="SIMPLE-S1",
        kind="service",
        offset=0,
        limit=10,
    )
    assert services["total"] == 1, "the imported service row was not persisted"
    assert services["items"][0].isic_code == "7020"

    # Re-importing the same SKUs updates instead of duplicating.
    again = _process_import_rows(rows[:2], db=db, business_id=user.business_id)
    assert again.updated == 2 and again.created == 0, (
        "re-importing a known SKU must update it, not duplicate it"
    )
    print("  ✓ simple import code detection / per-row errors OK")


# --------------------------------------------------------------------------
# 6. Customer directory: import + active state parity with items
# --------------------------------------------------------------------------


def check_zefe_customer_directory_wiring() -> None:
    """Customers must keep import, status filtering and restore flows."""
    print("[zefe] customer import / active state wiring\u2026", flush=True)
    _purge_shared_modules()
    text = (Path(ZEFE) / "routes" / "customer_routes.py").read_text()
    for marker in (
        "/customers/import",
        "/customers/import-overlay",
        "/customers/bulk-confirm",
        "/customers/{cid}/deactivate",
        "/customers/{cid}/restore",
        "import_customers",
        "bulk_activate_customers",
        "restore_customer",
        "_status_badge",
        "IMPORT_COLUMNS",
        'Option("Inactive"',
    ):
        assert marker in text, f"customer directory lost wiring: {marker}"

    backend = (Path(ZEBE) / "routes" / "customer_routes.py").read_text()
    for marker in (
        "/import",
        "/bulk-delete",
        "/bulk-activate",
        "/{id}/restore",
        "is_active",
        "parse_import_file",
    ):
        assert marker in backend, f"customer API lost wiring: {marker}"
    print("  ✓ customer import, deactivate, restore and filters are wired")


# --------------------------------------------------------------------------
# 7. Wizard stage 3: catalog first, one-off fallback
# --------------------------------------------------------------------------


def check_zefe_stage3_ux() -> None:
    """Stage 3 must offer exactly two non-competing ways to add a line.

    The saved-item flow is a search-first picker (never a plain dropdown of
    the whole catalog), and the one-off flow opens manual item details plus
    the HS / ISIC lookup on their own. A saved-item line never renders the
    manual classification fields beside its locked identity.
    """
    print("[zefe] stage 3 saved-item / one-off UX\u2026", flush=True)
    _purge_shared_modules()
    text = (Path(ZEFE) / "routes" / "wizard_routes.py").read_text()
    for marker in (
        "_add_actions",
        "_row_identity_cell",
        "_row_adjust_cell",
        "_saved_item_picker_modal",
        "_picker_search_input",
        "_catalog_results",
        "_saved_item_summary",
        "_locked_basis_row",
        "_line_from_catalog_item",
        "Add saved item",
        "Add one-off item",
        "/invoices/wizard/line/picker",
        "/invoices/wizard/line/one-off",
        "/invoices/wizard/line/catalog",
        "/invoices/wizard/line/catalog/apply",
        "/invoices/wizard/line/{idx}/update",
        "item_source_badge",
    ):
        assert marker in text, f"stage 3 lost wiring: {marker}"
    assert text.count("Manage items") == 1, (
        "the catalog link belongs only in the empty saved-item state, never "
        "inside a selected saved-item detail"
    )
    assert "manual = not _is_catalog_line(line)" in text, (
        "the line modal must know whether the row came from the catalog"
    )
    assert "if manual:" in text, (
        "the classification lookup must only render for one-off lines"
    )
    for removed in (
        "_row_catalog_select",
        "_catalog_block",
        "_add_row_button",
        "/invoices/wizard/step/3/rows/add",
    ):
        assert removed not in text, (
            "the two flows must not compete with the old inline catalog "
            f"dropdown / blank row path: {removed}"
        )
    for marker in ("discount_type", "fee_type", "percent", "flat"):
        assert marker in text, (
            f"per-row discount / fee controls lost wiring: {marker}"
        )
    print("  \u2713 search-first saved items, one-off path, locked identity")


# --------------------------------------------------------------------------
# 7b. Shared item presentation helpers (Items page + wizard stage 3)
# --------------------------------------------------------------------------

#: Every presentation helper both item surfaces must share.
ITEM_PRESENTATION_HELPERS: tuple[str, ...] = (
    "item_kind",
    "item_code",
    "item_category",
    "item_sku",
    "item_kind_badge",
    "item_classification_badge",
    "item_classification_meta",
    "item_status_badge",
    "item_source_badge",
    "item_sku_text",
    "unit_chip",
    "item_price_summary",
    "item_identity",
    "item_empty_panel",
    "item_search_empty_copy",
)

#: Local badge / metadata builders that must stay deleted from the routes.
STALE_ITEM_PRESENTATION_DEFS: tuple[tuple[str, str], ...] = (
    ("routes/item_routes.py", "def _kind_of("),
    ("routes/item_routes.py", "def _kind_badge("),
    ("routes/item_routes.py", "def _status_badge("),
)


def check_zefe_item_presentation_shared() -> None:
    """One presentation layer for items, reused by both surfaces.

    The Items page and invoice stage 3 render the same object, so the badges,
    HS / ISIC metadata, unit / SKU treatment, status / source pills and empty
    state tone must all come from ``ui/components.py`` rather than being
    re-implemented per route module.
    """
    print("[zefe] shared item presentation helpers\u2026", flush=True)
    _purge_shared_modules()
    components_path = Path(ZEFE) / "ui" / "components.py"
    tree = ast.parse(components_path.read_text(), filename=str(components_path))
    defined = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    missing = [n for n in ITEM_PRESENTATION_HELPERS if n not in defined]
    if missing:
        raise AssertionError(
            "ui/components.py is missing shared item helpers: "
            + ", ".join(missing)
        )

    items = (Path(ZEFE) / "routes" / "item_routes.py").read_text()
    wizard = (Path(ZEFE) / "routes" / "wizard_routes.py").read_text()
    for name, text in (("item_routes", items), ("wizard_routes", wizard)):
        for helper in (
            "item_kind",
            "item_kind_badge",
            "item_classification_badge",
            "item_identity",
            "unit_chip",
            "item_search_empty_copy",
        ):
            assert helper in text, (
                f"{name} must reuse the shared {helper} helper instead of "
                "its own item presentation code"
            )

    for rel, stale in STALE_ITEM_PRESENTATION_DEFS:
        text = (Path(ZEFE) / rel).read_text()
        assert stale not in text, (
            f"{rel} still defines its own '{stale}' — item presentation "
            "belongs to ui/components.py only"
        )

    for legacy in (
        "bg-indigo-100 text-indigo-700",
        "bg-purple-100 text-purple-700",
    ):
        assert legacy not in items and legacy not in wizard, (
            "item kind badges must be built by item_kind_badge, not by "
            f"hand-rolled classes ({legacy})"
        )
    print(
        "  \u2713 items page and invoice stage 3 share one presentation layer"
    )


# --------------------------------------------------------------------------
# 8. PDF: invoice lines print the item name only
# --------------------------------------------------------------------------


def check_zefe_pdf_item_name_only() -> None:
    print("[zefe] PDF prints item name only\u2026", flush=True)
    _purge_shared_modules()
    text = (Path(ZEFE) / "services" / "pdf_service.py").read_text()
    assert 'cell = f"<b>{name}</b>"' in text, (
        "the PDF invoice line must print the item name only"
    )
    assert 'ln.get("description")' not in text, (
        "the long classification description must stay off the PDF line"
    )
    assert 'item.get("description")' not in text, (
        "the item description must stay off the PDF line"
    )
    assert "CLASSIFICATION CODE" in text, (
        "the classification code column must stay on the PDF"
    )
    print("  ✓ invoice line renders the item name, code stays in its column")


# --------------------------------------------------------------------------
# 9. Docs and wording guardrails
# --------------------------------------------------------------------------

_EM_DASH = "\u2014"

#: Files whose user-facing wording and comments must stay em dash free.
EM_DASH_FREE_FILES: tuple[tuple[str, str], ...] = (
    (ZEBE, "routes/item_routes.py"),
    (ZEBE, "routes/customer_routes.py"),
    (ZEBE, "services/import_utils.py"),
    (str(REPO_ROOT.parent), "report.md"),
)


def check_no_em_dashes() -> None:
    print("[docs] key files stay em dash free\u2026", flush=True)
    offenders: list[str] = []
    for base, rel in EM_DASH_FREE_FILES:
        path = Path(base) / rel
        if not path.exists():
            raise AssertionError(f"missing file for the wording check: {rel}")
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            if _EM_DASH in line:
                offenders.append(f"{rel}:{lineno}")
    if offenders:
        raise AssertionError("em dash found in: " + ", ".join(offenders[:10]))
    print(f"  ✓ {len(EM_DASH_FREE_FILES)} files use plain punctuation")


def check_import_column_docs() -> None:
    """The simple import layout must be documented everywhere users see it."""
    print("[docs] simple import columns documented\u2026", flush=True)
    _purge_shared_modules()
    frontend = (Path(ZEFE) / "routes" / "item_routes.py").read_text()
    assert "code, unit_price, price_unit, " in frontend, (
        "the item import overlay must list the simple columns"
    )
    assert "XXXX.XX" in frontend, (
        "the overlay must explain how the classification code is detected"
    )

    endpoints_doc = (REPO_ROOT.parent / "endpoint.md").read_text()
    assert (
        "sku, name, description, code, unit_price, price_unit, base_quantity"
        in endpoints_doc
    ), "endpoint.md must document the simple import layout"

    report = REPO_ROOT.parent / "report.md"
    assert report.exists(), "report.md is missing from the app root"
    report_text = report.read_text()
    for marker in (
        "```mermaid",
        "tax_currency_code",
        "INV{sequence}",
        "/items/import",
        "FastHTML",
        "FastAPI",
    ):
        assert marker in report_text, f"report.md is missing: {marker}"
    print("  ✓ overlay, endpoint reference and report.md agree")


# --------------------------------------------------------------------------
# 10. Shared product / service lookup ranking relevance
# --------------------------------------------------------------------------


def _lookup_product_rows() -> list[dict]:
    """Representative FIRS HS candidates, in the upstream product shape."""
    return [
        {
            "hscode": "1006.10",
            "description": "Rice in the husk (paddy or rough)",
            "product_category": "Cereals",
        },
        {
            "hscode": "1006.30",
            "description": (
                "Semi-milled or wholly milled rice, whether or not "
                "polished or glazed"
            ),
            "product_category": "Cereals",
        },
        {
            "hscode": "0714.10",
            "description": "Manioc (cassava) roots, fresh or dried",
            "product_category": (
                "Edible vegetables and certain roots and tubers"
            ),
        },
        {
            "hscode": "0714.30",
            "description": "Yams (Dioscorea spp.), fresh or dried",
            "product_category": (
                "Edible vegetables and certain roots and tubers"
            ),
        },
        {
            "hscode": "0701.90",
            "description": "Potatoes, fresh or chilled, other",
            "product_category": "Edible vegetables",
        },
        {
            "hscode": "1001.99",
            "description": "Wheat and meslin, other",
            "product_category": "Cereals",
        },
        {
            "hscode": "1005.90",
            "description": "Maize (corn), other",
            "product_category": "Cereals",
        },
        {
            "hscode": "1008.29",
            "description": "Millet, other",
            "product_category": "Cereals",
        },
        {
            "hscode": "1007.90",
            "description": "Grain sorghum, other",
            "product_category": "Cereals",
        },
        {
            "hscode": "0713.33",
            "description": "Kidney beans, dried and shelled",
            "product_category": "Leguminous vegetables",
        },
        {
            "hscode": "0302.11",
            "description": "Trout, fresh or chilled fish",
            "product_category": "Fish and crustaceans",
        },
        {
            "hscode": "0201.30",
            "description": (
                "Meat of bovine animals, boneless, fresh or chilled"
            ),
            "product_category": "Meat and edible meat offal",
        },
        {
            "hscode": "0207.14",
            "description": (
                "Cuts and edible offal of poultry (chicken), frozen"
            ),
            "product_category": "Meat and edible meat offal",
        },
        {
            "hscode": "0407.21",
            "description": (
                "Eggs of fowls of the species Gallus domesticus, fresh"
            ),
            "product_category": "Birds eggs",
        },
        {
            "hscode": "0401.20",
            "description": "Milk and cream, not concentrated",
            "product_category": "Dairy produce",
        },
        {
            "hscode": "0702.00",
            "description": "Tomatoes, fresh or chilled",
            "product_category": "Edible vegetables",
        },
        {
            "hscode": "0703.10",
            "description": "Onions and shallots, fresh or chilled",
            "product_category": "Edible vegetables",
        },
        {
            "hscode": "0904.21",
            "description": "Pepper of the genus Capsicum, dried",
            "product_category": "Coffee, tea and spices",
        },
        {
            "hscode": "2501.00",
            "description": "Salt and pure sodium chloride",
            "product_category": "Salt and mineral substances",
        },
        {
            "hscode": "1701.99",
            "description": "Cane or beet sugar, refined",
            "product_category": "Sugars and sugar confectionery",
        },
        {
            "hscode": "1101.00",
            "description": "Wheat or meslin flour",
            "product_category": "Products of the milling industry",
        },
        {
            "hscode": "1905.90",
            "description": "Bread, pastry, cakes and biscuits, other",
            "product_category": "Bakers wares",
        },
        {
            "hscode": "3004.90",
            "description": (
                "Medicaments for therapeutic or prophylactic uses, other"
            ),
            "product_category": "Pharmaceutical products",
        },
        {
            "hscode": "8471.30",
            "description": (
                "Portable automatic data processing machines (laptop computers)"
            ),
            "product_category": "Machinery and mechanical appliances",
        },
        {
            "hscode": "8471.41",
            "description": (
                "Automatic data processing machines, desktop computers"
            ),
            "product_category": "Machinery and mechanical appliances",
        },
        {
            "hscode": "8443.32",
            "description": (
                "Printing machinery capable of connecting to a computer "
                "(printers)"
            ),
            "product_category": "Machinery and mechanical appliances",
        },
        {
            "hscode": "8517.13",
            "description": "Smartphones (cellular telephones)",
            "product_category": "Telephone sets and other apparatus",
        },
        {
            "hscode": "8528.72",
            "description": "Television reception apparatus, colour",
            "product_category": "Monitors and projectors",
        },
        {
            "hscode": "8528.52",
            "description": (
                "Monitors capable of connecting to a computer display"
            ),
            "product_category": "Monitors and projectors",
        },
        {
            "hscode": "8418.10",
            "description": "Combined refrigerator-freezers",
            "product_category": "Machinery and mechanical appliances",
        },
        {
            "hscode": "8418.69",
            "description": (
                "Water coolers and dispensers, refrigerating equipment"
            ),
            "product_category": "Machinery and mechanical appliances",
        },
        {
            "hscode": "6403.99",
            "description": (
                "Footwear with outer soles of rubber and uppers of "
                "leather, other"
            ),
            "product_category": "Footwear",
        },
        {
            "hscode": "2710.19",
            "description": "Gas oils and diesel fuel, petroleum oils",
            "product_category": "Mineral fuels",
        },
        {
            "hscode": "8703.23",
            "description": (
                "Motor cars with spark-ignition engine of 1500 to 3000 cc"
            ),
            "product_category": "Vehicles other than railway",
        },
        {
            "hscode": "4011.10",
            "description": ("New pneumatic tyres of rubber for motor cars"),
            "product_category": "Rubber and articles thereof",
        },
        {
            "hscode": "4901.99",
            "description": (
                "Printed books, brochures and similar printed matter"
            ),
            "product_category": "Printed books and newspapers",
        },
        {
            "hscode": "4802.56",
            "description": "Uncoated paper for writing and printing",
            "product_category": "Paper and paperboard",
        },
        {
            "hscode": "5208.52",
            "description": "Woven cotton fabrics, printed",
            "product_category": "Textile fabrics",
        },
        {
            "hscode": "6203.42",
            "description": ("Men's or boys' trousers of cotton (apparel)"),
            "product_category": (
                "Articles of apparel and clothing accessories"
            ),
        },
        {
            "hscode": "2201.10",
            "description": "Mineral waters and aerated waters, bottled",
            "product_category": "Beverages",
        },
    ]


def _lookup_service_rows() -> list[dict]:
    """Representative FIRS ISIC candidates, in the upstream service shape."""
    return [
        {
            "code": "7020",
            "description": "Management consultancy activities",
            "category": "Professional, scientific and technical activities",
        },
        {
            "code": "6920",
            "description": (
                "Accounting, bookkeeping and auditing activities; "
                "tax consultancy"
            ),
            "category": "Professional, scientific and technical activities",
        },
        {
            "code": "6910",
            "description": "Legal activities",
            "category": "Professional, scientific and technical activities",
        },
        {
            "code": "7310",
            "description": "Advertising activities",
            "category": "Professional, scientific and technical activities",
        },
        {
            "code": "7320",
            "description": "Market research and public opinion polling",
            "category": "Professional, scientific and technical activities",
        },
        {
            "code": "6201",
            "description": "Computer programming activities",
            "category": "Information and communication",
        },
        {
            "code": "5820",
            "description": "Software publishing",
            "category": "Publishing activities",
        },
        {
            "code": "7410",
            "description": "Specialized design activities",
            "category": "Professional, scientific and technical activities",
        },
        {
            "code": "8549",
            "description": (
                "Other education and training not elsewhere classified"
            ),
            "category": "Education",
        },
        {
            "code": "4923",
            "description": "Freight transport by road",
            "category": "Transportation and storage",
        },
        {
            "code": "5320",
            "description": "Other postal and courier activities",
            "category": "Transportation and storage",
        },
        {
            "code": "7730",
            "description": (
                "Renting and leasing of other machinery and equipment"
            ),
            "category": "Administrative and support activities",
        },
        {
            "code": "4100",
            "description": "Construction of buildings",
            "category": "Construction",
        },
        {
            "code": "8121",
            "description": "General cleaning of buildings",
            "category": "Services to buildings and landscape activities",
        },
        {
            "code": "8010",
            "description": "Private security activities",
            "category": "Administrative and support activities",
        },
        {
            "code": "5610",
            "description": ("Restaurants and mobile food service activities"),
            "category": "Accommodation and food service activities",
        },
        {
            "code": "5510",
            "description": ("Short term accommodation activities (hotels)"),
            "category": "Accommodation and food service activities",
        },
        {
            "code": "6311",
            "description": ("Data processing, hosting and related activities"),
            "category": "Information and communication",
        },
        {
            "code": "6110",
            "description": "Wired telecommunications activities",
            "category": "Information and communication",
        },
        {
            "code": "6512",
            "description": "Non-life insurance",
            "category": "Financial and insurance activities",
        },
        {
            "code": "6419",
            "description": "Other monetary intermediation (banking)",
            "category": "Financial and insurance activities",
        },
        {
            "code": "6810",
            "description": (
                "Real estate activities with own or leased property"
            ),
            "category": "Real estate activities",
        },
        {
            "code": "3312",
            "description": (
                "Repair and maintenance of machinery and equipment"
            ),
            "category": "Manufacturing",
        },
        {
            "code": "3320",
            "description": (
                "Installation of industrial machinery and equipment"
            ),
            "category": "Manufacturing",
        },
        {
            # Deliberate cross-kind distractor: a product query for "rice"
            # must not be won by this manufacturing service.
            "code": "1061",
            "description": (
                "Manufacture of grain mill products, including rice milling"
            ),
            "category": "Manufacturing",
        },
    ]


#: (query, expected top kind or None, code that must appear in the top 3).
LOOKUP_PRODUCT_CASES: list[tuple[str, str | None, str]] = [
    ("rice", "product", "1006.10"),
    ("paddy rice", "product", "1006.10"),
    ("milled rice", "product", "1006.30"),
    ("yam", "product", "0714.30"),
    ("yams", "product", "0714.30"),
    ("cassava", "product", "0714.10"),
    ("manioc", "product", "0714.10"),
    ("potato", "product", "0701.90"),
    ("potatoes", "product", "0701.90"),
    ("wheat", "product", "1001.99"),
    ("maize", "product", "1005.90"),
    ("corn", "product", "1005.90"),
    ("millet", "product", "1008.29"),
    ("sorghum", "product", "1007.90"),
    ("beans", "product", "0713.33"),
    ("fish", "product", "0302.11"),
    ("meat", "product", "0201.30"),
    ("chicken", "product", "0207.14"),
    ("poultry", "product", "0207.14"),
    ("eggs", "product", "0407.21"),
    ("milk", "product", "0401.20"),
    ("dairy", "product", "0401.20"),
    ("tomato", "product", "0702.00"),
    ("onion", "product", "0703.10"),
    ("pepper", "product", "0904.21"),
    ("salt", "product", "2501.00"),
    ("sugar", "product", "1701.99"),
    ("flour", "product", "1101.00"),
    ("bread", "product", "1905.90"),
    ("drug", "product", "3004.90"),
    ("drugs", "product", "3004.90"),
    ("pharmaceutical", "product", "3004.90"),
    ("medicine", "product", "3004.90"),
    ("laptop", "product", "8471.30"),
    ("laptops", "product", "8471.30"),
    ("computer", "product", "8471.41"),
    ("computers", "product", "8471.41"),
    ("desktop", "product", "8471.41"),
    ("printer", "product", "8443.32"),
    ("printers", "product", "8443.32"),
    ("phone", "product", "8517.13"),
    ("smartphone", "product", "8517.13"),
    ("mobile phone", "product", "8517.13"),
    ("television", "product", "8528.72"),
    ("tv", "product", "8528.72"),
    ("monitor", "product", "8528.52"),
    ("fridge", "product", "8418.10"),
    ("refrigerator", "product", "8418.10"),
    ("shoes", "product", "6403.99"),
    ("sneakers", "product", "6403.99"),
    ("footwear", "product", "6403.99"),
    ("water dispenser", "product", "8418.69"),
    ("diesel", "product", "2710.19"),
    ("petrol", "product", "2710.19"),
    ("fuel", "product", "2710.19"),
    ("car", "product", "8703.23"),
    ("cars", "product", "8703.23"),
    ("tyres", "product", "4011.10"),
    ("tires", "product", "4011.10"),
    ("books", "product", "4901.99"),
    ("paper", "product", "4802.56"),
    ("fabric", "product", "5208.52"),
    ("textile", "product", "5208.52"),
    ("clothing", "product", "6203.42"),
    ("apparel", "product", "6203.42"),
    ("bottled water", "product", "2201.10"),
]

LOOKUP_SERVICE_CASES: list[tuple[str, str | None, str]] = [
    ("consulting", "service", "7020"),
    ("consultancy", "service", "7020"),
    ("management consultancy", "service", "7020"),
    ("advisory", "service", "7020"),
    ("accounting", "service", "6920"),
    ("accountant", "service", "6920"),
    ("audit", "service", "6920"),
    ("auditing", "service", "6920"),
    ("bookkeeping", "service", "6920"),
    ("tax", "service", "6920"),
    ("legal", "service", "6910"),
    ("lawyer", "service", "6910"),
    ("law", "service", "6910"),
    ("advertising", "service", "7310"),
    ("marketing", "service", "7320"),
    ("market research", "service", "7320"),
    ("branding", "service", "7410"),
    ("software", "service", "5820"),
    ("programming", "service", "6201"),
    ("developer", "service", "6201"),
    ("app development", "service", "6201"),
    ("design", "service", "7410"),
    ("graphic design", "service", "7410"),
    ("training", "service", "8549"),
    ("education", "service", "8549"),
    ("course", "service", "8549"),
    ("transport", "service", "4923"),
    ("logistics", "service", "4923"),
    ("shipping", "service", "4923"),
    ("delivery", "service", "4923"),
    ("courier", "service", "5320"),
    ("rental", "service", "7730"),
    ("leasing", "service", "7730"),
    ("rent", "service", "7730"),
    ("construction", "service", "4100"),
    ("building", "service", "4100"),
    ("cleaning", "service", "8121"),
    ("janitorial", "service", "8121"),
    ("security", "service", "8010"),
    ("guard", "service", "8010"),
    ("restaurant", "service", "5610"),
    ("catering", "service", "5610"),
    ("hotel", "service", "5510"),
    ("lodging", "service", "5510"),
    ("hosting", "service", "6311"),
    ("internet", "service", "6110"),
    ("telecom", "service", "6110"),
    ("insurance", "service", "6512"),
    ("banking", "service", "6419"),
    ("real estate", "service", "6810"),
    ("property", "service", "6810"),
    ("repair", "service", "3312"),
    ("maintenance", "service", "3312"),
    ("installation", "service", "3320"),
]

LOOKUP_CODE_CASES: list[tuple[str, str | None, str]] = [
    ("1006.10", "product", "1006.10"),
    ("8471.30", "product", "8471.30"),
    ("6403.99", "product", "6403.99"),
    ("3004.90", "product", "3004.90"),
    ("8517.13", "product", "8517.13"),
    ("7020", "service", "7020"),
    ("6201", "service", "6201"),
    ("4923", "service", "4923"),
    ("6920", "service", "6920"),
    ("8121", "service", "8121"),
]

LOOKUP_COMPLEX_CASES: list[tuple[str, str | None, str]] = [
    ("premium rice 50kg bag", "product", "1006.10"),
    ("management consulting retainer", "service", "7020"),
    ("laptop computer for office", "product", "8471.30"),
    ("annual software subscription", "service", "5820"),
    ("fresh tomatoes and onions", "product", "0703.10"),
    ("office cleaning services monthly", "service", "8121"),
    ("cassava tubers export", "product", "0714.10"),
    ("diesel fuel supply", "product", "2710.19"),
    ("hotel accommodation booking", "service", "5510"),
    ("legal activities retainer", "service", "6910"),
    ("printed books for schools", "product", "4901.99"),
    ("water dispenser for office", "product", "8418.69"),
]


def check_zefe_lookup_ranking() -> None:
    """One shared ranker for the item and invoice-line classification lookup.

    The Items page lookup and the wizard one-off line lookup both go through
    ``services.lookup_ranking``, so this check exercises that single ranker
    with more than 100 product, service, code, synonym and complex queries
    against representative HS / ISIC candidates.
    """
    print("[zefe] shared lookup ranking relevance\u2026", flush=True)
    with _SubsystemPath(ZEFE, sibling=ZEBE):
        from services import lookup_ranking

        _assert_lookup_helpers(lookup_ranking)
        _assert_lookup_relevance(lookup_ranking)
        _assert_lookup_surfaces_share_ranker()


def _assert_lookup_helpers(lr) -> None:
    assert lr.detect_code_kind("1006.10") == "product"
    assert lr.detect_code_kind("7020") == "service"
    assert lr.detect_code_kind("100610") is None
    assert lr.detect_code_kind("rice") is None
    assert lr.is_code_query("0112") and not lr.is_code_query("consulting")

    assert lr.detect_bias("rice") == "product"
    assert lr.detect_bias("consulting") == "service"
    assert lr.detect_bias("blue widget") == "neutral"

    terms = [t.lower() for t in lr.expand_search_terms("drugs")]
    assert "drugs" in terms and "pharmaceutical" in terms, (
        f"synonym expansion lost the catalog wording: {terms}"
    )
    assert len(lr.expand_search_terms("rice", limit=3)) <= 3
    assert lr.expand_search_terms("") == []

    # Malformed upstream rows are ignored rather than crashing the lookup.
    assert lr.normalize_product_hits([{"description": "no code"}]) == []
    assert lr.normalize_service_hits(["not a dict", None]) == []

    # De-duplication is on (kind, code), so a term fan-out cannot repeat a hit.
    dup_products = _lookup_product_rows()[:1] * 4
    ranked = lr.rank_lookup_results("rice", dup_products, [])
    codes = [h["code"] for h in ranked]
    assert len(codes) == len(set(codes)) == 1, (
        f"duplicate candidates were not merged: {codes}"
    )
    for hit in ranked:
        assert set(hit) == {"kind", "code", "label", "category"}
        assert hit["kind"] in ("product", "service")

    assert lr.rank_lookup_results("", _lookup_product_rows(), []) == []
    print("  \u2713 code detection, bias, expansion and de-duplication OK")


def _assert_lookup_relevance(lr) -> None:
    products = _lookup_product_rows()
    services = _lookup_service_rows()
    cases = (
        LOOKUP_PRODUCT_CASES
        + LOOKUP_SERVICE_CASES
        + LOOKUP_CODE_CASES
        + LOOKUP_COMPLEX_CASES
    )
    assert len(cases) >= 100, (
        f"the relevance set must stay broad (got {len(cases)} queries)"
    )
    assert len(LOOKUP_PRODUCT_CASES) >= 40
    assert len(LOOKUP_SERVICE_CASES) >= 40

    failures: list[str] = []
    for query, expected_kind, expected_code in cases:
        hits = lr.rank_lookup_results(query, products, services, limit=10)
        if not hits:
            failures.append(f"{query!r}: no results")
            continue
        if expected_kind and hits[0]["kind"] != expected_kind:
            failures.append(
                f"{query!r}: top hit is {hits[0]['kind']} "
                f"{hits[0]['code']}, expected a {expected_kind}"
            )
        top_codes = [h["code"] for h in hits[:3]]
        if expected_code not in top_codes:
            failures.append(
                f"{query!r}: {expected_code} missing from top 3 {top_codes}"
            )
    if failures:
        raise AssertionError(
            f"{len(failures)}/{len(cases)} lookup relevance failures:\n  - "
            + "\n  - ".join(failures[:15])
        )

    # A product query must not be won by an unrelated service, and the
    # other way round.
    rice = lr.rank_lookup_results("rice", products, services, limit=10)
    assert [h["kind"] for h in rice[:2]] == ["product", "product"], (
        f"'rice' must rank HS results first: {rice[:3]}"
    )
    consulting = lr.rank_lookup_results(
        "consulting", products, services, limit=10
    )
    assert all(h["kind"] == "service" for h in consulting[:3]), (
        f"'consulting' must rank ISIC results first: {consulting[:3]}"
    )

    # FIRS constraints are preserved: a hit is a product HS code or a
    # service ISIC code, never both and never rewritten.
    for hit in rice + consulting:
        if hit["kind"] == "product":
            assert re.match(r"^\d{4}\.\d{2}$", hit["code"]), hit
        else:
            assert re.match(r"^\d{4}$", hit["code"]), hit

    print(f"  \u2713 {len(cases)} queries return a high-relevance top result")


def _assert_lookup_surfaces_share_ranker() -> None:
    """Neither surface may re-implement its own ranking."""
    items = (Path(ZEFE) / "routes" / "item_routes.py").read_text()
    wizard = (Path(ZEFE) / "routes" / "wizard_routes.py").read_text()
    for name, text in (("item_routes", items), ("wizard_routes", wizard)):
        assert "lookup_ranking" in text, (
            f"{name} must use the shared lookup ranker"
        )
        assert "search_and_rank_classifications(" in text, (
            f"{name} must search through the shared ranker"
        )
        for stale in ("SYNONYMS", "PRODUCT_HINTS", "SERVICE_HINTS"):
            assert stale not in text, (
                f"{name} still carries its own {stale} table; the ranking "
                "tables belong to services/lookup_ranking.py only"
            )
    print("  \u2713 items page and invoice wizard share one ranking path")


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def check_zebe_env_isolation() -> None:
    """Guard the harness's own DB isolation before anything else runs.

    This is the regression that broke the first cluster: a backend import that
    happened before (or in spite of) the isolated SQLite DATABASE_URL tried to
    load psycopg2 and blew up. Assert the guardrails directly:

      * the isolated SQLite URL is configured and re-assertable;
      * a ``load_dotenv(override=True)`` call — exactly what utils.database
        does — can no longer replace it;
      * importing zebe through :func:`_zebe_imports` yields a SQLite engine;
      * purging drops the cached backend modules so the next check re-imports
        them against its own environment.
    """
    print("[zebe] harness DB isolation…", flush=True)
    db_path = _configure_zebe_env()
    assert db_path, "no isolated SQLite database was configured"
    assert os.environ["DATABASE_URL"] == f"sqlite:///{db_path}"

    try:
        from dotenv import load_dotenv

        load_dotenv(override=True)
    except ImportError:
        logging.getLogger("smoke_tests").debug("python-dotenv not installed")
    assert os.environ["DATABASE_URL"] == f"sqlite:///{db_path}", (
        "load_dotenv(override=True) clobbered the isolated DATABASE_URL — the "
        "dotenv guard is not installed early enough"
    )

    with _zebe_imports():
        import utils.database as zebe_database

        assert zebe_database.is_sqlite, (
            "utils.database did not select the SQLite branch"
        )
        assert str(zebe_database.engine.url).endswith(db_path), (
            "zebe engine points at a different database file than the "
            f"isolated one ({zebe_database.engine.url})"
        )

    for name in ("utils", "utils.database", "routes", "services", "config"):
        assert name not in sys.modules, (
            f"stale cached backend module survived the purge: {name}"
        )
    print("  ✓ SQLite forced pre-import, dotenv guarded, module cache purged")


def main() -> int:
    checks = [
        check_zebe_env_isolation,
        check_zefe_syntax,
        check_zefe_zebe_contract,
        check_wizard_onboarding_wiring,
        check_zefe_derived_fields_readonly,
        check_zefe_customer_directory_wiring,
        check_zefe_stage3_ux,
        check_zefe_item_presentation_shared,
        check_zefe_lookup_ranking,
        check_zefe_pdf_item_name_only,
        check_no_em_dashes,
        check_import_column_docs,
        check_zebe_outbound_serialization,
        check_zebe_outbound_route_behavior,
        check_zebe_derived_invoice_fields,
        check_zebe_item_flow,
    ]
    failed = 0
    for check in checks:
        try:
            check()
        except AssertionError as e:
            # A failed assertion is already reported below in full; a
            # traceback here would only duplicate it.
            logging.exception("Unexpected error")
            failed += 1
            print(f"  ✗ {check.__name__}: {e}", file=sys.stderr)
        except Exception as e:  # pragma: no cover - defensive
            logging.exception("unexpected error in %s", check.__name__)
            failed += 1
            print(
                f"  ✗ {check.__name__}: unexpected error: {e!r}",
                file=sys.stderr,
            )
    _cleanup_isolated_db()
    total = len(checks)
    if failed:
        print(f"\n{failed}/{total} smoke checks failed.", file=sys.stderr)
        return 1
    print(f"\nAll {total} smoke checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
