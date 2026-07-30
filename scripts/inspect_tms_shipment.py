#!/usr/bin/env python3
"""
Analiza SOLO tms.shipment (Viajes Soltec).
No asume mapeos: lista TODOS los campos + muestras + casos borde.

  cd /opt/soltec/planner/scripts
  python3 inspect_tms_shipment.py

Opcional:
  export ODOO_SAMPLE=20
"""
from __future__ import annotations

import json
import os
import sys
import xmlrpc.client

ODOO_URL = os.environ.get("ODOO_URL", "https://odoo.soltecgrupo.es").rstrip("/")
ODOO_DB = os.environ.get("ODOO_DB", "db17-spain")
ODOO_USER = os.environ.get("ODOO_USER", "admin")
ODOO_PASSWORD = os.environ.get("ODOO_PASSWORD", "Soc0233Ssd4223aAs3367")
SAMPLE = int(os.environ.get("ODOO_SAMPLE", "15"))
MODEL = "tms.shipment"


def j(x):
    print(json.dumps(x, ensure_ascii=False, indent=2, default=str))


def main():
    common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
    uid = common.authenticate(ODOO_DB, ODOO_USER, ODOO_PASSWORD, {})
    if not uid:
        print("Auth fail", file=sys.stderr)
        sys.exit(2)
    m = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")
    print(f"OK auth uid={uid} model={MODEL}\n")

    exists = m.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD, "ir.model", "search_count",
        [[("model", "=", MODEL)]],
    )
    if not exists:
        print(f"{MODEL} NO EXISTE")
        sys.exit(1)

    # 1) TODOS los campos (con selection si aplica)
    fields = m.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD, MODEL, "fields_get", [],
        {"attributes": ["string", "type", "relation", "help", "selection", "required"]},
    )
    print(f"=== 1) TODOS los campos ({len(fields)}) ===")
    j({
        k: {
            "string": v.get("string"),
            "type": v.get("type"),
            "relation": v.get("relation"),
            "required": v.get("required"),
            "selection": v.get("selection"),
            "help": v.get("help"),
        }
        for k, v in sorted(fields.items())
    })

    # 2) Tabla legible campo → etiqueta
    print("\n=== 2) Campo → etiqueta (resumen) ===")
    for k, v in sorted(fields.items()):
        print(f"  {k:40} | {v.get('type'):12} | {v.get('string')}")

    field_names = list(fields.keys())
    # Odoo a veces falla con demasiados fields; priorizar no-relacionales one2many
    read_fields = [
        f for f, meta in fields.items()
        if meta.get("type") not in ("one2many", "many2many", "binary", "html")
    ]

    # 3) Últimos N registros crudos
    print(f"\n=== 3) Últimos {SAMPLE} registros ===")
    rows = m.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD, MODEL, "search_read", [[]],
        {"fields": read_fields, "limit": SAMPLE, "order": "id desc"},
    )
    j(rows)

    # 4) Casos borde útiles para negocio
    queries = [
        ("date_end relleno", [("date_end", "!=", False)]),
        ("date_end vacío", [("date_end", "=", False)]),
        ("date_start != date_end (multi-día)", [
            ("date_end", "!=", False),
            ("date_start", "!=", False),
        ]),
        ("desvio != 0", [("desvio", "!=", 0)]),
        ("desvio > 10", [("desvio", ">", 10)]),
        ("sin equipo", [("bim_transport_equipment_id", "=", False)]),
        ("sin conductor", [("driver_id", "=", False)]),
        ("begin_kilometers vacío", [("begin_kilometers", "=", False)]),
        ("end_kilometers vacío", [("end_kilometers", "=", False)]),
        ("qty > 0", [("qty", ">", 0)]),
    ]

    # Ajustar dominios a campos que existan
    print("\n=== 4) Conteos / muestras por caso ===")
    for title, domain in queries:
        # quitar condiciones sobre campos inexistentes
        clean = []
        ok = True
        for leaf in domain:
            if isinstance(leaf, (list, tuple)) and leaf and leaf[0] not in fields:
                ok = False
                break
            clean.append(leaf)
        if not ok:
            print(f"\n--- {title}: SKIP (campo no existe) ---")
            continue
        try:
            count = m.execute_kw(
                ODOO_DB, uid, ODOO_PASSWORD, MODEL, "search_count", [clean],
            )
            sample = m.execute_kw(
                ODOO_DB, uid, ODOO_PASSWORD, MODEL, "search_read", [clean],
                {
                    "fields": [f for f in (
                        "id", "name", "state", "date", "date_start", "date_end",
                        "bim_transport_equipment_id", "driver_id",
                        "begin_kilometers", "end_kilometers", "qty",
                        "km_previsto", "desvio", "reviewed",
                        "bim_project_origin_id", "bim_project_destination_id",
                        "x_studio_nota",
                    ) if f in fields],
                    "limit": 3,
                    "order": "id desc",
                },
            )
            # filtro extra multi-día en python
            if "multi-día" in title:
                sample = [
                    r for r in m.execute_kw(
                        ODOO_DB, uid, ODOO_PASSWORD, MODEL, "search_read",
                        [[("date_end", "!=", False)]],
                        {
                            "fields": [f for f in (
                                "id", "name", "date_start", "date_end",
                                "begin_kilometers", "end_kilometers", "qty", "desvio",
                                "bim_transport_equipment_id", "driver_id",
                            ) if f in fields],
                            "limit": 80,
                            "order": "id desc",
                        },
                    )
                    if r.get("date_start") and r.get("date_end")
                    and str(r["date_start"])[:10] != str(r["date_end"])[:10]
                ][:3]
                count = f"~muestra filtrada ({len(sample)} mostrados)"
            print(f"\n--- {title}: count={count} ---")
            j(sample)
        except Exception as exc:
            print(f"\n--- {title}: ERROR {exc} ---")

    # 5) Valores de state
    if "state" in fields and fields["state"].get("selection"):
        print("\n=== 5) Valores de state ===")
        j(fields["state"]["selection"])
        for val, label in fields["state"]["selection"]:
            c = m.execute_kw(
                ODOO_DB, uid, ODOO_PASSWORD, MODEL, "search_count",
                [[("state", "=", val)]],
            )
            print(f"  state={val!r} ({label}): {c}")

    print(
        "\n\n=== PARA CONFIRMAR CONMIGO ===\n"
        "Revisa el bloque 2 (campo → etiqueta) y las muestras.\n"
        "Dime explícitamente el mapeo que quieres, p.ej.:\n"
        "  Equipo        = …\n"
        "  Fecha         = …\n"
        "  Inicio / Fin  = …\n"
        "  Km ini / fin  = …\n"
        "  Conductor     = …\n"
        "  Desvío / prev = …\n"
        "  ¿Ignorar states? = …\n"
        "Hasta entonces NO asumo ni toco más el sync."
    )


if __name__ == "__main__":
    main()
