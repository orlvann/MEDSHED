Looks solid! I fixed a few typos, tightened wording, and made formatting consistent. Ready to paste:

---

# Dev current milestones

## OLA (Backend)

### Core Setup

- [x] App design and project layout finalized (`docs/admin_path_api.md`, `docs/doctor_path_api.md`)
- [x] FastAPI runs cleanly (`uvicorn backend.asgi:app --reload`)
- [x] Swagger & ReDoc generate full OpenAPI spec (`/docs`, `/redoc`)
- [x] Health endpoint working → `{"status": "ok", "api": "v1 available at /api/v1"}`

### Database (NEW)

- [x] SQLAlchemy core wired: `engine`, `SessionLocal`, `Base`, `get_db()` (ready for DI)
- [x] Alembic initialized (config + env)
- [x] Migrations:

  - **Users/Doctors:** `users`, `doctors` (unique email, helpful indexes, timestamps)
  - **Preferences:** `preferences_working`, `preferences_versions`, `preferences_pointers`, `preferences_deadlines`
  - **Schedules:** `schedule_working`, `schedule_versions` (draft|published), `schedule_pointers`, `schedule_diagnostics`

- [x] Enums centralized in `backend/models/common_enums.py`
- [x] Dev tooling:

  - Makefile targets: `db-upgrade`, `db-revision`, `db-check`, `db-check-one`, `db-check-like`, `db-show`, `db-seed`, `db-dump`, `db-dump-full`, `db-reset` (`help` is default)
  - Scripts: `scripts/db_check.py`, `scripts/db_seed.py`, `scripts/db_show.py`, `scripts/db_dump_sql.py`

- [x] Seed for local testing:

  - Doctors: Anna Kowalska (specialist), Piotr Nowak (resident)
  - Users: `admin@hospital.org` / `admin123!`, `anna@hospital.org` / `doctor123!` (linked to Doctor(Anna))

**Quick DB test**

```bash
make db-upgrade
make db-seed
make db-check                     # all tables & columns
make db-check-like p=sche%        # only schedule*
make db-check-like p=preferences% # only preferences*
make db-show
```

### Routers implemented (mock data, full shape)

- [x] **Auth** — endpoints exist (`/auth/login`, `/auth/me`); **currently mocked**; contracts stable
- [x] **Doctors** — CRUD with pagination/filters; fields & enums per spec
- [x] **Preferences** — lifecycle (working, checkpoint, undo/redo, deadlines, summary); day normalization & `min ≤ max` guards
- [x] **Schedules** — period view (working + draft/published pointers), generate, checkpoint, undo/redo, publish, diagnostics, export
- [x] **Diagnostics** — per `version_id` (draft/published) as in MVP
- [x] **Availability** — admin overview/day heatmap stub (shapes fixed for FE)
- [x] **Schemas (Pydantic DTOs)** — mapped 1:1 to the contract; Swagger renders correctly

**Quick API test**

```bash
make app
```

Then open:

- [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) (Swagger UI), or
- [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc) (ReDoc)

> ✅ Frontend can integrate with **all `/api/v1/*` endpoints** (mocks where applicable).
> 📄 HTTP responses & status codes consistent with the OpenAPI contract.
> 🔐 Auth team can start now: replace mock auth in HTTP routers with a DB-backed `auth_service`.
> 🧩 **Schedules flow works end-to-end (without solver)**: generate → working save (OCC) → checkpoint → publish → diagnostics cache (period view).

### Docs & Tooling

- [x] `README.md`, `docs/api-contract-v1.md`
- [x] `.gitignore`, `pre-commit`, `pytest.ini`, `requirements*.txt`
- [x] Makefile added (developer commands) and scripts for DB

---

# Next up in BE

## Ola (owner: **Schedules + Solver**)

0. **DB seed** — ensure realistic sample data for solver/availability (`make db-seed`).

1. **Availability**
   Compute real availability/heatmaps from **Doctors + Preferences**; expose via `backend/services/availability_service.py`.
   _Feeds solver + FE._

2. **Solver MVP**
   Model key CP-SAT constraints and plug into `SchedulingService.generate` (files: `backend/core/*`, `backend/services/scheduling_service.py`).
   _Produce assignments → create draft version + minimal diagnostics._

3. **Diagnostics v1**
   Persist KPIs per version (coverage, violations, fairness deltas) via `backend/services/diagnostics_service.py`; render in period view after generate/checkpoint/publish.
   _Visible immediately to FE._

4. **Schedules pipeline polish**
   Support publish with violations (`force`), OCC on working saves, consistent pointers, audit trail — all in `backend/services/scheduling_service.py`.
   _Complete admin workflow E2E._

---

## Ania (services over ORM)

1. **Preferences service** — replace stubs with ORM for **working / versions / pointers / deadlines** in `backend/services/preference_service.py`.
2. **Doctors service** — wire CRUD to ORM in `backend/services/doctor_service.py` (keep DTOs/routers unchanged).
3. **Auth & RBAC** — JWT login, password hashing, role guards (admin/doctor): `backend/services/auth_service.py`, `backend/routers/deps.py`, `backend/utils/security.py`.
4. **Exports (later)** — XLSX/PDF from **schedule versions** in `backend/services/export_service.py`.
   _(tbd)_
