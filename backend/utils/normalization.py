# backend/utils/normalization.py
"""
Normalization utilities for schedule structures.

Why normalize?
- Stable sorting + deduplication avoids "false diffs" caused by different orderings.
- Ensures we never persist duplicated assignment rows accidentally.
- Guarantees a consistent shape of the payload for exports and equality checks.

Normalization strategy for assignments:
- Sort by (day, shift_type, doctor_id).
- Deduplicate by the same triple.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple


def normalize_assignments(assignments: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Normalize assignments list:
    - Input item shape (validated by DTOs): {"day": int, "shift_type": "on_duty"|"on_call", "doctor_id": int}
    - Output: sorted + deduped list with the same item shape.

    Notes:
    - Sorting key matches how UI grid is laid out (day first, then by shift_type).
    - Dedup prevents accidental duplicates (e.g., double click or merge glitch).
    """
    seen: set[Tuple[int, str, int]] = set()
    out: List[Dict[str, Any]] = []

    # Stable sort ensures consistent serialization (useful for exports and testing).
    for a in sorted(assignments, key=lambda x: (x["day"], x["shift_type"], x["doctor_id"])):
        key = (int(a["day"]), str(a["shift_type"]), int(a["doctor_id"]))
        if key not in seen:
            seen.add(key)
            # Rebuild dict to guarantee correct types and field names.
            out.append({"day": key[0], "shift_type": key[1], "doctor_id": key[2]})
    return out
