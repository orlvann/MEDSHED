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

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.db.session import get_db
from backend.models.schemas import (
    ErrorPayload,  # canonical error shape from common (code/detail/context)
    LoginRequest,
    TokenResponse,
    UserRead,
)
from backend.models.schemas.dto_common import make_error
from backend.routers.deps import UserCtx, get_current_user
from backend.services import auth_service

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
        },
        403: {
            "model": ErrorPayload,
            "description": "User account is inactive",
            "content": {
                "application/json": {
                    "example": {
                        "code": "inactive_user",
                        "detail": "User account is inactive",
                        "context": None,
                    }
                }
            },
        }
    },
)
def login(payload: LoginRequest = Body(...), db: Session = Depends(get_db)):
    """
    Authenticate user and issue JWT access token.
    
    Verifies:
    - Email exists
    - Password is correct
    - User account is active
    
    Returns JWT token on success, raises 401/403 on failure.
    """
    try:
        token_response = auth_service.login(db, payload.email, payload.password)
        return token_response
    except auth_service.InvalidCredentialsError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=make_error(e.code, detail=e.detail),
        )
    except auth_service.InactiveUserError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=make_error(e.code, detail=e.detail),
        )


@router.get(
    "/api/v1/auth/me",
    response_model=UserRead,
    summary="Get current user info",
    responses={
        401: {
            "model": ErrorPayload,
            "description": "Invalid or expired token",
        }
    },
)
def me(user: UserCtx = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Get information about the currently authenticated user.
    
    Requires valid JWT token in Authorization header.
    Returns user information from the database.
    """
    # Fetch full user object from database
    from backend.models.orm.user import User
    
    db_user = db.query(User).filter(User.id == user.user_id).first()
    
    if not db_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=make_error("not_found", "User not found"),
        )
    
    return UserRead(
        id=db_user.id,
        email=db_user.email,
        role=db_user.role,
        is_active=db_user.is_active,
        created_at=db_user.created_at,
        updated_at=db_user.updated_at,
    )
