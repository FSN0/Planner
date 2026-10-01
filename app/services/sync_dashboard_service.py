"""Estadísticas y contexto para el panel de sincronización Odoo."""
import os
from datetime import timedelta

from sqlalchemy import func

from app import db
from app.models import Obra, User, Company, SyncLog, RegistroFichaje
from app.services.sync_config_service import SyncConfigService, SYNC_MODULES
from app.services.entity_linkage_service import get_entity_linkage_summary
from app.utils.timezone_utils import utc_now, today_local


def _last_log_for_tipo(tipo_prefix):
    return (
        SyncLog.query.filter(SyncLog.tipo.like(f'{tipo_prefix}%'))
        .order_by(SyncLog.fecha.desc())
        .first()
    )


def _stats_for_period(days=7):
    since = utc_now() - timedelta(days=days)
    logs = SyncLog.query.filter(SyncLog.fecha >= since).all()
    total_runs = len(logs)
    errors = sum(1 for l in logs if (getattr(l, 'estado', None) or 'ok') == 'error')
    partial = sum(1 for l in logs if (getattr(l, 'estado', None) or 'ok') == 'parcial')
    ok = sum(1 for l in logs if (getattr(l, 'estado', None) or 'ok') == 'ok')
    skipped = sum(l.errores or 0 for l in logs)
    nuevos = sum(l.nuevos or 0 for l in logs)
    actualizados = sum(l.actualizados or 0 for l in logs)
    return {
        'total_runs': total_runs,
        'ok': ok,
        'errors': errors,
        'partial': partial,
        'skipped_records': skipped,
        'nuevos': nuevos,
        'actualizados': actualizados,
    }


def test_odoo_connection():
    try:
        from app.sync.dispatcher import get_sync_adapter
        adapter = get_sync_adapter()
        return {
            'connected': True,
            'url': getattr(adapter, 'url', '') or os.environ.get('ODOO_URL', ''),
            'db': getattr(adapter, 'db_name', '') or os.environ.get('ODOO_DB', ''),
            'uid': getattr(adapter, 'uid', None),
            'message': 'Conexión XML-RPC establecida correctamente.',
        }
    except Exception as e:
        return {
            'connected': False,
            'url': os.environ.get('ODOO_URL', ''),
            'db': os.environ.get('ODOO_DB', ''),
            'uid': None,
            'message': str(e),
        }


def get_recent_sync_alerts():
    """Errores críticos + un único resumen por módulo (sin repetir cada ejecución)."""
    no_visto = db.or_(SyncLog.visto.is_(False), SyncLog.visto.is_(None))
    critical = (
        SyncLog.query.filter(SyncLog.estado == 'error', no_visto)
        .order_by(SyncLog.fecha.desc())
        .limit(5)
        .all()
    )

    seen = set()
    partial_summaries = []
    for log in (
        SyncLog.query.filter(
            no_visto,
            db.or_(SyncLog.estado == 'parcial', SyncLog.errores > 0),
        )
        .order_by(SyncLog.fecha.desc())
        .limit(80)
        .all()
    ):
        if log.tipo in seen:
            continue
        if (log.errores or 0) > 0 or (getattr(log, 'estado', None) or '') == 'parcial':
            seen.add(log.tipo)
            partial_summaries.append(log)
        if len(partial_summaries) >= 4:
            break

    return critical, partial_summaries


def marcar_sync_log_visto(log_id):
    log = SyncLog.query.get(log_id)
    if not log:
        return None
    log.visto = True
    log.visto_en = utc_now()
    return log


def marcar_alertas_sync_vistas():
    """Oculta errores/parciales pendientes del panel (no borra el historial en BD)."""
    no_visto = db.or_(SyncLog.visto.is_(False), SyncLog.visto.is_(None))
    pendientes = db.or_(
        SyncLog.estado == 'error',
        SyncLog.estado == 'parcial',
        SyncLog.errores > 0,
    )
    ahora = utc_now()
    (
        SyncLog.query.filter(no_visto, pendientes)
        .update({'visto': True, 'visto_en': ahora}, synchronize_session=False)
    )
    return ahora


def get_sync_panel_context():
    cfg = SyncConfigService.get_config()
    conn = test_odoo_connection()
    stats_7d = _stats_for_period(7)
    stats_30d = _stats_for_period(30)

    today = today_local()
    fichajes_hoy = RegistroFichaje.query.filter(RegistroFichaje.fecha == today).count()
    incidencias_pendientes = RegistroFichaje.query.filter(
        RegistroFichaje.estado.in_(['Conflicto', 'Paracaidista', 'Ausencia'])
    ).count()

    entity_linkage = get_entity_linkage_summary()

    modules = []
    for mod in SYNC_MODULES:
        last = _last_log_for_tipo(mod['tipo_log'])
        if mod['key'] == 'fichajes':
            schedule = SyncConfigService.format_fichajes_schedule(cfg)
            enabled = cfg['fichajes_enabled']
            next_run = SyncConfigService.estimate_next_fichajes(cfg)
            retro_next_run = SyncConfigService.estimate_next_fichajes_retro(cfg)
        elif mod['key'] == 'vehiculos':
            schedule = SyncConfigService.format_vehiculos_schedule(cfg)
            enabled = cfg['vehiculos_enabled']
            next_run = SyncConfigService.estimate_next_vehiculos(cfg)
            retro_next_run = SyncConfigService.estimate_next_vehiculos_retro(cfg)
        else:
            schedule = SyncConfigService.format_master_schedule(cfg)
            enabled = cfg.get(f"{mod['key']}_enabled", True)
            next_run = SyncConfigService.estimate_next_master(cfg)
            retro_next_run = None

        modules.append({
            **mod,
            'enabled': enabled,
            'schedule': schedule,
            'last_log': last,
            'next_run': next_run,
            'retro_next_run': retro_next_run,
        })

    critical_errors, partial_summaries = get_recent_sync_alerts()

    logs = (
        SyncLog.query
        .order_by(SyncLog.fecha.desc())
        .limit(50)
        .all()
    )

    preview_pending = {}
    preview_cache_meta = {}
    try:
        from app.services.sync_preview_cache_service import pending_counts_all, load_cache, format_saved_at
        preview_pending = pending_counts_all()
        for mod_key, count in preview_pending.items():
            if count > 0:
                cached = load_cache(mod_key) or {}
                preview_cache_meta[mod_key] = {
                    'count': count,
                    'saved_at': format_saved_at(cached.get('saved_at')),
                    'source': cached.get('source') or 'manual',
                }
    except Exception:
        preview_pending = {}
        preview_cache_meta = {}

    return {
        'config': cfg,
        'connection': conn,
        'stats_7d': stats_7d,
        'stats_30d': stats_30d,
        'entity_counts': {
            'obras_vinculadas': entity_linkage['obras']['vinculadas'],
            'obras_total': entity_linkage['obras']['total'],
            'empleados_vinculados': entity_linkage['empleados']['vinculados'],
            'empleados_total': entity_linkage['empleados']['total'],
            'empresas_vinculadas': entity_linkage['empresas']['vinculadas'],
            'empresas_total': entity_linkage['empresas']['total'],
        },
        'entity_linkage': entity_linkage,
        'modules': modules,
        'fichajes_hoy': fichajes_hoy,
        'incidencias_pendientes': incidencias_pendientes,
        'critical_errors': critical_errors,
        'partial_summaries': partial_summaries,
        'logs': logs,
        'preview_pending': preview_pending,
        'preview_cache_meta': preview_cache_meta,
    }
