# backend/tests/solver/_helpers.py
"""
Test helpers for solver tests.

We keep helper functions here to make individual tests short and readable.

Planned helpers (ETAP 3A):

* assignments_to_map(solution): map (day, shift_type) -> doctor_id
* pretty_solution(solution): build a readable snapshot string for assertion messages
* check_hard_invariants(solution, model): return a list[str] of detected issues
* compute_rest_penalty_offline(...): compute rest penalty from assignments (same weights as scoring)
* count_rest_violations_offline(...): count rest-rule violation patterns

NOTE:
These helpers live in tests/ (not production code) on purpose:

* production code stays clean,
* tests can provide extra diagnostics text for failures.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from backend.core import scoring
from backend.core.types import DoctorInput, HardModel, PreferencesInput, SolverAssignment, SolverSolution
from backend.models.common_enums import DoctorRole, ShiftType


def assignments_to_map(solution: SolverSolution) -> dict[tuple[int, ShiftType], int]:
    """
    Convert solution.assignments to a simple map:

    ```
        (day, shift_type) -> doctor_id

    Defensive behavior:
    - If duplicates exist for the same (day, shift_type), we do NOT raise.
    We apply "last wins" so tests can still inspect the map.
    - If you want to detect duplicates, use find_duplicate_slots(solution).
    """
    out: dict[tuple[int, ShiftType], int] = {}
    for a in solution.assignments:
        key = (int(a.day), a.shift_type)
        out[key] = int(a.doctor_id)
    return out


def find_duplicate_slots(solution: SolverSolution) -> dict[tuple[int, ShiftType], list[int]]:
    """
    Return a map of duplicated slots:

    ```
        (day, shift_type) -> [doctor_id1, doctor_id2, ...]

    Only keys that appear MORE THAN ONCE are included.
    This is useful in tests for readable failure messages (instead of a crash).
    """
    seen: dict[tuple[int, ShiftType], list[int]] = {}
    for a in solution.assignments:
        key = (int(a.day), a.shift_type)
        seen.setdefault(key, []).append(int(a.doctor_id))

    duplicates: dict[tuple[int, ShiftType], list[int]] = {}
    for key, doctor_ids in seen.items():
        if len(doctor_ids) > 1:
            duplicates[key] = doctor_ids
    return duplicates


def pretty_solution(solution: SolverSolution) -> str:
    """
    Produce a readable, stable snapshot of the solution for assert messages.

    ```
    Format:
    - first line: status
    - then one assignment per line in stable order: day, shift_type, doctor_id
    - if duplicates exist, we include a short section at the end
    """
    lines: list[str] = []
    lines.append(f"status={solution.status}")

    # Stable ordering: day -> shift_type -> doctor_id
    sorted_assignments = sorted(
        solution.assignments,
        key=lambda a: (int(a.day), str(a.shift_type.value), int(a.doctor_id)),
    )
    if not sorted_assignments:
        lines.append("(no assignments)")
    else:
        for a in sorted_assignments:
            lines.append(f"- day={int(a.day):02d} shift={a.shift_type.value} doctor_id={int(a.doctor_id)}")

    duplicates = find_duplicate_slots(solution)
    if duplicates:
        lines.append("duplicates_detected:")
        for (day, shift), doctor_ids in sorted(duplicates.items(), key=lambda x: (x[0][0], x[0][1].value)):
            lines.append(f"  - slot(day={day:02d}, shift={shift.value}) -> doctor_ids={doctor_ids}")

    return "\n".join(lines)


def check_hard_invariants(model: HardModel, solution: SolverSolution) -> list[str]:
    """
    Check the solver output against hard invariants.

    ```
    IMPORTANT:
    - This returns a list of human-readable error strings.
    - It does NOT raise exceptions (tests decide how to assert).

    Invariants checked:
    1) For each active day and each required shift (not ignored): exactly 1 assignment.
    2) At least one specialist among required shifts for that day (unless both shifts ignored).
    3) No doctor can be onsite and oncall on the same day (double shift).
    4) Assignments must only be for active days and must not target ignored slots.
    5) Sanity: assigned doctors should belong to participant_doctor_ids.
    """
    errors: list[str] = []

    # Pre-index assignments for counts and quick lookups.
    # We keep counts (not "map") to detect duplicates cleanly.
    per_slot_doctors: dict[tuple[int, ShiftType], list[int]] = {}
    per_day_per_doctor_shifts: dict[tuple[int, int], set[ShiftType]] = {}

    for a in solution.assignments:
        day = int(a.day)
        shift = a.shift_type
        doc_id = int(a.doctor_id)

        per_slot_doctors.setdefault((day, shift), []).append(doc_id)
        per_day_per_doctor_shifts.setdefault((day, doc_id), set()).add(shift)

        # Assignment must be in active days.
        if day not in set(model.active_days):
            errors.append(
                f"assignment_outside_active_days: day={day} shift={shift.value} doctor_id={doc_id} "
                f"(active_days={sorted(model.active_days)})"
            )

        # Assignment must not be in ignored slots.
        if (day, shift) in model.ignore_slots:
            errors.append(f"assignment_in_ignored_slot: day={day} shift={shift.value} doctor_id={doc_id}")

        # Sanity: assigned doctor should belong to participant pool.
        if doc_id not in set(model.participant_doctor_ids):
            errors.append(
                f"assignment_doctor_not_in_participants: day={day} shift={shift.value} doctor_id={doc_id} "
                f"(participants={sorted(model.participant_doctor_ids)})"
            )

    active_days_set = set(model.active_days)

    # 1) Exact coverage per required shift for each active day.
    for day in sorted(model.active_days):
        for shift in (ShiftType.onsite, ShiftType.oncall):
            if (day, shift) in model.ignore_slots:
                continue  # not required
            got = per_slot_doctors.get((day, shift), [])
            if len(got) != 1:
                errors.append(
                    f"coverage_wrong_count: day={day} shift={shift.value} expected=1 got={len(got)} doctor_ids={got}"
                )

        # 2) At least one specialist among required shifts for the day.
        required_shifts: list[ShiftType] = [
            s for s in (ShiftType.onsite, ShiftType.oncall) if (day, s) not in model.ignore_slots
        ]
        if not required_shifts:
            continue  # both shifts ignored -> skip specialist rule

        required_doctors: list[int] = []
        for s in required_shifts:
            required_doctors.extend(per_slot_doctors.get((day, s), []))

        # If coverage is missing, required_doctors may be empty or have wrong size.
        # We still try to produce a meaningful specialist error.
        has_specialist = False
        for doc_id in required_doctors:
            doc = model.doctors.get(doc_id)
            if doc and doc.role == DoctorRole.specialist:
                has_specialist = True
                break

        if not has_specialist:
            errors.append(
                f"no_specialist_on_day: day={day} required_shifts={[s.value for s in required_shifts]} "
                f"assigned_doctor_ids={required_doctors}"
            )

    # 3) No double shift for same doctor on same day.
    for (day, doc_id), shifts in sorted(per_day_per_doctor_shifts.items(), key=lambda x: (x[0][0], x[0][1])):
        if day not in active_days_set:
            continue  # already flagged above, but avoid noise
        if ShiftType.onsite in shifts and ShiftType.oncall in shifts:
            errors.append(
                f"double_shift_same_day: day={day} doctor_id={doc_id} shifts={[s.value for s in sorted(shifts)]}"
            )

    # 4) Assignments only for required shifts already covered above by "ignored slot" check,
    #    but we also provide a clearer message if an assignment targets a day outside model.days.
    model_days_set = set(model.days)
    for (day, shift), doctor_ids in sorted(per_slot_doctors.items(), key=lambda x: (x[0][0], x[0][1].value)):
        if day not in model_days_set:
            errors.append(
                f"assignment_day_not_in_model_days: day={day} shift={shift.value} doctor_ids={doctor_ids} "
                f"(model.days={sorted(model.days)})"
            )
    return errors


def _is_weekend_pair(year: int, month: int, d: int, d_next: int) -> bool:
    """
    Return True only for Saturday -> Sunday pairs (same logic as objective_builder.py).

    ```
    weekday(): 0=Mon ... 5=Sat, 6=Sun
    """
    wd = datetime(year, month, d).weekday()
    wd_next = datetime(year, month, d_next).weekday()
    return wd == 5 and wd_next == 6


def _iter_consecutive_day_pairs(days: list[int]) -> Iterable[tuple[int, int]]:
    """
    Yield consecutive integer day pairs (d, d_next) in the given days list.

    ```
    Defensive:
    - We only yield pairs where d_next == d + 1
    (to match objective_builder behavior).
    """
    for idx in range(len(days) - 1):
        d = int(days[idx])
        d_next = int(days[idx + 1])
        if d_next != d + 1:
            continue
        yield d, d_next


def count_rest_violations_offline(
    *,
    year: int,
    month: int,
    days: list[int],
    doctors: dict[int, DoctorInput],
    preferences: dict[int, PreferencesInput],
    assignments: list[SolverAssignment],
) -> dict[str, int]:
    """
    Count rest-rule violation patterns offline (outside OR-Tools).

    ```
    We count for each doctor and each consecutive day pair (d, d_next):
    - onsite(d) and onsite(d_next) -> "ons_ons"
    - oncall(d) and oncall(d_next) -> "onc_onc"
    - cross: onsite(d) and oncall(d_next) OR oncall(d) and onsite(d_next) -> "cross"

    Weekend exception (Sat->Sun only):
    - if doctor.allow_weekend_consecutive_onsite_oncall is True,
    then cross violations for that pair are NOT counted.
    (ons_ons and onc_onc are still counted)

    Return example:
        {"ons_ons": 1, "onc_onc": 0, "cross": 2}
    """
    counts: dict[str, int] = {"ons_ons": 0, "onc_onc": 0, "cross": 0}

    # Index assignments also per doctor and day for quick boolean checks.
    # Using slot_map is enough for "who is assigned", but we need "is this doctor assigned on that slot?".
    assigned_set: set[tuple[int, ShiftType, int]] = set()
    for a in assignments:
        assigned_set.add((int(a.day), a.shift_type, int(a.doctor_id)))

    for doc_id, doctor in doctors.items():
        prefs = preferences.get(doc_id)
        allow_weekend_consecutive = bool(prefs.allow_weekend_consecutive_onsite_oncall) if prefs else False

        for d, d_next in _iter_consecutive_day_pairs(days):
            is_weekend = _is_weekend_pair(year, month, d, d_next)

            ons_d = (d, ShiftType.onsite, doc_id) in assigned_set
            ons_dn = (d_next, ShiftType.onsite, doc_id) in assigned_set
            onc_d = (d, ShiftType.oncall, doc_id) in assigned_set
            onc_dn = (d_next, ShiftType.oncall, doc_id) in assigned_set

            # onsite -> onsite
            if ons_d and ons_dn:
                counts["ons_ons"] += 1

            # oncall -> oncall
            if onc_d and onc_dn:
                counts["onc_onc"] += 1

            # cross-shift
            skip_weekend_cross = bool(is_weekend and allow_weekend_consecutive)
            if not skip_weekend_cross:
                if (ons_d and onc_dn) or (onc_d and ons_dn):
                    counts["cross"] += 1
    return counts


def compute_rest_penalty_offline(
    *,
    year: int,
    month: int,
    days: list[int],
    doctors: dict[int, DoctorInput],
    preferences: dict[int, PreferencesInput],
    assignments: list[SolverAssignment],
) -> int:
    """
    Compute total rest penalty offline, using weights from backend/core/scoring.py.

    ```
    Penalties:
    - onsite->onsite: scoring.REST_ONS_ONS_WEIGHT
    - oncall->oncall: scoring.REST_ONCALL_ONCALL_WEIGHT
    - cross-shift: scoring.rest_cross_shift_weight(role=doctor.role)

    Weekend exception matches objective_builder.py (Sat->Sun only):
    - cross-shift is not penalized for doctors who allow it.
    """
    total: int = 0

    # Index assignments per doctor/day quickly.
    assigned_set: set[tuple[int, ShiftType, int]] = set()
    for a in assignments:
        assigned_set.add((int(a.day), a.shift_type, int(a.doctor_id)))

    for doc_id, doctor in doctors.items():
        prefs = preferences.get(doc_id)
        allow_weekend_consecutive = bool(prefs.allow_weekend_consecutive_onsite_oncall) if prefs else False

        # Defensive default: if doctor is missing from dict, treat as resident.
        role: DoctorRole = doctor.role if doctor else DoctorRole.resident
        cross_weight = scoring.rest_cross_shift_weight(role=role)

        for d, d_next in _iter_consecutive_day_pairs(days):
            is_weekend = _is_weekend_pair(year, month, d, d_next)

            ons_d = (d, ShiftType.onsite, doc_id) in assigned_set
            ons_dn = (d_next, ShiftType.onsite, doc_id) in assigned_set
            onc_d = (d, ShiftType.oncall, doc_id) in assigned_set
            onc_dn = (d_next, ShiftType.oncall, doc_id) in assigned_set

            if ons_d and ons_dn:
                total += int(scoring.REST_ONS_ONS_WEIGHT)

            if onc_d and onc_dn:
                total += int(scoring.REST_ONCALL_ONCALL_WEIGHT)

            skip_weekend_cross = bool(is_weekend and allow_weekend_consecutive)
            if not skip_weekend_cross:
                if ons_d and onc_dn:
                    total += int(cross_weight)
                if onc_d and ons_dn:
                    total += int(cross_weight)

    return total


def solution_snapshot(model: HardModel, solution: SolverSolution) -> str:
    """
    Convenience helper for debugging in tests:
    - pretty_solution(solution)
    - + hard invariant errors (if any)

    ```
    This is meant to be used inside assert messages.
    """
    lines: list[str] = [pretty_solution(solution)]
    errors = check_hard_invariants(model, solution)
    if errors:
        lines.append("")
        lines.append("hard_invariants_errors:")
        for e in errors:
            lines.append(f"- {e}")
    return "\n".join(lines)
