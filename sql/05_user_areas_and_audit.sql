-- ============================================================
-- NóminaBoard - Autorización por área (user_areas) + auditoría (audit_logs)
-- Migración incremental sobre el esquema de 01-04. Idempotente
-- (CREATE TABLE/INDEX IF NOT EXISTS) -- se puede correr varias veces sin error.
-- Rollback: ver 05_user_areas_and_audit_rollback.sql
-- ============================================================

-- ── Autorización por área ──────────────────────────────────
-- Relación many-to-many usuario<->área. `area` es texto libre (mismo valor
-- que novedades_nomina.area) -- no existe un catálogo normalizado de áreas
-- en este sistema, así que no se agrega uno solo para esto.
-- Sin columna de soft-delete: eliminar un área asignada es un DELETE real.
CREATE TABLE IF NOT EXISTS user_areas (
    id           SERIAL PRIMARY KEY,
    user_id      INT          NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    area         VARCHAR(200) NOT NULL,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    created_by   VARCHAR(50),
    CONSTRAINT uq_user_areas_user_area UNIQUE (user_id, area)
);

COMMENT ON TABLE user_areas IS 'Autorización por área: qué áreas puede ver/gestionar cada usuario no-admin. Un usuario admin no tiene filas aquí (sin restricción, ver auth_service.get_user_areas).';
COMMENT ON COLUMN user_areas.area IS 'Texto libre, mismo valor que novedades_nomina.area -- no hay catálogo de áreas separado';

CREATE INDEX IF NOT EXISTS ix_user_areas_user_id ON user_areas (user_id);
CREATE INDEX IF NOT EXISTS ix_user_areas_area    ON user_areas (area);

-- ── Auditoría genérica ──────────────────────────────────────
-- No acoplada a `users` -- reusable a futuro para otras entidades
-- administrativas sin necesitar una tabla nueva por cada una.
CREATE TABLE IF NOT EXISTS audit_logs (
    id               SERIAL PRIMARY KEY,
    entity_type      VARCHAR(50) NOT NULL,
    entity_id        INT         NOT NULL,
    action           VARCHAR(30) NOT NULL,   -- create | update | delete | areas_changed
    actor_username   VARCHAR(50),
    changes          TEXT,                    -- JSON: {"campo": {"antes": ..., "despues": ...}}
    ip_address       VARCHAR(45),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE audit_logs IS 'Registro de auditoría genérico por entidad/acción/actor. Usado hoy para creación, edición, cambio de áreas y eliminación de usuarios.';

CREATE INDEX IF NOT EXISTS ix_audit_entity      ON audit_logs (entity_type, entity_id);
CREATE INDEX IF NOT EXISTS ix_audit_created_at  ON audit_logs (created_at);
