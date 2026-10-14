"""Tests del sistema de valoraciones actitud/conocimiento 0–5."""
import uuid

from sqlalchemy import text

from app.models import Obra, Rating, User, ROLE_OPERARIO
from app.services.rating_service import (
    composite_score,
    parse_rating_payload,
    rating_display_score,
    rating_is_v2,
    resolve_obra_id,
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


def test_resolve_obra_id_optional(app, session, tenant_soltec):
    session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
    assert resolve_obra_id(None) is None
    assert resolve_obra_id('') is None
    o = Obra(nombre='Obra Rating', codigo=_uid('OR')[:8], estado='En Curso', is_deleted=False)
    session.add(o)
    session.flush()
    assert resolve_obra_id(o.id) == o.id
    try:
        resolve_obra_id(999999)
        assert False, 'expected ValueError'
    except ValueError:
        pass


def test_obras_valoracion_solo_participadas(app, session, tenant_soltec):
    from datetime import date, datetime, time
    from app.models import Asignacion, RegistroFichaje, ROLE_OPERARIO
    from app.services.rating_service import obras_participadas_usuario, resolve_obra_id

    session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
    dni = _uid('OP')
    u = User(
        name='P', lastname='Art', email=f'{dni.lower()}@test.com', dni=dni,
        role=ROLE_OPERARIO, active=True, password_hash='x',
    )
    o_si = Obra(nombre='Con Fichaje', codigo=_uid('CF')[:8], estado='En Curso', is_deleted=False)
    o_asig = Obra(nombre='Con Asig', codigo=_uid('CA')[:8], estado='En Curso', is_deleted=False)
    o_no = Obra(nombre='Sin Nada', codigo=_uid('SN')[:8], estado='En Curso', is_deleted=False)
    session.add_all([u, o_si, o_asig, o_no])
    session.flush()
    dia = date(2026, 10, 1)
    session.add(RegistroFichaje(
        user_id=u.id, obra_real_id=o_si.id, fecha=dia,
        check_in=datetime.combine(dia, time(8, 0)),
        check_out=datetime.combine(dia, time(16, 0)),
        estado='Correcto',
    ))
    session.add(Asignacion(user_id=u.id, obra_id=o_asig.id, fecha=dia))
    session.flush()

    obras = obras_participadas_usuario(u.id)
    ids = {o.id for o in obras}
    assert o_si.id in ids
    assert o_asig.id in ids
    assert o_no.id not in ids

    assert resolve_obra_id(o_si.id, user_id=u.id) == o_si.id
    try:
        resolve_obra_id(o_no.id, user_id=u.id)
        assert False, 'expected ValueError'
    except ValueError as e:
        assert 'participado' in str(e).lower()


def test_rating_guarda_obra(app, session, tenant_soltec):
    session.execute(text(f"SET search_path TO {tenant_soltec.schema_name}"))
    dni = _uid('RO')
    u = User(
        name='R', lastname='Obra', email=f'{dni.lower()}@test.com', dni=dni,
        role=ROLE_OPERARIO, active=True, password_hash='x',
    )
    o = Obra(nombre='Tajo Norte', codigo=_uid('TN')[:8], estado='En Curso', is_deleted=False)
    session.add_all([u, o])
    session.flush()
    r = Rating(
        user_id=u.id, created_by_id=u.id, obra_id=o.id,
        score=4.0, actitud=4, conocimiento=4, reason='Buen trabajo en tajo',
        is_active=True,
    )
    session.add(r)
    session.flush()
    session.refresh(r)
    assert r.obra_id == o.id
    assert r.obra.nombre == 'Tajo Norte'
