"""EN / pt-PT / FR overlays for marketing SEO articles and solutions.

Spanish source lives in seo_articles.py / seo_solutions.py. This module copies
that dict and overlays translated title, description, h1, keywords, eyebrow,
faq and body_html. Internal hrefs in body_html are prefixed for non-ES locales.
"""

from __future__ import annotations

import re

_LINK_LOCALES = frozenset({'en', 'pt', 'fr'})
_INTERNAL_FIRST = frozenset(
    {'alta', 'contacto', 'entrar', 'soluciones', 'recursos', 'legal'}
)
_ALREADY_PREFIXED = re.compile(r'^/(?:en|pt|fr)(/|$)')
_HREF_RE = re.compile(r'''href=(["'])(/[^"']*)\1''')

_ARTICLE_KEYS = ('title', 'description', 'h1', 'keywords', 'body_html')
_SOLUTION_KEYS = ('title', 'description', 'h1', 'keywords', 'eyebrow', 'body_html')


def _norm_locale(locale: str) -> str:
    raw = (locale or 'es').strip().lower().replace('_', '-')
    return raw.split('-', 1)[0] or 'es'


def localize_html_links(html: str, locale: str) -> str:
    """Prefix internal marketing hrefs for en/pt/fr. Never double-prefix."""
    if not html:
        return html
    loc = _norm_locale(locale)
    if loc not in _LINK_LOCALES:
        return html

    def _repl(match: re.Match) -> str:
        quote, path = match.group(1), match.group(2)
        if _ALREADY_PREFIXED.match(path):
            return match.group(0)
        first = path.split('/', 2)[1] if path.startswith('/') else ''
        if first in _INTERNAL_FIRST:
            return f'href={quote}/{loc}{path}{quote}'
        return match.group(0)

    return _HREF_RE.sub(_repl, html)


def _copy_item(item: dict) -> dict:
    out = dict(item)
    faq = out.get('faq')
    if isinstance(faq, list):
        out['faq'] = [dict(entry) for entry in faq]
    return out


def _apply_overlay(out: dict, overlay: dict, keys: tuple) -> None:
    if not overlay:
        return
    for key in keys:
        if key in overlay and overlay[key] is not None:
            out[key] = overlay[key]
    if 'faq' in overlay and overlay['faq'] is not None:
        out['faq'] = [dict(entry) for entry in overlay['faq']]


def localize_article(article: dict, slug: str, locale: str) -> dict:
    """Copy *article* and overlay the translation for *slug* / *locale*."""
    out = _copy_item(article)
    loc = _norm_locale(locale)
    overlay = (ARTICLES.get(loc) or {}).get(slug) or {}
    _apply_overlay(out, overlay, _ARTICLE_KEYS)
    body = out.get('body_html')
    if isinstance(body, str):
        out['body_html'] = localize_html_links(body, loc)
    return out


def localize_solution(solution: dict, slug: str, locale: str) -> dict:
    """Copy *solution* and overlay the translation for *slug* / *locale*."""
    out = _copy_item(solution)
    loc = _norm_locale(locale)
    overlay = (SOLUTIONS.get(loc) or {}).get(slug) or {}
    _apply_overlay(out, overlay, _SOLUTION_KEYS)
    body = out.get('body_html')
    if isinstance(body, str):
        out['body_html'] = localize_html_links(body, loc)
    return out


ARTICLES = {
    'en': {
        'planificador-de-obra': {
            'title': 'Site planner: the board of who goes to which job (not a Gantt)',
            'description': (
                'Site planner for builders: the daily crew board, not a project Gantt '
                'or an ERP. How to leave Excel and WhatsApp behind.'
            ),
            'h1': 'Site planner for construction companies',
            'keywords': 'site planner, construction crew board, construction planning',
            'body_html': """
<p>If you run a construction company or a site crew, the day usually splits between WhatsApp, Excel and whatever the site manager remembers. A <strong>site planner</strong> puts in one place <em>who goes to which job each day</em>, with changes visible to office and field.</p>
<h2>What a real site planner should do</h2>
<ul>
  <li>Assign people to sites and dates without fighting spreadsheet cells.</li>
  <li>See conflicts (double booking, leave) before they reach the site.</li>
  <li>Let the site manager move labourers without depending on the office Excel.</li>
  <li>Connect to time clocking and vehicles when you need to.</li>
</ul>
<h2>Site planner vs. just a calendar</h2>
<p>A generic calendar does not understand sites, roles or leave. A planner built for construction works with <strong>sites, labourers, managers and date windows</strong>, and shows the impact of a change on the rest of the board.</p>
<h2>How most crews start</h2>
<ol>
  <li>Add sites and people (even a short list).</li>
  <li>Board looking 2–4 weeks ahead.</li>
  <li>A clear rule: changes go in the tool, not only in a message.</li>
  <li>Then, phone clock-in and fleet if it applies.</li>
</ol>
<p>SignaPlan puts planner, time clocking with a working-time record and fleet on the same platform. If what you want is the <strong>crew board</strong> (who goes to which job), follow the <a href="/recursos/cuadrante-personal-obra">crew board guide</a> or <a href="/alta">create a free account</a>.</p>
""",
        },
        'cuadrante-personal-obra': {
            'title': 'Site crew board: who goes to which job each day',
            'description': (
                'Board of labourers and site managers by site and date. An alternative '
                'to Excel and WhatsApp. Not a Gantt or an ERP: it is who I send tomorrow '
                'to each job.'
            ),
            'h1': 'Site crew board (who goes to which job)',
            'keywords': 'construction crew board, labourer board, who goes to which site, excel crew board builder',
            'body_html': """
<p>If you open an Excel every morning to decide <strong>who goes to which site</strong>, you already have a crew board. The problem is that it lives in a file, in a WhatsApp group and in the manager’s head. A <strong>site crew board</strong> is that same question, on a board that office and field see the same way.</p>
<h2>It is not a Gantt-style site planner</h2>
<p>When Google shows “site planner”, you usually get <strong>project</strong> software: bars, bill of quantities, estimates. That does not tell you whether the labourer is on the A-23 tomorrow or on the house job. The crew board does: person, site, dates.</p>
<h2>What breaks with the Excel board</h2>
<ul>
  <li>Two versions (office and site hut) and nobody knows which one counts.</li>
  <li>A 7:00 change that never reaches the person who is driving.</li>
  <li>Double bookings and sick leave you only see when the job is already half done.</li>
</ul>
<h2>What the board has to do</h2>
<ul>
  <li>Assign people to sites by day, without fighting merged cells.</li>
  <li>Let the site manager move labourers without waiting for admin’s Excel.</li>
  <li>See clashes (two sites, leave) before the first van leaves.</li>
  <li>Hook time clocking and vehicles to the same calendar later.</li>
</ul>
<p>SignaPlan is exactly that board. Start with <a href="/alta">free signup</a> (no card) or see the <a href="/soluciones/planificador-personal-obra">crew planner solution</a>.</p>
""",
        },
        'fichaje-construccion': {
            'title': 'Time clocking on construction sites: ID + PIN on the phone, no wall clock',
            'description': (
                'How to roll out time clocking on site with a phone: clock-in, clock-out, '
                'breaks and a trail. A practical alternative to the wall clock for builders.'
            ),
            'h1': 'How to roll out time clocking on site (guide)',
            'keywords': 'construction time clock, site clock-in, construction working-time control',
            'body_html': """
<p>On site the wall clock gets lost, shared or simply not used. <strong>Time clocking in construction</strong> on a phone (ID + PIN) lets each worker record the day wherever the job is.</p>
<h2>What the daily practice needs</h2>
<ul>
  <li>Clock-in, clock-out and breaks without friction (gloves, sun, hurry).</li>
  <li>The office seeing the same day what happened.</li>
  <li>Reports ready when an inspection or an HR query arrives.</li>
</ul>
<h2>Time clocking and planning together</h2>
<p>If the board says Juan is on site A and the clock-in shows up somewhere else, someone has to find out soon. That is why <strong>planner and time clock should live in the same tool</strong>, not on two islands.</p>
<p>With SignaPlan the worker clocks in from the phone and the company keeps a working-time record with a trail. Continue on the <a href="/soluciones/fichaje-construccion">time-clock product page</a> or start with <a href="/alta">free signup</a>. If an inspection worries you, follow <a href="/recursos/inspeccion-trabajo-construccion">working-time inspection on site</a>.</p>
""",
        },
        'registro-jornada-laboral': {
            'title': 'Working-time record on site: leave Excel without losing control',
            'description': (
                'Working-time record in construction without Excel templates: breaks, '
                'a trail and a report for inspection. A practical guide for builders.'
            ),
            'h1': 'Working-time record on construction sites',
            'keywords': 'working-time record, working-time control, construction timesheet record',
            'body_html': """
<p>A <strong>working-time record</strong> is not just “clocking in”. It is being able to show hours, breaks and changes with a clear trail when inspection or the worker asks for it.</p>
<p>If you are looking for a <strong>working-time record in Excel</strong> (template, daily sheet, part-time), the problem is not the file: it is the copies, the corrections with no trace and that it does not match what happened on site. Digitising it is not “another Excel in the cloud”; it is a ledger of events that do not get rewritten.</p>
<h2>Typical Excel problems</h2>
<ul>
  <li>A different version on each PC.</li>
  <li>Corrections with no history.</li>
  <li>Hours that do not match what happened on site.</li>
</ul>
<h2>What actually helps</h2>
<p>A digital working-time ledger with chained events, breaks and, when it applies, the worker’s acknowledgement. Exportable PDF/CSV for filing or your adviser.</p>
<p>SignaPlan includes a working-time record with a trail tied to clocking in the field. If a visit from the inspector worries you, read <a href="/recursos/inspeccion-trabajo-construccion">what they ask for on site</a>. Continue on the <a href="/soluciones/registro-jornada-obra">working-time record solution</a> or <a href="/alta">create a free account</a>.</p>
""",
        },
        'inspeccion-trabajo-construccion': {
            'title': 'Labour inspection in construction: the working-time record on site',
            'description': (
                'What a working-time inspection usually asks for on a builder’s site: '
                'clock-ins, breaks and a credible trail on the job. How to stop improvising with Excel.'
            ),
            'h1': 'Labour inspection on site: a working-time record you can show',
            'keywords': 'labour inspection construction, working-time inspection site, working-time fine builder',
            'body_html': """
<p>In a <strong>labour inspection</strong> on a construction site it is not enough to say “we clock in”. You have to be able to show, by person and by day, clock-ins, clock-outs and breaks with a trail that is not an Excel patched the night before. This is not legal advice: it is what breaks on site when the clock is in the hut and the labourer is on the job.</p>
<h2>Why Excel does not survive the job</h2>
<ul>
  <li>Different copies on each PC and corrections with no history.</li>
  <li>Hours “agreed” on Friday that do not match what happened in the field.</li>
  <li>A wall clock that gets shared or that nobody uses.</li>
</ul>
<h2>What actually helps (without standing up an ERP)</h2>
<ul>
  <li>Clock-in on the phone, where the site is.</li>
  <li>A working-time ledger that does not get rewritten on a whim.</li>
  <li>Export (PDF/CSV) for filing, your adviser or the visit.</li>
  <li>The same system as the crew board: if Juan was meant to be on site A, you see it.</li>
</ul>
<p>SignaPlan joins field clock-in and a record with a trail. Create an account with <a href="/alta">free signup</a> or continue on <a href="/soluciones/registro-jornada-obra">working-time record on site</a> and <a href="/soluciones/fichaje-construccion">time clocking in construction</a>.</p>
""",
        },
        'gestion-flota-obra': {
            'title': 'Site fleet management: free vehicles and assignment to crew',
            'description': (
                'How to line vehicles up with the crew board and leave: free cars, '
                'daily assignment and fewer WhatsApps about ‘who takes the van’.'
            ),
            'h1': 'Fleet management for construction companies',
            'keywords': 'site fleet management, free cars construction, site vehicle assignment',
            'body_html': """
<p>The van that is “free” and nobody knows where it is: a classic. A <strong>fleet setup</strong> that is small but useful answers: which vehicle goes with which crew, and which ones are free because of leave or a site change.</p>
<h2>Tie fleet and people together</h2>
<p>If the planner moves a labourer and the van stays assigned “because that is how we do it”, you lose time every morning. The fleet has to look at the same calendar as the crew.</p>
<p>SignaPlan includes fleet lined up with leave and the crew board. <a href="/alta">Try it free</a> or continue on the <a href="/soluciones/flota-obra">fleet solution</a>.</p>
""",
        },
        'software-constructoras': {
            'title': 'Software for SME builders: crew board and time clock (not an ERP)',
            'description': (
                'Software for builders: who goes to which site, working-time control and fleet. '
                'Not an estimating ERP. Free signup, no card.'
            ),
            'h1': 'Software for builders (without standing up an ERP)',
            'keywords': 'construction software, site software, construction management program',
            'body_html': """
<p>Many small construction companies do not need a huge ERP on day one. They need to control the <strong>site day</strong>: who goes where, who has clocked in and which van is free. If you are looking for a “free ERP for builders”, this does not replace estimates or invoicing: it is the crew board, time clocking and fleet, and signup does not ask for a card.</p>
<h2>Quick checklist</h2>
<ul>
  <li>Does a site manager understand the planner in 10 minutes?</li>
  <li>Does time clocking work on the labourer’s phone?</li>
  <li>Can you export the working-time record when someone outside asks?</li>
  <li>Does the fleet look at the same calendar?</li>
</ul>
<p>SignaPlan is built exactly for that. Start with <a href="/alta">free signup</a> (no card). If you also run Odoo or another ERP, the integration is discussed as a project from <a href="/contacto">contact</a>.</p>
""",
        },
    },
    'pt': {
        'planificador-de-obra': {
            'title': 'Planeador de obra: o quadro de quem vai a cada frente (não um Gantt)',
            'description': (
                'Planeador de obra para construtoras: o quadro diário de pessoal, '
                'não um Gantt de projeto nem um ERP. Como deixar o Excel e o WhatsApp.'
            ),
            'h1': 'Planeador de obra para construtoras',
            'keywords': 'planeador de obra, quadro pessoal obra, planeamento construção',
            'body_html': """
<p>Se dirige uma construtora ou uma empresa de obra, o dia a dia costuma repartir-se entre WhatsApp, Excel e a memória do chefe de obra. Um <strong>planeador de obra</strong> põe num só sítio <em>quem vai a cada frente cada dia</em>, com alterações visíveis para escritório e campo.</p>
<h2>O que deve fazer um planeador de obra a sério</h2>
<ul>
  <li>Atribuir pessoal a obras e datas sem lutar com células.</li>
  <li>Ver conflitos (dupla atribuição, ausências) antes de chegarem à obra.</li>
  <li>Deixar o chefe de obra mover operários sem depender do Excel do escritório.</li>
  <li>Ligar ao ponto e aos veículos quando for preciso.</li>
</ul>
<h2>Planeador de obra vs. só um calendário</h2>
<p>Um calendário genérico não percebe de obras, funções nem ausências. Um planeador pensado para a construção trabalha com <strong>obras, operários, chefes e janelas de datas</strong>, e mostra o impacto de uma alteração no resto do quadro.</p>
<h2>Como começam a maior parte das equipas</h2>
<ol>
  <li>Alta de obras e pessoal (nem que seja uma lista curta).</li>
  <li>Quadro a 2–4 semanas vista.</li>
  <li>Regra clara: as alterações fazem-se na ferramenta, não só por mensagem.</li>
  <li>Depois, ponto no telemóvel e frota se aplicar.</li>
</ol>
<p>O SignaPlan junta planeador, ponto com registo de jornada e frota na mesma plataforma. Se o que procura é o <strong>quadro</strong> (quem vai a cada frente), siga no <a href="/pt/recursos/cuadrante-personal-obra">guia do quadro de pessoal</a> ou <a href="/pt/alta">crie uma conta gratuita</a>.</p>
""",
        },
        'cuadrante-personal-obra': {
            'title': 'Quadro de pessoal de obra: quem vai a cada frente cada dia',
            'description': (
                'Quadro de operários e chefes por obra e data. Alternativa ao Excel e ao '
                'WhatsApp. Não é um Gantt nem um ERP: é quem mando amanhã a cada frente.'
            ),
            'h1': 'Quadro de pessoal de obra (quem vai a cada frente)',
            'keywords': 'quadro pessoal obra, quadro operários, quem vai a cada obra, excel quadro construtora',
            'body_html': """
<p>Se abre um Excel todas as manhãs para decidir <strong>quem vai a cada obra</strong>, já tem um quadro. O problema é que vive num ficheiro, num grupo de WhatsApp e na cabeça do chefe. Um <strong>quadro de pessoal de obra</strong> é essa mesma pergunta, num painel que escritório e campo veem igual.</p>
<h2>Não é um planeador de obra tipo Gantt</h2>
<p>Quando o Google mostra “planeador de obra”, costuma sair software de <strong>projeto</strong>: barras, artigos, orçamentos. Isso não diz se o operário está amanhã na A-23 ou no chalé. O quadro sim: pessoa, obra, datas.</p>
<h2>O que se parte com o Excel do quadro</h2>
<ul>
  <li>Duas versões (escritório e casota) e ninguém sabe qual vale.</li>
  <li>Uma alteração às 7:00 que não chega a quem conduz.</li>
  <li>Duplas atribuições e baixas que se veem quando a frente já está a meio.</li>
</ul>
<h2>O que o quadro tem de fazer</h2>
<ul>
  <li>Atribuir gente a obras por dia, sem lutar com células combinadas.</li>
  <li>O chefe de obra poder mover operários sem esperar pelo Excel da administração.</li>
  <li>Ver choques (duas obras, ausência) antes de sair o primeiro carro.</li>
  <li>Poder ligar depois o ponto e os veículos ao mesmo calendário.</li>
</ul>
<p>O SignaPlan é exactamente esse painel. Comece em <a href="/pt/alta">alta gratuita</a> (sem cartão) ou veja a <a href="/pt/soluciones/planificador-personal-obra">solução de planeador de pessoal</a>.</p>
""",
        },
        'fichaje-construccion': {
            'title': 'Ponto na construção: documento + PIN no telemóvel, sem relógio de parede',
            'description': (
                'Como implantar o ponto em obra com telemóvel: entradas, saídas, pausas e '
                'rasto. Alternativa prática ao relógio físico nas construtoras.'
            ),
            'h1': 'Como implantar o ponto em obra (guia)',
            'keywords': 'ponto construção, ponto obra, controlo horário construção',
            'body_html': """
<p>Em obra o relógio de parede perde-se, partilha-se ou simplesmente não se usa. O <strong>ponto na construção</strong> com telemóvel (identificação + PIN) permite que cada trabalhador registe a jornada onde estiver a frente.</p>
<h2>O que pede a prática diária</h2>
<ul>
  <li>Entrada, saída e pausas sem atrito (luvas, sol, pressa).</li>
  <li>O escritório ver no mesmo dia o que aconteceu.</li>
  <li>Relatórios prontos quando chega uma inspeção ou um pedido de RH.</li>
</ul>
<h2>Ponto e planeamento juntos</h2>
<p>Se o quadro diz que o João está na obra A e o ponto sai noutro sítio, alguém tem de ficar a saber cedo. Por isso convém que <strong>planeador e ponto vivam na mesma ferramenta</strong>, não em duas ilhas.</p>
<p>Com o SignaPlan o operário regista o ponto a partir do telemóvel e a empresa conserva um registo de jornada com rasto. Siga na <a href="/pt/soluciones/fichaje-construccion">página de produto de ponto</a> ou comece em <a href="/pt/alta">alta gratuita</a>. Se o preocupa uma inspeção, siga em <a href="/pt/recursos/inspeccion-trabajo-construccion">inspeção de jornada em obra</a>.</p>
""",
        },
        'registro-jornada-laboral': {
            'title': 'Registo de jornada laboral em obra: deixar o Excel sem perder o controlo',
            'description': (
                'Registo de jornada laboral na construção sem modelos Excel: pausas, '
                'rasto e relatório para inspeção. Guia prático para construtoras.'
            ),
            'h1': 'Registo de jornada laboral em obra',
            'keywords': 'registo de jornada, controlo horário laboral, registo jornada construção',
            'body_html': """
<p>O <strong>registo de jornada</strong> não é só “picar o ponto”. É poder demonstrar horários, pausas e alterações com um rasto claro quando o pede a inspeção ou o próprio trabalhador.</p>
<p>Se procura um <strong>registo de jornada laboral em Excel</strong> (modelo, diário, tempo parcial), o problema não é o ficheiro: são as cópias, as correções sem rasto e que não bate certo com o que se passou em obra. Digitalizá-lo não é “outro Excel na nuvem”; é um livro com eventos que não se reescrevem.</p>
<h2>Problemas típicos do Excel</h2>
<ul>
  <li>Versões distintas em cada PC.</li>
  <li>Correções sem histórico.</li>
  <li>Horas que não batem certo com o que se passou em obra.</li>
</ul>
<h2>O que ajuda de verdade</h2>
<p>Um livro de jornada digital com eventos encadeados, pausas e, quando se aplicar, conforme do trabalhador. PDF/CSV exportáveis para arquivo ou assessoria.</p>
<p>O SignaPlan inclui registo de jornada com rasto ligado ao ponto no campo. Se o preocupa uma visita da Inspeção, leia <a href="/pt/recursos/inspeccion-trabajo-construccion">o que pedem em obra</a>. Siga na <a href="/pt/soluciones/registro-jornada-obra">solução de registo de jornada</a> ou <a href="/pt/alta">crie uma conta gratuita</a>.</p>
""",
        },
        'inspeccion-trabajo-construccion': {
            'title': 'Inspeção do trabalho na construção: o registo de jornada em obra',
            'description': (
                'O que costuma pedir-se numa inspeção de jornada em construtoras: entradas, '
                'pausas e um rasto credível na frente. Como deixar de improvisar com Excel.'
            ),
            'h1': 'Inspeção do trabalho em obra: um registo de jornada que se pode mostrar',
            'keywords': 'inspeção trabalho construção, registo jornada inspeção obra, coima registo jornada construtora',
            'body_html': """
<p>Numa <strong>inspeção do trabalho</strong> na construção não chega dizer “picamos o ponto”. É preciso poder mostrar, por pessoa e por dia, entradas, saídas e pausas com um rasto que não seja um Excel retocado na noite anterior. Isto não é aconselhamento jurídico: é o que se parte em obra quando o relógio está na casota e o operário está na frente.</p>
<h2>Porque é que o Excel não aguenta a frente</h2>
<ul>
  <li>Cópias distintas em cada PC e correções sem histórico.</li>
  <li>Horas “acordadas” na sexta que não coincidem com o que se passou no campo.</li>
  <li>Um relógio de parede que se partilha ou que ninguém usa.</li>
</ul>
<h2>O que ajuda de verdade (sem montar um ERP)</h2>
<ul>
  <li>Ponto no telemóvel, onde está a obra.</li>
  <li>Um livro de jornada que não se reescreve a bel-prazer.</li>
  <li>Exportação (PDF/CSV) para arquivo, assessoria ou a visita.</li>
  <li>O mesmo sistema que o quadro: se o João devia estar na obra A, vê-se.</li>
</ul>
<p>O SignaPlan junta ponto no campo e registo com rasto. Crie conta em <a href="/pt/alta">alta gratuita</a> ou siga em <a href="/pt/soluciones/registro-jornada-obra">registo de jornada em obra</a> e em <a href="/pt/soluciones/fichaje-construccion">ponto na construção</a>.</p>
""",
        },
        'gestion-flota-obra': {
            'title': 'Gestão de frota em obra: carros livres e atribuição ao pessoal',
            'description': (
                'Como alinhar veículos com o quadro e as ausências: carros livres, '
                'atribuição diária e menos WhatsApps sobre ‘quem leva a carrinha’.'
            ),
            'h1': 'Gestão de frota para empresas de obra',
            'keywords': 'gestão frota obra, carros livres construção, atribuição veículos obra',
            'body_html': """
<p>A carrinha “livre” que ninguém sabe onde está é um clássico. Uma <strong>gestão de frota</strong> mínima mas útil responde: que veículo vai com que equipa, e quais ficam livres por ausência ou mudança de obra.</p>
<h2>Ligar frota e pessoal</h2>
<p>Se o planeador move um operário e o carro continua atribuído “por costume”, perde tempo todas as manhãs. A frota deve olhar para o mesmo calendário que o pessoal.</p>
<p>O SignaPlan inclui frota alinhada com ausências e quadro. <a href="/pt/alta">Experimente grátis</a> ou siga na <a href="/pt/soluciones/flota-obra">solução de frota</a>.</p>
""",
        },
        'software-constructoras': {
            'title': 'Software para construtoras PME: quadro e ponto (não um ERP)',
            'description': (
                'Programa para construtoras: quem vai a cada obra, controlo horário e frota. '
                'Não é um ERP de orçamentos. Alta gratuita, sem cartão.'
            ),
            'h1': 'Software para construtoras (sem montar um ERP)',
            'keywords': 'software construtoras, software obra, programa gestão construção',
            'body_html': """
<p>Muitas PME de construção não precisam de um ERP enorme no primeiro dia. Precisam de controlar o <strong>dia a dia de obra</strong>: quem vai aonde, quem registou o ponto e que carro está livre. Se está à procura de um “ERP para construtoras grátis”, isto não substitui orçamentos nem faturação: é o quadro, o ponto e a frota, e a alta não pede cartão.</p>
<h2>Lista rápida</h2>
<ul>
  <li>O planeador percebe-o um chefe de obra em 10 minutos?</li>
  <li>O ponto funciona no telemóvel do operário?</li>
  <li>Pode exportar a jornada quando alguém de fora o pedir?</li>
  <li>A frota olha para o mesmo calendário?</li>
</ul>
<p>O SignaPlan está pensado exactamente para isso. Comece em <a href="/pt/alta">alta gratuita</a> (sem cartão). Se além disso tem Odoo ou outro ERP, a integração fala-se como projeto a partir de <a href="/pt/contacto">contacto</a>.</p>
""",
        },
    },
    'fr': {
        'planificador-de-obra': {
            'title': 'Planificateur de chantier : le tableau de qui va où (pas un Gantt)',
            'description': (
                'Planificateur de chantier pour le BTP : le tableau quotidien des équipes, '
                'pas un Gantt de projet ni un ERP. Comment quitter Excel et WhatsApp.'
            ),
            'h1': 'Planificateur de chantier pour le BTP',
            'keywords': 'planificateur de chantier, planning équipe BTP, planification construction',
            'body_html': """
<p>Si vous dirigez une entreprise de BTP ou une équipe de chantier, la journée se partage souvent entre WhatsApp, Excel et la mémoire du chef de chantier. Un <strong>planificateur de chantier</strong> met au même endroit <em>qui va sur quel poste chaque jour</em>, avec des changements visibles pour le bureau et le terrain.</p>
<h2>Ce qu’un vrai planificateur de chantier devrait faire</h2>
<ul>
  <li>Affecter le personnel aux chantiers et aux dates sans se battre avec les cellules.</li>
  <li>Voir les conflits (double affectation, absences) avant qu’ils n’arrivent sur le chantier.</li>
  <li>Laisser le chef de chantier déplacer les ouvriers sans dépendre de l’Excel du bureau.</li>
  <li>Relier le pointage et les véhicules quand c’est nécessaire.</li>
</ul>
<h2>Planificateur de chantier vs. un simple calendrier</h2>
<p>Un calendrier générique ne comprend ni les chantiers, ni les rôles, ni les absences. Un planificateur pensé pour le BTP travaille avec des <strong>chantiers, des ouvriers, des chefs et des plages de dates</strong>, et montre l’impact d’un changement sur le reste du tableau.</p>
<h2>Comment commencent la plupart des équipes</h2>
<ol>
  <li>Création des chantiers et du personnel (même une liste courte).</li>
  <li>Tableau à 2–4 semaines.</li>
  <li>Règle claire : les changements se font dans l’outil, pas seulement par message.</li>
  <li>Ensuite, pointage sur le téléphone et flotte si besoin.</li>
</ol>
<p>SignaPlan réunit planificateur, pointage avec registre du temps de travail et flotte sur la même plateforme. Si ce que vous cherchez c’est le <strong>planning d’équipe</strong> (qui va sur quel poste), suivez le <a href="/fr/recursos/cuadrante-personal-obra">guide du planning d’équipe</a> ou <a href="/fr/alta">créez un compte gratuit</a>.</p>
""",
        },
        'cuadrante-personal-obra': {
            'title': 'Planning d’équipe de chantier : qui va sur quel poste chaque jour',
            'description': (
                'Planning des ouvriers et chefs par chantier et par date. Alternative à Excel '
                'et WhatsApp. Ni Gantt ni ERP : c’est qui j’envoie demain sur chaque poste.'
            ),
            'h1': 'Planning d’équipe de chantier (qui va sur quel poste)',
            'keywords': 'planning équipe chantier, planning ouvriers, qui va sur quel chantier, excel planning BTP',
            'body_html': """
<p>Si vous ouvrez un Excel chaque matin pour décider <strong>qui va sur quel chantier</strong>, vous avez déjà un planning d’équipe. Le problème, c’est qu’il vit dans un fichier, dans un groupe WhatsApp et dans la tête du chef. Un <strong>planning d’équipe de chantier</strong> c’est la même question, sur un tableau que le bureau et le terrain voient pareil.</p>
<h2>Ce n’est pas un planificateur de chantier type Gantt</h2>
<p>Quand Google affiche « planificateur de chantier », il sort souvent un logiciel de <strong>projet</strong> : barres, lots, devis. Ça ne dit pas si l’ouvrier est demain sur l’A-23 ou sur la maison. Le planning d’équipe oui : personne, chantier, dates.</p>
<h2>Ce qui casse avec l’Excel du planning</h2>
<ul>
  <li>Deux versions (bureau et baraque) et personne ne sait laquelle compte.</li>
  <li>Un changement à 7 h qui n’arrive pas à celui qui conduit.</li>
  <li>Doubles affectations et arrêts qu’on voit quand le poste est déjà à moitié fait.</li>
</ul>
<h2>Ce que le planning doit faire</h2>
<ul>
  <li>Affecter les gens aux chantiers par jour, sans se battre avec des cellules fusionnées.</li>
  <li>Que le chef de chantier puisse déplacer les ouvriers sans attendre l’Excel de l’admin.</li>
  <li>Voir les collisions (deux chantiers, une absence) avant que le premier véhicule parte.</li>
  <li>Pouvoir brancher ensuite le pointage et les véhicules sur le même calendrier.</li>
</ul>
<p>SignaPlan, c’est exactement ce tableau. Commencez par <a href="/fr/alta">l’inscription gratuite</a> (sans carte) ou voyez la <a href="/fr/soluciones/planificador-personal-obra">solution de planificateur d’équipe</a>.</p>
""",
        },
        'fichaje-construccion': {
            'title': 'Pointage dans le BTP : pièce d’identité + PIN sur le téléphone, sans pointeuse murale',
            'description': (
                'Comment mettre en place le pointage sur chantier avec le téléphone : entrées, sorties, '
                'pauses et traçabilité. Alternative concrète à la pointeuse physique pour le BTP.'
            ),
            'h1': 'Comment mettre en place le pointage sur chantier (guide)',
            'keywords': 'pointage BTP, pointage chantier, contrôle horaire construction',
            'body_html': """
<p>Sur chantier, la pointeuse murale se perd, se partage ou ne s’utilise tout simplement pas. Le <strong>pointage dans le BTP</strong> sur téléphone (identification + PIN) permet à chaque salarié d’enregistrer la journée là où est le poste.</p>
<h2>Ce que demande la pratique quotidienne</h2>
<ul>
  <li>Entrée, sortie et pauses sans friction (gants, soleil, précipitation).</li>
  <li>Que le bureau voie le jour même ce qui s’est passé.</li>
  <li>Des rapports prêts quand arrive un contrôle ou une demande RH.</li>
</ul>
<h2>Pointage et planification ensemble</h2>
<p>Si le planning dit que Jean est sur le chantier A et que le pointage sort ailleurs, il faut que quelqu’un le sache vite. C’est pourquoi <strong>planificateur et pointage doivent vivre dans le même outil</strong>, pas sur deux îles.</p>
<p>Avec SignaPlan l’ouvrier pointe depuis le téléphone et l’entreprise conserve un registre de journée avec traçabilité. Continuez sur la <a href="/fr/soluciones/fichaje-construccion">page produit du pointage</a> ou commencez par <a href="/fr/alta">l’inscription gratuite</a>. Si un contrôle vous inquiète, suivez <a href="/fr/recursos/inspeccion-trabajo-construccion">le contrôle du temps de travail sur chantier</a>.</p>
""",
        },
        'registro-jornada-laboral': {
            'title': 'Registre du temps de travail sur chantier : quitter Excel sans perdre le contrôle',
            'description': (
                'Registre du temps de travail dans le BTP sans modèles Excel : pauses, '
                'traçabilité et rapport pour un contrôle. Guide pratique pour le BTP.'
            ),
            'h1': 'Registre du temps de travail sur chantier',
            'keywords': 'registre du temps de travail, contrôle horaire, registre journée BTP',
            'body_html': """
<p>Le <strong>registre du temps de travail</strong> ce n’est pas seulement « pointer ». C’est pouvoir démontrer horaires, pauses et changements avec une trace claire quand le contrôle ou le salarié le demande.</p>
<p>Si vous cherchez un <strong>registre du temps de travail dans Excel</strong> (modèle, quotidien, temps partiel), le problème n’est pas le fichier : ce sont les copies, les corrections sans trace et le décalage avec ce qui s’est passé sur chantier. Le numériser n’est pas « un autre Excel dans le cloud » ; c’est un registre d’événements qu’on ne réécrit pas.</p>
<h2>Problèmes typiques d’Excel</h2>
<ul>
  <li>Des versions différentes sur chaque PC.</li>
  <li>Des corrections sans historique.</li>
  <li>Des heures qui ne correspondent pas à ce qui s’est passé sur chantier.</li>
</ul>
<h2>Ce qui aide vraiment</h2>
<p>Un registre numérique avec des événements enchaînés, des pauses et, le cas échéant, l’accord du salarié. PDF/CSV exportables pour l’archive ou le conseil.</p>
<p>SignaPlan inclut un registre du temps de travail avec traçabilité lié au pointage sur le terrain. Si une visite d’inspection vous inquiète, lisez <a href="/fr/recursos/inspeccion-trabajo-construccion">ce qu’on vous demande sur chantier</a>. Continuez sur la <a href="/fr/soluciones/registro-jornada-obra">solution de registre du temps de travail</a> ou <a href="/fr/alta">créez un compte gratuit</a>.</p>
""",
        },
        'inspeccion-trabajo-construccion': {
            'title': 'Inspection du travail dans le BTP : le registre du temps de travail sur chantier',
            'description': (
                'Ce qu’on demande souvent lors d’un contrôle du temps de travail chez un constructeur : '
                'entrées, pauses et une trace crédible sur le poste. Comment arrêter d’improviser avec Excel.'
            ),
            'h1': 'Inspection du travail sur chantier : un registre que l’on peut montrer',
            'keywords': 'inspection du travail BTP, registre journée inspection chantier, amende registre BTP',
            'body_html': """
<p>Lors d’une <strong>inspection du travail</strong> dans le BTP, il ne suffit pas de dire « on pointe ». Il faut pouvoir montrer, par personne et par jour, les entrées, les sorties et les pauses avec une trace qui n’est pas un Excel retouché la veille. Ce n’est pas un conseil juridique : c’est ce qui casse sur chantier quand la pointeuse est à la baraque et l’ouvrier sur le poste.</p>
<h2>Pourquoi Excel ne tient pas sur le poste</h2>
<ul>
  <li>Des copies différentes sur chaque PC et des corrections sans historique.</li>
  <li>Des heures « convenues » le vendredi qui ne correspondent pas à ce qui s’est passé sur le terrain.</li>
  <li>Une pointeuse murale qu’on partage ou que personne n’utilise.</li>
</ul>
<h2>Ce qui aide vraiment (sans monter un ERP)</h2>
<ul>
  <li>Le pointage sur le téléphone, là où est le chantier.</li>
  <li>Un registre de journée qu’on ne réécrit pas à la va-vite.</li>
  <li>L’export (PDF/CSV) pour l’archive, le conseil ou la visite.</li>
  <li>Le même système que le planning : si Jean devait être sur le chantier A, on le voit.</li>
</ul>
<p>SignaPlan relie le pointage sur le terrain et un registre avec traçabilité. Créez un compte via <a href="/fr/alta">l’inscription gratuite</a> ou continuez sur <a href="/fr/soluciones/registro-jornada-obra">le registre du temps de travail sur chantier</a> et <a href="/fr/soluciones/fichaje-construccion">le pointage dans le BTP</a>.</p>
""",
        },
        'gestion-flota-obra': {
            'title': 'Gestion de flotte sur chantier : véhicules libres et affectation aux équipes',
            'description': (
                'Comment aligner les véhicules sur le planning et les absences : voitures libres, '
                'affectation du jour et moins de WhatsApp sur « qui prend le fourgon ».'
            ),
            'h1': 'Gestion de flotte pour les entreprises de chantier',
            'keywords': 'gestion flotte chantier, véhicules libres BTP, affectation véhicules chantier',
            'body_html': """
<p>Le fourgon « libre » dont personne ne sait où il est : un classique. Une <strong>gestion de flotte</strong> minimale mais utile répond : quel véhicule va avec quelle équipe, et lesquels restent libres pour une absence ou un changement de chantier.</p>
<h2>Relier flotte et personnel</h2>
<p>Si le planificateur déplace un ouvrier et que le véhicule reste affecté « par habitude », vous perdez du temps chaque matin. La flotte doit regarder le même calendrier que le personnel.</p>
<p>SignaPlan inclut une flotte alignée sur les absences et le planning. <a href="/fr/alta">Essayez gratuitement</a> ou continuez sur la <a href="/fr/soluciones/flota-obra">solution flotte</a>.</p>
""",
        },
        'software-constructoras': {
            'title': 'Logiciel pour PME du BTP : planning et pointage (pas un ERP)',
            'description': (
                'Logiciel pour le BTP : qui va sur quel chantier, contrôle horaire et flotte. '
                'Ce n’est pas un ERP de devis. Inscription gratuite, sans carte.'
            ),
            'h1': 'Logiciel pour le BTP (sans monter un ERP)',
            'keywords': 'logiciel BTP, logiciel chantier, programme gestion construction',
            'body_html': """
<p>Beaucoup de PME du BTP n’ont pas besoin d’un énorme ERP dès le premier jour. Elles ont besoin de contrôler le <strong>quotidien de chantier</strong> : qui va où, qui a pointé et quel véhicule est libre. Si vous cherchez un « ERP BTP gratuit », ceci ne remplace ni les devis ni la facturation : c’est le planning, le pointage et la flotte, et l’inscription ne demande pas de carte.</p>
<h2>Liste rapide</h2>
<ul>
  <li>Le planificateur, un chef de chantier le comprend-il en 10 minutes ?</li>
  <li>Le pointage marche-t-il sur le téléphone de l’ouvrier ?</li>
  <li>Pouvez-vous exporter la journée quand quelqu’un de l’extérieur le demande ?</li>
  <li>La flotte regarde-t-elle le même calendrier ?</li>
</ul>
<p>SignaPlan est pensé exactement pour ça. Commencez par <a href="/fr/alta">l’inscription gratuite</a> (sans carte). Si vous avez aussi Odoo ou un autre ERP, l’intégration se discute comme un projet depuis <a href="/fr/contacto">contact</a>.</p>
""",
        },
    },
}
SOLUTIONS = {
    'en': {
        'fichaje-construccion': {
            'title': 'Time clocking in construction: working-time control on the job, no wall clock',
            'description': (
                'Time clock and working-time control for builders: ID + PIN on the phone. '
                'Clock-ins, breaks and a working-time record. Try SignaPlan free, no card.'
            ),
            'h1': 'Time clocking in construction, built for the job',
            'eyebrow': 'Solution · Time clock',
            'keywords': 'construction time clock, site clock-in, mobile construction working-time control',
            'faq': [
                {
                    'q': 'Do I need to install a clock on every site?',
                    'a': 'No. In SignaPlan the worker clocks in from the phone with ID and PIN. You avoid hardware that gets lost or shared in the site hut.',
                },
                {
                    'q': 'Does it work if several sites are running at once?',
                    'a': 'Yes. Time clocking sits with the planner: you see who is assigned to each site and what they recorded for the day.',
                },
                {
                    'q': 'Does it cover the working-time record?',
                    'a': 'SignaPlan builds a working-time record with a trail (chained events, breaks and export). See also the guide on working-time inspection on site.',
                },
            ],
            'body_html': """
<p>On site the wall clock fails: it gets shared, forgotten or simply is not there. You need <strong>time clocking in construction</strong> that the labourer can use where the job is, and that the office can review the same day.</p>
<h2>What usually breaks with “office” clocking</h2>
<ul>
  <li>A fixed terminal somewhere nobody walks past.</li>
  <li>Excel at the end of the week (“put down what you remember”).</li>
  <li>Clocking in one app and planning in another: the data never talk.</li>
</ul>
<h2>How we set it up in SignaPlan</h2>
<ul>
  <li><strong>Phone in the field:</strong> ID + PIN, built for a quick use.</li>
  <li><strong>Breaks and the day:</strong> not only clock-in / clock-out.</li>
  <li><strong>Same platform as the crew board:</strong> you plan labourers and see clock-ins without jumping tools.</li>
  <li><strong>Trail:</strong> a record aimed at inspection and filing, not at “delete and done”.</li>
</ul>
<h2>Who it is for</h2>
<p>Builders and site companies (SME) already fighting the day with WhatsApp and Excel, who want real clocking without standing up a full ERP in the first month.</p>
<p>Start with a <a href="/alta">free account</a> or also see <a href="/soluciones/registro-jornada-obra">working-time record on site</a>, <a href="/recursos/inspeccion-trabajo-construccion">inspection in construction</a> and the <a href="/soluciones/planificador-personal-obra">crew planner</a>.</p>
""",
        },
        'planificador-personal-obra': {
            'title': 'Site crew planner: the daily board (not a Gantt)',
            'description': (
                'Who goes to which job each day. Board of labourers and site managers by site and date. '
                'Not an ERP. Free signup on SignaPlan, no card.'
            ),
            'h1': 'Site crew planner (a real board)',
            'eyebrow': 'Solution · Planning',
            'keywords': 'site crew planner, labourer board, plan site staff',
            'faq': [
                {
                    'q': 'Is it a project Gantt like an ERP?',
                    'a': 'No. SignaPlan focuses on the operational board: which person is on which site on which days. It does not replace BC3 estimates or certificates.',
                },
                {
                    'q': 'Can the site manager use it?',
                    'a': 'Yes. The idea is that office and site manager see the same board and move assignments without each fighting a different Excel.',
                },
                {
                    'q': 'What about leave?',
                    'a': 'Leave goes on the same calendar. That cuts double bookings and Monday-morning surprises.',
                },
            ],
            'body_html': """
<p>When you search “site planner”, Google fills the page with ERP, Gantt and estimates. If what hurts is <strong>who I send tomorrow to each job</strong>, you need a <strong>site crew planner</strong>: a board, not a price bank.</p>
<h2>The Excel + WhatsApp problem</h2>
<ul>
  <li>Different versions on the manager’s PC and in admin.</li>
  <li>Last-minute changes that do not reach everyone.</li>
  <li>Nobody sees conflicts (two sites, sick leave, van) until it is already late.</li>
</ul>
<h2>What SignaPlan does here</h2>
<ul>
  <li>Assign people to sites by dates, with a clear view.</li>
  <li>Spot clashes before the labourer is in the wrong place.</li>
  <li>Connect to <a href="/soluciones/fichaje-construccion">time clocking</a> and <a href="/soluciones/flota-obra">fleet</a> when you need them.</li>
</ul>
<h2>It is not a full ERP (and that is fine)</h2>
<p>If you need BC3, certificates and invoicing, there are tools for that. SignaPlan covers the <em>day-to-day of people and vehicles</em>. You can start here and link an ERP later if you need to.</p>
<p><a href="/alta">Create a free account</a> · <a href="/recursos/cuadrante-personal-obra">Guide: site crew board</a></p>
""",
        },
        'registro-jornada-obra': {
            'title': 'Working-time record on site: ready for an inspection',
            'description': (
                'Working-time record for builders: clock-in on the job, breaks '
                'and export. No endless Excel. Start free on SignaPlan.'
            ),
            'h1': 'Working-time record on site with a trail',
            'eyebrow': 'Solution · Compliance',
            'keywords': 'site working-time record, construction timesheet record, builder working-time control',
            'faq': [
                {
                    'q': 'Is Excel still enough?',
                    'a': 'The duty to record working time has existed since 2019. The framework is moving towards more reliable digital systems. A shared Excel is usually fragile in an inspection.',
                },
                {
                    'q': 'What does SignaPlan add besides clocking in?',
                    'a': 'An event ledger with a trail, breaks and export. Tied to field clock-in and the crew board, not as a separate island.',
                },
                {
                    'q': 'How long should data be kept?',
                    'a': 'You must keep the records for the legal period (usually years). Export and file as your adviser says; SignaPlan gives you the digital base for the day-to-day.',
                },
            ],
            'body_html': """
<p>In construction the working day does not pass through a fixed office. That is why the <strong>working-time record on site</strong> is one of the most searched pains: you have to show clock-ins, clock-outs and changes with a credible trail.</p>
<h2>Why there is more noise now</h2>
<p>On top of the duty already in force, the public debate about a <strong>digital and unalterable</strong> record is pushing many builders to leave paper and Excel. Better to get ahead with a system you can actually use in the field.</p>
<h2>What to ask of a serious tool</h2>
<ul>
  <li>A daily record per worker (start / end, and breaks if they apply).</li>
  <li>That it is not trivial to “delete and rewrite” without leaving a mark.</li>
  <li>Export for inspection or your adviser.</li>
  <li>That the labourer can clock in on site, not only in the office.</li>
</ul>
<h2>SignaPlan at this point</h2>
<p>Clock-ins feed a record with a trail. It fits with <a href="/soluciones/fichaje-construccion">time clocking in construction</a> and with the <a href="/soluciones/planificador-personal-obra">crew board</a>.</p>
<p><a href="/alta">Start free</a> · <a href="/recursos/inspeccion-trabajo-construccion">Guide: inspection on site</a></p>
""",
        },
        'flota-obra': {
            'title': 'Site fleet: free vehicles and assignment to crew',
            'description': (
                'Manage site vans and cars lined up with the crew board and '
                'leave. Fewer WhatsApps about ‘who takes the van’. SignaPlan.'
            ),
            'h1': 'Site fleet lined up with the crew',
            'eyebrow': 'Solution · Fleet',
            'keywords': 'site fleet, free cars builder, site vehicle assignment',
            'faq': [
                {
                    'q': 'Is it fleet GPS?',
                    'a': 'No. SignaPlan focuses on operational assignment: which vehicle goes with which crew and which ones are free because of leave or a site change.',
                },
                {
                    'q': 'Why tie it to the crew board?',
                    'a': 'If you move labourers and the van stays assigned ‘because that is how we do it’, you lose mornings. The fleet has to look at the same calendar as the crew.',
                },
            ],
            'body_html': """
<p>The van that is “free” and nobody knows where it is: a site classic. A <strong>fleet setup</strong> that is small but useful answers: which vehicle goes with which crew, and what is free when there is sick leave or a job change.</p>
<h2>Without people, the fleet lies</h2>
<p>Car lists in a separate Excel do not see leave or the crew board. SignaPlan ties vehicles to the same world as the <a href="/soluciones/planificador-personal-obra">crew planner</a>.</p>
<h2>Who it is for</h2>
<p>Companies with several vans or company cars that already suffer the morning chaos of “who takes which one?”.</p>
<p><a href="/alta">Try SignaPlan</a> · <a href="/soluciones/">See all solutions</a></p>
""",
        },
    },
    'pt': {
        'fichaje-construccion': {
            'title': 'Ponto na construção: controlo horário na frente, sem relógio de parede',
            'description': (
                'Ponto e controlo horário para construtoras: documento + PIN no telemóvel. '
                'Entradas, pausas e registo de jornada. Experimente o SignaPlan grátis, sem cartão.'
            ),
            'h1': 'Ponto na construção pensado para a frente',
            'eyebrow': 'Solução · Ponto',
            'keywords': 'ponto construção, ponto obra, controlo horário construção telemóvel',
            'faq': [
                {
                    'q': 'É preciso instalar um relógio em cada obra?',
                    'a': 'Não. No SignaPlan o operário regista o ponto a partir do telemóvel com identificação e PIN. Evita hardware que se perde ou se partilha na casota.',
                },
                {
                    'q': 'Serve se há várias obras ao mesmo tempo?',
                    'a': 'Sim. O ponto convive com o planeador: vê quem está atribuído a cada obra e o que registou na jornada.',
                },
                {
                    'q': 'Cumpre o registo de jornada?',
                    'a': 'O SignaPlan gera um registo de jornada com rasto (eventos encadeados, pausas e exportação). Consulte também o guia de inspeção de jornada em obra.',
                },
            ],
            'body_html': """
<p>Em obra o relógio de parede falha: partilha-se, esquece-se ou simplesmente não está. Precisa de um <strong>ponto na construção</strong> que o operário possa usar onde estiver a frente, e que o escritório possa rever no mesmo dia.</p>
<h2>O que costuma partir-se com o ponto “de escritório”</h2>
<ul>
  <li>Terminal fixo num sítio por onde ninguém passa.</li>
  <li>Excel no fim da semana (“ponha o que se lembrar”).</li>
  <li>Ponto numa app e planeamento noutra: os dados não se falam.</li>
</ul>
<h2>Como o colocamos no SignaPlan</h2>
<ul>
  <li><strong>Telemóvel no campo:</strong> identificação + PIN, pensado para uso rápido.</li>
  <li><strong>Pausas e jornada:</strong> não só entrada/saída.</li>
  <li><strong>A mesma plataforma que o quadro:</strong> planeia operários e vê o ponto sem saltar de ferramenta.</li>
  <li><strong>Rasto:</strong> registo orientado a inspeção e arquivo, não a “apagar e já está”.</li>
</ul>
<h2>Para quem é</h2>
<p>Construtoras e empresas de obra (PME) que já lutam o dia a dia com WhatsApp e Excel, e querem ponto a sério sem montar um ERP inteiro no primeiro mês.</p>
<p>Comece com <a href="/pt/alta">conta gratuita</a> ou veja também <a href="/pt/soluciones/registro-jornada-obra">registo de jornada em obra</a>, <a href="/pt/recursos/inspeccion-trabajo-construccion">inspeção na construção</a> e o <a href="/pt/soluciones/planificador-personal-obra">planeador de pessoal</a>.</p>
""",
        },
        'planificador-personal-obra': {
            'title': 'Planeador de pessoal de obra: o quadro diário (não um Gantt)',
            'description': (
                'Quem vai a cada frente cada dia. Quadro de operários e chefes por obra e data. '
                'Não é um ERP. Alta gratuita no SignaPlan, sem cartão.'
            ),
            'h1': 'Planeador de pessoal de obra (quadro a sério)',
            'eyebrow': 'Solução · Planeamento',
            'keywords': 'planeador pessoal obra, quadro operários, planear obras pessoal',
            'faq': [
                {
                    'q': 'É um Gantt de projeto tipo ERP?',
                    'a': 'Não. O SignaPlan centra-se no quadro operativo: que pessoa está em que obra em que dias. Não substitui orçamentos BC3 nem certificações.',
                },
                {
                    'q': 'Pode usá-lo o chefe de obra?',
                    'a': 'Sim. A ideia é que escritório e chefe vejam o mesmo painel e movam atribuições sem cada um lutar com um Excel diferente.',
                },
                {
                    'q': 'O que acontece com as ausências?',
                    'a': 'As ausências entram no mesmo calendário. Assim reduz duplas atribuições e surpresas à segunda de manhã.',
                },
            ],
            'body_html': """
<p>Quando procura “planeador de obra”, o Google enche-o de ERP, Gantt e orçamentos. Se o que dói é <strong>quem mando amanhã a cada frente</strong>, precisa de um <strong>planeador de pessoal de obra</strong>: um quadro, não um banco de preços.</p>
<h2>O problema do Excel + WhatsApp</h2>
<ul>
  <li>Versões distintas no PC do chefe e no da administração.</li>
  <li>Alterações de última hora que não chegam a todos.</li>
  <li>Ninguém vê conflitos (dupla obra, baixa, carro) até já ser tarde.</li>
</ul>
<h2>O que o SignaPlan faz aqui</h2>
<ul>
  <li>Atribuir pessoal a obras por datas, com vista clara.</li>
  <li>Detetar choques antes de o operário estar no sítio errado.</li>
  <li>Ligar ao <a href="/pt/soluciones/fichaje-construccion">ponto</a> e à <a href="/pt/soluciones/flota-obra">frota</a> quando precisar.</li>
</ul>
<h2>Não é um ERP completo (e está bem)</h2>
<p>Se precisa de BC3, certificações e faturação, há ferramentas para isso. O SignaPlan cobre o <em>dia a dia de gente e veículos</em>. Pode começar por aqui e ligar um ERP depois se for preciso.</p>
<p><a href="/pt/alta">Criar conta gratuita</a> · <a href="/pt/recursos/cuadrante-personal-obra">Guia: quadro de pessoal</a></p>
""",
        },
        'registro-jornada-obra': {
            'title': 'Registo de jornada em obra: pronto para uma inspeção',
            'description': (
                'Registo de jornada laboral para construtoras: ponto na frente, pausas '
                'e exportação. Sem Excel eterno. Comece grátis no SignaPlan.'
            ),
            'h1': 'Registo de jornada em obra com rasto',
            'eyebrow': 'Solução · Cumprimento',
            'keywords': 'registo jornada obra, registo jornada construção, controlo horário construtora',
            'faq': [
                {
                    'q': 'Ainda chega o Excel?',
                    'a': 'A obrigação de registar a jornada existe desde 2019. O enquadramento caminha para sistemas mais fiáveis e digitais. Um Excel partilhado costuma ser frágil perante inspeção.',
                },
                {
                    'q': 'O que acrescenta o SignaPlan além de picar o ponto?',
                    'a': 'Um livro de eventos com rasto, pausas e exportação. Ligado ao ponto no campo e ao quadro, não como ilha à parte.',
                },
                {
                    'q': 'Conservação de dados?',
                    'a': 'Deve conservar os registos o prazo legal (habitualmente anos). Exporte e arquive segundo a sua assessoria; o SignaPlan dá-lhe a base digital do dia a dia.',
                },
            ],
            'body_html': """
<p>Na construção a jornada não passa por um escritório fixo. Por isso o <strong>registo de jornada em obra</strong> é uma das dores mais procuradas: é preciso demonstrar entradas, saídas e alterações com um rasto credível.</p>
<h2>Porque é que agora há mais ruído</h2>
<p>Além da obrigação já em vigor, o debate público sobre um registo <strong>digital e inalterável</strong> empurra muitas construtoras a deixar o papel e o Excel. Convém antecipar-se com um sistema usável no campo.</p>
<h2>O que pedir a uma ferramenta a sério</h2>
<ul>
  <li>Registo diário por trabalhador (início / fim, e pausas se aplicarem).</li>
  <li>Que não seja trivial “apagar e reescrever” sem deixar rasto.</li>
  <li>Exportação para inspeção ou assessoria.</li>
  <li>Que o operário possa picar o ponto em obra, não só no escritório.</li>
</ul>
<h2>O SignaPlan neste ponto</h2>
<p>O ponto alimenta um registo com rasto. Encaixa com o <a href="/pt/soluciones/fichaje-construccion">ponto na construção</a> e com o <a href="/pt/soluciones/planificador-personal-obra">quadro</a>.</p>
<p><a href="/pt/alta">Começar grátis</a> · <a href="/pt/recursos/inspeccion-trabajo-construccion">Guia: inspeção em obra</a></p>
""",
        },
        'flota-obra': {
            'title': 'Frota em obra: carros livres e atribuição ao pessoal',
            'description': (
                'Gira carrinhas e carros de obra alinhados com o quadro e as '
                'ausências. Menos WhatsApps de ‘quem leva o carro’. SignaPlan.'
            ),
            'h1': 'Frota de obra alinhada com o pessoal',
            'eyebrow': 'Solução · Frota',
            'keywords': 'frota obra, carros livres construtora, atribuição veículos obra',
            'faq': [
                {
                    'q': 'É um GPS de frota?',
                    'a': 'Não. O SignaPlan centra-se na atribuição operativa: que veículo vai com que equipa e quais ficam livres por ausência ou mudança de obra.',
                },
                {
                    'q': 'Porque ligá-lo ao quadro?',
                    'a': 'Se move operários e o carro continua ‘por costume’, perde manhãs. A frota deve olhar para o mesmo calendário que o pessoal.',
                },
            ],
            'body_html': """
<p>A carrinha “livre” que ninguém sabe onde está é um clássico de obra. Uma <strong>gestão de frota</strong> mínima mas útil responde: que veículo vai com que equipa, e o que fica livre quando há baixa ou mudança de frente.</p>
<h2>Sem integrar pessoal, a frota mente</h2>
<p>Listas de carros num Excel à parte não veem ausências nem o quadro. O SignaPlan liga veículos ao mesmo mundo que o <a href="/pt/soluciones/planificador-personal-obra">planeador de pessoal</a>.</p>
<h2>Para quem</h2>
<p>Empresas com várias carrinhas ou carros de empresa que já sofrem o caos matinal de “quem leva qual?”.</p>
<p><a href="/pt/alta">Provar o SignaPlan</a> · <a href="/pt/soluciones/">Ver todas as soluções</a></p>
""",
        },
    },
    'fr': {
        'fichaje-construccion': {
            'title': 'Pointage dans le BTP : contrôle horaire sur le poste, sans pointeuse murale',
            'description': (
                'Pointage et contrôle horaire pour le BTP : pièce d’identité + PIN sur le téléphone. '
                'Entrées, pauses et registre de journée. Essayez SignaPlan gratuitement, sans carte.'
            ),
            'h1': 'Pointage dans le BTP pensé pour le poste',
            'eyebrow': 'Solution · Pointage',
            'keywords': 'pointage BTP, pointage chantier, contrôle horaire construction mobile',
            'faq': [
                {
                    'q': 'Faut-il installer une pointeuse sur chaque chantier ?',
                    'a': 'Non. Dans SignaPlan l’ouvrier pointe depuis le téléphone avec identification et PIN. Vous évitez du matériel qui se perd ou se partage à la baraque.',
                },
                {
                    'q': 'Ça marche s’il y a plusieurs chantiers en même temps ?',
                    'a': 'Oui. Le pointage vit avec le planificateur : vous voyez qui est affecté à chaque chantier et ce qu’il a enregistré pour la journée.',
                },
                {
                    'q': 'Est-ce que ça couvre le registre du temps de travail ?',
                    'a': 'SignaPlan génère un registre de journée avec traçabilité (événements enchaînés, pauses et export). Consultez aussi le guide sur le contrôle du temps de travail sur chantier.',
                },
            ],
            'body_html': """
<p>Sur chantier la pointeuse murale échoue : on la partage, on l’oublie, ou elle n’est simplement pas là. Vous avez besoin d’un <strong>pointage dans le BTP</strong> que l’ouvrier puisse utiliser là où est le poste, et que le bureau puisse relire le jour même.</p>
<h2>Ce qui casse souvent avec le pointage « de bureau »</h2>
<ul>
  <li>Un terminal fixe quelque part où personne ne passe.</li>
  <li>Excel en fin de semaine (« mets ce dont tu te souviens »).</li>
  <li>Le pointage dans une app et la planification dans une autre : les données ne se parlent pas.</li>
</ul>
<h2>Comment on le pose dans SignaPlan</h2>
<ul>
  <li><strong>Téléphone sur le terrain :</strong> identification + PIN, pensé pour un usage rapide.</li>
  <li><strong>Pauses et journée :</strong> pas seulement entrée/sortie.</li>
  <li><strong>La même plateforme que le planning :</strong> vous planifiez les ouvriers et voyez le pointage sans changer d’outil.</li>
  <li><strong>Traçabilité :</strong> un registre orienté contrôle et archive, pas « supprimer et c’est bon ».</li>
</ul>
<h2>Pour qui c’est</h2>
<p>Entreprises de BTP (PME) qui se battent déjà au quotidien avec WhatsApp et Excel, et qui veulent un vrai pointage sans monter un ERP entier le premier mois.</p>
<p>Commencez avec un <a href="/fr/alta">compte gratuit</a> ou voyez aussi <a href="/fr/soluciones/registro-jornada-obra">le registre du temps de travail sur chantier</a>, <a href="/fr/recursos/inspeccion-trabajo-construccion">le contrôle dans le BTP</a> et le <a href="/fr/soluciones/planificador-personal-obra">planificateur d’équipe</a>.</p>
""",
        },
        'planificador-personal-obra': {
            'title': 'Planificateur d’équipe de chantier : le tableau quotidien (pas un Gantt)',
            'description': (
                'Qui va sur quel poste chaque jour. Planning des ouvriers et chefs par chantier et date. '
                'Ce n’est pas un ERP. Inscription gratuite sur SignaPlan, sans carte.'
            ),
            'h1': 'Planificateur d’équipe de chantier (un vrai tableau)',
            'eyebrow': 'Solution · Planning',
            'keywords': 'planificateur équipe chantier, planning ouvriers, planifier personnel chantier',
            'faq': [
                {
                    'q': 'C’est un Gantt de projet type ERP ?',
                    'a': 'Non. SignaPlan se concentre sur le tableau opérationnel : quelle personne est sur quel chantier quels jours. Ça ne remplace ni les devis BC3 ni les situations.',
                },
                {
                    'q': 'Le chef de chantier peut l’utiliser ?',
                    'a': 'Oui. L’idée est que le bureau et le chef voient le même tableau et déplacent les affectations sans se battre chacun avec un Excel différent.',
                },
                {
                    'q': 'Et les absences ?',
                    'a': 'Les absences entrent dans le même calendrier. Ça réduit les doubles affectations et les surprises du lundi matin.',
                },
            ],
            'body_html': """
<p>Quand vous cherchez « planificateur de chantier », Google vous remplit d’ERP, de Gantt et de devis. Si ce qui fait mal c’est <strong>qui j’envoie demain sur chaque poste</strong>, il vous faut un <strong>planificateur d’équipe de chantier</strong> : un tableau, pas un bordereau de prix.</p>
<h2>Le problème Excel + WhatsApp</h2>
<ul>
  <li>Des versions différentes sur le PC du chef et sur celui de l’admin.</li>
  <li>Des changements de dernière minute qui n’arrivent pas à tout le monde.</li>
  <li>Personne ne voit les conflits (deux chantiers, un arrêt, un véhicule) avant qu’il ne soit trop tard.</li>
</ul>
<h2>Ce que SignaPlan fait ici</h2>
<ul>
  <li>Affecter le personnel aux chantiers par dates, avec une vue claire.</li>
  <li>Repérer les collisions avant que l’ouvrier soit au mauvais endroit.</li>
  <li>Relier le <a href="/fr/soluciones/fichaje-construccion">pointage</a> et la <a href="/fr/soluciones/flota-obra">flotte</a> quand vous en avez besoin.</li>
</ul>
<h2>Ce n’est pas un ERP complet (et c’est très bien)</h2>
<p>Si vous avez besoin de BC3, de situations et de facturation, il existe des outils pour ça. SignaPlan couvre le <em>quotidien des gens et des véhicules</em>. Vous pouvez commencer ici et relier un ERP plus tard si besoin.</p>
<p><a href="/fr/alta">Créer un compte gratuit</a> · <a href="/fr/recursos/cuadrante-personal-obra">Guide : planning d’équipe</a></p>
""",
        },
        'registro-jornada-obra': {
            'title': 'Registre du temps de travail sur chantier : prêt pour un contrôle',
            'description': (
                'Registre du temps de travail pour le BTP : pointage sur le poste, pauses '
                'et export. Sans Excel éternel. Commencez gratuitement sur SignaPlan.'
            ),
            'h1': 'Registre du temps de travail sur chantier avec traçabilité',
            'eyebrow': 'Solution · Conformité',
            'keywords': 'registre journée chantier, registre temps de travail BTP, contrôle horaire constructeur',
            'faq': [
                {
                    'q': 'Excel suffit-il encore ?',
                    'a': 'L’obligation d’enregistrer le temps de travail existe depuis 2019. Le cadre va vers des systèmes plus fiables et numériques. Un Excel partagé est souvent fragile face à un contrôle.',
                },
                {
                    'q': 'Qu’apporte SignaPlan en plus du pointage ?',
                    'a': 'Un registre d’événements avec traçabilité, pauses et export. Lié au pointage sur le terrain et au planning, pas comme une île à part.',
                },
                {
                    'q': 'Conservation des données ?',
                    'a': 'Vous devez conserver les enregistrements le délai légal (en général des années). Exportez et archivez selon votre conseil ; SignaPlan vous donne la base numérique du quotidien.',
                },
            ],
            'body_html': """
<p>Dans le BTP, la journée ne passe pas par un bureau fixe. C’est pourquoi le <strong>registre du temps de travail sur chantier</strong> est l’une des douleurs les plus cherchées : il faut démontrer entrées, sorties et changements avec une trace crédible.</p>
<h2>Pourquoi il y a plus de bruit maintenant</h2>
<p>En plus de l’obligation déjà en vigueur, le débat public sur un registre <strong>numérique et inaltérable</strong> pousse beaucoup d’entreprises de BTP à quitter le papier et Excel. Mieux vaut anticiper avec un système utilisable sur le terrain.</p>
<h2>Quoi demander à un outil sérieux</h2>
<ul>
  <li>Un enregistrement quotidien par salarié (début / fin, et pauses si elles s’appliquent).</li>
  <li>Que « supprimer et réécrire » sans laisser de trace ne soit pas trivial.</li>
  <li>L’export pour un contrôle ou le conseil.</li>
  <li>Que l’ouvrier puisse pointer sur le chantier, pas seulement au bureau.</li>
</ul>
<h2>SignaPlan à ce stade</h2>
<p>Le pointage alimente un registre avec traçabilité. Ça s’emboîte avec le <a href="/fr/soluciones/fichaje-construccion">pointage dans le BTP</a> et avec le <a href="/fr/soluciones/planificador-personal-obra">planning</a>.</p>
<p><a href="/fr/alta">Commencer gratuitement</a> · <a href="/fr/recursos/inspeccion-trabajo-construccion">Guide : contrôle sur chantier</a></p>
""",
        },
        'flota-obra': {
            'title': 'Flotte de chantier : véhicules libres et affectation aux équipes',
            'description': (
                'Gérez fourgons et voitures de chantier alignés sur le planning et les '
                'absences. Moins de WhatsApp « qui prend la voiture ». SignaPlan.'
            ),
            'h1': 'Flotte de chantier alignée sur le personnel',
            'eyebrow': 'Solution · Flotte',
            'keywords': 'flotte chantier, véhicules libres BTP, affectation véhicules chantier',
            'faq': [
                {
                    'q': 'C’est un GPS de flotte ?',
                    'a': 'Non. SignaPlan se concentre sur l’affectation opérationnelle : quel véhicule va avec quelle équipe et lesquels restent libres pour une absence ou un changement de chantier.',
                },
                {
                    'q': 'Pourquoi le lier au planning ?',
                    'a': 'Si vous déplacez des ouvriers et que le véhicule reste « par habitude », vous perdez des matins. La flotte doit regarder le même calendrier que le personnel.',
                },
            ],
            'body_html': """
<p>Le fourgon « libre » dont personne ne sait où il est : un classique de chantier. Une <strong>gestion de flotte</strong> minimale mais utile répond : quel véhicule va avec quelle équipe, et ce qui reste libre quand il y a un arrêt ou un changement de poste.</p>
<h2>Sans le personnel, la flotte ment</h2>
<p>Des listes de voitures dans un Excel à part ne voient ni les absences ni le planning. SignaPlan relie les véhicules au même monde que le <a href="/fr/soluciones/planificador-personal-obra">planificateur d’équipe</a>.</p>
<h2>Pour qui</h2>
<p>Les entreprises avec plusieurs fourgons ou voitures de société qui subissent déjà le chaos matinal du « qui prend laquelle ? ».</p>
<p><a href="/fr/alta">Essayer SignaPlan</a> · <a href="/fr/soluciones/">Voir toutes les solutions</a></p>
""",
        },
    },
}

