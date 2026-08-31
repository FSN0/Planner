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
    ORIGEN_PWA,
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
    SystemLog,
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
from app.utils.timezone_utils import format_time, local_to_utc

CONFIG_DEMO_ACTIVA = 'demo_data_activa'
CONFIG_DEMO_CLEARED = 'demo_data_cleared'

ORIGEN_PLAN_MANUAL = 'Planificación Manual'

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


SEED_PASSWORD = 'obra2026'
SEED_PIN_OPERARIO = '2468'
SEED_PIN_JEFE = '1357'

SEED_QTY_CAPS = {
    'obras': 80,
    'empleados': 200,
    'externos': 40,
    'vehiculos': 40,
    'jefes': 15,
    'dias_historial': 60,
    'dias_flota': 45,
    'solicitudes': 20,
}

_MATRICULA_LETRAS = 'BCDFGHJKLMNPRSTVWXYZ'


def _env_int(name, default, minimum=1):
    raw = (os.environ.get(name) or '').strip()
    if not raw:
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        return default


def demo_cantidades():
    """Cantidades del tutorial / semilla. También son los defaults del superadmin."""
    return {
        'obras': _env_int('DEMO_N_OBRAS', 10),
        'empleados': _env_int('DEMO_N_EMPLEADOS', 28),
        'externos': _env_int('DEMO_N_EXTERNOS', 4),
        'vehiculos': _env_int('DEMO_N_VEHICULOS', 5),
        'jefes': _env_int('DEMO_N_JEFES', 2),
        'dias_historial': _env_int('DEMO_N_DIAS', 14),  # ±N días laborables desde hoy
        'dias_flota': _env_int('DEMO_N_DIAS_FLOTA', 21),
        'solicitudes': _env_int('DEMO_N_SOLICITUDES', 3, minimum=0),
    }


def cantidades_desde_formulario(form):
    """Lee n_obras / obras / etc. del form de superadmin. Vacío = default tutorial."""
    base = demo_cantidades()
    if not form:
        return base
    out = dict(base)
    aliases = {
        'obras': ('obras', 'n_obras'),
        'empleados': ('empleados', 'n_empleados', 'n_gente'),
        'externos': ('externos', 'n_externos'),
        'vehiculos': ('vehiculos', 'n_vehiculos'),
        'jefes': ('jefes', 'n_jefes'),
        'dias_historial': ('dias_historial', 'n_dias'),
        'dias_flota': ('dias_flota', 'n_dias_flota'),
        'solicitudes': ('solicitudes', 'n_solicitudes'),
    }
    for key, names in aliases.items():
        raw = None
        for name in names:
            if form.get(name) not in (None, ''):
                raw = form.get(name)
                break
        if raw is None:
            continue
        try:
            n = int(str(raw).strip())
        except (TypeError, ValueError):
            continue
        lo = 0 if key in ('externos', 'solicitudes', 'vehiculos') else 1
        cap = SEED_QTY_CAPS.get(key, 100)
        out[key] = max(lo, min(cap, n))
    if out['obras'] < 1:
        out['obras'] = 1
    if out['empleados'] < 1:
        out['empleados'] = 1
    if out['jefes'] < 1:
        out['jefes'] = 1
    return out


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


def _tenant_slug():
    from flask import g, has_app_context

    tenant = getattr(g, 'current_tenant', None) if has_app_context() else None
    raw = (getattr(tenant, 'subdominio', None) or 'empresa').lower()
    slug = ''.join(ch for ch in raw if ch.isalnum())[:18]
    return slug or 'empresa'


def _matricula_semilla(indice):
    n = 1000 + (indice % 9000)
    a = _MATRICULA_LETRAS[indice % len(_MATRICULA_LETRAS)]
    b = _MATRICULA_LETRAS[(indice * 3) % len(_MATRICULA_LETRAS)]
    c = _MATRICULA_LETRAS[(indice * 7) % len(_MATRICULA_LETRAS)]
    return f'{n:04d}{a}{b}{c}'


def _email_unico(local_part):
    slug = _tenant_slug()
    candidate = f'{local_part}@{slug}.local'
    n = 1
    while User.query.filter_by(email=candidate).first():
        n += 1
        candidate = f'{local_part}{n}@{slug}.local'
    return candidate


def _dni_unico(prefix, indice):
    base = abs(indice) % 90_000_000
    for extra in range(50):
        dni = f'{prefix}{base + extra:08d}'
        if not User.query.filter_by(dni=dni).first():
            return dni
    return f'{prefix}{base:08d}{indice}'


def _codigo_obra_unico(indice, marcar_demo):
    prefix = DEMO_OBRA_PREFIX if marcar_demo else 'OB-'
    for extra in range(80):
        codigo = f'{prefix}{indice + extra:02d}'
        if not Obra.query.filter_by(codigo=codigo).first():
            return codigo
    return f'{prefix}{indice:02d}-{_tenant_slug()}'


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


def _autor_planificacion_obra(obra, jefes, fallback_id):
    """Quien planifica en la semilla realista: jefe de la obra si hay."""
    if obra and getattr(obra, 'jefe_obra_id', None):
        return obra.jefe_obra_id
    if jefes:
        return jefes[0].id
    return fallback_id


def _format_fichaje_app_detail(
    obra_label,
    entrada_local,
    salida_local,
    obra_plan_label=None,
    estado=None,
):
    entrada_utc = local_to_utc(entrada_local)
    salida_utc = local_to_utc(salida_local) if salida_local else None
    if estado == 'Conflicto' and obra_plan_label and obra_plan_label != obra_label:
        intro = (
            f'El operario fichó en {obra_label} '
            f'(tenía planificado en {obra_plan_label}).'
        )
    elif estado == 'Paracaidista':
        intro = f'El operario fichó en {obra_label} sin planificación en esa obra.'
    else:
        intro = f'El operario fichó en {obra_label}.'
    return (
        f'{intro} '
        f'Entrada: {format_time(entrada_utc) if entrada_utc else "-"} / '
        f'Salida: {format_time(salida_utc) if salida_utc else "-"}'
    )


def _retroceder_log_planificacion(user_id, dia, hora_local=None):
    """En semilla realista, el log no debe quedar con timestamp de «ahora»."""
    log = (
        SystemLog.query
        .filter_by(target_user_id=user_id, target_date=dia, category='planificacion')
        .filter(SystemLog.detail.like('Asignado%'))
        .order_by(SystemLog.id.desc())
        .first()
    )
    if not log:
        return
    hh = hora_local or time(6, random.randint(15, 50))
    log.timestamp = local_to_utc(datetime.combine(dia, hh))


def _retroceder_log_vehiculo(user_id, dia, offset_minutes=2):
    """El vehículo debe quedar planificado junto al operario, no tras el fichaje."""
    veh_log = (
        SystemLog.query
        .filter_by(target_user_id=user_id, target_date=dia, category='planificacion')
        .filter(SystemLog.detail.like('Vehículo%'))
        .order_by(SystemLog.id.desc())
        .first()
    )
    if not veh_log:
        return
    plan_log = (
        SystemLog.query
        .filter_by(target_user_id=user_id, target_date=dia, category='planificacion')
        .filter(SystemLog.detail.like('Asignado%'))
        .order_by(SystemLog.id.desc())
        .first()
    )
    if plan_log:
        veh_log.timestamp = plan_log.timestamp + timedelta(minutes=offset_minutes)
    else:
        veh_log.timestamp = local_to_utc(datetime.combine(dia, time(6, 32)))


def _registrar_log_fichaje_app(
    op, dia, obra_fichaje, entrada_local, salida_local, estado, obra_plan=None,
):
    obra_label = CoreAssignmentService.format_obra_label(obra_fichaje)
    obra_plan_label = (
        CoreAssignmentService.format_obra_label(obra_plan)
        if obra_plan
        else None
    )
    entrada_utc = local_to_utc(entrada_local)
    db.session.add(SystemLog(
        timestamp=entrada_utc,
        category='fichaje_app',
        action=f"Fichaje físico [{estado.replace('_', ' ')}]",
        detail=_format_fichaje_app_detail(
            obra_label,
            entrada_local,
            salida_local,
            obra_plan_label=obra_plan_label,
            estado=estado,
        ),
        target_user_id=op.id,
        target_date=dia,
    ))


def _crear_fichaje_ok(
    op,
    obra_plan,
    dia,
    autor_id=None,
    marcar_demo=True,
    obra_real=None,
    estado='Correcto',
):
    """
    Escribe en el libro de eventos y proyecta RegistroFichaje.

    marcar_demo=False: flujo natural (plan manual + fichaje en app).
    """
    obra_fichaje = obra_real or obra_plan
    entrada_local = datetime.combine(dia, time(7, 30)) + timedelta(
        minutes=random.randint(0, 35)
    )
    salida_local = datetime.combine(dia, time(16, 0)) + timedelta(
        minutes=random.randint(0, 40)
    )
    if dia == date.today() and random.random() < 0.35:
        salida_local = None

    if marcar_demo:
        origen = ORIGEN_IMPORTACION
        motivo = 'Datos de ejemplo SignaPlan'
        marca = {'demo': '1'}
        fichaje_autor = autor_id or op.id
    else:
        origen = ORIGEN_PWA
        motivo = None
        marca = None
        fichaje_autor = op.id

    registrar_evento(
        user_id=op.id,
        tipo=EVENTO_ENTRADA,
        origen=origen,
        ocurrido_en=local_to_utc(entrada_local),
        fecha_laboral=dia,
        autor_id=fichaje_autor,
        obra_id=obra_fichaje.id,
        motivo=motivo,
        external_ids=marca,
    )
    if salida_local is not None:
        registrar_evento(
            user_id=op.id,
            tipo=EVENTO_SALIDA,
            origen=origen,
            ocurrido_en=local_to_utc(salida_local),
            fecha_laboral=dia,
            autor_id=fichaje_autor,
            obra_id=obra_fichaje.id,
            motivo=motivo,
            external_ids=marca,
        )

    reg = proyectar_dia(op.id, dia)
    if reg is not None:
        reg.obra_planificada_id = obra_plan.id
        reg.obra_real_id = obra_fichaje.id
        reg.estado = estado
        db.session.flush()

    if not marcar_demo and reg is not None:
        _registrar_log_fichaje_app(
            op, dia, obra_fichaje, entrada_local, salida_local, reg.estado,
            obra_plan=obra_plan,
        )
    return reg


def _elegir_obra_distinta(obra, obras):
    candidatas = [o for o in obras if o.id != obra.id]
    if not candidatas:
        return None
    return random.choice(candidatas)


def _iter_dias_laborables_planificacion(hoy, dias_horizonte):
    """Días laborables desde hoy-dias_horizonte hasta hoy+dias_horizonte (orden cronológico)."""
    for d_offset in range(dias_horizonte, -dias_horizonte - 1, -1):
        dia = hoy - timedelta(days=d_offset)
        if dia.weekday() < 5:
            yield dia, d_offset


class _EstadoContinuidadAsignacion:
    """
    Elige obra con bloques de varios días en la misma obra y algún salto puntual.
    """

    def __init__(self, obras, max_por_obra_dia=4):
        self.obras = list(obras)
        self.max_por_obra_dia = max_por_obra_dia
        self.ocupacion = {}
        self.obra_actual = {}
        self.obra_anterior = {}
        self.streak = {}
        self.block_target = {}

    def _candidatas(self, dia):
        out = []
        for obra in self.obras:
            if self.ocupacion.get((obra.id, dia), 0) < self.max_por_obra_dia:
                out.append(obra)
        return out

    def _asignar_obra(self, user_id, nueva, actual):
        if actual and actual.id != nueva.id:
            self.obra_anterior[user_id] = actual
        if self.obra_actual.get(user_id) is not nueva:
            self.block_target[user_id] = random.randint(3, 8)
            self.streak[user_id] = 0
        self.obra_actual[user_id] = nueva
        return nueva

    def elegir(self, user_id, dia, prob_trabaja=0.78):
        if random.random() > prob_trabaja:
            return None
        candidatas = self._candidatas(dia)
        if not candidatas:
            return None

        actual = self.obra_actual.get(user_id)
        prev = self.obra_anterior.get(user_id)
        streak = self.streak.get(user_id, 0)
        candidatas_ids = {o.id for o in candidatas}

        if actual and actual.id in candidatas_ids:
            target = self.block_target.get(user_id, 5)
            if streak < target and random.random() < 0.90:
                return actual

        if prev and prev.id in candidatas_ids and random.random() < 0.50:
            return self._asignar_obra(user_id, prev, actual)

        pool = [o for o in candidatas if actual is None or o.id != actual.id]
        if not pool:
            pool = candidatas
        return self._asignar_obra(user_id, random.choice(pool), actual)

    def confirmar(self, user_id, obra, dia):
        if self.obra_actual.get(user_id) is obra:
            self.streak[user_id] = self.streak.get(user_id, 0) + 1
        clave = (obra.id, dia)
        self.ocupacion[clave] = self.ocupacion.get(clave, 0) + 1


def _sembrar_fichaje_dia(op, obra, dia, marcar_demo, obras, d_offset):
    """Variedad de escenarios para que el tablero y el historial parezcan reales."""
    roll = random.random()
    if marcar_demo:
        if roll < 0.70:
            _crear_fichaje_ok(op, obra, dia, marcar_demo=True)
        elif d_offset == 0:
            db.session.add(RegistroFichaje(
                user_id=op.id,
                fecha=dia,
                obra_planificada_id=obra.id,
                estado='Ausencia',
            ))
            db.session.flush()
        return

    if d_offset == 0:
        if roll < 0.48:
            _crear_fichaje_ok(
                op, obra, dia, marcar_demo=False, estado='Correcto',
            )
        elif roll < 0.60:
            otra = _elegir_obra_distinta(obra, obras)
            if otra:
                _crear_fichaje_ok(
                    op, obra, dia, marcar_demo=False,
                    obra_real=otra, estado='Conflicto',
                )
            else:
                _crear_fichaje_ok(
                    op, obra, dia, marcar_demo=False, estado='Correcto',
                )
        elif roll < 0.74:
            pass
        else:
            db.session.add(RegistroFichaje(
                user_id=op.id,
                fecha=dia,
                obra_planificada_id=obra.id,
                estado='Ausencia',
            ))
            db.session.flush()
        return

    if roll < 0.64:
        _crear_fichaje_ok(op, obra, dia, marcar_demo=False, estado='Correcto')
    elif roll < 0.74:
        otra = _elegir_obra_distinta(obra, obras)
        if otra:
            _crear_fichaje_ok(
                op, obra, dia, marcar_demo=False,
                obra_real=otra, estado='Conflicto',
            )
        else:
            _crear_fichaje_ok(op, obra, dia, marcar_demo=False, estado='Correcto')
    elif roll < 0.82:
        db.session.add(RegistroFichaje(
            user_id=op.id,
            fecha=dia,
            obra_planificada_id=obra.id,
            estado='Ausencia',
        ))
        db.session.flush()


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


def generar_datos_demo(actor_user=None, activar_fichaje=None, qty=None, marcar_demo=True):
    """
    Rellena el tenant actual con obras, gente, flota, asignaciones, fichajes y
    solicitudes.

    marcar_demo=True: trial/tutorial (banner, emails @demo.signaplan, códigos DEMO-).
    marcar_demo=False: contenido de grabación / superadmin; parece una empresa real.
    """
    qty = dict(demo_cantidades() if qty is None else {**demo_cantidades(), **qty})
    if marcar_demo:
        if demo_activa():
            raise ValueError('Ya hay datos de ejemplo activos. Bórralos antes de generar otros.')
        if _demo_users():
            raise ValueError(
                'Quedan restos de una demo anterior. Usa «Borrar datos de ejemplo» '
                'o contacta con soporte.'
            )

    autor_id = actor_user.id if actor_user else None
    hoy = date.today()
    origen = 'demo' if marcar_demo else ORIGEN_PLAN_MANUAL
    offset = User.query.filter(User.is_deleted.is_(False)).count()
    password_hash = generate_password_hash('demo1234' if marcar_demo else SEED_PASSWORD)
    pin_jefe = SEED_PIN_JEFE
    pin_op = SEED_PIN_OPERARIO
    desc_baja = DEMO_LEAVE_DESC if marcar_demo else 'Vacaciones'

    company = Company.query.filter_by(is_internal=True).first()
    if not company:
        company = Company(
            nombre='Empresa demo' if marcar_demo else 'Empresa',
            code='DEMO' if marcar_demo else _tenant_slug()[:15].upper(),
            is_internal=True,
            nif='B00000000',
            color=generate_random_color(),
        )
        db.session.add(company)
        db.session.flush()
    elif not company.color or company.color.lower() in ('#ffffff', '#fff', ''):
        company.color = generate_random_color()

    sub_code = DEMO_SUBCONTRATA_CODE if marcar_demo else f'SUB-{_tenant_slug()[:8].upper()}'
    subcontrata = Company.query.filter_by(code=sub_code).first()
    if not subcontrata:
        subcontrata = Company.query.filter_by(is_internal=False).first() if not marcar_demo else None
    if not subcontrata and qty.get('externos', 0) > 0:
        subcontrata = Company(
            nombre='Electricidad Norte Demo S.L.' if marcar_demo else 'Electricidad Norte S.L.',
            code=sub_code,
            is_internal=False,
            nif='B99887766' if marcar_demo else 'B12345678',
            gremio='Electricidad',
            color=generate_random_color(),
        )
        db.session.add(subcontrata)
        db.session.flush()

    jefes = []
    for i in range(qty['jefes']):
        idx = offset + i
        jefe = User(
            email=(
                f'jefe.demo{i + 1}{DEMO_EMAIL_SUFFIX}'
                if marcar_demo else _email_unico(f'jefe{i + 1}')
            ),
            password_hash=password_hash,
            role=ROLE_JEFE,
            name=NOMBRES[idx % len(NOMBRES)],
            lastname=APELLIDOS[idx % len(APELLIDOS)],
            dni=_dni_unico('DJ', 10_000_000 + idx) if not marcar_demo else f'DJ{10000000 + i}',
            company_id=company.id,
            active=True,
            email_verified=True,
            web_access=True,
        )
        db.session.add(jefe)
        db.session.flush()
        asignar_pin_explicito(jefe, pin_jefe, notify=False)
        jefes.append(jefe)

    operarios = []
    for i in range(qty['empleados']):
        idx = offset + qty['jefes'] + i
        op = User(
            email=(
                f'operario.demo{i + 1}{DEMO_EMAIL_SUFFIX}'
                if marcar_demo else _email_unico(f'op{i + 1}')
            ),
            password_hash=password_hash,
            role=ROLE_OPERARIO,
            name=NOMBRES[(idx + 3) % len(NOMBRES)],
            lastname=APELLIDOS[(idx + 5) % len(APELLIDOS)],
            dni=_dni_unico('DO', 20_000_000 + idx) if not marcar_demo else f'DO{20000000 + i}',
            company_id=company.id,
            active=True,
            email_verified=True,
            web_access=True,
            categoria_profesional=random.choice(['Oficial 1ª', 'Oficial 2ª', 'Peón']),
        )
        db.session.add(op)
        db.session.flush()
        asignar_pin_explicito(op, pin_op, notify=False)
        operarios.append(op)

    externos = []
    n_ext = qty.get('externos', 0) if subcontrata else 0
    for i in range(n_ext):
        idx = offset + qty['jefes'] + qty['empleados'] + i
        ex = User(
            email=(
                f'externo.demo{i + 1}{DEMO_EMAIL_SUFFIX}'
                if marcar_demo else _email_unico(f'ext{i + 1}')
            ),
            password_hash=password_hash,
            role=ROLE_OPERARIO,
            name=NOMBRES[(idx + 11) % len(NOMBRES)],
            lastname=APELLIDOS[(idx + 7) % len(APELLIDOS)],
            dni=_dni_unico('DE', 30_000_000 + idx) if not marcar_demo else f'DE{30000000 + i}',
            company_id=subcontrata.id,
            active=True,
            email_verified=True,
            web_access=False,
            categoria_profesional='Oficial 1ª',
            especialidad='Electricista',
        )
        db.session.add(ex)
        db.session.flush()
        asignar_pin_explicito(ex, pin_op, notify=False)
        externos.append(ex)

    plantilla = operarios + externos
    # El tutorial pide arrastrar el primer chip de Libres: esos no pueden estar
    # de vacaciones hoy ni asignados a una obra (si no sale el modal de ausencia).
    ids_libres_tutorial_hoy = ids_libres_tutorial(plantilla, 4)

    obras = []
    n_obras_prev = Obra.query.filter(Obra.is_deleted.is_(False)).count()
    horizon = qty['dias_historial']
    for i in range(qty['obras']):
        jefe = jefes[i % len(jefes)] if jefes else None
        base = OBRA_NOMBRES[(n_obras_prev + i) % len(OBRA_NOMBRES)]
        nombre = base if (n_obras_prev + i) < len(OBRA_NOMBRES) else f'{base} {n_obras_prev + i + 1}'
        obra = Obra(
            nombre=nombre,
            codigo=_codigo_obra_unico(n_obras_prev + i + 1, marcar_demo),
            estado='En Curso',
            jefe_obra_id=jefe.id if jefe else None,
            fecha_inicio=hoy - timedelta(days=horizon),
            fecha_fin=hoy + timedelta(days=horizon),
            color=generate_random_color(),
        )
        db.session.add(obra)
        db.session.flush()
        obras.append(obra)

    vehiculos = []
    n_veh_prev = Vehiculo.query.count()
    marcas = ('Citroën', 'Renault', 'Peugeot', 'Ford', 'Opel')
    modelos = ('Berlingo', 'Kangoo', 'Partner', 'Transit', 'Combo')
    for i in range(qty.get('vehiculos', 0)):
        idx = n_veh_prev + i
        if marcar_demo:
            matricula = f'{DEMO_MATRICULA_PREFIX}{i + 1:03d}'
            nombre_v = f'Furgoneta demo {i + 1}'
            marca = 'Demo'
            modelo = f'M{i + 1}'
        else:
            matricula = _matricula_semilla(idx)
            while Vehiculo.query.filter_by(matricula=matricula).first():
                idx += 17
                matricula = _matricula_semilla(idx)
            nombre_v = f'Furgoneta {idx + 1}'
            marca = marcas[idx % len(marcas)]
            modelo = modelos[idx % len(modelos)]
        v = Vehiculo(
            nombre=nombre_v,
            matricula=matricula,
            marca=marca,
            modelo=modelo,
            active=True,
        )
        db.session.add(v)
        db.session.flush()
        vehiculos.append(v)

    de_vacaciones = {}  # user_id -> (ini, fin)
    pool_vac_hoy = [o for o in operarios if o.id not in ids_libres_tutorial_hoy]
    n_vac_hoy = min(3, max(0 if not pool_vac_hoy else 1, len(pool_vac_hoy) // 8))
    if pool_vac_hoy and n_vac_hoy:
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
                descripcion=desc_baja,
                created_by_id=autor_id,
            )
            db.session.add(leave)
            db.session.flush()
            de_vacaciones[op.id] = (ini, fin)

    candidatos_futuro = [o for o in operarios if o.id not in de_vacaciones]
    if candidatos_futuro:
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
                descripcion=desc_baja,
                created_by_id=autor_id,
            )
            db.session.add(leave)
            db.session.flush()

    def _en_vacaciones(user_id, dia):
        rango = de_vacaciones.get(user_id)
        return bool(rango and rango[0] <= dia <= rango[1])

    max_por_obra_dia = 4
    continuidad = _EstadoContinuidadAsignacion(obras, max_por_obra_dia=max_por_obra_dia)
    for dia, d_offset in _iter_dias_laborables_planificacion(hoy, horizon):
        for op in plantilla:
            if _en_vacaciones(op.id, dia):
                continue
            if dia == hoy and op.id in ids_libres_tutorial_hoy:
                continue
            obra = continuidad.elegir(op.id, dia)
            if obra is None:
                continue
            plan_autor = (
                _autor_planificacion_obra(obra, jefes, autor_id)
                if not marcar_demo else autor_id
            )
            try:
                with db.session.begin_nested():
                    CoreAssignmentService.asignar(
                        op.id, obra.id, dia, plan_autor, origen,
                        registrar_log=True,
                    )
                if not marcar_demo:
                    _retroceder_log_planificacion(op.id, dia)
                continuidad.confirmar(op.id, obra, dia)
            except Exception:
                continue

            if dia > hoy:
                continue
            try:
                with db.session.begin_nested():
                    _sembrar_fichaje_dia(
                        op, obra, dia, marcar_demo, obras, abs(d_offset),
                    )
            except Exception:
                continue

    for i, v in enumerate(vehiculos):
        if i >= len(operarios):
            break
        if i < max(2, len(vehiculos) - 1):
            inicio = hoy - timedelta(days=horizon)
            fin = hoy + timedelta(days=horizon)
        else:
            inicio = hoy
            fin = hoy + timedelta(days=min(2, horizon))
        conductor = operarios[i]
        for dia in _daterange(inicio, fin):
            if dia.weekday() >= 5:
                continue
            if _en_vacaciones(conductor.id, dia):
                continue
            try:
                with db.session.begin_nested():
                    CoreVehicleAssignmentService.asignar(
                        v.id, conductor.id, dia, autor_id, origen,
                        registrar_log=not marcar_demo,
                    )
                    if not marcar_demo:
                        _retroceder_log_vehiculo(conductor.id, dia)
            except Exception:
                continue

    n_sol = int(qty.get('solicitudes') or 0)
    if n_sol > 0 and jefes and obras and operarios:
        jefe = jefes[0]
        obra_a = obras[0]
        obra_b = obras[1] if len(obras) > 1 else obras[0]
        libre = next((o for o in operarios if o.id not in de_vacaciones), operarios[0])
        nota_asig = (
            'Demo: necesitamos a esta persona la semana que viene.'
            if marcar_demo else 'Necesitamos a esta persona la semana que viene.'
        )
        nota_gen = (
            'Demo: faltan dos oficiales para el tajo.'
            if marcar_demo else 'Faltan dos oficiales para el tajo.'
        )
        nota_baja = (
            'Demo: baja solicitada por el jefe (sí está asignado).'
            if marcar_demo else 'Baja solicitada por el jefe.'
        )
        nota_veh = (
            'Demo: necesita furgoneta para el desplazamiento.'
            if marcar_demo else 'Necesita furgoneta para el desplazamiento.'
        )

        creadas = 0
        if creadas < n_sol:
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
                notas=nota_asig,
            ))
            creadas += 1
        if creadas < n_sol:
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
                notas=nota_gen,
            ))
            creadas += 1

        candidato_baja = next(
            (o for o in reversed(operarios) if o.id not in de_vacaciones and o.id != libre.id),
            None,
        )
        if candidato_baja is None:
            candidato_baja = libre
        fechas_baja = []
        if creadas < n_sol:
            for d_off in range(1, 8):
                dia = hoy + timedelta(days=d_off)
                if dia.weekday() >= 5:
                    continue
                try:
                    with db.session.begin_nested():
                        CoreAssignmentService.asignar(
                            candidato_baja.id, obra_a.id, dia, autor_id, origen,
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
                    notas=nota_baja,
                ))
                creadas += 1

        if creadas < n_sol and vehiculos and len(operarios) > 2:
            db.session.add(SolicitudVehiculo(
                accion='ASIGNAR',
                requested_by_id=jefe.id,
                empleado_id=operarios[min(2, len(operarios) - 1)].id,
                vehiculo_id=vehiculos[-1].id,
                fecha_inicio=hoy + timedelta(days=1),
                fecha_fin=hoy + timedelta(days=4),
                estado='PENDIENTE',
                notas=nota_veh,
            ))
            creadas += 1

        while creadas < n_sol:
            db.session.add(Solicitud(
                tipo='GENERICA',
                accion='ASIGNAR',
                obra_id=obras[creadas % len(obras)].id,
                requested_by_id=jefes[creadas % len(jefes)].id,
                fecha_inicio=hoy + timedelta(days=3 + creadas),
                fecha_fin=hoy + timedelta(days=12 + creadas),
                perfil_categoria='Peón',
                cantidad_solicitada=1,
                estado='PENDIENTE',
                notas=nota_gen,
            ))
            creadas += 1
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
    if marcar_demo:
        set_tenant_config(CONFIG_DEMO_ACTIVA, 'True')
    else:
        # Si más tarde activan onboarding, que no siembre encima una DEMO con banner.
        set_tenant_config(CONFIG_DEMO_CLEARED, 'True')
        set_tenant_config(CONFIG_DEMO_ACTIVA, 'False')
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
