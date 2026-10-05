#!/usr/bin/env python3
"""
Explora modelos de VIAJES / trayectos de flota en Odoo (XML-RPC).

Úsalo para identificar el modelo real de Soltec antes de cablear el sync
(Equipo=vehículo, Fecha registro, Ficha inicio/fin, km inicial/final).

Uso:

  export ODOO_URL='https://tu-odoo.ejemplo'
  export ODOO_DB='nombre_bd'
  export ODOO_USER='usuario'
  export ODOO_PASSWORD='clave'
  python3 scripts/inspect_odoo_viajes.py

Opcional:
  export ODOO_VIAJE_LIMIT=8
  export ODOO_VIAJE_MODEL='x_viaje'   # si ya conoces el technical name
"""
from __future__ import annotations

import json
import os
import sys
import xmlrpc.client

# Defaults locales (solo si no hay export). NO subas este archivo con password a git.
ODOO_URL = 'https://odoo.soltecgrupo.es'
ODOO_DB = 'db17-spain'
ODOO_USER = 'admin'
ODOO_PASSWORD = 'Soc0233Ssd4223aAs3367'

_DEFAULTS = {
    'ODOO_URL': ODOO_URL,
    'ODOO_DB': ODOO_DB,
    'ODOO_USER': ODOO_USER,
    'ODOO_PASSWORD': ODOO_PASSWORD,
}


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name) or default or _DEFAULTS.get(name)
    if not value:
        print(f"Falta variable de entorno: {name}", file=sys.stderr)
        sys.exit(1)
    return value


SEARCH_TOKENS = (
    "viaje",
    "viajes",
    "trip",
    "trayecto",
    "desplazamiento",
    "fleet",
    "odometer",
    "kilometr",
    "vehicle",
    "vehiculo",
    "equipo",
)

CANDIDATE_MODELS = [
    "fleet.vehicle.log.services",
    "fleet.vehicle.log.contract",
    "fleet.vehicle.log.fuel",
    "fleet.vehicle.odometer",
    "fleet.vehicle",
]

FIELD_HINTS = (
    "equipo",
    "vehicle",
    "vehiculo",
    "fleet",
    "date",
    "fecha",
    "inicio",
    "fin",
    "start",
    "end",
    "odometer",
    "odometro",
    "km",
    "kilometr",
    "driver",
    "conductor",
    "partner",
    "employee",
    "empleado",
    "ficha",
    "check",
    "valor",
    "value",
    "name",
    "state",
)


def _m2o(val):
    if isinstance(val, (list, tuple)) and len(val) >= 2:
        return {"id": val[0], "name": val[1]}
    if isinstance(val, int):
        return {"id": val}
    return val


def dump_model(models, db, uid, password, model: str, limit: int) -> None:
    exists = models.execute_kw(
        db, uid, password, "ir.model", "search_count", [[("model", "=", model)]]
    )
    if not exists:
        print(f"--- {model}: NO existe ---\n")
        return

    fields = models.execute_kw(
        db,
        uid,
        password,
        model,
        "fields_get",
        [],
        {"attributes": ["string", "type", "relation", "help"]},
    )
    interesting = []
    for fname, meta in sorted(fields.items()):
        key = fname.lower()
        label = (meta.get("string") or "").lower()
        if any(tok in key or tok in label for tok in FIELD_HINTS):
            interesting.append(
                {
                    "field": fname,
                    "string": meta.get("string"),
                    "type": meta.get("type"),
                    "relation": meta.get("relation"),
                    "help": (meta.get("help") or "")[:120] or None,
                }
            )

    print(f"=== {model}: campos relevantes ({len(interesting)}/{len(fields)}) ===")
    print(json.dumps(interesting, ensure_ascii=False, indent=2))

    # Mapeo sugerido según etiquetas Soltec
    suggest = {
        "equipo": [],
        "fecha_registro": [],
        "fecha_inicio": [],
        "fecha_fin": [],
        "km_inicial": [],
        "km_final": [],
        "conductor": [],
    }
    for item in interesting:
        f, s, t = item["field"], (item["string"] or "").lower(), item["type"]
        fl = f.lower()
        if t == "many2one" and any(x in fl or x in s for x in ("vehicle", "vehiculo", "equipo", "fleet")):
            suggest["equipo"].append(f)
        if any(x in fl or x in s for x in ("fecha", "date")) and "inicio" not in fl and "fin" not in fl and "start" not in fl and "end" not in fl:
            if t in ("date", "datetime"):
                suggest["fecha_registro"].append(f)
        if any(x in fl or x in s for x in ("inicio", "start", "date_start", "fecha_inicio", "ficha_inicio")):
            suggest["fecha_inicio"].append(f)
        if any(x in fl or x in s for x in ("fin", "end", "date_end", "fecha_fin", "ficha_fin")):
            suggest["fecha_fin"].append(f)
        if any(x in fl or x in s for x in ("km_ini", "odometer_start", "odometro_ini", "km inicial", "inicial")):
            suggest["km_inicial"].append(f)
        if any(x in fl or x in s for x in ("km_fin", "odometer_end", "odometro_fin", "km final", "final", "value", "odometer")) and f not in suggest["km_inicial"]:
            if "ini" not in fl and "start" not in fl:
                suggest["km_final"].append(f)
        if t == "many2one" and any(x in fl or x in s for x in ("driver", "conductor", "partner", "employee", "empleado")):
            suggest["conductor"].append(f)

    print(f"--- sugerencia de mapeo para {model} ---")
    print(json.dumps(suggest, ensure_ascii=False, indent=2))

    sample_fields = [f["field"] for f in interesting][:30] or ["id", "display_name"]
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
        cleaned = []
        for row in rows:
            cleaned.append({k: _m2o(v) for k, v in row.items()})
        print(f"--- muestras ({len(cleaned)}) ---")
        print(json.dumps(cleaned, ensure_ascii=False, indent=2, default=str))
    except Exception as exc:  # noqa: BLE100
        print(f"--- no se pudieron leer muestras: {exc} ---")
    print()


def main() -> None:
    url = env("ODOO_URL").rstrip("/")
    db = env("ODOO_DB")
    user = env("ODOO_USER")
    password = env("ODOO_PASSWORD")
    limit = int(os.environ.get("ODOO_VIAJE_LIMIT", "8"))
    forced_model = (os.environ.get("ODOO_VIAJE_MODEL") or "").strip()

    common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
    uid = common.authenticate(db, user, password, {})
    if not uid:
        print("Autenticación fallida", file=sys.stderr)
        sys.exit(2)

    models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")
    print(f"OK auth uid={uid} db={db}\n")

    # Búsquedas simples por token (evita dominios OR mal formados en Odoo)
    seen = {}
    for tok in SEARCH_TOKENS:
        for field in ("model", "name"):
            try:
                rows = models.execute_kw(
                    db,
                    uid,
                    password,
                    "ir.model",
                    "search_read",
                    [[(field, "ilike", tok)]],
                    {"fields": ["model", "name"], "limit": 100},
                )
            except Exception as exc:  # noqa: BLE001
                print(f"  aviso: búsqueda {field}~{tok} falló: {exc}", file=sys.stderr)
                continue
            for m in rows or []:
                if m.get("model"):
                    seen[m["model"]] = m

    model_names = sorted(seen.values(), key=lambda m: m.get("model") or "")
    print("=== Modelos candidatos (viaje / flota / km) ===")
    for m in model_names:
        print(f"  {m['model']:45} {m['name']}")
    print()

    to_dump = []
    if forced_model:
        to_dump.append(forced_model)

    # Priorizar nombres que huelan a viaje
    for m in model_names:
        tech = (m.get("model") or "").lower()
        label = (m.get("name") or "").lower()
        if any(t in tech or t in label for t in ("viaje", "trip", "trayecto", "desplaz")):
            if m["model"] not in to_dump:
                to_dump.append(m["model"])

    for c in CANDIDATE_MODELS:
        if c not in to_dump:
            to_dump.append(c)

    # También los x_* custom que mencionen km/viaje
    for m in model_names:
        tech = m.get("model") or ""
        if tech.startswith("x_") and tech not in to_dump:
            low = tech.lower() + " " + (m.get("name") or "").lower()
            if any(t in low for t in ("viaje", "km", "odomet", "flota", "vehic", "equipo")):
                to_dump.append(tech)

    print(f"Inspeccionando {len(to_dump)} modelos…\n")
    for model in to_dump:
        dump_model(models, db, uid, password, model, limit)

    print(
        "\nQué mirar en las muestras:\n"
        "  - Equipo / vehicle_id → vehículo\n"
        "  - Fecha (registro) vs Ficha inicio / Ficha fin → cobertura de días\n"
        "  - Km inicial (suele ser último odómetro) y Km final / value\n"
        "  - Si inicio≠fin en un registro → catch-up multi-día (limpia 'sin km')\n"
        "Pasa el technical name real con ODOO_VIAJE_MODEL=... y reenvía el JSON."
    )


if __name__ == "__main__":
    main()
