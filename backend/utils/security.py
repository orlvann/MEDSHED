# backend/utils/security.py
"""
Security utilities for password hashing and JWT token management.

Provides:
- hash_password(plain: str) -> str
- verify_password(plain: str, hashed: str) -> bool
- create_access_token(data: dict, expires_delta: timedelta) -> str
- decode_access_token(token: str) -> dict

Policy:
- For ALL newly created users (admin via users router, doctor via auto-provision),
  the system SHOULD set `must_change_password=True` to enforce a first-login reset.
- Use bcrypt for password hashing (strong KDF).
- Never return or log plaintext passwords.
"""

from datetime import datetime, timedelta
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from backend.config import settings

# Password hashing context using bcrypt
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    """
    Hash a plaintext password using bcrypt.

    Args:
        plain: The plaintext password

    Returns:
        The hashed password string
    """
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """
    Verify a plaintext password against a hashed password.

    Args:
        plain: The plaintext password to verify
        hashed: The hashed password to verify against

    Returns:
        True if the password matches, False otherwise
    """
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a JWT access token.

    Args:
        data: Dictionary of claims to encode (should include 'sub' for user ID)
        expires_delta: Optional custom expiration time. If not provided, uses default from config.

    Returns:
        Encoded JWT token string

    Example:
        token = create_access_token(
            data={"sub": str(user_id), "role": "admin", "email": "admin@hospital.org"},
            expires_delta=timedelta(minutes=60)
        )
    """
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update(
        {
            "exp": expire,
            "iat": datetime.utcnow(),
        }
    )

    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> dict:
    """
    Decode and verify a JWT access token.

    Args:
        token: The JWT token string

    Returns:
        Dictionary of decoded claims

    Raises:
        JWTError: If the token is invalid, expired, or malformed
    """
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        return payload
    except JWTError:
        raise


def generate_temp_password(length: int = 12) -> str:
    """
    Generate a temporary password for new users.

    Args:
        length: Length of the password (default: 12)

    Returns:
        A random alphanumeric password

    Note:
        Users should be forced to change this on first login
        (set must_change_password=True).
    """
    import secrets
    import string

    alphabet = string.ascii_letters + string.digits
    password = "".join(secrets.choice(alphabet) for _ in range(length))
    return password


def generate_random_password(length: int = 16) -> str:
    """
    Generate a cryptographically secure random password.
    Used for initial user account creation when admin creates a doctor.

    Args:
        length: Length of the password (default: 16, minimum recommended)

    Returns:
        A random password with letters, digits, and special characters

    Note:
        This password is never shown to the user - they receive a password
        reset token via email to set their own password.
    """
    import secrets
    import string

    # Include special characters for stronger password
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    password = "".join(secrets.choice(alphabet) for _ in range(length))
    return password


def generate_secure_token(num_bytes: int = 48) -> str:
    """
    Generate a cryptographically secure URL-safe token.
    Used for password reset tokens.

    Args:
        num_bytes: Number of random bytes to use (default: 48, produces ~64 chars)

    Returns:
        URL-safe base64-encoded random token string (64+ characters)

    Example:
        token = generate_secure_token()  # Returns: "xF3k9Lm2nQ8pR7wV..."

    Security:
        - Uses secrets module (cryptographically secure)
        - URL-safe (can be used in links)
        - Long enough to prevent brute force (2^384 possibilities for 48 bytes)
    """
    import secrets

    return secrets.token_urlsafe(num_bytes)
