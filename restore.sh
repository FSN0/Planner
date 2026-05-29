#!/bin/bash

# Directorio de backups
BACKUP_DIR="./backups"

# Colores para mensajes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}=== SISTEMA DE RESTAURACIÓN SOLTEC ===${NC}"

# 1. Listar backups disponibles
if [ -z "$(ls -A $BACKUP_DIR/*.sql 2>/dev/null)" ]; then
   echo "❌ No hay backups .sql en la carpeta $BACKUP_DIR"
   exit 1
fi

echo "Copias de seguridad encontradas:"
ls -1 $BACKUP_DIR/*.sql | xargs -n 1 basename | sed 's/db_//' | sed 's/.sql//'
echo ""
echo -e "${YELLOW}Introduce el TIMESTAMP (la fecha/hora, ej: 20251216_173000) que quieres restaurar:${NC}"
read TIMESTAMP

DB_FILE="$BACKUP_DIR/db_$TIMESTAMP.sql"
UPLOADS_FILE="$BACKUP_DIR/uploads_$TIMESTAMP.tar.gz"

# 2. Verificar que existen los archivos
if [[ ! -f "$DB_FILE" ]]; then
    echo -e "${RED}Error: No encuentro el archivo de base de datos: $DB_FILE${NC}"
    exit 1
fi

if [[ ! -f "$UPLOADS_FILE" ]]; then
    echo -e "${RED}Error: No encuentro el archivo de uploads: $UPLOADS_FILE${NC}"
    exit 1
fi

# 3. Confirmación de seguridad
echo -e "${RED}¡PELIGRO! Vas a restaurar la copia del $TIMESTAMP.${NC}"
echo -e "${RED}ESTO BORRARÁ TODOS LOS DATOS ACTUALES DE LA BASE DE DATOS Y LOS FICHEROS SUBIDOS.${NC}"
echo "¿Estás absolutamente seguro? (escribe 'si' para continuar)"
read CONFIRMATION

if [[ "$CONFIRMATION" != "si" ]]; then
    echo "Cancelado."
    exit 0
fi

echo -e "${GREEN}Iniciando restauración...${NC}"

# 4. Parar servicios web (para que nadie escriba mientras restauramos)
echo "1. Deteniendo la web y los workers..."
docker compose stop web celery_worker

# 5. Restaurar Ficheros (Uploads)
echo "2. Restaurando carpeta 'uploads'..."
# Borramos la carpeta actual para que no queden ficheros 'zombies'
rm -rf ./uploads/*
# Descomprimimos
tar -xzf "$UPLOADS_FILE" -C .
echo "✅ Ficheros restaurados."

# 6. Restaurar Base de Datos
echo "3. Restaurando Base de Datos..."

# Truco PRO: Borramos el esquema 'public' y lo recreamos. 
# Es más rápido y limpio que borrar toda la base de datos o ir tabla por tabla.
echo "   - Limpiando base de datos actual..."
docker compose exec -T db psql -U postgres gestion_obra_saas -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;" > /dev/null 2>&1

echo "   - Importando datos desde el backup..."
cat "$DB_FILE" | docker compose exec -T db psql -U postgres gestion_obra_saas > /dev/null 2>&1

if [ $? -eq 0 ]; then
    echo "✅ Base de datos restaurada correctamente."
else
    echo -e "${RED}❌ Hubo un error al importar la base de datos.${NC}"
    # Intentamos arrancar de todos modos por si acaso
fi

# 7. Arrancar todo de nuevo
echo "4. Arrancando servicios..."
docker compose start web celery_worker

echo -e "${GREEN}✨ RESTAURACIÓN COMPLETADA CON ÉXITO ✨${NC}"
