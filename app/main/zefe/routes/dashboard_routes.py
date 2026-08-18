from __future__ import annotations

import asyncio
import logging

from fasthtml.common import A, Div, H1, P, Span
from starlette.requests import Request

from deps import (
    current_business_id,
    current_jwt,
    current_username,
    get_session_id,
    require_session,
)
from services import api_client
from ui.icons import icon
from ui.layout import app_shell

logger = logging.getLogger(__name__)


def _stat_card(label: str, value: str, icon_name: str, accent: str) -> Div:
    return Div(
        Div(
            icon(icon_name, cls=f"h-5 w-5 {accent}"),
            cls="h-10 w-10 rounded-lg bg-slate-50 flex items-center justify-center mb-3",
        ),
        P(
            label,
            cls="text-xs uppercase text-slate-500 font-semibold tracking-wider",
        ),
        P(value, cls="text-2xl font-bold text-slate-900 mt-1"),
        cls="bg-white border border-slate-200 rounded-xl p-5 transition-shadow hover:shadow-sm",
    )


def _recent_row(item: dict) -> A:
    palette = {
        "PAID": "bg-emerald-100 text-emerald-700",
        "PENDING": "bg-amber-100 text-amber-700",
        "REJECTED": "bg-rose-100 text-rose-700",
        "PARTIAL": "bg-sky-100 text-sky-700",
    }
    status = item.get("payment_status", "PENDING")
    pill_cls = palette.get(status, "bg-slate-100 text-slate-700")
    display_status = status
    return A(
        Div(
            Div(
                P(
                    item.get("irn", ""),
                    cls="text-sm font-mono text-slate-900 truncate",
                ),
                P(
                    item.get("customer_name", ""),
                    cls="text-xs text-slate-500 truncate",
                ),
            ),
            Div(
                Span(
                    display_status,
                    cls=f"inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium {pill_cls}",
                ),
                P(
                    f"{item.get('currency', '')} {float(item.get('payable_amount', 0)):.2f}",
                    cls="text-sm font-semibold text-slate-900 mt-1",
                ),
                cls="flex flex-col items-end shrink-0",
            ),
            cls="flex items-center justify-between gap-4",
        ),
        href=f"/invoices/{item.get('irn', '')}",
        cls="block px-4 py-3 hover:bg-slate-50 border-b border-slate-100 last:border-b-0",
    )


def register_routes(rt) -> None:
    @rt("/", methods=["GET"])
    async def index(req: Request):
        redirect = require_session(req)
        if redirect:
            return redirect

        username = current_username(req) or "there"
        business_id = current_business_id(req) or ""
        jwt = current_jwt(req)
        sid = get_session_id(req)

        stats_data: dict = {}
        items: list[dict] = []
        customer_total = 0
        item_total = 0
        try:
            stats_task = api_client.get_invoice_stats(jwt, session_id=sid)
            log_task = api_client.get_invoice_log(jwt, limit=8, session_id=sid)
            cust_task = api_client.list_customers(jwt, session_id=sid, limit=1)
            item_task = api_client.list_items(
                jwt, session_id=sid, active=True, limit=1
            )
            stats_res, log_res, cust_res, item_res = await asyncio.gather(
                stats_task,
                log_task,
                cust_task,
                item_task,
                return_exceptions=True,
            )
            if not isinstance(stats_res, Exception):
                stats_data = stats_res or {}
            if not isinstance(log_res, Exception):
                items = (log_res or {}).get("items", [])
            if not isinstance(cust_res, Exception):
                customer_total = (cust_res or {}).get("total", 0)
            if not isinstance(item_res, Exception):
                item_total = (item_res or {}).get("total", 0)
        except Exception:
            logger.exception("dashboard load failed")

        welcome = Div(
            Div(
                H1(
                    f"Welcome, {username}",
                    cls="text-2xl font-bold text-slate-900 tracking-tight",
                ),
                P(
                    "Your Zetamind e-invoicing workspace.",
                    cls="text-sm text-slate-500 mt-1",
                ),
            ),
            A(
                icon("plus", cls="h-4 w-4"),
                Span("New invoice"),
                href="/invoices/new",
                cls="inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700 shadow-sm shrink-0",
            ),
            cls="flex items-start justify-between gap-4 mb-6",
        )

        stats = Div(
            _stat_card(
                "Total invoices",
                int(stats_data.get("total", 0) or 0),
                "receipt",
                "text-indigo-600",
            ),
            _stat_card(
                "Revenue (NGN)",
                f"{float(stats_data.get('revenue', 0) or 0):.2f}",
                "trending-up",
                "text-emerald-600",
            ),
            _stat_card(
                "Pending",
                int(stats_data.get("pending", 0) or 0),
                "clock",
                "text-amber-600",
            ),
            _stat_card(
                "Customers",
                int(customer_total or 0),
                "users",
                "text-sky-600",
            ),
            _stat_card(
                "Items",
                int(item_total or 0),
                "package",
                "text-indigo-600",
            ),
            cls="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4 mb-6",
        )

        recent_card = Div(
            Div(
                P(
                    "Recent invoices",
                    cls="text-base font-semibold text-slate-900",
                ),
                A(
                    "View all",
                    href="/invoices",
                    cls="text-sm text-indigo-600 hover:underline font-medium",
                ),
                cls="flex items-center justify-between p-4 border-b border-slate-200",
            ),
            Div(
                *[_recent_row(it) for it in items[:6]],
            )
            if items
            else Div(
                icon(
                    "receipt",
                    cls="h-8 w-8 text-slate-300 mx-auto mb-2",
                ),
                P(
                    "No invoices yet",
                    cls="text-sm text-slate-500",
                ),
                cls="text-center py-12",
            ),
            cls="bg-white border border-slate-200 rounded-xl overflow-hidden",
        )

        return app_shell(
            "Dashboard",
            welcome,
            stats,
            recent_card,
            active_nav="dashboard",
            username=username,
            business_id=business_id,
        )
