from datetime import datetime

from pydantic import BaseModel, EmailStr

# Import shared enums & error shape from common
from .common import Role  # reuse canonical Role


class LoginRequest(BaseModel):
    """Login form payload."""

    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """JWT response returned on successful login."""

    access_token: str
    token_type: str = "bearer"
    role: Role
    expires_in: int  # seconds


class UserRead(BaseModel):
    """Public representation of the current user."""

    id: int
    email: EmailStr
    role: Role
    is_active: bool
    created_at: datetime | None = None
