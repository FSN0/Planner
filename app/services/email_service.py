# app/services/email_service.py
from flask_mail import Message
from flask import current_app
from app import mail
from app.models import User, Obra, RegistroFichaje, ConfiguracionGlobal
from datetime import datetime, date, timedelta

def send_email(subject, recipients, text_body, html_body=None):
    """Envía correo. Devuelve True si salió; False si no hay destino o falla SMTP."""
    if not recipients:
        return False
    msg = Message(subject, sender=current_app.config.get('MAIL_DEFAULT_SENDER'), recipients=recipients)
    msg.body = text_body
    if html_body:
        msg.html = html_body
    try:
        mail.send(msg)
        return True
    except Exception as e:
        current_app.logger.warning('Error enviando correo a %s: %s', recipients, e)
        return False

def _obtener_destinatarios(evento_clave, obra_id=None, worker_id=None):
    """
    Función maestra que lee la Matriz de Configuración.
    Busca los correos de Admin, Jefe y Trabajador solo si están marcados (tick) en la BD.
    Sin filtros de silencio: si está tickado, se envía siempre.
    """
    conf = ConfiguracionGlobal.query.filter_by(clave=evento_clave).first()
    if not conf or not conf.valor:
        return [] # Nadie suscrito a este evento
        
    suscritos = conf.valor.split(',') # Ej: ['admin', 'jefe', 'trabajador']
    correos = []
    
    if 'admin' in suscritos:
        admins = User.query.filter_by(role='admin', active=True).all()
        correos.extend([a.email for a in admins if a.email])
        
    if 'jefe' in suscritos and obra_id:
        obra = Obra.query.get(obra_id)
        if obra and obra.jefe_obra_id:
            jefe = User.query.get(obra.jefe_obra_id)
            if jefe and jefe.email: correos.append(jefe.email)
            
    if 'trabajador' in suscritos and worker_id:
        worker = User.query.get(worker_id)
        if worker and worker.email: correos.append(worker.email)
        
    # Eliminamos duplicados (por si un admin también es jefe de esa obra)
    return list(set(correos))

def notificar_nueva_solicitud(solicitud, solicitante_name):
    """Notifica la creación de una solicitud (Genérica o Concreta)"""
    clave = 'email_sol_generica' if solicitud.tipo == 'GENERICA' else 'email_sol_concreta'
    destinatarios = _obtener_destinatarios(clave, obra_id=solicitud.obra_id, worker_id=solicitud.empleado_id)
    if not destinatarios: return

    obra = Obra.query.get(solicitud.obra_id)
    
    # Obtener nombre completo del Jefe y saber si es Baja
    jefe = User.query.get(solicitud.requested_by_id)
    nombre_jefe = f"{jefe.name} {jefe.lastname}" if jefe else solicitante_name
    tipo_solic = "baja de personal" if getattr(solicitud, 'accion', '') == 'DESASIGNAR' else "personal"

    asunto = f"NUEVA SOLICITUD DE {tipo_solic.upper()} - {obra.nombre}"
    
    texto = (
        f"El Jefe de Obra {nombre_jefe} ha creado una nueva solicitud de {tipo_solic}.\n\n"
        f"Obra: {obra.nombre}\n"
    )
    if solicitud.tipo == 'CONCRETA':
        worker = User.query.get(solicitud.empleado_id)
        if worker:
            texto += f"Trabajador Solicitado: {worker.name} {worker.lastname}\n"
    else:
        texto += f"Perfil Solicitado: {solicitud.perfil_categoria} (Cant: {solicitud.cantidad_solicitada})\n"
        
    texto += f"Fechas: {solicitud.fecha_inicio.strftime('%d/%m/%Y')} al {solicitud.fecha_fin.strftime('%d/%m/%Y')}\n"

    from app.services.solicitud_service import get_solicitud_notas
    notas = get_solicitud_notas(solicitud)
    if notas:
        texto += f"\nNotas del solicitante:\n{notas}\n"

    texto += "\nPor favor, entra en la plataforma para revisarla y gestionarla."
    
    send_email(asunto, destinatarios, texto)

def notificar_resolucion_solicitud(solicitud, admin_name, worker_id=None):
    """Notifica cuando una solicitud cambia de estado (Aprobada, Denegada, etc.)"""
    # Usamos el worker_id si lo hay, o el de la solicitud
    id_trabajador = solicitud.empleado_id or worker_id
    
    destinatarios = _obtener_destinatarios('email_sol_resuelta', obra_id=solicitud.obra_id, worker_id=id_trabajador)
    if not destinatarios:
        return

    obra = Obra.query.get(solicitud.obra_id) if solicitud.obra_id else None
    obra_nombre = obra.nombre if obra else 'obra'
    asunto = f"Resolución de solicitud #{solicitud.id} - {obra_nombre}"
    
    texto = (
        f"La solicitud para la obra {obra_nombre} ha sido resuelta por {admin_name}.\n\n"
        f"Estado: {solicitud.estado}\n"
        f"Acción solicitada: {getattr(solicitud, 'accion', 'ASIGNAR')}\n"
    )
    
    # AQUÍ PONEMOS EL NOMBRE Y LA EMPRESA SIN IMPORTAR SI ES CONCRETA O GENÉRICA
    if id_trabajador:
        worker = User.query.get(id_trabajador)
        if worker:
            empresa = worker.company_rel.nombre if worker.company_rel else "Sin empresa"
            texto += f"Trabajador movido: {worker.name} {worker.lastname}\n"
            texto += f"Empresa: {empresa}\n"

    if solicitud.fecha_inicio and solicitud.fecha_fin:
        texto += (
            f"Fechas: {solicitud.fecha_inicio.strftime('%d/%m/%Y')} "
            f"al {solicitud.fecha_fin.strftime('%d/%m/%Y')}\n\n"
        )
    texto += f"Revisa la plataforma para más detalles."
    
    send_email(asunto, destinatarios, texto)


def _clave_email_solicitud_vehiculo():
    """Config dedicada email_sol_vehiculo; si no existe, reutiliza email_sol_concreta."""
    conf = ConfiguracionGlobal.query.filter_by(clave='email_sol_vehiculo').first()
    if conf and conf.valor:
        return 'email_sol_vehiculo'
    return 'email_sol_concreta'


def notificar_nueva_solicitud_vehiculo(solicitud, solicitante_name):
    """Notifica la creación de una SolicitudVehiculo (espejo de personal concreta)."""
    clave = _clave_email_solicitud_vehiculo()
    destinatarios = _obtener_destinatarios(clave, worker_id=solicitud.empleado_id)
    if not destinatarios:
        return

    jefe = User.query.get(solicitud.requested_by_id)
    nombre_jefe = f"{jefe.name} {jefe.lastname}" if jefe else solicitante_name
    tipo_solic = (
        "baja de vehículo" if getattr(solicitud, 'accion', '') == 'DESASIGNAR'
        else "vehículo"
    )

    from app.models import Vehiculo
    veh = getattr(solicitud, 'vehiculo', None)
    if veh is None and solicitud.vehiculo_id:
        veh = Vehiculo.query.get(solicitud.vehiculo_id)
    veh_txt = veh.label() if veh else (
        f"vehículo #{solicitud.vehiculo_id}" if solicitud.vehiculo_id else "cualquier"
    )

    asunto = f"NUEVA SOLICITUD DE {tipo_solic.upper()} - {veh_txt}"
    texto = (
        f"El usuario {nombre_jefe} ha creado una nueva solicitud de {tipo_solic}.\n\n"
        f"Vehículo: {veh_txt}\n"
    )
    worker = User.query.get(solicitud.empleado_id)
    if worker:
        texto += f"Trabajador: {worker.name} {worker.lastname}\n"
    texto += (
        f"Fechas: {solicitud.fecha_inicio.strftime('%d/%m/%Y')} "
        f"al {solicitud.fecha_fin.strftime('%d/%m/%Y')}\n"
    )
    notas = (getattr(solicitud, 'notas', None) or '').strip()
    if notas:
        texto += f"\nNotas del solicitante:\n{notas}\n"
    texto += "\nPor favor, entra en la plataforma para revisarla y gestionarla."
    send_email(asunto, destinatarios, texto)


def notificar_resolucion_solicitud_vehiculo(solicitud, admin_name):
    """Notifica resolución de SolicitudVehiculo (aceptar/denegar)."""
    destinatarios = _obtener_destinatarios(
        'email_sol_resuelta', worker_id=solicitud.empleado_id
    )
    # Sin obra: si 'jefe' está suscrito, avisar al solicitante
    conf = ConfiguracionGlobal.query.filter_by(clave='email_sol_resuelta').first()
    if conf and conf.valor and 'jefe' in conf.valor.split(','):
        requester = User.query.get(solicitud.requested_by_id)
        if requester and requester.email:
            destinatarios = list(set(destinatarios + [requester.email]))
    if not destinatarios:
        return

    from app.models import Vehiculo
    veh = getattr(solicitud, 'vehiculo', None)
    if veh is None and solicitud.vehiculo_id:
        veh = Vehiculo.query.get(solicitud.vehiculo_id)
    veh_txt = veh.label() if veh else (
        f"vehículo #{solicitud.vehiculo_id}" if solicitud.vehiculo_id else "—"
    )

    asunto = f"Resolución de solicitud de vehículo #{solicitud.id} - {veh_txt}"
    texto = (
        f"La solicitud de vehículo ha sido resuelta por {admin_name}.\n\n"
        f"Estado: {solicitud.estado}\n"
        f"Acción solicitada: {getattr(solicitud, 'accion', 'ASIGNAR')}\n"
        f"Vehículo: {veh_txt}\n"
    )
    worker = User.query.get(solicitud.empleado_id)
    if worker:
        texto += f"Trabajador: {worker.name} {worker.lastname}\n"
    texto += (
        f"Fechas: {solicitud.fecha_inicio.strftime('%d/%m/%Y')} "
        f"al {solicitud.fecha_fin.strftime('%d/%m/%Y')}\n\n"
        f"Revisa la plataforma para más detalles."
    )
    send_email(asunto, destinatarios, texto)

def notificar_traslado_interno(jefe_name, worker, target_obra, dates, obras_origen=None):
    """Notifica cuando un Jefe mueve a un operario por custodia entre sus obras"""
    destinatarios = _obtener_destinatarios('email_traslado', obra_id=target_obra.id, worker_id=worker.id)
    if not destinatarios: return
    
    if len(dates) > 1:
        fecha_str = f"Desde el {min(dates).strftime('%d/%m/%Y')} hasta el {max(dates).strftime('%d/%m/%Y')}"
    else:
        fecha_str = f"El {dates[0].strftime('%d/%m/%Y')}"

    # Buscar el nombre completo del jefe
    jefe_obj = User.query.filter(User.name.like(f"%{jefe_name.split()[0]}%")).first()
    nombre_jefe_completo = f"{jefe_obj.name} {jefe_obj.lastname}" if jefe_obj else jefe_name

    # Diferenciamos si es Traslado o Extensión
    if obras_origen:
        asunto = f"Aviso: Traslado de Personal - {nombre_jefe_completo}"
        texto = (
            f"El Jefe de Obra {nombre_jefe_completo} ha realizado un traslado entre sus obras.\n\n"
            f"Trabajador movido: {worker.name} {worker.lastname}\n\n"
            f"Obra origen: {', '.join(obras_origen)}\n"
            f"Fechas origen: {fecha_str}\n\n"
            f"Obra Destino: {target_obra.nombre}\n"
            f"Fechas: {fecha_str}\n\n"
            f"Este movimiento ha sido auto-aprobado por el sistema ya que se disponía de custodia activa sobre el trabajador."
        )
    else:
        asunto = f"Aviso: Extensión de Personal - {nombre_jefe_completo}"
        texto = (
            f"El Jefe de Obra {nombre_jefe_completo} ha realizado una extensión de personal.\n\n"
            f"Trabajador movido: {worker.name} {worker.lastname}\n"
            f"Obra Destino: {target_obra.nombre}\n"
            f"Fechas: {fecha_str}\n\n"
            f"Este movimiento ha sido auto-aprobado por el sistema ya que se disponía de custodia activa sobre el trabajador."
        )

    send_email(asunto, destinatarios, texto)

def notificar_movimiento_admin_a_jo(obra_id, worker_name, accion, fecha_str, admin_name):
    """Notifica cuando se asigna o desasigna personal directamente en el planificador"""
    is_baja = 'desasignar' in accion.lower() or 'baja' in accion.lower()
    clave = 'email_desasignacion' if is_baja else 'email_asignacion'
    
    worker_id = None
    if worker_name:
        worker = User.query.filter(User.name.like(f"%{worker_name.split()[0]}%")).first()
        if worker:
            worker_id = worker.id

    destinatarios = _obtener_destinatarios(clave, obra_id=obra_id, worker_id=worker_id)
    if not destinatarios: return

    obra = Obra.query.get(obra_id)
    asunto = f"Actualización de Personal - {obra.nombre}"
    texto = (
        f"El administrador {admin_name} ha realizado un movimiento en la obra ({obra.nombre}):\n\n"
        f"Acción: {accion.upper()}\n"
        f"Operario: {worker_name}\n"
        f"Fecha/s afectada(s): {fecha_str}\n\n"
        f"Revisa el planificador para ver los detalles."
    )
    send_email(asunto, destinatarios, texto)


def enviar_super_reporte_diario():
    """
    Sustituye a 'notificar_auditoria_diaria_0830'.
    Manda correos agrupados a JO y Admins sobre ausencias de HOY y paracaidistas/conflictos de AYER.
    """
    from app.utils.timezone_utils import today_local
    hoy = today_local()
    ayer = hoy - timedelta(days=1)
    
    # 1. Ausencias tempranas de HOY
    ausencias_hoy = RegistroFichaje.query.filter_by(fecha=hoy, estado='Ausencia').all()
    
    # 2. Paracaidistas/Conflictos de AYER (por si en la BD guardas Paracaidista o Conflicto)
    conflictos_ayer = RegistroFichaje.query.filter(
        RegistroFichaje.fecha == ayer,
        RegistroFichaje.estado.in_(['Conflicto', 'Paracaidista'])
    ).all()

    if not ausencias_hoy and not conflictos_ayer:
        return 

    # ==========================================
    # CORREO GLOBAL PARA LOS ADMINISTRADORES
    # ==========================================
    admins = User.query.filter_by(role='admin', active=True).all()
    admin_emails = [a.email for a in admins if a.email]
    
    if admin_emails:
        asunto_admin = f"Alerta de Fichajes Global ({hoy.strftime('%d/%m/%Y')})"
        
        html_admin = f"""
        <div style="font-family: Arial, sans-serif; padding: 20px; color: #333;">
            <h2 style="color: #1d4ed8;">Reporte de Presencia y Fichajes 📋</h2>
            <p>Resumen automático generado en la hora de corte de entrada.</p>
            
            <h3 style="color: #dc2626; border-bottom: 1px solid #ddd; padding-bottom: 5px;">
                Ausencias Detectadas HOY ({hoy.strftime('%d/%m/%Y')}):
            </h3>
            <ul>
        """
        if ausencias_hoy:
            for a in ausencias_hoy:
                obra_nom = a.obra_planificada.nombre if a.obra_planificada else 'Obra Desconocida'
                html_admin += f"<li><b>{a.user.name} {a.user.lastname}</b> - Faltó en: {obra_nom}</li>"
        else:
            html_admin += "<li><i style='color: green;'>Todo el personal planificado ha fichado.</i></li>"
            
        html_admin += f"""
            </ul>
            <h3 style="color: #f59e0b; border-bottom: 1px solid #ddd; padding-bottom: 5px; margin-top: 20px;">
                Fichajes No Planificados AYER ({ayer.strftime('%d/%m/%Y')}):
            </h3>
            <ul>
        """
        
        if conflictos_ayer:
            for c in conflictos_ayer:
                obra_real = c.obra_real.nombre if c.obra_real else 'Desconocida'
                obra_plan = c.obra_planificada.nombre if c.obra_planificada else 'NINGUNA'
                html_admin += f"<li><b>{c.user.name} {c.user.lastname}</b> - Apareció en: {obra_real} (Estaba planificado en: {obra_plan})</li>"
        else:
            html_admin += "<li><i style='color: green;'>No hubo incidencias de paracaidistas ayer.</i></li>"
            
        html_admin += "</ul></div>"
            
        send_email(asunto_admin, admin_emails, "Contenido en HTML.", html_body=html_admin)

    # ==========================================
    # CORREOS ESPECÍFICOS PARA CADA JEFE DE OBRA
    # ==========================================
    obras_afectadas_ids = set(
        [a.obra_planificada_id for a in ausencias_hoy if a.obra_planificada_id] + 
        [c.obra_real_id for c in conflictos_ayer if c.obra_real_id]
    )
    
    for obra_id in obras_afectadas_ids:
        obra = Obra.query.get(obra_id)
        if not obra or not obra.jefe_obra or not obra.jefe_obra.email: continue
            
        aus_obra = [a for a in ausencias_hoy if a.obra_planificada_id == obra.id]
        con_obra = [c for c in conflictos_ayer if c.obra_real_id == obra.id]
        
        asunto_jo = f"Alerta de Personal - {obra.nombre} ({hoy.strftime('%d/%m/%Y')})"
        
        html_jo = f"""
        <div style="font-family: Arial, sans-serif; padding: 20px; color: #333;">
            <h3>Hola {obra.jefe_obra.name},</h3>
            <p>Incidencias detectadas en tu obra <b>{obra.nombre}</b> en la hora de corte:</p>
        """
        
        if aus_obra:
            html_jo += f"<h4 style='color: #dc2626;'>NO HAN FICHADO HOY ({hoy.strftime('%d/%m/%Y')}):</h4><ul>"
            for a in aus_obra: html_jo += f"<li>{a.user.name} {a.user.lastname}</li>"
            html_jo += "</ul>"
                
        if con_obra:
            html_jo += f"<h4 style='color: #f59e0b;'>FICHARON AYER ({ayer.strftime('%d/%m/%Y')}) SIN ESTAR PLANIFICADOS:</h4><ul>"
            for c in con_obra: html_jo += f"<li>{c.user.name} {c.user.lastname}</li>"
            html_jo += "</ul>"
            
        html_jo += "</div>"
            
        send_email(asunto_jo, [obra.jefe_obra.email], "Contenido en HTML.", html_body=html_jo)