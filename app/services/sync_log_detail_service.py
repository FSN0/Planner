"""Detalle estructurado de SyncLog (trazabilidad al clic en el historial)."""
from __future__ import annotations

from flask import has_request_context
from flask_login import current_user

from app.models import SyncLog, User

DETALLE_SCHEMA_VERSION = 1
MAX_ITEMS_PER_BUCKET = 80


def actor_from_request():
    """Usuario web actual si hay request autenticada."""
    if not has_request_context():
        return None
    try:
        if current_user and getattr(current_user, 'is_authenticated', False):
            return current_user
    except Exception:
        return None
    return None


def user_display_name(user) -> str:
    if not user:
        return '—'
    name = f'{(getattr(user, "name", None) or "").strip()} {(getattr(user, "lastname", None) or "").strip()}'.strip()
    return name or (getattr(user, 'email', None) or f'#{getattr(user, "id", "?")}')


def resolve_launcher(modo: str, actor=None, origen_label: str | None = None):
    """
    Quién disparó la sync.
    origen_label: p.ej. 'Hook Odoo', 'Programación automática', 'Panel sync'.
    """
    modo_l = (modo or '').strip() or 'Automático'
    if actor is not None:
        label = origen_label or f'{modo_l} · {user_display_name(actor)}'
        return {
            'lanzado_por_id': getattr(actor, 'id', None),
            'lanzado_por_label': label[:120],
            'lanzado_por': {
                'id': getattr(actor, 'id', None),
                'nombre': user_display_name(actor),
                'origen': origen_label or modo_l,
            },
        }
    if origen_label:
        label = origen_label
    elif modo_l.lower().startswith('hook'):
        label = 'Hook Odoo'
    elif modo_l.lower().startswith('manual'):
        label = 'Manual (sin usuario en contexto)'
    else:
        label = 'Programación automática'
    return {
        'lanzado_por_id': None,
        'lanzado_por_label': label[:120],
        'lanzado_por': {
            'id': None,
            'nombre': label,
            'origen': label,
        },
    }


def trim_bucket(items, limit=MAX_ITEMS_PER_BUCKET):
    items = list(items or [])
    return items[:limit], max(0, len(items) - limit)


def build_ausencias_detalle(
    *,
    ventana_desde,
    ventana_hasta,
    odoo_leidos: int,
    nuevos_items,
    cambiados_items,
    sin_cambio_count: int,
    omitidos_items,
    errores: int,
    sanados: int,
    explicacion=None,
    launcher=None,
):
    nuevos, nuevos_extra = trim_bucket(nuevos_items)
    cambiados, camb_extra = trim_bucket(cambiados_items)
    omitidos, omit_extra = trim_bucket(omitidos_items)
    launcher = launcher or {}
    return {
        'schema_version': DETALLE_SCHEMA_VERSION,
        'modulo': 'ausencias',
        'ventana': {
            'desde': str(ventana_desde) if ventana_desde else None,
            'hasta': str(ventana_hasta) if ventana_hasta else None,
            'fuente': 'odoo hr.leave (state=validate)',
        },
        'lanzado_por': launcher.get('lanzado_por'),
        'resumen': {
            'odoo_leidos': odoo_leidos,
            'nuevos': len(nuevos_items or []),
            'cambiados': len(cambiados_items or []),
            'sin_cambio': int(sin_cambio_count or 0),
            'omitidos': len(omitidos_items or []),
            'errores': int(errores or 0),
            'sanados': int(sanados or 0),
        },
        'explicacion': explicacion or [
            'Nueva = leave de Odoo que aún no existía en SignaPlan (por external_id).',
            'Cambiada = ya existía y algún campo útil difiere de Odoo (fechas, tipo, empleado…).',
            'Sin cambio = se leyó de Odoo pero SignaPlan ya tenía los mismos datos; no infla «~».',
            'Las fechas create/write son las de Odoo (cuándo se creó / tocó la ausencia allí).',
        ],
        'items': {
            'nuevos': nuevos,
            'cambiados': cambiados,
            'omitidos': omitidos,
            'truncados': {
                'nuevos': nuevos_extra,
                'cambiados': camb_extra,
                'omitidos': omit_extra,
            },
        },
    }


def get_sync_log_or_404(log_id: int):
    return SyncLog.query.get(log_id)


def detail_view_context(log: SyncLog):
    """Contexto para la plantilla de detalle."""
    launcher_name = log.lanzado_por_label
    if log.lanzado_por_id and not launcher_name:
        u = User.query.get(log.lanzado_por_id)
        launcher_name = user_display_name(u)
    detalle = log.detalle_json if isinstance(log.detalle_json, dict) else None
    return {
        'log': log,
        'launcher_name': launcher_name or '—',
        'detalle': detalle,
        'has_structured': bool(detalle),
        'legacy_text': (log.mensaje_error or log.detalles or '').strip(),
    }
