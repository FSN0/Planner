# app/services/person_day_timeline_service.py
import re
from datetime import datetime, date, timedelta

from flask import url_for
from markupsafe import Markup, escape

from app.models import User, SystemLog, RegistroFichaje, Obra
from app.services.core_assignment_service import CoreAssignmentService
from app.services.log_coverage import planif_detail_covers_day, strip_coverage
from app.utils.timezone_utils import format_datetime, format_time

MAX_TIMELINE_RANGE_DAYS = 31


def _parse_fecha(fecha_obj):
    if isinstance(fecha_obj, str):
        return datetime.strptime(fecha_obj, "%Y-%m-%d").date()
    if isinstance(fecha_obj, datetime):
        return fecha_obj.date()
    if isinstance(fecha_obj, date):
        return fecha_obj
    raise ValueError("Fecha inválida")

SYSTEM_ACTOR = "Sistema Automático"
SYSTEM_ACTIONS = {
    "Auto-asignación por Fichaje Físico",
    # Legacy: aceptar Paracaidista/Conflicto con «Añadir» se grababa así
    # sin autor. Los logs nuevos usan «Resolución de Fichaje: Añadir».
    "Actualización de Cuadrante (Auto)",
}
ACTION_ANADIR = "Resolución de Fichaje: Añadir"
ACTION_CUADRANTE_AUTO_LEGACY = "Actualización de Cuadrante (Auto)"

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
    ACTION_CUADRANTE_AUTO_LEGACY: ACTION_ANADIR,
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


def _infer_anadir_auditor(log):
    """
    Logs viejos de «Añadir» se grabaron como Actualización de Cuadrante (Auto)
    con user_id vacío. El autor está en la resolución de fichaje hermana.
    """
    if (log.action or "") != ACTION_CUADRANTE_AUTO_LEGACY:
        return None, None
    if not log.target_user_id or not log.target_date:
        return None, None

    sibling = (
        SystemLog.query.filter_by(
            category="fichajes",
            action=ACTION_ANADIR,
            target_user_id=log.target_user_id,
            target_date=log.target_date,
        )
        .filter(SystemLog.user_id.isnot(None))
        .order_by(SystemLog.timestamp.desc())
        .first()
    )
    if sibling and sibling.user:
        if log.timestamp and sibling.timestamp:
            delta = abs((log.timestamp - sibling.timestamp).total_seconds())
            if delta > 30:
                sibling = None
        if sibling and sibling.user:
            name = f"{sibling.user.name} {sibling.user.lastname}".strip()
            return name, sibling.user_id

    registro = (
        RegistroFichaje.query.filter_by(
            user_id=log.target_user_id,
            fecha=log.target_date,
        )
        .filter(RegistroFichaje.resuelto_por_id.isnot(None))
        .filter(RegistroFichaje.estado.in_(("Resuelto_Asignado", "Resuelto_Dividido")))
        .order_by(RegistroFichaje.fecha_auditoria.desc())
        .first()
    )
    if registro and registro.resuelto_por_id:
        auditor = User.query.get(registro.resuelto_por_id)
        if auditor:
            name = f"{auditor.name} {auditor.lastname}".strip()
            return name, auditor.id
    return None, None


def _resolve_actor(log, user):
    action = log.action or ""
    if log.category == "fichaje_app":
        return (
            f"{user.name} {user.lastname} (Fichaje en App)",
            user.id if user else None,
        )
    if log.user:
        return f"{log.user.name} {log.user.lastname}".strip(), log.user_id
    inferred_name, inferred_id = _infer_anadir_auditor(log)
    if inferred_name:
        return inferred_name, inferred_id
    if action in SYSTEM_ACTIONS or "(Auto)" in action:
        return SYSTEM_ACTOR, None
    return "Sistema", None


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
        from app.services.i18n_service import translate
        link = (
            f'<a href="{obra_url}" class="pdt-link pdt-link-obra" '
            f'target="_blank" rel="noopener" title="{translate("Ver obra")}">{escaped_label}</a>'
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
    from app.services.i18n_service import translate
    link = (
        f'<a href="{worker_url}" class="pdt-link pdt-link-user" '
        f'target="_blank" rel="noopener" title="{translate("Ver ficha")}">{escaped_name}</a>'
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
    plain = strip_coverage(text or "")
    plain = _enrich_legacy_fichaje_detail(log, plain) if log else plain
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
    autor, actor_user_id = _resolve_actor(log, user)

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


def _extra_planificacion_logs_covering(user_id, fecha_obj, already_ids=None):
    """
    Un rango de cuadrante es UN SystemLog (target_date = primer día).
    El histórico de un día posterior proyecta esa misma fila (autor y hora reales).
    """
    already_ids = set(already_ids or [])
    q = (
        SystemLog.query.filter_by(target_user_id=user_id, category="planificacion")
        .filter(SystemLog.target_date.isnot(None))
        .filter(SystemLog.target_date <= fecha_obj)
        .filter(SystemLog.target_date >= fecha_obj - timedelta(days=400))
        .order_by(SystemLog.timestamp.asc())
    )
    extra = []
    for log in q.all():
        if log.id in already_ids:
            continue
        if planif_detail_covers_day(log.detail, fecha_obj):
            extra.append(log)
    return extra


def _planificacion_log_covers_obra(logs, obra):
    if not obra:
        return False
    label = format_obra_label(obra)
    codigo = (obra.codigo or "").strip()
    nombre = (obra.nombre or "").strip()
    for log in logs:
        if log.category != "planificacion":
            continue
        detail = log.detail or ""
        if "Asignado" not in detail:
            continue
        if label and label in detail:
            return True
        if codigo and codigo in detail:
            return True
        if nombre and nombre in detail:
            return True
    return False


def _synthetic_asignacion_hito(user, obra, fecha_obj, created_at=None, source_id=None):
    """Hito de planificación cuando existe Asignacion/obra_planificada sin SystemLog."""
    label = format_obra_label(obra)
    user_nombre = f"{user.name} {user.lastname}".strip() if user else "Operario"
    detail = (
        f"Asignado {user_nombre} → '{label}' "
        f"({fecha_obj.strftime('%d/%m/%Y')})."
    )
    style = CATEGORY_STYLES["planificacion"]
    if created_at:
        local_ts = format_datetime(created_at, "%Y-%m-%d %H:%M:%S")
        fecha_txt = format_datetime(created_at, "%d/%m %H:%M")
    else:
        # Sin timestamp real: no inventar hora (antes: 06:00 UTC → 08:00 en verano).
        local_ts = fecha_obj.strftime("%Y-%m-%d") + " 00:00:00"
        fecha_txt = fecha_obj.strftime("%d/%m")
    return {
        "id": f"asig-{source_id or obra.id}-{fecha_obj.isoformat()}",
        "sort_time": local_ts,
        "prioridad": 2,
        "fecha": fecha_txt,
        "icon_class": style["icon"],
        "icon_color": style["color"],
        "titulo": "Planificación",
        "autor": "Planificación",
        "actor_user_id": None,
        "actor_url": None,
        "descripcion": detail,
        "descripcion_html": str(_link_obras_in_text(detail, {label.lower(): obra} if label else {})),
    }


def _append_missing_planificacion_hitos(hitos, logs, user, fecha_obj, obra_cache):
    """
    Si hay asignación (o obra planificada en el registro de fichaje) sin log de
    planificación, añade el hito para que la actividad del día cuente la historia.
    """
    from app.models import Asignacion

    obra_ids = set()
    created_by_obra = {}

    for asig in Asignacion.query.filter_by(user_id=user.id, fecha=fecha_obj).all():
        if asig.obra_id:
            obra_ids.add(asig.obra_id)
            if asig.created_at and asig.obra_id not in created_by_obra:
                created_by_obra[asig.obra_id] = asig.created_at

    for reg in RegistroFichaje.query.filter_by(user_id=user.id, fecha=fecha_obj).all():
        if reg.obra_planificada_id:
            obra_ids.add(reg.obra_planificada_id)

    if not obra_ids:
        return hitos

    out = list(hitos or [])
    # Quitar placeholder "Sin actividad" si vamos a añadir hechos reales
    if len(out) == 1 and out[0].get("titulo") == "Sin actividad":
        out = []

    for obra_id in sorted(obra_ids):
        obra = Obra.query.get(obra_id)
        if not obra:
            continue
        obra_cache[(obra.codigo or "").lower()] = obra
        obra_cache[(obra.nombre or "").lower()] = obra
        if _planificacion_log_covers_obra(logs, obra):
            continue
        # Evitar duplicar si ya hay hito sintético/real con el mismo label
        label = format_obra_label(obra)
        already = False
        for h in out:
            if h.get("titulo") in ("Planificación",) or "Asignado" in (h.get("descripcion") or ""):
                if label and label in (h.get("descripcion") or ""):
                    already = True
                    break
        if already:
            continue
        out.append(
            _synthetic_asignacion_hito(
                user,
                obra,
                fecha_obj,
                created_at=created_by_obra.get(obra_id),
                source_id=obra_id,
            )
        )

    out.sort(key=lambda x: (x.get("sort_time") or "", x.get("prioridad") or 0))
    return out


def _localize_hito(hito, user, obra_cache):
    from app.services.i18n_service import (
        translate,
        translate_log_action,
        translate_log_actor,
        translate_log_detail,
    )

    titulo_raw = hito.get("titulo") or ""
    empty = titulo_raw == "Sin actividad"
    autor_raw = hito.get("autor") or ""
    desc = translate_log_detail(hito.get("descripcion") or "")
    html = _link_obras_in_text(desc, obra_cache)
    html = _link_subject_in_text(html, user)
    item = dict(hito)
    item["empty"] = empty
    item["titulo"] = translate("Sin actividad") if empty else translate_log_action(titulo_raw)
    item["autor"] = translate_log_actor(autor_raw)
    item["actor_is_system"] = autor_raw in (SYSTEM_ACTOR, "Sistema", "-")
    item["descripcion"] = desc
    item["descripcion_html"] = str(html)
    return item


def build_person_day_timeline(user_id, fecha_obj):
    user = User.query.get(user_id)
    if not user:
        return None

    fecha_obj = _parse_fecha(fecha_obj)

    logs_del_dia = (
        SystemLog.query.filter_by(target_user_id=user_id, target_date=fecha_obj)
        .order_by(SystemLog.timestamp.asc())
        .all()
    )
    already_ids = [log.id for log in logs_del_dia]
    logs_del_dia = list(logs_del_dia) + _extra_planificacion_logs_covering(
        user_id, fecha_obj, already_ids
    )

    obra_cache = {}
    hitos = [_build_hito(log, user, obra_cache) for log in logs_del_dia]
    hitos = _append_missing_planificacion_hitos(
        hitos, logs_del_dia, user, fecha_obj, obra_cache
    )
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

    registros = RegistroFichaje.query.filter_by(user_id=user_id, fecha=fecha_obj).all()
    if registros:
        from app.services.fichaje_estado_service import estado_fichaje_agregado
        estado_actual = estado_fichaje_agregado([r.estado for r in registros])
    elif hitos and hitos[0].get("titulo") != "Sin actividad":
        estado_actual = "Actividad registrada"
    else:
        estado_actual = "Sin registro"

    hitos = [_localize_hito(h, user, obra_cache) for h in hitos]

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


def build_person_day_timeline_range(user_id, fecha_inicio, fecha_fin):
    """Historial apilado por día entre fecha_inicio y fecha_fin (inclusive)."""
    user = User.query.get(user_id)
    if not user:
        return None

    from app.services.i18n_service import translate

    try:
        fecha_inicio = _parse_fecha(fecha_inicio)
        fecha_fin = _parse_fecha(fecha_fin)
    except (TypeError, ValueError):
        return {"success": False, "error": translate("Formato de fecha inválido (YYYY-MM-DD)")}

    if fecha_fin < fecha_inicio:
        return {
            "success": False,
            "error": translate("La fecha fin debe ser posterior o igual a la fecha inicio"),
        }

    num_days = (fecha_fin - fecha_inicio).days + 1
    if num_days > MAX_TIMELINE_RANGE_DAYS:
        return {
            "success": False,
            "error": translate(
                "El rango máximo es de {n} días", n=MAX_TIMELINE_RANGE_DAYS
            ),
        }

    days = []
    current = fecha_inicio
    while current <= fecha_fin:
        day_data = build_person_day_timeline(user_id, current)
        days.append({
            "fecha": day_data["fecha"],
            "fecha_iso": day_data["fecha_iso"],
            "estado_actual": day_data["estado_actual"],
            "hitos": day_data["hitos"],
        })
        current += timedelta(days=1)

    if fecha_inicio == fecha_fin:
        fecha_label = fecha_inicio.strftime("%d/%m/%Y")
    else:
        fecha_label = (
            f"{fecha_inicio.strftime('%d/%m/%Y')} – {fecha_fin.strftime('%d/%m/%Y')}"
        )

    return {
        "success": True,
        "empleado": f"{user.name} {user.lastname}",
        "empleado_url": _worker_panel_url(user.id),
        "target_user_id": user.id,
        "fecha": fecha_label,
        "fecha_inicio": fecha_inicio.strftime("%d/%m/%Y"),
        "fecha_fin": fecha_fin.strftime("%d/%m/%Y"),
        "fecha_inicio_iso": fecha_inicio.strftime("%Y-%m-%d"),
        "fecha_fin_iso": fecha_fin.strftime("%Y-%m-%d"),
        "estado_actual": days[0]["estado_actual"] if num_days == 1 else None,
        "days": days,
    }
