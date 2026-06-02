import logging
from datetime import date, datetime, timedelta
from app import db
from app.models import RegistroFichaje, Asignacion, User, Obra, Festivo, ConfiguracionGlobal
from app.sync.dispatcher import get_sync_adapter

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
        # Si es festivo, salimos de la función sin generar ausencias ni conflictos.
        return

    # 1. Obtenemos el adaptador dinámico del cliente actual
    try:
        adapter = get_sync_adapter()
        datos_crudos = adapter.get_fichajes_diarios(fecha_str)
    except Exception as e:
        logger.error(f"Error obteniendo fichajes del adaptador: {e}")
        return

    # 2. Mapeamos al formato interno que esperaba tu algoritmo original
    fichajes_crudos = []
    for d in datos_crudos:
        try:
            fichajes_crudos.append({
                'odoo_user': str(d['empleado_external_id']), # AHORA ES STR
                'odoo_obra': str(d['obra_external_id']),
                'autor': d.get('autor', 'Sistema'),
                'check_in': d.get('check_in'),
                'check_out': d.get('check_out')
            })
        except (ValueError, TypeError):
            continue

    # =========================================================================
    # --- AQUÍ EMPIEZA TU LÓGICA DE NEGOCIO EXACTA E INTACTA ---
    # =========================================================================
    fichajes_unicos = {}
    for f in fichajes_crudos:
        key = f"{f['odoo_user']}_{f['odoo_obra']}"
        if key not in fichajes_unicos:
            fichajes_unicos[key] = f
        else:
            # Si han fichado varias veces en la misma obra, nos quedamos con el primer check-in y el último check-out
            if f['check_in'] and (not fichajes_unicos[key]['check_in'] or f['check_in'] < fichajes_unicos[key]['check_in']):
                fichajes_unicos[key]['check_in'] = f['check_in']
            if f['check_out'] and (not fichajes_unicos[key]['check_out'] or f['check_out'] > fichajes_unicos[key]['check_out']):
                fichajes_unicos[key]['check_out'] = f['check_out']

    # --- PRE-EVALUACIÓN: RELLENAR CON SIN REGISTRO ---
    todas_asig = Asignacion.query.filter_by(fecha=fecha_obj).all()
    for asig in todas_asig:
        registro = RegistroFichaje.query.filter_by(user_id=asig.user_id, fecha=fecha_obj, obra_planificada_id=asig.obra_id).first()
        if not registro:
            db.session.add(RegistroFichaje(
                user_id=asig.user_id, fecha=fecha_obj, obra_planificada_id=asig.obra_id, estado='Sin_Registro'
            ))
            db.session.flush()

    # =========================================================================
    # --- LIMPIEZA REACTIVA: GUARDADO DE DATOS ESTRUCTURADOS ---
    # =========================================================================
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
        
        if not u_local or not u_local.odoo_id or not o_real or not o_real.odoo_id: 
            continue

        obras_odoo_del_usuario = obras_por_usuario_odoo.get(u_local.odoo_id, [])

        if o_real.odoo_id not in obras_odoo_del_usuario:
            # 1. Borrar asignaciones mágicas
            if reg_local.estado in ['Correcto_Automatico', 'Paracaidista', 'Resuelto_Asignado', 'Resuelto_Dividido', 'Resuelto_Movido']:
                asig_fantasma = Asignacion.query.filter_by(user_id=u_local.id, fecha=fecha_obj, obra_id=o_real.id).first()
                if asig_fantasma:
                    db.session.delete(asig_fantasma)

            # 2. Buscar datos de la NUEVA obra (si lo han movido)
            o_nueva_id = ""
            o_nueva_cod = ""
            o_nueva_nom = ""
            accion = "Borrado en Odoo"

            for key, f in fichajes_unicos.items():
                local_user = User.query.filter(User.external_ids['odoo'].astext == f['odoo_user']).first()
                local_obra = Obra.query.filter(Obra.external_ids['odoo'].astext == f['odoo_obra']).first()
                if f['odoo_user'] == u_local.odoo_id:
                    o_nueva = Obra.query.filter_by(odoo_id=f['odoo_obra']).first()
                    if o_nueva:
                        o_nueva_id = str(o_nueva.id)
                        o_nueva_cod = str(o_nueva.codigo or '')
                        o_nueva_nom = str(o_nueva.nombre or '')
                        accion = "Modificado de Obra"
                    break

            estado_anterior = reg_local.estado

            # 3. Guardar string estructurado
            datos_string = f"{o_real.id}||{o_real.codigo or ''}||{o_real.nombre}||{o_nueva_id}||{o_nueva_cod}||{o_nueva_nom}||{accion}||{estado_anterior}"

            # 4. Aplicar
            reg_local.estado = 'Sobreescrito_RRHH'
            reg_local.obra_real_id = None 
            reg_local.notas_resolucion = datos_string

    db.session.flush()

    # =========================================================================
    # --- 2. MOTOR DE VALIDACIÓN ---
    # =========================================================================
    conf_primer_fichaje = ConfiguracionGlobal.query.filter_by(clave='aceptar_primer_fichaje').first()
    # Asumimos 'True' por defecto para que funcione como hasta ahora si nadie ha tocado la configuración
    aceptar_primer_fichaje = conf_primer_fichaje.valor == 'True' if conf_primer_fichaje else True
    # -----------------------------------

    for key, f in fichajes_unicos.items():
        local_user = User.query.filter_by(odoo_id=f['odoo_user']).first()
        local_obra = Obra.query.filter_by(odoo_id=f['odoo_obra']).first()
        
        if not local_user or not local_obra:
            continue

        # --- CONVERSIÓN DE HORAS ODOO A PYTHON (AJUSTE UTC -> ESPAÑA) ---
        check_in_dt = None
        if f.get('check_in'):
            try:
                check_in_dt = datetime.strptime(f['check_in'], '%Y-%m-%d %H:%M:%S') + timedelta(hours=2)
            except ValueError:
                pass
        check_out_dt = None
        if f.get('check_out'):
            try:
                check_out_dt = datetime.strptime(f['check_out'], '%Y-%m-%d %H:%M:%S') + timedelta(hours=2)
            except ValueError:
                pass
        # ----------------------------------------------------------------

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
            
            # --- SUSTITUIR ESTE BLOQUE COMPLETO ---
            if ultima_obra_id == local_obra.id:
                # Inercia normal: coincide con el historial
                nuevo_estado = 'Correcto_Automatico'
                nuevo_plan_id = local_obra.id
                crear_asignacion_magica = True
            
            elif ultima_obra_id is None:
                # Es el PRIMER fichaje. Verificamos qué quiere el cliente
                if aceptar_primer_fichaje:
                    nuevo_estado = 'Correcto_Automatico'
                    nuevo_plan_id = local_obra.id
                    crear_asignacion_magica = True
                else:
                    # El cliente no lo permite. Se marca como intruso.
                    nuevo_estado = 'Paracaidista'
                    nuevo_plan_id = None
                    crear_asignacion_magica = False
            
            else:
                # Ficha en obra distinta al historial (Paracaidista estándar)
                nuevo_estado = 'Paracaidista'
                nuevo_plan_id = None
                crear_asignacion_magica = False

        # >>> AÑADIDO 'Ausencia' PARA AUTO-RESOLVER FALTAS AL RECIBIR FICHAJE <<<
        registro_vacio_exacto = RegistroFichaje.query.filter(
            RegistroFichaje.user_id == local_user.id,
            RegistroFichaje.fecha == fecha_obj,
            RegistroFichaje.obra_planificada_id == local_obra.id,
            RegistroFichaje.estado.in_(['Sin_Registro', 'Ausencia'])
        ).first()

        if registro_vacio_exacto:
            # Si el sistema ya le había clavado 'Ausencia', es que llegó tarde
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

        if crear_asignacion_magica:
            existe_asig = Asignacion.query.filter_by(user_id=local_user.id, fecha=fecha_obj, obra_id=local_obra.id).first()
            if not existe_asig:
                db.session.add(Asignacion(user_id=local_user.id, fecha=fecha_obj, obra_id=local_obra.id))
        
        db.session.flush()

    # =========================================================================
    # >>> NUEVO: AUTO-EVALUAR AUSENCIAS TRAS SINCRONIZAR <<<
    # =========================================================================
    if fecha_obj == date.today():
        conf_hora = ConfiguracionGlobal.query.filter_by(clave='hora_limite_entrada').first()
        hora_str = conf_hora.valor if conf_hora else "08:30"
        
        try:
            hora_corte = datetime.strptime(hora_str, "%H:%M").time()
        except ValueError:
            hora_corte = datetime.strptime("08:30", "%H:%M").time()
        
        ahora_espana = datetime.utcnow() + timedelta(hours=2)
        
        # Si ya hemos superado la hora límite...
        if ahora_espana.time() >= hora_corte:
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

    db.session.commit()