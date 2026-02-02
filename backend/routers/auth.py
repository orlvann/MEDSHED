# backend/routers/auth.py
# Thin HTTP layer: validate input, delegate to service, serialize outputs.

"""
Auth Router — authentication & identity only.

Scope:
- POST /api/v1/auth/login → issue tokens
- GET  /api/v1/auth/me    → current user info

Error contract:
- Use dto_common.ErrorPayload {code, detail, context} (e.g., 401 invalid_credentials).
"""

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from backend.db.session import get_db
from backend.models.schemas import (
    ChangePasswordRequest,
    ChangePasswordResponse,
    ErrorPayload,
    LoginRequest,
    ProfileUpdate,
    SetPasswordRequest,
    SetPasswordResponse,
    TokenResponse,
    UserRead,
)
from backend.models.schemas.dto_common import make_error
from backend.routers.deps import UserCtx, get_current_user
from backend.services import auth_service

router = APIRouter(tags=["auth"])


class ForgotPasswordRequest(BaseModel):
    """Request schema for forgot password endpoint"""

    email: EmailStr


class ForgotPasswordResponse(BaseModel):
    """Response schema for forgot password endpoint"""

    message: str


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
        },
    },
)
def login(payload: LoginRequest = Body(...), db: Session = Depends(get_db)):
    """Authenticate user and issue JWT access token."""
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


@router.post(
    "/api/v1/auth/set-password",
    response_model=SetPasswordResponse,
    status_code=status.HTTP_200_OK,
    summary="Set password using reset token",
    responses={
        400: {
            "model": ErrorPayload,
            "description": "Invalid or expired token",
            "content": {
                "application/json": {
                    "example": {
                        "code": "invalid_token",
                        "detail": "Invalid or expired password reset token",
                        "context": None,
                    }
                }
            },
        },
        422: {"model": ErrorPayload, "description": "Weak password"},
    },
)
def set_password(payload: SetPasswordRequest = Body(...), db: Session = Depends(get_db)):
    """
    Set or reset password using a token received via email.
    """
    from backend.models.orm.user import User
    from backend.services import token_service
    from backend.utils.security import hash_password

    try:
        user_id = token_service.consume_token(token=payload.token, db=db)

        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=make_error("not_found", detail="User not found"),
            )

        user.password_hash = hash_password(payload.new_password)
        user.is_active = True
        db.commit()

        return SetPasswordResponse(message="Password set successfully")

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        import traceback

        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=make_error(
                "internal_error",
                detail="Failed to set password",
                context={"error": str(e)},
            ),
        )


@router.post(
    "/api/v1/auth/forgot-password",
    response_model=ForgotPasswordResponse,
    status_code=status.HTTP_200_OK,
    summary="Request password reset email",
    responses={
        200: {
            "model": ForgotPasswordResponse,
            "description": "Success response (returned even if email doesn't exist for security)",
        }
    },
)
def forgot_password(payload: ForgotPasswordRequest = Body(...), db: Session = Depends(get_db)):
    """Request a password reset email."""
    from backend.models.orm.user import User
    from backend.services import email_service, token_service

    try:
        user = db.query(User).filter(User.email == payload.email).first()

        if user:
            token = token_service.create_password_reset_token(user_id=user.id)

            try:
                email_service.send_password_reset_email(
                    to_email=user.email,
                    token=token,
                )
            except Exception:
                import traceback

                traceback.print_exc()

        return ForgotPasswordResponse(
            message="If an account exists with this email, you will receive password reset instructions."
        )

    except Exception:
        import traceback

        traceback.print_exc()
        return ForgotPasswordResponse(
            message="If an account exists with this email, you will receive password reset instructions."
        )


@router.get(
    "/api/v1/auth/me",
    response_model=UserRead,
    summary="Get current user info",
    responses={401: {"model": ErrorPayload, "description": "Invalid or expired token"}},
)
def me(user: UserCtx = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get information about the currently authenticated user."""
    from backend.models.orm.user import User

    db_user = db.query(User).filter(User.id == user.user_id).first()

    if not db_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=make_error("not_found", detail="User not found"),
        )

    first_name = None
    last_name = None
    if db_user.doctor:
        first_name = db_user.doctor.first_name
        last_name = db_user.doctor.last_name

    return UserRead(
        id=db_user.id,
        email=db_user.email,
        role=db_user.role,
        is_active=db_user.is_active,
        first_name=first_name,
        last_name=last_name,
        created_at=db_user.created_at,
        updated_at=db_user.updated_at,
    )


@router.patch(
    "/api/v1/auth/me",
    response_model=UserRead,
    summary="Update current user profile",
    responses={
        401: {"model": ErrorPayload, "description": "Invalid or expired token"},
        404: {"model": ErrorPayload, "description": "User or linked Doctor not found"},
    },
)
def update_profile(
    payload: ProfileUpdate = Body(...),
    user: UserCtx = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update the current user's profile (first_name, last_name)."""
    from backend.models.orm.user import User

    db_user = db.query(User).filter(User.id == user.user_id).first()

    if not db_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=make_error("not_found", detail="User not found"),
        )

    if not db_user.doctor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=make_error("no_doctor_linked", detail="No doctor profile linked to this user"),
        )

    if payload.first_name is not None:
        db_user.doctor.first_name = payload.first_name
    if payload.last_name is not None:
        db_user.doctor.last_name = payload.last_name

    db.commit()
    db.refresh(db_user)

    return UserRead(
        id=db_user.id,
        email=db_user.email,
        role=db_user.role,
        is_active=db_user.is_active,
        first_name=db_user.doctor.first_name,
        last_name=db_user.doctor.last_name,
        created_at=db_user.created_at,
        updated_at=db_user.updated_at,
    )


@router.post(
    "/api/v1/auth/change-password",
    response_model=ChangePasswordResponse,
    status_code=status.HTTP_200_OK,
    summary="Change current user's password",
    responses={
        400: {
            "model": ErrorPayload,
            "description": "Current password is incorrect",
            "content": {
                "application/json": {
                    "example": {
                        "code": "invalid_password",
                        "detail": "Current password is incorrect",
                        "context": None,
                    }
                }
            },
        },
        401: {"model": ErrorPayload, "description": "Invalid or expired token"},
    },
)
def change_password(
    payload: ChangePasswordRequest = Body(...),
    user: UserCtx = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Change the current user's password."""
    from backend.models.orm.user import User
    from backend.utils.security import hash_password, verify_password

    db_user = db.query(User).filter(User.id == user.user_id).first()

    if not db_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=make_error("not_found", detail="User not found"),
        )

    if not verify_password(payload.current_password, db_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=make_error("invalid_password", detail="Current password is incorrect"),
        )

    db_user.password_hash = hash_password(payload.new_password)
    db.commit()

    return ChangePasswordResponse(message="Password changed successfully")
