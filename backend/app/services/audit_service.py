"""Registro de auditoría genérico (ver app.models.audit_log.AuditLog).

No lanza si falla: auditar es una función auxiliar, no debe tumbar la
operación real (crear/editar/eliminar un usuario) por un problema al
escribir el log. Mismo criterio de fail-open ya usado en revoke_token/
_is_blacklisted (auth_service) para Redis -- aquí aplicado a la escritura
del audit log.
"""
import json
from typing import Optional, Any
from sqlalchemy.orm import Session
from fastapi import Request

from app.models.audit_log import AuditLog
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _client_ip(request: Optional[Request]) -> Optional[str]:
    if request is None:
        return None
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        # Mismo criterio que app.middleware.rate_limit.client_ip: la ÚLTIMA
        # entrada es la única que nginx garantiza y el cliente no puede falsificar.
        return xff.split(",")[-1].strip()
    return request.client.host if request.client else None


def log_audit(
    db: Session,
    entity_type: str,
    entity_id: int,
    action: str,
    actor_username: Optional[str],
    changes: Optional[dict[str, Any]] = None,
    request: Optional[Request] = None,
) -> None:
    try:
        entry = AuditLog(
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            actor_username=actor_username,
            changes=json.dumps(changes, default=str, ensure_ascii=False) if changes else None,
            ip_address=_client_ip(request),
        )
        db.add(entry)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning("audit_log_failed", entity_type=entity_type, entity_id=entity_id, action=action, error=str(e))
