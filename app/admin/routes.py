# app/admin/routes.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app, g, session
from app.services.i18n_service import translate
from flask_login import login_required, current_user
from sqlalchemy import or_, and_, func
from app.models import (
    User,
    Obra,
    Asignacion,
    ROLE_ADMIN,
    ROLE_JEFE,
    ROLE_OPERARIO,
    ROLE_LABORAL,
    ROLE_RRHH,
    Company,
    Solicitud,
    SolicitudVehiculo,
    Vehiculo,
)
from app import db
from werkzeug.security import generate_password_hash
from datetime import datetime, timedelta, date


from app.services.solicitud_service import (
    update_solicitudes_for_assignment,
    get_solicitud_notas,
    get_solicitud_auto_cierre_texto,
    compute_generica_coverage,
    get_solicitud_valid_dates,
    _recalculate_solicitud_coverage,
    sweep_open_solicitudes_actionable,
    iter_solicitud_calendar_spans,
)
from app.services.assignment_service import process_assignment_action
from app.services.core_assignment_service import CoreAssignmentService
from app.decorators import roles_required, permission_required
from itsdangerous import URLSafeTimedSerializer
import os
from app.services.import_service import (
    allowed_import_file,
    save_import_upload,
    resolve_import_path,
    cleanup_import_file,
    preview_import,
    commit_import,
    ENTITY_LABELS,
)
from app.models import Rating


from app.services.dashboard_service import get_dashboard_data, parse_date
from app.services.entity_panel_service import (
    get_obra_panel_stats,
    get_worker_panel_stats,
    get_company_panel_stats,
    get_worker_vehicle_rows,
    get_worker_vehicle_today,
    get_obra_vehicle_rows,
    get_vehicle_panel_stats,
    get_vehicle_history_rows,
)
from app.services.permission_service import (
    can_edit_planning_calendar,
    can_edit_vehicle_calendar,
    can_resolve_solicitudes_flota,
    can_resolve_solicitudes_personal,
    can_view_solicitudes_flota,
    can_view_solicitudes_personal,
    is_laboral,
    laboral_log_categories,
    user_can,
)
from app.services.panel_scope_service import (
    PANEL_PLANIFICADOR,
    PANEL_SOLICITUDES,
    apply_obra_scope_filter,
    solicitud_obra_in_scope,
    user_custody_jefe_ids,
    user_panel_mode,
)

from app.services.email_service import notificar_resolucion_solicitud, notificar_movimiento_admin_a_jo
# Definición del blueprint de admin
admin_bp = Blueprint("admin", __name__, url_prefix="/admin")
ALLOWED_EXTENSIONS = {"xlsx", "xls", "csv"}


@admin_bp.before_request
def _enforce_admin_module_permissions():
    from app.services.permission_guard import enforce_admin_permissions
    return enforce_admin_permissions()

IMPORT_WIZARD_CONFIG = {
    "obras": {
        "title": "Importar obras",
        "subtitle": "Sube un Excel o CSV para crear varias obras de una vez.",
        "intro_lead": (
            "Desde aquí cargas de golpe el listado de obras de tu empresa. "
            "No hace falta crearlas una a una: el asistente lee el fichero, "
            "mapea las columnas y te muestra una vista previa antes de guardar."
        ),
        "required_hint": "Obligatorio: Nombre. Opcional: Código, Dirección, Fechas.",
        "icon": "fa-hard-hat",
        "upload_endpoint": "admin.import_obras",
        "preview_endpoint": "admin.import_obras_preview",
        "confirm_endpoint": "admin.import_obras_confirm",
        "back_endpoint": "admin.obras_list",
        "back_label": "Volver al listado",
        "success_endpoint": "admin.obras_detailed",
        "success_label": "Ir a obras",
        "help_html": """
<ul>
  <li><strong>Obligatorio:</strong> una columna de <strong>Nombre</strong> de la obra.</li>
  <li><strong>Opcionales:</strong> Código, Dirección, Fecha de inicio y Fecha de fin.</li>
  <li><strong>Sin fechas:</strong> se pone <strong>hoy</strong> como inicio y <strong>un año después</strong> como fin.
      Si el Excel ya trae fechas (aunque sean del pasado), se respetan tal cual.</li>
  <li><strong>Sin código:</strong> la obra se crea sin código (puedes asignarlo después en la ficha).</li>
</ul>
<p class="import-help-note">Formatos: .xlsx o .csv. En el siguiente paso podrás corregir el mapeo de columnas.</p>
""",
    },
    "users": {
        "title": "Importar personal",
        "subtitle": "Sube un Excel o CSV para dar de alta usuarios.",
        "intro_lead": (
            "Carga de golpe tu plantilla (interna o externa). "
            "Revisarás el mapeo y una vista previa antes de crear a nadie."
        ),
        "required_hint": "Obligatorio: Nombre, Apellidos, DNI, Email. Recomendado: Empresa (externos), Rol.",
        "icon": "fa-users",
        "upload_endpoint": "admin.import_users",
        "preview_endpoint": "admin.import_users_preview",
        "confirm_endpoint": "admin.import_users_confirm",
        "back_endpoint": "admin.personal",
        "back_label": "Volver a personal",
        "success_endpoint": "admin.personal",
        "success_label": "Ir a personal",
        "help_html": """
<ul>
  <li><strong>Obligatorias:</strong> Nombre, Apellidos, DNI y Email.</li>
  <li><strong>Recomendadas:</strong> Rol y, si son externos, Empresa.</li>
  <li><strong>Empresa / subcontrata:</strong> en personal externo se busca o crea una empresa con ese nombre.
      Si dos personas son de la misma subcontrata, el nombre debe ser <strong>exactamente igual</strong>.</li>
  <li><strong>Sin rol:</strong> se asume operario. El PIN puedes activarlo después en Trabajadores.</li>
</ul>
<p class="import-help-note">Formatos: .xlsx o .csv. En el siguiente paso podrás corregir el mapeo.</p>
""",
    },
    "companies": {
        "title": "Importar subcontratas",
        "subtitle": "Sube un Excel o CSV para dar de alta empresas externas.",
        "intro_lead": (
            "Da de alta las empresas externas / subcontratas con las que trabajas. "
            "Así podrás vincular personal externo a cada una."
        ),
        "required_hint": "Obligatorio: Nombre. Opcional: NIF, Código, Gremio, Email, Descripción.",
        "icon": "fa-building",
        "upload_endpoint": "admin.import_companies",
        "preview_endpoint": "admin.import_companies_preview",
        "confirm_endpoint": "admin.import_companies_confirm",
        "back_endpoint": "admin.companies",
        "back_label": "Volver a subcontratas",
        "success_endpoint": "admin.companies",
        "success_label": "Ir a subcontratas",
        "help_html": """
<ul>
  <li><strong>Obligatorio:</strong> Nombre de la subcontrata / empresa externa.</li>
  <li><strong>Opcionales:</strong> NIF, Código, Gremio, Email, Descripción.</li>
  <li><strong>Mismo nombre:</strong> si ya existe una empresa con ese nombre, la fila se marca como duplicada.
      Usa siempre el mismo nombre para la misma subcontrata.</li>
</ul>
<p class="import-help-note">Formatos: .xlsx o .csv. En el siguiente paso podrás corregir el mapeo.</p>
""",
    },
}


@admin_bp.before_request
def _bloquear_operario_en_admin():
    """El operario no entra al panel de oficina (ni por PIN ni por portal web)."""
    if current_user.is_authenticated and current_user.role == ROLE_OPERARIO:
        from app.auth.routes import destino_portal_operario
        flash(translate('Tu perfil no tiene acceso al panel de administración.'), 'warning')
        return redirect(destino_portal_operario(current_user))


_RETURN_TO_ENDPOINTS = {
    'tablero': 'admin.obras_detailed',
    'planificador': 'admin.planificador_jo',
    'personal': 'admin.personal',
    'solicitudes': 'admin.solicitudes_list',
    'coches_libres': 'admin.vehiculos_libres',
    'vehiculos': 'admin.vehiculos',
}


def _return_to_key():
    key = (request.values.get('next') or '').strip()
    return key if key in _RETURN_TO_ENDPOINTS else ''


def _create_user_default_role():
    role = (request.values.get('role') or '').strip()
    try:
        from app.services.role_registry_service import valid_role_keys
        if role in valid_role_keys():
            return role
    except Exception:
        if role in (ROLE_OPERARIO, ROLE_JEFE, ROLE_RRHH, ROLE_LABORAL, ROLE_ADMIN):
            return role
    return ''


def _url_with_return_to(endpoint, **kwargs):
    key = _return_to_key()
    if key:
        kwargs['next'] = key
    if endpoint == 'admin.create_user':
        role = _create_user_default_role()
        if role:
            kwargs.setdefault('role', role)
    return url_for(endpoint, **kwargs)


def _redirect_after_create(default_endpoint, **url_kwargs):
    key = _return_to_key()
    if key:
        extra = {}
        if key == 'tablero':
            extra = {
                k: v for k, v in url_kwargs.items()
                if k in ('selected_date', 'obra')
            }
        return redirect(url_for(_RETURN_TO_ENDPOINTS[key], **extra))
    return redirect(url_for(default_endpoint, **url_kwargs))


def _cancel_url_after_create(default_endpoint, **url_kwargs):
    from app.utils.nav_back import resolve_back_url
    key = _return_to_key()
    if key:
        return url_for(_RETURN_TO_ENDPOINTS[key], **url_kwargs)
    return resolve_back_url(default_endpoint, **url_kwargs)


def allowed_file(filename):
    return allowed_import_file(filename)


def _import_session_key(entity_type):
    return f"import_{entity_type}"


def _import_nav_key(entity_type):
    return f"import_{entity_type}_nav"


def _import_from_onboarding() -> bool:
    """True si el wizard se abrió desde Primeros pasos."""
    raw = (
        request.args.get('desde')
        or request.form.get('desde')
        or ''
    ).strip().lower()
    if raw in ('primeros-pasos', 'primeros_pasos', 'onboarding', '1'):
        return True
    return False


def _apply_import_nav_context(entity_type, cfg: dict) -> dict:
    """Ajusta Volver / éxito si venimos de primeros pasos."""
    cfg = dict(cfg)
    nav = session.get(_import_nav_key(entity_type)) or {}
    from_onb = bool(nav.get('from_onboarding')) or _import_from_onboarding()
    if from_onb:
        session[_import_nav_key(entity_type)] = {'from_onboarding': True}
        session.modified = True
        cfg['back_endpoint'] = 'admin.primeros_pasos'
        cfg['back_label'] = 'Volver a primeros pasos'
        cfg['success_endpoint'] = 'admin.primeros_pasos'
        cfg['success_label'] = 'Volver a primeros pasos'
        cfg['from_onboarding'] = True
    else:
        cfg['from_onboarding'] = bool(nav.get('from_onboarding'))
        if cfg['from_onboarding']:
            cfg['back_endpoint'] = 'admin.primeros_pasos'
            cfg['back_label'] = 'Volver a primeros pasos'
            cfg['success_endpoint'] = 'admin.primeros_pasos'
            cfg['success_label'] = 'Volver a primeros pasos'
    return cfg


def _clear_import_session(entity_type):
    data = session.pop(_import_session_key(entity_type), None)
    session.pop(_import_session_key(entity_type) + '_opts', None)
    # Conservar nav (desde primeros pasos) entre reintentos del mismo flujo;
    # se limpia al salir al listado normal o al terminar con éxito.
    if data:
        cleanup_import_file(data.get("token", ""), data.get("ext", "xlsx"))


def _store_import_upload(entity_type, file_storage):
    token, ext = save_import_upload(file_storage)
    session[_import_session_key(entity_type)] = {
        "token": token,
        "ext": ext,
        "original_name": file_storage.filename,
        "column_map": None,
    }
    session.modified = True
    return token, ext


def _load_import_path(entity_type):
    data = session.get(_import_session_key(entity_type))
    if not data or not data.get("token"):
        return None, None
    path = resolve_import_path(data["token"], data.get("ext", "xlsx"))
    return path, data


def _column_map_from_form(_entity_type=None):
    """Lee map[campo]=columna desde el formulario de remapeo."""
    prefix = "map_"
    column_map = {}
    for key, value in request.form.items():
        if key.startswith(prefix):
            field_key = key[len(prefix):]
            column_map[field_key] = value if value and value != "__none__" else None
    return column_map or None


def _render_import_upload(entity_type):
    cfg = IMPORT_WIZARD_CONFIG[entity_type]
    import_mode = None
    if entity_type == 'users':
        import_mode = (request.args.get('modo') or request.form.get('modo') or '').strip().lower()
        if import_mode not in ('internos', 'externos'):
            import_mode = 'externos'

    from_onb = _import_from_onboarding()
    _clear_import_session(entity_type)
    if from_onb:
        session[_import_nav_key(entity_type)] = {'from_onboarding': True}
        session.modified = True
    else:
        session.pop(_import_nav_key(entity_type), None)

    cfg = _apply_import_nav_context(entity_type, cfg)

    external_companies = []
    internal_company = None
    if entity_type == 'users':
        session[_import_session_key(entity_type) + '_opts'] = {'mode': import_mode}
        session.modified = True
        from app.models import Company
        internal_company = Company.query.filter_by(is_internal=True).order_by(Company.id).first()
        external_companies = (
            Company.query.filter_by(is_internal=False)
            .order_by(Company.nombre)
            .all()
        )
        if import_mode == 'internos':
            cfg['title'] = 'Importar personal interno'
            cfg['subtitle'] = (
                'Todos se asignarán a la empresa interna'
                + (f' («{internal_company.nombre}»)' if internal_company else '')
                + '. La columna empresa del Excel se ignora.'
            )
        else:
            cfg['title'] = 'Importar personal externo'
            cfg['subtitle'] = (
                'Puedes forzar una empresa externa para todos, o dejar que se use/cree '
                'la del Excel.'
            )

    return render_template(
        "admin_import_wizard.html",
        entity_type=entity_type,
        entity_label=ENTITY_LABELS.get(entity_type, entity_type),
        cfg=cfg,
        step=1,
        import_mode=import_mode,
        internal_company=internal_company,
        external_companies=external_companies,
        from_onboarding=cfg.get('from_onboarding'),
    )


def _import_options_from_session(entity_type):
    opts = session.get(_import_session_key(entity_type) + '_opts') or {}
    mode = (opts.get('mode') or '').strip().lower() or None
    force = opts.get('force_company_id')
    try:
        force = int(force) if force not in (None, '', '0') else None
    except (TypeError, ValueError):
        force = None
    # PIN de fichaje: por defecto sí (correo con enlace para definirlo)
    assign_pin = opts.get('assign_pin')
    if assign_pin is None:
        from app.services.tenant_auth_policy import tenant_usa_acceso_pin
        assign_pin = tenant_usa_acceso_pin()
    notify_pin = opts.get('notify_pin')
    if notify_pin is None:
        notify_pin = True
    return {
        'mode': mode,
        'force_company_id': force,
        'assign_pin': bool(assign_pin),
        'notify_pin': bool(notify_pin),
    }


def _render_import_preview(entity_type, preview, column_map=None):
    cfg = _apply_import_nav_context(entity_type, IMPORT_WIZARD_CONFIG[entity_type])
    data = session.get(_import_session_key(entity_type)) or {}
    import_mode = None
    external_companies = []
    internal_company = None
    import_options = {}
    if entity_type == 'users':
        import_options = _import_options_from_session(entity_type)
        import_mode = import_options.get('mode')
        from app.models import Company
        internal_company = Company.query.filter_by(is_internal=True).order_by(Company.id).first()
        external_companies = (
            Company.query.filter_by(is_internal=False).order_by(Company.nombre).all()
        )
        internal = preview.get('_internal_rows') or []
        from app.services.import_service import annotate_user_rows_for_mode, _summarize_rows
        annotated = annotate_user_rows_for_mode(internal, import_options)
        preview = dict(preview)
        preview['_internal_rows'] = annotated
        public_rows = [
            {
                'row_number': r['row_number'],
                'status': r['status'],
                'messages': r.get('messages') or [],
                'data': r.get('data') or {},
            }
            for r in annotated
        ]
        preview['rows'] = public_rows
        preview['sample_rows'] = public_rows
        preview['summary'] = _summarize_rows(annotated)

    return render_template(
        "admin_import_wizard.html",
        entity_type=entity_type,
        entity_label=ENTITY_LABELS.get(entity_type, entity_type),
        cfg=cfg,
        preview=preview,
        column_map=column_map or preview.get("column_map") or {},
        columns=preview.get("columns") or [],
        fields=preview.get("fields") or [],
        original_name=data.get("original_name"),
        step=2,
        import_mode=import_mode,
        internal_company=internal_company,
        external_companies=external_companies,
        force_company_id=import_options.get('force_company_id') if entity_type == 'users' else None,
        assign_pin=import_options.get('assign_pin', True) if entity_type == 'users' else False,
        notify_pin=import_options.get('notify_pin', True) if entity_type == 'users' else False,
        from_onboarding=cfg.get('from_onboarding'),
    )


def _handle_import_upload_post(entity_type):
    file = request.files.get("file")
    from_onb = _import_from_onboarding()
    if not file or not allowed_file(file.filename):
        flash(translate("Sube un archivo Excel (.xlsx) o CSV (.csv) válido."), "danger")
        kwargs = {}
        if from_onb:
            kwargs['desde'] = 'primeros-pasos'
        if entity_type == 'users' and request.form.get('modo') in ('internos', 'externos'):
            kwargs['modo'] = request.form.get('modo')
        return redirect(url_for(IMPORT_WIZARD_CONFIG[entity_type]["upload_endpoint"], **kwargs))

    # Conservar modo antes de limpiar sesión de fichero
    preserved_opts = None
    if entity_type == 'users':
        modo = (request.form.get('modo') or '').strip().lower()
        if modo not in ('internos', 'externos'):
            modo = 'externos'
        preserved_opts = {'mode': modo}

    _clear_import_session(entity_type)
    if from_onb:
        session[_import_nav_key(entity_type)] = {'from_onboarding': True}
        session.modified = True
    if preserved_opts:
        session[_import_session_key(entity_type) + '_opts'] = preserved_opts
        session.modified = True

    try:
        _store_import_upload(entity_type, file)
    except Exception as exc:
        flash(translate("No se pudo guardar el archivo: {error}", error=exc), "danger")
        kwargs = {}
        if from_onb:
            kwargs['desde'] = 'primeros-pasos'
        if preserved_opts and preserved_opts.get('mode'):
            kwargs['modo'] = preserved_opts['mode']
        return redirect(url_for(IMPORT_WIZARD_CONFIG[entity_type]["upload_endpoint"], **kwargs))

    return redirect(url_for(IMPORT_WIZARD_CONFIG[entity_type]["preview_endpoint"]))


def _handle_import_preview(entity_type):
    cfg = IMPORT_WIZARD_CONFIG[entity_type]
    try:
        path, data = _load_import_path(entity_type)
    except (ValueError, FileNotFoundError) as exc:
        flash(translate(str(exc)), "danger")
        return redirect(url_for(cfg["upload_endpoint"]))

    if not path:
        flash(translate("Primero sube un archivo para previsualizar."), "warning")
        return redirect(url_for(cfg["upload_endpoint"]))

    column_map = None
    if request.method == "POST":
        column_map = _column_map_from_form(entity_type)
        data["column_map"] = column_map
        session[_import_session_key(entity_type)] = data
        # Opciones de personal (modo / empresa forzada)
        if entity_type == 'users':
            opts = session.get(_import_session_key(entity_type) + '_opts') or {}
            if request.form.get('modo') in ('internos', 'externos'):
                opts['mode'] = request.form.get('modo')
            force = (request.form.get('force_company_id') or '').strip()
            opts['force_company_id'] = int(force) if force.isdigit() else None
            # Checkbox: solo False si viene el form sin marcar (hidden 0 + checkbox)
            if 'assign_pin' in request.form:
                opts['assign_pin'] = request.form.get('assign_pin') in ('1', 'on', 'true', 'True')
            if 'notify_pin' in request.form:
                opts['notify_pin'] = request.form.get('notify_pin') in ('1', 'on', 'true', 'True')
            session[_import_session_key(entity_type) + '_opts'] = opts
        session.modified = True
    else:
        column_map = data.get("column_map")

    preview = preview_import(path, entity_type, column_map)
    if not preview.get("success"):
        flash(translate(preview.get("message") or "Error al leer el archivo"), "danger")
        _clear_import_session(entity_type)
        return redirect(url_for(cfg["upload_endpoint"]))

    data["column_map"] = preview.get("column_map")
    session[_import_session_key(entity_type)] = data
    session.modified = True

    return _render_import_preview(entity_type, preview)


def _handle_import_confirm(entity_type):
    cfg = IMPORT_WIZARD_CONFIG[entity_type]
    try:
        path, data = _load_import_path(entity_type)
    except (ValueError, FileNotFoundError) as exc:
        flash(translate(str(exc)), "danger")
        return redirect(url_for(cfg["upload_endpoint"]))

    if not path:
        flash(translate("No hay archivo pendiente de importar."), "warning")
        return redirect(url_for(cfg["upload_endpoint"]))

    column_map = _column_map_from_form(entity_type) or data.get("column_map")
    import_options = _import_options_from_session(entity_type) if entity_type == 'users' else None
    if entity_type == 'users':
        import_options = dict(import_options or {})
        if request.form.get('force_company_id') is not None:
            force = (request.form.get('force_company_id') or '').strip()
            import_options['force_company_id'] = int(force) if force.isdigit() else None
        if request.form.get('modo') in ('internos', 'externos'):
            import_options['mode'] = request.form.get('modo')
        # Checkbox: hidden 0 + checkbox 1
        import_options['assign_pin'] = request.form.get('assign_pin') in ('1', 'on', 'true', 'True')
        import_options['notify_pin'] = (
            import_options['assign_pin']
            and request.form.get('notify_pin') in ('1', 'on', 'true', 'True')
        )
        session[_import_session_key(entity_type) + '_opts'] = {
            k: import_options.get(k)
            for k in ('mode', 'force_company_id', 'assign_pin', 'notify_pin')
        }
        session.modified = True

    result = commit_import(
        path,
        entity_type,
        column_map,
        row_edits_form=request.form,
        import_options=import_options,
    )
    cfg = _apply_import_nav_context(entity_type, cfg)
    from_onb = bool(cfg.get('from_onboarding'))
    _clear_import_session(entity_type)
    if from_onb:
        # Tras éxito, el botón de vuelta sigue a primeros pasos
        session[_import_nav_key(entity_type)] = {'from_onboarding': True}
        session.modified = True

    if not result.get("success"):
        flash(translate(result.get("message") or "Error en la importación"), "danger")
        kwargs = {}
        if from_onb:
            kwargs['desde'] = 'primeros-pasos'
        if entity_type == 'users' and (import_options or {}).get('mode'):
            kwargs['modo'] = import_options['mode']
        return redirect(url_for(cfg["upload_endpoint"], **kwargs))

    # Tick de la guía de importación (obras / personal / empresas)
    try:
        from app.services.onboarding_service import marcar_import_tutorial
        if entity_type == 'obras':
            marcar_import_tutorial('obras')
        elif entity_type == 'companies':
            marcar_import_tutorial('companies')
        elif entity_type == 'users':
            mode = (import_options or {}).get('mode') or 'internos'
            marcar_import_tutorial(
                'users_externos' if mode == 'externos' else 'users_internos'
            )
    except Exception:
        pass

    return render_template(
        "admin_import_wizard.html",
        entity_type=entity_type,
        entity_label=ENTITY_LABELS.get(entity_type, entity_type),
        cfg=cfg,
        result=result,
        summary=result.get("summary") or {},
        rows=result.get("rows") or [],
        imported=result.get("imported") or [],
        created_companies=result.get("created_companies") or [],
        step=3,
        from_onboarding=from_onb,
        import_mode=(import_options or {}).get('mode') if entity_type == 'users' else None,
    )


@admin_bp.route("/import_obras", methods=["GET", "POST"])
@login_required
@roles_required(ROLE_ADMIN)
def import_obras():
    if request.method == "POST":
        return _handle_import_upload_post("obras")
    return _render_import_upload("obras")


@admin_bp.route("/import_obras/preview", methods=["GET", "POST"])
@login_required
@roles_required(ROLE_ADMIN)
def import_obras_preview():
    return _handle_import_preview("obras")


@admin_bp.route("/import_obras/confirm", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def import_obras_confirm():
    return _handle_import_confirm("obras")

@admin_bp.route('/solicitudes')
@login_required
def solicitudes_list():
    can_personal = can_view_solicitudes_personal(current_user)
    can_flota = can_view_solicitudes_flota(current_user)
    if not can_personal and not can_flota:
        flash(translate('No tienes permiso para ver solicitudes.'), 'danger')
        return redirect(url_for('main.dashboard'))

    seccion = request.args.get('seccion', 'personal')
    if seccion not in ('personal', 'vehiculos'):
        seccion = 'personal'
    if seccion == 'vehiculos' and not can_flota:
        seccion = 'personal'
    elif seccion == 'personal' and not can_personal and can_flota:
        seccion = 'vehiculos'

    estado = request.args.get('estado', 'todas')
    tipo = request.args.get('tipo', 'todas')
    obra_id = request.args.get('obra_id')
    date_filter_str = request.args.get('date_filter')
    estados_posibles = [
        'todas', 'PENDIENTE', 'EN_PROCESO', 'CUMPLIDA', 'CERRADA_PARCIAL',
        'DENEGADA', 'CANCELADA',
    ]
    tipos_posibles = ['todas', 'generica', 'concreta']
    target_date = parse_date(date_filter_str) if date_filter_str else None
    obra_seleccionada = Obra.query.get(int(obra_id)) if obra_id and obra_id.isdigit() else None
    can_resolve_vehiculo = can_resolve_solicitudes_flota(current_user)

    # --- SECCIÓN VEHÍCULOS ---
    if seccion == 'vehiculos':
        v_query = SolicitudVehiculo.query
        # Sin obra: oficina ve todas; custodia/none → solo las propias
        if user_panel_mode(current_user, PANEL_SOLICITUDES) != 'office':
            v_query = v_query.filter(SolicitudVehiculo.requested_by_id == current_user.id)

        if estado != 'todas':
            v_query = v_query.filter(SolicitudVehiculo.estado == estado)

        if target_date:
            v_query = v_query.filter(
                SolicitudVehiculo.fecha_inicio <= target_date,
                SolicitudVehiculo.fecha_fin >= target_date,
            )

        solicitudes_vehiculo = v_query.order_by(SolicitudVehiculo.created_at.desc()).all()
        return render_template(
            'admin_solicitudes_list.html',
            seccion=seccion,
            solicitudes=[],
            solicitudes_vehiculo=solicitudes_vehiculo,
            stats={},
            estado_filtro=estado,
            tipo_filtro=tipo,
            date_filtro=target_date,
            obra_filtro=obra_seleccionada,
            estados_posibles=estados_posibles,
            tipos_posibles=tipos_posibles,
            can_resolve_vehiculo=can_resolve_vehiculo,
        )

    # --- SECCIÓN PERSONAL (default) ---
    query = Solicitud.query
    scope_mode = user_panel_mode(current_user, PANEL_SOLICITUDES)
    if scope_mode != 'office':
        custody = user_custody_jefe_ids(current_user, PANEL_SOLICITUDES)
        if custody:
            query = query.outerjoin(Obra, Solicitud.obra_id == Obra.id).filter(
                or_(
                    Solicitud.requested_by_id == current_user.id,
                    Obra.jefe_obra_id.in_(custody),
                )
            )
        else:
            query = query.filter(Solicitud.requested_by_id == current_user.id)

    if obra_id:
        try:
            # 🛠️ CORRECCIÓN: Usar filtro explícito para evitar problemas similares
            query = query.filter(Solicitud.obra_id == int(obra_id))
        except ValueError: pass

    if estado != 'todas':
        # 🛠️ CORRECCIÓN: Forzar que el filtro se aplique a Solicitud, no a Obra
        query = query.filter(Solicitud.estado == estado)

    if tipo != 'todas':
        query = query.filter(func.lower(Solicitud.tipo) == tipo.lower())

    if target_date:
        query = query.filter(
            Solicitud.fecha_inicio <= target_date,
            Solicitud.fecha_fin >= target_date
        )

    # Cierra vencidas / cubiertas en accionable antes de pintar el inbox.
    try:
        sweep_open_solicitudes_actionable(limit=200)
    except Exception:
        current_app.logger.exception('sweep_open_solicitudes_actionable falló')
            
    solicitudes = query.order_by(Solicitud.created_at.desc()).all()

    # --- CÁLCULO DE ESTADÍSTICAS (misma lógica que el motor de cobertura) ---
    stats = {}

    for s in solicitudes:
        if s.tipo == 'GENERICA':
            cov = compute_generica_coverage(s)
            stats[s.id] = {
                'pct': cov['pct'],
                'cubiertas_total': cov['min_coverage'],
                'plazas_total': s.cantidad_solicitada,
            }
        else:
            valid_dates = get_solicitud_valid_dates(s)
            num_dias = len(valid_dates) or 1
            if s.empleado_id and valid_dates:
                dias_asignados = Asignacion.query.filter(
                    Asignacion.obra_id == s.obra_id,
                    Asignacion.user_id == s.empleado_id,
                    Asignacion.fecha.in_(valid_dates),
                ).count()
                pct = int((dias_asignados / num_dias) * 100)
            else:
                pct = 0
            stats[s.id] = {'pct': min(pct, 100)}

    solicitudes_inbox_vacio = (
        not solicitudes
        and estado == 'todas'
        and tipo == 'todas'
        and not obra_seleccionada
        and not target_date
    )
    tiene_jefes = (
        User.query.filter(
            User.role == ROLE_JEFE,
            User.is_deleted.is_(False),
            User.active.is_(True),
        ).count() > 0
    )

    return render_template(
        'admin_solicitudes_list.html',
        seccion=seccion,
        solicitudes=solicitudes,
        solicitudes_vehiculo=[],
        stats=stats, 
        estado_filtro=estado,
        tipo_filtro=tipo,
        date_filtro=target_date,
        obra_filtro=obra_seleccionada,
        estados_posibles=estados_posibles,
        tipos_posibles=tipos_posibles,
        can_resolve_vehiculo=can_resolve_vehiculo,
        solicitudes_inbox_vacio=solicitudes_inbox_vacio,
        tiene_jefes=tiene_jefes,
    )


@admin_bp.route('/solicitudes-vehiculo/<int:solicitud_id>/resolver', methods=['POST'])
@login_required
@permission_required('solicitudes_vehiculos', 'w')
def resolver_solicitud_vehiculo(solicitud_id):
    from app.services.vehicle_solicitud_service import VehicleSolicitudService

    solicitud = SolicitudVehiculo.query.get_or_404(solicitud_id)
    decision = request.form.get('decision') or (request.get_json() or {}).get('decision')
    if not decision:
        flash(translate('Falta la decisión (aceptar/denegar).'), 'danger')
        return redirect(url_for('admin.solicitudes_list', seccion='vehiculos'))

    try:
        mensaje = VehicleSolicitudService.resolve(solicitud, decision, current_user)
        flash(translate(mensaje), 'success')
    except Exception as e:
        db.session.rollback()
        flash(translate(str(e)), 'danger')

    return redirect(url_for('admin.solicitudes_list', seccion='vehiculos', estado=request.args.get('estado', 'todas')))

    
@admin_bp.route('/impersonate/<int:user_id>', methods=['POST'])
@login_required
@roles_required(ROLE_ADMIN)
def impersonate_user(user_id):
    """Entrar en la app como otro usuario (solo administrador)."""
    from app.services.impersonation_service import iniciar_impersonacion
    from app.utils import register_log

    target = User.query.filter_by(id=user_id, is_deleted=False).first_or_404()
    actor_id = current_user.id
    ok, err = iniciar_impersonacion(current_user, target)
    if not ok:
        flash(translate(err or 'No se pudo entrar como ese usuario.'), 'danger')
        return redirect(url_for('admin.personal'))

    register_log(
        user_id=actor_id,
        category='accesos',
        action='Impersonación inicio',
        detail=f"Entró como {target.name} {target.lastname} ({target.email}).",
        target_user_id=target.id,
    )
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()

    flash(
        translate(
            'Estás viendo la aplicación como {name}.',
            name=f'{target.name} {target.lastname}',
        ),
        'warning',
    )
    from app.services.user_home_service import home_url_for_user
    destino = home_url_for_user(target)
    from flask import make_response
    from app.services.impersonation_service import clear_remember_cookie
    resp = make_response(redirect(destino or url_for('auth.login')))
    return clear_remember_cookie(resp)


@admin_bp.route("/worker_panel/<int:user_id>", methods=["GET"])
@login_required
@roles_required(ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL)
def worker_panel(user_id):
    """
    Ficha del trabajador con calendario de sus asignaciones Y SOLICITUDES.
    (El calendario carga por API V6)
    """
    worker = User.query.get_or_404(user_id)
    panel_stats = get_worker_panel_stats(worker)
    history_days = 90
    history_open = request.args.get('history_open') == '1'
    try:
        history_days = int(request.args.get('history_days') or history_days)
    except (TypeError, ValueError):
        pass
    history_days = max(1, min(730, history_days))
    history_offset = 0
    try:
        history_offset = max(0, int(request.args.get('history_offset') or 0))
    except (TypeError, ValueError):
        pass
    history_page = get_worker_vehicle_rows(
        worker,
        days=history_days,
        offset=history_offset,
        limit=30,
    ) if history_open else None
    from app.services.permission_service import can_resolve_fichajes
    from app.services.fichaje_operario_service import tenant_muestra_auditoria_fichajes
    from app.services.impersonation_service import admin_puede_impersonar, puede_ser_impersonado
    from app.services.panel_scope_service import (
        planning_acts_as_office,
        valoraciones_acts_as_office,
    )
    from app.services.rating_service import reputation_for_viewer
    from app.utils.nav_back import resolve_back_url
    if planning_acts_as_office(current_user):
        back_url = resolve_back_url('admin.personal')
    else:
        back_url = resolve_back_url('admin.obras_detailed')
    rep_score, rep_count = reputation_for_viewer(worker, current_user)
    return render_template(
        "admin_worker_panel.html",
        worker=worker,
        back_url=back_url,
        stats=panel_stats["stats"],
        chart_14d=panel_stats["chart_14d"],
        chart_14d_max=panel_stats["chart_14d_max"],
        chart_caption=panel_stats.get("chart_caption"),
        vehicle_today=get_worker_vehicle_today(worker),
        history_days=history_days,
        history_open=history_open,
        history_page=history_page,
        can_edit_calendar=can_edit_planning_calendar(current_user),
        puede_impersonar=(
            admin_puede_impersonar(current_user)
            and puede_ser_impersonado(worker, current_user)
        ),
        puede_resolver_auditoria=(
            can_resolve_fichajes(current_user) and tenant_muestra_auditoria_fichajes()
        ),
        can_write_valoraciones=user_can(current_user, 'valoraciones', 'w'),
        can_read_valoraciones=user_can(current_user, 'valoraciones', 'r'),
        can_reset_valoraciones=(
            user_can(current_user, 'valoraciones', 'w')
            and valoraciones_acts_as_office(current_user)
        ),
        reputation_score=rep_score,
        reputation_count=rep_count,
    )


@admin_bp.route("/worker_panel/<int:user_id>/historial", methods=["GET"])
@login_required
@roles_required(ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL)
def worker_panel_historial(user_id):
    """Fragmento HTML del historial de vehículos del operario."""
    worker = User.query.get_or_404(user_id)
    try:
        days = int(request.args.get('days') or 90)
    except (TypeError, ValueError):
        days = 90
    days = max(1, min(730, days))
    try:
        offset = max(0, int(request.args.get('offset') or 0))
    except (TypeError, ValueError):
        offset = 0
    try:
        limit = int(request.args.get('limit') or 30)
    except (TypeError, ValueError):
        limit = 30
    page = get_worker_vehicle_rows(worker, days=days, offset=offset, limit=limit)
    return render_template(
        "components/_worker_vehicle_history_table.html",
        history_page=page,
    )


@admin_bp.route("/mapa-fichajes", methods=["GET"])
@login_required
def mapa_fichajes():
    from app.services.fichaje_operario_service import tenant_tiene_fichaje_operario_module
    from app.services.permission_service import user_can
    if not tenant_tiene_fichaje_operario_module():
        flash(translate("El mapa de fichajes requiere el módulo de fichaje operario activo."), "warning")
        return redirect(url_for('admin.panel'))
    if not user_can(current_user, 'mapa_fichajes', 'r'):
        flash(translate("No tienes permiso para ver el mapa de fichajes."), "danger")
        return redirect(url_for('admin.panel'))
    from app.utils.nav_back import resolve_back_url
    return render_template(
        "admin_mapa_fichajes.html",
        back_url=resolve_back_url('admin.panel'),
    )


@admin_bp.route("/api/mapa-fichajes/obras", methods=["GET"])
@login_required
def api_mapa_fichajes_obras():
    from app.services.fichaje_operario_service import tenant_tiene_fichaje_operario_module
    from app.services.mapa_fichajes_service import listar_obras_mapa
    from app.services.permission_service import user_can
    if not tenant_tiene_fichaje_operario_module():
        return jsonify({'success': False, 'error': translate('Módulo no disponible')}), 403
    if not user_can(current_user, 'mapa_fichajes', 'r'):
        return jsonify({'success': False, 'error': translate('Sin permiso')}), 403
    return jsonify({'success': True, **listar_obras_mapa(current_user)})


@admin_bp.route("/api/mapa-fichajes/obra/<int:obra_id>/fichajes", methods=["GET"])
@login_required
def api_mapa_fichajes_obra(obra_id):
    from app.services.fichaje_operario_service import tenant_tiene_fichaje_operario_module
    from app.services.mapa_fichajes_service import fichajes_mapa_obra
    from app.services.permission_service import user_can
    from app.services.dashboard_service import parse_date

    if not tenant_tiene_fichaje_operario_module():
        return jsonify({'success': False, 'error': translate('Módulo no disponible')}), 403
    if not user_can(current_user, 'mapa_fichajes', 'r'):
        return jsonify({'success': False, 'error': translate('Sin permiso')}), 403

    desde_raw = (request.args.get('desde') or '').strip()
    hasta_raw = (request.args.get('hasta') or '').strip()
    solo_dudosos = request.args.get('solo_dudosos') in ('1', 'true', 'yes')
    fecha_desde = parse_date(desde_raw) if desde_raw else None
    fecha_hasta = parse_date(hasta_raw) if hasta_raw else None

    data = fichajes_mapa_obra(
        obra_id,
        current_user,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        solo_dudosos=solo_dudosos,
    )
    if data is None:
        return jsonify({'success': False, 'error': translate('Obra no encontrada')}), 404
    return jsonify({'success': True, **data})


@admin_bp.route("/api/check_obra_status_impact", methods=["POST"])
@login_required
def check_obra_status_impact():
    """
    Calcula cuántas asignaciones futuras se borrarían al pausar una obra.
    """
    data = request.get_json()
    obra_id = data.get("obra_id")
    
    if not obra_id:
        return jsonify({"error": translate("Falta obra_id")}), 400

    today = date.today()
    
    # Contamos asignaciones desde HOY en adelante (inclusive)
    # porque al ponerla en pendiente, se para YA.
    future_assignments = Asignacion.query.filter(
        Asignacion.obra_id == obra_id,
        Asignacion.fecha >= today
    ).all()

    total_days = len(future_assignments)
    # Contamos trabajadores únicos afectados
    unique_workers = len(set(a.user_id for a in future_assignments))

    return jsonify({
        "success": True,
        "total_days": total_days,
        "unique_workers": unique_workers
    })
    

@admin_bp.route("/company_panel/<int:company_id>", methods=["GET"])
@login_required
@roles_required(ROLE_ADMIN, ROLE_JEFE)
def company_panel(company_id):
    """
    Ficha de empresa con cronograma de obras donde participa su personal.
    (Los datos del calendario ahora se cargan dinámicamente vía API).
    """
    company = Company.query.get_or_404(company_id)
    panel_stats = get_company_panel_stats(company)

    from app.utils.nav_back import resolve_back_url
    back_url = resolve_back_url('admin.companies')
    return render_template(
        "admin_company_panel.html",
        company=company,
        back_url=back_url,
        stats=panel_stats["stats"],
        chart_14d=panel_stats["chart_14d"],
        chart_14d_max=panel_stats["chart_14d_max"],
        avg_rating=panel_stats["avg_rating"],
        ratings_count=panel_stats["ratings_count"],
    )

   
    
@admin_bp.route('/solicitudes/<int:solicitud_id>')
@login_required
def solicitud_detail(solicitud_id):
    if not can_view_solicitudes_personal(current_user):
        flash(translate('No tienes permiso para ver solicitudes de personal.'), 'danger')
        return redirect(url_for('main.dashboard'))

    solicitud = Solicitud.query.get_or_404(solicitud_id)

    if not (
        solicitud.requested_by_id == current_user.id
        or solicitud_obra_in_scope(current_user, solicitud.obra)
    ):
        flash(translate('No tienes acceso a esta solicitud.'), 'danger')
        return redirect(url_for('admin.solicitudes_list'))

    # Sincroniza progreso/cobertura al abrir (corrige estados atascados tras asignar).
    if solicitud.estado in ('PENDIENTE', 'EN_PROCESO'):
        _recalculate_solicitud_coverage(solicitud)
        db.session.commit()
        db.session.refresh(solicitud)

    es_admin = can_resolve_solicitudes_personal(current_user)
    puede_cancelar = (
        solicitud.requested_by_id == current_user.id
        and solicitud.estado in ('PENDIENTE', 'EN_PROCESO')
    )
    fecha_inicio = solicitud.fecha_inicio
    fecha_fin = solicitud.fecha_fin
    cal_initial_date = fecha_inicio or fecha_fin or date.today()

    # 1. RESUMEN PERSONAL ASIGNADO (Se mantiene igual)
    asignaciones_resumen = []
    if fecha_inicio and fecha_fin:
        asignaciones = Asignacion.query.filter(
            Asignacion.obra_id == solicitud.obra_id,
            Asignacion.fecha >= fecha_inicio,
            Asignacion.fecha <= fecha_fin
        ).all()

        resumen = {}
        for a in asignaciones:
            if a.user_id not in resumen:
                worker = User.query.get(a.user_id)
                if not worker: continue
                resumen[a.user_id] = {
                    "worker": worker,
                    "empresa": worker.company_rel,
                    "num_dias": 0,
                    "primer_dia": a.fecha,
                    "ultimo_dia": a.fecha
                }
            r = resumen[a.user_id]
            r["num_dias"] += 1
            if a.fecha < r["primer_dia"]: r["primer_dia"] = a.fecha
            if a.fecha > r["ultimo_dia"]: r["ultimo_dia"] = a.fecha
        asignaciones_resumen = list(resumen.values())

    # 2. LÓGICA CANDIDATOS (NUEVA LÓGICA TRINARIA)
    profile_candidates = []
    candidate_states = {} # Diccionario para guardar el estado de cada trabajador
    
    ignore_profile = request.args.get('ignore_profile') 

    if fecha_inicio and fecha_fin:
        query = User.query.filter(
            User.role == ROLE_OPERARIO, 
            User.active.is_(True), 
            User.is_deleted.is_(False)
        )
        
        if not ignore_profile:
            # Eliminado el filtro estricto de categoría para sugerir a todos los trabajadores
            # if solicitud.perfil_categoria:
            #     query = query.filter(User.categoria_profesional.ilike(f"%{solicitud.perfil_categoria}%"))
            if solicitud.perfil_empresa_id:
                query = query.filter(User.company_id == solicitud.perfil_empresa_id)
            
        profile_candidates = query.order_by(User.name).all()
        candidate_ids = {u.id for u in profile_candidates}

        # Calcular duración total de la solicitud (en días)
        total_days_req = (fecha_fin - fecha_inicio).days + 1

        # Asignaciones en el periodo (cualquier obra) — incluye gente visible en calendario
        all_assignments = Asignacion.query.filter(
            Asignacion.fecha >= fecha_inicio,
            Asignacion.fecha <= fecha_fin,
        ).all()

        # Operarios con asignación en el rango que el filtro de empresa excluyó
        extra_user_ids = {a.user_id for a in all_assignments} - candidate_ids
        if extra_user_ids:
            extras = User.query.filter(
                User.id.in_(extra_user_ids),
                User.role == ROLE_OPERARIO,
                User.active.is_(True),
                User.is_deleted.is_(False),
            ).order_by(User.name).all()
            profile_candidates.extend(extras)
            profile_candidates.sort(key=lambda u: (u.name or '', u.lastname or ''))
            candidate_ids.update(u.id for u in extras)

        if solicitud.empleado_id and solicitud.empleado and solicitud.empleado.id not in candidate_ids:
            profile_candidates.append(solicitud.empleado)
            profile_candidates.sort(key=lambda u: (u.name or '', u.lastname or ''))
            candidate_ids.add(solicitud.empleado.id)
        
        # Agrupar asignaciones por usuario para contar días ocupados
        busy_counts = {}
        for a in all_assignments:
            if a.user_id not in candidate_ids:
                continue
            if a.user_id not in busy_counts:
                busy_counts[a.user_id] = set()
            busy_counts[a.user_id].add(a.fecha)
            
        # Determinar estado: LIBRE, PARCIAL, OCUPADO
        for u in profile_candidates:
            days_busy = len(busy_counts.get(u.id, set()))
            
            if days_busy == 0:
                state = 'FREE'
            elif days_busy >= total_days_req:
                state = 'BUSY' # Ocupado todo el periodo
            else:
                state = 'PARTIAL' # Tiene algunos días libres
                
            candidate_states[u.id] = {
                'status': state,
                'days_busy': days_busy
            }

    # 3. Cobertura (progreso + % de jornadas, misma lógica que el listado)
    cobertura_texto = ""
    if solicitud.tipo == 'GENERICA':
        cov = compute_generica_coverage(solicitud)
        cobertura_texto = (
            f"{cov['pct']}% · {solicitud.cantidad_cubierta}/{solicitud.cantidad_solicitada}"
        )

    from app.utils.nav_back import resolve_back_url
    back_url = resolve_back_url('admin.solicitudes_list')
    return render_template(
        'admin_solicitud_detail.html',
        solicitud=solicitud,
        back_url=back_url,
        solicitud_notas=get_solicitud_notas(solicitud),
        auto_cierre_texto=get_solicitud_auto_cierre_texto(solicitud),
        cobertura_texto=cobertura_texto,
        es_admin=es_admin,
        puede_cancelar=puede_cancelar,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        cal_initial_date=cal_initial_date,
        asignaciones_resumen=asignaciones_resumen, 
        profile_candidates=profile_candidates, 
        candidate_states=candidate_states, # <--- Pasamos el nuevo diccionario de estados
        total_days_req=(fecha_fin - fecha_inicio).days + 1 if fecha_inicio and fecha_fin else 1
    )

@admin_bp.route("/api/update_obra_staff", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def api_update_obra_staff():
    data = request.get_json()
    obra_id = data.get("obra_id")
    user_id = data.get("user_id") # Puede ser vacío si desasignamos
    role_type = data.get("role_type") # 'jefe' o 'encargado'
    
    obra = Obra.query.get(obra_id)
    if not obra:
        return jsonify({"success": False, "error": translate("Obra no encontrada")}), 404
        
    try:
        new_id = int(user_id) if user_id else None
        
        if role_type == 'jefe':
            obra.jefe_obra_id = new_id
            # Obtenemos nombre para devolver al frontend
            user_obj = obra.jefe_obra
        elif role_type == 'encargado':
            obra.encargado_id = new_id
            user_obj = obra.encargado
        else:
            return jsonify({"success": False, "error": translate("Tipo de rol inválido")}), 400
        
        db.session.commit()
        
        new_name = f"{user_obj.name} {user_obj.lastname}" if user_obj else translate("Sin asignar")
        return jsonify({"success": True, "new_name": new_name})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500



@admin_bp.route("/schedule_status/<int:user_id>", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def schedule_status(user_id):
    data = request.get_json()
    action = data.get("action")  # "activate" o "deactivate"

    scheduled_date = parse_date(data.get("date"))
    if not scheduled_date:
        return jsonify({"success": False, "error": translate("Fecha inválida")}), 400

    user = User.query.get(user_id)
    if not user or user.role != ROLE_OPERARIO:
        return jsonify({"success": False, "error": translate("Usuario no encontrado o rol inválido")}), 404

    if action == "deactivate":
        user.scheduled_deactivation_date = scheduled_date
        user.scheduled_activation_date = None
    elif action == "activate":
        user.scheduled_activation_date = scheduled_date
        user.scheduled_deactivation_date = None
    else:
        return jsonify({"success": False, "error": translate("Acción inválida")}), 400

    db.session.commit()
    return jsonify({"success": True, "message": translate("Fecha programada correctamente.")})


@admin_bp.route("/buscar_obras", methods=["GET"])
@login_required
@roles_required(ROLE_ADMIN)
def buscar_obras():
    start_date_str = request.args.get("start_date", "")
    end_date_str = request.args.get("end_date", "")
    jefe_id = request.args.get("jefe_id", "")
    operario_id = request.args.get("operario_id", "")

    start_date = parse_date(start_date_str, default=None)
    end_date = parse_date(end_date_str, default=None)
    query = Obra.query

    if start_date and end_date:
        query = query.filter(
            or_(
                Obra.fecha_inicio.between(start_date, end_date),
                Obra.fecha_fin.between(start_date, end_date),
            )
        )
    else:
        flash(translate("Formato de fechas inválido"), "danger")

    if jefe_id:
        try:
            jefe_id_int = int(jefe_id)
            query = query.filter(Obra.jefe_obra_id == jefe_id_int)
        except ValueError:
            pass

    if operario_id:
        try:
            operario_id_int = int(operario_id)
            query = query.join(Asignacion).filter(Asignacion.user_id == operario_id_int).distinct()
        except ValueError:
            pass

    obras = query.order_by(Obra.fecha_inicio.desc()).all()

    jefes = User.query.filter(User.role.in_([ROLE_JEFE, ROLE_ADMIN])).all()
    operarios = User.query.filter_by(role=ROLE_OPERARIO).all()

    return render_template(
        "admin_busqueda_obras.html",
        obras=obras,
        start_date=start_date_str,
        end_date=end_date_str,
        jefe_id=jefe_id,
        operario_id=operario_id,
        jefes=jefes,
        operarios=operarios,
    )


# --- AÑADIR EN app/admin/routes.py ---
# --- EN app/admin/routes.py ---
@admin_bp.route("/obra_panel/<int:obra_id>", methods=["GET"])
@login_required
@roles_required(ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL)
def obra_panel(obra_id):
    """
    Panel específico de una obra (Ficha de Obra).
    (Los datos del calendario ahora se cargan dinámicamente vía API universal).
    """
    from app.services.panel_scope_service import (
        PANEL_TABLERO,
        obra_in_planning_custody,
        planning_acts_as_office,
        user_panel_mode,
    )

    if not (
        user_can(current_user, 'tablero', 'r')
        or user_can(current_user, 'directorio', 'r')
    ):
        flash(translate("No tienes permisos para ver esta obra."), "danger")
        return redirect(url_for("main.dashboard"))

    obra = Obra.query.get_or_404(obra_id)

    if user_panel_mode(current_user, PANEL_TABLERO) == 'none' or not obra_in_planning_custody(
        current_user, obra
    ):
        flash(translate("No tienes permisos para ver esta obra."), "danger")
        return redirect(url_for("main.dashboard"))

    jefes = User.query.filter(User.role.in_([ROLE_JEFE, ROLE_ADMIN])).all()
    panel_stats = get_obra_panel_stats(obra)

    from app.utils.nav_back import resolve_back_url
    if planning_acts_as_office(current_user):
        back_url = resolve_back_url('admin.obras_list')
    else:
        back_url = resolve_back_url('admin.obras_detailed')

    return render_template(
        "admin_obra_panel.html",
        obra=obra,
        back_url=back_url,
        jefes=jefes,
        today=date.today(),
        stats=panel_stats["stats"],
        chart_14d=panel_stats["chart_14d"],
        chart_14d_max=panel_stats["chart_14d_max"],
        operarios_hoy=panel_stats["operarios_hoy"],
        ocupacion_pct=panel_stats["ocupacion_pct"],
        vehicle_rows=get_obra_vehicle_rows(obra),
        can_edit_calendar=can_edit_planning_calendar(current_user),
        can_edit_obra=user_can(current_user, 'directorio', 'w'),
    )
    
@admin_bp.route("/companies", methods=["GET"])
@login_required
@roles_required(ROLE_ADMIN)
def companies():
    """Solo lista las empresas."""
    filter_nombre = request.args.get("nombre", "")
    query = Company.query
    if filter_nombre:
        query = query.filter(Company.nombre.ilike(f"%{filter_nombre}%"))
    companies_list = query.all()
    return render_template("admin_companies.html", companies=companies_list, filter_nombre=filter_nombre)


@admin_bp.route("/vehiculos", methods=["GET"])
@login_required
@permission_required('vehiculos', 'r')
def vehiculos():
    """Listado de flota (alta manual y/o sync Odoo)."""
    show_inactive = request.args.get('show_inactive') in ('1', 'true', 'on', 'yes')
    query = Vehiculo.query
    if not show_inactive:
        query = query.filter(Vehiculo.active.is_(True))
    vehicles = (
        query
        .order_by(Vehiculo.active.desc(), Vehiculo.matricula.asc().nullslast(), Vehiculo.nombre.asc())
        .all()
    )
    return render_template(
        "admin_vehiculos.html",
        vehicles=vehicles,
        show_inactive=show_inactive,
    )


def _render_vehiculo_form(*, vehiculo=None, form_data=None):
    return render_template(
        "admin_vehiculo_form.html",
        vehiculo=vehiculo,
        form_data=form_data or {},
        return_to=_return_to_key(),
        cancel_url=_cancel_url_after_create('admin.vehiculos'),
    )


@admin_bp.route("/vehiculos/nuevo", methods=["GET"])
@login_required
@permission_required('vehiculos', 'w')
def vehiculos_nuevo():
    """Formulario de alta (misma plantilla que editar)."""
    return _render_vehiculo_form()


@admin_bp.route("/vehiculos/crear", methods=["POST"])
@login_required
@permission_required('vehiculos', 'w')
def vehiculos_crear():
    """Alta manual de vehículo (sin ERP)."""
    nombre = (request.form.get('nombre') or '').strip()
    matricula = (request.form.get('matricula') or '').strip().upper() or None
    marca = (request.form.get('marca') or '').strip() or None
    modelo = (request.form.get('modelo') or '').strip() or None
    from_form = request.form.get('from_form') == '1'

    if not nombre:
        flash(translate('Indica un nombre para el vehículo.'), 'danger')
        if from_form:
            return _render_vehiculo_form(form_data=request.form)
        return redirect(_url_with_return_to('admin.vehiculos_nuevo'))

    if matricula:
        dup = Vehiculo.query.filter(
            db.func.upper(Vehiculo.matricula) == matricula
        ).first()
        if dup:
            flash(translate('Ya existe un vehículo con matrícula {matricula}.', matricula=matricula), 'danger')
            if from_form:
                return _render_vehiculo_form(form_data=request.form)
            return redirect(_url_with_return_to('admin.vehiculos_nuevo'))

    v = Vehiculo(
        nombre=nombre[:120],
        matricula=matricula[:40] if matricula else None,
        marca=marca[:80] if marca else None,
        modelo=modelo[:80] if modelo else None,
        active=True,
    )
    db.session.add(v)
    db.session.commit()
    flash(translate('Vehículo «{label}» dado de alta.', label=v.label()), 'success')
    return _redirect_after_create('admin.vehiculos')


@admin_bp.route("/vehiculos/<int:vehiculo_id>/editar", methods=["GET", "POST"])
@login_required
@permission_required('vehiculos', 'w')
def vehiculos_editar(vehiculo_id):
    v = Vehiculo.query.get_or_404(vehiculo_id)
    if request.method == "GET":
        return render_template(
            "admin_vehiculo_form.html",
            vehiculo=v,
            form_data={},
        )

    nombre = (request.form.get('nombre') or '').strip()
    matricula = (request.form.get('matricula') or '').strip().upper() or None
    marca = (request.form.get('marca') or '').strip() or None
    modelo = (request.form.get('modelo') or '').strip() or None
    from_form = request.form.get('from_form') == '1'

    if not nombre:
        flash(translate('El nombre no puede quedar vacío.'), 'danger')
        if from_form:
            return render_template(
                "admin_vehiculo_form.html",
                vehiculo=v,
                form_data=request.form,
            )
        return redirect(url_for('admin.vehiculos_editar', vehiculo_id=v.id))

    if matricula:
        dup = Vehiculo.query.filter(
            db.func.upper(Vehiculo.matricula) == matricula,
            Vehiculo.id != v.id,
        ).first()
        if dup:
            flash(translate('Ya existe otro vehículo con matrícula {matricula}.', matricula=matricula), 'danger')
            if from_form:
                return render_template(
                    "admin_vehiculo_form.html",
                    vehiculo=v,
                    form_data=request.form,
                )
            return redirect(url_for('admin.vehiculos_editar', vehiculo_id=v.id))

    v.nombre = nombre[:120]
    v.matricula = matricula[:40] if matricula else None
    v.marca = marca[:80] if marca else None
    v.modelo = modelo[:80] if modelo else None
    if from_form:
        from app.utils.timezone_utils import utc_now
        want_active = request.form.get('active') in ('1', 'on', 'true', 'yes')
        if want_active and not v.active:
            v.active = True
            v.deactivation_reason = None
            v.deactivated_at = None
            v.deactivated_by_id = None
        elif (not want_active) and v.active:
            v.active = False
            v.deactivation_reason = 'manual'
            v.deactivated_at = utc_now()
            v.deactivated_by_id = current_user.id
    db.session.commit()
    flash(translate('Vehículo actualizado.'), 'success')
    return redirect(url_for('admin.vehicle_panel', vehiculo_id=v.id))


@admin_bp.route("/vehiculos/<int:vehiculo_id>/toggle", methods=["POST"])
@login_required
@permission_required('vehiculos', 'w')
def vehiculos_toggle(vehiculo_id):
    from app.utils.timezone_utils import utc_now

    v = Vehiculo.query.get_or_404(vehiculo_id)
    if v.active:
        v.active = False
        v.deactivation_reason = 'manual'
        v.deactivated_at = utc_now()
        v.deactivated_by_id = current_user.id
    else:
        v.active = True
        v.deactivation_reason = None
        v.deactivated_at = None
        v.deactivated_by_id = None
    db.session.commit()
    estado = translate('activado') if v.active else translate('desactivado')
    flash(
        translate('Vehículo «{label}» {estado}.', label=v.label(), estado=estado),
        'success',
    )
    return redirect(request.referrer or url_for('admin.vehiculos'))


@admin_bp.route("/vehiculos/libres", methods=["GET"])
@login_required
def vehiculos_libres():
    """Coches libres a futuro: sin plan o conductor de ausencia."""
    if not (
        user_can(current_user, 'vehiculos_libres', 'r')
        or user_can(current_user, 'vehiculos', 'r')
    ):
        flash(translate('No tienes permiso para ver coches libres.'), 'danger')
        return redirect(url_for('main.dashboard'))
    from app.services.vehicle_availability_service import (
        DEFAULT_HORIZON_MONTHS,
        HORIZON_MONTHS_ALLOWED,
        MOTIVO_AUSENCIA,
        MOTIVO_MIXTO,
        MOTIVO_SIN_PLAN,
        free_vehicle_summary,
        horizon_end,
        list_free_vehicle_stretches,
        parse_horizon_months,
    )
    from app.utils.timezone_utils import today_local

    months = parse_horizon_months(request.args.get('meses'), DEFAULT_HORIZON_MONTHS)
    motivo_filtro = (request.args.get('motivo') or '').strip()
    if motivo_filtro not in (MOTIVO_SIN_PLAN, MOTIVO_AUSENCIA, MOTIVO_MIXTO, ''):
        motivo_filtro = ''
    q = (request.args.get('q') or '').strip()

    today = today_local()
    hasta = horizon_end(today, months)
    stretches = list_free_vehicle_stretches(fecha_desde=today, fecha_hasta=hasta)
    if motivo_filtro:
        stretches = [s for s in stretches if s['motivo'] == motivo_filtro]
    if q:
        q_low = q.lower()
        stretches = [
            s for s in stretches
            if q_low in (s.get('vehiculo_label') or '').lower()
        ]
    summary = free_vehicle_summary(stretches)
    flota_vacia = Vehiculo.query.count() == 0

    return render_template(
        "admin_vehiculos_libres.html",
        stretches=stretches,
        summary=summary,
        months=months,
        months_allowed=HORIZON_MONTHS_ALLOWED,
        motivo_filtro=motivo_filtro,
        q=q,
        fecha_desde=today,
        fecha_hasta=hasta,
        flota_vacia=flota_vacia,
    )


@admin_bp.route("/vehicle_panel/<int:vehiculo_id>", methods=["GET"])
@login_required
@permission_required('vehiculos', 'r')
def vehicle_panel(vehiculo_id):
    """Ficha de vehículo con historial (plegable) y calendario de asignaciones."""
    vehiculo = Vehiculo.query.get_or_404(vehiculo_id)
    panel_stats = get_vehicle_panel_stats(vehiculo)
    try:
        history_days = int(request.args.get('history_days') or 30)
    except (TypeError, ValueError):
        history_days = 30
    history_days = max(1, min(730, history_days))
    history_open = request.args.get('history_open') in ('1', 'true', 'yes')

    from app.utils.nav_back import resolve_back_url
    back_url = resolve_back_url('admin.vehiculos')

    return render_template(
        "admin_vehicle_panel.html",
        vehiculo=vehiculo,
        back_url=back_url,
        stats=panel_stats["stats"],
        chart_14d=panel_stats["chart_14d"],
        chart_14d_max=panel_stats["chart_14d_max"],
        history_days=history_days,
        history_open=history_open,
        history_rows=get_vehicle_history_rows(vehiculo, days=history_days) if history_open else [],
        can_edit_calendar=can_edit_vehicle_calendar(current_user),
    )


@admin_bp.route("/vehicle_panel/<int:vehiculo_id>/historial", methods=["GET"])
@login_required
@permission_required('vehiculos', 'r')
def vehicle_panel_historial(vehiculo_id):
    """Fragmento HTML del historial de uso (rango configurable, máx. 730 días)."""
    vehiculo = Vehiculo.query.get_or_404(vehiculo_id)
    try:
        days = int(request.args.get('days') or 30)
    except (TypeError, ValueError):
        days = 30
    days = max(1, min(730, days))
    rows = get_vehicle_history_rows(vehiculo, days=days)
    return render_template(
        "components/_vehicle_history_table.html",
        history_rows=rows,
        history_days=days,
    )


@admin_bp.route("/create_company", methods=["GET", "POST"])
@login_required
@roles_required(ROLE_ADMIN)
def create_company():
    """Gestiona el formulario de creación."""
    if request.method == "POST":
        code = request.form.get("code")

        # --- FIX: Generar código automático si viene vacío o "None" ---
        if not code or str(code).strip() == "" or str(code).strip().lower() == "none":
            import uuid
            code = f"AUTO-{uuid.uuid4().hex[:6].upper()}"
        # --------------------------------------------------------------

        nombre = request.form.get("nombre")
        nif = request.form.get("nif")
        descripcion = request.form.get("descripcion")
        gremio = request.form.get("gremio")
        email = request.form.get("email")
        color = (request.form.get("color") or "").strip()
        if not color or color.lower() in ("#ffffff", "#fff", "#cccccc", "#ccc"):
            from app.models import generate_random_color
            color = generate_random_color()

        # LEER CHECKBOX: Si está marcado viene 'on', si no, None.
        is_internal = True if request.form.get("is_internal") == "on" else False

        existing = Company.query.filter_by(code=code).first()
        if existing:
            flash(translate("El código de empresa ya existe."), "danger")
            return redirect(url_for("admin.create_company"))
        
        new_company = Company(
            code=code,
            nombre=nombre,
            nif=nif,
            descripcion=descripcion,
            gremio=gremio,
            email=email,
            color=color,
            is_internal=is_internal
        )
        
        # --- FIX: Envolvemos en try/except para evitar bloqueos del servidor ---
        try:
            db.session.add(new_company)
            db.session.commit()
            flash(translate("Empresa creada exitosamente."), "success")
            return redirect(url_for("admin.companies"))
        except Exception as e:
            db.session.rollback()
            flash(translate("Error en la base de datos: {error}", error=str(e)), "danger")
            return redirect(url_for("admin.create_company"))

    from app.models import generate_random_color
    return render_template(
        "admin_create_company.html",
        color_sugerido=generate_random_color(),
    )


@admin_bp.route("/company/<int:company_id>/edit", methods=["GET", "POST"])
@login_required
@roles_required(ROLE_ADMIN, redirect_to="admin.companies")
def edit_company(company_id):
    company = Company.query.get_or_404(company_id)
    if request.method == "POST":
        new_code = request.form.get("code")
        
        # --- FIX: Generar código automático si lo dejan vacío ---
        if not new_code or str(new_code).strip() == "" or str(new_code).strip().lower() == "none":
            # Si ya tenía un código válido, se lo mantenemos por si lo han borrado sin querer
            if company.code and str(company.code).strip().lower() != "none":
                new_code = company.code
            else:
                import uuid
                new_code = f"AUTO-{uuid.uuid4().hex[:6].upper()}"
                
        # Validar que si han metido un código a mano, no coincida con el de OTRA empresa
        if new_code != company.code:
            existing = Company.query.filter_by(code=new_code).first()
            if existing:
                flash(translate("El código de empresa '{code}' ya está usado por otra subcontrata.", code=new_code), "danger")
                return render_template("admin_edit_company.html", company=company)
        # --------------------------------------------------------

        company.code = new_code
        company.nombre = request.form.get("nombre")
        company.nif = request.form.get("nif")
        company.descripcion = request.form.get("descripcion")
        company.gremio = request.form.get("gremio")
        company.email = request.form.get("email")
        company.color = request.form.get("color") or "#ffffff"
        
        # LEER Y ACTUALIZAR CHECKBOX
        company.is_internal = True if request.form.get("is_internal") == "on" else False

        # --- FIX: Try/Except protector ---
        try:
            db.session.commit()
            flash(translate("Empresa actualizada correctamente"), "success")
            return redirect(url_for("admin.companies"))
        except Exception as e:
            db.session.rollback()
            flash(translate("Error al guardar los cambios: {error}", error=str(e)), "danger")
            return render_template("admin_edit_company.html", company=company)
    
    return render_template("admin_edit_company.html", company=company)


@admin_bp.route("/api/rate_worker", methods=["POST"])
@login_required
def rate_worker():
    from app.services.tenant_modules import has_valoraciones
    from app.services.rating_service import parse_rating_payload
    if not has_valoraciones():
        return jsonify({'success': False, 'message': translate('Módulo no activo')}), 404
    if not user_can(current_user, 'valoraciones', 'w'):
        return jsonify({'success': False, 'message': translate('No autorizado')}), 403
    data = request.get_json() or {}
    worker_id = data.get('worker_id')

    if not worker_id:
        return jsonify({'success': False, 'message': translate('Faltan datos')}), 400

    try:
        actitud, conocimiento, media, reason = parse_rating_payload(data)
    except ValueError as e:
        return jsonify({'success': False, 'message': translate(str(e))}), 400

    try:
        new_rating = Rating(
            user_id=int(worker_id),
            created_by_id=current_user.id,
            score=media,
            actitud=actitud,
            conocimiento=conocimiento,
            reason=reason,
            is_active=True
        )
        db.session.add(new_rating)
        from app.utils import register_log
        operario = User.query.get(int(worker_id))
        nombre_operario = f"{operario.name} {operario.lastname}" if operario else f"ID {worker_id}"
        dims = []
        if actitud is not None:
            dims.append(f"actitud {actitud}")
        if conocimiento is not None:
            dims.append(f"conocimiento {conocimiento}")
        register_log(
            user_id=current_user.id,
            category='valoraciones',
            action='Nueva Valoración',
            detail=f"Ha puntuado a {nombre_operario} ({', '.join(dims)}; media {media}). Motivo: {reason}",
            target_user_id=int(worker_id),
        )
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


def _can_manage_rating(rating):
    """Editar/borrar: autor con escritura, u oficina de valoraciones."""
    if not user_can(current_user, 'valoraciones', 'w'):
        return False
    if rating.created_by_id == current_user.id:
        return True
    from app.services.panel_scope_service import valoraciones_acts_as_office
    return valoraciones_acts_as_office(current_user)


@admin_bp.route("/api/rating/<int:rating_id>", methods=["PUT"])
@login_required
def update_rating(rating_id):
    from app.services.tenant_modules import has_valoraciones
    from app.services.rating_service import parse_rating_payload
    if not has_valoraciones():
        return jsonify({'success': False, 'message': translate('Módulo no activo')}), 404
    rating = Rating.query.get_or_404(rating_id)
    if not _can_manage_rating(rating):
        return jsonify({'success': False, 'message': translate('No autorizado')}), 403
    if not rating.is_active:
        return jsonify({'success': False, 'message': translate('Esta valoración ya está archivada')}), 400

    data = request.get_json() or {}
    try:
        actitud, conocimiento, media, reason = parse_rating_payload(data)
    except ValueError as e:
        return jsonify({'success': False, 'message': translate(str(e))}), 400

    try:
        rating.actitud = actitud
        rating.conocimiento = conocimiento
        rating.score = media
        rating.reason = reason
        from app.utils import register_log
        register_log(
            user_id=current_user.id,
            category='valoraciones',
            action='Editar Valoración',
            detail=f"Editada valoración #{rating.id} → media {media} (A:{actitud} K:{conocimiento}). Motivo: {reason}",
            target_user_id=rating.user_id,
        )
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@admin_bp.route("/api/rating/<int:rating_id>", methods=["DELETE"])
@login_required
def delete_rating(rating_id):
    from app.services.tenant_modules import has_valoraciones
    if not has_valoraciones():
        return jsonify({'success': False, 'message': translate('Módulo no activo')}), 404
    rating = Rating.query.get_or_404(rating_id)
    if not _can_manage_rating(rating):
        return jsonify({'success': False, 'message': translate('No autorizado')}), 403
    if not rating.is_active:
        return jsonify({'success': False, 'message': translate('Ya estaba eliminada')}), 400

    try:
        rating.is_active = False
        from app.utils import register_log
        register_log(
            user_id=current_user.id,
            category='valoraciones',
            action='Eliminar Valoración',
            detail=f"Eliminada valoración #{rating.id} ({rating.score} pts).",
            target_user_id=rating.user_id,
        )
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@admin_bp.route("/worker/<int:user_id>/reset_ratings", methods=["POST"])
@login_required
def reset_worker_ratings(user_id):
    from app.services.tenant_modules import has_valoraciones
    from app.services.panel_scope_service import valoraciones_acts_as_office
    if not has_valoraciones():
        flash(translate('Módulo no activo.'), 'warning')
        return redirect(url_for('admin.worker_panel', user_id=user_id))
    if not (
        user_can(current_user, 'valoraciones', 'w')
        and valoraciones_acts_as_office(current_user)
    ):
        flash(translate('No tienes permiso para resetear valoraciones.'), 'danger')
        return redirect(url_for('admin.worker_panel', user_id=user_id))
    worker = User.query.get_or_404(user_id)
    
    # Marcamos todos los ratings actuales como inactivos (histórico)
    for r in worker.ratings_received:
        if r.is_active:
            r.is_active = False

    from app.utils import register_log
    register_log(
        user_id=current_user.id,
        category='valoraciones',
        action='Reseteo de Historial',
        detail=f"Ha reseteado a 0.0 todas las valoraciones de {worker.name} {worker.lastname}.",
        target_user_id=worker.id,
    )
    db.session.commit()
    flash(translate("Puntuación de {name} restablecida a 0. El historial se ha guardado.", name=worker.name), "success")
    return redirect(url_for('admin.worker_panel', user_id=worker.id))

@admin_bp.route("/worker/<int:user_id>/ratings_history")
@login_required
def worker_ratings_history(user_id):
    from app.services.tenant_modules import has_valoraciones
    from app.services.panel_scope_service import (
        rating_visible_to_user,
        valoraciones_acts_as_office,
    )
    from app.services.rating_service import reputation_for_viewer
    if not has_valoraciones():
        flash(translate('Módulo no activo.'), 'warning')
        return redirect(url_for('admin.worker_panel', user_id=user_id))
    if not user_can(current_user, 'valoraciones', 'r'):
        flash(translate('No tienes permiso para ver valoraciones.'), 'danger')
        return redirect(url_for('admin.worker_panel', user_id=user_id))
    worker = User.query.get_or_404(user_id)
    all_ratings = Rating.query.filter_by(user_id=worker.id).order_by(Rating.created_at.desc()).all()
    # Histórico: oficina ve todo; custodia solo las firmadas por autores permitidos
    # (incluye inactivas propias / de su alcance para trazabilidad).
    if valoraciones_acts_as_office(current_user):
        ratings = all_ratings
    else:
        ratings = [r for r in all_ratings if rating_visible_to_user(current_user, r)]
    rep_score, rep_count = reputation_for_viewer(worker, current_user)
    from app.utils.nav_back import resolve_back_url
    back_url = resolve_back_url('admin.worker_panel', user_id=worker.id)
    return render_template(
        "admin_worker_ratings.html",
        worker=worker,
        ratings=ratings,
        reputation_score=rep_score,
        reputation_count=rep_count,
        can_write_valoraciones=user_can(current_user, 'valoraciones', 'w'),
        valoraciones_office=valoraciones_acts_as_office(current_user),
        back_url=back_url,
    )

@admin_bp.route("/obras", methods=["GET"])
@login_required
@permission_required('directorio', 'r')
def obras_list():
    # Filtros básicos de SQL (opcional, ya que haremos filtrado en cliente también)
    query = Obra.query.filter(Obra.is_deleted != True)
    query = apply_obra_scope_filter(query, current_user, PANEL_PLANIFICADOR)
    obras = query.order_by(Obra.fecha_inicio.desc()).all()
    
    # NECESARIO: Obtener lista de jefes para el desplegable de edición rápida
    jefes = User.query.filter(
        User.role.in_([ROLE_JEFE, ROLE_ADMIN]),
        User.is_deleted == False
    ).order_by(User.name).all()

    return render_template(
        "admin_obras_list.html",
        obras=obras,
        jefes=jefes
    )

# --- NUEVA RUTA API PARA CAMBIO RÁPIDO DE JEFE ---
@admin_bp.route("/api/update_obra_jefe", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def api_update_obra_jefe():
    data = request.get_json()
    obra_id = data.get("obra_id")
    new_jefe_id = data.get("jefe_id")
    
    obra = Obra.query.get(obra_id)
    if not obra:
        return jsonify({"success": False, "error": translate("Obra no encontrada")}), 404
        
    try:
        if new_jefe_id:
            obra.jefe_obra_id = int(new_jefe_id)
        else:
            obra.jefe_obra_id = None
        
        db.session.commit()
        
        # Devolver el nombre para actualizar la interfaz
        nuevo_nombre = f"{obra.jefe_obra.name} {obra.jefe_obra.lastname}" if obra.jefe_obra else translate("Sin asignar")
        return jsonify({"success": True, "new_name": nuevo_nombre})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


@admin_bp.route("/api/obra/<int:obra_id>/ubicacion", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def api_obra_ubicacion(obra_id):
    from app.utils.obra_geo import aplicar_obra_geo_json

    obra = Obra.query.get_or_404(obra_id)
    data = request.get_json(silent=True) or {}
    try:
        aplicar_obra_geo_json(obra, data)
        db.session.commit()
        return jsonify({
            "success": True,
            "ubicacion": obra.ubicacion or "",
            "latitud": obra.latitud,
            "longitud": obra.longitud,
        })
    except ValueError as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

# Asegúrate de que tienes estos imports al principio del archivo admin/routes.py
# from sqlalchemy.orm import joinedload
@admin_bp.route("/obras_detailed", methods=["GET"])
@login_required
def obras_detailed():
    # Si el alta no dejó ejemplos, sembrarlos ahora (antes de pintar el tablero).
    try:
        from app.services.demo_data_service import ensure_demo_for_onboarding
        if current_user.role == ROLE_ADMIN:
            ensure_demo_for_onboarding(actor_user=current_user)
    except Exception:
        current_app.logger.exception('ensure_demo_for_onboarding falló')
        try:
            db.session.rollback()
        except Exception:
            pass

    # 1. Obtener fecha de la URL
    date_str = request.args.get('selected_date')
    
    # 2. Llamar al SERVICIO CENTRALIZADO
    # 'view_param="todas"' indica que el Admin quiere ver todas las obras activas
    context = get_dashboard_data(current_user, date_str, view_param='todas')
    
    # 3. Inyectar las URLs de navegación específicas para el Admin
    # Esto sobreescribe las del servicio para que los botones apunten a /admin/...
    context['prev_month_url'] = url_for('admin.obras_detailed', selected_date=context['prev_date_str'])
    context['next_month_url'] = url_for('admin.obras_detailed', selected_date=context['next_date_str'])
    
    # 4. Configurar modo vista (para activar botones de edición en el HTML)
    context['view_mode'] = 'readonly' if not can_edit_planning_calendar(current_user) else 'admin'
    from app.services.permission_service import can_resolve_fichajes
    from app.services.fichaje_operario_service import tenant_muestra_auditoria_fichajes
    context['puede_resolver_auditoria'] = (
        can_resolve_fichajes(current_user) and tenant_muestra_auditoria_fichajes()
    )
    
    # 5. Renderizar desempaquetando el contexto (header_days, timeline_data, free_workers, etc.)
    return render_template("obras_detailed_unificado.html", **context)



@admin_bp.route("/personal", methods=["GET"])
@login_required
@permission_required('trabajadores', 'r')
def personal():
    # 1. Usuarios INTERNOS (No operarios, O operarios de empresa interna)
    internos = User.query.join(Company, User.company_id == Company.id, isouter=True).filter(
        (User.role != ROLE_OPERARIO) | 
        ((User.role == ROLE_OPERARIO) & (Company.is_internal == True)),
        User.is_deleted == False
    ).order_by(User.name).all()

    # 2. Operarios EXTERNOS (Empresa con is_internal=False)
    base_operarios = User.query.join(Company).filter(
        User.role == ROLE_OPERARIO, 
        Company.is_internal == False, 
        User.is_deleted == False
    )
    
    # Filtro por empresa en la URL (?company_id=5)
    company_filter_id = request.args.get("company_id")
    if company_filter_id:
        base_operarios = base_operarios.filter(User.company_id == int(company_filter_id))

    operarios_activos = base_operarios.filter(User.active == True).order_by(User.name).all()
    operarios_pendientes = base_operarios.filter(User.active == False).order_by(User.name).all()

    # 3. Archivados (soft-delete): consulta, no gestionables desde las otras pestañas
    from sqlalchemy.orm import joinedload
    eliminados = (
        User.query
        .options(joinedload(User.deactivated_by), joinedload(User.company_rel))
        .filter(User.is_deleted.is_(True))
        .order_by(User.deactivated_at.desc().nullslast(), User.name)
        .all()
    )

    # Para el dropdown de filtros en la vista
    companies = Company.query.filter_by(is_internal=False, active=True).all()

    from app.services.plan_service import resumen_cupo
    cupo = resumen_cupo()

    return render_template(
        "gestion_personal_unificado.html",
        view_mode="admin",
        internos=internos,
        operarios_activos=operarios_activos,
        operarios_pendientes=operarios_pendientes,
        eliminados=eliminados,
        active_count=len(operarios_activos),
        pending_count=len(operarios_pendientes),
        companies=companies, # Pasamos objetos, no strings
        company_filter=company_filter_id,
        next_url=request.path,
        cupo=cupo,
    )


@admin_bp.route("/deactivate_operario/<int:user_id>", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def deactivate_operario(user_id):
    from app.services.employee_baja_service import dar_de_baja

    user = User.query.get(user_id)
    if user and user.role == ROLE_OPERARIO:
        result = dar_de_baja(user, actor_id=current_user.id, motivo='manual', commit=True)
        if result.get('changed'):
            flash(translate("Operario dado de baja (historial conservado)"), "success")
        else:
            flash(translate("El operario ya estaba inactivo"), "info")
    else:
        flash(translate("Usuario no encontrado o rol inválido"), "danger")
    return redirect(request.referrer or url_for("admin.personal", tab="operarios"))


@admin_bp.route("/edit_operario/<int:user_id>", methods=["GET", "POST"])
@login_required
@roles_required(ROLE_ADMIN)
def edit_operario(user_id):
    user = User.query.get_or_404(user_id)
    companies = Company.query.filter(
        or_(Company.active.is_(True), Company.id == user.company_id)
    ).order_by(
        Company.is_internal.desc(), Company.nombre.asc()
    ).all()

    if request.method == "POST":
        new_dni = (request.form.get("dni") or "").strip().upper()
        nuevo_rol = (request.form.get("role") or user.role).strip()
        from app.services.role_registry_service import valid_role_keys
        if nuevo_rol not in valid_role_keys():
            flash(translate("Rol no válido."), "danger")
            return _render_user_form(
                edit_mode=True,
                user=user,
                action_url=url_for("admin.edit_operario", user_id=user.id),
                companies=companies,
            )

        if nuevo_rol == ROLE_OPERARIO:
            new_email = (
                request.form.get("email")
                or request.form.get("email_advanced")
                or ""
            ).strip().lower()
            if not _email_parece_real_form(new_email):
                new_email = _email_placeholder_desde_dni(new_dni or user.dni)
        else:
            new_email = (
                request.form.get("email_office")
                or request.form.get("email")
                or ""
            ).strip().lower()
            if not _email_parece_real_form(new_email):
                flash(translate("Email obligatorio para perfiles de oficina."), "danger")
                return _render_user_form(
                    edit_mode=True,
                    user=user,
                    action_url=url_for("admin.edit_operario", user_id=user.id),
                    companies=companies,
                )

        existing_dni = User.query.filter(User.dni == new_dni, User.id != user.id).first()
        if existing_dni:
            flash(
                translate(
                    "Error: El DNI {dni} ya pertenece a otro usuario ({name}).",
                    dni=new_dni,
                    name=existing_dni.name,
                ),
                "danger",
            )
            return _render_user_form(
                edit_mode=True,
                user=user,
                action_url=url_for("admin.edit_operario", user_id=user.id),
                companies=companies,
            )

        existing_email = User.query.filter(
            User.email == new_email, User.id != user.id
        ).first()
        if existing_email:
            flash(translate("Error: El email {email} ya está registrado.", email=new_email), "danger")
            return _render_user_form(
                edit_mode=True,
                user=user,
                action_url=url_for("admin.edit_operario", user_id=user.id),
                companies=companies,
            )

        try:
            from app.services.plan_service import (
                PlanLimitError,
                cuenta_como_empleado,
                exigir_cambio_cupo,
            )
            from app.services.employee_baja_service import dar_de_baja, reactivar

            was_active = bool(user.active)
            nuevo_active = request.form.get("active") == "on"
            ocupar_antes = cuenta_como_empleado(user)
            ocupar_despues = cuenta_como_empleado(
                role=nuevo_rol,
                active=nuevo_active,
                is_deleted=user.is_deleted,
            )
            exigir_cambio_cupo(ocupar_antes, ocupar_despues)

            user.name = (request.form.get("name") or "").strip()
            user.lastname = (request.form.get("lastname") or "").strip()
            user.dni = new_dni
            user.email = new_email
            rol_anterior = user.role
            user.role = nuevo_rol
            if nuevo_rol != rol_anterior:
                from app.services.user_role_sync_service import lock_user_role_manual
                lock_user_role_manual(user)

            company_id = (request.form.get("company_id") or "").strip()
            if company_id:
                user.company_id = int(company_id)
            else:
                user.company_id = None

            user.receive_emails = request.form.get("receive_emails") == "on"
            user.categoria_profesional = (
                request.form.get("categoria_profesional") or ""
            ).strip() or None
            user.especialidad = (
                request.form.get("especialidad") or ""
            ).strip() or None

            # Acceso web gobernado por auth_mode + permisos.
            from app.services.auth_login_service import normalize_auth_mode
            from app.services.tenant_auth_policy import enforce_password_only_user, tenant_usa_acceso_pin
            user.auth_mode = normalize_auth_mode(
                request.form.get('auth_mode'),
                role=nuevo_rol,
            )
            if not tenant_usa_acceso_pin():
                enforce_password_only_user(user)
            user.web_access = True

            if was_active and not nuevo_active:
                dar_de_baja(user, actor_id=current_user.id, motivo='manual', commit=False)
            elif not was_active and nuevo_active:
                reactivar(user, actor_id=current_user.id, commit=False)
            else:
                user.active = nuevo_active
                if nuevo_active:
                    user.deactivation_reason = None
                    user.deactivated_at = None

            db.session.commit()
            flash(translate("Datos actualizados correctamente"), "success")
            from app.utils.nav_back import redirect_back_or
            return redirect_back_or("admin.personal")

        except PlanLimitError as e:
            db.session.rollback()
            flash(translate(str(e)), "danger")
        except Exception as e:
            db.session.rollback()
            flash(translate("Error inesperado al guardar: {error}", error=str(e)), "danger")

    from app.utils.nav_back import resolve_back_url, url_with_back
    return _render_user_form(
        edit_mode=True,
        user=user,
        action_url=url_with_back("admin.edit_operario", user_id=user.id),
        companies=companies,
        cancel_url=resolve_back_url("admin.personal"),
    )




@admin_bp.route("/panel", methods=["GET"])
@login_required
@roles_required(ROLE_ADMIN)
def panel():
    from app.services.permission_service import user_can, can_resolve_fichajes
    from app.services.user_home_service import resolve_inicio_panel_url
    if not user_can(current_user, 'inicio', 'r'):
        flash(translate('Acceso no autorizado'), 'danger')
        return redirect(url_for('main.dashboard'))

    dest = resolve_inicio_panel_url(current_user)
    admin_panel_url = url_for('admin.panel')
    if dest and dest != admin_panel_url:
        return redirect(dest)

    from app.services.panel_service import get_admin_panel_context
    from app.services.onboarding_service import necesita_onboarding, estado_onboarding
    ctx = get_admin_panel_context()
    ctx['mostrar_onboarding'] = necesita_onboarding()
    ctx['onboarding'] = estado_onboarding() if ctx['mostrar_onboarding'] else None
    from app.services.fichaje_operario_service import tenant_muestra_auditoria_fichajes
    ctx['puede_resolver_auditoria'] = (
        can_resolve_fichajes(current_user) and tenant_muestra_auditoria_fichajes()
    )
    return render_template("admin_panel.html", **ctx)


@admin_bp.route("/api/panel/kpi_detail", methods=["GET"])
@login_required
@roles_required(ROLE_ADMIN)
def api_panel_kpi_detail():
    """Detalle tabular de un KPI del panel (fichajes / asignaciones / auditoría)."""
    from app.services.panel_service import get_panel_kpi_detail
    from app.services.fichaje_operario_service import tenant_muestra_auditoria_fichajes

    kind = (request.args.get('kind') or '').strip().lower()
    fecha = (request.args.get('fecha') or '').strip() or None
    if kind in ('fichajes', 'auditoria') and not tenant_muestra_auditoria_fichajes():
        return jsonify({'success': False, 'message': translate('No disponible')}), 403
    try:
        data = get_panel_kpi_detail(kind, fecha)
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    return jsonify({'success': True, **data})


@admin_bp.route("/panel-laboral", methods=["GET"])
@login_required
@roles_required(ROLE_ADMIN, ROLE_LABORAL)
def panel_laboral():
    """Landing de inicio para perfiles laboral / RRHH / custom de jornada."""
    from app.services.permission_service import user_can
    from app.services.user_home_service import resolve_inicio_panel_url
    if not user_can(current_user, 'inicio', 'r'):
        flash(translate('Acceso no autorizado'), 'danger')
        return redirect(url_for('main.dashboard'))
    dest = resolve_inicio_panel_url(current_user)
    laboral_url = url_for('admin.panel_laboral')
    if dest and dest != laboral_url:
        return redirect(dest)

    from app.services.panel_service import get_laboral_panel_context
    from app.services.fichaje_operario_service import tenant_muestra_auditoria_fichajes
    ctx = get_laboral_panel_context(
        current_user,
        puede_ver_auditoria=(
            user_can(current_user, 'auditoria_fichajes', 'r')
            and tenant_muestra_auditoria_fichajes()
        ),
        horizon_days=14,
    )
    return render_template("admin_panel_laboral.html", **ctx)


@admin_bp.route("/primeros-pasos", methods=["GET", "POST"])
@login_required
@roles_required(ROLE_ADMIN)
def primeros_pasos():
    """
    Hub de arranque + Academia permanente de tutoriales cortos.
    """
    from app.services.onboarding_service import (
        academia_visible,
        estado_onboarding,
        marcar_onboarding_completo,
        necesita_onboarding,
        tenant_tiene_onboarding,
    )
    from app.services.demo_data_service import demo_activa, demo_cantidades
    from app.services.tour_catalog_service import evaluate_academia

    if not tenant_tiene_onboarding():
        return redirect(url_for("admin.panel"))

    if request.method == "POST":
        accion = (request.form.get("accion") or "").strip()
        try:
            if accion in ("listo", "saltar"):
                marcar_onboarding_completo()
                try:
                    from app.services.tour_catalog_service import mark_tour_done
                    from app.services.onboarding_service import marcar_tour_autostart
                    mark_tour_done('seed')
                    marcar_tour_autostart()
                except Exception:
                    pass
                flash(translate("Listo. Ya puedes usar SignaPlan a tu ritmo. "
                    "La Academia de tutoriales sigue en el menú."),
                    "success" if accion == "listo" else "info",
                )
                return redirect(url_for("admin.obras_detailed"))
            elif accion == "demo_generar":
                from app.services.demo_data_service import generar_datos_demo
                from app.services.tour_catalog_service import mark_tour_done, set_onboarding_path
                fichaje_raw = (request.form.get("fichaje") or "").strip().lower()
                activar_fichaje = None
                if fichaje_raw in ("1", "true", "si", "sí", "yes"):
                    activar_fichaje = True
                elif fichaje_raw in ("0", "false", "no"):
                    activar_fichaje = False
                qty = generar_datos_demo(
                    actor_user=current_user,
                    activar_fichaje=activar_fichaje,
                )
                try:
                    set_onboarding_path('demo')
                    mark_tour_done('demo')
                except Exception:
                    pass
                flash(
                    translate(
                        "Datos de ejemplo listos: {obras} obras, "
                        "{empleados} trabajadores, {vehiculos} vehículos. "
                        "Ya tienes material para los siguientes tutoriales.",
                        obras=qty['obras'],
                        empleados=qty['empleados'],
                        vehiculos=qty['vehiculos'],
                    ),
                    "success",
                )
                return redirect(url_for("admin.primeros_pasos", focus="next", demo="1"))
            elif accion == "elegir_camino":
                from app.services.tour_catalog_service import set_onboarding_path
                camino = (request.form.get("camino") or "").strip().lower()
                set_onboarding_path(camino)
                if camino == "guide":
                    return redirect(url_for("admin.primeros_pasos", tour="start"))
                if camino == "skip":
                    marcar_onboarding_completo()
                    flash(translate("Listo. Ya puedes usar SignaPlan a tu ritmo. "
                        "La Academia de tutoriales sigue en el menú."),
                        "info",
                    )
                    return redirect(url_for("admin.panel"))
                return redirect(url_for("admin.primeros_pasos"))
            elif accion == "demo_borrar":
                from app.services.demo_data_service import borrar_datos_demo
                from app.services.config_service import set_tenant_config
                from app.services.onboarding_service import CONFIG_ONBOARDING
                borrar_datos_demo()
                destino = (request.form.get("despues") or "panel").strip()
                flash(translate("Datos de ejemplo eliminados."), "success")
                if destino == "wizard":
                    set_tenant_config(CONFIG_ONBOARDING, "False")
                    return redirect(url_for("admin.primeros_pasos"))
                return redirect(url_for("admin.panel"))
            else:
                raise ValueError(translate("Acción no reconocida."))
        except ValueError as exc:
            db.session.rollback()
            flash(translate(str(exc)), "danger")
        except Exception as exc:
            db.session.rollback()
            flash(translate("No se ha podido completar la acción: {error}", error=exc), "danger")

        return redirect(url_for("admin.primeros_pasos"))

    # Al terminar la guía, el JS vuelve con ?done=seed — persistir el tic aunque
    # el POST /api/tour/seed/complete se hubiera perdido en la navegación.
    if (request.args.get("done") or "").strip().lower() == "seed":
        from app.services.tour_catalog_service import mark_tour_done
        try:
            mark_tour_done("seed")
        except Exception:
            pass
        # Evitar re-marcar en F5: limpiar el query param
        focus = (request.args.get("focus") or "guide").strip() or "guide"
        return redirect(url_for("admin.primeros_pasos", focus=focus))

    estado = estado_onboarding()
    academia = evaluate_academia(current_user)
    show_start = necesita_onboarding()

    if not show_start and not academia_visible():
        flash(
            translate("La Academia está oculta. Puedes volver a mostrarla en Configuración."),
            "info",
        )
        return redirect(url_for("admin.panel"))

    return render_template(
        "admin_primeros_pasos.html",
        onboarding=estado,
        demo_cantidades=demo_cantidades(),
        demo_activa=demo_activa(),
        empresa_vacia=estado.get("empresa_vacia", False),
        academia=academia,
        show_start_cards=show_start,
    )


@admin_bp.route("/api/tour/<tour_id>/start", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def api_tour_start(tour_id):
    from app.services.tour_catalog_service import mark_tour_started, evaluate_academia
    try:
        mark_tour_started(tour_id)
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    return jsonify({'success': True, 'academia': evaluate_academia(current_user)})


@admin_bp.route("/api/tour/complete-many", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def api_tour_complete_many():
    from app.services.tour_catalog_service import mark_tours_done, evaluate_academia
    data = request.get_json(silent=True) or {}
    ids = data.get('ids') or []
    if not isinstance(ids, list):
        return jsonify({'success': False, 'message': 'ids inválidos'}), 400
    mark_tours_done([str(x) for x in ids if x])
    return jsonify({'success': True, 'academia': evaluate_academia(current_user)})


@admin_bp.route("/api/tour/<tour_id>/complete", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def api_tour_complete(tour_id):
    from app.services.tour_catalog_service import mark_tour_done, evaluate_academia
    try:
        mark_tour_done(tour_id)
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    return jsonify({'success': True, 'academia': evaluate_academia(current_user)})


@admin_bp.route("/api/tour/fichaje", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def api_tour_fichaje():
    """Activa/desactiva fichaje operario desde la guía interactiva."""
    from app.services.config_service import set_tenant_config
    from app.services.fichaje_operario_service import (
        CONFIG_FICHAJE_OPERARIO,
        marcar_fichaje_preferencia_decidida,
        tenant_tiene_fichaje_operario_module,
    )
    data = request.get_json(silent=True) or {}
    activo = bool(data.get('activo'))
    if activo and not tenant_tiene_fichaje_operario_module():
        return jsonify({
            'success': False,
            'message': translate('Este espacio no tiene el módulo de fichaje operario.'),
        }), 400
    set_tenant_config(CONFIG_FICHAJE_OPERARIO, 'True' if activo else 'False')
    marcar_fichaje_preferencia_decidida()
    return jsonify({'success': True, 'activo': activo})


@admin_bp.route("/api/tour/fichaje-demo", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def api_tour_fichaje_demo():
    """Borra el fichaje de prueba del recorrido inicial (no el de un día real)."""
    from app.services.fichaje_operario_service import borrar_fichaje_tutorial

    data = request.get_json(silent=True) or {}
    dni = (data.get('dni') or '').strip()
    if not dni:
        return jsonify({'success': False, 'message': translate('Falta el DNI.')}), 400
    try:
        ok = borrar_fichaje_tutorial(dni)
    except Exception:
        db.session.rollback()
        current_app.logger.exception('No se pudo borrar el fichaje de prueba del tour')
        return jsonify({'success': False}), 500
    return jsonify({'success': True, 'deleted': bool(ok)})


@admin_bp.route("/tour/fichaje-probar", methods=["GET"])
@login_required
@roles_required(ROLE_ADMIN)
def tour_fichaje_probar():
    """
    Cierra la sesión de oficina y abre el login para que el admin
    pruebe el fichaje como el operario creado en la guía.
    Guarda el id del admin para poder volver al tablero después.
    Activa la obra «Oficina» y la deja preseleccionada en Fichaje (tutorial).
    """
    from flask import session
    from flask_login import logout_user
    from app.services.config_service import set_tenant_config
    from app.services.fichaje_operario_service import (
        activar_fichajes_alta,
        fichaje_operario_activo,
        tenant_tiene_fichaje_operario_module,
    )
    from app.services.oficina_obra_service import (
        CONFIG_OBRA_OFICINA,
        sincronizar_obra_oficina,
    )

    if not tenant_tiene_fichaje_operario_module():
        flash(
            translate('Este espacio no tiene fichaje de operarios. No se puede probar el fichaje.'),
            'warning',
        )
        return redirect(url_for('admin.obras_detailed'))

    if not fichaje_operario_activo():
        try:
            activar_fichajes_alta()
        except Exception:
            db.session.rollback()
            current_app.logger.exception('No se pudo activar fichaje para el tutorial')

    if not fichaje_operario_activo():
        flash(
            translate('No se ha podido abrir el fichaje. Actívalo en Configuración → Fichajes.'),
            'warning',
        )
        return redirect(url_for('admin.obras_detailed'))

    try:
        set_tenant_config(CONFIG_OBRA_OFICINA, 'True')
        sincronizar_obra_oficina(True)
        db.session.commit()
    except Exception:
        db.session.rollback()

    chapter = (request.args.get('chapter') or 'fichajes').strip() or 'fichajes'
    if chapter not in ('fichaje', 'fichajes'):
        chapter = 'fichajes'

    force_oficina = (request.args.get('oficina') or '1').strip() != '0'

    session['tour_admin_user_id'] = current_user.id
    session['tour_fichar_oficina'] = force_oficina
    session['tour_chapter'] = chapter
    logout_user()
    # tour=mi + chapter: no reinicia la guía ni cae al tutorial seed viejo.
    return redirect(url_for('auth.login', tour='mi', chapter=chapter))


@admin_bp.route("/create_obra", methods=["GET", "POST"])
@login_required
@roles_required(ROLE_ADMIN)
def create_obra():
    jefes = (
        User.query.filter(
            User.role.in_([ROLE_JEFE, ROLE_ADMIN]),
            User.is_deleted.is_(False),
            User.active.is_(True),
        )
        .order_by(User.name, User.lastname)
        .all()
    )
    encargados = (
        User.query.join(Company)
        .filter(
            User.role == ROLE_OPERARIO,
            User.active.is_(True),
            User.is_deleted.is_(False),
            Company.is_internal.is_(True),
        )
        .order_by(User.name)
        .all()
    )
    defaults = {
        'fecha_inicio': '',
        'fecha_fin': '',
        'estado': 'En Curso',
        'jefe_obra_id': '',
    }

    def _render_create(form_data):
        from app.services.geocerca_service import radio_default_metros
        return render_template(
            "create_obra.html",
            jefes=jefes,
            encargados=encargados,
            form_data=form_data,
            defaults=defaults,
            return_to=_return_to_key(),
            cancel_url=_cancel_url_after_create('admin.obras_list'),
            radio_default=radio_default_metros(),
        )

    if request.method == "POST":
        codigo = (request.form.get("codigo") or "").strip() or None
        jefe_obra_id = (request.form.get("jefe_obra_id") or "").strip()
        nombre = (request.form.get("nombre") or "").strip()
        fecha_inicio = (request.form.get("fecha_inicio") or "").strip()
        fecha_fin = (request.form.get("fecha_fin") or "").strip()
        estado = (request.form.get("estado") or "En Curso").strip() or "En Curso"

        if not nombre:
            flash(translate("El nombre de la obra es obligatorio."), "danger")
            return _render_create(request.form)

        if not fecha_fin and fecha_inicio:
            try:
                ini = parse_date(fecha_inicio)
                fecha_fin = date(ini.year + 1, ini.month, ini.day).isoformat()
            except Exception:
                fecha_fin = defaults['fecha_fin']

        if codigo:
            existe = Obra.query.filter_by(codigo=codigo).first()
            if existe:
                flash(
                    translate(
                        "Error: El código '{codigo}' ya existe en la obra '{obra}'.",
                        codigo=codigo,
                        obra=existe.nombre,
                    ),
                    "danger",
                )
                return _render_create(request.form)

        try:
            color = (request.form.get("color") or "").strip()
            if not color:
                from app.models import generate_random_color
                color = generate_random_color()

            encargado_id = (request.form.get("encargado_id") or "").strip()
            nueva_obra = Obra(
                codigo=codigo,
                nombre=nombre,
                descripcion=(request.form.get("descripcion") or "").strip() or None,
                ubicacion=(request.form.get("ubicacion") or "").strip() or None,
                fecha_inicio=parse_date(fecha_inicio) if fecha_inicio else None,
                fecha_fin=parse_date(fecha_fin) if fecha_fin else None,
                estado=estado,
                jefe_obra_id=int(jefe_obra_id) if jefe_obra_id else None,
                encargado_id=int(encargado_id) if encargado_id else None,
                color=color,
            )
            from app.utils.obra_geo import aplicar_obra_geo_form
            aplicar_obra_geo_form(nueva_obra, request.form)
            db.session.add(nueva_obra)
            db.session.commit()

            from app.utils import register_log
            register_log(
                user_id=current_user.id,
                category='obras',
                action='Crear Obra',
                detail=f"Ha creado la obra '{nombre}'"
                + (f" (Código: {codigo})" if codigo else ""),
            )

            flash(translate("Obra creada exitosamente"), "success")
            redirect_kwargs = {"obra": nueva_obra.id}
            if nueva_obra.fecha_inicio:
                redirect_kwargs["selected_date"] = nueva_obra.fecha_inicio.strftime("%Y-%m-%d")
            return _redirect_after_create("admin.obras_detailed", **redirect_kwargs)
        except Exception as e:
            db.session.rollback()
            flash(translate("Error al guardar: {error}", error=str(e)), "danger")
            return _render_create(request.form)

    return _render_create({})


@admin_bp.route("/edit_obra/<int:obra_id>", methods=["GET", "POST"])
@login_required
@roles_required(ROLE_ADMIN)
def edit_obra(obra_id):
    from app.services.geocerca_service import radio_default_metros

    radio_default = radio_default_metros()
    obra = Obra.query.get_or_404(obra_id)
    jefes = (
        User.query.filter(
            User.role.in_([ROLE_JEFE, ROLE_ADMIN]),
            User.is_deleted.is_(False),
            User.active.is_(True),
        )
        .order_by(User.name, User.lastname)
        .all()
    )
    encargados = (
        User.query.join(Company)
        .filter(
            User.role == ROLE_OPERARIO,
            User.active.is_(True),
            User.is_deleted.is_(False),
            Company.is_internal.is_(True),
        )
        .order_by(User.name)
        .all()
    )

    if request.method == "POST":
        new_codigo = (request.form.get("codigo") or "").strip() or None
        new_jefe_id = (request.form.get("jefe_obra_id") or "").strip()
        nombre = (request.form.get("nombre") or "").strip()

        if not nombre:
            flash(translate("El nombre de la obra es obligatorio."), "danger")
            return render_template(
                "edit_obra.html", obra=obra, jefes=jefes,
                encargados=encargados, form_data=request.form,
                radio_default=radio_default,
            )

        if new_codigo and new_codigo != obra.codigo:
            existe = Obra.query.filter(Obra.codigo == new_codigo, Obra.id != obra.id).first()
            if existe:
                flash(translate("Error: El código '{codigo}' ya está en uso en '{obra}'.", codigo=new_codigo, obra=existe.nombre), "danger")
                return render_template("edit_obra.html", obra=obra, jefes=jefes, encargados=encargados, form_data=request.form, radio_default=radio_default)

        obra.codigo = new_codigo
        obra.jefe_obra_id = int(new_jefe_id) if new_jefe_id else None
        obra.nombre = nombre
        obra.descripcion = (request.form.get("descripcion") or "").strip() or None
        obra.color = request.form.get("color") or obra.color

        old_estado = obra.estado
        new_estado = request.form.get("estado") or obra.estado
        obra.estado = new_estado

        f_inicio = (request.form.get("fecha_inicio") or "").strip()
        f_fin = (request.form.get("fecha_fin") or "").strip()
        obra.fecha_inicio = parse_date(f_inicio) if f_inicio else None
        obra.fecha_fin = parse_date(f_fin) if f_fin else None

        enc_id = (request.form.get("encargado_id") or "").strip()
        obra.encargado_id = int(enc_id) if enc_id else None

        today = date.today()
        actor_id = current_user.id
        obra_nombre = obra.nombre
        if new_estado == 'Pendiente' and old_estado != 'Pendiente':
            futuras = (
                Asignacion.query.filter(Asignacion.obra_id == obra.id, Asignacion.fecha >= today)
                .with_entities(Asignacion.user_id, Asignacion.obra_id, Asignacion.fecha)
                .all()
            )
            for uid, oid, fecha in futuras:
                CoreAssignmentService.desasignar(
                    uid, oid, fecha, actor_id,
                    "Pausa de Obra", f"Obra '{obra_nombre}' pausada.",
                    registrar_log=False,
                )
            if futuras:
                from app.utils import register_log
                register_log(
                    user_id=actor_id,
                    category='planificacion',
                    action='Pausa de Obra',
                    detail=f"Obra '{obra_nombre}' pausada: {len(futuras)} asignaciones futuras eliminadas.",
                )
                flash(translate("Obra pausada. {count} asignaciones eliminadas.", count=len(futuras)), "warning")
            from app.services.inercia_service import cortar_casa_de_obra
            cortar_casa_de_obra(obra.id, today, actor_id)
        elif new_estado == 'Finalizada' and old_estado != 'Finalizada':
            obra.fecha_fin = today
            futuras = (
                Asignacion.query.filter(Asignacion.obra_id == obra.id, Asignacion.fecha >= today)
                .with_entities(Asignacion.user_id, Asignacion.obra_id, Asignacion.fecha)
                .all()
            )
            for uid, oid, fecha in futuras:
                CoreAssignmentService.desasignar(
                    uid, oid, fecha, actor_id,
                    "Finalización de Obra", f"Obra '{obra_nombre}' finalizada.",
                    registrar_log=False,
                )
            if futuras:
                from app.utils import register_log
                register_log(
                    user_id=actor_id,
                    category='planificacion',
                    action='Finalización de Obra',
                    detail=f"Obra '{obra_nombre}' finalizada: {len(futuras)} asignaciones futuras eliminadas.",
                )
            flash(translate("Obra finalizada. {count} asignaciones eliminadas.", count=len(futuras)), "success")
            from app.services.inercia_service import cortar_casa_de_obra
            cortar_casa_de_obra(obra.id, today, actor_id)

        try:
            db.session.commit()
            from app.utils import register_log
            register_log(
                user_id=actor_id,
                category='obras',
                action='Editar Obra',
                detail=f"Ha editado la obra '{obra_nombre}'. Estado actual: {obra.estado}"
            )
            flash(translate("Obra actualizada correctamente"), "success")
            from app.utils.nav_back import redirect_back_or
            return redirect_back_or("admin.obra_panel", obra_id=obra.id)
        except Exception as e:
            db.session.rollback()
            flash(translate("Error al actualizar: {error}", error=str(e)), "danger")
            return render_template("edit_obra.html", obra=obra, jefes=jefes, encargados=encargados, form_data=request.form, radio_default=radio_default)

    return render_template("edit_obra.html", obra=obra, jefes=jefes, encargados=encargados, form_data={}, radio_default=radio_default)



@admin_bp.route("/company/<int:company_id>/confirm_delete", methods=["GET"])
@login_required
@roles_required(ROLE_ADMIN, redirect_to="admin.companies")
def confirm_delete_company(company_id):
    company = Company.query.get_or_404(company_id)
    
    # CORREGIDO: Filtrar por company_id, NO por company_code
    operarios = User.query.filter_by(
        role=ROLE_OPERARIO, 
        company_id=company.id,  # <--- CAMBIO AQUÍ
        is_deleted=False
    ).all()
    
    companies = Company.query.filter(Company.id != company.id).all()
    
    return render_template(
        "confirm_delete_company.html",
        company=company,
        operarios=operarios,
        companies=companies,
    )
    
@admin_bp.route("/company/<int:company_id>/delete", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN, redirect_to="admin.companies")
def delete_company(company_id):
    company = Company.query.get_or_404(company_id)
    
    # CORREGIDO: Filtrar por ID
    associated_workers = User.query.filter_by(
        role=ROLE_OPERARIO, 
        company_id=company.id # <--- CAMBIO AQUÍ
    ).all()
    
    action_option = request.form.get("action_option")
    if associated_workers and action_option:
        if action_option == "reassign":
            new_company_id = request.form.get("new_company") # Recibimos ID del form
            if not new_company_id:
                flash(translate("Debe seleccionar una empresa para reasignar"), "danger")
                return redirect(url_for("admin.confirm_delete_company", company_id=company_id))
            
            # Convertir a int
            new_company = Company.query.get(int(new_company_id))
            if not new_company:
                 flash(translate("Empresa destino no válida"), "danger")
                 return redirect(url_for("admin.confirm_delete_company", company_id=company_id))

            for worker in associated_workers:
                worker.company_id = new_company.id # <--- ASIGNAR ID
                
        elif action_option == "delete":
            for worker in associated_workers:
                worker.soft_delete(actor_id=current_user.id)
                worker.company_id = None

    # --- NUEVO: LIMPIEZA DE INTEGRIDAD REFERENCIAL ---
    from app.models import Asignacion
    
    # 1. Quitamos la empresa de cualquier asignación histórica que la tenga
    Asignacion.query.filter_by(company_id=company.id).update({"company_id": None})
    
    # 2. Por seguridad, si ha quedado algún usuario "fantasma" (incluso inactivo o de otro rol) con esta empresa, se la quitamos
    User.query.filter_by(company_id=company.id).update({"company_id": None})
    
    # Ahora la BD permite el borrado sin lanzar ForeignKeyViolation
    db.session.delete(company)
    db.session.commit()
    
    flash(translate("Empresa eliminada correctamente"), "success")
    return redirect(url_for("admin.companies"))



@admin_bp.route("/reset_password/<int:user_id>", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def reset_password(user_id):
    new_password = request.form.get("new_password")
    user = User.query.get(user_id)
    if user:
        user.password_hash = generate_password_hash(new_password)
        db.session.commit()
        flash(translate("Contraseña restablecida"), "success")
    else:
        flash(translate("Usuario no encontrado"), "danger")
    return redirect(url_for("admin.personal"))


@admin_bp.route("/enviar_acceso_fichaje/<int:user_id>", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def enviar_acceso_fichaje(user_id):
    """Asigna/regenera PIN y envía enlace para que el trabajador lo defina."""
    from app.services.pin_auth_service import PinAuthError, enviar_acceso_fichaje as _enviar

    user = User.query.get_or_404(user_id)
    if user.role != ROLE_OPERARIO:
        flash(translate('Solo los operarios usan PIN de fichaje. El resto entra con correo y contraseña.'), 'warning')
        return redirect(url_for('admin.edit_operario', user_id=user.id))

    email = (request.form.get('email') or '').strip()
    if email:
        user.email = email
    elif not user.email or '@demo.signaplan' in (user.email or '') or '@local.signaplan' in (user.email or ''):
        flash(translate('Indica un correo real para enviar el enlace de definir PIN.'), 'danger')
        return redirect(url_for('admin.edit_operario', user_id=user.id))

    pin = (request.form.get('nuevo_pin') or '').strip()
    regenerar = bool(request.form.get('regenerar'))
    try:
        ok, pin_usado = _enviar(
            user,
            pin_plano=pin or None,
            actor=current_user,
            regenerar=regenerar or not pin,
        )
        db.session.commit()
        if ok:
            extra = translate(' PIN provisional (solo visible aquí): {pin}.', pin=pin_usado) if pin_usado else ''
            flash(
                translate(
                    'Enlace para definir PIN enviado a {email}.{extra}',
                    email=user.email,
                    extra=extra,
                ),
                'success',
            )
        else:
            pin_bit = f' ({pin_usado})' if pin_usado else ''
            flash(
                translate(
                    'PIN preparado{pin}, pero no se pudo enviar el correo. Revisa SMTP o entrégaselo en mano.',
                    pin=pin_bit,
                ),
                'warning',
            )
    except PinAuthError as exc:
        db.session.rollback()
        flash(translate(str(exc)), 'danger')
    except Exception as exc:
        db.session.rollback()
        flash(translate('No se ha podido enviar el acceso: {error}', error=exc), 'danger')

    return redirect(url_for('admin.edit_operario', user_id=user.id))


@admin_bp.route("/enviar_informacion_acceso/<int:user_id>", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def enviar_informacion_acceso(user_id):
    """Envía instrucciones de acceso (URL, DNI, enlace PIN). Sin PIN en claro."""
    from app.services.pin_auth_service import notificar_informacion_acceso

    user = User.query.get_or_404(user_id)
    if user.role != ROLE_OPERARIO:
        flash(translate('Solo aplica a operarios (acceso con DNI + PIN).'), 'warning')
        return redirect(url_for('admin.edit_operario', user_id=user.id))

    email = (request.form.get('email') or '').strip()
    if email:
        user.email = email
    elif not user.email or '@demo.signaplan' in (user.email or '') or '@local.signaplan' in (user.email or ''):
        flash(translate('Indica un correo real para enviar las instrucciones de acceso.'), 'danger')
        return redirect(url_for('admin.edit_operario', user_id=user.id))

    try:
        ok = notificar_informacion_acceso(user, actor=current_user)
        db.session.commit()
        if ok:
            flash(
                translate('Instrucciones de acceso enviadas a {email}.', email=user.email),
                'success',
            )
        else:
            flash(
                translate(
                    'No se pudo enviar el correo. Revisa SMTP o copia las instrucciones a mano.'
                ),
                'warning',
            )
    except Exception as exc:
        db.session.rollback()
        flash(translate('No se ha podido enviar el acceso: {error}', error=exc), 'danger')

    return redirect(url_for('admin.edit_operario', user_id=user.id))


@admin_bp.route("/reset_pin/<int:user_id>", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def reset_pin(user_id):
    """
    Asigna o cambia el PIN de fichaje de un trabajador.

    El PIN solo se muestra al guardarlo aquí: después queda hasheado y no se
    puede recuperar, igual que una contraseña. El correo nunca lleva el PIN
    en claro: envía un enlace para definirlo.
    """
    from app.services.pin_auth_service import PinAuthError, asignar_pin, quitar_pin
    from app.services.tenant_auth_policy import tenant_usa_acceso_pin

    user = User.query.get_or_404(user_id)
    if not tenant_usa_acceso_pin():
        flash(translate('Este cliente no usa PIN de fichaje.'), 'warning')
        dest = (request.form.get('next') or '').strip() or url_for('admin.edit_operario', user_id=user.id)
        return redirect(dest)
    if user.role != ROLE_OPERARIO:
        flash(translate('Solo los operarios usan PIN de fichaje.'), 'warning')
        dest = (request.form.get('next') or '').strip() or url_for('admin.edit_operario', user_id=user.id)
        return redirect(dest)
    accion = (request.form.get('accion') or 'asignar').strip()
    next_url = (request.form.get('next') or '').strip()

    try:
        if accion == 'quitar':
            quitar_pin(user)
            db.session.commit()
            flash(translate('PIN de fichaje eliminado para {name}.', name=f'{user.name} {user.lastname}'), 'success')
        elif accion == 'generar':
            from app.services.pin_auth_service import asignar_pin_generado
            _, pin_plano = asignar_pin_generado(
                user, notify=True, actor=current_user
            )
            db.session.commit()
            mail_msg = (
                translate(' Se ha enviado un enlace por correo para que lo defina.')
                if user.email else ''
            )
            flash(
                translate(
                    'PIN provisional para {name}: {pin}. '
                    'Debe cambiarlo en el primer acceso (o con el enlace del correo).'
                    '{mail}',
                    name=f'{user.name} {user.lastname}',
                    pin=pin_plano,
                    mail=mail_msg,
                ),
                'success',
            )
        else:
            from app.services.pin_auth_service import asignar_pin_explicito
            pin = request.form.get('nuevo_pin')
            asignar_pin_explicito(user, pin, notify=True, actor=current_user)
            db.session.commit()
            mail_msg = (
                translate(' Se ha enviado un enlace por correo para que pueda redefinirlo.')
                if user.email else ''
            )
            flash(
                translate(
                    'PIN de fichaje actualizado para {name}.{mail}',
                    name=f'{user.name} {user.lastname}',
                    mail=mail_msg,
                ),
                'success',
            )
    except PinAuthError as exc:
        db.session.rollback()
        flash(translate(str(exc)), 'danger')

    if next_url.startswith('/admin/'):
        return redirect(next_url)
    return redirect(url_for('admin.personal'))


@admin_bp.route("/delete_user/<int:user_id>", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def delete_user(user_id):
    user = User.query.get(user_id)
    if user:
        user.soft_delete(actor_id=current_user.id)
        db.session.commit()
        flash(translate("Usuario eliminado y archivado. Se han removido asignaciones futuras."),
            "success",
        )
    else:
        flash(translate("Usuario no encontrado"), "danger")
    return redirect(url_for("admin.personal"))


def _email_placeholder_desde_dni(dni):
    base = (dni or '').strip().lower().replace(' ', '').replace('-', '')
    return f"{base}@local.signaplan"


def _email_parece_real_form(email):
    from app.services.pin_auth_service import _email_parece_real
    return _email_parece_real(email)


def _default_internal_company_id():
    interna = Company.query.filter_by(is_internal=True).order_by(Company.id.asc()).first()
    return interna.id if interna else None


def _render_user_form(*, edit_mode, user, action_url, companies=None, return_to='', cancel_url=None, default_role=''):
    from app.utils.nav_back import resolve_back_url
    from app.services.role_registry_service import list_roles
    if companies is None:
        keep_id = getattr(user, 'company_id', None) if user else None
        companies = Company.query.filter(
            or_(Company.active.is_(True), Company.id == keep_id) if keep_id
            else Company.active.is_(True)
        ).order_by(
            Company.is_internal.desc(), Company.nombre.asc()
        ).all()
    return render_template(
        "gestion_operario_form.html",
        edit_mode=edit_mode,
        user=user,
        action_url=action_url,
        cancel_url=cancel_url or resolve_back_url("admin.personal"),
        return_to=return_to,
        default_role=default_role,
        companies=companies,
        default_company_id=_default_internal_company_id(),
        assignable_roles=list_roles(),
    )


@admin_bp.route("/create_user", methods=["GET", "POST"])
@login_required
@roles_required(ROLE_ADMIN)
def create_user():
    if request.method == "POST":
        import secrets

        from app.services.pin_auth_service import (
            PinAuthError,
            asignar_pin_explicito,
            enviar_acceso_fichaje as _enviar_acceso_fichaje,
        )
        from app.services.plan_service import PlanLimitError, exigir_alta_empleado

        role = (request.form.get("role") or ROLE_OPERARIO).strip()
        from app.services.role_registry_service import valid_role_keys
        if role not in valid_role_keys():
            flash(translate("Rol no válido."), "danger")
            return redirect(_url_with_return_to("admin.create_user"))

        name = (request.form.get("name") or "").strip()
        lastname = (request.form.get("lastname") or "").strip()
        dni = (request.form.get("dni") or "").strip().upper()
        company_id = (request.form.get("company_id") or "").strip()
        active = request.form.get("active") == "on"
        categoria = (request.form.get("categoria_profesional") or "").strip() or None
        especialidad = (request.form.get("especialidad") or "").strip() or None
        receive_emails = request.form.get("receive_emails") == "on"
        pin_mode = (request.form.get("pin_mode") or "manual").strip()

        if not name or not lastname or not dni:
            flash(translate("Nombre, apellidos y DNI son obligatorios."), "danger")
            return redirect(_url_with_return_to("admin.create_user"))

        if User.query.filter_by(dni=dni).first():
            flash(translate("Error: El DNI {dni} ya pertenece a otro usuario.", dni=dni), "danger")
            return redirect(_url_with_return_to("admin.create_user"))

        if role == ROLE_OPERARIO:
            email_link = (
                request.form.get("email") or request.form.get("email_advanced") or ""
            ).strip().lower()
            if pin_mode == "email_link":
                if not _email_parece_real_form(email_link):
                    flash(translate("Para enviar el enlace de PIN indica un correo electrónico real."),
                        "danger",
                    )
                    return redirect(_url_with_return_to("admin.create_user"))
                email = email_link
            else:
                pin_form = (request.form.get("pin") or "").strip()
                if not pin_form:
                    flash(translate("Indica un PIN de 4 a 6 dígitos, o elige enviar enlace por correo."), "danger")
                    return redirect(_url_with_return_to("admin.create_user"))
                email_opt = (
                    request.form.get("email_advanced") or request.form.get("email") or ""
                ).strip().lower()
                email = email_opt if _email_parece_real_form(email_opt) else _email_placeholder_desde_dni(dni)
            password_hash = generate_password_hash(secrets.token_urlsafe(32))
            web_access = True
        else:
            email = (
                request.form.get("email_office")
                or request.form.get("email")
                or ""
            ).strip().lower()
            password = request.form.get("password") or ""
            if not _email_parece_real_form(email):
                flash(translate("Email obligatorio para perfiles de oficina."), "danger")
                return redirect(_url_with_return_to("admin.create_user"))
            if len(password) < 8:
                flash(translate("La contraseña debe tener al menos 8 caracteres."), "danger")
                return redirect(_url_with_return_to("admin.create_user"))
            password_hash = generate_password_hash(password)
            web_access = True
            pin_mode = "none"

        from app.services.auth_login_service import default_auth_mode_for_role, normalize_auth_mode
        from app.services.tenant_auth_policy import enforce_password_only_user, tenant_usa_acceso_pin
        auth_mode = normalize_auth_mode(
            request.form.get('auth_mode'),
            role=role,
        ) if request.form.get('auth_mode') else default_auth_mode_for_role(role)
        if not tenant_usa_acceso_pin():
            auth_mode = 'password'
            pin_mode = 'none'

        if User.query.filter_by(email=email).first():
            flash(translate("Error: El email {email} ya está registrado.", email=email), "danger")
            return redirect(_url_with_return_to("admin.create_user"))

        if not company_id:
            default_cid = _default_internal_company_id()
            company_id = str(default_cid) if default_cid else ""

        try:
            exigir_alta_empleado(role=role, active=active)
        except PlanLimitError as exc:
            flash(translate(str(exc)), "danger")
            return redirect(_url_with_return_to("admin.create_user"))

        new_user = User(
            email=email,
            password_hash=password_hash,
            role=role,
            name=name,
            lastname=lastname,
            dni=dni,
            company_id=int(company_id) if company_id else None,
            active=active,
            email_verified=True,
            web_access=web_access,
            auth_mode=auth_mode,
            receive_emails=receive_emails,
            categoria_profesional=categoria,
            especialidad=especialidad,
            deactivation_reason=None if active else 'pending',
            deactivated_at=None,
        )
        db.session.add(new_user)
        db.session.flush()
        if not tenant_usa_acceso_pin():
            enforce_password_only_user(new_user)

        pin_msg = ""
        try:
            if role == ROLE_OPERARIO and pin_mode == "email_link":
                ok, pin_usado = _enviar_acceso_fichaje(
                    new_user, pin_plano=None, actor=current_user, regenerar=True,
                )
                if ok:
                    pin_msg = translate(" Enlace para definir PIN enviado a {email}.", email=email)
                    if pin_usado:
                        pin_msg += translate(" PIN provisional (solo aquí): {pin}.", pin=pin_usado)
                else:
                    pin_bit = f' ({pin_usado})' if pin_usado else ''
                    pin_msg = translate(
                        " PIN preparado{pin}, pero no se pudo enviar el correo.",
                        pin=pin_bit,
                    )
            elif role == ROLE_OPERARIO:
                pin_form = (request.form.get("pin") or "").strip()
                asignar_pin_explicito(
                    new_user, pin_form, notify=False, actor=current_user
                )
                pin_msg = translate(" PIN asignado (DNI + PIN en la aplicación).")
        except PinAuthError as exc:
            db.session.rollback()
            flash(translate(str(exc)), "danger")
            return redirect(_url_with_return_to("admin.create_user"))

        db.session.commit()
        flash(translate("Usuario creado exitosamente.{pin_msg}", pin_msg=pin_msg), "success")
        return _redirect_after_create("admin.personal")

    return_to = _return_to_key()
    return _render_user_form(
        edit_mode=False,
        user=User(),
        action_url=_url_with_return_to("admin.create_user"),
        return_to=return_to,
        cancel_url=_cancel_url_after_create("admin.personal"),
        default_role=_create_user_default_role(),
    )


@admin_bp.route("/approve_operario/<int:user_id>", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def approve_operario(user_id):
    user = User.query.get_or_404(user_id)
    if user.role == ROLE_OPERARIO:
        from app.services.plan_service import (
            PlanLimitError,
            cuenta_como_empleado,
            exigir_cambio_cupo,
        )
        try:
            exigir_cambio_cupo(
                cuenta_como_empleado(user),
                cuenta_como_empleado(role=user.role, active=True, is_deleted=user.is_deleted),
            )
            user.active = True
            db.session.commit()
            flash(translate("Operario activado"), "success")
        except PlanLimitError as exc:
            flash(translate(str(exc)), "danger")
    else:
        flash(translate("El usuario no es un operario"), "danger")
    return redirect(url_for("admin.personal", tab="operarios"))





@admin_bp.route("/delete_obra/<int:obra_id>", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def delete_obra(obra_id):
    obra = Obra.query.get(obra_id)
    if not obra:
        flash(translate("Obra no encontrada"), "danger")
        return redirect(url_for("admin.panel"))

    today = date.today()
    obra.is_deleted = True
    actor_id = current_user.id
    obra_nombre = obra.nombre

    future_rows = [
        (a.user_id, a.obra_id, a.fecha)
        for a in obra.asignaciones if a.fecha >= today
    ]
    for uid, oid, fecha in future_rows:
        CoreAssignmentService.desasignar(
            uid, oid, fecha, actor_id,
            "Eliminación de Obra", f"Obra '{obra_nombre}' eliminada.",
            registrar_log=False,
        )
    if future_rows:
        from app.utils import register_log
        register_log(
            user_id=actor_id,
            category='planificacion',
            action='Eliminación de Obra',
            detail=f"Obra '{obra_nombre}' eliminada: {len(future_rows)} asignaciones futuras liberadas.",
        )

    db.session.commit()

    flash(translate("Obra eliminada. Se desasignaron solo las asignaciones futuras."),
        "success",
    )
    return redirect(url_for("admin.panel"))


@admin_bp.route("/import_users", methods=["GET", "POST"])
@login_required
@roles_required(ROLE_ADMIN)
def import_users():
    if request.method == "POST":
        return _handle_import_upload_post("users")
    return _render_import_upload("users")


@admin_bp.route("/import_users/preview", methods=["GET", "POST"])
@login_required
@roles_required(ROLE_ADMIN)
def import_users_preview():
    return _handle_import_preview("users")


@admin_bp.route("/import_users/confirm", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def import_users_confirm():
    return _handle_import_confirm("users")


@admin_bp.route("/import_companies", methods=["GET", "POST"])
@login_required
@roles_required(ROLE_ADMIN)
def import_companies():
    if request.method == "POST":
        return _handle_import_upload_post("companies")
    return _render_import_upload("companies")


@admin_bp.route("/import_companies/preview", methods=["GET", "POST"])
@login_required
@roles_required(ROLE_ADMIN)
def import_companies_preview():
    return _handle_import_preview("companies")


@admin_bp.route("/import_companies/confirm", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def import_companies_confirm():
    return _handle_import_confirm("companies")


@admin_bp.route("/active_obras", methods=["GET"])
@login_required
def active_obras():
    if not (
        user_can(current_user, 'directorio', 'r')
        or user_can(current_user, 'planificador', 'r')
        or user_can(current_user, 'tablero', 'r')
    ):
        return jsonify([]), 403
    start_date_str = request.args.get("start_date")
    end_date_str = request.args.get("end_date")
    if not start_date_str or not end_date_str:
        return jsonify([]), 400
    try:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
    except Exception:
        return jsonify([]), 400

    active_obras = Obra.query.filter(
        Obra.fecha_inicio <= end_date,
        Obra.fecha_fin >= start_date,
        Obra.estado != "Finalizada",
    ).all()
    obras_list = [{"id": obra.id, "nombre": obra.nombre} for obra in active_obras]
    return jsonify(obras_list)


# ==============================================================================
# NUEVO MÓDULO: PLANIFICADOR JO (TIMELINE / GANTT)
# ==============================================================================
from flask import request, jsonify, render_template
from flask_login import login_required, current_user
from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload

from app.models import Obra, User, Asignacion, Company, Solicitud
from app import db
from app.services.assignment_service import process_assignment_action

# 1. FUNCIÓN QUE CARGA EL HTML Y EL DESPLEGABLE
@admin_bp.route("/planificador")
@login_required
def planificador_jo():
    if not user_can(current_user, 'planificador', 'r'):
        flash(translate("Acceso no autorizado"), "danger")
        return redirect(url_for('main.dashboard'))

    from app.services.panel_scope_service import (
        PANEL_PLANIFICADOR,
        apply_obra_scope_filter,
        list_jefes_for_scope_ui,
        user_panel_mode,
        planning_acts_as_office,
    )
    from app.services.assign_mode_service import user_assigns_direct

    empresas = Company.query.filter_by(active=True).order_by(Company.nombre).all()

    base_q = Obra.query.filter(
        func.lower(Obra.estado) != 'finalizada',
        Obra.is_deleted.is_(False),
    )
    scope_q = apply_obra_scope_filter(base_q, current_user, PANEL_PLANIFICADOR)
    todas_obras = scope_q.order_by(Obra.nombre).all()

    planif_office = planning_acts_as_office(current_user)
    jefes = list_jefes_for_scope_ui() if planif_office else []

    from app.services.oficina_obra_service import es_obra_oficina
    planif_sin_obras = all(es_obra_oficina(o) for o in todas_obras) if todas_obras else True
    planif_sin_personal = (
        User.query.filter_by(role=ROLE_OPERARIO, active=True, is_deleted=False).count() == 0
    )

    from app.utils.timezone_utils import today_local
    from app.models import Festivo
    hoy_planif = today_local()
    festivos_planif = [
        f.fecha.isoformat()
        for f in Festivo.query.filter(
            Festivo.fecha >= hoy_planif - timedelta(days=7),
            Festivo.fecha <= hoy_planif + timedelta(days=400),
        ).all()
        if f.fecha
    ]

    return render_template(
        "planificador.html",
        todas_obras=todas_obras,
        jefes=jefes,
        empresas=empresas,
        ROLE_ADMIN=ROLE_ADMIN,
        planif_office=planif_office,
        planif_direct_assign=user_assigns_direct(current_user),
        can_edit_planificador=can_edit_planning_calendar(current_user),
        planif_sin_obras=planif_sin_obras,
        planif_sin_personal=planif_sin_personal,
        planif_scope_mode=user_panel_mode(current_user, PANEL_PLANIFICADOR),
        planificador_festivos=festivos_planif,
    )


def _planificador_worker_ids_from_request():
    out = []
    for raw in request.args.getlist('worker_ids[]'):
        s = str(raw or '').strip()
        if s.isdigit():
            out.append(int(s))
    return out


def _planificador_obras_con_operarios(worker_ids, start_date, end_date, obras_ids):
    if not worker_ids or not obras_ids:
        return set()
    from app.services.inercia_service import bloques_inercia_rango
    rows = (
        db.session.query(Asignacion.obra_id)
        .filter(
            Asignacion.user_id.in_(worker_ids),
            Asignacion.obra_id.in_(obras_ids),
            Asignacion.fecha >= start_date,
            Asignacion.fecha <= end_date,
        )
        .distinct()
        .all()
    )
    return {r[0] for r in rows} | {
        b['obra_id']
        for b in bloques_inercia_rango(
            worker_ids, start_date, end_date, obra_ids=obras_ids,
        )
    }


def _planificador_avg_ratings(user_ids):
    """Media de valoraciones activas v2 visibles según alcance del usuario."""
    from app.services.tenant_modules import has_valoraciones
    from app.services.permission_service import user_can
    from app.services.rating_service import apply_valoraciones_author_filter

    ids = [int(u) for u in (user_ids or []) if u]
    if not ids or not has_valoraciones() or not user_can(current_user, 'valoraciones', 'r'):
        return {}
    q = (
        db.session.query(Rating.user_id, func.avg(Rating.score))
        .filter(
            Rating.user_id.in_(ids),
            Rating.is_active.is_(True),
            or_(Rating.actitud.isnot(None), Rating.conocimiento.isnot(None)),
        )
    )
    q = apply_valoraciones_author_filter(q, current_user)
    rows = q.group_by(Rating.user_id).all()
    return {uid: round(float(avg), 1) for uid, avg in rows}


# 2. FUNCIÓN QUE CARGA LAS FILAS (EJE Y) DEL CALENDARIO
@admin_bp.route("/api/planificador/resources")
@login_required
def api_planificador_resources():
    jefe_id = request.args.get('jefe_id')
    start_str = request.args.get('start')
    end_str = request.args.get('end')

    # Empaquetamos los filtros para que sean idénticos en todas las búsquedas
    # Incluimos no finalizadas; el cliente/API filtra además por solape con la ventana.
    base_filters = [
        func.lower(Obra.estado) != 'finalizada',
        Obra.is_deleted.is_(False),
    ]

    win_start = None
    win_end = None
    try:
        if start_str:
            win_start = datetime.fromisoformat(start_str.replace('Z', '')).date()
        if end_str:
            win_end = datetime.fromisoformat(end_str.replace('Z', '')).date()
    except Exception:
        win_start = win_end = None

    if win_start and win_end:
        obras_ids_req = request.args.getlist('obra_ids[]')
        if not obras_ids_req:
            # Solo obras cuyo intervalo [inicio, fin] solapa la ventana pedida
            base_filters.extend([
                or_(Obra.fecha_inicio.is_(None), Obra.fecha_inicio <= win_end),
                or_(Obra.fecha_fin.is_(None), Obra.fecha_fin >= win_start),
            ])

    from app.services.panel_scope_service import (
        PANEL_PLANIFICADOR,
        apply_obra_scope_filter,
        user_panel_mode,
    )
    if user_panel_mode(current_user, PANEL_PLANIFICADOR) == 'none':
        return jsonify([])

    q = Obra.query.filter(*base_filters)
    q = apply_obra_scope_filter(q, current_user, PANEL_PLANIFICADOR, jefe_id_filter=jefe_id)
    obras_ids = request.args.getlist('obra_ids[]')
    if obras_ids and user_panel_mode(current_user, PANEL_PLANIFICADOR) == 'office' and not jefe_id:
        q = q.filter(Obra.id.in_(obras_ids))
    obras = q.all()

    worker_ids = _planificador_worker_ids_from_request()
    if worker_ids and win_start and win_end:
        allowed = _planificador_obras_con_operarios(
            worker_ids, win_start, win_end, {o.id for o in obras}
        )
        obras = [o for o in obras if o.id in allowed]

    resources = [{
        "id": str(obra.id), 
        "title": obra.nombre, 
        "codigo": obra.codigo or '',
        "fecha_inicio": obra.fecha_inicio.strftime("%Y-%m-%d") if obra.fecha_inicio else "",
        "fecha_fin": obra.fecha_fin.strftime("%d/%m/%y") if obra.fecha_fin else "",
        "fecha_fin_iso": obra.fecha_fin.strftime("%Y-%m-%d") if obra.fecha_fin else "",
    } for obra in obras]
    
    return jsonify(resources)


# 3. FUNCIÓN QUE CARGA LOS EVENTOS Y MARCADORES
@admin_bp.route("/api/planificador/events")
@login_required
def api_planificador_events():
    start_str = request.args.get('start')
    end_str = request.args.get('end')
    jefe_id = request.args.get('jefe_id')
    
    company_ids = request.args.getlist('company_ids[]')
    company_ids = [int(cid) for cid in company_ids if cid.lstrip('-').isdigit()]
    
    start_date = datetime.fromisoformat(start_str.replace('Z', '')).date() if start_str else datetime.today().date()
    end_date = datetime.fromisoformat(end_str.replace('Z', '')).date() if end_str else start_date + timedelta(days=30)
    base_filters = [
        func.lower(Obra.estado) != 'finalizada',
        Obra.is_deleted.is_(False),
    ]
    req_ids = request.args.getlist('obra_ids[]')
    # Sin selección explícita: solo obras que solapan la ventana (no mostrar acabadas “hacia delante”)
    if not req_ids:
        base_filters.extend([
            or_(Obra.fecha_inicio.is_(None), Obra.fecha_inicio <= end_date),
            or_(Obra.fecha_fin.is_(None), Obra.fecha_fin >= start_date),
        ])
    
    # Recopilamos IDs asegurándonos de aplicar los mismos filtros blindados
    from app.services.panel_scope_service import (
        PANEL_PLANIFICADOR,
        apply_obra_scope_filter,
        user_panel_mode,
    )
    if user_panel_mode(current_user, PANEL_PLANIFICADOR) == 'none':
        return jsonify([])

    q = Obra.query.filter(*base_filters)
    q = apply_obra_scope_filter(q, current_user, PANEL_PLANIFICADOR, jefe_id_filter=jefe_id)
    if req_ids and user_panel_mode(current_user, PANEL_PLANIFICADOR) == 'office' and not jefe_id:
        q = q.filter(Obra.id.in_(req_ids))
    obras_ids = [o.id for o in q.all()]

    worker_ids = _planificador_worker_ids_from_request()
    if worker_ids:
        allowed = _planificador_obras_con_operarios(
            worker_ids, start_date, end_date, obras_ids
        )
        obras_ids = [oid for oid in obras_ids if oid in allowed]

    if not obras_ids:
        return jsonify([])

    asignaciones_rows = (
        db.session.query(
            Asignacion.user_id,
            Asignacion.obra_id,
            Asignacion.fecha,
            Asignacion.company_id,
        )
        .filter(
            Asignacion.obra_id.in_(obras_ids),
            Asignacion.fecha >= start_date,
            Asignacion.fecha <= end_date,
        )
    )
    if worker_ids:
        asignaciones_rows = asignaciones_rows.filter(Asignacion.user_id.in_(worker_ids))
    asignaciones_rows = asignaciones_rows.all()

    user_ids_needed = {r.user_id for r in asignaciones_rows}
    company_ids_needed = {r.company_id for r in asignaciones_rows if r.company_id}
    users_by_id = {}
    if user_ids_needed:
        users_by_id = {
            u.id: u for u in User.query.options(joinedload(User.company_rel))
            .filter(User.id.in_(user_ids_needed))
            .all()
        }
        for u in users_by_id.values():
            if u.company_id:
                company_ids_needed.add(u.company_id)
    companies_by_id = {}
    if company_ids_needed:
        companies_by_id = {
            c.id: c for c in Company.query.filter(Company.id.in_(company_ids_needed)).all()
        }
    
    events_map = {}
    workers_info = {}
    ratings_cache = {}
    
    for row in asignaciones_rows:
        if company_ids:
            emp_id_check = row.company_id
            if not emp_id_check:
                worker_check = users_by_id.get(row.user_id)
                emp_id_check = worker_check.company_id if worker_check else 0
            
            if emp_id_check not in company_ids:
                continue

        key = f"w_{row.user_id}_o_{row.obra_id}"
        if key not in events_map:
            events_map[key] = []
            worker = users_by_id.get(row.user_id)
            comp = companies_by_id.get(row.company_id) if row.company_id else None
            color = comp.color if comp else (
                worker.company_rel.color if worker and worker.company_rel else "#3b82f6"
            )
            
            emp_nom = "Sin Empresa"
            emp_id = 0
            if comp:
                emp_nom = comp.nombre
                emp_id = comp.id
            elif worker and worker.company_rel:
                emp_nom = worker.company_rel.nombre
                emp_id = worker.company_rel.id

            ratings_cache[row.user_id] = None
            nota_media = 0

            workers_info[key] = {
                "name": f"{worker.name} {worker.lastname}" if worker else f"User {row.user_id}",
                "color": color, 
                "worker_id": row.user_id, 
                "obra_id": row.obra_id,
                "empresa_nombre": emp_nom,
                "empresa_id": emp_id,
                "categoria": worker.categoria_profesional if worker and worker.categoria_profesional else "",
                "especialidad": worker.especialidad if worker and worker.especialidad else "",
                "nota": nota_media,
            }
            
        events_map[key].append(row.fecha)

    from app.services.inercia_service import (
        bloques_inercia_rango,
        festivos_en,
        _hueco_solo_no_laborable,
    )
    include_inercia = request.args.get('inercia', '1').strip().lower() not in (
        '0', 'false', 'no', 'off',
    )
    compact = request.args.get('compact', '0').strip().lower() in (
        '1', 'true', 'yes', 'on',
    )
    bloques_in = []
    if include_inercia:
        bloques_in = bloques_inercia_rango(
            worker_ids or None, start_date, end_date, obra_ids=obras_ids,
        )
    extra_inercia_uids = {
        b['user_id'] for b in bloques_in if b['user_id'] not in users_by_id
    }
    if extra_inercia_uids:
        for u in User.query.options(joinedload(User.company_rel)).filter(
            User.id.in_(extra_inercia_uids)
        ).all():
            users_by_id[u.id] = u
            if u.company_id:
                company_ids_needed.add(u.company_id)
        if company_ids_needed:
            for c in Company.query.filter(
                Company.id.in_(company_ids_needed - set(companies_by_id))
            ).all():
                companies_by_id[c.id] = c

    def _info_inercia(uid, oid):
        key = f"w_{uid}_o_{oid}"
        if key in workers_info:
            return key, workers_info[key]
        worker = users_by_id.get(uid)
        comp = worker.company_rel if worker else None
        color = comp.color if comp else "#3b82f6"
        workers_info[key] = {
            "name": f"{worker.name} {worker.lastname}" if worker else f"User {uid}",
            "color": color,
            "worker_id": uid,
            "obra_id": oid,
            "empresa_nombre": comp.nombre if comp else "Sin Empresa",
            "empresa_id": comp.id if comp else 0,
            "categoria": worker.categoria_profesional if worker and worker.categoria_profesional else "",
            "especialidad": worker.especialidad if worker and worker.especialidad else "",
            "nota": 0,
        }
        ratings_cache[uid] = None
        return key, workers_info[key]

    inercia_emits = []
    for bloque in bloques_in:
        uid, oid = bloque['user_id'], bloque['obra_id']
        if company_ids:
            worker_check = users_by_id.get(uid)
            emp_id_check = worker_check.company_id if worker_check else 0
            if emp_id_check not in company_ids:
                continue
        key, info = _info_inercia(uid, oid)
        inercia_emits.append((bloque, key, info))

    if ratings_cache:
        avg_ratings = _planificador_avg_ratings(list(ratings_cache.keys()))
        for info in workers_info.values():
            info["nota"] = avg_ratings.get(info["worker_id"], 0)
        
    events = []

    from app.services.leave_service import (
        apply_leave_overlay_title,
        build_leaves_by_user,
        leave_covering,
    )
    from app.services.fichaje_estado_service import (
        COLOR_FALTA,
        TOOLTIP_FALTA,
        faltas_confirmadas_set,
    )
    leaves_idx = build_leaves_by_user(
        {info['worker_id'] for info in workers_info.values()},
        start_date,
        end_date,
    )
    faltas_set = faltas_confirmadas_set(
        start_date, end_date,
        user_ids={info['worker_id'] for info in workers_info.values()} or None,
        obra_ids=obras_ids or None,
        end_exclusive=False,
    )
    
    def crear_bloque(start_d, end_d, curr_key, curr_info, leave=None, inercia=False, es_falta=False):
        base_title = curr_info["name"]
        title, overlay_color, is_overlay = apply_leave_overlay_title(
            base_title, leave, name_first=True
        )
        color = overlay_color or curr_info["color"]
        class_name = "inercia-item" if inercia else None
        if es_falta and not is_overlay and not inercia:
            color = COLOR_FALTA
            title = f"{base_title} · Falta"
            class_name = "falta-item"
        events.append({
            "id": f"{curr_key}_{start_d}{'_i' if inercia else ''}{'_f' if es_falta and not inercia else ''}",
            "resourceId": str(curr_info["obra_id"]),
            "title": title,
            "start": start_d.strftime("%Y-%m-%d"),
            "end": (end_d + timedelta(days=1)).strftime("%Y-%m-%d"),
            "color": color,
            "worker_id": curr_info["worker_id"],
            "editable": not inercia,
            "inercia": inercia,
            "es_falta": bool(es_falta and not is_overlay and not inercia),
            "className": class_name,
            "empresa_nombre": curr_info["empresa_nombre"],
            "empresa_id": curr_info["empresa_id"],
            "categoria": curr_info["categoria"],
            "especialidad": curr_info["especialidad"],
            "nota": curr_info["nota"],
            "en_ausencia": is_overlay,
            "ausencia_tipo": leave.tipo if leave else None,
            "tooltipText": translate(TOOLTIP_FALTA) if (es_falta and not is_overlay and not inercia) else None,
        })

    for key, fechas in events_map.items():
        fechas = sorted(set(fechas))
        if not fechas: continue
        info = workers_info[key]
        user_leaves = leaves_idx.get(info["worker_id"], [])
        festivos_win = festivos_en(fechas[0], fechas[-1]) if compact else set()
        obra_id_key = info["obra_id"]
        wid = info["worker_id"]

        bloque_start = fechas[0]
        bloque_end = fechas[0]
        bloque_leave = leave_covering(user_leaves, fechas[0])
        bloque_leave_id = bloque_leave.id if bloque_leave else None
        bloque_falta = (wid, fechas[0], obra_id_key) in faltas_set and not bloque_leave

        for i in range(1, len(fechas)):
            d = fechas[i]
            leave_d = leave_covering(user_leaves, d)
            leave_id = leave_d.id if leave_d else None
            falta_d = (wid, d, obra_id_key) in faltas_set and not leave_d
            contiguous = (d - bloque_end).days == 1 or (
                compact and _hueco_solo_no_laborable(bloque_end, d, festivos_win)
            )
            same_leave = leave_id == bloque_leave_id
            same_falta = falta_d == bloque_falta
            if contiguous and same_leave and same_falta:
                bloque_end = d
            else:
                crear_bloque(
                    bloque_start, bloque_end, key, info, bloque_leave, False, bloque_falta,
                )
                bloque_start = d
                bloque_end = d
                bloque_leave = leave_d
                bloque_leave_id = leave_id
                bloque_falta = falta_d

        crear_bloque(
            bloque_start, bloque_end, key, info, bloque_leave, False, bloque_falta,
        )

    # Fantasma en barra aparte (estilo ghost). El JS asigna subgroup W{id}
    # con subgroupStack {R:true,__force:true} para misma altura que el hecho.
    for bloque, key, info in inercia_emits:
        crear_bloque(
            bloque['fecha_inicio'], bloque['fecha_fin'], key, info, None, True, False,
        )

    # MARCADOR FIN DE OBRA
    obras_objs = Obra.query.filter(Obra.id.in_(obras_ids)).all()
    for o in obras_objs:
        if o.fecha_fin:
            events.append({
                "id": f"fin_obra_marker_{o.id}",
                "resourceId": str(o.id),
                "start": o.fecha_fin.strftime("%Y-%m-%d"),
                "end": (o.fecha_fin + timedelta(days=1)).strftime("%Y-%m-%d"),
                "type": "background",
                "content": "<div class='fin-obra-text'>🚩 FIN OBRA</div>",
                "className": "obra-deadline-line",
                "worker_id": "SYSTEM"
            })

    # =====================================================================
    # --- INYECTAR SOLICITUDES TRASLÚCIDAS EN EL PLANIFICADOR ---
    # =====================================================================
    solicitudes = (
        Solicitud.query
        .options(joinedload(Solicitud.empleado))
        .filter(
            Solicitud.obra_id.in_(obras_ids),
            Solicitud.estado.in_(['PENDIENTE', 'EN_PROCESO']),
            Solicitud.fecha_inicio <= end_date,
            Solicitud.fecha_fin >= start_date,
        )
        .all()
    )

    if worker_ids:
        solicitudes = [
            s for s in solicitudes
            if s.tipo == 'CONCRETA' and s.empleado_id in worker_ids
        ]

    for sol in solicitudes:
        accion = getattr(sol, 'accion', 'ASIGNAR')
        is_baja = (accion == 'DESASIGNAR')
        if company_ids:
            if sol.tipo == 'CONCRETA' and sol.empleado:
                sol_comp_id = sol.empleado.company_id or 0
                if sol_comp_id not in company_ids: continue
            elif sol.tipo == 'GENERICA':
                sol_comp_id = sol.perfil_empresa_id or 0
                if sol_comp_id not in company_ids: continue

        # 1. Definir Colores (Sólido para el borde y texto, Traslúcido para el fondo)
        if is_baja:
            color_fuerte = "#ef4444" # Rojo
            color_suave = "rgba(239, 68, 68, 0.10)"
        else:
            color_fuerte = "#f59e0b" # Naranja
            color_suave = "rgba(245, 158, 11, 0.10)"

        # 2. Definir Título
        if sol.tipo == 'CONCRETA':
            emp_name = sol.empleado.name if sol.empleado else '?'
            title = f"{'Solicitud de Baja' if is_baja else 'FALTA'}: {emp_name}"
        else:
            faltan = sol.cantidad_solicitada - sol.cantidad_cubierta
            if faltan <= 0: continue
            title = f"FALTAN: {faltan} ({sol.perfil_categoria or 'Cualquiera'})"

        # 3. Crear el estilo CSS directo para vis.js
        estilo_solicitud = f"background-color: {color_suave} !important; border: 2px dashed {color_fuerte} !important; color: {color_fuerte} !important;"

        # Solo tramos pendientes (si el día 13 ya está cubierto, no se pinta ahí).
        spans = iter_solicitud_calendar_spans(sol)
        if not spans:
            continue
        range_end_inclusive = end_date - timedelta(days=1) if end_date > start_date else end_date
        for idx, (span_start, span_end) in enumerate(spans):
            if span_end < start_date or span_start > range_end_inclusive:
                continue
            draw_start = max(span_start, start_date)
            draw_end = min(span_end, range_end_inclusive)
            if draw_end < draw_start:
                continue
            events.append({
                "id": f"solicitud_{sol.id}_{idx}_{draw_start.isoformat()}",
                "resourceId": str(sol.obra_id),
                "title": title,
                "start": draw_start.strftime("%Y-%m-%d"),
                "end": (draw_end + timedelta(days=1)).strftime("%Y-%m-%d"),
                "style": estilo_solicitud,
                "worker_id": "REQUEST",
                "editable": False,
                "solicitud_id": sol.id
            })

    # =====================================================================
    # --- INYECTAR FESTIVOS COMO FONDO GLOBAL ---
    # =====================================================================
    from app.models import Festivo
    festivos = Festivo.query.filter(
        Festivo.fecha >= start_date,
        Festivo.fecha <= end_date
    ).all()

    for f in festivos:
        events.append({
            "id": f"festivo_{f.id}",
            "start": f.fecha.strftime("%Y-%m-%d"),
            "end": (f.fecha + timedelta(days=1)).strftime("%Y-%m-%d"),
            "type": "background",
            "content": f"<div style='color:#b91c1c; font-weight:bold; font-size:11px; padding-top:8px; writing-mode:vertical-rl; text-orientation:mixed;'>🌴 {f.descripcion}</div>",
            "color": "rgba(239, 68, 68, 0.15)",
            "worker_id": "SYSTEM"
        })

    return jsonify(events)


@admin_bp.route("/api/planificador/fichajes-estado")
@login_required
def api_planificador_fichajes_estado():
    """Estados agregados de fichaje por operario para un día (planificador móvil)."""
    from app.services.fichaje_operario_service import usuario_ve_estado_fichaje
    from app.services.fichaje_estado_service import fichajes_agregados_por_fecha

    if not usuario_ve_estado_fichaje(current_user):
        return jsonify({'success': True, 'estados': {}})

    fecha_str = request.args.get('fecha')
    if not fecha_str:
        return jsonify({'success': False, 'error': translate('Fecha requerida')}), 400
    try:
        fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'success': False, 'error': translate('Fecha inválida')}), 400

    return jsonify({
        'success': True,
        'fecha': fecha_str,
        'estados': fichajes_agregados_por_fecha(fecha),
    })


@admin_bp.route("/api/planificador/search_workers", methods=['GET'])
@login_required
def search_workers():
    """Select2: plantilla activa completa; busca por nombre o por empresa."""
    from sqlalchemy.orm import joinedload

    q = (request.args.get('q') or '').strip().lower()
    plain = request.args.get('plain') in ('1', 'true', 'yes')

    # 1. Opción Genérica (petición de personal): quien puede planificar periodos
    # la necesita. No aplica en altas de ausencias (plain=1).
    results = []
    if not plain:
        results.append({"id": "GENERICO", "text": "👤 CUALQUIERA (Petición Genérica)"})

    # 2. Plantilla activa (sin tope: al abrir el desplegable deben salir todos)
    query = (
        User.query
        .options(joinedload(User.company_rel))
        .filter(User.active.is_(True), User.is_deleted.is_(False))
    )
    if not plain:
        query = query.filter(User.role == ROLE_OPERARIO)
    if q:
        query = (
            query
            .outerjoin(Company, User.company_id == Company.id)
            .filter(or_(
                func.lower(User.name).contains(q),
                func.lower(User.lastname).contains(q),
                func.lower(
                    func.concat(func.coalesce(User.name, ''), ' ', func.coalesce(User.lastname, ''))
                ).contains(q),
                func.lower(func.coalesce(Company.nombre, '')).contains(q),
            ))
            .distinct()
        )

    workers = query.order_by(User.name, User.lastname).all()

    # Agrupar por empresa (orden alfabético de empresa, luego persona)
    grouped = {}
    for w in workers:
        comp_name = w.company_rel.nombre if w.company_rel else "Sin Empresa"
        if comp_name not in grouped:
            grouped[comp_name] = []
        grouped[comp_name].append({
            "id": w.id,
            "text": f"{w.name} {w.lastname}".strip(),
        })

    for comp_name in sorted(grouped.keys(), key=lambda s: s.casefold()):
        results.append({
            "text": f"🏢 {comp_name}",
            "children": grouped[comp_name],
        })

    return jsonify({"results": results})

    
    
@admin_bp.route('/configuracion')
@login_required
def configuracion_global():
    from app.services.permission_service import user_can
    if not user_can(current_user, 'configuracion', 'r'):
        flash(translate("Acceso denegado. Área exclusiva de administración."), "danger")
        return redirect(url_for('main.dashboard'))
        
    from app.models import Festivo, ConfiguracionGlobal, ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL, ROLE_RRHH
    from app.services.plan_service import monetizacion_activa
    from app.services.tenant_modules import (
        conforme_jornada_activo,
        has_auditoria_vehiculos,
        hora_corte_activa,
    )
    festivos = Festivo.query.order_by(Festivo.fecha.asc()).all()
    
    # Cargamos TODAS las configuraciones en un diccionario
    todas_configs = ConfiguracionGlobal.query.all()
    configs_dict = {c.clave: c.valor for c in todas_configs}
    
    # Extraemos el límite de custodia (o le damos 15 por defecto)
    limite_custodia = int(configs_dict.get('limite_custodia', 15))
    
    tenant_modulos = getattr(g.current_tenant, 'modulos_activos', {}) or {}

    academia_pref = False
    if tenant_modulos.get('onboarding'):
        from app.services.onboarding_service import academia_visible as _academia_visible
        academia_pref = _academia_visible()

    from app.services.notification_dispatch_service import matrix_for_ui
    notif_matrix = matrix_for_ui()

    return render_template(
        'admin_configuracion.html',
        festivos=festivos,
        limite_custodia=limite_custodia,
        configs=configs_dict,
        monetizacion_activa=monetizacion_activa(),
        tenant_has_fichaje_operario=bool(tenant_modulos.get('fichaje_operario')),
        tenant_has_onboarding=bool(tenant_modulos.get('onboarding')),
        academia_visible=academia_pref,
        tenant_has_auditoria_vehiculos=has_auditoria_vehiculos(),
        hora_corte_activa=hora_corte_activa(),
        conforme_jornada_activo=conforme_jornada_activo(),
        notif_matrix=notif_matrix,
    )


@admin_bp.route('/configuracion/reiniciar-guia', methods=['POST'])
@login_required
@roles_required(ROLE_ADMIN)
def reiniciar_guia_onboarding():
    """Permite volver a lanzar Primeros pasos + guía aunque ya haya datos."""
    from app.services.onboarding_service import (
        reiniciar_onboarding,
        tenant_tiene_onboarding,
    )
    from app.services.permission_service import user_can

    if not user_can(current_user, 'configuracion', 'w'):
        flash(translate('Acceso denegado.'), 'danger')
        return redirect(url_for('admin.configuracion_global'))
    if not tenant_tiene_onboarding():
        flash(translate('Este espacio no tiene el módulo de onboarding.'), 'warning')
        return redirect(url_for('admin.configuracion_global'))

    reiniciar_onboarding()
    modo = (request.form.get('modo') or 'guia').strip()
    flash(translate('Onboarding reiniciado. Puedes seguir la guía o los primeros pasos '
        '(no se han borrado datos de la empresa).'),
        'success',
    )
    if modo == 'pasos':
        return redirect(url_for('admin.primeros_pasos'))
    return redirect(url_for('admin.primeros_pasos', tour='start'))


@admin_bp.route('/permisos')
@admin_bp.route('/permisos/<role>')
@login_required
def permisos_roles(role=None):
    from app.services.permission_catalog import (
        ADMIN_LOCKED_MODULES,
        BINARY_TICK_MODULES,
        MODULE_READ_HINTS,
        MODULE_WRITE_HINTS,
        SSO_READ_ONLY_MODULES,
        WRITE_DISABLED_MODULES,
        modules_for_role,
    )
    from app.services.permission_service import (
        ensure_role_permissions,
        matrix_for_role,
        user_can,
    )
    from app.services.role_registry_service import (
        ensure_tenant_roles,
        get_role,
        is_role_locked,
        list_roles,
    )
    from app.services.panel_scope_service import (
        KIND_AUDITORIA,
        KIND_PLANIFICACION,
        KIND_SOLICITUDES,
        KIND_VALORACIONES,
        SCOPE_KINDS,
        ensure_obra_scope_unified,
        get_role_scope,
        list_jefes_for_scope_ui,
    )
    from app.services.assign_mode_service import (
        ASSIGN_MODE_DIRECT,
        ASSIGN_MODE_SOLICITUD,
        KIND_PEOPLE,
        KIND_VEHICLES,
        ensure_assign_modes_migrated,
        get_role_assign_mode,
    )
    from app.models import ROLE_ADMIN, ROLE_JEFE
    if not user_can(current_user, 'permisos', 'r'):
        flash(translate('Acceso denegado.'), 'danger')
        return redirect(url_for('main.dashboard'))
    ensure_tenant_roles()
    ensure_role_permissions()
    ensure_assign_modes_migrated()
    try:
        ensure_obra_scope_unified()
    except Exception:
        pass
    roles = list_roles()
    valid = {r for r, _ in roles}
    active = role if role in valid else 'admin'
    modules = modules_for_role(active)
    visible_keys = {m for m, _, _ in modules}
    active_meta = get_role(active)

    scope_labels = {
        KIND_PLANIFICACION: translate('Planificación'),
        KIND_AUDITORIA: translate('Auditoría fichajes / mapa'),
        KIND_SOLICITUDES: translate('Solicitudes (buzón)'),
        KIND_VALORACIONES: translate('Valoraciones'),
    }
    scope_option_sets = {
        KIND_VALORACIONES: [
            ('none', translate('Ninguno')),
            ('jefe', translate('Solo las suyas')),
            ('jefes', translate('De jefes concretos')),
            ('all', translate('Todas (oficina)')),
        ],
    }
    scopes_meta = {}
    for kind in SCOPE_KINDS:
        sc = get_role_scope(active, kind)
        meta = {
            'kind': kind,
            'label': scope_labels[kind],
            'mode': sc['mode'],
            'jefe_ids': set(sc.get('jefe_ids') or []),
            'locked': active == ROLE_ADMIN,
            'locked_note': (
                translate('Administrador: siempre ve todas las valoraciones.')
                if kind == KIND_VALORACIONES
                else translate('Administrador: siempre ve todas las obras.')
            ),
            'options': scope_option_sets.get(kind),
            'hint': (
                translate('Qué valoraciones ve en historial, paneles y reputación.')
                if kind == KIND_VALORACIONES
                else None
            ),
        }
        if active == ROLE_JEFE and kind == KIND_PLANIFICACION:
            meta['locked'] = True
            meta['locked_note'] = translate('Jefe de obra: planificación = solo sus obras.')
            meta['mode'] = 'jefe'
        scopes_meta[kind] = meta

    assign_mode_people = get_role_assign_mode(active, KIND_PEOPLE)
    assign_mode_vehicles = get_role_assign_mode(active, KIND_VEHICLES)
    assign_mode_locked = active == ROLE_ADMIN

    return render_template(
        'admin_permisos.html',
        roles=roles,
        modules=modules,
        active_role=active,
        active_role_label=(active_meta.label if active_meta else active),
        active_role_locked=is_role_locked(active),
        active_role_system=bool(active_meta and active_meta.is_system),
        matrix=matrix_for_role(active),
        locked_modules=ADMIN_LOCKED_MODULES,
        sso_read_only_modules=SSO_READ_ONLY_MODULES,
        write_disabled_modules=WRITE_DISABLED_MODULES,
        binary_tick_modules=BINARY_TICK_MODULES,
        read_hints=MODULE_READ_HINTS,
        write_hints=MODULE_WRITE_HINTS,
        show_integration_perm_hint=bool(
            visible_keys & {'soltec_alta_odoo', 'soltec_portal', 'sync_odoo', 'integraciones'}
        ),
        can_manage_roles=user_can(current_user, 'permisos', 'w'),
        scopes_meta=scopes_meta,
        scope_jefes=list_jefes_for_scope_ui(),
        assign_mode_people=assign_mode_people,
        assign_mode_vehicles=assign_mode_vehicles,
        assign_mode_locked=assign_mode_locked,
        ASSIGN_MODE_DIRECT=ASSIGN_MODE_DIRECT,
        ASSIGN_MODE_SOLICITUD=ASSIGN_MODE_SOLICITUD,
    )


@admin_bp.route('/permisos/guardar', methods=['POST'])
@login_required
def permisos_roles_save():
    from app.services.permission_catalog import modules_for_role
    from app.services.permission_service import (
        ensure_role_permissions,
        save_role_matrix,
        user_can,
    )
    from app.services.role_registry_service import valid_role_keys
    from app.services.panel_scope_service import (
        KIND_PLANIFICACION,
        parse_all_scopes_from_form,
        set_role_scope,
    )
    from app.models import ROLE_ADMIN, ROLE_JEFE
    if not user_can(current_user, 'permisos', 'w'):
        flash(translate('Acceso denegado.'), 'danger')
        return redirect(url_for('main.dashboard'))
    if request.form.get('reset_defaults'):
        ensure_role_permissions(force=True)
        flash(translate('Permisos restaurados a los valores por defecto.'), 'success')
        return redirect(url_for('admin.permisos_roles'))
    role = (request.form.get('role') or '').strip()
    if role not in valid_role_keys():
        flash(translate('Rol no válido.'), 'danger')
        return redirect(url_for('admin.permisos_roles'))
    try:
        role_modules = [m for m, _, _ in modules_for_role(role)]
        save_role_matrix(role, request.form, modules=role_modules)
        if role != ROLE_ADMIN:
            for kind, (mode, jefe_ids) in parse_all_scopes_from_form(request.form).items():
                if role == ROLE_JEFE and kind == KIND_PLANIFICACION:
                    continue  # forzado a sus obras
                set_role_scope(role, kind, mode, jefe_ids)
        from app.services.assign_mode_service import (
            KIND_PEOPLE,
            KIND_VEHICLES,
            parse_assign_mode_from_form,
            set_role_assign_mode,
        )
        set_role_assign_mode(
            role, parse_assign_mode_from_form(request.form, role, KIND_PEOPLE), KIND_PEOPLE
        )
        set_role_assign_mode(
            role, parse_assign_mode_from_form(request.form, role, KIND_VEHICLES), KIND_VEHICLES
        )
    except Exception as exc:
        db.session.rollback()
        flash(translate('No se pudieron guardar los permisos: {error}', error=exc), 'danger')
        return redirect(url_for('admin.permisos_roles', role=role))
    flash(translate('Permisos guardados.'), 'success')
    return redirect(url_for('admin.permisos_roles', role=role))


@admin_bp.route('/permisos/rol/renombrar', methods=['POST'])
@login_required
def permisos_rol_renombrar():
    from app.services.permission_service import user_can
    from app.services.role_registry_service import rename_role
    if not user_can(current_user, 'permisos', 'w'):
        flash(translate('Acceso denegado.'), 'danger')
        return redirect(url_for('main.dashboard'))
    key = (request.form.get('role') or '').strip()
    label = (request.form.get('label') or '').strip()
    try:
        rename_role(key, label)
        flash(translate('Nombre del rol actualizado.'), 'success')
    except Exception as exc:
        db.session.rollback()
        flash(translate('No se pudo renombrar: {error}', error=exc), 'danger')
    return redirect(url_for('admin.permisos_roles', role=key or 'admin'))


@admin_bp.route('/permisos/rol/crear', methods=['POST'])
@login_required
def permisos_rol_crear():
    from app.services.permission_service import user_can
    from app.services.role_registry_service import create_role
    if not user_can(current_user, 'permisos', 'w'):
        flash(translate('Acceso denegado.'), 'danger')
        return redirect(url_for('main.dashboard'))
    label = (request.form.get('label') or '').strip()
    key = (request.form.get('key') or '').strip() or None
    clone_from = (request.form.get('clone_from') or 'laboral').strip()
    try:
        row = create_role(key=key, label=label, clone_from=clone_from)
        flash(translate('Rol creado. Ajusta sus permisos abajo.'), 'success')
        return redirect(url_for('admin.permisos_roles', role=row.key))
    except Exception as exc:
        db.session.rollback()
        flash(translate('No se pudo crear el rol: {error}', error=exc), 'danger')
        return redirect(url_for('admin.permisos_roles'))


@admin_bp.route('/permisos/rol/eliminar', methods=['POST'])
@login_required
def permisos_rol_eliminar():
    from app.services.permission_service import user_can
    from app.services.role_registry_service import delete_role
    if not user_can(current_user, 'permisos', 'w'):
        flash(translate('Acceso denegado.'), 'danger')
        return redirect(url_for('main.dashboard'))
    key = (request.form.get('role') or '').strip()
    try:
        delete_role(key)
        flash(translate('Rol eliminado.'), 'success')
        return redirect(url_for('admin.permisos_roles'))
    except Exception as exc:
        db.session.rollback()
        flash(translate('No se pudo eliminar: {error}', error=exc), 'danger')
        return redirect(url_for('admin.permisos_roles', role=key or 'admin'))


@admin_bp.route('/configuracion/update', methods=['POST'])
@login_required
def update_config():
    from app.services.permission_service import user_can
    if not user_can(current_user, 'configuracion', 'w'):
        return redirect(url_for('main.dashboard'))

    from app.models import ConfiguracionGlobal

    section = (request.form.get('form_section') or 'all').strip()

    def _upsert(clave, valor):
        conf = ConfiguracionGlobal.query.filter_by(clave=clave).first()
        if not conf:
            db.session.add(ConfiguracionGlobal(clave=clave, valor=str(valor)))
        else:
            conf.valor = str(valor)

    def _upsert_int_cfg(clave, raw, default, min_v=1, max_v=100000):
        try:
            val = int(float(str(raw).strip().replace(',', '.'))) if raw not in (None, '') else int(default)
        except (TypeError, ValueError):
            val = int(default)
        val = max(min_v, min(max_v, val))
        _upsert(clave, val)

    # Compat: formularios antiguos sin form_section
    if section == 'all':
        section_keys = {'horario', 'fichajes', 'ausencias', 'laboral', 'vehiculos', 'emails'}
    else:
        section_keys = {section}

    if 'horario' in section_keys:
        zona = (request.form.get('zona_horaria') or '').strip()
        if zona:
            _upsert('zona_horaria', zona)
            from app.utils.timezone_utils import invalidate_app_timezone_cache
            invalidate_app_timezone_cache()

        limite = request.form.get('limite_custodia')
        if limite and str(limite).isdigit():
            _upsert('limite_custodia', limite)

    if 'fichajes' in section_keys:
        primer_fichaje_val = 'True' if request.form.get('aceptar_primer_fichaje') else 'False'
        _upsert('aceptar_primer_fichaje', primer_fichaje_val)

        from app.services.fichaje_operario_service import (
            CONFIG_FICHAJE_GEO,
            CONFIG_FICHAJE_GEO_EXIGIR,
            CONFIG_FICHAJE_OPERARIO,
            GEO_ACTIVADA,
            GEO_DESACTIVADA,
            tenant_tiene_fichaje_operario_module,
        )
        from app.services.geocerca_service import (
            CONFIG_GEOCERCA_RADIO,
            normalizar_modo_geo_config,
        )

        # Activar esto abre el login a los operarios, que hasta ahora no
        # entraban. Se avisa en la plantilla porque tiene consecuencias.
        from app.services.plan_service import PlanLimitError, exigir_geolocalizacion
        if tenant_tiene_fichaje_operario_module():
            operario_activo = 'True' if request.form.get('fichaje_operario_activo') else 'False'
            _upsert(CONFIG_FICHAJE_OPERARIO, operario_activo)

            if operario_activo == 'True':
                modo_geo_raw = (request.form.get('fichaje_geolocalizacion') or '').strip()
                modo_geo = (
                    GEO_ACTIVADA
                    if normalizar_modo_geo_config(modo_geo_raw) == GEO_ACTIVADA
                    else GEO_DESACTIVADA
                )
                if modo_geo == GEO_ACTIVADA:
                    try:
                        exigir_geolocalizacion()
                    except PlanLimitError as exc:
                        flash(translate(str(exc)), 'danger')
                        modo_geo = GEO_DESACTIVADA
                _upsert(CONFIG_FICHAJE_GEO, modo_geo)
                exigir_geo = (
                    'True'
                    if modo_geo == GEO_ACTIVADA and request.form.get('fichaje_geolocalizacion_exigir')
                    else 'False'
                )
                _upsert(CONFIG_FICHAJE_GEO_EXIGIR, exigir_geo)

                radio_raw = (request.form.get('fichaje_geocerca_radio_default') or '').strip()
                try:
                    radio = max(25, min(int(radio_raw or 150), 5000))
                except ValueError:
                    radio = 150
                _upsert(CONFIG_GEOCERCA_RADIO, str(radio))

                from app.services.oficina_obra_service import (
                    CONFIG_OBRA_OFICINA,
                    sincronizar_obra_oficina,
                )
                oficina_on = bool(request.form.get('obra_oficina_activa'))
                _upsert(CONFIG_OBRA_OFICINA, 'True' if oficina_on else 'False')
                sincronizar_obra_oficina(oficina_on)

        from app.services.tenant_modules import CONFIG_CONFORME_JORNADA
        _upsert(
            CONFIG_CONFORME_JORNADA,
            'True' if request.form.get('conforme_jornada_activo') else 'False',
        )

    if 'ausencias' in section_keys:
        jefe_resuelve = 'True' if request.form.get('ausencias_jefe_puede_resolver') else 'False'
        _upsert('ausencias_jefe_puede_resolver', jefe_resuelve)
        _upsert('ausencias_auto_resolucion', 'prefer_leave')
        from app.services.leave_service import release_assignments_blocked_by_leave
        release_assignments_blocked_by_leave(autor_id=current_user.id)

    if 'vehiculos' in section_keys:
        from app.services.tenant_modules import has_auditoria_vehiculos as _has_aud_veh
        if _has_aud_veh():
            from app.services.vehicle_anomaly_service import (
                DEFAULT_DESVIO_MAX_PCT,
                DEFAULT_DESVIO_MIN_PCT,
                DEFAULT_THRESHOLDS,
            )
            _upsert_int_cfg(
                'vehiculo_salto_km_dia',
                request.form.get('vehiculo_salto_km_dia'),
                DEFAULT_THRESHOLDS['vehiculo_salto_km_dia'],
                min_v=50, max_v=5000,
            )
            _upsert_int_cfg(
                'vehiculo_desvio_max_pct',
                request.form.get('vehiculo_desvio_max_pct'),
                DEFAULT_DESVIO_MAX_PCT,
                min_v=1, max_v=500,
            )
            _upsert_int_cfg(
                'vehiculo_desvio_min_pct',
                request.form.get('vehiculo_desvio_min_pct'),
                DEFAULT_DESVIO_MIN_PCT,
                min_v=1, max_v=500,
            )

    if 'emails' in section_keys:
        from app.services.notification_dispatch_service import save_matrix_from_form
        save_matrix_from_form(request.form)

    if 'guia' in section_keys:
        from app.services.onboarding_service import CONFIG_ACADEMIA_VISIBLE
        _upsert(
            CONFIG_ACADEMIA_VISIBLE,
            'True' if request.form.get('academia_visible') else 'False',
        )

    odoo_url = request.form.get('odoo_url')
    if odoo_url:
        _upsert('odoo_url', odoo_url)

    flash_msgs = {
        'horario': translate('Horario y planificación guardados.'),
        'fichajes': translate('Configuración de fichajes guardada.'),
        'ausencias': translate('Configuración de ausencias guardada.'),
        'laboral': translate('Permisos de Laboral guardados.'),
        'vehiculos': translate('Alertas de vehículos guardadas.'),
        'emails': translate('Notificaciones por correo guardadas.'),
        'guia': translate('Preferencia de Academia guardada.'),
        'all': translate('Configuración global actualizada correctamente.'),
    }

    try:
        db.session.commit()
        flash(flash_msgs.get(section, flash_msgs['all']), 'success')
    except Exception as e:
        db.session.rollback()
        flash(translate('Error al guardar la configuración: {error}', error=str(e)), 'danger')

    anchor = {
        'horario': 'cfg-horario',
        'fichajes': 'cfg-fichajes',
        'ausencias': 'cfg-ausencias',
        'laboral': 'cfg-laboral',
        'vehiculos': 'cfg-vehiculos',
        'emails': 'cfg-emails',
        'guia': 'cfg-guia',
    }.get(section)
    if anchor:
        return redirect(url_for('admin.configuracion_global') + f'#{anchor}')
    return redirect(url_for('admin.configuracion_global'))

@admin_bp.route('/configuracion/festivos/add', methods=['POST'])
@login_required
def add_festivo():
    from app.models import Festivo
    fecha_str = request.form.get('fecha')
    descripcion = request.form.get('descripcion')
    
    if fecha_str:
        try:
            fecha_obj = datetime.strptime(fecha_str, '%Y-%m-%d').date()
            # Comprobar si ya existe
            existe = Festivo.query.filter_by(fecha=fecha_obj).first()
            if existe:
                flash(translate("El día {date} ya está marcado como festivo.", date=fecha_str), "warning")
            else:
                nuevo_festivo = Festivo(fecha=fecha_obj, descripcion=descripcion)
                db.session.add(nuevo_festivo)
                db.session.commit()
                flash(translate("Día {date} añadido al calendario de festivos.", date=fecha_str), "success")
        except Exception as e:
            flash(translate("Error al añadir festivo: {error}", error=str(e)), "danger")
            db.session.rollback()
            
    return redirect(url_for('admin.configuracion_global'))


@admin_bp.route('/configuracion/festivos/delete/<int:id>')
@login_required
def delete_festivo(id):
    from app.models import Festivo
    f = Festivo.query.get_or_404(id)
    db.session.delete(f)
    db.session.commit()
    flash(translate("Día festivo eliminado del sistema."), "info")
    return redirect(url_for('admin.configuracion_global'))

@admin_bp.route("/api/obras/batch_status", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def batch_update_obras_status():
    """Cambia el estado de múltiples obras a la vez y limpia asignaciones si es necesario."""
    data = request.get_json()
    obra_ids = data.get('obra_ids', [])
    new_estado = data.get('new_status')

    if not obra_ids or not new_estado:
        return jsonify({'success': False, 'message': translate('Datos incompletos.')}), 400

    # AQUÍ ESTABA EL ERROR: Cambiamos 'Ejecucion' por 'En Curso'
    valid_estados = ['Pendiente', 'En Curso', 'En Garantía', 'Finalizada']

    if new_estado not in valid_estados:
        return jsonify({'success': False, 'message': translate('Estado no válido.')}), 400

    try:
        obras = Obra.query.filter(Obra.id.in_(obra_ids)).all()
        today = date.today()
        total_deleted = 0
        actor_id = current_user.id

        for obra in obras:
            old_estado = obra.estado
            obra.estado = new_estado
            obra_nombre = obra.nombre

            if new_estado == 'Pendiente' and old_estado != 'Pendiente':
                futuras = (
                    Asignacion.query.filter(Asignacion.obra_id == obra.id, Asignacion.fecha >= today)
                    .with_entities(Asignacion.user_id, Asignacion.obra_id, Asignacion.fecha)
                    .all()
                )
                for uid, oid, fecha in futuras:
                    CoreAssignmentService.desasignar(
                        uid, oid, fecha, actor_id,
                        "Pausa de Obra (Masiva)", f"Obra '{obra_nombre}' pausada.",
                        registrar_log=False,
                    )
                total_deleted += len(futuras)
                from app.services.inercia_service import cortar_casa_de_obra
                cortar_casa_de_obra(obra.id, today, actor_id)
            elif new_estado == 'Finalizada' and old_estado != 'Finalizada':
                obra.fecha_fin = today
                futuras = (
                    Asignacion.query.filter(Asignacion.obra_id == obra.id, Asignacion.fecha >= today)
                    .with_entities(Asignacion.user_id, Asignacion.obra_id, Asignacion.fecha)
                    .all()
                )
                for uid, oid, fecha in futuras:
                    CoreAssignmentService.desasignar(
                        uid, oid, fecha, actor_id,
                        "Finalización de Obra (Masiva)", f"Obra '{obra_nombre}' finalizada.",
                        registrar_log=False,
                    )
                total_deleted += len(futuras)
                from app.services.inercia_service import cortar_casa_de_obra
                cortar_casa_de_obra(obra.id, today, actor_id)

        if total_deleted > 0:
            from app.utils import register_log
            register_log(
                user_id=actor_id,
                category='planificacion',
                action=f'Cambio masivo a {new_estado}',
                detail=f"{len(obras)} obra(s) → '{new_estado}': {total_deleted} jornadas futuras liberadas.",
            )

        db.session.commit()
        
        msg = translate(
            "Estado actualizado a '{estado}' en {n} obras.",
            estado=new_estado,
            n=len(obras),
        )
        if total_deleted > 0:
            msg += ' ' + translate(
                'Se han liberado {n} jornadas asignadas a futuro.',
                n=total_deleted,
            )
            
        return jsonify({'success': True, 'message': msg})

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@admin_bp.route("/api/users/batch_delete", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def batch_delete_users():
    data = request.get_json() or {}
    user_ids = data.get("user_ids", [])
    if not user_ids:
        return jsonify({"success": False, "message": translate("No se seleccionaron usuarios.")}), 400

    deleted = 0
    for uid in user_ids:
        user = User.query.get(int(uid))
        if user and not user.is_deleted:
            user.soft_delete(actor_id=current_user.id)
            deleted += 1
    db.session.commit()
    return jsonify({"success": True, "message": translate("{n} usuario(s) eliminado(s).", n=deleted)})


@admin_bp.route("/api/users/batch_deactivate", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def batch_deactivate_users():
    from app.services.employee_baja_service import dar_de_baja

    data = request.get_json() or {}
    user_ids = data.get("user_ids", [])
    if not user_ids:
        return jsonify({"success": False, "message": translate("No se seleccionaron usuarios.")}), 400

    updated = 0
    for uid in user_ids:
        user = User.query.get(int(uid))
        if user and user.role == ROLE_OPERARIO and user.active:
            result = dar_de_baja(user, actor_id=current_user.id, motivo='manual', commit=False)
            if result.get('changed'):
                updated += 1
    db.session.commit()
    return jsonify({"success": True, "message": translate("{n} operario(s) desactivado(s).", n=updated)})


@admin_bp.route("/api/companies/batch_delete", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def batch_delete_companies():
    from app.models import Asignacion

    data = request.get_json() or {}
    company_ids = data.get("company_ids", [])
    if not company_ids:
        return jsonify({"success": False, "message": translate("No se seleccionaron empresas.")}), 400

    deleted = 0
    for cid in company_ids:
        company = Company.query.get(int(cid))
        if not company:
            continue

        associated_workers = User.query.filter_by(
            role=ROLE_OPERARIO, company_id=company.id
        ).all()
        for worker in associated_workers:
            worker.soft_delete(actor_id=current_user.id)
            worker.company_id = None

        Asignacion.query.filter_by(company_id=company.id).update({"company_id": None})
        User.query.filter_by(company_id=company.id).update({"company_id": None})
        db.session.delete(company)
        deleted += 1

    db.session.commit()
    return jsonify({"success": True, "message": translate("{n} empresa(s) eliminada(s).", n=deleted)})


@admin_bp.route("/sso/odoo_contactos")
@login_required
def sso_odoo_contactos():
    """SSO firmado hacia la app externa Alta Odoo (/sso_login)."""
    from app.utils.timezone_utils import utc_now
    from app.services.permission_service import user_can

    if not user_can(current_user, 'soltec_alta_odoo', 'r'):
        flash(translate('No tienes permiso para abrir Alta Odoo.'), 'danger')
        return redirect(url_for('main.dashboard'))

    sso_secret = current_app.config.get('SSO_SECRET_KEY')
    if not sso_secret:
        flash(translate('SSO no configurado (SSO_SECRET_KEY).'), 'danger')
        return redirect(url_for('admin.panel'))

    alta_url = (current_app.config.get('ODOO_ALTA_APP_URL') or '').strip().rstrip('/')
    if not alta_url:
        dominio_base = request.host.split(':')[0]
        alta_url = f"{request.scheme}://{dominio_base}:5002"

    u_name = current_user.name if current_user.name and str(current_user.name).lower() != 'none' else ''
    u_last = current_user.lastname if current_user.lastname and str(current_user.lastname).lower() != 'none' else ''
    full_name = f'{u_name} {u_last}'.strip() or current_user.email

    external_ids = getattr(current_user, 'external_ids', None) or {}
    odoo_id = external_ids.get('odoo') if isinstance(external_ids, dict) else None

    serializer = URLSafeTimedSerializer(sso_secret)
    token = serializer.dumps({
        'user_id': current_user.id,
        'odoo_id': odoo_id,
        'name': full_name,
        'email': current_user.email,
        'role': current_user.role,
        'iat': utc_now().timestamp(),
    })
    return redirect(f'{alta_url}/sso_login?token={token}')


# --- NUEVO MÓDULO DE LOGS Y AUDITORÍA ---
@admin_bp.route("/logs", methods=["GET"])
@login_required
@roles_required(ROLE_ADMIN, ROLE_LABORAL)
def system_logs():
    from app.models import SystemLog, LogPreference
    from app.services.log_notification_service import (
        get_unread_logs_by_category,
        get_unread_laboral_logs_by_category,
        get_laboral_acknowledged_ids,
        LABORAL_LOG_CATEGORIES,
        LABORAL_EXCLUDED_ACTIONS,
    )
    from datetime import timedelta

    allowed_categories = laboral_log_categories(current_user)
    if is_laboral(current_user):
        default_category = allowed_categories[0] if allowed_categories else 'solicitud'
    else:
        default_category = 'accesos'
    category = request.args.get('category', default_category)
    if category not in allowed_categories:
        category = default_category
    from app.utils.timezone_utils import utc_now, today_local

    logs = []
    laboral_acked_ids = set()
    if category != 'persona_obra':
        logs_q = SystemLog.query.filter_by(category=category)
        if category == 'valoraciones':
            from app.services.panel_scope_service import (
                valoraciones_acts_as_office,
                valoraciones_visible_author_ids,
            )
            if not valoraciones_acts_as_office(current_user):
                allowed = valoraciones_visible_author_ids(current_user) or set()
                # Solo logs de valoraciones firmadas por autores de su alcance
                if allowed:
                    logs_q = logs_q.filter(SystemLog.user_id.in_(list(allowed)))
                else:
                    logs_q = logs_q.filter(SystemLog.id.is_(None))
        logs = logs_q.order_by(SystemLog.timestamp.desc()).limit(300).all()

        if current_user.role == ROLE_ADMIN:
            pref = LogPreference.query.filter_by(user_id=current_user.id, category=category).first()
            if pref and pref.is_active:
                pref.last_read_at = utc_now()
                db.session.commit()

        if category in LABORAL_LOG_CATEGORIES:
            from app.services.tenant_modules import has_avisos_laborales
            if has_avisos_laborales():
                laboral_acked_ids = get_laboral_acknowledged_ids(
                    current_user.id, [log.id for log in logs]
                )

    active_prefs = []
    if current_user.role == ROLE_ADMIN:
        all_prefs = LogPreference.query.filter_by(user_id=current_user.id).all()
        active_prefs = [p.category for p in all_prefs if p.is_active]

    today = today_local()
    from app.services.tenant_modules import has_avisos_laborales
    avisos_laborales = has_avisos_laborales()
    return render_template(
        "admin_logs.html",
        logs=logs,
        current_category=category,
        active_prefs=active_prefs,
        log_unread_by_category=(
            get_unread_laboral_logs_by_category(current_user.id)
            if is_laboral(current_user) and avisos_laborales
            else get_unread_logs_by_category(current_user.id, active_only=True)
        ),
        laboral_acked_ids=laboral_acked_ids,
        laboral_excluded_actions=LABORAL_EXCLUDED_ACTIONS,
        default_date=today.strftime('%Y-%m-%d'),
        default_date_from=(today - timedelta(days=7)).strftime('%Y-%m-%d'),
        default_date_to=today.strftime('%Y-%m-%d'),
        can_manage_log_prefs=user_can(current_user, 'logs', 'w'),
        log_tabs=allowed_categories,
        tenant_has_avisos_laborales=avisos_laborales,
    )


@admin_bp.route("/logs/<int:log_id>/acknowledge", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN, ROLE_LABORAL)
def acknowledge_system_log(log_id):
    from app.services.tenant_modules import has_avisos_laborales
    if not has_avisos_laborales():
        return jsonify({'ok': False, 'error': translate('No disponible')}), 404
    from app.services.log_notification_service import acknowledge_log
    acknowledge_log(current_user.id, log_id)
    return jsonify({'ok': True})


@admin_bp.route("/logs/<int:log_id>/unacknowledge", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN, ROLE_LABORAL)
def unacknowledge_system_log(log_id):
    from app.services.tenant_modules import has_avisos_laborales
    if not has_avisos_laborales():
        return jsonify({'ok': False, 'error': translate('No disponible')}), 404
    from app.services.log_notification_service import unacknowledge_log
    unacknowledge_log(current_user.id, log_id)
    return jsonify({'ok': True})


@admin_bp.route("/logs/acknowledge-all-laboral", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def acknowledge_all_laboral_system_logs():
    """Admin: marca como leídos TODOS los avisos laborales para todos los usuarios."""
    from app.services.tenant_modules import has_avisos_laborales
    if not has_avisos_laborales():
        return jsonify({'ok': False, 'error': translate('No disponible')}), 404
    from app.services.log_notification_service import acknowledge_all_laboral_logs_global
    remaining = acknowledge_all_laboral_logs_global()
    return jsonify({'ok': True, 'remaining': remaining})


@admin_bp.route("/logs/preferencias", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def save_log_preferences():
    from app.models import LogPreference
    from app.services.tenant_modules import has_valoraciones
    categorias = ['accesos', 'planificacion', 'obras', 'fichajes', 'solicitud']
    if has_valoraciones():
        categorias.insert(1, 'valoraciones')
    
    for cat in categorias:
        pref = LogPreference.query.filter_by(user_id=current_user.id, category=cat).first()
        if not pref:
            pref = LogPreference(user_id=current_user.id, category=cat)
            db.session.add(pref)
            
        # Si el checkbox está marcado viene 'on', si no, False
        pref.is_active = True if request.form.get(f'pref_{cat}') == 'on' else False
        
    db.session.commit()
    flash(translate("Preferencias de notificaciones actualizadas."), "success")
    return redirect(url_for('admin.system_logs', category=request.form.get('current_category', 'accesos')))


# ==========================================
# AUSENCIAS PLANIFICADAS
# ==========================================

@admin_bp.route('/ausencias')
@login_required
@roles_required(ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL, ROLE_RRHH)
def ausencias_list():
    from datetime import date as date_cls
    from app.services.leave_service import (
        actor_puede_crear_ausencia,
        actor_puede_gestionar_ausencias,
        actor_puede_resolver_conflictos_ausencia,
        get_pending_conflicts,
        get_pending_manual_leaves,
        get_upcoming_leaves,
        get_leaves_scoped,
        obras_for_leave,
        obra_ids_for_leave_actor,
        auto_resolucion_ausencias,
        heal_odoo_pending_leaves,
    )
    from app.services.permission_service import user_can

    if not user_can(current_user, 'ausencias', 'r'):
        flash(translate('No tienes permisos para ver ausencias.'), 'danger')
        return redirect(url_for('main.dashboard'))

    # Vacaciones de Odoo no pasan por validación local.
    heal_odoo_pending_leaves()

    estado = request.args.get('estado') or ''
    puede_resolver = actor_puede_resolver_conflictos_ausencia(current_user)
    puede_gestionar = actor_puede_gestionar_ausencias(current_user)
    obra_ids = obra_ids_for_leave_actor(current_user)

    auto_mode = auto_resolucion_ausencias()
    conflictos = []
    if auto_mode == 'none' and puede_resolver:
        conflictos = get_pending_conflicts(obra_ids=obra_ids)

    def _rows(leaves):
        return [{'leave': leave, 'obras': obras_for_leave(leave)} for leave in leaves]

    en_curso_rows = _rows(get_upcoming_leaves(
        current_user, horizon_days=45, limit=40, only_active=True
    ))
    proximas_rows = _rows(get_upcoming_leaves(
        current_user, horizon_days=45, limit=40, only_future=True
    ))
    ausencias = get_leaves_scoped(current_user, estado=estado or None, limit=200)
    pendientes = []
    if user_can(current_user, 'ausencias', 'w'):
        pendientes = get_pending_manual_leaves(current_user, limit=100)

    return render_template(
        'admin_ausencias.html',
        ausencias=ausencias,
        pendientes=pendientes,
        en_curso_rows=en_curso_rows,
        proximas_rows=proximas_rows,
        conflictos=conflictos,
        puede_resolver=puede_resolver,
        puede_validar_pendientes=puede_gestionar,
        puede_alta_manual=actor_puede_crear_ausencia(current_user),
        ausencias_es_oficina=puede_gestionar,
        filtro_estado=estado,
        auto_mode=auto_mode,
        today=date_cls.today(),
        horizon_days=45,
    )


@admin_bp.route('/ausencias/sync', methods=['POST'])
@login_required
@roles_required(ROLE_ADMIN, ROLE_LABORAL)
def ausencias_sync():
    modulos = getattr(getattr(g, 'current_tenant', None), 'modulos_activos', {}) or {}
    if not modulos.get('odoo'):
        return redirect(url_for('admin.ausencias_list'))
    from app.services.leave_service import sync_leaves_from_erp
    try:
        stats = sync_leaves_from_erp(
            modo='Manual',
            actor=current_user,
            origen_label='Manual · pantalla Ausencias',
        )
        flash(
            translate(
                "Sync ausencias: {nuevos} nuevas, {actualizados} con cambios, "
                "{sin_cambio} sin cambio, {omitidos} omitidas, {errores} errores.",
                nuevos=stats['nuevos'],
                actualizados=stats['actualizados'],
                sin_cambio=stats.get('sin_cambio', 0),
                omitidos=stats['omitidos'],
                errores=stats['errores'],
            ),
            'success' if stats['errores'] == 0 else 'warning',
        )
    except Exception as exc:
        flash(translate('Error sincronizando ausencias: {error}', error=exc), 'danger')
    return redirect(url_for('admin.ausencias_list'))


@admin_bp.route('/ausencias/crear', methods=['POST'])
@login_required
@roles_required(ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL, ROLE_RRHH)
def ausencias_crear():
    from app.services.leave_service import (
        actor_puede_crear_ausencia,
        create_manual_leave,
        estado_alta_por_permiso,
    )

    if not actor_puede_crear_ausencia(current_user):
        flash(translate('No tienes permiso para crear ausencias.'), 'danger')
        return redirect(url_for('admin.ausencias_list'))

    user_id = request.form.get('user_id', type=int)
    fecha_inicio = request.form.get('fecha_inicio')
    fecha_fin = request.form.get('fecha_fin')
    tipo = (request.form.get('tipo') or 'Vacaciones').strip()
    estado = estado_alta_por_permiso(current_user, request.form.get('estado'))
    descripcion = request.form.get('descripcion') or None

    if not user_id or not fecha_inicio or not fecha_fin:
        flash(translate('Faltan empleado o fechas.'), 'danger')
        return redirect(url_for('admin.ausencias_list'))

    try:
        leave = create_manual_leave(
            user_id=user_id,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            tipo=tipo,
            estado=estado,
            descripcion=descripcion,
            created_by_id=current_user.id,
        )
        if leave.estado == 'pendiente':
            flash(translate('Solicitud de ausencia enviada. Pendiente de validación.'), 'info')
        else:
            flash(translate('Ausencia creada.'), 'success')
    except Exception as exc:
        flash(translate('Error al crear ausencia: {error}', error=exc), 'danger')
    return redirect(url_for('admin.ausencias_list'))


@admin_bp.route('/ausencias/<int:leave_id>/aprobar', methods=['POST'])
@login_required
@roles_required(ROLE_ADMIN, ROLE_LABORAL, ROLE_RRHH)
def ausencias_aprobar(leave_id):
    from app.models import LEAVE_STATUS_APROBADA
    from app.services.leave_service import set_leave_estado
    try:
        set_leave_estado(leave_id, LEAVE_STATUS_APROBADA, resolved_by_id=current_user.id)
        flash(translate('Ausencia aprobada.'), 'success')
    except Exception as exc:
        flash(translate(str(exc)), 'danger')
    return redirect(url_for('admin.ausencias_list'))


@admin_bp.route('/ausencias/<int:leave_id>/rechazar', methods=['POST'])
@login_required
@roles_required(ROLE_ADMIN, ROLE_LABORAL, ROLE_RRHH)
def ausencias_rechazar(leave_id):
    from app.models import LEAVE_STATUS_RECHAZADA
    from app.services.leave_service import set_leave_estado
    try:
        set_leave_estado(leave_id, LEAVE_STATUS_RECHAZADA, resolved_by_id=current_user.id)
        flash(translate('Ausencia rechazada.'), 'info')
    except Exception as exc:
        flash(translate(str(exc)), 'danger')
    return redirect(url_for('admin.ausencias_list'))


@admin_bp.route('/ausencias/<int:leave_id>/editar', methods=['POST'])
@login_required
@roles_required(ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL, ROLE_RRHH)
def ausencias_editar(leave_id):
    from app.services.leave_service import update_manual_leave
    try:
        leave = update_manual_leave(
            leave_id,
            current_user,
            fecha_inicio=request.form.get('fecha_inicio') or None,
            fecha_fin=request.form.get('fecha_fin') or None,
            tipo=request.form.get('tipo'),
            descripcion=request.form.get('descripcion'),
        )
        if leave.estado == 'pendiente':
            flash(translate('Ausencia actualizada y pendiente de validación.'), 'info')
        else:
            flash(translate('Ausencia actualizada.'), 'success')
    except Exception as exc:
        flash(translate(str(exc)), 'danger')
    return redirect(url_for('admin.ausencias_list'))


@admin_bp.route('/ausencias/<int:leave_id>/borrar', methods=['POST'])
@login_required
@roles_required(ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL, ROLE_RRHH)
def ausencias_borrar(leave_id):
    from app.services.leave_service import delete_manual_leave
    try:
        delete_manual_leave(leave_id, current_user)
        flash(translate('Ausencia eliminada.'), 'success')
    except Exception as exc:
        flash(translate(str(exc)), 'danger')
    return redirect(url_for('admin.ausencias_list'))


@admin_bp.route('/ausencias/conflictos/<int:conflict_id>/resolver', methods=['POST'])
@login_required
@roles_required(ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL)
def ausencias_resolver_conflicto(conflict_id):
    from app.models import AusenciaConflicto, CONFLICT_KEEP_LEAVE, CONFLICT_KEEP_ASSIGNMENT
    from app.services.leave_service import (
        actor_puede_resolver_conflictos_ausencia,
        resolve_conflict,
    )
    from app.services.panel_scope_service import obra_in_planning_custody

    if not actor_puede_resolver_conflictos_ausencia(current_user):
        flash(translate('No tienes permiso para resolver conflictos de ausencias.'), 'danger')
        return redirect(url_for('admin.ausencias_list'))

    decision = request.form.get('decision')
    if decision not in (CONFLICT_KEEP_LEAVE, CONFLICT_KEEP_ASSIGNMENT):
        flash(translate('Decisión no válida.'), 'danger')
        return redirect(url_for('admin.ausencias_list'))

    conflict = AusenciaConflicto.query.get_or_404(conflict_id)
    obra = Obra.query.get(conflict.obra_id)
    if not obra_in_planning_custody(current_user, obra):
        flash(translate('Solo puedes resolver conflictos de obras de tu alcance.'), 'danger')
        return redirect(url_for('admin.ausencias_list'))

    try:
        ok = resolve_conflict(conflict_id, decision, resolved_by_id=current_user.id)
        db.session.commit()
        flash(translate('Conflicto resuelto.') if ok else translate('El conflicto ya estaba resuelto.'), 'success')
    except Exception as exc:
        db.session.rollback()
        flash(translate('Error al resolver: {error}', error=exc), 'danger')
    return redirect(url_for('admin.ausencias_list'))


# ---------------------------------------------------------------------------
# Registro de jornada (informe para la Inspección)
# ---------------------------------------------------------------------------

def _parametros_informe():
    from app.services.fichaje_informe_service import (
        FichajeInformeError,
        generar_informe,
        periodo_por_defecto,
    )

    desde_def, hasta_def = periodo_por_defecto()
    desde = request.args.get('desde') or desde_def.isoformat()
    hasta = request.args.get('hasta') or hasta_def.isoformat()
    user_id = request.args.get('user_id') or None
    company_id = request.args.get('company_id') or None

    if user_id in ('', '0'):
        user_id = None
    if company_id in ('', '0'):
        company_id = None

    tenant_nombre = g.current_tenant.nombre if getattr(g, 'current_tenant', None) else None
    try:
        return generar_informe(
            desde=desde,
            hasta=hasta,
            user_id=user_id,
            company_id=company_id,
            tenant_nombre=tenant_nombre,
        )
    except FichajeInformeError as exc:
        flash(translate(str(exc)), 'warning')
        return None


@admin_bp.route('/registro-jornada')
@login_required
@roles_required(ROLE_ADMIN, ROLE_LABORAL)
def registro_jornada():
    """
    Pantalla de consulta y descarga del registro de jornada.

    Es lo que se enseña a la Inspección: detalle por trabajador y verificación
    de que el libro de eventos no ha sido manipulado.
    """
    from app.services.fichaje_informe_service import (
        etiquetar_tipo,
        formatear_horas,
        listar_empresas_para_filtro,
        listar_trabajadores_para_filtro,
        periodo_por_defecto,
    )
    from app.services.onboarding_service import tenant_tiene_registro_jornada

    if not tenant_tiene_registro_jornada():
        return redirect(url_for('admin.panel'))

    desde_def, hasta_def = periodo_por_defecto()
    hay_filtros = any(
        request.args.get(k) for k in ('desde', 'hasta', 'user_id', 'company_id')
    )
    informe = _parametros_informe() if hay_filtros or request.args.get('generar') else None

    if informe is not None:
        from app.services.onboarding_service import marcar_informe_visto
        try:
            marcar_informe_visto()
        except Exception:
            pass

    url_fichaje_mi = None
    try:
        from app.services.signup_service import url_acceso_tenant
        if getattr(g, 'current_tenant', None):
            url_fichaje_mi = url_acceso_tenant(g.current_tenant, path='/auth/login')
    except Exception:
        url_fichaje_mi = None

    return render_template(
        'admin_registro_jornada.html',
        informe=informe,
        trabajadores=listar_trabajadores_para_filtro(),
        empresas=listar_empresas_para_filtro(),
        desde=request.args.get('desde') or desde_def.isoformat(),
        hasta=request.args.get('hasta') or hasta_def.isoformat(),
        user_id=request.args.get('user_id') or '',
        company_id=request.args.get('company_id') or '',
        formatear_horas=formatear_horas,
        etiquetar_tipo=etiquetar_tipo,
        desde_onboarding=bool(request.args.get('desde_onboarding')),
        url_fichaje_mi=url_fichaje_mi,
    )


@admin_bp.route('/registro-jornada/imprimir')
@login_required
@roles_required(ROLE_ADMIN, ROLE_LABORAL)
def registro_jornada_imprimir():
    from app.services.fichaje_informe_service import etiquetar_tipo, formatear_horas
    from app.services.onboarding_service import tenant_tiene_registro_jornada

    if not tenant_tiene_registro_jornada():
        return redirect(url_for('admin.panel'))

    informe = _parametros_informe()
    if informe is None:
        return redirect(url_for('admin.registro_jornada'))

    return render_template(
        'admin_registro_jornada_print.html',
        informe=informe,
        formatear_horas=formatear_horas,
        etiquetar_tipo=etiquetar_tipo,
    )


@admin_bp.route('/registro-jornada.csv')
@login_required
@roles_required(ROLE_ADMIN, ROLE_LABORAL)
def registro_jornada_csv():
    from flask import Response
    from app.services.fichaje_informe_service import informe_a_csv
    from app.services.onboarding_service import tenant_tiene_registro_jornada

    if not tenant_tiene_registro_jornada():
        return redirect(url_for('admin.panel'))

    informe = _parametros_informe()
    if informe is None:
        return redirect(url_for('admin.registro_jornada'))

    archivo = (
        f"registro_jornada_{informe['desde']}_{informe['hasta']}.csv"
    )
    return Response(
        informe_a_csv(informe),
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename="{archivo}"'},
    )


@admin_bp.route('/registro-jornada.pdf')
@login_required
@roles_required(ROLE_ADMIN, ROLE_LABORAL)
def registro_jornada_pdf():
    """
    PDF generado con wkhtmltopdf a partir de la misma plantilla de impresión.

    Si el binario no está disponible, se redirige a la vista imprimible: el
    navegador puede guardar como PDF sin perder el contenido.
    """
    from flask import make_response
    from app.services.fichaje_informe_service import etiquetar_tipo, formatear_horas
    from app.services.onboarding_service import tenant_tiene_registro_jornada

    if not tenant_tiene_registro_jornada():
        return redirect(url_for('admin.panel'))

    informe = _parametros_informe()
    if informe is None:
        return redirect(url_for('admin.registro_jornada'))

    html = render_template(
        'admin_registro_jornada_print.html',
        informe=informe,
        formatear_horas=formatear_horas,
        etiquetar_tipo=etiquetar_tipo,
        para_pdf=True,
    )

    try:
        import pdfkit
        pdf = pdfkit.from_string(
            html,
            False,
            options={
                'page-size': 'A4',
                'encoding': 'UTF-8',
                'margin-top': '12mm',
                'margin-bottom': '14mm',
                'margin-left': '12mm',
                'margin-right': '12mm',
                'print-media-type': None,
                'quiet': '',
            },
        )
    except Exception as exc:
        current_app.logger.warning('No se pudo generar el PDF del registro: %s', exc)
        flash(translate('No se ha podido generar el PDF en el servidor. '
            'Usa «Versión para imprimir» y guárdalo como PDF desde el navegador.'),
            'warning',
        )
        return redirect(url_for(
            'admin.registro_jornada_imprimir',
            desde=request.args.get('desde'),
            hasta=request.args.get('hasta'),
            user_id=request.args.get('user_id') or '',
            company_id=request.args.get('company_id') or '',
        ))

    archivo = f"registro_jornada_{informe['desde']}_{informe['hasta']}.pdf"
    respuesta = make_response(pdf)
    respuesta.headers['Content-Type'] = 'application/pdf'
    respuesta.headers['Content-Disposition'] = f'attachment; filename="{archivo}"'
    return respuesta

