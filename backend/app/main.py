"""
NóminaBoard - API Principal
FastAPI + PostgreSQL + APScheduler
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os

from app.config import settings
from app.database import create_tables
from app.utils.logger import setup_logging, get_logger
from app.services.scheduler import start_scheduler, stop_scheduler
from app.services.auth_service import hash_password
from app.routers import auth, dashboard, execution, users, export

logger = get_logger(__name__)


def seed_admin_user():
    """Crear usuario administrador por defecto si no existe."""
    from app.database import SessionLocal
    from app.models.user import User, UserRole

    db = SessionLocal()
    try:
        if not db.query(User).filter(User.username == "admin").first():
            admin = User(
                username="admin",
                email="admin@sumimedical.com",
                full_name="Administrador del Sistema",
                role=UserRole.admin,
                is_active=True,
                hashed_password=hash_password("Admin2024!"),
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
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/api/docs",
    }


# Servir el frontend desde /frontend al final para no bloquear las rutas API
_frontend_path = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
_frontend_path = os.path.normpath(_frontend_path)
if os.path.isdir(_frontend_path):
    from fastapi.responses import RedirectResponse

    @app.get("/", include_in_schema=False)
    async def root():
        return RedirectResponse(url="/login.html")

    app.mount("/", StaticFiles(directory=_frontend_path, html=True), name="frontend")
