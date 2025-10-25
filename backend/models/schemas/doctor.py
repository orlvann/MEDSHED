from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field

from .common import DoctorRole, PageMeta


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
    email: Optional[EmailStr] = None


class DoctorPut(BaseModel):
    """Update PUT-first — full object required."""

    first_name: str = Field(..., min_length=1)
    last_name: str = Field(..., min_length=1)
    role: DoctorRole
    is_active: bool
    is_head: bool
    email: Optional[EmailStr] = None


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


class DoctorList(PageMeta):
    """Pagination envelope for doctors listing."""

    # Use default_factory to avoid mutable default list bugs
    items: List[DoctorRead] = Field(default_factory=list)
