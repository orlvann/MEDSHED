# backend/models/schemas/pending_doctor.py
"""
PendingDoctor DTOs — request/response schemas for doctor registration workflow.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field

from backend.models.common_enums import DoctorRole, UserRole
from backend.models.schemas.dto_common import PageMeta


class PendingDoctorRegister(BaseModel):
    """
    Public registration request from a prospective doctor.
    Used by: POST /api/v1/doctors/register (public endpoint, no auth)
    """

    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    phone_number: Optional[str] = None

    model_config = {
        "json_schema_extra": {
            "example": {"first_name": "John", "last_name": "Smith", "email": "john.smith@example.com"}
        }
    }


class PendingDoctorRead(BaseModel):
    """
    Pending doctor record (admin view).
    """

    id: int
    first_name: str
    last_name: str
    email: EmailStr
    phone_number: Optional[str] = None
    created_at: datetime

    model_config = {
        "json_schema_extra": {
            "example": {
                "id": 42,
                "first_name": "John",
                "last_name": "Smith",
                "email": "john.smith@example.com",
                "created_at": "2025-01-20T10:30:00Z",
            }
        }
    }


class PendingDoctorList(PageMeta):
    """Pagination envelope for pending doctors."""

    items: List[PendingDoctorRead] = Field(default_factory=list)


class PendingDoctorApprove(BaseModel):
    """
    Admin approval data for a pending doctor.
    Specifies the doctor and user details that will be created upon approval.
    """

    role: DoctorRole = Field(..., description="Doctor role: specialist or resident")
    user_role: UserRole = Field(..., description="User role: doctor or doctor_admin")
    is_head: bool = Field(False, description="Whether this doctor is head of department")
    is_active: bool = Field(True, description="Whether doctor is active in scheduling")

    model_config = {
        "json_schema_extra": {
            "example": {"role": "resident", "user_role": "doctor", "is_head": False, "is_active": True}
        }
    }
