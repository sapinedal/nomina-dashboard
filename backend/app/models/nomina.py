from sqlalchemy import Column, Integer, String, DateTime, Date, Float, Text, Numeric, Index
from sqlalchemy.sql import func
from app.database import Base


class NovedadNomina(Base):
    """
    Tabla consolidada de novedades de nómina.
    Las columnas cubren los campos típicos de los archivos Excel del CONSOLIDADO.
    Los campos desconocidos se almacenan en columnas_extra (JSON).
    """
    __tablename__ = "novedades_nomina"

    id = Column(Integer, primary_key=True, index=True)

    # Metadatos de trazabilidad
    archivo_origen = Column(String(255), nullable=False, index=True)
    hoja_origen = Column(String(255), nullable=False)
    fecha_procesamiento = Column(DateTime(timezone=True), server_default=func.now())
    fecha_modificacion_archivo = Column(DateTime(timezone=True), nullable=True)
    execution_id = Column(Integer, nullable=True, index=True)

    # Campos de nómina (normalización de columnas del Excel)
    cedula = Column(String(30), nullable=True, index=True)
    nombre_empleado = Column(String(200), nullable=True)
    area = Column(String(200), nullable=True, index=True)   # departamento / hoja
    sede = Column(String(200), nullable=True, index=True)   # ubicación física homologada
    cargo = Column(String(200), nullable=True)
    tipo_novedad = Column(String(150), nullable=True, index=True)
    descripcion_novedad = Column(Text, nullable=True)
    fecha_inicio = Column(Date, nullable=True)
    fecha_fin = Column(Date, nullable=True)
    dias = Column(Float, nullable=True)   # cantidad numérica (días, horas o valor según unidad)
    unidad = Column(String(10), nullable=True)  # 'dias' | 'horas' | 'valor'
    valor = Column(Numeric(18, 2), nullable=True)
    periodo = Column(String(20), nullable=True, index=True)   # YYYY-MM
    estado = Column(String(50), nullable=True)
    observaciones = Column(Text, nullable=True)

    # Columnas adicionales en formato JSON (campos no estándar)
    columnas_extra = Column(Text, nullable=True)  # JSON string

    # Control de calidad
    es_valido = Column(Integer, default=1)        # 1=válido, 0=inválido
    razon_invalido = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_nomina_cedula_periodo", "cedula", "periodo"),
        Index("ix_nomina_area_tipo", "area", "tipo_novedad"),
        Index("ix_nomina_fecha_inicio", "fecha_inicio"),
    )
