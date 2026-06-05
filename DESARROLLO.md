# Instrucciones para Desarrollo Local

## ✅ LISTO PARA DESARROLLAR

Ya está todo configurado para que sigas desarrollando en `cliente.localhost`.

## 🚀 Levantar el entorno

```bash
# Reconstruir (solo necesario la primera vez o tras cambios en requirements.txt)
docker-compose build

# Levantar todos los servicios
docker-compose up

# O en segundo plano
docker-compose up -d
```

## 🌐 Acceder a la aplicación

Accede desde el navegador a:
- `http://soltec.localhost` (o el subdominio de tu tenant)
- `http://demo.localhost`
- `http://localhost/superadmin` (panel de administración SaaS)

## 📝 Archivo `.env` creado

El archivo `.env` tiene la configuración necesaria para desarrollo:
- `FLASK_DEBUG=true` → cookies funcionan en HTTP, recarga automática
- `CELERY_TASK_ALWAYS_EAGER=true` → tareas síncronas (más fácil debuggear)
- Secretos simples para desarrollo local

**IMPORTANTE:** Si ya tenías una `ENCRYPTION_KEY`, ábrela en el `.env` y ponla ahí. 
Si no, deja esa línea comentada (solo si no tienes datos cifrados previos).

## 🔧 Cambios en el código

Con el bind mount activado (`.:/app`), cualquier cambio en archivos Python se reflejará:
- Flask en modo debug recarga automáticamente
- Celery worker necesita `docker-compose restart celery_worker` para ver cambios

## 🛑 Parar todo

```bash
docker-compose down
```

## 📦 Para producción

Cuando vayas a producción:
1. Crea un `.env.production` con valores reales y fuertes
2. Exporta las variables en el servidor (no uses el `.env` en el repo)
3. Opcionalmente, quita los bind mounts del docker-compose.yml
