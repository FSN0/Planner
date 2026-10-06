# tests/unit/test_odoo_fichaje_metricas.py
"""Campos UD / MOD / Total HH / MOE en fichajes Odoo (Soltec)."""

from app.sync.adapters.odoo_soltec import Adapter


class _FakeAdapter(Adapter):
    def __init__(self):
        self.tenant_id = 1
        self._attendance_metric_cache = {}

    def _odoo_fields_get(self, model_name):
        assert model_name == 'hr.attendance'
        return {
            'employee_id': {'string': 'Employee'},
            'x_studio_ud': {'string': 'UD'},
            'x_studio_mod': {'string': 'MOD'},
            'total_hh': {'string': 'Total HH'},
            'x_studio_moe': {'string': 'MOE'},
        }


def test_attendance_metric_field_map_resolves_by_label():
    adapter = _FakeAdapter()
    mapping = adapter._attendance_metric_field_map('hr.attendance')
    assert mapping['odoo_ud'] == 'x_studio_ud'
    assert mapping['odoo_mod'] == 'x_studio_mod'
    assert mapping['odoo_total_hh'] == 'total_hh'
    assert mapping['odoo_moe'] == 'x_studio_moe'


def test_extract_attendance_metrics_parses_numbers():
    adapter = _FakeAdapter()
    metric_map = adapter._attendance_metric_field_map('hr.attendance')
    row = {
        'x_studio_ud': 1.5,
        'x_studio_mod': '2',
        'total_hh': False,
        'x_studio_moe': None,
    }
    metrics = adapter._extract_attendance_metrics(row, metric_map)
    assert metrics['odoo_ud'] == 1.5
    assert metrics['odoo_mod'] == 2.0
    assert metrics['odoo_total_hh'] is None
    assert metrics['odoo_moe'] is None


def test_append_attendance_fichaje_includes_metrics():
    adapter = _FakeAdapter()
    metric_map = adapter._attendance_metric_field_map('hr.attendance')
    dest = []
    adapter._append_attendance_fichaje(
        dest,
        {
            'id': 99,
            'employee_id': [7, 'Pepe'],
            'project_id': [3, 'Obra'],
            'write_uid': [1, 'Admin'],
            'check_in': '2026-09-02 08:00:00',
            'check_out': '2026-09-02 17:00:00',
            'note': False,
            'x_studio_ud': 1,
            'x_studio_mod': 0.5,
            'total_hh': 8,
            'x_studio_moe': 0.25,
            'x_studio_state': 'validated',
        },
        actor_field='employee_id',
        origen_modelo='hr.attendance',
        fecha_str='2026-09-02',
        metric_map=metric_map,
        estado_field='x_studio_state',
    )
    assert len(dest) == 1
    item = dest[0]
    assert item['odoo_ud'] == 1.0
    assert item['odoo_mod'] == 0.5
    assert item['odoo_total_hh'] == 8.0
    assert item['odoo_moe'] == 0.25
    assert item['estado_odoo'] == 'validado'


def test_estado_fichaje_field_prefers_studio_state():
    class _EstadoAdapter(_FakeAdapter):
        def _odoo_fields_get(self, model_name):
            return {
                'employee_id': {'string': 'Employee', 'type': 'many2one'},
                'x_studio_state': {
                    'string': 'Estado',
                    'type': 'selection',
                    'selection': [
                        ('draft', 'Borrador'),
                        ('validated', 'Validado'),
                        ('invoiced', 'Facturado'),
                    ],
                },
            }

    adapter = _EstadoAdapter()
    assert adapter._estado_fichaje_field('hr.attendance') == 'x_studio_state'


def test_estado_fichaje_field_por_etiqueta_sin_selection():
    class _EstadoAdapter(_FakeAdapter):
        def _odoo_fields_get(self, model_name):
            return {
                'x_studio_selection_field_abc': {
                    'string': 'Estado',
                    'type': 'selection',
                    'selection': [],
                },
            }

    adapter = _EstadoAdapter()
    assert adapter._estado_fichaje_field('hr.attendance') == 'x_studio_selection_field_abc'
