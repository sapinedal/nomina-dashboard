"""
Programador automático usando APScheduler.
Ejecuta el proceso ETL el día 30 de cada mes a las 23:00 horas.
"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.utils.logger import get_logger

logger = get_logger(__name__)

_scheduler: BackgroundScheduler | None = None


def _etl_job():
    """Función ejecutada por el scheduler."""
    logger.info("scheduler_job_started")
    db: Session = SessionLocal()
    try:
        from app.services.excel_processor import run_etl_process
        result = run_etl_process(db, trigger_type="scheduled", triggered_by="scheduler")
        logger.info(
            "scheduler_job_completed",
            execution_id=result.id,
            status=result.status,
            records=result.total_records_inserted,
        )
    except Exception as e:
        logger.error("scheduler_job_error", error=str(e))
    finally:
        # El ETL de Excel borra e inserta por archivo_origen, incluidos los
        # períodos que Trazalo ya había sincronizado — re-sincronizar Trazalo
        # después garantiza que siga siendo la fuente autorizada de esos meses.
        db.close()
    _trazalo_job()


def _trazalo_job():
    """Sincroniza novedades de Trazalo (PostgreSQL) hacia novedades_nomina."""
    logger.info("trazalo_scheduler_job_started")
    db: Session = SessionLocal()
    try:
        from app.services.trazalo_sync import sync_trazalo
        result = sync_trazalo(db)
        logger.info("trazalo_scheduler_job_completed", **result)
    except Exception as e:
        logger.error("trazalo_scheduler_job_error", error=str(e))
    finally:
        db.close()


def _on_job_executed(event):
    logger.info("apscheduler_job_executed", job_id=event.job_id)


def _on_job_error(event):
    logger.error("apscheduler_job_error", job_id=event.job_id, exception=str(event.exception))


def get_scheduler() -> BackgroundScheduler:
    """Obtener la instancia global del scheduler."""
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(timezone="America/Bogota")
        _scheduler.add_listener(_on_job_executed, EVENT_JOB_EXECUTED)
        _scheduler.add_listener(_on_job_error, EVENT_JOB_ERROR)
    return _scheduler


def start_scheduler():
    """Iniciar el scheduler con el job mensual configurado."""
    scheduler = get_scheduler()

    # Trigger: día 30 de cada mes a las 23:00
    # Si el mes no tiene día 30 (Feb) se omite ese mes.
    trigger = CronTrigger(
        day=settings.SCHEDULER_DAY,
        hour=settings.SCHEDULER_HOUR,
        minute=settings.SCHEDULER_MINUTE,
        timezone="America/Bogota",
    )

    scheduler.add_job(
        _etl_job,
        trigger=trigger,
        id="monthly_etl",
        name="ETL Mensual - Novedades Nómina",
        replace_existing=True,
        misfire_grace_time=3600,  # 1 hora de gracia si el servidor estaba apagado
        coalesce=True,
    )

    # Sincronización frecuente con Trazalo (novedades en tiempo real de RRHH)
    if settings.TRAZALO_DB_HOST:
        scheduler.add_job(
            _trazalo_job,
            trigger="interval",
            minutes=settings.TRAZALO_SYNC_INTERVAL_MINUTES,
            next_run_time=datetime.now(timezone.utc),  # sync inmediato al arrancar, no esperar 1er intervalo
            id="trazalo_sync",
            name="Sincronización Trazalo",
            replace_existing=True,
            misfire_grace_time=600,
            coalesce=True,
        )

    if not scheduler.running:
        scheduler.start()
        logger.info(
            "scheduler_started",
            day=settings.SCHEDULER_DAY,
            hour=settings.SCHEDULER_HOUR,
            minute=settings.SCHEDULER_MINUTE,
        )

    return scheduler


def stop_scheduler():
    """Detener el scheduler al cerrar la aplicación."""
    scheduler = get_scheduler()
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("scheduler_stopped")


def trigger_manual_etl(db: Session, username: str):
    """Ejecutar el ETL manualmente (desde el panel de administración).
    Encadena la sincronización de Trazalo al final, para que siga siendo la
    fuente autorizada de los períodos que ya sincronizó (el ETL de Excel borra
    e inserta por archivo_origen, sin distinguir origen Excel/Trazalo)."""
    from app.services.excel_processor import run_etl_process
    from app.services.trazalo_sync import sync_trazalo
    logger.info("manual_etl_triggered", by=username)
    result = run_etl_process(db, trigger_type="manual", triggered_by=username)
    try:
        trazalo_result = sync_trazalo(db)
        logger.info("manual_trazalo_sync", **trazalo_result)
    except Exception as e:
        logger.error("manual_trazalo_sync_error", error=str(e))
    return result
