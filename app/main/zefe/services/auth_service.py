from __future__ import annotations

import contextvars
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

from config import BACKEND_URL
import endpoints

logger = logging.getLogger(__name__)

_sync_client: Optional[httpx.Client] = None
_session_cache_var: contextvars.ContextVar[Optional[dict]] = (
    contextvars.ContextVar("_zefe_session_cache", default=None)
)


def _get_request_cache() -> dict:
    cache = _session_cache_var.get()
    if cache is None:
        cache = {}
        _session_cache_var.set(cache)
    return cache


def _client() -> httpx.Client:
    global _sync_client
    if _sync_client is None or _sync_client.is_closed:
        _sync_client = httpx.Client(
            base_url=BACKEND_URL,
            timeout=httpx.Timeout(connect=3.0, read=8.0, write=5.0, pool=3.0),
        )
    return _sync_client


def shutdown() -> None:
    global _sync_client
    if _sync_client is not None and not _sync_client.is_closed:
        _sync_client.close()
    _sync_client = None


def _iso_to_dt(iso: str) -> datetime:
    if iso.endswith("Z"):
        iso = iso[:-1] + "+00:00"
    return datetime.fromisoformat(iso)


def create_session(jwt: str) -> str:
    resp = _client().post(
        endpoints.SESSIONS,
        headers={"Authorization": f"Bearer {jwt}"},
    )
    resp.raise_for_status()
    return resp.json()["session_id"]


def get_session(session_id: str) -> Optional[dict]:
    cache = _get_request_cache()
    if session_id in cache:
        return cache[session_id]
    try:
        resp = _client().get(endpoints.SESSIONS_BY_ID.format(session_id=session_id))
    except httpx.RequestError:
        logging.exception("get_session transport error")
        cache[session_id] = None
        return None
    if resp.status_code == 404:
        cache[session_id] = None
        return None
    resp.raise_for_status()
    data = resp.json()
    cache[session_id] = data
    return data


def is_authenticated(session_id: str) -> bool:
    if not session_id:
        return False
    try:
        row = get_session(session_id)
    except httpx.RequestError:
        logging.exception("is_authenticated transport error")
        return False
    if not row:
        return False
    try:
        expires = _iso_to_dt(row["expires_at"])
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return expires > datetime.now(timezone.utc)
    except (KeyError, ValueError, TypeError):
        logging.exception("Unexpected error")
        return False


def clear_session(session_id: str) -> None:
    if not session_id:
        return
    try:
        resp = _client().delete(
            endpoints.SESSIONS_BY_ID.format(session_id=session_id),
            headers=_auth_headers(session_id),
        )
        if resp.status_code not in (200, 204, 401, 403, 404):
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError:
                logging.exception(
                    "clear_session: unexpected status, ignoring (best-effort)"
                )
    except httpx.RequestError:
        logging.exception("clear_session transport error (best-effort)")
    except Exception:
        logging.exception("clear_session unexpected error (best-effort)")
    cache = _get_request_cache()
    cache.pop(session_id, None)


def get_jwt(session_id: str) -> Optional[str]:
    row = get_session(session_id)
    return row.get("jwt_token") if row else None


def get_business_id(session_id: str) -> Optional[str]:
    row = get_session(session_id)
    return row.get("business_id") if row else None


def get_user_secret(session_id: str) -> Optional[str]:
    row = get_session(session_id)
    return row.get("user_secret") if row else None


def get_username(session_id: str) -> Optional[str]:
    row = get_session(session_id)
    return row.get("username") if row else None


def update_session_token(session_id: str, new_jwt: str) -> None:
    cache = _get_request_cache()
    if session_id in cache and cache[session_id]:
        cache[session_id]["jwt_token"] = new_jwt


def _auth_headers(session_id: str) -> dict:
    cache = _get_request_cache()
    sess = cache.get(session_id)
    if not sess:
        try:
            sess = get_session(session_id)
        except Exception:
            logging.exception("_auth_headers: session lookup failed")
            sess = None
    if sess and sess.get("jwt_token"):
        return {"Authorization": f"Bearer {sess['jwt_token']}"}
    return {}


def save_user_secret(session_id: str, secret: str) -> None:
    try:
        resp = _client().patch(
            endpoints.SESSIONS_SECRET.format(session_id=session_id),
            json={"user_secret": secret},
            headers=_auth_headers(session_id),
        )
        resp.raise_for_status()
    except (httpx.RequestError, httpx.HTTPStatusError):
        logging.exception("save_user_secret best-effort failed")
        return
    cache = _get_request_cache()
    if session_id in cache and cache[session_id]:
        cache[session_id]["user_secret"] = secret


def save_wizard_json(session_id: str, wizard_json_str: str) -> None:
    try:
        resp = _client().patch(
            endpoints.SESSIONS_WIZARD.format(session_id=session_id),
            json={"wizard_json": wizard_json_str},
            headers=_auth_headers(session_id),
        )
        if resp.status_code not in (200, 204, 401, 403, 404):
            resp.raise_for_status()
    except (httpx.RequestError, httpx.HTTPStatusError):
        logging.exception("save_wizard_json best-effort failed")
    except Exception:
        logging.exception("save_wizard_json unexpected error (best-effort)")
    cache = _get_request_cache()
    if session_id in cache and cache[session_id]:
        cache[session_id]["wizard_json"] = wizard_json_str


def clear_wizard_json(session_id: str) -> None:
    try:
        resp = _client().delete(
            endpoints.SESSIONS_WIZARD.format(session_id=session_id),
            headers=_auth_headers(session_id),
        )
        if resp.status_code not in (200, 204, 401, 403, 404):
            resp.raise_for_status()
    except (httpx.RequestError, httpx.HTTPStatusError):
        logging.exception("clear_wizard_json best-effort failed")
    except Exception:
        logging.exception("clear_wizard_json unexpected error (best-effort)")
    cache = _get_request_cache()
    if session_id in cache and cache[session_id]:
        cache[session_id]["wizard_json"] = None