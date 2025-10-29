# MEDSCHED Web App

> **Status:** Private repository — **All rights reserved**.
> Publication is subject to the University’s **right of first publication**.
> No public use or redistribution without the MEDSCHED Team’s written permission.

## Overview

**MEDSCHED** is a web-based application that optimizes medical staff work schedules in Polish hospitals.
It focuses on individual preferences, legal compliance, and work-life balance to improve both efficiency and physician satisfaction.

## Key Features

* Constraint-based scheduling with **Google OR-Tools (CP-SAT)**
* Supports individual shift preferences and rest-period rules
* Interactive calendars for easy schedule management
* Real-time updates and manual adjustment options
* Diagnostics (fairness, coverage, penalties)
* Export to Excel, PDF, and calendar sync

## Architecture / Tech Stack

* **Backend:** Python **3.11**, FastAPI, OR-Tools
* **Frontend:** React, TypeScript *(planned/parallel work)*
* **Database:** **SQLite (dev)** + **Alembic** migrations; **PostgreSQL (target in prod)**
* **Runtime/Infra:** Uvicorn (dev/prod), Azure (deployment target)

> **Python version:** we standardize on **3.11** for stable wheels (e.g., OR-Tools on Linux/WSL/macOS) and fewer dependency surprises.
> If you try **3.12**, create a fresh venv and run the full test suite first. *(CI will pin 3.11 when added.)*

## Project Team

* Anna Orlova
* Aleksandra Muga-Bartkowiak
* Despoina Karli

## Project Status (working draft)

See **[docs/DEV_STATUS.md](docs/DEV_STATUS.md)** for a living overview of what’s done vs. next.


---

## Prerequisites (dev)

* **OS:** **Linux** or **macOS** (or **Windows 11 via WSL2/Ubuntu** running Linux toolchain)
* **Python:** **3.11**
* **Git**

### Quick install helpers

**Linux (Ubuntu 22.04+):**

```bash
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3-pip git
```

**Windows 11 (WSL2 with Ubuntu):**

* Install **WSL** + **Ubuntu** from Microsoft Store, then use the Linux commands above inside Ubuntu.

**macOS (Sonoma/Sequoia):**

```bash
# Install Homebrew if needed: https://brew.sh
brew install python@3.11 git
# If required, expose as python3.11:
# echo 'export PATH="/opt/homebrew/opt/python@3.11/bin:$PATH"' >> ~/.zshrc
```

---

## Quickstart

### Linux / WSL (Ubuntu) & macOS

```bash
# 1) Clone and enter the repo
git clone <YOUR_SSH_OR_HTTPS_URL>.git
cd <repo-folder>

# 2) Fresh virtual env and runtime deps
python3.11 -m venv .venv
source .venv/bin/activate      # zsh/bash both ok on macOS; bash on Linux/WSL
pip install --upgrade pip
pip install -r requirements.txt

# 3) Run the API (dev)
PYTHONPATH=. uvicorn backend.asgi:app --reload

# 4) Open Swagger at:
# http://127.0.0.1:8000/docs
```

---

## Database (dev) quickstart

Local dev uses **SQLite** + **Alembic**:

> No local config needed. By default we use SQLite at `backend/db/sqlite.db`.
> Set `DATABASE_URL` to override (e.g., Postgres).


```bash
make db-upgrade   # create/upgrade schema
make db-seed      # optional: sample users/doctors
make app          # run API and test at /docs
```

For more DB helpers, see **Makefile shortcuts** below.

> For production, `DATABASE_URL` will point to **PostgreSQL** (e.g., in Azure App Settings). **Alembic migrations are shared.**

---

## Makefile shortcuts (dev)

```bash
make help          # list available commands
make app           # run FastAPI (dev)
make db-upgrade    # apply latest Alembic migrations
make db-seed       # insert sample data
make db-check      # inspect SQLite tables & schema
make db-show       # print current doctors/users (joined)
make db-dump       # schema-only SQL dump to stdout
make db-dump-full  # schema + data to dump_full.sql
```

---

## API exploration (without frontend)

1. Start the backend (`make app` or the Quickstart command).
2. Open **Swagger UI**: `http://127.0.0.1:8000/docs`
   Or **ReDoc**: `http://127.0.0.1:8000/redoc`
   Raw OpenAPI JSON: `http://127.0.0.1:8000/openapi.json`
3. Test endpoints directly in Swagger (**Try it out → Execute**).

**Base URL (dev):** `http://127.0.0.1:8000`
**API prefix:** `/api/v1`

Example (curl):

```bash
curl http://127.0.0.1:8000/api/v1/diagnostics/health
```

Example (fetch in FE):

```ts
const res = await fetch("http://127.0.0.1:8000/api/v1/diagnostics/health");
const data = await res.json();
```

> Auth is still mocked in routers, but the **DB layer is ready**. The Auth team can start replacing mocks with a DB-backed `auth_service`.

---

## CORS (dev)

If the frontend runs on a different origin (e.g., Vite on `http://127.0.0.1:5173`), enable CORS in **`backend/asgi.py`** (the file that **imports and builds** the `app`):

```python
# backend/asgi.py
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .app import create_app  # your factory

app: FastAPI = create_app()

allowed = os.getenv("ALLOWED_ORIGINS", "")
origins = [o.strip() for o in allowed.split(",") if o.strip()]

if origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
```

> In production we aim for same-origin (SPA served from backend `/`), so CORS won’t be needed.

---

## Configuration


### 2) Uprość sekcję „Configuration”
Zastąp całą obecną sekcję „Configuration” tym krótkim wariantem:

```md
## Configuration

No local config is required for dev: Alembic and the app fall back to SQLite at `backend/db/sqlite.db`.
If you want to use another DB (e.g., Postgres), set:

```dotenv
DATABASE_URL=postgresql+psycopg://USER:PASS@HOST:5432/DBNAME

**Optional variables (not required for local dev):**
- `ALLOWED_ORIGINS` — enable CORS in dev (comma-separated), e.g. `http://127.0.0.1:5173`.
- `JWT_SECRET` — dev-only secret for auth (will be used when auth is wired).


---

## API Versioning

All public routes live under **`/api/v1`**:

```python
API_V1_PREFIX = "/api/v1"  # Version now → painless /api/v2 later without breaking clients
```

When the contract evolves, add `/api/v2` alongside `/api/v1` and migrate gradually.

---

## Project Structure (backend)

```
backend/
  app.py           # assemble FastAPI; register routers under /api/v1; expose create_app()
  asgi.py          # imports create_app(), builds FastAPI app, attaches dev CORS
  routers/         # API surface (APIRouter modules, thin)
  services/        # application layer (orchestrates core/DB)
  core/            # solver & domain logic (framework-agnostic, OR-Tools)
  models/          # ORM (SQLAlchemy) + Pydantic schemas
  db/              # db engine/session/dependencies
  utils/           # helpers (validators, loaders, exporters, ...)
tests/             # pytest tests (smoke/unit)
.vscode/           # editor debug/tasks config (optional)
.env.example       # sample environment variables
requirements.txt   # runtime deps (short, only top-level libs)
requirements-dev.txt # dev tools (tests, lint, format, hooks)
```

---

## Running & Debugging

**Terminal:**

```bash
source .venv/bin/activate
PYTHONPATH=. uvicorn backend.asgi:app --reload
```

**VS Code / Cursor:**

* `.vscode/launch.json` runs `uvicorn backend.asgi:app --reload`
* Uses your selected interpreter `.venv/bin/python`

**Tasks (optional):**

* `.vscode/tasks.json` → Terminal → *Run Task* → **Run API (uvicorn)**

---

## Testing

```bash
source .venv/bin/activate
pytest
```

`pytest.ini` sets `pythonpath = .`, so imports like `from backend.app import create_app` work without extra env vars.

---

## Dependencies

We keep `requirements.txt` **short** (only top-level libraries). Pip resolves sub-dependencies.

**Runtime (`requirements.txt`):**

* `fastapi` — web framework
* `uvicorn[standard]` — ASGI server; `[standard]` pulls faster libs (**uvloop**, **httptools**) on Linux/WSL/macOS
* `python-dotenv` — loads `.env` config
* `pydantic[email]` — request/response models **+ email validation** (`EmailStr`)
* `ortools` — CP-SAT solver for scheduling
* *(optional later)* `pandas`, `numpy` for reports/analytics

**Dev tools (`requirements-dev.txt`):**

* `pytest` — tests
* `ruff` — fast linter
* `black` — code formatter
* `pre-commit` — runs format/lint **before each git commit** (team consistency)

Enable pre-commit hooks (optional but recommended):

```bash
pip install -r requirements-dev.txt
pre-commit install
pre-commit run --all-files   # one-time run across repo
```

---

## Using Swagger / ReDoc (quick guide)

* Start the backend (`make app`).
* Open **Swagger UI**: **[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)**
* Or **ReDoc**: **[http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)**
* Raw OpenAPI spec: **[http://127.0.0.1:8000/openapi.json](http://127.0.0.1:8000/openapi.json)**
  (Optional) snapshot to file:
  `curl http://127.0.0.1:8000/openapi.json -o docs/openapi-v1.json`

---

## Git Workflow (short)

* Branch per feature: `feat/<name>`
* Small, frequent commits with clear messages
* PR → review → merge

---

## Troubleshooting

* **Debugger can’t find Python** → ensure interpreter is `.venv/bin/python`; recreate venv if needed.
* **Imports like `backend.*` fail** → run from repo root; `PYTHONPATH=.` is already set in `launch.json` / `pytest.ini`.
* **OR-Tools won’t install** → use Python **3.11**. If needed on Linux/macOS:
  `pip install --only-binary=:all: ortools`.

---

## License / Publication

This is an **educational project** under a **private** repository.
The University retains a **right of first publication** for the diploma thesis.
No license is granted for public use or redistribution without the MEDSCHED Team’s written permission.
