# app/cli/fichajes.py
#
# Mantenimiento del libro de eventos de jornada.
#
#   flask fichajes backfill    → genera eventos a partir del histórico existente
#   flask fichajes verificar   → comprueba que la cadena no ha sido manipulada
#
# Ambos recorren todos los tenants activos salvo que se acote con --tenant.

import click
from flask.cli import AppGroup
from sqlalchemy import text

from app import db, is_safe_schema_name

fichajes_cli = AppGroup('fichajes', help='Libro de eventos de jornada.')


def _tenants(subdominio=None):
    consulta = (
        'SELECT id, schema_name, subdominio, nombre '
        'FROM public.tenants WHERE is_active = true'
    )
    params = {}
    if subdominio:
        consulta += ' AND subdominio = :sub'
        params['sub'] = subdominio
    consulta += ' ORDER BY subdominio'

    with db.engine.connect() as conn:
        filas = conn.execute(text(consulta), params).fetchall()

    return [
        {'id': f[0], 'schema_name': f[1], 'subdominio': f[2], 'nombre': f[3]}
        for f in filas
    ]


def _en_cada_tenant(subdominio, callback):
    encontrados = _tenants(subdominio)
    if not encontrados:
        click.secho('No hay ningún tenant activo que coincida.', fg='yellow')
        return

    for tenant in encontrados:
        if not is_safe_schema_name(tenant['schema_name']):
            click.secho(
                f"  {tenant['subdominio']}: esquema inválido, se omite.", fg='red'
            )
            continue

        click.secho(f"\n▸ {tenant['nombre']} ({tenant['subdominio']})", bold=True)
        try:
            db.session.execute(text(f"SET search_path TO {tenant['schema_name']}, public"))
            callback(tenant)
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            click.secho(f'  Error: {exc}', fg='red')
        finally:
            db.session.remove()


@fichajes_cli.command('backfill')
@click.option('--tenant', 'subdominio', default=None, help='Limitar a un subdominio.')
@click.option('--dry-run', is_flag=True, help='Solo informar, sin escribir nada.')
def backfill(subdominio, dry_run):
    """
    Genera eventos a partir de los RegistroFichaje ya existentes.

    Es idempotente: cada evento generado queda marcado con el registro del que
    procede, así que volver a ejecutarlo no duplica nada.

    Se detiene en la jornada de ayer. El día en curso lo está alimentando la
    sincronización del ERP en tiempo real, y volcarlo también desde la tabla
    antigua dejaría cada fichaje de hoy anotado dos veces.
    """
    from app.models import (
        EVENTO_ENTRADA,
        EVENTO_SALIDA,
        ORIGEN_MIGRACION,
        FichajeEvento,
        RegistroFichaje,
    )
    from app.services.fichaje_ledger_service import registrar_evento
    from app.utils.timezone_utils import today_local

    hoy = today_local()

    def _procesar(_tenant):
        ya_migrados = {
            fila[0] for fila in db.session.query(
                FichajeEvento.external_ids['registro_fichaje_id'].astext
            ).filter(FichajeEvento.origen == ORIGEN_MIGRACION).all()
            if fila[0]
        }

        registros = (
            RegistroFichaje.query
            .filter(
                RegistroFichaje.check_in.isnot(None),
                RegistroFichaje.fecha < hoy,
            )
            .order_by(RegistroFichaje.fecha.asc(), RegistroFichaje.check_in.asc())
            .all()
        )

        creados = 0
        omitidos = 0

        for registro in registros:
            if str(registro.id) in ya_migrados:
                omitidos += 1
                continue
            if dry_run:
                creados += 1 + (1 if registro.check_out else 0)
                continue

            marca = {'registro_fichaje_id': str(registro.id)}
            motivo = (
                'Importado del histórico anterior a la implantación del libro '
                'de eventos.'
            )

            registrar_evento(
                user_id=registro.user_id,
                tipo=EVENTO_ENTRADA,
                origen=ORIGEN_MIGRACION,
                ocurrido_en=registro.check_in,
                fecha_laboral=registro.fecha,
                obra_id=registro.obra_real_id or registro.obra_planificada_id,
                motivo=motivo,
                external_ids=marca,
            )
            creados += 1

            if registro.check_out:
                registrar_evento(
                    user_id=registro.user_id,
                    tipo=EVENTO_SALIDA,
                    origen=ORIGEN_MIGRACION,
                    ocurrido_en=registro.check_out,
                    fecha_laboral=registro.fecha,
                    obra_id=registro.obra_real_id or registro.obra_planificada_id,
                    motivo=motivo,
                    external_ids=marca,
                )
                creados += 1

        verbo = 'se crearían' if dry_run else 'creados'
        click.echo(f'  Registros en histórico: {len(registros)}')
        click.echo(f'  Eventos {verbo}: {creados}')
        if omitidos:
            click.echo(f'  Registros ya migrados que se omiten: {omitidos}')

    _en_cada_tenant(subdominio, _procesar)

    if dry_run:
        click.secho('\nSimulación: no se ha escrito nada.', fg='yellow')
    else:
        click.secho('\nRelleno completado.', fg='green')


@fichajes_cli.command('verificar')
@click.option('--tenant', 'subdominio', default=None, help='Limitar a un subdominio.')
def verificar(subdominio):
    """
    Recalcula la cadena de hashes y denuncia cualquier manipulación.

    Es la prueba que se le enseña a un inspector: si esto sale limpio, ninguna
    fila del libro ha sido tocada desde que se escribió.
    """
    from app.models import FichajeEvento
    from app.services.fichaje_ledger_service import verificar_cadena

    hubo_incidencias = {'valor': False}

    def _procesar(_tenant):
        total = FichajeEvento.query.count()
        if total == 0:
            click.echo('  Libro vacío, nada que verificar.')
            return

        incidencias = verificar_cadena()
        click.echo(f'  Eventos en el libro: {total}')

        if not incidencias:
            click.secho('  Cadena íntegra.', fg='green')
            return

        hubo_incidencias['valor'] = True
        click.secho(f'  {len(incidencias)} incidencia(s):', fg='red')
        for inc in incidencias:
            click.secho(
                f"    · secuencia {inc['secuencia']} [{inc['tipo']}] {inc['detalle']}",
                fg='red',
            )

    _en_cada_tenant(subdominio, _procesar)

    if hubo_incidencias['valor']:
        raise SystemExit(1)


@fichajes_cli.command('proteger')
@click.option('--tenant', 'subdominio', default=None, help='Limitar a un subdominio.')
def proteger(subdominio):
    """
    Aplica (o reaplica) los triggers de inmutabilidad del libro de fichajes.

    Útil para tenants creados con create_all + stamp antes de que el
    aprovisionamiento llamara a proteger_libro_fichajes. Es idempotente.
    """
    from app.ddl import proteger_libro_fichajes

    def _procesar(tenant):
        schema = tenant['schema_name']
        proteger_libro_fichajes(
            lambda sql: db.session.execute(text(sql)),
            schema,
        )
        click.secho('  Triggers de inmutabilidad aplicados.', fg='green')

    _en_cada_tenant(subdominio, _procesar)
    click.secho('\nProtección aplicada.', fg='green')
