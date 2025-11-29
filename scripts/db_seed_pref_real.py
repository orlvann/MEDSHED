"""
Seed helper: real preferences from Excel files (DRY-RUN first).

Current behaviour:
- Scan data/preferences_excel for *.xlsx files.
- Parse year, month and doctor alias from file names: YYYY_MM_alias.xlsx
- Map alias -> Doctor row in the DB.
- Shift years: 2023->2025, 2024->2026, 2025->2027.
- Print what *would* be inserted for each (doctor, year, month).

Next step (TODO):
- After we agree on payload structure and ORM columns in Preference*
  models, add real inserts into:
  - PreferenceWorking / PreferenceVersion / PreferencePointer.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.session import SessionLocal
from backend.models.orm.doctor import Doctor

# Year remapping policy: how we "time-shift" the real data.
YEAR_MAP: Dict[int, int] = {
    2023: 2025,
    2024: 2026,
    2025: 2027,
}


# Map doctor alias used in Excel file names -> (first_name, last_name)
# Example file name: 2025_02_devon.xlsx  -> alias "devon" -> Brad Devon.
ALIAS_TO_NAME: Dict[str, Tuple[str, str]] = {
    "devon": ("Brad", "Devon"),
    "grizzly": ("Rick", "Grizzly"),
    "hamster": ("Anna", "Hamster"),
    "jedi": ("Martin", "Jedi"),
    "kolton": ("Jake", "Kolton"),
    "lukewood": ("Ralph", "Lukewood"),
    "router": ("Mark", "Router"),
    "skipperP": ("Paul", "Skipper"),
    "skipperW": ("William", "Skipper"),
    "streeter": ("Anna", "Streeter"),
    "sussman": ("Paul", "Sussman"),
    "tacker": ("Alice", "Tacker"),
}


@dataclass
class PrefFile:
    """Single Excel file with mapped DB doctor and shifted year/month."""

    path: Path
    doctor_id: int
    doctor_name: str  # for logging only
    orig_year: int
    orig_month: int
    target_year: int
    target_month: int


def load_doctor_ids(db: Session) -> Dict[str, int]:
    """
    Build mapping alias -> doctor_id using ALIAS_TO_NAME and the Doctors table.

    Key idea:
    - We never store alias in DB, so we map alias -> (first_name, last_name)
      and then look up the Doctor row by name.
    """
    alias_to_id: Dict[str, int] = {}

    for alias, (first_name, last_name) in ALIAS_TO_NAME.items():
        stmt = select(Doctor).where(
            Doctor.first_name == first_name,
            Doctor.last_name == last_name,
        )
        doctor = db.execute(stmt).scalars().first()
        if doctor is None:
            raise RuntimeError(
                f"Doctor not found for alias='{alias}' "
                f"({first_name} {last_name}). Did you run db_seed_doctors_anon?"
            )
        alias_to_id[alias] = doctor.id

    return alias_to_id


def parse_filename(path: Path) -> Tuple[int, int, str]:
    """
    Parse file name of the form 'YYYY_MM_alias.xlsx'.

    Returns:
        (year, month, alias)

    Raises:
        ValueError if the pattern does not match.
    """
    stem = path.stem  # e.g. "2025_02_devon"
    parts = stem.split("_", 2)
    if len(parts) != 3:
        raise ValueError(f"Unexpected file name format: {path.name!r}")

    year_str, month_str, alias = parts
    year = int(year_str)
    month = int(month_str)
    return year, month, alias


def collect_pref_files(db: Session, root_dir: Path) -> List[PrefFile]:
    """
    Scan root_dir for *.xlsx and build PrefFile objects for each.

    - Skip files whose year is not in YEAR_MAP.
    """
    alias_to_id = load_doctor_ids(db)
    results: List[PrefFile] = []

    for path in sorted(root_dir.glob("*.xlsx")):
        try:
            orig_year, orig_month, alias = parse_filename(path)
        except ValueError as exc:  # bad file name format
            print(f"[WARN] Skipping {path.name}: {exc}")
            continue

        if orig_year not in YEAR_MAP:
            print(f"[WARN] Skipping {path.name}: year {orig_year} not in YEAR_MAP")
            continue

        if alias not in alias_to_id:
            print(f"[WARN] Skipping {path.name}: unknown alias {alias!r}")
            continue

        target_year = YEAR_MAP[orig_year]
        target_month = orig_month

        doctor_id = alias_to_id[alias]
        first_name, last_name = ALIAS_TO_NAME[alias]
        doctor_name = f"{first_name} {last_name}"

        results.append(
            PrefFile(
                path=path,
                doctor_id=doctor_id,
                doctor_name=doctor_name,
                orig_year=orig_year,
                orig_month=orig_month,
                target_year=target_year,
                target_month=target_month,
            )
        )

    return results


def dry_run_print(files: List[PrefFile]) -> None:
    """Print a human-readable summary of what would be seeded."""
    print("== Planned preference imports (DRY RUN) ==")
    for f in files:
        print(
            f"{f.path.name}: "
            f"doctor #{f.doctor_id} ({f.doctor_name}) "
            f"{f.orig_year:04d}-{f.orig_month:02d} "
            f"-> target {f.target_year:04d}-{f.target_month:02d}"
        )

    print(f"\nTotal files mapped: {len(files)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed real preferences from Excel (currently DRY-RUN only).")
    parser.add_argument(
        "--root-dir",
        type=Path,
        default=Path("data/preferences_excel"),
        help="Directory with normalized Excel files YYYY_MM_alias.xlsx",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="When set, perform real inserts (TODO). For now only dry-run is implemented.",
    )
    args = parser.parse_args()

    db: Session = SessionLocal()
    try:
        files = collect_pref_files(db, args.root_dir)

        # For now we always only print the plan.
        dry_run_print(files)

        if args.commit:
            print(
                "\n[INFO] --commit was passed, but real DB inserts are not "
                "implemented yet. This script currently only performs a dry run."
            )
            # TODO: implement real inserts into Preference* tables.
    finally:
        db.close()


if __name__ == "__main__":
    main()
