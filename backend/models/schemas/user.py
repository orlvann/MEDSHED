from datetime import datetime

from pydantic import BaseModel, EmailStr

from backend.models.common_enums import Role  # "admin" | "doctor"


class UserRead(BaseModel):
    """
    Public representation of the current user (e.g., GET /api/v1/me).
    Role is derived from the token on the backend.
    """

    id: int
    email: EmailStr
    role: Role
    is_active: bool = True
    created_at: datetime | None = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "id": 101,
                "email": "admin@hospital.org",
                "role": "admin",
                "is_active": True,
                "created_at": "2026-01-05T10:22:31Z",
            }
        }
    }
