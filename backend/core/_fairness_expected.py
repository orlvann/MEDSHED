"""
Fairness expected calculator (pure Python).

This module computes deterministic "expected" values per doctor for fairness penalties.

Why this file exists:
- objective_builder.py should focus on CP-SAT variables and objective wiring,
- fairness expected policy is business logic (counts, caps, rotation),
  so it belongs to a pure helper that we can unit-test without OR-Tools.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Tuple

from backend.core.types import HardModel, ProblemData
from backend.models.common_enums import DoctorRole, ShiftType

ExpectedKey = Tuple[int, ShiftType, str]  # (doctor_id, shift_type, category_name)


def compute_expected_map_for_fairness(
    *,
    model: HardModel,
    problem: ProblemData,
    group_to_doctors: Dict[str, List[int]],
) -> Dict[ExpectedKey, int]:
    """
    Compute deterministic expected per doctor in 4 categories:
    - onsite_weekend, onsite_weekday, oncall_weekend, oncall_weekday

    Business policy implemented (B0–B4):
    - B0: Demand is counted only for REQUIRED slots (active_days minus ignore_slots).
    - B1: Resident caps come from "full days" (both shifts required) and allowed_slots:
        * CAP_resident_onsite_total = count(full_days where any resident allowed on onsite)
        * CAP_resident_oncall_total = count(full_days where any resident allowed on oncall)
      (Models "max 1 resident per full day", split by shift capability.)
    - Forced share: if a required slot can be covered ONLY by one group, that group target must include it.
    - B2: Group targets are proportional to group size, clamped by caps and forced share.
    - B3: Split totals into weekend/weekdays with consistency fix:
        * if weekends > total -> raise total to weekends (weekends priority).
    - B4: Allocate group targets to doctors without personal targets as base/base+1,
      where +1 rotates using carryover.had_plus1_*_last.
    - Personal targets override expected for that shift type (normalized + max trimming).
    """

    # -----------------------------
    # Small helpers (pure Python)
    # -----------------------------
    def _weekday(day: int) -> int:
        # Prefer precomputed mapping from services (faster + deterministic).
        wd = problem.weekdays.get(int(day))
        if wd is not None:
            return int(wd)
        return datetime(problem.year, problem.month, int(day)).weekday()

    def _is_weekend(day: int) -> bool:
        return _weekday(int(day)) in (5, 6)  # 5=Sat, 6=Sun

    def _clamp(v: int, lo: int, hi: int) -> int:
        return max(int(lo), min(int(v), int(hi)))

    def _round_int(v: float) -> int:
        return int(round(v))

    # -----------------------------
    # Groups and basic counts
    # -----------------------------
    residents = list(group_to_doctors.get("resident", []))
    specialists = list(group_to_doctors.get("specialist", []))
    n_res = len(residents)
    n_spec = len(specialists)
    n_all = n_res + n_spec

    # Role lookup (doctor_id -> is_resident)
    is_resident: Dict[int, bool] = {}
    for did, doc in model.doctors.items():
        if doc is None:
            continue
        is_resident[int(did)] = doc.role != DoctorRole.specialist

    # -----------------------------
    # B0 — Demand R_* (required slots only)
    # -----------------------------
    R_onsite_total = 0
    R_oncall_total = 0
    R_onsite_weekends = 0
    R_oncall_weekends = 0

    for day in model.active_days:
        day = int(day)

        if (day, ShiftType.onsite) not in model.ignore_slots:
            R_onsite_total += 1
            if _is_weekend(day):
                R_onsite_weekends += 1

        if (day, ShiftType.oncall) not in model.ignore_slots:
            R_oncall_total += 1
            if _is_weekend(day):
                R_oncall_weekends += 1

    # -----------------------------
    # B1 — Resident caps from pairing on FULL days (both shifts required)
    # -----------------------------
    full_days: List[int] = []
    for day in model.active_days:
        day = int(day)
        onsite_req = (day, ShiftType.onsite) not in model.ignore_slots
        oncall_req = (day, ShiftType.oncall) not in model.ignore_slots
        if onsite_req and oncall_req:
            full_days.append(day)

    def _any_resident_allowed(day: int, shift: ShiftType) -> bool:
        allowed = model.allowed_slots.get((int(day), shift), [])
        return any(bool(is_resident.get(int(did), False)) for did in allowed)

    CAP_resident_onsite_total = sum(1 for d in full_days if _any_resident_allowed(d, ShiftType.onsite))
    CAP_resident_oncall_total = sum(1 for d in full_days if _any_resident_allowed(d, ShiftType.oncall))

    # -----------------------------
    # Forced share (feasibility-aware)
    # -----------------------------
    def _forced_counts_for_shift(shift: ShiftType) -> Tuple[int, int, int, int]:
        """
        Returns:
            forced_res_total, forced_spec_total, forced_res_weekends, forced_spec_weekends
        """
        forced_res_total = 0
        forced_spec_total = 0
        forced_res_weekends = 0
        forced_spec_weekends = 0

        for day in model.active_days:
            day = int(day)
            if (day, shift) in model.ignore_slots:
                continue

            allowed = model.allowed_slots.get((day, shift), [])
            has_res = any(bool(is_resident.get(int(did), False)) for did in allowed)
            has_spec = any(not bool(is_resident.get(int(did), False)) for did in allowed)

            if has_res and not has_spec:
                forced_res_total += 1
                if _is_weekend(day):
                    forced_res_weekends += 1
            elif has_spec and not has_res:
                forced_spec_total += 1
                if _is_weekend(day):
                    forced_spec_weekends += 1

        return forced_res_total, forced_spec_total, forced_res_weekends, forced_spec_weekends

    forced_res_ons_total, forced_spec_ons_total, forced_res_ons_wknd, forced_spec_ons_wknd = _forced_counts_for_shift(
        ShiftType.onsite
    )
    forced_res_onc_total, forced_spec_onc_total, forced_res_onc_wknd, forced_spec_onc_wknd = _forced_counts_for_shift(
        ShiftType.oncall
    )

    # -----------------------------
    # B2 — Group targets between groups (proportional, clamped)
    # -----------------------------
    share_res = (n_res / n_all) if n_all > 0 else 0.0

    def _compute_group_target_total(
        *,
        R_total: int,
        forced_res_total: int,
        forced_spec_total: int,
        cap_res_total: int,
    ) -> int:
        """
        Compute resident target total for a shift type.
        - start from proportional ideal
        - clamp by cap (pairing)
        - but must be >= forced_res_total
        - and <= R_total - forced_spec_total
        """
        if n_all <= 0:
            return int(forced_res_total)

        ideal = _round_int(R_total * share_res)
        lo = int(forced_res_total)
        hi = int(max(0, R_total - forced_spec_total))
        hi = min(int(hi), int(cap_res_total))  # apply cap
        return _clamp(int(ideal), int(lo), int(hi))

    target_resident_onsite_total = _compute_group_target_total(
        R_total=R_onsite_total,
        forced_res_total=forced_res_ons_total,
        forced_spec_total=forced_spec_ons_total,
        cap_res_total=CAP_resident_onsite_total,
    )
    target_resident_oncall_total = _compute_group_target_total(
        R_total=R_oncall_total,
        forced_res_total=forced_res_onc_total,
        forced_spec_total=forced_spec_onc_total,
        cap_res_total=CAP_resident_oncall_total,
    )

    target_specialist_onsite_total = max(0, R_onsite_total - target_resident_onsite_total)
    target_specialist_oncall_total = max(0, R_oncall_total - target_resident_oncall_total)

    # -----------------------------
    # B3 — Split group totals into weekend/weekdays (consistency fix)
    # -----------------------------
    def _split_group_total(
        *,
        group_total: int,
        R_weekends: int,
        forced_group_weekends: int,
        share: float,
    ) -> Tuple[int, int]:
        """
        Returns: (weekend_target, weekday_target)

        Policy:
        - start from proportional weekend ideal
        - clamp weekends to [forced_weekends .. min(group_total, R_weekends)]
        - ensure total >= weekends by RAISING total if needed (weekends priority)
        """
        ideal_weekends = _round_int(R_weekends * share)
        wknd = _clamp(int(ideal_weekends), int(forced_group_weekends), int(min(group_total, R_weekends)))
        fixed_total = max(int(group_total), int(wknd))  # weekends priority
        wd = int(fixed_total) - int(wknd)
        return int(wknd), int(wd)

    # Residents split
    res_ons_wknd, res_ons_wd = _split_group_total(
        group_total=target_resident_onsite_total,
        R_weekends=R_onsite_weekends,
        forced_group_weekends=forced_res_ons_wknd,
        share=share_res,
    )
    res_onc_wknd, res_onc_wd = _split_group_total(
        group_total=target_resident_oncall_total,
        R_weekends=R_oncall_weekends,
        forced_group_weekends=forced_res_onc_wknd,
        share=share_res,
    )

    # Specialists are remainder
    spec_ons_wknd = max(0, R_onsite_weekends - res_ons_wknd)
    spec_onc_wknd = max(0, R_oncall_weekends - res_onc_wknd)
    spec_ons_wd = max(0, target_specialist_onsite_total - spec_ons_wknd)
    spec_onc_wd = max(0, target_specialist_oncall_total - spec_onc_wknd)

    # -----------------------------
    # B4 — Allocate to doctors (base/base+1 with rotation), then override with personal targets
    # -----------------------------
    def _had_plus1_last(doc_id: int, category_name: str) -> bool:
        """
        category_name in:
        - onsite_weekday, onsite_weekend, oncall_weekday, oncall_weekend
        """
        co = problem.carryover
        if co is None:
            return False
        dco = co.per_doctor.get(int(doc_id))
        if dco is None:
            return False

        if category_name == "onsite_weekday":
            return bool(dco.had_plus1_onsite_weekday_last)
        if category_name == "onsite_weekend":
            return bool(dco.had_plus1_onsite_weekend_last)
        if category_name == "oncall_weekday":
            return bool(dco.had_plus1_oncall_weekday_last)
        if category_name == "oncall_weekend":
            return bool(dco.had_plus1_oncall_weekend_last)
        return False

    def _allocate_base_plus_one(doctors: List[int], target: int, category_name: str) -> Dict[int, int]:
        """
        Distribute target across doctors:
        - base = target // n
        - rem  = target % n
        - rem doctors get base+1

        Rotation:
        - doctors who did NOT have +1 last month have priority to get it now.
        - tie-breaker: doctor_id (stable/deterministic).
        """
        n = len(doctors)
        if n <= 0:
            return {}
        base = int(target) // int(n)
        rem = int(target) % int(n)

        ordered = sorted(doctors, key=lambda did: (bool(_had_plus1_last(int(did), category_name)), int(did)))

        out = {int(did): int(base) for did in doctors}
        for did in ordered[:rem]:
            out[int(did)] = int(base) + 1
        return out

    def _has_personal_target(doc_id: int, shift_type: ShiftType) -> bool:
        prefs = problem.preferences.get(int(doc_id))
        if prefs is None:
            return False
        if shift_type == ShiftType.onsite:
            return (prefs.target_onsite_total is not None) or (prefs.target_onsite_weekends is not None)
        return (prefs.target_oncall_total is not None) or (prefs.target_oncall_weekends is not None)

    expected: Dict[ExpectedKey, int] = {}

    def _fill_group_expected(group_name: str, shift_type: ShiftType, category_name: str, target_value: int) -> None:
        """
        Fill expected for doctors in group who DO NOT have personal targets for this shift type.
        """
        docs = list(group_to_doctors.get(group_name, []))
        docs_no_personal = [int(did) for did in docs if not _has_personal_target(int(did), shift_type)]
        alloc = _allocate_base_plus_one(docs_no_personal, int(target_value), category_name)
        for did, v in alloc.items():
            expected[(int(did), shift_type, category_name)] = int(v)

    # Defaults (non-personal-target doctors)
    _fill_group_expected("resident", ShiftType.onsite, "onsite_weekend", res_ons_wknd)
    _fill_group_expected("resident", ShiftType.onsite, "onsite_weekday", res_ons_wd)
    _fill_group_expected("resident", ShiftType.oncall, "oncall_weekend", res_onc_wknd)
    _fill_group_expected("resident", ShiftType.oncall, "oncall_weekday", res_onc_wd)

    _fill_group_expected("specialist", ShiftType.onsite, "onsite_weekend", spec_ons_wknd)
    _fill_group_expected("specialist", ShiftType.onsite, "onsite_weekday", spec_ons_wd)
    _fill_group_expected("specialist", ShiftType.oncall, "oncall_weekend", spec_onc_wknd)
    _fill_group_expected("specialist", ShiftType.oncall, "oncall_weekday", spec_onc_wd)

    # Personal target normalization (max trims target, clamp, weekend>total fix)
    def _normalize_personal(
        *,
        t_total: Optional[int],
        t_weekends: Optional[int],
        max_total: Optional[int],
        max_weekends: Optional[int],
        R_total_limit: int,
        R_weekend_limit: int,
    ) -> Tuple[int, int, int]:
        """
        Returns:
            (fixed_total, fixed_weekends, fixed_weekdays)
        """
        total = 0 if t_total is None else int(t_total)
        wknd = 0 if t_weekends is None else int(t_weekends)

        # If max exists and target exceeds it -> max wins (trim).
        if max_total is not None:
            total = min(int(total), int(max_total))
        if max_weekends is not None:
            wknd = min(int(wknd), int(max_weekends))

        # Clamp to month demand limits (global limits).
        total = _clamp(int(total), 0, int(R_total_limit))
        wknd = _clamp(int(wknd), 0, int(R_weekend_limit))

        # Consistency fix: weekends are part of total, so total must be >= weekends.
        fixed_total = max(int(total), int(wknd))
        fixed_wknd = int(wknd)
        fixed_wd = int(fixed_total) - int(fixed_wknd)
        return int(fixed_total), int(fixed_wknd), int(fixed_wd)

    for doc_id in sorted(model.participant_doctor_ids):
        prefs = problem.preferences.get(int(doc_id))
        if prefs is None:
            continue

        # Onsite personal targets override expected for onsite categories.
        if prefs.target_onsite_total is not None or prefs.target_onsite_weekends is not None:
            _, wknd, wd = _normalize_personal(
                t_total=prefs.target_onsite_total,
                t_weekends=prefs.target_onsite_weekends,
                max_total=getattr(prefs, "max_onsite_total", None),
                max_weekends=getattr(prefs, "max_onsite_weekends", None),
                R_total_limit=R_onsite_total,
                R_weekend_limit=R_onsite_weekends,
            )
            expected[(int(doc_id), ShiftType.onsite, "onsite_weekend")] = int(wknd)
            expected[(int(doc_id), ShiftType.onsite, "onsite_weekday")] = int(wd)

        # Oncall personal targets override expected for oncall categories.
        if prefs.target_oncall_total is not None or prefs.target_oncall_weekends is not None:
            _, wknd, wd = _normalize_personal(
                t_total=prefs.target_oncall_total,
                t_weekends=prefs.target_oncall_weekends,
                max_total=getattr(prefs, "max_oncall_total", None),
                max_weekends=getattr(prefs, "max_oncall_weekends", None),
                R_total_limit=R_oncall_total,
                R_weekend_limit=R_oncall_weekends,
            )
            expected[(int(doc_id), ShiftType.oncall, "oncall_weekend")] = int(wknd)
            expected[(int(doc_id), ShiftType.oncall, "oncall_weekday")] = int(wd)

    return expected
