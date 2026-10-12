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
from app.models import (
    ROLE_ADMIN,
    ROLE_ADMIN_SUBCONTRATA,
    ROLE_JEFE,
    ROLE_LABORAL,
    ROLE_OPERARIO,
    ROLE_RRHH,
)
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
ITEM_DOCUMENTACION = 'documentacion'
ITEM_CERTIFICACION = 'certificacion'
ITEM_CONTRATACION = 'contratacion'
ITEM_MI_DOCUMENTACION = 'mi_documentacion'
ITEM_SUB_PERSONAL = 'sub_personal'

# Roles de oficina: no usan el portal «mi calendario / fichaje / horas».
_ROLES_OFICINA = frozenset({ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL, ROLE_RRHH})
_PORTAL_NAV_ITEMS = frozenset({
    ITEM_MI_FICHAJE,
    ITEM_MI_CALENDARIO,
    ITEM_MI_HORAS,
    ITEM_MI_AUSENCIAS,
})

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
    ITEM_DOCUMENTACION,
    ITEM_CERTIFICACION,
    ITEM_CONTRATACION,
    ITEM_MI_DOCUMENTACION,
    ITEM_SUB_PERSONAL,
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
                ITEM_MI_DOCUMENTACION,
            ],
        },
    ]


def _subcontrata_sections_blueprint() -> list[dict]:
    return [
        {
            'id': 'sec_home',
            'title': '',
            'items': [
                ITEM_INICIO,
                ITEM_SUB_PERSONAL,
                ITEM_MI_FICHAJE,
                ITEM_MI_CALENDARIO,
                ITEM_DOCUMENTACION,
                ITEM_CERTIFICACION,
            ],
        },
        {
            'id': 'sec_sys',
            'title': str(_('Cuenta')),
            'items': [ITEM_CONFIGURACION],
        },
    ]


def _is_operario(user) -> bool:
    return getattr(user, 'role', None) == ROLE_OPERARIO


def _is_admin_subcontrata(user) -> bool:
    return getattr(user, 'role', None) == ROLE_ADMIN_SUBCONTRATA


# Hijos absorbidos por un padre-grupo (no se pintan sueltos si el padre está).
_GROUP_ABSORBS = {
    ITEM_TRABAJADORES: frozenset({ITEM_AUSENCIAS, ITEM_CONTRATACION}),
    ITEM_SUBCONTRATAS: frozenset({ITEM_CERTIFICACION}),
    ITEM_FLOTA: frozenset({ITEM_COCHES_LIBRES, ITEM_AUDITORIA_VEH}),
    ITEM_CONFIGURACION: frozenset({ITEM_PERMISOS}),
    ITEM_INTEGRACIONES: frozenset({ITEM_ODOO_ALTA, ITEM_SOLTEC_PORTAL}),
}


def _default_sections_blueprint() -> list[dict]:
    """Estructura por defecto (títulos traducidos al construir)."""
    return [
        {
            'id': 'sec_home',
            'title': '',
            'items': [ITEM_INICIO],
        },
        {
            'id': 'sec_plan',
            'title': str(_('Planificación')),
            'items': [ITEM_TABLERO, ITEM_PLANIFICADOR],
        },
        {
            'id': 'sec_gestion',
            'title': str(_('Gestión')),
            'items': [
                ITEM_DIRECTORIO,
                ITEM_TRABAJADORES,
                ITEM_SUBCONTRATAS,
                ITEM_FLOTA,
            ],
        },
        {
            'id': 'sec_ops',
            'title': str(_('Operaciones')),
            'items': [ITEM_SOLICITUDES, ITEM_AUDITORIA_FICH],
        },
        {
            'id': 'sec_docs',
            'title': str(_('Cumplimiento')),
            'items': [ITEM_DOCUMENTACION],
        },
        {
            'id': 'sec_sys',
            'title': str(_('Sistema')),
            'items': [
                ITEM_CONFIGURACION,
                ITEM_INTEGRACIONES,
                ITEM_REUNIONES,
                ITEM_LOGS,
            ],
        },
    ]


def _default_hidden() -> list[str]:
    """Ítems del catálogo ocultos en el menú por defecto (siguen en personalizar)."""
    return [
        ITEM_MAPA_FICH,
        ITEM_REGISTRO_JORNADA,
        ITEM_PRIMEROS_PASOS,
    ]


def _is_stock_legacy_layout(sections: list) -> bool:
    """True si hay que migrar prefs al menú con secciones actuales."""
    ids = {str(s.get('id')) for s in sections if isinstance(s, dict)}
    # Layout nuevo: home + plan + gestión + ops + docs + sistema
    if {'sec_plan', 'sec_gestion', 'sec_ops', 'sec_sys'} <= ids:
        return False
    # Plano sec_main, stock multi-sección anterior, o Personal/Flota/Jornada
    if 'sec_main' in ids:
        return True
    if ids & {
        'sec_gestion', 'sec_plan', 'sec_solicitudes', 'sec_audit',
        'sec_soltec', 'sec_sys', 'sec_home', 'sec_ops', 'sec_docs',
    }:
        # Tiene alguna sección conocida pero no el set completo → migrar
        return not ({'sec_plan', 'sec_gestion', 'sec_ops', 'sec_sys'} <= ids)
    return 'sec_personal' in ids and 'sec_fleet' in ids


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
        'jefe.panel', 'empleado.calendario', 'subcontrata.inicio',
        'subcontrata.calendario',
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
        ITEM_TRABAJADORES: _nav_group(
            item_id=ITEM_TRABAJADORES,
            label=str(_('Trabajadores')),
            icon='fa-users',
            href=url_for('admin.personal'),
            parent_active='personal' in _ep(),
            children=_trabajadores_children(ctx),
            data_tour='nav-trabajadores',
        ),
        ITEM_SUBCONTRATAS: _nav_group(
            item_id=ITEM_SUBCONTRATAS,
            label=str(_('Subcontratas')),
            icon='fa-industry',
            href=url_for('admin.companies'),
            parent_active=('companies' in _ep() or _ep() == 'admin.company_panel'),
            children=_subcontratas_children(ctx),
            data_tour='nav-empresas',
        ),
        ITEM_DOCUMENTACION: {
            'id': ITEM_DOCUMENTACION,
            'label': str(_('Documentación')),
            'icon': 'fa-folder-open',
            'kind': 'link',
            'href': (
                url_for('subcontrata.documentacion')
                if _is_admin_subcontrata(u)
                else url_for('compliance.documentacion')
            ),
            'active': _ep() in (
                'compliance.documentacion', 'compliance.documentacion_empresa',
                'compliance.documentacion_empleado', 'subcontrata.documentacion',
                'subcontrata.documentacion_persona',
            ),
            'data_tour': None,
            'badge': int(ctx.get('doc_errores') or 0),
            'badge_warn': int(ctx.get('doc_avisos') or 0),
        },
        ITEM_CERTIFICACION: {
            'id': ITEM_CERTIFICACION,
            'label': str(_('Cert. de horario')),
            'icon': 'fa-clock',
            'kind': 'link',
            'href': (
                url_for('subcontrata.certificacion')
                if _is_admin_subcontrata(u)
                else url_for('compliance.certificacion_lista')
            ),
            'active': 'certificacion' in _ep(),
            'data_tour': None,
            'badge': int(ctx.get('cert_entrantes') or 0),
        },
        ITEM_CONTRATACION: {
            'id': ITEM_CONTRATACION,
            'label': str(_('Contratación')),
            'icon': 'fa-user-check',
            'kind': 'link',
            'href': url_for('compliance.contratacion_lista'),
            'active': 'contratacion' in _ep() and not str(_ep()).startswith('empleado.'),
            'data_tour': None,
            'badge': int(ctx.get('contratacion_pendientes') or 0),
        },
        ITEM_MI_DOCUMENTACION: {
            'id': ITEM_MI_DOCUMENTACION,
            'label': str(_('Mi documentación')) if not getattr(u, 'hiring_state', None) else str(_('Mi contratación')),
            'icon': 'fa-id-card',
            'kind': 'link',
            'href': (
                url_for('empleado.contratacion')
                if getattr(u, 'hiring_state', None)
                else url_for('empleado.mis_documentos')
            ),
            'active': _ep() in ('empleado.mis_documentos', 'empleado.contratacion'),
            'data_tour': None,
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
            'badge_personal': int(ctx.get('pending_solicitudes_personal') or 0),
            'badge_vehiculos': int(ctx.get('pending_solicitudes_vehiculos') or 0),
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
        ITEM_FLOTA: _nav_group(
            item_id=ITEM_FLOTA,
            label=str(_('Flota')),
            icon='fa-car',
            href=url_for('admin.vehiculos'),
            parent_active=_ep() in ('admin.vehiculos', 'admin.vehicle_panel'),
            children=_flota_children(ctx),
            data_tour=None,
        ),
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
        ITEM_INTEGRACIONES: _nav_group(
            item_id=ITEM_INTEGRACIONES,
            label=str(_('Integraciones')),
            icon='fa-plug',
            href=url_for('sync.panel'),
            parent_active=_ep() in ('sync.panel', 'sync.odoo_panel'),
            children=_integration_children(ctx),
            data_tour=None,
        ),
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
        ITEM_CONFIGURACION: (
            {
                'id': ITEM_CONFIGURACION,
                'label': str(_('Preferencias')),
                'icon': 'fa-user-cog',
                'kind': 'link',
                'href': url_for('admin.configuracion_global'),
                'active': _ep() == 'admin.configuracion_global',
                'data_tour': None,
            }
            if _is_admin_subcontrata(u)
            else _nav_group(
                item_id=ITEM_CONFIGURACION,
                label=str(_('Configuración')),
                icon='fa-sliders-h',
                href=url_for('admin.configuracion_global'),
                parent_active=_config_group_active(),
                children=_config_children(ctx),
                data_tour=None,
            )
        ),
        ITEM_SUB_PERSONAL: {
            'id': ITEM_SUB_PERSONAL,
            'label': str(_('Trabajadores')),
            'icon': 'fa-users',
            'kind': 'link',
            'href': url_for('subcontrata.personal'),
            'active': _ep() in ('subcontrata.personal', 'subcontrata.personal_calendario'),
            'data_tour': None,
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
            'label': str(_('Calendario') if _is_admin_subcontrata(u) else _('Mi calendario')),
            'icon': 'fa-calendar-alt',
            'kind': 'link',
            'href': (
                url_for('subcontrata.calendario')
                if _is_admin_subcontrata(u)
                else url_for('empleado.calendario')
            ),
            'active': _ep() in ('empleado.calendario', 'subcontrata.calendario'),
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
        # URL antigua de ajustes doc → redirige a Configuración.
        or _ep() == 'compliance.ajustes'
    )


def _nav_group(*, item_id, label, icon, href, parent_active, children, data_tour=None) -> dict:
    kids = list(children or [])
    child_active = any(bool(c.get('active')) for c in kids)
    active = bool(parent_active) or child_active
    badge = sum(int(c.get('badge') or 0) for c in kids)
    return {
        'id': item_id,
        'label': label,
        'icon': icon,
        'kind': 'group',
        'href': href,
        'active': active,
        'open': active,
        'data_tour': data_tour,
        'children': kids,
        'badge': badge,
    }


def _trabajadores_children(ctx: dict) -> list[dict]:
    u = ctx.get('user') or current_user
    kids = []
    if user_can(u, 'ausencias', 'r'):
        kids.append({
            'id': ITEM_AUSENCIAS,
            'label': str(_('Ausencias')),
            'icon': 'fa-umbrella-beach',
            'href': url_for('admin.ausencias_list'),
            'active': 'ausencias' in _ep() and not str(_ep()).startswith('empleado.'),
            'external': False,
        })
    if item_is_available(ITEM_CONTRATACION, u, ctx):
        kids.append({
            'id': ITEM_CONTRATACION,
            'label': str(_('Contratación')),
            'icon': 'fa-user-check',
            'href': url_for('compliance.contratacion_lista'),
            'active': 'contratacion' in _ep() and not str(_ep()).startswith('empleado.'),
            'external': False,
            'badge': int(ctx.get('contratacion_pendientes') or 0),
        })
    return kids


def _subcontratas_children(ctx: dict) -> list[dict]:
    u = ctx.get('user') or current_user
    kids = []
    if item_is_available(ITEM_CERTIFICACION, u, ctx):
        kids.append({
            'id': ITEM_CERTIFICACION,
            'label': str(_('Cert. de horario')),
            'icon': 'fa-clock',
            'href': (
                url_for('subcontrata.certificacion')
                if _is_admin_subcontrata(u)
                else url_for('compliance.certificacion_lista')
            ),
            'active': 'certificacion' in _ep(),
            'external': False,
            'badge': int(ctx.get('cert_entrantes') or 0),
        })
    return kids


def _flota_children(ctx: dict) -> list[dict]:
    u = ctx.get('user') or current_user
    kids = []
    if user_can(u, 'vehiculos_libres', 'r'):
        kids.append({
            'id': ITEM_COCHES_LIBRES,
            'label': str(_('Coches libres')),
            'icon': 'fa-car-side',
            'href': url_for('admin.vehiculos_libres'),
            'active': _ep() == 'admin.vehiculos_libres',
            'external': False,
        })
    if item_is_available(ITEM_AUDITORIA_VEH, u, ctx):
        kids.append({
            'id': ITEM_AUDITORIA_VEH,
            'label': str(_('Auditoría de vehículos')),
            'icon': 'fa-clipboard-check',
            'href': url_for('sync.auditoria_vehiculos'),
            'active': _ep() == 'sync.auditoria_vehiculos',
            'external': False,
        })
    return kids


def _config_children(ctx: dict) -> list[dict]:
    """Subentradas bajo Configuración: solo Permisos (ajustes = clic en el padre)."""
    u = ctx.get('user') or current_user
    kids = []
    if user_can(u, 'permisos', 'r'):
        kids.append({
            'id': 'cfg_permisos',
            'label': str(_('Permisos')),
            'icon': 'fa-user-shield',
            'href': url_for('admin.permisos_roles'),
            'active': _ep() == 'admin.permisos_roles',
            'external': False,
        })
    return kids


def _integration_children(ctx: dict) -> list[dict]:
    """Integraciones del tenant (Soltec: Alta Odoo, Portal, Odoo…)."""
    u = ctx.get('user') or current_user
    kids = []
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
    if ctx.get('tenant_has_odoo') and user_can(u, 'sync_odoo', 'r'):
        kids.append({
            'id': 'odoo_sync',
            'label': str(_('Odoo')),
            'icon': 'fa-sync',
            'href': url_for('sync.odoo_panel'),
            'active': _ep() == 'sync.odoo_panel',
            'external': False,
        })
    return kids


def item_is_available(item_id: str, user, ctx: dict) -> bool:
    # Oficina no lleva entradas del portal propio aunque la matriz las tenga.
    if item_id in _PORTAL_NAV_ITEMS and getattr(user, 'role', None) in _ROLES_OFICINA:
        return False
    if item_id == ITEM_INICIO:
        if _is_admin_subcontrata(user):
            return True
        return user_can(user, 'inicio', 'r')
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
    if item_id == ITEM_SUB_PERSONAL:
        return _is_admin_subcontrata(user)
    if item_id == ITEM_SUBCONTRATAS:
        return user_can(user, 'subcontratas', 'r')
    if item_id == ITEM_SOLICITUDES:
        # Buzón: ver personal y/o flota. Crear va por planificar en modo solicitud.
        return (
            user_can(user, 'solicitudes', 'r')
            or user_can(user, 'solicitudes_vehiculos', 'r')
        )
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
        # Visible si hay hub o alguna integración concreta del tenant.
        if user_can(user, 'integraciones', 'r'):
            return True
        if ctx.get('tenant_has_odoo') and user_can(user, 'sync_odoo', 'r'):
            return True
        if ctx.get('tenant_has_odoo_alta') and user_can(user, 'soltec_alta_odoo', 'r'):
            return True
        if ctx.get('tenant_has_soltec_portal_sso') and user_can(user, 'soltec_portal', 'r'):
            return True
        return False
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
        # Preferencias personales (idioma / avisos UI). Operario: solo si tiene
        # permiso tenant. El resto del shell oficina/subcontrata siempre.
        if _is_operario(user):
            return user_can(user, 'configuracion', 'r')
        return True
    if item_id == ITEM_PERMISOS:
        return user_can(user, 'permisos', 'r')
    if item_id == ITEM_LOGS:
        return user_can(user, 'logs', 'r')
    if item_id == ITEM_MI_FICHAJE:
        return (
            bool(ctx.get('tenant_has_fichaje_operario'))
            and user_can(user, 'operario_fichaje', 'r')
        )
    if item_id == ITEM_MI_CALENDARIO:
        return user_can(user, 'operario_calendario', 'r')
    if item_id == ITEM_MI_HORAS:
        return (
            bool(ctx.get('tenant_has_fichaje_operario'))
            and user_can(user, 'operario_fichaje', 'r')
        )
    if item_id == ITEM_MI_AUSENCIAS:
        return user_can(user, 'operario_ausencias', 'r')
    if item_id == ITEM_DOCUMENTACION:
        from app.services.tenant_modules import has_documentacion
        if not has_documentacion() or not user_can(user, 'documentacion', 'r'):
            return False
        if _is_admin_subcontrata(user):
            return True
        return getattr(user, 'role', None) != ROLE_OPERARIO
    if item_id == ITEM_CERTIFICACION:
        from app.services.tenant_modules import has_certificacion
        if not has_certificacion() or not user_can(user, 'certificacion', 'r'):
            return False
        if _is_admin_subcontrata(user):
            return True
        return getattr(user, 'role', None) != ROLE_OPERARIO
    if item_id == ITEM_CONTRATACION:
        from app.services.tenant_modules import has_contratacion
        if not has_contratacion() or not user_can(user, 'contratacion', 'r'):
            return False
        return getattr(user, 'role', None) not in (ROLE_OPERARIO, ROLE_ADMIN_SUBCONTRATA)
    if item_id == ITEM_MI_DOCUMENTACION:
        from app.services.tenant_modules import has_documentacion
        if getattr(user, 'hiring_state', None):
            return True
        return has_documentacion() and user_can(user, 'documentacion', 'r') and _is_operario(user)
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

    # Migrar layouts stock antiguos al menú sec_main
    if sections_pref is not None and _is_stock_legacy_layout(sections_pref):
        sections_pref = None
        hidden_raw = list(_default_hidden())

    if getattr(user, 'hiring_state', None):
        sections_pref = [{
            'id': 'sec_contratacion',
            'title': '',
            'items': [ITEM_MI_DOCUMENTACION],
        }]
        hidden_raw = []

    def _sections_for_user():
        if _is_admin_subcontrata(user):
            return _subcontrata_sections_blueprint()
        if _is_operario(user):
            return _operario_sections_blueprint()
        return _default_sections_blueprint()

    if sections_pref is None and hidden_raw is None:
        sections_pref = _sections_for_user()
        hidden_pref = set(_default_hidden())
    else:
        if sections_pref is None:
            sections_pref = _sections_for_user()
        hidden_pref = set(hidden_raw or [])

    placed: set[str] = set()
    sections_out = []
    for sec in sections_pref:
        if not isinstance(sec, dict):
            continue
        sid = str(sec.get('id') or f'sec_{uuid.uuid4().hex[:8]}')
        title = str(sec.get('title') if sec.get('title') is not None else '')
        sec_items = [str(x) for x in (sec.get('items') or [])]
        # Solo absorber hijos si el padre está disponible (si no, salen sueltos).
        absorbed_here = set()
        for key in sec_items:
            if key in available:
                absorbed_here |= _GROUP_ABSORBS.get(key, frozenset())
        items_resolved = []
        for key in sec_items:
            if key not in available or key in placed:
                continue
            # Hijos de un grupo presente en esta sección: no duplicar como ítem suelto.
            if key in absorbed_here:
                continue
            placed.add(key)
            for child_key in _GROUP_ABSORBS.get(key, frozenset()):
                placed.add(child_key)
            item = copy.deepcopy(available[key])
            item['hidden'] = key in hidden_pref
            items_resolved.append(item)
        sections_out.append({
            'id': sid,
            'title': title,
            'items': items_resolved,
        })

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
