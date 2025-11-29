````markdown
# Manual Tests – Real Anonymous Data Seed

This document describes how to seed the **real anonymous doctor + preferences data**
into the local development database.

The goal is to have:
- realistic doctors (names, roles, emails) from `data/seeds/doctors_anon.csv`
- a consistent calendar of preference deadlines for shifted demo years
- (later) real preference forms loaded from Excel files under `data/preferences_excel/`

> DEV ONLY: These scripts are for local development and demos.  
> Never run them against a shared/staging/production database.

---

## 1. Preconditions

Before seeding, make sure that:

1. The virtualenv is activated and dependencies are installed:

   ```bash
   pip install -r requirements.txt
````

2. The database exists and all migrations are applied, for example:

   ```bash
   # Preferred (if available in the Makefile)
   make db-upgrade

   # Or directly via Alembic:
   PYTHONPATH=. alembic -c backend/alembic.ini upgrade head
   ```

3. You are in the project root (`MEDSHED`) when running the commands:

   ```bash
   cd MEDSHED
   ```

---

## 2. Year shifting model (calendar mapping)

The real data comes from historical years **2023–2025**.
For the demo, we **shift** it into future years so that:

* `2023` → **`2025`**
* `2024` → **`2026`**
* `2025` → **`2027`**

This applies to:

* how we interpret the Excel files (`data/preferences_excel/...`)
* how we generate monthly **preference deadlines** in the DB

The earliest month with data is `2023-02`, which becomes `2025-02`.
The latest month is `2025-12`, which becomes `2027-12`.

---

## 3. Seeding doctors (anonymous real doctors)

Script: `scripts/db_seed_doctors_anon.py`
Source file: `data/seeds/doctors_anon.csv`

This script:

* wipes existing `doctors` rows (DEV ONLY)
* inserts doctors from `doctors_anon.csv`
* sets:

  * `first_name`, `last_name`
  * `role` (`specialist` | `resident`)
  * `is_active = true`
  * `is_head` according to the CSV
  * `email` like `first.last@medsched.test`
* **does not** create any `users` yet (no passwords, no login).

Run:

```bash
PYTHONPATH=. python -m scripts.db_seed_doctors_anon
```

Quick sanity check:

```bash
make db-show
```

Expected (example):

```text
== Doctors ==
#1 Brad Devon role=specialist email=brad.devon@medsched.test is_active=True is_head=False
...
```

(The exact IDs may differ, but the names / roles / emails should match the CSV.)

---

## 4. Seeding preference deadlines (shifted years)

Script: `scripts/db_seed_pref_deadlines_real.py`

This script:

* wipes all rows from `preferences_deadlines` (DEV ONLY)
* creates monthly deadlines for the shifted calendar:

  * from **2025-02** to **2027-12**
* uses the following rule:

For a given `{year, month}`:

* the deadline is **15th day of the previous month** at **23:59** in the organisation timezone
  (e.g. `Europe/Warsaw`), then converted and stored in **UTC** in the DB:

Example:

* Period: `2025-02`
* Org timezone: `Europe/Warsaw`
* Deadline: `2025-01-15 23:59` (org tz)
* Stored as: `2025-01-15 22:59:00+00:00` (UTC)

Run:

```bash
PYTHONPATH=. python -m scripts.db_seed_pref_deadlines_real
```

Check:

```bash
make db-show
```

Expected fragment:

```text
== Preferences: Deadlines ==
2025-02 deadline_utc=2025-01-15 22:59:00+00:00 org_tz=Europe/Warsaw
2025-03 deadline_utc=2025-02-15 22:59:00+00:00 org_tz=Europe/Warsaw
...
2027-12 deadline_utc=2027-11-15 22:59:00+00:00 org_tz=Europe/Warsaw
```

---

## 5. Seeding preferences from Excel (coming soon)

Data source:

* Normalized Excel files in: `data/preferences_excel/`
* One file per `{year_month}_{alias}.xlsx`, e.g.:

  * `2023_02_devon.xlsx`
  * `2023_02_hamster.xlsx`
  * ...

Year shifting rule:

* when reading Excel:

  * `2023` → `2025`
  * `2024` → `2026`
  * `2025` → `2027`

Target tables:

* `preferences_working`
* `preferences_versions`
* `preferences_pointers`

Status: **TBD** – to be implemented in a dedicated script
(e.g. `scripts/db_seed_preferences_real.py`).

When the script is ready, this section should be updated with:

* exact CLI command
* mapping rules (how we translate Excel fields → JSON stored in DB)
* sample output for `make db-show`.

---

## 6. Recommended full sequence (local dev)

For a fully fresh local dev database with real anonymous data:

1. Drop DB (optional, if needed)

2. Apply migrations:

   ```bash
   make db-upgrade
   ```

3. Seed doctors:

   ```bash
   PYTHONPATH=. python -m scripts.db_seed_doctors_anon
   ```

4. Seed preference deadlines:

   ```bash
   PYTHONPATH=. python -m scripts.db_seed_pref_deadlines_real
   ```

5. (Later) Seed real preferences from Excel once the script is ready.

6. Verify:

   ```bash
   make db-show
   ```

If everything looks correct, you can start the backend and hit the API:

```bash
uvicorn backend.asgi:app --reload
```

---

## 7. Safety notes

* These scripts are **destructive** for seed tables:

  * `db_seed_doctors_anon` wipes the `doctors` table.
  * `db_seed_pref_deadlines_real` wipes `preferences_deadlines`.
* Do not run them on any shared environment unless the team explicitly agrees.
* If in doubt, create a local backup first (see `scripts/db_dump_sql.py`).

````
