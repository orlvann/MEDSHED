from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Body, Path, Query, status

from backend.models.schemas import (
    DoctorCreate,
    DoctorList,
    DoctorPut,
    DoctorRead,
    DoctorRole,
)

router = APIRouter(tags=["doctors"])


@router.get(
    "/api/v1/doctors",
    response_model=DoctorList,
    summary="List doctors (pagination + optional filters)",
)
def list_doctors(
    page: int = Query(1, ge=1, description="1-based page number"),
    size: int = Query(50, ge=1, le=200, description="Page size"),
    role: DoctorRole | None = Query(None, description="Filter by role"),
    search: str | None = Query(None, description="Search by name"),
    is_active: Literal["true", "false", "all"] = Query(
        "all", description='Filter by active flag: "true" | "false" | "all"'
    ),
):
    """
    Stub: fetch a page of doctors + total count.
    Replace with: doctor_service.list(page, size, role, search, is_active).
    """
    items = [
        {
            "id": 1,
            "first_name": "Anna",
            "last_name": "Nowak",
            "role": DoctorRole.specialist,
            "is_active": True,
            "is_head": True,
            "email": "anna.nowak@hospital.pl",
            "created_at": "2026-01-05T10:22:31Z",
            "updated_at": "2026-01-05T10:22:31Z",
        },
        {
            "id": 2,
            "first_name": "Piotr",
            "last_name": "Zieliński",
            "role": DoctorRole.resident,
            "is_active": False,
            "is_head": False,
            "email": "piotr.zielinski@hospital.pl",
            "created_at": "2026-01-06T09:10:00Z",
            "updated_at": "2026-01-06T09:10:00Z",
        },
    ]
    # In a real impl, slice/filter by `page/size/role/search` and compute `total`.
    return {"items": items, "page": page, "size": size, "total": len(items)}


@router.post(
    "/api/v1/doctors",
    response_model=DoctorRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create doctor",
)
def create_doctor(payload: DoctorCreate = Body(...)):
    """
    Stub: create and return the new doctor.
    Replace with: doctor_service.create(payload).
    """
    now = datetime.now(timezone.utc)
    return {
        "id": 101,
        **payload.model_dump(),
        "created_at": now,
        "updated_at": now,
    }


@router.put(
    "/api/v1/doctors/{doctor_id}",
    response_model=DoctorRead,
    summary="Update doctor (PUT-first, full object)",
)
def put_doctor(
    doctor_id: int = Path(..., ge=1),
    payload: DoctorPut = Body(...),
):
    """
    Stub: full replace of the doctor (PUT-first).
    Replace with: doctor_service.put(doctor_id, payload).
    """
    now = datetime.now(timezone.utc)
    return {
        "id": doctor_id,
        **payload.model_dump(),
        "created_at": "2026-01-05T10:22:31Z",
        "updated_at": now,
    }


@router.delete(
    "/api/v1/doctors/{doctor_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete doctor",
)
def delete_doctor(doctor_id: int = Path(..., ge=1)):
    """
    Stub: delete (or soft-delete) the doctor.
    Replace with: doctor_service.delete(doctor_id).
    """
    return None
