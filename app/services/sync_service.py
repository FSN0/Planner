import logging
from datetime import date, datetime, timedelta
from app import db
from app.models import Obra, User, Company

logger = logging.getLogger(__name__)

def procesar_fichajes_diarios(fecha_str=None):
    """
    Motor central de validación de fichajes.
    Independiente del ERP que use el cliente (Odoo, SAP, etc).
    """
    if not fecha_str:
        fecha_str = date.today().strftime('%Y-%m-%d')
    fecha_obj = datetime.strptime(fecha_str, '%Y-%m-%d').date()
    
    es_festivo = Festivo.query.filter_by(fecha=fecha_obj).first()
    if es_festivo:
        return

        lock_id = 424242
        if not db.session.execute(text("SELECT pg_try_advisory_lock(:id)"), {'id': lock_id}).scalar():
            logger.warning("Sync fichajes omitido: otra instancia ya está en ejecución.")
            return

        try:
            self._sync_fichajes_diarios_impl(fecha_obj, fecha_str)
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
        finally:
            try:
                db.session.execute(text("SELECT pg_advisory_unlock(:id)"), {'id': lock_id})
            except Exception:
                pass

    def _sync_fichajes_diarios_impl(self, fecha_obj, fecha_str):
        from app.models import RegistroFichaje, Asignacion, User, Obra
        from datetime import datetime
        from app import db

    try:
        adapter = get_sync_adapter()
        datos_crudos = adapter.get_fichajes_diarios(fecha_str)
    except Exception as e:
        logger.error(f"Error obteniendo fichajes del adaptador: {e}")
        return

            for a in att_int:
                if a.get('employee_id'):
                    # Extraemos la obra de forma segura por si Odoo manda False (Obra quitada por RRHH)
                    obra_id = a.get('project_id')[0] if a.get('project_id') else None
                    modificado_por = a.get('write_uid')[1] if a.get('write_uid') else 'RRHH Odoo'
                    fichajes_crudos.append({'odoo_user': a['employee_id'][0], 'odoo_obra': obra_id, 'autor': modificado_por, 'check_in': a.get('check_in'), 'check_out': a.get('check_out')})
        except Exception as e:
            logger.error(f"🚨 [Odoo Sync] CRITICO: Fallo conexion hr.attendance: {str(e)}")
            return # ABORTA LA FUNCION SI FALLA LA CONEXION

        try:
            att_ext = self.models.execute_kw(self.db_name, self.uid, self.pwd, 'partner.attendance', 'search_read', [domain], {'fields': ['partner_id', 'project_id', 'write_uid', 'check_in', 'check_out']})
            if not isinstance(att_ext, list):
                logger.error(f"🚨 [Odoo Sync] Error: partner.attendance devolvio no-lista. Abortando.")
                return

            for a in att_ext:
                if a.get('partner_id'):
                    # Extraemos la obra de forma segura por si Odoo manda False
                    obra_id = a.get('project_id')[0] if a.get('project_id') else None
                    modificado_por = a.get('write_uid')[1] if a.get('write_uid') else 'RRHH Odoo'
                    fichajes_crudos.append({'odoo_user': a['partner_id'][0], 'odoo_obra': obra_id, 'autor': modificado_por, 'check_in': a.get('check_in'), 'check_out': a.get('check_out')})
        
        
        except Exception as e:
            logger.error(f"🚨 [Odoo Sync] CRITICO: Fallo conexion partner.attendance: {str(e)}")
            return # ABORTA LA FUNCION SI FALLA LA CONEXION

    fichajes_unicos = {}
    for f in fichajes_crudos:
        key = f"{f['odoo_user']}_{f['odoo_obra']}"
        if key not in fichajes_unicos:
            fichajes_unicos[key] = f
        else:
            if f['check_in'] and (not fichajes_unicos[key]['check_in'] or f['check_in'] < fichajes_unicos[key]['check_in']):
                fichajes_unicos[key]['check_in'] = f['check_in']
            if f['check_out'] and (not fichajes_unicos[key]['check_out'] or f['check_out'] > fichajes_unicos[key]['check_out']):
                fichajes_unicos[key]['check_out'] = f['check_out']

    todas_asig = Asignacion.query.filter_by(fecha=fecha_obj).all()
    for asig in todas_asig:
        registro = RegistroFichaje.query.filter_by(user_id=asig.user_id, fecha=fecha_obj, obra_planificada_id=asig.obra_id).first()
        if not registro:
            db.session.add(RegistroFichaje(
                user_id=asig.user_id, fecha=fecha_obj, obra_planificada_id=asig.obra_id, estado='Sin_Registro'
            ))
            db.session.flush()

    obras_por_usuario_odoo = {}
    for f in fichajes_unicos.values():
        if f['odoo_user'] not in obras_por_usuario_odoo:
            obras_por_usuario_odoo[f['odoo_user']] = []
        obras_por_usuario_odoo[f['odoo_user']].append(f['odoo_obra'])

    registros_hoy_locales = RegistroFichaje.query.filter_by(fecha=fecha_obj).filter(
        RegistroFichaje.obra_real_id.isnot(None),
        RegistroFichaje.estado != 'Sobreescrito_RRHH'
    ).all()

    for reg_local in registros_hoy_locales:
        u_local = User.query.get(reg_local.user_id)
        o_real = Obra.query.get(reg_local.obra_real_id)
        
        odoo_user_id = u_local.external_ids.get('odoo') if u_local and u_local.external_ids else None
        odoo_obra_id = o_real.external_ids.get('odoo') if o_real and o_real.external_ids else None
        
        if not u_local or not odoo_user_id or not o_real or not odoo_obra_id: 
            continue

        obras_odoo_del_usuario = obras_por_usuario_odoo.get(odoo_user_id, [])

            if o_real.odoo_id not in obras_odoo_del_usuario:
                # 1. Borrar asignaciones mágicas
                
                asig_fantasma = Asignacion.query.filter_by(user_id=u_local.id, fecha=fecha_obj, obra_id=o_real.id).first()
                if asig_fantasma:
                    from app.services.core_assignment_service import CoreAssignmentService
                    CoreAssignmentService.desasignar(
                        u_local.id, o_real.id, fecha_obj, 1,
                        "Fichaje Anulado por Odoo",
                        f"Borrada asignación en {o_real.nombre} por falta de registro en Odoo."
                    )

            o_nueva_id = ""
            o_nueva_cod = ""
            o_nueva_nom = ""
            accion = "Borrado en Odoo"

            for key, f in fichajes_unicos.items():
                if f['odoo_user'] == odoo_user_id:
                    o_nueva = Obra.query.filter(Obra.external_ids['odoo'].astext == f['odoo_obra']).first()
                    if o_nueva:
                        o_nueva_id = str(o_nueva.id)
                        o_nueva_cod = str(o_nueva.codigo or '')
                        o_nueva_nom = str(o_nueva.nombre or '')
                        accion = "Modificado de Obra"
                    break

            estado_anterior = reg_local.estado

            datos_string = f"{o_real.id}||{o_real.codigo or ''}||{o_real.nombre}||{o_nueva_id}||{o_nueva_cod}||{o_nueva_nom}||{accion}||{estado_anterior}"

            reg_local.estado = 'Sobreescrito_RRHH'
            reg_local.obra_real_id = None 
            reg_local.notas_resolucion = datos_string

    db.session.flush()

    conf_primer_fichaje = ConfiguracionGlobal.query.filter_by(clave='aceptar_primer_fichaje').first()
    aceptar_primer_fichaje = conf_primer_fichaje.valor == 'True' if conf_primer_fichaje else True

    for key, f in fichajes_unicos.items():
        local_user = User.query.filter(User.external_ids['odoo'].astext == f['odoo_user']).first()
        local_obra = Obra.query.filter(Obra.external_ids['odoo'].astext == f['odoo_obra']).first()
        
        if not local_user or not local_obra:
            continue

            from app.utils.timezone_utils import parse_odoo_datetime, utc_now, format_time
            check_in_dt = parse_odoo_datetime(f.get('check_in'))
            check_out_dt = parse_odoo_datetime(f.get('check_out'))
        check_in_dt = None
        if f.get('check_in'):
            try:
                dt_utc = datetime.strptime(f['check_in'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=ZoneInfo("UTC"))
                check_in_dt = dt_utc.astimezone(ZoneInfo("Europe/Madrid")).replace(tzinfo=None)
            except ValueError:
                pass
        check_out_dt = None
        if f.get('check_out'):
            try:
                check_out_dt = datetime.strptime(f['check_out'], '%Y-%m-%d %H:%M:%S') + timedelta(hours=2)
            except ValueError:
                pass

        plan_exacto = Asignacion.query.filter_by(user_id=local_user.id, fecha=fecha_obj, obra_id=local_obra.id).first()
        
        nuevo_estado = ''
        nuevo_plan_id = None
        crear_asignacion_magica = False

        if plan_exacto:
            nuevo_estado = 'Correcto'
            nuevo_plan_id = local_obra.id
        else:
            ultimo_reg = RegistroFichaje.query.filter(
                RegistroFichaje.user_id == local_user.id,
                RegistroFichaje.fecha < fecha_obj,
                RegistroFichaje.estado.in_(['Correcto', 'Correcto_Automatico', 'Resuelto_Movido', 'Resuelto_Asignado', 'Resuelto_Dividido'])
            ).order_by(RegistroFichaje.fecha.desc()).first()
            
            ultima_obra_id = ultimo_reg.obra_real_id if ultimo_reg else None
            
            if ultima_obra_id == local_obra.id:
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
            RegistroFichaje.estado.in_(['Sin_Registro', 'Ausencia'])
        ).first()

        if registro_vacio_exacto:
            if registro_vacio_exacto.estado == 'Ausencia':
                registro_vacio_exacto.estado = 'Retraso'
                registro_vacio_exacto.notas_resolucion = f"Fichaje recibido después del corte horario. Hora detectada: {check_in_dt.strftime('%H:%M') if check_in_dt else 'N/A'}"
            else:
                registro_vacio_exacto.estado = nuevo_estado
                
            registro_vacio_exacto.obra_real_id = local_obra.id
            registro_vacio_exacto.check_in = check_in_dt
            registro_vacio_exacto.check_out = check_out_dt
        else:
            registro_existente = RegistroFichaje.query.filter_by(
                user_id=local_user.id, fecha=fecha_obj, obra_real_id=local_obra.id
            ).first()
            
            if not registro_existente:
                db.session.add(RegistroFichaje(
                    user_id=local_user.id, fecha=fecha_obj,
                    obra_planificada_id=nuevo_plan_id, obra_real_id=local_obra.id, estado=nuevo_estado,
                    check_in=check_in_dt, check_out=check_out_dt 
                ))
            else:
                if not registro_existente.estado.startswith('Resuelto'):
                    registro_existente.estado = nuevo_estado
                    registro_existente.obra_planificada_id = nuevo_plan_id
                registro_existente.check_in = check_in_dt
                registro_existente.check_out = check_out_dt
            if registro_vacio_exacto:
                # Si el sistema ya le había clavado 'Ausencia', es que llegó tarde
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
            else:
                registro_existente = RegistroFichaje.query.filter_by(
                    user_id=local_user.id, fecha=fecha_obj, obra_real_id=local_obra.id
                ).first()
                
                if not registro_existente:
                    # 1. El sistema guarda el fichaje para el cuadrante
                    db.session.add(RegistroFichaje(
                        user_id=local_user.id, fecha=fecha_obj,
                        obra_planificada_id=nuevo_plan_id, obra_real_id=local_obra.id, estado=nuevo_estado,
                        check_in=check_in_dt, check_out=check_out_dt 
                    ))
                    
                    # 2. LA CAJA NEGRA: Grabar en piedra el log físico
                    from app.models import SystemLog
                    from app.services.core_assignment_service import CoreAssignmentService
                    obra_label = CoreAssignmentService.format_obra_label(local_obra)
                    db.session.add(SystemLog(
                        timestamp=check_in_dt or utc_now(),
                        category='fichaje_app',
                        action=f"Fichaje físico [{nuevo_estado.replace('_', ' ')}]",
                        detail=(
                            f"El operario fichó en {obra_label}. "
                            f"Entrada: {format_time(check_in_dt) if check_in_dt else '-'} / "
                            f"Salida: {format_time(check_out_dt) if check_out_dt else '-'}"
                        ),
                        target_user_id=local_user.id,
                        target_date=fecha_obj
                    ))
                else:
                    if not registro_existente.estado.startswith('Resuelto'):
                        registro_existente.estado = nuevo_estado
                        registro_existente.obra_planificada_id = nuevo_plan_id
                    registro_existente.check_in = check_in_dt
                    registro_existente.check_out = check_out_dt

        if crear_asignacion_magica:
            existe_asig = Asignacion.query.filter_by(user_id=local_user.id, fecha=fecha_obj, obra_id=local_obra.id).first()
            if not existe_asig:
                db.session.add(Asignacion(user_id=local_user.id, fecha=fecha_obj, obra_id=local_obra.id))
        
        db.session.flush()
            if crear_asignacion_magica:
                existe_asig = Asignacion.query.filter_by(user_id=local_user.id, fecha=fecha_obj, obra_id=local_obra.id).first()
                if not existe_asig:
                    from app.services.core_assignment_service import CoreAssignmentService
                    CoreAssignmentService.asignar(
                        local_user.id, local_obra.id, fecha_obj, None,
                        "Auto-asignación por Fichaje Físico"
                    )

    if fecha_obj == date.today():
        conf_hora = ConfiguracionGlobal.query.filter_by(clave='hora_limite_entrada').first()
        hora_str = conf_hora.valor if conf_hora else "08:30"
        
        try:
            hora_corte = datetime.strptime(hora_str, "%H:%M").time()
        except ValueError:
            hora_corte = datetime.strptime("08:30", "%H:%M").time()
        
        ahora_espana = datetime.utcnow() + timedelta(hours=2)
        
        if ahora_espana.time() >= hora_corte:
            sin_registros = RegistroFichaje.query.filter_by(fecha=fecha_obj, estado='Sin_Registro').all()
            for reg in sin_registros:
                reg.estado = 'Ausencia'
                reg.notas_resolucion = 'Generada automáticamente tras superar la hora de corte.'
        
        else:
            ausencias_tempranas = RegistroFichaje.query.filter_by(fecha=fecha_obj, estado='Ausencia').all()
            for reg in ausencias_tempranas:
                if not reg.check_in:
                    reg.estado = 'Sin_Registro'
                    reg.notas_resolucion = None

    db.session.commit()
       # =========================================================================
        # >>> NUEVO: AUTO-EVALUAR AUSENCIAS TRAS SINCRONIZAR <<<
        # =========================================================================
        from app.utils.timezone_utils import now_local, today_local
        if fecha_obj == today_local():
            from app.models import ConfiguracionGlobal
            
            conf_hora = ConfiguracionGlobal.query.filter_by(clave='hora_limite_entrada').first()
            hora_str = conf_hora.valor if conf_hora else "08:30"
            
            try:
                hora_corte = datetime.strptime(hora_str, "%H:%M").time()
            except ValueError:
                hora_corte = datetime.strptime("08:30", "%H:%M").time()
            
            ahora_local = now_local()
            
            if ahora_local.time() >= hora_corte:
                sin_registros = RegistroFichaje.query.filter_by(fecha=fecha_obj, estado='Sin_Registro').all()
                for reg in sin_registros:
                    reg.estado = 'Ausencia'
                    reg.notas_resolucion = 'Generada automáticamente tras superar la hora de corte.'
            
            # >>> NUEVO: Si la hora se ha retrasado y AÚN NO es la hora de corte...
            else:
                ausencias_tempranas = RegistroFichaje.query.filter_by(fecha=fecha_obj, estado='Ausencia').all()
                for reg in ausencias_tempranas:
                    # Si no tiene check_in real, significa que fue generada por el sistema. La devolvemos.
                    if not reg.check_in:
                        reg.estado = 'Sin_Registro'
                        reg.notas_resolucion = None

    