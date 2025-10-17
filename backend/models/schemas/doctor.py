from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field

from .common import DoctorRole, PageMeta


class DoctorCreate(BaseModel):
    """Payload to create a doctor (request body)."""

    first_name: str = Field(..., min_length=1)
    last_name: str = Field(..., min_length=1)
    role: DoctorRole
    is_head: bool = False
    email: Optional[EmailStr] = None
    color: Optional[str] = Field(None, description="HEX or named color used by the UI calendar")


class DoctorUpdate(BaseModel):
    """Partial update; all fields optional."""

    first_name: Optional[str] = Field(None, min_length=1)
    last_name: Optional[str] = Field(None, min_length=1)
    role: Optional[DoctorRole] = None
    is_head: Optional[bool] = None
    email: Optional[EmailStr] = None
    color: Optional[str] = None


class DoctorRead(BaseModel):
    """Doctor object returned by the API."""

    id: int
    first_name: str
    last_name: str
    role: DoctorRole
    is_head: bool
    email: Optional[EmailStr] = None
    color: Optional[str] = None


class DoctorList(PageMeta):
    """Pagination envelope for doctors listing."""

    # Use default_factory to avoid mutable default list bugs
    items: List[DoctorRead] = Field(default_factory=list)
