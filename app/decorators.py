from functools import wraps
from flask import flash, redirect, url_for
from flask_login import current_user

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
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated or current_user.role not in roles:
                flash("Acceso no autorizado", "danger")
                return redirect(url_for(redirect_to))
            return f(*args, **kwargs)
        return decorated_function
    return decorator
