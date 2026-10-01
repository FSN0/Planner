"""Análisis de diffs Odoo para previews manuales enriquecidos."""
from app.models import User


def _obra_razones(obra):
    razones = []
    if obra.get('warn_jefe'):
        raw = obra.get('jefe_odoo_raw') or 'sin asignar'
        razones.append(
            f"Jefe de obra «{raw}» no está vinculado en la BD local. "
            "En sync automática se omitirá hasta que lo asignes manualmente."
        )
    if obra.get('warn_encargado'):
        raw = obra.get('enc_odoo_raw') or 'sin asignar'
        razones.append(
            f"Encargado «{raw}» no está vinculado en la BD local. "
            "En sync automática se omitirá hasta que lo asignes manualmente."
        )
    return razones


def analyze_obras_preview(diff):
    listos = []
    incidencias = []
    omitidos_auto = []

    for obra in diff.get('nuevas', []):
        razones = _obra_razones(obra)
        entry = {**obra, 'accion': 'nueva', 'razones': razones}
        if razones:
            incidencias.append(entry)
            omitidos_auto.append(entry)
        else:
            listos.append(entry)

    for obra in diff.get('actualizadas', []):
        razones = _obra_razones(obra)
        entry = {**obra, 'accion': 'actualizar', 'razones': razones}
        if razones:
            incidencias.append(entry)
            omitidos_auto.append(entry)
        else:
            listos.append(entry)

    finalizadas = [{**o, 'accion': 'finalizar', 'razones': [
        'Ya no aparece activa en Odoo. Se marcará como Finalizada en local.'
    ]} for o in diff.get('finalizadas', [])]

    validadas = [{**o, 'accion': 'validada_manual', 'razones': [
        'Responsable asignado manualmente en la app; Odoo no coincide pero se respeta tu elección.'
    ]} for o in diff.get('validadas_manual', [])]

    sin_cambios = [{**o, 'accion': 'sin_cambios', 'razones': [
        'Datos idénticos y Odoo ID ya vinculado.'
    ]} for o in diff.get('sin_cambios', [])]

    stats = {
        'listos': len(listos),
        'incidencias': len(incidencias),
        'omitidos_auto': len(omitidos_auto),
        'finalizadas': len(finalizadas),
        'validadas_manual': len(validadas),
        'sin_cambios': len(sin_cambios),
        'total_accion': len(listos) + len(incidencias) + len(finalizadas),
    }

    return {
        'modulo': 'obras',
        'modulo_label': 'Obras / Proyectos',
        'icon': 'fa-building',
        'stats': stats,
        'listos': listos,
        'incidencias': incidencias,
        'omitidos_auto': omitidos_auto,
        'finalizadas': finalizadas,
        'validadas_manual': validadas,
        'sin_cambios': sin_cambios,
    }


def analyze_empleados_preview(diff):
    listos = []
    incidencias = []
    omitidos_auto = []

    for emp in diff.get('nuevos', []):
        listos.append({**emp, 'accion': 'nuevo', 'razones': []})

    for emp in diff.get('actualizados', []):
        if emp.get('conflicto'):
            c = emp['conflicto']
            razones = [
                f"Conflicto de {c['tipo']} duplicado: «{c['valor']}». "
                f"Compiten {c['actual']['nombre']} (ID {c['actual']['id']}) y "
                f"{c['bloqueador']['nombre']} (ID {c['bloqueador']['id']}). "
                "En sync automática se omitirá hasta resolver el conflicto."
            ]
            entry = {**emp, 'accion': 'actualizar', 'razones': razones}
            incidencias.append(entry)
            omitidos_auto.append(entry)
        else:
            listos.append({**emp, 'accion': 'actualizar', 'razones': []})

    desactivados = [{
        **d,
        'accion': 'desactivar',
        'razones': [
            'Se desactivará en la plataforma (historial intacto) y se liberarán '
            'asignaciones futuras vía solicitud de baja automática.'
        ],
    } for d in diff.get('desactivados', [])]

    omitidos_odoo = [{**o, 'accion': 'omitido_odoo'} for o in diff.get('omitidos', [])]

    sin_cambios = [{**e, 'accion': 'sin_cambios', 'razones': [
        'Empleado ya sincronizado; sin cambios detectados.'
    ]} for e in diff.get('sin_cambios', [])]

    stats = {
        'listos': len(listos),
        'incidencias': len(incidencias),
        'omitidos_auto': len(omitidos_auto),
        'omitidos_odoo': len(omitidos_odoo),
        'desactivados': len(desactivados),
        'sin_cambios': len(sin_cambios),
        'total_accion': len(listos) + len(incidencias) + len(desactivados),
    }

    return {
        'modulo': 'empleados',
        'modulo_label': 'Personal interno',
        'icon': 'fa-users',
        'stats': stats,
        'listos': listos,
        'incidencias': incidencias,
        'omitidos_auto': omitidos_auto,
        'omitidos_odoo': omitidos_odoo,
        'desactivados': desactivados,
        'sin_cambios': sin_cambios,
    }


def analyze_subcontratas_preview(diff):
    listos_empresas = []
    incidencias_empresas = []
    for emp in diff.get('empresas', {}).get('nuevas', []):
        listos_empresas.append({**emp, 'accion': 'nueva_empresa', 'razones': []})
    for emp in diff.get('empresas', {}).get('actualizadas', []):
        listos_empresas.append({**emp, 'accion': 'actualizar_empresa', 'razones': []})

    rellenar_cif = list(diff.get('empresas', {}).get('rellenar_cif') or [])
    sin_cambios_empresas = [{
        **emp, 'accion': 'sin_cambios', 'razones': [],
    } for emp in diff.get('empresas', {}).get('sin_cambios', [])]

    listos_empleados = []
    incidencias_empleados = []
    omitidos_auto = []

    for emp in diff.get('empleados', {}).get('nuevos', []):
        choque_dni = User.query.filter_by(dni=emp['dni']).first()
        choque_email = User.query.filter_by(email=emp['email']).first()
        razones = []
        if choque_dni:
            razones.append(
                f"DNI «{emp['dni']}» ya existe ({choque_dni.name} {choque_dni.lastname}). "
                f"Al importar se reutilizará o renombrará a {emp['dni']}-EXT{emp['odoo_id']}."
            )
        if choque_email and (not choque_dni or choque_email.id != choque_dni.id):
            razones.append(
                f"Email «{emp['email']}» ya existe ({choque_email.name} {choque_email.lastname}). "
                f"Al importar se reutilizará esa ficha (no se crea duplicado)."
            )
        entry = {**emp, 'accion': 'nuevo_externo', 'razones': razones}
        if razones:
            incidencias_empleados.append(entry)
        else:
            listos_empleados.append(entry)

    for emp in diff.get('empleados', {}).get('actualizados', []):
        listos_empleados.append({**emp, 'accion': 'actualizar_externo', 'razones': []})

    desactivados = [{
        **d,
        'accion': 'desactivar',
        'razones': [
            'Se desactivará (historial intacto). Si no queda personal activo, '
            'la empresa subcontrata se archivará.'
        ],
    } for d in diff.get('empleados', {}).get('desactivados', [])]

    sin_cambios = []
    meta = diff.get('meta') or {}

    stats = {
        'listos': len(listos_empresas) + len(listos_empleados),
        'incidencias': len(incidencias_empresas) + len(incidencias_empleados),
        'omitidos_auto': len(omitidos_auto),
        'empresas_nuevas': len(diff.get('empresas', {}).get('nuevas', [])),
        'empresas_act': len(diff.get('empresas', {}).get('actualizadas', [])),
        'empresas_rellenar_cif': len(rellenar_cif),
        'empresas_sin_cambios': len(sin_cambios_empresas),
        'empresas_odoo': meta.get('empresas_odoo', 0),
        'externos_nuevos': len(diff.get('empleados', {}).get('nuevos', [])),
        'externos_act': len(diff.get('empleados', {}).get('actualizados', [])),
        'desactivados': len(desactivados),
    }

    return {
        'modulo': 'subcontratas',
        'modulo_label': 'Subcontratas y externos',
        'icon': 'fa-hard-hat',
        'stats': stats,
        'meta': meta,
        'listos_empresas': listos_empresas,
        'rellenar_cif': rellenar_cif,
        'sin_cambios_empresas': sin_cambios_empresas,
        'incidencias_empresas': incidencias_empresas,
        'listos_empleados': listos_empleados,
        'incidencias_empleados': incidencias_empleados,
        'desactivados': desactivados,
        'omitidos_auto': omitidos_auto,
        'sin_cambios': sin_cambios,
    }
