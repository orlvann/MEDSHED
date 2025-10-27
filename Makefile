# Makefile — simple developer commands for the backend
# Usage (from repo root):
#   make help                 # show available commands
#   make app                  # run FastAPI with Uvicorn (dev)
#   make db-upgrade           # apply latest Alembic migrations
#   make db-revision m="..."  # create new autogenerate migration with message
#   make db-check             # QUICK LIVE INSPECTION of the DB (tables, columns, defaults, indexes, FKs) — no files
#   make db-check-one t=...   # inspect a single table (e.g., t=doctors)
#   make db-check-like p=...  # inspect tables by LIKE pattern (e.g., p=doc%)
#   make db-show              # print current rows from doctors/users (joined)
#   make db-dump              # SQL to RECREATE STRUCTURE (DDL only) — use to rebuild an empty DB
#   make db-dump-full         # SQL to RECREATE STRUCTURE + DATA (DDL + INSERTs) → writes dump_full.sql
#   make db-seed              # insert sample data into local DB
#   make db-reset             # drop local SQLite file and re-apply head
#
# Summary:
#   db-check      = quick inspection of what’s in the DB now (human-readable; no files)
#   db-dump       = SQL to recreate the schema (structure only; no data)
#   db-dump-full  = SQL to recreate schema + data (includes INSERTs)
#
# Notes:
# - Commands assume repo root as CWD.
# - PYTHONPATH is set to repo root so absolute imports like `backend.*` work.



.DEFAULT_GOAL := help

.PHONY: help app db-upgrade db-revision db-check db-check-one db-check-like db-seed db-reset db-show db-dump db-dump-full

help: ## Show this help.
	@printf "\nAvailable commands:\n\n"
	@awk 'BEGIN {FS = ":.*## "}; /^[a-zA-Z0-9_.-]+:.*## / {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@printf "\nExamples:\n  make db-revision m=\"add email to doctors\"\n  make db-check-one t=doctors\n  make db-check-like p=doc%%\n  make db-show\n  make db-dump-full\n\n"
app: ## Run FastAPI with Uvicorn (dev).
	PYTHONPATH=. python -m uvicorn backend.asgi:app --reload

db-upgrade: ## Apply latest Alembic migrations to local DB.
	alembic -c backend/alembic.ini upgrade head

db-revision: ## Create a new autogenerate migration; pass message via m="...".
	alembic -c backend/alembic.ini revision --autogenerate -m "$(m)"

db-check: ## Print local SQLite tables & schema (all tables).
	PYTHONPATH=. python scripts/db_check.py

db-check-one: ## Inspect a single table by exact name, usage: make db-check-one t=doctors
	PYTHONPATH=. python scripts/db_check.py --table "$(t)"

db-check-like: ## Inspect tables by LIKE pattern, usage: make db-check-like p=doc%
	PYTHONPATH=. python scripts/db_check.py --like "$(p)"

db-seed: ## Insert sample data into local DB (uses scripts/db_seed.py).
	PYTHONPATH=. python scripts/db_seed.py

db-reset: ## Remove local SQLite DB and re-create schema from head.
	rm -f backend/db/sqlite.db
	alembic -c backend/alembic.ini upgrade head

db-show: ## Print rows from doctors/users (joined)
	PYTHONPATH=. python scripts/db_show.py

db-dump: ## Print schema-only SQL dump (DDL) to stdout.
	PYTHONPATH=. python scripts/db_dump_sql.py

db-dump-full: ## Write full SQL dump (DDL + data) to dump_full.sql.
	PYTHONPATH=. python scripts/db_dump_sql.py --full --out dump_full.sql

