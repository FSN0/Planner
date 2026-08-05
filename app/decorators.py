from functools import wraps
from flask import flash, redirect, url_for, jsonify, request
from flask_login import current_user

from app.models import ROLE_LABORAL, ROLE_RRHH


def _expand_roles(roles):
    """Si se permite laboral, también RRHH (mismo ACL de momento)."""
    allowed = tuple(roles)
    if ROLE_LABORAL in allowed and ROLE_RRHH not in allowed:
        return allowed + (ROLE_RRHH,)
    return allowed


def roles_required(*roles, redirect_to='main.dashboard'):
    """
    Decorador que verifica que el usuario autenticado tenga al menos uno de los roles permitidos.
    
    Parámetros:
      *roles: Lista de roles permitidos (ej. ROLE_ADMIN, ROLE_RRHH, etc.)
      redirect_to (str, opcional): Nombre del endpoint al que se redirigirá en caso de fallo.
                                    Por defecto se usa 'main.dashboard'.
                                    
    Ejemplo de uso:
      @login_required
      @roles_required(ROLE_ADMIN, redirect_to='admin.panel')
      def panel():
          ...
    """
    allowed = _expand_roles(roles)

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated or current_user.role not in allowed:
                flash("Acceso no autorizado", "danger")
                return redirect(url_for(redirect_to))
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def roles_required_api(*roles):
    """Igual que roles_required pero responde JSON 403 (para /api/*)."""
    allowed = _expand_roles(roles)

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated or current_user.role not in allowed:
                return jsonify({'success': False, 'error': 'Acceso no autorizado'}), 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def api_wants_json():
    """True si la petición espera JSON (fetch/XHR)."""
    if request.path.startswith('/api/'):
        return True
    accept = (request.headers.get('Accept') or '').lower()
    return 'application/json' in accept and 'text/html' not in accept.split(',')[0]
