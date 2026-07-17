"""
Servicio de consultas para los tableros estadísticos.
"""
from typing import Optional, Any
from datetime import date
import re
from sqlalchemy.orm import Session
from sqlalchemy import func, text, cast, Float, distinct

from app.models.nomina import NovedadNomina
from app.schemas.dashboard import (
    EmpleadoEstado, EmpleadosListaResponse,
    KPIResponse, ChartResponse, SerieData, PaginatedTable,
    AlertItem, AlertsResponse,
)

_MESES_ES = {
    'ENERO': '01', 'FEBRERO': '02', 'MARZO': '03', 'ABRIL': '04',
    'MAYO': '05', 'JUNIO': '06', 'JULIO': '07', 'AGOSTO': '08',
    'SEPTIEMBRE': '09', 'OCTUBRE': '10', 'NOVIEMBRE': '11', 'DICIEMBRE': '12',
    'ABRI': '04',   # nombre truncado en algunos archivos
}

def _archivo_to_periodo(arch: str) -> Optional[str]:
    """Parsea nombres de archivo a 'YYYY-MM'.
    Soporta:
      - 'CONSOLIDADO ... MAYO  2026.xlsx' → '2026-05'
      - '052026.xlsx'                     → '2026-05'  (MMYYYY)
    """
    if not arch:
        return None
    # Formato numérico: MMYYYY.xlsx
    m_num = re.match(r'^(\d{2})(20\d{2})(?:\.xlsx|[_\s])', arch, re.IGNORECASE)
    if m_num:
        mes, year = m_num.group(1), m_num.group(2)
        if 1 <= int(mes) <= 12:
            return f"{year}-{mes}"
    arch_up = arch.upper()
    year_m = re.search(r'\b(20\d{2})\b', arch_up)
    if not year_m:
        return None
    year = year_m.group(1)
    mes_num = next((num for mes, num in _MESES_ES.items() if mes in arch_up), None)
    return f"{year}-{mes_num}" if mes_num else None


def _max_periodo_por_cedula(db: Session, max_per: str) -> dict[str, str]:
    """
    Para cada cédula, devuelve el período más reciente derivado del
    archivo_origen en que apareció, sin superar max_per.
    """
    rows = db.execute(text("""
        SELECT DISTINCT cedula, archivo_origen FROM novedades_nomina
        WHERE es_valido = 1
          AND cedula IS NOT NULL
          AND archivo_origen IS NOT NULL
          AND archivo_origen != 'REGISTRO MANUAL'
    """)).fetchall()

    result: dict[str, str] = {}
    for r in rows:
        per = _archivo_to_periodo(r.archivo_origen)
        if not per or per > max_per:
            continue
        if r.cedula not in result or per > result[r.cedula]:
            result[r.cedula] = per
    return result


def _max_periodo_archivos(db: Session) -> Optional[str]:
    """
    Deriva el último período cargado desde los nombres de archivo en la BD.
    Soporta formato corto (052026.xlsx → 2026-05) y largo (MAYO 2026.xlsx).
    """
    archivos = db.execute(text(
        "SELECT DISTINCT archivo_origen FROM novedades_nomina "
        "WHERE archivo_origen IS NOT NULL "
        "  AND archivo_origen NOT IN ('REGISTRO MANUAL', 'RETIRO AUTOMATICO')"
    )).scalars().all()

    max_periodo: Optional[str] = None
    for arch in archivos:
        per = _archivo_to_periodo(arch)
        if per and (max_periodo is None or per > max_periodo):
            max_periodo = per
    return max_periodo


def detect_and_mark_retirements(db: Session) -> dict:
    """
    Compara empleados en archivos consecutivos (orden cronológico).
    Los que desaparecen sin tener retiro registrado reciben RENUNCIA
    con archivo_origen='RETIRO AUTOMATICO'.  Es idempotente.
    """
    from collections import defaultdict

    # 1. Borrar retiros automáticos previos y recomputar desde cero
    db.execute(text("DELETE FROM novedades_nomina WHERE archivo_origen = 'RETIRO AUTOMATICO'"))
    db.commit()

    # 2. Una sola consulta: (archivo_origen, cedula) para todos los registros válidos
    filas = db.execute(text("""
        SELECT archivo_origen, cedula
        FROM novedades_nomina
        WHERE es_valido = 1
          AND archivo_origen IS NOT NULL
          AND archivo_origen NOT IN ('REGISTRO MANUAL', 'RETIRO AUTOMATICO')
          AND cedula IS NOT NULL
    """)).fetchall()

    # 3. Agrupar cédulas por período (unión de todos los archivos del mismo mes)
    periodo_empleados: dict = defaultdict(set)
    for arch, ced in filas:
        per = _archivo_to_periodo(arch)
        if per:
            periodo_empleados[per].add(ced)

    periodos = sorted(periodo_empleados.keys())
    if len(periodos) < 2:
        return {"retiros_insertados": 0, "periodos_analizados": len(periodos)}

    # 4. Cédulas que YA tienen retiro registrado válido (manual)
    retirados_manual = set(db.execute(text("""
        SELECT DISTINCT cedula FROM novedades_nomina
        WHERE cedula IS NOT NULL AND es_valido = 1
          AND (LOWER(tipo_novedad) LIKE '%renuncia%'
               OR LOWER(tipo_novedad) LIKE '%terminacion%')
          AND archivo_origen != 'RETIRO AUTOMATICO'
    """)).scalars().all())

    # 5. Info de empleados en una sola query (para llenar el registro de retiro)
    info_rows = db.execute(text("""
        SELECT cedula, MAX(nombre_empleado) AS nombre, MAX(area) AS area
        FROM novedades_nomina
        WHERE cedula IS NOT NULL AND nombre_empleado IS NOT NULL
        GROUP BY cedula
    """)).fetchall()
    info_emp = {r.cedula: (r.nombre, r.area) for r in info_rows}

    # 6. Último período donde aparece cada cédula (para filtrar reapariciones)
    #    Un empleado que desaparece un mes pero vuelve no es un retiro.
    ced_ultimo_periodo: dict = {}
    for per in periodos:
        for ced in periodo_empleados[per]:
            if per > ced_ultimo_periodo.get(ced, ''):
                ced_ultimo_periodo[ced] = per

    ultimo_periodo_global = periodos[-1]

    # 7. Recorrer pares consecutivos: marcar solo si el empleado
    #    NUNCA vuelve a aparecer en los archivos (no hay reapariciones)
    marcados: set = set(retirados_manual)
    nuevos: list = []

    for i in range(len(periodos) - 1):
        pa = periodos[i]
        pb = periodos[i + 1]
        for ced in sorted(periodo_empleados[pa] - periodo_empleados[pb]):
            if ced in marcados:
                continue
            # Solo marcar si el último período conocido fue 'pa'
            # (es decir, no volvió a aparecer en ningún archivo posterior)
            if ced_ultimo_periodo.get(ced, '') != pa:
                continue
            nombre, area = info_emp.get(ced, (None, None))
            nuevos.append({
                "cedula":               ced,
                "nombre_empleado":      nombre,
                "area":                 area,
                "tipo_novedad":         "RENUNCIA",
                "descripcion_novedad":  "RETIRO AUTOMATICO",
                "periodo":              pb,
                "archivo_origen":       "RETIRO AUTOMATICO",
                "hoja_origen":          "RETIRO AUTOMATICO",
                "es_valido":            1,
                "razon_invalido":       None,
                "sede":                 None,
                "cargo":                None,
                "fecha_inicio":         None,
                "fecha_fin":            None,
                "dias":                 None,
                "unidad":               None,
                "valor":                None,
                "estado":               None,
                "observaciones":        None,
                "columnas_extra":       None,
                "fecha_modificacion_archivo": None,
                "execution_id":         None,
            })
            marcados.add(ced)

    if nuevos:
        db.bulk_insert_mappings(NovedadNomina, nuevos)
        db.commit()

    return {
        "retiros_insertados": len(nuevos),
        "periodos_analizados": len(periodos),
        "primer_periodo":      periodos[0],
        "ultimo_periodo":      periodos[-1],
    }


PALETTE = [
    "#4F81BD", "#C0504D", "#9BBB59", "#8064A2",
    "#4BACC6", "#F79646", "#2C4770", "#A9373B",
]


def _apply_filters(query, filters: dict):
    if filters.get("fecha_inicio"):
        query = query.filter(NovedadNomina.fecha_inicio >= filters["fecha_inicio"])
    if filters.get("fecha_fin"):
        query = query.filter(NovedadNomina.fecha_fin <= filters["fecha_fin"])
    if filters.get("area"):
        query = query.filter(NovedadNomina.area == filters["area"])
    if filters.get("sede"):
        query = query.filter(NovedadNomina.sede == filters["sede"])
    if filters.get("tipo_novedad"):
        query = query.filter(NovedadNomina.tipo_novedad.ilike(f"%{filters['tipo_novedad']}%"))
    if filters.get("periodo"):
        query = query.filter(NovedadNomina.periodo == filters["periodo"])
    if filters.get("cedula"):
        query = query.filter(NovedadNomina.cedula == filters["cedula"])
    if filters.get("solo_activos"):
        # Excluir cedulas que tienen CUALQUIER registro de renuncia o terminación
        from sqlalchemy import select as sa_select
        cedulas_retiradas = sa_select(NovedadNomina.cedula).where(
            NovedadNomina.tipo_novedad.ilike("%renuncia%") |
            NovedadNomina.tipo_novedad.ilike("%terminacion%")
        ).distinct()
        query = query.filter(~NovedadNomina.cedula.in_(cedulas_retiradas))
    return query.filter(NovedadNomina.es_valido == 1)


def _prev_periodo(periodo: str) -> Optional[str]:
    """Dado 'YYYY-MM' devuelve el mes anterior."""
    try:
        year, month = int(periodo[:4]), int(periodo[5:7])
        month -= 1
        if month == 0:
            month, year = 12, year - 1
        return f"{year}-{month:02d}"
    except Exception:
        return None


def _pct_change(current: float, previous: float) -> Optional[float]:
    if previous == 0:
        return None
    return round((current - previous) / previous * 100, 1)


def get_kpis(db: Session, filters: dict) -> KPIResponse:
    # El Panel Ejecutivo se basa en el ARCHIVO del período (MMYYYY.xlsx), no en el
    # campo `periodo` de cada registro. Así todos los KPIs cuentan los empleados y
    # novedades reales del mes, de forma consistente con los demás paneles.
    periodo_filter = filters.get("periodo")
    max_per_arch   = _max_periodo_archivos(db)
    if periodo_filter:
        año, mes = periodo_filter.split("-")
        arch_activos = f"{mes}{año}.xlsx"
    elif max_per_arch:
        año, mes = max_per_arch.split("-")
        arch_activos = f"{mes}{año}.xlsx"
    else:
        arch_activos = None

    # base = registros del archivo del período + filtros de área/sede/tipo/fechas.
    # Se excluye el filtro por campo `periodo` (se reemplaza por archivo_origen).
    filters_sin_periodo = {k: v for k, v in filters.items() if k != "periodo"}
    base = _apply_filters(db.query(NovedadNomina), filters_sin_periodo)
    if arch_activos:
        base = base.filter(NovedadNomina.archivo_origen == arch_activos)

    total = base.count()
    empleados = base.filter(NovedadNomina.cedula.isnot(None)).with_entities(
        func.count(distinct(NovedadNomina.cedula))
    ).scalar() or 0
    areas = base.filter(NovedadNomina.area.isnot(None)).with_entities(
        func.count(distinct(NovedadNomina.area))
    ).scalar() or 0
    tipos = base.filter(NovedadNomina.tipo_novedad.isnot(None)).with_entities(
        func.count(distinct(NovedadNomina.tipo_novedad))
    ).scalar() or 0
    valor_total = base.with_entities(
        func.coalesce(func.sum(cast(NovedadNomina.valor, Float)), 0.0)
    ).scalar() or 0.0
    # Prom. días: solo novedades medidas en DÍAS (incapacidades, licencias,
    # vacaciones, permisos). Excluye HE/recargos (que están en horas) y rodamientos
    # (que son valores), porque mezclarlos distorsiona el promedio.
    avg_dias = base.filter(
        NovedadNomina.unidad == 'dias',
        NovedadNomina.tipo_novedad.ilike('%incapaci%') |
        NovedadNomina.tipo_novedad.ilike('%licencia%') |
        NovedadNomina.tipo_novedad.ilike('%vacacion%') |
        NovedadNomina.tipo_novedad.ilike('%permiso%') |
        NovedadNomina.tipo_novedad.ilike('%ausencia%') |
        NovedadNomina.tipo_novedad.ilike('%luto%') |
        NovedadNomina.tipo_novedad.ilike('%calamidad%')
    ).with_entities(
        func.coalesce(func.avg(cast(NovedadNomina.dias, Float)), 0.0)
    ).scalar() or 0.0
    periodos = base.filter(NovedadNomina.periodo.isnot(None)).with_entities(
        func.count(distinct(NovedadNomina.periodo))
    ).scalar() or 0

    # HE y ausentismo para KPIs del panel ejecutivo
    total_he = base.filter(
        NovedadNomina.unidad == 'horas'
    ).with_entities(
        func.coalesce(func.sum(cast(NovedadNomina.dias, Float)), 0.0)
    ).scalar() or 0.0

    total_aus = base.filter(
        NovedadNomina.unidad == 'dias',
        NovedadNomina.tipo_novedad.ilike('%incapaci%') |
        NovedadNomina.tipo_novedad.ilike('%licencia%') |
        NovedadNomina.tipo_novedad.ilike('%ausencia%')
    ).with_entities(
        func.coalesce(func.sum(cast(NovedadNomina.dias, Float)), 0.0)
    ).scalar() or 0.0

    # Empleados con HE > 48h en el archivo del período (suma de HE por cédula > 48)
    he_limite = (
        base.filter(NovedadNomina.unidad == 'horas')
        .group_by(NovedadNomina.cedula)
        .having(func.sum(cast(NovedadNomina.dias, Float)) > 48)
        .with_entities(NovedadNomina.cedula)
        .count()
    )

    # Activos / inactivos y valores monetarios: basados en el ARCHIVO del período
    # (arch_activos ya calculado al inicio de la función).
    # Construir parámetros de valor basados en archivo_origen (no en periodo)
    arch_val_where = "AND n.archivo_origen = :arch_val" if arch_activos else ""
    area_val_where = "AND n.area = :area_val" if filters.get("area") else ""
    sede_val_where = "AND n.sede = :sede_val" if filters.get("sede") else ""
    params_val: dict = {}
    if arch_activos:
        params_val["arch_val"] = arch_activos
    if filters.get("area"):
        params_val["area_val"] = filters["area"]
    if filters.get("sede"):
        params_val["sede_val"] = filters["sede"]

    # Valor monetario de HE y recargos (se calcula primero porque suma al total nómina)
    sql_valor_he = text(f"""
        SELECT COALESCE(SUM(
            CAST(n.dias AS REAL) * s.salario / 240.0 *
            CASE n.tipo_novedad
                WHEN 'HORAS EXTRAS DIURNAS'            THEN 1.25
                WHEN 'HORAS EXTRAS NOCTURNAS'          THEN 1.75
                WHEN 'HORAS EXTRAS DIURNAS FESTIVAS'   THEN 2.00
                WHEN 'HORAS EXTRAS NOCTURNAS FESTIVAS' THEN 2.50
                WHEN 'RECARGO FESTIVO'                 THEN 0.75
                WHEN 'RECARGO FESTIVO NOCTURNO'        THEN 1.10
                WHEN 'RECARGO NOCTURNO'                THEN 0.35
                ELSE 0.0
            END
        ), 0) as v
        FROM novedades_nomina n
        LEFT JOIN salarios_empleados s ON n.cedula = s.cedula
        WHERE n.es_valido = 1 AND n.unidad = 'horas'
          {arch_val_where} {area_val_where} {sede_val_where}
    """)
    valor_horas_extras = float(db.execute(sql_valor_he, params_val).scalar() or 0.0)

    sql_valor_aus = text(f"""
        SELECT COALESCE(SUM(
            CAST(n.dias AS REAL) * s.salario / 30.0
        ), 0) as v
        FROM novedades_nomina n
        LEFT JOIN salarios_empleados s ON n.cedula = s.cedula
        WHERE n.es_valido = 1 AND n.unidad = 'dias'
          AND (LOWER(n.tipo_novedad) LIKE '%incapaci%'
               OR LOWER(n.tipo_novedad) LIKE '%licencia%'
               OR LOWER(n.tipo_novedad) LIKE '%ausencia%')
          {arch_val_where} {area_val_where} {sede_val_where}
    """)
    valor_ausencias = float(db.execute(sql_valor_aus, params_val).scalar() or 0.0)

    # Suma de salarios base de los empleados presentes en el archivo del período
    # (un salario por empleado distinto). Incapacidades/licencias/permisos NO afectan.
    sql_salarios_base = text(f"""
        SELECT COALESCE(SUM(s.salario), 0) as v
        FROM salarios_empleados s
        WHERE s.cedula IN (
            SELECT DISTINCT n.cedula FROM novedades_nomina n
            WHERE n.es_valido = 1 AND n.cedula IS NOT NULL
              {arch_val_where} {area_val_where} {sede_val_where}
        )
    """)
    salarios_base = float(db.execute(sql_salarios_base, params_val).scalar() or 0.0)

    # Empleados del período sin salario real registrado: sus novedades NO se
    # incluyen en ningún valor monetario (antes usaban un salario por defecto
    # inventado, que distorsionaba el cálculo — ver hallazgo médicos/auxiliares).
    sql_sin_salario = text(f"""
        SELECT COUNT(DISTINCT n.cedula) FROM novedades_nomina n
        WHERE n.es_valido = 1 AND n.cedula IS NOT NULL
          {arch_val_where} {area_val_where} {sede_val_where}
          AND NOT EXISTS (SELECT 1 FROM salarios_empleados s WHERE s.cedula = n.cedula)
    """)
    empleados_sin_salario = int(db.execute(sql_sin_salario, params_val).scalar() or 0)

    # Valor Total Nómina = salarios base de los empleados + valor de horas extras/recargos
    valor_calculado = salarios_base + valor_horas_extras

    where_activos_parts = ["n.es_valido = 1", "n.cedula IS NOT NULL"]
    params_activos: dict = {}
    if arch_activos:
        where_activos_parts.append("n.archivo_origen = :arch_activos")
        params_activos["arch_activos"] = arch_activos
    if filters.get("area"):
        where_activos_parts.append("n.area = :area_act")
        params_activos["area_act"] = filters["area"]
    if filters.get("sede"):
        where_activos_parts.append("n.sede = :sede_act")
        params_activos["sede_act"] = filters["sede"]
    where_activos = " AND ".join(where_activos_parts)

    # ACTIVO = en el archivo del periodo sin renuncia/terminacion EN ESE MISMO ARCHIVO.
    # Empleados recontratados (que tuvieron retiro en un contrato anterior) quedan como activos
    # porque su presencia en el archivo ya confirma que están activos ese mes.
    # REGISTRO MANUAL siempre aplica (decisión administrativa explícita, independiente del archivo).
    sql_estados = text(f"""
        SELECT
            SUM(CASE WHEN NOT EXISTS (
                    SELECT 1 FROM novedades_nomina r
                    WHERE r.cedula = emp.cedula
                      AND r.es_valido = 1
                      AND (LOWER(r.tipo_novedad) LIKE '%renuncia%'
                           OR LOWER(r.tipo_novedad) LIKE '%terminacion%')
                      AND (r.archivo_origen = :arch_activos
                           OR r.archivo_origen = 'REGISTRO MANUAL')
                ) THEN 1 ELSE 0 END) AS activos,
            SUM(CASE WHEN EXISTS (
                    SELECT 1 FROM novedades_nomina r
                    WHERE r.cedula = emp.cedula
                      AND r.es_valido = 1
                      AND (LOWER(r.tipo_novedad) LIKE '%renuncia%'
                           OR LOWER(r.tipo_novedad) LIKE '%terminacion%')
                      AND (r.archivo_origen = :arch_activos
                           OR r.archivo_origen = 'REGISTRO MANUAL')
                ) THEN 1 ELSE 0 END) AS inactivos
        FROM (
            SELECT DISTINCT n.cedula
            FROM novedades_nomina n
            WHERE {where_activos}
        ) emp
    """)
    row_estados   = db.execute(sql_estados, params_activos).fetchone()
    emp_activos   = int(row_estados.activos   or 0)
    emp_inactivos = int(row_estados.inactivos or 0)

    # Delta vs período anterior (también basado en el archivo del período previo)
    delta_nov = delta_emp = delta_val = None
    periodo_actual = filters.get("periodo") or max_per_arch
    if periodo_actual:
        prev = _prev_periodo(periodo_actual)
        if prev:
            año_p, mes_p = prev.split("-")
            arch_prev = f"{mes_p}{año_p}.xlsx"
            prev_base = _apply_filters(db.query(NovedadNomina), filters_sin_periodo)
            prev_base = prev_base.filter(NovedadNomina.archivo_origen == arch_prev)
            prev_total = prev_base.count()
            prev_emp = prev_base.filter(NovedadNomina.cedula.isnot(None)).with_entities(
                func.count(distinct(NovedadNomina.cedula))
            ).scalar() or 0
            prev_valor = prev_base.with_entities(
                func.coalesce(func.sum(cast(NovedadNomina.valor, Float)), 0.0)
            ).scalar() or 0.0
            delta_nov = _pct_change(total, prev_total)
            delta_emp = _pct_change(empleados, prev_emp)
            delta_val = _pct_change(float(valor_total), float(prev_valor))

    return KPIResponse(
        total_novedades=total,
        total_empleados=empleados,
        total_areas=areas,
        total_tipos_novedad=tipos,
        valor_total=round(float(valor_total), 2),
        promedio_dias=round(float(avg_dias), 2),
        periodos_disponibles=periodos,
        delta_novedades=delta_nov,
        delta_empleados=delta_emp,
        delta_valor=delta_val,
        total_horas_extras=round(float(total_he), 1),
        total_dias_ausencia=round(float(total_aus), 1),
        empleados_he_limite=he_limite,
        valor_calculado=round(valor_calculado, 0),
        valor_horas_extras=round(valor_horas_extras, 0),
        valor_ausencias=round(valor_ausencias, 0),
        empleados_sin_salario=empleados_sin_salario,
        empleados_activos=emp_activos,
        empleados_inactivos=emp_inactivos,
    )


def get_novedades_por_tipo(db: Session, filters: dict, top_n: int = 10) -> ChartResponse:
    rows = (
        _apply_filters(db.query(NovedadNomina), filters)
        .filter(NovedadNomina.tipo_novedad.isnot(None))
        .with_entities(NovedadNomina.tipo_novedad, func.count().label("cnt"))
        .group_by(NovedadNomina.tipo_novedad)
        .order_by(func.count().desc())
        .limit(top_n)
        .all()
    )
    labels = [r.tipo_novedad for r in rows]
    data = [r.cnt for r in rows]
    colors = PALETTE[: len(labels)]
    return ChartResponse(
        labels=labels,
        series=[SerieData(label="Cantidad", data=data, color=PALETTE[0])],
        title=f"Top {top_n} Tipos de Novedad",
        chart_type="bar",
    )


def get_valor_por_categoria(db: Session, filters: dict) -> ChartResponse:
    """Impacto económico calculado (salarios) agrupado por categoría de novedad.
    Usa subconsulta para compatibilidad con SQLite (no soporta alias en HAVING)."""
    extra_where, params = _panel_filters_sql(filters, full=True)
    sql = text(f"""
        SELECT cat, eventos, val FROM (
            SELECT
                {_CATEGORIA_EXPR} AS cat,
                COUNT(*) AS eventos,
                COALESCE(SUM({_VALOR_CALC_EXPR}), 0) AS val
            FROM novedades_nomina n
            LEFT JOIN salarios_empleados s ON n.cedula = s.cedula
            WHERE n.es_valido = 1 {extra_where}
            GROUP BY cat
        ) sub
        WHERE cat IS NOT NULL AND val > 0
        ORDER BY val DESC
    """)
    rows = db.execute(sql, params).fetchall()
    colors = ["#4F81BD","#C0504D","#9BBB59","#8064A2","#4BACC6","#F79646","#2C4770","#A9373B","#5B9BD5","#ED7D31"]
    return ChartResponse(
        labels=[r.cat for r in rows],
        series=[SerieData(
            label="Valor (COP)",
            data=[round(float(r.val or 0), 0) for r in rows],
            color=colors[0],
        )],
        title="Impacto Económico por Categoría",
        chart_type="doughnut",
    )


def get_novedades_por_area(db: Session, filters: dict, top_n: int = 10) -> ChartResponse:
    rows = (
        _apply_filters(db.query(NovedadNomina), filters)
        .filter(NovedadNomina.area.isnot(None))
        .with_entities(NovedadNomina.area, func.count().label("cnt"))
        .group_by(NovedadNomina.area)
        .order_by(func.count().desc())
        .limit(top_n)
        .all()
    )
    return ChartResponse(
        labels=[r.area for r in rows],
        series=[SerieData(label="Novedades", data=[r.cnt for r in rows], color=PALETTE[1])],
        title=f"Top {top_n} Áreas con más Novedades",
        chart_type="bar",
    )


def get_tendencia_mensual(db: Session, filters: dict) -> ChartResponse:
    rows = (
        _apply_filters(db.query(NovedadNomina), filters)
        .filter(NovedadNomina.periodo.isnot(None))
        .with_entities(
            NovedadNomina.periodo,
            func.count().label("cnt"),
            func.coalesce(func.sum(cast(NovedadNomina.valor, Float)), 0).label("total_valor"),
        )
        .group_by(NovedadNomina.periodo)
        .order_by(NovedadNomina.periodo)
        .all()
    )
    labels = [r.periodo for r in rows]
    return ChartResponse(
        labels=labels,
        series=[
            SerieData(label="Novedades", data=[r.cnt for r in rows], color=PALETTE[0]),
            SerieData(label="Valor Total", data=[round(float(r.total_valor), 2) for r in rows], color=PALETTE[2]),
        ],
        title="Tendencia Mensual",
        chart_type="line",
    )


def get_valor_por_area(db: Session, filters: dict, top_n: int = 10) -> ChartResponse:
    rows = (
        _apply_filters(db.query(NovedadNomina), filters)
        .filter(NovedadNomina.area.isnot(None), NovedadNomina.valor.isnot(None))
        .with_entities(
            NovedadNomina.area,
            func.sum(cast(NovedadNomina.valor, Float)).label("total"),
        )
        .group_by(NovedadNomina.area)
        .order_by(func.sum(cast(NovedadNomina.valor, Float)).desc())
        .limit(top_n)
        .all()
    )
    return ChartResponse(
        labels=[r.area for r in rows],
        series=[SerieData(label="Valor ($)", data=[round(float(r.total), 2) for r in rows], color=PALETTE[3])],
        title="Valor Total por Área",
        chart_type="bar",
    )


def get_table_data(
    db: Session,
    filters: dict,
    page: int = 1,
    page_size: int = 50,
    sort_by: str = "id",
    sort_dir: str = "desc",
) -> PaginatedTable:
    query = _apply_filters(db.query(NovedadNomina), filters)
    total = query.count()

    allowed_sort = {
        "id", "cedula", "nombre_empleado", "area", "tipo_novedad",
        "fecha_inicio", "valor", "periodo",
    }
    col = sort_by if sort_by in allowed_sort else "id"
    order = getattr(NovedadNomina, col)
    if sort_dir == "desc":
        order = order.desc()

    rows = query.order_by(order).offset((page - 1) * page_size).limit(page_size).all()

    data = []
    for r in rows:
        data.append({
            "id": r.id,
            "cedula": r.cedula,
            "nombre_empleado": r.nombre_empleado,
            "area": r.area,
            "sede": r.sede,
            "cargo": r.cargo,
            "tipo_novedad": r.tipo_novedad,
            "fecha_inicio": r.fecha_inicio.isoformat() if r.fecha_inicio else None,
            "fecha_fin": r.fecha_fin.isoformat() if r.fecha_fin else None,
            "dias": r.dias,
            "unidad": r.unidad,
            "valor": float(r.valor) if r.valor is not None else None,
            "periodo": r.periodo,
            "estado": r.estado,
            "archivo_origen": r.archivo_origen,
            "hoja_origen": r.hoja_origen,
        })

    return PaginatedTable(total=total, page=page, page_size=page_size, data=data)


def get_alerts(db: Session, filters: dict) -> AlertsResponse:
    """Motor de alertas: detecta duplicados, valores atípicos y otras anomalías."""
    alertas: list[AlertItem] = []

    base_all = db.query(NovedadNomina)
    if filters.get("periodo"):
        base_all = base_all.filter(NovedadNomina.periodo == filters["periodo"])
    if filters.get("area"):
        base_all = base_all.filter(NovedadNomina.area == filters["area"])
    if filters.get("sede"):
        base_all = base_all.filter(NovedadNomina.sede == filters["sede"])

    # Totales para embudo ETL
    total_ingresados = base_all.count()
    total_validos = base_all.filter(NovedadNomina.es_valido == 1).count()
    total_invalidos = base_all.filter(NovedadNomina.es_valido == 0).count()

    # 1. Duplicados: misma cédula + tipo_novedad + período, más de una vez.
    # Excluye datos de Trazalo (hoja_origen='TRAZALO'): allí es normal que un
    # empleado tenga varios eventos del mismo tipo en un mes (ej. 15 turnos con
    # recargo nocturno), no es un error de captura como en el Excel mensual.
    dup_rows = (
        base_all.filter(
            NovedadNomina.cedula.isnot(None),
            NovedadNomina.tipo_novedad.isnot(None),
            NovedadNomina.periodo.isnot(None),
            NovedadNomina.hoja_origen != 'TRAZALO',
        )
        .with_entities(
            NovedadNomina.cedula,
            NovedadNomina.tipo_novedad,
            NovedadNomina.periodo,
            func.count().label("cnt"),
        )
        .group_by(NovedadNomina.cedula, NovedadNomina.tipo_novedad, NovedadNomina.periodo)
        .having(func.count() > 1)
        .all()
    )
    if dup_rows:
        alertas.append(AlertItem(
            severidad="alta",
            tipo="duplicado",
            mensaje=f"{len(dup_rows)} combinaciones cédula+tipo+período con registros duplicados detectadas.",
            cantidad=len(dup_rows),
        ))

    # 2. Incapacidades con días > 90 (valor atípico para incapacidad EG Colombia)
    atipicos = (
        base_all.filter(
            NovedadNomina.tipo_novedad.ilike('%incapaci%'),
            NovedadNomina.dias.isnot(None),
            cast(NovedadNomina.dias, Float) > 90,
        )
        .count()
    )
    if atipicos:
        alertas.append(AlertItem(
            severidad="alta",
            tipo="valor_atipico",
            mensaje=f"{atipicos} incapacidades con duración superior a 90 días (revisar prórroga EPS).",
            cantidad=atipicos,
        ))

    # 3. Registros inválidos
    if total_invalidos > 0:
        alertas.append(AlertItem(
            severidad="media",
            tipo="invalido",
            mensaje=f"{total_invalidos} registros marcados como inválidos sin tipo o cédula definida.",
            cantidad=total_invalidos,
        ))

    # 4. Empleados con HE > 48h en algún período
    he_exceso = (
        base_all.filter(
            NovedadNomina.es_valido == 1,
            NovedadNomina.unidad == 'horas',
            NovedadNomina.cedula.isnot(None),
        )
        .with_entities(
            NovedadNomina.cedula,
            NovedadNomina.periodo,
            func.sum(cast(NovedadNomina.dias, Float)).label("total_h"),
        )
        .group_by(NovedadNomina.cedula, NovedadNomina.periodo)
        .having(func.sum(cast(NovedadNomina.dias, Float)) > 48)
        .count()
    )
    if he_exceso:
        alertas.append(AlertItem(
            severidad="alta",
            tipo="he_limite",
            mensaje=f"{he_exceso} empleados superan 48 horas extras en un período (límite Art. 159 CST).",
            cantidad=he_exceso,
        ))

    # 5. Novedades sin fechas
    sin_fecha = (
        base_all.filter(
            NovedadNomina.es_valido == 1,
            NovedadNomina.fecha_inicio.is_(None),
        )
        .count()
    )
    if sin_fecha:
        alertas.append(AlertItem(
            severidad="baja",
            tipo="sin_fecha",
            mensaje=f"{sin_fecha} registros válidos sin fecha de inicio definida.",
            cantidad=sin_fecha,
        ))

    # 6. Áreas con mayor concentración de irregularidades
    area_invalidos = (
        base_all.filter(
            NovedadNomina.es_valido == 0,
            NovedadNomina.area.isnot(None),
        )
        .with_entities(NovedadNomina.area, func.count().label("cnt"))
        .group_by(NovedadNomina.area)
        .order_by(func.count().desc())
        .first()
    )
    if area_invalidos and area_invalidos.cnt > 0:
        alertas.append(AlertItem(
            severidad="baja",
            tipo="area_irregularidades",
            mensaje=f"El área '{area_invalidos.area}' concentra la mayor cantidad de registros con errores ({area_invalidos.cnt}).",
            cantidad=area_invalidos.cnt,
            area=area_invalidos.area,
        ))

    total_con_alerta = sum(a.cantidad for a in alertas if a.severidad in ("alta", "media"))
    cnt_alta = sum(1 for a in alertas if a.severidad == "alta")
    cnt_media = sum(1 for a in alertas if a.severidad == "media")
    cnt_baja = sum(1 for a in alertas if a.severidad == "baja")

    return AlertsResponse(
        total_alertas=len(alertas),
        alta=cnt_alta,
        media=cnt_media,
        baja=cnt_baja,
        alertas=alertas,
        total_ingresados=total_ingresados,
        total_validos=total_validos,
        total_con_alerta=total_con_alerta,
        total_invalidos=total_invalidos,
    )


def get_alerts_detalle(db: Session, filters: dict) -> dict:
    """Listado detallado de los registros que disparan cada alerta del panel operativo."""
    base_all = db.query(NovedadNomina)
    if filters.get("periodo"):
        base_all = base_all.filter(NovedadNomina.periodo == filters["periodo"])
    if filters.get("area"):
        base_all = base_all.filter(NovedadNomina.area == filters["area"])
    if filters.get("sede"):
        base_all = base_all.filter(NovedadNomina.sede == filters["sede"])

    detalle: list[dict] = []

    def _fila(r, tipo_alerta, severidad, motivo):
        return {
            "tipo_alerta": tipo_alerta,
            "severidad":   severidad,
            "motivo":      motivo,
            "cedula":      r.cedula,
            "nombre":      r.nombre_empleado,
            "area":        r.area,
            "tipo_novedad": r.tipo_novedad,
            "periodo":     r.periodo,
            "fecha_inicio": r.fecha_inicio.isoformat() if r.fecha_inicio else None,
            "fecha_fin":   r.fecha_fin.isoformat() if r.fecha_fin else None,
            "dias":        r.dias,
            "unidad":      r.unidad,
            "archivo_origen": r.archivo_origen,
        }

    # 1. Duplicados: cédula + tipo_novedad + período repetidos.
    # Excluye Trazalo (ver misma nota en get_alerts): allí repetir tipo+período
    # es normal (varios eventos aprobados el mismo mes), no un error de captura.
    dup_keys = (
        base_all.filter(
            NovedadNomina.cedula.isnot(None),
            NovedadNomina.tipo_novedad.isnot(None),
            NovedadNomina.periodo.isnot(None),
            NovedadNomina.hoja_origen != 'TRAZALO',
        )
        .with_entities(NovedadNomina.cedula, NovedadNomina.tipo_novedad, NovedadNomina.periodo)
        .group_by(NovedadNomina.cedula, NovedadNomina.tipo_novedad, NovedadNomina.periodo)
        .having(func.count() > 1)
        .all()
    )
    for k in dup_keys:
        regs = base_all.filter(
            NovedadNomina.cedula == k.cedula,
            NovedadNomina.tipo_novedad == k.tipo_novedad,
            NovedadNomina.periodo == k.periodo,
            NovedadNomina.hoja_origen != 'TRAZALO',
        ).all()
        for r in regs:
            detalle.append(_fila(r, "Duplicado", "alta",
                                 f"Repetido {len(regs)}× (cédula+tipo+período)"))

    # 2. Incapacidades con duración > 90 días
    atip = base_all.filter(
        NovedadNomina.tipo_novedad.ilike('%incapaci%'),
        NovedadNomina.dias.isnot(None),
        cast(NovedadNomina.dias, Float) > 90,
    ).all()
    for r in atip:
        detalle.append(_fila(r, "Valor atípico", "alta",
                             f"Incapacidad de {r.dias} días (>90, revisar prórroga EPS)"))

    # 3. Registros inválidos
    invalidos = base_all.filter(NovedadNomina.es_valido == 0).all()
    for r in invalidos:
        detalle.append(_fila(r, "Inválido", "media", "Registro sin tipo o cédula definida"))

    # 4. Novedades válidas sin fecha de inicio
    sin_fecha = base_all.filter(
        NovedadNomina.es_valido == 1,
        NovedadNomina.fecha_inicio.is_(None),
    ).all()
    for r in sin_fecha:
        detalle.append(_fila(r, "Sin fecha", "baja", "Registro válido sin fecha de inicio"))

    return {"total": len(detalle), "detalle": detalle}


def _panel_filters_sql(filters: dict, alias: str = "n", full: bool = False) -> tuple:
    """Retorna (where_extra, params) para consultas SQL raw de paneles.
    full=True incluye fecha_inicio, fecha_fin y tipo_novedad además de periodo/area/sede."""
    clauses, params = [], {}
    if filters.get("periodo"):
        clauses.append(f"{alias}.periodo = :periodo")
        params["periodo"] = filters["periodo"]
    if filters.get("area"):
        clauses.append(f"{alias}.area = :area")
        params["area"] = filters["area"]
    if filters.get("sede"):
        clauses.append(f"{alias}.sede = :sede")
        params["sede"] = filters["sede"]
    if full:
        if filters.get("fecha_inicio"):
            clauses.append(f"{alias}.fecha_inicio >= :fecha_inicio")
            params["fecha_inicio"] = str(filters["fecha_inicio"])
        if filters.get("fecha_fin"):
            clauses.append(f"{alias}.fecha_fin <= :fecha_fin")
            params["fecha_fin"] = str(filters["fecha_fin"])
    extra = (" AND " + " AND ".join(clauses)) if clauses else ""
    return extra, params


# SQL compartido para calcular el valor de cada novedad según su tipo
_VALOR_CALC_EXPR = """
    CASE
        WHEN n.unidad = 'horas' THEN
            CAST(n.dias AS REAL) * s.salario / 240.0 *
            CASE n.tipo_novedad
                WHEN 'HORAS EXTRAS DIURNAS'            THEN 1.25
                WHEN 'HORAS EXTRAS NOCTURNAS'          THEN 1.75
                WHEN 'HORAS EXTRAS DIURNAS FESTIVAS'   THEN 2.00
                WHEN 'HORAS EXTRAS NOCTURNAS FESTIVAS' THEN 2.50
                WHEN 'RECARGO FESTIVO'                 THEN 0.75
                WHEN 'RECARGO FESTIVO NOCTURNO'        THEN 1.10
                WHEN 'RECARGO NOCTURNO'                THEN 0.35
                ELSE 1.0
            END
        WHEN LOWER(n.tipo_novedad) LIKE '%permiso no rem%' THEN 0.0
        WHEN n.tipo_novedad IN ('OTRO NO ESPEC *','Fecha ingreso','PLAN BENEFICIOS BIENESTAR LABORAL','SANCIONADO') THEN 0.0
        WHEN n.tipo_novedad LIKE 'RODAMIENTO%' THEN CAST(n.dias AS REAL)
        WHEN n.unidad = 'dias' THEN CAST(n.dias AS REAL) * s.salario / 30.0
        ELSE 0.0
    END
"""

# Expresión de categoría para cada novedad
_CATEGORIA_EXPR = """
    CASE
        WHEN n.unidad = 'horas'                                                                  THEN 'H. Extras & Recargos'
        WHEN LOWER(n.tipo_novedad) LIKE '%incapaci%' OR LOWER(n.tipo_novedad) LIKE '%accidente%' THEN 'Incapacidades'
        WHEN LOWER(n.tipo_novedad) LIKE '%licencia%' OR LOWER(n.tipo_novedad) LIKE '%luto%'
          OR LOWER(n.tipo_novedad) LIKE '%calamidad%'
          OR LOWER(n.tipo_novedad) LIKE '%permiso remuner%'                                      THEN 'Licencias & Permisos'
        WHEN LOWER(n.tipo_novedad) LIKE '%vacacion%'                                             THEN 'Vacaciones'
        WHEN LOWER(n.tipo_novedad) LIKE '%renuncia%' OR LOWER(n.tipo_novedad) LIKE '%terminacion%' THEN 'Retiros'
        WHEN n.tipo_novedad = 'INGRESO'                                                          THEN 'Ingresos'
        WHEN n.tipo_novedad = 'TRABAJO EN CASA'                                                  THEN 'Trabajo en Casa'
        WHEN n.tipo_novedad LIKE 'RODAMIENTO%'                                                   THEN 'Rodamientos'
        WHEN LOWER(n.tipo_novedad) LIKE '%ausencia%'                                             THEN 'Ausencias'
        ELSE NULL
    END
"""


def get_panel_ausentismo(db: Session, filters: dict) -> dict:
    """Datos específicos del panel de ausentismo.
    Filtra por archivo_origen (no por el campo periodo): muchos registros del
    Excel tienen `periodo` derivado de su fecha_inicio, que puede caer en un
    mes distinto al del archivo donde están archivados (ej. una incapacidad
    reportada en 032026.xlsx con fecha_inicio en diciembre). Con período
    seleccionado se muestra ese mes; sin período, todo el histórico."""
    tipos_aus = ['%incapaci%', '%licencia%', '%ausencia%', '%permiso%', '%maternidad%', '%paternidad%', '%calamidad%', '%luto%', '%accidente%']
    periodo_filter = filters.get("periodo")
    if periodo_filter:
        año, mes = periodo_filter.split("-")
        arch_aus = f"{mes}{año}.xlsx"
    else:
        arch_aus = None

    aus_filter = db.query(NovedadNomina).filter(NovedadNomina.es_valido == 1)
    if arch_aus:
        aus_filter = aus_filter.filter(NovedadNomina.archivo_origen == arch_aus)
    if filters.get("area"):
        aus_filter = aus_filter.filter(NovedadNomina.area == filters["area"])
    if filters.get("sede"):
        aus_filter = aus_filter.filter(NovedadNomina.sede == filters["sede"])

    from sqlalchemy import or_
    # unidad='dias': evita sumar como "días perdidos" novedades cuyo campo `dias`
    # en realidad contiene HORAS (ej. PERMISO/CITA MÉDICA de Trazalo, que se
    # capturan por horas parciales de jornada, no por días completos).
    aus_base = aus_filter.filter(
        or_(*[NovedadNomina.tipo_novedad.ilike(t) for t in tipos_aus]),
        NovedadNomina.unidad == 'dias',
    )

    total_dias = aus_base.with_entities(
        func.coalesce(func.sum(cast(NovedadNomina.dias, Float)), 0.0)
    ).scalar() or 0.0

    total_eventos = aus_base.count()

    empleados_aus = aus_base.filter(NovedadNomina.cedula.isnot(None)).with_entities(
        func.count(distinct(NovedadNomina.cedula))
    ).scalar() or 0

    # Top áreas por días perdidos
    top_areas = (
        aus_base.filter(NovedadNomina.area.isnot(None))
        .with_entities(NovedadNomina.area, func.sum(cast(NovedadNomina.dias, Float)).label("dias"))
        .group_by(NovedadNomina.area)
        .order_by(func.sum(cast(NovedadNomina.dias, Float)).desc())
        .limit(8)
        .all()
    )

    # Distribución por tipo
    por_tipo = (
        aus_base.filter(NovedadNomina.tipo_novedad.isnot(None))
        .with_entities(NovedadNomina.tipo_novedad, func.count().label("cnt"))
        .group_by(NovedadNomina.tipo_novedad)
        .order_by(func.count().desc())
        .limit(10)
        .all()
    )

    # Tendencia mensual de ausentismo
    tendencia = (
        aus_base.filter(NovedadNomina.periodo.isnot(None))
        .with_entities(NovedadNomina.periodo, func.sum(cast(NovedadNomina.dias, Float)).label("dias"))
        .group_by(NovedadNomina.periodo)
        .order_by(NovedadNomina.periodo)
        .all()
    )

    # Empleados recurrentes (≥3 eventos)
    recurrentes = (
        aus_base.filter(NovedadNomina.cedula.isnot(None))
        .with_entities(NovedadNomina.cedula, func.count().label("cnt"))
        .group_by(NovedadNomina.cedula)
        .having(func.count() >= 3)
        .count()
    )

    # ── Valores monetarios por tipo (JOIN con salarios) ──────────
    # Mismo criterio de archivo_origen que aus_filter arriba (no periodo).
    arch_where_aus = "AND n.archivo_origen = :arch_aus" if arch_aus else ""
    area_where_aus = "AND n.area = :area_aus" if filters.get("area") else ""
    sede_where_aus = "AND n.sede = :sede_aus" if filters.get("sede") else ""
    params: dict = {}
    if arch_aus:
        params["arch_aus"] = arch_aus
    if filters.get("area"):
        params["area_aus"] = filters["area"]
    if filters.get("sede"):
        params["sede_aus"] = filters["sede"]
    extra_where = f"{arch_where_aus} {area_where_aus} {sede_where_aus}"
    AUS_PATTERN = (
        "LOWER(n.tipo_novedad) LIKE '%incapaci%' OR LOWER(n.tipo_novedad) LIKE '%licencia%' "
        "OR LOWER(n.tipo_novedad) LIKE '%ausencia%' OR LOWER(n.tipo_novedad) LIKE '%permiso%' "
        "OR LOWER(n.tipo_novedad) LIKE '%maternidad%' OR LOWER(n.tipo_novedad) LIKE '%paternidad%' "
        "OR LOWER(n.tipo_novedad) LIKE '%calamidad%' OR LOWER(n.tipo_novedad) LIKE '%luto%' "
        "OR LOWER(n.tipo_novedad) LIKE '%accidente%'"
    )
    sql_sin_salario_aus = text(f"""
        SELECT COUNT(DISTINCT n.cedula) FROM novedades_nomina n
        WHERE n.es_valido = 1 AND n.unidad = 'dias' AND n.cedula IS NOT NULL
          AND ({AUS_PATTERN}) {extra_where}
          AND NOT EXISTS (SELECT 1 FROM salarios_empleados s WHERE s.cedula = n.cedula)
    """)
    empleados_sin_salario_aus = int(db.execute(sql_sin_salario_aus, params).scalar() or 0)

    sql_valor = text(f"""
        SELECT
            n.tipo_novedad,
            COUNT(*) AS eventos,
            COALESCE(SUM(CAST(n.dias AS REAL)), 0) AS total_dias,
            COALESCE(SUM(
                CASE WHEN LOWER(n.tipo_novedad) LIKE '%permiso no rem%' THEN 0.0
                     ELSE CAST(n.dias AS REAL) * s.salario / 30.0
                END
            ), 0) AS valor
        FROM novedades_nomina n
        LEFT JOIN salarios_empleados s ON n.cedula = s.cedula
        WHERE n.es_valido = 1 AND n.unidad = 'dias' AND ({AUS_PATTERN})
        {extra_where}
        GROUP BY n.tipo_novedad
        ORDER BY total_dias DESC
    """)
    rows_valor = db.execute(sql_valor, params).fetchall()
    total_valor_aus = sum(float(r.valor or 0) for r in rows_valor)
    valor_por_tipo = [
        {
            "tipo": r.tipo_novedad,
            "eventos": int(r.eventos),
            "dias": round(float(r.total_dias or 0), 1),
            "valor": round(float(r.valor or 0), 0),
            "remunerado": "no rem" not in r.tipo_novedad.lower(),
        }
        for r in rows_valor
    ]

    # Empleados activos del período (para cálculo correcto de tasa de ausentismo)
    # Contar empleados activos (sin renuncia/terminación) en el archivo del período
    if arch_aus:
        emp_activos_query = db.query(NovedadNomina).filter(
            NovedadNomina.es_valido == 1,
            NovedadNomina.archivo_origen == arch_aus,
            NovedadNomina.cedula.isnot(None)
        )

        # Aplicar filtros de área/sede si existen
        if filters.get("area"):
            emp_activos_query = emp_activos_query.filter(NovedadNomina.area == filters["area"])
        if filters.get("sede"):
            emp_activos_query = emp_activos_query.filter(NovedadNomina.sede == filters["sede"])

        # Contar cédulas que NO tienen renuncia/terminación
        todos_emp = set()
        retirados_emp = set()

        for row in emp_activos_query.with_entities(NovedadNomina.cedula, NovedadNomina.tipo_novedad).all():
            todos_emp.add(row.cedula)
            if row.tipo_novedad and ('renuncia' in row.tipo_novedad.lower() or 'terminacion' in row.tipo_novedad.lower()):
                retirados_emp.add(row.cedula)

        empleados_activos_mes = len(todos_emp) - len(retirados_emp)
    else:
        empleados_activos_mes = 0

    # Evitar división por cero: si no hay empleados activos, tasa es 0
    if empleados_activos_mes <= 0:
        empleados_activos_mes = 1  # Usar 1 como mínimo para evitar error, pero tasa será muy alta (alerta)"

    return {
        "total_dias_perdidos": round(float(total_dias), 1),
        "total_eventos": total_eventos,
        "empleados_con_ausencia": empleados_aus,
        "empleados_activos_mes": empleados_activos_mes,
        "empleados_recurrentes": recurrentes,
        "total_valor_ausentismo": round(total_valor_aus, 0),
        "empleados_sin_salario": empleados_sin_salario_aus,
        "valor_por_tipo": valor_por_tipo,
        "chart_areas": ChartResponse(
            labels=[r.area for r in top_areas],
            series=[SerieData(label="Días perdidos", data=[round(float(r.dias or 0), 1) for r in top_areas], color=PALETTE[2])],
            title="Áreas con más Días de Ausencia",
            chart_type="bar",
        ),
        "chart_tipos": ChartResponse(
            labels=[r.tipo_novedad for r in por_tipo],
            series=[SerieData(label="Eventos", data=[r.cnt for r in por_tipo], color=PALETTE[1])],
            title="Distribución por Tipo de Ausencia",
            chart_type="doughnut",
        ),
        "chart_tendencia": ChartResponse(
            labels=[r.periodo for r in tendencia],
            series=[SerieData(label="Días perdidos", data=[round(float(r.dias or 0), 1) for r in tendencia], color=PALETTE[3])],
            title="Tendencia Mensual Ausentismo",
            chart_type="line",
        ),
    }


def get_panel_horas_extras(db: Session, filters: dict) -> dict:
    """Datos específicos del panel de horas extras y recargos.
    Con período seleccionado: muestra ese mes. Sin período: agrega TODO el
    histórico (así un área como SIST INFORMACION, que no tiene HE en el último
    mes pero sí en meses anteriores, sigue mostrando su información)."""
    periodo_filter = filters.get("periodo")
    max_per_arch   = _max_periodo_archivos(db)

    if periodo_filter:
        año, mes = periodo_filter.split("-")
        arch_he = f"{mes}{año}.xlsx"
    else:
        arch_he = None   # sin período => todo el histórico

    he_filter = db.query(NovedadNomina).filter(
        NovedadNomina.es_valido == 1,
        NovedadNomina.unidad == 'horas',
    )
    if arch_he:
        he_filter = he_filter.filter(NovedadNomina.archivo_origen == arch_he)
    if filters.get("area"):
        he_filter = he_filter.filter(NovedadNomina.area == filters["area"])
    if filters.get("sede"):
        he_filter = he_filter.filter(NovedadNomina.sede == filters["sede"])

    total_horas = he_filter.with_entities(
        func.coalesce(func.sum(cast(NovedadNomina.dias, Float)), 0.0)
    ).scalar() or 0.0

    total_eventos = he_filter.count()

    empleados_he = he_filter.filter(NovedadNomina.cedula.isnot(None)).with_entities(
        func.count(distinct(NovedadNomina.cedula))
    ).scalar() or 0

    # Distribución por tipo
    por_tipo = (
        he_filter.filter(NovedadNomina.tipo_novedad.isnot(None))
        .with_entities(NovedadNomina.tipo_novedad, func.sum(cast(NovedadNomina.dias, Float)).label("horas"))
        .group_by(NovedadNomina.tipo_novedad)
        .order_by(func.sum(cast(NovedadNomina.dias, Float)).desc())
        .limit(10)
        .all()
    )

    # Top áreas
    top_areas = (
        he_filter.filter(NovedadNomina.area.isnot(None))
        .with_entities(NovedadNomina.area, func.sum(cast(NovedadNomina.dias, Float)).label("horas"))
        .group_by(NovedadNomina.area)
        .order_by(func.sum(cast(NovedadNomina.dias, Float)).desc())
        .limit(8)
        .all()
    )

    # Top empleados por horas (solo cédula, sin datos personales en respuesta)
    top_empleados = (
        he_filter.filter(
            NovedadNomina.cedula.isnot(None),
            NovedadNomina.nombre_empleado.isnot(None),
        )
        .with_entities(
            NovedadNomina.cedula,
            NovedadNomina.nombre_empleado,
            NovedadNomina.area,
            func.sum(cast(NovedadNomina.dias, Float)).label("horas"),
        )
        .group_by(NovedadNomina.cedula, NovedadNomina.nombre_empleado, NovedadNomina.area)
        .order_by(func.sum(cast(NovedadNomina.dias, Float)).desc())
        .limit(10)
        .all()
    )

    # Tendencia mensual HISTÓRICA: recorre TODOS los archivos (no solo el período
    # seleccionado), agrupando por el mes derivado del nombre del archivo MMYYYY.xlsx.
    # Solo aplica filtros de área/sede para que la curva muestre toda la historia.
    tend_area_where = "AND n.area = :t_area" if filters.get("area") else ""
    tend_sede_where = "AND n.sede = :t_sede" if filters.get("sede") else ""
    tend_params: dict = {}
    if filters.get("area"):
        tend_params["t_area"] = filters["area"]
    if filters.get("sede"):
        tend_params["t_sede"] = filters["sede"]

    # OJO: el alias no puede llamarse 'periodo' porque colisiona con la columna real
    # y SQLite agruparía por la columna en vez de por el mes del archivo.
    is_sqlite = db.bind.dialect.name == "sqlite"
    glob_cond = "n.archivo_origen GLOB '[0-9][0-9][0-9][0-9][0-9][0-9].xlsx'" if is_sqlite else "n.archivo_origen ~ '^[0-9]{6}\\.xlsx$'"
    sql_tendencia = text(f"""
        SELECT
            SUBSTR(n.archivo_origen, 3, 4) || '-' || SUBSTR(n.archivo_origen, 1, 2) AS mes_arch,
            SUM(CAST(n.dias AS REAL)) AS horas
        FROM novedades_nomina n
        WHERE n.es_valido = 1 AND n.unidad = 'horas'
          AND {glob_cond}
          {tend_area_where} {tend_sede_where}
        GROUP BY SUBSTR(n.archivo_origen, 3, 4) || '-' || SUBSTR(n.archivo_origen, 1, 2)
        ORDER BY SUBSTR(n.archivo_origen, 3, 4) || '-' || SUBSTR(n.archivo_origen, 1, 2)
    """)
    tendencia = db.execute(sql_tendencia, tend_params).fetchall()

    # Empleados > 48h
    exceso_48h = (
        he_filter.filter(NovedadNomina.cedula.isnot(None))
        .with_entities(NovedadNomina.cedula, NovedadNomina.periodo, func.sum(cast(NovedadNomina.dias, Float)).label("h"))
        .group_by(NovedadNomina.cedula, NovedadNomina.periodo)
        .having(func.sum(cast(NovedadNomina.dias, Float)) > 48)
        .count()
    )

    prom_he = (float(total_horas) / empleados_he) if empleados_he > 0 else 0.0

    # ── Valores monetarios HE (JOIN con salarios) ─────────────────
    arch_where_sql = "AND n.archivo_origen = :arch_he" if arch_he else ""
    area_where_sql = "AND n.area = :area_he" if filters.get("area") else ""
    sede_where_sql = "AND n.sede = :sede_he" if filters.get("sede") else ""
    params_sql: dict = {}
    if arch_he:
        params_sql["arch_he"] = arch_he
    if filters.get("area"):
        params_sql["area_he"] = filters["area"]
    if filters.get("sede"):
        params_sql["sede_he"] = filters["sede"]

    sql_sin_salario_he = text(f"""
        SELECT COUNT(DISTINCT n.cedula) FROM novedades_nomina n
        WHERE n.es_valido = 1 AND n.unidad = 'horas' AND n.cedula IS NOT NULL
          {arch_where_sql} {area_where_sql} {sede_where_sql}
          AND NOT EXISTS (SELECT 1 FROM salarios_empleados s WHERE s.cedula = n.cedula)
    """)
    empleados_sin_salario_he = int(db.execute(sql_sin_salario_he, params_sql).scalar() or 0)

    sql_he_valor = text(f"""
        SELECT
            n.tipo_novedad,
            COUNT(*) AS eventos,
            COALESCE(SUM(CAST(n.dias AS REAL)), 0) AS total_horas,
            COALESCE(SUM(
                CAST(n.dias AS REAL) * s.salario / 240.0 *
                CASE n.tipo_novedad
                    WHEN 'HORAS EXTRAS DIURNAS'           THEN 1.25
                    WHEN 'HORAS EXTRAS NOCTURNAS'         THEN 1.75
                    WHEN 'HORAS EXTRAS DIURNAS FESTIVAS'  THEN 2.00
                    WHEN 'HORAS EXTRAS NOCTURNAS FESTIVAS'THEN 2.50
                    WHEN 'RECARGO FESTIVO'                THEN 0.75
                    WHEN 'RECARGO FESTIVO NOCTURNO'       THEN 1.10
                    WHEN 'RECARGO NOCTURNO'               THEN 0.35
                    ELSE 1.0
                END
            ), 0) AS valor
        FROM novedades_nomina n
        LEFT JOIN salarios_empleados s ON n.cedula = s.cedula
        WHERE n.es_valido = 1 AND n.unidad = 'horas'
          {arch_where_sql} {area_where_sql} {sede_where_sql}
        GROUP BY n.tipo_novedad
        ORDER BY total_horas DESC
    """)
    rows_he_v = db.execute(sql_he_valor, params_sql).fetchall()
    total_valor_he = sum(float(r.valor or 0) for r in rows_he_v)

    HE_FACTORES = {
        'HORAS EXTRAS DIURNAS': 1.25, 'HORAS EXTRAS NOCTURNAS': 1.75,
        'HORAS EXTRAS DIURNAS FESTIVAS': 2.00, 'HORAS EXTRAS NOCTURNAS FESTIVAS': 2.50,
        'RECARGO FESTIVO': 0.75, 'RECARGO FESTIVO NOCTURNO': 1.10, 'RECARGO NOCTURNO': 0.35,
    }
    valor_por_tipo_he = [
        {
            "tipo": r.tipo_novedad,
            "eventos": int(r.eventos),
            "horas": round(float(r.total_horas or 0), 1),
            "valor": round(float(r.valor or 0), 0),
            "factor": HE_FACTORES.get(r.tipo_novedad, 1.0),
        }
        for r in rows_he_v
    ]

    # Top empleados con valor
    sql_top_emp = text(f"""
        SELECT
            n.cedula, n.nombre_empleado, n.area,
            COALESCE(SUM(CAST(n.dias AS REAL)), 0) AS horas,
            COALESCE(SUM(
                CAST(n.dias AS REAL) * s.salario / 240.0 *
                CASE n.tipo_novedad
                    WHEN 'HORAS EXTRAS DIURNAS'           THEN 1.25
                    WHEN 'HORAS EXTRAS NOCTURNAS'         THEN 1.75
                    WHEN 'HORAS EXTRAS DIURNAS FESTIVAS'  THEN 2.00
                    WHEN 'HORAS EXTRAS NOCTURNAS FESTIVAS'THEN 2.50
                    WHEN 'RECARGO FESTIVO'                THEN 0.75
                    WHEN 'RECARGO FESTIVO NOCTURNO'       THEN 1.10
                    WHEN 'RECARGO NOCTURNO'               THEN 0.35
                    ELSE 1.0
                END
            ), 0) AS valor
        FROM novedades_nomina n
        LEFT JOIN salarios_empleados s ON n.cedula = s.cedula
        WHERE n.es_valido = 1 AND n.unidad = 'horas'
          AND n.cedula IS NOT NULL AND n.nombre_empleado IS NOT NULL
          {arch_where_sql} {area_where_sql} {sede_where_sql}
        GROUP BY n.cedula, n.nombre_empleado, n.area
        ORDER BY horas DESC
        LIMIT 10
    """)
    top_emp_rows = db.execute(sql_top_emp, params_sql).fetchall()

    return {
        "total_horas": round(float(total_horas), 1),
        "total_eventos": total_eventos,
        "empleados_con_he": empleados_he,
        "promedio_horas_empleado": round(prom_he, 1),
        "empleados_exceso_48h": exceso_48h,
        "total_valor_pagado": round(total_valor_he, 0),
        "empleados_sin_salario": empleados_sin_salario_he,
        "valor_por_tipo": valor_por_tipo_he,
        "chart_tipos": ChartResponse(
            labels=[r.tipo_novedad for r in por_tipo],
            series=[SerieData(label="Horas", data=[round(float(r.horas or 0), 1) for r in por_tipo], color=PALETTE[0])],
            title="Horas por Tipo de Recargo/HE",
            chart_type="bar",
        ),
        "chart_areas": ChartResponse(
            labels=[r.area for r in top_areas],
            series=[SerieData(label="Horas", data=[round(float(r.horas or 0), 1) for r in top_areas], color=PALETTE[1])],
            title="Top Áreas por Horas Extras",
            chart_type="bar",
        ),
        "chart_tendencia": ChartResponse(
            labels=[r.mes_arch for r in tendencia],
            series=[SerieData(label="Horas", data=[round(float(r.horas or 0), 1) for r in tendencia], color=PALETTE[4])],
            title="Tendencia Mensual H. Extras",
            chart_type="line",
        ),
        "top_empleados": [
            {
                "cedula": r.cedula,
                "nombre": r.nombre_empleado,
                "area": r.area,
                "horas": round(float(r.horas or 0), 1),
                "valor": round(float(r.valor or 0), 0),
                "excede_limite": float(r.horas or 0) > 48,
            }
            for r in top_emp_rows
        ],
    }


def get_filter_options(db: Session, panel: Optional[str] = None, periodo: Optional[str] = None) -> dict:
    """Obtener valores únicos para poblar los filtros del frontend.
    Si `panel` es 'ausentismo' u 'horas-extras', las áreas y sedes se
    restringen a las que tienen novedades de esa categoría (mismo criterio
    usado en get_panel_ausentismo / get_panel_horas_extras). Si además se pasa
    `periodo`, se acotan al mes seleccionado usando archivo_origen (mismo
    criterio de los paneles: MMYYYY.xlsx).
    Para panel 'ejecutivo', excluye áreas administrativas/clínicas que no aplican."""
    base = db.query(NovedadNomina).filter(NovedadNomina.es_valido == 1)

    # Acotar por período (solo tiene sentido para los paneles ausentismo/horas-extras)
    if panel in ('ausentismo', 'horas-extras') and periodo:
        try:
            año, mes = periodo.split("-")
            arch = f"{mes}{año}.xlsx"
            base = base.filter(NovedadNomina.archivo_origen == arch)
        except (ValueError, IndexError):
            pass

    if panel == 'ausentismo':
        from sqlalchemy import or_
        tipos_aus = ['%incapaci%', '%licencia%', '%ausencia%', '%permiso%', '%maternidad%', '%paternidad%', '%calamidad%', '%luto%', '%accidente%']
        base = base.filter(
            NovedadNomina.unidad == 'dias',
            or_(*[NovedadNomina.tipo_novedad.ilike(t) for t in tipos_aus]),
        )
    elif panel == 'horas-extras':
        base = base.filter(NovedadNomina.unidad == 'horas')

    # Para panel ejecutivo, excluir áreas administrativas/clínicas
    areas_excluir_ejecutivo = {
        'DOMICILIARIA', 'ENFERMEROS  - ORIENTAL', 'ENFERMERÍA - AP',
        'FARMACIA CIRUGIA', 'GESTOR LOGISTICO', 'LINEA DE FRENTE - AP',
        'LINEA DE FRENTE - R', 'LINEA FRENTE - BELLO', 'MEDICINA GENERAL - AP',
        'MENSAJERÍA', 'MÉDICOS - ORIENTAL', 'OTRAS ÁREAS', 'REVISAR',
        'SERVICIOS GENERALES', 'AUX LABORATORIO CLÍNICO', 'AUXILIAR ENFEMERIA - RIONEGRO',
        'BACTERIOLOGOS'
    }
    if panel == 'ejecutivo':
        base = base.filter(~NovedadNomina.area.in_(areas_excluir_ejecutivo))

    areas = (
        base.with_entities(distinct(NovedadNomina.area))
        .filter(NovedadNomina.area.isnot(None))
        .order_by(NovedadNomina.area)
        .all()
    )
    sedes = (
        base.with_entities(distinct(NovedadNomina.sede))
        .filter(NovedadNomina.sede.isnot(None))
        .order_by(NovedadNomina.sede)
        .all()
    )
    tipos = (
        base.with_entities(distinct(NovedadNomina.tipo_novedad))
        .filter(NovedadNomina.tipo_novedad.isnot(None))
        .filter(NovedadNomina.tipo_novedad != 'PRESENTE EN NOMINA')
        .order_by(NovedadNomina.tipo_novedad)
        .all()
    )
    max_per = _max_periodo_archivos(db) or '9999-99'
    is_sqlite = db.bind.dialect.name == "sqlite"
    glob_cond = "periodo GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]'" if is_sqlite else "periodo ~ '^[0-9]{4}-[0-9]{2}$'"
    periodos = db.execute(text(f"""
        SELECT DISTINCT periodo FROM novedades_nomina
        WHERE es_valido = 1
          AND periodo IS NOT NULL
          AND {glob_cond}
          AND CAST(SUBSTR(periodo, 1, 4) AS INTEGER) >= 2000
          AND periodo <= :max_per
        ORDER BY periodo DESC
    """), {"max_per": max_per}).scalars().all()
    return {
        "areas": [r[0] for r in areas],
        "sedes": [r[0] for r in sedes],
        "tipos_novedad": [r[0] for r in tipos],
        "periodos": list(periodos),
    }


def get_resumen_por_area(db: Session, filters: dict) -> list[dict]:
    """
    Resumen de empleados agrupado por área.
    Usa archivo_origen (no periodo) para incluir TODOS los empleados del mes seleccionado.
    Activo = en el archivo sin renuncia/terminación en ese mismo archivo o REGISTRO MANUAL.
    """
    periodo_filter = filters.get("periodo")
    max_per_arch   = _max_periodo_archivos(db)

    if periodo_filter:
        año, mes = periodo_filter.split("-")
        arch = f"{mes}{año}.xlsx"
    elif max_per_arch:
        año, mes = max_per_arch.split("-")
        arch = f"{mes}{año}.xlsx"
    else:
        arch = None

    params: dict = {"arch": arch}
    arch_where = "AND n.archivo_origen = :arch" if arch else ""

    area_where = ""
    if filters.get("area"):
        area_where += " AND n.area = :area"
        params["area"] = filters["area"]
    if filters.get("sede"):
        area_where += " AND n.sede = :sede"
        params["sede"] = filters["sede"]

    max_per = max_per_arch or '9999-99'
    params['max_per'] = max_per

    is_sqlite = db.bind.dialect.name == "sqlite"
    glob_cond = "n.periodo GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]'" if is_sqlite else "n.periodo ~ '^[0-9]{4}-[0-9]{2}$'"

    sql = text(f"""
        SELECT
            COALESCE(n.area, '(Sin área)') AS area,
            COUNT(DISTINCT n.cedula)        AS total_empleados,
            COUNT(DISTINCT CASE
                WHEN NOT EXISTS (
                    SELECT 1 FROM novedades_nomina r
                    WHERE r.cedula = n.cedula
                      AND r.es_valido = 1
                      AND (LOWER(r.tipo_novedad) LIKE '%renuncia%'
                           OR LOWER(r.tipo_novedad) LIKE '%terminacion%')
                      AND (r.archivo_origen = :arch OR r.archivo_origen = 'REGISTRO MANUAL')
                ) THEN n.cedula END)        AS activos,
            COUNT(DISTINCT CASE
                WHEN EXISTS (
                    SELECT 1 FROM novedades_nomina r
                    WHERE r.cedula = n.cedula
                      AND r.es_valido = 1
                      AND (LOWER(r.tipo_novedad) LIKE '%renuncia%'
                           OR LOWER(r.tipo_novedad) LIKE '%terminacion%')
                      AND (r.archivo_origen = :arch OR r.archivo_origen = 'REGISTRO MANUAL')
                ) THEN n.cedula END)        AS inactivos,
            COUNT(CASE WHEN n.tipo_novedad != 'PRESENTE EN NOMINA' THEN 1 END) AS total_novedades,
            MAX(CASE
                WHEN {glob_cond}
                 AND n.periodo <= :max_per
                THEN n.periodo END)         AS ultimo_periodo
        FROM novedades_nomina n
        WHERE n.es_valido = 1 AND n.cedula IS NOT NULL
          {arch_where} {area_where}
        GROUP BY n.area
        ORDER BY total_empleados DESC
    """)
    rows = db.execute(sql, params).fetchall()
    result = []
    for r in rows:
        total = r.total_empleados or 0
        pct   = round(r.activos / total * 100, 1) if total else 0
        result.append({
            "area":             r.area,
            "total_empleados":  total,
            "activos":          r.activos or 0,
            "inactivos":        r.inactivos or 0,
            "pct_activos":      pct,
            "total_novedades":  r.total_novedades or 0,
            "ultimo_periodo":   r.ultimo_periodo,
        })
    return result


def get_empleados_lista(db: Session, filters: dict, estado_filter: str = "todos") -> EmpleadosListaResponse:
    """
    Lista de empleados del archivo del periodo seleccionado.
    Filtra por archivo_origen (no por campo periodo) para incluir TODOS los empleados del mes.
    Activo = en el archivo sin renuncia/terminación en ese mismo archivo o REGISTRO MANUAL.
    """
    periodo_filter = filters.get("periodo")
    max_per_arch   = _max_periodo_archivos(db)
    max_per        = max_per_arch or '9999-99'

    if periodo_filter:
        año, mes = periodo_filter.split("-")
        arch = f"{mes}{año}.xlsx"
    elif max_per_arch:
        año, mes = max_per_arch.split("-")
        arch = f"{mes}{año}.xlsx"
    else:
        arch = None

    params: dict = {"arch": arch, "max_per": max_per}
    arch_where = "AND n.archivo_origen = :arch" if arch else ""

    area_having = ""
    if filters.get("area"):
        area_having = "HAVING area = :area_filter"
        params["area_filter"] = filters["area"]

    sede_where = ""
    if filters.get("sede"):
        sede_where = "AND n.sede = :sede"
        params["sede"] = filters["sede"]

    # Filtro por tipo de novedad: solo empleados con esa novedad en el archivo
    tipo_where = ""
    if filters.get("tipo_novedad"):
        arch_cond = "AND t.archivo_origen = :arch" if arch else ""
        tipo_where = f"""AND EXISTS (
            SELECT 1 FROM novedades_nomina t
            WHERE t.cedula = n.cedula AND t.es_valido = 1
              {arch_cond}
              AND LOWER(t.tipo_novedad) LIKE :tipo_like
        )"""
        params["tipo_like"] = f"%{filters['tipo_novedad'].lower()}%"

    is_sqlite = db.bind.dialect.name == "sqlite"
    glob_cond = "n.periodo GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]'" if is_sqlite else "n.periodo ~ '^[0-9]{4}-[0-9]{2}$'"

    sql = text(f"""
        SELECT
            n.cedula,
            (SELECT n2.nombre_empleado FROM novedades_nomina n2
             WHERE n2.cedula = n.cedula AND n2.es_valido = 1
               AND n2.nombre_empleado IS NOT NULL
               AND n2.archivo_origen = :arch
             ORDER BY n2.id DESC LIMIT 1) AS nombre,
            (SELECT n2.area FROM novedades_nomina n2
             WHERE n2.cedula = n.cedula AND n2.es_valido = 1
               AND n2.area IS NOT NULL
               AND n2.archivo_origen = :arch
             ORDER BY n2.id DESC LIMIT 1) AS area,
            (SELECT n2.cargo FROM novedades_nomina n2
             WHERE n2.cedula = n.cedula AND n2.es_valido = 1
               AND n2.cargo IS NOT NULL
               AND n2.archivo_origen = :arch
             ORDER BY n2.id DESC LIMIT 1) AS cargo,
            MAX(CASE
                WHEN {glob_cond}
                 AND n.periodo <= :max_per
                THEN n.periodo END) AS ultimo_periodo,
            (
                SELECT tipo_novedad FROM novedades_nomina r2
                WHERE r2.cedula = n.cedula AND r2.es_valido = 1
                  AND (LOWER(r2.tipo_novedad) LIKE '%renuncia%'
                       OR LOWER(r2.tipo_novedad) LIKE '%terminacion%')
                  AND (r2.archivo_origen = :arch OR r2.archivo_origen = 'REGISTRO MANUAL')
                LIMIT 1
            ) AS novedad_retiro,
            CASE
                WHEN EXISTS (
                    SELECT 1 FROM novedades_nomina r3
                    WHERE r3.cedula = n.cedula AND r3.es_valido = 1
                      AND (LOWER(r3.tipo_novedad) LIKE '%renuncia%'
                           OR LOWER(r3.tipo_novedad) LIKE '%terminacion%')
                      AND (r3.archivo_origen = :arch OR r3.archivo_origen = 'REGISTRO MANUAL')
                ) THEN 'inactivo'
                ELSE 'activo'
            END AS estado
        FROM novedades_nomina n
        WHERE n.es_valido = 1 AND n.cedula IS NOT NULL
          {arch_where} {sede_where} {tipo_where}
        GROUP BY n.cedula
        {area_having}
        ORDER BY estado ASC, nombre ASC
    """)
    rows = db.execute(sql, params).fetchall()

    per_por_cedula = _max_periodo_por_cedula(db, max_per)

    total     = len(rows)
    activos   = sum(1 for r in rows if r.estado == 'activo')
    inactivos = total - activos

    if estado_filter == 'activo':
        rows = [r for r in rows if r.estado == 'activo']
    elif estado_filter == 'inactivo':
        rows = [r for r in rows if r.estado == 'inactivo']

    data = [
        EmpleadoEstado(
            cedula=r.cedula,
            nombre=r.nombre,
            area=r.area,
            cargo=r.cargo,
            ultimo_periodo=max(
                filter(None, [r.ultimo_periodo, per_por_cedula.get(r.cedula)])
            ) if (r.ultimo_periodo or per_por_cedula.get(r.cedula)) else None,
            ultima_novedad=r.novedad_retiro if r.estado == 'inactivo' else None,
            estado=r.estado,
        )
        for r in rows
    ]
    return EmpleadosListaResponse(total=total, activos=activos, inactivos=inactivos, data=data)


def get_empleados_ausentismo(db: Session, filters: dict) -> dict:
    """Retorna lista detallada de empleados con sus novedades de ausentismo."""
    try:
        tipos_aus = ['%incapaci%', '%licencia%', '%ausencia%', '%permiso%', '%maternidad%', '%paternidad%', '%calamidad%', '%luto%', '%accidente%']

        periodo_filter = filters.get("periodo")
        arch_aus = None
        if periodo_filter:
            try:
                año, mes = periodo_filter.split("-")
                arch_aus = f"{mes}{año}.xlsx"
            except (ValueError, IndexError):
                arch_aus = None

        # Base query para novedades de ausentismo
        aus_filter = db.query(NovedadNomina).filter(
            NovedadNomina.es_valido == 1,
            NovedadNomina.unidad == 'dias'
        )

        if arch_aus:
            aus_filter = aus_filter.filter(NovedadNomina.archivo_origen == arch_aus)
        if filters.get("area"):
            aus_filter = aus_filter.filter(NovedadNomina.area == filters["area"])
        if filters.get("sede"):
            aus_filter = aus_filter.filter(NovedadNomina.sede == filters["sede"])

        from sqlalchemy import or_

        # Filtrar solo registros con tipo de ausencia válido
        aus_records = aus_filter.filter(
            or_(*[NovedadNomina.tipo_novedad.ilike(t) for t in tipos_aus])
        ).order_by(NovedadNomina.fecha_inicio.desc()).all()

        # Procesar records para retornar en formato tabla
        data = []
        for record in aus_records:
            if not record.cedula:
                continue

            try:
                # Procesar fecha_inicio
                if record.fecha_inicio:
                    fecha_inicio_str = record.fecha_inicio.strftime('%Y-%m-%d')
                else:
                    fecha_inicio_str = "—"

                # Procesar fecha_fin
                if record.fecha_fin:
                    fecha_fin_str = record.fecha_fin.strftime('%Y-%m-%d')
                else:
                    fecha_fin_str = "—"

                # Procesar valor
                try:
                    valor_float = float(record.valor) if record.valor else 0.0
                except (TypeError, ValueError):
                    valor_float = 0.0

                # Procesar días
                try:
                    dias_int = int(record.dias) if record.dias else 0
                except (TypeError, ValueError):
                    dias_int = 0

                data.append({
                    "cedula": str(record.cedula).strip() if record.cedula else "—",
                    "nombre": str(record.nombre_empleado).strip() if record.nombre_empleado else "—",
                    "area": str(record.area).strip() if record.area else "—",
                    "sede": str(record.sede).strip() if record.sede else "—",
                    "tipo_novedad": str(record.tipo_novedad).strip() if record.tipo_novedad else "—",
                    "fecha_inicio": fecha_inicio_str,
                    "fecha_fin": fecha_fin_str,
                    "dias": dias_int,
                    "valor": valor_float,
                    "periodo": str(record.periodo).strip() if record.periodo else "—",
                })
            except Exception as e:
                # Log del error pero continúa con el siguiente registro
                print(f"Error procesando registro {record.id}: {str(e)}")
                continue

        return {
            "total": len(data),
            "data": data
        }
    except Exception as e:
        print(f"Error en get_empleados_ausentismo: {str(e)}")
        return {
            "total": 0,
            "data": [],
            "error": str(e)
        }
