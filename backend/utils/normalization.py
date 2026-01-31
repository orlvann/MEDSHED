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
    - Input item shape (validated by DTOs): {"day": int, "shift_type": "onsite"|"oncall", "doctor_id": int}
    - Output: sorted + deduped list with the same item shape.

    Notes:
    - Sorting key matches how UI grid is laid out (day first, then by shift_type).
    - Dedup prevents accidental duplicates (e.g., double click or merge glitch).
    """
    seen: set[Tuple[int, str, int]] = set()
    out: List[Dict[str, Any]] = []

    def _as_value_shift(x: Any) -> str:
        # Accept Enum/str; prefer Enum.value if present.
        if hasattr(x, "value"):
            return str(getattr(x, "value"))
        return str(x)

    def _require_int(item: Dict[str, Any], key: str) -> int:
        """
        Read item[key] safely and convert it to int.

        Why:
        - dict.get(...) can return None, and Pylance then complains about int(None).
        - We want a clear error if the payload is missing required keys.
        """
        raw = item.get(key)
        if raw is None:
            raise ValueError(f"Missing '{key}' in assignment item: {item}")
        return int(raw)

    def _require_value(item: Dict[str, Any], key: str) -> Any:
        """
        Read item[key] safely (required field).
        Raises a clear error when missing.
        """
        raw = item.get(key)
        if raw is None:
            raise ValueError(f"Missing '{key}' in assignment item: {item}")
        return raw

    # Stable sort ensures consistent serialization (useful for exports and testing).
    items: List[Dict[str, Any]] = []
    for a in assignments or []:
        day = _require_int(a, "day")
        doctor_id = _require_int(a, "doctor_id")
        shift_raw = _require_value(a, "shift_type")
        shift = _as_value_shift(shift_raw)  # "on_call" | "on_duty"
        items.append({"day": day, "shift_type": shift, "doctor_id": doctor_id})

    for a in sorted(items, key=lambda x: (x["day"], x["shift_type"], x["doctor_id"])):
        key = (a["day"], a["shift_type"], a["doctor_id"])
        if key not in seen:
            seen.add(key)
            out.append({"day": key[0], "shift_type": key[1], "doctor_id": key[2]})

    return out


def normalize_meta(meta: Dict[str, Any] | None) -> Dict[str, Any]:
    """
    Normalize meta dict:
    - Ensure "labels" is a list of unique, sorted strings.
    - Ensure "exceptions" is a list (keep as-is if already a list).
    """
    # meta must always be a dict; if it's a wrong type, reset to a safe base shape.
    if not isinstance(meta, dict):
        m: Dict[str, Any] = {"labels": []}
    else:
        # Make a shallow copy so we don't mutate the caller's dict by accident.
        m = dict(meta)

    # ---- labels: ALWAYS a list[str] ----
    # Defensive: if labels is a string/dict/None/etc., treat it as empty list.
    labels_raw = m.get("labels", [])
    if not isinstance(labels_raw, list):
        labels_raw = []

    labels_clean: List[str] = []
    for x in labels_raw:
        # Convert everything to string, strip whitespace, skip empty labels.
        s = str(x).strip()
        if s:
            labels_clean.append(s)

    # Unique + sorted to keep payload deterministic.
    m["labels"] = sorted(set(labels_clean))

    # ---- exceptions: ALWAYS a list ----
    # If it is not a list, replace with empty list (do NOT try to coerce).
    if not isinstance(m.get("exceptions"), list):
        m["exceptions"] = []

    return m
