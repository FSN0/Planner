# app/services/demo_data_service.py
#
# Semilla de datos de ejemplo para trials self-serve.
# Cantidades configurables por env (DEMO_N_OBRAS, DEMO_N_EMPLEADOS, …).
#
# No guardamos la lista de IDs en configuracion_global (valor VARCHAR(255)):
# los datos demo se reconocen por marcadores al borrar.

import os
import random
from datetime import date, datetime, timedelta, time

from werkzeug.security import generate_password_hash

from app import db
from sqlalchemy import text

from app.models import (
    EVENTO_ENTRADA,
    EVENTO_SALIDA,
    ORIGEN_IMPORTACION,
    ROLE_JEFE,
    ROLE_OPERARIO,
    Asignacion,
    AsignacionVehiculo,
    AusenciaPlanificada,
    Company,
    FichajeEvento,
    LEAVE_SOURCE_MANUAL,
    LEAVE_STATUS_APROBADA,
    Obra,
    RegistroFichaje,
    Solicitud,
    SolicitudVehiculo,
    User,
    Vehiculo,
    generate_random_color,
)
from app.services.config_service import get_tenant_config, set_tenant_config
from app.services.core_assignment_service import CoreAssignmentService
from app.services.core_vehicle_assignment_service import CoreVehicleAssignmentService
from app.services.fichaje_ledger_service import proyectar_dia, registrar_evento
from app.services.fichaje_operario_service import CONFIG_FICHAJE_OPERARIO
from app.services.pin_auth_service import asignar_pin_explicito
from app.services.solicitud_service import build_comentarios_config
from app.utils.timezone_utils import local_to_utc

CONFIG_DEMO_ACTIVA = 'demo_data_activa'
CONFIG_DEMO_CLEARED = 'demo_data_cleared'

DEMO_EMAIL_SUFFIX = '@demo.signaplan'
DEMO_OBRA_PREFIX = 'DEMO-'
DEMO_MATRICULA_PREFIX = 'DEM'
DEMO_LEAVE_DESC = 'Demo SignaPlan'
DEMO_SUBCONTRATA_CODE = 'DEMO-SUB'

NOMBRES = [
    'Antonio', 'María', 'José', 'Carmen', 'Francisco', 'Ana', 'Manuel', 'Laura',
    'David', 'Elena', 'Javier', 'Lucía', 'Carlos', 'Sara', 'Miguel', 'Paula',
    'Pedro', 'Isabel', 'Luis', 'Marta', 'Ángel', 'Cristina', 'Rafael', 'Patricia',
    'Diego', 'Beatriz', 'Sergio', 'Nuria', 'Alberto', 'Rocío',
]
APELLIDOS = [
    'García', 'Rodríguez', 'González', 'Fernández', 'López', 'Martínez', 'Sánchez',
    'Pérez', 'Gómez', 'Martín', 'Jiménez', 'Ruiz', 'Hernández', 'Díaz', 'Moreno',
    'Muñoz', 'Álvarez', 'Romero', 'Alonso', 'Gutierrez',
]
OBRA_NOMBRES = [
    'Reforma Plaza Mayor', 'Nave industrial norte', 'Urbanización Los Olivos',
    'Colegio San Miguel', 'Viviendas Calle Sol', 'Polideportivo municipal',
    'Ampliación hospital', 'Parking centro', 'Centro comercial Este',
    'Chalet El Pinar', 'Oficinas Parque Tecnológico', 'Residencial Río',
]


def _env_int(name, default):
    raw = (os.environ.get(name) or '').strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def demo_cantidades():
    return {
        'obras': _env_int('DEMO_N_OBRAS', 10),
        'empleados': _env_int('DEMO_N_EMPLEADOS', 28),
        'externos': _env_int('DEMO_N_EXTERNOS', 4),
        'vehiculos': _env_int('DEMO_N_VEHICULOS', 5),
        'jefes': _env_int('DEMO_N_JEFES', 2),
        'dias_historial': _env_int('DEMO_N_DIAS', 14),
        'dias_flota': _env_int('DEMO_N_DIAS_FLOTA', 21),
    }


def ids_libres_tutorial(users, n=4):
    """Primeros del listado Libres (orden por nombre, como el tablero). El tutorial arrastra el primero."""
    ordered = sorted(
        users,
        key=lambda u: (
            (getattr(u, 'name', None) or ''),
            (getattr(u, 'lastname', None) or ''),
            getattr(u, 'id', 0) or 0,
        ),
    )
    return {u.id for u in ordered[:n]}


def ids_libres_tutorial(users, n=4):
    """Primeros del listado Libres (orden por nombre, como el tablero). El tutorial arrastra el primero."""
    ordered = sorted(
        users,
        key=lambda u: (
            (getattr(u, 'name', None) or ''),
            (getattr(u, 'lastname', None) or ''),
            getattr(u, 'id', 0) or 0,
        ),
    )
    return {u.id for u in ordered[:n]}


def demo_activa():
    return str(get_tenant_config(CONFIG_DEMO_ACTIVA, default='False')) == 'True'


def ensure_demo_for_onboarding(actor_user=None):
    """
    Si el alta no dejó ejemplos, sembrarlos al abrir el tablero.
    No vuelve a generarlos si el admin ya los quitó a propósito.
    """
    from flask import current_app, has_app_context
    from app.services.onboarding_service import necesita_onboarding, tenant_tiene_onboarding

    if not tenant_tiene_onboarding() or not necesita_onboarding():
        return False
    if demo_activa() or _demo_users():
        return False
    if str(get_tenant_config(CONFIG_DEMO_CLEARED, default='False')) == 'True':
        return False
    try:
        generar_datos_demo(actor_user=actor_user, activar_fichaje=True)
        return True
    except ValueError:
        return False
    except Exception:
        if has_app_context():
            current_app.logger.exception('No se pudieron generar datos de ejemplo al abrir el tablero')
        try:
            db.session.rollback()
        except Exception:
            pass
        return False


def _demo_users():
    return (
        User.query
        .filter(
            User.email.ilike(f'%{DEMO_EMAIL_SUFFIX}'),
            User.is_deleted.is_(False),
        )
        .all()
    )


def _demo_user_ids():
    return [u.id for u in _demo_users()]


def _daterange(inicio, fin):
    d = inicio
    while d <= fin:
        yield d
        d += timedelta(days=1)


def _crear_fichaje_ok(op, obra, dia, autor_id=None):
    """
    Escribe en el libro de eventos (fuente del registro de jornada) y proyecta
    RegistroFichaje (fuente de la auditoría operativa).
    """
    entrada_local = datetime.combine(dia, time(7, 30)) + timedelta(
        minutes=random.randint(0, 35)
    )
    salida_local = datetime.combine(dia, time(16, 0)) + timedelta(
        minutes=random.randint(0, 40)
    )
    if dia == date.today() and random.random() < 0.35:
        salida_local = None

    motivo = 'Datos de ejemplo SignaPlan'
    marca = {'demo': '1'}
    registrar_evento(
        user_id=op.id,
        tipo=EVENTO_ENTRADA,
        origen=ORIGEN_IMPORTACION,
        ocurrido_en=local_to_utc(entrada_local),
        fecha_laboral=dia,
        autor_id=autor_id or op.id,
        obra_id=obra.id,
        motivo=motivo,
        external_ids=marca,
    )
    if salida_local is not None:
        registrar_evento(
            user_id=op.id,
            tipo=EVENTO_SALIDA,
            origen=ORIGEN_IMPORTACION,
            ocurrido_en=local_to_utc(salida_local),
            fecha_laboral=dia,
            autor_id=autor_id or op.id,
            obra_id=obra.id,
            motivo=motivo,
            external_ids=marca,
        )

    reg = proyectar_dia(op.id, dia)
    if reg is not None:
        reg.obra_planificada_id = obra.id
        reg.estado = 'Correcto'
        db.session.flush()
    return reg


def _borrar_eventos_libro_demo(user_ids):
    """Quita del libro los eventos de la demo (requiere desproteger triggers)."""
    if not user_ids:
        return
    schema = db.session.execute(text('SELECT current_schema()')).scalar()
    if not schema or schema == 'public':
        return

    from app.ddl import desproteger_libro_fichajes, proteger_libro_fichajes

    desproteger_libro_fichajes(
        lambda sql: db.session.execute(text(sql)),
        schema,
    )
    try:
        FichajeEvento.query.filter(
            FichajeEvento.user_id.in_(user_ids)
        ).delete(synchronize_session=False)
        # Reencadenar lo que quede (si el admin fichó de verdad entre medias).
        restantes = (
            FichajeEvento.query
            .order_by(FichajeEvento.secuencia.asc(), FichajeEvento.id.asc())
            .all()
        )
        prev_hash = None
        for i, evento in enumerate(restantes, start=1):
            evento.secuencia = i
            evento.hash_previo = prev_hash
            evento.hash = evento.calcular_hash()
            prev_hash = evento.hash
        db.session.flush()
    finally:
        proteger_libro_fichajes(
            lambda sql: db.session.execute(text(sql)),
            schema,
        )


def generar_datos_demo(actor_user=None, activar_fichaje=None):
    if demo_activa():
        raise ValueError('Ya hay datos de ejemplo activos. Bórralos antes de generar otros.')
    if _demo_users():
        raise ValueError(
            'Quedan restos de una demo anterior. Usa «Borrar datos de ejemplo» '
            'o contacta con soporte.'
        )

    qty = demo_cantidades()
    autor_id = actor_user.id if actor_user else None
    hoy = date.today()

    company = Company.query.filter_by(is_internal=True).first()
    if not company:
        company = Company(
            nombre='Empresa demo',
            code='DEMO',
            is_internal=True,
            nif='B00000000',
            color=generate_random_color(),
        )
        db.session.add(company)
        db.session.flush()
    elif not company.color or company.color.lower() in ('#ffffff', '#fff', ''):
        company.color = generate_random_color()

    subcontrata = Company(
        nombre='Electricidad Norte Demo S.L.',
        code=DEMO_SUBCONTRATA_CODE,
        is_internal=False,
        nif='B99887766',
        gremio='Electricidad',
        color=generate_random_color(),
    )
    db.session.add(subcontrata)
    db.session.flush()

    jefes = []
    for i in range(qty['jefes']):
        jefe = User(
            email=f'jefe.demo{i + 1}{DEMO_EMAIL_SUFFIX}',
            password_hash=generate_password_hash('demo1234'),
            role=ROLE_JEFE,
            name=NOMBRES[i % len(NOMBRES)],
            lastname=APELLIDOS[i % len(APELLIDOS)],
            dni=f'DJ{10000000 + i}',
            company_id=company.id,
            active=True,
            email_verified=True,
            web_access=True,
        )
        db.session.add(jefe)
        db.session.flush()
        asignar_pin_explicito(jefe, '1357', notify=False)
        jefes.append(jefe)

    operarios = []
    for i in range(qty['empleados']):
        op = User(
            email=f'operario.demo{i + 1}{DEMO_EMAIL_SUFFIX}',
            password_hash=generate_password_hash('demo1234'),
            role=ROLE_OPERARIO,
            name=NOMBRES[(i + 3) % len(NOMBRES)],
            lastname=APELLIDOS[(i + 5) % len(APELLIDOS)],
            dni=f'DO{20000000 + i}',
            company_id=company.id,
            active=True,
            email_verified=True,
            web_access=True,
            categoria_profesional=random.choice(['Oficial 1ª', 'Oficial 2ª', 'Peón']),
        )
        db.session.add(op)
        db.session.flush()
        asignar_pin_explicito(op, '2468', notify=False)
        operarios.append(op)

    externos = []
    for i in range(qty['externos']):
        ex = User(
            email=f'externo.demo{i + 1}{DEMO_EMAIL_SUFFIX}',
            password_hash=generate_password_hash('demo1234'),
            role=ROLE_OPERARIO,
            name=NOMBRES[(i + 11) % len(NOMBRES)],
            lastname=APELLIDOS[(i + 7) % len(APELLIDOS)],
            dni=f'DE{30000000 + i}',
            company_id=subcontrata.id,
            active=True,
            email_verified=True,
            web_access=False,
            categoria_profesional='Oficial 1ª',
            especialidad='Electricista',
        )
        db.session.add(ex)
        db.session.flush()
        asignar_pin_explicito(ex, '2468', notify=False)
        externos.append(ex)

    plantilla = operarios + externos
    # El tutorial pide arrastrar el primer chip de Libres: esos no pueden estar
    # de vacaciones hoy ni asignados a una obra (si no sale el modal de ausencia).
    ids_libres_tutorial_hoy = ids_libres_tutorial(plantilla, 4)

    obras = []
    for i in range(qty['obras']):
        jefe = jefes[i % len(jefes)] if jefes else None
        base = OBRA_NOMBRES[i % len(OBRA_NOMBRES)]
        obra = Obra(
            nombre=base if i < len(OBRA_NOMBRES) else f'{base} {i + 1}',
            codigo=f'{DEMO_OBRA_PREFIX}{i + 1:02d}',
            estado='En Curso',
            jefe_obra_id=jefe.id if jefe else None,
            fecha_inicio=hoy - timedelta(days=30),
            color=generate_random_color(),
        )
        db.session.add(obra)
        db.session.flush()
        obras.append(obra)

    vehiculos = []
    for i in range(qty['vehiculos']):
        v = Vehiculo(
            nombre=f'Furgoneta demo {i + 1}',
            matricula=f'{DEMO_MATRICULA_PREFIX}{i + 1:03d}',
            marca='Demo',
            modelo=f'M{i + 1}',
            active=True,
        )
        db.session.add(v)
        db.session.flush()
        vehiculos.append(v)

    # Vacaciones que CUBREN hoy (2–4 personas), nunca sobre los Libres del tutorial.
    de_vacaciones = {}  # user_id -> (ini, fin)
    pool_vac_hoy = [o for o in operarios if o.id not in ids_libres_tutorial_hoy]
    n_vac_hoy = min(3, max(1, len(pool_vac_hoy) // 8))
    for op in random.sample(pool_vac_hoy, k=min(n_vac_hoy, len(pool_vac_hoy))):
        ini = hoy - timedelta(days=random.randint(1, 3))
        fin = hoy + timedelta(days=random.randint(2, 6))
        leave = AusenciaPlanificada(
            user_id=op.id,
            fecha_inicio=ini,
            fecha_fin=fin,
            dias=(fin - ini).days + 1,
            tipo='Vacaciones',
            estado=LEAVE_STATUS_APROBADA,
            origen=LEAVE_SOURCE_MANUAL,
            descripcion=DEMO_LEAVE_DESC,
            created_by_id=autor_id,
        )
        db.session.add(leave)
        db.session.flush()
        de_vacaciones[op.id] = (ini, fin)

    # Vacaciones futuras (además)
    candidatos_futuro = [o for o in operarios if o.id not in de_vacaciones]
    for op in random.sample(candidatos_futuro, k=min(3, len(candidatos_futuro))):
        ini = hoy + timedelta(days=random.randint(10, 25))
        fin = ini + timedelta(days=random.randint(3, 8))
        leave = AusenciaPlanificada(
            user_id=op.id,
            fecha_inicio=ini,
            fecha_fin=fin,
            dias=(fin - ini).days + 1,
            tipo='Vacaciones',
            estado=LEAVE_STATUS_APROBADA,
            origen=LEAVE_SOURCE_MANUAL,
            descripcion=DEMO_LEAVE_DESC,
            created_by_id=autor_id,
        )
        db.session.add(leave)
        db.session.flush()

    def _en_vacaciones(user_id, dia):
        rango = de_vacaciones.get(user_id)
        return bool(rango and rango[0] <= dia <= rango[1])

    # Asignaciones + fichajes (pasados y hoy).
    # Tope por obra/día para que el calendario no se hinche (el tutorial pide arrastrar).
    max_por_obra_dia = 4
    ocupacion = {}
    # Asignaciones + fichajes (pasados y hoy)
    for d_offset in range(qty['dias_historial']):
        dia = hoy - timedelta(days=d_offset)
        if dia.weekday() >= 5:
            continue
        obras_ciclo = list(obras)
        random.shuffle(obras_ciclo)
        cursor = 0
        for op in plantilla:
            if _en_vacaciones(op.id, dia):
                continue
            if dia == hoy and op.id in ids_libres_tutorial_hoy:
                continue
            if random.random() < 0.28:
                continue
            obra = None
            for intento in range(len(obras_ciclo)):
                candidata = obras_ciclo[(cursor + intento) % len(obras_ciclo)]
                clave = (candidata.id, dia)
                if ocupacion.get(clave, 0) >= max_por_obra_dia:
                    continue
                obra = candidata
                cursor = (cursor + intento + 1) % len(obras_ciclo)
                break
            if obra is None:
                continue
            try:
                with db.session.begin_nested():
                    CoreAssignmentService.asignar(
                        op.id, obra.id, dia, autor_id, 'demo',
                        registrar_log=True,
                    )
                clave = (obra.id, dia)
                ocupacion[clave] = ocupacion.get(clave, 0) + 1
            except Exception:
                continue

            # ~70% fichan (hoy incluido). El resto queda sin registro → auditoría.
            if random.random() < 0.70:
                try:
                    with db.session.begin_nested():
                        _crear_fichaje_ok(op, obra, dia, autor_id=autor_id)
                except Exception:
                    continue
            elif d_offset == 0:
                try:
                    with db.session.begin_nested():
                        reg = RegistroFichaje(
                            user_id=op.id,
                            fecha=dia,
                            obra_planificada_id=obra.id,
                            estado='Ausencia',
                        )
                        db.session.add(reg)
                        db.session.flush()
                except Exception:
                    continue

    # Flota: varios días hacia adelante (y algo atrás) para que no todo esté libre
    for i, v in enumerate(vehiculos):
        if i >= len(operarios):
            break
        if i < max(2, len(vehiculos) - 1):
            inicio = hoy - timedelta(days=2)
            fin = hoy + timedelta(days=qty['dias_flota'])
        else:
            inicio = hoy
            fin = hoy + timedelta(days=2)
        conductor = operarios[i]
        for dia in _daterange(inicio, fin):
            if dia.weekday() >= 5:
                continue
            if _en_vacaciones(conductor.id, dia):
                continue
            try:
                with db.session.begin_nested():
                    CoreVehicleAssignmentService.asignar(
                        v.id, conductor.id, dia, autor_id, 'demo',
                        registrar_log=False,
                    )
            except Exception:
                continue

    # Solicitudes de personal (pendientes) creadas por jefes
    if jefes and obras and operarios:
        jefe = jefes[0]
        obra_a = obras[0]
        obra_b = obras[1] if len(obras) > 1 else obras[0]
        libre = next((o for o in operarios if o.id not in de_vacaciones), operarios[0])

        db.session.add(Solicitud(
            tipo='CONCRETA',
            accion='ASIGNAR',
            obra_id=obra_a.id,
            requested_by_id=jefe.id,
            empleado_id=libre.id,
            fecha_inicio=hoy + timedelta(days=1),
            fecha_fin=hoy + timedelta(days=5),
            cantidad_solicitada=1,
            estado='PENDIENTE',
            notas='Demo: necesitamos a esta persona la semana que viene.',
        ))
        db.session.add(Solicitud(
            tipo='GENERICA',
            accion='ASIGNAR',
            obra_id=obra_b.id,
            requested_by_id=jefe.id,
            fecha_inicio=hoy + timedelta(days=2),
            fecha_fin=hoy + timedelta(days=10),
            perfil_categoria='Oficial 1ª',
            cantidad_solicitada=2,
            estado='PENDIENTE',
            notas='Demo: faltan dos oficiales para el tajo.',
        ))

        # DESASIGNAR solo tiene sentido si el operario está asignado esos días.
        candidato_baja = next(
            (o for o in reversed(operarios) if o.id not in de_vacaciones and o.id != libre.id),
            None,
        )
        if candidato_baja is None:
            candidato_baja = libre
        fechas_baja = []
        for d_off in range(1, 8):
            dia = hoy + timedelta(days=d_off)
            if dia.weekday() >= 5:
                continue
            try:
                with db.session.begin_nested():
                    CoreAssignmentService.asignar(
                        candidato_baja.id, obra_a.id, dia, autor_id, 'demo',
                        registrar_log=True,
                    )
                fechas_baja.append(dia)
            except Exception:
                continue
        if fechas_baja:
            db.session.add(Solicitud(
                tipo='CONCRETA',
                accion='DESASIGNAR',
                obra_id=obra_a.id,
                requested_by_id=jefes[-1].id,
                empleado_id=candidato_baja.id,
                fecha_inicio=min(fechas_baja),
                fecha_fin=max(fechas_baja),
                cantidad_solicitada=1,
                estado='PENDIENTE',
                comentarios=build_comentarios_config(fechas_baja),
                notas='Demo: baja solicitada por el jefe (sí está asignado).',
            ))

        if vehiculos and len(operarios) > 2:
            db.session.add(SolicitudVehiculo(
                accion='ASIGNAR',
                requested_by_id=jefe.id,
                empleado_id=operarios[2].id,
                vehiculo_id=vehiculos[-1].id,
                fecha_inicio=hoy + timedelta(days=1),
                fecha_fin=hoy + timedelta(days=4),
                estado='PENDIENTE',
                notas='Demo: necesita furgoneta para el desplazamiento.',
            ))
        db.session.flush()

    if activar_fichaje is None:
        from app.services.fichaje_operario_service import fichaje_operario_activo
        activo_fichaje = bool(fichaje_operario_activo())
    else:
        activo_fichaje = bool(activar_fichaje)
    set_tenant_config(CONFIG_FICHAJE_OPERARIO, 'True' if activo_fichaje else 'False')
    try:
        from app.services.fichaje_operario_service import marcar_fichaje_preferencia_decidida
        marcar_fichaje_preferencia_decidida()
    except Exception:
        pass
    set_tenant_config(CONFIG_DEMO_ACTIVA, 'True')
    return qty


def borrar_datos_demo():
    """
    Elimina datos reconocibles como demo.
    También limpia restos aunque el flag estuviera a medias por un fallo previo.
    """
    user_ids = _demo_user_ids()
    obra_ids = [
        o.id for o in Obra.query.filter(Obra.codigo.ilike(f'{DEMO_OBRA_PREFIX}%')).all()
    ]
    vehiculo_ids = [
        v.id for v in Vehiculo.query.filter(
            Vehiculo.matricula.ilike(f'{DEMO_MATRICULA_PREFIX}%')
        ).all()
    ]

    if not user_ids and not obra_ids and not vehiculo_ids and not demo_activa():
        raise ValueError('No hay datos de ejemplo que borrar.')

    if user_ids:
        SolicitudVehiculo.query.filter(
            SolicitudVehiculo.empleado_id.in_(user_ids)
        ).delete(synchronize_session=False)
        SolicitudVehiculo.query.filter(
            SolicitudVehiculo.requested_by_id.in_(user_ids)
        ).delete(synchronize_session=False)
        Solicitud.query.filter(
            Solicitud.empleado_id.in_(user_ids)
        ).delete(synchronize_session=False)
        Solicitud.query.filter(
            Solicitud.requested_by_id.in_(user_ids)
        ).delete(synchronize_session=False)
        AsignacionVehiculo.query.filter(
            AsignacionVehiculo.user_id.in_(user_ids)
        ).delete(synchronize_session=False)
        Asignacion.query.filter(
            Asignacion.user_id.in_(user_ids)
        ).delete(synchronize_session=False)
        RegistroFichaje.query.filter(
            RegistroFichaje.user_id.in_(user_ids)
        ).delete(synchronize_session=False)
        AusenciaPlanificada.query.filter(
            AusenciaPlanificada.user_id.in_(user_ids)
        ).delete(synchronize_session=False)
        _borrar_eventos_libro_demo(user_ids)

    if obra_ids:
        Solicitud.query.filter(Solicitud.obra_id.in_(obra_ids)).delete(
            synchronize_session=False
        )
        Asignacion.query.filter(Asignacion.obra_id.in_(obra_ids)).delete(
            synchronize_session=False
        )
        for obra in Obra.query.filter(Obra.id.in_(obra_ids)).all():
            obra.is_deleted = True

    if vehiculo_ids:
        SolicitudVehiculo.query.filter(
            SolicitudVehiculo.vehiculo_id.in_(vehiculo_ids)
        ).delete(synchronize_session=False)
        AsignacionVehiculo.query.filter(
            AsignacionVehiculo.vehiculo_id.in_(vehiculo_ids)
        ).delete(synchronize_session=False)
        Vehiculo.query.filter(Vehiculo.id.in_(vehiculo_ids)).delete(
            synchronize_session=False
        )

    for u in _demo_users():
        if u.role != 'admin':
            u.soft_delete()

    AusenciaPlanificada.query.filter_by(descripcion=DEMO_LEAVE_DESC).delete(
        synchronize_session=False
    )

    sub = Company.query.filter_by(code=DEMO_SUBCONTRATA_CODE).first()
    if sub:
        db.session.delete(sub)

    set_tenant_config(CONFIG_DEMO_ACTIVA, 'False')
    set_tenant_config(CONFIG_DEMO_CLEARED, 'True')
    stale = get_tenant_config('demo_data_ids', default=None)
    if stale is not None:
        from app.models import ConfiguracionGlobal
        row = ConfiguracionGlobal.query.filter_by(clave='demo_data_ids').first()
        if row:
            db.session.delete(row)
            db.session.commit()
    return True
