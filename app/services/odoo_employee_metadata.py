"""Metadatos Odoo en User.external_ids (departamento al importar, origen)."""
from __future__ import annotations

from sqlalchemy.orm.attributes import flag_modified

IMPORT_SOURCE_LABELS = {
    'sync_empleados_auto': 'Sync automática (empleados)',
    'sync_empleados_manual': 'Sync manual (empleados)',
    'conciliacion': 'Conciliación de personal',
    'manual': 'Alta manual',
}


def department_label_from_odoo_m2o(raw) -> str:
    if isinstance(raw, (list, tuple)) and len(raw) > 1:
        return str(raw[1] or '').strip()
    return ''


def user_odoo_model(user) -> str:
    """Modelo Odoo del vínculo principal: hr.employee o res.partner."""
    if not user:
        return 'hr.employee'
    ext = user.external_ids or {}
    model = (ext.get('odoo_model') or '').strip()
    if model in ('hr.employee', 'res.partner'):
        return model
    # Legacy sin odoo_model: externos/subcontratas → partner; resto → empleado.
    if getattr(user, 'tipo_empleado', None) == 'EXTERNO':
        return 'res.partner'
    return 'hr.employee'


def is_odoo_partner_link(user) -> bool:
    return user_odoo_model(user) == 'res.partner'


def import_fields_for_user(user) -> dict:
    ext = dict((user.external_ids or {}) if user else {})
    imp = (ext.get('odoo_department_import') or '').strip()
    registered = (ext.get('odoo_department') or '').strip()
    src = (ext.get('odoo_import_source') or '').strip()
    model = user_odoo_model(user)
    return {
        'departamento_importacion': imp,
        'departamento_registrado': registered,
        'import_source': src,
        'import_source_label': IMPORT_SOURCE_LABELS.get(src, src or ''),
        'odoo_model': model,
        'odoo_vinculo': (
            'Contacto Odoo (res.partner)'
            if model == 'res.partner'
            else 'Empleado Odoo (hr.employee)'
        ),
    }


def apply_odoo_employee_external_ids(
    user,
    odoo_id,
    *,
    department: str | None = None,
    barcode: str | None = None,
    import_source: str | None = None,
) -> None:
    ext = dict(user.external_ids or {})
    ext['odoo'] = str(odoo_id)
    ext['odoo_model'] = 'hr.employee'
    if barcode:
        ext['barcode'] = str(barcode).strip()
    dept = (department or '').strip()
    if dept:
        ext['odoo_department'] = dept
        if not (ext.get('odoo_department_import') or '').strip():
            ext['odoo_department_import'] = dept
    if import_source:
        ext['odoo_import_source'] = import_source
    user.external_ids = ext
    flag_modified(user, 'external_ids')


def build_external_ids_for_new_employee(
    odoo_id,
    *,
    department: str | None = None,
    barcode: str | None = None,
    import_source: str | None = None,
) -> dict:
    ext: dict = {'odoo': str(odoo_id), 'odoo_model': 'hr.employee'}
    if barcode:
        ext['barcode'] = str(barcode).strip()
    dept = (department or '').strip()
    if dept:
        ext['odoo_department'] = dept
        ext['odoo_department_import'] = dept
    if import_source:
        ext['odoo_import_source'] = import_source
    return ext
