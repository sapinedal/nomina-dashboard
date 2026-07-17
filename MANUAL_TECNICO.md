# NóminaBoard — Manual Técnico

## 1. Arquitectura de la solución

```
┌─────────────────────────────────────────────────────────────────┐
│                        CAPA PRESENTACIÓN                        │
│  HTML5 + CSS3 + JavaScript + Bootstrap 5 + Chart.js            │
│  login.html | dashboard.html | history.html | admin.html        │
└───────────────────────────┬─────────────────────────────────────┘
                            │ REST / JSON
┌───────────────────────────▼─────────────────────────────────────┐
│                      CAPA LÓGICA DE NEGOCIO                     │
│              FastAPI (Python 3.12) + APScheduler                │
│                                                                 │
│  /api/auth     Autenticación JWT                                │
│  /api/dashboard KPIs + Gráficas + Tabla paginada               │
│  /api/execution Historial ETL + Trigger manual                  │
│  /api/users    CRUD usuarios (solo Admin)                       │
│  /api/export   Exportación Excel (XlsxWriter) + PDF (ReportLab) │
│                                                                 │
│  Scheduler: día 30 cada mes 23:00 → ETL automático             │
└───────────────────────────┬─────────────────────────────────────┘
                            │ SQLAlchemy ORM
┌───────────────────────────▼─────────────────────────────────────┐
│                          CAPA DE DATOS                          │
│                    PostgreSQL 15                                 │
│                                                                 │
│  users | execution_logs | processed_files | novedades_nomina    │
└─────────────────────────────────────────────────────────────────┘
                            ▲
                    pandas + openpyxl
                            │
              \\192.168.0.13\fs_sumimedical\...
              Archivos: .xlsx  .xls  .xlsm
```

---

## 2. Modelo Entidad-Relación

```
users
├── id (PK)
├── username (UNIQUE)
├── email (UNIQUE)
├── full_name
├── hashed_password
├── role: ENUM(admin, analyst, readonly)
├── is_active
├── created_at
└── last_login

execution_logs
├── id (PK)
├── started_at / finished_at
├── duration_seconds
├── status: ENUM(running, completed, failed, partial)
├── trigger_type: scheduled | manual
├── triggered_by
├── total_files_found / processed / failed
├── total_records_inserted / updated / invalid
└── error_summary

processed_files
├── id (PK)
├── execution_id (FK → execution_logs)
├── file_name / file_path
├── file_size_kb / file_modified_at
├── sheets_found / sheets_processed
├── records_inserted / records_invalid
├── status: ok | error | skipped
└── error_detail

novedades_nomina
├── id (PK)
├── archivo_origen / hoja_origen         ← trazabilidad
├── fecha_procesamiento / execution_id   ← trazabilidad
├── cedula / nombre_empleado / area / cargo
├── tipo_novedad / descripcion_novedad
├── fecha_inicio / fecha_fin / dias / valor
├── periodo (YYYY-MM) / estado
├── columnas_extra (JSON)                ← campos no estándar
├── es_valido / razon_invalido           ← calidad
└── created_at
```

---

## 3. Flujo del proceso ETL

```
1. APScheduler dispara _etl_job() (día 30, 23:00)
   └─ O se dispara manualmente desde /api/execution/trigger

2. Crear registro ExecutionLog (status=running)

3. get_network_path()
   ├─ Windows: UNC directo (\\servidor\...)
   └─ Linux/Docker: monta via CIFS o usa /mnt/nomina_share

4. list_excel_files(path)
   ├─ Filtra por extensión: .xlsx, .xls, .xlsm
   └─ Ignora archivos temporales (~$...)

5. Para cada archivo:
   ├─ Crear registro ProcessedFile
   ├─ pd.ExcelFile(path) → leer nombre de hojas
   └─ Para cada hoja:
       ├─ df = xl.parse(sheet_name, dtype=str)
       ├─ Normalizar columnas (COLUMN_ALIASES)
       ├─ Para cada fila:
       │   ├─ Parsear fechas (parse_date_flexible)
       │   ├─ Limpiar valor monetario (clean_valor)
       │   ├─ Inferir período (infer_periodo)
       │   ├─ Capturar columnas extra → JSON
       │   ├─ validate_row() → es_valido + razon
       │   └─ Acumular en lista
       └─ bulk_insert_mappings(NovedadNomina, records)

6. Actualizar ExecutionLog (status, métricas, duración)

7. Frontend recibe actualización en próxima petición
```

---

## 4. Normalización de columnas Excel

El archivo `utils/validators.py` contiene `COLUMN_ALIASES`, un diccionario
que mapea variantes de nombres de columna al nombre estándar:

```python
"cédula" → "cedula"
"área"   → "area"
"monto"  → "valor"
...
```

Para agregar nuevas variantes, editar el diccionario `COLUMN_ALIASES` en
`backend/app/utils/validators.py`. No se requiere reiniciar si se usa
`--reload` en desarrollo.

---

## 5. Control de acceso (RBAC)

| Funcionalidad | Admin | Analista | Consulta |
|---|:---:|:---:|:---:|
| Ver tableros y KPIs | ✅ | ✅ | ✅ |
| Ver historial de ejecuciones | ✅ | ✅ | ✅ |
| Exportar Excel / PDF | ✅ | ✅ | ❌ |
| Gestionar usuarios | ✅ | ❌ | ❌ |
| Disparar ETL manualmente | ✅ | ❌ | ❌ |

Implementado en `services/auth_service.py` con decoradores `require_role()`.

---

## 6. Estructura de archivos del proyecto

```
nomina-dashboard/
├── backend/
│   ├── app/
│   │   ├── main.py              ← Entrypoint FastAPI + lifespan
│   │   ├── config.py            ← Settings (pydantic-settings)
│   │   ├── database.py          ← Engine SQLAlchemy + get_db()
│   │   ├── models/
│   │   │   ├── user.py          ← ORM: users
│   │   │   ├── execution.py     ← ORM: execution_logs, processed_files
│   │   │   └── nomina.py        ← ORM: novedades_nomina
│   │   ├── schemas/
│   │   │   ├── user.py          ← Pydantic I/O
│   │   │   ├── execution.py
│   │   │   └── dashboard.py
│   │   ├── routers/
│   │   │   ├── auth.py          ← POST /api/auth/token
│   │   │   ├── dashboard.py     ← GET  /api/dashboard/*
│   │   │   ├── execution.py     ← GET/POST /api/execution/*
│   │   │   ├── users.py         ← CRUD /api/users/
│   │   │   └── export.py        ← GET /api/export/excel|pdf
│   │   ├── services/
│   │   │   ├── excel_processor.py ← ETL principal
│   │   │   ├── scheduler.py       ← APScheduler
│   │   │   ├── auth_service.py    ← JWT + bcrypt
│   │   │   └── dashboard_service.py ← Consultas para tableros
│   │   └── utils/
│   │       ├── logger.py          ← structlog
│   │       └── validators.py      ← Normalización + validación
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── login.html
│   ├── dashboard.html
│   ├── history.html
│   ├── admin.html
│   ├── css/main.css
│   └── js/
│       ├── api.js       ← Cliente HTTP + utilidades globales
│       ├── charts.js    ← Wrappers Chart.js
│       └── dashboard.js ← Lógica del tablero principal
├── sql/
│   ├── 01_create_schema.sql
│   ├── 02_create_tables.sql
│   ├── 03_create_indexes.sql
│   └── 04_insert_initial_data.sql
├── nginx/nginx.conf
├── docker-compose.yml
├── .env.example
├── INSTALACION.md
└── MANUAL_TECNICO.md
```

---

## 7. API REST — Referencia rápida

| Método | Endpoint | Descripción | Rol mínimo |
|---|---|---|---|
| POST | `/api/auth/token` | Login → JWT | Público |
| GET | `/api/auth/me` | Perfil usuario actual | Cualquiera |
| GET | `/api/dashboard/kpis` | KPIs con filtros | Cualquiera |
| GET | `/api/dashboard/charts/novedades-por-tipo` | Gráfica por tipo | Cualquiera |
| GET | `/api/dashboard/charts/novedades-por-area` | Gráfica por área | Cualquiera |
| GET | `/api/dashboard/charts/tendencia-mensual` | Tendencia mensual | Cualquiera |
| GET | `/api/dashboard/charts/valor-por-area` | Valor $ por área | Cualquiera |
| GET | `/api/dashboard/table` | Tabla paginada | Cualquiera |
| GET | `/api/dashboard/filter-options` | Valores para filtros | Cualquiera |
| GET | `/api/execution/history` | Historial ETL | Cualquiera |
| GET | `/api/execution/{id}` | Detalle ejecución | Cualquiera |
| POST | `/api/execution/trigger` | Disparar ETL manual | Admin |
| GET | `/api/users/` | Listar usuarios | Admin |
| POST | `/api/users/` | Crear usuario | Admin |
| PUT | `/api/users/{id}` | Editar usuario | Admin |
| DELETE | `/api/users/{id}` | Eliminar usuario | Admin |
| GET | `/api/export/excel` | Exportar Excel | Admin/Analista |
| GET | `/api/export/pdf` | Exportar PDF | Admin/Analista |

Documentación interactiva completa: **http://localhost:8000/api/docs**

---

## 8. Variables de entorno

| Variable | Descripción | Ejemplo |
|---|---|---|
| `SECRET_KEY` | Clave secreta JWT (≥32 chars) | `abc123...` |
| `DATABASE_URL` | Conexión PostgreSQL completa | `postgresql://user:pw@db:5432/db` |
| `NETWORK_SHARE_PATH` | Ruta UNC a la carpeta Excel | `\\\\srv\\share\\...` |
| `NETWORK_SHARE_USER` | Usuario de red | `SUMIMEDICAL\usuario` |
| `NETWORK_SHARE_PASSWORD` | Contraseña de red | `pw` |
| `SCHEDULER_DAY` | Día del mes para ETL | `30` |
| `SCHEDULER_HOUR` | Hora para ETL | `23` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Duración del token | `480` |
| `LOG_LEVEL` | Nivel de log: DEBUG/INFO/WARNING | `INFO` |

---

## 9. Escalabilidad

- **Múltiples workers**: cambiar en `Dockerfile` el comando a `uvicorn ... --workers 4`
- **Base de datos**: pool configurado con `pool_size=10, max_overflow=20`
- **Redis**: incluido para eventual implementación de Celery como cola de tareas
- **Índices**: optimizados para filtros por área, tipo, período y cédula
- **Paginación**: la tabla usa cursor offset con límite configurable (10–500 filas)
