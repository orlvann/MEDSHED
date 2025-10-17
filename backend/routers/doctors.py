from fastapi import APIRouter, Body, Path, Query, status

from backend.models.schemas import (
    DoctorCreate,
    DoctorList,
    DoctorRead,
    DoctorRole,
    DoctorUpdate,
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
    search: str | None = Query(None, description="Search by name/email"),
):
    """
    Stub: fetch a page of doctors + total count.
    Replace with: doctor_service.list(page=page, size=size, role=role, search=search).
    """
    items = [
        {
            "id": 1,
            "first_name": "Anna",
            "last_name": "Nowak",
            "role": DoctorRole.SPECIALIST,
            "is_head": True,
            "email": "anna.nowak@hospital.pl",
            "color": "#8ecae6",
        },
        {
            "id": 2,
            "first_name": "Piotr",
            "last_name": "Zieliński",
            "role": DoctorRole.RESIDENT,
            "is_head": False,
            "email": "piotr.zielinski@hospital.pl",
            "color": "#ffd166",
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
    return {"id": 101, **payload.model_dump()}


@router.get(
    "/api/v1/doctors/{doctor_id}",
    response_model=DoctorRead,
    summary="Get doctor by id",
)
def get_doctor(doctor_id: int = Path(..., ge=1)):
    """
    Stub: fetch a single doctor by id.
    Replace with: doctor_service.get(doctor_id).
    """
    return {
        "id": doctor_id,
        "first_name": "Ewa",
        "last_name": "Kowalska",
        "role": DoctorRole.SPECIALIST,
        "is_head": False,
        "email": "ewa.kowalska@hospital.pl",
        "color": "#90be6d",
    }


@router.patch(
    "/api/v1/doctors/{doctor_id}",
    response_model=DoctorRead,
    summary="Update doctor (partial)",
)
def update_doctor(
    doctor_id: int = Path(..., ge=1),
    payload: DoctorUpdate = Body(...),
):
    """
    Stub: partial update of the doctor.
    Replace with: doctor_service.update(doctor_id, payload).
    """
    base = {
        "id": doctor_id,
        "first_name": "Ewa",
        "last_name": "Kowalska",
        "role": DoctorRole.SPECIALIST,
        "is_head": False,
        "email": "ewa.kowalska@hospital.pl",
        "color": "#90be6d",
    }
    # Merge only fields provided by client
    base.update(payload.model_dump(exclude_unset=True))
    return base


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
