from flask import Blueprint

compliance_bp = Blueprint('compliance', __name__, url_prefix='/admin')

from app.compliance import routes as _routes  # noqa: E402,F401
