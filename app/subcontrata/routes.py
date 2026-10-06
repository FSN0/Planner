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
from app.services.subcontrata_portal_service import panel
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


@subcontrata_bp.route('/documentacion', methods=['GET', 'POST'])
def documentacion():
    if not has_documentacion() or not user_can(current_user, 'documentacion', 'r'):
        abort(403)
    company = _company()
    if request.method == 'POST':
        if not user_can(current_user, 'documentacion', 'w'):
            abort(403)
        try:
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
            flash(translate('Documento subido.'), 'success')
        except Exception as exc:
            db.session.rollback()
            flash(str(exc), 'danger')
        return redirect(url_for('subcontrata.documentacion'))
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


@subcontrata_bp.route('/certificacion')
def certificacion():
    if not has_certificacion() or not user_can(current_user, 'certificacion', 'r'):
        abort(403)
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
    sub, emp = sincronizar(company, anio, mes, obra_id)
    db.session.commit()
    return _render_cert(
        company, anio, mes, obra=obra, propia=sub, ajena=emp, vista_subcontrata=True,
    )


@subcontrata_bp.route('/certificacion/pdf/<int:propuesta_id>')
def certificacion_pdf(propuesta_id):
    if not has_certificacion() or not user_can(current_user, 'certificacion', 'r'):
        abort(403)
    from app.models import CertificacionPropuesta
    from app.services.certificacion_service import html_propuesta, nombre_archivo_pdf, pdf_propuesta
    from flask import Response
    prop = CertificacionPropuesta.query.get_or_404(propuesta_id)
    if prop.company_id != current_user.company_id:
        abort(403)
    pdf = pdf_propuesta(prop)
    if pdf:
        return Response(pdf, mimetype='application/pdf', headers={
            'Content-Disposition': f'attachment; filename={nombre_archivo_pdf(prop)}',
        })
    return Response(html_propuesta(prop), mimetype='text/html')
