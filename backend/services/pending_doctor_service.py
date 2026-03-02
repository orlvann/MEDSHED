# backend/services/pending_doctor_service.py
"""
Pending Doctor Service — handles doctor self-registration workflow.

Workflow:
1. Doctor submits registration -> creates pending_doctor record
2. Admin reviews pending doctors
3. Admin approves -> creates Doctor + User, sends email, deletes pending
4. Admin rejects -> deletes pending record
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.db.session import SessionLocal
from backend.models.orm.doctor import Doctor
from backend.models.orm.pending_doctor import PendingDoctor
from backend.models.orm.user import User
from backend.models.schemas.dto_common import make_error
from backend.models.schemas.pending_doctor import (
    PendingDoctorApprove,
    PendingDoctorList,
    PendingDoctorRead,
    PendingDoctorRegister,
)
from backend.services import email_service, token_service
from backend.utils.security import generate_random_password, hash_password


def _now_utc() -> datetime:
    """Return current UTC timestamp."""
    return datetime.now(timezone.utc)


def _get_db() -> Session:
    """Get database session."""
    return SessionLocal()


def _pending_doctor_to_dto(pending: PendingDoctor) -> PendingDoctorRead:
    """Convert ORM PendingDoctor to DTO."""
    return PendingDoctorRead(
        id=pending.id,
        first_name=pending.first_name,
        last_name=pending.last_name,
        email=pending.email,
        phone_number=pending.phone_number,
        created_at=pending.created_at,
    )


# --------------------------- REGISTER --------------------------------------


def register_doctor(*, payload: PendingDoctorRegister) -> PendingDoctorRead:
    """
    Public endpoint: doctor submits registration request.
    
    Creates a pending_doctor record that admin will review.
    
    Args:
        payload: PendingDoctorRegister with first_name, last_name, email
        
    Returns:
        PendingDoctorRead
        
    Raises:
        HTTPException 409: If email already registered or pending
    """
    db = _get_db()
    try:
        # Check if email already exists in pending_doctors
        existing_pending = db.query(PendingDoctor).filter(
            PendingDoctor.email == payload.email
        ).first()
        if existing_pending:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=make_error(
                    "duplicate_email",
                    detail="This email is already pending approval",
                    context={"email": payload.email},
                ),
            )
        
        # Check if email already exists in doctors table
        existing_doctor = db.query(Doctor).filter(Doctor.email == payload.email).first()
        if existing_doctor:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=make_error(
                    "duplicate_email",
                    detail="This email is already registered",
                    context={"email": payload.email},
                ),
            )
        
        # Check if email already exists in users table
        existing_user = db.query(User).filter(User.email == payload.email).first()
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=make_error(
                    "duplicate_email",
                    detail="This email is already registered",
                    context={"email": payload.email},
                ),
            )
        
        # Create pending doctor record
        pending = PendingDoctor(
            first_name=payload.first_name,
            last_name=payload.last_name,
            email=payload.email,
            phone_number=payload.phone_number,
        )
        
        db.add(pending)
        db.commit()
        db.refresh(pending)
        
        return _pending_doctor_to_dto(pending)
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=make_error("duplicate_email", detail="Email already exists"),
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=make_error("internal_error", detail="Failed to register", context={"error": str(e)}),
        )
    finally:
        db.close()


# --------------------------- LIST ------------------------------------------


def list_pending_doctors(
    *,
    page: int,
    size: int,
) -> PendingDoctorList:
    """
    List pending doctor registrations (admin only).
    
    Args:
        page: Page number (1-based)
        size: Items per page
        
    Returns:
        PendingDoctorList with paginated results
    """
    db = _get_db()
    try:
        query = db.query(PendingDoctor).order_by(PendingDoctor.created_at.desc())
        
        # Get total count
        total = query.count()
        
        # Paginate
        offset = (page - 1) * size
        pending_doctors = query.offset(offset).limit(size).all()
        
        # Map to DTOs
        items = [_pending_doctor_to_dto(pd) for pd in pending_doctors]
        
        return PendingDoctorList(page=page, size=size, total=total, items=items)
    finally:
        db.close()


# --------------------------- COUNT -----------------------------------------


def get_pending_count() -> int:
    """
    Get count of pending doctor registrations (admin only).
    
    Returns:
        Count of pending records
    """
    db = _get_db()
    try:
        return db.query(PendingDoctor).count()
    finally:
        db.close()


# --------------------------- APPROVE ---------------------------------------


def approve_doctor(*, pending_id: int, approval_data: PendingDoctorApprove) -> None:
    """
    Approve a pending doctor registration (admin only).
    
    Creates Doctor and User records, sends welcome email, deletes pending record.
    
    Args:
        pending_id: ID of pending doctor
        approval_data: PendingDoctorApprove with role, user_role, is_head, is_active
        
    Raises:
        HTTPException 404: If pending doctor not found
        HTTPException 409: If email conflict (shouldn't happen normally)
    """
    db = _get_db()
    try:
        # Get pending doctor
        pending = db.query(PendingDoctor).filter(PendingDoctor.id == pending_id).first()
        if not pending:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=make_error("not_found", detail="Pending doctor not found", context={"id": pending_id}),
            )
        
        # Validate user_role
        if approval_data.user_role not in ["doctor", "doctor_admin"]:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=make_error(
                    "invalid_user_role",
                    detail="User role must be 'doctor' or 'doctor_admin'",
                    context={"user_role": approval_data.user_role},
                ),
            )
        
        # Create Doctor record
        doctor = Doctor(
            first_name=pending.first_name,
            last_name=pending.last_name,
            role=approval_data.role,
            is_active=approval_data.is_active,
            is_head=approval_data.is_head,
            email=pending.email,
            phone_number=pending.phone_number,
        )
        
        db.add(doctor)
        db.flush()  # Get doctor ID for user creation
        
        # Create User record
        random_password = generate_random_password()
        user = User(
            email=pending.email,
            role=approval_data.user_role,
            password_hash=hash_password(random_password),
            is_active=False,  # Will be activated when password is set
            doctor_id=doctor.id,
        )
        
        db.add(user)
        db.flush()
        
        # Generate password setup token (use same DB session to avoid locking)
        token = token_service.create_password_reset_token(user_id=user.id, expires_hours=48, db=db)
        
        # Send welcome email
        try:
            email_service.send_password_setup_email(
                email=pending.email,
                token=token,
                first_name=pending.first_name,
                last_name=pending.last_name,
            )
        except Exception as e:
            # Log but don't fail - email can be resent
            import logging
            logging.warning(f"Failed to send password setup email to {pending.email}: {e}")
        
        # Delete pending record
        db.delete(pending)
        
        # Commit all changes
        db.commit()
        
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=make_error("database_conflict", detail="Database constraint violation", context={"error": str(e)}),
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=make_error("internal_error", detail="Failed to approve doctor", context={"error": str(e)}),
        )
    finally:
        db.close()


# --------------------------- REJECT ----------------------------------------


def reject_doctor(*, pending_id: int) -> None:
    """
    Reject a pending doctor registration (admin only).

    Deletes the pending record and sends a rejection notification email.

    Args:
        pending_id: ID of pending doctor

    Raises:
        HTTPException 404: If pending doctor not found
    """
    db = _get_db()
    try:
        pending = db.query(PendingDoctor).filter(PendingDoctor.id == pending_id).first()
        if not pending:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=make_error("not_found", detail="Pending doctor not found", context={"id": pending_id}),
            )

        # Capture info before deleting
        rejected_email = pending.email
        rejected_first = pending.first_name
        rejected_last = pending.last_name

        db.delete(pending)
        db.commit()

        # Send rejection email after successful commit
        try:
            email_service.send_rejection_email(
                to_email=rejected_email,
                first_name=rejected_first,
                last_name=rejected_last,
            )
        except Exception as e:
            import logging
            logging.warning(f"Failed to send rejection email to {rejected_email}: {e}")
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=make_error("internal_error", detail="Failed to reject doctor", context={"error": str(e)}),
        )
    finally:
        db.close()

