// app/static/js/common.js

// Configuración global para AJAX (CSRF Token)
// Esto evita errores "400 Bad Request - CSRF token missing" en el futuro
$.ajaxSetup({
    beforeSend: function(xhr, settings) {
        if (!/^(GET|HEAD|OPTIONS|TRACE)$/i.test(settings.type) && !this.crossDomain) {
            var csrf_token = $('meta[name=csrf-token]').attr('content');
            // Si no hay meta tag, intentamos buscarlo en un input hidden común
            if (!csrf_token) {
                csrf_token = $('input[name="csrf_token"]').val();
            }
            if (csrf_token) {
                xhr.setRequestHeader("X-CSRFToken", csrf_token);
            }
        }
    }
});

console.log("Common JS loaded - AJAX Setup Complete");

/**
 * Función maestra para filtrar tablas.
 * Busca texto dentro de la celda o dentro de elementos específicos con clase .jefe-display (para tu listado de obras).
 * @param {string} tableId - ID de la tabla HTML.
 * @param {number} colIndex - Índice de la columna (0, 1, 2...).
 * @param {string} value - El texto que se está escribiendo.
 */
function filterTable(tableId, colIndex, value) {
    var filter = value.toUpperCase();
    var table = document.getElementById(tableId);
    if (!table) return;

    var tr = table.getElementsByTagName("tr");

    // Empezamos loop. Detectamos si es cabecera para saltarla.
    for (var i = 0; i < tr.length; i++) {
        // Si la fila tiene <th>, es cabecera, saltamos.
        if (tr[i].getElementsByTagName("th").length > 0) continue;

        var td = tr[i].getElementsByTagName("td")[colIndex];
        if (td) {
            var txtValue = "";
            
            var specialNode = td.querySelector('.jefe-trigger, .jefe-display');
            if (specialNode && !specialNode.classList.contains('d-none')) {
                txtValue = specialNode.textContent || specialNode.innerText;
            } else {
                txtValue = td.textContent || td.innerText;
            }

            if (txtValue.toUpperCase().indexOf(filter) > -1) {
                tr[i].style.display = "";
            } else {
                tr[i].style.display = "none";
            }
        }
    }
}

// =========================================================================
// ORDENACIÓN DE TABLAS ADMIN (obras, personal, subcontratas…)
// =========================================================================
const _adminTableOriginalOrder = {};

function getAdminTableDataRows(tbody) {
    if (!tbody) return [];
    var rows = Array.from(tbody.querySelectorAll('tr.data-row, tr.audit-data-row'));
    if (rows.length === 0) {
        rows = Array.from(tbody.querySelectorAll('tr.fila-fichaje-auditoria'));
    }
    return rows;
}

function captureAdminTableOrder(tableId) {
    const tbody = document.querySelector('#' + tableId + ' tbody');
    if (!tbody) return;
    _adminTableOriginalOrder[tableId] = getAdminTableDataRows(tbody);
}

function captureAllAdminTables() {
    document.querySelectorAll('table.filterable-table[id], table.audit-sortable-table[id]').forEach(function(table) {
        captureAdminTableOrder(table.id);
    });
}

function resetAdminSortIcons(tableId, exceptTh) {
    document.querySelectorAll('#' + tableId + ' .sortable-col').forEach(function(th) {
        if (th === exceptTh) return;
        th.dataset.sort = 'none';
        const icon = th.querySelector('.sort-icon');
        if (icon) icon.className = 'fas fa-sort sort-icon';
    });
}

function getAdminCellSortValue(row, colIndex) {
    const cell = row.cells[colIndex];
    if (!cell) return '';
    if (cell.dataset.sortValue !== undefined && cell.dataset.sortValue !== '') return cell.dataset.sortValue;
    if (cell.dataset.sort !== undefined && cell.dataset.sort !== '') return cell.dataset.sort;
    return (cell.textContent || '').trim();
}

function getAdminCellSortTier(row, colIndex) {
    const cell = row.cells[colIndex];
    if (!cell || cell.dataset.sortTier === undefined) return 1;
    return parseInt(cell.dataset.sortTier, 10) || 0;
}

/** Parsea fechas en Ymd, ISO, dd/mm/yyyy, dd/mm/yy o dd/mm (año actual). */
function parseAdminDateSortValue(raw) {
    if (raw === null || raw === undefined) return 0;
    var s = String(raw).trim();
    if (!s) return 0;

    if (/^\d{12}$/.test(s)) {
        return new Date(
            parseInt(s.slice(0, 4), 10),
            parseInt(s.slice(4, 6), 10) - 1,
            parseInt(s.slice(6, 8), 10),
            parseInt(s.slice(8, 10), 10),
            parseInt(s.slice(10, 12), 10)
        ).getTime();
    }

    if (/^\d{8}$/.test(s)) {
        return new Date(
            parseInt(s.slice(0, 4), 10),
            parseInt(s.slice(4, 6), 10) - 1,
            parseInt(s.slice(6, 8), 10)
        ).getTime();
    }

    var iso = Date.parse(s);
    if (!isNaN(iso) && /^\d{4}-\d{2}-\d{2}/.test(s)) return iso;

    var m = s.match(/(\d{1,2})\/(\d{1,2})\/(\d{2,4})/);
    if (m) {
        var y = m[3].length === 2 ? 2000 + parseInt(m[3], 10) : parseInt(m[3], 10);
        return new Date(y, parseInt(m[2], 10) - 1, parseInt(m[1], 10)).getTime();
    }

    m = s.match(/(\d{1,2})\/(\d{1,2})\/(\d{2,4})\s+(\d{1,2}):(\d{2})/);
    if (m) {
        var y2 = m[3].length === 2 ? 2000 + parseInt(m[3], 10) : parseInt(m[3], 10);
        return new Date(
            y2, parseInt(m[2], 10) - 1, parseInt(m[1], 10),
            parseInt(m[4], 10), parseInt(m[5], 10)
        ).getTime();
    }

    m = s.match(/(\d{1,2})\/(\d{1,2})/);
    if (m) {
        var year = new Date().getFullYear();
        return new Date(year, parseInt(m[2], 10) - 1, parseInt(m[1], 10)).getTime();
    }

    return 0;
}

function parseAdminTimeSortValue(raw) {
    if (!raw) return 0;
    var s = String(raw).trim().replace(':', '');
    if (/^\d{3,4}$/.test(s)) return parseInt(s, 10);
    var m = s.match(/(\d{1,2}):(\d{2})/);
    if (m) return parseInt(m[1], 10) * 100 + parseInt(m[2], 10);
    return 0;
}

function compareAdminSortValues(valA, valB, sortType) {
    if (sortType === 'date') {
        return parseAdminDateSortValue(valA) - parseAdminDateSortValue(valB);
    }
    if (sortType === 'time') {
        return parseAdminTimeSortValue(valA) - parseAdminTimeSortValue(valB);
    }
    return String(valA).toLowerCase().localeCompare(
        String(valB).toLowerCase(),
        undefined,
        { numeric: true, sensitivity: 'base' }
    );
}

function compareAdminRows(a, b, colIndex, sortType) {
    if (sortType === 'rating') {
        var tierA = getAdminCellSortTier(a, colIndex);
        var tierB = getAdminCellSortTier(b, colIndex);
        if (tierA !== tierB) return tierB - tierA;
    }
    return compareAdminSortValues(
        getAdminCellSortValue(a, colIndex),
        getAdminCellSortValue(b, colIndex),
        sortType === 'rating' ? 'text' : sortType
    );
}

function sortAdminTableWithState(thElement, forcedState) {
    const table = thElement.closest('table');
    if (!table || !table.id) return;
    const tableId = table.id;
    const colIndex = parseInt(thElement.dataset.colIndex, 10);
    const sortType = thElement.dataset.sortType || 'text';
    const tbody = table.querySelector('tbody');
    const rows = getAdminTableDataRows(tbody);
    if (rows.length === 0 || isNaN(colIndex)) return;

    const newState = forcedState;
    const icon = thElement.querySelector('.sort-icon');

    resetAdminSortIcons(tableId, thElement);
    thElement.dataset.sort = newState;

    if (icon) {
        if (newState === 'asc') icon.className = 'fas fa-sort-up sort-icon';
        else if (newState === 'desc') icon.className = 'fas fa-sort-down sort-icon';
        else icon.className = 'fas fa-sort sort-icon';
    }

    if (newState === 'none') {
        const original = _adminTableOriginalOrder[tableId];
        if (original) original.forEach(function(row) { tbody.appendChild(row); });
        return;
    }

    rows.sort(function(a, b) {
        const cmp = compareAdminRows(a, b, colIndex, sortType);
        return newState === 'asc' ? cmp : -cmp;
    });
    rows.forEach(function(row) { tbody.appendChild(row); });
}

function sortAdminTable(thElement) {
    const sortType = thElement.dataset.sortType || 'text';
    const currentState = thElement.dataset.sort || 'none';
    let newState;
    if (sortType === 'date' || sortType === 'time') {
        newState = currentState === 'none' ? 'desc' : currentState === 'desc' ? 'asc' : 'none';
    } else {
        newState = currentState === 'none' ? 'asc' : currentState === 'asc' ? 'desc' : 'none';
    }
    sortAdminTableWithState(thElement, newState);
}

/** Orden por fecha descendente al cargar (auditoría, etc.). */
function applyDefaultDateSort(tableId, colIndex) {
    const th = document.querySelector(
        '#' + tableId + ' thead .sortable-col[data-col-index="' + colIndex + '"]'
    );
    if (!th) return;
    if (!_adminTableOriginalOrder[tableId]) captureAdminTableOrder(tableId);
    sortAdminTableWithState(th, 'desc');
}

function getCsrfToken() {
    var value = "; " + document.cookie;
    var parts = value.split("; csrf_token=");
    if (parts.length === 2) return parts.pop().split(";").shift();
    var meta = document.querySelector('meta[name=csrf-token]');
    return meta ? meta.content : '';
}

function bulkJsonPost(url, payload) {
    return fetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken()
        },
        body: JSON.stringify(payload)
    }).then(function(r) { return r.json(); });
}

function initBulkSelection(config) {
    var table = document.getElementById(config.tableId);
    if (!table) return;

    var selectAll = config.selectAllId ? document.getElementById(config.selectAllId) : null;
    var toolbar = config.toolbarId ? document.getElementById(config.toolbarId) : null;
    var countEl = config.countId ? document.getElementById(config.countId) : null;
    var checkboxSelector = config.checkboxClass.indexOf('.') === 0
        ? config.checkboxClass
        : '.' + config.checkboxClass;

    function update() {
        var checked = table.querySelectorAll(checkboxSelector + ':checked');
        if (countEl) countEl.textContent = checked.length;
        if (toolbar) toolbar.classList.toggle('d-none', checked.length === 0);
        if (checked.length === 0 && selectAll) selectAll.checked = false;
    }

    if (selectAll) {
        selectAll.addEventListener('change', function(e) {
            table.querySelectorAll(checkboxSelector).forEach(function(cb) {
                cb.checked = e.target.checked;
            });
            update();
        });
    }

    table.querySelectorAll(checkboxSelector).forEach(function(cb) {
        cb.addEventListener('change', update);
    });
}

function getCheckedIds(tableId, checkboxClass) {
    var table = document.getElementById(tableId);
    if (!table) return [];
    var sel = checkboxClass.indexOf('.') === 0 ? checkboxClass : '.' + checkboxClass;
    return Array.from(table.querySelectorAll(sel + ':checked')).map(function(cb) {
        return cb.value;
    });
}

document.addEventListener('DOMContentLoaded', captureAllAdminTables);

/**
 * Hace clicables las filas de una tabla; data-href en <tr>.
 * Los enlaces/botones dentro de la fila siguen funcionando con stopPropagation.
 */
function initClickableTableRows(tableId) {
    var table = document.getElementById(tableId);
    if (!table) return;
    var tbody = table.querySelector('tbody');
    if (!tbody) return;
    tbody.addEventListener('click', function(e) {
        if (e.target.closest('a, button, input, select, label, .no-row-nav')) return;
        var row = e.target.closest('tr.row-clickable');
        if (!row || !row.dataset.href) return;
        window.location.href = row.dataset.href;
    });
}

// =========================================================================
// GESTIÓN GLOBAL DE CONFLICTOS DE ASIGNACIÓN
// =========================================================================
window.resolverConflictoAsignacion = function(data, payload, onRetryCallback, onCancelCallback) {
    let detailsHtml = '<ul class="text-left small text-muted mt-2 mb-0" style="padding-left: 20px; list-style-type: disc;">';
    if (data.conflict_details) {
        for (const [obraName, days] of Object.entries(data.conflict_details)) {
            let daysText = days.length > 6 ? `${days.slice(0, 6).join(', ')}... (+${days.length - 6})` : days.join(', ');
            detailsHtml += `<li class="mb-1"><b>${obraName}</b>: ${daysText}</li>`;
        }
    }
    detailsHtml += '</ul>';

    let config = {
        title: data.conflict_type === 'custody_partial' ? 'Custodia Parcial Detectada' : 'Conflicto de Asignación',
        icon: 'warning', width: '34em', showConfirmButton: false, showCancelButton: false, showDenyButton: false,
        html: `
            <p class="text-muted text-sm mb-3">${data.message}</p>
            <div class="text-left bg-light p-2 rounded border shadow-sm mb-3" style="max-height: 180px; overflow-y: auto;">
                <p class="mb-1 text-dark small font-weight-bold">Detalle de los días en conflicto:</p>
                ${detailsHtml}
            </div>
            <p class="small font-weight-bold mb-2">¿Cómo deseas proceder?</p>
            <div id="swal-custom-buttons-global" class="d-flex flex-column gap-2 pb-2"></div>
        `,
        didOpen: () => {
            const container = Swal.getPopup().querySelector('#swal-custom-buttons-global');
            if (data.conflict_type === 'custody_partial') {
                container.innerHTML = `
                    <button class="swal2-confirm swal2-styled w-100 m-0" style="background-color: #3b82f6;" id="btn-todo"><i class="fas fa-paper-plane mr-1"></i> Todo (Asignar + Solicitar)</button>
                    <button class="swal2-deny swal2-styled w-100 m-0 mt-2" style="background-color: #10b981;" id="btn-solo"><i class="fas fa-shield-alt mr-1"></i> Solo mis días (Ignorar conflicto)</button>
                    <button class="swal2-cancel swal2-styled w-100 m-0 mt-2" id="btn-cancel">Cancelar Acción</button>
                `;
                container.querySelector('#btn-todo').onclick = () => { Swal.close(); payload.overwrite_mode = 'assign_and_request'; onRetryCallback(payload); };
                container.querySelector('#btn-solo').onclick = () => { Swal.close(); payload.overwrite_mode = 'only_custody'; onRetryCallback(payload); };
            } else {
                container.innerHTML = `
                    <button class="swal2-confirm swal2-styled w-100 m-0" style="background-color: #ef4444;" id="btn-over"><i class="fas fa-eraser mr-1"></i> Sobrescribir (Quitar de otras obras)</button>
                    <button class="swal2-deny swal2-styled w-100 m-0 mt-2" style="background-color: #f59e0b;" id="btn-pluri"><i class="fas fa-layer-group mr-1"></i> Pluriempleo (Mantener en ambas)</button>
                    <button class="swal2-confirm swal2-styled w-100 m-0 mt-2" style="background-color: #10b981;" id="btn-free"><i class="fas fa-calendar-check mr-1"></i> Asignar solo días libres</button>
                    <button class="swal2-cancel swal2-styled w-100 m-0 mt-2" id="btn-cancel">Cancelar Acción</button>
                `;
                container.querySelector('#btn-over').onclick = () => { Swal.close(); payload.overwrite_mode = 'overwrite'; onRetryCallback(payload); };
                container.querySelector('#btn-pluri').onclick = () => { Swal.close(); payload.overwrite_mode = 'keep_both'; onRetryCallback(payload); };
                container.querySelector('#btn-free').onclick = () => { Swal.close(); payload.overwrite_mode = 'only_free'; onRetryCallback(payload); };
            }
            container.querySelector('#btn-cancel').onclick = () => { Swal.close(); if(onCancelCallback) onCancelCallback(); };
        }
    };
    Swal.fire(config);
};