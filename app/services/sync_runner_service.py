"""Ejecución de sync automática por módulo (usado por Celery y «Auto ahora»)."""
import time
from datetime import datetime

from werkzeug.security import generate_password_hash

from app import db
from app.models import Obra, User, Company, SyncLog
from app.sync.dispatcher import get_sync_adapter
from app.utils.timezone_utils import utc_now


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


def _set_odoo_external_id(entity, odoo_id):
    ext_ids = dict(entity.external_ids or {})
    ext_ids['odoo'] = str(odoo_id)
    entity.external_ids = ext_ids
    db.session.add(entity)


def run_auto_sync_obras():
    t0 = time.time()
    ahora = utc_now()
    service = get_sync_adapter()
    diff = service.get_diff_obras()
    nuevas_limpias = [o for o in diff['nuevas'] if not o.get('warn_jefe') and not o.get('warn_encargado')]
    act_limpias = [o for o in diff['actualizadas'] if not o.get('warn_jefe') and not o.get('warn_encargado')]
    errores = (len(diff['nuevas']) - len(nuevas_limpias)) + (len(diff['actualizadas']) - len(act_limpias))

    for obj in nuevas_limpias:
        f_inicio = datetime.strptime(obj['fecha_inicio'], "%Y-%m-%d").date() if obj.get('fecha_inicio') else None
        db.session.add(Obra(
            external_ids={'odoo': str(obj['odoo_id'])},
            codigo=obj['codigo'], nombre=obj['nombre'],
            descripcion=obj.get('cliente', ''), fecha_inicio=f_inicio, estado='Pendiente',
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

    for obj in diff['finalizadas']:
        obra = Obra.query.get(obj['local_id'])
        if obra:
            obra.estado = 'Finalizada'
            obra.fecha_fin = ahora.date()
            obra.fecha_importacion = ahora

    detalle = f"Sync automática obras. {errores} omitida(s) por responsables sin resolver." if errores else "Sync automática obras completada."
    db.session.add(SyncLog(
        fecha=ahora, tipo='Obras', modo='Automático',
        nuevos=len(nuevas_limpias), actualizados=len(act_limpias),
        finalizados=len(diff['finalizadas']), errores=errores,
        detalles=detalle, estado=_log_estado(errores),
        duracion_ms=int((time.time() - t0) * 1000),
    ))
    db.session.commit()
    return {'nuevos': len(nuevas_limpias), 'actualizados': len(act_limpias), 'omitidos': errores}


def run_auto_sync_empleados():
    t0 = time.time()
    ahora = utc_now()
    service = get_sync_adapter()
    diff = service.get_diff_empleados()
    emp_nuevos = diff['nuevos']
    emp_act = [e for e in diff['actualizados'] if not e.get('conflicto')]
    errores = len(diff['actualizados']) - len(emp_act)
    default_company = Company.query.first()
    default_company_id = default_company.id if default_company else None

    for obj in emp_nuevos:
        db.session.add(User(
            external_ids={'odoo': str(obj['odoo_id'])},
            name=obj['name'], lastname=obj['lastname'],
            dni=obj['dni'], email=obj['email'], role=obj['role'],
            categoria_profesional=obj.get('categoria_profesional', 'Sin definir'),
            company_id=default_company_id, active=True, email_verified=True,
            password_hash=generate_password_hash("123456"),
        ))

    for obj in emp_act:
        user = User.query.get(obj['local_id'])
        if user:
            _set_odoo_external_id(user, obj['odoo_id'])
            user.name = obj['name']
            user.lastname = obj['lastname']
            user.role = obj['role']
            user.categoria_profesional = obj.get('categoria_profesional', user.categoria_profesional)

    detalle = f"Sync automática empleados. {errores} omitido(s) por conflictos DNI/email." if errores else "Sync automática empleados completada."
    db.session.add(SyncLog(
        fecha=ahora, tipo='Empleados', modo='Automático',
        nuevos=len(emp_nuevos), actualizados=len(emp_act),
        finalizados=0, errores=errores,
        detalles=detalle, estado=_log_estado(errores),
        duracion_ms=int((time.time() - t0) * 1000),
    ))
    db.session.commit()
    return {'nuevos': len(emp_nuevos), 'actualizados': len(emp_act), 'omitidos': errores}


def run_auto_sync_subcontratas():
    t0 = time.time()
    ahora = utc_now()
    service = get_sync_adapter()
    diff = service.get_diff_subcontratas()
    mapa_empresas = {}

    for obj in diff['empresas']['actualizadas']:
        comp = Company.query.get(obj['local_id'])
        if comp:
            _set_odoo_external_id(comp, obj['odoo_id'])
            comp.nombre = obj['nombre']
            mapa_empresas[obj['odoo_id']] = comp.id

    for obj in diff['empresas']['nuevas']:
        nueva = Company(external_ids={'odoo': str(obj['odoo_id'])}, nombre=obj['nombre'])
        db.session.add(nueva)
        db.session.flush()
        mapa_empresas[obj['odoo_id']] = nueva.id

    for obj in diff['empleados']['actualizados']:
        user = User.query.get(obj['local_id'])
        if user:
            _set_odoo_external_id(user, obj['odoo_id'])
            user.name = obj['name']
            user.lastname = obj['lastname']
            if obj['dni'] and 'SINDNI' not in obj['dni']:
                user.dni = obj['dni']
            user.categoria_profesional = obj.get('categoria_profesional')
            odoo_c_id = obj.get('odoo_company_id')
            if odoo_c_id:
                if odoo_c_id not in mapa_empresas:
                    comp = _company_by_odoo_id(odoo_c_id)
                    if comp:
                        mapa_empresas[odoo_c_id] = comp.id
                if odoo_c_id in mapa_empresas:
                    user.company_id = mapa_empresas[odoo_c_id]

    dnis_en_tx = set()
    for obj in diff['empleados']['nuevos']:
        odoo_c_id = obj.get('odoo_company_id')
        local_comp_id = mapa_empresas.get(odoo_c_id)
        if not local_comp_id and odoo_c_id:
            comp = _company_by_odoo_id(odoo_c_id)
            if comp:
                local_comp_id = comp.id
                mapa_empresas[odoo_c_id] = local_comp_id
        dni = obj['dni']
        if User.query.filter_by(dni=dni).first() or dni in dnis_en_tx:
            dni = f"{dni}-EXT{obj['odoo_id']}"
        dnis_en_tx.add(dni)
        db.session.add(User(
            external_ids={'odoo': str(obj['odoo_id'])},
            name=obj['name'], lastname=obj['lastname'],
            dni=dni, email=obj['email'], role=obj['role'],
            categoria_profesional=obj.get('categoria_profesional'),
            company_id=local_comp_id, active=True, email_verified=True,
            password_hash=generate_password_hash("123456"),
        ))

    tot_n = len(diff['empresas']['nuevas']) + len(diff['empleados']['nuevos'])
    tot_a = len(diff['empresas']['actualizadas']) + len(diff['empleados']['actualizados'])
    db.session.add(SyncLog(
        fecha=ahora, tipo='Subcontratas', modo='Automático',
        nuevos=tot_n, actualizados=tot_a, finalizados=0, errores=0,
        detalles="Sync automática subcontratas completada.",
        estado='ok', duracion_ms=int((time.time() - t0) * 1000),
    ))
    db.session.commit()
    return {'nuevos': tot_n, 'actualizados': tot_a, 'omitidos': 0}


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

def run_auto_sync_ausencias():
    from app.services.leave_service import sync_leaves_from_erp
    return sync_leaves_from_erp()


def run_auto_sync_vehiculos():
    from app.services.vehicle_sync_service import run_vehiculos_en_vivo
    return run_vehiculos_en_vivo(modo='Automático')
