"""Artículos SEO públicos (español). Indexables; enlace discreto en footer."""

from __future__ import annotations

SEO_ARTICLES = {
    "planificador-de-obra": {
        "title": "Planificador de obra: quién va a cada tajo (no un Gantt)",
        "description": (
            "Planificador de obra para constructoras: el cuadrante de quién va a cada tajo "
            "cada día. No es Gantt ni ERP. Guía clara + alta gratis en SignaPlan."
        ),
        "h1": "Qué es un planificador de obra (y cuál te hace falta)",
        "updated": "2026-10-12",
        "keywords": "planificador de obra, planificador obra constructora, gantt obra vs cuadrante",
        "body_html": """
<p>Quien busca <strong>planificador de obra</strong> casi nunca busca lo mismo. Google
mezcla tres productos distintos: el Gantt de proyecto, el ERP de presupuestos y el
cuadrante de personal. Si eliges mal, pagas un software que no responde a la pregunta
de las 06:45: <em>quién mando mañana a cada tajo</em>.</p>

<h2>Las tres cosas que se llaman «planificador de obra»</h2>
<h3>1. Gantt / planificación de proyecto</h3>
<p>Barras en el tiempo, partidas, holguras, camino crítico. Sirve para saber <em>cuándo</em>
va el hormigón o el cerramiento. No dice si Pepe está en la A-23 o en el chalet.</p>
<h3>2. ERP de constructora</h3>
<p>Presupuestos, BC3, certificaciones, compras, facturación. Imprescindible cuando ya
facturas en serio. Pesado (y caro) si lo que se rompe es el Excel del personal.</p>
<h3>3. Cuadrante operativo (personal, no partidas)</h3>
<p>Persona, obra, fechas. Oficina y jefe ven el mismo tablero. Es lo que la mayoría de
PYMES de obra necesita el primer año, aunque lo busquen como «planificador de obra».</p>

<h2>Cómo saber cuál te duele a ti</h2>
<ul>
  <li>Si el caos es «no sé quién va a cada obra» → cuadrante de personal.</li>
  <li>Si el caos es «el plazo de la partida se ha comido» → Gantt / proyecto.</li>
  <li>Si el caos es «no cierro certificación ni albarán» → ERP.</li>
</ul>
<p>Pueden convivir. El error es comprar el tercero cuando el problema es el primero.</p>

<h2>Qué debe hacer un planificador operativo (checklist)</h2>
<ul>
  <li>Asignar gente a obras por día, no por «mes aproximado».</li>
  <li>Ver choques: dos obras, baja, vacaciones, el mismo peón dos veces.</li>
  <li>Que el jefe de obra mueva a alguien sin esperar al Excel de administración.</li>
  <li>Una sola versión: ni «final_v7» ni el grupo de WhatsApp como fuente de verdad.</li>
  <li>Poder enganchar después fichaje y vehículos al mismo calendario.</li>
</ul>

<h2>Excel: cuándo basta y cuándo ya no</h2>
<p>Con 4 peones y una obra, Excel aguanta. Se rompe cuando hay varias frentes, cambios
a las 07:00 y dos copias del archivo. Ahí no necesitas un ERP: necesitas un tablero
que no se bifurque.</p>

<h2>Errores típicos al elegir software</h2>
<ul>
  <li>Comprar «el más completo» y no usarlo porque el jefe no lo abre.</li>
  <li>Confundir planificación de partidas con planificación de personas.</li>
  <li>Montar fichaje en una app y el cuadrante en otra: los datos no se hablan.</li>
</ul>

<p>Si lo que te duele es el cuadrante, sigue en
<a href="/recursos/cuadrante-personal-obra">cuadrante de personal de obra</a>
o mira cómo lo resuelve el producto en
<a href="/soluciones/planificador-personal-obra">planificador de personal de obra</a>.
Alta gratuita, sin tarjeta, en <a href="/alta">crear cuenta</a>.</p>
""",
    },
    "cuadrante-personal-obra": {
        "title": "Cuadrante de personal de obra: quién va a cada tajo cada día",
        "description": (
            "Cuadrante de peones y jefes por obra y fecha. Alternativa al Excel y al "
            "WhatsApp. No es un Gantt ni un ERP: es quién mando mañana a cada tajo."
        ),
        "h1": "Cuadrante de personal de obra (quién va a cada tajo)",
        "updated": "2026-08-16",
        "keywords": "cuadrante personal obra, cuadrante peones, quién va a cada obra, excel cuadrante constructora",
        "body_html": """
<p>Si abres un Excel cada mañana para decidir <strong>quién va a cada obra</strong>,
ya tienes un cuadrante. El problema es que vive en un archivo, en un grupo de
WhatsApp y en la cabeza del jefe. Un <strong>cuadrante de personal de obra</strong>
es esa misma pregunta, en un tablero que oficina y campo ven igual.</p>

<h2>No es un planificador de obra tipo Gantt</h2>
<p>Cuando Google enseña “planificador de obra”, suele salir software de
<strong>proyecto</strong>: barras, partidas, presupuestos. Eso no te dice si
el peón está mañana en la A-23 o en el chalet. El cuadrante sí: persona, obra,
fechas.</p>

<h2>Qué se rompe con el Excel del cuadrante</h2>
<ul>
  <li>Dos versiones (oficina y caseta) y nadie sabe cuál vale.</li>
  <li>Un cambio a las 7:00 que no llega a quien conduce.</li>
  <li>Dobles asignaciones y bajas que se ven cuando el tajo ya está a medias.</li>
</ul>

<h2>Qué tiene que hacer el cuadrante</h2>
<ul>
  <li>Asignar gente a obras por día, sin pelearte con celdas combinadas.</li>
  <li>Que el jefe de obra pueda mover peones sin esperar al Excel de administración.</li>
  <li>Ver choques (dos obras, ausencia) antes de que salga el primer coche.</li>
  <li>Poder enganchar después el fichaje y los vehículos al mismo calendario.</li>
</ul>

<p>SignaPlan es exactamente ese tablero. Empieza en
<a href="/alta">alta gratuita</a> (sin tarjeta) o mira la
<a href="/soluciones/planificador-personal-obra">solución de planificador de personal</a>.</p>
""",
    },
    "fichaje-construccion": {
        "title": "Fichaje en construcción: DNI + PIN en el móvil, sin reloj de pared",
        "description": (
            "Cómo implantar el fichaje en obra con móvil: entradas, salidas, pausas y "
            "trazabilidad. Alternativa práctica al reloj físico en constructoras."
        ),
        "h1": "Cómo implantar el fichaje en obra (guía)",
        "updated": "2026-08-07",
        "keywords": "fichaje construcción, fichaje obra, control horario construcción",
        "body_html": """
<p>En obra el reloj de pared se pierde, se comparte o simplemente no se usa.
El <strong>fichaje en construcción</strong> con móvil (identificación + PIN) permite
que cada trabajador registre jornada donde esté el tajo.</p>

<h2>Qué pide la práctica diaria</h2>
<ul>
  <li>Entrada, salida y pausas sin fricción (guantes, sol, prisas).</li>
  <li>Que la oficina vea el mismo día qué ha pasado.</li>
  <li>Informes listos cuando llega una inspección o una consulta de RRHH.</li>
</ul>

<h2>Fichaje y planificación juntos</h2>
<p>Si el cuadrante dice que Juan está en la obra A y el fichaje sale en otro sitio,
alguien tiene que enterarse pronto. Por eso conviene que <strong>planificador y fichaje
vivan en la misma herramienta</strong>, no en dos islas.</p>

<p>Con SignaPlan el operario ficha desde el móvil y la empresa conserva un registro de
jornada con trazabilidad. Sigue en la
<a href="/soluciones/fichaje-construccion">página de producto de fichaje</a>
o empieza en <a href="/alta">alta gratuita</a>. Si te preocupa una inspección,
sigue en <a href="/recursos/inspeccion-trabajo-construccion">inspección de jornada en obra</a>.</p>
""",
    },
    "registro-jornada-laboral": {
        "title": "Registro de jornada laboral en obra: dejar el Excel sin perder el control",
        "description": (
            "Registro de jornada laboral en construcción sin plantillas Excel: pausas, "
            "trazabilidad e informe para inspección. Guía práctica para constructoras."
        ),
        "h1": "Registro de jornada laboral en obra",
        "updated": "2026-08-07",
        "keywords": "registro de jornada, control horario laboral, registro jornada construcción",
        "body_html": """
<p>El <strong>registro de jornada</strong> no es solo “fichar”. Es poder demostrar
horarios, pausas y cambios con una traza clara cuando lo pide inspección o el propio
trabajador.</p>

<p>Si buscas un <strong>registro de jornada laboral en Excel</strong> (plantilla,
diario, tiempo parcial), el problema no es el archivo: son las copias, las
correcciones sin rastro y que no cuadra con lo que pasó en obra. Digitalizarlo
no es “otro Excel en la nube”; es un libro con eventos que no se reescriben.</p>

<h2>Problemas típicos del Excel</h2>
<ul>
  <li>Versiones distintas en cada PC.</li>
  <li>Correcciones sin histórico.</li>
  <li>Horas que no cuadran con lo que pasó en obra.</li>
</ul>

<h2>Qué ayuda de verdad</h2>
<p>Un libro de jornada digital con eventos encadenados, pausas y, cuando aplique,
conforme del trabajador. PDF/CSV exportables para archivo o asesoría.</p>

<p>SignaPlan incluye registro de jornada con trazabilidad ligado al fichaje en campo.
Si te preocupa una visita de Inspección, lee
<a href="/recursos/inspeccion-trabajo-construccion">qué te piden en obra</a>.
Sigue en la <a href="/soluciones/registro-jornada-obra">solución de registro de jornada</a>
o <a href="/alta">crea una cuenta gratuita</a>.</p>
""",
    },
    "inspeccion-trabajo-construccion": {
        "title": "Inspección de trabajo en construcción: el registro de jornada en obra",
        "description": (
            "Qué suele pedirse en una inspección de jornada en constructoras: entradas, "
            "pausas y traza creíble en el tajo. Cómo dejar de improvisar con Excel."
        ),
        "h1": "Inspección de trabajo en obra: registro de jornada que se puede enseñar",
        "updated": "2026-08-16",
        "keywords": "inspección trabajo construcción, registro jornada inspección obra, multa registro jornada constructora",
        "body_html": """
<p>En una <strong>inspección de trabajo</strong> en construcción no basta con
decir “fichamos”. Hay que poder enseñar, por persona y por día, entradas, salidas
y pausas con una traza que no sea un Excel retocado la noche anterior. Esto no
es asesoramiento jurídico: es lo que se rompe en obra cuando el reloj está en
caseta y el peón está en el tajo.</p>

<h2>Por qué el Excel no aguanta el tajo</h2>
<ul>
  <li>Copias distintas en cada PC y correcciones sin histórico.</li>
  <li>Horas “acordadas” el viernes que no coinciden con lo que pasó en campo.</li>
  <li>Un reloj de pared que se comparte o que nadie usa.</li>
</ul>

<h2>Qué ayuda de verdad (sin montar un ERP)</h2>
<ul>
  <li>Fichaje en el móvil, donde está la obra.</li>
  <li>Un libro de jornada que no se reescribe a capón.</li>
  <li>Exportación (PDF/CSV) para archivo, asesoría o la visita.</li>
  <li>El mismo sistema que el cuadrante: si Juan debía estar en la obra A, se ve.</li>
</ul>

<p>SignaPlan une fichaje en campo y registro con trazabilidad. Crea cuenta en
<a href="/alta">alta gratuita</a> o sigue en
<a href="/soluciones/registro-jornada-obra">registro de jornada en obra</a> y en
<a href="/soluciones/fichaje-construccion">fichaje en construcción</a>.</p>
""",
    },
    "gestion-flota-obra": {
        "title": "Gestión de flota en obra: coches libres y asignación al personal",
        "description": (
            "Cómo alinear vehículos con el cuadrante y las ausencias: coches libres, "
            "asignación diaria y menos WhatsApps sobre ‘quién se lleva la furgoneta’."
        ),
        "h1": "Gestión de flota para empresas de obra",
        "updated": "2026-08-07",
        "keywords": "gestión flota obra, coches libres construcción, asignación vehículos obra",
        "body_html": """
<p>La furgoneta “libre” que nadie sabe dónde está es un clásico. Una
<strong>gestión de flota</strong> mínima pero útil responde: qué vehículo va con qué
equipo, y cuáles quedan libres por ausencia o cambio de obra.</p>

<h2>Enlazar flota y personal</h2>
<p>Si el planificador mueve a un peón y el coche sigue asignado “por costumbre”,
pierdes tiempo cada mañana. La flota debe mirar el mismo calendario que el personal.</p>

<p>SignaPlan incluye flota alineada con ausencias y cuadrante.
<a href="/alta">Pruébalo gratis</a> o sigue en la
<a href="/soluciones/flota-obra">solución de flota</a>.</p>
""",
    },
    "software-constructoras": {
        "title": "Software para constructoras: gestión del día a día (no un ERP)",
        "description": (
            "Software para constructoras PYME: cuadrante, fichaje y flota. Alta gratis, "
            "sin tarjeta. El programa del tajo, no el de presupuestos BC3."
        ),
        "h1": "Software para constructoras (sin montar un ERP)",
        "updated": "2026-10-12",
        "keywords": "software constructoras, software para constructoras, software obra",
        "body_html": """
<p>El <strong>software para constructoras</strong> que aparece en Google suele ser un ERP:
presupuestos, mediciones, facturación. Una PYME de obra también necesita otra capa, más
sucia y más diaria: quién va a cada tajo, quién ha fichado, qué furgoneta está libre y,
si hay subcontratas, que suban docs y certifiquen horas sin otro Excel.</p>

<h2>Qué cubre un ERP (y qué no)</h2>
<p>Un ERP de constructora es el sistema de <em>negocio</em>: oferta, certificación de
partidas, compras. No está pensado para que el jefe mueva a un peón a las 07:10 ni para
que el peón fiche con guantes en el tajo. Por eso conviven Excel y WhatsApp aunque
«ya tengáis programa».</p>

<h2>Qué tiene que hacer el software operativo</h2>
<ul>
  <li>Cuadrante de personal por obra y fecha.</li>
  <li>Fichaje en el móvil, no un reloj de pared en caseta.</li>
  <li>Registro de jornada exportable (inspección, asesoría).</li>
  <li>Flota alineada con el mismo calendario, no otra hoja.</li>
  <li>Portal de subcontrata: documentación exigida y certificación de <em>horas</em>
      (no de mediciones BC3).</li>
  <li>Que un jefe de obra lo use en diez minutos, no en un curso de tres días.</li>
</ul>

<h2>Checklist antes de comprar</h2>
<ul>
  <li>¿Lo entiende quien está en obra, no solo administración?</li>
  <li>¿El fichaje funciona con DNI/PIN o equivalente, sin hardware extra?</li>
  <li>¿Puedes enseñar jornada cuando llama inspección?</li>
  <li>¿La flota mira el mismo tablero que el personal?</li>
  <li>¿La subcontrata puede aportar docs y horas sin otro canal?</li>
  <li>¿El alta es usable sin comercial ni tarjeta el primer día?</li>
</ul>

<p>SignaPlan es ese software operativo. No sustituye BC3 ni facturación. Empieza en
<a href="/alta">alta gratuita</a>. Más detalle de subcontratas en
<a href="/soluciones/subcontratas-documentacion-horas">docs y horas con subcontratas</a>.
Si buscabas un ERP gratis, lee
<a href="/recursos/erp-constructoras-gratis">ERP para constructoras gratis</a>.
Integración con Odoo u otro ERP: <a href="/contacto">contacto</a>.</p>
""",
    },
    "erp-constructoras-gratis": {
        "title": "ERP para constructoras gratis: qué hay (y qué no te va a salvar)",
        "description": (
            "Un ERP para constructoras gratis de verdad casi no existe. Qué cubre un ERP, "
            "qué no, y qué software operativo puedes usar sin tarjeta el primer día."
        ),
        "h1": "ERP para constructoras gratis: la trampa del «todo incluido»",
        "updated": "2026-08-27",
        "keywords": "erp para constructoras gratis, erp constructoras, erp construcción gratuito",
        "body_html": """
<p>Quien busca <strong>ERP para constructoras gratis</strong> suele querer dos cosas a la
vez: no pagar, y que el programa le resuelva obra, personal, facturas y fichaje.
Eso, en un solo producto serio, casi no existe. Lo «gratis» o es un cebo de 15 días,
o es un Excel disfrazado, o le faltan justo las piezas que te duelen.</p>

<h2>Qué es un ERP de constructora (de verdad)</h2>
<p>Un ERP (Presto, CYPE, Obralia, Odoo a medida, etc.) cubre el ciclo económico:
presupuesto, medición, certificación, compras, a veces facturación. Es el sistema
de la oficina técnica y de administración. No es el cuadrante de peones ni el
fichaje en el tajo.</p>

<h2>Por qué «gratis» casi siempre miente</h2>
<ul>
  <li>Prueba de 14 días y luego cuota por usuario o por obra.</li>
  <li>Módulo base gratis y el de personal / fichaje de pago.</li>
  <li>Open source (Odoo Community) que exige implantador: el software es 0 €, el
      proyecto no.</li>
  <li>Herramientas que llaman ERP a un Gantt y un listado de contactos.</li>
</ul>

<h2>Qué te hace falta el primer año (PYME)</h2>
<p>Si sois 8–40 personas en obra, el incendio diario no es el BC3: es quién va a
cada frente, quién falta, quién ficha y qué coche sale. Eso se resuelve con software
<strong>operativo</strong>, no con un ERP completo el mes 1. El ERP llega cuando
ya facturáis con método y os duele la certificación, no el WhatsApp.</p>

<h2>Cómo no tirar el dinero</h2>
<ol>
  <li>Lista el dolor en una frase («no sé quién va mañana», «inspección de jornada»,
      «cierro certificación tarde»).</li>
  <li>Compra la herramienta de ese dolor. No «la más completa».</li>
  <li>Si más adelante hace falta ERP, se integra. No al revés.</li>
</ol>

<p>SignaPlan no es un ERP y no lo pretende: cuadrante, fichaje, flota y control con
subcontratas (docs y horas), alta <strong>sin tarjeta</strong>. Empieza en
<a href="/alta">crear cuenta</a>. Para elegir categoría de producto, la guía
<a href="/recursos/software-constructoras">software para constructoras</a>
y <a href="/recursos/software-gestion-empresa-constructora">software de gestión
para empresa constructora</a>.</p>
""",
    },
    "software-gestion-empresa-constructora": {
        "title": "Software de gestión operativa para constructoras (cuadrante y fichaje)",
        "description": (
            "Software de gestión operativa para constructoras: quién va a cada obra, "
            "quién ficha y qué coche está libre. Diferente de un ERP. Alta gratis."
        ),
        "h1": "Software de gestión operativa para constructoras",
        "updated": "2026-10-12",
        "keywords": (
            "software de gestión operativa para constructoras, "
            "software de gestion para empresa constructora, software gestión constructora, "
            "sistema de gestion para empresas constructoras"
        ),
        "body_html": """
<p>El <strong>software de gestión operativa para constructoras</strong> (también buscado
como software de gestión para empresa constructora) no es un único programa. Hay gestión
de <em>negocio</em> (euros, partidas, facturas) y gestión <em>operativa</em> (personas,
horas, vehículos). Mezclarlas en la misma ficha de compra es el origen de implantaciones
que nadie usa.</p>

<h2>Capa oficina (ERP / contabilidad / presupuestos)</h2>
<ul>
  <li>Ofertas, mediciones, certificaciones, compras.</li>
  <li>Usuarios: administración, encargado de producción, dirección.</li>
  <li>Ciclo: semanas y meses, no el parte de las 07:00.</li>
</ul>

<h2>Capa tajo (operaciones)</h2>
<ul>
  <li>Quién está en qué obra cada día.</li>
  <li>Fichaje y registro de jornada.</li>
  <li>Coches y furgonetas alineados con el cuadrante.</li>
  <li>Usuarios: jefe de obra y, si ficha, el peón en el móvil.</li>
</ul>

<h2>Señales de que te falta la capa tajo</h2>
<ul>
  <li>Tenéis «programa» pero el cuadrante sigue en Excel.</li>
  <li>Los cambios de última hora van por WhatsApp y no hay rastro.</li>
  <li>El fichaje, si existe, no cuadra con la planificación.</li>
  <li>Inspección o la asesoría piden jornada y tardáis un día en montar el Excel.</li>
</ul>

<h2>Orden de implantación que suele funcionar</h2>
<ol>
  <li>Cuadrante de personal (una sola verdad).</li>
  <li>Fichaje en campo + registro de jornada.</li>
  <li>Flota si hay más de un vehículo de empresa.</li>
  <li>ERP / integración cuando el cuello de botella ya no es la gente, sino el papel
      de certificación y factura.</li>
</ol>

<p>SignaPlan cubre la capa tajo. Alta en <a href="/alta">cuenta gratuita</a>.
Más contexto en <a href="/recursos/software-constructoras">software para constructoras</a>
y en la solución de
<a href="/soluciones/planificador-personal-obra">planificador de personal</a>.</p>
""",
    },
    "programa-para-constructoras": {
        "title": "Programas de una empresa constructora: el del tajo (no solo oficina)",
        "description": (
            "Programas de una empresa constructora: el que usa el jefe a las 07:00 "
            "(cuadrante, fichaje, flota). Alta gratis, sin montar un ERP."
        ),
        "h1": "Programas de una empresa constructora (el del día a día)",
        "updated": "2026-10-12",
        "keywords": (
            "programas de una empresa constructora, programa para constructoras, "
            "mejor programa gestion empresa constructora, programa constructoras"
        ),
        "body_html": """
<p>«<strong>Programas de una empresa constructora</strong>» (o programa para constructoras)
es la búsqueda de quien no quiere jerga (ERP, SaaS, Gantt) y sí una herramienta que el
jefe abra por la mañana. Si el programa solo lo entiende administración, en obra
seguirá el Excel.</p>

<h2>Qué tiene que hacer el programa el lunes a las 07:00</h2>
<ul>
  <li>Decir quién va a cada obra, sin abrir tres archivos.</li>
  <li>Permitir un cambio de última hora que vea todo el mundo.</li>
  <li>Dejar fichar en el tajo, no en un reloj que nadie usa.</li>
  <li>Saber qué furgoneta está libre si hay baja.</li>
  <li>Si hay subcontrata: que aporte docs y proponga horas sin otro canal.</li>
</ul>

<h2>Lo que no tiene que hacer el primer mes</h2>
<p>No tiene que presupuestar en BC3, ni llevar el IVA, ni sustituir a tu gestoría.
Eso es otro programa (o el mismo, años más tarde). Empezar por «todo» es la forma
más rápida de no usar nada. La certificación de <em>horas</em> con la subcontrata
sí puede entrar pronto; la de partidas, no.</p>

<h2>Prueba de 10 minutos</h2>
<p>Sienta al jefe de obra delante. Si en diez minutos no sabe asignar a un peón a
una obra, ese no es vuestro programa, por muchos módulos que tenga.</p>

<p>SignaPlan está hecho para esa prueba. Crea cuenta en
<a href="/alta">alta gratuita</a> (sin tarjeta) o compara categorías en
<a href="/recursos/software-constructoras">software para constructoras</a>.
Subcontratas:
<a href="/soluciones/subcontratas-documentacion-horas">docs y horas</a>.</p>
""",
    },
}


def list_articles(locale: str = None):
    from app.marketing.seo_i18n import localize_article
    from app.services.i18n_service import get_locale

    loc = locale or get_locale()
    items = []
    for slug, meta in SEO_ARTICLES.items():
        localized = localize_article(meta, slug, loc)
        items.append(
            {"slug": slug, **{k: v for k, v in localized.items() if k != "body_html"}}
        )
    return items


def get_article(slug: str, locale: str = None):
    from app.marketing.seo_i18n import localize_article
    from app.services.i18n_service import get_locale

    article = SEO_ARTICLES.get(slug)
    if article is None:
        return None
    return localize_article(article, slug, locale or get_locale())
