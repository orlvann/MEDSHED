# backend/routers/auth.py
# Thin HTTP layer: validate input, delegate to service, serialize outputs.

"""
Auth Router — authentication & identity only.

Scope:
- POST /api/v1/auth/login → issue tokens
- GET  /api/v1/auth/me    → current user info

Out of scope:
- Account creation and management (handled by 'users' router for admins,
  and by doctor_service auto-provision for doctors).

Login requirements:
- Deny when users.is_active == False.
- If users.must_change_password == True, require password change flow on first login
  (enforced by the auth layer or a dedicated endpoint — to be implemented).

Error contract:
- Use dto_common.ErrorPayload {code, detail, context} (e.g., 401 invalid_credentials).
"""

from fastapi import APIRouter, Body, status

from backend.models.schemas import (
    ErrorPayload,  # canonical error shape from common (code/detail/context)
    LoginRequest,
    Role,
    TokenResponse,
    UserRead,
)

router = APIRouter(tags=["auth"])


@router.post(
    "/api/v1/auth/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Issue JWT access token",
    responses={
        401: {
            "model": ErrorPayload,
            "description": "Invalid credentials",
            "content": {
                "application/json": {
                    "example": {
                        "code": "invalid_credentials",
                        "detail": "Invalid email or password",
                        "context": None,
                    }
                }
            },
        }
    },
)
def login(payload: LoginRequest = Body(...)):
    """
    Stub: delegate to auth_service.login(payload) and return a TokenResponse.
    On failure, raise HTTP 401 with ErrorPayload.

    TODO (real impl):
    - Verify password against stored hash.
    - Check `users.is_active` (deny login when False).
    - Issue JWT with proper claims (sub, role, exp, aud, etc.).
    """
    # Example success (stub)
    return {
        "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
        "token_type": "bearer",  # matches TokenResponse definition
        "role": Role.doctor,
        "expires_in": 3600,
    }


@router.get(
    "/api/v1/auth/me",
    response_model=UserRead,
    summary="Get current user",
)
def me():
    """
    Stub: read current user from auth context (e.g., request.state.user)
    and serialize to UserRead.

    TODO (real impl):
    - Populate from verified JWT / user lookup.
    - Ensure timestamps are UTC (ISO 'Z').
    """
    return {
        "id": 1,
        "email": "user@example.com",
        "role": Role.doctor,
        "is_active": True,
        "created_at": None,
        "updated_at": None,
    }
