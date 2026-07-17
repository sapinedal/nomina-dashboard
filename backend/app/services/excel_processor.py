"""
Procesador de archivos Excel — CONSOLIDADO de Novedades de Nómina (Sumimedical).

Formato real del archivo:
  - Filas 0-2: encabezado decorativo / metadatos del formulario
  - Fila 3:   encabezados reales de columnas
  - Fila 4+:  datos de empleados

Estructura (formato ancho / pivotado):
  No. | SEDE | IDENTIFICACIÓN | NOMBRES Y APELLIDOS | SALARIO | BLOQUE HORAS | HORAS MES
    | INGRESO | RENUNCIA | INCAPACIDAD | ... (un tipo de novedad por columna) ...
    | FEHCA INICIO NOVEDAD | FEHCA FINAL NOVEDAD | OBSERVACIONES

El procesador detecta el encabezado automáticamente, convierte el formato ancho a largo
(melt) y genera un registro por cada (empleado × novedad) con valor no nulo.
"""
import os
import re
import sys
import json
import subprocess
import platform
from pathlib import Path
from datetime import datetime
from typing import Optional

import pandas as pd
from sqlalchemy.orm import Session

from app.config import settings
from app.models.execution import ExecutionLog, ProcessedFile, ExecutionStatus
from app.models.nomina import NovedadNomina
from app.utils.logger import get_logger
from app.utils.validators import parse_date_flexible, validate_row, clean_valor, infer_periodo

logger = get_logger(__name__)

SUPPORTED_EXTENSIONS = {".xlsx", ".xls", ".xlsm"}

# Palabras clave para detectar la fila de encabezados reales
HEADER_KEYWORDS = [
    "identificaci", "cedula", "cédula", "nombres y", "apellido",
    "sede", "cargo", "tipo novedad",
]

# ── Patrones de clasificación de columnas ────────────────────────────────────
# Cada tupla: (lista de substrings, campo_estándar_o_None)
# None → tipo de novedad (se melt-ea)
# '__skip' → columna ignorada

_COL_CEDULA   = ['identificaci', 'cédula', 'cedula', 'documento', 'c.c']
_COL_NOMBRE   = ['nombres y apellidos', 'nombres y', 'nombre y', 'apellidos y nombres']
_COL_SEDE     = ['sede', 'área', 'dependencia']
_COL_AREA     = ['area']          # solo como palabra completa (comprobar aparte)
_COL_FI       = ['fecha inicio', 'fecha_inicio', 'inicio novedad', 'fehca inicio', 'fecha inico']
_COL_FF       = ['fecha fin', 'fecha final', 'fehca fin', 'fehca final', 'fin novedad', 'final novedad']
_COL_OBS      = ['observaci']
# Columnas a ignorar (no son novedades ni identidad relevante)
_COL_SKIP     = ['no.', 'n°', 'salario', 'bloque de hora', 'horas laboradas',
                  'fecha de aprobaci', 'versión', 'version', 'código', 'codigo']


# ─── Acceso a la carpeta compartida ───────────────────────────────────────────

def _mount_smb_share_linux(share_path: str) -> Optional[str]:
    mount_point = "/mnt/nomina_share"
    os.makedirs(mount_point, exist_ok=True)

    parts = share_path.replace("\\\\", "").replace("\\", "/").split("/", 2)
    if len(parts) < 2:
        raise ValueError(f"Ruta UNC inválida: {share_path}")

    host, share_name = parts[0], parts[1]
    sub_dir = parts[2] if len(parts) > 2 else ""
    smb_target = f"//{host}/{share_name}"

    creds = []
    if settings.NETWORK_SHARE_USER:
        creds.append(f"username={settings.NETWORK_SHARE_USER}")
    if settings.NETWORK_SHARE_PASSWORD:
        creds.append(f"password={settings.NETWORK_SHARE_PASSWORD}")
    if settings.NETWORK_SHARE_DOMAIN:
        creds.append(f"domain={settings.NETWORK_SHARE_DOMAIN}")

    options = ",".join(["vers=2.0", "uid=0", "gid=0", "file_mode=0777", "dir_mode=0777"] + creds)

    try:
        r = subprocess.run(
            ["mount", "-t", "cifs", smb_target, mount_point, "-o", options],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0 and "already mounted" not in r.stderr:
            logger.warning("smb_mount_warning", stderr=r.stderr)
    except Exception as e:
        logger.warning("smb_mount_error", error=str(e))

    return str(Path(mount_point) / sub_dir if sub_dir else Path(mount_point))


def get_network_path() -> Path:
    raw = settings.NETWORK_SHARE_PATH
    if platform.system() == "Windows":
        return Path(raw)
    if os.path.isdir("/mnt/nomina_share"):
        return Path("/mnt/nomina_share")
    return Path(_mount_smb_share_linux(raw))


def list_excel_files(base_path: Path) -> list[Path]:
    """Lista recursiva de archivos Excel válidos, omitiendo temporales."""
    files = []
    try:
        for entry in base_path.rglob("*"):
            if not entry.is_file():
                continue
            if entry.name.startswith("~$") or entry.name.startswith("."):
                logger.info("file_skipped_temp", name=entry.name)
                continue
            if entry.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            try:
                entry.stat()
            except (PermissionError, OSError) as e:
                logger.warning("file_inaccessible", name=entry.name, error=str(e))
                continue
            files.append(entry)
    except PermissionError as e:
        logger.error("permission_error_listing", path=str(base_path), error=str(e))
    except Exception as e:
        logger.error("error_listing_files", path=str(base_path), error=str(e))

    logger.info("files_found", count=len(files), path=str(base_path))
    return sorted(files)


# ─── Homologación de sedes y áreas ───────────────────────────────────────────

from app.utils.normalizers import (  # noqa: F401  (re-export para retrocompatibilidad)
    _strip_accents,
    _pre_clean,
    _SEDE_CANON,
    _SEDE_BLOCKLIST,
    _AREA_CANON,
    normalize_sede,
    normalize_area,
)


# ─── Override de área por cédula para hojas ambiguas ──────────────────────────
# Algunas hojas (ej. 'SI-NR' del archivo 072024) mezclan personal de varias áreas
# distintas en una sola pestaña, por lo que el nombre de la hoja no basta para
# determinar el área. Aquí se reasigna cada empleado a su área real (confirmada
# por su clasificación en los meses adyacentes). Clave externa = área que produce
# normalize_area para esa hoja; clave interna = cédula → área correcta.
_AREA_OVERRIDE_POR_CEDULA: dict[str, dict[str, str]] = {
    "SI NR": {
        "1000884719": "BASE DE DATOS",
        "1020472197": "BASE DE DATOS",
        "1000290325": "BASE DE DATOS",
        "1234990195": "BASE DE DATOS",
        "1017924704": "BASE DE DATOS",
        "1036131909": "DESARROLLO",
        "1020466970": "DESARROLLO",
        "1035877094": "DESARROLLO",
        "1001017647": "DESARROLLO",
    },
}


def resolve_area(sheet_name: str, cedula: Optional[str]) -> str:
    """Área de un registro: normaliza el nombre de hoja y aplica overrides por
    cédula cuando la hoja es ambigua (ver _AREA_OVERRIDE_POR_CEDULA)."""
    area = normalize_area(sheet_name)
    overrides = _AREA_OVERRIDE_POR_CEDULA.get(area)
    if overrides and cedula:
        ced = str(cedula).strip().replace(".", "").replace(" ", "")
        return overrides.get(ced, area)
    return area


# ─── Unidad de medida por tipo de novedad ────────────────────────────────────

# Patrones sobre el tipo de novedad normalizado (minúsculas, sin tildes)
_UNIDAD_HORAS = [
    r'recargo',          # RECARGO NOCTURNO, FESTIVO, FESTIVO NOCTURNO
    r'hora.{0,3}extra',  # HORAS EXTRAS DIURNAS/NOCTURNAS/FESTIVAS
    r'hora.{0,3}noct',   # por si acaso variantes
]
_UNIDAD_VALOR = [
    r'rodamiento',       # RODAMIENTO CARRO / MOTO (auxilio transporte/vehículo)
    r'bienestar',        # PLAN BENEFICIOS BIENESTAR LABORAL
    r'beneficio',
]
# Todo lo demás (incapacidad, permisos, licencias, vacaciones, ausencias…) → 'dias'


def get_tipo_unidad(tipo_novedad: str) -> str:
    """
    Determina la unidad de medida del valor numérico de una novedad:
      'horas'  → recargos y horas extras
      'valor'  → rodamientos y beneficios (valor monetario/unidades)
      'dias'   → incapacidades, permisos, licencias, vacaciones, etc. (predeterminado)
    """
    if not tipo_novedad:
        return "dias"
    t = _strip_accents(tipo_novedad.lower())
    for p in _UNIDAD_HORAS:
        if re.search(p, t):
            return "horas"
    for p in _UNIDAD_VALOR:
        if re.search(p, t):
            return "valor"
    return "dias"


# ─── Detección de encabezado y clasificación de columnas ─────────────────────

def _find_header_row(xl: pd.ExcelFile, sheet_name: str, max_scan: int = 15) -> int:
    """Detecta la fila que contiene los encabezados reales buscando palabras clave."""
    try:
        df_raw = xl.parse(sheet_name, header=None, nrows=max_scan, dtype=str)
    except Exception:
        return 0
    for i, row in df_raw.iterrows():
        row_text = " ".join(
            str(v).lower().strip().replace("fehca", "fecha")
            for v in row.values if str(v) not in ("nan", "None", "")
        )
        if any(kw in row_text for kw in HEADER_KEYWORDS):
            return i
    return 0


def _classify_col(col: str) -> Optional[str]:
    """
    Clasifica una columna por su nombre.
    Retorna el campo estándar ('cedula', 'nombre_empleado', etc.),
    '__skip' para columnas a ignorar, o None si es un tipo de novedad.
    """
    c = str(col).lower().strip().replace("fehca", "fecha")

    if any(p in c for p in _COL_CEDULA):
        return "cedula"
    if any(p in c for p in _COL_NOMBRE):
        return "nombre_empleado"
    if any(p in c for p in _COL_SEDE):
        return "sede"
    # 'area' solo como palabra suelta para no capturar 'bienestar laboral'
    if re.search(r'\barea\b', c):
        return "sede"
    if any(p in c for p in _COL_FI):
        return "fecha_inicio"
    if any(p in c for p in _COL_FF):
        return "fecha_fin"
    if any(p in c for p in _COL_OBS):
        return "observaciones"
    if any(p in c for p in _COL_SKIP):
        return "__skip"
    if c.startswith("unnamed") or c in ("nan", "no", "n°", "num", "#", ""):
        return "__skip"
    return None  # tipo de novedad


# ─── Lectura y transformación de una hoja ────────────────────────────────────

def _safe_float(value) -> Optional[float]:
    try:
        if pd.isna(value) or value is None:
            return None
        s = str(value).strip().replace(",", ".").replace(" ", "")
        return float(s) if s else None
    except Exception:
        return None


def _get_file_mtime(path: Path) -> Optional[datetime]:
    try:
        return datetime.utcfromtimestamp(path.stat().st_mtime)
    except Exception:
        return None


def _read_sheet(
    xl: pd.ExcelFile,
    sheet_name: str,
    file_name: str,
    file_modified: Optional[datetime],
    execution_id: int,
) -> tuple[list[dict], list[dict]]:
    """
    Lee una hoja en formato ancho (pivotado), la convierte a largo (melt)
    y retorna (registros_válidos, registros_inválidos).
    """
    # 1. Detectar fila real del encabezado
    header_row = _find_header_row(xl, sheet_name)

    try:
        df = xl.parse(sheet_name, header=header_row, dtype=str)
    except Exception as e:
        logger.error("sheet_read_error", sheet=sheet_name, file=file_name, error=str(e))
        return [], []

    df = df.dropna(how="all")
    if df.empty:
        logger.info("sheet_empty", sheet=sheet_name, file=file_name)
        return [], []

    # 2. Clasificar columnas directamente por su nombre
    #    identity_rename: orig_col → campo_estándar
    #    novedad_cols: lista de nombres ORIGINALES de columnas de novedad
    identity_rename: dict = {}
    novedad_cols: list = []
    skip_cols: list = []

    for orig_col in df.columns:
        cls = _classify_col(str(orig_col))
        if cls == "__skip":
            skip_cols.append(orig_col)
        elif cls is not None:
            # Columna de identidad — solo guardar la primera aparición de cada campo
            if cls not in identity_rename.values():
                identity_rename[orig_col] = cls
            else:
                skip_cols.append(orig_col)   # duplicado, ignorar
        else:
            # Tipo de novedad
            novedad_cols.append(orig_col)

    logger.info(
        "sheet_classified",
        file=file_name, sheet=sheet_name,
        header_row=header_row,
        identity_cols=list(identity_rename.values()),
        novedad_count=len(novedad_cols),
        rows=len(df),
    )

    if not novedad_cols:
        logger.info("no_novedad_cols", sheet=sheet_name, file=file_name,
                    all_cols=list(df.columns[:20]))
        return [], []

    # 3. Preparar DataFrame: drop skip, rename identity
    df = df.drop(columns=skip_cols, errors="ignore")
    df = df.rename(columns=identity_rename)

    # id_vars son los campos estándar que quedaron en el df
    id_vars = [c for c in identity_rename.values() if c in df.columns]

    # Verificar que las novedad_cols siguen en df (no se renombraron)
    novedad_cols_present = [c for c in novedad_cols if c in df.columns]

    if not novedad_cols_present:
        logger.warning("novedad_cols_missing_after_rename",
                       sheet=sheet_name, file=file_name,
                       expected=novedad_cols[:5], actual=list(df.columns[:10]))
        return [], []

    # 4. Melt: de ancho a largo
    try:
        df_long = df.melt(
            id_vars=id_vars,
            value_vars=novedad_cols_present,
            var_name="tipo_novedad",
            value_name="valor_novedad",
        )
    except Exception as e:
        logger.error("melt_error", sheet=sheet_name, file=file_name,
                     id_vars=id_vars, value_vars=novedad_cols_present[:5], error=str(e))
        return [], []

    # 5. Capturar identidad de TODOS los empleados antes de filtrar por valor
    #    (incluye los que no tienen ninguna novedad ese período)
    null_vals = {"nan", "none", ""}

    def _is_valid_id(series: "pd.Series") -> "pd.Series":
        return series.notna() & (~series.astype(str).str.strip().str.lower().isin(null_vals))

    mask_cedula_all = _is_valid_id(df_long["cedula"]) if "cedula" in df_long.columns \
        else pd.Series(False, index=df_long.index)
    mask_nombre_all = _is_valid_id(df_long["nombre_empleado"]) if "nombre_empleado" in df_long.columns \
        else pd.Series(False, index=df_long.index)

    # DataFrame de identidad única por empleado (cedula/nombre + metadatos)
    id_cols_present = [c for c in ["cedula", "nombre_empleado", "sede"] if c in df_long.columns]
    df_identidad = (
        df_long[mask_cedula_all | mask_nombre_all][id_cols_present]
        .drop_duplicates(subset=["cedula"] if "cedula" in id_cols_present else id_cols_present)
        .copy()
    )

    # 5b. Filtrar filas sin valor de novedad real
    df_long = df_long[
        df_long["valor_novedad"].notna() &
        (~df_long["valor_novedad"].astype(str).str.strip().str.lower().isin(null_vals))
    ]

    # Filtrar filas sin empleado identificable (cedula o nombre)
    mask_cedula = pd.Series(False, index=df_long.index)
    mask_nombre = pd.Series(False, index=df_long.index)
    if "cedula" in df_long.columns:
        mask_cedula = (
            df_long["cedula"].notna() &
            (~df_long["cedula"].astype(str).str.strip().str.lower().isin(null_vals))
        )
    if "nombre_empleado" in df_long.columns:
        mask_nombre = (
            df_long["nombre_empleado"].notna() &
            (~df_long["nombre_empleado"].astype(str).str.strip().str.lower().isin(null_vals))
        )
    df_long = df_long[mask_cedula | mask_nombre]

    # Empleados con cedula que ya tienen al menos una novedad (no necesitan fila extra)
    cedulas_con_novedad: set = set()
    if "cedula" in df_long.columns:
        cedulas_con_novedad = set(
            df_long["cedula"].dropna().astype(str).str.strip()
            .str.replace(".", "", regex=False).str.replace(" ", "")
        ) - {"", "nan", "none"}

    if df_long.empty and df_identidad.empty:
        logger.info("no_records_after_melt", sheet=sheet_name, file=file_name)
        return [], []

    # El nombre de la HOJA es el departamento/área; la columna SEDE es la ubicación física.
    area_canon = normalize_area(sheet_name)

    # 6. Construir registros
    valid_records: list[dict] = []
    invalid_records: list[dict] = []

    # 6a. Insertar "PRESENTE EN NÓMINA" para empleados sin ninguna novedad en este período
    periodo_archivo = infer_periodo({}, file_name)
    for _, id_row in df_identidad.iterrows():
        ced_raw = str(id_row.get("cedula", "") or "").strip().replace(".", "").replace(" ", "")
        if ced_raw in cedulas_con_novedad or not ced_raw or ced_raw.lower() in {"nan", "none", ""}:
            continue  # ya tiene novedades o no tiene cédula válida
        nombre_p = str(id_row.get("nombre_empleado", "") or "").strip() or None
        sede_raw_p = str(id_row.get("sede", "") or "").strip()
        presente = {
            "cedula":               ced_raw,
            "nombre_empleado":      nombre_p,
            "area":                 resolve_area(sheet_name, ced_raw),
            "sede":                 normalize_sede(sede_raw_p) if sede_raw_p else None,
            "cargo":                None,
            "tipo_novedad":         "PRESENTE EN NOMINA",
            "descripcion_novedad":  "PRESENTE EN NOMINA",
            "fecha_inicio":         None,
            "fecha_fin":            None,
            "dias":                 None,
            "unidad":               None,
            "valor":                None,
            "estado":               None,
            "observaciones":        None,
            "periodo":              periodo_archivo,
            "columnas_extra":       None,
            "archivo_origen":       file_name,
            "hoja_origen":          sheet_name,
            "fecha_modificacion_archivo": file_modified,
            "execution_id":         execution_id,
            "es_valido":            1,
            "razon_invalido":       None,
        }
        valid_records.append(presente)

    for _, row in df_long.iterrows():
        cedula = str(row.get("cedula", "") or "").strip().replace(".", "").replace(" ", "") or None
        nombre = str(row.get("nombre_empleado", "") or "").strip() or None
        sede_raw = str(row.get("sede", "") or "").strip()
        sede_canon = normalize_sede(sede_raw) if sede_raw else None
        tipo   = str(row.get("tipo_novedad", "") or "").strip()
        valor_raw = str(row.get("valor_novedad", "") or "").strip()
        obs    = str(row.get("observaciones", "") or "").strip() or None

        fecha_ini = parse_date_flexible(row.get("fecha_inicio"))
        fecha_fin_val = parse_date_flexible(row.get("fecha_fin"))

        unidad = get_tipo_unidad(tipo)
        # Área por hoja, con override por cédula para hojas ambiguas (ej. SI-NR)
        area_record = resolve_area(sheet_name, cedula) if cedula else area_canon
        record = {
            "cedula": cedula,
            "nombre_empleado": nombre,
            "area": area_record,          # departamento (nombre de hoja normalizado)
            "sede": sede_canon,           # ubicación física homologada
            "cargo": None,
            "tipo_novedad": tipo,
            "descripcion_novedad": obs or tipo,
            "fecha_inicio": fecha_ini,
            "fecha_fin": fecha_fin_val,
            "dias": _safe_float(valor_raw),
            "unidad": unidad,
            "valor": None,
            "estado": None,
            "observaciones": obs,
            "periodo": infer_periodo({"fecha_inicio": fecha_ini}, file_name),
            "columnas_extra": json.dumps(
                {"sede_raw": sede_raw, "valor_raw": valor_raw}, ensure_ascii=False
            ) if sede_raw else None,
            "archivo_origen": file_name,
            "hoja_origen": sheet_name,
            "fecha_modificacion_archivo": file_modified,
            "execution_id": execution_id,
        }

        es_valido, razon = validate_row(record)
        record["es_valido"] = 1 if es_valido else 0
        record["razon_invalido"] = razon if not es_valido else None

        if es_valido:
            valid_records.append(record)
        else:
            invalid_records.append(record)

    logger.info(
        "sheet_done",
        file=file_name, sheet=sheet_name,
        valid=len(valid_records), invalid=len(invalid_records),
    )
    return valid_records, invalid_records


# ─── Proceso ETL principal ────────────────────────────────────────────────────

def run_etl_process(
    db: Session,
    trigger_type: str = "scheduled",
    triggered_by: Optional[str] = None,
) -> ExecutionLog:
    """
    ETL completo:
      1. Conectar a la carpeta compartida.
      2. Listar recursivamente archivos Excel.
      3. Por cada archivo: detectar encabezado, hacer melt, insertar.
      4. Registrar métricas.
    """
    execution = ExecutionLog(
        trigger_type=trigger_type,
        triggered_by=triggered_by,
        status=ExecutionStatus.running,
    )
    db.add(execution)
    db.commit()
    db.refresh(execution)

    logger.info("etl_started", execution_id=execution.id, trigger=trigger_type)
    start_time = datetime.utcnow()

    total_inserted = total_invalid = total_processed = total_failed = 0

    try:
        share_path = get_network_path()
        excel_files = list_excel_files(share_path)
        execution.total_files_found = len(excel_files)
        db.commit()

        for file_path in excel_files:
            file_record = ProcessedFile(
                execution_id=execution.id,
                file_name=file_path.name,
                file_path=str(file_path),
                file_modified_at=_get_file_mtime(file_path),
            )
            try:
                file_record.file_size_kb = file_path.stat().st_size / 1024
            except Exception:
                pass

            logger.info("processing_file", file=file_path.name)

            try:
                # Eliminar registros previos de este archivo (deduplicación)
                deleted = (
                    db.query(NovedadNomina)
                    .filter(NovedadNomina.archivo_origen == file_path.name)
                    .delete(synchronize_session=False)
                )
                if deleted:
                    logger.info("dedup_deleted", file=file_path.name, count=deleted)
                db.commit()

                xl = pd.ExcelFile(str(file_path))
                sheets = xl.sheet_names
                file_record.sheets_found = len(sheets)

                file_inserted = file_invalid = sheets_ok = 0

                for sheet in sheets:
                    valid_recs, invalid_recs = _read_sheet(
                        xl, sheet, file_path.name,
                        file_record.file_modified_at, execution.id,
                    )
                    all_recs = valid_recs + invalid_recs
                    if all_recs:
                        db.bulk_insert_mappings(NovedadNomina, all_recs)
                        db.commit()
                        file_inserted += len(valid_recs)
                        file_invalid += len(invalid_recs)
                        sheets_ok += 1

                file_record.sheets_processed = sheets_ok
                file_record.records_inserted = file_inserted
                file_record.records_invalid = file_invalid
                file_record.status = "ok"

                total_inserted += file_inserted
                total_invalid += file_invalid
                total_processed += 1

            except Exception as e:
                logger.error("file_error", file=file_path.name, error=str(e))
                file_record.status = "error"
                file_record.error_detail = str(e)[:1000]
                total_failed += 1

            db.add(file_record)
            db.commit()

        execution.status = (
            ExecutionStatus.completed if total_failed == 0 else ExecutionStatus.partial
        )

        # Detección automática de retiros (post-ETL)
        try:
            from app.services.dashboard_service import detect_and_mark_retirements
            ret = detect_and_mark_retirements(db)
            logger.info(
                "retirement_detection_done",
                execution_id=execution.id,
                retiros_nuevos=ret["retiros_insertados"],
                periodos=ret["periodos_analizados"],
            )
        except Exception as ret_err:
            logger.warning("retirement_detection_error", error=str(ret_err))

    except Exception as e:
        logger.error("etl_critical_error", error=str(e), execution_id=execution.id)
        execution.status = ExecutionStatus.failed
        execution.error_summary = str(e)[:2000]

    finally:
        end_time = datetime.utcnow()
        execution.finished_at = end_time
        execution.duration_seconds = (end_time - start_time).total_seconds()
        execution.total_files_processed = total_processed
        execution.total_files_failed = total_failed
        execution.total_records_inserted = total_inserted
        execution.total_records_invalid = total_invalid
        db.commit()

    logger.info(
        "etl_finished",
        execution_id=execution.id,
        status=str(execution.status),
        duration=execution.duration_seconds,
        files_ok=total_processed,
        files_err=total_failed,
        records_valid=total_inserted,
        records_invalid=total_invalid,
    )
    return execution
