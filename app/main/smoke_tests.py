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
import sys
import tempfile
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


def _purge_shared_modules() -> None:
    """Drop cached imports whose top-level name collides across zebe/zefe."""
    for name in list(sys.modules):
        root = name.split(".", 1)[0]
        if root in _SHARED_TOP_LEVEL_NAMES:
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
# 1. zebe: item API round trip
# --------------------------------------------------------------------------


def check_zebe_item_flow() -> None:
    print("[zebe] item API round-trip…", flush=True)
    os.environ.setdefault(
        "JWT_SECRET_KEY",
        "smoke-test-secret-key-must-be-at-least-32-bytes-long",
    )
    tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    os.environ.setdefault("DATABASE_URL", f"sqlite:///{tmp_db}")
    os.environ.setdefault("API_KEY", "smoke-test-api-key")
    os.environ.setdefault("CLIENT_SECRET", "smoke-test-client-secret")

    with _SubsystemPath(ZEBE, sibling=ZEFE):
        _run_zebe_item_flow(tmp_db)


def _run_zebe_item_flow(tmp_db: str) -> None:
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
                price_unit="NGN per 1",
            ),
            token=token,
            db=db,
        )
        assert created.sku == "SVC-001", "Item SKU not persisted"
        assert created.price_unit == "EA", (
            "legacy free-text price_unit was not normalized to the official "
            f"default unit code EA (got {created.price_unit!r})"
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
                price_unit="NGN per 1",
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
                "price_unit": "NGN per 1",
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
                "price_unit": "NGN per 1",
            },
        ]
        result = _process_import_rows(rows, db=db, business_id=user.business_id)
        assert result.created == 1, f"expected 1 create, got {result.created}"
        assert result.skipped == 1 and result.errors, (
            "bad row should have been skipped with an error"
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
    finally:
        db.close()
        try:
            os.unlink(tmp_db)
        except OSError:
            logging.exception("Unexpected error")
    print("  ✓ item API create / search / update / import / bulk-delete OK")


def _run_zebe_unit_and_irn_checks(db, user) -> None:
    """Unit-code compliance + server-side IRN reservation guardrails."""
    from services.unit_codes import (
        DEFAULT_UNIT_CODE,
        VALID_UNIT_CODES,
        coerce_unit_code,
        normalize_unit_code,
    )
    from services.invoice_service import DEFAULT_PRICE_UNIT
    from services.irn_service import parse_irn, reserve_next_irn

    assert DEFAULT_UNIT_CODE == "EA", (
        "the official user-facing default unit code should be EA (each)"
    )
    assert DEFAULT_PRICE_UNIT == DEFAULT_UNIT_CODE, (
        "invoice assembly still defaults to a non-compliant price unit"
    )
    assert coerce_unit_code("NGN per 1") == "EA"
    assert coerce_unit_code("each") == "EA"
    assert coerce_unit_code("kg") == "KGM"
    assert coerce_unit_code("") == "EA"
    # Legacy C62 rows must keep validating rather than being rejected.
    assert "C62" in VALID_UNIT_CODES
    assert normalize_unit_code("C62") == "C62"
    assert normalize_unit_code("banana") is None
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
    os.environ.setdefault(
        "JWT_SECRET_KEY",
        "smoke-test-secret-key-must-be-at-least-32-bytes-long",
    )
    os.environ.setdefault("API_KEY", "smoke-test-api-key")
    os.environ.setdefault("CLIENT_SECRET", "smoke-test-client-secret")
    with _SubsystemPath(ZEBE, sibling=ZEFE):
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
                    "price_unit": "NGN per 1",
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

    line = payload["invoice_line"][0]
    assert line["price"]["price_unit"] == "EA", (
        "legacy free-text price_unit was not normalized to EA on assembly"
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
    """The wizard must display derived fields read-only and never as inputs."""
    print("[zefe] derived fields are read-only…", flush=True)
    _purge_shared_modules()
    text = (Path(ZEFE) / "routes" / "wizard_routes.py").read_text()
    for marker in (
        "_derived_fields_card",
        "_derived_invoice_kind",
        "Derived automatically",
        "_irn_readonly_block",
    ):
        assert marker in text, f"missing derived-field marker: {marker}"
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
# Entry point
# --------------------------------------------------------------------------


def main() -> int:
    checks = [
        check_zefe_syntax,
        check_zefe_zebe_contract,
        check_wizard_onboarding_wiring,
        check_zefe_derived_fields_readonly,
        check_zebe_derived_invoice_fields,
        check_zebe_item_flow,
    ]
    failed = 0
    for check in checks:
        try:
            check()
        except AssertionError as e:
            logging.exception("Unexpected error")
            failed += 1
            print(f"  ✗ {check.__name__}: {e}", file=sys.stderr)
        except Exception as e:  # pragma: no cover - defensive
            logging.exception("Unexpected error")
            failed += 1
            print(
                f"  ✗ {check.__name__}: unexpected error: {e!r}",
                file=sys.stderr,
            )
    total = len(checks)
    if failed:
        print(f"\n{failed}/{total} smoke checks failed.", file=sys.stderr)
        return 1
    print(f"\nAll {total} smoke checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
