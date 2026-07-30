import xmlrpc.client
import os
import re
from app import db
from app.models import Obra, User, Company, Vehiculo
from app.sync.adapters.base import BaseSyncAdapter
from app.services.config_service import get_tenant_config

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

        # --- FICHAJES INTERNOS ---
        try:
            att_int = self.models.execute_kw(
                self.db_name, self.uid, self.pwd, 
                'hr.attendance', 'search_read', 
                [domain], 
                {'fields': ['employee_id', 'project_id', 'write_uid', 'check_in', 'check_out', 'note']}
            )
            
            # Seguro contra respuestas malformadas de Odoo (típico de XML-RPC cuando falla)
            if not isinstance(att_int, list):
                logger.error(f"🚨 [Odoo Adapter - Tenant {self.tenant_id}] hr.attendance no devolvió una lista.")
                raise ConnectionError("Respuesta inválida de Odoo para fichajes internos.")

            for a in att_int:
                if a.get('employee_id'):
                    obra_id = a.get('project_id')[0] if a.get('project_id') else None
                    modificado_por = a.get('write_uid')[1] if a.get('write_uid') else 'RRHH Odoo'
                    fichajes_estandarizados.append({
                        'empleado_external_id': str(a['employee_id'][0]),
                        'obra_external_id': str(obra_id) if obra_id else None,
                        'fecha': fecha_str,
                        'check_in': a.get('check_in'),
                        'check_out': a.get('check_out'),
                        'autor': modificado_por,
                        'note': a.get('note') if a.get('note') not in (False, None, '') else None,
                    })
        except Exception as e:
            logger.error(f"🚨 [Odoo Adapter - Tenant {self.tenant_id}] CRÍTICO: Fallo de red en hr.attendance. Error: {str(e)}")
            raise e  # <- CRÍTICO: Lanzamos el error hacia arriba para abortar la sincronización de este tenant

        # --- FICHAJES SUBCONTRATAS ---
        try:
            att_ext = self.models.execute_kw(
                self.db_name, self.uid, self.pwd, 
                'partner.attendance', 'search_read', 
                [domain], 
                {'fields': ['partner_id', 'project_id', 'write_uid', 'check_in', 'check_out', 'note']}
            )
            
            if not isinstance(att_ext, list):
                logger.error(f"🚨 [Odoo Adapter - Tenant {self.tenant_id}] partner.attendance no devolvió una lista.")
                raise ConnectionError("Respuesta inválida de Odoo para fichajes de subcontratas.")

            for a in att_ext:
                if a.get('partner_id'):
                    obra_id = a.get('project_id')[0] if a.get('project_id') else None
                    modificado_por = a.get('write_uid')[1] if a.get('write_uid') else 'RRHH Odoo'
                    fichajes_estandarizados.append({
                        'empleado_external_id': str(a['partner_id'][0]),
                        'obra_external_id': str(obra_id) if obra_id else None,
                        'fecha': fecha_str,
                        'check_in': a.get('check_in'),
                        'check_out': a.get('check_out'),
                        'autor': modificado_por,
                        'note': a.get('note') if a.get('note') not in (False, None, '') else None,
                    })
        except Exception as e:
            logger.error(f"🚨 [Odoo Adapter - Tenant {self.tenant_id}] CRÍTICO: Fallo de red en partner.attendance. Error: {str(e)}")
            raise e  # <- CRÍTICO: Lanzamos el error hacia arriba

        return fichajes_estandarizados

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

    def get_diff_obras(self):
        domain = [['state_id', '=', 6], ['active', '=', True]]
        fields = ['id', 'name', 'nombre', 'customer_id', 'date_ini', 'nexecution_manager', 'encargado_obra']
        odoo_obras = self.models.execute_kw(self.db_name, self.uid, self.pwd, 'bim.project', 'search_read', [domain], {'fields': fields})
        
        diff = {'nuevas': [], 'actualizadas': [], 'sin_cambios': [], 'finalizadas': [], 'validadas_manual': []}
        active_odoo_ids = []

        for obra in odoo_obras:
            active_odoo_ids.append(obra['id'])
            raw_name = obra.get('name', '')
            
            import re
            match = re.match(r'^([A-Z0-9]+/[0-9]+)', raw_name)
            if match:
                codigo_limpio = match.group(1)
            else:
                codigo_limpio = raw_name.split(' ')[0][:20]
            
            nombre_limpio = obra.get('nombre') or raw_name

            local_obra = Obra.query.filter(
                (Obra.external_ids['odoo'].astext == str(obra['id'])) | 
                (Obra.codigo == codigo_limpio)
            ).first()
            cliente_name = obra.get('customer_id')[1] if obra.get('customer_id') else ''
            jefe_id, warn_jefe = self._resolve_employee(obra.get('nexecution_manager'))
            enc_id, warn_enc = self._resolve_employee(obra.get('encargado_obra'))
            
            parsed_data = {
                'odoo_id': obra['id'],
                'codigo': codigo_limpio, 
                'nombre': nombre_limpio, 
                'cliente': cliente_name,
                'fecha_inicio': obra.get('date_ini'),
                'estado': 'Pendiente', 
                'jefe_obra_id': jefe_id,
                'warn_jefe': warn_jefe,
                'encargado_id': enc_id,
                'warn_encargado': warn_enc,
                'jefe_odoo_raw': obra.get('nexecution_manager')[1] if obra.get('nexecution_manager') else '',
                'enc_odoo_raw': obra.get('encargado_obra')[1] if obra.get('encargado_obra') else '',
                'cambios': {}
            }
            
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

                if parsed_data['cambios'] or not local_obra.external_ids.get('odoo') or warn_jefe or warn_enc:
                    diff['actualizadas'].append(parsed_data)
                elif es_validacion_manual:
                    diff['validadas_manual'].append(parsed_data)
                else:
                    diff['sin_cambios'].append(parsed_data)
            else:
                diff['nuevas'].append(parsed_data)

        # Búsqueda correcta con JSONB para obras finalizadas
        obras_locales_activas = Obra.query.filter(Obra.external_ids.has_key('odoo'), Obra.estado != 'Finalizada').all()
        for local in obras_locales_activas:
            odoo_id_local = local.external_ids.get('odoo')
            if int(odoo_id_local) not in active_odoo_ids:
                diff['finalizadas'].append({
                    'local_id': local.id,
                    'odoo_id': int(odoo_id_local),
                    'codigo': local.codigo,
                    'nombre': local.nombre,
                    'estado_anterior': local.estado
                })
                
        return diff
    
    def get_diff_empleados(self):
        domain = [['active', '=', True]]
        fields = ['id', 'name', 'identification_id', 'work_email', 'job_title', 'department_id', 'job_id']
        odoo_emps = self.models.execute_kw(self.db_name, self.uid, self.pwd, 'hr.employee', 'search_read', [domain], {'fields': fields})
        
        diff = {'nuevos': [], 'actualizados': [], 'sin_cambios': []}
        
        departamentos_permitidos = [
            'Administración G', 'Administración S', 'Compras', 'Dirección',
            'Encargados/Of.1ª', 'Estudios clima', 'Estudios electricidad',
            'JO clima', 'JO electricidad', 'Oficiales 2ª/3ª', 'Producción clima',
            'Producción electricidad'
        ]
        
        for emp in odoo_emps:
            dni = emp.get('identification_id')
            if not dni: continue

            dep_raw = emp.get('department_id')
            department = dep_raw[1] if dep_raw else ''
            
            if not any(d in department for d in departamentos_permitidos):
                continue

            job_raw = emp.get('job_id')
            categoria = emp.get('job_title') or (job_raw[1] if job_raw else 'Sin definir')
            
            if 'JO ' in department or 'Jefe de obra' in department or 'jefe' in categoria.lower():
                role = 'jefe_obra'
            else:
                role = 'operario'

            email = emp.get('work_email') or f"sin_email_{emp['id']}@local.tuappsaas.com"
            
            local_user = User.query.filter(User.external_ids['odoo'].astext == str(emp['id'])).first()
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
                'cambios': {},
                'bloqueos': []
            }
            
            if local_user:
                data['local_id'] = local_user.id
                
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
                if local_user.role != role: data['cambios']['Rol'] = f"{local_user.role} ➔ {role}"
                if (local_user.categoria_profesional or '') != categoria: 
                    data['cambios']['Categoría'] = f"{local_user.categoria_profesional or 'Ninguna'} ➔ {categoria}"
                
                # Búsqueda correcta en JSONB
                if data['cambios'] or not local_user.external_ids.get('odoo'):
                    diff['actualizados'].append(data)
                else:
                    diff['sin_cambios'].append(data)
            else:
                diff['nuevos'].append(data)
                
        return diff

    def _resolve_employee(self, odoo_field):
        if not odoo_field: return None, False

        emp_id, emp_name = odoo_field[0], odoo_field[1]
        domain = ['|', '|', ('user_id', '=', emp_id), ('id', '=', emp_id), ('name', '=', emp_name)]
        emps = self.models.execute_kw(self.db_name, self.uid, self.pwd, 'hr.employee', 'search_read', [domain], {'fields': ['id', 'identification_id'], 'limit': 1})
        
        if emps:
            dni = emps[0].get('identification_id')
            real_id = emps[0]['id']
            
            if dni:
                local_user = User.query.filter(
                    (User.external_ids['odoo'].astext == str(real_id)) | (User.dni == dni)
                ).first()
            else:
                local_user = User.query.filter(User.external_ids['odoo'].astext == str(real_id)).first()
            
            if local_user: 
                return local_user.id, False
                
        return None, True
    
    def get_diff_subcontratas(self):
        domain_empresas = [
            ('is_company', '=', True),
            ('category_id.name', 'ilike', 'subcontrata')
        ]
        odoo_empresas = self.models.execute_kw(self.db_name, self.uid, self.pwd, 'res.partner', 'search_read', [domain_empresas], {'fields': ['id', 'name', 'vat']})
        
        diff = {
            'empresas': {'nuevas': [], 'actualizadas': []},
            'empleados': {'nuevos': [], 'actualizados': []}
        }
        
        if not odoo_empresas:
            return diff

        empresa_ids = [e['id'] for e in odoo_empresas]

        domain_contactos = [
            ('parent_id', 'in', empresa_ids),
            ('is_company', '=', False),
            ('active', '=', True)
        ]
        odoo_contactos = self.models.execute_kw(self.db_name, self.uid, self.pwd, 'res.partner', 'search_read', [domain_contactos], {'fields': ['id', 'name', 'email', 'vat', 'function', 'parent_id']})

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
            
            local_user = User.query.filter(User.external_ids['odoo'].astext == str(o_cont['id'])).first()
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
            
            if local_user:
                data_cont['local_id'] = local_user.id
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
                
                if data_cont['cambios'] or not local_user.external_ids.get('odoo'):
                    diff['empleados']['actualizados'].append(data_cont)
            else:
                diff['empleados']['nuevos'].append(data_cont)
                
        return diff

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
            return val[0], val[1]
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
                [[]],
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

        for veh in odoo_vehicles:
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
