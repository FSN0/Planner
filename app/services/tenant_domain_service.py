import re

from app.models import Tenant

_CUSTOM_DOMAIN_RE = re.compile(
    r'^(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$'
)
_RESERVED_SUBDOMAINS = frozenset({'www', 'admin', 'superadmin', 'signaplan'})
_MARKETING_HOSTS = frozenset({'signaplan.com', 'www.signaplan.com'})


def normalize_host(host):
    """Normaliza un host HTTP (sin puerto, minúsculas)."""
    return (host or '').split(':')[0].lower().strip().rstrip('.')


def validate_custom_domain(domain):
    """
    Valida y normaliza un dominio propio de cliente.
    Devuelve None si el valor está vacío (sin dominio personalizado).
    """
    domain = normalize_host(domain)
    if not domain:
        return None

    if not _CUSTOM_DOMAIN_RE.match(domain):
        raise ValueError(
            'Dominio no válido. Usa un hostname completo, por ejemplo planner.empresa.com'
        )

    if domain == 'signaplan.com' or domain.endswith('.signaplan.com'):
        raise ValueError(
            'Los dominios *.signaplan.com se resuelven por subdominio; '
            'no hace falta registrar uno como dominio propio.'
        )

    return domain


def assert_custom_domain_available(domain, tenant_id=None):
    """Comprueba que el dominio no esté asignado a otro tenant."""
    if not domain:
        return

    existing = Tenant.query.filter_by(custom_domain=domain).first()
    if existing and existing.id != tenant_id:
        raise ValueError(f"El dominio '{domain}' ya está asignado a {existing.nombre}.")


def is_marketing_host(host):
    """True en el dominio raíz público (escaparate comercial)."""
    return normalize_host(host) in _MARKETING_HOSTS


def is_signaplan_host(host):
    """True si el host pertenece al dominio SaaS (subdominio, no dominio propio)."""
    host = normalize_host(host)
    return host == 'signaplan.com' or host.endswith('.signaplan.com')


def resolve_tenant_by_custom_domain(host):
    """Busca un tenant activo por dominio propio (hostname completo)."""
    host = normalize_host(host)
    if not host or is_signaplan_host(host):
        return None
    return Tenant.query.filter_by(custom_domain=host, is_active=True).first()


def resolve_tenant_by_subdomain(subdomain):
    """Busca un tenant activo por subdominio SignaPlan (ej. soltec)."""
    subdomain = (subdomain or '').lower().strip()
    if not subdomain or subdomain in _RESERVED_SUBDOMAINS:
        return None
    return Tenant.query.filter_by(subdominio=subdomain, is_active=True).first()


def resolve_tenant_by_hub_host(host):
    """
    Resuelve tenant cuando el host es un dominio de despliegue Hub (ej. planner.soltecgrupo.es)
    listado en HUB_SSO_TENANTS junto al subdominio del tenant (ej. soltec).
    """
    from flask import current_app

    host = normalize_host(host)
    if not host:
        return None

    raw = current_app.config.get('HUB_SSO_TENANTS') or 'soltec'
    entries = [part.strip().lower() for part in raw.split(',') if part.strip()]
    if host not in entries:
        return None

    for entry in entries:
        if '.' not in entry:
            tenant = resolve_tenant_by_subdomain(entry)
            if tenant:
                return tenant
    return None


def is_host_allowed_for_tls(domain):
    """Indica si Caddy puede emitir certificado para este hostname."""
    domain = normalize_host(domain)
    if not domain:
        return False

    if domain in ('signaplan.com', 'www.signaplan.com', 'admin.signaplan.com'):
        return True

    if not is_signaplan_host(domain) and resolve_tenant_by_custom_domain(domain):
        return True

    parts = domain.split('.')
    if is_signaplan_host(domain) and len(parts) >= 3:
        return resolve_tenant_by_subdomain(parts[0]) is not None

    return False
