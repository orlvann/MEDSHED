"""
Fairness expected calculator for EDIT stage (pure Python).

EDIT stage semantics (your latest business rules):
- Diagnostics evaluates the CURRENT schedule "as is" (after admin edits).
- All calendar days in the month are considered required for both shifts.
- Ignore markers must NOT improve metrics (a gap is a gap).
- Admin can assign anyone during edits, so we do NOT use allowed_slots to limit "who can work".
- Resident cap is driven by pairing policy:
  - Max 1 resident per day across BOTH shifts (because the other shift must be a specialist).
  - Therefore, max resident assignments in the whole month <= number_of_days.
- Fairness is measured WITHIN group allocation:
  - First decide how many assignments belong to residents vs specialists (with the resident cap).
  - Then split those group totals into onsite/oncall and weekend/weekday.
  - Then distribute to doctors in each group using base/base+1 with +1 rotation via carryover.

Personal targets:
- If a doctor has personal target(s) for a shift type, they override expected for that shift type.
- Personal targets are normalized:
  - max_* trims target_* if exceeded
  - clamp to month demand limits
  - consistency fix: total must be >= weekends (weekends are part of total)
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Tuple

from backend.core.types import HardModel, ProblemData
from backend.models.common_enums import ShiftType

ExpectedKey = Tuple[int, ShiftType, str]  # (doctor_id, shift_type, category_name)


def compute_expected_map_for_fairness_edit(
    *,
    model: HardModel,
    problem: ProblemData,
    group_to_doctors: Dict[str, List[int]],
) -> Dict[ExpectedKey, int]:
    """
    Compute deterministic expected values per doctor for fairness penalties in EDIT stage.

    Categories (same 4 as in solver fairness):
    - onsite_weekend, onsite_weekday, oncall_weekend, oncall_weekday

    Returns:
        expected_map[(doctor_id, shift_type, category_name)] = expected_count
    """

    # -----------------------------
    # Small helpers (pure Python)
    # -----------------------------
    def _weekday(day: int) -> int:
        # Prefer precomputed mapping from services (fast + deterministic).
        wd = getattr(problem, "weekdays", None)
        if isinstance(wd, dict):
            v = wd.get(int(day))
            if v is not None:
                return int(v)
        return int(datetime(problem.year, problem.month, int(day)).weekday())

    def _is_weekend(day: int) -> bool:
        return _weekday(int(day)) in (5, 6)  # 5=Sat, 6=Sun

    def _clamp(v: int, lo: int, hi: int) -> int:
        return max(int(lo), min(int(v), int(hi)))

    def _round_int(v: float) -> int:
        return int(round(v))

    # -----------------------------
    # Participants + groups
    # -----------------------------
    residents = list(group_to_doctors.get("resident", []))
    specialists = list(group_to_doctors.get("specialist", []))
    n_res = len(residents)
    n_spec = len(specialists)
    n_all = n_res + n_spec

    # -----------------------------
    # Demand in EDIT stage:
    # - All days required for both shifts
    # -----------------------------
    all_days: List[int] = [int(d) for d in getattr(problem, "days", [])]
    days_count = len(all_days)

    R_onsite_total = int(days_count)
    R_oncall_total = int(days_count)

    R_onsite_weekends = sum(1 for d in all_days if _is_weekend(d))
    R_oncall_weekends = int(R_onsite_weekends)  # same calendar weekends

    # Total required assignments in month (both shifts):
    R_all_total = int(R_onsite_total + R_oncall_total)

    # -----------------------------
    # Resident cap in EDIT stage:
    # - Max 1 resident per day across BOTH shifts => cap_res_all = number of days
    # -----------------------------
    CAP_resident_all = int(days_count)

    # -----------------------------
    # Group totals between groups (EDIT stage)
    # - Ideal share is proportional to group size
    # - Then clamp by resident cap
    # -----------------------------
    share_res = (n_res / n_all) if n_all > 0 else 0.0

    # No forced-share in EDIT stage (admin can override availability/preferences by manual calling).
    forced_res_all = 0
    forced_spec_all = 0

    if n_all <= 0:
        target_resident_all = int(forced_res_all)
    else:
        ideal_res_all = _round_int(R_all_total * share_res)
        lo = int(forced_res_all)
        hi = int(max(0, R_all_total - forced_spec_all))
        hi = min(int(hi), int(CAP_resident_all))
        target_resident_all = _clamp(int(ideal_res_all), int(lo), int(hi))

    # -----------------------------
    # Split resident+specialist totals into shift types (onsite vs oncall)
    # - Since both shifts have equal demand (days_count each),
    #   the recommended choice is proportional split by demand.
    # -----------------------------
    def _split_between_shifts(total: int) -> tuple[int, int]:
        if R_all_total <= 0:
            return 0, 0
        ideal_ons = _round_int(total * (R_onsite_total / R_all_total))
        ons = _clamp(int(ideal_ons), 0, int(R_onsite_total))
        onc = int(total) - int(ons)
        onc = _clamp(int(onc), 0, int(R_oncall_total))
        # If clamp trimmed onc, push back into onsite if possible (keep sum close to total)
        if ons + onc != total:
            remaining = int(total) - int(ons + onc)
            if remaining > 0:
                # try to add to onsite first
                add = min(remaining, int(R_onsite_total - ons))
                ons += add
                remaining -= add
                if remaining > 0:
                    onc += min(remaining, int(R_oncall_total - onc))
            elif remaining < 0:
                # remove from onsite first
                rem = min(-remaining, ons)
                ons -= rem
                remaining += rem
                if remaining < 0:
                    onc = max(0, onc + remaining)
        return int(ons), int(onc)

    target_resident_onsite_total, target_resident_oncall_total = _split_between_shifts(target_resident_all)
    target_specialist_onsite_total = max(0, int(R_onsite_total - target_resident_onsite_total))
    target_specialist_oncall_total = max(0, int(R_oncall_total - target_resident_oncall_total))

    # -----------------------------
    # Split totals into weekend/weekdays (consistency fix: weekends priority)
    # -----------------------------
    def _split_total_into_weekend_weekday(
        *,
        group_total: int,
        R_weekends: int,
        share: float,
        forced_weekends: int = 0,
    ) -> tuple[int, int]:
        """
        Returns (weekend_target, weekday_target).

        Policy:
        - start from proportional weekend ideal
        - clamp weekends to [forced_weekends .. min(group_total, R_weekends)]
        - ensure total >= weekends by RAISING total if needed (weekends priority)
        """
        ideal_wknd = _round_int(R_weekends * share) if n_all > 0 else 0
        wknd = _clamp(int(ideal_wknd), int(forced_weekends), int(min(group_total, R_weekends)))
        fixed_total = max(int(group_total), int(wknd))
        wd = int(fixed_total) - int(wknd)
        return int(wknd), int(wd)

    # Residents weekend split per shift
    res_ons_wknd, res_ons_wd = _split_total_into_weekend_weekday(
        group_total=target_resident_onsite_total, R_weekends=R_onsite_weekends, share=share_res, forced_weekends=0
    )
    res_onc_wknd, res_onc_wd = _split_total_into_weekend_weekday(
        group_total=target_resident_oncall_total, R_weekends=R_oncall_weekends, share=share_res, forced_weekends=0
    )

    # Specialists are remainder per shift
    spec_ons_wknd = max(0, int(R_onsite_weekends - res_ons_wknd))
    spec_onc_wknd = max(0, int(R_oncall_weekends - res_onc_wknd))
    spec_ons_wd = max(0, int(target_specialist_onsite_total - spec_ons_wknd))
    spec_onc_wd = max(0, int(target_specialist_oncall_total - spec_onc_wknd))

    # -----------------------------
    # Rotation helper (+1 distribution)
    # -----------------------------
    def _had_plus1_last(doc_id: int, category_name: str) -> bool:
        co = getattr(problem, "carryover", None)
        if co is None:
            return False
        per_doc = getattr(co, "per_doctor", None)
        if not isinstance(per_doc, dict):
            return False
        dco = per_doc.get(int(doc_id))
        if dco is None:
            return False

        if category_name == "onsite_weekday":
            return bool(getattr(dco, "had_plus1_onsite_weekday_last", False))
        if category_name == "onsite_weekend":
            return bool(getattr(dco, "had_plus1_onsite_weekend_last", False))
        if category_name == "oncall_weekday":
            return bool(getattr(dco, "had_plus1_oncall_weekday_last", False))
        if category_name == "oncall_weekend":
            return bool(getattr(dco, "had_plus1_oncall_weekend_last", False))
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

    # -----------------------------
    # Personal targets override (with normalization)
    # -----------------------------
    def _has_personal_target(doc_id: int, shift_type: ShiftType) -> bool:
        prefs = problem.preferences.get(int(doc_id))
        if prefs is None:
            return False
        if shift_type == ShiftType.onsite:
            return (getattr(prefs, "target_onsite_total", None) is not None) or (
                getattr(prefs, "target_onsite_weekends", None) is not None
            )
        return (getattr(prefs, "target_oncall_total", None) is not None) or (
            getattr(prefs, "target_oncall_weekends", None) is not None
        )

    def _normalize_personal(
        *,
        t_total: Optional[int],
        t_weekends: Optional[int],
        max_total: Optional[int],
        max_weekends: Optional[int],
        R_total_limit: int,
        R_weekend_limit: int,
    ) -> tuple[int, int, int]:
        """
        Returns (fixed_total, fixed_weekends, fixed_weekdays).

        Rules:
        - max trims targets (max wins over target if target > max)
        - clamp to month demand limits
        - consistency fix: total must be >= weekends (weekends are part of total)
        """
        total = 0 if t_total is None else int(t_total)
        wknd = 0 if t_weekends is None else int(t_weekends)

        if max_total is not None:
            total = min(int(total), int(max_total))
        if max_weekends is not None:
            wknd = min(int(wknd), int(max_weekends))

        total = _clamp(int(total), 0, int(R_total_limit))
        wknd = _clamp(int(wknd), 0, int(R_weekend_limit))

        fixed_total = max(int(total), int(wknd))
        fixed_wknd = int(wknd)
        fixed_wd = int(fixed_total) - int(fixed_wknd)
        return int(fixed_total), int(fixed_wknd), int(fixed_wd)

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

    # Defaults (non-personal doctors)
    _fill_group_expected("resident", ShiftType.onsite, "onsite_weekend", res_ons_wknd)
    _fill_group_expected("resident", ShiftType.onsite, "onsite_weekday", res_ons_wd)
    _fill_group_expected("resident", ShiftType.oncall, "oncall_weekend", res_onc_wknd)
    _fill_group_expected("resident", ShiftType.oncall, "oncall_weekday", res_onc_wd)

    _fill_group_expected("specialist", ShiftType.onsite, "onsite_weekend", spec_ons_wknd)
    _fill_group_expected("specialist", ShiftType.onsite, "onsite_weekday", spec_ons_wd)
    _fill_group_expected("specialist", ShiftType.oncall, "oncall_weekend", spec_onc_wknd)
    _fill_group_expected("specialist", ShiftType.oncall, "oncall_weekday", spec_onc_wd)

    # Personal overrides
    for doc_id in sorted(model.participant_doctor_ids):
        prefs = problem.preferences.get(int(doc_id))
        if prefs is None:
            continue

        # Onsite personal targets
        if (
            getattr(prefs, "target_onsite_total", None) is not None
            or getattr(prefs, "target_onsite_weekends", None) is not None
        ):
            _, wknd, wd = _normalize_personal(
                t_total=getattr(prefs, "target_onsite_total", None),
                t_weekends=getattr(prefs, "target_onsite_weekends", None),
                max_total=getattr(prefs, "max_onsite_total", None),
                max_weekends=getattr(prefs, "max_onsite_weekends", None),
                R_total_limit=R_onsite_total,
                R_weekend_limit=R_onsite_weekends,
            )
            expected[(int(doc_id), ShiftType.onsite, "onsite_weekend")] = int(wknd)
            expected[(int(doc_id), ShiftType.onsite, "onsite_weekday")] = int(wd)

        # Oncall personal targets
        if (
            getattr(prefs, "target_oncall_total", None) is not None
            or getattr(prefs, "target_oncall_weekends", None) is not None
        ):
            _, wknd, wd = _normalize_personal(
                t_total=getattr(prefs, "target_oncall_total", None),
                t_weekends=getattr(prefs, "target_oncall_weekends", None),
                max_total=getattr(prefs, "max_oncall_total", None),
                max_weekends=getattr(prefs, "max_oncall_weekends", None),
                R_total_limit=R_oncall_total,
                R_weekend_limit=R_oncall_weekends,
            )
            expected[(int(doc_id), ShiftType.oncall, "oncall_weekend")] = int(wknd)
            expected[(int(doc_id), ShiftType.oncall, "oncall_weekday")] = int(wd)

    return expected
