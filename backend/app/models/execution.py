from sqlalchemy import Column, Integer, String, DateTime, Float, Text, Enum, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum
from app.database import Base, _is_sqlite


class ExecutionStatus(str, enum.Enum):
    running = "running"
    completed = "completed"
    failed = "failed"
    error = "error"
    partial = "partial"
    skipped = "skipped"


def _status_col(default_val):
    if _is_sqlite:
        return Column(String(20), default=default_val)
    return Column(Enum(ExecutionStatus), default=ExecutionStatus(default_val))


class ExecutionLog(Base):
    __tablename__ = "execution_logs"

    id = Column(Integer, primary_key=True, index=True)
    started_at = Column(DateTime, server_default=func.now())
    finished_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    status = _status_col("running")
    trigger_type = Column(String(20), default="scheduled")  # scheduled | manual
    triggered_by = Column(String(50), nullable=True)
    total_files_found = Column(Integer, default=0)
    total_files_processed = Column(Integer, default=0)
    total_files_failed = Column(Integer, default=0)
    total_records_inserted = Column(Integer, default=0)
    total_records_updated = Column(Integer, default=0)
    total_records_invalid = Column(Integer, default=0)
    error_summary = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)

    files = relationship("ProcessedFile", back_populates="execution", cascade="all, delete-orphan")


class ProcessedFile(Base):
    __tablename__ = "processed_files"

    id = Column(Integer, primary_key=True, index=True)
    execution_id = Column(Integer, ForeignKey("execution_logs.id"), nullable=False)
    file_name = Column(String(255), nullable=False)
    file_path = Column(String(1024), nullable=False)
    file_size_kb = Column(Float, nullable=True)
    file_modified_at = Column(DateTime(timezone=True), nullable=True)
    processed_at = Column(DateTime(timezone=True), server_default=func.now())
    sheets_found = Column(Integer, default=0)
    sheets_processed = Column(Integer, default=0)
    records_inserted = Column(Integer, default=0)
    records_invalid = Column(Integer, default=0)
    status = Column(String(20), default="ok")  # ok | error | skipped
    error_detail = Column(Text, nullable=True)

    execution = relationship("ExecutionLog", back_populates="files")
