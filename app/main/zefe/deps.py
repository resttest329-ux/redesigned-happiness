from __future__ import annotations

import logging
from typing import Optional

from starlette.requests import Request
from starlette.responses import RedirectResponse

from config import SESSION_COOKIE
from services import auth_service

logger = logging.getLogger(__name__)


def get_session_id(req: Request) -> Optional[str]:
    sid = req.cookies.get(SESSION_COOKIE)
    if sid:
        return sid
    try:
        return req.session.get("session_id")
    except (AssertionError, AttributeError):
        logging.exception("Unexpected error")
        return None


def is_logged_in(req: Request) -> bool:
    sid = get_session_id(req)
    return bool(sid) and auth_service.is_authenticated(sid)


def require_session(req: Request) -> Optional[RedirectResponse]:
    if not is_logged_in(req):
        return RedirectResponse("/login", status_code=303)
    return None


def current_jwt(req: Request) -> Optional[str]:
    sid = get_session_id(req)
    return auth_service.get_jwt(sid) if sid else None


def current_business_id(req: Request) -> Optional[str]:
    sid = get_session_id(req)
    return auth_service.get_business_id(sid) if sid else None


def current_username(req: Request) -> Optional[str]:
    sid = get_session_id(req)
    return auth_service.get_username(sid) if sid else None