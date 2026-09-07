"""POST /api/v6/odoo/hooks/changed — avisos de Odoo (sin sesión de usuario)."""
from flask import jsonify, request

from app import csrf, limiter
from app.services.i18n_service import translate
from app.services.odoo_hook_service import OdooHookError, accept_hook


def register_odoo_hook_routes(api_bp):
    @api_bp.route('/odoo/hooks/changed', methods=['POST'])
    @limiter.limit('120 per minute')
    def odoo_hook_changed():
        payload = request.get_json(silent=True)
        if payload is None:
            payload = {}
        try:
            result = accept_hook(request.headers, payload)
        except OdooHookError as err:
            return jsonify({
                'success': False,
                'accepted': False,
                'code': err.code,
                'error': translate(err.message),
            }), err.status
        except Exception:
            from flask import current_app
            current_app.logger.exception('Fallo inesperado en hook Odoo')
            return jsonify({
                'success': False,
                'accepted': False,
                'code': 'server_error',
                'error': translate('No se ha podido encolar el aviso.'),
            }), 500
        return jsonify({'success': True, **result}), 202

    csrf.exempt(odoo_hook_changed)
