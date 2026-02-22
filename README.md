````md
# MEDSCHED Web App

> **Status:** Private repository — **All rights reserved**.  
> Publication is subject to the University’s **right of first publication**.  
> No public use or redistribution without the MEDSCHED Team’s written permission.

## Overview

**MEDSCHED** is a web-based application that optimizes medical staff work schedules in Polish hospitals.  
It focuses on individual preferences, legal compliance, and work-life balance to improve both efficiency and physician satisfaction.

## Key Features

- Constraint-based scheduling with **Google OR-Tools (CP-SAT)**
- Supports individual shift preferences and rest-period rules
- Interactive calendars for easy schedule management
- Real-time updates and manual adjustment options
- Diagnostics (fairness, coverage, penalties)
- Export to Excel, PDF, and calendar sync

## Architecture / Tech Stack

- **Backend:** Python **3.11**, FastAPI, OR-Tools
- **Frontend:** React, TypeScript *(planned/parallel work)*
- **Database:** **SQLite (dev)** + **Alembic** migrations; **PostgreSQL (target in prod)**
- **Runtime/Infra:** Uvicorn (dev/prod), Azure (deployment target)

> **Python version:** we standardize on **3.11** for stable wheels (e.g., OR-Tools on Linux/WSL/macOS) and fewer dependency surprises.  
> If you try **3.12**, create a fresh venv and run the full test suite first.

## Project Team

- Anna Orlova
- Aleksandra Muga-Bartkowiak
- Despoina Karli

## Project Status (working draft)

See **[docs/DEV_STATUS.md](docs/DEV_STATUS.md)** for a living overview of what’s done vs. next.

---

## Prerequisites (dev)

- **OS:** **Linux** or **macOS** (or **Windows 11 via WSL2/Ubuntu** running Linux toolchain)
- **Python:** **3.11**
- **Git**

### Quick install helpers

**Linux (Ubuntu 22.04+):**

```bash
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3-pip git
````

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

# 2) Create and activate virtual env (required)
python3.11 -m venv .venv
source .venv/bin/activate

# IMPORTANT: verify you are using the venv interpreter
which python
# expected: .../<repo-folder>/.venv/bin/python

# 3) Install pinned lockfile (stable environment for everyone)
python -m pip install --upgrade pip
python -m pip install -r backend/requirements-dev.txt

# Optional sanity check for broken deps
python -m pip check

# 4) Run the API (dev)
PYTHONPATH=. uvicorn backend.asgi:app --reload

# WSL only (expose to Windows host):
# PYTHONPATH=. uvicorn backend.asgi:app --host 0.0.0.0 --port 8000 --reload

# 5) Open Swagger:
# http://127.0.0.1:8000/docs
```

### Smoke test (recommended)

```bash
source .venv/bin/activate
pytest
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
2. Open:

   * Swagger UI: `http://127.0.0.1:8000/docs`
   * ReDoc: `http://127.0.0.1:8000/redoc`
   * OpenAPI JSON: `http://127.0.0.1:8000/openapi.json`
3. Test endpoints directly in Swagger (**Try it out → Execute**).

**Base URL (dev):** `http://127.0.0.1:8000`
**API prefix:** `/api/v1`

Example (curl):

```bash
curl http://127.0.0.1:8000/api/v1/diagnostics/health
```

---

## CORS (dev)

If the frontend runs on a different origin (e.g., Vite on `http://127.0.0.1:5173`), enable CORS in **`backend/asgi.py`**:

```python
# backend/asgi.py
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .app import create_app  # app factory

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

No local config is required for dev: Alembic and the app fall back to SQLite at `backend/db/sqlite.db`.
If you want to use another DB (e.g., Postgres), set:

```dotenv
DATABASE_URL=postgresql+psycopg://USER:PASS@HOST:5432/DBNAME
```

**Optional variables (not required for local dev):**

* `ALLOWED_ORIGINS` — enable CORS in dev (comma-separated), e.g. `http://127.0.0.1:5173`
* `JWT_SECRET` — dev-only secret for auth (will be used when auth is wired)

---

## API Versioning

All public routes live under **`/api/v1`**.
When the contract evolves, add `/api/v2` alongside `/api/v1` and migrate gradually.

---

## Project Structure (backend)

```text
backend/
  app.py                      # assemble FastAPI; register routers under /api/v1; expose create_app()
  asgi.py                     # imports create_app(), builds FastAPI app, attaches dev CORS
  routers/                    # API surface (APIRouter modules, thin)
  services/                   # application layer (orchestrates core/DB)
  core/                       # solver & domain logic (framework-agnostic, OR-Tools)
  models/                     # ORM (SQLAlchemy) + Pydantic schemas
  db/                         # db engine/session/dependencies
  utils/                      # helpers (validators, loaders, exporters, ...)
  requirements.in             # top-level runtime deps (edited by humans)
  requirements.txt            # pinned runtime lockfile (autogenerated)
  requirements-dev.in         # runtime + dev tools (edited by humans)
  requirements-dev.txt        # pinned dev lockfile (autogenerated)
tests/                        # pytest tests (smoke/unit)
.vscode/                      # editor debug/tasks config (optional)
.env.example                  # sample environment variables
```

---

## Running & Debugging

**Terminal:**

```bash
source .venv/bin/activate
PYTHONPATH=. uvicorn backend.asgi:app --reload
```

**VS Code / Cursor:**

* Ensure interpreter is `.venv/bin/python` (**Python: Select Interpreter**)
* `.vscode/launch.json` runs `uvicorn backend.asgi:app --reload`

---

## Testing

```bash
source .venv/bin/activate
pytest
```

`pytest.ini` sets `pythonpath = .`, so imports like `from backend.app import create_app` work without extra env vars.

---

## Dependencies (reproducible installs)

We use **pip-tools** to keep environments reproducible across the team.

### Files (important)

* `backend/requirements.in` — runtime top-level deps (**human-edited**)
* `backend/requirements.txt` — runtime lockfile (**autogenerated**, pinned versions)
* `backend/requirements-dev.in` — dev top-level deps (**human-edited**; includes `-r requirements.in`)
* `backend/requirements-dev.txt` — dev lockfile (**autogenerated**, pinned versions)

> **Rule:** never edit `backend/requirements*.txt` manually.
> Always change `.in` and regenerate `.txt`.

### Install (recommended for dev)

```bash
python -m pip install -r backend/requirements-dev.txt
```

### Regenerate lockfiles (only when `.in` changes)

> Typically done by one person in a PR. Commit both updated `.txt` files.

```bash
python -m piptools compile --output-file=backend/requirements.txt backend/requirements.in
python -m piptools compile --output-file=backend/requirements-dev.txt backend/requirements-dev.in
```

### Why `.in` and `.txt` look different?

* `.in` lists only packages we chose directly (top-level).
* `.txt` contains **all resolved dependencies** (including transitive ones) with **exact pinned versions**.

### OR-Tools / protobuf stability

We pin OR-Tools + protobuf to a known stable combination.

Pinned by lockfiles (example):

* `ortools==9.12.4544`
* `protobuf==5.29.6`

If you see crashes / import problems again:

1. delete and recreate `.venv`
2. reinstall from `backend/requirements-dev.txt`
3. run `pytest`

---

## Pre-commit (recommended)

```bash
source .venv/bin/activate
pre-commit install
pre-commit run --all-files   # one-time run across repo
```

---

## Troubleshooting

### Pylance shows “Import fastapi could not be resolved”

VS Code is using the wrong interpreter.

1. `Ctrl+Shift+P` → **Python: Select Interpreter**
2. Pick: `<repo>/.venv/bin/python`
3. **Reload Window**

### You installed packages but they are “somewhere else”

Check:

```bash
which python
python -m pip show fastapi
```

Both should point to `.venv`.

### Imports like `backend.*` fail

Run from repo root and use:

```bash
PYTHONPATH=. uvicorn backend.asgi:app --reload
```

### OR-Tools won’t install

Use Python **3.11**. On Linux/macOS you can try:

```bash
python -m pip install --only-binary=:all: ortools
```

---

## License / Publication

This is an **educational project** under a **private** repository.
The University retains a **right of first publication** for the diploma thesis.
No license is granted for public use or redistribution without the MEDSCHED Team’s written permission.

```
::contentReference[oaicite:0]{index=0}
```
