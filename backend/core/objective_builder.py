# backend/core/objective_builder.py
"""
Attach soft constraints and objective to the hard model.

ETAP 3A:
* Add ONLY rest-rule penalties as soft constraints (objective terms).
* Hard constraints remain in engine.py.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Tuple

from ortools.sat.python import cp_model

from backend.core import scoring
from backend.core.types import HardModel, ProblemData
from backend.models.common_enums import DoctorRole, ShiftType


def _is_weekend_pair(year: int, month: int, d: int, d_next: int) -> bool:
    """
    Return True only for Saturday -> Sunday pairs.

    ```
    We intentionally use plain datetime.weekday() without time zones:
    - weekday(): 0=Mon ... 5=Sat, 6=Sun
    """
    wd = datetime(year, month, d).weekday()
    wd_next = datetime(year, month, d_next).weekday()
    return wd == 5 and wd_next == 6


def _add_pair_violation(
    cp: cp_model.CpModel,
    a: cp_model.IntVar,
    b: cp_model.IntVar,
    name: str,
) -> cp_model.IntVar:
    """
    Create a BoolVar v that becomes 1 when BOTH a==1 and b==1.

    ```
    AND encoding for binary vars:
    v >= a + b - 1
    """
    v = cp.NewBoolVar(name)
    cp.Add(v >= a + b - 1)
    return v


def attach_rest_objective(
    cp: cp_model.CpModel,
    x: Dict[Tuple[int, ShiftType, int], cp_model.IntVar],
    model: HardModel,
    problem: ProblemData,
) -> cp_model.IntVar:
    """
    Add rest-rule penalties to the CP-SAT model objective.
    ...
    """
    penalty_terms: List[cp_model.LinearExpr] = []
    ub: int = 0  # correct upper bound for total_penalty

    # We loop over doctors in the participant pool.
    for doc_id in model.participant_doctor_ids:
        doctor = model.doctors.get(doc_id)
        prefs = problem.preferences.get(doc_id)

        # Defensive defaults (should not happen in normal flow, but keeps solver robust)
        role: DoctorRole = doctor.role if doctor else DoctorRole.resident
        allow_weekend_consecutive = bool(prefs.allow_weekend_consecutive_onsite_oncall) if prefs else False

        weight_cross = scoring.rest_cross_shift_weight(role=role)

        # Iterate consecutive day pairs in the MONTH calendar days list.
        for idx in range(len(model.days) - 1):
            d = model.days[idx]
            d_next = model.days[idx + 1]

            # Skip pairs that are not consecutive integers (defensive).
            if d_next != d + 1:
                continue

            is_weekend_pair = _is_weekend_pair(problem.year, problem.month, d, d_next)

            # Pull decision vars (they might not exist if slot is forbidden).
            ons_d = x.get((d, ShiftType.onsite, doc_id))
            ons_dn = x.get((d_next, ShiftType.onsite, doc_id))
            oncall_d = x.get((d, ShiftType.oncall, doc_id))
            oncall_dn = x.get((d_next, ShiftType.oncall, doc_id))

            # onsite -> onsite
            if ons_d is not None and ons_dn is not None:
                v = _add_pair_violation(cp, ons_d, ons_dn, f"rest_ons_ons_d{d}_doc{doc_id}")
                penalty_terms.append(scoring.REST_ONS_ONS_WEIGHT * v)
                ub += int(scoring.REST_ONS_ONS_WEIGHT)

            # oncall -> oncall
            if oncall_d is not None and oncall_dn is not None:
                v = _add_pair_violation(cp, oncall_d, oncall_dn, f"rest_oncall_oncall_d{d}_doc{doc_id}")
                penalty_terms.append(scoring.REST_ONCALL_ONCALL_WEIGHT * v)
                ub += int(scoring.REST_ONCALL_ONCALL_WEIGHT)

            # cross-shift (ons->oncall, oncall->ons)
            # Weekend exception: Sat->Sun cross-shift is allowed without penalty if flag=True.
            skip_weekend_cross = bool(is_weekend_pair and allow_weekend_consecutive)

            if not skip_weekend_cross:
                if ons_d is not None and oncall_dn is not None:
                    v = _add_pair_violation(cp, ons_d, oncall_dn, f"rest_ons_oncall_d{d}_doc{doc_id}")
                    penalty_terms.append(int(weight_cross) * v)
                    ub += int(weight_cross)

                if oncall_d is not None and ons_dn is not None:
                    v = _add_pair_violation(cp, oncall_d, ons_dn, f"rest_oncall_ons_d{d}_doc{doc_id}")
                    penalty_terms.append(int(weight_cross) * v)
                    ub += int(weight_cross)

    # Build a single IntVar that equals the sum of all penalty terms.
    # CP-SAT likes having a concrete variable minimized.
    if penalty_terms:
        total_penalty = cp.NewIntVar(0, int(ub), "total_rest_penalty")
        cp.Add(total_penalty == sum(penalty_terms))
    else:
        total_penalty = cp.NewIntVar(0, 0, "total_rest_penalty")
        cp.Add(total_penalty == 0)

    return total_penalty
