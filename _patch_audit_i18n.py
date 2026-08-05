#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Append missing audit/vehicle UI msgids to EN/PT/FR catalogs and APP_UI_EN."""
import json
import re
from pathlib import Path

base = Path("/opt/soltec/planner")

en = {
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

pt = {
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

fr = {
    "Auditoría de Fichajes": "Audit des pointages",
    "Auditoría de fichajes": "Audit des pointages",
    "Odoo vs planificación": "Odoo vs planification",
    "Solo hoy": "Aujourd'hui seulement",
    "Últimos 7 días": "7 derniers jours",
    "Últimos 15 días": "15 derniers jours",
    "Último mes": "Dernier mois",
    "Dos meses": "Deux mois",
    "Sincronizar": "Synchroniser",
    "Sincronización Odoo": "Synchronisation Odoo",
    "Ir a desviaciones": "Aller aux écarts",
    "desviaciones": "écarts",
    "Ir a sin planificar": "Aller aux non planifiés",
    "sin planificar": "non planifié",
    "Ir a ausencias": "Aller aux absences",
    "ausencias": "absences",
    "Ir a modificaciones Odoo": "Aller aux modifications Odoo",
    "cambios Odoo": "modifications Odoo",
    "Ir al histórico": "Aller à l'historique",
    "en histórico": "dans l'historique",
    "Desviaciones de plan": "Écarts de plan",
    "No hay desviaciones pendientes": "Aucun écart en attente",
    "Fichajes sin planificar": "Pointages non planifiés",
    "No hay fichajes sin planificar": "Aucun pointage non planifié",
    "No hay ausencias registradas": "Aucune absence enregistrée",
    "Modificaciones Odoo (RRHH)": "Modifications Odoo (RH)",
    "Histórico global": "Historique global",
    "¿Aprobar y crear asignaciones de vehículo?": "Approuver et créer les affectations de véhicule ?",
    "¿Denegar esta solicitud?": "Refuser cette demande ?",
    "No hay solicitudes de vehículo con los filtros actuales.": "Aucune demande de véhicule avec les filtres actuels.",
    "Manual": "Manuel",
    "Solicitante": "Demandeur",
}


def load(name):
    return json.loads((base / name).read_text(encoding="utf-8"))


def save(name, data):
    (base / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def patch_app_ui_en(mapping):
    path = base / "app/services/i18n_catalog_app.py"
    text = path.read_text(encoding="utf-8")
    m = re.search(r"APP_UI_EN\s*=\s*\{", text)
    if not m:
        raise SystemExit("APP_UI_EN dict not found")
    start = m.end() - 1
    i = start
    depth = 0
    in_str = None
    escape = False
    end = None
    while i < len(text):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == in_str:
                in_str = None
        else:
            if ch in ("'", '"'):
                in_str = ch
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        i += 1
    if end is None:
        raise SystemExit("Could not find end of APP_UI_EN")
    body = text[start + 1 : end]
    existing = set(re.findall(r"""['"]([^'"]+)['"]\s*:""", body))
    to_add = [(k, v) for k, v in mapping.items() if k not in existing]
    if not to_add:
        print("APP_UI_EN: nothing to append")
        return 0
    insert_lines = [f"    {k!r}: {v!r}," for k, v in to_add]
    insert = "\n".join(insert_lines) + "\n"
    new_text = text[:end] + insert + text[end:]
    path.write_text(new_text, encoding="utf-8")
    print(f"APP_UI_EN: appended {len(to_add)} keys")
    for k, v in to_add:
        print(f"  + {k!r} -> {v!r}")
    return len(to_add)


def main():
    print("=== Pre-check ===")
    for name, mapping in [("_en_keys.json", en), ("_pt_full.json", pt), ("_fr_full.json", fr)]:
        data = load(name)
        miss = [k for k in mapping if k not in data]
        present = [k for k in mapping if k in data]
        print(f"{name}: {len(present)} present, {len(miss)} missing of {len(mapping)}")
        for k in miss:
            print(f"  MISS {k!r}")
        for k in present:
            if data[k] != mapping[k]:
                print(f"  DIFF {k!r}: have={data[k]!r} want={mapping[k]!r}")

    data = load("_en_keys.json")
    added = []
    for k, v in en.items():
        if k not in data:
            data[k] = v
            added.append(k)
    save("_en_keys.json", data)
    print(f"\n_en_keys.json: added {len(added)}")
    for k in added:
        print(f"  + {k!r}")

    data = load("_pt_full.json")
    added_pt, updated_pt = [], []
    for k, v in pt.items():
        if k not in data:
            data[k] = v
            added_pt.append(k)
        elif data[k] != v:
            old = data[k]
            data[k] = v
            updated_pt.append((k, old, v))
    save("_pt_full.json", data)
    print(f"\n_pt_full.json: added {len(added_pt)}, updated {len(updated_pt)}")
    for k in added_pt:
        print(f"  + {k!r}")
    for k, old, v in updated_pt:
        print(f"  ~ {k!r}: {old!r} -> {v!r}")

    data = load("_fr_full.json")
    added_fr, updated_fr = [], []
    for k, v in fr.items():
        if k not in data:
            data[k] = v
            added_fr.append(k)
        elif data[k] != v:
            old = data[k]
            data[k] = v
            updated_fr.append((k, old, v))
    save("_fr_full.json", data)
    print(f"\n_fr_full.json: added {len(added_fr)}, updated {len(updated_fr)}")
    for k in added_fr:
        print(f"  + {k!r}")
    for k, old, v in updated_fr:
        print(f"  ~ {k!r}: {old!r} -> {v!r}")

    n = patch_app_ui_en(en)
    print(f"\nDone. APP_UI_EN new keys: {n}")


if __name__ == "__main__":
    main()