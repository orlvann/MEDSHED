# backend/routers/deps.py
"""
Router dependencies for basic role-based access control (RBAC).

Purpose:
- Keep role checks out of router functions.
- Extract and validate JWT tokens from Authorization header.
- Provide user context to protected endpoints.

Notes:
- Error bodies are standardized across the API as:
  { "detail": "<code>", "code": "<code>", "context": { ... } }
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

# Unified error factory (keeps errors consistent with the rest of the API).
from backend.db.session import get_db
from backend.models.schemas.dto_common import make_error
from backend.services import auth_service

# HTTP Bearer scheme for extracting tokens from Authorization header
security = HTTPBearer()


class UserCtx:
    """
    Minimal user context propagated via Depends.

    Contains:
    - user_id: Database ID of the authenticated user (User.id)
    - role: User role ("admin" | "doctor" | "doctor_admin")
    - email: User email address
    - doctor_id: Database ID of the linked Doctor (Doctor.id), or None for admins
    """

    def __init__(self, user_id: int, role: str, email: str, doctor_id: int | None = None) -> None:
        self.user_id = user_id
        self.role = role  # expected values: "admin" | "doctor" | "doctor_admin"
        self.email = email
        self.doctor_id = doctor_id  # None for admin users, Doctor.id for doctor users


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> UserCtx:
    """
    Extract and validate JWT token from Authorization header.
    
    Args:
        credentials: HTTP Bearer token from Authorization header
        db: Database session
        
    Returns:
        UserCtx with user information
        
    Raises:
        HTTPException: 401 if token is invalid or user not found
    """
    token = credentials.credentials
    
    try:
        user = auth_service.get_user_from_token(db, token)
        return UserCtx(
            user_id=user.id,
            role=user.role.value,
            email=user.email,
            doctor_id=user.doctor_id,  # None for admins, Doctor.id for doctor users
        )
    except auth_service.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=make_error("invalid_token"),
            headers={"WWW-Authenticate": "Bearer"},
        )
    except auth_service.InactiveUserError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=make_error("inactive_user"),
        )


def require_admin(user: UserCtx = Depends(get_current_user)) -> UserCtx:
    """
    Enforce that only admins and doctor_admins can access the endpoint.
    Returns the user context for downstream use (e.g., auditing).
    """
    if user.role not in ("admin", "doctor_admin"):
        # Keep error shape consistent with the whole API.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=make_error("forbidden"),
        )
    return user


def require_doctor(user: UserCtx = Depends(get_current_user)) -> UserCtx:
    """
    Enforce that only doctors and doctor_admins can access the endpoint.
    Useful for doctor-facing paths (/me, ICS, /published, exports).
    """
    if user.role not in ("doctor", "doctor_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=make_error("forbidden"),
        )
    return user


def require_user(user: UserCtx = Depends(get_current_user)) -> UserCtx:
    """
    Generic guard: any authenticated user (admin or doctor).

    Used for read-only endpoints that are safe for both roles.
    """
    return user
