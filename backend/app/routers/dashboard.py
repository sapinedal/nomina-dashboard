from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional
from datetime import date

from app.database import get_db
from app.models.user import User
from app.services.auth_service import get_current_user, get_user_areas
from app.services import dashboard_service as svc
from app.schemas.dashboard import KPIResponse, ChartResponse, PaginatedTable, DashboardResponse, AlertsResponse, EmpleadosListaResponse

router = APIRouter(prefix="/api/dashboard", tags=["Tablero"])


def _build_filters(
    fecha_inicio: Optional[date],
    fecha_fin: Optional[date],
    area: Optional[str],
    sede: Optional[str],
    tipo_novedad: Optional[str],
    periodo: Optional[str],
    cedula: Optional[str],
    current_user: User,
) -> dict:
    return {
        "fecha_inicio": fecha_inicio,
        "fecha_fin": fecha_fin,
        "area": area,
        "sede": sede,
        "tipo_novedad": tipo_novedad,
        "periodo": periodo,
        "cedula": cedula,
        # Autorización por área: SIEMPRE calculada server-side desde el usuario
        # autenticado (nunca desde un parámetro de query) -- ver
        # dashboard_service._effective_areas, que la cruza con el filtro de
        # área elegido en el frontend. None = admin/sin restricción.
        "_allowed_areas": get_user_areas(current_user),
    }


@router.get("/kpis", response_model=KPIResponse, summary="Indicadores KPI")
async def get_kpis(
    fecha_inicio: Optional[date] = Query(None, description="Filtro desde fecha"),
    fecha_fin: Optional[date] = Query(None, description="Filtro hasta fecha"),
    area: Optional[str] = Query(None),
    sede: Optional[str] = Query(None),
    tipo_novedad: Optional[str] = Query(None),
    periodo: Optional[str] = Query(None, example="2025-01"),
    cedula: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    filters = _build_filters(fecha_inicio, fecha_fin, area, sede, tipo_novedad, periodo, cedula, current_user)
    return svc.get_kpis(db, filters)


@router.get("/charts/novedades-por-tipo", response_model=ChartResponse)
async def chart_por_tipo(
    fecha_inicio: Optional[date] = Query(None),
    fecha_fin: Optional[date] = Query(None),
    area: Optional[str] = Query(None),
    sede: Optional[str] = Query(None),
    periodo: Optional[str] = Query(None),
    top_n: int = Query(10, ge=3, le=30),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    filters = _build_filters(fecha_inicio, fecha_fin, area, sede, None, periodo, None, current_user)
    return svc.get_novedades_por_tipo(db, filters, top_n)


@router.get("/charts/novedades-por-area", response_model=ChartResponse)
async def chart_por_area(
    fecha_inicio: Optional[date] = Query(None),
    fecha_fin: Optional[date] = Query(None),
    sede: Optional[str] = Query(None),
    tipo_novedad: Optional[str] = Query(None),
    periodo: Optional[str] = Query(None),
    top_n: int = Query(10, ge=3, le=30),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    filters = _build_filters(fecha_inicio, fecha_fin, None, sede, tipo_novedad, periodo, None, current_user)
    return svc.get_novedades_por_area(db, filters, top_n)


@router.get("/charts/tendencia-mensual", response_model=ChartResponse)
async def chart_tendencia(
    fecha_inicio: Optional[date] = Query(None),
    fecha_fin: Optional[date] = Query(None),
    area: Optional[str] = Query(None),
    sede: Optional[str] = Query(None),
    tipo_novedad: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    filters = _build_filters(fecha_inicio, fecha_fin, area, sede, tipo_novedad, None, None, current_user)
    return svc.get_tendencia_mensual(db, filters)


@router.get("/charts/valor-por-area", response_model=ChartResponse)
async def chart_valor_area(
    fecha_inicio: Optional[date] = Query(None),
    fecha_fin: Optional[date] = Query(None),
    sede: Optional[str] = Query(None),
    tipo_novedad: Optional[str] = Query(None),
    periodo: Optional[str] = Query(None),
    top_n: int = Query(10, ge=3, le=30),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    filters = _build_filters(fecha_inicio, fecha_fin, None, sede, tipo_novedad, periodo, None, current_user)
    return svc.get_valor_por_area(db, filters, top_n)


@router.get("/table", response_model=PaginatedTable, summary="Tabla paginada de novedades")
async def get_table(
    fecha_inicio: Optional[date] = Query(None),
    fecha_fin: Optional[date] = Query(None),
    area: Optional[str] = Query(None),
    sede: Optional[str] = Query(None),
    tipo_novedad: Optional[str] = Query(None),
    periodo: Optional[str] = Query(None),
    cedula: Optional[str] = Query(None),
    solo_activos: bool = Query(False, description="Si True, excluye empleados con renuncia o terminación"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=10, le=500),
    sort_by: str = Query("id"),
    sort_dir: str = Query("desc"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    filters = _build_filters(fecha_inicio, fecha_fin, area, sede, tipo_novedad, periodo, cedula, current_user)
    filters["solo_activos"] = solo_activos
    return svc.get_table_data(db, filters, page, page_size, sort_by, sort_dir)


@router.get("/charts/valor-por-categoria", response_model=ChartResponse, summary="Impacto económico calculado por categoría de novedad")
async def chart_valor_categoria(
    fecha_inicio: Optional[date] = Query(None),
    fecha_fin: Optional[date] = Query(None),
    area: Optional[str] = Query(None),
    sede: Optional[str] = Query(None),
    periodo: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    filters = _build_filters(fecha_inicio, fecha_fin, area, sede, None, periodo, None, current_user)
    return svc.get_valor_por_categoria(db, filters)


@router.get("/filter-options", summary="Opciones disponibles para filtros")
async def filter_options(
    panel: Optional[str] = Query(None, description="ausentismo | horas-extras | None (todas las novedades)"),
    periodo: Optional[str] = Query(None, description="Acota áreas/sedes al período (solo aplica junto con panel=ausentismo u horas-extras)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return svc.get_filter_options(db, panel, periodo, allowed_areas=get_user_areas(current_user))


@router.get("/alerts", response_model=AlertsResponse, summary="Motor de alertas y validación")
async def get_alerts(
    area: Optional[str] = Query(None),
    sede: Optional[str] = Query(None),
    periodo: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    filters = {"area": area, "sede": sede, "periodo": periodo, "_allowed_areas": get_user_areas(current_user)}
    return svc.get_alerts(db, filters)


@router.get("/alerts/detalle", summary="Listado detallado de registros con alertas")
async def get_alerts_detalle(
    area: Optional[str] = Query(None),
    sede: Optional[str] = Query(None),
    periodo: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    filters = {"area": area, "sede": sede, "periodo": periodo, "_allowed_areas": get_user_areas(current_user)}
    return svc.get_alerts_detalle(db, filters)


@router.get("/panel/ausentismo", summary="Datos del panel de ausentismo")
async def panel_ausentismo(
    area: Optional[str] = Query(None),
    sede: Optional[str] = Query(None),
    periodo: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    filters = {"area": area, "sede": sede, "periodo": periodo, "_allowed_areas": get_user_areas(current_user)}
    return svc.get_panel_ausentismo(db, filters)


@router.get("/resumen-por-area", summary="Resumen de empleados por área con estado activo/inactivo")
async def resumen_por_area(
    fecha_inicio: Optional[date] = Query(None),
    fecha_fin:    Optional[date] = Query(None),
    area:         Optional[str]  = Query(None),
    sede:         Optional[str]  = Query(None),
    periodo:      Optional[str]  = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    filters = _build_filters(fecha_inicio, fecha_fin, area, sede, None, periodo, None, current_user)
    return svc.get_resumen_por_area(db, filters)


@router.get("/empleados", response_model=EmpleadosListaResponse, summary="Lista de empleados con estado activo/inactivo")
async def get_empleados(
    fecha_inicio: Optional[date] = Query(None),
    fecha_fin: Optional[date] = Query(None),
    area: Optional[str] = Query(None),
    sede: Optional[str] = Query(None),
    tipo_novedad: Optional[str] = Query(None),
    periodo: Optional[str] = Query(None),
    estado: str = Query("todos", description="todos | activo | inactivo"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    filters = _build_filters(fecha_inicio, fecha_fin, area, sede, tipo_novedad, periodo, None, current_user)
    return svc.get_empleados_lista(db, filters, estado)


@router.post("/empleados/detectar-retiros", summary="Detecta y marca retiros automáticos por comparación de archivos")
async def detectar_retiros(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    resultado = svc.detect_and_mark_retirements(db)
    return resultado


@router.get("/panel/horas-extras", summary="Datos del panel de horas extras y recargos")
async def panel_horas_extras(
    area: Optional[str] = Query(None),
    sede: Optional[str] = Query(None),
    periodo: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    filters = {"area": area, "sede": sede, "periodo": periodo, "_allowed_areas": get_user_areas(current_user)}
    return svc.get_panel_horas_extras(db, filters)


@router.get("/panel/horas-extras/detalle", summary="Detalle por empleado de un tipo de HE/recargo")
async def panel_horas_extras_detalle(
    tipo: str = Query(..., description="Tipo de HE/recargo a desglosar (ej. 'RECARGO NOCTURNO')"),
    area: Optional[str] = Query(None),
    sede: Optional[str] = Query(None),
    periodo: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    filters = {"area": area, "sede": sede, "periodo": periodo, "_allowed_areas": get_user_areas(current_user)}
    return svc.get_detalle_horas_extras_tipo(db, filters, tipo)


@router.get("/ausentismo/empleados", summary="Lista detallada de empleados con novedades de ausentismo")
async def empleados_ausentismo(
    area: Optional[str] = Query(None),
    sede: Optional[str] = Query(None),
    periodo: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    filters = {"area": area, "sede": sede, "periodo": periodo, "_allowed_areas": get_user_areas(current_user)}
    return svc.get_empleados_ausentismo(db, filters)
