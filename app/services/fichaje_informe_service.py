# app/services/fichaje_informe_service.py
#
# Informe de registro de jornada para la empresa.
#
# Es la pieza que se enseña a la Inspección: el detalle día a día de cada
# trabajador, con la verificación de la cadena de hashes del libro. Sin esto,
# el libro inalterable existe pero no hay un documento que lo demuestre.

import csv
import hashlib
import io
from datetime import datetime

from app.models import (
    EVENTO_ANULACION,
    EVENTO_ENTRADA,
    EVENTO_REASIGNACION_OBRA,
    EVENTO_SALIDA,
    Company,
    FichajeEvento,
    User,
)
from app.services.fichaje_ledger_service import (
    minutos_de,
    verificar_cadena,
    vigentes,
)
from app.utils.timezone_utils import format_time, today_local, utc_now

MAX_DIAS_INFORME = 366

_ETIQUETAS_TIPO = {
    EVENTO_ENTRADA: 'Entrada',
    EVENTO_SALIDA: 'Salida',
    'pausa_inicio': 'Inicio de pausa',
    'pausa_fin': 'Fin de pausa',
    EVENTO_ANULACION: 'Anulación',
    EVENTO_REASIGNACION_OBRA: 'Reimputación de obra',
}


class FichajeInformeError(Exception):
    """Datos del informe inválidos o rango no admisible."""


def _parse_fecha(valor, nombre):
    if isinstance(valor, datetime):
        return valor.date()
    if hasattr(valor, 'year') and hasattr(valor, 'month'):
        return valor
    try:
        return datetime.strptime(str(valor), '%Y-%m-%d').date()
    except (TypeError, ValueError) as exc:
        raise FichajeInformeError(
            f'La fecha «{nombre}» no es válida.'
        ) from exc


def _empresa_informante():
    """La empresa propia del tenant, si está dada de alta; si no, solo el nombre."""
    interna = Company.query.filter_by(is_internal=True).order_by(Company.id.asc()).first()
    return {
        'nombre': interna.nombre if interna else None,
        'nif': interna.nif if interna else None,
        'company_id': interna.id if interna else None,
    }


def _nombre_completo(user):
    return f'{user.name or ""} {user.lastname or ""}'.strip() or user.email


def _obra_del_dia(eventos):
    reasignaciones = [
        e for e in eventos
        if e.tipo == EVENTO_REASIGNACION_OBRA and e.obra_id is not None
    ]
    if reasignaciones:
        return reasignaciones[-1].obra

    for evento in eventos:
        if evento.tipo == EVENTO_ENTRADA and evento.obra is not None:
            return evento.obra
    return None


def _dia_desde_eventos(fecha, eventos):
    """
    Resumen de un día a partir de todos los eventos del libro ese día.

    Las horas y la obra se calculan sobre las marcas vigentes. Las anulaciones
    y reimputaciones se listan aparte: son lo que la Inspección tiene que ver
    si pregunta por correcciones.
    """
    vigentes_dia = vigentes(eventos)
    entradas = [e for e in vigentes_dia if e.tipo == EVENTO_ENTRADA]
    salidas = [e for e in vigentes_dia if e.tipo == EVENTO_SALIDA]
    obra = _obra_del_dia(vigentes_dia)
    correcciones = [
        e for e in eventos
        if e.tipo in (EVENTO_ANULACION, EVENTO_REASIGNACION_OBRA)
    ]

    return {
        'fecha': fecha,
        'entrada': entradas[0].ocurrido_en if entradas else None,
        'salida': salidas[-1].ocurrido_en if salidas else None,
        'minutos': minutos_de(vigentes_dia),
        'obra': obra,
        'obra_nombre': obra.nombre if obra else None,
        'eventos': eventos,
        'correcciones': correcciones,
        'tiene_correcciones': bool(correcciones),
        'sin_salida': bool(entradas) and not salidas,
    }


def generar_informe(desde, hasta, user_id=None, company_id=None, tenant_nombre=None):
    """
    Construye el informe de jornada del periodo.

    Por defecto incluye a todos los trabajadores con marcas en el rango.
    Se puede acotar a un trabajador o a una empresa (propia o subcontrata).
    """
    desde = _parse_fecha(desde, 'desde')
    hasta = _parse_fecha(hasta, 'hasta')

    if desde > hasta:
        desde, hasta = hasta, desde
    if (hasta - desde).days > MAX_DIAS_INFORME:
        raise FichajeInformeError(
            f'El periodo no puede superar {MAX_DIAS_INFORME} días.'
        )
    if hasta > today_local():
        hasta = today_local()

    consulta = FichajeEvento.query.filter(
        FichajeEvento.fecha_laboral >= desde,
        FichajeEvento.fecha_laboral <= hasta,
    )
    if user_id:
        consulta = consulta.filter(FichajeEvento.user_id == int(user_id))

    eventos = consulta.order_by(
        FichajeEvento.user_id.asc(),
        FichajeEvento.ocurrido_en.asc(),
        FichajeEvento.secuencia.asc(),
    ).all()

    if company_id:
        company_id = int(company_id)
        permitidos = {
            u.id for u in User.query.filter_by(company_id=company_id).all()
        }
        eventos = [e for e in eventos if e.user_id in permitidos]

    # Incluir anulaciones y reasignaciones en el detalle: la Inspección tiene
    # que ver las correcciones, no solo el resultado final.
    por_usuario = {}
    for evento in eventos:
        por_usuario.setdefault(evento.user_id, {}).setdefault(
            evento.fecha_laboral, []
        ).append(evento)

    trabajadores = []
    minutos_totales = 0
    dias_con_registro = 0
    dias_con_correccion = 0

    usuarios = {
        u.id: u for u in User.query.filter(User.id.in_(por_usuario.keys())).all()
    } if por_usuario else {}

    for uid in sorted(
        por_usuario.keys(),
        key=lambda i: (
            (usuarios.get(i).lastname or '') if usuarios.get(i) else '',
            (usuarios.get(i).name or '') if usuarios.get(i) else '',
            i,
        ),
    ):
        user = usuarios.get(uid)
        if user is None:
            continue

        dias = []
        minutos_trabajador = 0
        for fecha in sorted(por_usuario[uid].keys()):
            dia = _dia_desde_eventos(fecha, por_usuario[uid][fecha])
            dias.append(dia)
            minutos_trabajador += dia['minutos']
            dias_con_registro += 1
            if dia['tiene_correcciones']:
                dias_con_correccion += 1

        minutos_totales += minutos_trabajador
        trabajadores.append({
            'user': user,
            'nombre': _nombre_completo(user),
            'dni': user.dni,
            'empresa': user.company_rel.nombre if user.company_rel else None,
            'dias': dias,
            'minutos': minutos_trabajador,
            'dias_trabajados': len(dias),
        })

    incidencias = verificar_cadena()
    empresa = _empresa_informante()
    generado_en = utc_now()

    # Huella del contenido exportado: si alguien altera el CSV o el PDF después
    # de descargarlo, el resumen ya no cuadra con lo que hay en el libro.
    huella = _huella_informe(
        tenant_nombre=tenant_nombre or '',
        desde=desde,
        hasta=hasta,
        trabajadores=trabajadores,
        incidencias=len(incidencias),
        generado_en=generado_en,
    )

    return {
        'tenant_nombre': tenant_nombre,
        'empresa': empresa,
        'desde': desde,
        'hasta': hasta,
        'trabajadores': trabajadores,
        'minutos_totales': minutos_totales,
        'dias_con_registro': dias_con_registro,
        'dias_con_correccion': dias_con_correccion,
        'trabajadores_count': len(trabajadores),
        'cadena_integra': len(incidencias) == 0,
        'incidencias_cadena': incidencias,
        'eventos_en_libro': FichajeEvento.query.count(),
        'generado_en': generado_en,
        'huella': huella,
        'filtro_user_id': int(user_id) if user_id else None,
        'filtro_company_id': int(company_id) if company_id else None,
    }


def _huella_informe(*, tenant_nombre, desde, hasta, trabajadores, incidencias, generado_en):
    trozos = [
        tenant_nombre or '',
        desde.isoformat(),
        hasta.isoformat(),
        str(incidencias),
        generado_en.replace(microsecond=0).isoformat(),
    ]
    for t in trabajadores:
        trozos.append(f"{t['dni']}|{t['minutos']}|{t['dias_trabajados']}")
        for d in t['dias']:
            trozos.append(
                f"{d['fecha'].isoformat()}|"
                f"{d['entrada'].isoformat() if d['entrada'] else ''}|"
                f"{d['salida'].isoformat() if d['salida'] else ''}|"
                f"{d['minutos']}|{d['obra_nombre'] or ''}"
            )
    return hashlib.sha256('\n'.join(trozos).encode('utf-8')).hexdigest()


def etiquetar_tipo(tipo):
    return _ETIQUETAS_TIPO.get(tipo, tipo)


def formatear_horas(minutos):
    minutos = max(int(minutos or 0), 0)
    return f'{minutos // 60} h {minutos % 60:02d} min'


def informe_a_csv(informe):
    """CSV con una fila por día trabajado, listo para Excel en español."""
    buffer = io.StringIO()
    escritor = csv.writer(buffer, delimiter=';')
    escritor.writerow([
        'Empresa', 'NIF empresa', 'Trabajador', 'DNI', 'Empresa del trabajador',
        'Fecha', 'Entrada', 'Salida', 'Horas', 'Obra', 'Correcciones',
    ])

    nombre_empresa = (
        (informe['empresa']['nombre'] if informe['empresa'] else None)
        or informe.get('tenant_nombre')
        or ''
    )
    nif = (informe['empresa']['nif'] if informe['empresa'] else None) or ''

    for t in informe['trabajadores']:
        for d in t['dias']:
            escritor.writerow([
                nombre_empresa,
                nif,
                t['nombre'],
                t['dni'] or '',
                t['empresa'] or '',
                d['fecha'].strftime('%d/%m/%Y'),
                format_time(d['entrada']) if d['entrada'] else '',
                format_time(d['salida']) if d['salida'] else '',
                f"{d['minutos'] / 60:.2f}".replace('.', ','),
                d['obra_nombre'] or '',
                'Sí' if d['tiene_correcciones'] else 'No',
            ])

    escritor.writerow([])
    escritor.writerow(['Total horas', f"{informe['minutos_totales'] / 60:.2f}".replace('.', ',')])
    escritor.writerow([
        'Cadena de integridad',
        'Íntegra' if informe['cadena_integra'] else f"{len(informe['incidencias_cadena'])} incidencia(s)",
    ])
    escritor.writerow(['Huella del informe', informe['huella']])
    escritor.writerow([
        'Generado el',
        informe['generado_en'].strftime('%d/%m/%Y %H:%M:%S') + ' UTC',
    ])
    escritor.writerow([
        'Periodo',
        f"{informe['desde'].strftime('%d/%m/%Y')} — {informe['hasta'].strftime('%d/%m/%Y')}",
    ])

    return '\ufeff' + buffer.getvalue()


def periodo_por_defecto():
    """Último mes natural cerrado relativo a hoy, o el mes en curso si es día 1."""
    hoy = today_local()
    desde = hoy.replace(day=1)
    return desde, hoy


def listar_trabajadores_para_filtro():
    return (
        User.query
        .filter(User.is_deleted.is_(False))
        .order_by(User.lastname.asc(), User.name.asc())
        .all()
    )


def listar_empresas_para_filtro():
    return Company.query.order_by(Company.is_internal.desc(), Company.nombre.asc()).all()
