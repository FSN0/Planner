"""Matriz de notificaciones: modos off / immediate / debounce."""
from datetime import timedelta
from unittest.mock import patch

from sqlalchemy import text
from werkzeug.security import generate_password_hash


def test_catalog_has_business_and_access_events():
    from app.services.notification_catalog import event_keys, MODE_DEBOUNCE, MODE_IMMEDIATE, get_event
    keys = set(event_keys())
    assert 'asignacion' in keys
    assert 'desvio_fichaje' in keys
    assert 'acceso_pin' in keys
    assert 'hora_corte_reporte' in keys
    assert 'cert_pendiente' in keys
    assert 'cert_aceptada' in keys
    assert 'cert_rechazada' in keys
    assert 'cert_retirada' in keys
    assert get_event('asignacion')[3] == MODE_DEBOUNCE
    assert get_event('acceso_pin')[3] == MODE_IMMEDIATE
    assert get_event('cert_pendiente')[3] == MODE_IMMEDIATE


def test_legacy_key_normalizes():
    from app.services.notification_catalog import normalize_event_key
    assert normalize_event_key('email_asignacion') == 'asignacion'
    assert normalize_event_key('sol_concreta') == 'sol_concreta'


def _make_admin(session, tenant_soltec, company_internal, email, dni):
    from app.models import User, ROLE_ADMIN
    session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
    admin = User(
        email=email,
        password_hash=generate_password_hash('x'),
        role=ROLE_ADMIN,
        name='Admin',
        lastname='Notif',
        dni=dni,
        company_id=company_internal.id,
        active=True,
        email_verified=True,
    )
    session.add(admin)
    session.commit()
    return admin


def test_dispatch_off_sends_nothing(session, tenant_soltec, company_internal, app):
    from app.services.notification_dispatch_service import (
        set_event_settings,
        dispatch_notification,
        ensure_notif_queue_table,
    )

    ensure_notif_queue_table()
    admin = _make_admin(session, tenant_soltec, company_internal, 'admin-off@test.com', '90000001A')
    set_event_settings('asignacion', 'off', ['admin'])

    with app.app_context():
        with patch('app.services.email_service.send_email') as send:
            ok = dispatch_notification(
                'asignacion',
                subject='Test',
                body='Cuerpo',
                users=[admin],
            )
            assert ok is False
            send.assert_not_called()


def test_dispatch_immediate_sends(session, tenant_soltec, company_internal, app):
    from app.services.notification_dispatch_service import (
        set_event_settings,
        dispatch_notification,
        ensure_notif_queue_table,
    )

    ensure_notif_queue_table()
    admin = _make_admin(session, tenant_soltec, company_internal, 'admin-imm@test.com', '90000002B')
    set_event_settings('asignacion', 'immediate', ['admin'])

    with app.app_context():
        with patch('app.services.email_service.send_email', return_value=True) as send:
            ok = dispatch_notification(
                'asignacion',
                subject='Asig',
                body='Body',
                users=[admin],
            )
            assert ok is True
            send.assert_called_once()
            assert send.call_args[0][0] == 'Asig'
            assert 'admin-imm@test.com' in send.call_args[0][1]


def test_dispatch_debounce_enqueues(session, tenant_soltec, company_internal, app):
    from app.models import EmailNotifQueue
    from app.services.notification_dispatch_service import (
        set_event_settings,
        dispatch_notification,
        ensure_notif_queue_table,
        flush_debounce_due,
        get_debounce_minutes,
    )
    from app.services.config_service import set_tenant_config
    from app.services.notification_catalog import CONFIG_DEBOUNCE_MINUTES

    ensure_notif_queue_table()
    admin = _make_admin(session, tenant_soltec, company_internal, 'admin-deb@test.com', '90000003C')
    set_tenant_config(CONFIG_DEBOUNCE_MINUTES, '15')
    set_event_settings('asignacion', 'debounce', ['admin'])

    with app.app_context():
        with patch('app.services.email_service.send_email', return_value=True) as send:
            ok = dispatch_notification(
                'asignacion',
                subject='A1',
                body='B1',
                summary='S1',
                users=[admin],
                batch_key='test-batch',
            )
            assert ok is True
            send.assert_not_called()
            row = EmailNotifQueue.query.filter_by(event_key='asignacion').first()
            assert row is not None
            assert row.mode == 'debounce'
            assert len((row.payload or {}).get('lines') or []) == 1

            assert flush_debounce_due() == 0
            send.assert_not_called()

            row.flush_after = row.flush_after - timedelta(minutes=get_debounce_minutes() + 1)
            session.add(row)
            session.commit()
            n = flush_debounce_due()
            assert n == 1
            send.assert_called_once()
            assert EmailNotifQueue.query.count() == 0
