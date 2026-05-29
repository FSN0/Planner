from datetime import date, timedelta
import calendar
from app.models import Asignacion, User, ROLE_CURRANTE
from sqlalchemy import func

def get_header_day_data(year, month, selected_date_obj):
    """
    Genera una lista de diccionarios para cada día del mes.
    Cada día contiene:
    - date_str: 'YYYY-MM-DD'
    - day_num: 1, 2, 3...
    - weekday: 'LUN', 'MAR'...
    - free_count: Nº libres
    - ins: Nº personas que EMPIEZAN asignación ese día
    - outs: Nº personas que TERMINAN asignación el día anterior
    - is_selected: True si coincide con selected_date_obj
    """
    _, last_day = calendar.monthrange(year, month)
    header_days = []
    
    # Total activos base
    total_active = User.query.filter_by(role=ROLE_CURRANTE, active=True, is_deleted=False).count()

    # Pre-cargar todas las asignaciones del mes para no hacer 30 queries
    start_month = date(year, month, 1)
    end_month = date(year, month, last_day)
    
    # Query optimizada: obtener todas las tuplas (fecha, user_id)
    raw_assignments = Asignacion.query.filter(
        Asignacion.fecha.between(start_month - timedelta(days=1), end_month)
    ).with_entities(Asignacion.fecha, Asignacion.user_id).all()
    
    # Mapa: fecha -> set(user_ids)
    assignments_map = {}
    for d, uid in raw_assignments:
        assignments_map.setdefault(d, set()).add(uid)

    days_es = ['DOM','LUN','MAR','MIÉ','JUE','VIE','SÁB']

    for day in range(1, last_day + 1):
        current_dt = date(year, month, day)
        prev_dt = current_dt - timedelta(days=1)
        
        users_today = assignments_map.get(current_dt, set())
        users_prev = assignments_map.get(prev_dt, set())
        
        # Cálculos
        free_count = total_active - len(users_today)
        if free_count < 0: free_count = 0 # Por seguridad
        
        # Entradas: Hoy están, ayer no estaban
        ins = len(users_today - users_prev)
        
        # Salidas: Ayer estaban, hoy no están
        outs = len(users_prev - users_today)
        
        # Weekday ajuste (Python 0=Lunes, mi array 0=Domingo requiere ajuste)
        wd_idx = (current_dt.weekday() + 1) % 7 
        
        header_days.append({
            'date_str': current_dt.strftime('%Y-%m-%d'),
            'date_human': current_dt.strftime('%d/%m/%Y'),
            'day_num': day,
            'weekday': days_es[wd_idx],
            'free_count': free_count,
            'ins': ins,
            'outs': outs,
            'is_selected': (current_dt == selected_date_obj)
        })
        
    return header_days