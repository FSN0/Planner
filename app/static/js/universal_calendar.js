class UniversalCalendarManager {
    constructor(elementId, config) {
        this.element = document.getElementById(elementId);
        if (!this.element) return;

        this.element._calendarInstance = this;

        this.context = config.context; 
        this.entityId = config.id;
        this.entityName = config.entityName || null;
        this.mode = config.mode || 'empleados'; 
        this.callbacks = config.callbacks || {};
        this.showFichajes = config.showFichajes || false;
        this.readonly = config.readonly || false;
        this.partialSelectionMode = config.partialSelectionMode || false;
        this.compact = config.compact || false;

        this.calendar = null;
        this.ghostEventId = 'ghost_block';
        this.activeEvent = null; 
        this.keydownHandler = null; 
        
        this.init();
    }

    init() {
        let _this = this;

        this.panelId = this.element.id + '-bottom-panel';
        let oldPanel = document.getElementById(this.panelId);
        if (oldPanel) oldPanel.remove();
        
        this.titleId = this.element.id + '-univ-title';
        let oldTitle = document.getElementById(this.titleId);
        if (oldTitle) oldTitle.remove();

        this.element.innerHTML = ''; 

        if (!this.readonly) {
            let icon = 'fa-calendar-alt';
            let typeName = 'Elemento';
            let prep = 'de';
            let headerUrl = null;
            
            if (this.context === 'obra') { 
                icon = 'fa-building'; typeName = 'Obra'; prep = 'de la'; 
                headerUrl = `/admin/obra_panel/${this.entityId}`;
            }
            else if (this.context === 'worker') { 
                icon = 'fa-hard-hat'; typeName = 'Empleado'; prep = 'del'; 
                headerUrl = `/admin/worker_panel/${this.entityId}`;
            }
            else if (this.context === 'empresa') { 
                icon = 'fa-briefcase'; typeName = 'Empresa'; prep = 'de la'; 
                headerUrl = `/admin/company_panel/${this.entityId}`;
            }

            let titleText = `Calendario ${prep} ${typeName}`;
            if (this.entityName) {
                if (headerUrl) {
                    titleText += ` <a href="${headerUrl}" target="_blank" class="text-primary ml-2 font-weight-bold border-bottom-dashed" title="Ir a la ficha de este elemento" style="text-decoration: none; border-bottom: 1px dashed #3b82f6;">${this.entityName} <i class="fas fa-external-link-alt small ml-1" style="font-size:0.75rem;"></i></a>`;
                } else {
                    titleText += ` <span class="text-primary ml-2">${this.entityName}</span>`;
                }
            }

            let switcherHTML = '';
            if (this.context === 'obra') {
                let actEmp = this.mode === 'empresas' ? 'active' : '';
                let actOpe = this.mode === 'empleados' ? 'active' : '';
                switcherHTML = `
                    <div class="btn-group btn-group-sm ml-auto" role="group">
                        <button type="button" class="btn btn-outline-primary ${actEmp}" onclick="document.getElementById('${this.element.id}')._calendarInstance.changeMode('empresas')"><i class="fas fa-briefcase mr-1"></i> Empresas</button>
                        <button type="button" class="btn btn-outline-primary ${actOpe}" onclick="document.getElementById('${this.element.id}')._calendarInstance.changeMode('empleados')"><i class="fas fa-users mr-1"></i> Empleados</button>
                    </div>
                `;
            }

            let titleHTML = `
            <div id="${this.titleId}" class="mb-3 p-2 bg-white rounded shadow-sm d-flex align-items-center justify-content-between border" style="border-left: 4px solid #3b82f6 !important;">
                <div class="d-flex align-items-center">
                    <i class="fas ${icon} text-primary mr-2 ml-2" style="font-size: 1.25rem;"></i>
                    <h5 class="m-0 font-weight-bold text-dark" style="font-size: 1.05rem;">${titleText}</h5>
                </div>
                ${switcherHTML}
            </div>`;
            
            this.element.insertAdjacentHTML('beforebegin', titleHTML);

            let panelHTML = `
            <div id="${this.panelId}" class="mt-3 border rounded shadow-sm bg-white" style="display: none; border-left: 4px solid #3b82f6 !important; transition: all 0.2s ease-in-out;">
                <div class="bg-light px-3 py-2 border-bottom d-flex justify-content-between align-items-center">
                    <h6 class="mb-0 font-weight-bold text-dark" id="${this.panelId}-title">
                        <i class="fas fa-info-circle mr-2 text-primary"></i>Detalles del Evento
                    </h6>
                    <button type="button" class="close text-muted" aria-label="Close" onclick="document.getElementById('${this.panelId}').style.display='none'">
                        <span aria-hidden="true" style="font-size: 1.2rem;">&times;</span>
                    </button>
                </div>
                <div class="p-3">
                    <div class="row align-items-end">
                        <div class="col-md-5" id="${this.panelId}-selector-container"></div>
                        <div class="col-md-3">
                            <label class="small font-weight-bold mb-1 text-secondary">Fecha Inicio</label>
                            <input type="date" id="${this.panelId}-start" class="form-control form-control-sm font-weight-bold">
                        </div>
                        <div class="col-md-3">
                            <label class="small font-weight-bold mb-1 text-secondary">Fecha Fin</label>
                            <input type="date" id="${this.panelId}-end" class="form-control form-control-sm font-weight-bold">
                        </div>
                        <div class="col-md-1 pl-0">
                            <button id="${this.panelId}-save" class="btn btn-sm btn-primary w-100" title="Guardar cambios (Enter)"><i class="fas fa-check"></i></button>
                        </div>
                    </div>
                    <div class="row mt-2" id="${this.panelId}-generic-options" style="display: none;">
                        <div class="col-md-3">
                            <label class="small font-weight-bold mb-1 text-secondary"><i class="fas fa-users mr-1"></i> Cantidad de operarios</label>
                            <input type="number" id="${this.panelId}-quantity" class="form-control form-control-sm font-weight-bold text-center" value="1" min="1" max="50">
                        </div>
                    </div>

                    <div class="row mt-2" id="${this.panelId}-notas-row" style="display: none;">
                        <div class="col-md-12">
                            <label class="small font-weight-bold mb-1 text-secondary"><i class="fas fa-sticky-note mr-1"></i> Notas para RRHH <span class="text-muted font-weight-normal">(opcional, solo en solicitudes)</span></label>
                            <textarea id="${this.panelId}-notas" class="form-control form-control-sm" rows="2" maxlength="1000" placeholder="Ej: Necesito oficial de encofrado para planta baja..."></textarea>
                        </div>
                    </div>
                    
                    <div class="row mt-2">
                        <div class="col-md-12 text-right">
                            <div class="custom-control custom-switch d-inline-block">
                                <input type="checkbox" class="custom-control-input" id="${this.panelId}-weekends">
                                <label class="custom-control-label small font-weight-bold text-muted" for="${this.panelId}-weekends" style="cursor:pointer;">
                                    Asignar fines de semana
                                </label>
                            </div>
                        </div>
                    </div>

                    <div class="mt-3 pt-2 border-top text-right" id="${this.panelId}-extra-buttons" style="display:none;">
                        <button id="${this.panelId}-delete" class="btn btn-sm btn-danger mr-2" title="Borrar (Supr)"><i class="fas fa-trash-alt mr-1"></i> Desasignar bloque</button>
                        <button id="${this.panelId}-view" class="btn btn-sm btn-outline-secondary"><i class="fas fa-external-link-alt mr-1"></i> Ver Ficha</button>
                    </div>
                </div>
            </div>
            `;
            this.element.insertAdjacentHTML('afterend', panelHTML);
            this.bindPanelEvents();
        }

        let calendarConfig = {
            initialView: 'dayGridMonth',
            locale: 'es',
            editable: !this.readonly, 
            selectable: !this.readonly, 
            height: 'auto',
            dayMaxEventRows: _this.compact ? 2 : true,
            eventOrder: '-isGhost,start,title',
            events: `/api/v6/universal-calendar?context=${this.context}&id=${this.entityId}&mode=${this.mode}` + (this.showFichajes ? '&show_fichajes=1' : ''),
            
            
            eventDataTransform: function(eventData) {
                let bgColor = eventData.backgroundColor || eventData.color || '#3b82f6';
                eventData.classNames = eventData.classNames || [];
                if (!eventData.classNames.includes('font-weight-bold')) eventData.classNames.push('font-weight-bold');
                if (!eventData.classNames.includes('rounded')) eventData.classNames.push('rounded');
                eventData.borderColor = bgColor;

                if (bgColor.toLowerCase() === '#ffffff' || bgColor.toLowerCase() === '#fff' || bgColor.toLowerCase() === 'white') {
                    eventData.textColor = '#111827';
                    eventData.borderColor = '#cbd5e1'; 
                    return eventData;
                }
                try {
                    if (bgColor.startsWith('#')) {
                        let hex = bgColor.replace('#', '');
                        if (hex.length === 3) hex = hex.split('').map(c => c + c).join('');
                        let r = parseInt(hex.substring(0,2), 16), g = parseInt(hex.substring(2,4), 16), b = parseInt(hex.substring(4,6), 16);
                        let yiq = ((r * 299) + (g * 587) + (b * 114)) / 1000;
                        eventData.textColor = (yiq >= 128) ? '#111827' : '#ffffff';
                        if (yiq >= 210) eventData.borderColor = '#cbd5e1';
                    }
                } catch(e) {}
                return eventData;
            },

            eventContent: function(arg) {
                const evFont = _this.compact ? '0.58rem' : '0.85rem';
                const evPad = _this.compact ? '0 2px' : '4px';
                const evLine = _this.compact ? '1.05' : '1.2';
                const dotSize = _this.compact ? 5 : 10;
                if (arg.event.id === _this.ghostEventId) {
                    return { html: `<div class="text-center shadow-sm rounded" style="font-size:${evFont}; line-height:${evLine}; font-weight:bold; width:100%; padding:${evPad}; color:#111827; background:#e2e8f0; border:1px dashed #94a3b8;"><i class="fas fa-plus mr-1"></i>${arg.event.title}</div>` };
                }

                let innerHtml = '';
                if (arg.event.extendedProps && arg.event.extendedProps.estado_fichaje) {
                    let estado = arg.event.extendedProps.estado_fichaje;
                    let dotClass = '#94a3b8'; let titleMsg = 'Sin Registro';
                    if (estado === 'Correcto') { dotClass = '#10b981'; titleMsg = 'Fichaje Correcto'; }
                    else if (estado === 'Ausencia') { dotClass = '#f59e0b'; titleMsg = 'Ausencia Pendiente'; }
                    else if (estado === 'Resuelto_Ausencia' || estado === 'Conflicto' || estado === 'Paracaidista') { dotClass = '#ef4444'; titleMsg = 'Conflicto/Desviación'; }
                    else if (estado.startsWith('Resuelto')) { dotClass = '#3b82f6'; titleMsg = 'Resuelto Manual'; }

                    innerHtml += `<span title="${titleMsg}" style="display:inline-block; width:${dotSize}px; height:${dotSize}px; border-radius:50%; background-color:${dotClass}; margin-right:3px; flex-shrink:0;"></span>`;
                }
                innerHtml += `<span class="text-truncate">${arg.event.title}</span>`;
                return { html: `<div class="d-flex align-items-center" style="font-size:${evFont}; line-height:${evLine}; overflow:hidden; width:100%; padding:${evPad}; color:${arg.event.textColor || 'inherit'};">${innerHtml}</div>` };
            },

            eventDidMount: function(info) {
                // 1. CAPA DE FONDO: PELOTITAS DE FICHAJES
                if (info.event.extendedProps && info.event.extendedProps.isFichaje) {
                    let dotColor = info.event.extendedProps.estado_color || '#94a3b8';
                    let htmlTooltip = info.event.extendedProps.tooltipContent || '';

                    // Hacemos el fondo invisible para no ensuciar las barras
                    info.el.style.backgroundColor = 'transparent';
                    info.el.style.border = 'none';

                    // Buscamos la celda del día
                    let dayCell = info.el.closest('.fc-daygrid-day');
                    if (dayCell) {
                        // Borramos la bola anterior si Fullcalendar repinta
                        let existingDot = dayCell.querySelector('.fc-fichaje-dot-float');
                        if (existingDot) existingDot.remove();

                        // Creamos la bola flotante arriba a la izquierda
                        let dotEl = document.createElement('div');
                        dotEl.className = 'fc-fichaje-dot-float';
                        dotEl.style = 'position: absolute; top: 4px; left: 4px; z-index: 99; pointer-events: auto;';
                        dotEl.innerHTML = `<span style="display:inline-block; width:12px; height:12px; border-radius:50%; background-color:${dotColor}; box-shadow: 0 1px 3px rgba(0,0,0,0.5); border: 2px solid #fff; cursor: help;"></span>`;
                        
                        // La inyectamos de forma segura dentro del cuadro del día
                        let targetFrame = dayCell.querySelector('.fc-daygrid-day-frame');
                        if (targetFrame) targetFrame.appendChild(dotEl);
                        else dayCell.appendChild(dotEl);

                        // Le aplicamos el Tooltip
                        let targetSpan = dotEl.querySelector('span');
                        if (targetSpan && htmlTooltip) {
                            if (typeof tippy !== 'undefined') tippy(targetSpan, { content: htmlTooltip, allowHTML: true, placement: 'top', theme: 'light-border' });
                            else if (typeof $ !== 'undefined' && $.fn.tooltip) $(targetSpan).tooltip({ title: htmlTooltip, html: true, sanitize: false, placement: 'top', container: 'body' });
                        }
                    }
                    return;
                }

                // 2. LOGICA NORMAL DE OBRAS (Tooltips y Doble Clic)
                if (info.event.extendedProps && info.event.extendedProps.tooltipContent) {
                    if (typeof tippy !== 'undefined') {
                        tippy(info.el, { content: info.event.extendedProps.tooltipContent, allowHTML: true, placement: 'top', theme: 'light-border' });
                    } else if (typeof $ !== 'undefined' && $.fn.tooltip) {
                        $(info.el).tooltip({ title: info.event.extendedProps.tooltipContent, html: true, sanitize: false, placement: 'top', container: 'body' });
                    }
                }

                info.el.addEventListener('dblclick', function(e) {
                    e.preventDefault(); e.stopPropagation();
                    if (info.event.id === _this.ghostEventId) return;

                    let props = info.event.extendedProps || {};
                    if (info.event.url) { window.open(info.event.url, '_blank'); return; }

                    let targetUrl = null;
                    if (props.worker_id && _this.context !== 'worker') targetUrl = `/admin/worker_panel/${props.worker_id}`;
                    else if (props.obra_id && _this.context !== 'obra') targetUrl = `/admin/obra_panel/${props.obra_id}`;
                    else if ((props.empresa_id || props.company_id) && _this.context !== 'empresa') {
                        let cid = props.empresa_id || props.company_id; targetUrl = `/admin/company_panel/${cid}`;
                    } else if (props.type === 'empresa_group' && _this.context !== 'empresa') targetUrl = `/admin/companies`; 
                    
                    if (targetUrl) window.open(targetUrl, '_blank');
                });
            },
            eventWillUnmount: function(info) {
                try {
                    if (info.el._tippy) {
                        info.el._tippy.destroy();
                    } else if (typeof $ !== 'undefined' && $.fn.tooltip) {
                        let $el = $(info.el);
                        if ($el.data('bs.tooltip') || $el.data('ui-tooltip') || $el.attr('data-original-title')) {
                            try { $el.tooltip('dispose'); } catch(e) {}
                            try { $el.tooltip('destroy'); } catch(e) {}
                        }
                    }
                } catch (fatalError) {
                    console.warn("Tooltip unmount silenciado para evitar bloqueo.");
                }
            },

            dateClick: function(info) {
                if (_this.partialSelectionMode) {
                    if (_this.callbacks.onDateToggle) _this.callbacks.onDateToggle(info.dateStr);
                    return;
                }
                if (_this.readonly) return; 
                
                let today = moment().startOf('day');
                let clickedDate = moment(info.dateStr).startOf('day');
                if (clickedDate.isBefore(today)) {
                    if (typeof Swal !== 'undefined') Swal.fire('Acción no permitida', 'No puedes planificar en días pasados.', 'warning');
                    return;
                }
                _this.createGhostEvent(info.dateStr); 
            },

            eventClick: function(info) {
                info.jsEvent.preventDefault();
                let props = info.event.extendedProps || {};
                
                if (info.event.display === 'background') {
                    if (_this.partialSelectionMode && _this.callbacks.onDateToggle) {
                        let dStr = moment(info.event.start).format('YYYY-MM-DD');
                        _this.callbacks.onDateToggle(dStr);
                    }
                    return; 
                }

                if (info.event.url) {
                    if (_this.readonly) window.open(info.event.url, '_blank'); 
                    else window.location.href = info.event.url;
                    return;
                }

                let targetUrl = null;
                if (props.worker_id && _this.context !== 'worker') targetUrl = `/admin/worker_panel/${props.worker_id}`;
                else if (props.obra_id && _this.context !== 'obra') targetUrl = `/admin/obra_panel/${props.obra_id}`;
                else if ((props.empresa_id || props.company_id) && _this.context !== 'empresa') {
                    let cid = props.empresa_id || props.company_id;
                    targetUrl = `/admin/company_panel/${cid}`;
                } 
                else if (props.type === 'empresa_group' && _this.context !== 'empresa') targetUrl = `/admin/companies`; 

                if (_this.readonly) {
                    if (targetUrl) window.open(targetUrl, '_blank'); 
                    return; 
                }

                if (info.event.id === _this.ghostEventId) {
                    _this.showBottomPanel(info.event, true);
                    return;
                }

                let isEditable = true;
                let isPast = false;
                let reasonText = "";

                let today = moment().startOf('day');
                let eventEnd = info.event.end ? moment(info.event.end) : moment(info.event.start).add(1, 'days');
                
                if (eventEnd.startOf('day').isBefore(today)) {
                    isEditable = false;
                    isPast = true;
                    reasonText = "No puedes modificar bloques que ya pertenecen al pasado.";
                } else if (_this.mode === 'empresas' || props.type === 'empresa_group') {
                    isEditable = false;
                    reasonText = "Estás en vista agrupada. Cambia a 'Por Trabajadores' para editar bloques individuales.";
                }

                let targetName = null;
                if (props.worker_id && _this.context !== 'worker') targetName = 'Ver Empleado';
                else if (props.obra_id && _this.context !== 'obra') targetName = 'Ver Obra';
                else if ((props.empresa_id || props.company_id) && _this.context !== 'empresa') targetName = 'Ver Empresa';
                else if ((_this.mode === 'empresas' || props.type === 'empresa_group') && _this.context !== 'empresa') targetName = 'Ver Empresas';

                if (!isEditable) {
                    if (typeof Swal !== 'undefined') {
                        if (targetUrl) {
                            Swal.fire({
                                title: isPast ? 'Bloque Histórico' : 'Acción no permitida',
                                text: reasonText,
                                icon: 'info',
                                showDenyButton: true,
                                showCancelButton: false,
                                confirmButtonText: 'Cerrar',
                                denyButtonText: `<i class="fas fa-external-link-alt mr-1"></i> ${targetName}`,
                                confirmButtonColor: '#64748b',
                                denyButtonColor: '#3b82f6'
                            }).then((result) => {
                                if (result.isDenied) window.open(targetUrl, '_blank'); 
                            });
                        } else {
                            Swal.fire('Acción no permitida', reasonText, 'warning');
                        }
                    } else {
                        alert(reasonText);
                    }
                    return; 
                }

                let ghost = _this.calendar.getEventById(_this.ghostEventId);
                if (ghost) ghost.remove();
                
                if (!props.real_original_start) {
                    info.event.setExtendedProp('real_original_start', info.event.startStr);
                    info.event.setExtendedProp('real_original_end', info.event.endStr || moment(info.event.startStr).add(1, 'days').format('YYYY-MM-DD'));
                }
                
                _this.showBottomPanel(info.event, false);
            },
            
            eventDrop: function(info) {
                if (_this.readonly) return info.revert();
                
                let today = moment().startOf('day');
                if (moment(info.event.start).startOf('day').isBefore(today)) {
                    if(typeof Swal !== 'undefined') Swal.fire('Acción no permitida', 'No puedes mover una asignación a una fecha pasada.', 'warning');
                    info.revert();
                    return;
                }
                if (!info.event.extendedProps.real_original_start && info.event.id !== _this.ghostEventId) {
                    info.event.setExtendedProp('real_original_start', info.oldEvent.startStr);
                    info.event.setExtendedProp('real_original_end', info.oldEvent.endStr || moment(info.oldEvent.startStr).add(1, 'days').format('YYYY-MM-DD'));
                }
                _this.showBottomPanel(info.event, info.event.id === _this.ghostEventId);
            },
            
            eventResize: function(info) {
                if (_this.readonly) return info.revert();
                
                let today = moment().startOf('day');
                let endReal = info.event.end ? moment(info.event.end).subtract(1, 'days').startOf('day') : moment(info.event.start).startOf('day');
                if (endReal.isBefore(today)) {
                    if(typeof Swal !== 'undefined') Swal.fire('Acción no permitida', 'La asignación debe terminar al menos hoy o en una fecha futura.', 'warning');
                    info.revert();
                    return;
                }
                if (!info.event.extendedProps.real_original_start && info.event.id !== _this.ghostEventId) {
                    info.event.setExtendedProp('real_original_start', info.oldEvent.startStr);
                    info.event.setExtendedProp('real_original_end', info.oldEvent.endStr || moment(info.oldEvent.startStr).add(1, 'days').format('YYYY-MM-DD'));
                }
                _this.showBottomPanel(info.event, info.event.id === _this.ghostEventId);
            },

            eventAllow: function(dropInfo, draggedEvent) {
                if (_this.readonly) return false;
                if (draggedEvent.id === _this.ghostEventId) return true;
                if (_this.context === 'obra' && _this.mode === 'empresas') return false; 
                return true;
            }
        };

        this.calendar = new FullCalendar.Calendar(this.element, calendarConfig);
        this.calendar.render();

        if (!this.readonly) {
            this.keydownHandler = (e) => {
                if (typeof Swal !== 'undefined' && Swal.isVisible()) {
                    if (e.key === 'Enter') {
                        let confirmBtn = Swal.getConfirmButton();
                        if (confirmBtn && document.activeElement !== confirmBtn) {
                            e.preventDefault(); confirmBtn.click();
                        }
                    }
                    return; 
                }

                let panel = document.getElementById(this.panelId);
                if (panel && panel.style.display !== 'none') {
                    if (e.key === 'Enter') {
                        e.preventDefault();
                        document.getElementById(`${this.panelId}-save`).click();
                    } else if (e.key === 'Delete' || e.key === 'Backspace') {
                        if (e.target.tagName === 'INPUT' && e.key === 'Backspace') return; 
                        if (this.activeEvent && this.activeEvent.id !== this.ghostEventId) {
                            e.preventDefault();
                            document.getElementById(`${this.panelId}-delete`).click();
                        }
                    }
                }
            };
            document.addEventListener('keydown', this.keydownHandler);
        }
    }

    showBottomPanel(event, isNew) {
        if (this.readonly) return; 
        
        let isSameEvent = (this.activeEvent && this.activeEvent.id === event.id);
        this.activeEvent = event;
        
        let panel = document.getElementById(this.panelId);
        let titleEl = document.getElementById(`${this.panelId}-title`);
        let container = document.getElementById(`${this.panelId}-selector-container`);
        let extraBtns = document.getElementById(`${this.panelId}-extra-buttons`);
        
        this.updatePanelDatesFromEvent(event);
        panel.style.display = 'block';

        if (!isSameEvent) {
            if (isNew) {
                if (this.context === 'solicitud') {
                    this.hidePanel();
                    if (this.activeEvent && this.activeEvent.id === this.ghostEventId) this.activeEvent.remove();
                    if (typeof Swal !== 'undefined') Swal.fire('Aviso', 'No puedes crear asignaciones libres directamente desde la vista de solicitudes.', 'info');
                    return;
                }

                titleEl.innerHTML = '<i class="fas fa-plus-circle mr-2 text-success"></i>Nueva Asignación';
                extraBtns.style.display = 'none';

                let notasRow = document.getElementById(`${this.panelId}-notas-row`);
                let notasInput = document.getElementById(`${this.panelId}-notas`);
                if (notasRow) notasRow.style.display = 'block';
                if (notasInput) notasInput.value = '';

                let selectLabel = this.context === 'obra' ? 'Trabajador a asignar' : 'Obra destino';
                
                container.innerHTML = `
                    <label class="small font-weight-bold mb-1 text-secondary">${selectLabel}</label>
                    <select id="${this.panelId}-select" class="form-control form-control-sm" style="width: 100%;">
                        <option></option>
                    </select>
                `;

                setTimeout(() => {
                    let $select = $(`#${this.panelId}-select`);
                    if (this.context === 'obra') {
                        if (typeof $ !== 'undefined' && $.fn.select2) {
                            $select.select2({
                                dropdownParent: $(`#${this.panelId}`).parent(),
                                placeholder: "Escribe o elige 'CUALQUIERA'...",
                                allowClear: true,
                                ajax: {
                                    url: '/admin/api/planificador/search_workers',
                                    dataType: 'json', delay: 250,
                                    data: (p) => ({ q: p.term }),
                                    processResults: (d) => ({ results: d.results })
                                }
                            }).on('change', (e) => {
                                let gRow = document.getElementById(`${this.panelId}-generic-options`);
                                if(gRow) { e.target.value === 'GENERICO' ? $(gRow).slideDown(150) : $(gRow).slideUp(150); }
                            });
                        }
                    } else if (this.context === 'worker') {
                        fetch('/api/v6/recursos_activos').then(r=>r.json()).then(data => {
                            if (typeof $ !== 'undefined' && $.fn.select2) {
                                $select.select2({
                                    dropdownParent: $(`#${this.panelId}`).parent(),
                                    placeholder: "Selecciona una obra...",
                                    allowClear: true,
                                    data: data.obras 
                                });
                            }
                        });
                    }
                }, 150);

            } else {
                titleEl.innerHTML = '<i class="fas fa-edit mr-2 text-info"></i>Editar Asignación';
                extraBtns.style.display = 'block';

                let notasRow = document.getElementById(`${this.panelId}-notas-row`);
                if (notasRow) notasRow.style.display = 'none';
                
                container.innerHTML = `
                    <label class="small font-weight-bold mb-1 text-secondary">Elemento Asignado</label>
                    <div class="form-control form-control-sm bg-light text-dark font-weight-bold" style="cursor: not-allowed; border: 1px solid #e2e8f0;">
                        ${event.title}
                    </div>
                `;

                let btnView = document.getElementById(`${this.panelId}-view`);
                if (btnView) {
                    btnView.onclick = () => {
                        if(event.extendedProps && event.extendedProps.obra_url) { window.open(event.extendedProps.obra_url, '_blank'); return;}
                        let targetUrl = null;
                        if (this.context === 'worker') targetUrl = `/admin/obra_panel/${event.extendedProps.obra_id}`;
                        else if (this.context === 'obra') targetUrl = `/admin/worker_panel/${event.extendedProps.worker_id}`;
                        
                        if (targetUrl) window.open(targetUrl, '_blank');
                        else if(typeof Swal !== 'undefined') Swal.fire('Información', 'No hay enlace directo disponible.', 'info');
                    };
                }
            }
        }
    }

    updatePanelDatesFromEvent(event) {
        if (!this.activeEvent || this.activeEvent.id !== event.id) return;
        let startInput = document.getElementById(`${this.panelId}-start`);
        let endInput = document.getElementById(`${this.panelId}-end`);
        
        if (startInput) startInput.value = moment(event.start).format('YYYY-MM-DD');
        if (endInput) endInput.value = event.end ? moment(event.end).subtract(1, 'days').format('YYYY-MM-DD') : startInput.value;
    }

    bindPanelEvents() {
        let startInput = document.getElementById(`${this.panelId}-start`);
        let endInput = document.getElementById(`${this.panelId}-end`);
        let saveBtn = document.getElementById(`${this.panelId}-save`);
        let delBtn = document.getElementById(`${this.panelId}-delete`);

        if(startInput) startInput.addEventListener('change', (e) => {
            if(this.activeEvent && e.target.value) this.activeEvent.setStart(e.target.value);
        });
        
        if(endInput) endInput.addEventListener('change', (e) => {
            if(this.activeEvent && e.target.value) this.activeEvent.setEnd(moment(e.target.value).add(1, 'days').format('YYYY-MM-DD'));
        });

        if(saveBtn) saveBtn.addEventListener('click', () => {
            if (!this.activeEvent) return;
            
            let startVal = startInput.value;
            let endVal = endInput.value;
            let today = moment().startOf('day');

            let includeWeekendsCheck = document.getElementById(`${this.panelId}-weekends`);
            let includeWeekends = includeWeekendsCheck ? includeWeekendsCheck.checked : false;

            if (this.activeEvent.id === this.ghostEventId) {
                if (moment(startVal).isBefore(today)) {
                    if(typeof Swal !== 'undefined') Swal.fire('Error', 'No puedes planificar en el pasado.', 'error');
                    return;
                }
                
                let selEl = document.getElementById(`${this.panelId}-select`);
                let selVal = selEl ? selEl.value : null;

                if (this.callbacks.onSaveNew && !selEl) {
                    this.callbacks.onSaveNew(startVal, endVal, includeWeekends);
                    return;
                }

                if (!selVal) {
                    Swal.fire('Atención', 'Debes seleccionar un destino/trabajador.', 'warning');
                    return;
                }

                let qtyEl = document.getElementById(`${this.panelId}-quantity`);
                let qty = qtyEl ? parseInt(qtyEl.value) || 1 : 1;
                let notasEl = document.getElementById(`${this.panelId}-notas`);
                let notasVal = notasEl ? notasEl.value.trim() : '';

                let payload = {
                    start_date: startVal, end_date: endVal, original_start: null, original_end: null,
                    overwrite_mode: 'check', include_weekends: includeWeekends, cantidad: selVal === 'GENERICO' ? qty : 1
                };
                if (notasVal) payload.notas = notasVal;

                if (this.context === 'obra') {
                    payload.worker_id = selVal; payload.target_obra_id = this.entityId; payload.old_obra_id = this.entityId;
                } else if (this.context === 'worker') {
                    payload.worker_id = this.entityId; payload.target_obra_id = selVal; payload.old_obra_id = selVal;
                }

                this.executeSave(payload, () => {
                    this.calendar.refetchEvents(); this.hidePanel();
                    if (window.loadTimelineData) window.loadTimelineData(); 
                });

            } else {
                let originalStart = moment(this.activeEvent.extendedProps.real_original_start || this.activeEvent.start).startOf('day');
                
                if (originalStart.isSameOrAfter(today) && moment(startVal).isBefore(today)) {
                    if(typeof Swal !== 'undefined') Swal.fire('Error', 'No puedes mover hacia el pasado.', 'error');
                    return;
                }
                if (moment(endVal).isBefore(today)) {
                    if(typeof Swal !== 'undefined') Swal.fire('Error', 'La fecha de fin no puede apuntar al pasado.', 'error');
                    return;
                }

                let payload = {
                    start_date: startVal,
                    end_date: endVal, // <-- SOLUCIONADO: Ya no suma un día de más
                    original_start: this.activeEvent.extendedProps.real_original_start,
                    original_end: this.activeEvent.extendedProps.real_original_end ? moment(this.activeEvent.extendedProps.real_original_end).subtract(1, 'days').format('YYYY-MM-DD') : null,
                    overwrite_mode: 'overwrite', 
                    include_weekends: includeWeekends
                };

                if (this.context === 'worker') {
                    payload.worker_id = this.entityId;
                    payload.target_obra_id = this.activeEvent.extendedProps.obra_id;
                    payload.old_obra_id = this.activeEvent.extendedProps.obra_id;
                } else {
                    payload.worker_id = this.activeEvent.extendedProps.worker_id || this.entityId;
                    payload.target_obra_id = this.entityId;
                    payload.old_obra_id = this.entityId;
                }

                if (this.callbacks.onEventModified) {
                    this.callbacks.onEventModified(payload, null); 
                } else {
                    this.executeSave(payload, () => {
                        this.calendar.refetchEvents(); this.hidePanel();
                        if (window.loadTimelineData) window.loadTimelineData();
                    });
                }
            }
        });

        if(delBtn) delBtn.addEventListener('click', () => {
            if (!this.activeEvent) return;
            
            let originalStart = moment(this.activeEvent.startStr);
            let end = this.activeEvent.endStr ? moment(this.activeEvent.endStr).subtract(1, 'days') : originalStart.clone();
            let today = moment().startOf('day');
            
            let start = originalStart.isBefore(today) ? today.clone() : originalStart.clone();
            
            let daysCount = Math.max(0, end.diff(start, 'days') + 1);
            
            if (daysCount <= 0) {
                if (typeof Swal !== 'undefined') Swal.fire('Histórico Protegido', 'Este bloque pertenece íntegramente al pasado y no se puede borrar.', 'info');
                return;
            }

            let dates = [];
            let curr = start.clone();
            while(curr.isSameOrBefore(end)) {
                dates.push(curr.format('YYYY-MM-DD'));
                curr.add(1, 'days');
            }

            if (typeof Swal !== 'undefined') {
                let msg = originalStart.isBefore(today) 
                    ? `Se conservará el histórico pasado, pero se vaciarán <b class="text-danger">${daysCount} día(s)</b> desde hoy en adelante.` 
                    : `Se vaciarán <b class="text-danger">${daysCount} día(s)</b>.`;

                Swal.fire({
                    title: '¿Desasignar bloque?', html: msg, icon: 'warning', showCancelButton: true,
                    confirmButtonColor: '#d33', cancelButtonColor: '#64748b', confirmButtonText: 'Sí, borrar', cancelButtonText: 'Cancelar'
                }).then((res) => {
                    if (res.isConfirmed) {
                        if (this.callbacks.onDeleteAssignment) {
                            this.callbacks.onDeleteAssignment(this.activeEvent, dates, originalStart.isBefore(today));
                            this.hidePanel();
                        } else {
                            let wId = this.context === 'worker' ? this.entityId : this.activeEvent.extendedProps.worker_id;
                            let oId = this.context === 'obra' ? this.entityId : this.activeEvent.extendedProps.obra_id;

                            let csrf = "";
                            let parts = ("; " + document.cookie).split("; csrf_token=");
                            if (parts.length === 2) csrf = parts.pop().split(";").shift();

                            fetch('/api/v6/unassign_worker', {
                                method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
                                body: JSON.stringify({ worker_id: wId, obra_id: oId, dates: dates, mode: 'selected' })
                            }).then(r=>r.json()).then(data => {
                                if(data.success) {
                                    Swal.fire({toast: true, position: 'top-end', icon: 'success', title: 'Borrado', showConfirmButton: false, timer: 1500});
                                    this.calendar.refetchEvents(); this.hidePanel();
                                    if (window.loadTimelineData) window.loadTimelineData();
                                } else { Swal.fire('Error', data.message, 'error'); }
                            });
                        }
                    }
                });
            }
        });
    }

    triggerBackendAction(event, actionType, revertFunc) {
        let payload = {
            entity_id: this.entityId,
            context: this.context,
            event_data: event.extendedProps,
            new_start: event.startStr,
            new_end: event.endStr,
            include_weekends: event.include_weekends, 
            original_start: event.extendedProps.real_original_start, 
            original_end: event.extendedProps.real_original_end ? moment(event.extendedProps.real_original_end).subtract(1, 'days').format('YYYY-MM-DD') : null
        };

        if (this.callbacks.onEventModified) {
            this.callbacks.onEventModified(payload, revertFunc);
        } else {
            if(revertFunc) revertFunc();
        }
    }
    
    hidePanel() { 
        let p = document.getElementById(this.panelId);
        if(p) p.style.display = 'none'; 

        let genericRow = document.getElementById(`${this.panelId}-generic-options`);
        if (genericRow) genericRow.style.display = 'none';
        let qtyInput = document.getElementById(`${this.panelId}-quantity`);
        if (qtyInput) qtyInput.value = 1;
        let notasRow = document.getElementById(`${this.panelId}-notas-row`);
        if (notasRow) notasRow.style.display = 'none';
        let notasInput = document.getElementById(`${this.panelId}-notas`);
        if (notasInput) notasInput.value = '';
    }

    createGhostEvent(dateStr) {
        let existingGhost = this.calendar.getEventById(this.ghostEventId);
        if (existingGhost) existingGhost.remove();

        let endStr = moment(dateStr).add(1, 'days').format('YYYY-MM-DD');

        let ghost = this.calendar.addEvent({
            id: this.ghostEventId, title: 'NUEVA ASIGNACIÓN', start: dateStr, end: endStr,
            className: 'fc-ghost-event', editable: true, extendedProps: { isGhost: 1 }
        });

        this.showBottomPanel(ghost, true);
    }
    
    createGhostEventRange(startStr, endStr) {
        let existingGhost = this.calendar.getEventById(this.ghostEventId);
        if (existingGhost) existingGhost.remove();

        let endObj = moment(endStr).add(1, 'days').format('YYYY-MM-DD'); 
        
        let ghost = this.calendar.addEvent({
            id: this.ghostEventId, title: 'NUEVA ASIGNACIÓN', start: startStr, end: endObj,
            className: 'fc-ghost-event', editable: true, extendedProps: { isGhost: 1 }
        });
        this.showBottomPanel(ghost, true);
    }

    changeMode(newMode) {
        this.mode = newMode;
        this.calendar.removeAllEventSources();
        this.calendar.addEventSource(`/api/v6/universal-calendar?context=${this.context}&id=${this.entityId}&mode=${this.mode}` + (this.showFichajes ? '&show_fichajes=1' : ''));
        
        let btnEmpresas = document.querySelector(`#${this.titleId} .btn-outline-primary:nth-child(1)`);
        let btnEmpleados = document.querySelector(`#${this.titleId} .btn-outline-primary:nth-child(2)`);
        
        if (btnEmpresas && btnEmpleados) {
            if (newMode === 'empresas') {
                btnEmpresas.classList.add('active'); btnEmpleados.classList.remove('active');
            } else {
                btnEmpleados.classList.add('active'); btnEmpresas.classList.remove('active');
            }
        }
    }

    destroy() {
        if (this.calendar) this.calendar.destroy();
        if (this.keydownHandler) document.removeEventListener('keydown', this.keydownHandler);
        let panel = document.getElementById(this.panelId);
        if (panel) panel.remove();
        let title = document.getElementById(this.titleId);
        if (title) title.remove();
        if (this.element) this.element.innerHTML = ''; 
    }

    executeSave(payload, revertFunc) {
        if (!payload.overwrite_mode) payload.overwrite_mode = 'check';
        payload.check_conflicts = true;

        $.ajax({
            url: "/api/v6/planificador/action",
            type: "POST",
            contentType: "application/json",
            data: JSON.stringify(payload),
            success: (res) => {
                if (res.success) {
                    if(typeof Swal !== 'undefined') Swal.fire({toast: true, position: 'top-end', icon: 'success', title: 'Guardado', showConfirmButton: false, timer: 1500});
                    this.calendar.refetchEvents();
                    this.hidePanel();
                    if(revertFunc) revertFunc();
                    
                } else if (res.conflict || res.action === 'confirm_overwrite') {
                    if (typeof window.resolverConflictoAsignacion === 'function') {
                        window.resolverConflictoAsignacion(
                            res, payload, 
                            (nuevoPayload) => { this.executeSave(nuevoPayload, revertFunc); }, 
                            revertFunc
                        );
                    } else {
                        console.error("CRÍTICO: No se encontró window.resolverConflictoAsignacion.");
                    }
                } else {
                    if(typeof Swal !== 'undefined') Swal.fire('Error', res.error || res.message || 'Error desconocido', 'error');
                    if (revertFunc) revertFunc();
                }
            },
            error: () => {
                if(typeof Swal !== 'undefined') Swal.fire('Error', 'Fallo de red', 'error');
                if (revertFunc) revertFunc();
            }
        });
    }
}

window.addEventListener('scroll', function(e) {
    if (e.target && e.target.nodeType === 1 && e.target.classList.contains('select2-results__options')) { return; }
    if (typeof $ !== 'undefined' && $.fn.select2) { $('.select2-hidden-accessible').select2('close'); }
    if (typeof $ !== 'undefined') { $('.tooltip.show').remove(); }
    document.querySelectorAll('[data-tippy-root]').forEach(el => { if (el._tippy) el._tippy.hide(); });
    if (document.activeElement && document.activeElement.type === 'date') { document.activeElement.blur(); }
}, { capture: true, passive: true });

document.addEventListener('DOMContentLoaded', () => {
    if (typeof $ !== 'undefined' && $.fn.select2) {
        const fixSelect2Scroll = ($select) => {
            if ($select.closest('[id$="-bottom-panel"]').length > 0) {
                setTimeout(() => {
                    $select.select2({ width: '100%', dropdownParent: $select.parent() });
                }, 50);
            }
        };

        const observer = new MutationObserver((mutations) => {
            mutations.forEach((mutation) => {
                if (mutation.target.nodeName === 'SELECT') { fixSelect2Scroll($(mutation.target)); }
                mutation.addedNodes.forEach(node => {
                    if (node.nodeType === 1) { 
                        if (node.nodeName === 'SELECT') { fixSelect2Scroll($(node)); } 
                        else { $(node).find('select').each(function() { fixSelect2Scroll($(this)); }); }
                    }
                });
            });
        });

        observer.observe(document.body, { childList: true, subtree: true });
    }
});