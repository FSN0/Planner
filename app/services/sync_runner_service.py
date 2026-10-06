"""Ejecución de sync automática por módulo (usado por Celery y «Auto ahora»)."""
import secrets
import time
from datetime import datetime

from werkzeug.security import generate_password_hash

from app import db
from app.models import Obra, User, Company, SyncLog
from app.sync.dispatcher import get_sync_adapter
from app.utils.timezone_utils import utc_now
from app.services.odoo_employee_metadata import (
    apply_odoo_employee_external_ids,
    build_external_ids_for_new_employee,
)


def _log_estado(errores, had_exception=False):
    if had_exception:
        return 'error'
    if errores and errores > 0:
        return 'parcial'
    return 'ok'


def _company_by_odoo_id(odoo_c_id):
    if not odoo_c_id:
        return None
    return Company.query.filter(Company.external_ids['odoo'].astext == str(odoo_c_id)).first()


def _email_sync_seguro(user, email_nuevo: str) -> bool:
    """No pisa un correo real del planner con el sintético de Odoo."""
    from app.services.compliance_rules import email_es_real
    email_nuevo = (email_nuevo or '').strip()
    if not email_nuevo or email_nuevo == (user.email or ''):
        return False
    if email_es_real(user.email) and not email_es_real(email_nuevo):
        return False
    return not User.query.filter(User.email == email_nuevo, User.id != user.id).first()


def _set_odoo_external_id(entity, odoo_id):
    ext_ids = dict(entity.external_ids or {})
    ext_ids['odoo'] = str(odoo_id)
    entity.external_ids = ext_ids
    db.session.add(entity)


def run_auto_sync_obras(modo='Automático'):
    t0 = time.time()
    ahora = utc_now()
    try:
        service = get_sync_adapter()
        diff = service.get_diff_obras()
        nuevas_limpias = [o for o in diff['nuevas'] if not o.get('warn_jefe') and not o.get('warn_encargado')]
        act_limpias = [o for o in diff['actualizadas'] if not o.get('warn_jefe') and not o.get('warn_encargado')]
        errores = (len(diff['nuevas']) - len(nuevas_limpias)) + (len(diff['actualizadas']) - len(act_limpias))

        for obj in nuevas_limpias:
            f_inicio = datetime.strptime(obj['fecha_inicio'], "%Y-%m-%d").date() if obj.get('fecha_inicio') else None
            from app.services.obra_estado_service import (
                ESTADO_EN_GARANTIA,
                ESTADO_PENDIENTE,
            )
            # Ejecución nueva → Pendiente (oficina activa). Garantía → ya planificable.
            estado_in = obj.get('estado') or ESTADO_PENDIENTE
            estado = (
                ESTADO_EN_GARANTIA
                if estado_in == ESTADO_EN_GARANTIA
                else ESTADO_PENDIENTE
            )
            db.session.add(Obra(
                external_ids={'odoo': str(obj['odoo_id'])},
                codigo=obj['codigo'], nombre=obj['nombre'],
                descripcion=obj.get('cliente', ''), fecha_inicio=f_inicio, estado=estado,
                jefe_obra_id=obj.get('jefe_obra_id'), encargado_id=obj.get('encargado_id'),
                fecha_importacion=ahora,
            ))

        for obj in act_limpias:
            obra = Obra.query.get(obj['local_id'])
            if obra:
                _set_odoo_external_id(obra, obj['odoo_id'])
                obra.codigo = obj['codigo']
                obra.nombre = obj['nombre']
                obra.descripcion = obj.get('cliente', '')
                obra.fecha_importacion = ahora
                if obj.get('fecha_inicio'):
                    obra.fecha_inicio = datetime.strptime(obj['fecha_inicio'], "%Y-%m-%d").date()
                if obj.get('jefe_obra_id'):
                    obra.jefe_obra_id = obj['jefe_obra_id']
                if obj.get('encargado_id'):
                    obra.encargado_id = obj['encargado_id']
                if obj.get('estado'):
                    obra.estado = obj['estado']
                    if obj['estado'] != 'Finalizada':
                        obra.fecha_fin = None

        for obj in diff['finalizadas']:
            obra = Obra.query.get(obj['local_id'])
            if obra:
                obra.estado = 'Finalizada'
                obra.fecha_fin = ahora.date()
                obra.fecha_importacion = ahora

        detalle = f"Sync automática obras. {errores} omitida(s) por responsables sin resolver." if errores else "Sync automática obras completada."
        db.session.add(SyncLog(
            fecha=ahora, tipo='Obras', modo=modo,
            nuevos=len(nuevas_limpias), actualizados=len(act_limpias),
            finalizados=len(diff['finalizadas']), errores=errores,
            detalles=detalle, estado=_log_estado(errores),
            duracion_ms=int((time.time() - t0) * 1000),
        ))
        db.session.commit()
        try:
            from app.services.sync_preview_cache_service import cache_from_diff
            cache_from_diff('obras', diff, source='auto')
        except Exception:
            pass
        return {'nuevos': len(nuevas_limpias), 'actualizados': len(act_limpias), 'omitidos': errores}
    except Exception as e:
        db.session.rollback()
        db.session.add(SyncLog(
            fecha=utc_now(), tipo='Obras', modo=modo,
            nuevos=0, actualizados=0, finalizados=0, errores=1,
            detalles='Fallo en sincronización automática de obras.',
            estado='error', mensaje_error=str(e),
            duracion_ms=int((time.time() - t0) * 1000),
        ))
        db.session.commit()
        raise


def run_auto_sync_empleados(modo='Automático'):
    t0 = time.time()
    ahora = utc_now()
    service = get_sync_adapter()
    diff = service.get_diff_empleados()
    emp_nuevos = diff['nuevos']
    emp_act = [e for e in diff['actualizados'] if not e.get('conflicto')]
    emp_baja = diff.get('desactivados') or []
    errores = len(diff['actualizados']) - len(emp_act)
    default_company = Company.query.filter_by(is_internal=True).first() or Company.query.first()
    default_company_id = default_company.id if default_company else None

    from app.services.employee_baja_service import (
        aplicar_baja_por_odoo,
        desactivados_aplicables,
        reactivar,
    )

    for obj in emp_nuevos:
        from app.services.auth_login_service import default_auth_mode_for_role
        db.session.add(User(
            external_ids=build_external_ids_for_new_employee(
                obj['odoo_id'],
                department=obj.get('departamento'),
                barcode=obj.get('barcode'),
                import_source='sync_empleados_auto',
            ),
            name=obj['name'], lastname=obj['lastname'],
            dni=obj['dni'], email=obj['email'], role=obj['role'],
            categoria_profesional=obj.get('categoria_profesional', 'Sin definir'),
            company_id=default_company_id, active=True, email_verified=True,
            password_hash=generate_password_hash(secrets.token_urlsafe(24)),
            auth_mode=default_auth_mode_for_role(obj['role']),
        ))

    for obj in emp_act:
        user = User.query.get(obj['local_id'])
        if user:
            apply_odoo_employee_external_ids(
                user,
                obj['odoo_id'],
                department=obj.get('departamento'),
                barcode=obj.get('barcode'),
                import_source='sync_empleados_auto',
            )
            user.name = obj['name']
            user.lastname = obj['lastname']
            from app.services.user_role_sync_service import apply_odoo_role_if_allowed
            apply_odoo_role_if_allowed(user, obj['role'])
            user.categoria_profesional = obj.get('categoria_profesional', user.categoria_profesional)
            if not user.active:
                reactivar(user, commit=False)
            else:
                user.active = True

    for obj in diff.get('sin_cambios') or []:
        user = User.query.get(obj.get('local_id'))
        if user:
            apply_odoo_employee_external_ids(
                user,
                obj['odoo_id'],
                department=obj.get('departamento'),
                barcode=obj.get('barcode'),
            )

    emp_baja_aplicables = desactivados_aplicables(diff, emp_baja)
    for obj in emp_baja_aplicables:
        local_id = obj.get('local_id')
        if local_id:
            aplicar_baja_por_odoo(local_id, commit=False)

    detalle = f"Sync automática empleados. {errores} omitido(s) por conflictos DNI/email." if errores else "Sync automática empleados completada."
    if emp_baja_aplicables:
        detalle = f"{detalle} {len(emp_baja_aplicables)} baja(s)."
    db.session.add(SyncLog(
        fecha=ahora, tipo='Empleados', modo=modo,
        nuevos=len(emp_nuevos), actualizados=len(emp_act),
        finalizados=len(emp_baja_aplicables), errores=errores,
        detalles=detalle, estado=_log_estado(errores),
        duracion_ms=int((time.time() - t0) * 1000),
    ))
    db.session.commit()
    try:
        from app.services.sync_preview_cache_service import cache_from_diff
        cache_from_diff('empleados', diff, source='auto')
    except Exception:
        pass
    return {
        'nuevos': len(emp_nuevos),
        'actualizados': len(emp_act),
        'desactivados': len(emp_baja_aplicables),
        'omitidos': errores,
    }


def run_auto_sync_subcontratas(modo='Automático'):
    t0 = time.time()
    ahora = utc_now()
    service = get_sync_adapter()
    diff = service.get_diff_subcontratas()
    mapa_empresas = {}
    emp_baja = (diff.get('empleados') or {}).get('desactivados') or []

    from app.services.employee_baja_service import (
        aplicar_baja_por_odoo,
        desactivados_aplicables,
        reactivar,
    )

    for obj in list(diff['empresas'].get('actualizadas') or []) + list(diff['empresas'].get('rellenar_cif') or []):
        comp = Company.query.get(obj['local_id'])
        if comp:
            _set_odoo_external_id(comp, obj['odoo_id'])
            if obj.get('nombre'):
                comp.nombre = obj['nombre']
            if obj.get('cif'):
                comp.nif = obj['cif']
            if not getattr(comp, 'active', True):
                comp.active = True
            mapa_empresas[obj['odoo_id']] = comp.id

    for obj in diff['empresas']['nuevas']:
        nueva = Company(
            external_ids={'odoo': str(obj['odoo_id'])},
            nombre=obj['nombre'],
            nif=(obj.get('cif') or None) or None,
            active=True,
            is_internal=False,
        )
        db.session.add(nueva)
        db.session.flush()
        mapa_empresas[obj['odoo_id']] = nueva.id

    for obj in diff['empleados']['actualizados']:
        # No reescribir identidad si el Id Odoo saltó a otro partner no ligado.
        if (obj.get('cambios') or {}).get('Id Odoo'):
            continue
        user = User.query.get(obj['local_id'])
        if user:
            _set_odoo_external_id(user, obj['odoo_id'])
            user.name = obj['name']
            user.lastname = obj['lastname']
            user.is_deleted = False
            if obj['dni'] and 'SINDNI' not in obj['dni']:
                choque = User.query.filter(User.dni == obj['dni'], User.id != user.id).first()
                user.dni = f"{obj['dni']}-EXT{obj['odoo_id']}" if choque else obj['dni']
            email_nuevo = (obj.get('email') or '').strip()
            if _email_sync_seguro(user, email_nuevo):
                user.email = email_nuevo
            user.categoria_profesional = obj.get('categoria_profesional')
            if obj.get('role'):
                from app.services.user_role_sync_service import apply_subcontrata_portal_role
                apply_subcontrata_portal_role(user, obj['role'])
            odoo_c_id = obj.get('odoo_company_id')
            if odoo_c_id:
                if odoo_c_id not in mapa_empresas:
                    comp = _company_by_odoo_id(odoo_c_id)
                    if comp:
                        mapa_empresas[odoo_c_id] = comp.id
                if odoo_c_id in mapa_empresas:
                    user.company_id = mapa_empresas[odoo_c_id]
            if not user.active:
                reactivar(user, commit=False)
            else:
                user.active = True

    dnis_en_tx = set()
    emails_en_tx = set()
    from sqlalchemy.exc import IntegrityError

    for obj in diff['empleados']['nuevos']:
        odoo_c_id = obj.get('odoo_company_id')
        local_comp_id = mapa_empresas.get(odoo_c_id)
        if not local_comp_id and odoo_c_id:
            with db.session.no_autoflush:
                comp = _company_by_odoo_id(odoo_c_id)
            if comp:
                local_comp_id = comp.id
                mapa_empresas[odoo_c_id] = local_comp_id
        dni = obj['dni']
        email = (obj.get('email') or '').strip() or f"ext_{obj['odoo_id']}@subcontrata.local"

        with db.session.no_autoflush:
            existente = User.query.filter(
                (User.dni == dni)
                | (User.external_ids['odoo'].astext == str(obj['odoo_id']))
            ).order_by(User.is_deleted.asc(), User.id.asc()).first()
            if not existente:
                existente = User.query.filter(
                    User.dni == f"{dni}-EXT{obj['odoo_id']}"
                ).first()
            if not existente:
                existente = User.query.filter(
                    User.external_ids['odoo'].astext == str(obj['odoo_id'])
                ).first()

        if existente:
            _set_odoo_external_id(existente, obj['odoo_id'])
            existente.name = obj['name']
            existente.lastname = obj['lastname']
            existente.categoria_profesional = obj.get('categoria_profesional')
            existente.company_id = local_comp_id or existente.company_id
            existente.is_deleted = False
            if not existente.active:
                reactivar(existente, commit=False)
            else:
                existente.active = True
            email_nuevo = (obj.get('email') or '').strip()
            if _email_sync_seguro(existente, email_nuevo):
                existente.email = email_nuevo
            if obj.get('role'):
                from app.services.user_role_sync_service import apply_subcontrata_portal_role
                apply_subcontrata_portal_role(existente, obj['role'])
            dnis_en_tx.add(existente.dni)
            emails_en_tx.add(existente.email)
            continue

        with db.session.no_autoflush:
            choque_dni = User.query.filter_by(dni=dni).first()
            choque_email = User.query.filter_by(email=email).first()
        if choque_dni or dni in dnis_en_tx:
            dni = f"{dni}-EXT{obj['odoo_id']}"
        if choque_email or email in emails_en_tx:
            email = f"ext_{obj['odoo_id']}_dup@subcontrata.local"
        dnis_en_tx.add(dni)
        emails_en_tx.add(email)

        nuevo = User(
            external_ids={'odoo': str(obj['odoo_id'])},
            name=obj['name'], lastname=obj['lastname'],
            dni=dni, email=email, role=obj['role'],
            categoria_profesional=obj.get('categoria_profesional'),
            company_id=local_comp_id, active=True, email_verified=True,
            password_hash=generate_password_hash(secrets.token_urlsafe(24)),
        )
        try:
            with db.session.begin_nested():
                db.session.add(nuevo)
                db.session.flush()
        except IntegrityError:
            # Carrera / fantasma: reutilizar la ficha que ya tiene ese email o DNI.
            with db.session.no_autoflush:
                existente = User.query.filter(
                    (User.email == email) | (User.dni == dni)
                    | (User.external_ids['odoo'].astext == str(obj['odoo_id']))
                ).first()
            if not existente:
                raise
            _set_odoo_external_id(existente, obj['odoo_id'])
            existente.name = obj['name']
            existente.lastname = obj['lastname']
            existente.categoria_profesional = obj.get('categoria_profesional')
            existente.company_id = local_comp_id or existente.company_id
            existente.is_deleted = False
            if not existente.active:
                reactivar(existente, commit=False)
            else:
                existente.active = True
            if obj.get('role'):
                from app.services.user_role_sync_service import apply_subcontrata_portal_role
                apply_subcontrata_portal_role(existente, obj['role'])
            dnis_en_tx.add(existente.dni)
            emails_en_tx.add(existente.email)

    emp_baja_aplicables = desactivados_aplicables(diff, emp_baja)
    for obj in emp_baja_aplicables:
        local_id = obj.get('local_id')
        if local_id:
            aplicar_baja_por_odoo(local_id, commit=False)

    tot_n = len(diff['empresas']['nuevas']) + len(diff['empleados']['nuevos'])
    tot_a = len(diff['empresas']['actualizadas']) + len(diff['empleados']['actualizados'])
    detalle = "Sync automática subcontratas completada."
    if emp_baja_aplicables:
        detalle = f"{detalle} {len(emp_baja_aplicables)} baja(s)."
    db.session.add(SyncLog(
        fecha=ahora, tipo='Subcontratas', modo=modo,
        nuevos=tot_n, actualizados=tot_a, finalizados=len(emp_baja_aplicables), errores=0,
        detalles=detalle,
        estado='ok', duracion_ms=int((time.time() - t0) * 1000),
    ))
    db.session.commit()
    return {
        'nuevos': tot_n,
        'actualizados': tot_a,
        'desactivados': len(emp_baja_aplicables),
        'omitidos': 0,
    }


def run_fichajes_retro_sync(days=None, modo='Automático'):
    """Revisa fichajes de hoy y N días atrás para detectar cambios en Odoo."""
    from datetime import timedelta

    from app.services.sync_config_service import SyncConfigService
    from app.services.sync_service import procesar_fichajes_diarios
    from app.utils.timezone_utils import today_local

    cfg = SyncConfigService.get_config()
    dias = int(days if days is not None else cfg['fichajes_retro_days'])
    dias = max(1, min(365, dias))

    t0 = time.time()
    had_error = False
    err_msg = None

    try:
        for i in range(dias + 1):
            fecha_revision = (today_local() - timedelta(days=i)).strftime('%Y-%m-%d')
            procesar_fichajes_diarios(fecha_str=fecha_revision)
    except Exception as e:
        had_error = True
        err_msg = str(e)
        db.session.rollback()

    detalle = f"Revisión retrospectiva de fichajes (hoy + últimos {dias} días)."
    db.session.add(SyncLog(
        fecha=utc_now(),
        tipo='Fichajes (Auditoría)' if modo == 'Manual' else 'Fichajes (Retrospectivo)',
        modo=modo,
        nuevos=0,
        actualizados=0,
        finalizados=0,
        errores=1 if had_error else 0,
        detalles=detalle,
        estado=_log_estado(1 if had_error else 0, had_exception=had_error),
        duracion_ms=int((time.time() - t0) * 1000),
        mensaje_error=err_msg,
    ))
    db.session.commit()
    return {'dias': dias, 'ok': not had_error, 'error': err_msg}

def run_auto_sync_ausencias(modo='Automático', actor=None, origen_label=None):
    from app.services.leave_service import sync_leaves_from_erp
    if origen_label is None:
        if (modo or '').lower().startswith('hook'):
            origen_label = 'Hook Odoo'
        elif (modo or '').lower().startswith('manual'):
            origen_label = 'Manual (cola sync)'
        else:
            origen_label = 'Programación automática'
    return sync_leaves_from_erp(modo=modo, actor=actor, origen_label=origen_label)


def run_auto_sync_vehiculos(modo='Automático'):
    from app.services.vehicle_sync_service import run_vehiculos_en_vivo
    return run_vehiculos_en_vivo(modo=modo)
