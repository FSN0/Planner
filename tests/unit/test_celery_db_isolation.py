"""Aislamiento DB en workers Celery (search_path + cleanup)."""
from unittest.mock import MagicMock, patch

import pytest

from app.celery_worker import _cleanup_db_session, _set_search_path


def test_set_search_path_incluye_public(app):
    with app.app_context():
        with patch('app.celery_worker.db.session.execute') as execute:
            _set_search_path('tenant_soltec')
    sql = str(execute.call_args[0][0])
    assert 'tenant_soltec' in sql
    assert 'public' in sql


def test_set_search_path_public_solo(app):
    with app.app_context():
        with patch('app.celery_worker.db.session.execute') as execute:
            _set_search_path('public')
    sql = str(execute.call_args[0][0])
    assert sql.strip().endswith('TO public') or 'TO public' in sql
    assert 'tenant_' not in sql


def test_set_search_path_rechaza_schema_inseguro(app):
    with app.app_context():
        with pytest.raises(ValueError):
            _set_search_path('tenant; drop table users')


def test_cleanup_dispose_si_rollback_falla(app):
    import app.celery_worker as cw

    with app.app_context():
        fake_db = MagicMock()
        fake_db.session.rollback.side_effect = Exception('conn broken')
        with patch.object(cw, 'db', fake_db):
            _cleanup_db_session()
        fake_db.engine.dispose.assert_called_once()
