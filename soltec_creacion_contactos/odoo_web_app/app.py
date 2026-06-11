import json
import os
import xmlrpc.client
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from dotenv import load_dotenv
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature

from audit_log import log_event, list_logs, action_label, ACTION_LABELS
from signaplan_client import authenticate_signaplan

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'odoo_contactos_internal_key_2024')
app.config['SESSION_COOKIE_NAME'] = 'odoo_contactos_session'
app.config['SESSION_COOKIE_SECURE'] = os.getenv('SESSION_COOKIE_SECURE', 'false').lower() in ('1', 'true', 'yes')
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

URL = os.getenv('ODOO_URL')
DB = os.getenv('ODOO_DB')
USER = os.getenv('ODOO_USER')
PASSWORD = os.getenv('ODOO_PASSWORD')
CAMPO_CODIGO_EMPLEADO = 'attendance_password'
SSO_SECRET = os.getenv('SSO_SECRET_KEY', 'soltec_master_key_998877')
TENANT_DISPLAY = os.getenv('SIGNAPLAN_TENANT_NAME', 'Soltec')


def conectar_odoo():
    common = xmlrpc.client.ServerProxy(f'{URL}/xmlrpc/2/common')
    uid = common.authenticate(DB, USER, PASSWORD, {})
    if not uid:
        raise Exception('Error de autenticación con Odoo.')
    models = xmlrpc.client.ServerProxy(f'{URL}/xmlrpc/2/object')
    return uid, models


def _client_ip():
    return request.headers.get('X-Forwarded-For', request.remote_addr)


def is_admin():
    return session.get('is_admin') is True


def _set_user_session(user, auth_method):
    session['user_id'] = user.get('id')
    session['user_name'] = user.get('name') or user.get('email') or 'Usuario'
    session['user_email'] = user.get('email', '')
    session['is_admin'] = user.get('role') == 'admin'
    session['auth_method'] = auth_method


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        if not is_admin():
            flash('Solo los administradores pueden ver el registro de actividad.', 'error')
            return redirect(url_for('dashboard'))
        return view(*args, **kwargs)
    return wrapped


def _format_log_details(raw):
    if not raw:
        return '—'
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return str(raw)
    if not isinstance(data, dict):
        return str(data)
    parts = []
    for key, val in data.items():
        label = key.replace('_', ' ')
        if isinstance(val, list):
            if val and isinstance(val[0], dict):
                parts.append(f'{label}: {len(val)} línea(s)')
            else:
                parts.append(f'{label}: {", ".join(str(x) for x in val)}')
        else:
            parts.append(f'{label}: {val}')
    return ' · '.join(parts)


def _formatea_fecha(f):
    if not f:
        return 'Sin fecha'
    partes = f.split('-')
    return f'{partes[2]}/{partes[1]}/{partes[0]}' if len(partes) == 3 else f


@app.route('/', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        email = (request.form.get('email') or '').strip()
        password = request.form.get('password') or ''

        try:
            ok, result = authenticate_signaplan(email, password)
            if ok:
                _set_user_session(result, 'signaplan')
                log_event(
                    result.get('id'), result.get('name'), 'login_signaplan',
                    {'email': result.get('email'), 'role': result.get('role')},
                    _client_ip(), 'signaplan',
                )
                return redirect(url_for('dashboard'))
            log_event(None, email or '—', 'login_failed', {'email': email}, _client_ip(), 'signaplan')
            flash(result or 'Credenciales inválidas', 'error')
        except ValueError as exc:
            flash(str(exc), 'error')
        except Exception as exc:
            flash(f'Error de autenticación: {exc}', 'error')

    return render_template('login.html', tenant_name=TENANT_DISPLAY)


@app.route('/sso_login')
def sso_login():
    token = request.args.get('token')
    if not token:
        flash('Acceso denegado: no se proporcionó token de seguridad.', 'error')
        return redirect(url_for('login'))

    serializer = URLSafeTimedSerializer(SSO_SECRET)
    try:
        payload = serializer.loads(token, max_age=300)
        _set_user_session({
            'id': payload.get('user_id'),
            'name': payload.get('name'),
            'email': payload.get('email', ''),
            'role': payload.get('role'),
        }, 'sso')
        log_event(
            payload.get('user_id'),
            session['user_name'],
            'login_sso',
            {'role': payload.get('role'), 'odoo_id': payload.get('odoo_id')},
            _client_ip(),
            'sso',
        )
        return redirect(url_for('dashboard'))
    except SignatureExpired:
        flash('El enlace de acceso ha caducado. Vuelve a abrir Alta Odoo desde SignaPlan.', 'error')
    except BadSignature:
        flash('Firma de seguridad inválida.', 'error')

    return redirect(url_for('login'))


@app.route('/logout')
def logout():
    if session.get('user_id'):
        log_event(
            session.get('user_id'),
            session.get('user_name', '—'),
            'logout',
            None,
            _client_ip(),
            session.get('auth_method'),
        )
    session.clear()
    return redirect(url_for('login'))


@app.route('/admin/logs')
@admin_required
def admin_logs():
    action = request.args.get('action', '').strip() or None
    q = request.args.get('q', '').strip() or None
    logs = list_logs(limit=300, action=action, q=q)
    for entry in logs:
        entry['action_label'] = action_label(entry['action'])
        entry['details_display'] = _format_log_details(entry.get('details'))
    return render_template(
        'logs.html',
        logs=logs,
        usuario=session.get('user_name'),
        is_admin=True,
        filter_action=action or '',
        filter_q=q or '',
        action_labels=ACTION_LABELS,
    )


@app.route('/api/empresa_data/<int:empresa_id>')
@login_required
def api_empresa_data(empresa_id):
    try:
        uid, models = conectar_odoo()
        contratos = models.execute_kw(
            DB, uid, PASSWORD, 'partner.attendance.contract', 'search_read',
            [[('partner_id', '=', empresa_id)]], {'fields': ['hourly_rate']},
        )
        precio_medio = 0.0
        if contratos:
            tarifas = [c['hourly_rate'] for c in contratos if c.get('hourly_rate')]
            if tarifas:
                precio_medio = round(sum(tarifas) / len(tarifas), 2)

        empleados = models.execute_kw(
            DB, uid, PASSWORD, 'res.partner', 'search_read',
            [[('parent_id', '=', empresa_id), ('is_company', '=', False)]],
            {'fields': ['id', 'name'], 'order': 'name asc'},
        )
        return jsonify({'success': True, 'precio_medio': precio_medio, 'empleados': empleados})
    except Exception as exc:
        return jsonify({'success': False, 'error': str(exc)})


@app.route('/dashboard', methods=['GET', 'POST'])
@login_required
def dashboard():
    empresas, obras = [], []

    try:
        uid, models = conectar_odoo()

        if request.method == 'POST':
            action = request.form.get('action')

            if action == 'alta_trabajador':
                empresa_id_form = request.form.get('empresa_id')
                nueva_empresa_nombre = (request.form.get('nueva_empresa_nombre') or '').strip()
                cif_empresa = (request.form.get('cif_empresa') or '').strip()
                nombre_trabajador = (request.form.get('nombre_trabajador') or '').strip()
                dni = (request.form.get('dni') or '').strip()

                tag_records = models.execute_kw(
                    DB, uid, PASSWORD, 'res.partner.category', 'search_read',
                    [[('name', '=', 'SUBCONTRATA')]], {'fields': ['id'], 'limit': 1},
                )
                tag_id = tag_records[0]['id'] if tag_records else models.execute_kw(
                    DB, uid, PASSWORD, 'res.partner.category', 'create', [{'name': 'SUBCONTRATA'}],
                )

                empresa_nombre_log = nueva_empresa_nombre
                if nueva_empresa_nombre:
                    existente = models.execute_kw(
                        DB, uid, PASSWORD, 'res.partner', 'search',
                        [[('name', 'ilike', nueva_empresa_nombre), ('is_company', '=', True)]], {'limit': 1},
                    )
                    if existente:
                        empresa_id = existente[0]
                        datos_update = {'category_id': [(4, tag_id)]}
                        if cif_empresa:
                            datos_update['vat'] = cif_empresa
                        models.execute_kw(DB, uid, PASSWORD, 'res.partner', 'write', [[empresa_id], datos_update])
                    else:
                        datos_creacion = {
                            'name': nueva_empresa_nombre, 'is_company': True,
                            'category_id': [(6, 0, [tag_id])],
                        }
                        if cif_empresa:
                            datos_creacion['vat'] = cif_empresa
                        empresa_id = models.execute_kw(DB, uid, PASSWORD, 'res.partner', 'create', [datos_creacion])
                else:
                    empresa_id = int(empresa_id_form)
                    emp_data = models.execute_kw(
                        DB, uid, PASSWORD, 'res.partner', 'read', [[empresa_id], ['name']],
                    )
                    empresa_nombre_log = emp_data[0]['name'] if emp_data else str(empresa_id)

                models.execute_kw(DB, uid, PASSWORD, 'res.partner', 'create', [{
                    'name': nombre_trabajador,
                    'is_company': False,
                    'parent_id': empresa_id,
                    'type': 'contact',
                    CAMPO_CODIGO_EMPLEADO: dni,
                }])
                log_event(
                    session.get('user_id'), session.get('user_name'), 'alta_trabajador',
                    {
                        'trabajador': nombre_trabajador,
                        'dni': dni,
                        'empresa': empresa_nombre_log,
                        'empresa_id': empresa_id,
                        'nueva_empresa': bool(nueva_empresa_nombre),
                    },
                    _client_ip(), session.get('auth_method'),
                )
                flash(f'{nombre_trabajador} dado de alta correctamente en Odoo.', 'success')

            elif action == 'alta_contrato':
                empresa_id = int(request.form.get('empresa_contrato_id'))
                obra_id = int(request.form.get('obra_id'))
                coste_hora = float(request.form.get('coste_hora'))
                fecha_inicio = request.form.get('fecha_inicio')
                fecha_fin = request.form.get('fecha_fin')

                dominio_solapamiento = [
                    ('partner_id', '=', empresa_id),
                    ('project_id', '=', obra_id),
                    ('date_start', '<=', fecha_fin),
                    '|', ('date_end', '=', False), ('date_end', '>=', fecha_inicio),
                ]
                contratos_solapados = models.execute_kw(
                    DB, uid, PASSWORD, 'partner.attendance.contract', 'search_read',
                    [dominio_solapamiento],
                    {'fields': ['id', 'name', 'date_start', 'date_end'], 'limit': 1},
                )
                if contratos_solapados:
                    c = contratos_solapados[0]
                    c_name = c.get('name', 'Sin Referencia')
                    c_start = _formatea_fecha(c.get('date_start'))
                    c_end = _formatea_fecha(c.get('date_end')) if c.get('date_end') else 'Indefinida'
                    flash(
                        f"Ya existe el contrato '{c_name}' para esta subcontrata y obra "
                        f"(vigente desde {c_start} hasta {c_end}). Cambia las fechas.",
                        'error',
                    )
                    return redirect(url_for('dashboard'))

                contract_vals = {
                    'partner_id': empresa_id,
                    'project_id': obra_id,
                    'hourly_rate': coste_hora,
                    'date_start': fecha_inicio,
                    'date_end': fecha_fin,
                }
                operario_ids = request.form.getlist('operario_id[]')
                operario_costes = request.form.getlist('operario_coste[]')
                lines = []
                lineas_log = []
                for op_id, op_coste in zip(operario_ids, operario_costes):
                    if op_id and op_coste:
                        lines.append((0, 0, {'partner_id': int(op_id), 'hourly_rate': float(op_coste)}))
                        lineas_log.append({'operario_id': int(op_id), 'tarifa': float(op_coste)})
                if lines:
                    contract_vals['lines_ids'] = lines

                contract_id = models.execute_kw(
                    DB, uid, PASSWORD, 'partner.attendance.contract', 'create', [contract_vals],
                )
                for state in ('open', 'running', 'active', 'confirmed'):
                    try:
                        models.execute_kw(DB, uid, PASSWORD, 'partner.attendance.contract', 'write', [[contract_id], {'state': state}])
                    except Exception:
                        pass
                for method in ('action_confirm', 'button_confirm', 'action_open', 'button_open', 'state_open'):
                    try:
                        models.execute_kw(DB, uid, PASSWORD, 'partner.attendance.contract', method, [[contract_id]])
                    except Exception:
                        pass

                emp_name = models.execute_kw(DB, uid, PASSWORD, 'res.partner', 'read', [[empresa_id], ['name']])
                obra_name = models.execute_kw(DB, uid, PASSWORD, 'bim.project', 'read', [[obra_id], ['name']])
                log_event(
                    session.get('user_id'), session.get('user_name'), 'alta_contrato',
                    {
                        'contract_id': contract_id,
                        'empresa': emp_name[0]['name'] if emp_name else empresa_id,
                        'obra': obra_name[0]['name'] if obra_name else obra_id,
                        'fecha_inicio': fecha_inicio,
                        'fecha_fin': fecha_fin,
                        'coste_hora': coste_hora,
                        'lineas_operarios': lineas_log,
                    },
                    _client_ip(), session.get('auth_method'),
                )
                flash('Contrato de asistencia generado y activado en Odoo.', 'success')

            return redirect(url_for('dashboard'))

        empresas = models.execute_kw(
            DB, uid, PASSWORD, 'res.partner', 'search_read',
            [[('is_company', '=', True)]], {'fields': ['id', 'name', 'vat'], 'order': 'name asc'},
        )
        obras = models.execute_kw(
            DB, uid, PASSWORD, 'bim.project', 'search_read',
            [[('active', '=', True)]], {'fields': ['id', 'name', 'nombre'], 'order': 'name asc'},
        )
    except Exception as exc:
        flash(f'Error Odoo: {exc}', 'error')
        empresas, obras = [], []

    return render_template(
        'dashboard.html',
        empresas=empresas,
        obras=obras,
        usuario=session.get('user_name'),
        is_admin=is_admin(),
        num_empresas=len(empresas),
        num_obras=len(obras),
    )


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5002)
