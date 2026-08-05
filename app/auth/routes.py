# app/auth/routes.py

from datetime import date

from flask import Blueprint, render_template, request, redirect, url_for, flash, g, session
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash

from app import limiter, db
from app.models import User, ROLE_OPERARIO, ROLE_RRHH, ROLE_LABORAL
from app.services.tenant_domain_service import is_marketing_host, normalize_host

auth_bp = Blueprint('auth', __name__)

LOGIN_BLOCKED_ROLES = (ROLE_OPERARIO,)


def _puede_login_web(user):
    """
    El operario solo entra al portal web si administración le activó web_access.
    El módulo de fichaje (/mi con DNI+PIN) NO desbloquea el login de oficina.
    """
    if user.role == ROLE_OPERARIO:
        return bool(getattr(user, 'web_access', False))
    return user.role not in LOGIN_BLOCKED_ROLES


def _marcar_email_pendiente(user):
    pending = hasattr(user, 'email_verified') and not user.email_verified
    session['email_pending_verification'] = pending
    return pending


def _login_page_context():
    fichaje_activo = False
    try:
        from app.services.fichaje_operario_service import fichaje_operario_activo
        fichaje_activo = fichaje_operario_activo()
    except Exception:
        pass
    return {
        'tenant_name': g.current_tenant.nombre,
        'fichaje_activo': fichaje_activo,
        'show_resend_verification': session.pop('show_resend_verification', False),
    }


def _destino_por_rol(user):
    """A dónde va cada perfil nada más entrar. None si no tiene sitio."""
    if user.role == 'admin':
        try:
            from app.services.onboarding_service import debe_redirigir_a_wizard
            if debe_redirigir_a_wizard():
                return url_for('admin.primeros_pasos')
        except Exception:
            pass
        return url_for('admin.panel')
    if user.role == 'jefe_obra':
        return url_for('jefe.obras_detailed', selected_date=date.today())
    if user.role in (ROLE_LABORAL, ROLE_RRHH):
        return url_for('admin.panel_laboral')
    if user.role == ROLE_OPERARIO:
        if getattr(user, 'web_access', False):
            return url_for('empleado.inicio')
        return None
    return None


def _redirect_authenticated_user():
    destino = _destino_por_rol(current_user)
    if destino:
        return redirect(destino)
    logout_user()
    flash('Tu perfil no tiene acceso a la aplicación.', 'warning')
    return redirect(url_for('auth.login'))


@auth_bp.route('/entrar-alta')
@limiter.limit('10 per minute; 30 per hour')
def entrar_alta():
    """
    Compatibilidad con enlaces antiguos de auto-login post-alta.
    El flujo actual pide verificación de correo (/auth/verificar-email),
    pero permite entrar con email pendiente (banner de verificación).
    """
    from app.services.signup_service import SignupError, leer_token_entrada_post_alta

    if not hasattr(g, 'current_tenant') or not g.current_tenant:
        flash('Accede desde la URL de tu empresa.', 'warning')
        return redirect(url_for('main.dashboard'))

    token = request.args.get('t') or ''
    try:
        email = leer_token_entrada_post_alta(token, g.current_tenant)
    except SignupError as exc:
        flash(str(exc), 'warning')
        return redirect(url_for('auth.login'))

    user = User.query.filter_by(email=email, is_deleted=False).first()
    if user is None or not user.is_active:
        flash('No se ha podido abrir la sesión. Entra con tu correo y contraseña.', 'warning')
        return redirect(url_for('auth.login'))

    if current_user.is_authenticated:
        logout_user()

    login_user(user, remember=True)
    session['tenant_id'] = g.current_tenant.id
    if _marcar_email_pendiente(user):
        flash(
            'Has entrado. Verifica tu correo cuando puedas; hasta entonces '
            'algunas acciones sensibles están limitadas.',
            'info',
        )
    try:
        from app.utils import register_log
        register_log(
            user_id=user.id,
            category='accesos',
            action='Entrada post-alta',
            detail=f"Login automático tras crear cuenta. IP: {request.remote_addr or 'Desconocida'}",
        )
    except Exception:
        pass

    destino = _destino_por_rol(user)
    return redirect(destino or url_for('admin.panel'))


@auth_bp.route('/verificar-email')
@limiter.limit('10 per minute; 30 per hour')
def verificar_email():
    """Confirma el correo del admin tras el alta y abre sesión en el tenant."""
    from app.services.email_verification_service import (
        EmailVerificationError,
        confirmar_email,
    )

    if not hasattr(g, 'current_tenant') or not g.current_tenant:
        flash('Accede desde la URL de tu empresa.', 'warning')
        return redirect(url_for('main.dashboard'))

    token = request.args.get('t') or ''
    try:
        user = confirmar_email(token, g.current_tenant)
    except EmailVerificationError as exc:
        flash(str(exc), 'danger')
        session['show_resend_verification'] = True
        return redirect(url_for('auth.login'))

    if current_user.is_authenticated:
        logout_user()

    # login_user lee is_active; el User debe estar fresco en el schema del tenant
    from sqlalchemy import text
    db.session.execute(
        text(f'SET search_path TO {g.current_tenant.schema_name}, public')
    )
    user = User.query.get(user.id)
    if user is None:
        flash('No se ha podido abrir la sesión. Entra con tu correo y contraseña.', 'warning')
        return redirect(url_for('auth.login'))

    login_user(user, remember=True)
    session['tenant_id'] = g.current_tenant.id
    session['email_pending_verification'] = False
    try:
        from app.utils import register_log
        register_log(
            user_id=user.id,
            category='accesos',
            action='Verificación de correo',
            detail=(
                f'Correo verificado tras alta. IP: {request.remote_addr or "Desconocida"}'
            ),
        )
    except Exception:
        pass

    flash('Correo verificado. Bienvenido a SignaPlan.', 'success')
    destino = _destino_por_rol(user)
    return redirect(destino or url_for('admin.panel'))


@auth_bp.route('/reenviar-verificacion', methods=['POST'])
@limiter.limit('3 per minute; 10 per hour')
def reenviar_verificacion():
    """Reenvía el correo de verificación (logueado o con email en el formulario)."""
    from app.services.email_verification_service import (
        EmailVerificationError,
        reenviar_verificacion as _reenviar,
    )
    from app.services.i18n_service import translate

    if not hasattr(g, 'current_tenant') or not g.current_tenant:
        flash('Accede desde la URL de tu empresa.', 'warning')
        return redirect(url_for('main.dashboard'))

    try:
        if current_user.is_authenticated:
            _reenviar(g.current_tenant, user=current_user)
        else:
            _reenviar(g.current_tenant, email=request.form.get('email'))
        flash(
            translate(
                'Si el correo está pendiente de verificación, te hemos enviado un nuevo enlace.'
            ),
            'info',
        )
    except EmailVerificationError as exc:
        flash(str(exc), 'danger')

    if current_user.is_authenticated:
        return redirect(request.referrer or url_for('admin.panel'))
    return redirect(url_for('auth.login'))


@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit('10 per minute; 50 per hour', methods=['POST'])
def login():
    from app.services.i18n_service import translate

    if current_user.is_authenticated:
        return _redirect_authenticated_user()

    if not hasattr(g, 'current_tenant') or not g.current_tenant:
        host = normalize_host(request.host)
        if is_marketing_host(host):
            flash('Accede desde la URL de tu empresa, por ejemplo tuempresa.signaplan.com', 'info')
            return redirect(url_for('main.dashboard'))
        if host == 'localhost':
            return redirect(url_for('superadmin.dashboard'))
        flash('Por favor, accede desde la URL específica de tu empresa.', 'warning')
        return redirect(url_for('main.dashboard'))

    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        remember = True if request.form.get('remember') == 'on' else False

        user = User.query.filter_by(email=email).first()

        if user and check_password_hash(user.password_hash, password):
            if not _puede_login_web(user):
                from app.utils import register_log
                register_log(
                    user_id=user.id,
                    category='accesos',
                    action='Acceso denegado',
                    detail=(
                        f"Intento de login con rol sin acceso web ({user.role}). "
                        f"IP: {request.remote_addr or 'Desconocida'}"
                    ),
                )
                flash(
                    translate(
                        'Tu perfil no tiene acceso a la aplicación. Contacta con administración.'
                    ),
                    'warning',
                )
                return render_template('login.html', **_login_page_context())

            if not user.is_active:
                flash(
                    translate(
                        'Tu cuenta aún no está activa. Espera la aprobación de RRHH.'
                    ),
                    'warning',
                )
                return render_template('login.html', **_login_page_context())

            login_user(user, remember=remember)
            session['tenant_id'] = g.current_tenant.id
            pending = _marcar_email_pendiente(user)
            from app.utils import register_log
            register_log(
                user_id=user.id,
                category='accesos',
                action='Inicio de Sesión',
                detail=f"Login exitoso desde IP: {request.remote_addr or 'Desconocida'}",
            )
            if pending:
                flash(
                    translate(
                        'Inicio de sesión correcto. Verifica tu correo cuando puedas.'
                    ),
                    'info',
                )
            else:
                flash(translate('Inicio de sesión exitoso'), 'success')

            destino = _destino_por_rol(user)
            if destino:
                return redirect(destino)

            logout_user()
            flash(translate('Tu perfil no tiene acceso a la aplicación.'), 'warning')
            return render_template('login.html', **_login_page_context())

        if user:
            from app.utils import register_log
            register_log(
                user_id=user.id,
                category='accesos',
                action='Intento fallido de login',
                detail=f"Contraseña incorrecta. IP: {request.remote_addr or 'Desconocida'}",
            )
        flash(translate('Credenciales inválidas'), 'danger')

    return render_template('login.html', **_login_page_context())


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    session.pop('email_pending_verification', None)
    from app.services.i18n_service import translate
    flash(translate('Sesión cerrada'), 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/recuperar', methods=['GET', 'POST'])
@limiter.limit('5 per minute; 20 per hour', methods=['POST'])
def recuperar():
    """Pide el correo y, si existe, envía el enlace de restablecimiento."""
    if not hasattr(g, 'current_tenant') or not g.current_tenant:
        flash('Accede desde la URL de tu empresa para recuperar la contraseña.', 'info')
        return redirect(url_for('main.dashboard'))

    if request.method == 'POST':
        from app.services.password_reset_service import PasswordResetError, solicitar_reset

        email = request.form.get('email')
        try:
            solicitar_reset(
                email,
                g.current_tenant,
                reset_url_builder=lambda token: url_for(
                    'auth.recuperar_token', token=token, _external=True
                ),
            )
        except PasswordResetError as exc:
            flash(str(exc), 'danger')
            return render_template(
                'auth_recuperar.html',
                tenant_name=g.current_tenant.nombre,
            )
        # Mensaje único: no delata si el correo existe.
        flash(
            'Si el correo está registrado, recibirás un enlace para restablecer la contraseña.',
            'info',
        )
        return redirect(url_for('auth.login'))

    return render_template(
        'auth_recuperar.html',
        tenant_name=g.current_tenant.nombre,
    )


@auth_bp.route('/recuperar/<token>', methods=['GET', 'POST'])
@limiter.limit('10 per minute; 30 per hour', methods=['POST'])
def recuperar_token(token):
    if not hasattr(g, 'current_tenant') or not g.current_tenant:
        flash('Accede desde la URL de tu empresa.', 'warning')
        return redirect(url_for('main.dashboard'))

    from app.services.password_reset_service import (
        PasswordResetError,
        aplicar_nueva_password,
        leer_token,
    )

    try:
        leer_token(token, g.current_tenant)
    except PasswordResetError as exc:
        flash(str(exc), 'danger')
        return redirect(url_for('auth.recuperar'))

    if request.method == 'POST':
        try:
            aplicar_nueva_password(
                token,
                g.current_tenant,
                request.form.get('password'),
                request.form.get('password2'),
            )
            flash('Contraseña actualizada. Ya puedes iniciar sesión.', 'success')
            return redirect(url_for('auth.login'))
        except PasswordResetError as exc:
            flash(str(exc), 'danger')

    return render_template(
        'auth_recuperar_nueva.html',
        tenant_name=g.current_tenant.nombre,
        token=token,
    )


# Aquí vivía /auth/register, un alta pública en la que cualquiera que supiese el
# código de una subcontrata podía crearse una cuenta en el tenant de esa empresa.
# Llevaba roto desde que se borró su plantilla y nadie lo echó de menos: las
# personas entran por la sincronización del ERP o las da de alta administración.
# El alta de empresa (crear tenant) está en signaplan.com/alta.
