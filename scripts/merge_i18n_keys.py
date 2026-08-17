# Merge extra msgid → translations into app/i18n/locales/{es,en,pt,fr}.json
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOC = ROOT / "app" / "i18n" / "locales"

# msgid (ES or dotted) → {es, en, pt, fr}
KEYS = {
    "nav.solutions": {
        "es": "Soluciones",
        "en": "Solutions",
        "pt": "Soluções",
        "fr": "Solutions",
    },
    "nav.guides": {
        "es": "Guías",
        "en": "Guides",
        "pt": "Guias",
        "fr": "Guides",
    },
    "seo.landing.title": {
        "es": "SignaPlan — Cuadrante, fichaje y flota para constructoras (sin ERP)",
        "en": "SignaPlan — Crew board, time clock and fleet for builders (no ERP)",
        "pt": "SignaPlan — Quadro de pessoal, ponto e frota para construtoras (sem ERP)",
        "fr": "SignaPlan — Planning, pointage et flotte pour le BTP (sans ERP)",
    },
    "seo.landing.description": {
        "es": "Software para constructoras PYME: cuadrante de quién va a cada obra, fichaje en el tajo y coches libres. Sin ERP, sin tarjeta. Crea cuenta en minutos.",
        "en": "Software for small builders: who goes to which site, clock-in on the field, and free vehicles. No ERP, no card. Create an account in minutes.",
        "pt": "Software para construtoras PME: quem vai a cada obra, ponto no campo e carros livres. Sem ERP, sem cartão. Crie conta em minutos.",
        "fr": "Logiciel pour PME du BTP : qui va sur quel chantier, pointage sur le terrain et véhicules libres. Sans ERP, sans carte. Créez un compte en quelques minutes.",
    },
    "landing.see_solutions": {
        "es": "Ver soluciones",
        "en": "See solutions",
        "pt": "Ver soluções",
        "fr": "Voir les solutions",
    },
    "landing.looking_for": {
        "es": "Si estás buscando esto",
        "en": "If this is what you are looking for",
        "pt": "Se está à procura disto",
        "fr": "Si c’est ce que vous cherchez",
    },
    "landing.guides_sub": {
        "es": "Guías cortas para constructoras. El siguiente paso es crear cuenta, no descargar un Excel.",
        "en": "Short guides for builders. The next step is to create an account, not download a spreadsheet.",
        "pt": "Guias curtas para construtoras. O passo seguinte é criar conta, não descarregar um Excel.",
        "fr": "Guides courts pour le BTP. L’étape suivante est de créer un compte, pas de télécharger un Excel.",
    },
    "landing.guide.cuadrante": {
        "es": "Cuadrante de personal de obra",
        "en": "Site crew board",
        "pt": "Quadro de pessoal de obra",
        "fr": "Planning d’équipe de chantier",
    },
    "landing.guide.cuadrante_sub": {
        "es": "Quién va a cada tajo cada día. No es un Gantt ni un ERP.",
        "en": "Who goes to which site each day. Not a Gantt, not an ERP.",
        "pt": "Quem vai a cada frente cada dia. Não é um Gantt nem um ERP.",
        "fr": "Qui va sur quel chantier chaque jour. Ni Gantt, ni ERP.",
    },
    "landing.guide.inspeccion": {
        "es": "Inspección de jornada en construcción",
        "en": "Working-time inspection on construction sites",
        "pt": "Inspeção de jornada na construção",
        "fr": "Contrôle du temps de travail sur chantier",
    },
    "landing.guide.inspeccion_sub": {
        "es": "Qué se suele pedir en obra y por qué el Excel no aguanta el tajo.",
        "en": "What inspectors usually ask for, and why a spreadsheet does not survive the site.",
        "pt": "O que costuma ser pedido em obra e por que o Excel não aguenta o campo.",
        "fr": "Ce que l’on demande souvent sur chantier, et pourquoi Excel ne tient pas.",
    },
    "landing.guide.software": {
        "es": "Software para constructoras (sin ERP)",
        "en": "Software for builders (no ERP)",
        "pt": "Software para construtoras (sem ERP)",
        "fr": "Logiciel pour le BTP (sans ERP)",
    },
    "landing.guide.software_sub": {
        "es": "Cuadrante, fichaje y flota. Alta sin tarjeta.",
        "en": "Crew board, time clock and fleet. Sign up with no card.",
        "pt": "Quadro, ponto e frota. Alta sem cartão.",
        "fr": "Planning, pointage et flotte. Inscription sans carte.",
    },
    "landing.all_guides": {
        "es": "Ver todas las guías",
        "en": "See all guides",
        "pt": "Ver todos os guias",
        "fr": "Voir tous les guides",
    },
    "landing.inspection_link": {
        "es": "Inspección de jornada en obra",
        "en": "Working-time inspection on site",
        "pt": "Inspeção de jornada em obra",
        "fr": "Contrôle du temps de travail sur chantier",
    },
    "seo.alta.title": {
        "es": "Crear cuenta gratuita — SignaPlan",
        "en": "Create a free account — SignaPlan",
        "pt": "Criar conta gratuita — SignaPlan",
        "fr": "Créer un compte gratuit — SignaPlan",
    },
    "seo.alta.description": {
        "es": "Crea el espacio de tu constructora en SignaPlan. Sin tarjeta. Planificador de personal, fichaje en obra y flota.",
        "en": "Create your company workspace on SignaPlan. No card. Crew planner, site time clock and fleet.",
        "pt": "Crie o espaço da sua construtora no SignaPlan. Sem cartão. Planeador de pessoal, ponto na obra e frota.",
        "fr": "Créez l’espace de votre entreprise sur SignaPlan. Sans carte. Planning, pointage chantier et flotte.",
    },
    "alta.heading": {
        "es": "Crea el espacio de tu empresa",
        "en": "Create your company workspace",
        "pt": "Crie o espaço da sua empresa",
        "fr": "Créez l’espace de votre entreprise",
    },
    "alta.sub": {
        "es": "Sin tarjeta. Tu URL será",
        "en": "No card. Your URL will be",
        "pt": "Sem cartão. O seu URL será",
        "fr": "Sans carte. Votre URL sera",
    },
    "alta.company_name": {
        "es": "Nombre de la empresa",
        "en": "Company name",
        "pt": "Nome da empresa",
        "fr": "Nom de l’entreprise",
    },
    "alta.subdomain": {
        "es": "Subdominio",
        "en": "Subdomain",
        "pt": "Subdomínio",
        "fr": "Sous-domaine",
    },
    "alta.admin_email": {
        "es": "Correo del administrador",
        "en": "Administrator email",
        "pt": "E-mail do administrador",
        "fr": "E-mail de l’administrateur",
    },
    "alta.password": {
        "es": "Contraseña",
        "en": "Password",
        "pt": "Palavra-passe",
        "fr": "Mot de passe",
    },
    "alta.password2": {
        "es": "Repite la contraseña",
        "en": "Repeat the password",
        "pt": "Repita a palavra-passe",
        "fr": "Répétez le mot de passe",
    },
    "alta.privacy_1": {
        "es": "He leído la",
        "en": "I have read the",
        "pt": "Li a",
        "fr": "J’ai lu la",
    },
    "alta.privacy_2": {
        "es": "política de privacidad",
        "en": "privacy policy",
        "pt": "política de privacidade",
        "fr": "politique de confidentialité",
    },
    "alta.terms_1": {
        "es": "Acepto las",
        "en": "I accept the",
        "pt": "Aceito as",
        "fr": "J’accepte les",
    },
    "alta.terms_2": {
        "es": "condiciones de uso",
        "en": "terms of use",
        "pt": "condições de utilização",
        "fr": "conditions d’utilisation",
    },
    "cookie.aria": {
        "es": "Cookies",
        "en": "Cookies",
        "pt": "Cookies",
        "fr": "Cookies",
    },
    "cookie.essential": {
        "es": "Usamos cookies esenciales para que el sitio funcione.",
        "en": "We use essential cookies so the site works.",
        "pt": "Usamos cookies essenciais para o sítio funcionar.",
        "fr": "Nous utilisons des cookies essentiels pour faire fonctionner le site.",
    },
    "cookie.analytics": {
        "es": "Con tu permiso también usamos cookies de analítica (Google Analytics) para mejorar el producto.",
        "en": "With your permission we also use analytics cookies (Google Analytics) to improve the product.",
        "pt": "Com a sua permissão também usamos cookies de análise (Google Analytics) para melhorar o produto.",
        "fr": "Avec votre accord, nous utilisons aussi des cookies d’analyse (Google Analytics) pour améliorer le produit.",
    },
    "cookie.future": {
        "es": "Si en el futuro activamos analítica o marketing, te pediremos permiso aquí.",
        "en": "If we later enable analytics or marketing, we will ask permission here.",
        "pt": "Se no futuro ativarmos análise ou marketing, pediremos permissão aqui.",
        "fr": "Si nous activons plus tard l’analyse ou le marketing, nous demanderons l’autorisation ici.",
    },
    "cookie.more": {
        "es": "Más información",
        "en": "More information",
        "pt": "Mais informação",
        "fr": "Plus d’informations",
    },
    "cookie.only_essential": {
        "es": "Solo esenciales",
        "en": "Essential only",
        "pt": "Só essenciais",
        "fr": "Essentiels uniquement",
    },
    "cookie.accept_all": {
        "es": "Aceptar todas",
        "en": "Accept all",
        "pt": "Aceitar todas",
        "fr": "Tout accepter",
    },
    "cookie.ok": {
        "es": "Entendido",
        "en": "Got it",
        "pt": "Entendido",
        "fr": "Compris",
    },
    "legal.updated": {
        "es": "Última actualización: agosto 2026 · Contacto:",
        "en": "Last updated: August 2026 · Contact:",
        "pt": "Última atualização: agosto de 2026 · Contacto:",
        "fr": "Dernière mise à jour : août 2026 · Contact :",
    },
    "seo.legal.description": {
        "es": "Información legal de SignaPlan, software de planificación, fichaje y flota para constructoras.",
        "en": "Legal information for SignaPlan, planning, time-clock and fleet software for builders.",
        "pt": "Informação legal do SignaPlan, software de planeamento, ponto e frota para construtoras.",
        "fr": "Informations légales de SignaPlan, logiciel de planning, pointage et flotte pour le BTP.",
    },
    "Cargando…": {
        "es": "Cargando…",
        "en": "Loading…",
        "pt": "A carregar…",
        "fr": "Chargement…",
    },
}


def load(name: str) -> dict:
    return json.loads((LOC / name).read_text(encoding="utf-8"))


def dump(name: str, data: dict) -> None:
    (LOC / name).write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    bags = {code: load(f"{code}.json") for code in ("es", "en", "pt", "fr")}
    added = {code: 0 for code in bags}
    for key, trans in KEYS.items():
        for code, text in trans.items():
            if bags[code].get(key) != text:
                if key not in bags[code]:
                    added[code] += 1
                bags[code][key] = text
    for code, data in bags.items():
        dump(f"{code}.json", data)
    print("added/updated", added, "totals", {c: len(b) for c, b in bags.items()})


if __name__ == "__main__":
    main()
