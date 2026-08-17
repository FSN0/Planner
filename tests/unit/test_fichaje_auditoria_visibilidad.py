from types import SimpleNamespace

from flask import g

from app.services.fichaje_operario_service import tenant_muestra_auditoria_fichajes


def test_odoo_muestra_auditoria_aunque_no_haya_pwa(app):
    with app.app_context():
        g.current_tenant = SimpleNamespace(modulos_activos={'odoo': True})
        assert tenant_muestra_auditoria_fichajes() is True


def test_sin_odoo_ni_modulo_no_muestra_auditoria(app):
    with app.app_context():
        g.current_tenant = SimpleNamespace(modulos_activos={})
        assert tenant_muestra_auditoria_fichajes() is False


def test_modulo_fichaje_respeta_interruptor(app, monkeypatch):
    with app.app_context():
        g.current_tenant = SimpleNamespace(modulos_activos={'fichaje_operario': True})
        monkeypatch.setattr(
            'app.services.fichaje_operario_service.get_tenant_config',
            lambda *a, **k: 'True',
        )
        assert tenant_muestra_auditoria_fichajes() is True
        monkeypatch.setattr(
            'app.services.fichaje_operario_service.get_tenant_config',
            lambda *a, **k: 'False',
        )
        assert tenant_muestra_auditoria_fichajes() is False
