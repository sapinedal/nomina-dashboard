-- ============================================================
-- Rollback de 05_user_areas_and_audit.sql
--
-- ADVERTENCIA: DROP TABLE elimina los datos de forma irreversible.
-- audit_logs es un registro de auditoría -- confirmar con el negocio
-- antes de borrarlo en producción (puede haber requisito de retención).
-- user_areas se puede recrear re-asignando áreas desde Administración ->
-- Usuarios, pero el historial de quién asignó qué (created_by/created_at)
-- se pierde.
-- ============================================================

DROP TABLE IF EXISTS user_areas;
DROP TABLE IF EXISTS audit_logs;
