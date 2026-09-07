#!/usr/bin/env python3
"""Harvest every i18n msgid used in the app and diff against existing catalogs."""

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, 'app')
I18N = os.path.join(APP, 'i18n')

# ── regex patterns ──
PY_PATTERNS = [
    # _('...') _("...")  translate('...') translate("...")  _tf('...') _tf("...")
    re.compile(r"""(?:(?<!\w)_|translate|_tf)\(\s*'((?:[^'\\]|\\.)*)'\s*[,)]"""),
    re.compile(r"""(?:(?<!\w)_|translate|_tf)\(\s*"((?:[^"\\]|\\.)*)"\s*[,)]"""),
    # flash(translate('...'))
    re.compile(r"""flash\(\s*(?:translate|_)\(\s*'((?:[^'\\]|\\.)*)'\s*\)"""),
    re.compile(r"""flash\(\s*(?:translate|_)\(\s*"((?:[^"\\]|\\.)*)"\s*\)"""),
]

JS_PATTERNS = [
    re.compile(r"""(?:SP_T|(?<![.\w])t)\(\s*'((?:[^'\\]|\\.)*)'\s*\)"""),
    re.compile(r"""(?:SP_T|(?<![.\w])t)\(\s*"((?:[^"\\]|\\.)*)"\s*\)"""),
]

HTML_PATTERNS = [
    re.compile(r"""(?:_|translate|t|SP_T)\(\s*'((?:[^'\\]|\\.)*)'\s*\)"""),
    re.compile(r"""(?:_|translate|t|SP_T)\(\s*"((?:[^"\\]|\\.)*)"\s*\)"""),
]

SKIP_PY = {
    '_get_raw', '_set_raw', '_build_user_indexes', '_match_driver_user',
    '_norm_name', '_asignaciones_empresa_q', '_month_bounds', '_tf',
    '_parse_fecha', '_empresa_informante', '_nombre_completo',
    '_obra_del_dia', '_pausas_del_dia', '_SafeMap', '_reload_catalogs',
    '_load_json', '_RETURN_TO_ENDPOINTS', '_create_user_default_role',
    '_cookie_domain', '_marketing_url_locale', '_import_session_key',
    '_load_import_path', '_apply_import_nav_context', '_exige_email_verificado',
    '__missing__', '__init__',
}


def harvest_file(filepath, patterns, skip_set=None):
    keys = set()
    try:
        with open(filepath, encoding='utf-8') as f:
            content = f.read()
    except Exception:
        return keys

    for pat in patterns:
        for m in pat.finditer(content):
            key = m.group(1)
            # unescape
            key = key.replace("\\'", "'").replace('\\"', '"').replace('\\n', '\n')
            if not key or len(key) < 1:
                continue
            # skip obvious non-translations
            if key.startswith('.') or key.startswith('#'):
                continue
            if key in ('', ' ', '\n'):
                continue
            keys.add(key)
    return keys


def walk_harvest(directory, ext, patterns, skip_set=None):
    keys = set()
    for dirpath, _, filenames in os.walk(directory):
        for fn in filenames:
            if fn.endswith(ext):
                fp = os.path.join(dirpath, fn)
                keys |= harvest_file(fp, patterns, skip_set)
    return keys


def load_json(path):
    if not os.path.isfile(path):
        return {}
    with open(path, encoding='utf-8') as f:
        return json.load(f)




def main_to_file():
    """Write results to a JSON file for further processing."""
    all_keys, en_all, pt_all, fr_all = harvest_all()

    missing_en = sorted(k for k in all_keys if k not in en_all)
    missing_pt = sorted(k for k in all_keys if k not in pt_all)
    missing_fr = sorted(k for k in all_keys if k not in fr_all)

    out = {
        'total_harvested': len(all_keys),
        'missing_en_count': len(missing_en),
        'missing_pt_count': len(missing_pt),
        'missing_fr_count': len(missing_fr),
        'missing_en': missing_en,
        'missing_pt': missing_pt,
        'missing_fr': missing_fr,
    }
    outpath = os.path.join(I18N, '_missing_report.json')
    with open(outpath, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    sys.stdout.buffer.write(f"Wrote {outpath}\n".encode('utf-8'))
    sys.stdout.buffer.write(f"Total: {len(all_keys)}, EN missing: {len(missing_en)}, PT: {len(missing_pt)}, FR: {len(missing_fr)}\n".encode('utf-8'))


def harvest_all():
    py_keys = walk_harvest(APP, '.py', PY_PATTERNS, SKIP_PY)
    js_keys = walk_harvest(os.path.join(APP, 'static', 'js'), '.js', JS_PATTERNS)
    html_keys = walk_harvest(os.path.join(APP, 'templates'), '.html', HTML_PATTERNS)

    all_keys = py_keys | js_keys | html_keys

    runtime_panel = [
        'En uso hoy', 'Libre hoy', 'Días en uso (30d)', 'Planificado + Odoo',
        'Conductores (30d)', 'Personas distintas', 'Odómetro Odoo',
        'Sin conductor Odoo', 'Solicitudes abiertas', 'Pendientes / en proceso',
        'Operarios hoy', 'Cupo {n}', 'Sin límite definido', 'Empresas hoy',
        'Subcontratas activas', '{n} plazas pendientes', 'Sin plazas genéricas',
        'Días-persona mes', '{n} operarios distintos', 'Próx. 7 días',
        'Asignaciones planificadas', 'Fichajes hoy', '{n} incidencias',
        'Sin registros', 'Sin incidencias', 'Plazo obra',
        'días restantes', 'días desde cierre',
        'Asignado hoy', '{n} obra(s)', 'Días asignados mes',
        'En calendario actual', 'Obras (30 días)', '{n} días multi-obra',
        'Sin pluriempleo', 'Fichajes 30 días', 'Sin datos', 'Correctos',
        'Reputación', '{n} valoraciones activas', 'Solicitudes',
        'Abiertas vinculadas', 'Próxima asignación', 'Obra',
        'Plantilla', '{n} activos', 'En obra hoy', '{pct}% de activos',
        'Sin activos', 'Con personal asignado',
        'Intervenciones 30d', '{n} días-persona este mes',
        'Valoración media', '{n} valoraciones', 'Sin valoraciones',
        'Abiertas de la empresa', 'Incidencias fichaje', 'Últimos 30 días',
        'Vehículo #{n}', '{name} (no está en el programa)',
        'Uso Odoo (sin conductor)',
    ]
    all_keys |= set(runtime_panel)

    sync_labels = [
        'Obras / Proyectos', 'Personal interno', 'Subcontratas',
        'Ausencias / Time Off', 'Fichajes / asistencia', 'Vehículos / Flota',
        'Importa proyectos BIM activos desde Odoo (bim.project).',
        'Sincroniza empleados internos (hr.employee) con departamentos autorizados.',
        'Importa empresas subcontrata y sus contactos externos.',
        'Importa vacaciones, bajas, permisos y puentes (hr.leave) con su tipo y estado.',
        'Cruza fichajes Odoo con la planificación. En vivo durante el día y revisión retrospectiva nocturna.',
        'Sincroniza flota (fleet.vehicle) y odómetros diarios. Auditoría informativa plan vs conductor Odoo.',
        'Diario a las 03:00',
        'Cada 30 min (07:00–19:00) + retrospectivo diario',
        'Cada 60 min (07:00–19:00) + retrospectivo diario',
    ]
    all_keys |= set(sync_labels)

    import_keys = [
        'Importar obras',
        'Sube un Excel o CSV para crear varias obras de una vez.',
        'Desde aquí cargas de golpe el listado de obras de tu empresa. No hace falta crearlas una a una: el asistente lee el fichero, mapea las columnas y te muestra una vista previa antes de guardar.',
        'Obligatorio: Nombre. Opcional: Código, Dirección, Fechas.',
        'Volver al listado',
        'Ir a obras',
        'Importar personal',
        'Sube un Excel o CSV para dar de alta usuarios.',
        'Carga de golpe tu plantilla (interna o externa). Revisarás el mapeo y una vista previa antes de crear a nadie.',
        'Obligatorio: Nombre, Apellidos, DNI, Email. Recomendado: Empresa (externos), Rol.',
        'Volver a personal',
        'Ir a personal',
        'Importar subcontratas',
        'Sube un Excel o CSV para dar de alta empresas externas.',
        'Da de alta las empresas externas / subcontratas con las que trabajas. Así podrás vincular personal externo a cada una.',
        'Obligatorio: Nombre. Opcional: NIF, Código, Gremio, Email, Descripción.',
        'Volver a subcontratas',
        'Ir a subcontratas',
    ]
    all_keys |= set(import_keys)

    import_help_htmls = [
        '<ul>\n  <li><strong>Obligatorio:</strong> una columna de <strong>Nombre</strong> de la obra.</li>\n  <li><strong>Opcionales:</strong> Código, Dirección, Fecha de inicio y Fecha de fin.</li>\n  <li><strong>Sin fechas:</strong> se pone <strong>hoy</strong> como inicio y <strong>un año después</strong> como fin.\n      Si el Excel ya trae fechas (aunque sean del pasado), se respetan tal cual.</li>\n  <li><strong>Sin código:</strong> la obra se crea sin código (puedes asignarlo después en la ficha).</li>\n</ul>\n<p class="import-help-note">Formatos: .xlsx o .csv. En el siguiente paso podrás corregir el mapeo de columnas.</p>',
        '<ul>\n  <li><strong>Obligatorias:</strong> Nombre, Apellidos, DNI y Email.</li>\n  <li><strong>Recomendadas:</strong> Rol y, si son externos, Empresa.</li>\n  <li><strong>Empresa / subcontrata:</strong> en personal externo se busca o crea una empresa con ese nombre.\n      Si dos personas son de la misma subcontrata, el nombre debe ser <strong>exactamente igual</strong>.</li>\n  <li><strong>Sin rol:</strong> se asume operario. El PIN puedes activarlo después en Trabajadores.</li>\n</ul>\n<p class="import-help-note">Formatos: .xlsx o .csv. En el siguiente paso podrás corregir el mapeo.</p>',
        '<ul>\n  <li><strong>Obligatorio:</strong> Nombre de la subcontrata / empresa externa.</li>\n  <li><strong>Opcionales:</strong> NIF, Código, Gremio, Email, Descripción.</li>\n  <li><strong>Mismo nombre:</strong> si ya existe una empresa con ese nombre, la fila se marca como duplicada.\n      Usa siempre el mismo nombre para la misma subcontrata.</li>\n</ul>\n<p class="import-help-note">Formatos: .xlsx o .csv. En el siguiente paso podrás corregir el mapeo.</p>',
    ]
    all_keys |= set(import_help_htmls)

    role_keys = ['role.admin', 'role.jefe_obra', 'role.rrhh', 'role.operario', 'role.laboral']
    all_keys |= set(role_keys)

    fichaje_labels = [
        'Correcto', 'Correcto (auto)', 'Cambio de tajo', 'Conflicto', 'Paracaidista',
        'Ausencia', 'Pendiente', 'Retraso', 'Sin fichaje',
        'Corregido por RRHH / ERP', 'Exento (ausencia)',
        'Multi-obra cerrado', 'Resuelto (movido)', 'Resuelto (asignado)',
        'Resuelto (multi-obra)', 'Resuelto (ignorado)', 'Resuelto (falta)',
        'Resuelto (ausencia)', 'Resuelto / correcto', 'Sin datos',
    ]
    all_keys |= set(fichaje_labels)

    etiqueta_keys = [
        'Entrada', 'Salida', 'Inicio de pausa', 'Fin de pausa',
        'Anulación', 'Reimputación de obra', 'Conforme del trabajador',
    ]
    all_keys |= set(etiqueta_keys)

    month_keys = [
        'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
        'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre',
    ]
    all_keys |= set(month_keys)

    weekday_keys = ['DOM', 'LUN', 'MAR', 'MIÉ', 'JUE', 'VIE', 'SÁB']
    all_keys |= set(weekday_keys)

    # Load existing catalogs
    en_loc = load_json(os.path.join(I18N, 'locales', 'en.json'))
    pt_loc = load_json(os.path.join(I18N, 'locales', 'pt.json'))
    fr_loc = load_json(os.path.join(I18N, 'locales', 'fr.json'))
    en_ext = load_json(os.path.join(I18N, 'extra', 'en.json'))
    pt_ext = load_json(os.path.join(I18N, 'extra', 'pt.json'))
    fr_ext = load_json(os.path.join(I18N, 'extra', 'fr.json'))

    en_all = {**en_loc, **en_ext}
    pt_all = {**pt_loc, **pt_ext}
    fr_all = {**fr_loc, **fr_ext}

    return all_keys, en_all, pt_all, fr_all


if __name__ == '__main__':
    main_to_file()
