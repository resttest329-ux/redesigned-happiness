"""Customer directory pages for the standalone FastHTML frontend.

Customers behave exactly like catalog items: they are scoped to the business,
soft-deleted (``is_active``) so removing one never rewrites invoice history,
searchable across name / TIN / email, filterable by status, and importable in
bulk from a spreadsheet.

UI intentionally mirrors the Items page: white/slate surfaces, thin 1px
borders, rounded-lg/xl, indigo accents, flat compact tables and modals.
"""

from __future__ import annotations

import logging
import urllib.parse

from fasthtml.common import (
    Button,
    Div,
    Form,
    H2,
    H3,
    Hidden,
    Input,
    Label,
    Option,
    P,
    RedirectResponse,
    Script,
    Select,
    Span,
    Td,
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
from services.errors import extract_api_error_detail
from ui.components import (
    alert,
    country_state_fields,
    empty_state,
    guidance_panel,
    guidance_text,
    primary_button,
    table_container,
)
from ui.icons import icon
from ui.layout import app_shell

logger = logging.getLogger(__name__)

PAGE_SIZE = 10
MODAL_AREA = "#customer-modal-area"
LIST_TARGET = "#customer-list-container"
FILTERS = "#customer-filters"

_CLEAR_OVERLAY = "/customers/clear-overlay"

_INPUT_CLS = (
    "w-full px-3 py-2 bg-white text-slate-900 border border-slate-300 "
    "rounded-lg text-sm placeholder-slate-400 focus:outline-none "
    "focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
)
_SELECT_CLS = (
    "w-full appearance-none px-3 py-2 pr-9 bg-white text-slate-900 "
    "border border-slate-300 rounded-lg text-sm focus:outline-none "
    "focus:ring-2 focus:ring-indigo-500"
)
_CHEVRON_CLS = (
    "h-4 w-4 text-slate-400 absolute right-3 top-1/2 "
    "-translate-y-1/2 pointer-events-none"
)
_GHOST_BTN = (
    "px-4 py-2 bg-white border border-slate-300 text-slate-700 text-sm "
    "font-medium rounded-lg hover:bg-slate-50"
)
_DANGER_BTN = (
    "px-4 py-2 bg-rose-600 text-white text-sm font-medium rounded-lg "
    "hover:bg-rose-700"
)
_INDIGO_BTN = (
    "inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white "
    "text-sm font-medium rounded-lg hover:bg-indigo-700"
)

#: (name, label, input type, placeholder, required)
CUSTOMER_FIELDS = [
    ("party_name", "Company name", "text", "Acme Ltd", True),
    ("tin", "TIN", "text", "12345678-0001", True),
    ("email", "Email", "email", "billing@acme.com", True),
    ("telephone", "Telephone", "text", "+234 800 000 0000", True),
    ("street_name", "Street", "text", "21 Main Street", True),
    ("city_name", "City", "text", "Lagos", True),
    ("postal_zone", "Postal zone", "text", "100001", True),
    ("lga", "LGA", "text", "Ikeja", False),
]

CUSTOMER_REQUIRED_ADDRESS = [("country", "Country"), ("state", "State")]

IMPORT_COLUMNS = (
    "tin, party_name, email, telephone, street_name, city_name, "
    "postal_zone, country, state, lga"
)

FIELD_HELP = {
    "tin": "FIRS format: NNNNNNNN-NNNN",
    "email": "Used as the invoice recipient address.",
    "lga": "Optional local government area.",
}


# --------------------------------------------------------------------------
# Small field helpers (scoped to this page)
# --------------------------------------------------------------------------


def _field(
    *,
    name: str,
    label: str,
    value: str = "",
    type: str = "text",
    placeholder: str = "",
    required: bool = False,
    helper: str = "",
    **kwargs,
) -> Div:
    attrs = {
        "id": f"customer_{name}",
        "name": name,
        "type": type,
        "placeholder": placeholder,
        "value": value or "",
        **kwargs,
    }
    if required:
        attrs["required"] = True
    children = [
        Label(
            label,
            Span(" *", cls="text-rose-500 font-bold") if required else "",
            fr=f"customer_{name}",
            cls="block text-sm font-medium text-slate-700 mb-1.5",
        ),
        Input(**attrs, cls=_INPUT_CLS),
    ]
    if helper:
        children.append(guidance_text(helper))
    return Div(*children, cls="mb-4")


def _status_badge(is_active: bool) -> Span:
    if is_active:
        return Span(
            "Active",
            cls=(
                "inline-flex items-center px-2 py-0.5 rounded-full text-xs "
                "font-medium bg-emerald-50 text-emerald-700 "
                "border border-emerald-200 w-fit"
            ),
        )
    return Span(
        "Inactive",
        cls=(
            "inline-flex items-center px-2 py-0.5 rounded-full text-xs "
            "font-medium bg-slate-50 text-slate-600 "
            "border border-slate-200 w-fit"
        ),
    )


# --------------------------------------------------------------------------
# Modal shell
# --------------------------------------------------------------------------


def _modal_card(*children, max_w: str = "max-w-3xl") -> Div:
    return Div(
        Div(
            *children,
            cls=(
                "bg-white border border-slate-200 rounded-2xl w-full "
                f"{max_w} shadow-lg overflow-hidden animate-fade-in-up"
            ),
        ),
        cls=(
            "fixed inset-0 z-50 flex items-center justify-center "
            "bg-slate-900/40 backdrop-blur-xs p-4"
        ),
    )


def _modal_header(title: str, subtitle: str) -> Div:
    return Div(
        Div(
            H3(title, cls="text-lg font-bold text-slate-900"),
            P(subtitle, cls="text-sm text-slate-500 mt-0.5"),
            cls="flex-1 min-w-0",
        ),
        Button(
            icon("x", cls="h-4 w-4"),
            type="button",
            hx_get=_CLEAR_OVERLAY,
            hx_target=MODAL_AREA,
            hx_swap="innerHTML",
            cls=(
                "p-1.5 rounded-lg text-slate-400 hover:bg-slate-100 "
                "hover:text-slate-700 shrink-0"
            ),
        ),
        cls=(
            "flex items-start justify-between gap-3 px-6 py-4 "
            "border-b border-slate-200"
        ),
    )


def _modal_footer(*children) -> Div:
    return Div(
        *children,
        cls=(
            "flex justify-end gap-2 px-6 py-4 border-t border-slate-200 "
            "bg-slate-50 rounded-b-2xl"
        ),
    )


def _cancel_button(label: str = "Cancel") -> Button:
    return Button(
        Span(label),
        type="button",
        hx_get=_CLEAR_OVERLAY,
        hx_target=MODAL_AREA,
        hx_swap="innerHTML",
        cls=_GHOST_BTN,
    )


def _notice_modal(title: str, subtitle: str, body_text: str) -> Div:
    return _modal_card(
        _modal_header(title, subtitle),
        Div(P(body_text, cls="text-sm text-slate-600"), cls="px-6 py-5"),
        _modal_footer(_cancel_button("Close")),
        max_w="max-w-md",
    )


# --------------------------------------------------------------------------
# Customer form modal
# --------------------------------------------------------------------------


def _customer_form_modal(
    customer: dict | None = None,
    *,
    error: str = "",
    countries: list | None = None,
    ng_states: list | None = None,
) -> Div:
    customer = customer or {}
    cid = str(customer.get("id", "") or "")
    is_edit = bool(cid)

    body: list = []
    if error:
        body.append(alert("error", error, cls="mb-4"))
    body.append(
        guidance_panel(
            "Customer details are copied onto every invoice you raise for "
            "them, so keep the TIN and address accurate.",
            cls="mb-4",
        )
    )

    grid: list = []
    for name, label, ftype, placeholder, required in CUSTOMER_FIELDS:
        grid.append(
            _field(
                name=name,
                label=label,
                value=str(customer.get(name, "") or ""),
                type=ftype,
                placeholder=placeholder,
                required=required,
                helper=FIELD_HELP.get(name, ""),
            )
        )
    grid.append(
        country_state_fields(
            country_value=str(customer.get("country", "") or "NG"),
            state_value=str(customer.get("state", "") or ""),
            countries=countries or [],
            ng_states=ng_states or [],
            required=True,
            field_id_prefix="customer_addr",
        )
    )
    body.append(Div(*grid, cls="grid grid-cols-1 md:grid-cols-2 gap-x-4"))

    return _modal_card(
        Form(
            Hidden(name="customer_id", value=cid),
            _modal_header(
                "Edit customer" if is_edit else "New customer",
                "Saved to your workspace directory and reusable on invoices.",
            ),
            Div(*body, cls="px-6 py-5 max-h-[70vh] overflow-auto"),
            _modal_footer(
                _cancel_button(),
                Button(
                    icon("check-circle", cls="h-4 w-4"),
                    Span("Update customer" if is_edit else "Save customer"),
                    type="submit",
                    cls=_INDIGO_BTN,
                ),
            ),
            hx_post="/customers/save",
            hx_target=LIST_TARGET,
            hx_swap="outerHTML",
            hx_include=FILTERS,
            method="post",
            action="/customers/save",
            cls="flex flex-col",
        )
    )


# --------------------------------------------------------------------------
# Table
# --------------------------------------------------------------------------


def _customer_row(c: dict) -> Tr:
    cid = c.get("id", "")
    name = str(c.get("party_name", "") or "")
    initial = (name or "?")[:1].upper()
    is_active = bool(c.get("is_active", True))
    edit_attrs = {
        "hx_get": f"/customers/{cid}/edit-overlay",
        "hx_target": MODAL_AREA,
        "hx_swap": "innerHTML",
    }
    cell = "px-4 py-2 cursor-pointer"

    if is_active:
        # Deactivation changes what future invoices can use, so confirm first.
        toggle_control = Button(
            icon("x", cls="h-4 w-4"),
            type="button",
            title="Deactivate customer",
            aria_label=f"Deactivate customer {name}",
            onclick="event.stopPropagation();",
            hx_get=f"/customers/{cid}/deactivate-overlay",
            hx_target=MODAL_AREA,
            hx_swap="innerHTML",
            cls=(
                "p-2 rounded-lg text-slate-400 hover:bg-amber-50 "
                "hover:text-amber-600 transition-colors"
            ),
        )
    else:
        # Restoring is reversible, so no confirmation.
        toggle_control = Form(
            Button(
                icon("rotate-ccw", cls="h-4 w-4"),
                type="submit",
                title="Restore customer",
                aria_label=f"Restore customer {name}",
                onclick="event.stopPropagation();",
                cls=(
                    "p-2 rounded-lg text-slate-400 hover:bg-emerald-50 "
                    "hover:text-emerald-600 transition-colors"
                ),
            ),
            method="post",
            action=f"/customers/{cid}/restore",
            hx_post=f"/customers/{cid}/restore",
            hx_target=LIST_TARGET,
            hx_swap="outerHTML",
            hx_include=FILTERS,
            cls="inline",
        )

    return Tr(
        Td(
            Input(
                type="checkbox",
                name="customer_ids",
                value=str(cid),
                cls=(
                    "zefe-customer-check h-4 w-4 rounded border-slate-300 "
                    "text-indigo-600 focus:ring-indigo-500 cursor-pointer"
                ),
                onclick="event.stopPropagation();",
            ),
            cls="px-4 py-3 w-10",
        ),
        Td(
            Div(
                Div(
                    initial,
                    cls=(
                        "h-8 w-8 rounded-full bg-indigo-50 text-indigo-600 "
                        "flex items-center justify-center text-xs "
                        "font-semibold shrink-0"
                    ),
                ),
                Div(
                    P(
                        name,
                        cls="text-sm font-semibold text-slate-900 truncate",
                    ),
                    P(
                        c.get("email", "") or "",
                        cls="text-xs text-slate-500 truncate",
                    ),
                    cls="min-w-0",
                ),
                cls="flex items-center gap-3 min-w-0",
            ),
            cls=f"{cell} max-w-xs",
            **edit_attrs,
        ),
        Td(
            c.get("tin", "") or "",
            cls=(
                "px-4 py-2 text-sm font-mono text-slate-700 "
                "whitespace-nowrap cursor-pointer"
            ),
            **edit_attrs,
        ),
        Td(
            c.get("telephone", "") or "",
            cls="px-4 py-2 text-sm text-slate-700 whitespace-nowrap "
            "cursor-pointer",
            **edit_attrs,
        ),
        Td(
            f"{c.get('city_name', '') or ''}, {c.get('country', '') or ''}",
            cls="px-4 py-2 text-sm text-slate-700 cursor-pointer",
            **edit_attrs,
        ),
        Td(_status_badge(is_active), cls=cell, **edit_attrs),
        Td(
            Div(
                toggle_control,
                Button(
                    icon("trash", cls="h-4 w-4"),
                    type="button",
                    title="Delete permanently",
                    aria_label=f"Delete customer {name}",
                    onclick="event.stopPropagation();",
                    hx_get=f"/customers/{cid}/delete-overlay",
                    hx_target=MODAL_AREA,
                    hx_swap="innerHTML",
                    cls=(
                        "p-2 rounded-lg text-slate-400 hover:bg-rose-50 "
                        "hover:text-rose-600 transition-colors"
                    ),
                ),
                cls="flex items-center justify-end gap-1",
            ),
            cls="px-4 py-2 text-right w-24",
        ),
        cls="border-b border-slate-100 hover:bg-slate-50/50 transition-colors",
    )


def _customer_table(customers: list[dict], active: bool) -> Div:
    if not customers:
        return empty_state(
            icon_name="users",
            title="No customers found" if active else "No inactive customers",
            subtitle=(
                "Add your first customer, or import a spreadsheet to get "
                "started."
                if active
                else "Deactivated customers appear here and can be restored."
            ),
            action_link=Button(
                icon("plus", cls="h-4 w-4"),
                Span("Add customer"),
                type="button",
                hx_get="/customers/new-overlay",
                hx_target=MODAL_AREA,
                hx_swap="innerHTML",
                cls=f"mt-4 {_INDIGO_BTN}",
            )
            if active
            else None,
            id="customer-list",
        )
    headers = [
        Input(
            type="checkbox",
            id="zefe-customer-select-all",
            cls=(
                "h-4 w-4 rounded border-slate-300 text-indigo-600 "
                "focus:ring-indigo-500 cursor-pointer"
            ),
        ),
        "Customer",
        "TIN",
        "Phone",
        "Location",
        "Status",
        "",
    ]
    return table_container(
        headers, [_customer_row(c) for c in customers], id="customer-list"
    )


_CUSTOMERS_JS = """
(function(){
  function selected(){
    return Array.from(document.querySelectorAll('.zefe-customer-check:checked'))
      .map(function(c){return c.value;});
  }
  function refresh(){
    var ids = selected();
    var bar = document.getElementById('zefe-customer-bulk-bar');
    var count = document.getElementById('zefe-customer-bulk-count');
    document.querySelectorAll('.zefe-customer-bulk-ids').forEach(function(i){
      i.value = ids.join(',');
    });
    if (bar) bar.style.display = ids.length ? 'flex' : 'none';
    if (count) count.textContent = ids.length + ' selected';
    var all = document.querySelectorAll('.zefe-customer-check');
    var sa = document.getElementById('zefe-customer-select-all');
    if (sa) {
      sa.checked = all.length > 0 && ids.length === all.length;
      sa.indeterminate = ids.length > 0 && ids.length < all.length;
    }
  }
  document.addEventListener('change', function(e){
    if (e.target && e.target.classList &&
        e.target.classList.contains('zefe-customer-check')) refresh();
    if (e.target && e.target.id === 'zefe-customer-select-all') {
      document.querySelectorAll('.zefe-customer-check').forEach(function(c){
        c.checked = e.target.checked;
      });
      refresh();
    }
  });
  document.body.addEventListener('htmx:afterSwap', refresh);
  refresh();
})();
"""


def _bulk_bar(active: bool) -> Div:
    if active:
        primary_label = "Deactivate selected"
        primary_icon = "x"
        primary_action = "deactivate"
        primary_cls = (
            "inline-flex items-center gap-1.5 px-3 py-1.5 bg-white "
            "border border-amber-300 text-amber-700 text-xs font-semibold "
            "rounded-lg hover:bg-amber-50"
        )
    else:
        primary_label = "Restore selected"
        primary_icon = "rotate-ccw"
        primary_action = "restore"
        primary_cls = (
            "inline-flex items-center gap-1.5 px-3 py-1.5 bg-white "
            "border border-emerald-300 text-emerald-700 text-xs "
            "font-semibold rounded-lg hover:bg-emerald-50"
        )

    return Div(
        Span(
            "0 selected",
            id="zefe-customer-bulk-count",
            cls="text-sm font-semibold text-slate-700",
        ),
        Div(
            Button(
                icon(primary_icon, cls="h-3.5 w-3.5"),
                Span(primary_label),
                type="button",
                hx_get=f"/customers/bulk-confirm?action={primary_action}",
                hx_target=MODAL_AREA,
                hx_swap="innerHTML",
                hx_include=f"#zefe-customer-bulk-ids-1, {FILTERS}",
                cls=primary_cls,
            ),
            Button(
                icon("trash", cls="h-3.5 w-3.5"),
                Span("Delete selected"),
                type="button",
                hx_get="/customers/bulk-confirm?action=delete",
                hx_target=MODAL_AREA,
                hx_swap="innerHTML",
                hx_include=f"#zefe-customer-bulk-ids-2, {FILTERS}",
                cls=(
                    "inline-flex items-center gap-1.5 px-3 py-1.5 "
                    "bg-rose-600 text-white text-xs font-semibold "
                    "rounded-lg hover:bg-rose-700"
                ),
            ),
            Input(
                type="hidden",
                name="ids",
                value="",
                id="zefe-customer-bulk-ids-1",
                cls="zefe-customer-bulk-ids",
            ),
            Input(
                type="hidden",
                name="ids",
                value="",
                id="zefe-customer-bulk-ids-2",
                cls="zefe-customer-bulk-ids",
            ),
            cls="flex items-center gap-2",
        ),
        id="zefe-customer-bulk-bar",
        style="display:none;",
        cls=(
            "mb-4 px-4 py-3 bg-slate-50 border border-slate-200 "
            "rounded-xl items-center justify-between"
        ),
    )


def _pagination(page: int, total_pages: int, q: str, active_param: str) -> Div:
    base = (
        f"/customers?q={urllib.parse.quote(q or '')}"
        f"&active={urllib.parse.quote(active_param or 'true')}"
    )
    btn_cls = (
        "inline-flex items-center px-4 py-2 border border-slate-300 text-sm "
        "font-medium rounded-lg text-slate-700 bg-white hover:bg-slate-50 "
        "disabled:opacity-50 disabled:cursor-not-allowed"
    )

    prev_attrs = {"cls": btn_cls, "type": "button"}
    if page <= 1:
        prev_attrs["disabled"] = "true"
    else:
        prev_attrs["hx-get"] = f"{base}&page={page - 1}"
        prev_attrs["hx-target"] = LIST_TARGET
        prev_attrs["hx-swap"] = "outerHTML"

    next_attrs = {"cls": btn_cls, "type": "button"}
    if page >= total_pages:
        next_attrs["disabled"] = "true"
    else:
        next_attrs["hx-get"] = f"{base}&page={page + 1}"
        next_attrs["hx-target"] = LIST_TARGET
        next_attrs["hx-swap"] = "outerHTML"

    return Div(
        Button(
            icon("arrow-left", cls="h-4 w-4 mr-2"),
            Span("Previous"),
            **prev_attrs,
        ),
        Span(
            f"Page {page} of {total_pages}",
            cls="text-sm text-slate-600 font-medium px-4",
        ),
        Button(
            Span("Next"), icon("arrow-right", cls="h-4 w-4 ml-2"), **next_attrs
        ),
        cls=(
            "bg-white px-4 py-3 flex items-center justify-end gap-2 "
            "border border-slate-200 rounded-xl mt-4"
        ),
    )


def _list_container(
    customers: list[dict],
    page: int,
    total_pages: int,
    q: str,
    active_param: str,
    banner=None,
) -> Div:
    is_active = active_param != "false"
    return Div(
        banner or "",
        _bulk_bar(is_active),
        _customer_table(customers, is_active),
        _pagination(page, total_pages, q, active_param),
        Script(_CUSTOMERS_JS),
        id="customer-list-container",
    )


def _filters(q: str, active_param: str) -> Form:
    status_opts = [
        Option("Active", value="true", selected=(active_param != "false")),
        Option("Inactive", value="false", selected=(active_param == "false")),
    ]
    common = {
        "hx_get": "/customers",
        "hx_target": LIST_TARGET,
        "hx_swap": "outerHTML",
        "hx_include": FILTERS,
    }
    return Form(
        Div(
            Div(
                icon(
                    "search",
                    cls=(
                        "h-4 w-4 text-slate-400 absolute left-3 top-1/2 "
                        "-translate-y-1/2 pointer-events-none"
                    ),
                ),
                Input(
                    name="q",
                    type="search",
                    placeholder="Search by name, TIN, or email",
                    value=q,
                    autocomplete="off",
                    hx_trigger="keyup changed delay:300ms, search",
                    **common,
                    cls=_INPUT_CLS.replace("px-3", "pl-9 pr-3"),
                ),
                cls="relative flex-1 min-w-0",
            ),
            Div(
                Select(
                    *status_opts,
                    name="active",
                    hx_trigger="change",
                    **common,
                    cls=_SELECT_CLS,
                ),
                icon("chevron-down", cls=_CHEVRON_CLS),
                cls="relative w-36 shrink-0",
            ),
            Hidden(name="page", value="1"),
            cls="flex items-center gap-2 flex-wrap",
        ),
        id="customer-filters",
        method="get",
        action="/customers",
        cls="mb-4",
    )


# --------------------------------------------------------------------------
# Payload parsing / loading
# --------------------------------------------------------------------------


def _parse_customer_form(form) -> tuple[dict, str]:
    payload = {
        name: (form.get(name) or "").strip()
        for name, _, _, _, _ in CUSTOMER_FIELDS
    }
    payload["country"] = (form.get("country") or "").strip()
    payload["state"] = (form.get("state") or "").strip()

    missing = [
        label
        for name, label, _, _, required in CUSTOMER_FIELDS
        if required and not payload.get(name)
    ]
    missing += [
        label
        for name, label in CUSTOMER_REQUIRED_ADDRESS
        if not payload.get(name)
    ]
    if missing:
        return payload, f"Please fill in: {', '.join(missing)}."

    if not payload.get("lga"):
        payload["lga"] = None
    return payload, ""


async def _load_lookups(jwt: str, sid: str) -> tuple[list, list]:
    countries: list = []
    states: list = []
    try:
        raw = await api_client.get_countries(jwt, session_id=sid)
        if isinstance(raw, list):
            countries = raw
    except Exception:
        logger.exception("customers: get_countries failed")
    try:
        raw = await api_client.get_state_codes(jwt, session_id=sid)
        if isinstance(raw, list):
            states = raw
    except Exception:
        logger.exception("customers: get_state_codes failed")
    return countries, states


async def _load_page(
    jwt: str, sid: str, q: str, active_param: str, page: int
) -> tuple[list[dict], int, int, str]:
    offset = (max(page, 1) - 1) * PAGE_SIZE
    try:
        res = await api_client.list_customers(
            jwt,
            session_id=sid,
            search=q or None,
            active=(active_param != "false"),
            offset=offset,
            limit=PAGE_SIZE,
        )
        customers = res.get("items", []) or []
        total = int(res.get("total", 0) or 0)
        total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        return customers, total, total_pages, ""
    except api_client.APIError as e:
        logger.exception("list_customers failed")
        return [], 0, 1, extract_api_error_detail(e)
    except Exception:
        logger.exception("list_customers transport error")
        return [], 0, 1, "Backend service unavailable."


def _filter_state(getter) -> tuple[str, str, int]:
    q = (getter.get("q") or "").strip()
    active = "false" if (getter.get("active") or "") == "false" else "true"
    try:
        page = max(1, int(getter.get("page") or 1))
    except (TypeError, ValueError):
        page = 1
    return q, active, page


def _parse_ids(raw: str, limit: int = 200) -> list[int]:
    ids: list[int] = []
    for chunk in (raw or "").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            value = int(chunk)
        except ValueError:
            continue
        if value not in ids:
            ids.append(value)
    return ids[:limit]


def register_routes(rt) -> None:
    async def _refreshed_list(req: Request, form, banner=None):
        """Pagination-aware list refresh plus an out-of-band modal clear."""
        jwt = current_jwt(req)
        sid = get_session_id(req)
        q, active, page = _filter_state(form)
        customers, _total, total_pages, load_error = await _load_page(
            jwt, sid, q, active, page
        )
        if not customers and page > 1:
            page -= 1
            customers, _total, total_pages, load_error = await _load_page(
                jwt, sid, q, active, page
            )
        if load_error and banner is None:
            banner = alert("error", load_error)
        return (
            _list_container(customers, page, total_pages, q, active, banner),
            Div(id="customer-modal-area", hx_swap_oob="innerHTML"),
        )

    # ----------------------------------------------------------------- list
    @rt("/customers", methods=["GET"])
    async def list_customers_page(
        req: Request,
        q: str = "",
        active: str = "true",
        page: int = 1,
        error: str = "",
        success: str = "",
    ):
        redirect = require_session(req)
        if redirect:
            return redirect
        jwt = current_jwt(req)
        sid = get_session_id(req)
        page = max(1, page)
        active = "false" if active == "false" else "true"

        customers, total, total_pages, load_error = await _load_page(
            jwt, sid, q, active, page
        )
        if page > total_pages:
            page = total_pages
            customers, total, total_pages, load_error = await _load_page(
                jwt, sid, q, active, page
            )

        if req.headers.get("HX-Request") == "true":
            banner = alert("error", load_error) if load_error else None
            return _list_container(
                customers, page, total_pages, q, active, banner
            )

        header = Div(
            Div(
                H2("Customers", cls="text-2xl font-bold text-slate-900"),
                P(
                    f"{total} {'active' if active == 'true' else 'inactive'} "
                    "customer(s) in your workspace",
                    cls="text-sm text-slate-500 mt-1",
                ),
            ),
            Div(
                Button(
                    icon("upload", cls="h-4 w-4"),
                    Span("Import"),
                    type="button",
                    hx_get="/customers/import-overlay",
                    hx_target=MODAL_AREA,
                    hx_swap="innerHTML",
                    cls=(
                        "inline-flex items-center gap-2 px-4 py-2 bg-white "
                        "border border-slate-300 text-slate-700 text-sm "
                        "font-medium rounded-lg hover:bg-slate-50"
                    ),
                ),
                Button(
                    icon("plus", cls="h-4 w-4"),
                    Span("Add customer"),
                    type="button",
                    hx_get="/customers/new-overlay",
                    hx_target=MODAL_AREA,
                    hx_swap="innerHTML",
                    cls=_INDIGO_BTN,
                ),
                cls="flex items-center gap-2",
            ),
            cls="flex items-start justify-between gap-4 mb-6",
        )

        banners = []
        if error:
            banners.append(alert("error", error))
        if success:
            banners.append(alert("success", success))
        if load_error:
            banners.append(alert("error", load_error))

        return app_shell(
            "Customers",
            header,
            *banners,
            guidance_panel(
                "Customers are reusable on every invoice. Deactivate one to "
                "hide it from the active directory and from new invoices "
                "while keeping past invoices intact.",
                cls="mb-5",
            ),
            _filters(q, active),
            _list_container(customers, page, total_pages, q, active),
            Div(id="customer-modal-area"),
            active_nav="customers",
            username=current_username(req),
            business_id=current_business_id(req),
        )

    # -------------------------------------------------------------- overlays
    @rt("/customers/clear-overlay", methods=["GET"])
    def clear_overlay(req: Request):
        return HTMLResponse("")

    @rt("/customers/new", methods=["GET"])
    def new_customer_redirect(req: Request):
        redirect = require_session(req)
        if redirect:
            return redirect
        return RedirectResponse("/customers", status_code=303)

    @rt("/customers/new-overlay", methods=["GET"])
    async def new_overlay(req: Request):
        redirect = require_session(req)
        if redirect:
            return redirect
        countries, states = await _load_lookups(
            current_jwt(req), get_session_id(req)
        )
        return _customer_form_modal(
            {"country": "NG"}, countries=countries, ng_states=states
        )

    @rt("/customers/{cid}/edit-overlay", methods=["GET"])
    async def edit_overlay(req: Request, cid: int):
        redirect = require_session(req)
        if redirect:
            return redirect
        jwt = current_jwt(req)
        sid = get_session_id(req)
        try:
            customer = await api_client.get_customer(jwt, cid, session_id=sid)
        except api_client.APIError as e:
            logger.exception("get_customer failed")
            return _notice_modal(
                "Customer unavailable",
                "Could not load this customer.",
                extract_api_error_detail(e),
            )
        except Exception:
            logger.exception("get_customer transport error")
            return HTMLResponse("")
        countries, states = await _load_lookups(jwt, sid)
        return _customer_form_modal(
            customer, countries=countries, ng_states=states
        )

    # ------------------------------------------------------------------ save
    @rt("/customers/save", methods=["POST"])
    async def save_customer(req: Request):
        redirect = require_session(req)
        if redirect:
            return redirect
        form = await req.form()
        jwt = current_jwt(req)
        sid = get_session_id(req)
        raw_id = (form.get("customer_id") or "").strip()
        payload, err = _parse_customer_form(form)
        display = {**payload, "id": raw_id}

        async def _form_with_error(message: str):
            countries, states = await _load_lookups(jwt, sid)
            return _customer_form_modal(
                display,
                error=message,
                countries=countries,
                ng_states=states,
            )

        if err:
            return await _form_with_error(err)

        try:
            if raw_id:
                await api_client.update_customer(
                    jwt, int(raw_id), payload, session_id=sid
                )
                msg = f"Customer '{payload['party_name']}' updated."
            else:
                await api_client.create_customer(jwt, payload, session_id=sid)
                msg = f"Customer '{payload['party_name']}' created."
        except api_client.APIError as e:
            logger.exception("save_customer failed")
            return await _form_with_error(extract_api_error_detail(e))
        except (TypeError, ValueError):
            logger.exception("save_customer bad id")
            return await _form_with_error("Invalid customer reference.")
        except Exception:
            logger.exception("save_customer transport error")
            return await _form_with_error(
                "Backend service unavailable. Please try again."
            )

        if req.headers.get("HX-Request") != "true":
            return RedirectResponse(
                "/customers?success=" + urllib.parse.quote_plus(msg),
                status_code=303,
            )
        return await _refreshed_list(req, form, alert("success", msg))

    # ------------------------------------------------- deactivate / restore
    @rt("/customers/{cid}/deactivate-overlay", methods=["GET"])
    async def deactivate_overlay(req: Request, cid: int):
        redirect = require_session(req)
        if redirect:
            return redirect
        name = f"#{cid}"
        try:
            customer = await api_client.get_customer(
                current_jwt(req), cid, session_id=get_session_id(req)
            )
            name = customer.get("party_name") or name
        except Exception:
            logger.exception("deactivate_overlay get_customer failed")

        return _modal_card(
            Div(
                Div(
                    icon("alert-triangle", cls="h-6 w-6 text-amber-600"),
                    cls=(
                        "h-12 w-12 rounded-full bg-amber-100 flex "
                        "items-center justify-center mb-4 mx-auto"
                    ),
                ),
                H3(
                    "Deactivate this customer?",
                    cls="text-lg font-bold text-slate-950 text-center",
                ),
                P(
                    f'"{name}" will be hidden from the active directory and '
                    "from new invoices. Existing invoices keep their stored "
                    "customer details, and you can restore this customer any "
                    "time from the Inactive filter.",
                    cls=(
                        "text-sm text-slate-600 text-center mt-2 "
                        "leading-relaxed"
                    ),
                ),
                cls="p-6",
            ),
            _modal_footer(
                _cancel_button(),
                Form(
                    Button(
                        icon("x", cls="h-4 w-4"),
                        Span("Deactivate customer"),
                        type="submit",
                        cls=(
                            "inline-flex items-center gap-2 px-4 py-2 "
                            "bg-amber-600 text-white text-sm font-medium "
                            "rounded-lg hover:bg-amber-700"
                        ),
                    ),
                    hx_post=f"/customers/{cid}/deactivate",
                    hx_target=LIST_TARGET,
                    hx_swap="outerHTML",
                    hx_include=FILTERS,
                    method="post",
                    action=f"/customers/{cid}/deactivate",
                    cls="inline",
                ),
            ),
            max_w="max-w-md",
        )

    @rt("/customers/{cid}/deactivate", methods=["POST"])
    async def deactivate_customer(req: Request, cid: int):
        redirect = require_session(req)
        if redirect:
            return redirect
        form = await req.form()
        try:
            await api_client.delete_customer(
                current_jwt(req), cid, session_id=get_session_id(req)
            )
            banner = alert(
                "success",
                "Customer deactivated. Past invoices are unchanged and you "
                "can restore it from the Inactive filter.",
            )
        except api_client.APIError as e:
            logger.exception("deactivate_customer failed")
            banner = alert("error", extract_api_error_detail(e))
        except Exception:
            logger.exception("deactivate_customer transport error")
            banner = alert("error", "Backend service unavailable.")
        return await _refreshed_list(req, form, banner)

    @rt("/customers/{cid}/restore", methods=["POST"])
    async def restore_customer(req: Request, cid: int):
        redirect = require_session(req)
        if redirect:
            return redirect
        form = await req.form()
        try:
            await api_client.restore_customer(
                current_jwt(req), cid, session_id=get_session_id(req)
            )
            banner = alert(
                "success", "Customer restored to your active directory."
            )
        except api_client.APIError as e:
            logger.exception("restore_customer failed")
            banner = alert("error", extract_api_error_detail(e))
        except Exception:
            logger.exception("restore_customer transport error")
            banner = alert("error", "Backend service unavailable.")
        return await _refreshed_list(req, form, banner)

    # ---------------------------------------------------------------- delete
    @rt("/customers/{cid}/delete-overlay", methods=["GET"])
    async def delete_overlay(req: Request, cid: int):
        redirect = require_session(req)
        if redirect:
            return redirect
        name = f"#{cid}"
        try:
            customer = await api_client.get_customer(
                current_jwt(req), cid, session_id=get_session_id(req)
            )
            name = customer.get("party_name") or name
        except Exception:
            logger.exception("delete_overlay get_customer failed")

        return _modal_card(
            Div(
                Div(
                    icon("alert-triangle", cls="h-6 w-6 text-rose-600"),
                    cls=(
                        "h-12 w-12 rounded-full bg-rose-100 flex items-center "
                        "justify-center mb-4 mx-auto"
                    ),
                ),
                H3(
                    "Delete this customer permanently?",
                    cls="text-lg font-bold text-slate-950 text-center",
                ),
                P(
                    f'"{name}" will be removed from your directory for good. '
                    "Past invoices keep their stored customer details, but "
                    "Deactivate is the safer choice: it stops the customer "
                    "appearing on new invoices while keeping the record.",
                    cls=(
                        "text-sm text-slate-600 text-center mt-2 "
                        "leading-relaxed"
                    ),
                ),
                Div(
                    Button(
                        icon("x", cls="h-3.5 w-3.5"),
                        Span("Deactivate instead (recommended)"),
                        type="button",
                        hx_get=f"/customers/{cid}/deactivate-overlay",
                        hx_target=MODAL_AREA,
                        hx_swap="innerHTML",
                        cls=(
                            "inline-flex items-center gap-1.5 px-3 py-1.5 "
                            "bg-white border border-amber-300 text-amber-700 "
                            "text-xs font-semibold rounded-lg "
                            "hover:bg-amber-50"
                        ),
                    ),
                    cls="flex justify-center mt-4",
                ),
                Label(
                    Input(
                        type="checkbox",
                        name="confirm_hard",
                        value="1",
                        required=True,
                        form=f"customer-hard-delete-{cid}",
                        cls=(
                            "h-4 w-4 rounded border-slate-300 text-rose-600 "
                            "focus:ring-rose-500 cursor-pointer shrink-0 "
                            "mt-0.5"
                        ),
                    ),
                    Span(
                        "I understand this permanently removes the customer "
                        "and cannot be undone.",
                        cls="text-xs text-slate-600 leading-relaxed",
                    ),
                    cls=(
                        "flex items-start gap-2 mt-5 p-3 bg-rose-50 border "
                        "border-rose-200 rounded-xl cursor-pointer"
                    ),
                ),
                cls="p-6",
            ),
            _modal_footer(
                _cancel_button(),
                Form(
                    Button(
                        Span("Delete permanently"),
                        type="submit",
                        cls=_DANGER_BTN,
                    ),
                    id=f"customer-hard-delete-{cid}",
                    hx_post=f"/customers/{cid}/delete",
                    hx_target=LIST_TARGET,
                    hx_swap="outerHTML",
                    hx_include=f"{FILTERS}, [name='confirm_hard']",
                    method="post",
                    action=f"/customers/{cid}/delete",
                    cls="inline",
                ),
            ),
            max_w="max-w-md",
        )

    @rt("/customers/{cid}/delete", methods=["POST"])
    async def delete_customer_route(req: Request, cid: int):
        redirect = require_session(req)
        if redirect:
            return redirect
        form = await req.form()
        if not (form.get("confirm_hard") or "").strip():
            return await _refreshed_list(
                req,
                form,
                alert(
                    "error",
                    "Permanent delete was not confirmed. Tick the "
                    "acknowledgement, or deactivate the customer instead.",
                ),
            )
        try:
            await api_client.delete_customer(
                current_jwt(req),
                cid,
                session_id=get_session_id(req),
                hard=True,
            )
            banner = alert("success", "Customer deleted permanently.")
        except api_client.APIError as e:
            logger.exception("delete_customer failed")
            banner = alert("error", extract_api_error_detail(e))
        except Exception:
            logger.exception("delete_customer transport error")
            banner = alert("error", "Backend service unavailable.")
        return await _refreshed_list(req, form, banner)

    # ------------------------------------------------------------ bulk flows
    @rt("/customers/bulk-confirm", methods=["GET"])
    async def bulk_confirm(
        req: Request,
        action: str = "deactivate",
        ids: str = "",
        q: str = "",
        active: str = "true",
        page: int = 1,
    ):
        redirect = require_session(req)
        if redirect:
            return redirect
        action = (
            action
            if action in ("deactivate", "restore", "delete")
            else "deactivate"
        )
        id_list = _parse_ids(ids)
        if not id_list:
            return _notice_modal(
                "Nothing selected",
                "Tick at least one customer to continue.",
                "Select one or more rows using the checkboxes, then try again.",
            )

        jwt = current_jwt(req)
        sid = get_session_id(req)
        names: list[str] = []
        for cid in id_list[:50]:
            try:
                c = await api_client.get_customer(jwt, cid, session_id=sid)
                names.append(c.get("party_name") or f"#{cid}")
            except Exception:
                logger.exception("bulk_confirm: get_customer failed")
                names.append(f"#{cid}")

        chips = [
            Div(
                icon("users", cls="h-3 w-3 text-slate-500 shrink-0"),
                Span(n, cls="text-sm text-slate-700 truncate"),
                cls=(
                    "flex items-center gap-2 px-3 py-1.5 bg-white border "
                    "border-slate-200 rounded-lg min-w-0"
                ),
            )
            for n in names
        ]

        count = len(id_list)
        noun = "customer" if count == 1 else "customers"
        copy = {
            "deactivate": (
                f"Deactivate {count} {noun}?",
                f"{count} {noun} will be hidden from the active directory "
                "and from new invoices. Past invoices are unchanged, and you "
                "can restore them any time.",
                f"Deactivate {count} {noun}",
                (
                    "px-4 py-2 bg-amber-600 text-white text-sm font-medium "
                    "rounded-lg hover:bg-amber-700"
                ),
            ),
            "restore": (
                f"Restore {count} {noun}?",
                f"{count} {noun} will return to your active directory and "
                "become selectable on new invoices again.",
                f"Restore {count} {noun}",
                (
                    "px-4 py-2 bg-emerald-600 text-white text-sm font-medium "
                    "rounded-lg hover:bg-emerald-700"
                ),
            ),
            "delete": (
                f"Delete {count} {noun} permanently?",
                f"{count} {noun} will be removed from your directory for "
                "good. This cannot be undone. Use Deactivate if you may need "
                "them later.",
                f"Delete {count} {noun}",
                _DANGER_BTN,
            ),
        }[action]

        title, message, btn_label, btn_cls = copy

        return _modal_card(
            Div(
                Div(
                    icon("alert-triangle", cls="h-6 w-6 text-slate-700"),
                    cls=(
                        "h-12 w-12 rounded-full bg-slate-100 flex "
                        "items-center justify-center mb-4 mx-auto"
                    ),
                ),
                H3(title, cls="text-lg font-bold text-slate-950 text-center"),
                P(
                    message,
                    cls=(
                        "text-sm text-slate-600 text-center mt-2 "
                        "leading-relaxed"
                    ),
                ),
                Div(
                    *chips,
                    cls=(
                        "flex flex-wrap gap-2 mt-5 p-4 bg-slate-50 border "
                        "border-slate-200 rounded-xl max-h-60 overflow-auto"
                    ),
                ),
                cls="p-6",
            ),
            _modal_footer(
                _cancel_button(),
                Form(
                    Hidden(name="ids", value=",".join(str(x) for x in id_list)),
                    Hidden(name="action", value=action),
                    Hidden(name="q", value=q),
                    Hidden(name="active", value=active),
                    Hidden(name="page", value=str(page)),
                    Button(Span(btn_label), type="submit", cls=btn_cls),
                    hx_post="/customers/bulk",
                    hx_target=LIST_TARGET,
                    hx_swap="outerHTML",
                    method="post",
                    action="/customers/bulk",
                    cls="inline",
                ),
            ),
            max_w="max-w-lg",
        )

    @rt("/customers/bulk", methods=["POST"])
    async def bulk_apply(req: Request):
        redirect = require_session(req)
        if redirect:
            return redirect
        form = await req.form()
        action = (form.get("action") or "deactivate").strip()
        ids = _parse_ids(form.get("ids") or "")
        jwt = current_jwt(req)
        sid = get_session_id(req)

        if not ids:
            banner = alert("error", "No valid customers were selected.")
        else:
            try:
                if action == "restore":
                    res = await api_client.bulk_activate_customers(
                        jwt, ids, session_id=sid
                    )
                    n = int(res.get("activated", len(ids)) or 0)
                    banner = alert("success", f"Restored {n} customer(s).")
                elif action == "delete":
                    res = await api_client.bulk_delete_customers(
                        jwt, ids, session_id=sid, hard=True
                    )
                    n = int(res.get("deleted", len(ids)) or 0)
                    banner = alert("success", f"Deleted {n} customer(s).")
                else:
                    res = await api_client.bulk_delete_customers(
                        jwt, ids, session_id=sid, hard=False
                    )
                    n = int(res.get("deleted", len(ids)) or 0)
                    banner = alert("success", f"Deactivated {n} customer(s).")
            except api_client.APIError as e:
                logger.exception("customers bulk_apply failed")
                banner = alert("error", extract_api_error_detail(e))
            except Exception:
                logger.exception("customers bulk_apply transport error")
                banner = alert("error", "Backend service unavailable.")

        return await _refreshed_list(req, form, banner)

    # ---------------------------------------------------------------- import
    @rt("/customers/import-overlay", methods=["GET"])
    def import_overlay(req: Request, error: str = ""):
        redirect = require_session(req)
        if redirect:
            return redirect
        body = [
            alert("error", error, cls="mb-4") if error else "",
            guidance_panel(
                "Upload a CSV (or XLSX) with these columns: " + IMPORT_COLUMNS,
                title="Expected columns",
                cls="mb-4",
            ),
            Div(
                Label(
                    "File",
                    Span(" *", cls="text-rose-500 font-bold"),
                    fr="customers_import_file",
                    cls="block text-sm font-medium text-slate-700 mb-1.5",
                ),
                Input(
                    id="customers_import_file",
                    name="file",
                    type="file",
                    accept=".csv,.xlsx,.xlsm",
                    required=True,
                    cls=(
                        "w-full px-3 py-2 bg-white text-slate-900 border "
                        "border-slate-300 rounded-lg text-sm "
                        "file:mr-3 file:py-1.5 file:px-3 file:rounded-md "
                        "file:border-0 file:text-sm file:font-medium "
                        "file:bg-slate-100 file:text-slate-700"
                    ),
                ),
                guidance_text(
                    "Rows are matched on TIN: a known TIN is updated and "
                    "reactivated, a new TIN is created. Invalid rows are "
                    "skipped with a reason and never abort the import."
                ),
                cls="mb-2",
            ),
        ]
        return _modal_card(
            Form(
                _modal_header(
                    "Import customers",
                    "Bulk create or update directory entries from a "
                    "spreadsheet.",
                ),
                Div(*body, cls="px-6 py-5 max-h-[70vh] overflow-auto"),
                _modal_footer(
                    _cancel_button(),
                    primary_button("Import file", type="submit"),
                ),
                method="post",
                action="/customers/import",
                enctype="multipart/form-data",
                cls="flex flex-col",
            )
        )

    @rt("/customers/import", methods=["POST"])
    async def import_customers_route(req: Request):
        redirect = require_session(req)
        if redirect:
            return redirect
        form = await req.form()
        upload = form.get("file")
        if upload is None or not getattr(upload, "filename", ""):
            return RedirectResponse(
                "/customers?error="
                + urllib.parse.quote_plus("Choose a file to import."),
                status_code=303,
            )
        try:
            content = await upload.read()
        except Exception:
            logger.exception("import_customers read failed")
            return RedirectResponse(
                "/customers?error="
                + urllib.parse.quote_plus("Could not read the uploaded file."),
                status_code=303,
            )

        try:
            res = await api_client.import_customers(
                current_jwt(req),
                upload.filename,
                content,
                session_id=get_session_id(req),
            )
        except api_client.APIError as e:
            logger.exception("import_customers failed")
            return RedirectResponse(
                "/customers?error="
                + urllib.parse.quote_plus(extract_api_error_detail(e)),
                status_code=303,
            )
        except Exception:
            logger.exception("import_customers transport error")
            return RedirectResponse(
                "/customers?error="
                + urllib.parse.quote_plus("Backend service unavailable."),
                status_code=303,
            )

        created = int(res.get("created", 0) or 0)
        updated = int(res.get("updated", 0) or 0)
        skipped = int(res.get("skipped", 0) or 0)
        errors = res.get("errors") or []
        msg = (
            f"Import complete: {created} created, {updated} updated, "
            f"{skipped} skipped."
        )
        query = "/customers?success=" + urllib.parse.quote_plus(msg)
        if errors:
            detail = "; ".join(str(e) for e in errors[:3])
            if len(errors) > 3:
                detail += f" (+{len(errors) - 3} more)"
            query += "&error=" + urllib.parse.quote_plus(
                f"Skipped rows: {detail}"
            )
        return RedirectResponse(query, status_code=303)
