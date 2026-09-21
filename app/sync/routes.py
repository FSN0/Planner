import secrets
import xmlrpc.client

from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, g
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
from datetime import datetime, timedelta
from sqlalchemy import or_
from sqlalchemy.orm import joinedload, selectinload

from app import db
from app.models import Obra, User, Company, SyncLog, Asignacion, RegistroFichaje, RegistroOdometro, ROLE_ADMIN, ROLE_LABORAL, ROLE_RRHH
from app.services.core_assignment_service import CoreAssignmentService
from app.services.sync_dashboard_service import get_sync_panel_context, test_odoo_connection
from app.services.sync_config_service import SyncConfigService
from app.services.config_service import set_tenant_config, get_tenant_config
from app.sync.dispatcher import get_sync_adapter
from app.decorators import roles_required
from app.services.permission_service import can_resolve_fichajes, is_laboral, laboral_auditoria_sections
from app.services.i18n_service import translate

sync_bp = Blueprint('sync', __name__, url_prefix='/sync')

# Eager-load para auditoría: sin esto, ~2000 filas × 3 relaciones = miles de queries
# y el worker/Caddy cortan → «Esta página no funciona» a la primera (al recargar ya va).
_AUDITORIA_EAGER = (
    selectinload(RegistroFichaje.user),
    selectinload(RegistroFichaje.obra_planificada),
    selectinload(RegistroFichaje.obra_real),
    selectinload(RegistroFichaje.resuelto_por),
)
_AUDITORIA_PENDIENTES_LIMIT = 500
_AUDITORIA_HISTORIAL_LIMIT = 300
_AUDITORIA_CORRECCIONES_LIMIT = 150

# Módulo de escritura requerido por cada tarea «Auto ahora» / sync manual.
_SYNC_TASK_WRITE_MODULE = {
    'obras': 'directorio',
    'empleados': 'trabajadores',
    'subcontratas': 'subcontratas',
    'ausencias': 'ausencias',
    'fichajes': 'auditoria_fichajes',
    'fichajes-retro': 'auditoria_fichajes',
    'vehiculos': 'auditoria_vehiculos',
    'vehiculos-retro': 'auditoria_vehiculos',
}


def _user_can_sync_task(task_name):
    from app.services.permission_service import user_can
    module = _SYNC_TASK_WRITE_MODULE.get(task_name)
    if not module:
        return False
    return user_can(current_user, module, 'w') or user_can(current_user, 'sync_odoo', 'w')


def _require_module_write(module):
    from app.services.permission_service import user_can
    if user_can(current_user, module, 'w') or user_can(current_user, 'sync_odoo', 'w'):
        return None
    return jsonify({'success': False, 'error': translate('No autorizado')}), 403


@sync_bp.before_request
def _enforce_sync_module_permissions():
    from app.services.permission_guard import enforce_sync_permissions
    return enforce_sync_permissions()


def _company_by_odoo_id(odoo_c_id):
    if not odoo_c_id:
        return None
    return Company.query.filter(Company.external_ids['odoo'].astext == str(odoo_c_id)).first()


def _tenant_modulos():
    return getattr(g.current_tenant, 'modulos_activos', {}) or {}


def _tenant_has_integrations():
    """True si el tenant tiene al menos un módulo de integración contratado."""
    modulos = _tenant_modulos()
    return bool(modulos.get('odoo') or modulos.get('odoo_alta'))


def _require_odoo_module():
    if not _tenant_modulos().get('odoo'):
        return False
    return True


def _render_preview(modulo, template, diff, preview, *, extra=None):
    """Renderiza preview y persiste pendientes si los hay."""
    extra = extra or {}
    try:
        from app.services.sync_preview_cache_service import save_cache
        save_cache(modulo, preview, diff, source=extra.get('cache_source', 'manual'))
    except Exception:
        pass
    return render_template(
        template,
        diff=diff,
        preview=preview,
        from_cache=False,
        **extra,
    )


def _render_cached_preview(modulo, template, *, extra=None):
    from app.services.sync_preview_cache_service import load_cache, format_saved_at
    cached = load_cache(modulo)
    if not cached:
        flash(translate('No hay pendientes guardados para este módulo. Ejecuta un preview manual.'), 'warning')
        return redirect(url_for('sync.odoo_panel'))
    extra = extra or {}
    return render_template(
        template,
        diff=cached.get('diff') or {},
        preview=cached.get('preview') or {},
        from_cache=True,
        cache_saved_at=format_saved_at(cached.get('saved_at')),
        cache_source=cached.get('source') or 'manual',
        **extra,
    )


def _clear_preview_cache(modulo):
    try:
        from app.services.sync_preview_cache_service import clear_cache
        clear_cache(modulo)
    except Exception:
        pass


def _require_auditoria_vehiculos():
    from app.services.tenant_modules import has_auditoria_vehiculos
    return bool(_tenant_modulos().get('odoo') and has_auditoria_vehiculos())


def _require_integration_access():
    if not _tenant_has_integrations():
        return False
    return True


@sync_bp.route('/')
@login_required
@roles_required(ROLE_ADMIN)
def panel():
    """Hub de integraciones: módulos activos o página de contacto si no hay ninguno."""
    modulos_activos = _tenant_modulos()
    return render_template(
        'sync/integrations_hub.html',
        modulos_activos=modulos_activos,
        tenant_has_integrations=_tenant_has_integrations(),
    )


@sync_bp.route('/odoo')
@login_required
@roles_required(ROLE_ADMIN)
def odoo_panel():
    """Centro de sincronización Odoo (dashboard operativo, solo si módulo contratado)."""
    if not _require_odoo_module():
        return redirect(url_for('admin.panel'))
    ctx = get_sync_panel_context()
    has_password = bool(get_tenant_config('odoo_password', default=''))
    ctx['odoo_credentials'] = {
        'url': get_tenant_config('odoo_url', default=''),
        'db': get_tenant_config('odoo_db', default=''),
        'user': get_tenant_config('odoo_user', default=''),
        'password': '',
        'has_password': has_password,
        'external_auth_provider': get_tenant_config('external_auth_provider', default=''),
        'external_auth_odoo_url': get_tenant_config(
            'external_auth_odoo_url',
            default=get_tenant_config('odoo_url', default=''),
        ),
        'soltec_sso_enabled': get_tenant_config('soltec_sso_enabled', default='false'),
        'soltec_sso_issuer': get_tenant_config('soltec_sso_issuer', default='soltec_satellite'),
        'soltec_sso_portal_url': get_tenant_config(
            'soltec_sso_portal_url',
            default='https://portal-soltecgrupo.vercel.app',
        ),
        'soltec_sso_has_secret': bool(
            get_tenant_config('soltec_sso_shared_secret', default='')
        ),
    }
    from app.services.odoo_hook_service import hook_dashboard_context
    ctx['odoo_hook'] = hook_dashboard_context()
    return render_template('sync/odoo_dashboard.html', **ctx)


@sync_bp.route('/odoo/hook-key', methods=['POST'])
@login_required
@roles_required(ROLE_ADMIN)
def odoo_rotate_hook_key():
    if not _require_odoo_module():
        return redirect(url_for('sync.panel'))
    from app.services.odoo_hook_service import rotate_hook_key
    rotate_hook_key()
    flash(
        translate('Nueva clave de avisos Odoo. La anterior deja de valer; actualízala en Odoo.'),
        'success',
    )
    return redirect(url_for('sync.odoo_panel'))


@sync_bp.route('/odoo/save_config', methods=['POST'])
@login_required
@roles_required(ROLE_ADMIN)
def odoo_save_config():
    if not _require_odoo_module():
        return redirect(url_for('sync.panel'))
    try:
        url = (request.form.get('url') or '').strip()
        db_name = (request.form.get('db') or '').strip()
        user = (request.form.get('user') or '').strip()
        password = (request.form.get('password') or '').strip()

        # No pisar con vacío: evita el error intermitente "No hay ODOO_URL"
        if url:
            set_tenant_config('odoo_url', url)
        if db_name:
            set_tenant_config('odoo_db', db_name)
        if user:
            set_tenant_config('odoo_user', user)
        if password:
            set_tenant_config('odoo_password', password, encriptar=True)
        external_auth_provider = (request.form.get('external_auth_provider') or '').strip()
        external_auth_odoo_url = (request.form.get('external_auth_odoo_url') or '').strip()
        set_tenant_config('external_auth_provider', external_auth_provider)
        if external_auth_odoo_url:
            set_tenant_config('external_auth_odoo_url', external_auth_odoo_url)
        elif url:
            set_tenant_config('external_auth_odoo_url', url)
        set_tenant_config(
            'soltec_sso_enabled',
            'true' if request.form.get('soltec_sso_enabled') == 'on' else 'false',
        )
        soltec_sso_issuer = (request.form.get('soltec_sso_issuer') or '').strip() or 'soltec_satellite'
        set_tenant_config('soltec_sso_issuer', soltec_sso_issuer)
        soltec_sso_secret = (request.form.get('soltec_sso_shared_secret') or '').strip()
        if soltec_sso_secret:
            set_tenant_config('soltec_sso_shared_secret', soltec_sso_secret, encriptar=True)
        portal_url = (request.form.get('soltec_sso_portal_url') or '').strip().rstrip('/')
        if portal_url:
            set_tenant_config('soltec_sso_portal_url', portal_url)

        modulos = getattr(g.current_tenant, 'modulos_activos', {}) or {}
        motor = modulos.get('odoo_adapter') or 'odoo_soltec'
        set_tenant_config('motor_sincronizacion', motor)

        flash("Credenciales de Odoo guardadas de forma segura.", "success")
    except Exception as e:
        flash(f"Error al guardar credenciales: {str(e)}", "danger")
    return redirect(url_for('sync.odoo_panel'))


@sync_bp.route('/odoo/test_connection', methods=['POST'])
@login_required
@roles_required(ROLE_ADMIN)
def odoo_test_connection():
    if current_user.role != 'admin':
        return jsonify({'success': False, 'error': translate('No autorizado')}), 403
    result = test_odoo_connection()
    return jsonify({
        'success': result['connected'],
        'message': result['message'],
        'error': None if result['connected'] else result['message'],
    })


@sync_bp.route('/api/test-connection', methods=['POST'])
@login_required
@roles_required(ROLE_ADMIN)
def api_test_connection():
    return jsonify(test_odoo_connection())


@sync_bp.route('/api/config', methods=['POST'])
@login_required
@roles_required(ROLE_ADMIN)
def api_save_config():
    data = request.get_json() or {}
    try:
        SyncConfigService.save_config(data)
        return jsonify({'success': True, 'message': translate('Configuración guardada.')})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 400


@sync_bp.route('/api/run/<task_name>', methods=['POST'])
@login_required
def api_run_sync(task_name):
    labels = {
        'obras': 'obras',
        'empleados': 'empleados internos',
        'subcontratas': 'subcontratas',
        'ausencias': 'ausencias / time off',
        'fichajes': 'fichajes del día',
        'fichajes-retro': 'fichajes retrospectivos',
        'vehiculos': 'vehículos / flota (en vivo)',
        'vehiculos-retro': 'vehículos retrospectivos',
    }
    if task_name not in labels:
        return jsonify({'success': False, 'message': translate('Módulo desconocido')}), 400
    if not _user_can_sync_task(task_name):
        return jsonify({'success': False, 'message': translate('No autorizado')}), 403
    try:
        from app.celery_worker import (
            auto_sync_obras, auto_sync_empleados, auto_sync_subcontratas,
            auto_sync_ausencias,
            fichajes_en_vivo, fichajes_retroactivos,
            vehiculos_en_vivo, vehiculos_retroactivos,
        )
        tasks = {
            'obras': auto_sync_obras,
            'empleados': auto_sync_empleados,
            'subcontratas': auto_sync_subcontratas,
            'ausencias': auto_sync_ausencias,
            'fichajes': fichajes_en_vivo,
            'fichajes-retro': fichajes_retroactivos,
            'vehiculos': vehiculos_en_vivo,
            'vehiculos-retro': vehiculos_retroactivos,
        }
        tasks[task_name].delay()
        return jsonify({
            'success': True,
            'message': translate(
                'Sincronización automática de {modulo} lanzada en segundo plano.',
                modulo=translate(labels[task_name]),
            ),
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@sync_bp.route('/api/sync-log/<int:log_id>/visto', methods=['POST'])
@login_required
@roles_required(ROLE_ADMIN, ROLE_LABORAL, ROLE_RRHH)
def api_sync_log_visto(log_id):
    from app.services.permission_service import user_can
    from app.services.sync_dashboard_service import marcar_sync_log_visto
    if not user_can(current_user, 'sync_odoo', 'r'):
        return jsonify({'success': False, 'error': translate('Sin permiso')}), 403
    log = marcar_sync_log_visto(log_id)
    if not log:
        return jsonify({'success': False, 'error': translate('Registro no encontrado')}), 404
    try:
        db.session.commit()
        return jsonify({'success': True, 'id': log.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@sync_bp.route('/api/sync-log/visto-todos', methods=['POST'])
@login_required
@roles_required(ROLE_ADMIN, ROLE_LABORAL, ROLE_RRHH)
def api_sync_log_visto_todos():
    from app.services.permission_service import user_can
    from app.services.sync_dashboard_service import marcar_alertas_sync_vistas
    if not user_can(current_user, 'sync_odoo', 'r'):
        return jsonify({'success': False, 'error': translate('Sin permiso')}), 403
    try:
        marcar_alertas_sync_vistas()
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@sync_bp.route('/resolve_conflict_empleado', methods=['POST'])
@login_required
@roles_required(ROLE_ADMIN)
def resolve_conflict_empleado():
    data = request.json
    emp_data = data['emp']
    action = data['action']
    from app.services.user_role_sync_service import apply_odoo_role_if_allowed
    
    try:
        actual_user = User.query.get(emp_data['conflicto']['actual']['id'])
        blocker_user = User.query.get(emp_data['conflicto']['bloqueador']['id'])
        
        # Función auxiliar para retirar al perdedor
        def retirar_usuario(u):
            u.active = False
            u.is_deleted = True
            u.deactivation_reason = 'deleted'
            from app.utils.timezone_utils import utc_now
            u.deactivated_at = utc_now()
            u.deactivated_by_id = current_user.id if current_user.is_authenticated else None
            u.dni = f"DEL-{u.id}"
            if u.email:
                u.email = f"del-{u.id}@borrado.local"
            if u.external_ids and 'odoo' in u.external_ids:
                u.external_ids = {k: v for k, v in u.external_ids.items() if k != 'odoo'}
                db.session.add(u)

        if action == 'keep_actual':
            retirar_usuario(blocker_user)
            db.session.flush()

            actual_user.external_ids = actual_user.external_ids or {}
            actual_user.external_ids['odoo'] = str(emp_data['odoo_id'])
            actual_user.name = emp_data['name']
            actual_user.lastname = emp_data['lastname']
            actual_user.dni = emp_data['dni']
            actual_user.email = emp_data['email']
            apply_odoo_role_if_allowed(actual_user, emp_data['role'])
            db.session.add(actual_user)

        elif action == 'keep_blocker':
            retirar_usuario(actual_user)
            db.session.flush()

            blocker_user.external_ids = blocker_user.external_ids or {}
            blocker_user.external_ids['odoo'] = str(emp_data['odoo_id'])
            blocker_user.name = emp_data['name']
            blocker_user.lastname = emp_data['lastname']
            blocker_user.dni = emp_data['dni']
            blocker_user.email = emp_data['email']
            apply_odoo_role_if_allowed(blocker_user, emp_data['role'])
            db.session.add(blocker_user)
            
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    
@sync_bp.route('/preview_obras', methods=['GET'])
@login_required
@roles_required(ROLE_ADMIN)
def preview_obras():
    if not _require_odoo_module():
        return redirect(url_for('admin.panel'))
    try:
        from app.services.sync_preview_service import analyze_obras_preview
        jefes_locales = User.query.filter(User.role.in_(['jefe_obra', 'admin'])).all()
        encargados_locales = User.query.filter_by(active=True).all()
        extra = {'jefes': jefes_locales, 'encargados': encargados_locales}
        if request.args.get('cached') == '1':
            return _render_cached_preview('obras', 'sync/preview_obras.html', extra=extra)
        service = get_sync_adapter()
        diff = service.get_diff_obras()
        preview = analyze_obras_preview(diff)
        return _render_preview('obras', 'sync/preview_obras.html', diff, preview, extra=extra)
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception('Fallo al previsualizar obras Odoo')
        flash(f"Error Odoo: {str(e)}", "danger")
        return redirect(url_for('sync.odoo_panel'))

@sync_bp.route('/commit_obras', methods=['POST'])
@login_required
@roles_required(ROLE_ADMIN)
def commit_obras():
    data = request.json
    from app.utils.timezone_utils import utc_now
    ahora = utc_now()
    
    try:
        # 1. Procesar Nuevas
        for obj in data.get('nuevas', []):
            fecha = datetime.strptime(obj['fecha_inicio'], "%Y-%m-%d").date() if obj.get('fecha_inicio') else None
            
            nueva_obra = Obra(
                external_ids={'odoo': str(obj['odoo_id'])},
                codigo=obj['codigo'],
                nombre=obj['nombre'],
                descripcion=obj.get('cliente', ''),
                fecha_inicio=fecha,
                estado='Pendiente', 
                jefe_obra_id=obj.get('jefe_obra_id'),
                encargado_id=obj.get('encargado_id'),
                fecha_importacion=ahora  # <--- GUARDAMOS LA FECHA AQUÍ
            )
            db.session.add(nueva_obra)
            from app.utils import register_log
            register_log(
                user_id=current_user.id,
                category='obras',
                action='Crear Obra (Sincronización)',
                detail=f"Obra importada desde Odoo: '{obj['nombre']}' (Código: {obj['codigo']})"
            )
            
        # 2. Procesar Actualizadas
        for obj in data.get('actualizadas', []):
            obra = Obra.query.get(obj['local_id'])
            if obra:
                ext_ids = dict(obra.external_ids or {})
                ext_ids['odoo'] = str(obj['odoo_id'])
                obra.external_ids = ext_ids
                obra.codigo = obj['codigo']
                obra.nombre = obj['nombre']
                obra.descripcion = obj.get('cliente', '')
                obra.fecha_importacion = ahora
                db.session.add(obra)
                if obj.get('fecha_inicio'):
                    obra.fecha_inicio = datetime.strptime(obj['fecha_inicio'], "%Y-%m-%d").date()
                if obj.get('jefe_obra_id'):
                    obra.jefe_obra_id = obj['jefe_obra_id']
                if obj.get('encargado_id'):
                    obra.encargado_id = obj['encargado_id']
                    
        # 3. Procesar Finalizadas automáticamente
        for obj in data.get('finalizadas', []):
            obra = Obra.query.get(obj['local_id'])
            if obra:
                obra.estado = 'Finalizada'
                obra.fecha_fin = ahora.date() 
                obra.fecha_importacion = ahora
                from app.utils import register_log
                register_log(
                    user_id=current_user.id,
                    category='obras',
                    action='Finalizar Obra (Sincronización)',
                    detail=f"Obra marcada como Finalizada automáticamente por Odoo: '{obra.nombre}'"
                )
                
        # --- AÑADIR REGISTRO DE HISTORIAL ---
        db.session.add(SyncLog(
            fecha=ahora,
            tipo='Obras',
            modo='Manual',
            nuevos=len(data.get('nuevas', [])),
            actualizados=len(data.get('actualizadas', [])),
            finalizados=len(data.get('finalizadas', [])),
            errores=data.get('errores', 0),
            detalles="Sincronización manual de obras completada."
        ))
                
        db.session.commit()
        _clear_preview_cache('obras')
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@sync_bp.route('/preview_empleados', methods=['GET'])
@login_required
@roles_required(ROLE_ADMIN)
def preview_empleados():
    if not _require_odoo_module():
        return redirect(url_for('admin.panel'))
    try:
        from app.services.sync_preview_service import analyze_empleados_preview
        if request.args.get('cached') == '1':
            return _render_cached_preview('empleados', 'sync/preview_empleados.html')
        service = get_sync_adapter()
        diff = service.get_diff_empleados()
        preview = analyze_empleados_preview(diff)
        return _render_preview('empleados', 'sync/preview_empleados.html', diff, preview)
    except Exception as e:
        flash(f"Error Odoo: {str(e)}", "danger")
        return redirect(url_for('sync.odoo_panel'))

@sync_bp.route('/preview_subcontratas', methods=['GET'])
@login_required
@roles_required(ROLE_ADMIN)
def preview_subcontratas():
    if not _require_odoo_module():
        return redirect(url_for('admin.panel'))
    try:
        from app.services.sync_preview_service import analyze_subcontratas_preview
        if request.args.get('cached') == '1':
            return _render_cached_preview('subcontratas', 'sync/preview_subcontratas.html')
        service = get_sync_adapter()
        diff = service.get_diff_subcontratas()
        preview = analyze_subcontratas_preview(diff)
        return _render_preview('subcontratas', 'sync/preview_subcontratas.html', diff, preview)
    except Exception as e:
        flash(f"Error Odoo: {str(e)}", "danger")
        return redirect(url_for('sync.odoo_panel'))

@sync_bp.route('/commit_subcontratas', methods=['POST'])
@login_required
@roles_required(ROLE_ADMIN)
def commit_subcontratas():
    data = request.json
    from app.utils.timezone_utils import utc_now
    ahora = utc_now()
    
    try:
        mapa_empresas = {} 
        
        # 1. ACTUALIZAR O CREAR EMPRESAS
        for obj in data.get('empresas', {}).get('actualizadas', []):
            comp = Company.query.get(obj['local_id'])
            if comp:
                ext_ids = dict(comp.external_ids or {})
                ext_ids['odoo'] = str(obj['odoo_id'])
                comp.external_ids = ext_ids
                comp.nombre = obj['nombre']
                comp.active = True
                mapa_empresas[obj['odoo_id']] = comp.id
                db.session.add(comp)

        for obj in data.get('empresas', {}).get('nuevas', []):
            nueva_comp = Company(
                external_ids={'odoo': str(obj['odoo_id'])},
                nombre=obj['nombre'],
            )
            db.session.add(nueva_comp)
            db.session.flush() 
            mapa_empresas[obj['odoo_id']] = nueva_comp.id

        # 2. ACTUALIZAR EMPLEADOS (Seguro Anti-Colisiones DNI)
        from app.services.employee_baja_service import (
            aplicar_baja_por_odoo,
            desactivados_aplicables,
            reactivar,
        )
        for obj in data.get('empleados', {}).get('actualizados', []):
            user = User.query.get(obj['local_id'])
            if user:
                ext_ids = dict(user.external_ids or {})
                ext_ids['odoo'] = str(obj['odoo_id'])
                user.external_ids = ext_ids
                user.name = obj['name']
                user.lastname = obj['lastname']
                user.categoria_profesional = obj.get('categoria_profesional')
                db.session.add(user)

                if obj['dni'] and not 'SINDNI' in obj['dni']:
                    # Comprobamos si otro usuario distinto ya tiene ese DNI
                    choque = User.query.filter(User.dni == obj['dni'], User.id != user.id).first()
                    if choque:
                        user.dni = f"{obj['dni']}-EXT{obj['odoo_id']}"
                    else:
                        user.dni = obj['dni']
                
                # --- CORRECCIÓN: Búsqueda dinámica de la empresa ---
                odoo_c_id = obj.get('odoo_company_id')
                if odoo_c_id:
                    if odoo_c_id not in mapa_empresas:
                        comp_existente = _company_by_odoo_id(odoo_c_id)
                        if comp_existente:
                            mapa_empresas[odoo_c_id] = comp_existente.id
                    
                    if odoo_c_id in mapa_empresas:
                        user.company_id = mapa_empresas[odoo_c_id]
                # ---------------------------------------------------
                if not user.active:
                    reactivar(user, actor_id=current_user.id, commit=False)
                else:
                    user.active = True

        # 3. NUEVOS EMPLEADOS (Seguro Anti-Colisiones DNI + Memoria de Transacción)
        dnis_en_transaccion = set() # Memoria temporal por si en el mismo guardado vienen varios repetidos

        from app.services.plan_service import PlanLimitError, exigir_cupo, rol_cuenta_como_empleado

        nuevos_empleados = data.get('empleados', {}).get('nuevos', [])
        plazas = sum(1 for obj in nuevos_empleados if rol_cuenta_como_empleado(obj.get('role')))
        try:
            if plazas:
                exigir_cupo(plazas)
        except PlanLimitError as exc:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(exc)}), 403

        for obj in nuevos_empleados:
            # --- CORRECCIÓN: Búsqueda dinámica de la empresa ---
            odoo_c_id = obj.get('odoo_company_id')
            local_comp_id = mapa_empresas.get(odoo_c_id)
            
            if not local_comp_id and odoo_c_id:
                comp_existente = _company_by_odoo_id(odoo_c_id)
                if comp_existente:
                    local_comp_id = comp_existente.id
                    mapa_empresas[odoo_c_id] = local_comp_id
            # ---------------------------------------------------
            
            dni_limpio = obj['dni']
            
            # Revisar si existe en la BD o si ya lo hemos procesado en este mismo bucle
            existe_en_bd = User.query.filter_by(dni=dni_limpio).first()
            if existe_en_bd or dni_limpio in dnis_en_transaccion:
                dni_limpio = f"{dni_limpio}-EXT{obj['odoo_id']}"
                
            dnis_en_transaccion.add(dni_limpio)
            
            nuevo_user = User(
                external_ids={'odoo': str(obj['odoo_id'])},
                name=obj['name'],
                lastname=obj['lastname'],
                dni=dni_limpio,
                email=obj['email'],
                role=obj['role'],
                categoria_profesional=obj.get('categoria_profesional'),
                company_id=local_comp_id,
                active=True,
                email_verified=True,
                password_hash=generate_password_hash(secrets.token_urlsafe(16)),
            )
            db.session.add(nuevo_user)

        emp_baja = desactivados_aplicables(data, data.get('empleados', {}).get('desactivados') or [])
        for obj in emp_baja:
            local_id = obj.get('local_id')
            if local_id:
                aplicar_baja_por_odoo(local_id, actor_id=current_user.id, commit=False)

        total_nuevos = len(data.get('empresas', {}).get('nuevas', [])) + len(data.get('empleados', {}).get('nuevos', []))
        total_act = len(data.get('empresas', {}).get('actualizadas', [])) + len(data.get('empleados', {}).get('actualizados', []))
        detalle = "Sincronización de subcontratas y externos."
        if emp_baja:
            detalle = f"{detalle} {len(emp_baja)} baja(s)."

        db.session.add(SyncLog(
            fecha=ahora, tipo='Subcontratas', modo='Manual',
            nuevos=total_nuevos, actualizados=total_act,
            finalizados=len(emp_baja), errores=0, detalles=detalle
        ))

        db.session.commit()
        _clear_preview_cache('subcontratas')
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    
@sync_bp.route('/commit_empleados', methods=['POST'])
@login_required
@roles_required(ROLE_ADMIN)
def commit_empleados():
    data = request.json
    from app.utils.timezone_utils import utc_now
    ahora = utc_now()
    try:
        # Buscamos la primera empresa local para asignarla y que no sean "fantasmas"
        default_company = Company.query.filter_by(is_internal=True).first() or Company.query.first()
        default_company_id = default_company.id if default_company else None
        dnis_en_transaccion = set()
        emails_en_transaccion = set()

        from app.services.plan_service import (
            PlanLimitError,
            cuenta_como_empleado,
            exigir_cupo,
            rol_cuenta_como_empleado,
        )

        plazas_nuevas = 0
        for obj in data.get('actualizados', []):
            user = User.query.get(obj['local_id'])
            if not user:
                continue
            ocupar_antes = cuenta_como_empleado(user)
            ocupar_despues = cuenta_como_empleado(
                role=obj.get('role') or user.role,
                active=True,
                is_deleted=False,
            )
            if ocupar_despues and not ocupar_antes:
                plazas_nuevas += 1
        plazas_nuevas += sum(
            1 for obj in data.get('nuevos', [])
            if rol_cuenta_como_empleado(obj.get('role'))
        )
        try:
            if plazas_nuevas:
                exigir_cupo(plazas_nuevas)
        except PlanLimitError as exc:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(exc)}), 403

        for obj in data.get('actualizados', []):
            user = User.query.get(obj['local_id'])
            if user:
                choque_dni = User.query.filter(User.dni == obj['dni'], User.id != user.id).first()
                choque_email = User.query.filter(User.email == obj['email'], User.id != user.id).first()

                user.external_ids = user.external_ids or {}
                user.external_ids['odoo'] = str(obj['odoo_id'])
                user.external_ids['odoo_model'] = 'hr.employee'
                if obj.get('barcode'):
                    user.external_ids['barcode'] = str(obj['barcode']).strip()
                from sqlalchemy.orm.attributes import flag_modified
                flag_modified(user, 'external_ids')
                user.name = obj['name']
                user.lastname = obj['lastname']
                from app.services.user_role_sync_service import apply_odoo_role_if_allowed
                apply_odoo_role_if_allowed(user, obj['role'])
                user.categoria_profesional = obj.get('categoria_profesional', user.categoria_profesional)

                if not choque_dni:
                    user.dni = obj['dni']
                if not choque_email:
                    user.email = obj['email']

                user.company_id = default_company_id
                from app.services.employee_baja_service import reactivar
                if not user.active:
                    reactivar(user, actor_id=current_user.id, commit=False)
                else:
                    user.active = True
                user.is_deleted = False
                db.session.add(user)

                dnis_en_transaccion.add(user.dni)
                emails_en_transaccion.add(user.email)
                from app.utils import register_log
                register_log(
                    user_id=current_user.id,
                    category='rrhh_sync',
                    action="Empleado Actualizado desde Odoo",
                    detail=f"Datos modificados para: {user.name} {user.lastname}",
                    target_user_id=user.id,
                )

        for obj in data.get('nuevos', []):
            dni_limpio = obj['dni']
            email_limpio = obj['email']
            existe_bd = User.query.filter((User.dni == dni_limpio) | (User.email == email_limpio)).first()
            if existe_bd or dni_limpio in dnis_en_transaccion or email_limpio in emails_en_transaccion:
                dni_limpio = f"{dni_limpio}-Odoo{obj['odoo_id']}"
                email_limpio = f"colision_{obj['odoo_id']}@local.tuappsaas.com"
            dnis_en_transaccion.add(dni_limpio)
            emails_en_transaccion.add(email_limpio)

            ext_new = {'odoo': str(obj['odoo_id']), 'odoo_model': 'hr.employee'}
            if obj.get('barcode'):
                ext_new['barcode'] = str(obj['barcode']).strip()
            db.session.add(User(
                external_ids=ext_new,
                name=obj['name'],
                lastname=obj['lastname'],
                dni=dni_limpio,
                email=email_limpio,
                role=obj['role'],
                categoria_profesional=obj.get('categoria_profesional', 'Sin definir'),
                active=True,
                email_verified=True,
                company_id=default_company_id,
                password_hash=generate_password_hash(dni_limpio),
            ))

        from app.services.employee_baja_service import aplicar_baja_por_odoo, desactivados_aplicables
        emp_baja = desactivados_aplicables(data, data.get('desactivados') or [])
        for obj in emp_baja:
            local_id = obj.get('local_id')
            if local_id:
                aplicar_baja_por_odoo(local_id, actor_id=current_user.id, commit=False)

        detalle = "Sincronización manual de empleados completada."
        if emp_baja:
            detalle = f"{detalle} {len(emp_baja)} baja(s)."
        db.session.add(SyncLog(
            fecha=ahora,
            tipo='Empleados',
            modo='Manual',
            nuevos=len(data.get('nuevos', [])),
            actualizados=len(data.get('actualizados', [])),
            finalizados=len(emp_baja),
            errores=data.get('errores', 0),
            detalles=detalle,
        ))

        db.session.commit()
        _clear_preview_cache('empleados')
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    
@sync_bp.route('/auditoria')
@login_required
def auditoria_fichajes():
    from flask import current_app
    from app.services.permission_service import user_can
    from app.services.fichaje_operario_service import (
        tenant_muestra_auditoria_fichajes,
        tenant_tiene_fichaje_operario_module,
    )
    if not user_can(current_user, 'auditoria_fichajes', 'r') or not tenant_muestra_auditoria_fichajes():
        flash("Acceso denegado.", "danger")
        return redirect(url_for('main.dashboard'))

    try:
        # 1. FILTROS BASE MÚLTIPLES
        filtros_pendientes = [RegistroFichaje.estado.in_(
            ['Conflicto', 'Disputa', 'Paracaidista', 'Ausencia']
        )]
        filtros_historial = [~RegistroFichaje.estado.in_(
            ['Conflicto', 'Disputa', 'Paracaidista', 'Ausencia', 'Sin_Registro', 'Sobreescrito_RRHH']
        )]
        filtros_correcciones = [RegistroFichaje.estado == 'Sobreescrito_RRHH']

        # 2. SI ES JEFE DE OBRA, AÑADIMOS RESTRICCIONES
        if current_user.role == 'jefe_obra':
            obras_jefe = Obra.query.filter_by(jefe_obra_id=current_user.id).all()
            obras_jefe_ids = [obra.id for obra in obras_jefe]

            filtro_jefe = or_(
                RegistroFichaje.obra_planificada_id.in_(obras_jefe_ids),
                RegistroFichaje.obra_real_id.in_(obras_jefe_ids)
            )
            filtros_pendientes.append(filtro_jefe)
            filtros_historial.append(filtro_jefe)
            filtros_correcciones.append(filtro_jefe)

        # 3. Solo pendientes en la carga inicial (historial/correcciones = lazy).
        # Evita timeout «Esta página no funciona» a la primera visita.
        pendientes = (
            RegistroFichaje.query
            .options(*_AUDITORIA_EAGER)
            .filter(*filtros_pendientes)
            .order_by(RegistroFichaje.fecha.desc())
            .limit(_AUDITORIA_PENDIENTES_LIMIT)
            .all()
        )
        from app.services.desvio_fichaje_service import enriquecer_pendientes_desvio
        try:
            pendientes = enriquecer_pendientes_desvio(pendientes, current_user)
        except Exception:
            current_app.logger.exception('enriquecer_pendientes_desvio falló; se muestran sin UI desvío')
        from app.services.desvio_fichaje_service import repartir_secciones_auditoria
        try:
            _secciones = repartir_secciones_auditoria(pendientes)
            var_conflictos = _secciones['conflictos']
            var_ausencias = _secciones['ausencias']
            var_paracaidistas = _secciones['paracaidistas']
        except Exception:
            current_app.logger.exception('repartir_secciones_auditoria falló')
            var_conflictos = [
                r for r in pendientes if r.estado in ('Conflicto', 'Disputa')
            ]
            var_ausencias = [r for r in pendientes if r.estado == 'Ausencia']
            var_paracaidistas = [
                r for r in pendientes if r.estado == 'Paracaidista'
            ]
        historial = []
        correcciones = []
        historial_total = (
            RegistroFichaje.query.filter(*filtros_historial).count()
        )
        correcciones_total = (
            RegistroFichaje.query.filter(*filtros_correcciones).count()
        )
        visible_sections = laboral_auditoria_sections(current_user)

        from app.services.fichaje_geo_audit_service import (
            contar_geo_dudosa,
            entrada_geo_por_registros,
        )
        from app.services.geocerca_service import geocerca_activa

        geo_por_registro = entrada_geo_por_registros(list(pendientes))
        geo_dudosa_count = contar_geo_dudosa(geo_por_registro)
        muestra_geo_audit = geocerca_activa()

        trabajadores_marca = []
        obras_marca = []
        if can_resolve_fichajes(current_user) and current_user.role in (
            'admin', ROLE_LABORAL, ROLE_RRHH,
        ):
            trabajadores_marca = (
                User.query
                .filter(
                    User.is_deleted.is_(False),
                    User.active.is_(True),
                    User.role.in_(['operario', 'jefe_obra', 'admin', 'laboral']),
                )
                .order_by(User.lastname.asc(), User.name.asc())
                .limit(500)
                .all()
            )
            obras_marca = (
                Obra.query
                .filter(Obra.estado != 'Finalizada')
                .order_by(Obra.nombre.asc())
                .limit(400)
                .all()
            )

        return render_template(
            'sync/auditoria.html',
            pendientes=pendientes,
            var_conflictos=var_conflictos,
            var_ausencias=var_ausencias,
            var_paracaidistas=var_paracaidistas,
            historial=historial,
            correcciones=correcciones,
            historial_total=historial_total,
            correcciones_total=correcciones_total,
            auditoria_lazy=True,
            auditoria_sections=visible_sections,
            visible_sections=visible_sections,
            can_resolve=can_resolve_fichajes(current_user),
            can_resolve_fichajes=can_resolve_fichajes(current_user),
            can_sync_fichajes=user_can(current_user, 'auditoria_fichajes', 'w') or user_can(current_user, 'sync_odoo', 'w'),
            trabajadores_marca=trabajadores_marca,
            obras_marca=obras_marca,
            geo_por_registro=geo_por_registro,
            geo_dudosa_count=geo_dudosa_count,
            muestra_geo_audit=muestra_geo_audit,
            puede_ver_mapa_fichajes=(
                user_can(current_user, 'mapa_fichajes', 'r')
                and tenant_tiene_fichaje_operario_module()
            ),
        )
    except Exception:
        current_app.logger.exception('Fallo al cargar auditoría de fichajes')
        flash('No se pudo cargar la auditoría. Inténtalo de nuevo.', 'danger')
        return redirect(url_for('main.dashboard'))


def _auditoria_filtros_jefe():
    filtros_historial = [~RegistroFichaje.estado.in_(
        ['Conflicto', 'Disputa', 'Paracaidista', 'Ausencia', 'Sin_Registro', 'Sobreescrito_RRHH']
    )]
    filtros_correcciones = [RegistroFichaje.estado == 'Sobreescrito_RRHH']
    if current_user.role == 'jefe_obra':
        obras_jefe_ids = [
            o.id for o in Obra.query.filter_by(jefe_obra_id=current_user.id).all()
        ]
        filtro_jefe = or_(
            RegistroFichaje.obra_planificada_id.in_(obras_jefe_ids),
            RegistroFichaje.obra_real_id.in_(obras_jefe_ids),
        )
        filtros_historial.append(filtro_jefe)
        filtros_correcciones.append(filtro_jefe)
    return filtros_historial, filtros_correcciones


@sync_bp.route('/auditoria/seccion/<seccion>', methods=['GET'])
@login_required
def auditoria_fichajes_seccion(seccion):
    """Carga diferida de histórico / correcciones (evita tumbar la 1ª visita)."""
    from flask import current_app
    from app.services.permission_service import user_can
    from app.services.fichaje_operario_service import tenant_muestra_auditoria_fichajes

    if not user_can(current_user, 'auditoria_fichajes', 'r') or not tenant_muestra_auditoria_fichajes():
        return jsonify({'success': False, 'error': translate('Acceso denegado')}), 403
    if seccion not in ('historial', 'correcciones'):
        return jsonify({'success': False, 'error': translate('Sección desconocida')}), 400

    try:
        filtros_historial, filtros_correcciones = _auditoria_filtros_jefe()
        if seccion == 'historial':
            registros = (
                RegistroFichaje.query
                .options(*_AUDITORIA_EAGER)
                .filter(*filtros_historial)
                .order_by(RegistroFichaje.fecha.desc(), RegistroFichaje.fecha_auditoria.desc())
                .limit(_AUDITORIA_HISTORIAL_LIMIT)
                .all()
            )
        else:
            registros = (
                RegistroFichaje.query
                .options(*_AUDITORIA_EAGER)
                .filter(*filtros_correcciones)
                .order_by(RegistroFichaje.fecha.desc())
                .limit(_AUDITORIA_CORRECCIONES_LIMIT)
                .all()
            )

        from app.services.fichaje_geo_audit_service import entrada_geo_por_registros
        from app.services.geocerca_service import geocerca_activa
        geo_por_registro = entrada_geo_por_registros(registros)
        visible_sections = laboral_auditoria_sections(current_user)
        html = render_template(
            'sync/_auditoria_seccion_rows.html',
            seccion=seccion,
            registros=registros,
            geo_por_registro=geo_por_registro,
            muestra_geo_audit=geocerca_activa(),
            can_resolve_fichajes=can_resolve_fichajes(current_user),
            visible_sections=visible_sections,
        )
        return jsonify({'success': True, 'html': html, 'count': len(registros)})
    except Exception:
        current_app.logger.exception('Fallo sección auditoría %s', seccion)
        return jsonify({'success': False, 'error': translate('No se pudo cargar la sección')}), 500

ACCION_RESOLUCION_TITULOS = {
    'ignorar': 'Ignorar',
    'mover': 'Mover',
    'anadir': 'Añadir',
    'borrar_planificacion': 'Borrar Planificación',
    'confirmar_ausencia': 'Confirmar Ausencia',
    'liberar_plaza': 'Liberar plaza',
    'mantener_falta': 'Mantener falta',
    'aceptar_entrada': 'Aceptar entrada',
    'rechazar_entrada': 'Rechazar entrada',
    'confirmar_desvio': 'Confirmar desvío',
    'rechazar_desvio': 'Confirmar falta (desvío)',
}

# Placeholders / pendientes que dejan la pelotita naranja tras resolver otra fila.
# Incluye Paracaidista/Conflicto hermanos: si el admin ya cerró el caso del día
# (p. ej. aceptó multi-obra), no deben dejar la pelotita en rojo/naranja.
_ESTADOS_HERMANO_PLACEHOLDER = (
    'Sin_Registro', 'Ausencia', 'Pendiente', 'Retraso',
    'Paracaidista', 'Conflicto', 'Disputa',
)


_ESTADOS_RESUELTOS = (
    'Resuelto_Movido',
    'Resuelto_Asignado',
    'Resuelto_Dividido',
    'Resuelto_Ignorado',
    'Resuelto_Falta',
    'Resuelto_Ausencia',
    'Falta',
)


def _cerrar_hermanos_placeholder(registro, accion, estado_anterior=None):
    """
    Al aceptar/mover/borrar, cierra semillas hermanas del mismo día.

    No cierra otros Conflicto/Disputa de distintas obras de plan (multi-desvío):
    cada pata se resuelve aparte.
    """
    if accion not in (
        'anadir', 'mover', 'borrar_planificacion', 'ignorar', 'confirmar_ausencia',
    ):
        return

    semillas = ('Sin_Registro', 'Ausencia', 'Pendiente', 'Retraso')
    hermanos = RegistroFichaje.query.filter(
        RegistroFichaje.user_id == registro.user_id,
        RegistroFichaje.fecha == registro.fecha,
        RegistroFichaje.id != registro.id,
        RegistroFichaje.estado.in_(_ESTADOS_HERMANO_PLACEHOLDER),
    ).all()
    nota = {
        'anadir': 'Cerrado: el día quedó aceptado (multi-obra / asignación).',
        'mover': 'Cerrado: el fichaje se movió a otra obra.',
        'borrar_planificacion': 'Cerrado: se eliminó la planificación asociada.',
        'ignorar': 'Cerrado junto con la incidencia ignorada.',
        'confirmar_ausencia': 'Cerrado: falta confirmada en esa obra de plan.',
    }.get(accion, 'Cerrado tras resolución de auditoría.')

    obra_real = registro.obra_real_id
    obra_plan = registro.obra_planificada_id

    for h in hermanos:
        # Falta / desasignar: solo semillas de la misma obra de plan.
        if accion in ('confirmar_ausencia', 'borrar_planificacion'):
            if h.estado not in semillas:
                continue
            if obra_plan and h.obra_planificada_id and h.obra_planificada_id != obra_plan:
                continue
            h.estado_antes_resolucion = h.estado
            h.estado = 'Resuelto_Ignorado'
            h.resuelto_por_id = registro.resuelto_por_id
            h.fecha_auditoria = registro.fecha_auditoria
            h.notas_resolucion = nota
            continue

        # No tocar desvíos de otras obras de plan.
        if h.estado in ('Conflicto', 'Disputa'):
            if (
                h.obra_planificada_id
                and obra_plan
                and h.obra_planificada_id != obra_plan
            ):
                continue

        # Aceptar Paracaidista: borrar semillas fantasma del día.
        if (
            estado_anterior == 'Paracaidista'
            and accion == 'anadir'
            and h.estado in semillas
        ):
            db.session.delete(h)
            continue

        if h.estado in semillas or (
            h.estado in ('Conflicto', 'Disputa', 'Paracaidista')
            and (not obra_plan or h.obra_planificada_id == obra_plan)
        ):
            h.estado_antes_resolucion = h.estado
            h.estado = 'Resuelto_Ignorado'
            h.resuelto_por_id = registro.resuelto_por_id
            h.fecha_auditoria = registro.fecha_auditoria
            h.notas_resolucion = nota


def _reabrir_hermanos_cerrados(registro, fecha_auditoria_previa):
    """Restaura hermanos auto-cerrados en la misma resolución (misma fecha_auditoria)."""
    if not fecha_auditoria_previa:
        return
    hermanos = RegistroFichaje.query.filter(
        RegistroFichaje.user_id == registro.user_id,
        RegistroFichaje.fecha == registro.fecha,
        RegistroFichaje.id != registro.id,
        RegistroFichaje.estado == 'Resuelto_Ignorado',
        RegistroFichaje.fecha_auditoria == fecha_auditoria_previa,
    ).all()
    for h in hermanos:
        previo = (h.estado_antes_resolucion or '').strip()
        if not previo or previo in _ESTADOS_RESUELTOS:
            continue
        if not (h.notas_resolucion or '').startswith('Cerrado:'):
            continue
        h.estado = previo
        h.estado_antes_resolucion = None
        h.notas_resolucion = None
        h.resuelto_por_id = None
        h.fecha_auditoria = None


def _obra_label_resolucion(obra_id):
    if not obra_id:
        return None
    return CoreAssignmentService.format_obra_label(Obra.query.get(obra_id))


def _detalle_resolucion_fichaje(registro, accion, estado_anterior=None):
    obra_real = _obra_label_resolucion(registro.obra_real_id)
    obra_plan = _obra_label_resolucion(registro.obra_planificada_id)

    if accion == 'ignorar':
        if obra_real and obra_plan and obra_real != obra_plan:
            return (
                f"Se ignora el fichaje en '{obra_real}' "
                f"(estaba planificado en '{obra_plan}')."
            )
        if obra_real:
            return f"Se ignora el fichaje en '{obra_real}'."
        if obra_plan:
            return f"Se ignora la incidencia en '{obra_plan}'."
        return "Incidencia ignorada."

    if accion == 'mover':
        if obra_plan and obra_real:
            return f"Cuadrante actualizado: de '{obra_plan}' a '{obra_real}'."
        if obra_real:
            return f"Reasignado a '{obra_real}'."
        return "Reasignado a la obra real."

    if accion == 'anadir':
        if estado_anterior in ('Paracaidista', 'Conflicto') and obra_real:
            return f"Se acepta el fichaje {'sin planificar' if estado_anterior == 'Paracaidista' else 'con desviación de plan'} en '{obra_real}'."
        if obra_real:
            return f"Añadida asignación en '{obra_real}' (pluriempleo)."
        return "Añadida multi-asignación (pluriempleo)."

    if accion == 'borrar_planificacion':
        if obra_plan:
            return (
                f"Se desasigna de '{obra_plan}' "
                f"(la planificación no aplicaba / se elimina del cuadrante)."
            )
        return "Planificación eliminada."

    if accion == 'confirmar_ausencia':
        if obra_plan:
            return f"Falta confirmada: debía acudir a '{obra_plan}' y no fichó."
        return "Falta confirmada."

    return "Ajuste manual del cuadrante/fichaje."


@sync_bp.route('/auditoria/resolver', methods=['POST'])
@login_required
def resolver_fichaje():
    # BLINDAJE: Forzamos las importaciones dentro de la función para 
    # asegurar que Python no se confunda con variables locales o errores tipográficos.
    from app import db
    from app.models import RegistroFichaje, Asignacion, Obra
    from datetime import datetime
    
    if current_user.role not in ['admin', 'jefe_obra', ROLE_LABORAL, ROLE_RRHH]:
        return jsonify({'success': False, 'error': translate('No autorizado')}), 403
    from app.services.fichaje_operario_service import tenant_muestra_auditoria_fichajes
    if not tenant_muestra_auditoria_fichajes():
        return jsonify({'success': False, 'error': translate('Acceso denegado.')}), 403
    if not can_resolve_fichajes(current_user):
        return jsonify({'success': False, 'error': translate('Resolución deshabilitada para este perfil.')}), 403
        
    data = request.json
    registro_id = data.get('registro_id')
    accion = data.get('accion')
    scope = (data.get('scope') or 'day').strip().lower()
    if scope not in ('day', 'future'):
        scope = 'day'
    notas_desasign = (data.get('notas') or '').strip() or None
    
    registro = RegistroFichaje.query.get(registro_id)
    if not registro:
        return jsonify({'success': False, 'error': translate('Registro no encontrado')}), 404
        
    # Seguridad Backend: Evitar que un jefe resuelva un registro de otra obra
    if current_user.role == 'jefe_obra':
        obras_del_jefe = [o.id for o in Obra.query.filter_by(jefe_obra_id=current_user.id).all()]
        if registro.obra_planificada_id not in obras_del_jefe and registro.obra_real_id not in obras_del_jefe:
            return jsonify({'success': False, 'error': translate('No tienes permisos sobre este registro.')}), 403

    def _desasignar_futuro_desde_registro():
        """Desde hoy (o la fecha del registro si es futura) hasta el final en esa obra de plan.

        Si no hay más días que cortar, no es error: el liberar del desvío
        sigue quitando la plaza del día del registro.
        """
        from app.services.assignment_service import process_unassign_action
        from app.utils.timezone_utils import today_local

        obra_id = registro.obra_planificada_id
        if not obra_id:
            return {
                'success': False,
                'message': translate('No hay obra planificada que desasignar.'),
            }
        hoy = today_local()
        # process_unassign solo toca >= hoy; el día pasado del desvío lo libera
        # aplicar_accion_desvio (liberar_plaza) a continuación.
        desde = registro.fecha if registro.fecha >= hoy else hoy
        fechas = sorted({
            a.fecha
            for a in Asignacion.query.filter(
                Asignacion.user_id == registro.user_id,
                Asignacion.obra_id == obra_id,
                Asignacion.fecha >= desde,
            ).all()
        })
        if not fechas:
            # Sin filas futuras: aún intentamos cortar inercia ese día; si no hay
            # nada, seguimos (noop) para no tumbar el desasignado del desvío.
            un = process_unassign_action(
                actor_user=current_user,
                worker_id=registro.user_id,
                target_obra_id=obra_id,
                date_list=[desde.isoformat()],
                mode='selected',
                notas=notas_desasign,
            )
            if un.get('success'):
                return un
            return {
                'success': True,
                'action': 'noop',
                'message': translate(
                    'No había más días futuros que desasignar en esta obra.'
                ),
            }
        return process_unassign_action(
            actor_user=current_user,
            worker_id=registro.user_id,
            target_obra_id=obra_id,
            date_list=[d.isoformat() for d in fechas],
            mode='selected',
            notas=notas_desasign,
        )

    from app.services.desvio_fichaje_service import (
        ACCION_ACEPTAR_ENTRADA,
        ACCION_CONFIRMAR_DESVIO,
        ACCION_LIBERAR_PLAZA,
        ACCION_MANTENER_FALTA,
        ACCION_RECHAZAR_DESVIO,
        ACCION_RECHAZAR_ENTRADA,
        DesvioFichajeError,
        aplicar_accion_desvio,
        es_desvio_plan_vs_real,
        label_resolucion_plan,
        label_resolucion_real,
    )

    # Desvío X→Y: a favor / en contra por lado (o cierre completo)
    if accion in (
        ACCION_LIBERAR_PLAZA,
        ACCION_MANTENER_FALTA,
        ACCION_ACEPTAR_ENTRADA,
        ACCION_RECHAZAR_ENTRADA,
        ACCION_CONFIRMAR_DESVIO,
        ACCION_RECHAZAR_DESVIO,
    ):
        try:
            if accion == ACCION_LIBERAR_PLAZA and scope == 'future':
                un = _desasignar_futuro_desde_registro()
                if not un.get('success'):
                    return jsonify({
                        'success': False,
                        'error': un.get('message') or translate('Error'),
                    }), 400
                if un.get('action') == 'requested':
                    from app.utils import register_log
                    register_log(
                        user_id=current_user.id,
                        category='fichajes',
                        action='Resolución de Fichaje: Desasignar (solicitud)',
                        detail=un.get('message'),
                        target_user_id=registro.user_id,
                        target_date=registro.fecha,
                    )
                    return jsonify({
                        'success': True,
                        'resolved': False,
                        'dismiss_row': False,
                        'requested': True,
                        'message': translate(un.get('message') or 'OK'),
                        'ack_plan': False,
                        'ack_real': bool(getattr(registro, 'desvio_ack_real_at', None)),
                    })
                # Desasignación directa a futuro: cerrar también el lado plan del desvío
                try:
                    db.session.refresh(registro)
                except Exception:
                    pass
            resultado = aplicar_accion_desvio(registro, accion, current_user)
            if notas_desasign and accion == ACCION_LIBERAR_PLAZA:
                base = (registro.notas_resolucion or resultado.get('message') or '').strip()
                comentario = f"Comentario: {notas_desasign}"
                registro.notas_resolucion = (
                    f"{base} {comentario}".strip() if base else comentario
                )
            if resultado.get('resolved'):
                herm_accion = (
                    'confirmar_ausencia'
                    if registro.estado in ('Resuelto_Ausencia', 'Falta')
                    else 'mover'
                )
                _cerrar_hermanos_placeholder(
                    registro, herm_accion, estado_anterior='Conflicto'
                )
            from app.utils import register_log
            accion_titulo = ACCION_RESOLUCION_TITULOS.get(
                accion, accion.replace('_', ' ').title()
            )
            register_log(
                user_id=current_user.id,
                category='fichajes',
                action=f"Resolución de Fichaje: {accion_titulo}",
                detail=resultado.get('message') or registro.notas_resolucion,
                target_user_id=registro.user_id,
                target_date=registro.fecha,
            )
            db.session.commit()
            def _ack_nombre(uid):
                if not uid:
                    return None
                from app.models import User as _UserAck
                u = _UserAck.query.get(uid)
                if not u:
                    return None
                return f"{(u.name or '').strip()} {(u.lastname or '').strip()}".strip() or None
            return jsonify({
                'success': True,
                'resolved': resultado.get('resolved'),
                'dismiss_row': resultado.get('dismiss_for_viewer', True),
                'message': translate(resultado.get('message') or 'OK'),
                'ack_plan': resultado.get('ack_plan'),
                'ack_real': resultado.get('ack_real'),
                'ack_plan_por': _ack_nombre(registro.desvio_ack_plan_by_id),
                'ack_real_por': _ack_nombre(registro.desvio_ack_real_by_id),
                'ack_plan_label': (
                    translate(label_resolucion_plan(resultado.get('decision_plan') or registro.desvio_decision_plan))
                    if resultado.get('ack_plan') else None
                ),
                'ack_real_label': (
                    translate(label_resolucion_real(resultado.get('decision_real') or registro.desvio_decision_real))
                    if resultado.get('ack_real') else None
                ),
            })
        except DesvioFichajeError as err:
            db.session.rollback()
            return jsonify({'success': False, 'error': translate(err.message)}), err.status
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(e)}), 500

    # Acciones clásicas sobre un desvío: cierran ambas firmas de golpe
    if es_desvio_plan_vs_real(registro) and accion in (
        'mover', 'anadir', 'ignorar', 'borrar_planificacion',
    ):
        from app.utils.timezone_utils import utc_now as _utc_now
        ahora = _utc_now()
        if not registro.desvio_ack_plan_at:
            registro.desvio_ack_plan_at = ahora
            registro.desvio_ack_plan_by_id = current_user.id
        if not registro.desvio_ack_real_at:
            registro.desvio_ack_real_at = ahora
            registro.desvio_ack_real_by_id = current_user.id

    try:
        registro.resuelto_por_id = current_user.id
        from app.utils.timezone_utils import utc_now
        registro.fecha_auditoria = utc_now()

        # Guardar clasificación previa para poder «Reabrir» desde el histórico.
        estado_previo = registro.estado
        if estado_previo and estado_previo not in _ESTADOS_RESUELTOS:
            registro.estado_antes_resolucion = estado_previo

        estado_anterior = None

        if accion == 'ignorar':
            registro.estado = 'Resuelto_Ignorado'

        elif accion == 'mover':
            # 1. Borrar de la obra donde estaba planificado y NO fue
            asignaciones_viejas = Asignacion.query.filter_by(
                user_id=registro.user_id, 
                fecha=registro.fecha, 
                obra_id=registro.obra_planificada_id
            ).all()
            for asig in asignaciones_viejas:
                CoreAssignmentService.desasignar(
                    asig.user_id, asig.obra_id, asig.fecha, current_user.id,
                    "Resolución de Fichaje: Mover"
                )
            
            # 2. Añadir a la obra donde SÍ ha ido (si no existe ya)
            if registro.obra_real_id:
                existe = Asignacion.query.filter_by(
                    user_id=registro.user_id, 
                    fecha=registro.fecha, 
                    obra_id=registro.obra_real_id
                ).first()
                if not existe:
                    CoreAssignmentService.asignar(
                        registro.user_id, registro.obra_real_id, registro.fecha,
                        current_user.id, "Resolución de Fichaje: Mover"
                    )
                
            registro.estado = 'Resuelto_Movido'

        elif accion == 'anadir':
            estado_anterior = estado_previo

            if registro.obra_real_id:
                existe = Asignacion.query.filter_by(
                    user_id=registro.user_id, 
                    fecha=registro.fecha, 
                    obra_id=registro.obra_real_id
                ).first()
                if not existe:
                    CoreAssignmentService.asignar(
                        registro.user_id, registro.obra_real_id, registro.fecha,
                        current_user.id, "Resolución de Fichaje: Añadir",
                    )

            # Paracaidista: el fichaje ya ocurrió en obra_real. Al aceptar hay que
            # enlazar obra_planificada_id; si no, el sync siembra Sin_Registro→Ausencia
            # y dispara el correo de «no ha fichado» aunque sí fichó.
            if (
                estado_anterior == 'Paracaidista'
                and registro.obra_real_id
                and not registro.obra_planificada_id
            ):
                registro.obra_planificada_id = registro.obra_real_id
            
            if estado_anterior in ('Paracaidista', 'Conflicto'):
                registro.estado = 'Resuelto_Asignado'
            else:
                registro.estado = 'Resuelto_Dividido'

        elif accion == 'borrar_planificacion':
            if scope == 'future':
                un = _desasignar_futuro_desde_registro()
                if not un.get('success'):
                    return jsonify({
                        'success': False,
                        'error': un.get('message') or translate('Error'),
                    }), 400
                if un.get('action') == 'requested':
                    from app.utils import register_log
                    register_log(
                        user_id=current_user.id,
                        category='fichajes',
                        action='Resolución de Fichaje: Desasignar (solicitud)',
                        detail=un.get('message'),
                        target_user_id=registro.user_id,
                        target_date=registro.fecha,
                    )
                    return jsonify({
                        'success': True,
                        'resolved': False,
                        'dismiss_row': False,
                        'requested': True,
                        'message': translate(un.get('message') or 'OK'),
                    })
            else:
                asignaciones_viejas = Asignacion.query.filter_by(
                    user_id=registro.user_id,
                    fecha=registro.fecha,
                    obra_id=registro.obra_planificada_id
                ).all()
                for asig in asignaciones_viejas:
                    CoreAssignmentService.desasignar(
                        asig.user_id, asig.obra_id, asig.fecha, current_user.id,
                        "Desasignar (planificación incorrecta)",
                    )

            registro.estado = 'Resuelto_Falta'

        elif accion == 'confirmar_ausencia':
            # Falta real: sigue planificado con estado visual Falta.
            from app.services.desvio_fichaje_service import ESTADO_FALTA
            if registro.obra_planificada_id:
                existe = Asignacion.query.filter_by(
                    user_id=registro.user_id,
                    fecha=registro.fecha,
                    obra_id=registro.obra_planificada_id,
                ).first()
                if not existe:
                    CoreAssignmentService.asignar(
                        registro.user_id,
                        registro.obra_planificada_id,
                        registro.fecha,
                        current_user.id,
                        "Confirmar falta: se mantiene la planificación",
                    )
            registro.estado = ESTADO_FALTA

        else:
            return jsonify({'success': False, 'error': translate('Acción no reconocida')}), 400

        registro.notas_resolucion = _detalle_resolucion_fichaje(
            registro, accion, estado_anterior=estado_anterior
        )
        if notas_desasign and accion == 'borrar_planificacion':
            base = (registro.notas_resolucion or '').strip()
            comentario = f"Comentario: {notas_desasign}"
            registro.notas_resolucion = (
                f"{base} {comentario}".strip() if base else comentario
            )

        _cerrar_hermanos_placeholder(
            registro, accion, estado_anterior=estado_anterior or estado_previo
        )

        # Libro legal: solo registrar reimputación cuando hay cambio real de obra.
        # Aceptar un Paracaidista NO es un «cambio de obra»: el trabajador ya
        # fichó ahí; solo se valida a nivel de auditoría.
        try:
            from app.models import EVENTO_REASIGNACION_OBRA, ORIGEN_ADMIN
            from app.services.fichaje_ledger_service import (
                FichajeLedgerError,
                registrar_evento,
            )
            obra_ledger = registro.obra_real_id or registro.obra_planificada_id
            emitir_reasignacion = (
                accion == 'mover'
                or (
                    accion == 'anadir'
                    and estado_previo not in ('Paracaidista',)
                )
            )
            if obra_ledger and emitir_reasignacion:
                registrar_evento(
                    user_id=registro.user_id,
                    tipo=EVENTO_REASIGNACION_OBRA,
                    origen=ORIGEN_ADMIN,
                    fecha_laboral=registro.fecha,
                    autor_id=current_user.id,
                    obra_id=obra_ledger,
                    motivo=registro.notas_resolucion or f'Resolución auditoría: {accion}',
                )
        except FichajeLedgerError as ledger_err:
            from flask import current_app
            current_app.logger.warning(
                'Ledger no registró resolución fichaje %s: %s',
                registro.id, ledger_err,
            )

        from app.utils import register_log
        accion_titulo = ACCION_RESOLUCION_TITULOS.get(
            accion, accion.replace('_', ' ').title()
        )

        register_log(
            user_id=current_user.id,
            category='fichajes',
            action=f"Resolución de Fichaje: {accion_titulo}",
            detail=registro.notas_resolucion,
            target_user_id=registro.user_id,
            target_date=registro.fecha
        )
        # Al no reventar aquí, el commit funcionará y dejará el histórico
        db.session.commit()
        return jsonify({'success': True})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@sync_bp.route('/auditoria/reabrir', methods=['POST'])
@login_required
def reabrir_fichaje():
    """Restaura la clasificación previa de un registro resuelto (histórico).

    No deshace cambios de cuadrante (mover/añadir/borrar): solo vuelve a poner
    la incidencia en cola de auditoría con el estado que tenía.
    """
    from app import db
    from app.models import RegistroFichaje, Obra
    from app.utils import register_log
    from app.utils.timezone_utils import utc_now

    if current_user.role not in ['admin', 'jefe_obra', ROLE_LABORAL, ROLE_RRHH]:
        return jsonify({'success': False, 'error': translate('No autorizado')}), 403
    from app.services.fichaje_operario_service import tenant_muestra_auditoria_fichajes
    if not tenant_muestra_auditoria_fichajes():
        return jsonify({'success': False, 'error': translate('Acceso denegado.')}), 403
    if not can_resolve_fichajes(current_user):
        return jsonify({'success': False, 'error': translate('Resolución deshabilitada para este perfil.')}), 403

    data = request.get_json(silent=True) or {}
    registro_id = data.get('registro_id')
    registro = RegistroFichaje.query.get(registro_id)
    if not registro:
        return jsonify({'success': False, 'error': translate('Registro no encontrado')}), 404

    if current_user.role == 'jefe_obra':
        obras_del_jefe = [o.id for o in Obra.query.filter_by(jefe_obra_id=current_user.id).all()]
        if registro.obra_planificada_id not in obras_del_jefe and registro.obra_real_id not in obras_del_jefe:
            return jsonify({'success': False, 'error': translate('No tienes permisos sobre este registro.')}), 403

    if registro.estado not in _ESTADOS_RESUELTOS:
        return jsonify({'success': False, 'error': translate('Solo se pueden reabrir registros ya resueltos.')}), 400

    previo = (registro.estado_antes_resolucion or '').strip()
    if not previo or previo in _ESTADOS_RESUELTOS:
        return jsonify({
            'success': False,
            'error': translate('No hay clasificación previa guardada (decisiones antiguas no se pueden reabrir).'),
        }), 400

    try:
        fecha_aud_previa = registro.fecha_auditoria
        nota_previa = (registro.notas_resolucion or '').strip()

        registro.estado = previo
        registro.estado_antes_resolucion = None
        registro.notas_resolucion = (
            f'Reabierto → vuelve a «{previo}». '
            f'La clasificación se restaura; el cuadrante no se deshace automáticamente.'
            + (f' (Antes: {nota_previa})' if nota_previa else '')
        )
        registro.resuelto_por_id = current_user.id
        registro.fecha_auditoria = utc_now()
        if previo in ('Conflicto', 'Disputa'):
            from app.services.desvio_fichaje_service import limpiar_acks_desvio
            limpiar_acks_desvio(registro)
            if previo == 'Disputa':
                # Reabrir disputa → vuelve a Conflicto para que firmen de nuevo
                registro.estado = 'Conflicto'
                previo = 'Conflicto'

        _reabrir_hermanos_cerrados(registro, fecha_aud_previa)

        register_log(
            user_id=current_user.id,
            category='fichajes',
            action='Reabrir resolución de fichaje',
            detail=registro.notas_resolucion,
            target_user_id=registro.user_id,
            target_date=registro.fecha,
        )
        db.session.commit()
        return jsonify({
            'success': True,
            'estado': previo,
            'aviso': translate(
                'Clasificación restaurada. Si la resolución cambió el cuadrante '
                '(mover/añadir/borrar), revisa las asignaciones a mano.'
            ),
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


def _puede_editar_marcas():
    return (
        current_user.role in ('admin', ROLE_LABORAL, ROLE_RRHH)
        and can_resolve_fichajes(current_user)
    )


@sync_bp.route('/auditoria/marcas', methods=['GET'])
@login_required
def listar_marcas_dia():
    """Lista eventos del ledger de un trabajador/día (para corregir)."""
    if not _puede_editar_marcas():
        return jsonify({'success': False, 'error': translate('No autorizado')}), 403
    from datetime import datetime as dt
    from app.services.fichaje_admin_service import FichajeAdminError, listar_eventos_dia

    user_id = request.args.get('user_id', type=int)
    fecha_raw = (request.args.get('fecha') or '').strip()
    if not user_id or not fecha_raw:
        return jsonify({'success': False, 'error': translate('Indica trabajador y fecha.')}), 400
    try:
        fecha = dt.strptime(fecha_raw, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'success': False, 'error': translate('Fecha no válida.')}), 400
    try:
        eventos = listar_eventos_dia(user_id, fecha)
    except FichajeAdminError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400
    return jsonify({'success': True, 'eventos': eventos})


@sync_bp.route('/auditoria/marcas', methods=['POST'])
@login_required
def registrar_marca_auditoria():
    """Alta manual de entrada/salida/pausa (libro append-only + motivo)."""
    if not _puede_editar_marcas():
        return jsonify({'success': False, 'error': translate('No autorizado')}), 403
    from datetime import datetime as dt
    from app.services.fichaje_admin_service import (
        FichajeAdminError,
        registrar_marca_manual,
    )
    from app.utils import register_log

    data = request.get_json(silent=True) or {}
    fecha_lab = None
    if data.get('fecha_laboral'):
        try:
            fecha_lab = dt.strptime(data['fecha_laboral'], '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'success': False, 'error': translate('Fecha laboral no válida.')}), 400
    try:
        evento = registrar_marca_manual(
            user_id=data.get('user_id'),
            tipo=data.get('tipo'),
            ocurrido_en_local=data.get('ocurrido_en'),
            motivo=data.get('motivo'),
            autor_id=current_user.id,
            obra_id=data.get('obra_id') or None,
            fecha_laboral=fecha_lab,
            ip=request.remote_addr,
        )
        register_log(
            user_id=current_user.id,
            category='fichajes',
            action='Marca manual (admin)',
            detail=f"{evento.tipo} · motivo: {evento.motivo}",
            target_user_id=evento.user_id,
            target_date=evento.fecha_laboral,
        )
        db.session.commit()
        return jsonify({
            'success': True,
            'evento_id': evento.id,
            'secuencia': evento.secuencia,
        })
    except FichajeAdminError as exc:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(exc)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@sync_bp.route('/auditoria/marcas/corregir', methods=['POST'])
@login_required
def corregir_marca_auditoria():
    """Anula la marca original y registra la corregida (ambas quedan en el libro)."""
    if not _puede_editar_marcas():
        return jsonify({'success': False, 'error': translate('No autorizado')}), 403
    from app.services.fichaje_admin_service import FichajeAdminError, corregir_marca
    from app.utils import register_log

    data = request.get_json(silent=True) or {}
    try:
        evento = corregir_marca(
            evento_id=data.get('evento_id'),
            motivo=data.get('motivo'),
            autor_id=current_user.id,
            nuevo_ocurrido_en_local=data.get('ocurrido_en') or None,
            nueva_obra_id=data.get('obra_id'),
            ip=request.remote_addr,
        )
        register_log(
            user_id=current_user.id,
            category='fichajes',
            action='Corrección de marca (admin)',
            detail=f"Nueva secuencia #{evento.secuencia} · motivo: {evento.motivo}",
            target_user_id=evento.user_id,
            target_date=evento.fecha_laboral,
        )
        db.session.commit()
        return jsonify({'success': True, 'evento_id': evento.id})
    except FichajeAdminError as exc:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(exc)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@sync_bp.route('/auditoria/marcas/anular', methods=['POST'])
@login_required
def anular_marca_auditoria():
    """Anula una marca sin crear otra (queda la huella de anulación)."""
    if not _puede_editar_marcas():
        return jsonify({'success': False, 'error': translate('No autorizado')}), 403
    from app.services.fichaje_admin_service import FichajeAdminError, anular_marca
    from app.utils import register_log

    data = request.get_json(silent=True) or {}
    try:
        evento = anular_marca(
            evento_id=data.get('evento_id'),
            motivo=data.get('motivo'),
            autor_id=current_user.id,
        )
        register_log(
            user_id=current_user.id,
            category='fichajes',
            action='Anulación de marca (admin)',
            detail=f"Anulado evento {data.get('evento_id')} · motivo: {evento.motivo}",
            target_user_id=evento.user_id,
            target_date=evento.fecha_laboral,
        )
        db.session.commit()
        return jsonify({'success': True})
    except FichajeAdminError as exc:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(exc)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    
    
@sync_bp.route('/fichajes_manual', methods=['POST'])
@login_required
def sync_fichajes_manual():
    denied = _require_module_write('auditoria_fichajes')
    if denied:
        return denied

    try:
        data = request.get_json() or {}
        dias_atras = int(data.get('dias', 7))
        dias_atras = max(0, min(365, dias_atras))

        from app.services.sync_runner_service import run_fichajes_retro_sync
        run_fichajes_retro_sync(days=dias_atras, modo='Manual')

        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@sync_bp.route('/vehiculos_manual', methods=['POST'])
@login_required
def sync_vehiculos_manual():
    """Fuerza sync de flota + uso desde viajes tms.shipment (borra basura del rango)."""
    denied = _require_module_write('auditoria_vehiculos')
    if denied:
        return denied
    if not _require_odoo_module():
        return jsonify({'success': False, 'error': translate('Módulo Odoo no habilitado')}), 403
    try:
        from app.services.vehicle_sync_service import (
            apply_diff, purge_registros_uso, sync_odometros,
        )
        from app.utils.timezone_utils import today_local
        from datetime import timedelta

        data = request.get_json() or {}
        hoy = today_local()
        fecha_desde = data.get('fecha_desde')
        fecha_hasta = data.get('fecha_hasta')
        limpiar_todo = bool(data.get('limpiar_todo'))
        if not fecha_desde and data.get('dias') is not None:
            dias = max(0, min(365, int(data.get('dias', 7))))
            fecha_hasta = hoy.isoformat()
            fecha_desde = (hoy - timedelta(days=dias)).isoformat()
        if not fecha_desde:
            fecha_desde = hoy.isoformat()
        if not fecha_hasta:
            fecha_hasta = fecha_desde

        purged = 0
        if limpiar_todo:
            purged = purge_registros_uso()

        fleet = apply_diff(modo='Manual')
        odo = sync_odometros(
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
            modo='Manual',
            limpiar_rango=True,
        )
        return jsonify({
            'success': True,
            'fleet': fleet,
            'odometros': odo,
            'purgados_totales': purged,
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@sync_bp.route('/preview_vehiculos', methods=['GET'])
@login_required
@roles_required(ROLE_ADMIN)
def preview_vehiculos():
    if not _require_odoo_module():
        return redirect(url_for('admin.panel'))
    try:
        from app.services.vehicle_sync_service import preview_diff
        preview = preview_diff()
        return render_template(
            'sync/preview_vehiculos.html',
            preview=preview,
            diff=preview.get('diff') or {},
        )
    except Exception as e:
        flash(f"Error obteniendo diff de vehículos: {e}", "danger")
        return redirect(url_for('sync.odoo_panel'))


@sync_bp.route('/commit_vehiculos', methods=['POST'])
@login_required
@roles_required(ROLE_ADMIN)
def commit_vehiculos():
    if not _require_odoo_module():
        return jsonify({'success': False, 'error': translate('Módulo Odoo no habilitado')}), 403
    try:
        from app.services.vehicle_sync_service import apply_diff
        data = request.get_json() or {}
        # Si el cliente manda buckets, reconstruimos; si no, re-diff desde Odoo
        if 'nuevos' in data or 'actualizados' in data:
            diff = {
                'nuevos': data.get('nuevos', []),
                'actualizados': data.get('actualizados', []),
                'sin_cambios': data.get('sin_cambios', []),
                'error': None,
            }
            result = apply_diff(diff=diff, modo='Manual')
        else:
            result = apply_diff(modo='Manual')
        if result.get('error'):
            return jsonify({'success': False, 'error': result['error']}), 400
        return jsonify({'success': True, **result})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@sync_bp.route('/auditoria-vehiculos')
@login_required
@roles_required(ROLE_ADMIN, ROLE_LABORAL)
def auditoria_vehiculos():
    """Auditoría informativa plan vs odómetro Odoo (sin acciones de resolución)."""
    if not _require_auditoria_vehiculos():
        from app.services.user_home_service import home_url_for_user
        dest = home_url_for_user(current_user) or url_for('auth.login')
        return redirect(dest)

    from app.services.permission_service import user_can
    from app.utils.timezone_utils import today_local

    hoy = today_local()
    fecha_desde_str = (request.args.get('fecha_desde') or '').strip()
    fecha_hasta_str = (request.args.get('fecha_hasta') or '').strip()
    estado = (request.args.get('estado') or 'all').strip()
    orden = (request.args.get('orden') or 'fecha_desc').strip()
    search = (request.args.get('q') or '').strip().lower()

    def _parse_iso_date(raw, default):
        if not raw:
            return default
        try:
            return datetime.strptime(raw, '%Y-%m-%d').date()
        except ValueError:
            return default

    fecha_hasta = _parse_iso_date(fecha_hasta_str, hoy)
    fecha_desde = _parse_iso_date(fecha_desde_str, hoy - timedelta(days=7))
    if fecha_hasta < fecha_desde:
        fecha_desde, fecha_hasta = fecha_hasta, fecha_desde

    registros = (
        RegistroOdometro.query
        .options(
            joinedload(RegistroOdometro.vehiculo),
            joinedload(RegistroOdometro.planned_user),
        )
        .filter(
            RegistroOdometro.fecha >= fecha_desde,
            RegistroOdometro.fecha <= fecha_hasta,
        )
        .all()
    )

    # Antes de filtrar por pestaña: un mismatch explica el “sin km” del planificado.
    mismatch_en_rango = [r for r in registros if r.estado == 'mismatch_driver']

    if estado in {'mismatch_driver', 'sin_km', 'sin_planificar', 'ok'}:
        registros = [r for r in registros if r.estado == estado]

    if search:
        def _match_text(reg):
            values = [
                reg.vehiculo.matricula if reg.vehiculo else '',
                reg.vehiculo.nombre if reg.vehiculo else '',
                reg.odoo_driver_name or '',
                reg.planned_user.name if reg.planned_user else '',
                reg.planned_user.lastname if reg.planned_user else '',
                reg.estado or '',
            ]
            haystack = ' '.join(v for v in values if v).lower()
            return search in haystack

        registros = [r for r in registros if _match_text(r)]

    sorters = {
        'fecha_desc': lambda r: (r.fecha, r.id),
        'fecha_asc': lambda r: (r.fecha, r.id),
        'vehiculo_asc': lambda r: (
            ((r.vehiculo.matricula if r.vehiculo else '') or (r.vehiculo.nombre if r.vehiculo else '') or '').lower(),
            r.fecha,
            r.id,
        ),
        'vehiculo_desc': lambda r: (
            ((r.vehiculo.matricula if r.vehiculo else '') or (r.vehiculo.nombre if r.vehiculo else '') or '').lower(),
            r.fecha,
            r.id,
        ),
        'km_desc': lambda r: (r.valor if r.valor is not None else -1, r.fecha, r.id),
        'km_asc': lambda r: (r.valor if r.valor is not None else -1, r.fecha, r.id),
        'estado_asc': lambda r: ((r.estado or '').lower(), r.fecha, r.id),
        'estado_desc': lambda r: ((r.estado or '').lower(), r.fecha, r.id),
    }
    reverse = orden in {'fecha_desc', 'vehiculo_desc', 'km_desc', 'estado_desc'}
    registros = sorted(registros, key=sorters.get(orden, sorters['fecha_desc']), reverse=reverse)

    from app.services.vehicle_anomaly_service import (
        detect_cross_vehicle_reports,
        detect_odometer_jumps,
        detect_vehicle_on_leave,
        detect_viaje_desvios,
        filter_sin_km_explicados_por_mismatch,
        filter_sin_km_solo_pasados,
        get_desvio_thresholds,
        get_odometer_jump_thresholds,
        get_vistas_map,
        partition_anomalias,
    )

    mismatch = [r for r in registros if r.estado == 'mismatch_driver']
    sin_km = filter_sin_km_solo_pasados(
        filter_sin_km_explicados_por_mismatch(
            [r for r in registros if r.estado == 'sin_km'],
            mismatch_en_rango,
        ),
        hoy,
    )
    sin_plan = [r for r in registros if r.estado == 'sin_planificar']
    ok_hist = [r for r in registros if r.estado == 'ok']

    thresholds = get_odometer_jump_thresholds()
    umbrales_desvio = get_desvio_thresholds()
    saltos = detect_odometer_jumps(fecha_desde, fecha_hasta, thresholds=thresholds)
    vehiculo_distinto = detect_cross_vehicle_reports(fecha_desde, fecha_hasta)
    vehiculo_en_ausencia = detect_vehicle_on_leave(fecha_desde, fecha_hasta)
    desvios = detect_viaje_desvios(fecha_desde, fecha_hasta, thresholds=umbrales_desvio)

    if search:
        def _jump_match(j):
            v = j.get('vehiculo')
            values = [
                v.matricula if v else '',
                v.nombre if v else '',
                j.get('conductor_odoo') or '',
                (j['planned_user'].name if j.get('planned_user') else ''),
                (j['planned_user'].lastname if j.get('planned_user') else ''),
                ' '.join(j.get('motivos') or []),
            ]
            return search in ' '.join(x for x in values if x).lower()

        def _cross_match(a):
            values = [
                a['user'].name if a.get('user') else '',
                a['user'].lastname if a.get('user') else '',
                a['vehiculo_planificado'].label() if a.get('vehiculo_planificado') else '',
                a['vehiculo_reportado'].label() if a.get('vehiculo_reportado') else '',
                a.get('conductor_odoo') or '',
            ]
            return search in ' '.join(x for x in values if x).lower()

        def _leave_match(a):
            values = [
                a['user'].name if a.get('user') else '',
                a['user'].lastname if a.get('user') else '',
                a['vehiculo'].label() if a.get('vehiculo') else '',
                a.get('conductor_odoo') or '',
                a.get('ausencia_tipo') or '',
                a.get('fuente') or '',
            ]
            return search in ' '.join(x for x in values if x).lower()

        def _desvio_match(a):
            v = a.get('vehiculo')
            pu = a.get('planned_user')
            values = [
                v.matricula if v else '',
                v.nombre if v else '',
                a.get('conductor_odoo') or '',
                a.get('viaje_code') or '',
                pu.name if pu else '',
                pu.lastname if pu else '',
            ]
            return search in ' '.join(x for x in values if x).lower()

        saltos = [j for j in saltos if _jump_match(j)]
        vehiculo_distinto = [a for a in vehiculo_distinto if _cross_match(a)]
        vehiculo_en_ausencia = [a for a in vehiculo_en_ausencia if _leave_match(a)]
        desvios = [a for a in desvios if _desvio_match(a)]

    if estado == 'salto_km':
        mismatch, sin_km, sin_plan, ok_hist, vehiculo_distinto, vehiculo_en_ausencia, desvios = (
            [], [], [], [], [], [], []
        )
    elif estado == 'vehiculo_distinto':
        mismatch, sin_km, sin_plan, ok_hist, saltos, vehiculo_en_ausencia, desvios = (
            [], [], [], [], [], [], []
        )
    elif estado == 'en_ausencia':
        mismatch, sin_km, sin_plan, ok_hist, saltos, vehiculo_distinto, desvios = (
            [], [], [], [], [], [], []
        )
    elif estado == 'desvio':
        mismatch, sin_km, sin_plan, ok_hist, saltos, vehiculo_distinto, vehiculo_en_ausencia = (
            [], [], [], [], [], [], []
        )
    elif estado in {'mismatch_driver', 'sin_km', 'sin_planificar', 'ok'}:
        saltos, vehiculo_distinto, vehiculo_en_ausencia, desvios = [], [], [], []

    # Partición informativa pendientes vs visto (no altera detección)
    vistas_map = get_vistas_map([
        'salto', 'cross', 'leave', 'desvio', 'mismatch', 'sin_km', 'sin_plan',
    ])
    saltos, saltos_visto = partition_anomalias('salto', saltos, vistas_map)
    desvios, desvios_visto = partition_anomalias('desvio', desvios, vistas_map)
    vehiculo_en_ausencia, vehiculo_en_ausencia_visto = partition_anomalias(
        'leave', vehiculo_en_ausencia, vistas_map
    )
    vehiculo_distinto, vehiculo_distinto_visto = partition_anomalias(
        'cross', vehiculo_distinto, vistas_map
    )
    mismatch, mismatch_visto = partition_anomalias('mismatch', mismatch, vistas_map)
    sin_km, sin_km_visto = partition_anomalias('sin_km', sin_km, vistas_map)
    sin_plan, sin_plan_visto = partition_anomalias('sin_plan', sin_plan, vistas_map)

    return render_template(
        'sync/auditoria_vehiculos.html',
        mismatch=mismatch,
        mismatch_visto=mismatch_visto,
        sin_km=sin_km,
        sin_km_visto=sin_km_visto,
        sin_planificar=sin_plan,
        sin_planificar_visto=sin_plan_visto,
        historial_ok=ok_hist,
        saltos=saltos,
        saltos_visto=saltos_visto,
        vehiculo_distinto=vehiculo_distinto,
        vehiculo_distinto_visto=vehiculo_distinto_visto,
        vehiculo_en_ausencia=vehiculo_en_ausencia,
        vehiculo_en_ausencia_visto=vehiculo_en_ausencia_visto,
        desvios=desvios,
        desvios_visto=desvios_visto,
        umbrales_salto=thresholds,
        umbrales_desvio=umbrales_desvio,
        umbral_desvio=max(umbrales_desvio['max_pct'], umbrales_desvio['min_pct']),
        fecha_desde_default=fecha_desde.isoformat(),
        fecha_hasta_default=fecha_hasta.isoformat(),
        filtros={
            'estado': estado,
            'orden': orden,
            'q': request.args.get('q', '').strip(),
        },
        total_filtrado=(
            len(mismatch) + len(mismatch_visto)
            + len(sin_km) + len(sin_km_visto)
            + len(sin_plan) + len(sin_plan_visto)
            + len(ok_hist)
            + (len(saltos) + len(saltos_visto) if estado in ('all', 'salto_km') else 0)
            + (len(vehiculo_distinto) + len(vehiculo_distinto_visto)
               if estado in ('all', 'vehiculo_distinto') else 0)
            + (len(vehiculo_en_ausencia) + len(vehiculo_en_ausencia_visto)
               if estado in ('all', 'en_ausencia') else 0)
            + (len(desvios) + len(desvios_visto) if estado in ('all', 'desvio') else 0)
        ),
        total_ok=len(ok_hist),
        total_pendientes=(
            len(saltos) + len(desvios) + len(vehiculo_en_ausencia)
            + len(vehiculo_distinto) + len(mismatch) + len(sin_km) + len(sin_plan)
        ),
        can_sync_vehiculos=(
            user_can(current_user, 'auditoria_vehiculos', 'w')
            or user_can(current_user, 'sync_odoo', 'w')
        ),
    )


@sync_bp.route('/auditoria-vehiculos/visto', methods=['POST'])
@login_required
@roles_required(ROLE_ADMIN, ROLE_LABORAL)
def auditoria_vehiculos_visto():
    """Marca una anomalía de flota como vista (informativo; no resuelve)."""
    if not _require_auditoria_vehiculos():
        return jsonify({'success': False, 'error': translate('Módulo Odoo no habilitado')}), 403

    data = request.get_json(silent=True) or {}
    kind = (data.get('kind') or request.form.get('kind') or '').strip().lower()
    clave = (data.get('clave') or request.form.get('clave') or '').strip()
    if not kind or not clave:
        return jsonify({'success': False, 'error': translate('Faltan kind y clave')}), 400

    try:
        from app.services.vehicle_anomaly_service import marcar_anomalia_vista
        row = marcar_anomalia_vista(kind, clave, current_user.id)
        return jsonify({
            'success': True,
            'kind': row.kind,
            'clave': row.clave,
            'visto_en': row.visto_en.isoformat() if row.visto_en else None,
        })
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@sync_bp.route('/conciliacion')
@login_required
@roles_required(ROLE_ADMIN)
def conciliacion_personal():
    """UI de conciliación externo↔interno (vínculo Odoo / código asistencia)."""
    if not _require_odoo_module():
        return redirect(url_for('admin.panel'))
    from app.services.permission_service import user_can
    from app.services.personal_conciliation_service import get_conciliation_summary

    if not user_can(current_user, 'sync_odoo', 'r'):
        flash(translate('Acceso denegado.'), 'danger')
        return redirect(url_for('main.dashboard'))

    summary = get_conciliation_summary()
    return render_template(
        'sync/conciliacion_personal.html',
        candidates=summary['candidates'],
        candidates_maintained=summary.get('candidates_maintained') or [],
        candidates_count=summary['candidates_count'],
        internal_companies=summary['internal_companies'],
        companies=summary.get('companies') or [],
        plantilla_users=summary.get('plantilla_users') or [],
        log_entries=summary.get('log_entries') or [],
        can_write=user_can(current_user, 'sync_odoo', 'w'),
    )


@sync_bp.route('/conciliacion/create-user', methods=['POST'])
@login_required
@roles_required(ROLE_ADMIN)
def conciliacion_create_user():
    from app.services.permission_service import user_can
    from app.services.personal_conciliation_service import create_stub_user
    from app.services.plan_service import PlanLimitError
    if not user_can(current_user, 'sync_odoo', 'w'):
        return jsonify({'success': False, 'error': translate('No autorizado')}), 403
    data = request.get_json(silent=True) or {}
    try:
        result = create_stub_user(
            name=data.get('name'),
            lastname=data.get('lastname'),
            company_id=int(data.get('company_id')),
            dni=data.get('dni'),
            email=data.get('email'),
            actor=current_user,
        )
        return jsonify({'success': True, **result})
    except PlanLimitError as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 403
    except (TypeError, ValueError) as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@sync_bp.route('/conciliacion/search', methods=['GET'])
@login_required
@roles_required(ROLE_ADMIN)
def conciliacion_search():
    from app.services.permission_service import user_can
    from app.services.personal_conciliation_service import search_users
    if not user_can(current_user, 'sync_odoo', 'r'):
        return jsonify({'success': False, 'error': translate('No autorizado')}), 403
    q = request.args.get('q', '')
    return jsonify({'success': True, 'users': search_users(q)})


@sync_bp.route('/conciliacion/odoo-dni', methods=['GET'])
@login_required
@roles_required(ROLE_ADMIN)
def conciliacion_odoo_dni():
    """Busca en Odoo personas (HR + contactos) por DNI, código o nombre."""
    from flask import current_app
    from app.services.permission_service import user_can
    from app.services.personal_conciliation_service import search_odoo_people
    if not user_can(current_user, 'sync_odoo', 'r'):
        return jsonify({'success': False, 'error': translate('No autorizado')}), 403
    q = (request.args.get('q') or request.args.get('dni') or '').strip()
    if len(q) < 3:
        return jsonify({
            'success': False,
            'error': translate('Indica al menos 3 caracteres (DNI, código o nombre)'),
        }), 400
    try:
        hits = search_odoo_people(q)
        return jsonify({'success': True, 'people': hits, 'count': len(hits)})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        current_app.logger.exception('conciliacion_odoo_dni falló')
        return jsonify({'success': False, 'error': str(e)}), 500


@sync_bp.route('/conciliacion/link-odoo', methods=['POST'])
@login_required
@roles_required(ROLE_ADMIN)
def conciliacion_link_odoo():
    from app.services.permission_service import user_can
    from app.services.personal_conciliation_service import link_local_to_odoo
    if not user_can(current_user, 'sync_odoo', 'w'):
        return jsonify({'success': False, 'error': translate('No autorizado')}), 403
    data = request.get_json(silent=True) or {}
    try:
        links = data.get('odoo_links') or []
        extra = []
        primary_id = data.get('odoo_id')
        primary_source = data.get('source') or 'employee'
        primary_barcode = data.get('barcode')
        if links:
            primary = links[0]
            primary_id = primary.get('odoo_id')
            primary_source = primary.get('source') or 'employee'
            primary_barcode = primary.get('barcode')
            extra = links[1:]
        result = link_local_to_odoo(
            int(data.get('local_user_id')),
            primary_id,
            source=primary_source,
            force=bool(data.get('force')),
            actor=current_user,
            barcode=primary_barcode,
            extra_links=extra,
        )
        return jsonify({'success': True, **result})
    except (TypeError, ValueError) as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@sync_bp.route('/conciliacion/maintain', methods=['POST'])
@login_required
@roles_required(ROLE_ADMIN)
def conciliacion_maintain():
    from app.services.permission_service import user_can
    from app.services.personal_conciliation_service import maintain_group
    if not user_can(current_user, 'sync_odoo', 'w'):
        return jsonify({'success': False, 'error': translate('No autorizado')}), 403
    data = request.get_json(silent=True) or {}
    try:
        result = maintain_group(
            data.get('user_ids') or [],
            barcode=data.get('barcode'),
            group_key=data.get('group_key'),
            actor=current_user,
        )
        return jsonify({'success': True, **result})
    except (TypeError, ValueError) as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@sync_bp.route('/conciliacion/undo', methods=['POST'])
@login_required
@roles_required(ROLE_ADMIN)
def conciliacion_undo():
    from app.services.permission_service import user_can
    from app.services.personal_conciliation_service import undo_log_entry
    if not user_can(current_user, 'sync_odoo', 'w'):
        return jsonify({'success': False, 'error': translate('No autorizado')}), 403
    data = request.get_json(silent=True) or {}
    try:
        entry = undo_log_entry(data.get('entry_id'), actor=current_user)
        return jsonify({'success': True, 'entry': entry})
    except (TypeError, ValueError) as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@sync_bp.route('/conciliacion/merge', methods=['POST'])
@login_required
@roles_required(ROLE_ADMIN)
def conciliacion_merge():
    from app.services.permission_service import user_can
    from app.services.personal_conciliation_service import merge_users
    if not user_can(current_user, 'sync_odoo', 'w'):
        return jsonify({'success': False, 'error': translate('No autorizado')}), 403
    data = request.get_json(silent=True) or {}
    try:
        keep_id = int(data.get('keep_id'))
        absorb_id = int(data.get('absorb_id'))
        result = merge_users(
            keep_id, absorb_id,
            actor_id=current_user.id,
            actor=current_user,
        )
        return jsonify({'success': True, **result})
    except (TypeError, ValueError) as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@sync_bp.route('/conciliacion/promote', methods=['POST'])
@login_required
@roles_required(ROLE_ADMIN)
def conciliacion_promote():
    from app.services.permission_service import user_can
    from app.services.personal_conciliation_service import promote_as_internal
    if not user_can(current_user, 'sync_odoo', 'w'):
        return jsonify({'success': False, 'error': translate('No autorizado')}), 403
    data = request.get_json(silent=True) or {}
    try:
        user_id = int(data.get('user_id'))
        company_id = data.get('company_id')
        company_id = int(company_id) if company_id not in (None, '') else None
        card = promote_as_internal(user_id, company_id=company_id, actor=current_user)
        return jsonify({'success': True, 'user': card})
    except (TypeError, ValueError) as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@sync_bp.route('/timeline_dia/<int:user_id>/<string:fecha_str>', methods=['GET'])
@login_required
def get_timeline_dia(user_id, fecha_str):
    """Compatibilidad con auditoría de fichajes. Delega en el servicio compartido."""
    from flask import current_app
    from app.services.person_day_timeline_service import build_person_day_timeline

    if current_user.role not in ['admin', 'jefe_obra', ROLE_LABORAL, ROLE_RRHH]:
        return jsonify({'success': False, 'error': translate('Acceso denegado')}), 403

    try:
        data = build_person_day_timeline(user_id, fecha_str)
    except Exception:
        current_app.logger.exception(
            'timeline_dia falló user_id=%s fecha=%s', user_id, fecha_str
        )
        return jsonify({
            'success': False,
            'error': translate('No se pudo cargar el historial.'),
        }), 500
    if not data:
        return jsonify({'success': False, 'error': translate('Operario no encontrado')}), 404
    return jsonify(data)
