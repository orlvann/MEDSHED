# backend/services/token_service.py
"""
Password Reset Token Service.

Manages password reset tokens stored in a separate table for security.

Responsibilities:
- Create new password reset tokens (with expiration)
- Validate tokens (check existence and expiration)
- Consume tokens (validate once, then delete)
- Clean up old/expired tokens

Security:
- One active token per user (enforced by DB unique constraint)
- Tokens expire after configured time (default 48 hours)
- Tokens are single-use (deleted after consumption)
- Cryptographically secure random tokens (64+ chars)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from backend.db.session import SessionLocal
from backend.models.orm.password_reset_token import PasswordResetToken
from backend.models.schemas.dto_common import make_error
from backend.utils.security import generate_secure_token


def _now_utc() -> datetime:
    """Return current UTC timestamp with tzinfo=UTC."""
    return datetime.now(timezone.utc)


def _ensure_aware(dt: datetime) -> datetime:
    """Ensure datetime has UTC tzinfo for safe comparisons."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _get_db() -> Session:
    """Get database session."""
    return SessionLocal()


def create_password_reset_token(
    *, user_id: int, expires_hours: int = 48, db: Session | None = None
) -> str:
    """
    Create a new password reset token for a user.
    
    Args:
        user_id: The ID of the user
        expires_hours: Number of hours until token expires (default: 48)
        db: Optional database session (if None, creates a new one)
        
    Returns:
        The generated token string
        
    Notes:
        - Deletes any existing token for the user first (one token per user)
        - Token is cryptographically secure (64+ chars, URL-safe)
        - Token expires after specified hours
        - If db is provided, caller is responsible for committing
    """
    should_close = False
    if db is None:
        db = _get_db()
        should_close = True
    try:
        # Delete any existing tokens for this user (enforce one token per user)
        existing = db.query(PasswordResetToken).filter(
            PasswordResetToken.user_id == user_id
        ).first()
        if existing:
            db.delete(existing)
            if should_close:
                db.commit()
        
        # Generate new secure token
        token = generate_secure_token()
        
        # Calculate expiration
        expires_at = _now_utc() + timedelta(hours=expires_hours)
        
        # Create token record
        token_record = PasswordResetToken(
            user_id=user_id,
            token=token,
            expires_at=expires_at,
        )
        
        db.add(token_record)
        
        if should_close:
            db.commit()
        else:
            db.flush()
        
        return token
    except Exception as e:
        if should_close:
            db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=make_error(
                "token_creation_failed",
                detail="Failed to create password reset token",
                context={"error": str(e)},
            ),
        )
    finally:
        if should_close:
            db.close()


def validate_token(*, token: str) -> int:
    """
    Validate a password reset token.
    
    Args:
        token: The token string to validate
        
    Returns:
        The user_id associated with the token
        
    Raises:
        HTTPException 400: If token is invalid or expired
    """
    db = _get_db()
    try:
        # Find token
        token_record = db.query(PasswordResetToken).filter(
            PasswordResetToken.token == token
        ).first()
        
        if not token_record:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=make_error(
                    "invalid_token",
                    detail="Invalid or expired password reset token",
                    context={},
                ),
            )
        
        # Check if expired
        now = _now_utc()
        if token_record.expires_at < now:
            # Delete expired token
            db.delete(token_record)
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=make_error(
                    "expired_token",
                    detail="Password reset token has expired",
                    context={},
                ),
            )
        
        return token_record.user_id
    finally:
        db.close()


def consume_token(*, token: str, db: Session | None = None) -> int:
    """
    Validate and consume a password reset token (one-time use).
    
    Args:
        token: The token string to consume
        db: Optional database session (if None, creates a new one)
        
    Returns:
        The user_id associated with the token
        
    Raises:
        HTTPException 400: If token is invalid or expired
        
    Notes:
        - Validates the token first
        - If valid, deletes it (making it one-time use)
        - Returns the user_id for further processing
        - If db is provided, caller is responsible for committing/rolling back
    """
    should_close = False
    if db is None:
        db = _get_db()
        should_close = True    
    try:
        # Find and validate token
        token_record = db.query(PasswordResetToken).filter(
            PasswordResetToken.token == token
        ).first()
        
        if not token_record:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=make_error(
                    "invalid_token",
                    detail="Invalid or expired password reset token",
                    context={},
                ),
            )
        
        # Check if expired
        now = _now_utc()
        expires_at = _ensure_aware(token_record.expires_at)

        if expires_at < now:
            # Delete expired token
            db.delete(token_record)
            if should_close:
                db.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=make_error(
                    "expired_token",
                    detail="Password reset token has expired",
                    context={},
                ),
            )
        
        # Token is valid - get user_id and delete token (one-time use)
        user_id = token_record.user_id
        db.delete(token_record)
        if should_close:
            db.commit()
        
        return user_id
    except HTTPException:
        if should_close:
            db.rollback()
        raise
    except Exception as e:
        if should_close:
            db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=make_error(
                "token_consumption_failed",
                detail="Failed to process password reset token",
                context={"error": str(e)},
            ),
        )
    finally:
        if should_close:
            db.close()


def delete_token_for_user(*, user_id: int) -> None:
    """
    Delete any existing password reset token for a user.
    
    Args:
        user_id: The ID of the user
        
    Notes:
        - Used when manually revoking tokens
        - Silently succeeds if no token exists
    """
    db = _get_db()
    try:
        token_record = db.query(PasswordResetToken).filter(
            PasswordResetToken.user_id == user_id
        ).first()
        
        if token_record:
            db.delete(token_record)
            db.commit()
    except Exception:
        db.rollback()
        # Silently fail - not critical
    finally:
        db.close()

