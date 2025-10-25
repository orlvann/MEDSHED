# backend/routers/auth.py
# Thin HTTP layer: validate input, delegate to service, serialize outputs.

from fastapi import APIRouter, Body, status

from backend.models.schemas import (
    ErrorPayload,  # canonical error shape from common (code/message/details)
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
                        "message": "Invalid email or password",
                        "details": None,
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
    """
    return {
        "id": 1,
        "email": "user@example.com",
        "role": Role.doctor,
        "is_active": True,
        "created_at": None,
    }
