from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.config import settings

_is_sqlite = settings.DATABASE_URL.startswith("sqlite")

_connect_args = {"check_same_thread": False} if _is_sqlite else {}
_engine_kwargs = (
    {"connect_args": _connect_args}
    if _is_sqlite
    else {"pool_pre_ping": True, "pool_size": 10, "max_overflow": 20}
)

engine = create_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    **_engine_kwargs,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """Dependencia FastAPI para inyección de sesión de base de datos."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables():
    """Crear todas las tablas definidas en los modelos."""
    Base.metadata.create_all(bind=engine)
    _migrate_columns()


def _migrate_columns():
    """Añadir columnas nuevas a tablas existentes sin borrar datos (SQLite safe)."""
    from sqlalchemy import text
    migrations = [
        "ALTER TABLE novedades_nomina ADD COLUMN sede VARCHAR(200)",
        "ALTER TABLE novedades_nomina ADD COLUMN unidad VARCHAR(10)",
    ]
    with engine.connect() as conn:
        for sql in migrations:
            try:
                conn.execute(text(sql))
                conn.commit()
            except Exception:
                pass  # columna ya existe
