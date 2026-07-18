import reflex as rx
from app.states.auth_state import AuthState
from app.states.customer_state import CustomerState
from app.states.invoice_log_state import InvoiceLogState
from app.states.wizard_state import WizardState
from app.components.auth_pages import login_page, register_page
from app.components.customers import customers_page
from app.components.invoices import invoices_page, invoice_detail_page
from app.components.profile_pages import (
    profile_page,
    credentials_page,
    secret_page,
    dashboard_page,
)
from app.components.settings_pages import settings_page
from app.components.wizard import invoice_wizard_page

app = rx.App(theme=rx.theme(appearance="light"))
app.add_page(
    dashboard_page,
    route="/",
    on_load=[AuthState.check_session, InvoiceLogState.load_dashboard],
)
app.add_page(login_page, route="/login", on_load=AuthState.check_session)
app.add_page(register_page, route="/register", on_load=AuthState.check_session)
app.add_page(
    customers_page,
    route="/customers",
    on_load=[AuthState.check_session, CustomerState.load_customers],
)
app.add_page(
    invoices_page,
    route="/invoices",
    on_load=[AuthState.check_session, InvoiceLogState.load_items],
)
app.add_page(
    invoice_wizard_page,
    route="/invoices/new",
    on_load=[AuthState.check_session, WizardState.init_wizard],
)
app.add_page(
    invoice_detail_page,
    route="/invoices/[invoice_irn]",
    on_load=[AuthState.check_session, InvoiceLogState.load_detail],
)
app.add_page(settings_page, route="/settings", on_load=AuthState.check_session)
app.add_page(
    profile_page, route="/settings/profile", on_load=AuthState.check_session
)
app.add_page(
    credentials_page,
    route="/settings/credentials",
    on_load=AuthState.check_session,
)
app.add_page(
    secret_page, route="/settings/secret", on_load=AuthState.check_session
)