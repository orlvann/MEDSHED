# backend/routers/pending_doctors.py
"""
Pending Doctors Router — handles doctor self-registration and admin approval workflow.

Public endpoints:
- POST /api/v1/doctors/register - Doctor submits registration request

Admin-only endpoints:
- GET /api/v1/admin/pending-doctors - List pending registrations
- GET /api/v1/admin/pending-doctors/count - Get count of pending
- POST /api/v1/admin/pending-doctors/{id}/approve - Approve registration
- DELETE /api/v1/admin/pending-doctors/{id}/reject - Reject registration
"""

from fastapi import APIRouter, Body, Depends, Path, Query, status

from backend.models.schemas.dto_common import ErrorPayload
from backend.models.schemas.pending_doctor import (
    PendingDoctorApprove,
    PendingDoctorList,
    PendingDoctorRead,
    PendingDoctorRegister,
)
from backend.routers.deps import UserCtx, require_admin
from backend.services import pending_doctor_service

# Public router (no auth required)
public_router = APIRouter(tags=["doctors"])

# Admin-only router
admin_router = APIRouter(tags=["admin-pending-doctors"], dependencies=[Depends(require_admin)])


# --------------------------- PUBLIC ENDPOINTS ------------------------------


@public_router.post(
    "/api/v1/doctors/register",
    response_model=PendingDoctorRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register as a doctor (public)",
    operation_id="doctors_register",
    responses={
        409: {
            "model": ErrorPayload,
            "description": "Email already registered or pending",
        }
    },
)
def register_doctor(payload: PendingDoctorRegister = Body(...)):
    """
    Public endpoint: Prospective doctors can submit registration request.
    
    Admin will review and either approve or reject the request.
    
    Returns:
        PendingDoctorRead with registration details
    """
    return pending_doctor_service.register_doctor(payload=payload)


# --------------------------- ADMIN ENDPOINTS -------------------------------


@admin_router.get(
    "/api/v1/admin/pending-doctors",
    response_model=PendingDoctorList,
    summary="List pending doctor registrations (admin only)",
    operation_id="pending_doctors_list",
)
def list_pending_doctors(
    user: UserCtx = Depends(require_admin),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    size: int = Query(20, ge=1, le=100, description="Items per page"),
):
    """
    List all pending doctor registrations awaiting admin approval.
    
    Returns:
        PendingDoctorList with paginated results
    """
    return pending_doctor_service.list_pending_doctors(page=page, size=size)


@admin_router.get(
    "/api/v1/admin/pending-doctors/count",
    summary="Get count of pending doctor registrations (admin only)",
    operation_id="pending_doctors_count",
)
def get_pending_count(user: UserCtx = Depends(require_admin)):
    """
    Get the total count of pending doctor registrations.
    
    Useful for showing badges/notifications in admin UI.
    
    Returns:
        Object with count field
    """
    count = pending_doctor_service.get_pending_count()
    return {"count": count}


@admin_router.post(
    "/api/v1/admin/pending-doctors/{pending_id}/approve",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Approve pending doctor registration (admin only)",
    operation_id="pending_doctors_approve",
    responses={
        404: {
            "model": ErrorPayload,
            "description": "Pending doctor not found",
        }
    },
)
def approve_doctor(
    user: UserCtx = Depends(require_admin),
    pending_id: int = Path(..., ge=1, description="ID of pending doctor"),
    approval_data: PendingDoctorApprove = Body(...),
):
    """
    Approve a pending doctor registration.
    
    Creates:
    - Doctor record with specified role and settings
    - User account with specified user_role
    - Password setup token
    
    Sends welcome email with password setup link.
    Deletes the pending record.
    
    Args:
        pending_id: ID of the pending doctor to approve
        approval_data: Doctor and user settings (role, user_role, is_head, is_active)
    """
    pending_doctor_service.approve_doctor(pending_id=pending_id, approval_data=approval_data)
    return None


@admin_router.delete(
    "/api/v1/admin/pending-doctors/{pending_id}/reject",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Reject pending doctor registration (admin only)",
    operation_id="pending_doctors_reject",
    responses={
        404: {
            "model": ErrorPayload,
            "description": "Pending doctor not found",
        }
    },
)
def reject_doctor(
    user: UserCtx = Depends(require_admin),
    pending_id: int = Path(..., ge=1, description="ID of pending doctor"),
):
    """
    Reject a pending doctor registration.
    
    Simply deletes the pending record. No email is sent.
    
    Args:
        pending_id: ID of the pending doctor to reject
    """
    pending_doctor_service.reject_doctor(pending_id=pending_id)
    return None

