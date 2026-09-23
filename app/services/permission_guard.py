"""Enforcement de la matriz de permisos por prefijo de ruta."""
from __future__ import annotations

from flask import flash, jsonify, redirect, request, url_for
from flask_login import current_user
from urllib.parse import urlparse

from app.services.permission_service import user_can

# (path_prefix, module, default_action, {HTTP_METHOD: action})
# Orden: prefijos más específicos primero.
_ADMIN_RULES = (
    ('/admin/permisos', 'permisos', 'r', {'POST': 'w'}),
    ('/admin/configuracion', 'configuracion', 'r', {'POST': 'w'}),
    ('/admin/api/tour', 'primeros_pasos', 'r', {'POST': 'w'}),
    ('/admin/tour', 'primeros_pasos', 'r', {}),
    ('/admin/primeros-pasos', 'primeros_pasos', 'r', {'POST': 'w'}),
    ('/admin/obras_detailed', 'tablero', 'r', {}),
    ('/admin/planificador', 'planificador', 'r', {'POST': 'w'}),
    ('/admin/api/planificador/', 'planificador', 'r', {'POST': 'w'}),
    ('/admin/api/planificador/fichajes-estado', 'planificador', 'r', {}),
    ('/admin/solicitudes-vehiculo', 'solicitudes_vehiculos', 'r', {'POST': 'w'}),
    ('/admin/solicitudes', 'solicitudes', 'r', {'POST': 'w'}),
    ('/admin/ausencias', 'ausencias', 'r', {'POST': 'w'}),
    ('/admin/api/rate_worker', 'valoraciones', 'w', {'POST': 'w'}),
    ('/admin/api/rating/', 'valoraciones', 'w', {'PUT': 'w', 'DELETE': 'w', 'POST': 'w'}),
    ('/admin/vehiculos/libres', 'vehiculos_libres', 'r', {}),
    ('/admin/vehiculos_libres', 'vehiculos_libres', 'r', {}),
    ('/admin/vehiculos', 'vehiculos', 'r', {'POST': 'w'}),
    ('/admin/vehicle_panel', 'vehiculos', 'r', {}),
    ('/admin/registro_jornada', 'registro_jornada', 'r', {}),
    ('/admin/registro-jornada', 'registro_jornada', 'r', {}),
    ('/admin/system_logs', 'logs', 'r', {'POST': 'w'}),
    ('/admin/logs', 'logs', 'r', {'POST': 'w'}),
    # Trabajadores: listado + CRUD / import / accesos
    ('/admin/personal', 'trabajadores', 'r', {'POST': 'w'}),
    ('/admin/worker_panel', 'trabajadores', 'r', {'POST': 'w'}),
    ('/admin/worker', 'trabajadores', 'r', {'POST': 'w'}),
    ('/admin/create_user', 'trabajadores', 'w', {'GET': 'w', 'POST': 'w'}),
    ('/admin/edit_operario', 'trabajadores', 'w', {'GET': 'w', 'POST': 'w'}),
    ('/admin/delete_user', 'trabajadores', 'w', {'POST': 'w'}),
    ('/admin/deactivate_operario', 'trabajadores', 'w', {'POST': 'w'}),
    ('/admin/approve_operario', 'trabajadores', 'w', {'POST': 'w'}),
    ('/admin/schedule_status', 'trabajadores', 'w', {'POST': 'w'}),
    ('/admin/import_users', 'trabajadores', 'w', {'GET': 'w', 'POST': 'w'}),
    ('/admin/reset_password', 'trabajadores', 'w', {'POST': 'w'}),
    ('/admin/reset_pin', 'trabajadores', 'w', {'POST': 'w'}),
    ('/admin/enviar_acceso_fichaje', 'trabajadores', 'w', {'POST': 'w'}),
    ('/admin/enviar_informacion_acceso', 'trabajadores', 'w', {'POST': 'w'}),
    # Subcontratas
    ('/admin/companies', 'subcontratas', 'r', {'POST': 'w'}),
    ('/admin/company_panel', 'subcontratas', 'r', {}),
    ('/admin/company', 'subcontratas', 'r', {'POST': 'w'}),
    ('/admin/create_company', 'subcontratas', 'w', {'GET': 'w', 'POST': 'w'}),
    ('/admin/import_companies', 'subcontratas', 'w', {'GET': 'w', 'POST': 'w'}),
    # Directorio obras: listado + CRUD / import / staff / batch
    ('/admin/obras', 'directorio', 'r', {'POST': 'w'}),
    ('/admin/create_obra', 'directorio', 'w', {'GET': 'w', 'POST': 'w'}),
    ('/admin/edit_obra', 'directorio', 'w', {'GET': 'w', 'POST': 'w'}),
    ('/admin/delete_obra', 'directorio', 'w', {'POST': 'w'}),
    ('/admin/import_obras', 'directorio', 'w', {'GET': 'w', 'POST': 'w'}),
    ('/admin/buscar_obras', 'directorio', 'r', {}),
    ('/admin/active_obras', 'directorio', 'r', {}),
    ('/admin/api/update_obra_staff', 'directorio', 'w', {'POST': 'w'}),
    ('/admin/api/update_obra_jefe', 'directorio', 'w', {'POST': 'w'}),
    ('/admin/api/obra/', 'directorio', 'w', {'POST': 'w'}),
    ('/admin/api/obras/batch_status', 'directorio', 'w', {'POST': 'w'}),
    ('/admin/api/check_obra_status_impact', 'directorio', 'r', {'POST': 'r'}),
    ('/admin/api/companies/batch_delete', 'subcontratas', 'w', {'POST': 'w'}),
    ('/admin/api/users/batch_delete', 'trabajadores', 'w', {'POST': 'w'}),
    ('/admin/api/users/batch_deactivate', 'trabajadores', 'w', {'POST': 'w'}),
    ('/admin/mapa-fichajes', 'mapa_fichajes', 'r', {}),
    ('/admin/api/mapa-fichajes', 'mapa_fichajes', 'r', {}),
    ('/admin/panel-laboral', 'inicio', 'r', {}),
    ('/admin/panel', 'inicio', 'r', {}),
    ('/admin/obra', 'tablero', 'r', {'POST': 'w'}),
    ('/admin/sso/odoo_contactos', 'soltec_alta_odoo', 'r', {}),
)

# Sync «Auto ahora» por módulo: escritura del panel del elemento (o sync_odoo vía path_allows_user).
_SYNC_API_RUN_MODULE = {
    'obras': 'directorio',
    'empleados': 'trabajadores',
    'subcontratas': 'subcontratas',
    'ausencias': 'ausencias',
    'fichajes': 'auditoria_fichajes',
    'fichajes-retro': 'auditoria_fichajes',
    'vehiculos': 'auditoria_vehiculos',
    'vehiculos-retro': 'auditoria_vehiculos',
}

_SYNC_RULES = (
    ('/sync/auditoria-vehiculos', 'auditoria_vehiculos', 'r', {'POST': 'w'}),
    ('/sync/auditoria', 'auditoria_fichajes', 'r', {'POST': 'w'}),
    # Historial del día (pelotitas): NO es el hub Odoo. Sin esta línea pega
    # el catch-all /sync → integraciones y el fetch recibe un HTML de redirect.
    ('/sync/timeline_dia', 'auditoria_fichajes', 'r', {}),
    # Previews y commits = escritura del centro Odoo
    ('/sync/api/sync-log', 'sync_odoo', 'r', {'POST': 'w'}),
    ('/sync/api/test-connection', 'sync_odoo', 'w', {'POST': 'w'}),
    ('/sync/api/config', 'sync_odoo', 'w', {'POST': 'w'}),
    ('/sync/preview', 'sync_odoo', 'w', {'POST': 'w'}),
    ('/sync/commit', 'sync_odoo', 'w', {'POST': 'w'}),
    ('/sync/resolve_conflict', 'sync_odoo', 'w', {'POST': 'w'}),
    # api/run/<task> se resuelve en match_request_permission (módulo del task)
    ('/sync/odoo', 'sync_odoo', 'r', {'POST': 'w'}),
    ('/sync/fichajes_manual', 'auditoria_fichajes', 'w', {'POST': 'w'}),
    ('/sync/vehiculos_manual', 'auditoria_vehiculos', 'w', {'POST': 'w'}),
    ('/sync/conciliacion', 'sync_odoo', 'r', {'POST': 'w'}),
    ('/sync', 'integraciones', 'r', {'POST': 'w'}),
)

_NOTAS_RULES = (
    ('/notas', 'reuniones', 'r', {'POST': 'w'}),
)

_JEFE_RULES = (
    ('/jefe/obras_detailed', 'tablero', 'r', {}),
    ('/jefe/panel', 'inicio', 'r', {}),
    ('/jefe', 'inicio', 'r', {}),
)

_EMPLEADO_RULES = (
    ('/fichaje/ausencias', 'operario_ausencias', 'r', {'POST': 'w'}),
    ('/fichaje/calendario', 'operario_calendario', 'r', {}),
    ('/fichaje/fichar', 'operario_fichaje', 'r', {'POST': 'w'}),
    ('/fichaje/conformar', 'operario_fichaje', 'r', {'POST': 'w'}),
    ('/fichaje/fichajes', 'operario_fichaje', 'r', {}),
    ('/fichaje/fichajes.csv', 'operario_fichaje', 'r', {}),
    ('/fichaje/pin', 'operario_fichaje', 'r', {'POST': 'w'}),
    ('/empleado/ausencias', 'operario_ausencias', 'r', {'POST': 'w'}),
    ('/empleado/calendario', 'operario_calendario', 'r', {}),
    ('/empleado/fichar', 'operario_fichaje', 'r', {}),
    ('/empleado/fichajes', 'operario_fichaje', 'r', {}),
)

_PORTAL_JORNADA_MODULES = (
    ('operario_fichaje', 'r'),
    ('operario_calendario', 'r'),
    ('operario_ausencias', 'r'),
)

# Auth: atajos SSO salientes (defensa en profundidad; la ruta también chequea user_can)
_AUTH_RULES = (
    ('/auth/sso/portal', 'soltec_portal', 'r', {}),
)

_ALL_RULE_SETS = (
    _ADMIN_RULES,
    _SYNC_RULES,
    _NOTAS_RULES,
    _JEFE_RULES,
    _EMPLEADO_RULES,
    _AUTH_RULES,
)


def _match_rule(rules, path: str, method: str):
    method = (method or 'GET').upper()
    for prefix, module, default_action, overrides in rules:
        if not path.startswith(prefix):
            continue
        rest = path[len(prefix):]
        # Continuación válida: fin de path, query, subruta /, o sufijo _ (preview_obras)
        if rest and not rest.startswith(('/', '?', '_')):
            continue
        action = overrides.get(method, default_action)
        if method in ('PUT', 'PATCH', 'DELETE') and method not in overrides:
            action = 'w'
        return module, action
    return None


def _action_for(rules, method: str):
    return _match_rule(rules, request.path or '', method)


def match_request_permission():
    """Si la ruta está en el mapa, (module, action); si no, None."""
    path = request.path or ''
    method = request.method or 'GET'
    # Valoraciones anidadas bajo /admin/worker/…
    if path.startswith('/admin/worker/') and path.rstrip('/').endswith('/ratings_history'):
        return 'valoraciones', 'r'
    if path.startswith('/admin/worker/') and path.rstrip('/').endswith('/reset_ratings'):
        return 'valoraciones', 'w'
    # /sync/api/run/<task> → permiso del módulo de ese task (no el hub Odoo entero)
    if path.startswith('/sync/api/run/'):
        task = path[len('/sync/api/run/'):].split('/', 1)[0]
        module = _SYNC_API_RUN_MODULE.get(task)
        if module:
            action = 'w' if (method or 'GET').upper() in ('POST', 'PUT', 'PATCH', 'DELETE') else 'r'
            return module, action
    for rules in _ALL_RULE_SETS:
        matched = _match_rule(rules, path, method)
        if matched:
            return matched
    return None


def path_allows_user(user) -> bool:
    """True si la ruta está en el mapa y el usuario tiene el permiso."""
    matched = match_request_permission()
    if not matched:
        return False
    module, action = matched
    if user_can(user, module, action):
        return True
    # Buzón unificado: personal o flota
    if module == 'solicitudes' and (
        user_can(user, 'solicitudes_vehiculos', action)
    ):
        return True
    # Coches libres: módulo propio o lectura de flota
    if module == 'vehiculos_libres' and user_can(user, 'vehiculos', 'r'):
        return True
    # Ficha empresa: listado subcontratas o personal (jefe entra desde chip)
    path = request.path or ''
    if module == 'subcontratas' and path.startswith('/admin/company_panel'):
        if user_can(user, 'trabajadores', 'r'):
            return True
    # Quien tiene sync_odoo w puede lanzar cualquier sync de módulo
    if action == 'w' and path.startswith('/sync/api/run/') and user_can(user, 'sync_odoo', 'w'):
        return True
    return False


def _wants_json_response() -> bool:
    """Fetch/XHR/API: no redirigir al panel con HTML."""
    path = request.path or ''
    if path.startswith('/api/'):
        return True
    if request.is_json:
        return True
    ct = (request.content_type or '').lower()
    if 'application/json' in ct:
        return True
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return True
    accept = (request.headers.get('Accept') or '').lower()
    if 'application/json' in accept and 'text/html' not in accept.split(',')[0]:
        return True
    # FormData desde fetch (notas) suele mandar Accept: */*
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE') and 'multipart/form-data' in ct:
        if 'text/html' not in accept.split(',')[0]:
            return True
    return False


def _deny_message(action: str | None = None) -> str:
    if action in ('x', 'w'):
        return 'No tienes permiso de escritura para esta acción.'
    if action == 'r':
        return 'No tienes permiso para ver este módulo.'
    return 'Acceso no autorizado'


def _safe_referrer_redirect():
    ref = request.referrer
    if not ref:
        return None
    try:
        parsed = urlparse(ref)
        if parsed.netloc and parsed.netloc != request.host:
            return None
        if parsed.path.startswith('/auth') or parsed.path in ('/', ''):
            return None
        return ref
    except Exception:
        return None


def _deny(redirect_to='main.dashboard', action=None):
    msg = _deny_message(action)
    if _wants_json_response():
        return jsonify({
            'success': False,
            'error': msg,
            'message': msg,
            'permission_denied': True,
        }), 403
    flash(msg, 'danger')
    try:
        from app.services.impersonation_service import impersonacion_activa
        if impersonacion_activa():
            from app.auth.routes import destino_portal_operario
            return redirect(destino_portal_operario(current_user))
    except Exception:
        pass
    back = _safe_referrer_redirect()
    if back:
        return redirect(back)
    return redirect(url_for(redirect_to))


def enforce_rules(rules, *, redirect_to='main.dashboard', require_auth=True):
    """Devuelve response de redirect/403 si deniega; None si OK / no aplica."""
    if require_auth and not current_user.is_authenticated:
        return None
    if not current_user.is_authenticated:
        return None
    matched = _action_for(rules, request.method)
    if not matched:
        return None
    module, action = matched
    if user_can(current_user, module, action):
        return None
    # Misma lógica OR que path_allows_user (buzón / coches libres / ficha empresa)
    if module == 'solicitudes' and user_can(current_user, 'solicitudes_vehiculos', action):
        return None
    if module == 'vehiculos_libres' and user_can(current_user, 'vehiculos', 'r'):
        return None
    path = request.path or ''
    if module == 'subcontratas' and path.startswith('/admin/company_panel'):
        if user_can(current_user, 'trabajadores', 'r'):
            return None
    return _deny(redirect_to, action=action)


def enforce_admin_permissions():
    return enforce_rules(_ADMIN_RULES)


def enforce_sync_permissions():
    path = request.path or ''
    if path.startswith('/sync/api/run/'):
        if not current_user.is_authenticated:
            return None
        if path_allows_user(current_user):
            return None
        return _deny(action='w')
    return enforce_rules(_SYNC_RULES)


def enforce_notas_permissions():
    from app.services.tenant_modules import has_notas
    if not has_notas():
        flash('Este espacio no tiene el módulo de notas.', 'warning')
        return redirect(url_for('main.dashboard'))
    return enforce_rules(_NOTAS_RULES)


def enforce_jefe_permissions():
    return enforce_rules(_JEFE_RULES)


def enforce_empleado_permissions():
    path = (request.path or '').rstrip('/') or '/'
    if path in ('/fichaje', '/empleado'):
        if any(user_can(current_user, mod, act) for mod, act in _PORTAL_JORNADA_MODULES):
            return None
        return _deny('auth.login', action='r')
    return enforce_rules(_EMPLEADO_RULES, redirect_to='auth.login')


def enforce_auth_permissions():
    return enforce_rules(_AUTH_RULES)
