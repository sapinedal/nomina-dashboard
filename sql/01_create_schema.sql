-- ============================================================
-- NóminaBoard - Script de creación de esquema
-- Motor: PostgreSQL 15+
-- ============================================================

-- Extensiones útiles
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";  -- Para búsqueda de texto

-- Tipos enumerados
DO $$ BEGIN
    CREATE TYPE user_role AS ENUM ('admin', 'analyst', 'readonly');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE execution_status AS ENUM ('running', 'completed', 'failed', 'partial');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
