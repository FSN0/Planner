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
    if current_app.config.get('TESTING') or current_app.config.get('MAIL_SUPPRESS_SEND'):
        current_app.logger.info(
            'Correo no enviado (TESTING/MAIL_SUPPRESS_SEND): %s -> %s',
            subject, recipients,
        )
        return True
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

def _user_locale(user, *, bulk=False):
    from app.services.i18n_service import normalize_locale, get_locale, DEFAULT_LOCALE
    if user is not None:
        loc = normalize_locale(getattr(user, 'locale', None))
        if loc:
            return loc
        if bulk:
            return DEFAULT_LOCALE
    return get_locale() or DEFAULT_LOCALE


def _send_localized(users, subject_fn, text_fn, html_fn=None, *, bulk=True):
    from collections import defaultdict
    groups = defaultdict(list)
    seen = set()
    for user in users:
        email = (getattr(user, 'email', None) or '').strip() if user is not None else ''
        if not email or email in seen:
            continue
        seen.add(email)
        groups[_user_locale(user, bulk=bulk)].append(email)
    for loc, emails in groups.items():
        send_email(
            subject_fn(loc),
            emails,
            text_fn(loc),
            html_body=html_fn(loc) if html_fn else None,
        )


def _obtener_destinatarios(evento_clave, obra_id=None, worker_id=None):
    """
    Función maestra que lee la Matriz de Configuración.
    Busca Admin, Jefe y Trabajador solo si están marcados (tick) en la BD.
    Sin filtros de silencio: si está tickado, se envía siempre.
    Devuelve usuarios únicos con email (para traducir por locale).
    """
    conf = ConfiguracionGlobal.query.filter_by(clave=evento_clave).first()
    if not conf or not conf.valor:
        return []  # Nadie suscrito a este evento

    suscritos = conf.valor.split(',')  # Ej: ['admin', 'jefe', 'trabajador']
    users = []

    if 'admin' in suscritos:
        users.extend(User.query.filter_by(role='admin', active=True).all())

    if 'jefe' in suscritos and obra_id:
        obra = Obra.query.get(obra_id)
        if obra and obra.jefe_obra_id:
            jefe = User.query.get(obra.jefe_obra_id)
            if jefe:
                users.append(jefe)

    if 'trabajador' in suscritos and worker_id:
        worker = User.query.get(worker_id)
        if worker:
            users.append(worker)

    seen = set()
    out = []
    for user in users:
        email = (getattr(user, 'email', None) or '').strip()
        if not email or email in seen:
            continue
        seen.add(email)
        out.append(user)
    return out

def notificar_nueva_solicitud(solicitud, solicitante_name):
    """Notifica la creación de una solicitud (Genérica o Concreta)"""
    from app.services.i18n_service import translate

    clave = 'email_sol_generica' if solicitud.tipo == 'GENERICA' else 'email_sol_concreta'
    destinatarios = _obtener_destinatarios(clave, obra_id=solicitud.obra_id, worker_id=solicitud.empleado_id)
    if not destinatarios:
        return

    obra = Obra.query.get(solicitud.obra_id)

    jefe = User.query.get(solicitud.requested_by_id)
    nombre_jefe = f"{jefe.name} {jefe.lastname}" if jefe else solicitante_name
    is_baja = getattr(solicitud, 'accion', '') == 'DESASIGNAR'
    worker = User.query.get(solicitud.empleado_id) if solicitud.tipo == 'CONCRETA' else None

    from app.services.solicitud_service import get_solicitud_notas
    notas = get_solicitud_notas(solicitud)
    fechas = (
        f"{solicitud.fecha_inicio.strftime('%d/%m/%Y')} "
        f"al {solicitud.fecha_fin.strftime('%d/%m/%Y')}"
    )

    def subject(loc):
        if is_baja:
            return translate(
                'NUEVA SOLICITUD DE BAJA DE PERSONAL - {obra}', loc, obra=obra.nombre
            )
        return translate('NUEVA SOLICITUD DE PERSONAL - {obra}', loc, obra=obra.nombre)

    def text(loc):
        tipo_solic = (
            translate('baja de personal', loc) if is_baja else translate('personal', loc)
        )
        cuerpo = translate(
            'El Jefe de Obra {nombre} ha creado una nueva solicitud de {tipo}.\n\n'
            'Obra: {obra}\n',
            loc,
            nombre=nombre_jefe,
            tipo=tipo_solic,
            obra=obra.nombre,
        )
        if solicitud.tipo == 'CONCRETA' and worker:
            cuerpo += translate(
                'Trabajador Solicitado: {name}\n',
                loc,
                name=f'{worker.name} {worker.lastname}',
            )
        else:
            cuerpo += translate(
                'Perfil Solicitado: {perfil} (Cant: {cant})\n',
                loc,
                perfil=solicitud.perfil_categoria,
                cant=solicitud.cantidad_solicitada,
            )
        cuerpo += translate('Fechas: {fechas}\n', loc, fechas=fechas)
        if notas:
            cuerpo += translate('\nNotas del solicitante:\n{notas}\n', loc, notas=notas)
        cuerpo += translate(
            '\nPor favor, entra en la plataforma para revisarla y gestionarla.',
            loc,
        )
        return cuerpo

    _send_localized(destinatarios, subject, text)

def notificar_resolucion_solicitud(solicitud, admin_name, worker_id=None):
    """Notifica cuando una solicitud cambia de estado (Aprobada, Denegada, etc.)"""
    from app.services.i18n_service import translate

    id_trabajador = solicitud.empleado_id or worker_id

    destinatarios = _obtener_destinatarios('email_sol_resuelta', obra_id=solicitud.obra_id, worker_id=id_trabajador)
    if not destinatarios:
        return

    obra = Obra.query.get(solicitud.obra_id) if solicitud.obra_id else None
    worker = User.query.get(id_trabajador) if id_trabajador else None

    def subject(loc):
        obra_nombre = obra.nombre if obra else translate('obra', loc)
        return translate(
            'Resolución de solicitud #{id} - {obra}',
            loc,
            id=solicitud.id,
            obra=obra_nombre,
        )

    def text(loc):
        obra_nombre = obra.nombre if obra else translate('obra', loc)
        cuerpo = translate(
            'La solicitud para la obra {obra} ha sido resuelta por {admin}.\n\n'
            'Estado: {estado}\n'
            'Acción solicitada: {accion}\n',
            loc,
            obra=obra_nombre,
            admin=admin_name,
            estado=solicitud.estado,
            accion=getattr(solicitud, 'accion', 'ASIGNAR'),
        )
        if worker:
            empresa = (
                worker.company_rel.nombre
                if worker.company_rel
                else translate('Sin empresa', loc)
            )
            cuerpo += translate(
                'Trabajador movido: {name}\nEmpresa: {empresa}\n',
                loc,
                name=f'{worker.name} {worker.lastname}',
                empresa=empresa,
            )
        if solicitud.fecha_inicio and solicitud.fecha_fin:
            cuerpo += translate(
                'Fechas: {inicio} al {fin}\n\n',
                loc,
                inicio=solicitud.fecha_inicio.strftime('%d/%m/%Y'),
                fin=solicitud.fecha_fin.strftime('%d/%m/%Y'),
            )
        cuerpo += translate('Revisa la plataforma para más detalles.', loc)
        return cuerpo

    _send_localized(destinatarios, subject, text)


def _clave_email_solicitud_vehiculo():
    """Config dedicada email_sol_vehiculo; si no existe, reutiliza email_sol_concreta."""
    conf = ConfiguracionGlobal.query.filter_by(clave='email_sol_vehiculo').first()
    if conf and conf.valor:
        return 'email_sol_vehiculo'
    return 'email_sol_concreta'


def notificar_nueva_solicitud_vehiculo(solicitud, solicitante_name):
    """Notifica la creación de una SolicitudVehiculo (espejo de personal concreta)."""
    from app.services.i18n_service import translate

    clave = _clave_email_solicitud_vehiculo()
    destinatarios = _obtener_destinatarios(clave, worker_id=solicitud.empleado_id)
    if not destinatarios:
        return

    jefe = User.query.get(solicitud.requested_by_id)
    nombre_jefe = f"{jefe.name} {jefe.lastname}" if jefe else solicitante_name
    is_baja = getattr(solicitud, 'accion', '') == 'DESASIGNAR'

    from app.models import Vehiculo
    veh = getattr(solicitud, 'vehiculo', None)
    if veh is None and solicitud.vehiculo_id:
        veh = Vehiculo.query.get(solicitud.vehiculo_id)
    worker = User.query.get(solicitud.empleado_id)
    fechas = (
        f"{solicitud.fecha_inicio.strftime('%d/%m/%Y')} "
        f"al {solicitud.fecha_fin.strftime('%d/%m/%Y')}"
    )
    notas = (getattr(solicitud, 'notas', None) or '').strip()

    def _veh_txt(loc):
        if veh:
            return veh.label()
        if solicitud.vehiculo_id:
            return translate('vehículo #{id}', loc, id=solicitud.vehiculo_id)
        return translate('cualquier', loc)

    def subject(loc):
        veh_txt = _veh_txt(loc)
        if is_baja:
            return translate(
                'NUEVA SOLICITUD DE BAJA DE VEHÍCULO - {veh}', loc, veh=veh_txt
            )
        return translate('NUEVA SOLICITUD DE VEHÍCULO - {veh}', loc, veh=veh_txt)

    def text(loc):
        tipo_solic = (
            translate('baja de vehículo', loc) if is_baja else translate('vehículo', loc)
        )
        veh_txt = _veh_txt(loc)
        cuerpo = translate(
            'El usuario {nombre} ha creado una nueva solicitud de {tipo}.\n\n'
            'Vehículo: {veh}\n',
            loc,
            nombre=nombre_jefe,
            tipo=tipo_solic,
            veh=veh_txt,
        )
        if worker:
            cuerpo += translate(
                'Trabajador: {name}\n',
                loc,
                name=f'{worker.name} {worker.lastname}',
            )
        cuerpo += translate('Fechas: {fechas}\n', loc, fechas=fechas)
        if notas:
            cuerpo += translate('\nNotas del solicitante:\n{notas}\n', loc, notas=notas)
        cuerpo += translate(
            '\nPor favor, entra en la plataforma para revisarla y gestionarla.',
            loc,
        )
        return cuerpo

    _send_localized(destinatarios, subject, text)


def notificar_resolucion_solicitud_vehiculo(solicitud, admin_name):
    """Notifica resolución de SolicitudVehiculo (aceptar/denegar)."""
    from app.services.i18n_service import translate

    destinatarios = _obtener_destinatarios(
        'email_sol_resuelta', worker_id=solicitud.empleado_id
    )
    conf = ConfiguracionGlobal.query.filter_by(clave='email_sol_resuelta').first()
    if conf and conf.valor and 'jefe' in conf.valor.split(','):
        requester = User.query.get(solicitud.requested_by_id)
        if requester and requester.email:
            emails = {(getattr(u, 'email', None) or '').strip() for u in destinatarios}
            if requester.email.strip() not in emails:
                destinatarios = list(destinatarios) + [requester]
    if not destinatarios:
        return

    from app.models import Vehiculo
    veh = getattr(solicitud, 'vehiculo', None)
    if veh is None and solicitud.vehiculo_id:
        veh = Vehiculo.query.get(solicitud.vehiculo_id)
    worker = User.query.get(solicitud.empleado_id)

    def _veh_txt(loc):
        if veh:
            return veh.label()
        if solicitud.vehiculo_id:
            return translate('vehículo #{id}', loc, id=solicitud.vehiculo_id)
        return '—'

    def subject(loc):
        return translate(
            'Resolución de solicitud de vehículo #{id} - {veh}',
            loc,
            id=solicitud.id,
            veh=_veh_txt(loc),
        )

    def text(loc):
        cuerpo = translate(
            'La solicitud de vehículo ha sido resuelta por {admin}.\n\n'
            'Estado: {estado}\n'
            'Acción solicitada: {accion}\n'
            'Vehículo: {veh}\n',
            loc,
            admin=admin_name,
            estado=solicitud.estado,
            accion=getattr(solicitud, 'accion', 'ASIGNAR'),
            veh=_veh_txt(loc),
        )
        if worker:
            cuerpo += translate(
                'Trabajador: {name}\n',
                loc,
                name=f'{worker.name} {worker.lastname}',
            )
        cuerpo += translate(
            'Fechas: {inicio} al {fin}\n\n'
            'Revisa la plataforma para más detalles.',
            loc,
            inicio=solicitud.fecha_inicio.strftime('%d/%m/%Y'),
            fin=solicitud.fecha_fin.strftime('%d/%m/%Y'),
        )
        return cuerpo

    _send_localized(destinatarios, subject, text)

def notificar_traslado_interno(jefe_name, worker, target_obra, dates, obras_origen=None):
    """Notifica cuando un Jefe mueve a un operario por custodia entre sus obras"""
    from app.services.i18n_service import translate

    destinatarios = _obtener_destinatarios('email_traslado', obra_id=target_obra.id, worker_id=worker.id)
    if not destinatarios:
        return

    jefe_obj = User.query.filter(User.name.like(f"%{jefe_name.split()[0]}%")).first()
    nombre_jefe_completo = f"{jefe_obj.name} {jefe_obj.lastname}" if jefe_obj else jefe_name
    worker_name = f'{worker.name} {worker.lastname}'

    def _fecha_str(loc):
        if len(dates) > 1:
            return translate(
                'Desde el {start} hasta el {end}',
                loc,
                start=min(dates).strftime('%d/%m/%Y'),
                end=max(dates).strftime('%d/%m/%Y'),
            )
        return translate('El {date}', loc, date=dates[0].strftime('%d/%m/%Y'))

    def subject(loc):
        if obras_origen:
            return translate(
                'Aviso: Traslado de Personal - {jefe}', loc, jefe=nombre_jefe_completo
            )
        return translate(
            'Aviso: Extensión de Personal - {jefe}', loc, jefe=nombre_jefe_completo
        )

    def text(loc):
        fecha_str = _fecha_str(loc)
        if obras_origen:
            return translate(
                'El Jefe de Obra {jefe} ha realizado un traslado entre sus obras.\n\n'
                'Trabajador movido: {worker}\n\n'
                'Obra origen: {origen}\n'
                'Fechas origen: {fechas}\n\n'
                'Obra Destino: {destino}\n'
                'Fechas: {fechas}\n\n'
                'Este movimiento ha sido auto-aprobado por el sistema ya que se disponía de custodia activa sobre el trabajador.',
                loc,
                jefe=nombre_jefe_completo,
                worker=worker_name,
                origen=', '.join(obras_origen),
                fechas=fecha_str,
                destino=target_obra.nombre,
            )
        return translate(
            'El Jefe de Obra {jefe} ha realizado una extensión de personal.\n\n'
            'Trabajador movido: {worker}\n'
            'Obra Destino: {destino}\n'
            'Fechas: {fechas}\n\n'
            'Este movimiento ha sido auto-aprobado por el sistema ya que se disponía de custodia activa sobre el trabajador.',
            loc,
            jefe=nombre_jefe_completo,
            worker=worker_name,
            destino=target_obra.nombre,
            fechas=fecha_str,
        )

    _send_localized(destinatarios, subject, text)

def notificar_movimiento_admin_a_jo(obra_id, worker_name, accion, fecha_str, admin_name):
    """Notifica cuando se asigna o desasigna personal directamente en el planificador"""
    from app.services.i18n_service import translate

    is_baja = 'desasignar' in accion.lower() or 'baja' in accion.lower()
    clave = 'email_desasignacion' if is_baja else 'email_asignacion'

    worker_id = None
    if worker_name:
        worker = User.query.filter(User.name.like(f"%{worker_name.split()[0]}%")).first()
        if worker:
            worker_id = worker.id

    destinatarios = _obtener_destinatarios(clave, obra_id=obra_id, worker_id=worker_id)
    if not destinatarios:
        return

    obra = Obra.query.get(obra_id)

    def subject(loc):
        return translate('Actualización de Personal - {obra}', loc, obra=obra.nombre)

    def text(loc):
        return translate(
            'El administrador {admin} ha realizado un movimiento en la obra ({obra}):\n\n'
            'Acción: {accion}\n'
            'Operario: {worker}\n'
            'Fecha/s afectada(s): {fechas}\n\n'
            'Revisa el planificador para ver los detalles.',
            loc,
            admin=admin_name,
            obra=obra.nombre,
            accion=accion.upper(),
            worker=worker_name,
            fechas=fecha_str,
        )

    _send_localized(destinatarios, subject, text)


def notificar_desvio_fichaje(registro):
    """
    Aviso inmediato a los jefes de la obra planificada y de la obra fichada.
    Si es el mismo jefe, un solo correo con ambos lados.
    """
    from app.services.i18n_service import translate
    from app.services.desvio_fichaje_service import es_desvio_plan_vs_real
    from app.utils.timezone_utils import format_time

    if not es_desvio_plan_vs_real(registro):
        return
    user = registro.user
    if not user:
        return
    obra_plan = registro.obra_planificada
    obra_real = registro.obra_real
    if not obra_plan or not obra_real:
        return

    worker_name = f'{user.name or ""} {user.lastname or ""}'.strip() or user.email
    fecha_txt = registro.fecha.strftime('%d/%m/%Y') if registro.fecha else '—'
    hora_txt = format_time(registro.check_in) if registro.check_in else '—'

    def _mail_jefe(jefe, *, rol_lado):
        if not jefe or not jefe.email or getattr(jefe, 'is_deleted', False):
            return
        if not getattr(jefe, 'active', True):
            return
        loc = _user_locale(jefe, bulk=True)
        if rol_lado == 'ambos':
            asunto = translate(
                'Desvío de fichaje: {worker} ({date})',
                loc,
                worker=worker_name,
                date=fecha_txt,
            )
            cuerpo = translate(
                'Hola {jefe},\n\n'
                '{worker} estaba planificado en «{plan}» y ha fichado a las {hora} '
                'en «{real}» ({date}).\n\n'
                'Como gestionas ambas obras, confirma el desvío en Auditoría de fichajes: '
                'libera la plaza del plan y acepta la entrada.\n',
                loc,
                jefe=jefe.name or '',
                worker=worker_name,
                plan=obra_plan.nombre,
                real=obra_real.nombre,
                hora=hora_txt,
                date=fecha_txt,
            )
        elif rol_lado == 'plan':
            asunto = translate(
                'No ha venido a tu obra: {worker} fichó en otra ({date})',
                loc,
                worker=worker_name,
                date=fecha_txt,
            )
            cuerpo = translate(
                'Hola {jefe},\n\n'
                '{worker} estaba planificado hoy en «{plan}», pero ha fichado a las {hora} '
                'en «{real}» ({date}).\n\n'
                'No es un “sin fichar”: está en otra obra. En Auditoría de fichajes puedes '
                'liberar su plaza en tu obra.\n',
                loc,
                jefe=jefe.name or '',
                worker=worker_name,
                plan=obra_plan.nombre,
                real=obra_real.nombre,
                hora=hora_txt,
                date=fecha_txt,
            )
        else:
            asunto = translate(
                'Entrada no planificada: {worker} en tu obra ({date})',
                loc,
                worker=worker_name,
                date=fecha_txt,
            )
            cuerpo = translate(
                'Hola {jefe},\n\n'
                '{worker} ha fichado a las {hora} en «{real}» sin estar planificado ahí '
                '({date}). Venía de «{plan}».\n\n'
                'En Auditoría de fichajes puedes aceptar la entrada en tu obra.\n',
                loc,
                jefe=jefe.name or '',
                worker=worker_name,
                plan=obra_plan.nombre,
                real=obra_real.nombre,
                hora=hora_txt,
                date=fecha_txt,
            )
        send_email(asunto, [jefe.email], cuerpo)

    jefe_plan = obra_plan.jefe_obra
    jefe_real = obra_real.jefe_obra
    if jefe_plan and jefe_real and jefe_plan.id == jefe_real.id:
        _mail_jefe(jefe_plan, rol_lado='ambos')
        return
    _mail_jefe(jefe_plan, rol_lado='plan')
    _mail_jefe(jefe_real, rol_lado='real')


def enviar_super_reporte_diario():
    """
    Sustituye a 'notificar_auditoria_diaria_0830'.
    Manda correos agrupados a JO y Admins sobre ausencias de HOY y paracaidistas/conflictos de AYER.
    """
    from app.utils.timezone_utils import today_local
    from app.services.fichaje_operario_service import tenant_muestra_auditoria_fichajes
    from app.services.tenant_modules import hora_corte_destinatario_ids

    if not tenant_muestra_auditoria_fichajes():
        return

    hoy = today_local()
    ayer = hoy - timedelta(days=1)

    def _falso_positivo_ausencia(reg):
        """Si ya fichó (aunque sea Paracaidista) o hay resolución, no es «no ha fichado»."""
        hermanos = RegistroFichaje.query.filter(
            RegistroFichaje.user_id == reg.user_id,
            RegistroFichaje.fecha == reg.fecha,
            RegistroFichaje.id != reg.id,
        ).all()
        for h in hermanos:
            est = h.estado or ''
            if h.obra_real_id or h.check_in or est.startswith('Resuelto') or est in (
                'Correcto', 'Correcto_Automatico', 'Cerrado_Multiobra',
                'Paracaidista', 'Conflicto',
            ):
                return True
        return False

    # 1. Ausencias tempranas de HOY (sin falsos positivos por semillas de sync)
    ausencias_hoy = [
        a for a in RegistroFichaje.query.filter_by(fecha=hoy, estado='Ausencia').all()
        if not _falso_positivo_ausencia(a)
    ] 
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
    # Destinatarios: los marcados en Ajustes. Si no hay lista, todos los admin (legado).
    dest_ids = hora_corte_destinatario_ids()
    if dest_ids:
        admin_users = [
            u for u in User.query.filter(
                User.id.in_(dest_ids),
                User.active.is_(True),
            ).all()
            if u.email and not getattr(u, 'is_deleted', False)
        ]
    else:
        admin_users = [a for a in User.query.filter_by(role='admin', active=True).all() if a.email]

    if admin_users:
        from app.services.i18n_service import translate
        from collections import defaultdict

        groups = defaultdict(list)
        for admin in admin_users:
            groups[_user_locale(admin, bulk=True)].append(admin.email)

        for loc, emails in groups.items():
            asunto_admin = translate(
                'Alerta de Fichajes Global ({date})',
                loc,
                date=hoy.strftime('%d/%m/%Y'),
            )
            html_admin = (
                '<div style="font-family: Arial, sans-serif; padding: 20px; color: #333;">'
                f'<h2 style="color: #1d4ed8;">{translate("Reporte de Presencia y Fichajes 📋", loc)}</h2>'
                f'<p>{translate("Resumen automático generado en la hora de corte de entrada.", loc)}</p>'
                '<h3 style="color: #dc2626; border-bottom: 1px solid #ddd; padding-bottom: 5px;">'
                f'{translate("Ausencias Detectadas HOY ({date}):", loc, date=hoy.strftime("%d/%m/%Y"))}'
                '</h3><ul>'
            )
            if ausencias_hoy:
                for a in ausencias_hoy:
                    obra_nom = (
                        a.obra_planificada.nombre
                        if a.obra_planificada
                        else translate('Obra Desconocida', loc)
                    )
                    html_admin += translate(
                        '<li><b>{name}</b> - Faltó en: {obra}</li>',
                        loc,
                        name=f'{a.user.name} {a.user.lastname}',
                        obra=obra_nom,
                    )
            else:
                html_admin += (
                    "<li><i style='color: green;'>"
                    f"{translate('Todo el personal planificado ha fichado.', loc)}"
                    "</i></li>"
                )

            html_admin += (
                '</ul>'
                '<h3 style="color: #f59e0b; border-bottom: 1px solid #ddd; padding-bottom: 5px; margin-top: 20px;">'
                f'{translate("Fichajes No Planificados AYER ({date}):", loc, date=ayer.strftime("%d/%m/%Y"))}'
                '</h3><ul>'
            )

            if conflictos_ayer:
                for c in conflictos_ayer:
                    obra_real = (
                        c.obra_real.nombre if c.obra_real else translate('Desconocida', loc)
                    )
                    obra_plan = (
                        c.obra_planificada.nombre
                        if c.obra_planificada
                        else translate('NINGUNA', loc)
                    )
                    html_admin += translate(
                        '<li><b>{name}</b> - Apareció en: {real} (Estaba planificado en: {plan})</li>',
                        loc,
                        name=f'{c.user.name} {c.user.lastname}',
                        real=obra_real,
                        plan=obra_plan,
                    )
            else:
                html_admin += (
                    "<li><i style='color: green;'>"
                    f"{translate('No hubo incidencias de paracaidistas ayer.', loc)}"
                    "</i></li>"
                )

            html_admin += "</ul></div>"
            send_email(
                asunto_admin,
                emails,
                translate('Contenido en HTML.', loc),
                html_body=html_admin,
            )

    # Correos por obra al jefe: solo si no hay lista explícita de destinatarios.
    if dest_ids:
        return

    # ==========================================
    # CORREOS ESPECÍFICOS PARA CADA JEFE DE OBRA
    # ==========================================
    obras_afectadas_ids = set(
        [a.obra_planificada_id for a in ausencias_hoy if a.obra_planificada_id] +
        [c.obra_real_id for c in conflictos_ayer if c.obra_real_id] +
        [c.obra_planificada_id for c in conflictos_ayer if c.obra_planificada_id]
    )
    
    for obra_id in obras_afectadas_ids:
        obra = Obra.query.get(obra_id)
        if not obra or not obra.jefe_obra or not obra.jefe_obra.email: continue
            
        aus_obra = [a for a in ausencias_hoy if a.obra_planificada_id == obra.id]
        con_obra_real = [c for c in conflictos_ayer if c.obra_real_id == obra.id]
        con_obra_plan = [
            c for c in conflictos_ayer
            if c.obra_planificada_id == obra.id and c.obra_real_id != obra.id
        ]

        from app.services.i18n_service import translate
        loc = _user_locale(obra.jefe_obra, bulk=True)
        asunto_jo = translate(
            'Alerta de Personal - {obra} ({date})',
            loc,
            obra=obra.nombre,
            date=hoy.strftime('%d/%m/%Y'),
        )

        html_jo = (
            '<div style="font-family: Arial, sans-serif; padding: 20px; color: #333;">'
            f'<h3>{translate("Hola {name},", loc, name=obra.jefe_obra.name)}</h3>'
            f'<p>{translate("Incidencias detectadas en tu obra <b>{obra}</b> en la hora de corte:", loc, obra=obra.nombre)}</p>'
        )

        if aus_obra:
            html_jo += (
                "<h4 style='color: #dc2626;'>"
                f"{translate('NO HAN FICHADO HOY ({date}):', loc, date=hoy.strftime('%d/%m/%Y'))}"
                "</h4><ul>"
            )
            for a in aus_obra:
                html_jo += f"<li>{a.user.name} {a.user.lastname}</li>"
            html_jo += "</ul>"

        if con_obra_real:
            html_jo += (
                "<h4 style='color: #f59e0b;'>"
                f"{translate('FICHARON AYER ({date}) SIN ESTAR PLANIFICADOS EN TU OBRA:', loc, date=ayer.strftime('%d/%m/%Y'))}"
                "</h4><ul>"
            )
            for c in con_obra_real:
                plan_nom = (
                    c.obra_planificada.nombre
                    if c.obra_planificada
                    else translate('NINGUNA', loc)
                )
                html_jo += translate(
                    '<li>{name} (venía de: {plan})</li>',
                    loc,
                    name=f'{c.user.name} {c.user.lastname}',
                    plan=plan_nom,
                )
            html_jo += "</ul>"

        if con_obra_plan:
            html_jo += (
                "<h4 style='color: #dc2626;'>"
                f"{translate('PLANIFICADOS EN TU OBRA QUE FICHARON AYER EN OTRA:', loc, date=ayer.strftime('%d/%m/%Y'))}"
                "</h4><ul>"
            )
            for c in con_obra_plan:
                real_nom = (
                    c.obra_real.nombre if c.obra_real else translate('Desconocida', loc)
                )
                html_jo += translate(
                    '<li>{name} (fichó en: {real})</li>',
                    loc,
                    name=f'{c.user.name} {c.user.lastname}',
                    real=real_nom,
                )
            html_jo += "</ul>"

        if not aus_obra and not con_obra_real and not con_obra_plan:
            continue

        html_jo += "</div>"

        send_email(
            asunto_jo,
            [obra.jefe_obra.email],
            translate('Contenido en HTML.', loc),
            html_body=html_jo,
        )