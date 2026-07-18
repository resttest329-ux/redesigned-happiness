import reflex as rx
from app.states.settings_state import SettingsState
from app.components.layout import app_shell
from app.components.profile_pages import (
    profile_content,
    credentials_content,
    secret_content,
)


def _tab_button(label: str, key: str, icon: str) -> rx.Component:
    is_active = SettingsState.active_tab == key
    return rx.el.button(
        rx.icon(icon, class_name="h-4 w-4"),
        rx.el.span(label, class_name="text-sm font-medium"),
        on_click=lambda: SettingsState.set_tab(key),
        type="button",
        class_name=rx.cond(
            is_active,
            "flex items-center gap-2 px-4 py-2.5 border-b-2 border-blue-600 text-blue-700 font-semibold",
            "flex items-center gap-2 px-4 py-2.5 border-b-2 border-transparent text-gray-600 hover:text-gray-900 hover:border-gray-300",
        ),
    )


def settings_content() -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.el.h1("Settings", class_name="text-2xl font-bold text-gray-900"),
            rx.el.p(
                "Manage your profile, FIRS credentials, and signing secret",
                class_name="text-sm text-gray-500 mt-1",
            ),
            class_name="mb-6",
        ),
        rx.el.div(
            rx.el.div(
                _tab_button("Profile", "profile", "user"),
                _tab_button("FIRS Credentials", "credentials", "shield-check"),
                _tab_button("Signing Secret", "secret", "key"),
                class_name="flex items-center gap-1 border-b border-gray-200 mb-6 overflow-x-auto",
            ),
            rx.match(
                SettingsState.active_tab,
                ("profile", profile_content()),
                ("credentials", credentials_content()),
                ("secret", secret_content()),
                profile_content(),
            ),
        ),
    )


def settings_page() -> rx.Component:
    return app_shell(settings_content())