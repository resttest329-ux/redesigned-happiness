import httpx
import logging
from typing import Annotated
from fastapi import APIRouter, HTTPException, Header, Depends
from sqlalchemy.orm import Session
from utils import schema
from utils.models import InvoiceLog
from utils.utility import get_request_app, patch_request, post_request
from auth import verify_password, oauth2_scheme
from deps import get_db, get_current_user_obj
from services.invoice_service import (
    compute_totals,
    build_invoice_schema,
    generate_qr_b64,
    validate_wizard,
    validate_totals_consistency,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/invoice", tags=["Invoice"])


@router.post("/validate-irn")
async def validate_irn(
    data: schema.ValidateIRNSchema,
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Session = Depends(get_db),
):
    get_current_user_obj(token, db)
    endpoint: str = "/api/v1/einvoice/irn/validate"
    try:
        response = await post_request(
            endpoint=endpoint, payload=data.model_dump()
        )
    except Exception as e:
        logging.exception("Unexpected error")
        logger.error(f"validate-irn failed for IRN {data.irn}: {e}")
        raise HTTPException(status_code=502, detail="External API call failed")
    if response.get("code") == 200:
        return {"data": f"{data.irn} is linked to your company"}
    raise HTTPException(
        status_code=400, detail=response.get("message", "IRN validation failed")
    )


def _extract_error_detail(
    body: dict, default: str = "Validation failed"
) -> str:
    if not isinstance(body, dict):
        return default

    error_obj = body.get("error")
    if error_obj:
        if isinstance(error_obj, dict):
            detail = error_obj.get("details") or error_obj.get("public_message")
            if detail:
                return detail
        elif isinstance(error_obj, list):
            return ", ".join(str(item) for item in error_obj)
        elif isinstance(error_obj, str):
            return error_obj

    msg = body.get("message") or body.get("detail")
    if msg and msg != "Failed to validate invoice":
        return msg

    return default


def _assert_local_invoice_owner(irn: str, user, db: Session) -> InvoiceLog:
    log = (
        db.query(InvoiceLog)
        .filter(
            InvoiceLog.irn == irn,
            InvoiceLog.business_id == user.business_id,
        )
        .first()
    )
    if not log:
        raise HTTPException(status_code=404, detail="Invoice log not found")
    return log


@router.post("/validate-invoice")
async def validate_invoice(
    data: schema.InvoiceSchema,
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Session = Depends(get_db),
):
    get_current_user_obj(token, db)
    endpoint: str = "/api/v1/einvoice/validate"
    try:
        response = await post_request(
            endpoint=endpoint, payload=data.model_dump(exclude_none=True)
        )
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        try:
            body = e.response.json()
            logger.error(
                f"validate-invoice upstream {status} for IRN {data.irn}: {body}"
            )
        except Exception:
            logging.exception("Unexpected error")
            body = {}
            logger.error(
                f"validate-invoice upstream {status} for IRN {data.irn}: (no parseable body)"
            )
        if status == 400:
            detail = _extract_error_detail(
                body,
                "External API call failed. Please check all invoice fields are correctly filled.",
            )
            raise HTTPException(status_code=400, detail=detail)
        elif status in (401, 403):
            raise HTTPException(
                status_code=502,
                detail="FIRS authentication/authorisation failed",
            )
        else:
            detail = _extract_error_detail(body, "External API call failed")
            raise HTTPException(status_code=502, detail=detail)
    except Exception as e:
        logging.exception("Unexpected error")
        logger.error(f"validate-invoice failed for IRN {data.irn}: {e}")
        raise HTTPException(status_code=502, detail="External API call failed")
    if response.get("code") != 200:
        detail = _extract_error_detail(response, "Validation failed")
        raise HTTPException(
            status_code=400,
            detail=detail,
        )
    return response.get("message", "Validation successful")


@router.post("/sign-invoice")
async def sign_invoice(
    data: schema.InvoiceSchema,
    headers: Annotated[schema.InvoiceHeader, Header()],
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Session = Depends(get_db),
):
    logger.info(f"Sign invoice called for IRN: {data.irn}")
    user = get_current_user_obj(token, db)
    endpoint: str = "/api/v1/einvoice/sign"
    if not headers.user_secret or not user.user_secret:
        raise HTTPException(
            status_code=403, detail="User secret not configured"
        )
    if not verify_password(headers.user_secret, user.user_secret):
        raise HTTPException(status_code=403, detail="Invalid user secret")
    if not user.certificate or not user.public_key:
        raise HTTPException(
            status_code=403,
            detail="User certificate not configured. Please update your profile with your FIRS certificate and public key.",
        )
    try:
        signing_payload = {
            **data.model_dump(exclude_none=True),
            "certificate": user.certificate,
            "public_key": user.public_key,
        }
        response = await post_request(
            endpoint=endpoint, payload=signing_payload
        )
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        try:
            body = e.response.json()
            logger.error(
                f"sign-invoice upstream {status} for IRN {data.irn}: {body}"
            )
        except Exception:
            logging.exception("Unexpected error")
            body = {}
            logger.error(
                f"sign-invoice upstream {status} for IRN {data.irn}: (no parseable body)"
            )
        if status == 400:
            detail = _extract_error_detail(
                body,
                "External API call failed during signing. Please check all invoice fields.",
            )
            raise HTTPException(status_code=400, detail=detail)
        elif status in (401, 403):
            raise HTTPException(
                status_code=502,
                detail="FIRS authentication/authorisation failed during signing",
            )
        else:
            detail = _extract_error_detail(
                body, "External API call failed during signing"
            )
            raise HTTPException(status_code=502, detail=detail)
    except Exception as e:
        logging.exception("Unexpected error")
        logger.error(f"sign-invoice failed for IRN {data.irn}: {e}")
        raise HTTPException(status_code=502, detail="External API call failed")
    return response.get("message", "Invoice signed successfully")


@router.get("/transmit-invoice/{irn}")
async def transmit_invoice(
    irn: str,
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Session = Depends(get_db),
):
    logger.info(f"Transmit invoice called for IRN: {irn}")
    user = get_current_user_obj(token, db)
    _assert_local_invoice_owner(irn, user, db)
    endpoint: str = f"/api/v1/einvoice/transmit/{irn}"
    try:
        response = await get_request_app(endpoint=endpoint)
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        try:
            body = e.response.json()
            logger.error(
                f"transmit-invoice upstream {status} for IRN {irn}: {body}"
            )
        except Exception:
            logging.exception("Unexpected error")
            body = {}
            logger.error(
                f"transmit-invoice upstream {status} for IRN {irn}: (no parseable body)"
            )
        if status == 400:
            detail = _extract_error_detail(
                body, "External API call failed during transmit"
            )

            if isinstance(body, dict):
                error_obj = body.get("error")
                if (
                    isinstance(error_obj, dict)
                    and error_obj.get("sub_message") == "NOT_ENABLED"
                ):
                    raise HTTPException(
                        status_code=400,
                        detail="Recipient is not currently accepting eInvoices. Ask the customer to enable eInvoice receiving before transmission.",
                    )

            detail_lower = str(detail).lower()
            if any(
                word in detail_lower
                for word in ("already", "transmitted", "duplicate")
            ):
                logger.info(
                    f"transmit-invoice self-heal for IRN {irn}: already transmitted ({detail})"
                )
                return {"message": "Already transmitted", "data": {}}
            raise HTTPException(status_code=400, detail=detail)
        elif status in (401, 403):
            raise HTTPException(
                status_code=502,
                detail="FIRS authentication/authorisation failed",
            )
        else:
            detail = _extract_error_detail(
                body, "External API call failed during transmit"
            )
            raise HTTPException(status_code=502, detail=detail)
    except Exception as e:
        logging.exception("Unexpected error")
        logger.error(f"transmit-invoice failed for IRN {irn}: {e}")
        raise HTTPException(status_code=502, detail="External API call failed")
    return response.get("message", "Invoice transmitted successfully")


@router.get("/get-invoice/{irn}")
async def get_invoice(
    irn: str,
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Session = Depends(get_db),
):
    user = get_current_user_obj(token, db)
    endpoint: str = f"/api/v1/einvoice/{irn}"
    try:
        response = await get_request_app(endpoint=endpoint)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Invoice not found")
        logger.error(f"get-invoice failed for IRN {irn}: {e}")
        try:
            body = e.response.json()
            detail = (
                body.get("message")
                or body.get("detail")
                or body.get("error", {}).get(
                    "details",
                    "Invoice lookup failed. The external service is temporarily unavailable.",
                )
            )
        except Exception:
            logging.exception("Unexpected error")
            detail = "Invoice lookup failed. The external service is temporarily unavailable."
        raise HTTPException(status_code=502, detail=detail)
    except Exception as e:
        logging.exception("Unexpected error")
        logger.error(f"get-invoice failed for IRN {irn}: {e}")
        raise HTTPException(
            status_code=502,
            detail="Invoice lookup failed. The external service is temporarily unavailable.",
        )

    invoice_data = response.get("data") or response
    invoice_business_id = invoice_data.get("business_id")
    if (
        invoice_business_id
        and invoice_business_id.upper() != (user.business_id or "").upper()
    ):
        raise HTTPException(
            status_code=403,
            detail="You are not authorized to view this invoice",
        )
    return invoice_data


@router.patch("/update-invoice/{irn}")
async def update_invoice(
    irn: str,
    data: schema.UpdateInvoiceSchema,
    headers: Annotated[schema.InvoiceHeader, Header()],
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Session = Depends(get_db),
):
    logger.info(f"Update invoice called for IRN: {irn}")
    endpoint: str = f"/api/v1/einvoice/update/{irn}"
    user = get_current_user_obj(token, db)
    _assert_local_invoice_owner(irn, user, db)
    payload = data.model_dump(exclude_none=True, mode="json")
    if not headers.user_secret or not user.user_secret:
        raise HTTPException(
            status_code=403, detail="User secret not configured"
        )
    if not verify_password(headers.user_secret, user.user_secret):
        raise HTTPException(status_code=403, detail="Invalid user secret")
    try:
        response = await patch_request(endpoint=endpoint, payload=payload)
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        try:
            body = e.response.json()
            detail = _extract_error_detail(
                body,
                body.get("message", "External payment status update failed")
                if isinstance(body, dict)
                else "External payment status update failed",
            )
        except Exception:
            logging.exception("Unexpected error")
            detail = "External payment status update failed"

        logger.error(
            f"update-invoice upstream {status} for IRN {irn}: {detail}"
        )

        if status in (400, 404):
            raise HTTPException(status_code=status, detail=detail)
        if status in (401, 403):
            raise HTTPException(
                status_code=502,
                detail="FIRS authentication/authorisation failed during payment status update",
            )
        raise HTTPException(status_code=502, detail=detail)
    except Exception as e:
        logging.exception("Unexpected error")
        logger.error(f"update-invoice failed for IRN {irn}: {e}")
        raise HTTPException(status_code=502, detail="External API call failed")
    return response


@router.post("/assemble")
def assemble_invoice(
    body: schema.WizardAssembleRequest,
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Session = Depends(get_db),
):
    user = get_current_user_obj(token, db)
    wizard = body.wizard or {}

    structural_errors = validate_wizard(wizard)
    if structural_errors:
        logger.info(
            "assemble validation rejected %d issue(s) for business=%s irn=%s",
            len(structural_errors),
            (user.business_id or "")[-4:],
            (wizard.get("irn") or "")[-12:],
        )
        raise HTTPException(
            status_code=400,
            detail="Invoice validation failed: " + "; ".join(structural_errors),
        )

    lines = wizard.get("step3", {}).get("lines", []) or []
    if not lines:
        raise HTTPException(status_code=400, detail="No line items in wizard")
    computed = compute_totals(lines)

    total_errors = validate_totals_consistency(
        computed, lines, wizard.get("document_currency_code", "NGN")
    )
    if total_errors:
        logger.warning(
            "assemble totals inconsistent for irn=%s: %s",
            (wizard.get("irn") or "")[-12:],
            "; ".join(total_errors),
        )
        raise HTTPException(
            status_code=400,
            detail="Monetary totals are inconsistent: "
            + "; ".join(total_errors),
        )

    wizard["computed"] = computed
    invoice_dict = build_invoice_schema(wizard, user.business_id)
    return {"computed": computed, **invoice_dict}


@router.get("/{irn}/qr")
def generate_invoice_qr(
    irn: str,
    amount: float,
    date: str,
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Session = Depends(get_db),
):
    get_current_user_obj(token, db)
    b64 = generate_qr_b64(irn, amount, date)
    return {"qr_b64": b64}