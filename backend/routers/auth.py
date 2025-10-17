# Thin HTTP layer: validate, delegate, serialize.
# Import ONLY from schemas package
from fastapi import APIRouter, Body, status

from backend.models.schemas import (
    ErrorPayload,  # canonical error shape from common
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
                        # details may include e.g. {"attempts": 3} in real impl
                    }
                }
            },
        }
    },
)
def login(payload: LoginRequest = Body(...)):
    # TODO: delegate to auth_service.login(payload)
    # NOTE: When raising 401, return body matching ErrorPayload.
    # Example:
    # from fastapi import HTTPException
    # raise HTTPException(
    #     status_code=401,
    #     detail={
    #         "code": "invalid_credentials",
    #         "message": "Invalid email or password",
    #         "details": None,
    #     },
    # )

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
    # TODO: read current user from auth context (e.g. request.state.user)
    return {
        "id": 1,
        "email": "user@example.com",
        "role": Role.DOCTOR,
        "is_active": True,
        "created_at": None,
    }
