#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import py_compile
import sys
from pathlib import Path

sys.path.insert(0, "/opt/soltec/planner")
base = Path("/opt/soltec/planner")

py_compile.compile(str(base / "app/services/i18n_catalog_app.py"), doraise=True)
print("py_compile OK")

en_map = {
    "Auditoría de Fichajes": "Time-clock audit",
    "Auditoría de fichajes": "Time-clock audit",
    "Odoo vs planificación": "Odoo vs planning",
    "Solo hoy": "Today only",
    "Últimos 7 días": "Last 7 days",
    "Últimos 15 días": "Last 15 days",
    "Último mes": "Last month",
    "Dos meses": "Two months",
    "Sincronizar": "Sync",
    "Sincronización Odoo": "Odoo sync",
    "Ir a desviaciones": "Go to deviations",
    "desviaciones": "deviations",
    "Ir a sin planificar": "Go to unplanned",
    "sin planificar": "unplanned",
    "Ir a ausencias": "Go to leave",
    "ausencias": "leave",
    "Ir a modificaciones Odoo": "Go to Odoo changes",
    "cambios Odoo": "Odoo changes",
    "Ir al histórico": "Go to history",
    "en histórico": "in history",
    "Desviaciones de plan": "Plan deviations",
    "No hay desviaciones pendientes": "No pending deviations",
    "Fichajes sin planificar": "Unplanned clock-ins",
    "No hay fichajes sin planificar": "No unplanned clock-ins",
    "No hay ausencias registradas": "No leave recorded",
    "Modificaciones Odoo (RRHH)": "Odoo changes (HR)",
    "Histórico global": "Global history",
    "¿Aprobar y crear asignaciones de vehículo?": "Approve and create vehicle assignments?",
    "¿Denegar esta solicitud?": "Deny this request?",
    "No hay solicitudes de vehículo con los filtros actuales.": "No vehicle requests with the current filters.",
    "Manual": "Manual",
    "Solicitante": "Requester",
}
pt_map = {
    "Auditoría de Fichajes": "Auditoria de ponto",
    "Auditoría de fichajes": "Auditoria de ponto",
    "Odoo vs planificación": "Odoo vs planeamento",
    "Solo hoy": "Só hoje",
    "Últimos 7 días": "Últimos 7 dias",
    "Últimos 15 días": "Últimos 15 dias",
    "Último mes": "Último mês",
    "Dos meses": "Dois meses",
    "Sincronizar": "Sincronizar",
    "Sincronización Odoo": "Sincronização Odoo",
    "desviaciones": "desvios",
    "sin planificar": "sem plano",
    "ausencias": "ausências",
    "cambios Odoo": "alterações Odoo",
    "en histórico": "no histórico",
    "Desviaciones de plan": "Desvios do plano",
    "No hay desviaciones pendientes": "Sem desvios pendentes",
    "Fichajes sin planificar": "Pontos sem plano",
    "No hay fichajes sin planificar": "Sem pontos sem plano",
    "No hay ausencias registradas": "Sem ausências registadas",
    "Modificaciones Odoo (RRHH)": "Alterações Odoo (RH)",
    "Histórico global": "Histórico global",
    "¿Aprobar y crear asignaciones de vehículo?": "Aprovar e criar atribuições de veículo?",
    "¿Denegar esta solicitud?": "Negar este pedido?",
    "No hay solicitudes de vehículo con los filtros actuales.": "Não há pedidos de veículo com os filtros atuais.",
    "Manual": "Manual",
    "Solicitante": "Requerente",
    "Ir a desviaciones": "Ir para desvios",
    "Ir a sin planificar": "Ir para sem plano",
    "Ir a ausencias": "Ir para ausências",
    "Ir a modificaciones Odoo": "Ir para alterações Odoo",
    "Ir al histórico": "Ir para o histórico",
}

for name, mapping in [("_en_keys.json", en_map), ("_pt_full.json", pt_map)]:
    d = json.loads((base / name).read_text(encoding="utf-8"))
    miss = [k for k in mapping if k not in d]
    bad = [(k, d.get(k), v) for k, v in mapping.items() if d.get(k) != v]
    print(f"{name}: miss={len(miss)} diff={len(bad)}")
    for k in miss:
        print("  MISS", k)
    for k, h, w in bad:
        print("  DIFF", repr(k), repr(h), "!=", repr(w))

fr = json.loads((base / "_fr_full.json").read_text(encoding="utf-8"))
miss_fr = [k for k in en_map if k not in fr]
print(f"_fr_full.json: miss={len(miss_fr)}")
for k in miss_fr:
    print("  MISS", k)
# sample FR values
for k in ["Desviaciones de plan", "Sincronización Odoo", "Manual", "Solicitante"]:
    print(f"  FR {k!r} -> {fr.get(k)!r}")

from app.services.i18n_catalog_app import APP_UI_EN

miss_app = [k for k in en_map if k not in APP_UI_EN]
diff_app = [(k, APP_UI_EN[k], v) for k, v in en_map.items() if k in APP_UI_EN and APP_UI_EN[k] != v]
print(f"APP_UI_EN: miss={len(miss_app)} diff={len(diff_app)}")
for k in miss_app:
    print("  MISS", k)
for k, h, w in diff_app:
    print("  DIFF", repr(k), repr(h), "!=", repr(w))

from app.services.i18n_service import translate

print("--- samples ---")
for s in ["Jefe", "Desviaciones de plan", "plantilla ocupada"]:
    out = translate(s, locale="pt")
    print(f"translate({s!r}, locale='pt') -> {out!r}")