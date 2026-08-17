# Fill PT/FR gaps from EN catalog (msgid is Spanish).
from __future__ import annotations

import json
from pathlib import Path

LOC = Path(__file__).resolve().parents[1] / "app" / "i18n" / "locales"

PT = {
    "Abre el historial o pulsa Consultar para cargar datos.": "Abra o histórico ou prima Consultar para carregar dados.",
    "Activar": "Ativar",
    "Ajustes": "Definições",
    "Aquí llegan los pedidos de gente": "Aqui chegam os pedidos de pessoal",
    "Archivado": "Arquivado",
    "Auditoría vehículos": "Auditoria de veículos",
    "Auditorías": "Auditorias",
    "Cargando historial…": "A carregar histórico…",
    "Contactar con SignaPlan": "Contactar a SignaPlan",
    "Crear jefe de obra": "Criar chefe de obra",
    "Crear otro jefe de obra": "Criar outro chefe de obra",
    "Cuando pidas gente desde el tablero, las solicitudes saldrán aquí.": "Quando pedir pessoal a partir do quadro, os pedidos aparecerão aqui.",
    "Cuando un jefe pida gente desde el tablero, la petición aparecerá en esta lista.": "Quando um chefe pedir pessoal a partir do quadro, o pedido aparecerá nesta lista.",
    "Directorio de obras": "Diretório de obras",
    "Editar valoración": "Editar avaliação",
    "Evaluador": "Avaliador",
    "Ficha": "Ficha",
    "Gestión": "Gestão",
    "Integraciones a medida": "Integrações à medida",
    "Ir al tablero": "Ir para o quadro",
    "Las solicitudes las hace el jefe de obra cuando necesita personal en un tajo. Oficina las ve aquí y coloca a las personas.": "Os pedidos são feitos pelo chefe de obra quando precisa de pessoal. O escritório vê-os aqui e coloca as pessoas.",
    "Modifica la puntuación (-3 a +3)": "Altere a pontuação (-3 a +3)",
    "Operario / Conductor": "Operário / Condutor",
    "Personalizado": "Personalizado",
    "Planificado + odómetros Odoo": "Planeado + odómetros Odoo",
    "Puntos": "Pontos",
    "Se archivará y dejará de contar para la reputación.": "Será arquivado e deixará de contar para a reputação.",
    "Selecciona una puntuación.": "Selecione uma pontuação.",
    "Si colocas tú mismo a la gente en el tablero, esta pestaña se quedará vacía y no pasa nada. Si en obra hay un jefe que pide cuadrilla, créalo aquí.": "Se colocar você mesmo as pessoas no quadro, este separador pode ficar vazio. Se na obra houver um chefe que peça equipa, crie-o aqui.",
    "Sin marca/modelo": "Sem marca/modelo",
    "Sin motivo especificado": "Sem motivo indicado",
    "Sin uso planificado ni odómetros Odoo en los últimos": "Sem uso planeado nem odómetros Odoo nos últimos",
    "Sí, eliminar": "Sim, eliminar",
    "despliega para consultar": "expanda para consultar",
    "días": "dias",
    "registro": "registo",
    "¿Eliminar valoración?": "Eliminar avaliação?",
    "Últimos": "Últimos",
}

FR = {
    "Abre el historial o pulsa Consultar para cargar datos.": "Ouvrez l’historique ou appuyez sur Consulter pour charger les données.",
    "Activar": "Activer",
    "Ajustes": "Réglages",
    "Aquí llegan los pedidos de gente": "Les demandes de personnel arrivent ici",
    "Archivado": "Archivé",
    "Auditoría vehículos": "Audit véhicules",
    "Auditorías": "Audits",
    "Cargando historial…": "Chargement de l’historique…",
    "Contactar con SignaPlan": "Contacter SignaPlan",
    "Crear jefe de obra": "Créer un chef de chantier",
    "Crear otro jefe de obra": "Créer un autre chef de chantier",
    "Cuando pidas gente desde el tablero, las solicitudes saldrán aquí.": "Quand vous demanderez du personnel depuis le tableau, les demandes apparaîtront ici.",
    "Cuando un jefe pida gente desde el tablero, la petición aparecerá en esta lista.": "Quand un chef demandera du personnel depuis le tableau, la demande apparaîtra dans cette liste.",
    "Directorio de obras": "Annuaire des chantiers",
    "Editar valoración": "Modifier l’évaluation",
    "Evaluador": "Évaluateur",
    "Ficha": "Fiche",
    "Gestión": "Gestion",
    "Integraciones a medida": "Intégrations sur mesure",
    "Ir al tablero": "Aller au tableau",
    "Las solicitudes las hace el jefe de obra cuando necesita personal en un tajo. Oficina las ve aquí y coloca a las personas.": "Les demandes sont faites par le chef de chantier quand il a besoin de personnel. Le bureau les voit ici et place les personnes.",
    "Modifica la puntuación (-3 a +3)": "Modifiez la note (-3 à +3)",
    "Operario / Conductor": "Ouvrier / Conducteur",
    "Personalizado": "Personnalisé",
    "Planificado + odómetros Odoo": "Planifié + odomètres Odoo",
    "Puntos": "Points",
    "Se archivará y dejará de contar para la reputación.": "Il sera archivé et ne comptera plus pour la réputation.",
    "Selecciona una puntuación.": "Sélectionnez une note.",
    "Si colocas tú mismo a la gente en el tablero, esta pestaña se quedará vacía y no pasa nada. Si en obra hay un jefe que pide cuadrilla, créalo aquí.": "Si vous placez vous-même les personnes sur le tableau, cet onglet peut rester vide. Si un chef sur chantier demande une équipe, créez-le ici.",
    "Sin marca/modelo": "Sans marque/modèle",
    "Sin motivo especificado": "Sans motif indiqué",
    "Sin uso planificado ni odómetros Odoo en los últimos": "Sans usage planifié ni odomètres Odoo sur les derniers",
    "Sí, eliminar": "Oui, supprimer",
    "despliega para consultar": "déplier pour consulter",
    "días": "jours",
    "registro": "enregistrement",
    "¿Eliminar valoración?": "Supprimer l’évaluation ?",
    "Últimos": "Derniers",
}


def main() -> None:
    en = json.loads((LOC / "en.json").read_text(encoding="utf-8"))
    pt = json.loads((LOC / "pt.json").read_text(encoding="utf-8"))
    fr = json.loads((LOC / "fr.json").read_text(encoding="utf-8"))
    missing = set(en) - set(pt)
    matched_pt = 0
    unmatched = []
    for key in missing:
        if key in PT:
            pt[key] = PT[key]
            matched_pt += 1
        else:
            unmatched.append(key)
        if key in FR:
            fr[key] = FR[key]
        elif key in PT:
            pass
    print("filled_pt", matched_pt, "unmatched", len(unmatched))
    for k in unmatched:
        print("UNMATCHED", k.encode("unicode_escape").decode())
    (LOC / "pt.json").write_text(
        json.dumps(pt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (LOC / "fr.json").write_text(
        json.dumps(fr, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print("sizes", len(en), len(pt), len(fr))


if __name__ == "__main__":
    main()
