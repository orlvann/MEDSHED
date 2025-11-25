# backend/services/admin_user_service.py
"""
Admin User Service — CRUD for admin users (role='admin' only).

Manages:
- List, create, update, delete admin users
- Auto-generate password and send setup email
- Link admin users to doctor records (optional)

Security:
- Only manages users with role='admin' (not doctor/doctor_admin)
- All operations require admin privileges (enforced in router)
- New admins start with is_active=False until password is set

Notes:
- Doctor users are created via doctor_service auto-provision, not here
- Admin users can optionally be linked to a doctor record
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from backend.db.session import SessionLocal
from backend.models.orm.doctor import Doctor
from backend.models.orm.user import User
from backend.models.schemas.dto_common import make_error
from backend.models.schemas.user import UserAdminCreate, UserAdminList, UserAdminRead, UserAdminUpdate
from backend.services import email_service, token_service
from backend.utils.security import generate_random_password, hash_password


def _now_utc() -> datetime:
    """Return current UTC timestamp with tzinfo=UTC."""
    return datetime.now(timezone.utc)


def _get_db() -> Session:
    """Get database session."""
    return SessionLocal()


def _user_to_admin_dto(user: User) -> UserAdminRead:
    """Convert ORM User to DTO UserAdminRead."""
    return UserAdminRead(
        id=user.id,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


# --------------------------- LIST ------------------------------------------


def list_admin_users(
    *,
    page: int,
    size: int,
    search: Optional[str],
    is_active: str = "all",
) -> UserAdminList:
    """
    List admin users (role='admin' only) with filters and pagination.
    
    Args:
        page: Page number (1-based)
        size: Number of items per page
        search: Optional search filter for email
        
    Returns:
        UserAdminList with paginated results
    """
    db = _get_db()
    try:
        query = db.query(User).filter(User.role == "admin")
        
        # Filter by search (email)
        if search:
            search_pattern = f"%{search}%"
            query = query.filter(User.email.ilike(search_pattern))
        
        # Filter by is_active
        if is_active == "true":
            query = query.filter(User.is_active == True)
        elif is_active == "false":
            query = query.filter(User.is_active == False)
        
        # Get total count
        total = query.count()
        
        # Paginate
        offset = (page - 1) * size
        users = query.order_by(User.id).offset(offset).limit(size).all()
        
        # Map to DTOs
        items = [_user_to_admin_dto(user) for user in users]
        
        return UserAdminList(page=page, size=size, total=total, items=items)
    finally:
        db.close()


# --------------------------- GET BY ID -------------------------------------


def get_admin_user(*, user_id: int) -> UserAdminRead:
    """
    Get a single admin user by id.
    
    Args:
        user_id: The user ID
        
    Returns:
        UserAdminRead
        
    Raises:
        HTTPException 404: If user not found or not an admin
    """
    db = _get_db()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=make_error("not_found", detail="User not found", context={"user_id": user_id}),
            )
        
        if user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=make_error("not_found", detail="User is not an admin", context={"user_id": user_id}),
            )
        
        return _user_to_admin_dto(user)
    finally:
        db.close()


# --------------------------- CREATE ----------------------------------------


def create_admin_user(*, payload: UserAdminCreate) -> UserAdminRead:
    """
    Create a new admin user.
    
    Steps:
    1. Validate email uniqueness
    2. Validate doctor_id if provided
    3. Create User with role='admin', is_active=False, random password
    4. Generate password reset token
    5. Send password setup email
    6. Return UserAdminRead
    
    Args:
        payload: UserAdminCreate with email and optional doctor_id
        
    Returns:
        UserAdminRead
        
    Raises:
        HTTPException 409: If email already exists
        HTTPException 404: If doctor_id provided but doctor not found
    """
    db = _get_db()
    try:
        # Check email uniqueness
        existing = db.query(User).filter(User.email == payload.email).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=make_error(
                    "duplicate_email",
                    detail="Email already in use",
                    context={"email": payload.email},
                ),
            )
        
        # Create user
        random_password = generate_random_password()
        user = User(
            email=payload.email,
            role="admin",
            password_hash=hash_password(random_password),
            is_active=False,  # Will be activated when password is set
            doctor_id=None,  # Admins are not linked to doctors
        )
        
        db.add(user)
        db.commit()
        db.refresh(user)
        
        # Generate password reset token
        token = token_service.create_password_reset_token(user_id=user.id, expires_hours=48)
        
        # Send password setup email
        try:
            email_service.send_admin_created_email(
                email=payload.email,
                token=token,
            )
        except Exception as e:
            print(f"Warning: Failed to send admin password setup email: {e}")
        
        return _user_to_admin_dto(user)
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=make_error("internal_error", detail="Failed to create admin user", context={"error": str(e)}),
        )
    finally:
        db.close()


# --------------------------- UPDATE ----------------------------------------


def update_admin_user(*, user_id: int, payload: UserAdminUpdate) -> UserAdminRead:
    """
    Update an existing admin user.
    
    Args:
        user_id: The user ID
        payload: UserAdminUpdate with optional fields to update
        
    Returns:
        UserAdminRead
        
    Raises:
        HTTPException 404: If user not found or not an admin
        HTTPException 409: If email already in use
    """
    db = _get_db()
    try:
        # Get user
        user = db.query(User).filter(User.id == user_id).first()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=make_error("not_found", detail="User not found", context={"user_id": user_id}),
            )
        
        if user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=make_error("not_found", detail="User is not an admin", context={"user_id": user_id}),
            )
        
        # Update email if provided
        if payload.email and payload.email != user.email:
            existing = db.query(User).filter(
                User.email == payload.email,
                User.id != user_id
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
            user.email = payload.email
        
        # Update is_active if provided
        if payload.is_active is not None:
            user.is_active = payload.is_active
        
        db.commit()
        db.refresh(user)
        
        return _user_to_admin_dto(user)
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=make_error("internal_error", detail="Failed to update admin user", context={"error": str(e)}),
        )
    finally:
        db.close()


# --------------------------- DELETE ----------------------------------------


def delete_admin_user(*, user_id: int) -> None:
    """
    Delete an admin user.
    
    Args:
        user_id: The user ID
        
    Raises:
        HTTPException 404: If user not found or not an admin
    """
    db = _get_db()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=make_error("not_found", detail="User not found", context={"user_id": user_id}),
            )
        
        if user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=make_error("not_found", detail="User is not an admin", context={"user_id": user_id}),
            )
        
        db.delete(user)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=make_error("internal_error", detail="Failed to delete admin user", context={"error": str(e)}),
        )
    finally:
        db.close()

