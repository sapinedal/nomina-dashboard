"""Permisos por perfil (rol). No son flags por usuario: el admin asigna el rol
y el rol trae el conjunto de acciones. Consulta (readonly) no exporta ni ve
la lista nominativa de empleados del período.
"""

PERM_EMPLEADOS_PERIODO = "empleados_periodo"
PERM_EXPORT_EXCEL = "export_excel"
PERM_EXPORT_PDF = "export_pdf"
PERM_USUARIOS = "usuarios"
PERM_ETL = "etl"

PERMISSION_LABELS = {
    PERM_EMPLEADOS_PERIODO: "Ver empleados por período",
    PERM_EXPORT_EXCEL: "Exportar a Excel",
    PERM_EXPORT_PDF: "Exportar a PDF",
    PERM_USUARIOS: "Administrar usuarios",
    PERM_ETL: "Ejecutar carga ETL / Trazalo",
}

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "admin": frozenset({
        PERM_EMPLEADOS_PERIODO,
        PERM_EXPORT_EXCEL,
        PERM_EXPORT_PDF,
        PERM_USUARIOS,
        PERM_ETL,
    }),
    "analyst": frozenset({
        PERM_EMPLEADOS_PERIODO,
        PERM_EXPORT_EXCEL,
        PERM_EXPORT_PDF,
    }),
    "readonly": frozenset(),
}


def _role_str(role) -> str:
    return role.value if hasattr(role, "value") else str(role or "")


def permissions_for_role(role) -> list[str]:
    return sorted(ROLE_PERMISSIONS.get(_role_str(role), frozenset()))


def role_has_permission(role, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(_role_str(role), frozenset())


def catalog_for_role(role) -> list[dict]:
    """Etiquetas para el modal de usuarios (perfil elegido)."""
    granted = ROLE_PERMISSIONS.get(_role_str(role), frozenset())
    return [
        {"code": code, "label": label, "granted": code in granted}
        for code, label in PERMISSION_LABELS.items()
        if code in ROLE_PERMISSIONS.get("admin", frozenset())
    ]
