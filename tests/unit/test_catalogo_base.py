"""Catálogo base de documentación (subcontrata / externos / internos)."""
from app.services.documentacion_service import CATALOGO_BASE


def _por_audiencia(audiencia, ambito=None):
    out = []
    for row in CATALOGO_BASE:
        if row[4] != audiencia:
            continue
        if ambito and row[3] != ambito:
            continue
        out.append(row[0])
    return out


def test_empresa_subcontrata_incluye_mensuales_y_polizas():
    codigos = _por_audiencia('subcontrata', 'empresa')
    for esperado in (
        'escritura_constitucion', 'cif_empresa', 'inscripcion_rea',
        'evaluacion_riesgos', 'acreditacion_prevencion', 'convenio_mutua',
        'poliza_rc', 'poliza_convenio', 'poliza_vigilancia',
        'certificado_hacienda', 'certificado_ss', 'tc1_tc2',
        'certificado_salarios', 'ita', 'listado_trabajadores',
    ):
        assert esperado in codigos


def test_empleado_externo_lista_completa():
    codigos = _por_audiencia('subcontrata', 'empleado')
    for esperado in (
        'prl_6h', 'prl_20h', 'prl_60h',
        'curso_alturas', 'curso_pemp',
        'art_18', 'art_19', 'entrega_epis', 'autorizacion_maquinaria',
        'reconocimiento_medico', 'alta_ta2_idc', 'dni', 'contrato_sepe',
    ):
        assert esperado in codigos
    # Sin fase de contratación: van al bloque Empleado externo
    for row in CATALOGO_BASE:
        if row[0] in codigos:
            assert row[8] == 0, row[0]


def test_empleado_interno_contratacion_completa():
    codigos = _por_audiencia('interno', 'empleado')
    for esperado in (
        'dni_interno', 'sip_ss', 'carnet_conducir',
        'curso_pemp_interno', 'curso_alturas_interno',
        'prl_20h_interno', 'prl_6h_interno', 'prl_60h_interno',
        'art_19_interno', 'reconocimiento_medico_interno',
    ):
        assert esperado in codigos
    by_code = {r[0]: r for r in CATALOGO_BASE}
    assert by_code['dni_interno'][8] == 1
    assert by_code['prl_6h_interno'][8] == 1
    assert by_code['prl_60h_interno'][10] is False  # opcional
    assert by_code['carnet_conducir'][10] is True
    assert by_code['art_19_interno'][8] == 2
    assert by_code['reconocimiento_medico_interno'][8] == 2
    assert by_code['art_19_interno'][9] is True  # bloquea fase
    assert by_code['reconocimiento_medico_interno'][9] is True
