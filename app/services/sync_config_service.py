"""Configuración y planificación de sincronización Odoo."""
import json
from datetime import datetime, timedelta

from app import db
from app.models import ConfiguracionGlobal
from app.utils.timezone_utils import now_local, today_local

# Lista de fábrica (Soltec). El tenant puede ampliarla o cambiar el rol en Configurar.
DEFAULT_EMPLEADOS_DEPARTAMENTOS = [
    'Administración G', 'Administración S', 'Compras', 'Dirección',
    'Encargados/Of.1ª', 'Estudios clima', 'Estudios electricidad',
    'JO clima', 'JO electricidad', 'Oficiales 2ª/3ª', 'Producción clima',
    'Producción electricidad',
]
WILDCARD_TODOS_DEPARTAMENTOS = '*'
EMPLEADOS_IMPORT_ROLES = ('operario', 'jefe_obra', 'laboral', 'admin')


def infer_odoo_department_role(label):
    """Rol de fábrica a partir del nombre (solo para migrar listas antiguas)."""
    d = (label or '').lower()
    if 'jo ' in d or d.startswith('jo ') or 'jefe de obra' in d:
        return 'jefe_obra'
    return 'operario'


def default_empleados_departamento_map():
    return [
        {'department': name, 'role': infer_odoo_department_role(name)}
        for name in DEFAULT_EMPLEADOS_DEPARTAMENTOS
    ]


def _normalize_import_role(role):
    r = (role or '').strip().lower().replace(' ', '_')
    aliases = {
        'jefe': 'jefe_obra',
        'jefedeobra': 'jefe_obra',
        'oficina': 'laboral',
        'rrhh': 'laboral',
        'administrador': 'admin',
        'administracion': 'admin',
        'administración': 'admin',
    }
    r = aliases.get(r, r)
    if r in EMPLEADOS_IMPORT_ROLES:
        return r
    return 'operario'


def _row_from_unknown(item):
    if isinstance(item, dict):
        dept = str(
            item.get('department')
            or item.get('departamento')
            or item.get('name')
            or ''
        ).strip()
        if not dept:
            return None
        role = item.get('role') or item.get('rol') or infer_odoo_department_role(dept)
        return {'department': dept, 'role': _normalize_import_role(role)}
    dept = str(item).strip()
    if not dept:
        return None
    if '=' in dept:
        left, right = dept.split('=', 1)
        left, right = left.strip(), right.strip()
        if left:
            return {'department': left, 'role': _normalize_import_role(right)}
    return {'department': dept, 'role': infer_odoo_department_role(dept)}


def parse_empleados_departamento_map(raw, *, use_defaults_if_empty=True):
    items = []
    if isinstance(raw, list):
        items = raw
    else:
        text = str(raw or '').replace('\r\n', '\n').strip()
        if text:
            if text.startswith('['):
                try:
                    data = json.loads(text)
                    if isinstance(data, list):
                        items = data
                except (TypeError, ValueError, json.JSONDecodeError):
                    items = []
            if not items:
                if '\n' in text:
                    items = text.split('\n')
                elif ';' in text:
                    items = text.split(';')
                else:
                    items = [text]
    rows = []
    for item in items:
        row = _row_from_unknown(item)
        if row:
            rows.append(row)
    if rows:
        return rows
    if use_defaults_if_empty:
        return default_empleados_departamento_map()
    return []


def serialize_empleados_departamento_map(rows):
    clean = []
    for row in rows or []:
        dept = str((row or {}).get('department') or '').strip()
        if not dept:
            continue
        clean.append({
            'department': dept,
            'role': _normalize_import_role((row or {}).get('role')),
        })
    return json.dumps(clean, ensure_ascii=False)


def parse_empleados_departamentos(raw, *, use_defaults_if_empty=True):
    return [
        row['department']
        for row in parse_empleados_departamento_map(
            raw, use_defaults_if_empty=use_defaults_if_empty
        )
    ]


def resolve_departamento_role(department, mapping):
    """Rol configurado para ese departamento Odoo, o None si no entra."""
    mapping = mapping or []
    dept = (department or '').lower()
    wildcard_role = None
    best_role = None
    best_len = -1
    for row in mapping:
        if isinstance(row, str):
            label, role = row, infer_odoo_department_role(row)
        else:
            label = str((row or {}).get('department') or '').strip()
            role = _normalize_import_role((row or {}).get('role'))
        if not label:
            continue
        if label == WILDCARD_TODOS_DEPARTAMENTOS:
            wildcard_role = role
            continue
        if label.lower() in dept and len(label) > best_len:
            best_role = role
            best_len = len(label)
    if best_role:
        return best_role
    return wildcard_role


def department_is_allowed(department, allowed):
    return resolve_departamento_role(department, allowed) is not None


def empleados_departamentos_as_text(lines=None):
    if lines and isinstance(lines[0], dict):
        lines = [r['department'] for r in lines]
    return '\n'.join(lines if lines is not None else DEFAULT_EMPLEADOS_DEPARTAMENTOS)


DEFAULTS = {
    'sync_obras_enabled': 'true',
    'sync_empleados_enabled': 'true',
    'sync_subcontratas_enabled': 'true',
    'sync_fichajes_enabled': 'true',
    'sync_ausencias_enabled': 'true',
    'sync_vehiculos_enabled': 'true',
    'sync_master_hour': '3',
    'sync_master_minute': '0',
    'sync_fichajes_interval': '30',
    'sync_fichajes_hour_start': '7',
    'sync_fichajes_hour_end': '19',
    'sync_fichajes_retro_enabled': 'true',
    'sync_fichajes_retro_days': '30',
    'sync_fichajes_retro_hour': '2',
    'sync_fichajes_retro_minute': '30',
    'sync_vehiculos_interval': '60',
    'sync_vehiculos_hour_start': '7',
    'sync_vehiculos_hour_end': '19',
    'sync_vehiculos_retro_enabled': 'true',
    'sync_vehiculos_retro_days': '14',
    'sync_vehiculos_retro_hour': '3',
    'sync_vehiculos_retro_minute': '15',
    'sync_last_master_date': '',
    'sync_last_fichajes_at': '',
    'sync_last_fichajes_retro_date': '',
    'sync_last_vehiculos_at': '',
    'sync_last_vehiculos_retro_date': '',
    'sync_empleados_departamentos': serialize_empleados_departamento_map(
        default_empleados_departamento_map()
    ),
}

SYNC_MODULES = [
    {
        'key': 'obras',
        'tipo_log': 'Obras',
        'label': 'Obras / Proyectos',
        'icon': 'fa-building',
        'color': 'primary',
        'config_enabled': 'sync_obras_enabled',
        'description': 'Importa proyectos BIM activos desde Odoo (bim.project).',
        'default_schedule': 'Diario a las 03:00',
    },
    {
        'key': 'empleados',
        'tipo_log': 'Empleados',
        'label': 'Personal interno',
        'icon': 'fa-users',
        'color': 'info',
        'config_enabled': 'sync_empleados_enabled',
        'description': 'Sincroniza empleados internos (hr.employee) con departamentos autorizados.',
        'default_schedule': 'Diario a las 03:00',
    },
    {
        'key': 'subcontratas',
        'tipo_log': 'Subcontratas',
        'label': 'Subcontratas',
        'icon': 'fa-hard-hat',
        'color': 'warning',
        'config_enabled': 'sync_subcontratas_enabled',
        'description': 'Importa empresas subcontrata y sus contactos externos.',
        'default_schedule': 'Diario a las 03:00',
    },
    {
        'key': 'ausencias',
        'tipo_log': 'Ausencias',
        'label': 'Ausencias / Time Off',
        'icon': 'fa-umbrella-beach',
        'color': 'success',
        'config_enabled': 'sync_ausencias_enabled',
        'description': 'Importa vacaciones, bajas, permisos y puentes (hr.leave) con su tipo y estado.',
        'default_schedule': 'Diario a las 03:00',
    },
    {
        'key': 'fichajes',
        'tipo_log': 'Fichajes',
        'label': 'Fichajes / asistencia',
        'icon': 'fa-fingerprint',
        'color': 'danger',
        'config_enabled': 'sync_fichajes_enabled',
        'description': 'Cruza fichajes Odoo con la planificación. En vivo durante el día y revisión retrospectiva nocturna.',
        'default_schedule': 'Cada 30 min (07:00–19:00) + retrospectivo diario',
    },
    {
        'key': 'vehiculos',
        'tipo_log': 'Vehículos',
        'label': 'Vehículos / Flota',
        'icon': 'fa-car',
        'color': 'secondary',
        'config_enabled': 'sync_vehiculos_enabled',
        'description': 'Sincroniza flota (fleet.vehicle) y odómetros diarios. Auditoría informativa plan vs conductor Odoo.',
        'default_schedule': 'Cada 60 min (07:00–19:00) + retrospectivo diario',
    },
]


class SyncConfigService:
    @staticmethod
    def _get_raw(clave, default=None):
        row = ConfiguracionGlobal.query.filter_by(clave=clave).first()
        if row:
            return row.valor
        return default if default is not None else DEFAULTS.get(clave, '')

    @staticmethod
    def _set_raw(clave, valor):
        row = ConfiguracionGlobal.query.filter_by(clave=clave).first()
        if row:
            row.valor = str(valor)
        else:
            db.session.add(ConfiguracionGlobal(clave=clave, valor=str(valor)))

    @classmethod
    def get_config(cls):
        cfg = {}
        for k, v in DEFAULTS.items():
            cfg[k] = cls._get_raw(k, v)
        cfg['master_hour'] = int(cfg['sync_master_hour'])
        cfg['master_minute'] = int(cfg['sync_master_minute'])
        cfg['fichajes_interval'] = int(cfg['sync_fichajes_interval'])
        cfg['fichajes_hour_start'] = int(cfg['sync_fichajes_hour_start'])
        cfg['fichajes_hour_end'] = int(cfg['sync_fichajes_hour_end'])
        cfg['fichajes_retro_enabled'] = cfg['sync_fichajes_retro_enabled'].lower() == 'true'
        cfg['fichajes_retro_days'] = int(cfg['sync_fichajes_retro_days'])
        cfg['fichajes_retro_hour'] = int(cfg['sync_fichajes_retro_hour'])
        cfg['fichajes_retro_minute'] = int(cfg['sync_fichajes_retro_minute'])
        cfg['vehiculos_interval'] = int(cfg['sync_vehiculos_interval'])
        cfg['vehiculos_hour_start'] = int(cfg['sync_vehiculos_hour_start'])
        cfg['vehiculos_hour_end'] = int(cfg['sync_vehiculos_hour_end'])
        cfg['vehiculos_retro_enabled'] = cfg['sync_vehiculos_retro_enabled'].lower() == 'true'
        cfg['vehiculos_retro_days'] = int(cfg['sync_vehiculos_retro_days'])
        cfg['vehiculos_retro_hour'] = int(cfg['sync_vehiculos_retro_hour'])
        cfg['vehiculos_retro_minute'] = int(cfg['sync_vehiculos_retro_minute'])
        cfg['obras_enabled'] = cfg['sync_obras_enabled'].lower() == 'true'
        cfg['empleados_enabled'] = cfg['sync_empleados_enabled'].lower() == 'true'
        cfg['subcontratas_enabled'] = cfg['sync_subcontratas_enabled'].lower() == 'true'
        cfg['fichajes_enabled'] = cfg['sync_fichajes_enabled'].lower() == 'true'
        cfg['ausencias_enabled'] = cfg['sync_ausencias_enabled'].lower() == 'true'
        cfg['vehiculos_enabled'] = cfg['sync_vehiculos_enabled'].lower() == 'true'
        cfg['master_enabled'] = (
            cfg['obras_enabled'] or cfg['empleados_enabled']
            or cfg['subcontratas_enabled'] or cfg['ausencias_enabled']
        )
        cfg['empleados_departamento_map'] = parse_empleados_departamento_map(
            cfg.get('sync_empleados_departamentos')
        )
        cfg['empleados_departamentos'] = [
            row['department'] for row in cfg['empleados_departamento_map']
        ]
        cfg['empleados_departamentos_text'] = empleados_departamentos_as_text(
            cfg['empleados_departamentos']
        )
        return cfg

    @classmethod
    def save_config(cls, data):
        bool_map = {
            'sync_obras_enabled': data.get('sync_obras_enabled'),
            'sync_empleados_enabled': data.get('sync_empleados_enabled'),
            'sync_subcontratas_enabled': data.get('sync_subcontratas_enabled'),
            'sync_fichajes_enabled': data.get('sync_fichajes_enabled'),
            'sync_ausencias_enabled': data.get('sync_ausencias_enabled'),
            'sync_vehiculos_enabled': data.get('sync_vehiculos_enabled'),
            'sync_fichajes_retro_enabled': data.get('sync_fichajes_retro_enabled'),
            'sync_vehiculos_retro_enabled': data.get('sync_vehiculos_retro_enabled'),
        }
        for k, v in bool_map.items():
            if v is not None:
                cls._set_raw(k, 'true' if v in (True, 'true', '1', 1, 'on') else 'false')

        int_map = {
            'sync_master_hour': (0, 23, 'sync_master_hour'),
            'sync_master_minute': (0, 59, 'sync_master_minute'),
            'sync_fichajes_interval': (5, 120, 'sync_fichajes_interval'),
            'sync_fichajes_hour_start': (0, 23, 'sync_fichajes_hour_start'),
            'sync_fichajes_hour_end': (0, 23, 'sync_fichajes_hour_end'),
            'sync_fichajes_retro_days': (1, 365, 'sync_fichajes_retro_days'),
            'sync_fichajes_retro_hour': (0, 23, 'sync_fichajes_retro_hour'),
            'sync_fichajes_retro_minute': (0, 59, 'sync_fichajes_retro_minute'),
            'sync_vehiculos_interval': (5, 180, 'sync_vehiculos_interval'),
            'sync_vehiculos_hour_start': (0, 23, 'sync_vehiculos_hour_start'),
            'sync_vehiculos_hour_end': (0, 23, 'sync_vehiculos_hour_end'),
            'sync_vehiculos_retro_days': (1, 365, 'sync_vehiculos_retro_days'),
            'sync_vehiculos_retro_hour': (0, 23, 'sync_vehiculos_retro_hour'),
            'sync_vehiculos_retro_minute': (0, 59, 'sync_vehiculos_retro_minute'),
        }
        for field, (lo, hi, key) in int_map.items():
            if field in data and data[field] is not None and data[field] != '':
                val = max(lo, min(hi, int(data[field])))
                cls._set_raw(key, val)

        if 'sync_empleados_departamentos' in data:
            raw = data.get('sync_empleados_departamentos')
            rows = parse_empleados_departamento_map(raw, use_defaults_if_empty=False)
            cls._set_raw(
                'sync_empleados_departamentos',
                serialize_empleados_departamento_map(rows),
            )

        db.session.commit()

    @classmethod
    def get_empleados_departamentos(cls):
        return [
            row['department']
            for row in cls.get_empleados_departamento_map()
        ]

    @classmethod
    def get_empleados_departamento_map(cls):
        return parse_empleados_departamento_map(
            cls._get_raw('sync_empleados_departamentos')
        )

    @classmethod
    def mark_master_sync_done(cls):
        cls._set_raw('sync_last_master_date', today_local().isoformat())
        db.session.commit()

    @classmethod
    def mark_fichajes_sync_done(cls):
        cls._set_raw('sync_last_fichajes_at', now_local().strftime('%Y-%m-%d %H:%M:%S'))
        db.session.commit()

    @classmethod
    def mark_fichajes_retro_sync_done(cls):
        cls._set_raw('sync_last_fichajes_retro_date', today_local().isoformat())
        db.session.commit()

    @classmethod
    def mark_vehiculos_sync_done(cls):
        cls._set_raw('sync_last_vehiculos_at', now_local().strftime('%Y-%m-%d %H:%M:%S'))
        db.session.commit()

    @classmethod
    def mark_vehiculos_retro_sync_done(cls):
        cls._set_raw('sync_last_vehiculos_retro_date', today_local().isoformat())
        db.session.commit()

    @classmethod
    def should_run_master_sync(cls):
        cfg = cls.get_config()
        if not cfg['master_enabled']:
            return False
        now = now_local()
        target = now.replace(hour=cfg['master_hour'], minute=cfg['master_minute'], second=0, microsecond=0)
        if now < target:
            return False
        last = cls._get_raw('sync_last_master_date', '')
        return last != today_local().isoformat()

    @classmethod
    def should_run_fichajes_sync(cls):
        cfg = cls.get_config()
        if not cfg['fichajes_enabled']:
            return False
        now = now_local()
        if not (cfg['fichajes_hour_start'] <= now.hour <= cfg['fichajes_hour_end']):
            return False
        last_str = cls._get_raw('sync_last_fichajes_at', '')
        if not last_str:
            return True
        try:
            last = datetime.strptime(last_str, '%Y-%m-%d %H:%M:%S')
            last = last.replace(tzinfo=now.tzinfo) if now.tzinfo else last
        except ValueError:
            return True
        return (now - last).total_seconds() >= cfg['fichajes_interval'] * 60

    @classmethod
    def should_run_fichajes_retro_sync(cls):
        cfg = cls.get_config()
        if not cfg['fichajes_enabled'] or not cfg['fichajes_retro_enabled']:
            return False
        now = now_local()
        target = now.replace(
            hour=cfg['fichajes_retro_hour'],
            minute=cfg['fichajes_retro_minute'],
            second=0,
            microsecond=0,
        )
        if abs((now - target).total_seconds()) > 300:
            return False
        last = cls._get_raw('sync_last_fichajes_retro_date', '')
        return last != today_local().isoformat()

    @classmethod
    def should_run_vehiculos_sync(cls):
        cfg = cls.get_config()
        if not cfg['vehiculos_enabled']:
            return False
        now = now_local()
        if not (cfg['vehiculos_hour_start'] <= now.hour <= cfg['vehiculos_hour_end']):
            return False
        last_str = cls._get_raw('sync_last_vehiculos_at', '')
        if not last_str:
            return True
        try:
            last = datetime.strptime(last_str, '%Y-%m-%d %H:%M:%S')
            last = last.replace(tzinfo=now.tzinfo) if now.tzinfo else last
        except ValueError:
            return True
        return (now - last).total_seconds() >= cfg['vehiculos_interval'] * 60

    @classmethod
    def should_run_vehiculos_retro_sync(cls):
        cfg = cls.get_config()
        if not cfg['vehiculos_enabled'] or not cfg['vehiculos_retro_enabled']:
            return False
        now = now_local()
        target = now.replace(
            hour=cfg['vehiculos_retro_hour'],
            minute=cfg['vehiculos_retro_minute'],
            second=0,
            microsecond=0,
        )
        if abs((now - target).total_seconds()) > 300:
            return False
        last = cls._get_raw('sync_last_vehiculos_retro_date', '')
        return last != today_local().isoformat()

    @classmethod
    def format_master_schedule(cls, cfg=None):
        cfg = cfg or cls.get_config()
        return f"Diario a las {cfg['master_hour']:02d}:{cfg['master_minute']:02d}"

    @classmethod
    def format_fichajes_schedule(cls, cfg=None):
        cfg = cfg or cls.get_config()
        live = (
            f"En vivo cada {cfg['fichajes_interval']} min "
            f"({cfg['fichajes_hour_start']:02d}:00–{cfg['fichajes_hour_end']:02d}:59)"
        )
        if cfg['fichajes_retro_enabled']:
            live += (
                f" · Retrospectivo {cfg['fichajes_retro_hour']:02d}:"
                f"{cfg['fichajes_retro_minute']:02d} ({cfg['fichajes_retro_days']} días)"
            )
        return live

    @classmethod
    def format_vehiculos_schedule(cls, cfg=None):
        cfg = cfg or cls.get_config()
        live = (
            f"En vivo cada {cfg['vehiculos_interval']} min "
            f"({cfg['vehiculos_hour_start']:02d}:00–{cfg['vehiculos_hour_end']:02d}:59)"
            f", últimos {cfg['vehiculos_retro_days']} días"
        )
        if cfg['vehiculos_retro_enabled']:
            live += (
                f" · Retrospectivo {cfg['vehiculos_retro_hour']:02d}:"
                f"{cfg['vehiculos_retro_minute']:02d} "
                f"(mismos {cfg['vehiculos_retro_days']} días)"
            )
        return live

    @classmethod
    def format_fichajes_retro_schedule(cls, cfg=None):
        cfg = cfg or cls.get_config()
        return (
            f"Diario a las {cfg['fichajes_retro_hour']:02d}:{cfg['fichajes_retro_minute']:02d} "
            f"(hoy + {cfg['fichajes_retro_days']} días atrás)"
        )

    @classmethod
    def estimate_next_master(cls, cfg=None):
        cfg = cfg or cls.get_config()
        now = now_local()
        nxt = now.replace(hour=cfg['master_hour'], minute=cfg['master_minute'], second=0, microsecond=0)
        if nxt <= now:
            nxt += timedelta(days=1)
        return nxt

    @classmethod
    def estimate_next_fichajes(cls, cfg=None):
        cfg = cfg or cls.get_config()
        now = now_local()
        last_str = cls._get_raw('sync_last_fichajes_at', '')
        if last_str:
            try:
                base = datetime.strptime(last_str, '%Y-%m-%d %H:%M:%S')
                base = base.replace(tzinfo=now.tzinfo) if now.tzinfo else base
                nxt = base + timedelta(minutes=cfg['fichajes_interval'])
                if nxt > now:
                    return nxt
            except ValueError:
                pass
        if cfg['fichajes_hour_start'] <= now.hour <= cfg['fichajes_hour_end']:
            return now + timedelta(minutes=cfg['fichajes_interval'])
        tomorrow = now + timedelta(days=1)
        return tomorrow.replace(hour=cfg['fichajes_hour_start'], minute=0, second=0, microsecond=0)

    @classmethod
    def estimate_next_fichajes_retro(cls, cfg=None):
        cfg = cfg or cls.get_config()
        if not cfg['fichajes_retro_enabled']:
            return None
        now = now_local()
        nxt = now.replace(
            hour=cfg['fichajes_retro_hour'],
            minute=cfg['fichajes_retro_minute'],
            second=0,
            microsecond=0,
        )
        last = cls._get_raw('sync_last_fichajes_retro_date', '')
        if last == today_local().isoformat():
            nxt += timedelta(days=1)
        elif nxt <= now:
            nxt += timedelta(days=1)
        return nxt

    @classmethod
    def estimate_next_vehiculos(cls, cfg=None):
        cfg = cfg or cls.get_config()
        now = now_local()
        last_str = cls._get_raw('sync_last_vehiculos_at', '')
        if last_str:
            try:
                base = datetime.strptime(last_str, '%Y-%m-%d %H:%M:%S')
                base = base.replace(tzinfo=now.tzinfo) if now.tzinfo else base
                nxt = base + timedelta(minutes=cfg['vehiculos_interval'])
                if nxt > now:
                    return nxt
            except ValueError:
                pass
        if cfg['vehiculos_hour_start'] <= now.hour <= cfg['vehiculos_hour_end']:
            return now + timedelta(minutes=cfg['vehiculos_interval'])
        tomorrow = now + timedelta(days=1)
        return tomorrow.replace(hour=cfg['vehiculos_hour_start'], minute=0, second=0, microsecond=0)

    @classmethod
    def estimate_next_vehiculos_retro(cls, cfg=None):
        cfg = cfg or cls.get_config()
        if not cfg['vehiculos_retro_enabled']:
            return None
        now = now_local()
        nxt = now.replace(
            hour=cfg['vehiculos_retro_hour'],
            minute=cfg['vehiculos_retro_minute'],
            second=0,
            microsecond=0,
        )
        last = cls._get_raw('sync_last_vehiculos_retro_date', '')
        if last == today_local().isoformat():
            nxt += timedelta(days=1)
        elif nxt <= now:
            nxt += timedelta(days=1)
        return nxt
