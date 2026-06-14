from datetime import date

from flask import Blueprint, flash, g, redirect, request, session, url_for
from flask_login import current_user, login_user, logout_user
from sqlalchemy import func

from app import csrf
from app.auth.routes import LOGIN_BLOCKED_ROLES
from app.models import User
from app.services.hub_sso_service import get_authentik_identity, hub_sso_enabled_for_tenant

hub_sso_bp = Blueprint("hub_sso", __name__)


def _redirect_authenticated_user():
    if current_user.role == "admin":
        return redirect(url_for("admin.panel"))
    if current_user.role == "jefe_obra":
        return redirect(url_for("jefe.obras_detailed", selected_date=date.today()))
    logout_user()
    flash("Tu perfil no tiene acceso a la aplicacion.", "warning")
    return redirect(url_for("auth.login"))


def _redirect_after_login(user):
    if user.role == "admin":
        return redirect(url_for("admin.panel"))
    if user.role == "jefe_obra":
        return redirect(url_for("jefe.obras_detailed", selected_date=date.today()))
    logout_user()
    flash("Tu perfil no tiene acceso a la aplicacion.", "warning")
    return redirect(url_for("auth.login"))


@hub_sso_bp.route("/sso/hub")
def sso_hub():
    tenant = getattr(g, "current_tenant", None)
    if not tenant or not hub_sso_enabled_for_tenant(tenant):
        flash("El inicio de sesion con Hub no esta disponible para esta organizacion.", "warning")
        return redirect(url_for("auth.login"))

    if current_user.is_authenticated:
        return _redirect_authenticated_user()

    ident = get_authentik_identity()
    email = (ident["email"] or ident["username"] or "").strip()
    if not email:
        flash(
            "No se detecto sesion del Hub. Entra primero en el Hub de aplicaciones "
            "o usa email y contrasena.",
            "warning",
        )
        return redirect(url_for("auth.login"))

    user = User.query.filter(func.lower(User.email) == email.lower()).first()
    if not user:
        flash("Usuario no registrado en SignaPlan.", "warning")
        return redirect(url_for("auth.login"))

    if user.role in LOGIN_BLOCKED_ROLES:
        from app.utils import register_log

        register_log(
            user_id=user.id,
            category="accesos",
            action="Acceso denegado",
            detail=(
                f"Intento de login Hub con rol sin acceso ({user.role}). "
                f"IP: {request.remote_addr or 'Desconocida'}"
            ),
        )
        flash(
            "Tu perfil no tiene acceso a la aplicacion. Contacta con administracion.",
            "warning",
        )
        return redirect(url_for("auth.login"))

    if not user.is_active:
        flash("Tu cuenta aun no esta activa. Espera la aprobacion de RRHH.", "warning")
        return redirect(url_for("auth.login"))

    login_user(user, remember=True)
    session["tenant_id"] = tenant.id
    from app.utils import register_log

    register_log(
        user_id=user.id,
        category="accesos",
        action="Inicio de Sesion",
        detail=(
            f"Login Hub exitoso ({email}, uid={ident.get('uid') or 'n/a'}). "
            f"IP: {request.remote_addr or 'Desconocida'}"
        ),
    )
    flash("Inicio de sesion exitoso", "success")
    return _redirect_after_login(user)


csrf.exempt(sso_hub)
