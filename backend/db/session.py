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

# SQLite does NOT enforce foreign keys by default.
# Enable PRAGMA foreign_keys so ON DELETE CASCADE actually works.
if DATABASE_URL.startswith("sqlite"):
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

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
