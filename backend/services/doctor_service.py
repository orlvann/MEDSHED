"""
Doctor Service — CRUD for doctor records.

Manages:
- Create, read, update, delete doctor profiles.
- Prevent invalid actions (e.g., deleting a doctor with active assignments unless forced).
- Apply domain rules (e.g., unique contact info, role flags, specialties).

Responsibilities:
- Validate inputs beyond basic schema checks.
- Map Pydantic DTOs ↔ ORM entities.
- Enforce referential integrity and safe deletion strategies.

Depends on:
- ORM: Doctor (and possibly Assignment for safety checks)

Notes:
- Keep all doctor-related business rules here so routers remain thin.
"""
