"""Tests del sistema de valoraciones actitud/conocimiento 0–5."""
import uuid

from sqlalchemy import text

from app.models import Rating, User, ROLE_OPERARIO
from app.services.rating_service import (
    composite_score,
    parse_rating_payload,
    rating_display_score,
    rating_is_v2,
)


def _uid(prefix='T'):
    return f'{prefix}{uuid.uuid4().hex[:8].upper()}'


def test_parse_requires_at_least_one_dimension():
    try:
        parse_rating_payload({})
        assert False, 'expected ValueError'
    except ValueError:
        pass


def test_parse_only_actitud():
    a, c, media, reason = parse_rating_payload({'actitud': 4, 'reason': 'ok'})
    assert a == 4 and c is None and media == 4.0 and reason == 'ok'


def test_parse_both_dimensions_media():
    a, c, media, reason = parse_rating_payload({'actitud': 3, 'conocimiento': 5, 'reason': 'bien'})
    assert a == 3 and c == 5 and media == 4.0 and reason == 'bien'


def test_parse_requires_reason():
    try:
        parse_rating_payload({'actitud': 4, 'reason': '  '})
        assert False, 'expected ValueError'
    except ValueError as e:
        assert 'motivo' in str(e).lower()


def test_composite_score_single():
    assert composite_score(None, 2) == 2.0
    assert composite_score(5, None) == 5.0


def test_reputation_ignores_legacy(app, session, tenant_soltec):
    session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
    dni = _uid('R')
    u = User(
        name='A', lastname='One', email=f'{dni.lower()}@test.com', dni=dni,
        role=ROLE_OPERARIO, active=True, password_hash='x',
    )
    session.add(u)
    session.flush()
    session.add_all([
        Rating(user_id=u.id, created_by_id=u.id, score=-2, is_active=True),
        Rating(user_id=u.id, created_by_id=u.id, score=4.0, actitud=3, conocimiento=5, is_active=True),
        Rating(user_id=u.id, created_by_id=u.id, score=2.0, actitud=2, conocimiento=None, is_active=True),
        Rating(user_id=u.id, created_by_id=u.id, score=5.0, actitud=5, conocimiento=5, is_active=False),
    ])
    session.flush()
    # En la misma sesión (sin commit) el backref ya tiene las valoraciones.
    assert u.reputation_count == 2
    assert u.reputation_score == 3.0  # (4.0 + 2.0) / 2


def test_planificador_avg_ratings_v2_only(app, session, tenant_soltec, monkeypatch, user_admin):
    from app.admin import routes as admin_routes
    from app.admin.routes import _planificador_avg_ratings

    session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
    monkeypatch.setattr(admin_routes, 'current_user', user_admin)
    monkeypatch.setattr('app.services.tenant_modules.has_valoraciones', lambda: True)
    monkeypatch.setattr('app.services.permission_service.user_can', lambda *a, **k: True)

    d1, d2 = _uid('P1'), _uid('P2')
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
        Rating(user_id=u1.id, created_by_id=u1.id, score=4.0, actitud=4, conocimiento=4, is_active=True),
        Rating(user_id=u1.id, created_by_id=u1.id, score=2.0, actitud=2, conocimiento=2, is_active=True),
        Rating(user_id=u2.id, created_by_id=u2.id, score=-1, is_active=True),  # legacy: excluded
    ])
    session.commit()

    out = _planificador_avg_ratings([u1.id, u2.id])
    assert out[u1.id] == 3.0
    assert u2.id not in out


def test_rating_is_v2_helpers():
    legacy = Rating(score=-1, actitud=None, conocimiento=None)
    v2 = Rating(score=3.5, actitud=3, conocimiento=4)
    assert not rating_is_v2(legacy)
    assert rating_is_v2(v2)
    assert rating_display_score(v2) == 3.5
