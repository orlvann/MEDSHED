# backend/models/ORM/doctor.py
from sqlalchemy import Boolean, Column, Integer, String

from backend.db.session import Base


class Doctor(Base):
    __tablename__ = "doctors"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String, nullable=False)
    is_specialist = Column(Boolean, nullable=False, default=False)
