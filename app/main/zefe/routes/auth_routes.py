from __future__ import annotations

import logging

from fasthtml.common import (
    Div,
    Form,
    P,
    RedirectResponse,
    Span,
)
from starlette.requests import Request

from config import SESSION_COOKIE, SESSION_MAX_AGE
from deps import is_logged_in
from services import api_client, auth_service
from ui.components import (
    alert,
    auth_card,
    link,
    primary_button,
    text_field,
)
from ui.layout import auth_layout

logger = logging.getLogger(__name__)


def register_routes(rt) -> None:
    @rt("/login", methods=["GET"])
    def login_get(req: Request, error: str = "", registered: str = ""):
        if is_logged_in(req):
            return RedirectResponse("/", status_code=303)

        banners = []
        if registered:
            banners.append(
                alert("success", "Account created — please sign in.")
            )
        if error:
            banners.append(alert("error", error))

        form = Form(
            *banners,
            text_field(
                name="email",
                label="Email",
                type="email",
                placeholder="you@company.com",
                required=True,
                autocomplete="email",
                hide_asterisk=True,
            ),
            text_field(
                name="password",
                label="Password",
                type="password",
                placeholder="••••••••",
                required=True,
                autocomplete="current-password",
                hide_asterisk=True,
            ),
            Div(
                primary_button(
                    "Sign in",
                    type="submit",
                    cls=(
                        "w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 "
                        "bg-indigo-600 text-white font-medium text-sm rounded-lg "
                        "hover:bg-indigo-700 focus:outline-none focus:ring-2 "
                        "focus:ring-indigo-500 focus:ring-offset-1 disabled:opacity-50 "
                        "disabled:cursor-not-allowed transition-all active:scale-[0.99]"
                    ),
                ),
                cls="mt-1",
            ),
            P(
                "Don't have an account? ",
                link("Create one", "/register"),
                cls="text-sm text-slate-600 text-center mt-6",
            ),
            method="post",
            action="/login",
            cls="flex flex-col gap-1",
        )

        return auth_layout(
            "Sign in",
            auth_card(
                "Welcome back",
                "Sign in to your Zetamind e-invoicing workspace",
                "file-text",
                form,
            ),
        )

    @rt("/login", methods=["POST"])
    async def login_post(req: Request):
        form = await req.form()
        email = (form.get("email") or "").strip().lower()
        password = form.get("password") or ""

        if not email or not password:
            return RedirectResponse(
                "/login?error=Email+and+password+are+required",
                status_code=303,
            )

        try:
            token_resp = await api_client.login(email, password)
        except api_client.APIError as e:
            logging.exception("login api error")
            detail = (
                e.detail if isinstance(e.detail, str) else "Invalid credentials"
            )
            return RedirectResponse(f"/login?error={detail}", status_code=303)
        except Exception:
            logging.exception("login transport error")
            return RedirectResponse(
                "/login?error=Backend+service+unavailable",
                status_code=303,
            )

        jwt = token_resp.get("access_token", "")
        if not jwt:
            return RedirectResponse(
                "/login?error=Invalid+token+response", status_code=303
            )

        try:
            sid = auth_service.create_session(jwt=jwt)
        except Exception:
            logging.exception("login create_session failed")
            return RedirectResponse(
                "/login?error=Could+not+create+session", status_code=303
            )

        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie(
            SESSION_COOKIE,
            sid,
            httponly=True,
            samesite="lax",
            max_age=SESSION_MAX_AGE,
            path="/",
        )
        return resp

    @rt("/register", methods=["GET"])
    def register_get(req: Request, error: str = ""):
        if is_logged_in(req):
            return RedirectResponse("/", status_code=303)
        banner = alert("error", error) if error else Span("")
        form = Form(
            banner,
            text_field(
                name="username",
                label="Full name",
                placeholder="Jane Doe",
                required=True,
            ),
            text_field(
                name="email",
                label="Email",
                type="email",
                placeholder="you@company.com",
                required=True,
            ),
            text_field(
                name="password",
                label="Password",
                type="password",
                placeholder="Min 8 characters",
                required=True,
            ),
            text_field(
                name="business_id",
                label="Business ID",
                placeholder="FIRS-issued business ID",
                required=True,
            ),
            text_field(
                name="service_id",
                label="Service ID",
                placeholder="FIRS service ID",
                required=True,
            ),
            Div(
                primary_button(
                    "Create account",
                    type="submit",
                    cls=(
                        "w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 "
                        "bg-indigo-600 text-white font-medium text-sm rounded-lg "
                        "hover:bg-indigo-700 focus:outline-none focus:ring-2 "
                        "focus:ring-indigo-500 focus:ring-offset-1 disabled:opacity-50 "
                        "disabled:cursor-not-allowed transition-all active:scale-[0.99]"
                    ),
                ),
                cls="mt-1",
            ),
            P(
                "Already have an account? ",
                link("Sign in", "/login"),
                cls="text-sm text-slate-600 text-center mt-6",
            ),
            method="post",
            action="/register",
            cls="flex flex-col gap-1",
        )
        return auth_layout(
            "Create account",
            auth_card(
                "Create your account",
                "Set up your Zetamind e-invoicing workspace",
                "user-plus",
                form,
            ),
        )

    @rt("/register", methods=["POST"])
    async def register_post(req: Request):
        form = await req.form()
        username = (form.get("username") or "").strip()
        email = (form.get("email") or "").strip().lower()
        password = form.get("password") or ""
        business_id = (form.get("business_id") or "").strip()
        service_id = (form.get("service_id") or "").strip()

        if not all([username, email, password, business_id, service_id]):
            return RedirectResponse(
                "/register?error=All+fields+are+required", status_code=303
            )
        if len(password) < 8:
            return RedirectResponse(
                "/register?error=Password+must+be+at+least+8+characters",
                status_code=303,
            )

        try:
            await api_client.register(
                username=username,
                email=email,
                password=password,
                business_id=business_id,
                service_id=service_id,
            )
        except api_client.APIError as e:
            logging.exception("register api error")
            detail = (
                e.detail if isinstance(e.detail, str) else "Registration failed"
            )
            return RedirectResponse(
                f"/register?error={detail}", status_code=303
            )
        except Exception:
            logging.exception("register transport error")
            return RedirectResponse(
                "/register?error=Backend+service+unavailable",
                status_code=303,
            )

        return RedirectResponse("/login?registered=1", status_code=303)

    @rt("/logout", methods=["GET", "POST"])
    def logout(req: Request):
        sid = req.cookies.get(SESSION_COOKIE)
        if sid:
            try:
                auth_service.clear_session(sid)
            except Exception:
                logging.exception("logout: backend session cleanup failed")
        try:
            req.session.clear()
        except (AssertionError, AttributeError, Exception):
            logging.exception("logout: starlette session clear failed")
        resp = RedirectResponse("/login", status_code=303)
        resp.delete_cookie(SESSION_COOKIE, path="/")
        return resp