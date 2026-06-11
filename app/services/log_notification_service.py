"""Contadores de logs no leídos por categoría."""
from datetime import datetime, timezone

from app.models import LogPreference, SystemLog

LOG_TAB_CATEGORIES = ['accesos', 'valoraciones', 'planificacion', 'obras', 'fichajes']


def get_unread_logs_by_category(user_id, active_only=True):
    """Devuelve {categoria: count} con entradas no leídas (>0)."""
    prefs = {
        p.category: p
        for p in LogPreference.query.filter_by(user_id=user_id).all()
    }
    unread = {}

    for cat in LOG_TAB_CATEGORIES:
        pref = prefs.get(cat)
        if active_only and (not pref or not pref.is_active):
            continue
        last_read = pref.last_read_at if pref else datetime.min.replace(tzinfo=timezone.utc)
        count = SystemLog.query.filter(
            SystemLog.category == cat,
            SystemLog.timestamp > last_read,
        ).count()
        if count > 0:
            unread[cat] = count

    return unread


def get_total_unread_logs(user_id):
    return sum(get_unread_logs_by_category(user_id, active_only=True).values())
