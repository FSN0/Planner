#!/usr/bin/env python3
"""Diagnóstico rápido: distribución de fechas en tms.shipment."""
import xmlrpc.client
from collections import Counter

URL = "https://odoo.soltecgrupo.es"
DB = "db17-spain"
USER = "admin"
PWD = "Soc0233Ssd4223aAs3367"

uid = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common").authenticate(DB, USER, PWD, {})
m = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object")

rows = []
offset = 0
while True:
    chunk = m.execute_kw(
        DB, uid, PWD, "tms.shipment", "search_read",
        [[("state", "=", "confirmed")]],
        {
            "fields": ["id", "date", "date_start", "date_end", "bim_transport_equipment_id", "driver_id"],
            "limit": 2000,
            "offset": offset,
            "order": "id asc",
        },
    )
    if not chunk:
        break
    rows.extend(chunk)
    if len(chunk) < 2000:
        break
    offset += 2000

def day(v):
    if not v:
        return None
    return str(v)[:10]

starts = Counter(day(r.get("date_start")) for r in rows)
regs = Counter(day(r.get("date")) for r in rows)
vehs = Counter(
    (r.get("bim_transport_equipment_id") or [None])[0]
    if isinstance(r.get("bim_transport_equipment_id"), (list, tuple))
    else r.get("bim_transport_equipment_id")
    for r in rows
)

print(f"total confirmed={len(rows)}")
print(f"date_start unicos={len([k for k in starts if k])}  top10={starts.most_common(10)}")
print(f"date      unicos={len([k for k in regs if k])}  top10={regs.most_common(10)}")
print(f"vehiculos unicos={len([k for k in vehs if k])}")
print(f"date_start None/False={starts.get(None, 0)}")
print(f"sample 5:")
for r in rows[:5]:
    print(" ", r["id"], "start=", r.get("date_start"), "end=", r.get("date_end"), "date=", r.get("date"))
for r in rows[-5:]:
    print(" ", r["id"], "start=", r.get("date_start"), "end=", r.get("date_end"), "date=", r.get("date"))
