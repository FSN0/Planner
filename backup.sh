#!/bin/bash

# 1. Definir fecha y directorio de backups
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_DIR="./backups"
mkdir -p $BACKUP_DIR

echo "--- Iniciando Backup [$TIMESTAMP] ---"

# 2. Backup de la Base de Datos
echo "1. Exportando Base de Datos..."
docker compose exec -T db pg_dump -U postgres gestion_obra_db > "$BACKUP_DIR/db_$TIMESTAMP.sql"

# 3. Backup de los Archivos (Uploads)
echo "2. Comprimiendo ficheros subidos..."
tar -czf "$BACKUP_DIR/uploads_$TIMESTAMP.tar.gz" ./uploads

# 4. (Opcional) Borrar backups antiguos de más de 7 días para no llenar el disco
find $BACKUP_DIR -type f -mtime +7 -name "*.sql" -delete
find $BACKUP_DIR -type f -mtime +7 -name "*.tar.gz" -delete

echo "✅ Backup completado en la carpeta $BACKUP_DIR"
