# app/empleado/routes.py
#
# Portal web del operario (email/contraseña). Separado de /mi (DNI+PIN fichaje).
# Sin valoraciones. Solo datos propios. Requiere User.web_access.

from datetime import timedelta

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.decorators import roles_required
from app.empleado import empleado_bp
from app.models import (
    ROLE_OPERARIO,
    Asignacion,
    Obra,
)
from app.utils.timezone_utils import today_local


@empleado_bp.before_request
def _solo_operario_con_web():
    if not current_user.is_authenticated:
        return None
    if current_user.role != ROLE_OPERARIO:
        flash('Acceso no autorizado', 'danger')
        return redirect(url_for('auth.login'))
    from app.services.permission_service import user_can
    if not user_can(current_user, 'operario_web', 'r'):
        flash(
            'Tu perfil no tiene acceso al portal web. '
            'Pide a administración que active el permiso de operario.',
            'warning',
        )
        try:
            from app.services.fichaje_operario_service import fichaje_operario_activo
            if fichaje_operario_activo() and user_can(current_user, 'operario_fichaje', 'r'):
                return redirect(url_for('operarios.inicio'))
        except Exception:
            pass
        return redirect(url_for('auth.login'))
    if not getattr(current_user, 'web_access', False):
        flash(
            'Tu cuenta no tiene acceso a la plataforma web. '
            'Usa el fichaje con DNI y PIN o pide acceso a administración.',
            'warning',
        )
        try:
            from app.services.fichaje_operario_service import fichaje_operario_activo
            if fichaje_operario_activo() and user_can(current_user, 'operario_fichaje', 'r'):
                return redirect(url_for('operarios.inicio'))
        except Exception:
            pass
        return redirect(url_for('auth.login'))
    from app.services.permission_guard import enforce_empleado_permissions
    return enforce_empleado_permissions()


@empleado_bp.route('/')
@login_required
@roles_required(ROLE_OPERARIO, redirect_to='auth.login')
def inicio():
    hoy = today_local()
    fin_semana = hoy + timedelta(days=6)

    asignaciones = (
        Asignacion.query.filter(
            Asignacion.user_id == current_user.id,
            Asignacion.fecha >= hoy,
            Asignacion.fecha <= fin_semana,
        )
        .order_by(Asignacion.fecha)
        .all()
    )
    obra_ids = {a.obra_id for a in asignaciones if a.obra_id}
    obras = {
        o.id: o for o in Obra.query.filter(Obra.id.in_(obra_ids)).all()
    } if obra_ids else {}

    hoy_asigs = [
        {
            'obra': obras.get(a.obra_id).nombre if obras.get(a.obra_id) else '—',
            'codigo': getattr(obras.get(a.obra_id), 'codigo', None),
        }
        for a in asignaciones
        if a.fecha == hoy
    ]
    semana = [
        {
            'fecha': a.fecha,
            'obra': obras.get(a.obra_id).nombre if obras.get(a.obra_id) else '—',
            'codigo': getattr(obras.get(a.obra_id), 'codigo', None),
        }
        for a in asignaciones
    ]

    return render_template(
        'empleado/inicio.html',
        hoy=hoy,
        hoy_asigs=hoy_asigs,
        semana=semana,
        fin_semana=fin_semana,
    )


@empleado_bp.route('/calendario')
@login_required
@roles_required(ROLE_OPERARIO, redirect_to='auth.login')
def calendario():
    return render_template('empleado/calendario.html', worker=current_user)


@empleado_bp.route('/fichajes')
@login_required
@roles_required(ROLE_OPERARIO, redirect_to='auth.login')
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
@roles_required(ROLE_OPERARIO, redirect_to='auth.login')
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
                flash('Solicitud cancelada.', 'success')
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
                'Solicitud enviada. Queda pendiente de aprobación.',
                'success',
            )
        except Exception as exc:
            flash(str(exc), 'danger')
        return redirect(url_for('empleado.ausencias'))

    items = leaves_del_usuario(current_user.id, limit=100)
    return render_template('empleado/ausencias.html', ausencias=items)
