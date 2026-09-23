"""Tests de rendimiento/carga del planificador."""
import uuid

from sqlalchemy import text

from app.models import Rating, User, ROLE_OPERARIO
from app.admin.routes import _planificador_avg_ratings


def _uid(prefix='T'):
    return f'{prefix}{uuid.uuid4().hex[:8].upper()}'


def test_planificador_avg_ratings_empty(app):
    with app.app_context():
        assert _planificador_avg_ratings([]) == {}


def test_planificador_avg_ratings_batch(app, session, tenant_soltec, monkeypatch, user_admin):
    from app.admin import routes as admin_routes

    session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
    monkeypatch.setattr(admin_routes, 'current_user', user_admin)
    monkeypatch.setattr('app.services.tenant_modules.has_valoraciones', lambda: True)
    monkeypatch.setattr('app.services.permission_service.user_can', lambda *a, **k: True)

    d1, d2 = _uid('A'), _uid('B')
    u1 = User(
        name='A', lastname='One', email=f'{d1.lower()}@test.com', dni=d1,
        role=ROLE_OPERARIO, active=True, password_hash='x',
    )
    u2 = User(
        name='B', lastname='Two', email=f'{d2.lower()}@test.com', dni=d2,
        role=ROLE_OPERARIO, active=True, password_hash='x',
    )
    session.add_all([u1, u2])
    session.flush()
    session.add_all([
        Rating(user_id=u1.id, created_by_id=u1.id, score=2.0, actitud=2, conocimiento=2, is_active=True),
        Rating(user_id=u1.id, created_by_id=u1.id, score=4.0, actitud=4, conocimiento=4, is_active=True),
        Rating(user_id=u2.id, created_by_id=u2.id, score=1.0, actitud=1, conocimiento=None, is_active=True),
        Rating(user_id=u2.id, created_by_id=u2.id, score=10, is_active=False),
    ])
    session.commit()

    out = _planificador_avg_ratings([u1.id, u2.id])
    assert out[u1.id] == 3.0
    assert out[u2.id] == 1.0
