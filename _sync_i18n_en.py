#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Merge _en_keys.json extras into APP_UI_EN and ensure FR/PT extras for dynamic entity subs."""
import json
import re
from pathlib import Path

base = Path("/opt/soltec/planner")
en_keys = json.loads((base / "_en_keys.json").read_text(encoding="utf-8"))
fr = json.loads((base / "_fr_full.json").read_text(encoding="utf-8"))
pt = json.loads((base / "_pt_full.json").read_text(encoding="utf-8"))

# Entity-stat dynamic / static phrases used as whole msgids
extra_en = {
    "Sin límite definido": "No limit defined",
    "Subcontratas activas": "Active subcontractors",
    "Sin plazas genéricas": "No generic slots",
    "Asignaciones planificadas": "Planned assignments",
    "Sin incidencias": "No incidents",
    "Sin registros": "No records",
    "Con personal asignado": "With staff assigned",
    "Abiertas de la empresa": "Open for the company",
    "Últimos 30 días": "Last 30 days",
    "Sin valoraciones": "No ratings",
    "Sin activos": "No active staff",
    "Pendientes / en proceso": "Pending / in progress",
    "Libre hoy": "Free today",
    "Planificado + Odoo": "Planned + Odoo",
    "Personas distintas": "Distinct people",
    "Sin conductor Odoo": "No Odoo driver",
    "Conductor (ausencia)": "Driver (on leave)",
    "Sin más plan": "No further plan",
    "No hay tramos libres en este horizonte": "No free segments in this horizon",
    "con el filtro elegido": "with the selected filter",
    "Coche": "Vehicle",
    "Flota": "Fleet",
    "Motivo": "Reason",
    "Ausencia": "Leave",
    "Periodo": "Period",
    "Pendiente de admin": "Pending admin",
    "Solicitar ausencia": "Request leave",
    "Quedará pendiente hasta que administración la valide": "It will stay pending until admin validates it",
    "Crear ausencia manual (además del sync ERP)": "Create manual leave (in addition to ERP sync)",
    "Vacaciones, bajas y permisos de tu plantilla": "Vacation, sick leave and permits for your staff",
    "Consulta y filtros · tu personal": "Browse and filters · your staff",
    "Empiezan en los próximos": "Starting in the next",
    "días (aún no han empezado)": "days (not started yet)",
    "Interna": "Internal",
    "Inicio / Fin": "Start / End",
    "Ubicación": "Location",
    "Plataforma PRL": "H&S platform",
    "Jefe de obra": "Site manager",
    "Km Odoo": "Odoo km",
    "Genérica": "Generic",
    "Concreta": "Specific",
    "En Curso": "In progress",
    "Conflictos pendientes": "Pending conflicts",
    "Modo manual · requieren confirmación": "Manual mode · require confirmation",
}
extra_fr = {
    "Sin límite definido": "Aucune limite définie",
    "Subcontratas activas": "Sous-traitants actifs",
    "Sin plazas genéricas": "Sans places génériques",
    "Asignaciones planificadas": "Affectations planifiées",
    "Sin incidencias": "Sans incidents",
    "Sin registros": "Sans enregistrements",
    "Con personal asignado": "Avec personnel affecté",
    "Abiertas de la empresa": "Ouvertes de l'entreprise",
    "Últimos 30 días": "30 derniers jours",
    "Sin valoraciones": "Sans évaluations",
    "Sin activos": "Sans actifs",
    "Pendientes / en proceso": "En attente / en cours",
    "Libre hoy": "Libre aujourd'hui",
    "Planificado + Odoo": "Planifié + Odoo",
    "Personas distintas": "Personnes distinctes",
    "Sin conductor Odoo": "Sans conducteur Odoo",
    "Conductor (ausencia)": "Conducteur (absence)",
    "Sin más plan": "Plus de plan",
    "No hay tramos libres en este horizonte": "Aucun segment libre sur cet horizon",
    "con el filtro elegido": "avec le filtre choisi",
    "Coche": "Véhicule",
    "Flota": "Flotte",
    "Motivo": "Motif",
    "Ausencia": "Absence",
    "Periodo": "Période",
    "Pendiente de admin": "En attente d'admin",
    "Solicitar ausencia": "Demander une absence",
    "Quedará pendiente hasta que administración la valide": "Restera en attente jusqu'à validation par l'administration",
    "Crear ausencia manual (además del sync ERP)": "Créer une absence manuelle (en plus de la sync ERP)",
    "Vacaciones, bajas y permisos de tu plantilla": "Vacances, arrêts et congés de votre effectif",
    "Consulta y filtros · tu personal": "Consultation et filtres · votre personnel",
    "Empiezan en los próximos": "Commencent dans les",
    "días (aún no han empezado)": "jours (pas encore commencées)",
    "Interna": "Interne",
    "Inicio / Fin": "Début / Fin",
    "Ubicación": "Emplacement",
    "Plataforma PRL": "Plateforme PRL",
    "Jefe de obra": "Chef de chantier",
    "Km Odoo": "Km Odoo",
    "Genérica": "Générique",
    "Concreta": "Spécifique",
    "En Curso": "En cours",
    "Conflictos pendientes": "Conflits en attente",
    "Modo manual · requieren confirmación": "Mode manuel · confirmation requise",
}
extra_pt = {k: v for k, v in extra_en.items()}  # fallback then override
extra_pt.update({
    "Sin límite definido": "Sem limite definido",
    "Subcontratas activas": "Subempreiteiros ativos",
    "Sin plazas genéricas": "Sem vagas genéricas",
    "Asignaciones planificadas": "Atribuições planeadas",
    "Sin incidencias": "Sem incidentes",
    "Sin registros": "Sem registos",
    "Con personal asignado": "Com pessoal atribuído",
    "Abiertas de la empresa": "Abertas da empresa",
    "Últimos 30 días": "Últimos 30 dias",
    "Sin valoraciones": "Sem avaliações",
    "Sin activos": "Sem ativos",
    "Pendientes / en proceso": "Pendentes / em curso",
    "Libre hoy": "Livre hoje",
    "Personas distintas": "Pessoas distintas",
    "Sin conductor Odoo": "Sem condutor Odoo",
    "Conductor (ausencia)": "Condutor (ausência)",
    "Sin más plan": "Sem mais plano",
    "No hay tramos libres en este horizonte": "Não há troços livres neste horizonte",
    "con el filtro elegido": "com o filtro escolhido",
    "Coche": "Veículo",
    "Flota": "Frota",
    "Motivo": "Motivo",
    "Ausencia": "Ausência",
    "Periodo": "Período",
    "Pendiente de admin": "Pendente de admin",
    "Solicitar ausencia": "Solicitar ausência",
    "Crear ausencia manual (además del sync ERP)": "Criar ausência manual (além da sync ERP)",
    "Interna": "Interna",
    "Inicio / Fin": "Início / Fim",
    "Ubicación": "Localização",
    "Jefe de obra": "Chefe de obra",
    "Genérica": "Genérica",
    "Concreta": "Concreta",
    "En Curso": "Em curso",
    "Conflictos pendientes": "Conflitos pendentes",
})

en_keys.update(extra_en)
fr.update(extra_fr)
pt.update(extra_pt)
for k, v in en_keys.items():
    fr.setdefault(k, fr.get(k) or v)
    pt.setdefault(k, pt.get(k) or v)

(base / "_en_keys.json").write_text(json.dumps(en_keys, ensure_ascii=False, indent=2), encoding="utf-8")
(base / "_fr_full.json").write_text(json.dumps(fr, ensure_ascii=False, indent=2), encoding="utf-8")
(base / "_pt_full.json").write_text(json.dumps(pt, ensure_ascii=False, indent=2), encoding="utf-8")

# Patch APP_UI_EN in i18n_catalog_app.py: merge missing keys before closing brace of APP_UI_EN
app_path = base / "app/services/i18n_catalog_app.py"
text = app_path.read_text(encoding="utf-8")
# Extract existing APP_UI_EN keys roughly
existing = set(re.findall(r"^\s*'((?:\\'|[^'])*)'\s*:", text, flags=re.M))
# Also double-quoted
existing |= set(re.findall(r'^\s*"((?:\\"|[^"])*)"\s*:', text, flags=re.M))

to_add = {k: v for k, v in en_keys.items() if k not in existing}
# Insert before "# PT/FR:" comment
marker = "\n# PT/FR: complete locale maps"
if marker not in text:
    raise SystemExit("marker not found")
lines = ["\n    # --- synced from _en_keys.json ---\n"]
for k, v in sorted(to_add.items(), key=lambda kv: kv[0]):
    lines.append(f"    {k!r}: {v!r},\n")
insert = "".join(lines)
# Find end of APP_UI_EN dict: last `}` before marker
idx = text.index(marker)
# walk back to closing of APP_UI_EN
before = text[:idx].rstrip()
if not before.endswith("}"):
    raise SystemExit("expected APP_UI_EN to end with }")
# insert before the final }
# Find the APP_UI_EN = { ... }
m = re.search(r"APP_UI_EN\s*=\s*\{", text)
if not m:
    raise SystemExit("APP_UI_EN not found")
# last } before marker that closes APP_UI_EN - the `}` right before marker after roles
close_idx = before.rfind("}")
new_text = text[:close_idx] + insert + text[close_idx:]
app_path.write_text(new_text, encoding="utf-8")
print("added_to_APP_UI_EN", len(to_add))
print("fr_keys", len(fr), "en_keys", len(en_keys))
