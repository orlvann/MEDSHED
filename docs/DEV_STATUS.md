
# Dev current milestones

## OLA (Backend)

### Core Setup

* [x] App design and project layout finalized (`backend/`, `routers/`, `models/schemas`, `docs/`)
* [x] FastAPI runs cleanly (`uvicorn backend.asgi:app --reload`)
* [x] Swagger & ReDoc generate full OpenAPI spec (`/docs`, `/redoc`)
* [x] Health endpoint working → `{"status": "ok", "api": "v1 available at /api/v1"}`

### Database (NEW)

* [x] SQLAlchemy core wired: `engine`, `SessionLocal`, `Base`, `get_db()` (ready for DI)
* [x] Alembic initialized (config + env)
* [x] Migrations:

  * `doctors` table (unique email, timestamps, helpful indexes)
  * `users` table (unique email, `password_hash`, `role`, `is_active`, optional 1:1 `doctor_id` → `doctors`, timestamps)
* [x] Enums centralized in `backend/models/common_enums.py`
* [x] Dev tooling:

  * Makefile targets: `db-upgrade`, `db-revision`, `db-check`, `db-check-one`, `db-check-like`, `db-show`, `db-seed`, `db-dump`, `db-dump-full`, `db-reset` (`help` is default)
  * Scripts: `scripts/db_check.py`, `scripts/db_seed.py`, `scripts/db_show.py`, `scripts/db_dump_sql.py`
* [x] Seed for local testing:

  * Doctors: Anna Kowalska (specialist), Piotr Nowak (resident)
  * Users: `admin@hospital.org` / `admin123!`, `anna@hospital.org` / `doctor123!` (linked to Doctor(Anna))

**Quick DB test**

```bash
make db-upgrade
make db-seed
make db-check
make db-show
```

### Routers implemented (mock data, full shape)

* [x] **Auth** — endpoints exist (`/auth/login`, `/auth/me`); **currently mocked**; contracts stable
* [x] **Doctors** — CRUD with pagination/filters; fields & enums per spec
* [x] **Preferences** — lifecycle (working, checkpoint, undo/redo, deadlines, summary); day normalization & `min ≤ max` guards
* [x] **Schedules** — period view (working + draft/published pointers), generate, checkpoint, undo/redo, publish, diagnostics, export
* [x] **Diagnostics** — per `version_id` (draft/published) as in MVP
* [x] **Schemas (Pydantic DTOs)** — mapped 1:1 to the contract; Swagger renders correctly


**Quick API test**

```bash
make app
````

Then open:

* [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) (Swagger UI), or
* [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc) (ReDoc)

```

> ✅ Frontend can integrate with **all `/api/v1/*` endpoints** (mocks where applicable).
> 📄 HTTP responses & status codes consistent with the OpenAPI contract.
> 🔐 Auth team can start now: replace mock auth in HTTP routers with a DB-backed `auth_service`.


### Docs & Tooling

* [x] `README.md`, `docs/api-contract-v1.md` updated
* [x] `.gitignore`, `pre-commit`, `pytest.ini`, `requirements*.txt` configured
* [x] Makefile added (developer commands) and scripts for DB

### Next up

1. **Finish DB layer (ORMs + tables/migrations):** finalize remaining models, generate Alembic migrations, add seed data 
2. **Solver:** 
---

## ANNA

*(tbd)*

## DESPOINA

*(tbd)*
