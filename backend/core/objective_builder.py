# backend/core/objective_builder.py
"""
Attach soft constraints and objective to the hard model.

STAGE 1:
* Add ONLY rest-rule penalties as soft constraints (objective terms).
* Hard constraints remain in engine.py.

STAGE 2:
* Add preferred-days penalties + totals penalties as additional soft terms.
* We keep weights centralized in backend/core/scoring.py.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Set, Tuple

from ortools.sat.python import cp_model

from backend.core import scoring
from backend.core.fairness_expected import compute_expected_map_for_fairness
from backend.core.types import HardModel, ProblemData
from backend.models.common_enums import DoctorRole, ShiftType


def _is_weekend_pair(year: int, month: int, d: int, d_next: int) -> bool:
    """
    Return True only for Saturday -> Sunday pairs.

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

    AND encoding for binary vars:
    v >= a + b - 1
    """
    v = cp.NewBoolVar(name)
    cp.Add(v >= a + b - 1)
    return v


def attach_preferred_days_objective(
    cp: cp_model.CpModel,
    x: Dict[Tuple[int, ShiftType, int], cp_model.IntVar],
    model: HardModel,
    problem: ProblemData,
) -> cp_model.IntVar:
    """
    Add penalties related to concrete preferred days:
    - preferred_onsite_days
    - preferred_oncall_days

    Penalty is added when a preferred day is NOT assigned.
    If a slot variable does not exist (forbidden / filtered), we skip that preference (MVP).

    Returns:
        total_penalty: IntVar with the sum of preferred-day penalties.
    """
    penalty_terms: List[cp_model.LinearExpr] = []
    ub: int = 0  # upper bound for total_penalty

    for doc_id in model.participant_doctor_ids:
        doctor = model.doctors.get(doc_id)
        prefs = problem.preferences.get(doc_id)

        # If preferences are missing, treat as empty (no soft penalties added).
        if prefs is None:
            continue

        # Decide weight for missing preferred concrete days (head + role combined in scoring).
        is_head = bool(doctor.is_head) if doctor else False
        role = doctor.role if doctor else DoctorRole.resident
        miss_weight = scoring.preferred_day_miss_weight_for_doctor(is_head=is_head, role=role)

        # Preferred onsite days
        for day in prefs.preferred_onsite_days:
            x_var = x.get((day, ShiftType.onsite, doc_id))
            if x_var is None:
                # Slot not present (forbidden / filtered). MVP: skip preference (cannot satisfy anyway).
                continue

            miss = cp.NewBoolVar(f"miss_pref_ons_d{day}_doc{doc_id}")
            # miss = 1 iff x_var == 0  =>  miss + x_var == 1 for BoolVars
            cp.Add(miss + x_var == 1)

            penalty_terms.append(int(miss_weight) * miss)
            ub += int(miss_weight)

        # Preferred oncall days
        for day in prefs.preferred_oncall_days:
            x_var = x.get((day, ShiftType.oncall, doc_id))
            if x_var is None:
                continue

            miss = cp.NewBoolVar(f"miss_pref_oncall_d{day}_doc{doc_id}")
            cp.Add(miss + x_var == 1)

            penalty_terms.append(int(miss_weight) * miss)
            ub += int(miss_weight)

    if penalty_terms:
        total_penalty = cp.NewIntVar(0, int(ub), "total_preferred_days_penalty")
        cp.Add(total_penalty == sum(penalty_terms))
    else:
        total_penalty = cp.NewIntVar(0, 0, "total_preferred_days_penalty")
        cp.Add(total_penalty == 0)

    return total_penalty


def attach_totals_objective(
    cp: cp_model.CpModel,
    x: Dict[Tuple[int, ShiftType, int], cp_model.IntVar],
    model: HardModel,
    problem: ProblemData,
) -> cp_model.IntVar:
    """
    Add penalties related to:
    - monthly totals (max/target for onsite/oncall),
    - weekend totals (max/target for onsite/oncall weekends).

    Notes:
    - "max_*" uses an escalating (quadratic) penalty: excess^2.
      This discourages concentrating a large max-violation on one doctor.
    - "target_*" uses an escalating (quadratic) penalty: deviation^2 (over and under separately).
      This discourages concentrating a large deviation on one doctor.

    Returns:
        total_penalty: IntVar with the sum of totals penalties.
    """
    penalty_terms: List[cp_model.LinearExpr] = []
    ub: int = 0  # upper bound for total_penalty

    # Weekend days set (calendar days where weekday is Sat (5) or Sun (6)).
    weekend_days: Set[int] = {d for d in model.days if datetime(model.year, model.month, d).weekday() in (5, 6)}

    max_dev = len(model.days)
    max_w_dev = len(weekend_days)

    for doc_id in model.participant_doctor_ids:
        prefs = problem.preferences.get(doc_id)

        # If preferences are missing, treat as empty (no soft penalties added).
        if prefs is None:
            continue

        # -----------------------------
        # 1) Monthly totals (onsite/oncall)
        # -----------------------------

        onsite_terms = [x[(d, ShiftType.onsite, doc_id)] for d in model.days if (d, ShiftType.onsite, doc_id) in x]
        oncall_terms = [x[(d, ShiftType.oncall, doc_id)] for d in model.days if (d, ShiftType.oncall, doc_id) in x]

        total_onsite = cp.NewIntVar(0, max_dev, f"tot_ons_doc{doc_id}")
        total_oncall = cp.NewIntVar(0, max_dev, f"tot_oncall_doc{doc_id}")

        cp.Add(total_onsite == (sum(onsite_terms) if onsite_terms else 0))
        cp.Add(total_oncall == (sum(oncall_terms) if oncall_terms else 0))

        # max totals ->
        # penalize excess above max with escalating (quadratic) penalty for fair distribution among doctors
        if prefs.max_onsite_total is not None:
            max_ons = int(prefs.max_onsite_total)

            excess_ons = cp.NewIntVar(0, max_dev, f"excess_ons_doc{doc_id}")
            cp.Add(excess_ons >= total_onsite - max_ons)
            cp.Add(excess_ons >= 0)

            # Escalating (quadratic) penalty: excess^2 so bigger max violations hurt much more.
            excess_ons_sq = cp.NewIntVar(0, max_dev * max_dev, f"excess_ons_sq_doc{doc_id}")
            cp.AddMultiplicationEquality(excess_ons_sq, excess_ons, excess_ons)

            penalty_terms.append(int(scoring.MAX_TOTAL_EXCESS_WEIGHT) * excess_ons_sq)
            ub += int(scoring.MAX_TOTAL_EXCESS_WEIGHT) * (max_dev * max_dev)

        if prefs.max_oncall_total is not None:
            max_onc = int(prefs.max_oncall_total)

            excess_onc = cp.NewIntVar(0, max_dev, f"excess_oncall_doc{doc_id}")
            cp.Add(excess_onc >= total_oncall - max_onc)
            cp.Add(excess_onc >= 0)

            # Escalating (quadratic) penalty: excess^2 so bigger max violations hurt much more.
            excess_onc_sq = cp.NewIntVar(0, max_dev * max_dev, f"excess_oncall_sq_doc{doc_id}")
            cp.AddMultiplicationEquality(excess_onc_sq, excess_onc, excess_onc)

            penalty_terms.append(int(scoring.MAX_TOTAL_EXCESS_WEIGHT) * excess_onc_sq)
            ub += int(scoring.MAX_TOTAL_EXCESS_WEIGHT) * (max_dev * max_dev)

        # target totals ->
        # penalize deviation (over + under) with escalating (quadratic) penalty for fair distribution among doctors
        if prefs.target_onsite_total is not None:
            tgt_ons = int(prefs.target_onsite_total)

            over = cp.NewIntVar(0, max_dev, f"tgt_over_ons_doc{doc_id}")
            under = cp.NewIntVar(0, max_dev, f"tgt_under_ons_doc{doc_id}")

            cp.Add(over >= total_onsite - tgt_ons)
            cp.Add(over >= 0)
            cp.Add(under >= tgt_ons - total_onsite)
            cp.Add(under >= 0)

            over_sq = cp.NewIntVar(0, max_dev * max_dev, f"tgt_over_ons_sq_doc{doc_id}")
            under_sq = cp.NewIntVar(0, max_dev * max_dev, f"tgt_under_ons_sq_doc{doc_id}")
            cp.AddMultiplicationEquality(over_sq, over, over)
            cp.AddMultiplicationEquality(under_sq, under, under)

            penalty_terms.append(int(scoring.TARGET_TOTAL_DEVIATION_WEIGHT) * over_sq)
            penalty_terms.append(int(scoring.TARGET_TOTAL_DEVIATION_WEIGHT) * under_sq)
            ub += int(scoring.TARGET_TOTAL_DEVIATION_WEIGHT) * (max_dev * max_dev) * 2

        if prefs.target_oncall_total is not None:
            tgt_onc = int(prefs.target_oncall_total)

            over = cp.NewIntVar(0, max_dev, f"tgt_over_oncall_doc{doc_id}")
            under = cp.NewIntVar(0, max_dev, f"tgt_under_oncall_doc{doc_id}")

            cp.Add(over >= total_oncall - tgt_onc)
            cp.Add(over >= 0)
            cp.Add(under >= tgt_onc - total_oncall)
            cp.Add(under >= 0)

            over_sq = cp.NewIntVar(0, max_dev * max_dev, f"tgt_over_oncall_sq_doc{doc_id}")
            under_sq = cp.NewIntVar(0, max_dev * max_dev, f"tgt_under_oncall_sq_doc{doc_id}")
            cp.AddMultiplicationEquality(over_sq, over, over)
            cp.AddMultiplicationEquality(under_sq, under, under)

            penalty_terms.append(int(scoring.TARGET_TOTAL_DEVIATION_WEIGHT) * over_sq)
            penalty_terms.append(int(scoring.TARGET_TOTAL_DEVIATION_WEIGHT) * under_sq)
            ub += int(scoring.TARGET_TOTAL_DEVIATION_WEIGHT) * (max_dev * max_dev) * 2

        # -----------------------------
        # 2) Weekend totals (onsite/oncall)
        # -----------------------------

        onsite_w_terms = [x[(d, ShiftType.onsite, doc_id)] for d in weekend_days if (d, ShiftType.onsite, doc_id) in x]
        oncall_w_terms = [x[(d, ShiftType.oncall, doc_id)] for d in weekend_days if (d, ShiftType.oncall, doc_id) in x]

        total_onsite_weekends = cp.NewIntVar(0, max_w_dev, f"tot_ons_w_doc{doc_id}")
        total_oncall_weekends = cp.NewIntVar(0, max_w_dev, f"tot_oncall_w_doc{doc_id}")

        cp.Add(total_onsite_weekends == (sum(onsite_w_terms) if onsite_w_terms else 0))
        cp.Add(total_oncall_weekends == (sum(oncall_w_terms) if oncall_w_terms else 0))

        # max weekend totals -> penalize excess above max
        if prefs.max_onsite_weekends is not None:
            max_ons_w = int(prefs.max_onsite_weekends)

            excess_ons_w = cp.NewIntVar(0, max_w_dev, f"excess_ons_w_doc{doc_id}")
            cp.Add(excess_ons_w >= total_onsite_weekends - max_ons_w)
            cp.Add(excess_ons_w >= 0)

            # Escalating (quadratic) penalty: excess^2 so bigger weekend-max violations hurt much more.
            excess_ons_w_sq = cp.NewIntVar(0, max_w_dev * max_w_dev, f"excess_ons_w_sq_doc{doc_id}")
            cp.AddMultiplicationEquality(excess_ons_w_sq, excess_ons_w, excess_ons_w)

            penalty_terms.append(int(scoring.MAX_WEEKEND_EXCESS_WEIGHT) * excess_ons_w_sq)
            ub += int(scoring.MAX_WEEKEND_EXCESS_WEIGHT) * (max_w_dev * max_w_dev)

        if prefs.max_oncall_weekends is not None:
            max_onc_w = int(prefs.max_oncall_weekends)

            excess_onc_w = cp.NewIntVar(0, max_w_dev, f"excess_oncall_w_doc{doc_id}")
            cp.Add(excess_onc_w >= total_oncall_weekends - max_onc_w)
            cp.Add(excess_onc_w >= 0)

            # Escalating (quadratic) penalty: excess^2 so bigger weekend-max violations hurt much more.
            excess_onc_w_sq = cp.NewIntVar(0, max_w_dev * max_w_dev, f"excess_oncall_w_sq_doc{doc_id}")
            cp.AddMultiplicationEquality(excess_onc_w_sq, excess_onc_w, excess_onc_w)

            penalty_terms.append(int(scoring.MAX_WEEKEND_EXCESS_WEIGHT) * excess_onc_w_sq)
            ub += int(scoring.MAX_WEEKEND_EXCESS_WEIGHT) * (max_w_dev * max_w_dev)

        # target weekend totals -> penalize deviation (over + under) with escalating (quadratic) penalty
        if prefs.target_onsite_weekends is not None:
            tgt_ons_w = int(prefs.target_onsite_weekends)

            over = cp.NewIntVar(0, max_w_dev, f"tgt_over_ons_w_doc{doc_id}")
            under = cp.NewIntVar(0, max_w_dev, f"tgt_under_ons_w_doc{doc_id}")

            cp.Add(over >= total_onsite_weekends - tgt_ons_w)
            cp.Add(over >= 0)
            cp.Add(under >= tgt_ons_w - total_onsite_weekends)
            cp.Add(under >= 0)

            over_sq = cp.NewIntVar(0, max_w_dev * max_w_dev, f"tgt_over_ons_w_sq_doc{doc_id}")
            under_sq = cp.NewIntVar(0, max_w_dev * max_w_dev, f"tgt_under_ons_w_sq_doc{doc_id}")
            cp.AddMultiplicationEquality(over_sq, over, over)
            cp.AddMultiplicationEquality(under_sq, under, under)

            penalty_terms.append(int(scoring.TARGET_WEEKEND_DEVIATION_WEIGHT) * over_sq)
            penalty_terms.append(int(scoring.TARGET_WEEKEND_DEVIATION_WEIGHT) * under_sq)
            ub += int(scoring.TARGET_WEEKEND_DEVIATION_WEIGHT) * (max_w_dev * max_w_dev) * 2

        if prefs.target_oncall_weekends is not None:
            tgt_onc_w = int(prefs.target_oncall_weekends)

            over = cp.NewIntVar(0, max_w_dev, f"tgt_over_oncall_w_doc{doc_id}")
            under = cp.NewIntVar(0, max_w_dev, f"tgt_under_oncall_w_doc{doc_id}")

            cp.Add(over >= total_oncall_weekends - tgt_onc_w)
            cp.Add(over >= 0)
            cp.Add(under >= tgt_onc_w - total_oncall_weekends)
            cp.Add(under >= 0)

            over_sq = cp.NewIntVar(0, max_w_dev * max_w_dev, f"tgt_over_oncall_w_sq_doc{doc_id}")
            under_sq = cp.NewIntVar(0, max_w_dev * max_w_dev, f"tgt_under_oncall_w_sq_doc{doc_id}")
            cp.AddMultiplicationEquality(over_sq, over, over)
            cp.AddMultiplicationEquality(under_sq, under, under)

            penalty_terms.append(int(scoring.TARGET_WEEKEND_DEVIATION_WEIGHT) * over_sq)
            penalty_terms.append(int(scoring.TARGET_WEEKEND_DEVIATION_WEIGHT) * under_sq)
            ub += int(scoring.TARGET_WEEKEND_DEVIATION_WEIGHT) * (max_w_dev * max_w_dev) * 2

    if penalty_terms:
        total_penalty = cp.NewIntVar(0, int(ub), "total_totals_penalty")
        cp.Add(total_penalty == sum(penalty_terms))
    else:
        total_penalty = cp.NewIntVar(0, 0, "total_totals_penalty")
        cp.Add(total_penalty == 0)

    return total_penalty


def attach_rest_objective(
    cp: cp_model.CpModel,
    x: Dict[Tuple[int, ShiftType, int], cp_model.IntVar],
    model: HardModel,
    problem: ProblemData,
) -> cp_model.IntVar:
    """
    Add rest-rule penalties to the CP-SAT model objective.

    Current rules:
    - avoid onsite -> onsite on consecutive days
    - avoid oncall -> oncall on consecutive days
    - avoid cross-shifts across consecutive days (onsite->oncall or oncall->onsite)
      with a stronger penalty for specialists than residents
    - weekend exception: Sat->Sun cross-shift is NOT penalized if
      allow_weekend_consecutive_onsite_oncall=True
    """
    penalty_terms: List[cp_model.LinearExpr] = []
    ub: int = 0  # correct upper bound for total_penalty

    for doc_id in model.participant_doctor_ids:
        doctor = model.doctors.get(doc_id)
        prefs = problem.preferences.get(doc_id)

        # Defensive defaults (keeps solver robust)
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
                penalty_terms.append(int(scoring.REST_ONS_ONS_WEIGHT) * v)
                ub += int(scoring.REST_ONS_ONS_WEIGHT)

            # oncall -> oncall
            if oncall_d is not None and oncall_dn is not None:
                v = _add_pair_violation(cp, oncall_d, oncall_dn, f"rest_oncall_oncall_d{d}_doc{doc_id}")
                penalty_terms.append(int(scoring.REST_ONCALL_ONCALL_WEIGHT) * v)
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
    if penalty_terms:
        total_penalty = cp.NewIntVar(0, int(ub), "total_rest_penalty")
        cp.Add(total_penalty == sum(penalty_terms))
    else:
        total_penalty = cp.NewIntVar(0, 0, "total_rest_penalty")
        cp.Add(total_penalty == 0)

    return total_penalty


def attach_fairness_objective(
    cp: cp_model.CpModel,
    x: Dict[Tuple[int, ShiftType, int], cp_model.IntVar],
    model: HardModel,
    problem: ProblemData,
) -> cp_model.IntVar:
    """
    Add fairness penalties across doctors within the same role group.

    ```
    Groups (MVP):
    - Heads are included in the 'specialist' fairness group.
    - specialists (DoctorRole.specialist)
    - residents (DoctorRole.resident)

    Counts considered:
    - onsite weekdays, onsite weekends,
    - oncall weekdays, oncall weekends.

    For each group and count type:
    - compute per-doctor totals,
    - compute an integer "average" (floor),
    - for each doctor choose expected:
        * if target_* is set -> expected = target (weekday uses total-minus-weekends if both exist),
        * else -> expected = group average,
    - penalize squared deviation: (abs(total - expected))^2 (escalating).

    Returns:
        total_fairness_penalty: IntVar
    """
    penalty_terms: List[cp_model.LinearExpr] = []
    ub: int = 0  # upper bound for total_fairness_penalty

    # 1) Split days into weekend vs weekday (local helper, no dependency on utils/timez.py).
    weekend_days: Set[int] = {
        d for d in model.days if datetime(model.year, model.month, d).weekday() in (5, 6)  # 5=Sat, 6=Sun
    }
    weekday_days: List[int] = [d for d in model.days if d not in weekend_days]

    # 2) Build doctor groups by role.
    group_to_doctors: Dict[str, List[int]] = {
        "specialist": [],
        "resident": [],
    }

    for doc_id in sorted(model.participant_doctor_ids):
        doctor = model.doctors.get(doc_id)
        if not doctor:
            continue

        if doctor.role == DoctorRole.specialist:
            # Heads are included in the 'specialist' fairness group.
            group_to_doctors["specialist"].append(doc_id)
        else:
            group_to_doctors["resident"].append(doc_id)

    # 2.5) NEW: compute deterministic per-doctor expected (business algorithm)
    expected_map = compute_expected_map_for_fairness(
        model=model,
        problem=problem,
        group_to_doctors=group_to_doctors,
    )

    def _add_fairness_for_category(
        *,
        group_name: str,
        group_doctors: List[int],
        category_name: str,
        days: List[int],
        shift_type: ShiftType,
        max_per_doctor: int,
        weight: int,
    ) -> None:
        """
        Add fairness penalty terms for one category (e.g. onsite weekday in specialists).

        We compute:
        - total shifts for each doctor in this category,
        - sum of totals across the group,
        - average_total as an integer FLOOR:
            n * average_total <= sum_totals <= n * average_total + (n - 1)
        (This avoids forcing divisibility, which could accidentally make the model infeasible.)
        - abs deviation per doctor from average_total,
        - weighted sum of abs deviations goes to the objective.
        """
        nonlocal ub
        n = len(group_doctors)
        if n <= 1:
            # Fairness does not make sense for a group of size 0 or 1.
            return

        totals: List[cp_model.IntVar] = []
        for doc_id in group_doctors:
            total = cp.NewIntVar(0, max_per_doctor, f"fair_tot_{group_name}_{category_name}_doc{doc_id}")

            terms = [x[(d, shift_type, doc_id)] for d in days if (d, shift_type, doc_id) in x]

            if terms:
                cp.Add(total == sum(terms))
            else:
                cp.Add(total == 0)

            totals.append(total)

        for idx, doc_id in enumerate(group_doctors):
            # NEW: expected comes from our business algorithm (group targets + caps + +1 rotation + personal targets)
            expected_value = expected_map.get((int(doc_id), shift_type, category_name), 0)
            expected_value = max(0, min(int(expected_value), int(max_per_doctor)))

            expected_total = cp.NewIntVar(0, max_per_doctor, f"fair_expected_{group_name}_{category_name}_doc{doc_id}")
            cp.Add(expected_total == int(expected_value))

            deviation_pos = cp.NewIntVar(0, max_per_doctor, f"fair_dev_pos_{group_name}_{category_name}_doc{doc_id}")
            deviation_neg = cp.NewIntVar(0, max_per_doctor, f"fair_dev_neg_{group_name}_{category_name}_doc{doc_id}")

            cp.Add(deviation_pos >= totals[idx] - expected_total)
            cp.Add(deviation_pos >= 0)
            cp.Add(deviation_neg >= expected_total - totals[idx])
            cp.Add(deviation_neg >= 0)

            abs_dev = cp.NewIntVar(0, max_per_doctor, f"fair_abs_dev_{group_name}_{category_name}_doc{doc_id}")
            cp.Add(abs_dev == deviation_pos + deviation_neg)

            # Escalating penalty: abs_dev^2.
            # This makes "2 away for one doctor" worse than "1 away for two doctors".
            abs_dev_sq = cp.NewIntVar(
                0, max_per_doctor * max_per_doctor, f"fair_abs_dev_sq_{group_name}_{category_name}_doc{doc_id}"
            )
            cp.AddMultiplicationEquality(abs_dev_sq, abs_dev, abs_dev)

            penalty_terms.append(int(weight) * abs_dev_sq)
            ub += int(weight) * (int(max_per_doctor) * int(max_per_doctor))

    # 3) Add fairness per group, per (shift_type x weekday/weekend).
    for group_name, group_doctors in group_to_doctors.items():
        if len(group_doctors) <= 1:
            continue

        # Onsite weekdays
        _add_fairness_for_category(
            group_name=group_name,
            group_doctors=group_doctors,
            category_name="onsite_weekday",
            days=weekday_days,
            shift_type=ShiftType.onsite,
            max_per_doctor=len(weekday_days),
            weight=scoring.fairness_weight(shift_type=ShiftType.onsite, is_weekend=False),
        )

        # Onsite weekends
        _add_fairness_for_category(
            group_name=group_name,
            group_doctors=group_doctors,
            category_name="onsite_weekend",
            days=list(weekend_days),
            shift_type=ShiftType.onsite,
            max_per_doctor=len(weekend_days),
            weight=scoring.fairness_weight(shift_type=ShiftType.onsite, is_weekend=True),
        )

        # Oncall weekdays
        _add_fairness_for_category(
            group_name=group_name,
            group_doctors=group_doctors,
            category_name="oncall_weekday",
            days=weekday_days,
            shift_type=ShiftType.oncall,
            max_per_doctor=len(weekday_days),
            weight=scoring.fairness_weight(shift_type=ShiftType.oncall, is_weekend=False),
        )

        # Oncall weekends
        _add_fairness_for_category(
            group_name=group_name,
            group_doctors=group_doctors,
            category_name="oncall_weekend",
            days=list(weekend_days),
            shift_type=ShiftType.oncall,
            max_per_doctor=len(weekend_days),
            weight=scoring.fairness_weight(shift_type=ShiftType.oncall, is_weekend=True),
        )

    # 4) Wrap terms into a single IntVar.
    if penalty_terms:
        total_penalty = cp.NewIntVar(0, int(ub), "total_fairness_penalty")
        cp.Add(total_penalty == sum(penalty_terms))
    else:
        total_penalty = cp.NewIntVar(0, 0, "total_fairness_penalty")
        cp.Add(total_penalty == 0)

    return total_penalty


def attach_weekday_patterns_objective(
    cp: cp_model.CpModel,
    x: Dict[Tuple[int, ShiftType, int], cp_model.IntVar],
    model: HardModel,
    problem: ProblemData,
) -> cp_model.IntVar:
    """
    Add lower-priority weekday-pattern terms:
    - preferred_**weekdays -> small bonus
    - avoid**_weekdays -> small penalty

    ```
    Returns:
        total_weekday_patterns_penalty: IntVar (can be negative because of bonuses)
    """
    terms: List[cp_model.LinearExpr] = []

    ub_penalty: int = 0  # sum of all possible avoid penalties
    ub_bonus: int = 0  # sum of all possible preferred bonuses

    preferred_w = int(scoring.weekday_pattern_weight(kind="preferred"))
    avoid_w = int(scoring.weekday_pattern_weight(kind="avoid"))

    for doc_id in model.participant_doctor_ids:
        prefs = problem.preferences.get(doc_id)
        if prefs is None:
            continue

        # Use sets for fast "weekday in list" checks.
        pref_onsite_wd = set(int(v) for v in prefs.preferred_onsite_weekdays)
        pref_oncall_wd = set(int(v) for v in prefs.preferred_oncall_weekdays)
        avoid_onsite_wd = set(int(v) for v in prefs.avoid_onsite_weekdays)
        avoid_oncall_wd = set(int(v) for v in prefs.avoid_oncall_weekdays)

        for d in model.days:
            wd = datetime(model.year, model.month, d).weekday()  # 0=Mon .. 6=Sun

            # -----------------------------
            # Preferred weekdays -> BONUS (negative term)
            # -----------------------------
            if wd in pref_onsite_wd:
                x_var = x.get((d, ShiftType.onsite, doc_id))
                if x_var is not None:
                    terms.append((-preferred_w) * x_var)
                    ub_bonus += preferred_w  # x_var <= 1

            if wd in pref_oncall_wd:
                x_var = x.get((d, ShiftType.oncall, doc_id))
                if x_var is not None:
                    terms.append((-preferred_w) * x_var)
                    ub_bonus += preferred_w

            # -----------------------------
            # Avoid weekdays -> PENALTY (positive term)
            # -----------------------------
            if wd in avoid_onsite_wd:
                x_var = x.get((d, ShiftType.onsite, doc_id))
                if x_var is not None:
                    terms.append(avoid_w * x_var)
                    ub_penalty += avoid_w

            if wd in avoid_oncall_wd:
                x_var = x.get((d, ShiftType.oncall, doc_id))
                if x_var is not None:
                    terms.append(avoid_w * x_var)
                    ub_penalty += avoid_w

    if terms:
        total_penalty = cp.NewIntVar(-int(ub_bonus), int(ub_penalty), "total_weekday_patterns_penalty")
        cp.Add(total_penalty == sum(terms))
    else:
        total_penalty = cp.NewIntVar(0, 0, "total_weekday_patterns_penalty")
        cp.Add(total_penalty == 0)

    return total_penalty


def attach_preferred_partners_objective(
    cp: cp_model.CpModel,
    x: Dict[Tuple[int, ShiftType, int], cp_model.IntVar],
    model: HardModel,
    problem: ProblemData,
) -> cp_model.IntVar:
    """
    Add lower-priority preferred-partners bonus.

    For each preferred pair (doc, partner) and each day:
    - bonus if both doctors work that day (any shift).
    We model the bonus as a NEGATIVE penalty term (so Minimize prefers it).

    Returns:
        total_preferred_partners_penalty: IntVar (can be negative)
    """
    terms: List[cp_model.LinearExpr] = []

    bonus_w = int(scoring.preferred_partner_bonus_weight())

    # Collect unique pairs (doc_id < partner_id) to avoid double-counting.
    pairs: List[Tuple[int, int]] = []
    participants = set(model.participant_doctor_ids)

    for doc_id in sorted(model.participant_doctor_ids):
        prefs = problem.preferences.get(doc_id)
        if prefs is None:
            continue

        partners = list(prefs.preferred_partners or [])
        for partner_id in partners:
            partner_id = int(partner_id)
            if partner_id not in participants:
                continue
            if doc_id >= partner_id:
                continue
            pairs.append((int(doc_id), int(partner_id)))

    if not pairs or not model.days:
        total_penalty = cp.NewIntVar(0, 0, "total_preferred_partners_penalty")
        cp.Add(total_penalty == 0)
        return total_penalty

    # Upper/lower bounds:
    # - only bonuses (negative), so ub = 0
    # - most negative happens when "together" is 1 for every (pair, day)
    max_together_count = len(pairs) * len(model.days)
    lb = -int(bonus_w) * int(max_together_count)
    ub = 0

    def _works_on_day(*, day: int, doc_id: int) -> cp_model.IntVar:
        """
        Return BoolVar == 1 if doctor works ANY shift that day.

        Defensive:
        - if x vars are missing (forbidden slots), works == 0
        - does NOT assume sum(terms) <= 1 (we encode OR logic)
        """
        doc_terms: List[cp_model.IntVar] = []
        v1 = x.get((day, ShiftType.onsite, doc_id))
        v2 = x.get((day, ShiftType.oncall, doc_id))
        if v1 is not None:
            doc_terms.append(v1)
        if v2 is not None:
            doc_terms.append(v2)

        works = cp.NewBoolVar(f"works_d{int(day)}_doc{int(doc_id)}")
        if not doc_terms:
            cp.Add(works == 0)
            return works

        s = sum(doc_terms)
        # works = 1 if any term == 1, else 0
        cp.Add(s >= works)
        cp.Add(s <= len(doc_terms) * works)
        return works

    for doc_id, partner_id in pairs:
        for d in model.days:
            works_doc = _works_on_day(day=int(d), doc_id=int(doc_id))
            works_partner = _works_on_day(day=int(d), doc_id=int(partner_id))

            together = cp.NewBoolVar(f"together_d{int(d)}_doc{int(doc_id)}_p{int(partner_id)}")
            cp.AddMultiplicationEquality(together, [works_doc, works_partner])

            # Bonus as negative penalty term.
            terms.append((-bonus_w) * together)

    if terms:
        total_penalty = cp.NewIntVar(int(lb), int(ub), "total_preferred_partners_penalty")
        cp.Add(total_penalty == sum(terms))
    else:
        total_penalty = cp.NewIntVar(0, 0, "total_preferred_partners_penalty")
        cp.Add(total_penalty == 0)

    return total_penalty


def attach_avoid_friday_if_weekend_off_objective(
    cp: cp_model.CpModel,
    x: Dict[Tuple[int, ShiftType, int], cp_model.IntVar],
    model: HardModel,
    problem: ProblemData,
) -> cp_model.IntVar:
    """
    Add a small penalty when a doctor works on Friday and has the whole following weekend off.

    Definition (MVP):
    - Friday day = weekday() == 4
    - We look only at the immediate next Saturday and Sunday: (fri+1, fri+2),
      but only if they exist in model.days and are actually Sat/Sun.
    - A doctor "works" on a day if they have onsite OR oncall assignment on that day.

    Returns:
        total_friday_free_weekend_penalty: IntVar
    """
    terms: List[cp_model.LinearExpr] = []
    ub: int = 0

    weight = int(scoring.friday_with_free_weekend_weight())

    days_set: Set[int] = set(int(d) for d in model.days)

    def _weekday(day: int) -> int:
        """
        Return weekday for a given day number.
        Uses precomputed problem.weekdays if available, otherwise falls back to datetime().
        """
        wd = problem.weekdays.get(int(day))
        if wd is not None:
            return int(wd)
        return datetime(problem.year, problem.month, int(day)).weekday()

    # 1) Collect Fridays that have a full weekend (Sat+Sun) right after them inside this model.
    fridays_with_weekend: List[int] = []
    for d in days_set:
        if _weekday(int(d)) != 4:  # 4=Friday
            continue

        sat = int(d) + 1
        sun = int(d) + 2

        # Defensive: weekend days must exist in the model and must really be Sat/Sun.
        if sat not in days_set or sun not in days_set:
            continue
        if _weekday(sat) != 5 or _weekday(sun) != 6:  # 5=Sat, 6=Sun
            continue

        fridays_with_weekend.append(int(d))

    if not fridays_with_weekend:
        total_penalty = cp.NewIntVar(0, 0, "total_friday_free_weekend_penalty")
        cp.Add(total_penalty == 0)
        return total_penalty

    def _works_on_day(*, day: int, doc_id: int) -> cp_model.IntVar:
        """
        Return BoolVar == 1 if doctor works ANY shift that day (onsite OR oncall).

        Defensive:
        - if x vars are missing (forbidden slots), works == 0
        - does NOT assume sum(terms) <= 1 (we encode OR logic)
        """
        day_terms: List[cp_model.IntVar] = []
        v1 = x.get((int(day), ShiftType.onsite, int(doc_id)))
        v2 = x.get((int(day), ShiftType.oncall, int(doc_id)))
        if v1 is not None:
            day_terms.append(v1)
        if v2 is not None:
            day_terms.append(v2)

        works = cp.NewBoolVar(f"works_d{int(day)}_doc{int(doc_id)}")
        if not day_terms:
            cp.Add(works == 0)
            return works

        s = sum(day_terms)
        cp.Add(s >= works)
        cp.Add(s <= len(day_terms) * works)
        return works

    # 2) Add penalty terms for (doctor, friday) patterns.
    for doc_id in sorted(model.participant_doctor_ids):
        for fri in sorted(fridays_with_weekend):
            sat = int(fri) + 1
            sun = int(fri) + 2

            works_fri = _works_on_day(day=int(fri), doc_id=int(doc_id))
            works_sat = _works_on_day(day=int(sat), doc_id=int(doc_id))
            works_sun = _works_on_day(day=int(sun), doc_id=int(doc_id))

            # works_weekend = works_sat OR works_sun
            works_weekend = cp.NewBoolVar(f"works_weekend_after_fri{int(fri)}_doc{int(doc_id)}")
            cp.Add(works_weekend >= works_sat)
            cp.Add(works_weekend >= works_sun)
            cp.Add(works_weekend <= works_sat + works_sun)

            # weekend_off = NOT works_weekend
            weekend_off = cp.NewBoolVar(f"weekend_off_after_fri{int(fri)}_doc{int(doc_id)}")
            cp.Add(weekend_off + works_weekend == 1)

            # fri_with_free_weekend = works_fri AND weekend_off
            fri_with_free_weekend = cp.NewBoolVar(f"fri_free_weekend_d{int(fri)}_doc{int(doc_id)}")
            cp.AddMultiplicationEquality(fri_with_free_weekend, [works_fri, weekend_off])

            terms.append(int(weight) * fri_with_free_weekend)
            ub += int(weight)

    if terms:
        total_penalty = cp.NewIntVar(0, int(ub), "total_friday_free_weekend_penalty")
        cp.Add(total_penalty == sum(terms))
    else:
        total_penalty = cp.NewIntVar(0, 0, "total_friday_free_weekend_penalty")
        cp.Add(total_penalty == 0)

    return total_penalty
