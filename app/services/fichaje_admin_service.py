# app/services/fichaje_admin_service.py
#
# Altas y correcciones de marcas de jornada por administración.
# Nunca reescribe el pasado: anular = evento de anulación; corregir = anular + nuevo.

from datetime import datetime

from app import db
from app.models import (
    EVENTO_ANULACION,
    EVENTO_ENTRADA,
    EVENTO_PAUSA_FIN,
    EVENTO_PAUSA_INICIO,
    EVENTO_SALIDA,
    ORIGEN_ADMIN,
    ROLE_ADMIN,
    ROLE_JEFE,
    ROLE_LABORAL,
    ROLE_OPERARIO,
    ROLE_RRHH,
    FichajeEvento,
    Obra,
    User,
)
from app.services.fichaje_ledger_service import (
    FichajeLedgerError,
    anular_evento,
    esta_anulado,
    eventos_del_dia,
    proyectar_dia,
    registrar_evento,
)
from app.utils.timezone_utils import get_app_timezone, local_to_utc, utc_to_local

TIPOS_MARCA_EDITABLES = (
    EVENTO_ENTRADA,
    EVENTO_SALIDA,
    EVENTO_PAUSA_INICIO,
    EVENTO_PAUSA_FIN,
)

class FichajeAdminError(Exception):
    """Error de validación en altas/correcciones de marca."""


def _parse_local_datetime(valor):
    """
    Interpreta 'YYYY-MM-DDTHH:MM' o 'YYYY-MM-DD HH:MM[:SS]' en zona de la app
    y lo convierte a UTC naive (convención del proyecto).
    """
    raw = (valor or '').strip()
    if not raw:
        raise FichajeAdminError('Indica fecha y hora de la marca.')
    raw = raw.replace('T', ' ')
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
        try:
            local_naive = datetime.strptime(raw, fmt)
            break
        except ValueError:
            local_naive = None
    if local_naive is None:
        raise FichajeAdminError('Fecha/hora no válida.')
    return local_to_utc(local_naive, get_app_timezone()).replace(microsecond=0)


def _asegurar_trabajador(user_id):
    user = User.query.filter_by(id=user_id, is_deleted=False).first()
    if not user or user.role not in (
        ROLE_OPERARIO, ROLE_JEFE, ROLE_ADMIN, ROLE_LABORAL, ROLE_RRHH
    ):
        raise FichajeAdminError('Trabajador no válido.')
    return user


def _asegurar_obra(obra_id):
    if obra_id is None:
        return None
    obra = Obra.query.filter_by(id=obra_id).first()
    if not obra:
        raise FichajeAdminError('Obra no válida.')
    return obra


def listar_eventos_dia(user_id, fecha):
    """Eventos del día con flag de anulado (para el modal de corrección)."""
    todos = eventos_del_dia(user_id, fecha, incluir_anulados=True)
    vigentes = {e.id for e in eventos_del_dia(user_id, fecha, incluir_anulados=False)}
    out = []
    for e in todos:
        local = utc_to_local(e.ocurrido_en)
        out.append({
            'id': e.id,
            'tipo': e.tipo,
            'origen': e.origen,
            'obra_id': e.obra_id,
            'obra_nombre': e.obra.nombre if getattr(e, 'obra', None) else None,
            'ocurrido_en': e.ocurrido_en.isoformat() + 'Z' if e.ocurrido_en else None,
            'ocurrido_local': local.strftime('%Y-%m-%d %H:%M') if local else None,
            'motivo': e.motivo,
            'autor_id': e.autor_id,
            'secuencia': e.secuencia,
            'anulado': e.id not in vigentes and e.tipo != EVENTO_ANULACION,
            'evento_anulado_id': e.evento_anulado_id,
            'editable': e.tipo in TIPOS_MARCA_EDITABLES and e.id in vigentes,
        })
    return out


def registrar_marca_manual(
    *,
    user_id,
    tipo,
    ocurrido_en_local,
    motivo,
    autor_id,
    obra_id=None,
    fecha_laboral=None,
    ip=None,
    dispositivo=None,
):
    """
    Alta de una marca olvidada (entrada/salida/pausa) con ORIGEN_ADMIN.
    Conserva el registro anterior: solo añade al ledger.
    """
    if tipo not in TIPOS_MARCA_EDITABLES:
        raise FichajeAdminError('Tipo de marca no permitido.')
    motivo = (motivo or '').strip()
    if len(motivo) < 5:
        raise FichajeAdminError('El motivo debe tener al menos 5 caracteres (trazabilidad).')

    trabajador = _asegurar_trabajador(user_id)
    _asegurar_obra(obra_id)
    ocurrido_utc = (
        ocurrido_en_local
        if isinstance(ocurrido_en_local, datetime)
        else _parse_local_datetime(ocurrido_en_local)
    )
    fecha = fecha_laboral or utc_to_local(ocurrido_utc).date()

    try:
        evento = registrar_evento(
            user_id=trabajador.id,
            tipo=tipo,
            origen=ORIGEN_ADMIN,
            ocurrido_en=ocurrido_utc,
            fecha_laboral=fecha,
            autor_id=autor_id,
            obra_id=obra_id,
            motivo=motivo,
            ip=ip,
            dispositivo=dispositivo or 'admin-auditoria',
        )
        proyectar_dia(trabajador.id, fecha)
        db.session.flush()
        return evento
    except FichajeLedgerError as exc:
        raise FichajeAdminError(str(exc)) from exc


def corregir_marca(
    *,
    evento_id,
    motivo,
    autor_id,
    nuevo_ocurrido_en_local=None,
    nueva_obra_id=None,
    ip=None,
    dispositivo=None,
):
    """
    Corrige una marca vigente: anula la original (queda en el libro) y
    registra una nueva con los datos corregidos. Misma jornada laboral.
    """
    motivo = (motivo or '').strip()
    if len(motivo) < 5:
        raise FichajeAdminError('El motivo debe tener al menos 5 caracteres (trazabilidad).')

    original = FichajeEvento.query.filter_by(id=evento_id).first()
    if original is None:
        raise FichajeAdminError('La marca no existe.')
    if original.tipo not in TIPOS_MARCA_EDITABLES:
        raise FichajeAdminError('Solo se pueden corregir entradas, salidas o pausas.')
    if esta_anulado(original.id):
        raise FichajeAdminError('Esa marca ya estaba anulada.')

    obra_id = nueva_obra_id if nueva_obra_id is not None else original.obra_id
    _asegurar_obra(obra_id)

    if nuevo_ocurrido_en_local:
        ocurrido_utc = (
            nuevo_ocurrido_en_local
            if isinstance(nuevo_ocurrido_en_local, datetime)
            else _parse_local_datetime(nuevo_ocurrido_en_local)
        )
    else:
        ocurrido_utc = original.ocurrido_en

    try:
        anular_evento(
            evento_id=original.id,
            motivo=motivo,
            autor_id=autor_id,
            origen=ORIGEN_ADMIN,
        )
        nuevo = registrar_evento(
            user_id=original.user_id,
            tipo=original.tipo,
            origen=ORIGEN_ADMIN,
            ocurrido_en=ocurrido_utc,
            fecha_laboral=original.fecha_laboral,
            autor_id=autor_id,
            obra_id=obra_id,
            motivo=motivo,
            ip=ip,
            dispositivo=dispositivo or 'admin-auditoria',
        )
        proyectar_dia(original.user_id, original.fecha_laboral)
        db.session.flush()
        return nuevo
    except FichajeLedgerError as exc:
        raise FichajeAdminError(str(exc)) from exc


def anular_marca(*, evento_id, motivo, autor_id):
    """Anula una marca sin crear otra (olvido inverso / marca errónea)."""
    motivo = (motivo or '').strip()
    if len(motivo) < 5:
        raise FichajeAdminError('El motivo debe tener al menos 5 caracteres (trazabilidad).')
    original = FichajeEvento.query.filter_by(id=evento_id).first()
    if original is None:
        raise FichajeAdminError('La marca no existe.')
    if original.tipo not in TIPOS_MARCA_EDITABLES:
        raise FichajeAdminError('Solo se pueden anular entradas, salidas o pausas.')
    try:
        evento = anular_evento(
            evento_id=original.id,
            motivo=motivo,
            autor_id=autor_id,
            origen=ORIGEN_ADMIN,
        )
        proyectar_dia(original.user_id, original.fecha_laboral)
        db.session.flush()
        return evento
    except FichajeLedgerError as exc:
        raise FichajeAdminError(str(exc)) from exc
