import reflex as rx


class SettingsState(rx.State):
    active_tab: str = "profile"

    @rx.event
    def set_tab(self, tab: str):
        if tab in ("profile", "credentials", "secret"):
            self.active_tab = tab

    @rx.event
    def go_to_tab(self, tab: str):
        if tab in ("profile", "credentials", "secret"):
            self.active_tab = tab
        return rx.redirect("/settings")

    @rx.event
    def set_tab_and_redirect(self, tab: str):
        if tab in ("profile", "credentials", "secret"):
            self.active_tab = tab
            return rx.redirect("/settings")