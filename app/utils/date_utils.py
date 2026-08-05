# app/utils/date_utils.py
import calendar
from datetime import datetime, date

def get_calendar_info(selected_date):
    """
    Dado un objeto date, retorna un diccionario con:
      - year: año de la fecha
      - month: mes de la fecha
      - last_day: último día del mes
      - month_name: nombre del mes (idioma activo)
    """
    year = selected_date.year
    month = selected_date.month
    last_day = calendar.monthrange(year, month)[1]
    try:
        from app.services.i18n_service import month_name as i18n_month_name
        name = i18n_month_name(month)
    except Exception:
        name = calendar.month_name[month]
    return {"year": year, "month": month, "last_day": last_day, "month_name": name}

def parse_date(date_str, default=None):
    """
    Intenta convertir 'date_str' en un objeto date con el formato "%Y-%m-%d".
    Si falla, devuelve 'default' o date.today() si default es None.
    """
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return default or date.today()

def get_selected_date(request_args):
    """
    Obtiene la fecha seleccionada a partir de los argumentos de la petición.
    """
    date_str = request_args.get('selected_date')
    return parse_date(date_str)

def get_weekday_initial(year, month, day):
    from datetime import date
    # Mapeo: lunes: L, martes: M, miércoles: X, jueves: J, viernes: V, sábado: S, domingo: D
    mapping = {0: 'L', 1: 'M', 2: 'X', 3: 'J', 4: 'V', 5: 'S', 6: 'D'}
    dt = date(year, month, day)
    return mapping.get(dt.weekday(), '')