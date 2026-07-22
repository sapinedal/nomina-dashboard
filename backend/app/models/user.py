from sqlalchemy import Column, Integer, String, Boolean, DateTime, Enum, ForeignKey, UniqueConstraint, Index
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum
from app.database import Base, _is_sqlite


class UserRole(str, enum.Enum):
    admin = "admin"
    analyst = "analyst"
    readonly = "readonly"


def _role_col():
    if _is_sqlite:
        return Column(String(20), default="readonly", nullable=False)
    return Column(Enum(UserRole), default=UserRole.readonly, nullable=False)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(120), unique=True, nullable=False)
    full_name = Column(String(150), nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = _role_col()
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    last_login = Column(DateTime(timezone=True), nullable=True)

    area_assignments = relationship("UserArea", cascade="all, delete-orphan", back_populates="user")

    @property
    def areas(self) -> list[str]:
        """Nombres de área planos, para que UserResponse (Pydantic,
        from_attributes=True) los tome directo sin serializar objetos
        UserArea. La relación ORM real es `area_assignments`."""
        return [ua.area for ua in self.area_assignments]


class UserArea(Base):
    """Autorización por área: qué áreas puede ver/gestionar un usuario no-admin.

    `area` es texto libre (mismo valor que novedades_nomina.area) -- no existe
    un catálogo normalizado de áreas en este sistema, así que no se agrega uno
    solo para esto (el resto de la app ya trata las áreas como valores
    dinámicos derivados de los datos, ver dashboard_service.get_filter_options).

    Sin columna `active`: eliminar un área asignada es un DELETE real, no un
    soft-delete -- no hay necesidad de conservar el historial de remociones a
    nivel de fila (eso es responsabilidad de audit_logs si se necesita).
    """
    __tablename__ = "user_areas"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    area = Column(String(200), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    created_by = Column(String(50), nullable=True)

    user = relationship("User", back_populates="area_assignments")

    __table_args__ = (
        UniqueConstraint("user_id", "area", name="uq_user_areas_user_area"),
        Index("ix_user_areas_area", "area"),
    )
