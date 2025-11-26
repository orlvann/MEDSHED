# api-contract.md (MVP)

## 0) Scope & Roles

* **Admin**: manages directory, deadlines, availability, generation, editing, publication, exports.
* **Doctor**: edits own monthly preferences (current/future), browses published schedules; optional “My shifts” view & ICS.

---

## 1) Conventions & Best Practices

### 1.1 Time & Period Semantics

* Backend stores timestamps in **UTC**.
* UI renders in **`org_timezone`** (returned where relevant).
* Month classification (**past/current/future**) and **open/locked** for preferences are evaluated in **`org_timezone`**.

### 1.2 Data Model Patterns

* **Working + Versions + Pointers**

  * `*_working`: mutable working state (1 row per period).
  * `*_versions`: immutable snapshots

    * Preferences: `checkpoint`
    * Schedules: `draft_checkpoint` or `published`
  * `*_pointers`: pointer(s) to the current version(s).
  * Re-generating a schedule **overwrites** `schedule_working` for the period and creates a **new `draft_checkpoint`**; the draft pointer moves to the new version (history kept FIFO 5).
* **Undo/Redo**

  * Preferences: **mine-only** history per `{year, month, doctor_id}`; FIFO **5** checkpoints.
  * Schedules: **global** history per `{year, month}`; FIFO **5** draft checkpoints + **5** published.
  * **Autosave does not affect version history** — only `POST …/checkpoint` and `revert-last|revert-next` update `can_undo/can_redo`.
* **Diagnostics**

  * Stored **per version** (draft checkpoint or published).
  * Computed on **Save/Publish**, cached, or lazily on first fetch.

### 1.3 Naming (Normalized)

**Identifiers & versions**

* `version_id` — the single ID for every version (preferences `checkpoint` / schedule `draft_checkpoint` / schedule `published`). String, stable, immutable, globally unique.
* Other entity identifiers are integers (e.g., `doctor_id`).

**Case & format**

* JSON field names: `snake_case`.
* Enum values: **lowercase** (e.g., `"draft_checkpoint"`, `"published"`, `"specialist"`, `"resident"`, `"on_duty"`, `"on_call"`, `"ok"`, `"alert"`, `"critical"`).
* Timestamps: ISO-8601 UTC with `Z` suffix (e.g., `2026-02-01T10:15:00Z`).
* Time zones: IANA TZ strings (e.g., `"Europe/Warsaw"`).

**Common fields in responses**

* `org_timezone` — included where rendering depends on TZ.
* `period_status` ∈ `"past" | "current" | "future"`.
* Mutations return timestamps in UTC:
  * `working` reads/PUT → **`updated_at`**
  * creating a version / changing pointers (checkpoint/publish/revert) → **`processed_at`**

**Versioned object shape**

* Snapshot is under `payload` with:

  * `participant_doctor_ids: number[]`
  * `assignments: object[]` (app-internal shape)
  * `meta: { labels: string[], exceptions?: object[] }`
* Diagnostics per version:

  * `version_id`, `computed_at`, `summary` (+ optional `details`)

**Pagination (lists)**

* Request params: `page`, `size`
* Response: `{ page, size, total, items: [] }`

**Errors (stable shape)**

* `{ "detail": string, "code": string, "context"?: object }`

**Path & query parameters**

* Period as `/{year}/{month}` or `?year=&month=` (`year`: `YYYY`, `month`: `1..12` integer).
* Export: `mode=draft|published`, `format=xlsx|pdf|ics`, optional `doctor_id` (RBAC enforced).
* Diagnostics: `target=draft|published`.

**Day-list normalization**

* All day arrays are **unique + sorted + integers within 1..31** (normalized server-side). Invalid → `422`.

### 1.4 Status Codes

* **200 OK** — read or action without creating a new resource (GETs, `PUT …/working`, revert).
* **201 Created** — a new version/entity was created (checkpoint/draft/published).
* **204 No Content** — delete without body.
  **Quick map:**
  `GET → 200 · PUT …/working → 200 · POST …/checkpoint → 201 · POST …/revert-last|revert-next → 200 · POST /schedules/generate → 201 · POST /schedules/{y}/{m}/publish → 201 (or 409 if blocked) · DELETE → 204`

### 1.5 Error Model

```json
{ "detail": "human message", "code": "machine_code", "context": { /* optional */ } }
```

**Common codes**

* `401 unauthorized`
* `403 period_closed` (mutations on past months forbidden)
* `404 not_found` (entity/period/version not found)
* `409 cannot_undo` / `409 cannot_redo`
* `409 publish_blocked_by_hard_rules`
* `409 draft_already_exists` (guard for duplicate generate)
* `409 nothing_to_publish` (optional)
* `409 edit_conflict` (optional optimistic locking)
* `422 unprocessable_entity` (validation)
* `500 internal`

### 1.6 Lists of Days (Normalization)

* Server normalizes all day arrays: **unique, sorted, integers in 1..31**; invalid → `422` with
  `context: { "field": "<field_name>" }` (e.g., `"preferred_duty_days"`).


### 1.7 Pagination

* List endpoints (e.g., `GET /doctors`) accept `page`, `size`; return `{ page, size, total, items[] }`.

---

## 2) Shared Endpoints (Admin & Doctor)

### 2.1 Auth (Shared)

**Login**

```http
POST /api/v1/auth/login
Content-Type: application/json
```

**Request**

```json
{ "email": "user@hospital.org", "password": "••••••••" }
```

**Response (200)**

```json
{ "access_token": "eyJhbGciOiJIUzI1NiIs...", "token_type": "Bearer" }
```

Use `Authorization: Bearer <token>` for all subsequent calls.
Doctor identity is inferred from the token on all `/me` and on “my-assignments/ICS” operations.

### 2.2 Unified Export (Shared)

**Endpoint**
`GET /api/v1/schedules/export?year=YYYY&month=MM&mode=draft|published&format=xlsx|pdf|ics[&doctor_id=]`

**Behavior**

* Returns a file stream with correct `Content-Type` and `Content-Disposition`.
* Filenames:

  * XLSX/PDF (full schedule): `schedule_{YYYY}-{MM}_{mode}.(xlsx|pdf)`
  * ICS (personal): `schedule_{YYYY}-{MM}_doctor_{doctor_id}.ics`

**RBAC & Parameter Rules**

* **Doctor**

  * `format ∈ {xlsx,pdf}` → **requires** `mode=published` (draft forbidden → `403`).
  * `format=ics` → **personal ICS only**; `doctor_id` is forced to **me** (from token). Passing another `doctor_id` → `403`.
* **Admin**

  * `format ∈ {xlsx,pdf}` → `mode ∈ {draft,published}` allowed.
  * `format=ics` (optional policy) → may export ICS for a specific `doctor_id`. **Missing `doctor_id` → `422`**, invalid → `404`.

**Response (200)**
Binary stream (no JSON body).

**Errors**: `401`, `403`, `404` (no working/published for mode), `422`.

---

## 3) Admin Path

### 3.1 Doctors (Directory)

**List**

```http
GET /api/v1/doctors?page=&size=&role=&search=&is_active=true|false|all
```

**Response (200)**

```json
{
  "page": 1,
  "size": 20,
  "total": 132,
  "items": [
    {
      "id": 101,
      "first_name": "Anna",
      "last_name": "Nowak",
      "role": "specialist",
      "is_active": true,
      "is_head": false,
      "created_at": "2026-01-05T10:22:31Z",
      "updated_at": "2026-01-05T10:22:31Z"
    }
  ]
}
```

**Create**

```http
POST /api/v1/doctors
Content-Type: application/json
```

**Request**

```json
{ "first_name": "Anna", "last_name": "Nowak", "role": "specialist", "is_active": true, "is_head": false }
```

**Response (201)** — full object with IDs and timestamps.

**Update (PUT-first)**

```http
PUT /api/v1/doctors/{doctor_id}
Content-Type: application/json
```

**Request (full object)**

```json
{ "first_name": "Anna", "last_name": "Nowak", "role": "specialist", "is_active": false, "is_head": true }
```

**Response (200)** — full object.

**Delete**

```http
DELETE /api/v1/doctors/{doctor_id}
```

**Response (204)**

**Errors**: `401`, `404`, `422`.

**Note**: `is_active=true` defines the monthly pool for generation; the snapshot is stored as `participant_doctor_ids` in schedule versions.

---

### 3.2 Preferences (Admin — per doctor/month)

**Summary (who submitted / who is missing)**

```http
GET /api/v1/preferences/summary?year=&month=
```

**Response (200)**

```json
{
  "year": 2026,
  "month": 2,
  "submitted": [42,7,9],
  "missing": [11,13,21],
  "last_update_at": "2026-01-05T10:22:31Z"
}
```

**Read current form (working + pointer hints)**

```http
GET /api/v1/preferences/{year}/{month}/{doctor_id}
```

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
  "version_id": null,
  "submitted_at": null,
  "submitted_by_role": null,
  "submitted_by_user_id": null,
  "last_admin_note": null,

  "can_undo": false,
  "can_redo": false,
  "org_timezone": "Europe/Warsaw",
  "period_status": "current"
}
```

**Autosave (no checkpoint)**

```http
PUT /api/v1/preferences/{year}/{month}/{doctor_id}/working
Content-Type: application/json
```

**Request**

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
  "can_redo": false
}
```

**Errors**: `403 period_closed`, `422` (min>max, invalid days, unknown partners, etc.)

**Save (create checkpoint) — make it official & mark submitted**

```http
POST /api/v1/preferences/{year}/{month}/{doctor_id}/checkpoint
Content-Type: application/json
```

**Request (optional)**

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
  "version_id": "prefv_2026_02_doctor11_0001",
  "submitted_at": "2026-02-01T10:15:00Z",
  "submitted_by_user_id": 101,
  "submitted_by_role": "admin",

  "can_undo": true,
  "can_redo": false,
  "processed_at": "2026-02-01T10:15:00Z"
}
```

**Undo / Redo (mine-only)**

```http
POST /api/v1/preferences/{year}/{month}/{doctor_id}/revert-last
POST /api/v1/preferences/{year}/{month}/{doctor_id}/revert-next
```

**Response (200) — UNDO example**

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
  "version_id": "prefv_2026_02_doctor11_0000",
  "current_created_by_role": "admin",
  "current_created_by_user_id": 101,
  "current_created_at": "2026-01-28T09:58:00Z",
  "can_undo": true,
  "can_redo": true
}
```

**Response (200) — REDO example**

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
  "version_id": "prefv_2026_02_doctor11_0001",
  "current_created_by_role": "admin",
  "current_created_by_user_id": 101,
  "current_created_at": "2026-02-01T10:15:00Z",
  "can_undo": true,
  "can_redo": false
}
```

**Errors**: `401`, `403 period_closed`, `404`, `409 cannot_undo|cannot_redo`, `422`.

**Deadline (PUT-as-upsert)**

```http
GET /api/v1/preferences/deadlines/{year}/{month}
PUT /api/v1/preferences/deadlines/{year}/{month}
```

**GET (200)**

```json
{ "year": 2026, "month": 2, "deadline": "2026-01-20T23:59:59Z", "status": "open", "org_timezone": "Europe/Warsaw" }
```

**PUT (201 if created; 200 if updated)**

```json
{ "year": 2026, "month": 2, "deadline": "2026-01-22T23:59:59Z", "status": "open", "org_timezone": "Europe/Warsaw" }
```

Open/locked is evaluated in `org_timezone`; changing the deadline unlocks immediately. Past periods → `403 period_closed` (unless audited override).

**What the generator uses**

* If at least one checkpoint exists → the pointer’s checkpoint (current).
* If no checkpoint → the working (defaults to “allow all”).

---

### 3.3 Availability (Pre-flight)

```http
GET /api/v1/availability/overview?year=&month=
GET /api/v1/availability/{year}/{month}/{day}
```

**Overview (200)**

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

**Risk rules**

* `critical`: `available_specialists == 0` OR no staff at all OR a required role has `0`.
* `alert`: below configured thresholds but `> 0`.
* `ok`: sufficient.

**Day drill-down (200)**

```json
{
  "day": 12,
  "specialists": [],
  "residents":   [{ "id": 3, "first_name": "Ola", "last_name": "Nowicka" }],
  "risk": "critical"
}
```

---

### 3.4 Schedules (Admin)

**Generate (guard: avoid duplicates)**

```http
POST /api/v1/schedules/generate
Content-Type: application/json
```

**Request**

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
    "version_id": "schv_2026_02_0001",
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
    "version_id": "schv_2026_02_0001",
    "computed_at": "2026-02-01T10:12:01Z",
    "summary": { /* initial metrics for the generated draft */ }
  }
}
```

**Errors**: `401`, `403 period_closed`, `422`, `409 draft_already_exists` (if `schedule_working` already exists for `{year,month}`).

## 3.4 Schedules (Admin)

 ### Generate (guard: avoid duplicates)
 POST /api/v1/schedules/generate

**Behavior**
* If no `working` exists for `{year,month}`, create it from solver output.
* If `working` **already exists** for `{year,month}`, **overwrite** it with fresh solver output.
* In both cases, create a **new draft checkpoint** (incrementing `version_id`), move the **draft pointer** to it, and recompute diagnostics.
* Previous draft checkpoints remain in history (FIFO **5**).

**Errors**: `401`, `403 period_closed`, `422`.


**Schedules Tab — Period View**

```http
GET /api/v1/schedules/{year}/{month}
```

**Response (200)**

```json
{
  "year": 2026,
  "month": 2,
  "org_timezone": "Europe/Warsaw",
  "period_status": "current",

  "view": { "default_mode": "draft", "toggle_available": true },

  "working": {
    "exists": true,
    "participant_doctor_ids": [1,2,5,7],
    "assignments": [ /*...*/ ],
    "meta": { "labels": ["as_generated"] },
    "updated_at": "2026-02-01T10:20:00Z"
  },

  "draft": {
    "version_id": "schv_2026_02_0003",
    "checkpoints_count": 3,
    "can_undo": true,
    "can_redo": false,
    "payload": { /* snapshot */ }
  },

  "published": {
    "version_id": null,
    "publications_count": 0,
    "can_undo": false,
    "can_redo": false,
    "payload": null
  },

  "diagnostics": {
    "version_id": "schv_2026_02_0003",
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
**Errors**: `401`.
If the period has no data, the endpoint returns **`200`** with an empty skeleton:
`working.exists=false`, `draft.version_id=null`, `published.version_id=null`.

### Diagnostics (Schedules)

**GET** `/api/v1/schedules/{year}/{month}/diagnostics?target=draft|published`  
Returns diagnostics (KPIs) for the schedule version currently pointed by the selected stream.

- **200** → `DiagnosticsRead`
- **404** → when the selected pointer has no version for the period (or dangling pointer)

**MVP behavior**
- Backend resolves `{year,month,target}` → pointer → `version_id`.
- If the diagnostics cache is missing or stale, it recomputes and persists a compact summary, then returns it.
- `details` field is optional and may be `null` in MVP.

**POST-MVP roadmap**
1) Enrich `details` with strongly-typed sections:
   - coverage (under/overstaffed days, rest-rule flags, hotspots),
   - preferences (fulfilled/unfulfilled, per-doctor stats),
   - fairness (avg duties per role, distribution),
   - partnering (preferred pairs respected/missed),
   - visuals (daily cost heatmap, violations timeline),
   - suggestions (auto-fixes with estimated impact).

2) Additional endpoints:
   - `GET /api/v1/schedules/{y}/{m}/diagnostics/details?target=...` (lazy-load heavy details)
   - `POST /api/v1/schedules/{y}/{m}/diagnostics/recompute?target=...` (force refresh cache)

3) Streaming/exports:
   - Optional links in `details` to CSV/JSON dumps or plots where relevant.

**Working — read & autosave (optional optimistic locking)**

```http
GET  /api/v1/schedules/{year}/{month}/working
PUT  /api/v1/schedules/{year}/{month}/working
```

**GET (200)**

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

**PUT (200)**
**Request**

```json
{
  "assignments": [ /* edited in UI */ ],
  "meta": { "labels": ["as_generated","touched"] },
  "if_unmodified_since": "2026-02-01T10:20:00Z"
}
```

**Response**

```json
{ "year": 2026, "month": 2, "updated_at": "2026-02-01T11:05:30Z" }
```

**Errors**: `401`, `403 period_closed`, `404` (GET), `409 edit_conflict` (optional), `422`.
`409 edit_conflict` SHOULD include the current server value:
```json
{ "detail": "edit_conflict", "code": "edit_conflict", "context": { "updated_at": "2026-02-01T11:01:00Z" } }
```


**Save Draft Checkpoint (+diagnostics)**

```http
POST /api/v1/schedules/{year}/{month}/checkpoint
Content-Type: application/json
```

**Request (optional)**

```json
{ "note": "manual tweak day 12 on-call" }
```

**Response (201)**

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
      "assignments": [ /* working snapshot at save */ ],
      "meta": { "labels": ["as_generated","touched"], "exceptions": [] }
    }
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

**Errors**: `401`, `403 period_closed`, `422`.

**Draft UNDO/REDO**

```http
POST /api/v1/schedules/{year}/{month}/revert-last
POST /api/v1/schedules/{year}/{month}/revert-next
```

**UNDO — Response (200)**

```json
{
  "year": 2026,
  "month": 2,

  "draft": {
    "version_id": "schv_2026_02_0001",
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
    "version_id": "schv_2026_02_0001",
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

**REDO — Response (200)**

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

**Errors**: `401`, `403`, `409 cannot_undo|cannot_redo`.

**Publish (hard-rule guard) (guard: nothing to publish)**

```http
POST /api/v1/schedules/{year}/{month}/publish
Content-Type: application/json
```

**Request**

```json
{
  "force": false,
  "note": "Finalize February",
  "accepted_exceptions": []
}
```

* Validates hard rules on **current working**.
* If violations and `force=false` → `409 publish_blocked_by_hard_rules` with `violations[]`.
* With `force=true` + matching `accepted_exceptions[]` → create **published**; persist exceptions into `payload.meta.exceptions[]` with audit.
* Optional: if working equals last published (no diff) → `409 nothing_to_publish`.
  Comparison MUST be done after **normalizing** `assignments` (stable sort + key dedupe) to avoid false differences.


**Response (201)**

```json
{
  "year": 2026,
  "month": 2,
  "published": {
    "version_id": "schv_2026_02_0101",
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

**Example 409 error body (first attempt, `force=false`)**

```json
{
  "detail": "publish_blocked_by_hard_rules",
  "violations": [
    { "code": "NO_SPECIALIST_DAY_12", "message": "No specialist on 12th" },
    { "code": "MAX_CONSEC_ONCALL_EXCEEDED_DAY_20", "message": "Exceeded consecutive on-call limit on 20th" }
  ]
}
```

**Confirmed publish (second attempt, `force=true`)**

```json
{
  "force": true,
  "note": "Exceptional staffing shortage due to flu wave.",
  "accepted_exceptions": [
    { "code": "NO_SPECIALIST_DAY_12", "justification": "Clinic closed AM; ER covered by on-call specialist." },
    { "code": "MAX_CONSEC_ONCALL_EXCEEDED_DAY_20", "justification": "Doctor volunteered; union rep informed." }
  ]
}
```

**Published response excerpt with persisted exceptions**

```json
{
  "payload": {
    "meta": {
      "labels": ["as_generated","touched"],
      "exceptions": [
        { "code": "NO_SPECIALIST_DAY_12", "justification": "Clinic closed AM; ER covered by on-call specialist.", "accepted_by_user_id": 101, "accepted_at": "2026-02-01T11:20:00Z" },
        { "code": "MAX_CONSEC_ONCALL_EXCEEDED_DAY_20", "justification": "Doctor volunteered; union rep informed.", "accepted_by_user_id": 101, "accepted_at": "2026-02-01T11:20:00Z" }
      ]
    }
  }
}
```

**Published rollback/redo (within editing window)**

```http
POST /api/v1/schedules/{year}/{month}/revert-last-published
POST /api/v1/schedules/{year}/{month}/revert-next-published
```

**Rollback — Response (200)**

```json
{
  "year": 2026,
  "month": 2,
  "published": {
    "version_id": "schv_2026_02_0100",
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

**Redo — Response (200)**

```json
{
  "year": 2026,
  "month": 2,
  "published": {
    "version_id": "schv_2026_02_0101",
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

**Errors**: `401`, `403 period_closed`, `409 cannot_undo|cannot_redo`.

**Diagnostics (fetch)**

```http
GET /api/v1/schedules/{year}/{month}/diagnostics?target=draft|published
```
- Returns DiagnosticsRead for the version currently pointed by the given target.
* `target=draft` → uses the **draft** pointer’s `version_id`.
* `target=published` → uses the **published** pointer’s `version_id`.
- 200: DiagnosticsRead
- 404: when the selected pointer doesn't exist (no version for that stream)


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
  "details": { /* optional */ }
}
```

**Errors**: `401`, `404`.

---

## 4) Doctor Path

### 4.1 Preferences (own)

**Read (working + hints)**

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
  "period_status": "current"
}
```

**Autosave**

```http
PUT /api/v1/preferences/{year}/{month}/me/working
Content-Type: application/json
```

**Request**

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

**Errors**: `403 period_closed`, `422`.

**Save (checkpoint)**

```http
POST /api/v1/preferences/{year}/{month}/me/checkpoint
```

**Request (optional)**

```json
{ "note": "Submitted by doctor" }
```

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

**Undo/Redo (mine-only)**

```http
POST /api/v1/preferences/{year}/{month}/me/revert-last
POST /api/v1/preferences/{year}/{month}/me/revert-next
```

**UNDO — Response (200)**

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

**REDO — Response (200)**

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

**Deadline (read)**

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

**Errors (this section)**: `401`, `403 period_closed` (mutations on past), `404`, `409`, `422`.

---

### 4.2 Schedules (published only)

**Read published schedule (full month)**

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

**Errors**: `401`, `404 not_found` (no published).

**Diagnostics (published)**

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

**(Optional) My assignments (from the published version)**

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

**Errors**: `401`, `404` (no published).

---

## 5) Edge Cases & Consistency with Admin Path

* **No data for a period**

  * `GET /schedules/{y}/{m}/published` → `404` if no published schedule.
  * `GET /preferences/{y}/{m}/me` → `200` with default allow-all working and `status="missing"`.
* **Past months**

  * All preference mutations → `403 period_closed`.
  * Reads (preferences, published schedule, diagnostics) → `200`.
* **Validation rules (preferences)**

  * `422` for invalid shapes/values:

    * day lists normalized + range `1..31`,
    * `min ≤ max` constraints,
    * `preferred_partners` must exist.
* **Field names & shapes**

  * Always return **`version_id`** for versions (draft/published/diagnostics).
  * Include `org_timezone`, `period_status`, and `processed_at/updated_at` (UTC) on mutations for audit/debug parity with Admin Path.

---

