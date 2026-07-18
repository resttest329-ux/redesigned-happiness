from __future__ import annotations

import logging

from fasthtml.common import (
    A,
    Button,
    Div,
    Form,
    Label,
    P,
    RedirectResponse,
    Span,
    Textarea,
)
from starlette.requests import Request

from deps import (
    current_business_id,
    current_jwt,
    current_username,
    get_session_id,
    require_session,
)
from services import api_client
from ui.components import (
    alert,
    card,
    country_state_fields,
    primary_button,
    section_header,
    text_field,
)
from ui.icons import icon
from ui.layout import app_shell

logger = logging.getLogger(__name__)


PROFILE_FIELDS = [
    ("party_name", "Company name", "Acme Ltd"),
    ("tin", "TIN", "12345678-0001"),
    ("telephone", "Telephone", "+234..."),
    ("street_name", "Street", "21 Main Street"),
    ("city_name", "City", "Lagos"),
    ("postal_zone", "Postal zone", "100001"),
    ("lga", "LGA", "Ikeja"),
]


async def _load_profile_lookups(jwt: str, sid: str) -> tuple[list, list]:
    countries, states = [], []
    try:
        c = await api_client.get_countries(jwt, session_id=sid)
        if isinstance(c, list):
            countries = c
    except Exception:
        logger.exception("get_countries failed for profile")
    try:
        s = await api_client.get_state_codes(jwt, session_id=sid)
        if isinstance(s, list):
            states = s
    except Exception:
        logger.exception("get_state_codes failed for profile")
    return countries, states


def _settings_tabs(active: str) -> Div:
    tabs = [
        ("profile", "Profile", "user-plus"),
        ("credentials", "FIRS Credentials", "check-circle"),
        ("secret", "Signing Secret", "settings"),
    ]
    items = []
    for key, label, icon_name in tabs:
        is_active = key == active
        cls = (
            "flex items-center gap-2 px-4 py-2.5 border-b-2 border-indigo-600 text-indigo-700 font-semibold text-sm"
            if is_active
            else "flex items-center gap-2 px-4 py-2.5 border-b-2 border-transparent text-slate-600 hover:text-slate-900 text-sm font-medium"
        )
        items.append(
            A(
                icon(icon_name, cls="h-4 w-4"),
                Span(label),
                href=f"/settings/{key}",
                cls=cls,
            )
        )
    return Div(
        *items,
        cls="flex items-center gap-1 border-b border-slate-200 mb-6 overflow-x-auto",
    )


def register_routes(rt) -> None:
    @rt("/settings", methods=["GET"])
    def settings_index(req: Request):
        redirect = require_session(req)
        if redirect:
            return redirect
        return RedirectResponse("/settings/profile", status_code=303)

    @rt("/settings/profile", methods=["GET"])
    async def profile_page(req: Request, error: str = "", success: str = ""):
        redirect = require_session(req)
        if redirect:
            return redirect
        jwt = current_jwt(req)
        sid = get_session_id(req)
        try:
            me = await api_client.get_me(jwt, session_id=sid)
        except Exception:
            logger.exception("get_me failed")
            me = {}

        countries, ng_states = await _load_profile_lookups(jwt, sid)

        banners = []
        if error:
            banners.append(alert("error", error, cls="mb-3"))
        if success:
            banners.append(alert("success", success, cls="mb-3"))

        fields = []
        for name, label, placeholder in PROFILE_FIELDS:
            if name in ("lga"):
                continue
            fields.append(
                text_field(
                    name=name,
                    label=label,
                    placeholder=placeholder,
                    value=me.get(name) or "",
                    required=False,
                )
            )
        address_block = country_state_fields(
            country_value=me.get("country") or "NG",
            state_value=me.get("state") or "",
            countries=countries,
            ng_states=ng_states,
            required=False,
            field_id_prefix="profile_addr",
            span_full=False,
        )

        form = Form(
            *banners,
            Div(
                Div(
                    Label(
                        "Username",
                        cls="block text-sm font-medium text-slate-700 mb-1.5",
                    ),
                    P(
                        me.get("username", ""),
                        cls="text-sm text-slate-900 px-3 py-2 bg-slate-50 rounded-lg border border-slate-200",
                    ),
                    cls="mb-4",
                ),
                Div(
                    Label(
                        "Email",
                        cls="block text-sm font-medium text-slate-700 mb-1.5",
                    ),
                    P(
                        me.get("email", ""),
                        cls="text-sm text-slate-900 px-3 py-2 bg-slate-50 rounded-lg border border-slate-200",
                    ),
                    cls="mb-4",
                ),
                Div(
                    Label(
                        "Business ID",
                        cls="block text-sm font-medium text-slate-700 mb-1.5",
                    ),
                    P(
                        me.get("business_id", ""),
                        cls="text-sm font-mono text-slate-900 px-3 py-2 bg-slate-50 rounded-lg border border-slate-200",
                    ),
                    cls="mb-4",
                ),
                Div(
                    Label(
                        "Service ID",
                        cls="block text-sm font-medium text-slate-700 mb-1.5",
                    ),
                    P(
                        me.get("service_id", ""),
                        cls="text-sm font-mono text-slate-900 px-3 py-2 bg-slate-50 rounded-lg border border-slate-200",
                    ),
                    cls="mb-4",
                ),
                cls="grid grid-cols-1 md:grid-cols-2 gap-x-4 mb-4",
            ),
            Div(
                *fields,
                address_block,
                text_field(
                    name="lga",
                    label="LGA",
                    placeholder="Ikeja",
                    value=me.get("lga") or "",
                    required=False,
                ),
                cls="grid grid-cols-1 md:grid-cols-2 gap-x-4",
            ),
            Div(
                primary_button("Save profile", type="submit"),
                cls="flex justify-end mt-2",
            ),
            method="post",
            action="/settings/profile",
        )

        return app_shell(
            "Profile",
            section_header(
                "Profile",
                "These details appear as the supplier on FIRS invoices.",
            ),
            _settings_tabs("profile"),
            card(form),
            active_nav="settings",
            username=current_username(req),
            business_id=current_business_id(req),
        )

    @rt("/settings/profile", methods=["POST"])
    async def profile_save(req: Request):
        redirect = require_session(req)
        if redirect:
            return redirect
        form = await req.form()
        payload = {}
        for name, _, _ in PROFILE_FIELDS:
            v = (form.get(name) or "").strip()
            payload[name] = v if v else None
        country_v = (form.get("country") or "").strip()
        state_v = (form.get("state") or "").strip()
        payload["country"] = country_v if country_v else None
        payload["state"] = state_v if state_v else None
        jwt = current_jwt(req)
        sid = get_session_id(req)
        try:
            await api_client.update_profile(jwt, payload, session_id=sid)
        except api_client.APIError as e:
            logger.exception("update_profile failed")
            detail = e.detail if isinstance(e.detail, str) else "Update failed"
            return RedirectResponse(
                f"/settings/profile?error={detail}", status_code=303
            )
        except Exception:
            logger.exception("update_profile transport error")
            return RedirectResponse(
                "/settings/profile?error=Backend+service+unavailable",
                status_code=303,
            )
        return RedirectResponse(
            "/settings/profile?success=Profile+updated", status_code=303
        )

    @rt("/settings/credentials", methods=["GET"])
    async def credentials_page(
        req: Request, error: str = "", success: str = ""
    ):
        redirect = require_session(req)
        if redirect:
            return redirect
        jwt = current_jwt(req)
        sid = get_session_id(req)
        try:
            me = await api_client.get_me(jwt, session_id=sid)
        except Exception:
            logger.exception("get_me failed")
            me = {}

        banners = []
        if error:
            banners.append(alert("error", error, cls="mb-3"))
        if success:
            banners.append(alert("success", success, cls="mb-3"))

        cert_status = (
            "Certificate configured"
            if me.get("certificate")
            else "No certificate configured"
        )
        key_status = (
            "Public key configured"
            if me.get("public_key")
            else "No public key configured"
        )
        status_kind = (
            "success"
            if me.get("certificate") and me.get("public_key")
            else "warning"
        )

        form = Form(
            *banners,
            alert(status_kind, f"{cert_status} · {key_status}", cls="mb-5"),
            Div(
                Label(
                    "Certificate",
                    cls="block text-sm font-medium text-slate-700 mb-1.5",
                ),
                Textarea(
                    me.get("certificate") or "",
                    name="certificate",
                    id="certificate_textarea",
                    rows="6",
                    placeholder="-----BEGIN CERTIFICATE-----\n...",
                    cls="w-full px-3 py-2 bg-white text-slate-900 border border-slate-300 rounded-lg text-sm font-mono focus:outline-none focus:ring-2 focus:ring-indigo-500 blur-xs select-none",
                    style="filter: blur(4px); transition: filter 0.2s;",
                ),
                Button(
                    icon("eye", cls="h-4 w-4 mr-1.5"),
                    Span("Reveal Certificate"),
                    type="button",
                    onclick="const ta = document.getElementById('certificate_textarea'); if(ta.style.filter){ta.style.filter=''; ta.classList.remove('blur-xs', 'select-none'); this.innerHTML='Hide Certificate';}else{ta.style.filter='blur(4px)'; ta.classList.add('blur-xs', 'select-none'); this.innerHTML='Reveal Certificate';}",
                    cls="mt-2 inline-flex items-center text-xs font-semibold text-indigo-600 hover:text-indigo-700",
                ),
                cls="mb-4",
            ),
            Div(
                Label(
                    "Public key",
                    cls="block text-sm font-medium text-slate-700 mb-1.5",
                ),
                Textarea(
                    me.get("public_key") or "",
                    name="public_key",
                    id="public_key_textarea",
                    rows="6",
                    placeholder="-----BEGIN PUBLIC KEY-----\n...",
                    cls="w-full px-3 py-2 bg-white text-slate-900 border border-slate-300 rounded-lg text-sm font-mono focus:outline-none focus:ring-2 focus:ring-indigo-500 blur-xs select-none",
                    style="filter: blur(4px); transition: filter 0.2s;",
                ),
                Button(
                    icon("eye", cls="h-4 w-4 mr-1.5"),
                    Span("Reveal Public Key"),
                    type="button",
                    onclick="const ta = document.getElementById('public_key_textarea'); if(ta.style.filter){ta.style.filter=''; ta.classList.remove('blur-xs', 'select-none'); this.innerHTML='Hide Public Key';}else{ta.style.filter='blur(4px)'; ta.classList.add('blur-xs', 'select-none'); this.innerHTML='Reveal Public Key';}",
                    cls="mt-2 inline-flex items-center text-xs font-semibold text-indigo-600 hover:text-indigo-700",
                ),
                cls="mb-4",
            ),
            Div(
                primary_button("Save credentials", type="submit"),
                cls="flex justify-end",
            ),
            method="post",
            action="/settings/credentials",
        )

        return app_shell(
            "FIRS Credentials",
            section_header(
                "FIRS PKI credentials",
                "Paste the certificate and public key issued to your business.",
            ),
            _settings_tabs("credentials"),
            card(form),
            active_nav="settings",
            username=current_username(req),
            business_id=current_business_id(req),
        )

    @rt("/settings/credentials", methods=["POST"])
    async def credentials_save(req: Request):
        redirect = require_session(req)
        if redirect:
            return redirect
        form = await req.form()
        cert = (form.get("certificate") or "").strip()
        pub = (form.get("public_key") or "").strip()
        if not cert and not pub:
            return RedirectResponse(
                "/settings/credentials?error=Provide+at+least+one+credential",
                status_code=303,
            )
        jwt = current_jwt(req)
        sid = get_session_id(req)
        try:
            await api_client.update_cert_key(
                jwt,
                certificate=cert or None,
                public_key=pub or None,
                session_id=sid,
            )
        except api_client.APIError as e:
            logger.exception("update_cert_key failed")
            detail = e.detail if isinstance(e.detail, str) else "Update failed"
            return RedirectResponse(
                f"/settings/credentials?error={detail}", status_code=303
            )
        except Exception:
            logger.exception("update_cert_key transport error")
            return RedirectResponse(
                "/settings/credentials?error=Backend+service+unavailable",
                status_code=303,
            )
        return RedirectResponse(
            "/settings/credentials?success=Credentials+updated",
            status_code=303,
        )

    @rt("/settings/secret", methods=["GET"])
    async def secret_page(req: Request, error: str = "", success: str = ""):
        redirect = require_session(req)
        if redirect:
            return redirect
        jwt = current_jwt(req)
        sid = get_session_id(req)
        has_secret = False
        try:
            status = await api_client.get_user_secret_status(
                jwt, session_id=sid
            )
            has_secret = status.get("has_secret", False)
        except Exception:
            logger.exception("get_user_secret_status failed")

        banners = []
        if error:
            banners.append(alert("error", error, cls="mb-3"))
        if success:
            banners.append(alert("success", success, cls="mb-3"))

        form = Form(
            *banners,
            alert(
                "success" if has_secret else "info",
                "A signing secret is configured for your account."
                if has_secret
                else "No signing secret has been set yet.",
                cls="mb-5",
            ),
            text_field(
                name="user_secret",
                label="New signing secret",
                type="password",
                placeholder="Enter signing secret",
                required=True,
                hide_asterisk=True,
            ),
            text_field(
                name="confirm_secret",
                label="Confirm secret",
                type="password",
                placeholder="Re-enter to confirm",
                required=True,
                hide_asterisk=True,
            ),
            Div(
                primary_button("Save secret", type="submit"),
                cls="flex justify-end",
            ),
            method="post",
            action="/settings/secret",
        )

        return app_shell(
            "Signing Secret",
            section_header(
                "Signing secret",
                "Set a secret that authorises this device to sign invoices.",
            ),
            _settings_tabs("secret"),
            card(form),
            active_nav="settings",
            username=current_username(req),
            business_id=current_business_id(req),
        )

    @rt("/settings/secret", methods=["POST"])
    async def secret_save(req: Request):
        redirect = require_session(req)
        if redirect:
            return redirect
        form = await req.form()
        secret = form.get("user_secret") or ""
        confirm = form.get("confirm_secret") or ""
        if not secret:
            return RedirectResponse(
                "/settings/secret?error=Secret+cannot+be+empty",
                status_code=303,
            )
        if secret != confirm:
            return RedirectResponse(
                "/settings/secret?error=Secrets+do+not+match",
                status_code=303,
            )
        jwt = current_jwt(req)
        sid = get_session_id(req)
        try:
            await api_client.update_secret(jwt, secret, session_id=sid)
        except api_client.APIError as e:
            logger.exception("update_secret failed")
            detail = e.detail if isinstance(e.detail, str) else "Update failed"
            return RedirectResponse(
                f"/settings/secret?error={detail}", status_code=303
            )
        except Exception:
            logger.exception("update_secret transport error")
            return RedirectResponse(
                "/settings/secret?error=Backend+service+unavailable",
                status_code=303,
            )
        return RedirectResponse(
            "/settings/secret?success=Signing+secret+updated",
            status_code=303,
        )