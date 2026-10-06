"""Documentación, certificación y contratación para la empresa del SaaS."""
from __future__ import annotations

from datetime import date, datetime

from flask import (
    Response,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user, login_required

from app import db
from app.compliance import compliance_bp
from app.decorators import permission_required
from app.models import ROLE_ADMIN_SUBCONTRATA, ROLE_OPERARIO
from app.models import Company, DocumentoAporte, DocumentoTipo, User
from app.services.certificacion_service import (
    DIR_EMP,
    DIR_SUB,
    aceptar,
    agrupar,
    agrupar_por_fecha,
    agrupar_por_persona,
    aplicar_precio_borrador,
    aplicar_precio_plataforma_herederos,
    contar_borradores_odoo,
    enriquecer_grupos_ref_app,
    mapa_lineas_propuesta,
    desenviar,
    detalle_certificacion_obra,
    enviar,
    estado_propuesta,
    filtrar_grupos_por_rango,
    guardar_linea,
    guardar_precio_empresa,
    guardar_precio_plataforma,
    html_propuesta,
    interseccion_mes,
    lineas_incompletas,
    lineas_tramo_invalido,
    marcar_discrepancias,
    nombre_archivo_pdf,
    panel_certificacion_empresa_obras,
    panel_certificacion_obras,
    panel_certificacion_oficina,
    panel_meses_obra,
    parse_hora,
    pdf_propuesta,
    periodo_bloqueado,
    precio_empresa,
    precio_plataforma,
    propuestas_entrantes_oficina,
    rechazar,
    restablecer_linea_desde_fichaje,
    resumen_actividad,
    sincronizar,
    totales,
    totales_grupos,
)
from app.services.compliance_rules import email_es_real
from app.services.contratacion_service import (
    actualizar_perfil,
    asegurar_empresa_interna,
    crear as crear_contratacion,
    empresa_interna,
    finalizar,
    refrescar_fase,
)
from app.services.documentacion_service import (
    alertas_oficina,
    anadir_especifica,
    aporte_vigente,
    aviso_dias,
    borrar_tipo_definitivo,
    crear_tipo,
    eliminar_tipo,
    excluir_generica,
    excluir_para_persona,
    fase1_completa,
    filas_contratacion,
    filas_contratacion_activas,
    filas_empresa,
    filas_persona,
    guardar_aviso_dias,
    progreso_contratacion,
    rechazar as rechazar_doc,
    resumir,
    ruta_aporte,
    subir,
    tipo_recien_creado,
    tipos_plantilla_empleados_empresa,
    validar,
)
from app.services.documentacion_service import asegurar_catalogo
from app.services.i18n_service import translate
from app.services.tenant_modules import has_certificacion, has_contratacion, has_documentacion
from app.utils.timezone_utils import today_local


def _exigir(flag):
    if not flag():
        abort(404)


@compliance_bp.before_request
@login_required
def _solo_oficina():
    if getattr(current_user, 'role', None) in (ROLE_OPERARIO, ROLE_ADMIN_SUBCONTRATA):
        abort(403)


@compliance_bp.route('/documentacion')
@login_required
@permission_required('documentacion', 'r')
def documentacion():
    _exigir(has_documentacion)
    from app.services.documentacion_service import panel_documentacion_oficina
    panel = panel_documentacion_oficina()
    return render_template(
        'compliance/documentacion_oficina.html',
        panel=panel,
        alertas=panel,
        aviso_dias=aviso_dias(),
        entrantes=propuestas_entrantes_oficina() if has_certificacion() else 0,
    )


@compliance_bp.route('/documentacion/badge')
@login_required
@permission_required('documentacion', 'r')
def documentacion_badge():
    """Pelota del menú sin abrir el panel (JSON)."""
    _exigir(has_documentacion)
    from flask import jsonify
    from app.models import ROLE_ADMIN_SUBCONTRATA, ROLE_OPERARIO
    from app.services.documentacion_service import conteo_badge

    if current_user.role == ROLE_ADMIN_SUBCONTRATA and current_user.company_id:
        company_id = current_user.company_id
    elif current_user.role not in (ROLE_OPERARIO, ROLE_ADMIN_SUBCONTRATA):
        company_id = None
    else:
        return jsonify(errores=0, avisos=0)
    errores, avisos = conteo_badge(company_id)
    return jsonify(errores=int(errores), avisos=int(avisos))


@compliance_bp.route('/documentacion/ajustes', methods=['GET', 'POST'])
@login_required
@permission_required('configuracion', 'w')
def ajustes():
    if request.method == 'POST':
        try:
            guardar_aviso_dias(int(request.form.get('aviso_dias') or 15))
            db.session.commit()
            flash(translate('Ajustes guardados.'), 'success')
        except Exception as exc:
            db.session.rollback()
            flash(translate('No se han podido guardar: {error}', error=exc), 'danger')
        return redirect(url_for('compliance.ajustes'))
    return render_template(
        'compliance/ajustes.html',
        aviso_dias=aviso_dias(),
    )


@compliance_bp.route('/documentacion/catalogo', methods=['GET', 'POST'])
@login_required
@permission_required('documentacion', 'w')
def catalogo():
    _exigir(has_documentacion)
    asegurar_catalogo()

    def _grupo_redirect(tipo_or_destino):
        if isinstance(tipo_or_destino, str):
            destino = tipo_or_destino
            if destino == 'subcontratas':
                return 'subcontratas'
            if destino == 'interno_hire':
                return 'contratacion'
            if destino == 'interno_emp':
                return 'empleado'
            if destino == 'externo':
                return 'empleado_externo'
            return destino
        tipo = tipo_or_destino
        if tipo.ambito == 'empresa':
            return 'subcontratas'
        if (tipo.fase_contratacion or 0) > 0:
            return 'contratacion'
        if tipo.audiencia == 'subcontrata':
            return 'empleado_externo'
        return 'empleado'

    def _aplicar_destino(tipo, destino):
        """Mueve / reutiliza una plantilla en el bucket indicado."""
        if destino == 'subcontratas':
            tipo.ambito = 'empresa'
            tipo.audiencia = 'subcontrata'
            tipo.fase_contratacion = 0
            tipo.bloquea_fase = False
            return
        if destino == 'interno_hire':
            tipo.ambito = 'empleado'
            tipo.fase_contratacion = max(int(tipo.fase_contratacion or 0), 1) or 1
            if tipo.audiencia == 'subcontrata':
                tipo.audiencia = 'ambos'
            elif tipo.audiencia not in ('interno', 'ambos'):
                tipo.audiencia = 'interno'
            return
        if destino == 'interno_emp':
            tipo.ambito = 'empleado'
            tipo.fase_contratacion = 0
            tipo.bloquea_fase = False
            if tipo.audiencia == 'subcontrata':
                tipo.audiencia = 'ambos'
            elif tipo.audiencia not in ('interno', 'ambos'):
                tipo.audiencia = 'interno'
            return
        if destino == 'externo':
            tipo.ambito = 'empleado'
            tipo.fase_contratacion = 0
            tipo.bloquea_fase = False
            if tipo.audiencia == 'interno':
                # Reutilizar: la misma plantilla vale para internos y externos
                tipo.audiencia = 'ambos'
            elif tipo.audiencia not in ('subcontrata', 'ambos'):
                tipo.audiencia = 'subcontrata'
            return
        raise ValueError(translate('Destino de catálogo no válido.'))

    if request.method == 'POST':
        accion = request.form.get('accion')
        try:
            if accion == 'crear':
                fase = int(request.form.get('fase_contratacion') or 0)
                ambito = request.form.get('ambito') or 'empleado'
                audiencia = request.form.get('audiencia') or 'ambos'
                if ambito == 'empresa':
                    audiencia = 'subcontrata'
                    fase = 0
                crear_tipo(
                    nombre=request.form.get('nombre'),
                    categoria=request.form.get('categoria'),
                    ambito=ambito,
                    audiencia=audiencia,
                    regla_renovacion=request.form.get('regla_renovacion') or 'ninguna',
                    dia_renovacion=request.form.get('dia_renovacion') or 1,
                    mes_renovacion=request.form.get('mes_renovacion') or None,
                    fase_contratacion=fase,
                    bloquea_fase=request.form.get('bloquea_fase') == 'on',
                    obligatorio=request.form.get('obligatorio') == 'on',
                    activo=request.form.get('activo') == 'on',
                    por_defecto=request.form.get('por_defecto') == 'on',
                )
                db.session.commit()
                flash(translate('Catálogo actualizado.'), 'success')
                if ambito == 'empresa':
                    grupo = 'subcontratas'
                elif fase > 0:
                    grupo = 'contratacion'
                elif audiencia == 'subcontrata':
                    grupo = 'empleado_externo'
                else:
                    grupo = 'empleado'
                return redirect(url_for('compliance.catalogo', g=grupo))
            elif accion == 'mover':
                tipo = DocumentoTipo.query.get_or_404(int(request.form.get('tipo_id')))
                destino = (request.form.get('destino') or '').strip()
                _aplicar_destino(tipo, destino)
                db.session.commit()
                flash(translate('Plantilla movida / reutilizada.'), 'success')
                return redirect(url_for('compliance.catalogo', g=_grupo_redirect(destino)))
            elif accion == 'editar':
                tipo = DocumentoTipo.query.get_or_404(int(request.form.get('tipo_id')))
                tipo.nombre = (request.form.get('nombre') or tipo.nombre).strip()
                tipo.categoria = (request.form.get('categoria') or tipo.categoria).strip()
                if tipo.ambito != 'empresa' and request.form.get('audiencia'):
                    tipo.audiencia = request.form.get('audiencia')
                tipo.regla_renovacion = request.form.get('regla_renovacion') or tipo.regla_renovacion
                tipo.dia_renovacion = int(request.form.get('dia_renovacion') or tipo.dia_renovacion or 1)
                mes = request.form.get('mes_renovacion')
                tipo.mes_renovacion = int(mes) if mes else None
                tipo.fase_contratacion = int(request.form.get('fase_contratacion') or 0)
                tipo.bloquea_fase = request.form.get('bloquea_fase') == 'on'
                tipo.obligatorio = request.form.get('obligatorio') == 'on'
                tipo.activo = request.form.get('activo') == 'on'
                tipo.por_defecto = request.form.get('por_defecto') == 'on'
                db.session.commit()
                flash(translate('Catálogo actualizado.'), 'success')
                return redirect(url_for('compliance.catalogo', g=_grupo_redirect(tipo)))
            elif accion == 'eliminar':
                tipo = DocumentoTipo.query.get_or_404(int(request.form.get('tipo_id')))
                grupo = _grupo_redirect(tipo)
                eliminar_tipo(tipo)
                db.session.commit()
                flash(translate('Plantilla eliminada.'), 'success')
                return redirect(url_for('compliance.catalogo', g=grupo))
            db.session.commit()
            flash(translate('Catálogo actualizado.'), 'success')
        except Exception as exc:
            db.session.rollback()
            flash(str(exc), 'danger')
        return redirect(url_for('compliance.catalogo'))
    tipos = DocumentoTipo.query.order_by(DocumentoTipo.ambito, DocumentoTipo.orden, DocumentoTipo.nombre).all()
    return render_template('compliance/catalogo.html', tipos=tipos)


@compliance_bp.route('/documentacion/empresa/<int:company_id>', methods=['GET', 'POST'])
@login_required
@permission_required('documentacion', 'r')
def documentacion_empresa(company_id):
    _exigir(has_documentacion)
    company = Company.query.get_or_404(company_id)
    if request.method == 'POST':
        if not current_user_can_write():
            abort(403)
        return _post_empresa(company)
    # Altas sin empresa: engancharlas a la interna al abrir su ficha de docs.
    if company.is_internal:
        huerfanos = User.query.filter(
            User.company_id.is_(None),
            User.is_deleted.is_(False),
            db.or_(User.hiring_state.isnot(None), User.fecha_inicio.isnot(None)),
        ).all()
        fixed = False
        for u in huerfanos:
            if asegurar_empresa_interna(u):
                fixed = True
        if fixed:
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
    empleados = User.query.filter_by(company_id=company.id, is_deleted=False).order_by(User.name).all()
    resumen_empleados = []
    resumen_contratacion = []
    for u in empleados:
        filas_u = filas_persona(u)
        item = {
            'user': u,
            **resumir(filas_u),
            'filas': [f for f in filas_u if not f['tipo'].es_certificacion],
            'hiring': bool(u.hiring_state),
            'hiring_state': u.hiring_state,
        }
        if u.hiring_state:
            # En alta: solo docs de contratación (fase 1/2) para la sección dedicada.
            docs_alta = filas_contratacion_activas(u)
            item_alta = {
                'user': u,
                **resumir(docs_alta),
                'filas': docs_alta,
                'hiring': True,
                'hiring_state': u.hiring_state,
            }
            resumen_contratacion.append(item_alta)
        else:
            resumen_empleados.append(item)
    plantilla_empleados = tipos_plantilla_empleados_empresa(company)
    filas = filas_empresa(company)
    # Solo plantillas creadas que esta empresa aún no tiene (ni genéricas ni extras).
    ids_ya_empresa = {
        f['tipo'].id for f in filas
        if f.get('tipo') is not None and not f['tipo'].es_certificacion
    }
    ids_ya_empleados = {t.id for t in plantilla_empleados}
    catalogo_empresa_add = (
        DocumentoTipo.query
        .filter(
            DocumentoTipo.activo.is_(True),
            DocumentoTipo.ambito == 'empresa',
            DocumentoTipo.es_certificacion.is_(False),
        )
        .order_by(DocumentoTipo.nombre)
        .all()
    )
    catalogo_empresa_add = [t for t in catalogo_empresa_add if t.id not in ids_ya_empresa]
    catalogo_empleado_add = (
        DocumentoTipo.query
        .filter(
            DocumentoTipo.activo.is_(True),
            DocumentoTipo.ambito == 'empleado',
        )
        .order_by(DocumentoTipo.nombre)
        .all()
    )
    catalogo_empleado_add = [t for t in catalogo_empleado_add if t.id not in ids_ya_empleados]
    return render_template(
        'compliance/documentacion_empresa.html',
        company=company,
        filas=filas,
        plantilla_empleados=plantilla_empleados,
        empleados=empleados,
        catalogo_empresa_add=catalogo_empresa_add,
        catalogo_empleado_add=catalogo_empleado_add,
        resumen_empleados=resumen_empleados,
        resumen_contratacion=resumen_contratacion,
        abrir_exigencias=request.args.get('panel') == 'exigencias',
        persona_abierta=request.args.get('persona'),
        tipo_recien_creado=tipo_recien_creado,
    )


def current_user_can_write() -> bool:
    from app.services.permission_service import user_can
    return user_can(current_user, 'documentacion', 'w')


def _post_empresa(company):
    accion = request.form.get('accion')
    persona_ret = (request.form.get('return_persona') or '').strip() or None
    try:
        if accion == 'excluir':
            excluir_generica(int(request.form['tipo_id']), company.id, request.form.get('destino') or 'empresa')
        elif accion == 'anadir':
            anadir_especifica(
                int(request.form['tipo_id']),
                company_id=company.id,
                destino=request.form.get('destino') or 'empresa',
            )
        elif accion == 'crear_y_anadir':
            destino = request.form.get('destino') or 'empresa'
            ambito = 'empresa' if destino == 'empresa' else 'empleado'
            tipo = crear_tipo(
                nombre=request.form.get('nombre'),
                categoria='General',
                ambito=ambito,
                audiencia='ambos',
                regla_renovacion='ninguna',
                obligatorio=True,
                activo=True,
                por_defecto=False,
            )
            anadir_especifica(tipo.id, company_id=company.id, destino=destino)
        elif accion == 'borrar_tipo':
            tipo = DocumentoTipo.query.get_or_404(int(request.form['tipo_id']))
            borrar_tipo_definitivo(tipo)
        elif accion == 'obligatorio':
            tipo = DocumentoTipo.query.get_or_404(int(request.form['tipo_id']))
            tipo.obligatorio = request.form.get('obligatorio') == 'on'
        elif accion == 'subir':
            from app.services.documentacion_service import subir_desde_request
            tipo = DocumentoTipo.query.get_or_404(int(request.form['tipo_id']))
            uid = request.form.get('user_id')
            subir_desde_request(
                tipo, request,
                company_id=None if uid else company.id,
                user_id=int(uid) if uid else None,
                actor_id=current_user.id,
            )
        elif accion == 'validar':
            aporte = DocumentoAporte.query.get_or_404(int(request.form['aporte_id']))
            caduca = _parse_fecha(request.form.get('caduca_el'))
            validar(
                aporte, actor_id=current_user.id, caduca_el=caduca,
                aceptado_caducado=request.form.get('aceptado_caducado') == 'on',
                nota=request.form.get('nota_oficina'),
            )
            if aporte.user_id and request.form.get('fecha_inicio'):
                persona = User.query.get(aporte.user_id)
                if persona is not None:
                    persona.fecha_inicio = _parse_fecha(request.form.get('fecha_inicio'))
                    refrescar_fase(persona)
        elif accion == 'rechazar':
            aporte = DocumentoAporte.query.get_or_404(int(request.form['aporte_id']))
            rechazar_doc(aporte, actor_id=current_user.id, nota=request.form.get('nota_oficina') or '')
        db.session.commit()
        flash(translate('Cambios guardados.'), 'success')
    except Exception as exc:
        db.session.rollback()
        flash(str(exc), 'danger')
    kwargs = {}
    if accion in ('excluir', 'anadir', 'obligatorio', 'crear_y_anadir', 'borrar_tipo'):
        kwargs['panel'] = 'exigencias'
    if persona_ret:
        kwargs['persona'] = persona_ret
    return redirect(url_for('compliance.documentacion_empresa', company_id=company.id, **kwargs))


@compliance_bp.route('/documentacion/empleado/<int:user_id>', methods=['GET', 'POST'])
@login_required
@permission_required('documentacion', 'r')
def documentacion_empleado(user_id):
    _exigir(has_documentacion)
    user = User.query.get_or_404(user_id)
    if request.method == 'POST':
        if not current_user_can_write():
            abort(403)
        return _post_persona(user, 'compliance.documentacion_empleado')
    from app.services.compliance_rules import email_es_real
    filas = filas_persona(user)
    ids_ya = {f['tipo'].id for f in filas}
    catalogo_add = [
        t for t in DocumentoTipo.query.filter_by(activo=True, ambito='empleado').order_by(DocumentoTipo.nombre).all()
        if t.id not in ids_ya
    ]
    return render_template(
        'compliance/documentacion_persona.html',
        sujeto=user,
        filas=filas,
        catalogo=catalogo_add,
        catalogo_persona_add=catalogo_add,
        puede_validar=current_user_can_write(),
        puede_gestionar=current_user_can_write(),
        puede_subir=current_user_can_write(),
        email_real=email_es_real(user.email),
        abrir_exigencias=request.args.get('panel') == 'exigencias',
    )


def _post_persona(user, endpoint):
    accion = request.form.get('accion')
    try:
        if accion == 'perfil':
            actualizar_perfil(user, request.form)
        elif accion == 'anadir':
            anadir_especifica(int(request.form['tipo_id']), user_id=user.id, destino='persona')
        elif accion == 'excluir':
            excluir_para_persona(int(request.form['tipo_id']), user.id)
        elif accion == 'subir':
            from app.services.documentacion_service import subir_desde_request
            tipo = DocumentoTipo.query.get_or_404(int(request.form['tipo_id']))
            subir_desde_request(
                tipo, request,
                user_id=user.id, actor_id=current_user.id,
            )
        elif accion == 'validar':
            aporte = DocumentoAporte.query.get_or_404(int(request.form['aporte_id']))
            caduca = _parse_fecha(request.form.get('caduca_el'))
            validar(
                aporte, actor_id=current_user.id, caduca_el=caduca,
                aceptado_caducado=request.form.get('aceptado_caducado') == 'on',
                nota=request.form.get('nota_oficina'),
            )
            if request.form.get('fecha_inicio'):
                user.fecha_inicio = _parse_fecha(request.form.get('fecha_inicio'))
            refrescar_fase(user)
        elif accion == 'rechazar':
            aporte = DocumentoAporte.query.get_or_404(int(request.form['aporte_id']))
            rechazar_doc(aporte, actor_id=current_user.id, nota=request.form.get('nota_oficina') or '')
        db.session.commit()
        flash(translate('Cambios guardados.'), 'success')
    except Exception as exc:
        db.session.rollback()
        flash(str(exc), 'danger')
    kwargs = {}
    if accion in ('excluir', 'anadir'):
        kwargs['panel'] = 'exigencias'
    return redirect(url_for(endpoint, user_id=user.id, **kwargs))


@compliance_bp.route('/documentacion/archivo/<int:aporte_id>')
@login_required
def archivo(aporte_id):
    from app.services.permission_service import user_can
    if not (
        user_can(current_user, 'documentacion', 'r')
        or user_can(current_user, 'contratacion', 'r')
    ):
        abort(403)
    _exigir(has_documentacion)
    aporte = DocumentoAporte.query.get_or_404(aporte_id)
    path = ruta_aporte(aporte)
    if not path:
        abort(404)
    return send_file(path, as_attachment=False, download_name=aporte.nombre_original or 'documento')


@compliance_bp.route('/certificacion', methods=['GET', 'POST'])
@login_required
@permission_required('certificacion', 'r')
def certificacion_lista():
    """Entrada: empresas u obras del alcance; precio plataforma; mes o rango."""
    _exigir(has_certificacion)
    anio, mes, desde, hasta = _periodo()
    vista = (request.args.get('vista') or request.form.get('vista') or 'empresas').strip().lower()
    if vista not in ('empresas', 'obras'):
        vista = 'empresas'

    if request.method == 'POST':
        from app.services.permission_service import user_can
        if request.form.get('accion') == 'precio_plataforma':
            if not user_can(current_user, 'certificacion', 'w'):
                abort(403)
            try:
                guardar_precio_plataforma(request.form.get('precio_hora'))
                precio = precio_plataforma()
                n = aplicar_precio_plataforma_herederos(anio=anio, mes=mes, precio=precio)
                db.session.commit()
                if n:
                    flash(translate('Precio plataforma guardado y aplicado a empresas sin precio propio.'), 'success')
                else:
                    flash(translate('Precio plataforma guardado.'), 'success')
            except Exception as exc:
                db.session.rollback()
                flash(str(exc), 'danger')
            return redirect(url_for(
                'compliance.certificacion_lista',
                anio=anio, mes=mes, vista=vista,
                desde=desde.isoformat() if desde else None,
                hasta=hasta.isoformat() if hasta else None,
            ))

    if vista == 'obras':
        filas = panel_certificacion_obras(
            current_user, anio=anio, mes=mes, desde=desde, hasta=hasta,
        )
        entrantes = 0
    else:
        filas = panel_certificacion_oficina(
            current_user, anio=anio, mes=mes, desde=desde, hasta=hasta,
        )
        entrantes = sum(1 for f in filas if f['requiere_accion'])

    return render_template(
        'compliance/certificacion_lista.html',
        filas=filas,
        vista=vista,
        anio=anio,
        mes=mes,
        desde=desde,
        hasta=hasta,
        prev=_shift(anio, mes, -1),
        next=_shift(anio, mes, 1),
        entrantes=entrantes,
        precio_plataforma=precio_plataforma(),
    )


@compliance_bp.route('/certificacion/obra/<int:obra_id>')
@login_required
@permission_required('certificacion', 'r')
def certificacion_obra(obra_id):
    _exigir(has_certificacion)
    anio, mes, desde, hasta = _periodo()
    agrupacion = (request.args.get('agrupacion') or 'empresa').strip().lower()
    if agrupacion not in ('empresa', 'fecha'):
        agrupacion = 'empresa'
    detalle = detalle_certificacion_obra(
        current_user, obra_id, anio=anio, mes=mes, desde=desde, hasta=hasta,
    )
    if not detalle:
        abort(404)
    db.session.commit()
    return render_template(
        'compliance/certificacion_obra.html',
        detalle=detalle,
        agrupacion=agrupacion,
        anio=anio,
        mes=mes,
        desde=desde,
        hasta=hasta,
        prev=_shift(anio, mes, -1),
        next=_shift(anio, mes, 1),
        precio_plataforma=precio_plataforma(),
    )


@compliance_bp.route('/certificacion/empresa/<int:company_id>')
@login_required
@permission_required('certificacion', 'r')
def certificacion_empresa(company_id):
    """Hub: obras del mes para esta subcontrata."""
    _exigir(has_certificacion)
    company = Company.query.get_or_404(company_id)
    anio, mes, desde, hasta = _periodo()
    from app.services.panel_scope_service import certificacion_obra_ids
    allowed = certificacion_obra_ids(current_user)
    if allowed is not None:
        filas_alcance = panel_certificacion_oficina(
            current_user, anio=anio, mes=mes, desde=desde, hasta=hasta,
        )
        if company.id not in {f['company'].id for f in filas_alcance}:
            abort(404)
    filas = panel_certificacion_empresa_obras(
        current_user, company.id, anio=anio, mes=mes, desde=desde, hasta=hasta,
    )
    db.session.commit()
    return render_template(
        'compliance/certificacion_empresa.html',
        company=company,
        filas=filas,
        anio=anio,
        mes=mes,
        desde=desde,
        hasta=hasta,
        prev=_shift(anio, mes, -1),
        next=_shift(anio, mes, 1),
        precio=precio_empresa(company),
    )


@compliance_bp.route(
    '/certificacion/empresa/<int:company_id>/obra/<int:obra_id>',
    methods=['GET', 'POST'],
)
@login_required
@permission_required('certificacion', 'r')
def certificacion_empresa_obra(company_id, obra_id):
    _exigir(has_certificacion)
    company = Company.query.get_or_404(company_id)
    anio, mes, desde, hasta = _periodo()
    from app.services.panel_scope_service import certificacion_obra_ids
    from app.models import Obra
    allowed = certificacion_obra_ids(current_user)
    if allowed is not None and obra_id not in allowed:
        abort(404)
    obra = Obra.query.get_or_404(obra_id)
    if request.method == 'POST':
        from app.services.permission_service import user_can
        if not user_can(current_user, 'certificacion', 'w'):
            abort(403)
        return _post_cert(
            company, anio, mes, obra_id,
            direccion_propia=DIR_EMP,
            endpoint='compliance.certificacion_empresa_obra',
        )
    sub, emp = sincronizar(company, anio, mes, obra_id)
    db.session.commit()
    return _render_cert(
        company, anio, mes, obra=obra, propia=emp, ajena=sub, vista_subcontrata=False,
        desde=desde, hasta=hasta,
    )


def _grupos_como_obra(obra, fechas_o_vacio, prop):
    if not fechas_o_vacio and not (prop and prop.lineas):
        return []
    tot = totales(prop) if prop else {'horas': 0, 'importe': 0}
    return [{
        'obra': obra,
        'fechas': fechas_o_vacio or [],
        'horas': tot['horas'],
        'importe': tot['importe'],
    }]


def _grupos_como_persona(personas):
    """Convierte agrupación por persona a la forma obra→fechas→lineas de la plantilla."""
    from types import SimpleNamespace
    out = []
    for p in personas or []:
        user = p.get('user')
        nombre = f"{(user.name or '')} {(user.lastname or '')}".strip() if user else translate('Persona')
        fechas = []
        for f in p.get('fechas') or []:
            fechas.append({
                'fecha': f['fecha'],
                'lineas': [{'linea': f['linea'], 'importe': f['importe']}],
                'horas': f.get('horas') or 0,
                'importe': f.get('importe') or 0,
            })
        out.append({
            'obra': SimpleNamespace(nombre=nombre),
            'fechas': fechas,
            'horas': p.get('horas') or 0,
            'importe': p.get('importe') or 0,
        })
    return out


def _render_cert(
    company, anio, mes, *, obra, propia, ajena, vista_subcontrata,
    desde=None, hasta=None, modo_vista=None,
):
    filtro_desde, filtro_hasta = (None, None)
    if vista_subcontrata:
        modo = (modo_vista or request.args.get('modo') or 'fecha').strip().lower()
        if modo not in ('fecha', 'persona'):
            modo = 'fecha'
        if modo == 'persona':
            g_propia = _grupos_como_persona(agrupar_por_persona(propia))
            g_ajena = _grupos_como_persona(agrupar_por_persona(ajena)) if ajena else []
        else:
            g_propia = _grupos_como_obra(obra, agrupar_por_fecha(propia), propia)
            g_ajena = _grupos_como_obra(obra, agrupar_por_fecha(ajena), ajena) if ajena else []
    else:
        modo = None
        g_propia = agrupar(propia)
        g_ajena = agrupar(ajena) if ajena else []
        filtro_desde, filtro_hasta = interseccion_mes(anio, mes, desde, hasta)
        if desde or hasta:
            if filtro_desde is None:
                g_propia, g_ajena = [], []
            else:
                g_propia = filtrar_grupos_por_rango(g_propia, filtro_desde, filtro_hasta)
                g_ajena = filtrar_grupos_por_rango(g_ajena, filtro_desde, filtro_hasta)

    ajena_visible = bool(ajena and ajena.estado in ('enviada', 'aceptada'))
    if not ajena_visible:
        g_ajena = []

    mapa_propia = mapa_lineas_propuesta(propia)
    if not vista_subcontrata and g_ajena:
        enriquecer_grupos_ref_app(g_ajena, mapa_propia)

    scoped = bool(desde or hasta) and not vista_subcontrata
    falta_raw = (request.args.get('falta') or '').strip()
    falta_ids = set()
    for part in falta_raw.split(','):
        part = part.strip()
        if part.isdigit():
            falta_ids.add(int(part))

    # Pill de la propuesta ajena: "enviada" vista desde aquí = recibida
    if not ajena_visible:
        ajena_estado_ui = 'sin_movimiento'
    elif ajena.estado == 'enviada':
        ajena_estado_ui = 'recibida'
    elif ajena.estado == 'aceptada':
        ajena_estado_ui = 'aceptada'
    elif ajena.estado == 'cerrada':
        ajena_estado_ui = 'cerrada'
    else:
        ajena_estado_ui = ajena.estado

    bloqueado = periodo_bloqueado(company.id, anio, mes, obra.id)
    tot_propia = totales_grupos(g_propia) if scoped else totales(propia)
    aceptada_at = None
    for p in (propia, ajena):
        if p and p.estado == 'aceptada' and p.aceptada_at:
            aceptada_at = p.aceptada_at
            break

    return render_template(
        'compliance/certificacion.html',
        company=company,
        obra=obra,
        anio=anio,
        mes=mes,
        desde=desde,
        hasta=hasta,
        filtro_desde=filtro_desde,
        filtro_hasta=filtro_hasta,
        propia=propia,
        ajena=ajena,
        ajena_visible=ajena_visible,
        ajena_estado_ui=ajena_estado_ui,
        grupos_propia=g_propia,
        grupos_ajena=g_ajena,
        modo_vista=modo,
        totales_propia=tot_propia,
        totales_ajena=totales_grupos(g_ajena) if ajena_visible else {'horas': 0, 'importe': 0, 'filas': 0},
        estado=estado_propuesta(
            company.id, obra.id, anio, mes, vista_subcontrata=vista_subcontrata,
        ),
        bloqueado=bloqueado,
        aceptada_at=aceptada_at,
        precio=precio_empresa(company),
        vista_subcontrata=vista_subcontrata,
        falta_ids=falta_ids,
        borradores_odoo=0 if vista_subcontrata else contar_borradores_odoo(propia),
        mapa_propia=mapa_propia,
        meses_obra=panel_meses_obra(
            company.id, obra.id,
            anio_ref=anio, mes_ref=mes,
            vista_subcontrata=vista_subcontrata,
        ),
        actividad=resumen_actividad(
            propia, ajena,
            bloqueado=bloqueado,
            company=company,
            vista_subcontrata=vista_subcontrata,
        ),
        prev=_shift(anio, mes, -1),
        next=_shift(anio, mes, 1),
    )


def _cert_redirect(endpoint, company, anio, mes, obra_id, **extra):
    kwargs = {'anio': anio, 'mes': mes, 'obra_id': obra_id}
    if endpoint.startswith('compliance.'):
        kwargs['company_id'] = company.id
    for key, value in extra.items():
        if value is not None and value != '':
            kwargs[key] = value
    return redirect(url_for(endpoint, **kwargs))


def _post_cert(company, anio, mes, obra_id, *, direccion_propia, endpoint):
    sub, emp = sincronizar(company, anio, mes, obra_id)
    propia = emp if direccion_propia == DIR_EMP else sub
    ajena = sub if direccion_propia == DIR_EMP else emp
    accion = request.form.get('accion')
    restablecer_id = request.form.get('restablecer')
    guardar_fila_id = request.form.get('guardar_fila')
    desde_q = request.form.get('desde') or None
    hasta_q = request.form.get('hasta') or None
    modo_q = request.form.get('modo') or None
    try:
        if restablecer_id:
            try:
                lid = int(restablecer_id)
            except (TypeError, ValueError):
                raise ValueError(translate('Línea no válida.'))
            ln = next((x for x in propia.lineas if x.id == lid), None)
            if not ln:
                raise ValueError(translate('Línea no encontrada.'))
            restablecer_linea_desde_fichaje(ln)
            db.session.commit()
            if _cert_wants_json():
                return _json_linea(ln)
            flash(translate('Horas restablecidas desde el fichaje.'), 'success')
            return _cert_redirect(
                endpoint, company, anio, mes, obra_id, desde=desde_q, hasta=hasta_q, modo=modo_q,
            )
        if guardar_fila_id:
            try:
                lid = int(guardar_fila_id)
            except (TypeError, ValueError):
                raise ValueError(translate('Línea no válida.'))
            if not any(x.id == lid for x in propia.lineas):
                raise ValueError(translate('Línea no encontrada.'))
            _aplicar_lineas(propia, solo_id=lid)
            db.session.commit()
            ln = next(x for x in propia.lineas if x.id == lid)
            if _cert_wants_json():
                return _json_linea(ln)
            if lid in lineas_tramo_invalido(propia):
                flash(translate('La hora de fin tiene que ser posterior a la de inicio.'), 'danger')
                return _cert_redirect(
                    endpoint, company, anio, mes, obra_id,
                    desde=desde_q, hasta=hasta_q, modo=modo_q, falta=str(lid),
                )
            flash(translate('Fila guardada.'), 'success')
            return _cert_redirect(
                endpoint, company, anio, mes, obra_id, desde=desde_q, hasta=hasta_q, modo=modo_q,
            )
        if accion == 'precio':
            if direccion_propia != DIR_EMP:
                abort(403)
            precio = guardar_precio_empresa(company, request.form.get('precio_hora'))
            n = aplicar_precio_borrador(company, anio, mes, precio)
            db.session.commit()
            if n:
                flash(translate('Precio por defecto guardado y aplicado al borrador del mes.'), 'success')
            else:
                flash(translate('Precio por defecto guardado para esta empresa.'), 'success')
            return _cert_redirect(endpoint, company, anio, mes, obra_id)
        if accion == 'guardar':
            _aplicar_lineas(propia)
        elif accion == 'enviar':
            _aplicar_lineas(propia)
            db.session.flush()
            faltan = lineas_incompletas(propia)
            if faltan:
                db.session.commit()
                tramo_mal = set(lineas_tramo_invalido(propia))
                if tramo_mal & set(faltan):
                    flash(
                        translate(
                            'La hora de fin tiene que ser posterior a la de inicio. '
                            'Revisa las filas marcadas en rojo.'
                        ),
                        'danger',
                    )
                else:
                    flash(
                        translate('Rellena las horas (o precio) de las filas marcadas antes de enviar.'),
                        'danger',
                    )
                return _cert_redirect(
                    endpoint, company, anio, mes, obra_id,
                    desde=desde_q, hasta=hasta_q, modo=modo_q,
                    falta=','.join(str(x) for x in faltan),
                )
            enviar(propia, current_user.id)
        elif accion == 'desenviar':
            desenviar(propia, current_user.id)
        elif accion == 'aceptar':
            if not ajena or ajena.estado != 'enviada':
                raise ValueError(translate('No hay propuesta enviada que aceptar.'))
            aceptar(ajena, current_user.id)
        elif accion == 'rechazar':
            if not ajena or ajena.estado != 'enviada':
                raise ValueError(translate('No hay propuesta enviada que rechazar.'))
            notas = {}
            for key, value in request.form.items():
                if key.startswith('nota_disc_'):
                    try:
                        notas[int(key.replace('nota_disc_', ''))] = value or ''
                    except (TypeError, ValueError):
                        pass
            marcar_discrepancias(ajena, set(), notas)
            rechazar(ajena, current_user.id, request.form.get('comentario') or '')
        elif accion == 'marcar':
            if not ajena or ajena.estado != 'enviada':
                raise ValueError(translate('No hay propuesta enviada.'))
            notas = {}
            for key, value in request.form.items():
                if key.startswith('nota_disc_'):
                    try:
                        notas[int(key.replace('nota_disc_', ''))] = value or ''
                    except (TypeError, ValueError):
                        pass
            marcar_discrepancias(ajena, set(), notas)
        db.session.commit()
        flash(translate('Certificación actualizada.'), 'success')
    except Exception as exc:
        db.session.rollback()
        if _cert_wants_json() and (guardar_fila_id or restablecer_id):
            from flask import jsonify
            return jsonify({'ok': False, 'error': str(exc)}), 400
        flash(str(exc), 'danger')
    return _cert_redirect(
        endpoint, company, anio, mes, obra_id, desde=desde_q, hasta=hasta_q, modo=modo_q,
    )


def _cert_wants_json() -> bool:
    return (
        request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or request.accept_mimetypes.best == 'application/json'
    )


def _json_linea(ln):
    from flask import jsonify
    from app.services.compliance_rules import importe_linea
    tramo_mal = (
        ln.hora_inicio is not None
        and ln.hora_fin is not None
        and ln.horas is None
    )
    incompleta = ln.horas is None or ln.precio_hora is None
    imp = importe_linea(ln.horas, ln.precio_hora)
    error = None
    if tramo_mal:
        error = translate('La hora de fin tiene que ser posterior a la de inicio.')
    elif incompleta:
        error = translate('Faltan horas o precio.')
    return jsonify({
        'ok': not tramo_mal and not incompleta,
        'saved': True,
        'linea_id': int(ln.id),
        'horas': str(ln.horas) if ln.horas is not None else '',
        'hora_inicio': ln.hora_inicio.strftime('%H:%M') if ln.hora_inicio else '',
        'hora_fin': ln.hora_fin.strftime('%H:%M') if ln.hora_fin else '',
        'precio': str(ln.precio_hora) if ln.precio_hora is not None else '',
        'importe': f'{imp} €' if imp is not None else '—',
        'tramo_invalido': tramo_mal,
        'incompleta': incompleta,
        'editado': bool(ln.origen_horas and str(ln.origen_horas).startswith('manual')),
        'error': error,
    })


def _aplicar_lineas(prop, solo_id=None):
    for ln in list(prop.lineas):
        if solo_id is not None and ln.id != solo_id:
            continue
        pref = f'l{ln.id}_'
        if pref + 'horas' not in request.form and pref + 'inicio' not in request.form:
            continue
        horas_raw = request.form.get(pref + 'horas')
        inicio = parse_hora(request.form.get(pref + 'inicio'))
        fin = parse_hora(request.form.get(pref + 'fin'))
        precio = request.form.get(pref + 'precio')
        if inicio and fin:
            guardar_linea(ln, hora_inicio=inicio, hora_fin=fin, horas=None, precio=precio)
        elif (horas_raw or '').strip():
            guardar_linea(ln, hora_inicio=None, hora_fin=None, horas=horas_raw, precio=precio)
        else:
            guardar_linea(ln, hora_inicio=None, hora_fin=None, horas=None, precio=precio)


@compliance_bp.route('/certificacion/empresa/<int:company_id>/pdf/<int:propuesta_id>')
@login_required
@permission_required('certificacion', 'r')
def certificacion_pdf(company_id, propuesta_id):
    _exigir(has_certificacion)
    from app.models import CertificacionPropuesta
    prop = CertificacionPropuesta.query.get_or_404(propuesta_id)
    if prop.company_id != company_id:
        abort(404)
    pdf = pdf_propuesta(prop)
    if pdf:
        return Response(pdf, mimetype='application/pdf', headers={
            'Content-Disposition': f'attachment; filename={nombre_archivo_pdf(prop)}',
        })
    return Response(html_propuesta(prop), mimetype='text/html')


@compliance_bp.route('/contratacion')
@login_required
@permission_required('contratacion', 'r')
def contratacion_lista():
    _exigir(has_contratacion)
    personas = User.query.filter(
        User.hiring_state.isnot(None),
        User.is_deleted.is_(False),
    ).order_by(User.name).all()
    filas = []
    changed = False
    for persona in personas:
        if asegurar_empresa_interna(persona):
            changed = True
        docs = filas_contratacion_activas(persona)
        resumen = resumir(docs)
        antes = persona.hiring_state
        refrescar_fase(persona)
        if persona.hiring_state != antes:
            changed = True
            docs = filas_contratacion_activas(persona)
            resumen = resumir(docs)
        filas.append({
            'user': persona,
            'filas': docs,
            **resumen,
            'fase': 2 if persona.hiring_state == 'fase2' else 1,
        })
    # Cerradas: pasaron por el alta y ya tienen fecha de inicio.
    historial = (
        User.query.filter(
            User.hiring_state.is_(None),
            User.fecha_inicio.isnot(None),
            User.is_deleted.is_(False),
        )
        .order_by(User.fecha_inicio.desc(), User.name.asc())
        .limit(100)
        .all()
    )
    for persona in historial:
        if asegurar_empresa_interna(persona):
            changed = True
    if changed:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
    return render_template(
        'compliance/contratacion_lista.html',
        personas=filas,
        historial=historial,
    )


@compliance_bp.route('/contratacion/nueva', methods=['GET', 'POST'])
@login_required
@permission_required('contratacion', 'w')
def contratacion_nueva():
    _exigir(has_contratacion)
    if request.method == 'POST':
        try:
            from app.services.acceso_credenciales_service import url_credenciales
            from flask import g
            interna = empresa_interna()
            user = crear_contratacion(
                nombre=request.form.get('name'),
                apellido=request.form.get('lastname') or '',
                email=request.form.get('email') or '',
                role=request.form.get('role') or 'operario',
                company_id=interna.id if interna else None,
            )
            db.session.commit()
            enlace = url_credenciales(user, g.current_tenant)
            if email_es_real(user.email):
                from app.services.acceso_credenciales_service import enviar_enlace
                try:
                    enviar_enlace(user, g.current_tenant)
                    flash(translate('Enlace enviado. También puedes copiarlo: {url}', url=enlace), 'success')
                except Exception as exc:
                    flash(translate('{error} Enlace: {url}', error=exc, url=enlace), 'warning')
            else:
                flash(translate('Ficha creada. Copia este enlace (no hay correo): {url}', url=enlace), 'success')
            return redirect(url_for('compliance.contratacion_ficha', user_id=user.id))
        except Exception as exc:
            db.session.rollback()
            flash(str(exc), 'danger')
    interna = empresa_interna()
    return render_template(
        'compliance/contratacion_nueva.html',
        empresa_interna=interna,
    )


@compliance_bp.route('/contratacion/<int:user_id>', methods=['GET', 'POST'])
@login_required
@permission_required('contratacion', 'r')
def contratacion_ficha(user_id):
    _exigir(has_contratacion)
    user = User.query.get_or_404(user_id)
    if request.method == 'POST':
        from app.services.permission_service import user_can
        if not user_can(current_user, 'contratacion', 'w'):
            abort(403)
        accion = request.form.get('accion')
        wants_json = (
            request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            or 'application/json' in (request.headers.get('Accept') or '')
        )
        try:
            fase_antes = user.hiring_state
            if accion == 'perfil':
                actualizar_perfil(user, request.form)
            elif accion == 'enviar_enlace':
                from flask import g
                from app.services.acceso_credenciales_service import CredencialesError, enviar_enlace
                try:
                    enviar_enlace(user, g.current_tenant)
                    flash(translate('Enlace enviado a {email}.', email=user.email), 'success')
                except CredencialesError as exc:
                    flash(str(exc), 'warning')
                return redirect(url_for('compliance.contratacion_ficha', user_id=user.id))
            elif accion == 'validar':
                aporte = DocumentoAporte.query.get_or_404(int(request.form['aporte_id']))
                validar(
                    aporte, actor_id=current_user.id,
                    caduca_el=_parse_fecha(request.form.get('caduca_el')),
                    aceptado_caducado=request.form.get('aceptado_caducado') == 'on',
                    nota=request.form.get('nota_oficina'),
                )
                refrescar_fase(user)
            elif accion == 'validar_tipo':
                tipo_id = int(request.form['tipo_id'])
                pendientes = DocumentoAporte.query.filter_by(
                    user_id=user.id, tipo_id=tipo_id, vigente=True, estado='subido',
                ).all()
                if not pendientes:
                    raise ValueError(translate('No hay ficheros pendientes de validar.'))
                caduca = _parse_fecha(request.form.get('caduca_el'))
                for aporte in pendientes:
                    validar(
                        aporte, actor_id=current_user.id,
                        caduca_el=caduca,
                        aceptado_caducado=request.form.get('aceptado_caducado') == 'on',
                        nota=request.form.get('nota_oficina'),
                    )
                refrescar_fase(user)
            elif accion == 'rechazar':
                aporte = DocumentoAporte.query.get_or_404(int(request.form['aporte_id']))
                rechazar_doc(aporte, actor_id=current_user.id, nota=request.form.get('nota_oficina') or '')
            elif accion == 'finalizar':
                fecha = _parse_fecha(request.form.get('fecha_inicio'))
                finalizar(user, fecha_inicio=fecha)
            db.session.commit()
            if wants_json and accion in ('validar', 'validar_tipo', 'rechazar'):
                from flask import jsonify
                estado = _contratacion_ajax_estado(user, accion=accion, form=request.form)
                estado['reload'] = fase_antes != user.hiring_state
                return jsonify(estado)
            flash(translate('Guardado.'), 'success')
        except Exception as exc:
            db.session.rollback()
            if wants_json and accion in ('validar', 'validar_tipo', 'rechazar'):
                from flask import jsonify
                return jsonify({'ok': False, 'error': str(exc)}), 400
            flash(str(exc), 'danger')
        return redirect(url_for('compliance.contratacion_ficha', user_id=user.id))
    antes = user.hiring_state
    refrescar_fase(user)
    if user.hiring_state != antes:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
    from app.services.documentacion_service import puede_finalizar
    from app.utils.timezone_utils import today_local
    from flask import g
    from app.services.acceso_credenciales_service import url_credenciales
    enlace = ''
    try:
        enlace = url_credenciales(user, g.current_tenant)
    except Exception:
        enlace = ''
    todas = filas_contratacion(user, incluir_fase2_bloqueada=True)
    filas_fase1 = [f for f in todas if int(f['tipo'].fase_contratacion or 0) == 1]
    filas_fase2 = [f for f in todas if int(f['tipo'].fase_contratacion or 0) == 2]
    activas = filas_contratacion_activas(user)
    return render_template(
        'compliance/contratacion_ficha.html',
        sujeto=user,
        filas_fase1=filas_fase1,
        filas_fase2=filas_fase2,
        filas_activas=activas,
        fase1_completa=fase1_completa(user),
        puede_finalizar=puede_finalizar(user),
        enlace=enlace,
        email_real=email_es_real(user.email),
        hoy_iso=today_local().isoformat(),
    )


def _contratacion_ajax_estado(user, *, accion, form):
    from app.services.documentacion_service import puede_finalizar
    tipo_id = None
    if accion == 'validar_tipo':
        tipo_id = int(form.get('tipo_id'))
    elif form.get('aporte_id'):
        aporte = DocumentoAporte.query.get(int(form.get('aporte_id')))
        if aporte is not None:
            tipo_id = aporte.tipo_id
    filas = filas_persona(user)
    fila = next((f for f in filas if f['tipo'].id == tipo_id), None) if tipo_id else None
    activas = filas_contratacion_activas(user)
    prog = progreso_contratacion(activas)
    slots = []
    if fila:
        for slot in fila.get('slots') or []:
            ap = slot.get('aporte')
            slots.append({
                'codigo': slot.get('codigo'),
                'nombre': slot.get('nombre'),
                'aporte_id': ap.id if ap else None,
                'estado': ap.estado if ap else None,
                'nota_oficina': (ap.nota_oficina if ap else None) or '',
            })
        if not slots and fila.get('aporte'):
            ap = fila['aporte']
            slots.append({
                'codigo': '',
                'nombre': '',
                'aporte_id': ap.id,
                'estado': ap.estado,
                'nota_oficina': ap.nota_oficina or '',
            })
    labels = {
        'ok': translate('Validado'),
        'por_caducar': translate('Caduca pronto'),
        'pendiente_validar': translate('Por validar'),
        'rechazado': translate('Rechazado'),
        'falta': translate('Sin enviar'),
        'caducado': translate('Caducado'),
        'opcional_vacio': translate('Opcional'),
    }
    estado = fila['estado'] if fila else None
    return {
        'ok': True,
        'message': translate('Guardado.'),
        'tipo_id': tipo_id,
        'estado': estado,
        'estado_label': labels.get(estado, estado or ''),
        'slots': slots,
        'hiring_state': user.hiring_state,
        'hiring_label': (
            translate('Fase 2') if user.hiring_state == 'fase2'
            else (translate('Fase 1') if user.hiring_state else translate('Alta cerrada'))
        ),
        'reload': False,
        'puede_finalizar': bool(puede_finalizar(user)),
        'fecha_inicio': user.fecha_inicio.strftime('%d/%m/%Y') if user.fecha_inicio else None,
        'prog_n': prog['validados'] + prog['por_validar'],
        'prog_total': prog['total'],
        'validados': prog['validados'],
        'por_validar': prog['por_validar'],
        'por_completar': prog['por_completar'],
        'finalizar_url': url_for('compliance.contratacion_ficha', user_id=user.id),
        'finalizar_label': translate('Finalizar contratación'),
        'labels': {
            'validado': translate('Validado'),
            'por_validar': translate('Por validar'),
            'rechazado': translate('Rechazado'),
            'sin_fichero': translate('Sin fichero'),
        },
    }


def _parse_fecha(raw):
    raw = (raw or '').strip()
    if not raw:
        return None
    return datetime.strptime(raw, '%Y-%m-%d').date()


def _periodo():
    """Devuelve anio, mes, desde, hasta. Mes siempre; rango opcional (query/form)."""
    hoy = today_local()
    desde = _parse_fecha(request.args.get('desde') or request.form.get('desde'))
    hasta = _parse_fecha(request.args.get('hasta') or request.form.get('hasta'))
    try:
        anio = int(request.args.get('anio') or request.form.get('anio') or (desde.year if desde else hoy.year))
        mes = int(request.args.get('mes') or request.form.get('mes') or (desde.month if desde else hoy.month))
    except ValueError:
        anio, mes = hoy.year, hoy.month
    mes = min(max(mes, 1), 12)
    if desde and not hasta:
        hasta = desde
    if hasta and not desde:
        desde = hasta
    if desde and hasta and desde > hasta:
        desde, hasta = hasta, desde
    # Si el rango cae en otro mes, alinear anio/mes al inicio del rango
    if desde:
        anio, mes = desde.year, desde.month
    return anio, mes, desde, hasta


def _shift(anio, mes, delta):
    mes += delta
    if mes < 1:
        mes = 12
        anio -= 1
    elif mes > 12:
        mes = 1
        anio += 1
    return {'anio': anio, 'mes': mes}
