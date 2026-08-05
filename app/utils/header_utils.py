from datetime import date, timedelta
import calendar
from app.models import Asignacion, User, ROLE_OPERARIO


def get_header_day_data(year, month, selected_date_obj):
    """
    Genera una lista de diccionarios para cada día del mes.
    Cada día contiene:
    - date_str: 'YYYY-MM-DD'
    - day_num: 1, 2, 3...
    - weekday: abreviatura según idioma activo
    - free_count: Nº libres
    - ins: Nº personas que EMPIEZAN asignación ese día
    - outs: Nº personas que TERMINAN asignación el día anterior
    - is_selected: True si coincide con selected_date_obj
    """
    from app.services.i18n_service import weekday_short

    _, last_day = calendar.monthrange(year, month)
    header_days = []

    total_active = User.query.filter_by(role=ROLE_OPERARIO, active=True, is_deleted=False).count()

    start_month = date(year, month, 1)
    end_month = date(year, month, last_day)

    raw_assignments = Asignacion.query.filter(
        Asignacion.fecha.between(start_month - timedelta(days=1), end_month)
    ).with_entities(Asignacion.fecha, Asignacion.user_id).all()

    assignments_map = {}
    for d, uid in raw_assignments:
        assignments_map.setdefault(d, set()).add(uid)

    for day in range(1, last_day + 1):
        current_dt = date(year, month, day)
        prev_dt = current_dt - timedelta(days=1)

        users_today = assignments_map.get(current_dt, set())
        users_prev = assignments_map.get(prev_dt, set())

        free_count = total_active - len(users_today)
        if free_count < 0:
            free_count = 0

        ins = len(users_today - users_prev)
        outs = len(users_prev - users_today)

        header_days.append({
            'date_str': current_dt.strftime('%Y-%m-%d'),
            'date_human': current_dt.strftime('%d/%m/%Y'),
            'day_num': day,
            'weekday': weekday_short(current_dt),
            'free_count': free_count,
            'ins': ins,
            'outs': outs,
            'is_selected': (current_dt == selected_date_obj)
        })

    return header_days
