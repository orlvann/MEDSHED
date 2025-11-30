````markdown
# Real Anonymous Data Seed (DEV only)

This is a **one-shot helper** to load real-looking anonymous data into your **local dev DB**.

> ⚠️ DEV ONLY – never run this on shared/staging/prod.

---

## 1. Preconditions

Run everything from the project root (`MEDSHED`), with venv active and DB migrated:

```bash
cd MEDSHED
make db-upgrade
````

If you need a clean DB:

```bash
make db-reset
make db-upgrade
```

---

## 2. One command: seed real data

Main entrypoint:

```bash
make db-seed-real
```

This target runs three scripts in order:

1. `python -m scripts.db_seed_doctors_anon`

   * wipes `doctors`
   * inserts anonymous doctors from `data/seeds/doctors_anon.csv`
   * sets role, is_head, is_active, and fake email (`first.last@medsched.test`)

2. `python -m scripts.db_seed_pref_deadlines_real`

   * wipes `preferences_deadlines`
   * creates monthly deadlines for periods **2025-02 → 2027-12**
   * deadline rule: 15th of previous month, 23:59 in org timezone (stored as UTC)

3. `python -m scripts.db_seed_pref_real`

   * reads Excel files from `data/preferences_excel/`
     (`YYYY_MM_alias.xlsx`)
   * shifts years:
     `2023 → 2025`, `2024 → 2026`, `2025 → 2027`
   * fills:

     * `preferences_working` (day lists + comments)
     * `preferences_versions` (JSON payload snapshots)
     * `preferences_pointers` (current version per doctor/month)

On success you’ll see a summary like:

```text
All files processed and committed.
```

---

## 3. Quick sanity check

Basic check of what’s in the DB:

```bash
make db-show
```

Optional manual SQL (from `make db-shell` → `sqlite3`):

```sql
SELECT DISTINCT year, month
FROM preferences_working
ORDER BY year, month;

SELECT
    pw.doctor_id,
    d.first_name,
    d.last_name,
    pw.year,
    pw.month,
    pw.comments
FROM preferences_working AS pw
JOIN doctors AS d
    ON d.id = pw.doctor_id
WHERE pw.comments IS NOT NULL
  AND TRIM(pw.comments) <> ''
ORDER BY
    pw.doctor_id,
    pw.year,
    pw.month;

```

If years are `2025, 2026, 2027` and comments look reasonable, the seed worked.

```
