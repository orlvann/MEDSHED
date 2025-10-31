"""
User Service — future admin operations.

Planned API (later):
- create_admin(email, password_or_none, doctor_id_or_none) -> (UserAdminRead, temporary_password_set)

Rules:
- If password is missing, generate a secure temporary password.
- Optionally link the new admin to an existing doctor via doctor_id.
- Hash passwords; never store or return plain text.

Errors:
- 409 duplicate_email
- 404 doctor_not_found (when linking)
- 422 validation errors

Auth contract:
- Real login flow must reject when users.is_active == False.
"""
