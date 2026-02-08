# backend/core/rest_window.py
"""
Rest window helpers (pure core).

This module defines ONLY:
- what counts as a rest violation between two shifts,
- and a small date helper for Sat->Sun checks.

Rules:
- NO OR-Tools imports
- NO DB / DTO imports
- Safe to use in both solver and diagnostics.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from backend.models.common_enums import ShiftType


def is_sat_to_sun(
    *,
    prev_year: int,
    prev_month: int,
    prev_day: int,
    next_year: int,
    next_month: int,
    next_day: int,
) -> bool:
    """
    True only for Saturday -> Sunday across ANY boundary (including cross-month).

    We intentionally use naive datetime.weekday():
    - 0=Mon ... 5=Sat, 6=Sun
    """
    wd_prev = datetime(int(prev_year), int(prev_month), int(prev_day)).weekday()
    wd_next = datetime(int(next_year), int(next_month), int(next_day)).weekday()
    return wd_prev == 5 and wd_next == 6


def rest_violation_kind(
    *,
    prev_shift: ShiftType,
    next_shift: ShiftType,
    is_weekend_pair: bool,
    allow_weekend_consecutive: bool,
) -> Optional[str]:
    """
    Classify whether the pair (prev_shift -> next_shift) is a rest violation.

    Returns:
      - "onsite_onsite" for onsite -> onsite
      - "oncall_oncall" for oncall -> oncall
      - "cross" for onsite <-> oncall (unless weekend exception applies)
      - None if there is NO violation (only possible for weekend-exception cross)

    Weekend exception:
    - Applies ONLY to cross shifts
    - Applies ONLY to Sat->Sun
    - Requires allow_weekend_consecutive=True
    """
    if prev_shift == ShiftType.onsite and next_shift == ShiftType.onsite:
        return "onsite_onsite"

    if prev_shift == ShiftType.oncall and next_shift == ShiftType.oncall:
        return "oncall_oncall"

    # Cross shift (onsite <-> oncall)
    is_cross = (prev_shift == ShiftType.onsite and next_shift == ShiftType.oncall) or (
        prev_shift == ShiftType.oncall and next_shift == ShiftType.onsite
    )

    if not is_cross:
        # Defensive: should never happen with our enum, but keep it safe.
        return None

    if bool(is_weekend_pair and allow_weekend_consecutive):
        # Weekend exception allows cross shift without penalty.
        return None

    return "cross"
