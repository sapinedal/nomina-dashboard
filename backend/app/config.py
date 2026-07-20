from pydantic_settings import BaseSettings
from typing import Optional
from functools import lru_cache


class Settings(BaseSettings):
    # Aplicación
    APP_NAME: str = "NóminaBoard"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    SECRET_KEY: str = "dev-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480

    # Contraseña del admin sembrado en el PRIMER arranque (BD sin usuario admin).
    # Solo se usa al crear el admin; nunca sobrescribe la contraseña de un admin
    # existente. Configurar en el .env de producción; el default es solo para
    # levantar un entorno nuevo rápido.
    SEED_ADMIN_PASSWORD: str = "Admin2024!"

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


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
