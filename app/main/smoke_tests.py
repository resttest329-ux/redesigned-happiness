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
    finally:
        db.close()
        try:
            os.unlink(tmp_db)
        except OSError:
            logging.exception("Unexpected error")
    print("  ✓ item API create / search / update / import / bulk-delete OK")


# --------------------------------------------------------------------------
# 2. zefe: route + UI modules parse
# --------------------------------------------------------------------------

ZEFE_MODULES = [
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


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def main() -> int:
    checks = [
        check_zefe_syntax,
        check_zefe_zebe_contract,
        check_wizard_onboarding_wiring,
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
