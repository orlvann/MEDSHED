# backend/core/diagnostics.py
"""
Diagnostics (core) — compute schedule quality metrics from a snapshot payload.

This module must stay "pure core":
- no DB access,
- no FastAPI/Pydantic,
- operates only on ProblemData + snapshot payload dict.

It produces a JSON-serializable dict for storage in ScheduleDiagnostics.quality:
{
  "summary": {...},
  "details": {...}  # optional, can be None
}
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from backend.core import scoring
from backend.core.types import ProblemData
from backend.models.common_enums import DoctorRole, ShiftType

# ----------------------------- small parsing helpers -----------------------------


def _normalize_shift_type(raw: Any) -> Optional[ShiftType]:
    """
    Convert different shift-type encodings into our ShiftType enum.

    We accept (defensive):
    - ShiftType enum
    - "onsite" / "oncall"
    - legacy strings like "on_duty" / "on_call"

    Returns:
        ShiftType or None if unknown.
    """
    if raw is None:
        return None

    # If it's an Enum, prefer its .value
    if hasattr(raw, "value"):
        raw = getattr(raw, "value")

    s = str(raw).strip().lower()

    if s in ("onsite", "on_duty", "on-duty", "duty"):
        return ShiftType.onsite
    if s in ("oncall", "on_call", "on-call", "call"):
        return ShiftType.oncall
    return None


def _safe_int(raw: Any) -> Optional[int]:
    """
    Best-effort int conversion.
    Returns None when value is missing or cannot be converted.
    """
    if raw is None:
        return None
    try:
        return int(raw)
    except Exception:
        return None


def _weekday(problem: ProblemData, day: int) -> int:
    """
    Return weekday for a given day (0=Mon .. 6=Sun).
    Uses precomputed problem.weekdays when present, otherwise falls back to datetime().
    """
    wd = problem.weekdays.get(day)
    if wd is not None:
        return int(wd)
    return int(datetime(problem.year, problem.month, day).weekday())


def _extract_ignored_from_meta(meta: Dict[str, Any]) -> tuple[Set[int], Set[Tuple[int, ShiftType]]]:
    """
    Parse ignore_days / ignore_slots out of meta.exceptions.

    We store these in meta during generate():
    - {"code": "ignored_day", "day": 12, ...}
    - {"code": "ignored_slot", "day": 12, "shift_type": "onsite", ...}

    Returns:
        (ignored_days, ignored_slots)
    """
    ignored_days: Set[int] = set()
    ignored_slots: Set[Tuple[int, ShiftType]] = set()

    exceptions = meta.get("exceptions") or []
    if not isinstance(exceptions, list):
        return ignored_days, ignored_slots

    for e in exceptions:
        if not isinstance(e, dict):
            continue

        code = str(e.get("code") or "").strip().lower()

        if code == "ignored_day":
            day = _safe_int(e.get("day"))
            if day is not None:
                ignored_days.add(day)
            continue

        if code == "ignored_slot":
            day = _safe_int(e.get("day"))
            st = _normalize_shift_type(e.get("shift_type"))
            if day is not None and st is not None:
                ignored_slots.add((day, st))
            continue

    return ignored_days, ignored_slots


# ----------------------------- assignment index ---------------------------------


@dataclass(frozen=True)
class _Index:
    """
    Convenient precomputed structures for fast diagnostics.

    - slot_to_doctors[(day, shift_type)] -> list of doctor_ids (can be >1 if UI saved duplicates)
    - doctor_day_shifts[(doctor_id, day)] -> set of shifts worked that day
    """

    slot_to_doctors: Dict[Tuple[int, ShiftType], List[int]]
    doctor_day_shifts: Dict[Tuple[int, int], Set[ShiftType]]


def _build_index(assignments: Iterable[Any]) -> _Index:
    """
    Build index from assignment dicts.

    Each assignment expected shape:
      {"day": int, "shift_type": <enum or string>, "doctor_id": int}

    Defensive:
    - skip rows with invalid day/shift/doctor_id
    """
    slot_to_doctors: Dict[Tuple[int, ShiftType], List[int]] = {}
    doctor_day_shifts: Dict[Tuple[int, int], Set[ShiftType]] = {}

    for a in assignments or []:
        if not isinstance(a, dict):
            continue

        day = _safe_int(a.get("day"))
        doctor_id = _safe_int(a.get("doctor_id"))
        if day is None or doctor_id is None:
            continue

        st = _normalize_shift_type(a.get("shift_type"))
        if st is None:
            continue

        slot_key = (day, st)
        slot_to_doctors.setdefault(slot_key, []).append(doctor_id)

        dd_key = (doctor_id, day)
        doctor_day_shifts.setdefault(dd_key, set()).add(st)

    return _Index(slot_to_doctors=slot_to_doctors, doctor_day_shifts=doctor_day_shifts)


def _doctor_works_any(idx: _Index, *, doctor_id: int, day: int) -> bool:
    """True if doctor has onsite OR oncall on that day."""
    return bool(idx.doctor_day_shifts.get((doctor_id, day)))


def _doctor_has(idx: _Index, *, doctor_id: int, day: int, shift_type: ShiftType) -> bool:
    """True if doctor is assigned to this exact slot."""
    doctors = idx.slot_to_doctors.get((day, shift_type), [])
    return doctor_id in doctors


# ----------------------------- metrics: coverage --------------------------------


def compute_understaffed_days(
    *,
    problem: ProblemData,
    idx: _Index,
    ignored_days: Set[int],
    ignored_slots: Set[Tuple[int, ShiftType]],
) -> int:
    """
    Count days where required assignments are missing.

    MVP assumption:
    - each active day needs 1 onsite AND 1 oncall
    - ignore_days removes both requirements for that day
    - ignore_slots removes requirement for that (day, shift_type)
    """
    missing = 0

    for d_raw in problem.days:
        d = int(d_raw)
        if d in ignored_days:
            continue

        # onsite required?
        if (d, ShiftType.onsite) not in ignored_slots:
            if len(idx.slot_to_doctors.get((d, ShiftType.onsite), [])) < 1:
                missing += 1
                continue  # count day once even if both are missing

        # oncall required?
        if (d, ShiftType.oncall) not in ignored_slots:
            if len(idx.slot_to_doctors.get((d, ShiftType.oncall), [])) < 1:
                missing += 1
                continue

    return missing


# ----------------------------- metrics: preferences -----------------------------


def compute_preference_fulfillment_pct(
    *,
    problem: ProblemData,
    idx: _Index,
    ignored_days: Set[int],
    ignored_slots: Set[Tuple[int, ShiftType]],
) -> float:
    """
    Compute percent of satisfied "strong preferences":
    - preferred_onsite_days
    - preferred_oncall_days

    Notes:
    - If a preferred day is ignored/doesn't exist -> it's skipped (not counted).
    - If there are no preferences at all -> return 100.0.
    """
    total = 0
    ok = 0

    participants = set(problem.participant_doctor_ids)
    days_set = set(int(x) for x in problem.days)

    for doc_id in participants:
        prefs = problem.preferences.get(doc_id)
        if prefs is None:
            continue

        # Preferred onsite days
        for d_raw in prefs.preferred_onsite_days:
            d = int(d_raw)
            if d not in days_set:
                continue
            if d in ignored_days:
                continue
            if (d, ShiftType.onsite) in ignored_slots:
                continue

            total += 1
            if _doctor_has(idx, doctor_id=doc_id, day=d, shift_type=ShiftType.onsite):
                ok += 1

        # Preferred oncall days
        for d_raw in prefs.preferred_oncall_days:
            d = int(d_raw)
            if d not in days_set:
                continue
            if d in ignored_days:
                continue
            if (d, ShiftType.oncall) in ignored_slots:
                continue

            total += 1
            if _doctor_has(idx, doctor_id=doc_id, day=d, shift_type=ShiftType.oncall):
                ok += 1

    if total <= 0:
        return 100.0

    return float((ok * 100.0) / total)


# ----------------------------- penalty: rest rules ------------------------------


def _is_weekend_pair(problem: ProblemData, d: int, d_next: int) -> bool:
    """
    Weekend pair is only Sat -> Sun (same logic as objective_builder).
    """
    wd = _weekday(problem, d)
    wd_next = _weekday(problem, d_next)
    return wd == 5 and wd_next == 6


def compute_rest_penalty_and_violations(*, problem: ProblemData, idx: _Index) -> tuple[int, int]:
    """
    Compute rest penalty like the solver objective:
    - onsite->onsite consecutive
    - oncall->oncall consecutive
    - cross-shift consecutive (unless weekend exception flag is set)

    Returns:
        (penalty, violations_count)
    """
    penalty = 0
    violations = 0

    participants = sorted(problem.participant_doctor_ids)

    for doc_id in participants:
        doctor = problem.doctors.get(doc_id)
        prefs = problem.preferences.get(doc_id)

        # Defensive defaults
        role = doctor.role if doctor else DoctorRole.resident
        allow_weekend_consecutive = bool(prefs.allow_weekend_consecutive_onsite_oncall) if prefs else False

        cross_w = int(scoring.rest_cross_shift_weight(role=role))

        # Iterate consecutive day pairs
        days_sorted = [int(d) for d in problem.days]
        for i in range(len(days_sorted) - 1):
            d = days_sorted[i]
            d_next = days_sorted[i + 1]

            if d_next != d + 1:
                continue

            # onsite->onsite
            if _doctor_has(idx, doctor_id=doc_id, day=d, shift_type=ShiftType.onsite) and _doctor_has(
                idx, doctor_id=doc_id, day=d_next, shift_type=ShiftType.onsite
            ):
                penalty += int(scoring.REST_ONS_ONS_WEIGHT)
                violations += 1

            # oncall->oncall
            if _doctor_has(idx, doctor_id=doc_id, day=d, shift_type=ShiftType.oncall) and _doctor_has(
                idx, doctor_id=doc_id, day=d_next, shift_type=ShiftType.oncall
            ):
                penalty += int(scoring.REST_ONCALL_ONCALL_WEIGHT)
                violations += 1

            # cross shift
            skip_weekend_cross = bool(_is_weekend_pair(problem, d, d_next) and allow_weekend_consecutive)
            if not skip_weekend_cross:
                # onsite -> oncall
                if _doctor_has(idx, doctor_id=doc_id, day=d, shift_type=ShiftType.onsite) and _doctor_has(
                    idx, doctor_id=doc_id, day=d_next, shift_type=ShiftType.oncall
                ):
                    penalty += cross_w
                    violations += 1

                # oncall -> onsite
                if _doctor_has(idx, doctor_id=doc_id, day=d, shift_type=ShiftType.oncall) and _doctor_has(
                    idx, doctor_id=doc_id, day=d_next, shift_type=ShiftType.onsite
                ):
                    penalty += cross_w
                    violations += 1

    return penalty, violations


# ----------------------------- penalty: preferred days --------------------------


def compute_preferred_days_penalty(
    *,
    problem: ProblemData,
    idx: _Index,
    ignored_days: Set[int],
    ignored_slots: Set[Tuple[int, ShiftType]],
) -> int:
    """
    Penalty for missing preferred concrete days (same logic as objective_builder):
    - if slot cannot/should not exist (ignored) -> skip it
    - else miss is penalized with doctor-specific weight
    """
    penalty = 0
    days_set = set(int(x) for x in problem.days)

    for doc_id in problem.participant_doctor_ids:
        doctor = problem.doctors.get(doc_id)
        prefs = problem.preferences.get(doc_id)
        if prefs is None:
            continue

        is_head = bool(doctor.is_head) if doctor else False
        role = doctor.role if doctor else DoctorRole.resident
        miss_w = int(scoring.preferred_day_miss_weight_for_doctor(is_head=is_head, role=role))

        for d_raw in prefs.preferred_onsite_days:
            d = int(d_raw)
            if d not in days_set:
                continue
            if d in ignored_days:
                continue
            if (d, ShiftType.onsite) in ignored_slots:
                continue

            if not _doctor_has(idx, doctor_id=doc_id, day=d, shift_type=ShiftType.onsite):
                penalty += miss_w

        for d_raw in prefs.preferred_oncall_days:
            d = int(d_raw)
            if d not in days_set:
                continue
            if d in ignored_days:
                continue
            if (d, ShiftType.oncall) in ignored_slots:
                continue

            if not _doctor_has(idx, doctor_id=doc_id, day=d, shift_type=ShiftType.oncall):
                penalty += miss_w

    return penalty


# ----------------------------- penalty: totals ----------------------------------


def _weekend_days(problem: ProblemData) -> Set[int]:
    """Calendar weekend days: Sat(5) or Sun(6)."""
    out: Set[int] = set()
    for d_raw in problem.days:
        d = int(d_raw)
        wd = _weekday(problem, d)
        if wd in (5, 6):
            out.add(d)
    return out


def compute_totals_penalty(*, problem: ProblemData, idx: _Index) -> int:
    """
    Totals penalty (same spirit as objective_builder):
    - max_* -> excess^2
    - target_* -> (over^2 + under^2)
    Separate for monthly totals and weekend totals.
    """
    penalty = 0
    weekend = _weekend_days(problem)
    days_sorted = [int(d) for d in problem.days]

    for doc_id in problem.participant_doctor_ids:
        prefs = problem.preferences.get(doc_id)
        if prefs is None:
            continue

        # Count totals from assignments
        total_ons = 0
        total_onc = 0
        total_ons_w = 0
        total_onc_w = 0

        for d in days_sorted:
            if _doctor_has(idx, doctor_id=doc_id, day=d, shift_type=ShiftType.onsite):
                total_ons += 1
                if d in weekend:
                    total_ons_w += 1
            if _doctor_has(idx, doctor_id=doc_id, day=d, shift_type=ShiftType.oncall):
                total_onc += 1
                if d in weekend:
                    total_onc_w += 1

        # ---- monthly max ----
        if prefs.max_onsite_total is not None:
            excess = max(0, int(total_ons) - int(prefs.max_onsite_total))
            penalty += int(scoring.MAX_TOTAL_EXCESS_WEIGHT) * (excess * excess)

        if prefs.max_oncall_total is not None:
            excess = max(0, int(total_onc) - int(prefs.max_oncall_total))
            penalty += int(scoring.MAX_TOTAL_EXCESS_WEIGHT) * (excess * excess)

        # ---- monthly target (over + under) ----
        if prefs.target_onsite_total is not None:
            tgt = int(prefs.target_onsite_total)
            over = max(0, total_ons - tgt)
            under = max(0, tgt - total_ons)
            penalty += int(scoring.TARGET_TOTAL_DEVIATION_WEIGHT) * (over * over)
            penalty += int(scoring.TARGET_TOTAL_DEVIATION_WEIGHT) * (under * under)

        if prefs.target_oncall_total is not None:
            tgt = int(prefs.target_oncall_total)
            over = max(0, total_onc - tgt)
            under = max(0, tgt - total_onc)
            penalty += int(scoring.TARGET_TOTAL_DEVIATION_WEIGHT) * (over * over)
            penalty += int(scoring.TARGET_TOTAL_DEVIATION_WEIGHT) * (under * under)

        # ---- weekend max ----
        if prefs.max_onsite_weekends is not None:
            excess = max(0, total_ons_w - int(prefs.max_onsite_weekends))
            penalty += int(scoring.MAX_WEEKEND_EXCESS_WEIGHT) * (excess * excess)

        if prefs.max_oncall_weekends is not None:
            excess = max(0, total_onc_w - int(prefs.max_oncall_weekends))
            penalty += int(scoring.MAX_WEEKEND_EXCESS_WEIGHT) * (excess * excess)

        # ---- weekend target ----
        if prefs.target_onsite_weekends is not None:
            tgt = int(prefs.target_onsite_weekends)
            over = max(0, total_ons_w - tgt)
            under = max(0, tgt - total_ons_w)
            penalty += int(scoring.TARGET_WEEKEND_DEVIATION_WEIGHT) * (over * over)
            penalty += int(scoring.TARGET_WEEKEND_DEVIATION_WEIGHT) * (under * under)

        if prefs.target_oncall_weekends is not None:
            tgt = int(prefs.target_oncall_weekends)
            over = max(0, total_onc_w - tgt)
            under = max(0, tgt - total_onc_w)
            penalty += int(scoring.TARGET_WEEKEND_DEVIATION_WEIGHT) * (over * over)
            penalty += int(scoring.TARGET_WEEKEND_DEVIATION_WEIGHT) * (under * under)

    return penalty


# ----------------------------- penalty: fairness --------------------------------


def compute_fairness_penalty_and_index(*, problem: ProblemData, idx: _Index) -> tuple[int, float]:
    """
    Fairness like objective_builder:
    - groups: specialists (including heads) vs residents
    - categories: onsite weekday/weekend, oncall weekday/weekend
    - expected = target if present else group average (floor)
    - penalty = weight * (abs_dev^2)

    Also returns a simple fairness_index in [0..1] (1.0 means very even).
    """
    penalty = 0

    weekend = _weekend_days(problem)
    weekday_days: list[int] = [int(d) for d in problem.days if int(d) not in weekend]
    weekend_days: list[int] = sorted(int(d) for d in weekend)

    # Build groups
    specialist_ids: List[int] = []
    resident_ids: List[int] = []

    for doc_id in sorted(problem.participant_doctor_ids):
        doc = problem.doctors.get(doc_id)
        if not doc:
            continue
        if doc.role == DoctorRole.specialist:
            specialist_ids.append(int(doc_id))
        else:
            resident_ids.append(int(doc_id))

    def _count(doc_id: int, days: List[int], st: ShiftType) -> int:
        c = 0
        for d in days:
            if _doctor_has(idx, doctor_id=doc_id, day=int(d), shift_type=st):
                c += 1
        return c

    def _expected_for_category(doc_id: int, *, st: ShiftType, is_weekend_category: bool, group_avg_floor: int) -> int:
        prefs = problem.preferences.get(doc_id)

        expected: Optional[int] = None
        if prefs is not None:
            if st == ShiftType.onsite:
                if is_weekend_category:
                    if prefs.target_onsite_weekends is not None:
                        expected = int(prefs.target_onsite_weekends)
                else:
                    if prefs.target_onsite_total is not None:
                        expected = int(prefs.target_onsite_total)
                        if prefs.target_onsite_weekends is not None:
                            expected = expected - int(prefs.target_onsite_weekends)
            else:
                if is_weekend_category:
                    if prefs.target_oncall_weekends is not None:
                        expected = int(prefs.target_oncall_weekends)
                else:
                    if prefs.target_oncall_total is not None:
                        expected = int(prefs.target_oncall_total)
                        if prefs.target_oncall_weekends is not None:
                            expected = expected - int(prefs.target_oncall_weekends)

        if expected is None:
            expected = int(group_avg_floor)

        return max(0, expected)

    # --- Categories typing (Pylance-friendly) ---
    # (name, group_doctors, days, shift_type, is_weekend_category, weight)

    # --- Categories typing (Pylance-friendly) ---
    # (name, group_doctors, days, shift_type, is_weekend_category, weight)
    categories: List[tuple[str, List[int], List[int], ShiftType, bool, int]] = []

    # Build categories (only for groups with size >= 2)
    for group_ids in (specialist_ids, resident_ids):
        if len(group_ids) <= 1:
            continue

        categories.append(
            (
                "onsite_weekday",
                group_ids,
                weekday_days,
                ShiftType.onsite,
                False,
                int(scoring.fairness_weight(shift_type=ShiftType.onsite, is_weekend=False)),
            )
        )
        categories.append(
            (
                "onsite_weekend",
                group_ids,
                weekend_days,
                ShiftType.onsite,
                True,
                int(scoring.fairness_weight(shift_type=ShiftType.onsite, is_weekend=True)),
            )
        )
        categories.append(
            (
                "oncall_weekday",
                group_ids,
                weekday_days,
                ShiftType.oncall,
                False,
                int(scoring.fairness_weight(shift_type=ShiftType.oncall, is_weekend=False)),
            )
        )
        categories.append(
            (
                "oncall_weekend",
                group_ids,
                weekend_days,
                ShiftType.oncall,
                True,
                int(scoring.fairness_weight(shift_type=ShiftType.oncall, is_weekend=True)),
            )
        )

    # Now we unpack 6 fields (including the name)
    for _name, group_ids, days, st, is_weekend_cat, w in categories:
        ...

    # Fairness index: average of per-category "evenness" scores
    index_parts: List[float] = []

    # Now we unpack 6 fields (including the name)
    for _name, group_ids, days, st, is_weekend_cat, w in categories:
        if len(group_ids) <= 1:
            continue

        totals = [_count(doc_id, days, st) for doc_id in group_ids]
        n = len(totals)
        sum_tot = sum(totals)
        avg_floor = sum_tot // n  # floor, same as in model

        # penalty
        for doc_id, total in zip(group_ids, totals):
            exp = _expected_for_category(doc_id, st=st, is_weekend_category=is_weekend_cat, group_avg_floor=avg_floor)
            abs_dev = abs(int(total) - int(exp))
            penalty += int(w) * (abs_dev * abs_dev)

        # fairness_index part
        mean = (sum_tot / n) if n > 0 else 0.0
        if mean <= 0.0:
            index_parts.append(1.0)
        else:
            mean_abs_dev = sum(abs(t - mean) for t in totals) / n
            score = 1.0 - min(1.0, float(mean_abs_dev / mean))
            index_parts.append(max(0.0, score))

    fairness_index = float(sum(index_parts) / len(index_parts)) if index_parts else 1.0
    return penalty, fairness_index


# ----------------------------- penalty: weekday patterns -------------------------


def compute_weekday_patterns_penalty(*, problem: ProblemData, idx: _Index) -> int:
    """
    Weekday pattern terms:
    - preferred weekdays -> small BONUS (negative penalty)
    - avoid weekdays -> small PENALTY (positive penalty)
    """
    penalty = 0

    preferred_w = int(scoring.weekday_pattern_weight(kind="preferred"))
    avoid_w = int(scoring.weekday_pattern_weight(kind="avoid"))

    for doc_id in problem.participant_doctor_ids:
        prefs = problem.preferences.get(doc_id)
        if prefs is None:
            continue

        pref_ons = set(int(v) for v in prefs.preferred_onsite_weekdays)
        pref_onc = set(int(v) for v in prefs.preferred_oncall_weekdays)
        avoid_ons = set(int(v) for v in prefs.avoid_onsite_weekdays)
        avoid_onc = set(int(v) for v in prefs.avoid_oncall_weekdays)

        for d_raw in problem.days:
            d = int(d_raw)
            wd = _weekday(problem, d)

            # bonus: preferred weekday AND assigned
            if wd in pref_ons and _doctor_has(idx, doctor_id=doc_id, day=d, shift_type=ShiftType.onsite):
                penalty -= preferred_w
            if wd in pref_onc and _doctor_has(idx, doctor_id=doc_id, day=d, shift_type=ShiftType.oncall):
                penalty -= preferred_w

            # penalty: avoid weekday AND assigned
            if wd in avoid_ons and _doctor_has(idx, doctor_id=doc_id, day=d, shift_type=ShiftType.onsite):
                penalty += avoid_w
            if wd in avoid_onc and _doctor_has(idx, doctor_id=doc_id, day=d, shift_type=ShiftType.oncall):
                penalty += avoid_w

    return penalty


# ----------------------------- penalty: preferred partners -----------------------


def compute_preferred_partners_penalty(*, problem: ProblemData, idx: _Index) -> int:
    """
    Preferred partners bonus:
    - for each unique pair (doc_id < partner_id)
    - for each day: if both work any shift -> bonus (negative penalty)
    """
    bonus_w = int(scoring.preferred_partner_bonus_weight())
    participants = set(problem.participant_doctor_ids)

    pairs: List[Tuple[int, int]] = []
    for doc_id in sorted(problem.participant_doctor_ids):
        prefs = problem.preferences.get(doc_id)
        if prefs is None:
            continue
        for partner_raw in list(prefs.preferred_partners or []):
            partner_id = _safe_int(partner_raw)
            if partner_id is None:
                continue
            if partner_id not in participants:
                continue
            if doc_id >= partner_id:
                continue
            pairs.append((doc_id, partner_id))

    if not pairs:
        return 0

    penalty = 0
    for a, b in pairs:
        for d_raw in problem.days:
            d = int(d_raw)
            if _doctor_works_any(idx, doctor_id=a, day=d) and _doctor_works_any(idx, doctor_id=b, day=d):
                penalty -= bonus_w

    return penalty


# ----------------------------- penalty: Friday + free weekend --------------------


def compute_friday_free_weekend_penalty(*, problem: ProblemData, idx: _Index) -> int:
    """
    Avoid Friday if the following weekend is fully off:
    - Friday (weekday==4)
    - Saturday and Sunday must exist in this month: (fri+1, fri+2) and be Sat/Sun
    - penalty if doctor works on Friday AND does NOT work on Sat AND does NOT work on Sun
    """
    weight = int(scoring.friday_with_free_weekend_weight())
    days_set = set(int(d) for d in problem.days)

    fridays: List[int] = []
    for d in sorted(days_set):
        if _weekday(problem, d) != 4:
            continue

        sat = d + 1
        sun = d + 2
        if sat not in days_set or sun not in days_set:
            continue

        if _weekday(problem, sat) == 5 and _weekday(problem, sun) == 6:
            fridays.append(d)

    if not fridays:
        return 0

    penalty = 0
    for doc_id in problem.participant_doctor_ids:
        for fri in fridays:
            sat = fri + 1
            sun = fri + 2

            works_fri = _doctor_works_any(idx, doctor_id=doc_id, day=fri)
            works_weekend = _doctor_works_any(idx, doctor_id=doc_id, day=sat) or _doctor_works_any(
                idx, doctor_id=doc_id, day=sun
            )

            if works_fri and not works_weekend:
                penalty += weight

    return penalty


# ----------------------------- public API ---------------------------------------


def compute_quality(*, problem: ProblemData, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compute full diagnostics payload for a schedule snapshot.

    Returns a JSON-serializable dict:
    {
      "summary": {...},
      "details": {...} | None
    }
    """
    meta_any = payload.get("meta") or {"labels": []}
    meta: Dict[str, Any] = dict(meta_any) if isinstance(meta_any, dict) else {"labels": []}

    assignments_any = payload.get("assignments") or []
    assignments: List[Any] = list(assignments_any) if isinstance(assignments_any, list) else []

    ignored_days, ignored_slots = _extract_ignored_from_meta(meta)
    idx = _build_index(assignments)

    understaffed_days = compute_understaffed_days(
        problem=problem, idx=idx, ignored_days=ignored_days, ignored_slots=ignored_slots
    )

    pref_pct = compute_preference_fulfillment_pct(
        problem=problem, idx=idx, ignored_days=ignored_days, ignored_slots=ignored_slots
    )

    rest_pen, rest_viol = compute_rest_penalty_and_violations(problem=problem, idx=idx)
    pref_days_pen = compute_preferred_days_penalty(
        problem=problem, idx=idx, ignored_days=ignored_days, ignored_slots=ignored_slots
    )
    totals_pen = compute_totals_penalty(problem=problem, idx=idx)
    fairness_pen, fairness_index = compute_fairness_penalty_and_index(problem=problem, idx=idx)
    weekday_pen = compute_weekday_patterns_penalty(problem=problem, idx=idx)
    partners_pen = compute_preferred_partners_penalty(problem=problem, idx=idx)
    fri_pen = compute_friday_free_weekend_penalty(problem=problem, idx=idx)

    penalty_total = int(rest_pen + pref_days_pen + totals_pen + fairness_pen + weekday_pen + partners_pen + fri_pen)

    summary: Dict[str, Any] = {
        "penalty_total": int(penalty_total),
        "understaffed_days": int(understaffed_days),
        "rest_violations": int(rest_viol),
        "fairness_index": float(max(0.0, min(1.0, fairness_index))),
        "preference_fulfillment_pct": float(max(0.0, min(100.0, pref_pct))),
    }

    details: Dict[str, Any] = {
        "components": {
            "rest_penalty": int(rest_pen),
            "preferred_days_penalty": int(pref_days_pen),
            "totals_penalty": int(totals_pen),
            "fairness_penalty": int(fairness_pen),
            "weekday_patterns_penalty": int(weekday_pen),
            "preferred_partners_penalty": int(partners_pen),
            "friday_free_weekend_penalty": int(fri_pen),
        }
    }

    return {"summary": summary, "details": details}
