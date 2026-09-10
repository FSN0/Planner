import xmlrpc.client
import logging
import os
import re
from app import db
from app.models import Obra, User, Company, Vehiculo
from app.sync.adapters.base import BaseSyncAdapter
from app.services.config_service import get_tenant_config

logger = logging.getLogger(__name__)

class Adapter(BaseSyncAdapter):
    def __init__(self, tenant_id: int):
        super().__init__(tenant_id)
        
        self.url = (get_tenant_config('odoo_url', default=os.environ.get('ODOO_URL', '')) or '').strip()
        self.db_name = (get_tenant_config('odoo_db', default=os.environ.get('ODOO_DB', '')) or '').strip()
        self.user = (get_tenant_config('odoo_user', default=os.environ.get('ODOO_USER', '')) or '').strip()
        self.pwd = (get_tenant_config('odoo_password', desencriptar=True, default=os.environ.get('ODOO_PASSWORD', '')) or '').strip()

        if not self.url or not self.url.startswith('http'):
            raise ValueError(
                "No hay ODOO_URL configurada para este inquilino. "
                "Guarda la URL en Integración Odoo (debe empezar por https://)."
            )
            
        try:
            self.common = xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/common')
            self.uid = self.common.authenticate(self.db_name, self.user, self.pwd, {})
            if not self.uid:
                raise ValueError("Credenciales de Odoo incorrectas para este inquilino.")
            self.models = xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/object')
            self._emp_resolve_cache = {}
        except Exception as e:
            if "Credenciales de Odoo" in str(e):
                raise e
            raise ValueError(f"No se pudo establecer conexión XML-RPC: {str(e)}")

    def get_fichajes_diarios(self, fecha_str=None) -> list:
        import logging
        logger = logging.getLogger(__name__)
        from datetime import date
        
        if not fecha_str:
            fecha_str = date.today().strftime('%Y-%m-%d')
            
        domain = [('check_in', 'ilike', f'{fecha_str}%')]
        fichajes_estandarizados = []
        base_fields_int = ['employee_id', 'project_id', 'write_uid', 'check_in', 'check_out', 'note']
        base_fields_ext = ['partner_id', 'project_id', 'write_uid', 'check_in', 'check_out', 'note']

        # --- FICHAJES INTERNOS ---
        try:
            att_fields, metric_map = self._attendance_read_fields('hr.attendance', base_fields_int)
            att_int = self.models.execute_kw(
                self.db_name, self.uid, self.pwd, 
                'hr.attendance', 'search_read', 
                [domain], 
                {'fields': att_fields}
            )
            
            # Seguro contra respuestas malformadas de Odoo (típico de XML-RPC cuando falla)
            if not isinstance(att_int, list):
                logger.error(f"🚨 [Odoo Adapter - Tenant {self.tenant_id}] hr.attendance no devolvió una lista.")
                raise ConnectionError("Respuesta inválida de Odoo para fichajes internos.")

            for a in att_int:
                if a.get('employee_id'):
                    self._append_attendance_fichaje(
                        fichajes_estandarizados,
                        a,
                        actor_field='employee_id',
                        origen_modelo='hr.attendance',
                        fecha_str=fecha_str,
                        metric_map=metric_map,
                    )
        except Exception as e:
            logger.error(f"🚨 [Odoo Adapter - Tenant {self.tenant_id}] CRÍTICO: Fallo de red en hr.attendance. Error: {str(e)}")
            raise e  # <- CRÍTICO: Lanzamos el error hacia arriba para abortar la sincronización de este tenant

        # --- FICHAJES SUBCONTRATAS ---
        try:
            att_fields_ext, metric_map_ext = self._attendance_read_fields(
                'partner.attendance', base_fields_ext
            )
            att_ext = self.models.execute_kw(
                self.db_name, self.uid, self.pwd, 
                'partner.attendance', 'search_read', 
                [domain], 
                {'fields': att_fields_ext}
            )
            
            if not isinstance(att_ext, list):
                logger.error(f"🚨 [Odoo Adapter - Tenant {self.tenant_id}] partner.attendance no devolvió una lista.")
                raise ConnectionError("Respuesta inválida de Odoo para fichajes de subcontratas.")

            for a in att_ext:
                if a.get('partner_id'):
                    self._append_attendance_fichaje(
                        fichajes_estandarizados,
                        a,
                        actor_field='partner_id',
                        origen_modelo='partner.attendance',
                        fecha_str=fecha_str,
                        metric_map=metric_map_ext,
                    )
        except Exception as e:
            logger.error(f"🚨 [Odoo Adapter - Tenant {self.tenant_id}] CRÍTICO: Fallo de red en partner.attendance. Error: {str(e)}")
            raise e  # <- CRÍTICO: Lanzamos el error hacia arriba

        return fichajes_estandarizados

    def _attendance_metric_field_map(self, model_name):
        """Resuelve nombres técnicos de UD, MOD, Total HH y MOE en Odoo."""
        cache = getattr(self, '_attendance_metric_cache', None)
        if cache is None:
            self._attendance_metric_cache = {}
            cache = self._attendance_metric_cache
        if model_name in cache:
            return cache[model_name]

        available = self._odoo_fields_get(model_name) or {}

        def _pick(*names, labels=()):
            labels_norm = {str(l).strip().lower() for l in labels}
            for name in names:
                if name in available:
                    return name
            for fname, meta in available.items():
                label = (meta.get('string') or '').strip().lower()
                if label in labels_norm:
                    return fname
            return None

        mapping = {
            'odoo_ud': _pick('ud', 'x_studio_ud', 'x_ud', labels=('ud', 'u d')),
            'odoo_mod': _pick('mod', 'x_studio_mod', 'x_mod', labels=('mod',)),
            'odoo_total_hh': _pick(
                'total_hh', 'total_h_h', 'x_studio_total_hh', 'x_studio_total_h_h',
                labels=('total hh', 'total h h', 'total_hh', 'total h.h'),
            ),
            'odoo_moe': _pick('moe', 'x_studio_moe', 'x_moe', labels=('moe', 'm o e')),
        }
        cache[model_name] = mapping
        return mapping

    def _attendance_read_fields(self, model_name, base_fields):
        metric_map = self._attendance_metric_field_map(model_name)
        fields = list(base_fields)
        for odoo_field in metric_map.values():
            if odoo_field and odoo_field not in fields:
                fields.append(odoo_field)
        return fields, metric_map

    def _odoo_numeric(self, raw):
        if raw in (None, False, ''):
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    def _extract_attendance_metrics(self, row, metric_map):
        metrics = {}
        for target_key, odoo_field in (metric_map or {}).items():
            if not odoo_field:
                metrics[target_key] = None
                continue
            metrics[target_key] = self._odoo_numeric(row.get(odoo_field))
        return metrics

    def _append_attendance_fichaje(
        self,
        dest,
        row,
        *,
        actor_field,
        origen_modelo,
        fecha_str,
        metric_map,
    ):
        actor = row.get(actor_field)
        if not actor:
            return
        obra_id = row.get('project_id')[0] if row.get('project_id') else None
        modificado_por = row.get('write_uid')[1] if row.get('write_uid') else 'RRHH Odoo'
        item = {
            'registro_external_id': str(row['id']),
            'origen_modelo': origen_modelo,
            'empleado_external_id': str(actor[0]),
            'obra_external_id': str(obra_id) if obra_id else None,
            'fecha': fecha_str,
            'check_in': row.get('check_in'),
            'check_out': row.get('check_out'),
            'autor': modificado_por,
            'note': row.get('note') if row.get('note') not in (False, None, '') else None,
        }
        item.update(self._extract_attendance_metrics(row, metric_map))
        dest.append(item)

    def get_leaves(self, date_from=None, date_to=None) -> list:
        """Sincroniza hr.leave (todos los tipos: vacaciones, bajas, puentes, permisos…)."""
        import logging
        from datetime import date, timedelta

        logger = logging.getLogger(__name__)
        if not date_from:
            date_from = (date.today() - timedelta(days=30)).isoformat()
        if not date_to:
            date_to = (date.today() + timedelta(days=400)).isoformat()

        # Solo ausencias validadas en Odoo (aprobadas). Borradores/confirm no interesan.
        domain = [
            ('state', '=', 'validate'),
            '|',
            '&',
            ('request_date_from', '<=', date_to),
            ('request_date_to', '>=', date_from),
            '&',
            ('date_from', '<=', f'{date_to} 23:59:59'),
            ('date_to', '>=', f'{date_from} 00:00:00'),
        ]
        fields = [
            'id', 'name', 'state', 'employee_id', 'holiday_status_id',
            'request_date_from', 'request_date_to', 'date_from', 'date_to',
            'number_of_days',
        ]
        state_map = {
            'validate': 'aprobada',
        }

        try:
            rows = self.models.execute_kw(
                self.db_name, self.uid, self.pwd,
                'hr.leave', 'search_read',
                [domain],
                {'fields': fields, 'limit': 5000},
            )
        except Exception as e:
            logger.error(
                f"[Odoo Adapter - Tenant {self.tenant_id}] Fallo hr.leave: {e}"
            )
            raise

        if not isinstance(rows, list):
            raise ConnectionError("Respuesta inválida de Odoo para hr.leave.")

        leaves = []
        for row in rows:
            emp = row.get('employee_id')
            if not emp:
                continue
            htype = row.get('holiday_status_id')
            tipo_name = htype[1] if isinstance(htype, (list, tuple)) else (htype or 'Ausencia')
            tipo_id = str(htype[0]) if isinstance(htype, (list, tuple)) else None

            fecha_inicio = row.get('request_date_from')
            fecha_fin = row.get('request_date_to')
            if not fecha_inicio and row.get('date_from'):
                fecha_inicio = str(row['date_from'])[:10]
            if not fecha_fin and row.get('date_to'):
                fecha_fin = str(row['date_to'])[:10]
            if not fecha_inicio or not fecha_fin:
                continue

            leaves.append({
                'external_id': str(row['id']),
                'empleado_external_id': str(emp[0]),
                'tipo': tipo_name,
                'tipo_external_id': tipo_id,
                'estado': state_map.get(row.get('state'), 'aprobada'),
                'fecha_inicio': fecha_inicio,
                'fecha_fin': fecha_fin,
                'dias': row.get('number_of_days'),
                'descripcion': row.get('name') or None,
            })
        return leaves

    def _odoo_text(self, value):
        """Odoo XML-RPC usa False para char/date vacíos; no son strings."""
        if value in (None, False):
            return ''
        return str(value).strip()

    def _odoo_date(self, value):
        text = self._odoo_text(value)
        return text[:10] if text else None

    def _bim_ejecucion_domain(self):
        """Proyectos en ejecución. El id 6 es el histórico de Soltec; se resuelve por nombre."""
        state_id = 6
        try:
            rows = self.models.execute_kw(
                self.db_name, self.uid, self.pwd,
                'bim.project.state', 'search_read',
                [[('name', 'ilike', 'Ejecuci')]],
                {'fields': ['id', 'name'], 'limit': 5},
            )
            if isinstance(rows, list) and rows:
                state_id = rows[0]['id']
        except Exception as exc:
            logger.warning(
                "[Odoo Adapter - Tenant %s] No se pudo resolver bim.project.state: %s",
                self.tenant_id, exc,
            )
        return [['state_id', '=', state_id], ['active', '=', True]]

    def get_diff_obras(self):
        wanted = [
            'id', 'name', 'nombre', 'customer_id', 'date_ini',
            'nexecution_manager', 'encargado_obra', 'x_studio_encargado',
        ]
        available = self._odoo_fields_get('bim.project') or {}
        fields = [f for f in wanted if f == 'id' or f in available] or ['id', 'name']
        domain = self._bim_ejecucion_domain()
        try:
            odoo_obras = self.models.execute_kw(
                self.db_name, self.uid, self.pwd,
                'bim.project', 'search_read',
                [domain],
                {'fields': fields},
            )
        except Exception as exc:
            logger.error(
                "[Odoo Adapter - Tenant %s] search_read bim.project falló: %s",
                self.tenant_id, exc,
            )
            raise

        if not isinstance(odoo_obras, list):
            raise ConnectionError("Respuesta inválida de Odoo para bim.project.")

        diff = {'nuevas': [], 'actualizadas': [], 'sin_cambios': [], 'finalizadas': [], 'validadas_manual': []}
        active_odoo_ids = []

        for obra in odoo_obras:
            active_odoo_ids.append(obra['id'])
            raw_name = self._odoo_text(obra.get('name'))
            match = re.match(r'^([A-Z0-9]+/[0-9]+)', raw_name)
            if match:
                codigo_limpio = match.group(1)
            else:
                codigo_limpio = (raw_name.split(' ')[0] if raw_name else f"ODOO-{obra['id']}")[:20]

            nombre_limpio = self._odoo_text(obra.get('nombre')) or raw_name or codigo_limpio
            _, cliente_name = self._m2o_id_name(obra.get('customer_id'))
            cliente_name = self._odoo_text(cliente_name)

            jefe_field = obra.get('nexecution_manager')
            enc_field = obra.get('x_studio_encargado') or obra.get('encargado_obra')
            enc_as_partner = not bool(obra.get('x_studio_encargado'))
            jefe_id, warn_jefe = self._resolve_employee(jefe_field, as_partner=True)
            enc_id, warn_enc = self._resolve_employee(enc_field, as_partner=enc_as_partner)
            _, jefe_raw = self._m2o_id_name(jefe_field)
            _, enc_raw = self._m2o_id_name(enc_field)

            parsed_data = {
                'odoo_id': obra['id'],
                'codigo': codigo_limpio,
                'nombre': nombre_limpio,
                'cliente': cliente_name,
                'fecha_inicio': self._odoo_date(obra.get('date_ini')),
                'estado': 'Pendiente',
                'jefe_obra_id': jefe_id,
                'warn_jefe': warn_jefe,
                'encargado_id': enc_id,
                'warn_encargado': warn_enc,
                'jefe_odoo_raw': self._odoo_text(jefe_raw),
                'enc_odoo_raw': self._odoo_text(enc_raw),
                'cambios': {}
            }

            local_obra = Obra.query.filter(
                Obra.is_deleted.is_(False),
                (
                    (Obra.external_ids['odoo'].astext == str(obra['id'])) |
                    (Obra.codigo == codigo_limpio)
                ),
            ).first()

            if local_obra:
                parsed_data['local_id'] = local_obra.id
                es_validacion_manual = False

                if warn_jefe and local_obra.jefe_obra_id:
                    warn_jefe = False
                    parsed_data['warn_jefe'] = False
                    jefe_id = local_obra.jefe_obra_id
                    parsed_data['jefe_obra_id'] = jefe_id
                    es_validacion_manual = True

                if warn_enc and local_obra.encargado_id:
                    warn_enc = False
                    parsed_data['warn_encargado'] = False
                    enc_id = local_obra.encargado_id
                    parsed_data['encargado_id'] = enc_id
                    es_validacion_manual = True

                if local_obra.nombre != parsed_data['nombre']: parsed_data['cambios']['Nombre'] = f"{local_obra.nombre} ➔ {parsed_data['nombre']}"
                if (local_obra.descripcion or '') != parsed_data['cliente']: parsed_data['cambios']['Cliente'] = f"{local_obra.descripcion} ➔ {parsed_data['cliente']}"
                local_fecha = str(local_obra.fecha_inicio) if local_obra.fecha_inicio else None
                if local_fecha != parsed_data['fecha_inicio']: parsed_data['cambios']['Fecha'] = f"{local_fecha} ➔ {parsed_data['fecha_inicio']}"
                if local_obra.jefe_obra_id != jefe_id and not warn_jefe: parsed_data['cambios']['Jefe Obra'] = "Actualizado desde Odoo"
                if local_obra.encargado_id != enc_id and not warn_enc: parsed_data['cambios']['Encargado'] = "Actualizado desde Odoo"

                ext_ids = local_obra.external_ids or {}
                if parsed_data['cambios'] or not ext_ids.get('odoo') or warn_jefe or warn_enc:
                    diff['actualizadas'].append(parsed_data)
                elif es_validacion_manual:
                    diff['validadas_manual'].append(parsed_data)
                else:
                    diff['sin_cambios'].append(parsed_data)
            else:
                diff['nuevas'].append(parsed_data)

        obras_locales_activas = Obra.query.filter(
            Obra.is_deleted.is_(False),
            Obra.external_ids.has_key('odoo'),
            Obra.estado != 'Finalizada',
        ).all()
        for local in obras_locales_activas:
            odoo_id_local = (local.external_ids or {}).get('odoo')
            if odoo_id_local in (None, '', False):
                continue
            try:
                odoo_id_int = int(odoo_id_local)
            except (TypeError, ValueError):
                continue
            if odoo_id_int not in active_odoo_ids:
                diff['finalizadas'].append({
                    'local_id': local.id,
                    'odoo_id': odoo_id_int,
                    'codigo': local.codigo,
                    'nombre': local.nombre,
                    'estado_anterior': local.estado
                })

        return diff
    
    def _odoo_read_active_map(self, model, ids, fields=None):
        """Lee registros aunque estén archivados. Devuelve {id: active_bool}."""
        ids = [int(i) for i in ids if i is not None]
        if not ids:
            return {}
        wanted = fields or ['id', 'active', 'name']
        try:
            rows = self.models.execute_kw(
                self.db_name, self.uid, self.pwd,
                model, 'search_read',
                [[['id', 'in', ids]]],
                {'fields': wanted, 'context': {'active_test': False}},
            ) or []
        except Exception as exc:
            logger.warning(
                "[Odoo Adapter - Tenant %s] No se pudo leer %s inactivos: %s",
                self.tenant_id, model, exc,
            )
            return {}
        out = {}
        for row in rows:
            rid = row.get('id')
            if rid is None:
                continue
            out[int(rid)] = {
                'active': bool(row.get('active', True)),
                'name': row.get('name') or '',
            }
        return out

    def _users_with_odoo_link(self, *, externos=False):
        """Usuarios locales con external_ids.odoo (no soft-deleted)."""
        q = User.query.filter(
            User.is_deleted.is_(False),
            User.external_ids['odoo'].astext.isnot(None),
            User.external_ids['odoo'].astext != '',
        )
        users = q.all()
        result = []
        for u in users:
            is_ext = bool(u.company_rel and not u.company_rel.is_internal)
            if externos and is_ext:
                result.append(u)
            elif not externos and not is_ext:
                result.append(u)
        return result

    def _append_desactivados_empleados(self, diff, seen_odoo_ids, seen_local_ids=None):
        """
        Baja solo si el vínculo Odoo apunta a un hr.employee archivado.
        No usa «ausente del pull» (departamento, DNI vacío, id antiguo) ni
        «no encontrado» — eso daba falsos positivos (p.ej. ficha duplicada).
        """
        seen_local_ids = seen_local_ids or set()
        desactivados = []
        candidatos = [
            u for u in self._users_with_odoo_link(externos=False)
            if u.active
            and u.id not in seen_local_ids
            and str(u.external_ids.get('odoo')) not in seen_odoo_ids
        ]
        odoo_ids = []
        for u in candidatos:
            try:
                odoo_ids.append(int(u.external_ids.get('odoo')))
            except (TypeError, ValueError):
                continue
        active_map = self._odoo_read_active_map('hr.employee', odoo_ids)
        for u in candidatos:
            try:
                oid = int(u.external_ids.get('odoo'))
            except (TypeError, ValueError):
                continue
            info = active_map.get(oid)
            if info is None:
                logger.warning(
                    "[Odoo Adapter - Tenant %s] Empleado local %s (odoo_id=%s) "
                    "no aparece en hr.employee; no se da de baja.",
                    self.tenant_id, u.id, oid,
                )
                continue
            if info.get('active'):
                # Activo en Odoo pero fuera del filtro de departamentos → no baja.
                continue
            desactivados.append({
                'odoo_id': oid,
                'local_id': u.id,
                'name': u.name,
                'lastname': u.lastname or '',
                'dni': u.dni,
                'email': u.email,
                'role': u.role,
                'motivo': 'inactivo_odoo',
                'cambios': {
                    'Estado': 'Activo ➔ Baja (Odoo)',
                },
            })
        diff['desactivados'] = desactivados

    def get_diff_empleados(self):
        domain = [['active', '=', True]]
        fields = ['id', 'name', 'identification_id', 'work_email', 'job_title', 'department_id', 'job_id', 'barcode']
        try:
            odoo_emps = self.models.execute_kw(self.db_name, self.uid, self.pwd, 'hr.employee', 'search_read', [domain], {'fields': fields})
        except Exception:
            # Instancias sin barcode en hr.employee
            fields = ['id', 'name', 'identification_id', 'work_email', 'job_title', 'department_id', 'job_id']
            odoo_emps = self.models.execute_kw(self.db_name, self.uid, self.pwd, 'hr.employee', 'search_read', [domain], {'fields': fields})
        
        diff = {'nuevos': [], 'actualizados': [], 'sin_cambios': [], 'desactivados': [], 'omitidos': []}
        seen_odoo_ids = set()
        seen_local_ids = set()

        from app.services.sync_config_service import (
            SyncConfigService,
            default_empleados_departamento_map,
            resolve_departamento_role,
        )
        try:
            departamentos_map = SyncConfigService.get_empleados_departamento_map()
        except Exception:
            departamentos_map = default_empleados_departamento_map()

        for emp in odoo_emps:
            dni = emp.get('identification_id') or ''

            dep_raw = emp.get('department_id')
            department = dep_raw[1] if isinstance(dep_raw, (list, tuple)) and len(dep_raw) > 1 else ''

            if not dni:
                diff['omitidos'].append({
                    'odoo_id': emp['id'],
                    'nombre': emp.get('name') or '',
                    'departamento': department,
                    'motivo': 'Sin DNI en Odoo',
                })
                continue

            role = resolve_departamento_role(department, departamentos_map)
            if not role:
                diff['omitidos'].append({
                    'odoo_id': emp['id'],
                    'nombre': emp.get('name') or '',
                    'departamento': department or 'sin departamento',
                    'motivo': (
                        f'Departamento no autorizado: «{department or "sin departamento"}»'
                    ),
                })
                continue

            job_raw = emp.get('job_id')
            categoria = emp.get('job_title') or (job_raw[1] if job_raw else 'Sin definir')

            email = emp.get('work_email') or f"sin_email_{emp['id']}@local.tuappsaas.com"
            
            from app.services.personal_conciliation_service import (
                find_user_by_any_odoo,
                odoo_ids_for_user,
            )
            local_user = find_user_by_any_odoo(emp['id'], include_deleted=True)
            if local_user and local_user.is_deleted:
                local_user = None
            if not local_user and dni:
                local_user = User.query.filter(User.dni == dni).first()
            if not local_user and email:
                local_user = User.query.filter(User.email == email).first()
            
            parts = emp.get('name', '').split(' ', 1)
            name = parts[0]
            lastname = parts[1] if len(parts) > 1 else ''
            
            data = {
                'odoo_id': emp['id'],
                'name': name,
                'lastname': lastname,
                'dni': dni,
                'email': email,
                'role': role,
                'categoria_profesional': categoria,
                'barcode': (emp.get('barcode') or '') if emp.get('barcode') not in (False, None) else '',
                'cambios': {},
                'bloqueos': []
            }
            seen_odoo_ids.add(str(emp['id']))
            
            if local_user:
                data['local_id'] = local_user.id
                seen_local_ids.add(local_user.id)
                linked_oids = set(odoo_ids_for_user(local_user))
                for oid in linked_oids:
                    seen_odoo_ids.add(oid)
                stored_oid = str((local_user.external_ids or {}).get('odoo') or '')
                if stored_oid and stored_oid != str(emp['id']) and str(emp['id']) not in linked_oids:
                    data['cambios']['Id Odoo'] = f"{stored_oid} ➔ {emp['id']}"
                
                choque = User.query.filter(((User.dni == dni) | (User.email == email)), User.id != local_user.id).first()
                if choque:
                    motivo = "DNI" if choque.dni == dni else "Email"
                    valor = dni if choque.dni == dni else email
                    data['conflicto'] = {
                        'tipo': motivo,
                        'valor': valor,
                        'bloqueador': {'id': choque.id, 'nombre': f"{choque.name} {choque.lastname}"},
                        'actual': {'id': local_user.id, 'nombre': f"{local_user.name} {local_user.lastname}"}
                    }

                if local_user.name != name: data['cambios']['Nombre'] = f"{local_user.name} ➔ {name}"
                if (local_user.lastname or '') != lastname: data['cambios']['Apellidos'] = f"{local_user.lastname} ➔ {lastname}"
                if local_user.dni != dni: data['cambios']['DNI'] = f"{local_user.dni} ➔ {dni}"
                if local_user.email != email: data['cambios']['Email'] = f"{local_user.email} ➔ {email}"
                from app.services.user_role_sync_service import user_role_sync_locked
                role_sync_role = role
                office_roles = {'laboral', 'rrhh', 'admin'}
                odoo_field_roles = {'operario', 'jefe_obra'}
                if user_role_sync_locked(local_user):
                    role_sync_role = local_user.role
                elif local_user.role in office_roles and role in odoo_field_roles:
                    # p. ej. Lupe importada como operario pero ya es laboral en SignaPlan
                    role_sync_role = local_user.role
                elif local_user.role == 'jefe_obra' and role != 'admin':
                    # Un cambio de departamento en Odoo no le quita el rol de jefe aquí.
                    # Sí puede subir a admin si el departamento está mapeado así.
                    role_sync_role = local_user.role
                elif local_user.role != role:
                    data['cambios']['Rol'] = f"{local_user.role} ➔ {role}"
                data['role'] = role_sync_role
                if (local_user.categoria_profesional or '') != categoria: 
                    data['cambios']['Categoría'] = f"{local_user.categoria_profesional or 'Ninguna'} ➔ {categoria}"
                if not local_user.active:
                    data['cambios']['Estado'] = 'Inactivo ➔ Activo (reincorporación)'
                
                # Búsqueda correcta en JSONB
                if data['cambios'] or not local_user.external_ids.get('odoo'):
                    diff['actualizados'].append(data)
                else:
                    diff['sin_cambios'].append(data)
            else:
                diff['nuevos'].append(data)

        self._append_desactivados_empleados(diff, seen_odoo_ids, seen_local_ids)
        return diff

    def _resolve_employee(self, odoo_field, as_partner=True):
        if not odoo_field:
            return None, False

        emp_id, emp_name = self._m2o_id_name(odoo_field)
        if not emp_id and not emp_name:
            return None, False

        cache = getattr(self, '_emp_resolve_cache', None)
        if cache is None:
            self._emp_resolve_cache = {}
            cache = self._emp_resolve_cache
        cache_key = (bool(as_partner), emp_id, emp_name)
        if cache_key in cache:
            return cache[cache_key]

        result = self._resolve_employee_uncached(emp_id, emp_name, as_partner=as_partner)
        cache[cache_key] = result
        return result

    def _resolve_employee_uncached(self, emp_id, emp_name, as_partner=True):
        """Resuelve M2O Odoo → User local.

        - as_partner=True: el campo es un res.partner (p.ej. nexecution_manager).
          Primero mira vínculo directo local.external_ids.odoo == partner_id
          (conciliación contacto↔plantilla); luego intenta hr.employee ligado.
        - as_partner=False: el campo es hr.employee (o user_id).
        """
        # 1) Vínculo directo por ID de partner/empleado ya conciliado en plantilla
        if emp_id:
            from app.services.personal_conciliation_service import find_user_by_any_odoo
            local_direct = find_user_by_any_odoo(emp_id)
            if local_direct:
                return local_direct.id, False

        emp_fields = getattr(self, '_hr_employee_fields', None)
        if emp_fields is None:
            emp_fields = self._odoo_fields_get('hr.employee') or {}
            self._hr_employee_fields = emp_fields

        # Consultas en cascada (no un OR gigante): address_id es la sede de la
        # empresa y mezclarlo en el dominio devolvía empleados aleatorios.
        candidate_domains = []
        if emp_id:
            if as_partner:
                # Solo contactos reales del empleado. related_partner_id en Soltec
                # responde basura a search_read y no se puede usar.
                for fname in ('work_contact_id', 'user_partner_id'):
                    if fname in emp_fields:
                        candidate_domains.append([(fname, '=', emp_id)])
            else:
                candidate_domains.append([('id', '=', emp_id)])
                if 'user_id' in emp_fields:
                    candidate_domains.append([('user_id', '=', emp_id)])
        if emp_name:
            candidate_domains.append([('name', '=', emp_name)])

        emps = []
        for domain in candidate_domains:
            try:
                emps = self.models.execute_kw(
                    self.db_name, self.uid, self.pwd,
                    'hr.employee', 'search_read',
                    [domain],
                    {'fields': ['id', 'identification_id', 'name'], 'limit': 1},
                )
            except Exception as exc:
                logger.warning(
                    "[Odoo Adapter - Tenant %s] hr.employee lookup falló domain=%s: %s",
                    self.tenant_id, domain, exc,
                )
                emps = []
            if emps:
                break

        if emps:
            dni = emps[0].get('identification_id') or None
            if dni in (False, ''):
                dni = None
            real_id = emps[0]['id']

            from app.services.personal_conciliation_service import find_user_by_any_odoo
            local_user = find_user_by_any_odoo(real_id)
            if not local_user and dni:
                local_user = User.query.filter(
                    User.is_deleted.is_(False),
                    User.dni == dni,
                ).first()

            if local_user:
                return local_user.id, False

        return None, True
    
    def _append_desactivados_subcontratas(self, diff, seen_odoo_ids, seen_local_ids=None):
        seen_local_ids = seen_local_ids or set()
        desactivados = []
        candidatos = [
            u for u in self._users_with_odoo_link(externos=True)
            if u.active
            and u.id not in seen_local_ids
            and str(u.external_ids.get('odoo')) not in seen_odoo_ids
        ]
        odoo_ids = []
        for u in candidatos:
            try:
                odoo_ids.append(int(u.external_ids.get('odoo')))
            except (TypeError, ValueError):
                continue
        active_map = self._odoo_read_active_map('res.partner', odoo_ids)
        for u in candidatos:
            try:
                oid = int(u.external_ids.get('odoo'))
            except (TypeError, ValueError):
                continue
            info = active_map.get(oid)
            if info is None:
                logger.warning(
                    "[Odoo Adapter - Tenant %s] Externo local %s (odoo_id=%s) "
                    "no aparece en res.partner; no se da de baja.",
                    self.tenant_id, u.id, oid,
                )
                continue
            if info.get('active'):
                continue
            desactivados.append({
                'odoo_id': oid,
                'local_id': u.id,
                'name': u.name,
                'lastname': u.lastname or '',
                'dni': u.dni,
                'email': u.email,
                'role': u.role,
                'motivo': 'inactivo_odoo',
                'cambios': {
                    'Estado': 'Activo ➔ Baja (Odoo)',
                },
            })
        diff['empleados']['desactivados'] = desactivados

    def get_diff_subcontratas(self):
        domain_empresas = [
            ('is_company', '=', True),
            ('category_id.name', 'ilike', 'subcontrata')
        ]
        odoo_empresas = self.models.execute_kw(self.db_name, self.uid, self.pwd, 'res.partner', 'search_read', [domain_empresas], {'fields': ['id', 'name', 'vat']})
        
        diff = {
            'empresas': {'nuevas': [], 'actualizadas': []},
            'empleados': {'nuevos': [], 'actualizados': [], 'desactivados': []}
        }
        
        if not odoo_empresas:
            # Aun sin empresas en el pull, evaluar bajas de vinculados.
            self._append_desactivados_subcontratas(diff, set())
            return diff

        empresa_ids = [e['id'] for e in odoo_empresas]

        domain_contactos = [
            ('parent_id', 'in', empresa_ids),
            ('is_company', '=', False),
            ('active', '=', True)
        ]
        odoo_contactos = self.models.execute_kw(self.db_name, self.uid, self.pwd, 'res.partner', 'search_read', [domain_contactos], {'fields': ['id', 'name', 'email', 'vat', 'function', 'parent_id']})

        seen_odoo_ids = set()
        seen_local_ids = set()

        for o_emp in odoo_empresas:
            local_comp = Company.query.filter(Company.external_ids['odoo'].astext == str(o_emp['id'])).first()
            if not local_comp:
                local_comp = Company.query.filter(Company.nombre == o_emp['name']).first()
                
            data_emp = {
                'odoo_id': o_emp['id'],
                'nombre': o_emp['name'],
                'cif': o_emp.get('vat') or '',
                'cambios': {}
            }
            
            if local_comp:
                data_emp['local_id'] = local_comp.id
                if local_comp.nombre != o_emp['name']: data_emp['cambios']['Nombre'] = f"{local_comp.nombre} ➔ {o_emp['name']}"
                if not getattr(local_comp, 'active', True):
                    data_emp['cambios']['Estado'] = 'Inactiva ➔ Activa (reincorporación)'
                if data_emp['cambios'] or not local_comp.external_ids.get('odoo'):
                    diff['empresas']['actualizadas'].append(data_emp)
            else:
                diff['empresas']['nuevas'].append(data_emp)

        for o_cont in odoo_contactos:
            raw_vat = o_cont.get('vat')
            odoo_company_id = o_cont.get('parent_id')[0] if o_cont.get('parent_id') else None
            
            if not raw_vat or raw_vat[0].upper() in ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'J', 'N', 'P', 'Q', 'R', 'S', 'U', 'V', 'W']:
                dni_seguro = f"EXT-{o_cont['id']}"
            else:
                dni_seguro = raw_vat

            email = o_cont.get('email') or f"ext_{o_cont['id']}@subcontrata.local"
            
            from app.services.personal_conciliation_service import (
                find_user_by_any_odoo,
                odoo_ids_for_user,
            )
            local_user = find_user_by_any_odoo(o_cont['id'], include_deleted=True)
            if local_user and local_user.is_deleted:
                local_user = None
            if not local_user:
                local_user = User.query.filter(User.dni == dni_seguro).first()
            
            parts = o_cont.get('name', '').split(' ', 1)
            name = parts[0]
            lastname = parts[1] if len(parts) > 1 else ''
            
            data_cont = {
                'odoo_id': o_cont['id'],
                'name': name,
                'lastname': lastname,
                'dni': dni_seguro,
                'email': email,
                'role': 'operario',
                'categoria_profesional': o_cont.get('function') or 'Externo',
                'odoo_company_id': odoo_company_id,
                'cambios': {}
            }
            seen_odoo_ids.add(str(o_cont['id']))
            
            if local_user:
                data_cont['local_id'] = local_user.id
                seen_local_ids.add(local_user.id)
                linked_oids = set(odoo_ids_for_user(local_user))
                for oid in linked_oids:
                    seen_odoo_ids.add(oid)
                stored_oid = str((local_user.external_ids or {}).get('odoo') or '')
                if stored_oid and stored_oid != str(o_cont['id']) and str(o_cont['id']) not in linked_oids:
                    data_cont['cambios']['Id Odoo'] = f"{stored_oid} ➔ {o_cont['id']}"
                if local_user.name != name:
                    data_cont['cambios']['Nombre'] = f"{local_user.name} -> {name}"
                
                dni_local = local_user.dni
                dni_con_sufijo = f"{dni_seguro}-EXT{o_cont['id']}"
                
                if dni_local != dni_seguro and dni_local != dni_con_sufijo:
                    data_cont['cambios']['DNI'] = f"{dni_local} -> {dni_seguro}"
                
                # Extracción segura de la compañía desde JSONB
                local_odoo_company = int(local_user.company_rel.external_ids.get('odoo')) if local_user.company_rel and local_user.company_rel.external_ids and local_user.company_rel.external_ids.get('odoo') else None
                
                if local_odoo_company != odoo_company_id:
                    data_cont['cambios']['Empresa'] = "Auto-corrección de empresa huérfana"

                if not local_user.active:
                    data_cont['cambios']['Estado'] = 'Inactivo ➔ Activo (reincorporación)'
                
                if data_cont['cambios'] or not local_user.external_ids.get('odoo'):
                    diff['empleados']['actualizados'].append(data_cont)
            else:
                diff['empleados']['nuevos'].append(data_cont)

        self._append_desactivados_subcontratas(diff, seen_odoo_ids, seen_local_ids)
        return diff

    def search_people_by_dni(self, dni: str) -> list:
        """Busca en Odoo por DNI/NIF (identification_id / vat) y por código de asistencia (barcode)."""
        raw = (dni or '').strip()
        if len(raw) < 3:
            return []

        variants = []
        for v in (raw, raw.upper(), raw.replace(' ', ''), raw.upper().replace(' ', '')):
            if v and v not in variants:
                variants.append(v)

        results = []
        seen = set()
        emp_fields = ['id', 'name', 'identification_id', 'work_email', 'active', 'department_id', 'barcode']

        def _or_leaves(field, ops_variants, op='=ilike'):
            leaves = [[field, op, v] for v in ops_variants]
            if len(leaves) == 1:
                return leaves
            return ['|'] * (len(leaves) - 1) + leaves

        def _emp_domain_id_or_barcode(ops_variants, op='=ilike'):
            # (identification_id OR barcode) for each variant set
            id_part = _or_leaves('identification_id', ops_variants, op=op)
            bar_part = _or_leaves('barcode', ops_variants, op=op)
            return ['|'] + id_part + bar_part

        def _partner_domain(ops_variants, op='=ilike'):
            vat_part = _or_leaves('vat', ops_variants, op=op)
            try_bar = _or_leaves('barcode', ops_variants, op=op)
            identity = ['|'] + vat_part + try_bar
            return [['is_company', '=', False]] + identity

        def _read_emps(domain):
            try:
                return self.models.execute_kw(
                    self.db_name, self.uid, self.pwd,
                    'hr.employee', 'search_read', [domain],
                    {'fields': emp_fields, 'limit': 40},
                ) or []
            except Exception:
                # sin campo barcode
                try:
                    return self.models.execute_kw(
                        self.db_name, self.uid, self.pwd,
                        'hr.employee', 'search_read',
                        [_or_leaves('identification_id', variants)],
                        {
                            'fields': ['id', 'name', 'identification_id', 'work_email', 'active', 'department_id'],
                            'limit': 40,
                        },
                    ) or []
                except Exception:
                    return []

        emps = _read_emps(_emp_domain_id_or_barcode(variants))
        if not emps:
            wild = [f'%{v}%' for v in variants]
            emps = _read_emps(_emp_domain_id_or_barcode(wild, op='ilike'))

        for emp in emps:
            key = ('employee', emp['id'])
            if key in seen:
                continue
            seen.add(key)
            dep = emp.get('department_id')
            dep_name = dep[1] if isinstance(dep, (list, tuple)) and len(dep) > 1 else ''
            bar = emp.get('barcode')
            if bar in (False, None):
                bar = ''
            results.append({
                'odoo_id': emp['id'],
                'source': 'employee',
                'source_label': 'Empleado HR',
                'name': emp.get('name') or '',
                'dni': emp.get('identification_id') or '',
                'barcode': bar or '',
                'email': emp.get('work_email') or '',
                'company_name': dep_name or '',
                'active': bool(emp.get('active', True)),
            })

        def _read_partners(domain):
            try:
                return self.models.execute_kw(
                    self.db_name, self.uid, self.pwd,
                    'res.partner', 'search_read', [domain],
                    {
                        'fields': ['id', 'name', 'vat', 'email', 'active', 'parent_id', 'function', 'barcode'],
                        'limit': 40,
                    },
                ) or []
            except Exception:
                try:
                    return self.models.execute_kw(
                        self.db_name, self.uid, self.pwd,
                        'res.partner', 'search_read',
                        [[['is_company', '=', False]] + _or_leaves('vat', variants)],
                        {
                            'fields': ['id', 'name', 'vat', 'email', 'active', 'parent_id', 'function'],
                            'limit': 40,
                        },
                    ) or []
                except Exception:
                    return []

        partners = _read_partners(_partner_domain(variants))
        if not partners:
            wild = [f'%{v}%' for v in variants]
            partners = _read_partners(_partner_domain(wild, op='ilike'))

        for p in partners:
            key = ('partner', p['id'])
            if key in seen:
                continue
            seen.add(key)
            parent = p.get('parent_id')
            parent_name = parent[1] if isinstance(parent, (list, tuple)) and len(parent) > 1 else ''
            bar = p.get('barcode')
            if bar in (False, None):
                bar = ''
            results.append({
                'odoo_id': p['id'],
                'source': 'partner',
                'source_label': 'Contacto / subcontrata',
                'name': p.get('name') or '',
                'dni': p.get('vat') or '',
                'barcode': bar or '',
                'email': p.get('email') or '',
                'company_name': parent_name or (p.get('function') or ''),
                'active': bool(p.get('active', True)),
            })

        return results

    def search_people_by_name(self, name: str) -> list:
        """Busca empleados HR y contactos por nombre (ilike, todos los tokens)."""
        import re

        raw = (name or '').strip()
        if len(raw) < 3:
            return []

        tokens = [t for t in re.split(r'\s+', raw) if len(t) >= 2]
        if not tokens:
            tokens = [raw]

        # Lista de hojas = AND implícito en Odoo.
        name_leaves = [['name', 'ilike', f'%{tok}%'] for tok in tokens]
        name_domain = list(name_leaves)

        results = []
        seen = set()
        emp_fields = ['id', 'name', 'identification_id', 'work_email', 'active', 'department_id', 'barcode']

        def _read_emps(domain):
            try:
                return self.models.execute_kw(
                    self.db_name, self.uid, self.pwd,
                    'hr.employee', 'search_read', [domain],
                    {'fields': emp_fields, 'limit': 50},
                ) or []
            except Exception:
                try:
                    return self.models.execute_kw(
                        self.db_name, self.uid, self.pwd,
                        'hr.employee', 'search_read', [domain],
                        {
                            'fields': [
                                'id', 'name', 'identification_id',
                                'work_email', 'active', 'department_id',
                            ],
                            'limit': 50,
                        },
                    ) or []
                except Exception:
                    return []

        for emp in _read_emps(name_domain):
            key = ('employee', emp['id'])
            if key in seen:
                continue
            seen.add(key)
            dep = emp.get('department_id')
            dep_name = dep[1] if isinstance(dep, (list, tuple)) and len(dep) > 1 else ''
            bar = emp.get('barcode')
            if bar in (False, None):
                bar = ''
            results.append({
                'odoo_id': emp['id'],
                'source': 'employee',
                'source_label': 'Empleado HR',
                'name': emp.get('name') or '',
                'dni': emp.get('identification_id') or '',
                'barcode': bar or '',
                'email': emp.get('work_email') or '',
                'company_name': dep_name or '',
                'active': bool(emp.get('active', True)),
                'matched_by': 'name',
            })

        partner_domain = [['is_company', '=', False]] + name_leaves

        def _read_partners(domain):
            try:
                return self.models.execute_kw(
                    self.db_name, self.uid, self.pwd,
                    'res.partner', 'search_read', [domain],
                    {
                        'fields': [
                            'id', 'name', 'vat', 'email', 'active',
                            'parent_id', 'function', 'barcode',
                        ],
                        'limit': 50,
                    },
                ) or []
            except Exception:
                try:
                    return self.models.execute_kw(
                        self.db_name, self.uid, self.pwd,
                        'res.partner', 'search_read',
                        [[['is_company', '=', False]] + name_leaves],
                        {
                            'fields': [
                                'id', 'name', 'vat', 'email', 'active',
                                'parent_id', 'function',
                            ],
                            'limit': 50,
                        },
                    ) or []
                except Exception:
                    return []

        for p in _read_partners(partner_domain):
            key = ('partner', p['id'])
            if key in seen:
                continue
            seen.add(key)
            parent = p.get('parent_id')
            parent_name = parent[1] if isinstance(parent, (list, tuple)) and len(parent) > 1 else ''
            bar = p.get('barcode')
            if bar in (False, None):
                bar = ''
            results.append({
                'odoo_id': p['id'],
                'source': 'partner',
                'source_label': 'Contacto / subcontrata',
                'name': p.get('name') or '',
                'dni': p.get('vat') or '',
                'barcode': bar or '',
                'email': p.get('email') or '',
                'company_name': parent_name or (p.get('function') or ''),
                'active': bool(p.get('active', True)),
                'matched_by': 'name',
            })

        # Más relevantes primero: nombre más corto / empieza por el query
        needle = raw.lower()
        results.sort(key=lambda r: (
            0 if (r.get('name') or '').lower().startswith(needle) else 1,
            len(r.get('name') or ''),
            (r.get('name') or '').lower(),
        ))
        return results

    def fetch_barcodes_for_ids(self, employee_ids=None, partner_ids=None) -> dict:
        """Devuelve {(employee|partner, id_str): barcode}."""
        out = {}
        employee_ids = [int(x) for x in (employee_ids or []) if x]
        partner_ids = [int(x) for x in (partner_ids or []) if x]

        if employee_ids:
            try:
                rows = self.models.execute_kw(
                    self.db_name, self.uid, self.pwd,
                    'hr.employee', 'read',
                    [employee_ids],
                    {'fields': ['id', 'barcode']},
                ) or []
                for r in rows:
                    bar = r.get('barcode')
                    if bar in (False, None, ''):
                        continue
                    out[('employee', str(r['id']))] = str(bar).strip()
            except Exception:
                logger = logging.getLogger(__name__)
                logger.debug('fetch_barcodes employees no disponible', exc_info=True)

        if partner_ids:
            try:
                rows = self.models.execute_kw(
                    self.db_name, self.uid, self.pwd,
                    'res.partner', 'read',
                    [partner_ids],
                    {'fields': ['id', 'barcode']},
                ) or []
                for r in rows:
                    bar = r.get('barcode')
                    if bar in (False, None, ''):
                        continue
                    out[('partner', str(r['id']))] = str(bar).strip()
            except Exception:
                logger = logging.getLogger(__name__)
                logger.debug('fetch_barcodes partners no disponible', exc_info=True)

        return out

    # ------------------------------------------------------------------
    # Flota / odómetros (Odoo Fleet)
    # ------------------------------------------------------------------

    def _odoo_model_exists(self, model_name: str) -> bool:
        try:
            count = self.models.execute_kw(
                self.db_name, self.uid, self.pwd,
                'ir.model', 'search_count', [[('model', '=', model_name)]],
            )
            return bool(count)
        except Exception:
            return False

    def _odoo_fields_get(self, model_name: str) -> dict:
        try:
            return self.models.execute_kw(
                self.db_name, self.uid, self.pwd,
                model_name, 'fields_get', [],
                {'attributes': ['string', 'type', 'relation']},
            ) or {}
        except Exception:
            return {}

    def _m2o_id_name(self, val):
        if isinstance(val, (list, tuple)) and len(val) >= 2:
            raw_id, raw_name = val[0], val[1]
            return (
                None if raw_id in (False, None) else raw_id,
                None if raw_name in (False, None) else raw_name,
            )
        return None, None

    def get_diff_vehiculos(self):
        """Diff fleet.vehicle ↔ Vehiculo local (external_ids['odoo'])."""
        import logging
        logger = logging.getLogger(__name__)
        empty = {'nuevos': [], 'actualizados': [], 'sin_cambios': [], 'error': None}

        if not self._odoo_model_exists('fleet.vehicle'):
            empty['error'] = 'Modelo fleet.vehicle no disponible en Odoo (¿módulo Fleet instalado?).'
            logger.warning(f"[Odoo Adapter - Tenant {self.tenant_id}] {empty['error']}")
            return empty

        available = self._odoo_fields_get('fleet.vehicle')
        # Campos estándar Fleet; brand_id puede ser related o ausente según versión.
        wanted = ['id', 'name', 'license_plate', 'model_id', 'brand_id', 'active', 'driver_id']
        fields = [f for f in wanted if f in available] or ['id', 'name']
        if 'license_plate' not in fields and 'license_plate' in available:
            fields.append('license_plate')

        try:
            odoo_vehicles = self.models.execute_kw(
                self.db_name, self.uid, self.pwd,
                'fleet.vehicle', 'search_read',
                [[('active', '=', True)]],
                {'fields': fields},
            )
        except Exception as e:
            empty['error'] = f'Error leyendo fleet.vehicle: {e}'
            logger.error(f"[Odoo Adapter - Tenant {self.tenant_id}] {empty['error']}")
            return empty

        if not isinstance(odoo_vehicles, list):
            empty['error'] = 'Respuesta inválida de Odoo para fleet.vehicle.'
            return empty

        # Cache marca desde fleet.vehicle.model si no hay brand_id en vehicle
        model_brand_cache = {}
        need_model_brand = 'brand_id' not in fields and 'model_id' in fields
        if need_model_brand and self._odoo_model_exists('fleet.vehicle.model'):
            model_fields = self._odoo_fields_get('fleet.vehicle.model')
            brand_field = 'brand_id' if 'brand_id' in model_fields else None
            if brand_field:
                model_ids = sorted({
                    self._m2o_id_name(v.get('model_id'))[0]
                    for v in odoo_vehicles if v.get('model_id')
                } - {None})
                if model_ids:
                    try:
                        models_rows = self.models.execute_kw(
                            self.db_name, self.uid, self.pwd,
                            'fleet.vehicle.model', 'search_read',
                            [[('id', 'in', model_ids)]],
                            {'fields': ['id', brand_field]},
                        )
                        for row in models_rows or []:
                            _, bname = self._m2o_id_name(row.get(brand_field))
                            model_brand_cache[row['id']] = bname or ''
                    except Exception as e:
                        logger.warning(
                            f"[Odoo Adapter - Tenant {self.tenant_id}] "
                            f"No se pudo resolver marca vía model: {e}"
                        )

        diff = {'nuevos': [], 'actualizados': [], 'sin_cambios': [], 'error': None}
        active_odoo_ids = set()

        for veh in odoo_vehicles:
            active_odoo_ids.add(str(veh['id']))
            model_id, modelo_name = self._m2o_id_name(veh.get('model_id'))
            marca = ''
            if 'brand_id' in fields:
                _, marca = self._m2o_id_name(veh.get('brand_id'))
                marca = marca or ''
            elif model_id and model_id in model_brand_cache:
                marca = model_brand_cache[model_id]

            driver_partner_id, driver_name = self._m2o_id_name(veh.get('driver_id'))
            matricula = (veh.get('license_plate') or '') if isinstance(veh.get('license_plate'), str) else ''
            matricula = matricula.strip() or None
            nombre = (veh.get('name') or matricula or f"Vehículo {veh['id']}").strip()
            active = bool(veh.get('active', True))

            data = {
                'odoo_id': veh['id'],
                'nombre': nombre,
                'matricula': matricula,
                'marca': marca or None,
                'modelo': (modelo_name or None),
                'active': active,
                'driver_partner_id': driver_partner_id,
                'driver_name': driver_name,
                'cambios': {},
            }

            local = Vehiculo.query.filter(
                Vehiculo.external_ids['odoo'].astext == str(veh['id'])
            ).first()
            if not local and matricula:
                local = Vehiculo.query.filter(Vehiculo.matricula == matricula).first()

            if local:
                data['local_id'] = local.id
                if (local.nombre or '') != nombre:
                    data['cambios']['Nombre'] = f"{local.nombre} ➔ {nombre}"
                if (local.matricula or '') != (matricula or ''):
                    data['cambios']['Matrícula'] = f"{local.matricula or '—'} ➔ {matricula or '—'}"
                if (local.marca or '') != (marca or ''):
                    data['cambios']['Marca'] = f"{local.marca or '—'} ➔ {marca or '—'}"
                if (local.modelo or '') != (modelo_name or ''):
                    data['cambios']['Modelo'] = f"{local.modelo or '—'} ➔ {modelo_name or '—'}"
                if bool(local.active) != active:
                    data['cambios']['Activo'] = f"{local.active} ➔ {active}"

                if data['cambios'] or not (local.external_ids or {}).get('odoo'):
                    diff['actualizados'].append(data)
                else:
                    diff['sin_cambios'].append(data)
            else:
                diff['nuevos'].append(data)

        # Si un vehículo enlazado a Odoo ya no aparece entre los activos,
        # en Soltech lo tratamos como archivado y se desactiva localmente.
        local_odoo_vehicles = Vehiculo.query.filter(
            Vehiculo.external_ids['odoo'].astext.isnot(None)
        ).all()
        for local in local_odoo_vehicles:
            odoo_id = str((local.external_ids or {}).get('odoo') or '').strip()
            if not odoo_id or odoo_id in active_odoo_ids:
                continue
            if not bool(local.active):
                continue
            diff['actualizados'].append({
                'local_id': local.id,
                'odoo_id': int(odoo_id) if odoo_id.isdigit() else odoo_id,
                'nombre': local.nombre,
                'matricula': local.matricula,
                'marca': local.marca,
                'modelo': local.modelo,
                'active': False,
                'driver_partner_id': local.odoo_driver_partner_id,
                'driver_name': local.odoo_driver_name,
                'cambios': {
                    'Activo': f"{local.active} ➔ False",
                },
            })

        return diff

    def get_odometros_diarios(self, fecha=None, fecha_hasta=None):
        """Lee fleet.vehicle.odometer; fields_get para nombres de campo variables."""
        import logging
        from datetime import date as date_cls

        logger = logging.getLogger(__name__)

        if not fecha:
            fecha = date_cls.today().strftime('%Y-%m-%d')
        if not fecha_hasta:
            fecha_hasta = fecha

        if not self._odoo_model_exists('fleet.vehicle.odometer'):
            logger.warning(
                f"[Odoo Adapter - Tenant {self.tenant_id}] "
                "fleet.vehicle.odometer no disponible."
            )
            return []

        available = self._odoo_fields_get('fleet.vehicle.odometer')
        if not available:
            return []

        # Campos comunes según versión / customizaciones Soltec
        vehicle_field = next(
            (c for c in ('vehicle_id', 'fleet_vehicle_id', 'vehiculo_id') if c in available),
            None,
        )
        value_field = next(
            (c for c in ('value', 'odometer', 'km', 'kilometros') if c in available),
            None,
        )
        date_field = next(
            (c for c in ('date', 'odometer_date', 'fecha') if c in available),
            None,
        )
        driver_field = next(
            (
                c for c in (
                    'driver_id', 'partner_id', 'employee_id',
                    'create_uid', 'user_id',
                ) if c in available
            ),
            None,
        )

        if not vehicle_field or not value_field or not date_field:
            logger.error(
                f"[Odoo Adapter - Tenant {self.tenant_id}] "
                f"odómetro: faltan campos obligatorios "
                f"(vehicle={vehicle_field}, value={value_field}, date={date_field}). "
                f"Disponibles: {sorted(available.keys())}"
            )
            return []

        fields = [vehicle_field, value_field, date_field]
        if driver_field:
            fields.append(driver_field)

        domain = [
            (date_field, '>=', fecha),
            (date_field, '<=', fecha_hasta),
        ]

        try:
            rows = self.models.execute_kw(
                self.db_name, self.uid, self.pwd,
                'fleet.vehicle.odometer', 'search_read',
                [domain],
                {'fields': fields, 'order': f'{date_field} asc, id asc', 'limit': 10000},
            )
        except Exception as e:
            logger.error(
                f"[Odoo Adapter - Tenant {self.tenant_id}] "
                f"Error leyendo fleet.vehicle.odometer: {e}"
            )
            return []

        if not isinstance(rows, list):
            return []

        result = []
        for row in rows:
            veh_id, _ = self._m2o_id_name(row.get(vehicle_field))
            if veh_id is None and isinstance(row.get(vehicle_field), int):
                veh_id = row.get(vehicle_field)
            if not veh_id:
                continue

            raw_date = row.get(date_field)
            if not raw_date:
                continue
            date_str = str(raw_date)[:10]

            raw_val = row.get(value_field)
            try:
                value = float(raw_val) if raw_val not in (False, None, '') else None
            except (TypeError, ValueError):
                value = None

            driver_partner_id, driver_name = None, None
            if driver_field:
                driver_partner_id, driver_name = self._m2o_id_name(row.get(driver_field))
                # create_uid / user_id son res.users; el nombre sigue siendo útil
                if driver_field in ('create_uid', 'user_id') and driver_partner_id:
                    # Conservamos el id de user Odoo solo como referencia débil
                    pass

            result.append({
                'odoo_vehicle_id': int(veh_id),
                'date': date_str,
                'value': value,
                'driver_partner_id': int(driver_partner_id) if driver_partner_id else None,
                'driver_name': driver_name,
            })

        return result

    def get_viajes_diarios(self, fecha=None, fecha_hasta=None):
        """
        Viajes Soltec: tms.shipment confirmed.
        Día de uso = date_start..date_end (fallback: date de registro).
        """
        import logging
        from datetime import date as date_cls, datetime as dt_cls

        logger = logging.getLogger(__name__)

        if not fecha:
            fecha = date_cls.today().strftime('%Y-%m-%d')
        if not fecha_hasta:
            fecha_hasta = fecha

        model = 'tms.shipment'
        try:
            from app.models import ConfiguracionGlobal
            conf = ConfiguracionGlobal.query.filter_by(clave='odoo_viaje_model').first()
            if conf and (conf.valor or '').strip():
                model = conf.valor.strip()
        except Exception:
            pass

        if not self._odoo_model_exists(model):
            logger.error(
                f"[Odoo Adapter - Tenant {self.tenant_id}] "
                f"Modelo de viajes '{model}' no existe."
            )
            return []

        available = self._odoo_fields_get(model) or {}

        def _has(*names):
            for n in names:
                if n in available:
                    return n
            return None

        f_vehicle = _has('bim_transport_equipment_id', 'vehicle_id', 'equipo_id')
        f_date = _has('date')
        f_start = _has('date_start', 'fecha_inicio')
        f_end = _has('date_end', 'fecha_fin')
        f_km0 = _has('begin_kilometers', 'km_start', 'km_inicial')
        f_km1 = _has('end_kilometers', 'km_end', 'km_final')
        f_driver = _has('driver_id')
        f_qty = _has('qty')
        f_previsto = _has('km_previsto')
        f_desvio = _has('desvio')
        f_state = _has('state')
        f_name = _has('name')
        f_origin = _has('bim_project_origin_id')
        f_dest = _has('bim_project_destination_id')
        f_nota = _has('x_studio_nota', 'nota')
        f_reviewed = _has('reviewed')

        if not f_vehicle:
            logger.error(
                f"[Odoo Adapter - Tenant {self.tenant_id}] "
                f"{model}: falta equipo/vehículo. Campos: {sorted(available.keys())}"
            )
            return []

        fields = ['id', f_vehicle]
        for f in (
            f_date, f_start, f_end, f_km0, f_km1, f_driver, f_qty,
            f_previsto, f_desvio, f_state, f_name, f_origin, f_dest, f_nota, f_reviewed,
        ):
            if f and f not in fields:
                fields.append(f)

        # Dominio SIMPLE y correcto (notación polaca Odoo):
        # confirmed AND (
        #   date_start en rango
        #   OR (date_end cubre el rango)
        #   OR date registro en rango  ← catch-up
        # )
        leafs = []
        if f_start:
            leafs.append('&')
            leafs.append((f_start, '>=', fecha))
            leafs.append((f_start, '<=', fecha_hasta))
        if f_start and f_end:
            leafs.append('&')
            leafs.append('&')
            leafs.append((f_end, '!=', False))
            leafs.append((f_end, '>=', fecha))
            leafs.append((f_start, '<=', fecha_hasta))
        if f_date:
            leafs.append('&')
            leafs.append((f_date, '>=', f'{fecha} 00:00:00'))
            leafs.append((f_date, '<=', f'{fecha_hasta} 23:59:59'))

        n_branches = (1 if f_start else 0) + (1 if (f_start and f_end) else 0) + (1 if f_date else 0)
        if n_branches == 0:
            domain = [('state', '=', 'confirmed')] if f_state else []
        else:
            ors = ['|'] * (n_branches - 1) if n_branches > 1 else []
            domain = ors + leafs
            if f_state:
                domain = ['&', ('state', '=', 'confirmed')] + domain

        # Paginado: no depender de un único search_read enorme
        rows = []
        offset = 0
        page = 2000
        try:
            while True:
                chunk = self.models.execute_kw(
                    self.db_name, self.uid, self.pwd,
                    model, 'search_read',
                    [domain],
                    {
                        'fields': fields,
                        'order': 'id asc',
                        'limit': page,
                        'offset': offset,
                    },
                )
                if not isinstance(chunk, list) or not chunk:
                    break
                rows.extend(chunk)
                if len(chunk) < page:
                    break
                offset += page
                if offset > 100000:
                    break
        except Exception as e:
            logger.error(
                f"[Odoo Adapter - Tenant {self.tenant_id}] "
                f"Error leyendo {model}: {e} domain={domain}"
            )
            return []

        def _as_date(raw):
            if not raw or raw is False:
                return None
            s = str(raw).strip()[:10]
            try:
                dt_cls.strptime(s, '%Y-%m-%d')
                return s
            except ValueError:
                return None

        def _as_float(raw):
            try:
                return float(raw) if raw not in (False, None, '') else None
            except (TypeError, ValueError):
                return None

        def _m2o_label(raw):
            return self._m2o_id_name(raw)

        result = []
        for row in rows:
            if f_state and row.get(f_state) not in (None, False, 'confirmed'):
                continue

            veh_id, veh_name = _m2o_label(row.get(f_vehicle))
            if not veh_id:
                continue

            d_reg = _as_date(row.get(f_date)) if f_date else None
            d_start = _as_date(row.get(f_start)) if f_start else None
            d_end = _as_date(row.get(f_end)) if f_end else None
            # Día de uso real: ficha; si falta, fecha de registro
            if not d_start:
                d_start = d_reg
            if not d_end:
                d_end = d_start
            if not d_start:
                continue
            if d_end < d_start:
                d_start, d_end = d_end, d_start

            driver_partner_id, driver_name = (None, None)
            if f_driver:
                driver_partner_id, driver_name = _m2o_label(row.get(f_driver))

            origin_id, origin_name = (None, None)
            dest_id, dest_name = (None, None)
            if f_origin:
                origin_id, origin_name = _m2o_label(row.get(f_origin))
            if f_dest:
                dest_id, dest_name = _m2o_label(row.get(f_dest))

            km_start = _as_float(row.get(f_km0)) if f_km0 else None
            km_end = _as_float(row.get(f_km1)) if f_km1 else None
            qty = _as_float(row.get(f_qty)) if f_qty else None
            if qty is None and km_start is not None and km_end is not None:
                qty = km_end - km_start

            result.append({
                'odoo_vehicle_id': int(veh_id),
                'odoo_vehicle_name': veh_name,
                'odoo_viaje_id': int(row['id']) if row.get('id') else None,
                'code': row.get(f_name) if f_name else None,
                'state': row.get(f_state) if f_state else None,
                'date_registro': d_reg or d_end,
                'date_start': d_start,
                'date_end': d_end,
                'km_start': km_start,
                'km_end': km_end,
                'qty_km': qty,
                'km_previsto': _as_float(row.get(f_previsto)) if f_previsto else None,
                'desvio': _as_float(row.get(f_desvio)) if f_desvio else None,
                'driver_partner_id': int(driver_partner_id) if driver_partner_id else None,
                'driver_name': driver_name,
                'obra_origen': origin_name,
                'obra_destino': dest_name,
                'obra_origen_id': int(origin_id) if origin_id else None,
                'obra_destino_id': int(dest_id) if dest_id else None,
                'nota': row.get(f_nota) if f_nota else None,
                'reviewed': bool(row.get(f_reviewed)) if f_reviewed else None,
                'source_model': model,
            })

        # Diagnóstico de fechas (para cazar el colapso a pocos días)
        starts = [r['date_start'] for r in result]
        unique_starts = sorted(set(starts))
        logger.info(
            f"[Odoo Adapter - Tenant {self.tenant_id}] "
            f"viajes ({model}): {len(result)} rows, "
            f"date_start unicos={len(unique_starts)}, "
            f"min={unique_starts[0] if unique_starts else None}, "
            f"max={unique_starts[-1] if unique_starts else None}, "
            f"domain={domain}"
        )

        # Si date_start viene colapsado (p.ej. computed=hoy para todos),
        # el día de uso real pasa a ser la fecha de registro del viaje.
        if len(result) >= 200 and len(unique_starts) <= 5:
            logger.warning(
                f"[Odoo Adapter - Tenant {self.tenant_id}] "
                f"date_start colapsado ({len(unique_starts)} únicos / {len(result)} viajes). "
                f"Usando date (registro) como día de uso."
            )
            for r in result:
                d = r.get('date_registro') or r['date_start']
                r['date_start'] = d
                r['date_end'] = d
                r['_fecha_desde_registro'] = True

        return result
