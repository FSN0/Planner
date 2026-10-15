"""Portal del admin de subcontrata: su gente, su documentación, su certificación."""
from __future__ import annotations

from flask import abort, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from app import db
from app.models import ROLE_ADMIN_SUBCONTRATA, Company, DocumentoAporte, DocumentoTipo, Obra, User
from app.services.certificacion_service import (
    DIR_SUB,
    panel_certificacion_subcontrata_obras,
    sincronizar,
)
from app.services.documentacion_service import filas_empresa, filas_persona, resumir, ruta_aporte, subir
from app.services.i18n_service import translate
from app.services.permission_service import user_can
from app.services.subcontrata_portal_service import (
    ficha_trabajador,
    listado_personal,
    panel,
    usuario_de_company,
)
from app.services.tenant_modules import has_certificacion, has_documentacion, has_portal_subcontrata
from app.subcontrata import subcontrata_bp
from app.compliance.routes import _periodo, _post_cert, _render_cert, _shift


@subcontrata_bp.before_request
@login_required
def _solo_admin_subcontrata():
    if not has_portal_subcontrata():
        abort(404)
    if getattr(current_user, 'role', None) != ROLE_ADMIN_SUBCONTRATA:
        abort(403)
    if not current_user.company_id:
        abort(403)


def _company() -> Company:
    company = Company.query.get(current_user.company_id)
    if not company:
        abort(403)
    return company


@subcontrata_bp.route('/')
def inicio():
    return render_template('subcontrata/panel.html', company=_company(), datos=panel(_company()))


@subcontrata_bp.route('/personal')
def personal():
    """Equipo de la subcontrata: listado y acceso a calendarios."""
    company = _company()
    return render_template(
        'subcontrata/personal.html',
        company=company,
        filas=listado_personal(company),
    )


@subcontrata_bp.route('/personal/<int:user_id>/calendario')
def personal_calendario(user_id):
    """Ficha de un trabajador de la misma empresa: KPIs + calendario (solo lectura)."""
    company = _company()
    worker = usuario_de_company(company, user_id)
    if not worker:
        abort(403)
    return render_template(
        'subcontrata/personal_calendario.html',
        company=company,
        worker=worker,
        ficha=ficha_trabajador(company, worker),
    )


@subcontrata_bp.route('/calendario')
def calendario():
    """Calendario personal o de toda la empresa (solo lectura)."""
    if not user_can(current_user, 'operario_calendario', 'r'):
        abort(403)
    from app.models import Asignacion
    from app.utils.timezone_utils import today_local

    company = _company()
    tiene_asignaciones = (
        Asignacion.query.filter(
            Asignacion.user_id == current_user.id,
            Asignacion.fecha >= today_local(),
        ).limit(1).first()
        is not None
    )
    modo = (request.args.get('modo') or '').strip().lower()
    if modo not in ('personal', 'empresa'):
        modo = 'personal' if tiene_asignaciones else 'empresa'
    return render_template(
        'subcontrata/calendario.html',
        company=company,
        worker=current_user,
        modo=modo,
        tiene_asignaciones=tiene_asignaciones,
    )


def _post_documentacion(company: Company, *, redirect_endpoint: str, redirect_kwargs: dict | None = None):
    """Subir / archivar doc de empresa o persona de la subcontrata."""
    if not user_can(current_user, 'documentacion', 'w'):
        abort(403)
    redirect_kwargs = redirect_kwargs or {}
    try:
        accion = (request.form.get('accion') or 'subir').strip()
        if accion == 'eliminar_aporte':
            from app.services.documentacion_service import archivar_aporte
            aporte = DocumentoAporte.query.get_or_404(int(request.form['aporte_id']))
            if aporte.company_id and aporte.company_id != company.id:
                abort(403)
            if aporte.user_id:
                dueno = User.query.get(aporte.user_id)
                if not dueno or dueno.company_id != company.id:
                    abort(403)
            archivar_aporte(aporte)
            db.session.commit()
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                from flask import jsonify
                return jsonify(ok=True, message=translate('Documento archivado. Puedes subir otra versión.'))
            flash(translate('Documento archivado. Puedes subir otra versión.'), 'success')
        else:
            tipo = DocumentoTipo.query.get_or_404(int(request.form['tipo_id']))
            user_id = request.form.get('user_id')
            persona_id = int(user_id) if user_id else None
            if persona_id:
                persona = User.query.filter_by(
                    id=persona_id, company_id=company.id, is_deleted=False,
                ).first()
                if not persona:
                    abort(403)
            from app.services.documentacion_service import subir_desde_request
            subir_desde_request(
                tipo,
                request,
                company_id=None if persona_id else company.id,
                user_id=persona_id,
                actor_id=current_user.id,
            )
            db.session.commit()
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                from flask import jsonify
                return jsonify(ok=True, message=translate('Documento subido.'))
            flash(translate('Documento subido.'), 'success')
    except Exception as exc:
        db.session.rollback()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            from flask import jsonify
            return jsonify(ok=False, error=str(exc)), 400
        flash(str(exc), 'danger')
    return redirect(url_for(redirect_endpoint, **redirect_kwargs))


@subcontrata_bp.route('/documentacion', methods=['GET', 'POST'])
def documentacion():
    if not has_documentacion() or not user_can(current_user, 'documentacion', 'r'):
        abort(403)
    company = _company()
    if request.method == 'POST':
        # Si el upload es de una persona, volver a su ficha documental.
        uid = request.form.get('user_id')
        if uid:
            try:
                return _post_documentacion(
                    company,
                    redirect_endpoint='subcontrata.documentacion_persona',
                    redirect_kwargs={'user_id': int(uid)},
                )
            except (TypeError, ValueError):
                pass
        return _post_documentacion(company, redirect_endpoint='subcontrata.documentacion')
    empleados = User.query.filter_by(company_id=company.id, is_deleted=False).order_by(User.name).all()
    filas_empresa_vista = filas_empresa(company)
    empleados_vista = []
    for persona in empleados:
        filas = filas_persona(persona)
        empleados_vista.append({'user': persona, 'filas': filas, **resumir(filas)})
    return render_template(
        'subcontrata/documentacion.html',
        company=company,
        filas=filas_empresa_vista,
        empleados=empleados_vista,
        puede_subir=user_can(current_user, 'documentacion', 'w'),
    )


@subcontrata_bp.route('/documentacion/persona/<int:user_id>', methods=['GET', 'POST'])
def documentacion_persona(user_id):
    """Ficha documental de un operario de la subcontrata (subir / revisar)."""
    if not has_documentacion() or not user_can(current_user, 'documentacion', 'r'):
        abort(403)
    company = _company()
    persona = usuario_de_company(company, user_id)
    if not persona:
        abort(403)
    if request.method == 'POST':
        return _post_documentacion(
            company,
            redirect_endpoint='subcontrata.documentacion_persona',
            redirect_kwargs={'user_id': persona.id},
        )
    filas = filas_persona(persona)
    resumen = resumir(filas)
    return render_template(
        'subcontrata/documentacion_persona.html',
        company=company,
        sujeto=persona,
        filas=filas,
        resumen=resumen,
        puede_subir=user_can(current_user, 'documentacion', 'w'),
    )


@subcontrata_bp.route('/documentacion/archivo/<int:aporte_id>')
def archivo(aporte_id):
    if not has_documentacion() or not user_can(current_user, 'documentacion', 'r'):
        abort(403)
    aporte = DocumentoAporte.query.get_or_404(aporte_id)
    company = _company()
    if aporte.company_id and aporte.company_id != company.id:
        abort(403)
    if aporte.user_id:
        dueno = User.query.get(aporte.user_id)
        if not dueno or dueno.company_id != company.id:
            abort(403)
    path = ruta_aporte(aporte)
    if not path:
        abort(404)
    return send_file(path, as_attachment=False, download_name=aporte.nombre_original or 'documento')


@subcontrata_bp.route('/certificacion/avisos/quitar', methods=['POST'])
def certificacion_avisos_quitar():
    if not has_certificacion() or not user_can(current_user, 'certificacion', 'w'):
        abort(403)
    from app.services.certificacion_avisos_service import dismiss_aviso, undismiss_aviso
    from app.services.i18n_service import translate
    scope = (request.form.get('scope') or '').strip()
    accion = (request.form.get('accion') or 'quitar').strip().lower()
    try:
        anio = int(request.form.get('anio') or 0)
        mes = int(request.form.get('mes') or 0)
    except (TypeError, ValueError):
        anio, mes = 0, 0
    if not scope or not (1 <= mes <= 12) or anio < 2000:
        flash(translate('No se pudo actualizar el aviso.'), 'danger')
    elif accion == 'reactivar':
        undismiss_aviso(scope, anio, mes)
        flash(translate('Avisos de este mes reactivados.'), 'success')
    else:
        dismiss_aviso(scope, anio, mes)
        flash(translate('Avisos de este mes ocultos en este alcance.'), 'success')
    nxt = (request.form.get('next') or '').strip()
    if nxt.startswith('/'):
        return redirect(nxt)
    return redirect(url_for('subcontrata.certificacion', anio=anio or None, mes=mes or None))


@subcontrata_bp.route('/certificacion')
def certificacion():
    if not has_certificacion() or not user_can(current_user, 'certificacion', 'r'):
        abort(403)
    from app.compliance.routes import _cert_avisos_ctx
    from app.services.certificacion_avisos_service import scope_company
    company = _company()
    anio, mes, _desde, _hasta = _periodo()
    filas = panel_certificacion_subcontrata_obras(company, anio=anio, mes=mes)
    db.session.commit()
    return render_template(
        'subcontrata/certificacion_lista.html',
        company=company,
        filas=filas,
        anio=anio,
        mes=mes,
        prev=_shift(anio, mes, -1),
        next=_shift(anio, mes, 1),
        **_cert_avisos_ctx(
            scope_company(company.id, vista_subcontrata=True),
            anio=anio,
            mes=mes,
            company_id=company.id,
            vista_subcontrata=True,
        ),
    )


@subcontrata_bp.route('/certificacion/obra/<int:obra_id>', methods=['GET', 'POST'])
def certificacion_obra(obra_id):
    if not has_certificacion() or not user_can(current_user, 'certificacion', 'r'):
        abort(403)
    company = _company()
    anio, mes, _desde, _hasta = _periodo()
    obra = Obra.query.get_or_404(obra_id)
    if request.method == 'POST':
        if not user_can(current_user, 'certificacion', 'w'):
            abort(403)
        return _post_cert(
            company, anio, mes, obra_id,
            direccion_propia=DIR_SUB,
            endpoint='subcontrata.certificacion_obra',
        )
    from app.services.certificacion_service import cargar_par_certificacion
    from app import db
    forzar = str(request.args.get('refrescar') or '').strip().lower() in (
        '1', 'true', 'yes', 'si',
    )
    sub, emp, did_sync = cargar_par_certificacion(
        company, anio, mes, obra_id,
        forzar_sync=forzar,
        refrescar_precios=False,
    )
    if did_sync:
        db.session.commit()
    return _render_cert(
        company, anio, mes, obra=obra, propia=sub, ajena=emp, vista_subcontrata=True,
    )


@subcontrata_bp.route('/certificacion/pdf/<int:propuesta_id>')
def certificacion_pdf(propuesta_id):
    if not has_certificacion() or not user_can(current_user, 'certificacion', 'r'):
        abort(403)
    from io import BytesIO
    from flask import Response, flash, send_file
    from app.services.certificacion_service import (
        cargar_propuesta_para_pdf,
        html_propuesta,
        nombre_archivo_pdf,
        pdf_propuesta,
    )
    from app.services.i18n_service import translate

    from app.services.certificacion_service import pdf_cache_path_if_ready

    prop = cargar_propuesta_para_pdf(propuesta_id)
    if prop is None or prop.company_id != current_user.company_id:
        abort(403)
    # La subcontrata solo descarga el PDF cuando ya hay acuerdo (aceptada).
    if (prop.estado or '') != 'aceptada':
        abort(403)
    cached = pdf_cache_path_if_ready(prop)
    if cached:
        return send_file(
            cached,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=nombre_archivo_pdf(prop),
            max_age=0,
            conditional=False,
        )
    pdf = pdf_propuesta(prop)
    if pdf:
        return send_file(
            BytesIO(pdf),
            mimetype='application/pdf',
            as_attachment=True,
            download_name=nombre_archivo_pdf(prop),
            max_age=0,
        )
    flash(translate('No se pudo generar el PDF. Se muestra la vista HTML.'), 'warning')
    return Response(html_propuesta(prop), mimetype='text/html')
