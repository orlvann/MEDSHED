# backend/routers/admin_users.py
"""
Admin Users Router — CRUD for admin users (admin-only access).

Scope:
- List, create, update, delete admin users (role='admin' only)
- All endpoints require admin role

Security:
- Only admins can manage other admin users
- Password is auto-generated and sent via email

Notes:
- Doctor users are NOT managed here (use doctor_service auto-provision)
- Admin users can optionally be linked to doctor records
"""

from typing import Optional

from fastapi import APIRouter, Body, Depends, Query, status

from backend.models.schemas import ErrorPayload, UserAdminCreate, UserAdminList, UserAdminRead, UserAdminUpdate
from backend.routers.deps import require_admin
from backend.services import admin_user_service

router = APIRouter(tags=["admin-users"], dependencies=[Depends(require_admin)])


@router.get(
    "/api/v1/admin/users",
    response_model=UserAdminList,
    summary="List admin users",
    description="List all users with role='admin'. Supports pagination and search.",
)
def list_admin_users(
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    size: int = Query(20, ge=1, le=100, description="Items per page"),
    search: Optional[str] = Query(None, description="Search by email"),
    is_active: Optional[str] = Query("all", description="Filter by active status: true/false/all"),
):
    """
    List admin users with pagination and optional search filter.
    
    Only returns users with role='admin' (excludes doctor and doctor_admin).
    """
    return admin_user_service.list_admin_users(
        page=page,
        size=size,
        search=search,
        is_active=is_active,
    )


@router.get(
    "/api/v1/admin/users/{user_id}",
    response_model=UserAdminRead,
    summary="Get admin user by ID",
    responses={
        404: {
            "model": ErrorPayload,
            "description": "User not found or not an admin",
        }
    },
)
def get_admin_user(user_id: int):
    """
    Get a single admin user by ID.
    
    Returns 404 if user not found or if user is not an admin.
    """
    return admin_user_service.get_admin_user(user_id=user_id)


@router.post(
    "/api/v1/admin/users",
    response_model=UserAdminRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create admin user",
    responses={
        409: {
            "model": ErrorPayload,
            "description": "Email already in use",
        },
        404: {
            "model": ErrorPayload,
            "description": "Doctor not found (if doctor_id provided)",
        }
    },
)
def create_admin_user(payload: UserAdminCreate = Body(...)):
    """
    Create a new admin user.
    
    - Role is automatically set to 'admin'
    - Password is auto-generated
    - User starts with is_active=False
    - Password setup email is sent
    - User can optionally be linked to a doctor record
    """
    return admin_user_service.create_admin_user(payload=payload)


@router.put(
    "/api/v1/admin/users/{user_id}",
    response_model=UserAdminRead,
    summary="Update admin user",
    responses={
        404: {
            "model": ErrorPayload,
            "description": "User not found or not an admin",
        },
        409: {
            "model": ErrorPayload,
            "description": "Email already in use",
        }
    },
)
def update_admin_user(user_id: int, payload: UserAdminUpdate = Body(...)):
    """
    Update an existing admin user.
    
    Can update:
    - Email
    - is_active status
    - Linked doctor (doctor_id)
    """
    return admin_user_service.update_admin_user(user_id=user_id, payload=payload)


@router.delete(
    "/api/v1/admin/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete admin user",
    responses={
        404: {
            "model": ErrorPayload,
            "description": "User not found or not an admin",
        }
    },
)
def delete_admin_user(user_id: int):
    """
    Delete an admin user.
    
    Returns 404 if user not found or if user is not an admin.
    """
    admin_user_service.delete_admin_user(user_id=user_id)
    return None

