"""Detecta razones sociales mezcladas en el roster de Trazalo.

Trazalo guarda empleados y terceros (proveedores, ESP, SAS) en la misma
tabla `users`. No hay tipo_tercero/NIT vs CC que consultar; la señal fiable
es el sufijo societario. Límites de palabra para no marcar a ROSA/SARA.
"""
import re
import unicodedata

_RAZON_SOCIAL_RE = re.compile(
    r"(?:^|[\s,;./])(?:"
    r"S\.?\s*A\.?\s*S\.?"
    r"|E\.?\s*S\.?\s*P\.?"
    r"|S\.?\s*A\.?"
    r"|LTDA\.?"
    r"|LIMITADA"
    r"|C[IÍ]A\.?"
    r")(?=$|[\s,;./])",
    re.IGNORECASE,
)

# LIKE portable (SQLite y PostgreSQL). El espacio antes del sufijo evita
# marcar ROSA / SARA / ESPERANZA: '%SA' pegaría, '% SA' no.
_SQL_LIKE_PATTERNS = (
    "% E.S.P%",
    "% E.S.P",
    "% S.A.S%",
    "% S.A.S",
    "% S.A.%",
    "% SAS %",
    "% SAS",
    "% SA %",
    "% SA",
    "% LTDA%",
    "% LIMITADA%",
    "% CIA",
    "% CIA %",
    "% CÍA%",
)


def _normalizar_nombre(nombre) -> str:
    s = unicodedata.normalize("NFKC", str(nombre))
    s = s.replace("\u00a0", " ").replace("\u202f", " ")
    return " ".join(s.upper().split())


def es_razon_social(nombre) -> bool:
    """True si el nombre es una persona jurídica, no un empleado."""
    if not nombre or not str(nombre).strip():
        return False
    return bool(_RAZON_SOCIAL_RE.search(_normalizar_nombre(nombre)))


def sql_es_razon_social(nombre_expr: str) -> str:
    """Predicado SQL (LIKE) verdadero si el nombre es razón social."""
    likes = " OR ".join(
        f"UPPER({nombre_expr}) LIKE '{pat}'" for pat in _SQL_LIKE_PATTERNS
    )
    return f"({likes})"


def sql_not_razon_social(nombre_expr: str) -> str:
    """AND ... nombre NULL o persona natural. Portable SQLite/PostgreSQL."""
    return (
        f"AND ({nombre_expr} IS NULL OR NOT {sql_es_razon_social(nombre_expr)})"
    )
