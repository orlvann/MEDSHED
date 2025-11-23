# backend/services/doctor_service.py
"""
Doctor Service — CRUD for doctor records with real database operations.

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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.db.session import SessionLocal
from backend.models.common_enums import DoctorRole
from backend.models.orm.doctor import Doctor
from backend.models.schemas import DoctorCreate, DoctorList, DoctorPut, DoctorRead
from backend.models.schemas.dto_common import make_error


def _now_utc() -> datetime:
    """Return current UTC timestamp with tzinfo=UTC (DB/audit convention)."""
    return datetime.now(timezone.utc)


def _get_db() -> Session:
    """Get database session."""
    return SessionLocal()


def _doctor_to_dto(doctor: Doctor) -> DoctorRead:
    """Convert ORM Doctor to DTO DoctorRead."""
    return DoctorRead(
        id=doctor.id,
        first_name=doctor.first_name,
        last_name=doctor.last_name,
        role=doctor.role,
        is_active=doctor.is_active,
        is_head=doctor.is_head,
        email=doctor.email,
        created_at=doctor.created_at,
        updated_at=doctor.updated_at,
    )


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
    List doctors with filters and pagination.
    """
    db = _get_db()
    try:
        query = db.query(Doctor)
        
        # Filter by role
        if role:
            query = query.filter(Doctor.role == role)
        
        # Filter by is_active
        if is_active == "true":
            query = query.filter(Doctor.is_active == True)
        elif is_active == "false":
            query = query.filter(Doctor.is_active == False)
        
        # Filter by search (name or email)
        if search:
            search_pattern = f"%{search}%"
            query = query.filter(
                (Doctor.first_name.ilike(search_pattern)) |
                (Doctor.last_name.ilike(search_pattern)) |
                (Doctor.email.ilike(search_pattern))
            )
        
        # Get total count
        total = query.count()
        
        # Paginate
        offset = (page - 1) * size
        doctors = query.order_by(Doctor.id).offset(offset).limit(size).all()
        
        # Map to DTOs
        items = [_doctor_to_dto(doc) for doc in doctors]
        
        return DoctorList(page=page, size=size, total=total, items=items)
    finally:
        db.close()


# --------------------------- GET BY ID -------------------------------------


def get_doctor(*, doctor_id: int) -> DoctorRead:
    """
    Get a single doctor by id.
    Raises 404 if not found.
    """
    db = _get_db()
    try:
        doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
        if not doctor:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=make_error("not_found", detail="Doctor not found", context={"doctor_id": doctor_id}),
            )
        return _doctor_to_dto(doctor)
    finally:
        db.close()


# --------------------------- CREATE ----------------------------------------


def create_doctor(*, payload: DoctorCreate) -> DoctorRead:
    """
    Create a new doctor.
    Validates email uniqueness (if provided).
    """
    db = _get_db()
    try:
        # Check email uniqueness if provided
        if payload.email:
            existing = db.query(Doctor).filter(Doctor.email == payload.email).first()
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=make_error(
                        "duplicate_email",
                        detail="Email already in use",
                        context={"email": payload.email},
                    ),
                )
        
        # Create new doctor
        doctor = Doctor(
            first_name=payload.first_name,
            last_name=payload.last_name,
            role=payload.role,
            is_active=payload.is_active,
            is_head=payload.is_head,
            email=payload.email,
        )
        
        db.add(doctor)
        db.commit()
        db.refresh(doctor)
        
        return _doctor_to_dto(doctor)
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=make_error("database_conflict", detail="Database constraint violation", context={"error": str(e)}),
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=make_error("internal_error", detail="Failed to create doctor", context={"error": str(e)}),
        )
    finally:
        db.close()


# --------------------------- UPDATE (PUT-first) -----------------------------


def put_doctor(*, doctor_id: int, payload: DoctorPut) -> DoctorRead:
    """
    Full replace (PUT) of an existing doctor.
    Validates email uniqueness if changed.
    """
    db = _get_db()
    try:
        # Check if doctor exists
        doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
        if not doctor:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=make_error("not_found", detail="Doctor not found", context={"doctor_id": doctor_id}),
            )
        
        # Check email uniqueness if email is being changed
        if payload.email and payload.email != doctor.email:
            existing = db.query(Doctor).filter(
                Doctor.email == payload.email,
                Doctor.id != doctor_id
            ).first()
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=make_error(
                        "duplicate_email",
                        detail="Email already in use",
                        context={"email": payload.email},
                    ),
                )
        
        # Update all fields
        doctor.first_name = payload.first_name
        doctor.last_name = payload.last_name
        doctor.role = payload.role
        doctor.is_active = payload.is_active
        doctor.is_head = payload.is_head
        doctor.email = payload.email
        
        db.commit()
        db.refresh(doctor)
        
        return _doctor_to_dto(doctor)
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=make_error("database_conflict", detail="Database constraint violation", context={"error": str(e)}),
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=make_error("internal_error", detail="Failed to update doctor", context={"error": str(e)}),
        )
    finally:
        db.close()


# --------------------------- DELETE ----------------------------------------


def delete_doctor(*, doctor_id: int) -> None:
    """
    Delete a doctor.
    Raises 404 if not found.
    """
    db = _get_db()
    try:
        doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
        if not doctor:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=make_error("not_found", detail="Doctor not found", context={"doctor_id": doctor_id}),
            )
        
        db.delete(doctor)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=make_error("internal_error", detail="Failed to delete doctor", context={"error": str(e)}),
        )
    finally:
        db.close()
