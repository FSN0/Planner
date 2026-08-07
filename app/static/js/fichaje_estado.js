/**
 * Colores/estados de pelotita de fichaje — espejo de fichaje_estado_service.py
 * Fuente canónica en Python; este JS debe mantenerse alineado.
 */
window.SPFichajeEstado = (function () {
    var OK = {
        Correcto: 1, Correcto_Automatico: 1,
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
            Correcto: 'Correcto',
            Correcto_Automatico: 'Correcto (auto)',
            Conflicto: 'Conflicto',
            Paracaidista: 'Paracaidista',
            Ausencia: 'Ausencia',
            Pendiente: 'Pendiente',
            Retraso: 'Retraso',
            Sin_Registro: 'Sin fichaje',
            Sobreescrito_RRHH: 'Corregido por RRHH / ERP',
            Exento_Ausencia: 'Exento (ausencia)',
            Cerrado_Multiobra: 'Multi-obra cerrado',
            Resuelto_Movido: 'Resuelto (movido)',
            Resuelto_Asignado: 'Resuelto (asignado)',
            Resuelto_Dividido: 'Resuelto (multi-obra)',
            Resuelto_Ignorado: 'Resuelto (ignorado)',
            Resuelto_Falta: 'Resuelto (falta)',
            Resuelto_Ausencia: 'Resuelto (ausencia)',
        };
        if ((estado || '').indexOf('Resuelto') === 0) return labels[estado] || 'Resuelto / correcto';
        return labels[estado] || estado || 'Sin datos';
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
