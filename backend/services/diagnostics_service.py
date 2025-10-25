"""
Diagnostics Service — analyze and summarize schedules.

Responsible for:
- Loading schedule data, preferences, and doctor roles from the DB.
- Calling analytical functions in core/diagnostics.py.
- Aggregating results (scores, fairness, costs, chart-ready data) into DTOs (schemas/diagnostics.py)
- Optionally caching results in a schedule_metrics table for fast retrieval.

Design:
- Knows DB and DTOs, but not FastAPI internals or solver implementation details.

Depends on:
- ORM: Schedule, Assignment, Doctor, Preference (as needed)
- core/diagnostics.py
- schemas/diagnostics.py (DTOs for API responses)

Notes:
- Keep heavy computations in core/, aggregation/assembly here.
"""
