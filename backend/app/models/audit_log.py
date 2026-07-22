from sqlalchemy import Column, Integer, String, DateTime, Text, Index
from sqlalchemy.sql import func
from app.database import Base


class AuditLog(Base):
    """Registro de auditoría genérico, reutilizable para cualquier entidad
    (no acoplado a `users` -- pensado para crecer a otras entidades
    administrativas sin necesitar una tabla nueva por cada una)."""
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    entity_type = Column(String(50), nullable=False)   # ej. "user"
    entity_id = Column(Integer, nullable=False)
    action = Column(String(30), nullable=False)         # create | update | delete | areas_changed
    actor_username = Column(String(50), nullable=True)  # quién hizo el cambio (None si el actor ya no existe)
    changes = Column(Text, nullable=True)                # JSON: {"campo": {"antes": ..., "despues": ...}}
    ip_address = Column(String(45), nullable=True)       # IPv4/IPv6
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_audit_entity", "entity_type", "entity_id"),
        Index("ix_audit_created_at", "created_at"),
    )
