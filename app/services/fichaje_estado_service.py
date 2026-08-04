"""
Agregación visual del estado de fichaje de un día.

Un trabajador puede tener varias filas RegistroFichaje el mismo día
(multi-obra, paracaidista + plan, etc.). El calendario del trabajador ya
elige un color “final”; el tablero debe usar la misma precedencia.
"""

FICHAJE_OK = {
    'Correcto',
    'Correcto_Automatico',
    'Resuelto_Movido',
    'Resuelto_Asignado',
    'Resuelto_Dividido',
    'Resuelto_Ignorado',
    'Resuelto_Falta',
    'Resuelto_Ausencia',
    'Exento_Ausencia',
}
FICHAJE_ROJO = {'Conflicto', 'Paracaidista'}
FICHAJE_NARANJA = {'Ausencia', 'Pendiente', 'Retraso'}


def estado_fichaje_agregado(estados):
    """
    Devuelve un único estado representativo del día para pintar la pelotita.

    Precedencia: rojo (pendiente grave) > naranja (pendiente) > verde (OK /
    resuelto / exento). Si todo está resuelto o correcto, el resultado es
    verde aunque haya varias filas o mezcla Correcto + Resuelto_*.
    """
    limpios = [e for e in (estados or []) if e]
    if not limpios:
        return 'Sin_Registro'

    if any(est in FICHAJE_ROJO for est in limpios):
        for est in limpios:
            if est in FICHAJE_ROJO:
                return est

    if any(est in FICHAJE_NARANJA for est in limpios):
        for est in limpios:
            if est in FICHAJE_NARANJA:
                return est

    if all(
        est in FICHAJE_OK or (est or '').startswith('Resuelto')
        for est in limpios
    ):
        for preferido in (
            'Correcto',
            'Correcto_Automatico',
            'Resuelto_Asignado',
            'Resuelto_Movido',
            'Resuelto_Dividido',
            'Resuelto_Falta',
            'Resuelto_Ignorado',
            'Resuelto_Ausencia',
            'Exento_Ausencia',
        ):
            if preferido in limpios:
                return preferido
        return limpios[0]

    if any((est or '').startswith('Resuelto') for est in limpios):
        return 'Correcto'

    return 'Pendiente'


def color_fichaje_agregado(estados):
    """Misma lógica que el calendario del trabajador (hex)."""
    estado = estado_fichaje_agregado(estados)
    if estado in FICHAJE_ROJO:
        return '#ef4444'
    if estado in FICHAJE_NARANJA or estado == 'Pendiente':
        return '#f59e0b'
    if estado in FICHAJE_OK or (estado or '').startswith('Resuelto'):
        if estado == 'Exento_Ausencia':
            return '#7c3aed'
        return '#10b981'
    if estado == 'Sin_Registro':
        return '#94a3b8'
    return '#f59e0b'
