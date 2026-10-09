"""Preferencias personales de avisos de la interfaz (badges), no correos."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm.attributes import flag_modified

from app import db

# key → etiqueta (i18n en la vista con _())
NOTIF_KEYS: tuple[tuple[str, str], ...] = (
    ('documentacion', 'Documentación'),
    ('certificacion', 'Certificación de horario'),
    ('contratacion', 'Contratación'),
    ('solicitudes', 'Solicitudes'),
    ('logs', 'Logs'),
    ('logs_laboral', 'Logs laborales'),
)

ALL_KEYS = frozenset(k for k, _ in NOTIF_KEYS)

# Contadores del context processor / sidebar que anula cada key
_CTX_FIELDS: dict[str, tuple[str, ...]] = {
    'documentacion': ('doc_errores', 'doc_avisos'),
    'certificacion': ('cert_entrantes',),
    'contratacion': ('contratacion_pendientes',),
    'solicitudes': (
        'pending_notifications',
        'pending_solicitudes_personal',
        'pending_solicitudes_vehiculos',
    ),
    'logs': ('unread_logs_count',),
    'logs_laboral': ('unread_laboral_count',),
}


def get_prefs(user) -> dict[str, bool]:
    """Preferencias efectivas: ausencia de clave = activado."""
    raw = getattr(user, 'ui_notif_prefs', None) or {}
    if not isinstance(raw, dict):
        raw = {}
    out: dict[str, bool] = {}
    for key, _ in NOTIF_KEYS:
        val = raw.get(key, True)
        out[key] = bool(val)
    return out


def is_enabled(user, key: str) -> bool:
    if key not in ALL_KEYS:
        return True
    return bool(get_prefs(user).get(key, True))


def catalog_for_ui(user) -> list[dict[str, Any]]:
    prefs = get_prefs(user)
    return [
        {'key': key, 'label': label, 'enabled': prefs[key]}
        for key, label in NOTIF_KEYS
    ]


def save_prefs(user, payload: dict | None = None, *, form=None) -> dict[str, bool]:
    """Guarda preferencias. Form: checkboxes ui_notif__<key>."""
    current = get_prefs(user)
    if form is not None:
        cleaned: dict[str, bool] = {}
        for key in ALL_KEYS:
            cleaned[key] = bool(form.get(f'ui_notif__{key}'))
    elif isinstance(payload, dict):
        cleaned = dict(current)
        for key in ALL_KEYS:
            if key in payload:
                cleaned[key] = bool(payload[key])
    else:
        cleaned = current

    user.ui_notif_prefs = cleaned
    flag_modified(user, 'ui_notif_prefs')
    db.session.add(user)
    db.session.commit()
    return cleaned


def apply_to_badge_ctx(ctx: dict, user) -> dict:
    """Pone a 0 los contadores cuya preferencia está desactivada. Mutates ctx."""
    if not ctx or user is None:
        return ctx
    prefs = get_prefs(user)
    for key, fields in _CTX_FIELDS.items():
        if prefs.get(key, True):
            continue
        for field in fields:
            if field in ctx:
                ctx[field] = 0
    return ctx
