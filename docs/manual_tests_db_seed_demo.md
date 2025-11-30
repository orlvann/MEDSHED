````markdown
# Manual Tests for `db_seed_demo.py`

This document describes manual test scenarios for the **demo seed script**:

```bash
PYTHONPATH=. python scripts/db_seed_demo.py
````

The script prints something like:

```text
Locked period: locked_year = 2025, locked_month = 11
Open period:   open_year   = 2025, open_month  = 12
```

**Always use the exact `locked_year/locked_month` and `open_year/open_month` values from your own script output.**
The examples below use `2025/11` as the **locked period** and `2025/12` as the **open period**.

Backend is expected to run as:

```bash
uvicorn backend.app:app --reload
```

Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)

---

## 1. Deadline (admin + doctor)

### Endpoint

```http
GET /api/v1/preferences/deadlines/{year}/{month}
```

### Steps

1. Open Swagger.
2. As **admin** or **doctor**, call:

   * Locked period:
     `GET /api/v1/preferences/deadlines/2025/11`
   * Open period:
     `GET /api/v1/preferences/deadlines/2025/12`

   (Replace `2025/11` and `2025/12` with values from the script log.)

### Expected results

**Locked period (e.g. 2025/11):**

* `deadline` – non-null UTC datetime (ISO string),
* `status` – `"locked"`,
* `org_timezone` – `"Europe/Warsaw"`.

**Open period (e.g. 2025/12):**

* No row exists in `preferences_deadlines` for this period, so backend returns:

  * `deadline` – `null`,
  * `status` – `"open"`,
  * `org_timezone` – `"Europe/Warsaw"`.

---

## 2. Summary (admin)

### Endpoint

```http
GET /api/v1/preferences/summary?year=YYYY&month=MM
```

### Steps

1. In Swagger, use **admin** role.
2. Call:

   ```http
   GET /api/v1/preferences/summary?year=2025&month=12
   ```

   (Use `open_year` / `open_month` from the script log.)

### Expected results

* `submitted` – contains **doctor IDs** of the `multi_checkpoint_docs` group
  (the first 3 active doctors used in the seed for the open period).
* `missing` – contains all **other active doctors**:

  * doctors with **working-only** forms,
  * doctors with **no data at all**.

> Note: `summary` does **not** call `ensure_latest_checkpoints_for_period`,
> so doctors with only working data are still counted as `"missing"` here.

---

## 3. Admin – read single doctor form

### Endpoint

```http
GET /api/v1/preferences/{year}/{month}/{doctor_id}
```

### Steps

1. In Swagger, use **admin** role.
2. For each doctor type below, call:

   ```http
   GET /api/v1/preferences/2025/12/{doctor_id}
   ```

   (Use `open_year` / `open_month` and real IDs from `/api/v1/doctors`.)

### Expected results

#### 3.1. Multi-checkpoint doctor

For a doctor from the `multi_checkpoint_docs` group:

* Response contains the full form (all preference fields).
* `status` – `"submitted"`.
* `version_id` – non-null string (current checkpoint ID).
* `can_undo` / `can_redo`:

  * these flags are computed during checkpoint/undo/redo operations,
  * for now, you mainly verify that history exists in DB (multiple versions).

#### 3.2. Working-only doctor

For a doctor from the **working-only** group:

* `status` – `"missing"`,
* working fields are filled according to the seed:

  * unavailable / preferred days,
  * min/max numbers, comments, etc.

#### 3.3. No-data doctor

For a doctor from the **no-data** group (no working, no checkpoint):

* `status` – `"missing"`,
* all day lists are empty:

  * `unavailable_*` – `[]`,
  * `preferred_*` – `[]`,
* numeric fields:

  * `min_*` – `0`,
  * `max_*` – `null`,
* `weekend_back_to_back_allowed` – `true`,
* `comments` – `null`.

This represents the default "fully available" form.

---

## 4. Availability – monthly overview (admin)

### Endpoint

```http
GET /api/v1/availability/overview?year=YYYY&month=MM
```

### Steps

1. In Swagger, use **admin** role.
2. Call for the **open period**:

   ```http
   GET /api/v1/availability/overview?year=2025&month=12
   ```

   (Use `open_year` / `open_month` from the script log.)

### Internal behavior

* This endpoint automatically calls:

  ```python
  ensure_latest_checkpoints_for_period(year, month)
  ```

* For **multi-checkpoint** doctors:

  * existing checkpoints from the seed are used.

* For **working-only** doctors:

  * the service creates **system-generated checkpoints** from working.

* For **no-data** doctors:

  * no working row → they are treated as fully available (all days, duty + on-call).

### Expected results

Use the `day_critical`, `day_ok`, and `day_alert` printed by the script, for example:

```text
Special patterns for open period:
- day_critical = 5
- day_ok       = 10
- day_alert    = 15
```

In the JSON response:

* For `day_critical` (e.g. 5):

  * `risk` should be `"critical"`
    (all specialists are marked as unavailable on this day).

* For `day_alert` (e.g. 15):

  * `risk` should be `"alert"`
    (only one specialist is available; thresholds do not qualify as "ok").

* For `day_ok` (e.g. 10):

  * `risk` should be `"ok"`
    (enough total doctors and enough specialists for both duty and on-call).

---

## 5. Availability – day drill-down (admin)

### Endpoint

```http
GET /api/v1/availability/{year}/{month}/{day}
```

### Steps

1. In Swagger, use **admin** role.
2. Call for several days in the **open period**, for example:

   ```http
   GET /api/v1/availability/2025/12/5   # day_critical
   GET /api/v1/availability/2025/12/10  # day_ok
   GET /api/v1/availability/2025/12/15  # day_alert
   ```

   (Use `open_year` / `open_month` and real day numbers from the script log.)

### Expected results

**Critical day (day_critical):**

* `specialists_duty` – empty list,
* `specialists_oncall` – empty list,
* only residents may appear in `*_duty` / `*_oncall` lists,
* `risk` – `"critical"`.

**Alert day (day_alert):**

* `specialists_duty` and `specialists_oncall`:

  * contain at least one specialist,
  * but do **not** reach the thresholds required for `"ok"`,
* `risk` – `"alert"`.

**Ok day (day_ok):**

* `specialists_duty` and `specialists_oncall`:

  * enough specialists are available,
* together with residents, totals are high enough for `"ok"`,
* `risk` – `"ok"`.

---

## 6. Notes

* All tests above assume:

  * backend is running locally (`uvicorn backend.app:app --reload`),
  * you are authenticated as **admin** for admin endpoints,
  * you use the **exact** year/month and day values printed by `db_seed_demo.py`.
* If you re-run the seed script, IDs and dates may change; always check the latest console output.

```
```
