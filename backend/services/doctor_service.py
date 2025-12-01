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


def _doctor_to_dto(doctor: Doctor, db: Session) -> DoctorRead:
    """Convert ORM Doctor to DTO DoctorRead with linked user information."""
    from backend.models.orm.user import User
    
    # Find linked user account
    linked_user = db.query(User).filter(User.doctor_id == doctor.id).first()
    
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
        user_is_active=linked_user.is_active if linked_user else None,
        user_role=linked_user.role if linked_user else None,
    )


# --------------------------- LIST ------------------------------------------


def list_doctors(
    *,
    page: int,
    size: int,
    role: Optional[DoctorRole],
    search: Optional[str],
    is_active: Literal["true", "false", "all"],
    user_role: Optional[str] = None,
    user_is_active: Optional[str] = None,
    is_head: Optional[str] = None,
) -> DoctorList:
    """
    List doctors with filters and pagination.
    """
    from backend.models.orm.user import User
    
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
        
        # Filter by is_head (handle both boolean and SQLite integer representation)
        if is_head == "true":
            query = query.filter((Doctor.is_head == True) | (Doctor.is_head == 1))
        elif is_head == "false":
            query = query.filter((Doctor.is_head == False) | (Doctor.is_head == 0))
        
        # Filter by user_role (requires join with users table)
        if user_role and user_role != "all":
            query = query.join(User, User.doctor_id == Doctor.id).filter(User.role == user_role)
        
        # Filter by user_is_active (requires join with users table if not already joined)
        if user_is_active and user_is_active != "all":
            # Check if we already joined
            if user_role and user_role != "all":
                # Already joined, just add filter
                if user_is_active == "true":
                    query = query.filter(User.is_active == True)
                elif user_is_active == "false":
                    query = query.filter(User.is_active == False)
            else:
                # Need to join
                if user_is_active == "true":
                    query = query.join(User, User.doctor_id == Doctor.id).filter(User.is_active == True)
                elif user_is_active == "false":
                    query = query.join(User, User.doctor_id == Doctor.id).filter(User.is_active == False)
        
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
        items = [_doctor_to_dto(doc, db) for doc in doctors]
        
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
        return _doctor_to_dto(doctor, db)
    finally:
        db.close()


# --------------------------- CREATE ----------------------------------------


def create_doctor(*, payload: DoctorCreate) -> DoctorRead:
    """
    Create a new doctor with auto-provisioned user account.
    
    Steps:
    1. Validate email uniqueness across doctors and users tables
    2. Create Doctor record
    3. Create User record with random password and is_active=False
    4. Generate password reset token
    5. Send password setup email
    6. Return DoctorRead with user info
    """
    from backend.models.orm.user import User
    from backend.services import email_service, token_service
    from backend.utils.security import generate_random_password, hash_password
    
    db = _get_db()
    try:
        # Check email uniqueness in doctors table
        existing_doctor = db.query(Doctor).filter(Doctor.email == payload.email).first()
        if existing_doctor:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=make_error(
                    "duplicate_email",
                    detail="Email already in use by another doctor",
                    context={"email": payload.email},
                ),
            )
        
        # Check email uniqueness in users table
        existing_user = db.query(User).filter(User.email == payload.email).first()
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=make_error(
                    "duplicate_email",
                    detail="Email already in use by another user",
                    context={"email": payload.email},
                ),
            )
        
        # Validate user_role (must be doctor or doctor_admin)
        if payload.user_role not in ["doctor", "doctor_admin"]:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=make_error(
                    "invalid_user_role",
                    detail="User role must be 'doctor' or 'doctor_admin'",
                    context={"user_role": payload.user_role},
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
        
        # Create user account
        random_password = generate_random_password()
        user = User(
            email=payload.email,
            role=payload.user_role,
            password_hash=hash_password(random_password),
            is_active=False,  # Will be activated when password is set
            doctor_id=doctor.id,
        )
        
        db.add(user)
        db.commit()
        db.refresh(user)
        
        # Generate password reset token
        token = token_service.create_password_reset_token(user_id=user.id, expires_hours=48)
        
        # Send password setup email
        try:
            email_service.send_password_setup_email(
                email=payload.email,
                token=token,
                first_name=payload.first_name,
                last_name=payload.last_name,
            )
        except Exception as e:
            # Log but don't fail - email is not critical for account creation
            print(f"Warning: Failed to send password setup email: {e}")
        
        return _doctor_to_dto(doctor, db)
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
    Updates doctor record and linked user account if applicable.
    
    Handles:
    - Email changes (validates uniqueness, updates user.email)
    - user_role changes (updates user.role)
    - user_is_active changes (updates user.is_active)
    - Creates user if email provided but no user exists
    """
    from backend.models.orm.user import User
    from backend.services import email_service, token_service
    from backend.utils.security import generate_random_password, hash_password
    
    db = _get_db()
    try:
        # Check if doctor exists
        doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
        if not doctor:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=make_error("not_found", detail="Doctor not found", context={"doctor_id": doctor_id}),
            )
        
        # Find linked user
        linked_user = db.query(User).filter(User.doctor_id == doctor_id).first()
        
        # Check email uniqueness if email is being changed
        if payload.email and payload.email != doctor.email:
            # Check in doctors table
            existing_doctor = db.query(Doctor).filter(
                Doctor.email == payload.email,
                Doctor.id != doctor_id
            ).first()
            if existing_doctor:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=make_error(
                        "duplicate_email",
                        detail="Email already in use by another doctor",
                        context={"email": payload.email},
                    ),
                )
            
            # Check in users table (excluding linked user)
            existing_user = db.query(User).filter(
                User.email == payload.email,
                User.id != (linked_user.id if linked_user else -1)
            ).first()
            if existing_user:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=make_error(
                        "duplicate_email",
                        detail="Email already in use by another user",
                        context={"email": payload.email},
                    ),
                )
        
        # Update doctor fields
        doctor.first_name = payload.first_name
        doctor.last_name = payload.last_name
        doctor.role = payload.role
        doctor.is_active = payload.is_active
        doctor.is_head = payload.is_head
        doctor.email = payload.email
        
        # Handle user account updates
        if linked_user:
            # Update existing user
            if payload.email:
                linked_user.email = payload.email
            if payload.user_role:
                if payload.user_role not in ["doctor", "doctor_admin"]:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail=make_error(
                            "invalid_user_role",
                            detail="User role must be 'doctor' or 'doctor_admin'",
                            context={"user_role": payload.user_role},
                        ),
                    )
                linked_user.role = payload.user_role
            if payload.user_is_active is not None:
                linked_user.is_active = payload.user_is_active
        elif payload.email:
            # No user exists but email provided - create user
            user_role = payload.user_role if payload.user_role else "doctor"
            if user_role not in ["doctor", "doctor_admin"]:
                user_role = "doctor"
            
            random_password = generate_random_password()
            new_user = User(
                email=payload.email,
                role=user_role,
                password_hash=hash_password(random_password),
                is_active=False,
                doctor_id=doctor.id,
            )
            
            db.add(new_user)
            db.commit()
            db.refresh(new_user)
            
            # Generate token and send email
            token = token_service.create_password_reset_token(user_id=new_user.id, expires_hours=48)
            try:
                email_service.send_password_setup_email(
                    email=payload.email,
                    token=token,
                    first_name=payload.first_name,
                    last_name=payload.last_name,
                )
            except Exception as e:
                print(f"Warning: Failed to send password setup email: {e}")
        
        db.commit()
        db.refresh(doctor)
        
        return _doctor_to_dto(doctor, db)
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
    Delete a doctor and their linked user account.
    Raises 404 if not found.
    """
    from backend.models.orm.user import User
    
    db = _get_db()
    try:
        doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
        if not doctor:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=make_error("not_found", detail="Doctor not found", context={"doctor_id": doctor_id}),
            )
        
        # Delete linked user account if exists
        linked_user = db.query(User).filter(User.doctor_id == doctor_id).first()
        if linked_user:
            db.delete(linked_user)
        
        # Delete doctor
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
