#!/usr/bin/env python3
"""Muestra las credenciales Odoo guardadas en un tenant (descifra la contraseña).

Uso:
  python scripts/show_odoo_creds.py              # lista tenants
  python scripts/show_odoo_creds.py soltec       # volcado de ese tenant
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sqlalchemy import text

from app import create_app, db, is_safe_schema_name
from app.models import Tenant


def match_tenants(tenants, needle):
    n = (needle or '').strip().lower()
    if not n:
        return []
    exact = [
        t for t in tenants
        if (t.subdominio or '').lower() == n or (t.schema_name or '').lower() == n
    ]
    if exact:
        return exact
    return [
        t for t in tenants
        if n in (t.subdominio or '').lower()
        or n in (t.schema_name or '').lower()
        or n in (t.nombre or '').lower()
    ]


def _print_tenant_table(tenants):
    if not tenants:
        print('No hay tenants en public.tenants.')
        return
    rows = [('subdominio', 'esquema', 'nombre', 'activo')]
    rows += [
        (
            t.subdominio or '',
            t.schema_name or '',
            t.nombre or '',
            'sí' if t.is_active else 'no',
        )
        for t in tenants
    ]
    widths = [max(len(r[i]) for r in rows) for i in range(4)]
    for i, row in enumerate(rows):
        line = '  '.join(cell.ljust(widths[j]) for j, cell in enumerate(row))
        print(line)
        if i == 0:
            print('  '.join('-' * widths[j] for j in range(4)))


def _list_and_usage(tenants, *, error=None):
    if error:
        print(error)
        print()
    print('Tenants:')
    print()
    _print_tenant_table(tenants)
    print()
    print('Uso:  make odoo-creds TENANT=soltec')
    print('      make odoo-creds-prod TENANT=soltec')


def _dump_creds(tenant):
    from flask import g
    from app.services.config_service import get_tenant_config

    schema = tenant.schema_name
    if not is_safe_schema_name(schema):
        print(f'Esquema no válido: {schema}', file=sys.stderr)
        return 1

    g.current_tenant = tenant
    db.session.execute(text(f'SET search_path TO {schema}, public'))

    url = get_tenant_config('odoo_url', default='') or ''
    odoo_db = get_tenant_config('odoo_db', default='') or ''
    user = get_tenant_config('odoo_user', default='') or ''
    cipher = get_tenant_config('odoo_password', default='') or ''
    password = get_tenant_config('odoo_password', desencriptar=True, default='') or ''

    print(f'Tenant:  {tenant.nombre}  ({tenant.subdominio})')
    print(f'Esquema: {schema}')
    print(f'URL:     {url or "(vacía)"}')
    print(f'Base:    {odoo_db or "(vacía)"}')
    print(f'Usuario: {user or "(vacío)"}')
    if not cipher:
        print('Clave:   (no hay contraseña guardada)')
    elif not password or password == cipher:
        print('Clave:   (no se pudo descifrar; revisa ENCRYPTION_KEY)')
    else:
        print(f'Clave:   {password}')
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description='Credenciales Odoo de un tenant')
    parser.add_argument(
        'tenant',
        nargs='?',
        default='',
        help='subdominio, esquema o nombre (si se omite, lista tenants)',
    )
    args = parser.parse_args(argv)

    app = create_app()
    with app.app_context():
        db.session.execute(text('SET search_path TO public'))
        tenants = Tenant.query.order_by(Tenant.subdominio.asc()).all()

        needle = (args.tenant or '').strip()
        if not needle:
            _list_and_usage(tenants)
            return 0

        matches = match_tenants(tenants, needle)
        if len(matches) == 1:
            return _dump_creds(matches[0])
        if len(matches) > 1:
            _list_and_usage(
                matches,
                error=f'Varios tenants coinciden con "{needle}". Elige el subdominio exacto:',
            )
            return 2
        _list_and_usage(
            tenants,
            error=f'Ningún tenant coincide con "{needle}".',
        )
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
