# backend/services/diagnostics_service.py

"""
Diagnostics Service — analyze and summarize schedules.

Responsibilities:
- Load schedule payload + frozen inputs_snapshot from DB (working/draft/published).
- Load preference versions referenced by inputs_snapshot.
- Build ProblemData (pure core input).
- Call backend/core/diagnostics.py to compute metrics.
- Assemble API DTOs (schemas/diagnostics.py) or return plain dict for storage.

Design rules:
- Service knows DB and DTOs.
- Core computes metrics (no DB, no Pydantic).
"""

from __future__ import annotations

import calendar
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.core.diagnostics import compute_quality
from backend.core.types import DoctorInput, PreferencesInput, ProblemData
from backend.models.common_enums import DoctorRole
from backend.models.orm.preference import PreferenceVersion


def _month_days(year: int, month: int) -> list[int]:
    """Return all calendar day numbers for the given month (1..num_days)."""
    _, num_days = calendar.monthrange(int(year), int(month))
    return list(range(1, int(num_days) + 1))


def _month_weekdays(year: int, month: int, days: list[int]) -> dict[int, int]:
    """Return {day -> weekday} where weekday is 0=Mon .. 6=Sun."""
    out: dict[int, int] = {}
    for d in days:
        out[int(d)] = int(datetime(int(year), int(month), int(d)).weekday())
    return out


def _build_doctors_from_inputs_snapshot(inputs_snapshot: dict) -> dict[int, DoctorInput]:
    """
    Build core DoctorInput dict from schedule.inputs_snapshot.doctors.

    Expected inputs_snapshot shape (DTO):
    {
      "doctors": {
        "123": {"role": "specialist"|"resident", "is_head": true, ...},
        ...
      },
      ...
    }

    IMPORTANT:
    - Snapshot values are plain JSON, so role is typically a string.
    - We must parse it defensively to avoid crashing diagnostics for old/bad data.
    """
    doctors_any = (inputs_snapshot or {}).get("doctors") or {}
    if not isinstance(doctors_any, dict):
        return {}

    doctors: dict[int, DoctorInput] = {}

    for raw_id, snap in doctors_any.items():
        try:
            doc_id = int(raw_id)
        except Exception:
            continue

        if not isinstance(snap, dict):
            continue

        role_raw = snap.get("role")
        try:
            role = DoctorRole(str(role_raw))
        except Exception:
            # Defensive fallback for corrupted snapshot role values.
            role = DoctorRole.specialist

        doctors[doc_id] = DoctorInput(
            id=int(doc_id),
            role=role,
            is_head=bool(snap.get("is_head", False)),
            is_active=bool(snap.get("is_active_at_snapshot", True)),
        )

    return doctors


def _load_preference_versions_by_id(db: Session, version_ids: set[int]) -> dict[int, dict]:
    """
    Load PreferenceVersion.payload for the given version IDs.

    Returns:
      {version_id: payload_dict}
    """
    if not version_ids:
        return {}

    rows = db.query(PreferenceVersion).filter(PreferenceVersion.id.in_(sorted(int(x) for x in version_ids))).all()

    out: dict[int, dict] = {}
    for r in rows:
        if isinstance(r.payload, dict):
            out[int(r.id)] = dict(r.payload)
    return out


def _prefs_input_from_payload(doctor_id: int, payload: dict) -> PreferencesInput:
    """
    Convert PreferenceVersion.payload (DTO-like dict) into core PreferencesInput.

    We only map fields that core needs today. Missing fields default safely.
    """

    def _list_int(name: str) -> list[int]:
        v = payload.get(name) or []
        if not isinstance(v, list):
            return []
        out: list[int] = []
        for x in v:
            try:
                out.append(int(x))
            except Exception:
                continue
        return out

    def _opt_int(name: str) -> Optional[int]:
        v = payload.get(name)
        if v is None:
            return None
        try:
            return int(v)
        except Exception:
            return None

    return PreferencesInput(
        doctor_id=int(doctor_id),
        unavailable_onsite_days=_list_int("unavailable_onsite_days"),
        unavailable_oncall_days=_list_int("unavailable_oncall_days"),
        preferred_onsite_days=_list_int("preferred_onsite_days"),
        preferred_oncall_days=_list_int("preferred_oncall_days"),
        max_onsite_total=_opt_int("max_onsite_total"),
        target_onsite_total=_opt_int("target_onsite_total"),
        max_oncall_total=_opt_int("max_oncall_total"),
        target_oncall_total=_opt_int("target_oncall_total"),
        max_onsite_weekends=_opt_int("max_onsite_weekends"),
        target_onsite_weekends=_opt_int("target_onsite_weekends"),
        max_oncall_weekends=_opt_int("max_oncall_weekends"),
        target_oncall_weekends=_opt_int("target_oncall_weekends"),
        preferred_onsite_weekdays=_list_int("preferred_onsite_weekdays"),
        preferred_oncall_weekdays=_list_int("preferred_oncall_weekdays"),
        avoid_onsite_weekdays=_list_int("avoid_onsite_weekdays"),
        avoid_oncall_weekdays=_list_int("avoid_oncall_weekdays"),
        allow_weekend_consecutive_onsite_oncall=bool(payload.get("allow_weekend_consecutive_onsite_oncall", False)),
        preferred_partners=_list_int("preferred_partners"),
        comments=(payload.get("comments") if isinstance(payload.get("comments"), str) else None),
    )


def build_problem_data_from_schedule_snapshot(
    *,
    db: Session,
    year: int,
    month: int,
    schedule_payload: dict,
) -> ProblemData:
    """
    Build ProblemData for diagnostics from schedule payload + inputs_snapshot.

    schedule_payload expected minimal shape:
    {
      "participant_doctor_ids": [...],
      "assignments": [...],
      "inputs_snapshot": {
         "doctors": {...},
         "preference_version_id_by_doctor": {...}
      },
      "meta": {...}
    }
    """
    inputs_snapshot = schedule_payload.get("inputs_snapshot") or {}
    if not isinstance(inputs_snapshot, dict):
        inputs_snapshot = {}

    doctors = _build_doctors_from_inputs_snapshot(inputs_snapshot)

    participants_any = schedule_payload.get("participant_doctor_ids") or []
    participants: set[int] = set()
    if isinstance(participants_any, list):
        for x in participants_any:
            try:
                participants.add(int(x))
            except Exception:
                continue

    # Map doctor_id -> preference_version_id
    pref_map_any = inputs_snapshot.get("preference_version_id_by_doctor") or {}
    pref_version_by_doc: dict[int, Optional[int]] = {}
    if isinstance(pref_map_any, dict):
        for k, v in pref_map_any.items():
            try:
                doc_id = int(k)
            except Exception:
                continue
            if v is None:
                pref_version_by_doc[doc_id] = None
            else:
                try:
                    pref_version_by_doc[doc_id] = int(v)
                except Exception:
                    pref_version_by_doc[doc_id] = None

    version_ids: set[int] = set(v for v in pref_version_by_doc.values() if isinstance(v, int))
    payload_by_version_id = _load_preference_versions_by_id(db, version_ids)

    # Build PreferencesInput per participant doctor
    preferences: dict[int, PreferencesInput] = {}
    for doc_id in sorted(participants):
        version_id = pref_version_by_doc.get(doc_id)
        payload = payload_by_version_id.get(int(version_id)) if isinstance(version_id, int) else None

        # If snapshot has no pref version, we still create an "empty" PreferencesInput
        # (safe defaults => "no preferences").
        preferences[doc_id] = _prefs_input_from_payload(doc_id, payload or {})

    days = _month_days(year, month)
    weekdays = _month_weekdays(year, month, days)

    return ProblemData(
        year=int(year),
        month=int(month),
        days=list(days),
        weekdays=dict(weekdays),
        doctors=dict(doctors),
        preferences=dict(preferences),
        participant_doctor_ids=set(participants),
        # ignore_days/ignore_slots are handled by core via meta.exceptions parsing,
        # but we keep them here for completeness (future use).
        ignore_days=set(),
        ignore_slots=set(),
    )


def compute_schedule_diagnostics_quality(
    *,
    db: Session,
    year: int,
    month: int,
    schedule_payload: dict,
) -> dict[str, Any]:
    """
    High-level service API: compute diagnostics quality dict.

    Returns JSON-serializable dict:
    {
      "summary": {...},
      "details": {...}
    }
    """
    problem = build_problem_data_from_schedule_snapshot(
        db=db, year=year, month=month, schedule_payload=schedule_payload
    )
    return compute_quality(problem=problem, payload=schedule_payload)
