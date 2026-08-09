import logging
from datetime import datetime

from sqlalchemy import text

from app import db
from app.sync.dispatcher import get_sync_adapter
from app.utils.timezone_utils import (
    parse_odoo_datetime,
    utc_now,
    format_time,
    now_local,
    today_local,
)

logger = logging.getLogger(__name__)


def _clean_odoo_note(note):
    if note is False or note is None:
        return None
    stripped = str(note).strip()
    return stripped or None


def _merge_fichaje_notes(existing, new):
    new_clean = _clean_odoo_note(new)
    if not new_clean:
        return _clean_odoo_note(existing)
    existing_clean = _clean_odoo_note(existing)
    if not existing_clean:
        return new_clean
    parts = [p.strip() for p in existing_clean.split(' | ') if p.strip()]
    if new_clean not in parts:
        parts.append(new_clean)
    return ' | '.join(parts)


def _format_fichaje_log_detail(obra_label, check_in_dt, check_out_dt, note=None):
    detail = (
        f"El operario fichó en {obra_label}. "
        f"Entrada: {format_time(check_in_dt) if check_in_dt else '-'} / "
        f"Salida: {format_time(check_out_dt) if check_out_dt else '-'}"
    )
    note_clean = _clean_odoo_note(note)
    if note_clean:
        detail += f" Notas: {note_clean}"
    return detail


def procesar_fichajes_diarios(fecha_str=None):
    """
    Motor central de validación de fichajes.
    Independiente del ERP que use el cliente (Odoo, SAP, etc).
    """
    from app.models import Festivo

    if not fecha_str:
        fecha_str = today_local().strftime('%Y-%m-%d')
    fecha_obj = datetime.strptime(fecha_str, '%Y-%m-%d').date()

    if Festivo.query.filter_by(fecha=fecha_obj).first():
        return

    lock_id = 424242
    if not db.session.execute(text("SELECT pg_try_advisory_lock(:id)"), {'id': lock_id}).scalar():
        logger.warning("Sync fichajes omitido: otra instancia ya está en ejecución.")
        return

    try:
        _procesar_fichajes_diarios_impl(fecha_obj, fecha_str)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    finally:
        try:
            db.session.execute(text("SELECT pg_advisory_unlock(:id)"), {'id': lock_id})
        except Exception:
            pass


def _procesar_fichajes_diarios_impl(fecha_obj, fecha_str):
    from app.models import RegistroFichaje, Asignacion, User, Obra, ConfiguracionGlobal, SystemLog
    from app.services.core_assignment_service import CoreAssignmentService

    try:
        adapter = get_sync_adapter()
        datos_crudos = adapter.get_fichajes_diarios(fecha_str)
    except Exception as e:
        logger.error(f"Error obteniendo fichajes del adaptador: {e}")
        return

    # El libro de eventos se escribe con los apuntes tal cual llegan, antes de
    # fusionarlos por obra. Lo de abajo agrupa y reinterpreta para la auditoría;
    # el libro tiene que guardar el hecho en bruto, no la interpretación.
    from app.services.fichaje_erp_ledger_service import (
        reflejar_sin_romper_la_sincronizacion,
    )
    reflejar_sin_romper_la_sincronizacion(fecha_obj, datos_crudos)

    fichajes_crudos = []
    for d in datos_crudos:
        empleado_id = d.get('empleado_external_id')
        if not empleado_id:
            continue
        obra_id = d.get('obra_external_id')
        fichajes_crudos.append({
            'odoo_user': str(empleado_id),
            'odoo_obra': str(obra_id) if obra_id else None,
            'autor': d.get('autor', 'ERP'),
            'check_in': d.get('check_in'),
            'check_out': d.get('check_out'),
            'note': _clean_odoo_note(d.get('note')),
        })

    fichajes_unicos = {}
    for f in fichajes_crudos:
        key = f"{f['odoo_user']}_{f['odoo_obra']}"
        if key not in fichajes_unicos:
            fichajes_unicos[key] = f
        else:
            if f['check_in'] and (
                not fichajes_unicos[key]['check_in']
                or f['check_in'] < fichajes_unicos[key]['check_in']
            ):
                fichajes_unicos[key]['check_in'] = f['check_in']
            if f['check_out'] and (
                not fichajes_unicos[key]['check_out']
                or f['check_out'] > fichajes_unicos[key]['check_out']
            ):
                fichajes_unicos[key]['check_out'] = f['check_out']
            fichajes_unicos[key]['note'] = _merge_fichaje_notes(
                fichajes_unicos[key].get('note'), f.get('note')
            )

    todas_asig = Asignacion.query.filter_by(fecha=fecha_obj).all()
    from app.services.leave_service import user_has_approved_leave
    for asig in todas_asig:
        registro = RegistroFichaje.query.filter_by(
            user_id=asig.user_id,
            fecha=fecha_obj,
            obra_planificada_id=asig.obra_id,
        ).first()
        if not registro:
            # Ya fichó / resolvió en esa obra (p. ej. Paracaidista aceptado):
            # no sembrar Sin_Registro→Ausencia fantasma.
            ya_en_obra = RegistroFichaje.query.filter(
                RegistroFichaje.user_id == asig.user_id,
                RegistroFichaje.fecha == fecha_obj,
                RegistroFichaje.obra_real_id == asig.obra_id,
            ).first()
            if ya_en_obra:
                if not ya_en_obra.obra_planificada_id:
                    ya_en_obra.obra_planificada_id = asig.obra_id
                continue
            estado_ini = (
                'Exento_Ausencia'
                if user_has_approved_leave(asig.user_id, fecha_obj)
                else 'Sin_Registro'
            )
            db.session.add(RegistroFichaje(
                user_id=asig.user_id,
                fecha=fecha_obj,
                obra_planificada_id=asig.obra_id,
                estado=estado_ini,
                notas_resolucion=(
                    'Exento: ausencia planificada aprobada (Odoo/manual).'
                    if estado_ini == 'Exento_Ausencia' else None
                ),
            ))
            db.session.flush()

    obras_por_usuario_odoo = {}
    for f in fichajes_unicos.values():
        if f['odoo_user'] not in obras_por_usuario_odoo:
            obras_por_usuario_odoo[f['odoo_user']] = []
        if f['odoo_obra']:
            obras_por_usuario_odoo[f['odoo_user']].append(f['odoo_obra'])

    registros_hoy_locales = RegistroFichaje.query.filter_by(fecha=fecha_obj).filter(
        RegistroFichaje.obra_real_id.isnot(None),
        RegistroFichaje.estado != 'Sobreescrito_RRHH',
    ).all()

    for reg_local in registros_hoy_locales:
        u_local = User.query.get(reg_local.user_id)
        o_real = Obra.query.get(reg_local.obra_real_id)

        odoo_user_id = u_local.external_ids.get('odoo') if u_local and u_local.external_ids else None
        odoo_obra_id = o_real.external_ids.get('odoo') if o_real and o_real.external_ids else None

        if not u_local or not odoo_user_id or not o_real or not odoo_obra_id:
            continue

        obras_odoo_del_usuario = obras_por_usuario_odoo.get(str(odoo_user_id), [])

        if str(odoo_obra_id) not in obras_odoo_del_usuario:
            asig_fantasma = Asignacion.query.filter_by(
                user_id=u_local.id, fecha=fecha_obj, obra_id=o_real.id
            ).first()
            if asig_fantasma:
                CoreAssignmentService.desasignar(
                    u_local.id, o_real.id, fecha_obj, 1,
                    "Fichaje Anulado por Odoo",
                    f"Borrada asignación en {o_real.nombre} por falta de registro en Odoo.",
                )

            o_nueva_id = ""
            o_nueva_cod = ""
            o_nueva_nom = ""
            accion = "Borrado en Odoo"

            for f in fichajes_unicos.values():
                if f['odoo_user'] == str(odoo_user_id) and f['odoo_obra']:
                    o_nueva = Obra.query.filter(
                        Obra.external_ids['odoo'].astext == f['odoo_obra']
                    ).first()
                    if o_nueva:
                        o_nueva_id = str(o_nueva.id)
                        o_nueva_cod = str(o_nueva.codigo or '')
                        o_nueva_nom = str(o_nueva.nombre or '')
                        accion = "Modificado de Obra"
                    break

            estado_anterior = reg_local.estado
            datos_string = (
                f"{o_real.id}||{o_real.codigo or ''}||{o_real.nombre}||"
                f"{o_nueva_id}||{o_nueva_cod}||{o_nueva_nom}||{accion}||{estado_anterior}"
            )

            reg_local.estado = 'Sobreescrito_RRHH'
            reg_local.obra_real_id = None
            reg_local.notas_resolucion = datos_string

    db.session.flush()

    conf_primer_fichaje = ConfiguracionGlobal.query.filter_by(clave='aceptar_primer_fichaje').first()
    aceptar_primer_fichaje = conf_primer_fichaje.valor == 'True' if conf_primer_fichaje else True

    for f in fichajes_unicos.values():
        if not f['odoo_obra']:
            continue

        local_user = User.query.filter(
            User.external_ids['odoo'].astext == f['odoo_user']
        ).first()
        local_obra = Obra.query.filter(
            Obra.external_ids['odoo'].astext == f['odoo_obra']
        ).first()

        if not local_user or not local_obra:
            continue

        check_in_dt = parse_odoo_datetime(f.get('check_in'))
        check_out_dt = parse_odoo_datetime(f.get('check_out'))

        plan_exacto = Asignacion.query.filter_by(
            user_id=local_user.id, fecha=fecha_obj, obra_id=local_obra.id
        ).first()

        nuevo_estado = ''
        nuevo_plan_id = None
        crear_asignacion_magica = False

        if plan_exacto:
            nuevo_estado = 'Correcto'
            nuevo_plan_id = local_obra.id
        else:
            # ¿Tenía plan en otra obra hoy? → desviación (Conflicto).
            # Sin plan en todo el día → Paracaidista (o inercia Correcto_Automatico).
            plan_otro_hoy = Asignacion.query.filter(
                Asignacion.user_id == local_user.id,
                Asignacion.fecha == fecha_obj,
                Asignacion.obra_id != local_obra.id,
            ).first()

            ultimo_reg = RegistroFichaje.query.filter(
                RegistroFichaje.user_id == local_user.id,
                RegistroFichaje.fecha < fecha_obj,
                RegistroFichaje.estado.in_([
                    'Correcto', 'Correcto_Automatico',
                    'Resuelto_Movido', 'Resuelto_Asignado', 'Resuelto_Dividido',
                ]),
            ).order_by(RegistroFichaje.fecha.desc()).first()

            ultima_obra_id = ultimo_reg.obra_real_id if ultimo_reg else None

            if plan_otro_hoy:
                # Había cuadrante en otra obra: es desviación, no "sin planificar".
                nuevo_estado = 'Conflicto'
                nuevo_plan_id = plan_otro_hoy.obra_id
                crear_asignacion_magica = False
            elif ultima_obra_id == local_obra.id:
                nuevo_estado = 'Correcto_Automatico'
                nuevo_plan_id = local_obra.id
                crear_asignacion_magica = True
            elif ultima_obra_id is None:
                if aceptar_primer_fichaje:
                    nuevo_estado = 'Correcto_Automatico'
                    nuevo_plan_id = local_obra.id
                    crear_asignacion_magica = True
                else:
                    nuevo_estado = 'Paracaidista'
                    nuevo_plan_id = None
                    crear_asignacion_magica = False
            else:
                nuevo_estado = 'Paracaidista'
                nuevo_plan_id = None
                crear_asignacion_magica = False

        registro_vacio_exacto = RegistroFichaje.query.filter(
            RegistroFichaje.user_id == local_user.id,
            RegistroFichaje.fecha == fecha_obj,
            RegistroFichaje.obra_planificada_id == local_obra.id,
            RegistroFichaje.estado.in_(['Sin_Registro', 'Ausencia']),
        ).first()

        if registro_vacio_exacto:
            if registro_vacio_exacto.estado == 'Ausencia':
                registro_vacio_exacto.estado = 'Retraso'
                registro_vacio_exacto.notas_resolucion = (
                    f"Fichaje recibido después del corte horario. "
                    f"Hora detectada: {format_time(check_in_dt) if check_in_dt else 'N/A'}"
                )
            else:
                registro_vacio_exacto.estado = nuevo_estado

            registro_vacio_exacto.obra_real_id = local_obra.id
            registro_vacio_exacto.check_in = check_in_dt
            registro_vacio_exacto.check_out = check_out_dt
            registro_vacio_exacto.nota_odoo = _merge_fichaje_notes(
                registro_vacio_exacto.nota_odoo, f.get('note')
            )
        else:
            registro_existente = RegistroFichaje.query.filter_by(
                user_id=local_user.id, fecha=fecha_obj, obra_real_id=local_obra.id
            ).first()

            if not registro_existente:
                db.session.add(RegistroFichaje(
                    user_id=local_user.id,
                    fecha=fecha_obj,
                    obra_planificada_id=nuevo_plan_id,
                    obra_real_id=local_obra.id,
                    estado=nuevo_estado,
                    check_in=check_in_dt,
                    check_out=check_out_dt,
                    nota_odoo=f.get('note'),
                ))

                obra_label = CoreAssignmentService.format_obra_label(local_obra)
                db.session.add(SystemLog(
                    timestamp=check_in_dt or utc_now(),
                    category='fichaje_app',
                    action=f"Fichaje físico [{nuevo_estado.replace('_', ' ')}]",
                    detail=_format_fichaje_log_detail(
                        obra_label, check_in_dt, check_out_dt, f.get('note')
                    ),
                    target_user_id=local_user.id,
                    target_date=fecha_obj,
                ))
            else:
                if not registro_existente.estado.startswith('Resuelto'):
                    registro_existente.estado = nuevo_estado
                    registro_existente.obra_planificada_id = nuevo_plan_id
                registro_existente.check_in = check_in_dt
                registro_existente.check_out = check_out_dt
                registro_existente.nota_odoo = _merge_fichaje_notes(
                    registro_existente.nota_odoo, f.get('note')
                )

        if crear_asignacion_magica:
            existe_asig = Asignacion.query.filter_by(
                user_id=local_user.id, fecha=fecha_obj, obra_id=local_obra.id
            ).first()
            if not existe_asig:
                CoreAssignmentService.asignar(
                    local_user.id, local_obra.id, fecha_obj, None,
                    "Auto-asignación por Fichaje Físico",
                )

    if fecha_obj == today_local():
        conf_hora = ConfiguracionGlobal.query.filter_by(clave='hora_limite_entrada').first()
        hora_str = conf_hora.valor if conf_hora else "08:30"

        try:
            hora_corte = datetime.strptime(hora_str, "%H:%M").time()
        except ValueError:
            hora_corte = datetime.strptime("08:30", "%H:%M").time()

        ahora_local = now_local()

        if ahora_local.time() >= hora_corte:
            from app.services.leave_service import user_has_approved_leave
            from app.services.fichaje_estado_service import FICHAJE_OK

            candidatos = RegistroFichaje.query.filter(
                RegistroFichaje.fecha == fecha_obj,
                RegistroFichaje.estado.in_(['Sin_Registro', 'Ausencia']),
            ).all()
            for reg in candidatos:
                if user_has_approved_leave(reg.user_id, fecha_obj):
                    # Asignado pero de vacaciones/baja/permiso: no marcar ausencia
                    reg.estado = 'Exento_Ausencia'
                    reg.notas_resolucion = 'Cubierto por ausencia planificada (no cuenta como ausencia).'
                    continue
                if reg.estado == 'Sin_Registro':
                    # No inventar Ausencia si el día ya tiene fichaje/resolución real
                    hermano_ok = RegistroFichaje.query.filter(
                        RegistroFichaje.user_id == reg.user_id,
                        RegistroFichaje.fecha == fecha_obj,
                        RegistroFichaje.id != reg.id,
                    ).filter(
                        db.or_(
                            RegistroFichaje.obra_real_id.isnot(None),
                            RegistroFichaje.check_in.isnot(None),
                            RegistroFichaje.estado.like('Resuelto%'),
                            RegistroFichaje.estado.in_(
                                list(FICHAJE_OK) + ['Paracaidista', 'Conflicto', 'Cerrado_Multiobra']
                            ),
                        )
                    ).first()
                    if hermano_ok:
                        reg.estado = 'Cerrado_Multiobra'
                        reg.notas_resolucion = (
                            'Cerrado automáticamente: ya hay fichaje o resolución '
                            'el mismo día.'
                        )
                        continue
                    reg.estado = 'Ausencia'
                    reg.notas_resolucion = 'Generada automáticamente tras superar la hora de corte.'
        else:
            ausencias_tempranas = RegistroFichaje.query.filter_by(
                fecha=fecha_obj, estado='Ausencia'
            ).all()
            for reg in ausencias_tempranas:
                if not reg.check_in:
                    reg.estado = 'Sin_Registro'
                    reg.notas_resolucion = None

        # Multi-obra: si el día ya tiene fichaje/resolución real, las semillas
        # Sin_Registro / Ausencia dejan de ensuciar la pelotita.
        from app.services.fichaje_estado_service import (
            FICHAJE_INTERVENCION,
            FICHAJE_OK,
            FICHAJE_ROJO,
        )
        semillas = RegistroFichaje.query.filter(
            RegistroFichaje.fecha == fecha_obj,
            RegistroFichaje.estado.in_(['Sin_Registro', 'Ausencia']),
        ).all()
        if semillas:
            by_user = {}
            for s in semillas:
                by_user.setdefault(s.user_id, []).append(s)
            for uid, seeds in by_user.items():
                hermanos = RegistroFichaje.query.filter(
                    RegistroFichaje.user_id == uid,
                    RegistroFichaje.fecha == fecha_obj,
                    RegistroFichaje.id.notin_([s.id for s in seeds]),
                ).all()
                if any(
                    (h.estado in FICHAJE_OK)
                    or (h.estado in FICHAJE_INTERVENCION)
                    or (h.estado in FICHAJE_ROJO)
                    or (h.estado or '').startswith('Resuelto')
                    for h in hermanos
                ):
                    for s in seeds:
                        s.estado = 'Cerrado_Multiobra'
                        s.notas_resolucion = (
                            'Cerrado automáticamente: el trabajador fichó u '
                            'obtuvo resolución en otra obra el mismo día.'
                        )