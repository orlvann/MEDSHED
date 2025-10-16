from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

from .common import Role


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    # Pydantic v2-safe: Literal zamiast Field(examples=...)
    token_type: Literal["bearer"] = "bearer"
    role: Role
    expires_in: int = Field(..., ge=1, description="Seconds until token expiry")


class UserRead(BaseModel):
    id: int
    email: EmailStr
    role: Role
    is_active: bool = True
    created_at: datetime | None = None
