#!/usr/bin/env python3
"""
Encuentra el modelo CUSTOM de Viajes Soltec.
NO uses inspect_odoo_viajes.py (ese solo mira fleet estándar).

  python3 scripts/inspect_odoo_find_viajes.py
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
SAMPLE = int(os.environ.get("ODOO_SAMPLE", "5"))


def main():
    common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
    uid = common.authenticate(ODOO_DB, ODOO_USER, ODOO_PASSWORD, {})
    if not uid:
        print("Auth fail", file=sys.stderr)
        sys.exit(2)
    m = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")
    print(f"OK auth uid={uid}\n")
    print("*** ESTE ES inspect_odoo_find_viajes.py (custom), no el de fleet ***\n")

    # 1) Menús que digan Viaje / Trayecto / Kilómetro
    print("=== Menús Odoo (ir.ui.menu) con Viaje/Trayecto/Km/Flota ===")
    menus = m.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD, "ir.ui.menu", "search_read",
        [["|", "|", "|", "|",
          ("name", "ilike", "viaje"),
          ("name", "ilike", "trayecto"),
          ("name", "ilike", "kilometr"),
          ("name", "ilike", "odometr"),
          ("name", "ilike", "flota"),
        ]],
        {"fields": ["id", "name", "complete_name", "action"], "limit": 80},
    )
    print(json.dumps(menus, ensure_ascii=False, indent=2, default=str))

    # 2) Acciones ventana ligadas a esos nombres
    print("\n=== Acciones (ir.actions.act_window) con Viaje/Trayecto ===")
    acts = m.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD, "ir.actions.act_window", "search_read",
        [["|", "|", "|",
          ("name", "ilike", "viaje"),
          ("name", "ilike", "trayecto"),
          ("res_model", "ilike", "viaje"),
          ("res_model", "ilike", "trayecto"),
        ]],
        {"fields": ["id", "name", "res_model", "view_mode"], "limit": 80},
    )
    print(json.dumps(acts, ensure_ascii=False, indent=2, default=str))

    # 3) Todos los modelos x_*
    print("\n=== Todos los modelos x_* (custom/Studio) ===")
    xmodels = m.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD, "ir.model", "search_read",
        [[("model", "=like", "x_%")]],
        {"fields": ["model", "name"], "order": "model asc", "limit": 500},
    )
    for row in xmodels:
        print(f"  {row['model']:55} {row['name']}")
    print(f"({len(xmodels)} modelos x_*)")

    # 4) Modelos cuyo NAME/MODEL contiene Viaje
    print("\n=== ir.model con name/model ilike viaje|trayecto|trip ===")
    named = m.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD, "ir.model", "search_read",
        [["|", "|", "|", "|", "|",
          ("name", "ilike", "viaje"),
          ("name", "ilike", "trayecto"),
          ("name", "ilike", "trip"),
          ("model", "ilike", "viaje"),
          ("model", "ilike", "trayecto"),
          ("model", "ilike", "trip"),
        ]],
        {"fields": ["model", "name"], "limit": 100},
    )
    print(json.dumps(named, ensure_ascii=False, indent=2))

    # 5) Dump candidatos
    to_dump = []
    for a in acts:
        rm = a.get("res_model")
        if rm and rm not in to_dump and "odometer" not in (rm or ""):
            to_dump.append(rm)
    for row in named:
        rm = row.get("model")
        if rm and rm not in to_dump and "odometer" not in (rm or ""):
            to_dump.append(rm)
    for row in xmodels:
        blob = f"{row['model']} {row['name']}".lower()
        if any(t in blob for t in (
            "viaje", "trayecto", "trip", "km", "equipo", "ficha",
            "odometr", "flota", "vehic", "desplaz",
        )):
            if row["model"] not in to_dump:
                to_dump.append(row["model"])

    print(f"\n=== DUMP de {len(to_dump)} modelos candidatos ===")
    for tech in to_dump:
        try:
            fields = m.execute_kw(
                ODOO_DB, uid, ODOO_PASSWORD, tech, "fields_get", [],
                {"attributes": ["string", "type", "relation"]},
            )
        except Exception as exc:
            print(f"\n--- {tech}: error fields_get: {exc}")
            continue
        interesting = {
            k: {"string": v.get("string"), "type": v.get("type"), "relation": v.get("relation")}
            for k, v in sorted(fields.items())
            if any(h in f"{k} {v.get('string') or ''}".lower() for h in (
                "vehicle", "vehiculo", "equipo", "fleet", "km", "odometr", "kilometr",
                "fecha", "date", "inicio", "fin", "start", "end", "ficha",
                "driver", "conductor", "employee", "partner", "name", "state",
                "valor", "value", "desvio", "previs", "delta",
            ))
        }
        print(f"\n{'='*60}\n{tech}  ({len(fields)} campos, {len(interesting)} interesantes)")
        print(json.dumps(interesting, ensure_ascii=False, indent=2))
        try:
            rows = m.execute_kw(
                ODOO_DB, uid, ODOO_PASSWORD, tech, "search_read", [[]],
                {"fields": list(interesting.keys())[:35] or ["id", "display_name"],
                 "limit": SAMPLE, "order": "id desc"},
            )
            print(f"muestras ({len(rows)}):")
            print(json.dumps(rows, ensure_ascii=False, indent=2, default=str))
        except Exception as exc:
            print(f"muestras error: {exc}")

    print(
        "\n\nSi no sale nada: en Odoo Ajustes→Técnico→Modelos→busca Viaje,\n"
        "copia el technical name y:\n"
        "  ODOO_VIAJE_MODEL=ese.nombre python3 inspect_odoo_find_viajes.py"
    )


if __name__ == "__main__":
    forced = (os.environ.get("ODOO_VIAJE_MODEL") or "").strip()
    if forced:
        common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
        uid = common.authenticate(ODOO_DB, ODOO_USER, ODOO_PASSWORD, {})
        m = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")
        print(f"Dump forzado de {forced}")
        fields = m.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD, forced, "fields_get", [],
            {"attributes": ["string", "type", "relation", "help"]},
        )
        print(json.dumps(
            {k: {"string": v.get("string"), "type": v.get("type"), "relation": v.get("relation")}
             for k, v in sorted(fields.items())},
            ensure_ascii=False, indent=2,
        ))
        rows = m.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD, forced, "search_read", [[]],
            {"fields": list(fields.keys())[:40], "limit": SAMPLE, "order": "id desc"},
        )
        print(json.dumps(rows, ensure_ascii=False, indent=2, default=str))
        sys.exit(0)
    main()
