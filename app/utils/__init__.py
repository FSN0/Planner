# app/utils/__init__.py

from .date_utils import get_calendar_info
from .timezone_utils import (
    utc_now, now_local, today_local, format_datetime, format_time, format_date,
    get_app_timezone, get_user_timezone, COMMON_TIMEZONES, DEFAULT_TIMEZONE,
    invalidate_app_timezone_cache, parse_odoo_datetime,
)
from app.models import db, SystemLog

def register_log(user_id, category, action, detail="", target_user_id=None, target_date=None):
    """Guarda un registro de auditoría en la base de datos."""
    try:
        nuevo_log = SystemLog(
            user_id=user_id,
            category=category,
            action=action,
            detail=detail,
            target_user_id=target_user_id,
            target_date=target_date
        )
        db.session.add(nuevo_log)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        pass