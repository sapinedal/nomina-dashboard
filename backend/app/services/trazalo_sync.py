"""
Sincronización con Trazalo: sistema de novedades de RRHH en tiempo real
(PostgreSQL, base de datos externa `trazalo`).

A diferencia del Excel (reportes mensuales compilados manualmente), Trazalo
contiene novedades ya aprobadas por RRHH, capturadas en tiempo real, y cubre
TODO el personal (incluye áreas clínicas/asistenciales, no solo administrativas).

Estrategia (dos modos según el período, ver REEMPLAZA_DESDE_PERIODO):
  - REEMPLAZO (desde 2026-05): Trazalo ya tiene volumen de adopción completo,
    se convierte en la fuente autorizada — se invalidan los registros de Excel
    de ese mismo archivo_origen y se insertan los de Trazalo.
  - COMBINAR (antes de 2026-05): Trazalo todavía tenía muy poca adopción
    (decenas de eventos para ~1200 empleados) y reemplazar el Excel completo
    perdía datos reales (incapacidades, licencias, vacaciones). En estos
    períodos NO se invalida el Excel: los pocos eventos de Trazalo se agregan
    junto a los del Excel.
En ambos modos se sintetiza el mismo archivo_origen MMYYYY.xlsx que usa el
Excel, así todos los paneles existentes consumen los datos sin cambios.

Limitación conocida: el snapshot "PRESENTE EN NOMINA" usa el roster ACTUAL
de empleados activos en Trazalo para todos los períodos sincronizados (no hay
una foto histórica del roster por mes), así que el conteo de activos de meses
pasados sincronizados por Trazalo es una aproximación con el roster de hoy.
"""
from collections import defaultdict
from typing import Optional

import psycopg2
import psycopg2.extras
from sqlalchemy.orm import Session

from app.config import settings
from app.models.nomina import NovedadNomina
from app.services.excel_processor import normalize_sede
from app.utils.logger import get_logger

logger = get_logger(__name__)

HOJA_MARKER = "TRAZALO"

# A partir de este período (inclusive), Trazalo tiene volumen suficiente para
# considerarse la fuente autorizada y REEMPLAZA al Excel de ese mismo mes.
# Antes de este período, la adopción de Trazalo era muy baja (pocas decenas de
# eventos para ~1200 empleados) y reemplazar el Excel completo perdía datos
# reales de incapacidades/licencias/vacaciones que sí estaban capturados allí.
# Para esos meses tempranos se usa modo COMBINAR: Trazalo se agrega sin
# invalidar el Excel existente.
REEMPLAZA_DESDE_PERIODO = "2026-05"

# Tipos de novedad cuyo valor numérico real es HORAS (recargos/extras ya lo son
# en el propio sistema; PERMISO / CITA MÉDICA / DISPONIBILIDAD se capturan por
# horas parciales de jornada, no por días completos).
_TIPOS_HORAS = {
    "HORAS EXTRAS DIURNAS", "HORAS EXTRAS NOCTURNAS",
    "HORAS EXTRAS DIURNAS FESTIVAS", "HORAS EXTRAS NOCTURNAS FESTIVAS",
    "RECARGO NOCTURNO", "RECARGO FESTIVO", "RECARGO FESTIVO NOCTURNO",
    "PERMISO", "CITA MÉDICA", "DISPONIBILIDAD",
}
_TIPOS_VALOR = {"RODAMIENTO"}
# Todo lo demás (VACACIONES, INCAPACIDAD, LICENCIA, RENUNCIA, etc.) -> 'dias',
# calculado desde el rango fecha_inicial..fecha_final.


def _clean_cedula(raw) -> Optional[str]:
    if raw is None:
        return None
    s = str(raw).strip().replace(".", "").replace(" ", "")
    return s or None


def _get_connection():
    if not settings.TRAZALO_DB_HOST:
        raise RuntimeError("TRAZALO_DB_HOST no configurado en el entorno")
    conn = psycopg2.connect(
        host=settings.TRAZALO_DB_HOST,
        port=settings.TRAZALO_DB_PORT,
        dbname=settings.TRAZALO_DB_NAME,
        user=settings.TRAZALO_DB_USER,
        password=settings.TRAZALO_DB_PASSWORD,
        connect_timeout=10,
    )
    # Asegurar lectura correcta de tildes/ñ en áreas, nombres, etc.
    conn.set_client_encoding("UTF8")
    return conn


def _unidad_y_dias(tipo: str, total_horas, fecha_inicial, fecha_final) -> tuple[str, float]:
    if tipo in _TIPOS_HORAS:
        return "horas", float(total_horas or 0)
    if tipo in _TIPOS_VALOR:
        return "valor", float(total_horas) if total_horas else 1.0
    if fecha_inicial and fecha_final:
        dias = (fecha_final - fecha_inicial).days + 1
    else:
        dias = 1
    return "dias", float(max(dias, 1))


def _area_upper(raw: Optional[str]) -> Optional[str]:
    if not raw or not raw.strip():
        return None
    return raw.strip().upper()


def _sede_canon(raw: Optional[str]) -> Optional[str]:
    if not raw or not raw.strip():
        return None
    canon = normalize_sede(raw)
    return canon or None


def sync_trazalo(db: Session) -> dict:
    """Sincroniza novedades APROBADAS de Trazalo hacia novedades_nomina,
    reemplazando (por período) los registros que venían de Excel."""
    if not settings.TRAZALO_DB_HOST:
        logger.info("trazalo_sync_skipped", reason="no_configurado")
        return {"status": "skipped", "reason": "TRAZALO_DB_HOST no configurado"}

    try:
        conn = _get_connection()
    except Exception as e:
        logger.error("trazalo_connection_error", error=str(e))
        return {"status": "error", "error": str(e)}

    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # El área proviene del campo `area_informativa` del empleado (fuente
    # autorizada indicada por RRHH). Se usa la tabla relacional `areas` solo
    # como respaldo cuando area_informativa está vacía.
    cur.execute("""
        SELECT
            u.documento AS cedula,
            TRIM(CONCAT_WS(' ', u.primer_nombre, u.segundo_nombre, u.primer_apellido, u.segundo_apellido)) AS nombre,
            COALESCE(NULLIF(TRIM(u.area_informativa), ''), a.nombre) AS area,
            s.nombre AS sede, c.nombre AS cargo,
            tn.nombre AS tipo_novedad,
            n.fecha_inicial, n.fecha_final, n.total_horas,
            n.detalle_actividad AS observaciones,
            to_char(n.fecha_inicial, 'YYYY-MM') AS periodo
        FROM novedades n
        JOIN users u ON u.id = n.empleado_id
        JOIN tipo_novedades tn ON tn.id = n.tipo_novedad_id
        LEFT JOIN areas a ON a.id = u.area_id
        LEFT JOIN sedes s ON s.id = a.sede_id
        LEFT JOIN cargos c ON c.id = u.cargo_id
        WHERE n.estado = 'aprobada' AND n.fecha_inicial IS NOT NULL
        ORDER BY n.fecha_inicial
    """)
    filas = cur.fetchall()

    cur.execute("""
        SELECT u.documento AS cedula,
               u.salario,
               TRIM(CONCAT_WS(' ', u.primer_nombre, u.segundo_nombre, u.primer_apellido, u.segundo_apellido)) AS nombre,
               COALESCE(NULLIF(TRIM(u.area_informativa), ''), a.nombre) AS area,
               s.nombre AS sede, c.nombre AS cargo
        FROM users u
        LEFT JOIN areas a ON a.id = u.area_id
        LEFT JOIN sedes s ON s.id = a.sede_id
        LEFT JOIN cargos c ON c.id = u.cargo_id
        WHERE u.activo = true AND u.documento IS NOT NULL
    """)
    roster = cur.fetchall()
    cur.close()
    conn.close()

    # Sincronizar salarios en la tabla local salarios_empleados
    from sqlalchemy import text
    salarios_a_sincronizar = []
    for u in roster:
        cedula = _clean_cedula(u["cedula"])
        salario = u.get("salario")
        if cedula and salario is not None:
            try:
                salario_val = float(salario)
                salarios_a_sincronizar.append({"cedula": cedula, "salario": salario_val})
            except (ValueError, TypeError):
                continue

    if salarios_a_sincronizar:
        sql_upsert = text("""
            INSERT INTO salarios_empleados (cedula, salario)
            VALUES (:cedula, :salario)
            ON CONFLICT (cedula) 
            DO UPDATE SET salario = EXCLUDED.salario
        """)
        for item in salarios_a_sincronizar:
            db.execute(sql_upsert, item)
        db.commit()
        logger.info("trazalo_salarios_sincronizados", total=len(salarios_a_sincronizar))

    por_periodo: dict[str, list] = defaultdict(list)
    for f in filas:
        por_periodo[f["periodo"]].append(f)

    total_periodos = total_insertados = total_invalidados = 0

    for periodo, registros in sorted(por_periodo.items()):
        anio, mes = periodo.split("-")
        archivo_origen = f"{mes}{anio}.xlsx"
        modo_reemplazo = periodo >= REEMPLAZA_DESDE_PERIODO

        invalidados = 0
        if modo_reemplazo:
            invalidados = (
                db.query(NovedadNomina)
                .filter(
                    NovedadNomina.archivo_origen == archivo_origen,
                    NovedadNomina.hoja_origen != HOJA_MARKER,
                    NovedadNomina.es_valido == 1,
                )
                .update(
                    {
                        "es_valido": 0,
                        "razon_invalido": "Reemplazado por sincronización en tiempo real de Trazalo",
                    },
                    synchronize_session=False,
                )
            )
        else:
            # Modo COMBINAR: por si antes se invalidó el Excel de este período
            # (ej. en una sincronización previa a este cambio), restaurarlo.
            (
                db.query(NovedadNomina)
                .filter(
                    NovedadNomina.archivo_origen == archivo_origen,
                    NovedadNomina.hoja_origen != HOJA_MARKER,
                    NovedadNomina.es_valido == 0,
                    NovedadNomina.razon_invalido.ilike("%Trazalo%"),
                )
                .update(
                    {"es_valido": 1, "razon_invalido": None},
                    synchronize_session=False,
                )
            )
        total_invalidados += invalidados

        db.query(NovedadNomina).filter(
            NovedadNomina.archivo_origen == archivo_origen,
            NovedadNomina.hoja_origen == HOJA_MARKER,
        ).delete(synchronize_session=False)

        nuevos = []
        cedulas_con_novedad = set()
        for f in registros:
            cedula = _clean_cedula(f["cedula"])
            if not cedula:
                continue
            cedulas_con_novedad.add(cedula)
            unidad, dias = _unidad_y_dias(
                f["tipo_novedad"], f["total_horas"], f["fecha_inicial"], f["fecha_final"]
            )
            nuevos.append({
                "cedula": cedula,
                "nombre_empleado": f["nombre"] or None,
                "area": _area_upper(f["area"]),
                "sede": _sede_canon(f["sede"]),
                "cargo": f["cargo"],
                "tipo_novedad": f["tipo_novedad"],
                "descripcion_novedad": f["observaciones"] or f["tipo_novedad"],
                "fecha_inicio": f["fecha_inicial"],
                "fecha_fin": f["fecha_final"],
                "dias": dias,
                "unidad": unidad,
                "valor": None,
                "estado": "aprobada",
                "observaciones": f["observaciones"],
                "periodo": periodo,
                "columnas_extra": None,
                "archivo_origen": archivo_origen,
                "hoja_origen": HOJA_MARKER,
                "fecha_modificacion_archivo": None,
                "execution_id": None,
                "es_valido": 1,
                "razon_invalido": None,
            })

        for u in roster:
            cedula = _clean_cedula(u["cedula"])
            if not cedula or cedula in cedulas_con_novedad:
                continue
            nuevos.append({
                "cedula": cedula,
                "nombre_empleado": u["nombre"] or None,
                "area": _area_upper(u["area"]),
                "sede": _sede_canon(u["sede"]),
                "cargo": u["cargo"],
                "tipo_novedad": "PRESENTE EN NOMINA",
                "descripcion_novedad": "PRESENTE EN NOMINA",
                "fecha_inicio": None,
                "fecha_fin": None,
                "dias": None,
                "unidad": None,
                "valor": None,
                "estado": None,
                "observaciones": None,
                "periodo": periodo,
                "columnas_extra": None,
                "archivo_origen": archivo_origen,
                "hoja_origen": HOJA_MARKER,
                "fecha_modificacion_archivo": None,
                "execution_id": None,
                "es_valido": 1,
                "razon_invalido": None,
            })

        if nuevos:
            db.bulk_insert_mappings(NovedadNomina, nuevos)
        db.commit()

        total_periodos += 1
        total_insertados += len(nuevos)
        logger.info(
            "trazalo_periodo_sincronizado", periodo=periodo, archivo=archivo_origen,
            modo="reemplazo" if modo_reemplazo else "combinar",
            insertados=len(nuevos), invalidados_excel=invalidados,
        )

    logger.info(
        "trazalo_sync_completado", periodos=total_periodos,
        insertados=total_insertados, invalidados=total_invalidados,
    )
    return {
        "status": "ok",
        "periodos_sincronizados": total_periodos,
        "registros_insertados": total_insertados,
        "registros_excel_invalidados": total_invalidados,
    }
