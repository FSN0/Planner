import json
import os
from flask import g
from sqlalchemy import text

os.environ.setdefault("FLASK_DEBUG", "0")

from app import create_app, db
from app.models import Tenant
from app.sync.adapters.odoo_soltec import Adapter

app = create_app()
with app.app_context():
    tenants = Tenant.query.order_by(Tenant.id).all()
    print(
        "tenants:",
        [
            (
                t.id,
                t.subdominio,
                t.schema_name,
                bool((t.modulos_activos or {}).get("odoo")),
            )
            for t in tenants
        ],
    )

    preferred = None
    for t in tenants:
        if t.subdominio == "soltec" or (t.schema_name or "") == "tenant_soltec":
            preferred = t
            break
    if preferred is None:
        for t in tenants:
            if (t.modulos_activos or {}).get("odoo"):
                preferred = t
                break
    if preferred is None and tenants:
        preferred = tenants[0]
    if preferred is None:
        print("NO_TENANTS")
        raise SystemExit(1)

    print("USING_TENANT:", preferred.id, preferred.subdominio, preferred.schema_name)
    db.session.execute(text(f"SET search_path TO {preferred.schema_name}, public"))
    g.current_tenant = preferred

    try:
        adapter = Adapter(tenant_id=preferred.id)
        print("ADAPTER_OK url=", adapter.url, "db=", adapter.db_name, "uid=", adapter.uid)
    except Exception as e:
        print("ADAPTER_ERROR:", type(e).__name__, e)
        raise SystemExit(2)

    for model in ("hr.attendance", "partner.attendance"):
        print("\n====", model, "====")
        try:
            print("MODEL_EXISTS:", adapter._odoo_model_exists(model))
        except Exception as e:
            print("MODEL_EXISTS_ERROR:", e)
        try:
            field = adapter._estado_fichaje_field(model)
            print("FOUND_FIELD:", field)
        except Exception as e:
            print("FIELD_ERROR:", type(e).__name__, e)
            field = None
        try:
            available = adapter._odoo_fields_get(model) or {}
            sels = []
            for n, m in sorted(available.items()):
                if not isinstance(m, dict):
                    continue
                if (m.get("type") or "") != "selection":
                    continue
                sel = m.get("selection")
                sample = None
                if isinstance(sel, (list, tuple)):
                    sample = list(sel)[:12]
                elif sel:
                    sample = str(sel)[:160]
                sels.append(
                    {"name": n, "string": m.get("string"), "selection_sample": sample}
                )
            print("SELECTION_FIELDS_COUNT:", len(sels))
            print(json.dumps(sels, ensure_ascii=False, indent=2, default=str))
            candidates = []
            for n, m in sorted(available.items()):
                if not isinstance(m, dict):
                    continue
                nl = n.lower()
                sl = (m.get("string") or "").lower()
                if any(k in nl or k in sl for k in ("estado", "state", "status", "draft", "valid")):
                    candidates.append(
                        {
                            "name": n,
                            "string": m.get("string"),
                            "type": m.get("type"),
                            "selection_sample": (
                                list(m.get("selection") or [])[:8]
                                if isinstance(m.get("selection"), (list, tuple))
                                else m.get("selection")
                            ),
                        }
                    )
            print("ESTADO_LIKE_FIELDS_COUNT:", len(candidates))
            print(json.dumps(candidates, ensure_ascii=False, indent=2, default=str))
        except Exception as e:
            print("FIELDS_GET_ERROR:", type(e).__name__, e)
