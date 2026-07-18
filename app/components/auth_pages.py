import reflex as rx
from app.states.auth_state import AuthState


def _alert_box() -> rx.Component:
    return rx.el.div(
        rx.cond(
            AuthState.backend_unavailable,
            rx.el.div(
                rx.icon("triangle-alert", class_name="h-4 w-4"),
                rx.el.span(
                    "Backend service unavailable. Please try again later.",
                    class_name="text-sm",
                ),
                class_name="flex items-center gap-2 p-3 mb-4 bg-red-50 text-red-700 rounded-md border border-red-200",
            ),
            rx.fragment(),
        ),
        rx.cond(
            AuthState.error_message != "",
            rx.el.div(
                rx.icon("circle-alert", class_name="h-4 w-4"),
                rx.el.span(AuthState.error_message, class_name="text-sm"),
                class_name="flex items-center gap-2 p-3 mb-4 bg-red-50 text-red-700 rounded-md border border-red-200",
            ),
            rx.fragment(),
        ),
        rx.cond(
            AuthState.success_message != "",
            rx.el.div(
                rx.icon("circle-check", class_name="h-4 w-4"),
                rx.el.span(AuthState.success_message, class_name="text-sm"),
                class_name="flex items-center gap-2 p-3 mb-4 bg-green-50 text-green-700 rounded-md border border-green-200",
            ),
            rx.fragment(),
        ),
    )


def _input(
    name: str, label: str, type_: str = "text", placeholder: str = ""
) -> rx.Component:
    return rx.el.div(
        rx.el.label(
            label, class_name="block text-sm font-medium text-gray-700 mb-1.5"
        ),
        rx.el.input(
            name=name,
            type=type_,
            placeholder=placeholder,
            required=True,
            class_name="w-full px-3 py-2 bg-white text-gray-900 border border-gray-300 rounded-md text-sm focus:outline-hidden focus:ring-2 focus:ring-blue-500 focus:border-blue-500",
        ),
        class_name="mb-4",
    )


def login_page() -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.el.div(
                rx.el.div(
                    rx.icon("file-text", class_name="h-8 w-8 text-blue-600"),
                    class_name="flex justify-center mb-4",
                ),
                rx.el.h1(
                    "Welcome back",
                    class_name="text-2xl font-bold text-gray-900 text-center",
                ),
                rx.el.p(
                    "Sign in to your zefe account",
                    class_name="text-sm text-gray-500 text-center mt-1 mb-6",
                ),
                _alert_box(),
                rx.el.form(
                    _input("email", "Email", "email", "you@company.com"),
                    _input("password", "Password", "password", "••••••••"),
                    rx.el.button(
                        rx.cond(
                            AuthState.loading,
                            rx.el.span(
                                rx.icon(
                                    "loader-circle",
                                    class_name="h-4 w-4 animate-spin inline mr-2",
                                ),
                                "Signing in...",
                            ),
                            rx.el.span("Sign in"),
                        ),
                        type="submit",
                        disabled=AuthState.loading,
                        aria_busy=AuthState.loading,
                        class_name="w-full flex items-center justify-center px-4 py-2.5 bg-blue-600 text-white font-medium text-sm rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 transition-all active:scale-[0.99]",
                    ),
                    on_submit=AuthState.login,
                    reset_on_submit=False,
                ),
                rx.el.p(
                    "Don't have an account? ",
                    rx.el.a(
                        "Sign up",
                        href="/register",
                        class_name="text-blue-600 font-medium hover:underline",
                    ),
                    class_name="text-sm text-gray-600 text-center mt-6",
                ),
                class_name="bg-white border border-gray-200 rounded-xl p-8 w-full max-w-md",
            ),
            class_name="min-h-screen flex items-center justify-center bg-gray-50 p-4",
        ),
        class_name="font-['Inter']",
    )


def register_page() -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.el.div(
                rx.el.div(
                    rx.icon("user-plus", class_name="h-8 w-8 text-blue-600"),
                    class_name="flex justify-center mb-4",
                ),
                rx.el.h1(
                    "Create your account",
                    class_name="text-2xl font-bold text-gray-900 text-center",
                ),
                rx.el.p(
                    "Set up your zefe e-invoicing workspace",
                    class_name="text-sm text-gray-500 text-center mt-1 mb-6",
                ),
                _alert_box(),
                rx.el.form(
                    _input("username", "Full name", "text", "Jane Doe"),
                    _input("email", "Email", "email", "you@company.com"),
                    _input(
                        "password", "Password", "password", "Min 8 characters"
                    ),
                    _input(
                        "business_id",
                        "Business ID",
                        "text",
                        "FIRS-issued business ID",
                    ),
                    _input(
                        "service_id", "Service ID", "text", "FIRS service ID"
                    ),
                    rx.el.button(
                        rx.cond(
                            AuthState.loading,
                            rx.el.span(
                                rx.icon(
                                    "loader-circle",
                                    class_name="h-4 w-4 animate-spin inline mr-2",
                                ),
                                "Registering...",
                            ),
                            rx.el.span("Create account"),
                        ),
                        type="submit",
                        disabled=AuthState.loading,
                        aria_busy=AuthState.loading,
                        class_name="w-full flex items-center justify-center px-4 py-2.5 bg-blue-600 text-white font-medium text-sm rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 transition-all active:scale-[0.99]",
                    ),
                    on_submit=AuthState.register,
                    reset_on_submit=False,
                ),
                rx.el.p(
                    "Already have an account? ",
                    rx.el.a(
                        "Sign in",
                        href="/login",
                        class_name="text-blue-600 font-medium hover:underline",
                    ),
                    class_name="text-sm text-gray-600 text-center mt-6",
                ),
                class_name="bg-white border border-gray-200 rounded-xl p-8 w-full max-w-md",
            ),
            class_name="min-h-screen flex items-center justify-center bg-gray-50 p-4",
        ),
        class_name="font-['Inter']",
    )