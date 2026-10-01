"""Lectura de checkboxes del formulario de permisos."""
from app.services.permission_service import _checkbox_on


class _FakeForm(dict):
    def get(self, key, default=None):
        return super().get(key, default)


def test_checkbox_on_accepts_on():
    form = _FakeForm({'perm__tablero__r': 'on'})
    assert _checkbox_on(form, 'perm__tablero__r') is True
    assert _checkbox_on(form, 'perm__tablero__w') is False


def test_checkbox_on_accepts_true_variants():
    assert _checkbox_on(_FakeForm({'x': '1'}), 'x') is True
    assert _checkbox_on(_FakeForm({'x': 'yes'}), 'x') is True
    assert _checkbox_on(_FakeForm({'x': True}), 'x') is True


def test_checkbox_on_rejects_empty():
    assert _checkbox_on(_FakeForm({}), 'x') is False
    assert _checkbox_on(_FakeForm({'x': ''}), 'x') is False
    assert _checkbox_on(None, 'x') is False
