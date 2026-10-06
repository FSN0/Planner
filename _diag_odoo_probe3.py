"""Call get_fichajes_diarios and count estado_odoo presence in adapter output."""
import os
from collections import Counter
from flask import g
from sqlalchemy import text

os.environ.setdefault("FLASK_DEBUG", "0")
from app import create_app, db
from app.models import Tenant
from app.sync.adapters.odoo_soltec import Adapter

app = create_app()
with app.app_context():
    t = Tenant.query.filter_by(subdominio="soltec").one()
    db.session.execute(text(f"SET search_path TO {t.schema_name}, public"))
    g.current_tenant = t
    a = Adapter(tenant_id=t.id)

    # Confirm code path in container
    import inspect
    src = inspect.getsource(a._append_attendance_fichaje)
    print("HAS_estado_odoo_in__append_attendance_fichaje:", "estado_odoo" in src)
    print("hr field:", a._estado_fichaje_field("hr.attendance"))
    print("partner field:", a._estado_fichaje_field("partner.attendance"))

    rows = a.get_fichajes_diarios()
    print("get_fichajes_diarios count:", len(rows) if rows else 0)
    c = Counter()
    origins = Counter()
    for r in rows or []:
        eo = r.get("estado_odoo")
        c[eo if eo is not None else "NULL"] += 1
        origins[r.get("origen") or r.get("fuente") or r.get("modelo") or "unknown"] += 1
        # try detect model via keys
        if "odoo_model" in r:
            origins[str(r.get("odoo_model"))] += 1
    print("estado_odoo distribution in adapter output:", dict(c))
    # sample keys
    if rows:
        print("sample keys:", sorted(rows[0].keys()))
        # show a few with/without estado
        for r in (rows or [])[:5]:
            print(
                " sample:",
                {
                    k: r.get(k)
                    for k in (
                        "odoo_id",
                        "estado_odoo",
                        "empleado_id",
                        "partner_id",
                        "nombre",
                        "check_in",
                        "tipo",
                    )
                    if k in r or True
                },
            )
        # count how many have employee vs partner-ish
        empish = sum(1 for r in rows if r.get("empleado_odoo_id") or r.get("employee_id"))
        print("rows with employee-ish id fields:", empish)
        print("non-null estado_odoo samples:")
        shown = 0
        for r in rows:
            if r.get("estado_odoo") is not None:
                print(" ", {k: r.get(k) for k in ("odoo_id", "estado_odoo", "nombre", "check_in")})
                shown += 1
                if shown >= 5:
                    break
        if shown == 0:
            print("  (none)")
