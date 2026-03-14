import os
from sqlalchemy import create_engine, Column, Integer, String, Text, Float, DateTime
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy.sql import func

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@postgres:5432/appdb")

engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


class AIReport(Base):
    __tablename__ = "ai_reports"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    trigger_type = Column(String(50))   # alert | scheduled | manual
    alert_name = Column(String(255), default="")
    severity = Column(String(50), default="ok")
    summary = Column(Text, default="")
    analysis = Column(Text, default="")
    recommendations = Column(Text, default="")
    duration_seconds = Column(Float, default=0)


def init_db():
    Base.metadata.create_all(bind=engine)


def save_report(data: dict) -> int:
    with Session() as db:
        report = AIReport(**data)
        db.add(report)
        db.commit()
        db.refresh(report)
        return report.id


def get_reports(limit: int = 20) -> list:
    with Session() as db:
        rows = db.query(AIReport).order_by(AIReport.created_at.desc()).limit(limit).all()
        return [
            {
                "id": r.id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "trigger_type": r.trigger_type,
                "alert_name": r.alert_name,
                "severity": r.severity,
                "summary": r.summary,
                "analysis": r.analysis,
                "recommendations": r.recommendations,
                "duration_seconds": r.duration_seconds,
            }
            for r in rows
        ]
