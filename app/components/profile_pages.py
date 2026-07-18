import reflex as rx
from app.states.auth_state import AuthState
from app.states.customer_state import CustomerState
from app.states.invoice_log_state import InvoiceLogState, InvoiceLogItem
from app.states.settings_state import SettingsState
from app.components.layout import app_shell


def _checklist_item(
    label: str, icon: str, checked: rx.Var, tab: str
) -> rx.Component:
    return rx.el.button(
        rx.icon(
            icon,
            class_name=rx.cond(
                checked, "h-4 w-4 text-green-600", "h-4 w-4 text-gray-400"
            ),
        ),
        rx.el.span(label, class_name="text-sm font-medium"),
        on_click=lambda: SettingsState.set_tab_and_redirect(tab),
        type="button",
        class_name="w-full flex items-center gap-2 px-3 py-2 hover:bg-gray-50 rounded-md text-gray-700 text-left",
    )


def _field(
    name: str,
    label: str,
    default: rx.Var,
    placeholder: str = "",
    type_: str = "text",
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
            class_name="w-full px-3 py-2 bg-white text-gray-900 border border-gray-300 rounded-md text-sm focus:outline-hidden focus:ring-2 focus:ring-blue-500 focus:border-blue-500",
        ),
        rx.cond(
            helper != "",
            rx.el.p(helper, class_name="text-xs text-gray-500 mt-1"),
            rx.fragment(),
        ),
        class_name="mb-4",
    )


def _card_header(title: str, subtitle: str, icon: str) -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.icon(icon, class_name="h-5 w-5 text-blue-600"),
            class_name="h-10 w-10 rounded-lg bg-blue-50 flex items-center justify-center",
        ),
        rx.el.div(
            rx.el.h2(title, class_name="text-lg font-semibold text-gray-900"),
            rx.el.p(subtitle, class_name="text-sm text-gray-500"),
        ),
        class_name="flex items-start gap-3 mb-6",
    )


def _page_header(title: str, subtitle: str) -> rx.Component:
    return rx.el.div(
        rx.el.h1(title, class_name="text-2xl font-bold text-gray-900"),
        rx.el.p(subtitle, class_name="text-sm text-gray-500 mt-1"),
        class_name="mb-6",
    )


def profile_content() -> rx.Component:
    return rx.el.div(
        _page_header(
            "Profile", "Manage your business identity used on FIRS invoices"
        ),
        rx.el.div(
            _card_header(
                "Account",
                "Read-only credentials provisioned to your workspace",
                "user",
            ),
            rx.el.div(
                rx.el.div(
                    rx.el.p(
                        "Username",
                        class_name="text-xs uppercase text-gray-500 font-semibold tracking-wider",
                    ),
                    rx.el.p(
                        AuthState.username,
                        class_name="text-sm text-gray-900 mt-1",
                    ),
                ),
                rx.el.div(
                    rx.el.p(
                        "Email",
                        class_name="text-xs uppercase text-gray-500 font-semibold tracking-wider",
                    ),
                    rx.el.p(
                        AuthState.email, class_name="text-sm text-gray-900 mt-1"
                    ),
                ),
                rx.el.div(
                    rx.el.p(
                        "Business ID",
                        class_name="text-xs uppercase text-gray-500 font-semibold tracking-wider",
                    ),
                    rx.el.p(
                        AuthState.business_id,
                        class_name="text-sm text-gray-900 mt-1 font-mono",
                    ),
                ),
                rx.el.div(
                    rx.el.p(
                        "Service ID",
                        class_name="text-xs uppercase text-gray-500 font-semibold tracking-wider",
                    ),
                    rx.el.p(
                        AuthState.service_id,
                        class_name="text-sm text-gray-900 mt-1 font-mono",
                    ),
                ),
                class_name="grid grid-cols-1 sm:grid-cols-2 gap-4",
            ),
            class_name="bg-white border border-gray-200 rounded-xl p-6 mb-6",
        ),
        rx.el.div(
            _card_header(
                "Company details",
                "These details appear as the supplier on FIRS invoices",
                "building-2",
            ),
            rx.el.form(
                rx.el.div(
                    _field(
                        "party_name",
                        "Company name",
                        AuthState.party_name,
                        "Acme Ltd",
                    ),
                    _field("tin", "TIN", AuthState.tin, "12345678-0001"),
                    _field(
                        "telephone", "Telephone", AuthState.telephone, "+234..."
                    ),
                    _field(
                        "street_name",
                        "Street",
                        AuthState.street_name,
                        "21 Main Street",
                        helper="Street name and number",
                    ),
                    _field(
                        "city_name",
                        "City",
                        AuthState.city_name,
                        "Lagos",
                        helper="City or town name",
                    ),
                    _field(
                        "postal_zone",
                        "Postal zone",
                        AuthState.postal_zone,
                        "100001",
                        helper="Local postal code",
                    ),
                    _field(
                        "state",
                        "State",
                        AuthState.state_field,
                        "Lagos",
                        helper="Nigerian state name (e.g. Lagos, Abia)",
                    ),
                    _field(
                        "lga",
                        "LGA",
                        AuthState.lga,
                        "Ikeja",
                        helper="Local Government Area",
                    ),
                    _field(
                        "country",
                        "Country (ISO-2)",
                        AuthState.country,
                        "NG",
                        helper="Two-letter ISO country code (e.g. NG, GB, US)",
                    ),
                    class_name="grid grid-cols-1 md:grid-cols-2 gap-x-4",
                ),
                rx.el.div(
                    rx.el.button(
                        rx.cond(
                            AuthState.loading,
                            rx.icon(
                                "loader-circle",
                                class_name="h-4 w-4 animate-spin",
                            ),
                            rx.el.span("Save changes"),
                        ),
                        type="submit",
                        disabled=AuthState.loading,
                        class_name="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-50",
                    ),
                    class_name="flex justify-end mt-2",
                ),
                on_submit=AuthState.update_profile,
                reset_on_submit=False,
            ),
            class_name="bg-white border border-gray-200 rounded-xl p-6",
        ),
    )


def credentials_content() -> rx.Component:
    return rx.el.div(
        _page_header(
            "FIRS PKI credentials",
            "Paste the certificate and public key issued to your business",
        ),
        rx.el.div(
            _card_header(
                "Certificate & Public Key",
                "Required to sign invoices for transmission to FIRS",
                "shield-check",
            ),
            rx.el.div(
                rx.el.div(
                    rx.icon("info", class_name="h-4 w-4 shrink-0 mt-0.5"),
                    rx.el.div(
                        rx.el.p(
                            rx.cond(
                                AuthState.certificate != "",
                                "Certificate configured",
                                "No certificate configured",
                            ),
                            class_name="text-sm font-medium",
                        ),
                        rx.el.p(
                            rx.cond(
                                AuthState.public_key != "",
                                "Public key configured",
                                "No public key configured",
                            ),
                            class_name="text-sm font-medium",
                        ),
                    ),
                    class_name=rx.cond(
                        (AuthState.certificate != "")
                        & (AuthState.public_key != ""),
                        "flex items-start gap-2 p-3 mb-4 bg-green-50 text-green-700 rounded-md border border-green-200",
                        "flex items-start gap-2 p-3 mb-4 bg-yellow-50 text-yellow-700 rounded-md border border-yellow-200",
                    ),
                ),
            ),
            rx.el.form(
                rx.el.div(
                    rx.el.label(
                        "Certificate",
                        class_name="block text-sm font-medium text-gray-700 mb-1.5",
                    ),
                    rx.el.textarea(
                        name="certificate",
                        placeholder="-----BEGIN CERTIFICATE-----\n...",
                        default_value=AuthState.certificate,
                        key=AuthState.certificate,
                        rows="6",
                        class_name="w-full px-3 py-2 bg-white text-gray-900 border border-gray-300 rounded-md text-sm font-mono focus:outline-hidden focus:ring-2 focus:ring-blue-500",
                    ),
                    class_name="mb-4",
                ),
                rx.el.div(
                    rx.el.label(
                        "Public key",
                        class_name="block text-sm font-medium text-gray-700 mb-1.5",
                    ),
                    rx.el.textarea(
                        name="public_key",
                        placeholder="-----BEGIN PUBLIC KEY-----\n...",
                        default_value=AuthState.public_key,
                        key=AuthState.public_key,
                        rows="6",
                        class_name="w-full px-3 py-2 bg-white text-gray-900 border border-gray-300 rounded-md text-sm font-mono focus:outline-hidden focus:ring-2 focus:ring-blue-500",
                    ),
                    class_name="mb-4",
                ),
                rx.el.div(
                    rx.el.button(
                        rx.cond(
                            AuthState.loading,
                            rx.icon(
                                "loader-circle",
                                class_name="h-4 w-4 animate-spin",
                            ),
                            rx.el.span("Save credentials"),
                        ),
                        type="submit",
                        disabled=AuthState.loading,
                        class_name="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-50",
                    ),
                    class_name="flex justify-end",
                ),
                on_submit=AuthState.update_cert_key,
                reset_on_submit=False,
            ),
            class_name="bg-white border border-gray-200 rounded-xl p-6",
        ),
    )


def secret_content() -> rx.Component:
    return rx.el.div(
        _page_header(
            "Signing secret",
            "Set a secret that authorises this device to sign invoices",
        ),
        rx.el.div(
            _card_header(
                "User signing secret",
                "You'll be asked to confirm this when signing invoices",
                "key",
            ),
            rx.el.div(
                rx.icon(
                    rx.cond(AuthState.has_secret, "circle-check", "info"),
                    class_name="h-4 w-4 shrink-0 mt-0.5",
                ),
                rx.el.span(
                    rx.cond(
                        AuthState.has_secret,
                        "A signing secret is configured for your account.",
                        "No signing secret has been set yet.",
                    ),
                    class_name="text-sm",
                ),
                class_name=rx.cond(
                    AuthState.has_secret,
                    "flex items-start gap-2 p-3 mb-4 bg-green-50 text-green-700 rounded-md border border-green-200",
                    "flex items-start gap-2 p-3 mb-4 bg-blue-50 text-blue-700 rounded-md border border-blue-200",
                ),
            ),
            rx.el.form(
                rx.el.div(
                    rx.el.label(
                        "New signing secret",
                        class_name="block text-sm font-medium text-gray-700 mb-1.5",
                    ),
                    rx.el.input(
                        name="user_secret",
                        type="password",
                        required=True,
                        placeholder="Enter signing secret",
                        class_name="w-full px-3 py-2 bg-white text-gray-900 border border-gray-300 rounded-md text-sm focus:outline-hidden focus:ring-2 focus:ring-blue-500",
                    ),
                    class_name="mb-4",
                ),
                rx.el.div(
                    rx.el.label(
                        "Confirm secret",
                        class_name="block text-sm font-medium text-gray-700 mb-1.5",
                    ),
                    rx.el.input(
                        name="confirm_secret",
                        type="password",
                        required=True,
                        placeholder="Re-enter to confirm",
                        class_name="w-full px-3 py-2 bg-white text-gray-900 border border-gray-300 rounded-md text-sm focus:outline-hidden focus:ring-2 focus:ring-blue-500",
                    ),
                    class_name="mb-4",
                ),
                rx.el.div(
                    rx.el.button(
                        rx.cond(
                            AuthState.loading,
                            rx.icon(
                                "loader-circle",
                                class_name="h-4 w-4 animate-spin",
                            ),
                            rx.el.span("Save secret"),
                        ),
                        type="submit",
                        disabled=AuthState.loading,
                        class_name="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-50",
                    ),
                    class_name="flex justify-end",
                ),
                on_submit=AuthState.update_secret,
                reset_on_submit=True,
            ),
            class_name="bg-white border border-gray-200 rounded-xl p-6",
        ),
    )


def _stat_card(
    label: str, value: rx.Var, icon: str, color: str
) -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.icon(icon, class_name=f"h-5 w-5 {color}"),
            class_name=f"h-10 w-10 rounded-lg bg-gray-50 flex items-center justify-center mb-3",
        ),
        rx.el.p(
            label,
            class_name="text-xs uppercase text-gray-500 font-semibold tracking-wider",
        ),
        rx.cond(
            InvoiceLogState.stats_loading,
            rx.el.div(
                class_name="h-8 w-24 bg-gray-200 rounded animate-pulse mt-1"
            ),
            rx.el.p(value, class_name="text-2xl font-bold text-gray-900 mt-1"),
        ),
        class_name="bg-white border border-gray-200 rounded-xl p-6 transition-shadow hover:shadow-sm",
    )


def _status_pill(status: rx.Var) -> rx.Component:
    return rx.el.span(
        status,
        class_name=rx.match(
            status,
            (
                "PAID",
                "inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-700 w-fit",
            ),
            (
                "PENDING",
                "inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-yellow-100 text-yellow-700 w-fit",
            ),
            (
                "REJECTED",
                "inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-700 w-fit",
            ),
            (
                "PARTIAL",
                "inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-700 w-fit",
            ),
            "inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-700 w-fit",
        ),
    )


def _recent_row(item: InvoiceLogItem) -> rx.Component:
    return rx.el.a(
        rx.el.div(
            rx.el.div(
                rx.el.p(
                    item["irn"],
                    class_name="text-sm font-mono text-gray-900 truncate",
                ),
                rx.el.p(
                    item["customer_name"],
                    class_name="text-xs text-gray-500 truncate",
                ),
            ),
            rx.el.div(
                _status_pill(item["payment_status"]),
                rx.el.p(
                    f"{item['currency']} {item['payable_amount']:.2f}",
                    class_name="text-sm font-semibold text-gray-900 mt-1",
                ),
                class_name="flex flex-col items-end shrink-0",
            ),
            class_name="flex items-center justify-between gap-4",
        ),
        href=f"/invoices/{item['irn']}",
        class_name="block px-4 py-3 hover:bg-gray-50 border-b border-gray-100 last:border-b-0",
    )


def dashboard_content() -> rx.Component:
    return rx.el.div(
        _page_header(
            f"Welcome, {AuthState.username}", "Your zefe e-invoicing workspace"
        ),
        rx.el.div(
            _stat_card(
                "Total invoices",
                f"{InvoiceLogState.stats['total']:.0f}",
                "receipt",
                "text-blue-600",
            ),
            _stat_card(
                "Revenue (NGN)",
                f"{InvoiceLogState.stats['revenue']:.2f}",
                "trending-up",
                "text-green-600",
            ),
            _stat_card(
                "Paid",
                f"{InvoiceLogState.stats['paid']:.0f}",
                "circle-check",
                "text-green-600",
            ),
            _stat_card(
                "Pending",
                f"{InvoiceLogState.stats['pending']:.0f}",
                "clock",
                "text-yellow-600",
            ),
            class_name="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6",
        ),
        rx.el.div(
            rx.el.div(
                rx.el.div(
                    rx.el.h3(
                        "Recent invoices",
                        class_name="text-base font-semibold text-gray-900",
                    ),
                    rx.el.a(
                        "View all",
                        href="/invoices",
                        class_name="text-sm text-blue-600 hover:underline font-medium",
                    ),
                    class_name="flex items-center justify-between p-4 border-b border-gray-200",
                ),
                rx.cond(
                    InvoiceLogState.loading
                    & (InvoiceLogState.items.length() == 0),
                    rx.el.div(
                        rx.el.div(
                            rx.el.div(
                                class_name="h-4 w-32 bg-gray-200 rounded animate-pulse"
                            ),
                            rx.el.div(
                                class_name="h-3 w-24 bg-gray-100 rounded animate-pulse mt-2"
                            ),
                            class_name="px-4 py-3 border-b border-gray-100",
                        ),
                        rx.el.div(
                            rx.el.div(
                                class_name="h-4 w-40 bg-gray-200 rounded animate-pulse"
                            ),
                            rx.el.div(
                                class_name="h-3 w-28 bg-gray-100 rounded animate-pulse mt-2"
                            ),
                            class_name="px-4 py-3 border-b border-gray-100",
                        ),
                        rx.el.div(
                            rx.el.div(
                                class_name="h-4 w-36 bg-gray-200 rounded animate-pulse"
                            ),
                            rx.el.div(
                                class_name="h-3 w-20 bg-gray-100 rounded animate-pulse mt-2"
                            ),
                            class_name="px-4 py-3",
                        ),
                    ),
                    rx.cond(
                        InvoiceLogState.items.length() == 0,
                        rx.el.div(
                            rx.icon(
                                "receipt",
                                class_name="h-8 w-8 text-gray-300 mx-auto mb-2",
                            ),
                            rx.el.p(
                                "No invoices yet",
                                class_name="text-sm text-gray-500",
                            ),
                            rx.el.a(
                                "Create your first invoice",
                                href="/invoices/new",
                                class_name="text-sm text-blue-600 hover:underline font-medium mt-2 inline-block",
                            ),
                            class_name="text-center py-12",
                        ),
                        rx.el.div(
                            rx.foreach(InvoiceLogState.items[0:6], _recent_row),
                        ),
                    ),
                ),
                class_name="bg-white border border-gray-200 rounded-xl overflow-hidden md:col-span-2",
            ),
            rx.el.div(
                rx.el.div(
                    rx.el.h3(
                        "Setup checklist",
                        class_name="text-base font-semibold text-gray-900 mb-4",
                    ),
                    rx.el.div(
                        rx.el.div(
                            _checklist_item(
                                "Complete your profile",
                                rx.cond(
                                    AuthState.party_name != "",
                                    "circle-check",
                                    "circle",
                                ),
                                AuthState.party_name != "",
                                "profile",
                            ),
                            _checklist_item(
                                "Configure FIRS PKI",
                                rx.cond(
                                    (AuthState.certificate != "")
                                    & (AuthState.public_key != ""),
                                    "circle-check",
                                    "circle",
                                ),
                                (AuthState.certificate != "")
                                & (AuthState.public_key != ""),
                                "credentials",
                            ),
                            _checklist_item(
                                "Set signing secret",
                                rx.cond(
                                    AuthState.has_secret,
                                    "circle-check",
                                    "circle",
                                ),
                                AuthState.has_secret,
                                "secret",
                            ),
                            rx.el.a(
                                rx.icon(
                                    rx.cond(
                                        CustomerState.total > 0,
                                        "circle-check",
                                        "circle",
                                    ),
                                    class_name=rx.cond(
                                        CustomerState.total > 0,
                                        "h-4 w-4 text-green-600",
                                        "h-4 w-4 text-gray-400",
                                    ),
                                ),
                                rx.el.span(
                                    rx.cond(
                                        CustomerState.total > 0,
                                        f"{CustomerState.total} customer(s) added",
                                        "Add customers",
                                    ),
                                    class_name="text-sm font-medium",
                                ),
                                href="/customers",
                                class_name="flex items-center gap-2 px-3 py-2 hover:bg-gray-50 rounded-md text-gray-700",
                            ),
                            class_name="flex flex-col gap-1",
                        ),
                        class_name="flex flex-col gap-1",
                    ),
                    class_name="bg-white border border-gray-200 rounded-xl p-5",
                ),
                class_name="bg-white border border-gray-200 rounded-xl p-5",
            ),
            class_name="grid grid-cols-1 md:grid-cols-3 gap-4",
        ),
    )


def profile_page() -> rx.Component:
    return app_shell(profile_content())


def credentials_page() -> rx.Component:
    return app_shell(credentials_content())


def secret_page() -> rx.Component:
    return app_shell(secret_content())


def dashboard_page() -> rx.Component:
    return app_shell(dashboard_content())