"""Sample whether partner.attendance.state has values; confirm hr has no state."""
import os
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

    print("hr.attendance fields containing state/estado:", [
        n for n in (a._odoo_fields_get("hr.attendance") or {}) if "state" in n.lower() or "estado" in n.lower()
    ])
    print("partner.attendance fields containing state/estado:", [
        n for n in (a._odoo_fields_get("partner.attendance") or {}) if "state" in n.lower() or "estado" in n.lower()
    ])

    rows = a.models.execute_kw(
        a.db_name, a.uid, a.pwd,
        "partner.attendance", "search_read",
        [[]],
        {"fields": ["id", "state", "check_in", "check_out"], "limit": 10, "order": "id desc"},
    ) or []
    print("partner.attendance sample state values:")
    for r in rows:
        print(" ", r)

    # group count by state if possible
    try:
        grouped = a.models.execute_kw(
            a.db_name, a.uid, a.pwd,
            "partner.attendance", "read_group",
            [[]],
            {"fields": ["state"], "groupby": ["state"], "lazy": False},
        )
        print("partner.attendance state counts:", grouped)
    except Exception as e:
        print("read_group error:", e)

    # How many from each model would sync code see today?
    from datetime import date
    today = date.today().isoformat()
    for model in ("hr.attendance", "partner.attendance"):
        try:
            n = a.models.execute_kw(
                a.db_name, a.uid, a.pwd,
                model, "search_count",
                [[["check_in", ">=", today + " 00:00:00"]]],
            )
            print(f"{model} count check_in>={today}:", n)
        except Exception as e:
            print(f"{model} count error:", e)
