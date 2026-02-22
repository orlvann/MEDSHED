# backend/models/schemas/user.py
"""
User DTOs — scope and direction.

Current:
- UserRead: public self-view for /auth/me (id, email, role, is_active, created_at, updated_at).
  (No password fields in responses; never expose plaintext passwords.)

First-login policy (applies to all new accounts):
- Newly created users (admins via users router; doctors via auto-provision)
  SHOULD have `must_change_password=True` set on creation (server-side policy).
  The actual interactive password-change flow is handled by the auth layer.

Future (admin-only DTOs):
- UserAdminCreateRequest / UserAdminCreateResponse / UserAdminRead for
  POST /api/v1/users/admins (admin-only).
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field

from backend.models.common_enums import UserRole  # "admin" | "doctor" | "doctor_admin"

from .dto_common import PageMeta


class UserRead(BaseModel):
    """
    Public representation of the current user (e.g., GET /api/v1/auth/me).
    UserRole is derived from the token on the backend.
    Timestamps are UTC ISO-8601 (with 'Z').
    """

    id: int
    email: EmailStr
    role: UserRole
    is_active: bool = True
    first_name: Optional[str] = None  # From linked Doctor if exists
    last_name: Optional[str] = None   # From linked Doctor if exists
    phone_number: Optional[str] = None  # From linked Doctor if exists
    created_at: datetime | None = None
    updated_at: datetime | None = None  # keep parity with other DTOs using created_at/updated_at

    model_config = {
        "json_schema_extra": {
            "example": {
                "id": 101,
                "email": "admin@hospital.org",
                "role": "admin",
                "is_active": True,
                "first_name": "John",
                "last_name": "Doe",
                "created_at": "2026-01-05T10:22:31Z",
                "updated_at": "2026-01-12T15:44:10Z",
            }
        }
    }


# Admin Users Management Schemas


class UserAdminCreate(BaseModel):
    """Create a new admin user."""

    email: EmailStr


class UserAdminUpdate(BaseModel):
    """Update an existing admin user."""

    email: Optional[EmailStr] = None
    is_active: Optional[bool] = None


class UserAdminRead(BaseModel):
    """Admin user details (extended from UserRead)."""

    id: int
    email: EmailStr
    role: UserRole
    is_active: bool
    created_at: datetime
    updated_at: datetime


class UserAdminList(PageMeta):
    """Pagination envelope for admin users listing."""

    items: List[UserAdminRead] = Field(default_factory=list)


# Profile Update Schemas


class ProfileUpdate(BaseModel):
    """Update current user's profile."""

    first_name: Optional[str] = Field(None, min_length=1, max_length=100)
    last_name: Optional[str] = Field(None, min_length=1, max_length=100)
    phone_number: Optional[str] = Field(None, max_length=20)


class ChangePasswordRequest(BaseModel):
    """Request to change password."""

    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8)


class ChangePasswordResponse(BaseModel):
    """Response after successful password change."""

    message: str
