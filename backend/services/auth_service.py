"""
Auth Service — login, tokens, roles.

Purpose:
- Handle user login and authentication.
- Generate and verify JWT tokens.
- Enforce role-based access (admin vs doctor).

Responsibilities:
- Validate credentials, hash/verify passwords.
- Issue short-lived access tokens (and optional refresh tokens).
- Decode/verify tokens and expose identity + roles to routers/services.
- Centralize auth-related errors and security policies.

Depends on:
- ORM: User
- config.py (JWT secret, token TTL)
- Password hashing (passlib)

Notes:
- This service is called by routers; it should not import FastAPI objects.
- Keep token payload minimal and privacy-safe.
"""

from datetime import timedelta
from typing import Optional

from jose import JWTError
from sqlalchemy.orm import Session

from backend.config import settings
from backend.models.orm.user import User
from backend.models.schemas.auth import TokenResponse
from backend.utils.security import create_access_token, decode_access_token, verify_password


class AuthError(Exception):
    """Base exception for authentication errors."""

    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(detail)


class InvalidCredentialsError(AuthError):
    """Raised when login credentials are invalid."""

    def __init__(self):
        super().__init__("invalid_credentials", "Invalid email or password")


class InactiveUserError(AuthError):
    """Raised when user account is inactive."""

    def __init__(self):
        super().__init__("inactive_user", "User account is inactive")


class InvalidTokenError(AuthError):
    """Raised when JWT token is invalid or expired."""

    def __init__(self):
        super().__init__("invalid_token", "Invalid or expired token")


def login(db: Session, email: str, password: str) -> TokenResponse:
    """
    Authenticate user and return JWT token.

    Args:
        db: Database session
        email: User email
        password: Plain text password

    Returns:
        TokenResponse with access_token and token_type

    Raises:
        InvalidCredentialsError: If email or password is incorrect
        InactiveUserError: If user account is not active
    """
    # Find user by email
    user = db.query(User).filter(User.email == email).first()

    if not user:
        raise InvalidCredentialsError()

    # Verify password
    if not verify_password(password, user.password_hash):
        raise InvalidCredentialsError()

    # Check if user is active
    if not user.is_active:
        raise InactiveUserError()

    # Create JWT token
    token_data = {
        "sub": str(user.id),
        "email": user.email,
        "role": user.role.value,
    }

    expires_delta = timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(data=token_data, expires_delta=expires_delta)

    return TokenResponse(access_token=access_token, token_type="Bearer")


def get_user_from_token(db: Session, token: str) -> User:
    """
    Decode JWT token and retrieve user from database.

    Args:
        db: Database session
        token: JWT token string

    Returns:
        User object

    Raises:
        InvalidTokenError: If token is invalid or user not found
    """
    try:
        payload = decode_access_token(token)
    except JWTError:
        raise InvalidTokenError()

    # Extract user ID from 'sub' claim
    user_id_str: Optional[str] = payload.get("sub")
    if not user_id_str:
        raise InvalidTokenError()

    try:
        user_id = int(user_id_str)
    except ValueError:
        raise InvalidTokenError()

    # Retrieve user from database
    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        raise InvalidTokenError()

    # Check if user is still active
    if not user.is_active:
        raise InactiveUserError()

    return user
