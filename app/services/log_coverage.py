"""Cobertura de días de un SystemLog agrupado (cuadrante).

El listado de Planificación guarda UNA fila por acción (rango).
Persona a día proyecta esa fila sobre cada jornada que cubre.

Si los días no son un calendario corrido (p. ej. solo laborables), se
añade un marcador [[cov:...]] al detalle. La UI lo oculta; la proyección
lo usa para no pintar sábados que no se asignaron.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

_COV_RE = re.compile(r"(?:\r?\n|\s)*\[\[cov:([0-9,\-]+)\]\]\s*$")
_PLANIF_DETAIL_DATES_RE = re.compile(
    r"\((\d{2}/\d{2}/\d{4})(?:\s*→\s*(\d{2}/\d{2}/\d{4}))?"
)


def dates_are_contiguous(days):
    uniq = sorted({d for d in days if d})
    if len(uniq) <= 1:
        return True
    return (uniq[-1] - uniq[0]).days + 1 == len(uniq)


def attach_coverage(detail, dates):
    """Añade marcador solo si hay huecos. Rangos corridos se leen del texto."""
    days = sorted({d for d in (dates or []) if d})
    if len(days) < 2 or dates_are_contiguous(days):
        return detail or ""
    payload = ",".join(d.isoformat() for d in days)
    return f"{(detail or '').rstrip()} [[cov:{payload}]]"


def strip_coverage(detail):
    if not detail:
        return ""
    return _COV_RE.sub("", detail).rstrip()


def parse_coverage_dates(detail):
    if not detail:
        return None
    match = _COV_RE.search(detail)
    if not match:
        return None
    out = []
    for part in match.group(1).split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(date.fromisoformat(part))
        except ValueError:
            continue
    return out


def planif_detail_covers_day(detail, fecha_obj):
    """True si el texto de un log de cuadrante cubre esa fecha (un día o un rango)."""
    if not fecha_obj:
        return False
    covered = parse_coverage_dates(detail)
    if covered is not None:
        return fecha_obj in covered
    match = _PLANIF_DETAIL_DATES_RE.search(strip_coverage(detail) or "")
    if not match:
        return False
    try:
        ini = datetime.strptime(match.group(1), "%d/%m/%Y").date()
        fin = (
            datetime.strptime(match.group(2), "%d/%m/%Y").date()
            if match.group(2)
            else ini
        )
    except ValueError:
        return False
    if fin < ini:
        ini, fin = fin, ini
    return ini <= fecha_obj <= fin


def expand_contiguous(fecha_inicio, fecha_fin):
    if not fecha_inicio:
        return []
    last = fecha_fin or fecha_inicio
    if last < fecha_inicio:
        fecha_inicio, last = last, fecha_inicio
    days = []
    cur = fecha_inicio
    while cur <= last:
        days.append(cur)
        cur += timedelta(days=1)
    return days
