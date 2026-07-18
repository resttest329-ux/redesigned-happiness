import asyncio
import logging
from typing import Optional

import httpx

from config import settings


_client: Optional[httpx.AsyncClient] = None
_client_loop: Optional[asyncio.AbstractEventLoop] = None


def _build_headers() -> dict:
    return {
        "API-KEY": settings.API_KEY,
        "API-SECRET": settings.CLIENT_SECRET,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _build_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=90.0, write=30.0, pool=15.0)
    )


def get_client() -> httpx.AsyncClient:
    global _client, _client_loop
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        logging.exception("Unexpected error")
        current_loop = None

    needs_new = (
        _client is None
        or _client.is_closed
        or (
            current_loop is not None
            and _client_loop is not None
            and _client_loop is not current_loop
        )
        or (_client_loop is not None and _client_loop.is_closed())
    )

    if needs_new:
        if _client is not None and not _client.is_closed:
            try:
                _client._transport = _client._transport
            except Exception:
                logging.exception("get_client: discarding stale client")
        _client = _build_client()
        _client_loop = current_loop
    return _client


async def close_client() -> None:
    global _client, _client_loop
    if _client is not None and not _client.is_closed:
        try:
            await _client.aclose()
        except Exception:
            logging.exception("close_client aclose failed")
    _client = None
    _client_loop = None


async def get_request(endpoint: str):
    client = get_client()
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = await client.get(settings.BASE_URL + endpoint)
            response.raise_for_status()
            return response.json()
        except (
            httpx.RequestError,
            httpx.TimeoutException,
            httpx.NetworkError,
        ):
            logging.exception("Unexpected error")
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(0.5 * (attempt + 1))
        except httpx.HTTPStatusError:
            logging.exception("Unexpected error")
            raise


async def get_request_app(endpoint: str, params: Optional[dict] = None):
    headers = _build_headers()
    client = get_client()
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = await client.get(
                settings.PASCA_BASE_URL + endpoint,
                headers=headers,
                params=params,
            )
            response.raise_for_status()
            return response.json()
        except (
            httpx.RequestError,
            httpx.TimeoutException,
            httpx.NetworkError,
        ):
            logging.exception("Unexpected error")
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(0.5 * (attempt + 1))
        except httpx.HTTPStatusError:
            logging.exception("Unexpected error")
            raise


async def post_request(endpoint: str, payload):
    headers = _build_headers()
    client = get_client()
    response = await client.post(
        url=settings.PASCA_BASE_URL + endpoint, headers=headers, json=payload
    )
    response.raise_for_status()
    return response.json()


async def patch_request(endpoint: str, payload):
    headers = _build_headers()
    client = get_client()
    response = await client.patch(
        url=settings.PASCA_BASE_URL + endpoint, headers=headers, json=payload
    )
    response.raise_for_status()
    return response.json()