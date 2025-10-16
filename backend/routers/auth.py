# Thin HTTP layer: validate, delegate, serialize.

from fastapi import APIRouter, Body

from backend.models.schemas import LoginRequest, Role, TokenResponse, UserRead

router = APIRouter(tags=["auth"])


@router.post("/api/v1/auth/login", response_model=TokenResponse, summary="Issue JWT")
def login(payload: LoginRequest = Body(...)):
    # TODO: auth_service.login(payload)
    return {
        "access_token": "jwt-string",
        "token_type": "bearer",
        "role": Role.DOCTOR,
        "expires_in": 3600,
    }


@router.get("/api/v1/auth/me", response_model=UserRead, summary="Current user")
def me():
    # TODO: from auth context
    return {
        "id": 1,
        "email": "user@example.com",
        "role": Role.DOCTOR,
        "is_active": True,
        "created_at": None,
    }
