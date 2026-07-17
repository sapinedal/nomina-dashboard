-- ============================================================
-- NóminaBoard - Datos iniciales
-- Contraseña admin: Admin2024!  (bcrypt hash)
-- CAMBIAR LA CONTRASEÑA DESPUÉS DE LA PRIMERA INSTALACIÓN
-- ============================================================

INSERT INTO users (username, email, full_name, hashed_password, role, is_active)
VALUES
  (
    'admin',
    'admin@sumimedical.com',
    'Administrador del Sistema',
    '$2b$12$KmG5zR2bCL9wH8xN4pT7/OQI2kHf1aJL3mN6sB8dK0pE9vX7yZ1ci',  -- Admin2024!
    'admin',
    TRUE
  ),
  (
    'analista',
    'analista@sumimedical.com',
    'Analista de Nómina',
    '$2b$12$KmG5zR2bCL9wH8xN4pT7/OQI2kHf1aJL3mN6sB8dK0pE9vX7yZ1ci',  -- Admin2024!
    'analyst',
    TRUE
  ),
  (
    'consultor',
    'consultor@sumimedical.com',
    'Usuario de Consulta',
    '$2b$12$KmG5zR2bCL9wH8xN4pT7/OQI2kHf1aJL3mN6sB8dK0pE9vX7yZ1ci',  -- Admin2024!
    'readonly',
    TRUE
  )
ON CONFLICT (username) DO NOTHING;
