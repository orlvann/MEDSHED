"""
Services package.

What is a Service?
- A service is like a “manager”: it organizes work and talks to other parts of the system.
- Routers talk to services; services talk to everything else (core, db, utils).
- Services contain business logic and orchestrate multi-step processes.

Goal:
- Keep routers thin (I/O + HTTP only).
- Keep core focused (algorithms/analytics).
- Keep services as the application “brain”.

Service layer public API re-exports.
Keeping these imports lightweight makes IDEs (Pylance) aware of available symbols.
"""

from .scheduling_service import (
    get_pointer_version_id,
    get_published_pointer,
    get_working,
    get_working_lock_version,
    list_my_assignments_from_published,
    save_working_autosave,
    snapshot_working,
)

__all__ = [
    "get_working",
    "get_working_lock_version",
    "get_pointer_version_id",
    "get_published_pointer",
    "save_working_autosave",
    "snapshot_working",
    "list_my_assignments_from_published",
]
