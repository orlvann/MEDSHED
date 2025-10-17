# backend/asgi.py
# ASGI entrypoint for uvicorn/gunicorn; keep it tiny.
from .app import create_app

app = create_app()
