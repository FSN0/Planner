var t = window.SP_T || function (key) { return key; };

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
        this.selfService = config.selfService || false;
        this.partialSelectionMode = config.partialSelectionMode || false;
        this.compact = config.compact || false;
        this.embedded = config.embedded || false;
        this.hideTitle = config.hideTitle || false;
        this.kanbanSourceObraId = config.kanbanSourceObraId;
        this.kanbanPrefill = null;
        this._pendingPrefill = null;
        this._embeddedModal = null;

        this.calendar = null;
        this.ghostEventId = 'ghost_block';
        this.activeEvent = null; 
        this.keydownHandler = null; 
        
        this.init();
    }

    /** En portal /fichaje no saltar a pantallas de administración. */
    _adminUrl(url) {
        return (this.selfService || !url) ? null : url;
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
        this.element.classList.add('univ-calendar-root');
        if (this.compact) this.element.classList.add('univ-calendar-compact');

        if (!this.readonly) {
            let icon = 'fa-calendar-alt';
            let typeName = t('Elemento');
            let prep = t('de');
            let headerUrl = null;
            
            if (this.context === 'obra') { 
                icon = 'fa-building'; typeName = t('Obra'); prep = t('de la'); 
                headerUrl = `/admin/obra_panel/${this.entityId}`;
            }
            else if (this.context === 'worker') { 
                icon = 'fa-hard-hat'; typeName = t('Empleado'); prep = t('del'); 
                headerUrl = `/admin/worker_panel/${this.entityId}`;
            }
            else if (this.context === 'empresa') { 
                icon = 'fa-briefcase'; typeName = t('Empresa'); prep = t('de la'); 
                headerUrl = `/admin/company_panel/${this.entityId}`;
            }
            else if (this.context === 'vehiculo') {
                icon = 'fa-car'; typeName = t('Vehículo'); prep = t('del');
                headerUrl = `/admin/vehicle_panel/${this.entityId}`;
            }

            let titleText = `${t('Calendario')} ${prep} ${typeName}`;
            if (this.entityName) {
                if (headerUrl) {
                    titleText += ` <a href="${headerUrl}" target="_blank" class="univ-calendar-entity-link" title="${t('Ir a la ficha de este elemento')}">${this.entityName} <i class="fas fa-external-link-alt small ml-1"></i></a>`;
                } else {
                    titleText += ` <span class="univ-calendar-entity-name">${this.entityName}</span>`;
                }
            }

            let switcherHTML = '';
            if (this.context === 'obra') {
                let actEmp = this.mode === 'empresas' ? 'active' : '';
                let actOpe = this.mode === 'empleados' ? 'active' : '';
                switcherHTML = `
                    <div class="btn-group btn-group-sm ml-auto" role="group">
                        <button type="button" class="btn btn-outline-primary ${actEmp}" onclick="document.getElementById('${this.element.id}')._calendarInstance.changeMode('empresas')"><i class="fas fa-briefcase mr-1"></i> ${t('Empresas')}</button>
                        <button type="button" class="btn btn-outline-primary ${actOpe}" onclick="document.getElementById('${this.element.id}')._calendarInstance.changeMode('empleados')"><i class="fas fa-users mr-1"></i> ${t('Empleados')}</button>
                    </div>
                `;
            }

            let titleHTML = '';
            if (!this.hideTitle || switcherHTML) {
                let headingBlock = '';
                if (!this.hideTitle) {
                    headingBlock = `
                <div class="univ-calendar-title-heading">
                    <i class="fas ${icon}"></i>
                    <span>${titleText}</span>
                </div>`;
                }
                titleHTML = `
            <div id="${this.titleId}" class="univ-calendar-title${this.hideTitle ? ' univ-calendar-title--toolbar-only' : ''}">
                ${headingBlock}
                ${switcherHTML}
            </div>`;
                this.element.insertAdjacentHTML('beforebegin', titleHTML);
            }

            if (this.hideTitle) {
                this.element.classList.add('univ-calendar-root--no-title');
            }

            if (this.embedded) {
                this._embeddedModal = this.element.closest('.modal');
                if (this._embeddedModal) {
                    this._embeddedModal.classList.add('univ-calendar-embedded');
                    const modalBody = this.element.closest('.modal-body');
                    if (modalBody && !modalBody.querySelector('.univ-calendar-modal-close')) {
                        const closeBtn = document.createElement('button');
                        closeBtn.type = 'button';
                        closeBtn.className = 'close univ-calendar-modal-close';
                        closeBtn.setAttribute('aria-label', t('Cerrar'));
                        closeBtn.innerHTML = '<span aria-hidden="true">&times;</span>';
                        closeBtn.addEventListener('click', () => {
                            if (typeof $ !== 'undefined' && this._embeddedModal) {
                                $(this._embeddedModal).modal('hide');
                            }
                        });
                        modalBody.prepend(closeBtn);
                    }
                }
            }

            let panelHTML = `
            <div id="${this.panelId}" class="univ-calendar-panel" style="display: none;">
                <div class="univ-calendar-panel-head">
                    <h6 id="${this.panelId}-title">
                        <i class="fas fa-info-circle mr-2 univ-calendar-icon"></i>${t('Detalles del Evento')}
                    </h6>
                    <button type="button" class="close text-muted" aria-label="${t('Cerrar')}" onclick="document.getElementById('${this.panelId}').style.display='none'">
                        <span aria-hidden="true">&times;</span>
                    </button>
                </div>
                <div class="univ-calendar-panel-body">
                    <div class="row align-items-end">
                        <div class="col-md-5">
                            <label class="small font-weight-bold mb-1 text-secondary">${t('Fecha Inicio')}</label>
                            <input type="date" id="${this.panelId}-start" class="form-control form-control-sm font-weight-bold">
                        </div>
                        <div class="col-md-5">
                            <label class="small font-weight-bold mb-1 text-secondary">${t('Fecha Fin')}</label>
                            <input type="date" id="${this.panelId}-end" class="form-control form-control-sm font-weight-bold">
                        </div>
                        <div class="col-md-2">
                            <label class="small font-weight-bold mb-1 text-secondary d-block">&nbsp;</label>
                            <button id="${this.panelId}-save" class="btn btn-sm btn-primary w-100" title="${t('Guardar cambios (Enter)')}"><i class="fas fa-check"></i></button>
                        </div>
                    </div>
                    <div class="row mt-2">
                        <div class="col-12" id="${this.panelId}-selector-container"></div>
                    </div>
                    <div class="row mt-2" id="${this.panelId}-vehicle-row" style="display: none;">
                        <div class="col-md-6" id="${this.panelId}-vehicle-container"></div>
                    </div>
                    <div class="row mt-2" id="${this.panelId}-generic-options" style="display: none;">
                        <div class="col-md-3">
                            <label class="small font-weight-bold mb-1 text-secondary"><i class="fas fa-users mr-1"></i> ${t('Cantidad de operarios')}</label>
                            <input type="number" id="${this.panelId}-quantity" class="form-control form-control-sm font-weight-bold text-center" value="1" min="1" max="50">
                        </div>
                    </div>

                    <div class="row mt-2" id="${this.panelId}-notas-row" style="display: none;">
                        <div class="col-md-12">
                            <label class="small font-weight-bold mb-1 text-secondary"><i class="fas fa-sticky-note mr-1"></i> ${t('Notas para RRHH')} <span class="text-muted font-weight-normal">(${t('opcional, solo en solicitudes')})</span></label>
                            <textarea id="${this.panelId}-notas" class="form-control form-control-sm" rows="2" maxlength="1000" placeholder="${t('Ej: Necesito oficial de encofrado para planta baja...')}"></textarea>
                        </div>
                    </div>
                    
                    <div class="row mt-2">
                        <div class="col-md-12 text-right">
                            <div class="custom-control custom-switch d-inline-block">
                                <input type="checkbox" class="custom-control-input" id="${this.panelId}-weekends">
                                <label class="custom-control-label small font-weight-bold text-muted" for="${this.panelId}-weekends" style="cursor:pointer;">
                                    ${t('Asignar fines de semana')}
                                </label>
                            </div>
                        </div>
                    </div>

                    <div class="mt-3 pt-2 border-top text-right" id="${this.panelId}-extra-buttons" style="display:none;">
                        <button id="${this.panelId}-delete" class="btn btn-sm btn-danger mr-2" title="${t('Borrar (Supr)')}"><i class="fas fa-trash-alt mr-1"></i> ${t('Desasignar bloque')}</button>
                        <button id="${this.panelId}-view" class="btn btn-sm btn-outline-secondary"><i class="fas fa-external-link-alt mr-1"></i> ${t('Ver Ficha')}</button>
                    </div>
                    <div class="mt-2 pt-2 border-top text-right" id="${this.panelId}-leave-row" style="display:none;">
                        <button type="button" id="${this.panelId}-leave" class="btn btn-sm btn-outline-warning">
                            <i class="fas fa-umbrella-beach mr-1"></i> ${t('Marcar vacaciones / ausencia')}
                        </button>
                    </div>
                </div>
            </div>
            `;
            this.element.insertAdjacentHTML('afterend', panelHTML);
            this.bindPanelEvents();
            this.bindPanelIsolation();
        }

        let calendarConfig = {
            initialView: 'dayGridMonth',
            locale: (window.SP_lang ? window.SP_lang() : ((typeof window.SP_LOCALE === 'string' && window.SP_LOCALE) ? window.SP_LOCALE : (document.documentElement.lang || 'es').slice(0, 2))),
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
                const evType = (eventData.extendedProps && eventData.extendedProps.type) || '';
                if ((evType === 'vehiculo' || evType === 'vehiculo_odoo') && !eventData.classNames.includes('fc-event-vehiculo')) {
                    eventData.classNames.push('fc-event-vehiculo');
                }
                if ((evType === 'asignacion' || evType === 'obra') && !eventData.classNames.includes('fc-event-obra')) {
                    eventData.classNames.push('fc-event-obra');
                }
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
                const props = arg.event.extendedProps || {};
                if (props.estado_fichaje) {
                    let estado = props.estado_fichaje;
                    let FE = window.SPFichajeEstado;
                    let dotClass = (FE && FE.colorDeEstado) ? FE.colorDeEstado(estado) : '#94a3b8';
                    let titleMsg = (FE && FE.labelDeEstado) ? FE.labelDeEstado(estado) : (estado || t('Sin Registro'));

                    innerHtml += `<span title="${titleMsg}" style="display:inline-block; width:${dotSize}px; height:${dotSize}px; border-radius:50%; background-color:${dotClass}; margin-right:3px; flex-shrink:0;"></span>`;
                }
                if (props.type === 'vehiculo' || props.type === 'vehiculo_odoo') {
                    const tip = props.vehiculo_label
                        ? `${t('Vehículo')}: ${props.vehiculo_label}${props.km != null ? ' · ' + Math.round(props.km) + ' km' : ''}`
                        : t('Vehículo');
                    innerHtml += `<i class="fas fa-car" title="${tip}" style="margin-right:3px; flex-shrink:0; opacity:0.95;"></i>`;
                    const evPadVeh = _this.compact ? '0 1px' : '2px 4px';
                    const evFontVeh = _this.compact ? '0.52rem' : '0.72rem';
                    return { html: `<div class="d-flex align-items-center fc-event-vehiculo-inner" style="font-size:${evFontVeh}; line-height:1.1; overflow:hidden; width:100%; padding:${evPadVeh}; color:${arg.event.textColor || 'inherit'}; opacity:0.92;">${innerHtml}<span class="text-truncate">${arg.event.title}</span></div>` };
                }
                const showWorkerVehicle = props.vehiculo_label
                    && props.type === 'asignacion'
                    && _this.context === 'obra';
                const titleHtml = `<span class="text-truncate">${arg.event.title}</span>`;
                if (showWorkerVehicle) {
                    const vehTip = `${t('Vehículo')}: ${props.vehiculo_label}`;
                    const vehFont = _this.compact ? '0.48rem' : '0.62rem';
                    const vehPad = _this.compact ? '0 2px' : '0 4px';
                    return {
                        html: `<div class="univ-event-with-vehicle" style="font-size:${evFont}; line-height:${evLine}; overflow:hidden; width:100%; padding:${evPad}; color:${arg.event.textColor || 'inherit'};">
                            <div class="d-flex align-items-center" style="min-width:0;">${innerHtml}${titleHtml}</div>
                            <div class="univ-event-vehicle-line text-truncate" title="${vehTip}" style="font-size:${vehFont}; line-height:1.15; opacity:0.92; padding-left:2px;">
                                <i class="fas fa-car mr-1" style="font-size:0.9em;"></i>${props.vehiculo_label}
                            </div>
                        </div>`
                    };
                }
                innerHtml += titleHtml;
                return { html: `<div class="d-flex align-items-center" style="font-size:${evFont}; line-height:${evLine}; overflow:hidden; width:100%; padding:${evPad}; color:${arg.event.textColor || 'inherit'};">${innerHtml}</div>` };
            },

            eventDidMount: function(info) {
                // 1. CAPA DE FONDO: PELOTITAS DE FICHAJES
                if (info.event.extendedProps && info.event.extendedProps.isFichaje) {
                    let dotColor = info.event.extendedProps.estado_color || '#94a3b8';
                    let htmlTooltip = info.event.extendedProps.tooltipContent || '';
                    const fProps = info.event.extendedProps || {};
                    const fechaStr = fProps.fecha_iso || (info.event.startStr || '').substring(0, 10);
                    const userId = fProps.worker_id || (_this.context === 'worker' ? _this.entityId : null);
                    const estadoFichaje = fProps.estado_fichaje || '';
                    const dotInteractive = !!(_this.showFichajes && userId && fechaStr);

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
                        dotEl.className = 'fc-fichaje-dot-float' + (dotInteractive ? ' fc-fichaje-dot-float--interactive' : '');
                        dotEl.style = 'position: absolute; top: 4px; left: 4px; z-index: 99; pointer-events: auto;';
                        if (dotInteractive) {
                            dotEl.setAttribute('data-fichaje-dot', '1');
                            dotEl.setAttribute('data-user-id', String(userId));
                            dotEl.setAttribute('data-fecha', fechaStr);
                            if (estadoFichaje) dotEl.setAttribute('data-estado-fichaje', estadoFichaje);
                            dotEl.setAttribute('role', 'button');
                            dotEl.setAttribute('tabindex', '0');
                            dotEl.setAttribute('aria-label', t('Ver historial del fichaje del día'));
                            dotEl.title = t('Clic para ver el historial del día');
                        }
                        dotEl.innerHTML = `<span style="display:inline-block; width:12px; height:12px; border-radius:50%; background-color:${dotColor}; box-shadow: 0 1px 3px rgba(0,0,0,0.5); border: 2px solid #fff; cursor:${dotInteractive ? 'pointer' : 'help'};"></span>`;
                        
                        // La inyectamos de forma segura dentro del cuadro del día
                        let targetFrame = dayCell.querySelector('.fc-daygrid-day-frame');
                        if (targetFrame) targetFrame.appendChild(dotEl);
                        else dayCell.appendChild(dotEl);

                        // Tooltip solo si no es clicable (en clicable abre el modal)
                        let targetSpan = dotEl.querySelector('span');
                        if (targetSpan && htmlTooltip && !dotInteractive) {
                            if (typeof tippy !== 'undefined') tippy(targetSpan, { content: htmlTooltip, allowHTML: true, placement: 'top', theme: 'light-border' });
                            else if (typeof $ !== 'undefined' && $.fn.tooltip) $(targetSpan).tooltip({ title: htmlTooltip, html: true, sanitize: false, placement: 'top', container: 'body' });
                        }
                    }
                    return;
                }

                // 2. LOGICA NORMAL DE OBRAS (Tooltips y Doble Clic)
                const evTypeMount = (info.event.extendedProps && info.event.extendedProps.type) || '';
                if (evTypeMount === 'vehiculo' || evTypeMount === 'vehiculo_odoo') {
                    // Más compacto y con borde discontinuo para no confundir con obras
                    info.el.style.fontSize = '0.72rem';
                    info.el.style.opacity = '0.95';
                    info.el.style.borderStyle = 'dashed';
                    info.el.style.borderWidth = '1.5px';
                    info.el.title = info.el.title || (info.event.title || t('Vehículo'));
                }

                if (info.event.extendedProps && info.event.extendedProps.tooltipContent) {
                    if (typeof tippy !== 'undefined') {
                        tippy(info.el, { content: info.event.extendedProps.tooltipContent, allowHTML: true, placement: 'top', theme: 'light-border' });
                    } else if (typeof $ !== 'undefined' && $.fn.tooltip) {
                        $(info.el).tooltip({ title: info.event.extendedProps.tooltipContent, html: true, sanitize: false, placement: 'top', container: 'body' });
                    } else {
                        info.el.title = info.event.extendedProps.tooltipText
                            || String(info.event.extendedProps.tooltipContent).replace(/<br\s*\/?>/gi, ' · ').replace(/<[^>]+>/g, '');
                    }
                } else if (info.event.extendedProps && info.event.extendedProps.tooltipText) {
                    info.el.title = info.event.extendedProps.tooltipText;
                }

                info.el.addEventListener('dblclick', function(e) {
                    e.preventDefault(); e.stopPropagation();
                    if (info.event.id === _this.ghostEventId) return;

                    let props = info.event.extendedProps || {};
                    if (info.event.url) { window.open(info.event.url, '_blank'); return; }

                    let targetUrl = null;
                    if (props.worker_id && _this.context !== 'worker') targetUrl = _this._adminUrl(`/admin/worker_panel/${props.worker_id}`);
                    else if (props.obra_id && _this.context !== 'obra') targetUrl = _this._adminUrl(`/admin/obra_panel/${props.obra_id}`);
                    else if (props.vehiculo_id && _this.context !== 'vehiculo') targetUrl = _this._adminUrl(`/admin/vehicle_panel/${props.vehiculo_id}`);
                    else if ((props.empresa_id || props.company_id) && _this.context !== 'empresa') {
                        let cid = props.empresa_id || props.company_id; targetUrl = _this._adminUrl(`/admin/company_panel/${cid}`);
                    } else if (props.type === 'empresa_group' && _this.context !== 'empresa') targetUrl = _this._adminUrl('/admin/companies');
                    
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
                // Un clic con selectable también dispara `select`; no duplicar el bloque.
                if (_this._fromSelect) return;

                let today = moment().startOf('day');
                let clickedDate = moment(info.dateStr).startOf('day');
                if (clickedDate.isBefore(today)) {
                    if (typeof Swal !== 'undefined') Swal.fire(t('Acción no permitida'), t('No puedes planificar en días pasados.'), 'warning');
                    return;
                }
                _this.createGhostEvent(info.dateStr); 
            },

            select: function(info) {
                if (_this.partialSelectionMode) {
                    _this.calendar.unselect();
                    return;
                }
                if (_this.readonly) {
                    _this.calendar.unselect();
                    return;
                }
                _this._fromSelect = true;
                setTimeout(function () { _this._fromSelect = false; }, 0);

                let today = moment().startOf('day');
                let start = moment(info.startStr).startOf('day');
                let endInclusive = moment(info.endStr).subtract(1, 'days').startOf('day');
                if (!endInclusive.isValid() || endInclusive.isBefore(start)) {
                    endInclusive = start.clone();
                }
                if (start.isBefore(today)) {
                    _this.calendar.unselect();
                    if (typeof Swal !== 'undefined') Swal.fire(t('Acción no permitida'), t('No puedes planificar en días pasados.'), 'warning');
                    return;
                }
                _this.createGhostEventRange(
                    start.format('YYYY-MM-DD'),
                    endInclusive.format('YYYY-MM-DD')
                );
                _this.calendar.unselect();
            },

            selectAllow: function(info) {
                if (_this.readonly || _this.partialSelectionMode) return false;
                return !moment(info.start).startOf('day').isBefore(moment().startOf('day'));
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
                    if (_this.selfService && String(info.event.url).indexOf('/admin/') !== -1) {
                        return;
                    }
                    if (_this.readonly) window.open(info.event.url, '_blank');
                    else window.location.href = info.event.url;
                    return;
                }

                let targetUrl = null;
                if (props.worker_id && _this.context !== 'worker') targetUrl = _this._adminUrl(`/admin/worker_panel/${props.worker_id}`);
                else if (props.obra_id && _this.context !== 'obra') targetUrl = _this._adminUrl(`/admin/obra_panel/${props.obra_id}`);
                else if (props.vehiculo_id && _this.context !== 'vehiculo') targetUrl = _this._adminUrl(`/admin/vehicle_panel/${props.vehiculo_id}`);
                else if ((props.empresa_id || props.company_id) && _this.context !== 'empresa') {
                    let cid = props.empresa_id || props.company_id;
                    targetUrl = _this._adminUrl(`/admin/company_panel/${cid}`);
                }
                else if (props.type === 'empresa_group' && _this.context !== 'empresa') targetUrl = _this._adminUrl('/admin/companies');

                if (_this.readonly || _this.selfService) {
                    if (targetUrl && !_this.selfService) window.open(targetUrl, '_blank');
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
                    reasonText = t('No puedes modificar bloques que ya pertenecen al pasado.');
                } else if (_this.mode === 'empresas' || props.type === 'empresa_group') {
                    isEditable = false;
                    reasonText = t("Estás en vista agrupada. Cambia a 'Por Trabajadores' para editar bloques individuales.");
                } else if (props.type === 'solicitud_vehiculo' || props.type === 'request') {
                    isEditable = false;
                    reasonText = t('Las solicitudes se gestionan desde el centro de solicitudes.');
                }

                let targetName = null;
                if (props.worker_id && _this.context !== 'worker') targetName = t('Ver Empleado');
                else if (props.obra_id && _this.context !== 'obra') targetName = t('Ver Obra');
                else if (props.vehiculo_id && _this.context !== 'vehiculo') targetName = t('Ver Vehículo');
                else if ((props.empresa_id || props.company_id) && _this.context !== 'empresa') targetName = t('Ver Empresa');
                else if ((_this.mode === 'empresas' || props.type === 'empresa_group') && _this.context !== 'empresa') targetName = t('Ver Empresas');

                if (!isEditable) {
                    if (typeof Swal !== 'undefined') {
                        if (targetUrl) {
                            const swalBase = typeof window.adminSwalDefaults === 'function' ? window.adminSwalDefaults : (o) => o;
                            Swal.fire(swalBase({
                                title: isPast ? t('Bloque Histórico') : t('Acción no permitida'),
                                text: reasonText,
                                icon: 'info',
                                showDenyButton: true,
                                showCancelButton: false,
                                confirmButtonText: t('Cerrar'),
                                denyButtonText: `${targetName}`,
                                customClass: {
                                    popup: 'admin-swal-popup',
                                    title: 'admin-swal-title',
                                    htmlContainer: 'admin-swal-html',
                                    confirmButton: 'admin-swal-btn admin-swal-btn-ghost',
                                    denyButton: 'admin-swal-btn admin-swal-btn-info',
                                    actions: 'admin-swal-actions',
                                },
                            })).then((result) => {
                                if (result.isDenied) window.open(targetUrl, '_blank'); 
                            });
                        } else {
                            const swalBase = typeof window.adminSwalDefaults === 'function' ? window.adminSwalDefaults : (o) => o;
                            Swal.fire(swalBase({ title: t('Acción no permitida'), text: reasonText, icon: 'warning', confirmButtonText: t('Entendido') }));
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
                    if(typeof Swal !== 'undefined') Swal.fire(t('Acción no permitida'), t('No puedes mover una asignación a una fecha pasada.'), 'warning');
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
                    if(typeof Swal !== 'undefined') Swal.fire(t('Acción no permitida'), t('La asignación debe terminar al menos hoy o en una fecha futura.'), 'warning');
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

        try {
            this.calendar = new FullCalendar.Calendar(this.element, calendarConfig);
        } catch (err) {
            calendarConfig.locale = window.SP_lang ? window.SP_lang() : 'es';
            this.calendar = new FullCalendar.Calendar(this.element, calendarConfig);
        }
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
        
        let isSameEvent = (this.activeEvent === event);
        this.activeEvent = event;
        
        let panel = document.getElementById(this.panelId);
        let titleEl = document.getElementById(`${this.panelId}-title`);
        let container = document.getElementById(`${this.panelId}-selector-container`);
        let extraBtns = document.getElementById(`${this.panelId}-extra-buttons`);
        let leaveRow = document.getElementById(`${this.panelId}-leave-row`);
        
        this.updatePanelDatesFromEvent(event);
        panel.style.display = 'block';
        if (leaveRow) {
            leaveRow.style.display = (this.context === 'worker' && !this.readonly) ? 'block' : 'none';
        }
        if (!isNew && this.embedded) {
            this._setEmbeddedModalHint(false);
        }

        if (!isSameEvent) {
            if (isNew) {
                if (this.context === 'solicitud') {
                    this.hidePanel();
                    if (this.activeEvent && this.activeEvent.id === this.ghostEventId) this.activeEvent.remove();
                    if (typeof Swal !== 'undefined') Swal.fire(t('Aviso'), t('No puedes crear asignaciones libres directamente desde la vista de solicitudes.'), 'info');
                    return;
                }

                titleEl.innerHTML = `<i class="fas fa-plus-circle mr-2 univ-calendar-icon"></i>${t('Nueva Asignación')}`;
                extraBtns.style.display = 'none';

                let notasRow = document.getElementById(`${this.panelId}-notas-row`);
                let notasInput = document.getElementById(`${this.panelId}-notas`);
                if (notasRow) notasRow.style.display = 'block';
                if (notasInput) notasInput.value = '';

                // Kanban / drag: multi-trabajador (con vehículo) y prefill del operario
                const dragPrefill = this._pendingPrefill || this.kanbanPrefill || null;
                const hasPrefill = !!(dragPrefill && (dragPrefill.workerId || dragPrefill.obraId));
                this._renderResourceSelect(container, hasPrefill ? dragPrefill : null);
                this._toggleVehicleRow(true);
            } else {
                titleEl.innerHTML = `<i class="fas fa-edit mr-2 univ-calendar-icon"></i>${t('Editar Asignación')}`;
                extraBtns.style.display = 'block';

                let notasRow = document.getElementById(`${this.panelId}-notas-row`);
                if (notasRow) notasRow.style.display = 'none';
                this._toggleVehicleRow(false);

                const props = event.extendedProps || {};
                if (this.context === 'worker' || this.context === 'obra' || this.context === 'vehiculo') {
                    let prefill = null;
                    if (this.context === 'worker') {
                        prefill = { obraId: props.obra_id, obraName: event.title };
                    } else if (this.context === 'obra' || this.context === 'vehiculo') {
                        prefill = {
                            workerId: props.worker_id,
                            workerName: event.title,
                        };
                        if (props.vehiculo_id) {
                            prefill.vehicleId = props.vehiculo_id;
                            prefill.vehicleLabel = props.vehiculo_label || t('Vehículo');
                        }
                    }
                    this._renderResourceSelect(container, prefill);
                } else {
                    container.innerHTML = `
                        <label class="small font-weight-bold mb-1 text-secondary">${t('Elemento Asignado')}</label>
                        <div class="form-control form-control-sm bg-light text-dark font-weight-bold" style="cursor: not-allowed; border: 1px solid #e2e8f0;">
                            ${event.title}
                        </div>
                    `;
                }

                let btnView = document.getElementById(`${this.panelId}-view`);
                if (btnView) {
                    btnView.onclick = () => {
                        if(props.obra_url) { window.open(props.obra_url, '_blank'); return;}
                        let targetUrl = null;
                        if (this.context === 'worker') targetUrl = this._adminUrl(`/admin/obra_panel/${props.obra_id}`);
                        else if (this.context === 'obra' || this.context === 'vehiculo') targetUrl = this._adminUrl(`/admin/worker_panel/${props.worker_id}`);
                        
                        if (targetUrl) window.open(targetUrl, '_blank');
                        else if(typeof Swal !== 'undefined') Swal.fire(t('Información'), t('No hay enlace directo disponible.'), 'info');
                    };
                }
            }
        }
    }

    _currentPanelDateRange() {
        const startInput = document.getElementById(`${this.panelId}-start`);
        const endInput = document.getElementById(`${this.panelId}-end`);
        const start = startInput ? startInput.value : '';
        const end = endInput ? endInput.value : '';
        return { start, end };
    }

    _vehicleAjaxData(term, workerId) {
        const range = this._currentPanelDateRange();
        return {
            q: term,
            start: range.start,
            end: range.end,
            worker_id: workerId || '',
        };
    }

    _initVehicleSelect($select, workerId, placeholder) {
        if (typeof $ === 'undefined' || !$.fn.select2) return $select;
        return this.initPanelSelect2($select, {
            placeholder: placeholder || t('Opcional: asignar vehículo...'),
            allowClear: true,
            ajax: {
                url: '/api/v6/vehicles',
                dataType: 'json',
                delay: 250,
                data: (p) => this._vehicleAjaxData(
                    p.term,
                    typeof workerId === 'function' ? workerId() : workerId
                ),
                processResults: (d) => ({ results: d.results || [] }),
            }
        });
    }

    _toggleVehicleRow(showForNew) {
        const row = document.getElementById(`${this.panelId}-vehicle-row`);
        const container = document.getElementById(`${this.panelId}-vehicle-container`);
        if (!row || !container) return;

        // En obra nueva la flota va por fila multi-trabajador; aquí solo worker context.
        const show = !!showForNew && this.context === 'worker';
        row.style.display = show ? 'flex' : 'none';
        if (!show) {
            const existing = $(`#${this.panelId}-vehicle-select`);
            if (existing.length && existing.data('select2')) existing.select2('destroy');
            container.innerHTML = '';
            return;
        }

        const existingSelect = $(`#${this.panelId}-vehicle-select`);
        if (existingSelect.length && existingSelect.data('select2')) {
            existingSelect.select2('destroy');
        }
        container.innerHTML = `
            <label class="small font-weight-bold mb-1 text-secondary"><i class="fas fa-car mr-1"></i>${t('Vehículo')}</label>
            <select id="${this.panelId}-vehicle-select" class="form-control form-control-sm" style="width: 100%;">
                <option></option>
            </select>
        `;
        setTimeout(() => {
            const $select = $(`#${this.panelId}-vehicle-select`);
            this._initVehicleSelect($select, this.context === 'worker' ? this.entityId : null);
        }, 150);
    }

    _destroySelect2In(container) {
        if (!container || typeof $ === 'undefined') return;
        $(container).find('select').each(function () {
            const $s = $(this);
            if ($s.data('select2')) $s.select2('destroy');
        });
    }

    _renderResourceSelect(container, prefill) {
        // Vista obra: siempre multi-fila (incluye toggle de vehículo). Prefill en la 1ª fila.
        if (this.context === 'obra') {
            this._renderMultiWorkerSelect(container, prefill);
            return;
        }

        let selectLabel = (this.context === 'vehiculo')
            ? t('Trabajador a asignar')
            : t('Obra destino');

        this._destroySelect2In(container);
        const existingSelect = $(`#${this.panelId}-select`);
        if (existingSelect.length && existingSelect.data('select2')) {
            existingSelect.select2('destroy');
        }

        container.innerHTML = `
            <label class="small font-weight-bold mb-1 text-secondary">${selectLabel}</label>
            <select id="${this.panelId}-select" class="form-control form-control-sm" style="width: 100%;">
                <option></option>
            </select>
        `;

        if (prefill) this._pendingPrefill = prefill;

        setTimeout(() => {
            let $select = $(`#${this.panelId}-select`);
            if (this.context === 'vehiculo') {
                if (typeof $ !== 'undefined' && $.fn.select2) {
                    this.initPanelSelect2($select, {
                        placeholder: t('Selecciona un operario...'),
                        allowClear: true,
                        ajax: {
                            url: '/admin/api/planificador/search_workers',
                            dataType: 'json', delay: 250,
                            data: (p) => ({ q: p.term }),
                            processResults: (d) => ({
                                results: (d.results || []).filter((r) => String(r.id) !== 'GENERICO')
                            })
                        }
                    });
                    this._applyPendingPrefillToSelect($select);
                }
            } else if (this.context === 'worker') {
                fetch('/api/v6/recursos_activos').then(r=>r.json()).then(data => {
                    if (typeof $ !== 'undefined' && $.fn.select2) {
                        this.initPanelSelect2($select, {
                            placeholder: t('Selecciona una obra (opcional si hay vehículo)...'),
                            allowClear: true,
                            data: data.obras
                        });
                        this._applyPendingPrefillToSelect($select);
                    }
                });
            }
        }, 150);
    }

    _allowGenericoRequest() {
        return !(window.JEFES_ASIGNAN_DIRECTO && window.SP_USER_ROLE === 'jefe_obra');
    }

    _renderMultiWorkerSelect(container, prefill) {
        this._destroySelect2In(container);
        container.innerHTML = `
            <div class="d-flex align-items-center justify-content-between mb-1">
                <label class="small font-weight-bold mb-0 text-secondary">${t('Trabajadores a asignar')}</label>
                <button type="button" class="btn btn-link btn-sm p-0" id="${this.panelId}-add-worker">
                    <i class="fas fa-plus mr-1"></i>${t('Añadir trabajador')}
                </button>
            </div>
            <div id="${this.panelId}-workers-list"></div>
            <select id="${this.panelId}-select" class="d-none" aria-hidden="true"><option></option></select>
        `;
        const list = document.getElementById(`${this.panelId}-workers-list`);
        this._addWorkerRow(list, { allowGenerico: this._allowGenericoRequest(), prefill: prefill || null });
        const addBtn = document.getElementById(`${this.panelId}-add-worker`);
        if (addBtn) {
            addBtn.addEventListener('click', () => {
                this._addWorkerRow(list, { allowGenerico: false });
            });
        }
    }

    _addWorkerRow(listEl, opts) {
        if (!listEl) return;
        opts = opts || {};
        const rowId = `${this.panelId}-wrow-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
        const row = document.createElement('div');
        row.className = 'univ-worker-row';
        row.dataset.rowId = rowId;
        row.innerHTML = `
            <div class="univ-worker-row-inner">
                <div class="univ-worker-row-main">
                    <label class="small text-muted mb-0">${t('Trabajador')}</label>
                    <select class="form-control form-control-sm univ-worker-select" style="width:100%;">
                        <option></option>
                    </select>
                </div>
                <div class="univ-worker-row-vehicle">
                    <div class="custom-control custom-switch mb-1">
                        <input type="checkbox" class="custom-control-input univ-vehicle-toggle" id="${rowId}-vehicle-toggle">
                        <label class="custom-control-label small text-muted" for="${rowId}-vehicle-toggle">
                            <i class="fas fa-car mr-1"></i>${t('Asignar vehículo')}
                        </label>
                    </div>
                    <div class="univ-vehicle-wrap" style="display:none;">
                        <select class="form-control form-control-sm univ-vehicle-select" style="width:100%;">
                            <option></option>
                        </select>
                    </div>
                </div>
                <div class="univ-worker-row-actions">
                    <button type="button" class="btn btn-sm btn-outline-danger univ-worker-remove" title="${t('Quitar')}">
                        <i class="fas fa-times"></i>
                    </button>
                </div>
            </div>
        `;
        listEl.appendChild(row);

        const allowGenerico = !!opts.allowGenerico;
        setTimeout(() => {
            const $w = $(row).find('.univ-worker-select');
            const $v = $(row).find('.univ-vehicle-select');
            const toggle = row.querySelector('.univ-vehicle-toggle');
            const vehicleWrap = row.querySelector('.univ-vehicle-wrap');
            if (typeof $ !== 'undefined' && $.fn.select2) {
                this.initPanelSelect2($w, {
                    placeholder: allowGenerico
                        ? t("Escribe o elige 'CUALQUIERA'...")
                        : t('Selecciona un trabajador...'),
                    allowClear: true,
                    ajax: {
                        url: '/admin/api/planificador/search_workers',
                        dataType: 'json', delay: 250,
                        data: (p) => ({ q: p.term }),
                        processResults: (d) => ({
                            results: allowGenerico
                                ? (d.results || [])
                                : (d.results || []).filter((r) => String(r.id) !== 'GENERICO'),
                        }),
                    },
                }).on('change', (e) => {
                    const gRow = document.getElementById(`${this.panelId}-generic-options`);
                    const rows = listEl.querySelectorAll('.univ-worker-row');
                    const onlyOne = rows.length === 1;
                    if (gRow && onlyOne) {
                        e.target.value === 'GENERICO' ? $(gRow).slideDown(150) : $(gRow).slideUp(150);
                    }
                    // Sync hidden #select for single/GENERICO legacy path
                    const hidden = document.getElementById(`${this.panelId}-select`);
                    if (hidden && onlyOne) hidden.value = e.target.value || '';
                });

                // Prefill kanban / drag: operario ya elegido, se puede cambiar
                if (opts.prefill && opts.prefill.workerId) {
                    const val = String(opts.prefill.workerId);
                    const label = opts.prefill.workerName || t('Operario');
                    if (!$w.find(`option[value="${val}"]`).length) {
                        $w.append(new Option(label, val, true, true));
                    }
                    $w.val(val).trigger('change');
                    const hidden = document.getElementById(`${this.panelId}-select`);
                    if (hidden) hidden.value = val;
                    this._pendingPrefill = null;

                    if (opts.prefill && opts.prefill.vehicleId) {
                        const vid = String(opts.prefill.vehicleId);
                        const vlabel = opts.prefill.vehicleLabel || t('Vehículo');
                        const workerIdFn = () => {
                            const workerSel = row.querySelector('.univ-worker-select');
                            if (!workerSel) return val;
                            return (typeof $ !== 'undefined' && $(workerSel).val)
                                ? $(workerSel).val()
                                : workerSel.value;
                        };
                        if (toggle) {
                            toggle.checked = true;
                            if (vehicleWrap) vehicleWrap.style.display = 'block';
                        }
                        if (!$v.data('select2')) {
                            this._initVehicleSelect($v, workerIdFn, t('Selecciona vehículo...'));
                        }
                        if (!$v.find(`option[value="${vid}"]`).length) {
                            $v.append(new Option(vlabel, vid, true, true));
                        }
                        $v.val(vid).trigger('change');
                    }
                }

                if (toggle) {
                    toggle.addEventListener('change', () => {
                        const showVehicle = !!toggle.checked;
                        if (vehicleWrap) {
                            vehicleWrap.style.display = showVehicle ? 'block' : 'none';
                        }
                        if (!showVehicle) {
                            if ($v.data('select2')) $v.val(null).trigger('change');
                            return;
                        }
                        if (!$v.data('select2')) {
                            const workerId = () => {
                                const workerSel = row.querySelector('.univ-worker-select');
                                if (!workerSel) return null;
                                return (typeof $ !== 'undefined' && $(workerSel).val)
                                    ? $(workerSel).val()
                                    : workerSel.value;
                            };
                            this._initVehicleSelect($v, workerId, t('Selecciona vehículo...'));
                        }
                    });
                }
            }
        }, 50);

        const removeBtn = row.querySelector('.univ-worker-remove');
        if (removeBtn) {
            removeBtn.addEventListener('click', () => {
                const rows = listEl.querySelectorAll('.univ-worker-row');
                if (rows.length <= 1) {
                    if (typeof Swal !== 'undefined') {
                        Swal.fire(t('Atención'), t('Debe quedar al menos un trabajador.'), 'info');
                    }
                    return;
                }
                this._destroySelect2In(row);
                row.remove();
                const gRow = document.getElementById(`${this.panelId}-generic-options`);
                if (gRow) $(gRow).slideUp(150);
            });
        }
    }

    _collectMultiWorkers() {
        const list = document.getElementById(`${this.panelId}-workers-list`);
        if (!list) return null;
        const workers = [];
        list.querySelectorAll('.univ-worker-row').forEach((row, index) => {
            const wSel = row.querySelector('.univ-worker-select');
            const vSel = row.querySelector('.univ-vehicle-select');
            const vToggle = row.querySelector('.univ-vehicle-toggle');
            let wid = null;
            if (wSel) {
                wid = (typeof $ !== 'undefined' && $(wSel).val) ? $(wSel).val() : wSel.value;
            }
            if (!wid) return;
            const entry = { worker_id: wid, index };
            let vid = null;
            if (vToggle && vToggle.checked && vSel) {
                vid = (typeof $ !== 'undefined' && $(vSel).val) ? $(vSel).val() : vSel.value;
            }
            if (vid) entry.vehicle_id = vid;
            workers.push(entry);
        });
        return workers;
    }

    _resolvePanelWorkerId(props) {
        props = props || {};
        let val = null;
        const hidden = document.getElementById(`${this.panelId}-select`);
        if (hidden && hidden.value) val = hidden.value;

        if (this.context === 'obra') {
            const multi = this._collectMultiWorkers();
            if (multi && multi.length === 1 && multi[0].worker_id) {
                val = String(multi[0].worker_id);
                if (hidden) hidden.value = val;
            }
        }

        if (!val && props.worker_id) val = String(props.worker_id);
        return val;
    }

    _resolvePanelVehicleId() {
        if (this.context === 'obra') {
            const multi = this._collectMultiWorkers();
            if (multi && multi.length === 1 && multi[0].vehicle_id) {
                return multi[0].vehicle_id;
            }
            return null;
        }
        const vehicleEl = document.getElementById(`${this.panelId}-vehicle-select`);
        return (this.context === 'worker' && vehicleEl && vehicleEl.value)
            ? vehicleEl.value
            : null;
    }

    _assignmentDatesChanged(props, startVal, endVal) {
        if (!this.activeEvent) return true;
        props = props || this.activeEvent.extendedProps || {};
        const origStart = moment(props.real_original_start || this.activeEvent.start).format('YYYY-MM-DD');
        let origEnd = startVal;
        if (props.real_original_end) {
            origEnd = moment(props.real_original_end).subtract(1, 'days').format('YYYY-MM-DD');
        } else if (this.activeEvent.end) {
            origEnd = moment(this.activeEvent.end).subtract(1, 'days').format('YYYY-MM-DD');
        }
        return origStart !== startVal || origEnd !== endVal;
    }

    _showBatchAssignResult(res) {
        const results = (res && res.results) || [];
        const failed = results.filter((r) => !r.success);
        const ok = results.filter((r) => r.success);
        if (!failed.length) {
            if (typeof Swal !== 'undefined') {
                Swal.fire({
                    toast: true, position: 'top-end', icon: 'success',
                    title: res.message || t('Guardado'),
                    showConfirmButton: false, timer: 2000,
                });
            }
            return;
        }
        let html = `<p class="mb-2 text-left">${res.message || ''}</p><ul class="text-left small mb-0">`;
        failed.forEach((r) => {
            const name = r.worker_name || (`#${r.worker_id}`);
            const reason = r.message || r.error || t('Error');
            const leaveTag = r.conflict_type === 'leave'
                ? ` <span class="badge badge-warning">${t('Ausencia')}</span>`
                : '';
            html += `<li><b>${name}</b>${leaveTag}: ${reason}</li>`;
        });
        html += '</ul>';
        if (typeof Swal !== 'undefined') {
            Swal.fire({
                title: ok.length ? t('Asignación parcial') : t('No se pudo asignar'),
                html,
                icon: ok.length ? 'warning' : 'error',
                confirmButtonText: t('Entendido'),
            });
        }
    }

    updatePanelDatesFromEvent(event) {
        if (!this.activeEvent || this.activeEvent !== event) return;
        let startInput = document.getElementById(`${this.panelId}-start`);
        let endInput = document.getElementById(`${this.panelId}-end`);
        
        if (startInput) startInput.value = moment(event.start).format('YYYY-MM-DD');
        if (endInput) endInput.value = event.end ? moment(event.end).subtract(1, 'days').format('YYYY-MM-DD') : startInput.value;
    }

    bindPanelIsolation() {
        const panel = document.getElementById(this.panelId);
        if (!panel || panel.dataset.isolationBound) return;
        panel.dataset.isolationBound = '1';
        panel.addEventListener('mousedown', (e) => e.stopPropagation());
        panel.addEventListener('click', (e) => e.stopPropagation());
    }

    initPanelSelect2($select, extraOpts = {}) {
        if (!$select || !$select.length || typeof $ === 'undefined' || !$.fn.select2) return $select;
        if ($select.data('select2')) {
            $select.select2('destroy');
        }
        const panel = document.getElementById(this.panelId);
        const modal = panel ? panel.closest('.modal') : null;
        // Siempre body: fixed escapea transform del modal (si no, el listado queda bajo el FC).
        const opts = Object.assign({
            dropdownParent: $(document.body),
            dropdownCssClass: 'admin-select2-dropdown univ-calendar-select2-dropdown',
            width: '100%',
        }, extraOpts);
        $select.select2(opts);
        if (window.SignaPlanSelect2 && typeof window.SignaPlanSelect2.bindFixedDropdown === 'function') {
            const roots = [
                document.querySelector('.planificador-page'),
                document.querySelector('.admin-main'),
                modal ? modal.querySelector('.modal-body') : null,
                modal,
                panel,
                document.querySelector('.fc'),
            ].filter(Boolean);
            window.SignaPlanSelect2.bindFixedDropdown($select, roots);
        }
        return $select;
    }

    bindPanelEvents() {
        let startInput = document.getElementById(`${this.panelId}-start`);
        let endInput = document.getElementById(`${this.panelId}-end`);
        let saveBtn = document.getElementById(`${this.panelId}-save`);
        let delBtn = document.getElementById(`${this.panelId}-delete`);
        let leaveBtn = document.getElementById(`${this.panelId}-leave`);

        if(startInput) startInput.addEventListener('change', (e) => {
            if(this.activeEvent && e.target.value) this.activeEvent.setStart(e.target.value);
        });
        
        if(endInput) endInput.addEventListener('change', (e) => {
            if(this.activeEvent && e.target.value) this.activeEvent.setEnd(moment(e.target.value).add(1, 'days').format('YYYY-MM-DD'));
        });

        if (leaveBtn) leaveBtn.addEventListener('click', () => {
            if (this.readonly || this.context !== 'worker' || !this.entityId) return;
            let startVal = startInput ? startInput.value : null;
            let endVal = endInput ? endInput.value : null;
            if (!startVal || !endVal) {
                if (typeof Swal !== 'undefined') Swal.fire(t('Atención'), t('Indica fecha de inicio y fin.'), 'warning');
                return;
            }
            const TIPO_VACACIONES = 'Vacaciones';
            const doSave = (tipo) => {
                fetch('/api/v6/ausencias', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': (document.querySelector('meta[name="csrf-token"]') || {}).content || '',
                    },
                    body: JSON.stringify({
                        worker_id: this.entityId,
                        fecha_inicio: startVal,
                        fecha_fin: endVal,
                        tipo: tipo || TIPO_VACACIONES,
                    }),
                })
                .then((r) => r.json().then((res) => ({ ok: r.ok, res })).catch(() => ({ ok: false, res: null })))
                .then(({ ok, res }) => {
                    if (!ok || !res || !res.success) {
                        const msg = (res && (res.error || res.message)) || t('No se pudo guardar');
                        if (typeof Swal !== 'undefined') Swal.fire(t('Error'), msg, 'error');
                        return;
                    }
                    if (typeof Swal !== 'undefined') {
                        Swal.fire({
                            toast: true,
                            position: 'top-end',
                            icon: 'success',
                            title: res.message || t('Ausencia guardada'),
                            showConfirmButton: false,
                            timer: 2200,
                        });
                    }
                    this.calendar.refetchEvents();
                    this.hidePanel();
                })
                .catch(() => {
                    if (typeof Swal !== 'undefined') Swal.fire(t('Error'), t('Fallo de conexión'), 'error');
                });
            };
            if (typeof Swal !== 'undefined') {
                Swal.fire({
                    title: t('Marcar ausencia'),
                    input: 'text',
                    inputValue: t(TIPO_VACACIONES),
                    inputPlaceholder: t('Tipo (Vacaciones, Baja…)'),
                    showCancelButton: true,
                    confirmButtonText: t('Guardar'),
                    cancelButtonText: t('Cancelar'),
                }).then((result) => {
                    if (result.isConfirmed) {
                        var raw = String(result.value || '').trim();
                        doSave(!raw || raw === t(TIPO_VACACIONES) ? TIPO_VACACIONES : raw);
                    }
                });
            } else {
                doSave(TIPO_VACACIONES);
            }
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
                    if(typeof Swal !== 'undefined') Swal.fire(t('Error'), t('No puedes planificar en el pasado.'), 'error');
                    return;
                }
                
                let selEl = document.getElementById(`${this.panelId}-select`);
                let selVal = selEl ? selEl.value : null;

                if (this.callbacks.onSaveNew && !selEl) {
                    this.callbacks.onSaveNew(startVal, endVal, includeWeekends);
                    return;
                }

                let vehicleEl = document.getElementById(`${this.panelId}-vehicle-select`);
                let vehicleVal = (this.context === 'worker' && vehicleEl) ? vehicleEl.value : null;
                let notasEl = document.getElementById(`${this.panelId}-notas`);
                let notasVal = notasEl ? notasEl.value.trim() : '';

                if (this.context === 'vehiculo') {
                    if (!selVal || String(selVal) === 'GENERICO') {
                        Swal.fire(t('Atención'), t('Selecciona un operario para asignar el vehículo.'), 'warning');
                        return;
                    }
                    const vPayload = {
                        worker_id: selVal,
                        vehicle_id: this.entityId,
                        start: startVal,
                        end: endVal,
                        include_weekends: includeWeekends,
                        overwrite_mode: 'check'
                    };
                    if (notasVal) vPayload.notas = notasVal;
                    this.executeVehicleSave(vPayload, (vres) => {
                        if (!vres || !vres.success) return;
                        if (typeof Swal !== 'undefined') {
                            Swal.fire({toast: true, position: 'top-end', icon: 'success', title: vres.message || t('Vehículo asignado'), showConfirmButton: false, timer: 1800});
                        }
                        this.calendar.refetchEvents(); this.hidePanel();
                        if (window.loadTimelineData) window.loadTimelineData();
                    });
                    return;
                }

                if (this.context === 'worker') {
                    if (!selVal && !vehicleVal) {
                        Swal.fire(t('Atención'), t('Selecciona una obra y/o un vehículo, o usa «Marcar vacaciones».'), 'warning');
                        return;
                    }
                }

                // Obra: multi-trabajador (nueva asignación)
                const multiWorkers = (this.context === 'obra') ? this._collectMultiWorkers() : null;
                if (this.context === 'obra' && multiWorkers !== null) {
                    if (!multiWorkers.length) {
                        Swal.fire(t('Atención'), t('Debes seleccionar al menos un trabajador.'), 'warning');
                        return;
                    }
                    // Un solo GENERICO → flujo legacy de solicitud genérica
                    if (multiWorkers.length === 1 && String(multiWorkers[0].worker_id) === 'GENERICO') {
                        selVal = 'GENERICO';
                    } else {
                        const realWorkers = multiWorkers.filter((w) => String(w.worker_id) !== 'GENERICO');
                        if (!realWorkers.length) {
                            Swal.fire(t('Atención'), t('Debes seleccionar trabajadores concretos.'), 'warning');
                            return;
                        }
                        // Un solo trabajador: legacy (conflictos interactivos) + vehículo de la fila
                        if (realWorkers.length === 1) {
                            selVal = String(realWorkers[0].worker_id);
                            if (realWorkers[0].vehicle_id) {
                                // Reutilizar runVehicleSave más abajo inyectando worker de la fila
                                vehicleVal = realWorkers[0].vehicle_id;
                                // Marcar worker para vehículo post-obra
                                this._pendingObraVehicleWorkerId = selVal;
                            }
                        } else {
                            let payload = {
                                start_date: startVal,
                                end_date: endVal,
                                original_start: null,
                                original_end: null,
                                overwrite_mode: 'check',
                                include_weekends: includeWeekends,
                                target_obra_id: this.entityId,
                                old_obra_id: (this.kanbanSourceObraId !== undefined && this.kanbanSourceObraId !== null)
                                    ? this.kanbanSourceObraId : this.entityId,
                                workers: realWorkers,
                            };
                            if (notasVal) payload.notas = notasVal;
                            this.executeSave(payload, (obraRes) => {
                                if (!obraRes) return;
                                if (obraRes.batch) {
                                    this._showBatchAssignResult(obraRes);
                                    if (obraRes.ok_count > 0) {
                                        this.calendar.refetchEvents();
                                        this.hidePanel();
                                        if (window.loadTimelineData) window.loadTimelineData();
                                    }
                                    return;
                                }
                                if (!obraRes.success) return;
                                this.calendar.refetchEvents();
                                this.hidePanel();
                                if (window.loadTimelineData) window.loadTimelineData();
                            }, { skipHideOnSuccess: true, skipSuccessToast: true });
                            return;
                        }
                    }
                }

                if (this.context !== 'worker' && !selVal) {
                    Swal.fire(t('Atención'), t('Debes seleccionar un destino/trabajador.'), 'warning');
                    return;
                }

                let qtyEl = document.getElementById(`${this.panelId}-quantity`);
                let qty = qtyEl ? parseInt(qtyEl.value) || 1 : 1;

                const afterSave = (opts) => this._finishPanelSave(opts || {});

                const runVehicleSave = (onDone) => {
                    const vWorker = this._pendingObraVehicleWorkerId || (
                        this.context === 'worker' ? this.entityId : null
                    );
                    this._pendingObraVehicleWorkerId = null;
                    if (!vehicleVal || !vWorker) {
                        if (onDone) onDone({ success: true });
                        return;
                    }
                    const vPayload = {
                        worker_id: vWorker,
                        vehicle_id: vehicleVal,
                        start: startVal,
                        end: endVal,
                        include_weekends: includeWeekends,
                        overwrite_mode: 'check'
                    };
                    if (notasVal) vPayload.notas = notasVal;
                    this.executeVehicleSave(vPayload, onDone);
                };

                if (selVal) {
                    let payload = {
                        start_date: startVal, end_date: endVal, original_start: null, original_end: null,
                        overwrite_mode: 'check', include_weekends: includeWeekends, cantidad: selVal === 'GENERICO' ? qty : 1
                    };
                    if (notasVal) payload.notas = notasVal;

                    if (this.context === 'obra') {
                        payload.worker_id = selVal;
                        payload.target_obra_id = this.entityId;
                        payload.old_obra_id = (this.kanbanSourceObraId !== undefined && this.kanbanSourceObraId !== null)
                            ? this.kanbanSourceObraId : this.entityId;
                    } else if (this.context === 'worker') {
                        payload.worker_id = this.entityId;
                        payload.target_obra_id = selVal;
                        payload.old_obra_id = (this.kanbanSourceObraId !== undefined && this.kanbanSourceObraId !== null)
                            ? this.kanbanSourceObraId : selVal;
                    }

                    if (this.context === 'obra' && vehicleVal && !this._pendingObraVehicleWorkerId) {
                        this._pendingObraVehicleWorkerId = selVal;
                    }

                    this.executeSave(payload, (obraRes) => {
                        // Solo continuar con vehículo si la obra se guardó (cancelar conflicto no pasa success)
                        if (!obraRes || !obraRes.success) return;
                        runVehicleSave((vres) => {
                            if (!vres || !vres.success) return;
                            afterSave();
                        });
                    }, { skipHideOnSuccess: !!vehicleVal && (this.context === 'worker' || this.context === 'obra') });
                } else {
                    // Solo vehículo (contexto worker)
                    runVehicleSave((vres) => {
                        if (!vres || !vres.success) return;
                        afterSave({ message: vres.message || t('Vehículo guardado') });
                    });
                }

            } else {
                let originalStart = moment(this.activeEvent.extendedProps.real_original_start || this.activeEvent.start).startOf('day');
                
                if (originalStart.isSameOrAfter(today) && moment(startVal).isBefore(today)) {
                    if(typeof Swal !== 'undefined') Swal.fire(t('Error'), t('No puedes mover hacia el pasado.'), 'error');
                    return;
                }
                if (moment(endVal).isBefore(today)) {
                    if(typeof Swal !== 'undefined') Swal.fire(t('Error'), t('La fecha de fin no puede apuntar al pasado.'), 'error');
                    return;
                }

                let selEl = document.getElementById(`${this.panelId}-select`);
                const props = this.activeEvent.extendedProps || {};
                let selVal = this._resolvePanelWorkerId(props);

                let payload = {
                    start_date: startVal,
                    end_date: endVal,
                    original_start: this.activeEvent.extendedProps.real_original_start,
                    original_end: this.activeEvent.extendedProps.real_original_end ? moment(this.activeEvent.extendedProps.real_original_end).subtract(1, 'days').format('YYYY-MM-DD') : null,
                    overwrite_mode: 'check',
                    include_weekends: includeWeekends
                };

                const afterSave = (opts) => this._finishPanelSave(opts || {});

                if (this.context === 'worker') {
                    if (!selVal) {
                        if (typeof Swal !== 'undefined') Swal.fire(t('Atención'), t('Debes seleccionar una obra.'), 'warning');
                        return;
                    }
                    payload.worker_id = this.entityId;
                    payload.old_obra_id = props.obra_id;
                    payload.target_obra_id = selVal;
                } else if (this.context === 'vehiculo') {
                    if (!selVal || String(selVal) === 'GENERICO') {
                        if (typeof Swal !== 'undefined') Swal.fire(t('Atención'), t('Selecciona un operario.'), 'warning');
                        return;
                    }
                    const oldWorkerId = props.worker_id;
                    const afterVehicleSave = () => {
                        this.calendar.refetchEvents(); this.hidePanel();
                        if (window.loadTimelineData) window.loadTimelineData();
                    };
                    const assignNew = () => {
                        const vPayload = {
                            worker_id: selVal,
                            vehicle_id: this.entityId,
                            start: startVal,
                            end: endVal,
                            include_weekends: includeWeekends,
                            overwrite_mode: 'overwrite',
                            accion: 'ASIGNAR',
                        };
                        this.executeVehicleSave(vPayload, (vres) => {
                            if (!vres || !vres.success) return;
                            if (typeof Swal !== 'undefined') {
                                Swal.fire({toast: true, position: 'top-end', icon: 'success', title: vres.message || t('Guardado'), showConfirmButton: false, timer: 1500});
                            }
                            afterVehicleSave();
                        });
                    };
                    // Limpiar rango original editable, luego asignar el nuevo
                    if (oldWorkerId) {
                        const origStart = this.activeEvent.extendedProps.real_original_start
                            || moment(this.activeEvent.start).format('YYYY-MM-DD');
                        let origEnd = endVal;
                        if (this.activeEvent.extendedProps.real_original_end) {
                            origEnd = moment(this.activeEvent.extendedProps.real_original_end).subtract(1, 'days').format('YYYY-MM-DD');
                        } else if (this.activeEvent.end) {
                            origEnd = moment(this.activeEvent.end).subtract(1, 'days').format('YYYY-MM-DD');
                        }
                        // Solo desasignar días futuros del rango original
                        const clearStart = moment(origStart).isBefore(today) ? today.format('YYYY-MM-DD') : origStart;
                        this.executeVehicleSave({
                            worker_id: oldWorkerId,
                            vehicle_id: this.entityId,
                            start: clearStart,
                            end: origEnd,
                            include_weekends: true,
                            overwrite_mode: 'overwrite',
                            accion: 'DESASIGNAR',
                        }, (vres) => {
                            if (!vres || !vres.success) return;
                            assignNew();
                        });
                    } else {
                        assignNew();
                    }
                    return;
                } else if (this.context === 'obra') {
                    const vehicleVal = this._resolvePanelVehicleId();
                    if (!selVal) {
                        if (typeof Swal !== 'undefined') Swal.fire(t('Atención'), t('Debes seleccionar un trabajador.'), 'warning');
                        return;
                    }
                    const oldWorkerId = props.worker_id;
                    payload.target_obra_id = this.entityId;
                    payload.old_obra_id = this.entityId;
                    payload.worker_id = selVal;

                    const finishWithVehicle = (next) => {
                        if (!vehicleVal) {
                            if (next) next({ success: true });
                            return;
                        }
                        this.executeVehicleSave({
                            worker_id: selVal,
                            vehicle_id: vehicleVal,
                            start: startVal,
                            end: endVal,
                            include_weekends: includeWeekends,
                            overwrite_mode: 'check',
                        }, next);
                    };

                    const saveAssignment = (cb) => {
                        if (this.callbacks.onEventModified) {
                            this.callbacks.onEventModified(payload, () => cb({ success: true }));
                        } else {
                            this.executeSave(payload, cb, { skipHideOnSuccess: !!vehicleVal });
                        }
                    };

                    if (oldWorkerId && String(selVal) !== String(oldWorkerId) && String(selVal) !== 'GENERICO') {
                        const dates = this._buildEditableDates(startVal, endVal);
                        if (!dates.length) {
                            if (typeof Swal !== 'undefined') Swal.fire(t('Histórico Protegido'), t('No hay días futuros editables en este bloque.'), 'info');
                            return;
                        }
                        this._unassignThenSave(oldWorkerId, this.entityId, dates, payload, (res) => {
                            if (!res || res.success === false) return;
                            saveAssignment((obraRes) => {
                                if (!obraRes || !obraRes.success) return;
                                finishWithVehicle((vres) => {
                                    if (!vres || !vres.success) return;
                                    afterSave();
                                });
                            });
                        });
                        return;
                    }

                    const datesChanged = this._assignmentDatesChanged(props, startVal, endVal);
                    const vehicleOnly = !!(vehicleVal && oldWorkerId && String(selVal) === String(oldWorkerId) && !datesChanged);

                    if (vehicleOnly) {
                        finishWithVehicle((vres) => {
                            if (!vres || !vres.success) return;
                            afterSave({ message: vres.message || t('Vehículo guardado') });
                        });
                        return;
                    }

                    saveAssignment((obraRes) => {
                        if (!obraRes || !obraRes.success) return;
                        finishWithVehicle((vres) => {
                            if (!vres || !vres.success) return;
                            afterSave();
                        });
                    });
                    return;
                } else {
                    payload.worker_id = props.worker_id || this.entityId;
                    payload.target_obra_id = this.entityId;
                    payload.old_obra_id = this.entityId;
                }

                if (this.callbacks.onEventModified) {
                    this.callbacks.onEventModified(payload, null); 
                } else {
                    this.executeSave(payload, afterSave);
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
                if (typeof Swal !== 'undefined') Swal.fire(t('Histórico Protegido'), t('Este bloque pertenece íntegramente al pasado y no se puede borrar.'), 'info');
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
                    ? `${t('Se conservará el histórico pasado, pero se vaciarán')} <b class="text-danger">${daysCount} ${t('día(s)')}</b> ${t('desde hoy en adelante.')}` 
                    : `${t('Se vaciarán')} <b class="text-danger">${daysCount} ${t('día(s)')}</b>.`;

                const swalBase = typeof window.adminSwalDefaults === 'function' ? window.adminSwalDefaults : (o) => o;
                Swal.fire(swalBase({
                    title: t('¿Desasignar bloque?'),
                    html: msg,
                    icon: 'warning',
                    showCancelButton: true,
                    confirmButtonText: t('Sí, borrar'),
                    cancelButtonText: t('Cancelar'),
                    customClass: {
                        popup: 'admin-swal-popup',
                        title: 'admin-swal-title',
                        htmlContainer: 'admin-swal-html',
                        confirmButton: 'admin-swal-btn admin-swal-btn-danger',
                        cancelButton: 'admin-swal-btn admin-swal-btn-ghost',
                        actions: 'admin-swal-actions',
                    },
                })).then((res) => {
                    if (res.isConfirmed) {
                        if (this.callbacks.onDeleteAssignment) {
                            this.callbacks.onDeleteAssignment(this.activeEvent, dates, originalStart.isBefore(today));
                            this.hidePanel();
                        } else if (this.context === 'vehiculo') {
                            const wId = this.activeEvent.extendedProps.worker_id;
                            if (!wId) {
                                Swal.fire(t('Error'), t('No se pudo identificar el operario del bloque.'), 'error');
                                return;
                            }
                            this.executeVehicleSave({
                                worker_id: wId,
                                vehicle_id: this.entityId,
                                start: start.format('YYYY-MM-DD'),
                                end: end.format('YYYY-MM-DD'),
                                include_weekends: true,
                                overwrite_mode: 'overwrite',
                                accion: 'DESASIGNAR',
                            }, (vres) => {
                                if (!vres || !vres.success) return;
                                Swal.fire({toast: true, position: 'top-end', icon: 'success', title: vres.message || t('Desasignado'), showConfirmButton: false, timer: 1500});
                                this.calendar.refetchEvents(); this.hidePanel();
                                if (window.loadTimelineData) window.loadTimelineData();
                            });
                        } else {
                            let wId = this.context === 'worker' ? this.entityId : this.activeEvent.extendedProps.worker_id;
                            let oId = this.context === 'obra' ? this.entityId : this.activeEvent.extendedProps.obra_id;
                            if (!oId || oId === '0' || oId === 0) oId = null;

                            let csrf = "";
                            let parts = ("; " + document.cookie).split("; csrf_token=");
                            if (parts.length === 2) csrf = parts.pop().split(";").shift();

                            fetch('/api/v6/unassign_worker', {
                                method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
                                body: JSON.stringify({ worker_id: wId, obra_id: oId, dates: dates, mode: 'selected' })
                            }).then(r=>r.json()).then(data => {
                                if(data.success) {
                                    Swal.fire({toast: true, position: 'top-end', icon: 'success', title: t('Borrado'), showConfirmButton: false, timer: 1500});
                                    this.calendar.refetchEvents(); this.hidePanel();
                                    if (window.loadTimelineData) window.loadTimelineData();
                                } else { Swal.fire(t('Error'), data.message, 'error'); }
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
    
    hidePanel(opts) { 
        opts = opts || {};
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
        const workersList = document.getElementById(`${this.panelId}-workers-list`);
        if (workersList) {
            this._destroySelect2In(workersList);
            workersList.innerHTML = '';
        }
        const selectorContainer = document.getElementById(`${this.panelId}-selector-container`);
        if (selectorContainer) {
            this._destroySelect2In(selectorContainer);
            selectorContainer.innerHTML = '';
        }
        const hiddenSelect = document.getElementById(`${this.panelId}-select`);
        if (hiddenSelect) hiddenSelect.value = '';
        this._pendingPrefill = null;
        this._pendingObraVehicleWorkerId = null;
        this.activeEvent = null;
        this._toggleVehicleRow(false);
        if (this.embedded && !opts.skipScroll) {
            this._scrollEmbeddedToCalendar();
        }
    }

    _setEmbeddedModalHint(showEmpty) {
        if (!this.embedded) return;
        const hintEmpty = document.getElementById('modalAssignHintEmpty');
        const hintPrefill = document.getElementById('modalAssignHintPrefill');
        if (hintEmpty) hintEmpty.classList.toggle('d-none', !showEmpty);
        if (hintPrefill && showEmpty) hintPrefill.classList.add('d-none');
    }

    _scrollEmbeddedToCalendar() {
        const modalBody = this._embeddedModal && this._embeddedModal.querySelector('.modal-body');
        if (!modalBody || !this.element) return;
        setTimeout(() => {
            const top = Math.max(0, this.element.offsetTop - 16);
            modalBody.scrollTo({ top, behavior: 'smooth' });
        }, 80);
    }

    _finishPanelSave(opts) {
        opts = opts || {};
        if (!opts.skipToast && typeof Swal !== 'undefined') {
            Swal.fire({
                toast: true,
                position: 'top-end',
                icon: 'success',
                title: opts.message || t('Guardado'),
                showConfirmButton: false,
                timer: 1500,
            });
        }
        this.hidePanel({ skipScroll: true });
        this.calendar.refetchEvents();
        if (this.embedded) {
            setTimeout(() => this._scrollEmbeddedToCalendar(), 220);
        }
        if (window.loadTimelineData) window.loadTimelineData();
        try {
            if (window.jQuery) {
                window.jQuery(document).trigger('sp-calendar-assigned', [opts.result || {}]);
            }
        } catch (eCal) { /* ignore */ }
    }

    _buildEditableDates(startVal, endVal) {
        const today = moment().startOf('day');
        let start = moment(startVal).startOf('day');
        let end = moment(endVal).startOf('day');
        if (start.isBefore(today)) start = today.clone();
        const dates = [];
        let curr = start.clone();
        while (curr.isSameOrBefore(end)) {
            dates.push(curr.format('YYYY-MM-DD'));
            curr.add(1, 'days');
        }
        return dates;
    }

    _csrfToken() {
        let csrf = "";
        const meta = document.querySelector('meta[name="csrf-token"]');
        if (meta && meta.content) return meta.content;
        let parts = ("; " + document.cookie).split("; csrf_token=");
        if (parts.length === 2) csrf = parts.pop().split(";").shift();
        return csrf;
    }

    _unassignThenSave(workerId, obraId, dates, assignPayload, afterSave) {
        fetch('/api/v6/unassign_worker', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': this._csrfToken() },
            body: JSON.stringify({ worker_id: workerId, obra_id: obraId, dates: dates, mode: 'selected' })
        }).then(r => r.json()).then(data => {
            if (!data.success) {
                if (typeof Swal !== 'undefined') Swal.fire(t('Error'), data.message || t('No se pudo desasignar al trabajador anterior.'), 'error');
                return;
            }
            // Tras desasignar, el alta del nuevo es una asignación nueva (sin rango original)
            const createPayload = Object.assign({}, assignPayload, {
                original_start: null,
                original_end: null,
                overwrite_mode: 'check',
            });
            this.executeSave(createPayload, afterSave);
        }).catch(() => {
            if (typeof Swal !== 'undefined') Swal.fire(t('Error'), t('Error de red al cambiar el trabajador.'), 'error');
        });
    }

    _applyPendingPrefillToSelect($select) {
        if (!this._pendingPrefill || !$select || !$select.length) return;
        const pf = this._pendingPrefill;
        this._pendingPrefill = null;
        if (this.context === 'obra' && pf.workerId) {
            const val = String(pf.workerId);
            if (!$select.find(`option[value="${val}"]`).length) {
                $select.append(new Option(pf.workerName || t('Operario'), val, true, true));
            }
            $select.val(val).trigger('change');
        } else if (this.context === 'vehiculo' && pf.workerId) {
            const val = String(pf.workerId);
            if (!$select.find(`option[value="${val}"]`).length) {
                $select.append(new Option(pf.workerName || t('Operario'), val, true, true));
            }
            $select.val(val).trigger('change');
        } else if (this.context === 'worker' && pf.obraId) {
            const val = String(pf.obraId);
            if (!$select.find(`option[value="${val}"]`).length) {
                $select.append(new Option(pf.obraName || t('Obra'), val, true, true));
            }
            $select.val(val).trigger('change');
        }
    }

    prefillKanbanAssignment({ dateStr, workerId, workerName, obraId, obraName }) {
        this.kanbanPrefill = { dateStr, workerId, workerName, obraId, obraName };
        this._pendingPrefill = { workerId, workerName, obraId, obraName };
        if (!this.calendar) return;
        this.calendar.gotoDate(dateStr);
        setTimeout(() => this.createGhostEvent(dateStr), 200);
    }

    createGhostEvent(dateStr) {
        let existingGhost = this.calendar.getEventById(this.ghostEventId);
        if (existingGhost) existingGhost.remove();

        let endStr = moment(dateStr).add(1, 'days').format('YYYY-MM-DD');

        let ghost = this.calendar.addEvent({
            id: this.ghostEventId, title: t('NUEVA ASIGNACIÓN'), start: dateStr, end: endStr,
            className: 'fc-ghost-event', editable: true, extendedProps: { isGhost: 1 }
        });

        this.showBottomPanel(ghost, true);
    }
    
    createGhostEventRange(startStr, endStr) {
        let existingGhost = this.calendar.getEventById(this.ghostEventId);
        if (existingGhost) existingGhost.remove();

        let endObj = moment(endStr).add(1, 'days').format('YYYY-MM-DD'); 
        
        let ghost = this.calendar.addEvent({
            id: this.ghostEventId, title: t('NUEVA ASIGNACIÓN'), start: startStr, end: endObj,
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
        if (this._embeddedModal) {
            const modalBody = this._embeddedModal.querySelector('.modal-body');
            if (modalBody) {
                const closeBtn = modalBody.querySelector('.univ-calendar-modal-close');
                if (closeBtn) closeBtn.remove();
            }
            this._embeddedModal.classList.remove('univ-calendar-embedded');
            this._embeddedModal = null;
        }
        if (this.element) this.element.innerHTML = ''; 
    }

    executeSave(payload, revertFunc, options) {
        if (!payload.overwrite_mode) payload.overwrite_mode = 'check';
        payload.check_conflicts = true;
        options = options || {};

        $.ajax({
            url: "/api/v6/planificador/action",
            type: "POST",
            contentType: "application/json",
            data: JSON.stringify(payload),
            success: (res) => {
                if (res.success) {
                    if (!options.skipHideOnSuccess) {
                        if (!options.skipSuccessToast && typeof Swal !== 'undefined') {
                            Swal.fire({toast: true, position: 'top-end', icon: 'success', title: t('Guardado'), showConfirmButton: false, timer: 1500});
                        }
                        this.calendar.refetchEvents();
                        this.hidePanel();
                    }
                    if (this.callbacks.onAfterSave) this.callbacks.onAfterSave(res);
                    try {
                        if (window.jQuery) {
                            window.jQuery(document).trigger('sp-calendar-assigned', [res]);
                        }
                    } catch (eCal) { /* ignore */ }
                    if(revertFunc) revertFunc(res);
                    
                } else if (res.batch) {
                    // Lote parcial o total fallido: el callback muestra detalle por fila
                    if (revertFunc) revertFunc(res);
                } else if (res.conflict || res.action === 'confirm_overwrite') {
                    if (typeof window.resolverConflictoAsignacion === 'function') {
                        window.resolverConflictoAsignacion(
                            res, payload, 
                            (nuevoPayload) => { this.executeSave(nuevoPayload, revertFunc, options); }, 
                            revertFunc
                        );
                    } else {
                        console.error("CRÍTICO: No se encontró window.resolverConflictoAsignacion.");
                    }
                } else {
                    if(typeof Swal !== 'undefined') Swal.fire(t('Error'), res.error || res.message || t('Error desconocido'), 'error');
                    if (revertFunc) revertFunc();
                }
            },
            error: () => {
                if(typeof Swal !== 'undefined') Swal.fire(t('Error'), t('Fallo de red'), 'error');
                if (revertFunc) revertFunc();
            }
        });
    }

    executeVehicleSave(payload, onDone) {
        if (!payload.overwrite_mode) payload.overwrite_mode = 'check';

        $.ajax({
            url: "/api/v6/planificador/vehicle-action",
            type: "POST",
            contentType: "application/json",
            data: JSON.stringify(payload),
            success: (res) => {
                if (res.success) {
                    if (onDone) onDone(res);
                } else if (res.conflict) {
                    if (typeof Swal === 'undefined') {
                        if (onDone) onDone(res);
                        return;
                    }
                    let detailHtml = '';
                    if (res.conflict_details) {
                        detailHtml = '<ul style="text-align:left;font-size:0.85rem;">';
                        Object.keys(res.conflict_details).forEach((k) => {
                            detailHtml += `<li><b>${k}</b>: ${res.conflict_details[k].join(', ')}</li>`;
                        });
                        detailHtml += '</ul>';
                    }
                    Swal.fire({
                        title: t('Conflicto de vehículo'),
                        html: (res.message || '') + detailHtml,
                        icon: 'warning',
                        showCancelButton: true,
                        confirmButtonText: t('Sobrescribir'),
                        cancelButtonText: t('Cancelar'),
                    }).then((result) => {
                        if (result.isConfirmed) {
                            const next = Object.assign({}, payload, { overwrite_mode: 'overwrite' });
                            this.executeVehicleSave(next, onDone);
                        } else if (onDone) {
                            onDone(res);
                        }
                    });
                } else {
                    if (typeof Swal !== 'undefined') {
                        Swal.fire(t('Error'), res.error || res.message || t('Error de vehículo'), 'error');
                    }
                    if (onDone) onDone(res);
                }
            },
            error: () => {
                if (typeof Swal !== 'undefined') Swal.fire(t('Error'), t('Fallo de red (vehículo)'), 'error');
                if (onDone) onDone({ success: false });
            }
        });
    }
}

window.addEventListener('scroll', function(e) {
    const t = e.target;
    if (t && t.nodeType === 1 && typeof t.closest === 'function') {
        if (t.classList.contains('select2-results__options')) return;
        if (t.closest('.select2-dropdown, .select2-container, .univ-calendar-panel, .modal')) return;
    }
    // Con dropdown fijo no cerrar al scroll: SignaPlanSelect2 lo reposiciona.
    // Cerrar aquí hacía que el listado "no abriera" (open → scroll → close).
    if (document.querySelector('.select2-container--open')) return;
    if (typeof $ !== 'undefined' && $.fn.select2) { $('.select2-hidden-accessible').select2('close'); }
    if (typeof $ !== 'undefined') { $('.tooltip.show').remove(); }
    document.querySelectorAll('[data-tippy-root]').forEach(el => { if (el._tippy) el._tippy.hide(); });
    if (document.activeElement && document.activeElement.type === 'date') { document.activeElement.blur(); }
}, { capture: true, passive: true });
