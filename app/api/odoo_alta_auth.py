"""Autenticación para la app externa Alta Odoo (mismas credenciales que SignaPlan)."""
from flask import request, jsonify, g, current_app
from sqlalchemy import text
from werkzeug.security import check_password_hash

from app import db, csrf, limiter
from app.models import User, Tenant, ROLE_ADMIN
from app.services.i18n_service import translate
from app import is_safe_schema_name


def register_odoo_alta_auth_routes(api_bp):
    @api_bp.route('/odoo-alta/login', methods=['POST'])
    @limiter.limit('15 per minute')
    def odoo_alta_login():
        shared_key = request.headers.get('X-Odoo-Alta-Key', '')
        expected = current_app.config.get('SSO_SECRET_KEY') or ''
        if not expected or shared_key != expected:
            return jsonify({'success': False, 'error': translate('No autorizado')}), 401

        data = request.get_json(silent=True) or {}
        email = (data.get('email') or '').strip().lower()
        password = data.get('password') or ''
        tenant_slug = (
            (data.get('tenant') or '').strip()
            or (current_app.config.get('ODOO_ALTA_TENANT_SLUG') or '').strip()
        )

        if not email or not password:
            return jsonify({'success': False, 'error': translate('Email y contraseña obligatorios')}), 400
        if not tenant_slug:
            return jsonify({'success': False, 'error': translate('Tenant no configurado')}), 400

        tenant = Tenant.query.filter_by(subdominio=tenant_slug, is_active=True).first()
        if not tenant:
            return jsonify({'success': False, 'error': translate('Empresa no encontrada')}), 404
        if not is_safe_schema_name(tenant.schema_name):
            return jsonify({'success': False, 'error': translate('Configuración de tenant inválida')}), 500

        g.current_tenant = tenant
        db.session.execute(text(f'SET search_path TO {tenant.schema_name}, public'))

        modulos = tenant.modulos_activos or {}
        if not modulos.get('odoo_alta'):
            return jsonify({'success': False, 'error': translate('Módulo Alta Odoo no activo para esta empresa')}), 403

        user = User.query.filter_by(email=email).first()
        if not user or not check_password_hash(user.password_hash, password):
            return jsonify({'success': False, 'error': translate('Credenciales inválidas')}), 401

        from app.services.permission_service import user_can

        if not user_can(user, 'soltec_alta_odoo', 'r'):
            return jsonify({'success': False, 'error': translate('Tu perfil no tiene acceso a Alta Odoo')}), 403

        if not user.is_active:
            return jsonify({'success': False, 'error': translate('Tu cuenta no está activa')}), 403

        u_name = user.name if user.name and str(user.name).lower() != 'none' else ''
        u_last = user.lastname if user.lastname and str(user.lastname).lower() != 'none' else ''
        full_name = f'{u_name} {u_last}'.strip() or user.email
        external_ids = user.external_ids if isinstance(user.external_ids, dict) else {}
        alta_as_admin = (
            user.role == ROLE_ADMIN
            or user_can(user, 'soltec_alta_odoo_admin', 'r')
        )

        return jsonify({
            'success': True,
            'user': {
                'id': user.id,
                'name': full_name,
                'email': user.email,
                'role': user.role,
                'odoo_id': external_ids.get('odoo'),
                'is_admin': bool(alta_as_admin),
            },
        })

    csrf.exempt(odoo_alta_login)
