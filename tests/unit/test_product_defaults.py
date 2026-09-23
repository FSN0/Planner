from datetime import date, timedelta
from types import SimpleNamespace

from flask import g
from sqlalchemy import text

from app.models import (
    LEAVE_SOURCE_MANUAL,
    LEAVE_STATUS_APROBADA,
    Asignacion,
    AusenciaPlanificada,
)
from app.services.core_assignment_service import CoreAssignmentService
from app.services.leave_service import auto_resolucion_ausencias
from app.services.tenant_modules import (
    conforme_jornada_activo,
    has_auditoria_vehiculos,
    has_notas,
    has_valoraciones,
    has_portal_ausencias,
    hora_corte_activa,
    hora_corte_destinatario_ids,
)
from app.services.assign_mode_service import (
    ASSIGN_MODE_DIRECT,
    ASSIGN_MODE_SOLICITUD,
    default_assign_mode_for_role,
)
from app.utils.timezone_utils import get_user_timezone


def _tenant(sub, mods=None):
    return SimpleNamespace(subdominio=sub, modulos_activos=mods or {})


def _no_config(monkeypatch):
    monkeypatch.setattr(
        'app.services.config_service.get_tenant_config',
        lambda *a, **k: k.get('default'),
    )


def test_soltec_keeps_legacy_modules_when_key_missing(app):
    with app.app_context():
        g.current_tenant = _tenant('soltec', {})
        assert has_notas() is True
        assert has_valoraciones() is True
        assert has_auditoria_vehiculos() is True


def test_generic_tenant_modules_off_when_key_missing(app):
    with app.app_context():
        g.current_tenant = _tenant('acme', {})
        assert has_notas() is False
        assert has_valoraciones() is True
        assert has_auditoria_vehiculos() is False


def test_explicit_false_overrides_soltec_fallback(app):
    with app.app_context():
        g.current_tenant = _tenant(
            'soltec',
            {'notas': False, 'valoraciones': False, 'auditoria_vehiculos': False},
        )
        assert has_notas() is False
        assert has_valoraciones() is True
        assert has_auditoria_vehiculos() is False


def test_valoraciones_always_on(app):
    with app.app_context():
        g.current_tenant = _tenant('acme', {'valoraciones': False})
        assert has_valoraciones() is True
        g.current_tenant = _tenant('soltec', {})
        assert has_valoraciones() is True


def test_portal_ausencias_off_for_soltec_by_default(app):
    with app.app_context():
        g.current_tenant = _tenant('soltec', {})
        assert has_portal_ausencias() is False
        g.current_tenant = _tenant('acme', {})
        assert has_portal_ausencias() is True
        g.current_tenant = _tenant('soltec', {'portal_ausencias': True})
        assert has_portal_ausencias() is True
        g.current_tenant = _tenant('acme', {'portal_ausencias': False})
        assert has_portal_ausencias() is False


def test_assign_mode_defaults_soltec_vs_saas(monkeypatch):
    monkeypatch.setattr(
        'app.services.tenant_modules.is_soltec_tenant', lambda: False
    )
    assert default_assign_mode_for_role('jefe_obra') == ASSIGN_MODE_DIRECT
    monkeypatch.setattr(
        'app.services.tenant_modules.is_soltec_tenant', lambda: True
    )
    assert default_assign_mode_for_role('jefe_obra') == ASSIGN_MODE_SOLICITUD


def test_sidebar_hides_solicitudes_without_perm(monkeypatch):
    from app.services.sidebar_nav_service import ITEM_SOLICITUDES, item_is_available

    jefe = SimpleNamespace(role='jefe_obra', is_authenticated=True)
    monkeypatch.setattr(
        'app.services.sidebar_nav_service.user_can',
        lambda u, m, a='r': False,
    )
    assert item_is_available(ITEM_SOLICITUDES, jefe, {}) is False


def test_sidebar_shows_solicitudes_if_flota_r(monkeypatch):
    from app.services.sidebar_nav_service import ITEM_SOLICITUDES, item_is_available

    jefe = SimpleNamespace(role='jefe_obra', is_authenticated=True)
    monkeypatch.setattr(
        'app.services.sidebar_nav_service.user_can',
        lambda u, m, a='r': m == 'solicitudes_vehiculos',
    )
    assert item_is_available(ITEM_SOLICITUDES, jefe, {}) is True


def test_hora_corte_defaults(app, monkeypatch):
    _no_config(monkeypatch)
    with app.app_context():
        g.current_tenant = _tenant('acme')
        assert hora_corte_activa() is False
        g.current_tenant = _tenant('soltec')
        assert hora_corte_activa() is True


def test_conforme_jornada_off_by_default(app, monkeypatch):
    _no_config(monkeypatch)
    with app.app_context():
        g.current_tenant = _tenant('acme')
        assert conforme_jornada_activo() is False
        g.current_tenant = _tenant('soltec')
        assert conforme_jornada_activo() is False


def test_hora_corte_destinatario_ids_parse(app, monkeypatch):
    monkeypatch.setattr(
        'app.services.config_service.get_tenant_config',
        lambda *a, **k: '3, 7,x,12',
    )
    with app.app_context():
        g.current_tenant = _tenant('acme')
        assert hora_corte_destinatario_ids() == [3, 7, 12]


def test_get_user_timezone_is_always_tenant_zone(monkeypatch):
    monkeypatch.setattr(
        'app.utils.timezone_utils.get_app_timezone',
        lambda: 'Europe/Paris',
    )
    fake_user = SimpleNamespace(timezone='America/New_York')
    assert get_user_timezone(fake_user) == 'Europe/Paris'
    assert get_user_timezone(None) == 'Europe/Paris'


def test_auto_resolucion_always_prefer_leave():
    assert auto_resolucion_ausencias() == 'prefer_leave'


def test_asignar_blocked_by_approved_leave(
    session, tenant_soltec, user_operario, obra_activa, user_admin,
):
    session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
    day = date.today() + timedelta(days=4)
    session.add(AusenciaPlanificada(
        user_id=user_operario.id,
        fecha_inicio=day,
        fecha_fin=day,
        tipo='Vacaciones',
        estado=LEAVE_STATUS_APROBADA,
        origen=LEAVE_SOURCE_MANUAL,
        created_by_id=user_admin.id,
    ))
    session.commit()

    created = CoreAssignmentService.asignar(
        user_operario.id, obra_activa.id, day, user_admin.id, 'test',
    )
    assert created is None
    assert Asignacion.query.filter_by(
        user_id=user_operario.id, fecha=day,
    ).count() == 0


def test_create_manual_leave_on_assigned_day_returns_id(
    app, session, tenant_soltec, user_operario, obra_activa, user_admin,
):
    """Alta de vacaciones con gente ya en obra: no debe petar al leer leave.id."""
    from flask import g
    from app.services.leave_service import create_manual_leave

    session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
    g.current_tenant = tenant_soltec
    day = date.today() + timedelta(days=5)
    created = CoreAssignmentService.asignar(
        user_operario.id, obra_activa.id, day, user_admin.id, 'test',
    )
    assert created is not None
    session.commit()

    leave = create_manual_leave(
        user_id=user_operario.id,
        fecha_inicio=day,
        fecha_fin=day,
        tipo='Vacaciones',
        estado=LEAVE_STATUS_APROBADA,
        created_by_id=user_admin.id,
    )
    assert leave is not None
    assert leave.id is not None
    assert leave.estado == LEAVE_STATUS_APROBADA
    assert Asignacion.query.filter_by(
        user_id=user_operario.id, fecha=day,
    ).count() == 0
