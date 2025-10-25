"""
Scheduling Service — orchestrates schedule generation & lifecycle.

Coordinates:
- Preparing solver input (load doctors, preferences, constraints).
- Running the scheduler from core/ to generate schedules.
- Managing drafts, manual edits, publish/unpublish flows.
- Saving results and assignments to the database.

Responsibilities:
- End-to-end workflow orchestration (multi-step process).
- Keep 'working draft' separate from immutable stored versions.
- Maintain checkpoints for undo/redo within the draft lifecycle.
- Enforce publishing rules (at most one published per {year, month}).

Depends on:
- ORM: Schedule, Assignment (and related tables)
- core/ (scheduler.py, heuristics/, constraints/)
- Possibly diagnostics_service for post-run metrics

Notes:
- This is the “brain” of scheduling: decide steps, order, and error handling.
"""
