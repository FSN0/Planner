"""Logos e identidad visual del tenant (informes, futuras pantallas)."""
from __future__ import annotations

import base64
import mimetypes
import os
import re

from flask import current_app, g
from werkzeug.utils import secure_filename

from app.services.config_service import get_tenant_config, set_tenant_config

CONFIG_BRAND_LOGO = 'brand_logo_filename'
CONFIG_BRAND_HEADER = 'brand_header_filename'
CONFIG_BRAND_MARK = 'brand_mark_filename'  # logo sin letras (marca de agua)
CONFIG_BRAND_REPORT_TITLE = 'brand_report_header_title'
CONFIG_BRAND_STRIPE_COLOR = 'brand_report_stripe_color'

ALLOWED_LOGO_EXTENSIONS = frozenset({'png', 'jpg', 'jpeg', 'webp', 'svg'})
MAX_LOGO_BYTES = 2 * 1024 * 1024
DEFAULT_STRIPE_COLOR = '#1e3a5f'


def _current_schema() -> str | None:
    tenant = getattr(g, 'current_tenant', None)
    return getattr(tenant, 'schema_name', None) if tenant else None


def get_tenant_branding_dir(schema_name: str | None = None) -> str:
    schema = schema_name or _current_schema() or 'default'
    safe = re.sub(r'[^a-zA-Z0-9_]', '', schema)
    base = os.path.join(current_app.root_path, '..', 'uploads', 'branding', safe)
    base = os.path.abspath(base)
    os.makedirs(base, exist_ok=True)
    return base


def _resolve_brand_file(config_key: str, schema_name: str | None = None) -> str | None:
    filename = (get_tenant_config(config_key, default='') or '').strip()
    if not filename:
        return None
    safe_name = secure_filename(filename)
    if not safe_name or safe_name != filename:
        return None
    path = os.path.join(get_tenant_branding_dir(schema_name), safe_name)
    if os.path.isfile(path):
        return path
    return None


def resolve_tenant_logo_path(schema_name: str | None = None) -> str | None:
    return _resolve_brand_file(CONFIG_BRAND_LOGO, schema_name)


def resolve_tenant_header_path(schema_name: str | None = None) -> str | None:
    return _resolve_brand_file(CONFIG_BRAND_HEADER, schema_name)


def resolve_tenant_mark_only_path(schema_name: str | None = None) -> str | None:
    """Solo el logo sin letras (sin fallback)."""
    return _resolve_brand_file(CONFIG_BRAND_MARK, schema_name)


def resolve_tenant_mark_path(schema_name: str | None = None) -> str | None:
    """Logo sin letras para marca de agua; si no hay, cae al logo normal."""
    path = resolve_tenant_mark_only_path(schema_name)
    if path:
        return path
    return resolve_tenant_logo_path(schema_name)


def _save_brand_file(file_storage, *, dest_stem: str, config_key: str) -> str:
    if not file_storage or not file_storage.filename:
        raise ValueError('No se recibió ningún archivo.')
    original = secure_filename(file_storage.filename)
    ext = original.rsplit('.', 1)[-1].lower() if '.' in original else ''
    if ext not in ALLOWED_LOGO_EXTENSIONS:
        raise ValueError('Formato no válido. Use PNG, JPG, WEBP o SVG.')

    file_storage.stream.seek(0, os.SEEK_END)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size > MAX_LOGO_BYTES:
        raise ValueError('El archivo supera el máximo de 2 MB.')

    dest_name = f'{dest_stem}.{ext}'
    dest_path = os.path.join(get_tenant_branding_dir(), dest_name)

    old = _resolve_brand_file(config_key)
    if old and os.path.abspath(old) != os.path.abspath(dest_path):
        try:
            os.remove(old)
        except OSError:
            pass

    file_storage.save(dest_path)
    set_tenant_config(config_key, dest_name)
    return dest_name


def save_tenant_logo(file_storage) -> str:
    return _save_brand_file(
        file_storage, dest_stem='logo', config_key=CONFIG_BRAND_LOGO,
    )


def save_tenant_header(file_storage) -> str:
    return _save_brand_file(
        file_storage, dest_stem='header', config_key=CONFIG_BRAND_HEADER,
    )


def save_tenant_mark(file_storage) -> str:
    return _save_brand_file(
        file_storage, dest_stem='mark', config_key=CONFIG_BRAND_MARK,
    )


def _clear_brand_file(config_key: str) -> None:
    path = _resolve_brand_file(config_key)
    if path:
        try:
            os.remove(path)
        except OSError:
            pass
    set_tenant_config(config_key, '')


def clear_tenant_logo() -> None:
    _clear_brand_file(CONFIG_BRAND_LOGO)


def clear_tenant_header() -> None:
    _clear_brand_file(CONFIG_BRAND_HEADER)


def clear_tenant_mark() -> None:
    _clear_brand_file(CONFIG_BRAND_MARK)


def normalize_stripe_color(raw: str | None) -> str:
    text = (raw or '').strip()
    if not text:
        return DEFAULT_STRIPE_COLOR
    if not text.startswith('#'):
        text = f'#{text}'
    if not re.fullmatch(r'#[0-9A-Fa-f]{6}', text):
        return DEFAULT_STRIPE_COLOR
    return text.lower()


def get_brand_stripe_color() -> str:
    return normalize_stripe_color(
        get_tenant_config(CONFIG_BRAND_STRIPE_COLOR, default=DEFAULT_STRIPE_COLOR)
    )


def set_brand_stripe_color(raw: str | None) -> str:
    color = normalize_stripe_color(raw)
    set_tenant_config(CONFIG_BRAND_STRIPE_COLOR, color)
    return color


def get_organization_display_name() -> str:
    custom = (get_tenant_config(CONFIG_BRAND_REPORT_TITLE, default='') or '').strip()
    if custom:
        return custom
    tenant = getattr(g, 'current_tenant', None)
    if tenant and getattr(tenant, 'nombre', None):
        return str(tenant.nombre).strip()
    return 'SignaPlan'


def _file_data_uri(path: str | None) -> str | None:
    if not path:
        return None
    mime, _ = mimetypes.guess_type(path)
    if not mime:
        ext = path.rsplit('.', 1)[-1].lower()
        mime = {
            'png': 'image/png',
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'webp': 'image/webp',
            'svg': 'image/svg+xml',
        }.get(ext, 'application/octet-stream')
    try:
        with open(path, 'rb') as fh:
            raw = fh.read()
    except OSError:
        return None
    encoded = base64.b64encode(raw).decode('ascii')
    return f'data:{mime};base64,{encoded}'


def logo_data_uri(schema_name: str | None = None) -> str | None:
    return _file_data_uri(resolve_tenant_logo_path(schema_name))


def logo_stripe_data_uri(schema_name: str | None = None) -> str | None:
    """
    Logo rotado 90° para la franja derecha del PDF.

    Se rota en PIL (no con CSS transform): transform dentro de
    position:fixed rompe la repetición por página en wkhtmltopdf.
    """
    path = resolve_tenant_logo_path(schema_name)
    if not path:
        return None
    try:
        from io import BytesIO

        from PIL import Image

        with Image.open(path) as src:
            im = src.convert('RGBA')
            # 90° antihorario → logo en vertical a lo largo del margen
            im = im.transpose(Image.Transpose.ROTATE_90)
            buf = BytesIO()
            im.save(buf, format='PNG', optimize=True)
        encoded = base64.b64encode(buf.getvalue()).decode('ascii')
        return f'data:image/png;base64,{encoded}'
    except Exception:
        return _file_data_uri(path)


def header_data_uri(schema_name: str | None = None) -> str | None:
    return _file_data_uri(resolve_tenant_header_path(schema_name))


def mark_data_uri(
    schema_name: str | None = None,
    *,
    opacity: float | None = None,
) -> str | None:
    """
    Marca de agua (logo sin letras si existe; si no, el logo normal).

    Si ``opacity`` está entre 0 y 1, se aplica al canal alfa del PNG.
    wkhtmltopdf a menudo ignora ``opacity`` en CSS; hornearlo en la imagen
    es lo que deja leer el texto debajo.
    """
    path = resolve_tenant_mark_path(schema_name)
    if not path:
        return None
    if opacity is None:
        return _file_data_uri(path)
    try:
        alpha = max(0.0, min(1.0, float(opacity)))
    except (TypeError, ValueError):
        return _file_data_uri(path)
    if alpha >= 0.999:
        return _file_data_uri(path)
    try:
        from io import BytesIO

        from PIL import Image

        with Image.open(path) as src:
            im = src.convert('RGBA')
            r, g, b, a = im.split()
            a = a.point(lambda p: int(p * alpha))
            out = Image.merge('RGBA', (r, g, b, a))
            buf = BytesIO()
            out.save(buf, format='PNG', optimize=True)
        encoded = base64.b64encode(buf.getvalue()).decode('ascii')
        return f'data:image/png;base64,{encoded}'
    except Exception:
        return _file_data_uri(path)
