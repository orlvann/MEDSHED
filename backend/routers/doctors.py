# backend/routers/doctors.py


from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Body, Depends, Path, Query, status

from backend.models.schemas import (
    DoctorCreate,
    DoctorList,
    DoctorPut,
    DoctorRead,
    DoctorRole,
)
from backend.routers.deps import UserCtx, require_admin
from backend.services.doctor_service import (
    create_doctor,
    delete_doctor,
    get_doctor,
    list_doctors,
    put_doctor,
)

router = APIRouter(tags=["doctors"])

# Semantics:
# - doctors.is_active controls directory/scheduling pool ONLY (not login).
# - Linked user login is governed by users.is_active; newly created users (via auto-provision)
#   should also set must_change_password=True by default (first-login policy).
# - Email updates propagate to users.email (409 on duplicates). Soft/hard delete affects linked user
#   per policy (see doctor_service).


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
    return list_doctors(
        page=page, 
        size=size, 
        role=role, 
        search=search, 
        is_active=is_active,
        user_role=user_role,
        user_is_active=user_is_active,
        is_head=is_head,
    )


@router.get(
    "/api/v1/doctors/{doctor_id}",
    response_model=DoctorRead,
    summary="Get doctor by id",
    operation_id="doctors_get",
)
def doctors_get(
    user: UserCtx = Depends(require_admin),
    doctor_id: int = Path(..., ge=1),
):
    return get_doctor(doctor_id=doctor_id)


@router.post(
    "/api/v1/doctors",
    response_model=DoctorRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create doctor",
    operation_id="doctors_create",
)
def doctors_create(
    user: UserCtx = Depends(require_admin),
    payload: DoctorCreate = Body(...),
):
    return create_doctor(payload=payload)


@router.put(
    "/api/v1/doctors/{doctor_id}",
    response_model=DoctorRead,
    summary="Update doctor (PUT-first, full object)",
    operation_id="doctors_update",
)
def doctors_update(
    user: UserCtx = Depends(require_admin),
    doctor_id: int = Path(..., ge=1),
    payload: DoctorPut = Body(...),
):
    return put_doctor(doctor_id=doctor_id, payload=payload)


@router.delete(
    "/api/v1/doctors/{doctor_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete doctor",
    operation_id="doctors_delete",
)
def doctors_delete(
    user: UserCtx = Depends(require_admin),
    doctor_id: int = Path(..., ge=1),
):
    delete_doctor(doctor_id=doctor_id)
    return None
