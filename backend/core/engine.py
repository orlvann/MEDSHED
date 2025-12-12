# backend/core/engine.py
"""
Adapter for the OR-Tools CP-SAT solver.

This is the ONLY place where we directly import OR-Tools.
Everything else in core works with plain Python structures.
"""

from typing import Dict, List, Tuple

from ortools.sat.python import cp_model

from backend.models.common_enums import DoctorRole, ShiftType

from .types import HardModel, SolverAssignment, SolverSolution, SolverStatus


def build_and_solve(model: HardModel) -> SolverSolution:
    """
    Build a CP-SAT model for the given HardModel and solve it.

    ```
    Hard constraints enforced:
    - exactly one onsite and one oncall doctor per active day,
    - at least one specialist per active day (in any role),
    - no doctor can be onsite and oncall on the same day,
    - no assignment outside allowed_slots (unavailability + ignore_* are already "cut out").
    """
    # If there are no allowed slots at all, the solver has nothing to work with.
    if not model.allowed_slots:
        return SolverSolution(status=SolverStatus.EMPTY, assignments=[])

    # 1) Create CP-SAT model container.
    cp = cp_model.CpModel()

    # 2) Create binary decision variables for each allowed (day, shift_type, doctor) slot.
    #    We do NOT create variables for forbidden combinations.
    x: Dict[Tuple[int, ShiftType, int], cp_model.IntVar] = {}

    for (day, shift_type), doctor_ids in model.allowed_slots.items():
        for doctor_id in doctor_ids:
            x[(day, shift_type, doctor_id)] = cp.NewBoolVar(f"x_d{day}_{shift_type.value}_doc{doctor_id}")

    # 3) Hard constraints -------------------------------------------------------

    # 3.1 Enforce exactly one onsite and one oncall doctor per active day.
    for day in model.days:
        onsite_vars = [
            x[(day, ShiftType.onsite, doc_id)]
            for doc_id in model.allowed_slots.get((day, ShiftType.onsite), [])
            if (day, ShiftType.onsite, doc_id) in x
        ]
        if onsite_vars:
            cp.Add(sum(onsite_vars) == 1)

        oncall_vars = [
            x[(day, ShiftType.oncall, doc_id)]
            for doc_id in model.allowed_slots.get((day, ShiftType.oncall), [])
            if (day, ShiftType.oncall, doc_id) in x
        ]
        if oncall_vars:
            cp.Add(sum(oncall_vars) == 1)

    # 3.2 Enforce that each active day has at least one specialist (onsite OR oncall).
    for day in model.days:
        specialist_vars: List[cp_model.IntVar] = []

        for shift_type in (ShiftType.onsite, ShiftType.oncall):
            for doc_id in model.allowed_slots.get((day, shift_type), []):
                doctor = model.doctors.get(doc_id)
                if doctor and doctor.role == DoctorRole.specialist:
                    var = x.get((day, shift_type, doc_id))
                    if var is not None:
                        specialist_vars.append(var)

        if specialist_vars:
            cp.Add(sum(specialist_vars) >= 1)
        else:
            # If the input says "no specialist is allowed today", make the model infeasible on purpose.
            # This matches the rule: at least one specialist is required daily.
            cp.Add(0 >= 1)

    # 3.3 Enforce that the same doctor cannot be onsite AND oncall on the same day.
    for day in model.days:
        for doc_id in model.participant_doctor_ids:
            v_ons = x.get((day, ShiftType.onsite, doc_id))
            v_onc = x.get((day, ShiftType.oncall, doc_id))
            if v_ons is not None and v_onc is not None:
                cp.Add(v_ons + v_onc <= 1)

    # 4) Objective placeholder: we only need any feasible solution in this stage.
    cp.Minimize(0)

    # 5) Solve -----------------------------------------------------------------
    solver = cp_model.CpSolver()
    status = solver.Solve(cp)

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        status_enum = SolverStatus.OK
    elif status == cp_model.INFEASIBLE:
        status_enum = SolverStatus.INFEASIBLE
    else:
        # For example: UNKNOWN, MODEL_INVALID, etc.
        status_enum = SolverStatus.NOT_SOLVED

    if status_enum is not SolverStatus.OK:
        return SolverSolution(status=status_enum, assignments=[])

    # 6) Build SolverAssignment list from chosen Boolean variables.
    assignments: List[SolverAssignment] = []

    for (day, shift_type, doc_id), var in x.items():
        if solver.BooleanValue(var):
            assignments.append(
                SolverAssignment(
                    day=day,
                    shift_type=shift_type,
                    doctor_id=doc_id,
                )
            )

    # Deterministic ordering (helps tests and stable API payloads).
    assignments.sort(key=lambda a: (a.day, a.shift_type.value, a.doctor_id))

    return SolverSolution(status=SolverStatus.OK, assignments=assignments)
