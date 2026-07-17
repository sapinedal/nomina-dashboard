from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from app.models.execution import ExecutionStatus


class ProcessedFileResponse(BaseModel):
    id: int
    file_name: str
    file_size_kb: Optional[float]
    file_modified_at: Optional[datetime]
    processed_at: datetime
    sheets_found: int
    sheets_processed: int
    records_inserted: int
    records_invalid: int
    status: str
    error_detail: Optional[str]

    model_config = {"from_attributes": True}


class ExecutionLogResponse(BaseModel):
    id: int
    started_at: datetime
    finished_at: Optional[datetime]
    duration_seconds: Optional[float]
    status: ExecutionStatus
    trigger_type: str
    triggered_by: Optional[str]
    total_files_found: int
    total_files_processed: int
    total_files_failed: int
    total_records_inserted: int
    total_records_updated: int
    total_records_invalid: int
    error_summary: Optional[str]
    files: List[ProcessedFileResponse] = []

    model_config = {"from_attributes": True}


class ExecutionSummary(BaseModel):
    id: int
    started_at: datetime
    status: ExecutionStatus
    trigger_type: str
    total_files_processed: int
    total_records_inserted: int
    duration_seconds: Optional[float]

    model_config = {"from_attributes": True}
