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

// =========================================================================
// SweetAlert2 — estética admin compartida
// =========================================================================
window.adminSwalDefaults = function(overrides = {}) {
    const base = {
        customClass: {
            popup: 'admin-swal-popup',
            title: 'admin-swal-title',
            htmlContainer: 'admin-swal-html',
            confirmButton: 'admin-swal-btn admin-swal-btn-primary',
            denyButton: 'admin-swal-btn admin-swal-btn-warning',
            cancelButton: 'admin-swal-btn admin-swal-btn-ghost',
            actions: 'admin-swal-actions',
        },
        buttonsStyling: false,
    };
    if (overrides.customClass) {
        base.customClass = Object.assign({}, base.customClass, overrides.customClass);
        const rest = Object.assign({}, overrides);
        delete rest.customClass;
        return Object.assign(base, rest);
    }
    return Object.assign(base, overrides);
};

// =========================================================================
// GESTIÓN GLOBAL DE CONFLICTOS DE ASIGNACIÓN
// =========================================================================
window.resolverConflictoAsignacion = function(data, payload, onRetryCallback, onCancelCallback) {
    let detailsHtml = '<ul>';
    if (data.conflict_details) {
        for (const [obraName, days] of Object.entries(data.conflict_details)) {
            let daysText = days.length > 6 ? `${days.slice(0, 6).join(', ')}... (+${days.length - 6})` : days.join(', ');
            detailsHtml += `<li><b>${obraName}</b>: ${daysText}</li>`;
        }
    }
    detailsHtml += '</ul>';

    let config = window.adminSwalDefaults({
        title: data.conflict_type === 'custody_partial' ? 'Custodia Parcial Detectada' : 'Conflicto de Asignación',
        icon: 'warning',
        width: '34em',
        showConfirmButton: false,
        showCancelButton: false,
        showDenyButton: false,
        html: `
            <p class="mb-2">${data.message}</p>
            <div class="admin-swal-conflict-box">
                <p class="mb-1 font-weight-bold" style="font-size:0.78rem;color:#334155;">Detalle de los días en conflicto</p>
                ${detailsHtml}
            </div>
            <p class="font-weight-bold mb-1" style="font-size:0.78rem;color:#334155;">¿Cómo deseas proceder?</p>
            <div id="swal-custom-buttons-global" class="d-flex flex-column w-100"></div>
        `,
        didOpen: () => {
            const container = Swal.getPopup().querySelector('#swal-custom-buttons-global');
            if (data.conflict_type === 'custody_partial') {
                container.innerHTML = `
                    <button type="button" class="admin-swal-btn admin-swal-btn-info" id="btn-todo"><i class="fas fa-paper-plane"></i> Todo (Asignar + Solicitar)</button>
                    <button type="button" class="admin-swal-btn admin-swal-btn-primary" id="btn-solo"><i class="fas fa-shield-alt"></i> Solo mis días (Ignorar conflicto)</button>
                    <button type="button" class="admin-swal-btn admin-swal-btn-ghost" id="btn-cancel">Cancelar acción</button>
                `;
                container.querySelector('#btn-todo').onclick = () => { Swal.close(); payload.overwrite_mode = 'assign_and_request'; onRetryCallback(payload); };
                container.querySelector('#btn-solo').onclick = () => { Swal.close(); payload.overwrite_mode = 'only_custody'; onRetryCallback(payload); };
            } else {
                container.innerHTML = `
                    <button type="button" class="admin-swal-btn admin-swal-btn-danger" id="btn-over"><i class="fas fa-eraser"></i> Sobrescribir (Quitar de otras obras)</button>
                    <button type="button" class="admin-swal-btn admin-swal-btn-warning" id="btn-pluri"><i class="fas fa-layer-group"></i> Pluriempleo (Mantener en ambas)</button>
                    <button type="button" class="admin-swal-btn admin-swal-btn-primary" id="btn-free"><i class="fas fa-calendar-check"></i> Asignar solo días libres</button>
                    <button type="button" class="admin-swal-btn admin-swal-btn-ghost" id="btn-cancel">Cancelar acción</button>
                `;
                container.querySelector('#btn-over').onclick = () => { Swal.close(); payload.overwrite_mode = 'overwrite'; onRetryCallback(payload); };
                container.querySelector('#btn-pluri').onclick = () => { Swal.close(); payload.overwrite_mode = 'keep_both'; onRetryCallback(payload); };
                container.querySelector('#btn-free').onclick = () => { Swal.close(); payload.overwrite_mode = 'only_free'; onRetryCallback(payload); };
            }
            container.querySelector('#btn-cancel').onclick = () => { Swal.close(); if(onCancelCallback) onCancelCallback(); };
        }
    });
    Swal.fire(config);
};

/**
 * Filas de tabla clicables (navegan a data-row-href o data-href en <tr>).
 * Ignora clics en enlaces, botones, inputs y columna de checkbox.
 */
function initClickableTableRows(tableId) {
    var table = document.getElementById(tableId);
    if (!table) return;
    table.querySelectorAll('tbody tr[data-row-href], tbody tr[data-href]').forEach(function(row) {
        row.classList.add('table-row-clickable');
        row.setAttribute('tabindex', '0');
        row.setAttribute('role', 'link');
        function go() {
            var href = row.getAttribute('data-row-href') || row.getAttribute('data-href');
            if (href) window.location.href = href;
        }
        row.addEventListener('click', function(e) {
            if (e.target.closest('a, button, input, select, textarea, label, .btn-table-action, .col-check, .table-actions, .jefe-trigger, .no-row-nav')) {
                return;
            }
            go();
        });
        row.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                go();
            }
        });
    });
}