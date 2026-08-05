# app/empleado/__init__.py
from flask import Blueprint

empleado_bp = Blueprint('empleado', __name__, url_prefix='/empleado')

from app.empleado import routes as _routes  # noqa: E402,F401

__all__ = ['empleado_bp']
