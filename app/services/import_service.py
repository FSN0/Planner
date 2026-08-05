import secrets
import pandas as pd
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash
from sqlalchemy import func
from app import db
from app.models import Obra, User, Company, ROLE_OPERARIO

def process_obras_import(file):
    """
    Procesa el archivo Excel de obras.
    Retorna: (success: bool, message: str, count: int)
    """
    try:
        df = pd.read_excel(file)
    except Exception as e:
        return False, f"Error al leer el Excel: {str(e)}", 0

    count = 0
    for idx, row in df.iterrows():
        try:
            codigo = str(row.get("Código", "")).strip()
            nombre_imp = str(row.get("Nombre", "")).strip()
            # Si no hay nombre, saltamos la fila
            if not nombre_imp: 
                continue
                
            cliente = str(row.get("Cliente", "")).strip()
            direccion = str(row.get("Dirección", "")).strip()
            
            # Parseo de fechas
            fi_raw = row.get("Fecha de inicio")
            ff_raw = row.get("Fecha de fin", None)

            if pd.isna(fi_raw):
                continue
            
            fecha_inicio = fi_raw.date() if hasattr(fi_raw, "date") else fi_raw

            if pd.isna(ff_raw) or ff_raw is None:
                fecha_fin = fecha_inicio + timedelta(days=365)
            else:
                fecha_fin = ff_raw.date() if hasattr(ff_raw, "date") else ff_raw

            # Evitar duplicados por código si ya existe (Opcional: Update or Skip)
            # Aquí asumimos creación simple como tenías
            obra = Obra(
                nombre=f"{codigo} - {nombre_imp}" if codigo else nombre_imp,
                descripcion=cliente,
                ubicacion=direccion,
                fecha_inicio=fecha_inicio,
                fecha_fin=fecha_fin,
                estado="Pendiente",
                limite_trabajadores=50,
                jefe_obra_id=None,
                codigo=codigo if codigo else None
            )
            db.session.add(obra)
            count += 1
        except Exception:
            continue # Saltar filas con errores puntuales

    try:
        db.session.commit()
        return True, f"{count} obras importadas correctamente.", count
    except Exception as e:
        db.session.rollback()
        return False, f"Error al guardar en base de datos: {str(e)}", 0


def process_users_import(file):
    """
    Procesa el archivo Excel de usuarios.
    Retorna: (success: bool, message: str, data: dict)
    Donde data contiene 'imported' (lista) y 'created_companies' (lista).
    """
    try:
        df = pd.read_excel(file)
    except Exception as e:
        return False, f"Error leyendo el archivo Excel: {str(e)}", {}

    imported = []
    created_companies = set()

    for _, row in df.iterrows():
        try:
            pwd = str(row.get("Contraseña", "")).strip()
            role = str(row.get("Rol", "")).strip().lower()
            email = str(row.get("Email", "")).strip()
            name = str(row.get("Nombre", "")).strip()
            lastname = str(row.get("Apellidos", "")).strip()
            dni = str(row.get("DNI", "")).strip()
            empresa_nombre = str(row.get("Empresa", "")).strip()
            
            # Validaciones mínimas
            if not email or not dni:
                continue

            active_flag = (str(row.get("Activo", "")).strip().lower() in ("sí", "si", "yes"))
            email_flag = (str(row.get("Recibir notificaciones por email", "")).strip().lower() in ("sí", "si", "yes"))

            # Lógica de Empresa (Buscar o Crear)
            created = False
            comp = Company.query.filter(func.lower(Company.nombre) == empresa_nombre.lower()).first()
            
            if not comp and empresa_nombre:
                # Crear empresa nueva externa
                code_gen = empresa_nombre.upper().replace(" ", "")[:10]
                # Asegurar unicidad de código simple
                if Company.query.filter_by(code=code_gen).first():
                    code_gen = f"{code_gen}_{datetime.now().strftime('%S')}"

                comp = Company(code=code_gen, nombre=empresa_nombre, is_internal=False)
                db.session.add(comp)
                db.session.flush()
                created = True
                created_companies.add(empresa_nombre)

            # Crear Usuario
            # Verificar duplicados básicos antes de insertar para evitar crash masivo
            if User.query.filter((User.email == email) | (User.dni == dni)).first():
                # Si existe, saltamos (o podrías hacer update)
                continue

            new_user = User(
                email=email,
                password_hash=generate_password_hash(pwd) if pwd else generate_password_hash(secrets.token_urlsafe(16)),
                role=role if role else ROLE_OPERARIO,
                name=name,
                lastname=lastname,
                dni=dni,
                company_id=comp.id if comp else None,
                active=active_flag,
                email_verified=True,
                receive_emails=email_flag,
            )
            db.session.add(new_user)
            
            # Guardar para el reporte
            imported.append({
                "email": email, "role": role, "name": name, "lastname": lastname,
                "dni": dni, "empresa": empresa_nombre, "company_created": created,
                "active": active_flag, "receive_emails": email_flag,
            })
        
        except Exception:
            # Si falla una fila, continuamos con la siguiente
            continue

    try:
        db.session.commit()
        return True, "Importación finalizada", {
            "imported": imported, 
            "created_companies": list(created_companies)
        }
    except Exception as e:
        db.session.rollback()
        return False, f"Error de base de datos general: {str(e)}", {}