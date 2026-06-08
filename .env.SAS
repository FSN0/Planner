# ==============================================================================
# CONFIGURACIÓN PARA DESARROLLO LOCAL
# ==============================================================================
# Este archivo NO debe subirse a git (ya está en .gitignore)
# Para producción, usa variables de entorno del sistema o un .env diferente

# --- MODO DESARROLLO ---
FLASK_DEBUG=true
CELERY_TASK_ALWAYS_EAGER=true

# --- SECRETOS (para desarrollo, valores simples) ---
# IMPORTANTE: En producción usa valores aleatorios fuertes
SECRET_KEY=mGQm_gNN6rDE9YtW-tPxRN6vxpiol8x2q_P0rFspj4P_9G-VTDqoDBPF841T-cpg
SUPERADMIN_USER=fsn
SUPERADMIN_PASS=fsn123

# --- BASE DE DATOS ---
POSTGRES_PASSWORD=postgres
DATABASE_URL=postgresql://postgres:postgres@db:5432/gestion_obra_saas


# --- ENCRYPTION KEY ---
# CRÍTICO: Si ya tenías una ENCRYPTION_KEY, usa la MISMA aquí.
# Si cambias esta clave, no podrás descifrar datos ya guardados.
# Para generar una nueva (solo si es un proyecto nuevo):
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# 
# Descomenta y pon tu clave existente:
# ENCRYPTION_KEY=tu_clave_fernet_existente_aqui
ENCRYPTION_KEY=ilSA-QHCeeV_aoWa4oFFWVKSz9ezJ1W2pb38uczB8wU=

# --- EMAIL (opcional para desarrollo) ---
# Si no tienes configurado email, la app funciona pero los correos no se envían
MAIL_USERNAME=soltec.app.adm@gmail.com
MAIL_PASSWORD="sgnn bkpf acno cnhv"

# --- ODOO (si usas integración Odoo) ---
ODOO_URL=https://odoo.soltecgrupo.es
ODOO_DB=db17-spain
ODOO_USER=admin
ODOO_PASSWORD=Soc0233Ssd4223aAs3367

# --- DOMINIO (para Caddy/HTTPS) ---
# En desarrollo local déjalo vacío o sin definir
# DOMAIN=
#DOMAIN=http://localhost
FLASK_SECRET_KEY=2fadd5f5bd86144a55d02254bb17aa07cfa2e11318a2a0080b6fa059ebd23162
ODOO_CONTACTOS_URL=http://localhost:5001






# para HTTPS; vacío = solo HTTP local
# Para desarrollo local añade: FL