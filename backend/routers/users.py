"""
Users Router (admin-only) — minimal scope by design.

Purpose:
- Provide a narrow endpoint to create additional admin accounts when needed
  (e.g., temporary replacement). The organization normally has exactly one admin.

Out of scope on this router:
- Generic /users CRUD and doctor-user creation are NOT exposed here.
  Doctor users are auto-provisioned in doctor_service during POST /doctors.

Endpoint to add later:
- POST /api/v1/users/admins  (admin-only, tags=["users"], operation_id="users_create_admin")

Behavior:
- Body: email (required), password (optional → generate temp if missing),
  role=admin (fixed), optional doctor_id to link the admin with a Doctor.
- Response: admin-view user object + flag 'temporary_password_set'.
- When a user is created here, set `must_change_password=True` by default
  (first-login policy), unless explicitly disabled by policy.

Errors (dto_common.ErrorPayload):
- 409 duplicate_email
- 404 doctor_not_found (when linking via doctor_id)
- 422 validation errors

Security utils:
- backend/utils/security.py for password hashing and temporary password generation.

Notes:
- Login must deny when users.is_active == False (independent from doctors.is_active).
- Doctor users are created via auto-provision in doctor_service (not here) and
  SHOULD also set `must_change_password=True` by default.
"""
