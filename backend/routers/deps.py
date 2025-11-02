# backend/routers/deps.py
"""
Router dependencies for basic role-based access control (RBAC).

Purpose:
- Keep role checks out of router functions.
- Make it easy to swap the internals for real JWT validation later
  without changing routers' signatures.

Notes:
- Error bodies are standardized across the API as:
  { "detail": "<code>", "code": "<code>", "context": { ... } }
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status

# Unified error factory (keeps errors consistent with the rest of the API).
from backend.models.schemas.dto_common import make_error


class UserCtx:
    """
    Minimal user context propagated via Depends.

    Real-world implementation should:
    - Parse and verify JWT (signature, expiration, audience, etc.).
    - Map claims to roles/permissions.
    - Optionally load user from DB (for flags like is_active).
    """

    def __init__(self, user_id: int, role: str) -> None:
        self.user_id = user_id
        self.role = role  # expected values: "admin" | "doctor"


# TODO (replace stub):
# - Decode JWT from Authorization: Bearer <token>.
# - Validate signature and claims.
# - Create UserCtx from claims (user_id, role).
def get_current_user() -> UserCtx:
    """
    Stub: always returns an admin user.

    Replace with e.g.:
        token = auth_service.get_bearer_token(request)
        claims = auth_service.decode_and_verify(token)
        return UserCtx(user_id=claims.sub, role=claims.role)
    """
    return UserCtx(user_id=101, role="admin")


def require_admin(user: UserCtx = Depends(get_current_user)) -> UserCtx:
    """
    Enforce that only admins can access the endpoint.
    Returns the user context for downstream use (e.g., auditing).
    """
    if user.role != "admin":
        # Keep error shape consistent with the whole API.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=make_error("forbidden"),
        )
    return user


def require_doctor(user: UserCtx = Depends(get_current_user)) -> UserCtx:
    """
    Enforce that doctors (and admins) can access the endpoint.
    Useful for doctor-facing paths (/me, ICS, /published, exports).
    """
    if user.role not in ("doctor", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=make_error("forbidden"),
        )
    return user
