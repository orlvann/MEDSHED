# backend/db/session.py
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# Load .env for local dev
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///backend/db/sqlite.db")

# For SQLite, turn off check_same_thread for multi-threaded (e.g., FastAPI) usage
connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, echo=False, connect_args=connect_args)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    """Base class for ORM models."""

    pass


def get_db():
    """
    FastAPI-style dependency:
    yields a SQLAlchemy session and closes it after the request.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
