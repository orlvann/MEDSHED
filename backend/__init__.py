"""Backend root package: FastAPI modular monolith.
Routers (HTTP) → Services (business) → Core (solver/analytics) → DB (ORM).
Keep HTTP-free logic out of routers; keep DB-free logic in core."""
