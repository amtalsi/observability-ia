from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.sql import func
from database import Base


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    description = Column(String(1000))
    status = Column(String(50), default="pending")  # pending | processing | done | failed
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
