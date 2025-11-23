# backend/asgi.py
# ASGI entrypoint for uvicorn/gunicorn; keep it tiny.
from fastapi.middleware.cors import CORSMiddleware

from .app import create_app
from .config import settings

app = create_app()

# Configure CORS for frontend access (dev only)
# Default to allowing localhost if ALLOWED_ORIGINS not set
allowed_origins_str = settings.ALLOWED_ORIGINS or "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000"
origins = [origin.strip() for origin in allowed_origins_str.split(",") if origin.strip()]

if origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
