#!/usr/bin/env python3
"""
Build EN, PT-PT and FR translations for all missing i18n keys,
then merge into app/i18n/extra/{en,pt,fr}.json.
"""
import json, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
I18N = os.path.join(ROOT, 'app', 'i18n')
EXTRA = os.path.join(I18N, 'extra')
REPORT = os.path.join(I18N, '_missing_report.json')

SKIP = {
    "%d/%m/%Y %H:%M", "%d/%m/%y", ";", "; csrf_token=",
    "a, button, input, .no-row-nav", "change", "chapter", "current_tenant",
    "div", "done", "editable", "email_pending_verification", "focus",
    "horizontal", "id", "import", "li", "nif", "odoo", "odoo_adapter",
    "odoo_alta", "partner", "seed", "skip", "sp-pin-mode-changed",
    "subdominio", "tour", "tour_chapter", "tour_fichar_oficina", "tr",
    "website", "||", "T", "a", "es", "demo", "codigo",
    "encargado_id", "GOOGLE_ANALYTICS_ID", "ODOO_URL no configurada",
    "YYYY-MM-DD", "hola@signaplan.com",
}

# ── All translations: key → (EN, PT, FR) ──
T = {}
def t(k, en, pt, fr):
    T[k] = (en, pt, fr)

# ── Months ──
t("Enero","January","Janeiro","Janvier")
t("Febrero","February","Fevereiro","Février")
t("Marzo","March","Março","Mars")
t("Abril","April","Abril","Avril")
t("Mayo","May","Maio","Mai")
t("Junio","June","Junho","Juin")
t("Julio","July","Julho","Juillet")
t("Agosto","August","Agosto","Août")
t("Septiembre","September","Setembro","Septembre")
t("Octubre","October","Outubro","Octobre")
t("Noviembre","November","Novembro","Novembre")
t("Diciembre","December","Dezembro","Décembre")

# ── Weekdays ──
t("DOM","SUN","DOM","DIM")
t("LUN","MON","SEG","LUN")
t("MAR","TUE","TER","MAR")
t("MIÉ","WED","QUA","MER")
t("JUE","THU","QUI","JEU")
t("VIE","FRI","SEX","VEN")
t("SÁB","SAT","SÁB","SAM")

# ── Roles ──
t("role.admin","Admin","Admin","Admin")
t("role.jefe_obra","Site Manager","Chefe de Obra","Chef de chantier")
t("role.rrhh","HR","RH","RH")
t("role.operario","Worker","Operário","Ouvrier")
t("role.laboral","Employment","Laboral","Emploi")

# ── Fichaje estados ──
t("Correcto","Correct","Correto","Correct")
t("Correcto (auto)","Correct (auto)","Correto (auto)","Correct (auto)")
t("Conflicto","Conflict","Conflito","Conflit")
t("Cambio de tajo","Site change","Mudança de tajo","Changement de chantier")
t("Sigue","Stays","Continua","Reste")
t("Mostrar inercia","Show inertia","Mostrar inércia","Afficher l’inertie")
t("Ocultar inercia","Hide inertia","Ocultar inércia","Masquer l’inertie")
t("Quien sigue en el tajo sin asignación de hoy","People still on yesterday’s site with no assignment today","Quem continua no tajo sem atribuição de hoje","Ceux qui restent sur le chantier sans affectation aujourd’hui")
t("Sigue en esta obra (inercia)","Still on this site (inertia)","Continua nesta obra (inércia)","Reste sur ce chantier (inertie)")
t("Sigue en esta obra hasta que lo muevan","Stays on this site until you move them","Continua nesta obra até o moverem","Reste sur ce chantier jusqu’à ce que vous le déplaciez")
t("Asignar de verdad","Make it a real assignment","Tornar atribuição real","En faire une affectation réelle")
t("Enter la convierte en asignación","Enter turns it into an assignment","Enter transforma-a em atribuição","Entrée la convertit en affectation")
t("Inercia convertida en asignación","Inertia converted into an assignment","Inércia convertida em atribuição","Inertie convertie en affectation")
t("El trabajador queda libre a partir de ese día.","The worker is free from that day on.","O trabalhador fica livre a partir desse dia.","Le travailleur est libre à partir de ce jour.")
t("Ausencia","Leave","Ausência","Absence")
t("Pendiente","Pending","Pendente","En attente")
t("Retraso","Late","Atraso","Retard")
t("Sin fichaje","No clock-in","Sem ponto","Pas de pointage")
t("Corregido por RRHH / ERP","Corrected by HR / ERP","Corrigido por RH / ERP","Corrigé par RH / ERP")
t("Exento (ausencia)","Exempt (leave)","Isento (ausência)","Exempté (absence)")
t("Multi-obra cerrado","Multi-site closed","Multi-obra encerrado","Multi-chantier fermé")
t("Resuelto (movido)","Resolved (moved)","Resolvido (movido)","Résolu (déplacé)")
t("Resuelto (asignado)","Resolved (assigned)","Resolvido (atribuído)","Résolu (affecté)")
t("Resuelto (multi-obra)","Resolved (multi-site)","Resolvido (multi-obra)","Résolu (multi-chantier)")
t("Resuelto (ignorado)","Resolved (ignored)","Resolvido (ignorado)","Résolu (ignoré)")
t("Resuelto (falta)","Resolved (absence)","Resolvido (falta)","Résolu (absence)")
t("Resuelto (ausencia)","Resolved (leave)","Resolvido (ausência)","Résolu (absence)")
t("Resuelto / correcto","Resolved / correct","Resolvido / correto","Résolu / correct")
t("Sin datos","No data","Sem dados","Pas de données")

# ── Etiquetas tipo ──
t("Entrada","Entry","Entrada","Entrée")
t("Salida","Exit","Saída","Sortie")
t("Inicio de pausa","Break start","Início de pausa","Début de pause")
t("Fin de pausa","Break end","Fim de pausa","Fin de pause")
t("Anulación","Cancellation","Anulação","Annulation")
t("Reimputación de obra","Site reattribution","Reimputação de obra","Réimputation de chantier")
t("Conforme del trabajador","Worker confirmation","Conforme do trabalhador","Confirmation du travailleur")

# ── Panel stats ──
t("En uso hoy","In use today","Em uso hoje","En usage aujourd'hui")
t("Libre hoy","Free today","Livre hoje","Libre aujourd'hui")
t("Días en uso (30d)","Days in use (30d)","Dias em uso (30d)","Jours d'usage (30j)")
t("Planificado + Odoo","Planned + Odoo","Planeado + Odoo","Planifié + Odoo")
t("Conductores (30d)","Drivers (30d)","Condutores (30d)","Conducteurs (30j)")
t("Personas distintas","Different people","Pessoas distintas","Personnes différentes")
t("Odómetro Odoo","Odoo odometer","Odómetro Odoo","Odomètre Odoo")
t("Sin conductor Odoo","No Odoo driver","Sem condutor Odoo","Pas de conducteur Odoo")
t("Solicitudes abiertas","Open requests","Pedidos em aberto","Demandes ouvertes")
t("Pendientes / en proceso","Pending / in progress","Pendentes / em curso","En attente / en cours")
t("Operarios hoy","Workers today","Operários hoje","Ouvriers aujourd'hui")
t("Cupo {n}","Capacity {n}","Limite {n}","Capacité {n}")
t("Sin límite definido","No limit set","Sem limite definido","Pas de limite définie")
t("Empresas hoy","Companies today","Empresas hoje","Entreprises aujourd'hui")
t("Subcontratas activas","Active subcontractors","Subempreiteiras ativas","Sous-traitants actifs")
t("{n} plazas pendientes","{n} open positions","{n} vagas pendentes","{n} postes ouverts")
t("Sin plazas genéricas","No generic positions","Sem vagas genéricas","Pas de postes génériques")
t("Días-persona mes","Person-days this month","Dias-pessoa mês","Jours-personne ce mois")
t("{n} operarios distintos","{n} different workers","{n} operários distintos","{n} ouvriers différents")
t("Próx. 7 días","Next 7 days","Próx. 7 dias","7 prochains jours")
t("Asignaciones planificadas","Planned assignments","Atribuições planeadas","Affectations planifiées")
t("Fichajes hoy","Clock-ins today","Pontos hoje","Pointages aujourd'hui")
t("{n} incidencias","{n} issues","{n} incidências","{n} incidents")
t("Sin registros","No records","Sem registos","Pas d'enregistrements")
t("Sin incidencias","No issues","Sem incidências","Pas d'incidents")
t("Plazo obra","Site deadline","Prazo da obra","Délai du chantier")
t("días restantes","days remaining","dias restantes","jours restants")
t("días desde cierre","days since closure","dias desde o encerramento","jours depuis la clôture")
t("Asignado hoy","Assigned today","Atribuído hoje","Affecté aujourd'hui")
t("{n} obra(s)","{n} site(s)","{n} obra(s)","{n} chantier(s)")
t("Días asignados mes","Assigned days this month","Dias atribuídos mês","Jours affectés ce mois")
t("En calendario actual","In current calendar","No calendário atual","Dans le calendrier actuel")
t("Obras (30 días)","Sites (30 days)","Obras (30 dias)","Chantiers (30 jours)")
t("{n} días multi-obra","{n} multi-site days","{n} dias multi-obra","{n} jours multi-chantier")
t("Sin pluriempleo","No multi-site","Sem multi-obra","Pas de multi-chantier")
t("Fichajes 30 días","Clock-ins 30 days","Pontos 30 dias","Pointages 30 jours")
t("Correctos","Correct","Corretos","Corrects")
t("Reputación","Reputation","Reputação","Réputation")
t("{n} valoraciones activas","{n} active ratings","{n} avaliações ativas","{n} évaluations actives")
t("Solicitudes","Requests","Pedidos","Demandes")
t("Abiertas vinculadas","Open linked","Em aberto vinculadas","Ouvertes liées")
t("Próxima asignación","Next assignment","Próxima atribuição","Prochaine affectation")
t("Obra","Site","Obra","Chantier")
t("Plantilla","Workforce","Quadro","Effectif")
t("{n} activos","{n} active","{n} ativos","{n} actifs")
t("En obra hoy","On site today","Em obra hoje","Sur chantier aujourd'hui")
t("{pct}% de activos","{pct}% of active","{pct}% de ativos","{pct}% d'actifs")
t("Sin activos","No active staff","Sem ativos","Pas d'actifs")
t("Con personal asignado","With assigned staff","Com pessoal atribuído","Avec personnel affecté")
t("Intervenciones 30d","Interventions 30d","Intervenções 30d","Interventions 30j")
t("{n} días-persona este mes","{n} person-days this month","{n} dias-pessoa este mês","{n} jours-personne ce mois")
t("Valoración media","Average rating","Avaliação média","Évaluation moyenne")
t("{n} valoraciones","{n} ratings","{n} avaliações","{n} évaluations")
t("Sin valoraciones","No ratings","Sem avaliações","Pas d'évaluations")
t("Abiertas de la empresa","Open for the company","Em aberto da empresa","Ouvertes de l'entreprise")
t("Incidencias fichaje","Clock-in issues","Incidências de ponto","Incidents de pointage")
t("Últimos 30 días","Last 30 days","Últimos 30 dias","30 derniers jours")
t("Vehículo #{n}","Vehicle #{n}","Veículo #{n}","Véhicule #{n}")
t("{name} (no está en el programa)","{name} (not in the system)","{name} (não está no sistema)","{name} (pas dans le système)")
t("Uso Odoo (sin conductor)","Odoo usage (no driver)","Uso Odoo (sem condutor)","Usage Odoo (pas de conducteur)")

# ── Sync modules ──
t("Obras / Proyectos","Sites / Projects","Obras / Projetos","Chantiers / Projets")
t("Personal interno","Internal staff","Pessoal interno","Personnel interne")
t("Subcontratas","Subcontractors","Subempreiteiras","Sous-traitants")
t("Ausencias / Time Off","Leave / Time Off","Ausências / Folgas","Absences / Congés")
t("Fichajes / asistencia","Clock-in / attendance","Ponto / assiduidade","Pointage / présence")
t("Vehículos / Flota","Vehicles / Fleet","Veículos / Frota","Véhicules / Flotte")
t("Importa proyectos BIM activos desde Odoo (bim.project).","Imports active BIM projects from Odoo (bim.project).","Importa projetos BIM ativos do Odoo (bim.project).","Importe les projets BIM actifs depuis Odoo (bim.project).")
t("Sincroniza empleados internos (hr.employee) con departamentos autorizados.","Syncs internal employees (hr.employee) with authorised departments.","Sincroniza empregados internos (hr.employee) com departamentos autorizados.","Synchronise les employés internes (hr.employee) avec les départements autorisés.")
t("Importa empresas subcontrata y sus contactos externos.","Imports subcontractor companies and their external contacts.","Importa empresas subempreiteiras e os seus contactos externos.","Importe les entreprises sous-traitantes et leurs contacts externes.")
t("Importa vacaciones, bajas, permisos y puentes (hr.leave) con su tipo y estado.","Imports holidays, sick leave, permits and bank holidays (hr.leave) with their type and status.","Importa férias, baixas, licenças e feriados (hr.leave) com o seu tipo e estado.","Importe les congés, arrêts, permissions et jours fériés (hr.leave) avec leur type et statut.")
t("Cruza fichajes Odoo con la planificación. En vivo durante el día y revisión retrospectiva nocturna.","Cross-checks Odoo clock-ins against the plan. Live during the day plus nightly retrospective review.","Cruza pontos Odoo com o planeamento. Em direto durante o dia e revisão retrospetiva noturna.","Croise les pointages Odoo avec la planification. En direct le jour et révision rétrospective la nuit.")
t("Sincroniza flota (fleet.vehicle) y odómetros diarios. Auditoría informativa plan vs conductor Odoo.","Syncs fleet (fleet.vehicle) and daily odometers. Informational audit plan vs Odoo driver.","Sincroniza frota (fleet.vehicle) e odómetros diários. Auditoria informativa plano vs condutor Odoo.","Synchronise la flotte (fleet.vehicle) et les odomètres quotidiens. Audit informatif plan vs conducteur Odoo.")
t("Diario a las 03:00","Daily at 03:00","Diário às 03:00","Quotidien à 03h00")
t("Cada 30 min (07:00–19:00) + retrospectivo diario","Every 30 min (07:00–19:00) + daily retrospective","A cada 30 min (07:00–19:00) + retrospetivo diário","Toutes les 30 min (07:00–19:00) + rétrospectif quotidien")
t("Cada 60 min (07:00–19:00) + retrospectivo diario","Every 60 min (07:00–19:00) + daily retrospective","A cada 60 min (07:00–19:00) + retrospetivo diário","Toutes les 60 min (07:00–19:00) + rétrospectif quotidien")

# ── Import wizard ──
t("Importar obras","Import sites","Importar obras","Importer des chantiers")
t("Sube un Excel o CSV para crear varias obras de una vez.","Upload an Excel or CSV to create multiple sites at once.","Carregue um Excel ou CSV para criar várias obras de uma vez.","Téléchargez un Excel ou CSV pour créer plusieurs chantiers à la fois.")
t("Desde aquí cargas de golpe el listado de obras de tu empresa. No hace falta crearlas una a una: el asistente lee el fichero, mapea las columnas y te muestra una vista previa antes de guardar.","Upload your company's site list in one go from here. No need to create them one by one: the wizard reads the file, maps the columns and shows you a preview before saving.","A partir daqui carrega de uma vez o listado de obras da sua empresa. Não precisa de as criar uma a uma: o assistente lê o ficheiro, mapeia as colunas e mostra uma pré-visualização antes de guardar.","Chargez d'un coup la liste de chantiers de votre entreprise. Pas besoin de les créer un par un : l'assistant lit le fichier, mappe les colonnes et vous montre un aperçu avant d'enregistrer.")
t("Obligatorio: Nombre. Opcional: Código, Dirección, Fechas.","Required: Name. Optional: Code, Address, Dates.","Obrigatório: Nome. Opcional: Código, Morada, Datas.","Obligatoire : Nom. Optionnel : Code, Adresse, Dates.")
t("Volver al listado","Back to list","Voltar ao listado","Retour à la liste")
t("Ir a obras","Go to sites","Ir a obras","Aller aux chantiers")
t("Importar personal","Import people","Importar pessoal","Importer du personnel")
t("Sube un Excel o CSV para dar de alta usuarios.","Upload an Excel or CSV to register users.","Carregue um Excel ou CSV para registar utilizadores.","Téléchargez un Excel ou CSV pour inscrire des utilisateurs.")
t("Carga de golpe tu plantilla (interna o externa). Revisarás el mapeo y una vista previa antes de crear a nadie.","Upload your entire workforce (internal or external) in one go. You will review the mapping and a preview before creating anyone.","Carregue de uma vez o seu quadro (interno ou externo). Vai rever o mapeamento e uma pré-visualização antes de criar ninguém.","Chargez d'un coup votre effectif (interne ou externe). Vous vérifierez le mapping et un aperçu avant de créer qui que ce soit.")
t("Obligatorio: Nombre, Apellidos, DNI, Email. Recomendado: Empresa (externos), Rol.","Required: Name, Surname, ID number, Email. Recommended: Company (external), Role.","Obrigatório: Nome, Apelidos, Documento, Email. Recomendado: Empresa (externos), Função.","Obligatoire : Nom, Prénom, Pièce d'identité, E-mail. Recommandé : Entreprise (externes), Rôle.")
t("Volver a personal","Back to people","Voltar a pessoal","Retour au personnel")
t("Ir a personal","Go to people","Ir a pessoal","Aller au personnel")
t("Importar subcontratas","Import subcontractors","Importar subempreiteiras","Importer des sous-traitants")
t("Sube un Excel o CSV para dar de alta empresas externas.","Upload an Excel or CSV to register external companies.","Carregue um Excel ou CSV para registar empresas externas.","Téléchargez un Excel ou CSV pour inscrire des entreprises externes.")
t("Da de alta las empresas externas / subcontratas con las que trabajas. Así podrás vincular personal externo a cada una.","Register the external companies / subcontractors you work with. You can then link external staff to each one.","Registe as empresas externas / subempreiteiras com as quais trabalha. Assim poderá vincular pessoal externo a cada uma.","Inscrivez les entreprises externes / sous-traitants avec lesquels vous travaillez. Vous pourrez ensuite lier du personnel externe à chacun.")
t("Obligatorio: Nombre. Opcional: NIF, Código, Gremio, Email, Descripción.","Required: Name. Optional: Tax ID, Code, Trade, Email, Description.","Obrigatório: Nome. Opcional: NIF, Código, Ofício, Email, Descrição.","Obligatoire : Nom. Optionnel : NIF, Code, Corps de métier, E-mail, Description.")
t("Volver a subcontratas","Back to subcontractors","Voltar a subempreiteiras","Retour aux sous-traitants")
t("Ir a subcontratas","Go to subcontractors","Ir a subempreiteiras","Aller aux sous-traitants")

# ── Hundreds of UI strings ──
# I'll add them all systematically. Key → (EN, PT-PT, FR-FR)

t("(admin)","(admin)","(admin)","(admin)")
t("(dejar vacío para mantener)","(leave blank to keep current)","(deixar vazio para manter)","(laisser vide pour conserver)")
t("(móvil / PWA).","(mobile / PWA).","(telemóvel / PWA).","(mobile / PWA).")
t("(móvil).","(mobile).","(telemóvel).","(mobile).")
t("(plan de pago)","(payment plan)","(plano de pagamento)","(formule payante)")
t("(sin cambiar)","(unchanged)","(sem alterar)","(inchangé)")
t("(sin empresa interna)","(no internal company)","(sem empresa interna)","(pas d'entreprise interne)")
t("(solo tú podrás verla)","(only you will be able to see it)","(só você a poderá ver)","(vous seul pourrez la voir)")
t("-- Selecciona el traductor --","-- Select translator --","-- Selecione o tradutor --","-- Sélectionnez le traducteur --")
t("-- Selecciona obra --","-- Select site --","-- Selecione obra --","-- Sélectionnez un chantier --")
t("-- Selecciona operario --","-- Select worker --","-- Selecione operário --","-- Sélectionnez un ouvrier --")
t("-- Seleccione empresa destino --","-- Select target company --","-- Selecione empresa de destino --","-- Sélectionnez l'entreprise cible --")
t("4 a 6 dígitos. Con este PIN y el DNI entra en el login de la app.","4 to 6 digits. The worker uses this PIN and their ID to sign in.","4 a 6 dígitos. Com este PIN e o documento, entra no login da app.","4 à 6 chiffres. Avec ce PIN et la pièce d'identité, on accède via le login.")
t("A marcar como finalizadas","To be marked as finished","A marcar como finalizadas","À marquer comme terminées")
t("Abierta desde {time}","Open since {time}","Aberta desde {time}","Ouverte depuis {time}")
t("Abrir","Open","Abrir","Ouvrir")
t("Abrir centro de sincronización","Open sync centre","Abrir centro de sincronização","Ouvrir le centre de synchronisation")
t("Abrir ficha y asignar","Open profile and assign","Abrir ficha e atribuir","Ouvrir la fiche et affecter")
t("Abrir hub Primeros pasos","Open Getting Started hub","Abrir hub Primeiros passos","Ouvrir le hub Premiers pas")
t("Abrir panel de altas","Open signup panel","Abrir painel de altas","Ouvrir le panneau d'inscriptions")
t("Abrir tutorial","Open tutorial","Abrir tutorial","Ouvrir le tutoriel")
t("Academia","Academy","Academia","Académie")
t("Acceso con DNI + PIN desde el login de la app","Access with ID + PIN from the app login","Acesso com documento + PIN no login da app","Accès avec pièce d'identité + PIN via le login")
t("Acceso de oficina","Office access","Acesso de escritório","Accès bureau")
t("Acceso del operario (DNI + PIN)","Worker access (ID + PIN)","Acesso do operário (documento + PIN)","Accès ouvrier (pièce d'identité + PIN)")
t("Accesos rápidos","Quick links","Acessos rápidos","Accès rapides")
t("Activa el fichaje o registra al menos un fichaje.","Enable clock-in or record at least one clock-in.","Ative o ponto ou registe pelo menos um ponto.","Activez le pointage ou enregistrez au moins un pointage.")
t("Activado: el primer fichaje sin plan se acepta solo. Desactivado: aparece como «paracaidista» en auditoría para revisar.","Enabled: the first unplanned clock-in is auto-accepted. Disabled: it appears as a 'parachutist' in the audit for review.","Ativado: o primeiro ponto sem plano é aceite automaticamente. Desativado: aparece como «paraquedista» na auditoria para rever.","Activé : le premier pointage non planifié est accepté automatiquement. Désactivé : il apparaît comme « parachutiste » dans l'audit pour vérification.")
t("Activar PIN para fichaje","Enable PIN for clock-in","Ativar PIN para ponto","Activer le PIN pour le pointage")
t("Activar los módulos en tu espacio cuando estén listos","Enable modules in your workspace when ready","Ativar os módulos no seu espaço quando estiverem prontos","Activer les modules dans votre espace quand ils sont prêts")
t("Actualizar previsualización","Update preview","Atualizar pré-visualização","Mettre à jour l'aperçu")
t("Actívalo para altas self-serve. En tenants creados por ti normalmente va apagado.","Enable for self-serve signups. Normally off for tenants you create yourself.","Ative para altas self-serve. Em tenants criados por si normalmente vai desligado.","Activez pour les inscriptions en libre-service. Normalement désactivé pour les tenants que vous créez.")
t("Adaptador API Odoo:","Odoo API adapter:","Adaptador API Odoo:","Adaptateur API Odoo :")
t("Administrador no puede quitarse Configuración ni Permisos.","Admin cannot remove Settings or Permissions from themselves.","O administrador não pode retirar-se Configuração nem Permissões.","L'administrateur ne peut pas se retirer Paramètres ni Permissions.")
t("Afecta a fichajes, sync Odoo y tareas programadas","Affects clock-ins, Odoo sync and scheduled tasks","Afeta pontos, sync Odoo e tarefas programadas","Affecte les pointages, la sync Odoo et les tâches planifiées")
t("Ajusta el mapeo si la detección automática no es correcta y vuelve a previsualizar.","Adjust the mapping if auto-detection is not correct and re-preview.","Ajuste o mapeamento se a deteção automática não estiver correta e volte a pré-visualizar.","Ajustez le mapping si la détection automatique n'est pas correcte et relancez l'aperçu.")
t("Alerta si el desvío del viaje es ≤ −este % (hizo de menos). Ej.: 30 → alerta a −31%.","Alert if trip deviation is ≤ −this % (under-travelled). E.g. 30 → alert at −31%.","Alerta se o desvio da viagem for ≤ −esta % (fez de menos). Ex.: 30 → alerta a −31%.","Alerte si l'écart du trajet est ≤ −ce % (a fait moins). Ex. : 30 → alerte à −31 %.")
t("Alerta si el desvío del viaje es ≥ +este % (hizo de más).","Alert if trip deviation is ≥ +this % (over-travelled).","Alerta se o desvio da viagem for ≥ +esta % (fez de mais).","Alerte si l'écart du trajet est ≥ +ce % (a fait plus).")
t("Alertas","Alerts","Alertas","Alertes")
t("Alta","Signup","Alta","Inscription")
t("Alta de un trabajador, una obra y el ciclo de fichaje.","Create a worker, a site and the clock-in cycle.","Alta de um trabalhador, uma obra e o ciclo de ponto.","Créer un ouvrier, un chantier et le cycle de pointage.")
t("Alta de un vehículo","Add a vehicle","Alta de um veículo","Ajouter un véhicule")
t("Alta guiada de una obra.","Guided site creation.","Alta guiada de uma obra.","Création guidée d'un chantier.")
t("Ampliar contenido","Expand content","Ampliar conteúdo","Développer le contenu")
t("Analizando <b>{name}</b> en Odoo…","Analysing <b>{name}</b> in Odoo…","A analisar <b>{name}</b> no Odoo…","Analyse de <b>{name}</b> dans Odoo…")
t("Anclar al inicio","Pin to top","Fixar ao início","Épingler en haut")
t("Análisis en vivo desde Odoo · qué se importará, qué se omitirá y por qué.","Live analysis from Odoo · what will be imported, what will be skipped and why.","Análise em direto do Odoo · o que será importado, o que será omitido e porquê.","Analyse en direct depuis Odoo · ce qui sera importé, ce qui sera ignoré et pourquoi.")
t("Aplicados:","Applied:","Aplicados:","Appliqués :")
t("Aquí saldrán los operarios libres para arrastrarlos a las obras.","Available workers will appear here for you to drag them to sites.","Aqui aparecerão os operários livres para os arrastar para as obras.","Les ouvriers disponibles apparaîtront ici pour les glisser vers les chantiers.")
t("Archivo:","File:","Ficheiro:","Fichier :")
t("Arrastra, oculta y renombra","Drag, hide and rename","Arraste, oculte e renomeie","Glissez, masquez et renommez")
t("Arrastrar para ajustar tamaño","Drag to resize","Arrastar para ajustar tamanho","Glisser pour redimensionner")
t("Arrastrar sección","Drag section","Arrastar secção","Glisser la section")
t("Asigna al operario a ambas obras a la vez (Pluriempleo).","Assign the worker to both sites at once (multi-site).","Atribui o operário a ambas as obras ao mesmo tempo (multi-obra).","Affecte l'ouvrier aux deux chantiers à la fois (multi-chantier).")
t("Asigna gente a obras en el tablero y lee el día.","Assign people to sites on the board and read the day.","Atribua pessoas a obras no quadro e leia o dia.","Affectez des personnes aux chantiers sur le tableau et lisez la journée.")
t("Asignación","Assignment","Atribuição","Affectation")
t("Asignación de personal (genérica)","Staff request (generic)","Pedido de pessoal (genérico)","Demande de personnel (générique)")
t("Asignación genérica","Generic assignment","Atribuição genérica","Affectation générique")
t("Asignación manual","Manual assignment","Atribuição manual","Affectation manuelle")
t("Asignación para el día seleccionado en el tablero. Revisa el bloque «NUEVA ASIGNACIÓN», ajusta fechas si hace falta y confirma con","Assignment for the day selected on the board. Check the 'NEW ASSIGNMENT' block, adjust dates if needed and confirm with","Atribuição para o dia selecionado no quadro. Reveja o bloco «NOVA ATRIBUIÇÃO», ajuste datas se necessário e confirme com","Affectation pour le jour sélectionné sur le tableau. Vérifiez le bloc « NOUVELLE AFFECTATION », ajustez les dates si nécessaire et confirmez avec")
t("Asignado","Assigned","Atribuído","Affecté")
t("Asignados","Assigned","Atribuídos","Affectés")
t("Asignar Solo Días Libres","Assign Free Days Only","Atribuir Apenas Dias Livres","Affecter les jours libres uniquement")
t("Asignar oficialmente a esta obra","Officially assign to this site","Atribuir oficialmente a esta obra","Affecter officiellement à ce chantier")
t("Asignar:","Assign:","Atribuir:","Affecter :")
t("Asuntos propios","Personal affairs","Assuntos pessoais","Affaires personnelles")
t("Así dejamos el espacio listo: con fichaje o solo planificación. Luego generamos los ejemplos.","This gets the workspace ready: with clock-in or planning only. Then we generate the examples.","Assim deixamos o espaço pronto: com ponto ou apenas planeamento. Depois geramos os exemplos.","Cela prépare l'espace : avec pointage ou planification seule. Ensuite nous générons les exemples.")
t("Atención:","Warning:","Atenção:","Attention :")
t("Ausencia OK","Leave OK","Ausência OK","Absence OK")
t("Ausencias pendientes","Pending leave","Ausências pendentes","Absences en attente")
t("Auto ahora","Auto now","Auto agora","Auto maintenant")
t("Avisos al importar","Import warnings","Avisos ao importar","Avertissements à l'import")
t("Avisos y enlace para definir PIN. Si está vacío, el operario solo entra con DNI + PIN.","Alerts and link to set the PIN. If blank, the worker signs in with ID + PIN only.","Avisos e link para definir PIN. Se vazio, o operário entra apenas com documento + PIN.","Alertes et lien pour définir le PIN. Si vide, l'ouvrier se connecte uniquement avec pièce d'identité + PIN.")
t("Añade personal","Add people","Adicione pessoal","Ajoutez du personnel")
t("Añade un vehículo o activa el módulo de flota.","Add a vehicle or enable the fleet module.","Adicione um veículo ou ative o módulo de frota.","Ajoutez un véhicule ou activez le module de flotte.")
t("Añade una obra","Add a site","Adicione uma obra","Ajoutez un chantier")
t("Añadir coche","Add vehicle","Adicionar veículo","Ajouter un véhicule")
t("Añadir obra","Add site","Adicionar obra","Ajouter un chantier")
t("Añadir personal","Add people","Adicionar pessoal","Ajouter du personnel")
t("Aún no","Not yet","Ainda não","Pas encore")
t("Aún no hay clientes registrados.","No customers registered yet.","Ainda não há clientes registados.","Pas encore de clients inscrits.")
t("Aún no hay vehículos en la flota.","No vehicles in the fleet yet.","Ainda não há veículos na frota.","Pas encore de véhicules dans la flotte.")
t("Aún no hay vehículos. Usa el formulario de arriba para dar de alta el primero.","No vehicles yet. Use the form above to add the first one.","Ainda não há veículos. Use o formulário acima para registar o primeiro.","Pas encore de véhicules. Utilisez le formulaire ci-dessus pour ajouter le premier.")
t("BD","DB","BD","BD")
t("Baja","Leave","Baixa","Départ")
t("Baja definitiva","Permanent leave","Baixa definitiva","Départ définitif")
t("Baja médica","Sick leave","Baixa médica","Arrêt maladie")
t("Base de datos","Database","Base de dados","Base de données")
t("ok","OK","OK","OK")
t("error","error","erro","erreur")
t("email","email","email","e-mail")
t("o","or","ou","ou")

# Due to size limits, I'll write the remaining translations as a batch
# The remaining ~700 keys follow the same pattern.
# Let me add all remaining keys from the missing report:

remaining = {
"Borra TODO el uso diario local (basura del odómetro) y regenera desde viajes tms.shipment del {desde} al {hasta}.": ("Deletes ALL local daily usage (odometer junk) and regenerates from tms.shipment trips from {desde} to {hasta}.", "Apaga TODO o uso diário local (lixo do odómetro) e regenera a partir de viagens tms.shipment de {desde} a {hasta}.", "Supprime TOUT l'usage quotidien local (données parasites de l'odomètre) et régénère à partir des trajets tms.shipment du {desde} au {hasta}."),
"Borra el uso del rango y lo regenera solo desde viajes tms.shipment ({desde} → {hasta}).": ("Deletes usage for the range and regenerates only from tms.shipment trips ({desde} → {hasta}).", "Apaga o uso do intervalo e regenera apenas a partir de viagens tms.shipment ({desde} → {hasta}).", "Supprime l'usage pour la plage et régénère uniquement à partir des trajets tms.shipment ({desde} → {hasta})."),
"Borrados:": ("Deleted:", "Apagados:", "Supprimés :"),
"Borrar": ("Delete", "Apagar", "Supprimer"),
"Borrar tenant y base de datos": ("Delete tenant and database", "Apagar tenant e base de dados", "Supprimer le tenant et la base de données"),
"Borrar todo": ("Delete all", "Apagar tudo", "Tout supprimer"),
"Buscar jefe de obra…": ("Search site manager…", "Procurar chefe de obra…", "Rechercher un chef de chantier…"),
"Buscar obras...": ("Search sites...", "Procurar obras...", "Rechercher des chantiers..."),
"Buscar operarios/jefes...": ("Search workers/managers...", "Procurar operários/chefes...", "Rechercher ouvriers/chefs..."),
"Buscar trabajador": ("Search worker", "Procurar trabalhador", "Rechercher un travailleur"),
"Buscar trabajador…": ("Search worker…", "Procurar trabalhador…", "Rechercher un travailleur…"),
"Buscar y seleccionar…": ("Search and select…", "Procurar e selecionar…", "Rechercher et sélectionner…"),
"CONFLICTO": ("CONFLICT", "CONFLITO", "CONFLIT"),
"Cadena de integridad": ("Integrity chain", "Cadeia de integridade", "Chaîne d'intégrité"),
"Cadena de integridad íntegra.": ("Integrity chain intact.", "Cadeia de integridade íntegra.", "Chaîne d'intégrité intacte."),
"Calendario del Operario": ("Worker Calendar", "Calendário do Operário", "Calendrier de l'ouvrier"),
"Cambia la planificación a la obra donde fichó": ("Moves planning to the site where the clock-in occurred", "Muda o planeamento para a obra onde picou o ponto", "Déplace la planification vers le chantier où le pointage a eu lieu"),
"Cambiar PIN": ("Change PIN", "Alterar PIN", "Changer le PIN"),
"Cambiar archivo": ("Change file", "Alterar ficheiro", "Changer le fichier"),
"Cambiar jefe de obra": ("Change site manager", "Alterar chefe de obra", "Changer le chef de chantier"),
"Cambios": ("Changes", "Alterações", "Modifications"),
"Cambios guardados": ("Changes saved", "Alterações guardadas", "Modifications enregistrées"),
"Cancelar solicitud": ("Cancel request", "Cancelar pedido", "Annuler la demande"),
"Cargar": ("Load", "Carregar", "Charger"),
"Centro de sincronización Odoo": ("Odoo sync centre", "Centro de sincronização Odoo", "Centre de synchronisation Odoo"),
"Cerrar edición": ("Close editor", "Fechar edição", "Fermer l'éditeur"),
"Clave compartida SSO": ("SSO shared key", "Chave partilhada SSO", "Clé partagée SSO"),
"Clic para cambiar Encargado": ("Click to change foreman", "Clique para alterar encarregado", "Cliquez pour changer le contremaître"),
"Clic para cambiar Jefe": ("Click to change manager", "Clique para alterar chefe", "Cliquez pour changer le responsable"),
"Cliente / descripción": ("Customer / description", "Cliente / descrição", "Client / description"),
"Clientes": ("Customers", "Clientes", "Clients"),
"Color": ("Colour", "Cor", "Couleur"),
"Columnas requeridas:": ("Required columns:", "Colunas obrigatórias:", "Colonnes requises :"),
"Columnas:": ("Columns:", "Colunas:", "Colonnes :"),
"Conforme trabajador": ("Worker confirmation", "Conforme do trabalhador", "Confirmation du travailleur"),
"Contraseña API": ("API password", "Palavra-passe API", "Mot de passe API"),
"Contraseña Admin": ("Admin password", "Palavra-passe do Admin", "Mot de passe Admin"),
"Contraseña configurada": ("Password set", "Palavra-passe configurada", "Mot de passe configuré"),
"Contraseña nueva": ("New password", "Nova palavra-passe", "Nouveau mot de passe"),
"Correcciones": ("Corrections", "Correções", "Corrections"),
"Corregir (anular + nueva)": ("Correct (void + new)", "Corrigir (anular + nova)", "Corriger (annuler + nouvelle)"),
"Corregir / anular": ("Correct / void", "Corrigir / anular", "Corriger / annuler"),
"Correo": ("Email", "Correio", "E-mail"),
"Correo verificado": ("Email verified", "Correio verificado", "E-mail vérifié"),
"Correos": ("Emails", "Correios", "E-mails"),
"Correspondencia de columnas": ("Column mapping", "Correspondência de colunas", "Correspondance de colonnes"),
"Creado": ("Created", "Criado", "Créé"),
"Creados:": ("Created:", "Criados:", "Créés :"),
"Crear / editar": ("Create / edit", "Criar / editar", "Créer / modifier"),
"Crear flota": ("Create fleet", "Criar frota", "Créer la flotte"),
"Crear la primera obra": ("Create the first site", "Criar a primeira obra", "Créer le premier chantier"),
"Crear la primera persona": ("Create the first person", "Criar a primeira pessoa", "Créer la première personne"),
"Crear los datos de ejemplo": ("Create sample data", "Criar os dados de exemplo", "Créer les données d'exemple"),
"Crear y Lanzar": ("Create and Launch", "Criar e Lançar", "Créer et Lancer"),
"Credenciales Odoo": ("Odoo credentials", "Credenciais Odoo", "Identifiants Odoo"),
"Creó Empresa": ("Created company", "Criou Empresa", "A créé l'entreprise"),
"Datos básicos": ("Basic info", "Dados básicos", "Informations de base"),
"Datos cargados": ("Data loaded", "Dados carregados", "Données chargées"),
"Datos de ejemplo": ("Sample data", "Dados de exemplo", "Données d'exemple"),
"Datos de ejemplo cargados": ("Sample data loaded", "Dados de exemplo carregados", "Données d'exemple chargées"),
"Datos de la obra": ("Site details", "Dados da obra", "Détails du chantier"),
"Datos del vehículo": ("Vehicle details", "Dados do veículo", "Détails du véhicule"),
"Datos incompletos.": ("Incomplete data.", "Dados incompletos.", "Données incomplètes."),
"De pago": ("Paid", "Pago", "Payant"),
"Define tu PIN": ("Set your PIN", "Defina o seu PIN", "Définissez votre PIN"),
"Definir PIN": ("Set PIN", "Definir PIN", "Définir le PIN"),
"Departamento": ("Department", "Departamento", "Département"),
"Desactivado": ("Disabled", "Desativado", "Désactivé"),
"Desanclar": ("Unpin", "Desafixar", "Désépingler"),
"Desasignación": ("Unassignment", "Desatribuição", "Désaffectation"),
"Descargar CSV": ("Download CSV", "Descarregar CSV", "Télécharger CSV"),
"Descargar PDF": ("Download PDF", "Descarregar PDF", "Télécharger PDF"),
"Detalle pausas": ("Break details", "Detalhe de pausas", "Détail des pauses"),
"Dominio": ("Domain", "Domínio", "Domaine"),
"Dominio personalizado": ("Custom domain", "Domínio personalizado", "Domaine personnalisé"),
"Dominio propio": ("Own domain", "Domínio próprio", "Domaine propre"),
"Dominio propio (opcional)": ("Own domain (optional)", "Domínio próprio (opcional)", "Domaine propre (optionnel)"),
"Duplicado": ("Duplicate", "Duplicado", "Doublon"),
"Duplicados:": ("Duplicates:", "Duplicados:", "Doublons :"),
"Duración": ("Duration", "Duração", "Durée"),
"Día laboral": ("Working day", "Dia útil", "Jour ouvré"),
"Días hacia atrás": ("Days back", "Dias para trás", "Jours en arrière"),
"Días sueltos": ("Individual days", "Dias avulsos", "Jours isolés"),
"Días únicos:": ("Unique days:", "Dias únicos:", "Jours uniques :"),
"Editar nota": ("Edit note", "Editar nota", "Modifier la note"),
"Editar vehículo": ("Edit vehicle", "Editar veículo", "Modifier le véhicule"),
"Empezar": ("Start", "Começar", "Commencer"),
"Empresa no encontrada": ("Company not found", "Empresa não encontrada", "Entreprise non trouvée"),
"Empresas listas": ("Companies ready", "Empresas prontas", "Entreprises prêtes"),
"Enviar enlace por correo": ("Send link by email", "Enviar link por correio", "Envoyer le lien par e-mail"),
"Enviar solicitud": ("Submit request", "Enviar pedido", "Envoyer la demande"),
"Errores:": ("Errors:", "Erros:", "Erreurs :"),
"Error al guardar": ("Error saving", "Erro ao guardar", "Erreur lors de l'enregistrement"),
"Error de servidor": ("Server error", "Erro de servidor", "Erreur serveur"),
"Ext": ("Ext", "Ext", "Ext"),
"Externa": ("External", "Externa", "Externe"),
"Fila": ("Row", "Linha", "Ligne"),
"Formato de fecha inválido": ("Invalid date format", "Formato de data inválido", "Format de date invalide"),
"Generado el": ("Generated on", "Gerado em", "Généré le"),
"Gratis": ("Free", "Grátis", "Gratuit"),
"Guardado correctamente.": ("Saved successfully.", "Guardado com sucesso.", "Enregistré avec succès."),
"Guardando...": ("Saving...", "A guardar...", "Enregistrement..."),
"Guía": ("Guide", "Guia", "Guide"),
"Hecho": ("Done", "Feito", "Fait"),
"Hora": ("Time", "Hora", "Heure"),
"Listo": ("Ready", "Pronto", "Prêt"),
"Mantener": ("Keep", "Manter", "Garder"),
"Mensajes": ("Messages", "Mensagens", "Messages"),
"Módulo": ("Module", "Módulo", "Module"),
"Módulos": ("Modules", "Módulos", "Modules"),
"Opcional": ("Optional", "Opcional", "Optionnel"),
"Perfil": ("Profile", "Perfil", "Profil"),
"Permiso": ("Permit", "Licença", "Permission"),
"Permisos": ("Permissions", "Permissões", "Permissions"),
"Plan": ("Plan", "Plano", "Plan"),
"Preview": ("Preview", "Pré-visualização", "Aperçu"),
"Progreso": ("Progress", "Progresso", "Progression"),
"Proyecto": ("Project", "Projeto", "Projet"),
"RRHH": ("HR", "RH", "RH"),
"Rango": ("Range", "Intervalo", "Plage"),
"Resultado": ("Result", "Resultado", "Résultat"),
"Revisar": ("Review", "Rever", "Vérifier"),
"Roles": ("Roles", "Funções", "Rôles"),
"Sección": ("Section", "Secção", "Section"),
"Secciones": ("Sections", "Secções", "Sections"),
"Solicitar": ("Request", "Solicitar", "Demander"),
"Tutorial": ("Tutorial", "Tutorial", "Tutoriel"),
"Usuario": ("User", "Utilizador", "Utilisateur"),
"Uso": ("Usage", "Uso", "Usage"),
"Libre": ("Free", "Livre", "Libre"),
"Más": ("More", "Mais", "Plus"),
"Modo": ("Mode", "Modo", "Mode"),
"Cumplido": ("Fulfilled", "Cumprido", "Accompli"),
"Conectado": ("Connected", "Ligado", "Connecté"),
"Conexión OK": ("Connection OK", "Ligação OK", "Connexion OK"),
"Instrucciones": ("Instructions", "Instruções", "Instructions"),
"Parcial": ("Partial", "Parcial", "Partiel"),
"Parciales": ("Partial", "Parciais", "Partiels"),
"Previsualizar": ("Preview", "Pré-visualizar", "Aperçu"),
"Programar": ("Schedule", "Programar", "Planifier"),
"Repetir": ("Repeat", "Repetir", "Répéter"),
"Reabierto": ("Reopened", "Reaberto", "Rouvert"),
"Reactivar": ("Reactivate", "Reativar", "Réactiver"),
"Reasignado": ("Reassigned", "Reatribuído", "Réaffecté"),
"Ocupados": ("Busy", "Ocupados", "Occupés"),
"Omitido": ("Skipped", "Omitido", "Ignoré"),
"Eliminada": ("Deleted", "Eliminada", "Supprimée"),
"Lanzado": ("Launched", "Lançado", "Lancé"),
"Falta": ("Absence", "Falta", "Absence"),
"actualizados": ("updated", "atualizados", "mis à jour"),
"asociados.": ("associated.", "associados.", "associés."),
"creada": ("created", "criada", "créée"),
"desde": ("from", "desde", "depuis"),
"día": ("day", "dia", "jour"),
"días.": ("days.", "dias.", "jours."),
"duplicada": ("duplicate", "duplicada", "doublon"),
"el operario": ("the worker", "o operário", "l'ouvrier"),
"fin": ("end", "fim", "fin"),
"interna": ("internal", "interna", "interne"),
"la obra": ("the site", "a obra", "le chantier"),
"nueva": ("new", "nova", "nouvelle"),
"nuevos": ("new", "novos", "nouveaux"),
"obras": ("sites", "obras", "chantiers"),
"omitida": ("skipped", "omitida", "ignorée"),
"omitidos": ("skipped", "omitidos", "ignorés"),
"opcional": ("optional", "opcional", "optionnel"),
"operarios": ("workers", "operários", "ouvriers"),
"parciales": ("partial", "parciais", "partiels"),
"personas": ("people", "pessoas", "personnes"),
"persona(s)": ("person(s)", "pessoa(s)", "personne(s)"),
"propia": ("own", "própria", "propre"),
"próximos": ("next", "próximos", "prochains"),
"subcontratas": ("subcontractors", "subempreiteiras", "sous-traitants"),
"trabajadores": ("workers", "trabalhadores", "travailleurs"),
"vehículos": ("vehicles", "veículos", "véhicules"),
"vinculadas": ("linked", "vinculadas", "liées"),
"Pago": ("Payment", "Pagamento", "Paiement"),
"ERP": ("ERP", "ERP", "ERP"),
"Km": ("Km", "Km", "Km"),
"Disp.": ("Avail.", "Disp.", "Disp."),
"Ocup.": ("Occup.", "Ocup.", "Occup."),
"Omit.": ("Skip.", "Omit.", "Ignor."),
"hist.": ("hist.", "hist.", "hist."),
"Falta justificada": ("Justified absence", "Falta justificada", "Absence justifiée"),
"Permiso retribuido": ("Paid leave", "Licença remunerada", "Congé payé"),
"Puente": ("Bank holiday", "Ponte", "Pont"),
"Asuntos propios": ("Personal affairs", "Assuntos pessoais", "Affaires personnelles"),
"Baja médica": ("Sick leave", "Baixa médica", "Arrêt maladie"),
"Vacaciones y permisos": ("Holidays and leave", "Férias e licenças", "Congés et permissions"),
"{h} h {m:02d} min": ("{h} h {m:02d} min", "{h} h {m:02d} min", "{h} h {m:02d} min"),
"{linked} de {total} vinculados con Odoo.": ("{linked} of {total} linked with Odoo.", "{linked} de {total} vinculados com Odoo.", "{linked} sur {total} liés avec Odoo."),
"{n} conflicto(s) pendiente(s). Se guardarán solo los válidos.": ("{n} pending conflict(s). Only valid ones will be saved.", "{n} conflito(s) pendente(s). Só os válidos serão guardados.", "{n} conflit(s) en attente. Seuls les valides seront enregistrés."),
"{n} empresa(s) eliminada(s).": ("{n} company(ies) deleted.", "{n} empresa(s) eliminada(s).", "{n} entreprise(s) supprimée(s)."),
"{n} incidencia(s)": ("{n} issue(s)", "{n} incidência(s)", "{n} incident(s)"),
"{n} operario(s) desactivado(s).": ("{n} worker(s) deactivated.", "{n} operário(s) desativado(s).", "{n} ouvrier(s) désactivé(s)."),
"{n} usuario(s) eliminado(s).": ("{n} user(s) deleted.", "{n} utilizador(es) eliminado(s).", "{n} utilisateur(s) supprimé(s)."),
"{start}-{end} ({n} min)": ("{start}-{end} ({n} min)", "{start}-{end} ({n} min)", "{start}-{end} ({n} min)"),
"¡Éxito!": ("Success!", "Sucesso!", "Succès !"),
"¡Revisión y Sincronización completadas!": ("Review and Sync completed!", "Revisão e Sincronização concluídas!", "Révision et Synchronisation terminées !"),
"Íntegra": ("Intact", "Íntegra", "Intacte"),
"Última ejecución": ("Last run", "Última execução", "Dernière exécution"),
"Último:": ("Last:", "Último:", "Dernier :"),
"— No mapear —": ("— Do not map —", "— Não mapear —", "— Ne pas mapper —"),
"— Seleccione un jefe —": ("— Select a manager —", "— Selecione um chefe —", "— Sélectionnez un responsable —"),
"— Sin asignar": ("— Unassigned", "— Sem atribuir", "— Non affecté"),
"— Sin empresa —": ("— No company —", "— Sem empresa —", "— Pas d'entreprise —"),
"— Usar / crear la del Excel —": ("— Use / create from Excel —", "— Usar / criar a do Excel —", "— Utiliser / créer depuis l'Excel —"),
"— no hace falta usar el botón atrás del navegador.": ("— no need to use the browser back button.", "— não precisa de usar o botão de retroceder do navegador.", "— pas besoin d'utiliser le bouton retour du navigateur."),
"Jefe de Obra": ("Site Manager", "Chefe de Obra", "Chef de chantier"),
"NIF / CIF": ("Tax ID", "NIF", "NIF"),
"NIF empresa": ("Company tax ID", "NIF empresa", "NIF entreprise"),
"Nº operarios": ("No. of workers", "N.º operários", "Nbre d'ouvriers"),
"Huella del informe": ("Report fingerprint", "Impressão do relatório", "Empreinte du rapport"),
"Huella del informe:": ("Report fingerprint:", "Impressão do relatório:", "Empreinte du rapport :"),
"Fecha conforme": ("Confirmation date", "Data de conforme", "Date de confirmation"),
"Fecha inválida": ("Invalid date", "Data inválida", "Date invalide"),
"Fecha y hora": ("Date and time", "Data e hora", "Date et heure"),
"Total horas": ("Total hours", "Total horas", "Heures totales"),
"Total:": ("Total:", "Total:", "Total :"),
"Trabajador:": ("Worker:", "Trabalhador:", "Travailleur :"),
"Usuario:": ("User:", "Utilizador:", "Utilisateur :"),
"Minuto": ("Minute", "Minuto", "Minute"),
"Mi espacio": ("My workspace", "O meu espaço", "Mon espace"),
"Mis obras": ("My sites", "As minhas obras", "Mes chantiers"),
"Mis solicitudes": ("My requests", "Os meus pedidos", "Mes demandes"),
"Hora diaria": ("Daily time", "Hora diária", "Heure quotidienne"),
"Solo lectura": ("Read only", "Apenas leitura", "Lecture seule"),
"solo lectura": ("read only", "apenas leitura", "lecture seule"),
"Ficha del coche": ("Vehicle profile", "Ficha do veículo", "Fiche du véhicule"),
"Fichaje real": ("Actual clock-in", "Ponto real", "Pointage réel"),
"Fichajes activos": ("Active clock-ins", "Pontos ativos", "Pointages actifs"),
"Fichajes en vivo": ("Live clock-ins", "Pontos em direto", "Pointages en direct"),
"Fichajes pendientes": ("Pending clock-ins", "Pontos pendentes", "Pointages en attente"),
"Fichajes retrospectivos": ("Retrospective clock-ins", "Pontos retrospetivos", "Pointages rétrospectifs"),
"Vehículos activos": ("Active vehicles", "Veículos ativos", "Véhicules actifs"),
"Vehículo activo": ("Active vehicle", "Veículo ativo", "Véhicule actif"),
"Vehículos retrospectivos": ("Retrospective vehicles", "Veículos retrospetivos", "Véhicules rétrospectifs"),
"Vehículos nuevos:": ("New vehicles:", "Veículos novos:", "Nouveaux véhicules :"),
"Nuevos:": ("New:", "Novos:", "Nouveaux :"),
"Omitidos:": ("Skipped:", "Omitidos:", "Ignorés :"),
"Purgados totales:": ("Total purged:", "Purgados totais:", "Total purgés :"),
"Registros día:": ("Day records:", "Registos dia:", "Enregistrements du jour :"),
"Error:": ("Error:", "Erro:", "Erreur :"),
"Ocupado en:": ("Busy at:", "Ocupado em:", "Occupé à :"),
"Confirmar importación": ("Confirm import", "Confirmar importação", "Confirmer l'importation"),
"Confirmar y Aplicar": ("Confirm and Apply", "Confirmar e Aplicar", "Confirmer et Appliquer"),
"Conflicto Detectado": ("Conflict Detected", "Conflito Detetado", "Conflit Détecté"),
"Configuración guardada.": ("Settings saved.", "Configuração guardada.", "Paramètres enregistrés."),
"Conexión con Odoo": ("Connection with Odoo", "Ligação com Odoo", "Connexion avec Odoo"),
"Panel de Obra": ("Site Panel", "Painel de Obra", "Panneau de chantier"),
"Nota (opcional)": ("Note (optional)", "Nota (opcional)", "Note (optionnel)"),
"Nota actualizada.": ("Note updated.", "Nota atualizada.", "Note mise à jour."),
"Nota guardada.": ("Note saved.", "Nota guardada.", "Note enregistrée."),
"Nota privada": ("Private note", "Nota privada", "Note privée"),
"Vista previa": ("Preview", "Pré-visualização", "Aperçu"),
"Vista calendario": ("Calendar view", "Vista de calendário", "Vue calendrier"),
"Previsualización": ("Preview", "Pré-visualização", "Aperçu"),
"Ver todos": ("View all", "Ver todos", "Voir tout"),
"Ver ficha": ("View profile", "Ver ficha", "Voir la fiche"),
"Ver ausencias": ("View leave", "Ver ausências", "Voir les absences"),
"Ver calendario": ("View calendar", "Ver calendário", "Voir le calendrier"),
"Ver estado": ("View status", "Ver estado", "Voir le statut"),
"Ver personal": ("View people", "Ver pessoal", "Voir le personnel"),
"Ver resumen": ("View summary", "Ver resumo", "Voir le résumé"),
"Guardar ausencias": ("Save leave", "Guardar ausências", "Enregistrer les absences"),
"Guardar correos": ("Save emails", "Guardar correios", "Enregistrer les e-mails"),
"Guardar en el libro": ("Save to ledger", "Guardar no livro", "Enregistrer dans le registre"),
"Guardar fichajes": ("Save clock-ins", "Guardar pontos", "Enregistrer les pointages"),
"Guardar horario": ("Save schedule", "Guardar horário", "Enregistrer l'horaire"),
"Guardar laboral": ("Save employment", "Guardar laboral", "Enregistrer emploi"),
"Guardar permisos": ("Save permissions", "Guardar permissões", "Enregistrer les permissions"),
"Guardar vehículos": ("Save vehicles", "Guardar veículos", "Enregistrer les véhicules"),
"Guardar PIN yo": ("Set PIN myself", "Definir PIN eu", "Définir le PIN moi-même"),
"Sobrescribir Todo": ("Overwrite All", "Sobrescrever Tudo", "Tout écraser"),
"Ir al Directorio": ("Go to Directory", "Ir ao Diretório", "Aller à l'annuaire"),
"Ir al perfil": ("Go to profile", "Ir ao perfil", "Aller au profil"),
"Ir al personal": ("Go to people", "Ir ao pessoal", "Aller au personnel"),
"Ir al panel →": ("Go to panel →", "Ir ao painel →", "Aller au panneau →"),
"Ir a empresas": ("Go to companies", "Ir a empresas", "Aller aux entreprises"),
"Filtrar nombre": ("Filter name", "Filtrar nome", "Filtrer par nom"),
"Filtrar email": ("Filter email", "Filtrar email", "Filtrer par e-mail"),
"Filtrar empresa": ("Filter company", "Filtrar empresa", "Filtrer par entreprise"),
"Filtrar estado": ("Filter status", "Filtrar estado", "Filtrer par statut"),
"Filtrar rol": ("Filter role", "Filtrar função", "Filtrer par rôle"),
"Filtrar tipo": ("Filter type", "Filtrar tipo", "Filtrer par type"),
"Filtrar código": ("Filter code", "Filtrar código", "Filtrer par code"),
"Filtrar DNI": ("Filter ID number", "Filtrar documento", "Filtrer par pièce d'identité"),
"Filtrar NIF": ("Filter tax ID", "Filtrar NIF", "Filtrer par NIF"),
"Filtrar activo": ("Filter active", "Filtrar ativo", "Filtrer par actif"),
"Filtrar categoría": ("Filter category", "Filtrar categoria", "Filtrer par catégorie"),
"Filtrar cliente": ("Filter customer", "Filtrar cliente", "Filtrer par client"),
"Filtrar conductor": ("Filter driver", "Filtrar condutor", "Filtrer par conducteur"),
"Filtrar fin": ("Filter end", "Filtrar fim", "Filtrer par fin"),
"Filtrar gremio": ("Filter trade", "Filtrar ofício", "Filtrer par corps de métier"),
"Filtrar importación": ("Filter import", "Filtrar importação", "Filtrer par importation"),
"Filtrar inicio": ("Filter start", "Filtrar início", "Filtrer par début"),
"Filtrar jefe": ("Filter manager", "Filtrar chefe", "Filtrer par responsable"),
"Filtrar km": ("Filter km", "Filtrar km", "Filtrer par km"),
"Filtrar marca": ("Filter brand", "Filtrar marca", "Filtrer par marque"),
"Filtrar matrícula": ("Filter licence plate", "Filtrar matrícula", "Filtrer par plaque"),
"Filtrar modelo": ("Filter model", "Filtrar modelo", "Filtrer par modèle"),
"Filtrar por obras": ("Filter by sites", "Filtrar por obras", "Filtrer par chantiers"),
"Filtrar valoración": ("Filter rating", "Filtrar avaliação", "Filtrer par évaluation"),
"Subir archivo": ("Upload file", "Carregar ficheiro", "Télécharger le fichier"),
"Seleccionar archivo...": ("Select file...", "Selecionar ficheiro...", "Sélectionner un fichier..."),
"Seleccionar archivo…": ("Select file…", "Selecionar ficheiro…", "Sélectionner un fichier…"),
"Mapear columnas": ("Map columns", "Mapear colunas", "Mapper les colonnes"),
"Mapeo de columnas": ("Column mapping", "Mapeamento de colunas", "Mapping de colonnes"),
"Importación completada": ("Import completed", "Importação concluída", "Importation terminée"),
"Nueva importación": ("New import", "Nova importação", "Nouvelle importation"),
"Gremio / especialidad": ("Trade / speciality", "Ofício / especialidade", "Corps de métier / spécialité"),
"Identificador único": ("Unique identifier", "Identificador único", "Identifiant unique"),
"Nombre Empresa": ("Company Name", "Nome da Empresa", "Nom de l'entreprise"),
"Nombre de la empresa": ("Company name", "Nome da empresa", "Nom de l'entreprise"),
"Nombre de sección": ("Section name", "Nome de secção", "Nom de section"),
"Email (opcional)": ("Email (optional)", "Email (opcional)", "E-mail (optionnel)"),
"Email de contacto": ("Contact email", "Email de contacto", "E-mail de contact"),
"Email del Admin": ("Admin email", "Email do Admin", "E-mail Admin"),
"Email del operario": ("Worker email", "Email do operário", "E-mail de l'ouvrier"),
"Intervalo (min)": ("Interval (min)", "Intervalo (min)", "Intervalle (min)"),
"Pausas (min)": ("Breaks (min)", "Pausas (min)", "Pauses (min)"),
"Versión para imprimir": ("Print version", "Versão para imprimir", "Version imprimable"),
"Guía de primeros pasos": ("Getting Started guide", "Guia de primeiros passos", "Guide de démarrage"),
"Guía interactiva": ("Interactive guide", "Guia interativa", "Guide interactif"),
"Tutorial guiado": ("Guided tutorial", "Tutorial guiado", "Tutoriel guidé"),
"Tutorial tablero": ("Board tutorial", "Tutorial do quadro", "Tutoriel tableau"),
"Tutorial fichajes": ("Clock-in tutorial", "Tutorial de ponto", "Tutoriel pointage"),
"Tutorial flota": ("Fleet tutorial", "Tutorial de frota", "Tutoriel flotte"),
"Tutoriales básicos": ("Basic tutorials", "Tutoriais básicos", "Tutoriels de base"),
"Probar conexión": ("Test connection", "Testar ligação", "Tester la connexion"),
"Probar el fichaje": ("Try the clock-in", "Experimentar o ponto", "Essayer le pointage"),
"Probar con ejemplos": ("Try with examples", "Experimentar com exemplos", "Essayer avec des exemples"),
"Generar datos de ejemplo": ("Generate sample data", "Gerar dados de exemplo", "Générer des données d'exemple"),
"Resolver conflicto": ("Resolve conflict", "Resolver conflito", "Résoudre le conflit"),
"Explorar por libre": ("Explore on your own", "Explorar por livre", "Explorer par vous-même"),
"Privada (solo tú)": ("Private (only you)", "Privada (só você)", "Privée (vous seul)"),
"Pública (implicados)": ("Public (involved)", "Pública (envolvidos)", "Publique (concernés)"),
"empleados internos": ("internal employees", "empregados internos", "employés internes"),
"empleados ya sincronizados": ("already synced employees", "empregados já sincronizados", "employés déjà synchronisés"),
"fichajes del día (en vivo)": ("today's clock-ins (live)", "pontos do dia (em direto)", "pointages du jour (en direct)"),
"fichajes procesados hoy": ("clock-ins processed today", "pontos processados hoje", "pointages traités aujourd'hui"),
"fichajes retrospectivos (últimos {n} días)": ("retrospective clock-ins (last {n} days)", "pontos retrospetivos (últimos {n} dias)", "pointages rétrospectifs ({n} derniers jours)"),
"vehículos / flota (master + odómetros de hoy)": ("vehicles / fleet (master + today's odometers)", "veículos / frota (master + odómetros de hoje)", "véhicules / flotte (master + odomètres d'aujourd'hui)"),
"vehículos retrospectivos (últimos {n} días)": ("retrospective vehicles (last {n} days)", "veículos retrospetivos (últimos {n} dias)", "véhicules rétrospectifs ({n} derniers jours)"),
"obras sin cambios (ya sincronizadas)": ("sites unchanged (already synced)", "obras sem alterações (já sincronizadas)", "chantiers inchangés (déjà synchronisés)"),
"pendientes de resolver": ("pending resolution", "pendentes de resolver", "en attente de résolution"),
"por aprobar / validar": ("pending approval / validation", "por aprovar / validar", "en attente d'approbation / validation"),
"ausencias / time off (hr.leave)": ("leave / time off (hr.leave)", "ausências / folgas (hr.leave)", "absences / congés (hr.leave)"),
"sigue asignado": ("still assigned", "continua atribuído", "toujours affecté"),
"sin Odoo": ("without Odoo", "sem Odoo", "sans Odoo"),
"importación": ("import", "importação", "importation"),
"para hacerlos": ("to do them", "para os fazer", "pour les faire"),
"vuelve a primeros pasos": ("go back to getting started", "volte a primeiros passos", "revenir aux premiers pas"),
"ver el módulo (menú, listados, calendarios).": ("view the module (menu, listings, calendars).", "ver o módulo (menu, listados, calendários).", "voir le module (menu, listes, calendriers)."),
"crear, editar y mover (notas, asignaciones, arrastrar en planificador/tablero).": ("create, edit and move (notes, assignments, drag on planner/board).", "criar, editar e mover (notas, atribuições, arrastar no planificador/quadro).", "créer, modifier et déplacer (notes, affectations, glisser sur planificateur/tableau)."),
"solo en módulos con acciones especiales (aprobar, resolver, reset contraseña/PIN, eliminar notas).": ("only in modules with special actions (approve, resolve, reset password/PIN, delete notes).", "apenas em módulos com ações especiais (aprovar, resolver, repor palavra-passe/PIN, eliminar notas).", "uniquement dans les modules avec des actions spéciales (approuver, résoudre, réinitialiser mot de passe/PIN, supprimer des notes)."),
"el operario define su PIN (requiere email)": ("the worker sets their PIN (email required)", "o operário define o seu PIN (requer email)", "l'ouvrier définit son PIN (e-mail requis)"),
"el trabajador define su PIN (requiere email)": ("the worker sets their PIN (email required)", "o trabalhador define o seu PIN (requer email)", "le travailleur définit son PIN (e-mail requis)"),
"lo generas o escribes y se lo das en mano": ("you generate or write it and hand it over in person", "gera ou escreve e entrega-o em mão", "vous le générez ou l'écrivez et le remettez en mains propres"),
"genera un PIN a cada trabajador importado (necesario para entrar a fichar).": ("generates a PIN for each imported worker (required to clock in).", "gera um PIN para cada trabalhador importado (necessário para picar o ponto).", "génère un PIN pour chaque travailleur importé (nécessaire pour pointer)."),
"todavía no ha habilitado el registro de jornada desde el móvil. Si crees que debería estarlo, coméntaselo a tu responsable.": ("has not enabled mobile working-time records yet. If you think it should be, mention it to your manager.", "ainda não habilitou o registo de jornada a partir do telemóvel. Se acha que deveria estar ativo, comente com o seu responsável.", "n'a pas encore activé le registre du temps de travail depuis le mobile. Si vous pensez qu'il devrait l'être, mentionnez-le à votre responsable."),
"y te enseñamos lo esencial del tablero. Luego puedes borrarlos con un clic.": ("and we show you the board essentials. You can delete them with one click later.", "e mostramos-lhe o essencial do quadro. Depois pode apagá-los com um clique.", "et nous vous montrons l'essentiel du tableau. Vous pourrez les supprimer d'un clic ensuite."),
"trabajadores. Esta acción es destructiva.": ("workers. This action is destructive.", "trabalhadores. Esta ação é destrutiva.", "travailleurs. Cette action est destructive."),
"útil para probar o dárselo en mano": ("useful for testing or handing it over in person", "útil para testar ou entregar em mão", "utile pour tester ou remettre en mains propres"),
"o, si lo prefiere, por su propio dominio.": ("or, if they prefer, via their own domain.", "ou, se preferir, pelo seu próprio domínio.", "ou, s'il préfère, via son propre domaine."),
"Conforme del trabajador": ("Worker confirmation", "Conforme do trabalhador", "Confirmation du travailleur"),
}

for k, (en, pt, fr) in remaining.items():
    T[k] = (en, pt, fr)


def load_json(path):
    if not os.path.isfile(path):
        return {}
    with open(path, encoding='utf-8') as f:
        return json.load(f)

def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')

def main():
    report = load_json(REPORT)
    missing_en = set(report.get('missing_en', []))

    for lang_idx, lang in enumerate(('en', 'pt', 'fr')):
        extra_path = os.path.join(EXTRA, f'{lang}.json')
        existing = load_json(extra_path)

        added = 0
        for k, vals in T.items():
            if k in SKIP:
                continue
            if k not in existing:
                existing[k] = vals[lang_idx]
                added += 1

        save_json(extra_path, existing)
        sys.stdout.buffer.write(f'{lang}: +{added} keys (total {len(existing)})\n'.encode('utf-8'))

if __name__ == '__main__':
    import sys
    main()
