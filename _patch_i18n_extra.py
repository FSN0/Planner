#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
from pathlib import Path

base = Path("/opt/soltec/planner")
en = json.loads((base / "_en_keys.json").read_text(encoding="utf-8"))
fr = json.loads((base / "_fr_full.json").read_text(encoding="utf-8"))
pt = json.loads((base / "_pt_full.json").read_text(encoding="utf-8"))

HINT_ES = (
    "Libre = sin conductor planificado, o el planificado de ausencia. "
    "Los tramos del mismo coche van juntos. Si no hay más plan hasta el horizonte, "
    "solo verás «Desde … en adelante» (sin hasta inventado)."
)
HINT_EN = (
    "Free = no planned driver, or the planned driver is on leave. "
    "Segments for the same vehicle are grouped. If there is no further plan until the horizon, "
    'you will only see "From … onwards" (no invented end date).'
)
HINT_FR = (
    "Libre = sans conducteur planifié, ou le conducteur planifié est en absence. "
    "Les segments du même véhicule sont regroupés. S'il n'y a plus de plan jusqu'à l'horizon, "
    "vous ne verrez que « Du … en avant » (sans date de fin inventée)."
)
HINT_PT = (
    "Livre = sem condutor planeado, ou o planeado está de ausência. "
    "Os troços do mesmo veículo ficam juntos. Se não houver mais plano até ao horizonte, "
    "só verá « De … em diante » (sem data final inventada)."
)

# Also cover the exact hint string used in the template (may use «Du» already in FR UI paste)
HINT_ES_ALT = (
    "Libre = sin conductor planificado, o el planificado de ausencia. "
    "Los tramos del mismo coche van juntos. Si no hay más plan hasta el horizonte, "
    "solo verás «Du … en adelante» (sin hasta inventado)."
)

extra_en = {
    "Todas las obras": "All sites",
    "Tu personal": "Your staff",
    HINT_ES: HINT_EN,
    HINT_ES_ALT: HINT_EN,
    "Tramos libres": "Free segments",
    "Por ausencia": "Due to leave",
    "Buscar coche": "Search vehicle",
    "Matrícula o nombre…": "Plate or name…",
    "Horizonte": "Horizon",
    "Todos los motivos": "All reasons",
    "Sin plan / Ausencia": "Unplanned / Leave",
    "en adelante": "onwards",
    "mes": "month",
    "meses": "months",
    "No especificado": "Not specified",
    "No especificada": "Not specified",
    "Enlace externo": "External link",
    "En curso": "In progress",
    "Sin límite": "No limit",
    "Sin límite definido": "No limit defined",
    "Cupo máximo": "Max capacity",
    "Cliente": "Client",
    "Sin asignaciones de vehículo en los últimos 30 días.": "No vehicle assignments in the last 30 days.",
    "Sin NIF": "No tax ID",
    "Empresa interna": "Internal company",
    "Subcontrata / externa": "Subcontractor / external",
    "Color identificativo": "Identifying colour",
    "Indicadores": "Indicators",
    "Actividad últimos 14 días": "Activity last 14 days",
    "Operarios hoy": "Workers today",
    "Empresas hoy": "Companies today",
    "Días-persona mes": "Person-days this month",
    "Próx. 7 días": "Next 7 days",
    "Vehículos en obra": "Vehicles on site",
    "Plantilla": "Workforce",
    "En obra hoy": "On site today",
    "Intervenciones 30d": "Interventions 30d",
    "Valoración media": "Average rating",
    "Incidencias fichaje": "Time-clock incidents",
    "En curso hoy": "Ongoing today",
    "Próximas": "Upcoming",
    "Conflictos": "Conflicts",
    "Solicitudes de jefe / altas pendientes": "Manager requests / pending sign-ups",
    "Tus solicitudes en espera": "Your pending requests",
    "Empleado": "Employee",
    "En curso ahora": "Ongoing now",
    "Quien está de vacaciones / baja / permiso hoy": "Who is on vacation / sick leave / leave today",
    "Próximas ausencias": "Upcoming leave",
    "Empiezan en los próximos 45 días (aún no han empezado)": "Starting in the next 45 days (not started yet)",
    "Alta de ausencia": "Register leave",
    "Listado / historial": "List / history",
    "Consulta y filtros · global": "Browse and filters · global",
    "Integración Odoo": "Odoo integration",
    "Añadir vehículo": "Add vehicle",
    "Ej. Furgoneta 1": "E.g. Van 1",
    "registros": "records",
    "Filtros activos:": "Active filters:",
    "Asignación (genérica)": "Assignment (generic)",
    "Movimiento (concreta)": "Transfer (specific)",
    "Buscar operario o empresa...": "Search worker or company...",
    "S/C": "N/A",
    "Vacaciones": "Vacation",
    "Approve": "Approve",
    "Reject": "Reject",
    "Pending validation": "Pending validation",
    "Create manual leave (in addition to ERP sync)": "Create manual leave (in addition to ERP sync)",
    "Synchronisation ERP disponible": "ERP sync available",
    "Synchroniser ERP": "Sync ERP",
}

extra_fr = {
    "Todas las obras": "Tous les chantiers",
    "Tu personal": "Votre personnel",
    HINT_ES: HINT_FR,
    HINT_ES_ALT: HINT_FR,
    "Tramos libres": "Segments libres",
    "Por ausencia": "Pour absence",
    "Buscar coche": "Rechercher un véhicule",
    "Matrícula o nombre…": "Immatriculation ou nom…",
    "Horizonte": "Horizon",
    "Todos los motivos": "Tous les motifs",
    "Sin plan / Ausencia": "Sans plan / Absence",
    "en adelante": "en avant",
    "mes": "mois",
    "meses": "mois",
    "No especificado": "Non spécifié",
    "No especificada": "Non spécifiée",
    "Enlace externo": "Lien externe",
    "En curso": "En cours",
    "Sin límite": "Sans limite",
    "Sin límite definido": "Aucune limite définie",
    "Cupo máximo": "Capacité max.",
    "Cliente": "Client",
    "Sin asignaciones de vehículo en los últimos 30 días.": "Aucune affectation de véhicule sur les 30 derniers jours.",
    "Sin NIF": "Sans NIF",
    "Empresa interna": "Entreprise interne",
    "Subcontrata / externa": "Sous-traitant / externe",
    "Color identificativo": "Couleur d'identification",
    "Indicadores": "Indicateurs",
    "Actividad últimos 14 días": "Activité des 14 derniers jours",
    "Operarios hoy": "Ouvriers aujourd'hui",
    "Empresas hoy": "Entreprises aujourd'hui",
    "Días-persona mes": "Jours-personne du mois",
    "Próx. 7 días": "Proch. 7 jours",
    "Vehículos en obra": "Véhicules sur chantier",
    "Plantilla": "Effectif",
    "En obra hoy": "Sur chantier aujourd'hui",
    "Intervenciones 30d": "Interventions 30j",
    "Valoración media": "Note moyenne",
    "Incidencias fichaje": "Incidents de pointage",
    "En curso hoy": "En cours aujourd'hui",
    "Próximas": "À venir",
    "Conflictos": "Conflits",
    "Solicitudes de jefe / altas pendientes": "Demandes de chef / inscriptions en attente",
    "Tus solicitudes en espera": "Vos demandes en attente",
    "Empleado": "Employé",
    "En curso ahora": "En cours maintenant",
    "Quien está de vacaciones / baja / permiso hoy": "Qui est en vacances / arrêt / congé aujourd'hui",
    "Próximas ausencias": "Absences à venir",
    "Empiezan en los próximos 45 días (aún no han empezado)": "Commencent dans les 45 prochains jours (pas encore commencées)",
    "Alta de ausencia": "Créer une absence",
    "Listado / historial": "Liste / historique",
    "Consulta y filtros · global": "Consultation et filtres · global",
    "Integración Odoo": "Intégration Odoo",
    "Añadir vehículo": "Ajouter un véhicule",
    "Ej. Furgoneta 1": "Ex. Fourgon 1",
    "registros": "enregistrements",
    "Filtros activos:": "Filtres actifs :",
    "Asignación (genérica)": "Affectation (générique)",
    "Movimiento (concreta)": "Mouvement (spécifique)",
    "Buscar operario o empresa...": "Rechercher ouvrier ou entreprise...",
    "S/C": "S/C",
    "Vacaciones": "Vacances",
    "Salida": "Sortie",
    "Aprobar": "Approuver",
    "Rechazar": "Refuser",
    "Pendientes de validar": "En attente de validation",
    "Approve": "Approuver",
    "Reject": "Refuser",
    "Pending validation": "En attente de validation",
    "Create manual leave (in addition to ERP sync)": "Créer une absence manuelle (en plus de la sync ERP)",
    "Synchronisation ERP disponible": "Synchronisation ERP disponible",
    "Synchroniser ERP": "Synchroniser ERP",
}

extra_pt = {
    "Todas las obras": "Todas as obras",
    "Tu personal": "O seu pessoal",
    HINT_ES: HINT_PT,
    HINT_ES_ALT: HINT_PT,
    "Tramos libres": "Troços livres",
    "Por ausencia": "Por ausência",
    "Buscar coche": "Pesquisar veículo",
    "Matrícula o nombre…": "Matrícula ou nome…",
    "Horizonte": "Horizonte",
    "Todos los motivos": "Todos os motivos",
    "Sin plan / Ausencia": "Sem plano / Ausência",
    "en adelante": "em diante",
    "mes": "mês",
    "meses": "meses",
    "No especificado": "Não especificado",
    "No especificada": "Não especificada",
    "Enlace externo": "Link externo",
    "En curso": "Em curso",
    "Sin límite": "Sem limite",
    "Sin límite definido": "Sem limite definido",
    "Cupo máximo": "Lotação máxima",
    "Cliente": "Cliente",
    "Sin asignaciones de vehículo en los últimos 30 días.": "Sem atribuições de veículo nos últimos 30 dias.",
    "Sin NIF": "Sem NIF",
    "Empresa interna": "Empresa interna",
    "Subcontrata / externa": "Subempreiteiro / externa",
    "Color identificativo": "Cor identificativa",
    "Indicadores": "Indicadores",
    "Actividad últimos 14 días": "Atividade últimos 14 dias",
    "Operarios hoy": "Operários hoje",
    "Empresas hoy": "Empresas hoje",
    "Días-persona mes": "Dias-pessoa do mês",
    "Próx. 7 días": "Próx. 7 dias",
    "Vehículos en obra": "Veículos em obra",
    "Plantilla": "Quadro",
    "En obra hoy": "Em obra hoje",
    "Intervenciones 30d": "Intervenções 30d",
    "Valoración media": "Avaliação média",
    "Incidencias fichaje": "Incidentes de ponto",
    "En curso hoy": "Em curso hoje",
    "Próximas": "Próximas",
    "Conflictos": "Conflitos",
    "Solicitudes de jefe / altas pendientes": "Pedidos de chefe / altas pendentes",
    "Tus solicitudes en espera": "Os seus pedidos em espera",
    "Empleado": "Empregado",
    "En curso ahora": "Em curso agora",
    "Quien está de vacaciones / baja / permiso hoy": "Quem está de férias / baixa / licença hoje",
    "Próximas ausencias": "Próximas ausências",
    "Empiezan en los próximos 45 días (aún no han empezado)": "Começam nos próximos 45 dias (ainda não começaram)",
    "Alta de ausencia": "Registar ausência",
    "Listado / historial": "Lista / histórico",
    "Consulta y filtros · global": "Consulta e filtros · global",
    "Integración Odoo": "Integração Odoo",
    "Añadir vehículo": "Adicionar veículo",
    "Ej. Furgoneta 1": "Ex. Carrinha 1",
    "registros": "registos",
    "Filtros activos:": "Filtros ativos:",
    "Asignación (genérica)": "Atribuição (genérica)",
    "Movimiento (concreta)": "Movimento (específica)",
    "Buscar operario o empresa...": "Pesquisar operário ou empresa...",
    "Vacaciones": "Férias",
    "Salida": "Saída",
    "Aprobar": "Aprovar",
    "Rechazar": "Rejeitar",
    "Pendientes de validar": "Pendentes de validar",
    "Approve": "Aprovar",
    "Reject": "Rejeitar",
    "Pending validation": "Validação pendente",
    "Create manual leave (in addition to ERP sync)": "Criar ausência manual (além da sync ERP)",
    "Synchronisation ERP disponible": "Sincronização ERP disponível",
    "Synchroniser ERP": "Sincronizar ERP",
}

en.update(extra_en)
fr.update(extra_fr)
pt.update(extra_pt)

for k, v in en.items():
    fr.setdefault(k, fr.get(k) or v)
    pt.setdefault(k, pt.get(k) or v)

(base / "_en_keys.json").write_text(json.dumps(en, ensure_ascii=False, indent=2), encoding="utf-8")
(base / "_fr_full.json").write_text(json.dumps(fr, ensure_ascii=False, indent=2), encoding="utf-8")
(base / "_pt_full.json").write_text(json.dumps(pt, ensure_ascii=False, indent=2), encoding="utf-8")

print("updated", len(en), len(fr), len(pt))
print("Todas las obras FR:", fr["Todas las obras"])
print("Salida FR:", fr["Salida"])
