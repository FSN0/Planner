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
            "required": True,
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

PREVIEW_SAMPLE_ROWS = 15


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
    if not fecha_inicio:
        messages.append("Falta o es inválida la fecha de inicio")

    if messages:
        return {
            "row_number": row_number,
            "status": "error",
            "messages": messages,
            "data": data,
        }

    if not fecha_fin:
        fecha_fin = fecha_inicio + timedelta(days=365)
        data["fecha_fin"] = fecha_fin.isoformat()

    if codigo:
        existing = Obra.query.filter(func.lower(Obra.codigo) == codigo.lower()).first()
        if existing:
            return {
                "row_number": row_number,
                "status": "duplicate",
                "messages": [f"Ya existe una obra con código «{codigo}»"],
                "data": data,
            }

    return {
        "row_number": row_number,
        "status": "new",
        "messages": [],
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
    role = (raw or "").strip().lower().replace(" ", "_")
    aliases = {
        "operario": ROLE_OPERARIO,
        "trabajador": ROLE_OPERARIO,
        "empleado": ROLE_OPERARIO,
        "admin": "admin",
        "administrador": "admin",
        "jefe": "jefe_obra",
        "jefe_obra": "jefe_obra",
        "jefe de obra": "jefe_obra",
        "rrhh": "rrhh",
        "recursos_humanos": "rrhh",
        "laboral": "laboral",
    }
    return aliases.get(role, role or ROLE_OPERARIO)


def _preview_user_row(row: pd.Series, column_map: dict, row_number: int) -> dict:
    email = _cell_str(_mapped_value(row, column_map, "email")).lower()
    rol = _normalize_role(_cell_str(_mapped_value(row, column_map, "rol")))
    nombre = _cell_str(_mapped_value(row, column_map, "nombre"))
    apellidos = _cell_str(_mapped_value(row, column_map, "apellidos"))
    dni = _cell_str(_mapped_value(row, column_map, "dni")).upper().replace(" ", "")
    empresa = _cell_str(_mapped_value(row, column_map, "empresa"))
    password = _cell_str(_mapped_value(row, column_map, "password"))
    activo = _parse_bool(_mapped_value(row, column_map, "activo"), default=False)
    recibir = _parse_bool(_mapped_value(row, column_map, "recibir_emails"), default=True)

    data = {
        "email": email,
        "rol": rol,
        "nombre": nombre,
        "apellidos": apellidos,
        "dni": dni,
        "empresa": empresa,
        "activo": "Sí" if activo else "No",
        "recibir_emails": "Sí" if recibir else "No",
    }
    messages: list[str] = []

    if not any([email, nombre, apellidos, dni, empresa]):
        return {
            "row_number": row_number,
            "status": "skip",
            "messages": ["Fila vacía"],
            "data": data,
        }

    if not email:
        messages.append("Falta el email")
    elif "@" not in email:
        messages.append("Email inválido")
    if not dni:
        messages.append("Falta el DNI")
    if not nombre:
        messages.append("Falta el nombre")
    if not apellidos:
        messages.append("Faltan los apellidos")

    if messages:
        return {
            "row_number": row_number,
            "status": "error",
            "messages": messages,
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
        "messages": [],
        "data": data,
        "_parsed": {
            "email": email,
            "rol": rol,
            "nombre": nombre,
            "apellidos": apellidos,
            "dni": dni,
            "empresa": empresa,
            "password": password,
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

def _commit_obra(parsed: dict) -> None:
    obra = Obra(
        codigo=parsed.get("codigo"),
        nombre=parsed["nombre"],
        cliente=parsed.get("cliente"),
        ubicacion=parsed.get("direccion"),
        descripcion=parsed.get("cliente") or None,
        fecha_inicio=parsed["fecha_inicio"],
        fecha_fin=parsed["fecha_fin"],
        estado="Pendiente",
        limite_trabajadores=50,
        jefe_obra_id=None,
        fecha_importacion=datetime.utcnow(),
    )
    db.session.add(obra)


def _ensure_company_for_user(empresa_nombre: str) -> tuple[Optional[Company], bool]:
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


def _commit_user(parsed: dict) -> dict:
    comp, company_created = _ensure_company_for_user(parsed.get("empresa") or "")
    pwd = parsed.get("password") or secrets.token_urlsafe(16)
    new_user = User(
        email=parsed["email"],
        password_hash=generate_password_hash(pwd),
        role=parsed.get("rol") or ROLE_OPERARIO,
        name=parsed["nombre"],
        lastname=parsed["apellidos"],
        dni=parsed["dni"],
        company_id=comp.id if comp else None,
        active=bool(parsed.get("activo")),
        email_verified=True,
        receive_emails=bool(parsed.get("recibir_emails", True)),
    )
    db.session.add(new_user)
    return {
        "email": parsed["email"],
        "role": parsed.get("rol"),
        "name": parsed["nombre"],
        "lastname": parsed["apellidos"],
        "dni": parsed["dni"],
        "empresa": parsed.get("empresa") or "",
        "company_created": company_created,
        "active": bool(parsed.get("activo")),
        "receive_emails": bool(parsed.get("recibir_emails", True)),
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


def commit_import(file_or_path, entity_type: str, column_map: Optional[dict] = None) -> dict:
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
    result_rows = []
    imported = []
    created_companies: set = set()
    created_count = 0

    for row in internal_rows:
        status = row.get("status")
        public = {
            "row_number": row["row_number"],
            "status": status,
            "messages": list(row.get("messages") or []),
            "data": row.get("data") or {},
        }

        if status != "new":
            result_rows.append(public)
            continue

        parsed = row.get("_parsed") or {}
        try:
            # Savepoint: un fallo en una fila no descarta el resto.
            with db.session.begin_nested():
                if entity_type == "obras":
                    _commit_obra(parsed)
                elif entity_type == "users":
                    info = _commit_user(parsed)
                elif entity_type == "companies":
                    _commit_company(parsed)
                db.session.flush()
            public["status"] = "created"
            if entity_type == "obras":
                public["messages"] = ["Obra creada"]
            elif entity_type == "users":
                imported.append(info)
                if info.get("company_created") and info.get("empresa"):
                    created_companies.add(info["empresa"])
                public["messages"] = ["Usuario creado"]
            elif entity_type == "companies":
                public["messages"] = ["Empresa creada"]
            created_count += 1
        except Exception as exc:
            public["status"] = "error"
            public["messages"] = [f"Error al guardar: {exc}"]

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
