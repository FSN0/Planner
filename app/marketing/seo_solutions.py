"""Páginas /soluciones/ — hub SEO por problema (calidad, no granja)."""

from __future__ import annotations

SOLUTIONS = {
    "fichaje-construccion": {
        "title": "Fichaje en construcción: móvil en obra sin reloj de pared",
        "description": (
            "Fichaje para constructoras con DNI + PIN en el móvil. Entradas, salidas y "
            "pausas en el tajo, unido al cuadrante de personal. Prueba SignaPlan gratis."
        ),
        "h1": "Fichaje en construcción pensado para el tajo",
        "eyebrow": "Solución · Fichaje",
        "updated": "2026-08-07",
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
                "a": "SignaPlan genera un registro de jornada con trazabilidad (eventos encadenados, pausas y exportación). Consulta también nuestra guía de registro de jornada en obra.",
            },
        ],
        "body_html": """
<p>En obra el reloj de pared falla: se comparte, se olvida o simplemente no está.
Necesitas un <strong>fichaje en construcción</strong> que el peón pueda usar
donde esté el tajo, y que la oficina pueda revisar el mismo día.</p>

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
  <li><strong>Misma plataforma que el cuadrante:</strong> planificas peones y ves el fichaje sin saltar de herramienta.</li>
  <li><strong>Trazabilidad:</strong> registro orientado a inspección y archivo, no a “borrar y ya”.</li>
</ul>

<h2>Para quién es</h2>
<p>Constructoras y empresas de obra (PYME) que ya pelean el día a día con WhatsApp
y Excel, y quieren fichaje real sin montar un ERP entero el primer mes.</p>

<p>Empieza con <a href="/alta">cuenta gratuita</a> o mira también
<a href="/soluciones/registro-jornada-obra">registro de jornada en obra</a> y el
<a href="/soluciones/planificador-personal-obra">planificador de personal</a>.</p>
""",
    },
    "planificador-personal-obra": {
        "title": "Planificador de personal de obra: quién va a cada tajo cada día",
        "description": (
            "Cuadrante de peones y jefes por obra y fecha. Menos Excel, menos WhatsApp. "
            "Planificador de personal para constructoras — SignaPlan."
        ),
        "h1": "Planificador de personal de obra (cuadrante real)",
        "eyebrow": "Solución · Planificación",
        "updated": "2026-08-07",
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
<strong>planificador de personal de obra</strong>: un cuadrante, no un banco de precios.</p>

<h2>El problema del Excel + WhatsApp</h2>
<ul>
  <li>Versiones distintas en el PC del jefe y en el de administración.</li>
  <li>Cambios de última hora que no llegan a todos.</li>
  <li>Nadie ve conflictos (doble obra, baja, coche) hasta que ya es tarde.</li>
</ul>

<h2>Qué hace SignaPlan aquí</h2>
<ul>
  <li>Asignar personal a obras por fechas, con vista clara.</li>
  <li>Detectar choques antes de que el peón esté en el sitio equivocado.</li>
  <li>Conectar con <a href="/soluciones/fichaje-construccion">fichaje</a> y
      <a href="/soluciones/flota-obra">flota</a> cuando lo necesites.</li>
</ul>

<h2>No es un ERP completo (y está bien)</h2>
<p>Si necesitas BC3, certificaciones y facturación, hay herramientas para eso.
SignaPlan cubre el <em>día a día de gente y vehículos</em>. Puedes empezar por aquí
y enlazar un ERP después si hace falta.</p>

<p><a href="/alta">Crear cuenta gratuita</a> ·
<a href="/contacto">Pedir demo</a></p>
""",
    },
    "registro-jornada-obra": {
        "title": "Registro de jornada en obra: trazabilidad para inspección",
        "description": (
            "Registro de jornada laboral para constructoras: digital, con pausas y "
            "exportación. Prepárate ante inspección sin Excel eterno. SignaPlan."
        ),
        "h1": "Registro de jornada en obra con trazabilidad",
        "eyebrow": "Solución · Cumplimiento",
        "updated": "2026-08-07",
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
hay que demostrar entradas, salidas y cambios con una traza creíble.</p>

<h2>Por qué ahora hay más ruido</h2>
<p>Además de la obligación ya vigente, el debate público sobre registro
<strong>digital e inalterable</strong> empuja a muchas constructoras a dejar el
papel y el Excel. Conviene adelantarse con un sistema usable en campo.</p>

<h2>Qué pedirle a una herramienta seria</h2>
<ul>
  <li>Registro diario por trabajador (inicio / fin, y pausas si aplican).</li>
  <li>Que no sea trivial “borrar y reescribir” sin dejar huella.</li>
  <li>Exportación para inspección o asesoría.</li>
  <li>Que el peón pueda fichar en obra, no solo en oficina.</li>
</ul>

<h2>SignaPlan en este punto</h2>
<p>El fichaje alimenta un registro con trazabilidad. Encaja con el
<a href="/soluciones/fichaje-construccion">fichaje en construcción</a> y con el
<a href="/soluciones/planificador-personal-obra">cuadrante</a>.</p>

<p><a href="/alta">Empezar gratis</a> ·
<a href="/recursos/registro-jornada-laboral">Guía relacionada</a></p>
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
        "updated": "2026-08-07",
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
va con qué equipo, y qué queda libre cuando hay baja o cambio de tajo.</p>

<h2>Sin integrar personal, la flota miente</h2>
<p>Listas de coches en un Excel aparte no ven ausencias ni el cuadrante.
SignaPlan enlaza vehículos con el mismo mundo que el
<a href="/soluciones/planificador-personal-obra">planificador de personal</a>.</p>

<h2>Para quién</h2>
<p>Empresas con varias furgonetas o coches de empresa que ya sufren el caos
matutino de “¿quién se lleva cuál?”.</p>

<p><a href="/alta">Probar SignaPlan</a> ·
<a href="/soluciones/">Ver todas las soluciones</a></p>
""",
    },
}


def list_solutions():
    items = [
        {"slug": slug, **{k: v for k, v in meta.items() if k not in ("body_html", "faq")}}
        for slug, meta in SOLUTIONS.items()
    ]
    return sorted(items, key=lambda x: (x.get("priority", 99), x["slug"]))


def get_solution(slug: str):
    return SOLUTIONS.get(slug)
