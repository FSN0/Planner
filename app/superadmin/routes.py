from flask import render_template, request, redirect, url_for, flash, current_app, Response
from app.superadmin import superadmin_bp
from app.models import Tenant
from app.services.tenant_service import provision_new_tenant
from app.services.config_service import set_tenant_config
from app import db
from sqlalchemy import text

# ==========================================
# CATÁLOGO DE MÓDULOS Y ADAPTADORES
# ==========================================
MODULOS_DISPONIBLES = {
    'odoo': 'Integración Odoo (ERP)',
    'chat': 'Chat de Comunicación (Próximamente)'
}

ADAPTADORES_ODOO = {
    'odoo_soltec': 'Traductor / Adaptador Soltec',
    'odoo_generico': 'Traductor Genérico Estándar'
}

# ==========================================
# PROTECCIÓN DEL PANEL SUPERADMIN (Basic Auth)
# ==========================================
def check_auth(username, password):
    """Comprueba si las credenciales coinciden con la configuración."""
    return username == current_app.config['SUPERADMIN_USER'] and password == current_app.config['SUPERADMIN_PASS']

def authenticate():
    """Envía un error 401 que fuerza al navegador a mostrar el popup de login."""
    return Response(
        'Acceso denegado. Área exclusiva de infraestructura SaaS.\n', 401,
        {'WWW-Authenticate': 'Basic realm="Superadmin Login"'}
    )

@superadmin_bp.before_request
def require_basic_auth():
    """Intercepta todas las peticiones a /superadmin y exige autenticación."""
    auth = request.authorization
    if not auth or not auth.type == 'basic' or not check_auth(auth.username, auth.password):
        return authenticate()

# ==========================================
# RUTAS DE VISTAS
# ==========================================
@superadmin_bp.route('/')
def dashboard():
    # Obtenemos todos los inquilinos (clientes) del esquema public
    tenants = Tenant.query.all()
    # Pasamos también los adaptadores a la vista
    return render_template('superadmin/dashboard.html', 
                           tenants=tenants, 
                           modulos=MODULOS_DISPONIBLES,
                           adaptadores_odoo=ADAPTADORES_ODOO)

@superadmin_bp.route('/create_tenant', methods=['POST'])
def create_tenant():
    nombre = request.form.get('nombre')
    subdominio = request.form.get('subdominio')
    admin_email = request.form.get('admin_email')
    admin_password = request.form.get('admin_password')
    
    if not all([nombre, subdominio, admin_email, admin_password]):
        flash("Faltan datos en el formulario.", "danger")
        return redirect(url_for('superadmin.dashboard'))
        
    try:
        provision_new_tenant(nombre, subdominio, admin_email, admin_password)
        flash(f"Inquilino '{nombre}' creado. El administrador ya puede iniciar sesión.", "success")
    except Exception as e:
        flash(f"Error al crear inquilino: {str(e)}", "danger")
        
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
    
    flash(f"Módulos actualizados correctamente para {tenant.nombre}.", "success")
    return redirect(url_for('superadmin.dashboard'))