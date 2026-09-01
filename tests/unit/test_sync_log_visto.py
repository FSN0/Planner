"""Tests para marcar errores de sync Odoo como vistos."""

import pytest
from app.models import SyncLog
from app.services.sync_dashboard_service import (
    get_recent_sync_alerts,
    marcar_sync_log_visto,
    marcar_alertas_sync_vistas,
)


@pytest.fixture
def sync_logs(session, tenant_soltec, app):
    from sqlalchemy import text
    session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
    logs = [
        SyncLog(tipo='Fichajes', estado='error', mensaje_error='fallo A'),
        SyncLog(tipo='Fichajes', estado='ok', errores=0),
        SyncLog(tipo='Obras', estado='parcial', errores=2),
    ]
    session.add_all(logs)
    session.commit()
    return logs


def test_marcar_sync_log_visto_oculta_de_alertas(session, tenant_soltec, app, sync_logs):
    from sqlalchemy import text
    session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))

    err = sync_logs[0]
    critical_before, _ = get_recent_sync_alerts()
    assert any(l.id == err.id for l in critical_before)

    marcar_sync_log_visto(err.id)
    session.commit()

    critical_after, partial_after = get_recent_sync_alerts()
    assert not any(l.id == err.id for l in critical_after)
    assert err.visto is True
    assert err.visto_en is not None


def test_marcar_alertas_sync_vistas_todas(session, tenant_soltec, app, sync_logs):
    from sqlalchemy import text
    session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))

    marcar_alertas_sync_vistas()
    session.commit()

    critical, partial = get_recent_sync_alerts()
    assert critical == []
    assert partial == []
