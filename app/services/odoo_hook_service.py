"""Avisos inbound de Odoo: no traen la ficha, solo despiertan el sync que ya existe.

Odoo POST {model, id, action}. SignaPlan responde 202, espera unos segundos
por si llegan más avisos del mismo módulo, y tira del adaptador XML-RPC de
siempre (mismos campos, mismas reglas).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
from datetime import datetime, timezone

from flask import g, has_request_context, url_for
from flask import current_app

from app.models import SyncLog
from app.services.config_service import get_tenant_config, set_tenant_config

logger = logging.getLogger(__name__)

HOOK_KEY_CLAVE = 'odoo_sync_hook_key'
DEBOUNCE_SECONDS = 8
HOOK_MODO = 'Hook Odoo'

# model Odoo → módulo de sync_runner / panel
MODEL_TO_RESOURCE = {
    'res.partner': 'subcontratas',
    'hr.employee': 'empleados',
    'bim.project': 'obras',
    'hr.leave': 'ausencias',
    'hr.attendance': 'fichajes',
    'fleet.vehicle': 'vehiculos',
    'fleet.vehicle.odometer': 'vehiculos',
}

RESOURCE_ALIASES = {
    'subcontratas': 'subcontratas',
    'partners': 'subcontratas',
    'contactos': 'subcontratas',
    'empleados': 'empleados',
    'employees': 'empleados',
    'obras': 'obras',
    'projects': 'obras',
    'ausencias': 'ausencias',
    'leaves': 'ausencias',
    'fichajes': 'fichajes',
    'attendance': 'fichajes',
    'vehiculos': 'vehiculos',
    'vehicles': 'vehiculos',
    'flota': 'vehiculos',
}

VALID_ACTIONS = frozenset({
    'create', 'write', 'unlink', 'archive', 'unarchive', 'refresh',
})

RESOURCE_TIPO_LOG = {
    'obras': 'Obras',
    'empleados': 'Empleados',
    'subcontratas': 'Subcontratas',
    'ausencias': 'Ausencias',
    'fichajes': 'Fichajes',
    'vehiculos': 'Vehículos',
}


class OdooHookError(Exception):
    def __init__(self, message, status=400, code='invalid'):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


def _tenant_has_odoo():
    tenant = getattr(g, 'current_tenant', None)
    if not tenant:
        return False
    modulos = getattr(tenant, 'modulos_activos', None) or {}
    return bool(modulos.get('odoo'))


def ensure_hook_key():
    """Crea una clave por tenant la primera vez. Cifrada en configuración."""
    existing = (get_tenant_config(HOOK_KEY_CLAVE, desencriptar=True, default='') or '').strip()
    if existing:
        return existing
    key = secrets.token_urlsafe(32)
    set_tenant_config(HOOK_KEY_CLAVE, key, encriptar=True)
    return key


def rotate_hook_key():
    key = secrets.token_urlsafe(32)
    set_tenant_config(HOOK_KEY_CLAVE, key, encriptar=True)
    return key


def get_hook_key():
    return (get_tenant_config(HOOK_KEY_CLAVE, desencriptar=True, default='') or '').strip()


def extract_provided_key(headers, json_body=None):
    header = (headers.get('X-Odoo-Sync-Key') or '').strip()
    if header:
        return header
    auth = (headers.get('Authorization') or '').strip()
    if auth.lower().startswith('bearer '):
        return auth[7:].strip()
    if isinstance(json_body, dict):
        return str(json_body.get('key') or json_body.get('secret') or '').strip()
    return ''


def keys_match(provided, expected):
    if not provided or not expected:
        return False
    a = provided.encode('utf-8')
    b = expected.encode('utf-8')
    # Misma longitud para compare_digest; si no, comparamos hashes.
    if len(a) != len(b):
        hmac.compare_digest(hashlib.sha256(a).digest(), hashlib.sha256(b).digest())
        return False
    return hmac.compare_digest(a, b)


def resolve_resource(payload):
    """Devuelve el módulo de sync o None si el modelo no nos interesa."""
    if not isinstance(payload, dict):
        return None
    raw_resource = (payload.get('resource') or payload.get('module') or '').strip().lower()
    if raw_resource:
        aliased = RESOURCE_ALIASES.get(raw_resource)
        if aliased:
            return aliased
    model = str(payload.get('model') or payload.get('odoo_model') or '').strip()
    if not model:
        return None
    mapped = MODEL_TO_RESOURCE.get(model)
    if mapped:
        return mapped
    # fleet.* → vehículos (odómetro, viajes custom, etc.)
    if model.startswith('fleet.'):
        return 'vehiculos'
    return None


def _parse_odoo_id(payload):
    raw = payload.get('id', payload.get('odoo_id', payload.get('res_id')))
    if raw is None or raw == '':
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise OdooHookError('id debe ser un entero de Odoo.', status=422, code='bad_id')


def parse_hook_payload(payload):
    if not isinstance(payload, dict) or not payload:
        raise OdooHookError('JSON vacío o inválido.', status=400, code='bad_json')

    resource = resolve_resource(payload)
    if not resource:
        model = str(payload.get('model') or '').strip() or None
        return {
            'ignored': True,
            'resource': None,
            'model': model,
            'odoo_id': None,
            'action': None,
            'event_id': str(payload.get('event_id') or '').strip() or None,
        }

    action = str(payload.get('action') or payload.get('event') or 'write').strip().lower()
    if action.startswith('record.'):
        action = action.split('.', 1)[-1]
    if action not in VALID_ACTIONS:
        action = 'write'

    odoo_id = _parse_odoo_id(payload)
    if odoo_id is None and action != 'refresh':
        raise OdooHookError(
            'Falta id del registro Odoo (entero). Para refrescar un módulo entero usa action=refresh.',
            status=422,
            code='missing_id',
        )

    parent_id = payload.get('parent_id')
    try:
        parent_id = int(parent_id) if parent_id not in (None, '') else None
    except (TypeError, ValueError):
        parent_id = None

    write_date = payload.get('write_date') or payload.get('date') or None
    if write_date is not None:
        write_date = str(write_date)[:64]

    return {
        'ignored': False,
        'resource': resource,
        'model': str(payload.get('model') or '').strip() or None,
        'odoo_id': odoo_id,
        'parent_id': parent_id,
        'action': action,
        'event_id': str(payload.get('event_id') or '').strip() or None,
        'write_date': write_date,
    }


def _redis():
    try:
        import redis
        url = current_app.config.get('CELERY_BROKER_URL') or 'redis://redis:6379/0'
        return redis.from_url(url, socket_connect_timeout=0.4, socket_timeout=0.4)
    except Exception:
        return None


def _debounce_should_schedule(tenant_id, resource):
    """True si hay que encolar. False si otro aviso del mismo módulo ya espera."""
    client = _redis()
    if client is None:
        return True
    key = f'odoo_hook:debounce:{tenant_id}:{resource}'
    try:
        # SET NX EX: el primero programa; el resto se agrupan en esa pasada.
        got = client.set(key, '1', nx=True, ex=DEBOUNCE_SECONDS + 30)
        return bool(got)
    except Exception as exc:
        logger.warning('Redis debounce Odoo hook no disponible: %s', exc)
        return True


def schedule_resource_sync(resource, meta=None):
    tenant = getattr(g, 'current_tenant', None)
    if not tenant:
        raise OdooHookError('No hay tenant en el host.', status=404, code='no_tenant')
    if not _debounce_should_schedule(tenant.id, resource):
        return 'coalesced'
    from app.celery_worker import process_odoo_hook_task
    process_odoo_hook_task.apply_async(
        args=[tenant.schema_name, resource],
        kwargs={'meta': meta or {}},
        countdown=DEBOUNCE_SECONDS,
    )
    return 'scheduled'


def accept_hook(headers, payload):
    """Valida el aviso y encola el sync del módulo. No habla con Odoo aquí."""
    if not getattr(g, 'current_tenant', None):
        raise OdooHookError(
            'Llama a la URL del espacio de la empresa (subdominio o dominio propio).',
            status=404,
            code='no_tenant',
        )
    if not _tenant_has_odoo():
        raise OdooHookError('Este espacio no tiene el módulo Odoo activo.', status=403, code='no_module')

    expected = get_hook_key()
    if not expected:
        expected = ensure_hook_key()
    provided = extract_provided_key(headers, payload)
    if not keys_match(provided, expected):
        raise OdooHookError('Clave de aviso no válida.', status=401, code='unauthorized')

    parsed = parse_hook_payload(payload if isinstance(payload, dict) else {})
    if parsed['ignored']:
        return {
            'accepted': True,
            'ignored': True,
            'status': 'ignored',
            'model': parsed.get('model'),
            'message': 'Modelo no sincronizado; no se hace nada.',
        }

    status = schedule_resource_sync(parsed['resource'], meta={
        'model': parsed.get('model'),
        'odoo_id': parsed.get('odoo_id'),
        'action': parsed.get('action'),
        'event_id': parsed.get('event_id'),
        'parent_id': parsed.get('parent_id'),
        'write_date': parsed.get('write_date'),
    })
    logger.info(
        'Hook Odoo %s resource=%s model=%s id=%s action=%s',
        status, parsed['resource'], parsed.get('model'),
        parsed.get('odoo_id'), parsed.get('action'),
    )
    return {
        'accepted': True,
        'ignored': False,
        'status': status,
        'resource': parsed['resource'],
        'model': parsed.get('model'),
        'id': parsed.get('odoo_id'),
        'action': parsed.get('action'),
        'debounce_seconds': DEBOUNCE_SECONDS,
    }


def run_hook_resource(resource, meta=None):
    """Ejecuta el mismo runner que el botón Auto / la noche, solo este módulo."""
    from app.services.sync_config_service import SyncConfigService
    from app.services.sync_runner_service import (
        run_auto_sync_ausencias,
        run_auto_sync_empleados,
        run_auto_sync_obras,
        run_auto_sync_subcontratas,
        run_auto_sync_vehiculos,
    )

    meta = meta or {}
    cfg = SyncConfigService.get_config()
    enabled = {
        'obras': cfg.get('obras_enabled', True),
        'empleados': cfg.get('empleados_enabled', True),
        'subcontratas': cfg.get('subcontratas_enabled', True),
        'ausencias': cfg.get('ausencias_enabled', True),
        'fichajes': cfg.get('fichajes_enabled', True),
        'vehiculos': cfg.get('vehiculos_enabled', True),
    }
    if not enabled.get(resource, False):
        logger.info('Hook Odoo %s omitido: módulo desactivado en config.', resource)
        return {'skipped': True, 'resource': resource}

    tipo = RESOURCE_TIPO_LOG.get(resource, resource)
    detail_bits = [f"Aviso Odoo {resource}."]
    if meta.get('model'):
        detail_bits.append(f"model={meta['model']}")
    if meta.get('odoo_id') is not None:
        detail_bits.append(f"id={meta['odoo_id']}")
    if meta.get('action'):
        detail_bits.append(f"action={meta['action']}")
    detalle = ' '.join(detail_bits)

    t0 = datetime.now(timezone.utc)
    try:
        if resource == 'obras':
            run_auto_sync_obras(modo=HOOK_MODO)
        elif resource == 'empleados':
            run_auto_sync_empleados(modo=HOOK_MODO)
        elif resource == 'subcontratas':
            run_auto_sync_subcontratas(modo=HOOK_MODO)
        elif resource == 'ausencias':
            run_auto_sync_ausencias(modo=HOOK_MODO)
        elif resource == 'fichajes':
            from app.services.sync_service import procesar_fichajes_diarios
            procesar_fichajes_diarios()
            SyncConfigService.mark_fichajes_sync_done()
            from app import db
            from app.utils.timezone_utils import utc_now
            db.session.add(SyncLog(
                fecha=utc_now(),
                tipo='Fichajes',
                modo=HOOK_MODO,
                nuevos=0, actualizados=0, finalizados=0, errores=0,
                detalles=detalle,
                estado='ok',
                duracion_ms=int((datetime.now(timezone.utc) - t0).total_seconds() * 1000),
            ))
            db.session.commit()
        elif resource == 'vehiculos':
            run_auto_sync_vehiculos(modo=HOOK_MODO)
        else:
            return {'skipped': True, 'resource': resource, 'reason': 'unknown'}
    except Exception:
        logger.exception('Hook Odoo falló al sincronizar %s', resource)
        raise

    logger.info('Hook Odoo sync %s ok (%s)', resource, detalle)
    return {'ok': True, 'resource': resource}


def hook_endpoint_url():
    if has_request_context():
        try:
            return url_for('api_v6.odoo_hook_changed', _external=True)
        except Exception:
            pass
    return '/api/v6/odoo/hooks/changed'


def hook_dashboard_context():
    key = ensure_hook_key()
    last = (
        SyncLog.query.filter_by(modo=HOOK_MODO)
        .order_by(SyncLog.fecha.desc())
        .first()
    )
    example = {
        'event_id': '00000000-0000-0000-0000-000000000001',
        'action': 'create',
        'model': 'res.partner',
        'id': 12345,
        'write_date': '2026-09-07T09:00:00+02:00',
        'parent_id': 998,
    }
    return {
        'url': hook_endpoint_url(),
        'key': key,
        'header': 'X-Odoo-Sync-Key',
        'models': [
            {'model': 'res.partner', 'resource': 'subcontratas', 'label': 'Subcontratas y contactos'},
            {'model': 'hr.employee', 'resource': 'empleados', 'label': 'Personal interno'},
            {'model': 'bim.project', 'resource': 'obras', 'label': 'Obras / proyectos BIM'},
            {'model': 'hr.leave', 'resource': 'ausencias', 'label': 'Ausencias / time off'},
            {'model': 'hr.attendance', 'resource': 'fichajes', 'label': 'Fichajes (opcional; el cron de 30 min sigue)'},
            {'model': 'fleet.vehicle', 'resource': 'vehiculos', 'label': 'Vehículos / flota'},
        ],
        'last_log': last,
        'debounce_seconds': DEBOUNCE_SECONDS,
        'example': example,
        'example_json': json.dumps(example, indent=2, ensure_ascii=False),
    }
