# =============================================================================
# SignaPlan - Makefile unificado
# =============================================================================
# Uso:
#   make dev          → Levanta entorno de desarrollo
#   make ship         → Commit + push (listo para prod-update)
#   make prod-deploy  → Despliega en producción
#   make logs         → Ver logs en tiempo real
#   make help         → Ver todos los comandos disponibles
# =============================================================================

.PHONY: help sync-brand dev dev-build dev-down dev-restart prod-deploy prod-down prod-logs \
        migrate migrate-new backup restore test test-db test-unit test-integration \
        test-ledger test-pwa test-erp test-informe test-pin test-plan test-comercial \
        test-oficina test-onboarding lan-tunnel logs shell db-shell clean init-saas \
        odoo-creds odoo-creds-prod ship agent-readonly

# Detectar compose file según entorno
DEV_COMPOSE  = docker-compose.yml
PROD_COMPOSE = docker-compose.prod.yml

# Los tests corren contra una base de datos aparte que se borra a cada vuelta.
TEST_DB           = gestion_obra_test
TEST_DATABASE_URL = postgresql://postgres:$${POSTGRES_PASSWORD:-postgres}@db:5432/$(TEST_DB)
PYTEST            = docker compose -f $(DEV_COMPOSE) exec \
                        -e TEST_DATABASE_URL="$(TEST_DATABASE_URL)" \
                        web python -m pytest

# ─────────────────────────────────────────────────────────────────────────────
# AYUDA
# ─────────────────────────────────────────────────────────────────────────────
help: ## Muestra esta ayuda
	@echo ""
	@echo "╔════════════════════════════════════════╗"
	@echo "║     SignaPlan - Comandos Make          ║"
	@echo "╚════════════════════════════════════════╝"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@echo ""

# ─────────────────────────────────────────────────────────────────────────────
# DESARROLLO
# ─────────────────────────────────────────────────────────────────────────────
sync-brand: ## Copia logos desde logos_signaplan/ a static/img/brand
	@bash scripts/sync_brand_assets.sh

dev: ## Levanta entorno de desarrollo
	@$(MAKE) sync-brand
	docker compose -f $(DEV_COMPOSE) up -d --build
	@echo ""
	@echo "✓ Entorno de desarrollo listo"
	@echo "  http://localhost       (esquema public)"
	@echo "  http://demo.localhost  (tenant demo)"
	@echo ""

dev-build: ## Rebuild completo (sin caché) + levantar
	@$(MAKE) sync-brand
	docker compose -f $(DEV_COMPOSE) build --no-cache
	docker compose -f $(DEV_COMPOSE) up -d

dev-down: ## Detener entorno de desarrollo
	docker compose -f $(DEV_COMPOSE) down

dev-restart: ## Reiniciar solo el contenedor web (rápido)
	docker compose -f $(DEV_COMPOSE) restart web

# ─────────────────────────────────────────────────────────────────────────────
# GIT (dev → producción)
# ─────────────────────────────────────────────────────────────────────────────
# Un solo comando: stage + commit + push.
# Mensaje opcional: make ship MSG="arregla X"
# -c safe.directory=* evita el "dubious ownership" si lanzas make como root
# en un repo cuyo dueño es otro usuario (típico en WSL).
GIT = git -c safe.directory=*

ship: ## Commit de TODO lo pendiente y push al remoto (para luego prod-update)
	@if ! $(GIT) rev-parse --is-inside-work-tree >/dev/null 2>&1; then \
		echo "✗ No es un repositorio git"; \
		exit 1; \
	fi
	@status="$$($(GIT) status --porcelain 2>&1)"; \
	rc=$$?; \
	if [ $$rc -ne 0 ]; then \
		echo "✗ git status falló:"; \
		echo "$$status"; \
		exit $$rc; \
	fi; \
	if [ -n "$$status" ]; then \
		$(GIT) add -A; \
		if ! $(GIT) diff --cached --quiet; then \
			msg="$(MSG)"; \
			if [ -z "$$msg" ]; then \
				msg="chore: snapshot desarrollo $$(date +%Y-%m-%d\ %H:%M)"; \
			fi; \
			$(GIT) commit -m "$$msg"; \
			echo "✓ Commit creado"; \
		else \
			echo "✓ Nada nuevo que commitear (¿todo ignorado?)"; \
		fi; \
	else \
		echo "✓ Working tree limpio (sin cambios locales)"; \
	fi
	@echo "→ Push…"
	@$(GIT) push -u origin HEAD
	@echo ""
	@echo "✓ En internet. En el servidor: make prod-update"
	@echo ""

# ─────────────────────────────────────────────────────────────────────────────
# PRODUCCIÓN
# ─────────────────────────────────────────────────────────────────────────────
prod-deploy: ## Desplegar en producción (build + up)
	@bash scripts/deploy.sh --build --migrate

prod-update: ## Actualizar producción (git pull + rebuild)
	@bash scripts/deploy.sh --build

prod-down: ## Detener producción
	docker compose -f $(PROD_COMPOSE) down

prod-logs: ## Logs de producción en tiempo real
	docker compose -f $(PROD_COMPOSE) logs -f

prod-status: ## Estado de los servicios en producción
	docker compose -f $(PROD_COMPOSE) ps

# ─────────────────────────────────────────────────────────────────────────────
# MIGRACIONES
# ─────────────────────────────────────────────────────────────────────────────
migrate: ## Aplicar migraciones pendientes (dev)
	docker compose -f $(DEV_COMPOSE) exec web flask db upgrade

migrate-new: ## Crear nueva migración. Uso: make migrate-new MSG="descripcion"
	docker compose -f $(DEV_COMPOSE) exec web flask db migrate -m "$(MSG)"

migrate-prod: ## Aplicar migraciones en producción (funciona aunque web esté parado)
	@bash scripts/fix_migration_heads.sh
	docker compose -f $(PROD_COMPOSE) build web
	docker compose -f $(PROD_COMPOSE) up -d db
	@sleep 3
	docker compose -f $(PROD_COMPOSE) run --rm --no-deps web flask db upgrade

agent-readonly: ## Provisiona rol/vistas agent_* (Soltec) y regenera CONECTOR_AGENTE.txt
	@COMPOSE_FILE=$(PROD_COMPOSE) bash scripts/ensure_agent_readonly.sh

# ─────────────────────────────────────────────────────────────────────────────
# BACKUPS
# ─────────────────────────────────────────────────────────────────────────────
backup: ## Crear backup (DB + uploads) - usa COMPOSE_FILE de prod por defecto
	@COMPOSE_FILE=$(PROD_COMPOSE) bash scripts/backup.sh

backup-dev: ## Backup del entorno de desarrollo
	@COMPOSE_FILE=$(DEV_COMPOSE) bash scripts/backup.sh

restore: ## Restaurar backup (prod). Uso: make restore TS=20260607_120000
	@COMPOSE_FILE=$(PROD_COMPOSE) bash scripts/restore.sh $(TS)

restore-dev: ## Restaurar backup en desarrollo. Uso: make restore-dev TS=20260607_120000
	@COMPOSE_FILE=$(DEV_COMPOSE) bash scripts/restore.sh $(TS)

# ─────────────────────────────────────────────────────────────────────────────
# TESTS
# ─────────────────────────────────────────────────────────────────────────────
test-db: ## Crea la base de datos de test si no existe
	@docker compose -f $(DEV_COMPOSE) exec -T db \
		psql -U postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$(TEST_DB)'" \
		| grep -q 1 \
		|| docker compose -f $(DEV_COMPOSE) exec -T db createdb -U postgres $(TEST_DB)

test: test-db ## Ejecutar todos los tests (dev - usa DB de test)
	$(PYTEST) tests/ -v --tb=short

test-unit: test-db ## Solo tests unitarios (dev)
	$(PYTEST) tests/unit/ -v

test-integration: test-db ## Solo tests de integración (dev)
	$(PYTEST) tests/integration/ -v

test-ledger: test-db ## Solo tests del libro de fichajes
	$(PYTEST) tests/integration/test_fichaje_ledger.py -v

test-pwa: test-db ## Solo tests de la app de fichaje del operario
	$(PYTEST) tests/integration/test_pwa_operario.py -v

test-erp: test-db ## Solo tests del volcado del ERP al libro de fichajes
	$(PYTEST) tests/integration/test_fichaje_erp_ledger.py -v

test-informe: test-db ## Solo tests del informe de registro de jornada
	$(PYTEST) tests/integration/test_fichaje_informe.py -v

test-pin: test-db ## Solo tests del acceso DNI + PIN
	$(PYTEST) tests/integration/test_pin_auth.py -v

test-plan: test-db ## Solo tests del freemium / cupo de plantilla
	$(PYTEST) tests/integration/test_plan_limits.py -v

test-comercial: test-db ## Alta, legales, recuperación y exención de cobro
	$(PYTEST) tests/integration/test_signup_legal_password.py -v

test-oficina: test-db ## Obra Oficina opcional
	$(PYTEST) tests/integration/test_oficina_obra.py -v

test-onboarding: test-db ## Wizard post-alta y panel hoy en obra
	$(PYTEST) tests/integration/test_onboarding_hoy.py -v

lan-tunnel: ## Túnel Cloudflare para probar fichaje desde el móvil
	bash scripts/lan-tunnel.sh

smoke: ## Smoke tests post-deploy (seguro en prod). Uso: make smoke DOMAIN=signaplan.com
	@bash scripts/smoke-test.sh $(DOMAIN)

smoke-prod: ## Smoke tests en producción (signaplan.com)
	@COMPOSE_FILE=$(PROD_COMPOSE) bash scripts/smoke-test.sh signaplan.com

smoke-dev: ## Smoke tests en desarrollo (localhost)
	@COMPOSE_FILE=$(DEV_COMPOSE) bash scripts/smoke-test.sh localhost

# ─────────────────────────────────────────────────────────────────────────────
# UTILIDADES
# ─────────────────────────────────────────────────────────────────────────────
logs: ## Ver logs del entorno de desarrollo
	docker compose -f $(DEV_COMPOSE) logs -f

logs-web: ## Logs solo del servicio web
	docker compose -f $(DEV_COMPOSE) logs -f web

odoo-creds: ## Credenciales Odoo de un tenant (dev). Uso: make odoo-creds TENANT=soltec
	@docker compose -f $(DEV_COMPOSE) exec -T -w /app -e PYTHONPATH=/app web python scripts/show_odoo_creds.py "$(TENANT)"

odoo-creds-prod: ## Credenciales Odoo de un tenant (producción). Uso: make odoo-creds-prod TENANT=soltec
	@docker compose -f $(PROD_COMPOSE) exec -T -w /app -e PYTHONPATH=/app web python scripts/show_odoo_creds.py "$(TENANT)"

shell: ## Abrir shell en el contenedor web (dev)
	docker compose -f $(DEV_COMPOSE) exec web bash

db-shell: ## Abrir psql en la base de datos (dev)
	docker compose -f $(DEV_COMPOSE) exec db psql -U postgres gestion_obra_saas

init-saas: ## Inicializar SaaS (crear tenant demo)
	docker compose -f $(DEV_COMPOSE) exec web python init_saas.py

clean: ## Limpiar todo (contenedores, volúmenes, imágenes huérfanas)
	docker compose -f $(DEV_COMPOSE) down -v --remove-orphans
	docker image prune -f
	@echo "✓ Limpieza completada (volúmenes eliminados - DATA LOST)"
