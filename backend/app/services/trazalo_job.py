"""Ejecución fuera del request de la sincronización con Trazalo.

El botón «Sincronizar Trazalo» del panel de admin llamaba a `sync_trazalo`
dentro del propio request HTTP. Ese sync consulta la base externa de Trazalo y
después reescribe el roster completo (~1200 empleados) en CADA período
sincronizado, así que tarda de decenas de segundos a varios minutos. Mientras
tanto la petición seguía abierta y, además, al estar el endpoint declarado
`async def` con código bloqueante dentro, ocupaba el único hilo del bucle de
eventos de uvicorn: ni siquiera `/health` respondía. Cuando algún intermediario
(Traefik, nginx o el propio navegador) se cansaba de esperar y cerraba el
socket, el `fetch()` del frontend rechazaba con `TypeError: Failed to fetch`,
un mensaje que no dice si el sync falló, sigue corriendo o terminó bien.

Aquí el sync corre en un hilo aparte con su propia sesión de BD; el endpoint
responde 202 al instante y el frontend consulta el resultado por sondeo.

El candado es de proceso, no distribuido: con un único worker de uvicorn (el
despliegue actual) basta para que el scheduler y el botón no se pisen.
"""
import threading
from datetime import datetime, timezone

from app.utils.logger import get_logger

logger = get_logger(__name__)

# idle    -> nunca se ha corrido en este proceso
# running -> hay un sync en curso
# ok / skipped / error -> resultado del último sync terminado
_lock = threading.Lock()
_state: dict = {
    "status": "idle",
    "started_at": None,
    "finished_at": None,
    "duration_seconds": None,
    "triggered_by": None,
    "result": None,
    "error": None,
}


def get_state() -> dict:
    """Copia del estado actual, segura para serializar en una respuesta."""
    with _lock:
        return dict(_state)


def _begin(triggered_by: str) -> bool:
    """Marca el inicio del sync. False si ya había uno en curso."""
    with _lock:
        if _state["status"] == "running":
            return False
        _state.update({
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
            "duration_seconds": None,
            "triggered_by": triggered_by,
            "result": None,
            "error": None,
        })
        return True


def _end(result: dict | None = None, error: str | None = None) -> None:
    finished = datetime.now(timezone.utc)
    with _lock:
        _state["finished_at"] = finished.isoformat()
        if _state["started_at"]:
            inicio = datetime.fromisoformat(_state["started_at"])
            _state["duration_seconds"] = round((finished - inicio).total_seconds(), 1)
        if error is not None:
            _state.update({"status": "error", "error": error, "result": None})
        else:
            result = result or {}
            # sync_trazalo ya distingue ok/skipped/error en el propio dict.
            _state.update({
                "status": result.get("status", "ok"),
                "result": result,
                "error": result.get("error"),
            })


def _execute(triggered_by: str) -> dict:
    from app.database import SessionLocal
    from app.services.trazalo_sync import sync_trazalo

    db = SessionLocal()
    try:
        result = sync_trazalo(db)
        _end(result=result)
        logger.info("trazalo_job_completed", triggered_by=triggered_by, **result)
        return result
    except Exception as e:
        # Sin este catch la excepción moriría en el hilo y el estado se quedaría
        # en "running" para siempre: el frontend sondearía hasta agotarse sin
        # llegar a mostrar nunca el motivo del fallo.
        try:
            db.rollback()
        except Exception:
            pass
        _end(error=str(e))
        logger.error("trazalo_job_error", triggered_by=triggered_by, error=str(e))
        return {"status": "error", "error": str(e)}
    finally:
        db.close()


def start(triggered_by: str) -> tuple[bool, dict]:
    """Lanza el sync en segundo plano. Devuelve (arrancó, estado)."""
    if not _begin(triggered_by):
        logger.info("trazalo_job_ya_en_curso", triggered_by=triggered_by)
        return False, get_state()

    threading.Thread(
        target=_execute,
        args=(triggered_by,),
        name="trazalo-sync",
        daemon=True,
    ).start()
    return True, get_state()


def run_now(triggered_by: str) -> dict:
    """Corre el sync en el hilo actual (scheduler / ETL manual), respetando el
    mismo candado: dos sincronizaciones simultáneas se pisarían los DELETE e
    INSERT por período."""
    if not _begin(triggered_by):
        logger.info("trazalo_job_omitido", reason="ya_en_curso", triggered_by=triggered_by)
        return {"status": "skipped", "reason": "ya hay una sincronización en curso"}
    return _execute(triggered_by)
