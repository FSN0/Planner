// app/static/js/kanban_logic.js

$(document).ready(function() {
    const t = window.SP_T || function (key) { return key; };

    // =========================================================================
    // 0. CONFIGURACIÓN CENTRALIZADA Y VARIABLES GLOBALES
    // =========================================================================
    let modalCalendarInstance = null;
    let libresCalendarInstance = null;

    /**
     * Altura real de la cabecera sticky → top/height de operarios libres.
     * Solo actualiza si cambia ≥2px (evita el «salto» al cargar).
     */
    function syncKanbanHeaderHeight() {
        var header = document.querySelector('.kanban-sticky-header');
        if (!header) return;
        var h = Math.round(header.getBoundingClientRect().height);
        if (h < 1) return;
        var prev = parseFloat(
            getComputedStyle(document.documentElement)
                .getPropertyValue('--kanban-header-height')
        ) || 0;
        if (Math.abs(prev - h) < 2) return;
        document.documentElement.style.setProperty('--kanban-header-height', h + 'px');
    }
    // Medir en el primer frame (cabecera ya en layout); sin timeouts que muevan la columna
    requestAnimationFrame(function () {
        syncKanbanHeaderHeight();
        requestAnimationFrame(syncKanbanHeaderHeight);
    });
    window.addEventListener('resize', syncKanbanHeaderHeight, { passive: true });
    if (typeof ResizeObserver !== 'undefined') {
        var headerEl = document.querySelector('.kanban-sticky-header');
        if (headerEl) {
            var ro = new ResizeObserver(function () { syncKanbanHeaderHeight(); });
            ro.observe(headerEl);
        }
    }

    function initKanbanWorksPan() {
        var wrap = document.getElementById('kanbanWorksWrapper');
        var stage = document.getElementById('kanbanWorksStage');
        var btnLeft = document.getElementById('kanbanWorksEdgeLeft');
        var btnRight = document.getElementById('kanbanWorksEdgeRight');
        if (!wrap || !stage) return;

        var EDGE = 72;
        var CARD = 296;
        var lastX = 0;
        var holdDir = 0;
        var raf = null;

        function wheelPx(e, axis) {
            var v = axis === 'x' ? e.deltaX : e.deltaY;
            if (e.deltaMode === 1) v *= 16;
            if (e.deltaMode === 2) {
                v *= axis === 'x' ? wrap.clientWidth : wrap.clientHeight;
            }
            return v;
        }
        function maxScroll() {
            return Math.max(0, wrap.scrollWidth - wrap.clientWidth);
        }
        function isDragging() {
            return document.body.classList.contains('kanban-is-dragging');
        }
        function setDisabled(btn, on) {
            if (!btn) return;
            btn.disabled = on;
            btn.classList.toggle('is-disabled', on);
        }
        function updateEdges() {
            var max = maxScroll();
            var overflowing = max > 4;
            stage.classList.toggle('is-overflow-x', overflowing);
            var sl = wrap.scrollLeft;
            stage.classList.toggle('is-overflow-left', overflowing && sl > 4);
            stage.classList.toggle('is-overflow-right', overflowing && sl < max - 4);
            setDisabled(btnLeft, !overflowing || sl <= 4);
            setDisabled(btnRight, !overflowing || sl >= max - 4);
        }
        function scrollBy(dx) {
            wrap.scrollLeft += dx;
            updateEdges();
        }

        function dragDir() {
            if (!isDragging()) return 0;
            var rect = stage.getBoundingClientRect();
            if (lastX < rect.left - 24 || lastX > rect.right + 24) return 0;
            var leftDist = lastX - rect.left;
            var rightDist = rect.right - lastX;
            if (leftDist < EDGE) return -Math.max(0.25, 1 - (leftDist / EDGE));
            if (rightDist < EDGE) return Math.max(0.25, 1 - (rightDist / EDGE));
            return 0;
        }
        function tick() {
            var dir = holdDir || dragDir();
            if (dir) scrollBy(dir * 22);
            if (holdDir || isDragging()) {
                raf = requestAnimationFrame(tick);
            } else {
                raf = null;
            }
        }
        function startLoop() {
            if (!raf) raf = requestAnimationFrame(tick);
        }

        wrap.addEventListener('scroll', updateEdges, { passive: true });
        wrap.addEventListener('wheel', function (e) {
            var dx = wheelPx(e, 'x');
            var dy = wheelPx(e, 'y');
            if (maxScroll() <= 4) return;
            if (e.shiftKey && Math.abs(dy) >= Math.abs(dx) && Math.abs(dy) >= 0.1) {
                e.preventDefault();
                scrollBy(dy);
                return;
            }
            if (Math.abs(dx) < 0.1) return;
            if (Math.abs(dx) <= Math.abs(dy)) return;
            e.preventDefault();
            scrollBy(dx);
        }, { passive: false });

        function bindHold(btn, dir) {
            if (!btn) return;
            var delay = null;
            var from = 0;
            var stop = function () {
                if (delay) {
                    clearTimeout(delay);
                    delay = null;
                }
                holdDir = 0;
            };
            btn.addEventListener('pointerdown', function (e) {
                if (e.button !== 0) return;
                e.preventDefault();
                try { btn.setPointerCapture(e.pointerId); } catch (err) {}
                from = Date.now();
                delay = setTimeout(function () {
                    delay = null;
                    holdDir = dir;
                    startLoop();
                }, 280);
            });
            btn.addEventListener('pointerup', function () {
                var wasHold = !delay;
                stop();
                if (!wasHold && Date.now() - from < 280) scrollBy(dir * CARD);
            });
            btn.addEventListener('pointercancel', stop);
        }
        bindHold(btnLeft, -1);
        bindHold(btnRight, 1);
        document.addEventListener('pointerup', function () { holdDir = 0; });

        document.addEventListener('pointermove', function (e) {
            lastX = e.clientX;
            if (isDragging()) startLoop();
        }, { passive: true });

        if (typeof ResizeObserver !== 'undefined') {
            var ro = new ResizeObserver(updateEdges);
            ro.observe(wrap);
            ro.observe(stage);
        }
        window.addEventListener('resize', updateEdges, { passive: true });
        stage.kanbanSyncPan = updateEdges;
        updateEdges();
        requestAnimationFrame(updateEdges);
    }

    // =========================================================================
    // 1. EVENTOS: DRAG & DROP — soltar en la obra asigna el día del tablero
    // =========================================================================

    function getKanbanSelectedDate() {
        const input = document.getElementById('timeline-selected-date');
        if (input && input.value) return input.value;
        if (typeof moment !== 'undefined') return moment().format('YYYY-MM-DD');
        return new Date().toISOString().slice(0, 10);
    }

    function refreshObraWorkerCounts() {
        $('.obra-card[data-obra-id]').each(function () {
            const n = $(this).find('.worker-list-body > .worker-chip').length;
            $(this).find('.header-subtitle strong').first().text(n);
        });
    }

    function moveChipToObra($chip, $targetCol) {
        if (!$chip || !$chip.length || !$targetCol || !$targetCol.length) return;
        $chip.detach().appendTo($targetCol);
        $chip.css({'transition': 'background-color 0.5s', 'background-color': '#d4edda'});
        setTimeout(function () { $chip.css('background-color', ''); }, 1000);
        refreshObraWorkerCounts();
    }

    const kanbanReadonly = window.KANBAN_READONLY === true
        || window.CURRENT_USER_ROLE === 'laboral';

    if (!kanbanReadonly) {
    $(".worker-chip").draggable({
        revert: "invalid", helper: "clone", appendTo: "body", zIndex: 9999, scroll: false,
        start: function() {
            $(this).addClass('dragging-source');
            document.body.classList.add('kanban-is-dragging');
        },
        stop: function() {
            $(this).removeClass('dragging-source');
            document.body.classList.remove('kanban-is-dragging');
        }
    });

    $(".worker-list-body").droppable({
        accept: ".worker-chip", tolerance: "pointer", hoverClass: "droppable-hover",
        drop: function(event, ui) {
            const $chip = ui.draggable;
            const workerId = $chip.data("worker-id");
            const workerName = $chip.data("worker-name");
            const $targetCol = $(this);
            const targetObraId = $targetCol.data("obra-id");
            const $source = $chip.closest('.worker-list-body');
            const sourceObraId = $source.data('obra-id');

            if (sourceObraId == targetObraId) return;
            if ($chip.data('kanban-assigning')) return;

            if (targetObraId == 0) {
                openUnassignModalWithCalendar(workerId, workerName, sourceObraId, $source.data('obra-name'));
            } else {
                assignKanbanDay($chip, workerId, targetObraId, sourceObraId, $targetCol);
            }
        }
    });
    } else {
        $(".worker-chip").css('cursor', 'default');
    }

    function assignKanbanDay($chip, workerId, targetObraId, sourceObraId, $targetCol) {
        const fromObra = sourceObraId != null && String(sourceObraId) !== '0' && String(sourceObraId) !== '';
        const payload = {
            worker_id: workerId,
            target_obra_id: targetObraId,
            selected_dates: [getKanbanSelectedDate()],
            overwrite_mode: fromObra ? 'overwrite' : 'check',
        };
        enviarAsignacionDiaKanban(payload, $chip, $targetCol);
    }

    function enviarAsignacionDiaKanban(payload, $chip, $targetCol) {
        if (!payload.overwrite_mode) payload.overwrite_mode = 'check';
        if ($chip && $chip.length) $chip.data('kanban-assigning', true);

        $.ajax({
            url: "/api/v6/assign",
            type: "POST",
            contentType: "application/json",
            data: JSON.stringify(payload),
            success: function(data) {
                if ($chip && $chip.length) $chip.data('kanban-assigning', false);
                    if (data.success) {
                    const action = data.action || 'assigned';
                    if (action === 'requested') {
                        Swal.fire({
                            toast: true, position: 'top-end', icon: 'info',
                            title: data.message || t('Solicitud enviada'),
                            showConfirmButton: false, timer: 2200
                        });
                        return;
                    }
                    Swal.fire({
                        toast: true, position: 'top-end', icon: 'success',
                        title: t('Asignado'), showConfirmButton: false, timer: 1200
                    });
                    try {
                        $(document).trigger('sp-kanban-assigned', {
                            workerId: payload.worker_id,
                            targetObraId: payload.target_obra_id,
                        });
                    } catch (eTrig) { /* ignore */ }
                    if ($chip && $chip.length && $targetCol && $targetCol.length) {
                        moveChipToObra($chip, $targetCol);
                    } else {
                        setTimeout(function () { location.reload(); }, 600);
                    }
                } else if (data.conflict) {
                    window.resolverConflictoAsignacion(data, payload,
                        function (nuevoPayload) {
                            enviarAsignacionDiaKanban(nuevoPayload, $chip, $targetCol);
                        },
                        function () {}
                    );
                } else {
                    Swal.fire(t('Error'), data.error || data.message || t('Error desconocido'), 'error');
                }
            },
            error: function(xhr) {
                if ($chip && $chip.length) $chip.data('kanban-assigning', false);
                let msg = t('Fallo de conexión');
                try {
                    const body = xhr.responseJSON;
                    if (body) msg = body.error || body.message || msg;
                } catch (e) { /* ignore */ }
                Swal.fire(t('Error'), msg, 'error');
            }
        });
    }

    // =========================================================================
    // 2. CALENDARIO DE LA OBRA (icono: vacío, sin persona ni bloque)
    // =========================================================================

    function renderAssignmentCalendar(viewType, workerId, workerName, targetObraId, obraName, sourceObraId, options) {
        options = options || {};
        if (modalCalendarInstance) modalCalendarInstance.destroy();

        const prefillDate = getKanbanSelectedDate();
        const context = viewType;
        const entityId = (viewType === 'obra') ? targetObraId : workerId;
        const eName = (viewType === 'obra') ? obraName : workerName;
        const mode = (viewType === 'obra') ? 'empleados' : 'obras';

        modalCalendarInstance = new UniversalCalendarManager('modal-calendar-container', {
            context: context,
            id: entityId,
            mode: mode,
            entityName: eName,
            embedded: true,
            kanbanSourceObraId: sourceObraId || 0,
            callbacks: {
                onAfterSave: function() {
                    $('#assignmentModal').modal('hide');
                    setTimeout(function() { location.reload(); }, 400);
                }
            }
        });

        setTimeout(function() {
            if (!modalCalendarInstance) return;
            if (!options.skipPrefill && workerId && modalCalendarInstance.prefillKanbanAssignment) {
                modalCalendarInstance.prefillKanbanAssignment({
                    dateStr: prefillDate,
                    workerId: workerId,
                    workerName: workerName,
                    obraId: targetObraId,
                    obraName: obraName
                });
            } else if (modalCalendarInstance.calendar && prefillDate) {
                modalCalendarInstance.calendar.gotoDate(prefillDate);
            }
        }, 400);
    }

    function setAssignmentModalMode(mode, obraName, workerName) {
        const empty = mode === 'empty';
        $('#modalAssignTitleText').text(obraName || t('Calendario de la obra'));
        $('#modalAssignViewToggle').toggle(!empty);
        $('#modalAssignHintEmpty').toggleClass('d-none', !empty);
        $('#modalAssignHintPrefill').toggleClass('d-none', empty);
        if (!empty) {
            $('#modalWorkerSummary').text(workerName || '');
            $('#modalObraSummary').text(obraName || '');
        }
    }

    window.openObraCalendarModal = function(targetObraId, obraName) {
        $('#modalWorkerId').val('');
        $('#modalTargetObraId').val(targetObraId);
        setAssignmentModalMode('empty', obraName, '');
        $('#assignmentModal').modal('show');
        try {
            $(document).trigger('sp-kanban-calendar-open', {
                targetObraId: targetObraId,
                obraName: obraName,
            });
        } catch (eCal) { /* ignore */ }

        setTimeout(function() {
            renderAssignmentCalendar('obra', null, '', targetObraId, obraName, 0, { skipPrefill: true });
        }, 300);
    };

    window.openConcreteModal = function(workerId, workerName, targetObraId, obraName, sourceObraId) {
        $('#modalWorkerId').val(workerId);
        $('#modalTargetObraId').val(targetObraId);
        setAssignmentModalMode('prefill', obraName, workerName);

        $('#btnViewObra').addClass('active btn-primary').removeClass('btn-outline-primary');
        $('#btnViewWorker').removeClass('active btn-primary').addClass('btn-outline-primary');

        $('#assignmentModal').modal('show');

        setTimeout(function() {
            renderAssignmentCalendar('obra', workerId, workerName, targetObraId, obraName, sourceObraId);

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

    $(document).on('mousedown', '.btn-obra-calendar', function (e) {
        e.stopPropagation();
    });
    $(document).on('click', '.btn-obra-calendar', function (e) {
        e.preventDefault();
        e.stopPropagation();
        if (kanbanReadonly) return;
        const $btn = $(this);
        window.openObraCalendarModal($btn.attr('data-obra-id'), $btn.attr('data-obra-name'));
    });

    $('#assignmentModal').on('hidden.bs.modal', function () {
        if (modalCalendarInstance) {
            modalCalendarInstance.destroy();
            modalCalendarInstance = null;
        }
    });

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
                    Swal.fire({toast: true, position: 'top-end', icon: 'success', title: t('Guardado'), showConfirmButton: false, timer: 1500});
                    $('#assignmentModal').modal('hide');

                    let chip = $(`.worker-chip[data-worker-id="${payload.worker_id}"]`);
                    let targetCol = $(`.worker-list-body[data-obra-id="${payload.target_obra_id}"]`);

                    if (chip.length && targetCol.length) {
                        chip.detach().appendTo(targetCol);
                        chip.css({'transition': 'background-color 0.5s', 'background-color': '#d4edda'});
                        setTimeout(() => chip.css('background-color', ''), 1000);
                    } else {
                        setTimeout(() => location.reload(), 600);
                    }
                } 
                else if (data.conflict) {
                    window.resolverConflictoAsignacion(data, payload, 
                        (nuevoPayload) => { enviarAccionKanban(nuevoPayload, revertFunc); }, 
                        revertFunc
                    );
                } else {
                    Swal.fire(t('Error'), data.error || data.message || t('Error desconocido'), 'error');
                    if (revertFunc) revertFunc();
                }
            },
            error: function() {
                Swal.fire(t('Error'), t('Fallo de conexión'), 'error');
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
        $('#libresSourceName').text(sourceObraName || t('Obra desconocida'));
        
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
                embedded: true,
            });
        }, 300);
    };

    window.submitUnassignFromLibres = function() {
        var deleteAll = $('#chk-libres-all').is(':checked');

        if (!deleteAll) {
            Swal.fire(t('Atención'), t("Para desasignar días sueltos usa el calendario directamente. Este botón es exclusivo para procesar la 'Baja Total'."), 'info');
            return;
        }

        var workerId = $('#libresWorkerId').val();
        var obraId = $('#libresSourceObraId').val();
        var $btn = $('#modalMoveToLibres .btn-primary');
        
        $btn.prop('disabled', true).text(t('Procesando...'));

        $.ajax({
            url: "/api/v6/unassign_worker", // URL NUEVA UNIFICADA
            type: "POST",
            contentType: "application/json",
            data: JSON.stringify({ worker_id: workerId, obra_id: obraId, mode: 'all_obra', dates: [] }),
            success: function(res) {
                if (res.success) { location.reload(); } 
                else { alert(t('Error') + ': ' + res.message); $btn.prop('disabled', false).text(t('Confirmar')); }
            },
            error: function() {
                alert(t('Error de conexión'));
                $btn.prop('disabled', false).text(t('Confirmar'));
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
        $('#modalStaffTitle').text(role === 'jefe' ? t('Cambiar Jefe de Obra') : t('Cambiar Encargado'));
        $('#staffObraNameDisplay').text(obraName ? obraName : t('Obra sin nombre'));
        
        var $select = $('#staffSelect').empty();
        var dataList = (role === 'jefe') ? (window.LISTA_JEFES || []) : (window.LISTA_ENCARGADOS || []);
        $select.append(new Option(t("-- Sin Asignar --"), "", false, !currentId));
        dataList.forEach(item => {
            $select.append(new Option(item.text, item.id, false, String(item.id) === String(currentId)));
        });
        
        $('#modalEditStaff').data('trigger-element', $span).modal('show');
    });

    window.submitStaffChange = function() {
        var obraId = $('#staffObraId').val();
        var role = $('#staffRoleType').val();
        var userId = $('#staffSelect').val(); 
        var $btn = $('#modalEditStaff button.btn-primary').prop('disabled', true).text(t('Guardando...'));
        
        $.ajax({
            url: '/admin/api/update_obra_staff', type: 'POST', contentType: 'application/json',
            data: JSON.stringify({ obra_id: obraId, role_type: role, user_id: userId }),
            success: function(res) {
                if (res.success) {
                    $('#modalEditStaff').modal('hide');
                    var $span = $('#modalEditStaff').data('trigger-element');
                    $span.data('current-id', userId); 
                    if (!userId) {
                        $span.html('<span class="text-muted font-italic">' + ((role === 'jefe') ? t('Sin jefe') : t('Sin encargado')) + '</span>');
                    } else {
                        $span.text(res.new_name);
                    }
                    $span.css('background-color', '#d4edda');
                    setTimeout(() => $span.css('background-color', 'transparent'), 1000);
                } else alert(t('Error') + ': ' + res.error);
            },
            complete: () => $btn.prop('disabled', false).text(t('Guardar Cambios'))
        });
    };

    // Scroll horizontal de obras (flechas, barra pegada, bordes al arrastrar)
    initKanbanWorksPan();

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
        if (activeFilters.length === 0) {
            $('.filterable-obra').show();
        } else {
            $('.filterable-obra').each(function() {
                var text = ($(this).data('search-text') || "").toLowerCase();
                activeFilters.some(t => text.includes(t)) ? $(this).show() : $(this).hide();
            });
        }
        var stage = document.getElementById('kanbanWorksStage');
        if (stage && typeof stage.kanbanSyncPan === 'function') stage.kanbanSyncPan();
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
                alert(t("Error al guardar preferencia."));
                $icon.toggleClass('text-primary text-muted-light');
            }
        });
    });

    if ($("#kanbanWorksWrapper").length > 0) {
        $("#kanbanWorksWrapper").sortable({
            items: ".kanban-col-wrapper",
            handle: ".col-header",
            cancel: "a, button, input, select, textarea, .btn-pin-obra, .btn-obra-calendar, .editable-staff",
            placeholder: "ui-state-highlight",
            tolerance: "pointer",
            axis: "x",
            containment: "parent",
            cursor: "grabbing",
            forcePlaceholderSize: true,

            start: function(e, ui) {
                ui.placeholder.height(ui.item.outerHeight());
                ui.placeholder.width(ui.item.outerWidth());
                document.body.classList.add('kanban-is-dragging');
            },

            stop: function(e, ui) {
                document.body.classList.remove('kanban-is-dragging');
                var $wrap = $("#kanbanWorksWrapper");
                var $start = $wrap.children('.kanban-start-obra');
                if ($start.length) {
                    $start.appendTo($wrap);
                }

                var orderedIds = [];
                $wrap.children(".kanban-col-wrapper").each(function() {
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