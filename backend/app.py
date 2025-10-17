from fastapi import FastAPI

from .routers import auth, diagnostics, doctors, preferences, schedules

TAGS_METADATA = [
    {"name": "auth", "description": "Login and identity"},
    {"name": "doctors", "description": "Doctors CRUD and listing"},
    {"name": "preferences", "description": "Monthly preference forms"},
    {"name": "schedules", "description": "Generate, edit, publish, export"},
    {"name": "diagnostics", "description": "Schedule analytics and quality"},
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

    @app.get("/", tags=["diagnostics"])
    def root():
        return {"status": "ok", "api": "v1 available at /api/v1"}

    return app
