"""Despacho de notificaciones: matriz + inmediato / debounce / digest.

Toda notificación de negocio debe pasar por ``dispatch_notification``.
Los envíos SMTP siguen en ``email_service.send_email``.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from flask import current_app, g, has_request_context

from app import db
from app.models import (
    ROLE_ADMIN,
    ROLE_ADMIN_SUBCONTRATA,
    ROLE_JEFE,
    ROLE_LABORAL,
    ROLE_RRHH,
    EmailNotifQueue,
    Obra,
    User,
)
from app.services.config_service import get_tenant_config, set_tenant_config
from app.services.notification_catalog import (
    CONFIG_DEBOUNCE_MINUTES,
    CONFIG_DIGEST_HOUR,
    CONFIG_HORA_CORTE_FOLDED,
    CONFIG_INCLUDE_ALL,
    CONFIG_INCLUDE_NONE,
    CONFIG_MIGRATED,
    CONTEXTUAL_RECIPIENTS,
    DEFAULT_DEBOUNCE_MINUTES,
    DEFAULT_DIGEST_HOUR,
    DELIVERY_MODES,
    MODE_DEBOUNCE,
    MODE_DIGEST,
    MODE_IMMEDIATE,
    MODE_OFF,
    NOTIFICATION_EVENTS,
    RECIPIENT_ADMIN,
    RECIPIENT_ADMIN_SUBCONTRATA,
    RECIPIENT_JEFE,
    RECIPIENT_LABORAL,
    RECIPIENT_REQUESTER,
    RECIPIENT_RRHH,
    RECIPIENT_TARGET,
    RECIPIENT_TRABAJADOR,
    event_help,
    get_event,
    include_config_key,
    include_role_keys,
    mode_label,
    normalize_event_key,
)

_TABLE_READY = '_email_notif_queue_ready'


def _config_mode_key(event: str) -> str:
    return f'notif.{event}.mode'[:50]


def _config_to_key(event: str) -> str:
    return f'notif.{event}.to'[:50]


def ensure_notif_queue_table():
    """Crea email_notif_queue en el schema actual del tenant si falta.

    Importante: usar la conexión de la sesión (con search_path del tenant).
    create() vía db.engine abre otra conexión en public y la cola nunca
    aparece donde se consulta → UndefinedTable en celery.
    """
    if has_request_context() and getattr(g, _TABLE_READY, False):
        return True
    try:
        from sqlalchemy import text

        # Consulta simple: inspect() sobre una sesión a medias (Celery / multi-tenant)
        # puede dejar el cursor en PGRES_TUPLES_OK y romper el siguiente SELECT.
        exists = db.session.execute(text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = current_schema() "
            "AND table_name = 'email_notif_queue' "
            "LIMIT 1"
        )).scalar()
        if not exists:
            bind = db.session.connection()
            EmailNotifQueue.__table__.create(bind, checkfirst=True)
        if has_request_context():
            setattr(g, _TABLE_READY, True)
        return True
    except Exception as exc:
        current_app.logger.warning('email_notif_queue no disponible: %s', exc)
        try:
            db.session.rollback()
        except Exception:
            pass
        return False


def ensure_notification_matrix_migrated():
    """Migra email_* legacy → notif.{event}.mode/to y materializa defaults."""
    if get_tenant_config(CONFIG_MIGRATED, default=None):
        ensure_hora_corte_folded_into_matrix()
        return
    for key, _label, _group, default_mode, default_to, _modes, legacy in NOTIFICATION_EVENTS:
        mode_k = _config_mode_key(key)
        to_k = _config_to_key(key)
        if get_tenant_config(mode_k, default=None) is not None:
            continue
        mode = default_mode
        recipients = list(default_to)
        if legacy:
            raw = get_tenant_config(legacy, default=None)
            if raw is None:
                # Legacy vacío = nadie → off
                conf_row = None
                try:
                    from app.models import ConfiguracionGlobal
                    conf_row = ConfiguracionGlobal.query.filter_by(clave=legacy).first()
                except Exception:
                    conf_row = None
                if conf_row is not None and not (conf_row.valor or '').strip():
                    mode = MODE_OFF
                    recipients = []
                elif conf_row is not None:
                    recipients = [x.strip() for x in (conf_row.valor or '').split(',') if x.strip()]
                    mode = MODE_IMMEDIATE if recipients else MODE_OFF
            else:
                recipients = [x.strip() for x in str(raw).split(',') if x.strip()]
                mode = MODE_IMMEDIATE if recipients else MODE_OFF
        set_tenant_config(mode_k, mode)
        set_tenant_config(to_k, ','.join(recipients) if recipients else CONFIG_INCLUDE_NONE)
    if get_tenant_config(CONFIG_DEBOUNCE_MINUTES, default=None) is None:
        set_tenant_config(CONFIG_DEBOUNCE_MINUTES, str(DEFAULT_DEBOUNCE_MINUTES))
    if get_tenant_config(CONFIG_DIGEST_HOUR, default=None) is None:
        set_tenant_config(CONFIG_DIGEST_HOUR, DEFAULT_DIGEST_HOUR)
    set_tenant_config(CONFIG_MIGRATED, '1')
    ensure_hora_corte_folded_into_matrix()


def ensure_hora_corte_folded_into_matrix():
    """Pasa el aviso diario / destinatarios de Horario a la matriz de correos."""
    if get_tenant_config(CONFIG_HORA_CORTE_FOLDED, default=None):
        return
    from app.services.tenant_modules import (
        CONFIG_HORA_CORTE_ACTIVA,
        CONFIG_HORA_CORTE_DESTINATARIOS,
        is_soltec_tenant,
    )

    raw_flag = get_tenant_config(CONFIG_HORA_CORTE_ACTIVA, default=None)
    if raw_flag is None:
        mode = MODE_IMMEDIATE if is_soltec_tenant() else MODE_OFF
    else:
        mode = (
            MODE_IMMEDIATE
            if str(raw_flag).strip().lower() in ('true', '1', 'yes', 'on')
            else MODE_OFF
        )

    dest_raw = get_tenant_config(CONFIG_HORA_CORTE_DESTINATARIOS, default='') or ''
    dest_ids = []
    for part in str(dest_raw).split(','):
        part = part.strip()
        if part.isdigit():
            dest_ids.append(int(part))

    recipients = [RECIPIENT_ADMIN, RECIPIENT_LABORAL]
    if dest_ids:
        users = User.query.filter(
            User.id.in_(dest_ids),
            User.is_deleted.is_(False),
        ).all()
        role_map = {
            ROLE_ADMIN: RECIPIENT_ADMIN,
            ROLE_LABORAL: RECIPIENT_LABORAL,
            ROLE_RRHH: RECIPIENT_RRHH,
            ROLE_JEFE: RECIPIENT_JEFE,
        }
        by_role = {rk: [] for rk in include_role_keys()}
        found_roles = []
        for u in users:
            rk = role_map.get(getattr(u, 'role', None))
            if not rk:
                # Roles custom: la propia clave de User.role
                ur = (getattr(u, 'role', None) or '').strip()
                if ur and ur in by_role:
                    rk = ur
                else:
                    continue
            by_role[rk].append(u.id)
            if rk not in found_roles:
                found_roles.append(rk)
        if found_roles:
            recipients = found_roles
        for rk, ids in by_role.items():
            if ids:
                set_role_include_ids(rk, ids)

    # Solo escribir mode/to si aún no hay config explícita del evento
    if get_tenant_config(_config_mode_key('hora_corte_reporte'), default=None) is None:
        set_tenant_config(_config_mode_key('hora_corte_reporte'), mode)
        set_tenant_config(
            _config_to_key('hora_corte_reporte'),
            ','.join(recipients) if recipients else CONFIG_INCLUDE_NONE,
        )
    else:
        # Ya había matriz: alinear modo con flag legado si el flag existía
        if raw_flag is not None:
            set_tenant_config(_config_mode_key('hora_corte_reporte'), mode)

    set_tenant_config(CONFIG_HORA_CORTE_FOLDED, '1')


def get_role_include_ids(role_key: str):
    """None = todos los del rol; set() = nadie; set(ids) = solo esos."""
    raw = get_tenant_config(include_config_key(role_key), default=None)
    if raw is None:
        return None
    text = str(raw).strip()
    if text in (CONFIG_INCLUDE_ALL, '*'):
        return None
    if text in (CONFIG_INCLUDE_NONE, '-', '0'):
        return set()
    if not text:
        # Legado: '' quedó como «nadie» pero get_tenant_config lo tragaba;
        # si la fila existe vacía no llegamos aquí. Tratar como nadie.
        return set()
    ids = set()
    for part in text.split(','):
        part = part.strip()
        if part.isdigit():
            ids.add(int(part))
    return ids


def set_role_include_ids(role_key: str, user_ids):
    if role_key not in include_role_keys():
        return
    if user_ids is None:
        set_tenant_config(include_config_key(role_key), CONFIG_INCLUDE_ALL)
        return
    clean = []
    for x in user_ids:
        try:
            i = int(x)
        except (TypeError, ValueError):
            continue
        if i not in clean:
            clean.append(i)
    # Comparar con todos los activos del rol: si son los mismos → *
    role_db = {
        RECIPIENT_ADMIN: ROLE_ADMIN,
        RECIPIENT_LABORAL: ROLE_LABORAL,
        RECIPIENT_RRHH: ROLE_RRHH,
        RECIPIENT_JEFE: ROLE_JEFE,
    }.get(role_key, role_key)
    if role_db:
        all_ids = {
            u.id for u in User.query.filter_by(
                role=role_db, active=True, is_deleted=False,
            ).all()
            if (u.email or '').strip()
        }
        if not clean:
            set_tenant_config(include_config_key(role_key), CONFIG_INCLUDE_NONE)
            return
        if all_ids and set(clean) == all_ids:
            set_tenant_config(include_config_key(role_key), CONFIG_INCLUDE_ALL)
            return
    if not clean:
        set_tenant_config(include_config_key(role_key), CONFIG_INCLUDE_NONE)
        return
    set_tenant_config(include_config_key(role_key), ','.join(str(i) for i in clean))


def user_allowed_for_role(user, role_key: str) -> bool:
    allowed = get_role_include_ids(role_key)
    if allowed is None:
        return True
    return bool(user and user.id in allowed)


def _filter_by_include(users, role_key: str) -> list:
    allowed = get_role_include_ids(role_key)
    if allowed is None:
        return list(users)
    return [u for u in users if u.id in allowed]


def office_users_by_role() -> dict:
    """Usuarios por rol (builtin + custom) para el selector de la matriz."""
    from app.services.role_registry_service import role_display_label

    out = []
    for key in include_role_keys():
        label = role_display_label(key) or key
        # Etiquetas cortas históricas en UI de correos
        if key == RECIPIENT_ADMIN:
            label = 'Admin'
        elif key == RECIPIENT_JEFE:
            label = 'Jefe obra'
        users = (
            User.query.filter_by(role=key, active=True, is_deleted=False)
            .order_by(User.name, User.lastname)
            .all()
        )
        allowed = get_role_include_ids(key)
        out.append({
            'key': key,
            'label': label,
            'users': [
                {
                    'id': u.id,
                    'name': f'{u.name or ""} {u.lastname or ""}'.strip(),
                    'email': (u.email or '').strip(),
                    'checked': True if allowed is None else (u.id in allowed),
                }
                for u in users
            ],
        })
    return out


def get_debounce_minutes() -> int:
    try:
        ensure_notification_matrix_migrated()
    except Exception:
        pass
    raw = get_tenant_config(CONFIG_DEBOUNCE_MINUTES, default=str(DEFAULT_DEBOUNCE_MINUTES))
    try:
        n = int(raw)
    except (TypeError, ValueError):
        n = DEFAULT_DEBOUNCE_MINUTES
    return max(1, min(n, 24 * 60))


def get_digest_hour() -> str:
    try:
        ensure_notification_matrix_migrated()
    except Exception:
        pass
    raw = (get_tenant_config(CONFIG_DIGEST_HOUR, default=DEFAULT_DIGEST_HOUR) or DEFAULT_DIGEST_HOUR).strip()
    try:
        hh, mm = raw.split(':')
        h, m = int(hh), int(mm)
        if 0 <= h <= 23 and 0 <= m <= 59:
            return f'{h:02d}:{m:02d}'
    except Exception:
        pass
    return DEFAULT_DIGEST_HOUR


def _parse_recipients_raw(raw_to, default_to) -> list[str]:
    """Interpreta notif.*.to. '' lo traga get_tenant_config → None (= defaults).

    Sentinel CONFIG_INCLUDE_NONE = nadie a propósito (tics desmarcados).
    """
    if raw_to is None:
        return list(default_to)
    text = str(raw_to).strip()
    if text in (CONFIG_INCLUDE_NONE, '-', '0'):
        return []
    return [x.strip() for x in text.split(',') if x.strip()]


def get_event_settings(event_key: str) -> dict:
    try:
        ensure_notification_matrix_migrated()
    except Exception:
        pass
    key = normalize_event_key(event_key)
    meta = get_event(key)
    if not meta:
        return {'mode': MODE_OFF, 'recipients': [], 'allowed_modes': DELIVERY_MODES}
    _k, _l, _g, default_mode, default_to, allowed, _leg = meta
    mode = (get_tenant_config(_config_mode_key(key), default=default_mode) or default_mode).strip().lower()
    if mode not in allowed:
        mode = default_mode if default_mode in allowed else MODE_OFF
    raw_to = get_tenant_config(_config_to_key(key), default=None)
    recipients = _parse_recipients_raw(raw_to, default_to)
    return {'mode': mode, 'recipients': recipients, 'allowed_modes': allowed}


def set_event_settings(event_key: str, mode: str, recipients: list[str]):
    key = normalize_event_key(event_key)
    meta = get_event(key)
    if not meta:
        return
    allowed = meta[5]
    mode = (mode or MODE_OFF).strip().lower()
    if mode not in allowed:
        mode = MODE_OFF
    clean = []
    for r in recipients or []:
        r = (r or '').strip()
        if r and r not in clean and r not in (CONFIG_INCLUDE_NONE, '-', '0'):
            clean.append(r)
    set_tenant_config(_config_mode_key(key), mode)
    # Nunca '' : get_tenant_config lo trata como «sin config» y restaura defaults.
    set_tenant_config(
        _config_to_key(key),
        ','.join(clean) if clean else CONFIG_INCLUDE_NONE,
    )


def matrix_for_ui() -> dict:
    """Datos para la plantilla de configuración."""
    try:
        ensure_notification_matrix_migrated()
    except Exception:
        pass
    from app.services.role_registry_service import role_display_label

    groups = []
    by_group = {}
    for key, label, group, *_rest in NOTIFICATION_EVENTS:
        st = get_event_settings(key)
        ev = {
            'key': key,
            'label': label,
            'help': event_help(key),
            'group': group,
            'mode': st['mode'],
            'recipients': st['recipients'],
            'allowed_modes': st['allowed_modes'],
        }
        if group not in by_group:
            by_group[group] = []
            groups.append({'name': group, 'events': by_group[group]})
        by_group[group].append(ev)
    recipient_opts = []
    for rk in include_role_keys():
        lbl = role_display_label(rk) or rk
        if rk == RECIPIENT_ADMIN:
            lbl = 'Admin'
        elif rk == RECIPIENT_JEFE:
            lbl = 'Jefe obra'
        recipient_opts.append((rk, lbl))
    recipient_opts.extend([
        (RECIPIENT_ADMIN_SUBCONTRATA, 'Admin subcontrata'),
        (RECIPIENT_TRABAJADOR, 'Trabajador'),
        (RECIPIENT_REQUESTER, 'Solicitante'),
        (RECIPIENT_TARGET, 'Destinatario'),
    ])

    return {
        'groups': groups,
        'events': [e for g in groups for e in g['events']],
        'debounce_minutes': get_debounce_minutes(),
        'digest_hour': get_digest_hour(),
        'mode_labels': {m: mode_label(m) for m in DELIVERY_MODES},
        'role_users': office_users_by_role(),
        'recipient_opts': recipient_opts,
    }


def save_matrix_from_form(form) -> None:
    ensure_notification_matrix_migrated()
    raw_min = form.get('notif_debounce_minutes')
    try:
        minutes = int(raw_min)
    except (TypeError, ValueError):
        minutes = DEFAULT_DEBOUNCE_MINUTES
    set_tenant_config(CONFIG_DEBOUNCE_MINUTES, str(max(1, min(minutes, 24 * 60))))
    hour = (form.get('notif_digest_hour') or DEFAULT_DIGEST_HOUR).strip()
    set_tenant_config(CONFIG_DIGEST_HOUR, hour if len(hour) >= 4 else DEFAULT_DIGEST_HOUR)

    for key, *_rest in NOTIFICATION_EVENTS:
        mode = form.get(f'notif__{key}__mode') or MODE_OFF
        recipients = form.getlist(f'notif__{key}__to')
        set_event_settings(key, mode, recipients)

    # Personas por rol (si el formulario trae el panel)
    if form.get('notif_users_panel') == '1':
        for rk in include_role_keys():
            # Solo actualizar roles presentes en el POST (marca oculta).
            if form.get(f'notif_user_role__{rk}') != '1':
                continue
            ids = form.getlist(f'notif_user__{rk}')
            set_role_include_ids(rk, ids)

    # Mantener flag legado alineado (Celery / tests antiguos)
    from app.services.tenant_modules import CONFIG_HORA_CORTE_ACTIVA
    st = get_event_settings('hora_corte_reporte')
    set_tenant_config(
        CONFIG_HORA_CORTE_ACTIVA,
        'True' if st['mode'] != MODE_OFF else 'False',
    )


def resolve_recipients(
    event_key: str,
    *,
    obra_id=None,
    worker_id=None,
    target_user_id=None,
    requester_user_id=None,
    company_id=None,
    include_office: bool = True,
    include_subcontrata: bool = True,
) -> list[User]:
    st = get_event_settings(event_key)
    if st['mode'] == MODE_OFF:
        return []
    roles = set(st['recipients'])
    users = []

    # Jefe: destinatario contextual de la obra (no todos los del rol).
    if include_office and RECIPIENT_JEFE in roles and obra_id:
        obra = Obra.query.get(obra_id)
        if obra and obra.jefe_obra_id:
            jefe = User.query.get(obra.jefe_obra_id)
            if jefe and jefe.active and not jefe.is_deleted and user_allowed_for_role(jefe, RECIPIENT_JEFE):
                users.append(jefe)

    # Resto de roles de oficina / custom: todas las personas del rol (con include).
    if include_office:
        for rk in roles:
            if rk in CONTEXTUAL_RECIPIENTS or rk == RECIPIENT_JEFE:
                continue
            users.extend(_filter_by_include(
                User.query.filter_by(role=rk, active=True, is_deleted=False).all(),
                rk,
            ))

    if include_subcontrata and RECIPIENT_ADMIN_SUBCONTRATA in roles and company_id:
        users.extend(
            User.query.filter_by(
                role=ROLE_ADMIN_SUBCONTRATA,
                company_id=company_id,
                active=True,
                is_deleted=False,
            ).all()
        )

    if RECIPIENT_TRABAJADOR in roles and worker_id:
        w = User.query.get(worker_id)
        if w and w.active and not getattr(w, 'is_deleted', False):
            users.append(w)
    if RECIPIENT_TARGET in roles and target_user_id:
        t = User.query.get(target_user_id)
        if t and not getattr(t, 'is_deleted', False):
            users.append(t)
    if RECIPIENT_REQUESTER in roles and requester_user_id:
        r = User.query.get(requester_user_id)
        if r and r.active and not getattr(r, 'is_deleted', False):
            users.append(r)

    seen = set()
    out = []
    for u in users:
        email = (getattr(u, 'email', None) or '').strip()
        if not email or email in seen:
            continue
        seen.add(email)
        out.append(u)
    return out


def _user_locale(user):
    from app.services.i18n_service import normalize_locale, DEFAULT_LOCALE
    loc = normalize_locale(getattr(user, 'locale', None)) if user else None
    return loc or DEFAULT_LOCALE


def _send_now(users, subject: str, body: str, html: str | None = None):
    from app.services.email_service import send_email
    from collections import defaultdict
    groups = defaultdict(list)
    for u in users:
        email = (u.email or '').strip()
        if email:
            groups[_user_locale(u)].append(email)
    # subject/body already localized by caller for single-locale, or plain ES
    for _loc, emails in groups.items():
        send_email(subject, emails, body, html_body=html)


def _enqueue(user, event_key: str, mode: str, batch_key: str, line: dict, flush_after):
    if not ensure_notif_queue_table():
        # Sin cola: degradar a inmediato
        _send_now([user], line.get('subject') or event_key, line.get('body') or line.get('summary') or '')
        return
    row = (
        EmailNotifQueue.query.filter_by(
            event_key=event_key,
            mode=mode,
            recipient_user_id=user.id,
            batch_key=batch_key,
        )
        .order_by(EmailNotifQueue.id.desc())
        .first()
    )
    if row and mode == MODE_DEBOUNCE:
        payload = dict(row.payload or {})
        lines = list(payload.get('lines') or [])
        lines.append(line)
        payload['lines'] = lines
        row.payload = payload
        row.flush_after = flush_after
        db.session.add(row)
        return
    if row and mode == MODE_DIGEST:
        payload = dict(row.payload or {})
        lines = list(payload.get('lines') or [])
        lines.append(line)
        payload['lines'] = lines
        row.payload = payload
        db.session.add(row)
        return
    payload = {'lines': [line]}
    db.session.add(EmailNotifQueue(
        event_key=event_key,
        mode=mode,
        recipient_user_id=user.id,
        batch_key=batch_key,
        payload=payload,
        flush_after=flush_after,
        locale=_user_locale(user),
    ))


def event_allows_send(event_key: str) -> bool:
    """True si el evento no está en off (para flujos sin User / sin tenant pleno)."""
    try:
        return get_event_settings(event_key)['mode'] != MODE_OFF
    except Exception:
        meta = get_event(normalize_event_key(event_key))
        return bool(meta and meta[3] != MODE_OFF)


def dispatch_notification(
    event_key: str,
    *,
    subject: str,
    body: str,
    html: str | None = None,
    summary: str | None = None,
    obra_id=None,
    worker_id=None,
    target_user_id=None,
    requester_user_id=None,
    company_id=None,
    include_office: bool = True,
    include_subcontrata: bool = True,
    batch_key: str | None = None,
    users: list[User] | None = None,
):
    """Entrada con subject/body ya compuestos (mismo locale para todos o texto neutro)."""
    return dispatch_localized(
        event_key,
        lambda _loc: subject,
        lambda _loc: body,
        (lambda _loc: html) if html is not None else None,
        summary_fn=(lambda _loc: summary) if summary is not None else None,
        obra_id=obra_id,
        worker_id=worker_id,
        target_user_id=target_user_id,
        requester_user_id=requester_user_id,
        company_id=company_id,
        include_office=include_office,
        include_subcontrata=include_subcontrata,
        batch_key=batch_key,
        users=users,
    )


def dispatch_localized(
    event_key: str,
    subject_fn,
    text_fn,
    html_fn=None,
    summary_fn=None,
    *,
    obra_id=None,
    worker_id=None,
    target_user_id=None,
    requester_user_id=None,
    company_id=None,
    include_office: bool = True,
    include_subcontrata: bool = True,
    batch_key: str | None = None,
    users: list[User] | None = None,
):
    """Como dispatch_notification pero con subject/body por locale (fns(loc) → str)."""
    from collections import defaultdict

    key = normalize_event_key(event_key)
    if not get_event(key):
        current_app.logger.warning('Notificación desconocida: %s', event_key)
        return False
    st = get_event_settings(key)
    if st['mode'] == MODE_OFF:
        return False
    if users is None:
        users = resolve_recipients(
            key,
            obra_id=obra_id,
            worker_id=worker_id,
            target_user_id=target_user_id,
            requester_user_id=requester_user_id,
            company_id=company_id,
            include_office=include_office,
            include_subcontrata=include_subcontrata,
        )
    else:
        # Deduplicar por email
        seen = set()
        clean = []
        for u in users:
            email = (getattr(u, 'email', None) or '').strip()
            if not email or email in seen:
                continue
            seen.add(email)
            clean.append(u)
        users = clean
    if not users:
        return False

    if st['mode'] == MODE_IMMEDIATE:
        from app.services.email_service import send_email
        groups = defaultdict(list)
        for u in users:
            email = (u.email or '').strip()
            if email:
                groups[_user_locale(u)].append(email)
        for loc, emails in groups.items():
            send_email(
                subject_fn(loc),
                emails,
                text_fn(loc),
                html_body=html_fn(loc) if html_fn else None,
            )
        return True

    # debounce / digest: una entrada por usuario (texto en locale del usuario)
    from app.utils.timezone_utils import utc_now, today_local
    now = utc_now()
    if st['mode'] == MODE_DEBOUNCE:
        flush_after = now + timedelta(minutes=get_debounce_minutes())
        base_batch = batch_key or f'{key}:debounce'
    else:
        flush_after = None
        base_batch = batch_key or f'{key}:digest:{today_local().isoformat()}'

    for u in users:
        loc = _user_locale(u)
        line = {
            'summary': (summary_fn(loc) if summary_fn else subject_fn(loc)),
            'subject': subject_fn(loc),
            'body': text_fn(loc),
            'html': html_fn(loc) if html_fn else None,
        }
        bkey = f'{base_batch}:u{u.id}'
        _enqueue(u, key, st['mode'], bkey, line, flush_after)
    try:
        db.session.flush()
    except Exception:
        db.session.rollback()
        raise
    return True


def _compose_batch_email(event_key: str, lines: list, loc: str) -> tuple[str, str]:
    from app.services.i18n_service import translate
    meta = get_event(event_key)
    label = meta[1] if meta else event_key
    subject = translate('Resumen: {event} ({n})', loc, event=translate(label, loc), n=len(lines))
    parts = [
        translate(
            'Estas son las notificaciones agrupadas de «{event}»:',
            loc,
            event=translate(label, loc),
        ),
        '',
    ]
    for i, line in enumerate(lines, 1):
        parts.append(f'{i}. {line.get("summary") or line.get("subject") or "—"}')
        body = (line.get('body') or '').strip()
        if body and body != line.get('summary'):
            # Indent brief detail (first 400 chars)
            snippet = body.replace('\n', ' ').strip()
            if len(snippet) > 400:
                snippet = snippet[:397] + '…'
            parts.append(f'   {snippet}')
        parts.append('')
    parts.append(translate('— SignaPlan', loc))
    return subject, '\n'.join(parts)


def flush_debounce_due() -> int:
    """Envía lotes debounce cuya ventana ha cerrado. Devuelve nº de mails."""
    if not ensure_notif_queue_table():
        return 0
    from app.utils.timezone_utils import utc_now
    from app.services.email_service import send_email

    now = utc_now()
    rows = (
        EmailNotifQueue.query.filter(
            EmailNotifQueue.mode == MODE_DEBOUNCE,
            EmailNotifQueue.flush_after.isnot(None),
            EmailNotifQueue.flush_after <= now,
        )
        .order_by(EmailNotifQueue.id.asc())
        .all()
    )
    sent = 0
    for row in rows:
        user = User.query.get(row.recipient_user_id)
        email = (getattr(user, 'email', None) or '').strip() if user else ''
        lines = list((row.payload or {}).get('lines') or [])
        if email and lines:
            loc = row.locale or _user_locale(user)
            subject, body = _compose_batch_email(row.event_key, lines, loc)
            if send_email(subject, [email], body):
                sent += 1
        db.session.delete(row)
    db.session.commit()
    return sent


def flush_digest_for_hour(hour_hhmm: str | None = None) -> int:
    """Si la hora local del tenant coincide con digest_hour, vacía la cola digest."""
    if not ensure_notif_queue_table():
        return 0
    from app.utils.timezone_utils import now_local
    from app.services.email_service import send_email

    target = hour_hhmm or get_digest_hour()
    ahora = now_local()
    current = f'{ahora.hour:02d}:{ahora.minute:02d}'
    # Ventana de 5 min (beat cada ~5 min)
    th, tm = map(int, target.split(':'))
    if not (ahora.hour == th and tm <= ahora.minute < tm + 5):
        return 0

    rows = EmailNotifQueue.query.filter_by(mode=MODE_DIGEST).order_by(EmailNotifQueue.id.asc()).all()
    sent = 0
    for row in rows:
        user = User.query.get(row.recipient_user_id)
        email = (getattr(user, 'email', None) or '').strip() if user else ''
        lines = list((row.payload or {}).get('lines') or [])
        if email and lines:
            loc = row.locale or _user_locale(user)
            subject, body = _compose_batch_email(row.event_key, lines, loc)
            if send_email(subject, [email], body):
                sent += 1
        db.session.delete(row)
    db.session.commit()
    return sent
