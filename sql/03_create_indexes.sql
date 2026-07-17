-- ============================================================
-- NóminaBoard - Índices para optimización de consultas
-- ============================================================

-- Usuarios
CREATE INDEX IF NOT EXISTS ix_users_username  ON users (username);
CREATE INDEX IF NOT EXISTS ix_users_role      ON users (role);

-- Ejecuciones
CREATE INDEX IF NOT EXISTS ix_exec_started_at ON execution_logs (started_at DESC);
CREATE INDEX IF NOT EXISTS ix_exec_status     ON execution_logs (status);

-- Archivos procesados
CREATE INDEX IF NOT EXISTS ix_pfiles_exec_id  ON processed_files (execution_id);
CREATE INDEX IF NOT EXISTS ix_pfiles_status   ON processed_files (status);

-- Novedades - índices de consulta frecuente
CREATE INDEX IF NOT EXISTS ix_nomina_cedula          ON novedades_nomina (cedula);
CREATE INDEX IF NOT EXISTS ix_nomina_area            ON novedades_nomina (area);
CREATE INDEX IF NOT EXISTS ix_nomina_tipo            ON novedades_nomina (tipo_novedad);
CREATE INDEX IF NOT EXISTS ix_nomina_periodo         ON novedades_nomina (periodo);
CREATE INDEX IF NOT EXISTS ix_nomina_archivo         ON novedades_nomina (archivo_origen);
CREATE INDEX IF NOT EXISTS ix_nomina_exec_id         ON novedades_nomina (execution_id);
CREATE INDEX IF NOT EXISTS ix_nomina_es_valido       ON novedades_nomina (es_valido);
CREATE INDEX IF NOT EXISTS ix_nomina_fecha_inicio    ON novedades_nomina (fecha_inicio);
CREATE INDEX IF NOT EXISTS ix_nomina_cedula_periodo  ON novedades_nomina (cedula, periodo);
CREATE INDEX IF NOT EXISTS ix_nomina_area_tipo       ON novedades_nomina (area, tipo_novedad);

-- Índice de texto para búsqueda de nombres (requiere pg_trgm)
CREATE INDEX IF NOT EXISTS ix_nomina_nombre_trgm
    ON novedades_nomina USING GIN (nombre_empleado gin_trgm_ops);
