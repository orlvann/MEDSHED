# backend/routers/doctors.py
from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query

from backend.models.schemas import DoctorList, DoctorRole
from backend.routers.deps import UserCtx, require_admin
from backend.services.doctor_service import list_doctors

router = APIRouter(tags=["doctors"])


@router.get(
    "/api/v1/doctors",
    response_model=DoctorList,
    summary="List doctors (pagination + optional filters)",
    operation_id="doctors_list",
)
def doctors_list(
    user: UserCtx = Depends(require_admin),
    page: int = Query(1, ge=1, description="1-based page number"),
    size: int = Query(50, ge=1, le=200, description="Page size"),
    role: Optional[DoctorRole] = Query(None, description="Filter by role"),
    search: Optional[str] = Query(None, description="Search by name/email"),
    is_active: Literal["true", "false", "all"] = Query("all", description='Active flag: "true" | "false" | "all"'),
    user_role: Optional[str] = Query(None, description="Filter by user role (doctor/doctor_admin)"),
    user_is_active: Optional[str] = Query(None, description="Filter by user login status"),
    is_head: Optional[str] = Query(None, description="Filter by head of department status"),
):
    # NOTE:
    # user_role / user_is_active / is_head are accepted for FE compatibility,
    # but are currently NOT passed to the service unless/ until doctor_service supports them.
    return list_doctors(
        page=page,
        size=size,
        role=role,
        search=search,
        is_active=is_active,
    )
