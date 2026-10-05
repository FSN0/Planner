"""
Importación masiva (obras, personal, subcontratas) con detección de columnas,
previsualización y commit con informe por fila.
"""
from __future__ import annotations

import os
import re
import secrets
import uuid
from datetime import datetime, timedelta, date
from difflib import SequenceMatcher
from typing import Any, Optional

import pandas as pd
from flask import current_app
from sqlalchemy import func
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename

from app import db
from app.models import Obra, User, Company, ROLE_OPERARIO

ALLOWED_IMPORT_EXTENSIONS = {"xlsx", "xls", "csv"}

# ---------------------------------------------------------------------------
# Definición de campos por entidad (aliases en español / variantes comunes)
# ---------------------------------------------------------------------------

ENTITY_FIELDS = {
    "obras": [
        {
            "key": "codigo",
            "label": "Código",
            "required": False,
            "aliases": [
                "codigo", "código", "code", "cod", "cod obra", "codigo obra",
                "nº", "num", "número", "referencia", "ref",
            ],
        },
        {
            "key": "nombre",
            "label": "Nombre",
            "required": True,
            "aliases": [
                "nombre", "name", "obra", "titulo", "título", "denominacion",
                "denominación", "proyecto",
            ],
        },
        {
            "key": "cliente",
            "label": "Cliente",
            "required": False,
            "aliases": [
                "cliente", "client", "customer", "promotor", "propietario",
            ],
        },
        {
            "key": "direccion",
            "label": "Dirección",
            "required": False,
            "aliases": [
                "direccion", "dirección", "ubicacion", "ubicación", "address",
                "localizacion", "localización", "sitio", "emplazamiento",
            ],
        },
        {
            "key": "fecha_inicio",
            "label": "Fecha de inicio",
            "required": False,
            "aliases": [
                "fecha de inicio", "fecha inicio", "inicio", "start",
                "start date", "f inicio", "fecha_inicio", "comienzo",
            ],
        },
        {
            "key": "fecha_fin",
            "label": "Fecha de fin",
            "required": False,
            "aliases": [
                "fecha de fin", "fecha fin", "fin", "end", "end date",
                "f fin", "fecha_fin", "finalizacion", "finalización",
            ],
        },
    ],
    "users": [
        {
            "key": "email",
            "label": "Email",
            "required": True,
            "aliases": [
                "email", "e-mail", "correo", "correo electronico",
                "correo electrónico", "mail",
            ],
        },
        {
            "key": "rol",
            "label": "Rol",
            "required": False,
            "aliases": ["rol", "role", "perfil", "cargo", "tipo"],
        },
        {
            "key": "nombre",
            "label": "Nombre",
            "required": True,
            "aliases": ["nombre", "name", "first name", "nombre de pila"],
        },
        {
            "key": "apellidos",
            "label": "Apellidos",
            "required": True,
            "aliases": [
                "apellidos", "apellido", "lastname", "last name", "surname",
            ],
        },
        {
            "key": "dni",
            "label": "DNI",
            "required": True,
            "aliases": [
                "dni", "nif", "nie", "documento", "doc", "identificacion",
                "identificación", "id",
            ],
        },
        {
            "key": "empresa",
            "label": "Empresa",
            "required": False,
            "aliases": [
                "empresa", "company", "compañia", "compañía", "subcontrata",
                "empleador",
            ],
        },
        {
            "key": "password",
            "label": "Contraseña",
            "required": False,
            "aliases": [
                "contraseña", "contrasena", "password", "clave", "pass", "pwd",
            ],
        },
        {
            "key": "pin",
            "label": "PIN fichaje",
            "required": False,
            "aliases": [
                "pin", "pin fichaje", "pin_fichaje", "clave fichaje", "codigo pin",
            ],
        },
        {
            "key": "activo",
            "label": "Activo",
            "required": False,
            "aliases": ["activo", "active", "activado", "habilitado"],
        },
        {
            "key": "recibir_emails",
            "label": "Recibir emails",
            "required": False,
            "aliases": [
                "recibir notificaciones por email", "recibir emails",
                "recibir email", "notificaciones", "receive emails",
            ],
        },
    ],
    "companies": [
        {
            "key": "nombre",
            "label": "Nombre",
            "required": True,
            "aliases": [
                "nombre", "name", "empresa", "razon social", "razón social",
                "subcontrata", "company",
            ],
        },
        {
            "key": "nif",
            "label": "NIF",
            "required": False,
            "aliases": ["nif", "cif", "vat", "tax id", "documento fiscal"],
        },
        {
            "key": "code",
            "label": "Código",
            "required": False,
            "aliases": [
                "codigo", "código", "code", "cod", "abreviatura", "siglas",
            ],
        },
        {
            "key": "gremio",
            "label": "Gremio",
            "required": False,
            "aliases": [
                "gremio", "especialidad", "oficio", "actividad", "trade",
                "sector",
            ],
        },
        {
            "key": "email",
            "label": "Email",
            "required": False,
            "aliases": [
                "email", "e-mail", "correo", "correo electronico",
                "correo electrónico", "mail", "contacto",
            ],
        },
        {
            "key": "descripcion",
            "label": "Descripción",
            "required": False,
            "aliases": [
                "descripcion", "descripción", "description", "notas", "obs",
                "observaciones",
            ],
        },
        {
            "key": "is_internal",
            "label": "Interna",
            "required": False,
            "aliases": [
                "interna", "is_internal", "internal", "propia", "empresa propia",
            ],
        },
    ],
}

ENTITY_LABELS = {
    "obras": "Obras",
    "users": "Personal",
    "companies": "Subcontratas",
}

PREVIEW_SAMPLE_ROWS = 500  # Editable: mostrar (casi) todas las filas


# ---------------------------------------------------------------------------
# Normalización / fuzzy match
# ---------------------------------------------------------------------------

def _normalize_header(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip().lower()
    text = (
        text.replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
        .replace("ü", "u")
        .replace("ñ", "n")
    )
    text = re.sub(r"[_\-./\\]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.92
    return SequenceMatcher(None, a, b).ratio()


def detect_columns(dataframe: pd.DataFrame, entity_type: str = "obras") -> dict:
    """
    Empareja cabeceras del DataFrame con campos de la entidad.
    Retorna dict field_key -> nombre_columna_original (o None).
    """
    if entity_type not in ENTITY_FIELDS:
        raise ValueError(f"Tipo de entidad no soportado: {entity_type}")

    columns = list(dataframe.columns)
    norm_cols = {_normalize_header(c): c for c in columns}
    used_cols = set()
    mapping: dict[str, Optional[str]] = {}

    for field in ENTITY_FIELDS[entity_type]:
        best_col = None
        best_score = 0.0
        aliases = [_normalize_header(a) for a in field["aliases"]]
        aliases.append(_normalize_header(field["label"]))
        aliases.append(_normalize_header(field["key"]))

        for norm_header, original in norm_cols.items():
            if original in used_cols or not norm_header:
                continue
            score = max(_similarity(norm_header, alias) for alias in aliases)
            if score > best_score:
                best_score = score
                best_col = original

        # Umbral: coincidencia exacta/substring o fuzzy razonable
        if best_col is not None and best_score >= 0.72:
            mapping[field["key"]] = best_col
            used_cols.add(best_col)
        else:
            mapping[field["key"]] = None

    return mapping


def get_entity_fields(entity_type: str) -> list:
    return list(ENTITY_FIELDS.get(entity_type, []))


# ---------------------------------------------------------------------------
# Lectura de ficheros y almacenamiento temporal
# ---------------------------------------------------------------------------

def allowed_import_file(filename: str) -> bool:
    return (
        bool(filename)
        and "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_IMPORT_EXTENSIONS
    )


def get_imports_dir() -> str:
    base = os.path.join(current_app.root_path, "..", "uploads", "imports")
    base = os.path.abspath(base)
    os.makedirs(base, exist_ok=True)
    return base


def save_import_upload(file_storage) -> tuple[str, str]:
    """
    Guarda el fichero subido con nombre aleatorio.
    Retorna (token, extension).
    """
    original = secure_filename(file_storage.filename or "import.xlsx")
    ext = original.rsplit(".", 1)[-1].lower() if "." in original else "xlsx"
    if ext not in ALLOWED_IMPORT_EXTENSIONS:
        raise ValueError("Formato no soportado. Use .xlsx o .csv")

    token = uuid.uuid4().hex
    path = os.path.join(get_imports_dir(), f"{token}.{ext}")
    file_storage.save(path)
    return token, ext


def resolve_import_path(token: str, ext: str) -> str:
    safe_token = re.sub(r"[^a-zA-Z0-9]", "", token or "")
    safe_ext = (ext or "xlsx").lower()
    if safe_ext not in ALLOWED_IMPORT_EXTENSIONS or not safe_token:
        raise ValueError("Token de importación inválido")
    path = os.path.join(get_imports_dir(), f"{safe_token}.{safe_ext}")
    if not os.path.isfile(path):
        raise FileNotFoundError("El archivo temporal de importación no existe o ha caducado.")
    return path


def cleanup_import_file(token: str, ext: str) -> None:
    try:
        path = resolve_import_path(token, ext)
        os.remove(path)
    except (ValueError, FileNotFoundError, OSError):
        pass


def read_import_dataframe(file_or_path) -> pd.DataFrame:
    """Lee CSV o Excel desde path, file-like o FileStorage."""
    name = ""
    if isinstance(file_or_path, str):
        name = file_or_path
        path = file_or_path
        if name.lower().endswith(".csv"):
            return pd.read_csv(path)
        return pd.read_excel(path)

    filename = getattr(file_or_path, "filename", "") or ""
    if str(filename).lower().endswith(".csv"):
        return pd.read_csv(file_or_path)
    return pd.read_excel(file_or_path)


def _cell_str(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value).strip()
    if text.lower() in ("nan", "none", "nat", "<na>"):
        return ""
    return text


def _parse_bool(value: Any, default: bool = False) -> bool:
    text = _cell_str(value).lower()
    if not text:
        return default
    return text in ("si", "sí", "yes", "y", "true", "1", "activo", "x", "on")


def _parse_date(value: Any) -> Optional[date]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if hasattr(value, "date") and callable(value.date):
        try:
            return value.date()
        except Exception:
            pass
    text = _cell_str(value)
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    try:
        parsed = pd.to_datetime(value, dayfirst=True, errors="coerce")
        if pd.isna(parsed):
            return None
        return parsed.date()
    except Exception:
        return None


def _mapped_value(row: pd.Series, column_map: dict, field_key: str) -> Any:
    col = column_map.get(field_key)
    if not col or col not in row.index:
        return None
    return row.get(col)


def _normalize_column_map(column_map: Optional[dict], dataframe: pd.DataFrame, entity_type: str) -> dict:
    if not column_map:
        return detect_columns(dataframe, entity_type)
    normalized = {}
    valid_cols = set(str(c) for c in dataframe.columns)
    for field in ENTITY_FIELDS[entity_type]:
        key = field["key"]
        raw = column_map.get(key)
        if raw in (None, "", "__none__"):
            normalized[key] = None
        elif str(raw) in valid_cols:
            normalized[key] = str(raw)
        else:
            # Intentar match por nombre normalizado
            target = _normalize_header(raw)
            match = next(
                (c for c in dataframe.columns if _normalize_header(c) == target),
                None,
            )
            normalized[key] = match
    return normalized


# ---------------------------------------------------------------------------
# Validación / preview por fila (sin commit)
# ---------------------------------------------------------------------------

def _preview_obra_row(row: pd.Series, column_map: dict, row_number: int) -> dict:
    codigo = _cell_str(_mapped_value(row, column_map, "codigo"))
    nombre = _cell_str(_mapped_value(row, column_map, "nombre"))
    cliente = _cell_str(_mapped_value(row, column_map, "cliente"))
    direccion = _cell_str(_mapped_value(row, column_map, "direccion"))
    fecha_inicio = _parse_date(_mapped_value(row, column_map, "fecha_inicio"))
    fecha_fin = _parse_date(_mapped_value(row, column_map, "fecha_fin"))

    data = {
        "codigo": codigo,
        "nombre": nombre,
        "cliente": cliente,
        "direccion": direccion,
        "fecha_inicio": fecha_inicio.isoformat() if fecha_inicio else "",
        "fecha_fin": fecha_fin.isoformat() if fecha_fin else "",
    }
    messages: list[str] = []

    # Fila vacía
    if not any([codigo, nombre, cliente, direccion, fecha_inicio]):
        return {
            "row_number": row_number,
            "status": "skip",
            "messages": ["Fila vacía"],
            "data": data,
        }

    if not nombre:
        messages.append("Falta el nombre de la obra")

    if messages:
        return {
            "row_number": row_number,
            "status": "error",
            "messages": messages,
            "data": data,
        }

    if not fecha_inicio:
        fecha_inicio = date.today()
        data["fecha_inicio"] = fecha_inicio.isoformat()
        messages.append("Sin fecha de inicio; se usará hoy")

    if not fecha_fin:
        fecha_fin = fecha_inicio + timedelta(days=365)
        data["fecha_fin"] = fecha_fin.isoformat()
        messages.append("Sin fecha de fin; se usará un año después del inicio")
    # Si viene fecha de fin (aunque sea pasada), se respeta tal cual.

    if codigo:
        existing = Obra.query.filter(func.lower(Obra.codigo) == codigo.lower()).first()
        if existing:
            return {
                "row_number": row_number,
                "status": "duplicate",
                "messages": [f"Ya existe una obra con código «{codigo}»"],
                "data": data,
            }
        if len(codigo) > _OBRA_LIMITS["codigo"]:
            messages.append(
                f"Código demasiado largo ({len(codigo)}>{_OBRA_LIMITS['codigo']}); se acortará al importar"
            )

    if len(nombre) > _OBRA_LIMITS["nombre"]:
        messages.append(
            f"Nombre demasiado largo ({len(nombre)}>{_OBRA_LIMITS['nombre']}); se acortará al importar"
        )
    if len(cliente) > _OBRA_LIMITS["cliente"]:
        messages.append(
            f"Cliente demasiado largo ({len(cliente)}>{_OBRA_LIMITS['cliente']}); "
            "se acortará en ficha y el texto completo irá a descripción"
        )
    if len(direccion) > _OBRA_LIMITS["ubicacion"]:
        messages.append(
            f"Dirección demasiado larga ({len(direccion)}>{_OBRA_LIMITS['ubicacion']}); se acortará al importar"
        )

    # Avisos de longitud no bloquean: status sigue 'new'
    return {
        "row_number": row_number,
        "status": "new",
        "messages": messages,
        "data": data,
        "_parsed": {
            "codigo": codigo or None,
            "nombre": nombre,
            "cliente": cliente or None,
            "direccion": direccion or None,
            "fecha_inicio": fecha_inicio,
            "fecha_fin": fecha_fin,
        },
    }


def _normalize_role(raw: str) -> str:
    from app.models import ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL, ROLE_OPERARIO, ROLE_RRHH

    role = (raw or "").strip().lower().replace(" ", "_")
    aliases = {
        "operario": ROLE_OPERARIO,
        "trabajador": ROLE_OPERARIO,
        "empleado": ROLE_OPERARIO,
        "oficial": ROLE_OPERARIO,
        "peon": ROLE_OPERARIO,
        "peón": ROLE_OPERARIO,
        "admin": ROLE_ADMIN,
        "administrador": ROLE_ADMIN,
        "jefe": ROLE_JEFE,
        "jefe_obra": ROLE_JEFE,
        "jefe_de_obra": ROLE_JEFE,
        "jefe de obra": ROLE_JEFE,
        "rrhh": ROLE_RRHH,
        "recursos_humanos": ROLE_RRHH,
        "laboral": ROLE_LABORAL,
    }
    if not role:
        return ROLE_OPERARIO
    mapped = aliases.get(role, role)
    known = {ROLE_OPERARIO, ROLE_JEFE, ROLE_ADMIN, ROLE_LABORAL, ROLE_RRHH}
    # Roles inventados del Excel → operario (si no, no pueden tener PIN)
    if mapped not in known:
        return ROLE_OPERARIO
    return mapped


def _preview_user_row(row: pd.Series, column_map: dict, row_number: int) -> dict:
    email = _cell_str(_mapped_value(row, column_map, "email")).lower()
    rol_raw = _cell_str(_mapped_value(row, column_map, "rol"))
    rol = _normalize_role(rol_raw)
    nombre = _cell_str(_mapped_value(row, column_map, "nombre"))
    apellidos = _cell_str(_mapped_value(row, column_map, "apellidos"))
    dni = _cell_str(_mapped_value(row, column_map, "dni")).upper().replace(" ", "")
    empresa = _cell_str(_mapped_value(row, column_map, "empresa"))
    password = _cell_str(_mapped_value(row, column_map, "password"))
    pin = _cell_str(_mapped_value(row, column_map, "pin"))
    # Activo por defecto: si no, el paso 2 de primeros pasos no cuenta la plantilla
    activo = _parse_bool(_mapped_value(row, column_map, "activo"), default=True)
    recibir = _parse_bool(_mapped_value(row, column_map, "recibir_emails"), default=True)

    data = {
        "email": email,
        "rol": rol,
        "nombre": nombre,
        "apellidos": apellidos,
        "dni": dni,
        "empresa": empresa,
        "pin": "sí" if pin else "auto",
        "activo": "Sí" if activo else "No",
        "recibir_emails": "Sí" if recibir else "No",
    }
    errors: list[str] = []
    warnings: list[str] = []

    if rol_raw and _normalize_role(rol_raw) == ROLE_OPERARIO:
        raw_l = rol_raw.strip().lower().replace(" ", "_")
        if raw_l not in (
            ROLE_OPERARIO, "trabajador", "empleado", "oficial", "peon", "peón", ""
        ):
            from app.models import ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL, ROLE_RRHH
            known_aliases = {
                ROLE_OPERARIO, "trabajador", "empleado", "oficial", "peon", "peón",
                ROLE_ADMIN, "administrador", ROLE_JEFE, "jefe", "jefe_obra", "jefe_de_obra",
                ROLE_RRHH, "recursos_humanos", ROLE_LABORAL,
            }
            if raw_l not in known_aliases:
                # Aviso informativo: el rol queda como Operario y SÍ se puede importar
                warnings.append(f"Rol «{rol_raw}» no reconocido → Operario")

    if not any([email, nombre, apellidos, dni, empresa]):
        return {
            "row_number": row_number,
            "status": "skip",
            "messages": ["Fila vacía"],
            "data": data,
        }

    if not email:
        errors.append("Falta el email")
    elif "@" not in email:
        errors.append("Email inválido")
    if not dni:
        errors.append("Falta el DNI")
    if not nombre:
        errors.append("Falta el nombre")
    if not apellidos:
        errors.append("Faltan los apellidos")

    if errors:
        return {
            "row_number": row_number,
            "status": "error",
            "messages": errors + warnings,
            "data": data,
        }

    existing = User.query.filter(
        (func.lower(User.email) == email) | (func.upper(User.dni) == dni)
    ).first()
    if existing:
        reason = []
        if existing.email and existing.email.lower() == email:
            reason.append("email")
        if existing.dni and existing.dni.upper() == dni:
            reason.append("DNI")
        return {
            "row_number": row_number,
            "status": "duplicate",
            "messages": [f"Usuario ya existe ({' y '.join(reason)})"],
            "data": data,
        }

    return {
        "row_number": row_number,
        "status": "new",
        "messages": warnings,
        "data": data,
        "_parsed": {
            "email": email,
            "rol": rol,
            "nombre": nombre,
            "apellidos": apellidos,
            "dni": dni,
            "empresa": empresa,
            "password": password,
            "pin": pin,
            "activo": activo,
            "recibir_emails": recibir,
        },
    }


def _preview_company_row(row: pd.Series, column_map: dict, row_number: int) -> dict:
    nombre = _cell_str(_mapped_value(row, column_map, "nombre"))
    nif = _cell_str(_mapped_value(row, column_map, "nif")).upper().replace(" ", "")
    code = _cell_str(_mapped_value(row, column_map, "code")).upper().replace(" ", "")
    gremio = _cell_str(_mapped_value(row, column_map, "gremio"))
    email = _cell_str(_mapped_value(row, column_map, "email")).lower()
    descripcion = _cell_str(_mapped_value(row, column_map, "descripcion"))
    is_internal = _parse_bool(_mapped_value(row, column_map, "is_internal"), default=False)

    data = {
        "nombre": nombre,
        "nif": nif,
        "code": code,
        "gremio": gremio,
        "email": email,
        "descripcion": descripcion,
        "is_internal": "Sí" if is_internal else "No",
    }

    if not any([nombre, nif, code, gremio, email]):
        return {
            "row_number": row_number,
            "status": "skip",
            "messages": ["Fila vacía"],
            "data": data,
        }

    if not nombre:
        return {
            "row_number": row_number,
            "status": "error",
            "messages": ["Falta el nombre de la empresa"],
            "data": data,
        }

    messages: list[str] = []
    if nif:
        dup_nif = Company.query.filter(func.upper(Company.nif) == nif).first()
        if dup_nif:
            return {
                "row_number": row_number,
                "status": "duplicate",
                "messages": [f"Ya existe una empresa con NIF «{nif}»"],
                "data": data,
            }
    if code:
        dup_code = Company.query.filter(func.upper(Company.code) == code).first()
        if dup_code:
            return {
                "row_number": row_number,
                "status": "duplicate",
                "messages": [f"Ya existe una empresa con código «{code}»"],
                "data": data,
            }

    dup_name = Company.query.filter(func.lower(Company.nombre) == nombre.lower()).first()
    if dup_name:
        return {
            "row_number": row_number,
            "status": "duplicate",
            "messages": [f"Ya existe una empresa llamada «{nombre}»"],
            "data": data,
        }

    return {
        "row_number": row_number,
        "status": "new",
        "messages": messages,
        "data": data,
        "_parsed": {
            "nombre": nombre,
            "nif": nif or None,
            "code": code or None,
            "gremio": gremio or None,
            "email": email or None,
            "descripcion": descripcion or None,
            "is_internal": is_internal,
        },
    }


_PREVIEW_HANDLERS = {
    "obras": _preview_obra_row,
    "users": _preview_user_row,
    "companies": _preview_company_row,
}


def _build_row_previews(df: pd.DataFrame, entity_type: str, column_map: dict) -> list[dict]:
    handler = _PREVIEW_HANDLERS[entity_type]
    rows = []
    for idx, row in df.iterrows():
        # Excel/CSV: fila 1 = cabecera → datos empiezan en 2
        row_number = int(idx) + 2 if isinstance(idx, (int, float)) else len(rows) + 2
        try:
            preview = handler(row, column_map, row_number)
        except Exception as exc:
            preview = {
                "row_number": row_number,
                "status": "error",
                "messages": [f"Error al procesar la fila: {exc}"],
                "data": {},
            }
        rows.append(preview)
    return rows


def _summarize_rows(rows: list[dict]) -> dict:
    summary = {"new": 0, "duplicate": 0, "error": 0, "skip": 0, "created": 0}
    for r in rows:
        status = r.get("status", "error")
        if status in summary:
            summary[status] += 1
        else:
            summary["error"] += 1
    return summary


def preview_import(file_or_path, entity_type: str, column_map: Optional[dict] = None) -> dict:
    """
    Analiza el fichero sin escribir en BD.
    Retorna columnas, mapeo, filas con status y resumen.
    """
    if entity_type not in ENTITY_FIELDS:
        return {
            "success": False,
            "message": f"Tipo de entidad no soportado: {entity_type}",
            "columns": [],
            "column_map": {},
            "fields": [],
            "rows": [],
            "sample_rows": [],
            "summary": {},
        }

    try:
        df = read_import_dataframe(file_or_path)
    except Exception as exc:
        return {
            "success": False,
            "message": f"Error al leer el archivo: {exc}",
            "columns": [],
            "column_map": {},
            "fields": get_entity_fields(entity_type),
            "rows": [],
            "sample_rows": [],
            "summary": {},
        }

    # Normalizar nombres de columna a str
    df.columns = [str(c).strip() if c is not None else f"col_{i}" for i, c in enumerate(df.columns)]
    column_map = _normalize_column_map(column_map, df, entity_type)
    rows = _build_row_previews(df, entity_type, column_map)
    summary = _summarize_rows(rows)

    # Para la UI: filas sin _parsed y muestra limitada
    public_rows = []
    for r in rows:
        public_rows.append({
            "row_number": r["row_number"],
            "status": r["status"],
            "messages": r.get("messages") or [],
            "data": r.get("data") or {},
        })

    return {
        "success": True,
        "message": "Previsualización lista",
        "columns": list(df.columns),
        "column_map": column_map,
        "fields": get_entity_fields(entity_type),
        "rows": public_rows,
        "sample_rows": public_rows[:PREVIEW_SAMPLE_ROWS],
        "summary": summary,
        "_internal_rows": rows,
        "_dataframe": df,
    }


# ---------------------------------------------------------------------------
# Commit
# ---------------------------------------------------------------------------

# Límites reales del modelo Obra (app.models.Obra)
_OBRA_LIMITS = {
    "codigo": 20,
    "nombre": 100,
    "cliente": 100,
    "ubicacion": 100,
}


def _clip_str(value, max_len: int) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) <= max_len:
        return text
    return text[:max_len].rstrip()


def _estado_obra_import(fecha_inicio: Optional[date], fecha_fin: Optional[date]) -> str:
    """En Curso si el día de hoy cae en el intervalo; si no, Pendiente."""
    if not fecha_inicio:
        return "Pendiente"
    today = date.today()
    fin = fecha_fin or (fecha_inicio + timedelta(days=365))
    if fecha_inicio <= today <= fin:
        return "En Curso"
    return "Pendiente"


def _friendly_import_error(exc: BaseException) -> str:
    """Mensaje legible; nunca volcar SQLAlchemy/psycopg2 al usuario."""
    if isinstance(exc, ValueError):
        return str(exc)
    raw = str(exc) or ""
    low = raw.lower()
    if (
        "stringdatarighttruncation" in low
        or "value too long" in low
        or "character varying" in low
    ):
        return (
            "Un texto es demasiado largo para la base de datos "
            "(código máx. 20; nombre/cliente/ubicación máx. 100). "
            "Acórtalo en la vista previa e inténtalo de nuevo."
        )
    if "unique" in low or "duplicate" in low:
        return "Ya existe un registro con el mismo código o identificador."
    return "No se pudo guardar esta fila. Revisa los datos e inténtalo de nuevo."


def _commit_obra(parsed: dict) -> dict:
    """Crea la obra respetando límites de columna. Devuelve resumen para la UI."""
    codigo_full = (parsed.get("codigo") or "") or ""
    nombre_full = parsed.get("nombre") or ""
    cliente_full = (parsed.get("cliente") or "") or ""
    ubicacion_full = (parsed.get("direccion") or "") or ""

    codigo = _clip_str(codigo_full, _OBRA_LIMITS["codigo"])
    nombre = _clip_str(nombre_full, _OBRA_LIMITS["nombre"])
    cliente = _clip_str(cliente_full, _OBRA_LIMITS["cliente"])
    ubicacion = _clip_str(ubicacion_full, _OBRA_LIMITS["ubicacion"])

    if not nombre:
        raise ValueError("Falta el nombre de la obra")

    # El cliente completo (si era largo) va a descripción (Text); en cliente, versión corta.
    if len(cliente_full) > _OBRA_LIMITS["cliente"]:
        descripcion = cliente_full
    else:
        descripcion = cliente_full or None

    fecha_inicio = parsed["fecha_inicio"]
    fecha_fin = parsed["fecha_fin"]
    obra = Obra(
        codigo=codigo,
        nombre=nombre,
        cliente=cliente,
        ubicacion=ubicacion,
        descripcion=descripcion,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        estado=_estado_obra_import(fecha_inicio, fecha_fin),
        jefe_obra_id=None,
        fecha_importacion=datetime.utcnow(),
    )
    db.session.add(obra)
    return {
        "codigo": codigo or "",
        "nombre": nombre,
    }


def _ensure_company_for_user(
    empresa_nombre: str,
    *,
    mode: str | None = None,
    force_company_id: int | None = None,
) -> tuple[Optional[Company], bool]:
    """
    mode:
      - 'internos': siempre la empresa interna del tenant (ignora texto Excel)
      - 'externos': si force_company_id → esa; si no, match/crear por nombre (externa)
      - None: comportamiento legado (match o crear externa)
    """
    mode = (mode or '').strip().lower() or None

    if mode == 'internos':
        internal = Company.query.filter_by(is_internal=True).order_by(Company.id).first()
        if not internal:
            raise ValueError(
                'No hay empresa interna configurada. Crea o marca una empresa como interna.'
            )
        return internal, False

    if force_company_id:
        forced = Company.query.get(int(force_company_id))
        if not forced:
            raise ValueError('La empresa seleccionada no existe.')
        return forced, False

    if not empresa_nombre:
        return None, False
    comp = Company.query.filter(func.lower(Company.nombre) == empresa_nombre.lower()).first()
    if comp:
        return comp, False

    code_gen = re.sub(r"[^A-Z0-9]", "", empresa_nombre.upper())[:10] or "EMP"
    if Company.query.filter_by(code=code_gen).first():
        code_gen = f"{code_gen}{datetime.now().strftime('%S')}"[:20]

    comp = Company(code=code_gen, nombre=empresa_nombre, is_internal=False)
    db.session.add(comp)
    db.session.flush()
    return comp, True


def _commit_user(parsed: dict, *, import_options: Optional[dict] = None) -> dict:
    from app.services.pin_auth_service import (
        PinAuthError,
        asignar_pin_explicito,
        asignar_pin_generado,
    )
    from app.models import ROLE_ADMIN, ROLE_JEFE, ROLE_LABORAL, ROLE_OPERARIO, ROLE_RRHH

    opts = import_options or {}
    mode = opts.get('mode')
    force_company_id = opts.get('force_company_id')

    empresa_txt = parsed.get("empresa") or ""
    if mode == 'internos':
        # El nombre visible en resultado será el de la empresa interna
        internal = Company.query.filter_by(is_internal=True).order_by(Company.id).first()
        empresa_txt = internal.nombre if internal else empresa_txt

    comp, company_created = _ensure_company_for_user(
        empresa_txt if mode != 'internos' else '',
        mode=mode,
        force_company_id=force_company_id if mode == 'externos' else None,
    )
    if mode == 'internos' and comp:
        empresa_txt = comp.nombre
    elif mode == 'externos' and force_company_id and comp:
        empresa_txt = comp.nombre

    pwd = parsed.get("password") or secrets.token_urlsafe(16)
    role = _normalize_role(parsed.get("rol") or ROLE_OPERARIO)
    # Importación internos/externos: plantilla de obra → operario salvo jefe/admin explícito
    if mode in ('internos', 'externos') and role not in (ROLE_OPERARIO, ROLE_JEFE, ROLE_ADMIN):
        role = ROLE_OPERARIO

    # Personal importado activo salvo Excel/preview diga No
    activo = True if parsed.get("activo") is None else bool(parsed.get("activo"))
    if mode in ('internos', 'externos'):
        activo = bool(parsed.get("activo", True))

    new_user = User(
        email=parsed["email"],
        password_hash=generate_password_hash(pwd),
        role=role,
        name=parsed["nombre"],
        lastname=parsed["apellidos"],
        dni=parsed["dni"],
        company_id=comp.id if comp else None,
        active=activo,
        email_verified=True,
        receive_emails=bool(parsed.get("recibir_emails", True)),
    )
    db.session.add(new_user)
    db.session.flush()

    pin_plano = None
    pin_mode = None
    pin_mail = False
    assign_pin = opts.get('assign_pin', True)
    notify_pin = opts.get('notify_pin', True)
    if assign_pin and role in (ROLE_OPERARIO, ROLE_JEFE, ROLE_ADMIN, ROLE_LABORAL, ROLE_RRHH):
        pin_in = (parsed.get("pin") or "").strip()
        try:
            if pin_in:
                asignar_pin_explicito(new_user, pin_in, notify=bool(notify_pin))
                pin_plano = pin_in
                pin_mode = "explicit"
            else:
                _, pin_plano = asignar_pin_generado(new_user, notify=bool(notify_pin))
                pin_mode = "generated"
            pin_mail = bool(notify_pin)
        except PinAuthError:
            pin_plano = None
            pin_mode = "error"

    return {
        "email": parsed["email"],
        "role": role,
        "name": parsed["nombre"],
        "lastname": parsed["apellidos"],
        "dni": parsed["dni"],
        "empresa": empresa_txt or (comp.nombre if comp else ""),
        "company_created": company_created,
        "active": activo,
        "receive_emails": bool(parsed.get("recibir_emails", True)),
        "pin": pin_plano,
        "pin_mode": pin_mode,
        "pin_mail": pin_mail,
    }


def _commit_company(parsed: dict) -> None:
    code = parsed.get("code")
    if not code:
        base = re.sub(r"[^A-Z0-9]", "", (parsed["nombre"] or "").upper())[:10] or "AUTO"
        code = base
        if Company.query.filter_by(code=code).first():
            code = f"AUTO-{uuid.uuid4().hex[:6].upper()}"

    company = Company(
        code=code,
        nombre=parsed["nombre"],
        nif=parsed.get("nif"),
        gremio=parsed.get("gremio"),
        email=parsed.get("email"),
        descripcion=parsed.get("descripcion"),
        is_internal=bool(parsed.get("is_internal")),
        color="#ffffff",
    )
    db.session.add(company)


def annotate_user_rows_for_mode(rows: list, import_options: Optional[dict] = None) -> list:
    """Ajusta mensajes/empresa visible según modo internos/externos (sin tocar BD)."""
    opts = import_options or {}
    mode = (opts.get('mode') or '').strip().lower()
    force_id = opts.get('force_company_id')
    if not mode:
        return rows

    internal = Company.query.filter_by(is_internal=True).order_by(Company.id).first()
    forced = Company.query.get(int(force_id)) if force_id else None

    out = []
    for row in rows:
        r = dict(row)
        data = dict(r.get('data') or {})
        msgs = list(r.get('messages') or [])
        parsed = dict(r.get('_parsed') or {})

        if mode == 'internos':
            if not internal:
                if r.get('status') == 'new':
                    r['status'] = 'error'
                    msgs.append('No hay empresa interna en el sistema')
            else:
                data['empresa'] = internal.nombre
                parsed['empresa'] = internal.nombre
                if r.get('status') == 'new':
                    msgs = [m for m in msgs if 'empresa' not in m.lower()]
                    msgs.append(f'Empresa interna: {internal.nombre}')
        elif mode == 'externos':
            if forced:
                data['empresa'] = forced.nombre
                parsed['empresa'] = forced.nombre
                if r.get('status') == 'new':
                    msgs.append(f'Empresa forzada: {forced.nombre}')
            elif not (data.get('empresa') or '').strip():
                if r.get('status') == 'new':
                    # Se creará al confirmar si hay texto; sin texto → sin empresa
                    msgs.append('Sin empresa en Excel: se importará sin empresa (o créala en el texto)')
            else:
                if r.get('status') == 'new':
                    existing = Company.query.filter(
                        func.lower(Company.nombre) == data['empresa'].lower()
                    ).first()
                    if existing:
                        msgs.append(f'Empresa existente: {existing.nombre}')
                    else:
                        msgs.append(f'Se creará empresa externa «{data["empresa"]}»')

        r['data'] = data
        r['messages'] = msgs
        if parsed:
            r['_parsed'] = parsed
        out.append(r)
    return out


def apply_row_edits(entity_type: str, internal_rows: list, form) -> list:
    """
    Aplica ediciones de la vista previa (edit_{row}_{field}).
    Revalida filas tocadas.
    """
    fields = ENTITY_FIELDS.get(entity_type) or []
    editable_keys = [
        f['key'] for f in fields
        if f['key'] not in ('password',)  # no editar contraseña en preview
    ]
    result = []
    for row in internal_rows:
        rn = row.get('row_number')
        edits = {}
        for key in editable_keys:
            form_key = f'edit_{rn}_{key}'
            if form_key in form:
                edits[key] = (form.get(form_key) or '').strip()
        if not edits:
            result.append(row)
            continue

        data = dict(row.get('data') or {})
        data.update(edits)

        if entity_type == 'obras':
            rebuilt = _rebuild_obra_from_data(rn, data)
        elif entity_type == 'users':
            # Conservar password/pin del parse original si no se editan
            parsed_old = row.get('_parsed') or {}
            rebuilt = _rebuild_user_from_data(rn, data, parsed_old)
        elif entity_type == 'companies':
            rebuilt = _rebuild_company_from_data(rn, data)
        else:
            result.append(row)
            continue
        result.append(rebuilt)
    return result


def _rebuild_obra_from_data(row_number: int, data: dict) -> dict:
    codigo = _cell_str(data.get('codigo'))
    nombre = _cell_str(data.get('nombre'))
    cliente = _cell_str(data.get('cliente'))
    direccion = _cell_str(data.get('direccion'))
    fecha_inicio = _parse_date(data.get('fecha_inicio'))
    fecha_fin = _parse_date(data.get('fecha_fin'))
    display = {
        'codigo': codigo,
        'nombre': nombre,
        'cliente': cliente,
        'direccion': direccion,
        'fecha_inicio': fecha_inicio.isoformat() if fecha_inicio else _cell_str(data.get('fecha_inicio')),
        'fecha_fin': fecha_fin.isoformat() if fecha_fin else _cell_str(data.get('fecha_fin')),
    }
    messages = []
    if not any([codigo, nombre, cliente, direccion, fecha_inicio]):
        return {'row_number': row_number, 'status': 'skip', 'messages': ['Fila vacía'], 'data': display}
    if not nombre:
        messages.append('Falta el nombre de la obra')
    if messages:
        return {'row_number': row_number, 'status': 'error', 'messages': messages, 'data': display}
    if not fecha_inicio:
        fecha_inicio = date.today()
        display['fecha_inicio'] = fecha_inicio.isoformat()
        messages.append('Sin fecha de inicio; se usará hoy')
    if not fecha_fin:
        fecha_fin = fecha_inicio + timedelta(days=365)
        display['fecha_fin'] = fecha_fin.isoformat()
        messages.append('Sin fecha de fin; se usará un año después del inicio')
    if codigo:
        existing = Obra.query.filter(func.lower(Obra.codigo) == codigo.lower()).first()
        if existing:
            return {
                'row_number': row_number,
                'status': 'duplicate',
                'messages': [f'Ya existe una obra con código «{codigo}»'],
                'data': display,
            }
    return {
        'row_number': row_number,
        'status': 'new',
        'messages': messages,
        'data': display,
        '_parsed': {
            'codigo': codigo or None,
            'nombre': nombre,
            'cliente': cliente or None,
            'direccion': direccion or None,
            'fecha_inicio': fecha_inicio,
            'fecha_fin': fecha_fin,
        },
    }


def _rebuild_user_from_data(row_number: int, data: dict, parsed_old: dict) -> dict:
    email = _cell_str(data.get('email')).lower()
    rol = _normalize_role(_cell_str(data.get('rol')))
    nombre = _cell_str(data.get('nombre'))
    apellidos = _cell_str(data.get('apellidos'))
    dni = _cell_str(data.get('dni')).upper().replace(' ', '')
    empresa = _cell_str(data.get('empresa'))
    activo_raw = data.get('activo')
    if isinstance(activo_raw, bool):
        activo = activo_raw
    else:
        activo = _parse_bool(activo_raw, default=True)
    recibir_raw = data.get('recibir_emails')
    if isinstance(recibir_raw, bool):
        recibir = recibir_raw
    else:
        recibir = _parse_bool(recibir_raw, default=True)

    display = {
        'email': email,
        'rol': rol,
        'nombre': nombre,
        'apellidos': apellidos,
        'dni': dni,
        'empresa': empresa,
        'pin': ('sí' if (data.get('pin') or parsed_old.get('pin')) else 'auto'),
        'activo': 'Sí' if activo else 'No',
        'recibir_emails': 'Sí' if recibir else 'No',
    }
    messages = []
    if not any([email, nombre, apellidos, dni, empresa]):
        return {'row_number': row_number, 'status': 'skip', 'messages': ['Fila vacía'], 'data': display}
    if not email:
        messages.append('Falta el email')
    elif '@' not in email:
        messages.append('Email inválido')
    if not dni:
        messages.append('Falta el DNI')
    if not nombre:
        messages.append('Falta el nombre')
    if not apellidos:
        messages.append('Faltan los apellidos')
    if messages:
        return {'row_number': row_number, 'status': 'error', 'messages': messages, 'data': display}

    existing = User.query.filter(
        (func.lower(User.email) == email) | (func.upper(User.dni) == dni)
    ).first()
    if existing:
        reason = []
        if existing.email and existing.email.lower() == email:
            reason.append('email')
        if existing.dni and existing.dni.upper() == dni:
            reason.append('DNI')
        return {
            'row_number': row_number,
            'status': 'duplicate',
            'messages': [f"Usuario ya existe ({' y '.join(reason)})"],
            'data': display,
        }

    pin = _cell_str(data.get('pin')) if 'pin' in data else (parsed_old.get('pin') or '')
    password = parsed_old.get('password') or ''

    return {
        'row_number': row_number,
        'status': 'new',
        'messages': [],
        'data': display,
        '_parsed': {
            'email': email,
            'rol': rol,
            'nombre': nombre,
            'apellidos': apellidos,
            'dni': dni,
            'empresa': empresa,
            'password': password,
            'pin': pin,
            'activo': activo,
            'recibir_emails': recibir,
        },
    }


def _rebuild_company_from_data(row_number: int, data: dict) -> dict:
    nombre = _cell_str(data.get('nombre'))
    nif = _cell_str(data.get('nif')).upper().replace(' ', '')
    code = _cell_str(data.get('code')).upper().replace(' ', '')
    gremio = _cell_str(data.get('gremio'))
    email = _cell_str(data.get('email')).lower()
    descripcion = _cell_str(data.get('descripcion'))
    is_internal = _parse_bool(data.get('is_internal'), default=False)
    display = {
        'nombre': nombre,
        'nif': nif,
        'code': code,
        'gremio': gremio,
        'email': email,
        'descripcion': descripcion,
        'is_internal': 'Sí' if is_internal else 'No',
    }
    if not nombre:
        return {
            'row_number': row_number,
            'status': 'error',
            'messages': ['Falta el nombre de la empresa'],
            'data': display,
        }
    return {
        'row_number': row_number,
        'status': 'new',
        'messages': [],
        'data': display,
        '_parsed': {
            'nombre': nombre,
            'nif': nif or None,
            'code': code or None,
            'gremio': gremio or None,
            'email': email or None,
            'descripcion': descripcion or None,
            'is_internal': is_internal,
        },
    }


def commit_import(
    file_or_path,
    entity_type: str,
    column_map: Optional[dict] = None,
    *,
    row_edits_form=None,
    import_options: Optional[dict] = None,
) -> dict:
    """
    Aplica la importación. Solo crea filas con status 'new'.
    Duplicados y errores se reportan sin abortar el resto.
    """
    preview = preview_import(file_or_path, entity_type, column_map)
    if not preview.get("success"):
        return {
            "success": False,
            "message": preview.get("message") or "Error en previsualización",
            "rows": [],
            "summary": {},
            "imported": [],
            "created_companies": [],
        }

    internal_rows = preview.get("_internal_rows") or []
    if row_edits_form is not None:
        internal_rows = apply_row_edits(entity_type, internal_rows, row_edits_form)
    if entity_type == 'users' and import_options:
        internal_rows = annotate_user_rows_for_mode(internal_rows, import_options)

    # Checkboxes include_{n}: si el form trae include_enabled, solo se importan los marcados
    use_include = bool(
        row_edits_form is not None
        and str(row_edits_form.get('include_enabled') or '') in ('1', 'true', 'True', 'on')
    )

    result_rows = []
    imported = []
    created_companies: set = set()
    created_count = 0

    for row in internal_rows:
        status = row.get("status")
        rn = row.get("row_number")
        public = {
            "row_number": rn,
            "status": status,
            "messages": list(row.get("messages") or []),
            "data": row.get("data") or {},
        }

        if use_include and status == "new":
            included = (row_edits_form.get(f'include_{rn}') in ('1', 'on', 'true', 'True'))
            if not included:
                public["status"] = "skip"
                public["messages"] = ["Excluida por el usuario"]
                result_rows.append(public)
                continue

        if status != "new":
            result_rows.append(public)
            continue

        parsed = row.get("_parsed") or {}
        try:
            with db.session.begin_nested():
                if entity_type == "obras":
                    info = _commit_obra(parsed)
                elif entity_type == "users":
                    info = _commit_user(parsed, import_options=import_options)
                elif entity_type == "companies":
                    info = _commit_company(parsed)
                else:
                    info = None
                db.session.flush()
            public["status"] = "created"
            if entity_type == "obras":
                cod = (info or {}).get("codigo") or "—"
                nom = (info or {}).get("nombre") or ""
                public["messages"] = [f"Creada: {cod} — {nom}"]
            elif entity_type == "users":
                imported.append(info)
                if info.get("company_created") and info.get("empresa"):
                    created_companies.add(info["empresa"])
                public["messages"] = [
                    f"Creado: {info.get('name', '')} {info.get('lastname', '')} "
                    f"({info.get('email', '')})"
                ]
            elif entity_type == "companies":
                public["messages"] = [
                    f"Creada: {(row.get('data') or {}).get('nombre') or 'empresa'}"
                ]
            created_count += 1
        except Exception as exc:
            public["status"] = "error"
            public["messages"] = [_friendly_import_error(exc)]

        result_rows.append(public)

    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        return {
            "success": False,
            "message": f"Error al guardar en base de datos: {exc}",
            "rows": result_rows,
            "summary": _summarize_rows(result_rows),
            "imported": [],
            "created_companies": [],
        }

    summary = _summarize_rows(result_rows)
    summary["created"] = created_count

    label = ENTITY_LABELS.get(entity_type, entity_type)
    return {
        "success": True,
        "message": f"Importación de {label} finalizada: {created_count} creados.",
        "rows": result_rows,
        "summary": summary,
        "imported": imported,
        "created_companies": list(created_companies),
    }


# ---------------------------------------------------------------------------
# Compatibilidad con llamadas antiguas
# ---------------------------------------------------------------------------

def process_obras_import(file):
    """Compat: importa obras de inmediato. Preferir preview + commit."""
    result = commit_import(file, "obras")
    return result["success"], result["message"], result["summary"].get("created", 0)


def process_users_import(file):
    """Compat: importa usuarios de inmediato. Preferir preview + commit."""
    result = commit_import(file, "users")
    return result["success"], result["message"], {
        "imported": result.get("imported") or [],
        "created_companies": result.get("created_companies") or [],
        "rows": result.get("rows") or [],
        "summary": result.get("summary") or {},
    }


def process_companies_import(file):
    result = commit_import(file, "companies")
    return result["success"], result["message"], result["summary"].get("created", 0)
