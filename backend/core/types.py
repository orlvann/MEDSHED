# backend/core/types.py
"""
Core domain types used by the solver.

These are small, pure-Python data containers (dataclasses) that are:
- independent from Pydantic, FastAPI and the database,
- built by services from ORM/DTO objects,
- consumed only inside backend/core/* modules.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Set, Tuple

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

    # Monthly totals (soft caps and targets)
    min_onsite_total: int | None = None  # not used in MVP
    max_onsite_total: int | None = None
    target_onsite_total: int | None = None

    min_oncall_total: int | None = None  # not used in MVP
    max_oncall_total: int | None = None
    target_oncall_total: int | None = None

    # Weekend-specific caps and targets (Sat–Sun)
    max_onsite_weekends: int | None = None
    target_onsite_weekends: int | None = None
    max_oncall_weekends: int | None = None
    target_oncall_weekends: int | None = None

    # Weekly pattern preferences (0=Monday..6=Sunday)
    preferred_onsite_weekdays: List[int] = field(default_factory=list)
    preferred_oncall_weekdays: List[int] = field(default_factory=list)
    avoid_onsite_weekdays: List[int] = field(default_factory=list)
    avoid_oncall_weekdays: List[int] = field(default_factory=list)

    # Flags and relationship preferences
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

    # Map of day -> weekday (0=Mon .. 6=Sun), computed once in the service.
    weekdays: Dict[int, int]

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
    Data wrapper for the hard-constraint phase.

    ```
    This object contains:
    - a flat copy of the ProblemData fields needed by the solver core,
    - allowed_slots: a precomputed "hard feasible" doctor list per (day, shift_type).

    Note:
    - allowed_slots is ONLY based on ignore rules and unavailability.
    - soft constraints (fairness, targets, weekends, etc.) are handled later.
    """

    # Base fields (copied from ProblemData so the core does not need to reach outside HardModel)
    year: int
    month: int
    days: List[int]
    doctors: Dict[int, DoctorInput]
    preferences: Dict[int, PreferencesInput]
    participant_doctor_ids: Set[int]
    ignore_days: Set[int] = field(default_factory=set)
    ignore_slots: Set[Tuple[int, ShiftType]] = field(default_factory=set)

    # HardModel-specific:
    # For each (day, shift_type) store doctors that are allowed to work in this slot.
    allowed_slots: Dict[Tuple[int, ShiftType], List[int]] = field(default_factory=dict)

    # Optional: keep seed hints for later stages (not used yet).
    seed_hints: Any | None = None


@dataclass
class SolverAssignment:
    """
    Single assignment decision produced by the solver.

    ```
    - day: calendar day number (1..31),
    - shift_type: onsite or oncall,
    - doctor_id: doctor assigned to this slot.
    """

    day: int
    shift_type: ShiftType
    doctor_id: int


class SolverStatus(str, Enum):
    """
    High-level status of the solver run.

    ```
    Using an Enum instead of a plain string:
    - avoids typos in status values,
    - gives us autocomplete and a single source of truth,
    - still serializes nicely to JSON (value is a string).
    """

    OK = "OK"
    EMPTY = "EMPTY"  # no allowed slots or no assignments produced
    INFEASIBLE = "INFEASIBLE"  # model cannot be satisfied
    NOT_SOLVED = "NOT_SOLVED"  # solver did not run or aborted
    ERROR = "ERROR"  # internal error while building/solving


@dataclass
class FeasibilityIssue:
    """
    Single feasibility issue detected before or during solving.

    This is a lightweight diagnostic describing why the problem
    cannot be solved (or is very likely infeasible).
    """

    day: int  # calendar day number (1..31)
    code: str  # short machine-readable code, e.g. "no_specialist"
    message: str  # short human-readable explanation


@dataclass
class SolverSolution:
    """
    Full solver result for one month.

    ```
    - status: high-level solver status,
    - assignments: list of concrete SolverAssignment objects,
    - issues: feasibility issues detected before or during solving.
    """

    status: SolverStatus
    assignments: List[SolverAssignment] = field(default_factory=list)
    issues: List[FeasibilityIssue] = field(default_factory=list)
