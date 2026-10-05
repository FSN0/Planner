"""Contadores de logs no leídos por categoría."""
from datetime import datetime, timezone

from sqlalchemy import func

from app import db
from app.models import ConfiguracionGlobal, LogAcknowledgement, LogPreference, SystemLog
from app.utils.timezone_utils import utc_now

LOG_TAB_CATEGORIES = ['accesos', 'valoraciones', 'planificacion', 'obras', 'fichajes']

LABORAL_LOG_CATEGORIES = ['solicitud', 'planificacion']
LABORAL_EXCLUDED_ACTIONS = ['Borrar Planificación']
LABORAL_BULK_CFG_KEY = 'laboral_bulk_cleared_at'


def get_unread_logs_by_category(user_id, active_only=True):
    """Devuelve {categoria: count} con entradas no leídas (>0)."""
    prefs = {
        p.category: p
        for p in LogPreference.query.filter_by(user_id=user_id).all()
    }
    # Sin preferencias activas no hay badges → evita escanear system_logs.
    active_cats = []
    last_reads = {}
    for cat in LOG_TAB_CATEGORIES:
        pref = prefs.get(cat)
        if active_only and (not pref or not pref.is_active):
            continue
        active_cats.append(cat)
        last_reads[cat] = (
            pref.last_read_at if pref and pref.last_read_at
            else datetime.min.replace(tzinfo=timezone.utc)
        )
    if not active_cats:
        return {}

    unread = {}
    # Una COUNT por categoría activa (típicamente 0–5), con filtro timestamp.
    # Con índice (category, timestamp) es barato; sin prefs activas no se llega aquí.
    for cat in active_cats:
        count = SystemLog.query.filter(
            SystemLog.category == cat,
            SystemLog.timestamp > last_reads[cat],
        ).count()
        if count > 0:
            unread[cat] = count
    return unread


def get_total_unread_logs(user_id):
    return sum(get_unread_logs_by_category(user_id, active_only=True).values())


def _parse_dt(raw):
    if not raw:
        return None
    text = str(raw).strip()
    for fmt in ('%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S'):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def get_laboral_bulk_cleared_at():
    """Marca global de 'leer todas' (afecta a admin + laboral)."""
    row = ConfiguracionGlobal.query.filter_by(clave=LABORAL_BULK_CFG_KEY).first()
    return _parse_dt(row.valor) if row else None


def _laboral_base_filter(user_id):
    """Categoría laboral, sin excluidas, sin ack individual, posteriores al clear global."""
    acked_exists = db.session.query(LogAcknowledgement.id).filter(
        LogAcknowledgement.user_id == user_id,
        LogAcknowledgement.log_id == SystemLog.id,
    ).exists()
    filters = [
        SystemLog.category.in_(LABORAL_LOG_CATEGORIES),
        ~SystemLog.action.in_(LABORAL_EXCLUDED_ACTIONS),
        ~acked_exists,
    ]
    cleared_at = get_laboral_bulk_cleared_at()
    if cleared_at is not None:
        filters.append(SystemLog.timestamp > cleared_at)
    return filters


def get_unread_laboral_logs(user_id):
    """Cuenta SystemLog laborales sin acusar (respeta clear global)."""
    return SystemLog.query.filter(*_laboral_base_filter(user_id)).count()


def get_unread_laboral_logs_by_category(user_id):
    """Cuenta logs laborales no acusados por categoría."""
    rows = (
        db.session.query(SystemLog.category, func.count(SystemLog.id))
        .filter(*_laboral_base_filter(user_id))
        .group_by(SystemLog.category)
        .all()
    )
    return {category: count for category, count in rows}


def get_laboral_acknowledged_ids(user_id, log_ids):
    """Set de log_id ya leídos (ack individual o cubiertos por clear global)."""
    if not log_ids:
        return set()
    rows = (
        LogAcknowledgement.query
        .filter(
            LogAcknowledgement.user_id == user_id,
            LogAcknowledgement.log_id.in_(log_ids),
        )
        .with_entities(LogAcknowledgement.log_id)
        .all()
    )
    acked = {row[0] for row in rows}
    cleared_at = get_laboral_bulk_cleared_at()
    if cleared_at is None:
        return acked
    older = (
        SystemLog.query
        .filter(
            SystemLog.id.in_(log_ids),
            SystemLog.timestamp <= cleared_at,
        )
        .with_entities(SystemLog.id)
        .all()
    )
    acked.update(row[0] for row in older)
    return acked


def acknowledge_log(user_id, log_id):
    existing = LogAcknowledgement.query.filter_by(user_id=user_id, log_id=log_id).first()
    if existing:
        return
    db.session.add(LogAcknowledgement(user_id=user_id, log_id=log_id))
    db.session.commit()


def unacknowledge_log(user_id, log_id):
    """Quita el ack individual. No revierte un clear global masivo."""
    LogAcknowledgement.query.filter_by(user_id=user_id, log_id=log_id).delete()
    db.session.commit()


def acknowledge_all_laboral_logs_global():
    """
    Marca como leídos todos los logs laborales actuales para TODOS los usuarios
    (admin + laboral). Usa watermark global en ConfiguracionGlobal.
    """
    now = utc_now()
    valor = now.strftime('%Y-%m-%dT%H:%M:%S.%f')
    row = ConfiguracionGlobal.query.filter_by(clave=LABORAL_BULK_CFG_KEY).first()
    if not row:
        db.session.add(ConfiguracionGlobal(clave=LABORAL_BULK_CFG_KEY, valor=valor))
    else:
        row.valor = valor
    db.session.commit()
    return 0
