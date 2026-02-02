from __future__ import annotations

from backend.utils.normalization import normalize_meta


def test_normalize_meta_keeps_exceptions_dict_items_untrimmed():
    """
    Policy: when exceptions is a valid list, we keep items as-is (no field whitelisting).
    """
    meta = {
        "labels": ["x"],
        "exceptions": [
            {"kind": "a", "code": "c1", "custom": "must_stay", "nested": {"ok": True}},
            {"kind": "b", "code": "c2", "extra": 123},
        ],
    }

    out = normalize_meta(meta)
    assert out["exceptions"] == meta["exceptions"]


def test_normalize_meta_replaces_wrong_exceptions_type_with_empty_list():
    """
    Policy: if exceptions is corrupted (wrong type), reset to [] to avoid crashes.
    """
    meta = {"labels": ["x"], "exceptions": "not-a-list"}
    out = normalize_meta(meta)
    assert out["exceptions"] == []
