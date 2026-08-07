# app/operarios/routes.py
#
# Área del trabajador: la PWA de fichaje. Es la única parte de la aplicación
# pensada para un móvil en obra, con guantes y a pleno sol, así que va aparte
# del panel de escritorio y no comparte plantilla con él.
#
# Todo lo que se ficha aquí entra en el libro de eventos inalterable.

import csv
import io
from datetime import datetime, timedelta

from flask import (
    Blueprint,
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

from app import limiter
from app import db
from app.models import ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL, ROLE_OPERARIO, ROLE_RRHH
from app.services.fichaje_ledger_service import FichajeLedgerError
from app.services.fichaje_operario_service import (
    estado_para_pantalla,
    fichaje_operario_activo,
    fichar,
    historial,
    conformar_jornada,
)
from app.services.pin_auth_service import PinAuthError, autenticar_por_pin
from app.utils.timezone_utils import format_datetime, format_time, today_local

operarios_bp = Blueprint('operarios', __name__, url_prefix='/mi')

# Quién ve el área de fichaje. Los perfiles de oficina también tienen jornada.
ROLES_CON_FICHAJE = (ROLE_OPERARIO, ROLE_JEFE, ROLE_ADMIN, ROLE_LABORAL, ROLE_RRHH)

# Rutas públicas del área: no exigen sesión.
_RUTAS_PUBLICAS = {
    'operarios.entrar',
    'operarios.definir_pin',
    'operarios.manifest',
    'operarios.service_worker',
}

MAX_DIAS_HISTORIAL = 400


def _dispositivo():
    """User-agent recortado: sirve para auditar, no para perfilar."""
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


@operarios_bp.before_request
def _solo_perfiles_con_jornada():
    if request.endpoint in _RUTAS_PUBLICAS:
        return None

    if not current_user.is_authenticated:
        return redirect(url_for('operarios.entrar', next=request.path))

    if current_user.role not in ROLES_CON_FICHAJE:
        flash('Tu perfil no tiene área de fichaje.', 'warning')
        return redirect(url_for('main.dashboard'))

    # Matriz de permisos: el rol operario puede tener fichaje desactivado por tenant.
    if current_user.role == ROLE_OPERARIO:
        from app.services.permission_service import user_can
        if not user_can(current_user, 'operario_fichaje', 'r'):
            flash('Tu perfil no tiene acceso al fichaje.', 'warning')
            return redirect(url_for('auth.login'))

    # PIN provisional: solo puede cambiar PIN o salir.
    from app.services.pin_auth_service import debe_cambiar_pin
    if debe_cambiar_pin(current_user) and request.endpoint not in (
        'operarios.cambiar_pin',
        'operarios.salir',
    ):
        return redirect(url_for('operarios.cambiar_pin', obligatorio=1))
    return None


@operarios_bp.route('/entrar', methods=['GET', 'POST'])
@limiter.limit('20 per minute; 100 per hour', methods=['POST'])
def entrar():
    """
    Acceso a la PWA con DNI y PIN.

    Es la puerta pensada para obra. El login de correo y contraseña sigue
    existiendo para oficina; aquí el teclado es numérico y no hace falta
    recordar un email.
    """
    if not fichaje_operario_activo():
        abort(404)

    if current_user.is_authenticated and current_user.role in ROLES_CON_FICHAJE:
        return redirect(url_for('operarios.inicio'))

    if request.method == 'POST':
        try:
            user = autenticar_por_pin(
                request.form.get('dni'),
                request.form.get('pin'),
            )
        except PinAuthError as exc:
            from app.utils import register_log
            register_log(
                user_id=None,
                category='accesos',
                action='Intento fallido de acceso por PIN',
                detail=f"IP: {request.remote_addr or 'Desconocida'}",
            )
            flash(str(exc), 'danger')
            return render_template('operario/entrar.html')

        login_user(user, remember=True)
        if getattr(g, 'current_tenant', None):
            from flask import session
            session['tenant_id'] = g.current_tenant.id

        from app.utils import register_log
        register_log(
            user_id=user.id,
            category='accesos',
            action='Inicio de sesión (PIN)',
            detail=f"Acceso a fichaje desde IP: {request.remote_addr or 'Desconocida'}",
        )

        from app.services.pin_auth_service import debe_cambiar_pin
        if debe_cambiar_pin(user):
            return redirect(url_for('operarios.cambiar_pin', obligatorio=1))

        destino = request.args.get('next') or url_for('operarios.inicio')
        if not destino.startswith('/mi'):
            destino = url_for('operarios.inicio')
        return redirect(destino)

    return render_template('operario/entrar.html')


@operarios_bp.route('/salir')
def salir():
    logout_user()
    flash('Sesión cerrada', 'info')
    return redirect(url_for('operarios.entrar'))


@operarios_bp.route('/')
def inicio():
    if not fichaje_operario_activo():
        abort(404)

    from app.services.pin_auth_service import debe_cambiar_pin
    if debe_cambiar_pin(current_user):
        return redirect(url_for('operarios.cambiar_pin', obligatorio=1))

    contexto = estado_para_pantalla(current_user)
    return render_template('operario/fichar.html', **contexto)


@operarios_bp.route('/definir-pin', methods=['GET', 'POST'])
@limiter.limit('10 per minute; 40 per hour', methods=['POST'])
def definir_pin():
    """Define el PIN desde el enlace del correo (sin sesión ni PIN previo)."""
    from app.services.pin_auth_service import (
        PinAuthError,
        definir_pin_desde_token,
        leer_token_definir_pin,
    )

    if not getattr(g, 'current_tenant', None):
        flash('Accede desde la URL de tu empresa.', 'warning')
        return redirect(url_for('operarios.entrar'))

    token = (request.values.get('t') or '').strip()
    if not token:
        flash('El enlace para definir el PIN no es válido.', 'danger')
        return redirect(url_for('operarios.entrar'))

    # Validación temprana en GET para mostrar error claro si el token caducó.
    if request.method == 'GET':
        try:
            leer_token_definir_pin(token, g.current_tenant)
        except PinAuthError as exc:
            flash(str(exc), 'danger')
            return redirect(url_for('operarios.entrar'))

    if request.method == 'POST':
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
            flash('PIN guardado. Ya puedes fichar.', 'success')
            return redirect(url_for('operarios.inicio'))
        except PinAuthError as exc:
            db.session.rollback()
            flash(str(exc), 'danger')

    return render_template(
        'operario/definir_pin.html',
        token=token,
        activo='pin',
    )


@operarios_bp.route('/pin', methods=['GET', 'POST'])
@limiter.limit('20 per minute; 60 per hour', methods=['POST'])
def cambiar_pin():
    """Cambio de PIN (voluntario) o primer cambio obligatorio tras PIN generado."""
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
            if obligatorio or debe_cambiar_pin(current_user):
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
            flash('PIN actualizado.', 'success')
            return redirect(url_for('operarios.inicio'))
        except PinAuthError as exc:
            db.session.rollback()
            flash(str(exc), 'danger')

    return render_template(
        'operario/cambiar_pin.html',
        obligatorio=obligatorio or debe_cambiar_pin(current_user),
        activo='pin',
    )


@operarios_bp.route('/ausencias', methods=['GET', 'POST'])
@limiter.limit('20 per minute; 60 per hour', methods=['POST'])
def ausencias():
    """Solicitar vacaciones/permisos y ver el estado (pendiente → aprobación oficina)."""
    from app.models import LEAVE_STATUS_PENDIENTE, LEAVE_SOURCE_MANUAL
    from app.services.leave_service import (
        delete_manual_leave,
        leaves_del_usuario,
        solicitar_ausencia_propia,
    )
    from app.services.permission_service import user_can
    from app.utils import register_log

    if current_user.role == ROLE_OPERARIO:
        need = 'w' if request.method == 'POST' else 'r'
        if not user_can(current_user, 'operario_ausencias', need):
            flash('No tienes permiso para gestionar ausencias.', 'warning')
            return redirect(url_for('operarios.inicio'))

    if request.method == 'POST':
        accion = (request.form.get('accion') or 'solicitar').strip()
        if accion == 'cancelar':
            leave_id = request.form.get('leave_id', type=int)
            try:
                delete_manual_leave(leave_id, current_user)
                flash('Solicitud cancelada.', 'success')
            except Exception as exc:
                flash(str(exc), 'danger')
            return redirect(url_for('operarios.ausencias'))

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
                'Solicitud enviada. Queda pendiente de que oficina o RRHH la aprueben.',
                'success',
            )
        except Exception as exc:
            flash(str(exc), 'danger')
        return redirect(url_for('operarios.ausencias'))

    items = leaves_del_usuario(current_user.id, limit=50)
    return render_template(
        'operario/ausencias.html',
        ausencias=items,
        activo='ausencias',
        LEAVE_STATUS_PENDIENTE=LEAVE_STATUS_PENDIENTE,
        LEAVE_SOURCE_MANUAL=LEAVE_SOURCE_MANUAL,
    )


@operarios_bp.route('/fichar', methods=['POST'])
@limiter.limit('30 per minute; 200 per hour')
def api_fichar():
    """
    Registra un fichaje y devuelve el estado actualizado.

    Responde siempre en JSON: la pantalla se refresca sola sin recargar, que
    en una obra con cobertura mala importa más de lo que parece.
    """
    from app.services.pin_auth_service import debe_cambiar_pin
    if debe_cambiar_pin(current_user):
        return jsonify({
            'ok': False,
            'error': 'Debes cambiar el PIN antes de fichar.',
            'must_change_pin': True,
        }), 403

    datos = request.get_json(silent=True) or request.form

    try:
        estado = fichar(
            user=current_user,
            tipo=(datos.get('tipo') or '').strip(),
            obra_id=datos.get('obra_id') or None,
            latitud=_numero(datos.get('latitud')),
            longitud=_numero(datos.get('longitud')),
            precision_metros=_numero(datos.get('precision_metros')),
            ip=_ip(),
            dispositivo=_dispositivo(),
        )
    except FichajeLedgerError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    except Exception:
        current_app.logger.exception('Fallo al registrar un fichaje desde la PWA')
        return jsonify({
            'ok': False,
            'error': 'No se ha podido registrar el fichaje. Inténtalo de nuevo.',
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


@operarios_bp.route('/conformar', methods=['POST'])
@limiter.limit('20 per minute; 100 per hour')
def api_conformar():
    """Conforme digital del trabajador sobre la jornada del día (firma en el libro)."""
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
            'error': 'No se ha podido registrar el conforme. Inténtalo de nuevo.',
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


def _rango_solicitado():
    hasta = today_local()
    desde = hasta - timedelta(days=30)

    try:
        if request.args.get('desde'):
            desde = datetime.strptime(request.args['desde'], '%Y-%m-%d').date()
        if request.args.get('hasta'):
            hasta = datetime.strptime(request.args['hasta'], '%Y-%m-%d').date()
    except ValueError:
        flash('Las fechas indicadas no son válidas; se muestra el último mes.', 'warning')
        return today_local() - timedelta(days=30), today_local()

    if desde > hasta:
        desde, hasta = hasta, desde
    if (hasta - desde).days > MAX_DIAS_HISTORIAL:
        desde = hasta - timedelta(days=MAX_DIAS_HISTORIAL)

    return desde, hasta


@operarios_bp.route('/registros')
def registros():
    """
    El trabajador consultando sus propios fichajes.

    Esto no depende de que la empresa active nada: el derecho a consultar el
    registro propio es del trabajador, no una función que se contrate.
    """
    desde, hasta = _rango_solicitado()
    return render_template(
        'operario/registros.html',
        **historial(current_user.id, desde, hasta),
    )


@operarios_bp.route('/registros.csv')
@limiter.limit('10 per minute')
def registros_csv():
    """Descarga del registro propio, en un formato que se abre en cualquier sitio."""
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
        # BOM para que Excel en español no destroce los acentos al abrirlo.
        '\ufeff' + buffer.getvalue(),
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename="{archivo}"'},
    )


@operarios_bp.route('/manifest.webmanifest')
def manifest():
    """
    El manifiesto se genera al vuelo para que la app instalada lleve el nombre
    de la empresa y no el de la plataforma.
    """
    nombre = g.current_tenant.nombre if getattr(g, 'current_tenant', None) else 'SignaPlan'
    return jsonify({
        'name': f'Fichaje · {nombre}',
        'short_name': 'Fichaje',
        'description': f'Registro de jornada de {nombre}',
        'start_url': url_for('operarios.inicio'),
        'scope': url_for('operarios.inicio'),
        'display': 'standalone',
        'orientation': 'portrait',
        'background_color': '#0f172a',
        'theme_color': '#0f172a',
        'lang': 'es',
        'icons': [
            {
                'src': url_for('static', filename='img/brand/logo-mark.png'),
                'sizes': 'any',
                'type': 'image/svg+xml',
                'purpose': 'any maskable',
            },
        ],
    })


@operarios_bp.route('/sw.js')
def service_worker():
    """
    Se sirve desde /mi/ para que su alcance sea solo el área de fichaje y no
    intercepte nada del panel de administración.
    """
    respuesta = current_app.send_static_file('js/fichaje-sw.js')
    respuesta.headers['Content-Type'] = 'application/javascript'
    respuesta.headers['Service-Worker-Allowed'] = '/mi/'
    # Sin esto, un móvil puede quedarse con un service worker viejo semanas.
    respuesta.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return respuesta
