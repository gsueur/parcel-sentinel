from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError

from .jwt import decode_token

_bearer = HTTPBearer()


@dataclass
class UserClaims:
    user_id: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def current_user(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
) -> UserClaims:
    try:
        payload = decode_token(creds.credentials)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    return UserClaims(user_id=payload["sub"], role=payload["role"])


def require_admin(user: UserClaims = Depends(current_user)) -> UserClaims:
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user
