#!/usr/bin/env python3
"""Probe hr.attendance for statusbar/state field (tenant soltec)."""
import json
import logging
import re

logging.basicConfig(level=logging.WARNING)

KEYWORDS = (
    "state", "estado", "status", "studio", "invoice", "valid",
    "draft", "factur", "borra",
)


def match_kw(s):
    s = (s or "").lower()
    return any(k in s for k in KEYWORDS)


def main():
    from app import create_app
    app = create_app()
    with app.app_context():
        from sqlalchemy import text
        from flask import g
        from app import db
        from app.models import Tenant
        from app.sync.adapters.odoo_soltec import Adapter

        t = (
            Tenant.query.filter_by(subdominio="soltec").first()
            or Tenant.query.filter(Tenant.schema_name == "tenant_soltec").first()
        )
        print("TENANT", t.id if t else None, getattr(t, "subdominio", None), getattr(t, "schema_name", None))
        if not t:
            raise SystemExit("Tenant soltec no encontrado")
        # Adapter reads Odoo creds via get_tenant_config → needs tenant schema
        g.tenant = t
        db.session.execute(text(f"SET search_path TO {t.schema_name}, public"))
        adapter = Adapter(tenant_id=t.id)
        print("ODOO", adapter.db_name, "uid", adapter.uid)

        fields = adapter._odoo_fields_get("hr.attendance") or {}

        print("\n=== 1. hr.attendance fields matching keywords (name/type/string) ===")
        hits = []
        for name, meta in sorted(fields.items()):
            if not isinstance(meta, dict):
                continue
            if (
                match_kw(name)
                or match_kw(meta.get("string"))
                or match_kw(str(meta.get("selection") or ""))
            ):
                hits.append({
                    "name": name,
                    "type": meta.get("type"),
                    "string": meta.get("string"),
                    "selection": meta.get("selection") if (meta.get("type") or "") == "selection" else None,
                })
        print("COUNT", len(hits))
        print(json.dumps(hits, ensure_ascii=False, indent=2, default=str))

        print("\n=== 2. ALL x_* fields on hr.attendance ===")
        xfields = []
        for name, meta in sorted(fields.items()):
            if name.startswith("x_") and isinstance(meta, dict):
                xfields.append({
                    "name": name,
                    "type": meta.get("type"),
                    "string": meta.get("string"),
                    "selection": meta.get("selection") if (meta.get("type") or "") == "selection" else None,
                })
        print("COUNT", len(xfields))
        print(json.dumps(xfields, ensure_ascii=False, indent=2, default=str))

        print("\n=== 3. ir.model.fields for hr.attendance (keyword filter) ===")
        rows = adapter.models.execute_kw(
            adapter.db_name, adapter.uid, adapter.pwd,
            "ir.model.fields", "search_read",
            [[("model", "=", "hr.attendance")]],
            {
                "fields": [
                    "name", "ttype", "field_description", "selection",
                    "state", "store", "related", "compute", "readonly",
                ],
                "limit": 1000,
            },
        )
        filtered = []
        for r in rows or []:
            blob = " ".join(str(r.get(k) or "") for k in (
                "name", "ttype", "field_description", "selection", "related", "compute",
            ))
            if match_kw(blob):
                filtered.append(r)
        print("TOTAL_FIELDS_ON_MODEL", len(rows or []))
        print("MATCHING", len(filtered))
        print(json.dumps(filtered, ensure_ascii=False, indent=2, default=str))

        print("\n=== 4. ir.ui.view arch for hr.attendance (statusbar/state/estado) ===")
        views = adapter.models.execute_kw(
            adapter.db_name, adapter.uid, adapter.pwd,
            "ir.ui.view", "search_read",
            [[
                ("model", "=", "hr.attendance"),
                ("type", "in", ["form", "tree", "kanban", "search"]),
            ]],
            {"fields": ["id", "name", "type", "inherit_id", "arch_db", "key"], "limit": 200},
        )
        print("VIEWS_COUNT", len(views or []))
        for v in views or []:
            arch = v.get("arch_db") or ""
            arch_l = arch.lower()
            if not any(k in arch_l for k in (
                "statusbar", "state", "estado", "status", "draft", "validated", "invoiced",
            )):
                continue
            print("--- VIEW", v.get("id"), v.get("name"), v.get("type"),
                  "inherit", v.get("inherit_id"), "key", v.get("key"))
            # field name=... near statusbar / state / estado
            for m in re.finditer(
                r'<(?:field|button)[^>]*(?:name|widget)=["\'][^"\']*(?:state|estado|status|statusbar)[^"\']*["\'][^>]*/?>',
                arch, flags=re.I,
            ):
                print("  TAG:", m.group(0)[:300])
            for m in re.finditer(r'statusbar[^>]{0,200}', arch, flags=re.I):
                start = max(0, m.start() - 120)
                print("  STATUSBAR_CTX:", arch[start:m.end() + 80].replace("\n", " ")[:400])
            # also any name="..." containing state/estado
            for m in re.finditer(r'name=["\']([^"\']*(?:state|estado|status)[^"\']*)["\']', arch, flags=re.I):
                print("  NAME_ATTR:", m.group(1))

        print("\n=== 5. Sample 3 recent hr.attendance ===")
        xnames = [f["name"] for f in xfields]
        candidates = sorted(
            {h["name"] for h in hits}
            | set(xnames)
            | {"state", "status", "estado", "x_studio_state", "x_studio_estado", "x_estado", "x_status"}
        )
        rf = ["id", "check_in", "check_out", "employee_id", "project_id"]
        seen = set(rf)
        for c in candidates:
            if c in fields and c not in seen:
                rf.append(c)
                seen.add(c)
        print("READ_FIELDS", rf)
        try:
            recs = adapter.models.execute_kw(
                adapter.db_name, adapter.uid, adapter.pwd,
                "hr.attendance", "search_read",
                [[]],
                {"fields": rf, "limit": 3, "order": "id desc"},
            )
            print(json.dumps(recs, ensure_ascii=False, indent=2, default=str))
        except Exception as e:
            print("READ_ERROR", type(e).__name__, e)
            existing = [f for f in rf if f in fields or f == "id"]
            print("FALLBACK_FIELDS", existing)
            recs = adapter.models.execute_kw(
                adapter.db_name, adapter.uid, adapter.pwd,
                "hr.attendance", "search_read",
                [[]],
                {"fields": existing, "limit": 3, "order": "id desc"},
            )
            print(json.dumps(recs, ensure_ascii=False, indent=2, default=str))

        # Also try reading state even if not in fields_get (forces AccessError/ValueError if missing)
        print("\n=== 5b. Force-read state/status/estado on 3 latest ids ===")
        ids = adapter.models.execute_kw(
            adapter.db_name, adapter.uid, adapter.pwd,
            "hr.attendance", "search", [[]], {"limit": 3, "order": "id desc"},
        )
        for fname in ("state", "status", "estado", "x_studio_state", "x_studio_estado", "x_estado"):
            try:
                data = adapter.models.execute_kw(
                    adapter.db_name, adapter.uid, adapter.pwd,
                    "hr.attendance", "read",
                    [ids, ["id", fname]],
                )
                print(f"FORCE_OK {fname}:", data)
            except Exception as e:
                print(f"FORCE_FAIL {fname}:", type(e).__name__, str(e)[:200])

        print("\n=== 6. Partner DB null check + sync path ===")
        # search_path / g.tenant already set before Adapter
        rows_om = db.session.execute(text("""
            SELECT COALESCE(origen_modelo, '(null)') AS origen,
                   COUNT(*) AS n,
                   COUNT(estado_odoo) AS with_estado,
                   COUNT(*) FILTER (WHERE estado_odoo IS NULL) AS null_estado
            FROM registros_fichajes
            GROUP BY 1
            ORDER BY 2 DESC
        """)).fetchall()
        print("origen_modelo breakdown:")
        for r in rows_om:
            print(dict(r._mapping))

        # recent partner rows (updated_at may be missing)
        try:
            recent = db.session.execute(text("""
                SELECT id, origen_modelo, registro_external_id, fecha, estado_odoo, updated_at
                FROM registros_fichajes
                WHERE origen_modelo = 'partner.attendance'
                ORDER BY id DESC
                LIMIT 5
            """)).fetchall()
        except Exception as e:
            print("updated_at query failed:", type(e).__name__, str(e)[:200])
            db.session.rollback()
            db.session.execute(text(f"SET search_path TO {t.schema_name}, public"))
            recent = db.session.execute(text("""
                SELECT id, origen_modelo, registro_external_id, fecha, estado_odoo
                FROM registros_fichajes
                WHERE origen_modelo = 'partner.attendance'
                ORDER BY id DESC
                LIMIT 5
            """)).fetchall()
        print("recent partner.attendance DB rows:")
        for r in recent:
            print(dict(r._mapping))

        print("\nDONE")


if __name__ == "__main__":
    main()
