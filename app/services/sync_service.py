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
    if new_clean in existing_clean:
        return existing_clean
    return f"{existing_clean}\n{new_clean}"


def _odoo_metric_value(raw):
    if raw in (None, False, ''):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _merge_odoo_metric(existing, new):
    new_v = _odoo_metric_value(new)
    if new_v is None:
        return _odoo_metric_value(existing)
    existing_v = _odoo_metric_value(existing)
    if existing_v is None:
        return new_v
    return existing_v + new_v


def _merge_estado_odoo(existing, new):
    """Al fusionar varios fichajes del mismo día/obra, gana el estado más avanzado."""
    from app.services.compliance_rules import estado_fichaje_agregado
    return estado_fichaje_agregado([existing, new])


def _apply_odoo_metrics(registro, fichaje):
    for key in ('odoo_ud', 'odoo_mod', 'odoo_total_hh', 'odoo_moe'):
        value = _odoo_metric_value(fichaje.get(key))
        if value is not None:
            setattr(registro, key, value)
    if 'estado_odoo' in fichaje:
        registro.estado_odoo = fichaje.get('estado_odoo') or None


def _format_fichaje_log_detail(
    obra_label,
    check_in_dt,
    check_out_dt,
    note=None,
    obra_plan_label=None,
    estado=None,
):
    if estado == 'Conflicto' and obra_plan_label and obra_plan_label != obra_label:
        intro = (
            f"El operario fichó en {obra_label} "
            f"(tenía planificado en {obra_plan_label})."
        )
    elif estado == 'Paracaidista':
        intro = f"El operario fichó en {obra_label} sin planificación en esa obra."
    elif estado == 'Cambio_Tajo' and obra_plan_label and obra_plan_label != obra_label:
        intro = (
            f"El operario cambió de tajo: fichó en {obra_label} "
            f"(casa anterior: {obra_plan_label})."
        )
    else:
        intro = f"El operario fichó en {obra_label}."
    detail = (
        f"{intro} "
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

    Devuelve True si procesó; False si otra instancia ya tenía el candado
    (no marcar sync como hecha en ese caso).
    """
    from app.models import Festivo

    if not fecha_str:
        fecha_str = today_local().strftime('%Y-%m-%d')
    fecha_obj = datetime.strptime(fecha_str, '%Y-%m-%d').date()

    if Festivo.query.filter_by(fecha=fecha_obj).first():
        return True

    # Candado por tenant (schema) y transacción: se libera solo con commit/rollback.
    # Antes era pg_advisory_lock(424242) global → un tenant bloqueaba a todos y,
    # si la sesión moría sin unlock, el tick verde mentía (sync omitida).
    got_lock = db.session.execute(
        text(
            "SELECT pg_try_advisory_xact_lock("
            "hashtext(current_schema()::text), :k)"
        ),
        {'k': 424242},
    ).scalar()
    if not got_lock:
        schema = db.session.execute(text('SELECT current_schema()')).scalar()
        logger.warning(
            "Sync fichajes omitido (%s): otra instancia ya está en ejecución.",
            schema or '?',
        )
        return False

    try:
        _procesar_fichajes_diarios_impl(fecha_obj, fecha_str)
        db.session.commit()
        return True
    except Exception:
        db.session.rollback()
        raise


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
            'odoo_ud': d.get('odoo_ud'),
            'odoo_mod': d.get('odoo_mod'),
            'odoo_total_hh': d.get('odoo_total_hh'),
            'odoo_moe': d.get('odoo_moe'),
            'estado_odoo': d.get('estado_odoo'),
            'origen_modelo': d.get('origen_modelo'),
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
            for metric_key in ('odoo_ud', 'odoo_mod', 'odoo_total_hh', 'odoo_moe'):
                fichajes_unicos[key][metric_key] = _merge_odoo_metric(
                    fichajes_unicos[key].get(metric_key), f.get(metric_key)
                )
            fichajes_unicos[key]['estado_odoo'] = _merge_estado_odoo(
                fichajes_unicos[key].get('estado_odoo'), f.get('estado_odoo')
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

    # Inercia (casa) NO siembra Sin_Registro/Ausencia: solo clasifica fichajes
    # reales. Sin asignación firme ese día → no se espera a nadie ahí.

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

        from app.services.personal_conciliation_service import odoo_ids_for_user
        odoo_ids_usuario = odoo_ids_for_user(u_local) or [str(odoo_user_id)]
        obras_odoo_del_usuario = []
        for oid_u in odoo_ids_usuario:
            obras_odoo_del_usuario.extend(obras_por_usuario_odoo.get(str(oid_u), []))

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
                if f['odoo_user'] in {str(x) for x in odoo_ids_usuario} and f['odoo_obra']:
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

    desvios_a_notificar = []

    for f in fichajes_unicos.values():
        if not f['odoo_obra']:
            continue

        from app.services.personal_conciliation_service import find_user_by_any_odoo
        local_user = find_user_by_any_odoo(f['odoo_user'])
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
        otras_plan_ids = []

        if plan_exacto:
            nuevo_estado = 'Correcto'
            nuevo_plan_id = local_obra.id
        else:
            from app.services.inercia_service import (
                aceptar_primer_fichaje as _aceptar_primer,
                casa_en_fecha,
                clasificar_entrada_fichaje,
            )
            otras_hoy = Asignacion.query.filter(
                Asignacion.user_id == local_user.id,
                Asignacion.fecha == fecha_obj,
                Asignacion.obra_id != local_obra.id,
            ).all()
            casa_id = None
            if not otras_hoy:
                casa_id = casa_en_fecha(local_user.id, fecha_obj)
            clasif = clasificar_entrada_fichaje(
                obra_fichada_id=local_obra.id,
                planificado_en_obra_fichada=False,
                otras_obras_planificadas_ids=[a.obra_id for a in otras_hoy],
                casa_obra_id=casa_id,
                aceptar_primer_fichaje=_aceptar_primer(),
            )
            nuevo_estado = clasif.estado
            nuevo_plan_id = clasif.obra_planificada_id
            crear_asignacion_magica = clasif.materializar
            otras_plan_ids = [a.obra_id for a in otras_hoy]

        registro_vacio_exacto = RegistroFichaje.query.filter(
            RegistroFichaje.user_id == local_user.id,
            RegistroFichaje.fecha == fecha_obj,
            RegistroFichaje.obra_planificada_id == local_obra.id,
            RegistroFichaje.estado.in_(['Sin_Registro', 'Ausencia', 'Falta']),
        ).first()

        if nuevo_estado == 'Conflicto' and otras_plan_ids:
            from app.services.desvio_fichaje_service import materializar_conflictos_entrada
            _, a_notif = materializar_conflictos_entrada(
                user_id=local_user.id,
                fecha=fecha_obj,
                obra_real_id=local_obra.id,
                obras_plan_ids=otras_plan_ids,
                check_in=check_in_dt,
                check_out=check_out_dt,
                nota_odoo=f.get('note'),
            )
            desvios_a_notificar.extend(a_notif)
            for reg in a_notif:
                _apply_odoo_metrics(reg, f)
            continue

        if plan_exacto:
            from app.services.desvio_fichaje_service import resolver_plan_cumplido_por_fichaje
            resolver_plan_cumplido_por_fichaje(
                local_user.id, fecha_obj, local_obra.id, check_in=check_in_dt,
            )

        if registro_vacio_exacto:
            if registro_vacio_exacto.estado in ('Ausencia', 'Falta'):
                registro_vacio_exacto.estado = 'Retraso'
                registro_vacio_exacto.notas_resolucion = (
                    f"Fichaje recibido después del cierre del día. "
                    f"Hora detectada: {format_time(check_in_dt) if check_in_dt else 'N/A'}"
                )
            else:
                prev = registro_vacio_exacto.estado
                registro_vacio_exacto.estado = nuevo_estado
                if nuevo_estado == 'Conflicto' and prev != 'Conflicto':
                    desvios_a_notificar.append(registro_vacio_exacto)

            registro_vacio_exacto.obra_real_id = local_obra.id
            registro_vacio_exacto.check_in = check_in_dt
            registro_vacio_exacto.check_out = check_out_dt
            registro_vacio_exacto.nota_odoo = _merge_fichaje_notes(
                registro_vacio_exacto.nota_odoo, f.get('note')
            )
            _apply_odoo_metrics(registro_vacio_exacto, f)
        else:
            registro_existente = RegistroFichaje.query.filter_by(
                user_id=local_user.id, fecha=fecha_obj, obra_real_id=local_obra.id
            ).first()

            if not registro_existente:
                nuevo_reg = RegistroFichaje(
                    user_id=local_user.id,
                    fecha=fecha_obj,
                    obra_planificada_id=nuevo_plan_id,
                    obra_real_id=local_obra.id,
                    estado=nuevo_estado,
                    check_in=check_in_dt,
                    check_out=check_out_dt,
                    nota_odoo=f.get('note'),
                    odoo_ud=_odoo_metric_value(f.get('odoo_ud')),
                    odoo_mod=_odoo_metric_value(f.get('odoo_mod')),
                    odoo_total_hh=_odoo_metric_value(f.get('odoo_total_hh')),
                    odoo_moe=_odoo_metric_value(f.get('odoo_moe')),
                    estado_odoo=f.get('estado_odoo') or None,
                )
                db.session.add(nuevo_reg)
                _apply_odoo_metrics(nuevo_reg, f)
                if nuevo_estado == 'Conflicto':
                    desvios_a_notificar.append(nuevo_reg)

                obra_label = CoreAssignmentService.format_obra_label(local_obra)
                obra_plan_label = None
                if nuevo_plan_id and nuevo_plan_id != local_obra.id:
                    obra_plan = Obra.query.get(nuevo_plan_id)
                    if obra_plan:
                        obra_plan_label = CoreAssignmentService.format_obra_label(obra_plan)
                db.session.add(SystemLog(
                    timestamp=check_in_dt or utc_now(),
                    category='fichaje_app',
                    action=f"Fichaje físico [{nuevo_estado.replace('_', ' ')}]",
                    detail=_format_fichaje_log_detail(
                        obra_label,
                        check_in_dt,
                        check_out_dt,
                        f.get('note'),
                        obra_plan_label=obra_plan_label,
                        estado=nuevo_estado,
                    ),
                    target_user_id=local_user.id,
                    target_date=fecha_obj,
                ))
            else:
                prev_estado = registro_existente.estado
                if not registro_existente.estado.startswith('Resuelto') and registro_existente.estado != 'Falta':
                    registro_existente.estado = nuevo_estado
                    registro_existente.obra_planificada_id = nuevo_plan_id
                    if nuevo_estado == 'Conflicto' and prev_estado != 'Conflicto':
                        registro_existente.desvio_ack_plan_at = None
                        registro_existente.desvio_ack_plan_by_id = None
                        registro_existente.desvio_ack_real_at = None
                        registro_existente.desvio_ack_real_by_id = None
                        desvios_a_notificar.append(registro_existente)
                registro_existente.check_in = check_in_dt
                registro_existente.check_out = check_out_dt
                registro_existente.nota_odoo = _merge_fichaje_notes(
                    registro_existente.nota_odoo, f.get('note')
                )
                _apply_odoo_metrics(registro_existente, f)

        if crear_asignacion_magica:
            existe_asig = Asignacion.query.filter_by(
                user_id=local_user.id, fecha=fecha_obj, obra_id=local_obra.id
            ).first()
            if not existe_asig:
                CoreAssignmentService.asignar(
                    local_user.id, local_obra.id, fecha_obj, None,
                    "Auto-asignación por Fichaje Físico",
                )

    # Cierre de día anterior: pendientes → Ausencia (aún no Falta).
    # Hoy no se marca Ausencia por hora límite: puede fichar más tarde.
    if fecha_obj < today_local():
        from app.services.desvio_fichaje_service import consolidar_pendientes_a_ausencia
        consolidar_pendientes_a_ausencia(fecha_obj)
    elif fecha_obj == today_local():
        # Solo exenciones por baja/vacaciones; no convertir Sin_Registro→Ausencia.
        from app.services.leave_service import user_has_approved_leave
        candidatos = RegistroFichaje.query.filter(
            RegistroFichaje.fecha == fecha_obj,
            RegistroFichaje.estado == 'Sin_Registro',
        ).all()
        for reg in candidatos:
            if user_has_approved_leave(reg.user_id, fecha_obj):
                reg.estado = 'Exento_Ausencia'
                reg.notas_resolucion = 'Cubierto por ausencia planificada (no cuenta como ausencia).'
        # Revertir Ausencias tempranas inventadas por el corte antiguo (sin fichaje).
        ausencias_tempranas = RegistroFichaje.query.filter_by(
            fecha=fecha_obj, estado='Ausencia'
        ).all()
        for reg in ausencias_tempranas:
            if not reg.check_in and not reg.obra_real_id:
                if (reg.notas_resolucion or '').startswith('Generada automáticamente'):
                    reg.estado = 'Sin_Registro'
                    reg.notas_resolucion = None

    if desvios_a_notificar:
        db.session.flush()
        from app.services.desvio_fichaje_service import notificar_desvio_inmediato
        vistos = set()
        reales_avisados = set()
        for reg in desvios_a_notificar:
            key = (reg.user_id, reg.fecha, reg.obra_planificada_id, reg.obra_real_id)
            if key in vistos:
                continue
            vistos.add(key)
            key_real = (reg.user_id, reg.fecha, reg.obra_real_id)
            omitir_real = key_real in reales_avisados
            if not omitir_real:
                reales_avisados.add(key_real)
            notificar_desvio_inmediato(reg, omitir_lado_real=omitir_real)