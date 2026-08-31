// app/static/js/common.js

var t = window.SP_T || function (key) { return key; };

window.SP_lang = function () {
    var loc = String(window.SP_LOCALE || (document.documentElement && document.documentElement.lang) || 'es');
    return loc.replace('_', '-').toLowerCase().split('-')[0] || 'es';
};

window.SP_dateLocale = function () {
    var map = { es: 'es-ES', en: 'en-GB', pt: 'pt-PT', fr: 'fr-FR' };
    var lang = window.SP_lang();
    return map[lang] || lang || 'es-ES';
};

if (window.moment && typeof window.moment.locale === 'function') {
    try { window.moment.locale(window.SP_lang()); } catch (e) { /* ignore */ }
}

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
 * Select2 con dropdown en body + position:fixed anclado al campo.
 * Evita que overflow/scroll de paneles/modales recorte o “cierre” el listado.
 */
window.SignaPlanSelect2 = window.SignaPlanSelect2 || {
    _reposition($select) {
        if (!$select || !$select.length || !$select.data('select2')) return;
        const $dropdown = $select.data('select2').$dropdown;
        const $container = $select.data('select2').$container;
        if (!$dropdown || !$dropdown.length || !$container || !$container.length) return;
        if (!$dropdown.parent().length) return;
        const rect = $container[0].getBoundingClientRect();
        const dropH = $dropdown.outerHeight() || 280;
        const spaceBelow = window.innerHeight - rect.bottom;
        const openAbove = spaceBelow < Math.min(dropH, 220) && rect.top > spaceBelow;
        const width = Math.max(rect.width, 220);
        $dropdown.css({
            position: 'fixed',
            left: rect.left + 'px',
            width: width + 'px',
            top: openAbove ? 'auto' : (rect.bottom + 2) + 'px',
            bottom: openAbove ? (window.innerHeight - rect.top + 2) + 'px' : 'auto',
            zIndex: 20050,
        });
    },
    bindFixedDropdown($select, scrollRoots) {
        if (!$select || !$select.length || typeof $ === 'undefined' || !$.fn.select2) return;

        // Re-bind limpio si el select se reutiliza tras destroy()
        const prevCleanup = $select.data('signaplan-select2-cleanup');
        if (typeof prevCleanup === 'function') prevCleanup();

        const reposition = () => window.SignaPlanSelect2._reposition($select);
        const onScrollOrResize = () => {
            if ($select.data('select2') && $select.select2('isOpen')) reposition();
        };
        const roots = (scrollRoots || []).filter(Boolean);

        const cleanup = () => {
            roots.forEach((el) => {
                el.removeEventListener('scroll', onScrollOrResize);
            });
            window.removeEventListener('scroll', onScrollOrResize, true);
            window.removeEventListener('resize', onScrollOrResize);
            $select.off('.signaplanFixed');
            $select.removeData('signaplan-select2-fixed');
            $select.removeData('signaplan-select2-cleanup');
        };

        $select.data('signaplan-select2-cleanup', cleanup);
        $select.data('signaplan-select2-fixed', true);

        $select.on('select2:open.signaplanFixed', function () {
            requestAnimationFrame(reposition);
            setTimeout(reposition, 0);
            setTimeout(reposition, 50);
        });
        $select.on('select2:destroy.signaplanFixed', cleanup);

        roots.forEach((el) => {
            el.addEventListener('scroll', onScrollOrResize, { passive: true });
        });
        window.addEventListener('scroll', onScrollOrResize, true);
        window.addEventListener('resize', onScrollOrResize);
    },
};

// Bootstrap modal: no atrapar el foco del buscador Select2 (dropdown en body)
$(document).on('focusin.bs.modal', function (e) {
    if ($(e.target).closest('.select2-container, .select2-dropdown').length) {
        e.stopImmediatePropagation();
    }
});

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

function getAdminTableRowSearchText(row) {
    if (!row || !row.cells) return "";
    var parts = [];
    Array.prototype.forEach.call(row.cells, function (td) {
        if (td.dataset.sortValue) parts.push(td.dataset.sortValue);
        var specialNode = td.querySelector(".jefe-trigger, .jefe-display");
        if (specialNode && !specialNode.classList.contains("d-none")) {
            parts.push(specialNode.textContent || specialNode.innerText || "");
        } else {
            parts.push(td.textContent || td.innerText || "");
        }
    });
    return parts.join(" ").replace(/\s+/g, " ").trim();
}

/** Búsqueda global en móvil: texto en cualquier columna (incl. ocultas en móvil). */
function filterTableAll(tableId, value) {
    var table = document.getElementById(tableId);
    if (!table) return;
    var filter = (value || "").toUpperCase().trim();
    var tbody = table.tBodies[0];
    if (!tbody) return;

    var visible = 0;
    tbody.querySelectorAll("tr").forEach(function (tr) {
        if (tr.classList.contains("table-empty-state")) return;
        if (tr.querySelector("th")) {
            tr.style.display = "none";
            return;
        }
        if (!filter) {
            tr.style.display = "";
            visible++;
            return;
        }
        var haystack = getAdminTableRowSearchText(tr).toUpperCase();
        var match = haystack.indexOf(filter) > -1;
        tr.style.display = match ? "" : "none";
        if (match) visible++;
    });

    var host = table.closest(".admin-table-scroll, .audit-table-wrap, .aus-table-wrap, .admin-panel-flush, .admin-panel");
    if (!host) return;
    var emptyEl = host.querySelector(".sp-mobile-table-search-empty[data-table-id='" + tableId + "']");
    if (!filter) {
        if (emptyEl) emptyEl.hidden = true;
        return;
    }
    if (!emptyEl) {
        emptyEl = document.createElement("p");
        emptyEl.className = "sp-mobile-table-search-empty";
        emptyEl.dataset.tableId = tableId;
        emptyEl.setAttribute("role", "status");
        var searchBar = host.querySelector(".sp-mobile-table-search[data-table-id='" + tableId + "']");
        if (searchBar && searchBar.nextSibling) {
            host.insertBefore(emptyEl, searchBar.nextSibling);
        } else {
            host.appendChild(emptyEl);
        }
    }
    emptyEl.textContent = visible === 0 ? t("Sin resultados") : "";
    emptyEl.hidden = visible !== 0;
}

function initMobileTableSearch() {
    var tFn = window.SP_T || function (key) { return key; };
    document.querySelectorAll("table.filterable-table[id], table.audit-sortable-table[id]").forEach(function (table) {
        var tableId = table.id;
        if (!tableId || table.dataset.mobileSearchReady === "1") return;
        if (!table.tBodies.length || !getAdminTableDataRows(table.tBodies[0]).length) return;

        var host = table.closest(".admin-table-scroll, .audit-table-wrap, .aus-table-wrap, .sync-preview-table-wrap, .sync-log-table-wrap, .ratings-table-wrap, .admin-panel-flush, .admin-panel");
        if (!host || host.querySelector(".sp-mobile-table-search[data-table-id='" + tableId + "']")) return;

        table.dataset.mobileSearchReady = "1";

        var wrap = document.createElement("div");
        wrap.className = "sp-mobile-table-search";
        wrap.dataset.tableId = tableId;
        wrap.innerHTML =
            '<label class="sp-mobile-table-search-field">' +
            '<i class="fas fa-search sp-mobile-table-search-icon" aria-hidden="true"></i>' +
            '<input type="search" class="sp-mobile-table-search-input" ' +
            'placeholder="' + tFn("Buscar…") + '" autocomplete="off" enterkeyhint="search" ' +
            'aria-label="' + tFn("Buscar en la lista") + '">' +
            "</label>" +
            '<button type="button" class="sp-mobile-table-search-clear" hidden ' +
            'aria-label="' + tFn("Limpiar búsqueda") + '">' +
            '<i class="fas fa-times" aria-hidden="true"></i></button>';

        host.insertBefore(wrap, table);

        var input = wrap.querySelector(".sp-mobile-table-search-input");
        var clearBtn = wrap.querySelector(".sp-mobile-table-search-clear");

        function syncClear() {
            var hasValue = !!(input.value || "").trim();
            clearBtn.hidden = !hasValue;
        }

        input.addEventListener("input", function () {
            filterTableAll(tableId, input.value);
            syncClear();
        });
        input.addEventListener("search", function () {
            if (!input.value) filterTableAll(tableId, "");
            syncClear();
        });
        clearBtn.addEventListener("click", function () {
            input.value = "";
            filterTableAll(tableId, "");
            syncClear();
            input.focus();
        });
    });
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

document.addEventListener('DOMContentLoaded', function () {
    captureAllAdminTables();
    initMobileTableSearch();
});

// =========================================================================
// SweetAlert2 — estética admin compartida
// =========================================================================
window.adminSwalDefaults = function(overrides = {}) {
    const base = {
        confirmButtonText: t('Aceptar'),
        cancelButtonText: t('Cancelar'),
        denyButtonText: t('No'),
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
    // Ausencias: leave_dates (no conflict_details por obra)
    if (data.conflict_type === 'leave' && Array.isArray(data.leave_dates) && data.leave_dates.length) {
        const days = data.leave_dates.map((iso) => {
            const parts = String(iso).split('-');
            if (parts.length === 3) return `${parts[2]}/${parts[1]}`;
            return iso;
        });
        const daysText = days.length > 10
            ? `${days.slice(0, 10).join(', ')}... (+${days.length - 10})`
            : days.join(', ');
        detailsHtml += `<li><b>${t('Ausencia aprobada')}</b>: ${daysText}</li>`;
    } else if (data.conflict_details && typeof data.conflict_details === 'object') {
        for (const [obraName, days] of Object.entries(data.conflict_details)) {
            if (!Array.isArray(days) || !days.length) continue;
            let daysText = days.length > 6 ? `${days.slice(0, 6).join(', ')}... (+${days.length - 6})` : days.join(', ');
            detailsHtml += `<li><b>${obraName}</b>: ${daysText}</li>`;
        }
    }
    detailsHtml += '</ul>';

    // Ausencia aprobada: bloqueo duro — no ofrecer sobrescribir/pluriempleo.
    if (data.conflict_type === 'leave') {
        Swal.fire(window.adminSwalDefaults({
            title: t('Trabajador de ausencia'),
            icon: 'info',
            width: '34em',
            showConfirmButton: true,
            confirmButtonText: t('Entendido'),
            html: `
                <p class="mb-2">${data.message || t('No se puede asignar: hay una ausencia aprobada en esas fechas.')}</p>
                <div class="admin-swal-conflict-box">
                    <p class="mb-1 font-weight-bold" style="font-size:0.78rem;color:#334155;">${t('Días afectados')}</p>
                    ${detailsHtml}
                </div>
                <p class="text-muted mb-0" style="font-size:0.85rem;">
                    ${t('Gestiona la ausencia en Ausencias o elige otro trabajador / otras fechas.')}
                </p>
            `,
        })).then(() => { if (onCancelCallback) onCancelCallback(); });
        return;
    }

    let config = window.adminSwalDefaults({
        title: data.conflict_type === 'custody_partial' ? t('Custodia Parcial Detectada') : t('Conflicto de Asignación'),
        icon: 'warning',
        width: '34em',
        showConfirmButton: false,
        showCancelButton: false,
        showDenyButton: false,
        html: `
            <p class="mb-2">${data.message}</p>
            <div class="admin-swal-conflict-box">
                <p class="mb-1 font-weight-bold" style="font-size:0.78rem;color:#334155;">${t('Detalle de los días en conflicto')}</p>
                ${detailsHtml}
            </div>
            <p class="font-weight-bold mb-1" style="font-size:0.78rem;color:#334155;">${t('¿Cómo deseas proceder?')}</p>
            <div id="swal-custom-buttons-global" class="d-flex flex-column w-100"></div>
        `,
        didOpen: () => {
            const container = Swal.getPopup().querySelector('#swal-custom-buttons-global');
            if (data.conflict_type === 'custody_partial') {
                container.innerHTML = `
                    <button type="button" class="admin-swal-btn admin-swal-btn-info" id="btn-todo"><i class="fas fa-paper-plane"></i> ${t('Todo (Asignar + Solicitar)')}</button>
                    <button type="button" class="admin-swal-btn admin-swal-btn-primary" id="btn-solo"><i class="fas fa-shield-alt"></i> ${t('Solo mis días (Ignorar conflicto)')}</button>
                    <button type="button" class="admin-swal-btn admin-swal-btn-ghost" id="btn-cancel">${t('Cancelar acción')}</button>
                `;
                container.querySelector('#btn-todo').onclick = () => { Swal.close(); payload.overwrite_mode = 'assign_and_request'; payload.conflict_resolved = true; onRetryCallback(payload); };
                container.querySelector('#btn-solo').onclick = () => { Swal.close(); payload.overwrite_mode = 'only_custody'; payload.conflict_resolved = true; onRetryCallback(payload); };
            } else {
                container.innerHTML = `
                    <button type="button" class="admin-swal-btn admin-swal-btn-danger" id="btn-over"><i class="fas fa-eraser"></i> ${t('Sobrescribir (Quitar de otras obras)')}</button>
                    <button type="button" class="admin-swal-btn admin-swal-btn-warning" id="btn-pluri"><i class="fas fa-layer-group"></i> ${t('Pluriempleo (Mantener en ambas)')}</button>
                    <button type="button" class="admin-swal-btn admin-swal-btn-primary" id="btn-free"><i class="fas fa-calendar-check"></i> ${t('Asignar solo días libres')}</button>
                    <button type="button" class="admin-swal-btn admin-swal-btn-ghost" id="btn-cancel">${t('Cancelar acción')}</button>
                `;
                container.querySelector('#btn-over').onclick = () => { Swal.close(); payload.overwrite_mode = 'overwrite'; payload.conflict_resolved = true; onRetryCallback(payload); };
                container.querySelector('#btn-pluri').onclick = () => { Swal.close(); payload.overwrite_mode = 'keep_both'; payload.conflict_resolved = true; onRetryCallback(payload); };
                container.querySelector('#btn-free').onclick = () => { Swal.close(); payload.overwrite_mode = 'only_free'; payload.conflict_resolved = true; onRetryCallback(payload); };
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