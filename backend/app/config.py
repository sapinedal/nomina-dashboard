from pydantic_settings import BaseSettings
from typing import Optional
from functools import lru_cache

# Valores de arranque rápido para entornos DEBUG=true (dev local, sin Docker).
# Nunca deben llegar a un despliegue con DEBUG=false — ver Settings.model_post_init.
_INSECURE_DEFAULT_SECRET_KEY = "dev-secret-key-change-in-production"
_INSECURE_DEFAULT_ADMIN_PASSWORD = "Admin2024!"
_MIN_SECRET_KEY_LENGTH = 32

# Valores "conocidos" que model_post_init debe rechazar además de los
# defaults de arriba: los placeholders de .env.example. Si alguien copia ese
# archivo a .env y olvida editarlo, el placeholder queda como env var real
# (ya no es el default de esta clase) y pasaría el chequeo si solo
# comparáramos contra _INSECURE_DEFAULT_*. Mantener sincronizado con
# .env.example.
_KNOWN_INSECURE_SECRET_KEYS = frozenset({
    _INSECURE_DEFAULT_SECRET_KEY,
    "cambia_este_valor_por_una_clave_secreta_muy_larga_y_aleatoria",
})
_KNOWN_INSECURE_ADMIN_PASSWORDS = frozenset({
    _INSECURE_DEFAULT_ADMIN_PASSWORD,
    "cambia_esta_contrasena_del_admin_semilla",
})


class Settings(BaseSettings):
    # Aplicación
    APP_NAME: str = "NóminaBoard"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    SECRET_KEY: str = _INSECURE_DEFAULT_SECRET_KEY
    ALGORITHM: str = "HS256"
    # Corto a propósito (SEC-2): si un access token se filtra, la ventana de
    # explotación es de minutos, no horas. El frontend renueva la sesión de
    # forma transparente vía REFRESH_TOKEN_EXPIRE_DAYS (ver /api/auth/refresh).
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Contraseña del admin sembrado en el PRIMER arranque (BD sin usuario admin).
    # Solo se usa al crear el admin; nunca sobrescribe la contraseña de un admin
    # existente. Configurar en el .env de producción; el default es solo para
    # levantar un entorno nuevo rápido.
    SEED_ADMIN_PASSWORD: str = _INSECURE_DEFAULT_ADMIN_PASSWORD

    # Base de datos
    DATABASE_URL: str = "postgresql://nomina_user:password@localhost:5432/nomina_dashboard"

    # Carpeta compartida de red
    NETWORK_SHARE_PATH: str = (
        r"\\192.168.0.13\fs_sumimedical\SUBGERENCIA ADMINISTRATIVA Y FINANCIERA"
        r"\DIRECCIÓN ADMINISTRATIVA\NOVEDADES NOMINA\CONSOLIDADO"
    )
    NETWORK_SHARE_USER: Optional[str] = None
    NETWORK_SHARE_PASSWORD: Optional[str] = None
    NETWORK_SHARE_DOMAIN: Optional[str] = None

    # Base de datos Trazalo (PostgreSQL, sistema de novedades en tiempo real de RRHH)
    TRAZALO_DB_HOST: Optional[str] = None
    TRAZALO_DB_PORT: int = 5432
    TRAZALO_DB_NAME: Optional[str] = None
    TRAZALO_DB_USER: Optional[str] = None
    TRAZALO_DB_PASSWORD: Optional[str] = None
    TRAZALO_SYNC_INTERVAL_MINUTES: int = 60

    # Programador automático
    SCHEDULER_DAY: int = 30
    SCHEDULER_HOUR: int = 23
    SCHEDULER_MINUTE: int = 0

    # CORS
    ALLOWED_ORIGINS: str = "http://localhost,http://localhost:80"

    # Logs
    LOG_LEVEL: str = "INFO"
    LOG_DIR: str = "/app/logs"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    model_config = {"env_file": ".env", "case_sensitive": True}

    @property
    def allowed_origins_list(self) -> list[str]:
        origins = [o.strip() for o in self.ALLOWED_ORIGINS.split(",")]
        # "*" en la lista activa acceso desde cualquier origen (red interna)
        if "*" in origins:
            return ["*"]
        return origins

    def model_post_init(self, __context) -> None:
        """Falla el arranque si DEBUG=false corre con valores inseguros.

        Sin esto, un despliegue que olvide configurar SECRET_KEY o
        SEED_ADMIN_PASSWORD sirve tráfico con credenciales conocidas
        públicamente (este archivo y .env.example) en lugar de fallar de
        forma ruidosa. DEBUG=true (dev local) mantiene el arranque rápido
        sin exigir estas variables.

        Acumula todos los problemas encontrados y los reporta juntos: así
        quien configure el despliegue los corrige de una sola vez en vez de
        descubrirlos uno por uno en sucesivos intentos de arranque fallidos.
        """
        if self.DEBUG:
            return

        errors: list[str] = []

        if not self.SECRET_KEY or self.SECRET_KEY in _KNOWN_INSECURE_SECRET_KEYS:
            errors.append(
                "SECRET_KEY no está configurado o usa un valor de ejemplo "
                "conocido (default de config.py o placeholder de "
                ".env.example). Generar con: "
                "python -c \"import secrets; print(secrets.token_urlsafe(32))\" "
                "y definirlo como variable de entorno SECRET_KEY."
            )
        elif len(self.SECRET_KEY) < _MIN_SECRET_KEY_LENGTH:
            errors.append(
                f"SECRET_KEY tiene {len(self.SECRET_KEY)} caracteres; se "
                f"requieren al menos {_MIN_SECRET_KEY_LENGTH} para resistir "
                "fuerza bruta sobre la firma HS256."
            )

        if not self.SEED_ADMIN_PASSWORD or self.SEED_ADMIN_PASSWORD in _KNOWN_INSECURE_ADMIN_PASSWORDS:
            errors.append(
                "SEED_ADMIN_PASSWORD no está configurado o usa un valor de "
                "ejemplo conocido (default de config.py o placeholder de "
                ".env.example). Definir una contraseña fuerte como variable "
                "de entorno SEED_ADMIN_PASSWORD antes de desplegar."
            )

        if errors:
            raise ValueError(
                f"Configuración insegura para producción (DEBUG=false) — "
                f"{len(errors)} problema(s):\n- " + "\n- ".join(errors)
            )


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
