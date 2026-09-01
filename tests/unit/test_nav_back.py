# tests/unit/test_nav_back.py
from app.utils.nav_back import is_safe_back_url, resolve_back_url


def test_safe_back_accepts_admin_with_hash():
    assert is_safe_back_url('/admin/personal#operarios')


def test_safe_back_rejects_logout():
    assert not is_safe_back_url('/auth/logout')


def test_resolve_back_prefers_query(app, client):
    with app.test_request_context('/admin/worker_panel/1?back=%2Fadmin%2Fpersonal%23operarios'):
        assert resolve_back_url('admin.personal') == '/admin/personal#operarios'
