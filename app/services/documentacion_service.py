"""Catálogo, exigencias y ficheros de documentación."""
from __future__ import annotations

import json
import os
import time
import uuid
from collections import defaultdict
from datetime import date

from flask import current_app, g, has_request_context
from sqlalchemy import or_, text
from werkzeug.utils import secure_filename

from app import db
from app.models import (
    CertificacionPropuesta,
    Company,
    DocumentoAporte,
    DocumentoExigencia,
    DocumentoTipo,
    User,
)
from app.services.compliance_rules import (
    clasificar_aporte,
    es_aviso_documental,
    es_error_documental,
    sugerir_caducidad,
)
from app.utils.timezone_utils import today_local

CONFIG_AVISO_DIAS = 'documentacion_aviso_dias'
EXTENSIONES = {'.pdf', '.png', '.jpg', '.jpeg', '.webp'}
MAX_BYTES = 20 * 1024 * 1024
SLOTS_DNI = (
    '[{"codigo":"anverso","nombre":"Por delante"},'
    '{"codigo":"reverso","nombre":"Por detrás"}]'
)

# codigo, nombre, categoria, ambito, audiencia, regla, dia, mes, fase, bloquea, obligatorio, es_certificacion, orden, slots_json
# audiencia: subcontrata | interno | ambos
CATALOGO_BASE = (
    # —— Subcontratas (empresa) ——
    ('escritura_constitucion', 'Escritura de Constitución', 'Empresa', 'empresa', 'subcontrata', 'ninguna', 1, None, 0, False, True, False, 10, None),
    ('cif_empresa', 'CIF Empresa', 'Empresa', 'empresa', 'subcontrata', 'ninguna', 1, None, 0, False, True, False, 20, None),
    ('inscripcion_rea', 'Inscripción en el REA', 'Empresa', 'empresa', 'subcontrata', 'ninguna', 1, None, 0, False, True, False, 30, None),
    (
        'evaluacion_riesgos',
        'Evaluación de riesgos y Planificación preventiva de los riesgos por actividad o puesto de trabajo',
        'Empresa', 'empresa', 'subcontrata', 'ninguna', 1, None, 0, False, True, False, 40, None,
    ),
    (
        'acreditacion_prevencion',
        'Acreditación de las 4 especialidades del servicio de prevención',
        'Empresa', 'empresa', 'subcontrata', 'ninguna', 1, None, 0, False, True, False, 50, None,
    ),
    ('convenio_mutua', 'Convenio con la Mutua', 'Empresa', 'empresa', 'subcontrata', 'ninguna', 1, None, 0, False, True, False, 60, None),
    (
        'poliza_rc',
        'Póliza de Seguro de Responsabilidad Civil y recibo de pago actualizado',
        'Empresa', 'empresa', 'subcontrata', 'ninguna', 1, None, 0, False, True, False, 70, None,
    ),
    (
        'poliza_convenio',
        'Póliza del Seguro de Convenio y recibo de pago actualizado',
        'Empresa', 'empresa', 'subcontrata', 'ninguna', 1, None, 0, False, True, False, 80, None,
    ),
    (
        'poliza_vigilancia',
        'Póliza de Prevención y Vigilancia de salud y recibo del pago actualizado',
        'Empresa', 'empresa', 'subcontrata', 'ninguna', 1, None, 0, False, True, False, 90, None,
    ),
    # Mensuales empresa subcontrata
    (
        'certificado_hacienda',
        'Certificado de Hacienda de estar al corriente de pago',
        'Mensual', 'empresa', 'subcontrata', 'mensual', 1, None, 0, False, True, False, 110, None,
    ),
    (
        'certificado_ss',
        'Certificado de S.S. de estar al corriente de pago',
        'Mensual', 'empresa', 'subcontrata', 'mensual', 1, None, 0, False, True, False, 120, None,
    ),
    (
        'tc1_tc2',
        'Últimos TC1-TC2 con sello de pago o recibo bancario de pago',
        'Mensual', 'empresa', 'subcontrata', 'mensual', 1, None, 0, False, True, False, 130, None,
    ),
    (
        'certificado_salarios',
        'Certificado de pago salarios de los trabajadores',
        'Mensual', 'empresa', 'subcontrata', 'mensual', 1, None, 0, False, True, False, 140, None,
    ),
    ('ita', 'ITA', 'Mensual', 'empresa', 'subcontrata', 'mensual', 1, None, 0, False, True, False, 150, None),
    (
        'listado_trabajadores',
        'Listado de los trabajadores que han estado en la obra (informes de certificación de horario)',
        'Mensual', 'empresa', 'subcontrata', 'mensual', 1, None, 0, False, True, True, 160, None,
    ),
    # —— Empleados externos (subcontrata) ——
    (
        'prl_6h',
        'Curso 6h inicial PRL de oficio (o, en su caso, el de 20h)',
        'PRL convenio', 'empleado', 'subcontrata', 'ninguna', 1, None, 0, False, True, False, 300, None,
    ),
    (
        'prl_20h',
        'Curso 20h inicial PRL de oficio (reciclaje si tiene más de 4 años)',
        'PRL convenio', 'empleado', 'subcontrata', 'ninguna', 1, None, 0, False, True, False, 310, None,
    ),
    (
        'prl_60h',
        'Curso 60h PRL (para ser recurso preventivo en la obra)',
        'PRL convenio', 'empleado', 'subcontrata', 'ninguna', 1, None, 0, False, False, False, 320, None,
    ),
    ('curso_alturas', 'Curso de trabajos en altura', 'PRL', 'empleado', 'subcontrata', 'ninguna', 1, None, 0, False, True, False, 330, None),
    (
        'curso_pemp',
        'Curso de plataformas elevadoras',
        'PRL', 'empleado', 'subcontrata', 'ninguna', 1, None, 0, False, True, False, 340, None,
    ),
    ('art_19', 'Formación Art. 19', 'PRL', 'empleado', 'subcontrata', 'ninguna', 1, None, 0, False, True, False, 360, None),
    (
        'art_18',
        'Formación e información de PRL de su puesto de trabajo. Art. 18',
        'PRL', 'empleado', 'subcontrata', 'ninguna', 1, None, 0, False, True, False, 350, None,
    ),
    ('entrega_epis', 'Documento entrega de EPIs', 'Laboral', 'empleado', 'subcontrata', 'ninguna', 1, None, 0, False, True, False, 400, None),
    (
        'autorizacion_maquinaria',
        'Autorización uso de maquinaria',
        'Laboral', 'empleado', 'subcontrata', 'ninguna', 1, None, 0, False, True, False, 410, None,
    ),
    (
        'reconocimiento_medico',
        'Reconocimiento Médico apto',
        'Laboral', 'empleado', 'subcontrata', 'ninguna', 1, None, 0, False, True, False, 420, None,
    ),
    ('alta_ta2_idc', 'Alta (TA2) y IDC', 'Laboral', 'empleado', 'subcontrata', 'ninguna', 1, None, 0, False, True, False, 430, None),
    ('dni', 'Fotocopia DNI', 'Identidad', 'empleado', 'subcontrata', 'ninguna', 1, None, 0, False, True, False, 200, SLOTS_DNI),
    (
        'contrato_sepe',
        'Contrato de trabajo y comunicación del SEPE',
        'Laboral', 'empleado', 'subcontrata', 'ninguna', 1, None, 0, False, True, False, 440, None,
    ),
    # —— Empleado interno: pack por defecto = contratación fase 1 ——
    # (talla, cuenta, mail y teléfono van en el formulario de perfil, no aquí)
    (
        'dni_interno',
        'DNI/NIE por delante y por detrás',
        'Identidad', 'empleado', 'interno', 'ninguna', 1, None, 1, True, True, False, 210, SLOTS_DNI,
    ),
    (
        'sip_ss',
        'Número de la Seguridad Social (foto SIP trasera)',
        'Identidad', 'empleado', 'interno', 'ninguna', 1, None, 1, True, True, False, 220, None,
    ),
    (
        'carnet_conducir',
        'Foto carnet de conducir',
        'Identidad', 'empleado', 'interno', 'ninguna', 1, None, 1, False, True, False, 230, None,
    ),
    (
        'curso_pemp_interno',
        'Curso PEMP (plataformas elevadoras)',
        'PRL', 'empleado', 'interno', 'ninguna', 1, None, 1, False, True, False, 240, None,
    ),
    (
        'curso_alturas_interno',
        'Curso de trabajos en altura',
        'PRL', 'empleado', 'interno', 'ninguna', 1, None, 1, False, True, False, 250, None,
    ),
    (
        'prl_20h_interno',
        'Curso específico PRL 20h',
        'PRL', 'empleado', 'interno', 'ninguna', 1, None, 1, False, True, False, 260, None,
    ),
    (
        'prl_6h_interno',
        'Curso específico PRL 6h',
        'PRL', 'empleado', 'interno', 'ninguna', 1, None, 1, False, True, False, 270, None,
    ),
    (
        'prl_60h_interno',
        'Curso PRL 60h (si lo tuviera)',
        'PRL', 'empleado', 'interno', 'ninguna', 1, None, 1, False, False, False, 280, None,
    ),
    # —— Contratación fase 2 (marca fecha de inicio) ——
    (
        'art_19_interno',
        'Formación Art. 19',
        'PRL', 'empleado', 'interno', 'ninguna', 1, None, 2, True, True, False, 361, None,
    ),
    (
        'reconocimiento_medico_interno',
        'Reconocimiento médico apto',
        'Laboral', 'empleado', 'interno', 'ninguna', 1, None, 2, True, True, False, 421, None,
    ),
)


def slots_de(tipo) -> list[dict]:
    raw = getattr(tipo, 'slots_json', None) or ''
    if not str(raw).strip():
        return []
    try:
        data = json.loads(raw)
    except Exception:
        return []
    out = []
    for item in data or []:
        if not isinstance(item, dict) or not item.get('codigo'):
            continue
        out.append({
            'codigo': str(item['codigo']).strip(),
            'nombre': str(item.get('nombre') or item['codigo']).strip(),
        })
    return out


def _slot_key(slot) -> str:
    return (slot or '').strip()


def _meter_aporte(bucket: dict, aporte: DocumentoAporte) -> None:
    bucket.setdefault(_slot_key(getattr(aporte, 'slot', None)), aporte)


def _bucket_aporte(pack, *, user_id=None, company_id=None, tipo_id: int) -> dict:
    if user_id:
        return pack.aporte_user.setdefault((user_id, tipo_id), {})
    return pack.aporte_empresa.setdefault((company_id, tipo_id), {})


def _aporte_unico(bucket: dict):
    if not bucket:
        return None
    if '' in bucket:
        return bucket['']
    if len(bucket) == 1:
        return next(iter(bucket.values()))
    return None


def clasificar_slots(slots: list[dict], bucket: dict, *, obligatorio: bool, hoy: date, aviso_dias: int) -> str:
    if not slots:
        return clasificar_aporte(
            _aporte_unico(bucket),
            obligatorio=obligatorio,
            hoy=hoy,
            aviso_dias=aviso_dias,
        )
    legacy = bucket.get('')
    estados = []
    for idx, slot in enumerate(slots):
        aporte = bucket.get(slot['codigo'])
        # Fichero antiguo sin cara: cuenta como la primera.
        if aporte is None and legacy is not None and idx == 0:
            aporte = legacy
        estados.append(clasificar_aporte(
            aporte,
            obligatorio=obligatorio,
            hoy=hoy,
            aviso_dias=aviso_dias,
        ))
    for codigo in ('rechazado', 'caducado', 'falta', 'pendiente_validar', 'por_caducar'):
        if codigo in estados:
            return codigo
    if all(e == 'ok' for e in estados):
        return 'ok'
    if all(e == 'opcional_vacio' for e in estados):
        return 'opcional_vacio'
    return 'falta' if obligatorio else 'opcional_vacio'


def aviso_dias() -> int:
    if has_request_context() and getattr(g, '_aviso_dias', None) is not None:
        return g._aviso_dias
    from app.services.config_service import get_tenant_config
    raw = get_tenant_config(CONFIG_AVISO_DIAS, default='15')
    try:
        dias = max(0, int(raw))
    except (TypeError, ValueError):
        dias = 15
    if has_request_context():
        g._aviso_dias = dias
    return dias


def guardar_aviso_dias(dias: int) -> None:
    from app.services.config_service import set_tenant_config
    set_tenant_config(CONFIG_AVISO_DIAS, str(max(0, int(dias))))


def asegurar_catalogo() -> None:
    if has_request_context() and getattr(g, '_catalogo_asegurado', False):
        return
    try:
        from sqlalchemy import inspect as sa_inspect
        schema = db.session.execute(text('SELECT current_schema()')).scalar()
        cols = {
            c['name']
            for c in sa_inspect(db.engine).get_columns('documento_tipos', schema=schema)
        }
        tiene_slots = 'slots_json' in cols
        if 'por_defecto' not in cols:
            db.session.execute(text(
                'ALTER TABLE documento_tipos ADD COLUMN '
                'por_defecto BOOLEAN NOT NULL DEFAULT true'
            ))
            db.session.execute(text(
                'UPDATE documento_tipos SET por_defecto = activo'
            ))
            db.session.commit()
            cols.add('por_defecto')
        if 'created_at' not in cols:
            db.session.execute(text(
                'ALTER TABLE documento_tipos ADD COLUMN created_at TIMESTAMP NULL'
            ))
            db.session.commit()
            cols.add('created_at')
    except Exception:
        tiene_slots = False

    existentes = {
        t.codigo: t
        for t in DocumentoTipo.query.filter(DocumentoTipo.codigo.isnot(None)).all()
    }
    changed = False
    if tiene_slots:
        changed = _unificar_plantilla_dni(existentes)
        existentes = {
            t.codigo: t
            for t in DocumentoTipo.query.filter(DocumentoTipo.codigo.isnot(None)).all()
        }
    for row in CATALOGO_BASE:
        codigo = row[0]
        if codigo in existentes:
            if _sincronizar_tipo_catalogo(existentes[codigo], row, tiene_slots=tiene_slots):
                changed = True
            continue
        kwargs = dict(
            codigo=codigo,
            nombre=row[1],
            categoria=row[2],
            ambito=row[3],
            audiencia=row[4],
            regla_renovacion=row[5],
            dia_renovacion=row[6],
            mes_renovacion=row[7],
            fase_contratacion=row[8],
            bloquea_fase=row[9],
            obligatorio=row[10],
            es_certificacion=row[11],
            orden=row[12],
            es_sistema=True,
            activo=True,
            por_defecto=True,
        )
        if tiene_slots and len(row) > 13:
            kwargs['slots_json'] = row[13]
        db.session.add(DocumentoTipo(**kwargs))
        changed = True
    if changed:
        db.session.flush()
        existentes = {
            t.codigo: t
            for t in DocumentoTipo.query.filter(DocumentoTipo.codigo.isnot(None)).all()
        }
    # Aportes de internos que estaban en plantillas ahora solo-externas → variantes internas
    if _reasignar_aportes_internos('dni', 'dni_interno'):
        changed = True
    if _reasignar_aportes_internos('art_19', 'art_19_interno'):
        changed = True
    if _reasignar_aportes_internos('reconocimiento_medico', 'reconocimiento_medico_interno'):
        changed = True
    if changed:
        db.session.commit()
    if has_request_context():
        g._catalogo_asegurado = True


def _sincronizar_tipo_catalogo(tipo: DocumentoTipo, row: tuple, *, tiene_slots: bool) -> bool:
    """Alinea plantillas de sistema con CATALOGO_BASE (nombres, audiencia, fases…)."""
    changed = False
    mapping = (
        ('nombre', 1),
        ('categoria', 2),
        ('ambito', 3),
        ('audiencia', 4),
        ('regla_renovacion', 5),
        ('dia_renovacion', 6),
        ('mes_renovacion', 7),
        ('fase_contratacion', 8),
        ('bloquea_fase', 9),
        ('obligatorio', 10),
        ('es_certificacion', 11),
        ('orden', 12),
    )
    for attr, idx in mapping:
        val = row[idx]
        if getattr(tipo, attr) != val:
            setattr(tipo, attr, val)
            changed = True
    if not tipo.es_sistema:
        tipo.es_sistema = True
        changed = True
    if tiene_slots and len(row) > 13 and row[13]:
        if not (tipo.slots_json or '').strip():
            tipo.slots_json = row[13]
            changed = True
    return changed


def _usuario_es_interno_para_docs(user: User | None) -> bool:
    if user is None:
        return False
    company = getattr(user, 'company_rel', None) or (
        Company.query.get(user.company_id) if user.company_id else None
    )
    return company is None or bool(company.is_internal)


def _reasignar_aportes_internos(codigo_origen: str, codigo_destino: str) -> bool:
    """Mueve aportes de empleados internos a la plantilla interna gemela."""
    origen = DocumentoTipo.query.filter_by(codigo=codigo_origen).first()
    destino = DocumentoTipo.query.filter_by(codigo=codigo_destino).first()
    if not origen or not destino or origen.id == destino.id:
        return False
    changed = False
    aportes = DocumentoAporte.query.filter(
        DocumentoAporte.tipo_id == origen.id,
        DocumentoAporte.user_id.isnot(None),
    ).all()
    for aporte in aportes:
        user = User.query.get(aporte.user_id)
        if not _usuario_es_interno_para_docs(user):
            continue
        slot = (aporte.slot or '') or None
        existe = DocumentoAporte.query.filter_by(
            user_id=aporte.user_id,
            tipo_id=destino.id,
            slot=slot,
        ).first()
        if existe:
            continue
        aporte.tipo_id = destino.id
        changed = True
    return changed


def _unificar_plantilla_dni(existentes: dict) -> bool:
    """Pasa DNI anverso/reverso a una sola plantilla con dos huecos y borra legacies."""
    changed = False
    for codigo_canonico in ('dni', 'dni_interno'):
        canon = existentes.get(codigo_canonico)
        if not canon:
            continue
        if not (canon.slots_json or '').strip():
            canon.slots_json = SLOTS_DNI
            if codigo_canonico == 'dni_interno':
                canon.nombre = canon.nombre or 'DNI/NIE por delante y por detrás'
            else:
                canon.nombre = canon.nombre or 'DNI/NIE'
            changed = True
        elif codigo_canonico == 'dni_interno' and 'delante' not in (canon.nombre or '').lower():
            # Nombre antiguo monolítico → el de dos caras
            if (canon.nombre or '').strip() in ('DNI/NIE', 'Fotocopia DNI', 'DNI'):
                canon.nombre = 'DNI/NIE por delante y por detrás'
                changed = True

    anverso = existentes.get('dni_anverso')
    reverso = existentes.get('dni_reverso') or existentes.get('dni_reverso_legacy')
    dni = existentes.get('dni')
    if anverso and not dni:
        anverso.codigo = 'dni'
        anverso.nombre = 'Fotocopia DNI'
        anverso.slots_json = SLOTS_DNI
        anverso.activo = True
        for aporte in DocumentoAporte.query.filter_by(tipo_id=anverso.id).all():
            if not aporte.slot:
                aporte.slot = 'anverso'
        dni = anverso
        existentes['dni'] = anverso
        existentes.pop('dni_anverso', None)
        changed = True
    elif dni and not (dni.slots_json or '').strip():
        dni.slots_json = SLOTS_DNI
        dni.nombre = dni.nombre or 'Fotocopia DNI'
        changed = True

    destino_reverso = dni or existentes.get('dni_interno')
    if reverso and destino_reverso and reverso.id != destino_reverso.id:
        for aporte in DocumentoAporte.query.filter_by(tipo_id=reverso.id).all():
            aporte.tipo_id = destino_reverso.id
            aporte.slot = aporte.slot or 'reverso'
        for exigencia in DocumentoExigencia.query.filter_by(tipo_id=reverso.id).all():
            exigencia.tipo_id = destino_reverso.id
        db.session.delete(reverso)
        for key in ('dni_reverso', 'dni_reverso_legacy'):
            existentes.pop(key, None)
        changed = True
    elif reverso and not destino_reverso:
        reverso.activo = False
        reverso.codigo = 'dni_reverso_legacy'
        changed = True

    # Anverso suelto si ya existe dni canónico
    if anverso and dni and anverso.id != dni.id:
        for aporte in DocumentoAporte.query.filter_by(tipo_id=anverso.id).all():
            aporte.tipo_id = dni.id
            aporte.slot = aporte.slot or 'anverso'
        for exigencia in DocumentoExigencia.query.filter_by(tipo_id=anverso.id).all():
            exigencia.tipo_id = dni.id
        db.session.delete(anverso)
        existentes.pop('dni_anverso', None)
        changed = True

    # Basura legacy inactiva
    for codigo in list(existentes.keys()):
        if not str(codigo).endswith('_legacy') and codigo not in (
            'dni_anverso', 'dni_reverso', 'dni_reverso_legacy', 'dni_anverso_legacy',
        ):
            continue
        tipo = existentes.get(codigo)
        if not tipo:
            continue
        destino = existentes.get('dni_interno') if getattr(tipo, 'audiencia', None) == 'interno' else existentes.get('dni')
        destino = destino or existentes.get('dni') or existentes.get('dni_interno')
        if destino and tipo.id != destino.id:
            for aporte in DocumentoAporte.query.filter_by(tipo_id=tipo.id).all():
                aporte.tipo_id = destino.id
                if not aporte.slot:
                    aporte.slot = 'reverso' if 'reverso' in codigo else 'anverso'
            for exigencia in DocumentoExigencia.query.filter_by(tipo_id=tipo.id).all():
                exigencia.tipo_id = destino.id
        db.session.delete(tipo)
        existentes.pop(codigo, None)
        changed = True

    # Restos inactivos sueltos (sin código o nombre de cara única) tras unificar slots
    canon_ids = {
        t.id for t in (existentes.get('dni'), existentes.get('dni_interno')) if t
    }
    if canon_ids:
        for tipo in DocumentoTipo.query.filter(
            DocumentoTipo.ambito == 'empleado',
            DocumentoTipo.activo.is_(False),
        ).all():
            if tipo.id in canon_ids:
                continue
            nombre = (tipo.nombre or '').strip().lower()
            codigo = (tipo.codigo or '')
            es_resto = (
                codigo in ('dni_anverso', 'dni_reverso', 'dni_reverso_legacy', 'dni_anverso_legacy')
                or codigo.endswith('_legacy')
                or 'reverso' in nombre
                or 'por detrás' in nombre
                or 'por detras' in nombre
                or nombre in ('dni por delante', 'fotocopia dni anverso', 'fotocopia dni reverso')
            )
            if not es_resto:
                continue
            destino = existentes.get('dni_interno') if tipo.audiencia == 'interno' else existentes.get('dni')
            destino = destino or existentes.get('dni') or existentes.get('dni_interno')
            if destino:
                for aporte in DocumentoAporte.query.filter_by(tipo_id=tipo.id).all():
                    aporte.tipo_id = destino.id
                    if not aporte.slot:
                        aporte.slot = 'reverso' if ('reverso' in nombre or 'detrás' in nombre or 'detras' in nombre) else 'anverso'
                for exigencia in DocumentoExigencia.query.filter_by(tipo_id=tipo.id).all():
                    exigencia.tipo_id = destino.id
            db.session.delete(tipo)
            if tipo.codigo:
                existentes.pop(tipo.codigo, None)
            changed = True
    return changed


def _audiencias(company_or_user_interno: bool) -> tuple[str, ...]:
    if company_or_user_interno:
        return ('interno', 'ambos')
    return ('subcontrata', 'ambos')


def _empresa_es_interna(company: Company | None) -> bool:
    return bool(company and company.is_internal)


def tipos_empresa(company: Company) -> list[DocumentoTipo]:
    asegurar_catalogo()
    base = DocumentoTipo.query.filter(
        DocumentoTipo.activo.is_(True),
        DocumentoTipo.por_defecto.is_(True),
        DocumentoTipo.ambito == 'empresa',
        DocumentoTipo.audiencia.in_(_audiencias(_empresa_es_interna(company))),
    ).all()
    exclusiones = {
        e.tipo_id for e in DocumentoExigencia.query.filter_by(
            company_id=company.id, destino='empresa', modo='excluir',
        ).all()
    }
    extras_ids = [
        e.tipo_id for e in DocumentoExigencia.query.filter_by(
            company_id=company.id, destino='empresa', modo='anadir',
        ).all()
    ]
    extras = DocumentoTipo.query.filter(
        DocumentoTipo.id.in_(extras_ids), DocumentoTipo.activo.is_(True),
    ).all() if extras_ids else []
    vistos = set()
    out = []
    for tipo in list(base) + list(extras):
        if tipo.id in vistos or tipo.id in exclusiones:
            continue
        if tipo.ambito != 'empresa':
            continue
        vistos.add(tipo.id)
        out.append(tipo)
    out.sort(key=lambda t: (t.orden or 0, t.nombre or ''))
    return out


def tipos_persona(user: User) -> list[DocumentoTipo]:
    asegurar_catalogo()
    company = user.company_rel
    interno = _empresa_es_interna(company) or company is None
    base = DocumentoTipo.query.filter(
        DocumentoTipo.activo.is_(True),
        DocumentoTipo.por_defecto.is_(True),
        DocumentoTipo.ambito == 'empleado',
        DocumentoTipo.audiencia.in_(_audiencias(interno)),
    ).all()
    exclusiones = set()
    extras_ids = []
    if user.company_id:
        exclusiones = {
            e.tipo_id for e in DocumentoExigencia.query.filter_by(
                company_id=user.company_id, destino='empleados', modo='excluir',
            ).all()
        }
        extras_ids.extend(
            e.tipo_id for e in DocumentoExigencia.query.filter_by(
                company_id=user.company_id, destino='empleados', modo='anadir',
            ).all()
        )
    exclusiones |= {
        e.tipo_id for e in DocumentoExigencia.query.filter_by(
            user_id=user.id, destino='persona', modo='excluir',
        ).all()
    }
    extras_ids.extend(
        e.tipo_id for e in DocumentoExigencia.query.filter_by(
            user_id=user.id, destino='persona', modo='anadir',
        ).all()
    )
    extras = DocumentoTipo.query.filter(
        DocumentoTipo.id.in_(extras_ids), DocumentoTipo.activo.is_(True),
    ).all() if extras_ids else []
    vistos = set()
    out = []
    for tipo in list(base) + list(extras):
        if tipo.id in vistos or tipo.id in exclusiones:
            continue
        vistos.add(tipo.id)
        out.append(tipo)
    out.sort(key=lambda t: (t.orden or 0, t.nombre or ''))
    return out


def tipos_plantilla_empleados_empresa(company: Company) -> list[DocumentoTipo]:
    """Exigencias de empleado que esta subcontrata añade o hereda, sin una persona concreta."""
    asegurar_catalogo()
    base = DocumentoTipo.query.filter(
        DocumentoTipo.activo.is_(True),
        DocumentoTipo.por_defecto.is_(True),
        DocumentoTipo.ambito == 'empleado',
        DocumentoTipo.audiencia.in_(_audiencias(company.is_internal)),
    ).all()
    exclusiones = {
        e.tipo_id for e in DocumentoExigencia.query.filter_by(
            company_id=company.id, destino='empleados', modo='excluir',
        ).all()
    }
    extras_ids = [
        e.tipo_id for e in DocumentoExigencia.query.filter_by(
            company_id=company.id, destino='empleados', modo='anadir',
        ).all()
    ]
    extras = DocumentoTipo.query.filter(
        DocumentoTipo.id.in_(extras_ids), DocumentoTipo.activo.is_(True),
    ).all() if extras_ids else []
    vistos = set()
    out = []
    for tipo in list(base) + list(extras):
        if tipo.id in vistos or tipo.id in exclusiones:
            continue
        vistos.add(tipo.id)
        out.append(tipo)
    out.sort(key=lambda t: (t.orden or 0, t.nombre or ''))
    return out


def aporte_vigente(tipo_id: int, *, company_id=None, user_id=None, slot=None) -> DocumentoAporte | None:
    q = DocumentoAporte.query.filter_by(tipo_id=tipo_id, vigente=True)
    if user_id:
        q = q.filter_by(user_id=user_id)
    else:
        q = q.filter(DocumentoAporte.user_id.is_(None), DocumentoAporte.company_id == company_id)
    slot_key = _slot_key(slot)
    if slot_key:
        q = q.filter(DocumentoAporte.slot == slot_key)
    else:
        q = q.filter(or_(DocumentoAporte.slot.is_(None), DocumentoAporte.slot == ''))
    return q.order_by(DocumentoAporte.id.desc()).first()


def _certificacion_ok(company_id: int, hoy: date) -> bool:
    mes = hoy.month - 1 or 12
    anio = hoy.year if hoy.month > 1 else hoy.year - 1
    row = CertificacionPropuesta.query.filter_by(
        company_id=company_id, anio=anio, mes=mes, estado='aceptada',
    ).first()
    return row is not None


def _estado_tipo(tipo: DocumentoTipo, bucket: dict, *, company_id, hoy, dias) -> str:
    if tipo.es_certificacion and company_id:
        return clasificar_aporte(
            None,
            obligatorio=bool(tipo.obligatorio),
            hoy=hoy,
            aviso_dias=dias,
            es_certificacion=True,
            cert_ok=_certificacion_ok(company_id, hoy),
        )
    return clasificar_slots(
        slots_de(tipo),
        bucket,
        obligatorio=bool(tipo.obligatorio),
        hoy=hoy,
        aviso_dias=dias,
    )


class _DocPack:
    """Datos de documentación ya leídos en esta petición, para no repetir consultas."""

    def __init__(self):
        self.tipos = []
        self.tipos_por_id = {}
        self.tipos_listos = False
        self.dias = 15
        self.todo = False
        self.empresas_completas = set()
        self.company_exigencias = set()
        self.aporte_empresa_leido = set()
        self.cert_periodo = None
        self.cert_ok = set()
        self.cert_companies = set()
        self.user_ids = set()
        self.companies = {}
        self.users_by_company = defaultdict(list)
        self.excluir_empresa = defaultdict(set)
        self.anadir_empresa = defaultdict(set)
        self.excluir_empleados = defaultdict(set)
        self.anadir_empleados = defaultdict(set)
        self.anadir_persona = defaultdict(set)
        self.excluir_persona = defaultdict(set)
        self.aporte_empresa = {}
        self.aporte_user = {}


def _pack_request() -> _DocPack:
    if not has_request_context():
        return _DocPack()
    pack = getattr(g, '_doc_pack', None)
    if pack is None:
        pack = _DocPack()
        g._doc_pack = pack
    return pack


def _periodo_cert(hoy: date) -> tuple[int, int]:
    mes = hoy.month - 1 or 12
    anio = hoy.year if hoy.month > 1 else hoy.year - 1
    return anio, mes


def _absorber_exigencia(pack: _DocPack, row: DocumentoExigencia) -> None:
    if row.modo == 'excluir' and row.destino == 'empresa' and row.company_id:
        pack.excluir_empresa[row.company_id].add(row.tipo_id)
    elif row.modo == 'anadir' and row.destino == 'empresa' and row.company_id:
        pack.anadir_empresa[row.company_id].add(row.tipo_id)
    elif row.modo == 'excluir' and row.destino == 'empleados' and row.company_id:
        pack.excluir_empleados[row.company_id].add(row.tipo_id)
    elif row.modo == 'anadir' and row.destino == 'empleados' and row.company_id:
        pack.anadir_empleados[row.company_id].add(row.tipo_id)
    elif row.modo == 'anadir' and row.destino == 'persona' and row.user_id:
        pack.anadir_persona[row.user_id].add(row.tipo_id)
    elif row.modo == 'excluir' and row.destino == 'persona' and row.user_id:
        pack.excluir_persona[row.user_id].add(row.tipo_id)


def _asegurar_tipos(pack: _DocPack) -> None:
    if pack.tipos_listos:
        return
    asegurar_catalogo()
    pack.tipos = DocumentoTipo.query.filter_by(activo=True).all()
    pack.tipos_por_id = {t.id: t for t in pack.tipos}
    pack.dias = aviso_dias()
    pack.tipos_listos = True


def _marcar_cert(pack: _DocPack, company_ids, hoy: date) -> None:
    periodo = _periodo_cert(hoy)
    if pack.cert_periodo != periodo:
        pack.cert_periodo = periodo
        pack.cert_ok = set()
        pack.cert_companies = set()
    missing = [cid for cid in company_ids if cid and cid not in pack.cert_companies]
    if not missing:
        return
    anio, mes = periodo
    rows = CertificacionPropuesta.query.filter(
        CertificacionPropuesta.company_id.in_(missing),
        CertificacionPropuesta.anio == anio,
        CertificacionPropuesta.mes == mes,
        CertificacionPropuesta.estado == 'aceptada',
    ).with_entities(CertificacionPropuesta.company_id).all()
    pack.cert_ok.update(row[0] for row in rows)
    pack.cert_companies.update(missing)


def _juntar_tipos(pack, *, ambito, audiencias, exclusiones, extras_ids, solo_ambito: bool):
    extras = []
    for tid in extras_ids:
        tipo = pack.tipos_por_id.get(tid)
        if tipo is not None and tipo.activo:
            extras.append(tipo)
    base = [
        t for t in pack.tipos
        if t.ambito == ambito
        and t.audiencia in audiencias
        and getattr(t, 'por_defecto', True)
    ]
    vistos = set()
    out = []
    for tipo in base + extras:
        if tipo.id in vistos or tipo.id in exclusiones:
            continue
        if solo_ambito and tipo.ambito != ambito:
            continue
        vistos.add(tipo.id)
        out.append(tipo)
    out.sort(key=lambda t: (t.orden or 0, t.nombre or ''))
    return out


def _interno_de(pack: _DocPack, user: User) -> bool:
    if not user.company_id:
        return True
    company = pack.companies.get(user.company_id)
    if company is None:
        company = user.company_rel
        if company is not None:
            pack.companies[company.id] = company
    return _empresa_es_interna(company) or company is None


def _estado_pack(pack: _DocPack, tipo, bucket: dict, company_id, hoy: date) -> str:
    if tipo.es_certificacion and company_id:
        if pack.cert_periodo == _periodo_cert(hoy) and company_id in pack.cert_companies:
            cert_ok = company_id in pack.cert_ok
        else:
            cert_ok = _certificacion_ok(company_id, hoy)
        return clasificar_aporte(
            None,
            obligatorio=bool(tipo.obligatorio),
            hoy=hoy,
            aviso_dias=pack.dias,
            es_certificacion=True,
            cert_ok=cert_ok,
        )
    return clasificar_slots(
        slots_de(tipo),
        bucket,
        obligatorio=bool(tipo.obligatorio),
        hoy=hoy,
        aviso_dias=pack.dias,
    )


def _fila(pack, tipo, bucket: dict, company_id, hoy, origen) -> dict:
    slots = slots_de(tipo)
    legacy = bucket.get('')
    slot_filas = []
    for idx, slot in enumerate(slots):
        aporte = bucket.get(slot['codigo'])
        if aporte is None and legacy is not None and idx == 0:
            aporte = legacy
        slot_filas.append({
            'codigo': slot['codigo'],
            'nombre': slot['nombre'],
            'aporte': aporte,
        })
    aporte = None if slots else _aporte_unico(bucket)
    return {
        'tipo': tipo,
        'aporte': aporte,
        'slots': slot_filas,
        'estado': _estado_pack(pack, tipo, bucket, company_id, hoy),
        'origen': origen,
        'caducidad_sugerida': sugerir_caducidad(
            tipo.regla_renovacion, tipo.dia_renovacion, tipo.mes_renovacion, hoy,
        ),
    }


def _tipos_empresa_pack(pack: _DocPack, company: Company):
    return _juntar_tipos(
        pack,
        ambito='empresa',
        audiencias=_audiencias(_empresa_es_interna(company)),
        exclusiones=pack.excluir_empresa.get(company.id, set()),
        extras_ids=pack.anadir_empresa.get(company.id, set()),
        solo_ambito=True,
    )


def _tipos_persona_pack(pack: _DocPack, user: User):
    extras = set(pack.anadir_empleados.get(user.company_id, set())) if user.company_id else set()
    extras |= pack.anadir_persona.get(user.id, set())
    exclusiones = set(pack.excluir_empleados.get(user.company_id, set())) if user.company_id else set()
    exclusiones |= pack.excluir_persona.get(user.id, set())
    return _juntar_tipos(
        pack,
        ambito='empleado',
        audiencias=_audiencias(_interno_de(pack, user)),
        exclusiones=exclusiones,
        extras_ids=extras,
        solo_ambito=False,
    )


def _leer_aportes_empresa(pack: _DocPack, company_id: int) -> None:
    if company_id in pack.aporte_empresa_leido:
        return
    rows = DocumentoAporte.query.filter(
        DocumentoAporte.vigente.is_(True),
        DocumentoAporte.user_id.is_(None),
        DocumentoAporte.company_id == company_id,
    ).order_by(DocumentoAporte.id.desc()).all()
    for aporte in rows:
        bucket = pack.aporte_empresa.setdefault((company_id, aporte.tipo_id), {})
        _meter_aporte(bucket, aporte)
    pack.aporte_empresa_leido.add(company_id)


def _leer_aportes_usuarios(pack: _DocPack, user_ids) -> None:
    if not user_ids:
        return
    rows = DocumentoAporte.query.filter(
        DocumentoAporte.vigente.is_(True),
        DocumentoAporte.user_id.in_(user_ids),
    ).order_by(DocumentoAporte.id.desc()).all()
    for aporte in rows:
        bucket = pack.aporte_user.setdefault((aporte.user_id, aporte.tipo_id), {})
        _meter_aporte(bucket, aporte)


def _leer_exigencias_empresa(pack: _DocPack, company_id: int) -> None:
    if company_id in pack.company_exigencias:
        return
    for row in DocumentoExigencia.query.filter_by(company_id=company_id).all():
        _absorber_exigencia(pack, row)
    pack.company_exigencias.add(company_id)


def _llenar_empresa(pack: _DocPack, company: Company, hoy: date) -> None:
    _asegurar_tipos(pack)
    if company.id in pack.empresas_completas:
        return
    pack.companies[company.id] = company
    usuarios = User.query.filter_by(company_id=company.id, is_deleted=False).all()
    nuevos = []
    for user in usuarios:
        if user.id in pack.user_ids:
            continue
        pack.user_ids.add(user.id)
        pack.users_by_company[company.id].append(user)
        nuevos.append(user.id)
    _leer_exigencias_empresa(pack, company.id)
    if nuevos:
        for row in DocumentoExigencia.query.filter(
            DocumentoExigencia.user_id.in_(nuevos),
            DocumentoExigencia.destino == 'persona',
        ).all():
            _absorber_exigencia(pack, row)
        _leer_aportes_usuarios(pack, nuevos)
    _leer_aportes_empresa(pack, company.id)
    _marcar_cert(pack, [company.id], hoy)
    pack.empresas_completas.add(company.id)


def _llenar_persona(pack: _DocPack, user: User, hoy: date) -> None:
    _asegurar_tipos(pack)
    if user.id in pack.user_ids and (not user.company_id or user.company_id in pack.company_exigencias):
        return
    if user.company_id:
        _leer_exigencias_empresa(pack, user.company_id)
        _marcar_cert(pack, [user.company_id], hoy)
    if user.id not in pack.user_ids:
        pack.user_ids.add(user.id)
        pack.users_by_company[user.company_id].append(user)
        for row in DocumentoExigencia.query.filter_by(user_id=user.id, destino='persona').all():
            _absorber_exigencia(pack, row)
        _leer_aportes_usuarios(pack, [user.id])


def _llenar_todo(pack: _DocPack, hoy: date) -> None:
    if pack.todo:
        return
    _asegurar_tipos(pack)
    companies = Company.query.filter_by(active=True).order_by(Company.nombre).all()
    ids = [c.id for c in companies]
    for company in companies:
        pack.companies[company.id] = company
    usuarios = User.query.filter(
        User.is_deleted.is_(False),
        User.company_id.in_(ids),
    ).all() if ids else []
    for user in usuarios:
        if user.id in pack.user_ids:
            continue
        pack.user_ids.add(user.id)
        pack.users_by_company[user.company_id].append(user)
    for row in DocumentoExigencia.query.all():
        _absorber_exigencia(pack, row)
    for aporte in DocumentoAporte.query.filter_by(vigente=True).order_by(DocumentoAporte.id.desc()).all():
        if aporte.user_id:
            bucket = pack.aporte_user.setdefault((aporte.user_id, aporte.tipo_id), {})
            _meter_aporte(bucket, aporte)
        elif aporte.company_id:
            bucket = pack.aporte_empresa.setdefault((aporte.company_id, aporte.tipo_id), {})
            _meter_aporte(bucket, aporte)
    pack.company_exigencias.update(ids)
    pack.empresas_completas.update(ids)
    pack.aporte_empresa_leido.update(ids)
    _marcar_cert(pack, ids, hoy)
    pack.todo = True


def _filas_empresa_pack(pack: _DocPack, company: Company, hoy: date) -> list[dict]:
    anadidas = pack.anadir_empresa.get(company.id, set())
    filas = []
    for tipo in _tipos_empresa_pack(pack, company):
        bucket = {} if tipo.es_certificacion else pack.aporte_empresa.get((company.id, tipo.id), {})
        origen = 'especifica' if tipo.id in anadidas else 'generica'
        filas.append(_fila(pack, tipo, bucket, company.id, hoy, origen))
    return filas


def _filas_persona_pack(pack: _DocPack, user: User, hoy: date, solo_fase: int | None) -> list[dict]:
    personales = pack.anadir_persona.get(user.id, set())
    filas = []
    for tipo in _tipos_persona_pack(pack, user):
        if solo_fase is not None and int(tipo.fase_contratacion or 0) != solo_fase:
            continue
        bucket = pack.aporte_user.get((user.id, tipo.id), {})
        origen = 'persona' if tipo.id in personales else 'generica'
        filas.append(_fila(pack, tipo, bucket, user.company_id, hoy, origen))
    return filas


def filas_empresa(company: Company, hoy: date | None = None) -> list[dict]:
    hoy = hoy or today_local()
    pack = _pack_request()
    _llenar_empresa(pack, company, hoy)
    return _filas_empresa_pack(pack, company, hoy)


def filas_persona(user: User, hoy: date | None = None, *, solo_fase: int | None = None) -> list[dict]:
    hoy = hoy or today_local()
    pack = _pack_request()
    if user.company_id and user.company_id in pack.empresas_completas and user.id in pack.user_ids:
        pass
    else:
        _llenar_persona(pack, user, hoy)
    return _filas_persona_pack(pack, user, hoy, solo_fase)


def resumir(filas: list[dict]) -> dict:
    errores = sum(1 for f in filas if es_error_documental(f['estado']))
    avisos = sum(1 for f in filas if es_aviso_documental(f['estado']))
    ok = sum(1 for f in filas if f['estado'] in ('ok', 'cert_ok', 'por_caducar'))
    # Solo cuentan como enviados los que tienen fichero de verdad.
    enviados = sum(
        1 for f in filas
        if f['estado'] in ('ok', 'pendiente_validar', 'por_caducar', 'rechazado', 'caducado')
    )
    exigidos = sum(
        1 for f in filas
        if not f['tipo'].es_certificacion and f['estado'] != 'opcional_vacio'
    )
    if exigidos == 0:
        exigidos = sum(1 for f in filas if not f['tipo'].es_certificacion)
    prog = progreso_contratacion(filas)
    return {
        'errores': errores,
        'avisos': avisos,
        'ok': ok,
        'total': len(filas),
        'enviados': enviados,
        'exigidos': exigidos,
        'validados': prog['validados'],
        'por_validar': prog['por_validar'],
        'por_completar': prog['por_completar'],
        'prog_total': prog['total'],
    }


def progreso_contratacion(filas: list[dict]) -> dict:
    """Barra de contratación: validado / por validar / por completar."""
    docs = [
        f for f in filas
        if not f['tipo'].es_certificacion and f['estado'] != 'opcional_vacio'
    ]
    validados = sum(1 for f in docs if f['estado'] in ('ok', 'por_caducar'))
    por_validar = sum(1 for f in docs if f['estado'] == 'pendiente_validar')
    por_completar = sum(
        1 for f in docs
        if f['estado'] in ('falta', 'rechazado', 'caducado', 'cert_pendiente')
    )
    total = len(docs)
    return {
        'validados': validados,
        'por_validar': por_validar,
        'por_completar': por_completar,
        'total': total,
        'pct_ok': (validados * 100 / total) if total else 0,
        'pct_wait': (por_validar * 100 / total) if total else 0,
        'pct_bad': (por_completar * 100 / total) if total else 0,
    }


def excluir_generica(tipo_id: int, company_id: int, destino: str) -> None:
    """destino: empresa | empleados."""
    existe = DocumentoExigencia.query.filter_by(
        tipo_id=tipo_id, company_id=company_id, destino=destino, modo='excluir',
    ).first()
    if not existe:
        db.session.add(DocumentoExigencia(
            tipo_id=tipo_id, company_id=company_id, destino=destino, modo='excluir',
        ))
    DocumentoExigencia.query.filter_by(
        tipo_id=tipo_id, company_id=company_id, destino=destino, modo='anadir',
    ).delete()


def excluir_para_persona(tipo_id: int, user_id: int) -> None:
    """Quita un documento solo para esta persona (herencia o extra personal)."""
    DocumentoExigencia.query.filter_by(
        tipo_id=tipo_id, user_id=user_id, destino='persona', modo='anadir',
    ).delete()
    existe = DocumentoExigencia.query.filter_by(
        tipo_id=tipo_id, user_id=user_id, destino='persona', modo='excluir',
    ).first()
    if not existe:
        db.session.add(DocumentoExigencia(
            tipo_id=tipo_id, user_id=user_id, destino='persona', modo='excluir',
        ))


def anadir_especifica(tipo_id: int, *, company_id=None, user_id=None, destino: str) -> None:
    q = DocumentoExigencia.query.filter_by(tipo_id=tipo_id, destino=destino, modo='anadir')
    if user_id:
        q = q.filter_by(user_id=user_id)
    else:
        q = q.filter_by(company_id=company_id, user_id=None)
    if q.first():
        return
    if company_id and not user_id:
        DocumentoExigencia.query.filter_by(
            tipo_id=tipo_id, company_id=company_id, destino=destino, modo='excluir',
        ).delete()
    if user_id:
        DocumentoExigencia.query.filter_by(
            tipo_id=tipo_id, user_id=user_id, destino='persona', modo='excluir',
        ).delete()
    db.session.add(DocumentoExigencia(
        tipo_id=tipo_id,
        company_id=company_id,
        user_id=user_id,
        destino=destino,
        modo='anadir',
    ))


def quitar_especifica(exigencia_id: int) -> None:
    row = DocumentoExigencia.query.get(exigencia_id)
    if row and row.modo == 'anadir':
        db.session.delete(row)


def _directorio() -> str:
    schema = db.session.execute(text('SELECT current_schema()')).scalar() or 'tenant'
    safe = ''.join(ch for ch in str(schema) if ch.isalnum() or ch == '_')
    base = os.path.abspath(os.path.join(current_app.root_path, '..', 'uploads', 'documentacion', safe))
    os.makedirs(base, exist_ok=True)
    return base


def guardar_fichero(storage) -> tuple[str, str]:
    if not storage or not storage.filename:
        raise ValueError('Falta el fichero.')
    storage.seek(0, os.SEEK_END)
    size = storage.tell()
    storage.seek(0)
    if size > MAX_BYTES:
        raise ValueError('El fichero supera 20 MB.')
    original = secure_filename(storage.filename) or 'documento'
    ext = os.path.splitext(original)[1].lower()
    if ext not in EXTENSIONES:
        raise ValueError('Formato no admitido. Usa PDF o una imagen.')
    nombre = f'{uuid.uuid4().hex}{ext}'
    path = os.path.join(_directorio(), nombre)
    storage.save(path)
    return nombre, original


def ruta_aporte(aporte: DocumentoAporte) -> str | None:
    if not aporte or not aporte.archivo_path:
        return None
    path = os.path.join(_directorio(), aporte.archivo_path)
    if not os.path.isfile(path):
        return None
    return path


def subir(tipo: DocumentoTipo, storage, *, company_id=None, user_id=None, nota=None, actor_id=None, slot=None) -> DocumentoAporte:
    if tipo.es_certificacion:
        raise ValueError('Este requisito se cumple con la certificación de horario, no con un fichero.')
    huecos = slots_de(tipo)
    slot_key = _slot_key(slot)
    if huecos:
        codigos = {s['codigo'] for s in huecos}
        if slot_key not in codigos:
            raise ValueError('Indica qué parte del documento estás subiendo.')
    else:
        slot_key = ''
    archivo, original = guardar_fichero(storage)
    previos = DocumentoAporte.query.filter_by(tipo_id=tipo.id, vigente=True)
    if user_id:
        previos = previos.filter_by(user_id=user_id)
    else:
        previos = previos.filter(DocumentoAporte.user_id.is_(None), DocumentoAporte.company_id == company_id)
    if slot_key:
        previos = previos.filter(DocumentoAporte.slot == slot_key)
    else:
        previos = previos.filter(or_(DocumentoAporte.slot.is_(None), DocumentoAporte.slot == ''))
    version = 1
    for previo in previos.all():
        version = max(version, int(previo.version or 1) + 1)
        previo.vigente = False
    aporte = DocumentoAporte(
        tipo_id=tipo.id,
        company_id=None if user_id else company_id,
        user_id=user_id,
        archivo_path=archivo,
        nombre_original=original,
        nota=(nota or '').strip() or None,
        estado='subido',
        subido_por_id=actor_id,
        version=version,
        vigente=True,
        slot=slot_key or None,
    )
    db.session.add(aporte)
    db.session.flush()
    _invalidar_badge()
    return aporte


def subir_desde_request(tipo: DocumentoTipo, request, *, company_id=None, user_id=None, actor_id=None) -> list[DocumentoAporte]:
    """Acepta un fichero, o varios si la plantilla tiene huecos (archivo_anverso, …)."""
    nota = request.form.get('nota')
    huecos = slots_de(tipo)
    subidos = []
    if huecos:
        for slot in huecos:
            storage = (
                request.files.get(f'archivo_{slot["codigo"]}')
                or request.files.get(f'archivo[{slot["codigo"]}]')
            )
            if storage and storage.filename:
                subidos.append(subir(
                    tipo, storage,
                    company_id=company_id, user_id=user_id,
                    nota=nota, actor_id=actor_id, slot=slot['codigo'],
                ))
        if not subidos:
            storage = request.files.get('archivo')
            slot = request.form.get('slot')
            if storage and storage.filename:
                subidos.append(subir(
                    tipo, storage,
                    company_id=company_id, user_id=user_id,
                    nota=nota, actor_id=actor_id, slot=slot,
                ))
        if not subidos:
            raise ValueError('Elige al menos un archivo.')
        return subidos
    storage = request.files.get('archivo')
    if not storage or not storage.filename:
        raise ValueError('Falta el fichero.')
    return [subir(
        tipo, storage,
        company_id=company_id, user_id=user_id,
        nota=nota, actor_id=actor_id,
    )]


def validar(aporte: DocumentoAporte, *, actor_id, caduca_el, aceptado_caducado=False, nota=None) -> None:
    aporte.estado = 'validado'
    aporte.caduca_el = caduca_el
    aporte.aceptado_caducado = bool(aceptado_caducado)
    aporte.nota_oficina = (nota or '').strip() or None
    aporte.validado_por_id = actor_id
    from app.utils.timezone_utils import utc_now
    aporte.validado_at = utc_now()
    _invalidar_badge()


def rechazar(aporte: DocumentoAporte, *, actor_id, nota: str) -> None:
    if not (nota or '').strip():
        raise ValueError('El rechazo necesita una nota.')
    aporte.estado = 'rechazado'
    aporte.nota_oficina = nota.strip()
    aporte.validado_por_id = actor_id
    from app.utils.timezone_utils import utc_now
    aporte.validado_at = utc_now()
    _invalidar_badge()


def crear_tipo(**kwargs) -> DocumentoTipo:
    from app.utils.timezone_utils import utc_now
    tipo = DocumentoTipo(
        nombre=(kwargs.get('nombre') or '').strip(),
        categoria=(kwargs.get('categoria') or 'General').strip() or 'General',
        ambito=kwargs.get('ambito') or 'empleado',
        audiencia=kwargs.get('audiencia') or 'ambos',
        regla_renovacion=kwargs.get('regla_renovacion') or 'ninguna',
        dia_renovacion=int(kwargs.get('dia_renovacion') or 1),
        mes_renovacion=int(kwargs['mes_renovacion']) if kwargs.get('mes_renovacion') else None,
        fase_contratacion=int(kwargs.get('fase_contratacion') or 0),
        bloquea_fase=bool(kwargs.get('bloquea_fase')),
        obligatorio=bool(kwargs.get('obligatorio', True)),
        es_sistema=False,
        activo=bool(kwargs.get('activo', True)),
        por_defecto=bool(kwargs.get('por_defecto', True)),
        orden=int(kwargs.get('orden') or 500),
        created_at=utc_now(),
    )
    if not tipo.nombre:
        raise ValueError('El documento necesita un nombre.')
    if tipo.ambito not in ('empresa', 'empleado'):
        raise ValueError('Ámbito no válido.')
    if tipo.audiencia not in ('subcontrata', 'interno', 'ambos'):
        raise ValueError('Audiencia no válida.')
    db.session.add(tipo)
    db.session.flush()
    return tipo


def eliminar_tipo(tipo: DocumentoTipo) -> None:
    """Elimina la plantilla del catálogo (desaparece). Las de sistema no se borran."""
    if getattr(tipo, 'es_sistema', False):
        raise ValueError(
            'Las plantillas de sistema no se pueden eliminar. '
            'Desmarca «Activa» si no quieres que se pidan.'
        )
    # Borrar ficheros físicos de aportes (CASCADE limpia las filas).
    aportes = DocumentoAporte.query.filter_by(tipo_id=tipo.id).all()
    for aporte in aportes:
        path = ruta_aporte(aporte)
        if path:
            try:
                os.remove(path)
            except OSError:
                pass
    db.session.delete(tipo)
    _invalidar_badge()


def tipo_recien_creado(tipo: DocumentoTipo, *, minutos: int = 2) -> bool:
    """Plantilla creada hace poco: se puede borrar del todo sin pasar por el catálogo."""
    if not tipo or getattr(tipo, 'es_sistema', False):
        return False
    created = getattr(tipo, 'created_at', None)
    if created is None:
        return False
    from app.utils.timezone_utils import utc_now
    ahora = utc_now()
    if created.tzinfo is None and getattr(ahora, 'tzinfo', None) is not None:
        created = created.replace(tzinfo=ahora.tzinfo)
    elif created.tzinfo is not None and getattr(ahora, 'tzinfo', None) is None:
        ahora = ahora.replace(tzinfo=created.tzinfo)
    try:
        return (ahora - created).total_seconds() <= max(60, minutos * 60)
    except Exception:
        return False


def borrar_tipo_definitivo(tipo: DocumentoTipo) -> None:
    """Borra la plantilla del catálogo (solo si es reciente y no de sistema)."""
    if not tipo_recien_creado(tipo):
        raise ValueError('Solo se puede borrar del todo una plantilla recién creada.')
    eliminar_tipo(tipo)


_BADGE_CACHE = {}
_BADGE_TTL = 180
_BADGE_STORE_TTL = 6 * 3600
_CONFIG_BADGE_ERR = 'doc_badge_errores'
_CONFIG_BADGE_AVISO = 'doc_badge_avisos'
_CONFIG_BADGE_TS = 'doc_badge_ts'


def _badge_key(company_id: int | None):
    schema = ''
    if has_request_context():
        tenant = getattr(g, 'current_tenant', None)
        schema = getattr(tenant, 'schema_name', None) or ''
    if not schema:
        schema = db.session.execute(text('SELECT current_schema()')).scalar() or ''
    return (str(schema), int(company_id or 0))


def _guardar_badge(company_id: int | None, errores: int, avisos: int) -> None:
    _BADGE_CACHE[_badge_key(company_id)] = (time.monotonic(), int(errores), int(avisos))
    # Oficina: recuerda la pelota entre páginas/workers para no tener que abrir Documentación.
    if company_id is None and has_request_context():
        try:
            from app.services.config_service import set_tenant_config
            set_tenant_config(_CONFIG_BADGE_ERR, str(int(errores)))
            set_tenant_config(_CONFIG_BADGE_AVISO, str(int(avisos)))
            set_tenant_config(_CONFIG_BADGE_TS, str(int(time.time())))
        except Exception:
            pass


def _invalidar_badge() -> None:
    _BADGE_CACHE.clear()
    if has_request_context():
        try:
            from app.services.config_service import set_tenant_config
            set_tenant_config(_CONFIG_BADGE_TS, '0')
        except Exception:
            pass


# Al cargar el módulo tras un despliegue, tira la pelota vieja (contaba documentos).
_BADGE_CACHE.clear()


def badge_en_cache(company_id: int | None = None):
    """None si el recuento está frío. Memoria primero; luego almacén del tenant (oficina)."""
    hit = _BADGE_CACHE.get(_badge_key(company_id))
    if hit and time.monotonic() - hit[0] < _BADGE_TTL:
        return hit[1], hit[2]
    if company_id is None and has_request_context():
        try:
            from app.services.config_service import get_tenant_config
            ts = int(get_tenant_config(_CONFIG_BADGE_TS, default='0') or 0)
            if ts and (time.time() - ts) < _BADGE_STORE_TTL:
                err = int(get_tenant_config(_CONFIG_BADGE_ERR, default='0') or 0)
                avi = int(get_tenant_config(_CONFIG_BADGE_AVISO, default='0') or 0)
                _BADGE_CACHE[_badge_key(None)] = (time.monotonic(), err, avi)
                return err, avi
        except Exception:
            pass
    return None


_ESTADOS_ACCION = frozenset({
    'pendiente_validar', 'rechazado', 'caducado', 'por_caducar',
})


def _filas_tienen_aporte(filas: list[dict]) -> bool:
    for f in filas:
        aporte = f.get('aporte')
        if aporte is not None and getattr(aporte, 'archivo_path', None):
            return True
        for slot in f.get('slots') or []:
            sa = slot.get('aporte')
            if sa is not None and getattr(sa, 'archivo_path', None):
                return True
    return False


def _detalle_persona(user: User, filas: list[dict]) -> dict:
    resumen = resumir(filas)
    errores_contratacion = sum(
        1 for f in filas
        if es_error_documental(f['estado']) and int(f['tipo'].fase_contratacion or 0) > 0
    )
    errores_resto = sum(
        1 for f in filas
        if es_error_documental(f['estado']) and int(f['tipo'].fase_contratacion or 0) == 0
    )
    avisos_contratacion = sum(
        1 for f in filas
        if es_aviso_documental(f['estado']) and int(f['tipo'].fase_contratacion or 0) > 0
    )
    avisos_resto = sum(
        1 for f in filas
        if es_aviso_documental(f['estado']) and int(f['tipo'].fase_contratacion or 0) == 0
    )
    pendientes = [
        {
            'nombre': f['tipo'].nombre,
            'estado': f['estado'],
            'contratacion': int(f['tipo'].fase_contratacion or 0) > 0,
        }
        for f in filas
        if es_error_documental(f['estado']) or es_aviso_documental(f['estado'])
    ]
    pendientes_vista = pendientes[:8]
    tiene_aporte = _filas_tienen_aporte(filas)
    requiere_accion = any(f['estado'] in _ESTADOS_ACCION for f in filas)
    hiring = bool(user.hiring_state)
    # Plantilla sin ningún fichero: no hincha la pelota ni el listado (arranque en frío).
    sin_expediente = (not hiring) and (not tiene_aporte) and bool(resumen['errores'])
    return {
        'user': user,
        **resumen,
        'hiring': hiring,
        'hiring_state': user.hiring_state,
        'errores_contratacion': errores_contratacion,
        'errores_resto': errores_resto,
        'avisos_contratacion': avisos_contratacion,
        'avisos_resto': avisos_resto,
        'pendientes': pendientes_vista,
        'pendientes_extra': max(0, len(pendientes) - len(pendientes_vista)),
        'tiene_pendientes_contratacion': any(p['contratacion'] for p in pendientes),
        'tiene_pendientes_resto': any(not p['contratacion'] for p in pendientes),
        'tiene_aporte': tiene_aporte,
        'requiere_accion': requiere_accion,
        'sin_expediente': sin_expediente,
    }


def _casos_subcontrata(empresa_errores: int, empresa_avisos: int, emp_errores: int, emp_avisos: int) -> list[str]:
    casos = []
    if empresa_errores:
        casos.append('empresa')
    if emp_errores:
        casos.append('empleados')
    if not casos:
        if empresa_avisos:
            casos.append('empresa_aviso')
        if emp_avisos:
            casos.append('empleados_aviso')
    return casos


def panel_documentacion_oficina(hoy: date | None = None) -> dict:
    """Panel de oficina: internos, subcontratas y pelota por sujetos (no por documento)."""
    hoy = hoy or today_local()
    pack = _pack_request()
    _llenar_todo(pack, hoy)

    companies = [
        c for c in pack.companies.values()
        if c.active and c.id in pack.empresas_completas
    ]
    companies.sort(key=lambda c: (not c.is_internal, (c.nombre or '').lower()))

    interna = next((c for c in companies if c.is_internal), None)
    personas_internas = []
    if interna:
        for user in sorted(
            pack.users_by_company.get(interna.id, []),
            key=lambda u: ((u.name or '').lower(), (u.lastname or '').lower()),
        ):
            filas = _filas_persona_pack(pack, user, hoy, None)
            personas_internas.append(_detalle_persona(user, filas))

    personas_internas.sort(
        key=lambda p: (-p['errores'], -p['avisos'], (p['user'].name or '').lower()),
    )
    # Acción real: validar / rechazado / caducado / aviso. No listar 100 «falta» de arranque.
    accion_i = [p for p in personas_internas if p['requiere_accion'] or (p['hiring'] and p['errores'])]
    sin_expediente_i = [p for p in personas_internas if p['sin_expediente']]
    con_aviso_i = [p for p in personas_internas if p['avisos'] and not p['errores']]
    en_alta = [p for p in personas_internas if p['hiring']]
    al_dia = [p for p in personas_internas if not p['errores'] and not p['avisos']]

    panel_interna = {
        'company': interna,
        'total': len(personas_internas),
        'con_error': len(accion_i),
        'con_aviso': len(con_aviso_i),
        'en_contratacion': len(en_alta),
        'al_dia': len(al_dia),
        'sin_expediente': len(sin_expediente_i),
        'personas': personas_internas,
        'personas_contratacion': [p for p in personas_internas if p['hiring']],
        'personas_plantilla_problema': [
            p for p in personas_internas
            if (not p['hiring']) and p['requiere_accion']
        ],
        'personas_plantilla_ok': len([
            p for p in personas_internas if (not p['hiring']) and not p['errores'] and not p['avisos']
        ]),
    }

    subcontratas = []
    for company in companies:
        if company.is_internal:
            continue
        filas_emp = _filas_empresa_pack(pack, company, hoy)
        resumen_emp = resumir(filas_emp)
        emp_err = 0
        emp_aviso = 0
        for user in pack.users_by_company.get(company.id, []):
            r = resumir(_filas_persona_pack(pack, user, hoy, None))
            if r['errores']:
                emp_err += 1
            elif r['avisos']:
                emp_aviso += 1
        if not (resumen_emp['errores'] or resumen_emp['avisos'] or emp_err or emp_aviso):
            continue
        pendientes_empresa = [
            {'nombre': f['tipo'].nombre, 'estado': f['estado']}
            for f in filas_emp
            if es_error_documental(f['estado']) or es_aviso_documental(f['estado'])
        ]
        subcontratas.append({
            'company': company,
            'empresa_errores': resumen_emp['errores'],
            'empresa_avisos': resumen_emp['avisos'],
            'empresa_ok': resumen_emp['ok'],
            'empresa_total': resumen_emp['total'],
            'empleados_total': len(pack.users_by_company.get(company.id, [])),
            'empleados_con_error': emp_err,
            'empleados_con_aviso': emp_aviso,
            'casos': _casos_subcontrata(
                resumen_emp['errores'], resumen_emp['avisos'], emp_err, emp_aviso,
            ),
            'pendientes_empresa': pendientes_empresa[:8],
            'pendientes_empresa_extra': max(0, len(pendientes_empresa) - 8),
        })

    # Pelota: acción interna + cada subcontrata con fallo. No cuentan los 100 sin expediente.
    padres_error = len(accion_i) + sum(
        1 for s in subcontratas
        if s['empresa_errores'] or s['empleados_con_error']
    )
    padres_aviso = len([p for p in con_aviso_i if not p['requiere_accion'] and not p['hiring']]) + sum(
        1 for s in subcontratas
        if not (s['empresa_errores'] or s['empleados_con_error'])
        and (s['empresa_avisos'] or s['empleados_con_aviso'])
    )
    _guardar_badge(None, padres_error, padres_aviso)

    # Compatibilidad con pantallas antiguas.
    empresas_legacy = []
    for s in subcontratas:
        empresas_legacy.append({
            'company': s['company'],
            'errores': s['empresa_errores'] + s['empleados_con_error'],
            'avisos': s['empresa_avisos'] + s['empleados_con_aviso'],
        })
    if interna and (panel_interna['con_error'] or panel_interna['con_aviso']):
        empresas_legacy.insert(0, {
            'company': interna,
            'errores': sum(p['errores'] for p in personas_internas),
            'avisos': sum(p['avisos'] for p in personas_internas),
        })

    return {
        'errores': padres_error,
        'avisos': padres_aviso,
        'interna': panel_interna,
        'subcontratas': subcontratas,
        'empresas': empresas_legacy,
    }


def alertas_oficina(hoy: date | None = None) -> dict:
    """Alias del panel. La pelota cuenta sujetos, no documentos."""
    return panel_documentacion_oficina(hoy)


def conteo_badge(company_id: int | None = None) -> tuple[int, int]:
    """Pelota del menú: sujetos con fallo (persona interna o subcontrata)."""
    cached = badge_en_cache(company_id)
    if cached is not None:
        return cached
    try:
        if company_id:
            company = Company.query.get(company_id)
            if company is None:
                pair = (0, 0)
            else:
                hoy = today_local()
                pack = _pack_request()
                _llenar_empresa(pack, company, hoy)
                filas = _filas_empresa_pack(pack, company, hoy)
                resumen = resumir(filas)
                emp_err = 0
                emp_aviso = 0
                for persona in pack.users_by_company.get(company.id, []):
                    r = resumir(_filas_persona_pack(pack, persona, hoy, None))
                    if r['errores']:
                        emp_err += 1
                    elif r['avisos']:
                        emp_aviso += 1
                # En el portal de una sola empresa: 1 si falla la empresa + 1 por cada operario.
                padres_e = (1 if resumen['errores'] else 0) + emp_err
                padres_a = (1 if resumen['avisos'] and not resumen['errores'] else 0) + emp_aviso
                pair = (padres_e, padres_a)
        else:
            data = panel_documentacion_oficina()
            pair = (int(data['errores']), int(data['avisos']))
            return pair
    except Exception:
        current_app.logger.exception('No se ha podido contar la documentación')
        db.session.rollback()
        pair = (0, 0)
    _guardar_badge(company_id, pair[0], pair[1])
    return pair


def fase1_completa(user: User) -> bool:
    """Pasa a fase 2 solo cuando lo necesario de fase 1 está validado (no basta con subirlo)."""
    filas = [
        f for f in filas_persona(user)
        if int(f['tipo'].fase_contratacion or 0) == 1
        and not f['tipo'].es_certificacion
        and (
            f['tipo'].bloquea_fase
            or f['tipo'].obligatorio
        )
        and f['estado'] != 'opcional_vacio'
    ]
    if not filas:
        return False
    return all(f['estado'] in ('ok', 'por_caducar') for f in filas)


def fase2_completa(user: User) -> bool:
    """Art. 19 y reconocimiento validados (o no hay ninguno exigido)."""
    filas = [
        f for f in filas_persona(user)
        if int(f['tipo'].fase_contratacion or 0) == 2
        and not f['tipo'].es_certificacion
        and (
            f['tipo'].bloquea_fase
            or f['tipo'].obligatorio
        )
        and f['estado'] != 'opcional_vacio'
    ]
    if not filas:
        return True
    return all(f['estado'] in ('ok', 'por_caducar') for f in filas)


def filas_contratacion(user: User, *, incluir_fase2_bloqueada: bool = False) -> list[dict]:
    """Docs de alta: fase 2 solo se exige (y cuenta) cuando la fase 1 está cerrada."""
    filas = [
        f for f in filas_persona(user)
        if int(f['tipo'].fase_contratacion or 0) in (1, 2)
        and not f['tipo'].es_certificacion
    ]
    en_fase2 = user.hiring_state == 'fase2'
    out = []
    for f in filas:
        fase = int(f['tipo'].fase_contratacion or 0)
        if fase == 2 and not en_fase2:
            if not incluir_fase2_bloqueada:
                continue
            locked = dict(f)
            locked['fase_bloqueada'] = True
            out.append(locked)
            continue
        item = dict(f)
        item['fase_bloqueada'] = False
        out.append(item)
    return out


def filas_contratacion_activas(user: User) -> list[dict]:
    """Solo lo que ahora mismo hay que completar/validar."""
    return [f for f in filas_contratacion(user) if not f.get('fase_bloqueada')]


def puede_finalizar(user: User) -> bool:
    if not user.hiring_state:
        return False
    if not fase1_completa(user):
        return False
    return fase2_completa(user)