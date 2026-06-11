# app/services/person_day_timeline_service.py
import re
from datetime import datetime, date

from flask import url_for
from markupsafe import Markup, escape

from app.models import User, SystemLog, RegistroFichaje, Obra
from app.services.core_assignment_service import CoreAssignmentService
from app.utils.timezone_utils import format_datetime, format_time

SYSTEM_ACTOR = "Sistema Automático"
SYSTEM_ACTIONS = {
    "Auto-asignación por Fichaje Físico",
    "Actualización de Cuadrante (Auto)",
}

format_obra_label = CoreAssignmentService.format_obra_label

CATEGORY_STYLES = {
    "fichaje_app": {"icon": "fa-mobile-alt", "color": "#0369a1"},
    "fichajes": {"icon": "fa-balance-scale", "color": "#6d28d9"},
    "planificacion": {"icon": "fa-calendar-check", "color": "#047857"},
    "default": {"icon": "fa-cog", "color": "#64748b"},
}

ACTION_TITLE_ALIASES = {
    "Resolución de Fichaje: Error al Planificar": "Borrar Planificación",
    "Resolución de Fichaje: Error Al Planificar": "Borrar Planificación",
    "Resolución de Fichaje: Borrar Planificacion": "Resolución de Fichaje: Borrar Planificación",
}

LEGACY_SHORT_FICHAJE_DETAILS = {
    "Ignorado",
    "Ausencia confirmada manualmente.",
    "Planificación eliminada (Error al planificar).",
    "Reasignado a la obra real",
    "Añadida multi-asignación (Pluriempleo).",
    "Añadida multi-asignación (pluriempleo).",
}


def _normalize_title(action):
    title = (action or "").strip()
    for prefix in ("📍 ", "📅 ", "⚖️ "):
        if title.startswith(prefix):
            title = title[len(prefix):]
    return ACTION_TITLE_ALIASES.get(title, title)


def _enrich_legacy_fichaje_detail(log, detail):
    if log.category != "fichajes" or not detail:
        return detail
    if detail not in LEGACY_SHORT_FICHAJE_DETAILS:
        if "Error al planificar" in detail:
            return detail.replace(" (Error al planificar)", "").replace(
                "(Error al planificar)", ""
            ).strip()
        return detail

    regs = RegistroFichaje.query.filter_by(
        user_id=log.target_user_id,
        fecha=log.target_date,
    ).filter(RegistroFichaje.resuelto_por_id.isnot(None)).all()

    if not regs:
        return detail.replace(" (Error al planificar)", "").strip()

    reg = regs[0]
    if len(regs) > 1 and log.timestamp:
        with_ts = [r for r in regs if r.fecha_auditoria]
        if with_ts:
            reg = min(
                with_ts,
                key=lambda r: abs((r.fecha_auditoria - log.timestamp).total_seconds()),
            )

    obra_real = format_obra_label(Obra.query.get(reg.obra_real_id)) if reg.obra_real_id else None
    obra_plan = (
        format_obra_label(Obra.query.get(reg.obra_planificada_id))
        if reg.obra_planificada_id
        else None
    )

    if detail == "Ignorado":
        if obra_real and obra_plan and obra_real != obra_plan:
            return (
                f"Se ignora el fichaje en '{obra_real}' "
                f"(estaba planificado en '{obra_plan}')."
            )
        if obra_real:
            return f"Se ignora el fichaje en '{obra_real}'."
        if obra_plan:
            return f"Se ignora la incidencia en '{obra_plan}'."
    elif detail == "Ausencia confirmada manualmente." and obra_plan:
        return f"Ausencia confirmada: no acudió a '{obra_plan}'."
    elif "Error al planificar" in detail:
        if obra_plan:
            return (
                f"Se elimina la planificación en '{obra_plan}' "
                f"(el operario no fichó en esa obra)."
            )
        return "Planificación eliminada."
    elif detail == "Reasignado a la obra real":
        if obra_plan and obra_real:
            return f"Cuadrante actualizado: de '{obra_plan}' a '{obra_real}'."
        if obra_real:
            return f"Reasignado a '{obra_real}'."
    elif "multi-asignación" in detail.lower() and obra_real:
        return f"Añadida asignación en '{obra_real}' (pluriempleo)."

    return detail


def _resolve_actor(log, user):
    action = log.action or ""
    if action in SYSTEM_ACTIONS or "(Auto)" in action:
        return SYSTEM_ACTOR
    if log.category == "fichaje_app":
        return f"{user.name} {user.lastname} (Fichaje en App)"
    if log.category == "planificacion" and "(Auto)" in action:
        return SYSTEM_ACTOR
    if log.user:
        return f"{log.user.name} {log.user.lastname}".strip()
    return "Sistema"


def _lookup_obra(fragment, cache):
    raw = (fragment or "").strip()
    if not raw:
        return None

    key = raw.lower()
    if key in cache:
        return cache[key]

    obra = None
    if "—" in raw:
        codigo_part = raw.split("—", 1)[0].strip()
        obra = Obra.query.filter(Obra.codigo.ilike(codigo_part)).first()

    if not obra:
        obra = Obra.query.filter(Obra.codigo.ilike(raw)).first()

    if not obra:
        obra = Obra.query.filter(Obra.nombre.ilike(raw)).first()

    if not obra and len(raw) > 3:
        obra = Obra.query.filter(Obra.nombre.ilike(f"%{raw}%")).first()

    cache[key] = obra
    return obra


def _obra_label_for_fragment(fragment, cache):
    obra = _lookup_obra(fragment, cache)
    return format_obra_label(obra) if obra else fragment.strip()


def _normalize_detail_obras(text, cache):
    if not text:
        return text

    def repl_ficho(match):
        label = _obra_label_for_fragment(match.group(1), cache)
        return f"fichó en {label}."

    text = re.sub(r"fichó en ([^.]+)\.", repl_ficho, text, flags=re.IGNORECASE)

    def repl_arrow(match):
        label = _obra_label_for_fragment(match.group(1), cache)
        return f"→ '{label}'"

    text = re.sub(r"→ '([^']+)'", repl_arrow, text)

    def repl_en_quoted(match):
        prefix = match.group(1)
        label = _obra_label_for_fragment(match.group(2), cache)
        return f"{prefix}'{label}'"

    text = re.sub(
        r"(sin planificar en |en )'([^']+)'",
        repl_en_quoted,
        text,
        flags=re.IGNORECASE,
    )

    return text


def _utc_time_label_to_local(hm, target_date):
    """Convierte HH:MM guardado en UTC (texto de logs antiguos) a hora local."""
    if not hm or not target_date:
        return hm
    try:
        t = datetime.strptime(hm, "%H:%M").time()
        dt_utc = datetime.combine(target_date, t)
        return format_time(dt_utc)
    except ValueError:
        return hm


def _fichaje_detail_uses_utc(text, target_date, log_timestamp):
    """Detecta logs antiguos con Entrada/Salida en UTC (no en hora local)."""
    match = re.search(r"Entrada: (\d{2}:\d{2})", text or "")
    if not match or not log_timestamp:
        return False
    entrada = match.group(1)
    ts_local = format_datetime(log_timestamp, "%H:%M")
    if entrada == ts_local:
        return False
    return _utc_time_label_to_local(entrada, target_date) == ts_local


def _normalize_fichaje_times_in_detail(text, target_date, log_timestamp=None):
    if not text or not target_date:
        return text
    if not _fichaje_detail_uses_utc(text, target_date, log_timestamp):
        return text

    def repl_entrada(match):
        return f"Entrada: {_utc_time_label_to_local(match.group(1), target_date)}"

    def repl_salida(match):
        return f"Salida: {_utc_time_label_to_local(match.group(1), target_date)}"

    def repl_hora_detectada(match):
        return f"Hora detectada: {_utc_time_label_to_local(match.group(1), target_date)}"

    text = re.sub(r"Entrada: (\d{2}:\d{2})", repl_entrada, text)
    text = re.sub(r"Salida: (\d{2}:\d{2})", repl_salida, text)
    text = re.sub(r"Hora detectada: (\d{2}:\d{2})", repl_hora_detectada, text)
    return text


def _worker_panel_url(user_id):
    if not user_id:
        return None
    return url_for("admin.worker_panel", user_id=user_id)


def _obra_panel_url(obra_id):
    if not obra_id:
        return None
    return url_for("admin.obra_panel", obra_id=obra_id)


def _link_obras_in_text(text, obra_cache):
    if not text:
        return ""

    html = str(escape(text))
    linked_ids = set()

    for obra in obra_cache.values():
        if not obra or obra.id in linked_ids:
            continue
        linked_ids.add(obra.id)
        label = format_obra_label(obra)
        escaped_label = str(escape(label))
        if escaped_label not in html:
            continue
        obra_url = _obra_panel_url(obra.id)
        link = (
            f'<a href="{obra_url}" class="pdt-link pdt-link-obra" '
            f'target="_blank" rel="noopener" title="Ver obra">{escaped_label}</a>'
        )
        html = html.replace(escaped_label, link)

    return Markup(html)


def _link_subject_in_text(html, subject_user):
    if not subject_user:
        return html

    full_name = f"{subject_user.name} {subject_user.lastname}".strip()
    escaped_name = str(escape(full_name))
    html_str = str(html)
    if escaped_name not in html_str:
        return Markup(html_str)

    worker_url = _worker_panel_url(subject_user.id)
    link = (
        f'<a href="{worker_url}" class="pdt-link pdt-link-user" '
        f'target="_blank" rel="noopener" title="Ver ficha">{escaped_name}</a>'
    )
    return Markup(html_str.replace(escaped_name, link, 1))


def _append_fichaje_notes_from_registro(log, detail):
    """Añade notas Odoo al detalle del log si el registro local las tiene."""
    if log.category != 'fichaje_app' or not detail or 'Notas:' in detail:
        return detail
    if not log.target_user_id or not log.target_date:
        return detail

    regs = RegistroFichaje.query.filter_by(
        user_id=log.target_user_id,
        fecha=log.target_date,
    ).filter(RegistroFichaje.nota_odoo.isnot(None)).all()

    for reg in regs:
        note = (reg.nota_odoo or '').strip()
        if not note:
            continue
        obra = Obra.query.get(reg.obra_real_id) if reg.obra_real_id else None
        if not obra:
            continue
        label = format_obra_label(obra)
        codigo = (obra.codigo or '').strip()
        if label in detail or (codigo and codigo in detail):
            return f"{detail.rstrip('.')} Notas: {note}"
    return detail


def _build_detail_html(text, obra_cache, subject_user, target_date=None, log_timestamp=None, log=None):
    plain = _enrich_legacy_fichaje_detail(log, text or "") if log else (text or "")
    plain = _append_fichaje_notes_from_registro(log, plain) if log else plain
    plain = _normalize_detail_obras(plain, obra_cache)
    plain = _normalize_fichaje_times_in_detail(plain, target_date, log_timestamp)
    html = _link_obras_in_text(plain, obra_cache)
    return plain, _link_subject_in_text(html, subject_user)


def _category_style(log):
    if log.category == "fichaje_app":
        return CATEGORY_STYLES["fichaje_app"], 0
    if log.category == "fichajes":
        return CATEGORY_STYLES["fichajes"], 1
    if log.category == "planificacion":
        style = dict(CATEGORY_STYLES["planificacion"])
        if not (log.detail or "").startswith("Asignado"):
            style["icon"] = "fa-trash-alt"
        return style, 2
    return CATEGORY_STYLES["default"], 3


def _build_hito(log, user, obra_cache):
    detail, detail_html = _build_detail_html(
        log.detail, obra_cache, user, log.target_date, log.timestamp, log
    )
    style, prioridad = _category_style(log)
    autor = _resolve_actor(log, user)

    actor_user_id = None
    if autor != SYSTEM_ACTOR and log.user_id:
        actor_user_id = log.user_id
    elif log.category == "fichaje_app":
        actor_user_id = user.id

    local_ts = format_datetime(log.timestamp, "%Y-%m-%d %H:%M:%S")
    return {
        "id": log.id,
        "sort_time": local_ts,
        "prioridad": prioridad,
        "fecha": format_datetime(log.timestamp, "%d/%m %H:%M"),
        "icon_class": style["icon"],
        "icon_color": style["color"],
        "titulo": _normalize_title(log.action),
        "autor": autor,
        "actor_user_id": actor_user_id,
        "actor_url": _worker_panel_url(actor_user_id),
        "descripcion": detail,
        "descripcion_html": str(detail_html),
    }


def build_person_day_timeline(user_id, fecha_obj):
    user = User.query.get(user_id)
    if not user:
        return None

    if isinstance(fecha_obj, str):
        fecha_obj = datetime.strptime(fecha_obj, "%Y-%m-%d").date()
    elif isinstance(fecha_obj, datetime):
        fecha_obj = fecha_obj.date()

    logs_del_dia = (
        SystemLog.query.filter_by(target_user_id=user_id, target_date=fecha_obj)
        .order_by(SystemLog.timestamp.asc())
        .all()
    )

    obra_cache = {}
    hitos = [_build_hito(log, user, obra_cache) for log in logs_del_dia]
    hitos.sort(key=lambda x: (x["sort_time"], x["prioridad"]))

    if not hitos:
        hitos = [{
            "sort_time": "0000-00-00 00:00:00",
            "fecha": "--/-- --:--",
            "icon_class": "fa-ghost",
            "icon_color": "#94a3b8",
            "titulo": "Sin actividad",
            "autor": "-",
            "actor_user_id": None,
            "actor_url": None,
            "descripcion": "No hay ningún evento histórico registrado en el sistema para este día.",
            "descripcion_html": "No hay ningún evento histórico registrado en el sistema para este día.",
        }]

    registro = RegistroFichaje.query.filter_by(user_id=user_id, fecha=fecha_obj).first()
    if registro and registro.estado:
        estado_actual = registro.estado
    elif hitos and hitos[0].get("titulo") != "Sin actividad":
        estado_actual = "Actividad registrada"
    else:
        estado_actual = "Sin registro"

    return {
        "success": True,
        "empleado": f"{user.name} {user.lastname}",
        "empleado_url": _worker_panel_url(user.id),
        "target_user_id": user.id,
        "fecha": fecha_obj.strftime("%d/%m/%Y"),
        "fecha_iso": fecha_obj.strftime("%Y-%m-%d"),
        "estado_actual": estado_actual,
        "hitos": hitos,
    }
