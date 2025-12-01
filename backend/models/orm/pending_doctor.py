# backend/models/orm/pending_doctor.py
"""
PendingDoctor ORM Model.

Represents doctor registration requests awaiting admin approval.
Once approved, a Doctor and User record will be created, and the pending record will be deleted.
If rejected, the pending record is simply deleted.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from backend.db.session import Base


class PendingDoctor(Base):
    """
    Pending doctor registration awaiting admin approval.
    
    Workflow:
    1. Doctor submits registration (POST /api/v1/doctors/register)
    2. Admin reviews in pending doctors management page
    3. Admin approves -> creates Doctor + User, sends welcome email, deletes pending
    4. Admin rejects -> deletes pending record
    """
    
    __tablename__ = "pending_doctors"
    
    # Identity
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    
    # Audit
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        nullable=False, 
        server_default=func.now()
    )
    
    __table_args__ = (
        # Email must be unique among pending registrations
        UniqueConstraint("email", name="uq_pending_doctors_email"),
        # Index for faster email lookups
        Index("ix_pending_doctors_email", "email"),
    )
    
    def __repr__(self) -> str:
        return f"<PendingDoctor id={self.id} email={self.email} name={self.first_name} {self.last_name}>"

