#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Add missing short UI keys + fix bad PT/EN entries."""
import json
import re
from pathlib import Path

base = Path("/opt/soltec/planner")

en = {
    "Jefe": "Manager",
    "Fin": "End",
    "Nueva": "New",
    "Nuevo": "New",
    "Asunto": "Subject",
    "Resumen": "Summary",
    "Asunto / Resumen": "Subject / Summary",
    "Implicados": "People involved",
    "Acceso": "Access",
    "Encargado": "Supervisor",
    "Import.": "Import.",
    "Sols.": "Reqs.",
    "Valor.": "Rating",
    "Gremio": "Trade",
    "seleccionadas": "selected",
    "seleccionados": "selected",
    "Finalizar": "Finish",
    "Finalizada": "Finished",
    "En Curso": "In progress",
    "En curso": "In progress",
    "Desactivar": "Deactivate",
    "Internos": "Internal",
    "Externos": "External",
    "Categoría": "Category",
    "Valoración": "Rating",
    "Cuaderno de Bitácora": "Logbook",
    "Registro de reuniones, notas operativas e incidencias.": "Meetings, operational notes and incidents.",
    "Nueva nota / reunión": "New note / meeting",
    "Privada": "Private",
    "Pública": "Public",
    "Ver / editar": "View / edit",
    "plantilla ocupada": "workforce occupied",
    "fichados": "clocked in",
    "sin fichar": "not clocked in",
    "en otra obra": "on another site",
    "Planificado vs fichado": "Planned vs clocked in",
    "Fichado en": "Clocked in at",
    "Sem picar": "Not clocked in",  # if ES source uses Sin fichar
    "Sin fichar": "Not clocked in",
    "OK": "OK",
    "Hoy": "Today",
    "Trabajador": "Worker",
    "Planificado": "Planned",
    "Pedidos recientes": "Recent requests",
    "Solicitudes recientes": "Recent requests",
    "Obras con más personal hoy": "Sites with most staff today",
    "Sin asignaciones hoy": "No assignments today",
    "empresas": "companies",
    "int.": "int.",
    "ext.": "ext.",
    "Plantilla": "Workforce",
    "acceso completo": "full access",
    "pago": "paid",
    "gratis": "free",
    "Sin registros internos.": "No internal records.",
    "Sin operarios externos.": "No external workers.",
    "Restablecer contraseña": "Reset password",
    "Nueva contraseña": "New password",
    "Nueva clave…": "New password…",
    "PIN de fichaje": "Time-clock PIN",
    "Nuevo PIN": "New PIN",
    "Desasignar": "Unassign",
    "Asignar": "Assign",
    "Denegar": "Deny",
    "Petición": "Request",
    "Trabajo": "Work",
    "Perfil / Operario": "Profile / Worker",
    "Cobertura": "Coverage",
    "Plazas": "Slots",
    "Acción": "Action",
    "Solicitante": "Requester",
    "Periodo": "Period",
    "Período": "Period",
    "Vehículo": "Vehicle",
    "Operario": "Worker",
    "Personal": "Staff",
    "Subcontratas": "Subcontractors",
    "Obras": "Sites",
    "Importar": "Import",
    "Código": "Code",
    "Nombre": "Name",
    "Cliente": "Client",
    "Estado": "Status",
    "Inicio": "Start",  # date column (was wrongly Home)
    "Tipo": "Type",
    "Fecha": "Date",
    "Acciones": "Actions",
    "Eliminar": "Delete",
    "Email": "Email",
    "Rol": "Role",
    "DNI": "ID",
    "NIF": "Tax ID",
    "Activo": "Active",
    "Inactivo": "Inactive",
    "Pendiente": "Pending",
    "Seleccionar todas": "Select all",
    "Ordenar": "Sort",
    "Mostrar metadatos": "Show metadata",
    "Ocultar metadatos": "Hide metadata",
    "Privacidad": "Privacy",
    "Cargando…": "Loading…",
    "Tablero": "Board",
}

pt = {
    "Jefe": "Chefe",
    "Fin": "Fim",
    "Nueva": "Nova",
    "Nuevo": "Novo",
    "Asunto": "Assunto",
    "Resumen": "Resumo",
    "Asunto / Resumen": "Assunto / Resumo",
    "Implicados": "Envolvidos",
    "Acceso": "Acesso",
    "Encargado": "Encarregado",
    "Import.": "Import.",
    "Sols.": "Ped.",
    "Valor.": "Aval.",
    "Gremio": "Ofício",
    "seleccionadas": "selecionadas",
    "seleccionados": "selecionados",
    "Finalizar": "Finalizar",
    "Finalizada": "Finalizada",
    "En Curso": "Em curso",
    "En curso": "Em curso",
    "Desactivar": "Desativar",
    "Internos": "Internos",
    "Externos": "Externos",
    "Categoría": "Categoria",
    "Valoración": "Avaliação",
    "Cuaderno de Bitácora": "Caderno de bitácora",
    "Registro de reuniones, notas operativas e incidencias.": "Registo de reuniões, notas operativas e incidentes.",
    "Nueva nota / reunión": "Nova nota / reunião",
    "Privada": "Privada",
    "Pública": "Pública",
    "Ver / editar": "Ver / editar",
    "plantilla ocupada": "quadro ocupado",
    "fichados": "com ponto",
    "sin fichar": "sem ponto",
    "en otra obra": "noutra obra",
    "Planificado vs fichado": "Planeado vs picado",
    "Fichado en": "Picado em",
    "Sin fichar": "Sem ponto",
    "Hoy": "Hoje",
    "Trabajador": "Trabalhador",
    "Planificado": "Planeado",
    "Pedidos recientes": "Pedidos recentes",
    "Solicitudes recientes": "Pedidos recentes",
    "Obras con más personal hoy": "Obras com mais pessoal hoje",
    "Sin asignaciones hoy": "Sem atribuições hoje",
    "empresas": "empresas",
    "Plantilla": "Quadro",
    "acceso completo": "acesso completo",
    "pago": "pago",
    "gratis": "grátis",
    "Sin registros internos.": "Sem registos internos.",
    "Sin operarios externos.": "Sem operários externos.",
    "Restablecer contraseña": "Repor palavra-passe",
    "Nueva contraseña": "Nova palavra-passe",
    "Nueva clave…": "Nova palavra-passe…",
    "PIN de fichaje": "PIN de ponto",
    "Nuevo PIN": "Novo PIN",
    "Desasignar": "Desatribuir",
    "Asignar": "Atribuir",
    "Denegar": "Negar",
    "Petición": "Pedido",
    "Trabajo": "Trabalho",
    "Perfil / Operario": "Perfil / Operário",
    "Cobertura": "Cobertura",
    "Plazas": "Vagas",
    "Acción": "Ação",
    "Solicitante": "Requerente",
    "Periodo": "Período",
    "Período": "Período",
    "Vehículo": "Veículo",
    "Operario": "Operário",
    "Personal": "Pessoal",
    "Subcontratas": "Subempreiteiros",
    "Obras": "Obras",
    "Importar": "Importar",
    "Código": "Código",
    "Nombre": "Nome",
    "Cliente": "Cliente",
    "Estado": "Estado",
    "Inicio": "Início",
    "Tipo": "Tipo",
    "Fecha": "Data",
    "Acciones": "Ações",
    "Eliminar": "Eliminar",
    "Rol": "Função",
    "Activo": "Ativo",
    "Inactivo": "Inativo",
    "Pendiente": "Pendente",
    "Seleccionar todas": "Selecionar todas",
    "Ordenar": "Ordenar",
    "Mostrar metadatos": "Mostrar metadados",
    "Ocultar metadatos": "Ocultar metadados",
    "Privacidad": "Privacidade",
    "Cargando…": "A carregar…",
    "Tablero": "Painel",
    "Ver todas": "Ver todas",
    "Concreta": "Concreta",
    "Genérica": "Genérica",
    "Guardar": "Guardar",
    "Cancelar": "Cancelar",
    "Editar": "Editar",
    "Filtrar": "Filtrar",
}

fr = {
    "Jefe": "Chef",
    "Fin": "Fin",
    "Nueva": "Nouvelle",
    "Nuevo": "Nouveau",
    "Asunto": "Objet",
    "Resumen": "Résumé",
    "Asunto / Resumen": "Objet / Résumé",
    "Implicados": "Impliqués",
    "Acceso": "Accès",
    "Encargado": "Responsable",
    "Import.": "Import.",
    "Sols.": "Dem.",
    "Valor.": "Note",
    "Gremio": "Métier",
    "seleccionadas": "sélectionnées",
    "seleccionados": "sélectionnés",
    "Finalizar": "Terminer",
    "Finalizada": "Terminée",
    "En Curso": "En cours",
    "En curso": "En cours",
    "Desactivar": "Désactiver",
    "Internos": "Internes",
    "Externos": "Externes",
    "Categoría": "Catégorie",
    "Valoración": "Évaluation",
    "Cuaderno de Bitácora": "Journal de bord",
    "Registro de reuniones, notas operativas e incidencias.": "Réunions, notes opérationnelles et incidents.",
    "Nueva nota / reunión": "Nouvelle note / réunion",
    "Privada": "Privée",
    "Pública": "Publique",
    "Ver / editar": "Voir / modifier",
    "plantilla ocupada": "effectif occupé",
    "fichados": "pointés",
    "sin fichar": "non pointés",
    "en otra obra": "sur un autre chantier",
    "Planificado vs fichado": "Planifié vs pointé",
    "Fichado en": "Pointé sur",
    "Sin fichar": "Non pointé",
    "Hoy": "Aujourd'hui",
    "Trabajador": "Travailleur",
    "Planificado": "Planifié",
    "Solicitudes recientes": "Demandes récentes",
    "Obras con más personal hoy": "Chantiers avec le plus de personnel aujourd'hui",
    "Sin asignaciones hoy": "Aucune affectation aujourd'hui",
    "empresas": "entreprises",
    "Plantilla": "Effectif",
    "acceso completo": "accès complet",
    "pago": "payant",
    "gratis": "gratuit",
    "Sin registros internos.": "Aucun enregistrement interne.",
    "Sin operarios externos.": "Aucun ouvrier externe.",
    "Restablecer contraseña": "Réinitialiser le mot de passe",
    "Nueva contraseña": "Nouveau mot de passe",
    "Nueva clave…": "Nouveau mot de passe…",
    "PIN de fichaje": "PIN de pointage",
    "Nuevo PIN": "Nouveau PIN",
    "Desasignar": "Désaffecter",
    "Asignar": "Affecter",
    "Denegar": "Refuser",
    "Petición": "Demande",
    "Trabajo": "Travail",
    "Perfil / Operario": "Profil / Ouvrier",
    "Cobertura": "Couverture",
    "Plazas": "Places",
    "Acción": "Action",
    "Solicitante": "Demandeur",
    "Periodo": "Période",
    "Período": "Période",
    "Vehículo": "Véhicule",
    "Operario": "Ouvrier",
    "Personal": "Personnel",
    "Subcontratas": "Sous-traitants",
    "Obras": "Chantiers",
    "Importar": "Importer",
    "Código": "Code",
    "Nombre": "Nom",
    "Cliente": "Client",
    "Estado": "Statut",
    "Inicio": "Début",
    "Tipo": "Type",
    "Fecha": "Date",
    "Acciones": "Actions",
    "Eliminar": "Supprimer",
    "Rol": "Rôle",
    "Activo": "Actif",
    "Inactivo": "Inactif",
    "Pendiente": "En attente",
    "Seleccionar todas": "Tout sélectionner",
    "Ordenar": "Trier",
    "Mostrar metadatos": "Afficher les métadonnées",
    "Ocultar metadatos": "Masquer les métadonnées",
    "Privacidad": "Confidentialité",
    "Cargando…": "Chargement…",
    "Tablero": "Tableau",
    "Ver todas": "Voir tout",
    "Concreta": "Spécifique",
    "Genérica": "Générique",
}

def load(name):
    p = base / name
    return json.loads(p.read_text(encoding="utf-8"))

def save(name, data):
    (base / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

en_all = load("_en_keys.json")
fr_all = load("_fr_full.json")
pt_all = load("_pt_full.json")

en_all.update(en)
fr_all.update(fr)
pt_all.update(pt)

# Ensure every EN key exists in FR/PT
for k, v in en_all.items():
    fr_all.setdefault(k, fr_all.get(k) or v)
    pt_all.setdefault(k, pt_all.get(k) or v)

save("_en_keys.json", en_all)
save("_fr_full.json", fr_all)
save("_pt_full.json", pt_all)

# Patch APP_UI_EN: update Inicio and add missing
app_path = base / "app/services/i18n_catalog_app.py"
text = app_path.read_text(encoding="utf-8")
# Fix Inicio: Home -> Start
text2 = re.sub(r"(['\"]Inicio['\"]\s*:\s*)['\"]Home['\"]", r"\1'Start'", text)
if text2 == text:
    # maybe already Start or different quoting
    pass
text = text2

# Add missing keys before closing of APP_UI_EN
existing = set(re.findall(r"^\s*'((?:\\'|[^'])*)'\s*:", text, flags=re.M))
existing |= set(re.findall(r'^\s*"((?:\\"|[^"])*)"\s*:', text, flags=re.M))
to_add = {k: v for k, v in en.items() if k not in existing}
# Also force-update keys that must change
force = {"Inicio": "Start", "plantilla ocupada": "workforce occupied", "Tablero": "Board"}
marker = "\n# PT/FR: complete locale maps"
idx = text.index(marker)
before = text[:idx].rstrip()
close_idx = before.rfind("}")
lines = ["\n    # --- list headers / short UI ---\n"]
for k, v in sorted({**to_add, **{k: force[k] for k in force if k in en_all}}.items()):
    if k in existing and k not in force:
        continue
    lines.append(f"    {k!r}: {v!r},\n")
insert = "".join(lines)
# Remove old Inicio/Plantilla lines if force - already regex fixed Inicio
new_text = text[:close_idx] + insert + text[close_idx:]
# Deduplicate by rewriting APP_UI_EN carefully: run a small dedupe
app_path.write_text(new_text, encoding="utf-8")

# Dedupe APP_UI_EN keys keeping last
src = app_path.read_text(encoding="utf-8")
m = re.search(r"APP_UI_EN\s*=\s*\{", src)
if m:
    start = m.end() - 1
    # find matching brace
    depth = 0
    end = None
    for i, ch in enumerate(src[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    body = src[start + 1 : end]
    # parse naive key: value pairs with ast
    import ast
    try:
        d = ast.literal_eval("{" + body + "}")
    except Exception as e:
        print("ast fail", e)
        d = None
    if d is not None:
        d.update(en)
        d.update(force)
        # rebuild
        lines = ["APP_UI_EN = {\n"]
        for k, v in d.items():
            lines.append(f"    {k!r}: {v!r},\n")
        lines.append("}\n")
        new_src = src[: m.start()] + "".join(lines) + src[end + 1 :]
        # keep PT/FR aliases after
        app_path.write_text(new_src, encoding="utf-8")
        print("rebuilt APP_UI_EN", len(d))

print("ok", len(en_all), len(fr_all), len(pt_all))
print("Jefe PT", pt_all["Jefe"], "EN", en_all["Jefe"])
print("Inicio EN", en_all["Inicio"], "plantilla", pt_all["plantilla ocupada"])
print("Tablero PT", pt_all["Tablero"])
