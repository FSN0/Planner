-- Migración manual: zona horaria por usuario + config global
-- Ejecutar si no usas Flask-Migrate automático.

ALTER TABLE users ADD COLUMN IF NOT EXISTS timezone VARCHAR(64);

INSERT INTO configuracion_global (clave, valor)
SELECT 'zona_horaria', 'Europe/Madrid'
WHERE NOT EXISTS (
    SELECT 1 FROM configuracion_global WHERE clave = 'zona_horaria'
);
