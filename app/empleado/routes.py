# app/empleado/routes.py
#
# Portal de jornada del trabajador (/fichaje): fichar, calendario, ausencias y PIN.

import csv
import io
from datetime import datetime, timedelta

from flask import (
    Response,
    abort,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user

from app import db, limiter
from app.empleado import empleado_bp
from app.models import ROLE_OPERARIO
from app.services.fichaje_ledger_service import FichajeLedgerError
from app.services.fichaje_operario_service import (
    conformar_jornada,
    estado_para_pantalla,
    fichaje_operario_activo,
    fichar as registrar_fichaje,
    historial,
    tenant_tiene_fichaje_operario_module,
)
from app.services.i18n_service import translate
from app.utils.timezone_utils import format_datetime, format_time, today_local

MAX_DIAS_HISTORIAL = 400

# Rutas públicas (sin sesión): definir PIN desde el correo.
_RUTAS_PUBLICAS = frozenset({
    'empleado.definir_pin',
})


def _puede_portal_jornada() -> bool:
    from app.services.permission_service import user_can
    return any(
        user_can(current_user, mod, 'r')
        for mod in (
            'operario_fichaje',
            'operario_calendario',
            'operario_ausencias',
        )
    )


def _dispositivo():
    return (request.headers.get('User-Agent') or '')[:255] or None


def _ip():
    reenviada = request.headers.get('X-Forwarded-For', '')
    return (reenviada.split(',')[0].strip() or request.remote_addr or None)


def _numero(valor):
    if valor in (None, '', 'null'):
        return None
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def _rango_solicitado():
    hasta = today_local()
    desde = hasta - timedelta(days=30)
    try:
        if request.args.get('desde'):
            desde = datetime.strptime(request.args['desde'], '%Y-%m-%d').date()
        if request.args.get('hasta'):
            hasta = datetime.strptime(request.args['hasta'], '%Y-%m-%d').date()
    except ValueError:
        flash(translate('Las fechas indicadas no son válidas; se muestra el último mes.'), 'warning')
        return today_local() - timedelta(days=30), today_local()
    if desde > hasta:
        desde, hasta = hasta, desde
    if (hasta - desde).days > MAX_DIAS_HISTORIAL:
        desde = hasta - timedelta(days=MAX_DIAS_HISTORIAL)
    return desde, hasta


@empleado_bp.before_request
def _portal_jornada_guard():
    if request.endpoint in _RUTAS_PUBLICAS:
        return None
    if not current_user.is_authenticated:
        return None
    if not _puede_portal_jornada():
        flash(translate('No tienes acceso a esta sección.'), 'warning')
        return redirect(url_for('main.dashboard'))
    from app.services.permission_guard import enforce_empleado_permissions
    return enforce_empleado_permissions()


@empleado_bp.route('/')
@login_required
def inicio():
    from app.services.permission_service import user_can
    if (
        tenant_tiene_fichaje_operario_module()
        and user_can(current_user, 'operario_fichaje', 'r')
    ):
        return redirect(url_for('empleado.fichar'))
    if user_can(current_user, 'operario_calendario', 'r'):
        return redirect(url_for('empleado.calendario'))
    if user_can(current_user, 'operario_ausencias', 'r'):
        return redirect(url_for('empleado.ausencias'))
    return redirect(url_for('empleado.fichar'))


@empleado_bp.route('/calendario')
@login_required
def calendario():
    return render_template('empleado/calendario.html', worker=current_user)


@empleado_bp.route('/fichar')
@login_required
def fichar():
    from app.services.permission_service import user_can
    from app.services.pin_auth_service import debe_cambiar_pin

    if not tenant_tiene_fichaje_operario_module():
        abort(404)
    if not user_can(current_user, 'operario_fichaje', 'r'):
        abort(403)

    if not fichaje_operario_activo():
        abort(404)

    if debe_cambiar_pin(current_user):
        flash(translate('Debes cambiar el PIN antes de fichar.'), 'warning')
        return redirect(url_for('empleado.cambiar_pin', obligatorio=1))

    contexto = estado_para_pantalla(current_user)
    return render_template('empleado/fichar.html', **contexto)


@empleado_bp.route('/fichar', methods=['POST'])
@login_required
@limiter.limit('30 per minute; 200 per hour')
def api_fichar():
    """Registra un fichaje y devuelve el estado actualizado (JSON)."""
    if not tenant_tiene_fichaje_operario_module() or not fichaje_operario_activo():
        abort(404)
    from app.services.pin_auth_service import debe_cambiar_pin
    if debe_cambiar_pin(current_user):
        return jsonify({
            'ok': False,
            'error': translate('Debes cambiar el PIN antes de fichar.'),
            'must_change_pin': True,
        }), 403

    datos = request.get_json(silent=True) or request.form
    try:
        estado = registrar_fichaje(
            user=current_user,
            tipo=(datos.get('tipo') or '').strip(),
            obra_id=datos.get('obra_id') or None,
            latitud=_numero(datos.get('latitud')),
            longitud=_numero(datos.get('longitud')),
            precision_metros=_numero(datos.get('precision_metros')),
            nota_ubicacion=(datos.get('nota_ubicacion') or '').strip() or None,
            ip=_ip(),
            dispositivo=_dispositivo(),
        )
    except FichajeLedgerError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    except Exception:
        current_app.logger.exception('Fallo al registrar un fichaje')
        return jsonify({
            'ok': False,
            'error': translate('No se ha podido registrar el fichaje. Inténtalo de nuevo.'),
        }), 500

    return jsonify({
        'ok': True,
        'estado': estado['estado'],
        'desde': format_time(estado['desde']) if estado['desde'] else None,
        'minutos': estado['minutos'],
        'obra': estado['obra_actual'].nombre if estado['obra_actual'] else None,
        'conforme': estado.get('conforme'),
        'puede_conformar': estado.get('puede_conformar'),
        'eventos': [
            {
                'tipo': e.tipo,
                'hora': format_time(e.ocurrido_en),
                'obra': e.obra.nombre if e.obra else None,
            }
            for e in estado['eventos']
        ],
    })


@empleado_bp.route('/conformar', methods=['POST'])
@login_required
@limiter.limit('20 per minute; 100 per hour')
def api_conformar():
    """Conforme digital del trabajador sobre la jornada del día."""
    try:
        estado = conformar_jornada(
            user=current_user,
            ip=_ip(),
            dispositivo=_dispositivo(),
        )
    except FichajeLedgerError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    except Exception:
        current_app.logger.exception('Fallo al registrar conforme de jornada')
        return jsonify({
            'ok': False,
            'error': translate('No se ha podido registrar el conforme. Inténtalo de nuevo.'),
        }), 500

    return jsonify({
        'ok': True,
        'conforme': True,
        'puede_conformar': False,
        'estado': estado['estado'],
        'minutos': estado['minutos'],
        'eventos': [
            {
                'tipo': e.tipo,
                'hora': format_time(e.ocurrido_en),
                'obra': e.obra.nombre if e.obra else None,
            }
            for e in estado['eventos']
        ],
    })


@empleado_bp.route('/fichajes')
@login_required
def fichajes():
    if not fichaje_operario_activo():
        abort(404)
    datos = historial(current_user.id)
    return render_template('empleado/fichajes.html', **datos)


@empleado_bp.route('/fichajes.csv')
@login_required
@limiter.limit('10 per minute')
def fichajes_csv():
    """Descarga del registro propio en CSV."""
    desde, hasta = _rango_solicitado()
    datos = historial(current_user.id, desde, hasta)

    buffer = io.StringIO()
    escritor = csv.writer(buffer, delimiter=';')
    escritor.writerow([
        'Fecha', 'Entrada', 'Salida', 'Obra', 'Horas', 'Trabajador', 'DNI', 'Empresa',
    ])

    nombre_completo = f'{current_user.name or ""} {current_user.lastname or ""}'.strip()
    for dia in datos['dias']:
        escritor.writerow([
            dia['fecha'].strftime('%d/%m/%Y'),
            format_time(dia['entrada']) if dia['entrada'] else '',
            format_time(dia['salida']) if dia['salida'] else '',
            dia['obra'].nombre if dia['obra'] else '',
            f"{dia['minutos'] / 60:.2f}".replace('.', ','),
            nombre_completo,
            current_user.dni or '',
            g.current_tenant.nombre,
        ])

    escritor.writerow([])
    escritor.writerow([
        'Total horas', f"{datos['minutos_totales'] / 60:.2f}".replace('.', ','),
    ])
    escritor.writerow([
        'Documento generado el', format_datetime(datos['generado_en']),
    ])

    archivo = f"fichajes_{current_user.dni or current_user.id}_{desde}_{hasta}.csv"
    return Response(
        '\ufeff' + buffer.getvalue(),
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename="{archivo}"'},
    )


@empleado_bp.route('/ausencias', methods=['GET', 'POST'])
@login_required
def ausencias():
    from app.services.leave_service import (
        delete_manual_leave,
        leaves_del_usuario,
        solicitar_ausencia_propia,
    )
    from app.utils import register_log

    if request.method == 'POST':
        accion = (request.form.get('accion') or 'solicitar').strip()
        if accion == 'cancelar':
            leave_id = request.form.get('leave_id', type=int)
            try:
                delete_manual_leave(leave_id, current_user)
                flash(translate('Solicitud cancelada.'), 'success')
            except Exception as exc:
                flash(str(exc), 'danger')
            return redirect(url_for('empleado.ausencias'))
        try:
            leave = solicitar_ausencia_propia(
                current_user,
                fecha_inicio=request.form.get('fecha_inicio'),
                fecha_fin=request.form.get('fecha_fin'),
                tipo=request.form.get('tipo') or 'Vacaciones',
                descripcion=request.form.get('descripcion'),
            )
            register_log(
                user_id=current_user.id,
                category='ausencias',
                action='Solicitud de ausencia',
                detail=(
                    f'{leave.tipo}: {leave.fecha_inicio} — {leave.fecha_fin} '
                    f'(pendiente de aprobación)'
                ),
                target_user_id=current_user.id,
                target_date=leave.fecha_inicio,
            )
            flash(
                translate('Solicitud enviada. Queda pendiente de aprobación.'),
                'success',
            )
        except Exception as exc:
            flash(str(exc), 'danger')
        return redirect(url_for('empleado.ausencias'))

    items = leaves_del_usuario(current_user.id, limit=100)
    return render_template('empleado/ausencias.html', ausencias=items)


@empleado_bp.route('/pin', methods=['GET', 'POST'])
@login_required
@limiter.limit('20 per minute; 60 per hour', methods=['POST'])
def cambiar_pin():
    from app.services.pin_auth_service import (
        PinAuthError,
        debe_cambiar_pin,
        cambiar_pin_propio,
        forzar_cambio_pin_primer_acceso,
    )

    obligatorio = bool(
        request.args.get('obligatorio')
        or request.form.get('obligatorio')
        or debe_cambiar_pin(current_user)
    )

    if request.method == 'POST':
        try:
            if obligatorio and debe_cambiar_pin(current_user):
                forzar_cambio_pin_primer_acceso(
                    current_user,
                    request.form.get('pin_nuevo'),
                    request.form.get('pin_nuevo2'),
                )
            else:
                cambiar_pin_propio(
                    current_user,
                    request.form.get('pin_actual'),
                    request.form.get('pin_nuevo'),
                    request.form.get('pin_nuevo2'),
                )
            db.session.commit()
            flash(translate('PIN actualizado.'), 'success')
            return redirect(url_for('empleado.fichar'))
        except PinAuthError as exc:
            db.session.rollback()
            flash(str(exc), 'danger')

    return render_template(
        'empleado/cambiar_pin.html',
        obligatorio=obligatorio,
    )


@empleado_bp.route('/definir-pin', methods=['GET', 'POST'])
@limiter.limit('10 per minute; 40 per hour', methods=['POST'])
def definir_pin():
    """Define el PIN desde el enlace del correo (sin sesión ni PIN previo)."""
    from app.services.pin_auth_service import (
        PinAuthError,
        definir_pin_desde_token,
        usuario_desde_token_definir_pin,
        _url_login_tenant,
    )

    if not getattr(g, 'current_tenant', None):
        flash(translate('Accede desde la URL de tu empresa.'), 'warning')
        return redirect(url_for('auth.login'))

    token = (request.values.get('t') or '').strip()
    if not token:
        flash(translate('El enlace para definir el PIN no es válido.'), 'danger')
        return redirect(url_for('auth.login'))

    pin_user, pin_error = usuario_desde_token_definir_pin(token, g.current_tenant)
    login_url = _url_login_tenant(g.current_tenant)

    if request.method == 'POST' and not pin_error:
        try:
            user = definir_pin_desde_token(
                token,
                g.current_tenant,
                request.form.get('pin_nuevo'),
                request.form.get('pin_nuevo2'),
            )
            db.session.commit()
            if current_user.is_authenticated:
                logout_user()
            login_user(user, remember=True)
            flash(translate('PIN guardado. Ya puedes fichar.'), 'success')
            return redirect(url_for('empleado.fichar'))
        except PinAuthError as exc:
            db.session.rollback()
            pin_error = str(exc)

    return render_template(
        'empleado/definir_pin.html',
        token=token,
        pin_error=pin_error,
        pin_user=pin_user,
        login_url=login_url,
    )
