# app/services/oficina_obra_service.py
#
# Obra sintética «Oficina»: opcional por tenant. Sirve para fichar cuando no
# hay tajo asignado y para planificar quién está en oficina vs en obra.

from app import db
from app.models import Obra
from app.services.config_service import get_tenant_config

CONFIG_OBRA_OFICINA = 'obra_oficina_activa'

CODIGO_OFICINA = 'OFICINA'
NOMBRE_OFICINA = 'Oficina'
COLOR_OFICINA = '#64748b'  # slate: se distingue de los pasteles de obra


def oficina_activa():
    return str(get_tenant_config(CONFIG_OBRA_OFICINA, default='False')) == 'True'


def es_obra_oficina(obra):
    if obra is None:
        return False
    if (obra.codigo or '').upper() == CODIGO_OFICINA:
        return True
    ext = obra.external_ids or {}
    return ext.get('sistema') == 'oficina'


def buscar_obra_oficina(incluir_borradas=False):
    q = Obra.query.filter(Obra.codigo == CODIGO_OFICINA)
    if not incluir_borradas:
        q = q.filter(Obra.is_deleted.is_(False))
    obra = q.first()
    if obra:
        return obra

    # Fallback JSONB sin cargar todas las obras en memoria
    q = Obra.query.filter(Obra.external_ids.contains({'sistema': 'oficina'}))
    if not incluir_borradas:
        q = q.filter(Obra.is_deleted.is_(False))
    return q.order_by(Obra.id.asc()).first()


def asegurar_obra_oficina():
    """Crea o reactiva la obra Oficina. No hace commit."""
    obra = buscar_obra_oficina(incluir_borradas=True)
    if obra is None:
        obra = Obra(
            codigo=CODIGO_OFICINA,
            nombre=NOMBRE_OFICINA,
            descripcion=(
                'Espacio de oficina / sede. Permite fichar y planificar personal '
                'cuando no está en un tajo de obra.'
            ),
            ubicacion='Oficina',
            estado='En Curso',
            color=COLOR_OFICINA,
            is_deleted=False,
            external_ids={'sistema': 'oficina'},
        )
        db.session.add(obra)
        db.session.flush()
        return obra

    obra.is_deleted = False
    obra.estado = 'En Curso'
    obra.nombre = NOMBRE_OFICINA
    obra.codigo = CODIGO_OFICINA
    ext = dict(obra.external_ids or {})
    ext['sistema'] = 'oficina'
    obra.external_ids = ext
    if not obra.color:
        obra.color = COLOR_OFICINA
    db.session.flush()
    return obra


def desactivar_obra_oficina():
    """Archiva la obra Oficina (soft-delete). No hace commit."""
    obra = buscar_obra_oficina(incluir_borradas=True)
    if obra is None:
        return None
    obra.is_deleted = True
    obra.estado = 'FINALIZADA'
    db.session.flush()
    return obra


def sincronizar_obra_oficina(activar):
    """Aplica el interruptor de configuración a la fila de obras."""
    if activar:
        return asegurar_obra_oficina()
    return desactivar_obra_oficina()
