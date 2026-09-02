"""
NóminaBoard - API Principal
FastAPI + PostgreSQL + APScheduler
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
import os

from app.config import settings
from app.database import create_tables
from app.utils.logger import setup_logging, get_logger
from app.services.scheduler import start_scheduler, stop_scheduler
from app.services.auth_service import hash_password
from app.middleware.rate_limit import limiter, rate_limit_exceeded_handler
from app.routers import auth, dashboard, execution, users, export

logger = get_logger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """DEF-0004: cabeceras de endurecimiento (también sin nginx delante)."""

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
        )
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "font-src 'self' https://cdn.jsdelivr.net data:; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'",
        )
        if settings.COOKIE_SECURE:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response


def _docs_url():
    # DEF-0002: solo con flag explícito.
    if settings.EXPOSE_OPENAPI:
        return "/api/docs"
    return None


def _redoc_url():
    if settings.EXPOSE_OPENAPI:
        return "/api/redoc"
    return None


def _openapi_url():
    if settings.EXPOSE_OPENAPI:
        return "/api/openapi.json"
    return None


def seed_admin_user():
    """Crear el usuario administrador SOLO si aún no existe.

    Antes, cuando el admin ya existía, se re-escribía su contraseña a un valor
    fijo y se forzaba is_active=True en CADA arranque. Eso revertía silenciosamente
    cualquier cambio de contraseña del admin (y reactivaba cuentas desactivadas) al
    reiniciar el servidor. Ahora, si el admin existe, NO se toca: su contraseña y su
    estado los gestiona el propio administrador. La contraseña inicial (solo para el
    primer arranque en una BD nueva) sale de settings.SEED_ADMIN_PASSWORD.
    """
    from app.database import SessionLocal
    from app.models.user import User, UserRole

    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.username == "admin").first()
        if admin:
            return  # ya existe: no sobrescribir contraseña ni estado
        admin = User(
            username="admin",
            email="admin@sumimedical.com",
            full_name="Administrador del Sistema",
            role=UserRole.admin,
            is_active=True,
            hashed_password=hash_password(settings.SEED_ADMIN_PASSWORD),
        )
        db.add(admin)
        db.commit()
        logger.info("default_admin_created", username="admin")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    setup_logging()
    logger.info("app_starting", name=settings.APP_NAME, version=settings.APP_VERSION)
    create_tables()
    seed_admin_user()
    # Empresas mezcladas en novedades_nomina (AGUAS DEL PUERTO, etc.) siguen
    # saliendo en Empleados del Período aunque el sync ya no las inserte.
    # Purgarlas al arrancar: el redeploy limpia la BD sin pulsar el botón.
    try:
        from app.services.trazalo_sync import purgar_razones_sociales
        purgar_razones_sociales()
    except Exception as e:
        logger.error("purge_razones_sociales_failed", error=str(e))
    start_scheduler()
    yield
    # Shutdown
    stop_scheduler()
    logger.info("app_stopped")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="""
## NóminaBoard

Sistema de tableros estadísticos para Novedades de Nómina.

### Características
- Procesamiento automático de archivos Excel desde carpeta compartida de red
- Tableros interactivos con KPIs, gráficas y tablas dinámicas
- Control de acceso por roles: Administrador, Analista, Consulta
- Exportación a Excel y PDF
- Historial completo de ejecuciones
    """,
    docs_url=_docs_url(),
    redoc_url=_redoc_url(),
    openapi_url=_openapi_url(),
    lifespan=lifespan,
)

# Rate limiting (SEC-4): el objeto limiter debe vivir en app.state para que
# los decoradores @limiter.limit(...) de los routers lo encuentren.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

# CORS. En el despliegue normal el frontend se sirve desde el mismo origen (el
# nginx del compose enruta /api/ al backend), así que ni siquiera hay preflight;
# esta configuración cubre el caso de servir el frontend aparte.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Sin esto, `downloadFile` no puede leer el nombre del archivo en un
    # despliegue cross-origin: el navegador oculta todas las cabeceras de
    # respuesta que no estén en la lista blanca por defecto.
    expose_headers=["Content-Disposition"],
)
app.add_middleware(SecurityHeadersMiddleware)

# Routers
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(execution.router)
app.include_router(users.router)
app.include_router(export.router)


@app.get("/health", tags=["Sistema"])
async def health_check():
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
    }


@app.get("/api", tags=["Sistema"])
async def api_info():
    info = {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
    }
    if settings.EXPOSE_OPENAPI:
        info["docs"] = "/api/docs"
    return info


# Servir el frontend desde /frontend al final para no bloquear las rutas API
_frontend_path = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
_frontend_path = os.path.normpath(_frontend_path)
if os.path.isdir(_frontend_path):
    from fastapi.responses import RedirectResponse

    @app.get("/", include_in_schema=False)
    async def root():
        return RedirectResponse(url="/login.html")

    app.mount("/", StaticFiles(directory=_frontend_path, html=True), name="frontend")
