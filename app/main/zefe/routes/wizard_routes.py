from __future__ import annotations

import asyncio
import json
import logging
import urllib.parse
from datetime import date, datetime

from fasthtml.common import (
    A,
    Button,
    Div,
    Form,
    H1,
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
    Table,
    Tbody,
    Td,
    Th,
    Thead,
    Tr,
)
from starlette.requests import Request
from starlette.responses import HTMLResponse

from deps import (
    current_business_id,
    current_jwt,
    current_username,
    get_session_id,
    require_session,
)
from services import api_client, auth_service, lookup_ranking
from services.errors import (
    extract_api_error_detail,
    normalize_transmission_error,
)
from services.unit_codes import (
    DEFAULT_UNIT_CODE,
    coerce_unit_code,
    unit_code_label,
    unit_code_options,
)
from ui.components import (
    alert,
    card,
    confirm_detail_rows,
    confirm_dialog,
    country_state_fields,
    guidance_panel,
    guidance_text,
    item_classification_badge,
    item_empty_panel,
    item_identity,
    item_kind,
    item_kind_badge,
    item_price_summary,
    item_search_empty_copy,
    item_sku_text,
    item_source_badge,
    unit_chip,
)
from ui.icons import icon
from ui.layout import app_shell

logger = logging.getLogger(__name__)

TAX_RATE = 0.075
REFERENCE_REQUIRED_INVOICE_TYPES = frozenset({"380", "384", "385"})
_IRN_MIN_SEQUENCE = 3180

import re as _re_module


def _normalize_service_segment(service_id: str) -> str:
    cleaned = _re_module.sub(r"[^A-Za-z0-9]", "", service_id or "")
    return (cleaned.upper()[:12]) or "SERVICE0"


def _default_price_unit(wizard: dict) -> str:
    """Official default unit code for a new line (never free text).

    FIRS requires ``price_unit`` to be a 2-3 character UN/ECE code, so the
    wizard always defaults to ``EA`` (each) regardless of currency. Legacy
    values such as ``C62`` or ``"NGN per 1"`` are normalized, never shown.
    """
    return DEFAULT_UNIT_CODE


# NOTE: invoice_kind, tax_point_date, tax_currency_code, payment_status and
# the IRN sequence remain fully derived server-side (see
# zebe/services/invoice_service.py). They are never collected as wizard inputs
# and are no longer surfaced as a read-only panel in step 4.


def _unit_select_field(value: str = DEFAULT_UNIT_CODE) -> Div:
    """Compact official unit-code dropdown for the line form."""
    current = coerce_unit_code(value)
    opts = []
    for code, label in unit_code_options():
        opts.append(
            Option(f"{code} - {label}", value=code, selected=(code == current))
        )
    return Div(
        Label(
            "Price unit",
            fr="price_unit",
            cls="block text-sm font-medium text-slate-700 mb-1.5",
        ),
        Div(
            Select(
                *opts,
                id="price_unit",
                name="price_unit",
                required=True,
                cls=(
                    "w-full appearance-none px-3 py-2 pr-9 bg-white "
                    "text-slate-900 border border-slate-300 rounded-lg "
                    "text-sm focus:outline-none focus:ring-2 "
                    "focus:ring-indigo-500"
                ),
            ),
            icon(
                "chevron-down",
                cls=(
                    "h-4 w-4 text-slate-400 absolute right-3 top-1/2 "
                    "-translate-y-1/2 pointer-events-none"
                ),
            ),
            cls="relative",
        ),
        guidance_text(
            "Official 2-3 character UN/ECE unit code (EA = each). "
            "FIRS rejects free text such as 'NGN per 1'."
        ),
        cls="mb-4",
    )


async def _compute_next_irn(jwt: str, sid: str, service_id: str) -> str:
    ts = datetime.now().strftime("%Y%m%d")
    svc = _normalize_service_segment(service_id)
    max_seq = _IRN_MIN_SEQUENCE - 1
    try:
        result = await api_client.get_invoice_log(
            jwt, limit=200, offset=0, session_id=sid
        )
        items = (result or {}).get("items", []) or []
        for item in items:
            irn_str = str((item or {}).get("irn", "") or "")
            m = _re_module.match(r"^INV(\d+)", irn_str)
            if not m:
                continue
            try:
                n = int(m.group(1))
                if n > max_seq:
                    max_seq = n
            except ValueError:
                continue
    except Exception:
        logger.exception("_compute_next_irn: invoice log scan failed")
    next_seq = max(_IRN_MIN_SEQUENCE, max_seq + 1)
    return f"INV{next_seq}-{svc}-{ts}"


def _load_wizard(session_id: str) -> dict:
    try:
        row = auth_service.get_session(session_id)
    except Exception:
        logging.exception("load wizard session")
        return {}
    if not row or not row.get("wizard_json"):
        return {}
    try:
        return json.loads(row["wizard_json"])
    except (json.JSONDecodeError, TypeError):
        logging.exception("wizard json parse")
        return {}


def _save_wizard(session_id: str, wizard: dict) -> None:
    try:
        auth_service.save_wizard_json(session_id, json.dumps(wizard))
    except Exception:
        logger.exception("_save_wizard best-effort failed")


def _clear_wizard(session_id: str) -> None:
    try:
        auth_service.clear_wizard_json(session_id)
    except Exception as e:
        logger.exception("Failed to clear wizard JSON: %s", e)


def _safe_float(v, default=0.0) -> float:
    if v is None or v == "":
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _line_extension(line: dict) -> float:
    qty = _safe_float(line.get("invoiced_quantity", 0))
    price = _safe_float(line.get("price_amount", 0))
    base = qty * price
    discount_amount = _safe_float(line.get("discount_amount"))
    discount_rate = _safe_float(line.get("discount_rate"))
    fee_amount = _safe_float(line.get("fee_amount"))
    fee_rate = _safe_float(line.get("fee_rate"))
    discount = (
        discount_amount if discount_amount else base * discount_rate / 100
    )
    fee = fee_amount if fee_amount else base * fee_rate / 100
    return base - discount + fee


def _stepper(current: int, max_reached: int) -> Div:
    steps = [
        (1, "Header", "file-text"),
        (2, "Parties", "users"),
        (3, "Line items", "receipt"),
        (4, "Review & Sign", "check-circle"),
    ]
    nodes = []
    for num, label, icon_name in steps:
        active = num == current
        done = num < current or (num <= max_reached and num != current)
        if active:
            circle_cls = "h-8 w-8 rounded-full bg-indigo-600 text-white flex items-center justify-center text-xs font-semibold shrink-0"
        elif done:
            circle_cls = "h-8 w-8 rounded-full bg-emerald-600 text-white flex items-center justify-center text-xs font-semibold shrink-0"
        else:
            circle_cls = "h-8 w-8 rounded-full bg-slate-200 text-slate-500 flex items-center justify-center text-xs font-semibold shrink-0"
        label_cls = (
            "text-sm font-semibold text-indigo-700"
            if active
            else "text-sm font-medium text-slate-700"
        )
        node = Div(
            Div(num, cls=circle_cls),
            Div(
                P(
                    f"Step {num}",
                    cls="text-xs uppercase text-slate-500 font-semibold tracking-wider",
                ),
                P(label, cls=label_cls),
                cls="hidden sm:block text-left",
            ),
            cls="flex items-center gap-2",
        )
        nodes.append(node)
        if num < 4:
            nodes.append(Div(cls="flex-1 h-px bg-slate-200 mx-2"))
    return Div(
        Div(*nodes, cls="flex items-center w-full"),
        cls="bg-white border border-slate-200 rounded-xl p-4 mb-6",
    )


def _banner(error: str = "", success: str = "") -> Div:
    items = []
    if error:
        items.append(alert("error", error, cls=""))
    if success:
        items.append(alert("success", success, cls=""))
    return Div(*items, cls="space-y-3 mb-5") if items else Span("")


def _page_header(title: str, subtitle: str) -> Div:
    return Div(
        A(
            icon("arrow-left", cls="h-4 w-4"),
            Span("Back to invoices"),
            href="/invoices",
            cls="inline-flex items-center gap-2 text-sm text-slate-600 hover:text-indigo-600 mb-3",
        ),
        H1(
            title,
            cls="text-2xl font-bold text-slate-900 tracking-tight",
        ),
        P(subtitle, cls="text-sm text-slate-500 mt-1"),
        cls="mb-5",
    )


def _wizard_actions(
    *,
    show_back: bool = True,
    next_label: str = "Continue",
    next_icon: str = "arrow-right",
    discard: bool = True,
) -> Div:
    children = []
    if discard:
        children.append(
            Button(
                icon("x", cls="h-4 w-4"),
                Span("Discard progress"),
                type="button",
                hx_get="/invoices/wizard/discard-confirm",
                hx_target="#wizard-modal-area",
                hx_swap="innerHTML",
                cls="inline-flex items-center gap-2 px-4 py-2 bg-white border border-slate-300 text-slate-700 text-sm font-medium rounded-lg hover:bg-slate-50 cursor-pointer",
            )
        )
    children.append(Div(cls="flex-1"))
    if show_back:
        children.append(
            Button(
                icon("arrow-left", cls="h-4 w-4"),
                Span("Back"),
                type="submit",
                name="_action",
                value="back",
                cls="inline-flex items-center gap-2 px-4 py-2 bg-white border border-slate-300 text-slate-700 text-sm font-medium rounded-lg hover:bg-slate-50",
            )
        )
    children.append(
        Button(
            Span(next_label),
            icon(next_icon, cls="h-4 w-4"),
            type="submit",
            name="_action",
            value="next",
            cls="inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700",
        )
    )
    return Div(*children, cls="flex items-center gap-2 mt-6")


def _field(
    *,
    name: str,
    label: str,
    value: str = "",
    type: str = "text",
    placeholder: str = "",
    required: bool = False,
    helper: str = "",
    span_full: bool = False,
    **kwargs,
) -> Div:
    inp_attrs = {
        "id": name,
        "name": name,
        "type": type,
        "placeholder": placeholder,
        "value": value or "",
        **kwargs,
    }
    if required:
        inp_attrs["required"] = True
    children = [
        Label(
            label,
            fr=name,
            cls="block text-sm font-medium text-slate-700 mb-1.5",
        ),
        Input(
            **inp_attrs,
            cls=(
                "w-full px-3 py-2 bg-white text-slate-900 border border-slate-300 "
                "rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500",
            ),
        ),
    ]
    if helper:
        children.append(guidance_text(helper))
    extra = " md:col-span-2" if span_full else ""
    return Div(*children, cls=f"mb-4{extra}")


def _select_field(
    *,
    name: str,
    label: str,
    options: list,
    value: str = "",
    placeholder: str = "Select…",
    required: bool = False,
    helper: str = "",
    **kwargs,
) -> Div:
    opts = [Option(placeholder, value="", disabled=True, selected=not value)]
    for code, lbl in options:
        opts.append(Option(lbl, value=code, selected=(str(code) == str(value))))
    children = [
        Label(
            label,
            fr=name,
            cls="block text-sm font-medium text-slate-700 mb-1.5",
        ),
        Div(
            Select(
                *opts,
                id=name,
                name=name,
                required=required,
                cls="w-full appearance-none px-3 py-2 pr-9 bg-white text-slate-900 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500",
                **kwargs,
            ),
            icon(
                "chevron-down",
                cls="h-4 w-4 text-slate-400 absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none",
            ),
            cls="relative",
        ),
    ]
    if helper:
        children.append(P(helper, cls="text-xs text-slate-500 mt-1"))
    return Div(*children, cls="mb-4")


async def _load_step1_lookups(jwt: str, sid: str):
    types = []
    means = []
    currencies = []
    try:
        types_t = api_client.get_invoice_types(jwt, session_id=sid)
        means_t = api_client.get_payment_means(jwt, session_id=sid)
        cur_t = api_client.get_currencies(jwt, session_id=sid)
        types_r, means_r, cur_r = await asyncio.gather(
            types_t, means_t, cur_t, return_exceptions=True
        )
        types = (
            [
                (t["code"], t.get("value") or t["code"])
                for t in types_r
                if isinstance(t, dict) and t.get("code")
            ]
            if not isinstance(types_r, Exception)
            else []
        )
        means = (
            [
                (m["code"], m.get("value", m["code"]))
                for m in means_r
                if isinstance(m, dict)
            ]
            if not isinstance(means_r, Exception)
            else []
        )
        currencies = (
            [
                (c["code"], f"{c['code']} - {c.get('name', '')}")
                for c in cur_r
                if isinstance(c, dict)
            ]
            if not isinstance(cur_r, Exception)
            else []
        )
    except Exception:
        logger.exception("step1 lookups failed")
    if not types:
        types = [
            ("381", "Commercial Invoice"),
            ("380", "Credit Note"),
            ("384", "Debit Note"),
            ("385", "Self Billed Invoice"),
            ("388", "Factored Invoice"),
            ("389", "Statement of Account"),
        ]
    if not means:
        means = [
            ("10", "Cash"),
            ("20", "Cheque"),
            ("30", "Credit Transfer"),
            ("31", "Debit Transfer"),
            ("42", "ACH Credit"),
            ("43", "ACH Debit"),
        ]

    if not currencies:
        currencies = [
            ("NGN", "NGN - Nigerian Naira"),
            ("USD", "USD - US Dollar"),
        ]
    return types, means, currencies


async def _load_geo_lookups(jwt: str, sid: str):
    try:
        states_t = api_client.get_state_codes(jwt, session_id=sid)
        countries_t = api_client.get_countries(jwt, session_id=sid)
        states_r, countries_r = await asyncio.gather(
            states_t, countries_t, return_exceptions=True
        )
        states = (
            [
                (s.get("code") or s.get("name", ""), s.get("name", ""))
                for s in states_r
                if isinstance(s, dict)
            ]
            if not isinstance(states_r, Exception)
            else []
        )
        countries = (
            [
                (c.get("alpha_2", ""), c.get("name", ""))
                for c in countries_r
                if isinstance(c, dict) and c.get("alpha_2")
            ]
            if not isinstance(countries_r, Exception)
            else []
        )
    except Exception:
        logger.exception("geo lookups failed")
        states, countries = [], []
    if not countries:
        countries = [
            ("NG", "Nigeria"),
            ("GB", "United Kingdom"),
            ("US", "United States"),
        ]
    return states, countries


def _render_step1_billing_reference(inv_type: str, wizard: dict) -> Div:
    norm_type = str(inv_type or "").strip()
    needs_billing = norm_type in REFERENCE_REQUIRED_INVOICE_TYPES
    if not needs_billing:
        return Div(id="billing-reference-container", cls="hidden")
    return Div(
        H3(
            "Billing reference (required)",
            cls="text-sm font-semibold text-slate-700 mb-2",
        ),
        P(
            "FIRS requires the original invoice's IRN and issue date for credit notes, debit notes, and self-billed invoices.",
            cls="text-xs text-slate-500 mb-3",
        ),
        Div(
            _field(
                name="billing_reference_irn",
                label="Original IRN",
                value=wizard.get("billing_reference_irn", ""),
                required=True,
            ),
            _field(
                name="billing_reference_issue_date",
                label="Original issue date",
                type="date",
                value=wizard.get("billing_reference_issue_date", ""),
                required=True,
            ),
            cls="grid grid-cols-1 md:grid-cols-2 gap-x-4",
        ),
        id="billing-reference-container",
        cls="mt-4 p-4 bg-slate-50 rounded-lg border border-slate-200",
    )


def _irn_readonly_block(irn: str) -> Div:
    return Div(
        Label(
            "Invoice Reference Number (IRN)",
            cls="block text-sm font-medium text-slate-700 mb-1.5",
        ),
        Div(
            Span(
                irn or "-",
                cls="font-mono text-sm text-slate-900 break-all min-w-0 flex-1",
            ),
            Span(
                "System generated",
                cls=(
                    "ml-3 inline-flex items-center px-2 py-0.5 rounded-full "
                    "text-[11px] font-semibold bg-indigo-50 text-indigo-700 "
                    "border border-indigo-200 shrink-0"
                ),
            ),
            cls=(
                "flex items-center gap-2 px-3 py-2 bg-slate-50 border "
                "border-slate-200 rounded-lg"
            ),
        ),
        Hidden(name="irn", value=irn or ""),
        P(
            "Generated automatically using the FIRS pattern "
            "INV{sequence}-{ServiceID}-{YYYYMMDD}. The sequence is "
            "auto-incremented from your invoice history to prevent "
            "duplicate IRNs on the FIRS gateway.",
            cls="text-xs text-slate-500 mt-1.5 leading-relaxed",
        ),
        cls="mb-4 md:col-span-2",
    )


def _render_step1(
    *,
    wizard: dict,
    types: list,
    means: list,
    currencies: list,
    service_id: str = "",
    error: str = "",
    success: str = "",
) -> Div:
    irn_default = wizard.get("irn") or ""
    issue = wizard.get("issue_date") or date.today().isoformat()
    inv_type = wizard.get("invoice_type_code", "381")

    billing_block = _render_step1_billing_reference(inv_type, wizard)

    form = Form(
        _banner(error, success),
        Div(
            _irn_readonly_block(irn_default),
            cls="grid grid-cols-1 md:grid-cols-2 gap-x-4",
        ),
        Div(
            _field(
                name="issue_date",
                label="Issue date",
                type="date",
                value=issue,
                required=True,
            ),
            _field(
                name="due_date",
                label="Due date",
                type="date",
                value=wizard.get("due_date", ""),
            ),
            cls="grid grid-cols-1 md:grid-cols-2 gap-x-4",
        ),
        Div(
            _select_field(
                name="invoice_type_code",
                label="Invoice type",
                options=types,
                value=inv_type,
                required=True,
                hx_get="/invoices/wizard/billing-reference-partial",
                hx_trigger="change",
                hx_target="#billing-reference-container",
                hx_swap="outerHTML",
                helper="Credit/debit/self-billed types require a billing reference below.",
            ),
            _select_field(
                name="document_currency_code",
                label="Currency",
                options=currencies,
                value=wizard.get("document_currency_code", "NGN"),
                required=True,
            ),
            cls="grid grid-cols-1 md:grid-cols-2 gap-x-4",
        ),
        _select_field(
            name="payment_means_code",
            label="Payment means",
            options=means,
            value=wizard.get("payment_means_code", "10"),
            required=True,
        ),
        billing_block,
        _wizard_actions(show_back=False, next_label="Next: parties"),
        method="post",
        action="/invoices/wizard/step/1",
    )
    return Div(card(form), Div(id="wizard-modal-area"))


def _supplier_summary(profile: dict) -> Div:
    def f(lbl, val):
        return Div(
            P(
                lbl,
                cls="text-xs uppercase text-slate-500 font-semibold tracking-wider",
            ),
            P(val or "-", cls="text-sm text-slate-900 mt-1"),
        )

    return Div(
        Div(
            Div(
                icon("user-plus", cls="h-5 w-5 text-indigo-600"),
                Div(
                    H3(
                        "Supplier (you)",
                        cls="text-base font-semibold text-slate-900",
                    ),
                    P(
                        "Pulled from your business profile.",
                        cls="text-xs text-slate-500",
                    ),
                ),
                cls="flex items-center gap-3",
            ),
            A(
                icon("settings", cls="h-3 w-3"),
                Span("Edit in Settings"),
                href="/settings/profile",
                cls="inline-flex items-center gap-1.5 text-xs font-medium text-indigo-600 hover:underline",
            ),
            cls="flex items-center justify-between mb-4",
        ),
        Div(
            f("Company", profile.get("party_name", "")),
            f("TIN", profile.get("tin", "")),
            f("Email", profile.get("email", "")),
            f("Telephone", profile.get("telephone", "")),
            f("Street", profile.get("street_name", "")),
            f("City", profile.get("city_name", "")),
            f("State", profile.get("state", "")),
            f("Country", profile.get("country", "")),
            cls="grid grid-cols-2 md:grid-cols-4 gap-4",
        ),
        cls="bg-white border border-slate-200 rounded-xl p-5 mb-5",
    )


def _customer_picker(customers: list, selected_id: str = "") -> Div:
    options = [
        Option(
            "Choose a saved customer (optional)",
            value="",
            selected=not selected_id,
        )
    ]
    for c in customers[:200]:
        cid = str(c.get("id", ""))
        label = f"{c.get('party_name', '')} · {c.get('tin', '')}"
        options.append(
            Option(label, value=cid, selected=(cid == str(selected_id)))
        )
    return Div(
        Label(
            "Pick a saved customer",
            fr="customer_id",
            cls="block text-sm font-medium text-slate-700 mb-1.5",
        ),
        Div(
            Select(
                *options,
                id="customer_id",
                name="customer_id",
                hx_post="/invoices/wizard/customer/select",
                hx_trigger="change",
                hx_target="body",
                hx_swap="outerHTML",
                hx_include="this",
                cls="w-full appearance-none px-3 py-2 pr-9 bg-white text-slate-900 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500",
            ),
            icon(
                "chevron-down",
                cls="h-4 w-4 text-slate-400 absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none",
            ),
            cls="relative",
        ),
        P(
            "Choose a saved customer to fill their details automatically, or skip and type a one-off below.",
            cls="text-xs text-slate-500 mt-1",
        ),
        cls="mb-5",
    )


def _selected_customer_summary(wizard: dict) -> Div:
    cid = str(wizard.get("customer_id", "") or "")

    def field(label: str, value):
        return Div(
            P(
                label,
                cls="text-xs uppercase text-slate-500 font-semibold tracking-wider",
            ),
            P(value or "-", cls="text-sm text-slate-900 mt-1 truncate"),
        )

    return Div(
        Div(
            Div(
                icon("user-plus", cls="h-5 w-5 text-indigo-600"),
                Div(
                    H3(
                        "Selected customer",
                        cls="text-base font-semibold text-slate-900",
                    ),
                    P(
                        "These details come from your saved customer list.",
                        cls="text-xs text-slate-500",
                    ),
                ),
                cls="flex items-center gap-3",
            ),
            Div(
                Button(
                    icon("settings", cls="h-3 w-3"),
                    Span("Edit customer"),
                    type="button",
                    hx_get=f"/invoices/wizard/customer/{cid}/edit",
                    hx_target="#wizard-modal-area",
                    hx_swap="innerHTML",
                    cls="inline-flex items-center gap-1.5 text-xs font-semibold text-indigo-600 hover:text-indigo-700 hover:underline",
                ),
                A(
                    icon("x", cls="h-3 w-3"),
                    Span("Choose different"),
                    href="/invoices/wizard/customer/clear",
                    cls="inline-flex items-center gap-1.5 text-xs font-medium text-slate-500 hover:text-slate-900 ml-3",
                ),
                cls="flex items-center",
            ),
            cls="flex items-center justify-between mb-4 gap-3",
        ),
        Div(
            field("Company", wizard.get("customer_party_name", "")),
            field("TIN", wizard.get("customer_tin", "")),
            field("Email", wizard.get("customer_email", "")),
            field("Telephone", wizard.get("customer_telephone", "")),
            field("Street", wizard.get("customer_street_name", "")),
            field("City", wizard.get("customer_city_name", "")),
            field("State", wizard.get("customer_state", "")),
            field("Country", wizard.get("customer_country", "")),
            cls="grid grid-cols-2 md:grid-cols-4 gap-4",
        ),
        cls="bg-white border border-slate-200 rounded-xl p-5 mb-5",
    )


def _wizard_customer_edit_overlay(
    customer: dict,
    countries: list,
    states: list,
    error: str = "",
) -> Div:
    cid = str(customer.get("id", "") or "")

    body_children = []
    if error:
        body_children.append(alert("error", error))
    body_children.append(
        Div(
            _field(
                name="party_name",
                label="Company name",
                value=customer.get("party_name", "") or "",
                required=True,
            ),
            _field(
                name="tin",
                label="TIN",
                value=customer.get("tin", "") or "",
                placeholder="12345678-0001",
                required=True,
                helper="FIRS format: NNNNNNNN-NNNN",
            ),
            _field(
                name="email",
                label="Email",
                type="email",
                value=customer.get("email", "") or "",
                required=True,
            ),
            _field(
                name="telephone",
                label="Telephone",
                value=customer.get("telephone", "") or "",
                required=True,
            ),
            _field(
                name="street_name",
                label="Street",
                value=customer.get("street_name", "") or "",
                required=True,
            ),
            _field(
                name="city_name",
                label="City",
                value=customer.get("city_name", "") or "",
                required=True,
            ),
            _field(
                name="postal_zone",
                label="Postal zone",
                value=customer.get("postal_zone", "") or "",
                required=True,
            ),
            _field(
                name="lga",
                label="LGA (optional)",
                value=customer.get("lga", "") or "",
            ),
            country_state_fields(
                country_value=customer.get("country", "") or "NG",
                state_value=customer.get("state", "") or "",
                countries=countries,
                ng_states=states,
                required=True,
                field_id_prefix="wizard_edit_addr",
            ),
            cls="grid grid-cols-1 md:grid-cols-2 gap-x-4",
        )
    )

    return Div(
        Div(
            Form(
                Div(
                    Div(
                        H3(
                            "Edit customer",
                            cls="text-lg font-bold text-slate-900",
                        ),
                        P(
                            "Saves to your customer list and updates this invoice.",
                            cls="text-sm text-slate-500 mt-0.5",
                        ),
                        cls="flex-1 min-w-0",
                    ),
                    Button(
                        icon("x", cls="h-4 w-4"),
                        type="button",
                        hx_get="/invoices/wizard/modal/clear",
                        hx_target="#wizard-modal-area",
                        hx_swap="innerHTML",
                        cls="p-1.5 rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-700 shrink-0",
                    ),
                    cls="flex items-start justify-between gap-3 px-6 py-4 border-b border-slate-200",
                ),
                Div(
                    *body_children,
                    cls="px-6 py-5 max-h-[65vh] overflow-auto",
                ),
                Div(
                    Button(
                        Span("Cancel"),
                        type="button",
                        hx_get="/invoices/wizard/modal/clear",
                        hx_target="#wizard-modal-area",
                        hx_swap="innerHTML",
                        cls="px-4 py-2 bg-white border border-slate-300 text-slate-700 text-sm font-medium rounded-lg hover:bg-slate-50",
                    ),
                    Button(
                        icon("check-circle", cls="h-4 w-4"),
                        Span("Save customer"),
                        type="submit",
                        cls="inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700",
                    ),
                    cls="flex justify-end gap-2 px-6 py-4 border-t border-slate-200 bg-slate-50 rounded-b-2xl",
                ),
                hx_post=f"/invoices/wizard/customer/{cid}/edit",
                hx_target="#wizard-modal-area",
                hx_swap="innerHTML",
                method="post",
                action=f"/invoices/wizard/customer/{cid}/edit",
                cls="flex flex-col",
            ),
            cls="bg-white border border-slate-200 rounded-2xl w-full max-w-3xl shadow-lg overflow-hidden",
        ),
        cls="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 backdrop-blur-xs p-4",
    )


def _customers_data_script(customers: list) -> Script:
    rows = []
    for c in customers:
        rows.append(
            {
                "id": str(c.get("id", "")),
                "tin": c.get("tin", "") or "",
                "party_name": c.get("party_name", "") or "",
                "email": c.get("email", "") or "",
                "telephone": c.get("telephone", "") or "",
                "street_name": c.get("street_name", "") or "",
                "city_name": c.get("city_name", "") or "",
                "postal_zone": c.get("postal_zone", "") or "",
                "country": c.get("country", "") or "",
                "state": c.get("state", "") or "",
                "lga": c.get("lga", "") or "",
            }
        )
    js = (
        "window.__zefeCustomers = "
        + json.dumps(rows)
        + ";"
        + """
window.zefeFillCustomer = function(sel) {
  var id = sel.value;
  var row = (window.__zefeCustomers || []).find(function(c){return c.id === id;});
  var fields = ['tin','party_name','email','telephone','street_name','city_name','postal_zone','country','state','lga'];
  var lockNotice = document.getElementById('customer-lock-notice');
  var unlockNotice = document.getElementById('customer-unlock-notice');
  
  if (!row) {
    fields.forEach(function(f){
      var el = document.getElementById('customer_'+f);
      if(el) {
        el.value = '';
        el.removeAttribute('readonly');
        el.classList.remove('bg-slate-50', 'text-slate-500', 'cursor-not-allowed');
      }
    });
    if(lockNotice) lockNotice.style.display = 'none';
    if(unlockNotice) unlockNotice.style.display = 'block';
    return;
  }
  fields.forEach(function(f){
    var el = document.getElementById('customer_'+f);
    if(el) {
      el.value = row[f] || '';
      el.setAttribute('readonly', 'true');
      el.classList.add('bg-slate-50', 'text-slate-500', 'cursor-not-allowed');
    }
  });
  if(lockNotice) lockNotice.style.display = 'block';
  if(unlockNotice) unlockNotice.style.display = 'none';
};
document.addEventListener('DOMContentLoaded', function() {
  var sel = document.getElementById('customer_id');
  if(sel && sel.value) window.zefeFillCustomer(sel);
});
"""
    )
    return Script(js)


def _render_step2(
    *,
    wizard: dict,
    profile: dict,
    customers: list,
    states: list,
    countries: list,
    error: str = "",
    success: str = "",
) -> Div:
    selected = str(wizard.get("customer_id", "") or "")
    has_selected = bool(selected) and bool(wizard.get("customer_party_name"))

    def cv(field: str, default: str = "") -> str:
        return wizard.get(f"customer_{field}", default) or ""

    customer_field_names = (
        "tin",
        "party_name",
        "email",
        "telephone",
        "street_name",
        "city_name",
        "postal_zone",
        "country",
        "state",
        "lga",
    )

    if has_selected:
        hidden_fields = [Hidden(name="customer_id", value=selected)]
        hidden_fields.extend(
            Hidden(name=f"customer_{f}", value=cv(f))
            for f in customer_field_names
        )
        form = Form(
            _banner(error, success),
            *hidden_fields,
            _wizard_actions(next_label="Next: line items"),
            method="post",
            action="/invoices/wizard/step/2",
        )
        customer_card = card(
            Div(
                H3(
                    "Customer",
                    cls="text-base font-semibold text-slate-900",
                ),
                P(
                    "Using a saved customer. Use Edit to update their details, or choose a different one.",
                    cls="text-xs text-slate-500",
                ),
                cls="mb-4",
            ),
            _selected_customer_summary(wizard),
            form,
        )
    else:
        form = Form(
            _banner(error, success),
            _customer_picker(customers, ""),
            Div(
                _field(
                    name="customer_party_name",
                    label="Company name",
                    value=cv("party_name"),
                    required=True,
                ),
                _field(
                    name="customer_tin",
                    label="TIN",
                    value=cv("tin"),
                    placeholder="12345678-0001",
                    required=True,
                    helper="FIRS format: NNNNNNNN-NNNN",
                ),
                _field(
                    name="customer_email",
                    label="Email",
                    type="email",
                    value=cv("email"),
                    required=True,
                ),
                _field(
                    name="customer_telephone",
                    label="Telephone",
                    value=cv("telephone"),
                    required=True,
                ),
                _field(
                    name="customer_street_name",
                    label="Street",
                    value=cv("street_name"),
                    required=True,
                ),
                _field(
                    name="customer_city_name",
                    label="City",
                    value=cv("city_name"),
                    required=True,
                ),
                _field(
                    name="customer_postal_zone",
                    label="Postal zone",
                    value=cv("postal_zone"),
                    required=True,
                ),
                _field(
                    name="customer_lga",
                    label="LGA (optional)",
                    value=cv("lga"),
                ),
                country_state_fields(
                    country_value=cv("country", "NG"),
                    state_value=cv("state"),
                    countries=countries,
                    ng_states=states,
                    country_name="customer_country",
                    state_name="customer_state",
                    required=True,
                    field_id_prefix="wizard_customer_addr",
                ),
                cls="grid grid-cols-1 md:grid-cols-2 gap-x-4",
            ),
            _wizard_actions(next_label="Next: line items"),
            method="post",
            action="/invoices/wizard/step/2",
        )
        customer_card = card(
            Div(
                H3(
                    "Customer",
                    cls="text-base font-semibold text-slate-900",
                ),
                P(
                    "Pick a saved customer or fill in details for a one-off invoice.",
                    cls="text-xs text-slate-500",
                ),
                cls="mb-4",
            ),
            form,
        )

    return Div(
        _supplier_summary(profile),
        customer_card,
        Div(id="wizard-modal-area"),
    )


_ROW_INPUT_CLS = (
    "w-full px-2 py-1.5 bg-white text-slate-900 border border-slate-300 "
    "rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
)
_ROW_SELECT_CLS = (
    "w-full appearance-none px-2 py-1.5 pr-7 bg-white text-slate-900 "
    "border border-slate-300 rounded-lg text-sm focus:outline-none "
    "focus:ring-2 focus:ring-indigo-500"
)
_ROW_CHEV_CLS = (
    "h-3.5 w-3.5 text-slate-400 absolute right-2 top-1/2 "
    "-translate-y-1/2 pointer-events-none"
)
_ROW_TD = "px-3 py-3 align-middle"
_ROW_TH = (
    "px-3 py-2.5 text-left text-[11px] font-semibold text-slate-500 "
    "uppercase tracking-wider"
)
_ROW_TH_RIGHT = (
    "px-3 py-2.5 text-right text-[11px] font-semibold text-slate-500 "
    "uppercase tracking-wider"
)


def _fmt_num(value, default: str = "") -> str:
    """Render a stored numeric line value for an input, without noise."""
    if value is None or str(value).strip() == "":
        return default
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return str(value)


def _line_catalog_id(line: dict) -> str:
    return str((line or {}).get("catalog_item_id") or "").strip()


def _is_catalog_line(line: dict) -> bool:
    return bool(_line_catalog_id(line))


def _empty_row_line(default_unit: str = DEFAULT_UNIT_CODE) -> dict:
    """A blank invoice row, ready for a saved item or a one-off line."""
    return {
        "name": "",
        "description": "",
        "sellers_item_identification": "",
        "hsn_code": "",
        "product_category": "",
        "isic_code": "",
        "service_category": "",
        "invoiced_quantity": 1.0,
        "price_amount": 0.0,
        "price_unit": coerce_unit_code(default_unit),
        "base_quantity": 1.0,
        "discount_rate": 0.0,
        "discount_amount": 0.0,
        "fee_rate": 0.0,
        "fee_amount": 0.0,
        "catalog_item_id": "",
    }


def _normalize_line(line: dict, default_unit: str = DEFAULT_UNIT_CODE) -> dict:
    """Coerce a stored line into the exact shape the backend expects.

    Only the wizard-local ``catalog_item_id`` is added; every FIRS/NRS field
    keeps its existing name, type and meaning so assembly, validation and the
    official unit codes behave exactly as before.
    """
    out = dict(line or {})
    qty = _safe_float(out.get("invoiced_quantity"), 1.0)
    out["invoiced_quantity"] = qty
    out["price_amount"] = _safe_float(out.get("price_amount"), 0.0)
    base = _safe_float(out.get("base_quantity"), 1.0)
    out["base_quantity"] = base if base > 0 else 1.0
    for key in (
        "discount_rate",
        "discount_amount",
        "fee_rate",
        "fee_amount",
    ):
        out[key] = _safe_float(out.get(key), 0.0)
    out["price_unit"] = coerce_unit_code(out.get("price_unit"), default_unit)
    for key in (
        "name",
        "description",
        "sellers_item_identification",
        "hsn_code",
        "product_category",
        "isic_code",
        "service_category",
    ):
        out[key] = str(out.get(key) or "").strip()
    out["catalog_item_id"] = _line_catalog_id(out)
    return out


def _adjust_type(line: dict, prefix: str) -> str:
    if _safe_float(line.get(f"{prefix}_rate")) > 0:
        return "percent"
    if _safe_float(line.get(f"{prefix}_amount")) > 0:
        return "flat"
    return "none"


def _adjust_value(line: dict, prefix: str) -> str:
    kind = _adjust_type(line, prefix)
    if kind == "percent":
        return _fmt_num(line.get(f"{prefix}_rate"), "")
    if kind == "flat":
        return _fmt_num(line.get(f"{prefix}_amount"), "")
    return ""


def _apply_row_form(
    line: dict,
    form,
    default_unit: str,
    ignore: tuple[str, ...] = (),
) -> tuple[dict, str]:
    """Apply the inline row inputs onto a line. Returns (line, error)."""
    out = dict(line or {})
    err = ""

    if "quantity" not in ignore:
        raw = form.get("quantity")
        if raw is not None and str(raw).strip() != "":
            qty = _safe_float(raw, 0.0)
            if qty < 0:
                err = err or "Quantity cannot be negative."
            else:
                out["invoiced_quantity"] = qty

    if "unit_price" not in ignore:
        raw = form.get("unit_price")
        if raw is not None and str(raw).strip() != "":
            price = _safe_float(raw, 0.0)
            if price < 0:
                err = err or "Unit price cannot be negative."
            else:
                out["price_amount"] = price

    for prefix, label in (
        ("discount", "Discount"),
        ("fee", "Additional charge"),
    ):
        kind = (form.get(f"{prefix}_type") or "none").strip().lower()
        if kind not in ("none", "percent", "flat"):
            kind = "none"
        raw = form.get(f"{prefix}_value")
        value = (
            _safe_float(raw, 0.0)
            if raw is not None and str(raw).strip() != ""
            else 0.0
        )
        if kind == "none":
            out[f"{prefix}_rate"] = 0.0
            out[f"{prefix}_amount"] = 0.0
            continue
        if value < 0:
            err = err or f"{label} cannot be negative."
            continue
        if kind == "percent":
            if value > 100:
                err = err or f"{label} percent must be between 0 and 100."
                continue
            out[f"{prefix}_rate"] = value
            out[f"{prefix}_amount"] = 0.0
        else:
            out[f"{prefix}_rate"] = 0.0
            out[f"{prefix}_amount"] = value

    return out, err


def _row_update_attrs(idx: int) -> dict:
    """Inline row inputs: post the whole row, swap rows, OOB swap totals.

    ``hx_sync`` keeps only the newest in-flight row request, and because every
    request carries every field of the row no edit can be lost by an abort.
    """
    return {
        "hx_post": f"/invoices/wizard/line/{idx}/update",
        "hx_trigger": "change",
        "hx_target": "#line-rows",
        "hx_swap": "outerHTML",
        "hx_include": f"#line-row-{idx} [data-row-field]",
        "hx_sync": "closest tbody:replace",
        "data_row_field": "1",
    }


def _source_badge(line: dict) -> Span:
    """Where this line came from: the catalog, or typed once for this invoice.

    Shared with the Items page presentation layer so the pills match.
    """
    return item_source_badge(_is_catalog_line(line))


def _row_classification_badge(line: dict) -> Span:
    """HS / ISIC chip, identical to the one the Items page renders."""
    return item_classification_badge(line)


def _row_identity_cell(line: dict) -> Td:
    """Read-only identity for the row. Editing happens in the line modal."""
    return Td(
        item_identity(
            line,
            badges=[_source_badge(line), _row_classification_badge(line)],
            fallback_name="Details needed",
        ),
        cls=f"{_ROW_TD} min-w-[17rem] max-w-[24rem]",
    )


def _row_adjust_cell(idx: int, line: dict, prefix: str, label: str) -> Td:
    """Discount / additional charge: a fixed-width type select then a value."""
    kind = _adjust_type(line, prefix)
    value_attrs = {
        "id": f"line-{idx}-{prefix}-value",
        "name": f"{prefix}_value",
        "type": "number",
        "value": _adjust_value(line, prefix),
        "min": "0",
        "step": "0.01",
        "placeholder": "0",
        "aria_label": f"{label} value for line {idx + 1}",
    }
    if kind == "none":
        value_attrs["disabled"] = True
        value_attrs["placeholder"] = "-"
    return Td(
        Div(
            Div(
                Select(
                    Option("None", value="none", selected=(kind == "none")),
                    Option(
                        "Percent",
                        value="percent",
                        selected=(kind == "percent"),
                    ),
                    Option("Fixed", value="flat", selected=(kind == "flat")),
                    name=f"{prefix}_type",
                    aria_label=f"{label} type for line {idx + 1}",
                    **_row_update_attrs(idx),
                    cls=_ROW_SELECT_CLS,
                ),
                icon("chevron-down", cls=_ROW_CHEV_CLS),
                cls="relative w-[7.5rem] shrink-0",
            ),
            Input(
                **value_attrs,
                **_row_update_attrs(idx),
                cls=f"{_ROW_INPUT_CLS} w-24 text-right shrink-0",
            ),
            cls="flex items-center gap-2",
        ),
        cls=f"{_ROW_TD} w-[15rem]",
    )


def _line_row(idx: int, line: dict, currency: str) -> Tr:
    qty = _safe_float(line.get("invoiced_quantity", 1), 1.0)
    price = _safe_float(line.get("price_amount", 0))
    unit = coerce_unit_code(line.get("price_unit"))
    total = _line_extension(line)
    return Tr(
        Td(
            Span(
                idx + 1,
                cls="text-xs font-semibold text-slate-400",
            ),
            cls="px-3 py-3 align-middle w-10",
        ),
        _row_identity_cell(line),
        Td(
            Input(
                id=f"line-{idx}-quantity",
                name="quantity",
                type="number",
                value=_fmt_num(qty, "1"),
                min="0",
                step="1",
                aria_label=f"Quantity for line {idx + 1}",
                **_row_update_attrs(idx),
                cls=f"{_ROW_INPUT_CLS} w-20 text-right",
            ),
            cls=f"{_ROW_TD} w-24",
        ),
        Td(
            Div(
                Input(
                    id=f"line-{idx}-unit-price",
                    name="unit_price",
                    type="number",
                    value=_fmt_num(price, "0"),
                    min="0",
                    step="0.01",
                    aria_label=f"Unit price for line {idx + 1}",
                    **_row_update_attrs(idx),
                    cls=f"{_ROW_INPUT_CLS} w-28 text-right",
                ),
                unit_chip(unit, unit_code_label(unit)),
                cls="flex items-center justify-end gap-2",
            ),
            cls=f"{_ROW_TD} w-[11rem]",
        ),
        _row_adjust_cell(idx, line, "discount", "Discount"),
        _row_adjust_cell(idx, line, "fee", "Additional charge"),
        Td(
            P(
                f"{currency} {total:,.2f}",
                cls=(
                    "text-sm font-semibold text-slate-900 text-right "
                    "whitespace-nowrap"
                ),
            ),
            cls=f"{_ROW_TD} w-36",
        ),
        Td(
            Div(
                Button(
                    icon("eye", cls="h-4 w-4"),
                    type="button",
                    title="Open line details",
                    aria_label=f"Open details for line {idx + 1}",
                    hx_get=f"/invoices/wizard/line/{idx}/edit",
                    hx_target="#wizard-modal-area",
                    hx_swap="innerHTML",
                    cls=(
                        "p-2 rounded-lg text-slate-400 hover:bg-slate-100 "
                        "hover:text-indigo-600 transition-colors"
                    ),
                ),
                Button(
                    icon("trash", cls="h-4 w-4"),
                    type="button",
                    title="Remove line",
                    aria_label=f"Remove line {idx + 1}",
                    hx_post="/invoices/wizard/step/3/remove",
                    hx_vals=json.dumps({"idx": str(idx)}),
                    hx_target="#line-rows",
                    hx_swap="outerHTML",
                    cls=(
                        "p-2 rounded-lg text-slate-400 hover:bg-rose-50 "
                        "hover:text-rose-600 transition-colors"
                    ),
                ),
                cls="flex items-center justify-end gap-1",
            ),
            cls=f"{_ROW_TD} text-right w-24",
        ),
        id=f"line-row-{idx}",
        cls=(
            "border-b border-slate-100 last:border-b-0 "
            "hover:bg-slate-50/50 transition-colors"
        ),
    )


def _add_actions(compact: bool = False) -> Div:
    """The two ways to add a line. They never compete inside one surface."""
    size = "px-3 py-1.5 text-xs" if compact else "px-4 py-2 text-sm"
    return Div(
        Button(
            icon("package", cls="h-4 w-4"),
            Span("Add saved item"),
            type="button",
            title="Search your catalog and add a saved item",
            hx_get="/invoices/wizard/line/picker",
            hx_target="#wizard-modal-area",
            hx_swap="innerHTML",
            cls=(
                f"inline-flex items-center gap-2 {size} bg-indigo-600 "
                "text-white font-medium rounded-lg hover:bg-indigo-700 "
                "shadow-sm"
            ),
        ),
        Button(
            icon("plus", cls="h-4 w-4"),
            Span("Add one-off item"),
            type="button",
            title="Type the item details once for this invoice only",
            hx_get="/invoices/wizard/line/one-off",
            hx_target="#wizard-modal-area",
            hx_swap="innerHTML",
            cls=(
                f"inline-flex items-center gap-2 {size} bg-white border "
                "border-slate-300 text-slate-700 font-medium rounded-lg "
                "hover:bg-slate-50 hover:border-indigo-300 "
                "hover:text-indigo-700"
            ),
        ),
        cls="flex items-center gap-2 flex-wrap",
    )


def _line_rows_table(wizard: dict) -> Div:
    lines = (wizard.get("step3", {}) or {}).get("lines", []) or []
    currency = wizard.get("document_currency_code", "NGN") or "NGN"
    if not lines:
        return Div(
            icon("receipt", cls="h-9 w-9 text-slate-300 mx-auto mb-3"),
            P(
                "No lines yet",
                cls="text-base font-semibold text-slate-900",
            ),
            P(
                "Add a saved item from your catalog, or add a one-off item "
                "for something you invoice only this once.",
                cls="text-sm text-slate-500 mt-1 max-w-md mx-auto",
            ),
            Div(_add_actions(), cls="flex justify-center mt-4"),
            cls=(
                "text-center py-12 bg-white rounded-2xl border "
                "border-dashed border-slate-300"
            ),
        )
    return Div(
        Table(
            Thead(
                Tr(
                    Th("#", cls=f"{_ROW_TH} w-10"),
                    Th("Item", cls=_ROW_TH),
                    Th("Qty", cls=_ROW_TH_RIGHT),
                    Th("Unit price", cls=_ROW_TH_RIGHT),
                    Th("Discount", cls=_ROW_TH),
                    Th("Additional charge", cls=_ROW_TH),
                    Th("Line total", cls=_ROW_TH_RIGHT),
                    Th(
                        Span("Actions", cls="sr-only"),
                        cls="px-3 py-2.5",
                    ),
                    cls="border-b border-slate-200 bg-slate-50",
                ),
            ),
            Tbody(
                *[_line_row(i, line, currency) for i, line in enumerate(lines)]
            ),
            cls="table-auto w-full min-w-[64rem]",
        ),
        cls="overflow-x-auto rounded-2xl border border-slate-200 bg-white",
    )


def _rows_container(
    wizard: dict,
    banner=None,
    oob: bool = False,
) -> Div:
    attrs: dict = {"id": "line-rows"}
    if oob:
        attrs["hx_swap_oob"] = "outerHTML"
    lines = (wizard.get("step3", {}) or {}).get("lines", []) or []
    footer = (
        Div(
            P(
                "Need another line?",
                cls="text-xs text-slate-500",
            ),
            _add_actions(compact=True),
            cls="flex items-center justify-between gap-3 flex-wrap mt-3",
        )
        if lines
        else ""
    )
    return Div(
        banner or "",
        _line_rows_table(wizard),
        footer,
        **attrs,
    )


def _totals_card(wizard: dict, oob: bool = False) -> Div:
    lines = (wizard.get("step3", {}) or {}).get("lines", []) or []
    subtotal = sum(_line_extension(line) for line in lines)
    tax = subtotal * TAX_RATE
    total = subtotal + tax
    currency = wizard.get("document_currency_code", "NGN") or "NGN"
    attrs: dict = {"id": "line-totals"}
    if oob:
        attrs["hx_swap_oob"] = "outerHTML"
    return Div(
        Div(
            P("Subtotal", cls="text-sm text-slate-600"),
            P(
                f"{currency} {subtotal:,.2f}",
                cls="text-sm font-medium text-slate-900",
            ),
            cls="flex items-center justify-between py-1.5",
        ),
        Div(
            P("VAT (7.5%)", cls="text-sm text-slate-600"),
            P(
                f"{currency} {tax:,.2f}",
                cls="text-sm font-medium text-slate-900",
            ),
            cls="flex items-center justify-between py-1.5",
        ),
        Div(
            P(
                "Total payable",
                cls="text-base font-semibold text-slate-900",
            ),
            P(
                f"{currency} {total:,.2f}",
                cls="text-lg font-bold text-indigo-700",
            ),
            cls=(
                "flex items-center justify-between py-2 border-t "
                "border-slate-200 mt-2"
            ),
        ),
        P(
            "Totals recalculate as soon as a row changes.",
            cls="text-[11px] text-slate-400 mt-1",
        ),
        cls="bg-white border border-slate-200 rounded-2xl p-5 mt-4",
        **attrs,
    )


def _rows_response(
    wizard: dict,
    banner=None,
    oob_rows: bool = False,
    close_modal: bool = False,
) -> tuple:
    """Rows container (swap target) plus totals, and optionally close a modal."""
    parts: list = [
        _rows_container(wizard, banner=banner, oob=oob_rows),
        _totals_card(wizard, oob=True),
    ]
    if close_modal:
        parts.append(Div(id="wizard-modal-area", hx_swap_oob="innerHTML"))
    return tuple(parts)


def _lookup_hit_row(hit: dict) -> Button:
    kind = hit.get("kind", "product")
    code = hit.get("code", "")
    label = hit.get("label", "")
    category = hit.get("category", "") or label
    code_prefix = "HS" if kind == "product" else "ISIC"
    return Button(
        Div(
            Div(
                item_kind_badge(kind),
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
        hx_get="/invoices/wizard/line/lookup/apply",
        hx_vals=json.dumps(
            {
                "kind": kind,
                "code": code,
                "label": label,
                "category": category,
            }
        ),
        hx_include=(
            "[name='invoiced_quantity'],[name='price_amount'],"
            "[name='sellers_item_identification'],"
            "[name='base_quantity'],[name='price_unit']"
        ),
        hx_target="#line-form-fields",
        hx_swap="outerHTML",
        cls="w-full px-3 py-3 hover:bg-indigo-50 border-b border-slate-100 last:border-b-0 text-left transition-colors cursor-pointer block",
    )


def _paired_adjustment_field(
    *, prefix: str, label: str, line: dict, helper: str = ""
) -> Div:
    rate_key = f"{prefix}_rate"
    amount_key = f"{prefix}_amount"
    try:
        rate_val = float(line.get(rate_key) or 0)
    except (TypeError, ValueError):
        rate_val = 0.0
    try:
        amt_val = float(line.get(amount_key) or 0)
    except (TypeError, ValueError):
        amt_val = 0.0
    if rate_val > 0:
        selected_type = "percent"
        value_str = str(line.get(rate_key) or "")
    elif amt_val > 0:
        selected_type = "flat"
        value_str = str(line.get(amount_key) or "")
    else:
        selected_type = "percent"
        value_str = ""
    if value_str in ("0", "0.0", "0.00"):
        value_str = ""

    type_name = f"{prefix}_type"
    value_name = f"{prefix}_value"

    chev_cls = (
        "h-4 w-4 text-slate-400 absolute right-3 top-1/2 "
        "-translate-y-1/2 pointer-events-none"
    )

    return Div(
        Label(
            label,
            fr=value_name,
            cls="block text-sm font-medium text-slate-700 mb-1.5",
        ),
        Div(
            Div(
                Select(
                    Option(
                        "Percent (%)",
                        value="percent",
                        selected=(selected_type == "percent"),
                    ),
                    Option(
                        "Flat amount",
                        value="flat",
                        selected=(selected_type == "flat"),
                    ),
                    id=type_name,
                    name=type_name,
                    cls=(
                        "w-full appearance-none px-3 py-2 pr-9 bg-white "
                        "text-slate-900 border border-slate-300 rounded-lg "
                        "text-sm focus:outline-none focus:ring-2 "
                        "focus:ring-indigo-500"
                    ),
                ),
                icon("chevron-down", cls=chev_cls),
                cls="relative w-36 shrink-0",
            ),
            Input(
                id=value_name,
                name=value_name,
                type="number",
                value=value_str,
                placeholder="0",
                min="0",
                step="0.01",
                cls=(
                    "flex-1 min-w-0 px-3 py-2 bg-white text-slate-900 "
                    "border border-slate-300 rounded-lg text-sm "
                    "placeholder-slate-400 focus:outline-none focus:ring-2 "
                    "focus:ring-indigo-500"
                ),
            ),
            cls="flex items-stretch gap-2",
        ),
        guidance_text(
            helper
            or (
                "Choose Percent (0–100) or Flat amount (≥ 0). "
                "Leave blank for none."
            )
        ),
        cls="mb-4",
    )


def _catalog_item_row(item: dict, idx: int = -1) -> Button:
    """One saved catalog item. Selecting it adds (or replaces) a locked line.

    Presented with exactly the same badges, HS / ISIC chip, unit chip and SKU
    treatment as a row on the Items page.
    """
    unit = coerce_unit_code(item.get("price_unit"))
    return Button(
        Div(
            Div(
                item_kind_badge(item_kind(item)),
                P(
                    item.get("name", ""),
                    cls=(
                        "text-sm font-medium text-slate-900 text-left "
                        "whitespace-normal break-words"
                    ),
                ),
                cls="flex items-start gap-2 min-w-0",
            ),
            Div(
                item_classification_badge(item),
                item_sku_text(item.get("sku"), inline=True),
                unit_chip(unit, unit_code_label(unit)),
                item_price_summary(item.get("unit_price"), unit),
                cls="flex items-center gap-1.5 flex-wrap mt-1.5",
            ),
            cls="min-w-0 w-full",
        ),
        type="button",
        hx_post="/invoices/wizard/line/catalog/apply",
        hx_vals=json.dumps(
            {"item_id": str(item.get("id", "")), "idx": str(idx)}
        ),
        hx_target="#line-rows",
        hx_swap="outerHTML",
        cls=(
            "w-full px-3 py-3 hover:bg-indigo-50 border-b border-slate-100 "
            "last:border-b-0 text-left transition-colors cursor-pointer block"
        ),
    )


def _catalog_results(items: list[dict], query: str, idx: int = -1) -> Div:
    if not items:
        searching = bool((query or "").strip())
        title, subtitle = item_search_empty_copy(
            query=query,
            noun="saved items",
            empty_title="No saved items yet",
            empty_subtitle=(
                "Build your catalog to reuse lines across invoices, or close "
                "this and use Add one-off item."
            ),
            extra_hint=(
                "If it is not in your catalog, close this and use Add "
                "one-off item instead."
            ),
        )
        # The catalog link only belongs here when there is nothing to pick
        # from at all; a no-match search stays inside the invoice flow.
        action = None
        if not searching:
            action = A(
                icon("package", cls="h-3 w-3"),
                Span("Manage items"),
                href="/items",
                target="_blank",
                cls=(
                    "inline-flex items-center gap-1.5 text-xs "
                    "font-medium text-indigo-600 hover:underline"
                ),
            )
        return item_empty_panel(
            title,
            subtitle,
            action,
            icon_name="search" if searching else "package",
            id="catalog-results",
        )
    return Div(
        *[_catalog_item_row(i, idx) for i in items[:20]],
        id="catalog-results",
        cls=(
            "mt-2 max-h-72 overflow-auto rounded-xl border border-slate-200 "
            "bg-white shadow-xs animate-fade-in-up"
        ),
    )


def _picker_search_input(query: str, idx: int) -> Div:
    return Div(
        icon(
            "search",
            cls=(
                "h-4 w-4 text-slate-400 absolute left-3 top-1/2 "
                "-translate-y-1/2 pointer-events-none"
            ),
        ),
        Input(
            type="search",
            name="catalog_q",
            id="catalog-q-input",
            placeholder="Search saved items by name or SKU…",
            value=query,
            autocomplete="off",
            autofocus=True,
            hx_get="/invoices/wizard/line/catalog",
            hx_vals=json.dumps({"idx": str(idx)}),
            hx_trigger="keyup changed delay:300ms, search",
            hx_target="#catalog-results",
            hx_swap="outerHTML",
            hx_indicator="#catalog-spinner",
            cls=(
                "w-full pl-9 pr-9 py-2 bg-white text-slate-900 "
                "border border-slate-300 rounded-lg text-sm "
                "focus:outline-none focus:ring-2 focus:ring-indigo-500"
            ),
        ),
        Div(
            icon("loader", cls="h-4 w-4 text-indigo-500 animate-spin"),
            id="catalog-spinner",
            cls=(
                "htmx-indicator absolute right-3 top-1/2 "
                "-translate-y-1/2 pointer-events-none"
            ),
        ),
        cls="relative",
    )


def _saved_item_picker_modal(
    query: str = "",
    items: list[dict] | None = None,
    idx: int = -1,
) -> Div:
    """Search-first picker for the saved-item flow. No manual fields here."""
    items = items or []
    replacing = idx >= 0
    title = (
        f"Replace the saved item on line {idx + 1}"
        if replacing
        else "Add a saved item"
    )
    subtitle = (
        "Search your catalog and pick the replacement. Quantity, discount "
        "and additional charge on the line are kept."
        if replacing
        else "Search your catalog. The item identity and classification stay "
        "locked on the invoice, so only the numbers are yours to set."
    )
    return Div(
        Div(
            Div(
                Div(
                    H3(title, cls="text-lg font-bold text-slate-900"),
                    P(subtitle, cls="text-sm text-slate-500 mt-0.5"),
                    cls="flex-1 min-w-0",
                ),
                Button(
                    icon("x", cls="h-4 w-4"),
                    type="button",
                    hx_get="/invoices/wizard/modal/clear",
                    hx_target="#wizard-modal-area",
                    hx_swap="innerHTML",
                    cls=(
                        "p-1.5 rounded-lg text-slate-400 "
                        "hover:bg-slate-100 hover:text-slate-700 shrink-0"
                    ),
                ),
                cls=(
                    "flex items-start justify-between gap-3 px-6 py-4 "
                    "border-b border-slate-200"
                ),
            ),
            Div(
                _picker_search_input(query, idx),
                _catalog_results(items, query, idx),
                cls="px-6 py-5",
            ),
            Div(
                Button(
                    Span("Cancel"),
                    type="button",
                    hx_get="/invoices/wizard/modal/clear",
                    hx_target="#wizard-modal-area",
                    hx_swap="innerHTML",
                    cls=(
                        "px-4 py-2 bg-white border border-slate-300 "
                        "text-slate-700 text-sm font-medium rounded-lg "
                        "hover:bg-slate-50"
                    ),
                ),
                cls=(
                    "flex justify-end gap-2 px-6 py-4 border-t "
                    "border-slate-200 bg-slate-50 rounded-b-2xl"
                ),
            ),
            cls=(
                "bg-white border border-slate-200 rounded-2xl w-full "
                "max-w-2xl shadow-lg overflow-hidden"
            ),
        ),
        cls=(
            "fixed inset-0 z-50 flex items-center justify-center "
            "bg-slate-900/40 backdrop-blur-xs p-4"
        ),
    )


def _line_from_catalog_item(item: dict, quantity: str = "1") -> dict:
    """Merge a saved catalog item into a wizard line (quantity stays local)."""
    return {
        "catalog_item_id": str(item.get("id", "") or ""),
        "name": item.get("name", "") or "",
        "description": item.get("description", "") or "",
        "sellers_item_identification": item.get("sku", "") or "",
        "hsn_code": item.get("hsn_code", "") or "",
        "product_category": item.get("hsn_category", "") or "",
        "isic_code": item.get("isic_code", "") or "",
        "service_category": item.get("isic_category", "") or "",
        "invoiced_quantity": quantity or "1",
        "price_amount": str(item.get("unit_price", "") or ""),
        "price_unit": coerce_unit_code(item.get("price_unit")),
        "base_quantity": str(item.get("base_quantity", "1") or "1"),
    }


async def _load_catalog_items(
    jwt: str, sid: str, query: str = "", limit: int = 20
) -> list[dict]:
    """Active catalog items for the line picker (best-effort)."""
    try:
        res = await api_client.list_items(
            jwt,
            session_id=sid,
            search=(query or None),
            active=True,
            offset=0,
            limit=limit,
        )
        items = (res or {}).get("items", []) or []
        return [i for i in items if isinstance(i, dict)]
    except Exception:
        logger.exception("wizard: list_items failed")
        return []


def _locked_basis_row(line: dict, default_unit: str) -> Div:
    """Unit code and base quantity of a saved item, shown read only.

    The values still travel to the backend unchanged (hidden inputs), so the
    official unit-code validation is untouched.
    """
    unit = coerce_unit_code(line.get("price_unit"), default_unit)
    base = _fmt_num(line.get("base_quantity"), "1")

    def labelled(label: str, node) -> Div:
        return Div(
            P(
                label,
                cls=(
                    "text-[11px] font-semibold uppercase tracking-wider "
                    "text-slate-500"
                ),
            ),
            Div(node, cls="mt-1"),
        )

    return Div(
        labelled("Unit", unit_chip(unit, unit_code_label(unit))),
        labelled(
            "Price covers",
            Span(
                f"{base} unit(s)",
                cls=(
                    "inline-flex items-center px-2 py-0.5 rounded-md "
                    "text-[11px] font-mono font-semibold bg-white "
                    "text-slate-700 border border-slate-200 w-fit"
                ),
            ),
        ),
        Hidden(name="price_unit", value=unit),
        Hidden(name="base_quantity", value=base),
        cls="grid grid-cols-2 gap-4",
    )


def _pricing_section(line: dict, default_unit: str, manual: bool = True) -> Div:
    """Quantity, price and the unit basis, grouped where they are used."""
    children = [
        P(
            "Pricing on this invoice",
            cls=(
                "text-[11px] font-bold uppercase tracking-wider "
                "text-slate-500 mb-3"
            ),
        ),
        Div(
            _field(
                name="invoiced_quantity",
                label="Quantity",
                type="number",
                value=_fmt_num(line.get("invoiced_quantity"), "1"),
                required=True,
                helper="How many units you are billing on this line.",
                min="1",
                step="1",
            ),
            _field(
                name="price_amount",
                label="Unit price" if manual else "Unit price (this invoice)",
                type="number",
                value=_fmt_num(line.get("price_amount"), "0.00"),
                required=True,
                helper=(
                    "Price for a single unit."
                    if manual
                    else "Prefilled from the catalog. Changing it applies to "
                    "this invoice only."
                ),
                min="0.01",
                step="0.01",
            ),
            cls="grid grid-cols-1 md:grid-cols-2 gap-x-4",
        ),
    ]
    if manual:
        children.append(
            Div(
                _unit_select_field(line.get("price_unit") or default_unit),
                _field(
                    name="base_quantity",
                    label="Units the price covers",
                    type="number",
                    value=_fmt_num(line.get("base_quantity"), "1"),
                    required=True,
                    min="1",
                    step="1",
                    helper=(
                        "Leave at 1 unless the unit price covers a multi "
                        "unit pack."
                    ),
                ),
                cls="grid grid-cols-1 md:grid-cols-2 gap-x-4",
            )
        )
    else:
        children.append(_locked_basis_row(line, default_unit))
    return Div(
        *children,
        cls="p-4 bg-slate-50/60 rounded-xl border border-slate-200 mb-4",
    )


def _adjustments_section(line: dict) -> Div:
    return Div(
        P(
            "Discount and additional charge",
            cls=(
                "text-[11px] font-bold uppercase tracking-wider "
                "text-slate-500 mb-3"
            ),
        ),
        Div(
            _paired_adjustment_field(
                prefix="discount",
                label="Discount",
                line=line,
                helper=(
                    "Percent takes a % off the line, Flat amount takes a "
                    "fixed amount off. Leave blank for none."
                ),
            ),
            _paired_adjustment_field(
                prefix="fee",
                label="Additional charge",
                line=line,
                helper=(
                    "Percent adds a % surcharge, Flat amount adds a fixed "
                    "charge. Leave blank for none."
                ),
            ),
            cls="grid grid-cols-1 md:grid-cols-2 gap-x-4",
        ),
        cls="p-4 bg-white rounded-xl border border-slate-200",
    )


def _line_form_fields(
    line: dict,
    *,
    error: str = "",
    default_unit: str = DEFAULT_UNIT_CODE,
    manual: bool = True,
) -> Div:
    has_hsn = bool(line.get("hsn_code"))
    has_isic = bool(line.get("isic_code"))
    badge_kind = ""
    badge_code = ""
    if has_hsn:
        badge_kind = "Product"
        badge_code = f"HS {line['hsn_code']}"
    elif has_isic:
        badge_kind = "Service"
        badge_code = f"ISIC {line['isic_code']}"

    children = []
    if error:
        children.append(alert("error", error, cls="mb-3"))

    if badge_code:
        children.append(
            Div(
                icon(
                    "check-circle",
                    cls="h-4 w-4 text-emerald-600 shrink-0",
                ),
                Span(
                    "Classification attached",
                    cls="text-xs font-medium text-emerald-700",
                ),
                Span(
                    badge_kind,
                    cls=(
                        "ml-auto inline-flex items-center px-2 py-0.5 "
                        "rounded-full text-[10px] font-semibold uppercase "
                        "tracking-wider bg-white text-emerald-700 "
                        "border border-emerald-200 shrink-0"
                    ),
                ),
                Span(
                    badge_code,
                    cls=(
                        "inline-flex items-center px-2 py-0.5 rounded-md "
                        "text-[11px] font-mono font-semibold bg-white "
                        "text-emerald-800 border border-emerald-200 shrink-0"
                    ),
                ),
                cls=(
                    "flex items-center gap-2 mb-4 p-2.5 bg-emerald-50 "
                    "rounded-lg border border-emerald-200"
                ),
            )
        )

    children.extend(
        [
            Hidden(name="catalog_item_id", value=_line_catalog_id(line)),
            Hidden(name="hsn_code", value=line.get("hsn_code", "") or ""),
            Hidden(
                name="product_category",
                value=line.get("product_category", "") or "",
            ),
            Hidden(name="isic_code", value=line.get("isic_code", "") or ""),
            Hidden(
                name="service_category",
                value=line.get("service_category", "") or "",
            ),
        ]
    )

    if manual:
        children.append(
            Div(
                _field(
                    name="name",
                    label="Item name",
                    value=line.get("name", "") or "",
                    placeholder="Web design services",
                    required=True,
                    helper="This is what prints on the invoice line.",
                ),
                _field(
                    name="sellers_item_identification",
                    label="SKU (optional)",
                    value=line.get("sellers_item_identification", "") or "",
                    placeholder="Your internal code",
                    helper="Only if you track your own item codes.",
                ),
                cls="grid grid-cols-1 md:grid-cols-2 gap-x-4",
            )
        )
        children.append(
            _field(
                name="description",
                label="Description (optional)",
                value=line.get("description", "") or "",
                placeholder="Extra detail for this line",
                helper="Kept on the invoice record for your reference.",
            )
        )
    else:
        # A catalog backed row keeps the saved item identity intact; only the
        # invoice specific numbers below are editable here.
        children.extend(
            [
                Hidden(name="name", value=line.get("name", "") or ""),
                Hidden(
                    name="description",
                    value=line.get("description", "") or "",
                ),
                Hidden(
                    name="sellers_item_identification",
                    value=line.get("sellers_item_identification", "") or "",
                ),
            ]
        )

    children.append(_pricing_section(line, default_unit, manual))
    children.append(_adjustments_section(line))

    return Div(*children, id="line-form-fields")


def _lookup_empty_panel(query: str) -> Div:
    """Actionable empty state for the shared classification lookup."""
    children = [
        icon("search", cls="h-8 w-8 text-slate-300 mx-auto mb-2"),
        P(
            f"No relevant products or services found for “{query}”.",
            cls="text-sm font-semibold text-slate-700 text-center",
        ),
    ]
    if lookup_ranking.is_code_query(query):
        children.append(
            P(
                "That looks like a classification code, but nothing matches "
                "it on the FIRS gateway. Check the format: products use ",
                Span("XXXX.XX", cls="font-mono text-indigo-600"),
                " (HS), services use ",
                Span("XXXX", cls="font-mono text-indigo-600"),
                " (ISIC). You can also search by name instead.",
                cls=(
                    "text-xs text-slate-500 text-center mt-2 "
                    "leading-relaxed px-2"
                ),
            )
        )
    else:
        children.append(
            P(
                "Try a broader term, a single keyword, a synonym, or the "
                "classification code itself. Products use HS codes like ",
                Span("1006.10", cls="font-mono text-indigo-600"),
                " and services use ISIC codes like ",
                Span("0112", cls="font-mono text-indigo-600"),
                ". For example use ",
                Span("“footwear”", cls="font-mono text-indigo-600"),
                " instead of ",
                Span("“sneakers”", cls="font-mono text-slate-500"),
                ", or ",
                Span("“consultancy”", cls="font-mono text-indigo-600"),
                " instead of ",
                Span("“consult”", cls="font-mono text-slate-500"),
                ".",
                cls=(
                    "text-xs text-slate-500 text-center mt-2 "
                    "leading-relaxed px-2"
                ),
            )
        )
    return Div(
        Div(*children, cls="px-4 py-6"),
        id="lookup-results",
        cls=(
            "mt-2 rounded-lg border border-slate-200 bg-slate-50/60 "
            "animate-fade-in-up"
        ),
    )


def _lookup_results_panel(hits: list[dict], query: str) -> Div:
    if not query:
        return Div(id="lookup-results")
    if hits:
        return Div(
            *[_lookup_hit_row(h) for h in hits],
            id="lookup-results",
            cls=(
                "mt-2 max-h-72 overflow-auto rounded-lg border "
                "border-slate-200 bg-white shadow-xs animate-fade-in-up"
            ),
        )
    return _lookup_empty_panel(query)


def _lookup_block(
    lookup_query: str = "", lookup_hits: list[dict] | None = None
) -> Div:
    """Classification lookup. Shown only for one-off / manual line editing."""
    lookup_hits = lookup_hits or []
    return Div(
        Label(
            "Classification lookup",
            cls="block text-sm font-medium text-slate-700 mb-1.5",
        ),
        guidance_panel(
            "Not saved in your catalog yet? Search the FIRS classification "
            "list and attach a code to this one-off line.",
            cls="mb-3",
        ),
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
                    type="search",
                    name="lookup_q",
                    id="lookup-q-input",
                    placeholder=(
                        "Search by keyword or code, e.g. 'rice', "
                        "'consulting', '1006.10'"
                    ),
                    value=lookup_query,
                    autocomplete="off",
                    hx_get="/invoices/wizard/line/lookup",
                    hx_trigger="keyup changed delay:400ms, search",
                    hx_target="#lookup-results",
                    hx_swap="outerHTML",
                    hx_indicator="#lookup-spinner",
                    cls=(
                        "w-full pl-9 pr-9 py-2 bg-white text-slate-900 "
                        "border border-slate-300 rounded-lg text-sm "
                        "focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    ),
                ),
                Div(
                    icon(
                        "loader",
                        cls="h-4 w-4 text-indigo-500 animate-spin",
                    ),
                    id="lookup-spinner",
                    cls=(
                        "htmx-indicator absolute right-3 top-1/2 "
                        "-translate-y-1/2 pointer-events-none"
                    ),
                ),
                cls="relative",
            ),
            guidance_text(
                "Type at least 2 characters. Selecting a result attaches its "
                "code. Clearing the search keeps your selection."
            ),
            _lookup_results_panel(lookup_hits, lookup_query),
            cls="p-4 bg-slate-50 rounded-lg border border-slate-200",
        ),
        id="line-lookup-block",
        cls="mb-5",
    )


def _saved_item_summary(line: dict, idx: int = -1) -> Div:
    """Locked catalog identity for a saved-item line. No manual fields.

    Uses the same badges and identity block as the Items page and the
    saved-item picker, so a line and its catalog row read the same way. There
    is deliberately no catalog link here: the only action is swapping the
    saved item, which stays inside the invoice flow.
    """
    description = str(line.get("description", "") or "").strip()
    return Div(
        Div(
            Div(
                icon("package", cls="h-4 w-4 text-indigo-600 shrink-0"),
                P(
                    "Saved item",
                    cls=(
                        "text-[11px] font-bold uppercase tracking-wider "
                        "text-slate-500"
                    ),
                ),
                item_kind_badge(item_kind(line)),
                _row_classification_badge(line),
                cls="flex items-center gap-2 min-w-0 flex-wrap",
            ),
            Button(
                icon("search", cls="h-3 w-3"),
                Span("Change saved item"),
                type="button",
                hx_get="/invoices/wizard/line/picker",
                hx_vals=json.dumps({"idx": str(idx)}),
                hx_target="#wizard-modal-area",
                hx_swap="innerHTML",
                cls=(
                    "inline-flex items-center gap-1.5 px-2.5 py-1 bg-white "
                    "border border-indigo-300 text-indigo-700 text-xs "
                    "font-semibold rounded-lg hover:bg-indigo-50 shrink-0"
                ),
            )
            if idx >= 0
            else "",
            cls="flex items-center justify-between gap-3 mb-2",
        ),
        item_identity(line, fallback_name="Saved item"),
        P(description, cls="text-xs text-slate-500 mt-0.5")
        if description
        else "",
        guidance_text(
            "Name, description and classification are locked to your "
            "catalog. Only the numbers below apply to this invoice."
        ),
        cls="mb-5 p-4 bg-white rounded-xl border border-indigo-200",
    )


def _line_modal(
    *,
    edit_idx: int = -1,
    line: dict | None = None,
    error: str = "",
    lookup_query: str = "",
    lookup_hits: list[dict] | None = None,
    default_unit: str = DEFAULT_UNIT_CODE,
) -> Div:
    line = line or {}
    manual = not _is_catalog_line(line)
    is_edit = edit_idx >= 0
    if manual:
        title = (
            f"One-off line {edit_idx + 1}" if is_edit else "Add one-off item"
        )
        subtitle = (
            "Name the item, attach a FIRS classification code, then set the "
            "numbers for this invoice."
        )
    else:
        title = f"Saved item on line {edit_idx + 1}" if is_edit else "Line"
        subtitle = (
            "Set the quantity, price and charges for this invoice. Your "
            "catalog item is not changed."
        )
    submit_label = "Save line" if is_edit else "Add line"
    action = "/invoices/wizard/line/save"

    body: list = []
    if manual:
        body.append(_lookup_block(lookup_query, lookup_hits or []))
    else:
        body.append(_saved_item_summary(line, edit_idx))
    body.append(
        _line_form_fields(
            line, error=error, default_unit=default_unit, manual=manual
        )
    )

    return Div(
        Div(
            Form(
                Hidden(name="edit_idx", value=str(edit_idx)),
                Div(
                    Div(
                        H3(title, cls="text-lg font-bold text-slate-900"),
                        P(subtitle, cls="text-sm text-slate-500 mt-0.5"),
                        cls="flex-1 min-w-0",
                    ),
                    Button(
                        icon("x", cls="h-4 w-4"),
                        type="button",
                        hx_get="/invoices/wizard/modal/clear",
                        hx_target="#wizard-modal-area",
                        hx_swap="innerHTML",
                        cls=(
                            "p-1.5 rounded-lg text-slate-400 "
                            "hover:bg-slate-100 hover:text-slate-700 shrink-0"
                        ),
                    ),
                    cls=(
                        "flex items-start justify-between gap-3 px-6 py-4 "
                        "border-b border-slate-200"
                    ),
                ),
                Div(*body, cls="px-6 py-5 max-h-[70vh] overflow-auto"),
                Div(
                    Button(
                        Span("Cancel"),
                        type="button",
                        hx_get="/invoices/wizard/modal/clear",
                        hx_target="#wizard-modal-area",
                        hx_swap="innerHTML",
                        cls=(
                            "px-4 py-2 bg-white border border-slate-300 "
                            "text-slate-700 text-sm font-medium rounded-lg "
                            "hover:bg-slate-50"
                        ),
                    ),
                    Button(
                        icon("check-circle", cls="h-4 w-4"),
                        Span(submit_label),
                        type="submit",
                        cls=(
                            "inline-flex items-center gap-2 px-4 py-2 "
                            "bg-indigo-600 text-white text-sm font-medium "
                            "rounded-lg hover:bg-indigo-700"
                        ),
                    ),
                    cls=(
                        "flex justify-end gap-2 px-6 py-4 border-t "
                        "border-slate-200 bg-slate-50 rounded-b-2xl"
                    ),
                ),
                method="post",
                action=action,
                hx_post=action,
                hx_target="#wizard-modal-area",
                hx_swap="innerHTML",
                cls="flex flex-col",
            ),
            cls=(
                "bg-white border border-slate-200 rounded-2xl w-full "
                "max-w-3xl shadow-lg overflow-hidden"
            ),
        ),
        cls=(
            "fixed inset-0 z-50 flex items-center justify-center "
            "bg-slate-900/40 backdrop-blur-xs p-4"
        ),
    )


def _step3(
    *,
    wizard: dict,
    error: str = "",
    success: str = "",
) -> Div:
    lines = (wizard.get("step3", {}) or {}).get("lines", []) or []

    header = Div(
        Div(
            H3(
                "Invoice lines",
                cls="text-base font-semibold text-slate-900",
            ),
            P(
                f"{len(lines)} line(s) on this invoice",
                cls="text-xs text-slate-500 mt-0.5",
            ),
        ),
        _add_actions(),
        cls="flex items-start justify-between gap-3 mb-4 flex-wrap",
    )

    nav = Form(
        _wizard_actions(next_label="Next: review"),
        method="post",
        action="/invoices/wizard/step/3",
    )

    return Div(
        _banner(error, success),
        guidance_panel(
            "Two ways to add a line. Add saved item searches your catalog "
            "and keeps the item identity and classification locked. Add "
            "one-off item lets you type the details and attach a "
            "classification once. On every row you set quantity, unit price, "
            "discount and additional charge, and the totals update straight "
            "away.",
            title="How this screen works",
            cls="mb-5",
        ),
        header,
        _rows_container(wizard),
        _totals_card(wizard),
        nav,
        Div(id="wizard-modal-area"),
        cls="flex flex-col",
    )


def _summary_card(wizard: dict) -> Div:
    computed = wizard.get("computed", {})
    currency = wizard.get("document_currency_code", "NGN")
    lines = wizard.get("step3", {}).get("lines", [])
    return Div(
        H3(
            "Invoice summary",
            cls="text-base font-semibold text-slate-900 mb-4",
        ),
        Div(
            Div(
                P(
                    "IRN",
                    cls="text-xs uppercase text-slate-500 font-semibold tracking-wider",
                ),
                P(
                    wizard.get("irn", "") or "-",
                    cls="text-sm font-mono text-slate-900 mt-1 break-all",
                ),
            ),
            Div(
                P(
                    "Issue date",
                    cls="text-xs uppercase text-slate-500 font-semibold tracking-wider",
                ),
                P(
                    wizard.get("issue_date", "") or "-",
                    cls="text-sm text-slate-900 mt-1",
                ),
            ),
            Div(
                P(
                    "Customer",
                    cls="text-xs uppercase text-slate-500 font-semibold tracking-wider",
                ),
                P(
                    wizard.get("customer_party_name", "") or "-",
                    cls="text-sm text-slate-900 mt-1",
                ),
            ),
            Div(
                P(
                    "Lines",
                    cls="text-xs uppercase text-slate-500 font-semibold tracking-wider",
                ),
                P(
                    len(lines),
                    cls="text-sm text-slate-900 mt-1",
                ),
            ),
            cls="grid grid-cols-2 gap-4 mb-4",
        ),
        Div(cls="border-t border-slate-200 my-4"),
        Div(
            P("Subtotal", cls="text-sm text-slate-600"),
            P(
                f"{currency} {float(computed.get('tax_exclusive_amount', 0)):.2f}",
                cls="text-sm text-slate-900",
            ),
            cls="flex items-center justify-between py-1",
        ),
        Div(
            P("VAT", cls="text-sm text-slate-600"),
            P(
                f"{currency} {float(computed.get('tax_amount', 0)):.2f}",
                cls="text-sm text-slate-900",
            ),
            cls="flex items-center justify-between py-1",
        ),
        Div(
            P(
                "Total payable",
                cls="text-sm font-semibold text-slate-900",
            ),
            P(
                f"{currency} {float(computed.get('payable_amount', 0)):.2f}",
                cls="text-base font-bold text-indigo-700",
            ),
            cls="flex items-center justify-between py-2 border-t border-slate-200 mt-1",
        ),
    )


def _lifecycle_step(
    num: int, label: str, done: bool, busy: bool = False
) -> Div:
    if done:
        circle = Div(
            icon("check-circle", cls="h-4 w-4 text-white"),
            cls="h-7 w-7 rounded-full bg-emerald-600 flex items-center justify-center shrink-0",
        )
    else:
        circle = Div(
            Span(num, cls="text-xs font-bold text-white"),
            cls="h-7 w-7 rounded-full bg-slate-400 flex items-center justify-center shrink-0",
        )
    return Div(
        circle,
        P(label, cls="text-sm font-medium text-slate-900"),
        cls="flex items-center gap-3 py-2",
    )


#: Lifecycle stage tones as (label, background, border, text) tokens.
#:
#: These describe the *review lifecycle*, never an item. They are kept as
#: separate class tokens so this module never assembles a badge class string
#: that reads like a product / service pill: every item kind badge on the
#: wizard surfaces is built by ui.components.item_kind_badge instead.
_STAGE_STATUS_TONES: dict[str, tuple[str, str, str, str]] = {
    "done": (
        "Complete",
        "bg-emerald-100",
        "border-emerald-200",
        "text-emerald-700",
    ),
    "active": (
        "Action required",
        "bg-indigo-100",
        "border-indigo-200",
        "text-indigo-700",
    ),
    "locked": (
        "Locked",
        "bg-slate-100",
        "border-slate-200",
        "text-slate-500",
    ),
    "pending": (
        "Pending",
        "bg-amber-100",
        "border-amber-200",
        "text-amber-700",
    ),
}


def _stage_status_badge(state: str) -> Span:
    label, bg, border, text = _STAGE_STATUS_TONES.get(
        state, _STAGE_STATUS_TONES["locked"]
    )
    return Span(
        label,
        cls=(
            "inline-flex items-center px-2 py-0.5 rounded-full text-[11px] "
            f"font-semibold border {bg} {border} {text}"
        ),
    )


def _stage_card(
    *,
    num: int,
    title: str,
    subtitle: str,
    state: str,
    body,
) -> Div:
    if state == "done":
        circle_cls = (
            "h-8 w-8 rounded-full bg-emerald-600 text-white flex items-center "
            "justify-center text-sm font-semibold shrink-0"
        )
        circle_inner = icon("check-circle", cls="h-4 w-4")
        outer_cls = "bg-white border border-emerald-200 rounded-xl p-5"
    elif state == "active":
        circle_cls = (
            "h-8 w-8 rounded-full bg-indigo-600 text-white flex items-center "
            "justify-center text-sm font-semibold shrink-0"
        )
        circle_inner = Span(num)
        outer_cls = "bg-white border border-indigo-200 rounded-xl p-5 shadow-sm"
    elif state == "pending":
        circle_cls = (
            "h-8 w-8 rounded-full bg-amber-500 text-white flex items-center "
            "justify-center text-sm font-semibold shrink-0"
        )
        circle_inner = Span(num)
        outer_cls = "bg-white border border-amber-200 rounded-xl p-5"
    else:
        circle_cls = (
            "h-8 w-8 rounded-full bg-slate-200 text-slate-500 flex items-center "
            "justify-center text-sm font-semibold shrink-0"
        )
        circle_inner = Span(num)
        outer_cls = (
            "bg-slate-50/50 border border-slate-200 rounded-xl p-5 opacity-75"
        )

    return Div(
        Div(
            Div(circle_inner, cls=circle_cls),
            Div(
                Div(
                    H3(title, cls="text-sm font-semibold text-slate-900"),
                    _stage_status_badge(state),
                    cls="flex items-center gap-2 flex-wrap",
                ),
                P(subtitle, cls="text-xs text-slate-500 mt-0.5"),
                cls="flex-1 min-w-0",
            ),
            cls="flex items-start gap-3 mb-4",
        ),
        body,
        cls=outer_cls,
    )


def _signing_secret_setup_card() -> Form:
    """Inline first-timer onboarding: set the signing secret without leaving
    the wizard, then continue straight to signing."""
    input_cls = (
        "w-full pl-9 pr-3 py-2 bg-white text-slate-900 border "
        "border-slate-300 rounded-lg text-sm focus:outline-none "
        "focus:ring-2 focus:ring-indigo-500"
    )

    def secret_input(name: str, placeholder: str) -> Div:
        return Div(
            icon(
                "settings",
                cls=(
                    "h-4 w-4 text-slate-400 absolute left-3 top-1/2 "
                    "-translate-y-1/2 pointer-events-none"
                ),
            ),
            Input(
                id=name,
                name=name,
                type="password",
                required=True,
                autocomplete="new-password",
                placeholder=placeholder,
                cls=input_cls,
            ),
            cls="relative",
        )

    return Form(
        guidance_panel(
            "You don't have a signing secret yet. It is the passphrase that "
            "authorises your invoices with FIRS. Set it once here and "
            "reuse it for every invoice. You can change it later in "
            "Settings, Signing Secret.",
            title="First invoice? Set your signing secret",
            cls="mb-4",
        ),
        Div(
            Label(
                "New signing secret",
                fr="user_secret",
                cls="block text-sm font-medium text-slate-700 mb-1.5",
            ),
            secret_input("user_secret", "Choose a signing secret"),
            guidance_text("Use at least 8 characters you can remember."),
            cls="mb-4",
        ),
        Div(
            Label(
                "Confirm signing secret",
                fr="confirm_secret",
                cls="block text-sm font-medium text-slate-700 mb-1.5",
            ),
            secret_input("confirm_secret", "Re-enter to confirm"),
            cls="mb-4",
        ),
        Div(
            Button(
                icon("check-circle", cls="h-4 w-4"),
                Span("Save secret & continue"),
                type="submit",
                cls=(
                    "inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 "
                    "text-white text-sm font-medium rounded-lg "
                    "hover:bg-indigo-700 shadow-sm"
                ),
            ),
            A(
                icon("settings", cls="h-3 w-3"),
                Span("Manage in Settings"),
                href="/settings/secret",
                target="_blank",
                cls=(
                    "inline-flex items-center gap-1.5 text-xs font-medium "
                    "text-indigo-600 hover:underline"
                ),
            ),
            cls="flex items-center gap-4",
        ),
        method="post",
        action="/invoices/wizard/set-secret",
    )


def _render_step4(
    *,
    wizard: dict,
    error: str = "",
    success: str = "",
    has_secret: bool = True,
) -> Div:
    validated = bool(wizard.get("_validated"))
    signed = bool(wizard.get("_signed"))
    transmitted = bool(wizard.get("_transmitted"))
    log_created = bool(wizard.get("_log_created"))

    summary = card(_summary_card(wizard))

    if validated:
        validate_state = "done"
    else:
        validate_state = "active"

    if signed:
        sign_state = "done"
    elif validated and not has_secret:
        sign_state = "pending"
    elif validated:
        sign_state = "active"
    else:
        sign_state = "locked"

    if transmitted:
        transmit_state = "done"
    elif signed:
        transmit_state = "active"
    else:
        transmit_state = "locked"

    if signed:
        finish_state = "active"
    else:
        finish_state = "locked"

    if validate_state == "done":
        validate_body = Div(
            Div(
                icon("check-circle", cls="h-4 w-4 text-emerald-600"),
                Span(
                    "Invoice schema validated against FIRS rules.",
                    cls="text-sm text-emerald-700",
                ),
                cls="flex items-center gap-2 mb-3 px-3 py-2 bg-emerald-50 rounded-lg border border-emerald-200",
            ),
            Form(
                Button(
                    icon("check-circle", cls="h-4 w-4"),
                    Span("Re-validate"),
                    type="submit",
                    cls=(
                        "inline-flex items-center gap-2 px-3 py-1.5 bg-white "
                        "border border-slate-300 text-slate-600 text-xs font-medium "
                        "rounded-lg hover:bg-slate-50"
                    ),
                ),
                method="post",
                action="/invoices/wizard/validate",
                cls="inline",
            ),
        )
    else:
        validate_body = Div(
            P(
                "Run a quick check against the FIRS schema before you can sign. "
                "This catches missing fields, malformed codes, or invalid amounts.",
                cls="text-sm text-slate-600 mb-3",
            ),
            Form(
                Button(
                    icon("check-circle", cls="h-4 w-4"),
                    Span("Validate now"),
                    type="submit",
                    cls=(
                        "inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 "
                        "text-white text-sm font-medium rounded-lg hover:bg-indigo-700 "
                        "shadow-sm"
                    ),
                ),
                method="post",
                action="/invoices/wizard/validate",
                cls="inline",
            ),
        )

    validate_card = _stage_card(
        num=1,
        title="Validate",
        subtitle="Check the invoice against the FIRS schema.",
        state=validate_state,
        body=validate_body,
    )

    if sign_state == "done":
        sign_body = Div(
            icon("check-circle", cls="h-4 w-4 text-emerald-600"),
            Span(
                "Invoice signed successfully.",
                cls="text-sm text-emerald-700",
            ),
            cls="flex items-center gap-2 px-3 py-2 bg-emerald-50 rounded-lg border border-emerald-200",
        )
    elif sign_state == "pending":
        sign_body = _signing_secret_setup_card()
    elif sign_state == "active":
        sign_body = Form(
            Div(
                P(
                    "Enter your signing secret to authorise this invoice. "
                    "It is sent securely to FIRS and never stored in this browser.",
                    cls="text-sm text-slate-600 mb-3",
                ),
                Label(
                    "Signing secret",
                    fr="user_secret",
                    cls="block text-sm font-medium text-slate-700 mb-1.5",
                ),
                Div(
                    icon(
                        "settings",
                        cls="h-4 w-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2",
                    ),
                    Input(
                        id="user_secret",
                        name="user_secret",
                        type="password",
                        required=True,
                        autocomplete="off",
                        placeholder="Enter your signing secret",
                        cls=(
                            "w-full pl-9 pr-3 py-2 bg-white text-slate-900 border "
                            "border-slate-300 rounded-lg text-sm focus:outline-none "
                            "focus:ring-2 focus:ring-indigo-500"
                        ),
                    ),
                    cls="relative",
                ),
                P(
                    Span("Tip: ", cls="font-semibold text-slate-700"),
                    "you can manage your signing secret in ",
                    A(
                        "Settings → Signing Secret",
                        href="/settings/secret",
                        target="_blank",
                        cls="text-indigo-600 hover:underline font-medium",
                    ),
                    ".",
                    cls="text-xs text-slate-500 mt-2",
                ),
                cls="mb-4",
            ),
            Button(
                icon("check-circle", cls="h-4 w-4"),
                Span("Sign invoice"),
                type="submit",
                cls=(
                    "inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 "
                    "text-white text-sm font-medium rounded-lg hover:bg-indigo-700 "
                    "shadow-sm"
                ),
            ),
            method="post",
            action="/invoices/wizard/sign",
        )
    else:
        sign_body = Div(
            icon("alert-circle", cls="h-4 w-4 text-slate-400"),
            Span(
                "Validate the invoice first to unlock signing.",
                cls="text-sm text-slate-500",
            ),
            cls="flex items-center gap-2 px-3 py-2 bg-slate-100 rounded-lg border border-slate-200",
        )

    sign_card = _stage_card(
        num=2,
        title="Sign",
        subtitle=(
            "Set your signing secret to unlock signing."
            if sign_state == "pending"
            else "Authorise the invoice with your signing secret."
        ),
        state=sign_state,
        body=sign_body,
    )

    if transmit_state == "done":
        transmit_body = Div(
            icon("check-circle", cls="h-4 w-4 text-emerald-600"),
            Span(
                "Invoice transmitted to FIRS.",
                cls="text-sm text-emerald-700",
            ),
            cls="flex items-center gap-2 px-3 py-2 bg-emerald-50 rounded-lg border border-emerald-200",
        )
    elif transmit_state == "active":
        transmit_body = Div(
            P(
                "Send the signed invoice to FIRS. You can also transmit later "
                "from the invoice detail page if you'd rather review first.",
                cls="text-sm text-slate-600 mb-3",
            ),
            Button(
                icon("send", cls="h-4 w-4"),
                Span("Transmit to FIRS"),
                type="button",
                hx_get="/invoices/wizard/transmit-confirm",
                hx_target="#wizard-modal-area",
                hx_swap="innerHTML",
                cls=(
                    "inline-flex items-center gap-2 px-4 py-2 bg-emerald-600 "
                    "text-white text-sm font-medium rounded-lg "
                    "hover:bg-emerald-700 shadow-sm cursor-pointer"
                ),
            ),
        )
    else:
        transmit_body = Div(
            icon("alert-circle", cls="h-4 w-4 text-slate-400"),
            Span(
                "Sign the invoice first to enable transmission.",
                cls="text-sm text-slate-500",
            ),
            cls="flex items-center gap-2 px-3 py-2 bg-slate-100 rounded-lg border border-slate-200",
        )

    transmit_card = _stage_card(
        num=3,
        title="Transmit (optional)",
        subtitle="Send the signed invoice to FIRS now or later.",
        state=transmit_state,
        body=transmit_body,
    )

    if finish_state == "active":
        finish_body = Div(
            P(
                "All set! Open the invoice detail page to view the signed "
                "invoice, download a copy, or update its payment status.",
                cls="text-sm text-slate-600 mb-3",
            ),
            A(
                icon("check-circle", cls="h-4 w-4"),
                Span("Finish & view invoice"),
                href="/invoices/wizard/finish",
                cls=(
                    "inline-flex items-center gap-2 px-4 py-2 bg-slate-900 "
                    "text-white text-sm font-medium rounded-lg hover:bg-slate-800 "
                    "shadow-sm"
                ),
            ),
        )
    else:
        finish_body = Div(
            icon("alert-circle", cls="h-4 w-4 text-slate-400"),
            Span(
                "Sign the invoice to enable the finish action.",
                cls="text-sm text-slate-500",
            ),
            cls="flex items-center gap-2 px-3 py-2 bg-slate-100 rounded-lg border border-slate-200",
        )

    finish_card = _stage_card(
        num=4,
        title="Finish",
        subtitle="Wrap up and review your invoice.",
        state=finish_state,
        body=finish_body,
    )

    lifecycle_recap = card(
        H3(
            "Progress",
            cls="text-base font-semibold text-slate-900 mb-2",
        ),
        _lifecycle_step(1, "Assembled (totals computed)", True),
        _lifecycle_step(2, "Validated against FIRS schema", validated),
        _lifecycle_step(3, "Signed", signed),
        _lifecycle_step(4, "Transmitted to FIRS (optional)", transmitted),
        P(
            "✓ Local invoice log entry created.",
            cls="text-xs text-emerald-700 mt-2",
        )
        if log_created
        else "",
    )

    return Div(
        _banner(error, success),
        Div(
            summary,
            lifecycle_recap,
            cls="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4",
        ),
        Div(
            Div(
                H3(
                    "Guided lifecycle",
                    cls="text-base font-semibold text-slate-900",
                ),
                P(
                    "Complete each stage in order. Locked stages unlock automatically as you progress.",
                    cls="text-xs text-slate-500 mt-0.5",
                ),
                cls="mb-4",
            ),
            validate_card,
            Div(cls="h-3"),
            sign_card,
            Div(cls="h-3"),
            transmit_card,
            Div(cls="h-3"),
            finish_card,
            cls="bg-slate-50/50 border border-slate-200 rounded-2xl p-5",
        ),
        Div(
            A(
                icon("arrow-left", cls="h-4 w-4"),
                Span("Back to line items"),
                href="/invoices/wizard?step=3",
                cls="inline-flex items-center gap-2 px-4 py-2 bg-white border border-slate-300 text-slate-700 text-sm font-medium rounded-lg hover:bg-slate-50",
            ),
            Button(
                icon("x", cls="h-4 w-4"),
                Span("Discard progress"),
                type="button",
                hx_get="/invoices/wizard/discard-confirm",
                hx_target="#wizard-modal-area",
                hx_swap="innerHTML",
                cls="inline-flex items-center gap-2 px-4 py-2 bg-white border border-slate-300 text-slate-700 text-sm font-medium rounded-lg hover:bg-slate-50 cursor-pointer",
            ),
            cls="flex items-center justify-between gap-2 mt-6",
        ),
        Div(id="wizard-modal-area"),
    )


def _validate_step1(wizard: dict) -> str:
    for f in (
        "irn",
        "issue_date",
        "invoice_type_code",
        "document_currency_code",
        "payment_means_code",
    ):
        if not wizard.get(f):
            return f"{f.replace('_', ' ').title()} is required."
    if wizard.get("invoice_type_code") in REFERENCE_REQUIRED_INVOICE_TYPES:
        if not wizard.get("billing_reference_irn") or not wizard.get(
            "billing_reference_issue_date"
        ):
            return "Billing reference (original IRN + date) is required for this invoice type."
    return ""


def _validate_step2(wizard: dict) -> str:
    required_supplier = [
        ("supplier_party_name", "Company name"),
        ("supplier_tin", "TIN"),
        ("supplier_email", "Email"),
        ("supplier_telephone", "Telephone"),
        ("supplier_street_name", "Street"),
        ("supplier_city_name", "City"),
        ("supplier_postal_zone", "Postal zone"),
        ("supplier_country", "Country"),
        ("supplier_state", "State"),
    ]
    missing_supplier = [
        label for key, label in required_supplier if not wizard.get(key)
    ]
    if missing_supplier:
        return f"Your supplier profile is incomplete. Missing fields: {', '.join(missing_supplier)}. Please complete them in Settings → Profile."

    required_customer = [
        ("customer_party_name", "Company name"),
        ("customer_tin", "TIN"),
        ("customer_email", "Email"),
        ("customer_telephone", "Telephone"),
        ("customer_street_name", "Street"),
        ("customer_city_name", "City"),
        ("customer_postal_zone", "Postal zone"),
        ("customer_country", "Country"),
        ("customer_state", "State"),
    ]
    missing_customer = [
        label for key, label in required_customer if not wizard.get(key)
    ]
    if missing_customer:
        return f"Missing customer details: {', '.join(missing_customer)}."
    return ""


def _validate_line(line: dict) -> str:
    if not line.get("name"):
        return "Item name is required."
    has_hsn = bool(line.get("hsn_code"))
    has_isic = bool(line.get("isic_code"))
    if not (has_hsn or has_isic):
        return "Either an HS code (product) or ISIC code (service) is required."
    if has_hsn and has_isic:
        return "Each line must be either a product or a service, not both."
    import re

    if has_hsn and not re.match(r"^\d{4}\.\d{2}$", line["hsn_code"]):
        return "HS code must use PASCA format XXXX.XX (e.g. 1006.10)."
    if has_isic and not re.match(r"^\d{4}$", line["isic_code"]):
        return "Service code must be exactly 4 digits (e.g. 0112)."
    if has_hsn and not line.get("product_category"):
        return "Product category is required for product lines."
    if has_isic and not line.get("service_category"):
        return "Service category is required for service lines."
    if _safe_float(line.get("invoiced_quantity")) <= 0:
        return "Quantity must be greater than zero."
    if _safe_float(line.get("price_amount")) <= 0:
        return "Unit price must be greater than zero."
    return ""


def _wizard_layout(
    title: str,
    subtitle: str,
    step: int,
    body,
    *,
    username: str | None = None,
    business_id: str | None = None,
    max_reached: int | None = None,
) -> object:
    max_reached = max(step, max_reached or step, 1)
    return app_shell(
        title,
        _page_header(title, subtitle),
        _stepper(step, max_reached),
        body,
        active_nav="invoices",
        username=username,
        business_id=business_id,
    )


def register_routes(rt) -> None:
    @rt("/invoices/wizard/discard-confirm", methods=["GET"])
    def discard_confirm(req: Request):
        return Div(
            Div(
                Div(
                    Div(
                        icon("alert-triangle", cls="h-6 w-6 text-rose-600"),
                        cls="h-12 w-12 rounded-full bg-rose-100 flex items-center justify-center mb-4 mx-auto",
                    ),
                    H3(
                        "Discard invoice progress?",
                        cls="text-lg font-bold text-slate-950 text-center",
                    ),
                    P(
                        "Are you sure you want to discard your draft progress? This will permanently delete your in-progress e-invoice draft, and this action is completely irreversible.",
                        cls="text-sm text-slate-600 text-center mt-2",
                    ),
                    cls="p-6",
                ),
                Div(
                    Button(
                        Span("Cancel"),
                        hx_get="/invoices/wizard/modal/clear",
                        hx_target="#wizard-modal-area",
                        hx_swap="innerHTML",
                        type="button",
                        cls="px-4 py-2 bg-white border border-slate-300 text-slate-700 text-sm font-medium rounded-lg hover:bg-slate-50 cursor-pointer",
                    ),
                    A(
                        Span("Confirm discard"),
                        href="/invoices/wizard/discard",
                        cls="px-4 py-2 bg-rose-600 text-white text-sm font-medium rounded-lg hover:bg-rose-700 cursor-pointer",
                    ),
                    cls="flex items-center justify-end gap-2 px-6 py-4 border-t border-slate-200 bg-slate-50 rounded-b-2xl",
                ),
                cls="bg-white border border-slate-200 rounded-2xl max-w-md w-full shadow-lg relative z-50 animate-fade-in-up",
            ),
            cls="fixed inset-0 z-40 flex items-center justify-center bg-slate-900/40 backdrop-blur-xs p-4",
        )

    @rt("/invoices/wizard/billing-reference-partial", methods=["GET"])
    def billing_reference_partial(req: Request, invoice_type_code: str = ""):
        wizard = _load_wizard(get_session_id(req))
        return _render_step1_billing_reference(invoice_type_code, wizard)

    @rt("/invoices/new", methods=["GET"])
    async def new_invoice(req: Request):
        redirect = require_session(req)
        if redirect:
            return redirect
        return RedirectResponse("/invoices/wizard", status_code=303)

    @rt("/invoices/wizard", methods=["GET"])
    async def wizard_root(
        req: Request, step: int = 0, error: str = "", success: str = ""
    ):
        redirect = require_session(req)
        if redirect:
            return redirect
        jwt = current_jwt(req)
        sid = get_session_id(req)
        wizard = _load_wizard(sid)
        current_step = step or wizard.get("_step", 1)
        try:
            current_step = int(current_step)
        except (TypeError, ValueError):
            current_step = 1
        if current_step < 1 or current_step > 4:
            current_step = 1

        # Keep the stepper honest when the user walks backwards (step 4 to
        # step 3) and forwards again: the current step is authoritative, the
        # furthest reached step is remembered separately.
        try:
            max_step_reached = int(
                wizard.get("_max_step") or wizard.get("_step") or 1
            )
        except (TypeError, ValueError):
            max_step_reached = 1
        max_step_reached = max(1, min(4, max_step_reached), current_step)
        wizard["_step"] = current_step
        wizard["_max_step"] = max_step_reached

        try:
            me = await api_client.get_me(jwt, session_id=sid)
        except Exception:
            logger.exception("get_me failed")
            me = {}

        for f in (
            "tin",
            "party_name",
            "email",
            "telephone",
            "street_name",
            "city_name",
            "postal_zone",
            "country",
            "state",
            "lga",
        ):
            wizard[f"supplier_{f}"] = me.get(f) or ""
        _save_wizard(sid, wizard)

        if current_step == 1:
            types, means, currencies = await _load_step1_lookups(jwt, sid)
            if not wizard.get("irn"):
                try:
                    new_irn = await _compute_next_irn(
                        jwt, sid, me.get("service_id", "") or ""
                    )
                    if new_irn:
                        wizard["irn"] = new_irn
                        _save_wizard(sid, wizard)
                except Exception:
                    logger.exception("wizard_root: IRN auto-gen failed")
            body = _render_step1(
                wizard=wizard,
                types=types,
                means=means,
                currencies=currencies,
                service_id=me.get("service_id", ""),
                error=error,
                success=success,
            )
            return _wizard_layout(
                "New invoice",
                "Identify the invoice with its IRN, dates, and FIRS classification.",
                1,
                body,
                username=current_username(req),
                business_id=current_business_id(req),
                max_reached=max_step_reached,
            )

        if current_step == 2:
            try:
                customers_res = await api_client.list_customers(
                    jwt, session_id=sid, limit=200
                )
                customers = customers_res.get("items", [])
            except Exception:
                logger.exception("list_customers failed")
                customers = []
            states, countries = await _load_geo_lookups(jwt, sid)
            body = _render_step2(
                wizard=wizard,
                profile=me,
                customers=customers,
                states=states,
                countries=countries,
                error=error,
                success=success,
            )
            return _wizard_layout(
                "Supplier & customer",
                "Your business is the supplier. Pick a saved customer or enter new details.",
                2,
                body,
                username=current_username(req),
                business_id=current_business_id(req),
                max_reached=max_step_reached,
            )

        if current_step == 3:
            body = _step3(
                wizard=wizard,
                error=error,
                success=success,
            )
            return _wizard_layout(
                "Invoice lines",
                "Add saved items from your catalog, or one-off items, then "
                "set quantity, price and any adjustments per line.",
                3,
                body,
                username=current_username(req),
                business_id=current_business_id(req),
                max_reached=max_step_reached,
            )

        has_secret = False
        try:
            secret_status = await api_client.get_user_secret_status(
                jwt, session_id=sid
            )
            has_secret = bool((secret_status or {}).get("has_secret"))
        except Exception:
            logger.exception("wizard_root: get_user_secret_status failed")

        body = _render_step4(
            wizard=wizard,
            error=error,
            success=success,
            has_secret=has_secret,
        )
        return _wizard_layout(
            "Review & sign",
            "Validate against FIRS schema, sign with your secret, and optionally transmit.",
            4,
            body,
            username=current_username(req),
            business_id=current_business_id(req),
            max_reached=max_step_reached,
        )

    @rt("/invoices/wizard/step/1", methods=["POST"])
    async def submit_step1(req: Request):
        redirect = require_session(req)
        if redirect:
            return redirect
        sid = get_session_id(req)
        jwt = current_jwt(req)
        form = await req.form()
        wizard = _load_wizard(sid)
        for f in (
            "issue_date",
            "due_date",
            "invoice_type_code",
            "document_currency_code",
            "payment_means_code",
            "billing_reference_irn",
            "billing_reference_issue_date",
        ):
            v = (form.get(f) or "").strip()
            wizard[f] = v
        if not wizard.get("irn"):
            try:
                me = await api_client.get_me(jwt, session_id=sid)
                wizard["irn"] = await _compute_next_irn(
                    jwt, sid, (me or {}).get("service_id", "") or ""
                )
            except Exception:
                logger.exception("submit_step1: IRN regeneration failed")
        wizard["tax_currency_code"] = "NGN"
        err = _validate_step1(wizard)
        if err:
            wizard["_step"] = 1
            _save_wizard(sid, wizard)
            return RedirectResponse(
                f"/invoices/wizard?step=1&error={err}", status_code=303
            )
        wizard["_step"] = 2
        _save_wizard(sid, wizard)
        return RedirectResponse("/invoices/wizard?step=2", status_code=303)

    @rt("/invoices/wizard/step/2", methods=["POST"])
    async def submit_step2(req: Request):
        redirect = require_session(req)
        if redirect:
            return redirect
        sid = get_session_id(req)
        form = await req.form()
        action = (form.get("_action") or "next").strip()
        wizard = _load_wizard(sid)

        if action == "back":
            wizard["_step"] = 1
            _save_wizard(sid, wizard)
            return RedirectResponse("/invoices/wizard?step=1", status_code=303)

        wizard["customer_id"] = (form.get("customer_id") or "").strip()
        for f in (
            "party_name",
            "tin",
            "email",
            "telephone",
            "street_name",
            "city_name",
            "postal_zone",
            "country",
            "state",
            "lga",
        ):
            wizard[f"customer_{f}"] = (form.get(f"customer_{f}") or "").strip()

        err = _validate_step2(wizard)
        if err:
            wizard["_step"] = 2
            _save_wizard(sid, wizard)
            return RedirectResponse(
                f"/invoices/wizard?step=2&error={err}", status_code=303
            )
        wizard["_step"] = 3
        _save_wizard(sid, wizard)
        return RedirectResponse("/invoices/wizard?step=3", status_code=303)

    @rt("/invoices/wizard/customer/select", methods=["POST"])
    async def select_wizard_customer(req: Request):
        redirect = require_session(req)
        if redirect:
            return redirect
        sid = get_session_id(req)
        jwt = current_jwt(req)
        form = await req.form()
        cid = (form.get("customer_id") or "").strip()
        wizard = _load_wizard(sid)
        customer_fields = (
            "tin",
            "party_name",
            "email",
            "telephone",
            "street_name",
            "city_name",
            "postal_zone",
            "country",
            "state",
            "lga",
        )
        if not cid:
            wizard["customer_id"] = ""
            for f in customer_fields:
                wizard[f"customer_{f}"] = ""
        else:
            try:
                customer = await api_client.get_customer(
                    jwt, int(cid), session_id=sid
                )
                wizard["customer_id"] = cid
                for f in customer_fields:
                    wizard[f"customer_{f}"] = customer.get(f, "") or ""
            except (api_client.APIError, ValueError, Exception):
                logger.exception("select_wizard_customer: get_customer failed")
                wizard["customer_id"] = ""
                for f in customer_fields:
                    wizard[f"customer_{f}"] = ""
        wizard["_step"] = 2
        _save_wizard(sid, wizard)
        if req.headers.get("HX-Request") == "true":
            resp = HTMLResponse("")
            resp.headers["HX-Redirect"] = "/invoices/wizard?step=2"
            return resp
        return RedirectResponse("/invoices/wizard?step=2", status_code=303)

    @rt("/invoices/wizard/customer/clear", methods=["GET"])
    async def clear_wizard_customer(req: Request):
        redirect = require_session(req)
        if redirect:
            return redirect
        sid = get_session_id(req)
        wizard = _load_wizard(sid)
        wizard["customer_id"] = ""
        for f in (
            "tin",
            "party_name",
            "email",
            "telephone",
            "street_name",
            "city_name",
            "postal_zone",
            "country",
            "state",
            "lga",
        ):
            wizard[f"customer_{f}"] = ""
        wizard["_step"] = 2
        _save_wizard(sid, wizard)
        return RedirectResponse("/invoices/wizard?step=2", status_code=303)

    @rt("/invoices/wizard/modal/clear", methods=["GET"])
    def clear_wizard_modal(req: Request):
        return HTMLResponse("")

    async def _wizard_geo_lookups(jwt: str, sid: str) -> tuple[list, list]:
        try:
            countries = await api_client.get_countries(jwt, session_id=sid)
            if not isinstance(countries, list):
                countries = []
        except Exception:
            logger.exception("wizard_geo_lookups: countries failed")
            countries = []
        try:
            states = await api_client.get_state_codes(jwt, session_id=sid)
            if not isinstance(states, list):
                states = []
        except Exception:
            logger.exception("wizard_geo_lookups: states failed")
            states = []
        return countries, states

    @rt("/invoices/wizard/customer/{cid}/edit", methods=["GET"])
    async def wizard_customer_edit_form(req: Request, cid: int):
        redirect = require_session(req)
        if redirect:
            return redirect
        jwt = current_jwt(req)
        sid = get_session_id(req)
        try:
            customer = await api_client.get_customer(jwt, cid, session_id=sid)
        except api_client.APIError as e:
            logger.exception("wizard_customer_edit_form: get_customer failed")
            detail = (
                e.detail
                if isinstance(e.detail, str)
                else "Could not load this customer."
            )
            return HTMLResponse(
                f'<div class="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 backdrop-blur-xs p-4">'
                f'<div class="bg-white border border-slate-200 rounded-2xl p-6 max-w-md w-full">'
                f'<p class="text-sm text-rose-700">{detail}</p>'
                f'<button hx-get="/invoices/wizard/modal/clear" hx-target="#wizard-modal-area" hx-swap="innerHTML" '
                f'class="mt-4 px-4 py-2 bg-white border border-slate-300 text-slate-700 text-sm font-medium rounded-lg hover:bg-slate-50">Close</button>'
                f"</div></div>"
            )
        except Exception:
            logger.exception("wizard_customer_edit_form transport error")
            return HTMLResponse("")
        countries, states = await _wizard_geo_lookups(jwt, sid)
        return _wizard_customer_edit_overlay(customer, countries, states)

    @rt("/invoices/wizard/customer/{cid}/edit", methods=["POST"])
    async def wizard_customer_edit_save(req: Request, cid: int):
        redirect = require_session(req)
        if redirect:
            return redirect
        jwt = current_jwt(req)
        sid = get_session_id(req)
        form = await req.form()
        payload = {
            "party_name": (form.get("party_name") or "").strip(),
            "tin": (form.get("tin") or "").strip(),
            "email": (form.get("email") or "").strip(),
            "telephone": (form.get("telephone") or "").strip(),
            "street_name": (form.get("street_name") or "").strip(),
            "city_name": (form.get("city_name") or "").strip(),
            "postal_zone": (form.get("postal_zone") or "").strip(),
            "country": (form.get("country") or "").strip(),
            "state": (form.get("state") or "").strip(),
        }
        lga_val = (form.get("lga") or "").strip()
        payload["lga"] = lga_val or None

        required_pairs = [
            ("party_name", "Company name"),
            ("tin", "TIN"),
            ("email", "Email"),
            ("telephone", "Telephone"),
            ("street_name", "Street"),
            ("city_name", "City"),
            ("postal_zone", "Postal zone"),
            ("country", "Country"),
            ("state", "State"),
        ]
        missing = [
            label for key, label in required_pairs if not payload.get(key)
        ]
        if missing:
            countries, states = await _wizard_geo_lookups(jwt, sid)
            return _wizard_customer_edit_overlay(
                {**payload, "id": cid, "lga": lga_val},
                countries,
                states,
                error=f"Please fill in: {', '.join(missing)}.",
            )

        try:
            updated = await api_client.update_customer(
                jwt, cid, payload, session_id=sid
            )
        except api_client.APIError as e:
            logger.exception("wizard_customer_edit_save: update failed")
            countries, states = await _wizard_geo_lookups(jwt, sid)
            detail = (
                e.detail
                if isinstance(e.detail, str)
                else "Could not save customer. Please try again."
            )
            return _wizard_customer_edit_overlay(
                {**payload, "id": cid, "lga": lga_val},
                countries,
                states,
                error=str(detail),
            )
        except Exception:
            logger.exception("wizard_customer_edit_save transport error")
            countries, states = await _wizard_geo_lookups(jwt, sid)
            return _wizard_customer_edit_overlay(
                {**payload, "id": cid, "lga": lga_val},
                countries,
                states,
                error="Backend service unavailable. Please try again.",
            )

        wizard = _load_wizard(sid)
        if str(wizard.get("customer_id", "") or "") == str(cid):
            for f in (
                "tin",
                "party_name",
                "email",
                "telephone",
                "street_name",
                "city_name",
                "postal_zone",
                "country",
                "state",
                "lga",
            ):
                wizard[f"customer_{f}"] = updated.get(f, "") or ""
            wizard["_step"] = 2
            _save_wizard(sid, wizard)

        if req.headers.get("HX-Request") == "true":
            resp = HTMLResponse("")
            resp.headers["HX-Redirect"] = "/invoices/wizard?step=2"
            return resp
        return RedirectResponse("/invoices/wizard?step=2", status_code=303)

    @rt("/invoices/wizard/line/picker", methods=["GET"])
    async def line_saved_picker(req: Request, idx: int = -1):
        """Search-first saved-item picker. Never shown next to manual fields."""
        redirect = require_session(req)
        if redirect:
            return redirect
        jwt = current_jwt(req)
        sid = get_session_id(req)
        items = await _load_catalog_items(jwt, sid, limit=20)
        return _saved_item_picker_modal("", items, idx=idx)

    @rt("/invoices/wizard/line/one-off", methods=["GET"])
    def line_one_off_modal(req: Request):
        """Manual item details plus the HS / ISIC lookup, on their own."""
        redirect = require_session(req)
        if redirect:
            return redirect
        wizard = _load_wizard(get_session_id(req))
        unit = _default_price_unit(wizard)
        return _line_modal(
            edit_idx=-1,
            line=_empty_row_line(unit),
            default_unit=unit,
        )

    @rt("/invoices/wizard/line/catalog", methods=["GET"])
    async def line_catalog_search(
        req: Request, catalog_q: str = "", idx: int = -1
    ):
        redirect = require_session(req)
        if redirect:
            return redirect
        q = (catalog_q or "").strip()
        jwt = current_jwt(req)
        sid = get_session_id(req)
        items = await _load_catalog_items(jwt, sid, q)
        return _catalog_results(items, q, idx)

    @rt("/invoices/wizard/line/catalog/apply", methods=["POST"])
    async def line_catalog_apply(req: Request):
        """Add a saved item as a new locked line, or replace one on a row."""
        redirect = require_session(req)
        if redirect:
            return redirect
        sid = get_session_id(req)
        jwt = current_jwt(req)
        form = await req.form()
        item_id = (form.get("item_id") or "").strip()
        try:
            idx = int(form.get("idx") or "-1")
        except ValueError:
            idx = -1
        wizard = _load_wizard(sid)
        default_unit = _default_price_unit(wizard)
        lines = wizard.setdefault("step3", {}).setdefault("lines", [])

        item: dict = {}
        try:
            item = await api_client.get_item(jwt, int(item_id), session_id=sid)
        except (TypeError, ValueError):
            logger.exception("line_catalog_apply: bad item id")
        except api_client.APIError:
            logger.exception("line_catalog_apply: get_item failed")
        except Exception:
            logger.exception("line_catalog_apply transport error")

        if not item:
            if req.headers.get("HX-Request") != "true":
                return RedirectResponse(
                    "/invoices/wizard?step=3", status_code=303
                )
            return _rows_response(
                wizard,
                banner=alert(
                    "error",
                    "Could not load that saved item. It may have been "
                    "deactivated. Search again, or add it as a one-off item.",
                ),
                close_modal=True,
            )

        name = str(item.get("name", "") or "").strip() or "Saved item"
        if 0 <= idx < len(lines):
            previous = dict(lines[idx])
            qty = _fmt_num(previous.get("invoiced_quantity"), "1")
            merged = _line_from_catalog_item(item, qty)
            for key in (
                "discount_rate",
                "discount_amount",
                "fee_rate",
                "fee_amount",
            ):
                merged[key] = previous.get(key, 0.0)
            lines[idx] = _normalize_line(merged, default_unit)
            msg = f"Line {idx + 1} now uses {name}."
        else:
            lines.append(
                _normalize_line(
                    _line_from_catalog_item(item, "1"), default_unit
                )
            )
            msg = f"Added {name}. Set the quantity on the row."
        wizard["_step"] = 3
        _save_wizard(sid, wizard)

        if req.headers.get("HX-Request") != "true":
            return RedirectResponse("/invoices/wizard?step=3", status_code=303)
        return _rows_response(
            wizard, banner=alert("success", msg), close_modal=True
        )

    @rt("/invoices/wizard/line/{idx}/update", methods=["POST"])
    async def update_line_row(req: Request, idx: int):
        """Inline row update: quantity, unit price, discount, additional charge."""
        redirect = require_session(req)
        if redirect:
            return redirect
        sid = get_session_id(req)
        form = await req.form()
        wizard = _load_wizard(sid)
        lines = wizard.setdefault("step3", {}).setdefault("lines", [])
        if idx < 0 or idx >= len(lines):
            return _rows_response(
                wizard,
                banner=alert("error", "That line no longer exists."),
            )

        default_unit = _default_price_unit(wizard)
        line, err = _apply_row_form(dict(lines[idx]), form, default_unit)
        lines[idx] = _normalize_line(line, default_unit)
        wizard["_step"] = 3
        _save_wizard(sid, wizard)

        banner = alert("error", f"Line {idx + 1}: {err}") if err else None
        if req.headers.get("HX-Request") != "true":
            return RedirectResponse("/invoices/wizard?step=3", status_code=303)
        return _rows_response(wizard, banner=banner)

    @rt("/invoices/wizard/line/{idx}/edit", methods=["GET"])
    def edit_line_modal(req: Request, idx: int):
        redirect = require_session(req)
        if redirect:
            return redirect
        sid = get_session_id(req)
        wizard = _load_wizard(sid)
        lines = wizard.get("step3", {}).get("lines", [])
        if idx < 0 or idx >= len(lines):
            return HTMLResponse("")
        return _line_modal(
            edit_idx=idx,
            line=lines[idx],
            default_unit=_default_price_unit(wizard),
        )

    @rt("/invoices/wizard/line/lookup", methods=["GET"])
    async def line_lookup(req: Request, lookup_q: str = ""):
        """One-off line classification lookup.

        Uses the same shared ranker as the Items page lookup, so a product
        query such as "rice" ranks HS results first and a service query such
        as "consulting" ranks ISIC results first.
        """
        redirect = require_session(req)
        if redirect:
            return redirect
        q = (lookup_q or "").strip()
        if len(q) < 2:
            return Div(id="lookup-results")
        jwt = current_jwt(req)
        sid = get_session_id(req)
        hits = await lookup_ranking.search_and_rank_classifications(
            jwt, q, session_id=sid, limit=20
        )
        return _lookup_results_panel(hits, q)

    @rt("/invoices/wizard/line/lookup/apply", methods=["GET"])
    async def line_lookup_apply(
        req: Request,
        kind: str = "product",
        code: str = "",
        label: str = "",
        category: str = "",
        invoiced_quantity: str = "",
        price_amount: str = "",
        base_quantity: str = "",
        price_unit: str = "",
        sellers_item_identification: str = "",
    ):
        redirect = require_session(req)
        if redirect:
            return redirect
        kind = (kind or "product").strip()
        code = (code or "").strip()
        label = (label or "").strip()
        category = (category or "").strip() or label
        qty = (invoiced_quantity or "").strip() or "1"
        price = (price_amount or "").strip() or "0.00"
        base_qty = (base_quantity or "").strip() or "1"
        unit = coerce_unit_code(price_unit)
        sku = (sellers_item_identification or "").strip()

        def _short_name(full: str) -> str:
            if not full:
                return ""
            primary = full.split(";", 1)[0].strip()
            if len(primary) > 50 and "," in primary:
                primary = primary.split(",", 1)[0].strip()
            return (primary[:60] or full[:60]).strip()

        short = _short_name(label)
        full_desc = label or category
        sid = get_session_id(req)
        wizard = _load_wizard(sid)
        default_unit = _default_price_unit(wizard)
        unit = coerce_unit_code(price_unit, default_unit)
        line = {
            "name": short,
            "description": full_desc,
            "sellers_item_identification": sku,
            "hsn_code": code if kind == "product" else "",
            "product_category": category if kind == "product" else "",
            "isic_code": code if kind == "service" else "",
            "service_category": category if kind == "service" else "",
            "invoiced_quantity": qty,
            "price_amount": price,
            "base_quantity": base_qty,
            "price_unit": unit,
        }
        return (
            _line_form_fields(line, default_unit=default_unit),
            Div(
                id="lookup-results",
                hx_swap_oob="outerHTML",
            ),
            Input(
                type="search",
                name="lookup_q",
                id="lookup-q-input",
                placeholder="Search products & services (e.g. 'computer', 'consulting')…",
                value="",
                autocomplete="off",
                hx_get="/invoices/wizard/line/lookup",
                hx_trigger="keyup changed delay:400ms, search",
                hx_target="#lookup-results",
                hx_swap="outerHTML",
                hx_swap_oob="outerHTML",
                cls="w-full pl-9 pr-3 py-2 bg-white text-slate-900 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500",
            ),
        )

    @rt("/invoices/wizard/line/save", methods=["POST"])
    async def save_line(req: Request):
        redirect = require_session(req)
        if redirect:
            return redirect
        sid = get_session_id(req)
        form = await req.form()
        wizard = _load_wizard(sid)
        default_unit = _default_price_unit(wizard)
        try:
            edit_idx = int(form.get("edit_idx") or "-1")
        except ValueError:
            edit_idx = -1

        raw_desc = (form.get("description") or "").strip()
        if not raw_desc:
            raw_desc = (
                (form.get("product_category") or "").strip()
                or (form.get("service_category") or "").strip()
                or (form.get("name") or "").strip()
            )
        disc_type = (form.get("discount_type") or "percent").strip().lower()
        if disc_type not in ("percent", "flat"):
            disc_type = "percent"
        fee_type = (form.get("fee_type") or "percent").strip().lower()
        if fee_type not in ("percent", "flat"):
            fee_type = "percent"

        raw_disc_value = form.get("discount_value")
        raw_fee_value = form.get("fee_value")
        disc_value = (
            _safe_float(raw_disc_value, 0.0)
            if raw_disc_value not in (None, "")
            else 0.0
        )
        fee_value = (
            _safe_float(raw_fee_value, 0.0)
            if raw_fee_value not in (None, "")
            else 0.0
        )

        num_err = ""
        if disc_type == "percent" and (disc_value < 0 or disc_value > 100):
            num_err = "Discount percent must be between 0 and 100."
        elif disc_type == "flat" and disc_value < 0:
            num_err = "Discount amount cannot be negative."
        elif fee_type == "percent" and (fee_value < 0 or fee_value > 100):
            num_err = "Additional charge percent must be between 0 and 100."
        elif fee_type == "flat" and fee_value < 0:
            num_err = "Additional charge cannot be negative."

        if disc_type == "percent":
            discount_rate_out, discount_amount_out = disc_value, 0.0
        else:
            discount_rate_out, discount_amount_out = 0.0, disc_value
        if fee_type == "percent":
            fee_rate_out, fee_amount_out = fee_value, 0.0
        else:
            fee_rate_out, fee_amount_out = 0.0, fee_value

        line = {
            "catalog_item_id": (form.get("catalog_item_id") or "").strip(),
            "name": (form.get("name") or "").strip(),
            "description": raw_desc,
            "sellers_item_identification": (
                form.get("sellers_item_identification") or ""
            ).strip(),
            "hsn_code": (form.get("hsn_code") or "").strip(),
            "product_category": (form.get("product_category") or "").strip(),
            "isic_code": (form.get("isic_code") or "").strip(),
            "service_category": (form.get("service_category") or "").strip(),
            "invoiced_quantity": _safe_float(
                form.get("invoiced_quantity"), 1.0
            ),
            "price_amount": _safe_float(form.get("price_amount"), 0.0),
            "price_unit": coerce_unit_code(
                form.get("price_unit"), default_unit
            ),
            "base_quantity": _safe_float(form.get("base_quantity"), 1.0),
            "discount_rate": discount_rate_out,
            "discount_amount": discount_amount_out,
            "fee_rate": fee_rate_out,
            "fee_amount": fee_amount_out,
        }

        if line["hsn_code"] and not line["product_category"]:
            line["product_category"] = line["name"]
        if line["isic_code"] and not line["service_category"]:
            line["service_category"] = line["name"]

        if not num_err:
            if line["invoiced_quantity"] <= 0:
                num_err = "Quantity must be greater than zero."
            elif line["price_amount"] <= 0:
                num_err = "Unit price must be greater than zero."
            elif line["base_quantity"] <= 0:
                num_err = "Units the price covers must be greater than zero."

        err = num_err or _validate_line(line)
        line = _normalize_line(line, default_unit)
        if err:
            if req.headers.get("HX-Request") == "true":
                return _line_modal(
                    edit_idx=edit_idx,
                    line=line,
                    error=err,
                    default_unit=default_unit,
                )
            return RedirectResponse(
                "/invoices/wizard?step=3&error=" + urllib.parse.quote_plus(err),
                status_code=303,
            )

        lines = wizard.setdefault("step3", {}).setdefault("lines", [])
        if edit_idx >= 0 and edit_idx < len(lines):
            lines[edit_idx] = line
            success = "Line updated"
        else:
            lines.append(line)
            success = "Line added"
        wizard["_step"] = 3
        _save_wizard(sid, wizard)

        if req.headers.get("HX-Request") == "true":
            return (
                Div(),
                *_rows_response(
                    wizard,
                    banner=alert("success", f"{success}."),
                    oob_rows=True,
                ),
            )
        return RedirectResponse(
            f"/invoices/wizard?step=3&success={success.replace(' ', '+')}",
            status_code=303,
        )

    @rt("/invoices/wizard/step/3/remove", methods=["POST"])
    async def remove_line(req: Request):
        redirect = require_session(req)
        if redirect:
            return redirect
        sid = get_session_id(req)
        form = await req.form()
        try:
            idx = int(form.get("idx") or "-1")
        except ValueError:
            idx = -1
        wizard = _load_wizard(sid)
        lines = wizard.get("step3", {}).get("lines", [])
        removed = False
        if 0 <= idx < len(lines):
            lines.pop(idx)
            wizard.setdefault("step3", {})["lines"] = lines
            removed = True
        wizard["_step"] = 3
        _save_wizard(sid, wizard)
        if req.headers.get("HX-Request") == "true":
            banner = (
                alert("success", "Line removed.")
                if removed
                else alert("error", "That line no longer exists.")
            )
            return _rows_response(wizard, banner=banner)
        return RedirectResponse("/invoices/wizard?step=3", status_code=303)

    @rt("/invoices/wizard/step/3", methods=["POST"])
    async def submit_step3(req: Request):
        redirect = require_session(req)
        if redirect:
            return redirect
        sid = get_session_id(req)
        jwt = current_jwt(req)
        form = await req.form()
        action = (form.get("_action") or "next").strip()
        wizard = _load_wizard(sid)

        if action == "back":
            wizard["_step"] = 2
            _save_wizard(sid, wizard)
            return RedirectResponse("/invoices/wizard?step=2", status_code=303)

        lines = wizard.get("step3", {}).get("lines", []) or []
        if not lines:
            return RedirectResponse(
                "/invoices/wizard?step=3&error="
                + urllib.parse.quote_plus("Add at least one invoice line."),
                status_code=303,
            )
        for position, line in enumerate(lines, start=1):
            line_error = _validate_line(line)
            if line_error:
                return RedirectResponse(
                    "/invoices/wizard?step=3&error="
                    + urllib.parse.quote_plus(f"Line {position}: {line_error}"),
                    status_code=303,
                )
        try:
            assembled = await api_client.assemble_invoice(
                jwt, wizard, session_id=sid
            )
            wizard["computed"] = assembled.get("computed", {})
            wizard["_assembled"] = assembled
        except api_client.APIError as e:
            logging.exception("Unexpected error")
            detail = extract_api_error_detail(e)
            return RedirectResponse(
                f"/invoices/wizard?step=3&error={detail}", status_code=303
            )
        except Exception:
            logger.exception("assemble failed")
            return RedirectResponse(
                "/invoices/wizard?step=3&error=Backend+service+unavailable",
                status_code=303,
            )

        wizard["_validated"] = False
        wizard["_signed"] = False
        wizard["_transmitted"] = False
        wizard["_log_created"] = False
        wizard["_step"] = 4
        _save_wizard(sid, wizard)
        return RedirectResponse("/invoices/wizard?step=4", status_code=303)

    @rt("/invoices/wizard/validate", methods=["POST"])
    async def do_validate(req: Request):
        redirect = require_session(req)
        if redirect:
            return redirect
        sid = get_session_id(req)
        jwt = current_jwt(req)
        wizard = _load_wizard(sid)
        try:
            assembled = await api_client.assemble_invoice(
                jwt, wizard, session_id=sid
            )
            invoice_dict = {
                k: v for k, v in assembled.items() if k != "computed"
            }
            await api_client.validate_invoice(jwt, invoice_dict, session_id=sid)
            wizard["_assembled"] = assembled
            wizard["computed"] = assembled.get("computed", {})
            wizard["_validated"] = True
            _save_wizard(sid, wizard)
            return RedirectResponse(
                "/invoices/wizard?step=4&success=Validated+against+FIRS+schema",
                status_code=303,
            )
        except api_client.APIError as e:
            logging.exception("Unexpected error")
            detail = extract_api_error_detail(e)
            return RedirectResponse(
                f"/invoices/wizard?step=4&error={detail}", status_code=303
            )
        except Exception:
            logger.exception("validate failed")
            return RedirectResponse(
                "/invoices/wizard?step=4&error=Backend+service+unavailable",
                status_code=303,
            )

    @rt("/invoices/wizard/set-secret", methods=["POST"])
    async def wizard_set_secret(req: Request):
        """First-timer onboarding: create the signing secret inline so the
        wizard can continue straight to signing."""
        redirect = require_session(req)
        if redirect:
            return redirect
        sid = get_session_id(req)
        jwt = current_jwt(req)
        form = await req.form()
        secret = (form.get("user_secret") or "").strip()
        confirm = (form.get("confirm_secret") or "").strip()

        def _fail(message: str):
            return RedirectResponse(
                "/invoices/wizard?step=4&error="
                + urllib.parse.quote_plus(message),
                status_code=303,
            )

        if not secret:
            return _fail("Signing secret cannot be empty.")
        if len(secret) < 8:
            return _fail("Signing secret must be at least 8 characters.")
        if secret != confirm:
            return _fail("The signing secrets you entered do not match.")

        try:
            await api_client.update_secret(jwt, secret, session_id=sid)
        except api_client.APIError as e:
            logger.exception("wizard_set_secret: update_secret failed")
            return _fail(extract_api_error_detail(e))
        except Exception:
            logger.exception("wizard_set_secret transport error")
            return _fail("Backend service unavailable. Please try again.")

        try:
            auth_service.save_user_secret(sid, secret)
        except Exception:
            logger.exception("wizard_set_secret: session cache best-effort")

        return RedirectResponse(
            "/invoices/wizard?step=4&success="
            + urllib.parse.quote_plus(
                "Signing secret saved. You can now sign this invoice."
            ),
            status_code=303,
        )

    @rt("/invoices/wizard/transmit-confirm", methods=["GET"])
    def wizard_transmit_confirm(req: Request):
        redirect = require_session(req)
        if redirect:
            return redirect
        wizard = _load_wizard(get_session_id(req))
        irn = wizard.get("irn", "") or "—"
        confirm_btn = Form(
            Button(
                icon("send", cls="h-4 w-4"),
                Span("Transmit now"),
                type="submit",
                cls=(
                    "inline-flex items-center gap-2 px-4 py-2 bg-emerald-600 "
                    "text-white text-sm font-medium rounded-lg "
                    "hover:bg-emerald-700"
                ),
            ),
            method="post",
            action="/invoices/wizard/transmit",
            cls="inline",
        )
        return confirm_dialog(
            title="Transmit this invoice to FIRS?",
            message=(
                "The signed invoice will be sent to the FIRS gateway. "
                "Transmission cannot be recalled. Corrections must be "
                "issued as a new invoice with a fresh IRN. You can also "
                "transmit later from the invoice page."
            ),
            confirm_control=confirm_btn,
            cancel_get="/invoices/wizard/modal/clear",
            cancel_target="#wizard-modal-area",
            icon_name="send",
            tone="info",
            details=confirm_detail_rows(
                [
                    ("IRN", irn),
                    ("Customer", wizard.get("customer_party_name", "") or "-"),
                ]
            ),
        )

    @rt("/invoices/wizard/sign", methods=["POST"])
    async def do_sign(req: Request):
        redirect = require_session(req)
        if redirect:
            return redirect
        sid = get_session_id(req)
        jwt = current_jwt(req)
        form = await req.form()
        secret = (form.get("user_secret") or "").strip()
        if not secret:
            return RedirectResponse(
                "/invoices/wizard?step=4&error=Signing+secret+required",
                status_code=303,
            )
        wizard = _load_wizard(sid)
        try:
            assembled = await api_client.assemble_invoice(
                jwt, wizard, session_id=sid
            )
            invoice_dict = {
                k: v for k, v in assembled.items() if k != "computed"
            }
            await api_client.sign_invoice(
                jwt, secret, invoice_dict, session_id=sid
            )
            wizard["_signed"] = True
            wizard["_assembled"] = assembled
            wizard["computed"] = assembled.get("computed", {})
            try:
                await api_client.create_invoice_log(
                    jwt,
                    {
                        "irn": wizard.get("irn"),
                        "issue_date": wizard.get("issue_date"),
                        "customer_name": wizard.get("customer_party_name"),
                        "currency": wizard.get("document_currency_code", "NGN"),
                        "payment_status": "PENDING",
                        "payable_amount": float(
                            wizard.get("computed", {}).get("payable_amount", 0)
                        ),
                        "transmitted": False,
                    },
                    session_id=sid,
                )
                wizard["_log_created"] = True
            except Exception:
                logger.exception("create_invoice_log failed")
            _save_wizard(sid, wizard)
            return RedirectResponse(
                "/invoices/wizard?step=4&success=Invoice+signed",
                status_code=303,
            )
        except api_client.APIError as e:
            logging.exception("Unexpected error")
            detail = extract_api_error_detail(e)
            return RedirectResponse(
                f"/invoices/wizard?step=4&error={detail}", status_code=303
            )
        except Exception:
            logger.exception("sign failed")
            return RedirectResponse(
                "/invoices/wizard?step=4&error=Backend+service+unavailable",
                status_code=303,
            )

    @rt("/invoices/wizard/transmit", methods=["POST"])
    async def do_transmit(req: Request):
        redirect = require_session(req)
        if redirect:
            return redirect
        sid = get_session_id(req)
        jwt = current_jwt(req)
        wizard = _load_wizard(sid)
        irn = wizard.get("irn", "")
        if not wizard.get("_signed") or not irn:
            return RedirectResponse(
                "/invoices/wizard?step=4&error=Sign+the+invoice+first",
                status_code=303,
            )
        customer_tin = wizard.get("customer_tin", "")
        try:
            await api_client.transmit_invoice(jwt, irn, session_id=sid)
            try:
                await api_client.mark_transmitted(jwt, irn, session_id=sid)
            except Exception:
                logger.exception("mark_transmitted failed")
            wizard["_transmitted"] = True
            _save_wizard(sid, wizard)
            return RedirectResponse(
                "/invoices/wizard?step=4&success=Transmitted+to+FIRS",
                status_code=303,
            )
        except api_client.APIError as e:
            logging.exception("Unexpected error")
            detail = extract_api_error_detail(e)
            lower = str(detail).lower()
            if any(w in lower for w in ("already", "transmitted", "duplicate")):
                wizard["_transmitted"] = True
                _save_wizard(sid, wizard)
                return RedirectResponse(
                    "/invoices/wizard?step=4&success=Already+transmitted",
                    status_code=303,
                )
            friendly_error = normalize_transmission_error(detail, customer_tin)
            return RedirectResponse(
                f"/invoices/wizard?step=4&error={urllib.parse.quote_plus(friendly_error)}",
                status_code=303,
            )
        except Exception:
            logger.exception("transmit failed")
            return RedirectResponse(
                "/invoices/wizard?step=4&error=Backend+service+unavailable",
                status_code=303,
            )

    @rt("/invoices/wizard/finish", methods=["GET"])
    async def finish_wizard(req: Request):
        redirect = require_session(req)
        if redirect:
            return redirect
        sid = get_session_id(req)
        wizard = _load_wizard(sid)
        irn = wizard.get("irn", "")
        _clear_wizard(sid)
        if irn:
            return RedirectResponse(f"/invoices/{irn}", status_code=303)
        return RedirectResponse("/invoices", status_code=303)

    @rt("/invoices/wizard/discard", methods=["GET"])
    async def discard_wizard(req: Request):
        redirect = require_session(req)
        if redirect:
            return redirect
        sid = get_session_id(req)
        _clear_wizard(sid)
        return RedirectResponse("/invoices", status_code=303)
