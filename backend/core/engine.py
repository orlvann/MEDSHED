# backend/core/engine.py
"""
Adapter for the OR-Tools CP-SAT solver.

This is the ONLY place where we directly import OR-Tools.
Everything else in core works with plain Python structures.
"""

from typing import List

from backend.models.common_enums import ShiftType

from .types import HardModel, Slot, SolverAssignment, SolverSolution, SolverStatus

# def build_and_solve(model: HardModel) -> SolverSolution:
#     """
#     Build a simple greedy solution for the given hard model.

#     ```
#     For each day we try to choose at most one onsite doctor and at most one
#     on-call doctor, never assigning the same doctor to both roles on the
#     same day.
#     """
#     # If there are no allowed slots at all, we treat this as an empty model.
#     if not model.allowed_slots:
#         # We could also use SolverStatus.INFEASIBLE here; for now we keep EMPTY
#         # to clearly signal that the solver had nothing to work with.
#         return SolverSolution(status=SolverStatus.EMPTY, assignments=[])

#     # This list will store all solver decisions for the whole month.
#     assignments: List[SolverAssignment] = []

#     # Index allowed slots by (day, shift_type) to make lookups fast and clear.
#     slots_by_day_and_shift: dict[tuple[int, ShiftType], List[Slot]] = {}
#     for slot in model.allowed_slots:
#         key = (slot.day, slot.shift_type)
#         # Create list for this (day, shift_type) if it does not exist yet.
#         if key not in slots_by_day_and_shift:
#             slots_by_day_and_shift[key] = []
#         slots_by_day_and_shift[key].append(slot)

#     # Iterate through days in a stable order (ascending day number).
#     for day in sorted(model.problem.days):
#         # Safety guard: days listed in ignore_days should stay empty.
#         if day in model.problem.ignore_days:
#             continue

#         # Keep track of doctors already used on this day
#         # so we never assign the same doctor twice.
#         used_doctors_for_day: set[int] = set()

#         onsite_assignment = None
#         oncall_assignment = None

#         # --- Choose onsite doctor (at most one) --------------------------------
#         onsite_key = (day, ShiftType.onsite)
#         onsite_slots = slots_by_day_and_shift.get(onsite_key, [])

#         # Greedy rule: pick the first available slot.
#         for slot in onsite_slots:
#             if slot.doctor_id in used_doctors_for_day:
#                 # This should not normally happen, but we keep the check for clarity.
#                 continue
#             onsite_assignment = SolverAssignment(
#                 day=slot.day,
#                 shift_type=slot.shift_type,
#                 doctor_id=slot.doctor_id,
#             )
#             used_doctors_for_day.add(slot.doctor_id)
#             break  # Only one onsite per day.

#         # --- Choose on-call doctor (at most one) -------------------------------
#         oncall_key = (day, ShiftType.oncall)
#         oncall_slots = slots_by_day_and_shift.get(oncall_key, [])

#         for slot in oncall_slots:
#             # Do not assign the same doctor twice on the same day.
#             if slot.doctor_id in used_doctors_for_day:
#                 continue
#             oncall_assignment = SolverAssignment(
#                 day=slot.day,
#                 shift_type=slot.shift_type,
#                 doctor_id=slot.doctor_id,
#             )
#             used_doctors_for_day.add(slot.doctor_id)
#             break  # Only one on-call per day.

#         # --- Collect assignments for this day ----------------------------------
#         if onsite_assignment is not None:
#             assignments.append(onsite_assignment)

#         if oncall_assignment is not None:
#             assignments.append(oncall_assignment)

#     # For MVP we treat any non-empty assignment set as a successful solution.
#     status = SolverStatus.OK if assignments else SolverStatus.EMPTY
#     return SolverSolution(status=status, assignments=assignments)


def build_and_solve(model: HardModel) -> SolverSolution:
    """
    Build a simple greedy solution for the given hard model.

    For each day we try to choose at most one onsite doctor and at most one
    on-call doctor, never assigning the same doctor to both roles on the
    same day.
    """
    # Debug: check how many allowed slots we have.
    print(f"[DEBUG] allowed_slots count = {len(model.allowed_slots)}")

    if not model.allowed_slots:
        print("[DEBUG] No allowed slots, returning EMPTY solution")
        return SolverSolution(status=SolverStatus.EMPTY, assignments=[])

    assignments: List[SolverAssignment] = []

    slots_by_day_and_shift: dict[tuple[int, ShiftType], List[Slot]] = {}
    for slot in model.allowed_slots:
        key = (slot.day, slot.shift_type)
        if key not in slots_by_day_and_shift:
            slots_by_day_and_shift[key] = []
        slots_by_day_and_shift[key].append(slot)

    for day in sorted(model.problem.days):
        if day in model.problem.ignore_days:
            print(f"[DEBUG] Day {day} is in ignore_days, skipping")
            continue

        used_doctors_for_day: set[int] = set()
        onsite_assignment = None
        oncall_assignment = None

        onsite_key = (day, ShiftType.onsite)
        onsite_slots = slots_by_day_and_shift.get(onsite_key, [])

        for slot in onsite_slots:
            if slot.doctor_id in used_doctors_for_day:
                continue
            onsite_assignment = SolverAssignment(
                day=slot.day,
                shift_type=slot.shift_type,
                doctor_id=slot.doctor_id,
            )
            used_doctors_for_day.add(slot.doctor_id)
            break

        oncall_key = (day, ShiftType.oncall)
        oncall_slots = slots_by_day_and_shift.get(oncall_key, [])

        for slot in oncall_slots:
            if slot.doctor_id in used_doctors_for_day:
                continue
            oncall_assignment = SolverAssignment(
                day=slot.day,
                shift_type=slot.shift_type,
                doctor_id=slot.doctor_id,
            )
            used_doctors_for_day.add(slot.doctor_id)
            break

        print(f"[DEBUG] Day {day}: onsite={onsite_assignment}, oncall={oncall_assignment}")

        if onsite_assignment is not None:
            assignments.append(onsite_assignment)
        if oncall_assignment is not None:
            assignments.append(oncall_assignment)

    print(f"[DEBUG] Total assignments produced = {len(assignments)}")
    status = SolverStatus.OK if assignments else SolverStatus.EMPTY
    print(f"[DEBUG] Solver status = {status}")
    return SolverSolution(status=status, assignments=assignments)
