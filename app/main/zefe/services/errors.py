from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def extract_api_error_detail(e: Any) -> str:
    detail = getattr(e, "detail", None)
    if detail is None:
        return str(e) if e else "Request failed"
    if isinstance(detail, str):
        return detail or "Request failed"

    if isinstance(detail, dict):
        d = detail.get("detail")
        if isinstance(d, str) and d:
            return d
        if isinstance(d, list):
            parts = []
            for item in d:
                if isinstance(item, dict):
                    msg = item.get("msg") or item.get("message") or ""
                    loc = item.get("loc") or []
                    if msg:
                        if isinstance(loc, list) and len(loc) > 1:
                            field = ".".join(str(x) for x in loc[1:])
                            parts.append(f"{field}: {msg}")
                        else:
                            parts.append(msg)
                elif isinstance(item, str):
                    parts.append(item)
            if parts:
                return "; ".join(parts)
        err_obj = detail.get("error")
        if isinstance(err_obj, dict):
            for key in ("details", "public_message", "message"):
                v = err_obj.get(key)
                if isinstance(v, str) and v:
                    return v
        for key in ("message", "msg"):
            v = detail.get(key)
            if isinstance(v, str) and v:
                return v

    if isinstance(detail, list):
        parts = [str(item) for item in detail if item]
        if parts:
            return "; ".join(parts)

    return str(detail) or "Request failed"


def normalize_transmission_error(detail: str, customer_tin: str = "") -> str:
    if not detail:
        return "Transmission failed. Please retry shortly."
    safe = decode_upstream_text(detail)
    lower = safe.lower()
    if "not_enabled" in lower or "not enabled" in lower or "recipient" in lower:
        who = f" ({customer_tin})" if customer_tin else ""
        return (
            f"The recipient{who} is not currently accepting e-invoices. "
            "Ask the customer to enable e-invoice receiving with FIRS, "
            "then retry transmission."
        )
    if "irn" in lower and "template" in lower:
        return (
            f"FIRS rejected the IRN template: {safe}. "
            "Verify the Service ID segment matches the value registered "
            "with your PASCA template in Settings → Profile."
        )
    return safe


def decode_upstream_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        for enc in ("utf-8", "latin-1"):
            try:
                return value.decode(enc, errors="replace")
            except Exception:
                logger.exception("decode_upstream_text fallback")
                continue
        return value.decode("utf-8", errors="replace")
    return str(value)