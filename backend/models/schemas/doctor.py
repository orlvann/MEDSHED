# backend/models/schemas/doctor.py
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field

from backend.models.common_enums import DoctorRole, UserRole

from .dto_common import PageMeta


class DoctorMini(BaseModel):
    id: int
    first_name: str
    last_name: str


class DoctorCreate(BaseModel):
    """Payload to create a doctor (request body)."""

    first_name: str = Field(..., min_length=1)
    last_name: str = Field(..., min_length=1)
    role: DoctorRole
    is_active: bool = True
    is_head: bool = False
    email: EmailStr  # Required: user account will be auto-created
    user_role: UserRole = Field(..., description="User account role: doctor or doctor_admin")


class DoctorPut(BaseModel):
    """Update PUT-first — full object required."""

    first_name: str = Field(..., min_length=1)
    last_name: str = Field(..., min_length=1)
    role: DoctorRole
    is_active: bool
    is_head: bool
    email: Optional[EmailStr] = Field(None, description="Email address of the doctor")
    user_role: Optional[UserRole] = Field(None, description="User account role: doctor or doctor_admin")
    user_is_active: Optional[bool] = Field(None, description="Whether user can login (users.is_active)")


class DoctorRead(BaseModel):
    """Doctor object returned by the API."""

    id: int
    first_name: str
    last_name: str
    role: DoctorRole
    is_active: bool
    is_head: bool
    email: Optional[EmailStr] = None
    created_at: datetime
    updated_at: datetime
    # User account fields (None if no linked user)
    user_is_active: Optional[bool] = Field(None, description="Whether user can login (from users table)")
    user_role: Optional[UserRole] = Field(None, description="User account role (from users table)")


class DoctorList(PageMeta):
    """Pagination envelope for doctors listing."""

    items: List[DoctorRead] = Field(default_factory=list)
