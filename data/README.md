```markdown
# Data directory

This folder contains seed and reference data for the MEDSCHED project.

Key locations:

- `data/seeds/`
  - `doctors_anon.csv` – anonymous real doctor list used by `scripts/db_seed_doctors_anon.py`.
- `data/preferences_excel/`
  - Normalized monthly preference forms per doctor (one file per `{year_month}_{alias}.xlsx`).

For step-by-step instructions on how to seed these into the local database,
see:

- `docs/manual_tests_db_seed_real.md`
