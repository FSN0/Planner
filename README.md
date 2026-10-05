# SignaPlan

Aplicación SaaS multi-tenant de gestión de obra. Flask + PostgreSQL + Celery + Caddy.

## Estructura del proyecto

```
├── app/                    # Aplicación Flask
│   ├── admin/              # Panel administrador
│   ├── api/                # API REST
│   ├── auth/               # Autenticación
│   ├── jefe_obra/          # Panel jefe de obra
│   ├── notas/              # Sistema de notas
│   ├── operarios/          # Panel operarios
│   ├── rrhh/               # Panel RRHH
│   ├── services/           # Lógica de negocio
│   ├── superadmin/         # Panel superadmin (multi-tenant)
│   ├── sync/               # Sincronización con Odoo
│   ├── static/             # CSS, JS
│   ├── templates/          # Jinja2 templates
│   └── config.py           # Configuración Flask
├── migrations/             # Alembic (migraciones de DB)
├── tests/                  # Tests (unit + integration)
├── scripts/                # Scripts de operaciones
│   ├── setup-server.sh     # Provisioning de servidor nuevo
│   ├── deploy.sh           # Deploy/actualización producción
│   ├── backup.sh           # Crear backup
│   └── restore.sh          # Restaurar backup
├── docker-compose.yml      # Compose para DESARROLLO
├── docker-compose.prod.yml # Compose para PRODUCCIÓN
├── Dockerfile              # Imagen de la app
├── Caddyfile               # Caddy dev (HTTP)
├── Caddyfile.prod          # Caddy prod (HTTPS + On-Demand TLS)
├── Makefile                # Comandos unificados
├── .env.example            # Template variables dev
├── .env.production.example # Template variables prod
├── requirements.txt        # Dependencias Python
└── run.py                  # Entry point Flask
```

## Desarrollo local

### Requisitos
- Docker + Docker Compose

### Setup inicial

```bash
# 1. Clonar el repo
git clone -b VERSION_SAAS git@github.com:FSN0/Planner.git
cd Planner

# 2. Crear .env de desarrollo
cp .env.example .env

# 3. Levantar todo
make dev

# 4. (Primera vez) Inicializar SaaS con tenant demo
make init-saas
```

### Comandos frecuentes

```bash
make dev            # Levantar entorno
make dev-build      # Rebuild sin caché
make dev-down       # Parar todo
make dev-restart    # Reiniciar solo web (rápido)
make logs           # Ver logs
make shell          # Bash en el contenedor web
make db-shell       # psql directo
make migrate        # Aplicar migraciones
make migrate-new MSG="añadir campo X"  # Crear migración
make test           # Ejecutar tests
make help           # Ver todos los comandos
```

### Acceso local
- `http://localhost` → Esquema público
- `http://demo.localhost` → Tenant demo
- `http://localhost/superadmin` → Panel de gestión de tenants

## Producción

### Servidor nuevo (desde cero)

```bash
# 1. En el servidor como root:
bash scripts/setup-server.sh

# 2. Añadir la Deploy Key en GitHub (la muestra el script)

# 3. Conectar como deployer:
ssh deployer@212.227.94.86

# 4. Clonar y configurar:
cd /opt/saas
git clone -b VERSION_SAAS git@github.com:FSN0/Planner.git .
cp .env.production.example .env
nano .env  # Rellenar TODOS los valores

# 5. Desplegar:
make prod-deploy
```

### Actualizaciones

```bash
ssh deployer@212.227.94.86
cd /opt/saas
make prod-update           # Pull + rebuild + restart
make prod-deploy           # Full deploy con migraciones
```

### Operaciones

```bash
make backup                # Backup DB + uploads
make restore TS=20260607_120000  # Restaurar
make prod-logs             # Logs en tiempo real
make prod-status           # Estado de servicios
make migrate-prod          # Aplicar migraciones
```

### DNS

Configurar en el proveedor de dominio:
```
signaplan.com      → A → 212.227.94.86
*.signaplan.com    → A → 212.227.94.86
```

Caddy gestionará los certificados HTTPS automáticamente (On-Demand TLS para subdominios de clientes).

## Arquitectura

- **Multi-tenant**: Cada cliente tiene su propio schema PostgreSQL
- **Routing**: Subdominio → schema (ej: `cliente1.signaplan.com` → schema `cliente1`)
- **Workers**: Celery procesa tareas pesadas (emails, sincronización Odoo)
- **Proxy**: Caddy maneja TLS automático y reverse proxy
