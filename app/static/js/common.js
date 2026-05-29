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
            
            // Lógica específica para tus celdas complejas (Jefe de obra)
            // Si existe un elemento .jefe-display visible, usamos ese texto.
            var specialNode = td.querySelector('.jefe-display');
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