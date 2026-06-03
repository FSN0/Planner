# app/utils/__init__.py

from .date_utils import get_calendar_info
from app.models import db, SystemLog

def register_log(user_id, category, action, detail=""):
    """Guarda un registro de auditoría en la base de datos."""
    try:
        nuevo_log = SystemLog(
            user_id=user_id,
            category=category,
            action=action,
            detail=detail
        )
        db.session.add(nuevo_log)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        pass