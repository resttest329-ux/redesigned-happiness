import logging
import secrets
from datetime import datetime, timezone, timedelta
from typing import Annotated
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session as DBSession
from utils import schema
from utils.models import SessionState
from deps import get_db, get_current_user_obj
from auth import oauth2_scheme

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions", tags=["Sessions"])


def _get_session_or_404(session_id: str, db: DBSession) -> SessionState:
    session = (
        db.query(SessionState)
        .filter(SessionState.session_id == session_id)
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


def _assert_session_not_expired(session: SessionState) -> None:
    try:
        expires = datetime.fromisoformat(session.expires_at)
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires < datetime.now(timezone.utc):
            raise HTTPException(status_code=404, detail="Session expired")
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="Session expired")


def _authorize_session_owner(
    session: SessionState, token: str, db: DBSession
) -> None:
    current_user = get_current_user_obj(token, db)
    if session.user_id is not None and session.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    if session.user_id is None:
        session.user_id = current_user.id
        db.commit()


@router.post("")
def create_session(data: schema.SessionCreate, db: DBSession = Depends(get_db)):
    session_id = secrets.token_urlsafe(32)
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=8)).isoformat()
    session = SessionState(
        session_id=session_id,
        jwt_token=data.jwt_token,
        user_secret=data.user_secret,
        username=data.username,
        business_id=data.business_id,
        user_id=data.user_id,
        expires_at=expires_at,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    logger.info("Session created for user_id=%s", data.user_id)
    return {"session_id": session_id}


@router.get("/{session_id}", response_model=schema.SessionOutWithToken)
def get_session(
    session_id: str,
    db: DBSession = Depends(get_db),
):
    session = _get_session_or_404(session_id, db)
    _assert_session_not_expired(session)
    return session


@router.delete("/{session_id}")
def delete_session(
    session_id: str,
    token: Annotated[str, Depends(oauth2_scheme)],
    db: DBSession = Depends(get_db),
):
    session = _get_session_or_404(session_id, db)
    _authorize_session_owner(session, token, db)
    db.delete(session)
    db.commit()
    return {"ok": True}


@router.patch("/{session_id}/secret")
def update_session_secret(
    session_id: str,
    body: schema.SessionSecretUpdate,
    token: Annotated[str, Depends(oauth2_scheme)],
    db: DBSession = Depends(get_db),
):
    session = _get_session_or_404(session_id, db)
    _authorize_session_owner(session, token, db)
    session.user_secret = body.user_secret
    session.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}


@router.patch("/{session_id}/wizard")
def update_session_wizard(
    session_id: str,
    body: schema.SessionWizardUpdate,
    token: Annotated[str, Depends(oauth2_scheme)],
    db: DBSession = Depends(get_db),
):
    session = _get_session_or_404(session_id, db)
    _authorize_session_owner(session, token, db)
    session.wizard_json = body.wizard_json
    session.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}


@router.patch("/{session_id}/token")
def update_session_token(
    session_id: str,
    body: schema.SessionTokenUpdate,
    token: Annotated[str, Depends(oauth2_scheme)],
    db: DBSession = Depends(get_db),
):
    session = _get_session_or_404(session_id, db)
    _authorize_session_owner(session, token, db)
    session.jwt_token = body.jwt_token
    session.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}


@router.delete("/{session_id}/wizard")
def clear_session_wizard(
    session_id: str,
    token: Annotated[str, Depends(oauth2_scheme)],
    db: DBSession = Depends(get_db),
):
    session = _get_session_or_404(session_id, db)
    _authorize_session_owner(session, token, db)
    session.wizard_json = None
    session.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}