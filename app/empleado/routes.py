# app/empleado/routes.py
#
# Portal de jornada del trabajador (/fichaje): fichar, calendario, ausencias.
# Acceso por permisos operario_*; mismo shell lateral que el resto de la app.

from datetime import timedelta

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app import limiter
from app.empleado import empleado_bp
from app.models import (
    ROLE_OPERARIO,
    Asignacion,
    Obra,
)
from app.utils.timezone_utils import today_local
from app.services.i18n_service import translate


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


@empleado_bp.before_request
def _portal_jornada_guard():
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
    from app.services.fichaje_operario_service import tenant_tiene_fichaje_operario_module
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
    from app.services.fichaje_operario_service import (
        estado_para_pantalla,
        fichaje_operario_activo,
        tenant_tiene_fichaje_operario_module,
    )
    from app.services.permission_service import user_can
    from app.services.pin_auth_service import debe_cambiar_pin

    if not tenant_tiene_fichaje_operario_module():
        abort(404)
    if not user_can(current_user, 'operario_fichaje', 'r'):
        abort(403)

    if not fichaje_operario_activo():
        return render_template(
            'empleado/fichaje_desactivado.html',
            puede_activar=current_user.role == 'admin',
        )

    if debe_cambiar_pin(current_user):
        flash(translate('Debes cambiar el PIN antes de fichar.'), 'warning')
        return redirect(url_for('empleado.cambiar_pin', obligatorio=1))

    contexto = estado_para_pantalla(current_user)
    return render_template('empleado/fichar.html', **contexto)


@empleado_bp.route('/fichajes')
@login_required
def fichajes():
    from app.services.fichaje_operario_service import (
        fichaje_operario_activo,
        historial,
    )

    if not fichaje_operario_activo():
        abort(404)

    datos = historial(current_user.id)
    return render_template('empleado/fichajes.html', **datos)


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
            from app import db
            db.session.commit()
            flash(translate('PIN actualizado.'), 'success')
            return redirect(url_for('empleado.fichar'))
        except PinAuthError as exc:
            from app import db
            db.session.rollback()
            flash(str(exc), 'danger')

    return render_template(
        'empleado/cambiar_pin.html',
        obligatorio=obligatorio,
    )
