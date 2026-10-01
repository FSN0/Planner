"""Páginas /soluciones/ — hub SEO por problema (calidad, no granja)."""

from __future__ import annotations

SOLUTIONS = {
    "fichaje-construccion": {
        "title": "Fichaje en construcción: control horario en el tajo, sin reloj de pared",
        "description": (
            "Fichaje y control horario para constructoras: DNI + PIN en el móvil. "
            "Entradas, pausas y registro de jornada. Prueba SignaPlan gratis, sin tarjeta."
        ),
        "h1": "Fichaje en construcción pensado para el tajo",
        "eyebrow": "Solución · Fichaje",
        "updated": "2026-08-27",
        "priority": 1,
        "keywords": "fichaje construcción, fichaje obra, control horario construcción móvil",
        "faq": [
            {
                "q": "¿Hace falta instalar un reloj en cada obra?",
                "a": "No. En SignaPlan el operario ficha desde el móvil con identificación y PIN. Evitas hardware que se pierde o se comparte en caseta.",
            },
            {
                "q": "¿Sirve si hay varias obras a la vez?",
                "a": "Sí. El fichaje convive con el planificador: ves quién está asignado a cada obra y qué ha registrado en jornada.",
            },
            {
                "q": "¿Cumple con el registro de jornada?",
                "a": "SignaPlan genera un registro de jornada con trazabilidad (eventos encadenados, pausas y exportación). Consulta también la guía de inspección de jornada en obra.",
            },
        ],
        "body_html": """
<p>En obra el reloj de pared falla: se comparte, se olvida o simplemente no está.
Necesitas un <strong>fichaje en construcción</strong> que el peón pueda usar
donde esté el tajo, y que la oficina pueda revisar el mismo día. En SignaPlan
es DNI + PIN en el móvil: sin terminal en caseta.</p>

<h2>Qué suele romperse con el fichaje “de oficina”</h2>
<ul>
  <li>Terminal fijo en un sitio al que nadie pasa.</li>
  <li>Excel al final de la semana (“pon lo que te acuerdes”).</li>
  <li>Fichaje en una app y planificación en otra: los datos no se hablan.</li>
</ul>

<h2>Cómo lo planteamos en SignaPlan</h2>
<ul>
  <li><strong>Móvil en campo:</strong> identificación + PIN, pensado para uso rápido.</li>
  <li><strong>Pausas y jornada:</strong> no solo entrada/salida.</li>
  <li><strong>Misma plataforma que el cuadrante:</strong> ves quién está asignado y qué ha registrado.</li>
  <li><strong>Trazabilidad:</strong> registro orientado a inspección, no a “borrar y ya”.</li>
</ul>

<h2>Para quién sí / no</h2>
<p><strong>Sí:</strong> constructoras PYME que ya pelean el día con WhatsApp y quieren
fichaje real sin montar un ERP el primer mes.</p>
<p><strong>No:</strong> si buscas un reloj biométrico de pared o un control de presencia
de oficina (torno, tarjeta). Esto está pensado para el tajo.</p>

<p>Empieza con <a href="/alta">cuenta gratuita</a> o mira
<a href="/soluciones/registro-jornada-obra">registro de jornada en obra</a>,
<a href="/recursos/inspeccion-trabajo-construccion">inspección en construcción</a>
y el <a href="/soluciones/planificador-personal-obra">planificador de personal</a>.</p>
""",
    },
    "planificador-personal-obra": {
        "title": "Planificador de personal de obra: el cuadrante diario (no un Gantt)",
        "description": (
            "Quién va a cada tajo cada día. Cuadrante de peones y jefes por obra y fecha. "
            "No es un ERP. Alta gratuita en SignaPlan, sin tarjeta."
        ),
        "h1": "Planificador de personal de obra (cuadrante real)",
        "eyebrow": "Solución · Planificación",
        "updated": "2026-08-27",
        "priority": 2,
        "keywords": "planificador personal obra, cuadrante peones, planificar obras personal",
        "faq": [
            {
                "q": "¿Es un Gantt de proyecto tipo ERP?",
                "a": "No. SignaPlan se centra en el cuadrante operativo: qué persona está en qué obra qué días. No sustituye presupuestos BC3 ni certificaciones.",
            },
            {
                "q": "¿Puede usarlo el jefe de obra?",
                "a": "Sí. La idea es que oficina y jefe vean el mismo tablero y muevan asignaciones sin pelearse con un Excel distinto cada uno.",
            },
            {
                "q": "¿Qué pasa con las ausencias?",
                "a": "Las ausencias entran en el mismo calendario. Así reduces dobles asignaciones y sorpresas el lunes por la mañana.",
            },
        ],
        "body_html": """
<p>Cuando buscas “planificador de obra”, Google te llena de ERP, Gantt y presupuestos.
Si lo que te duele es <strong>quién mando mañana a cada tajo</strong>, necesitas un
<strong>planificador de personal de obra</strong>: un cuadrante, no un banco de precios.
SignaPlan es exactamente ese tablero.</p>

<h2>Qué hace SignaPlan (no un Gantt)</h2>
<ul>
  <li>Asignar peones y jefes a obras por fechas, en un único calendario.</li>
  <li>Que oficina y jefe de obra vean la misma versión: se acabó el «final_v7.xlsx».</li>
  <li>Ver choques (doble obra, baja, vacaciones) antes de que salga el primer coche.</li>
  <li>Ausencias en el mismo sitio que las asignaciones, no en otro Excel.</li>
  <li>Cuando lo necesites: <a href="/soluciones/fichaje-construccion">fichaje</a> y
      <a href="/soluciones/flota-obra">flota</a> sobre el mismo calendario.</li>
</ul>

<h2>Para quién sí / para quién no</h2>
<p><strong>Sí:</strong> constructora o empresa de obra PYME (aprox. 5–80 personas en
campo) que hoy reparte gente con WhatsApp y hojas. El jefe tiene que poder mover a
alguien sin un curso.</p>
<p><strong>No:</strong> si lo que buscas es presupuestar en BC3, certificar partidas o
llevar la contabilidad. Eso es un ERP. SignaPlan no lo sustituye; puede convivir.</p>

<h2>Cómo se usa el primer día</h2>
<ol>
  <li>Alta gratuita, sin tarjeta. Espacio propio (tuempresa.signaplan.com).</li>
  <li>Obras y personal (aunque sea un listado corto).</li>
  <li>Cuadrante a 2–4 semanas. Regla: los cambios se hacen aquí, no solo por mensaje.</li>
</ol>

<h2>El problema del Excel + WhatsApp</h2>
<ul>
  <li>Versiones distintas en el PC del jefe y en el de administración.</li>
  <li>Cambios de última hora que no llegan a quien conduce.</li>
  <li>Nadie ve conflictos hasta que el tajo ya está a medias.</li>
</ul>

<p><a href="/alta">Crear cuenta gratuita</a> ·
Guía (qué es un planificador de obra, no el producto):
<a href="/recursos/planificador-de-obra">planificador de obra</a> ·
<a href="/recursos/cuadrante-personal-obra">cuadrante de personal</a></p>
""",
    },
    "registro-jornada-obra": {
        "title": "Registro de jornada en obra: listo para una inspección",
        "description": (
            "Registro de jornada laboral para constructoras: fichaje en el tajo, pausas "
            "y exportación. Sin Excel eterno. Empieza gratis en SignaPlan."
        ),
        "h1": "Registro de jornada en obra con trazabilidad",
        "eyebrow": "Solución · Cumplimiento",
        "updated": "2026-08-27",
        "priority": 1,
        "keywords": "registro jornada obra, registro jornada construcción, control horario constructora",
        "faq": [
            {
                "q": "¿Sigue bastando el Excel?",
                "a": "La obligación de registrar jornada existe desde 2019. El marco va hacia sistemas más fiables y digitales. Un Excel compartido suele ser frágil ante inspección.",
            },
            {
                "q": "¿Qué aporta SignaPlan además de fichar?",
                "a": "Un libro de eventos con trazabilidad, pausas y exportación. Ligado al fichaje en campo y al cuadrante, no como isla aparte.",
            },
            {
                "q": "¿Conservación de datos?",
                "a": "Debes conservar los registros el plazo legal (habitualmente años). Exporta e archiva según tu asesoría; SignaPlan te da la base digital del día a día.",
            },
        ],
        "body_html": """
<p>En construcción la jornada no pasa por una oficina fija. Por eso el
<strong>registro de jornada en obra</strong> es uno de los dolores más buscados:
hay que demostrar entradas, salidas y cambios con una traza creíble. SignaPlan
genera un libro de eventos ligado al fichaje en campo, no un Excel retocado el
viernes.</p>

<h2>Por qué ahora hay más ruido</h2>
<p>Además de la obligación ya vigente, el debate público sobre registro
<strong>digital e inalterable</strong> empuja a muchas constructoras a dejar el
papel. Conviene adelantarse con un sistema usable en el tajo.</p>

<h2>Qué pedirle a una herramienta seria</h2>
<ul>
  <li>Registro diario por trabajador (inicio / fin, y pausas si aplican).</li>
  <li>Que no sea trivial “borrar y reescribir” sin dejar huella.</li>
  <li>Exportación para inspección o asesoría (PDF/CSV).</li>
  <li>Que el peón fiche en obra, no solo en oficina.</li>
</ul>

<h2>SignaPlan en este punto</h2>
<p>El fichaje alimenta un registro con trazabilidad (eventos encadenados). Encaja con el
<a href="/soluciones/fichaje-construccion">fichaje en construcción</a> y con el
<a href="/soluciones/planificador-personal-obra">cuadrante</a>.</p>
<p>Esto no es asesoramiento jurídico: es la herramienta. El cumplimiento de plazos
de conservación y de información a la plantilla es de la empresa y su asesoría.</p>

<p><a href="/alta">Empezar gratis</a> ·
<a href="/recursos/inspeccion-trabajo-construccion">Guía: inspección en obra</a> ·
<a href="/recursos/registro-jornada-laboral">Guía: registro de jornada</a></p>
""",
    },
    "flota-obra": {
        "title": "Flota en obra: coches libres y asignación al personal",
        "description": (
            "Gestiona furgonetas y coches de obra alineados con el cuadrante y las "
            "ausencias. Menos WhatsApps de ‘quién se lleva el coche’. SignaPlan."
        ),
        "h1": "Flota de obra alineada con el personal",
        "eyebrow": "Solución · Flota",
        "updated": "2026-08-27",
        "priority": 3,
        "keywords": "flota obra, coches libres constructora, asignación vehículos obra",
        "faq": [
            {
                "q": "¿Es un GPS de flota?",
                "a": "No. SignaPlan se centra en asignación operativa: qué vehículo va con qué equipo y cuáles quedan libres por ausencia o cambio de obra.",
            },
            {
                "q": "¿Por qué unirlo al cuadrante?",
                "a": "Si mueves peones y el coche sigue ‘por costumbre’, pierdes mañanas. La flota debe mirar el mismo calendario que el personal.",
            },
        ],
        "body_html": """
<p>La furgoneta “libre” que nadie sabe dónde está es un clásico de obra.
Una <strong>gestión de flota</strong> mínima pero útil responde: qué vehículo
va con qué equipo, y qué queda libre cuando hay baja o cambio de tajo.
SignaPlan no es un GPS: es asignación operativa sobre el mismo calendario
que el personal.</p>

<h2>Sin integrar personal, la flota miente</h2>
<p>Listas de coches en un Excel aparte no ven ausencias ni el cuadrante.
Si mueves peones y el coche sigue «por costumbre», pierdes mañanas. La flota
debe mirar el mismo mundo que el
<a href="/soluciones/planificador-personal-obra">planificador de personal</a>.</p>

<h2>Para quién</h2>
<p>Empresas con varias furgonetas o coches de empresa que ya sufren el caos
matutino de “¿quién se lleva cuál?”. Si solo tenéis un vehículo, esto puede
esperar: empieza por el cuadrante.</p>

<p><a href="/alta">Probar SignaPlan</a> ·
<a href="/recursos/gestion-flota-obra">Guía: gestión de flota en obra</a> ·
<a href="/soluciones/">Ver todas las soluciones</a></p>
""",
    },
}


def list_solutions(locale: str = None):
    from app.marketing.seo_i18n import localize_solution
    from app.services.i18n_service import get_locale

    loc = locale or get_locale()
    items = []
    for slug, meta in SOLUTIONS.items():
        localized = localize_solution(meta, slug, loc)
        items.append(
            {
                "slug": slug,
                **{k: v for k, v in localized.items() if k not in ("body_html", "faq")},
            }
        )
    return sorted(items, key=lambda x: (x.get("priority", 99), x["slug"]))


def get_solution(slug: str, locale: str = None):
    from app.marketing.seo_i18n import localize_solution
    from app.services.i18n_service import get_locale

    solution = SOLUTIONS.get(slug)
    if solution is None:
        return None
    return localize_solution(solution, slug, locale or get_locale())
