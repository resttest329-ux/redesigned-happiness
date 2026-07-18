from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fasthtml.common import (
    A,
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
from ui.components import (
    alert,
    confirm_modal,
    empty_state,
    guidance_panel,
    guidance_text,
    icon_button,
    modal_shell,
    pagination_controls,
    primary_button,
    table_container,
    text_field,
)
from ui.icons import icon
from ui.layout import app_shell

logger = logging.getLogger(__name__)


ITEM_TEXT_FIELDS = [
    ("sku", "SKU", "text", "e.g. RICE-001", True, "Unique per business."),
    ("name", "Item name", "text", "Premium Rice, 50kg bag", True, ""),
    (
        "description",
        "Description",
        "text",
        "Optional details",
        False,
        "",
    ),
    (
        "unit_price",
        "Unit price",
        "number",
        "0.00",
        False,
        "Default price used when picking this item on an invoice line.",
    ),
    (
        "price_unit",
        "Price unit",
        "text",
        "NGN per 1",
        False,
        "Unit descriptor shown on the invoice, e.g. 'NGN per 1'.",
    ),
]


# ---------------------------------------------------------------------------
# Small local components (kept close to the routes so the layout is easy to
# tweak without touching shared UI primitives)
# ---------------------------------------------------------------------------


def _classification_badge(item: dict, *, size: str = "sm") -> Span:
    hsn = (item.get("hsn_code") or "").strip()
    isic = (item.get("isic_code") or "").strip()
    if hsn:
        label = f"HS {hsn}"
        cls = "bg-indigo-50 text-indigo-700 border-indigo-200"
    elif isic:
        label = f"ISIC {isic}"
        cls = "bg-purple-50 text-purple-700 border-purple-200"
    else:
        label = "Unclassified"
        cls = "bg-slate-100 text-slate-500 border-slate-200"
    padding = (
        "px-2 py-0.5 text-[11px]" if size == "sm" else "px-2.5 py-1 text-xs"
    )
    return Span(
        label,
        cls=(
            f"inline-flex items-center rounded-full font-mono font-semibold "
            f"border w-fit {padding} {cls}"
        ),
    )


def _classification_kind(item: dict) -> str:
    if item.get("hsn_code"):
        return "Product"
    if item.get("isic_code"):
        return "Service"
    return "—"


def _bulk_action_bar() -> Div:
    return Form(
        Div(
            Span(
                "0 selected",
                id="zefe-item-bulk-count",
                cls="text-sm font-semibold text-slate-700",
            ),
            Hidden(name="ids", value="", id="zefe-item-bulk-ids"),
            Button(
                icon("trash", cls="h-4 w-4"),
                type="submit",
                title="Delete selected items",
                aria_label="Delete selected items",
                hx_get="/items/bulk-delete-confirm",
                hx_target="#item-modal-area",
                hx_swap="innerHTML",
                hx_include="#zefe-item-bulk-ids, [name='q'], [name='kind'], [name='page']",
                cls=(
                    "inline-flex items-center justify-center p-2 bg-rose-600 "
                    "text-white rounded-lg hover:bg-rose-700 focus:outline-none "
                    "focus:ring-2 focus:ring-rose-500 focus:ring-offset-1 "
                    "transition-colors shadow-xs"
                ),
            ),
            cls="flex items-center justify-between w-full",
        ),
        method="get",
        action="/items/bulk-delete-confirm",
        id="zefe-item-bulk-bar",
        style="display:none;",
        cls="mb-4 px-4 py-3 bg-rose-50/50 border border-rose-100 rounded-xl",
    )


_ITEMS_JS = """
(function(){
  function selected(){return Array.from(document.querySelectorAll('.zefe-item-check:checked')).map(c=>c.value);}
  function refresh(){
    var ids=selected();
    var bar=document.getElementById('zefe-item-bulk-bar');
    var count=document.getElementById('zefe-item-bulk-count');
    var input=document.getElementById('zefe-item-bulk-ids');
    if(bar){bar.style.display=ids.length?'flex':'none';}
    if(count){count.textContent=ids.length+' selected';}
    if(input){input.value=ids.join(',');}
    var all=document.querySelectorAll('.zefe-item-check');
    var sa=document.getElementById('zefe-item-select-all');
    if(sa){sa.checked=all.length>0 && ids.length===all.length;sa.indeterminate=ids.length>0 && ids.length<all.length;}
  }
  document.addEventListener('change',function(e){
    if(e.target&&e.target.classList&&e.target.classList.contains('zefe-item-check'))refresh();
    if(e.target&&e.target.id==='zefe-item-select-all'){
      document.querySelectorAll('.zefe-item-check').forEach(c=>c.checked=e.target.checked);refresh();
    }
  });
  document.body.addEventListener('htmx:afterSwap',refresh);
  refresh();
})();
"""


def _item_row(item: dict) -> Tr:
    iid = item.get("id", "")
    edit_hx_get = f"/items/{iid}/edit-overlay"
    kind = _classification_kind(item)
    unit_price = item.get("unit_price")
    price_display = (
        f"{float(unit_price):,.2f}"
        if unit_price is not None and unit_price != ""
        else "—"
    )
    unit = item.get("price_unit") or ""
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
                    item.get("sku", ""),
                    cls="text-sm font-mono font-semibold text-slate-900 truncate",
                ),
                P(
                    item.get("name", ""),
                    cls="text-xs text-slate-500 truncate",
                ),
                cls="min-w-0",
            ),
            cls="px-4 py-3 max-w-xs cursor-pointer",
            hx_get=edit_hx_get,
            hx_target="#item-modal-area",
        ),
        Td(
            Span(
                kind,
                cls=(
                    "inline-flex items-center px-2 py-0.5 rounded-full text-[11px] "
                    "font-semibold border "
                    + (
                        "bg-indigo-50 text-indigo-700 border-indigo-200"
                        if kind == "Product"
                        else (
                            "bg-purple-50 text-purple-700 border-purple-200"
                            if kind == "Service"
                            else "bg-slate-100 text-slate-500 border-slate-200"
                        )
                    )
                ),
            ),
            cls="px-4 py-3 whitespace-nowrap cursor-pointer",
            hx_get=edit_hx_get,
            hx_target="#item-modal-area",
        ),
        Td(
            _classification_badge(item),
            cls="px-4 py-3 whitespace-nowrap cursor-pointer",
            hx_get=edit_hx_get,
            hx_target="#item-modal-area",
        ),
        Td(
            Div(
                P(
                    price_display,
                    cls="text-sm font-semibold text-slate-900 text-right",
                ),
                P(
                    unit,
                    cls="text-[11px] text-slate-500 text-right",
                )
                if unit
                else "",
                cls="",
            ),
            cls="px-4 py-3 whitespace-nowrap cursor-pointer",
            hx_get=edit_hx_get,
            hx_target="#item-modal-area",
        ),
        Td(
            icon_button(
                "trash",
                "Delete",
                variant="danger",
                hx_get=f"/items/{iid}/delete-overlay",
                hx_target="#item-modal-area",
                onclick="event.stopPropagation();",
            ),
            cls="px-4 py-3 text-right w-16",
        ),
        cls="border-b border-slate-100 hover:bg-slate-50/50 transition-colors",
    )


def _item_table(items: list[dict]) -> Div:
    if not items:
        return empty_state(
            icon_name="receipt",
            title="No items found",
            subtitle="Add products or services to reuse them on future invoices.",
            action_link=Button(
                icon("plus", cls="h-4 w-4"),
                Span("Add item"),
                hx_get="/items/new-overlay",
                hx_target="#item-modal-area",
                cls=(
                    "mt-4 inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 "
                    "text-white text-sm font-medium rounded-lg hover:bg-indigo-700"
                ),
            ),
            id="item-list",
        )
    rows = [_item_row(it) for it in items]
    headers = [
        Input(
            type="checkbox",
            id="zefe-item-select-all",
            cls=(
                "h-4 w-4 rounded border-slate-300 text-indigo-600 "
                "focus:ring-indigo-500 cursor-pointer"
            ),
        ),
        "SKU / Name",
        "Kind",
        "Classification",
        "Unit price",
        "",
    ]
    return table_container(headers, rows, id="item-list")


# ---------------------------------------------------------------------------
# Classification search embedded in the item form
# ---------------------------------------------------------------------------


def _selected_classification_summary(
    hsn_code: str,
    hsn_category: str,
    isic_code: str,
    isic_category: str,
) -> Div:
    has_hsn = bool(hsn_code)
    has_isic = bool(isic_code)
    if has_hsn:
        kind_label = "Product"
        kind_cls = "bg-indigo-100 text-indigo-700"
        code_display = f"HS {hsn_code}"
        cat_display = hsn_category or ""
    elif has_isic:
        kind_label = "Service"
        kind_cls = "bg-purple-100 text-purple-700"
        code_display = f"ISIC {isic_code}"
        cat_display = isic_category or ""
    else:
        return Div(
            icon("alert-circle", cls="h-4 w-4 text-amber-500 shrink-0"),
            Span(
                "No classification attached yet — search for a product or service below.",
                cls="text-xs text-amber-700",
            ),
            id="item-classification-summary",
            cls=(
                "flex items-center gap-2 p-2.5 rounded-lg border "
                "bg-amber-50 border-amber-200"
            ),
        )
    return Div(
        icon("check-circle", cls="h-4 w-4 text-emerald-600 shrink-0"),
        Span(
            "Classification attached",
            cls="text-xs font-medium text-emerald-700",
        ),
        Span(
            kind_label,
            cls=(
                "ml-auto inline-flex items-center px-2 py-0.5 rounded-full "
                f"text-[10px] font-semibold uppercase tracking-wider {kind_cls} shrink-0"
            ),
        ),
        Span(
            code_display,
            cls=(
                "inline-flex items-center px-2 py-0.5 rounded-md text-[11px] "
                "font-mono font-semibold bg-white text-slate-800 border "
                "border-emerald-200 shrink-0"
            ),
        ),
        Span(
            cat_display,
            cls="text-[11px] text-slate-500 truncate hidden md:inline",
        )
        if cat_display
        else "",
        id="item-classification-summary",
        cls=(
            "flex items-center gap-2 p-2.5 bg-emerald-50 rounded-lg "
            "border border-emerald-200"
        ),
    )


def _classification_hidden_inputs(
    hsn_code: str,
    hsn_category: str,
    isic_code: str,
    isic_category: str,
) -> Div:
    return Div(
        Hidden(name="hsn_code", value=hsn_code or "", id="item-hsn-code"),
        Hidden(
            name="hsn_category",
            value=hsn_category or "",
            id="item-hsn-category",
        ),
        Hidden(name="isic_code", value=isic_code or "", id="item-isic-code"),
        Hidden(
            name="isic_category",
            value=isic_category or "",
            id="item-isic-category",
        ),
        id="item-classification-hidden",
    )


def _classification_hit_row(hit: dict) -> Button:
    kind = hit.get("kind", "product")
    code = hit.get("code", "")
    label = hit.get("label", "")
    category = hit.get("category", "") or label
    badge_cls = (
        "bg-indigo-100 text-indigo-700"
        if kind == "product"
        else "bg-purple-100 text-purple-700"
    )
    code_prefix = "HS" if kind == "product" else "ISIC"
    import json as _json

    return Button(
        Div(
            Div(
                Span(
                    "Product" if kind == "product" else "Service",
                    cls=(
                        f"inline-flex items-center px-2 py-0.5 rounded-full "
                        f"text-[10px] font-semibold uppercase tracking-wider "
                        f"w-fit shrink-0 {badge_cls}"
                    ),
                ),
                P(
                    label,
                    cls="text-sm text-slate-900 text-left whitespace-normal break-words",
                ),
                cls="flex items-start gap-2 min-w-0",
            ),
            P(
                f"{code_prefix} {code}"
                + (f" · {category}" if category and category != label else ""),
                cls="text-xs text-slate-500 font-mono text-left mt-1 whitespace-normal break-words",
            ),
            cls="min-w-0 w-full",
        ),
        type="button",
        hx_get="/items/classification/apply",
        hx_vals=_json.dumps(
            {
                "kind": kind,
                "code": code,
                "label": label,
                "category": category,
            }
        ),
        hx_target="#item-classification-block",
        hx_swap="outerHTML",
        cls=(
            "w-full px-3 py-3 hover:bg-indigo-50 border-b border-slate-100 "
            "last:border-b-0 text-left transition-colors cursor-pointer block"
        ),
    )


def _classification_block(
    *,
    hsn_code: str = "",
    hsn_category: str = "",
    isic_code: str = "",
    isic_category: str = "",
    lookup_query: str = "",
    lookup_hits: list[dict] | None = None,
) -> Div:
    lookup_hits = lookup_hits or []
    if lookup_query:
        if lookup_hits:
            results = Div(
                *[_classification_hit_row(h) for h in lookup_hits],
                id="item-lookup-results",
                cls=(
                    "mt-2 max-h-72 overflow-auto rounded-lg border "
                    "border-slate-200 bg-white shadow-xs animate-fade-in-up"
                ),
            )
        else:
            results = Div(
                P(
                    "No matching products or services found. Try a broader term.",
                    cls="text-xs text-slate-500 px-3 py-3",
                ),
                id="item-lookup-results",
                cls="mt-2 rounded-lg border border-slate-200 bg-slate-50/60",
            )
    else:
        results = Div(id="item-lookup-results")

    return Div(
        _classification_hidden_inputs(
            hsn_code, hsn_category, isic_code, isic_category
        ),
        _selected_classification_summary(
            hsn_code, hsn_category, isic_code, isic_category
        ),
        Div(
            Div(
                icon(
                    "search",
                    cls="h-4 w-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none",
                ),
                Input(
                    type="search",
                    name="classification_q",
                    placeholder="Search HS codes (products) or ISIC codes (services)…",
                    value=lookup_query,
                    autocomplete="off",
                    hx_get="/items/classification/search",
                    hx_trigger="keyup changed delay:400ms, search",
                    hx_target="#item-lookup-results",
                    hx_swap="outerHTML",
                    cls=(
                        "w-full pl-9 pr-3 py-2 bg-white text-slate-900 border "
                        "border-slate-300 rounded-lg text-sm focus:outline-none "
                        "focus:ring-2 focus:ring-indigo-500"
                    ),
                ),
                cls="relative mt-3",
            ),
            guidance_text(
                "Type a keyword (e.g. 'rice', 'consulting') or a code. "
                "Choosing a result attaches exactly one classification — "
                "either HS (product) or ISIC (service)."
            ),
            results,
            cls="",
        ),
        id="item-classification-block",
    )


# ---------------------------------------------------------------------------
# Item form
# ---------------------------------------------------------------------------


def _item_form(
    *,
    item: dict | None = None,
    error: str | None = None,
) -> Div:
    item = item or {}
    is_edit = bool(item.get("id"))
    action = f"/items/{item['id']}-htmx" if is_edit else "/items-htmx"

    body_children = []
    if error:
        body_children.append(alert("error", error, cls="mb-3"))

    body_children.append(
        _classification_block(
            hsn_code=item.get("hsn_code", "") or "",
            hsn_category=item.get("hsn_category", "") or "",
            isic_code=item.get("isic_code", "") or "",
            isic_category=item.get("isic_category", "") or "",
        )
    )

    field_children = []
    for name, label, ftype, placeholder, required, helper in ITEM_TEXT_FIELDS:
        raw_val = item.get(name, "")
        if name == "unit_price" and raw_val not in (None, ""):
            try:
                raw_val = f"{float(raw_val):.2f}"
            except (TypeError, ValueError):
                raw_val = str(raw_val)
        input_kwargs = {}
        if ftype == "number":
            input_kwargs["step"] = "0.01"
            input_kwargs["min"] = "0"
        field_children.append(
            text_field(
                name=name,
                label=label,
                type=ftype,
                placeholder=placeholder,
                value=str(raw_val or ""),
                required=required,
                helper=helper or "",
                **input_kwargs,
            )
        )

    body_children.append(
        Div(
            *field_children,
            cls="grid grid-cols-1 md:grid-cols-2 gap-x-4 mt-5",
        )
    )
    body_children.append(
        guidance_panel(
            "SKUs must be unique per business. When you add an invoice line "
            "you can search this catalog by SKU or name and the classification, "
            "price, and unit are copied in automatically.",
            title="Reusable on invoices",
            cls="mt-1",
        )
    )

    footer = Div(
        Button(
            "Cancel",
            type="button",
            hx_get="/items/clear-overlay",
            hx_target="#item-modal-area",
            hx_swap="innerHTML",
            cls=(
                "px-4 py-2 bg-white border border-slate-300 text-slate-700 "
                "text-sm font-medium rounded-lg hover:bg-slate-50"
            ),
        ),
        primary_button(
            "Update item" if is_edit else "Save item",
            type="submit",
            icon_name="check-circle",
        ),
        cls="flex justify-end gap-2",
    )

    form_body = Form(
        *body_children,
        Div(footer, cls="mt-6"),
        method="post",
        action=action,
        hx_post=action,
        hx_target="#item-list-container",
        hx_swap="outerHTML",
    )

    return modal_shell(
        title="Edit item" if is_edit else "New item / service",
        subtitle=(
            "Update this reusable item — changes affect future invoices only."
            if is_edit
            else "Create a reusable product or service you can add to invoices."
        ),
        content=form_body,
    )


# ---------------------------------------------------------------------------
# Import UI
# ---------------------------------------------------------------------------


def _import_overlay(
    result: dict | None = None,
    error: str | None = None,
) -> Div:
    body_children: list = []
    if error:
        body_children.append(alert("error", error, cls="mb-4"))

    if result:
        errors_list = result.get("errors") or []
        summary_children = [
            Div(
                Span(
                    "Created",
                    cls="text-xs font-semibold text-slate-500 uppercase tracking-wider",
                ),
                Span(
                    result.get("created", 0),
                    cls="text-2xl font-bold text-emerald-600 mt-1",
                ),
                cls=(
                    "flex flex-col p-4 bg-emerald-50 rounded-lg border "
                    "border-emerald-200"
                ),
            ),
            Div(
                Span(
                    "Updated",
                    cls="text-xs font-semibold text-slate-500 uppercase tracking-wider",
                ),
                Span(
                    result.get("updated", 0),
                    cls="text-2xl font-bold text-indigo-600 mt-1",
                ),
                cls=(
                    "flex flex-col p-4 bg-indigo-50 rounded-lg border "
                    "border-indigo-200"
                ),
            ),
            Div(
                Span(
                    "Skipped",
                    cls="text-xs font-semibold text-slate-500 uppercase tracking-wider",
                ),
                Span(
                    result.get("skipped", 0),
                    cls=(
                        "text-2xl font-bold mt-1 "
                        + (
                            "text-amber-600"
                            if result.get("skipped", 0)
                            else "text-slate-500"
                        )
                    ),
                ),
                cls=(
                    "flex flex-col p-4 bg-white rounded-lg border border-slate-200"
                ),
            ),
            Div(
                Span(
                    "Total rows",
                    cls="text-xs font-semibold text-slate-500 uppercase tracking-wider",
                ),
                Span(
                    result.get("total_rows", 0),
                    cls="text-2xl font-bold text-slate-900 mt-1",
                ),
                cls=(
                    "flex flex-col p-4 bg-white rounded-lg border border-slate-200"
                ),
            ),
        ]
        body_children.append(
            Div(
                *summary_children,
                cls="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5",
            )
        )

        if errors_list:
            err_rows = []
            for e in errors_list[:50]:
                err_rows.append(
                    Div(
                        Span(
                            f"Row {e.get('row', '?')}",
                            cls=(
                                "inline-flex items-center px-2 py-0.5 "
                                "rounded-md text-[11px] font-mono font-semibold "
                                "bg-rose-100 text-rose-700 shrink-0"
                            ),
                        ),
                        Span(
                            e.get("sku") or "—",
                            cls=(
                                "inline-flex items-center px-2 py-0.5 rounded-md "
                                "text-[11px] font-mono bg-slate-100 text-slate-700 shrink-0"
                            ),
                        ),
                        Span(
                            e.get("error", ""),
                            cls="text-xs text-slate-700 flex-1 min-w-0",
                        ),
                        cls=(
                            "flex items-start gap-2 px-3 py-2 border-b "
                            "border-slate-100 last:border-b-0"
                        ),
                    )
                )
            body_children.append(
                Div(
                    Div(
                        icon("alert-triangle", cls="h-4 w-4 text-rose-500"),
                        Span(
                            f"{len(errors_list)} row(s) had validation errors",
                            cls="text-sm font-semibold text-slate-900",
                        ),
                        cls="flex items-center gap-2 px-3 py-2 border-b border-slate-200 bg-slate-50",
                    ),
                    Div(
                        *err_rows,
                        cls="max-h-60 overflow-auto",
                    ),
                    cls="rounded-lg border border-slate-200 bg-white mb-4",
                )
            )
        else:
            body_children.append(
                alert(
                    "success",
                    "All rows imported successfully.",
                    cls="mb-4",
                )
            )

    body_children.append(
        Form(
            guidance_panel(
                "Upload a .csv or .xlsx file. The header row must include at "
                "least 'sku' and 'name'. Each row must have exactly one of "
                "'hsn_code' (product) or 'isic_code' (service). Optional columns: "
                "description, hsn_category, isic_category, unit_price, price_unit.",
                title="File format",
                icon_name="info",
                cls="mb-4",
            ),
            Label(
                "Choose CSV or Excel file",
                fr="import-file",
                cls="block text-sm font-medium text-slate-700 mb-1.5",
            ),
            Input(
                id="import-file",
                type="file",
                name="file",
                accept=".csv,.xlsx",
                required=True,
                cls=(
                    "block w-full text-sm text-slate-600 "
                    "file:mr-3 file:py-2 file:px-4 file:rounded-lg "
                    "file:border-0 file:text-sm file:font-semibold "
                    "file:bg-indigo-50 file:text-indigo-700 "
                    "hover:file:bg-indigo-100 cursor-pointer"
                ),
            ),
            guidance_text(
                "Existing items with the same SKU will be updated. "
                "New SKUs will be created."
            ),
            Div(
                Div(
                    icon("loader", cls="h-4 w-4 text-indigo-600 animate-spin"),
                    Span(
                        "Importing your file\u2026 large files can take up to a minute.",
                        cls="text-xs text-indigo-700",
                    ),
                    id="item-import-spinner",
                    cls=(
                        "htmx-indicator flex items-center gap-2 mt-4 p-2.5 "
                        "bg-indigo-50 border border-indigo-200 rounded-lg"
                    ),
                ),
                Div(
                    Button(
                        Span("Close"),
                        type="button",
                        hx_get="/items/clear-overlay",
                        hx_target="#item-modal-area",
                        hx_swap="innerHTML",
                        cls=(
                            "px-4 py-2 bg-white border border-slate-300 text-slate-700 "
                            "text-sm font-medium rounded-lg hover:bg-slate-50"
                        ),
                    ),
                    Button(
                        Span(
                            icon("download", cls="h-4 w-4"),
                            Span("Upload & import"),
                            cls="zefe-busy-label inline-flex items-center gap-2",
                        ),
                        Span(
                            icon("loader", cls="h-4 w-4"),
                            cls="zefe-busy-spinner",
                        ),
                        type="submit",
                        data_zefe_busy="1",
                        cls=(
                            "inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 "
                            "text-white font-medium text-sm rounded-lg "
                            "hover:bg-indigo-700 disabled:opacity-50 "
                            "disabled:cursor-not-allowed"
                        ),
                    ),
                    cls="flex justify-end gap-2 mt-6",
                ),
            ),
            method="post",
            action="/items/import",
            enctype="multipart/form-data",
            hx_post="/items/import",
            hx_encoding="multipart/form-data",
            hx_target="#item-modal-area",
            hx_swap="innerHTML",
            hx_indicator="#item-import-spinner",
        )
    )

    return modal_shell(
        title="Import items from CSV / Excel",
        subtitle="Bulk-load your product & service catalog in one upload.",
        content=Div(*body_children),
    )


# ---------------------------------------------------------------------------
# Pagination helper
# ---------------------------------------------------------------------------


def _pagination(page: int, total_pages: int, q: str, kind: str = "") -> Div:
    return pagination_controls(
        page,
        total_pages,
        q,
        "/items",
        "#item-list-container",
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


def _parse_payload(form) -> dict:
    payload: dict = {}
    for name, _, ftype, _, _, _ in ITEM_TEXT_FIELDS:
        raw = (form.get(name) or "").strip()
        if ftype == "number":
            if raw == "":
                payload[name] = None
            else:
                try:
                    payload[name] = float(raw)
                except ValueError:
                    payload[name] = raw  # let backend reject
        else:
            payload[name] = raw or (
                None if name != "sku" and name != "name" else ""
            )
    # Classification hidden fields
    payload["hsn_code"] = (form.get("hsn_code") or "").strip() or None
    payload["hsn_category"] = (form.get("hsn_category") or "").strip() or None
    payload["isic_code"] = (form.get("isic_code") or "").strip() or None
    payload["isic_category"] = (form.get("isic_category") or "").strip() or None
    # Ensure required strings aren't None
    for req in ("sku", "name"):
        if payload.get(req) in (None, ""):
            payload[req] = ""
    return payload


def register_routes(rt) -> None:
    @rt("/items", methods=["GET"])
    async def list_items_page(
        req: Request,
        q: str = "",
        kind: str = "",
        page: int = 1,
        error: str = "",
        success: str = "",
    ):
        redirect = require_session(req)
        if redirect:
            return redirect
        jwt = current_jwt(req)
        sid = get_session_id(req)
        items: list[dict] = []
        total_items = 0
        limit = 10
        try:
            page_int = max(1, int(page))
        except (TypeError, ValueError):
            page_int = 1
        offset = (page_int - 1) * limit
        load_error = ""
        try:
            result = await api_client.list_items(
                jwt,
                session_id=sid,
                search=q or None,
                kind=kind or None,
                offset=offset,
                limit=limit,
            )
            items = result.get("items", [])
            total_items = result.get("total", 0)
        except api_client.APIError as e:
            logger.exception("list_items failed")
            load_error = (
                e.detail
                if isinstance(e.detail, str)
                else "Failed to load items."
            )
        except Exception:
            logger.exception("list_items transport error")
            load_error = "Backend service unavailable."

        total_pages = max(1, (total_items + limit - 1) // limit)

        is_htmx = req.headers.get("HX-Request") == "true"
        if is_htmx:
            return Div(
                _bulk_action_bar(),
                _item_table(items),
                _pagination(page_int, total_pages, q, kind),
                Script(_ITEMS_JS),
                id="item-list-container",
            )

        header = Div(
            Div(
                H2("Items & Services", cls="text-2xl font-bold text-slate-900"),
                P(
                    f"{total_items} item(s) in your catalog",
                    cls="text-sm text-slate-500 mt-1",
                ),
            ),
            Div(
                Button(
                    icon("download", cls="h-4 w-4"),
                    Span("Import CSV / Excel"),
                    hx_get="/items/import-overlay",
                    hx_target="#item-modal-area",
                    cls=(
                        "inline-flex items-center gap-2 px-4 py-2 bg-white "
                        "border border-slate-300 text-slate-700 text-sm font-medium "
                        "rounded-lg hover:bg-slate-50"
                    ),
                ),
                Button(
                    icon("plus", cls="h-4 w-4"),
                    Span("Add item"),
                    hx_get="/items/new-overlay",
                    hx_target="#item-modal-area",
                    cls=(
                        "inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 "
                        "text-white text-sm font-medium rounded-lg hover:bg-indigo-700"
                    ),
                ),
                cls="flex items-center gap-2",
            ),
            cls="flex items-center justify-between gap-4 mb-6 flex-wrap",
        )

        kind_options = [
            ("", "All kinds"),
            ("product", "Products (HS)"),
            ("service", "Services (ISIC)"),
        ]
        kind_select = Select(
            *[
                Option(lbl, value=val, selected=(val == kind))
                for val, lbl in kind_options
            ],
            name="kind",
            hx_get="/items",
            hx_trigger="change",
            hx_target="#item-list-container",
            hx_swap="innerHTML",
            hx_include="[name='q']",
            hx_push_url="true",
            cls=(
                "appearance-none px-3 py-2 pr-9 bg-white text-slate-900 border "
                "border-slate-300 rounded-lg text-sm focus:outline-none "
                "focus:ring-2 focus:ring-indigo-500"
            ),
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
                    placeholder="Search by SKU, name, description…",
                    value=q,
                    autocomplete="off",
                    hx_get="/items",
                    hx_trigger="keyup changed delay:300ms, search, change",
                    hx_target="#item-list-container",
                    hx_swap="innerHTML",
                    hx_include="[name='kind']",
                    hx_push_url="true",
                    cls=(
                        "w-full pl-9 pr-3 py-2 bg-white text-slate-900 border "
                        "border-slate-300 rounded-lg text-sm focus:outline-none "
                        "focus:ring-2 focus:ring-indigo-500"
                    ),
                ),
                cls="relative flex-1 min-w-0",
            ),
            Div(
                kind_select,
                icon(
                    "chevron-down",
                    cls=(
                        "h-4 w-4 text-slate-400 absolute right-3 top-1/2 "
                        "-translate-y-1/2 pointer-events-none"
                    ),
                ),
                cls="relative shrink-0",
            ),
            Hidden(name="page", value="1"),
        ]
        if q or kind:
            search_inputs.append(
                A(
                    icon("x", cls="h-4 w-4"),
                    Span("Clear"),
                    href="/items",
                    cls=(
                        "inline-flex items-center gap-1.5 px-3 py-2 text-sm "
                        "font-medium text-slate-600 hover:text-slate-900 shrink-0"
                    ),
                )
            )
        search = Form(
            Div(*search_inputs, cls="flex items-center gap-2 max-w-2xl"),
            method="get",
            action="/items",
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
            _item_table(items),
            _pagination(page_int, total_pages, q, kind),
            Script(_ITEMS_JS),
            id="item-list-container",
        )

        return app_shell(
            "Items & Services",
            header,
            *banners,
            search,
            list_container,
            Div(id="item-modal-area"),
            active_nav="items",
            username=current_username(req),
            business_id=current_business_id(req),
        )

    @rt("/items/clear-overlay", methods=["GET"])
    def clear_overlay(req: Request):
        return HTMLResponse("")

    @rt("/items/new-overlay", methods=["GET"])
    async def new_overlay(req: Request):
        redirect = require_session(req)
        if redirect:
            return redirect
        return _item_form(item={"price_unit": "NGN per 1"})

    @rt("/items/{iid}/edit-overlay", methods=["GET"])
    async def edit_overlay(req: Request, iid: int):
        redirect = require_session(req)
        if redirect:
            return redirect
        jwt = current_jwt(req)
        sid = get_session_id(req)
        try:
            item = await api_client.get_item(jwt, iid, session_id=sid)
        except Exception:
            logger.exception("edit_overlay: get_item failed")
            return HTMLResponse("")
        return _item_form(item=item)

    @rt("/items/{iid}/delete-overlay", methods=["GET"])
    async def delete_overlay(req: Request, iid: int):
        redirect = require_session(req)
        if redirect:
            return redirect
        jwt = current_jwt(req)
        sid = get_session_id(req)
        try:
            item = await api_client.get_item(jwt, iid, session_id=sid)
        except Exception:
            logger.exception("delete_overlay: get_item failed")
            return HTMLResponse("")
        confirm_btn = Form(
            Button(
                Span("Delete item"),
                type="submit",
                cls=(
                    "px-4 py-2 bg-rose-600 text-white text-sm font-medium "
                    "rounded-lg hover:bg-rose-700"
                ),
            ),
            hx_post=f"/items/{iid}/delete-htmx",
            hx_target="#item-list-container",
            hx_swap="outerHTML",
            cls="inline",
        )
        # Reuse the customer confirm_modal — the cancel handler points at
        # /customers/clear-overlay which returns an empty HTMLResponse. We
        # want ours to hit /items/clear-overlay instead, so build inline.
        return Div(
            Div(
                Div(
                    Div(
                        Div(
                            icon("alert-triangle", cls="h-6 w-6 text-rose-600"),
                            cls=(
                                "h-12 w-12 rounded-full bg-rose-100 flex "
                                "items-center justify-center mb-4 mx-auto"
                            ),
                        ),
                        H3(
                            "Delete this item?",
                            cls="text-lg font-bold text-slate-950 text-center",
                        ),
                        P(
                            f"You are about to permanently delete "
                            f"“{item.get('sku', '')} · {item.get('name', '')}”. "
                            "Existing invoices are unaffected.",
                            cls="text-sm text-slate-600 text-center mt-2",
                        ),
                        cls="p-6",
                    ),
                    Div(
                        Button(
                            Span("Cancel"),
                            hx_get="/items/clear-overlay",
                            hx_target="#item-modal-area",
                            hx_swap="innerHTML",
                            type="button",
                            cls=(
                                "px-4 py-2 bg-white border border-slate-300 "
                                "text-slate-700 text-sm font-medium rounded-lg "
                                "hover:bg-slate-50"
                            ),
                        ),
                        confirm_btn,
                        cls=(
                            "flex items-center justify-end gap-2 px-6 py-4 "
                            "border-t border-slate-200 bg-slate-50 rounded-b-2xl"
                        ),
                    ),
                    cls=(
                        "bg-white border border-slate-200 rounded-2xl "
                        "max-w-md w-full shadow-lg relative z-50 animate-fade-in-up"
                    ),
                ),
                cls=(
                    "fixed inset-0 z-40 flex items-center justify-center "
                    "bg-slate-900/40 backdrop-blur-xs p-4"
                ),
            )
        )

    async def _reload_list(
        jwt: str, sid: str, page_int: int = 1, q: str = "", kind: str = ""
    ) -> tuple[list, int, int]:
        limit = 10
        offset = (page_int - 1) * limit
        try:
            result = await api_client.list_items(
                jwt,
                session_id=sid,
                search=q or None,
                kind=kind or None,
                offset=offset,
                limit=limit,
            )
            items = result.get("items", [])
            total_items = result.get("total", 0)
        except Exception:
            logger.exception("_reload_list failed")
            items = []
            total_items = 0
        total_pages = max(1, (total_items + limit - 1) // limit)
        return items, total_items, total_pages

    @rt("/items-htmx", methods=["POST"])
    async def create_htmx(req: Request):
        redirect = require_session(req)
        if redirect:
            return redirect
        form = await req.form()
        payload = _parse_payload(form)
        jwt = current_jwt(req)
        sid = get_session_id(req)
        try:
            await api_client.create_item(jwt, payload, session_id=sid)
        except api_client.APIError as e:
            logger.exception("create_item failed")
            detail = (
                e.detail
                if isinstance(e.detail, str)
                else "Could not save item — please review the fields."
            )
            return _item_form(item=payload, error=str(detail))
        except Exception:
            logger.exception("create_item transport error")
            return _item_form(
                item=payload, error="Backend service unavailable. Try again."
            )
        items, _, total_pages = await _reload_list(jwt, sid)
        return Div(
            alert("success", "Item created successfully."),
            _bulk_action_bar(),
            _item_table(items),
            _pagination(1, total_pages, "", ""),
            Div(id="item-modal-area", hx_swap_oob="innerHTML"),
            Script(_ITEMS_JS),
            id="item-list-container",
        )

    @rt("/items/{iid}-htmx", methods=["POST"])
    async def update_htmx(req: Request, iid: int):
        redirect = require_session(req)
        if redirect:
            return redirect
        form = await req.form()
        payload = _parse_payload(form)
        jwt = current_jwt(req)
        sid = get_session_id(req)
        try:
            await api_client.update_item(jwt, iid, payload, session_id=sid)
        except api_client.APIError as e:
            logger.exception("update_item failed")
            detail = (
                e.detail
                if isinstance(e.detail, str)
                else "Could not update item."
            )
            payload_with_id = {**payload, "id": iid}
            return _item_form(item=payload_with_id, error=str(detail))
        except Exception:
            logger.exception("update_item transport error")
            return _item_form(
                item={**payload, "id": iid},
                error="Backend service unavailable. Try again.",
            )
        items, _, total_pages = await _reload_list(jwt, sid)
        return Div(
            alert("success", "Item updated successfully."),
            _bulk_action_bar(),
            _item_table(items),
            _pagination(1, total_pages, "", ""),
            Div(id="item-modal-area", hx_swap_oob="innerHTML"),
            Script(_ITEMS_JS),
            id="item-list-container",
        )

    @rt("/items/{iid}/delete-htmx", methods=["POST"])
    async def delete_htmx(req: Request, iid: int):
        redirect = require_session(req)
        if redirect:
            return redirect
        jwt = current_jwt(req)
        sid = get_session_id(req)
        success_msg = ""
        err_msg = ""
        try:
            await api_client.delete_item(jwt, iid, session_id=sid)
            success_msg = "Item deleted."
        except api_client.APIError as e:
            logger.exception("delete_item failed")
            err_msg = (
                e.detail if isinstance(e.detail, str) else "Delete failed."
            )
        except Exception:
            logger.exception("delete_item transport error")
            err_msg = "Backend service unavailable."
        items, _, total_pages = await _reload_list(jwt, sid)
        banner = (
            alert("success", success_msg)
            if success_msg
            else (alert("error", err_msg) if err_msg else "")
        )
        return Div(
            banner,
            _bulk_action_bar(),
            _item_table(items),
            _pagination(1, total_pages, "", ""),
            Div(id="item-modal-area", hx_swap_oob="innerHTML"),
            Script(_ITEMS_JS),
            id="item-list-container",
        )

    @rt("/items/bulk-delete-confirm", methods=["GET"])
    async def bulk_delete_confirm(
        req: Request,
        ids: str = "",
        q: str = "",
        kind: str = "",
        page: int = 1,
    ):
        redirect = require_session(req)
        if redirect:
            return redirect
        id_list = [s.strip() for s in (ids or "").split(",") if s.strip()]
        if not id_list:
            return HTMLResponse(
                '<div class="fixed inset-0 z-40 flex items-center justify-center '
                'bg-slate-900/40 backdrop-blur-xs p-4">'
                '<div class="bg-white border border-slate-200 rounded-2xl max-w-md '
                'w-full p-6 shadow-lg">'
                '<p class="text-sm text-slate-700">Please select at least one item.</p>'
                '<div class="flex justify-end mt-4">'
                '<button hx-get="/items/clear-overlay" hx-target="#item-modal-area" '
                'hx-swap="innerHTML" class="px-4 py-2 bg-white border border-slate-300 '
                'text-slate-700 text-sm font-medium rounded-lg hover:bg-slate-50">'
                "Close</button></div></div></div>"
            )

        count = len(id_list)
        plural = "item" if count == 1 else "items"

        confirm_btn = Form(
            Hidden(name="ids", value=",".join(id_list)),
            Hidden(name="q", value=q),
            Hidden(name="kind", value=kind),
            Hidden(name="page", value=str(page)),
            Button(
                Span(f"Delete {count} {plural}"),
                type="submit",
                cls=(
                    "px-4 py-2 bg-rose-600 text-white text-sm font-medium "
                    "rounded-lg hover:bg-rose-700"
                ),
            ),
            hx_post="/items/bulk-delete-htmx",
            hx_target="#item-list-container",
            hx_swap="outerHTML",
            cls="inline",
        )

        return Div(
            Div(
                Div(
                    Div(
                        Div(
                            icon("alert-triangle", cls="h-6 w-6 text-rose-600"),
                            cls=(
                                "h-12 w-12 rounded-full bg-rose-100 flex "
                                "items-center justify-center mb-4 mx-auto"
                            ),
                        ),
                        H3(
                            f"Delete {count} {plural}?",
                            cls="text-lg font-bold text-slate-950 text-center",
                        ),
                        P(
                            f"You are about to permanently delete {count} {plural} "
                            "from your catalog. Existing invoices are unaffected.",
                            cls="text-sm text-slate-600 text-center mt-2",
                        ),
                        cls="p-6",
                    ),
                    Div(
                        Button(
                            Span("Cancel"),
                            hx_get="/items/clear-overlay",
                            hx_target="#item-modal-area",
                            hx_swap="innerHTML",
                            type="button",
                            cls=(
                                "px-4 py-2 bg-white border border-slate-300 "
                                "text-slate-700 text-sm font-medium rounded-lg "
                                "hover:bg-slate-50"
                            ),
                        ),
                        confirm_btn,
                        cls=(
                            "flex items-center justify-end gap-2 px-6 py-4 "
                            "border-t border-slate-200 bg-slate-50 rounded-b-2xl"
                        ),
                    ),
                    cls=(
                        "bg-white border border-slate-200 rounded-2xl "
                        "max-w-md w-full shadow-lg animate-fade-in-up"
                    ),
                ),
                cls=(
                    "fixed inset-0 z-40 flex items-center justify-center "
                    "bg-slate-900/40 backdrop-blur-xs p-4"
                ),
            )
        )

    @rt("/items/bulk-delete-htmx", methods=["POST"])
    async def bulk_delete_htmx(req: Request):
        redirect = require_session(req)
        if redirect:
            return redirect
        form = await req.form()
        ids = (form.get("ids") or "").strip()
        q = (form.get("q") or "").strip()
        kind = (form.get("kind") or "").strip()
        try:
            page_int = int(form.get("page") or 1)
        except (TypeError, ValueError):
            page_int = 1

        int_ids: list[int] = []
        for raw in [s.strip() for s in ids.split(",") if s.strip()]:
            try:
                int_ids.append(int(raw))
            except ValueError:
                continue
        jwt = current_jwt(req)
        sid = get_session_id(req)
        deleted = 0
        try:
            if int_ids:
                res = await api_client.bulk_delete_items(
                    jwt, int_ids, session_id=sid
                )
                deleted = int(res.get("deleted", 0))
        except Exception:
            logger.exception("bulk_delete_items failed")

        items, total_items, total_pages = await _reload_list(
            jwt, sid, page_int=page_int, q=q, kind=kind
        )
        if not items and page_int > 1:
            page_int -= 1
            items, total_items, total_pages = await _reload_list(
                jwt, sid, page_int=page_int, q=q, kind=kind
            )
        return Div(
            alert("success", f"Deleted {deleted} item(s)."),
            _bulk_action_bar(),
            _item_table(items),
            _pagination(page_int, total_pages, q, kind),
            Div(id="item-modal-area", hx_swap_oob="innerHTML"),
            Script(_ITEMS_JS),
            id="item-list-container",
        )

    # -------------------- Classification search ---------------------

    @rt("/items/classification/search", methods=["GET"])
    async def classification_search(req: Request, classification_q: str = ""):
        redirect = require_session(req)
        if redirect:
            return redirect
        q = (classification_q or "").strip()
        if len(q) < 2:
            return Div(id="item-lookup-results")
        jwt = current_jwt(req)
        sid = get_session_id(req)

        async def _prods():
            try:
                return await api_client.search_products(
                    jwt, q, length=15, session_id=sid
                )
            except Exception:
                logger.exception("classification_search: products failed")
                return []

        async def _servs():
            try:
                return await api_client.search_services(
                    jwt, q, length=15, session_id=sid
                )
            except Exception:
                logger.exception("classification_search: services failed")
                return []

        prods, servs = await asyncio.gather(_prods(), _servs())
        merged: list[dict] = []
        for p in prods or []:
            if not isinstance(p, dict):
                continue
            code = str(p.get("hscode") or p.get("code") or "").strip()
            if not code:
                continue
            label = str(p.get("description") or p.get("label") or "").strip()
            category = str(
                p.get("product_category") or p.get("category") or label
            ).strip()
            merged.append(
                {
                    "kind": "product",
                    "code": code,
                    "label": label,
                    "category": category,
                }
            )
        for s in servs or []:
            if not isinstance(s, dict):
                continue
            code = str(s.get("code") or "").strip()
            if not code:
                continue
            label = str(s.get("description") or s.get("label") or "").strip()
            category = str(s.get("category") or label).strip()
            merged.append(
                {
                    "kind": "service",
                    "code": code,
                    "label": label,
                    "category": category,
                }
            )
        # Simple relevance: prefer prefix match on code/label
        ql = q.lower()

        def _score(h):
            lbl = (h.get("label") or "").lower()
            code = (h.get("code") or "").lower()
            s = 0
            if code == ql or lbl == ql:
                s += 100
            if lbl.startswith(ql):
                s += 20
            if ql in lbl:
                s += 10
            if ql.replace(" ", "") in code:
                s += 6
            return -s

        merged.sort(key=_score)
        if not merged[:20]:
            return Div(
                P(
                    f"No matching products or services found for “{q}”.",
                    cls="text-xs text-slate-500 px-3 py-3 text-center",
                ),
                id="item-lookup-results",
                cls="mt-2 rounded-lg border border-slate-200 bg-slate-50/60",
            )
        return Div(
            *[_classification_hit_row(h) for h in merged[:20]],
            id="item-lookup-results",
            cls=(
                "mt-2 max-h-72 overflow-auto rounded-lg border border-slate-200 "
                "bg-white shadow-xs animate-fade-in-up"
            ),
        )

    @rt("/items/classification/apply", methods=["GET"])
    async def classification_apply(
        req: Request,
        kind: str = "product",
        code: str = "",
        label: str = "",
        category: str = "",
    ):
        redirect = require_session(req)
        if redirect:
            return redirect
        kind = (kind or "product").strip()
        code = (code or "").strip()
        label = (label or "").strip()
        category = (category or "").strip() or label
        if kind == "product":
            return _classification_block(
                hsn_code=code,
                hsn_category=category,
                isic_code="",
                isic_category="",
            )
        return _classification_block(
            hsn_code="",
            hsn_category="",
            isic_code=code,
            isic_category=category,
        )

    # -------------------- Import -----------------------------------

    @rt("/items/import-overlay", methods=["GET"])
    async def import_overlay(req: Request):
        redirect = require_session(req)
        if redirect:
            return redirect
        return _import_overlay()

    @rt("/items/import", methods=["POST"])
    async def import_submit(req: Request):
        redirect = require_session(req)
        if redirect:
            return redirect
        form = await req.form()
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            return _import_overlay(
                error="Please choose a CSV or Excel file to upload."
            )
        filename = getattr(upload, "filename", "upload") or "upload"
        content_type = (
            getattr(upload, "content_type", None) or "application/octet-stream"
        )
        try:
            content = await upload.read()
        except Exception:
            logger.exception("import_submit: read upload failed")
            return _import_overlay(error="Could not read the uploaded file.")

        if not content:
            return _import_overlay(error="Uploaded file was empty.")
        if len(content) > 10 * 1024 * 1024:
            return _import_overlay(error="File is too large — maximum 10 MiB.")

        jwt = current_jwt(req)
        sid = get_session_id(req)
        try:
            result = await api_client.import_items(
                jwt, filename, content, content_type, session_id=sid
            )
        except api_client.APIError as e:
            logger.exception("import_items api error")
            detail = (
                e.detail
                if isinstance(e.detail, str)
                else "Import failed. Please check your file and try again."
            )
            return _import_overlay(error=str(detail))
        except Exception:
            logger.exception("import_items transport error")
            return _import_overlay(
                error="Backend service unavailable. Please retry shortly."
            )

        # Return combined swap: the result overlay AND a refreshed table.
        items, _, total_pages = await _reload_list(jwt, sid)
        overlay = _import_overlay(result=result)
        return Div(
            overlay,
            Div(
                _bulk_action_bar(),
                _item_table(items),
                _pagination(1, total_pages, "", ""),
                Script(_ITEMS_JS),
                id="item-list-container",
                hx_swap_oob="outerHTML",
            ),
        )
