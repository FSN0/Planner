"""Preferencias personales de avisos UI (badges)."""
from types import SimpleNamespace

from sqlalchemy import text
from werkzeug.datastructures import MultiDict


def test_get_prefs_default_all_on():
    from app.services.ui_notif_prefs_service import ALL_KEYS, get_prefs, is_enabled

    user = SimpleNamespace(ui_notif_prefs={})
    prefs = get_prefs(user)
    assert set(prefs) == ALL_KEYS
    assert all(prefs.values())
    assert is_enabled(user, 'documentacion')
    assert is_enabled(user, 'certificacion')


def test_get_prefs_respects_opt_out():
    from app.services.ui_notif_prefs_service import get_prefs, is_enabled

    user = SimpleNamespace(ui_notif_prefs={'certificacion': False, 'logs': False})
    prefs = get_prefs(user)
    assert prefs['certificacion'] is False
    assert prefs['logs'] is False
    assert prefs['documentacion'] is True
    assert is_enabled(user, 'certificacion') is False
    assert is_enabled(user, 'solicitudes') is True


def test_apply_to_badge_ctx_zeros_disabled():
    from app.services.ui_notif_prefs_service import apply_to_badge_ctx

    user = SimpleNamespace(ui_notif_prefs={
        'documentacion': False,
        'certificacion': True,
        'logs': False,
    })
    ctx = {
        'doc_errores': 3,
        'doc_avisos': 2,
        'cert_entrantes': 5,
        'contratacion_pendientes': 1,
        'pending_notifications': 4,
        'pending_solicitudes_personal': 2,
        'pending_solicitudes_vehiculos': 2,
        'unread_logs_count': 7,
        'unread_laboral_count': 1,
    }
    apply_to_badge_ctx(ctx, user)
    assert ctx['doc_errores'] == 0
    assert ctx['doc_avisos'] == 0
    assert ctx['cert_entrantes'] == 5
    assert ctx['unread_logs_count'] == 0
    assert ctx['pending_notifications'] == 4
    assert ctx['unread_laboral_count'] == 1


def test_save_prefs_from_form(session, tenant_soltec, company_internal, user_admin, app):
    from app.models import User
    from app.services.ui_notif_prefs_service import get_prefs, save_prefs

    schema = tenant_soltec.schema_name
    session.execute(text(f'SET search_path TO {schema}'))
    uid = user_admin.id
    form = MultiDict([
        ('ui_notif__documentacion', '1'),
        ('ui_notif__solicitudes', '1'),
    ])
    with app.app_context():
        session.execute(text(f'SET search_path TO {schema}'))
        user = User.query.get(uid)
        save_prefs(user, form=form)

    session.execute(text(f'SET search_path TO {schema}'))
    user = User.query.get(uid)
    prefs = get_prefs(user)
    assert prefs['documentacion'] is True
    assert prefs['solicitudes'] is True
    assert prefs['certificacion'] is False
    assert prefs['logs'] is False


def test_is_enabled_hides_ficha_badges():
    """company_panel usa is_enabled para docs/cert."""
    from app.services.ui_notif_prefs_service import is_enabled

    user = SimpleNamespace(ui_notif_prefs={'documentacion': False, 'certificacion': True})
    assert is_enabled(user, 'documentacion') is False
    assert is_enabled(user, 'certificacion') is True
