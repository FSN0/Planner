#!/bin/bash
set -e
cd /opt/soltec/planner
OUT=/opt/soltec/planner/_checks_out.txt
{
  echo "=== 2. docker compose ps ==="
  docker compose ps celery_worker celery_beat
  echo
  echo "=== 3. ADVISORY LOCKS ==="
  docker compose exec -T db psql -U postgres -d gestion_obra -c "SELECT locktype, objid, pid, mode, granted FROM pg_locks WHERE locktype = 'advisory';"
  echo
  echo "=== 4. FICHAJE COUNTS ==="
  docker compose exec -T db psql -U postgres -d gestion_obra -c "SELECT CURRENT_DATE; SELECT COUNT(*) AS hoy FROM tenant_soltec.registros_fichajes WHERE fecha = CURRENT_DATE; SELECT COUNT(*) AS ayer FROM tenant_soltec.registros_fichajes WHERE fecha = CURRENT_DATE - 1; SELECT MAX(fecha) FROM tenant_soltec.registros_fichajes;"
  echo
  echo "=== 5. ONE-SHOT SYNC ==="
  docker compose exec -T -w /app -e PYTHONPATH=/app web python - <<'PY'
from app import create_app, db
from sqlalchemy import text
from app.services.sync_service import procesar_fichajes_diarios
from app.models import RegistroFichaje, Tenant
from app.utils.timezone_utils import today_local
from flask import g

app = create_app()
with app.app_context():
    row = db.session.execute(text("SELECT id, schema_name, subdominio, nombre, modulos_activos FROM public.tenants WHERE subdominio='soltec'")).fetchone()
    db.session.execute(text(f'SET search_path TO {row[1]}'))
    g.current_tenant = Tenant(id=row[0], schema_name=row[1], subdominio=row[2], nombre=row[3] or '', modulos_activos=row[4] if isinstance(row[4], dict) else {})
    print('today_local', today_local())
    print('before', RegistroFichaje.query.filter_by(fecha=today_local()).count())
    print('ran', procesar_fichajes_diarios())
    print('after', RegistroFichaje.query.filter_by(fecha=today_local()).count())
PY
} > "$OUT" 2>&1
echo DONE >> "$OUT"
