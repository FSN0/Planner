# app/models.py
from . import db, login_manager
from flask_login import UserMixin
from datetime import datetime, date, timezone
import hashlib
import random
from sqlalchemy.dialects.postgresql import JSONB


def _utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)



# --- CONSTANTES DE ROLES ---
ROLE_OPERARIO = 'operario'
ROLE_JEFE = 'jefe_obra'
ROLE_RRHH = 'rrhh'
ROLE_ADMIN = 'admin'
ROLE_LABORAL = 'laboral'
# RRHH = mismos permisos que laboral (hasta definir un ACL propio).
ROLES_LABORAL_LIKE = (ROLE_LABORAL, ROLE_RRHH)
# No se pueden renombrar ni borrar (comportamiento de la app).
ROLES_SYSTEM_LOCKED = frozenset({ROLE_ADMIN, ROLE_JEFE, ROLE_OPERARIO})
# Roles de fábrica (siempre sembrados); laboral/rrhh sí se pueden renombrar.
ROLES_BUILTIN = (
    ROLE_ADMIN,
    ROLE_JEFE,
    ROLE_LABORAL,
    ROLE_RRHH,
    ROLE_OPERARIO,
)
from sqlalchemy import event

# Esta función se dispara cada vez que SQLAlchemy hace una consulta
@event.listens_for(db.Model, 'before_insert', propagate=True)
def before_insert(mapper, connection, target):
    # Esto asegura que si estamos en un tenant, no intente insertar en public
    pass
class Tenant(db.Model):
    """
    Representa a cada cliente/empresa que contrata el SaaS.
    Este modelo reside estrictamente en el esquema 'public'.
    """
    __tablename__ = 'tenants'
    __table_args__ = {'schema': 'public'}  # Fuerza a que esta tabla viva siempre fuera de los esquemas aislados

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    subdominio = db.Column(db.String(50), unique=True, nullable=False)  # Ej: 'soltec', 'acme'
    custom_domain = db.Column(db.String(255), unique=True, nullable=True)  # Ej: 'planner.empresa.com'
    schema_name = db.Column(db.String(50), unique=True, nullable=False) # Ej: 'tenant_soltec', 'tenant_acme'
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    # Soft-off: al desactivar se rellena; a +30 días se puede borrar el schema.
    deactivated_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    modulos_activos = db.Column(db.JSON, nullable=False, server_default='{}')

    # Freemium: free hasta N trabajadores; paid sin límite (salvo trato a medida).
    plan = db.Column(db.String(20), nullable=False, server_default='free')
    limite_empleados = db.Column(db.Integer, nullable=True)

    # Facturación: exempt = premium sin pasarela (demos, Soltec, cortesías).
    # stripe_* se rellenarán cuando exista cuenta Stripe real.
    billing_exempt = db.Column(db.Boolean, nullable=False, server_default='false', default=False)
    stripe_customer_id = db.Column(db.String(120), nullable=True)
    stripe_subscription_id = db.Column(db.String(120), nullable=True)

    # Consentimiento legal del alta autoservicio (versiones publicadas en /legal).
    legal_aceptado_at = db.Column(db.DateTime, nullable=True)
    legal_privacidad_version = db.Column(db.String(32), nullable=True)
    legal_condiciones_version = db.Column(db.String(32), nullable=True)
    
    def __repr__(self):
        return f'<Tenant {self.nombre} - Subdominio: {self.subdominio}>'


class SignupReservation(db.Model):
    """
    Alta pública pendiente de confirmar el correo.
    El tenant (schema) no existe hasta pulsar confirmar: así un email falso
    no deja un espacio usable ni quema el subdominio para siempre.
    """
    __tablename__ = 'signup_reservations'
    __table_args__ = (
        db.Index(
            'uq_signup_reservations_subdominio_live',
            'subdominio',
            unique=True,
            postgresql_where=db.text(
                "status IN ('pending', 'provisioning', 'ready')"
            ),
        ),
        db.Index('ix_signup_reservations_admin_email', 'admin_email'),
        {'schema': 'public'},
    )

    STATUS_PENDING = 'pending'
    STATUS_PROVISIONING = 'provisioning'
    STATUS_READY = 'ready'
    STATUS_FAILED = 'failed'
    STATUS_EXPIRED = 'expired'

    id = db.Column(db.Integer, primary_key=True)
    subdominio = db.Column(db.String(50), nullable=False)
    nombre_empresa = db.Column(db.String(100), nullable=False)
    admin_email = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    locale = db.Column(db.String(8), nullable=True)
    legal_privacidad_version = db.Column(db.String(32), nullable=True)
    legal_condiciones_version = db.Column(db.String(32), nullable=True)
    status = db.Column(
        db.String(20), nullable=False, default=STATUS_PENDING, server_default='pending'
    )
    tenant_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    error_message = db.Column(db.String(255), nullable=True)

    def __repr__(self):
        return f'<SignupReservation {self.subdominio} {self.status}>'


def generate_random_color():
    """Genera un color pastel aleatorio para las obras/empresas."""
    palette = ["#a8d5ba", "#f4d06f", "#f7a072", "#d291bc", "#b8a9c9",
               "#a3cef1", "#c2b9b0", "#e3d4b9", "#9dc08b", "#c8d6e5"]
    return random.choice(palette)

class Company(db.Model):
    """
    Representa empresas. Puede ser la empresa 'madre' (Interna) o subcontratas.
    is_internal: True si es la empresa propia, False si es externa.
    """
    __tablename__ = 'companies'
    id = db.Column(db.Integer, primary_key=True)
    
    # Identificador único corto (ej: "EMPRESA_A", "ELEC_PEPE")
    code = db.Column(db.String(20), unique=True, nullable=True) 
    nombre = db.Column(db.String(100), nullable=False)
    nif = db.Column(db.String(20), nullable=True)
    
    external_ids = db.Column(JSONB, server_default='{}', nullable=False)
    
    descripcion = db.Column(db.Text)
    gremio = db.Column(db.String(100)) # Ej: Electricidad, Albañilería
    
    email = db.Column(db.String(120), nullable=True) # Email de contacto principal
    color = db.Column(db.String(7), nullable=True, default=generate_random_color)
    
    # Flag clave para distinguir personal propio de subcontratado
    is_internal = db.Column(db.Boolean, nullable=False, default=False)
    # Archivo sin borrado: baja de subcontrata / sin personal activo.
    active = db.Column(db.Boolean, nullable=False, default=True, server_default='true')
    
    def __repr__(self):
        return f'<Company {self.nombre} ({self.code})>'



class User(UserMixin, db.Model):
    """
    Modelo unificado de Usuario (Admin, Jefes, RRHH, Operarios).
    """
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)

    
    external_ids = db.Column(JSONB, server_default='{}', nullable=False)
    
    # Autenticación
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    auth_source_last = db.Column(db.String(20), nullable=True)
    odoo_verified_at = db.Column(db.DateTime, nullable=True)
    odoo_password_sig = db.Column(db.String(64), nullable=True)
    odoo_fallback_disabled = db.Column(
        db.Boolean, nullable=False, default=False, server_default='false'
    )
    # PIN numérico para la PWA de fichaje (DNI + PIN). Independiente del login web.
    pin_hash = db.Column(db.String(255), nullable=True)
    # True si el PIN fue generado y aún no lo ha cambiado el trabajador en la app.
    pin_must_change = db.Column(
        db.Boolean, nullable=False, default=False, server_default='false'
    )
    # Bloqueo temporal tras intentos fallidos de PIN (anti fuerza bruta suave).
    pin_failed_attempts = db.Column(
        db.Integer, nullable=False, default=0, server_default='0'
    )
    pin_locked_until = db.Column(db.DateTime, nullable=True)
    role = db.Column(db.String(40), nullable=False)  # admin, jefe_obra, roles custom…
    
    # Datos Personales
    name = db.Column(db.String(100), nullable=False)
    lastname = db.Column(db.String(100), nullable=False)
    dni = db.Column(db.String(20), unique=True, nullable=False)
    
    # Datos de Empresa  
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=True)
    company_rel = db.relationship('Company', backref='users')

    # Datos Profesionales
    categoria_profesional = db.Column(db.String(100), nullable=True) # Ej: Oficial 1ª, Peón

    # Estados y Ciclo de vida
    active = db.Column(db.Boolean, default=False)  # Aprobado por RRHH (para operarios)
    is_deleted = db.Column(db.Boolean, default=False)  # Soft delete
    # Motivo de inactividad: pending | manual | odoo | deleted
    deactivation_reason = db.Column(db.String(40), nullable=True)
    deactivated_at = db.Column(db.DateTime, nullable=True)
    deactivated_by_id = db.Column(
        db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True
    )
    deactivated_by = db.relationship(
        'User',
        foreign_keys=[deactivated_by_id],
        remote_side=[id],
        post_update=True,
    )
    # En el alta nueva el admin nace ya verificado. En cuentas antiguas
    # puede quedar False; no bloquea el login.
    email_verified = db.Column(
        db.Boolean, nullable=False, default=False, server_default='false'
    )
    # Login web (legacy; acceso gobernado por auth_mode + permisos).
    web_access = db.Column(
        db.Boolean, nullable=False, default=False, server_default='false'
    )
    # pin | password | both — operario por defecto pin; oficina password.
    auth_mode = db.Column(
        db.String(16), nullable=False, default='password', server_default='password'
    )
    
    # Configuración
    receive_emails = db.Column(db.Boolean, default=True)
    # Idioma de interfaz (es, en, pt, fr). None → detección automática.
    locale = db.Column(db.String(8), nullable=True)
    # Preferencias del menú lateral: secciones, orden, títulos, ocultos.
    sidebar_prefs = db.Column(JSONB, server_default='{}', nullable=False)
    especialidad = db.Column(db.String(100), nullable=True) # Electricista, Fontanero, Albañil...
    
    # Programación de estados (Activación/Desactivación futura)
    scheduled_activation_date = db.Column(db.Date, nullable=True)
    scheduled_deactivation_date = db.Column(db.Date, nullable=True)

    # Relación con documentos
    
    
    @property
    def is_active(self):
        """Flask-Login usa esta propiedad para permitir/denegar el login.

        Sobreescribimos UserMixin (que siempre devolvía True) para que los
        usuarios no aprobados por RRHH (active=False) o eliminados no puedan
        iniciar sesión.
        """
        return bool(self.active) and not bool(self.is_deleted)

    @property
    def inactive_reason_label(self):
        """Texto para tooltip cuando el usuario no está operativo."""
        from app.services.i18n_service import translate

        if self.active and not self.is_deleted:
            return ''

        if self.is_deleted or self.deactivation_reason == 'deleted':
            base = translate('Eliminado (archivado)')
        elif self.scheduled_activation_date and not self.active:
            base = translate(
                'Activación programada para el {fecha}',
                fecha=self.scheduled_activation_date.strftime('%d/%m/%Y'),
            )
            return base
        elif self.deactivation_reason == 'odoo':
            base = translate('Baja por sincronización Odoo')
        elif self.deactivation_reason == 'manual':
            base = translate('Baja manual')
        elif self.deactivation_reason == 'pending':
            # Seguridad: vinculado a Odoo no es «pendiente de alta»
            ext = self.external_ids or {}
            if ext.get('odoo'):
                base = translate('Baja por sincronización Odoo')
            else:
                base = translate('Pendiente de activación')
        else:
            ext = self.external_ids or {}
            if ext.get('odoo') and not self.active:
                base = translate('Baja por sincronización Odoo')
            else:
                base = translate('Inactivo (motivo no registrado)')

        if self.deactivated_at and (
            self.deactivation_reason in ('manual', 'odoo', 'deleted')
            or (
                (self.external_ids or {}).get('odoo')
                and self.deactivation_reason in (None, '', 'pending')
            )
        ):
            return f"{base} · {self.deactivated_at.strftime('%d/%m/%Y')}"
        return base

    @property
    def reputation_score(self):
        """
        Calcula la media de las valoraciones activas.
        Devuelve un valor redondeado a 1 decimal (ej: 2.5).
        """
        # --- CORRECCIÓN AQUÍ ---
        # Usamos 'ratings_received' porque así lo llamaste en el backref de la clase Rating
        if not hasattr(self, 'ratings_received'):
            return 0.0

        valid_ratings = [r for r in self.ratings_received if r.is_active]
        
        if not valid_ratings:
            return 0.0
            
        # 2. Suma total de puntos
        total = sum(r.score for r in valid_ratings)
        
        # 3. Cálculo de la media
        media = total / len(valid_ratings)
        
        # 4. Devolver redondeado
        return round(media, 1)
    
    @property
    def tipo_empleado(self):
        """Devuelve 'INTERNO' o 'EXTERNO' según la empresa asignada."""
        if self.company_rel and self.company_rel.is_internal:
            return 'INTERNO'
        return 'EXTERNO'

    def soft_delete(self, actor_id=None):
        """
        Marca al usuario como eliminado, libera su DNI (añadiendo sufijo)
        y elimina asignaciones futuras para liberar planificación.
        """
        from app.utils.timezone_utils import today_local, utc_now
        today = today_local()
        new_dni = f"{self.dni}-del-{self.id}"
        self.dni = new_dni[:20]
        
        self.is_deleted = True
        self.active = False
        self.deactivation_reason = 'deleted'
        self.deactivated_at = utc_now()
        self.deactivated_by_id = int(actor_id) if actor_id else None
        self.scheduled_activation_date = None
        self.scheduled_deactivation_date = None

        if self.role == ROLE_OPERARIO:
            from app.models import Asignacion
            from app.services.core_assignment_service import CoreAssignmentService
            future_assignments = Asignacion.query.filter(
                Asignacion.user_id == self.id,
                Asignacion.fecha > today
            ).all()
            for assignment in future_assignments:
                CoreAssignmentService.desasignar(
                    assignment.user_id, assignment.obra_id, assignment.fecha,
                    actor_id or 1, "Baja de Empleado"
                )

        # Si es jefe, quitarle la jefatura de obras activas
        elif self.role in [ROLE_JEFE, ROLE_ADMIN]:
            from app.models import Obra
            active_obras = Obra.query.filter(
                Obra.jefe_obra_id == self.id,
                Obra.fecha_fin >= today
            ).all()
            for obra in active_obras:
                obra.jefe_obra_id = None

    def __repr__(self):
        return f'<User {self.email} - {self.role}>'

from flask import g, session

@login_manager.user_loader
def load_user(user_id):
    # Asegurarnos de que hay un tenant activo en la petición actual
    if not hasattr(g, 'current_tenant') or not g.current_tenant:
        return None
        
    # SEGURIDAD SAAS: Evitar que una cookie de la "Empresa A" abra la cuenta en "Empresa B"
    if session.get('tenant_id') != g.current_tenant.id:
        return None
    
    # Si una query anterior dejó la transacción abortada (p. ej. columna
    # pendiente de migración), recuperamos la sesión antes de cargar el user.
    try:
        return User.query.get(int(user_id))
    except Exception:
        try:
            from app import db
            db.session.rollback()
        except Exception:
            pass
        try:
            return User.query.get(int(user_id))
        except Exception:
            return None




class UserObraConfig(db.Model):
    """
    Guarda la configuración personalizada de un usuario para una obra específica.
    - is_pinned: Si está anclada al principio.
    - position: El orden manual (solo aplica si is_pinned=True).
    """
    __tablename__ = 'user_obra_config'
    
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), primary_key=True)
    obra_id = db.Column(db.Integer, db.ForeignKey('obras.id'), primary_key=True)
    
    is_pinned = db.Column(db.Boolean, default=False)
    position = db.Column(db.Integer, default=0)
    
    # Relaciones
    user = db.relationship('User', backref=db.backref('obra_configs', cascade='all, delete-orphan'))
    obra = db.relationship('Obra', backref=db.backref('user_configs', cascade='all, delete-orphan'))

    def __repr__(self):
        return f"<UserObraConfig U:{self.user_id} O:{self.obra_id} Pinned:{self.is_pinned}>"
    
class SystemLog(db.Model):
    __tablename__ = 'system_logs'
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=_utc_now)
    
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True) 
    category = db.Column(db.String(50), nullable=False) 
    action = db.Column(db.String(150), nullable=False) 
    detail = db.Column(db.Text, nullable=True) 

    # --- NUEVOS CAMPOS PARA AUDITORÍA (LA CAJA NEGRA) ---
    target_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True) 
    target_date = db.Column(db.Date, nullable=True)

    user = db.relationship('User', foreign_keys=[user_id])
    target_user = db.relationship('User', foreign_keys=[target_user_id])

class LogPreference(db.Model):
    __tablename__ = 'log_preferences'
    id = db.Column(db.Integer, primary_key=True)
    # --- AQUÍ TAMBIÉN: Cambiado 'user.id' por 'users.id' ---
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    category = db.Column(db.String(50), nullable=False)
    is_active = db.Column(db.Boolean, default=False) 
    last_read_at = db.Column(db.DateTime, default=_utc_now) 

    user = db.relationship('User', backref=db.backref('log_preferences', lazy='dynamic'))


class LogAcknowledgement(db.Model):
    """Acuse de lectura individual de un SystemLog (contador laboral)."""
    __tablename__ = 'log_acknowledgements'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    log_id = db.Column(db.Integer, db.ForeignKey('system_logs.id'), nullable=False, index=True)
    acknowledged_at = db.Column(db.DateTime, default=_utc_now, nullable=False)
    __table_args__ = (
        db.UniqueConstraint('user_id', 'log_id', name='uq_log_ack_user_log'),
    )

    user = db.relationship('User', backref=db.backref('log_acknowledgements', lazy='dynamic'))
    log = db.relationship('SystemLog', backref=db.backref('acknowledgements', lazy='dynamic'))


class Obra(db.Model):
    """
    Unidad central de planificación.
    """
    __tablename__ = 'obras'
    id = db.Column(db.Integer, primary_key=True)
    
    # Identificación
    codigo = db.Column(db.String(20), unique=True)
    nombre = db.Column(db.String(100), nullable=False)
    descripcion = db.Column(db.Text)
    cliente = db.Column(db.String(100))
    ubicacion = db.Column(db.String(100))
    latitud = db.Column(db.Float, nullable=True)
    longitud = db.Column(db.Float, nullable=True)
    radio_metros = db.Column(db.Integer, nullable=True)
    fecha_sincronizacion = db.Column(db.DateTime, nullable=True)

    external_ids = db.Column(JSONB, server_default='{}', nullable=False)
    
    # Fechas
    fecha_inicio = db.Column(db.Date)
    fecha_fin = db.Column(db.Date)
    fecha_importacion = db.Column(db.DateTime, nullable=True)
    
    # Estado y Gestión
    estado = db.Column(db.String(20), default='PLANIFICADA')
    
    # Responsable (Usuario Interno)
    jefe_obra_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    jefe_obra = db.relationship('User', foreign_keys=[jefe_obra_id])
    
    encargado_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    encargado = db.relationship('User', foreign_keys=[encargado_id])
    
    # Estilo
    color = db.Column(db.String(7), nullable=False, default=generate_random_color)
    is_deleted = db.Column(db.Boolean, default=False)

    # Relación inversa
    asignaciones = db.relationship('Asignacion', backref='obra', lazy=True)

    def __repr__(self):
        return f'<Obra {self.nombre}>'

class Asignacion(db.Model):
    """
    Tabla de hechos: Empleado en Obra en Fecha.
    """
    __tablename__ = 'asignaciones'
    id = db.Column(db.Integer, primary_key=True)
    
    obra_id = db.Column(db.Integer, db.ForeignKey('obras.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    user = db.relationship('User', backref='asignaciones')
    fecha = db.Column(db.Date, nullable=False)
    
    # Snapshot: Empresa del trabajador en el momento de la asignación
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=True)
    company = db.relationship('Company')
    
    created_at = db.Column(db.DateTime, default=_utc_now)
    solicitud_id = db.Column(db.Integer, db.ForeignKey('solicitudes.id', ondelete="SET NULL"), nullable=True)
    solicitud = db.relationship('Solicitud', backref='asignaciones_vinculadas')
    __table_args__ = (
        # Restricción: Un usuario no puede estar dos veces en la MISMA obra el MISMO día.
        # PERO sí puede estar en Obra A y Obra B el mismo día (Multi-asignación).
        db.UniqueConstraint('obra_id', 'user_id', 'fecha', name='uq_obra_user_fecha'),
    )
    
    def __repr__(self):
        return f'<Asignacion Obra:{self.obra_id} User:{self.user_id} Fecha:{self.fecha}>'


class InerciaCorte(db.Model):
    """
    Corta la casa de un trabajador a partir de una fecha.

    El cuadrante no guarda filas fantasma: la inercia se calcula. Soltar a
    Libres tiene que persistir el corte; si no, al día siguiente el fantasma
    devolvería a la persona al tajo.
    """
    __tablename__ = 'inercia_cortes'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    fecha = db.Column(db.Date, nullable=False)
    autor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=_utc_now)
    __table_args__ = (
        db.UniqueConstraint('user_id', 'fecha', name='uq_inercia_corte_user_fecha'),
    )

    def __repr__(self):
        return f'<InerciaCorte User:{self.user_id} Fecha:{self.fecha}>'


class HistorialAsignacion(db.Model):
    """Auditoría de cambios en asignaciones."""
    __tablename__ = 'historial_asignaciones'
    id = db.Column(db.Integer, primary_key=True)
    asignacion_id = db.Column(db.Integer, db.ForeignKey('asignaciones.id', ondelete="SET NULL"), nullable=True)
    accion = db.Column(db.String(100))  # Creada, Borrada, Modificada
    timestamp = db.Column(db.DateTime, default=_utc_now)
    realizado_por = db.Column(db.Integer, db.ForeignKey('users.id'))

    def __repr__(self):
        return f'<Historial Asignacion {self.id} - {self.accion}>'

class SyncLog(db.Model):
    __tablename__ = 'sync_logs'
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime, default=_utc_now)
    tipo = db.Column(db.String(50)) # 'Obras', 'Empleados', 'Subcontratas', 'Fichajes'
    modo = db.Column(db.String(50)) # 'Manual' o 'Automático'
    nuevos = db.Column(db.Integer, default=0)
    actualizados = db.Column(db.Integer, default=0)
    finalizados = db.Column(db.Integer, default=0)
    errores = db.Column(db.Integer, default=0) # Registros omitidos o con conflicto
    detalles = db.Column(db.Text, nullable=True)
    estado = db.Column(db.String(20), default='ok')  # ok | parcial | error
    duracion_ms = db.Column(db.Integer, nullable=True)
    mensaje_error = db.Column(db.Text, nullable=True)
    visto = db.Column(db.Boolean, default=False, nullable=False)
    visto_en = db.Column(db.DateTime, nullable=True)
    
    
class RegistroFichaje(db.Model):
    __tablename__ = 'registros_fichajes'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    fecha = db.Column(db.Date)
    
    check_in = db.Column(db.DateTime, nullable=True)
    check_out = db.Column(db.DateTime, nullable=True)
    nota_odoo = db.Column(db.Text, nullable=True)
    # Métricas de hr.attendance / partner.attendance (Soltec / Odoo)
    odoo_ud = db.Column(db.Numeric(12, 4), nullable=True)
    odoo_mod = db.Column(db.Numeric(12, 4), nullable=True)
    odoo_total_hh = db.Column(db.Numeric(12, 4), nullable=True)
    odoo_moe = db.Column(db.Numeric(12, 4), nullable=True)
    
    # Lo que decía tu aplicación
    obra_planificada_id = db.Column(db.Integer, db.ForeignKey('obras.id'), nullable=True)
    # Dónde pisó realmente la obra
    obra_real_id = db.Column(db.Integer, db.ForeignKey('obras.id'), nullable=True)
    
    # Estados: 'Correcto', 'Conflicto', 'Ausencia', 'Resuelto_Movido', ...
    estado = db.Column(db.String(50), default='Pendiente')
    # Estado previo a la resolución de auditoría (para «Reabrir»).
    estado_antes_resolucion = db.Column(db.String(50), nullable=True)
    notas_resolucion = db.Column(db.Text, nullable=True)
    fecha_auditoria = db.Column(db.DateTime, default=_utc_now)

    # Trazabilidad: Quién resolvió el conflicto
    resuelto_por_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    # Desvío X→Y: firmas/decisiones independientes de plan y de obra fichada
    desvio_ack_plan_at = db.Column(db.DateTime, nullable=True)
    desvio_ack_plan_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    desvio_ack_real_at = db.Column(db.DateTime, nullable=True)
    desvio_ack_real_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    # liberar | mantener_falta
    desvio_decision_plan = db.Column(db.String(20), nullable=True)
    # aceptar | rechazar
    desvio_decision_real = db.Column(db.String(20), nullable=True)

    # Relaciones para navegar fácilmente desde Jinja
    user = db.relationship('User', backref='fichajes_diarios', foreign_keys=[user_id])
    obra_planificada = db.relationship('Obra', foreign_keys=[obra_planificada_id])
    obra_real = db.relationship('Obra', foreign_keys=[obra_real_id])
    resuelto_por = db.relationship('User', foreign_keys=[resuelto_por_id])
    desvio_ack_plan_by = db.relationship('User', foreign_keys=[desvio_ack_plan_by_id])
    desvio_ack_real_by = db.relationship('User', foreign_keys=[desvio_ack_real_by_id])


# --- TIPOS DE EVENTO DE FICHAJE ---
EVENTO_ENTRADA = 'entrada'
EVENTO_SALIDA = 'salida'
EVENTO_PAUSA_INICIO = 'pausa_inicio'
EVENTO_PAUSA_FIN = 'pausa_fin'
EVENTO_ANULACION = 'anulacion'

# Cambiar la obra a la que se imputan unas horas no es rectificar la jornada:
# el art. 34.9 ET obliga a registrar el horario de inicio y fin, no el destino
# de esas horas, que es contabilidad de costes. Por eso tiene evento propio y no
# se resuelve anulando la entrada: si cada corrección de obra anulase marcas de
# tiempo, el libro parecería lleno de jornadas rectificadas cuando en realidad
# ninguna hora se ha tocado, y eso es justo lo contrario de lo que debe probar.
EVENTO_REASIGNACION_OBRA = 'reasignacion_obra'

# Conforme del trabajador sobre la jornada del día (art. 34.9 ET / inspección).
# No es marca de tiempo: acredita que el interesado revisó y aceptó el registro.
EVENTO_CONFORME_JORNADA = 'conforme_jornada'

TIPOS_EVENTO_FICHAJE = (
    EVENTO_ENTRADA,
    EVENTO_SALIDA,
    EVENTO_PAUSA_INICIO,
    EVENTO_PAUSA_FIN,
    EVENTO_ANULACION,
    EVENTO_REASIGNACION_OBRA,
    EVENTO_CONFORME_JORNADA,
)

# Tipos que representan una marca de tiempo real de la persona. El resto son
# anotaciones sobre esas marcas y no computan jornada.
TIPOS_MARCA_DE_TIEMPO = (
    EVENTO_ENTRADA,
    EVENTO_SALIDA,
    EVENTO_PAUSA_INICIO,
    EVENTO_PAUSA_FIN,
)

# --- ORÍGENES DE UN EVENTO ---
ORIGEN_PWA = 'pwa'
ORIGEN_KIOSCO = 'kiosco'  # histórico; no se ofrece en producto
ORIGEN_ERP = 'erp'
ORIGEN_ADMIN = 'admin'
ORIGEN_IMPORTACION = 'importacion'
ORIGEN_MIGRACION = 'migracion'

ORIGENES_EVENTO_FICHAJE = (
    ORIGEN_PWA,
    ORIGEN_KIOSCO,
    ORIGEN_ERP,
    ORIGEN_ADMIN,
    ORIGEN_IMPORTACION,
    ORIGEN_MIGRACION,
)

# Orígenes que exigen motivo documentado: no los genera el trabajador.
ORIGENES_REQUIEREN_MOTIVO = (ORIGEN_ADMIN, ORIGEN_IMPORTACION)

# Años de conservación exigidos por el art. 34.9 ET / art. 21.5 LISOS.
ANIOS_CONSERVACION_FICHAJES = 4


class FichajeEvento(db.Model):
    """
    Libro de eventos de jornada. Solo admite inserciones: la base de datos
    rechaza UPDATE y DELETE mediante disparador, y cada fila va encadenada por
    hash con la anterior, de forma que cualquier manipulación posterior es
    detectable aunque se haga por fuera de la aplicación.

    Una corrección nunca modifica el evento original: se añade un evento de
    tipo 'anulacion' que lo referencia, y a continuación el evento correcto.
    """
    __tablename__ = 'fichajes_eventos'
    __table_args__ = (
        db.UniqueConstraint('secuencia', name='uq_fichajes_eventos_secuencia'),
        db.Index('ix_fichajes_eventos_user_fecha', 'user_id', 'fecha_laboral'),
        db.Index('ix_fichajes_eventos_ocurrido', 'ocurrido_en'),
    )

    id = db.Column(db.Integer, primary_key=True)

    # Posición en la cadena del tenant. Empieza en 1 y no admite huecos.
    secuencia = db.Column(db.BigInteger, nullable=False)

    # Trabajador al que se imputa la jornada.
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    tipo = db.Column(db.String(20), nullable=False)
    origen = db.Column(db.String(20), nullable=False)

    # Jornada a la que se imputa. Se separa de 'ocurrido_en' porque un turno
    # de noche cruza la medianoche y sigue perteneciendo al día anterior.
    fecha_laboral = db.Column(db.Date, nullable=False)

    # Momento real del fichaje (UTC) y momento en que entró en el sistema.
    ocurrido_en = db.Column(db.DateTime, nullable=False)
    registrado_en = db.Column(db.DateTime, nullable=False, default=_utc_now)
    zona_horaria = db.Column(db.String(64), nullable=True)

    # Quién lo registra: normalmente el propio trabajador, salvo altas manuales.
    autor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    # Obra declarada en el momento de fichar.
    obra_id = db.Column(db.Integer, db.ForeignKey('obras.id'), nullable=True)

    # Posición en el momento del fichaje. Finalidad declarada: verificar la
    # presencia en obra. Solo se rellena si el tenant lo tiene activado.
    latitud = db.Column(db.Float, nullable=True)
    longitud = db.Column(db.Float, nullable=True)
    precision_metros = db.Column(db.Float, nullable=True)

    # Validación contra geocerca de la obra (solo PWA; ERP puede rellenarlo más adelante).
    geo_estado = db.Column(db.String(20), nullable=True)
    distancia_obra_metros = db.Column(db.Float, nullable=True)
    nota_ubicacion = db.Column(db.Text, nullable=True)

    dispositivo = db.Column(db.String(255), nullable=True)
    ip = db.Column(db.String(45), nullable=True)

    # Obligatorio en altas manuales y en anulaciones: el "por qué" que exige
    # la trazabilidad.
    motivo = db.Column(db.Text, nullable=True)
    evento_anulado_id = db.Column(db.Integer, db.ForeignKey('fichajes_eventos.id'), nullable=True)

    # Referencia al sistema externo del que proviene, si aplica.
    external_ids = db.Column(JSONB, nullable=True)

    hash_previo = db.Column(db.String(64), nullable=True)
    hash = db.Column(db.String(64), nullable=False)

    user = db.relationship('User', foreign_keys=[user_id])
    autor = db.relationship('User', foreign_keys=[autor_id])
    obra = db.relationship('Obra', foreign_keys=[obra_id])
    evento_anulado = db.relationship('FichajeEvento', remote_side=[id])

    def payload_canonico(self):
        """
        Representación determinista del contenido del evento. Es lo que se
        firma: si cambia un solo carácter, el hash deja de cuadrar.
        """
        def val(v):
            if v is None:
                return ''
            if isinstance(v, datetime):
                return v.replace(microsecond=0).isoformat()
            if isinstance(v, date):
                return v.isoformat()
            if isinstance(v, float):
                return f'{v:.6f}'
            return str(v)

        campos = (
            self.secuencia, self.user_id, self.tipo, self.origen,
            self.fecha_laboral, self.ocurrido_en, self.registrado_en,
            self.zona_horaria, self.autor_id, self.obra_id,
            self.latitud, self.longitud, self.precision_metros,
            self.geo_estado, self.distancia_obra_metros, self.nota_ubicacion,
            self.dispositivo, self.ip, self.motivo, self.evento_anulado_id,
            self.hash_previo,
        )
        return '|'.join(val(c) for c in campos)

    def calcular_hash(self):
        return hashlib.sha256(self.payload_canonico().encode('utf-8')).hexdigest()

    def __repr__(self):
        return f'<FichajeEvento #{self.secuencia} {self.tipo} user={self.user_id}>'


class Solicitud(db.Model):
    """
    Petición de recursos (Personal) realizada por Jefes de Obra a Administración.
    """
    __tablename__ = 'solicitudes'

    id = db.Column(db.Integer, primary_key=True)

    # TIPO: 'generica' (Pido perfil) | 'concreta' (Pido persona específica)
    tipo = db.Column(db.String(20), nullable=False)
    # Fíjate que ponemos server_default
    accion = db.Column(db.String(20), nullable=False, server_default='ASIGNAR')
    
    obra_id = db.Column(db.Integer, db.ForeignKey('obras.id'), nullable=False)
    requested_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Solo para solicitudes CONCRETAS
    empleado_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    # Rango de fechas solicitado
    fecha_inicio = db.Column(db.Date, nullable=False)
    fecha_fin = db.Column(db.Date, nullable=False)

    # Solo para solicitudes GENÉRICAS
    perfil_categoria = db.Column(db.String(50), nullable=True) # Ej: "Oficial 1ª"
    perfil_empresa_id = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=True)

    cantidad_solicitada = db.Column(db.Integer, nullable=False, default=1)
    
    # Cantidad cubierta actualmente (calculada dinámicamente según asignaciones)
    cantidad_cubierta = db.Column(db.Integer, nullable=False, default=0)

    # ESTADOS: PENDIENTE, EN_PROCESO, CUMPLIDA, CERRADA_PARCIAL, DENEGADA
    estado = db.Column(db.String(20), nullable=False, default='PENDIENTE')
    
    # True si el sistema la marcó como CUMPLIDA automáticamente al detectar asignaciones
    auto_fulfilled = db.Column(db.Boolean, nullable=False, default=False)

    # JSON técnico: fechas pendientes, modo de baja, etc.
    comentarios = db.Column(db.Text, nullable=True)
    # Notas del solicitante para RRHH (solo texto humano)
    notas = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=_utc_now)
    updated_at = db.Column(db.DateTime, default=_utc_now, onupdate=_utc_now)
    
    resolved_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    resolved_at = db.Column(db.DateTime, nullable=True)

    # Relaciones
    obra = db.relationship('Obra', backref='solicitudes')
    requested_by = db.relationship('User', foreign_keys=[requested_by_id])
    empleado = db.relationship('User', foreign_keys=[empleado_id])
    resolved_by = db.relationship('User', foreign_keys=[resolved_by_id])
    perfil_empresa = db.relationship('Company')

    def __repr__(self):
        return f'<Solicitud {self.id} {self.tipo} {self.estado}>'
    
    
# ==========================================
# MÓDULO DE VEHÍCULOS
# ==========================================

class Vehiculo(db.Model):
    """Flota de vehículos asignables a operarios por día."""
    __tablename__ = 'vehiculos'

    id = db.Column(db.Integer, primary_key=True)
    external_ids = db.Column(JSONB, server_default='{}', nullable=False)

    nombre = db.Column(db.String(120), nullable=False)
    matricula = db.Column(db.String(40), unique=True, nullable=True)
    marca = db.Column(db.String(80), nullable=True)
    modelo = db.Column(db.String(80), nullable=True)
    active = db.Column(db.Boolean, default=True, nullable=False)

    # Último conductor / odómetro conocidos (sync Odoo — relleno futuro)
    odoo_driver_partner_id = db.Column(db.Integer, nullable=True)
    odoo_driver_name = db.Column(db.String(160), nullable=True)
    odoo_odometer_date = db.Column(db.Date, nullable=True)
    odoo_odometer_value = db.Column(db.Float, nullable=True)

    created_at = db.Column(db.DateTime, default=_utc_now)
    updated_at = db.Column(db.DateTime, default=_utc_now, onupdate=_utc_now)

    asignaciones = db.relationship('AsignacionVehiculo', backref='vehiculo', lazy=True)

    def label(self):
        mat = (self.matricula or '').strip()
        nom = (self.nombre or '').strip()
        if mat and nom:
            return f"{mat} — {nom}"
        return mat or nom or f"Vehículo #{self.id}"

    def __repr__(self):
        return f'<Vehiculo {self.id} {self.matricula or self.nombre}>'


class AsignacionVehiculo(db.Model):
    """Empleado con vehículo en una fecha (1 vehículo/día y 1 persona/día)."""
    __tablename__ = 'asignaciones_vehiculo'
    __table_args__ = (
        db.UniqueConstraint('vehiculo_id', 'fecha', name='uq_vehiculo_fecha'),
        db.UniqueConstraint('user_id', 'fecha', name='uq_user_vehiculo_fecha'),
    )

    id = db.Column(db.Integer, primary_key=True)
    vehiculo_id = db.Column(db.Integer, db.ForeignKey('vehiculos.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    fecha = db.Column(db.Date, nullable=False)
    solicitud_id = db.Column(
        db.Integer, db.ForeignKey('solicitudes_vehiculo.id', ondelete='SET NULL'), nullable=True
    )

    created_at = db.Column(db.DateTime, default=_utc_now)

    user = db.relationship('User', backref='asignaciones_vehiculo')
    solicitud = db.relationship(
        'SolicitudVehiculo', backref='asignaciones_vinculadas', foreign_keys=[solicitud_id]
    )

    def __repr__(self):
        return f'<AsignacionVehiculo V:{self.vehiculo_id} U:{self.user_id} {self.fecha}>'


class RegistroOdometro(db.Model):
    """Snapshot diario viaje Odoo (tms.shipment) vs asignación planificada."""
    __tablename__ = 'registros_odometro'
    __table_args__ = (
        db.UniqueConstraint('vehiculo_id', 'fecha', name='uq_odometro_vehiculo_fecha'),
    )

    id = db.Column(db.Integer, primary_key=True)
    vehiculo_id = db.Column(db.Integer, db.ForeignKey('vehiculos.id'), nullable=False)
    fecha = db.Column(db.Date, nullable=False)
    valor = db.Column(db.Float, nullable=True)  # end_kilometers del viaje

    odoo_driver_partner_id = db.Column(db.Integer, nullable=True)
    odoo_driver_name = db.Column(db.String(160), nullable=True)

    planned_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    # Datos del viaje tms.shipment (fuente de uso real)
    km_start = db.Column(db.Float, nullable=True)
    qty_km = db.Column(db.Float, nullable=True)
    km_previsto = db.Column(db.Float, nullable=True)
    desvio = db.Column(db.Float, nullable=True)  # % desvío vs previsto
    viaje_code = db.Column(db.String(64), nullable=True)
    viaje_odoo_id = db.Column(db.Integer, nullable=True)

    # ok | mismatch_driver | sin_km | sin_planificar
    estado = db.Column(db.String(40), nullable=False, default='ok')

    created_at = db.Column(db.DateTime, default=_utc_now)
    updated_at = db.Column(db.DateTime, default=_utc_now, onupdate=_utc_now)

    vehiculo = db.relationship('Vehiculo', backref='registros_odometro')
    planned_user = db.relationship('User', foreign_keys=[planned_user_id])

    def __repr__(self):
        return f'<RegistroOdometro V:{self.vehiculo_id} {self.fecha} {self.estado}>'


class SolicitudVehiculo(db.Model):
    """Petición de vehículo (espejo de Solicitud personal, persona-bound)."""
    __tablename__ = 'solicitudes_vehiculo'

    id = db.Column(db.Integer, primary_key=True)
    accion = db.Column(db.String(20), nullable=False, server_default='ASIGNAR')

    requested_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    empleado_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    vehiculo_id = db.Column(db.Integer, db.ForeignKey('vehiculos.id'), nullable=True)

    fecha_inicio = db.Column(db.Date, nullable=False)
    fecha_fin = db.Column(db.Date, nullable=False)

    # PENDIENTE | EN_PROCESO | CUMPLIDA | CERRADA_PARCIAL | DENEGADA
    estado = db.Column(db.String(20), nullable=False, default='PENDIENTE')
    notas = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=_utc_now)
    resolved_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    resolved_at = db.Column(db.DateTime, nullable=True)

    requested_by = db.relationship('User', foreign_keys=[requested_by_id])
    empleado = db.relationship('User', foreign_keys=[empleado_id])
    vehiculo = db.relationship('Vehiculo', foreign_keys=[vehiculo_id])
    resolved_by = db.relationship('User', foreign_keys=[resolved_by_id])

    def __repr__(self):
        return f'<SolicitudVehiculo {self.id} {self.accion} {self.estado}>'


class AnomaliaVehiculoVista(db.Model):
    """Acuse informativo de anomalía de flota (oculta de la vista por defecto)."""
    __tablename__ = 'anomalias_vehiculo_vista'
    __table_args__ = (
        db.UniqueConstraint('kind', 'clave', name='uq_anomalia_vehiculo_vista_kind_clave'),
    )

    id = db.Column(db.Integer, primary_key=True)
    # salto | cross | leave | desvio | mismatch | sin_km | sin_plan
    kind = db.Column(db.String(32), nullable=False, index=True)
    clave = db.Column(db.String(160), nullable=False)
    visto_por_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    visto_en = db.Column(db.DateTime, default=_utc_now, nullable=False)
    payload = db.Column(db.JSON, nullable=True)

    visto_por = db.relationship('User', foreign_keys=[visto_por_id])

    def __repr__(self):
        return f'<AnomaliaVehiculoVista {self.kind}:{self.clave}>'


class Rating(db.Model):
    """Sistema de Puntuación/Reputación para Operarios."""
    __tablename__ = 'ratings'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    score = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=_utc_now)
    
    # >>> NUEVO: Para poder resetear la suma sin borrar el dato
    is_active = db.Column(db.Boolean, default=True, nullable=False) 
    
    user = db.relationship('User', foreign_keys=[user_id], backref='ratings_received')
    created_by = db.relationship('User', foreign_keys=[created_by_id])
    
    
class Festivo(db.Model):
    __tablename__ = 'festivos'
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.Date, nullable=False, unique=True)
    descripcion = db.Column(db.String(100))

    def __repr__(self):
        return f'<Festivo {self.fecha}: {self.descripcion}>'


# ==========================================
# AUSENCIAS PLANIFICADAS (vacaciones, bajas, permisos…)
# ==========================================
# Estados internos (genéricos, independientes del ERP):
LEAVE_STATUS_APROBADA = 'aprobada'
LEAVE_STATUS_PENDIENTE = 'pendiente'
LEAVE_STATUS_RECHAZADA = 'rechazada'

LEAVE_SOURCE_MANUAL = 'manual'
LEAVE_SOURCE_ODOO = 'odoo'
LEAVE_SOURCE_ERP = 'erp'

CONFLICT_PENDING = 'pendiente'
CONFLICT_KEEP_LEAVE = 'mantener_ausencia'      # quitar asignación (manual / legacy)
CONFLICT_KEEP_ASSIGNMENT = 'mantener_asignacion'  # ignorar ausencia ese día
CONFLICT_OVERLAY = 'overlay'  # Odoo manda: mantener asignación, marcar en UI


class AusenciaPlanificada(db.Model):
    """
    Ausencia genérica por empleado (vacaciones, puente, baja, permiso…).
    Origen: alta manual o sync ERP (Odoo hr.leave u otro adaptador).
    Solo estado=aprobada es efectiva (conflictos, no-ausencia, calendario efectivo).
    """
    __tablename__ = 'ausencias_planificadas'
    __table_args__ = (
        db.Index('ix_ausencias_user_fechas', 'user_id', 'fecha_inicio', 'fecha_fin'),
        db.Index('ix_ausencias_external', 'origen', 'external_id'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    fecha_inicio = db.Column(db.Date, nullable=False)
    fecha_fin = db.Column(db.Date, nullable=False)
    dias = db.Column(db.Float, nullable=True)

    # Etiqueta visible: "Vacaciones", "Baja médica", "Puente", …
    tipo = db.Column(db.String(120), nullable=False, default='Ausencia')
    tipo_external_id = db.Column(db.String(64), nullable=True)

    estado = db.Column(db.String(20), nullable=False, default=LEAVE_STATUS_APROBADA)
    origen = db.Column(db.String(20), nullable=False, default=LEAVE_SOURCE_MANUAL)
    external_id = db.Column(db.String(64), nullable=True)

    descripcion = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=_utc_now)
    updated_at = db.Column(db.DateTime, default=_utc_now, onupdate=_utc_now)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    user = db.relationship('User', foreign_keys=[user_id], backref='ausencias_planificadas')
    created_by = db.relationship('User', foreign_keys=[created_by_id])

    @property
    def es_efectiva(self):
        return self.estado == LEAVE_STATUS_APROBADA

    def covers(self, day):
        return self.fecha_inicio <= day <= self.fecha_fin

    def __repr__(self):
        return f'<AusenciaPlanificada {self.id} {self.tipo} {self.fecha_inicio}-{self.fecha_fin}>'


class AusenciaConflicto(db.Model):
    """
    Conflicto: empleado con asignación en un día y ausencia planificada aprobada.
    Requiere confirmación (admin / jefe según config) salvo auto-resolución del tenant.
    """
    __tablename__ = 'ausencias_conflictos'
    __table_args__ = (
        db.UniqueConstraint(
            'user_id', 'fecha', 'obra_id', 'ausencia_id',
            name='uq_ausencia_conflicto_dia',
        ),
        db.Index('ix_ausencias_conflictos_estado', 'estado'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    fecha = db.Column(db.Date, nullable=False)
    obra_id = db.Column(db.Integer, db.ForeignKey('obras.id'), nullable=False)
    ausencia_id = db.Column(db.Integer, db.ForeignKey('ausencias_planificadas.id'), nullable=False)
    asignacion_id = db.Column(
        db.Integer, db.ForeignKey('asignaciones.id', ondelete='SET NULL'), nullable=True
    )

    estado = db.Column(db.String(30), nullable=False, default=CONFLICT_PENDING)
    resolved_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    resolved_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=_utc_now)

    user = db.relationship('User', foreign_keys=[user_id])
    obra = db.relationship('Obra', foreign_keys=[obra_id])
    ausencia = db.relationship('AusenciaPlanificada', backref='conflictos')
    asignacion = db.relationship('Asignacion', foreign_keys=[asignacion_id])
    resolved_by = db.relationship('User', foreign_keys=[resolved_by_id])

    @property
    def pendiente(self):
        return self.estado == CONFLICT_PENDING

    def __repr__(self):
        return f'<AusenciaConflicto {self.id} user={self.user_id} {self.fecha} {self.estado}>'


class ConfiguracionGlobal(db.Model):
    __tablename__ = 'configuracion_global'
    id = db.Column(db.Integer, primary_key=True)
    clave = db.Column(db.String(50), unique=True, nullable=False)
    # Text: Academia y otros JSON de onboarding superan con facilidad 255 chars.
    valor = db.Column(db.Text, nullable=False)

    def __repr__(self):
        return f'<ConfiguracionGlobal {self.clave}={self.valor}>'


class RolePermission(db.Model):
    """Matriz de permisos por rol dentro del tenant (R/W/X por módulo)."""
    __tablename__ = 'role_permissions'
    __table_args__ = (
        db.UniqueConstraint('role', 'module', name='uq_role_permissions_role_module'),
    )

    id = db.Column(db.Integer, primary_key=True)
    role = db.Column(db.String(40), nullable=False, index=True)
    module = db.Column(db.String(50), nullable=False, index=True)
    can_read = db.Column(db.Boolean, nullable=False, default=False)
    can_write = db.Column(db.Boolean, nullable=False, default=False)
    can_execute = db.Column(db.Boolean, nullable=False, default=False)

    def __repr__(self):
        flags = ''.join([
            'r' if self.can_read else '-',
            'w' if self.can_write else '-',
            'x' if self.can_execute else '-',
        ])
        return f'<RolePermission {self.role}/{self.module} {flags}>'


class TenantRole(db.Model):
    """
    Catálogo de roles del tenant.
    Clave inmutable (admin, jefe_obra…); etiqueta editable salvo roles bloqueados.
    """
    __tablename__ = 'tenant_roles'

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(40), nullable=False, unique=True, index=True)
    label = db.Column(db.String(80), nullable=False)
    is_system = db.Column(db.Boolean, nullable=False, default=False)
    is_locked = db.Column(db.Boolean, nullable=False, default=False)
    sort_order = db.Column(db.Integer, nullable=False, default=100)
    clone_from = db.Column(db.String(40), nullable=True)

    def __repr__(self):
        return f'<TenantRole {self.key}>'


# ==========================================
# MÓDULO DE NOTAS Y REUNIONES (CRM INTERNO)
# ==========================================
nota_obra = db.Table('nota_obra',
    db.Column('nota_id', db.Integer, db.ForeignKey('notas.id', ondelete='CASCADE'), primary_key=True),
    db.Column('obra_id', db.Integer, db.ForeignKey('obras.id', ondelete='CASCADE'), primary_key=True)
)

nota_user = db.Table('nota_user',
    db.Column('nota_id', db.Integer, db.ForeignKey('notas.id', ondelete='CASCADE'), primary_key=True),
    db.Column('user_id', db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
)


class Nota(db.Model):
    __tablename__ = 'notas'
    
    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(200), nullable=False)
    contenido = db.Column(db.Text, nullable=False)
    fecha = db.Column(db.Date, default=date.today, nullable=False)
    es_privada = db.Column(db.Boolean, default=False, nullable=False)
    
    autor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=_utc_now)
    
    # Relaciones
    autor = db.relationship('User', foreign_keys=[autor_id])
    
    # Las notas aparecerán mágicamente en Obra.notas y User.notas_implicado
    obras = db.relationship('Obra', secondary=nota_obra, backref=db.backref('notas', lazy='dynamic'))
    usuarios_implicados = db.relationship('User', secondary=nota_user, backref=db.backref('notas_implicado', lazy='dynamic'))

    def __repr__(self):
        return f'<Nota {self.titulo} - Autor: {self.autor_id}>'


class NotaAudioJob(db.Model):
    """Procesamiento asíncrono de audio → nota privada (Whisper + resumen)."""
    __tablename__ = 'nota_audio_jobs'

    ESTADO_PENDIENTE = 'pendiente'
    ESTADO_PROCESANDO = 'procesando'
    ESTADO_COMPLETADO = 'completado'
    ESTADO_ERROR = 'error'

    id = db.Column(db.Integer, primary_key=True)
    autor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    estado = db.Column(db.String(20), nullable=False, default=ESTADO_PENDIENTE)
    archivo_path = db.Column(db.String(500), nullable=True)
    archivo_nombre = db.Column(db.String(255), nullable=True)
    duracion_segundos = db.Column(db.Float, nullable=True)
    nota_id = db.Column(db.Integer, db.ForeignKey('notas.id', ondelete='SET NULL'), nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    meta_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=_utc_now)
    updated_at = db.Column(db.DateTime, default=_utc_now, onupdate=_utc_now)
    completed_at = db.Column(db.DateTime, nullable=True)

    autor = db.relationship('User', foreign_keys=[autor_id])
    nota = db.relationship('Nota', foreign_keys=[nota_id])

    def __repr__(self):
        return f'<NotaAudioJob {self.id} {self.estado}>'