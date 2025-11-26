````markdown
# Manual tests — `db_seed_edge_cases.py`

This document describes how to manually test the edge-case demo seed for
**preferences + availability** used by the Availability Service and (later) the solver.

Script under test:

- `scripts/db_seed_edge_cases.py`

> **Important:** This script is **DEV ONLY**. Do **not** run it on production data.


## 1. Prerequisites

Before running the script, make sure that:

1. You have a working virtual environment with backend dependencies installed.

2. The database is reachable (e.g. local SQLite from `backend/config.py`).

3. There are **no critical changes** in the DB schema since the script was written
   (tables:
   `doctors`, `preferences_working`, `preferences_versions`, `preferences_pointers`
   exist and migrations are up-to-date).

4. The backend can start normally:

   ```bash
   uvicorn backend.app:app --reload
````

Swagger should be available at:

* [http://localhost:8000/docs](http://localhost:8000/docs)

## 2. Running the edge-case seed

From the repo root, run:

```bash
PYTHONPATH=. python scripts/db_seed_edge_cases.py
```

The script will print something like:

```text
[edge] Edge-case periods: ALL-CRITICAL=YYYY-01, ALL-ALERT=YYYY-02, ALL-OK=YYYY-03
[edge] Active doctors in DB: [(1, 'Alice', 'Spec', 'specialist'), ...]
...
== Edge-case demo seed complete ==
ALL-CRITICAL period : YYYY-01 (no specialists available).
ALL-ALERT period    : YYYY-02 (exactly one specialist available).
ALL-OK period       : YYYY-03 (everyone fully available).
```

Remember the printed `YYYY` and months:

* **ALL-CRITICAL**: `year_critical = YYYY`, `month_critical = 1`
* **ALL-ALERT**: `year_alert = YYYY`, `month_alert = 2`
* **ALL-OK**: `year_ok = YYYY`, `month_ok = 3`

You will use these values in Swagger.

## 3. What to test in Swagger (admin)

Assumption: you are logged in / authenticated as **admin** (RBAC: `require_admin`).

### 3.1. Availability overview — ALL-CRITICAL period

**Endpoint:**

* `GET /api/v1/availability/overview`

**Parameters:**

* `year = year_critical` (from script log)
* `month = month_critical` (e.g. `1`)

**Expected result:**

* `period_status` should be `"future"` (for next-year periods).
* In the `days` array, **every day** should have:

  * `risk = "critical"`
  * `available_specialists_duty = 0`
  * `available_specialists_oncall = 0`
  * `available_residents_duty >= 1`
  * `available_residents_oncall >= 1`

Explanation:

* For the ALL-CRITICAL period, the script marks **all specialists** unavailable
  on every day (duty + on-call).
* Residents stay fully available.
* Risk rule: `total_specialists == 0` → `RiskLevel.critical`.

### 3.2. Day drill-down — ALL-CRITICAL period

**Endpoint:**

* `GET /api/v1/availability/{year}/{month}/{day}`

**Parameters:**

* `year = year_critical`
* `month = month_critical`
* `day = 1` (or any valid day in that month)

**Expected result:**

* `risk = "critical"`
* `specialists_duty` is an **empty list**
* `specialists_oncall` is an **empty list**
* `residents_duty` contains one or more doctors (IDs and names)
* `residents_oncall` contains one or more doctors

This confirms that:

* Specialists are not available on that day.
* Only residents are available.

### 3.3. Availability overview — ALL-ALERT period

**Endpoint:**

* `GET /api/v1/availability/overview`

**Parameters:**

* `year = year_alert`
* `month = month_alert` (e.g. `2`)

**Expected result:**

* `period_status` should be `"future"`.
* For **every day** in `days`:

  * `risk = "alert"`
  * `available_specialists_duty = 1`
  * `available_specialists_oncall = 1`
  * `available_residents_duty >= 1`
  * `available_residents_oncall >= 1`

Explanation:

* The script keeps **exactly one specialist** fully available,
  marks all other specialists unavailable (all days, duty + on-call),
  and keeps all residents fully available.
* Risk rules:

  * `total_specialists = 1` (< `MIN_OK_SPECIALISTS_TOTAL = 2`)
  * `total_doctors` is high (specialists + residents)
  * Therefore: not `critical` (there is a specialist), but not `ok` either → `alert`.

### 3.4. Day drill-down — ALL-ALERT period

**Endpoint:**

* `GET /api/v1/availability/{year}/{month}/{day}`

**Parameters:**

* `year = year_alert`
* `month = month_alert`
* `day = 1` (or any valid day)

**Expected result:**

* `risk = "alert"`

* In `specialists_duty` and `specialists_oncall`:

  * Exactly **one** doctor (the "always available" specialist).

* In `residents_duty` and `residents_oncall`:

  * One or more doctors (all residents are available).

This confirms:

* The "one specialist + many residents" pattern for every day.
* Risk evaluation correctly identifies it as `alert`.

### 3.5. Availability overview — ALL-OK period

**Endpoint:**

* `GET /api/v1/availability/overview`

**Parameters:**

* `year = year_ok`
* `month = month_ok` (e.g. `3`)

**Expected result:**

* `period_status` should be `"future"`.
* For **every day** in `days`:

  * `risk = "ok"`
  * `available_specialists_duty >= 2`
  * `available_specialists_oncall >= 2`
  * `available_residents_duty >= 1`
  * `available_residents_oncall >= 1`

(Exact numbers depend on how many active doctors you have, but they should be
high enough to satisfy the "ok" thresholds.)

Explanation:

* Script keeps **everyone fully available**.
* Risk rules:

  * Enough specialists and residents in both duty/on-call categories.
  * → `RiskLevel.ok`.

### 3.6. Day drill-down — ALL-OK period

**Endpoint:**

* `GET /api/v1/availability/{year}/{month}/{day}`

**Parameters:**

* `year = year_ok`
* `month = month_ok`
* `day = 1` (or any valid day)

**Expected result:**

* `risk = "ok"`

* `specialists_duty` and `specialists_oncall`:

  * multiple specialists (≥ 2)

* `residents_duty` and `residents_oncall`:

  * multiple residents

This confirms:

* All doctors are available on that day.
* Risk calculation treats the day as `ok`.

## 4. Optional checks — Preferences admin read

You can also confirm the underlying preferences for one doctor.

**Endpoint:**

* `GET /api/v1/preferences/{year}/{month}/{doctor_id}` (admin)

Try for each period:

* ALL-CRITICAL:

  * For a specialist doctor:

    * `unavailable_duty_days` = `[1, 2, ..., last_day_of_month]`
    * `unavailable_oncall_days` = same list
    * `status = "submitted"` (because we created checkpoints + pointer)

* ALL-ALERT:

  * For the always-available specialist:

    * `unavailable_duty_days = []`
    * `unavailable_oncall_days = []`

  * For other specialists:

    * `unavailable_duty_days` = `[1, 2, ..., last_day_of_month]`
    * `unavailable_oncall_days` = same list

* ALL-OK:

  * For any doctor:

    * `unavailable_duty_days = []`
    * `unavailable_oncall_days = []`

These checks confirm that what you see in availability comes from seeded
preference checkpoints, not hard-coded logic.

```


