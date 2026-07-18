import logging
from typing import Optional


def normalize_detail(response, default: str = "Request failed") -> str:
    """Extract a user-friendly error detail from a backend response.

    Handles FastAPI's standard {"detail": "..."} format, validation errors
    where detail is a list, and missing/invalid JSON bodies.
    """
    if response is None:
        return default
    try:
        body = response.json()
    except Exception:
        logging.exception("normalize_detail json parse")
        text = getattr(response, "text", "")
        return text[:200] if text else default
    if not isinstance(body, dict):
        return default
    detail = body.get("detail")
    if detail is None:
        msg = body.get("message")
        if isinstance(msg, str) and msg:
            return msg
        return default
    if isinstance(detail, str):
        return detail or default
    if isinstance(detail, list):
        msgs: list[str] = []
        for item in detail:
            if isinstance(item, dict):
                m = item.get("msg") or item.get("message") or ""
                loc = item.get("loc") or []
                if isinstance(loc, list) and loc:
                    field = ".".join(str(x) for x in loc[1:]) or str(loc[-1])
                    msgs.append(f"{field}: {m}" if m else field)
                elif m:
                    msgs.append(m)
            elif isinstance(item, str):
                msgs.append(item)
        return "; ".join(msgs) if msgs else default
    if isinstance(detail, dict):
        m = detail.get("message") or detail.get("details")
        if isinstance(m, str) and m:
            return m
    return default