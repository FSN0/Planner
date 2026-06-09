import xmlrpc.client
import os
import re
from app import db
from app.models import Obra, User, Company

class OdooSyncService:
    def __init__(self):
        self.url = os.environ.get('ODOO_URL', '').strip()
        self.db_name = os.environ.get('ODOO_DB', '').strip()
        self.user = os.environ.get('ODOO_USER', '').strip()
        self.pwd = os.environ.get('ODOO_PASSWORD', '').strip()
        
        if not self.url or not self.url.startswith('http'):
            raise ValueError("Falta configurar la variable ODOO_URL en Docker o no empieza por http://")
            
        try:
            self.common = xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/common')
            self.uid = self.common.authenticate(self.db_name, self.user, self.pwd, {})
            if not self.uid:
                raise ValueError("Credenciales de Odoo incorrectas.")
            self.models = xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/object')
        except Exception as e:
            raise ValueError(f"No se pudo establecer conexión XML-RPC: {str(e)}")

    def get_diff_obras(self):
        domain = [['state_id', '=', 6], ['active', '=', True]]
        fields = ['id', 'name', 'nombre', 'customer_id', 'date_ini', 'nexecution_manager', 'encargado_obra']
        odoo_obras = self.models.execute_kw(self.db_name, self.uid, self.pwd, 'bim.project', 'search_read', [domain], {'fields': fields})
        
        # AÑADIMOS LA NUEVA CATEGORÍA 'validadas_manual'
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

            local_obra = Obra.query.filter((Obra.odoo_id == obra['id']) | (Obra.codigo == codigo_limpio)).first()
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

                # --- NUEVA LÓGICA: Validaciones Manuales ---
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
                # -------------------------------------------

                if local_obra.nombre != parsed_data['nombre']: parsed_data['cambios']['Nombre'] = f"{local_obra.nombre} ➔ {parsed_data['nombre']}"
                if (local_obra.descripcion or '') != parsed_data['cliente']: parsed_data['cambios']['Cliente'] = f"{local_obra.descripcion} ➔ {parsed_data['cliente']}"
                local_fecha = str(local_obra.fecha_inicio) if local_obra.fecha_inicio else None
                if local_fecha != parsed_data['fecha_inicio']: parsed_data['cambios']['Fecha'] = f"{local_fecha} ➔ {parsed_data['fecha_inicio']}"
                if local_obra.jefe_obra_id != jefe_id and not warn_jefe: parsed_data['cambios']['Jefe Obra'] = "Actualizado desde Odoo"
                if local_obra.encargado_id != enc_id and not warn_enc: parsed_data['cambios']['Encargado'] = "Actualizado desde Odoo"

                # REPARTO EN LAS LISTAS SEGÚN EL ESTADO
                if parsed_data['cambios'] or not local_obra.odoo_id or warn_jefe or warn_enc:
                    diff['actualizadas'].append(parsed_data)
                elif es_validacion_manual:
                    diff['validadas_manual'].append(parsed_data)
                else:
                    diff['sin_cambios'].append(parsed_data)
            else:
                diff['nuevas'].append(parsed_data)

        obras_locales_activas = Obra.query.filter(Obra.odoo_id.isnot(None), Obra.estado != 'Finalizada').all()
        for local in obras_locales_activas:
            if local.odoo_id not in active_odoo_ids:
                diff['finalizadas'].append({
                    'local_id': local.id,
                    'odoo_id': local.odoo_id,
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
        
        # LISTA EXACTA DE DEPARTAMENTOS EXTRAÍDA DE TU ODOO
        departamentos_permitidos = [
            'Administración G',
            'Administración S',
            'Compras',
            'Dirección',
            'Encargados/Of.1ª',
            'Estudios clima',
            'Estudios electricidad',
            'JO clima',
            'JO electricidad',
            'Oficiales 2ª/3ª',
            'Producción clima',
            'Producción electricidad'
        ]
        
        for emp in odoo_emps:
            dni = emp.get('identification_id')
            if not dni: continue

            dep_raw = emp.get('department_id')
            department = dep_raw[1] if dep_raw else ''
            
            # Comprobamos si alguna de las palabras clave permitidas está en el nombre del departamento
            # (Lo hacemos con 'in' por si Odoo devuelve "Producción clima / Encargados/Of.1ª")
            if not any(d in department for d in departamentos_permitidos):
                continue

            job_raw = emp.get('job_id')
            categoria = emp.get('job_title') or (job_raw[1] if job_raw else 'Sin definir')
            
            # Asignación de roles: OJO a los nuevos "JO" (Jefes de Obra)
            if 'JO ' in department or 'Jefe de obra' in department or 'jefe' in categoria.lower():
                role = 'jefe_obra'
            else:
                role = 'operario'

            email = emp.get('work_email') or f"sin_email_{emp['id']}@soltec.local"
            
            local_user = User.query.filter(User.odoo_id == emp['id']).first()
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
                
                if data['cambios'] or not local_user.odoo_id:
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
            
            # --- CORRECCIÓN: Filtrar la trampa del 'False' de Odoo ---
            # Si dni tiene un valor válido (es decir, no es False ni vacío)
            if dni:
                local_user = User.query.filter((User.odoo_id == real_id) | (User.dni == dni)).first()
            else:
                # Si Odoo devolvió False porque no tiene DNI, buscamos SOLO por el ID
                local_user = User.query.filter(User.odoo_id == real_id).first()
            # ---------------------------------------------------------
            
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
            local_comp = Company.query.filter(Company.odoo_id == o_emp['id']).first()
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
                if data_emp['cambios'] or not local_comp.odoo_id:
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
            
            local_user = User.query.filter(User.odoo_id == o_cont['id']).first()
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
                
                # --- NUEVO BLOQUE: Forzar auto-corrección de empresa ---
                local_odoo_company = local_user.company_rel.odoo_id if local_user.company_rel else None
                if local_odoo_company != odoo_company_id:
                    data_cont['cambios']['Empresa'] = "Auto-corrección de empresa huérfana"
                # -------------------------------------------------------
                
                if data_cont['cambios'] or not local_user.odoo_id:
                    diff['empleados']['actualizados'].append(data_cont)
            else:
                diff['empleados']['nuevos'].append(data_cont)
                
        return diff
    
    def sync_fichajes_diarios(self, fecha_str=None):
        from app.models import RegistroFichaje, Asignacion, User, Obra, Festivo
        from datetime import date, datetime
        from app import db # Asegúrate de que db está importado
        from sqlalchemy import text
        import logging
        logger = logging.getLogger(__name__)

        from app.utils.timezone_utils import today_local
        if not fecha_str:
            fecha_str = today_local().strftime('%Y-%m-%d')
        fecha_obj = datetime.strptime(fecha_str, '%Y-%m-%d').date()
        
        es_festivo = Festivo.query.filter_by(fecha=fecha_obj).first()
        if es_festivo:
            # Si es festivo, salimos de la función sin generar ausencias ni conflictos.
            return

        lock_id = 424242
        if not db.session.execute(text("SELECT pg_try_advisory_lock(:id)"), {'id': lock_id}).scalar():
            logger.warning("Sync fichajes omitido: otra instancia ya está en ejecución.")
            return

        try:
            self._sync_fichajes_diarios_impl(fecha_obj, fecha_str)
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
        finally:
            try:
                db.session.execute(text("SELECT pg_advisory_unlock(:id)"), {'id': lock_id})
            except Exception:
                pass

    def _sync_fichajes_diarios_impl(self, fecha_obj, fecha_str):
        from app.models import RegistroFichaje, Asignacion, User, Obra
        from datetime import datetime
        from app import db

        domain = [('check_in', 'ilike', f'{fecha_str}%')]
        fichajes_crudos = []

        # 1. Bajar Fichajes de Odoo (AHORA CON HORAS)
        import logging
        logger = logging.getLogger(__name__)

        try:
            att_int = self.models.execute_kw(self.db_name, self.uid, self.pwd, 'hr.attendance', 'search_read', [domain], {'fields': ['employee_id', 'project_id', 'write_uid', 'check_in', 'check_out']})
            if not isinstance(att_int, list):
                logger.error(f"🚨 [Odoo Sync] Error: hr.attendance devolvio no-lista. Abortando.")
                return

            for a in att_int:
                if a.get('employee_id'):
                    # Extraemos la obra de forma segura por si Odoo manda False (Obra quitada por RRHH)
                    obra_id = a.get('project_id')[0] if a.get('project_id') else None
                    modificado_por = a.get('write_uid')[1] if a.get('write_uid') else 'RRHH Odoo'
                    fichajes_crudos.append({'odoo_user': a['employee_id'][0], 'odoo_obra': obra_id, 'autor': modificado_por, 'check_in': a.get('check_in'), 'check_out': a.get('check_out')})
        except Exception as e:
            logger.error(f"🚨 [Odoo Sync] CRITICO: Fallo conexion hr.attendance: {str(e)}")
            return # ABORTA LA FUNCION SI FALLA LA CONEXION

        try:
            att_ext = self.models.execute_kw(self.db_name, self.uid, self.pwd, 'partner.attendance', 'search_read', [domain], {'fields': ['partner_id', 'project_id', 'write_uid', 'check_in', 'check_out']})
            if not isinstance(att_ext, list):
                logger.error(f"🚨 [Odoo Sync] Error: partner.attendance devolvio no-lista. Abortando.")
                return

            for a in att_ext:
                if a.get('partner_id'):
                    # Extraemos la obra de forma segura por si Odoo manda False
                    obra_id = a.get('project_id')[0] if a.get('project_id') else None
                    modificado_por = a.get('write_uid')[1] if a.get('write_uid') else 'RRHH Odoo'
                    fichajes_crudos.append({'odoo_user': a['partner_id'][0], 'odoo_obra': obra_id, 'autor': modificado_por, 'check_in': a.get('check_in'), 'check_out': a.get('check_out')})
        
        
        except Exception as e:
            logger.error(f"🚨 [Odoo Sync] CRITICO: Fallo conexion partner.attendance: {str(e)}")
            return # ABORTA LA FUNCION SI FALLA LA CONEXION

        fichajes_unicos = {}
        for f in fichajes_crudos:
            key = f"{f['odoo_user']}_{f['odoo_obra']}"
            if key not in fichajes_unicos:
                fichajes_unicos[key] = f
            else:
                # Si han fichado varias veces en la misma obra, nos quedamos con el primer check-in y el último check-out
                if f['check_in'] and (not fichajes_unicos[key]['check_in'] or f['check_in'] < fichajes_unicos[key]['check_in']):
                    fichajes_unicos[key]['check_in'] = f['check_in']
                if f['check_out'] and (not fichajes_unicos[key]['check_out'] or f['check_out'] > fichajes_unicos[key]['check_out']):
                    fichajes_unicos[key]['check_out'] = f['check_out']

        # --- PRE-EVALUACIÓN: RELLENAR CON SIN REGISTRO ---
        todas_asig = Asignacion.query.filter_by(fecha=fecha_obj).all()
        for asig in todas_asig:
            registro = RegistroFichaje.query.filter_by(user_id=asig.user_id, fecha=fecha_obj, obra_planificada_id=asig.obra_id).first()
            if not registro:
                db.session.add(RegistroFichaje(
                    user_id=asig.user_id, fecha=fecha_obj, obra_planificada_id=asig.obra_id, estado='Sin_Registro'
                ))
                db.session.flush()

        # =========================================================================
        # --- LIMPIEZA REACTIVA: GUARDADO DE DATOS ESTRUCTURADOS ---
        # =========================================================================
        obras_por_usuario_odoo = {}
        for f in fichajes_unicos.values():
            if f['odoo_user'] not in obras_por_usuario_odoo:
                obras_por_usuario_odoo[f['odoo_user']] = []
            obras_por_usuario_odoo[f['odoo_user']].append(f['odoo_obra'])

        registros_hoy_locales = RegistroFichaje.query.filter_by(fecha=fecha_obj).filter(
            RegistroFichaje.obra_real_id.isnot(None),
            RegistroFichaje.estado != 'Sobreescrito_RRHH'
        ).all()

        for reg_local in registros_hoy_locales:
            u_local = User.query.get(reg_local.user_id)
            o_real = Obra.query.get(reg_local.obra_real_id)
            
            if not u_local or not u_local.odoo_id or not o_real or not o_real.odoo_id: 
                continue

            obras_odoo_del_usuario = obras_por_usuario_odoo.get(u_local.odoo_id, [])

            if o_real.odoo_id not in obras_odoo_del_usuario:
                # 1. Borrar asignaciones mágicas
                
                asig_fantasma = Asignacion.query.filter_by(user_id=u_local.id, fecha=fecha_obj, obra_id=o_real.id).first()
                if asig_fantasma:
                    from app.services.core_assignment_service import CoreAssignmentService
                    CoreAssignmentService.desasignar(
                        u_local.id, o_real.id, fecha_obj, 1,
                        "Fichaje Anulado por Odoo",
                        f"Borrada asignación en {o_real.nombre} por falta de registro en Odoo."
                    )

                # 2. Buscar datos de la NUEVA obra (si lo han movido)
                o_nueva_id = ""
                o_nueva_cod = ""
                o_nueva_nom = ""
                accion = "Borrado en Odoo"

                for key, f in fichajes_unicos.items():
                    if f['odoo_user'] == u_local.odoo_id:
                        o_nueva = Obra.query.filter_by(odoo_id=f['odoo_obra']).first()
                        if o_nueva:
                            o_nueva_id = str(o_nueva.id)
                            o_nueva_cod = str(o_nueva.codigo or '')
                            o_nueva_nom = str(o_nueva.nombre or '')
                            accion = "Modificado de Obra"
                        break

                estado_anterior = reg_local.estado

                # 3. Guardar string estructurado
                datos_string = f"{o_real.id}||{o_real.codigo or ''}||{o_real.nombre}||{o_nueva_id}||{o_nueva_cod}||{o_nueva_nom}||{accion}||{estado_anterior}"

                # 4. Aplicar
                reg_local.estado = 'Sobreescrito_RRHH'
                reg_local.obra_real_id = None 
                reg_local.notas_resolucion = datos_string

        db.session.flush()

        # =========================================================================
        # --- 2. MOTOR DE VALIDACIÓN ---
        # =========================================================================
        from app.models import ConfiguracionGlobal
        conf_primer_fichaje = ConfiguracionGlobal.query.filter_by(clave='aceptar_primer_fichaje').first()
        # Asumimos 'True' por defecto para que funcione como hasta ahora si nadie ha tocado la configuración
        aceptar_primer_fichaje = conf_primer_fichaje.valor == 'True' if conf_primer_fichaje else True
        # -----------------------------------

        for key, f in fichajes_unicos.items():
            local_user = User.query.filter_by(odoo_id=f['odoo_user']).first()
            local_obra = Obra.query.filter_by(odoo_id=f['odoo_obra']).first()
            
            if not local_user or not local_obra:
                continue

            from app.utils.timezone_utils import parse_odoo_datetime, utc_now
            check_in_dt = parse_odoo_datetime(f.get('check_in'))
            check_out_dt = parse_odoo_datetime(f.get('check_out'))

            plan_exacto = Asignacion.query.filter_by(user_id=local_user.id, fecha=fecha_obj, obra_id=local_obra.id).first()
            
            nuevo_estado = ''
            nuevo_plan_id = None
            crear_asignacion_magica = False

            if plan_exacto:
                nuevo_estado = 'Correcto'
                nuevo_plan_id = local_obra.id
            else:
                ultimo_reg = RegistroFichaje.query.filter(
                    RegistroFichaje.user_id == local_user.id,
                    RegistroFichaje.fecha < fecha_obj,
                    RegistroFichaje.estado.in_(['Correcto', 'Correcto_Automatico', 'Resuelto_Movido', 'Resuelto_Asignado', 'Resuelto_Dividido'])
                ).order_by(RegistroFichaje.fecha.desc()).first()
                
                ultima_obra_id = ultimo_reg.obra_real_id if ultimo_reg else None
                
                # --- SUSTITUIR ESTE BLOQUE COMPLETO ---
                if ultima_obra_id == local_obra.id:
                    # Inercia normal: coincide con el historial
                    nuevo_estado = 'Correcto_Automatico'
                    nuevo_plan_id = local_obra.id
                    crear_asignacion_magica = True
                
                elif ultima_obra_id is None:
                    # Es el PRIMER fichaje. Verificamos qué quiere el cliente
                    if aceptar_primer_fichaje:
                        nuevo_estado = 'Correcto_Automatico'
                        nuevo_plan_id = local_obra.id
                        crear_asignacion_magica = True
                    else:
                        # El cliente no lo permite. Se marca como intruso.
                        nuevo_estado = 'Paracaidista'
                        nuevo_plan_id = None
                        crear_asignacion_magica = False
                
                else:
                    # Ficha en obra distinta al historial (Paracaidista estándar)
                    nuevo_estado = 'Paracaidista'
                    nuevo_plan_id = None
                    crear_asignacion_magica = False

            # >>> AÑADIDO 'Ausencia' PARA AUTO-RESOLVER FALTAS AL RECIBIR FICHAJE <<<
            registro_vacio_exacto = RegistroFichaje.query.filter(
                RegistroFichaje.user_id == local_user.id,
                RegistroFichaje.fecha == fecha_obj,
                RegistroFichaje.obra_planificada_id == local_obra.id,
                RegistroFichaje.estado.in_(['Sin_Registro', 'Ausencia'])
            ).first()

            if registro_vacio_exacto:
                # Si el sistema ya le había clavado 'Ausencia', es que llegó tarde
                if registro_vacio_exacto.estado == 'Ausencia':
                    registro_vacio_exacto.estado = 'Retraso'
                    registro_vacio_exacto.notas_resolucion = f"Fichaje recibido después del corte horario. Hora detectada: {check_in_dt.strftime('%H:%M') if check_in_dt else 'N/A'}"
                else:
                    registro_vacio_exacto.estado = nuevo_estado
                    
                registro_vacio_exacto.obra_real_id = local_obra.id
                registro_vacio_exacto.check_in = check_in_dt
                registro_vacio_exacto.check_out = check_out_dt
            else:
                registro_existente = RegistroFichaje.query.filter_by(
                    user_id=local_user.id, fecha=fecha_obj, obra_real_id=local_obra.id
                ).first()
                
                if not registro_existente:
                    # 1. El sistema guarda el fichaje para el cuadrante
                    db.session.add(RegistroFichaje(
                        user_id=local_user.id, fecha=fecha_obj,
                        obra_planificada_id=nuevo_plan_id, obra_real_id=local_obra.id, estado=nuevo_estado,
                        check_in=check_in_dt, check_out=check_out_dt 
                    ))
                    
                    # 2. LA CAJA NEGRA: Grabar en piedra el log físico
                    from app.models import SystemLog
                    db.session.add(SystemLog(
                        timestamp=check_in_dt or utc_now(),
                        category='fichaje_app',
                        action=f"📍 Fichaje Físico [{nuevo_estado.replace('_', ' ')}]",
                        detail=f"El operario fichó en {local_obra.codigo}. Entrada: {check_in_dt.strftime('%H:%M') if check_in_dt else '-'} / Salida: {check_out_dt.strftime('%H:%M') if check_out_dt else '-'}",
                        target_user_id=local_user.id,
                        target_date=fecha_obj
                    ))
                else:
                    if not registro_existente.estado.startswith('Resuelto'):
                        registro_existente.estado = nuevo_estado
                        registro_existente.obra_planificada_id = nuevo_plan_id
                    registro_existente.check_in = check_in_dt
                    registro_existente.check_out = check_out_dt

            if crear_asignacion_magica:
                existe_asig = Asignacion.query.filter_by(user_id=local_user.id, fecha=fecha_obj, obra_id=local_obra.id).first()
                if not existe_asig:
                    from app.services.core_assignment_service import CoreAssignmentService
                    CoreAssignmentService.asignar(
                        local_user.id, local_obra.id, fecha_obj, 1,
                        "Auto-asignación por Fichaje Físico"
                    )

       # =========================================================================
        # >>> NUEVO: AUTO-EVALUAR AUSENCIAS TRAS SINCRONIZAR <<<
        # =========================================================================
        from app.utils.timezone_utils import now_local, today_local
        if fecha_obj == today_local():
            from app.models import ConfiguracionGlobal
            
            conf_hora = ConfiguracionGlobal.query.filter_by(clave='hora_limite_entrada').first()
            hora_str = conf_hora.valor if conf_hora else "08:30"
            
            try:
                hora_corte = datetime.strptime(hora_str, "%H:%M").time()
            except ValueError:
                hora_corte = datetime.strptime("08:30", "%H:%M").time()
            
            ahora_local = now_local()
            
            if ahora_local.time() >= hora_corte:
                sin_registros = RegistroFichaje.query.filter_by(fecha=fecha_obj, estado='Sin_Registro').all()
                for reg in sin_registros:
                    reg.estado = 'Ausencia'
                    reg.notas_resolucion = 'Generada automáticamente tras superar la hora de corte.'
            
            # >>> NUEVO: Si la hora se ha retrasado y AÚN NO es la hora de corte...
            else:
                ausencias_tempranas = RegistroFichaje.query.filter_by(fecha=fecha_obj, estado='Ausencia').all()
                for reg in ausencias_tempranas:
                    # Si no tiene check_in real, significa que fue generada por el sistema. La devolvemos.
                    if not reg.check_in:
                        reg.estado = 'Sin_Registro'
                        reg.notas_resolucion = None

    