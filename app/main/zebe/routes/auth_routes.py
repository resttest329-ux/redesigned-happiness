import logging
import jwt
from typing import Annotated
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from utils import schema
from utils.models import User, SessionState
from auth import (
    create_access_token,
    hash_password,
    verify_password,
    oauth2_scheme,
)
from deps import get_db, get_current_user_obj
from config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _validate_pki_field(value: str | None, field_name: str) -> None:
    if value is not None and len(value.strip()) < 50:
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} appears invalid — paste the full {field_name.lower()} text",
        )


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    response_model=schema.UserOut,
)
def register_user(user: schema.UserCreate, db: Session = Depends(get_db)):
    logger.info(f"Register attempt for email: {user.email}")
    existing_user = db.query(User).filter(User.email == user.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already exists",
        )

    _validate_pki_field(user.certificate, "Certificate")
    _validate_pki_field(user.public_key, "Public key")

    db_user = User(
        username=user.username,
        email=user.email,
        business_id=user.business_id,
        service_id=user.service_id,
        hashed_password=hash_password(user.password),
        certificate=user.certificate.strip() if user.certificate else None,
        public_key=user.public_key.strip() if user.public_key else None,
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


@router.post("/token", response_model=schema.Token)
def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Session = Depends(get_db),
):
    logger.info(f"Login attempt for: {form_data.username}")
    user = (
        db.query(User).filter(User.email == form_data.username.lower()).first()
    )
    if not user or not verify_password(
        form_data.password, user.hashed_password
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token_expires = timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_IN_MINUTES
    )
    access_token = create_access_token(
        data={"sub": str(user.id)}, expires_delta=access_token_expires
    )
    logger.info(f"Login successful for user id={user.id}")
    return schema.Token(access_token=access_token, token_type="bearer")


@router.get("/me", response_model=schema.UserOut)
def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Session = Depends(get_db),
):
    return get_current_user_obj(token, db)


@router.patch("/me/secret")
def update_user_secret(
    body: schema.UserSecretUpdate,
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Session = Depends(get_db),
):
    user = get_current_user_obj(token, db)
    if not body.user_secret:
        raise HTTPException(
            status_code=400, detail="User secret cannot be empty"
        )
    hashed = hash_password(body.user_secret)
    user.user_secret = hashed
    db.commit()
    return {"ok": True}


@router.get("/me/secret")
def get_user_secret_status(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Session = Depends(get_db),
):
    user = get_current_user_obj(token, db)
    return {"has_secret": user.user_secret is not None}


@router.patch("/me/cert-key")
def update_user_cert_key(
    body: schema.UserCertKeyUpdate,
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Session = Depends(get_db),
):
    user = get_current_user_obj(token, db)
    if body.certificate is None and body.public_key is None:
        raise HTTPException(
            status_code=400, detail="At least one field must be provided"
        )
    if body.certificate is not None:
        _validate_pki_field(body.certificate, "Certificate")
        user.certificate = body.certificate.strip()
    if body.public_key is not None:
        _validate_pki_field(body.public_key, "Public key")
        user.public_key = body.public_key.strip()
    db.commit()
    return {"ok": True}


@router.patch("/me/profile")
def update_user_profile(
    body: schema.UserProfileUpdate,
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Session = Depends(get_db),
):
    user = get_current_user_obj(token, db)
    update_data = body.model_dump(exclude_unset=True)
    for field_name, value in update_data.items():
        setattr(user, field_name, value)
    db.commit()
    return {"ok": True}


@router.post("/refresh", response_model=schema.Token)
def refresh_token(body: schema.RefreshRequest, db: Session = Depends(get_db)):
    session = (
        db.query(SessionState)
        .filter(SessionState.session_id == body.session_id)
        .first()
    )
    if not session:
        raise HTTPException(status_code=401, detail="Session not found")
    if session.user_id is None:
        try:
            payload = jwt.decode(
                session.jwt_token,
                settings.JWT_SECRET_KEY,
                algorithms=[settings.ALGORITHM],
                options={"verify_exp": False, "require": ["sub"]},
            )
            session.user_id = int(payload["sub"])
            db.commit()
        except (jwt.InvalidTokenError, ValueError, TypeError):
            logging.exception("Unexpected error")
            raise HTTPException(
                status_code=401, detail="Session has no associated user"
            )
    try:
        expires = datetime.fromisoformat(session.expires_at)
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires < datetime.now(timezone.utc):
            raise HTTPException(status_code=401, detail="Session expired")
    except (ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Session expired")
    new_jwt = create_access_token(data={"sub": str(session.user_id)})
    session.jwt_token = new_jwt
    session.updated_at = datetime.now(timezone.utc)
    db.commit()
    logger.info(
        "Refreshed JWT for session_id=%s user_id=%s",
        body.session_id,
        session.user_id,
    )
    return schema.Token(access_token=new_jwt, token_type="bearer")