"""Tests de rendimiento/carga del planificador."""
from app.models import Rating, User, ROLE_OPERARIO
from app.admin.routes import _planificador_avg_ratings


def test_planificador_avg_ratings_empty(app):
    with app.app_context():
        assert _planificador_avg_ratings([]) == {}


def test_planificador_avg_ratings_batch(app, db_session):
    with app.app_context():
        u1 = User(
            name='A', lastname='One', email='a1@test.com', dni='11111111A',
            role=ROLE_OPERARIO, active=True, password_hash='x',
        )
        u2 = User(
            name='B', lastname='Two', email='b2@test.com', dni='22222222B',
            role=ROLE_OPERARIO, active=True, password_hash='x',
        )
        db_session.add_all([u1, u2])
        db_session.flush()
        db_session.add_all([
            Rating(user_id=u1.id, created_by_id=u1.id, score=2, is_active=True),
            Rating(user_id=u1.id, created_by_id=u1.id, score=4, is_active=True),
            Rating(user_id=u2.id, created_by_id=u2.id, score=-1, is_active=True),
            Rating(user_id=u2.id, created_by_id=u2.id, score=10, is_active=False),
        ])
        db_session.commit()

        out = _planificador_avg_ratings([u1.id, u2.id])
        assert out[u1.id] == 3.0
        assert out[u2.id] == -1.0
