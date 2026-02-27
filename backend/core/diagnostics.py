# backend/core/diagnostics.py
"""
Diagnostics (core) — compute schedule quality metrics from a snapshot payload.

This module must stay "pure core":
- no DB access,
- no FastAPI/Pydantic,
- operates only on ProblemData + snapshot payload dict,
- returns only JSON-serializable Python structures (dict/list/str/int/float/bool).

It produces a dict suitable for storage in ScheduleDiagnostics.quality:
{
  "summary": {...},
  "details": {...}
}

OUTPUT CONTRACT (current)
------------------------
summary includes stable KPI fields used by the API/FE:
- coverage_missing_required_slots (int)  # per-slot gaps (onsite/oncall)
- hard_issues_count (int)               # number of "critical" findings
- rest_violations (int)                 # total consecutive-rest violations
- fairness_index (float 0..1)           # higher is better
- preference_fulfillment_pct (float 0..100)

Backward-compatible summary fields (still emitted):
- penalty_total (int)
- understaffed_days (int)  # deprecated, day-level

details includes:
- findings[]    # list of {code, severity, context}
- audit[]       # projection of meta.exceptions (human decisions history)
- per_doctor[]  # per-participant metrics (includes ui_stars + ui_reasons_codes + ui_components)
- rankings{}    # {top_happy: [...], top_unhappy: [...]} derived from per_doctor.ui_stars
- components{}  # global penalties (rest/totals/fairness/...)


IGNORE POLICY (diagnostics truth vs generation helpers)
------------------------------------------------------
- ignore_days does not exist.
- "Ignore" is controlled only by ignore_slots (set of (day, shift_type)).
- IMPORTANT: ignored slots MUST NOT improve diagnostics metrics.
  Diagnostics always reports real gaps and violations even if a slot was previously accepted.
- The only effect of ignore_slots in diagnostics is:
  - findings context can mark gaps as "was_ignored" for UI clarity,
  - decision history is preserved in details.audit[].


META.EXCEPTIONS POLICY (audit only)
-----------------------------------
payload.meta.exceptions is treated as "audit hints" only and is projected into details.audit[].

Two shapes are supported:
1) Slot marker rows (must have day + shift_type)
   Examples:
   - ignore-slot markers (generation decisions about uncovered slots)
   - head_commitment_resolution markers (chosen head for a concrete slot)

2) Action rows (must NOT have day/shift_type)
   Examples:
   - publish_acceptance / force publish decisions with optional justification

Diagnostics must never use meta.exceptions to "fix" or "improve" computed metrics.


RANKINGS POLICY (UI)
-------------------
- Every doctor must be in EXACTLY ONE list:
    happy:   ui_stars >= 4
    unhappy: ui_stars <= 3
- Sorting:
    happy:   ui_stars DESC, then surname (last token of display_name),
             then display_name, then doctor_id
    unhappy: ui_stars ASC,  then surname (last token of display_name),
             then display_name, then doctor_id
- score in ranking rows is UI stars (float, backward compatible).
- reasons_codes are short, actionable codes (whitelisted).

Minimal payload input shape (example):
{
  "participant_doctor_ids": [101, 102],
  "assignments": [
    {"day": 1, "shift_type": "onsite", "doctor_id": 101},
    {"day": 1, "shift_type": "oncall", "doctor_id": 102}
  ],
  "meta": {"labels": [], "exceptions": [{"code":"coverage_ignored_slot","day":2,"shift_type":"onsite"}]},
  "inputs_snapshot": {
    "doctors": {
      "101": {"display_name":"Alice", "role":"specialist", "is_head":True, "is_active_at_snapshot":True}
    }
  }
}
"""


from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from backend.core import issues, scoring
from backend.core.constraint_builder import build_hard_model_for_diagnostics
from backend.core.fairness_expected import compute_expected_map_for_fairness
from backend.core.rest_window import is_sat_to_sun, rest_violation_kind
from backend.core.types import ProblemData
from backend.models.common_enums import DoctorRole, ShiftType
from backend.models.constants.diagnostics_reason_codes import (
    REASON_BALANCED_LOAD,
    REASON_FRIDAY_PENALTY,
    REASON_GOOD_REST,
    REASON_HARD_DOUBLE_SHIFT_SAME_DAY,
    REASON_OVERLOADED_TOTALS,
    REASON_PREFERENCES_MET,
    REASON_PREFERENCES_NOT_FULLY_MET,
    REASON_PREFERRED_DAYS_MISSED,
    REASON_REST_VIOLATIONS,
    REASON_WEEKDAY_AVOID_HIT,
    REASON_WEEKDAY_PREFERRED_MATCHED,
    REASON_WEEKDAY_PREFERRED_NOT_MATCHED,
)

# ----------------------------- issues codes (safe) -----------------------------


def _issue_code(name: str, fallback: str) -> str:
    """
    Safely get a string code from backend.core.issues.

    Why:
    - We want stable codes, but we also want this module to not crash if an
      attribute name changes in issues.py.
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

    Returns: ShiftType or None if unknown.
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
    """Best-effort int conversion. Returns None when value is missing or cannot be converted."""
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

    Returns: ignored_slots set[(day, ShiftType)]
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
      1) slot marker rows: have (day + shift_type) and represent a human decision about a
         concrete slot (e.g., ignore coverage for this slot, head commitment resolution for this slot),
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

            row = {
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

        row = {"kind": kind, "code": code_raw}
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

    Returns: (missing_count, missing_slots_list)
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
    DEPRECATED (kept for backward compatibility): Count days where required assignments are missing.

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
    - Ignore markers MUST NOT improve metrics. If a preferred slot was ignored during generation,
      it is still counted and can be missed.
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
) -> tuple[Dict[int, float], Dict[int, int], Dict[int, int]]:
    """
    Compute per-doctor preference fulfillment percent, preferred_days_missed,
    and preferred_days_requested (how many preferred days were declared).

    Returns: (pct_by_doctor, missed_by_doctor, requested_by_doctor)
    """
    days_set = set(int(x) for x in problem.days)

    pct_by_doctor: Dict[int, float] = {}
    missed_by_doctor: Dict[int, int] = {}
    requested_by_doctor: Dict[int, int] = {}

    for doc_id in sorted(problem.participant_doctor_ids):
        prefs = problem.preferences.get(doc_id)
        if prefs is None:
            pct_by_doctor[int(doc_id)] = 100.0
            missed_by_doctor[int(doc_id)] = 0
            requested_by_doctor[int(doc_id)] = 0
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
        requested_by_doctor[int(doc_id)] = int(total)

    return pct_by_doctor, missed_by_doctor, requested_by_doctor


# ----------------------------- rest rules (per-doctor stats) ---------------------


def _is_weekend_pair(problem: ProblemData, d: int, d_next: int) -> bool:
    """Weekend pair is only Sat -> Sun (same logic as objective_builder)."""
    wd = _weekday(problem, d)
    wd_next = _weekday(problem, d_next)
    return wd == 5 and wd_next == 6


def compute_rest_penalty_and_violations(*, problem: ProblemData, idx: _Index) -> tuple[int, int]:
    """Backward-compatible wrapper. Returns: (total_penalty, total_violations_count)"""
    total_penalty, total_violations, _viol_by_doc, _pen_by_doc, _rest_findings = _compute_rest_stats(
        problem=problem,
        idx=idx,
    )
    return int(total_penalty), int(total_violations)


def _compute_rest_stats(
    *,
    problem: ProblemData,
    idx: _Index,
) -> tuple[int, int, Dict[int, int], Dict[int, int], List[Dict[str, Any]]]:
    """
    Compute rest penalty and violations both globally and per-doctor.

    Returns:
    (total_penalty, total_violations, violations_by_doctor, penalty_by_doctor, rest_findings)
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
                        idx,
                        doctor_id=int(doc_id),
                        day=int(day1),
                        shift_type=ShiftType.onsite,
                    )
                    has_day1_oncall = _doctor_has(
                        idx,
                        doctor_id=int(doc_id),
                        day=int(day1),
                        shift_type=ShiftType.oncall,
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
                idx,
                doctor_id=doc_id,
                day=d_next,
                shift_type=ShiftType.onsite,
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
                idx,
                doctor_id=doc_id,
                day=d_next,
                shift_type=ShiftType.oncall,
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
                    idx,
                    doctor_id=doc_id,
                    day=d_next,
                    shift_type=ShiftType.oncall,
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
                    idx,
                    doctor_id=doc_id,
                    day=d_next,
                    shift_type=ShiftType.onsite,
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

    Returns: (total_penalty, penalty_by_doctor)
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

    Returns: (total_penalty, fairness_index, penalty_by_doctor)
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

    # Variant B (final):
    # - fairness should be feasibility-aware (uses allowed_slots filtered by unavailable days),
    # - ignore markers MUST NOT improve metrics, so diagnostics fairness treats the full month as required.
    model = build_hard_model_for_diagnostics(problem)

    expected_map = compute_expected_map_for_fairness(
        model=model,
        problem=problem,
        group_to_doctors=group_to_doctors,
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
    """Backward-compatible wrapper (NET = penalty + bonus)."""
    total_pen, total_bonus, _pen_by_doc, _bonus_by_doc = _compute_weekday_patterns_components_per_doctor(
        problem=problem, idx=idx
    )
    return int(total_pen + total_bonus)


def _compute_weekday_patterns_components_per_doctor(
    *,
    problem: ProblemData,
    idx: _Index,
) -> tuple[int, int, Dict[int, int], Dict[int, int]]:
    """
    Weekday pattern terms split into two components (NO mixed signs in one field):

    - weekday_patterns_penalty: >= 0 (avoid weekdays)
    - weekday_patterns_bonus: <= 0 (preferred weekdays; solver convention: negative)

    Returns:
        (total_penalty, total_bonus, penalty_by_doctor, bonus_by_doctor)
    """
    total_penalty = 0  # >= 0
    total_bonus = 0  # <= 0

    penalty_by_doctor: Dict[int, int] = {int(d): 0 for d in problem.participant_doctor_ids}
    bonus_by_doctor: Dict[int, int] = {int(d): 0 for d in problem.participant_doctor_ids}

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

        p_pen = 0  # >= 0
        p_bonus = 0  # <= 0

        for d_raw in problem.days:
            d = int(d_raw)
            wd = _weekday(problem, d)

            # Preferred weekdays -> BONUS (negative)
            if wd in pref_ons and _doctor_has(idx, doctor_id=doc_id, day=d, shift_type=ShiftType.onsite):
                p_bonus -= preferred_w
            if wd in pref_onc and _doctor_has(idx, doctor_id=doc_id, day=d, shift_type=ShiftType.oncall):
                p_bonus -= preferred_w

            # Avoid weekdays -> PENALTY (positive)
            if wd in avoid_ons and _doctor_has(idx, doctor_id=doc_id, day=d, shift_type=ShiftType.onsite):
                p_pen += avoid_w
            if wd in avoid_onc and _doctor_has(idx, doctor_id=doc_id, day=d, shift_type=ShiftType.oncall):
                p_pen += avoid_w

        penalty_by_doctor[int(doc_id)] = int(p_pen)
        bonus_by_doctor[int(doc_id)] = int(p_bonus)

        total_penalty += int(p_pen)
        total_bonus += int(p_bonus)

    return int(total_penalty), int(total_bonus), penalty_by_doctor, bonus_by_doctor


# ----------------------------- preferred partners (per-doctor bonus) -------------


def compute_preferred_partners_penalty(*, problem: ProblemData, idx: _Index) -> int:
    """Backward-compatible wrapper (total penalty)."""
    total_penalty, _bonus_by_doctor = _compute_preferred_partners_bonus_by_doctor(problem=problem, idx=idx)
    return int(total_penalty)


def _compute_preferred_partners_bonus_by_doctor(
    *,
    problem: ProblemData,
    idx: _Index,
) -> tuple[int, Dict[int, float]]:
    """
    Preferred partners bonus:
    - for each unique pair (doc_id < partner_id)
    - for each day: if both work any shift -> bonus (negative penalty)

    Per-doctor allocation for rankings:
    - The solver objective counts bonus per pair-day once.
    - For per-doctor "score", we split the bonus equally: half to each doctor.

    Returns: (total_penalty, bonus_by_doctor) where bonus values are floats (negative numbers).
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


def _compute_friday_free_weekend_penalty_per_doctor(
    *,
    problem: ProblemData,
    idx: _Index,
) -> tuple[int, Dict[int, int]]:
    """
    Avoid Friday if the following weekend is fully off:
    - Friday (weekday==4)
    - Saturday and Sunday must exist in this month: (fri+1, fri+2) and be Sat/Sun
    - penalty if doctor works on Friday AND does NOT work on Sat AND does NOT work on Sun

    Returns: (total_penalty, penalty_by_doctor)
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
                idx,
                doctor_id=doc_id,
                day=sun,
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
        problem=problem,
        idx=idx,
        ignored_slots=ignored_slots,
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

    - Ignore markers MUST NOT improve metrics. If a preferred slot was ignored during generation,
      it is still counted and can be missed.

    Returns: (total_penalty, penalty_by_doctor)
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

        base_miss_w = int(scoring.PREF_DAY_MISS_BASE_WEIGHT)
        miss_w = int(
            scoring.effective_weight(
                base_weight=int(base_miss_w),
                category="preferred_days",
                is_head=is_head,
                role=role,
            )
        )
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

    Returns: (findings, double_shift_days_by_doctor)
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


# ----------------------------- UI quality (stars + reasons) ---------------------


def _clamp_int(v: int, lo: int, hi: int) -> int:
    """Clamp int into [lo..hi]."""
    return max(int(lo), min(int(v), int(hi)))


def _clamp_float(v: float, lo: float, hi: float) -> float:
    """Clamp float into [lo..hi]."""
    return max(float(lo), min(float(v), float(hi)))


def _badness_to_stars_1_5(badness: float) -> int:
    """
    Map badness 0..1 to stars 5..1.
    0.0 -> 5, 1.0 -> 1.
    """
    b = _clamp_float(float(badness), 0.0, 1.0)
    # 5 - round(4*b) gives: 0->5, 0.25->4, 0.5->3, 0.75->2, 1->1
    return _clamp_int(int(5 - round(4.0 * b)), 1, 5)


def _ui_quality_for_doctor(
    *,
    doctor_id: int,
    rest_violations: int,
    preferred_days_missed: int,
    preferred_days_requested: int,
    preference_fulfillment_pct: float,
    double_shift_days: int,
    # per-doctor penalties/bonuses from components (solver-like, but used only as signals)
    rest_pen: int,
    pref_days_pen: int,
    totals_pen: int,
    fairness_pen: int,
    weekday_pen: int,  # >= 0 (avoid weekdays hit)
    weekday_bonus: int,  # <= 0 (preferred weekdays matched; solver convention: negative)
    friday_pen: int,
    partners_bonus: float,  # negative means "good" (bonus)
    # applicability hints (computed in compute_quality from preferences/month calendar)
    weekday_preferred_declared: bool = False,
    weekday_avoid_declared: bool = False,
    preferred_partners_declared: bool = False,
    totals_prefs_declared: bool = False,
    friday_rule_applicable: bool = False,
) -> tuple[int, list[str], dict[str, Any]]:
    """
    UI quality (human-facing), stable and deterministic.

    Output:
    - ui_stars: int 1..5
    - ui_reasons_codes: list[str] max 3 (stable codes)
    - ui_components: dict with per-category applicable/badness/stars + debug inputs
    """

    categories: Dict[str, Dict[str, Any]] = {}

    # "Has any work / any signal at all?"
    assigned_any = (
        int(rest_violations) > 0
        or int(rest_pen) != 0
        or int(pref_days_pen) != 0
        or int(totals_pen) != 0
        or int(fairness_pen) != 0
        or int(weekday_pen) != 0
        or int(friday_pen) != 0
    )

    # -----------------------------
    # REST (discrete, strong)
    # -----------------------------
    rv = max(0, int(rest_violations))
    rest_applicable = bool(assigned_any)
    if rv <= 0:
        rest_badness = 0.0
    elif rv == 1:
        rest_badness = 0.60
    elif rv == 2:
        rest_badness = 0.85
    else:
        rest_badness = 1.00

    categories["rest"] = {
        "applicable": bool(rest_applicable),
        "badness": float(rest_badness),
        "stars": int(_badness_to_stars_1_5(rest_badness)) if rest_applicable else None,
    }

    # -----------------------------
    # PREFERRED DAYS (opportunities-based)
    # -----------------------------
    req = max(0, int(preferred_days_requested))
    miss = max(0, int(preferred_days_missed))
    pref_applicable = req > 0

    if not pref_applicable:
        pref_badness = 0.0
    else:
        miss_rate = float(miss) / float(max(1, req))
        # T_pref = 0.20 -> 20% misses is already "very bad"
        pref_badness = _clamp_float(miss_rate / 0.20, 0.0, 1.0)

    categories["preferred_days"] = {
        "applicable": bool(pref_applicable),
        "badness": float(pref_badness),
        "stars": int(_badness_to_stars_1_5(pref_badness)) if pref_applicable else None,
        "requested": int(req),
        "missed": int(miss),
    }

    # -----------------------------
    # FAIRNESS (penalty-based for now)
    # -----------------------------
    fp = max(0, int(fairness_pen))
    fairness_applicable = bool(assigned_any)
    fairness_badness = _clamp_float(float(fp) / 80.0, 0.0, 1.0) if fairness_applicable else 0.0
    categories["fairness"] = {
        "applicable": bool(fairness_applicable),
        "badness": float(fairness_badness),
        "stars": int(_badness_to_stars_1_5(fairness_badness)) if fairness_applicable else None,
    }

    # -----------------------------
    # TOTALS (only if declared in preferences)
    # -----------------------------
    tp = max(0, int(totals_pen))
    totals_applicable = bool(totals_prefs_declared)

    if not totals_applicable:
        totals_badness = 0.0
        totals_stars = None
    else:
        totals_badness = _clamp_float(float(tp) / 80.0, 0.0, 1.0)
        totals_stars = int(_badness_to_stars_1_5(totals_badness))

    categories["totals"] = {
        "applicable": bool(totals_applicable),
        "badness": float(totals_badness),
        "stars": totals_stars,
    }

    # -----------------------------
    # WEEKDAY PATTERNS (only if declared)
    # - avoid: penalty >= 0
    # - preferred: bonus <= 0 (negative means "matched")
    # -----------------------------
    wp = max(0, int(weekday_pen))  # avoid penalty (>=0)
    wb = int(weekday_bonus)  # preferred bonus (<=0)

    weekday_applicable = bool(weekday_preferred_declared) or bool(weekday_avoid_declared)

    # Badness is driven mainly by avoid-penalty.
    weekday_badness = _clamp_float(float(wp) / 20.0, 0.0, 1.0) if weekday_applicable else 0.0

    categories["weekday_patterns"] = {
        "applicable": bool(weekday_applicable),
        "badness": float(weekday_badness),
        "stars": int(_badness_to_stars_1_5(weekday_badness)) if weekday_applicable else None,
        "avoid_penalty": int(wp),
        "preferred_bonus": int(wb),
        "preferred_declared": bool(weekday_preferred_declared),
        "avoid_declared": bool(weekday_avoid_declared),
    }

    # -----------------------------
    # FRIDAY RULE (only if month pattern exists)
    # -----------------------------
    frp = max(0, int(friday_pen))
    friday_applicable = bool(friday_rule_applicable)
    friday_badness = _clamp_float(float(frp) / 20.0, 0.0, 1.0) if friday_applicable else 0.0
    categories["friday_free_weekend"] = {
        "applicable": bool(friday_applicable),
        "badness": float(friday_badness),
        "stars": int(_badness_to_stars_1_5(friday_badness)) if friday_applicable else None,
    }

    # -----------------------------
    # PARTNERS (only if declared)
    # -----------------------------
    pb = float(partners_bonus) if partners_bonus is not None else 0.0
    partners_applicable = bool(preferred_partners_declared)
    categories["preferred_partners"] = {
        "applicable": bool(partners_applicable),
        "badness": 0.0,
        "stars": (5 if partners_applicable and pb <= -1.0 else 4) if partners_applicable else None,
    }

    # -----------------------------
    # Weighted average over ONLY applicable categories
    # -----------------------------
    weights = {
        "rest": 0.35,
        "preferred_days": 0.35,
        "fairness": 0.10,
        "totals": 0.10,
        "weekday_patterns": 0.05,
        "friday_free_weekend": 0.03,
        "preferred_partners": 0.02,
    }

    applicable_items: List[tuple[str, float, int]] = []
    for k, w in weights.items():
        c = categories.get(k, {})
        if bool(c.get("applicable")) and c.get("stars") is not None:
            applicable_items.append((k, float(w), int(c["stars"])))

    if not applicable_items:
        base_stars = 5
    else:
        w_sum = sum(w for _, w, _ in applicable_items)
        base_stars_f = 0.0
        for _, w, s in applicable_items:
            base_stars_f += (float(w) / float(max(1e-9, w_sum))) * float(s)
        base_stars = int(round(base_stars_f))

    # Hard pain adjustments after aggregation
    stars = int(base_stars)

    ds = max(0, int(double_shift_days))
    if ds > 0:
        stars -= 2

    if pb <= -4.0:
        stars += 1

    stars = _clamp_int(int(stars), 1, 5)

    # -----------------------------
    # Reasons (max 5, stable)
    # -----------------------------
    reasons: List[str] = []

    # 1) Hard signals first
    if ds > 0:
        reasons.append(REASON_HARD_DOUBLE_SHIFT_SAME_DAY)
    if rv > 0:
        reasons.append(REASON_REST_VIOLATIONS)

    # 2) Dominant soft contributor (by badness * weight)
    soft_candidates: List[tuple[float, str]] = []

    if pref_applicable and miss > 0:
        soft_candidates.append((float(pref_badness) * float(weights["preferred_days"]), REASON_PREFERRED_DAYS_MISSED))

    if totals_applicable and tp > 0:
        soft_candidates.append((float(totals_badness) * float(weights["totals"]), REASON_OVERLOADED_TOTALS))

        # Weekday avoid hit (negative signal)
    if weekday_avoid_declared and int(wp) > 0:
        soft_candidates.append((float(weekday_badness) * float(weights["weekday_patterns"]), REASON_WEEKDAY_AVOID_HIT))

    # Preferred weekdays declared but not matched (negative signal)
    if weekday_preferred_declared and int(weekday_bonus) == 0:
        soft_candidates.append((0.01, REASON_WEEKDAY_PREFERRED_NOT_MATCHED))

    if friday_applicable and frp > 0:
        soft_candidates.append((float(friday_badness) * float(weights["friday_free_weekend"]), REASON_FRIDAY_PENALTY))

    soft_candidates.sort(key=lambda x: float(x[0]), reverse=True)
    if soft_candidates:
        reasons.append(str(soft_candidates[0][1]))

    # 3) Positive fillers only if still empty (don’t spam)
    if not reasons:
        if rv == 0:
            reasons.append(REASON_GOOD_REST)
        if pref_applicable and miss == 0:
            reasons.append(REASON_PREFERENCES_MET)
        if fp == 0 and tp == 0:
            reasons.append(REASON_BALANCED_LOAD)

    # de-dup + trim
    out: List[str] = []
    seen: Set[str] = set()
    for r in reasons:
        if r in seen:
            continue
        seen.add(str(r))
        out.append(str(r))
        if len(out) >= 5:
            break

        # Keep the same naming as the public API "solver_components_by_doc".
    # This dict is still useful internally (tests/debug), even if the API now exposes it top-level.
    solver_components_by_doc = {
        "rest_penalty": int(rest_pen),
        "preferred_days_penalty": int(pref_days_pen),
        "totals_penalty": int(totals_pen),
        "fairness_penalty": int(fairness_pen),
        "weekday_patterns_penalty": int(weekday_pen),
        "weekday_patterns_bonus": int(weekday_bonus),
        "friday_free_weekend_penalty": int(friday_pen),
        "preferred_partners_bonus": float(pb),
    }

    # Minimal internal breakdown:
    # - we keep ONLY what compute_quality needs to lift into per_doctor top-level fields
    # - we intentionally do NOT include duplicates like doctor_id/stars/inputs/etc.
    ui_components = {
        "categories": dict(categories),
        "solver_components_by_doc": dict(solver_components_by_doc),
    }

    return int(stars), list(out), dict(ui_components)


# ----------------------------- rankings -----------------------------------------
def _safe_float(v: Any) -> float:
    try:
        return float(v)
    except Exception:
        return 0.0


def _pick_dominant_soft_reason(
    *,
    doc_id: int,
    # Per-doctor penalties (>=0). These are already computed by diagnostics.
    pref_days_pen_by_doc: Dict[int, int],
    totals_pen_by_doc: Dict[int, int],
    fairness_pen_by_doc: Dict[int, int],
    weekday_pen_by_doc: Dict[int, int],
    fri_pen_by_doc: Dict[int, int],
    # Used only as a broad fallback if we have no specific reason.
    preference_fulfillment_pct: float,
) -> List[str]:
    """
    Choose at most ONE "dominant" soft reason (deterministic).

    Policy:
    - Consider only positive penalties (bonuses are ignored here).
    - Pick the largest component.
    - Emit it only if it dominates enough (>= 40% of positive sum).
    - Otherwise: allow broad fallback 'preferences_not_fully_met' only when pct < 100.
    """
    # Positive penalties only (defensive)
    pref_days = max(0, int(pref_days_pen_by_doc.get(int(doc_id), 0)))
    totals = max(0, int(totals_pen_by_doc.get(int(doc_id), 0)))
    fairness = max(0, int(fairness_pen_by_doc.get(int(doc_id), 0)))
    weekday = max(0, int(weekday_pen_by_doc.get(int(doc_id), 0)))
    friday = max(0, int(fri_pen_by_doc.get(int(doc_id), 0)))

    positive_sum = int(pref_days + totals + fairness + weekday + friday)
    if positive_sum <= 0:
        # No soft penalties -> no soft reasons.
        return []

    # Candidate mapping: component -> reason code
    # NOTE: fairness is real, but we do not emit a separate fairness reason right now.
    candidates: List[tuple[str, int]] = [
        (REASON_PREFERRED_DAYS_MISSED, pref_days),
        (REASON_OVERLOADED_TOTALS, totals),
        (REASON_WEEKDAY_AVOID_HIT, weekday),  # weekday_pen is "avoid hit" (>=0)
        (REASON_FRIDAY_PENALTY, friday),
    ]

    # Deterministic: sort by value desc, then code asc
    candidates_sorted = sorted(candidates, key=lambda x: (-int(x[1]), str(x[0])))

    top_code, top_value = candidates_sorted[0]
    if int(top_value) <= 0:
        # No meaningful mapped component (could be fairness-only).
        if _safe_float(preference_fulfillment_pct) < 100.0:
            return [REASON_PREFERENCES_NOT_FULLY_MET]
        return []

    share = float(top_value) / float(positive_sum) if positive_sum > 0 else 0.0

    # Emit only if dominant enough (>=40% of positive penalty sum).
    if float(share) >= 0.40:
        return [str(top_code)]

    # Not dominant enough -> use broad fallback ONLY if pct < 100, otherwise emit nothing.
    if _safe_float(preference_fulfillment_pct) < 100.0:
        return [REASON_PREFERENCES_NOT_FULLY_MET]

    return []


def ui_reasons_codes_unhappy(
    *,
    row: Dict[str, Any],
    double_shift_days_by_doctor: Dict[int, int],
    pref_days_pen_by_doc: Dict[int, int],
    totals_pen_by_doc: Dict[int, int],
    fairness_pen_by_doc: Dict[int, int],
    weekday_pen_by_doc: Dict[int, int],
    fri_pen_by_doc: Dict[int, int],
) -> List[str]:
    """
    UI-friendly reason codes for top_unhappy ranking.

    Output rules:
    - Max 3 codes.
    - No duplicates.
    - Every code must be in ALL_REASON_CODES (validated in tests).
    """
    doc_id = int(row.get("doctor_id", 0))
    reasons: List[str] = []

    # Hard-ish / very actionable signals first
    if int(row.get("rest_violations", 0)) > 0:
        reasons.append(REASON_REST_VIOLATIONS)

    if int(double_shift_days_by_doctor.get(int(doc_id), 0)) > 0:
        reasons.append(REASON_HARD_DOUBLE_SHIFT_SAME_DAY)

    # If we have a concrete "missed preferred day", prefer it over any broad fallback.
    preferred_missed = int(row.get("preferred_days_missed", 0))
    if preferred_missed > 0:
        reasons.append(REASON_PREFERRED_DAYS_MISSED)

    # Soft: pick ONE dominant reason (or fallback broad)
    pref_pct = _safe_float(row.get("preference_fulfillment_pct", 100.0))
    reasons.extend(
        _pick_dominant_soft_reason(
            doc_id=doc_id,
            pref_days_pen_by_doc=pref_days_pen_by_doc,
            totals_pen_by_doc=totals_pen_by_doc,
            fairness_pen_by_doc=fairness_pen_by_doc,
            weekday_pen_by_doc=weekday_pen_by_doc,
            fri_pen_by_doc=fri_pen_by_doc,
            preference_fulfillment_pct=pref_pct,
        )
    )

    # If preferred days are missed, NEVER show the generic fallback too (same meaning -> bad UX).
    if preferred_missed > 0:
        reasons = [r for r in reasons if r != REASON_PREFERENCES_NOT_FULLY_MET]

    # De-dup, keep order, max 3
    out: List[str] = []
    seen: Set[str] = set()
    for r in reasons:
        rr = str(r)
        if rr in seen:
            continue
        seen.add(rr)
        out.append(rr)
        if len(out) >= 3:
            break

    return out


def ui_reasons_codes_happy(
    *,
    row: Dict[str, Any],
    totals_pen_by_doc: Dict[int, int],
    fairness_pen_by_doc: Dict[int, int],
) -> List[str]:
    """
    UI-friendly reason codes for top_happy ranking.

    Output rules:
    - Max 3 codes.
    - No duplicates.
    - Every code must be in ALL_REASON_CODES (validated in tests).
    """
    doc_id = int(row.get("doctor_id", 0))
    reasons: List[str] = []

    if int(row.get("rest_violations", 0)) == 0:
        reasons.append(REASON_GOOD_REST)

    pref_pct = _safe_float(row.get("preference_fulfillment_pct", 100.0))
    if float(pref_pct) >= float(scoring.happy_preferences_met_threshold_pct()):
        reasons.append(REASON_PREFERENCES_MET)

    # Balanced load: both totals and fairness penalties are very low.
    # (We choose strict MVP rule: exactly zero penalties.)
    totals_pen = max(0, int(totals_pen_by_doc.get(int(doc_id), 0)))
    fairness_pen = max(0, int(fairness_pen_by_doc.get(int(doc_id), 0)))
    if totals_pen == 0 and fairness_pen == 0:
        reasons.append(REASON_BALANCED_LOAD)

    # De-dup, keep order
    out: List[str] = []
    seen: Set[str] = set()
    for r in reasons:
        if r in seen:
            continue
        seen.add(str(r))
        out.append(str(r))
        if len(out) >= 3:
            break

    return out


RANKING_REASONS_LIMIT = 5


def _build_rankings(
    *,
    per_doctor_rows: List[Dict[str, Any]],
    double_shift_days_by_doctor: Dict[int, int],
    pref_days_pen_by_doc: Dict[int, int],
    totals_pen_by_doc: Dict[int, int],
    fairness_pen_by_doc: Dict[int, int],
    weekday_pen_by_doc: Dict[int, int],
    weekday_bonus_by_doc: Dict[int, int],
    weekday_preferred_declared_by_doc: Dict[int, bool],
    weekday_avoid_declared_by_doc: Dict[int, bool],
    fri_pen_by_doc: Dict[int, int],
) -> Dict[str, Any]:
    """
    Build rankings for UI.

    Rules:
    - Every doctor must be in EXACTLY ONE list:
        happy:   ui_stars >= 4
        unhappy: ui_stars <= 3
    - Sorting (human-friendly):
        happy:   ui_stars DESC, then surname (last token), then display_name, then doctor_id
        unhappy: ui_stars ASC,  then surname (last token), then display_name, then doctor_id
    - score in ranking rows is UI stars (float, backward compatible).
    - reasons_codes are short, actionable, whitelisted codes.
    - Prefer per_doctor.ui_reasons_codes when present (already curated), otherwise fallback to heuristics.

    NOTE:
    - weekday_bonus_by_doc follows solver convention: negative numbers (bonus).
      We keep it available for future heuristics, but we do not force extra reasons from it here.
    """

    from backend.models.constants.diagnostics_reason_codes import (
        ALL_REASON_CODES,
        REASON_BALANCED_LOAD,
        REASON_FRIDAY_PENALTY,
        REASON_GOOD_REST,
        REASON_HARD_DOUBLE_SHIFT_SAME_DAY,
        REASON_OVERLOADED_TOTALS,
        REASON_PREFERRED_DAYS_MISSED,
        REASON_REST_VIOLATIONS,
        REASON_WEEKDAY_AVOID_HIT,
        REASON_WEEKDAY_PREFERRED_NOT_MATCHED,
    )

    HAPPY_MIN_STARS = 4

    def _safe_str(v: Any) -> str:
        try:
            s = str(v) if v is not None else ""
        except Exception:
            s = ""
        return s.strip()

    def _last_name_key(display_name: Any) -> str:
        """
        Sort key: last token as "surname" (human-ish).
        Falls back to whole display_name.
        """
        dn = _safe_str(display_name)
        if not dn:
            return ""
        parts = [p for p in dn.split(" ") if p]
        if not parts:
            return dn.lower()
        return str(parts[-1]).lower()

    def _dedup_trim(reasons: List[str], limit: int = 5) -> List[str]:
        out: List[str] = []
        seen: Set[str] = set()
        for r in reasons:
            rr = _safe_str(r)
            if not rr:
                continue
            if rr not in ALL_REASON_CODES:
                continue
            if rr in seen:
                continue
            seen.add(rr)
            out.append(rr)
            if len(out) >= int(limit):
                break
        return out

    def _take_ui_reasons_if_any(row: Dict[str, Any]) -> List[str]:
        """
        Prefer UI reasons computed per doctor (already curated, max 3, and usually more UX-friendly).
        Fall back to ranking heuristics if missing/empty.
        """
        v = row.get("ui_reasons_codes", [])
        if not isinstance(v, list):
            return []
        out: List[str] = []
        for x in v:
            sx = _safe_str(x)
            if not sx:
                continue
            out.append(sx)
        return _dedup_trim(out, limit=RANKING_REASONS_LIMIT)

    def _clamp_stars(v: Any) -> int:
        try:
            s = int(v)
        except Exception:
            s = 1
        return max(1, min(5, s))

    # ------------------------------
    # Normalize rows into internal items
    # ------------------------------
    items: List[Dict[str, Any]] = []
    for row in per_doctor_rows:
        doc_id = int(row.get("doctor_id", 0))
        ui_stars = _clamp_stars(row.get("ui_stars", 0))
        display_name = _safe_str(row.get("display_name", ""))

        items.append(
            {
                "doctor_id": doc_id,
                "ui_stars": ui_stars,
                "display_name": display_name,
                "_row": row,
            }
        )

    # ------------------------------
    # Partition: each doctor goes to exactly one list
    # ------------------------------
    happy_items = [it for it in items if int(it["ui_stars"]) >= HAPPY_MIN_STARS]
    unhappy_items = [it for it in items if int(it["ui_stars"]) < HAPPY_MIN_STARS]

    # ------------------------------
    # Sort (IMPORTANT: keep full lists, no top_n slicing)
    # ------------------------------
    happy_items.sort(
        key=lambda it: (
            -int(it["ui_stars"]),
            _last_name_key(it.get("display_name", "")),
            _safe_str(it.get("display_name", "")).lower(),
            int(it["doctor_id"]),
        )
    )
    unhappy_items.sort(
        key=lambda it: (
            int(it["ui_stars"]),
            _last_name_key(it.get("display_name", "")),
            _safe_str(it.get("display_name", "")).lower(),
            int(it["doctor_id"]),
        )
    )

    # ------------------------------
    # Reasons (ranking-specific, human-friendly)
    # - First: use per-doctor ui_reasons_codes if present.
    # - Else: fallback heuristics (deterministic, max 3).
    # ------------------------------
    def _reasons_for_unhappy(row: Dict[str, Any]) -> List[str]:
        ui = _take_ui_reasons_if_any(row)
        if ui:
            return ui

        doc_id = int(row.get("doctor_id", 0))

        reasons: List[str] = []

        # 1) Hard double shift
        if int(double_shift_days_by_doctor.get(doc_id, 0)) > 0:
            reasons.append(REASON_HARD_DOUBLE_SHIFT_SAME_DAY)

        # 2) Rest violations
        if int(row.get("rest_violations", 0)) > 0:
            reasons.append(REASON_REST_VIOLATIONS)

        # 3) Preferred days missed
        if int(row.get("preferred_days_missed", 0)) > 0:
            reasons.append(REASON_PREFERRED_DAYS_MISSED)

        # 4) Pick ONE dominant extra signal (avoid spam)
        candidates: List[tuple[int, str]] = []

        tp = max(0, int(totals_pen_by_doc.get(doc_id, 0)))
        if tp > 0:
            candidates.append((tp, REASON_OVERLOADED_TOTALS))

        # Weekday patterns (solver-consistent):
        # - penalty (avoid hit) is non-negative
        # - bonus (preferred matched) is non-positive (negative means "good")
        wp = max(0, int(weekday_pen_by_doc.get(doc_id, 0)))
        wb = int(weekday_bonus_by_doc.get(doc_id, 0))  # <= 0, negative means matched preferred weekdays

        if weekday_avoid_declared_by_doc.get(doc_id, False) and wp > 0:
            candidates.append((wp, REASON_WEEKDAY_AVOID_HIT))

        # "preferred" is a bit special: we treat it as a reason even when penalty is 0
        # because it explains WHY the doctor is happy/unhappy in terms of weekday prefs.
        if weekday_preferred_declared_by_doc.get(doc_id, False) and wb < 0:
            reasons.append(REASON_WEEKDAY_PREFERRED_MATCHED)

        if weekday_preferred_declared_by_doc.get(doc_id, False) and wb == 0:
            reasons.append(REASON_WEEKDAY_PREFERRED_NOT_MATCHED)

        # Optional UX negative: preferred declared but no bonus matched.
        # We can only infer this from the row (ui_reasons_codes) in normal flow.
        # In fallback heuristics (tests), we use weekday_bonus_by_doc.
        wb = int(weekday_bonus_by_doc.get(doc_id, 0))
        if wb == 0:
            # Add as a weak candidate; if something else dominates, it may be skipped.
            candidates.append((1, REASON_WEEKDAY_PREFERRED_NOT_MATCHED))

        fp = max(0, int(fri_pen_by_doc.get(doc_id, 0)))
        if fp > 0:
            candidates.append((fp, REASON_FRIDAY_PENALTY))

        candidates.sort(key=lambda x: int(x[0]), reverse=True)
        if candidates:
            reasons.append(str(candidates[0][1]))

        return _dedup_trim(reasons, limit=RANKING_REASONS_LIMIT)

    def _reasons_for_happy(row: Dict[str, Any]) -> List[str]:
        ui = _take_ui_reasons_if_any(row)
        if ui:
            return ui

        doc_id = int(row.get("doctor_id", 0))
        reasons: List[str] = []

        # "Happy" list can still include a positive explainer
        if int(row.get("rest_violations", 0)) == 0:
            reasons.append(REASON_GOOD_REST)

        tp = max(0, int(totals_pen_by_doc.get(doc_id, 0)))
        fp = max(0, int(fairness_pen_by_doc.get(doc_id, 0)))
        if tp == 0 and fp == 0:
            reasons.append(REASON_BALANCED_LOAD)

        # Keep weekday bonus available for future (solver convention: negative)
        _ = int(weekday_bonus_by_doc.get(doc_id, 0))

        return _dedup_trim(reasons, limit=RANKING_REASONS_LIMIT)

    # ------------------------------
    # Emit DTO shape
    # score = ui_stars (float for schema compatibility)
    # NOTE: output keys are stable: happy / unhappy (full lists, sorted)
    # ------------------------------
    happy: List[Dict[str, Any]] = []
    for it in happy_items:
        row = dict(it["_row"])
        happy.append(
            {
                "doctor_id": int(it["doctor_id"]),
                "display_name": _safe_str(it.get("display_name", "")),
                "score": float(it["ui_stars"]),
                "reasons_codes": _reasons_for_happy(row),
            }
        )

    unhappy: List[Dict[str, Any]] = []
    for it in unhappy_items:
        row = dict(it["_row"])
        unhappy.append(
            {
                "doctor_id": int(it["doctor_id"]),
                "display_name": _safe_str(it.get("display_name", "")),
                "score": float(it["ui_stars"]),
                "reasons_codes": _reasons_for_unhappy(row),
            }
        )

    return {"happy": happy, "unhappy": unhappy}


# ----------------------------- helpers (UI applicability) -----------------------------


def _friday_rule_applicable(*, problem: ProblemData) -> bool:
    """
    Friday rule is applicable only if this month contains at least one Friday
    that is immediately followed by Saturday and Sunday that also exist in the month.

    This is month-level (same for all doctors).
    """
    days_set = set(int(d) for d in problem.days)

    for d in sorted(days_set):
        if _weekday(problem, int(d)) != 4:  # 4 = Friday
            continue

        sat = int(d) + 1
        sun = int(d) + 2

        if sat not in days_set or sun not in days_set:
            continue

        # Extra safety: ensure they are really Sat/Sun
        if _weekday(problem, sat) == 5 and _weekday(problem, sun) == 6:
            return True

    return False


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

    # Month-level applicability flag for Friday rule (same for all doctors)
    friday_rule_applicable = _friday_rule_applicable(problem=problem)

    # Coverage (final semantics: per slot)
    coverage_missing_required_slots, missing_slots = compute_coverage_missing_required_slots(
        problem=problem,
        idx=idx,
        ignored_slots=ignored_slots,
    )

    # Backward compatibility field (deprecated KPI)
    understaffed_days = compute_understaffed_days(problem=problem, idx=idx, ignored_slots=ignored_slots)

    # Global preference fulfillment
    pref_pct = compute_preference_fulfillment_pct(problem=problem, idx=idx, ignored_slots=ignored_slots)

    # Rest (global + per doctor)
    rest_pen, rest_viol, rest_viol_by_doc, rest_pen_by_doc, rest_findings = _compute_rest_stats(
        problem=problem,
        idx=idx,
    )

    # Preferred concrete days (global + per doctor)
    pref_days_pen, pref_days_pen_by_doc = _compute_preferred_days_penalty_per_doctor(
        problem=problem,
        idx=idx,
        ignored_slots=ignored_slots,
    )

    # Totals (global + per doctor)
    totals_pen, totals_pen_by_doc = _compute_totals_penalty_per_doctor(problem=problem, idx=idx)

    # Fairness (global + per doctor + index)
    fairness_pen, fairness_index, fairness_pen_by_doc = _compute_fairness_stats(problem=problem, idx=idx)

    # Weekday patterns (global + per doctor)
    weekday_pen, weekday_bonus, weekday_pen_by_doc, weekday_bonus_by_doc = (
        _compute_weekday_patterns_components_per_doctor(
            problem=problem,
            idx=idx,
        )
    )

    # Preferred partners (global + per doctor bonus share)
    partners_pen, partners_bonus_by_doc = _compute_preferred_partners_bonus_by_doctor(problem=problem, idx=idx)

    # Friday if weekend off (global + per doctor)
    fri_pen, fri_pen_by_doc = _compute_friday_free_weekend_penalty_per_doctor(problem=problem, idx=idx)

    # Total penalty (legacy, still useful for debug)
    # IMPORTANT: keep solver convention:
    # - penalties are positive
    # - bonuses are negative (reduce the total)
    penalty_total = int(
        rest_pen + pref_days_pen + totals_pen + fairness_pen + weekday_pen + weekday_bonus + partners_pen + fri_pen
    )

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

    pref_pct_by_doc, pref_missed_by_doc, pref_requested_by_doc = _compute_preference_stats_per_doctor(
        problem=problem,
        idx=idx,
        ignored_slots=ignored_slots,
    )

    per_doctor: List[Dict[str, Any]] = []
    for doc_id in sorted(problem.participant_doctor_ids):
        doc_id_i = int(doc_id)

        # ------------------------------
        # UI applicability flags (based on declared preferences)
        # ------------------------------
        prefs = problem.preferences.get(doc_id_i)

        weekday_preferred_declared = False
        weekday_avoid_declared = False
        preferred_partners_declared = False
        totals_prefs_declared = False

        if prefs is not None:
            # Weekday patterns: split declaration into two flags
            weekday_preferred_declared = bool(prefs.preferred_onsite_weekdays or prefs.preferred_oncall_weekdays)
            weekday_avoid_declared = bool(prefs.avoid_onsite_weekdays or prefs.avoid_oncall_weekdays)

            preferred_partners_declared = bool(prefs.preferred_partners)

            # NEW: totals preferences declared?
            # We treat totals as "declared" if ANY totals-related field exists and is not None.
            totals_fields = [
                "target_onsite_total",
                "target_oncall_total",
                "min_onsite_total",
                "min_oncall_total",
                "max_onsite_total",
                "max_oncall_total",
                "desired_onsite_total",
                "desired_oncall_total",
            ]
            totals_prefs_declared = any(getattr(prefs, f, None) is not None for f in totals_fields)

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
        }

        # ------------------------------
        # UI quality (stars + reasons + structured categories)
        # ------------------------------
        ui_stars, ui_reasons, ui_components = _ui_quality_for_doctor(
            doctor_id=int(doc_id_i),
            rest_violations=int(rest_viol_by_doc.get(doc_id_i, 0)),
            preferred_days_missed=int(pref_missed_by_doc.get(doc_id_i, 0)),
            preferred_days_requested=int(pref_requested_by_doc.get(doc_id_i, 0)),
            preference_fulfillment_pct=float(pref_pct_by_doc.get(doc_id_i, 100.0)),
            double_shift_days=int(double_shift_days_by_doc.get(doc_id_i, 0)),
            rest_pen=int(rest_pen_by_doc.get(doc_id_i, 0)),
            pref_days_pen=int(pref_days_pen_by_doc.get(doc_id_i, 0)),
            totals_pen=int(totals_pen_by_doc.get(doc_id_i, 0)),
            fairness_pen=int(fairness_pen_by_doc.get(doc_id_i, 0)),
            weekday_pen=int(weekday_pen_by_doc.get(doc_id_i, 0)),
            weekday_bonus=int(weekday_bonus_by_doc.get(doc_id_i, 0)),
            friday_pen=int(fri_pen_by_doc.get(doc_id_i, 0)),
            partners_bonus=float(partners_bonus_by_doc.get(doc_id_i, 0.0)),
            weekday_preferred_declared=bool(weekday_preferred_declared),
            weekday_avoid_declared=bool(weekday_avoid_declared),
            preferred_partners_declared=bool(preferred_partners_declared),
            totals_prefs_declared=bool(totals_prefs_declared),
            friday_rule_applicable=bool(friday_rule_applicable),
        )

        # Extract the already-computed structured data from ui_components
        categories = dict(ui_components.get("categories") or {})
        solver_components_by_doc = dict(ui_components.get("solver_components_by_doc") or {})

        # ------------------------------
        # Build per-doctor row in EXACT requested order
        # ------------------------------
        row: Dict[str, Any] = {
            "doctor_id": doc_id_i,
            "display_name": _display_name_from_snapshot(payload, doc_id_i),
            "assigned_onsite_total": int(onsite_total_by_doc.get(doc_id_i, 0)),
            "assigned_oncall_total": int(oncall_total_by_doc.get(doc_id_i, 0)),
            "rest_violations": int(rest_viol_by_doc.get(doc_id_i, 0)),
            "preferred_days_requested": int(pref_requested_by_doc.get(doc_id_i, 0)),
            "preferred_days_missed": int(pref_missed_by_doc.get(doc_id_i, 0)),
            "preference_fulfillment_pct": float(pref_pct_by_doc.get(doc_id_i, 100.0)),
            "ui_stars": int(ui_stars),
            "ui_reasons_codes": list(ui_reasons),
            "categories": categories,
            "solver_components_by_doc": solver_components_by_doc,
        }

        per_doctor.append(row)

    # Build per-doctor weekday preference declaration maps for rankings.
    weekday_preferred_declared_by_doc: Dict[int, bool] = {}
    weekday_avoid_declared_by_doc: Dict[int, bool] = {}

    for row in per_doctor:
        did = int(row.get("doctor_id", 0))
        # We recompute from snapshot-backed prefs for consistency (same logic as above).
        prefs = problem.preferences.get(did)
        if prefs is None:
            weekday_preferred_declared_by_doc[did] = False
            weekday_avoid_declared_by_doc[did] = False
            continue

        weekday_preferred_declared_by_doc[did] = bool(
            prefs.preferred_onsite_weekdays or prefs.preferred_oncall_weekdays
        )
        weekday_avoid_declared_by_doc[did] = bool(prefs.avoid_onsite_weekdays or prefs.avoid_oncall_weekdays)

    rankings = _build_rankings(
        per_doctor_rows=per_doctor,
        double_shift_days_by_doctor=double_shift_days_by_doc,
        pref_days_pen_by_doc=pref_days_pen_by_doc,
        totals_pen_by_doc=totals_pen_by_doc,
        fairness_pen_by_doc=fairness_pen_by_doc,
        weekday_pen_by_doc=weekday_pen_by_doc,
        weekday_bonus_by_doc=weekday_bonus_by_doc,
        weekday_preferred_declared_by_doc=weekday_preferred_declared_by_doc,
        weekday_avoid_declared_by_doc=weekday_avoid_declared_by_doc,
        fri_pen_by_doc=fri_pen_by_doc,
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
        "solver_components_total": {
            "rest_penalty": int(rest_pen),
            "preferred_days_penalty": int(pref_days_pen),
            "totals_penalty": int(totals_pen),
            "fairness_penalty": int(fairness_pen),
            "weekday_patterns_penalty": int(weekday_pen),
            "weekday_patterns_bonus": int(weekday_bonus),
            "preferred_partners_bonus": float(sum(partners_bonus_by_doc.values())),
            "friday_free_weekend_penalty": int(fri_pen),
        },
    }

    return {"summary": summary, "details": details}
