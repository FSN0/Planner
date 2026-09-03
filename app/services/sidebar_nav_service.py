# app/services/sidebar_nav_service.py
#
# Menú lateral personalizable: secciones (título libre), orden de entradas,
# ocultar/mostrar. Los ítems disponibles siguen gobernados por permisos.

from __future__ import annotations

import copy
import uuid
from typing import Any, Optional

from flask import has_request_context, request, url_for
from flask_login import current_user

from app import db
from app.models import ROLE_JEFE, ROLE_OPERARIO
from app.services.i18n_service import _
from app.services.permission_service import is_laboral, user_can


# Claves estables de entradas del catálogo
ITEM_INICIO = 'inicio'
ITEM_TABLERO = 'tablero'
ITEM_DIRECTORIO = 'directorio'
ITEM_PLANIFICADOR = 'planificador'
ITEM_REUNIONES = 'reuniones'
ITEM_TRABAJADORES = 'trabajadores'
ITEM_SUBCONTRATAS = 'subcontratas'
ITEM_SOLICITUDES = 'solicitudes'
ITEM_AUSENCIAS = 'ausencias'
ITEM_FLOTA = 'flota'
ITEM_COCHES_LIBRES = 'coches_libres'
ITEM_AUDITORIA_VEH = 'auditoria_vehiculos'
ITEM_AUDITORIA_FICH = 'auditoria_fichajes'
ITEM_MAPA_FICH = 'mapa_fichajes'
ITEM_REGISTRO_JORNADA = 'registro_jornada'
ITEM_INTEGRACIONES = 'integraciones'
ITEM_SOLTEC_PORTAL = 'soltec_portal'
ITEM_ODOO_ALTA = 'odoo_alta'
ITEM_PRIMEROS_PASOS = 'primeros_pasos'
ITEM_CONFIGURACION = 'configuracion'
ITEM_PERMISOS = 'permisos'
ITEM_LOGS = 'logs'
ITEM_MI_FICHAJE = 'mi_fichaje'
ITEM_MI_CALENDARIO = 'mi_calendario'
ITEM_MI_HORAS = 'mi_horas'
ITEM_MI_AUSENCIAS = 'mi_ausencias_portal'

ALL_ITEM_KEYS = (
    ITEM_INICIO,
    ITEM_TABLERO,
    ITEM_DIRECTORIO,
    ITEM_PLANIFICADOR,
    ITEM_REUNIONES,
    ITEM_TRABAJADORES,
    ITEM_SUBCONTRATAS,
    ITEM_SOLICITUDES,
    ITEM_AUSENCIAS,
    ITEM_FLOTA,
    ITEM_COCHES_LIBRES,
    ITEM_AUDITORIA_VEH,
    ITEM_AUDITORIA_FICH,
    ITEM_MAPA_FICH,
    ITEM_REGISTRO_JORNADA,
    ITEM_INTEGRACIONES,
    ITEM_ODOO_ALTA,
    ITEM_SOLTEC_PORTAL,
    ITEM_PRIMEROS_PASOS,
    ITEM_CONFIGURACION,
    ITEM_PERMISOS,
    ITEM_LOGS,
    ITEM_MI_FICHAJE,
    ITEM_MI_CALENDARIO,
    ITEM_MI_HORAS,
    ITEM_MI_AUSENCIAS,
)


def _operario_sections_blueprint() -> list[dict]:
    return [
        {
            'id': 'sec_jornada',
            'title': '',
            'items': [
                ITEM_MI_FICHAJE,
                ITEM_MI_CALENDARIO,
                ITEM_MI_HORAS,
                ITEM_MI_AUSENCIAS,
            ],
        },
    ]


def _is_operario(user) -> bool:
    return getattr(user, 'role', None) == ROLE_OPERARIO


def _default_sections_blueprint() -> list[dict]:
    """Estructura por defecto (títulos traducidos al construir)."""
    return [
        {'id': 'sec_home', 'title': '', 'items': [ITEM_INICIO, ITEM_MI_FICHAJE]},
        {
            'id': 'sec_plan',
            'title': str(_('Planificación')),
            'items': [ITEM_TABLERO, ITEM_PLANIFICADOR, ITEM_COCHES_LIBRES],
        },
        {
            'id': 'sec_gestion',
            # Maestros / fichas: obras, gente, empresas y vehículos
            'title': str(_('Gestión')),
            'items': [ITEM_DIRECTORIO, ITEM_TRABAJADORES, ITEM_SUBCONTRATAS, ITEM_FLOTA, ITEM_AUSENCIAS],
        },
        {
            'id': 'sec_solicitudes',
            'title': str(_('Solicitudes')),
            'items': [ITEM_SOLICITUDES],
        },
        {
            'id': 'sec_audit',
            'title': str(_('Auditorías')),
            'items': [ITEM_AUDITORIA_FICH, ITEM_MAPA_FICH, ITEM_REGISTRO_JORNADA, ITEM_AUDITORIA_VEH],
        },
        {
            'id': 'sec_soltec',
            'title': str(_('Soltec')),
            'items': [ITEM_ODOO_ALTA, ITEM_SOLTEC_PORTAL],
        },
        {
            'id': 'sec_sys',
            'title': str(_('Sistema')),
            # Permisos va como submenú de Configuración (no ítem suelto).
            # Logs queda oculto por defecto (_default_hidden).
            'items': [
                ITEM_PRIMEROS_PASOS,
                ITEM_CONFIGURACION,
                ITEM_REUNIONES,
                ITEM_LOGS,
            ],
        },
    ]


def _default_hidden() -> list[str]:
    """Ítems del catálogo ocultos en el menú por defecto (siguen en personalizar)."""
    return [ITEM_LOGS]


def _is_stock_v1_layout(sections: list) -> bool:
    """True si las prefs parecen el menú stock anterior (antes del rediseño)."""
    ids = {str(s.get('id')) for s in sections if isinstance(s, dict)}
    if 'sec_gestion' in ids or 'sec_solicitudes' in ids or 'sec_audit' in ids:
        return False
    if 'sec_soltec' in ids:
        return False
    # Layout viejo tenía Personal + Vehículos + Jornada
    return 'sec_personal' in ids and 'sec_fleet' in ids and 'sec_jornada' in ids


def _ep() -> str:
    if not has_request_context():
        return ''
    return request.endpoint or ''


def _is_jefe(user) -> bool:
    return getattr(user, 'role', None) == 'jefe_obra'


def _is_adm(user) -> bool:
    return getattr(user, 'role', None) == 'admin'


def _home_href(user) -> str:
    from app.services.user_home_service import home_url_for_user
    dest = home_url_for_user(user)
    if dest:
        return dest
    return url_for('main.dashboard')


def _home_active() -> bool:
    return _ep() in (
        'main.dashboard', 'admin.panel', 'admin.panel_laboral',
        'jefe.panel', 'empleado.calendario',
        'admin.vehiculos', 'admin.vehicle_panel', 'admin.vehiculos_libres',
        'sync.auditoria_vehiculos',
    )


def catalog_definitions(ctx: dict) -> dict[str, dict]:
    """Definiciones estáticas (sin filtrar por permiso)."""
    u = ctx.get('user') or current_user
    return {
        ITEM_INICIO: {
            'id': ITEM_INICIO,
            'label': str(_('Inicio')),
            'icon': 'fa-home',
            'kind': 'link',
            'href': _home_href(u),
            'active': _home_active(),
            'data_tour': None,
        },
        ITEM_TABLERO: {
            'id': ITEM_TABLERO,
            'label': str(_('Tablero')),
            'icon': 'fa-th-large',
            'kind': 'link',
            'href': url_for('jefe.obras_detailed') if _is_jefe(u) else url_for('admin.obras_detailed'),
            'active': _ep() in ('admin.obras_detailed', 'jefe.obras_detailed'),
            'data_tour': 'nav-tablero',
        },
        ITEM_DIRECTORIO: {
            'id': ITEM_DIRECTORIO,
            'label': str(_('Obras')),
            'icon': 'fa-building',
            'kind': 'link',
            'href': url_for('admin.obras_list'),
            'active': _ep() == 'admin.obras_list',
            'data_tour': 'nav-directorio',
        },
        ITEM_PLANIFICADOR: {
            'id': ITEM_PLANIFICADOR,
            'label': str(_('Planificador')),
            'icon': 'fa-calendar-check',
            'kind': 'link',
            'href': url_for('admin.planificador_jo'),
            'active': 'planificador' in _ep(),
            'data_tour': 'nav-planificador',
        },
        ITEM_REUNIONES: {
            'id': ITEM_REUNIONES,
            'label': str(_('Reuniones')),
            'icon': 'fa-book-open',
            'kind': 'link',
            'href': url_for('notas.centro_mando'),
            'active': 'notas' in _ep(),
            'data_tour': None,
        },
        ITEM_TRABAJADORES: {
            'id': ITEM_TRABAJADORES,
            'label': str(_('Trabajadores')),
            'icon': 'fa-users',
            'kind': 'link',
            'href': url_for('admin.personal'),
            'active': 'personal' in _ep(),
            'data_tour': 'nav-trabajadores',
        },
        ITEM_SUBCONTRATAS: {
            'id': ITEM_SUBCONTRATAS,
            'label': str(_('Subcontratas')),
            'icon': 'fa-industry',
            'kind': 'link',
            'href': url_for('admin.companies'),
            'active': 'companies' in _ep() or _ep() == 'admin.company_panel',
            'data_tour': 'nav-empresas',
        },
        ITEM_SOLICITUDES: {
            'id': ITEM_SOLICITUDES,
            'label': str(_('Solicitudes')),
            'icon': 'fa-user-plus',
            'kind': 'link',
            'href': url_for('admin.solicitudes_list'),
            'active': 'solicitud' in _ep(),
            'data_tour': None,
            'badge': int(ctx.get('pending_notifications') or 0),
        },
        ITEM_AUSENCIAS: {
            'id': ITEM_AUSENCIAS,
            'label': str(_('Ausencias')),
            'icon': 'fa-umbrella-beach',
            'kind': 'link',
            'href': url_for('admin.ausencias_list'),
            'active': 'ausencias' in _ep(),
            'data_tour': None,
        },
        ITEM_FLOTA: {
            'id': ITEM_FLOTA,
            'label': str(_('Flota')),
            'icon': 'fa-car',
            'kind': 'link',
            'href': url_for('admin.vehiculos'),
            'active': _ep() in ('admin.vehiculos', 'admin.vehicle_panel'),
            'data_tour': None,
        },
        ITEM_COCHES_LIBRES: {
            'id': ITEM_COCHES_LIBRES,
            'label': str(_('Coches libres')),
            'icon': 'fa-car-side',
            'kind': 'link',
            'href': url_for('admin.vehiculos_libres'),
            'active': _ep() == 'admin.vehiculos_libres',
            'data_tour': 'nav-coches-libres',
        },
        ITEM_AUDITORIA_VEH: {
            'id': ITEM_AUDITORIA_VEH,
            'label': str(_('Auditoría vehículos')),
            'icon': 'fa-clipboard-check',
            'kind': 'link',
            'href': url_for('sync.auditoria_vehiculos'),
            'active': _ep() == 'sync.auditoria_vehiculos',
            'data_tour': None,
        },
        ITEM_AUDITORIA_FICH: {
            'id': ITEM_AUDITORIA_FICH,
            'label': str(_('Auditoría fichajes')),
            'icon': 'fa-user-clock',
            'kind': 'link',
            'href': url_for('sync.auditoria_fichajes'),
            'active': _ep() == 'sync.auditoria_fichajes',
            'data_tour': 'nav-auditoria-fichajes',
        },
        ITEM_MAPA_FICH: {
            'id': ITEM_MAPA_FICH,
            'label': str(_('Mapa fichajes')),
            'icon': 'fa-map-marked-alt',
            'kind': 'link',
            'href': url_for('admin.mapa_fichajes'),
            'active': _ep() == 'admin.mapa_fichajes',
            'data_tour': None,
        },
        ITEM_REGISTRO_JORNADA: {
            'id': ITEM_REGISTRO_JORNADA,
            'label': str(_('Registro jornada')),
            'icon': 'fa-file-signature',
            'kind': 'link',
            'href': url_for('admin.registro_jornada'),
            'active': 'registro_jornada' in _ep(),
            'data_tour': 'nav-registro-jornada',
        },
        ITEM_INTEGRACIONES: {
            'id': ITEM_INTEGRACIONES,
            'label': str(_('Integraciones')),
            'icon': 'fa-plug',
            'kind': 'link',
            'href': url_for('sync.panel'),
            'active': _ep() in ('sync.panel', 'sync.odoo_panel'),
            'data_tour': None,
        },
        ITEM_ODOO_ALTA: {
            'id': ITEM_ODOO_ALTA,
            'label': str(_('Alta Odoo')),
            'icon': 'fa-address-book',
            'kind': 'link',
            'href': url_for('admin.sso_odoo_contactos'),
            'active': False,
            'data_tour': None,
            'external': True,
        },
        ITEM_SOLTEC_PORTAL: {
            'id': ITEM_SOLTEC_PORTAL,
            'label': str(_('Portal Soltec')),
            'icon': 'fa-external-link-alt',
            'kind': 'link',
            'href': url_for('auth.sso_portal'),
            'active': False,
            'data_tour': None,
            'external': False,
        },
        ITEM_PRIMEROS_PASOS: {
            'id': ITEM_PRIMEROS_PASOS,
            'label': str(_('Academia')) if ctx.get('onboarding_completo') else str(_('Primeros pasos')),
            'icon': 'fa-graduation-cap' if ctx.get('onboarding_completo') else 'fa-rocket',
            'kind': 'link',
            'href': url_for('admin.primeros_pasos'),
            'active': _ep() == 'admin.primeros_pasos',
            'data_tour': None,
        },
        ITEM_CONFIGURACION: {
            'id': ITEM_CONFIGURACION,
            'label': str(_('Configuración')),
            'icon': 'fa-sliders-h',
            'kind': 'group',
            'href': url_for('admin.configuracion_global'),
            'active': _config_group_active(),
            'data_tour': None,
            'open': _config_group_active(),
            'children': _config_children(ctx),
        },
        ITEM_PERMISOS: {
            # Conservado por compatibilidad con prefs antiguas; en el layout
            # nuevo vive como hijo de Configuración.
            'id': ITEM_PERMISOS,
            'label': str(_('Permisos')),
            'icon': 'fa-user-shield',
            'kind': 'link',
            'href': url_for('admin.permisos_roles'),
            'active': _ep() == 'admin.permisos_roles',
            'data_tour': None,
        },
        ITEM_LOGS: {
            'id': ITEM_LOGS,
            'label': str(_('Logs')),
            'icon': 'fa-history',
            'kind': 'link',
            'href': url_for('admin.system_logs'),
            'active': 'system_logs' in _ep(),
            'data_tour': None,
            'badge_logs': int(ctx.get('unread_logs_count') or 0),
            'badge_laboral': int(ctx.get('unread_laboral_count') or 0),
            'show_laboral_badge': bool(ctx.get('tenant_has_avisos_laborales')),
        },
        ITEM_MI_FICHAJE: {
            'id': ITEM_MI_FICHAJE,
            'label': str(_('Fichaje')),
            'icon': 'fa-fingerprint',
            'kind': 'link',
            'href': url_for('empleado.fichar'),
            'active': _ep() in ('empleado.fichar', 'empleado.inicio'),
            'data_tour': None,
        },
        ITEM_MI_CALENDARIO: {
            'id': ITEM_MI_CALENDARIO,
            'label': str(_('Mi calendario')),
            'icon': 'fa-calendar-alt',
            'kind': 'link',
            'href': url_for('empleado.calendario'),
            'active': _ep() == 'empleado.calendario',
            'data_tour': None,
        },
        ITEM_MI_HORAS: {
            'id': ITEM_MI_HORAS,
            'label': str(_('Mis horas')),
            'icon': 'fa-clock',
            'kind': 'link',
            'href': url_for('empleado.fichajes'),
            'active': _ep() == 'empleado.fichajes',
            'data_tour': None,
        },
        ITEM_MI_AUSENCIAS: {
            'id': ITEM_MI_AUSENCIAS,
            'label': str(_('Vacaciones')),
            'icon': 'fa-umbrella-beach',
            'kind': 'link',
            'href': url_for('empleado.ausencias'),
            'active': _ep() == 'empleado.ausencias',
            'data_tour': None,
        },
    }


def _config_group_active() -> bool:
    return (
        'configuracion' in _ep()
        or _ep() == 'admin.permisos_roles'
        or _ep() in ('sync.panel', 'sync.odoo_panel')
    )


def _config_children(ctx: dict) -> list[dict]:
    """Subentradas bajo Configuración (ajustes, permisos, integraciones)."""
    u = ctx.get('user') or current_user
    kids = [{
        'id': 'cfg_general',
        'label': str(_('Ajustes')),
        'icon': 'fa-sliders-h',
        'href': url_for('admin.configuracion_global'),
        'active': 'configuracion' in _ep() and 'permisos' not in _ep(),
        'external': False,
    }]
    if user_can(u, 'permisos', 'r'):
        kids.append({
            'id': 'cfg_permisos',
            'label': str(_('Permisos')),
            'icon': 'fa-user-shield',
            'href': url_for('admin.permisos_roles'),
            'active': _ep() == 'admin.permisos_roles',
            'external': False,
        })
    if user_can(u, 'integraciones', 'r'):
        kids.append({
            'id': 'cfg_integraciones',
            'label': str(_('Integraciones')),
            'icon': 'fa-plug',
            'href': url_for('sync.panel'),
            'active': _ep() in ('sync.panel', 'sync.odoo_panel'),
            'external': False,
        })
    return kids


def _integration_children(ctx: dict) -> list[dict]:
    """Legacy: el hub es ahora un enlace; se mantiene por si hay prefs antiguas."""
    u = ctx.get('user') or current_user
    kids = []
    if ctx.get('tenant_has_odoo') and user_can(u, 'sync_odoo', 'r'):
        kids.append({
            'id': 'odoo_sync',
            'label': str(_('Sincronización Odoo')),
            'icon': 'fa-sync',
            'href': url_for('sync.odoo_panel'),
            'active': _ep() == 'sync.odoo_panel',
            'external': False,
        })
    if ctx.get('tenant_has_odoo_alta') and user_can(u, 'soltec_alta_odoo', 'r'):
        kids.append({
            'id': 'odoo_alta',
            'label': str(_('Alta Odoo')),
            'icon': 'fa-address-book',
            'href': url_for('admin.sso_odoo_contactos'),
            'active': False,
            'external': True,
        })
    if ctx.get('tenant_has_soltec_portal_sso') and user_can(u, 'soltec_portal', 'r'):
        kids.append({
            'id': 'soltec_portal',
            'label': str(_('Portal Soltec')),
            'icon': 'fa-external-link-alt',
            'href': url_for('auth.sso_portal'),
            'active': False,
            'external': False,
        })
    if ctx.get('tenant_has_integrations') and user_can(u, 'integraciones', 'r'):
        kids.append({
            'id': 'integ_all',
            'label': str(_('Ver todas')),
            'icon': 'fa-th-large',
            'href': url_for('sync.panel'),
            'active': _ep() == 'sync.panel',
            'external': False,
        })
    return kids


def _portal_jornada_disponible(user, ctx: dict) -> bool:
    """El hub de jornada (fichaje/calendario/ausencias) requiere módulo activo."""
    if _is_operario(user):
        return True
    return bool(ctx.get('tenant_has_fichaje_operario'))


def item_is_available(item_id: str, user, ctx: dict) -> bool:
    if item_id == ITEM_INICIO:
        return not _is_operario(user)
    if item_id == ITEM_TABLERO:
        return user_can(user, 'tablero', 'r')
    if item_id == ITEM_DIRECTORIO:
        return user_can(user, 'directorio', 'r')
    if item_id == ITEM_PLANIFICADOR:
        return user_can(user, 'planificador', 'r')
    if item_id == ITEM_REUNIONES:
        return user_can(user, 'reuniones', 'r') and bool(ctx.get('tenant_has_notas'))
    if item_id == ITEM_TRABAJADORES:
        return user_can(user, 'trabajadores', 'r')
    if item_id == ITEM_SUBCONTRATAS:
        return user_can(user, 'subcontratas', 'r')
    if item_id == ITEM_SOLICITUDES:
        # Buzón de oficina: si el jefe mueve gente en el cuadrante, no hay
        # peticiones que gestionar. Vale para todos los roles, no solo el jefe.
        if ctx.get('jefes_asignan_directo'):
            return False
        return user_can(user, 'solicitudes', 'r')
    if item_id == ITEM_AUSENCIAS:
        return user_can(user, 'ausencias', 'r')
    if item_id == ITEM_FLOTA:
        return user_can(user, 'vehiculos', 'r')
    if item_id == ITEM_COCHES_LIBRES:
        return user_can(user, 'vehiculos_libres', 'r')
    if item_id == ITEM_AUDITORIA_VEH:
        return (
            user_can(user, 'auditoria_vehiculos', 'r')
            and bool(ctx.get('tenant_has_auditoria_vehiculos'))
            and bool(ctx.get('tenant_has_odoo'))
        )
    if item_id == ITEM_AUDITORIA_FICH:
        if not user_can(user, 'auditoria_fichajes', 'r'):
            return False
        return bool(ctx.get('muestra_auditoria_fichajes'))
    if item_id == ITEM_MAPA_FICH:
        if not user_can(user, 'mapa_fichajes', 'r'):
            return False
        return bool(ctx.get('tenant_has_fichaje_operario'))
    if item_id == ITEM_REGISTRO_JORNADA:
        return user_can(user, 'registro_jornada', 'r') and bool(ctx.get('tenant_has_registro_jornada'))
    if item_id == ITEM_INTEGRACIONES:
        # Quien tiene Configuración la ve ahí dentro. Quien no (p. ej. un jefe
        # con Odoo), sigue teniendo el enlace suelto.
        if user_can(user, 'configuracion', 'r'):
            return False
        return user_can(user, 'integraciones', 'r')
    if item_id == ITEM_ODOO_ALTA:
        return (
            bool(ctx.get('tenant_has_odoo_alta'))
            and user_can(user, 'soltec_alta_odoo', 'r')
        )
    if item_id == ITEM_SOLTEC_PORTAL:
        return (
            bool(ctx.get('tenant_has_soltec_portal_sso'))
            and user_can(user, 'soltec_portal', 'r')
        )
    if item_id == ITEM_PRIMEROS_PASOS:
        if not user_can(user, 'primeros_pasos', 'r'):
            return False
        if not ctx.get('tenant_has_onboarding'):
            return False
        if ctx.get('mostrar_onboarding'):
            return True
        return bool(ctx.get('academia_visible'))
    if item_id == ITEM_CONFIGURACION:
        return user_can(user, 'configuracion', 'r')
    if item_id == ITEM_PERMISOS:
        return user_can(user, 'permisos', 'r')
    if item_id == ITEM_LOGS:
        return user_can(user, 'logs', 'r')
    if item_id == ITEM_MI_FICHAJE:
        if not _portal_jornada_disponible(user, ctx):
            return False
        return (
            bool(ctx.get('tenant_has_fichaje_operario'))
            and user_can(user, 'operario_fichaje', 'r')
        )
    if item_id == ITEM_MI_CALENDARIO:
        if not _portal_jornada_disponible(user, ctx):
            return False
        return user_can(user, 'operario_calendario', 'r')
    if item_id == ITEM_MI_HORAS:
        if not _portal_jornada_disponible(user, ctx):
            return False
        return (
            bool(ctx.get('tenant_has_fichaje_operario'))
            and user_can(user, 'operario_fichaje', 'r')
        )
    if item_id == ITEM_MI_AUSENCIAS:
        if not _portal_jornada_disponible(user, ctx):
            return False
        return user_can(user, 'operario_ausencias', 'r')
    return False


def _raw_prefs(user) -> dict:
    raw = getattr(user, 'sidebar_prefs', None) or {}
    if not isinstance(raw, dict):
        return {}
    return raw


def _normalize_prefs_payload(payload: Any) -> dict:
    """Valida y limpia el JSON de preferencias."""
    if not isinstance(payload, dict):
        raise ValueError('Formato inválido')
    sections_in = payload.get('sections')
    if not isinstance(sections_in, list):
        raise ValueError('sections debe ser una lista')
    hidden_in = payload.get('hidden') or []
    if not isinstance(hidden_in, list):
        raise ValueError('hidden debe ser una lista')

    seen_items: set[str] = set()
    sections_out = []
    for sec in sections_in:
        if not isinstance(sec, dict):
            continue
        sid = str(sec.get('id') or '').strip() or f'sec_{uuid.uuid4().hex[:8]}'
        title = str(sec.get('title') if sec.get('title') is not None else '').strip()
        # límite razonable
        if len(title) > 60:
            title = title[:60]
        items = []
        for it in (sec.get('items') or []):
            key = str(it).strip()
            if key not in ALL_ITEM_KEYS or key in seen_items:
                continue
            seen_items.add(key)
            items.append(key)
        sections_out.append({'id': sid, 'title': title, 'items': items})

    if not sections_out:
        raise ValueError('Hace falta al menos una sección')

    hidden_out = []
    for h in hidden_in:
        key = str(h).strip()
        if key in ALL_ITEM_KEYS and key not in hidden_out:
            hidden_out.append(key)

    return {'sections': sections_out, 'hidden': hidden_out}


def save_sidebar_prefs(user, payload: dict) -> dict:
    from sqlalchemy.orm.attributes import flag_modified

    cleaned = _normalize_prefs_payload(payload)
    user.sidebar_prefs = cleaned
    flag_modified(user, 'sidebar_prefs')
    db.session.add(user)
    db.session.commit()
    return cleaned


def build_sidebar_nav(user, ctx: Optional[dict] = None) -> dict:
    """
    Devuelve { sections: [...], hidden: [...], edit_mode_items: [...] }
    listo para la plantilla.
    """
    ctx = dict(ctx or {})
    ctx['user'] = user
    defs = catalog_definitions(ctx)
    available = {k: v for k, v in defs.items() if item_is_available(k, user, ctx)}

    prefs = _raw_prefs(user)
    sections_pref = prefs.get('sections') if isinstance(prefs.get('sections'), list) else None
    hidden_raw = prefs.get('hidden') if isinstance(prefs.get('hidden'), list) else None

    # En suplantación: menú fijo del operario (no prefs de oficina ni personalizadas).
    if ctx.get('impersonacion_activa') and _is_operario(user):
        sections_pref = _operario_sections_blueprint()
        hidden_raw = []

    # Migrar el layout stock antiguo (Personal/Vehículos/Jornada) al nuevo por defecto
    if sections_pref is not None and _is_stock_v1_layout(sections_pref):
        sections_pref = None
        hidden_raw = list(_default_hidden())

    if sections_pref is None and hidden_raw is None:
        sections_pref = (
            _operario_sections_blueprint()
            if _is_operario(user)
            else _default_sections_blueprint()
        )
        hidden_pref = set(_default_hidden())
    else:
        if sections_pref is None:
            sections_pref = (
                _operario_sections_blueprint()
                if _is_operario(user)
                else _default_sections_blueprint()
            )
        hidden_pref = set(hidden_raw or [])

    placed: set[str] = set()
    sections_out = []
    for sec in sections_pref:
        if not isinstance(sec, dict):
            continue
        sid = str(sec.get('id') or f'sec_{uuid.uuid4().hex[:8]}')
        title = str(sec.get('title') if sec.get('title') is not None else '')
        sec_items = [str(x) for x in (sec.get('items') or [])]
        items_resolved = []
        for key in sec_items:
            if key not in available or key in placed:
                continue
            # Permisos e Integraciones viven bajo Configuración; no duplicar.
            if key in (ITEM_PERMISOS, ITEM_INTEGRACIONES) and ITEM_CONFIGURACION in sec_items:
                continue
            placed.add(key)
            item = copy.deepcopy(available[key])
            item['hidden'] = key in hidden_pref
            items_resolved.append(item)
        sections_out.append({
            'id': sid,
            'title': title,
            'items': items_resolved,
        })

    if ITEM_CONFIGURACION in placed:
        placed.add(ITEM_PERMISOS)
        placed.add(ITEM_INTEGRACIONES)

    # Ítems nuevos (permisos nuevos) que no estaban en prefs → sección al final
    orphan_keys = [k for k in available.keys() if k not in placed]
    if orphan_keys:
        # Intentar meterlos en su sección por defecto si existe
        default_map = {}
        for sec in _default_sections_blueprint():
            for k in sec['items']:
                default_map[k] = sec['id']
        by_sec: dict[str, list] = {}
        for k in orphan_keys:
            sec_id = default_map.get(k, 'sec_extra')
            by_sec.setdefault(sec_id, []).append(k)
        sec_index = {s['id']: s for s in sections_out}
        for sec_id, keys in by_sec.items():
            if sec_id in sec_index:
                for k in keys:
                    item = copy.deepcopy(available[k])
                    item['hidden'] = k in hidden_pref
                    sec_index[sec_id]['items'].append(item)
                    placed.add(k)
            else:
                title = str(_('Más')) if sec_id == 'sec_extra' else ''
                # buscar título default
                for d in _default_sections_blueprint():
                    if d['id'] == sec_id:
                        title = d['title']
                        break
                items_resolved = []
                for k in keys:
                    item = copy.deepcopy(available[k])
                    item['hidden'] = k in hidden_pref
                    items_resolved.append(item)
                    placed.add(k)
                sections_out.append({'id': sec_id, 'title': title, 'items': items_resolved})

    # En modo normal la plantilla solo pinta no-hidden; en config pinta todos
    return {
        'sections': sections_out,
        'hidden': sorted(hidden_pref & set(available.keys())),
        'available_ids': list(available.keys()),
    }


def prefs_for_client(user, ctx: Optional[dict] = None) -> dict:
    """Snapshot serializable para el JS de configuración."""
    nav = build_sidebar_nav(user, ctx)
    return {
        'sections': [
            {
                'id': s['id'],
                'title': s['title'],
                'items': [it['id'] for it in s['items']],
            }
            for s in nav['sections']
        ],
        'hidden': nav['hidden'],
    }
