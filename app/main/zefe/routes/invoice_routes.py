from __future__ import annotations

import logging
import re
from typing import Optional

from fasthtml.common import (
    A,
    Button,
    Div,
    Form,
    H2,
    H3,
    Hidden,
    Img,
    Input,
    Label,
    Option,
    P,
    RedirectResponse,
    Script,
    Select,
    Span,
    Table,
    Tbody,
    Td,
    Th,
    Thead,
    Tr,
)
from starlette.requests import Request
from starlette.responses import Response

from deps import (
    current_business_id,
    current_jwt,
    current_username,
    get_session_id,
    require_session,
)
from services import api_client
from services.pdf_service import build_invoice_pdf
from services.errors import extract_api_error_detail
from ui.components import (
    alert,
    card,
    pagination_controls,
    primary_button,
)
from ui.icons import icon
from ui.layout import app_shell

logger = logging.getLogger(__name__)


def _status_badge(status: str) -> Span:
    palette = {
        "PAID": "bg-emerald-100 text-emerald-700",
        "PENDING": "bg-amber-100 text-amber-700",
        "REJECTED": "bg-rose-100 text-rose-700",
        "PARTIAL": "bg-sky-100 text-sky-700",
    }
    tooltips = {
        "PENDING": "Pending: Invoice issued but payment has not yet been received.",
        "PAID": "Paid: Payment has been fully received and settled for this invoice.",
        "PARTIAL": "Partial: A portion of the invoice amount has been paid, leaving a remaining balance.",
        "REJECTED": "Rejected: The invoice payment or validity has been rejected or disputed.",
    }
    cls = palette.get(status or "PENDING", "bg-slate-100 text-slate-700")
    tip = tooltips.get(status or "PENDING", "")
    display_status = status or "PENDING"
    return Span(
        f" {display_status} ",
        title=tip,
        cls=f"inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium cursor-help {cls}",
    )


def _transmit_badge(transmitted: bool) -> Span:
    if transmitted:
        return Span(
            "Transmitted",
            cls="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-50 text-emerald-700 border border-emerald-200",
        )
    return Span(
        "Pending",
        cls="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-slate-50 text-slate-600 border border-slate-200",
    )


def _invoice_row(item: dict) -> Tr:
    irn = item.get("irn", "")
    href = f"/invoices/{irn}"
    cell_cls = "px-4 py-3 cursor-pointer"
    return Tr(
        Td(
            Span(
                irn,
                cls="text-sm font-mono text-indigo-600",
            ),
            cls=cell_cls,
            onclick=f"window.location='{href}'",
        ),
        Td(
            item.get("customer_name", ""),
            cls="px-4 py-3 text-sm text-slate-900 max-w-xs truncate cursor-pointer",
            onclick=f"window.location='{href}'",
        ),
        Td(
            item.get("issue_date", ""),
            cls="px-4 py-3 text-sm text-slate-700 whitespace-nowrap cursor-pointer",
            onclick=f"window.location='{href}'",
        ),
        Td(
            f"{item.get('currency', '')} {float(item.get('payable_amount', 0)):.2f}",
            cls="px-4 py-3 text-sm font-medium text-slate-900 text-right whitespace-nowrap cursor-pointer",
            onclick=f"window.location='{href}'",
        ),
        Td(
            _status_badge(item.get("payment_status", "")),
            cls="px-4 py-3 cursor-pointer",
            onclick=f"window.location='{href}'",
        ),
        Td(
            _transmit_badge(bool(item.get("transmitted", False))),
            cls="px-4 py-3 cursor-pointer",
            onclick=f"window.location='{href}'",
        ),
        Td(
            A(
                icon("layout-dashboard", cls="h-4 w-4"),
                href=href,
                title="View",
                onclick="event.stopPropagation();",
                cls="p-2 rounded-lg text-slate-500 hover:bg-slate-100 hover:text-indigo-600",
            ),
            cls="px-4 py-3 text-right",
        ),
        cls="border-b border-slate-100 hover:bg-slate-50 transition-colors",
    )


def _invoice_table(items: list[dict]) -> Div:
    if not items:
        return Div(
            icon("receipt", cls="h-10 w-10 text-slate-300 mx-auto mb-3"),
            P(
                "No invoices found",
                cls="text-base font-semibold text-slate-900",
            ),
            P(
                "Try a different search, or create a new invoice.",
                cls="text-sm text-slate-500 mt-1",
            ),
            cls="text-center py-16 bg-white rounded-2xl border border-slate-200",
            id="invoice-list",
        )
    return Div(
        Table(
            Thead(
                Tr(
                    Th(
                        "IRN",
                        cls="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider",
                    ),
                    Th(
                        "Customer",
                        cls="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider",
                    ),
                    Th(
                        "Date",
                        cls="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider",
                    ),
                    Th(
                        "Amount",
                        cls="px-4 py-3 text-right text-xs font-semibold text-slate-500 uppercase tracking-wider",
                    ),
                    Th(
                        "Status",
                        cls="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider",
                    ),
                    Th(
                        "Transmit",
                        cls="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider",
                    ),
                    Th("", cls="px-4 py-3"),
                    cls="border-b border-slate-200 bg-slate-50",
                ),
            ),
            Tbody(*[_invoice_row(it) for it in items]),
            cls="table-auto w-full",
        ),
        cls="overflow-hidden rounded-2xl border border-slate-200 bg-white",
        id="invoice-list",
    )


def _party_card(title: str, party: dict, icon_name: str) -> Div:
    addr = party.get("postal_address") or {}
    addr_parts = [
        addr.get("street_name", ""),
        addr.get("city_name", ""),
        addr.get("state", ""),
        addr.get("country", ""),
    ]
    address = ", ".join([a for a in addr_parts if a])
    return Div(
        Div(
            icon(icon_name, cls="h-4 w-4 text-indigo-600"),
            P(
                title,
                cls="text-xs uppercase text-slate-500 font-semibold tracking-wider",
            ),
            cls="flex items-center gap-2 mb-3",
        ),
        P(
            party.get("party_name", ""),
            cls="text-sm font-semibold text-slate-900",
        ),
        P(
            f"TIN: {party.get('tin', '')}",
            cls="text-xs font-mono text-slate-600 mt-1",
        )
        if party.get("tin")
        else "",
        P(
            party.get("email", ""),
            cls="text-xs text-slate-600 mt-1",
        )
        if party.get("email")
        else "",
        P(
            party.get("telephone", ""),
            cls="text-xs text-slate-600 mt-1",
        )
        if party.get("telephone")
        else "",
        P(address, cls="text-xs text-slate-500 mt-2") if address else "",
        cls="bg-white border border-slate-200 rounded-xl p-4",
    )


def _line_row(line: dict) -> Tr:
    item = line.get("item") or {}
    price = line.get("price") or {}
    qty = float(line.get("invoiced_quantity", 0) or 0)
    unit = float(price.get("price_amount", 0) or 0)
    total = float(line.get("line_extension_amount", qty * unit) or 0)
    code = line.get("hsn_code") or line.get("isic_code") or ""
    return Tr(
        Td(
            P(
                item.get("name", ""),
                cls="text-sm font-medium text-slate-900",
            ),
            P(
                code,
                cls="text-xs text-slate-500 font-mono",
            )
            if code
            else "",
            cls="px-4 py-3",
        ),
        Td(
            f"{qty:.2f}",
            cls="px-4 py-3 text-sm text-slate-700 text-right",
        ),
        Td(
            f"{unit:.2f}",
            cls="px-4 py-3 text-sm text-slate-700 text-right",
        ),
        Td(
            f"{total:.2f}",
            cls="px-4 py-3 text-sm font-medium text-slate-900 text-right",
        ),
        cls="border-b border-slate-100",
    )


def _pagination_controls(
    page: int,
    total_pages: int,
    q: str,
    base_path: str = "/invoices",
    target_id: str = "#invoice-list-container",
) -> Div:
    return pagination_controls(page, total_pages, q, base_path, target_id)


def _terminal_status_notice(payment_status: str) -> Div:
    upper = (payment_status or "").upper()
    is_paid = upper == "PAID"
    icon_name = "check-circle" if is_paid else "alert-circle"
    accent_text = "text-emerald-700" if is_paid else "text-rose-700"
    accent_icon = "text-emerald-600" if is_paid else "text-rose-600"
    accent_bg = (
        "bg-emerald-50 border-emerald-200"
        if is_paid
        else "bg-rose-50 border-rose-200"
    )
    title = "Payment status: PAID" if is_paid else "Payment status: REJECTED"
    if is_paid:
        body = (
            "This invoice has been fully paid. Per FIRS rules, the payment "
            "status of a paid invoice is final and cannot be changed. To "
            "make a correction or refund, issue a credit note as a new "
            "invoice with a fresh IRN."
        )
    else:
        body = (
            "This invoice has been rejected. Per FIRS rules, the payment "
            "status of a rejected invoice is final and cannot be changed. "
            "To proceed with a corrected invoice, create and submit a new "
            "invoice with a fresh IRN."
        )
    return Div(
        H3(
            "Update payment status",
            cls="text-base font-semibold text-slate-900 mb-3",
        ),
        Div(
            icon(icon_name, cls=f"h-5 w-5 {accent_icon} shrink-0 mt-0.5"),
            Div(
                P(
                    title,
                    cls=f"text-sm font-semibold {accent_text}",
                ),
                P(body, cls="text-sm text-slate-600 mt-1 leading-relaxed"),
                cls="flex-1 min-w-0",
            ),
            cls=(f"flex items-start gap-3 p-4 rounded-lg border {accent_bg}"),
        ),
        Div(
            P(
                "Need to issue a corrective document?",
                cls="text-xs font-semibold text-slate-700 mb-1.5",
            ),
            A(
                icon("plus", cls="h-3.5 w-3.5"),
                Span("Create a new invoice"),
                href="/invoices/new",
                cls=(
                    "inline-flex items-center gap-1.5 px-3 py-1.5 bg-white "
                    "border border-slate-300 text-slate-700 text-xs "
                    "font-medium rounded-lg hover:bg-slate-50 "
                    "hover:text-indigo-600 hover:border-indigo-300 "
                    "transition-colors"
                ),
            ),
            cls="mt-4 pt-4 border-t border-slate-100",
        ),
    )


def register_routes(rt) -> None:
    @rt("/invoices", methods=["GET"])
    async def list_invoices(
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
        items: list[dict] = []
        total_items = 0
        limit = 10
        offset = (page - 1) * limit
        load_error = ""
        try:
            result = await api_client.get_invoice_log(
                jwt,
                limit=limit,
                offset=offset,
                session_id=sid,
                search=q or None,
            )
            items = result.get("items", [])
            total_items = result.get("total", 0)
        except Exception:
            logger.exception("get_invoice_log failed")
            load_error = "Failed to load invoices."

        total_pages = max(1, (total_items + limit - 1) // limit)

        is_htmx = req.headers.get("HX-Request") == "true"
        if is_htmx:
            return Div(
                _invoice_table(items),
                _pagination_controls(
                    page, total_pages, q, "/invoices", "#invoice-list-container"
                ),
                id="invoice-list-container",
            )

        header = Div(
            Div(
                H2(
                    "Invoices",
                    cls="text-2xl font-bold text-slate-900",
                ),
                P(
                    f"{total_items} invoice(s) in your log",
                    cls="text-sm text-slate-500 mt-1",
                ),
            ),
            A(
                icon("plus", cls="h-4 w-4"),
                Span("New invoice"),
                href="/invoices/new",
                cls="inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700 shadow-sm",
            ),
            cls="flex items-center justify-between gap-4 mb-6",
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
                    placeholder="Search by IRN or customer…",
                    value=q,
                    autocomplete="off",
                    hx_get="/invoices",
                    hx_trigger="keyup changed delay:300ms, search, change",
                    hx_target="#invoice-list-container",
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
                    href="/invoices",
                    cls="inline-flex items-center gap-1.5 px-3 py-2 text-sm font-medium text-slate-600 hover:text-slate-900 shrink-0",
                )
            )
        search = Form(
            Div(*search_inputs, cls="flex items-center gap-2 max-w-2xl"),
            method="get",
            action="/invoices",
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
            _invoice_table(items),
            _pagination_controls(
                page, total_pages, q, "/invoices", "#invoice-list-container"
            ),
            id="invoice-list-container",
        )

        return app_shell(
            "Invoices",
            header,
            *banners,
            search,
            list_container,
            active_nav="invoices",
            username=current_username(req),
            business_id=current_business_id(req),
        )

    _RESERVED_INVOICE_SEGMENTS = {"new", "wizard"}

    @rt("/invoices/{irn}", methods=["GET"])
    async def invoice_detail(
        req: Request, irn: str, error: str = "", success: str = ""
    ):
        redirect = require_session(req)
        if redirect:
            return redirect

        if irn in _RESERVED_INVOICE_SEGMENTS or irn.startswith("wizard"):
            return RedirectResponse("/invoices/new", status_code=303)

        jwt = current_jwt(req)
        sid = get_session_id(req)

        log_entry = None
        try:
            log_entry = await api_client.get_invoice_log_by_irn(
                jwt, irn, session_id=sid
            )
        except Exception:
            logger.exception("get_invoice_log_by_irn failed")

        invoice_data: dict = {}
        load_error = ""
        try:
            invoice_data = await api_client.get_invoice(
                jwt, irn, session_id=sid
            )
        except api_client.APIError as e:
            logger.exception("get_invoice failed")
            load_error = (
                e.detail
                if isinstance(e.detail, str)
                else "Could not load invoice from FIRS"
            )
        except Exception:
            logger.exception("get_invoice transport error")
            load_error = "Backend service unavailable."

        if not isinstance(invoice_data, dict):
            invoice_data = {}

        qr_b64 = ""
        if invoice_data:
            amount = (invoice_data.get("legal_monetary_total") or {}).get(
                "payable_amount", 0
            )
            issue_date = invoice_data.get("issue_date", "")
            try:
                qr_b64 = await api_client.get_invoice_qr(
                    jwt, irn, amount, issue_date, session_id=sid
                )
            except Exception:
                logger.exception("get_invoice_qr failed")

        banners = []
        if error:
            banners.append(alert("error", error))
        if success:
            banners.append(alert("success", success))
        if load_error:
            banners.append(alert("warning", load_error))

        back_link = A(
            icon("arrow-left", cls="h-4 w-4"),
            Span("Back to invoices"),
            href="/invoices",
            cls="inline-flex items-center gap-2 text-sm text-slate-600 hover:text-indigo-600 mb-4",
        )

        is_transmitted = bool(log_entry and log_entry.get("transmitted"))
        payment_status = (log_entry or {}).get(
            "payment_status", invoice_data.get("payment_status", "PENDING")
        )

        header = Div(
            Div(
                H2(
                    irn,
                    cls="text-2xl font-bold text-slate-900 font-mono",
                ),
                Div(
                    _status_badge(payment_status),
                    _transmit_badge(is_transmitted),
                    cls="flex items-center gap-2 mt-2",
                ),
            ),
            Div(
                A(
                    icon("download", cls="h-4 w-4"),
                    Span("Download PDF"),
                    href=f"/invoices/{irn}/download",
                    title="Download a PDF copy of this invoice",
                    cls="inline-flex items-center gap-2 px-4 py-2 bg-white border border-slate-300 text-slate-700 text-sm font-medium rounded-lg hover:bg-slate-50",
                ),
                Form(
                    Button(
                        icon("send", cls="h-4 w-4"),
                        Span("Transmit"),
                        type="submit",
                        cls="inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700",
                    ),
                    method="post",
                    action=f"/invoices/{irn}/transmit",
                    cls="inline",
                )
                if not is_transmitted
                else "",
                cls="flex items-center gap-2",
            ),
            cls="flex items-start justify-between gap-3 mb-6",
        )

        is_terminal_status = (payment_status or "").upper() in (
            "PAID",
            "REJECTED",
        )

        external_default = (
            payment_status
            if payment_status in ("PAID", "PARTIAL", "REJECTED")
            else "PAID"
        )

        status_form_script = Script(
            """
            (function(){
              function toggle(){
                var sel = document.getElementById('zefe-status-select');
                var box = document.getElementById('zefe-partial-fields');
                var amt = document.getElementById('zefe-status-amount');
                if (!sel || !box || !amt) return;
                var isPartial = sel.value === 'PARTIAL';
                box.style.display = isPartial ? 'block' : 'none';
                if (isPartial) {
                  amt.setAttribute('required', 'required');
                } else {
                  amt.removeAttribute('required');
                }
              }
              document.addEventListener('DOMContentLoaded', toggle);
              var s = document.getElementById('zefe-status-select');
              if (s) s.addEventListener('change', toggle);
              toggle();
            })();
            """
        )

        status_form = Form(
            H3(
                "Update payment status",
                cls="text-base font-semibold text-slate-900 mb-3",
            ),
            Div(
                Label(
                    "Status",
                    cls="block text-sm font-medium text-slate-700 mb-1.5",
                ),
                Div(
                    Select(
                        Option(
                            "PAID",
                            value="PAID",
                            selected=external_default == "PAID",
                        ),
                        Option(
                            "PARTIAL",
                            value="PARTIAL",
                            selected=external_default == "PARTIAL",
                        ),
                        Option(
                            "REJECTED",
                            value="REJECTED",
                            selected=external_default == "REJECTED",
                        ),
                        name="payment_status",
                        id="zefe-status-select",
                        cls="w-full appearance-none px-3 py-2 pr-9 bg-white text-slate-900 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500",
                    ),
                    icon(
                        "chevron-down",
                        cls="h-4 w-4 text-slate-400 absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none",
                    ),
                    cls="relative",
                ),
                Div(
                    P(
                        "💡 Status Explanations:",
                        cls="text-[11px] font-semibold text-slate-600 mt-2",
                    ),
                    P(
                        "• Paid: Full payment has been received and settled.",
                        cls="text-[11px] text-slate-500",
                    ),
                    P(
                        "• Partial: Part-paid with remaining balance outstanding "
                        "(amount required).",
                        cls="text-[11px] text-slate-500",
                    ),
                    P(
                        "• Rejected: Payment has been rejected, invalid or disputed.",
                        cls="text-[11px] text-slate-500",
                    ),
                    P(
                        "Note: only transmitted invoices can have their FIRS "
                        "payment status updated.",
                        cls="text-[11px] text-slate-500 mt-1",
                    ),
                    cls="mt-1.5 space-y-0.5 bg-slate-50 p-2.5 rounded-lg border border-slate-200",
                ),
                cls="mb-3",
            ),
            Div(
                Div(
                    Label(
                        "Amount paid",
                        cls="block text-sm font-medium text-slate-700 mb-1.5",
                    ),
                    Input(
                        name="amount",
                        id="zefe-status-amount",
                        type="number",
                        step="0.01",
                        min="0.01",
                        placeholder="0.00",
                        cls="w-full px-3 py-2 bg-white text-slate-900 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500",
                    ),
                    P(
                        "Required for PARTIAL — must be greater than zero.",
                        cls="text-[11px] text-slate-500 mt-1",
                    ),
                    cls="mb-3",
                ),
                Div(
                    Label(
                        "Reference (optional)",
                        cls="block text-sm font-medium text-slate-700 mb-1.5",
                    ),
                    Input(
                        name="reference",
                        type="text",
                        placeholder="e.g. bank transfer ref, receipt #",
                        cls="w-full px-3 py-2 bg-white text-slate-900 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500",
                    ),
                    cls="mb-3",
                ),
                Div(
                    Label(
                        "Payment date (optional)",
                        cls="block text-sm font-medium text-slate-700 mb-1.5",
                    ),
                    Input(
                        name="payment_update_date",
                        type="date",
                        cls="w-full px-3 py-2 bg-white text-slate-900 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500",
                    ),
                    cls="mb-3",
                ),
                id="zefe-partial-fields",
                cls="border border-indigo-100 bg-indigo-50/40 rounded-lg p-3 mb-3",
                style="display:none;",
            ),
            Div(
                Label(
                    "Signing secret",
                    cls="block text-sm font-medium text-slate-700 mb-1.5",
                ),
                Input(
                    name="user_secret",
                    type="password",
                    required=True,
                    autocomplete="off",
                    placeholder="Enter your signing secret",
                    cls="w-full px-3 py-2 bg-white text-slate-900 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500",
                ),
                P(
                    "Your secret is sent securely to FIRS and never stored "
                    "in this browser.",
                    cls="text-[11px] text-slate-500 mt-1",
                ),
                cls="mb-3",
            ),
            Div(
                primary_button("Update status", type="submit"),
                cls="flex justify-end",
            ),
            status_form_script,
            method="post",
            action=f"/invoices/{irn}/status",
        )

        supplier: dict = {}
        customer: dict = {}
        lines: list = []
        totals: dict = {}
        currency: str = ""
        if invoice_data:
            supplier = invoice_data.get("accounting_supplier_party") or {}
            customer = invoice_data.get("accounting_customer_party") or {}
            raw_lines = invoice_data.get("invoice_line") or []
            lines = raw_lines if isinstance(raw_lines, list) else []
            totals = invoice_data.get("legal_monetary_total") or {}
            currency = invoice_data.get("document_currency_code", "") or ""
        if not isinstance(supplier, dict):
            supplier = {}
        if not isinstance(customer, dict):
            customer = {}
        if not isinstance(totals, dict):
            totals = {}

        auth_section = card(
            Div(
                icon(
                    "check-circle",
                    cls="h-4 w-4 text-emerald-600",
                ),
                H3(
                    "FIRS authoritative data",
                    cls="text-base font-semibold text-slate-900",
                ),
                cls="flex items-center gap-2 mb-4",
            ),
            Div(
                _party_card("Supplier", supplier, "user-plus"),
                _party_card("Customer", customer, "user-plus"),
                cls="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-4",
            ),
            Div(
                H3(
                    "Line items",
                    cls="text-xs uppercase text-slate-500 font-semibold tracking-wider mb-2",
                ),
                Div(
                    Table(
                        Thead(
                            Tr(
                                Th(
                                    "Item",
                                    cls="px-4 py-2 text-left text-xs font-semibold text-slate-500 uppercase",
                                ),
                                Th(
                                    "Qty",
                                    cls="px-4 py-2 text-right text-xs font-semibold text-slate-500 uppercase",
                                ),
                                Th(
                                    "Unit",
                                    cls="px-4 py-2 text-right text-xs font-semibold text-slate-500 uppercase",
                                ),
                                Th(
                                    "Total",
                                    cls="px-4 py-2 text-right text-xs font-semibold text-slate-500 uppercase",
                                ),
                                cls="border-b border-slate-200 bg-slate-50",
                            )
                        ),
                        Tbody(*[_line_row(ln) for ln in lines]),
                        cls="table-auto w-full",
                    ),
                    cls="overflow-hidden rounded-lg border border-slate-200",
                )
                if lines
                else P(
                    "No line items.",
                    cls="text-sm text-slate-500",
                ),
                cls="mb-4",
            ),
            Div(
                Div(
                    P("Subtotal", cls="text-sm text-slate-600"),
                    P(
                        f"{currency} {float(totals.get('tax_exclusive_amount', 0)):.2f}",
                        cls="text-sm text-slate-900",
                    ),
                    cls="flex items-center justify-between py-1",
                ),
                Div(
                    P("Tax", cls="text-sm text-slate-600"),
                    P(
                        f"{currency} {float((invoice_data.get('tax_total') or [{}])[0].get('tax_amount', 0) if invoice_data.get('tax_total') else 0):.2f}",
                        cls="text-sm text-slate-900",
                    ),
                    cls="flex items-center justify-between py-1",
                ),
                Div(
                    P(
                        "Payable",
                        cls="text-sm font-semibold text-slate-900",
                    ),
                    P(
                        f"{currency} {float(totals.get('payable_amount', 0)):.2f}",
                        cls="text-base font-bold text-indigo-700",
                    ),
                    cls="flex items-center justify-between py-2 border-t border-slate-200 mt-1",
                ),
            ),
        )

        qr_card = card(
            H3(
                "QR code",
                cls="text-base font-semibold text-slate-900 mb-3",
            ),
            Img(
                src=f"data:image/png;base64,{qr_b64}",
                alt=f"QR code for invoice {irn}",
                cls="w-48 h-48 mx-auto",
            )
            if qr_b64
            else Div(
                icon(
                    "alert-circle",
                    cls="h-12 w-12 text-slate-300 mx-auto",
                ),
                P(
                    "QR not available",
                    cls="text-xs text-slate-500 text-center mt-2",
                ),
                cls="py-8",
            ),
            Div(
                P(
                    "Scan to verify invoice",
                    cls="text-xs font-semibold text-slate-700 text-center",
                ),
                P(
                    "This QR encodes the invoice's IRN, payable amount, and "
                    "issue date for quick verification. Scanning will return "
                    "plain text in the format ",
                    Span(
                        "IRN:…|AMT:…|DATE:…",
                        cls="font-mono text-[11px] bg-slate-100 px-1 py-0.5 rounded",
                    ),
                    " — useful for cross-checking against this page.",
                    cls="text-[11px] text-slate-500 text-center mt-1.5 leading-relaxed",
                ),
                cls="mt-3 px-1",
            )
            if qr_b64
            else "",
        )

        status_panel = (
            card(_terminal_status_notice(payment_status))
            if is_terminal_status
            else card(status_form)
        )

        return app_shell(
            irn,
            back_link,
            *banners,
            header,
            Div(
                Div(
                    auth_section,
                    status_panel,
                    cls="md:col-span-2 flex flex-col gap-4",
                ),
                qr_card,
                cls="grid grid-cols-1 md:grid-cols-3 gap-4",
            ),
            active_nav="invoices",
            username=current_username(req),
            business_id=current_business_id(req),
        )

    @rt("/invoices/{irn}/download", methods=["GET"])
    async def download_invoice(req: Request, irn: str):
        redirect = require_session(req)
        if redirect:
            return redirect
        jwt = current_jwt(req)
        sid = get_session_id(req)
        try:
            invoice_data = await api_client.get_invoice(
                jwt, irn, session_id=sid
            )
        except api_client.APIError as e:
            logger.exception("download_invoice get_invoice failed")
            detail = (
                e.detail
                if isinstance(e.detail, str)
                else "Could not load invoice"
            )
            return RedirectResponse(
                f"/invoices/{irn}?error={detail}", status_code=303
            )
        except Exception:
            logger.exception("download_invoice transport error")
            return RedirectResponse(
                f"/invoices/{irn}?error=Backend+service+unavailable",
                status_code=303,
            )

        log_entry = None
        try:
            log_entry = await api_client.get_invoice_log_by_irn(
                jwt, irn, session_id=sid
            )
        except Exception:
            logger.exception("download_invoice get_log failed (best-effort)")

        qr_b64 = ""
        if invoice_data:
            amount = (invoice_data.get("legal_monetary_total") or {}).get(
                "payable_amount", 0
            )
            issue_date = invoice_data.get("issue_date", "")
            try:
                qr_b64 = await api_client.get_invoice_qr(
                    jwt, irn, amount, issue_date, session_id=sid
                )
            except Exception:
                logger.exception(
                    "download_invoice get_invoice_qr failed (best-effort)"
                )

        safe_irn = re.sub(r"[^A-Za-z0-9._-]", "_", irn) or "invoice"
        filename = f"invoice_{safe_irn}.pdf"

        try:
            pdf_bytes = build_invoice_pdf(
                invoice_data, log_entry, qr_b64=qr_b64
            )
        except Exception:
            logger.exception("download_invoice pdf build failed")
            return RedirectResponse(
                f"/invoices/{irn}?error=Could+not+generate+invoice+PDF",
                status_code=303,
            )

        headers = {
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "application/pdf",
            "Content-Length": str(len(pdf_bytes)),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        }
        return Response(
            content=pdf_bytes,
            headers=headers,
            media_type="application/pdf",
        )

    @rt("/invoices/{irn}/transmit", methods=["POST"])
    async def transmit_invoice(req: Request, irn: str):
        redirect = require_session(req)
        if redirect:
            return redirect
        jwt = current_jwt(req)
        sid = get_session_id(req)
        try:
            await api_client.transmit_invoice(jwt, irn, session_id=sid)
            try:
                await api_client.mark_transmitted(jwt, irn, session_id=sid)
            except Exception:
                logger.exception("mark_transmitted failed")
            return RedirectResponse(
                f"/invoices/{irn}?success=Invoice+transmitted+to+FIRS.+"
                "Final+delivery+depends+on+the+recipient+having+e-invoice+"
                "receiving+enabled.",
                status_code=303,
            )
        except api_client.APIError as e:
            detail_str = extract_api_error_detail(e)
            lower = detail_str.lower()
            if any(w in lower for w in ("already", "transmitted", "duplicate")):
                try:
                    await api_client.mark_transmitted(jwt, irn, session_id=sid)
                except Exception:
                    logger.exception("mark_transmitted self-heal failed")
                return RedirectResponse(
                    f"/invoices/{irn}?success=Already+transmitted",
                    status_code=303,
                )
            logger.exception("transmit_invoice failed")
            return RedirectResponse(
                f"/invoices/{irn}?error={detail_str}", status_code=303
            )
        except Exception:
            logger.exception("transmit transport error")
            return RedirectResponse(
                f"/invoices/{irn}?error=Backend+service+unavailable",
                status_code=303,
            )

    @rt("/invoices/{irn}/status", methods=["POST"])
    async def update_status(req: Request, irn: str):
        import urllib.parse

        redirect = require_session(req)
        if redirect:
            return redirect
        form = await req.form()
        new_status = (form.get("payment_status") or "").strip().upper()
        secret = (form.get("user_secret") or "").strip()
        amount_raw = (form.get("amount") or "").strip()
        reference = (form.get("reference") or "").strip()
        payment_update_date = (form.get("payment_update_date") or "").strip()

        if new_status not in ("PAID", "PARTIAL", "REJECTED"):
            msg = urllib.parse.quote_plus(
                "Choose PAID, PARTIAL, or REJECTED to update the FIRS payment status."
            )
            return RedirectResponse(
                f"/invoices/{irn}?error={msg}", status_code=303
            )

        if not secret:
            return RedirectResponse(
                f"/invoices/{irn}?error=Signing+secret+required",
                status_code=303,
            )

        amount: Optional[float] = None
        if amount_raw:
            try:
                amount = float(amount_raw)
            except ValueError:
                msg = urllib.parse.quote_plus("Amount must be a valid number.")
                return RedirectResponse(
                    f"/invoices/{irn}?error={msg}", status_code=303
                )
            if amount <= 0:
                msg = urllib.parse.quote_plus(
                    "Amount must be greater than zero."
                )
                return RedirectResponse(
                    f"/invoices/{irn}?error={msg}", status_code=303
                )

        if new_status == "PARTIAL":
            if amount is None:
                msg = urllib.parse.quote_plus(
                    "A payment amount greater than zero is required when "
                    "marking an invoice as PARTIAL."
                )
                return RedirectResponse(
                    f"/invoices/{irn}?error={msg}", status_code=303
                )
        else:
            amount = None

        jwt = current_jwt(req)
        sid = get_session_id(req)

        try:
            current_log = await api_client.get_invoice_log_by_irn(
                jwt, irn, session_id=sid
            )
            current_status = (
                (current_log or {}).get("payment_status", "") or ""
            ).upper()
            if current_status in ("PAID", "REJECTED"):
                friendly = (
                    "This invoice is already PAID and cannot be updated. "
                    "Issue a credit note as a new invoice instead."
                    if current_status == "PAID"
                    else "This invoice is REJECTED and cannot be updated. "
                    "Create a new invoice with a fresh IRN."
                )
                return RedirectResponse(
                    f"/invoices/{irn}?error={urllib.parse.quote_plus(friendly)}",
                    status_code=303,
                )
        except Exception:
            logger.exception("update_status: pre-check terminal state failed")

        try:
            await api_client.update_invoice_status(
                jwt,
                irn,
                user_secret=secret,
                payment_status=new_status,
                reference=reference,
                amount=amount,
                payment_update_date=payment_update_date or None,
                session_id=sid,
            )
        except api_client.APIError as e:
            logger.exception("update_invoice_status failed")
            detail = extract_api_error_detail(e)
            safe = urllib.parse.quote_plus(detail)
            return RedirectResponse(
                f"/invoices/{irn}?error={safe}", status_code=303
            )
        except Exception:
            logger.exception("update_status transport error")
            return RedirectResponse(
                f"/invoices/{irn}?error=Backend+service+unavailable",
                status_code=303,
            )

        try:
            await api_client.update_log_status(
                jwt, irn, new_status, session_id=sid
            )
        except Exception:
            logger.exception("update_log_status failed after authoritative ok")
            warn = urllib.parse.quote_plus(
                f"FIRS updated to {new_status}, but the local invoice log "
                "could not be refreshed. Reload to see the latest state."
            )
            return RedirectResponse(
                f"/invoices/{irn}?error={warn}", status_code=303
            )

        return RedirectResponse(
            f"/invoices/{irn}?success=Status+updated+to+{new_status}",
            status_code=303,
        )