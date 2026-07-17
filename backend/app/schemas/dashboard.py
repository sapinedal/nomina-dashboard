from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import date


class DashboardFilters(BaseModel):
    fecha_inicio: Optional[date] = None
    fecha_fin: Optional[date] = None
    area: Optional[str] = None
    tipo_novedad: Optional[str] = None
    periodo: Optional[str] = None
    cedula: Optional[str] = None


class KPIResponse(BaseModel):
    total_novedades: int
    total_empleados: int
    total_areas: int
    total_tipos_novedad: int
    valor_total: float
    promedio_dias: float
    periodos_disponibles: int
    # Deltas vs período anterior (None si no hay período anterior)
    delta_novedades: Optional[float] = None   # % cambio
    delta_empleados: Optional[float] = None
    delta_valor: Optional[float] = None
    # KPIs adicionales
    total_horas_extras: Optional[float] = None
    total_dias_ausencia: Optional[float] = None
    empleados_he_limite: Optional[int] = None  # empleados > 48h HE
    # Valor calculado desde salarios (todas las novedades)
    valor_calculado: Optional[float] = None
    # Valor monetario de HE y recargos
    valor_horas_extras: Optional[float] = None
    # Valor monetario de incapacidades y licencias
    valor_ausencias: Optional[float] = None
    # Empleados del período sin salario real registrado (excluidos de los
    # valores monetarios, no se les asume ningún salario por defecto)
    empleados_sin_salario: Optional[int] = None
    # Desglose activos / inactivos (basado en última novedad global de cada empleado)
    empleados_activos: Optional[int] = None
    empleados_inactivos: Optional[int] = None


class EmpleadoEstado(BaseModel):
    cedula: str
    nombre: Optional[str]
    area: Optional[str]
    cargo: Optional[str]
    ultimo_periodo: Optional[str]
    ultima_novedad: Optional[str]
    estado: str   # 'activo' | 'inactivo'


class EmpleadosListaResponse(BaseModel):
    total: int
    activos: int
    inactivos: int
    data: List[EmpleadoEstado]


class AlertItem(BaseModel):
    severidad: str          # 'alta' | 'media' | 'baja'
    tipo: str               # 'duplicado' | 'valor_atipico' | 'solapamiento' | 'invalido' | 'he_limite'
    mensaje: str
    cantidad: int = 0
    area: Optional[str] = None


class AlertsResponse(BaseModel):
    total_alertas: int
    alta: int
    media: int
    baja: int
    alertas: List[AlertItem]
    # Embudo ETL
    total_ingresados: int = 0
    total_validos: int = 0
    total_con_alerta: int = 0
    total_invalidos: int = 0


class SerieData(BaseModel):
    label: str
    data: List[Any]
    color: Optional[str] = None


class ChartResponse(BaseModel):
    labels: List[str]
    series: List[SerieData]
    title: str
    chart_type: str  # bar | line | pie | doughnut


class TableRow(BaseModel):
    cedula: Optional[str]
    nombre_empleado: Optional[str]
    area: Optional[str]
    cargo: Optional[str]
    tipo_novedad: Optional[str]
    fecha_inicio: Optional[date]
    fecha_fin: Optional[date]
    dias: Optional[float]
    valor: Optional[float]
    periodo: Optional[str]
    estado: Optional[str]
    archivo_origen: str
    hoja_origen: str

    model_config = {"from_attributes": True}


class PaginatedTable(BaseModel):
    total: int
    page: int
    page_size: int
    data: List[Dict[str, Any]]


class DashboardResponse(BaseModel):
    kpis: KPIResponse
    novedades_por_tipo: ChartResponse
    novedades_por_area: ChartResponse
    tendencia_mensual: ChartResponse
    valor_por_area: ChartResponse
