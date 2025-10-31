# backend/app.py
from fastapi import FastAPI

from .routers import auth, availability, diagnostics, doctors, preferences, schedules

TAGS_METADATA = [
    {"name": "auth", "description": "Login and identity"},
    {"name": "doctors", "description": "Doctors CRUD and listing"},
    {
        "name": "preferences:admin",
        "description": "Monthly preference forms — ADMIN path (manage others, deadlines, history)",
    },
    {"name": "preferences:doctor", "description": "My monthly preferences — DOCTOR path (mine-only undo/redo)"},
    {"name": "availability", "description": "Pre-flight coverage check (availability overview & day drill-down)"},
    {
        "name": "schedules:admin",
        "description": "Schedules — ADMIN path (generate, edit, checkpoints, publish, rollback)",
    },
    {"name": "schedules:doctor", "description": "Schedules — DOCTOR path (read published, my assignments, export)"},
    {"name": "diagnostics", "description": "Schedule analytics and quality"},
    {
        "name": "schedules:export",
        "description": "Unified export for admins & doctors (pointer-based, xlsx/pdf)",
    },
]


def create_app() -> FastAPI:
    app = FastAPI(
        title="MedSchedApp API",
        version="0.1.0",
        description="DRAFT v1 — shapes may change",
        openapi_tags=TAGS_METADATA,
        docs_url="/docs",
        redoc_url="/redoc",
    )
    app.include_router(auth.router)
    app.include_router(doctors.router)
    app.include_router(preferences.router)
    app.include_router(schedules.router)
    app.include_router(diagnostics.router)
    app.include_router(availability.router)

    # Hide root from OpenAPI to keep docs tidy
    @app.get("/", include_in_schema=False)
    def root():
        return {"status": "ok", "api": "v1 available at /api/v1"}

    return app
