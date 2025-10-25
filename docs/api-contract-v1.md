# MEDSCHED API Contract — **v1 (DRAFT)**

> **Status:** NOT VALID - follow admin_path_api.md
> Public routes are versioned under **`/api/v1`**. Breaking changes will ship under **`/api/v2`**
> This document reflects the **cleaned path layout** and is aligned with the current OpenAPI schemas and response codes.

---

## Architecture note: Routers vs. Services

- **Routers** (this API surface) are a **thin HTTP layer** — think *“secretary who receives the request and forwards it”*.
  They:
  - define endpoints and **Pydantic request/response schemas**,
  - perform **automatic structural validation** (FastAPI/Pydantic),
  - delegate to services,
  - return JSON/files.

- **Services** contain **business logic** (e.g., constraints, DB orchestration, solver calls).
  - Routers trust that **payloads are structurally valid**; services may add **semantic checks** (e.g., `min ≤ max`, legal rules).
  - Typical errors from semantic checks: **400/409** with a clear message.

---

## Conventions

- **Base URL (dev):** `http://127.0.0.1:8000/api/v1`
- **Content-Type:** `application/json` unless noted
- **Auth:** `Authorization: Bearer <JWT>` (prefer httpOnly cookie in production)
- **Roles:** `Admin`, `Doctor`
- **IDs:** UUID strings unless stated
- **Dates:** ISO `YYYY-MM-DD`; Timestamps: ISO-8601 UTC (e.g., `2025-10-14T09:30:00Z`)
- **Pagination (when applicable):** `?page=1&page_size=50` (default `page_size=50`, max `200`)
  Response includes: `items`, `page`, `page_size`, `total`
- **Errors (canonical shape):**
  ```json
  {
    "error": {
      "code": "string_identifier",
      "message": "Human-readable message",
      "details": { "field": "optional explanation" }
    }
  }
````

* **Validation:** Structural validation errors are returned by FastAPI/Pydantic as **422** with field details.

---

## Diagnostics (public)

### `GET /diagnostics/health`

Health probe.

**200 OK**

```json
{ "status": "ok", "api": "v1 available at /api/v1" }
```

---

## Auth

### `POST /auth/login` — Issue JWT

**Request (LoginRequest)**

```json
{ "email": "user@example.com", "password": "secret" }
```

**200 OK (TokenResponse)**

```json
{
  "access_token": "jwt-string",
  "token_type": "bearer",
  "role": "ADMIN",
  "expires_in": 3600
}
```

**422 Unprocessable Entity** – structural validation error.

---

### `GET /auth/me` — Current user

**200 OK (UserRead)**

```json
{
  "id": 1,
  "email": "user@example.com",
  "role": "DOCTOR",
  "is_active": true,
  "created_at": "2025-10-14T09:30:00Z"
}
```

---

## Doctors

### `GET /doctors` — List (pagination + optional filters)

**Query params**

* `page` (int, default 1, min 1)
* `size` (int, default 50, 1..200)
* `role` (`SPECIALIST` | `RESIDENT`, optional)
* `search` (string, optional; name/email substring)

**200 OK (DoctorList)**

```json
{
  "page": 1,
  "size": 50,
  "total": 47,
  "items": [
    {
      "id": 42,
      "first_name": "Anna",
      "last_name": "Nowak",
      "role": "SPECIALIST",
      "is_head": false,
      "email": "anna.nowak@example.com",
      "color": "#1f77b4"
    }
  ]
}
```

**422 Unprocessable Entity**

---

### `POST /doctors` — Create

**Request (DoctorCreate)**

```json
{
  "first_name": "Anna",
  "last_name": "Nowak",
  "role": "SPECIALIST",
  "is_head": false,
  "email": "anna.nowak@example.com",
  "color": "#1f77b4"
}
```

**201 Created (DoctorRead)**

```json
{
  "id": 43,
  "first_name": "Anna",
  "last_name": "Nowak",
  "role": "SPECIALIST",
  "is_head": false,
  "email": "anna.nowak@example.com",
  "color": "#1f77b4"
}
```

**422 Unprocessable Entity**

---

### `GET /doctors/{doctor_id}` — Get by id

**200 OK (DoctorRead)** …as above
**422 Unprocessable Entity**

---

### `PATCH /doctors/{doctor_id}` — Partial update

**Request (DoctorUpdate)** — all fields optional

```json
{ "is_head": true, "color": "#9467bd" }
```

**200 OK (DoctorRead)**
**422 Unprocessable Entity**

---

### `DELETE /doctors/{doctor_id}`

**204 No Content**
**422 Unprocessable Entity**

---


## Preferences

> Router handles structural validation; service enforces semantic rules (e.g., ranges, deadlines).

### `GET /preferences` — My monthly preferences (doctor)

**Query params**

* `year` (int, 1900..2100) **required**
* `month` (int, 1..12) **required**
* `doctor_id` (int, admin-only, optional; otherwise inferred from auth)

**200 OK (PreferenceRead)**

```json
{
  "id": 123,
  "doctor_id": 42,
  "year": 2026,
  "month": 2,
  "unavailable_duty_days": [7,14],
  "unavailable_oncall_days": [8],
  "preferred_duty_days": [10,11],
  "preferred_oncall_days": [12],
  "min_duties_weekdays": 5,
  "max_duties_weekdays": 7,
  "min_duties_weekends": 2,
  "max_duties_weekends": 3,
  "min_oncall_weekdays": 3,
  "max_oncall_weekdays": 5,
  "min_oncall_weekends": 1,
  "max_oncall_weekends": 2,
  "weekend_back_to_back_allowed": false,
  "preferred_partners": [7,9],
  "comments": "no nights after clinics",
  "status": "draft",
  "submitted_at": null,
  "updated_at": "2025-10-14T09:30:00Z",
  "updated_by_user_id": 1
}
```

**422 Unprocessable Entity**

---

### `POST /preferences` — Create or replace (upsert)

**Request (PreferenceCreate)**

```json
{
  "doctor_id": 42,
  "year": 2026,
  "month": 2,
  "unavailable_duty_days": [7,14],
  "unavailable_oncall_days": [8],
  "preferred_duty_days": [10,11],
  "preferred_oncall_days": [12],
  "min_duties_weekdays": 5,
  "max_duties_weekdays": 7,
  "min_duties_weekends": 2,
  "max_duties_weekends": 3,
  "min_oncall_weekdays": 3,
  "max_oncall_weekdays": 5,
  "min_oncall_weekends": 1,
  "max_oncall_weekends": 2,
  "weekend_back_to_back_allowed": false,
  "preferred_partners": [7,9],
  "comments": "no nights after clinics"
}
```

**201 Created (PreferenceRead)** — full read model with metadata
**422 Unprocessable Entity**

---

### `GET /preferences/{doctor_id}` — Admin: get a doctor’s preferences

**Query params:** `year` (required), `month` (required)
**200 OK (PreferenceRead)**
**422 Unprocessable Entity**

---

### `PATCH /preferences/{pref_id}` — Partial update

**Request (PreferenceUpdate)** — all fields optional (incl. `status`)

```json
{ "comments": "updated note", "status": "submitted" }
```

**200 OK (PreferenceRead)**
**422 Unprocessable Entity**

---

### `POST /preferences/{pref_id}/submit` — Mark as SUBMITTED

**200 OK (PreferenceRead)**
**422 Unprocessable Entity**

---

### `POST /preferences/{pref_id}/revert` — Revert SUBMITTED → DRAFT

**200 OK (PreferenceRead)**
**422 Unprocessable Entity**

---

### `GET /preferences/{pref_id}/audit` — Audit trail

**200 OK (PreferenceAuditEntryRead[])**

```json
[
  {
    "id": 1,
    "preference_id": 123,
    "actor_user_id": 5,
    "actor_role": "ADMIN",
    "action": "update",
    "at": "2025-10-14T10:00:00Z",
    "diff": { "comments": ["old", "new"] }
  }
]
```

**422 Unprocessable Entity**

---

### `GET /preferences/summary` — Submission & coverage summary

**Query params:** `year` (required), `month` (required)

**200 OK (PreferenceSummary)**

```json
{
  "submitted": [1,2,42],
  "missing": [5,7],
  "coverageByDay": [
    { "day": 1, "availableDuty": 5, "availableOnCall": 3 }
  ]
}
```

**422 Unprocessable Entity**

---


## Schedules

### `POST /schedules/generate` — Run solver and create a draft

**Request (GenerateScheduleRequest)**

```json
{ "year": 2026, "month": 2, "department_id": "ER" }
```

**201 Created (ScheduleRead)**

```json
{
  "id": 99,
  "year": 2026,
  "month": 2,
  "status": "draft",
  "created_by": 1,
  "created_at": "2025-01-20T12:34:56Z",
  "updated_at": null,
  "published_at": null,
  "published_by": null,
  "assignments": [
    { "day": 1, "shift_type": "OnDuty", "doctor_id": 5 },
    { "day": 1, "shift_type": "OnCall", "doctor_id": 2 }
  ]
}
```

**422 Unprocessable Entity**

---

### `GET /schedules/{sid}` — Get schedule by id

**200 OK (ScheduleRead)**
**422 Unprocessable Entity**

---

### `PATCH /schedules/{sid}` — Apply manual edits (with validation)

**Request** — array of `ManualEditRequest`

```json
[
  { "day": 10, "shift_type": "OnDuty", "to_doctor_id": 2, "reason": "swap" }
]
```

**200 OK (ScheduleRead)**
**422 Unprocessable Entity**

---

### `POST /schedules/{sid}/publish` — Publish (visible to doctors)

**Request (optional, PublishRequest)**

```json
{ "note": "Finalized by head of department" }
```

**200 OK (ScheduleRead)**
**422 Unprocessable Entity**

---

### `GET /schedules/history` — Browse past schedules

**Query params**

* `from_year` (required)
* `from_month` (required)
* `to_year` (required)
* `to_month` (required)

**200 OK (ScheduleHistoryList)**

```json
{
  "items": [
    {
      "schedule_id": 77,
      "year": 2025,
      "month": 12,
      "status": "published",
      "published_at": "2025-11-28T09:00:00Z"
    }
  ],
  "total": 1
}
```

**422 Unprocessable Entity**

---

### Exports

#### `GET /schedules/{sid}/export` — Export metadata + link

**Query params (optional)**

* `format` (`xlsx` | `pdf`, default `xlsx`)
* `include_diagnostics` (bool, default `true`)
* `include_details` (bool, default `true`)

**200 OK (ExportResponse)**

```json
{
  "schedule_id": 99,
  "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  "generated_at": "2025-01-20T13:00:00Z",
  "download_url": "/api/v1/schedules/99/export.xlsx",
  "size_bytes": 102400
}
```

**422 Unprocessable Entity**

#### `GET /schedules/{sid}/export.xlsx` — Binary

**200 OK** — binary stream (`Content-Disposition` suggested)

**422 Unprocessable Entity**

#### `GET /schedules/{sid}/export.pdf` — Binary

**200 OK** — binary stream

**422 Unprocessable Entity**

---

## Diagnostics

### `GET /diagnostics/schedules/{sid}/diagnostics` — Diagnostics for schedule

**200 OK (DiagnosticsRead)**

```json
{
  "schedule_id": 99,
  "summary": {
    "primary_cost": 12,
    "secondary_cost": 3,
    "penalty_total": 4,
    "fairness_gini": 0.12
  },
  "coverage": {
    "understaffed_days": [5,12],
    "overstaffed_days": [],
    "resident_only_days": [],
    "rest_rule_flags": [
      { "day": 15, "doctor_id": 7, "type": "rest_break" }
    ],
    "hotspots": [15]
  },
  "preferences": {
    "fulfilled": 20,
    "unfulfilled": 5,
    "per_doctor": [
      {
        "doctor_id": 42,
        "duties_total": 6,
        "oncall_total": 4,
        "weekends_worked": 2,
        "unavailable_violations": 0,
        "preferences_fulfilled": 5,
        "duty_requested": 6,
        "oncall_requested": 4
      }
    ]
  },
  "fairness": {
    "specialists_avg_duties": 6.0,
    "residents_avg_duties": 5.0,
    "distribution": [
      { "doctor_id": 42, "duties": 6, "oncall": 4 }
    ]
  },
  "partnering": {
    "preferred_pairs_respected": 12,
    "missed_pairs": [
      { "day": 10, "pair": [3,7] }
    ]
  },
  "visuals": {
    "daily_cost_heatmap": [0,1,2,0,3],
    "violations_timeline": [
      { "2025-02-01": 0 },
      { "2025-02-02": 1 }
    ]
  },
  "suggestions": [],
  "exports": {
    "xlsx": "/api/v1/schedules/99/export.xlsx",
    "pdf": "/api/v1/schedules/99/export.pdf"
  }
}
```

**422 Unprocessable Entity**

---

## Error Summary

| HTTP | Meaning (typical)                                                      |
| ---- | ---------------------------------------------------------------------- |
| 200  | Success (GET/PATCH/POST actions as defined)                            |
| 201  | Created (e.g., POST `/doctors`, `/schedules/generate`, `/preferences`) |
| 204  | No Content (DELETE)                                                    |
| 422  | Unprocessable Entity (validation errors)                               |

> Business-rule errors (e.g., conflicts, not found, forbidden) may be surfaced by services using conventional HTTP codes; shape may follow a generic `{ "error": { "code", "message", "details" } }` pattern if implemented.

---

## Key Schemas (names match OpenAPI)

* `UserRead`, `TokenResponse`, `DoctorRead`, `DoctorCreate`, `DoctorUpdate`, `DoctorList`
* `PreferenceCreate`, `PreferenceRead`, `PreferenceUpdate`, `PreferenceAuditEntryRead`, `PreferenceSummary`, `PreferenceStatus`
* `ScheduleRead`, `ScheduleStatus`, `AssignmentRead`, `ManualEditRequest`, `ExportResponse`
* `DiagnosticsRead`, `DiagnosticsSummary`, `DiagnosticsVisuals`, `CoverageReport`, `PreferencesBreakdown`, `FairnessBreakdown`, `PartneringBreakdown`
* Enums: `Role` (`ADMIN`/`DOCTOR`), `DoctorRole` (`SPECIALIST`/`RESIDENT`), `ShiftType` (`OnDuty`/`OnCall`)

---

### Notes

* Examples use **snake_case** to match the OpenAPI component schemas.
* Endpoint response codes reflect your current OpenAPI: e.g., **`201`** for `POST /doctors`, `POST /preferences`, and `POST /schedules/generate`.

---
