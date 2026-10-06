"""Reglas puras de documentación, horas y estados de fichaje."""
from datetime import date, datetime, time
from types import SimpleNamespace

from app.services.compliance_rules import (
    campo_estado_parece_fichaje,
    clasificar_aporte,
    email_es_real,
    es_aviso_documental,
    es_error_documental,
    horas_entre,
    normalizar_estado_odoo,
    propuestas_coinciden,
    sugerir_caducidad,
)


def test_email_real_rechaza_placeholders():
    assert email_es_real('yo@empresa.com')
    assert not email_es_real('ext_1@subcontrata.local')
    assert not email_es_real('cabc@pending.local')
    assert not email_es_real('a@local.signaplan')
    assert not email_es_real('')


def test_estado_odoo_por_etiqueta():
    assert normalizar_estado_odoo('Borrador') == 'borrador'
    assert normalizar_estado_odoo(['draft', 'Borrador']) == 'borrador'
    assert normalizar_estado_odoo('Validado') == 'validado'
    assert normalizar_estado_odoo('validated') == 'validado'
    assert normalizar_estado_odoo('Facturado') == 'facturado'
    assert normalizar_estado_odoo('invoiced') == 'facturado'
    assert normalizar_estado_odoo(False) is None
    assert normalizar_estado_odoo('otro') is None


def test_descubre_campo_con_los_tres_estados():
    assert campo_estado_parece_fichaje('x_estado', {
        'string': 'Estado fichaje',
        'type': 'selection',
        'selection': [
            ('draft', 'Borrador'),
            ('done', 'Validado'),
            ('invoiced', 'Facturado'),
        ],
    })
    assert campo_estado_parece_fichaje('x_studio_state', {
        'string': 'Status',
        'type': 'selection',
        'selection': [
            ('draft', 'Draft'),
            ('validated', 'Validated'),
            ('invoiced', 'Invoiced'),
        ],
    })
    assert campo_estado_parece_fichaje('state', {
        'string': 'State',
        'type': 'selection',
        'selection': [
            ('draft', 'Draft'),
            ('validated', 'Validated'),
            ('invoiced', 'Invoiced'),
        ],
    })
    # Studio: selection vacía en fields_get pero nombre claro
    assert campo_estado_parece_fichaje('x_studio_estado', {
        'string': 'Estado',
        'type': 'selection',
        'selection': [],
    })
    assert not campo_estado_parece_fichaje('state', {
        'string': 'Estado',
        'type': 'selection',
        'selection': [('draft', 'Borrador'), ('open', 'Abierto')],
    })
    assert not campo_estado_parece_fichaje('employee_state', {
        'string': 'Employee state',
        'type': 'selection',
        'selection': [],
    })


def test_caducidad_mensual_cae_en_el_dia_y_se_puede_pisar():
    assert sugerir_caducidad('mensual', 1, None, hoy=date(2026, 10, 5)) == date(2026, 11, 1)
    assert sugerir_caducidad('anual', 1, 3, hoy=date(2026, 10, 5)) == date(2027, 3, 1)
    assert sugerir_caducidad('ninguna', 1, None, hoy=date(2026, 10, 5)) is None
    assert sugerir_caducidad('mensual', 31, None, hoy=date(2026, 1, 31)) == date(2026, 2, 28)


def test_horas_y_propuestas_vacias_no_coinciden():
    assert horas_entre(time(8, 0), time(12, 30)) == __import__('decimal').Decimal('4.50')
    assert horas_entre(time(18, 0), time(8, 0)) is None
    linea = {
        'user_id': 1, 'obra_id': 2, 'fecha': date(2026, 10, 1),
        'horas': '8.00', 'precio_hora': '12.50',
    }
    assert propuestas_coinciden([linea], [dict(linea)])
    assert not propuestas_coinciden([], [])
    vacia = dict(linea, horas=None)
    assert not propuestas_coinciden([vacia], [vacia])


def test_bolita_y_admiracion():
    hoy = date(2026, 10, 5)
    assert clasificar_aporte(None, obligatorio=True, hoy=hoy, aviso_dias=15) == 'falta'
    assert es_error_documental('pendiente_validar')
    aporte = SimpleNamespace(estado='validado', caduca_el=date(2026, 10, 10), aceptado_caducado=False)
    assert clasificar_aporte(aporte, obligatorio=True, hoy=hoy, aviso_dias=15) == 'por_caducar'
    assert es_aviso_documental('por_caducar')
    caducado = SimpleNamespace(estado='validado', caduca_el=date(2026, 10, 1), aceptado_caducado=True)
    assert clasificar_aporte(caducado, obligatorio=True, hoy=hoy, aviso_dias=15) == 'ok'


def test_categoria_admin_solo_si_el_contacto_la_tiene():
    from app.sync.adapters.odoo_soltec import Adapter
    assert Adapter._category_id_set([9, [4, 'Admin']]) == {9, 4}
    assert Adapter._category_id_set(None) == set()
    admin = {9}
    assert not (Adapter._category_id_set(None) & admin)
    assert Adapter._category_id_set([9]) & admin
