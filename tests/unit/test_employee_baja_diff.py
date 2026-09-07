from app.services.employee_baja_service import (
    desactivados_aplicables,
    local_ids_activos_en_diff,
)


def test_local_ids_activos_en_diff_empleados():
    diff = {
        'nuevos': [],
        'actualizados': [{'local_id': 7, 'odoo_id': 200}],
        'sin_cambios': [{'local_id': 8}],
        'desactivados': [{'local_id': 7, 'odoo_id': 100}],
    }
    assert local_ids_activos_en_diff(diff) == {7, 8}


def test_desactivados_aplicables_omite_quien_sigue_activo_en_el_diff():
    diff = {
        'nuevos': [],
        'actualizados': [{'local_id': 7, 'odoo_id': 200}],
        'sin_cambios': [],
        'desactivados': [
            {'local_id': 7, 'odoo_id': 100},
            {'local_id': 9, 'odoo_id': 300},
        ],
    }
    aplicables = desactivados_aplicables(diff)
    assert [d['local_id'] for d in aplicables] == [9]
