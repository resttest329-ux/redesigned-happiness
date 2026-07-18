import logging
import reflex as rx
from typing import TypedDict
from app.states.auth_state import AuthState
from app.states.api_utils import normalize_detail
from app.states.auth_state import AuthState


class InvoiceLogItem(TypedDict):
    id: int
    business_id: str
    irn: str
    issue_date: str
    customer_name: str
    currency: str
    payment_status: str
    payable_amount: float
    transmitted: bool
    created_at: str


class AuthLine(TypedDict):
    name: str
    description: str
    quantity: float
    unit_price: float
    line_total: float
    code: str


class AuthParty(TypedDict):
    party_name: str
    tin: str
    email: str
    telephone: str
    address: str


class InvoiceLogState(rx.State):
    items: list[InvoiceLogItem] = []
    total: int = 0
    search_query: str = ""
    order: str = "desc"
    loading: bool = False
    error_message: str = ""
    success_message: str = ""
    # Per-IRN action tracking so a single in-flight transmit/status update
    # doesn't visually disable other unrelated rows.
    transmitting_irns: list[str] = []
    status_updating_irn: str = ""

    stats: dict[str, float] = {
        "total": 0.0,
        "revenue": 0.0,
        "pending": 0.0,
        "paid": 0.0,
        "rejected": 0.0,
        "partial": 0.0,
    }
    stats_loading: bool = False

    selected: InvoiceLogItem = {
        "id": 0,
        "business_id": "",
        "irn": "",
        "issue_date": "",
        "customer_name": "",
        "currency": "NGN",
        "payment_status": "PENDING",
        "payable_amount": 0.0,
        "transmitted": False,
        "created_at": "",
    }
    detail_loading: bool = False
    qr_b64: str = ""

    show_status_modal: bool = False
    status_irn: str = ""
    new_status: str = "PAID"
    status_user_secret: str = ""

    # Authoritative invoice details (from FIRS/PASCA backend)
    firs_invoice: dict[str, str | int | float | bool | list | dict | None] = {}
    auth_supplier: AuthParty = {
        "party_name": "",
        "tin": "",
        "email": "",
        "telephone": "",
        "address": "",
    }
    auth_customer: AuthParty = {
        "party_name": "",
        "tin": "",
        "email": "",
        "telephone": "",
        "address": "",
    }
    auth_lines: list[AuthLine] = []

    @rx.event
    async def load_items(self):
        self.loading = True
        self.error_message = ""
        try:
            auth = await self.get_state(AuthState)
            params = {"limit": 50, "order": self.order}
            if self.search_query:
                params["search"] = self.search_query
            resp = await auth._api_request("GET", "/invoice-log", params=params)
            if resp is None:
                self.error_message = "Failed to load invoices"
                return
            if resp.status_code == 200:
                data = resp.json()
                self.items = data.get("items", [])
                self.total = data.get("total", 0)
            else:
                self.error_message = "Failed to load invoices"
        except Exception as e:
            logging.exception(f"load invoices: {e}")
            self.error_message = "Failed to load invoices"
        finally:
            self.loading = False

    @rx.event
    async def load_stats(self):
        self.stats_loading = True
        try:
            auth = await self.get_state(AuthState)
            resp = await auth._api_request("GET", "/invoice-log/stats")
            if resp is not None and resp.status_code == 200:
                data = resp.json()
                self.stats = {
                    "total": float(data.get("total", 0)),
                    "revenue": float(data.get("revenue", 0)),
                    "pending": float(data.get("pending", 0)),
                    "paid": float(data.get("paid", 0)),
                    "rejected": float(data.get("rejected", 0)),
                    "partial": float(data.get("partial", 0)),
                }
        except Exception as e:
            logging.exception(f"load stats: {e}")
        finally:
            self.stats_loading = False

    @rx.event
    async def load_dashboard(self):
        import asyncio

        self.error_message = ""
        self.loading = True
        self.stats_loading = True
        try:
            auth = await self.get_state(AuthState)
            params = {"limit": 50, "order": self.order}
            if self.search_query:
                params["search"] = self.search_query
            stats_task = auth._api_request("GET", "/invoice-log/stats")
            items_task = auth._api_request("GET", "/invoice-log", params=params)
            stats_resp, items_resp = await asyncio.gather(
                stats_task, items_task, return_exceptions=True
            )
            if not isinstance(stats_resp, Exception) and stats_resp is not None:
                if stats_resp.status_code == 200:
                    data = stats_resp.json()
                    self.stats = {
                        "total": float(data.get("total", 0)),
                        "revenue": float(data.get("revenue", 0)),
                        "pending": float(data.get("pending", 0)),
                        "paid": float(data.get("paid", 0)),
                        "rejected": float(data.get("rejected", 0)),
                        "partial": float(data.get("partial", 0)),
                    }
            if not isinstance(items_resp, Exception) and items_resp is not None:
                if items_resp.status_code == 200:
                    data = items_resp.json()
                    self.items = data.get("items", [])
                    self.total = data.get("total", 0)
                else:
                    self.error_message = "Failed to load invoices"
        except Exception as e:
            logging.exception(f"load dashboard: {e}")
            self.error_message = "Failed to load dashboard"
        finally:
            self.loading = False
            self.stats_loading = False

    @rx.event
    async def set_search(self, value: str):
        if value == self.search_query:
            return
        self.search_query = value
        self.success_message = ""
        yield InvoiceLogState.load_items

    @rx.event
    async def toggle_order(self):
        self.order = "asc" if self.order == "desc" else "desc"
        yield InvoiceLogState.load_items

    @rx.event
    async def transmit_invoice(self, irn: str):
        if irn in self.transmitting_irns:
            return
        self.error_message = ""
        self.transmitting_irns = self.transmitting_irns + [irn]
        try:
            auth = await self.get_state(AuthState)
            resp = await auth._api_request(
                "GET", f"/invoice/transmit-invoice/{irn}"
            )
            if resp is None:
                self.error_message = "Transmit failed"
                return
            if resp.status_code != 200:
                self.error_message = normalize_detail(resp, "Transmit failed")
                return
            mark_resp = await auth._api_request(
                "PATCH", f"/invoice-log/{irn}/transmitted"
            )
            if mark_resp is not None and mark_resp.status_code == 200:
                self.success_message = f"Invoice {irn} transmitted"
                # Optimistic local update — avoid a full list reload
                self.items = [
                    {**item, "transmitted": True}
                    if item["irn"] == irn
                    else item
                    for item in self.items
                ]
                if self.selected.get("irn", "") == irn:
                    self.selected = {**self.selected, "transmitted": True}
        except Exception as e:
            logging.exception(f"transmit failed: {e}")
            self.error_message = "Transmit request failed."
        finally:
            self.transmitting_irns = [
                x for x in self.transmitting_irns if x != irn
            ]

    @rx.event
    async def load_detail(self):
        self.detail_loading = True
        self.error_message = ""
        self.qr_b64 = ""
        self.firs_invoice = {}
        self.auth_lines = []
        empty_party: AuthParty = {
            "party_name": "",
            "tin": "",
            "email": "",
            "telephone": "",
            "address": "",
        }
        self.auth_supplier = empty_party
        self.auth_customer = empty_party
        try:
            irn = self.router.page.params.get("invoice_irn", "")
            if not irn:
                return
            auth = await self.get_state(AuthState)
            resp = await auth._api_request("GET", f"/invoice-log/{irn}")
            if resp is None:
                self.error_message = "Failed to load invoice"
                return
            if resp.status_code == 200:
                self.selected = resp.json()
                qr_resp = await auth._api_request(
                    "GET",
                    f"/invoice/{irn}/qr",
                    params={
                        "amount": self.selected["payable_amount"],
                        "date": self.selected["issue_date"],
                    },
                )
                if qr_resp is not None and qr_resp.status_code == 200:
                    self.qr_b64 = qr_resp.json().get("qr_b64", "")
                # Load authoritative data silently
                yield InvoiceLogState.load_authoritative_detail
            else:
                self.error_message = "Invoice not found"
        except Exception as e:
            logging.exception(f"load detail: {e}")
            self.error_message = "Failed to load invoice"
        finally:
            self.detail_loading = False

    @rx.event
    async def load_authoritative_detail(self):
        try:
            irn = self.selected.get("irn", "")
            if not irn:
                self.firs_invoice = {}
                return
            auth = await self.get_state(AuthState)
            resp = await auth._api_request("GET", f"/invoice/get-invoice/{irn}")
            if resp is None or resp.status_code != 200:
                self.firs_invoice = {}
                return
            data = resp.json() or {}
            if not isinstance(data, dict) or not data:
                self.firs_invoice = {}
                return
            self.firs_invoice = data

            def _party(p: dict) -> AuthParty:
                if not isinstance(p, dict):
                    return {
                        "party_name": "",
                        "tin": "",
                        "email": "",
                        "telephone": "",
                        "address": "",
                    }
                addr = p.get("postal_address") or {}
                addr_parts = [
                    addr.get("street_name", ""),
                    addr.get("city_name", ""),
                    addr.get("state", ""),
                    addr.get("country", ""),
                ]
                return {
                    "party_name": str(p.get("party_name", "") or ""),
                    "tin": str(p.get("tin", "") or ""),
                    "email": str(p.get("email", "") or ""),
                    "telephone": str(p.get("telephone", "") or ""),
                    "address": ", ".join([a for a in addr_parts if a]),
                }

            self.auth_supplier = _party(
                data.get("accounting_supplier_party") or {}
            )
            self.auth_customer = _party(
                data.get("accounting_customer_party") or {}
            )
            lines_raw = data.get("invoice_line") or []
            lines: list[AuthLine] = []
            for ln in lines_raw:
                if not isinstance(ln, dict):
                    continue
                item = ln.get("item") or {}
                price = ln.get("price") or {}
                qty = float(ln.get("invoiced_quantity", 0) or 0)
                unit = float(price.get("price_amount", 0) or 0)
                ext = float(ln.get("line_extension_amount", qty * unit) or 0)
                code = ln.get("hsn_code") or ln.get("isic_code") or ""
                lines.append(
                    {
                        "name": str(item.get("name", "") or ""),
                        "description": str(item.get("description", "") or ""),
                        "quantity": qty,
                        "unit_price": unit,
                        "line_total": ext,
                        "code": str(code or ""),
                    }
                )
            self.auth_lines = lines
        except Exception as e:
            logging.exception(f"load authoritative detail: {e}")
            self.firs_invoice = {}

    @rx.event
    def open_status_modal(self, irn: str, current_status: str):
        self.status_irn = irn
        self.new_status = "PAID" if current_status != "PAID" else "PENDING"
        self.status_user_secret = ""
        self.show_status_modal = True

    @rx.event
    def close_status_modal(self):
        self.show_status_modal = False
        self.status_user_secret = ""

    @rx.event
    def set_new_status(self, value: str):
        self.new_status = value

    @rx.event
    def set_status_user_secret(self, value: str):
        self.status_user_secret = value

    @rx.event
    async def submit_status_change(self, form_data: dict):
        self.loading = True
        self.status_updating_irn = self.status_irn
        self.error_message = ""
        try:
            user_secret = (
                form_data.get("user_secret", "") or self.status_user_secret
            ).strip()
            if not user_secret:
                self.error_message = "Signing secret is required."
                self.loading = False
                return
            self.status_user_secret = user_secret

            # Apply optimistic updates immediately to satisfy strict sub-50ms timing
            updated_irn = self.status_irn
            new_status_value = self.new_status
            old_items = list(self.items)
            old_selected = dict(self.selected)

            self.items = [
                {**item, "payment_status": new_status_value}
                if item["irn"] == updated_irn
                else item
                for item in self.items
            ]
            if self.selected.get("irn", "") == updated_irn:
                self.selected = {
                    **self.selected,
                    "payment_status": new_status_value,
                }
            self.show_status_modal = False
            yield

            auth = await self.get_state(AuthState)
            # Step 1: Authoritative backend update first with user-secret header
            upstream = await auth._api_request(
                "PATCH",
                f"/invoice/update-invoice/{updated_irn}",
                json={"payment_status": new_status_value},
                headers={"user-secret": user_secret},
            )
            if upstream is None or upstream.status_code != 200:
                # Rollback on failure
                self.items = old_items
                self.selected = old_selected
                self.show_status_modal = True
                if upstream is not None:
                    detail = normalize_detail(upstream, "")
                    if upstream.status_code == 403:
                        self.error_message = detail or "Invalid signing secret."
                    else:
                        self.error_message = (
                            detail or "Failed to update invoice on FIRS."
                        )
                else:
                    self.error_message = "Failed to update invoice on FIRS."
                return

            # Step 2: Update local invoice log only after authoritative succeeded
            resp = await auth._api_request(
                "PATCH",
                f"/invoice-log/{updated_irn}/status",
                json={"payment_status": new_status_value},
            )
            if resp is None or resp.status_code != 200:
                self.error_message = "FIRS updated but local log update failed."
                return
            self.success_message = f"Status updated to {new_status_value}"
            self.status_user_secret = ""
        finally:
            self.loading = False
            self.status_updating_irn = ""

    @rx.event
    def clear_messages(self):
        self.error_message = ""
        self.success_message = ""