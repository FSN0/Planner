# app/services/solicitud_service.py
from datetime import datetime, timedelta, date
import json
from app import db
from app.utils.timezone_utils import utc_now, today_local
from app.models import Solicitud, Asignacion, User, Festivo
from app.services.email_service import notificar_nueva_solicitud

_AUTO_COMENTARIO_MARKERS = (
    'Petición automática',
    'Creado desde Planificador',
    'Rango ampliado',
)


def _dates_to_str(dates):
    result = []
    for d in dates:
        if isinstance(d, str):
            result.append(d)
        elif isinstance(d, date):
            result.append(d.strftime('%Y-%m-%d'))
    return sorted(set(result))


def build_comentarios_config(dates, mode='selected'):
    dates_str = _dates_to_str(dates)
    return json.dumps({
        'mode': mode,
        'dates': dates_str,
        'original_dates': dates_str,
    })


def merge_comentarios_dates(existing_comentarios, new_dates, mode='selected'):
    dates_str = _dates_to_str(new_dates)
    try:
        if existing_comentarios and existing_comentarios.strip().startswith('{'):
            config = json.loads(existing_comentarios)
        else:
            config = {}
    except Exception:
        config = {}

    merged = sorted(set(config.get('dates', []) + dates_str))
    config['mode'] = config.get('mode', mode)
    config['dates'] = merged
    if not config.get('original_dates'):
        config['original_dates'] = merged
    return json.dumps(config)


def merge_notas(existing_notas, new_notas):
    new_notas = (new_notas or '').strip()
    if not new_notas:
        return existing_notas
    existing = (existing_notas or '').strip()
    if not existing:
        return new_notas
    if new_notas in existing:
        return existing
    return f"{existing}\n---\n{new_notas}"


def log_nueva_solicitud(solicitud):
    """Registra en SystemLog la creación de una solicitud (solo altas nuevas)."""
    from app.utils import register_log
    from app.models import Obra

    tipo = (solicitud.tipo or '').upper()
    accion = (getattr(solicitud, 'accion', None) or 'ASIGNAR').upper()
    if tipo == 'GENERICA':
        action = 'Nueva solicitud GENERICA'
    elif accion == 'DESASIGNAR':
        action = 'Nueva solicitud DESASIGNAR'
    else:
        action = 'Nueva solicitud ASIGNAR'

    obra = getattr(solicitud, 'obra', None)
    if obra is None and solicitud.obra_id:
        obra = Obra.query.get(solicitud.obra_id)
    if obra:
        obra_txt = f"{obra.codigo or ''} {obra.nombre}".strip()
    else:
        obra_txt = f"obra #{solicitud.obra_id}"

    emp_txt = None
    if solicitud.empleado_id:
        emp = getattr(solicitud, 'empleado', None)
        if emp is None:
            emp = User.query.get(solicitud.empleado_id)
        if emp:
            emp_txt = f"{emp.name} {emp.lastname}".strip()

    requester = getattr(solicitud, 'requested_by', None)
    if requester is None and solicitud.requested_by_id:
        requester = User.query.get(solicitud.requested_by_id)
    if requester:
        req_txt = f"{requester.name} {requester.lastname}".strip()
    else:
        req_txt = f"user #{solicitud.requested_by_id}"

    fi = solicitud.fecha_inicio.strftime('%Y-%m-%d') if solicitud.fecha_inicio else '?'
    ff = solicitud.fecha_fin.strftime('%Y-%m-%d') if solicitud.fecha_fin else '?'

    parts = [f"Obra: {obra_txt}"]
    if emp_txt:
        parts.append(f"Empleado: {emp_txt}")
    parts.append(f"Fechas: {fi} → {ff}")
    parts.append(f"Solicitante: {req_txt}")

    register_log(
        user_id=solicitud.requested_by_id,
        category='solicitud',
        action=action,
        detail=' | '.join(parts),
        target_user_id=solicitud.empleado_id if tipo == 'CONCRETA' else None,
    )


def get_solicitud_notas(solicitud):
    if getattr(solicitud, 'notas', None):
        text = solicitud.notas.strip()
        if text:
            return text

    comentarios = solicitud.comentarios
    if not comentarios:
        return None

    if comentarios.strip().startswith('{'):
        try:
            data = json.loads(comentarios)
            legacy = (data.get('mensaje_original') or '').strip()
            return legacy or None
        except Exception:
            return None

    if any(marker in comentarios for marker in _AUTO_COMENTARIO_MARKERS):
        return None
    text = comentarios.strip()
    return text or None

def update_solicitudes_for_assignment(obra_id, worker_id, fecha, resolved_by_id=None):
    from datetime import date
    if fecha < today_local():
        return
    
    worker_id = int(worker_id)
    if obra_id:
        obra_id = int(obra_id)
        
    worker = User.query.get(worker_id)
    if not worker:
        return

    qs = Solicitud.query.filter(
        Solicitud.obra_id == obra_id,
        Solicitud.estado.in_(["PENDIENTE", "EN_PROCESO"]),
        Solicitud.fecha_inicio <= fecha,
        Solicitud.fecha_fin >= fecha,
    ).all()

    for sol in qs:
        if sol.tipo == "CONCRETA" and sol.empleado_id != worker_id:
            continue

        estado_previo = sol.estado
        _recalculate_solicitud_coverage(sol, resolved_by_id)

        if estado_previo != 'CUMPLIDA' and sol.estado == 'CUMPLIDA':
            from app.services.email_service import notificar_resolucion_solicitud
            admin_user = User.query.get(resolved_by_id) if resolved_by_id else None
            admin_name = f"{admin_user.name} {admin_user.lastname}" if admin_user else "Sistema Automático"
            notificar_resolucion_solicitud(sol, admin_name, worker_id=worker_id)

def _recalculate_solicitud_coverage(solicitud, resolved_by_id=None):
    start = solicitud.fecha_inicio
    end = solicitud.fecha_fin
    valid_dates = []

    explicit_dates = []
    if solicitud.comentarios:
        try:
            if not solicitud.comentarios.strip().startswith('{'):
                data = {}
            else:
                data = json.loads(solicitud.comentarios)
            
            fechas_base = data.get('original_dates') or data.get('dates', [])
            if fechas_base:
                explicit_dates = [datetime.strptime(d, '%Y-%m-%d').date() for d in fechas_base]
        except Exception:
            pass

    if explicit_dates:
        valid_dates = [d for d in explicit_dates if start <= d <= end]

    if not valid_dates:
        festivos = Festivo.query.filter(Festivo.fecha >= start, Festivo.fecha <= end).all()
        fechas_festivas = [f.fecha for f in festivos]
        curr = start
        while curr <= end:
            if curr.weekday() < 5 and curr not in fechas_festivas:
                valid_dates.append(curr)
            curr += timedelta(days=1)
            
        if not valid_dates:
            valid_dates = [start + timedelta(days=i) for i in range((end - start).days + 1)]

    total_validos = len(valid_dates)
    prev_estado = solicitud.estado

    if solicitud.tipo == "GENERICA":
        requested = solicitud.cantidad_solicitada or 1

        # FIX DEFINITIVO: Ahora el motor es puro. No roba asignaciones huérfanas o fantasmas.
        # SÓLO cuenta aquellas que tú le inyectas directamente desde los endpoints, 
        # que siempre vendrán atadas con su solicitud.id.
        asignaciones_vinculadas = Asignacion.query.filter(
            Asignacion.obra_id == solicitud.obra_id,
            Asignacion.solicitud_id == solicitud.id,
            Asignacion.fecha.in_(valid_dates)
        ).all()

        counts_by_day = {d: 0 for d in valid_dates}
        for a in asignaciones_vinculadas:
            counts_by_day[a.fecha] += 1

        min_coverage = min(counts_by_day.values()) if counts_by_day else 0
        solicitud.cantidad_cubierta = min_coverage
        total_assignments_count = sum(counts_by_day.values())

        # --- AUTO-MANTENIMIENTO DEL FRONTEND (Días Verdes) ---
        dias_incompletos = [d.strftime("%Y-%m-%d") for d, c in counts_by_day.items() if c < requested]
        try:
            if not solicitud.comentarios or not solicitud.comentarios.strip().startswith('{'):
                config = {}
                plain = (solicitud.comentarios or '').strip()
                if plain and not any(marker in plain for marker in _AUTO_COMENTARIO_MARKERS):
                    config['mensaje_original'] = plain
            else:
                config = json.loads(solicitud.comentarios)
                
            if 'original_dates' not in config:
                config['original_dates'] = config.get('dates', [])
            if not config['original_dates'] and valid_dates:
                config['original_dates'] = [d.strftime("%Y-%m-%d") for d in valid_dates]
            
            config['mode'] = 'selected'
            config['dates'] = dias_incompletos
            solicitud.comentarios = json.dumps(config)
        except Exception:
            pass
        # ----------------------------------------------------

        if min_coverage >= requested:
            solicitud.estado = "CUMPLIDA"
            solicitud.resolved_at = utc_now()
            if resolved_by_id: solicitud.resolved_by_id = resolved_by_id
        elif total_assignments_count > 0:
            solicitud.estado = "EN_PROCESO"
            solicitud.resolved_at = None
        else:
            solicitud.estado = "PENDIENTE"
            solicitud.resolved_at = None

    elif solicitud.tipo == "CONCRETA":
        accion = getattr(solicitud, 'accion', 'ASIGNAR')
        
        if accion == 'DESASIGNAR' and prev_estado == 'CUMPLIDA':
            return
        
        asignaciones_reales = Asignacion.query.filter(
            Asignacion.obra_id == solicitud.obra_id,
            Asignacion.user_id == solicitud.empleado_id,
            Asignacion.fecha.in_(valid_dates)
        ).all()
        
        asignados_dias = [a.fecha for a in asignaciones_reales]
        cobertura_count = len(set(asignados_dias))
        
        is_fulfilled = False
        is_in_process = False

        if accion == 'DESASIGNAR':
            is_fulfilled = (cobertura_count == 0)
            is_in_process = (cobertura_count > 0 and cobertura_count < total_validos)
        else:
            is_fulfilled = (cobertura_count == total_validos and total_validos > 0)
            is_in_process = (cobertura_count > 0 and cobertura_count < total_validos)

        if is_fulfilled:
            solicitud.estado = "CUMPLIDA"
            solicitud.cantidad_cubierta = solicitud.cantidad_solicitada
            solicitud.resolved_at = utc_now()
            if resolved_by_id:
                solicitud.resolved_by_id = resolved_by_id
        elif is_in_process:
            solicitud.estado = "EN_PROCESO"
        else:
            solicitud.estado = "PENDIENTE"
            solicitud.cantidad_cubierta = 0
            solicitud.resolved_at = None

    db.session.add(solicitud)

class SolicitudService:
    @staticmethod
    def create_solicitud_generica(solicitante_id, obra_id, fecha_inicio, fecha_fin, cantidad, perfil, notas=None, fechas_explicitas=None):
        solicitante = User.query.get(solicitante_id)
        fechas = fechas_explicitas or [fecha_inicio + timedelta(days=i) for i in range((fecha_fin - fecha_inicio).days + 1)]
        nueva_solicitud = Solicitud(
            requested_by_id=solicitante_id,
            obra_id=obra_id,
            tipo="GENERICA",
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            cantidad_solicitada=cantidad,
            perfil_categoria=perfil,
            comentarios=build_comentarios_config(fechas),
            notas=(notas or '').strip() or None,
            estado="PENDIENTE"
        )
        db.session.add(nueva_solicitud)
        db.session.commit()
        log_nueva_solicitud(nueva_solicitud)
        notificar_nueva_solicitud(nueva_solicitud, solicitante.name)
        return nueva_solicitud

    @staticmethod
    def create_or_merge_solicitud_baja(jefe_id, obra_id, empleado_id, date_objs, notas=None):
        if not date_objs:
            return None, "none"

        # Solo tiene sentido pedir baja de días en los que el operario está asignado.
        fechas_pedidas = []
        for d in date_objs:
            if isinstance(d, str):
                d = datetime.strptime(d, '%Y-%m-%d').date()
            fechas_pedidas.append(d)
        fechas_pedidas = sorted(set(fechas_pedidas))

        asignados = {
            a.fecha
            for a in Asignacion.query.filter(
                Asignacion.obra_id == obra_id,
                Asignacion.user_id == empleado_id,
                Asignacion.fecha.in_(fechas_pedidas),
            ).all()
        }
        date_objs = [d for d in fechas_pedidas if d in asignados]
        if not date_objs:
            return None, "none"

        start_date = min(date_objs)
        end_date = max(date_objs)
        dates_str = [d.strftime('%Y-%m-%d') for d in date_objs]

        open_bajas = Solicitud.query.filter_by(
            tipo='CONCRETA', accion='DESASIGNAR', obra_id=obra_id, empleado_id=empleado_id
        ).filter(Solicitud.estado.in_(['PENDIENTE', 'EN_PROCESO'])).all()

        for baja in open_bajas:
            if (baja.fecha_inicio - timedelta(days=1)) <= end_date and (baja.fecha_fin + timedelta(days=1)) >= start_date:
                baja.fecha_inicio = min(baja.fecha_inicio, start_date)
                baja.fecha_fin = max(baja.fecha_fin, end_date)
                baja.comentarios = merge_comentarios_dates(baja.comentarios, dates_str)
                baja.notas = merge_notas(baja.notas, notas)
                db.session.commit()
                return baja, "merged"

        sol_baja = Solicitud(
            tipo='CONCRETA', accion='DESASIGNAR', obra_id=obra_id,
            requested_by_id=jefe_id, empleado_id=empleado_id,
            fecha_inicio=start_date, fecha_fin=end_date,
            cantidad_solicitada=1, estado='PENDIENTE',
            comentarios=build_comentarios_config(dates_str),
            notas=(notas or '').strip() or None,
        )
        db.session.add(sol_baja)
        db.session.commit()
        log_nueva_solicitud(sol_baja)

        jefe = User.query.get(jefe_id)
        notificar_nueva_solicitud(sol_baja, jefe.name if jefe else 'Sistema')
        return sol_baja, "new"
    
def _parse_desasignacion_config(solicitud):
    mode = 'all_obra'
    dates_to_remove = []
    if solicitud.comentarios and '{' in solicitud.comentarios:
        try:
            config = json.loads(solicitud.comentarios)
            mode = config.get('mode', 'all_obra')
            dates_to_remove = config.get('dates', []) or []
        except Exception:
            pass
    return mode, dates_to_remove


def _collect_desasignacion_asignaciones(solicitud):
    """Asignaciones a eliminar según mode de la solicitud de baja."""
    mode, dates_to_remove = _parse_desasignacion_config(solicitud)
    asigs = []

    if mode == 'selected' and dates_to_remove:
        for d_str in dates_to_remove:
            try:
                d_obj = datetime.strptime(d_str, '%Y-%m-%d').date()
            except ValueError:
                continue
            a = Asignacion.query.filter_by(
                user_id=solicitud.empleado_id,
                obra_id=solicitud.obra_id,
                fecha=d_obj,
            ).first()
            if a:
                asigs.append(a)
    elif mode == 'auto_range':
        asigs = Asignacion.query.filter(
            Asignacion.user_id == solicitud.empleado_id,
            Asignacion.obra_id == solicitud.obra_id,
            Asignacion.fecha >= solicitud.fecha_inicio,
            Asignacion.fecha <= solicitud.fecha_fin,
        ).all()
    else:  # all_obra
        start_del = solicitud.fecha_inicio if solicitud.fecha_inicio else today_local()
        asigs = Asignacion.query.filter(
            Asignacion.user_id == solicitud.empleado_id,
            Asignacion.obra_id == solicitud.obra_id,
            Asignacion.fecha >= start_del,
        ).all()

    return asigs


def resolver_solicitud_admin(solicitud, accion, user_actor, target_obra_id=None):
    from app.services.assignment_service import process_assignment_action
    from app.services.email_service import notificar_resolucion_solicitud
    from app.services.core_assignment_service import CoreAssignmentService

    if accion in ('aceptar_concreta', 'aceptar_concreta_traslado'):
        if not solicitud.empleado_id:
            raise ValueError("Error: Solicitud concreta sin empleado asignado.")

        tipo_accion = getattr(solicitud, 'accion', 'ASIGNAR')

        if accion == 'aceptar_concreta_traslado':
            if tipo_accion != 'DESASIGNAR':
                raise ValueError("El traslado solo aplica a solicitudes de desasignación.")
            if not target_obra_id:
                raise ValueError("Debes indicar la obra de destino.")
            target_obra_id = int(target_obra_id)
            if int(target_obra_id) == int(solicitud.obra_id):
                raise ValueError("La obra de destino debe ser distinta a la de origen.")

            asigs = _collect_desasignacion_asignaciones(solicitud)
            if not asigs:
                raise ValueError("No hay asignaciones que trasladar en el periodo solicitado.")

            fechas = sorted({a.fecha for a in asigs})
            for a in asigs:
                CoreAssignmentService.desasignar(
                    a.user_id, a.obra_id, a.fecha, user_actor.id,
                    "Traslado desde solicitud de baja",
                    detalle_extra=f"Origen obra {solicitud.obra_id} → destino {target_obra_id}",
                    registrar_log=False,
                )
            if fechas:
                CoreAssignmentService.registrar_log_rango(
                    solicitud.empleado_id, solicitud.obra_id,
                    fechas[0], fechas[-1], len(fechas),
                    user_actor.id, "Traslado desde solicitud de baja", False,
                    detalle_extra=f"Origen obra {solicitud.obra_id} → destino {target_obra_id}",
                )

            result = process_assignment_action(
                actor_user=user_actor,
                worker_id=solicitud.empleado_id,
                target_obra_id=target_obra_id,
                date_list=fechas,
                overwrite=True,
            )
            if not result.get('success'):
                raise ValueError(
                    f"Desasignado del origen, pero fallo al asignar destino: {result.get('message')}"
                )

            mensaje = (
                f"Traslado completado: {len(fechas)} día(s) de la obra origen "
                f"a la obra {target_obra_id}."
            )

        elif tipo_accion == 'DESASIGNAR':
            asigs = _collect_desasignacion_asignaciones(solicitud)
            count = 0
            fechas = []
            for a in asigs:
                borrado = CoreAssignmentService.desasignar(
                    a.user_id, a.obra_id, a.fecha, user_actor.id,
                    "Aprobación de Solicitud de Baja",
                    registrar_log=False,
                )
                if borrado:
                    count += 1
                    fechas.append(a.fecha)
            if count and fechas:
                fechas = sorted(set(fechas))
                CoreAssignmentService.registrar_log_rango(
                    solicitud.empleado_id, solicitud.obra_id,
                    fechas[0], fechas[-1], count,
                    user_actor.id, "Aprobación de Solicitud de Baja", False,
                )
            mensaje = f"Devolución aprobada. Se han eliminado {count} asignaciones."

        else:
            from app.models import Festivo
            festivos = {
                f.fecha for f in Festivo.query.filter(
                    Festivo.fecha >= solicitud.fecha_inicio,
                    Festivo.fecha <= solicitud.fecha_fin,
                ).all()
            }
            dias = []
            curr = solicitud.fecha_inicio
            while curr <= solicitud.fecha_fin:
                if curr.weekday() < 5 and curr not in festivos:
                    dias.append(curr)
                curr += timedelta(days=1)
            if not dias:
                raise ValueError(
                    "El rango de la solicitud no contiene días laborables válidos."
                )

            result = process_assignment_action(
                actor_user=user_actor, worker_id=solicitud.empleado_id,
                target_obra_id=solicitud.obra_id, date_list=dias, overwrite=True
            )

            if not result.get('success'):
                raise ValueError(f"Error al asignar: {result.get('message')}")

            mensaje = "Solicitud aceptada y trabajador asignado."

        solicitud.estado = 'CUMPLIDA'
        solicitud.cantidad_cubierta = solicitud.cantidad_solicitada
        solicitud.resolved_at = utc_now()
        solicitud.resolved_by_id = user_actor.id
        db.session.commit()
        notificar_resolucion_solicitud(solicitud, user_actor.name)
        return mensaje

    elif accion == 'denegar':
        solicitud.estado = 'DENEGADA'
        solicitud.resolved_at = utc_now()
        solicitud.resolved_by_id = user_actor.id
        db.session.commit()
        notificar_resolucion_solicitud(solicitud, user_actor.name)
        return "Solicitud denegada."

    elif accion == 'reabrir':
        solicitud.estado = 'PENDIENTE'
        solicitud.resolved_at = None
        solicitud.resolved_by_id = None
        db.session.commit()
        return "Solicitud reabierta."
    else:
        raise ValueError("Acción no reconocida.")
