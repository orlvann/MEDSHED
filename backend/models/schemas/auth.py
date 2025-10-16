# Thin HTTP layer: validate, delegate, serialize.
from fastapi import APIRouter, Body, status

from backend.models.schemas import (
    ErrorPayload,
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
    summary="Issue JWT",
    responses={401: {"model": ErrorPayload}},
)
def login(payload: LoginRequest = Body(...)):
    # TODO: auth_service.login(payload)
    # On bad credentials, raise HTTPException(status_code=401, detail=...)
    return {
        "access_token": "jwt-string",
        "token_type": "bearer",
        "role": Role.DOCTOR,
        "expires_in": 3600,
    }


@router.get(
    "/api/v1/auth/me",
    response_model=UserRead,
    summary="Current user",
)
def me():
    # TODO: read from auth context
    return {
        "id": 1,
        "email": "user@example.com",
        "role": Role.DOCTOR,
        "is_active": True,
        "created_at": None,
    }
