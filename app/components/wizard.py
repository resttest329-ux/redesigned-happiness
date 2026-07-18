import reflex as rx
from app.states.wizard_state import (
    WizardState,
    WizardLine,
    LookupItem,
    CustomerLite,
    LookupHit,
    StateOption,
    CountryOption,
)
from app.components.layout import app_shell


def _step_indicator() -> rx.Component:
    steps = [
        (1, "Header", "file-text"),
        (2, "Parties", "users"),
        (3, "Line items", "list"),
        (4, "Review & Sign", "shield-check"),
    ]

    def step_node(num: int, label: str, icon: str) -> rx.Component:
        is_active = WizardState.current_step == num
        is_done = WizardState.current_step > num
        is_reachable = num <= WizardState.max_step_reached
        return rx.el.button(
            rx.el.div(
                rx.cond(
                    is_done,
                    rx.icon("check", class_name="h-4 w-4"),
                    rx.el.span(num, class_name="text-xs font-bold"),
                ),
                class_name=rx.cond(
                    is_active,
                    "h-8 w-8 rounded-full bg-blue-600 text-white flex items-center justify-center shrink-0",
                    rx.cond(
                        is_done,
                        "h-8 w-8 rounded-full bg-green-600 text-white flex items-center justify-center shrink-0",
                        "h-8 w-8 rounded-full bg-gray-200 text-gray-500 flex items-center justify-center shrink-0",
                    ),
                ),
            ),
            rx.el.div(
                rx.el.p(
                    f"Step {num}",
                    class_name="text-xs uppercase text-gray-500 font-semibold tracking-wider",
                ),
                rx.el.p(
                    label,
                    class_name=rx.cond(
                        is_active,
                        "text-sm font-semibold text-blue-700",
                        "text-sm font-medium text-gray-700",
                    ),
                ),
                class_name="text-left hidden sm:block",
            ),
            on_click=lambda: WizardState.go_to_step(num),
            disabled=~is_reachable,
            type="button",
            class_name=rx.cond(
                is_reachable,
                "flex items-center gap-2 px-2 py-1 rounded-md hover:bg-gray-100 transition-colors",
                "flex items-center gap-2 px-2 py-1 opacity-50 cursor-not-allowed",
            ),
        )

    return rx.el.div(
        rx.el.div(
            step_node(1, "Header", "file-text"),
            rx.el.div(class_name="flex-1 h-px bg-gray-200 mx-2"),
            step_node(2, "Parties", "users"),
            rx.el.div(class_name="flex-1 h-px bg-gray-200 mx-2"),
            step_node(3, "Line items", "list"),
            rx.el.div(class_name="flex-1 h-px bg-gray-200 mx-2"),
            step_node(4, "Review & Sign", "shield-check"),
            class_name="flex items-center w-full",
        ),
        class_name="bg-white border border-gray-200 rounded-xl p-4 mb-6",
    )


def _messages() -> rx.Component:
    return rx.el.div(
        rx.cond(
            WizardState.error_message != "",
            rx.el.div(
                rx.icon("circle-alert", class_name="h-4 w-4 shrink-0"),
                rx.el.span(WizardState.error_message, class_name="text-sm"),
                rx.el.button(
                    rx.icon("x", class_name="h-3 w-3"),
                    on_click=WizardState.clear_messages,
                    class_name="ml-auto p-1",
                ),
                class_name="flex items-center gap-2 p-3 mb-4 bg-red-50 text-red-700 rounded-md border border-red-200",
            ),
            rx.fragment(),
        ),
        rx.cond(
            WizardState.success_message != "",
            rx.el.div(
                rx.icon("circle-check", class_name="h-4 w-4 shrink-0"),
                rx.el.span(WizardState.success_message, class_name="text-sm"),
                rx.el.button(
                    rx.icon("x", class_name="h-3 w-3"),
                    on_click=WizardState.clear_messages,
                    class_name="ml-auto p-1",
                ),
                class_name="flex items-center gap-2 p-3 mb-4 bg-green-50 text-green-700 rounded-md border border-green-200",
            ),
            rx.fragment(),
        ),
    )


def _input(
    name: str,
    label: str,
    default: rx.Var,
    placeholder: str = "",
    type_: str = "text",
    required: bool = True,
    helper: str = "",
) -> rx.Component:
    return rx.el.div(
        rx.el.label(
            label, class_name="block text-sm font-medium text-gray-700 mb-1.5"
        ),
        rx.el.input(
            name=name,
            type=type_,
            placeholder=placeholder,
            default_value=default,
            key=default.to_string(),
            required=required,
            class_name="w-full px-3 py-2 bg-white text-gray-900 border border-gray-300 rounded-md text-sm focus:outline-hidden focus:ring-2 focus:ring-blue-500",
        ),
        rx.cond(
            helper != "",
            rx.el.p(helper, class_name="text-xs text-gray-500 mt-1"),
            rx.fragment(),
        ),
        class_name="mb-4",
    )


def _select(
    name: str,
    label: str,
    default: rx.Var,
    options: rx.Var,
    on_change_handler,
    helper: str = "",
) -> rx.Component:
    return rx.el.div(
        rx.el.label(
            label, class_name="block text-sm font-medium text-gray-700 mb-1.5"
        ),
        rx.el.div(
            rx.el.select(
                rx.foreach(
                    options,
                    lambda opt: rx.el.option(opt["value"], value=opt["code"]),
                ),
                name=name,
                value=default,
                on_change=on_change_handler,
                class_name="w-full appearance-none px-3 py-2 bg-white text-gray-900 border border-gray-300 rounded-md text-sm focus:outline-hidden focus:ring-2 focus:ring-blue-500",
            ),
            rx.icon(
                "chevron-down",
                class_name="h-4 w-4 text-gray-400 absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none",
            ),
            class_name="relative",
        ),
        rx.cond(
            helper != "",
            rx.el.p(helper, class_name="text-xs text-gray-500 mt-1"),
            rx.fragment(),
        ),
        class_name="mb-4",
    )


def _currency_select() -> rx.Component:
    return rx.el.div(
        rx.el.label(
            "Currency",
            class_name="block text-sm font-medium text-gray-700 mb-1.5",
        ),
        rx.el.div(
            rx.el.select(
                rx.foreach(
                    WizardState.currencies,
                    lambda c: rx.el.option(
                        f"{c['code']} — {c['name']}", value=c["code"]
                    ),
                ),
                name="document_currency_code",
                default_value=WizardState.document_currency_code,
                key=WizardState.document_currency_code,
                class_name="w-full appearance-none px-3 py-2 bg-white text-gray-900 border border-gray-300 rounded-md text-sm focus:outline-hidden focus:ring-2 focus:ring-blue-500",
            ),
            rx.icon(
                "chevron-down",
                class_name="h-4 w-4 text-gray-400 absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none",
            ),
            class_name="relative",
        ),
        class_name="mb-4",
    )


def _irn_input_field() -> rx.Component:
    return rx.el.div(
        rx.el.label(
            "Invoice Reference Number (IRN)",
            class_name="block text-sm font-medium text-gray-700 mb-1.5",
        ),
        rx.el.div(
            rx.el.input(
                name="irn",
                type="text",
                placeholder="INV300-XXXXXX-BIZ-YYYYMMDD",
                default_value=WizardState.irn,
                key=WizardState.irn,
                required=True,
                disabled=~WizardState.allow_edit_irn,
                class_name=rx.cond(
                    WizardState.allow_edit_irn,
                    "w-full pl-3 pr-20 py-2 bg-white text-gray-900 border border-gray-300 rounded-md text-sm focus:outline-hidden focus:ring-2 focus:ring-blue-500",
                    "w-full pl-3 pr-20 py-2 bg-gray-50 text-gray-500 border border-gray-200 rounded-md text-sm cursor-not-allowed",
                ),
            ),
            rx.el.button(
                rx.cond(WizardState.allow_edit_irn, "Lock", "Edit"),
                on_click=WizardState.toggle_edit_irn,
                type="button",
                class_name="absolute right-2 top-1/2 -translate-y-1/2 px-3 py-1 bg-white border border-gray-300 text-gray-700 text-xs font-semibold rounded-md hover:bg-gray-50 hover:text-blue-600 transition-colors",
            ),
            class_name="relative",
        ),
        rx.el.p(
            "The valid staging/production IRN pattern is auto-generated from your registered Service ID and the invoice date using an advancing INV300+ sequence prefix pattern to avoid duplication conflicts. Editing is restricted by default to preserve conformity with FIRS templates; please note that changing the prefix requires a pre-provisioned template on the Peppol/PASCA gateway.",
            class_name="text-xs text-gray-500 mt-1",
        ),
        class_name="mb-4",
    )


def _step1() -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.el.h2(
                "Invoice header",
                class_name="text-lg font-semibold text-gray-900",
            ),
            rx.el.p(
                "Identify the invoice with its IRN, dates, and FIRS classification.",
                class_name="text-sm text-gray-500 mt-1",
            ),
            class_name="mb-6",
        ),
        rx.el.form(
            rx.el.div(
                _irn_input_field(),
                rx.el.div(
                    _input(
                        "issue_date",
                        "Issue date",
                        WizardState.issue_date,
                        "",
                        "date",
                    ),
                    _input(
                        "due_date",
                        "Due date",
                        WizardState.due_date,
                        "",
                        "date",
                        required=False,
                    ),
                    class_name="grid grid-cols-1 md:grid-cols-2 gap-x-4",
                ),
                rx.el.div(
                    _select(
                        "invoice_type_code",
                        "Invoice type",
                        WizardState.invoice_type_code,
                        WizardState.invoice_types,
                        WizardState.set_invoice_type_code,
                        "Some invoice types (credit/debit/self-billed) require a billing reference below.",
                    ),
                    _currency_select(),
                    class_name="grid grid-cols-1 md:grid-cols-2 gap-x-4",
                ),
                _select(
                    "payment_means_code",
                    "Payment means",
                    WizardState.payment_means_code,
                    WizardState.payment_means,
                    WizardState.set_payment_means_code,
                ),
                rx.cond(
                    (WizardState.invoice_type_code == "380")
                    | (WizardState.invoice_type_code == "384")
                    | (WizardState.invoice_type_code == "385"),
                    rx.el.div(
                        rx.el.h3(
                            "Billing reference (required)",
                            class_name="text-sm font-semibold text-gray-700 mb-2",
                        ),
                        rx.el.p(
                            "FIRS requires the original invoice's IRN and issue date for credit notes, debit notes, and self-billed invoices.",
                            class_name="text-xs text-gray-500 mb-3",
                        ),
                        rx.el.div(
                            _input(
                                "billing_reference_irn",
                                "Original IRN",
                                WizardState.billing_reference_irn,
                                "INV-...",
                                required=True,
                            ),
                            _input(
                                "billing_reference_issue_date",
                                "Original issue date",
                                WizardState.billing_reference_issue_date,
                                "",
                                "date",
                                required=True,
                            ),
                            class_name="grid grid-cols-1 md:grid-cols-2 gap-x-4",
                        ),
                        class_name="mt-4 p-4 bg-gray-50 rounded-md border border-gray-200",
                    ),
                    rx.fragment(),
                ),
                class_name="space-y-1",
            ),
            rx.el.div(
                rx.el.button(
                    rx.icon("trash-2", class_name="h-4 w-4"),
                    rx.el.span("Discard"),
                    type="button",
                    on_click=WizardState.discard_wizard,
                    class_name="flex items-center gap-2 px-4 py-2 bg-white border border-gray-300 text-gray-700 text-sm font-medium rounded-md hover:bg-gray-50",
                ),
                rx.el.button(
                    rx.el.span("Next: parties"),
                    rx.icon("arrow-right", class_name="h-4 w-4"),
                    type="submit",
                    class_name="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700",
                ),
                class_name="flex justify-between mt-6",
            ),
            on_submit=WizardState.save_step1,
            reset_on_submit=False,
        ),
        class_name="bg-white border border-gray-200 rounded-xl p-6",
    )


def _customer_chip(c: CustomerLite) -> rx.Component:
    return rx.el.button(
        rx.el.div(
            rx.el.p(
                c["party_name"],
                class_name="text-sm font-medium text-gray-900 truncate",
            ),
            rx.el.p(
                c["tin"], class_name="text-xs text-gray-500 font-mono truncate"
            ),
            class_name="text-left min-w-0",
        ),
        on_click=lambda: WizardState.select_saved_customer(c["id"]),
        type="button",
        class_name=rx.cond(
            WizardState.customer_id == c["id"],
            "px-3 py-2 rounded-md border border-blue-500 bg-blue-50 hover:bg-blue-100 min-w-0",
            "px-3 py-2 rounded-md border border-gray-200 bg-white hover:bg-gray-50 min-w-0",
        ),
    )


def _lookup_select(
    name: str,
    label: str,
    default: rx.Var,
    options: rx.Var,
    placeholder_label: str,
    helper: str = "",
    required: bool = True,
) -> rx.Component:
    return rx.el.div(
        rx.el.label(
            label, class_name="block text-sm font-medium text-gray-700 mb-1.5"
        ),
        rx.el.div(
            rx.el.select(
                rx.el.option(placeholder_label, value="", disabled=True),
                rx.foreach(
                    options,
                    lambda opt: rx.el.option(
                        f"{opt['name']} ({opt['code']})", value=opt["code"]
                    ),
                ),
                name=name,
                default_value=default,
                key=default,
                required=required,
                class_name="w-full appearance-none px-3 py-2 bg-white text-gray-900 border border-gray-300 rounded-md text-sm focus:outline-hidden focus:ring-2 focus:ring-blue-500",
            ),
            rx.icon(
                "chevron-down",
                class_name="h-4 w-4 text-gray-400 absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none",
            ),
            class_name="relative",
        ),
        rx.cond(
            helper != "",
            rx.el.p(helper, class_name="text-xs text-gray-500 mt-1"),
            rx.fragment(),
        ),
        class_name="mb-4",
    )


def _party_inputs(prefix: str, party_label: str) -> rx.Component:
    def get_var(field_name: str):
        return getattr(WizardState, f"{prefix}_{field_name}")

    return rx.el.div(
        rx.el.h3(
            party_label, class_name="text-base font-semibold text-gray-900 mb-3"
        ),
        rx.el.div(
            _input(
                f"{prefix}_tin",
                "TIN",
                get_var("tin"),
                "12345678-0001",
                helper="FIRS format: NNNNNNNN-NNNN",
            ),
            _input(
                f"{prefix}_party_name",
                "Company name",
                get_var("party_name"),
                "Acme Ltd",
            ),
            _input(
                f"{prefix}_email",
                "Email",
                get_var("email"),
                "billing@acme.com",
                "email",
            ),
            _input(
                f"{prefix}_telephone",
                "Telephone",
                get_var("telephone"),
                "+234...",
            ),
            _input(
                f"{prefix}_street_name",
                "Street",
                get_var("street_name"),
                "21 Main Street",
            ),
            _input(
                f"{prefix}_city_name",
                "City",
                get_var("city_name"),
                "Lagos",
            ),
            _input(
                f"{prefix}_postal_zone",
                "Postal zone",
                get_var("postal_zone"),
                "100001",
            ),
            _lookup_select(
                f"{prefix}_country",
                "Country",
                get_var("country"),
                WizardState.countries_options,
                "Select a country",
                helper="ISO-2 country code from FIRS lookup",
            ),
            _lookup_select(
                f"{prefix}_state",
                "State",
                get_var("state"),
                WizardState.states_options,
                "Select a state",
                helper="Nigerian state from FIRS lookup",
            ),
            _input(
                f"{prefix}_lga",
                "LGA",
                get_var("lga"),
                "Ikeja",
                required=False,
            ),
            class_name="grid grid-cols-1 md:grid-cols-2 gap-x-4",
        ),
        class_name="mb-2",
    )


def _supplier_summary() -> rx.Component:
    def field(label: str, value: rx.Var):
        return rx.el.div(
            rx.el.p(
                label,
                class_name="text-xs uppercase text-gray-500 font-semibold tracking-wider",
            ),
            rx.el.p(
                rx.cond(value != "", value, "—"),
                class_name="text-sm text-gray-900 mt-1",
            ),
        )

    return rx.el.div(
        rx.el.div(
            rx.el.div(
                rx.icon("building-2", class_name="h-5 w-5 text-blue-600"),
                rx.el.div(
                    rx.el.h3(
                        "Supplier (you)",
                        class_name="text-base font-semibold text-gray-900",
                    ),
                    rx.el.p(
                        "Read-only — pulled from your business profile.",
                        class_name="text-xs text-gray-500",
                    ),
                ),
                class_name="flex items-center gap-3",
            ),
            rx.el.a(
                rx.icon("settings", class_name="h-3 w-3"),
                rx.el.span("Edit in Settings"),
                href="/settings",
                class_name="flex items-center gap-1.5 text-xs font-medium text-blue-600 hover:underline",
            ),
            class_name="flex items-center justify-between mb-4",
        ),
        rx.el.div(
            field("Company name", WizardState.supplier_party_name),
            field("TIN", WizardState.supplier_tin),
            field("Email", WizardState.supplier_email),
            field("Telephone", WizardState.supplier_telephone),
            field("Street", WizardState.supplier_street_name),
            field("City", WizardState.supplier_city_name),
            field("State", WizardState.supplier_state),
            field("Country", WizardState.supplier_country),
            class_name="grid grid-cols-1 md:grid-cols-2 gap-4",
        ),
        class_name="bg-white border border-gray-200 rounded-xl p-6",
    )


def _selected_customer_summary() -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.el.div(
                WizardState.customer_party_name[0:1].upper(),
                class_name="h-10 w-10 rounded-full bg-blue-100 text-blue-700 flex items-center justify-center text-sm font-semibold shrink-0",
            ),
            rx.el.div(
                rx.el.p(
                    WizardState.customer_party_name,
                    class_name="text-sm font-semibold text-gray-900 truncate",
                ),
                rx.el.p(
                    rx.cond(
                        WizardState.customer_tin != "",
                        f"TIN {WizardState.customer_tin}",
                        "No TIN set",
                    ),
                    class_name="text-xs text-gray-500 font-mono truncate",
                ),
                class_name="min-w-0 flex-1",
            ),
            rx.el.button(
                rx.icon("x", class_name="h-3 w-3"),
                rx.el.span("Clear", class_name="text-xs"),
                type="button",
                on_click=WizardState.clear_customer,
                class_name="flex items-center gap-1 px-2 py-1 text-gray-500 hover:text-red-600 shrink-0",
            ),
            class_name="flex items-center gap-3",
        ),
        class_name="p-3 bg-blue-50 rounded-md border border-blue-200 mb-3",
    )


def _step2() -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.el.h2(
                "Supplier and customer",
                class_name="text-lg font-semibold text-gray-900",
            ),
            rx.el.p(
                "Your business is the supplier. Pick a saved customer or enter new details below.",
                class_name="text-sm text-gray-500 mt-1",
            ),
            class_name="mb-6",
        ),
        _supplier_summary(),
        rx.el.div(class_name="my-6"),
        rx.el.div(
            rx.el.div(
                rx.el.div(
                    rx.icon("user", class_name="h-5 w-5 text-blue-600"),
                    rx.el.div(
                        rx.el.h3(
                            "Customer",
                            class_name="text-base font-semibold text-gray-900",
                        ),
                        rx.el.p(
                            "Search saved customers or fill in details for a one-off invoice.",
                            class_name="text-xs text-gray-500",
                        ),
                    ),
                    class_name="flex items-center gap-3",
                ),
                rx.el.a(
                    rx.icon("users", class_name="h-3 w-3"),
                    rx.el.span("Manage customers"),
                    href="/customers",
                    class_name="flex items-center gap-1.5 text-xs font-medium text-blue-600 hover:underline",
                ),
                class_name="flex items-center justify-between mb-4",
            ),
            rx.cond(
                WizardState.customer_id > 0,
                _selected_customer_summary(),
                rx.fragment(),
            ),
            rx.cond(
                WizardState.saved_customers.length() > 0,
                rx.el.div(
                    rx.el.div(
                        rx.icon(
                            "search",
                            class_name="h-4 w-4 text-gray-400 absolute left-3 top-1/2 -translate-y-1/2",
                        ),
                        rx.el.input(
                            placeholder="Search saved customers by name, TIN, or email…",
                            on_change=WizardState.set_customer_search_query,
                            on_focus=WizardState.focus_customer_search,
                            on_blur=WizardState.blur_customer_search,
                            class_name="w-full pl-9 pr-3 py-2 bg-white text-gray-900 border border-gray-300 rounded-md text-sm focus:outline-hidden focus:ring-2 focus:ring-blue-500",
                            default_value=WizardState.customer_search_query,
                        ),
                        rx.cond(
                            WizardState.customer_search_query != "",
                            rx.el.button(
                                rx.icon("x", class_name="h-3 w-3"),
                                type="button",
                                on_click=WizardState.clear_customer_search,
                                class_name="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded hover:bg-gray-100 text-gray-500",
                            ),
                            rx.fragment(),
                        ),
                        class_name="relative mb-2",
                    ),
                    rx.cond(
                        WizardState.show_customer_results,
                        rx.cond(
                            WizardState.filtered_saved_customers.length() > 0,
                            rx.el.div(
                                rx.foreach(
                                    WizardState.filtered_saved_customers,
                                    _customer_chip,
                                ),
                                class_name="grid grid-cols-1 md:grid-cols-2 gap-2 max-h-56 overflow-auto",
                            ),
                            rx.el.p(
                                "No matching saved customers.",
                                class_name="text-xs text-gray-500 px-1",
                            ),
                        ),
                        rx.el.p(
                            f"Type to search across {WizardState.saved_customers.length()} saved customer(s), or fill in the form below for a one-off invoice.",
                            class_name="text-xs text-gray-500 px-1",
                        ),
                    ),
                    class_name="mb-4 p-4 bg-gray-50 rounded-md border border-gray-200",
                ),
                rx.fragment(),
            ),
            rx.el.form(
                _party_inputs("customer", "Customer details"),
                rx.el.div(
                    rx.el.button(
                        rx.icon("arrow-left", class_name="h-4 w-4"),
                        rx.el.span("Back"),
                        type="button",
                        on_click=WizardState.prev_step,
                        class_name="flex items-center gap-2 px-4 py-2 bg-white border border-gray-300 text-gray-700 text-sm font-medium rounded-md hover:bg-gray-50",
                    ),
                    rx.el.button(
                        rx.el.span("Next: line items"),
                        rx.icon("arrow-right", class_name="h-4 w-4"),
                        type="submit",
                        class_name="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700",
                    ),
                    class_name="flex justify-between mt-6",
                ),
                on_submit=WizardState.save_step2,
                reset_on_submit=False,
            ),
            class_name="bg-white border border-gray-200 rounded-xl p-6",
        ),
    )


def _line_row(line: WizardLine, index: int) -> rx.Component:
    return rx.el.tr(
        rx.el.td(
            rx.el.p(
                line["name"], class_name="text-sm font-medium text-gray-900"
            ),
            rx.el.p(
                rx.cond(
                    line["hsn_code"] != "",
                    f"HS {line['hsn_code']}",
                    f"ISIC {line['isic_code']}",
                ),
                class_name="text-xs text-gray-500 font-mono",
            ),
            class_name="px-4 py-3",
        ),
        rx.el.td(
            f"{line['invoiced_quantity']:.2f}",
            class_name="px-4 py-3 text-sm text-gray-700 text-right",
        ),
        rx.el.td(
            f"{line['price_amount']:.2f}",
            class_name="px-4 py-3 text-sm text-gray-700 text-right",
        ),
        rx.el.td(
            f"{line['invoiced_quantity'] * line['price_amount']:.2f}",
            class_name="px-4 py-3 text-sm font-medium text-gray-900 text-right",
        ),
        rx.el.td(
            rx.el.div(
                rx.el.button(
                    rx.icon("pencil", class_name="h-4 w-4"),
                    on_click=lambda: WizardState.open_edit_line(index),
                    type="button",
                    class_name="p-2 rounded-md text-gray-500 hover:bg-gray-100 hover:text-blue-600",
                ),
                rx.el.button(
                    rx.icon("trash-2", class_name="h-4 w-4"),
                    on_click=lambda: WizardState.remove_line(index),
                    type="button",
                    class_name="p-2 rounded-md text-gray-500 hover:bg-gray-100 hover:text-red-600",
                ),
                class_name="flex items-center justify-end gap-1",
            ),
            class_name="px-4 py-3",
        ),
        class_name="border-b border-gray-100",
    )


def _lookup_hit_row(h: LookupHit) -> rx.Component:
    return rx.el.button(
        rx.el.div(
            rx.el.div(
                rx.el.span(
                    rx.cond(h["kind"] == "product", "Product", "Service"),
                    class_name=rx.cond(
                        h["kind"] == "product",
                        "inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold bg-blue-100 text-blue-700 uppercase tracking-wider w-fit shrink-0",
                        "inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold bg-purple-100 text-purple-700 uppercase tracking-wider w-fit shrink-0",
                    ),
                ),
                rx.el.p(
                    h["label"],
                    class_name="text-sm text-gray-900 truncate text-left",
                ),
                class_name="flex items-center gap-2 min-w-0",
            ),
            rx.el.p(
                rx.cond(
                    h["kind"] == "product",
                    f"HS {h['code']} · {h['category']}",
                    f"ISIC {h['code']}",
                ),
                class_name="text-xs text-gray-500 font-mono text-left mt-0.5",
            ),
            class_name="min-w-0",
        ),
        on_click=lambda: WizardState.apply_lookup_hit(
            h["kind"], h["code"], h["label"], h["category"]
        ),
        type="button",
        class_name="w-full px-3 py-2 hover:bg-blue-50 border-b border-gray-100 last:border-b-0 text-left",
    )


def _line_form_modal() -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.el.div(
                rx.el.div(
                    rx.el.h2(
                        rx.cond(
                            WizardState.edit_line_index >= 0,
                            "Edit line item",
                            "New line item",
                        ),
                        class_name="text-lg font-semibold text-gray-900",
                    ),
                    rx.el.button(
                        rx.icon("x", class_name="h-4 w-4"),
                        on_click=WizardState.close_line_form,
                        type="button",
                        class_name="p-1.5 rounded-md hover:bg-gray-100",
                    ),
                    class_name="flex items-center justify-between p-5 border-b border-gray-200",
                ),
                rx.el.div(
                    rx.el.div(
                        rx.el.div(
                            rx.el.h4(
                                "Item lookup",
                                class_name="text-sm font-semibold text-gray-700",
                            ),
                            rx.el.p(
                                "Search across HS codes (products) and ISIC codes (services).",
                                class_name="text-xs text-gray-500 mt-0.5",
                            ),
                            class_name="mb-3",
                        ),
                        rx.el.div(
                            rx.icon(
                                "search",
                                class_name="h-4 w-4 text-gray-400 absolute left-3 top-1/2 -translate-y-1/2",
                            ),
                            rx.el.input(
                                placeholder="Search products & services (e.g. 'computer', 'consulting')…",
                                default_value=WizardState.lookup_query,
                                on_change=WizardState.search_lookup.debounce(
                                    400
                                ),
                                class_name="w-full pl-9 pr-3 py-2 bg-white text-gray-900 border border-gray-300 rounded-md text-sm focus:outline-hidden focus:ring-2 focus:ring-blue-500",
                            ),
                            class_name="relative",
                        ),
                        rx.cond(
                            WizardState.lookup_loading,
                            rx.el.div(
                                rx.icon(
                                    "loader-circle",
                                    class_name="h-4 w-4 text-blue-600 animate-spin",
                                ),
                                class_name="flex items-center justify-center py-3",
                            ),
                            rx.cond(
                                WizardState.lookup_hits.length() > 0,
                                rx.el.div(
                                    rx.foreach(
                                        WizardState.lookup_hits,
                                        _lookup_hit_row,
                                    ),
                                    class_name="mt-2 max-h-56 overflow-auto rounded-md border border-gray-200 bg-white",
                                ),
                                rx.fragment(),
                            ),
                        ),
                        rx.cond(
                            (WizardState.line_form["hsn_code"] != "")
                            | (WizardState.line_form["isic_code"] != ""),
                            rx.el.div(
                                rx.icon(
                                    "circle-check",
                                    class_name="h-4 w-4 text-green-600",
                                ),
                                rx.el.span(
                                    rx.cond(
                                        WizardState.line_form["hsn_code"] != "",
                                        f"HS {WizardState.line_form['hsn_code']} · {WizardState.line_form['product_category']}",
                                        f"ISIC {WizardState.line_form['isic_code']} · {WizardState.line_form['service_category']}",
                                    ),
                                    class_name="text-sm text-green-700",
                                ),
                                class_name="flex items-center gap-2 mt-3 p-2 bg-green-50 rounded-md border border-green-200",
                            ),
                            rx.fragment(),
                        ),
                        class_name="p-4 bg-gray-50 border-b border-gray-200",
                    ),
                    rx.el.form(
                        rx.el.div(
                            _input(
                                "name",
                                "Item name",
                                WizardState.line_form["name"],
                                "Web design services",
                            ),
                            _input(
                                "description",
                                "Description",
                                WizardState.line_form["description"],
                                "Optional details",
                                required=False,
                            ),
                            _input(
                                "sellers_item_identification",
                                "SKU",
                                WizardState.line_form[
                                    "sellers_item_identification"
                                ],
                                "Optional",
                                required=False,
                            ),
                            class_name="p-5",
                        ),
                        rx.el.div(
                            rx.el.div(
                                _input(
                                    "invoiced_quantity",
                                    "Quantity",
                                    WizardState.line_form["invoiced_quantity"],
                                    "1",
                                    "number",
                                ),
                                _input(
                                    "price_amount",
                                    "Unit price",
                                    WizardState.line_form["price_amount"],
                                    "0.00",
                                    "number",
                                ),
                                _input(
                                    "base_quantity",
                                    "Base quantity",
                                    WizardState.line_form["base_quantity"],
                                    "1",
                                    "number",
                                ),
                                _input(
                                    "price_unit",
                                    "Price unit",
                                    WizardState.line_form["price_unit"],
                                    "NGN per 1",
                                ),
                                _input(
                                    "discount_rate",
                                    "Discount rate (%)",
                                    WizardState.line_form["discount_rate"],
                                    "0",
                                    "number",
                                    required=False,
                                ),
                                _input(
                                    "discount_amount",
                                    "Discount amount",
                                    WizardState.line_form["discount_amount"],
                                    "0",
                                    "number",
                                    required=False,
                                ),
                                _input(
                                    "fee_rate",
                                    "Fee rate (%)",
                                    WizardState.line_form["fee_rate"],
                                    "0",
                                    "number",
                                    required=False,
                                ),
                                _input(
                                    "fee_amount",
                                    "Fee amount",
                                    WizardState.line_form["fee_amount"],
                                    "0",
                                    "number",
                                    required=False,
                                ),
                                class_name="grid grid-cols-1 md:grid-cols-2 gap-x-4 px-5 pb-5",
                            ),
                        ),
                        rx.el.div(
                            rx.el.button(
                                "Cancel",
                                type="button",
                                on_click=WizardState.close_line_form,
                                class_name="px-4 py-2 bg-white border border-gray-300 text-gray-700 text-sm font-medium rounded-md hover:bg-gray-50",
                            ),
                            rx.el.button(
                                rx.cond(
                                    WizardState.edit_line_index >= 0,
                                    "Update line",
                                    "Add line",
                                ),
                                type="submit",
                                class_name="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700",
                            ),
                            class_name="flex justify-end gap-2 p-4 border-t border-gray-200 bg-gray-50",
                        ),
                        on_submit=WizardState.save_line,
                        reset_on_submit=False,
                    ),
                ),
                class_name="bg-white rounded-xl border border-gray-200 w-full max-w-3xl max-h-[90vh] overflow-auto",
            ),
            class_name="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4",
        ),
    )


def _step3() -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.el.div(
                rx.el.h2(
                    "Line items",
                    class_name="text-lg font-semibold text-gray-900",
                ),
                rx.el.p(
                    "Add the goods and services being invoiced. Use the lookup to attach FIRS HS / ISIC codes.",
                    class_name="text-sm text-gray-500 mt-1",
                ),
            ),
            rx.el.button(
                rx.icon("plus", class_name="h-4 w-4"),
                rx.el.span("Add line"),
                type="button",
                on_click=WizardState.open_new_line,
                class_name="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700",
            ),
            class_name="flex items-center justify-between mb-6",
        ),
        rx.cond(
            WizardState.lines.length() == 0,
            rx.el.div(
                rx.icon(
                    "list", class_name="h-10 w-10 text-gray-300 mx-auto mb-3"
                ),
                rx.el.p(
                    "No line items yet",
                    class_name="text-base font-semibold text-gray-900",
                ),
                rx.el.p(
                    "Add at least one item to continue.",
                    class_name="text-sm text-gray-500 mt-1",
                ),
                class_name="text-center py-12 bg-gray-50 rounded-xl border border-dashed border-gray-300",
            ),
            rx.el.div(
                rx.el.table(
                    rx.el.thead(
                        rx.el.tr(
                            rx.el.th(
                                "Item",
                                class_name="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider",
                            ),
                            rx.el.th(
                                "Qty",
                                class_name="px-4 py-3 text-right text-xs font-semibold text-gray-500 uppercase tracking-wider",
                            ),
                            rx.el.th(
                                "Unit price",
                                class_name="px-4 py-3 text-right text-xs font-semibold text-gray-500 uppercase tracking-wider",
                            ),
                            rx.el.th(
                                "Subtotal",
                                class_name="px-4 py-3 text-right text-xs font-semibold text-gray-500 uppercase tracking-wider",
                            ),
                            rx.el.th("", class_name="px-4 py-3"),
                            class_name="border-b border-gray-200 bg-gray-50",
                        ),
                    ),
                    rx.el.tbody(
                        rx.foreach(
                            WizardState.lines,
                            lambda line, idx: _line_row(line, idx),
                        ),
                    ),
                    class_name="table-auto w-full",
                ),
                class_name="overflow-hidden rounded-xl border border-gray-200 bg-white",
            ),
        ),
        rx.el.div(
            rx.el.div(
                rx.el.p("Subtotal", class_name="text-sm text-gray-600"),
                rx.el.p(
                    f"{WizardState.document_currency_code} {WizardState.ux_subtotal:.2f}",
                    class_name="text-sm font-medium text-gray-900",
                ),
                class_name="flex items-center justify-between py-2",
            ),
            rx.el.div(
                rx.el.p("VAT (7.5%)", class_name="text-sm text-gray-600"),
                rx.el.p(
                    f"{WizardState.document_currency_code} {WizardState.ux_tax:.2f}",
                    class_name="text-sm font-medium text-gray-900",
                ),
                class_name="flex items-center justify-between py-2",
            ),
            rx.el.div(
                rx.el.p(
                    "Total payable",
                    class_name="text-base font-semibold text-gray-900",
                ),
                rx.el.p(
                    f"{WizardState.document_currency_code} {WizardState.ux_total:.2f}",
                    class_name="text-lg font-bold text-blue-700",
                ),
                class_name="flex items-center justify-between py-2 border-t border-gray-200 mt-2",
            ),
            class_name="bg-white border border-gray-200 rounded-xl p-5 mt-4",
        ),
        rx.el.div(
            rx.el.button(
                rx.icon("arrow-left", class_name="h-4 w-4"),
                rx.el.span("Back"),
                type="button",
                on_click=WizardState.prev_step,
                class_name="flex items-center gap-2 px-4 py-2 bg-white border border-gray-300 text-gray-700 text-sm font-medium rounded-md hover:bg-gray-50",
            ),
            rx.el.button(
                rx.el.span("Next: review"),
                rx.icon("arrow-right", class_name="h-4 w-4"),
                type="button",
                on_click=WizardState.next_step,
                class_name="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700",
            ),
            class_name="flex justify-between mt-6",
        ),
        rx.cond(WizardState.show_line_form, _line_form_modal(), rx.fragment()),
    )


def _summary_card() -> rx.Component:
    return rx.el.div(
        rx.el.h3(
            "Invoice summary",
            class_name="text-base font-semibold text-gray-900 mb-4",
        ),
        rx.el.div(
            rx.el.div(
                rx.el.p(
                    "IRN",
                    class_name="text-xs uppercase text-gray-500 font-semibold tracking-wider",
                ),
                rx.el.p(
                    WizardState.irn,
                    class_name="text-sm font-mono text-gray-900 mt-1 break-all",
                ),
            ),
            rx.el.div(
                rx.el.p(
                    "Issue date",
                    class_name="text-xs uppercase text-gray-500 font-semibold tracking-wider",
                ),
                rx.el.p(
                    WizardState.issue_date,
                    class_name="text-sm text-gray-900 mt-1",
                ),
            ),
            rx.el.div(
                rx.el.p(
                    "Customer",
                    class_name="text-xs uppercase text-gray-500 font-semibold tracking-wider",
                ),
                rx.el.p(
                    WizardState.customer_party_name,
                    class_name="text-sm text-gray-900 mt-1",
                ),
            ),
            rx.el.div(
                rx.el.p(
                    "Lines",
                    class_name="text-xs uppercase text-gray-500 font-semibold tracking-wider",
                ),
                rx.el.p(
                    WizardState.lines.length().to_string(),
                    class_name="text-sm text-gray-900 mt-1",
                ),
            ),
            class_name="grid grid-cols-2 gap-4",
        ),
        rx.el.div(class_name="my-4 border-t border-gray-200"),
        rx.el.div(
            rx.el.div(
                rx.el.p("Subtotal", class_name="text-sm text-gray-600"),
                rx.el.p(
                    f"{WizardState.document_currency_code} {WizardState.computed_totals['tax_exclusive_amount']:.2f}",
                    class_name="text-sm text-gray-900",
                ),
                class_name="flex items-center justify-between py-1",
            ),
            rx.el.div(
                rx.el.p("VAT", class_name="text-sm text-gray-600"),
                rx.el.p(
                    f"{WizardState.document_currency_code} {WizardState.computed_totals['tax_amount']:.2f}",
                    class_name="text-sm text-gray-900",
                ),
                class_name="flex items-center justify-between py-1",
            ),
            rx.el.div(
                rx.el.p(
                    "Total payable",
                    class_name="text-sm font-semibold text-gray-900",
                ),
                rx.el.p(
                    f"{WizardState.document_currency_code} {WizardState.computed_totals['payable_amount']:.2f}",
                    class_name="text-base font-bold text-blue-700",
                ),
                class_name="flex items-center justify-between py-2 border-t border-gray-200 mt-1",
            ),
        ),
        class_name="bg-white border border-gray-200 rounded-xl p-6",
    )


def _lifecycle_step(
    num: int, label: str, done: rx.Var, busy_key: str
) -> rx.Component:
    is_busy = WizardState.busy_action == busy_key
    return rx.el.div(
        rx.el.div(
            rx.cond(
                done,
                rx.icon("check", class_name="h-4 w-4 text-white"),
                rx.cond(
                    is_busy,
                    rx.icon(
                        "loader-circle",
                        class_name="h-4 w-4 text-white animate-spin",
                    ),
                    rx.el.span(num, class_name="text-xs font-bold text-white"),
                ),
            ),
            class_name=rx.cond(
                done,
                "h-7 w-7 rounded-full bg-green-600 flex items-center justify-center shrink-0",
                "h-7 w-7 rounded-full bg-gray-400 flex items-center justify-center shrink-0",
            ),
        ),
        rx.el.p(label, class_name="text-sm font-medium text-gray-900"),
        class_name="flex items-center gap-3 py-2",
    )


def _sign_modal() -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.el.div(
                rx.el.div(
                    rx.icon("shield-check", class_name="h-5 w-5 text-blue-600"),
                    rx.el.h2(
                        "Confirm signing",
                        class_name="text-lg font-semibold text-gray-900",
                    ),
                    class_name="flex items-center gap-2 p-5 border-b border-gray-200",
                ),
                rx.el.form(
                    rx.el.div(
                        rx.el.p(
                            "Enter your signing secret to authorise this invoice for FIRS submission.",
                            class_name="text-sm text-gray-600 mb-4",
                        ),
                        rx.el.label(
                            "Signing secret",
                            class_name="block text-sm font-medium text-gray-700 mb-1.5",
                        ),
                        rx.el.input(
                            name="user_secret",
                            type="password",
                            required=True,
                            placeholder="Enter your signing secret",
                            class_name="w-full px-3 py-2 bg-white text-gray-900 border border-gray-300 rounded-md text-sm focus:outline-hidden focus:ring-2 focus:ring-blue-500",
                        ),
                        class_name="p-5",
                    ),
                    rx.el.div(
                        rx.el.button(
                            "Cancel",
                            type="button",
                            on_click=WizardState.close_sign_modal,
                            disabled=WizardState.loading,
                            class_name="px-4 py-2 bg-white border border-gray-300 text-gray-700 text-sm font-medium rounded-md hover:bg-gray-50 transition-all active:scale-[0.98]",
                        ),
                        rx.el.button(
                            rx.cond(
                                WizardState.loading,
                                rx.el.span(
                                    rx.icon(
                                        "loader-circle",
                                        class_name="h-4 w-4 animate-spin inline mr-1.5",
                                    ),
                                    "Signing...",
                                ),
                                rx.el.span("Sign invoice"),
                            ),
                            type="submit",
                            disabled=WizardState.loading,
                            class_name="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all active:scale-[0.98]",
                        ),
                        class_name="flex justify-end gap-2 p-4 border-t border-gray-200 bg-gray-50",
                    ),
                    on_submit=WizardState.sign,
                    reset_on_submit=True,
                ),
                class_name="bg-white rounded-xl border border-gray-200 w-full max-w-md",
            ),
            class_name="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4",
        ),
    )


def _step4() -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.el.h2(
                "Review and submit",
                class_name="text-lg font-semibold text-gray-900",
            ),
            rx.el.p(
                "Assemble the FIRS invoice schema, validate, sign with your secret, and optionally transmit.",
                class_name="text-sm text-gray-500 mt-1",
            ),
            class_name="mb-6",
        ),
        rx.el.div(
            _summary_card(),
            rx.el.div(
                rx.el.h3(
                    "Lifecycle",
                    class_name="text-base font-semibold text-gray-900 mb-2",
                ),
                _lifecycle_step(
                    1,
                    "Assembled (computed totals)",
                    WizardState.computed_totals["payable_amount"] > 0,
                    "assemble",
                ),
                _lifecycle_step(
                    2,
                    "Validated against FIRS schema",
                    WizardState.validated,
                    "validate",
                ),
                _lifecycle_step(3, "Signed", WizardState.signed, "sign"),
                _lifecycle_step(
                    4,
                    "Transmitted to FIRS (optional)",
                    WizardState.transmitted,
                    "transmit",
                ),
                rx.cond(
                    WizardState.log_created,
                    rx.el.p(
                        "✓ Local invoice log entry created.",
                        class_name="text-xs text-green-700 mt-2",
                    ),
                    rx.fragment(),
                ),
                class_name="bg-white border border-gray-200 rounded-xl p-6 mt-4",
            ),
            class_name="grid grid-cols-1 md:grid-cols-2 gap-4",
        ),
        rx.el.div(
            rx.el.div(
                rx.el.p(
                    rx.cond(
                        WizardState.busy_action != "",
                        f"Working on: {WizardState.busy_action}…",
                        "Run each step in order. Other actions stay available so you can review while a step runs.",
                    ),
                    class_name=rx.cond(
                        WizardState.busy_action != "",
                        "text-xs text-blue-700 mb-3 flex items-center gap-1.5",
                        "text-xs text-gray-500 mb-3",
                    ),
                ),
                rx.el.div(
                    rx.el.button(
                        rx.cond(
                            WizardState.busy_action == "assemble",
                            rx.icon(
                                "loader-circle",
                                class_name="h-4 w-4 animate-spin",
                            ),
                            rx.icon("calculator", class_name="h-4 w-4"),
                        ),
                        rx.el.span("Assemble"),
                        on_click=WizardState.assemble,
                        type="button",
                        disabled=WizardState.busy_action != "",
                        aria_busy=WizardState.busy_action == "assemble",
                        class_name="flex items-center gap-2 px-4 py-2 bg-white border border-gray-300 text-gray-700 text-sm font-medium rounded-md hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-blue-500 transition-all active:scale-[0.98]",
                    ),
                    rx.el.button(
                        rx.cond(
                            WizardState.busy_action == "validate",
                            rx.icon(
                                "loader-circle",
                                class_name="h-4 w-4 animate-spin",
                            ),
                            rx.icon("circle-check", class_name="h-4 w-4"),
                        ),
                        rx.el.span("Validate"),
                        on_click=WizardState.validate,
                        type="button",
                        disabled=WizardState.busy_action != "",
                        aria_busy=WizardState.busy_action == "validate",
                        class_name="flex items-center gap-2 px-4 py-2 bg-white border border-gray-300 text-gray-700 text-sm font-medium rounded-md hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-blue-500 transition-all active:scale-[0.98]",
                    ),
                    rx.el.button(
                        rx.icon("shield-check", class_name="h-4 w-4"),
                        rx.el.span("Sign"),
                        on_click=WizardState.open_sign_modal,
                        type="button",
                        disabled=(WizardState.busy_action != "")
                        | ~WizardState.validated,
                        class_name="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1 transition-all active:scale-[0.98]",
                    ),
                    rx.el.button(
                        rx.cond(
                            WizardState.busy_action == "transmit",
                            rx.icon(
                                "loader-circle",
                                class_name="h-4 w-4 animate-spin",
                            ),
                            rx.icon("send", class_name="h-4 w-4"),
                        ),
                        rx.el.span("Transmit"),
                        on_click=WizardState.transmit,
                        type="button",
                        disabled=(WizardState.busy_action != "")
                        | ~WizardState.signed,
                        aria_busy=WizardState.busy_action == "transmit",
                        class_name="flex items-center gap-2 px-4 py-2 bg-green-600 text-white text-sm font-medium rounded-md hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-green-500 focus:ring-offset-1 transition-all active:scale-[0.98]",
                    ),
                    class_name="flex flex-wrap items-center gap-2",
                ),
            ),
            class_name="bg-white border border-gray-200 rounded-xl p-4 mt-4",
        ),
        rx.el.div(
            rx.el.button(
                rx.icon("arrow-left", class_name="h-4 w-4"),
                rx.el.span("Back"),
                type="button",
                on_click=WizardState.prev_step,
                class_name="flex items-center gap-2 px-4 py-2 bg-white border border-gray-300 text-gray-700 text-sm font-medium rounded-md hover:bg-gray-50",
            ),
            rx.cond(
                WizardState.signed,
                rx.el.button(
                    rx.icon("circle-check", class_name="h-4 w-4"),
                    rx.el.span("Finish & view invoice"),
                    type="button",
                    on_click=WizardState.finish_and_clear,
                    class_name="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700",
                ),
                rx.el.button(
                    rx.icon("trash-2", class_name="h-4 w-4"),
                    rx.el.span("Discard progress"),
                    type="button",
                    on_click=WizardState.discard_wizard,
                    class_name="flex items-center gap-2 px-4 py-2 bg-white border border-gray-300 text-gray-700 text-sm font-medium rounded-md hover:bg-gray-50",
                ),
            ),
            class_name="flex justify-between mt-6",
        ),
        rx.cond(WizardState.show_sign_modal, _sign_modal(), rx.fragment()),
    )


def wizard_content() -> rx.Component:
    return rx.el.div(
        rx.el.a(
            rx.icon("arrow-left", class_name="h-4 w-4"),
            rx.el.span("Back to invoices"),
            href="/invoices",
            class_name="inline-flex items-center gap-2 text-sm text-gray-600 hover:text-blue-600 mb-4",
        ),
        rx.el.div(
            rx.el.h1(
                "New FIRS invoice",
                class_name="text-2xl font-bold text-gray-900",
            ),
            rx.el.p(
                "Build, validate, sign, and transmit your e-invoice in four guided steps.",
                class_name="text-sm text-gray-500 mt-1",
            ),
            class_name="mb-6",
        ),
        _step_indicator(),
        _messages(),
        rx.match(
            WizardState.current_step,
            (1, _step1()),
            (2, _step2()),
            (3, _step3()),
            (4, _step4()),
            _step1(),
        ),
    )


def invoice_wizard_page() -> rx.Component:
    return app_shell(wizard_content())