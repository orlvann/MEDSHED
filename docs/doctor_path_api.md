# Doctor Path – API (Coming soon)

This document will define the doctor-facing workflow & endpoints aligned with Admin Path.


# **Doctor Path – Monthly Preferences & Published Schedules**

## General Overview

### Full Doctor View at a Glance

1. **Login**
2. **Preferences Tab:** fill/edit **my** monthly preferences (current & future months); Undo/Redo is **mine-only**; deadline-aware.
3. **Schedules Tab:** browse **published** schedules by `{year,month}`; view my shifts; download PDF/XLSX/ICS.

---

## Endpoints Overview (Doctor)

**Auth**

* `POST /api/v1/auth/login`

**Preferences (mine)**

* `GET  /api/v1/preferences/{year}/{month}/me`
* `PUT  /api/v1/preferences/{year}/{month}/me/working`                 // autosave (no checkpoint)
* `POST /api/v1/preferences/{year}/{month}/me/checkpoint`              // Save → new checkpoint
* `POST /api/v1/preferences/{year}/{month}/me/revert-last`             // UNDO (mine-only)
* `POST /api/v1/preferences/{year}/{month}/me/revert-next`             // REDO (mine-only)
* `GET  /api/v1/preferences/deadlines/{year}/{month}`

**Schedules (published only, read-only)**

* `GET  /api/v1/schedules/{year}/{month}/published`
* `GET  /api/v1/schedules/{year}/{month}/diagnostics?target=published`
* `GET  /api/v1/schedules/{year}/{month}/my-assignments`
* `GET  /api/v1/schedules/export?year=&month=&mode=published&format=xlsx|pdf|ics`

> `doctor_id` is inferred from the token for all `/me` endpoints and for `my-assignments`/`export?format=ics`.

---

## Error Codes — Summary

* **401 unauthorized** — missing/invalid token.
* **403 period_closed** — any mutation for past months is forbidden.
* **404 not_found** — entity not found (e.g., no published schedule for a period).
* **409 cannot_undo / cannot_redo** — no suitable version in history.
* **422 unprocessable_entity** — input validation errors.
* **500 internal** — server error.

> Error bodies include a machine-readable `code` (e.g., `"period_closed"`, `"cannot_undo"`) and optional `context`.

---

## Undo/Redo for Preferences — Scope & Behavior

**Backend (BE) provides safe, coarse steps**

* **Scope:** **mine-only** — the Undo/Redo stream contains **only** checkpoints created by the current doctor.
* **APIs:** `POST …/checkpoint`, `POST …/revert-last`, `POST …/revert-next` — each returns the **full current form** plus `version_id`, `can_undo`, `can_redo`.
* **Retention:** keep the **last 5** checkpoints per `{year,month,doctor_id}` (FIFO).

**Frontend (FE) may add micro comfort**

* Local Ctrl+Z/Ctrl+Y while typing (client-only stack).
* FE still uses `PUT …/working` for autosave; **autosave does not change** `can_undo / can_redo`.

> **Clear rule:**
> `PUT …/working` updates the **working** row only (no checkpoint, no pointer move, no redo pruning).
> `POST …/checkpoint` creates a checkpoint, **clears redo**, prunes to **last 5**, moves the pointer.

---

## 0) Preconditions

* You can log in with **role = DOCTOR**.
* The admin may configure a **preferences submission deadline** per month.
* BE stores timestamps in **UTC**; UI renders in **`org_timezone`**.
  Month classification (**past/current/future**) and **open/locked** state for preferences are evaluated in `org_timezone`.

---

## 1) Login

**API**

```http
POST /api/v1/auth/login
Content-Type: application/json
```

**Request**

```json
{ "email": "doctor@hospital.org", "password": "••••••••" }
```

**Response**

```json
{ "access_token": "eyJhbGciOiJIUzI1NiIs...", "token_type": "Bearer" }
```

Use `Authorization: Bearer <token>` for all subsequent calls.

---

## 2) Preferences Tab — My Monthly Preferences

### UI — What I see

* **Year/Month picker** — defaults to the **current** month (in `org_timezone`).
* **Deadline banner** — e.g., “**5 days left** · Deadline: 2026-01-22 23:59:59 (Europe/Warsaw)”.
* **Status**: `missing` (no checkpoint yet) or `submitted` (at least one checkpoint).
* An editable form for **current/future** months (past months are read-only):

  * `unavailable_duty_days`, `unavailable_oncall_days`
  * `preferred_duty_days`, `preferred_oncall_days`
  * `min_*` / `max_*` for duty/on-call on weekdays/weekends
  * `weekend_back_to_back_allowed` (bool)
  * `preferred_partners` (doctor IDs)
  * `comments` (string)
* Default working state is **“allow all”** (fully available every day).
* **Buttons:** Autosave (implicit via PUT); **Save** (creates checkpoint); **Undo/Redo** (mine-only).

### API — Preferences (Doctor)

> **Data model (same as Admin Path):**
>
> * `preferences_working` — one mutable row per `{year,month,doctor_id}`
> * `preferences_versions` — immutable checkpoints
> * `preferences_pointers` — pointer per `{year,month,doctor_id}` → `version_id`, plus `submitted_*`
>   **Day-list normalization:** server enforces unique, sorted, range **1..31**; invalid → **422**.

#### A) Read current form (working + pointer hints)

```http
GET /api/v1/preferences/{year}/{month}/me
```

**Response (200)**

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
  "version_id": null,
  "submitted_at": null,
  "submitted_by_role": null,

  "can_undo": false,
  "can_redo": false,
  "org_timezone": "Europe/Warsaw",
  "period_status": "current"   // "past" | "current" | "future"
}
```

**Errors:** `401`

---

#### B) Autosave (no checkpoint)

```http
PUT /api/v1/preferences/{year}/{month}/me/working
Content-Type: application/json
```

**Request (example)**

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

**Response (200)**

```json
{
  "doctor_id": 11,
  "year": 2026,
  "month": 2,
  "updated_at": "2026-01-06T09:10:00Z",
  "status": "missing",
  "version_id": null,
  "can_undo": false,
  "can_redo": false,
  "processed_at": "2026-01-06T09:10:00Z"
}
```

**Errors:**

* `403 period_closed` (past months are read-only)
* `422 unprocessable_entity` (e.g., `min > max`, invalid day values, non-existent partner IDs)

---

#### C) Save (create checkpoint)

```http
POST /api/v1/preferences/{year}/{month}/me/checkpoint
Content-Type: application/json
```

**Request (optional)**

```json
{ "note": "Submitted by doctor" }
```

**Server behavior:** copy **working → versions(kind='checkpoint')**, move pointer, **clear redo**, prune to **last 5**, set `submitted_*`.

**Response (201)**

```json
{
  "doctor_id": 11,
  "year": 2026,
  "month": 2,

  "status": "submitted",
  "version_id": "prefv_2026_02_doctor11_0001",
  "submitted_at": "2026-02-01T10:15:00Z",
  "submitted_by_user_id": 11,
  "submitted_by_role": "doctor",

  "can_undo": true,
  "can_redo": false,
  "processed_at": "2026-02-01T10:15:00Z"
}
```

**Errors:** `403 period_closed`, `422`

---

#### D) Undo one step (mine-only)

```http
POST /api/v1/preferences/{year}/{month}/me/revert-last
```

**Body:** *(none)*
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
  "weekend_back_to_back_allowed": false,
  "preferred_partners": [7],
  "comments": "avoid Mondays",

  "reverted_at": "2026-02-01T11:00:00Z",
  "version_id": "prefv_2026_02_doctor11_0000",
  "current_created_by_role": "doctor",
  "current_created_by_user_id": 11,
  "current_created_at": "2026-01-28T09:58:00Z",
  "can_undo": true,
  "can_redo": true
}
```

**Errors:** `409 cannot_undo`, `403 period_closed`

---

#### E) Redo one step (mine-only)

```http
POST /api/v1/preferences/{year}/{month}/me/revert-next
```

**Body:** *(none)*
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
  "weekend_back_to_back_allowed": false,
  "preferred_partners": [7],
  "comments": "avoid Mondays",

  "reverted_at": "2026-02-01T11:02:00Z",
  "version_id": "prefv_2026_02_doctor11_0001",
  "current_created_by_role": "doctor",
  "current_created_by_user_id": 11,
  "current_created_at": "2026-02-01T10:15:00Z",
  "can_undo": true,
  "can_redo": false
}
```

**Errors:** `409 cannot_redo`, `403 period_closed`
**Note:** A new **Save** (checkpoint) after Redo **clears Redo**.

---

#### F) Deadline — read

```http
GET /api/v1/preferences/deadlines/{year}/{month}
```

**Response (200)**

```json
{
  "year": 2026,
  "month": 2,
  "deadline": "2026-01-22T23:59:59Z",
  "status": "open",
  "org_timezone": "Europe/Warsaw"
}
```

**Errors:** `401`, `404` (if not configured; recommended: always return a resource)

---

## 3) Schedules Tab — Browse Published Schedules

### UI — What I see

* **Year/Month picker** — defaults to the **current** month.
* **Status badge**: “Published” (if exists) or “No published schedule yet”.
* Calendar/table of **published** assignments: `on_duty` and `on_call`. My shifts are highlighted.
* Optional **My Summary** panel (from diagnostics): assigned vs. preferred, weekends worked, etc.
* **Download**: XLSX/PDF (full schedule) and ICS (my personal calendar).

### API — Schedules (Doctor, read-only)

> **Data model (same as Admin Path):**
>
> * `schedule_versions` (both `draft_checkpoint` and `published`)
> * `schedule_pointers` (doctor uses the **published** pointer only)
> * `schedule_diagnostics` (cached per `version_id`)
>   There is **at most one published** per `{year,month}`.

#### 1) Read published schedule for a period

```http
GET /api/v1/schedules/{year}/{month}/published
```

**Response (200)**

```json
{
  "year": 2026,
  "month": 2,
  "org_timezone": "Europe/Warsaw",
  "period_status": "current",

  "published": {
    "version_id": "schv_2026_02_0101",
    "publications_count": 1,
    "payload": {
      "participant_doctor_ids": [1,2,5,7],
      "assignments": [
        { "day": 1,  "shift_type": "on_duty", "doctor_id": 11 },
        { "day": 3,  "shift_type": "on_call", "doctor_id": 11 },
        { "day": 12, "shift_type": "on_duty", "doctor_id": 7  }
      ],
      "meta": {
        "labels": ["as_generated","touched"],
        "exceptions": [
          {
            "code": "NO_SPECIALIST_DAY_12",
            "justification": "Clinic closed AM; ER covered by on-call specialist.",
            "accepted_by_user_id": 101,
            "accepted_at": "2026-02-01T11:20:00Z"
          }
        ]
      }
    }
  }
}
```

**Errors:** `404 not_found` (no published), `401`

---

#### 2) Diagnostics (published)

```http
GET /api/v1/schedules/{year}/{month}/diagnostics?target=published
```

**Response (200)**

```json
{
  "version_id": "schv_2026_02_0101",
  "computed_at": "2026-02-01T11:20:05Z",
  "summary": {
    "penalty_total": 38,
    "understaffed_days": 0,
    "rest_violations": 0,
    "fairness_index": 0.94,
    "preference_fulfillment_pct": 88.0
  }
}
```

**Errors:** `404 not_found`, `401`

---

#### 3) My assignments (from the published version)

```http
GET /api/v1/schedules/{year}/{month}/my-assignments
```

**Response (200)**

```json
{
  "doctor_id": 11,
  "year": 2026,
  "month": 2,
  "assignments": [
    { "day": 1, "shift_type": "on_duty" },
    { "day": 3, "shift_type": "on_call" }
  ]
}
```

**Errors:** `404 not_found` (no published), `401`

---

#### 4) Export (XLSX / PDF / ICS)

```http
GET /api/v1/schedules/export?year=&month=&mode=published&format=xlsx|pdf|ics
```

**Semantics**

* `mode=published` → exports from the **current published** pointer.
* `format=ics` → **personal ICS**, filtered by `doctor_id=me` (from token; param `doctor_id` ignored).
* `format=xlsx|pdf` → full published schedule (subject to org policy; usually allowed).

**Response (200)**
Binary stream with `Content-Disposition: attachment; filename="schedule_2026-02_published.pdf"`
**Errors:** `404 not_found` (no published), `401`

---

## Edge Cases & Consistency with Admin Path

* **No data for a period**

  * `GET /schedules/{y}/{m}/published` → **404** if no published schedule.
  * `GET /preferences/{y}/{m}/me` → **200** with default allow-all working and `status="missing"`.

* **Past months**

  * All preference mutations → **403 period_closed**.
  * Reads (preferences, published schedule, diagnostics) → **200**.

* **Validation rules (preferences)**

  * **422** for invalid shapes/values:

    * day lists normalized + range **1..31**,
    * `min ≤ max` constraints,
    * `preferred_partners` must exist.

* **Field names & shapes**

  * Always return `version_id` for versions (draft/published/diagnostics).
  * Include `org_timezone`, `period_status`, and `processed_at` (UTC) on mutations for audit/debug parity with Admin Path.

---

## Minimal UX Checklist (Doctor)

* [ ] Deadline banner with countdown (“N days left”).
* [ ] Clear states: **Missing / Submitted / Locked** (after deadline).
* [ ] Autosave + **Save (checkpoint)** + **Undo/Redo** (mine-only).
* [ ] Year/Month picker for both tabs.
* [ ] Published schedule view with **“My shifts”** highlighting.
* [ ] **Export** buttons: PDF/XLSX (full), **ICS** (personal).
* [ ] (Optional) **My Summary** based on **published diagnostics**.

---

### Summary

* The Doctor can edit **only their own** preferences for **current/future** months with **mine-only Undo/Redo**, and sees **published** schedules read-only by `{year,month}`.
* JSON shapes, naming (`version_id`, `org_timezone`, `period_status`), and error codes are **fully consistent** with the Admin Path.
* No working/draft schedules are exposed to the Doctor; only the **published** stream and optional diagnostics are visible.
