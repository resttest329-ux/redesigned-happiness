from __future__ import annotations

from typing import Optional

from fasthtml.common import (
    A,
    Aside,
    Body,
    Div,
    Head,
    Header,
    Html,
    Img,
    Link,
    Main,
    Meta,
    Nav,
    P,
    Script,
    Span,
    Title,
)

from ui.icons import icon


_NAV_ITEMS = [
    ("Dashboard", "/", "layout-dashboard", "dashboard"),
    ("Customers", "/customers", "users", "customers"),
    ("Items & Services", "/items", "file-text", "items"),
    ("Invoices", "/invoices", "receipt", "invoices"),
    ("Settings", "/settings", "settings", "settings"),
]


def _nav_link(label: str, href: str, icon_name: str, *, active: bool) -> A:
    base = (
        "flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium "
        "transition-colors"
    )
    state = (
        "bg-indigo-50 text-indigo-700"
        if active
        else "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
    )
    return A(
        icon(icon_name, cls="h-4 w-4"),
        Span(label),
        href=href,
        cls=f"{base} {state}",
    )


def sidebar(
    active_nav: Optional[str],
    username: Optional[str],
    business_id: Optional[str],
) -> Aside:
    initial = (username or "?")[:1].upper()
    return Aside(
        Div(
            Div(
                Img(
                    src="/static/img/complete_colored.svg",
                    alt="Zetamind",
                    cls="h-8 w-auto",
                ),
                cls="flex items-center px-5 h-16 border-b border-slate-200",
            ),
            Nav(
                *[
                    _nav_link(
                        label, href, icon_name, active=(active_nav == key)
                    )
                    for label, href, icon_name, key in _NAV_ITEMS
                ],
                cls="flex flex-col gap-1 p-3 flex-1 overflow-auto",
            ),
            Div(
                Div(
                    Div(
                        initial,
                        cls=(
                            "h-9 w-9 rounded-full bg-indigo-600 text-white "
                            "flex items-center justify-center text-xs font-semibold "
                            "shrink-0"
                        ),
                    ),
                    Div(
                        P(
                            username or "Not signed in",
                            cls="text-sm font-semibold text-slate-900 truncate",
                        ),
                        P(
                            business_id or "—",
                            cls="text-xs text-slate-500 truncate font-mono",
                        ),
                        cls="min-w-0",
                    ),
                    cls="flex items-center gap-2.5 min-w-0",
                ),
                A(
                    icon("log-out", cls="h-4 w-4"),
                    href="/logout",
                    title="Sign out",
                    cls=(
                        "p-2 rounded-lg text-slate-500 hover:bg-slate-100 "
                        "hover:text-rose-600 transition-colors shrink-0"
                    ),
                ),
                cls="flex items-center justify-between p-4 border-t border-slate-200",
            ),
            cls="flex flex-col h-full",
        ),
        cls=(
            "hidden md:flex flex-col w-64 h-screen bg-white border-r "
            "border-slate-200 shrink-0 sticky top-0 z-10"
        ),
    )


def mobile_header() -> Header:
    return Header(
        Div(
            Img(
                src="/static/img/complete_colored.svg",
                alt="Zetamind",
                cls="h-7 w-auto",
            ),
            A(
                icon("log-out", cls="h-4 w-4"),
                href="/logout",
                cls="p-2 rounded-lg text-slate-600 hover:bg-slate-100",
            ),
            cls="flex items-center justify-between px-4 h-14",
        ),
        cls="md:hidden bg-white border-b border-slate-200 sticky top-0 z-10",
    )


def page_head(page_title: str) -> Head:
    return Head(
        Meta(charset="utf-8"),
        Meta(name="viewport", content="width=device-width,initial-scale=1"),
        Title(f"{page_title} · Zetamind"),
        Link(
            rel="icon", type="image/svg+xml", href="/static/img/icon_purple.svg"
        ),
        Link(rel="shortcut icon", href="/static/img/icon_purple.svg"),
        Link(rel="apple-touch-icon", href="/static/img/icon_purple.svg"),
        Link(
            rel="preconnect",
            href="https://fonts.googleapis.com",
        ),
        Link(
            rel="preconnect",
            href="https://fonts.gstatic.com",
            crossorigin="",
        ),
        Link(
            href=(
                "https://fonts.googleapis.com/css2?"
                "family=Inter:wght@400;500;600;700&"
                "family=Plus+Jakarta+Sans:wght@600;700;800&display=swap"
            ),
            rel="stylesheet",
        ),
        Script(src="https://cdn.tailwindcss.com"),
        Script(src="https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js"),
        Link(rel="stylesheet", href="/static/css/app.css"),
    )


def auth_layout(page_title: str, *content) -> Html:
    return Html(
        page_head(page_title),
        Body(
            Main(*content, cls="font-['Inter']"),
            cls="font-['Inter'] text-slate-900 antialiased bg-slate-50",
        ),
    )


def app_shell(
    page_title: str,
    *content,
    active_nav: Optional[str] = None,
    username: Optional[str] = None,
    business_id: Optional[str] = None,
    error: Optional[str] = None,
) -> Html:
    body_children = [
        sidebar(active_nav, username, business_id),
        Div(
            mobile_header(),
            Main(
                Div(
                    *content,
                    cls="max-w-7xl mx-auto p-6 md:p-8",
                ),
                cls="flex-1",
            ),
            cls="flex-1 flex flex-col min-w-0 min-h-screen",
        ),
    ]
    return Html(
        page_head(page_title),
        Body(
            Div(*body_children, cls="flex min-h-screen bg-slate-50"),
            cls="font-['Inter'] text-slate-900 antialiased",
        ),
    )
