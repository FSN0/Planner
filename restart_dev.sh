#!/bin/bash
# Script rápido para reiniciar el entorno de desarrollo

echo "🛑 Deteniendo contenedores..."
docker-compose down

echo ""
echo "🔨 Reconstruyendo imágenes (esto toma un minuto)..."
docker-compose build --no-cache

echo ""
echo "🚀 Levantando servicios..."
docker-compose up -d

echo ""
echo "⏳ Esperando a que los servicios inicien..."
sleep 5

echo ""
echo "✅ Entorno listo!"
echo ""
echo "📍 Accede a tu aplicación en:"
echo "   http://soltec.localhost    (o tu tenant)"
echo "   http://demo.localhost"
echo "   http://localhost/superadmin"
echo ""
echo "📋 Ver logs en tiempo real:"
echo "   docker-compose logs -f web"
echo ""
echo "🛑 Para parar todo:"
echo "   docker-compose down"
