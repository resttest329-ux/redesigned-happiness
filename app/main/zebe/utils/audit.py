import logging
from typing import Any, Optional

from fastapi import Request

audit_logger = logging.getLogger("zebe.audit")


_SENSITIVE_KEYS = {
    "password",
    "hashed_password",
    "user_secret",
    "secret",
    "confirm_secret",
    "certificate",
    "public_key",
    "jwt_token",
    "access_token",
    "token",
    "authorization",
    "api_key",
    "api_secret",
}


def mask_id(value: Any, keep: int = 4) -> str:
    """Mask an identifier keeping only the tail characters visible."""
    if value is None:
        return ""
    s = str(value)
    if not s:
        return ""
    if len(s) <= keep:
        return "*" * len(s)
    return "*" * (len(s) - keep) + s[-keep:]


def mask_email(email: Optional[str]) -> str:
    if not email or "@" not in str(email):
        return mask_id(email or "")
    local, _, domain = str(email).partition("@")
    if len(local) <= 2:
        masked_local = "*" * len(local)
    else:
        masked_local = local[0] + "*" * (len(local) - 2) + local[-1]
    return f"{masked_local}@{domain}"


def mask_tin(tin: Optional[str]) -> str:
    if not tin:
        return ""
    s = str(tin)
    if "-" in s:
        head, _, tail = s.partition("-")
        return f"{'*' * max(0, len(head) - 2)}{head[-2:] if len(head) >= 2 else head}-{tail}"
    return mask_id(s)


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if str(k).lower() in _SENSITIVE_KEYS:
                out[k] = "[REDACTED]"
            elif str(k).lower() == "email":
                out[k] = mask_email(v) if isinstance(v, str) else "[REDACTED]"
            elif str(k).lower() == "tin":
                out[k] = mask_tin(v) if isinstance(v, str) else "[REDACTED]"
            else:
                out[k] = _redact(v)
        return out
    if isinstance(value, (list, tuple)):
        return [_redact(v) for v in value]
    return value


def _client_ip(request: Optional[Request]) -> str:
    if request is None:
        return "-"
    try:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip() or "-"
        client = request.client
        if client and client.host:
            return client.host
    except Exception:
        logging.exception("Unexpected error")
        return "-"
    return "-"


def audit(
    action: str,
    *,
    request: Optional[Request] = None,
    outcome: str = "ok",
    actor_id: Any = None,
    business_id: Any = None,
    target: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> None:
    """Emit a structured, redacted audit log line."""
    try:
        payload = {
            "action": action,
            "outcome": outcome,
            "ip": _client_ip(request),
            "actor_id": actor_id if actor_id is not None else "-",
            "business_id": mask_id(business_id) if business_id else "-",
            "target": target or "-",
        }
        if metadata:
            payload["meta"] = _redact(metadata)
        audit_logger.info("audit %s", payload)
    except Exception:
        logging.exception("Unexpected error")
        audit_logger.exception("audit logging failed for action=%s", action)
