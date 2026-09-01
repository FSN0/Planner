"""Política de acceso por tenant (PIN vs contraseña)."""
from __future__ import annotations

from app.services.fichaje_operario_service import fichaje_operario_activo
from app.services.tenant_modules import is_soltec_tenant


def tenant_usa_acceso_pin(tenant=None) -> bool:
    """
    True si el tenant usa el flujo DNI+PIN del operario (PWA fichaje).

    Soltec y clientes sin portal de fichaje operativo usan solo contraseña.
    """
    if is_soltec_tenant(tenant):
        return False
    return fichaje_operario_activo()


def enforce_password_only_user(user) -> None:
    """Fuerza contraseña como único modo de acceso (sin PIN)."""
    user.auth_mode = 'password'
