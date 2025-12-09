# backend/core/types.py
"""
Core domain types used by the solver.

These are small, pure-Python data containers (dataclasses) that are:
- independent from Pydantic, FastAPI and the database,
- built by services from ORM/DTO objects,
- consumed only inside backend/core/* modules.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple

from backend.models.common_enums import DoctorRole, ShiftType


@dataclass
class DoctorInput:
    """
    Minimal doctor information required by the solver.

    We do NOT use full DoctorRead here, only the fields that affect the model:
    - id: primary key (used in assignments).
    - role: specialist vs resident (rest rules, fairness, coverage).
    - is_head: True for department heads (stronger preference priority).
    - is_active: used for participant filtering (usually already filtered in services).
    """

    id: int
    role: DoctorRole
    is_head: bool
    is_active: bool = True


@dataclass
class PreferencesInput:
    """
    Flattened monthly preference data for a single doctor.

    These fields are taken from PreferenceWorking (or a Version payload),
    but converted to plain Python types for the core.
    """

    doctor_id: int

    # Day-level preferences (calendar days 1..31)
    unavailable_onsite_days: List[int] = field(default_factory=list)
    unavailable_oncall_days: List[int] = field(default_factory=list)
    preferred_onsite_days: List[int] = field(default_factory=list)
    preferred_oncall_days: List[int] = field(default_factory=list)

    # Monthly totals (soft constraints)
    min_onsite_total: int | None = None  # not used in MVP
    max_onsite_total: int | None = None
    target_onsite_total: int | None = None

    min_oncall_total: int | None = None  # not used in MVP
    max_oncall_total: int | None = None
    target_oncall_total: int | None = None

    # Weekend refinement (Sat–Sun)
    max_onsite_weekends: int | None = None
    target_onsite_weekends: int | None = None
    max_oncall_weekends: int | None = None
    target_oncall_weekends: int | None = None

    # Weekday patterns (0=Monday..6=Sunday)
    preferred_onsite_weekdays: List[int] = field(default_factory=list)
    preferred_oncall_weekdays: List[int] = field(default_factory=list)
    avoid_onsite_weekdays: List[int] = field(default_factory=list)
    avoid_oncall_weekdays: List[int] = field(default_factory=list)

    # Other preferences
    allow_weekend_consecutive_onsite_oncall: bool = False
    preferred_partners: List[int] = field(default_factory=list)
    comments: str | None = None  # informational only, ignored by solver


@dataclass
class ProblemData:
    """
    Full input for the solver for a single month (year+month).

    Services are responsible for:
    - building this structure from ORM / PreferenceWorking / DoctorRead,
    - filtering to participant_doctor_ids,
    - respecting ignore_days / ignore_slots from ScheduleGenerateRequest.
    """

    year: int
    month: int

    # Calendar days of this period, as day numbers 1..31
    days: List[int]

    # Mapping doctor_id -> DoctorInput
    doctors: Dict[int, DoctorInput]

    # Mapping doctor_id -> PreferencesInput
    preferences: Dict[int, PreferencesInput]

    # Which doctors are in the pool for this month (Admins can exclude some)
    participant_doctor_ids: Set[int]

    # Slots the solver must completely ignore (Admin wants to keep them empty)
    ignore_days: Set[int] = field(default_factory=set)
    ignore_slots: Set[Tuple[int, ShiftType]] = field(default_factory=set)


@dataclass
class Slot:
    """
    Single potential assignment in the schedule.

    This is a low-level unit used by the solver:
    - day: calendar day number (1..31),
    - shift_type: onsite or oncall,
    - doctor_id: doctor assigned to this slot.
    """

    day: int
    shift_type: ShiftType
    doctor_id: int


@dataclass
class HardModel:
    """
    Minimal hard-constraint model used by the solver engine.

    For now it only contains:
    - problem: original ProblemData for context,
    - allowed_slots: all slots that are not blocked by hard filters
    (ignore_days, ignore_slots, unavailable days from preferences).
    """

    problem: ProblemData
    allowed_slots: List[Slot]
