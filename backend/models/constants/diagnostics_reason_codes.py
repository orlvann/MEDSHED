# backend/constants/diagnostics_reason_codes.py
"""
Stable reason codes used by diagnostics rankings (UI-friendly).

Rules:
- Every code must be defined as a constant here.
- Rankings must only emit codes that are inside ALL_REASON_CODES.
- Keep this module small and dependency-free (constants only).
"""

from __future__ import annotations

from typing import Final, FrozenSet

# ------------------------------
# Unhappy reasons (negative signals)
# ------------------------------

# Doctor violated rest rules at least once.
REASON_REST_VIOLATIONS: Final[str] = "rest_violations"

# Doctor missed at least one preferred concrete day (preferred_onsite_days / preferred_oncall_days).
REASON_PREFERRED_DAYS_MISSED: Final[str] = "preferred_days_missed"

# Doctor had a hard double shift on the same day (onsite+oncall).
REASON_HARD_DOUBLE_SHIFT_SAME_DAY: Final[str] = "hard_double_shift_same_day"

# Doctor is assigned on weekdays they wanted to avoid (weekday patterns penalty).
REASON_WEEKDAY_PATTERN_MISMATCH: Final[str] = "weekday_pattern_mismatch"

# Doctor has too many assigned shifts compared to targets/max (totals penalty dominates).
REASON_OVERLOADED_TOTALS: Final[str] = "overloaded_totals"

# Doctor works on Fridays before a free weekend more than desired.
REASON_FRIDAY_PENALTY: Final[str] = "friday_penalty"

# Broad fallback: preference fulfillment percent is below 100% and we found no more specific reason.
REASON_PREFERENCES_NOT_FULLY_MET: Final[str] = "preferences_not_fully_met"


# ------------------------------
# Happy reasons (positive signals)
# ------------------------------

# Doctor has zero rest violations.
REASON_GOOD_REST: Final[str] = "good_rest"

# Doctor has good preference fulfillment (>= threshold).
REASON_PREFERENCES_MET: Final[str] = "preferences_met"

# Doctor has very low fairness/totals penalties (balanced workload).
REASON_BALANCED_LOAD: Final[str] = "balanced_load"


# ------------------------------
# Single source of truth for validation
# ------------------------------

ALL_REASON_CODES: Final[FrozenSet[str]] = frozenset(
    {
        REASON_REST_VIOLATIONS,
        REASON_PREFERRED_DAYS_MISSED,
        REASON_HARD_DOUBLE_SHIFT_SAME_DAY,
        REASON_WEEKDAY_PATTERN_MISMATCH,
        REASON_OVERLOADED_TOTALS,
        REASON_FRIDAY_PENALTY,
        REASON_PREFERENCES_NOT_FULLY_MET,
        REASON_GOOD_REST,
        REASON_PREFERENCES_MET,
        REASON_BALANCED_LOAD,
    }
)
