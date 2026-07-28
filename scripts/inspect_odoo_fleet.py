#!/usr/bin/env python3
"""
Inspecciona modelos de flota / odómetro en Odoo (XML-RPC).
Úsalo antes de cablear el sync de vehículos.

Uso (desde el host o un contenedor con acceso a Odoo):

  export ODOO_URL='https://tu-odoo.ejemplo'
  export ODOO_DB='nombre_bd'
  export ODOO_USER='usuario'
  export ODOO_PASSWORD='clave'
  python3 scripts/inspect_odoo_fleet.py

Opcional:
  export ODOO_VEHICLE_LIMIT=5
"""
from __future__ import annotations

import json
import os
import sys
import xmlrpc.client


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if not value:
        print(f"Falta variable de entorno: {name}", file=sys.stderr)
        sys.exit(1)
    return value


def main() -> None:
    url = env("ODOO_URL").rstrip("/")
    db = env("ODOO_DB")
    user = env("ODOO_USER")
    password = env("ODOO_PASSWORD")
    limit = int(os.environ.get("ODOO_VEHICLE_LIMIT", "5"))

    common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
    uid = common.authenticate(db, user, password, {})
    if not uid:
        print("Autenticación fallida", file=sys.stderr)
        sys.exit(2)

    models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")
    print(f"OK auth uid={uid} db={db}\n")

    # 1) Modelos relacionados con flota / odómetro
    model_names = models.execute_kw(
        db,
        uid,
        password,
        "ir.model",
        "search_read",
        [[
            "|", "|", "|", "|",
            ("model", "ilike", "fleet"),
            ("model", "ilike", "odometer"),
            ("model", "ilike", "vehicle"),
            ("model", "ilike", "vehiculo"),
            ("model", "ilike", "kilometr"),
        ]],
        {"fields": ["model", "name"], "order": "model asc"},
    )
    print("=== Modelos encontrados ===")
    for m in model_names:
        print(f"  {m['model']:40} {m['name']}")
    print()

    candidates = [
        "fleet.vehicle",
        "fleet.vehicle.odometer",
        "fleet.vehicle.log.services",
        "fleet.vehicle.assignation.log",
    ]

    for model in candidates:
        exists = models.execute_kw(
            db, uid, password, "ir.model", "search_count", [[("model", "=", model)]]
        )
        if not exists:
            print(f"--- {model}: NO existe ---")
            continue

        fields = models.execute_kw(
            db,
            uid,
            password,
            model,
            "fields_get",
            [],
            {"attributes": ["string", "type", "relation"]},
        )
        interesting = []
        for fname, meta in sorted(fields.items()):
            key = fname.lower()
            if any(
                tok in key
                for tok in (
                    "name",
                    "license",
                    "plate",
                    "driver",
                    "odometer",
                    "partner",
                    "employee",
                    "active",
                    "model",
                    "brand",
                    "state",
                    "date",
                    "value",
                    "vehicle",
                    "km",
                )
            ):
                interesting.append(
                    {
                        "field": fname,
                        "string": meta.get("string"),
                        "type": meta.get("type"),
                        "relation": meta.get("relation"),
                    }
                )

        print(f"=== {model}: campos relevantes ===")
        print(json.dumps(interesting, ensure_ascii=False, indent=2))

        sample_fields = [f["field"] for f in interesting][:25] or ["id", "display_name"]
        try:
            rows = models.execute_kw(
                db,
                uid,
                password,
                model,
                "search_read",
                [[]],
                {"fields": sample_fields, "limit": limit, "order": "id desc"},
            )
            print(f"--- muestras ({len(rows)}) ---")
            print(json.dumps(rows, ensure_ascii=False, indent=2, default=str))
        except Exception as exc:  # noqa: BLE001
            print(f"--- no se pudieron leer muestras: {exc} ---")
        print()

    # Hint: último conductor = último registro de odómetro por vehículo
    if models.execute_kw(
        db, uid, password, "ir.model", "search_count", [[("model", "=", "fleet.vehicle.odometer")]]
    ):
        print("=== Hint odómetro (últimos por vehículo) ===")
        odo_fields = models.execute_kw(
            db,
            uid,
            password,
            "fleet.vehicle.odometer",
            "fields_get",
            [],
            {"attributes": ["string", "type", "relation"]},
        )
        driverish = [
            f
            for f in odo_fields
            if any(t in f for t in ("driver", "partner", "employee", "user", "create_uid"))
        ]
        print("Campos posibles de conductor en odómetro:", driverish or "(ninguno obvio)")
        print(
            "Revisa vehicle_id + date + value + driver/partner para mapear "
            "'última persona que metió km'."
        )


if __name__ == "__main__":
    main()
