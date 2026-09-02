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

from sqlalchemy.orm import Session

from app.config import settings
from app.models.nomina import NovedadNomina
from app.services.excel_processor import normalize_sede
from app.utils.logger import get_logger
from app.utils.razon_social import es_razon_social

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
    # El driver se importa aqui y no arriba a proposito: asi el resto del modulo
    # —la logica que ya recibe los datos y solo los vuelca en la BD local— se
    # puede importar y probar sin tener psycopg2 instalado.
    import psycopg2
    import psycopg2.extras

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



def _desactivar_empresas(db, extra_cedulas) -> int:
    """Pone activo=0 a razones sociales ya mezcladas en el roster local.

    Toma las cédulas/NIT que Trazalo acaba de mandar como empresa (aunque el
    nombre local esté vacío) y, además, barre filas cuyo `nombre` ya sea
    razón social por un sync anterior.
    """
    from sqlalchemy import text

    cedulas = {c for c in extra_cedulas if c}
    for row in db.execute(text(
        "SELECT cedula, nombre FROM salarios_empleados WHERE nombre IS NOT NULL"
    )).fetchall():
        mapping = row._mapping
        if es_razon_social(mapping["nombre"]):
            cedulas.add(mapping["cedula"])
    if not cedulas:
        return 0
    sql = text(
        "UPDATE salarios_empleados SET activo = 0 "
        "WHERE cedula = :cedula AND COALESCE(activo, 1) <> 0"
    )
    for cedula in cedulas:
        db.execute(sql, {"cedula": cedula})
    return len(cedulas)


def invalidar_novedades_empresas(db, extra_cedulas=()) -> int:
    """Saca de la prenómina las novedades de razones sociales.

    El dashboard de empleados lee `novedades_nomina`, no el roster. Dejar
    `activo=0` en salarios_empleados no basta: un PRESENTE EN NOMINA viejo
    (o una fila de Excel) sigue mostrando a AGUAS DEL PUERTO como empleado.
    """
    from sqlalchemy import text

    cedulas = {c for c in extra_cedulas if c}
    for row in db.execute(text(
        "SELECT DISTINCT cedula, nombre_empleado AS nombre "
        "FROM novedades_nomina "
        "WHERE es_valido = 1 AND cedula IS NOT NULL AND nombre_empleado IS NOT NULL"
    )).fetchall():
        mapping = row._mapping
        if es_razon_social(mapping["nombre"]):
            cedulas.add(mapping["cedula"])
    if not cedulas:
        return 0
    sql = text(
        "UPDATE novedades_nomina "
        "SET es_valido = 0, razon_invalido = :razon "
        "WHERE cedula = :cedula AND es_valido = 1"
    )
    filas = 0
    razon = "Razón social, no es empleado"
    for cedula in cedulas:
        result = db.execute(sql, {"cedula": cedula, "razon": razon})
        filas += result.rowcount or 0
    db.commit()
    logger.info("trazalo_novedades_empresas_invalidadas",
                cedulas=len(cedulas), filas=filas)
    return filas


def purgar_razones_sociales(db=None, extra_cedulas=()) -> dict:
    """Limpia empresas ya mezcladas en roster y novedades. Idempotente.

    El dashboard lista gente desde `novedades_nomina`, no desde el roster.
    Sin este barrido, un PRESENTE EN NOMINA viejo sigue mostrando a
    AGUAS DEL PUERTO como empleado aunque el sync ya no las inserte.
    Se llama al arrancar la app (redeploy) y al terminar cada sync.
    """
    from app.database import SessionLocal

    close = False
    if db is None:
        db = SessionLocal()
        close = True
    try:
        n_roster = _desactivar_empresas(db, extra_cedulas)
        if n_roster:
            db.commit()
        n_nov = invalidar_novedades_empresas(db, extra_cedulas)
        logger.info("trazalo_razones_sociales_purgadas",
                    roster=n_roster, novedades=n_nov)
        return {"roster_desactivadas": n_roster, "novedades_invalidadas": n_nov}
    except Exception as e:
        logger.error("trazalo_purge_error", error=str(e))
        try:
            db.rollback()
        except Exception:
            pass
        return {"error": str(e)}
    finally:
        if close:
            db.close()


def sincronizar_roster(db, roster: list) -> dict:
    """Vuelca el roster de Trazalo en `salarios_empleados`.

    Se guarda el roster de EMPLEADOS y no solo el salario: el reporte de nomina
    necesita saber que empleados existen en cada area aunque no tengan ninguna
    novedad en el periodo. `activo` viene del WHERE de la consulta del roster
    (u.activo = true), asi que todo lo que llega aqui esta activo en Trazalo.

    Las razones sociales (S.A.S, E.S.P., LTDA, etc.) se omiten: Trazalo las
    mezcla en `users` junto al personal, y no deben liquidarse ni aparecer en
    prenomina. Si ya estaban en la tabla local, se desactivan.

    **La identidad se sincroniza tenga o no salario.** Antes toda la fila se
    descartaba con `if salario is not None`, y eso dejaba en el reporte filas
    con cedula y salario viejo pero con nombre, area y cargo vacios: empleados
    activos en Trazalo a los que ese sistema no les expone salario (el grueso
    del personal clinico) y que por eso nunca recibian su identidad. Bug
    reportado el 2026-08-26 sobre el Excel de produccion.

    Por eso hay dos caminos y no uno:

    - Con salario: UPSERT, que puede crear la fila.
    - Sin salario: UPDATE de la identidad sobre la fila que ya exista. No se
      inserta porque `salarios_empleados.salario` es NOT NULL; un empleado sin
      salario y sin fila previa sigue sin aparecer en la prenomina, que es la
      decision ya tomada de no liquidar con salarios inventados.

    Devuelve el conteo de cada camino, para que quede en el log que se hizo.
    """
    from sqlalchemy import text

    con_salario, sin_salario = [], []
    empresas_cedulas = []
    for u in roster:
        cedula = _clean_cedula(u["cedula"])
        if not cedula:
            continue
        if es_razon_social(u.get("nombre")):
            empresas_cedulas.append(cedula)
            continue
        # _area_upper es la MISMA normalizacion que se aplica al area de cada
        # novedad. Sin ella el area del roster no casaria con las areas
        # asignadas a un analista y el reporte le saldria vacio.
        identidad = {
            "cedula": cedula,
            "nombre": u.get("nombre"),
            "area": _area_upper(u.get("area")),
            "sede": u.get("sede"),
            "cargo": u.get("cargo"),
        }
        salario = u.get("salario")
        if salario is None:
            sin_salario.append(identidad)
            continue
        try:
            con_salario.append({**identidad, "salario": float(salario)})
        except (ValueError, TypeError):
            # Un salario ilegible no puede costarle la identidad al empleado.
            sin_salario.append(identidad)

    if con_salario:
        sql_upsert = text("""
            INSERT INTO salarios_empleados (cedula, salario, nombre, area, sede, cargo, activo)
            VALUES (:cedula, :salario, :nombre, :area, :sede, :cargo, 1)
            ON CONFLICT (cedula)
            DO UPDATE SET salario = EXCLUDED.salario,
                          nombre  = EXCLUDED.nombre,
                          area    = EXCLUDED.area,
                          sede    = EXCLUDED.sede,
                          cargo   = EXCLUDED.cargo,
                          activo  = 1
        """)
        for item in con_salario:
            db.execute(sql_upsert, item)

    if sin_salario:
        # Solo identidad: el salario que ya estuviera guardado NO se toca, es el
        # unico que hay para liquidar a esa persona.
        sql_identidad = text("""
            UPDATE salarios_empleados
               SET nombre = :nombre, area = :area, sede = :sede,
                   cargo = :cargo, activo = 1
             WHERE cedula = :cedula
        """)
        for item in sin_salario:
            db.execute(sql_identidad, item)

    empresas_desactivadas = _desactivar_empresas(db, empresas_cedulas)

    if con_salario or sin_salario or empresas_desactivadas or empresas_cedulas:
        db.commit()
        logger.info(
            "trazalo_roster_sincronizado",
            con_salario=len(con_salario),
            sin_salario=len(sin_salario),
            empresas_omitidas=len(empresas_cedulas),
            empresas_desactivadas=empresas_desactivadas,
        )
    return {
        "con_salario": len(con_salario),
        "sin_salario": len(sin_salario),
        "empresas_omitidas": len(empresas_cedulas),
    }



def obtener_empleados_sin_salario() -> list[dict]:
    """Empleados activos en Trazalo a los que ese sistema no les registra salario.

    Es la lista que NO se puede sacar de la base local: `salarios_empleados`
    solo tiene fila para quien tuvo salario alguna vez, asi que armarla desde
    ahi se saltaria justo a quienes nunca lo han tenido — que son la mayoria del
    personal clinico y el motivo por el que este reporte existe.

    Consulta Trazalo en vivo, con la misma definicion de "activo" que usa el
    sync (`u.activo = true`), para que la lista cuadre con lo que el dashboard
    cuenta como `empleados_sin_salario`. Un salario en cero se trata como
    ausente: para liquidar da exactamente lo mismo.

    Devuelve identidad, nunca dinero: el punto es saber a quien le falta cargar
    el salario, no cuanto gana nadie. El area sale normalizada con `_area_upper`
    igual que en el resto del sistema, porque el endpoint filtra con ella por
    las areas autorizadas del usuario.
    """
    import psycopg2.extras  # ver el comentario de _get_connection

    conn = _get_connection()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT u.documento AS cedula,
                   TRIM(CONCAT_WS(' ', u.primer_nombre, u.segundo_nombre,
                                       u.primer_apellido, u.segundo_apellido)) AS nombre,
                   COALESCE(NULLIF(TRIM(u.area_informativa), ''), a.nombre) AS area,
                   s.nombre AS sede, c.nombre AS cargo
            FROM users u
            LEFT JOIN areas a ON a.id = u.area_id
            LEFT JOIN sedes s ON s.id = a.sede_id
            LEFT JOIN cargos c ON c.id = u.cargo_id
            WHERE u.activo = true AND u.documento IS NOT NULL
              AND COALESCE(u.salario, 0) <= 0
        """)
        filas = [
            {
                "cedula": _clean_cedula(r["cedula"]),
                "nombre": r.get("nombre"),
                "area": _area_upper(r.get("area")),
                "sede": r.get("sede"),
                "cargo": r.get("cargo"),
            }
            for r in cur.fetchall()
        ]
        cur.close()
    finally:
        conn.close()

    filas.sort(key=lambda f: ((f["area"] or ""), (f["nombre"] or "")))
    logger.info("trazalo_empleados_sin_salario", total=len(filas))
    return filas


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

    import psycopg2.extras  # ver el comentario de _get_connection

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

    # Sincronizar el roster en la tabla local salarios_empleados
    sincronizar_roster(db, roster)
    empresas_cedulas = [
        _clean_cedula(u["cedula"]) for u in roster
        if es_razon_social(u.get("nombre"))
    ]

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
            if not cedula or es_razon_social(f.get("nombre")):
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
            if not cedula or cedula in cedulas_con_novedad or es_razon_social(u.get("nombre")):
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

    purgar_razones_sociales(db, empresas_cedulas)

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
