from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr

from ..auth.dependencies import UserClaims, current_user
from ..auth.email import send_new_user_notification, send_verification_email
from ..auth.jwt import create_token
from ..auth.password import hash_password, verify_password
from ..config import settings
from ..storage.duckdb_store import store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    name: str | None = None
    newsletter: bool = False


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


@router.post("/register", status_code=201)
async def register(body: RegisterRequest):
    """Create a new account. Sends a verification email before login is allowed."""
    if store.get_user_by_email(body.email) is not None:
        raise HTTPException(status_code=409, detail="Email already registered")

    user = store.create_user(
        email=body.email,
        password_hash=hash_password(body.password),
        name=body.name,
        newsletter=body.newsletter,
    )
    token = store.create_verification_token(user["user_id"])

    try:
        send_verification_email(body.email, token)
    except Exception:
        logger.warning("Failed to send verification email to %s", body.email, exc_info=True)

    try:
        send_new_user_notification(body.email, body.name, body.newsletter)
    except Exception:
        logger.warning("Failed to send new-user notification for %s", body.email, exc_info=True)

    return {"user_id": user["user_id"], "message": "Check your email to verify your account"}


@router.get("/verify")
async def verify_email(token: str = Query(...)):
    """Consume a one-time email verification token."""
    user_id = store.consume_verification_token(token)
    if user_id is None:
        raise HTTPException(status_code=400, detail="Invalid or expired verification token")

    store.mark_user_verified(user_id)

    if settings.FRONTEND_URL:
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/verified")
    return {"message": "Email verified. You can now log in."}


@router.post("/login")
async def login(body: LoginRequest):
    """Exchange email + password for a long-lived JWT."""
    user = store.get_user_by_email(body.email)
    if user is None or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user["is_verified"]:
        raise HTTPException(status_code=403, detail="Email address not verified")

    token = create_token(user["user_id"], user["role"])
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.JWT_EXPIRE_DAYS)
    return {
        "token": token,
        "user_id": user["user_id"],
        "role": user["role"],
        "expires_at": expires_at.isoformat(),
    }


@router.get("/me")
async def me(user: UserClaims = Depends(current_user)):
    """Return the authenticated user's profile."""
    db_user = store.get_user_by_id(user.user_id)
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "user_id": db_user["user_id"],
        "email": db_user["email"],
        "name": db_user["name"],
        "role": db_user["role"],
        "created_at": db_user["created_at"],
    }
