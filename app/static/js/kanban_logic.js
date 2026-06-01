// app/static/js/kanban_logic.js

$(document).ready(function() {

    // =========================================================================
    // 0. CONFIGURACIÓN CENTRALIZADA Y VARIABLES GLOBALES
    // =========================================================================
    let modalCalendarInstance = null;
    let libresCalendarInstance = null;

    // =========================================================================
    // 1. EVENTOS: APERTURA DE MODALES (DRAG & DROP)
    // =========================================================================

    $(".worker-chip").draggable({
        revert: "invalid", helper: "clone", appendTo: "body", zIndex: 9999, scroll: false,
        start: function() { $(this).addClass('dragging-source'); },
        stop: function() { $(this).removeClass('dragging-source'); }
    });

    $(".worker-list-body").droppable({
        accept: ".worker-chip", tolerance: "pointer", hoverClass: "droppable-hover",
        drop: function(event, ui) {
            const workerId = ui.draggable.data("worker-id");
            const workerName = ui.draggable.data("worker-name");
            const targetObraId = $(this).data("obra-id");
            const targetObraName = $(this).data("obra-name");
            const $source = ui.draggable.closest('.worker-list-body');
            const sourceObraId = $source.data('obra-id'); 

            if (sourceObraId == targetObraId) return;

            if (targetObraId == 0) {
                // CASO A: MOVER A LIBRES
                openUnassignModalWithCalendar(workerId, workerName, sourceObraId, $source.data('obra-name'));
            } else {
                // CASO B: MOVER A OBRA
                openConcreteModal(workerId, workerName, targetObraId, targetObraName, sourceObraId); 
            }
        }
    });

    // =========================================================================
    // 2. LÓGICA DEL CALENDARIO UNIVERSAL: ASIGNAR A OBRA (CON CAMBIO DE VISTA)
    // =========================================================================
    
    function renderAssignmentCalendar(viewType, workerId, workerName, targetObraId, obraName, sourceObraId) {
        if (modalCalendarInstance) modalCalendarInstance.destroy();
        
        let context = viewType; // 'obra' o 'worker'
        let entityId = (viewType === 'obra') ? targetObraId : workerId;
        
        // CORRECCIÓN DEL BUG: Usamos el nombre que toca según la vista
        let eName = (viewType === 'obra') ? obraName : workerName;
        let mode = (viewType === 'obra') ? 'empresas' : 'obras';

        modalCalendarInstance = new UniversalCalendarManager('modal-calendar-container', {
            context: context,
            id: entityId,
            mode: mode,
            entityName: eName
        });
    }

    window.openConcreteModal = function(workerId, workerName, targetObraId, obraName, sourceObraId) {
        $('#modalWorkerId').val(workerId);
        $('#modalTargetObraId').val(targetObraId);
        $('#modalWorkerDisplay').text(workerName);
        $('#modalObraDisplay').text(obraName);
        
        // Reset visual de los botones
        $('#btnViewObra').addClass('active btn-primary').removeClass('btn-outline-primary');
        $('#btnViewWorker').removeClass('active btn-primary').addClass('btn-outline-primary');

        $('#assignmentModal').modal('show');
        
        setTimeout(() => {
            // Renderiza por defecto el destino
            renderAssignmentCalendar('obra', workerId, workerName, targetObraId, obraName, sourceObraId);
            
            // Listeners para los botones de cambio de vista
            $('#btnViewObra').off('click').on('click', function() {
                $(this).addClass('active btn-primary').removeClass('btn-outline-primary');
                $('#btnViewWorker').removeClass('active btn-primary').addClass('btn-outline-primary');
                renderAssignmentCalendar('obra', workerId, workerName, targetObraId, obraName, sourceObraId);
            });

            $('#btnViewWorker').off('click').on('click', function() {
                $(this).addClass('active btn-primary').removeClass('btn-outline-primary');
                $('#btnViewObra').removeClass('active btn-primary').addClass('btn-outline-primary');
                renderAssignmentCalendar('worker', workerId, workerName, targetObraId, obraName, sourceObraId);
            });

        }, 300);
    };

    // =========================================================================
    // 3. PUENTE UNIVERSAL: RESOLVEDOR DE CONFLICTOS Y AJAX
    // =========================================================================
    window.enviarAccionKanban = function(payload, revertFunc) {
        if (!payload.overwrite_mode) payload.overwrite_mode = 'check';
        payload.check_conflicts = true; 

        $.ajax({
            url: "/api/v6/planificador/action",
            type: "POST",
            contentType: "application/json",
            data: JSON.stringify(payload),
            success: function(data) {
                if (data.success) {
                    Swal.fire({toast: true, position: 'top-end', icon: 'success', title: 'Guardado', showConfirmButton: false, timer: 1500});
                    $('#assignmentModal').modal('hide');
                    
                    // --- MAGIA SPA: MOVER EL CHIP SIN RECARGAR LA PÁGINA ---
                    let chip = $(`.worker-chip[data-worker-id="${payload.worker_id}"]`);
                    let targetCol = $(`.worker-list-body[data-obra-id="${payload.target_obra_id}"]`);
                    
                    if (chip.length && targetCol.length) {
                        chip.detach().appendTo(targetCol); // Mueve la ficha de columna
                        chip.css({'transition': 'background-color 0.5s', 'background-color': '#d4edda'});
                        setTimeout(() => chip.css('background-color', ''), 1000);
                    }
                } 
                else if (data.conflict) {
                    window.resolverConflictoAsignacion(data, payload, 
                        (nuevoPayload) => { enviarAccionKanban(nuevoPayload, revertFunc); }, 
                        revertFunc
                    );
                } else {
                    Swal.fire('Error', data.error || data.message || 'Error desconocido', 'error');
                    if (revertFunc) revertFunc();
                }
            },
            error: function() {
                Swal.fire('Error', 'Fallo de conexión', 'error');
                if (revertFunc) revertFunc();
            }
        });
    };

    // =========================================================================
    // 4. LÓGICA DEL CALENDARIO UNIVERSAL: MOVER A LIBRES (DESASIGNAR)
    // =========================================================================
    window.openUnassignModalWithCalendar = function(workerId, workerName, sourceObraId, sourceObraName) {
        $('#libresWorkerId').val(workerId);
        $('#libresSourceObraId').val(sourceObraId);
        $('#libresWorkerName').text(workerName);
        $('#libresSourceName').text(sourceObraName || 'Obra desconocida');
        
        $('#chk-libres-all').prop('checked', false);
        $('#btn-toggle-container').removeClass('active-state');
        $('#lbl-libres-text').removeClass('text-white').addClass('text-danger');

        $('#modalMoveToLibres').modal('show');

        setTimeout(() => {
            if (libresCalendarInstance) libresCalendarInstance.destroy();
            
            let container = document.getElementById('libres-calendar-container');
            if(container) {
                container.style.height = '480px';
                container.style.background = 'white';
                container.innerHTML = ''; 
            }

            libresCalendarInstance = new UniversalCalendarManager('libres-calendar-container', {
                context: 'worker',
                id: workerId,
                entityName: workerName,
                mode: 'obras',
            });
        }, 300);
    };

    window.submitUnassignFromLibres = function() {
        var deleteAll = $('#chk-libres-all').is(':checked');

        if (!deleteAll) {
            Swal.fire('Atención', "Para desasignar días sueltos usa el calendario directamente. Este botón es exclusivo para procesar la 'Baja Total'.", 'info');
            return;
        }

        var workerId = $('#libresWorkerId').val();
        var obraId = $('#libresSourceObraId').val();
        var $btn = $('#modalMoveToLibres .btn-primary');
        
        $btn.prop('disabled', true).text('Procesando...');

        $.ajax({
            url: "/api/v6/unassign_worker", // URL NUEVA UNIFICADA
            type: "POST",
            contentType: "application/json",
            data: JSON.stringify({ worker_id: workerId, obra_id: obraId, mode: 'all_obra', dates: [] }),
            success: function(res) {
                if (res.success) { location.reload(); } 
                else { alert("Error: " + res.message); $btn.prop('disabled', false).text('Confirmar'); }
            },
            error: function() {
                alert("Error de conexión");
                $btn.prop('disabled', false).text('Confirmar');
            }
        });
    };

    // =========================================================================
    // 5. LÓGICA DE STAFF Y OTRAS UTILIDADES SECUNDARIAS
    // =========================================================================

    // Cambio Rápido Staff
    $(document).on('click', '.editable-staff', function() {
        var obraId = $(this).data('obra-id');
        var role = $(this).data('role'); 
        var currentId = $(this).data('current-id');
        var obraName = $(this).data('obra-name'); 
        
        var $span = $(this); 
        $('#staffObraId').val(obraId); $('#staffRoleType').val(role);
        $('#modalStaffTitle').text(role === 'jefe' ? 'Cambiar Jefe de Obra' : 'Cambiar Encargado');
        $('#staffObraNameDisplay').text(obraName ? obraName : 'Obra sin nombre');
        
        var $select = $('#staffSelect').empty();
        var dataList = (role === 'jefe') ? (window.LISTA_JEFES || []) : (window.LISTA_ENCARGADOS || []);
        $select.append(new Option("-- Sin Asignar --", "", false, !currentId));
        dataList.forEach(item => {
            $select.append(new Option(item.text, item.id, false, String(item.id) === String(currentId)));
        });
        
        $('#modalEditStaff').data('trigger-element', $span).modal('show');
    });

    window.submitStaffChange = function() {
        var obraId = $('#staffObraId').val();
        var role = $('#staffRoleType').val();
        var userId = $('#staffSelect').val(); 
        var $btn = $('#modalEditStaff button.btn-primary').prop('disabled', true).text('Guardando...');
        
        $.ajax({
            url: '/admin/api/update_obra_staff', type: 'POST', contentType: 'application/json',
            data: JSON.stringify({ obra_id: obraId, role_type: role, user_id: userId }),
            success: function(res) {
                if (res.success) {
                    $('#modalEditStaff').modal('hide');
                    var $span = $('#modalEditStaff').data('trigger-element');
                    $span.data('current-id', userId); 
                    if (!userId) {
                        $span.html('<span class="text-muted font-italic">' + ((role === 'jefe') ? 'Sin jefe' : 'Sin encargado') + '</span>');
                    } else {
                        $span.text(res.new_name);
                    }
                    $span.css('background-color', '#d4edda');
                    setTimeout(() => $span.css('background-color', 'transparent'), 1000);
                } else alert("Error: " + res.error);
            },
            complete: () => $btn.prop('disabled', false).text('Guardar Cambios')
        });
    };

    // AutoScroll del Kanban
    try {
        autoScroll([document.querySelector('#kanbanContainer')], {
            margin: 50, maxSpeed: 20, scrollWhenOutside: true,
            autoScroll: () => Boolean($('.ui-draggable-dragging').length)
        });
    } catch(e) { }

    // Filtros Kanban
    var activeFilters = [];
    $('#kanbanFilterInput').on('keydown', function(e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            var term = $(this).val().trim().toLowerCase();
            if (term && !activeFilters.includes(term)) {
                activeFilters.push(term); renderTags(); applyKanbanFilters();
                $(this).val('');
            }
        }
    });
    window.removeFilterTag = function(term) {
        activeFilters = activeFilters.filter(t => t !== term);
        renderTags(); applyKanbanFilters();
    };
    window.clearKanbanFilters = function() {
        activeFilters = []; renderTags(); applyKanbanFilters();
    };
    function renderTags() {
        $('#activeFiltersList').empty().append(activeFilters.map(t => 
            `<div class="filter-tag">${t} <span class="remove-tag" onclick="removeFilterTag('${t}')">&times;</span></div>`
        ));
        activeFilters.length > 0 ? $('#btnClearFilters').show() : $('#btnClearFilters').hide();
    }
    function applyKanbanFilters() {
        if (activeFilters.length === 0) return $('.filterable-obra').show();
        $('.filterable-obra').each(function() {
            var text = ($(this).data('search-text') || "").toLowerCase();
            activeFilters.some(t => text.includes(t)) ? $(this).show() : $(this).hide();
        });
    }

    // =========================================================================
    // 6. GESTIÓN DE PINES Y ORDENACIÓN DE OBRAS
    // =========================================================================

    $(document).on('click', '.btn-pin-obra', function(e) {
        e.stopPropagation(); 
        var $icon = $(this);
        var obraId = $icon.data('obra-id');
        
        $icon.toggleClass('text-primary text-muted-light');

        $.ajax({
            url: '/api/v6/toggle_pin_obra',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ obra_id: obraId }),
            success: function(res) {
                window.location.reload(); 
            },
            error: function(xhr) {
                console.error("Error pinning:", xhr.responseText);
                alert("Error al guardar preferencia.");
                $icon.toggleClass('text-primary text-muted-light');
            }
        });
    });

    if ($("#kanbanWorksWrapper").length > 0) {
        $("#kanbanWorksWrapper").sortable({
            items: ".kanban-col-wrapper.is-pinned", 
            handle: ".col-header",
            placeholder: "ui-state-highlight",
            tolerance: "pointer",
            axis: "x",
            containment: "parent",
            cursor: "grabbing",
            forcePlaceholderSize: true,
            
            start: function(e, ui) {
                ui.placeholder.height(ui.item.outerHeight());
                ui.placeholder.width(ui.item.outerWidth());
            },
            
            stop: function(e, ui) {
                var orderedIds = [];
                $("#kanbanWorksWrapper .kanban-col-wrapper.is-pinned").each(function() {
                    orderedIds.push($(this).data('id'));
                });

                $.ajax({
                    url: '/api/v6/reorder_pinned_obras',
                    type: 'POST',
                    contentType: 'application/json',
                    data: JSON.stringify({ ordered_ids: orderedIds }),
                    success: function() { console.log("Orden guardado"); }
                });
            }
        });
        $("#kanbanWorksWrapper").disableSelection();
    }
});