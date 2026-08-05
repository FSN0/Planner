import sys
sys.path.insert(0, '/opt/soltec/planner')
from app.services.i18n_catalog_app import APP_UI_EN, APP_UI_FR, APP_UI_PT

print('sizes', len(APP_UI_EN), len(APP_UI_FR), len(APP_UI_PT))
same = sum(1 for k, v in APP_UI_FR.items() if APP_UI_EN.get(k) == v and v != k)
print('fr_same_as_en', same)
for k in [
    'Salida',
    'Pendientes de validar',
    'Crear ausencia manual (además del sync ERP)',
    'Sin asignar',
    'Ubicación',
    'Editar',
    'Empresa',
    'Aprobar',
    'Rechazar',
    'Todas las obras',
]:
    print(repr(k), '=>', repr(APP_UI_FR.get(k, '<missing>')))
