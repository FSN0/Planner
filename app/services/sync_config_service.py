"""Configuración y planificación de sincronización Odoo."""
from datetime import datetime, timedelta

from app import db
from app.models import ConfiguracionGlobal
from app.utils.timezone_utils import now_local, today_local

DEFAULTS = {
    'sync_obras_enabled': 'true',
    'sync_empleados_enabled': 'true',
    'sync_subcontratas_enabled': 'true',
    'sync_fichajes_enabled': 'true',
    'sync_master_hour': '3',
    'sync_master_minute': '0',
    'sync_fichajes_interval': '30',
    'sync_fichajes_hour_start': '7',
    'sync_fichajes_hour_end': '19',
    'sync_fichajes_retro_enabled': 'true',
    'sync_fichajes_retro_days': '30',
    'sync_fichajes_retro_hour': '2',
    'sync_fichajes_retro_minute': '30',
    'sync_last_master_date': '',
    'sync_last_fichajes_at': '',
    'sync_last_fichajes_retro_date': '',
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
        'key': 'fichajes',
        'tipo_log': 'Fichajes',
        'label': 'Fichajes / asistencia',
        'icon': 'fa-fingerprint',
        'color': 'danger',
        'config_enabled': 'sync_fichajes_enabled',
        'description': 'Cruza fichajes Odoo con la planificación. En vivo durante el día y revisión retrospectiva nocturna.',
        'default_schedule': 'Cada 30 min (07:00–19:00) + retrospectivo diario',
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
        cfg['obras_enabled'] = cfg['sync_obras_enabled'].lower() == 'true'
        cfg['empleados_enabled'] = cfg['sync_empleados_enabled'].lower() == 'true'
        cfg['subcontratas_enabled'] = cfg['sync_subcontratas_enabled'].lower() == 'true'
        cfg['fichajes_enabled'] = cfg['sync_fichajes_enabled'].lower() == 'true'
        cfg['master_enabled'] = cfg['obras_enabled'] or cfg['empleados_enabled'] or cfg['subcontratas_enabled']
        return cfg

    @classmethod
    def save_config(cls, data):
        bool_map = {
            'sync_obras_enabled': data.get('sync_obras_enabled'),
            'sync_empleados_enabled': data.get('sync_empleados_enabled'),
            'sync_subcontratas_enabled': data.get('sync_subcontratas_enabled'),
            'sync_fichajes_enabled': data.get('sync_fichajes_enabled'),
            'sync_fichajes_retro_enabled': data.get('sync_fichajes_retro_enabled'),
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
        }
        for field, (lo, hi, key) in int_map.items():
            if field in data and data[field] is not None and data[field] != '':
                val = max(lo, min(hi, int(data[field])))
                cls._set_raw(key, val)

        db.session.commit()

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
    def should_run_master_sync(cls):
        cfg = cls.get_config()
        if not cfg['master_enabled']:
            return False
        now = now_local()
        target = now.replace(hour=cfg['master_hour'], minute=cfg['master_minute'], second=0, microsecond=0)
        if abs((now - target).total_seconds()) > 300:
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
