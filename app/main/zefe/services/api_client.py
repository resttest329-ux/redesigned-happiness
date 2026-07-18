from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional, Union

import httpx

from config import BACKEND_URL
from services import auth_service

logger = logging.getLogger(__name__)


class APIError(Exception):
    def __init__(self, status_code: int, detail: Union[str, dict, list]):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"API Error {status_code}: {detail}")


class TransportError(APIError):
    def __init__(self, detail: Any):
        super().__init__(503, str(detail))


_client: Optional[httpx.AsyncClient] = None


async def startup() -> None:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=BACKEND_URL,
            timeout=httpx.Timeout(
                connect=15.0, read=95.0, write=30.0, pool=15.0
            ),
        )
        logger.info("api_client started against %s", BACKEND_URL)


async def shutdown() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _assert_client() -> None:
    if _client is None:
        raise RuntimeError("HTTP client not initialized; call startup() first")


def _check(resp: httpx.Response) -> None:
    if not (200 <= resp.status_code < 300):
        try:
            detail = resp.json()
        except Exception:
            logging.exception("non-json error body")
            detail = resp.text
        raise APIError(resp.status_code, detail)


async def _get(
    path: str,
    token: Optional[str] = None,
    session_id: Optional[str] = None,
    **kwargs,
) -> httpx.Response:
    _assert_client()
    headers = kwargs.pop("headers", {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    for attempt in range(3):
        try:
            resp = await _client.get(path, headers=headers, **kwargs)
            _check(resp)
            return resp
        except APIError as e:
            logging.exception("Unexpected error")
            if e.status_code == 401 and session_id and attempt == 0:
                new_jwt = await refresh_token(session_id)
                auth_service.update_session_token(session_id, new_jwt)
                headers["Authorization"] = f"Bearer {new_jwt}"
                continue
            raise
        except httpx.RequestError as e:
            logging.exception("transport error during GET")
            if attempt == 2:
                raise TransportError(e)
            await asyncio.sleep(0.5 * (attempt + 1))
    raise RuntimeError("Unreachable")


async def _exec_with_refresh(
    coro_factory, token: str, session_id: Optional[str]
):
    try:
        return await coro_factory(token)
    except APIError as e:
        logging.exception("Unexpected error")
        if e.status_code == 401 and session_id:
            new_jwt = await refresh_token(session_id)
            auth_service.update_session_token(session_id, new_jwt)
            return await coro_factory(new_jwt)
        raise


async def login(username: str, password: str) -> dict:
    _assert_client()
    try:
        resp = await _client.post(
            "/auth/token",
            data={
                "username": username,
                "password": password,
                "grant_type": "password",
            },
        )
    except httpx.RequestError as e:
        logging.exception("Unexpected error")
        raise TransportError(e)
    _check(resp)
    return resp.json()


async def register(
    username: str,
    email: str,
    password: str,
    business_id: str,
    service_id: str,
    certificate: Optional[str] = None,
    public_key: Optional[str] = None,
) -> dict:
    _assert_client()
    body = {
        "username": username,
        "email": email,
        "password": password,
        "business_id": business_id,
        "service_id": service_id,
    }
    if certificate is not None:
        body["certificate"] = certificate
    if public_key is not None:
        body["public_key"] = public_key
    try:
        resp = await _client.post("/auth/register", json=body)
    except httpx.RequestError as e:
        logging.exception("Unexpected error")
        raise TransportError(e)
    _check(resp)
    return resp.json()


async def get_me(token: str, session_id: Optional[str] = None) -> dict:
    resp = await _get("/auth/me", token, session_id=session_id)
    return resp.json()


async def get_user_secret_status(
    token: str, session_id: Optional[str] = None
) -> dict:
    resp = await _get("/auth/me/secret", token, session_id=session_id)
    return resp.json()


async def refresh_token(session_id: str) -> str:
    _assert_client()
    try:
        resp = await _client.post(
            "/auth/refresh", json={"session_id": session_id}
        )
    except httpx.RequestError as e:
        logging.exception("Unexpected error")
        raise TransportError(e)
    _check(resp)
    return resp.json()["access_token"]


async def patch_session_token(session_id: str, new_jwt: str) -> None:
    _assert_client()
    try:
        resp = await _client.patch(
            f"/sessions/{session_id}/token", json={"jwt_token": new_jwt}
        )
    except httpx.RequestError as e:
        logging.exception("Unexpected error")
        raise TransportError(e)
    _check(resp)


async def _lookup_get(
    path: str, token: str, session_id: Optional[str] = None
) -> list:
    resp = await _get(path, token, session_id=session_id)
    data = resp.json()
    return data if isinstance(data, list) else []


async def get_invoice_types(
    token: str, session_id: Optional[str] = None
) -> list:
    return await _lookup_get("/lookup/types-of-invoice", token, session_id)


async def get_payment_means(
    token: str, session_id: Optional[str] = None
) -> list:
    return await _lookup_get("/lookup/payment-means", token, session_id)


async def get_currencies(token: str, session_id: Optional[str] = None) -> list:
    return await _lookup_get("/lookup/get-currency", token, session_id)


async def get_tax_categories(
    token: str, session_id: Optional[str] = None
) -> list:
    return await _lookup_get("/lookup/tax-categories", token, session_id)


async def get_state_codes(token: str, session_id: Optional[str] = None) -> list:
    return await _lookup_get("/lookup/state-codes", token, session_id)


async def get_lga_codes(token: str, session_id: Optional[str] = None) -> list:
    return await _lookup_get("/lookup/lga-codes", token, session_id)


async def get_countries(token: str, session_id: Optional[str] = None) -> list:
    return await _lookup_get("/lookup/countries", token, session_id)


async def get_units_of_measurement(
    token: str, session_id: Optional[str] = None
) -> list:
    return await _lookup_get("/lookup/units-of-measurement", token, session_id)


async def list_customers(
    token: str,
    session_id: Optional[str] = None,
    search: Optional[str] = None,
    offset: int = 0,
    limit: int = 50,
) -> dict:
    params = {"offset": offset, "limit": limit}
    if search:
        params["search"] = search
    resp = await _get("/customers", token, session_id=session_id, params=params)
    return resp.json()


async def get_invoice_stats(
    token: str, session_id: Optional[str] = None
) -> dict:
    resp = await _get("/invoice-log/stats", token, session_id=session_id)
    return resp.json()


async def get_invoice_log(
    token: str,
    limit: int = 20,
    offset: int = 0,
    session_id: Optional[str] = None,
    search: Optional[str] = None,
) -> dict:
    params = {"limit": limit, "offset": offset, "order": "desc"}
    if search:
        params["search"] = search
    resp = await _get(
        "/invoice-log", token, session_id=session_id, params=params
    )
    return resp.json()


async def get_invoice_log_by_irn(
    token: str, irn: str, session_id: Optional[str] = None
) -> Optional[dict]:
    _assert_client()
    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = await _client.get(f"/invoice-log/{irn}", headers=headers)
    except httpx.RequestError as e:
        logging.exception("Unexpected error")
        raise TransportError(e)
    if resp.status_code == 404:
        return None
    _check(resp)
    return resp.json()


async def mark_transmitted(
    token: str, irn: str, session_id: Optional[str] = None
) -> dict:
    async def _call(tok):
        _assert_client()
        try:
            r = await _client.patch(
                f"/invoice-log/{irn}/transmitted",
                headers={"Authorization": f"Bearer {tok}"},
            )
        except httpx.RequestError as e:
            logging.exception("Unexpected error")
            raise TransportError(e)
        _check(r)
        return r.json()

    return await _exec_with_refresh(_call, token, session_id)


async def update_log_status(
    token: str, irn: str, payment_status: str, session_id: Optional[str] = None
) -> dict:
    async def _call(tok):
        _assert_client()
        try:
            r = await _client.patch(
                f"/invoice-log/{irn}/status",
                json={"payment_status": payment_status},
                headers={"Authorization": f"Bearer {tok}"},
            )
        except httpx.RequestError as e:
            logging.exception("Unexpected error")
            raise TransportError(e)
        _check(r)
        return r.json()

    return await _exec_with_refresh(_call, token, session_id)


async def create_customer(
    token: str, payload: dict, session_id: Optional[str] = None
) -> dict:
    async def _call(tok):
        _assert_client()
        try:
            r = await _client.post(
                "/customers",
                json=payload,
                headers={"Authorization": f"Bearer {tok}"},
            )
        except httpx.RequestError as e:
            logging.exception("Unexpected error")
            raise TransportError(e)
        _check(r)
        return r.json()

    return await _exec_with_refresh(_call, token, session_id)


async def get_customer(
    token: str, cid: int, session_id: Optional[str] = None
) -> dict:
    resp = await _get(f"/customers/{cid}", token, session_id=session_id)
    return resp.json()


async def update_customer(
    token: str, cid: int, payload: dict, session_id: Optional[str] = None
) -> dict:
    async def _call(tok):
        _assert_client()
        try:
            r = await _client.patch(
                f"/customers/{cid}",
                json=payload,
                headers={"Authorization": f"Bearer {tok}"},
            )
        except httpx.RequestError as e:
            logging.exception("Unexpected error")
            raise TransportError(e)
        _check(r)
        return r.json()

    return await _exec_with_refresh(_call, token, session_id)


async def delete_customer(
    token: str, cid: int, session_id: Optional[str] = None
) -> None:
    async def _call(tok):
        _assert_client()
        try:
            r = await _client.delete(
                f"/customers/{cid}",
                headers={"Authorization": f"Bearer {tok}"},
            )
        except httpx.RequestError as e:
            logging.exception("Unexpected error")
            raise TransportError(e)
        _check(r)

    return await _exec_with_refresh(_call, token, session_id)


async def update_profile(
    token: str, payload: dict, session_id: Optional[str] = None
) -> dict:
    async def _call(tok):
        _assert_client()
        try:
            r = await _client.patch(
                "/auth/me/profile",
                json=payload,
                headers={"Authorization": f"Bearer {tok}"},
            )
        except httpx.RequestError as e:
            logging.exception("Unexpected error")
            raise TransportError(e)
        _check(r)
        return r.json()

    return await _exec_with_refresh(_call, token, session_id)


async def update_cert_key(
    token: str,
    certificate: Optional[str] = None,
    public_key: Optional[str] = None,
    session_id: Optional[str] = None,
) -> dict:
    async def _call(tok):
        _assert_client()
        body = {}
        if certificate is not None:
            body["certificate"] = certificate
        if public_key is not None:
            body["public_key"] = public_key
        try:
            r = await _client.patch(
                "/auth/me/cert-key",
                json=body,
                headers={"Authorization": f"Bearer {tok}"},
            )
        except httpx.RequestError as e:
            logging.exception("Unexpected error")
            raise TransportError(e)
        _check(r)
        return r.json()

    return await _exec_with_refresh(_call, token, session_id)


async def update_secret(
    token: str, secret: str, session_id: Optional[str] = None
) -> dict:
    async def _call(tok):
        _assert_client()
        try:
            r = await _client.patch(
                "/auth/me/secret",
                json={"user_secret": secret},
                headers={"Authorization": f"Bearer {tok}"},
            )
        except httpx.RequestError as e:
            logging.exception("Unexpected error")
            raise TransportError(e)
        _check(r)
        return r.json()

    return await _exec_with_refresh(_call, token, session_id)


async def get_invoice(
    token: str, irn: str, session_id: Optional[str] = None
) -> dict:
    resp = await _get(
        f"/invoice/get-invoice/{irn}", token, session_id=session_id
    )
    return resp.json()


async def get_invoice_qr(
    token: str,
    irn: str,
    amount: float,
    date: str,
    session_id: Optional[str] = None,
) -> str:
    resp = await _get(
        f"/invoice/{irn}/qr",
        token,
        session_id=session_id,
        params={"amount": amount, "date": date},
    )
    return resp.json().get("qr_b64", "")


async def transmit_invoice(
    token: str, irn: str, session_id: Optional[str] = None
) -> dict:
    resp = await _get(
        f"/invoice/transmit-invoice/{irn}", token, session_id=session_id
    )
    return resp.json() if resp.content else {}


async def update_invoice_status(
    token: str,
    irn: str,
    user_secret: str,
    payment_status: str,
    reference: str = "",
    amount: Optional[float] = None,
    payment_update_date: Optional[str] = None,
    session_id: Optional[str] = None,
) -> dict:
    async def _call(tok):
        _assert_client()
        body: dict = {"payment_status": payment_status}
        if reference:
            body["reference"] = reference
        if amount is not None:
            body["amount"] = amount
        if payment_update_date:
            body["payment_update_date"] = payment_update_date
        try:
            r = await _client.patch(
                f"/invoice/update-invoice/{irn}",
                json=body,
                headers={
                    "Authorization": f"Bearer {tok}",
                    "user-secret": user_secret,
                },
            )
        except httpx.RequestError as e:
            logging.exception("Unexpected error")
            raise TransportError(e)
        _check(r)
        return r.json()

    return await _exec_with_refresh(_call, token, session_id)


async def assemble_invoice(
    token: str, wizard: dict, session_id: Optional[str] = None
) -> dict:
    async def _call(tok):
        _assert_client()
        try:
            r = await _client.post(
                "/invoice/assemble",
                json={"wizard": wizard},
                headers={"Authorization": f"Bearer {tok}"},
            )
        except httpx.RequestError as e:
            logging.exception("assemble transport error")
            raise TransportError(e)
        _check(r)
        return r.json()

    return await _exec_with_refresh(_call, token, session_id)


async def validate_invoice(
    token: str, invoice_dict: dict, session_id: Optional[str] = None
) -> dict:
    async def _call(tok):
        _assert_client()
        try:
            r = await _client.post(
                "/invoice/validate-invoice",
                json=invoice_dict,
                headers={"Authorization": f"Bearer {tok}"},
            )
        except httpx.RequestError as e:
            logging.exception("validate transport error")
            raise TransportError(e)
        _check(r)
        return r.json() if r.content else {}

    return await _exec_with_refresh(_call, token, session_id)


async def sign_invoice(
    token: str,
    user_secret: str,
    invoice_dict: dict,
    session_id: Optional[str] = None,
) -> dict:
    async def _call(tok):
        _assert_client()
        try:
            r = await _client.post(
                "/invoice/sign-invoice",
                json=invoice_dict,
                headers={
                    "Authorization": f"Bearer {tok}",
                    "user-secret": user_secret,
                },
            )
        except httpx.RequestError as e:
            logging.exception("sign transport error")
            raise TransportError(e)
        _check(r)
        return r.json() if r.content else {}

    return await _exec_with_refresh(_call, token, session_id)


async def create_invoice_log(
    token: str, payload: dict, session_id: Optional[str] = None
) -> dict:
    async def _call(tok):
        _assert_client()
        try:
            r = await _client.post(
                "/invoice-log",
                json=payload,
                headers={"Authorization": f"Bearer {tok}"},
            )
        except httpx.RequestError as e:
            logging.exception("create_invoice_log transport error")
            raise TransportError(e)
        _check(r)
        return r.json()

    return await _exec_with_refresh(_call, token, session_id)


async def search_products(
    token: str,
    search: str,
    length: int = 8,
    session_id: Optional[str] = None,
) -> list:
    resp = await _get(
        "/lookup/products",
        token,
        session_id=session_id,
        params={"search": search, "length": length},
    )
    data = resp.json()
    return data if isinstance(data, list) else []


async def search_services(
    token: str,
    search: str,
    length: int = 8,
    session_id: Optional[str] = None,
) -> list:
    resp = await _get(
        "/lookup/services",
        token,
        session_id=session_id,
        params={"search": search, "length": length},
    )
    data = resp.json()
    return data if isinstance(data, list) else []


# ---------------------------------------------------------------------------
# Items & Services catalog
# ---------------------------------------------------------------------------


async def list_items(
    token: str,
    session_id: Optional[str] = None,
    search: Optional[str] = None,
    kind: Optional[str] = None,
    offset: int = 0,
    limit: int = 50,
) -> dict:
    params: dict = {"offset": offset, "limit": limit}
    if search:
        params["search"] = search
    if kind in ("product", "service"):
        params["kind"] = kind
    resp = await _get("/items", token, session_id=session_id, params=params)
    return resp.json()


async def get_item(
    token: str, item_id: int, session_id: Optional[str] = None
) -> dict:
    resp = await _get(f"/items/{item_id}", token, session_id=session_id)
    return resp.json()


async def create_item(
    token: str, payload: dict, session_id: Optional[str] = None
) -> dict:
    async def _call(tok):
        _assert_client()
        try:
            r = await _client.post(
                "/items",
                json=payload,
                headers={"Authorization": f"Bearer {tok}"},
            )
        except httpx.RequestError as e:
            logging.exception("create_item transport error")
            raise TransportError(e)
        _check(r)
        return r.json()

    return await _exec_with_refresh(_call, token, session_id)


async def update_item(
    token: str,
    item_id: int,
    payload: dict,
    session_id: Optional[str] = None,
) -> dict:
    async def _call(tok):
        _assert_client()
        try:
            r = await _client.patch(
                f"/items/{item_id}",
                json=payload,
                headers={"Authorization": f"Bearer {tok}"},
            )
        except httpx.RequestError as e:
            logging.exception("update_item transport error")
            raise TransportError(e)
        _check(r)
        return r.json()

    return await _exec_with_refresh(_call, token, session_id)


async def delete_item(
    token: str, item_id: int, session_id: Optional[str] = None
) -> None:
    async def _call(tok):
        _assert_client()
        try:
            r = await _client.delete(
                f"/items/{item_id}",
                headers={"Authorization": f"Bearer {tok}"},
            )
        except httpx.RequestError as e:
            logging.exception("delete_item transport error")
            raise TransportError(e)
        _check(r)

    return await _exec_with_refresh(_call, token, session_id)


async def bulk_delete_items(
    token: str, ids: list[int], session_id: Optional[str] = None
) -> dict:
    async def _call(tok):
        _assert_client()
        try:
            r = await _client.post(
                "/items/bulk-delete",
                json={"ids": ids},
                headers={"Authorization": f"Bearer {tok}"},
            )
        except httpx.RequestError as e:
            logging.exception("bulk_delete_items transport error")
            raise TransportError(e)
        _check(r)
        return r.json()

    return await _exec_with_refresh(_call, token, session_id)


async def import_items(
    token: str,
    filename: str,
    content: bytes,
    content_type: str = "application/octet-stream",
    session_id: Optional[str] = None,
) -> dict:
    async def _call(tok):
        _assert_client()
        try:
            r = await _client.post(
                "/items/import",
                files={"file": (filename, content, content_type)},
                headers={"Authorization": f"Bearer {tok}"},
                timeout=httpx.Timeout(
                    connect=15.0, read=120.0, write=60.0, pool=15.0
                ),
            )
        except httpx.RequestError as e:
            logging.exception("import_items transport error")
            raise TransportError(e)
        _check(r)
        return r.json()

    return await _exec_with_refresh(_call, token, session_id)
