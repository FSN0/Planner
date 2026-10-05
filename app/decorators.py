from functools import wraps
from flask import jsonify, request
from flask_login import current_user

from app.models import ROLE_LABORAL, ROLE_RRHH
from app.services.permission_service import user_can


def _expand_roles(roles):
    """Si se permite laboral, también RRHH (mismo ACL de momento)."""
    allowed = tuple(roles)
    if ROLE_LABORAL in allowed and ROLE_RRHH not in allowed:
        return allowed + (ROLE_RRHH,)
    return allowed


def roles_required(*roles, redirect_to='main.dashboard'):
    """
    Verifica rol hardcodeado O permiso de matriz sobre la ruta actual.

    Si el rol no está en la lista pero la ruta está mapeada en permission_guard
    y user_can(...) lo permite, deja pasar. Así Configuración → Permisos
    puede ampliar accesos sin reescribir cada decorador.
    """
    allowed = _expand_roles(roles)

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            from app.services.permission_guard import _deny, path_allows_user

            if not current_user.is_authenticated:
                return _deny(redirect_to, action='r')
            if current_user.role in allowed:
                return f(*args, **kwargs)
            if path_allows_user(current_user):
                return f(*args, **kwargs)
            return _deny(redirect_to, action='r')
        return decorated_function
    return decorator


def permission_required(module, action='r', redirect_to='main.dashboard'):
    """Acceso según matriz de permisos del tenant (RolePermission)."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            from app.services.permission_guard import _deny
            if not current_user.is_authenticated or not user_can(current_user, module, action):
                return _deny(redirect_to, action=action)
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def roles_required_api(*roles):
    """Igual que roles_required pero responde JSON 403 (para /api/*)."""
    allowed = _expand_roles(roles)

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return jsonify({'success': False, 'error': 'Acceso no autorizado', 'permission_denied': True}), 403
            if current_user.role in allowed:
                return f(*args, **kwargs)
            from app.services.permission_guard import path_allows_user
            if path_allows_user(current_user):
                return f(*args, **kwargs)
            return jsonify({'success': False, 'error': 'Acceso no autorizado', 'permission_denied': True}), 403
        return decorated_function
    return decorator


def permission_required_api(module, action='r'):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated or not user_can(current_user, module, action):
                return jsonify({
                    'success': False,
                    'error': 'Acceso no autorizado',
                    'permission_denied': True,
                }), 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def api_wants_json():
    """True si la petición espera JSON (fetch/XHR)."""
    if request.path.startswith('/api/'):
        return True
    accept = (request.headers.get('Accept') or '').lower()
    return 'application/json' in accept and 'text/html' not in accept.split(',')[0]
