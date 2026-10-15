"""Informe PDF de reuniones."""
from types import SimpleNamespace
from unittest.mock import patch

from app.services.nota_informe_service import (
    _format_contenido_html,
    _safe_pdf_filename,
    estimate_informe_page_count,
    render_informe_html,
    send_informe_to_author,
    split_acta_contenido,
)


def test_format_contenido_html_escapes_and_breaks():
    raw = 'Hola <script>\nSegunda línea'
    out = _format_contenido_html(raw)
    assert '<script>' not in out
    assert '&lt;script&gt;' in out
    assert '<br>' in out


def test_safe_pdf_filename():
    nota = SimpleNamespace(id=7, titulo='Reunión Obra / Norte')
    name = _safe_pdf_filename(nota)
    assert name.endswith('_7.pdf')
    assert ' ' not in name


def test_split_acta_contenido_con_transcripcion():
    raw = (
        '## Resumen\nPuntos clave.\n\n'
        '---\n\nTranscripción:\n\n'
        'Hola a todos...\n\n'
        '---\n\n'
        'Obras vinculadas: Norte'
    )
    resumen, transcripcion = split_acta_contenido(raw)
    assert 'Puntos clave' in resumen
    assert 'Hola a todos' in transcripcion
    assert 'Obras vinculadas' not in transcripcion
    assert 'Transcripción' not in resumen


def test_split_acta_contenido_sin_marcador():
    resumen, transcripcion = split_acta_contenido('Solo texto escrito')
    assert resumen == 'Solo texto escrito'
    assert transcripcion == ''


def test_estimate_informe_page_count_nota_corta():
    assert estimate_informe_page_count('abcd', '') == 1
    assert estimate_informe_page_count('', '') == 1


def test_render_informe_html_sin_request_context():
    from pathlib import Path
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    templates = Path(__file__).resolve().parents[2] / 'app' / 'templates'
    env = Environment(
        loader=FileSystemLoader(str(templates)),
        autoescape=select_autoescape(['html', 'xml']),
    )
    mock_app = SimpleNamespace(
        jinja_env=env,
        logger=SimpleNamespace(
            warning=lambda *a, **k: None,
            info=lambda *a, **k: None,
        ),
    )
    nota = SimpleNamespace(
        id=27,
        titulo='Daily obra norte',
        contenido=(
            'Resumen amplio.\n\n---\n\nTranscripción:\n\n'
            'Acta <b>segura</b>\n\n---\n\nObras vinculadas: Norte'
        ),
        fecha=SimpleNamespace(strftime=lambda f: '04/10/2026'),
        es_privada=True,
        autor_id=1,
        autor=SimpleNamespace(name='Juan', lastname='Pérez', email='juan@empresa.com'),
        obras=[SimpleNamespace(nombre='Obra Norte')],
        usuarios_implicados=[],
    )
    with patch(
        'app.services.nota_informe_service.current_app',
        mock_app,
    ), patch(
        'app.services.nota_informe_service.get_organization_display_name',
        return_value='Soltec',
    ), patch(
        'app.services.nota_informe_service.logo_stripe_data_uri',
        return_value=None,
    ), patch(
        'app.services.nota_informe_service.header_data_uri',
        return_value=None,
    ), patch(
        'app.services.nota_informe_service.mark_data_uri',
        return_value='data:image/png;base64,aaa',
    ), patch(
        'app.services.nota_informe_service.get_brand_stripe_color',
        return_value='#1e3a5f',
    ):
        html_doc = render_informe_html(nota)
    assert 'Daily obra norte' in html_doc
    assert 'class="doc-title"' in html_doc
    assert 'Resumen amplio' in html_doc
    assert '&lt;b&gt;' in html_doc
    assert '<b>' not in html_doc.replace('&lt;b&gt;', '')
    assert 'Transcripción' in html_doc
    assert 'page-break-before' in html_doc
    assert 'class="page-stripe"' in html_doc
    assert 'width: 10mm' in html_doc
    assert 'class="page-wm"' in html_doc
    assert html_doc.count('class="page-stripe"') <= 5
    assert 'rotate(180deg)' in html_doc
    assert 'data:image/png;base64,aaa' in html_doc
    # Metadatos internos de la app: fuera del informe externo
    assert 'Documento generado automáticamente' not in html_doc
    assert 'Elaborado por' not in html_doc
    assert 'Personas implicadas' not in html_doc
    assert 'Visibilidad' not in html_doc
    assert 'Obras vinculadas' not in html_doc
    assert '#1e3a5f' in html_doc
    assert 'Soltec' in html_doc  # fallback sin imagen de cabecera


def test_send_informe_solo_autor():
    autor = SimpleNamespace(id=1, email='juan@empresa.com', name='Juan', lastname='Pérez')
    otro = SimpleNamespace(id=2, email='otro@empresa.com', name='Otro', lastname='')
    nota = SimpleNamespace(
        id=99,
        titulo='Daily',
        contenido='Acta',
        fecha=SimpleNamespace(strftime=lambda f: '01/01/2026'),
        es_privada=True,
        autor_id=1,
        autor=autor,
        obras=[],
        usuarios_implicados=[otro],
        informe_pdf_path=None,
        informe_pdf_nombre=None,
    )
    mock_app = SimpleNamespace(
        logger=SimpleNamespace(warning=lambda *a, **k: None, info=lambda *a, **k: None),
    )
    with patch('app.services.nota_informe_service.current_app', mock_app):
        with patch('app.services.nota_informe_service.Nota') as NotaModel:
            NotaModel.query.get.return_value = nota
            with patch(
                'app.services.nota_informe_service.render_informe_pdf_bytes',
                return_value=b'%PDF',
            ):
                with patch(
                    'app.services.nota_informe_service.persist_informe_pdf',
                    return_value='/tmp/informe.pdf',
                ) as persist:
                    with patch('app.services.nota_informe_service.send_email', return_value=True) as send:
                        ok = send_informe_to_author(99)
    assert ok is True
    persist.assert_called_once()
    send.assert_called_once()
    recipients = send.call_args[0][1]
    assert recipients == ['juan@empresa.com']


def test_send_informe_sin_email_persiste_pdf():
    autor = SimpleNamespace(id=1, email='', name='Juan', lastname='Pérez')
    nota = SimpleNamespace(
        id=100,
        titulo='Daily',
        contenido='Acta',
        fecha=SimpleNamespace(strftime=lambda f: '01/01/2026'),
        es_privada=True,
        autor_id=1,
        autor=autor,
        obras=[],
        usuarios_implicados=[],
        informe_pdf_path=None,
        informe_pdf_nombre=None,
    )
    mock_app = SimpleNamespace(
        logger=SimpleNamespace(warning=lambda *a, **k: None, info=lambda *a, **k: None),
    )
    with patch('app.services.nota_informe_service.current_app', mock_app):
        with patch('app.services.nota_informe_service.Nota') as NotaModel:
            NotaModel.query.get.return_value = nota
            with patch(
                'app.services.nota_informe_service.render_informe_pdf_bytes',
                return_value=b'%PDF',
            ):
                with patch(
                    'app.services.nota_informe_service.persist_informe_pdf',
                    return_value='/tmp/informe.pdf',
                ) as persist:
                    with patch('app.services.nota_informe_service.send_email') as send:
                        ok = send_informe_to_author(100)
    assert ok is True
    persist.assert_called_once()
    send.assert_not_called()
