from pathlib import Path
import json

LOC = Path("app/i18n/locales")
EXTRA = {
    "Aviso legal": {"es": "Aviso legal", "en": "Legal notice", "pt": "Aviso legal", "fr": "Mentions légales"},
    "Política de privacidad": {"es": "Política de privacidad", "en": "Privacy policy", "pt": "Política de privacidade", "fr": "Politique de confidentialité"},
    "Política de cookies": {"es": "Política de cookies", "en": "Cookie policy", "pt": "Política de cookies", "fr": "Politique de cookies"},
    "Encargo de tratamiento": {"es": "Encargo de tratamiento", "en": "Data processing agreement", "pt": "Encarregado do tratamento", "fr": "Accord de sous-traitance"},
    "Condiciones de uso": {"es": "Condiciones de uso", "en": "Terms of use", "pt": "Condições de utilização", "fr": "Conditions d’utilisation"},
    "Inicio": {"es": "Inicio", "en": "Home", "pt": "Início", "fr": "Accueil"},
    "Preguntas frecuentes": {"es": "Preguntas frecuentes", "en": "Frequently asked questions", "pt": "Perguntas frequentes", "fr": "Questions fréquentes"},
    "También te puede interesar": {"es": "También te puede interesar", "en": "You may also like", "pt": "Também lhe pode interessar", "fr": "Vous pouvez aussi aimer"},
    "Actualizado": {"es": "Actualizado", "en": "Updated", "pt": "Atualizado", "fr": "Mis à jour"},
    "Guías prácticas": {"es": "Guías prácticas", "en": "Practical guides", "pt": "Guias práticos", "fr": "Guides pratiques"},
    "Guías para constructoras": {"es": "Guías para constructoras", "en": "Guides for builders", "pt": "Guias para construtoras", "fr": "Guides pour le BTP"},
    "Crear cuenta gratuita": {"es": "Crear cuenta gratuita", "en": "Create a free account", "pt": "Criar conta gratuita", "fr": "Créer un compte gratuit"},
    "Enviar mensaje": {"es": "Enviar mensaje", "en": "Send message", "pt": "Enviar mensagem", "fr": "Envoyer le message"},
    "Hablar con nosotros": {"es": "Hablar con nosotros", "en": "Talk to us", "pt": "Falar connosco", "fr": "Nous contacter"},
    "Nombre": {"es": "Nombre", "en": "Name", "pt": "Nome", "fr": "Nom"},
    "Tu correo": {"es": "Tu correo", "en": "Your email", "pt": "O seu e-mail", "fr": "Votre e-mail"},
    "Empresa": {"es": "Empresa", "en": "Company", "pt": "Empresa", "fr": "Entreprise"},
    "Mensaje": {"es": "Mensaje", "en": "Message", "pt": "Mensagem", "fr": "Message"},
    "(opcional)": {"es": "(opcional)", "en": "(optional)", "pt": "(opcional)", "fr": "(facultatif)"},
    "seo.contacto.title": {
        "es": "Contacto — SignaPlan",
        "en": "Contact — SignaPlan",
        "pt": "Contacto — SignaPlan",
        "fr": "Contact — SignaPlan",
    },
    "seo.contacto.description": {
        "es": "Habla con SignaPlan: demo, alta o integración con tu ERP. Software de cuadrante, fichaje y flota para constructoras.",
        "en": "Talk to SignaPlan: demo, signup or ERP integration. Crew board, time clock and fleet for builders.",
        "pt": "Fale com a SignaPlan: demo, alta ou integração com o ERP. Quadro, ponto e frota para construtoras.",
        "fr": "Parlez à SignaPlan : démo, inscription ou intégration ERP. Planning, pointage et flotte pour le BTP.",
    },
    "seo.entrar.title": {
        "es": "Entrar — SignaPlan",
        "en": "Sign in — SignaPlan",
        "pt": "Entrar — SignaPlan",
        "fr": "Connexion — SignaPlan",
    },
    "seo.entrar.description": {
        "es": "Accede al espacio de tu empresa en SignaPlan. Si no recuerdas la URL, te la enviamos por correo.",
        "en": "Access your company workspace on SignaPlan. If you forgot the URL, we will email it.",
        "pt": "Aceda ao espaço da sua empresa no SignaPlan. Se não lembrar o URL, enviamos por e-mail.",
        "fr": "Accédez à l’espace de votre entreprise sur SignaPlan. Si vous avez oublié l’URL, nous l’envoyons par e-mail.",
    },
    "seo.soluciones.title": {
        "es": "Soluciones SignaPlan — cuadrante, fichaje en obra y flota",
        "en": "SignaPlan solutions — crew board, site time clock and fleet",
        "pt": "Soluções SignaPlan — quadro, ponto na obra e frota",
        "fr": "Solutions SignaPlan — planning, pointage chantier et flotte",
    },
    "seo.soluciones.description": {
        "es": "Cuadrante de personal, fichaje y control horario en construcción, registro de jornada y flota. Sin montar un ERP. Alta gratuita.",
        "en": "Crew board, construction time clock, working-time record and fleet. No ERP to install. Free signup.",
        "pt": "Quadro de pessoal, ponto e controlo horário na construção, registo de jornada e frota. Sem montar um ERP. Alta gratuita.",
        "fr": "Planning d’équipe, pointage BTP, registre du temps de travail et flotte. Sans installer un ERP. Inscription gratuite.",
    },
    "seo.recursos.title": {
        "es": "Guías SignaPlan — cuadrante, fichaje e inspección de jornada",
        "en": "SignaPlan guides — crew board, time clock and labour inspection",
        "pt": "Guias SignaPlan — quadro, ponto e inspeção de jornada",
        "fr": "Guides SignaPlan — planning, pointage et contrôle du temps de travail",
    },
    "seo.recursos.description": {
        "es": "Cuadrante de personal de obra, fichaje en construcción, registro de jornada e inspección. Textos prácticos para constructoras, no jerga de ERP.",
        "en": "Site crew board, construction time clock, working-time record and inspection. Practical writing for builders, not ERP jargon.",
        "pt": "Quadro de pessoal de obra, ponto na construção, registo de jornada e inspeção. Textos práticos para construtoras, não jargão de ERP.",
        "fr": "Planning d’équipe, pointage BTP, registre du temps de travail et contrôle. Textes pratiques pour le BTP, pas du jargon d’ERP.",
    },
}

def main():
    bags = {c: json.loads((LOC / f"{c}.json").read_text(encoding="utf-8")) for c in ("es", "en", "pt", "fr")}
    for key, trans in EXTRA.items():
        for code, val in trans.items():
            if code == "es" and "." not in key:
                continue
            bags[code][key] = val
        bags["es"].setdefault(key, trans["es"])
    for code, data in bags.items():
        (LOC / f"{code}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(code, len(data))

if __name__ == "__main__":
    main()
