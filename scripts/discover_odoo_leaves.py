#!/usr/bin/env python3
"""
Descubre en Odoo qué modelos/campos usan para vacaciones / time off.
Uso (en el host donde ya tienes XML-RPC a Odoo):

  export ODOO_URL=https://odoo.soltecgrupo.es
  export ODOO_DB=db17-spain
  export ODOO_USER=admin
  export ODOO_PASSWORD='***'

  python3 discover_odoo_leaves.py
"""
from __future__ import annotations

import os
import xmlrpc.client

ODOO_URL = 'https://odoo.soltecgrupo.es'
ODOO_DB = 'db17-spain'
ODOO_USER = 'admin'
ODOO_PASSWORD = 'Soc0233Ssd4223aAs3367'

# Candidatos habituales en Odoo 14–17 (hr_holidays / time off)
CANDIDATE_MODELS = [
    "hr.leave",
    "hr.holidays",
    "hr.leave.allocation",
    "resource.calendar.leaves",
]


def connect():
    print(f"Conectando a {ODOO_URL} / DB={ODOO_DB} ...")
    common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
    uid = common.authenticate(ODOO_DB, ODOO_USER, ODOO_PASSWORD, {})
    if not uid:
        raise SystemExit("Auth Odoo fallida")
    models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")
    print(f"OK uid={uid}\n")
    return uid, models


def model_exists(models, uid, name: str) -> bool:
    try:
        models.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD,
            name, "fields_get",
            [],
            {"attributes": ["string", "type"]},
        )
        return True
    except Exception as exc:
        print(f"  [skip] {name}: {exc}")
        return False


def interesting_fields(fields: dict) -> list[str]:
    keys_prefer = [
        "name", "state", "holiday_status_id", "holiday_type",
        "employee_id", "employee_ids", "department_id",
        "date_from", "date_to", "request_date_from", "request_date_to",
        "number_of_days", "number_of_days_display",
        "leave_type_request_unit", "request_unit_half", "request_unit_hours",
        "validation_type", "active", "user_id", "partner_id",
        "time_type", "resource_id", "calendar_id",
    ]
    found = [k for k in keys_prefer if k in fields]
    # también cualquier campo con leave/holiday/vacation/absence en el nombre
    extra = [
        k for k in fields
        if any(t in k.lower() for t in ("leave", "holiday", "vacation", "absence", "time_off"))
        and k not in found
    ]
    return found + sorted(extra)[:30]


def dump_model(models, uid, name: str):
    print("=" * 70)
    print(f" MODELO: {name}")
    print("=" * 70)
    fields = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        name, "fields_get",
        [],
        {"attributes": ["string", "type", "selection", "relation"]},
    )
    keep = interesting_fields(fields)
    print(f"Campos relevantes ({len(keep)}):")
    for k in keep:
        meta = fields[k]
        sel = meta.get("selection")
        rel = meta.get("relation")
        extra = ""
        if sel:
            extra = f" selection={sel[:12]}{'...' if len(sel) > 12 else ''}"
        if rel:
            extra += f" → {rel}"
        print(f"  - {k:28} {meta.get('type'):10} {meta.get('string')}{extra}")

    # Estados posibles
    if "state" in fields and fields["state"].get("selection"):
        print("\nEstados (state):")
        for value, label in fields["state"]["selection"]:
            print(f"  {value:20} = {label}")

    # Tipos de ausencia
    if "holiday_status_id" in fields:
        try:
            types = models.execute_kw(
                ODOO_DB, uid, ODOO_PASSWORD,
                "hr.leave.type", "search_read",
                [[]],
                {"fields": ["name", "active", "requires_allocation", "time_type", "request_unit"], "limit": 50},
            )
            print(f"\nTipos hr.leave.type ({len(types)}):")
            for t in types:
                print(f"  [{t['id']}] {t.get('name')} active={t.get('active')} time_type={t.get('time_type')}")
        except Exception as exc:
            print(f"\nNo se pudo listar hr.leave.type: {exc}")

    # Muestra reciente
    date_fields = [f for f in ("request_date_from", "date_from", "date_to", "request_date_to") if f in fields]
    read_fields = [f for f in (
        "name", "state", "employee_id", "holiday_status_id",
        "request_date_from", "request_date_to", "date_from", "date_to",
        "number_of_days",
    ) if f in fields]

    order = "id desc"
    if "request_date_from" in fields:
        order = "request_date_from desc"
    elif "date_from" in fields:
        order = "date_from desc"

    try:
        rows = models.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD,
            name, "search_read",
            [[]],
            {"fields": read_fields, "limit": 15, "order": order},
        )
        print(f"\nÚltimos {len(rows)} registros:")
        for r in rows:
            emp = r.get("employee_id")
            emp_name = emp[1] if isinstance(emp, (list, tuple)) else emp
            htype = r.get("holiday_status_id")
            htype_name = htype[1] if isinstance(htype, (list, tuple)) else htype
            print(
                f"  id={r.get('id')} state={r.get('state')} "
                f"emp={emp_name} type={htype_name} "
                f"from={r.get('request_date_from') or r.get('date_from')} "
                f"to={r.get('request_date_to') or r.get('date_to')} "
                f"days={r.get('number_of_days')}"
            )
    except Exception as exc:
        print(f"\nNo se pudieron leer registros: {exc}")
        print(f"(campos fecha detectados: {date_fields})")
    print()


def search_ir_model(models, uid):
    print("=" * 70)
    print(" Búsqueda ir.model por leave/holiday/vacation/time.off")
    print("=" * 70)
    try:
        found = models.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD,
            "ir.model", "search_read",
            [[
                "|", "|", "|",
                ("model", "ilike", "leave"),
                ("model", "ilike", "holiday"),
                ("model", "ilike", "vacation"),
                ("model", "ilike", "time.off"),
            ]],
            {"fields": ["model", "name"], "limit": 40},
        )
        for m in found:
            print(f"  {m['model']:40} {m.get('name')}")
    except Exception as exc:
        print(f"  ir.model no accesible: {exc}")
    print()


def main():
    uid, models = connect()
    search_ir_model(models, uid)
    for name in CANDIDATE_MODELS:
        if model_exists(models, uid, name):
            dump_model(models, uid, name)
        else:
            print(f"Modelo ausente: {name}\n")


if __name__ == "__main__":
    main()
