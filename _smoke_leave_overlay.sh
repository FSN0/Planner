#!/usr/bin/env bash
set -euo pipefail
cd /opt/soltec/planner
docker compose -f docker-compose.yml exec -T web python <<'PY'
from app import create_app
app = create_app()
with app.app_context():
    from app.services import leave_service as ls
    from app.models import CONFLICT_OVERLAY, AusenciaPlanificada, Asignacion
    assert CONFLICT_OVERLAY == 'overlay'
    class L:
        tipo = 'Vacaciones'
        estado = 'aprobada'
        id = 1
        def covers(self, d):
            return True
    t, c, o = ls.apply_leave_overlay_title('Pepe', L(), name_first=True)
    assert o and 'Vacaciones' in t and c == ls.LEAVE_COLOR_APROBADA
    print('overlay_title_ok', t)
    # Compile calendar module
    from app.api import routes as api_routes
    assert hasattr(api_routes, 'procesar_bloques_empresa')
    print('SMOKE_OK')
PY
