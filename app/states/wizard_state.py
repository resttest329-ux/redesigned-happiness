import json
import logging
import reflex as rx
from typing import TypedDict
from datetime import datetime
from app.states.auth_state import AuthState
from app.states.api_utils import normalize_detail


class WizardLine(TypedDict):
    id: str
    name: str
    description: str
    sellers_item_identification: str
    hsn_code: str
    product_category: str
    isic_code: str
    service_category: str
    invoiced_quantity: float
    price_amount: float
    price_unit: str
    base_quantity: float
    discount_rate: float
    discount_amount: float
    fee_rate: float
    fee_amount: float


class LookupItem(TypedDict):
    code: str
    value: str


class CustomerLite(TypedDict):
    id: int
    party_name: str
    tin: str
    email: str
    telephone: str
    street_name: str
    city_name: str
    postal_zone: str
    country: str
    state: str
    lga: str


class LookupHit(TypedDict):
    kind: str
    code: str
    label: str
    category: str


class StateOption(TypedDict):
    code: str
    name: str


class CountryOption(TypedDict):
    code: str
    name: str


def _empty_line() -> WizardLine:
    return {
        "id": "",
        "name": "",
        "description": "",
        "sellers_item_identification": "",
        "hsn_code": "",
        "product_category": "",
        "isic_code": "",
        "service_category": "",
        "invoiced_quantity": 1.0,
        "price_amount": 0.0,
        "price_unit": "NGN per 1",
        "base_quantity": 1.0,
        "discount_rate": 0.0,
        "discount_amount": 0.0,
        "fee_rate": 0.0,
        "fee_amount": 0.0,
    }


class WizardState(rx.State):
    # Step navigation
    current_step: int = 1
    max_step_reached: int = 1

    # Step 1: Header
    irn: str = ""
    issue_date: str = ""
    due_date: str = ""
    invoice_type_code: str = "381"
    document_currency_code: str = "NGN"
    tax_currency_code: str = "NGN"
    payment_means_code: str = "10"
    billing_reference_irn: str = ""
    billing_reference_issue_date: str = ""

    # Step 2: Supplier (from profile)
    supplier_tin: str = ""
    supplier_party_name: str = ""
    supplier_email: str = ""
    supplier_telephone: str = ""
    supplier_street_name: str = ""
    supplier_city_name: str = ""
    supplier_postal_zone: str = ""
    supplier_country: str = "NG"
    supplier_state: str = ""
    supplier_lga: str = ""

    # Step 2: Customer
    customer_id: int = 0
    customer_tin: str = ""
    customer_party_name: str = ""
    customer_email: str = ""
    customer_telephone: str = ""
    customer_street_name: str = ""
    customer_city_name: str = ""
    customer_postal_zone: str = ""
    customer_country: str = "NG"
    customer_state: str = ""
    customer_lga: str = ""
    saved_customers: list[CustomerLite] = []
    customer_search_query: str = ""
    customer_search_focused: bool = False

    # Step 3: Lines
    lines: list[WizardLine] = []
    edit_line_index: int = -1
    line_form: WizardLine = {
        "id": "",
        "name": "",
        "description": "",
        "sellers_item_identification": "",
        "hsn_code": "",
        "product_category": "",
        "isic_code": "",
        "service_category": "",
        "invoiced_quantity": 1.0,
        "price_amount": 0.0,
        "price_unit": "NGN per 1",
        "base_quantity": 1.0,
        "discount_rate": 0.0,
        "discount_amount": 0.0,
        "fee_rate": 0.0,
        "fee_amount": 0.0,
    }
    show_line_form: bool = False
    last_derived_name: str = ""
    last_derived_desc: str = ""

    # Lookup search (unified products + services)
    lookup_query: str = ""
    lookup_hits: list[LookupHit] = []
    lookup_loading: bool = False

    # Lookup options (cached)
    invoice_types: list[LookupItem] = []
    payment_means: list[LookupItem] = []
    currencies: list[dict[str, str]] = []
    states_options: list[StateOption] = []
    countries_options: list[CountryOption] = []
    lookups_loaded: bool = False

    # Step 4: Review/Submit
    assembled: dict[str, str | int | float | bool | list | dict | None] = {}
    computed_totals: dict[str, float] = {
        "line_extension_amount": 0.0,
        "tax_amount": 0.0,
        "tax_exclusive_amount": 0.0,
        "tax_inclusive_amount": 0.0,
        "payable_amount": 0.0,
    }
    validated: bool = False
    signed: bool = False
    transmitted: bool = False
    log_created: bool = False
    final_irn: str = ""

    # Signing secret modal
    show_sign_modal: bool = False
    pending_user_secret: str = ""

    # UI state
    loading: bool = False
    busy_action: str = ""
    error_message: str = ""
    success_message: str = ""
    allow_edit_irn: bool = False

    @rx.var
    def total_lines(self) -> int:
        return len(self.lines)

    @rx.var
    def filtered_saved_customers(self) -> list[CustomerLite]:
        q = (self.customer_search_query or "").lower().strip()
        if not self.customer_search_focused and not q:
            return []
        if not q:
            return self.saved_customers[:8]
        return [
            c
            for c in self.saved_customers
            if q in (c["party_name"] or "").lower()
            or q in (c["tin"] or "").lower()
            or q in (c["email"] or "").lower()
        ][:8]

    @rx.var
    def show_customer_results(self) -> bool:
        return (
            self.customer_search_focused
            or (self.customer_search_query or "").strip() != ""
        )

    @rx.var
    def ux_subtotal(self) -> float:
        return sum(
            float(l["invoiced_quantity"]) * float(l["price_amount"])
            for l in self.lines
        )

    @rx.var
    def ux_tax(self) -> float:
        return self.ux_subtotal * 0.075

    @rx.var
    def ux_total(self) -> float:
        return self.ux_subtotal + self.ux_tax

    def _wizard_dict(self) -> dict:
        return {
            "current_step": self.current_step,
            "max_step_reached": self.max_step_reached,
            "irn": self.irn,
            "issue_date": self.issue_date,
            "due_date": self.due_date,
            "invoice_type_code": self.invoice_type_code,
            "document_currency_code": self.document_currency_code,
            "tax_currency_code": self.tax_currency_code,
            "payment_means_code": self.payment_means_code,
            "billing_reference_irn": self.billing_reference_irn,
            "billing_reference_issue_date": self.billing_reference_issue_date,
            "supplier_tin": self.supplier_tin,
            "supplier_party_name": self.supplier_party_name,
            "supplier_email": self.supplier_email,
            "supplier_telephone": self.supplier_telephone,
            "supplier_street_name": self.supplier_street_name,
            "supplier_city_name": self.supplier_city_name,
            "supplier_postal_zone": self.supplier_postal_zone,
            "supplier_country": self.supplier_country,
            "supplier_state": self.supplier_state,
            "supplier_lga": self.supplier_lga,
            "customer_id": self.customer_id,
            "customer_tin": self.customer_tin,
            "customer_party_name": self.customer_party_name,
            "customer_email": self.customer_email,
            "customer_telephone": self.customer_telephone,
            "customer_street_name": self.customer_street_name,
            "customer_city_name": self.customer_city_name,
            "customer_postal_zone": self.customer_postal_zone,
            "customer_country": self.customer_country,
            "customer_state": self.customer_state,
            "customer_lga": self.customer_lga,
            "step3": {"lines": self.lines},
        }

    def _apply_dict(self, d: dict):
        self.current_step = int(d.get("current_step", 1))
        self.max_step_reached = int(d.get("max_step_reached", 1))
        for k in [
            "irn",
            "issue_date",
            "due_date",
            "invoice_type_code",
            "document_currency_code",
            "tax_currency_code",
            "payment_means_code",
            "billing_reference_irn",
            "billing_reference_issue_date",
            "supplier_tin",
            "supplier_party_name",
            "supplier_email",
            "supplier_telephone",
            "supplier_street_name",
            "supplier_city_name",
            "supplier_postal_zone",
            "supplier_country",
            "supplier_state",
            "supplier_lga",
            "customer_tin",
            "customer_party_name",
            "customer_email",
            "customer_telephone",
            "customer_street_name",
            "customer_city_name",
            "customer_postal_zone",
            "customer_country",
            "customer_state",
            "customer_lga",
        ]:
            if k in d:
                setattr(self, k, d.get(k, "") or "")
        self.customer_id = int(d.get("customer_id", 0) or 0)
        step3 = d.get("step3", {})
        self.lines = [dict(line) for line in (step3.get("lines", []) or [])]
        self.line_form = _empty_line()
        self.last_derived_name = ""
        self.last_derived_desc = ""

    @rx.event
    async def init_wizard(self):
        import asyncio

        self.error_message = ""
        self.success_message = ""
        self.lines = []
        self.line_form = _empty_line()
        self.last_derived_name = ""
        self.last_derived_desc = ""
        auth = await self.get_state(AuthState)
        if not auth.session_id:
            return
        # Run independent supporting loads concurrently
        try:
            await asyncio.gather(
                self._load_lookups_inner(auth),
                self._load_saved_customers_inner(auth),
                return_exceptions=True,
            )
        except Exception as e:
            logging.exception(f"init wizard concurrent loads: {e}")
        # Restore wizard from session
        try:
            resp = await auth._api_request(
                "GET", f"/sessions/{auth.session_id}"
            )
            if resp is not None and resp.status_code == 200:
                wizard_json = resp.json().get("wizard_json")
                if wizard_json:
                    try:
                        d = json.loads(wizard_json)
                        self._apply_dict(d)
                        self.success_message = (
                            "Resumed your in-progress invoice."
                        )
                        return
                    except Exception:
                        logging.exception("wizard parse")
        except Exception as e:
            logging.exception(f"init wizard: {e}")
        # Fresh wizard - prefill from profile
        self.supplier_tin = auth.tin
        self.supplier_party_name = auth.party_name
        self.supplier_email = auth.email
        self.supplier_telephone = auth.telephone
        self.supplier_street_name = auth.street_name
        self.supplier_city_name = auth.city_name
        self.supplier_postal_zone = auth.postal_zone
        self.supplier_country = auth.country or "NG"
        self.supplier_state = auth.state_field
        self.supplier_lga = auth.lga
        if not self.issue_date:
            self.issue_date = datetime.now().strftime("%Y-%m-%d")
        if not self.irn:
            next_seq = 1000
            try:
                from app.states.invoice_log_state import InvoiceLogState

                invoice_log = await self.get_state(InvoiceLogState)
                if not invoice_log.items and invoice_log.total == 0:
                    await invoice_log.load_items()
                import re

                max_seq = 999
                for item in invoice_log.items:
                    irn_str = item.get("irn", "")
                    match = re.match(r"^INV(\d+)", irn_str)
                    if match:
                        try:
                            num = int(match.group(1))
                            if num > max_seq:
                                max_seq = num
                        except ValueError:
                            pass
                next_seq = max(1000, max_seq + 1)
            except Exception as ex:
                logging.exception(f"Failed to scan invoice log sequence: {ex}")
                next_seq = 1000
            svc = (auth.service_id or "SVC")[:8].upper()
            ts = datetime.now().strftime("%Y%m%d")
            self.irn = f"INV{next_seq}-{svc}-{ts}"

    async def _load_lookups_inner(self, auth):
        if self.lookups_loaded:
            return
        import asyncio

        try:
            results = await asyncio.gather(
                auth._api_request("GET", "/lookup/types-of-invoice"),
                auth._api_request("GET", "/lookup/payment-means"),
                auth._api_request("GET", "/lookup/get-currency"),
                auth._api_request("GET", "/lookup/state-codes"),
                auth._api_request("GET", "/lookup/countries"),
                return_exceptions=True,
            )
            r_types, r_pm, r_curr, r_states, r_countries = results
            if (
                not isinstance(r_types, Exception)
                and r_types is not None
                and r_types.status_code == 200
            ):
                self.invoice_types = [
                    {"code": x.get("code", ""), "value": x.get("value", "")}
                    for x in r_types.json()
                ]
            if (
                not isinstance(r_pm, Exception)
                and r_pm is not None
                and r_pm.status_code == 200
            ):
                self.payment_means = [
                    {"code": x.get("code", ""), "value": x.get("value", "")}
                    for x in r_pm.json()
                ]
            if (
                not isinstance(r_curr, Exception)
                and r_curr is not None
                and r_curr.status_code == 200
            ):
                self.currencies = [
                    {"code": x.get("code", ""), "name": x.get("name", "")}
                    for x in r_curr.json()
                ]
            if (
                not isinstance(r_states, Exception)
                and r_states is not None
                and r_states.status_code == 200
            ):
                self.states_options = [
                    {
                        "code": x.get("code", "") or x.get("name", ""),
                        "name": x.get("name", ""),
                    }
                    for x in r_states.json()
                ]
            if (
                not isinstance(r_countries, Exception)
                and r_countries is not None
                and r_countries.status_code == 200
            ):
                self.countries_options = [
                    {
                        "code": x.get("alpha_2", ""),
                        "name": x.get("name", ""),
                    }
                    for x in r_countries.json()
                ]
            self.lookups_loaded = True
        except Exception as e:
            logging.exception(f"load_lookups: {e}")

    async def _load_saved_customers_inner(self, auth):
        try:
            r = await auth._api_request(
                "GET", "/customers", params={"limit": 200}
            )
            if r is not None and r.status_code == 200:
                items = r.json().get("items", [])
                self.saved_customers = [
                    {
                        "id": c.get("id", 0),
                        "party_name": c.get("party_name", ""),
                        "tin": c.get("tin", ""),
                        "email": c.get("email", ""),
                        "telephone": c.get("telephone", ""),
                        "street_name": c.get("street_name", ""),
                        "city_name": c.get("city_name", ""),
                        "postal_zone": c.get("postal_zone", ""),
                        "country": c.get("country", "NG"),
                        "state": c.get("state", ""),
                        "lga": c.get("lga", "") or "",
                    }
                    for c in items
                ]
        except Exception as e:
            logging.exception(f"load_saved_customers: {e}")

    @rx.event
    async def load_lookups(self):
        if self.lookups_loaded:
            return
        auth = await self.get_state(AuthState)
        try:
            r = await auth._api_request("GET", "/lookup/types-of-invoice")
            if r is not None and r.status_code == 200:
                self.invoice_types = [
                    {"code": x.get("code", ""), "value": x.get("value", "")}
                    for x in r.json()
                ]
            r = await auth._api_request("GET", "/lookup/payment-means")
            if r is not None and r.status_code == 200:
                self.payment_means = [
                    {"code": x.get("code", ""), "value": x.get("value", "")}
                    for x in r.json()
                ]
            r = await auth._api_request("GET", "/lookup/get-currency")
            if r is not None and r.status_code == 200:
                self.currencies = [
                    {"code": x.get("code", ""), "name": x.get("name", "")}
                    for x in r.json()
                ]
            r = await auth._api_request("GET", "/lookup/state-codes")
            if r is not None and r.status_code == 200:
                self.states_options = [
                    {
                        "code": x.get("code", "") or x.get("name", ""),
                        "name": x.get("name", ""),
                    }
                    for x in r.json()
                ]
            r = await auth._api_request("GET", "/lookup/countries")
            if r is not None and r.status_code == 200:
                self.countries_options = [
                    {
                        "code": x.get("alpha_2", ""),
                        "name": x.get("name", ""),
                    }
                    for x in r.json()
                ]
            self.lookups_loaded = True
        except Exception as e:
            logging.exception(f"load_lookups: {e}")

    @rx.event
    async def load_saved_customers(self):
        auth = await self.get_state(AuthState)
        try:
            r = await auth._api_request(
                "GET", "/customers", params={"limit": 200}
            )
            if r is not None and r.status_code == 200:
                items = r.json().get("items", [])
                self.saved_customers = [
                    {
                        "id": c.get("id", 0),
                        "party_name": c.get("party_name", ""),
                        "tin": c.get("tin", ""),
                        "email": c.get("email", ""),
                        "telephone": c.get("telephone", ""),
                        "street_name": c.get("street_name", ""),
                        "city_name": c.get("city_name", ""),
                        "postal_zone": c.get("postal_zone", ""),
                        "country": c.get("country", "NG"),
                        "state": c.get("state", ""),
                        "lga": c.get("lga", "") or "",
                    }
                    for c in items
                ]
        except Exception as e:
            logging.exception(f"load_saved_customers: {e}")

    async def _persist(self):
        auth = await self.get_state(AuthState)
        if not auth.session_id:
            return
        try:
            payload = json.dumps(self._wizard_dict())
            await auth._api_request(
                "PATCH",
                f"/sessions/{auth.session_id}/wizard",
                json={"wizard_json": payload},
            )
        except Exception as e:
            logging.exception(f"persist wizard: {e}")

    # --- Step navigation ---
    @rx.event
    async def go_to_step(self, step: int):
        self.error_message = ""
        self.success_message = ""
        if step < 1 or step > 4:
            return
        if step > self.max_step_reached:
            return
        self.current_step = step
        await self._persist()

    @rx.event
    async def next_step(self):
        valid, msg = self._validate_step(self.current_step)
        if not valid:
            self.error_message = msg
            return
        if self.current_step < 4:
            self.current_step += 1
            if self.current_step > self.max_step_reached:
                self.max_step_reached = self.current_step
            await self._persist()
        self.error_message = ""
        self.success_message = ""

    @rx.event
    async def prev_step(self):
        if self.current_step > 1:
            self.current_step -= 1
            await self._persist()
        self.error_message = ""
        self.success_message = ""

    def _validate_step(self, step: int) -> tuple[bool, str]:
        if step == 1:
            if not self.irn:
                return False, "IRN is required."
            if not self.issue_date:
                return False, "Issue date is required."
            if not self.invoice_type_code:
                return False, "Invoice type is required."
            if not self.document_currency_code:
                return False, "Currency is required."
            # Due date must not be earlier than the issue date.
            if self.due_date and self.issue_date:
                try:
                    issue = datetime.strptime(
                        self.issue_date.strip(), "%Y-%m-%d"
                    )
                    due = datetime.strptime(self.due_date.strip(), "%Y-%m-%d")
                    if due < issue:
                        return (
                            False,
                            "Due date cannot be earlier than the issue date.",
                        )
                except ValueError:
                    return (
                        False,
                        "Issue and due dates must be valid YYYY-MM-DD dates.",
                    )
            # Per FIRS rules: invoice types 380 (credit note), 384 (debit note),
            # and 385 (self-billed) MUST reference the original invoice via
            # BillingReference (original IRN + original issue date).
            # Type 381 (commercial invoice) keeps BillingReference optional.
            if self.invoice_type_code in ("380", "384", "385"):
                if (
                    not self.billing_reference_irn
                    or self.billing_reference_irn.strip() == ""
                ):
                    return (
                        False,
                        f"Original invoice IRN is required for invoice type {self.invoice_type_code}.",
                    )
                if (
                    not self.billing_reference_issue_date
                    or self.billing_reference_issue_date.strip() == ""
                ):
                    return (
                        False,
                        f"Original invoice issue date is required for invoice type {self.invoice_type_code}.",
                    )
                # Original issue date must be on or before this invoice's issue date.
                if self.issue_date:
                    try:
                        orig = datetime.strptime(
                            self.billing_reference_issue_date.strip(),
                            "%Y-%m-%d",
                        )
                        cur = datetime.strptime(
                            self.issue_date.strip(), "%Y-%m-%d"
                        )
                        if orig > cur:
                            return (
                                False,
                                "Original invoice date cannot be after this invoice's issue date.",
                            )
                    except ValueError:
                        return (
                            False,
                            "Original issue date must be a valid YYYY-MM-DD date.",
                        )
            return True, ""
        if step == 2:
            # Supplier identity
            if (
                not self.supplier_tin
                or not self.supplier_party_name
                or not self.supplier_email
            ):
                return False, "Supplier TIN, name and email are required."
            # Supplier address — required for FIRS submission
            missing_supplier_addr = [
                ("Supplier street", self.supplier_street_name),
                ("Supplier city", self.supplier_city_name),
                ("Supplier postal zone", self.supplier_postal_zone),
                ("Supplier country", self.supplier_country),
                ("Supplier state", self.supplier_state),
            ]
            for label, val in missing_supplier_addr:
                if not val or not str(val).strip():
                    return False, f"{label} is required."
            # Customer identity
            if (
                not self.customer_tin
                or not self.customer_party_name
                or not self.customer_email
            ):
                return False, "Customer TIN, name and email are required."
            # Customer address
            missing_customer_addr = [
                ("Customer street", self.customer_street_name),
                ("Customer city", self.customer_city_name),
                ("Customer postal zone", self.customer_postal_zone),
                ("Customer country", self.customer_country),
                ("Customer state", self.customer_state),
            ]
            for label, val in missing_customer_addr:
                if not val or not str(val).strip():
                    return False, f"{label} is required."
            return True, ""
        if step == 3:
            if not self.lines:
                return False, "Add at least one invoice line."
            return True, ""
        return True, ""

    # --- Step 1 setters ---
    @rx.event
    def set_irn(self, v: str):
        self.irn = v.upper()

    @rx.event
    def set_issue_date(self, v: str):
        self.issue_date = v

    @rx.event
    def set_due_date(self, v: str):
        self.due_date = v

    @rx.event
    def set_invoice_type_code(self, v: str):
        self.invoice_type_code = v

    @rx.event
    def set_document_currency_code(self, v: str):
        self.document_currency_code = v
        # Tax currency is fixed to NGN per FIRS requirements
        self.tax_currency_code = "NGN"

    @rx.event
    def set_payment_means_code(self, v: str):
        self.payment_means_code = v

    @rx.event
    def set_billing_reference_irn(self, v: str):
        self.billing_reference_irn = v.upper()

    @rx.event
    def set_billing_reference_issue_date(self, v: str):
        self.billing_reference_issue_date = v

    @rx.event
    def set_customer_search_query(self, value: str):
        self.customer_search_query = value

    @rx.event
    def focus_customer_search(self, value: str = ""):
        self.customer_search_focused = True

    @rx.event
    def blur_customer_search(self, value: str = ""):
        self.customer_search_focused = False

    @rx.event
    def clear_customer_search(self):
        self.customer_search_query = ""
        self.customer_search_focused = False

    # --- Step 2 setters ---
    @rx.event
    def set_supplier_field(self, field: str, v: str):
        setattr(self, f"supplier_{field}", v)

    @rx.event
    def select_saved_customer(self, customer_id: int):
        self.error_message = ""
        self.success_message = ""
        for c in self.saved_customers:
            if c["id"] == customer_id:
                self.customer_id = c["id"]
                self.customer_tin = c["tin"]
                self.customer_party_name = c["party_name"]
                self.customer_email = c["email"]
                self.customer_telephone = c["telephone"]
                self.customer_street_name = c["street_name"]
                self.customer_city_name = c["city_name"]
                self.customer_postal_zone = c["postal_zone"]
                self.customer_country = c["country"]
                self.customer_state = c["state"]
                self.customer_lga = c["lga"] or ""
                self.customer_search_query = c["party_name"]
                self.customer_search_focused = False
                return

    @rx.event
    def clear_customer(self):
        self.error_message = ""
        self.success_message = ""
        self.customer_id = 0
        self.customer_tin = ""
        self.customer_party_name = ""
        self.customer_email = ""
        self.customer_telephone = ""
        self.customer_street_name = ""
        self.customer_city_name = ""
        self.customer_postal_zone = ""
        self.customer_country = "NG"
        self.customer_state = ""
        self.customer_lga = ""
        self.customer_search_query = ""

    @rx.event
    async def save_step2(self, form_data: dict):
        for k in [
            "customer_tin",
            "customer_party_name",
            "customer_email",
            "customer_telephone",
            "customer_street_name",
            "customer_city_name",
            "customer_postal_zone",
            "customer_country",
            "customer_state",
            "customer_lga",
        ]:
            setattr(self, k, form_data.get(k, "").strip())
        self.error_message = ""
        self.success_message = ""
        valid, msg = self._validate_step(2)
        if not valid:
            self.error_message = msg
            return
        if self.current_step < 4:
            self.current_step += 1
            if self.current_step > self.max_step_reached:
                self.max_step_reached = self.current_step
        await self._persist()

    @rx.event
    async def save_step1(self, form_data: dict):
        self.irn = form_data.get("irn", "").strip().upper()
        self.issue_date = form_data.get("issue_date", "").strip()
        self.due_date = form_data.get("due_date", "").strip()
        self.invoice_type_code = form_data.get("invoice_type_code", "381")
        self.document_currency_code = form_data.get(
            "document_currency_code", "NGN"
        )
        # Tax currency is fixed to NGN per FIRS requirements
        self.tax_currency_code = "NGN"
        self.payment_means_code = form_data.get("payment_means_code", "10")
        self.billing_reference_irn = (
            form_data.get("billing_reference_irn", "").strip().upper()
        )
        self.billing_reference_issue_date = form_data.get(
            "billing_reference_issue_date", ""
        ).strip()

        self.error_message = ""
        self.success_message = ""
        valid, msg = self._validate_step(1)
        if not valid:
            self.error_message = msg
            return

        if self.current_step < 4:
            self.current_step += 1
            if self.current_step > self.max_step_reached:
                self.max_step_reached = self.current_step
        await self._persist()
        self.error_message = ""
        self.success_message = ""

    # --- Step 3 line items ---
    @rx.event
    def open_new_line(self):
        self.error_message = ""
        self.success_message = ""
        self.line_form = _empty_line()
        self.lines = list(self.lines)
        self.edit_line_index = -1
        self.show_line_form = True
        self.lookup_hits = []
        self.lookup_query = ""
        self.last_derived_name = ""
        self.last_derived_desc = ""

    @rx.event
    def open_edit_line(self, index: int):
        self.error_message = ""
        self.success_message = ""
        self.lines = list(self.lines)
        if 0 <= index < len(self.lines):
            self.line_form = dict(self.lines[index])
            self.edit_line_index = index
            self.show_line_form = True
            self.last_derived_name = self.line_form.get("name", "")
            self.last_derived_desc = self.line_form.get("description", "")

    @rx.event
    def close_line_form(self):
        self.error_message = ""
        self.success_message = ""
        self.show_line_form = False
        self.edit_line_index = -1
        self.line_form = _empty_line()
        self.last_derived_name = ""
        self.last_derived_desc = ""

    @rx.event
    async def remove_line(self, index: int):
        self.error_message = ""
        self.success_message = ""
        self.lines = list(self.lines)
        if 0 <= index < len(self.lines):
            new_lines = list(self.lines)
            new_lines.pop(index)
            self.lines = new_lines
            await self._persist()

    @rx.event
    async def search_lookup(self, q: str):
        self.lookup_query = q
        if not q or len(q) < 2:
            self.lookup_hits = []
            return
        self.lookup_loading = True
        auth = await self.get_state(AuthState)
        merged: list[LookupHit] = []
        try:
            r = await auth._api_request(
                "GET",
                "/lookup/products",
                params={"search": q, "length": 8},
            )
            if r is not None and r.status_code == 200:
                for h in r.json():
                    p_code = h.get("hscode") or h.get("code") or ""
                    p_label = h.get("description") or h.get("label") or ""
                    p_category = (
                        h.get("product_category")
                        or h.get("category")
                        or p_label
                    )
                    merged.append(
                        {
                            "kind": "product",
                            "code": str(p_code),
                            "label": str(p_label),
                            "category": str(p_category),
                        }
                    )
            r = await auth._api_request(
                "GET",
                "/lookup/services",
                params={"search": q, "length": 8},
            )
            if r is not None and r.status_code == 200:
                for h in r.json():
                    s_code = h.get("code") or ""
                    s_label = h.get("description") or h.get("label") or ""
                    s_category = h.get("category") or s_label
                    merged.append(
                        {
                            "kind": "service",
                            "code": str(s_code),
                            "label": str(s_label),
                            "category": str(s_category),
                        }
                    )
            self.lookup_hits = merged
        except Exception as e:
            logging.exception(f"lookup search: {e}")
        finally:
            self.lookup_loading = False

    @rx.event
    def apply_lookup_hit(
        self, hit_type: str, code: str, label: str, category: str
    ):
        self.line_form = dict(self.line_form)
        self.error_message = ""
        self.success_message = ""
        if hit_type == "product":
            self.line_form["hsn_code"] = code
            self.line_form["product_category"] = category
            self.line_form["isic_code"] = ""
            self.line_form["service_category"] = ""
        else:
            self.line_form["isic_code"] = code
            self.line_form["service_category"] = category
            self.line_form["hsn_code"] = ""
            self.line_form["product_category"] = ""

        new_name = label[:80]
        new_desc = category or label

        if (
            not self.line_form.get("name")
            or self.line_form.get("name") == self.last_derived_name
        ):
            self.line_form["name"] = new_name
            self.last_derived_name = new_name

        if (
            not self.line_form.get("description")
            or self.line_form.get("description") == self.last_derived_desc
        ):
            self.line_form["description"] = new_desc
            self.last_derived_desc = new_desc

        self.lookup_hits = []
        self.lookup_query = ""

    @rx.event
    async def save_line(self, form_data: dict):
        def _to_float(name: str, default: float = 0.0) -> tuple[float, str]:
            raw = form_data.get(name, "")
            if raw is None or str(raw).strip() == "":
                return default, ""
            try:
                return float(raw), ""
            except (ValueError, TypeError):
                return (
                    default,
                    f"{name.replace('_', ' ').title()} must be a number.",
                )

        qty, err = _to_float("invoiced_quantity", 1.0)
        if err:
            self.error_message = err
            return
        price, err = _to_float("price_amount", 0.0)
        if err:
            self.error_message = err
            return
        base_qty, err = _to_float("base_quantity", 1.0)
        if err:
            self.error_message = err
            return
        disc_rate, err = _to_float("discount_rate", 0.0)
        if err:
            self.error_message = err
            return
        disc_amt, err = _to_float("discount_amount", 0.0)
        if err:
            self.error_message = err
            return
        fee_rate, err = _to_float("fee_rate", 0.0)
        if err:
            self.error_message = err
            return
        fee_amt, err = _to_float("fee_amount", 0.0)
        if err:
            self.error_message = err
            return

        if qty <= 0:
            self.error_message = "Quantity must be greater than 0."
            return
        if base_qty <= 0:
            self.error_message = "Base quantity must be greater than 0."
            return
        if price < 0:
            self.error_message = "Price cannot be negative."
            return
        if disc_rate < 0 or disc_rate > 100:
            self.error_message = "Discount rate must be between 0 and 100."
            return
        if fee_rate < 0 or fee_rate > 100:
            self.error_message = "Fee rate must be between 0 and 100."
            return
        if disc_amt < 0:
            self.error_message = "Discount amount cannot be negative."
            return
        if fee_amt < 0:
            self.error_message = "Fee amount cannot be negative."
            return

        desc = form_data.get("description", "").strip()
        if not desc:
            desc = (
                self.line_form.get("description", "").strip()
                or self.line_form.get("product_category", "").strip()
                or self.line_form.get("service_category", "").strip()
                or form_data.get("name", "").strip()
            )

        line: WizardLine = {
            "id": self.line_form.get("id", "")
            or str(datetime.now().timestamp()),
            "name": form_data.get("name", "").strip(),
            "description": desc,
            "sellers_item_identification": form_data.get(
                "sellers_item_identification", ""
            ).strip(),
            "hsn_code": self.line_form.get("hsn_code", ""),
            "product_category": self.line_form.get("product_category", ""),
            "isic_code": self.line_form.get("isic_code", ""),
            "service_category": self.line_form.get("service_category", ""),
            "invoiced_quantity": qty,
            "price_amount": price,
            "price_unit": form_data.get("price_unit", "NGN per 1")
            or "NGN per 1",
            "base_quantity": base_qty,
            "discount_rate": disc_rate,
            "discount_amount": disc_amt,
            "fee_rate": fee_rate,
            "fee_amount": fee_amt,
        }
        if not line["name"]:
            self.error_message = "Item name is required."
            return
        if not (line["hsn_code"] or line["isic_code"]):
            self.error_message = (
                "Select an HS code (product) or service code via lookup."
            )
            return

        import re

        if line["hsn_code"] and not re.match(
            r"^\d{4}\.\d{2}$", line["hsn_code"]
        ):
            self.error_message = (
                "HS code must use PASCA format XXXX.XX, for example 1006.10."
            )
            return

        if line["isic_code"] and not re.match(r"^\d{4}$", line["isic_code"]):
            self.error_message = (
                "Service code must use PASCA ISIC format, for example 0112."
            )
            return
        self.error_message = ""
        self.lines = list(self.lines)
        if self.edit_line_index >= 0:
            new_lines = list(self.lines)
            new_lines[self.edit_line_index] = line
            self.lines = new_lines
        else:
            self.lines = list(self.lines) + [line]
        self.show_line_form = False
        self.edit_line_index = -1
        await self._persist()

    # --- Step 4: Assemble / Validate / Sign / Transmit ---
    async def _do_assemble(self) -> bool:
        auth = await self.get_state(AuthState)
        payload = {"wizard": self._wizard_dict()}
        r = await auth._api_request("POST", "/invoice/assemble", json=payload)
        if r is None:
            self.error_message = "Failed to assemble invoice."
            return False
        if r.status_code != 200:
            self.error_message = normalize_detail(r, "Assemble failed")
            return False
        data = r.json()
        self.computed_totals = {
            k: float(v) for k, v in (data.get("computed", {}) or {}).items()
        }
        self.assembled = {k: v for k, v in data.items() if k != "computed"}
        return True

    @rx.event
    async def assemble(self):
        self.error_message = ""
        self.success_message = ""
        self.loading = True
        self.busy_action = "assemble"
        try:
            ok = await self._do_assemble()
            if ok:
                self.success_message = "Invoice assembled."
        finally:
            self.loading = False
            self.busy_action = ""

    @rx.event
    async def validate(self):
        self.error_message = ""
        self.success_message = ""
        self.loading = True
        self.busy_action = "validate"
        try:
            if not self.assembled:
                ok = await self._do_assemble()
                if not ok:
                    return
            auth = await self.get_state(AuthState)
            r = await auth._api_request(
                "POST", "/invoice/validate-invoice", json=self.assembled
            )
            if r is None:
                self.error_message = "Validation failed."
                return
            if r.status_code != 200:
                self.error_message = normalize_detail(r, "Validation failed")
                return
            self.validated = True
            self.success_message = "Invoice validated successfully."
        finally:
            self.loading = False
            self.busy_action = ""

    @rx.event
    def open_sign_modal(self):
        self.error_message = ""
        self.success_message = ""
        self.pending_user_secret = ""
        self.show_sign_modal = True

    @rx.event
    def close_sign_modal(self):
        self.error_message = ""
        self.success_message = ""
        self.show_sign_modal = False
        self.pending_user_secret = ""

    @rx.event
    def set_pending_secret(self, v: str):
        self.pending_user_secret = v

    @rx.event
    async def sign(self, form_data: dict):
        self.error_message = ""
        self.success_message = ""
        secret = form_data.get("user_secret", "")
        if not secret:
            self.error_message = "Signing secret required."
            return
        self.loading = True
        self.busy_action = "sign"
        try:
            if not self.assembled:
                ok = await self._do_assemble()
                if not ok:
                    return
            auth = await self.get_state(AuthState)
            r = await auth._api_request(
                "POST",
                "/invoice/sign-invoice",
                json=self.assembled,
                headers={"user-secret": secret},
            )
            if r is None:
                self.error_message = "Signing request failed."
                return
            if r.status_code != 200:
                self.error_message = normalize_detail(r, "Signing failed")
                return
            self.signed = True
            self.final_irn = self.irn
            self.show_sign_modal = False
            self.success_message = "Invoice signed."
            # Create local invoice log entry
            log_warn = ""
            try:
                log_payload = {
                    "irn": self.irn,
                    "issue_date": self.issue_date,
                    "customer_name": self.customer_party_name,
                    "currency": self.document_currency_code,
                    "payment_status": "PENDING",
                    "payable_amount": float(
                        self.computed_totals.get("payable_amount", 0)
                    ),
                    "transmitted": False,
                }
                lr = await auth._api_request(
                    "POST", "/invoice-log", json=log_payload
                )
                if lr is not None and lr.status_code in (200, 201):
                    self.log_created = True
                else:
                    log_warn = normalize_detail(
                        lr,
                        "Invoice signed, but local log entry could not be created.",
                    )
            except Exception as e:
                logging.exception(f"create log: {e}")
                log_warn = (
                    "Invoice signed, but local log entry could not be created."
                )
            if log_warn:
                # Surface as an error so the user sees the warning without
                # losing the success state of the signing itself.
                self.error_message = log_warn
        finally:
            self.loading = False
            self.busy_action = ""

    @rx.event
    async def transmit(self):
        self.error_message = ""
        self.success_message = ""
        if not self.signed:
            self.error_message = "Sign the invoice before transmitting."
            return
        self.loading = True
        self.busy_action = "transmit"
        try:
            auth = await self.get_state(AuthState)
            r = await auth._api_request(
                "GET", f"/invoice/transmit-invoice/{self.irn}"
            )
            if r is None:
                self.error_message = "Transmit failed."
                return
            if r.status_code != 200:
                detail = ""
                try:
                    detail = r.json().get("detail", "")
                except Exception:
                    logging.exception("Unexpected error")
                lower = detail.lower()
                if any(
                    w in lower for w in ("already", "transmitted", "duplicate")
                ):
                    self.transmitted = True
                    self.success_message = (
                        "Invoice already transmitted to FIRS."
                    )
                else:
                    self.error_message = detail or "Transmit failed"
                    return
            else:
                self.transmitted = True
                self.success_message = "Invoice transmitted to FIRS."
            # Mark in local log
            try:
                await auth._api_request(
                    "PATCH", f"/invoice-log/{self.irn}/transmitted"
                )
            except Exception:
                logging.exception("mark transmitted")
        finally:
            self.loading = False
            self.busy_action = ""

    @rx.event
    async def finish_and_clear(self):
        self.error_message = ""
        self.success_message = ""
        irn = self.final_irn or self.irn
        await self._clear_session_wizard()
        self._reset_local()
        return rx.redirect(f"/invoices/{irn}")

    @rx.event
    async def discard_wizard(self):
        self.error_message = ""
        self.success_message = ""
        await self._clear_session_wizard()
        self._reset_local()
        return rx.redirect("/invoices")

    async def _clear_session_wizard(self):
        auth = await self.get_state(AuthState)
        if auth.session_id:
            try:
                await auth._api_request(
                    "DELETE", f"/sessions/{auth.session_id}/wizard"
                )
            except Exception:
                logging.exception("clear wizard")

    def _reset_local(self):
        self.current_step = 1
        self.max_step_reached = 1
        self.irn = ""
        self.issue_date = ""
        self.due_date = ""
        self.lines = []
        self.line_form = _empty_line()
        self.last_derived_name = ""
        self.last_derived_desc = ""
        self.assembled = {}
        self.computed_totals = {
            "line_extension_amount": 0.0,
            "tax_amount": 0.0,
            "tax_exclusive_amount": 0.0,
            "tax_inclusive_amount": 0.0,
            "payable_amount": 0.0,
        }
        self.validated = False
        self.signed = False
        self.transmitted = False
        self.log_created = False
        self.final_irn = ""
        self.error_message = ""
        self.success_message = ""
        self.show_sign_modal = False
        self.pending_user_secret = ""
        self.allow_edit_irn = False

    @rx.event
    def toggle_edit_irn(self):
        self.allow_edit_irn = not self.allow_edit_irn

    @rx.event
    def clear_messages(self):
        self.error_message = ""
        self.success_message = ""

    @rx.event
    def close_sign_modal_and_clear(self):
        self.show_sign_modal = False
        self.pending_user_secret = ""
        self.error_message = ""
        self.success_message = ""