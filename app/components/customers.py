import reflex as rx
from app.states.customer_state import CustomerState, Customer
from app.components.layout import app_shell


def _status_messages() -> rx.Component:
    return rx.el.div(
        rx.cond(
            CustomerState.error_message != "",
            rx.el.div(
                rx.icon("circle-alert", class_name="h-4 w-4"),
                rx.el.span(CustomerState.error_message, class_name="text-sm"),
                class_name="flex items-center gap-2 p-3 mb-4 bg-red-50 text-red-700 rounded-md border border-red-200",
            ),
            rx.fragment(),
        ),
        rx.cond(
            CustomerState.success_message != "",
            rx.el.div(
                rx.icon("circle-check", class_name="h-4 w-4"),
                rx.el.span(CustomerState.success_message, class_name="text-sm"),
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
            key=default,
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


def _customer_form() -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.el.div(
                rx.el.div(
                    rx.el.h2(
                        rx.cond(
                            CustomerState.editing_id > 0,
                            "Edit customer",
                            "New customer",
                        ),
                        class_name="text-lg font-semibold text-gray-900",
                    ),
                    rx.el.button(
                        rx.icon("x", class_name="h-4 w-4"),
                        on_click=CustomerState.close_form,
                        type="button",
                        class_name="p-1.5 rounded-md hover:bg-gray-100",
                    ),
                    class_name="flex items-center justify-between p-5 border-b border-gray-200",
                ),
                rx.el.form(
                    rx.el.div(
                        _input(
                            "party_name",
                            "Company name",
                            CustomerState.form_party_name,
                            "Acme Ltd",
                        ),
                        _input(
                            "tin",
                            "TIN",
                            CustomerState.form_tin,
                            "12345678-0001",
                            helper="FIRS format: NNNNNNNN-NNNN",
                        ),
                        _input(
                            "email",
                            "Email",
                            CustomerState.form_email,
                            "billing@acme.com",
                            "email",
                        ),
                        _input(
                            "telephone",
                            "Telephone",
                            CustomerState.form_telephone,
                            "+234...",
                        ),
                        _input(
                            "street_name",
                            "Street",
                            CustomerState.form_street_name,
                            "21 Main Street",
                        ),
                        _input(
                            "city_name",
                            "City",
                            CustomerState.form_city_name,
                            "Lagos",
                        ),
                        _input(
                            "postal_zone",
                            "Postal zone",
                            CustomerState.form_postal_zone,
                            "100001",
                        ),
                        _input(
                            "country",
                            "Country (ISO-2)",
                            CustomerState.form_country,
                            "NG",
                        ),
                        _input(
                            "state", "State", CustomerState.form_state, "Lagos"
                        ),
                        _input(
                            "lga",
                            "LGA",
                            CustomerState.form_lga,
                            "Ikeja",
                            required=False,
                        ),
                        class_name="grid grid-cols-1 md:grid-cols-2 gap-x-4 p-5",
                    ),
                    rx.el.div(
                        rx.el.button(
                            "Cancel",
                            type="button",
                            on_click=CustomerState.close_form,
                            class_name="px-4 py-2 bg-white border border-gray-300 text-gray-700 text-sm font-medium rounded-md hover:bg-gray-50 transition-all active:scale-[0.98]",
                        ),
                        rx.el.button(
                            rx.cond(
                                CustomerState.loading,
                                rx.el.span(
                                    rx.icon(
                                        "loader-circle",
                                        class_name="h-4 w-4 animate-spin inline mr-1.5",
                                    ),
                                    "Saving...",
                                ),
                                rx.el.span("Save"),
                            ),
                            type="submit",
                            disabled=CustomerState.loading,
                            class_name="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all active:scale-[0.98]",
                        ),
                        class_name="flex justify-end gap-2 p-5 border-t border-gray-200 bg-gray-50",
                    ),
                    on_submit=CustomerState.submit_form,
                    reset_on_submit=False,
                ),
                class_name="bg-white rounded-xl border border-gray-200 w-full max-w-2xl max-h-[90vh] overflow-auto",
            ),
            class_name="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4",
        ),
    )


def _delete_modal() -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.el.div(
                rx.el.div(
                    rx.icon(
                        "triangle-alert", class_name="h-6 w-6 text-red-600"
                    ),
                    class_name="h-12 w-12 rounded-full bg-red-100 flex items-center justify-center mb-4",
                ),
                rx.el.h2(
                    "Delete customer",
                    class_name="text-lg font-semibold text-gray-900",
                ),
                rx.el.p(
                    f"Are you sure you want to delete {CustomerState.delete_name}? This cannot be undone.",
                    class_name="text-sm text-gray-600 mt-2",
                ),
                class_name="p-6",
            ),
            rx.el.div(
                rx.el.button(
                    "Cancel",
                    on_click=CustomerState.close_delete,
                    disabled=CustomerState.loading,
                    class_name="px-4 py-2 bg-white border border-gray-300 text-gray-700 text-sm font-medium rounded-md hover:bg-gray-50 transition-all active:scale-[0.98]",
                ),
                rx.el.button(
                    rx.cond(
                        CustomerState.loading,
                        rx.el.span(
                            rx.icon(
                                "loader-circle",
                                class_name="h-4 w-4 animate-spin inline mr-1.5",
                            ),
                            "Deleting...",
                        ),
                        rx.el.span("Delete"),
                    ),
                    on_click=CustomerState.confirm_delete,
                    disabled=CustomerState.loading,
                    class_name="px-4 py-2 bg-red-600 text-white text-sm font-medium rounded-md hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all active:scale-[0.98]",
                ),
                class_name="flex justify-end gap-2 p-4 border-t border-gray-200 bg-gray-50",
            ),
            class_name="bg-white rounded-xl border border-gray-200 w-full max-w-md",
        ),
        class_name="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4",
    )


def _customer_row(c: Customer) -> rx.Component:
    return rx.el.tr(
        rx.el.td(
            rx.el.div(
                rx.el.div(
                    c["party_name"][0:1].upper(),
                    class_name="h-8 w-8 rounded-full bg-blue-100 text-blue-700 flex items-center justify-center text-xs font-semibold shrink-0",
                ),
                rx.el.div(
                    rx.el.p(
                        c["party_name"],
                        class_name="text-sm font-medium text-gray-900 truncate",
                    ),
                    rx.el.p(
                        c["email"],
                        class_name="text-xs text-gray-500 truncate",
                    ),
                    class_name="min-w-0",
                ),
                class_name="flex items-center gap-3 min-w-0",
            ),
            class_name="px-4 py-3 max-w-[18rem]",
        ),
        rx.el.td(
            c["tin"],
            class_name="px-4 py-3 text-sm font-mono text-gray-700 whitespace-nowrap",
        ),
        rx.el.td(
            c["telephone"],
            class_name="px-4 py-3 text-sm text-gray-700 whitespace-nowrap",
        ),
        rx.el.td(
            rx.el.span(
                f"{c['city_name']}, {c['country']}",
                class_name="text-sm text-gray-700",
            ),
            class_name="px-4 py-3",
        ),
        rx.el.td(
            rx.el.div(
                rx.el.button(
                    rx.icon("pencil", class_name="h-4 w-4"),
                    rx.el.span("Edit", class_name="sr-only"),
                    on_click=lambda: CustomerState.open_edit(c),
                    aria_label=f"Edit customer {c['party_name']}",
                    class_name="p-2 rounded-md text-gray-500 hover:bg-gray-100 hover:text-blue-600 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors",
                    title="Edit",
                ),
                rx.el.button(
                    rx.icon("trash-2", class_name="h-4 w-4"),
                    rx.el.span("Delete", class_name="sr-only"),
                    on_click=lambda: CustomerState.open_delete(c),
                    aria_label=f"Delete customer {c['party_name']}",
                    class_name="p-2 rounded-md text-gray-500 hover:bg-gray-100 hover:text-red-600 focus:outline-none focus:ring-2 focus:ring-red-500 transition-colors",
                    title="Delete",
                ),
                class_name="flex items-center justify-end gap-1",
            ),
            class_name="px-4 py-3",
        ),
        class_name="border-b border-gray-100 hover:bg-gray-50 transition-colors",
    )


def _customer_skeleton_row() -> rx.Component:
    return rx.el.tr(
        rx.el.td(
            rx.el.div(
                rx.el.div(
                    class_name="h-8 w-8 rounded-full bg-gray-200 animate-pulse"
                ),
                rx.el.div(
                    rx.el.div(
                        class_name="h-4 w-32 bg-gray-200 rounded animate-pulse"
                    ),
                    rx.el.div(
                        class_name="h-3 w-40 bg-gray-100 rounded animate-pulse mt-2"
                    ),
                ),
                class_name="flex items-center gap-3",
            ),
            class_name="px-4 py-3",
        ),
        rx.el.td(
            rx.el.div(class_name="h-4 w-28 bg-gray-200 rounded animate-pulse"),
            class_name="px-4 py-3",
        ),
        rx.el.td(
            rx.el.div(class_name="h-4 w-24 bg-gray-200 rounded animate-pulse"),
            class_name="px-4 py-3",
        ),
        rx.el.td(
            rx.el.div(class_name="h-4 w-32 bg-gray-200 rounded animate-pulse"),
            class_name="px-4 py-3",
        ),
        rx.el.td(
            rx.el.div(
                class_name="h-4 w-12 bg-gray-200 rounded animate-pulse ml-auto"
            ),
            class_name="px-4 py-3",
        ),
        class_name="border-b border-gray-100",
    )


def customers_content() -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.el.div(
                rx.el.h1(
                    "Customers", class_name="text-2xl font-bold text-gray-900"
                ),
                rx.el.p(
                    f"{CustomerState.total} customers in your workspace",
                    class_name="text-sm text-gray-500 mt-1",
                ),
            ),
            rx.el.button(
                rx.icon("plus", class_name="h-4 w-4"),
                rx.el.span("Add customer"),
                on_click=CustomerState.open_create,
                class_name="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700",
            ),
            class_name="flex items-center justify-between mb-6",
        ),
        _status_messages(),
        rx.el.div(
            rx.el.div(
                rx.icon(
                    "search",
                    class_name="h-4 w-4 text-gray-400 absolute left-3 top-1/2 -translate-y-1/2",
                ),
                rx.el.input(
                    placeholder="Search by name, TIN, or email…",
                    default_value=CustomerState.search_query,
                    on_change=CustomerState.set_search.debounce(400),
                    class_name="w-full pl-9 pr-3 py-2 bg-white text-gray-900 border border-gray-300 rounded-md text-sm focus:outline-hidden focus:ring-2 focus:ring-blue-500",
                ),
                class_name="relative max-w-md",
            ),
            class_name="mb-4",
        ),
        rx.el.div(
            rx.cond(
                CustomerState.loading & (CustomerState.customers.length() == 0),
                rx.el.div(
                    rx.el.table(
                        rx.el.thead(
                            rx.el.tr(
                                rx.el.th(
                                    "Customer",
                                    class_name="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider",
                                ),
                                rx.el.th(
                                    "TIN",
                                    class_name="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider",
                                ),
                                rx.el.th(
                                    "Phone",
                                    class_name="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider",
                                ),
                                rx.el.th(
                                    "Location",
                                    class_name="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider",
                                ),
                                rx.el.th("", class_name="px-4 py-3"),
                                class_name="border-b border-gray-200 bg-gray-50",
                            ),
                        ),
                        rx.el.tbody(
                            _customer_skeleton_row(),
                            _customer_skeleton_row(),
                            _customer_skeleton_row(),
                            _customer_skeleton_row(),
                        ),
                        class_name="table-auto w-full",
                    ),
                    class_name="overflow-hidden rounded-xl border border-gray-200 bg-white",
                ),
                rx.cond(
                    CustomerState.customers.length() == 0,
                    rx.el.div(
                        rx.icon(
                            "users",
                            class_name="h-10 w-10 text-gray-300 mx-auto mb-3",
                        ),
                        rx.el.p(
                            "No customers yet",
                            class_name="text-base font-semibold text-gray-900",
                        ),
                        rx.el.p(
                            "Add your first customer to start invoicing.",
                            class_name="text-sm text-gray-500 mt-1",
                        ),
                        rx.el.button(
                            rx.icon("plus", class_name="h-4 w-4"),
                            rx.el.span("Add customer"),
                            on_click=CustomerState.open_create,
                            class_name="mt-4 inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700",
                        ),
                        class_name="text-center py-16",
                    ),
                    rx.el.div(
                        rx.el.table(
                            rx.el.thead(
                                rx.el.tr(
                                    rx.el.th(
                                        "Customer",
                                        class_name="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider",
                                    ),
                                    rx.el.th(
                                        "TIN",
                                        class_name="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider",
                                    ),
                                    rx.el.th(
                                        "Phone",
                                        class_name="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider",
                                    ),
                                    rx.el.th(
                                        "Location",
                                        class_name="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider",
                                    ),
                                    rx.el.th("", class_name="px-4 py-3"),
                                    class_name="border-b border-gray-200 bg-gray-50",
                                ),
                            ),
                            rx.el.tbody(
                                rx.foreach(
                                    CustomerState.customers, _customer_row
                                ),
                            ),
                            class_name="table-auto w-full",
                        ),
                        class_name="overflow-hidden rounded-xl border border-gray-200 bg-white",
                    ),
                ),
            ),
        ),
        rx.cond(CustomerState.show_form, _customer_form(), rx.fragment()),
        rx.cond(
            CustomerState.show_delete_confirm, _delete_modal(), rx.fragment()
        ),
    )


def customers_page() -> rx.Component:
    return app_shell(customers_content())