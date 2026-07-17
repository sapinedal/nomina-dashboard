import logging
import structlog
import sys
import os
from pathlib import Path
from app.config import settings


def setup_logging():
    """Configurar logging estructurado para la aplicación."""
    log_dir = Path(settings.LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)

    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    # Configuración del procesador structlog
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Handler para archivo
    file_handler = logging.FileHandler(
        log_dir / "nomina_dashboard.log", encoding="utf-8"
    )
    file_handler.setLevel(log_level)

    # Handler para consola
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)

    # Configuración raíz
    logging.basicConfig(
        level=log_level,
        handlers=[file_handler, console_handler],
        format="%(message)s",
    )


def get_logger(name: str = __name__):
    return structlog.get_logger(name)
