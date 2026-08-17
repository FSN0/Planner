# app/services/tour_catalog_service.py
#
# Academia: capítulos cortos con desbloqueo blando por umbrales de datos.

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from flask import g, has_app_context, url_for
from flask_login import current_user

from app.models import ROLE_OPERARIO, Obra, RegistroFichaje, User, Vehiculo
from app.services.config_service import get_tenant_config, set_tenant_config
from app.services.fichaje_operario_service import fichaje_operario_activo
from app.services.i18n_service import _
from app.services.onboarding_service import (
    import_tutorials_done,
    onboarding_marcado_completo,
    tenant_tiene_onboarding,
    tenant_tiene_registro_jornada,
)
from app.services.permission_service import user_can
from app.services.tenant_modules import has_auditoria_vehiculos

CONFIG_TOURS = 'academia_tours'
CONFIG_ONBOARDING_PATH = 'onboarding_path'  # guide | demo | skip

STATUS_LOCKED = 'locked'
STATUS_AVAILABLE = 'available'
STATUS_IN_PROGRESS = 'in_progress'
STATUS_DONE = 'done'

# Umbral del puente (vehículos NUNCA obligatorios) — para HACER los tutoriales básicos
BRIDGE_REQUIRES = {'obras': 3, 'operarios': 3}

# Umbral para VISUALIZAR el bloque «después de empezar» (vehículo no obligatorio)
CURRICULUM_VISIBLE_REQUIRES = {'obras': 1, 'operarios': 1}

# Capítulos en orden de sugerencia
TOUR_IDS = (
    'seed',
    'import',
    'demo',
    'tablero_basico',
    'planificador_multi',
    'fichajes',
    'flota',
    'coches_libres',
    'auditoria_vehiculos',
)

# Tutoriales básicos tras el puente (empezar a usar la herramienta)
SHARED_TOUR_IDS = (
    'tablero_basico',
    'planificador_multi',
    'fichajes',
    'flota',
)

# Sección siguiente (menos prioritaria; se ampliará más adelante)
ADVANCED_TOUR_IDS = (
    'coches_libres',
)


def _modulos():
    if not has_app_context():
        return {}
    tenant = getattr(g, 'current_tenant', None)
    return getattr(tenant, 'modulos_activos', {}) or {}


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).strftime('%Y-%m-%dT%H:%M:%S')


def tenant_metrics() -> dict[str, Any]:
    """Contadores baratos para umbrales de desbloqueo."""
    from app.services.demo_data_service import demo_activa

    obras = Obra.query.filter(Obra.is_deleted.is_(False)).count()
    operarios = User.query.filter_by(role=ROLE_OPERARIO, is_deleted=False).count()
    vehiculos = 0
    try:
        vehiculos = Vehiculo.query.filter_by(active=True).count()
    except Exception:
        try:
            vehiculos = Vehiculo.query.count()
        except Exception:
            vehiculos = 0
    fichajes = 0
    try:
        fichajes = RegistroFichaje.query.count()
    except Exception:
        fichajes = 0
    return {
        'obras': obras,
        'operarios': operarios,
        'vehiculos': vehiculos,
        'fichajes': fichajes,
        'fichaje_activo': bool(fichaje_operario_activo()),
        'has_odoo': bool(_modulos().get('odoo')),
        'has_registro_jornada': tenant_tiene_registro_jornada(),
        'has_flota_module': bool(_modulos().get('vehiculos', True)),
        'demo_activa': bool(demo_activa()),
    }


def _load_raw_progress() -> dict:
    raw = get_tenant_config(CONFIG_TOURS, default='{}') or '{}'
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    tours = data.get('tours') if isinstance(data.get('tours'), dict) else data
    if not isinstance(tours, dict):
        tours = {}
    out = {}
    for tid, entry in tours.items():
        if isinstance(entry, str):
            status = {
                'd': STATUS_DONE,
                'a': STATUS_AVAILABLE,
                'p': STATUS_IN_PROGRESS,
                'l': STATUS_LOCKED,
            }.get(entry, entry)
            out[tid] = {'status': status, 'seen_unlock': True}
        elif isinstance(entry, dict):
            normalized = dict(entry)
            if 'u' in normalized and 'seen_unlock' not in normalized:
                normalized['seen_unlock'] = bool(normalized.pop('u'))
            elif 'u' in normalized:
                normalized.pop('u', None)
            out[tid] = normalized
    return out


def _compact_tours(tours: dict) -> dict:
    """Solo capítulos con estado útil."""
    compact = {}
    for tid, entry in (tours or {}).items():
        if not isinstance(entry, dict):
            continue
        status = entry.get('status')
        if not status or status == STATUS_LOCKED:
            continue
        row = {'status': status}
        if entry.get('seen_unlock'):
            row['u'] = 1
        at = entry.get('at') or entry.get('unlocked_at') or entry.get('started_at')
        if at:
            row['at'] = str(at)[:19]
        compact[tid] = row
    return compact


def _save_progress(tours: dict) -> None:
    from app import db

    payload = json.dumps({'tours': _compact_tours(tours)}, ensure_ascii=False, separators=(',', ':'))
    try:
        set_tenant_config(CONFIG_TOURS, payload)
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        try:
            minimal = {}
            for tid, entry in (tours or {}).items():
                if isinstance(entry, dict) and entry.get('status') in (
                    STATUS_DONE, STATUS_AVAILABLE, STATUS_IN_PROGRESS,
                ):
                    minimal[tid] = {'status': entry['status']}
            set_tenant_config(
                CONFIG_TOURS,
                json.dumps({'tours': minimal}, ensure_ascii=False, separators=(',', ':')),
            )
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass


def catalog_definitions() -> list[dict]:
    """Catálogo estático (sin estado evaluado)."""
    return [
        {
            'id': 'seed',
            'phase': 0,
            'title': str(_('Guía interactiva')),
            'blurb': str(_('Alta de un trabajador, una obra y el ciclo de fichaje.')),
            'chapter_js': 'trabajadores',
            'entry_endpoint': 'admin.primeros_pasos',
            'entry_args': {'tour': 'start'},
            'module': 'primeros_pasos',
            'minutes': 8,
            'requires': {},
            'soft': True,
        },
        {
            'id': 'import',
            'phase': 0,
            'title': str(_('Importar desde Excel')),
            'blurb': str(_('Sube obras, personal o empresas con la guía de mapeo.')),
            'chapter_js': 'import',
            'entry_endpoint': 'admin.primeros_pasos',
            'entry_args': {'tour': 'import'},
            'module': 'primeros_pasos',
            'minutes': 6,
            'requires': {},
            'soft': True,
        },
        {
            'id': 'demo',
            'phase': 0,
            'title': str(_('Probar con datos de ejemplo')),
            'blurb': str(_('Rellena el tablero con datos de ejemplo para los tutoriales.')),
            'chapter_js': 'demo',
            'entry_endpoint': 'admin.primeros_pasos',
            'entry_args': {'focus': 'next', 'demo': '1'},
            'module': 'primeros_pasos',
            'minutes': 5,
            'requires': {},
            'soft': True,
        },
        {
            'id': 'tablero_basico',
            'phase': 1,
            'title': str(_('Tablero básico')),
            'blurb': str(_('Asigna gente a obras en el tablero y lee el día.')),
            'chapter_js': 'tablero_basico',
            'entry_endpoint': 'admin.obras_detailed',
            'entry_args': {'tour': 'tablero_basico', 'mode': 'solo'},
            'module': 'tablero',
            'minutes': 5,
            'requires': dict(BRIDGE_REQUIRES),
            'soft': True,
        },
        {
            'id': 'planificador_multi',
            'phase': 1,
            'title': str(_('Planificador')),
            'blurb': str(_('Planifica varias personas a varios días.')),
            'chapter_js': 'planificador_multi',
            'entry_endpoint': 'admin.planificador_jo',
            'entry_args': {'tour': 'planificador_multi', 'mode': 'solo'},
            'module': 'planificador',
            'minutes': 6,
            'requires': dict(BRIDGE_REQUIRES),
            'soft': True,
        },
        {
            'id': 'fichajes',
            'phase': 2,
            'title': str(_('Fichajes')),
            'blurb': str(_('PIN, fichar, registro de jornada y auditoría.')),
            'chapter_js': 'fichajes',
            # Quedarse en Primeros pasos: el tour ilumina Trabajadores en el menú
            'entry_endpoint': 'admin.primeros_pasos',
            'entry_args': {'tour': 'fichajes', 'mode': 'solo'},
            'module': 'auditoria_fichajes',
            'minutes': 12,
            'requires': {'fichaje_activo': True},
            'soft': True,
        },
        {
            'id': 'flota',
            'phase': 3,
            'title': str(_('Flota')),
            'blurb': str(_('Vehículos y asignación a obra o persona.')),
            'chapter_js': 'flota',
            'entry_endpoint': 'admin.vehiculos',
            'entry_args': {'tour': 'flota', 'mode': 'solo'},
            'module': 'vehiculos',
            'minutes': 5,
            'requires': {'vehiculos_or_module': True},
            'soft': True,
        },
        {
            'id': 'coches_libres',
            'phase': 4,
            'title': str(_('Coches libres')),
            'blurb': str(_('Lee la disponibilidad de la flota.')),
            'chapter_js': 'coches_libres',
            'entry_endpoint': 'admin.vehiculos_libres',
            'entry_args': {'tour': 'coches_libres', 'mode': 'solo'},
            'module': 'vehiculos_libres',
            'minutes': 3,
            'requires': {'vehiculos': 1},
            'soft': True,
        },
        {
            'id': 'auditoria_vehiculos',
            'phase': 4,
            'title': str(_('Auditoría de vehículos')),
            'blurb': str(_('Revisa odómetros y alertas de flota.')),
            'chapter_js': 'auditoria_vehiculos',
            'entry_endpoint': 'sync.auditoria_vehiculos',
            'entry_args': {'tour': 'auditoria_vehiculos', 'mode': 'solo'},
            'module': 'auditoria_vehiculos',
            'minutes': 4,
            'requires': {'odoo': True, 'vehiculos': 1},
            'soft': True,
        },
    ]


def _threshold_met(requires: dict, metrics: dict) -> tuple[bool, str]:
    """Devuelve (ok, mensaje_si_falta)."""
    if not requires:
        return True, ''
    if requires.get('obras') and metrics['obras'] < int(requires['obras']):
        return False, str(_('Necesitas al menos %(n)s obras.') % {'n': requires['obras']})
    if requires.get('operarios') and metrics['operarios'] < int(requires['operarios']):
        return False, str(_('Necesitas al menos %(n)s operarios.') % {'n': requires['operarios']})
    if requires.get('vehiculos') and metrics['vehiculos'] < int(requires['vehiculos']):
        return False, str(_('Necesitas al menos %(n)s vehículo(s).') % {'n': requires['vehiculos']})
    if requires.get('fichajes_or_activo'):
        if not (metrics['fichajes'] >= 1 or metrics['fichaje_activo']):
            return False, str(_('Activa el fichaje o registra al menos un fichaje.'))
    if requires.get('fichaje_activo') and not metrics.get('fichaje_activo'):
        return False, str(_('Esta sección solo aparece si activaste el fichaje de operarios.'))
    if requires.get('registro_jornada') and not metrics['has_registro_jornada']:
        return False, str(_('Este espacio no tiene registro de jornada.'))
    if requires.get('odoo') and not metrics['has_odoo']:
        return False, str(_('Este espacio no tiene sincronización Odoo.'))
    if requires.get('vehiculos_or_module'):
        if metrics['vehiculos'] < 1 and not metrics.get('has_flota_module', True):
            return False, str(_('Añade un vehículo o activa el módulo de flota.'))
    return True, ''


def _module_visible(module: str, user) -> bool:
    if not module:
        return True
    if module == 'primeros_pasos':
        return True
    if module == 'registro_jornada' and not tenant_tiene_registro_jornada():
        return False
    if module == 'auditoria_vehiculos' and not has_auditoria_vehiculos():
        return False
    try:
        return user_can(user, module, 'r')
    except Exception:
        return True


def _entry_url(defn: dict) -> str:
    try:
        return url_for(defn['entry_endpoint'], **(defn.get('entry_args') or {}))
    except Exception:
        return url_for('admin.primeros_pasos')


def _safe_url(endpoint: str, **kwargs) -> str:
    try:
        return url_for(endpoint, **kwargs)
    except Exception:
        try:
            return url_for('admin.primeros_pasos')
        except Exception:
            return '/admin/primeros-pasos'


def get_onboarding_path() -> str:
    try:
        raw = (get_tenant_config(CONFIG_ONBOARDING_PATH, default='') or '').strip().lower()
    except Exception:
        return ''
    return raw if raw in ('guide', 'demo', 'skip') else ''


def set_onboarding_path(path: str) -> None:
    path = (path or '').strip().lower()
    if path not in ('guide', 'demo', 'skip'):
        return
    set_tenant_config(CONFIG_ONBOARDING_PATH, path)


def bridge_progress(metrics: Optional[dict] = None) -> dict:
    """Contadores del puente obras/operarios (sin vehículos)."""
    metrics = metrics or tenant_metrics()
    missing = []
    for key, need in BRIDGE_REQUIRES.items():
        have = int(metrics.get(key) or 0)
        if have < need:
            label = str(_('obras')) if key == 'obras' else str(_('operarios'))
            missing.append({'key': key, 'have': have, 'need': need, 'label': label})
    met, _msg = _threshold_met(BRIDGE_REQUIRES, metrics)
    return {
        'requires': dict(BRIDGE_REQUIRES),
        'obras': int(metrics.get('obras') or 0),
        'operarios': int(metrics.get('operarios') or 0),
        'met': met,
        'missing': missing,
    }


def curriculum_visibility(metrics: Optional[dict] = None, chapters: Optional[list] = None) -> dict:
    """
    Cuándo mostrar el bloque de tutoriales básicos bajo las 3 puertas.

    Visible si:
      - hay ≥1 obra y ≥1 persona (guía / import / alta; vehículo NO obligatorio), o
      - generaron datos de ejemplo, o
      - el capítulo de importación está marcado como hecho.
    Poder HACERLOS sigue siendo el puente 3+3 (bridge.met).
    """
    metrics = metrics or tenant_metrics()
    by_id = {c['id']: c for c in (chapters or [])}
    obras = int(metrics.get('obras') or 0)
    operarios = int(metrics.get('operarios') or 0)
    demo_activa = bool(metrics.get('demo_activa'))

    seed_done = (by_id.get('seed') or {}).get('status') == STATUS_DONE
    demo_done = (by_id.get('demo') or {}).get('status') == STATUS_DONE
    import_done = (by_id.get('import') or {}).get('status') == STATUS_DONE

    min_data, _ = _threshold_met(CURRICULUM_VISIBLE_REQUIRES, metrics)
    visible = bool(min_data or demo_activa or demo_done or import_done)

    return {
        'visible': visible,
        'requires': dict(CURRICULUM_VISIBLE_REQUIRES),
        'obras': obras,
        'operarios': operarios,
        'min_data': min_data,
        'via_demo': demo_activa or demo_done,
        'via_import': import_done,
        'via_guide': bool(seed_done and min_data),
    }


def _node_status(done: bool, available: bool = True) -> str:
    if done:
        return STATUS_DONE
    if available:
        return STATUS_AVAILABLE
    return STATUS_LOCKED


def build_caminitos(chapters: list, metrics: dict) -> dict:
    """
    Mapa visual: puertas → troncos → puente → currículo compartido.
    Excel es lateral y no desbloquea el tronco.
    """
    by_id = {c['id']: c for c in chapters}
    path = get_onboarding_path()
    bridge = bridge_progress(metrics)
    fichaje_on = bool(metrics.get('fichaje_activo'))
    seed = by_id.get('seed') or {}
    demo = by_id.get('demo') or {}
    import_ch = by_id.get('import')

    obras = int(metrics.get('obras') or 0)
    operarios = int(metrics.get('operarios') or 0)
    vehiculos = int(metrics.get('vehiculos') or 0)
    fichajes = int(metrics.get('fichajes') or 0)
    seed_done = seed.get('status') == STATUS_DONE
    demo_done = demo.get('status') == STATUS_DONE

    trunk_a = [
        {
            'id': 'a0',
            'kind': 'question',
            'title': str(_('¿Vais a fichar?')),
            'blurb': str(_('Se pregunta al empezar el recorrido completo.')),
            'status': _node_status(True, True) if path == 'guide' or fichaje_on or seed_done else STATUS_AVAILABLE,
            'action': 'guide_start',
        },
        {
            'id': 'a1',
            'kind': 'tutorial',
            'title': str(_('Crear la primera persona')),
            'blurb': str(_('Te enseñamos dónde crear un trabajador.')),
            'status': _node_status(operarios >= 1 or seed_done, True),
            'counters': [{'have': operarios, 'need': 1, 'label': str(_('personas'))}],
            'action': 'guide_start',
            'href': _safe_url('admin.primeros_pasos', tour='start'),
        },
        {
            'id': 'a2',
            'kind': 'tutorial',
            'title': str(_('Crear la primera obra')),
            'blurb': str(_('Alta guiada de una obra.')),
            'status': _node_status(obras >= 1 or seed_done, operarios >= 1 or seed_done),
            'counters': [{'have': obras, 'need': 1, 'label': str(_('obras'))}],
            'action': 'guide_obra',
            'href': (
                _safe_url('admin.create_obra', tour='obra')
                if operarios >= 1 or seed_done
                else None
            ),
        },
        {
            'id': 'a3',
            'kind': 'tutorial',
            'title': str(_('Probar el fichaje')),
            'blurb': str(_('Solo si decidiste activarlo.')),
            'status': (
                STATUS_LOCKED if not fichaje_on and not seed_done
                else _node_status(fichajes >= 1 or seed_done, fichaje_on or seed_done)
            ),
            'optional': True,
            'hidden_if_no_fichaje': True,
            'action': 'guide_fichaje',
        },
        {
            'id': 'q_fleet',
            'kind': 'question',
            'title': str(_('¿Tenéis vehículos?')),
            'blurb': str(_('Se pregunta al terminar el recorrido completo.')),
            'status': _node_status(vehiculos >= 1, obras >= 1 or seed_done),
            'optional': True,
            'action': 'fleet_ask',
        },
        {
            'id': 'a4',
            'kind': 'tutorial',
            'title': str(_('Alta de un vehículo')),
            'blurb': str(_('Si dijiste que sí, o cuando quieras desde aquí.')),
            'status': _node_status(vehiculos >= 1, True),
            'optional': True,
            'counters': [{'have': vehiculos, 'need': 1, 'label': str(_('vehículos'))}],
            'href': _safe_url('admin.vehiculos_nuevo'),
            'action': 'fleet_tour',
        },
    ]

    trunk_b = [
        {
            'id': 'b0',
            'kind': 'question',
            'title': str(_('¿Vais a fichar?')),
            'blurb': str(_('También en datos de ejemplo.')),
            'status': STATUS_AVAILABLE if path != 'demo' else STATUS_DONE,
            'action': 'demo_fichaje',
        },
        {
            'id': 'b1',
            'kind': 'tutorial',
            'title': str(_('Generar datos de ejemplo')),
            'blurb': str(_('Salta la semilla: obras, personas y vehículos demo.')),
            'status': _node_status(bool(metrics.get('demo_activa')) or demo_done or path == 'demo', True),
            'action': 'demo_generate',
        },
    ]

    shared = []
    for tid in SHARED_TOUR_IDS:
        ch = by_id.get(tid)
        if ch:
            shared.append(ch)

    advanced = []
    for tid in ADVANCED_TOUR_IDS:
        ch = by_id.get(tid)
        if ch:
            advanced.append(ch)

    curriculum = curriculum_visibility(metrics, chapters)

    if seed_done:
        for node in trunk_a:
            if node.get('id') == 'a4':
                node['status'] = _node_status(vehiculos >= 1, True)
            elif node.get('kind') in ('tutorial', 'question'):
                node['status'] = STATUS_DONE

    return {
        'path': path,
        'bridge': bridge,
        'curriculum': curriculum,
        'guide_done': seed_done,
        'demo_done': bool(demo_done or metrics.get('demo_activa')),
        'trunk_a': trunk_a,
        'trunk_b': trunk_b,
        'shared': shared,
        'advanced': advanced,
        'side_import': import_ch,
        'fichaje_activo': fichaje_on,
        'doors': {
            'guide': {
                'active': path == 'guide',
                'done': seed_done,
                'label': str(_('Guía interactiva')),
            },
            'demo': {
                'active': path == 'demo',
                'done': bool(demo_done or metrics.get('demo_activa')),
                'label': str(_('Datos de ejemplo')),
            },
            'skip': {'active': path == 'skip', 'label': str(_('Ya sé / ir a la app'))},
        },
    }


def evaluate_academia(user=None) -> dict:
    """
    Estado completo de la Academia para plantillas / API.
    Soft gates: locked = no cumple umbral, pero se puede abrir igual (available_forced).
    """
    user = user or current_user
    if not tenant_tiene_onboarding():
        return {
            'enabled': False,
            'chapters': [],
            'metrics': {},
            'done': 0,
            'total': 0,
            'next': None,
            'newly_unlocked': [],
            'caminitos': None,
        }

    metrics = tenant_metrics()
    progress = _load_raw_progress()
    dirty = False
    # Capítulos viejos → sección unificada «fichajes»
    if (progress.get('fichajes') or {}).get('status') != STATUS_DONE:
        legacy_done = any(
            (progress.get(k) or {}).get('status') == STATUS_DONE
            for k in ('auditoria_fichajes', 'registro_jornada')
        )
        if legacy_done:
            progress['fichajes'] = {
                'status': STATUS_DONE,
                'at': _utcnow_iso(),
                'seen_unlock': True,
            }
            dirty = True
    # Sync import ticks → chapter import
    imp = import_tutorials_done()
    if (
        all(imp.get(k) for k in ('obras', 'users_internos', 'users_externos', 'companies'))
        and progress.get('import', {}).get('status') != STATUS_DONE
    ):
        progress['import'] = {'status': STATUS_DONE, 'at': _utcnow_iso(), 'seen_unlock': True}
        dirty = True

    chapters = []
    newly_unlocked = []
    for defn in catalog_definitions():
        tid = defn['id']
        # Solo si activaron fichaje de operarios
        if tid == 'fichajes' and not metrics.get('fichaje_activo'):
            continue
        if not _module_visible(defn.get('module') or '', user):
            continue
        met, missing_msg = _threshold_met(defn.get('requires') or {}, metrics)
        stored = progress.get(tid) if isinstance(progress.get(tid), dict) else {}
        stored_status = stored.get('status') or ''

        if stored_status == STATUS_DONE:
            status = STATUS_DONE
        elif stored_status == STATUS_IN_PROGRESS:
            status = STATUS_IN_PROGRESS
        elif met:
            status = STATUS_AVAILABLE
            if stored_status == STATUS_LOCKED or (
                not stored_status and defn.get('requires')
            ):
                # Primera vez disponible tras umbral
                if stored.get('seen_unlock') is not True and defn.get('requires'):
                    newly_unlocked.append(tid)
                    progress[tid] = {
                        'status': STATUS_AVAILABLE,
                        'seen_unlock': True,
                        'unlocked_at': _utcnow_iso(),
                    }
                    dirty = True
        else:
            status = STATUS_LOCKED

        chapters.append({
            **defn,
            'status': status,
            'missing_msg': missing_msg,
            'threshold_met': met,
            'href': _entry_url(defn),
            'can_start': True,  # soft gate
        })

    if dirty:
        _save_progress(progress)

    done = sum(1 for c in chapters if c['status'] == STATUS_DONE)
    total = len(chapters)
    next_ch = None
    shared_set = set(SHARED_TOUR_IDS)
    advanced_set = set(ADVANCED_TOUR_IDS)

    def _pick_next(candidates):
        for c in candidates:
            if c['status'] in (STATUS_AVAILABLE, STATUS_IN_PROGRESS):
                return c
        for c in candidates:
            if c['status'] == STATUS_LOCKED and c.get('soft'):
                return c
        for c in candidates:
            if c['status'] != STATUS_DONE:
                return c
        return None

    basics = [c for c in chapters if c['id'] in shared_set]
    advanced = [c for c in chapters if c['id'] in advanced_set]
    other = [c for c in chapters if c['id'] not in shared_set and c['id'] not in advanced_set]
    next_ch = _pick_next(basics) or _pick_next(other) or _pick_next(advanced)

    return {
        'enabled': True,
        'chapters': chapters,
        'metrics': metrics,
        'done': done,
        'total': total,
        'next': next_ch,
        'newly_unlocked': newly_unlocked,
        'onboarding_completo': onboarding_marcado_completo(),
        'caminitos': build_caminitos(chapters, metrics),
    }


def mark_tour_status(tour_id: str, status: str) -> dict:
    if tour_id not in TOUR_IDS:
        raise ValueError('Tutorial desconocido')
    if status not in (STATUS_DONE, STATUS_IN_PROGRESS, STATUS_AVAILABLE, STATUS_LOCKED):
        raise ValueError('Estado inválido')
    progress = _load_raw_progress()
    prev = progress.get(tour_id) if isinstance(progress.get(tour_id), dict) else {}
    entry = {**prev, 'status': status}
    if status == STATUS_DONE:
        entry['at'] = _utcnow_iso()
    if status == STATUS_IN_PROGRESS:
        entry['started_at'] = _utcnow_iso()
    progress[tour_id] = entry
    _save_progress(progress)
    return entry


def mark_tour_done(tour_id: str) -> dict:
    return mark_tour_status(tour_id, STATUS_DONE)


def mark_tour_started(tour_id: str) -> dict:
    if tour_id == 'seed':
        set_onboarding_path('guide')
    elif tour_id == 'demo':
        set_onboarding_path('demo')
    return mark_tour_status(tour_id, STATUS_IN_PROGRESS)


def chapter_by_js(chapter_js: str) -> Optional[str]:
    for defn in catalog_definitions():
        if defn.get('chapter_js') == chapter_js:
            return defn['id']
    # seed uses trabajadores/obra/fichaje chain
    if chapter_js in ('trabajadores', 'obra', 'fichaje'):
        return 'seed'
    return None
