import hmac
from flask import render_template, request, redirect, url_for, flash, current_app, Response
from app.superadmin import superadmin_bp
from app.models import Tenant
from app.services.tenant_service import provision_new_tenant
from app.services.tenant_domain_service import validate_custom_domain, assert_custom_domain_available
from app.services.config_service import set_tenant_config
from app import db, csrf
from sqlalchemy import text

# ==========================================
# CATÁLOGO DE MÓDULOS Y ADAPTADORES
# ==========================================
MODULOS_DISPONIBLES = {
    'fichaje_operario': 'Fichaje móvil del trabajador',
    'registro_jornada': 'Registro de jornada / Inspección',
    'onboarding': 'Onboarding de primeros pasos',
    'odoo': 'Integración Odoo (ERP / Sincronización)',
    'odoo_alta': 'Alta Odoo (Fichajes Soltec / SSO)',
    # Personalizaciones por cliente (no producto genérico)
    'avisos_laborales': 'Avisos laborales en Logs (click acusar Planificación/Solicitud)',
}

# Solo adaptadores realmente implementados en app/sync/adapters/.
# Integraciones ERP a medida para otros clientes: proyecto bajo demanda (ver landing).
ADAPTADORES_ODOO = {
    'odoo_soltec': 'Traductor / Adaptador Soltec',
}

# ==========================================
# PROTECCIÓN DEL PANEL SUPERADMIN (Basic Auth)
# ==========================================
def check_auth(username, password):
    """Comprueba si las credenciales coinciden con la configuración.

    Si SUPERADMIN_USER/SUPERADMIN_PASS no están configuradas, el acceso queda
    bloqueado (devuelve False). Se usa compare_digest para evitar ataques de tiempo.
    """
    cfg_user = current_app.config.get('SUPERADMIN_USER')
    cfg_pass = current_app.config.get('SUPERADMIN_PASS')
    if not cfg_user or not cfg_pass:
        return False
    user_ok = hmac.compare_digest(str(username or ''), str(cfg_user))
    pass_ok = hmac.compare_digest(str(password or ''), str(cfg_pass))
    return user_ok and pass_ok

def authenticate():
    """Envía un error 401 que fuerza al navegador a mostrar el popup de login."""
    return Response(
        'Acceso denegado. Área exclusiva de infraestructura SaaS.\n', 401,
        {'WWW-Authenticate': 'Basic realm="Superadmin Login"'}
    )

@superadmin_bp.before_request
def require_basic_auth():
    """Intercepta todas las peticiones a /superadmin y exige autenticación.

    Solo en hosts de marketing / apex (no en subdominios de cliente), para
    reducir superficie de ataque del panel de control.
    """
    from app.services.tenant_domain_service import is_marketing_host, normalize_host
    host = normalize_host(request.host)
    # Permitir también localhost / IP en desarrollo
    es_ip = bool(host) and all(p.isdigit() for p in host.split('.')) and host.count('.') == 3
    if not (
        is_marketing_host(host)
        or host in ('localhost', '127.0.0.1', 'web')
        or es_ip
        or host.endswith('.localhost')
    ):
        return Response('No encontrado.\n', 404)

    auth = request.authorization
    if not auth or not auth.type == 'basic' or not check_auth(auth.username, auth.password):
        return authenticate()

# ==========================================
# RUTAS DE VISTAS
# ==========================================
@superadmin_bp.route('/')
def dashboard():
    from app.services.superadmin_ops_service import (
        DIAS_PURGA_TRAS_DESACTIVAR,
        dias_para_purga,
        enrich_tenants,
    )
    tenants = Tenant.query.order_by(Tenant.created_at.desc()).all()
    rows = enrich_tenants(tenants)
    for row in rows:
        row['dias_purga'] = dias_para_purga(row['tenant'])
    return render_template(
        'superadmin/dashboard.html',
        tenant_rows=rows,
        tenants=tenants,
        modulos=MODULOS_DISPONIBLES,
        adaptadores_odoo=ADAPTADORES_ODOO,
        dias_purga=DIAS_PURGA_TRAS_DESACTIVAR,
    )


@superadmin_bp.route('/tenant/<int:id_tenant>/desactivar', methods=['POST'])
def desactivar_tenant(id_tenant):
    from app.services.superadmin_ops_service import desactivar_tenant as _off
    tenant = Tenant.query.get_or_404(id_tenant)
    try:
        _off(tenant)
        flash(f'{tenant.nombre} desactivado. Ya no es accesible por su URL.', 'warning')
    except Exception as e:
        flash(str(e), 'danger')
    return redirect(url_for('superadmin.dashboard'))


@superadmin_bp.route('/tenant/<int:id_tenant>/reactivar', methods=['POST'])
def reactivar_tenant(id_tenant):
    from app.services.superadmin_ops_service import reactivar_tenant as _on
    tenant = Tenant.query.get_or_404(id_tenant)
    try:
        _on(tenant)
        flash(f'{tenant.nombre} reactivado.', 'success')
    except Exception as e:
        flash(str(e), 'danger')
    return redirect(url_for('superadmin.dashboard'))


@superadmin_bp.route('/tenant/<int:id_tenant>/purgar', methods=['POST'])
def purgar_tenant(id_tenant):
    from app.services.superadmin_ops_service import purgar_tenant as _purge
    tenant = Tenant.query.get_or_404(id_tenant)
    nombre = tenant.nombre
    try:
        _purge(tenant, request.form.get('confirm_subdominio'))
        flash(f'Tenant {nombre} eliminado definitivamente.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(str(e), 'danger')
    return redirect(url_for('superadmin.dashboard'))


@superadmin_bp.route('/tenant/<int:id_tenant>/impersonar', methods=['POST'])
def impersonar_tenant(id_tenant):
    from urllib.parse import quote
    from app.services.signup_service import url_acceso_tenant
    from app.services.superadmin_ops_service import crear_token_impersonacion

    tenant = Tenant.query.get_or_404(id_tenant)
    try:
        token = crear_token_impersonacion(tenant)
        url = url_acceso_tenant(
            tenant, path=f'/auth/impersonate?t={quote(token, safe="")}'
        )
        return redirect(url)
    except Exception as e:
        flash(str(e), 'danger')
        return redirect(url_for('superadmin.dashboard'))

@superadmin_bp.route('/create_tenant', methods=['POST'])
def create_tenant():
    nombre = request.form.get('nombre')
    subdominio = request.form.get('subdominio')
    admin_email = request.form.get('admin_email')
    admin_password = request.form.get('admin_password')
    custom_domain_raw = request.form.get('custom_domain')
    
    if not all([nombre, subdominio, admin_email, admin_password]):
        flash("Faltan datos en el formulario.", "danger")
        return redirect(url_for('superadmin.dashboard'))
        
    try:
        custom_domain = validate_custom_domain(custom_domain_raw)
        assert_custom_domain_available(custom_domain)
        provision_new_tenant(
            nombre,
            subdominio,
            admin_email,
            admin_password,
            custom_domain=custom_domain,
            modulos_activos={
                'fichaje_operario': False,
                'registro_jornada': True,
                'onboarding': False,
            },
        )
        flash(f"Inquilino '{nombre}' creado. El administrador ya puede iniciar sesión.", "success")
    except Exception as e:
        flash(f"Error al crear inquilino: {str(e)}", "danger")
        
    return redirect(url_for('superadmin.dashboard'))

@superadmin_bp.route('/tenant/<int:id_tenant>/dominio', methods=['POST'])
def configurar_dominio_tenant(id_tenant):
    tenant = Tenant.query.get_or_404(id_tenant)
    custom_domain_raw = request.form.get('custom_domain')

    try:
        custom_domain = validate_custom_domain(custom_domain_raw)
        assert_custom_domain_available(custom_domain, tenant_id=tenant.id)
        tenant.custom_domain = custom_domain
        db.session.commit()
        if custom_domain:
            flash(
                f"Dominio propio actualizado para {tenant.nombre}: {custom_domain}",
                "success",
            )
        else:
            flash(
                f"Dominio propio eliminado para {tenant.nombre}. "
                f"Acceso por subdominio: {tenant.subdominio}.signaplan.com",
                "success",
            )
    except Exception as e:
        db.session.rollback()
        flash(f"Error al actualizar dominio: {str(e)}", "danger")

    return redirect(url_for('superadmin.dashboard'))

@superadmin_bp.route('/tenant/<int:id_tenant>/configurar_modulos', methods=['POST'])
def configurar_modulos_tenant(id_tenant):
    tenant = Tenant.query.get_or_404(id_tenant)
    
    # Recogemos la lista de checkboxes marcados
    modulos_marcados = request.form.getlist('modulos')
    odoo_adapter = request.form.get('odoo_adapter') # Recogemos el traductor elegido
    
    # Construimos el JSON dinámicamente
    estado_modulos = {}
    for key in MODULOS_DISPONIBLES.keys():
        estado_modulos[key] = (key in modulos_marcados)
        
    # Si Odoo está activo, guardamos el adaptador en el JSON
    if estado_modulos.get('odoo'):
        estado_modulos['odoo_adapter'] = odoo_adapter
    else:
        estado_modulos['odoo_adapter'] = None
        
    tenant.modulos_activos = estado_modulos
    db.session.commit()

    db.session.execute(text(f"SET search_path TO {tenant.schema_name}"))
    if estado_modulos.get('odoo') and odoo_adapter:
        set_tenant_config('motor_sincronizacion', odoo_adapter)
    else:
        set_tenant_config('motor_sincronizacion', 'fichajes_locales')
    db.session.execute(text("SET search_path TO public"))
    
    flash(f"Módulos actualizados correctamente para {tenant.nombre}.", "success")
    return redirect(url_for('superadmin.dashboard'))


@superadmin_bp.route('/tenant/<int:id_tenant>/plan', methods=['POST'])
def configurar_plan_tenant(id_tenant):
    from app.services.plan_service import PLANES, asignar_plan

    tenant = Tenant.query.get_or_404(id_tenant)
    plan = request.form.get('plan')
    limite_raw = request.form.get('limite_empleados')
    try:
        limite = None
        if limite_raw is not None and str(limite_raw).strip() != '':
            limite = int(limite_raw)
            if limite < 1:
                raise ValueError('El límite tiene que ser al menos 1.')
        if plan not in PLANES:
            raise ValueError('Plan no válido.')
        asignar_plan(tenant, plan, limite=limite, billing_exempt=bool(request.form.get('billing_exempt')))
        db.session.commit()
        flash(f"Plan de {tenant.nombre} actualizado a '{plan}'.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error al actualizar el plan: {e}", "danger")
    return redirect(url_for('superadmin.dashboard'))
