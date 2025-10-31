# backend/services/doctor_service.py
"""
Doctor Service — CRUD for doctor records.

Manages:
- Create, read, update, delete doctor profiles.
- Prevent invalid actions (e.g., deleting a doctor with active assignments unless forced).
- Apply domain rules (e.g., unique contact info, role flags).

Responsibilities:
- Validate inputs beyond basic schema checks.
- Map Pydantic DTOs ↔ ORM entities.
- Enforce referential integrity and safe deletion strategies.

Notes:
- Stubs only: replace bodies with real DB/ORM calls.
- This service also demonstrates a mock "duplicate email" check that returns
  a 409 Conflict with a standardized error payload via make_error(...).

*****************************************************************************************

Doctor ↔ User coupling (backlog — not implemented yet).

Auto-provision on create (POST /doctors):
- If a unique email is provided: create a linked user (role=doctor, is_active=True, hashed password),
  and link the account to the new doctor record.
- If email is missing: create the Doctor only; UI should indicate that login is unavailable.

On update (PUT /doctors/{id}):
- Email changes propagate to users.email (check uniqueness -> 409 on conflict).
- doctors.is_active DOES NOT affect users.is_active (directory/pool vs. login are separate concerns).

On delete (DELETE /doctors/{id}):
- soft (default): if a linked user exists, disable login (users.is_active=False) and set deactivated_at (if present).
- hard: remove the Doctor; for the linked user either delete the row, or mark deleted_at and set is_active=False
  (policy decision to be made during implementation).

Note:
- Login access is governed solely by users.is_active, not by doctors.is_active.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import HTTPException, status

from backend.models.common_enums import DoctorRole
from backend.models.schemas import DoctorCreate, DoctorList, DoctorPut, DoctorRead
from backend.models.schemas.dto_common import make_error


def _now_utc() -> datetime:
    """Return current UTC timestamp with tzinfo=UTC (DB/audit convention)."""
    return datetime.now(timezone.utc)


# --------------------------- LIST ------------------------------------------


def list_doctors(
    *,
    page: int,
    size: int,
    role: Optional[DoctorRole],
    search: Optional[str],
    is_active: Literal["true", "false", "all"],
) -> DoctorList:
    """
    List doctors with light mock filters and pagination.
    In real impl:
      - Compose DB query with WHERE/ILIKE filters.
      - Compute total count in a separate COUNT(*) or window func.
      - Map ORM entities to DoctorRead DTOs.
    """
    sample = [
        DoctorRead(
            id=1,
            first_name="Anna",
            last_name="Nowak",
            role=DoctorRole.specialist,
            is_active=True,
            is_head=True,
            email="anna.nowak@hospital.pl",
            created_at=_now_utc(),
            updated_at=_now_utc(),
        ),
        DoctorRead(
            id=2,
            first_name="Piotr",
            last_name="Zieliński",
            role=DoctorRole.resident,
            is_active=False,
            is_head=False,
            email="piotr.zielinski@hospital.pl",
            created_at=_now_utc(),
            updated_at=_now_utc(),
        ),
    ]

    # --- mock filtering ---
    items = sample
    if role is not None:
        items = [d for d in items if d.role == role]
    if is_active != "all":
        flag = is_active == "true"
        items = [d for d in items if d.is_active == flag]
    if search:
        q = search.lower()
        items = [
            d for d in items if q in (d.first_name + " " + d.last_name).lower() or (d.email or "").lower().find(q) >= 0
        ]

    total = len(items)
    start = (page - 1) * size
    end = start + size
    return DoctorList(page=page, size=size, total=total, items=items[start:end])


# --------------------------- GET BY ID -------------------------------------


def get_doctor(*, doctor_id: int) -> DoctorRead:
    """
    Get a single doctor by id.
    In real impl: SELECT ... WHERE id=:doctor_id; raise 404 if not found.
    """
    if doctor_id == 1:
        return DoctorRead(
            id=1,
            first_name="Anna",
            last_name="Nowak",
            role=DoctorRole.specialist,
            is_active=True,
            is_head=True,
            email="anna.nowak@hospital.pl",
            created_at=_now_utc(),
            updated_at=_now_utc(),
        )
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=make_error("not_found", context={"entity": "doctor", "doctor_id": doctor_id}),
    )


# --------------------------- CREATE ----------------------------------------


def create_doctor(*, payload: DoctorCreate) -> DoctorRead:
    """
    Create a new doctor.
    Domain example: e-mail must be unique (if provided) → 409 duplicate_email.

    In real impl:
      - Check uniqueness in DB (UNIQUE constraint, or SELECT + handle IntegrityError).
      - INSERT row and return mapped DTO.
    """
    # --- mock uniqueness check ---
    existing_emails = {
        "anna.nowak@hospital.pl",
        "piotr.zielinski@hospital.pl",
    }
    if payload.email and payload.email.lower() in existing_emails:
        # Keep error shape consistent across the API
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=make_error(
                "duplicate_email",
                detail="email already in use",
                context={"email": payload.email},
            ),
        )

    now = _now_utc()
    return DoctorRead(
        id=101,  # In real impl: DB-generated ID (RETURNING id)
        first_name=payload.first_name,
        last_name=payload.last_name,
        role=payload.role,
        is_active=payload.is_active,
        is_head=payload.is_head,
        email=payload.email,
        created_at=now,
        updated_at=now,
    )


# --------------------------- UPDATE (PUT-first) -----------------------------


def put_doctor(*, doctor_id: int, payload: DoctorPut) -> DoctorRead:
    """
    Full replace (PUT-first) of an existing doctor.
    Domain example: if email is changing, enforce uniqueness → 409 duplicate_email.

    In real impl:
      - SELECT for existence; raise 404 if missing.
      - If email changed, enforce UNIQUE.
      - UPDATE and return the new row.
    """
    # --- existence check (mock) ---
    if doctor_id != 1:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=make_error("not_found", context={"entity": "doctor", "doctor_id": doctor_id}),
        )

    # --- mock uniqueness check on update ---
    existing_emails = {
        "anna.nowak@hospital.pl",
        "piotr.zielinski@hospital.pl",
    }
    if payload.email and payload.email.lower() in existing_emails and payload.email.lower() != "anna.nowak@hospital.pl":
        # In the mock, doctor_id=1 has "anna.nowak@hospital.pl" already,
        # so only other existing emails should conflict.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=make_error(
                "duplicate_email",
                detail="email already in use",
                context={"email": payload.email},
            ),
        )

    return DoctorRead(
        id=doctor_id,
        first_name=payload.first_name,
        last_name=payload.last_name,
        role=payload.role,
        is_active=payload.is_active,
        is_head=payload.is_head,
        email=payload.email,
        # In a real impl keep original created_at from DB:
        created_at=_now_utc(),
        updated_at=_now_utc(),
    )


# --------------------------- DELETE ----------------------------------------


def delete_doctor(*, doctor_id: int) -> None:
    """
    Delete (or soft-delete) a doctor.
    In real impl:
      - Check existence; raise 404 if missing.
      - Optional safety checks: ensure no active assignments, or request 'force'.
      - Soft delete (set is_active=False) or hard delete depending on policy.
    """
    if doctor_id != 1:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=make_error("not_found", context={"entity": "doctor", "doctor_id": doctor_id}),
        )
    # Success: return None (204 No Content at router level).
    return None
