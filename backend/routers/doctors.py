# backend/routers/doctors.py
from __future__ import annotations

from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, Query, status

from backend.models.schemas import DoctorCreate, DoctorList, DoctorMini, DoctorPut, DoctorRead, DoctorRole
from backend.models.schemas.dto_common import ErrorPayload
from backend.routers.deps import UserCtx, require_admin, require_doctor
from backend.services.doctor_service import (
    create_doctor,
    delete_doctor,
    get_doctor,
    list_doctor_names,
    list_doctors,
    put_doctor,
)

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
    "/api/v1/doctors/names",
    response_model=List[DoctorMini],
    summary="List doctor names (lightweight, accessible by all doctors)",
    operation_id="doctors_names",
)
def doctors_names(
    user: UserCtx = Depends(require_doctor),
):
    """Return id + first_name + last_name for all active doctors.
    Accessible by any authenticated doctor (regular or admin).
    Used for name-mapping in team schedule views and colleague selectors.
    """
    return list_doctor_names()


@router.get(
    "/api/v1/doctors/{doctor_id}",
    response_model=DoctorRead,
    summary="Get a single doctor by ID",
    responses={
        404: {
            "model": ErrorPayload,
            "description": "Doctor not found",
        }
    },
)
def doctors_get(
    doctor_id: int,
    user: UserCtx = Depends(require_admin),
):
    """Get a single doctor by ID."""
    return get_doctor(doctor_id=doctor_id)


@router.post(
    "/api/v1/doctors",
    response_model=DoctorRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new doctor with auto-provisioned user account",
    responses={
        409: {
            "model": ErrorPayload,
            "description": "Email already in use",
        }
    },
)
def doctors_create(
    payload: DoctorCreate,
    user: UserCtx = Depends(require_admin),
):
    """Create a new doctor and linked user account."""
    return create_doctor(payload=payload)


@router.put(
    "/api/v1/doctors/{doctor_id}",
    response_model=DoctorRead,
    summary="Update a doctor (full replace)",
    responses={
        404: {
            "model": ErrorPayload,
            "description": "Doctor not found",
        },
        409: {
            "model": ErrorPayload,
            "description": "Email already in use",
        },
    },
)
def doctors_update(
    doctor_id: int,
    payload: DoctorPut,
    user: UserCtx = Depends(require_admin),
):
    """Update a doctor and their linked user account."""
    return put_doctor(doctor_id=doctor_id, payload=payload)


@router.delete(
    "/api/v1/doctors/{doctor_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a doctor and their linked user account",
    responses={
        404: {
            "model": ErrorPayload,
            "description": "Doctor not found",
        }
    },
)
def doctors_delete(
    doctor_id: int,
    user: UserCtx = Depends(require_admin),
):
    """Delete a doctor and their linked user account."""
    delete_doctor(doctor_id=doctor_id)
