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

from pydantic import BaseModel, EmailStr

from backend.models.common_enums import Role  # "admin" | "doctor"


class UserRead(BaseModel):
    """
    Public representation of the current user (e.g., GET /api/v1/auth/me).
    Role is derived from the token on the backend.
    Timestamps are UTC ISO-8601 (with 'Z').
    """

    id: int
    email: EmailStr
    role: Role
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None  # keep parity with other DTOs using created_at/updated_at

    model_config = {
        "json_schema_extra": {
            "example": {
                "id": 101,
                "email": "admin@hospital.org",
                "role": "admin",
                "is_active": True,
                "created_at": "2026-01-05T10:22:31Z",
                "updated_at": "2026-01-12T15:44:10Z",
            }
        }
    }
