"""
Homologacion (normalizacion) de sedes y areas a nombres canonicos.

Extraido VERBATIM desde app.services.excel_processor (sin cambios de logica)
para que sea codigo de dominio compartido, reutilizable por excel_processor y
trazalo_sync. Solo depende de re. Comportamiento congelado por
tests/test_normalizers_characterization.py.
"""
import re


def _strip_accents(s: str) -> str:
    return (s.replace("á","a").replace("é","e").replace("í","i")
             .replace("ó","o").replace("ú","u").replace("ñ","n")
             .replace("Á","A").replace("É","E").replace("Í","I")
             .replace("Ó","O").replace("Ú","U").replace("Ñ","N"))


def _pre_clean(raw: str) -> tuple[str, str]:
    """
    Limpieza universal antes de la normalización:
    - Elimina puntos, comas y espacios al final (ARCHIVO. → ARCHIVO)
    - Colapsa espacios internos múltiples
    Retorna (cadena_limpia, cadena_para_matching_en_minusculas_sin_tildes)
    """
    s = raw.strip()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[.,;\s]+$", "", s).strip()   # quitar puntuación y espacios al final
    norm = _strip_accents(s.lower())
    norm = re.sub(r"\s+", " ", norm)
    return s, norm


# ── SEDES ─────────────────────────────────────────────────────────────────────
# Pares (patrón_regex, nombre_canónico). Patrón sobre minúsculas sin tildes.
# Orden: más específico primero.
_SEDE_CANON: list[tuple[str, str]] = [
    # ── Clínica / Victoriana → CLINICA ───────────────────────────────────────
    (r"clinic|victorian",                           "CLINICA"),
    # ── Torre Villanueva (Torre Especialistas, Villanueva) ───────────────────
    (r"\btorre\b|villanueva",                       "TORRE VILLANUEVA"),
    # ── Sede Estadio (Estadio) ────────────────────────────────────────────────
    (r"^estadio$|sede.{0,3}estadio",               "SEDE ESTADIO"),
    # ── Sede Oriental (Oriental) ──────────────────────────────────────────────
    (r"\boriental\b",                               "SEDE ORIENTAL"),
    # ── Sede Administrativa (Sede 80) ─────────────────────────────────────────
    (r"sede.{0,5}80|\b80\b|sede.{0,5}adm|administrativa", "SEDE ADMINISTRATIVA"),
    (r"\bcontac|\bcall.{0,3}cent",                  "ITAGÜÍ"),
    (r"apoyo.{0,5}terapeu",                         "APOYO TERAPÉUTICO"),
    (r"istmina|itsmina",                            "ISTMINA"),
    (r"necocl",                                     "NECOCLÍ"),
    (r"\bbello\b",                                  "BELLO"),
    (r"itag[ui]",                                   "ITAGÜÍ"),
    (r"rionegro",                                   "RIONEGRO"),
    (r"laureles",                                   "LAURELES"),
    (r"el.{0,3}poblado|\bpoblado\b",               "EL POBLADO"),
    (r"envigado",                                   "ENVIGADO"),
    (r"sabaneta",                                   "SABANETA"),
    (r"copacabana",                                 "COPACABANA"),
    (r"girardota",                                  "GIRARDOTA"),
    (r"\bcaldas\b",                                 "CALDAS"),
    (r"la.{0,3}estrella",                           "LA ESTRELLA"),
    (r"\bbarbosa\b",                                "BARBOSA"),
    (r"puerto.{0,3}berr",                           "PUERTO BERRÍO"),
    (r"caucasia",                                   "CAUCASIA"),
    (r"apartad",                                    "APARTADÓ"),
    (r"\bturbo\b",                                  "TURBO"),
    (r"quibd",                                      "QUIBDÓ"),
    (r"bogot",                                      "BOGOTÁ"),
    (r"medellin|medell",                            "MEDELLÍN"),
    (r"supernumerar",                               "SUPERNUMERARIO"),
]

# Valores que NO son sedes reales (nombres de personas, roles, basura).
# Se normalizan (minúsculas, sin tildes) y se descartan (sede = vacío/NULL).
_SEDE_BLOCKLIST: set[str] = {
    "aprendiz compras",
    "carlos andres amaya",
    "colaborador",
    "maria camila escalante",
    "santiago lopez",
    "sumimedical",
}

# ── ÁREAS / DEPARTAMENTOS ─────────────────────────────────────────────────────
# Estrategia: primero los más específicos (más palabras clave), luego los generales.
_AREA_CANON: list[tuple[str, str]] = [
    # ── Contact Center (muchas variantes: CONTAC CENCTER, CONTAC CENTER, etc.) ──
    (r"\bcontac|\bcall.{0,5}cent",                  "CONTACT CENTER"),

    # ── Archivo (unifica ARCHIVO Y CORRESPONDENCIA y ARCHIVO) ───────────────────
    (r"archivo",                                    "ARCHIVO"),

    # ── Base de Datos (unifica ARQUITECTURA DE DATOS, ARQUITECTURA, BASE DE DATOS) ─
    (r"arquitec|base.{0,8}dato",                    "BASE DE DATOS"),

    # ── Coordinadores ───────────────────────────────────────────────────────────
    (r"coordinador",                                "COORDINADORES Y OTROS"),

    # ── Logística + Servicios Generales (área unificada) ────────────────────────
    (r"log[ií]s|logi.{0,4}tic",                   "SERVICIOS GENERALES y LOGÍSTICA"),

    # ── Gestión Humana / Recursos Humanos (GESTION HUM., RECURSOS HUM., RRHH) ──
    (r"gestion.{0,8}huma|recursos.{0,8}huma|rrhh|r\.h\.", "RECURSOS HUMANOS"),

    # ── Administrativo ──────────────────────────────────────────────────────────
    (r"administrativ",                              "ADMINISTRATIVO"),

    # ── Financiero ──────────────────────────────────────────────────────────────
    (r"financier",                                  "FINANCIERO"),

    # ── Contabilidad ────────────────────────────────────────────────────────────
    (r"contabilid|contab",                          "CONTABILIDAD"),

    # ── Tesorería ───────────────────────────────────────────────────────────────
    (r"tesorer",                                    "TESORERÍA"),

    # ── Cartera ─────────────────────────────────────────────────────────────────
    (r"\bcartera\b",                                "CARTERA"),

    # ── Facturación ─────────────────────────────────────────────────────────────
    (r"facturaci|factura",                          "FACTURACIÓN"),

    # ── Nómina ──────────────────────────────────────────────────────────────────
    (r"\bnomina\b",                                 "NÓMINA"),

    # ── Compras ─────────────────────────────────────────────────────────────────
    (r"compras|adquisic",                           "COMPRAS Y ADQUISICIONES"),

    # ── Comercial / Ventas ───────────────────────────────────────────────────────
    (r"comercial|ventas",                           "COMERCIAL"),

    # ── Jurídica / Legal ────────────────────────────────────────────────────────
    (r"juridic|legal|asesor.{0,8}juri",            "ASESORÍA JURÍDICA"),

    # ── Soporte (hoja "SISTEMAS" sola o "SOPORTE" = soporte técnico) ────────────
    (r"^soporte$|^sistemas$",                        "SOPORTE"),

    # ── Sistemas de Información (antes que la regla general de sistem) ──────────
    (r"sistem.{0,5}de.{0,5}infor|sist.{0,5}infor",  "SIST INFORMACION"),

    # ── Sistemas / Tecnología → unificado como SOPORTE ─────────────────────────
    (r"sistem.{1,20}tecnolog|tecnolog.{1,20}sistem|^tecnolog", "SOPORTE"),

    # ── Operaciones ─────────────────────────────────────────────────────────────
    (r"operacion",                                  "OPERACIONES"),

    # ── Servicios Generales (área unificada con Logística) ──────────────────────
    (r"servicios.{0,8}general|serv.{0,5}gen",      "SERVICIOS GENERALES y LOGÍSTICA"),

    # ── Gestión Documental ──────────────────────────────────────────────────────
    (r"gestion.{0,8}documental|doc.{0,8}gestion",  "GESTIÓN DOCUMENTAL"),

    # ── Comunicaciones ──────────────────────────────────────────────────────────
    (r"comunicac",                                  "COMUNICACIONES"),

    # ── Planeación / Planeamiento ────────────────────────────────────────────────
    (r"planeac|planeamient",                        "PLANEACIÓN"),

    # ── Presupuesto ─────────────────────────────────────────────────────────────
    (r"presupuest",                                 "PRESUPUESTO"),

    # ── Mercadeo / Marketing ─────────────────────────────────────────────────────
    (r"mercadeo|marketing",                         "MERCADEO"),

    # ── Calidad ─────────────────────────────────────────────────────────────────
    (r"calidad",                                    "CALIDAD"),

    # ── Gerencia / Dirección ─────────────────────────────────────────────────────
    (r"gerencia|direcci[oó]n",                     "GERENCIA"),

    # ── Infraestructura (unifica INFRAESTRUCTURA e INFRAESTRUCTURA FISICA) ──────
    (r"infraestruc",                                "INFRAESTRUCTURA FISICA"),

    # ── Mantenimiento ────────────────────────────────────────────────────────────
    (r"mantenimiento",                              "MANTENIMIENTO"),

    # ── Seguridad ────────────────────────────────────────────────────────────────
    (r"seguridad",                                  "SEGURIDAD"),

    # ── Desarrollo ───────────────────────────────────────────────────────────────
    (r"desarrollo",                                 "DESARROLLO"),

    # ── Clínica / Asistencial ────────────────────────────────────────────────────
    (r"enfermer",                                   "ENFERMERÍA"),
    (r"farmac",                                     "FARMACIA"),
    (r"radiol",                                     "RADIOLOGÍA"),
    (r"laborat",                                    "LABORATORIO"),
    (r"urgencia",                                   "URGENCIAS"),
    (r"hospitaliz",                                 "HOSPITALIZACIÓN"),
    (r"cirug",                                      "CIRUGÍA"),
    (r"maternidad|ginecolog",                       "MATERNIDAD Y GINECOLOGÍA"),
    (r"pediatr",                                    "PEDIATRÍA"),
    (r"odontolog",                                  "ODONTOLOGÍA"),
    (r"\bmedic",                                    "MÉDICOS"),
]


def normalize_sede(raw: str) -> str:
    """Homologa el nombre de una sede física a un nombre canónico.
    Descarta valores de la lista negra (nombres de personas/roles, no sedes)."""
    if not raw or not raw.strip():
        return ""
    s, norm = _pre_clean(raw)
    if norm in _SEDE_BLOCKLIST:
        return ""   # no es una sede real
    for pattern, canon in _SEDE_CANON:
        if re.search(pattern, norm):
            return canon
    return s.upper()


def normalize_area(raw: str) -> str:
    """
    Homologa el nombre de un área/departamento (nombre de hoja Excel).
    Pasos:
      1. Elimina puntos/espacios al final  (ARCHIVO. → ARCHIVO)
      2. Aplica mapa de patrones canónicos
      3. Si no hay coincidencia, devuelve la cadena limpia en mayúsculas
    """
    if not raw or not raw.strip():
        return ""
    s, norm = _pre_clean(raw)
    for pattern, canon in _AREA_CANON:
        if re.search(pattern, norm):
            return canon
    # Sin coincidencia: devolver limpio, sin guiones/underscores y en mayúsculas
    clean = re.sub(r"[_\-]+", " ", s)
    return re.sub(r"\s+", " ", clean).upper()
