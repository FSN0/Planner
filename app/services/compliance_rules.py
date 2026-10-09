"""Reglas puras de documentación, horas y estados de fichaje Odoo."""
from __future__ import annotations

import calendar
from datetime import date, time, timedelta
from decimal import Decimal, ROUND_HALF_UP


CENT = Decimal('0.01')


def cuantizar(value) -> Decimal | None:
    if value is None or value == '':
        return None
    try:
        return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)
    except Exception:
        return None


def horas_entre(inicio: time | None, fin: time | None) -> Decimal | None:
    if inicio is None or fin is None:
        return None
    a = inicio.hour * 60 + inicio.minute
    b = fin.hour * 60 + fin.minute
    if b <= a:
        return None
    return (Decimal(b - a) / Decimal(60)).quantize(CENT, rounding=ROUND_HALF_UP)


def horas_desde_datetimes(inicio, fin) -> Decimal | None:
    if inicio is None or fin is None or fin <= inicio:
        return None
    seconds = (fin - inicio).total_seconds()
    if seconds <= 0:
        return None
    return (Decimal(str(seconds)) / Decimal(3600)).quantize(CENT, rounding=ROUND_HALF_UP)


def importe_linea(horas, precio) -> Decimal | None:
    h = cuantizar(horas)
    p = cuantizar(precio)
    if h is None or p is None:
        return None
    return (h * p).quantize(CENT, rounding=ROUND_HALF_UP)


def normalizar_estado_odoo(raw) -> str | None:
    """borrador | validado | facturado, a partir del valor que mande Odoo."""
    if raw in (None, False, ''):
        return None
    if isinstance(raw, (list, tuple)):
        # selection M2O-style o (key, label)
        if len(raw) >= 2:
            for part in (raw[0], raw[1]):
                got = normalizar_estado_odoo(part)
                if got:
                    return got
            return None
        raw = raw[0]
    s = str(raw).strip().lower()
    if not s or s in ('false', 'none', 'null'):
        return None
    if any(k in s for k in ('factur', 'invoic', 'posted')):
        return 'facturado'
    if any(k in s for k in ('borrador', 'draft')):
        return 'borrador'
    if any(k in s for k in ('valid', 'confirm', 'approved', 'done')):
        return 'validado'
    return None


def _selection_parts(meta: dict) -> list[str]:
    """Extrae claves/etiquetas de un campo selection (lista o string dinámico)."""
    selection = meta.get('selection')
    parts: list[str] = []
    if isinstance(selection, (list, tuple)):
        for item in selection:
            if isinstance(item, (list, tuple)):
                for part in item[:2]:
                    if part not in (None, False, ''):
                        parts.append(str(part))
            elif item not in (None, False, ''):
                parts.append(str(item))
    elif isinstance(selection, str) and selection.strip():
        parts.append(selection)
    string = meta.get('string')
    if string:
        parts.append(str(string))
    return parts


def score_campo_estado_fichaje(name: str, meta: dict) -> int:
    """Cuántos de {borrador, validado, facturado} se reconocen en el campo."""
    found = set()
    for part in _selection_parts(meta or {}):
        got = normalizar_estado_odoo(part)
        if got:
            found.add(got)
    n = (name or '').lower()
    for token in (n,):
        got = normalizar_estado_odoo(token)
        if got:
            found.add(got)
    return len(found)


def campo_estado_parece_fichaje(name: str, meta: dict) -> bool:
    """True si el campo de Odoo parece el statusbar borrador/validado/facturado (ES o EN)."""
    meta = meta or {}
    score = score_campo_estado_fichaje(name, meta)
    if score >= 2:
        return True

    n = (name or '').lower()
    tipo = (meta.get('type') or '').lower()
    if tipo and tipo not in ('selection', 'char', 'text'):
        return False

    parts_blob = ' '.join(_selection_parts(meta)).lower()
    blob = f'{parts_blob} {n}'
    has_draft = any(k in blob for k in ('draft', 'borrador'))
    has_valid = any(k in blob for k in ('validat', 'validado', 'confirm', 'approved'))
    has_invoice = any(k in blob for k in ('invoic', 'factur', 'posted'))
    if has_draft and has_valid and has_invoice:
        return True
    if has_draft and has_invoice:
        return True

    # Statusbar Studio / custom: fields_get a veces no trae selection.
    nombre_ok = (
        n in (
            'state', 'x_studio_state', 'x_studio_estado', 'x_studio_status',
            'x_estado', 'x_estado_fichaje', 'estado_fichaje', 'estado',
            'status', 'x_status',
        )
        or 'estado' in n
        or n.endswith('_state')
        or n.endswith('_status')
        or 'studio_state' in n
        or 'studio_status' in n
        or 'studio_estado' in n
    )
    if not nombre_ok:
        return False
    if any(bad in n for bad in ('employee', 'partner', 'company', 'project', 'write', 'create', 'active')):
        return False
    selection = meta.get('selection')
    selection_vacia = (
        not isinstance(selection, (list, tuple))
        or len(selection) == 0
    )
    # Solo confiar en el nombre si no hay selection usable (Studio / related)
    return selection_vacia


def _add_months(d: date, months: int) -> date:
    m0 = d.month - 1 + int(months)
    year = d.year + m0 // 12
    month = m0 % 12 + 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(d.day, last))


def _add_years(d: date, years: int) -> date:
    years = int(years)
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        # 29-feb → último día de febrero del año destino
        return date(d.year + years, 2, 28)


def sugerir_caducidad(
    regla: str,
    dia: int | None = None,
    mes: int | None = None,
    hoy: date | None = None,
    *,
    periodo_anos: int | None = None,
) -> date | None:
    """Caducidad relativa al día de hoy (al subir / validar).

    - ninguna → sin fecha
    - mensual → hoy + 1 mes
    - anual → hoy + 1 año
    - anos → hoy + periodo_anos años (mín. 1)
    """
    hoy = hoy or date.today()
    regla = (regla or 'ninguna').strip().lower()
    if regla in ('', 'ninguna', 'none'):
        return None
    if regla == 'mensual':
        return _add_months(hoy, 1)
    if regla == 'anual':
        return _add_years(hoy, 1)
    if regla in ('anos', 'años', 'years', 'periodica', 'periodica_anos'):
        n = int(periodo_anos or 1)
        n = max(1, min(n, 50))
        return _add_years(hoy, n)
    # Compat: si llega día/mes antiguos sin regla reconocida, no inventar
    return None


def clasificar_aporte(aporte, *, obligatorio: bool, hoy: date, aviso_dias: int, es_certificacion: bool = False, cert_ok: bool | None = None) -> str:
    """
    falta | opcional_vacio | rechazado | pendiente_validar | caducado | por_caducar | ok | cert_pendiente | cert_ok
    """
    if es_certificacion:
        return 'cert_ok' if cert_ok else 'cert_pendiente'
    if aporte is None or getattr(aporte, 'estado', None) is None:
        return 'falta' if obligatorio else 'opcional_vacio'
    estado = aporte.estado
    if estado == 'rechazado':
        return 'rechazado'
    if estado != 'validado':
        return 'pendiente_validar'
    caduca = getattr(aporte, 'caduca_el', None)
    if caduca and caduca < hoy and not getattr(aporte, 'aceptado_caducado', False):
        return 'caducado'
    if caduca and hoy <= caduca <= hoy + timedelta(days=max(0, int(aviso_dias or 0))):
        return 'por_caducar'
    return 'ok'


def es_error_documental(codigo: str) -> bool:
    return codigo in ('falta', 'rechazado', 'caducado', 'pendiente_validar', 'cert_pendiente')


def es_aviso_documental(codigo: str) -> bool:
    return codigo == 'por_caducar'


def firma_lineas(filas) -> tuple:
    """Identidad de una propuesta: persona, obra, día, horas y precio. Sin inicio/fin."""
    rows = []
    for fila in filas:
        horas = cuantizar(fila.get('horas') if isinstance(fila, dict) else fila.horas)
        precio = cuantizar(fila.get('precio_hora') if isinstance(fila, dict) else fila.precio_hora)
        user_id = fila.get('user_id') if isinstance(fila, dict) else fila.user_id
        obra_id = fila.get('obra_id') if isinstance(fila, dict) else fila.obra_id
        fecha = fila.get('fecha') if isinstance(fila, dict) else fila.fecha
        fecha_s = fecha.isoformat() if hasattr(fecha, 'isoformat') else str(fecha)
        rows.append((
            int(user_id),
            int(obra_id),
            fecha_s,
            None if horas is None else format(horas, 'f'),
            None if precio is None else format(precio, 'f'),
        ))
    return tuple(sorted(rows))


def propuestas_coinciden(a, b) -> bool:
    fa = firma_lineas(a)
    fb = firma_lineas(b)
    if not fa or not fb:
        return False
    if any(row[3] is None or row[4] is None for row in fa + fb):
        return False
    return fa == fb


def intervalos_solapan(a0, a1, b0, b1) -> bool:
    if not a0 or not a1 or not b0 or not b1:
        return False
    return a0 < b1 and b0 < a1


def email_es_real(email: str | None) -> bool:
    email = (email or '').strip().lower()
    if not email or '@' not in email:
        return False
    for suffix in (
        '@local.signaplan',
        '@demo.signaplan',
        '@subcontrata.local',
        '@pending.local',
    ):
        if email.endswith(suffix):
            return False
    return True


def estado_fichaje_agregado(estados) -> str | None:
    limpios = [e for e in estados if e]
    if not limpios:
        return None
    if 'facturado' in limpios:
        return 'facturado'
    if 'borrador' in limpios:
        return 'borrador'
    if 'validado' in limpios:
        return 'validado'
    return None


def fichaje_verificado(estado: str | None) -> bool:
    return estado in ('validado', 'facturado')
