from flask import Blueprint

subcontrata_bp = Blueprint('subcontrata', __name__, url_prefix='/subcontrata')

from app.subcontrata import routes as _routes  # noqa: E402,F401
