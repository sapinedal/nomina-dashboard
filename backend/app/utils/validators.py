import re
import pandas as pd
from datetime import date
from typing import Optional


# Mapas de normalización de nombres de columna
COLUMN_ALIASES: dict[str, str] = {
    # Cédula / identificación
    "cedula": "cedula",
    "cédula": "cedula",
    "cc": "cedula",
    "identificacion": "cedula",
    "identificación": "cedula",
    "nro_documento": "cedula",
    "documento": "cedula",
    # Nombre
    "nombre": "nombre_empleado",
    "nombre_completo": "nombre_empleado",
    "nombres": "nombre_empleado",
    "empleado": "nombre_empleado",
    "funcionario": "nombre_empleado",
    "trabajador": "nombre_empleado",
    # Área
    "area": "area",
    "área": "area",
    "dependencia": "area",
    "departamento": "area",
    "proceso": "area",
    # Cargo
    "cargo": "cargo",
    "puesto": "cargo",
    "denominacion": "cargo",
    # Tipo de novedad
    "tipo_novedad": "tipo_novedad",
    "tipo": "tipo_novedad",
    "novedad": "tipo_novedad",
    "clase_novedad": "tipo_novedad",
    "concepto": "tipo_novedad",
    # Descripción
    "descripcion": "descripcion_novedad",
    "descripción": "descripcion_novedad",
    "detalle": "descripcion_novedad",
    # Fechas
    "fecha_inicio": "fecha_inicio",
    "fecha_desde": "fecha_inicio",
    "desde": "fecha_inicio",
    "inicio": "fecha_inicio",
    "fecha_fin": "fecha_fin",
    "fecha_hasta": "fecha_fin",
    "hasta": "fecha_fin",
    "fin": "fecha_fin",
    # Días
    "dias": "dias",
    "días": "dias",
    "num_dias": "dias",
    "numero_dias": "dias",
    "cantidad_dias": "dias",
    # Valor
    "valor": "valor",
    "monto": "valor",
    "importe": "valor",
    "valor_novedad": "valor",
    # Período
    "periodo": "periodo",
    "período": "periodo",
    "mes": "periodo",
    "año": "periodo",
    # Estado
    "estado": "estado",
    "estatus": "estado",
    "situacion": "estado",
    # Observaciones
    "observaciones": "observaciones",
    "observacion": "observaciones",
    "notas": "observaciones",
    "nota": "observaciones",
}


def normalize_column_name(col: str) -> str:
    """Normalizar nombre de columna: minúsculas, sin espacios, sin tildes."""
    col = str(col).lower().strip()
    col = col.replace(" ", "_")
    col = (
        col.replace("á", "a").replace("é", "e").replace("í", "i")
           .replace("ó", "o").replace("ú", "u").replace("ñ", "n")
    )
    col = re.sub(r"[^a-z0-9_]", "", col)
    return COLUMN_ALIASES.get(col, col)


def parse_date_flexible(value) -> Optional[date]:
    """Intentar parsear una fecha desde distintos formatos."""
    if pd.isna(value) or value is None or str(value).strip() == "":
        return None
    if isinstance(value, (date,)):
        return value
    if isinstance(value, pd.Timestamp):
        return value.date()
    try:
        return pd.to_datetime(str(value), dayfirst=True).date()
    except Exception:
        return None


def validate_cedula(value) -> bool:
    if not value or pd.isna(value):
        return False
    s = str(value).strip().replace(".", "").replace(",", "")
    return s.isdigit() and 5 <= len(s) <= 12


def validate_row(row: dict) -> tuple[bool, str]:
    """
    Retorna (es_valido, razon_invalido).
    Un registro es válido si tiene al menos cédula O nombre, y tiene tipo de novedad.
    """
    reasons = []
    has_cedula = row.get("cedula") and validate_cedula(row.get("cedula"))
    has_nombre = bool(row.get("nombre_empleado", "").strip() if row.get("nombre_empleado") else "")
    if not has_cedula and not has_nombre:
        reasons.append("sin identificación de empleado")
    if not row.get("tipo_novedad"):
        reasons.append("tipo de novedad ausente")
    return (len(reasons) == 0, "; ".join(reasons))


def clean_valor(value) -> Optional[float]:
    if pd.isna(value) or value is None:
        return None
    try:
        s = str(value).replace("$", "").replace(".", "").replace(",", ".")
        s = re.sub(r"\s+", "", s)
        return float(s)
    except (ValueError, TypeError):
        return None


def infer_periodo(row: dict, file_name: str) -> Optional[str]:
    """Inferir período YYYY-MM desde fechas del registro o nombre del archivo."""
    fi = row.get("fecha_inicio")
    if fi and isinstance(fi, date):
        return fi.strftime("%Y-%m")
    # Intentar extraer del nombre de archivo: AAAA-MM o AAAAMM
    m = re.search(r"(20\d{2})[-_]?(\d{2})", file_name)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    return None
