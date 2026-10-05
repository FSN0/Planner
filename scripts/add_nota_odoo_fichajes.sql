-- Migración manual: notas de fichaje desde Odoo (campo 'note')
-- Ejecutar si no usas Flask-Migrate automático.

ALTER TABLE registros_fichajes ADD COLUMN IF NOT EXISTS nota_odoo TEXT;
