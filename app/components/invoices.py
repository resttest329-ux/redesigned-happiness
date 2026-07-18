import reflex as rx
from app.states.invoice_log_state import InvoiceLogState, InvoiceLogItem
from app.components.layout import app_shell


def _status_badge(status: rx.Var) -> rx.Component:
    return rx.el.span(
        status,
        class_name=rx.match(
            status,
            (
                "PAID",
                "inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-700 w-fit",
            ),
            (
                "PENDING",
                "inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-yellow-100 text-yellow-700 w-fit",
            ),
            (
                "REJECTED",
                "inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-700 w-fit",
            ),
            (
                "PARTIAL",
                "inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-700 w-fit",
            ),
            "inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-700 w-fit",
        ),
    )


def _transmit_badge(transmitted: rx.Var) -> rx.Component:
    return rx.cond(
        transmitted,
        rx.el.span(
            rx.icon("circle-check", class_name="h-3 w-3"),
            rx.el.span("Transmitted"),
            class_name="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-green-50 text-green-700 border border-green-200 w-fit",
        ),
        rx.el.span(
            rx.icon("clock", class_name="h-3 w-3"),
            rx.el.span("Pending"),
            class_name="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-gray-50 text-gray-600 border border-gray-200 w-fit",
        ),
    )


def _status_modal() -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.el.div(
                rx.el.h2(
                    "Update payment status",
                    class_name="text-lg font-semibold text-gray-900",
                ),
                rx.el.p(
                    f"Set the payment status for {InvoiceLogState.status_irn}",
                    class_name="text-sm text-gray-500 mt-1",
                ),
                class_name="p-5 border-b border-gray-200",
            ),
            rx.el.form(
                rx.el.div(
                    rx.el.div(
                        rx.el.label(
                            "Status",
                            class_name="block text-sm font-medium text-gray-700 mb-1.5",
                        ),
                        rx.el.div(
                            rx.el.select(
                                rx.el.option("PENDING", value="PENDING"),
                                rx.el.option("PAID", value="PAID"),
                                rx.el.option("PARTIAL", value="PARTIAL"),
                                rx.el.option("REJECTED", value="REJECTED"),
                                value=InvoiceLogState.new_status,
                                on_change=InvoiceLogState.set_new_status,
                                class_name="w-full appearance-none px-3 py-2 bg-white text-gray-900 border border-gray-300 rounded-md text-sm focus:outline-hidden focus:ring-2 focus:ring-blue-500",
                            ),
                            rx.icon(
                                "chevron-down",
                                class_name="h-4 w-4 text-gray-400 absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none",
                            ),
                            class_name="relative",
                        ),
                        class_name="mb-4",
                    ),
                    rx.el.div(
                        rx.el.label(
                            "Signing secret",
                            class_name="block text-sm font-medium text-gray-700 mb-1.5",
                        ),
                        rx.el.input(
                            name="user_secret",
                            type="password",
                            required=True,
                            placeholder="Enter your signing secret",
                            default_value=InvoiceLogState.status_user_secret,
                            key=InvoiceLogState.status_user_secret,
                            class_name="w-full px-3 py-2 bg-white text-gray-900 border border-gray-300 rounded-md text-sm focus:outline-hidden focus:ring-2 focus:ring-blue-500",
                        ),
                        rx.el.p(
                            "Required to authorise this status update with FIRS.",
                            class_name="text-xs text-gray-500 mt-1",
                        ),
                    ),
                    class_name="p-5",
                ),
                rx.el.div(
                    rx.el.button(
                        "Cancel",
                        type="button",
                        on_click=InvoiceLogState.close_status_modal,
                        disabled=InvoiceLogState.loading,
                        class_name="px-4 py-2 bg-white border border-gray-300 text-gray-700 text-sm font-medium rounded-md hover:bg-gray-50 transition-all active:scale-[0.98]",
                    ),
                    rx.el.button(
                        rx.cond(
                            InvoiceLogState.loading,
                            rx.el.span(
                                rx.icon(
                                    "loader-circle",
                                    class_name="h-4 w-4 animate-spin inline mr-1.5",
                                ),
                                "Updating...",
                            ),
                            rx.el.span("Update"),
                        ),
                        type="submit",
                        disabled=InvoiceLogState.loading,
                        class_name="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all active:scale-[0.98]",
                    ),
                    class_name="flex justify-end gap-2 p-4 border-t border-gray-200 bg-gray-50",
                ),
                on_submit=InvoiceLogState.submit_status_change,
                reset_on_submit=True,
            ),
            class_name="bg-white rounded-xl border border-gray-200 w-full max-w-md",
        ),
        class_name="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4",
    )


def _party_card(title: str, party: rx.Var, icon: str) -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.icon(icon, class_name="h-4 w-4 text-blue-600"),
            rx.el.h4(
                title,
                class_name="text-xs uppercase text-gray-500 font-semibold tracking-wider",
            ),
            class_name="flex items-center gap-2 mb-3",
        ),
        rx.el.p(
            party["party_name"],
            class_name="text-sm font-semibold text-gray-900",
        ),
        rx.cond(
            party["tin"] != "",
            rx.el.p(
                f"TIN: {party['tin']}",
                class_name="text-xs font-mono text-gray-600 mt-1",
            ),
            rx.fragment(),
        ),
        rx.cond(
            party["email"] != "",
            rx.el.p(party["email"], class_name="text-xs text-gray-600 mt-1"),
            rx.fragment(),
        ),
        rx.cond(
            party["telephone"] != "",
            rx.el.p(
                party["telephone"], class_name="text-xs text-gray-600 mt-1"
            ),
            rx.fragment(),
        ),
        rx.cond(
            party["address"] != "",
            rx.el.p(party["address"], class_name="text-xs text-gray-500 mt-2"),
            rx.fragment(),
        ),
        class_name="bg-white border border-gray-200 rounded-xl p-4",
    )


def _auth_line_row(line) -> rx.Component:
    return rx.el.tr(
        rx.el.td(
            rx.el.p(
                line["name"],
                class_name="text-sm font-medium text-gray-900",
            ),
            rx.cond(
                line["code"] != "",
                rx.el.p(
                    line["code"],
                    class_name="text-xs text-gray-500 font-mono",
                ),
                rx.fragment(),
            ),
            class_name="px-4 py-3",
        ),
        rx.el.td(
            f"{line['quantity']:.2f}",
            class_name="px-4 py-3 text-sm text-gray-700 text-right",
        ),
        rx.el.td(
            f"{line['unit_price']:.2f}",
            class_name="px-4 py-3 text-sm text-gray-700 text-right",
        ),
        rx.el.td(
            f"{line['line_total']:.2f}",
            class_name="px-4 py-3 text-sm font-medium text-gray-900 text-right",
        ),
        class_name="border-b border-gray-100",
    )


def _authoritative_section() -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.el.div(
                rx.icon("shield-check", class_name="h-4 w-4 text-green-600"),
                rx.el.h3(
                    "FIRS authoritative data",
                    class_name="text-base font-semibold text-gray-900",
                ),
                class_name="flex items-center gap-2 mb-4",
            ),
            rx.el.div(
                _party_card(
                    "Supplier",
                    InvoiceLogState.auth_supplier,
                    "building-2",
                ),
                _party_card(
                    "Customer",
                    InvoiceLogState.auth_customer,
                    "user",
                ),
                class_name="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-4",
            ),
            rx.cond(
                InvoiceLogState.auth_lines.length() > 0,
                rx.el.div(
                    rx.el.h4(
                        "Line items",
                        class_name="text-xs uppercase text-gray-500 font-semibold tracking-wider mb-2",
                    ),
                    rx.el.div(
                        rx.el.table(
                            rx.el.thead(
                                rx.el.tr(
                                    rx.el.th(
                                        "Item",
                                        class_name="px-4 py-2 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider",
                                    ),
                                    rx.el.th(
                                        "Qty",
                                        class_name="px-4 py-2 text-right text-xs font-semibold text-gray-500 uppercase tracking-wider",
                                    ),
                                    rx.el.th(
                                        "Unit",
                                        class_name="px-4 py-2 text-right text-xs font-semibold text-gray-500 uppercase tracking-wider",
                                    ),
                                    rx.el.th(
                                        "Total",
                                        class_name="px-4 py-2 text-right text-xs font-semibold text-gray-500 uppercase tracking-wider",
                                    ),
                                    class_name="border-b border-gray-200 bg-gray-50",
                                ),
                            ),
                            rx.el.tbody(
                                rx.foreach(
                                    InvoiceLogState.auth_lines,
                                    _auth_line_row,
                                ),
                            ),
                            class_name="table-auto w-full",
                        ),
                        class_name="overflow-hidden rounded-md border border-gray-200",
                    ),
                ),
                rx.fragment(),
            ),
            class_name="bg-white border border-gray-200 rounded-xl p-6",
        ),
    )


def _messages() -> rx.Component:
    return rx.el.div(
        rx.cond(
            InvoiceLogState.error_message != "",
            rx.el.div(
                rx.icon("circle-alert", class_name="h-4 w-4"),
                rx.el.span(InvoiceLogState.error_message, class_name="text-sm"),
                class_name="flex items-center gap-2 p-3 mb-4 bg-red-50 text-red-700 rounded-md border border-red-200",
            ),
            rx.fragment(),
        ),
        rx.cond(
            InvoiceLogState.success_message != "",
            rx.el.div(
                rx.icon("circle-check", class_name="h-4 w-4"),
                rx.el.span(
                    InvoiceLogState.success_message, class_name="text-sm"
                ),
                class_name="flex items-center gap-2 p-3 mb-4 bg-green-50 text-green-700 rounded-md border border-green-200",
            ),
            rx.fragment(),
        ),
    )


def _invoice_row(item: InvoiceLogItem) -> rx.Component:
    is_transmitting = InvoiceLogState.transmitting_irns.contains(item["irn"])
    return rx.el.tr(
        rx.el.td(
            rx.el.a(
                item["irn"],
                href=f"/invoices/{item['irn']}",
                class_name="text-sm font-mono text-blue-600 hover:underline focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1 rounded-sm",
            ),
            class_name="px-4 py-3",
        ),
        rx.el.td(
            item["customer_name"],
            class_name="px-4 py-3 text-sm text-gray-900 max-w-[16rem] truncate",
        ),
        rx.el.td(
            item["issue_date"],
            class_name="px-4 py-3 text-sm text-gray-700 whitespace-nowrap",
        ),
        rx.el.td(
            f"{item['currency']} {item['payable_amount']:.2f}",
            class_name="px-4 py-3 text-sm font-medium text-gray-900 text-right whitespace-nowrap",
        ),
        rx.el.td(_status_badge(item["payment_status"]), class_name="px-4 py-3"),
        rx.el.td(_transmit_badge(item["transmitted"]), class_name="px-4 py-3"),
        rx.el.td(
            rx.el.div(
                rx.cond(
                    ~item["transmitted"],
                    rx.el.button(
                        rx.cond(
                            is_transmitting,
                            rx.icon(
                                "loader-circle",
                                class_name="h-4 w-4 animate-spin",
                            ),
                            rx.icon("send", class_name="h-4 w-4"),
                        ),
                        rx.el.span("Transmit", class_name="sr-only"),
                        on_click=InvoiceLogState.transmit_invoice(
                            item["irn"]
                        ).throttle(1000),
                        disabled=is_transmitting,
                        aria_label=f"Transmit invoice {item['irn']}",
                        class_name="p-2 rounded-md text-gray-500 hover:bg-blue-50 hover:text-blue-600 disabled:opacity-50 disabled:cursor-wait focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors",
                        title="Transmit",
                    ),
                    rx.fragment(),
                ),
                rx.el.button(
                    rx.icon("circle-dollar-sign", class_name="h-4 w-4"),
                    rx.el.span("Update status", class_name="sr-only"),
                    on_click=lambda: InvoiceLogState.open_status_modal(
                        item["irn"], item["payment_status"]
                    ),
                    aria_label=f"Update payment status for {item['irn']}",
                    class_name="p-2 rounded-md text-gray-500 hover:bg-gray-100 hover:text-blue-600 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors",
                    title="Update status",
                ),
                rx.el.a(
                    rx.icon("eye", class_name="h-4 w-4"),
                    rx.el.span("View", class_name="sr-only"),
                    href=f"/invoices/{item['irn']}",
                    aria_label=f"View invoice {item['irn']}",
                    class_name="p-2 rounded-md text-gray-500 hover:bg-gray-100 hover:text-blue-600 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors",
                    title="View",
                ),
                class_name="flex items-center justify-end gap-1",
            ),
            class_name="px-4 py-3",
        ),
        class_name="border-b border-gray-100 hover:bg-gray-50 transition-colors",
    )


def _skeleton_row() -> rx.Component:
    return rx.el.tr(
        rx.el.td(
            rx.el.div(class_name="h-4 w-32 bg-gray-200 rounded animate-pulse"),
            class_name="px-4 py-3",
        ),
        rx.el.td(
            rx.el.div(class_name="h-4 w-40 bg-gray-200 rounded animate-pulse"),
            class_name="px-4 py-3",
        ),
        rx.el.td(
            rx.el.div(class_name="h-4 w-20 bg-gray-200 rounded animate-pulse"),
            class_name="px-4 py-3",
        ),
        rx.el.td(
            rx.el.div(
                class_name="h-4 w-24 bg-gray-200 rounded animate-pulse ml-auto"
            ),
            class_name="px-4 py-3",
        ),
        rx.el.td(
            rx.el.div(
                class_name="h-5 w-16 bg-gray-200 rounded-full animate-pulse"
            ),
            class_name="px-4 py-3",
        ),
        rx.el.td(
            rx.el.div(
                class_name="h-5 w-20 bg-gray-200 rounded-full animate-pulse"
            ),
            class_name="px-4 py-3",
        ),
        rx.el.td(
            rx.el.div(
                class_name="h-4 w-16 bg-gray-200 rounded animate-pulse ml-auto"
            ),
            class_name="px-4 py-3",
        ),
        class_name="border-b border-gray-100",
    )


def invoices_content() -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.el.div(
                rx.el.h1(
                    "Invoices", class_name="text-2xl font-bold text-gray-900"
                ),
                rx.el.p(
                    f"{InvoiceLogState.total} invoices in your log",
                    class_name="text-sm text-gray-500 mt-1",
                ),
            ),
            rx.el.a(
                rx.icon("plus", class_name="h-4 w-4"),
                rx.el.span("New invoice"),
                href="/invoices/new",
                class_name="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700",
            ),
            class_name="flex items-center justify-between mb-6",
        ),
        _messages(),
        rx.el.div(
            rx.el.div(
                rx.icon(
                    "search",
                    class_name="h-4 w-4 text-gray-400 absolute left-3 top-1/2 -translate-y-1/2",
                ),
                rx.el.input(
                    placeholder="Search by IRN or customer name…",
                    default_value=InvoiceLogState.search_query,
                    on_change=InvoiceLogState.set_search.debounce(400),
                    class_name="w-full pl-9 pr-3 py-2 bg-white text-gray-900 border border-gray-300 rounded-md text-sm focus:outline-hidden focus:ring-2 focus:ring-blue-500",
                ),
                class_name="relative flex-1 max-w-md",
            ),
            rx.el.button(
                rx.icon(
                    rx.cond(
                        InvoiceLogState.order == "desc",
                        "arrow-down",
                        "arrow-up",
                    ),
                    class_name="h-4 w-4",
                ),
                rx.el.span(
                    rx.cond(
                        InvoiceLogState.order == "desc", "Newest", "Oldest"
                    ),
                    class_name="text-sm",
                ),
                on_click=InvoiceLogState.toggle_order,
                class_name="flex items-center gap-2 px-3 py-2 bg-white border border-gray-300 text-gray-700 rounded-md hover:bg-gray-50",
            ),
            class_name="flex items-center gap-3 mb-4",
        ),
        rx.cond(
            InvoiceLogState.loading & (InvoiceLogState.items.length() == 0),
            rx.el.div(
                rx.el.table(
                    rx.el.thead(
                        rx.el.tr(
                            rx.el.th(
                                "IRN",
                                class_name="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider",
                            ),
                            rx.el.th(
                                "Customer",
                                class_name="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider",
                            ),
                            rx.el.th(
                                "Date",
                                class_name="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider",
                            ),
                            rx.el.th(
                                "Amount",
                                class_name="px-4 py-3 text-right text-xs font-semibold text-gray-500 uppercase tracking-wider",
                            ),
                            rx.el.th(
                                "Status",
                                class_name="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider",
                            ),
                            rx.el.th(
                                "Transmit",
                                class_name="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider",
                            ),
                            rx.el.th("", class_name="px-4 py-3"),
                            class_name="border-b border-gray-200 bg-gray-50",
                        ),
                    ),
                    rx.el.tbody(
                        _skeleton_row(),
                        _skeleton_row(),
                        _skeleton_row(),
                        _skeleton_row(),
                        _skeleton_row(),
                    ),
                    class_name="table-auto w-full",
                ),
                class_name="overflow-hidden rounded-xl border border-gray-200 bg-white",
            ),
            rx.cond(
                InvoiceLogState.items.length() == 0,
                rx.el.div(
                    rx.icon(
                        "receipt",
                        class_name="h-10 w-10 text-gray-300 mx-auto mb-3",
                    ),
                    rx.el.p(
                        "No invoices yet",
                        class_name="text-base font-semibold text-gray-900",
                    ),
                    rx.el.p(
                        "Create your first invoice to get started.",
                        class_name="text-sm text-gray-500 mt-1",
                    ),
                    rx.el.a(
                        rx.icon("plus", class_name="h-4 w-4"),
                        rx.el.span("New invoice"),
                        href="/invoices/new",
                        class_name="mt-4 inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 transition-all active:scale-[0.98]",
                    ),
                    class_name="text-center py-16 bg-white rounded-xl border border-gray-200",
                ),
                rx.el.div(
                    rx.el.table(
                        rx.el.thead(
                            rx.el.tr(
                                rx.el.th(
                                    "IRN",
                                    class_name="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider",
                                ),
                                rx.el.th(
                                    "Customer",
                                    class_name="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider",
                                ),
                                rx.el.th(
                                    "Date",
                                    class_name="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider",
                                ),
                                rx.el.th(
                                    "Amount",
                                    class_name="px-4 py-3 text-right text-xs font-semibold text-gray-500 uppercase tracking-wider",
                                ),
                                rx.el.th(
                                    "Status",
                                    class_name="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider",
                                ),
                                rx.el.th(
                                    "Transmit",
                                    class_name="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider",
                                ),
                                rx.el.th("", class_name="px-4 py-3"),
                                class_name="border-b border-gray-200 bg-gray-50",
                            ),
                        ),
                        rx.el.tbody(
                            rx.foreach(InvoiceLogState.items, _invoice_row),
                        ),
                        class_name="table-auto w-full",
                    ),
                    class_name="overflow-hidden rounded-xl border border-gray-200 bg-white",
                ),
            ),
        ),
        rx.cond(
            InvoiceLogState.show_status_modal, _status_modal(), rx.fragment()
        ),
    )


def invoice_detail_content() -> rx.Component:
    return rx.el.div(
        rx.el.a(
            rx.icon("arrow-left", class_name="h-4 w-4"),
            rx.el.span("Back to invoices"),
            href="/invoices",
            class_name="inline-flex items-center gap-2 text-sm text-gray-600 hover:text-blue-600 mb-4",
        ),
        _messages(),
        rx.cond(
            InvoiceLogState.detail_loading,
            rx.el.div(
                rx.icon(
                    "loader-circle",
                    class_name="h-6 w-6 text-blue-600 animate-spin",
                ),
                class_name="flex items-center justify-center py-16",
            ),
            rx.cond(
                InvoiceLogState.selected["irn"] == "",
                rx.el.div(
                    rx.icon(
                        "file-question",
                        class_name="h-10 w-10 text-gray-300 mx-auto mb-3",
                    ),
                    rx.el.p(
                        "Invoice not found",
                        class_name="text-base font-semibold text-gray-900",
                    ),
                    class_name="text-center py-16 bg-white rounded-xl border border-gray-200",
                ),
                rx.el.div(
                    rx.el.div(
                        rx.el.div(
                            rx.el.h1(
                                InvoiceLogState.selected["irn"],
                                class_name="text-2xl font-bold text-gray-900 font-mono",
                            ),
                            rx.el.div(
                                _status_badge(
                                    InvoiceLogState.selected["payment_status"]
                                ),
                                _transmit_badge(
                                    InvoiceLogState.selected["transmitted"]
                                ),
                                class_name="flex items-center gap-2 mt-2",
                            ),
                        ),
                        rx.el.div(
                            rx.cond(
                                ~InvoiceLogState.selected["transmitted"],
                                rx.el.button(
                                    rx.icon("send", class_name="h-4 w-4"),
                                    rx.el.span("Transmit"),
                                    on_click=lambda: (
                                        InvoiceLogState.transmit_invoice(
                                            InvoiceLogState.selected["irn"]
                                        )
                                    ),
                                    class_name="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700",
                                ),
                                rx.fragment(),
                            ),
                            rx.el.button(
                                rx.icon(
                                    "circle-dollar-sign", class_name="h-4 w-4"
                                ),
                                rx.el.span("Update status"),
                                on_click=lambda: (
                                    InvoiceLogState.open_status_modal(
                                        InvoiceLogState.selected["irn"],
                                        InvoiceLogState.selected[
                                            "payment_status"
                                        ],
                                    )
                                ),
                                class_name="flex items-center gap-2 px-4 py-2 bg-white border border-gray-300 text-gray-700 text-sm font-medium rounded-md hover:bg-gray-50",
                            ),
                            class_name="flex items-center gap-2",
                        ),
                        class_name="flex items-start justify-between mb-6",
                    ),
                    rx.el.div(
                        rx.el.div(
                            rx.el.div(
                                rx.el.div(
                                    rx.el.h3(
                                        "Invoice details",
                                        class_name="text-base font-semibold text-gray-900 mb-4",
                                    ),
                                    rx.el.div(
                                        rx.el.div(
                                            rx.el.p(
                                                "Customer",
                                                class_name="text-xs uppercase text-gray-500 font-semibold tracking-wider",
                                            ),
                                            rx.el.p(
                                                InvoiceLogState.selected[
                                                    "customer_name"
                                                ],
                                                class_name="text-sm text-gray-900 mt-1",
                                            ),
                                        ),
                                        rx.el.div(
                                            rx.el.p(
                                                "Issue date",
                                                class_name="text-xs uppercase text-gray-500 font-semibold tracking-wider",
                                            ),
                                            rx.el.p(
                                                InvoiceLogState.selected[
                                                    "issue_date"
                                                ],
                                                class_name="text-sm text-gray-900 mt-1",
                                            ),
                                        ),
                                        rx.el.div(
                                            rx.el.p(
                                                "Currency",
                                                class_name="text-xs uppercase text-gray-500 font-semibold tracking-wider",
                                            ),
                                            rx.el.p(
                                                InvoiceLogState.selected[
                                                    "currency"
                                                ],
                                                class_name="text-sm text-gray-900 mt-1",
                                            ),
                                        ),
                                        rx.el.div(
                                            rx.el.p(
                                                "Payable amount",
                                                class_name="text-xs uppercase text-gray-500 font-semibold tracking-wider",
                                            ),
                                            rx.el.p(
                                                f"{InvoiceLogState.selected['currency']} {InvoiceLogState.selected['payable_amount']:.2f}",
                                                class_name="text-base font-semibold text-gray-900 mt-1",
                                            ),
                                        ),
                                        class_name="grid grid-cols-2 gap-4",
                                    ),
                                    class_name="bg-white border border-gray-200 rounded-xl p-6",
                                ),
                                rx.cond(
                                    InvoiceLogState.firs_invoice.length() > 0,
                                    _authoritative_section(),
                                    rx.fragment(),
                                ),
                                class_name="md:col-span-2 flex flex-col gap-4",
                            ),
                            rx.el.div(
                                rx.el.h3(
                                    "QR code",
                                    class_name="text-base font-semibold text-gray-900 mb-4",
                                ),
                                rx.el.div(
                                    rx.cond(
                                        InvoiceLogState.qr_b64 != "",
                                        rx.el.div(
                                            rx.el.img(
                                                src=f"data:image/png;base64,{InvoiceLogState.qr_b64}",
                                                class_name="w-48 h-48 mx-auto",
                                            ),
                                            rx.el.p(
                                                "Scan to verify invoice",
                                                class_name="text-xs text-gray-500 text-center mt-2",
                                            ),
                                        ),
                                        rx.el.div(
                                            rx.icon(
                                                "qr-code",
                                                class_name="h-12 w-12 text-gray-300 mx-auto",
                                            ),
                                            rx.el.p(
                                                "QR not available",
                                                class_name="text-xs text-gray-500 text-center mt-2",
                                            ),
                                            class_name="py-8",
                                        ),
                                    ),
                                    class_name="bg-white border border-gray-200 rounded-xl p-6",
                                ),
                                class_name="grid grid-cols-1 md:grid-cols-3 gap-4",
                            ),
                        ),
                    ),
                ),
            ),
        ),
        rx.cond(
            InvoiceLogState.show_status_modal, _status_modal(), rx.fragment()
        ),
    )


def invoices_page() -> rx.Component:
    return app_shell(invoices_content())


def invoice_detail_page() -> rx.Component:
    return app_shell(invoice_detail_content())