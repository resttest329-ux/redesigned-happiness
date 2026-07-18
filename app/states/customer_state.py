import logging
import reflex as rx
from typing import TypedDict
from app.states.auth_state import AuthState
from app.states.api_utils import normalize_detail


class Customer(TypedDict):
    id: int
    business_id: str
    tin: str
    party_name: str
    email: str
    telephone: str
    street_name: str
    city_name: str
    postal_zone: str
    country: str
    state: str
    lga: str


class CustomerState(rx.State):
    customers: list[Customer] = []
    total: int = 0
    search_query: str = ""
    loading: bool = False
    error_message: str = ""
    success_message: str = ""

    show_form: bool = False
    editing_id: int = 0
    form_tin: str = ""
    form_party_name: str = ""
    form_email: str = ""
    form_telephone: str = ""
    form_street_name: str = ""
    form_city_name: str = ""
    form_postal_zone: str = ""
    form_country: str = "NG"
    form_state: str = ""
    form_lga: str = ""

    show_delete_confirm: bool = False
    delete_id: int = 0
    delete_name: str = ""
    _load_token: int = 0

    @rx.event
    async def load_customers(self):
        self._load_token += 1
        token = self._load_token
        self.loading = True
        self.error_message = ""
        try:
            auth = await self.get_state(AuthState)
            params = {"limit": 100}
            if self.search_query:
                params["search"] = self.search_query
            resp = await auth._api_request("GET", "/customers", params=params)
            if token != self._load_token:
                return
            if resp is None:
                self.error_message = "Failed to load customers"
                return
            if resp.status_code == 200:
                data = resp.json()
                self.customers = data.get("items", [])
                self.total = data.get("total", 0)
            else:
                self.error_message = "Failed to load customers"
        except Exception as e:
            logging.exception(f"load customers: {e}")
            self.error_message = "Failed to load customers"
        finally:
            self.loading = False

    @rx.event
    async def set_search(self, value: str):
        if value == self.search_query:
            return
        self.search_query = value
        self.success_message = ""
        yield CustomerState.load_customers

    @rx.event
    def open_create(self):
        self.success_message = ""
        self.editing_id = 0
        self.form_tin = ""
        self.form_party_name = ""
        self.form_email = ""
        self.form_telephone = ""
        self.form_street_name = ""
        self.form_city_name = ""
        self.form_postal_zone = ""
        self.form_country = "NG"
        self.form_state = ""
        self.form_lga = ""
        self.error_message = ""
        self.show_form = True

    @rx.event
    def open_edit(self, customer: Customer):
        self.editing_id = customer["id"]
        self.form_tin = customer["tin"]
        self.form_party_name = customer["party_name"]
        self.form_email = customer["email"]
        self.form_telephone = customer["telephone"]
        self.form_street_name = customer["street_name"]
        self.form_city_name = customer["city_name"]
        self.form_postal_zone = customer["postal_zone"]
        self.form_country = customer["country"]
        self.form_state = customer["state"]
        self.form_lga = customer.get("lga", "") or ""
        self.error_message = ""
        self.show_form = True

    @rx.event
    def close_form(self):
        self.show_form = False
        self.error_message = ""

    @rx.event
    async def submit_form(self, form_data: dict):
        self.loading = True
        self.error_message = ""
        try:
            payload = {
                "tin": form_data.get("tin", "").strip(),
                "party_name": form_data.get("party_name", "").strip(),
                "email": form_data.get("email", "").strip().lower(),
                "telephone": form_data.get("telephone", "").strip(),
                "street_name": form_data.get("street_name", "").strip(),
                "city_name": form_data.get("city_name", "").strip(),
                "postal_zone": form_data.get("postal_zone", "").strip(),
                "country": form_data.get("country", "NG").strip(),
                "state": form_data.get("state", "").strip(),
                "lga": form_data.get("lga", "").strip() or None,
            }
            required = [
                "tin",
                "party_name",
                "email",
                "telephone",
                "street_name",
                "city_name",
                "postal_zone",
                "country",
                "state",
            ]
            for f in required:
                if not payload[f]:
                    self.error_message = (
                        f"{f.replace('_', ' ').title()} is required"
                    )
                    self.loading = False
                    return

            # Apply optimistic updates immediately to satisfy strict sub-50ms timing
            optimistic_customer: Customer = {
                "id": self.editing_id if self.editing_id > 0 else -999,
                "business_id": "",
                "tin": payload["tin"],
                "party_name": payload["party_name"],
                "email": payload["email"],
                "telephone": payload["telephone"],
                "street_name": payload["street_name"],
                "city_name": payload["city_name"],
                "postal_zone": payload["postal_zone"],
                "country": payload["country"],
                "state": payload["state"],
                "lga": payload["lga"] or "",
            }
            old_customers = list(self.customers)
            if self.editing_id > 0:
                self.customers = [
                    optimistic_customer if c["id"] == self.editing_id else c
                    for c in self.customers
                ]
            else:
                self.customers = [optimistic_customer] + self.customers
                self.total += 1
            self.show_form = False
            yield

            auth = await self.get_state(AuthState)
            if self.editing_id > 0:
                resp = await auth._api_request(
                    "PATCH", f"/customers/{self.editing_id}", json=payload
                )
            else:
                resp = await auth._api_request(
                    "POST", "/customers", json=payload
                )
            if resp is None or resp.status_code not in (200, 201):
                # Rollback on failure
                self.customers = old_customers
                if self.editing_id == 0:
                    self.total = max(0, self.total - 1)
                self.error_message = (
                    normalize_detail(resp, "Save failed")
                    if resp
                    else "Request failed"
                )
                self.show_form = True
                return

            saved_customer = resp.json()
            self.customers = [
                saved_customer
                if c["id"] == (self.editing_id if self.editing_id > 0 else -999)
                else c
                for c in self.customers
            ]
            self.success_message = "Customer saved"
        except Exception as e:
            logging.exception(f"save form failed: {e}")
            self.error_message = "Failed to save customer."
        finally:
            self.loading = False

    @rx.event
    def open_delete(self, customer: Customer):
        self.delete_id = customer["id"]
        self.delete_name = customer["party_name"]
        self.show_delete_confirm = True

    @rx.event
    def close_delete(self):
        self.show_delete_confirm = False
        self.delete_id = 0

    @rx.event
    async def confirm_delete(self):
        self.loading = True
        deleted_id = self.delete_id
        old_customers = list(self.customers)
        old_total = self.total

        # Optimistic remove
        self.customers = [c for c in self.customers if c["id"] != deleted_id]
        self.total = max(0, self.total - 1)
        self.show_delete_confirm = False
        yield

        try:
            auth = await self.get_state(AuthState)
            resp = await auth._api_request("DELETE", f"/customers/{deleted_id}")
            if resp is not None and resp.status_code == 200:
                self.success_message = "Customer deleted"
                self.delete_id = 0
                self.delete_name = ""
            else:
                # Rollback on failure
                self.customers = old_customers
                self.total = old_total
                self.error_message = "Delete failed"
        except Exception as e:
            logging.exception(f"delete failed: {e}")
            self.customers = old_customers
            self.total = old_total
            self.error_message = "Delete failed"
        finally:
            self.loading = False

    @rx.event
    def clear_messages(self):
        self.error_message = ""
        self.success_message = ""