"""
Export Service — create XLSX/PDF exports of schedules.

Creates:
- Exportable files (Excel/PDF) for the final schedule.
- Optional inclusion of diagnostics/metrics in the export.

Responsibilities:
- Load schedule and related data from the DB.
- Call helper modules in utils/exporters/ to build files.
- Decide the output format (xlsx/pdf) and provide a binary payload with proper metadata.
- Optionally record export metadata (job status, filename, created_by, timestamp).

Depends on:
- ORM: Schedule, Assignment
- utils/exporters/ (xlsx/pdf builders)
- diagnostics_service (optional, if including analytics)

Notes:
- This service returns bytes + content-type/filename metadata; routers wrap it into HTTP responses.
"""
