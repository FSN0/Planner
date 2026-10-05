"""Informe PDF de reuniones / notas y envío al autor."""
from __future__ import annotations

import html
import re

from flask import current_app

from app.models import Nota, User
from app.services.email_service import send_email
from app.services.i18n_service import translate
from app.services.tenant_branding_service import (
    get_brand_stripe_color,
    get_organization_display_name,
    header_data_uri,
    logo_stripe_data_uri,
    mark_data_uri,
)

_TRANSCRIPT_SPLIT_RE = re.compile(
    r'(?:^|\n)\s*---\s*\n+\s*Transcripción\s*:\s*\n',
    re.IGNORECASE,
)
# Cola interna del acta (obras vinculadas, sugerencias, etc.) tras un segundo ---
_TAIL_SPLIT_RE = re.compile(r'(?:^|\n)\s*---\s*\n', re.MULTILINE)


def _pdfkit_options() -> dict:
    # A4 a sangre. La franja y la marca de agua van con position:fixed en el HTML.
    return {
        'page-size': 'A4',
        'encoding': 'UTF-8',
        'margin-top': '0',
        'margin-bottom': '0',
        'margin-left': '0',
        'margin-right': '0',
        'quiet': '',
        'enable-local-file-access': None,
        'disable-smart-shrinking': None,
        'print-media-type': None,
        'no-outline': None,
    }


def _format_contenido_html(contenido: str) -> str:
    escaped = html.escape((contenido or '').rstrip())
    return escaped.replace('\n', '<br>\n')


def _text_line_count(text: str, *, chars_per_line: int = 80) -> int:
    if not (text or '').strip():
        return 0
    total = 0
    for line in (text or '').splitlines() or ['']:
        total += max(1, (len(line) + chars_per_line - 1) // chars_per_line)
    return total


def estimate_informe_page_count(resumen: str, transcripcion: str) -> int:
    """
    Estimación de páginas A4 para capas de franja/marca de agua.
    El PDF real se mide en un primer pase sin capas (ver render_informe_pdf_bytes).
    """
    resumen_lines = _text_line_count(resumen)
    trans_lines = _text_line_count(transcripcion)
    first_page_lines = 32
    other_page_lines = 42

    if not transcripcion:
        lines = max(resumen_lines, 1)
        if lines <= first_page_lines:
            return 1
        rest = lines - first_page_lines
        return 1 + (rest + other_page_lines - 1) // other_page_lines

    pages = 1
    if resumen_lines > first_page_lines:
        rest = resumen_lines - first_page_lines
        pages = 1 + (rest + other_page_lines - 1) // other_page_lines

    trans_lines += 4  # cabecera «Transcripción» + margen
    pages += max(1, (trans_lines + other_page_lines - 1) // other_page_lines)
    return max(pages, 1)


def _count_pdf_pages(pdf_bytes: bytes) -> int:
    try:
        from io import BytesIO

        from pypdf import PdfReader

        return max(1, len(PdfReader(BytesIO(pdf_bytes)).pages))
    except Exception:
        return 1


def split_acta_contenido(contenido: str) -> tuple[str, str]:
    """
    Separa resumen / cuerpo principal de la transcripción.
    Formato típico de notas por voz:
      <resumen>
      ---
      Transcripción:
      <texto>
      ---
      Obras vinculadas: ...
    """
    text = (contenido or '').strip()
    if not text:
        return '', ''

    match = _TRANSCRIPT_SPLIT_RE.search(text)
    if match:
        resumen = text[: match.start()].strip()
        resto = text[match.end():].strip()
        # Quitar cola interna (obras / personas) tras el siguiente ---
        tail = _TAIL_SPLIT_RE.search(resto)
        if tail:
            transcripcion = resto[: tail.start()].strip()
        else:
            transcripcion = resto
        return resumen, transcripcion

    # Sin marcador de transcripción: todo es cuerpo (notas escritas)
    return text, ''


def build_informe_context(
    nota: Nota,
    *,
    schema_name: str | None = None,
    overlay_page_count: int | None = None,
) -> dict:
    resumen_raw, transcripcion_raw = split_acta_contenido(nota.contenido or '')
    if overlay_page_count is None:
        overlay_page_count = estimate_informe_page_count(resumen_raw, transcripcion_raw)
    overlay_page_count = max(0, int(overlay_page_count))
    ctx = {
        'nota': nota,
        'titulo': nota.titulo,
        'resumen_html': _format_contenido_html(resumen_raw),
        'transcripcion_html': _format_contenido_html(transcripcion_raw) if transcripcion_raw else '',
        'tiene_transcripcion': bool(transcripcion_raw),
        'organizacion': get_organization_display_name(),
        'logo_data_uri': logo_stripe_data_uri(schema_name),
        'header_data_uri': header_data_uri(schema_name),
        # Visible pero deja leer el texto; CSS opacity falla en wkhtmltopdf.
        'mark_data_uri': mark_data_uri(schema_name, opacity=0.14),
        'stripe_color': get_brand_stripe_color(),
        'overlay_page_count': overlay_page_count,
    }
    try:
        current_app.logger.info(
            'Informe PDF assets nota_id=%s header=%s logo=%s mark=%s stripe=%s',
            getattr(nota, 'id', None),
            bool(ctx['header_data_uri']),
            bool(ctx['logo_data_uri']),
            bool(ctx['mark_data_uri']),
            ctx['stripe_color'],
        )
    except Exception:
        pass
    return ctx


def render_informe_html(
    nota: Nota,
    *,
    schema_name: str | None = None,
    overlay_page_count: int | None = None,
) -> str:
    """Render sin request context: Celery no tiene petición HTTP."""
    ctx = build_informe_context(
        nota,
        schema_name=schema_name,
        overlay_page_count=overlay_page_count,
    )
    template = current_app.jinja_env.get_template('notas/informe_reunion_pdf.html')
    return template.render(_=translate, **ctx)


def _pdfkit_render(html_doc: str) -> bytes:
    import pdfkit

    config = None
    wkhtml = (
        current_app.config.get('WKHTMLTOPDF_CMD')
        or current_app.config.get('PDFKIT_WKHTMLTOPDF')
    )
    if wkhtml:
        config = pdfkit.configuration(wkhtmltopdf=wkhtml)
    return pdfkit.from_string(
        html_doc, False, options=_pdfkit_options(), configuration=config,
    )


def render_informe_pdf_bytes(nota: Nota, *, schema_name: str | None = None) -> bytes:
    # 1) Sin capas absolute: wkhtmltopdf no infla a 40 hojas vacías.
    probe_html = render_informe_html(
        nota, schema_name=schema_name, overlay_page_count=0,
    )
    page_count = _count_pdf_pages(_pdfkit_render(probe_html))
    # 2) Franja y marca de agua solo en las hojas que existen.
    final_html = render_informe_html(
        nota, schema_name=schema_name, overlay_page_count=page_count,
    )
    return _pdfkit_render(final_html)


def _safe_pdf_filename(nota: Nota) -> str:
    base = re.sub(r'[^\w\s\-]', '', (nota.titulo or 'reunion')[:80]).strip()
    base = re.sub(r'\s+', '_', base) or 'reunion'
    return f'informe_{base}_{nota.id}.pdf'


def send_informe_to_author(nota_id: int, *, schema_name: str | None = None) -> bool:
    """
    Genera PDF y lo envía únicamente al autor de la nota (un destinatario).
    """
    nota = Nota.query.get(nota_id)
    if not nota:
        current_app.logger.warning('Informe reunión: nota %s no encontrada', nota_id)
        return False

    autor = nota.autor or User.query.get(nota.autor_id)
    email = (getattr(autor, 'email', None) or '').strip()
    if not email:
        current_app.logger.info(
            'Informe reunión: autor sin email (nota_id=%s autor_id=%s)',
            nota_id, nota.autor_id,
        )
        return False

    try:
        pdf_bytes = render_informe_pdf_bytes(nota, schema_name=schema_name)
    except Exception as exc:
        current_app.logger.warning(
            'Informe reunión: no se pudo generar PDF nota_id=%s: %s', nota_id, exc,
        )
        return False

    subject = translate('Informe de reunión: {titulo}', titulo=nota.titulo)
    body = translate(
        'Adjuntamos el informe PDF de la reunión «{titulo}» ({fecha}).',
        titulo=nota.titulo,
        fecha=nota.fecha.strftime('%d/%m/%Y') if nota.fecha else '',
    )
    filename = _safe_pdf_filename(nota)

    return bool(send_email(
        subject,
        [email],
        body,
        attachments=[{
            'filename': filename,
            'content_type': 'application/pdf',
            'data': pdf_bytes,
        }],
    ))
