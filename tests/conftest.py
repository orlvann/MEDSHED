# tests/conftest.py
"""
Global pytest fixtures for DB-backed tests (services / ORM).

Goal:
- Each test gets a fresh in-memory SQLite database.
- SchedulingService uses this DB via monkeypatched SessionLocal.

IMPORTANT:
- This is separate from tests/solver/conftest.py (solver tests are DB-free).
"""

from __future__ import annotations

from typing import Generator

import pytest
from sqlalchemy import Boolean, Integer, String, create_engine
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

import backend.db.session as db_session_module
import backend.services.scheduling_service as scheduling_service_module

# Import ORM models so their tables are registered in Base.metadata BEFORE create_all().
# Without this, create_all() might create an empty DB with missing tables.
from backend.models.orm.doctor import Doctor  # noqa: F401
from backend.models.orm.preference import (  # noqa: F401
    PreferenceDeadline,
    PreferencePointer,
    PreferenceVersion,
    PreferenceWorking,
)
from backend.models.orm.schedule import (  # noqa: F401
    ScheduleDiagnostics,
    SchedulePointer,
    ScheduleVersion,
    ScheduleWorking,
)

# ---------------------------------------------------------------------------
# Minimal Users table for tests (ONLY if not already present)
# ---------------------------------------------------------------------------
# Some projects already have a real User ORM model imported somewhere,
# which registers "users" table in Base.metadata.
# In that case we MUST NOT define it again.
if "users" not in db_session_module.Base.metadata.tables:

    class TestUser(db_session_module.Base):
        __tablename__ = "users"

        id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

        # Optional extra fields (not required, but harmless).
        email: Mapped[str | None] = mapped_column(String(320), nullable=True)
        is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


@pytest.fixture()
def db_engine():
    """
    Create a brand new in-memory SQLite engine for a single test.

    StaticPool is important:
    - it keeps the same connection alive for the whole test,
    - so the in-memory DB does not "disappear" between sessions.
    """
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    return engine


@pytest.fixture()
def db_session(db_engine) -> Generator[Session, None, None]:
    """
    Provide a SQLAlchemy Session bound to the test engine,
    and create/drop all tables around the test.

    Also monkeypatch SessionLocal so services use the test DB.
    """
    # 1) Create all tables for this test
    db_session_module.Base.metadata.create_all(bind=db_engine)

    # 2) Create a sessionmaker bound to the test engine
    TestingSessionLocal = sessionmaker(bind=db_engine, autoflush=False, autocommit=False, future=True)

    # 3) Monkeypatch SessionLocal in BOTH places:
    #    - backend.db.session.SessionLocal (source)
    #    - backend.services.scheduling_service.SessionLocal (imported name used by the service)
    db_session_module.SessionLocal = TestingSessionLocal
    scheduling_service_module.SessionLocal = TestingSessionLocal

    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        # 4) Drop all tables after the test to keep it isolated
        db_session_module.Base.metadata.drop_all(bind=db_engine)
