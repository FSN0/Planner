"""Tests de suplantación de sesión (admin → operario)."""
from sqlalchemy import text

from app.services.impersonation_service import (
    SESSION_IMPERSONATED_USER_KEY,
    SESSION_IMPERSONATOR_KEY,
    iniciar_impersonacion,
    reparar_sesion_impersonacion,
)


class TestImpersonationService:
    def test_iniciar_guarda_usuario_suplantado(
        self, app, session, tenant_soltec, user_admin, user_operario,
    ):
        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
        with app.test_request_context('/'):
            from flask import session as flask_session
            from flask_login import login_user

            flask_session['tenant_id'] = tenant_soltec.id
            login_user(user_admin, remember=True)
            ok, err = iniciar_impersonacion(user_admin, user_operario)
            assert ok is True
            assert err is None
            assert flask_session.get(SESSION_IMPERSONATOR_KEY) == user_admin.id
            assert flask_session.get(SESSION_IMPERSONATED_USER_KEY) == user_operario.id
            assert '_remember' not in flask_session

    def test_reparar_restaura_operario_si_sesion_vuelve_al_admin(
        self, app, session, tenant_soltec, user_admin, user_operario,
    ):
        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
        with app.test_request_context('/'):
            from flask import session as flask_session
            from flask_login import current_user, login_user

            flask_session['tenant_id'] = tenant_soltec.id
            login_user(user_admin, remember=True)
            iniciar_impersonacion(user_admin, user_operario)
            assert current_user.id == user_operario.id

            login_user(user_admin, remember=True)
            assert current_user.id == user_admin.id

            assert reparar_sesion_impersonacion() is True
            assert current_user.id == user_operario.id


class TestImpersonationHttp:
    def test_admin_impersona_y_abre_calendario_operario(
        self, authenticated_client, user_operario, tenant_soltec, session,
    ):
        session.execute(text(f'SET search_path TO {tenant_soltec.schema_name}'))
        resp = authenticated_client.post(
            f'/admin/impersonate/{user_operario.id}',
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
        assert '/fichaje/' in resp.headers.get('Location', '')

        cal = authenticated_client.get('/fichaje/calendario', follow_redirects=True)
        assert cal.status_code == 200
        body = cal.get_data(as_text=True)
        assert 'empleado-calendar' in body or 'Mi calendario' in body

        with authenticated_client.session_transaction() as sess:
            assert sess.get(SESSION_IMPERSONATOR_KEY)
            assert sess.get('_user_id') == str(user_operario.id)
