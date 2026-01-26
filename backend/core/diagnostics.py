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
  "details": {...}
}

Important contract notes (final contract alignment):
- summary includes stable KPI fields expected by the API contract
  (coverage_missing_required_slots, hard_issues_count, rest_violations, fairness_index,
  preference_fulfillment_pct).
- details includes findings[], per_doctor[] and rankings{}.
- core returns only plain Python structures (dict/list/str/int/float/bool).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from backend.core import issues, scoring
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
    - {"code": "ignored_day" | "coverage_ignored_day", "day": 12, ...}
    - {"code": "ignored_slot" | "coverage_ignored_slot", "day": 12, "shift_type": "onsite", ...}

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
        ignored_day_codes = {
            "ignored_day",
            str(getattr(issues, "COVERAGE_IGNORED_DAY", "coverage_ignored_day")).strip().lower(),
        }
        ignored_slot_codes = {
            "ignored_slot",
            str(getattr(issues, "COVERAGE_IGNORED_SLOT", "coverage_ignored_slot")).strip().lower(),
        }

        if code in ignored_day_codes:
            day = _safe_int(e.get("day"))
            if day is not None:
                ignored_days.add(day)
            continue

        if code in ignored_slot_codes:
            day = _safe_int(e.get("day"))
            st = _normalize_shift_type(e.get("shift_type"))
            if day is not None and st is not None:
                ignored_slots.add((day, st))
            continue

    return ignored_days, ignored_slots


def _display_name_from_snapshot(payload: Dict[str, Any], doctor_id: int) -> str:
    """
    Read display_name from payload.inputs_snapshot.doctors (frozen snapshot).
    Fallback is deterministic and safe for UI/debugging.
    """
    snap_any = payload.get("inputs_snapshot") or {}
    if not isinstance(snap_any, dict):
        return f"Doctor {int(doctor_id)}"

    doctors_any = snap_any.get("doctors") or {}
    if not isinstance(doctors_any, dict):
        return f"Doctor {int(doctor_id)}"

    # JSON keys can be "123" or 123, so we try both.
    snap = doctors_any.get(doctor_id)
    if snap is None:
        snap = doctors_any.get(str(int(doctor_id)))

    if isinstance(snap, dict):
        name = snap.get("display_name")
        if isinstance(name, str) and name.strip():
            return name.strip()

    return f"Doctor {int(doctor_id)}"


# ----------------------------- assignment index ---------------------------------


@dataclass(frozen=True)
class _Index:
    """
    Convenient precomputed structures for fast diagnostics.

    - slot_to_doctors[(day, shift_type)] -> list of doctor_ids
      (can be >1 if UI saved duplicates or multiple assignments are allowed later)
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


# ----------------------------- findings helpers ---------------------------------


def _finding(*, code: str, severity: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Create a finding dict in the stable, FE-friendly shape.

    NOTE: This stays pure dict to avoid importing DTOs into core.
    """
    return {
        "code": str(code),
        "severity": str(severity),
        "context": dict(context or {}),
    }


# ----------------------------- coverage (final semantics) ------------------------


def compute_coverage_missing_required_slots(
    *,
    problem: ProblemData,
    idx: _Index,
    ignored_days: Set[int],
    ignored_slots: Set[Tuple[int, ShiftType]],
) -> tuple[int, List[Tuple[int, ShiftType]]]:
    """
    Count missing required coverage slots (per slot, not per day).

    Rules:
    - Each day requires 1 onsite and 1 oncall slot (MVP).
    - IMPORTANT: ignore rules DO NOT reduce requirements in diagnostics.
    Ignore exceptions were used only to allow generation, but diagnostics must show real gaps.
    - We still return ignored_days/ignored_slots separately so UI can display that the gap was previously "accepted".

    Returns:
        (missing_count, missing_slots_list)
    """
    missing_slots: List[Tuple[int, ShiftType]] = []

    for d_raw in problem.days:
        d = int(d_raw)

        # NOTE:
        # We DO NOT skip ignored_days/ignored_slots here.
        # Diagnostics must show gaps even if they were "accepted" during generation.

        if len(idx.slot_to_doctors.get((d, ShiftType.onsite), [])) < 1:
            missing_slots.append((d, ShiftType.onsite))

        if len(idx.slot_to_doctors.get((d, ShiftType.oncall), [])) < 1:
            missing_slots.append((d, ShiftType.oncall))

    return int(len(missing_slots)), missing_slots


def compute_understaffed_days(
    *,
    problem: ProblemData,
    idx: _Index,
    ignored_days: Set[int],
    ignored_slots: Set[Tuple[int, ShiftType]],
) -> int:
    """
    DEPRECATED (kept for backward compatibility):
    Count days where required assignments are missing.

    NOTE:
    - New contract uses compute_coverage_missing_required_slots (per-slot gaps).
    - This value should not be used as a KPI by FE anymore.
    """
    missing = 0

    for d_raw in problem.days:
        d = int(d_raw)

        # NOTE:
        # Diagnostics must show understaffed days even if they were "accepted" during generation.
        # This field is deprecated, but keep semantics consistent with coverage gaps.

        if len(idx.slot_to_doctors.get((d, ShiftType.onsite), [])) < 1:
            missing += 1
            continue

        if len(idx.slot_to_doctors.get((d, ShiftType.oncall), [])) < 1:
            missing += 1
            continue

    return missing


# ----------------------------- preferences fulfillment ---------------------------


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


def _compute_preference_stats_per_doctor(
    *,
    problem: ProblemData,
    idx: _Index,
    ignored_days: Set[int],
    ignored_slots: Set[Tuple[int, ShiftType]],
) -> tuple[Dict[int, float], Dict[int, int]]:
    """
    Compute per-doctor preference fulfillment percent and preferred_days_missed.

    Returns:
        (pct_by_doctor, missed_by_doctor)
    """
    days_set = set(int(x) for x in problem.days)

    pct_by_doctor: Dict[int, float] = {}
    missed_by_doctor: Dict[int, int] = {}

    for doc_id in sorted(problem.participant_doctor_ids):
        prefs = problem.preferences.get(doc_id)
        if prefs is None:
            pct_by_doctor[int(doc_id)] = 100.0
            missed_by_doctor[int(doc_id)] = 0
            continue

        total = 0
        ok = 0
        missed = 0

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
            else:
                missed += 1

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
            else:
                missed += 1

        if total <= 0:
            pct = 100.0
        else:
            pct = float((ok * 100.0) / total)

        pct_by_doctor[int(doc_id)] = float(max(0.0, min(100.0, pct)))
        missed_by_doctor[int(doc_id)] = int(missed)

    return pct_by_doctor, missed_by_doctor


# ----------------------------- rest rules (per-doctor stats) ---------------------


def _is_weekend_pair(problem: ProblemData, d: int, d_next: int) -> bool:
    """Weekend pair is only Sat -> Sun (same logic as objective_builder)."""
    wd = _weekday(problem, d)
    wd_next = _weekday(problem, d_next)
    return wd == 5 and wd_next == 6


def compute_rest_penalty_and_violations(*, problem: ProblemData, idx: _Index) -> tuple[int, int]:
    """
    Backward-compatible wrapper.

    Returns:
        (total_penalty, total_violations_count)
    """
    total_penalty, total_violations, _viol_by_doc, _pen_by_doc, _rest_findings = _compute_rest_stats(
        problem=problem, idx=idx
    )

    return int(total_penalty), int(total_violations)


def _compute_rest_stats(
    *, problem: ProblemData, idx: _Index
) -> tuple[int, int, Dict[int, int], Dict[int, int], List[Dict[str, Any]]]:
    """
    Compute rest penalty and violations both globally and per-doctor.

    Returns:
        (total_penalty, total_violations, violations_by_doctor, penalty_by_doctor)
    """
    total_penalty = 0
    total_violations = 0

    violations_by_doctor: Dict[int, int] = {int(d): 0 for d in problem.participant_doctor_ids}
    penalty_by_doctor: Dict[int, int] = {int(d): 0 for d in problem.participant_doctor_ids}
    rest_findings: List[Dict[str, Any]] = []

    days_sorted = [int(d) for d in problem.days]

    for doc_id in sorted(problem.participant_doctor_ids):
        doctor = problem.doctors.get(doc_id)
        prefs = problem.preferences.get(doc_id)

        role = doctor.role if doctor else DoctorRole.resident
        allow_weekend_consecutive = bool(prefs.allow_weekend_consecutive_onsite_oncall) if prefs else False

        cross_w = int(scoring.rest_cross_shift_weight(role=role))

        for i in range(len(days_sorted) - 1):
            d = days_sorted[i]
            d_next = days_sorted[i + 1]
            if d_next != d + 1:
                continue

            # onsite->onsite
            if _doctor_has(idx, doctor_id=doc_id, day=d, shift_type=ShiftType.onsite) and _doctor_has(
                idx, doctor_id=doc_id, day=d_next, shift_type=ShiftType.onsite
            ):
                w = int(scoring.REST_ONS_ONS_WEIGHT)
                total_penalty += w
                total_violations += 1
                violations_by_doctor[int(doc_id)] += 1
                penalty_by_doctor[int(doc_id)] += w
                rest_findings.append(
                    _finding(
                        code=issues.REST_CONSECUTIVE_VIOLATION,
                        severity="warning",
                        context={"doctor_id": int(doc_id), "day": int(d), "kind": "onsite_onsite"},
                    )
                )

            # oncall->oncall
            if _doctor_has(idx, doctor_id=doc_id, day=d, shift_type=ShiftType.oncall) and _doctor_has(
                idx, doctor_id=doc_id, day=d_next, shift_type=ShiftType.oncall
            ):
                w = int(scoring.REST_ONCALL_ONCALL_WEIGHT)
                total_penalty += w
                total_violations += 1
                violations_by_doctor[int(doc_id)] += 1
                penalty_by_doctor[int(doc_id)] += w
                rest_findings.append(
                    _finding(
                        code=issues.REST_CONSECUTIVE_VIOLATION,
                        severity="warning",
                        context={"doctor_id": int(doc_id), "day": int(d), "kind": "oncall_oncall"},
                    )
                )

            # cross shift (unless weekend exception)
            skip_weekend_cross = bool(_is_weekend_pair(problem, d, d_next) and allow_weekend_consecutive)
            if not skip_weekend_cross:
                # onsite -> oncall
                if _doctor_has(idx, doctor_id=doc_id, day=d, shift_type=ShiftType.onsite) and _doctor_has(
                    idx, doctor_id=doc_id, day=d_next, shift_type=ShiftType.oncall
                ):
                    total_penalty += cross_w
                    total_violations += 1
                    violations_by_doctor[int(doc_id)] += 1
                    penalty_by_doctor[int(doc_id)] += cross_w
                    rest_findings.append(
                        _finding(
                            code=issues.REST_CONSECUTIVE_VIOLATION,
                            severity="warning",
                            context={"doctor_id": int(doc_id), "day": int(d), "kind": "cross"},
                        )
                    )

                # oncall -> onsite
                if _doctor_has(idx, doctor_id=doc_id, day=d, shift_type=ShiftType.oncall) and _doctor_has(
                    idx, doctor_id=doc_id, day=d_next, shift_type=ShiftType.onsite
                ):
                    total_penalty += cross_w
                    total_violations += 1
                    violations_by_doctor[int(doc_id)] += 1
                    penalty_by_doctor[int(doc_id)] += cross_w
                    rest_findings.append(
                        _finding(
                            code=issues.REST_CONSECUTIVE_VIOLATION,
                            severity="warning",
                            context={"doctor_id": int(doc_id), "day": int(d), "kind": "cross"},
                        )
                    )

    return int(total_penalty), int(total_violations), violations_by_doctor, penalty_by_doctor, rest_findings


# ----------------------------- totals (per-doctor penalty) -----------------------


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
    Backward-compatible wrapper (total penalty).
    """
    total_penalty, _pen_by_doc = _compute_totals_penalty_per_doctor(problem=problem, idx=idx)
    return int(total_penalty)


def _compute_totals_penalty_per_doctor(*, problem: ProblemData, idx: _Index) -> tuple[int, Dict[int, int]]:
    """
    Totals penalty (same spirit as objective_builder), per doctor:
    - max_* -> excess^2
    - target_* -> (over^2 + under^2)
    Separate for monthly totals and weekend totals.
    """
    total_penalty = 0
    penalty_by_doctor: Dict[int, int] = {int(d): 0 for d in problem.participant_doctor_ids}

    weekend = _weekend_days(problem)
    days_sorted = [int(d) for d in problem.days]

    for doc_id in sorted(problem.participant_doctor_ids):
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

        p = 0

        # monthly max
        if prefs.max_onsite_total is not None:
            excess = max(0, int(total_ons) - int(prefs.max_onsite_total))
            p += int(scoring.MAX_TOTAL_EXCESS_WEIGHT) * (excess * excess)

        if prefs.max_oncall_total is not None:
            excess = max(0, int(total_onc) - int(prefs.max_oncall_total))
            p += int(scoring.MAX_TOTAL_EXCESS_WEIGHT) * (excess * excess)

        # monthly target (over + under)
        if prefs.target_onsite_total is not None:
            tgt = int(prefs.target_onsite_total)
            over = max(0, total_ons - tgt)
            under = max(0, tgt - total_ons)
            p += int(scoring.TARGET_TOTAL_DEVIATION_WEIGHT) * (over * over)
            p += int(scoring.TARGET_TOTAL_DEVIATION_WEIGHT) * (under * under)

        if prefs.target_oncall_total is not None:
            tgt = int(prefs.target_oncall_total)
            over = max(0, total_onc - tgt)
            under = max(0, tgt - total_onc)
            p += int(scoring.TARGET_TOTAL_DEVIATION_WEIGHT) * (over * over)
            p += int(scoring.TARGET_TOTAL_DEVIATION_WEIGHT) * (under * under)

        # weekend max
        if prefs.max_onsite_weekends is not None:
            excess = max(0, total_ons_w - int(prefs.max_onsite_weekends))
            p += int(scoring.MAX_WEEKEND_EXCESS_WEIGHT) * (excess * excess)

        if prefs.max_oncall_weekends is not None:
            excess = max(0, total_onc_w - int(prefs.max_oncall_weekends))
            p += int(scoring.MAX_WEEKEND_EXCESS_WEIGHT) * (excess * excess)

        # weekend target
        if prefs.target_onsite_weekends is not None:
            tgt = int(prefs.target_onsite_weekends)
            over = max(0, total_ons_w - tgt)
            under = max(0, tgt - total_ons_w)
            p += int(scoring.TARGET_WEEKEND_DEVIATION_WEIGHT) * (over * over)
            p += int(scoring.TARGET_WEEKEND_DEVIATION_WEIGHT) * (under * under)

        if prefs.target_oncall_weekends is not None:
            tgt = int(prefs.target_oncall_weekends)
            over = max(0, total_onc_w - tgt)
            under = max(0, tgt - total_onc_w)
            p += int(scoring.TARGET_WEEKEND_DEVIATION_WEIGHT) * (over * over)
            p += int(scoring.TARGET_WEEKEND_DEVIATION_WEIGHT) * (under * under)

        penalty_by_doctor[int(doc_id)] = int(p)
        total_penalty += int(p)

    return int(total_penalty), penalty_by_doctor


# ----------------------------- fairness (per-doctor penalty + index) -------------


def compute_fairness_penalty_and_index(*, problem: ProblemData, idx: _Index) -> tuple[int, float]:
    """
    Backward-compatible wrapper (total penalty + index).
    """
    total_penalty, fairness_index, _pen_by_doc = _compute_fairness_stats(problem=problem, idx=idx)
    return int(total_penalty), float(fairness_index)


def _compute_fairness_stats(*, problem: ProblemData, idx: _Index) -> tuple[int, float, Dict[int, int]]:
    """
    Fairness like objective_builder:
    - groups: specialists (including heads) vs residents
    - categories: onsite weekday/weekend, oncall weekday/weekend
    - expected = target if present else group average (floor)
    - penalty = weight * (abs_dev^2)

    Returns:
        (total_penalty, fairness_index, penalty_by_doctor)
    """
    total_penalty = 0
    penalty_by_doctor: Dict[int, int] = {int(d): 0 for d in problem.participant_doctor_ids}

    weekend = _weekend_days(problem)
    weekday_days: List[int] = [int(d) for d in problem.days if int(d) not in weekend]
    weekend_days: List[int] = sorted(int(d) for d in weekend)

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

    categories: List[tuple[List[int], List[int], ShiftType, bool, int]] = []

    for group_ids in (specialist_ids, resident_ids):
        if len(group_ids) <= 1:
            continue

        categories.append(
            (
                group_ids,
                weekday_days,
                ShiftType.onsite,
                False,
                int(scoring.fairness_weight(shift_type=ShiftType.onsite, is_weekend=False)),
            )
        )
        categories.append(
            (
                group_ids,
                weekend_days,
                ShiftType.onsite,
                True,
                int(scoring.fairness_weight(shift_type=ShiftType.onsite, is_weekend=True)),
            )
        )
        categories.append(
            (
                group_ids,
                weekday_days,
                ShiftType.oncall,
                False,
                int(scoring.fairness_weight(shift_type=ShiftType.oncall, is_weekend=False)),
            )
        )
        categories.append(
            (
                group_ids,
                weekend_days,
                ShiftType.oncall,
                True,
                int(scoring.fairness_weight(shift_type=ShiftType.oncall, is_weekend=True)),
            )
        )

    index_parts: List[float] = []

    for group_ids, days, st, is_weekend_cat, w in categories:
        totals = [_count(doc_id, days, st) for doc_id in group_ids]
        n = len(totals)
        sum_tot = sum(totals)
        avg_floor = sum_tot // n

        for doc_id, total in zip(group_ids, totals):
            exp = _expected_for_category(doc_id, st=st, is_weekend_category=is_weekend_cat, group_avg_floor=avg_floor)
            abs_dev = abs(int(total) - int(exp))
            p = int(w) * (abs_dev * abs_dev)

            total_penalty += int(p)
            penalty_by_doctor[int(doc_id)] += int(p)

        mean = (sum_tot / n) if n > 0 else 0.0
        if mean <= 0.0:
            index_parts.append(1.0)
        else:
            mean_abs_dev = sum(abs(t - mean) for t in totals) / n
            score = 1.0 - min(1.0, float(mean_abs_dev / mean))
            index_parts.append(max(0.0, score))

    fairness_index = float(sum(index_parts) / len(index_parts)) if index_parts else 1.0
    fairness_index = float(max(0.0, min(1.0, fairness_index)))

    return int(total_penalty), float(fairness_index), penalty_by_doctor


# ----------------------------- weekday patterns (per-doctor penalty) -------------


def compute_weekday_patterns_penalty(*, problem: ProblemData, idx: _Index) -> int:
    """
    Backward-compatible wrapper (total penalty).
    """
    total_penalty, _pen_by_doc = _compute_weekday_patterns_penalty_per_doctor(problem=problem, idx=idx)
    return int(total_penalty)


def _compute_weekday_patterns_penalty_per_doctor(*, problem: ProblemData, idx: _Index) -> tuple[int, Dict[int, int]]:
    """
    Weekday pattern terms:
    - preferred weekdays -> small BONUS (negative penalty)
    - avoid weekdays -> small PENALTY (positive penalty)

    Returns:
        (total_penalty, penalty_by_doctor)
    """
    total_penalty = 0
    penalty_by_doctor: Dict[int, int] = {int(d): 0 for d in problem.participant_doctor_ids}

    preferred_w = int(scoring.weekday_pattern_weight(kind="preferred"))
    avoid_w = int(scoring.weekday_pattern_weight(kind="avoid"))

    for doc_id in sorted(problem.participant_doctor_ids):
        prefs = problem.preferences.get(doc_id)
        if prefs is None:
            continue

        pref_ons = set(int(v) for v in prefs.preferred_onsite_weekdays)
        pref_onc = set(int(v) for v in prefs.preferred_oncall_weekdays)
        avoid_ons = set(int(v) for v in prefs.avoid_onsite_weekdays)
        avoid_onc = set(int(v) for v in prefs.avoid_oncall_weekdays)

        p = 0
        for d_raw in problem.days:
            d = int(d_raw)
            wd = _weekday(problem, d)

            if wd in pref_ons and _doctor_has(idx, doctor_id=doc_id, day=d, shift_type=ShiftType.onsite):
                p -= preferred_w
            if wd in pref_onc and _doctor_has(idx, doctor_id=doc_id, day=d, shift_type=ShiftType.oncall):
                p -= preferred_w

            if wd in avoid_ons and _doctor_has(idx, doctor_id=doc_id, day=d, shift_type=ShiftType.onsite):
                p += avoid_w
            if wd in avoid_onc and _doctor_has(idx, doctor_id=doc_id, day=d, shift_type=ShiftType.oncall):
                p += avoid_w

        penalty_by_doctor[int(doc_id)] = int(p)
        total_penalty += int(p)

    return int(total_penalty), penalty_by_doctor


# ----------------------------- preferred partners (per-doctor bonus) -------------


def compute_preferred_partners_penalty(*, problem: ProblemData, idx: _Index) -> int:
    """
    Backward-compatible wrapper (total penalty).
    """
    total_penalty, _bonus_by_doctor = _compute_preferred_partners_bonus_by_doctor(problem=problem, idx=idx)
    return int(total_penalty)


def _compute_preferred_partners_bonus_by_doctor(*, problem: ProblemData, idx: _Index) -> tuple[int, Dict[int, float]]:
    """
    Preferred partners bonus:
    - for each unique pair (doc_id < partner_id)
    - for each day: if both work any shift -> bonus (negative penalty)

    Per-doctor allocation for rankings:
    - The solver objective counts bonus per pair-day once.
    - For per-doctor "score", we split the bonus equally: half to each doctor.

    Returns:
        (total_penalty, bonus_by_doctor)  where bonus values are floats (negative numbers).
    """
    bonus_w = float(scoring.preferred_partner_bonus_weight())
    participants = set(problem.participant_doctor_ids)

    bonus_by_doctor: Dict[int, float] = {int(d): 0.0 for d in problem.participant_doctor_ids}

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
            pairs.append((int(doc_id), int(partner_id)))

    if not pairs:
        return 0, bonus_by_doctor

    total_penalty = 0.0
    for a, b in pairs:
        for d_raw in problem.days:
            d = int(d_raw)
            if _doctor_works_any(idx, doctor_id=a, day=d) and _doctor_works_any(idx, doctor_id=b, day=d):
                total_penalty -= bonus_w
                bonus_by_doctor[int(a)] -= bonus_w / 2.0
                bonus_by_doctor[int(b)] -= bonus_w / 2.0

    return int(total_penalty), bonus_by_doctor


# ----------------------------- Friday + free weekend (per-doctor penalty) --------


def compute_friday_free_weekend_penalty(*, problem: ProblemData, idx: _Index) -> int:
    """
    Backward-compatible wrapper (total penalty).
    """
    total_penalty, _pen_by_doc = _compute_friday_free_weekend_penalty_per_doctor(problem=problem, idx=idx)
    return int(total_penalty)


def _compute_friday_free_weekend_penalty_per_doctor(*, problem: ProblemData, idx: _Index) -> tuple[int, Dict[int, int]]:
    """
    Avoid Friday if the following weekend is fully off:
    - Friday (weekday==4)
    - Saturday and Sunday must exist in this month: (fri+1, fri+2) and be Sat/Sun
    - penalty if doctor works on Friday AND does NOT work on Sat AND does NOT work on Sun

    Returns:
        (total_penalty, penalty_by_doctor)
    """
    weight = int(scoring.friday_with_free_weekend_weight())
    days_set = set(int(d) for d in problem.days)

    penalty_by_doctor: Dict[int, int] = {int(d): 0 for d in problem.participant_doctor_ids}

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
        return 0, penalty_by_doctor

    total_penalty = 0
    for doc_id in sorted(problem.participant_doctor_ids):
        p = 0
        for fri in fridays:
            sat = fri + 1
            sun = fri + 2

            works_fri = _doctor_works_any(idx, doctor_id=doc_id, day=fri)
            works_weekend = _doctor_works_any(idx, doctor_id=doc_id, day=sat) or _doctor_works_any(
                idx, doctor_id=doc_id, day=sun
            )

            if works_fri and not works_weekend:
                p += int(weight)

        penalty_by_doctor[int(doc_id)] = int(p)
        total_penalty += int(p)

    return int(total_penalty), penalty_by_doctor


# ----------------------------- preferred concrete days (per-doctor) --------------


def compute_preferred_days_penalty(
    *,
    problem: ProblemData,
    idx: _Index,
    ignored_days: Set[int],
    ignored_slots: Set[Tuple[int, ShiftType]],
) -> int:
    """
    Backward-compatible wrapper (total penalty).
    """
    total_penalty, _pen_by_doc = _compute_preferred_days_penalty_per_doctor(
        problem=problem, idx=idx, ignored_days=ignored_days, ignored_slots=ignored_slots
    )
    return int(total_penalty)


def _compute_preferred_days_penalty_per_doctor(
    *,
    problem: ProblemData,
    idx: _Index,
    ignored_days: Set[int],
    ignored_slots: Set[Tuple[int, ShiftType]],
) -> tuple[int, Dict[int, int]]:
    """
    Penalty for missing preferred concrete days (same logic as objective_builder):
    - if slot cannot/should not exist (ignored) -> skip it
    - else miss is penalized with doctor-specific weight

    Returns:
        (total_penalty, penalty_by_doctor)
    """
    total_penalty = 0
    penalty_by_doctor: Dict[int, int] = {int(d): 0 for d in problem.participant_doctor_ids}

    days_set = set(int(x) for x in problem.days)

    for doc_id in sorted(problem.participant_doctor_ids):
        doctor = problem.doctors.get(doc_id)
        prefs = problem.preferences.get(doc_id)
        if prefs is None:
            continue

        is_head = bool(doctor.is_head) if doctor else False
        role = doctor.role if doctor else DoctorRole.resident
        miss_w = int(scoring.preferred_day_miss_weight_for_doctor(is_head=is_head, role=role))

        p = 0

        for d_raw in prefs.preferred_onsite_days:
            d = int(d_raw)
            if d not in days_set:
                continue
            if d in ignored_days:
                continue
            if (d, ShiftType.onsite) in ignored_slots:
                continue

            if not _doctor_has(idx, doctor_id=doc_id, day=d, shift_type=ShiftType.onsite):
                p += miss_w

        for d_raw in prefs.preferred_oncall_days:
            d = int(d_raw)
            if d not in days_set:
                continue
            if d in ignored_days:
                continue
            if (d, ShiftType.oncall) in ignored_slots:
                continue

            if not _doctor_has(idx, doctor_id=doc_id, day=d, shift_type=ShiftType.oncall):
                p += miss_w

        penalty_by_doctor[int(doc_id)] = int(p)
        total_penalty += int(p)

    return int(total_penalty), penalty_by_doctor


# ----------------------------- per-doctor assignments totals ---------------------


def _assigned_totals_per_doctor(*, problem: ProblemData, idx: _Index) -> tuple[Dict[int, int], Dict[int, int]]:
    """
    Count assigned totals for each doctor (onsite and oncall).
    """
    onsite_by_doctor: Dict[int, int] = {int(d): 0 for d in problem.participant_doctor_ids}
    oncall_by_doctor: Dict[int, int] = {int(d): 0 for d in problem.participant_doctor_ids}

    for doc_id in sorted(problem.participant_doctor_ids):
        ons = 0
        onc = 0
        for d_raw in problem.days:
            d = int(d_raw)
            if _doctor_has(idx, doctor_id=doc_id, day=d, shift_type=ShiftType.onsite):
                ons += 1
            if _doctor_has(idx, doctor_id=doc_id, day=d, shift_type=ShiftType.oncall):
                onc += 1
        onsite_by_doctor[int(doc_id)] = int(ons)
        oncall_by_doctor[int(doc_id)] = int(onc)

    return onsite_by_doctor, oncall_by_doctor


# ----------------------------- hard issues / findings ----------------------------


def _build_findings(
    *,
    problem: ProblemData,
    payload: Dict[str, Any],
    idx: _Index,
    ignored_days: Set[int],
    ignored_slots: Set[Tuple[int, ShiftType]],
    missing_slots: List[Tuple[int, ShiftType]],
    rest_findings: List[Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], Dict[int, int]]:
    """
    Build findings list and return additional per-doctor counters used by rankings.

    Returns:
        (findings, double_shift_days_by_doctor)
    """
    findings: List[Dict[str, Any]] = []

    # Info: ignored day/slot context (NOT a KPI, but helpful for UI debugging).
    for d in sorted(ignored_days):
        findings.append(_finding(code=issues.COVERAGE_IGNORED_DAY, severity="info", context={"day": int(d)}))

    for d, st in sorted(ignored_slots, key=lambda x: (int(x[0]), str(x[1].value))):
        findings.append(
            _finding(
                code=issues.COVERAGE_IGNORED_SLOT, severity="info", context={"day": int(d), "shift_type": st.value}
            )
        )

    # Critical: missing coverage slots (Gaps)
    # Even if a gap was previously "accepted" (ignored during generation),
    # diagnostics must still show it as a real gap.
    for d, st in missing_slots:
        was_ignored = bool((int(d) in ignored_days) or ((int(d), st) in ignored_slots))
        findings.append(
            _finding(
                code="coverage_missing_required_slot",
                severity="critical",
                context={"day": int(d), "shift_type": st.value, "was_ignored": was_ignored},
            )
        )

    # Critical: doctor has both onsite and oncall on the same day (double shift)
    double_shift_days_by_doctor: Dict[int, int] = {int(d): 0 for d in problem.participant_doctor_ids}
    for (doc_id, day), shifts in idx.doctor_day_shifts.items():
        if int(doc_id) not in problem.participant_doctor_ids:
            continue
        if len(set(shifts)) >= 2:
            double_shift_days_by_doctor[int(doc_id)] += 1
            findings.append(
                _finding(
                    code=issues.HARD_DOUBLE_SHIFT_SAME_DAY,
                    severity="critical",
                    context={"doctor_id": int(doc_id), "day": int(day)},
                )
            )

    # Critical: onsite slot exists but has no specialist assigned
    # (coverage is handled separately; this is about role mix on onsite)
    for d_raw in problem.days:
        d = int(d_raw)
        if d in ignored_days:
            continue
        if (d, ShiftType.onsite) in ignored_slots:
            continue

        assigned = idx.slot_to_doctors.get((d, ShiftType.onsite), []) or []
        if not assigned:
            continue  # already covered by coverage_missing_required_slot

        has_specialist = False
        for doc_id in assigned:
            doc = problem.doctors.get(int(doc_id))
            if doc and doc.role == DoctorRole.specialist:
                has_specialist = True
                break

        if not has_specialist:
            findings.append(
                _finding(code=issues.COVERAGE_NO_SPECIALIST_DAY, severity="critical", context={"day": int(d)})
            )

    # Warning: rest rule violations (already computed in rest stats)
    for f in rest_findings or []:
        if isinstance(f, dict):
            findings.append(dict(f))

    # Warning: preferred concrete days missed (per preferred day that was not assigned)
    # Policy: keep this severity consistent (warning).
    days_set = set(int(x) for x in problem.days)

    for doc_id in sorted(problem.participant_doctor_ids):
        prefs = problem.preferences.get(doc_id)
        if prefs is None:
            continue

        for d in sorted(set(int(x) for x in (prefs.preferred_onsite_days or []))):
            if d not in days_set:
                continue
            if d in ignored_days:
                continue
            if (d, ShiftType.onsite) in ignored_slots:
                continue
            if not _doctor_has(idx, doctor_id=int(doc_id), day=int(d), shift_type=ShiftType.onsite):
                findings.append(
                    _finding(
                        code=issues.PREFERENCE_MISS,
                        severity="warning",
                        context={"doctor_id": int(doc_id), "day": int(d), "shift_type": ShiftType.onsite.value},
                    )
                )

        for d in sorted(set(int(x) for x in (prefs.preferred_oncall_days or []))):
            if d not in days_set:
                continue
            if d in ignored_days:
                continue
            if (d, ShiftType.oncall) in ignored_slots:
                continue
            if not _doctor_has(idx, doctor_id=int(doc_id), day=int(d), shift_type=ShiftType.oncall):
                findings.append(
                    _finding(
                        code=issues.PREFERENCE_MISS,
                        severity="warning",
                        context={"doctor_id": int(doc_id), "day": int(d), "shift_type": ShiftType.oncall.value},
                    )
                )

    return findings, double_shift_days_by_doctor


# ----------------------------- rankings -----------------------------------------


def _build_rankings(
    *,
    per_doctor_rows: List[Dict[str, Any]],
    top_n: int = 5,
) -> Dict[str, Any]:
    """
    Build deterministic rankings:
    - top_unhappy: highest score first (score = penalty-like measure, higher => worse)
    - top_happy: lowest score first, but we return score as negative (higher => better)
    """

    # Defensive: if score is missing, treat it as 0.0
    def _score(row: Dict[str, Any]) -> float:
        try:
            v = row.get("score")
            return float(v) if v is not None else 0.0
        except Exception:
            return 0.0

    # Unhappy: worst score first
    unhappy_sorted = sorted(per_doctor_rows, key=lambda r: (-_score(r), int(r.get("doctor_id", 0))))
    unhappy = unhappy_sorted[: int(top_n)]

    # Happy: best (lowest) score first
    happy_sorted = sorted(per_doctor_rows, key=lambda r: (_score(r), int(r.get("doctor_id", 0))))
    happy = happy_sorted[: int(top_n)]

    def _reasons_codes(row: Dict[str, Any]) -> List[str]:
        # Stable, short reason codes for FE (no messages here).
        reasons: List[str] = []
        if int(row.get("rest_violations", 0)) > 0:
            reasons.append("rest_violations")
        if int(row.get("preferred_days_missed", 0)) > 0:
            reasons.append("preferred_days_missed")
        if int(row.get("_double_shift_days", 0)) > 0:
            reasons.append(issues.HARD_DOUBLE_SHIFT_SAME_DAY)
        if float(row.get("preference_fulfillment_pct", 100.0)) < 100.0:
            reasons.append("preferences_not_fully_met")
        # Keep list short and stable
        return reasons[:3]

    top_unhappy = [
        {
            "doctor_id": int(r["doctor_id"]),
            "score": float(_score(r)),
            "reasons_codes": _reasons_codes(r),
        }
        for r in unhappy
    ]

    top_happy = []
    for r in happy:
        reasons: List[str] = []
        if int(r.get("rest_violations", 0)) == 0:
            reasons.append("good_rest")
        if float(r.get("preference_fulfillment_pct", 100.0)) >= float(scoring.happy_preferences_met_threshold_pct()):
            reasons.append("preferences_met")
        # score convention: higher=better for the "happy" list
        top_happy.append(
            {
                "doctor_id": int(r["doctor_id"]),
                "score": float(-_score(r)),
                "reasons_codes": reasons[:3],
            }
        )

    return {"top_unhappy": top_unhappy, "top_happy": top_happy}


# ----------------------------- public API ---------------------------------------


def compute_quality(*, problem: ProblemData, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compute full diagnostics payload for a schedule snapshot.

    Returns a JSON-serializable dict:
    {
      "summary": {...},
      "details": {
        "findings": [...],
        "per_doctor": [...],
        "rankings": {...},
        "components": {...}  # optional, useful for debugging
      }
    }
    """
    meta_any = payload.get("meta") or {"labels": []}
    meta: Dict[str, Any] = dict(meta_any) if isinstance(meta_any, dict) else {"labels": []}

    assignments_any = payload.get("assignments") or []
    assignments: List[Any] = list(assignments_any) if isinstance(assignments_any, list) else []

    ignored_days, ignored_slots = _extract_ignored_from_meta(meta)
    idx = _build_index(assignments)

    # Coverage (final semantics: per slot)
    coverage_missing_required_slots, missing_slots = compute_coverage_missing_required_slots(
        problem=problem, idx=idx, ignored_days=ignored_days, ignored_slots=ignored_slots
    )

    # Backward compatibility field (deprecated KPI)
    understaffed_days = compute_understaffed_days(
        problem=problem, idx=idx, ignored_days=ignored_days, ignored_slots=ignored_slots
    )

    # Global preference fulfillment
    pref_pct = compute_preference_fulfillment_pct(
        problem=problem, idx=idx, ignored_days=ignored_days, ignored_slots=ignored_slots
    )

    # Rest (global + per doctor)
    rest_pen, rest_viol, rest_viol_by_doc, rest_pen_by_doc, rest_findings = _compute_rest_stats(
        problem=problem, idx=idx
    )

    # Preferred concrete days (global + per doctor)
    pref_days_pen, pref_days_pen_by_doc = _compute_preferred_days_penalty_per_doctor(
        problem=problem, idx=idx, ignored_days=ignored_days, ignored_slots=ignored_slots
    )

    # Totals (global + per doctor)
    totals_pen, totals_pen_by_doc = _compute_totals_penalty_per_doctor(problem=problem, idx=idx)

    # Fairness (global + per doctor + index)
    fairness_pen, fairness_index, fairness_pen_by_doc = _compute_fairness_stats(problem=problem, idx=idx)

    # Weekday patterns (global + per doctor)
    weekday_pen, weekday_pen_by_doc = _compute_weekday_patterns_penalty_per_doctor(problem=problem, idx=idx)

    # Preferred partners (global + per doctor bonus share)
    partners_pen, partners_bonus_by_doc = _compute_preferred_partners_bonus_by_doctor(problem=problem, idx=idx)

    # Friday if weekend off (global + per doctor)
    fri_pen, fri_pen_by_doc = _compute_friday_free_weekend_penalty_per_doctor(problem=problem, idx=idx)

    # Total penalty (legacy, still useful for debug)
    penalty_total = int(rest_pen + pref_days_pen + totals_pen + fairness_pen + weekday_pen + partners_pen + fri_pen)

    # Findings + hard issues count
    findings, double_shift_days_by_doc = _build_findings(
        problem=problem,
        payload=payload,
        idx=idx,
        ignored_days=ignored_days,
        ignored_slots=ignored_slots,
        missing_slots=missing_slots,
        rest_findings=rest_findings,
    )

    hard_issues_count = int(sum(1 for f in findings if str(f.get("severity")) == "critical"))

    # Per-doctor blocks
    onsite_total_by_doc, oncall_total_by_doc = _assigned_totals_per_doctor(problem=problem, idx=idx)
    pref_pct_by_doc, pref_missed_by_doc = _compute_preference_stats_per_doctor(
        problem=problem, idx=idx, ignored_days=ignored_days, ignored_slots=ignored_slots
    )

    per_doctor: List[Dict[str, Any]] = []
    for doc_id in sorted(problem.participant_doctor_ids):
        doc_id_i = int(doc_id)

        # A simple per-doctor score derived from the same components as the solver objective.
        # Higher score => worse (used for "top_unhappy").
        score = 0.0
        score += float(rest_pen_by_doc.get(doc_id_i, 0))
        score += float(pref_days_pen_by_doc.get(doc_id_i, 0))
        score += float(totals_pen_by_doc.get(doc_id_i, 0))
        score += float(fairness_pen_by_doc.get(doc_id_i, 0))
        score += float(weekday_pen_by_doc.get(doc_id_i, 0))
        score += float(fri_pen_by_doc.get(doc_id_i, 0))
        score += float(partners_bonus_by_doc.get(doc_id_i, 0.0))  # bonus is negative

        row: Dict[str, Any] = {
            "doctor_id": doc_id_i,
            "display_name": _display_name_from_snapshot(payload, doc_id_i),
            "assigned_onsite_total": int(onsite_total_by_doc.get(doc_id_i, 0)),
            "assigned_oncall_total": int(oncall_total_by_doc.get(doc_id_i, 0)),
            "rest_violations": int(rest_viol_by_doc.get(doc_id_i, 0)),
            "preference_fulfillment_pct": float(pref_pct_by_doc.get(doc_id_i, 100.0)),
            "preferred_days_missed": int(pref_missed_by_doc.get(doc_id_i, 0)),
            "score": float(score),
            # Internal helper fields for rankings reasons (not part of DTO, but still pure dict)
            "_double_shift_days": int(double_shift_days_by_doc.get(doc_id_i, 0)),
        }
        per_doctor.append(row)

    rankings = _build_rankings(per_doctor_rows=per_doctor, top_n=5)

    summary: Dict[str, Any] = {
        # NEW (final contract KPIs)
        "coverage_missing_required_slots": int(coverage_missing_required_slots),
        "hard_issues_count": int(hard_issues_count),
        "rest_violations": int(rest_viol),
        "fairness_index": float(max(0.0, min(1.0, fairness_index))),
        "preference_fulfillment_pct": float(max(0.0, min(100.0, pref_pct))),
        # OLD (deprecated, kept for backward compatibility)
        "penalty_total": int(penalty_total),
        "understaffed_days": int(understaffed_days),
    }

    details: Dict[str, Any] = {
        "findings": list(findings),
        "per_doctor": list(per_doctor),
        "rankings": dict(rankings),
        "components": {
            "rest_penalty": int(rest_pen),
            "preferred_days_penalty": int(pref_days_pen),
            "totals_penalty": int(totals_pen),
            "fairness_penalty": int(fairness_pen),
            "weekday_patterns_penalty": int(weekday_pen),
            "preferred_partners_penalty": int(partners_pen),
            "friday_free_weekend_penalty": int(fri_pen),
        },
    }

    return {"summary": summary, "details": details}
