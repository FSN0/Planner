import xmlrpc.client
import os
import re
from app import db
from app.models import Obra, User, Company
from app.sync.adapters.base import BaseSyncAdapter
from app.services.config_service import get_tenant_config

class Adapter(BaseSyncAdapter):
    def __init__(self, tenant_id: int):
        super().__init__(tenant_id)
        
        self.url = get_tenant_config('odoo_url', default=os.environ.get('ODOO_URL', '')).strip()
        self.db_name = get_tenant_config('odoo_db', default=os.environ.get('ODOO_DB', '')).strip()
        self.user = get_tenant_config('odoo_user', default=os.environ.get('ODOO_USER', '')).strip()
        self.pwd = get_tenant_config('odoo_password', desencriptar=True, default=os.environ.get('ODOO_PASSWORD', '')).strip()
        
        if not self.url or not self.url.startswith('http'):
            raise ValueError("No hay ODOO_URL configurada para este inquilino.")
            
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
                {'fields': ['employee_id', 'project_id', 'write_uid', 'check_in', 'check_out']}
            )
            
            # Seguro contra respuestas malformadas de Odoo (típico de XML-RPC cuando falla)
            if not isinstance(att_int, list):
                logger.error(f"🚨 [Odoo Adapter - Tenant {self.tenant_id}] hr.attendance no devolvió una lista.")
                raise ConnectionError("Respuesta inválida de Odoo para fichajes internos.")

            for a in att_int:
                if a.get('employee_id') and a.get('project_id'):
                    modificado_por = a.get('write_uid')[1] if a.get('write_uid') else 'RRHH Odoo'
                    fichajes_estandarizados.append({
                        'empleado_external_id': str(a['employee_id'][0]),
                        'obra_external_id': str(a['project_id'][0]),
                        'fecha': fecha_str,
                        'check_in': a.get('check_in'),
                        'check_out': a.get('check_out'),
                        'autor': modificado_por  
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
                {'fields': ['partner_id', 'project_id', 'write_uid', 'check_in', 'check_out']}
            )
            
            if not isinstance(att_ext, list):
                logger.error(f"🚨 [Odoo Adapter - Tenant {self.tenant_id}] partner.attendance no devolvió una lista.")
                raise ConnectionError("Respuesta inválida de Odoo para fichajes de subcontratas.")

            for a in att_ext:
                if a.get('partner_id') and a.get('project_id'):
                    modificado_por = a.get('write_uid')[1] if a.get('write_uid') else 'RRHH Odoo'
                    fichajes_estandarizados.append({
                        'empleado_external_id': str(a['partner_id'][0]),
                        'obra_external_id': str(a['project_id'][0]),
                        'fecha': fecha_str,
                        'check_in': a.get('check_in'),
                        'check_out': a.get('check_out'),
                        'autor': modificado_por
                    })
        except Exception as e:
            logger.error(f"🚨 [Odoo Adapter - Tenant {self.tenant_id}] CRÍTICO: Fallo de red en partner.attendance. Error: {str(e)}")
            raise e  # <- CRÍTICO: Lanzamos el error hacia arriba

        return fichajes_estandarizados
    
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