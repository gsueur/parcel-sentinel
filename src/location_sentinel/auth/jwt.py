from __future__ import annotations

from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt  # noqa: F401 (JWTError re-exported for callers)

from ..config import settings


def create_token(user_id: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.JWT_EXPIRE_DAYS)
    payload = {"sub": user_id, "role": role, "exp": expire}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def decode_token(token: str) -> dict:
    """Returns payload dict or raises jose.JWTError."""
    return jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
