from types import SimpleNamespace

from app.services.tour_catalog_service import (
    INITIAL_TOUR_IDS,
    SHARED_TOUR_IDS,
    STATUS_DONE,
    STATUS_IN_PROGRESS,
    evaluate_academia,
)


def test_recorrido_inicial_orden_obra_antes_persona():
    assert INITIAL_TOUR_IDS == (
        'tablero_leer',
        'tablero_asignar',
        'obra',
        'trabajadores',
        'fichaje',
    )


def test_calendario_no_es_tutorial_aparte():
    assert 'calendario' not in SHARED_TOUR_IDS
    assert 'calendario' not in INITIAL_TOUR_IDS
    assert 'fichajes' not in SHARED_TOUR_IDS
    assert SHARED_TOUR_IDS == ('planificador_multi', 'flota')


def _metrics(**over):
    base = {
        'obras': 5,
        'operarios': 5,
        'vehiculos': 1,
        'fichajes': 2,
        'fichaje_activo': True,
        'has_odoo': False,
        'has_registro_jornada': True,
        'has_flota_module': True,
        'demo_activa': True,
    }
    base.update(over)
    return base


def _patch_academia(monkeypatch, progress):
    monkeypatch.setattr(
        'app.services.tour_catalog_service.tenant_tiene_onboarding', lambda: True,
    )
    monkeypatch.setattr(
        'app.services.tour_catalog_service.onboarding_marcado_completo', lambda: True,
    )
    monkeypatch.setattr(
        'app.services.tour_catalog_service.import_tutorials_done',
        lambda: {
            'obras': False,
            'users_internos': False,
            'users_externos': False,
            'companies': False,
        },
    )
    monkeypatch.setattr(
        'app.services.tour_catalog_service.get_onboarding_path', lambda: 'demo',
    )
    monkeypatch.setattr('app.services.tour_catalog_service._save_progress', lambda p: None)
    monkeypatch.setattr(
        'app.services.tour_catalog_service._module_visible', lambda m, u: True,
    )
    monkeypatch.setattr(
        'app.services.tour_catalog_service.tenant_metrics', lambda: _metrics(),
    )
    monkeypatch.setattr(
        'app.services.tour_catalog_service._load_raw_progress', lambda: progress,
    )
    monkeypatch.setattr(
        'app.services.tour_catalog_service.url_for',
        lambda *a, **k: '/admin/primeros-pasos',
    )


def test_saltar_recorrido_no_marca_calendario_ni_fichaje(monkeypatch):
    """Cerrar seed/onboarding no debe fingir que hiciste calendario o fichaje."""
    progress = {
        'seed': {'status': STATUS_DONE, 'at': '2026-08-28T08:00:00'},
        'tablero_leer': {'status': STATUS_DONE, 'at': '2026-08-28T08:01:00'},
        'tablero_asignar': {'status': STATUS_DONE, 'at': '2026-08-28T08:02:00'},
        'obra': {'status': STATUS_DONE, 'at': '2026-08-28T08:03:00'},
        'trabajadores': {'status': STATUS_DONE, 'at': '2026-08-28T08:04:00'},
        'fichaje': {'status': STATUS_IN_PROGRESS, 'started_at': '2026-08-28T08:05:00'},
    }
    _patch_academia(monkeypatch, progress)
    snap = evaluate_academia(user=SimpleNamespace(role='admin'))
    by_id = {c['id']: c for c in snap['chapters']}
    assert by_id['fichaje']['status'] == STATUS_IN_PROGRESS
    assert by_id['calendario']['status'] != STATUS_DONE
    cam = snap['caminitos']
    assert cam['guide_done'] is False
    assert cam['resume'] and cam['resume']['id'] == 'fichaje'


def test_recorrido_hecho_solo_si_los_cinco_capitulos_estan_hechos(monkeypatch):
    progress = {
        'seed': {'status': STATUS_DONE},
        'tablero_leer': {'status': STATUS_DONE},
        'tablero_asignar': {'status': STATUS_DONE},
        'obra': {'status': STATUS_DONE},
        'trabajadores': {'status': STATUS_DONE},
        'fichaje': {'status': STATUS_DONE},
    }
    _patch_academia(monkeypatch, progress)
    snap = evaluate_academia(user=SimpleNamespace(role='admin'))
    cam = snap['caminitos']
    assert cam['guide_done'] is True
    assert cam['resume'] is None
    by_id = {c['id']: c for c in snap['chapters']}
    assert by_id['calendario']['status'] != STATUS_DONE


def test_resume_no_se_salta_crear_persona(monkeypatch):
    """Si obra está hecha, el siguiente es persona aunque fichaje quedara en curso."""
    progress = {
        'seed': {'status': STATUS_DONE},
        'tablero_leer': {'status': STATUS_DONE},
        'tablero_asignar': {'status': STATUS_DONE},
        'obra': {'status': STATUS_DONE},
        'fichaje': {'status': STATUS_IN_PROGRESS},
    }
    _patch_academia(monkeypatch, progress)
    snap = evaluate_academia(user=SimpleNamespace(role='admin'))
    by_id = {c['id']: c for c in snap['chapters']}
    assert by_id['trabajadores']['status'] != STATUS_DONE
    assert by_id['fichaje']['status'] != STATUS_IN_PROGRESS
    cam = snap['caminitos']
    assert cam['resume'] and cam['resume']['id'] == 'trabajadores'


def test_obra_no_abre_el_formulario():
    from app.services.tour_catalog_service import catalog_definitions
    obra = next(d for d in catalog_definitions() if d['id'] == 'obra')
    assert obra['entry_endpoint'] == 'admin.obras_detailed'
    persona = next(d for d in catalog_definitions() if d['id'] == 'trabajadores')
    assert persona['entry_endpoint'] == 'admin.obras_detailed'
