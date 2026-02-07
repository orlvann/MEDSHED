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

IGNORE POLICY (final):
- ignore_days does not exist anymore.
- Required/ignored scheduling scope is controlled ONLY by ignore_slots: set[(day, shift_type)].
- Diagnostics parsing supports meta.exceptions as "audit hints" only:
  - slot marker rows (must have day + shift_type), e.g. ignore-slot markers,
  - action rows (must NOT have day/shift_type), e.g. force publish acceptance with justification.
  Diagnostics must never use exceptions to "improve" metrics.
  (We project meta.exceptions into details.audit[].)

Example (input payload shape, minimal):
{
  "participant_doctor_ids": [101, 102],
  "assignments": [
    {"day": 1, "shift_type": "onsite", "doctor_id": 101},
    {"day": 1, "shift_type": "oncall", "doctor_id": 102},
  ],
  "meta": {"labels": [], "exceptions": [{"code":"coverage_ignored_slot","day":2,"shift_type":"onsite"}]},
  "inputs_snapshot": {"doctors": {"101": {
  "display_name":"Alice","role":"specialist","is_head":True,"is_active_at_snapshot":True}}}
}

Example (output shape):
{
  "summary": {
    "coverage_missing_required_slots": 0,
    "hard_issues_count": 0,
    "rest_violations": 0,
    "fairness_index": 1.0,
    "preference_fulfillment_pct": 100.0,
    "penalty_total": 0,
    "understaffed_days": 0
  },
  "details": {
    "findings": [...],
    "per_doctor": [...],
    "rankings": {"top_unhappy":[...],"top_happy":[...]},
    "components": {...}
  }
}
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from backend.core import issues, scoring
from backend.core.fairness_expected_edit import compute_expected_map_for_fairness_edit
from backend.core.rest_window import is_sat_to_sun, rest_violation_kind
from backend.core.types import HardModel, ProblemData
from backend.models.common_enums import DoctorRole, ShiftType

# ----------------------------- issues codes (safe) -----------------------------


def _issue_code(name: str, fallback: str) -> str:
    """
    Safely get a string code from backend.core.issues.

    Why:
    - We want stable codes, but we also want this module to not crash
      if an attribute name changes in issues.py.
    """
    v = getattr(issues, name, None)
    if v is None:
        return str(fallback)
    return str(getattr(v, "value", v))


# Stable codes used by this module (with safe fallbacks).
_CODE_COVERAGE_IGNORED_SLOT = _issue_code("COVERAGE_IGNORED_SLOT", "coverage_ignored_slot")
_CODE_COVERAGE_MISSING_REQUIRED_SLOT = _issue_code("COVERAGE_MISSING_REQUIRED_SLOT", "coverage_missing_required_slot")
_CODE_COVERAGE_NO_SPECIALIST_DAY = _issue_code("COVERAGE_NO_SPECIALIST_DAY", "coverage_no_specialist_day")
_CODE_HARD_DOUBLE_SHIFT_SAME_DAY = _issue_code("HARD_DOUBLE_SHIFT_SAME_DAY", "hard_double_shift_same_day")
_CODE_REST_CONSECUTIVE_VIOLATION = _issue_code("REST_CONSECUTIVE_VIOLATION", "rest_consecutive_violation")
_CODE_PREFERENCE_MISS = _issue_code("PREFERENCE_MISS", "preference_miss")


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
    # Defensive: some ProblemData builders may leave weekdays=None.
    weekdays = getattr(problem, "weekdays", None)
    if isinstance(weekdays, dict):
        wd = weekdays.get(day)
    else:
        wd = None
    if wd is not None:
        return int(wd)
    return int(datetime(problem.year, problem.month, day).weekday())


def _extract_ignored_slots_from_meta(meta: Dict[str, Any]) -> Set[Tuple[int, ShiftType]]:
    """
    Parse ignored slots out of meta.exceptions.

    Supported records (preferred, stable):
    - {"code": "coverage_ignored_slot", "day": 12, "shift_type": "onsite"|"oncall", ...}

    Backward compatible (legacy):
    - {"code": "ignored_slot", "day": 12, "shift_type": "onsite"|"oncall", ...}

    Returns:
        ignored_slots set[(day, ShiftType)]
    """
    ignored_slots: Set[Tuple[int, ShiftType]] = set()

    exceptions = meta.get("exceptions") or []
    if not isinstance(exceptions, list):
        return ignored_slots

    # We support both stable and legacy codes to avoid breaking old payloads.
    stable_code = str(_CODE_COVERAGE_IGNORED_SLOT).strip().lower()
    legacy_code = "ignored_slot"

    for e in exceptions:
        if not isinstance(e, dict):
            continue

        code = str(e.get("code") or "").strip().lower()
        if code not in (stable_code, legacy_code):
            continue

        day = _safe_int(e.get("day"))
        st = _normalize_shift_type(e.get("shift_type"))
        if day is not None and st is not None:
            ignored_slots.add((day, st))

    return ignored_slots


def _extract_audit_common_fields(e: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract common audit fields from a meta.exceptions record.

    We keep these fields JSON-friendly and optional:
    - accepted_at (ISO string)
    - accepted_by_user_id (int when possible)
    - justification (string)
    """
    out: Dict[str, Any] = {}

    accepted_at = e.get("accepted_at")
    if isinstance(accepted_at, str) and accepted_at.strip():
        out["accepted_at"] = accepted_at.strip()

    accepted_by = e.get("accepted_by_user_id")
    if accepted_by is not None:
        try:
            out["accepted_by_user_id"] = int(accepted_by)
        except Exception:
            # Defensive: keep raw value if it's not int-coercible
            out["accepted_by_user_id"] = accepted_by

    justification = e.get("justification")
    if isinstance(justification, str) and justification.strip():
        out["justification"] = justification.strip()

    return out


def _extract_audit_from_meta(meta: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Project "decision history" into a dedicated diagnostics field: details.audit[].

    Rule (final):
    - Audit is "what a human decided / accepted / clicked".
    - We MUST distinguish two shapes of decision history that BOTH live in details.audit[]:
      1) slot marker rows: have (day + shift_type) and represent a human decision about a concrete slot
         (e.g., ignore coverage for this slot, head commitment resolution for this slot),
      2) action rows: have NO (day/shift_type) and represent a human decision about the whole action
         (e.g., force publish acceptance), optionally with justification.
    """
    out: List[Dict[str, Any]] = []

    exceptions = meta.get("exceptions") or []
    if not isinstance(exceptions, list):
        return out

    stable_ignore_code = str(_CODE_COVERAGE_IGNORED_SLOT).strip().lower()
    legacy_ignore_code = "ignored_slot"

    # Allowed kind values (defensive / backward compatible).
    # We ACCEPT various inputs but we NORMALIZE to a small stable set in output.
    #
    # Output kinds (stable):
    # - "generation_ignore" (slot marker)
    # - "head_commitment_resolution" (slot marker)
    # - "publish_acceptance" (action row)
    allowed_kinds = {
        # ignore-slot marker variants
        "generation_ignore",
        "ignore_slot",
        # head resolution (slot marker)
        "head_commitment_resolution",
        # publish acceptance (action row) variants
        "publish_acceptance",
        "force_publish_acceptance",
    }

    def _normalize_kind(raw: Optional[str]) -> Optional[str]:
        if raw in ("ignore_slot", "generation_ignore"):
            return "generation_ignore"
        if raw == "head_commitment_resolution":
            return "head_commitment_resolution"
        if raw in ("publish_acceptance", "force_publish_acceptance"):
            return "publish_acceptance"
        return None

    for e in exceptions:
        if not isinstance(e, dict):
            continue

        code_raw = str(e.get("code") or "").strip()
        code_lc = code_raw.lower()
        if not code_lc:
            continue

        # Optional kind passed through from payload (if present).
        kind_raw = e.get("kind")
        kind: Optional[str] = None
        if isinstance(kind_raw, str) and kind_raw.strip() in allowed_kinds:
            kind = _normalize_kind(kind_raw.strip())

        has_acceptance_context = any(k in e for k in ("justification", "accepted_by_user_id", "accepted_at"))

        # -------------------------
        # 1) SLOT MARKERS
        # -------------------------
        # A) ignore-slot -> slot marker
        if code_lc in (stable_ignore_code, legacy_ignore_code):
            day = _safe_int(e.get("day"))
            st = _normalize_shift_type(e.get("shift_type"))
            if day is None or st is None:
                continue

            # Enforce normalized kind for ignore-slot marker rows.
            kind = "generation_ignore"

            row: Dict[str, Any] = {
                "kind": kind,
                "code": code_raw,
                "day": int(day),
                "shift_type": st.value,
            }

            # IMPORTANT:
            # Slot marker rows MUST carry acceptance metadata too,
            # because FE needs to show "who accepted it" and "when".
            row.update(_extract_audit_common_fields(e))

            out.append(row)
            continue

        # B) head commitment resolution -> slot marker (must have day+shift_type)
        if kind == "head_commitment_resolution":
            day = _safe_int(e.get("day"))
            st = _normalize_shift_type(e.get("shift_type"))
            if day is None or st is None:
                # This kind is defined as slot-scoped, so skip malformed rows.
                continue

            row: Dict[str, Any] = {
                "kind": kind,
                "code": code_raw,
                "day": int(day),
                "shift_type": st.value,
            }

            # Keep chosen_head_id when present (so FE can show what was chosen).
            chosen_head_id = _safe_int(e.get("chosen_head_id"))
            if chosen_head_id is not None:
                row["chosen_head_id"] = int(chosen_head_id)

            # Also keep acceptance metadata (who/when).
            row.update(_extract_audit_common_fields(e))

            out.append(row)
            continue

        # -------------------------
        # 2) ACTION ROWS
        # -------------------------
        # Publish acceptance is action-level; it must NOT carry day/shift_type in audit,
        # because justification is for the whole action, not for a single slot.
        #
        # Include action rows when:
        # - kind is explicitly publish_acceptance OR generation_ignore, OR
        # - kind is missing but acceptance context exists (backward compatible -> publish_acceptance).
        #
        # IMPORTANT:
        # Slot markers like COVERAGE_IGNORED_SLOT DO appear in details.audit[] as kind="generation_ignore".
        # They must NOT "improve" diagnostics metrics; we only use them to:
        # - mark matching gap findings with context.was_ignored=True,
        # - preserve user decision history for UI.
        if kind is None and has_acceptance_context:
            kind = "publish_acceptance"

        if kind not in ("publish_acceptance", "generation_ignore"):
            continue

        # Action rows MUST NOT carry slot scope.
        # If they do, treat them as malformed and skip (slot marker rows are handled above).
        if _safe_int(e.get("day")) is not None or _normalize_shift_type(e.get("shift_type")) is not None:
            continue

        row: Dict[str, Any] = {"kind": kind, "code": code_raw}
        row.update(_extract_audit_common_fields(e))

        out.append(row)

    # Deterministic order for stable tests/UI:
    # - action rows first (no day/shift_type), then slot rows (with day/shift_type)
    # - within group: by kind, code, day, shift_type, accepted_at
    def _sort_key(x: Dict[str, Any]) -> tuple:
        is_slot_marker = x.get("day") is not None and x.get("shift_type") is not None
        return (
            0 if not is_slot_marker else 1,  # action first
            str(x.get("kind", "")),
            str(x.get("code", "")),
            int(x.get("day", 0)) if x.get("day") is not None else 0,
            str(x.get("shift_type", "")),
            str(x.get("accepted_at", "")),
        )

    out.sort(key=_sort_key)
    return out


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
    ignored_slots: Set[Tuple[int, ShiftType]],
) -> tuple[int, List[Tuple[int, ShiftType]]]:
    """
    Count missing required coverage slots (per slot, not per day).

    Rules:
    - Each day requires 1 onsite and 1 oncall slot (MVP).
    - IMPORTANT: ignore rules DO NOT reduce requirements in diagnostics.
      Ignore exceptions were used only to allow generation, but diagnostics must show real gaps.
    - We still return ignored_slots separately so UI can display that the gap was previously "accepted".

    Returns:
        (missing_count, missing_slots_list)
    """
    missing_slots: List[Tuple[int, ShiftType]] = []

    for d_raw in problem.days:
        d = int(d_raw)

        # NOTE:
        # We DO NOT skip ignored_slots here.
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
    ignored_slots: Set[Tuple[int, ShiftType]],
) -> float:
    """
    Compute percent of satisfied "strong preferences":
    - preferred_onsite_days
    - preferred_oncall_days

    Notes:.
    - Ignore markers MUST NOT improve metrics.
      If a preferred slot was ignored during generation, it is still counted and can be missed.
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

            total += 1
            if _doctor_has(idx, doctor_id=doc_id, day=d, shift_type=ShiftType.onsite):
                ok += 1

        for d_raw in prefs.preferred_oncall_days:
            d = int(d_raw)
            if d not in days_set:
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

            total += 1
            if _doctor_has(idx, doctor_id=doc_id, day=d, shift_type=ShiftType.onsite):
                ok += 1
            else:
                missed += 1

        for d_raw in prefs.preferred_oncall_days:
            d = int(d_raw)
            if d not in days_set:
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
        (
          total_penalty,
          total_violations,
          violations_by_doctor,
          penalty_by_doctor,
          rest_findings
        )
    """
    total_penalty = 0
    total_violations = 0

    violations_by_doctor: Dict[int, int] = {int(d): 0 for d in problem.participant_doctor_ids}
    penalty_by_doctor: Dict[int, int] = {int(d): 0 for d in problem.participant_doctor_ids}
    rest_findings: List[Dict[str, Any]] = []

    days_sorted = [int(d) for d in problem.days]
    days_set = set(days_sorted)

    for doc_id in sorted(problem.participant_doctor_ids):
        doctor = problem.doctors.get(doc_id)
        prefs = problem.preferences.get(doc_id)

        role = doctor.role if doctor else DoctorRole.resident
        allow_weekend_consecutive = bool(prefs.allow_weekend_consecutive_onsite_oncall) if prefs else False

        cross_w = int(scoring.rest_cross_shift_weight(role=role))

        # ------------------------------------------------------------------
        # Cross-month rest: last day of previous month -> day 1 of current month
        # Mirrors solver logic from objective_builder.attach_rest_objective()
        # ------------------------------------------------------------------
        carry = problem.carryover
        if carry is not None:
            doc_carry = carry.per_doctor.get(int(doc_id))
            edge = list(doc_carry.edge_assignments_last) if doc_carry else []

            if edge:
                # Last calendar day from previous month that appears in edge_assignments_last
                last_prev_day = max(int(e.day) for e in edge)

                # All shift types the doctor had on that last previous day
                prev_day_shifts = [e.shift_type for e in edge if int(e.day) == int(last_prev_day)]

                day1 = 1

                # GUARD: only evaluate if day 1 exists in this ProblemData
                if day1 in days_set:
                    # Weekend boundary check (Sat->Sun across month boundary)
                    weekend_pair = is_sat_to_sun(
                        prev_year=int(carry.prev_year),
                        prev_month=int(carry.prev_month),
                        prev_day=int(last_prev_day),
                        next_year=int(problem.year),
                        next_month=int(problem.month),
                        next_day=int(day1),
                    )

                    # Only evaluate if doctor actually works on day 1 in the current schedule
                    has_day1_onsite = _doctor_has(
                        idx, doctor_id=int(doc_id), day=int(day1), shift_type=ShiftType.onsite
                    )
                    has_day1_oncall = _doctor_has(
                        idx, doctor_id=int(doc_id), day=int(day1), shift_type=ShiftType.oncall
                    )

                    if has_day1_onsite or has_day1_oncall:
                        for prev_st in prev_day_shifts:
                            # prev -> onsite(day 1)
                            if has_day1_onsite:
                                kind = rest_violation_kind(
                                    prev_shift=prev_st,
                                    next_shift=ShiftType.onsite,
                                    is_weekend_pair=bool(weekend_pair),
                                    allow_weekend_consecutive=bool(allow_weekend_consecutive),
                                )

                                if kind == "onsite_onsite":
                                    w = int(scoring.REST_ONS_ONS_WEIGHT)
                                    total_penalty += w
                                    total_violations += 1
                                    violations_by_doctor[int(doc_id)] += 1
                                    penalty_by_doctor[int(doc_id)] += w
                                    rest_findings.append(
                                        _finding(
                                            code=_CODE_REST_CONSECUTIVE_VIOLATION,
                                            severity="warning",
                                            context={
                                                "doctor_id": int(doc_id),
                                                "day": int(day1),
                                                "kind": "onsite_onsite",
                                                "cross_month": True,
                                                "prev_year": int(carry.prev_year),
                                                "prev_month": int(carry.prev_month),
                                                "prev_day": int(last_prev_day),
                                            },
                                        )
                                    )
                                elif kind == "cross":
                                    w = int(cross_w)
                                    total_penalty += w
                                    total_violations += 1
                                    violations_by_doctor[int(doc_id)] += 1
                                    penalty_by_doctor[int(doc_id)] += w
                                    rest_findings.append(
                                        _finding(
                                            code=_CODE_REST_CONSECUTIVE_VIOLATION,
                                            severity="warning",
                                            context={
                                                "doctor_id": int(doc_id),
                                                "day": int(day1),
                                                "kind": "cross",
                                                "cross_month": True,
                                                "prev_year": int(carry.prev_year),
                                                "prev_month": int(carry.prev_month),
                                                "prev_day": int(last_prev_day),
                                            },
                                        )
                                    )

                            # prev -> oncall(day 1)
                            if has_day1_oncall:
                                kind = rest_violation_kind(
                                    prev_shift=prev_st,
                                    next_shift=ShiftType.oncall,
                                    is_weekend_pair=bool(weekend_pair),
                                    allow_weekend_consecutive=bool(allow_weekend_consecutive),
                                )

                                if kind == "oncall_oncall":
                                    w = int(scoring.REST_ONCALL_ONCALL_WEIGHT)
                                    total_penalty += w
                                    total_violations += 1
                                    violations_by_doctor[int(doc_id)] += 1
                                    penalty_by_doctor[int(doc_id)] += w
                                    rest_findings.append(
                                        _finding(
                                            code=_CODE_REST_CONSECUTIVE_VIOLATION,
                                            severity="warning",
                                            context={
                                                "doctor_id": int(doc_id),
                                                "day": int(day1),
                                                "kind": "oncall_oncall",
                                                "cross_month": True,
                                                "prev_year": int(carry.prev_year),
                                                "prev_month": int(carry.prev_month),
                                                "prev_day": int(last_prev_day),
                                            },
                                        )
                                    )
                                elif kind == "cross":
                                    w = int(cross_w)
                                    total_penalty += w
                                    total_violations += 1
                                    violations_by_doctor[int(doc_id)] += 1
                                    penalty_by_doctor[int(doc_id)] += w
                                    rest_findings.append(
                                        _finding(
                                            code=_CODE_REST_CONSECUTIVE_VIOLATION,
                                            severity="warning",
                                            context={
                                                "doctor_id": int(doc_id),
                                                "day": int(day1),
                                                "kind": "cross",
                                                "cross_month": True,
                                                "prev_year": int(carry.prev_year),
                                                "prev_month": int(carry.prev_month),
                                                "prev_day": int(last_prev_day),
                                            },
                                        )
                                    )

        # -----------------------------
        # In-month consecutive day pairs
        # -----------------------------
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
                        code=_CODE_REST_CONSECUTIVE_VIOLATION,
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
                        code=_CODE_REST_CONSECUTIVE_VIOLATION,
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
                            code=_CODE_REST_CONSECUTIVE_VIOLATION,
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
                            code=_CODE_REST_CONSECUTIVE_VIOLATION,
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
    """Backward-compatible wrapper (total penalty)."""
    total_penalty, _pen_by_doc = _compute_totals_penalty_per_doctor(problem=problem, idx=idx)
    return int(total_penalty)


def _compute_totals_penalty_per_doctor(*, problem: ProblemData, idx: _Index) -> tuple[int, Dict[int, int]]:
    """
    Totals penalty (same spirit as objective_builder), per doctor:
    - max_* -> excess^2
    - target_* -> (over^2 + under^2)
    Separate for monthly totals and weekend totals.

    Returns:
        (total_penalty, penalty_by_doctor)
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
    """Backward-compatible wrapper (total penalty + index)."""
    total_penalty, fairness_index, _pen_by_doc = _compute_fairness_stats(problem=problem, idx=idx)
    return int(total_penalty), float(fairness_index)


def _compute_fairness_stats(*, problem: ProblemData, idx: _Index) -> tuple[int, float, Dict[int, int]]:
    """
    Fairness for diagnostics (EDIT stage):
    - expected is computed by compute_expected_map_for_fairness_edit(...)
    - penalty = weight * (abs_dev^2) per category
    - fairness_index is based on mean absolute deviation from expected (per category)

    Returns:
        (total_penalty, fairness_index, penalty_by_doctor)
    """
    total_penalty = 0
    penalty_by_doctor: Dict[int, int] = {int(d): 0 for d in problem.participant_doctor_ids}

    # Weekend / weekday day lists (calendar-based)
    weekend = _weekend_days(problem)
    weekday_days: List[int] = [int(d) for d in problem.days if int(d) not in weekend]
    weekend_days: List[int] = sorted(int(d) for d in weekend)

    # Build groups from current participants
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

    group_to_doctors: Dict[str, List[int]] = {
        "specialist": list(specialist_ids),
        "resident": list(resident_ids),
    }

    # Build a lightweight HardModel ONLY to satisfy the helper signature.
    # In EDIT stage expected does NOT use allowed_slots, so we can pass {} safely.
    model = HardModel(
        year=int(problem.year),
        month=int(problem.month),
        days=[int(d) for d in problem.days],
        active_days=[int(d) for d in problem.days],
        doctors=dict(problem.doctors),
        preferences=dict(problem.preferences),
        participant_doctor_ids=set(int(d) for d in problem.participant_doctor_ids),
        ignore_slots=set(),  # ignored markers must NOT affect fairness evaluation
        allowed_slots={},  # unused in EDIT-stage expected
        seed_hints=None,
    )

    expected_map = compute_expected_map_for_fairness_edit(
        model=model, problem=problem, group_to_doctors=group_to_doctors
    )

    def _count(doc_id: int, days: List[int], st: ShiftType) -> int:
        c = 0
        for d in days:
            if _doctor_has(idx, doctor_id=int(doc_id), day=int(d), shift_type=st):
                c += 1
        return int(c)

    # Categories definition:
    # (days_list, shift_type, category_name, weight)
    categories: List[tuple[List[int], ShiftType, str, int]] = [
        (
            weekday_days,
            ShiftType.onsite,
            "onsite_weekday",
            int(scoring.fairness_weight(shift_type=ShiftType.onsite, is_weekend=False)),
        ),
        (
            weekend_days,
            ShiftType.onsite,
            "onsite_weekend",
            int(scoring.fairness_weight(shift_type=ShiftType.onsite, is_weekend=True)),
        ),
        (
            weekday_days,
            ShiftType.oncall,
            "oncall_weekday",
            int(scoring.fairness_weight(shift_type=ShiftType.oncall, is_weekend=False)),
        ),
        (
            weekend_days,
            ShiftType.oncall,
            "oncall_weekend",
            int(scoring.fairness_weight(shift_type=ShiftType.oncall, is_weekend=True)),
        ),
    ]

    index_parts: List[float] = []

    for days_list, st, category_name, w in categories:
        # We compute fairness within each group separately, then average index parts.
        for group_ids in (specialist_ids, resident_ids):
            if len(group_ids) <= 1:
                # If group has 0 or 1 person, fairness in that group is trivially perfect.
                index_parts.append(1.0)
                continue

            actuals = [_count(doc_id, days_list, st) for doc_id in group_ids]
            expecteds = [int(expected_map.get((int(doc_id), st, category_name), 0)) for doc_id in group_ids]

            # Penalty per doctor (abs_dev^2)
            for doc_id, actual, exp in zip(group_ids, actuals, expecteds):
                abs_dev = abs(int(actual) - int(exp))
                p = int(w) * (abs_dev * abs_dev)
                total_penalty += int(p)
                penalty_by_doctor[int(doc_id)] += int(p)

            # Index part: deviation relative to expected mean (not actual mean)
            mean_exp = (sum(expecteds) / len(expecteds)) if expecteds else 0.0
            if mean_exp <= 0.0:
                index_parts.append(1.0)
            else:
                mean_abs_dev = sum(abs(int(a) - int(e)) for a, e in zip(actuals, expecteds)) / len(expecteds)
                score = 1.0 - min(1.0, float(mean_abs_dev / mean_exp))
                index_parts.append(max(0.0, float(score)))

    fairness_index = float(sum(index_parts) / len(index_parts)) if index_parts else 1.0
    fairness_index = float(max(0.0, min(1.0, fairness_index)))

    return int(total_penalty), float(fairness_index), penalty_by_doctor


# ----------------------------- weekday patterns (per-doctor penalty) -------------


def compute_weekday_patterns_penalty(*, problem: ProblemData, idx: _Index) -> int:
    """Backward-compatible wrapper (total penalty)."""
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
    """Backward-compatible wrapper (total penalty)."""
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
    """Backward-compatible wrapper (total penalty)."""
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
    ignored_slots: Set[Tuple[int, ShiftType]],
) -> int:
    """Backward-compatible wrapper (total penalty)."""
    total_penalty, _pen_by_doc = _compute_preferred_days_penalty_per_doctor(
        problem=problem, idx=idx, ignored_slots=ignored_slots
    )
    return int(total_penalty)


def _compute_preferred_days_penalty_per_doctor(
    *,
    problem: ProblemData,
    idx: _Index,
    ignored_slots: Set[Tuple[int, ShiftType]],
) -> tuple[int, Dict[int, int]]:
    """
    Penalty for missing preferred concrete days (same logic as objective_builder):
    - Ignore markers MUST NOT improve metrics.
    If a preferred slot was ignored during generation, it is still counted and can be missed.

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

            if not _doctor_has(idx, doctor_id=doc_id, day=d, shift_type=ShiftType.onsite):
                p += miss_w

        for d_raw in prefs.preferred_oncall_days:
            d = int(d_raw)
            if d not in days_set:
                continue

            if not _doctor_has(idx, doctor_id=doc_id, day=d, shift_type=ShiftType.oncall):
                p += miss_w

        penalty_by_doctor[int(doc_id)] = int(p)
        total_penalty += int(p)

    return int(total_penalty), penalty_by_doctor


# ----------------------------- per-doctor assignments totals ---------------------


def _assigned_totals_per_doctor(*, problem: ProblemData, idx: _Index) -> tuple[Dict[int, int], Dict[int, int]]:
    """Count assigned totals for each doctor (onsite and oncall)."""
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

    # Critical: missing coverage slots (Gaps)
    # Even if a gap was previously "accepted" (ignored during generation),
    # diagnostics must still show it as a real gap.
    for d, st in missing_slots:
        was_ignored = bool((int(d), st) in ignored_slots)
        findings.append(
            _finding(
                code=_CODE_COVERAGE_MISSING_REQUIRED_SLOT,
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
                    code=_CODE_HARD_DOUBLE_SHIFT_SAME_DAY,
                    severity="critical",
                    context={"doctor_id": int(doc_id), "day": int(day)},
                )
            )

    # Critical: in this day there must be at least 1 specialist assigned on ANY shift.
    for d_raw in problem.days:
        d = int(d_raw)

        onsite_assigned = idx.slot_to_doctors.get((d, ShiftType.onsite), []) or []
        oncall_assigned = idx.slot_to_doctors.get((d, ShiftType.oncall), []) or []
        assigned_any = set(int(x) for x in (onsite_assigned + oncall_assigned))

        has_specialist = False
        for doc_id in assigned_any:
            doc = problem.doctors.get(int(doc_id))
            if doc and doc.role == DoctorRole.specialist:
                has_specialist = True
                break

        if not has_specialist:
            was_ignored_day = bool(
                (int(d), ShiftType.onsite) in ignored_slots and (int(d), ShiftType.oncall) in ignored_slots
            )
            findings.append(
                _finding(
                    code=_CODE_COVERAGE_NO_SPECIALIST_DAY,
                    severity="critical",
                    context={
                        "day": int(d),
                        "day_empty": bool(len(assigned_any) == 0),
                        "assigned_doctor_ids": sorted(int(x) for x in assigned_any),
                        "was_ignored_day": bool(was_ignored_day),
                        "was_ignored_onsite": bool((int(d), ShiftType.onsite) in ignored_slots),
                        "was_ignored_oncall": bool((int(d), ShiftType.oncall) in ignored_slots),
                    },
                )
            )

    # Warning: rest rule violations (already computed in rest stats)
    for f in rest_findings or []:
        if isinstance(f, dict):
            findings.append(dict(f))

    # Warning: preferred concrete days missed (per preferred day that was not assigned)
    days_set = set(int(x) for x in problem.days)

    for doc_id in sorted(problem.participant_doctor_ids):
        prefs = problem.preferences.get(doc_id)
        if prefs is None:
            continue

        for d in sorted(set(int(x) for x in (prefs.preferred_onsite_days or []))):
            if d not in days_set:
                continue
            if not _doctor_has(idx, doctor_id=int(doc_id), day=int(d), shift_type=ShiftType.onsite):
                findings.append(
                    _finding(
                        code=_CODE_PREFERENCE_MISS,
                        severity="warning",
                        context={"doctor_id": int(doc_id), "day": int(d), "shift_type": ShiftType.onsite.value},
                    )
                )

        for d in sorted(set(int(x) for x in (prefs.preferred_oncall_days or []))):
            if d not in days_set:
                continue
            if not _doctor_has(idx, doctor_id=int(doc_id), day=int(d), shift_type=ShiftType.oncall):
                findings.append(
                    _finding(
                        code=_CODE_PREFERENCE_MISS,
                        severity="warning",
                        context={"doctor_id": int(doc_id), "day": int(d), "shift_type": ShiftType.oncall.value},
                    )
                )

    return findings, double_shift_days_by_doctor


# ----------------------------- rankings -----------------------------------------


def _build_rankings(
    *,
    per_doctor_rows: List[Dict[str, Any]],
    double_shift_days_by_doctor: Dict[int, int],
    top_n: int = 5,
) -> Dict[str, Any]:
    """
    Build deterministic rankings (POINTS convention):
    - score = points (higher => better/happier)
    - top_happy: highest score first
    - top_unhappy: lowest score first (often negative)

    Output shape:
    {
      "top_unhappy": [{"doctor_id": 1, "score": -123.0, "reasons_codes":[...]}],
      "top_happy":   [{"doctor_id": 2, "score": 0.0, "reasons_codes":[...]}]
    }
    """

    def _score(row: Dict[str, Any]) -> float:
        # Defensive: if score is missing, treat it as 0.0
        try:
            v = row.get("score")
            return float(v) if v is not None else 0.0
        except Exception:
            return 0.0

    def _reasons_codes(row: Dict[str, Any]) -> List[str]:
        # Stable, short reason codes for FE (no messages here).
        doc_id = int(row.get("doctor_id", 0))
        reasons: List[str] = []
        if int(row.get("rest_violations", 0)) > 0:
            reasons.append("rest_violations")
        if int(row.get("preferred_days_missed", 0)) > 0:
            reasons.append("preferred_days_missed")
        if int(double_shift_days_by_doctor.get(doc_id, 0)) > 0:
            reasons.append(_CODE_HARD_DOUBLE_SHIFT_SAME_DAY)
        if float(row.get("preference_fulfillment_pct", 100.0)) < 100.0:
            reasons.append("preferences_not_fully_met")
        return reasons[:3]

    # Unhappy: lowest score first, tie-break by doctor_id ascending.
    # Defensive: normalize NaN to 0.0 so ordering is deterministic.
    def _unhappy_sort_key(r: Dict[str, Any]) -> tuple:
        s = _score(r)
        try:
            if s != s:  # NaN check
                s = 0.0
        except Exception:
            s = 0.0
        return (float(s), int(r.get("doctor_id", 0)))

    unhappy_sorted = sorted(per_doctor_rows, key=_unhappy_sort_key)
    unhappy = unhappy_sorted[: int(top_n)]

    # Happy: highest score first, tie-break by doctor_id ascending.
    # Defensive: normalize NaN to 0.0 so ordering is deterministic.
    def _happy_sort_key(r: Dict[str, Any]) -> tuple:
        s = _score(r)
        try:
            if s != s:  # NaN check
                s = 0.0
        except Exception:
            s = 0.0
        return (-float(s), int(r.get("doctor_id", 0)))

    happy_sorted = sorted(per_doctor_rows, key=_happy_sort_key)
    happy = happy_sorted[: int(top_n)]

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
        top_happy.append(
            {
                "doctor_id": int(r["doctor_id"]),
                "score": float(_score(r)),
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
        "components": {...}
      }
    }
    """
    meta_any = payload.get("meta") or {"labels": []}
    meta: Dict[str, Any] = dict(meta_any) if isinstance(meta_any, dict) else {"labels": []}

    # Separate "admin decisions history" into details.audit[] (projection from meta.exceptions).
    audit_rows = _extract_audit_from_meta(meta)

    assignments_any = payload.get("assignments") or []
    assignments: List[Any] = list(assignments_any) if isinstance(assignments_any, list) else []

    ignored_slots = _extract_ignored_slots_from_meta(meta)
    idx = _build_index(assignments)

    # Coverage (final semantics: per slot)
    coverage_missing_required_slots, missing_slots = compute_coverage_missing_required_slots(
        problem=problem, idx=idx, ignored_slots=ignored_slots
    )

    # Backward compatibility field (deprecated KPI)
    understaffed_days = compute_understaffed_days(problem=problem, idx=idx, ignored_slots=ignored_slots)

    # Global preference fulfillment
    pref_pct = compute_preference_fulfillment_pct(problem=problem, idx=idx, ignored_slots=ignored_slots)

    # Rest (global + per doctor)
    rest_pen, rest_viol, rest_viol_by_doc, rest_pen_by_doc, rest_findings = _compute_rest_stats(
        problem=problem, idx=idx
    )

    # Preferred concrete days (global + per doctor)
    pref_days_pen, pref_days_pen_by_doc = _compute_preferred_days_penalty_per_doctor(
        problem=problem, idx=idx, ignored_slots=ignored_slots
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
        ignored_slots=ignored_slots,
        missing_slots=missing_slots,
        rest_findings=rest_findings,
    )

    hard_issues_count = int(sum(1 for f in findings if str(f.get("severity")) == "critical"))

    # Per-doctor blocks
    onsite_total_by_doc, oncall_total_by_doc = _assigned_totals_per_doctor(problem=problem, idx=idx)
    pref_pct_by_doc, pref_missed_by_doc = _compute_preference_stats_per_doctor(
        problem=problem, idx=idx, ignored_slots=ignored_slots
    )

    per_doctor: List[Dict[str, Any]] = []
    for doc_id in sorted(problem.participant_doctor_ids):
        doc_id_i = int(doc_id)

        # Build a per-doctor "penalty-like" score from the same components as solver objective.
        # Then convert it to "points" where HIGHER means BETTER:
        # points = -penalty_like
        penalty_like = 0.0
        penalty_like += float(rest_pen_by_doc.get(doc_id_i, 0))
        penalty_like += float(pref_days_pen_by_doc.get(doc_id_i, 0))
        penalty_like += float(totals_pen_by_doc.get(doc_id_i, 0))
        penalty_like += float(fairness_pen_by_doc.get(doc_id_i, 0))
        penalty_like += float(weekday_pen_by_doc.get(doc_id_i, 0))
        penalty_like += float(fri_pen_by_doc.get(doc_id_i, 0))
        penalty_like += float(partners_bonus_by_doc.get(doc_id_i, 0.0))  # bonus is negative

        score_points = float(-penalty_like)

        # IMPORTANT:
        # Keep per_doctor rows aligned with the public DTO contract.
        # Do NOT add internal helper keys here.
        row: Dict[str, Any] = {
            "doctor_id": doc_id_i,
            "display_name": _display_name_from_snapshot(payload, doc_id_i),
            "assigned_onsite_total": int(onsite_total_by_doc.get(doc_id_i, 0)),
            "assigned_oncall_total": int(oncall_total_by_doc.get(doc_id_i, 0)),
            "rest_violations": int(rest_viol_by_doc.get(doc_id_i, 0)),
            "preference_fulfillment_pct": float(pref_pct_by_doc.get(doc_id_i, 100.0)),
            "preferred_days_missed": int(pref_missed_by_doc.get(doc_id_i, 0)),
            # "score" is points: higher => happier/better
            "score": float(score_points),
        }
        per_doctor.append(row)

    rankings = _build_rankings(
        per_doctor_rows=per_doctor,
        double_shift_days_by_doctor=double_shift_days_by_doc,
        top_n=5,
    )

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
        "audit": list(audit_rows),
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
