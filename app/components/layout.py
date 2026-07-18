import reflex as rx
from app.states.auth_state import AuthState


def _nav_link(label: str, icon: str, route: str) -> rx.Component:
    return rx.el.a(
        rx.icon(icon, class_name="h-4 w-4"),
        rx.el.span(label, class_name="text-sm font-medium"),
        href=route,
        class_name="flex items-center gap-3 px-3 py-2 rounded-md text-gray-700 hover:bg-gray-100 hover:text-blue-600 transition-colors",
    )


def sidebar() -> rx.Component:
    return rx.el.aside(
        rx.el.div(
            rx.el.div(
                rx.icon("file-text", class_name="h-5 w-5 text-blue-600"),
                rx.el.span(
                    "zefe",
                    class_name="text-lg font-bold text-gray-900 tracking-tight",
                ),
                class_name="flex items-center gap-2 px-4 h-16 border-b border-gray-200",
            ),
            rx.el.nav(
                _nav_link("Dashboard", "layout-dashboard", "/"),
                _nav_link("Customers", "users", "/customers"),
                _nav_link("Invoices", "receipt", "/invoices"),
                _nav_link("New Invoice", "circle_plus", "/invoices/new"),
                rx.el.div(class_name="my-3 border-t border-gray-200"),
                _nav_link("Settings", "settings", "/settings"),
                class_name="flex flex-col gap-1 p-3",
            ),
            class_name="flex flex-col h-full",
        ),
        rx.el.div(
            rx.el.div(
                rx.el.div(
                    rx.el.div(
                        AuthState.username[0:1].upper(),
                        class_name="h-8 w-8 rounded-full bg-blue-600 text-white flex items-center justify-center text-xs font-semibold",
                    ),
                    rx.el.div(
                        rx.el.p(
                            AuthState.username,
                            class_name="text-sm font-semibold text-gray-900 truncate",
                        ),
                        rx.el.p(
                            AuthState.business_id,
                            class_name="text-xs text-gray-500 truncate",
                        ),
                        class_name="flex flex-col min-w-0",
                    ),
                    class_name="flex items-center gap-2 min-w-0",
                ),
                rx.el.button(
                    rx.icon("log-out", class_name="h-4 w-4"),
                    rx.el.span("Logout", class_name="sr-only"),
                    on_click=AuthState.logout,
                    aria_label="Sign out",
                    class_name="p-2 rounded-md text-gray-500 hover:bg-gray-100 hover:text-red-600 focus:outline-none focus:ring-2 focus:ring-red-500 transition-colors",
                    title="Logout",
                ),
                class_name="flex items-center justify-between p-4 border-t border-gray-200",
            ),
        ),
        class_name="hidden md:flex flex-col w-64 h-screen bg-white border-r border-gray-200 shrink-0 sticky top-0",
    )


def header() -> rx.Component:
    return rx.el.header(
        rx.el.div(
            rx.el.div(
                rx.icon("file-text", class_name="h-5 w-5 text-blue-600"),
                rx.el.span(
                    "zefe", class_name="text-lg font-bold text-gray-900"
                ),
                class_name="flex items-center gap-2",
            ),
            rx.el.button(
                rx.icon("log-out", class_name="h-4 w-4"),
                rx.el.span("Logout", class_name="sr-only"),
                on_click=AuthState.logout,
                aria_label="Sign out",
                class_name="p-2 rounded-md text-gray-600 hover:bg-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors",
            ),
            class_name="flex items-center justify-between px-4 h-14",
        ),
        class_name="md:hidden bg-white border-b border-gray-200 sticky top-0 z-10",
    )


def banner() -> rx.Component:
    return rx.el.div(
        rx.cond(
            AuthState.backend_unavailable,
            rx.el.div(
                rx.icon("triangle-alert", class_name="h-4 w-4"),
                rx.el.span(
                    "Backend service unavailable. Some features may not work."
                ),
                class_name="flex items-center gap-2 px-4 py-2 bg-red-50 text-red-700 text-sm border-b border-red-200",
            ),
            rx.fragment(),
        ),
        rx.cond(
            AuthState.error_message != "",
            rx.el.div(
                rx.icon("circle-alert", class_name="h-4 w-4"),
                rx.el.span(AuthState.error_message),
                rx.el.button(
                    rx.icon("x", class_name="h-3 w-3"),
                    on_click=AuthState.clear_messages,
                    class_name="ml-auto p-1 rounded hover:bg-red-100",
                ),
                class_name="flex items-center gap-2 px-4 py-2 bg-red-50 text-red-700 text-sm border-b border-red-200",
            ),
            rx.fragment(),
        ),
        rx.cond(
            AuthState.success_message != "",
            rx.el.div(
                rx.icon("circle-check", class_name="h-4 w-4"),
                rx.el.span(AuthState.success_message),
                rx.el.button(
                    rx.icon("x", class_name="h-3 w-3"),
                    on_click=AuthState.clear_messages,
                    class_name="ml-auto p-1 rounded hover:bg-green-100",
                ),
                class_name="flex items-center gap-2 px-4 py-2 bg-green-50 text-green-700 text-sm border-b border-green-200",
            ),
            rx.fragment(),
        ),
    )


def app_shell(content: rx.Component) -> rx.Component:
    return rx.el.div(
        rx.cond(
            AuthState.is_authenticated,
            rx.el.div(
                sidebar(),
                rx.el.div(
                    header(),
                    banner(),
                    rx.el.main(
                        content,
                        class_name="flex-1 p-6 md:p-8 max-w-7xl w-full mx-auto",
                    ),
                    class_name="flex-1 flex flex-col min-w-0",
                ),
                class_name="flex min-h-screen bg-gray-50",
            ),
            rx.el.div(
                rx.cond(
                    AuthState.backend_unavailable,
                    rx.el.div(
                        rx.el.div(
                            rx.el.div(
                                rx.icon(
                                    "triangle-alert",
                                    class_name="h-6 w-6 text-red-600",
                                ),
                                class_name="h-12 w-12 rounded-full bg-red-100 flex items-center justify-center mb-4 mx-auto",
                            ),
                            rx.el.h2(
                                "Backend service unavailable",
                                class_name="text-lg font-semibold text-gray-900 text-center",
                            ),
                            rx.el.p(
                                "We can't reach the zefe backend right now. Check your connection or try again.",
                                class_name="text-sm text-gray-500 text-center mt-2 max-w-sm",
                            ),
                            rx.el.div(
                                rx.el.button(
                                    rx.icon(
                                        "refresh-cw",
                                        class_name="h-4 w-4",
                                    ),
                                    rx.el.span("Retry"),
                                    on_click=AuthState.check_session,
                                    class_name="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700",
                                ),
                                rx.el.a(
                                    rx.icon(
                                        "log-in",
                                        class_name="h-4 w-4",
                                    ),
                                    rx.el.span("Sign in"),
                                    href="/login",
                                    class_name="flex items-center gap-2 px-4 py-2 bg-white border border-gray-300 text-gray-700 text-sm font-medium rounded-md hover:bg-gray-50",
                                ),
                                class_name="flex items-center justify-center gap-2 mt-6",
                            ),
                            class_name="bg-white border border-gray-200 rounded-xl p-8 max-w-md w-full",
                        ),
                        class_name="min-h-screen flex items-center justify-center bg-gray-50 p-4",
                    ),
                    rx.el.div(
                        rx.el.div(
                            rx.el.div(
                                rx.el.div(
                                    rx.icon(
                                        "loader-circle",
                                        class_name="h-8 w-8 text-blue-600 animate-spin",
                                    ),
                                    class_name="flex items-center justify-center",
                                ),
                                rx.el.p(
                                    "Checking session...",
                                    class_name="text-sm text-gray-500 mt-3",
                                ),
                                class_name="flex flex-col items-center",
                            ),
                            class_name="min-h-screen flex items-center justify-center bg-gray-50",
                        ),
                    ),
                ),
            ),
        ),
        class_name="font-['Inter'] text-gray-900",
        style={
            "& .reflex-logo": {"display": "none !important"},
            "& #__next-toast": {"z-index": "9999 !important"},
        },
    )