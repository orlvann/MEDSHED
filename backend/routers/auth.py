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
    ChangePasswordRequest,
    ChangePasswordResponse,
    ErrorPayload,  # canonical error shape from common (code/detail/context)
    LoginRequest,
    ProfileUpdate,
    SetPasswordRequest,
    SetPasswordResponse,
    TokenResponse,
    UserRead,
)
from pydantic import BaseModel, EmailStr
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
        422: {
            "model": ErrorPayload,
            "description": "Weak password",
        }
    },
)
def set_password(payload: SetPasswordRequest = Body(...), db: Session = Depends(get_db)):
    """
    Set or reset password using a token received via email.
    
    This endpoint is used when:
    - A new user receives a password setup email
    - A user requests a password reset
    
    The token is validated, the password is updated, and the user account is activated.
    The token is consumed (deleted) after use, making it one-time only.
    
    Validation:
    - Token must be valid and not expired (48 hours)
    - Password must be at least 8 characters
    """
    from backend.models.orm.user import User
    from backend.services import token_service
    from backend.utils.security import hash_password
    
    try:
        # Validate and consume token (one-time use) - use same DB session
        user_id = token_service.consume_token(token=payload.token, db=db)
        
        # Get user
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=make_error("not_found", "User not found"),
            )
        
        # Update password and activate account
        user.password_hash = hash_password(payload.new_password)
        user.is_active = True
        
        db.commit()
        
        return SetPasswordResponse(message="Password set successfully")
        
    except HTTPException:
        # Re-raise HTTP exceptions from token_service
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
    """
    Request a password reset email.
    
    This endpoint:
    - Checks if the user exists
    - Generates a password reset token
    - Sends a password reset email
    - Always returns 200 OK (even if email doesn't exist, for security)
    
    The user will receive an email with a link to set a new password.
    The link uses the same /set-password endpoint as initial password setup.
    """
    from backend.models.orm.user import User
    from backend.services import token_service, email_service
    
    try:
        # Look up user by email
        user = db.query(User).filter(User.email == payload.email).first()
        
        # If user exists, generate token and send email
        if user:
            # Generate password reset token
            token = token_service.create_password_reset_token(user_id=user.id)
            
            # Send password reset email
            try:
                email_service.send_password_reset_email(
                    to_email=user.email,
                    token=token,
                )
            except Exception as e:
                # Log error but don't expose to user
                import traceback
                traceback.print_exc()
                # Still return success to prevent email enumeration
        
        # Always return success message (security: don't reveal if email exists)
        return ForgotPasswordResponse(
            message="If an account exists with this email, you will receive password reset instructions."
        )
        
    except Exception as e:
        # Log error but return success to prevent information leakage
        import traceback
        traceback.print_exc()
        return ForgotPasswordResponse(
            message="If an account exists with this email, you will receive password reset instructions."
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
    
    # Get first_name and last_name from linked Doctor if exists
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
        401: {
            "model": ErrorPayload,
            "description": "Invalid or expired token",
        },
        404: {
            "model": ErrorPayload,
            "description": "User or linked Doctor not found",
        }
    },
)
def update_profile(
    payload: ProfileUpdate = Body(...),
    user: UserCtx = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Update the current user's profile (first_name, last_name).

    Since first_name and last_name come from the linked Doctor record,
    this endpoint updates the Doctor model if the user has one linked.
    """
    from backend.models.orm.user import User

    db_user = db.query(User).filter(User.id == user.user_id).first()

    if not db_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=make_error("not_found", "User not found"),
        )

    # Only update if user has a linked Doctor
    if not db_user.doctor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=make_error("no_doctor_linked", "No doctor profile linked to this user"),
        )

    # Update the doctor's name fields
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
        401: {
            "model": ErrorPayload,
            "description": "Invalid or expired token",
        }
    },
)
def change_password(
    payload: ChangePasswordRequest = Body(...),
    user: UserCtx = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Change the current user's password.

    Requires the current password for verification before setting the new one.
    """
    from backend.models.orm.user import User
    from backend.utils.security import hash_password, verify_password

    db_user = db.query(User).filter(User.id == user.user_id).first()

    if not db_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=make_error("not_found", "User not found"),
        )

    # Verify current password
    if not verify_password(payload.current_password, db_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=make_error("invalid_password", "Current password is incorrect"),
        )

    # Update password
    db_user.password_hash = hash_password(payload.new_password)
    db.commit()

    return ChangePasswordResponse(message="Password changed successfully")
