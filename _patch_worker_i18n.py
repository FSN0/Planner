#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Catalog patch for worker panel / kanban / form / vehicle audit strings."""
import ast
import json
import re
from pathlib import Path

base = Path("/opt/soltec/planner")

en = {
    "Empleado": "Employee",
    "Externo": "External",
    "Sin empresa": "No company",
    "Sin Empresa": "No company",
    "Sin categoría": "No category",
    "Especialidad": "Specialty",
    "Reputación": "Reputation",
    "Reputación actual": "Current reputation",
    "Puntuar": "Rate",
    "Historial": "History",
    "Conductor Odoo": "Odoo driver",
    "Sin vehículos planificados ni uso Odoo en los últimos 30 días.": "No planned vehicles or Odoo usage in the last 30 days.",
    "Valorar a": "Rate",
    "Selecciona una puntuación entre -3 y +3": "Select a score between -3 and +3",
    "Motivo (opcional)": "Reason (optional)",
    "Describe brevemente el motivo de la valoración…": "Briefly describe the reason for the rating…",
    "Guardar valoración": "Save rating",
    "¿Resetear contador a 0? Las valoraciones antiguas se guardarán en el historial.": "Reset counter to 0? Old ratings will be kept in history.",
    "Resetear contador": "Reset counter",
    "libres": "free",
    "total": "total",
    "Libres": "Free",
    "Ocupados hoy": "Busy today",
    "Ocupado en otra obra": "Busy on another site",
    "No hay operarios.": "No workers.",
    "No se encontraron coincidencias.": "No matches found.",
    "Correcto": "OK",
    "Auto-Asignado": "Auto-assigned",
    "Conflicto": "Conflict",
    "Resuelto / correcto": "Resolved / OK",
    "Sin Registro": "No record",
    "Usuario activo": "Active user",
    "Puede ser asignado a obras": "Can be assigned to sites",
    "Notificaciones por email": "Email notifications",
    "Recibir avisos de asignaciones y cambios": "Receive assignment and change alerts",
    "Editar Usuario": "Edit user",
    "Nuevo Usuario": "New user",
    "Editar persona": "Edit person",
    "Nueva persona": "New person",
    "Nuevo usuario": "New user",
    "Complete la información del personal": "Fill in the staff details",
    "Datos de cuenta": "Account details",
    "Contraseña": "Password",
    "Rol de sistema": "System role",
    "Jefe de obra": "Site manager",
    "RRHH / Administrativo": "HR / Admin",
    "Laboral": "Labour",
    "Administrador": "Administrator",
    "Define los permisos de acceso a la plataforma.": "Defines access permissions on the platform.",
    "Información personal": "Personal information",
    "Apellidos": "Last name",
    "DNI / NIE": "ID document",
    "Perfil profesional": "Professional profile",
    "Categoría (nómina)": "Category (payroll)",
    "Especialidad (oficio)": "Specialty (trade)",
    "Afiliación": "Affiliation",
    "— Seleccione empresa —": "— Select company —",
    "Crear usuario": "Create user",
    "Saltos de odómetro": "Odometer jumps",
    "Saltos de odometro": "Odometer jumps",
    "desvío vs km planificados": "deviation vs planned km",
    "desvio vs km planificados": "deviation vs planned km",
    "Desvío km previsto": "Planned km deviation",
    "Desvío vs km planificados": "Deviation vs planned km",
    "Operarios": "Workers",
}

pt = {
    "Empleado": "Empregado",
    "Externo": "Externo",
    "Sin empresa": "Sem empresa",
    "Sin Empresa": "Sem empresa",
    "Sin categoría": "Sem categoria",
    "Especialidad": "Especialidade",
    "Reputación": "Reputação",
    "Reputación actual": "Reputação atual",
    "Puntuar": "Avaliar",
    "Historial": "Histórico",
    "Conductor Odoo": "Condutor Odoo",
    "Sin vehículos planificados ni uso Odoo en los últimos 30 días.": "Sem veículos planeados nem uso Odoo nos últimos 30 dias.",
    "Valorar a": "Avaliar",
    "Selecciona una puntuación entre -3 y +3": "Selecione uma pontuação entre -3 e +3",
    "Motivo (opcional)": "Motivo (opcional)",
    "Describe brevemente el motivo de la valoración…": "Descreva brevemente o motivo da avaliação…",
    "Guardar valoración": "Guardar avaliação",
    "¿Resetear contador a 0? Las valoraciones antiguas se guardarán en el historial.": "Repor contador a 0? As avaliações antigas ficarão no histórico.",
    "Resetear contador": "Repor contador",
    "libres": "livres",
    "total": "total",
    "Libres": "Livres",
    "Ocupados hoy": "Ocupados hoje",
    "Ocupado en otra obra": "Ocupado noutra obra",
    "No hay operarios.": "Não há operários.",
    "No se encontraron coincidencias.": "Não foram encontradas coincidências.",
    "Correcto": "OK",
    "Auto-Asignado": "Autoatribuído",
    "Conflicto": "Conflito",
    "Resuelto / correcto": "Resolvido / OK",
    "Sin Registro": "Sem registo",
    "Usuario activo": "Utilizador ativo",
    "Puede ser asignado a obras": "Pode ser atribuído a obras",
    "Notificaciones por email": "Notificações por e-mail",
    "Recibir avisos de asignaciones y cambios": "Receber avisos de atribuições e alterações",
    "Editar Usuario": "Editar utilizador",
    "Nuevo Usuario": "Novo utilizador",
    "Editar persona": "Editar pessoa",
    "Nueva persona": "Nova pessoa",
    "Nuevo usuario": "Novo utilizador",
    "Complete la información del personal": "Preencha a informação do pessoal",
    "Datos de cuenta": "Dados da conta",
    "Contraseña": "Palavra-passe",
    "Rol de sistema": "Função do sistema",
    "Jefe de obra": "Chefe de obra",
    "RRHH / Administrativo": "RH / Administrativo",
    "Laboral": "Laboral",
    "Administrador": "Administrador",
    "Define los permisos de acceso a la plataforma.": "Define as permissões de acesso à plataforma.",
    "Información personal": "Informação pessoal",
    "Apellidos": "Apelidos",
    "DNI / NIE": "Documento de identidade",
    "Perfil profesional": "Perfil profissional",
    "Categoría (nómina)": "Categoria (folha)",
    "Especialidad (oficio)": "Especialidade (ofício)",
    "Afiliación": "Afiliação",
    "— Seleccione empresa —": "— Selecione empresa —",
    "Crear usuario": "Criar utilizador",
    "Saltos de odómetro": "Saltos de odómetro",
    "Saltos de odometro": "Saltos de odómetro",
    "desvío vs km planificados": "desvio vs km planeados",
    "desvio vs km planificados": "desvio vs km planeados",
    "Desvío km previsto": "Desvio km previsto",
    "Desvío vs km planificados": "Desvio vs km planeados",
    "Operarios": "Operários",
}

fr = {
    "Empleado": "Employé",
    "Externo": "Externe",
    "Sin empresa": "Sans entreprise",
    "Sin Empresa": "Sans entreprise",
    "Sin categoría": "Sans catégorie",
    "Especialidad": "Spécialité",
    "Reputación": "Réputation",
    "Reputación actual": "Réputation actuelle",
    "Puntuar": "Noter",
    "Historial": "Historique",
    "Conductor Odoo": "Conducteur Odoo",
    "Sin vehículos planificados ni uso Odoo en los últimos 30 días.": "Aucun véhicule planifié ni usage Odoo sur les 30 derniers jours.",
    "Valorar a": "Évaluer",
    "Selecciona una puntuación entre -3 y +3": "Choisissez une note entre -3 et +3",
    "Motivo (opcional)": "Motif (facultatif)",
    "Describe brevemente el motivo de la valoración…": "Décrivez brièvement le motif de l'évaluation…",
    "Guardar valoración": "Enregistrer l'évaluation",
    "¿Resetear contador a 0? Las valoraciones antiguas se guardarán en el historial.": "Remettre le compteur à 0 ? Les anciennes évaluations seront conservées dans l'historique.",
    "Resetear contador": "Réinitialiser le compteur",
    "libres": "libres",
    "total": "total",
    "Libres": "Libres",
    "Ocupados hoy": "Occupés aujourd'hui",
    "Ocupado en otra obra": "Occupé sur un autre chantier",
    "No hay operarios.": "Aucun ouvrier.",
    "No se encontraron coincidencias.": "Aucune correspondance.",
    "Correcto": "OK",
    "Auto-Asignado": "Auto-affecté",
    "Conflicto": "Conflit",
    "Resuelto / correcto": "Résolu / OK",
    "Sin Registro": "Sans enregistrement",
    "Usuario activo": "Utilisateur actif",
    "Puede ser asignado a obras": "Peut être affecté aux chantiers",
    "Notificaciones por email": "Notifications par e-mail",
    "Recibir avisos de asignaciones y cambios": "Recevoir les alertes d'affectations et de changements",
    "Editar Usuario": "Modifier l'utilisateur",
    "Nuevo Usuario": "Nouvel utilisateur",
    "Editar persona": "Modifier la personne",
    "Nueva persona": "Nouvelle personne",
    "Nuevo usuario": "Nouvel utilisateur",
    "Complete la información del personal": "Complétez les informations du personnel",
    "Datos de cuenta": "Données du compte",
    "Contraseña": "Mot de passe",
    "Rol de sistema": "Rôle système",
    "Jefe de obra": "Chef de chantier",
    "RRHH / Administrativo": "RH / Administratif",
    "Laboral": "Social",
    "Administrador": "Administrateur",
    "Define los permisos de acceso a la plataforma.": "Définit les droits d'accès à la plateforme.",
    "Información personal": "Informations personnelles",
    "Apellidos": "Nom de famille",
    "DNI / NIE": "Pièce d'identité",
    "Perfil profesional": "Profil professionnel",
    "Categoría (nómina)": "Catégorie (paie)",
    "Especialidad (oficio)": "Spécialité (métier)",
    "Afiliación": "Affiliation",
    "— Seleccione empresa —": "— Sélectionnez une entreprise —",
    "Crear usuario": "Créer l'utilisateur",
    "Saltos de odómetro": "Sauts d'odomètre",
    "Saltos de odometro": "Sauts d'odomètre",
    "desvío vs km planificados": "écart vs km planifiés",
    "desvio vs km planificados": "écart vs km planifiés",
    "Desvío km previsto": "Écart km prévu",
    "Desvío vs km planificados": "Écart vs km planifiés",
    "Operarios": "Ouvriers",
}


def load(name):
    return json.loads((base / name).read_text(encoding="utf-8"))


def save(name, data):
    (base / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


en_all = load("_en_keys.json")
fr_all = load("_fr_full.json")
pt_all = load("_pt_full.json")
en_all.update(en)
fr_all.update(fr)
pt_all.update(pt)
for k, v in en_all.items():
    fr_all.setdefault(k, fr_all.get(k) or v)
    pt_all.setdefault(k, pt_all.get(k) or v)
save("_en_keys.json", en_all)
save("_fr_full.json", fr_all)
save("_pt_full.json", pt_all)

# Merge into APP_UI_EN via ast rebuild of dict
app_path = base / "app/services/i18n_catalog_app.py"
src = app_path.read_text(encoding="utf-8")
m = re.search(r"APP_UI_EN\s*=\s*\{", src)
start = m.end() - 1
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
d = ast.literal_eval("{" + body + "}")
d.update(en)
lines = ["APP_UI_EN = {\n"]
for k, v in d.items():
    lines.append(f"    {k!r}: {v!r},\n")
lines.append("}\n")
# Keep everything after APP_UI_EN closing brace
rest = src[end + 1 :]
# Ensure PT/FR aliases still there
if "APP_UI_PT" not in rest:
    rest = (
        "\n# PT/FR: complete locale maps (no English fallback).\n"
        "from app.services.i18n_catalog_locales import APP_UI_FR_FULL, APP_UI_PT_FULL\n"
        "APP_UI_PT = APP_UI_PT_FULL\n"
        "APP_UI_FR = APP_UI_FR_FULL\n"
        + rest
    )
# Fix duplicate imports if we already import at top
# Prefer not duplicating - check top of file
head = src[: m.start()]
if "APP_UI_FR_FULL" in head and "from app.services.i18n_catalog_locales import" in head:
    # strip accidental re-import block we might have added
    rest = re.sub(
        r"\n# PT/FR: complete locale maps.*?\nAPP_UI_FR = APP_UI_FR_FULL\n",
        "\n# PT/FR: complete locale maps (no English fallback).\nAPP_UI_PT = APP_UI_PT_FULL\nAPP_UI_FR = APP_UI_FR_FULL\n",
        rest,
        count=1,
        flags=re.S,
    )
    if "APP_UI_PT = APP_UI_PT_FULL" not in rest:
        rest = (
            "\n# PT/FR: complete locale maps (no English fallback).\n"
            "APP_UI_PT = APP_UI_PT_FULL\n"
            "APP_UI_FR = APP_UI_FR_FULL\n"
            + rest
        )

app_path.write_text(head + "".join(lines) + rest, encoding="utf-8")
import py_compile

py_compile.compile(str(app_path), doraise=True)
print("ok", len(d), "libres PT", pt_all["libres"], "Usuario activo PT", pt_all["Usuario activo"])
