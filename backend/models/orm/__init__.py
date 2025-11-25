"""
SQLAlchemy ORM models (User, Doctor, Preference, Schedule, …).
Map Python classes to DB tables; import from this package to ensure models
are registered in Base.metadata (useful for Alembic, seeds, smoke tests).

Usage examples:
    from backend.models.orm import User, Doctor
    from backend.models.orm import (
        PreferenceWorking, PreferenceVersion, PreferencePointer, PreferenceDeadline,
    )
    from backend.models.orm import (
        ScheduleVersion, SchedulePointer, ScheduleWorking, ScheduleDiagnostics,
    )
"""

# Core entities
from .doctor import Doctor  # noqa: F401
from .password_reset_token import PasswordResetToken  # noqa: F401

# Preferences domain
from .preference import (  # noqa: F401
    PreferenceDeadline,
    PreferencePointer,
    PreferenceVersion,
    PreferenceWorking,
)

# Schedules domain
from .schedule import (  # noqa: F401
    ScheduleDiagnostics,
    SchedulePointer,
    ScheduleVersion,
    ScheduleWorking,
)
from .user import User  # noqa: F401

__all__ = [
    # core
    "User",
    "Doctor",
    "PasswordResetToken",
    # preferences
    "PreferenceWorking",
    "PreferenceVersion",
    "PreferencePointer",
    "PreferenceDeadline",
    # schedules
    "ScheduleVersion",
    "SchedulePointer",
    "ScheduleWorking",
    "ScheduleDiagnostics",
]
