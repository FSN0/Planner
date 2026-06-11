import os
import xmlrpc.client
from dotenv import load_dotenv

# Cargar credenciales de tu .env actual

URL = 'https://odoo.soltecgrupo.es'
DB = 'db17-spain'
USER = 'admin'
PASS = 'Soc0233Ssd4223aAs3367'

def get_client():
    print(f"🔄 Conectando a {URL} (BD: {DB})...")
    common = xmlrpc.client.ServerProxy(f'{URL}/xmlrpc/2/common')
    uid = common.authenticate(DB, USER, PASS, {})
    if not uid:
        raise Exception("❌ Autenticación fallida. Revisa el .env")
    models = xmlrpc.client.ServerProxy(f'{URL}/xmlrpc/2/object')
    print("✅ Conectado con éxito.")
    return uid, models

def buscar_modelos(uid, models, palabras_clave):
    print("\n🔍 BUSCANDO MODELOS CANDIDATOS...")
    for palabra in palabras_clave:
        dominio = ['|', ('model', 'ilike', palabra), ('name', 'ilike', palabra)]
        resultados = models.execute_kw(DB, uid, PASS, 'ir.model', 'search_read', [dominio], {'fields': ['model', 'name']})
        
        if resultados:
            print(f"\n--- Resultados para '{palabra}' ---")
            for r in resultados:
                print(f"Modelo Interno: {r['model']} | Nombre descriptivo: {r['name']}")

def analizar_modelo(uid, models, nombre_modelo):
    print(f"\n🔬 ANALIZANDO CAMPOS DEL MODELO: {nombre_modelo}")
    try:
        campos = models.execute_kw(DB, uid, PASS, nombre_modelo, 'fields_get', [], {'attributes': ['string', 'type', 'relation']})
        for technical_name, atributos in campos.items():
            tipo = atributos.get('type')
            relacion = atributos.get('relation', '')
            info_extra = f" -> Relacion con: {relacion}" if relacion else ""
            print(f"- {technical_name} ({tipo}){info_extra} | Etiqueta: {atributos.get('string')}")
    except Exception as e:
        print(f"❌ Error al leer el modelo {nombre_modelo}: {e}")

if __name__ == "__main__":
    try:
        uid, models = get_client()
        
        # Comentamos la búsqueda porque ya hemos cazado a los sospechosos
        # palabras = ['asistencia', 'contrato', 'contract', 'subcontrata']
        # buscar_modelos(uid, models, palabras)

        # Analizamos los dos modelos que nos interesan
        analizar_modelo(uid, models, 'partner.attendance.contract')
        print("\n" + "="*80 + "\n")
        analizar_modelo(uid, models, 'partner.attendance.contract.line')

    except Exception as e:
        print(e)