"""Items catalog pages for the standalone FastHTML frontend.

An item is a reusable invoice line minus the per-invoice fields. The catalog
lets a business save the stable part of a line once (name, SKU, description,
HS/ISIC classification + category, unit price, official unit code, base
quantity) so the invoice wizard only has to ask for quantity.

UI intentionally mirrors the Customers page: white/slate surfaces, thin 1px
borders, rounded-lg/xl, indigo accents, flat tables and modals.
"""

from __future__ import annotations

import asyncio
import json
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
from services.unit_codes import (
    DEFAULT_UNIT_CODE,
    coerce_unit_code,
    unit_code_label,
    unit_code_options,
)
from ui.components import (
    alert,
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
MODAL_AREA = "#item-modal-area"
LIST_TARGET = "#item-list-container"

_CLEAR_OVERLAY = "/items/clear-overlay"

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


# --------------------------------------------------------------------------
# Small shared field helpers (scoped to this page)
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
        "id": f"item_{name}",
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
            fr=f"item_{name}",
            cls="block text-sm font-medium text-slate-700 mb-1.5",
        ),
        Input(**attrs, cls=_INPUT_CLS),
    ]
    if helper:
        children.append(guidance_text(helper))
    return Div(*children, cls="mb-4")


def _unit_select(value: str = DEFAULT_UNIT_CODE) -> Div:
    current = coerce_unit_code(value)
    opts = []
    for code, label in unit_code_options():
        opts.append(
            Option(f"{code} — {label}", value=code, selected=(code == current))
        )
    return Div(
        Label(
            "Price unit",
            Span(" *", cls="text-rose-500 font-bold"),
            fr="item_price_unit",
            cls="block text-sm font-medium text-slate-700 mb-1.5",
        ),
        Div(
            Select(
                *opts,
                id="item_price_unit",
                name="price_unit",
                required=True,
                cls=_SELECT_CLS,
            ),
            icon("chevron-down", cls=_CHEVRON_CLS),
            cls="relative",
        ),
        guidance_text(
            "Official 2-3 character UN/ECE unit code sent to FIRS "
            "(EA = each). Free text is not accepted."
        ),
        cls="mb-4",
    )


def _kind_of(item: dict) -> str:
    if (item or {}).get("hsn_code"):
        return "product"
    if (item or {}).get("isic_code"):
        return "service"
    return ""


def _kind_badge(kind: str) -> Span:
    if kind == "product":
        return Span(
            "Product",
            cls=(
                "inline-flex items-center px-2 py-0.5 rounded-full "
                "text-[10px] font-semibold uppercase tracking-wider "
                "bg-indigo-100 text-indigo-700 w-fit"
            ),
        )
    if kind == "service":
        return Span(
            "Service",
            cls=(
                "inline-flex items-center px-2 py-0.5 rounded-full "
                "text-[10px] font-semibold uppercase tracking-wider "
                "bg-purple-100 text-purple-700 w-fit"
            ),
        )
    return Span(
        "Unclassified",
        cls=(
            "inline-flex items-center px-2 py-0.5 rounded-full text-[10px] "
            "font-semibold uppercase tracking-wider bg-slate-100 "
            "text-slate-600 w-fit"
        ),
    )


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


# --------------------------------------------------------------------------
# Classification block (HS / ISIC lookup)
# --------------------------------------------------------------------------


def _classification_block(item: dict) -> Div:
    hsn = (item or {}).get("hsn_code") or ""
    hsn_cat = (item or {}).get("hsn_category") or ""
    isic = (item or {}).get("isic_code") or ""
    isic_cat = (item or {}).get("isic_category") or ""

    if hsn:
        badge = Div(
            icon("check-circle", cls="h-4 w-4 text-emerald-600 shrink-0"),
            _kind_badge("product"),
            Span(
                f"HS {hsn}",
                cls=(
                    "inline-flex items-center px-2 py-0.5 rounded-md "
                    "text-[11px] font-mono font-semibold bg-white "
                    "text-emerald-800 border border-emerald-200 shrink-0"
                ),
            ),
            Span(
                hsn_cat,
                cls="text-xs text-emerald-700 truncate min-w-0",
            ),
            cls=(
                "flex items-center gap-2 p-2.5 bg-emerald-50 rounded-lg "
                "border border-emerald-200"
            ),
        )
    elif isic:
        badge = Div(
            icon("check-circle", cls="h-4 w-4 text-emerald-600 shrink-0"),
            _kind_badge("service"),
            Span(
                f"ISIC {isic}",
                cls=(
                    "inline-flex items-center px-2 py-0.5 rounded-md "
                    "text-[11px] font-mono font-semibold bg-white "
                    "text-emerald-800 border border-emerald-200 shrink-0"
                ),
            ),
            Span(
                isic_cat,
                cls="text-xs text-emerald-700 truncate min-w-0",
            ),
            cls=(
                "flex items-center gap-2 p-2.5 bg-emerald-50 rounded-lg "
                "border border-emerald-200"
            ),
        )
    else:
        badge = Div(
            icon("alert-circle", cls="h-4 w-4 text-amber-600 shrink-0"),
            Span(
                "No classification attached yet — search below and pick a "
                "product (HS code) or a service (ISIC code).",
                cls="text-xs text-amber-700",
            ),
            cls=(
                "flex items-center gap-2 p-2.5 bg-amber-50 rounded-lg "
                "border border-amber-200"
            ),
        )

    return Div(
        Hidden(name="hsn_code", value=hsn),
        Hidden(name="hsn_category", value=hsn_cat),
        Hidden(name="isic_code", value=isic),
        Hidden(name="isic_category", value=isic_cat),
        badge,
        id="item-classification",
        cls="mb-4",
    )


def _lookup_hit_row(hit: dict) -> Button:
    kind = hit.get("kind", "product")
    code = hit.get("code", "")
    label = hit.get("label", "")
    category = hit.get("category", "") or label
    prefix = "HS" if kind == "product" else "ISIC"
    return Button(
        Div(
            Div(
                _kind_badge(kind),
                P(
                    label,
                    cls=(
                        "text-sm text-slate-900 text-left whitespace-normal "
                        "break-words"
                    ),
                ),
                cls="flex items-start gap-2 min-w-0",
            ),
            P(
                f"{prefix} {code}"
                + (f" · {category}" if category and category != label else ""),
                cls=(
                    "text-xs text-slate-500 font-mono text-left mt-1 "
                    "whitespace-normal break-words"
                ),
            ),
            cls="min-w-0 w-full",
        ),
        type="button",
        hx_get="/items/classification/apply",
        hx_vals=json.dumps(
            {
                "kind": kind,
                "code": code,
                "label": label,
                "category": category,
            }
        ),
        hx_include="[name='name'],[name='description']",
        hx_target="#item-classification",
        hx_swap="outerHTML",
        cls=(
            "w-full px-3 py-3 hover:bg-indigo-50 border-b border-slate-100 "
            "last:border-b-0 text-left transition-colors cursor-pointer block"
        ),
    )


def _lookup_results(hits: list[dict], query: str) -> Div:
    if not query:
        return Div(id="item-lookup-results")
    if not hits:
        return Div(
            P(
                f"No products or services matched “{query}”. Try a broader "
                "keyword, or search the classification code directly "
                "(products use 1006.10 style HS codes, services use 4-digit "
                "ISIC codes).",
                cls="text-xs text-slate-500 px-3 py-3 leading-relaxed",
            ),
            id="item-lookup-results",
            cls="mt-2 rounded-lg border border-slate-200 bg-slate-50/60",
        )
    rows = [_lookup_hit_row(h) for h in hits[:20]]
    return Div(
        *rows,
        id="item-lookup-results",
        cls=(
            "mt-2 max-h-64 overflow-auto rounded-lg border border-slate-200 "
            "bg-white shadow-xs animate-fade-in-up"
        ),
    )


# --------------------------------------------------------------------------
# Item form
# --------------------------------------------------------------------------


def _item_form_modal(item: dict | None = None, error: str = "") -> Div:
    item = item or {}
    item_id = str(item.get("id", "") or "")
    is_edit = bool(item_id)

    body_children = []
    if error:
        body_children.append(alert("error", error, cls="mb-4"))

    body_children.append(
        Div(
            Label(
                "Classification lookup",
                cls="block text-sm font-medium text-slate-700 mb-1.5",
            ),
            guidance_panel(
                "Every item must be either a product (HS code + category) or "
                "a service (ISIC code + category) — never both. Pick one from "
                "the FIRS lookup so invoices validate first time.",
                cls="mb-3",
            ),
            Div(
                icon(
                    "search",
                    cls=(
                        "h-4 w-4 text-slate-400 absolute left-3 top-1/2 "
                        "-translate-y-1/2 pointer-events-none"
                    ),
                ),
                Input(
                    type="search",
                    name="lookup_q",
                    id="item-lookup-q",
                    placeholder=(
                        "Search products & services e.g. 'rice', "
                        "'consulting', '1006.10'…"
                    ),
                    autocomplete="off",
                    hx_get="/items/lookup",
                    hx_trigger="keyup changed delay:400ms, search",
                    hx_target="#item-lookup-results",
                    hx_swap="outerHTML",
                    hx_indicator="#item-lookup-spinner",
                    cls=_INPUT_CLS.replace("px-3", "pl-9 pr-9"),
                ),
                Div(
                    icon("loader", cls="h-4 w-4 text-indigo-500 animate-spin"),
                    id="item-lookup-spinner",
                    cls=(
                        "htmx-indicator absolute right-3 top-1/2 "
                        "-translate-y-1/2 pointer-events-none"
                    ),
                ),
                cls="relative",
            ),
            Div(id="item-lookup-results"),
            cls=("mb-5 p-4 bg-slate-50 rounded-lg border border-slate-200"),
        )
    )

    body_children.append(_classification_block(item))

    body_children.append(
        Div(
            _field(
                name="name",
                label="Item name",
                value=item.get("name", "") or "",
                placeholder="Premium rice (50kg bag)",
                required=True,
                helper="Shown on the invoice line.",
            ),
            _field(
                name="sku",
                label="SKU",
                value=item.get("sku", "") or "",
                placeholder="RICE-001",
                helper="Optional, but must be unique in your workspace.",
            ),
            cls="grid grid-cols-1 md:grid-cols-2 gap-x-4",
        )
    )
    body_children.append(
        _field(
            name="description",
            label="Description",
            value=item.get("description", "") or "",
            placeholder="Optional extra detail for this item",
        )
    )
    body_children.append(
        Div(
            _field(
                name="unit_price",
                label="Unit price",
                value=str(item.get("unit_price", "") or ""),
                type="number",
                placeholder="0.00",
                required=True,
                min="0.01",
                helper="Price for one unit. Must be greater than zero.",
            ),
            _unit_select(item.get("price_unit") or DEFAULT_UNIT_CODE),
            cls="grid grid-cols-1 md:grid-cols-2 gap-x-4",
        )
    )
    body_children.append(
        Div(
            _field(
                name="base_quantity",
                label="Base quantity",
                value=str(item.get("base_quantity", "1") or "1"),
                type="number",
                required=True,
                min="1",
                step="1",
                helper=(
                    "Quantity the unit price applies to. Leave at 1 unless "
                    "you price in multi-unit packs."
                ),
            ),
            cls="grid grid-cols-1 md:grid-cols-2 gap-x-4",
        )
    )

    return _modal_card(
        Form(
            Hidden(name="item_id", value=item_id),
            _modal_header(
                "Edit item" if is_edit else "New item",
                "Reusable invoice line. Quantity is asked for per invoice.",
            ),
            Div(*body_children, cls="px-6 py-5 max-h-[70vh] overflow-auto"),
            _modal_footer(
                _cancel_button(),
                Button(
                    icon("check-circle", cls="h-4 w-4"),
                    Span("Update item" if is_edit else "Save item"),
                    type="submit",
                    cls=(
                        "inline-flex items-center gap-2 px-4 py-2 "
                        "bg-indigo-600 text-white text-sm font-medium "
                        "rounded-lg hover:bg-indigo-700"
                    ),
                ),
            ),
            hx_post="/items/save",
            hx_target=LIST_TARGET,
            hx_swap="outerHTML",
            hx_include="#item-filters",
            method="post",
            action="/items/save",
            cls="flex flex-col",
        )
    )


# --------------------------------------------------------------------------
# Table
# --------------------------------------------------------------------------


def _item_row(item: dict) -> Tr:
    iid = item.get("id", "")
    kind = _kind_of(item)
    code = item.get("hsn_code") or item.get("isic_code") or "—"
    category = item.get("hsn_category") or item.get("isic_category") or ""
    is_active = bool(item.get("is_active", True))
    unit = coerce_unit_code(item.get("price_unit"))
    edit_attrs = {
        "hx_get": f"/items/{iid}/edit-overlay",
        "hx_target": MODAL_AREA,
        "hx_swap": "innerHTML",
    }
    cell = "px-4 py-2 cursor-pointer"

    if is_active:
        # Deactivation affects future invoices → confirm first.
        toggle_control = Button(
            icon("x", cls="h-4 w-4"),
            type="button",
            title="Deactivate item",
            aria_label=f"Deactivate item {item.get('name', '')}",
            onclick="event.stopPropagation();",
            hx_get=f"/items/{iid}/deactivate-overlay",
            hx_target=MODAL_AREA,
            hx_swap="innerHTML",
            cls=(
                "p-2 rounded-lg text-slate-400 hover:bg-amber-50 "
                "hover:text-amber-600 transition-colors"
            ),
        )
    else:
        # Restoring is reversible → no confirmation.
        toggle_control = Form(
            Button(
                icon("rotate-ccw", cls="h-4 w-4"),
                type="submit",
                title="Restore item",
                aria_label=f"Restore item {item.get('name', '')}",
                onclick="event.stopPropagation();",
                cls=(
                    "p-2 rounded-lg text-slate-400 hover:bg-emerald-50 "
                    "hover:text-emerald-600 transition-colors"
                ),
            ),
            Hidden(name="_row", value="1"),
            method="post",
            action=f"/items/{iid}/restore",
            hx_post=f"/items/{iid}/restore",
            hx_target=LIST_TARGET,
            hx_swap="outerHTML",
            hx_include="#item-filters",
            cls="inline",
        )

    return Tr(
        Td(
            Input(
                type="checkbox",
                name="item_ids",
                value=str(iid),
                cls=(
                    "zefe-item-check h-4 w-4 rounded border-slate-300 "
                    "text-indigo-600 focus:ring-indigo-500 cursor-pointer"
                ),
                onclick="event.stopPropagation();",
            ),
            cls="px-4 py-3 w-10",
        ),
        Td(
            Div(
                P(
                    item.get("name", ""),
                    cls="text-sm font-semibold text-slate-900 truncate",
                ),
                P(
                    item.get("sku") or "No SKU",
                    cls="text-xs text-slate-500 font-mono truncate",
                ),
                cls="min-w-0",
            ),
            cls=f"{cell} max-w-xs",
            **edit_attrs,
        ),
        Td(_kind_badge(kind), cls=cell, **edit_attrs),
        Td(
            Div(
                P(
                    code,
                    cls="text-sm font-mono text-slate-700 whitespace-nowrap",
                ),
                P(category, cls="text-xs text-slate-500 truncate")
                if category
                else "",
                cls="min-w-0",
            ),
            cls=f"{cell} max-w-[14rem]",
            **edit_attrs,
        ),
        Td(
            f"{float(item.get('unit_price', 0) or 0):.2f}",
            cls=(
                "px-4 py-2 text-sm font-medium text-slate-900 text-right "
                "whitespace-nowrap cursor-pointer"
            ),
            **edit_attrs,
        ),
        Td(
            Span(
                unit,
                title=unit_code_label(unit),
                cls=(
                    "inline-flex items-center px-2 py-0.5 rounded-md "
                    "text-[11px] font-mono font-semibold bg-slate-100 "
                    "text-slate-700 border border-slate-200 w-fit"
                ),
            ),
            cls=cell,
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
                    aria_label=f"Delete item {item.get('name', '')}",
                    onclick="event.stopPropagation();",
                    hx_get=f"/items/{iid}/delete-overlay",
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
        cls=(
            "border-b border-slate-100 hover:bg-slate-50/50 transition-colors"
        ),
    )


def _item_table(items: list[dict], active: bool) -> Div:
    if not items:
        return empty_state(
            icon_name="package",
            title="No items found" if active else "No inactive items",
            subtitle=(
                "Save your first catalog item so invoice lines only need a "
                "quantity."
                if active
                else "Deactivated items will appear here and can be restored."
            ),
            action_link=Button(
                icon("plus", cls="h-4 w-4"),
                Span("Add item"),
                type="button",
                hx_get="/items/new-overlay",
                hx_target=MODAL_AREA,
                hx_swap="innerHTML",
                cls=(
                    "mt-4 inline-flex items-center gap-2 px-4 py-2 "
                    "bg-indigo-600 text-white text-sm font-medium "
                    "rounded-lg hover:bg-indigo-700"
                ),
            )
            if active
            else None,
            id="item-list",
        )
    headers = [
        Input(
            type="checkbox",
            id="zefe-item-select-all",
            cls=(
                "h-4 w-4 rounded border-slate-300 text-indigo-600 "
                "focus:ring-indigo-500 cursor-pointer"
            ),
        ),
        "Item",
        "Type",
        "Classification",
        ("Unit price", "right"),
        "Unit",
        "Status",
        "",
    ]
    return table_container(
        headers, [_item_row(i) for i in items], id="item-list"
    )


_ITEMS_JS = """
(function(){
  function selected(){
    return Array.from(document.querySelectorAll('.zefe-item-check:checked'))
      .map(function(c){return c.value;});
  }
  function refresh(){
    var ids = selected();
    var bar = document.getElementById('zefe-item-bulk-bar');
    var count = document.getElementById('zefe-item-bulk-count');
    document.querySelectorAll('.zefe-item-bulk-ids').forEach(function(i){
      i.value = ids.join(',');
    });
    if (bar) bar.style.display = ids.length ? 'flex' : 'none';
    if (count) count.textContent = ids.length + ' selected';
    var all = document.querySelectorAll('.zefe-item-check');
    var sa = document.getElementById('zefe-item-select-all');
    if (sa) {
      sa.checked = all.length > 0 && ids.length === all.length;
      sa.indeterminate = ids.length > 0 && ids.length < all.length;
    }
  }
  document.addEventListener('change', function(e){
    if (e.target && e.target.classList &&
        e.target.classList.contains('zefe-item-check')) refresh();
    if (e.target && e.target.id === 'zefe-item-select-all') {
      document.querySelectorAll('.zefe-item-check').forEach(function(c){
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
            id="zefe-item-bulk-count",
            cls="text-sm font-semibold text-slate-700",
        ),
        Div(
            Button(
                icon(primary_icon, cls="h-3.5 w-3.5"),
                Span(primary_label),
                type="button",
                hx_get=f"/items/bulk-confirm?action={primary_action}",
                hx_target=MODAL_AREA,
                hx_swap="innerHTML",
                hx_include="#zefe-item-bulk-ids-1, #item-filters",
                cls=primary_cls,
            ),
            Button(
                icon("trash", cls="h-3.5 w-3.5"),
                Span("Delete selected"),
                type="button",
                hx_get="/items/bulk-confirm?action=delete",
                hx_target=MODAL_AREA,
                hx_swap="innerHTML",
                hx_include="#zefe-item-bulk-ids-2, #item-filters",
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
                id="zefe-item-bulk-ids-1",
                cls="zefe-item-bulk-ids",
            ),
            Input(
                type="hidden",
                name="ids",
                value="",
                id="zefe-item-bulk-ids-2",
                cls="zefe-item-bulk-ids",
            ),
            cls="flex items-center gap-2",
        ),
        id="zefe-item-bulk-bar",
        style="display:none;",
        cls=(
            "mb-4 px-4 py-3 bg-slate-50 border border-slate-200 "
            "rounded-xl items-center justify-between"
        ),
    )


def _pagination(
    page: int, total_pages: int, q: str, kind: str, active_param: str
) -> Div:
    base = (
        f"/items?q={urllib.parse.quote(q or '')}"
        f"&kind={urllib.parse.quote(kind or '')}"
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
    items: list[dict],
    page: int,
    total_pages: int,
    q: str,
    kind: str,
    active_param: str,
    banner=None,
) -> Div:
    is_active = active_param != "false"
    return Div(
        banner or "",
        _bulk_bar(is_active),
        _item_table(items, is_active),
        _pagination(page, total_pages, q, kind, active_param),
        Script(_ITEMS_JS),
        id="item-list-container",
    )


def _filters(q: str, kind: str, active_param: str) -> Form:
    kind_opts = [
        Option("All types", value="", selected=(kind == "")),
        Option("Products", value="product", selected=(kind == "product")),
        Option("Services", value="service", selected=(kind == "service")),
    ]
    status_opts = [
        Option("Active", value="true", selected=(active_param != "false")),
        Option("Inactive", value="false", selected=(active_param == "false")),
    ]
    common = {
        "hx_get": "/items",
        "hx_target": LIST_TARGET,
        "hx_swap": "outerHTML",
        "hx_include": "#item-filters",
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
                    placeholder="Search by name, SKU, or description…",
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
                    *kind_opts,
                    name="kind",
                    hx_trigger="change",
                    **common,
                    cls=_SELECT_CLS,
                ),
                icon("chevron-down", cls=_CHEVRON_CLS),
                cls="relative w-40 shrink-0",
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
        id="item-filters",
        method="get",
        action="/items",
        cls="mb-4",
    )


# --------------------------------------------------------------------------
# Payload parsing / validation
# --------------------------------------------------------------------------


def _to_float(raw, default=None):
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _parse_item_form(form) -> tuple[dict, str]:
    hsn = (form.get("hsn_code") or "").strip()
    isic = (form.get("isic_code") or "").strip()
    payload = {
        "sku": (form.get("sku") or "").strip() or None,
        "name": (form.get("name") or "").strip(),
        "description": (form.get("description") or "").strip() or None,
        "hsn_code": hsn or None,
        "hsn_category": (form.get("hsn_category") or "").strip() or None,
        "isic_code": isic or None,
        "isic_category": (form.get("isic_category") or "").strip() or None,
        "price_unit": coerce_unit_code(form.get("price_unit")),
    }

    if not payload["name"]:
        return payload, "Item name is required."
    if hsn and isic:
        return payload, (
            "An item is either a product (HS code) or a service (ISIC code), "
            "not both. Re-pick the classification."
        )
    if not hsn and not isic:
        return payload, (
            "Select a classification: a product HS code or a service ISIC "
            "code is required."
        )
    if hsn and not payload["hsn_category"]:
        return payload, (
            "Product category is missing — re-select the product from the "
            "FIRS lookup."
        )
    if isic and not payload["isic_category"]:
        return payload, (
            "Service category is missing — re-select the service from the "
            "FIRS lookup."
        )

    unit_price = _to_float(form.get("unit_price"))
    if unit_price is None:
        return payload, "Unit price must be a number."
    if unit_price <= 0:
        return payload, "Unit price must be greater than zero."
    payload["unit_price"] = unit_price

    base_qty = _to_float(form.get("base_quantity"), 1.0)
    if base_qty is None:
        return payload, "Base quantity must be a number."
    if base_qty <= 0:
        return payload, "Base quantity must be greater than zero."
    payload["base_quantity"] = base_qty

    return payload, ""


async def _search_classifications(jwt: str, sid: str, q: str) -> list[dict]:
    async def _prods():
        try:
            return await api_client.search_products(
                jwt, q, length=20, session_id=sid
            )
        except Exception:
            logger.exception("items lookup: search_products failed")
            return []

    async def _svcs():
        try:
            return await api_client.search_services(
                jwt, q, length=20, session_id=sid
            )
        except Exception:
            logger.exception("items lookup: search_services failed")
            return []

    prods, svcs = await asyncio.gather(_prods(), _svcs())
    hits: list[dict] = []
    for h in prods or []:
        if not isinstance(h, dict):
            continue
        code = str(h.get("hscode") or h.get("code") or "").strip()
        if not code:
            continue
        label = str(h.get("description") or "").strip()
        hits.append(
            {
                "kind": "product",
                "code": code,
                "label": label,
                "category": str(
                    h.get("product_category") or h.get("category") or label
                ).strip(),
            }
        )
    for h in svcs or []:
        if not isinstance(h, dict):
            continue
        code = str(h.get("code") or "").strip()
        if not code:
            continue
        label = str(h.get("description") or "").strip()
        hits.append(
            {
                "kind": "service",
                "code": code,
                "label": label,
                "category": str(h.get("category") or label).strip(),
            }
        )
    lower = q.lower()
    hits.sort(
        key=lambda h: (
            0 if (h["label"] or "").lower().startswith(lower) else 1,
            (h["label"] or "").lower(),
        )
    )
    return hits


async def _load_page(
    jwt: str,
    sid: str,
    q: str,
    kind: str,
    active_param: str,
    page: int,
) -> tuple[list[dict], int, int, str]:
    offset = (max(page, 1) - 1) * PAGE_SIZE
    try:
        res = await api_client.list_items(
            jwt,
            session_id=sid,
            search=q or None,
            kind=kind or None,
            active=(active_param != "false"),
            offset=offset,
            limit=PAGE_SIZE,
        )
        items = res.get("items", []) or []
        total = int(res.get("total", 0) or 0)
        total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        return items, total, total_pages, ""
    except api_client.APIError as e:
        logger.exception("list_items failed")
        return [], 0, 1, extract_api_error_detail(e)
    except Exception:
        logger.exception("list_items transport error")
        return [], 0, 1, "Backend service unavailable."


def register_routes(rt) -> None:
    # ----------------------------------------------------------------- list
    @rt("/items", methods=["GET"])
    async def list_items_page(
        req: Request,
        q: str = "",
        kind: str = "",
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
        kind = kind if kind in ("product", "service") else ""
        active = "false" if active == "false" else "true"

        items, total, total_pages, load_error = await _load_page(
            jwt, sid, q, kind, active, page
        )
        if page > total_pages:
            page = total_pages
            items, total, total_pages, load_error = await _load_page(
                jwt, sid, q, kind, active, page
            )

        if req.headers.get("HX-Request") == "true":
            banner = alert("error", load_error) if load_error else None
            return _list_container(
                items, page, total_pages, q, kind, active, banner
            )

        header = Div(
            Div(
                H2("Items", cls="text-2xl font-bold text-slate-900"),
                P(
                    f"{total} {'active' if active == 'true' else 'inactive'} "
                    "item(s) in your catalog",
                    cls="text-sm text-slate-500 mt-1",
                ),
            ),
            Div(
                Button(
                    icon("upload", cls="h-4 w-4"),
                    Span("Import"),
                    type="button",
                    hx_get="/items/import-overlay",
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
                    Span("Add item"),
                    type="button",
                    hx_get="/items/new-overlay",
                    hx_target=MODAL_AREA,
                    hx_swap="innerHTML",
                    cls=(
                        "inline-flex items-center gap-2 px-4 py-2 "
                        "bg-indigo-600 text-white text-sm font-medium "
                        "rounded-lg hover:bg-indigo-700"
                    ),
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
            "Items",
            header,
            *banners,
            guidance_panel(
                "Items are reusable invoice lines. Saving name, SKU, "
                "classification, unit price and unit code here means the "
                "invoice wizard only asks for quantity.",
                cls="mb-5",
            ),
            _filters(q, kind, active),
            _list_container(items, page, total_pages, q, kind, active),
            Div(id="item-modal-area"),
            active_nav="items",
            username=current_username(req),
            business_id=current_business_id(req),
        )

    def _filter_state(form_or_req) -> tuple[str, str, str, int]:
        get = form_or_req.get
        q = (get("q") or "").strip()
        kind = (get("kind") or "").strip()
        kind = kind if kind in ("product", "service") else ""
        active = "false" if (get("active") or "") == "false" else "true"
        try:
            page = max(1, int(get("page") or 1))
        except (TypeError, ValueError):
            page = 1
        return q, kind, active, page

    async def _refreshed_list(req: Request, form, banner=None):
        jwt = current_jwt(req)
        sid = get_session_id(req)
        q, kind, active, page = _filter_state(form)
        items, _total, total_pages, load_error = await _load_page(
            jwt, sid, q, kind, active, page
        )
        if not items and page > 1:
            page -= 1
            items, _total, total_pages, load_error = await _load_page(
                jwt, sid, q, kind, active, page
            )
        if load_error and banner is None:
            banner = alert("error", load_error)
        return (
            _list_container(items, page, total_pages, q, kind, active, banner),
            Div(id="item-modal-area", hx_swap_oob="innerHTML"),
        )

    # -------------------------------------------------------------- overlays
    @rt("/items/clear-overlay", methods=["GET"])
    def clear_overlay(req: Request):
        return HTMLResponse("")

    @rt("/items/new-overlay", methods=["GET"])
    def new_overlay(req: Request):
        redirect = require_session(req)
        if redirect:
            return redirect
        return _item_form_modal(
            {"price_unit": DEFAULT_UNIT_CODE, "base_quantity": 1}
        )

    @rt("/items/{item_id}/edit-overlay", methods=["GET"])
    async def edit_overlay(req: Request, item_id: int):
        redirect = require_session(req)
        if redirect:
            return redirect
        jwt = current_jwt(req)
        sid = get_session_id(req)
        try:
            item = await api_client.get_item(jwt, item_id, session_id=sid)
        except api_client.APIError as e:
            logger.exception("get_item failed")
            return _modal_card(
                _modal_header("Item unavailable", "Could not load this item."),
                Div(
                    alert("error", extract_api_error_detail(e)),
                    cls="px-6 py-5",
                ),
                _modal_footer(_cancel_button("Close")),
                max_w="max-w-md",
            )
        except Exception:
            logger.exception("get_item transport error")
            return HTMLResponse("")
        return _item_form_modal(item)

    # --------------------------------------------------------- classification
    @rt("/items/lookup", methods=["GET"])
    async def item_lookup(req: Request, lookup_q: str = ""):
        redirect = require_session(req)
        if redirect:
            return redirect
        q = (lookup_q or "").strip()
        if len(q) < 2:
            return Div(id="item-lookup-results")
        jwt = current_jwt(req)
        sid = get_session_id(req)
        hits = await _search_classifications(jwt, sid, q)
        return _lookup_results(hits, q)

    @rt("/items/classification/apply", methods=["GET"])
    def apply_classification(
        req: Request,
        kind: str = "product",
        code: str = "",
        label: str = "",
        category: str = "",
        name: str = "",
        description: str = "",
    ):
        redirect = require_session(req)
        if redirect:
            return redirect
        kind = "service" if kind == "service" else "product"
        code = (code or "").strip()
        label = (label or "").strip()
        category = (category or "").strip() or label

        item = {
            "hsn_code": code if kind == "product" else "",
            "hsn_category": category if kind == "product" else "",
            "isic_code": code if kind == "service" else "",
            "isic_category": category if kind == "service" else "",
        }

        def _short(full: str) -> str:
            if not full:
                return ""
            primary = full.split(";", 1)[0].strip()
            if len(primary) > 50 and "," in primary:
                primary = primary.split(",", 1)[0].strip()
            return (primary[:60] or full[:60]).strip()

        extras = []
        if not (name or "").strip():
            extras.append(
                Input(
                    id="item_name",
                    name="name",
                    type="text",
                    value=_short(label),
                    required=True,
                    placeholder="Premium rice (50kg bag)",
                    hx_swap_oob="outerHTML",
                    cls=_INPUT_CLS,
                )
            )
        if not (description or "").strip():
            extras.append(
                Input(
                    id="item_description",
                    name="description",
                    type="text",
                    value=label or category,
                    placeholder="Optional extra detail for this item",
                    hx_swap_oob="outerHTML",
                    cls=_INPUT_CLS,
                )
            )
        extras.append(
            Div(
                id="item-lookup-results",
                hx_swap_oob="outerHTML",
            )
        )
        extras.append(
            Input(
                type="search",
                name="lookup_q",
                id="item-lookup-q",
                value="",
                autocomplete="off",
                placeholder=(
                    "Search products & services e.g. 'rice', "
                    "'consulting', '1006.10'…"
                ),
                hx_get="/items/lookup",
                hx_trigger="keyup changed delay:400ms, search",
                hx_target="#item-lookup-results",
                hx_swap="outerHTML",
                hx_swap_oob="outerHTML",
                cls=_INPUT_CLS.replace("px-3", "pl-9 pr-9"),
            )
        )
        return (_classification_block(item), *extras)

    # ------------------------------------------------------------------ save
    @rt("/items/save", methods=["POST"])
    async def save_item(req: Request):
        redirect = require_session(req)
        if redirect:
            return redirect
        form = await req.form()
        jwt = current_jwt(req)
        sid = get_session_id(req)
        raw_id = (form.get("item_id") or "").strip()
        payload, err = _parse_item_form(form)

        display = {
            **payload,
            "id": raw_id,
            "unit_price": (form.get("unit_price") or "").strip(),
            "base_quantity": (form.get("base_quantity") or "1").strip(),
        }
        if err:
            return _item_form_modal(display, error=err)

        try:
            if raw_id:
                await api_client.update_item(
                    jwt, int(raw_id), payload, session_id=sid
                )
                msg = f"Item '{payload['name']}' updated."
            else:
                await api_client.create_item(jwt, payload, session_id=sid)
                msg = f"Item '{payload['name']}' created."
        except api_client.APIError as e:
            logger.exception("save_item failed")
            return _item_form_modal(display, error=extract_api_error_detail(e))
        except (TypeError, ValueError):
            logger.exception("save_item bad id")
            return _item_form_modal(display, error="Invalid item reference.")
        except Exception:
            logger.exception("save_item transport error")
            return _item_form_modal(
                display,
                error="Backend service unavailable. Please try again.",
            )

        return await _refreshed_list(req, form, alert("success", msg))

    # ------------------------------------------------- deactivate / restore
    @rt("/items/{item_id}/deactivate", methods=["POST"])
    async def deactivate_item(req: Request, item_id: int):
        redirect = require_session(req)
        if redirect:
            return redirect
        form = await req.form()
        jwt = current_jwt(req)
        sid = get_session_id(req)
        try:
            await api_client.delete_item(jwt, item_id, session_id=sid)
            banner = alert(
                "success",
                "Item deactivated. It stays on past invoices and can be "
                "restored from the Inactive filter.",
            )
        except api_client.APIError as e:
            logger.exception("deactivate_item failed")
            banner = alert("error", extract_api_error_detail(e))
        except Exception:
            logger.exception("deactivate_item transport error")
            banner = alert("error", "Backend service unavailable.")
        return await _refreshed_list(req, form, banner)

    @rt("/items/{item_id}/restore", methods=["POST"])
    async def restore_item(req: Request, item_id: int):
        redirect = require_session(req)
        if redirect:
            return redirect
        form = await req.form()
        jwt = current_jwt(req)
        sid = get_session_id(req)
        try:
            await api_client.bulk_activate_items(jwt, [item_id], session_id=sid)
            banner = alert("success", "Item restored to your active catalog.")
        except api_client.APIError as e:
            logger.exception("restore_item failed")
            banner = alert("error", extract_api_error_detail(e))
        except Exception:
            logger.exception("restore_item transport error")
            banner = alert("error", "Backend service unavailable.")
        return await _refreshed_list(req, form, banner)

    # ------------------------------------------------------ deactivate guard
    @rt("/items/{item_id}/deactivate-overlay", methods=["GET"])
    async def deactivate_overlay(req: Request, item_id: int):
        redirect = require_session(req)
        if redirect:
            return redirect
        jwt = current_jwt(req)
        sid = get_session_id(req)
        name = f"#{item_id}"
        try:
            item = await api_client.get_item(jwt, item_id, session_id=sid)
            name = item.get("name") or name
        except Exception:
            logger.exception("deactivate_overlay get_item failed")

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
                    "Deactivate this item?",
                    cls="text-lg font-bold text-slate-950 text-center",
                ),
                P(
                    f'"{name}" will be hidden from the active catalog and from '
                    "new invoice lines. Existing invoices are untouched, and "
                    "you can restore it any time from the Inactive filter.",
                    cls="text-sm text-slate-600 text-center mt-2 leading-relaxed",
                ),
                cls="p-6",
            ),
            _modal_footer(
                _cancel_button(),
                Form(
                    Button(
                        icon("x", cls="h-4 w-4"),
                        Span("Deactivate item"),
                        type="submit",
                        cls=(
                            "inline-flex items-center gap-2 px-4 py-2 "
                            "bg-amber-600 text-white text-sm font-medium "
                            "rounded-lg hover:bg-amber-700"
                        ),
                    ),
                    hx_post=f"/items/{item_id}/deactivate",
                    hx_target=LIST_TARGET,
                    hx_swap="outerHTML",
                    hx_include="#item-filters",
                    method="post",
                    action=f"/items/{item_id}/deactivate",
                    cls="inline",
                ),
            ),
            max_w="max-w-md",
        )

    # ---------------------------------------------------------------- delete
    @rt("/items/{item_id}/delete-overlay", methods=["GET"])
    async def delete_overlay(req: Request, item_id: int):
        redirect = require_session(req)
        if redirect:
            return redirect
        jwt = current_jwt(req)
        sid = get_session_id(req)
        name = f"#{item_id}"
        try:
            item = await api_client.get_item(jwt, item_id, session_id=sid)
            name = item.get("name") or name
        except Exception:
            logger.exception("delete_overlay get_item failed")

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
                    "Delete this item permanently?",
                    cls="text-lg font-bold text-slate-950 text-center",
                ),
                P(
                    f'"{name}" will be removed from your catalog for good. '
                    "This item may still be referenced by past invoices, so "
                    "Deactivate is the safer choice: it stops the item "
                    "appearing on new invoices while keeping it for reference.",
                    cls="text-sm text-slate-600 text-center mt-2 leading-relaxed",
                ),
                Div(
                    Button(
                        icon("x", cls="h-3.5 w-3.5"),
                        Span("Deactivate instead (recommended)"),
                        type="button",
                        hx_get=f"/items/{item_id}/deactivate-overlay",
                        hx_target=MODAL_AREA,
                        hx_swap="innerHTML",
                        cls=(
                            "inline-flex items-center gap-1.5 px-3 py-1.5 "
                            "bg-white border border-amber-300 text-amber-700 "
                            "text-xs font-semibold rounded-lg hover:bg-amber-50"
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
                        form=f"item-hard-delete-{item_id}",
                        cls=(
                            "h-4 w-4 rounded border-slate-300 text-rose-600 "
                            "focus:ring-rose-500 cursor-pointer shrink-0 mt-0.5"
                        ),
                    ),
                    Span(
                        "I understand this permanently removes the item and "
                        "cannot be undone.",
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
                    id=f"item-hard-delete-{item_id}",
                    hx_post=f"/items/{item_id}/delete",
                    hx_target=LIST_TARGET,
                    hx_swap="outerHTML",
                    hx_include="#item-filters, [name='confirm_hard']",
                    method="post",
                    action=f"/items/{item_id}/delete",
                    cls="inline",
                ),
            ),
            max_w="max-w-md",
        )

    @rt("/items/{item_id}/delete", methods=["POST"])
    async def delete_item_route(req: Request, item_id: int):
        redirect = require_session(req)
        if redirect:
            return redirect
        form = await req.form()
        jwt = current_jwt(req)
        sid = get_session_id(req)
        if not (form.get("confirm_hard") or "").strip():
            return await _refreshed_list(
                req,
                form,
                alert(
                    "error",
                    "Permanent delete was not confirmed. Tick the "
                    "acknowledgement, or deactivate the item instead.",
                ),
            )
        try:
            await api_client.delete_item(
                jwt, item_id, session_id=sid, hard=True
            )
            banner = alert("success", "Item deleted permanently.")
        except api_client.APIError as e:
            logger.exception("delete_item failed")
            banner = alert("error", extract_api_error_detail(e))
        except Exception:
            logger.exception("delete_item transport error")
            banner = alert("error", "Backend service unavailable.")
        return await _refreshed_list(req, form, banner)

    # ------------------------------------------------------------ bulk flows
    @rt("/items/bulk-confirm", methods=["GET"])
    async def bulk_confirm(
        req: Request,
        action: str = "deactivate",
        ids: str = "",
        q: str = "",
        kind: str = "",
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
        id_list = [s.strip() for s in (ids or "").split(",") if s.strip()][:200]
        if not id_list:
            return _modal_card(
                _modal_header(
                    "Nothing selected",
                    "Tick at least one item to continue.",
                ),
                Div(
                    P(
                        "Select one or more rows using the checkboxes, then "
                        "try again.",
                        cls="text-sm text-slate-600",
                    ),
                    cls="px-6 py-5",
                ),
                _modal_footer(_cancel_button("Close")),
                max_w="max-w-md",
            )

        count = len(id_list)
        noun = "item" if count == 1 else "items"
        copy = {
            "deactivate": (
                f"Deactivate {count} {noun}?",
                f"{count} {noun} will be hidden from the active catalog and "
                "from new invoice lines. Existing invoices are untouched, and "
                "you can restore them any time.",
                f"Deactivate {count} {noun}",
                (
                    "px-4 py-2 bg-amber-600 text-white text-sm font-medium "
                    "rounded-lg hover:bg-amber-700"
                ),
            ),
            "restore": (
                f"Restore {count} {noun}?",
                f"{count} {noun} will return to your active catalog and "
                "become selectable on new invoice lines again.",
                f"Restore {count} {noun}",
                (
                    "px-4 py-2 bg-emerald-600 text-white text-sm font-medium "
                    "rounded-lg hover:bg-emerald-700"
                ),
            ),
            "delete": (
                f"Delete {count} {noun} permanently?",
                f"{count} {noun} will be removed from your catalog for good. "
                "This cannot be undone. Use Deactivate if you may need them "
                "later.",
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
                    cls="text-sm text-slate-600 text-center mt-2",
                ),
                cls="p-6",
            ),
            _modal_footer(
                _cancel_button(),
                Form(
                    Hidden(name="ids", value=",".join(id_list)),
                    Hidden(name="action", value=action),
                    Hidden(name="q", value=q),
                    Hidden(name="kind", value=kind),
                    Hidden(name="active", value=active),
                    Hidden(name="page", value=str(page)),
                    Button(Span(btn_label), type="submit", cls=btn_cls),
                    hx_post="/items/bulk",
                    hx_target=LIST_TARGET,
                    hx_swap="outerHTML",
                    method="post",
                    action="/items/bulk",
                    cls="inline",
                ),
            ),
            max_w="max-w-md",
        )

    @rt("/items/bulk", methods=["POST"])
    async def bulk_apply(req: Request):
        redirect = require_session(req)
        if redirect:
            return redirect
        form = await req.form()
        action = (form.get("action") or "deactivate").strip()
        raw_ids = (form.get("ids") or "").strip()
        ids: list[int] = []
        for chunk in raw_ids.split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            try:
                ids.append(int(chunk))
            except ValueError:
                continue

        jwt = current_jwt(req)
        sid = get_session_id(req)
        banner = None
        if not ids:
            banner = alert("error", "No valid items were selected.")
        else:
            try:
                if action == "restore":
                    res = await api_client.bulk_activate_items(
                        jwt, ids, session_id=sid
                    )
                    n = int(res.get("activated", len(ids)) or 0)
                    banner = alert("success", f"Restored {n} item(s).")
                elif action == "delete":
                    res = await api_client.bulk_delete_items(
                        jwt, ids, session_id=sid, hard=True
                    )
                    n = int(res.get("deleted", len(ids)) or 0)
                    banner = alert("success", f"Deleted {n} item(s).")
                else:
                    res = await api_client.bulk_delete_items(
                        jwt, ids, session_id=sid, hard=False
                    )
                    n = int(res.get("deleted", len(ids)) or 0)
                    banner = alert("success", f"Deactivated {n} item(s).")
            except api_client.APIError as e:
                logger.exception("bulk_apply failed")
                banner = alert("error", extract_api_error_detail(e))
            except Exception:
                logger.exception("bulk_apply transport error")
                banner = alert("error", "Backend service unavailable.")

        return await _refreshed_list(req, form, banner)

    # ---------------------------------------------------------------- import
    @rt("/items/import-overlay", methods=["GET"])
    def import_overlay(req: Request, error: str = ""):
        redirect = require_session(req)
        if redirect:
            return redirect
        columns = (
            "sku, name, description, code, unit_price, price_unit, "
            "base_quantity"
        )
        body = [
            alert("error", error, cls="mb-4") if error else "",
            guidance_panel(
                "Upload a CSV (or XLSX) with these columns: " + columns,
                title="Expected columns",
                cls="mb-4",
            ),
            Div(
                Label(
                    "File",
                    Span(" *", cls="text-rose-500 font-bold"),
                    fr="items_import_file",
                    cls="block text-sm font-medium text-slate-700 mb-1.5",
                ),
                Input(
                    id="items_import_file",
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
                    "Use one classification code per item in the code column: "
                    "HS format XXXX.XX for a product, or 4 digits for a "
                    "service. Rows matching an existing SKU are updated. "
                    "Invalid rows are skipped with a reason and never abort "
                    "the import. Price units must be official codes such as "
                    "EA or KGM."
                ),
                cls="mb-2",
            ),
        ]
        return _modal_card(
            Form(
                _modal_header(
                    "Import items",
                    "Bulk-create or update catalog items from a spreadsheet.",
                ),
                Div(*body, cls="px-6 py-5 max-h-[70vh] overflow-auto"),
                _modal_footer(
                    _cancel_button(),
                    primary_button("Import file", type="submit"),
                ),
                method="post",
                action="/items/import",
                enctype="multipart/form-data",
                cls="flex flex-col",
            )
        )

    @rt("/items/import", methods=["POST"])
    async def import_items_route(req: Request):
        redirect = require_session(req)
        if redirect:
            return redirect
        form = await req.form()
        upload = form.get("file")
        if upload is None or not getattr(upload, "filename", ""):
            return RedirectResponse(
                "/items?error="
                + urllib.parse.quote_plus("Choose a file to import."),
                status_code=303,
            )
        try:
            content = await upload.read()
        except Exception:
            logger.exception("import_items read failed")
            return RedirectResponse(
                "/items?error="
                + urllib.parse.quote_plus("Could not read the uploaded file."),
                status_code=303,
            )

        jwt = current_jwt(req)
        sid = get_session_id(req)
        try:
            res = await api_client.import_items(
                jwt, upload.filename, content, session_id=sid
            )
        except api_client.APIError as e:
            logger.exception("import_items failed")
            return RedirectResponse(
                "/items?error="
                + urllib.parse.quote_plus(extract_api_error_detail(e)),
                status_code=303,
            )
        except Exception:
            logger.exception("import_items transport error")
            return RedirectResponse(
                "/items?error="
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
        query = "/items?success=" + urllib.parse.quote_plus(msg)
        if errors:
            detail = "; ".join(str(e) for e in errors[:3])
            if len(errors) > 3:
                detail += f" (+{len(errors) - 3} more)"
            query += "&error=" + urllib.parse.quote_plus(
                f"Skipped rows: {detail}"
            )
        return RedirectResponse(query, status_code=303)
