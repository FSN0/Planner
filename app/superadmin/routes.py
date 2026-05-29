from flask import render_template, request, redirect, url_for, flash
from app.superadmin import superadmin_bp
from app.models import Tenant
from app.services.tenant_service import provision_new_tenant

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