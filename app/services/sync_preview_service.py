"""Análisis de diffs Odoo para previews manuales enriquecidos."""
from app.models import User


def _empleado_import_razon(o):
    imp = (o.get('departamento_importacion') or '').strip()
    src = (o.get('import_source_label') or '').strip()
    if imp:
        txt = f"Departamento registrado al importar: «{imp}»."
        if src:
            txt += f" Origen: {src}."
        return txt
    return (
        'No consta el departamento al importar (ficha anterior a este registro). '
        'No podemos reconstruir el dpto Odoo del momento del alta sin datos guardados.'
    )


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
    omitidos_decision = []
    for o in diff.get('omitidos_decision', []):
        tipo = o.get('tipo_aviso') or 'departamento'
        import_line = _empleado_import_razon(o)
        if tipo == 'departamento':
            razones = [
                f"Ya está en la app como {o.get('local_name', '')} {o.get('local_lastname', '')}. "
                f"En Odoo figura ahora en «{o.get('departamento') or 'sin departamento'}», "
                "departamento que no está en el mapa de sync. Decide si lo autorizas.",
                import_line,
            ]
        elif tipo == 'no_encontrado':
            razones = [
                f"Ya está en la app como {o.get('local_name', '')} {o.get('local_lastname', '')}, "
                "pero su Id Odoo ya no aparece en hr.employee. Revisa el vínculo o da de baja manualmente.",
                import_line,
            ]
        elif tipo == 'sin_dni':
            razones = [
                f"Ya está en la app como {o.get('local_name', '')} {o.get('local_lastname', '')}, "
                "pero en Odoo no tiene DNI y el sync no puede actualizarlo.",
                import_line,
            ]
        else:
            razones = [
                f"Ya está en la app como {o.get('local_name', '')} {o.get('local_lastname', '')}, "
                "activo en Odoo pero fuera del filtro de sync. "
                f"Motivo: {o.get('motivo') or 'filtro'}.",
                import_line,
            ]
        omitidos_decision.append({
            **o,
            'accion': 'omitido_decision',
            'razones': razones,
        })

    sin_cambios = [{**e, 'accion': 'sin_cambios', 'razones': [
        'Empleado ya sincronizado; sin cambios detectados.'
    ]} for e in diff.get('sin_cambios', [])]

    stats = {
        'listos': len(listos),
        'incidencias': len(incidencias),
        'omitidos_auto': len(omitidos_auto),
        'omitidos_odoo': len(omitidos_odoo),
        'omitidos_decision': len(omitidos_decision),
        'desactivados': len(desactivados),
        'sin_cambios': len(sin_cambios),
        'total_accion': (
            len(listos) + len(incidencias) + len(desactivados) + len(omitidos_decision)
        ),
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
        'omitidos_decision': omitidos_decision,
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
        cambios = emp.get('cambios') or {}
        # Cambio de Id Odoo a otro no ligado = posible identidad distinta (p.ej. email empresa).
        if cambios.get('Id Odoo'):
            incidencias_empleados.append({
                **emp,
                'accion': 'actualizar_externo',
                'razones': [
                    'Cambio de Id Odoo en una ficha ya existente. Revisa antes de aplicar: '
                    'puede ser otra persona (p. ej. varios contactos con el mismo email de empresa). '
                    'Usa Conciliación personal si hay que unificar a mano.'
                ],
            })
        else:
            listos_empleados.append({**emp, 'accion': 'actualizar_externo', 'razones': []})

    desactivados = [{
        **d,
        'accion': 'desactivar',
        'razones': [
            'Se desactivará (historial intacto). Si no queda personal activo, '
            'la empresa subcontrata se archivará.'
        ],
    } for d in diff.get('empleados', {}).get('desactivados', [])]

    omitidos_decision = [{
        **o,
        'accion': 'omitido_decision',
        'razones': [
            f"Externo ya en la app ({o.get('name', '')} {o.get('lastname', '')}). "
            f"{o.get('motivo') or 'Fuera del sync de subcontratas'}. "
            "Sigue activo aquí; revisa o da de baja si corresponde."
        ],
    } for o in diff.get('empleados', {}).get('omitidos_decision', [])]

    sin_cambios = []
    meta = diff.get('meta') or {}

    stats = {
        'listos': len(listos_empresas) + len(listos_empleados),
        'incidencias': len(incidencias_empresas) + len(incidencias_empleados),
        'omitidos_auto': len(omitidos_auto),
        'omitidos_decision': len(omitidos_decision),
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
        'omitidos_decision': omitidos_decision,
        'desactivados': desactivados,
        'omitidos_auto': omitidos_auto,
        'sin_cambios': sin_cambios,
    }
