# data_preferences_excel_normalize.py
"""
Normalize Excel file names for real (anonymized) preferences.

Input tree (NOT tracked in git):
    data/preferences_excel_raw/preferences_real_anon/<DoctorFolder>/<Year>/<MM_YYYY_alias.xlsx>

Example:
    data/preferences_excel_raw/preferences_real_anon/Devon_Brad/2023/02_2023_devon.xlsx

Output (tracked in git):
    data/preferences_excel/YYYY_MM_alias.xlsx

Example:
    data/preferences_excel/2023_02_devon.xlsx

This script does NOT modify or delete the raw files – it only copies them
with normalized names into data/preferences_excel/.
"""

from __future__ import annotations

import shutil
from pathlib import Path

# Root with raw Excel files (copied from Windows, ignored by git)
RAW_ROOT = Path("data/preferences_excel_raw/preferences_real_anon")

# Root for normalized copies (tracked in git)
OUT_ROOT = Path("data/preferences_excel")


def normalize_excel_files() -> None:
    """Walk through RAW_ROOT and copy all .xlsx files with normalized names."""
    if not RAW_ROOT.exists():
        print(f"[error] RAW_ROOT does not exist: {RAW_ROOT}")
        return

    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    copied = 0
    skipped = 0

    # Walk recursively through all subfolders and find *.xlsx files
    for path in RAW_ROOT.rglob("*.xlsx"):
        if not path.is_file():
            continue

        # Example: "02_2023_devon.xlsx" -> "02_2023_devon"
        stem = path.stem
        parts = stem.split("_")

        # We expect at least: [MM, YYYY, alias]
        if len(parts) < 3:
            print(f"[warn] Unexpected filename format (skipping): {path}")
            skipped += 1
            continue

        month_str = parts[0]
        year_str = parts[1]
        # alias may contain extra underscores, so join the rest back
        alias = "_".join(parts[2:])

        # Basic numeric validation for month/year
        try:
            month = int(month_str)
            year = int(year_str)
        except ValueError:
            print(f"[warn] Non-numeric month/year in filename (skipping): {path}")
            skipped += 1
            continue

        # Normalize month to 2 digits, keep year_str as is
        dest_name = f"{year:04d}_{month:02d}_{alias}.xlsx"
        dest_path = OUT_ROOT / dest_name

        # Copy the file (overwrite if already exists, but log it)
        if dest_path.exists():
            print(f"[info] Overwriting existing file: {dest_path}")

        # Use copy2 to preserve timestamps/metadata (not critical, but nice)
        shutil.copy2(path, dest_path)
        copied += 1

    print(f"[done] Copied {copied} files into {OUT_ROOT} (skipped={skipped}).")


if __name__ == "__main__":
    normalize_excel_files()
