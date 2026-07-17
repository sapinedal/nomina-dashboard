-- ============================================================
-- NóminaBoard - Creación de tablas
-- ============================================================

-- ── Usuarios ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id               SERIAL PRIMARY KEY,
    username         VARCHAR(50)  NOT NULL UNIQUE,
    email            VARCHAR(120) NOT NULL UNIQUE,
    full_name        VARCHAR(150) NOT NULL,
    hashed_password  VARCHAR(255) NOT NULL,
    role             user_role    NOT NULL DEFAULT 'readonly',
    is_active        BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ,
    last_login       TIMESTAMPTZ
);

COMMENT ON TABLE users IS 'Usuarios del sistema con control de acceso por rol';
COMMENT ON COLUMN users.role IS 'admin: acceso total | analyst: consulta + exportación | readonly: solo visualización';

-- ── Historial de ejecuciones ──────────────────────────────
CREATE TABLE IF NOT EXISTS execution_logs (
    id                      SERIAL PRIMARY KEY,
    started_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    finished_at             TIMESTAMPTZ,
    duration_seconds        FLOAT,
    status                  execution_status NOT NULL DEFAULT 'running',
    trigger_type            VARCHAR(20)  NOT NULL DEFAULT 'scheduled',  -- scheduled | manual
    triggered_by            VARCHAR(50),
    total_files_found       INT NOT NULL DEFAULT 0,
    total_files_processed   INT NOT NULL DEFAULT 0,
    total_files_failed      INT NOT NULL DEFAULT 0,
    total_records_inserted  INT NOT NULL DEFAULT 0,
    total_records_updated   INT NOT NULL DEFAULT 0,
    total_records_invalid   INT NOT NULL DEFAULT 0,
    error_summary           TEXT,
    notes                   TEXT
);

COMMENT ON TABLE execution_logs IS 'Registro de cada ejecución del proceso ETL';

-- ── Archivos procesados por ejecución ──────────────────────
CREATE TABLE IF NOT EXISTS processed_files (
    id                   SERIAL PRIMARY KEY,
    execution_id         INT NOT NULL REFERENCES execution_logs(id) ON DELETE CASCADE,
    file_name            VARCHAR(255) NOT NULL,
    file_path            VARCHAR(1024) NOT NULL,
    file_size_kb         FLOAT,
    file_modified_at     TIMESTAMPTZ,
    processed_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sheets_found         INT NOT NULL DEFAULT 0,
    sheets_processed     INT NOT NULL DEFAULT 0,
    records_inserted     INT NOT NULL DEFAULT 0,
    records_invalid      INT NOT NULL DEFAULT 0,
    status               VARCHAR(20) NOT NULL DEFAULT 'ok',   -- ok | error | skipped
    error_detail         TEXT
);

COMMENT ON TABLE processed_files IS 'Detalle de cada archivo Excel procesado en una ejecución';

-- ── Novedades de Nómina (tabla principal de datos) ─────────
CREATE TABLE IF NOT EXISTS novedades_nomina (
    id                          SERIAL PRIMARY KEY,

    -- Trazabilidad
    archivo_origen              VARCHAR(255) NOT NULL,
    hoja_origen                 VARCHAR(255) NOT NULL,
    fecha_procesamiento         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    fecha_modificacion_archivo  TIMESTAMPTZ,
    execution_id                INT,

    -- Datos de nómina
    cedula                      VARCHAR(30),
    nombre_empleado             VARCHAR(200),
    area                        VARCHAR(200),
    cargo                       VARCHAR(200),
    tipo_novedad                VARCHAR(150),
    descripcion_novedad         TEXT,
    fecha_inicio                DATE,
    fecha_fin                   DATE,
    dias                        FLOAT,
    valor                       NUMERIC(18, 2),
    periodo                     VARCHAR(20),       -- YYYY-MM
    estado                      VARCHAR(50),
    observaciones               TEXT,
    columnas_extra              TEXT,              -- JSON con columnas no estándar

    -- Control de calidad
    es_valido                   SMALLINT NOT NULL DEFAULT 1,  -- 1=válido, 0=inválido
    razon_invalido              TEXT,

    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE novedades_nomina IS 'Consolidado de novedades de nómina leídas de los archivos Excel';
COMMENT ON COLUMN novedades_nomina.columnas_extra IS 'JSON con campos adicionales no mapeados en el esquema estándar';
COMMENT ON COLUMN novedades_nomina.periodo IS 'Período en formato YYYY-MM (inferido de fecha_inicio o nombre del archivo)';
