from flask import Blueprint

# Creamos el Blueprint para el panel maestro del SaaS
superadmin_bp = Blueprint('superadmin', __name__, url_prefix='/superadmin')

from . import routes