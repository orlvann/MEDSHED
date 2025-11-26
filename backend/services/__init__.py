# backend/services._init_
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

from .scheduling_service import SchedulingService

__all__ = ["SchedulingService"]
