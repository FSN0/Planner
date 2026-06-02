from flask import render_template, request, redirect, url_for, flash, current_app, Response
from app.superadmin import superadmin_bp
from app.models import Tenant
from app.services.tenant_service import provision_new_tenant

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


# ... (El resto de tus rutas create_tenant, etc. se quedan igual) ...
# NOTA: En un futuro cercano protegeremos esta ruta con un login específico para ti.
# Por ahora, la dejamos abierta para poder crear los primeros clientes.
@superadmin_bp.route('/')
def dashboard():
    # Obtenemos todos los inquilinos (clientes) del esquema public
    tenants = Tenant.query.all()
    return render_template('superadmin/dashboard.html', tenants=tenants)

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