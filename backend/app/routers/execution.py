from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app.models.user import User
from app.models.execution import ExecutionLog
from app.services.auth_service import get_current_user, require_admin
from app.services.scheduler import trigger_manual_etl
from app.schemas.execution import ExecutionLogResponse, ExecutionSummary

router = APIRouter(prefix="/api/execution", tags=["Ejecuciones"])


@router.get("/history", summary="Historial de ejecuciones (paginado)")
async def get_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = db.query(ExecutionLog).order_by(ExecutionLog.started_at.desc())
    total = q.count()
    items = q.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": r.id,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                "duration_seconds": r.duration_seconds,
                "status": str(r.status.value) if hasattr(r.status, "value") else str(r.status),
                "trigger_type": r.trigger_type,
                "triggered_by": r.triggered_by,
                "files_processed": r.total_files_processed or 0,
                "sheets_processed": sum(f.sheets_processed or 0 for f in r.files),
                "records_processed": r.total_records_inserted or 0,
                "errors_count": r.total_files_failed or 0,
                "error_message": r.error_summary,
            }
            for r in items
        ],
    }


@router.get("/{execution_id}", response_model=ExecutionLogResponse, summary="Detalle de ejecución")
async def get_execution(
    execution_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    record = db.query(ExecutionLog).filter(ExecutionLog.id == execution_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Ejecución no encontrada")
    return record


@router.post("/trigger", summary="Disparar proceso ETL manualmente (solo Admin)")
async def trigger_etl(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """
    Inicia el proceso ETL inmediatamente en segundo plano.
    Solo disponible para administradores.
    """
    def run_in_bg():
        from app.database import SessionLocal
        bg_db = SessionLocal()
        try:
            trigger_manual_etl(bg_db, current_user.username)
        finally:
            bg_db.close()

    background_tasks.add_task(run_in_bg)
    return {"message": "Proceso ETL iniciado en segundo plano", "triggered_by": current_user.username}


@router.post("/trigger-trazalo", summary="Sincronizar Trazalo manualmente (solo Admin)")
async def trigger_trazalo(
    current_user: User = Depends(require_admin),
):
    """Ejecuta la sincronización con Trazalo (PostgreSQL) inmediatamente."""
    from app.database import SessionLocal
    from app.services.trazalo_sync import sync_trazalo
    db = SessionLocal()
    try:
        result = sync_trazalo(db)
        return result
    finally:
        db.close()
