## ✅ Dev Status – Backend (current milestone)

### Core Setup

* [x] Project layout finalized (`backend/`, `routers/`, `models/schemas`, `docs/`)
* [x] Unified API prefix **`/api/v1`** for all routers
* [x] FastAPI app runs cleanly (`uvicorn backend.asgi:app --reload`)
* [x] Swagger & ReDoc generate full OpenAPI spec (`/docs`, `/redoc`)
* [x] Health endpoint working → `{"status": "ok", "api": "v1 available at /api/v1"}`

### Routers implemented (mock data, full shape)

* [x] **Auth** — `/auth/login`, `/auth/me`
* [x] **Doctors** — CRUD endpoints with pagination/filtering
* [x] **Preferences** — full lifecycle (`get`, `upsert`, `patch`, `submit`, `revert`, `audit`, `summary`)
* [x] **Schedules** — `generate`, `get`, `patch`, `publish`, `export` (`.xlsx`, `.pdf`)
* [x] **Diagnostics** — `GET /schedules/{sid}/diagnostics`
* [x] Response models aligned with OpenAPI schema (verified in Swagger)

### Tooling & Docs

* [x] `.gitignore`, `.pre-commit`, `pytest.ini`, `.vscode`, `requirements*.txt` configured
* [x] `README.md` and `docs/api-contract-v1.md` updated to match OpenAPI
* [x] `NOTICE` and `CONTRIBUTING.md` added

### Integration status

> ✅ Frontend can already integrate with **all `/api/v1/*` endpoints** using mock data.
> 🚫 Auth & DB persistence not yet implemented (no JWT, in-memory data only).
> 📄 HTTP responses and status codes consistent with Swagger spec.

---
