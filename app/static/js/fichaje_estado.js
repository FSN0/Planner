/**
 * Colores/estados de pelotita de fichaje — espejo de fichaje_estado_service.py
 * Fuente canónica en Python; este JS debe mantenerse alineado.
 */
window.SPFichajeEstado = (function () {
    var t = window.SP_T || function (key) { return key; };
    var OK = {
        Correcto: 1, Correcto_Automatico: 1, Cambio_Tajo: 1,
        Resuelto_Movido: 1, Resuelto_Asignado: 1, Resuelto_Dividido: 1,
        Resuelto_Ignorado: 1, Resuelto_Falta: 1, Resuelto_Ausencia: 1,
        Exento_Ausencia: 1, Cerrado_Multiobra: 1,
    };
    var INTERVENCION = { Sobreescrito_RRHH: 1 };
    var ROJO = { Conflicto: 1, Paracaidista: 1 };
    var NARANJA = { Ausencia: 1, Pendiente: 1, Retraso: 1 };
    var COLOR = {
        rojo: '#ef4444',
        naranja: '#f59e0b',
        verde: '#10b981',
        violeta: '#7c3aed',
        gris: '#94a3b8',
    };

    function esOk(est) {
        return !!(OK[est] || (est || '').indexOf('Resuelto') === 0);
    }

    function colorDeEstado(estado) {
        if (ROJO[estado]) return COLOR.rojo;
        if (NARANJA[estado] || estado === 'Pendiente') return COLOR.naranja;
        if (INTERVENCION[estado] || estado === 'Exento_Ausencia') return COLOR.violeta;
        if (esOk(estado)) return COLOR.verde;
        if (estado === 'Sin_Registro') return COLOR.gris;
        return COLOR.naranja;
    }

    function labelDeEstado(estado) {
        var labels = {
            Correcto: t('Correcto'),
            Correcto_Automatico: t('Correcto (auto)'),
            Cambio_Tajo: t('Cambio de tajo'),
            Conflicto: t('Conflicto'),
            Paracaidista: t('Paracaidista'),
            Ausencia: t('Ausencia'),
            Pendiente: t('Pendiente'),
            Retraso: t('Retraso'),
            Sin_Registro: t('Sin fichaje'),
            Sobreescrito_RRHH: t('Corregido por RRHH / ERP'),
            Exento_Ausencia: t('Exento (ausencia)'),
            Cerrado_Multiobra: t('Multi-obra cerrado'),
            Resuelto_Movido: t('Resuelto (movido)'),
            Resuelto_Asignado: t('Resuelto (asignado)'),
            Resuelto_Dividido: t('Resuelto (multi-obra)'),
            Resuelto_Ignorado: t('Resuelto (ignorado)'),
            Resuelto_Falta: t('Resuelto (falta)'),
            Resuelto_Ausencia: t('Resuelto (ausencia)'),
        };
        if ((estado || '').indexOf('Resuelto') === 0) return labels[estado] || t('Resuelto / correcto');
        return labels[estado] || estado || t('Sin datos');
    }

    function badgeClass(estado) {
        if (ROJO[estado]) return 'badge-soft-red';
        if (NARANJA[estado] || estado === 'Pendiente') return 'badge-soft-amber';
        if (INTERVENCION[estado] || estado === 'Exento_Ausencia') return 'badge-soft-blue';
        if (esOk(estado)) return 'badge-soft-green';
        return 'badge-soft-gray';
    }

    return {
        colorDeEstado: colorDeEstado,
        labelDeEstado: labelDeEstado,
        badgeClass: badgeClass,
        esOk: esOk,
        COLOR: COLOR,
    };
})();
