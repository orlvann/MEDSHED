"""
Preference Service — monthly preference forms.

Handles:
- Receiving and validating doctors' monthly preference forms.
- Ensuring data consistency (e.g., min <= max, no overlapping unavailable/preferred days).
- Storing preferences in the database.

Responsibilities:
- Perform domain validation beyond schema-level checks.
- Normalize/clean inputs (days 1..31, deduplicate/sort, ranges).
- Maintain auditability (who changed what and when).

Uses:
- utils/validator.py for domain checks (logic validation).

Depends on:
- ORM: Preference, Doctor

Notes:
- Keep preference-specific rules centralized here.
"""
