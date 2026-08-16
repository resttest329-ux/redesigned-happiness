from __future__ import annotations

import logging

from fasthtml.common import (
    A,
    Button,
    Div,
    Form,
    H2,
    H3,
    Hidden,
    Input,
    P,
    RedirectResponse,
    Script,
    Span,
    Table,
    Tbody,
    Td,
    Th,
    Thead,
    Tr,
    HTMLResponse,
)
from starlette.requests import Request

from deps import (
    current_business_id,
    current_jwt,
    current_username,
    get_session_id,
    require_session,
)
from services import api_client
from ui.icons import icon
from ui.layout import app_shell

logger = logging.getLogger(__name__)


CUSTOMER_FIELDS = [
    ("party_name", "Company name", "text", "Acme Ltd", True),
    ("tin", "TIN", "text", "12345678-0001", True),
    ("email", "Email", "email", "billing@acme.com", True),
    ("telephone", "Telephone", "text", "+234...", True),
    ("street_name", "Street", "text", "21 Main Street", True),
    ("city_name", "City", "text", "Lagos", True),
    ("postal_zone", "Postal zone", "text", "100001", True),
    ("lga", "LGA", "text", "Ikeja", False),
]

CUSTOMER_REQUIRED_ADDRESS = [("country", "Country"), ("state", "State")]


async def _load_customer_lookups(jwt: str, sid: str) -> tuple[list, list]:
    countries, states = [], []
    try:
        countries_raw = await api_client.get_countries(jwt, session_id=sid)
        if isinstance(countries_raw, list):
            countries = countries_raw
    except Exception:
        logger.exception("get_countries failed for customer form")
    try:
        states_raw = await api_client.get_state_codes(jwt, session_id=sid)
        if isinstance(states_raw, list):
            states = states_raw
    except Exception:
        logger.exception("get_state_codes failed for customer form")
    return countries, states


def _customer_form(
    customer: dict | None = None,
    error: str | None = None,
    countries: list | None = None,
    ng_states: list | None = None,
    is_modal: bool = False,
) -> Div:
    is_edit = customer is not None and customer.get("id")
    action = f"/customers/{customer['id']}" if is_edit else "/customers"
    method = "post"

    fields = []
    if error:
        fields.append(alert("error", error))

    grid_children = []
    for name, label, ftype, placeholder, required in CUSTOMER_FIELDS:
        value = (customer or {}).get(name, "") or ""
        grid_children.append(
            text_field(
                name=name,
                label=label,
                type=ftype,
                placeholder=placeholder,
                value=value,
                required=required,
            )
        )
    grid_children.append(
        country_state_fields(
            country_value=(customer or {}).get("country", "") or "NG",
            state_value=(customer or {}).get("state", "") or "",
            countries=countries or [],
            ng_states=ng_states or [],
            required=True,
            field_id_prefix="customer_addr",
        )
    )

    fields.append(
        Div(*grid_children, cls="grid grid-cols-1 md:grid-cols-2 gap-x-4")
    )

    form_kwargs = {"method": method, "action": action}
    if is_modal:
        form_kwargs["hx_post"] = f"{action}-htmx"
        form_kwargs["hx_target"] = "#customer-list-container"

    cancel_btn = (
        A(
            "Cancel",
            href="/customers",
            cls="px-4 py-2 bg-white border border-slate-300 text-slate-700 text-sm font-medium rounded-lg hover:bg-slate-50",
        )
        if not is_modal
        else Button(
            "Cancel",
            hx_get="/customers/clear-overlay",
            hx_target="#customer-modal-area",
            type="button",
            cls="px-4 py-2 bg-white border border-slate-300 text-slate-700 text-sm font-medium rounded-lg hover:bg-slate-50",
        )
    )

    footer = [
        cancel_btn,
        primary_button(
            "Save customer" if not is_edit else "Update customer", type="submit"
        ),
    ]
    form_body = Form(
        *fields, Div(*footer, cls="flex justify-end gap-2 mt-6"), **form_kwargs
    )

    if is_modal:
        return modal_shell(
            title="Edit customer" if is_edit else "New customer",
            subtitle="Update the information below for this workspace customer."
            if is_edit
            else "Add a new customer to your workspace directory.",
            content=form_body,
        )

    return Div(
        Div(
            H2(
                "Edit customer" if is_edit else "New customer",
                cls="text-xl font-bold text-slate-900 mb-4",
            ),
            form_body,
            cls="bg-white border border-slate-200 rounded-2xl p-6 max-w-3xl w-full mx-auto",
        ),
        cls="flex items-center justify-center min-h-[50vh] p-4",
    )


from ui.components import (
    alert,
    confirm_dialog,
    confirm_modal,
    country_state_fields,
    empty_state,
    icon_button,
    modal_shell,
    pagination_controls,
    primary_button,
    section_header,
    table_container,
    text_field,
)


def _customer_row(c: dict) -> Tr:
    initial = (c.get("party_name") or "?")[:1].upper()
    cid = c.get("id", "")
    edit_hx_get = f"/customers/{cid}/edit-overlay"
    return Tr(
        Td(
            Input(
                type="checkbox",
                name="customer_ids",
                value=str(cid),
                cls="zefe-row-check h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500 cursor-pointer",
                onclick="event.stopPropagation();",
            ),
            cls="px-4 py-3 w-10",
        ),
        Td(
            Div(
                Div(
                    initial,
                    cls="h-8 w-8 rounded-full bg-indigo-50 text-indigo-600 flex items-center justify-center text-xs font-semibold shrink-0",
                ),
                Div(
                    P(
                        c.get("party_name", ""),
                        cls="text-sm font-semibold text-slate-900 truncate",
                    ),
                    P(
                        c.get("email", ""),
                        cls="text-xs text-slate-500 truncate",
                    ),
                    cls="min-w-0",
                ),
                cls="flex items-center gap-3 min-w-0",
            ),
            cls="px-4 py-2 max-w-xs cursor-pointer",
            hx_get=edit_hx_get,
            hx_target="#customer-modal-area",
        ),
        Td(
            c.get("tin", ""),
            cls="px-4 py-2 text-sm font-mono text-slate-700 whitespace-nowrap cursor-pointer",
            hx_get=edit_hx_get,
            hx_target="#customer-modal-area",
        ),
        Td(
            c.get("telephone", ""),
            cls="px-4 py-2 text-sm text-slate-700 whitespace-nowrap cursor-pointer",
            hx_get=edit_hx_get,
            hx_target="#customer-modal-area",
        ),
        Td(
            f"{c.get('city_name', '')}, {c.get('country', '')}",
            cls="px-4 py-2 text-sm text-slate-700 cursor-pointer",
            hx_get=edit_hx_get,
            hx_target="#customer-modal-area",
        ),
        Td(
            icon_button(
                "trash",
                "Delete",
                variant="danger",
                hx_get=f"/customers/{cid}/delete-overlay",
                hx_target="#customer-modal-area",
                onclick="event.stopPropagation();",
            ),
            cls="px-4 py-2 text-right w-16",
        ),
        cls="border-b border-slate-100 hover:bg-slate-50/50 transition-colors",
    )


_CUSTOMERS_JS = """
(function(){
  function selected(){return Array.from(document.querySelectorAll('.zefe-row-check:checked')).map(c=>c.value);}
  window.zefeSelectedCustomerIds=function(){return selected().join(',');};
  function refresh(){
    var ids=selected();
    var bar=document.getElementById('zefe-bulk-bar');
    var count=document.getElementById('zefe-bulk-count');
    var input=document.getElementById('zefe-bulk-ids');
    if(bar){bar.style.display=ids.length?'flex':'none';}
    if(count){count.textContent=ids.length+' selected';}
    if(input){input.value=ids.join(',');}
    var all=document.querySelectorAll('.zefe-row-check');
    var sa=document.getElementById('zefe-select-all');
    if(sa){sa.checked=all.length>0 && ids.length===all.length;sa.indeterminate=ids.length>0 && ids.length<all.length;}
  }
  document.addEventListener('change',function(e){
    if(e.target&&e.target.classList&&e.target.classList.contains('zefe-row-check'))refresh();
    if(e.target&&e.target.id==='zefe-select-all'){
      document.querySelectorAll('.zefe-row-check').forEach(c=>c.checked=e.target.checked);refresh();
    }
  });
  document.body.addEventListener('htmx:afterSwap',refresh);
  refresh();
})();
"""


def _customer_table(customers: list[dict]) -> Div:
    if not customers:
        return empty_state(
            icon_name="users",
            title="No customers found",
            subtitle="Try a different search, or add your first customer.",
            action_link=A(
                Span("Add customer"),
                href="/customers/new",
                cls="mt-4 inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700",
            ),
            id="customer-list",
        )

    rows = [_customer_row(c) for c in customers]
    headers = [
        Input(
            type="checkbox",
            id="zefe-select-all",
            cls="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500 cursor-pointer",
        ),
        "Customer",
        "TIN",
        "Phone",
        "Location",
        "",
    ]
    return table_container(headers, rows, id="customer-list")


def _bulk_action_bar() -> Div:
    """Selection bar. Selected IDs are read live from the DOM via hx-vals so a
    stale hidden input can never submit an empty selection."""
    return Div(
        Span(
            "0 selected",
            id="zefe-bulk-count",
            cls="text-sm font-semibold text-slate-700",
        ),
        Input(type="hidden", name="ids", value="", id="zefe-bulk-ids"),
        Button(
            icon("trash", cls="h-4 w-4"),
            Span("Delete selected", cls="text-xs font-semibold"),
            type="button",
            title="Delete selected customers",
            aria_label="Delete selected customers",
            hx_get="/customers/bulk-delete-confirm",
            hx_vals="js:{ids: window.zefeSelectedCustomerIds()}",
            hx_target="#customer-modal-area",
            hx_swap="innerHTML",
            hx_include="[name='q'], [name='page']",
            cls=(
                "inline-flex items-center gap-1.5 px-3 py-1.5 bg-rose-600 "
                "text-white text-xs font-semibold rounded-lg "
                "hover:bg-rose-700 focus:outline-none focus:ring-2 "
                "focus:ring-rose-500 focus:ring-offset-1 transition-colors"
            ),
        ),
        id="zefe-bulk-bar",
        style="display:none;",
        cls=(
            "mb-4 px-4 py-3 bg-rose-50/50 border border-rose-100 rounded-xl "
            "items-center justify-between"
        ),
    )


def _pagination_controls(
    page: int,
    total_pages: int,
    q: str,
    base_path: str = "/customers",
    target_id: str = "#customer-list-container",
) -> Div:
    return pagination_controls(page, total_pages, q, base_path, target_id)


def register_routes(rt) -> None:
    @rt("/customers", methods=["GET"])
    async def list_customers(
        req: Request,
        q: str = "",
        page: int = 1,
        error: str = "",
        success: str = "",
    ):
        redirect = require_session(req)
        if redirect:
            return redirect
        jwt = current_jwt(req)
        sid = get_session_id(req)
        customers: list[dict] = []
        total_items = 0
        limit = 10
        offset = (page - 1) * limit
        load_error = ""
        try:
            result = await api_client.list_customers(
                jwt,
                session_id=sid,
                search=q or None,
                offset=offset,
                limit=limit,
            )
            customers = result.get("items", [])
            total_items = result.get("total", 0)
        except api_client.APIError:
            logger.exception("list_customers failed")
            load_error = "Failed to load customers."
        except Exception:
            logger.exception("list_customers transport error")
            load_error = "Backend service unavailable."

        total_pages = max(1, (total_items + limit - 1) // limit)

        is_htmx = req.headers.get("HX-Request") == "true"
        if is_htmx:
            return Div(
                _bulk_action_bar(),
                _customer_table(customers),
                _pagination_controls(
                    page,
                    total_pages,
                    q,
                    "/customers",
                    "#customer-list-container",
                ),
                Script(_CUSTOMERS_JS),
                id="customer-list-container",
            )

        header = Div(
            Div(
                H2(
                    "Customers",
                    cls="text-2xl font-bold text-slate-900",
                ),
                P(
                    f"{total_items} customer(s) in your workspace",
                    cls="text-sm text-slate-500 mt-1",
                ),
            ),
            Button(
                icon("plus", cls="h-4 w-4"),
                Span("Add customer"),
                hx_get="/customers/new-overlay",
                hx_target="#customer-modal-area",
                cls="inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700",
            ),
            cls="flex items-center justify-between mb-6",
        )

        search_inputs = [
            Div(
                icon(
                    "search",
                    cls="h-4 w-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2",
                ),
                Input(
                    name="q",
                    type="search",
                    placeholder="Search by name, TIN, or email…",
                    value=q,
                    autocomplete="off",
                    hx_get="/customers",
                    hx_trigger="keyup changed delay:300ms, search, change",
                    hx_target="#customer-list-container",
                    hx_swap="innerHTML",
                    hx_include="this",
                    hx_push_url="true",
                    cls="w-full pl-9 pr-3 py-2 bg-white text-slate-900 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500",
                ),
                cls="relative flex-1 min-w-0",
            ),
            Hidden(name="page", value="1"),
        ]
        if q:
            search_inputs.append(
                A(
                    icon("x", cls="h-4 w-4"),
                    Span("Clear"),
                    href="/customers",
                    cls="inline-flex items-center gap-1.5 px-3 py-2 text-sm font-medium text-slate-600 hover:text-slate-900 shrink-0",
                )
            )
        search = Form(
            Div(*search_inputs, cls="flex items-center gap-2 max-w-xl"),
            method="get",
            action="/customers",
            cls="mb-4",
        )

        banners = []
        if error:
            banners.append(alert("error", error))
        if success:
            banners.append(alert("success", success))
        if load_error:
            banners.append(alert("error", load_error))

        list_container = Div(
            _bulk_action_bar(),
            _customer_table(customers),
            _pagination_controls(
                page, total_pages, q, "/customers", "#customer-list-container"
            ),
            id="customer-list-container",
        )

        return app_shell(
            "Customers",
            header,
            *banners,
            search,
            list_container,
            Div(id="customer-modal-area"),
            Script(_CUSTOMERS_JS),
            active_nav="customers",
            username=current_username(req),
            business_id=current_business_id(req),
        )

    @rt("/customers/{cid}/delete-overlay", methods=["GET"])
    async def delete_overlay(req: Request, cid: int):
        redirect = require_session(req)
        if redirect:
            return redirect
        jwt = current_jwt(req)
        sid = get_session_id(req)
        try:
            customer = await api_client.get_customer(jwt, cid, session_id=sid)
        except Exception:
            logger.exception("delete_overlay: get_customer failed")
            return HTMLResponse("")

        confirm_btn = Form(
            Button(
                Span("Delete customer"),
                type="submit",
                cls="px-4 py-2 bg-rose-600 text-white text-sm font-medium rounded-lg hover:bg-rose-700",
            ),
            hx_post=f"/customers/{cid}/delete-htmx",
            hx_target="#customer-list-container",
            cls="inline",
        )

        return confirm_modal(
            title="Delete this customer?",
            message=f'You are about to permanently delete "{customer.get("party_name", "")}". This action cannot be undone.',
            confirm_btn=confirm_btn,
            cancel_hx_target="#customer-modal-area",
        )

    @rt("/customers/clear-overlay", methods=["GET"])
    def clear_overlay(req: Request):
        return HTMLResponse("")

    @rt("/customers/new-overlay", methods=["GET"])
    async def new_overlay(req: Request):
        redirect = require_session(req)
        if redirect:
            return redirect
        jwt, sid = current_jwt(req), get_session_id(req)
        countries, ng_states = await _load_customer_lookups(jwt, sid)
        return _customer_form(
            customer={"country": "NG"},
            countries=countries,
            ng_states=ng_states,
            is_modal=True,
        )

    @rt("/customers/{cid}/edit-overlay", methods=["GET"])
    async def edit_overlay(req: Request, cid: int):
        redirect = require_session(req)
        if redirect:
            return redirect
        jwt, sid = current_jwt(req), get_session_id(req)
        try:
            customer = await api_client.get_customer(jwt, cid, session_id=sid)
        except Exception:
            logging.exception("Unexpected error")
            return HTMLResponse("")
        countries, ng_states = await _load_customer_lookups(jwt, sid)
        return _customer_form(
            customer=customer,
            countries=countries,
            ng_states=ng_states,
            is_modal=True,
        )

    @rt("/customers-htmx", methods=["POST"])
    async def create_htmx(req: Request):
        redirect = require_session(req)
        if redirect:
            return redirect
        form = await req.form()
        payload = {
            name: (form.get(name) or "").strip()
            for name, _, _, _, _ in CUSTOMER_FIELDS
        }
        payload["country"] = (form.get("country") or "").strip()
        payload["state"] = (form.get("state") or "").strip()
        if not payload.get("lga"):
            payload["lga"] = None

        jwt, sid = current_jwt(req), get_session_id(req)
        try:
            await api_client.create_customer(jwt, payload, session_id=sid)
            res = await api_client.list_customers(jwt, session_id=sid, limit=10)
            return Div(
                alert("success", "Customer created successfully"),
                _bulk_action_bar(),
                _customer_table(res.get("items", [])),
                _pagination_controls(
                    1, max(1, (res.get("total", 0) + 9) // 10), ""
                ),
                Div(id="customer-modal-area", hx_swap_oob="innerHTML"),
                Script(_CUSTOMERS_JS),
                id="customer-list-container",
            )
        except api_client.APIError as e:
            logging.exception("Unexpected error")
            countries, ng_states = await _load_customer_lookups(jwt, sid)
            return _customer_form(
                customer=payload,
                error=str(e.detail),
                countries=countries,
                ng_states=ng_states,
                is_modal=True,
            )

    @rt("/customers/{cid}-htmx", methods=["POST"])
    async def update_htmx_route(req: Request, cid: int):
        redirect = require_session(req)
        if redirect:
            return redirect
        form = await req.form()
        payload = {
            name: (form.get(name) or "").strip()
            for name, _, _, _, _ in CUSTOMER_FIELDS
        }
        payload["country"] = (form.get("country") or "").strip()
        payload["state"] = (form.get("state") or "").strip()
        if not payload.get("lga"):
            payload["lga"] = None

        jwt, sid = current_jwt(req), get_session_id(req)
        try:
            await api_client.update_customer(jwt, cid, payload, session_id=sid)
            res = await api_client.list_customers(jwt, session_id=sid, limit=10)
            return Div(
                alert("success", "Customer updated successfully"),
                _bulk_action_bar(),
                _customer_table(res.get("items", [])),
                _pagination_controls(
                    1, max(1, (res.get("total", 0) + 9) // 10), ""
                ),
                Div(id="customer-modal-area", hx_swap_oob="innerHTML"),
                Script(_CUSTOMERS_JS),
                id="customer-list-container",
            )
        except api_client.APIError as e:
            logging.exception("Unexpected error")
            countries, ng_states = await _load_customer_lookups(jwt, sid)
            payload["id"] = cid
            return _customer_form(
                customer=payload,
                error=str(e.detail),
                countries=countries,
                ng_states=ng_states,
                is_modal=True,
            )

    @rt("/customers/{cid}/delete-htmx", methods=["POST"])
    async def delete_htmx(req: Request, cid: int):
        redirect = require_session(req)
        if redirect:
            return redirect
        jwt = current_jwt(req)
        sid = get_session_id(req)
        deleted_name = ""
        try:
            customer = await api_client.get_customer(jwt, cid, session_id=sid)
            deleted_name = customer.get("party_name", f"#{cid}")
            await api_client.delete_customer(jwt, cid, session_id=sid)
            success_msg = f"Customer '{deleted_name}' deleted successfully"
        except Exception:
            logger.exception("delete_htmx: delete failed")
            success_msg = "Could not delete customer"

        customers = []
        try:
            result = await api_client.list_customers(
                jwt, session_id=sid, limit=200
            )
            customers = result.get("items", [])
        except Exception:
            logger.exception("delete_htmx: reload customers failed")

        return Div(
            alert("success", success_msg)
            if "successfully" in success_msg
            else alert("error", success_msg),
            _bulk_action_bar(),
            _customer_table(customers),
            Div(id="customer-modal-area", hx_swap_oob="innerHTML"),
            Script(_CUSTOMERS_JS),
            id="customer-list-container",
        )

    @rt("/customers/bulk-delete-confirm", methods=["GET"])
    async def bulk_delete_confirm(
        req: Request, ids: str = "", q: str = "", page: int = 1
    ):
        redirect = require_session(req)
        if redirect:
            return redirect
        id_list = [s.strip() for s in (ids or "").split(",") if s.strip()]
        if not id_list:
            return confirm_dialog(
                title="Nothing selected",
                message=(
                    "Tick the checkbox on one or more customer rows, then "
                    "choose Delete selected again."
                ),
                confirm_control="",
                cancel_get="/customers/clear-overlay",
                cancel_target="#customer-modal-area",
                cancel_label="Close",
                icon_name="alert-circle",
                tone="info",
            )

        jwt = current_jwt(req)
        sid = get_session_id(req)
        names: list[str] = []
        clean_ids: list[str] = []
        for raw in id_list[:50]:
            try:
                cid = int(raw)
            except (TypeError, ValueError):
                continue
            clean_ids.append(cid)
            try:
                c = await api_client.get_customer(jwt, cid, session_id=sid)
                names.append(c.get("party_name", f"#{cid}"))
            except Exception:
                logger.exception("bulk_delete_confirm: get_customer failed")
                names.append(f"#{raw}")

        selected_chips = [
            Div(
                icon("users", cls="h-3 w-3 text-slate-500 shrink-0"),
                Span(n, cls="text-sm text-slate-700 truncate"),
                cls="flex items-center gap-2 px-3 py-1.5 bg-white border border-slate-200 rounded-lg min-w-0",
            )
            for n in names
        ]

        count = len(clean_ids)
        plural = "customer" if count == 1 else "customers"

        confirm_btn = Form(
            Hidden(name="ids", value=",".join(str(x) for x in clean_ids)),
            Hidden(name="q", value=q),
            Hidden(name="page", value=str(page)),
            Button(
                Span(f"Delete {count} {plural}"),
                type="submit",
                cls="px-4 py-2 bg-rose-600 text-white text-sm font-medium rounded-lg hover:bg-rose-700",
            ),
            hx_post="/customers/bulk-delete-htmx",
            hx_target="#customer-list-container",
            hx_swap="outerHTML",
            method="post",
            action="/customers/bulk-delete",
            cls="inline",
        )

        return confirm_dialog(
            title=f"Delete {count} {plural}?",
            message=(
                f"You are about to permanently delete {count} {plural} from "
                "your workspace. Past invoices keep their stored customer "
                "details, but this action cannot be undone."
            ),
            confirm_control=confirm_btn,
            cancel_get="/customers/clear-overlay",
            cancel_target="#customer-modal-area",
            details=Div(
                *selected_chips,
                cls=(
                    "flex flex-wrap gap-2 mt-5 p-4 bg-slate-50 border "
                    "border-slate-200 rounded-xl max-h-60 overflow-auto"
                ),
            ),
            max_w="max-w-lg",
        )

    @rt("/customers/bulk-delete-htmx", methods=["POST"])
    async def bulk_delete_htmx(req: Request):
        redirect = require_session(req)
        if redirect:
            return redirect
        form = await req.form()
        ids = (form.get("ids") or "").strip()
        q = (form.get("q") or "").strip()
        try:
            page = int(form.get("page") or 1)
        except ValueError:
            page = 1
        id_list = [s.strip() for s in ids.split(",") if s.strip()]
        jwt = current_jwt(req)
        sid = get_session_id(req)
        success_count = 0
        for raw in id_list:
            try:
                cid = int(raw)
            except ValueError:
                continue
            try:
                await api_client.delete_customer(jwt, cid, session_id=sid)
                success_count += 1
            except Exception:
                logger.exception(f"bulk_delete_htmx: failed for {raw}")

        success_msg = (
            f"Successfully deleted {success_count} customer(s)"
            if success_count
            else ""
        )

        customers = []
        total_items = 0
        limit = 10
        offset = (page - 1) * limit
        try:
            result = await api_client.list_customers(
                jwt,
                session_id=sid,
                search=q or None,
                offset=offset,
                limit=limit,
            )
            customers = result.get("items", [])
            total_items = result.get("total", 0)
        except Exception:
            logger.exception("bulk_delete_htmx: reload customers failed")

        total_pages = max(1, (total_items + limit - 1) // limit)
        if not customers and page > 1:
            page -= 1
            offset = (page - 1) * limit
            try:
                result = await api_client.list_customers(
                    jwt,
                    session_id=sid,
                    search=q or None,
                    offset=offset,
                    limit=limit,
                )
                customers = result.get("items", [])
                total_items = result.get("total", 0)
                total_pages = max(1, (total_items + limit - 1) // limit)
            except Exception:
                logger.exception("bulk_delete_htmx: fallback reload failed")

        return Div(
            alert("success", success_msg) if success_msg else "",
            _bulk_action_bar(),
            _customer_table(customers),
            _pagination_controls(
                page,
                total_pages,
                q,
                "/customers",
                "#customer-list-container",
            ),
            Div(id="customer-modal-area", hx_swap_oob="innerHTML"),
            Script(_CUSTOMERS_JS),
            id="customer-list-container",
        )

    @rt("/customers/bulk-delete", methods=["POST"])
    async def bulk_delete(req: Request):
        redirect = require_session(req)
        if redirect:
            return redirect
        form = await req.form()
        ids = (form.get("ids") or "").strip()
        id_list = [s.strip() for s in ids.split(",") if s.strip()]
        jwt = current_jwt(req)
        sid = get_session_id(req)
        deleted = 0
        for raw in id_list:
            try:
                cid = int(raw)
            except ValueError:
                continue
            try:
                await api_client.delete_customer(jwt, cid, session_id=sid)
                deleted += 1
            except Exception:
                logger.exception(f"bulk_delete: failed for {raw}")
        return RedirectResponse(
            f"/customers?error=Deleted+{deleted}+customer(s)"
            if deleted
            else "/customers?error=No+customers+were+deleted",
            status_code=303,
        )

    @rt("/customers/new", methods=["GET"])
    async def new_customer(req: Request, error: str = ""):
        redirect = require_session(req)
        if redirect:
            return redirect
        jwt = current_jwt(req)
        sid = get_session_id(req)
        countries, ng_states = await _load_customer_lookups(jwt, sid)
        return app_shell(
            "New customer",
            section_header(
                "New customer",
                "Add a customer that you can invoice from the wizard.",
            ),
            _customer_form(
                customer={"country": "NG"},
                error=error or None,
                countries=countries,
                ng_states=ng_states,
            ),
            active_nav="customers",
            username=current_username(req),
            business_id=current_business_id(req),
        )

    @rt("/customers", methods=["POST"])
    async def create_customer(req: Request):
        redirect = require_session(req)
        if redirect:
            return redirect
        form = await req.form()
        payload = {
            name: (form.get(name) or "").strip()
            for name, _, _, _, _ in CUSTOMER_FIELDS
        }
        payload["country"] = (form.get("country") or "").strip()
        payload["state"] = (form.get("state") or "").strip()

        missing_fields = []
        for name, label, _, _, required in CUSTOMER_FIELDS:
            if required and not payload.get(name):
                missing_fields.append(label)
        for name, label in CUSTOMER_REQUIRED_ADDRESS:
            if not payload.get(name):
                missing_fields.append(label)
        if missing_fields:
            error_msg = f"Missing required fields: {', '.join(missing_fields)}"
            return RedirectResponse(
                f"/customers/new?error={error_msg.replace(' ', '+')}",
                status_code=303,
            )

        if not payload.get("lga"):
            payload["lga"] = None

        jwt = current_jwt(req)
        sid = get_session_id(req)
        try:
            await api_client.create_customer(jwt, payload, session_id=sid)
        except api_client.APIError as e:
            logger.exception("create_customer failed")
            detail = (
                e.detail
                if isinstance(e.detail, str)
                else "Could not create customer"
            )
            return RedirectResponse(
                f"/customers/new?error={detail}", status_code=303
            )
        except Exception:
            logger.exception("create_customer transport error")
            return RedirectResponse(
                "/customers/new?error=Backend+service+unavailable",
                status_code=303,
            )
        return RedirectResponse(
            "/customers?success=Customer+created+successfully", status_code=303
        )

    @rt("/customers/{cid}/edit", methods=["GET"])
    async def edit_customer(req: Request, cid: int, error: str = ""):
        redirect = require_session(req)
        if redirect:
            return redirect
        jwt = current_jwt(req)
        sid = get_session_id(req)
        try:
            customer = await api_client.get_customer(jwt, cid, session_id=sid)
        except Exception:
            logger.exception("get_customer failed")
            return RedirectResponse(
                "/customers?error=Customer+not+found", status_code=303
            )
        countries, ng_states = await _load_customer_lookups(jwt, sid)
        return app_shell(
            "Edit customer",
            section_header("Edit customer", customer.get("party_name", "")),
            _customer_form(
                customer=customer,
                error=error or None,
                countries=countries,
                ng_states=ng_states,
            ),
            active_nav="customers",
            username=current_username(req),
            business_id=current_business_id(req),
        )

    @rt("/customers/{cid}", methods=["POST"])
    async def update_customer(req: Request, cid: int):
        redirect = require_session(req)
        if redirect:
            return redirect
        form = await req.form()
        payload = {
            name: (form.get(name) or "").strip()
            for name, _, _, _, _ in CUSTOMER_FIELDS
        }
        payload["country"] = (form.get("country") or "").strip()
        payload["state"] = (form.get("state") or "").strip()

        missing_fields = []
        for name, label, _, _, required in CUSTOMER_FIELDS:
            if required and not payload.get(name):
                missing_fields.append(label)
        for name, label in CUSTOMER_REQUIRED_ADDRESS:
            if not payload.get(name):
                missing_fields.append(label)
        if missing_fields:
            error_msg = f"Missing required fields: {', '.join(missing_fields)}"
            return RedirectResponse(
                f"/customers/{cid}/edit?error={error_msg.replace(' ', '+')}",
                status_code=303,
            )

        if not payload.get("lga"):
            payload["lga"] = None

        jwt = current_jwt(req)
        sid = get_session_id(req)
        try:
            await api_client.update_customer(jwt, cid, payload, session_id=sid)
        except api_client.APIError as e:
            logger.exception("update_customer failed")
            detail = e.detail if isinstance(e.detail, str) else "Update failed"
            return RedirectResponse(
                f"/customers/{cid}/edit?error={detail}", status_code=303
            )
        except Exception:
            logger.exception("update_customer transport error")
            return RedirectResponse(
                f"/customers/{cid}/edit?error=Backend+service+unavailable",
                status_code=303,
            )
        return RedirectResponse(
            "/customers?success=Customer+updated+successfully", status_code=303
        )

    @rt("/customers/{cid}/delete", methods=["POST"])
    async def delete_customer(req: Request, cid: int):
        redirect = require_session(req)
        if redirect:
            return redirect
        jwt = current_jwt(req)
        sid = get_session_id(req)
        try:
            await api_client.delete_customer(jwt, cid, session_id=sid)
        except Exception:
            logger.exception("delete_customer failed")
            return RedirectResponse(
                "/customers?error=Could+not+delete+customer",
                status_code=303,
            )
        return RedirectResponse(
            "/customers?error=Customer+deleted", status_code=303
        )
