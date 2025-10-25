
# **Admin Path – Monthly Schedule Workflow & API endpoints**

## General Overview
 

### Full Admin View at a Glance

1. **Login**
2. **Doctors Tab:** manage directory / monthly doctors' pool (`is_active` checkbox)
3. **Preferences Tab:** review, adjust, manage deadlines
4. **Generate New Draft Tab:** confirm the monthly pool, run pre-flight coverage (optionally `ignore_*`), click **Generate**
5. **Schedules Tab:**
   - **Browse** by year/month, draft/published
   - **Diagnostics:** quality, fairness, coverage
   - **Manual tweaks** → **Save** (checkpoint) → diagnostics update
   - **Publish** (with `force` + `accepted_exceptions` if needed)
   - **Export** XLSX/PDF


---

### List of endpoints in Admin view

**Auth**

* `POST /api/v1/auth/login`

**Doctors (directory)**

* `GET /api/v1/doctors?page=&size=&role=&search=&is_active=true|false|all`
* `POST /api/v1/doctors`
* `PUT /api/v1/doctors/{doctor_id}`
* `DELETE /api/v1/doctors/{doctor_id}`

**Preferences (monthly)**

* `GET  /api/v1/preferences/summary?year=&month=`
* `GET  /api/v1/preferences/{year}/{month}/{doctor_id}`
* `PUT  /api/v1/preferences/{year}/{month}/{doctor_id}/working`
* `POST /api/v1/preferences/{year}/{month}/{doctor_id}/checkpoint`
* `POST /api/v1/preferences/{year}/{month}/{doctor_id}/revert-last`
* `POST /api/v1/preferences/{year}/{month}/{doctor_id}/revert-next`
* `GET  /api/v1/preferences/deadlines/{year}/{month}`
* `PUT  /api/v1/preferences/deadlines/{year}/{month}`

**Availability (pre-flight coverage)**

* `GET /api/v1/availability/overview?year=&month=`
* `GET /api/v1/availability/{year}/{month}/{day}`

**Schedules (generate, edit, publish, diagnostics, export)**

* `POST /api/v1/schedules/generate`
* `GET  /api/v1/schedules/{year}/{month}`                      // tab view (working + pointers + diagnostics)
* `GET  /api/v1/schedules/{year}/{month}/working`              // explicit read
* `PUT  /api/v1/schedules/{year}/{month}/working`              // autosave (no checkpoint)
* `POST /api/v1/schedules/{year}/{month}/checkpoint`           // Save → new draft checkpoint (+diagnostics)
* `POST /api/v1/schedules/{year}/{month}/revert-last`          // draft UNDO
* `POST /api/v1/schedules/{year}/{month}/revert-next`          // draft REDO
* `POST /api/v1/schedules/{year}/{month}/publish`              // Publish from working (hard-rule guard, force supported)
* `POST /api/v1/schedules/{year}/{month}/revert-last-published`
* `POST /api/v1/schedules/{year}/{month}/revert-next-published`
* `GET  /api/v1/schedules/{year}/{month}/diagnostics?target=draft|published`
* `GET  /api/v1/schedules/export?year=&month=&mode=draft|published&format=xlsx|pdf`


### Error codes — summary
>
> * **401 unauthorized** — missing/invalid token.
> * **403 period_closed** — modifying past months — any mutation or pointer move outside the editing window (including published rollback).
> * **404 not_found** — entity does not exist (e.g., `doctor_id`, `year/month` with no data, `version_id`).
> * **409 cannot_undo / cannot_redo** — no suitable version in history.
> * **409 publish_blocked_by_hard_rules** — hard-rule violations prevent publishing when `force=false`.
> * **422 unprocessable_entity** — input validation errors.
> * **500 internal** — server error.
>
> **Note:** multiple domain conflicts can share HTTP **409**. Disambiguate by the JSON `detail`/`code` field in the response body.


### Undo/Redo for Preferences and Schedules — who does what (BE vs FE)

**Backend (BE) provides the big, safe steps**

* **Function:** step through **saved checkpoints** → previous / next

  * **Preferences:** **mine-only** (created by the current caller).
  * **Schedules:** **global** (single admin).
* **UX feel:** **big left/right arrows** (⟵ ⟶) that jump between **saved states** (not every keystroke).
* **APIs:** `POST /…/checkpoint`, `POST /…/revert-last`, `POST /…/revert-next` — each returns the **full current state** plus `current_checkpoint_id`, `can_undo`, `can_redo` so the UI can refresh **without an extra GET**.
  *(Schedules also have published-stream variants: `…/revert-last-published`, `…/revert-next-published`.)*
* **Scope policy:** **Preferences** keep **per-caller** (mine-only) Undo/Redo history; **Schedules** keep a **single global** history (one admin).
* **Retention (FIFO):**

  * **Preferences:** keep the **last 5** checkpoints per `{year, month, doctor_id}`.
  * **Schedules:** keep **two streams per `{year, month}`** — **5 draft checkpoints** and **5 published** snapshots (separately).

**Frontend (FE) can add micro editing comfort**

* **Function:** **Ctrl+Z / Ctrl+Y** for **tiny local edits** while typing (client-only undo/redo stack).
* **UX feel:** a **small curved arrow** for micro-Undo/Redo next to the editor; acts instantly, **no server call**.
* **Server stays the same:** FE still uses `PUT …/working` to autosave snapshots and `POST /…/checkpoint` to create a saved version.
  *(Autosave does **not** change `can_undo / can_redo`; only Save does.)*

> **Autosave vs. history (clear rule):**
>
> * `PUT …/working` (**autosave**) only writes the current **working buffer**. It **does not** create a checkpoint, **does not** prune checkpoints, and **does not** move the pointer.
> * Therefore, autosave **does not change** `can_undo` / `can_redo`.
> * **Only** `POST …/checkpoint` (**Save**) affects history: it creates a new checkpoint, **clears Redo**, **keeps Undo** (subject to FIFO=5), and updates the pointer to the new version.



## 0) Preconditions

* You can log in as **ADMIN**.
* Doctors exist in the **directory**; some **monthly preferences** may exist (or you’ll add them).
* Time zone: backend returns timestamps in **UTC**; the UI localizes them to the organization’s time zone (also used to decide whether a month is past/current/future).
> **Time semantics (clarification).** The backend stores timestamps in **UTC**, while:
>
> * month classification (**past / current / future**) and preference form **open/locked** state are evaluated in the **organization’s time zone**,
> * deadline endpoints evaluate **open/locked** in the **organization’s time zone**.

---

## 1) Login

**UI:** Open the app → fill the Login form → submit.
**API:** `POST /api/v1/auth/login` → returns `access_token` (Bearer).
Use this token for all subsequent calls.

**Request**

```http
POST /api/v1/auth/login
Content-Type: application/json
```

```json
{ "email": "admin@hospital.org", "password": "••••••••" }
```

**Response**

```json
{ "access_token": "eyJhbGciOiJIUzI1NiIs...", "token_type": "Bearer" }
```

---

## 2) Verify & edit the doctor list available for this month

### UI (Doctors Tab) — What you see

* The **doctor directory** with:

  * **Role** (Resident / Specialist),
  * **Head of Department** flag,
  * A checkbox **“Include in this month”**.
* By default, checkboxes are **selected** for all doctors with `is_active=true`.
> **Behavior note (global `is_active`).**
> The **“Include in this month”** checkbox directly maps to the **global** `is_active` field in the doctor directory. This ensures that subsequent months start from the **same pool** by default. The monthly pool passed to the generator is the current set of doctors with `is_active=true`, and its **snapshot** is stored in each generated schedule under `participant_doctor_ids`.

### What you can do

1. Tick/untick **Include in this month** to control who enters the solver pool.
2. **Filter & search** by role, name, `is_active`.
3. **CRUD** the directory (add/update/delete doctors).


---

## API

> **Note:** returning full objects keeps FE logic simple (no extra fetch).
> `is_active` powers the monthly solver pool; the checkbox UI writes it directly.

### List directory

```http
GET /api/v1/doctors?page=&size=&role=&search=&is_active=true|false|all
```

**What it does:** returns a paginated list filtered by query params.
**Response (200)**

```json
{
  "page": 1,
  "size": 20,
  "total": 132,
  "items": [
    { "id": 101, "first_name": "Anna", "last_name": "Nowak", "role": "specialist", "is_active": true, "is_head": false, "created_at": "2026-01-05T10:22:31Z", "updated_at": "2026-01-05T10:22:31Z" }
  ]
}
```

### Create

```http
POST /api/v1/doctors
Content-Type: application/json
```

**What it does:** creates a new doctor.
**Request**

```json
{ "first_name": "Anna", "last_name": "Nowak", "role": "specialist", "is_active": true, "is_head": false }
```

**Response (201)**

```json
{ "id": 101, "first_name": "Anna", "last_name": "Nowak", "role": "specialist", "is_active": true, "is_head": false, "created_at": "2026-01-05T10:22:31Z", "updated_at": "2026-01-05T10:22:31Z" }
```

### Update (full update for simplicity — PUT-first)

```http
PUT /api/v1/doctors/{doctor_id}
Content-Type: application/json
```

**What it does:** replaces the doctor record (use for toggling `is_active`, changing name/role/flags).
**Request**

```json
{ "first_name": "Anna", "last_name": "Nowak", "role": "specialist", "is_active": false, "is_head": true }
```

**Response (200)**

```json
{ "id": 101, "first_name": "Anna", "last_name": "Nowak", "role": "specialist", "is_active": false, "is_head": true, "created_at": "2026-01-05T10:22:31Z", "updated_at": "2026-01-06T09:10:00Z" }
```

> **Validation errors (422).**
> The backend returns **422** for cases such as:
>
> * directory-level constraints (e.g., unknown `role`, invalid name format),
> * required fields missing or wrong types.
>   Error format example:
>
> ```json
> { "detail": [{ "loc": ["body","role"], "msg": "unknown role", "type": "value_error" }] }
> ```


### Delete

```http
DELETE /api/v1/doctors/{doctor_id}
```

**What it does:** deletes the doctor from the directory.
**Response (204)**

> **Guideline:** Use the **checkboxes** to set who is in the monthly pool — the selected set (`participant_doctor_ids`) is passed to the solver when you click **Generate**. Deleting removes the doctor record from the db entirely.

**How the monthly pool is sent to the generator (example)**

```json
{
  "year": 2026,
  "month": 2,
  "participant_doctor_ids": [1, 2, 5, 7],
  "ignore_days": [],
  "ignore_slots": []
}
```

> `participant_doctor_ids` are also stored with each generated schedule so you can see exactly who was used for that run.


---


## 3) Review preference submissions for the target month

### UI (Preferences Tab) — What you see

* A **clear list** of doctors with **Submitted / Missing** status.
* A **deadline banner** showing the due date and **days remaining** (or **Locked** after the deadline).
* A **year/month picker** (defaults to the current month in the organization’s time zone).

### What you can do

* **Open a doctor’s form** and edit their monthly preferences for the **current or future** months (not for the past). As **ADMIN** you can also edit **after the deadline**; all changes are **tracked**.
* **Manage the deadline** — changing the date **unlocks immediately**; after the new date passes, forms **auto-lock** again.
* **Browse preference history** — open a selected doctor’s **past monthly submissions** (read-only) to review what they filed in **previous months**.
* **Undo one step (mine-only)** — go back to **your** previous saved checkpoint.
* **Redo one step (mine-only)** — go forward to **your** next saved checkpoint (available only immediately after an Undo).

---

## API

> **Data model (DB tables)**
>
> * **`preferences_working`** — one **mutable** row per `{year, month, doctor_id}` (always exists; defaults to “allow all” - a doctor is available every day, with no special wishes and no restrictions).
> * **`preferences_versions`** — **immutable checkpoints** per `{year, month, doctor_id}`(saved snapshots for undo/history).
> * **`preferences_pointers`** — **one pointer** per `{year, month, doctor_id}` → `current_checkpoint_id` (latest saved). Also stores: `submitted_at`, `submitted_by_user_id`, `submitted_by_role`, `last_admin_note`.

> **Simple rule**
>
> * **Submitted** = someone (admin/doctor) clicked **Save** → a **checkpoint** was created and the pointer moved (we set `submitted_*`).
> * **Missing** = no checkpoint yet → the **default working** (“allow all”) will be used by the generator if nothing is saved.

---

### Submission summary — *who submitted vs who is missing*

```http
GET /api/v1/preferences/summary?year=&month=
```

**What it does:** returns IDs of doctors who **submitted** (have at least one checkpoint) and who are **missing** (no checkpoint yet).
**Response (200)**

```json
{
  "year": 2026,
  "month": 2,
  "submitted": [42, 7, 9],
  "missing": [11, 13, 21],
  "last_update_at": "2026-01-05T10:22:31Z"
}
```

---

### Read the current form (working + pointer hints)

```http
GET /api/v1/preferences/{year}/{month}/{doctor_id}
```

**What it does:** returns the **current editable form** (from `preferences_working`) plus basic pointer info so the UI knows if Undo/Redo is possible.
**When are Undo/Redo enabled?**

* `can_undo = true` if there is an **earlier checkpoint by the current caller** (mine-only policy) and the period isn’t past/locked.
* `can_redo = true` only **right after an Undo** and if there is a **newer checkpoint by the current caller**; any **new Save (checkpoint)** clears redo.

**Response (200) — example (default “allow all”, not yet submitted)**

```json
{
  "doctor_id": 11,
  "year": 2026,
  "month": 2,

  "unavailable_duty_days": [],
  "unavailable_oncall_days": [],
  "preferred_duty_days": [],
  "preferred_oncall_days": [],
  "min_duties_weekdays": 0,
  "max_duties_weekdays": 999,
  "min_duties_weekends": 0,
  "max_duties_weekends": 999,
  "min_oncall_weekdays": 0,
  "max_oncall_weekdays": 999,
  "min_oncall_weekends": 0,
  "max_oncall_weekends": 999,
  "weekend_back_to_back_allowed": true,
  "preferred_partners": [],
  "comments": "",

  "status": "missing",
  "current_checkpoint_id": null,
  "submitted_at": null,
  "submitted_by_role": null,
  "last_admin_note": null,

  "can_undo": false,
  "can_redo": false
}
```

---

### Save edits to the working form (no checkpoint)

```http
PUT /api/v1/preferences/{year}/{month}/{doctor_id}/working
Content-Type: application/json
```

```json
{
  "unavailable_duty_days": [7, 14],
  "unavailable_oncall_days": [8],
  "preferred_duty_days": [10, 11],
  "preferred_oncall_days": [12],
  "min_duties_weekdays": 2,
  "max_duties_weekdays": 6,
  "min_duties_weekends": 1,
  "max_duties_weekends": 2,
  "min_oncall_weekdays": 2,
  "max_oncall_weekdays": 4,
  "min_oncall_weekends": 0,
  "max_oncall_weekends": 2,
  "weekend_back_to_back_allowed": false,
  "preferred_partners": [7],
  "comments": "avoid Mondays"
}
```

**What it does:** overwrites the **working** row only (autosave/draft edits). **Does not** create a checkpoint and **does not** mark submitted.
**Response (200)**

```json
{
  "doctor_id": 11,
  "year": 2026,
  "month": 2,
  "updated_at": "2026-01-06T09:10:00Z",
  "status": "missing",
  "current_checkpoint_id": null,
  "can_undo": false,
  "can_redo": false
}
```

**Why it exists:** FE calls this during autosave (timer or on-blur) or before leaving the page to avoid data loss. **BE doesn’t schedule autosaves**—it just accepts this PUT.
**BE does:** validates and updates `preferences_working`. Writes to **past months** → **403 `period_closed`**.
> **Validation errors (422).**
> The backend returns **422** for cases such as:
>
> * `min` > `max` for duty/on-call limits,
> * day values outside **1..31** or duplicates after normalization,
> * `preferred_partners` referencing non-existent `doctor_id`,
> * required fields missing or wrong types.
>   Error format example:
>
> ```json
> { "detail": [{ "loc": ["body","min_duties_weekdays"], "msg": "min must be ≤ max", "type": "value_error" }] }
> ```


---

### Save (create checkpoint) — *make it official & mark submitted*

```http
POST /api/v1/preferences/{year}/{month}/{doctor_id}/checkpoint
Content-Type: application/json
```

**What it does:** copies **working → versions(kind='checkpoint')**, moves the **pointer** to the new version, prunes to **last 5**, sets `submitted_*`, and **clears Redo**.
You **don’t send the form fields here**—those are already saved via the `PUT .../working`. The request body is **optional metadata only**:

```json
{ "admin_note": "Entered by admin after phone call" }
```

**Response (201)**

```json
{
  "doctor_id": 11,
  "year": 2026,
  "month": 2,

  "unavailable_duty_days": [7,14],
  "unavailable_oncall_days": [8],
  "preferred_duty_days": [10,11],
  "preferred_oncall_days": [12],
  "min_duties_weekdays": 2,
  "max_duties_weekdays": 6,
  "min_duties_weekends": 1,
  "max_duties_weekends": 2,
  "min_oncall_weekdays": 2,
  "max_oncall_weekdays": 4,
  "min_oncall_weekends": 0,
  "max_oncall_weekends": 2,
  "weekend_back_to_back_allowed": false,
  "preferred_partners": [7],
  "comments": "avoid Mondays",

  "status": "submitted",
  "current_checkpoint_id": "pref_rev_2026-02-01T10:15:00Z",
  "submitted_at": "2026-02-01T10:15:00Z",
  "submitted_by_user_id": 101,
  "submitted_by_role": "admin",

  "can_undo": true,
  "can_redo": false
}
```

**BE does:** persists snapshot, rotates old checkpoints (keep 5). Past months → **403 `period_closed`**.

---


### Undo one step (go back to your previous checkpoint)

```http
POST /api/v1/preferences/{year}/{month}/{doctor_id}/revert-last
Content-Type: application/json
```

**Request body:** *(none)*

**What it does:** moves the pointer to the **previous checkpoint** authored by the **caller**, overwrites `preferences_working`, **and returns the full current form (working snapshot + pointer hints)** so the FE can refresh without an extra `GET`.


**Response (200)**

```json
{
  "doctor_id": 11,
  "year": 2026,
  "month": 2,

  "unavailable_duty_days": [7,14],
  "unavailable_oncall_days": [8],
  "preferred_duty_days": [10,11],
  "preferred_oncall_days": [12],
  "min_duties_weekdays": 2,
  "max_duties_weekdays": 6,
  "min_duties_weekends": 1,
  "max_duties_weekends": 2,
  "min_oncall_weekdays": 2,
  "max_oncall_weekdays": 4,
  "min_oncall_weekends": 0,
  "max_oncall_weekends": 2,
  "weekend_back_to_back_allowed": false,
  "preferred_partners": [7],
  "comments": "avoid Mondays",

  "reverted_at": "2026-02-01T11:00:00Z",
  "current_checkpoint_id": "pref_rev_2026-01-28T09:58:00Z",
  "current_created_by_role": "admin",
  "current_created_by_user_id": 101,
  "current_created_at": "2026-01-28T09:58:00Z",
  "can_undo": true,
  "can_redo": true
}
```

**Errors:**

* `409 cannot_undo` — there is **no earlier checkpoint by this caller**.
* `403 period_closed` — past months are read-only.

---

### Redo one step (next checkpoint by the same author)

```http
POST /api/v1/preferences/{year}/{month}/{doctor_id}/revert-next
Content-Type: application/json
```

**Request body:** *(none)*

**What it does:** moves the pointer to the **next newer** checkpoint by the **caller**, overwrites `preferences_working`, **and returns the full current form**, so the FE can refresh without an extra GET.

**Response (200)**


```json
{
  "doctor_id": 11,
  "year": 2026,
  "month": 2,

  "unavailable_duty_days": [7,14],
  "unavailable_oncall_days": [8],
  "preferred_duty_days": [10,11],
  "preferred_oncall_days": [12],
  "min_duties_weekdays": 2,
  "max_duties_weekdays": 6,
  "min_duties_weekends": 1,
  "max_duties_weekends": 2,
  "min_oncall_weekdays": 2,
  "max_oncall_weekdays": 4,
  "min_oncall_weekends": 0,
  "max_oncall_weekends": 2,
  "weekend_back_to_back_allowed": false,
  "preferred_partners": [7],
  "comments": "avoid Mondays",

  "reverted_at": "2026-02-01T11:02:00Z",
  "current_checkpoint_id": "pref_rev_2026-02-01T10:15:00Z",
  "current_created_by_role": "admin",
  "current_created_by_user_id": 101,
  "current_created_at": "2026-02-01T10:15:00Z",
  "can_undo": true,
  "can_redo": false
}
```

**Errors:**

* `409 cannot_redo` — there is **no newer checkpoint by this caller**.
* `403 period_closed` — past months are read-only.

**Behavioral note:** Creating a **new checkpoint** (Save) **clears Redo** until you Undo again.

---

### Deadline for the period — *single resource, PUT-as-upsert*

```http
GET /api/v1/preferences/deadlines/{year}/{month}
```

**What it does:** returns the current deadline and status (`open`/`locked`).
**Response (200)**

```json
{ "year": 2026, "month": 2, "deadline": "2026-01-20T23:59:59Z", "status": "open", "org_timezone": "Europe/Warsaw" }
```

```http
PUT /api/v1/preferences/deadlines/{year}/{month}
Content-Type: application/json
```

**What it does:** **creates or updates** the deadline; changing it **unlocks immediately**.
**Request**

```json
{ "deadline": "2026-01-22T23:59:59Z" }
```

**Response (200/201)**

```json
{ "year": 2026, "month": 2, "deadline": "2026-01-22T23:59:59Z", "status": "open", "org_timezone": "Europe/Warsaw" }
```

> **Open/locked evaluation.**
> Whether a deadline has passed (thus **locked**) is evaluated in the **organization’s time zone**. Changing the deadline **immediately unlocks** forms, and after the new deadline passes the system will **auto-lock** them again.

**BE does:** evaluates in the org timezone; after the new deadline passes, forms **auto-lock** (`locked`). Writes to past periods → **403 `period_closed`** unless audited ADMIN override is allowed.

---

### What the generator uses

* If there is **at least one checkpoint** → it uses the **pointer’s checkpoint** (current).
* If **no checkpoint** yet → it uses the **working** (which starts as **“allow all”**).

---


## 4) Generate new schedule

### UI (Generate New Schedule Tab) — What you see

* **Year/month selection** (defaults to current; sets `{year,month}` for the rest of the flow).
* **Solver input summary** for the month:

  * Read-only list of currently active doctors (`is_active=true`). To change it, go to **Doctors**.
  * **Pre-flight coverage check**:

    * A calendar with daily counts of available **specialists** and **residents**.
    * Color warnings:

      * **Impossible** (e.g., no specialist) — Red
      * **Risky** — Yellow
      * **OK** — Green
* Buttons: **Edit Doctors**, **Fix Preferences / Change Availability**, **Generate Schedule**.

### What you can do

* Use **Edit Doctors** to adjust the pool in the Doctors tab.

* Hover/click a day to see available names by role.

* If a day is risky or impossible:

  * **Fix preferences** (navigate to Preferences), or
  * **Acknowledge gaps** and let the solver **skip** certain days/slots via `ignore_*`.

* **Solver under the hood**

  * Load doctors + preferences
  * Build **hard constraints**
  * Optimize **soft goals**
  * Optionally apply heuristics

* When generation finishes, the UI navigates to the **Schedules** screen.

### API

* **Active doctors (read-only list)**
  `GET /api/v1/doctors?is_active=true&role=&search=&page=&size=`

* **Monthly availability overview**
> **Risk enum (availability).**
> `risk ∈ { "ok", "alert", "critical"}`
>
> * **ok** — sufficient numbers of both roles,
> * **alert** — low availability - generally low counts but still may be feasible,
> * **critical** — only one doctor available **or** **zero** specialists available **or** no one available; impossible to cover the day


  ```http
  GET /api/v1/availability/overview?year=&month=
  ```

  ```json
  {
    "days": [
      { "day": 1,  "available_specialists": 5, "available_residents": 6, "risk": "ok" },
      { "day": 10, "available_specialists": 1, "available_residents": 1, "risk": "alert" },
      { "day": 12, "available_specialists": 0, "available_residents": 2, "risk": "critical" },
      { "day": 20, "available_specialists": 1, "available_residents": 0, "risk": "critical" }
    ]
  }
  ```

* **Daily availability drill-down**

  ```http
  GET /api/v1/availability/{year}/{month}/{day}
  ```

  ```json
  {
    "day": 12,
    "specialists": [],
    "residents":   [{ "id": 3, "first_name": "Ola", "last_name": "Nowicka" }],
    "risk": "critical"
    }
  ```



* **Generate schedule**

  ```http
  POST /api/v1/schedules/generate
  Content-Type: application/json
  ```

  ```json
  {
    "year": 2026,
    "month": 2,
    "participant_doctor_ids": [1, 2, 5, 7],
    "ignore_days": [15],
    "ignore_slots": [
      { "day": 12, "shift_type": "on_duty" },
      { "day": 20, "shift_type": "on_call" }
    ]
  }
  ```
**What it does (for current/future months only):**

1. Runs the solver, writes **`schedule_working`** for `{year,month}`.
2. **Automatically** creates the **first `draft_checkpoint`** from the just-created working and sets `current_draft_version_id` to it (FIFO 5, clear redo).

**Response (201)**

```json
{
  "year": 2026,
  "month": 2,
  "status": "draft",
  "working": {
    "participant_doctor_ids": [1,2,5,7],
    "assignments": [ /* generated */ ],
    "meta": { "labels": ["as_generated"] },
    "updated_at": "2026-02-01T10:12:00Z"
  },
  "draft": {
    "current_checkpoint_id": "schv_2026_02_0001",
    "checkpoints_count": 1,
    "can_undo": false,
    "can_redo": false,
    "payload": {
      "participant_doctor_ids": [1,2,5,7],
      "assignments": [ /* generated */ ],
      "meta": { "labels": ["as_generated"], "exceptions": [] }
    }
  },
 "diagnostics": {
   "for_version_id": "schv_2026_02_0001",
   "computed_at": "2026-02-01T10:12:01Z",
   "summary": { /* initial metrics for the generated draft */ }
  }
}
```

**Errors**

* `403 period_closed` (past)
* `422 unprocessable_entity` (invalid inputs)


### After generate → Schedules Tab

> Generate returns a `ScheduleRead` with `status="draft"`. The UI **navigates to the Schedules tab** to show the newly created draft.

---

## 5) Schedules Tab — view, edit, diagnose, publish, export

### UI — What you see

* **Year/month picker** to browse schedules. *“Current month” = the month that is ongoing in the organization’s time zone.*
* The **current schedule** for the selected period with a **status badge** (Draft / Published).
  * For **current** and **future** months:
    * show **Draft** by default and allow switching between **Draft / Published**, if both exist (toggle disappears if not)
    * editable **Draft** + buttons **Save** (make a new checkpoint) and **Publish** (make visible to doctors)
    * if admin switches to **Published**: show **Edit** button only (creates a new draft from live and it becomes editable)
  * For **past** months show **Published** if exists, else Draft, but all **read-only** (no edit, save, publish buttons).
* **Diagnostics** for the displayed schedule:

  * Penalty / total cost (soft violations)
  * Rest-rule violations
  * Fairness / workload balance
  * Coverage flags (under-staffed days)
  * Preference fulfillment
* **Download** button (XLSX; optional PDF).

### What you can do

1. **Edit the draft** (current/future only): change assignments, then **Save** to create a **checkpoint**, undo and redo changes; diagnostics refresh automatically.
2. **Publish** the draft so doctors can see it. If a **hard rule** is broken, a **red warning modal** appears after clicking Publish button; explicit confirmation is required from admin. Accepted exceptions go to `meta.exceptions[]`.
3. If a published schedule has an issue:

   * **Undo (instant rollback)** → move published pointer back to previous **published**.
   * **Edit published (hotfix flow)** → **Edit** creates a draft from live; fix, **Save** (checkpoint), then **Publish** again. Old live remains visible until you publish the fix.
4. **Download** XLSX (PDF optional) — for both Draft and Published.
5. **Browse history** — for the selected month, allow viewing:
    - **Draft history** (last ≤5 draft checkpoints), and
    - **Published history** (last ≤5 publications).
      In past months both streams are **read-only**. The **latest draft** may or may not match the **latest published** (draft is a working state and could include unpublished changes).


---

### API for the Schedules Tab

> The endpoints below follow the **working + checkpoints + pointers** data model (DB tables):
>
> * **`schedule_working`** — mutable working draft, one row per `{year,month}` (exists only when a draft is being edited or after generate)
> * **`schedule_versions`** — immutable snapshots per `{year, month}`(`draft_checkpoint` / `published`)
> * **`schedule_pointers`** — pointers to *current* draft and *current* published => two **pointers** per `{year, month}`
> * **`schedule_diagnostics`** — cache **per version** (only for checkpoints and published)


The Schedule API reflects the rules:

* **No edits/undo/redo/publish after the period closes** (00:00 on the first day of the next month in the org timezone). Allowed in past months: **read + export** only
* **Generate** writes **working** and **automatically creates the first draft checkpoint** (and points the draft pointer there).
* **Publish** is taken **from working**.
* **Diagnostics are stored per version** (both **draft checkpoints** and **published**).
  They are computed on **Save/Publish** and cached per `version_id`.
  If the cache is missing, the backend computes them **lazily on first fetch**, persists, and returns.

* **Pointers live per `{year, month}`** (no `sid`).
* **Separate pointer & FIFO(5)** for **draft checkpoints** and for **published**.
* **Single admin** (global UNDO/REDO).

#### 1) Get the “current schedule” for a period (single call for the tab)

```http
GET /api/v1/schedules/{year}/{month}
```

**What it does:**
Returns a **period view** for the Schedules tab:

* the **working** (only for current/future),
* the **current draft checkpoint** (via pointer),
* the **current published** (via pointer),
* **diagnostics for the current draft checkpoint** (if any),
* UI hints: **what is editable** and **can_undo/can_redo** for both pointers.

**Response (200)**

```json
{
  "year": 2026,
  "month": 2,
  "org_timezone": "Europe/Warsaw",
  "period_status": "current",                     // "past" | "current" | "future"

  "view": {
    "default_mode": "draft",                      // UI hint
    "toggle_available": true                      // if both draft and published exist (current/future only)
  },

  "working": {                                    // present only for current/future when working exists
    "exists": true,
    "participant_doctor_ids": [1,2,5,7],
    "assignments": [ /* ... */ ],
    "meta": { "labels": ["as_generated"] },
    "updated_at": "2026-02-01T10:20:00Z"
  },

  "draft": {                                      // current draft checkpoint snapshot via pointer (nullable)
    "current_checkpoint_id": "schv_2026_02_0003",
    "checkpoints_count": 1,                       // max 5
    "can_undo": false,
    "can_redo": false,
    "payload": {
      "participant_doctor_ids": [1,2,5,7],
      "assignments": [ /* ... */ ],
      "meta": { "labels": ["as_generated"], "exceptions": [] }
    }
  },

  "published": {                                  // current published snapshot via pointer (nullable)
    "current_published_id": null,
    "publications_count": 0,                      // max 5
    "can_undo": false,
    "can_redo": false,
    "payload": null
  },

  "diagnostics": {                                // diagnostics of the current draft checkpoint (if any)
    "for_version_id": "schv_2026_02_0003",
    "computed_at": "2026-02-01T10:15:02Z",
    "summary": {
      "penalty_total": 42,
      "understaffed_days": 1,
      "rest_violations": 0,
      "fairness_index": 0.92,
      "preference_fulfillment_pct": 86.5
    }
  }
}
```

**Errors**

* `404 not_found` — no data at all for that period.
* `401 unauthorized`

---

#### 2) Read/Autosave the working draft
##### Read working (explicit)

```http
GET /api/v1/schedules/{year}/{month}/working
```

**Response (200)**

```json
{
  "year": 2026,
  "month": 2,
  "exists": true,
  "participant_doctor_ids": [1,2,5,7],
  "assignments": [ /* ... */ ],
  "meta": { "labels": ["as_generated"] },
  "updated_at": "2026-02-01T11:01:00Z"
}
```

**Errors:** `404 not_found` (no working yet), `401`

---

##### Save edits to working (autosave; no checkpoint)

```http
PUT /api/v1/schedules/{year}/{month}/working
Content-Type: application/json
```

**Request**

```json
{
  "assignments": [ /* edited in UI */ ],
  "meta": { "labels": ["as_generated","touched"] }
}
```

**What it does:** overwrites the **working** row only. No diagnostics. No checkpoint.

**Response (200)**

```json
{
  "year": 2026,
  "month": 2,
  "updated_at": "2026-02-01T11:05:30Z"
}
```

**Errors**

* `403 period_closed` (past)
* `422 unprocessable_entity` (shape/validation)

---

#### 3) Save (create **draft checkpoint**) — computes diagnostics

```http
POST /api/v1/schedules/{year}/{month}/checkpoint
Content-Type: application/json
```

**Request (optional note)**

```json
{ "note": "manual tweak day 12 on-call" }
```

**What it does (current/future only):**
Copies **working → schedule_versions(kind='draft_checkpoint')**, sets the **draft pointer** to the new version, **clears Redo**, prunes to **last 5**, and **computes diagnostics** for this version.

**Response (201)**

```json
{
  "year": 2026,
  "month": 2,

  "draft": {
    "current_checkpoint_id": "schv_2026_02_0002",
    "checkpoints_count": 2,
    "can_undo": true,
    "can_redo": false,
    "payload": {
      "participant_doctor_ids": [1,2,5,7],
      "assignments": [ /* working snapshot at save */ ],
      "meta": { "labels": ["as_generated","touched"], "exceptions": [] }
    }
  },

  "diagnostics": {
    "for_version_id": "schv_2026_02_0002",
    "computed_at": "2026-02-01T11:06:00Z",
    "summary": {
      "penalty_total": 38,
      "understaffed_days": 0,
      "rest_violations": 0,
      "fairness_index": 0.94,
      "preference_fulfillment_pct": 88.0
    }
  }
}
```

**Errors**

* `403 period_closed`
* `422 unprocessable_entity`

---

#### 4) Draft UNDO / REDO (pointer moves + working overwrite)

##### UNDO one step (to previous draft checkpoint)

```http
POST /api/v1/schedules/{year}/{month}/revert-last
```

**Request body:** *(none)*

**What it does:** Moves the **draft pointer** to the previous `draft_checkpoint`, **overwrites working** from that snapshot, returns the **full current draft** + diagnostics.

**Response (200)**

```json
{
  "year": 2026,
  "month": 2,

  "draft": {
    "current_checkpoint_id": "schv_2026_02_0001",
    "checkpoints_count": 2,
    "can_undo": false,
    "can_redo": true,
    "payload": {
      "participant_doctor_ids": [1,2,5,7],
      "assignments": [ /* snapshot of 0001 */ ],
      "meta": { "labels": ["as_generated"], "exceptions": [] }
    }
  },

  "working": {
    "participant_doctor_ids": [1,2,5,7],
    "assignments": [ /* now equals 0001 */ ],
    "meta": { "labels": ["as_generated"] },
    "updated_at": "2026-02-01T11:07:00Z"
  },

  "diagnostics": {
    "for_version_id": "schv_2026_02_0001",
    "computed_at": "2026-02-01T10:15:02Z",
    "summary": {
      "penalty_total": 42,
      "understaffed_days": 1,
      "rest_violations": 0,
      "fairness_index": 0.92,
      "preference_fulfillment_pct": 86.5
    }
  }
}
```

**Errors**

* `409 cannot_undo` — no older checkpoint
* `403 period_closed`

---

##### REDO one step (to next draft checkpoint)

```http
POST /api/v1/schedules/{year}/{month}/revert-next
```

**Request body:** *(none)*

**What it does:** Moves the **draft pointer** to the next `draft_checkpoint`, **overwrites working**, returns the **current draft** + diagnostics.

**Response (200)**

```json
{
  "year": 2026,
  "month": 2,

  "draft": {
    "version_id": "schv_2026_02_0002",
    "checkpoints_count": 2,
    "can_undo": true,
    "can_redo": false,
    "payload": {
      "participant_doctor_ids": [1,2,5,7],
      "assignments": [ /* snapshot of 0002 */ ],
      "meta": { "labels": ["as_generated","touched"], "exceptions": [] }
    }
  },

  "working": {
    "participant_doctor_ids": [1,2,5,7],
    "assignments": [ /* now equals 0002 */ ],
    "meta": { "labels": ["as_generated","touched"] },
    "updated_at": "2026-02-01T11:08:00Z"
  },

  "diagnostics": {
    "version_id": "schv_2026_02_0002",
    "computed_at": "2026-02-01T11:06:00Z",
    "summary": {
      "penalty_total": 38,
      "understaffed_days": 0,
      "rest_violations": 0,
      "fairness_index": 0.94,
      "preference_fulfillment_pct": 88.0
    }
  }
}
```

**Errors**

* `409 cannot_redo`
* `403 period_closed`

---

#### 5) Publish (from working) with hard-rule guard

```http
POST /api/v1/schedules/{year}/{month}/publish
Content-Type: application/json
```

**Request**

```json
{
  "force": false,
  "note": "finalize February",
  "accepted_exceptions": []    // when force=true, backend will persist into payload.meta.exceptions[]
}
```

**What it does (current/future only):**

* Validates **hard rules** on the **current working**.
  * If violations and `force=false` → **409** with `detail="publish_blocked_by_hard_rules"` and a `violations[]` list (see below).
  * If the admin confirms in the UI, call **again with `force=true`** and **`accepted_exceptions[]`**:
     - Backend verifies that accepted exceptions match the detected violations,
     - Persists them into `payload.meta.exceptions[]` with user and timestamp,
     - Creates a **published** version from working, updates the **published pointer**, prunes to **last 5**.


**Response (201)**

```json
{
  "year": 2026,
  "month": 2,
  "published": {
    "current_published_id": "schv_2026_02_0101",
    "audit": {
      "published_at": "2026-02-01T11:20:00Z",
      "published_by_user_id": 101,
      "note": "Exceptional staffing shortage due to flu wave."
    },
    "publications_count": 1,
    "can_undo": false,
    "can_redo": false,
    "payload": {
      "participant_doctor_ids": [1,2,5,7],
      "assignments": [ /* working at publish time */ ],
      "meta": { "labels": ["as_generated","touched"], "exceptions": [] }
    }
  }
}
```


**Errors**

* `403 period_closed`
* `422 unprocessable_entity`
* `409 publish_blocked_by_hard_rules`:

**Error (first attempt, `force=false`):** - example error body

```
 {
   "detail": "publish_blocked_by_hard_rules",
   "violations": [
     { "code": "NO_SPECIALIST_DAY_12", "message": "No specialist on 12th" },
     { "code": "MAX_CONSEC_ONCALL_EXCEEDED_DAY_20", "message": "Exceeded consecutive on-call limit on 20th" }
   ]
 }
```

**Confirmed publish (second attempt, `force=true`):** - example request body

```
 {
   "force": true,
   "note": "Exceptional staffing shortage due to flu wave.",
   "accepted_exceptions": [
     { "code": "NO_SPECIALIST_DAY_12", "justification": "Clinic closed AM; ER covered by on-call specialist." },
     { "code": "MAX_CONSEC_ONCALL_EXCEEDED_DAY_20", "justification": "Doctor volunteered; union rep informed." }
   ]
 }
```

**Published response fragment (`meta.exceptions[]` persisted):** - example response excerpt

```
 "payload": {
   "meta": {
     "labels": ["as_generated","touched"],
     "exceptions": [
       { "code": "NO_SPECIALIST_DAY_12", "justification": "Clinic closed AM; ER covered by on-call specialist.", "accepted_by_user_id": 101, "accepted_at": "2026-02-01T11:20:00Z" },
       { "code": "MAX_CONSEC_ONCALL_EXCEEDED_DAY_20", "justification": "Doctor volunteered; union rep informed.", "accepted_by_user_id": 101, "accepted_at": "2026-02-01T11:20:00Z" }
     ]
   }
 }
```
---

#### 6) Published rollback / redo (only within the editing window)

##### Rollback one published (pointer move to previous published)

```http
POST /api/v1/schedules/{year}/{month}/revert-last-published
```

**Request body:** *(none)*

**Response (200)**

```json
{
  "year": 2026,
  "month": 2,
  "published": {
    "current_published_id": "schv_2026_02_0100",
    "publications_count": 2,
    "can_undo": false,
    "can_redo": true,
    "payload": {
      "participant_doctor_ids": [1,2,5,7],
      "assignments": [ /* snapshot of 0100 */ ],
      "meta": { "labels": ["as_generated","touched"], "exceptions": [] }
    }
  }
}
```

**Errors**

* `409 cannot_undo`
* `403 period_closed` (cannot rollback in past)

---

##### Redo one published (pointer move to next published)

```http
POST /api/v1/schedules/{year}/{month}/revert-next-published
```

**Request body:** *(none)*

**Response (200)**

```json
{
  "year": 2026,
  "month": 2,
  "published": {
    "current_published_id": "schv_2026_02_0101",
    "publications_count": 2,
    "can_undo": true,
    "can_redo": false,
    "payload": {
      "participant_doctor_ids": [1,2,5,7],
      "assignments": [ /* snapshot of 0101 */ ],
      "meta": { "labels": ["as_generated","touched"], "exceptions": [] }
    }
  }
}
```

**Errors**

* `409 cannot_redo`
* `403 period_closed`

---

#### 7) Diagnostics (fetch)

> Diagnostics are **per version** (checkpoint or published).
> For **working** we **do not compute** diagnostics.

```http
GET /api/v1/schedules/{year}/{month}/diagnostics?target=draft|published
```

* `target=draft` → uses the draft pointer (`current_checkpoint_id`)
* `target=published` → uses the published pointer (`current_published_id`)



**Response (200)**

```json
{
  "version_id": "schv_2026_02_0002",
  "computed_at": "2026-02-01T11:06:00Z",
  "summary": {
    "penalty_total": 38,
    "understaffed_days": 0,
    "rest_violations": 0,
    "fairness_index": 0.94,
    "preference_fulfillment_pct": 88.0
  },
  "details": { /* only if you want to expose */ }
}
```

**Errors**

* `404 not_found` (no pointer / no version)
* `401 unauthorized`

> If the diagnostics cache is missing for that `version_id`, the backend **computes it now**, persists, and returns.
> This applies to **both** draft checkpoints **and** published versions.

---

#### 8) Export (XLSX / PDF)

```http
GET /api/v1/schedules/export?year=&month=&mode=draft|published&format=xlsx|pdf
```

**What it does:**

* `mode=draft` → exports from **working**.
* `mode=published` → exports from **current published**.

**Response (200)**
Binary stream (file download). No diagnostics included.

**Errors**

* `404 not_found` (no working/published for the chosen mode)
* `401 unauthorized`

---
