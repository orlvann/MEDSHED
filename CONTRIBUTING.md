# Contributing Guide

Thanks for helping improve **MEDSCHED**! This guide keeps our workflow predictable and low-friction.

---

## TL;DR

- **Python:** 3.11 (team standard)
- **Style:** Black (format), Ruff (lint)
- **Hooks:** pre-commit (runs Black+Ruff before each commit)
- **Branching:** `feature/<name>` / `fix/<name>` / `chore/<name>`
- **PRs:** small, focused, with tests & docs updated

---

## Environment (macOS / Linux / WSL)

```bash
# create & activate venv
python3.11 -m venv .venv
source .venv/bin/activate

# deps
pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-dev.txt

# enable git hooks (format+lint before commits)
pre-commit install
````

Run API (dev):

```bash
PYTHONPATH=. uvicorn backend.asgi:app --reload
# Swagger: http://127.0.0.1:8000/docs
```

Quality & tests:

```bash
ruff check . --fix
black .
pytest
```

---

## Branching

* Base off **main**:

  ```bash
  git checkout main && git pull
  git checkout -b feature/<short-name>
  ```
* Keep branches small and single-purpose:

  * `feature/solver-hard-constraints`
  * `fix/auth-expired-token`
  * `chore/ci-cache`

---

## Commits

* Clear, imperative messages; group related changes:

  * `feat(schedules): add CP-SAT solver wrapper`
  * `fix(auth): handle expired JWT refresh`
  * `chore: tighten .gitignore and add NOTICE`

---

## Pull Requests

* Target: **main**
* Keep PRs small; include only necessary changes
* Request review from ≥1 teammate

**PR checklist (copy into PR body):**

* [ ] Code builds & runs locally
* [ ] Tests added/updated (if applicable)
* [ ] `ruff` and `black` pass; pre-commit ran
* [ ] `docs/api-contract-v1.md` updated (if API changed)
* [ ] `.env.example`/README updated (if config changed)

---

## Code Layout & Style

* **FastAPI routers** thin; call **services/**; keep domain logic in **core/**.
* Public API lives under **`/api/v1`** (see `API_V1_PREFIX`).
* Prefer type hints; keep functions short, testable.
* Handle errors with clear messages and consistent shapes.

---

## Testing

* Use `pytest` + `fastapi.testclient` (or `httpx` for async).
* Add **smoke tests** for new routes and **unit tests** for core logic.
* Keep tests deterministic and isolated (no network; use fakes/mocks).

---

## Docs

* Update **`docs/api-contract-v1.md`** when endpoints, payloads, or status codes change.
* Add examples for requests/responses; mark deprecations clearly.
* Update **README** when setup or workflows change.

---

## Security & Secrets

* **Never** commit secrets. Use `.env` locally; use secret stores in cloud.
* If a secret leaks: **rotate immediately**, invalidate old, document the rotation.
* Sanitize logs and error messages (no sensitive data).

---

## Versioning & Deprecation

* Backwards-incompatible changes go to **`/api/v2`**; keep `/api/v1` during a sunset period.
* Mark deprecated fields/paths in Swagger and docs with **DEPRECATED** and a removal date.

---

## License / Publication

* Private repository — **All rights reserved**.
* University retains **right of first publication** for the thesis.
* No public redistribution without written permission.

---

```
```
