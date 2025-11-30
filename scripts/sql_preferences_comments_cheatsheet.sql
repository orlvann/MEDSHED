-- docs/sql_preferences_comments_cheatsheet.sql
-- Quick SQL cheatsheet for exploring preference comments in the local SQLite DB.
--
-- HOW TO USE THIS FILE
-- ---------------------
-- 1) From repo root, open the SQLite shell:
--        make db-shell
--    (this runs: sqlite3 backend/db/sqlite.db)
--
-- 2) In the sqlite> prompt, you can:
--    - Paste the "CREATE VIEW" statement below (once, to define the view).
--    - Then run any of the example SELECT queries.
--
-- 3) To leave sqlite3:
--        .quit
--    or:
--        .exit
--
-- NOTE:
-- - This view is read-only helper, it DOES NOT modify data.
-- - It only shows rows where comments are present (non-NULL and non-empty).


/* -------------------------------------------------------------------------
   VIEW: v_doctor_preferences_comments
   - One row per doctor / year / month where a comment exists.
   - Joins preferences_working with doctors.
   - Adds a human-friendly "period_date" string like '2025-02-01'.
   ------------------------------------------------------------------------- */
CREATE VIEW IF NOT EXISTS v_doctor_preferences_comments AS
SELECT
    pw.doctor_id,
    d.first_name,
    d.last_name,
    pw.year,
    pw.month,
    -- Human-readable period string, useful for ordering / display.
    printf('%04d-%02d-01', pw.year, pw.month) AS period_date,
    pw.comments
FROM preferences_working AS pw
JOIN doctors AS d
    ON d.id = pw.doctor_id
WHERE pw.comments IS NOT NULL
  AND TRIM(pw.comments) <> '';


/* -------------------------------------------------------------------------
   EXAMPLES: how to query the view
   ------------------------------------------------------------------------- */

-- 1) Show ALL doctors that have any comment, ordered by name and period.
SELECT
    doctor_id,
    first_name,
    last_name,
    year,
    month,
    period_date,
    comments
FROM v_doctor_preferences_comments
ORDER BY last_name, first_name, year, month;


-- 2) Show comments for ONE doctor (by doctor_id), ordered by year/month.
--    Example: doctor_id = 7
SELECT
    doctor_id,
    first_name,
    last_name,
    year,
    month,
    period_date,
    comments
FROM v_doctor_preferences_comments
WHERE doctor_id = 7
ORDER BY year, month;


-- 3) Show comments for ONE doctor and ONE specific period (year + month).
--    Example: doctor_id = 7, year = 2025, month = 6
SELECT
    doctor_id,
    first_name,
    last_name,
    year,
    month,
    period_date,
    comments
FROM v_doctor_preferences_comments
WHERE doctor_id = 7
  AND year = 2025
  AND month = 6
ORDER BY year, month;


-- 4) Show all comments for a given year (all doctors).
--    Example: year = 2025
SELECT
    doctor_id,
    first_name,
    last_name,
    year,
    month,
    period_date,
    comments
FROM v_doctor_preferences_comments
WHERE year = 2025
ORDER BY last_name, first_name, month;


-- 5) Count how many doctors have a comment in each {year,month}.
SELECT
    year,
    month,
    COUNT(*) AS doctors_with_comments
FROM v_doctor_preferences_comments
GROUP BY year, month
ORDER BY year, month;


-- REMINDER: leaving sqlite3
-- -------------------------
-- In sqlite> prompt:
--    .quit    -- or:
--    .exit
