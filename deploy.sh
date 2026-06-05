#!/bin/bash
set -e

echo "╔════════════════════════════════════════╗"
echo "║   SIGNAPLAN - Deploy a Producción      ║"
echo "╚════════════════════════════════════════╝"
echo ""

# Verificar que existe .env
if [ ! -f .env ]; then
    echo "ERROR: No existe el archivo .env"
    echo "Copia .env.production.example como .env y rellena los valores:"
    echo "  cp .env.production.example .env"
    echo "  nano .env"
    exit 1
fi

# Verificar variables críticas
source .env
if [ -z "$SECRET_KEY" ]; then
    echo "ERROR: SECRET_KEY no está definida en .env"
    echo "Genera una con: python3 -c \"import secrets; print(secrets.token_hex(32))\""
    exit 1
fi

if [ -z "$POSTGRES_PASSWORD" ]; then
    echo "ERROR: POSTGRES_PASSWORD no está definida en .env"
    exit 1
fi

if [ -z "$ENCRYPTION_KEY" ]; then
    echo "ERROR: ENCRYPTION_KEY no está definida en .env"
    echo "Genera una con: python3 -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
    exit 1
fi

echo "[1/4] Construyendo imágenes..."
docker compose -f docker-compose.prod.yml build

echo "[2/4] Iniciando servicios..."
docker compose -f docker-compose.prod.yml up -d

echo "[3/4] Esperando a que la base de datos esté lista..."
sleep 5

echo "[4/4] Verificando estado..."
docker compose -f docker-compose.prod.yml ps

echo ""
echo "════════════════════════════════════════"
echo "  Deploy completado."
echo ""
echo "  Panel superadmin: https://signaplan.com/superadmin"
echo "  Logs: docker compose -f docker-compose.prod.yml logs -f"
echo "════════════════════════════════════════"
