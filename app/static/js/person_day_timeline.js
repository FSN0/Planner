/**
 * Módulo reutilizable: línea temporal de actividad operario + día / rango.
 */
window.PersonDayTimeline = (function () {
    const DEFAULT_API = '/api/v6/person-day-timeline';
    const t = window.SP_T || function (key) { return key; };

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text || '';
        return div.innerHTML;
    }

    const ACTIONABLE_ESTADOS = new Set([
        'Conflicto', 'Paracaidista', 'Ausencia', 'Pendiente', 'Retraso',
    ]);

    function auditSectionForEstado(estado) {
        const canon = canonEstado(estado);
        if (canon === 'Paracaidista') return '#collapseParacaidistas';
        if (canon === 'Ausencia') return '#collapseAusencias';
        return '#collapseConflictos';
    }

    function buildAuditoriaUrl(userId, fechaStr, estado, auditBase, registroId) {
        const base = auditBase || '/sync/auditoria';
        const params = new URLSearchParams();
        if (userId) params.set('user_id', String(userId));
        if (fechaStr) params.set('fecha', fechaStr);
        if (estado) params.set('estado', canonEstado(estado));
        const section = auditSectionForEstado(estado);
        if (section) {
            params.set('seccion', section.replace('#collapse', '').toLowerCase());
        }
        if (registroId) params.set('registro_id', String(registroId));
        return `${base}?${params.toString()}`;
    }

    function hideResolveButton(modal) {
        const btn = modal && modal.querySelector('[data-timeline-resolve-audit]');
        if (!btn) return;
        btn.classList.add('d-none');
        btn.hidden = true;
        btn.removeAttribute('href');
    }

    function updateResolveButton(modal, data, opts) {
        const btn = modal && modal.querySelector('[data-timeline-resolve-audit]');
        if (!btn) return;
        const options = opts || {};
        if (!options.canResolveAudit) {
            hideResolveButton(modal);
            return;
        }
        const estado = canonEstado(
            (data && data.estado_actual) || options.estadoHint || ''
        );
        if (!ACTIONABLE_ESTADOS.has(estado)) {
            hideResolveButton(modal);
            return;
        }
        const userId = (data && (data.target_user_id || data.user_id)) || options.userId;
        const fechaStr = (data && data.fecha_iso) || options.fechaStr;
        btn.href = buildAuditoriaUrl(
            userId,
            fechaStr,
            estado,
            options.auditUrl,
            data && data.registro_auditoria_id
        );
        btn.classList.remove('d-none');
        btn.hidden = false;
    }

    function wrapOnLoaded(opts, modal, openCtx) {
        const prev = opts && opts.onLoaded;
        return function (data) {
            updateResolveButton(modal, data, Object.assign({}, opts, openCtx));
            if (typeof prev === 'function') prev(data);
        };
    }

    function renderEmpleadoLink(name, url) {
        if (!name) return '—';
        if (!url) return escapeHtml(name);
        return `<a href="${escapeHtml(url)}" class="pdt-link pdt-link-user" target="_blank" rel="noopener">${escapeHtml(name)}</a>`;
    }

    function canonEstado(estado) {
        const raw = (estado || '').trim();
        if (!raw) return 'Sin_Registro';
        if (raw === 'Sin registro' || raw === 'Sin fichaje') return 'Sin_Registro';
        return raw;
    }

    function applyEstadoBadge(el, estado) {
        if (!el) return;
        const raw = canonEstado(estado);
        const FE = window.SPFichajeEstado;
        const value = FE && FE.labelDeEstado ? FE.labelDeEstado(raw) : t(raw.replace(/_/g, ' '));
        el.textContent = value;
        const badge = FE && FE.badgeClass ? FE.badgeClass(raw) : 'badge-soft-gray';
        el.className = 'badge-soft person-day-timeline-estado ' + badge;
    }

    function renderActor(hito) {
        const autor = hito.autor || '-';
        const isSystem = hito.actor_is_system || autor === 'Sistema Automático' || autor === 'Sistema';
        const actorClass = isSystem ? 'person-day-timeline-actor--system' : 'person-day-timeline-actor--user';

        let actorContent;
        if (hito.actor_url && !isSystem) {
            actorContent = `<a href="${escapeHtml(hito.actor_url)}" class="pdt-link pdt-actor-link" target="_blank" rel="noopener">${escapeHtml(autor)}</a>`;
        } else {
            actorContent = escapeHtml(autor);
        }

        return `<span class="person-day-timeline-actor ${actorClass}">${actorContent}</span>`;
    }

    function renderHitoCard(hito) {
        const iconClass = hito.icon_class || 'fa-circle';
        const iconColor = hito.icon_color || '#64748b';
        const descripcion = hito.descripcion_html || escapeHtml(hito.descripcion || '');
        const searchBlob = [
            hito.titulo || '',
            hito.descripcion || '',
            hito.autor || '',
            hito.fecha || '',
        ].join(' ').toLowerCase();

        return `
            <div class="person-day-timeline-item${hito.conflicto ? ' person-day-timeline-item--conflict' : ''}" data-timeline-search="${escapeHtml(searchBlob)}">
                <span class="person-day-timeline-marker" style="background:${iconColor};">
                    <i class="fas ${iconClass}" style="color:#fff;"></i>
                </span>
                <div class="person-day-timeline-card">
                    <div class="person-day-timeline-header">
                        <h6 class="person-day-timeline-title">${escapeHtml(hito.titulo || '')}</h6>
                        <span class="person-day-timeline-time">${escapeHtml(hito.fecha || '')}</span>
                    </div>
                    <p class="person-day-timeline-desc">${descripcion}</p>
                    <div class="person-day-timeline-footer">
                        ${renderActor(hito)}
                    </div>
                </div>
            </div>
        `;
    }

    function isEmptyHitos(hitos) {
        if (!hitos || !hitos.length) return true;
        return hitos.length === 1 && (
            hitos[0].empty === true
            || hitos[0].titulo === 'Sin actividad'
            || hitos[0].titulo === t('Sin actividad')
        );
    }

    function renderHitosHTML(data) {
        const hitos = data.hitos || data;

        if (isEmptyHitos(hitos)) {
            return `<div class="person-day-timeline-empty person-day-timeline-empty--compact"><i class="fas fa-ghost fa-lg mb-2 d-block"></i><p class="mb-0">${escapeHtml(t('Sin actividad'))}</p></div>`;
        }

        return hitos.map(renderHitoCard).join('');
    }

    function renderDaySection(day) {
        const raw = canonEstado(day.estado_actual || '');
        const FE = window.SPFichajeEstado;
        const badge = FE && FE.badgeClass ? FE.badgeClass(raw) : 'badge-soft-gray';
        const estadoLabel = FE && FE.labelDeEstado ? FE.labelDeEstado(raw) : t(raw.replace(/_/g, ' '));

        return `
            <section class="person-day-timeline-day" data-fecha-iso="${escapeHtml(day.fecha_iso || '')}">
                <header class="person-day-timeline-day-header">
                    <span class="person-day-timeline-day-date">
                        <i class="fas fa-calendar-day mr-1"></i>${escapeHtml(day.fecha || '')}
                    </span>
                    <span class="badge-soft person-day-timeline-estado ${badge}">${escapeHtml(estadoLabel || '—')}</span>
                </header>
                <div class="person-day-timeline-day-body">
                    ${renderHitosHTML(day)}
                </div>
            </section>
        `;
    }

    function renderDaysHTML(days) {
        if (!days || !days.length) {
            return `<div class="person-day-timeline-empty"><i class="fas fa-ghost fa-lg mb-2 d-block"></i><p class="mb-0">${escapeHtml(t('Sin eventos en el periodo.'))}</p></div>`;
        }
        return days.map(renderDaySection).join('');
    }

    function setEmpleadoElement(el, data) {
        if (!el) return;
        el.innerHTML = renderEmpleadoLink(data.empleado, data.empleado_url);
    }

    function renderInto(container, data) {
        if (!container) return;

        const modal = container.closest('.modal');
        if (modal) {
            const titleEmpleado = modal.querySelector('.modal-title [data-timeline-empleado]');
            setEmpleadoElement(titleEmpleado, data);
        }

        const meta = container.querySelector('[data-timeline-meta]');
        if (meta) {
            const empleadoEl = meta.querySelector('[data-timeline-empleado]');
            const fechaEl = meta.querySelector('[data-timeline-fecha]');
            const estadoEl = meta.querySelector('[data-timeline-estado]');
            setEmpleadoElement(empleadoEl, data);
            if (fechaEl) fechaEl.textContent = data.fecha || '';
            if (estadoEl) {
                const wrap = estadoEl.closest('.person-day-timeline-meta-item');
                const multiDay = !!(data.days && data.days.length > 1);
                if (wrap) wrap.hidden = multiDay;
                if (!multiDay) applyEstadoBadge(estadoEl, data.estado_actual);
            }
        }

        const content = container.querySelector('[data-timeline-content]') || container;
        let bodyHtml;
        if (data.days && data.days.length) {
            bodyHtml = `<div class="person-day-timeline-container person-day-timeline-container--range">${renderDaysHTML(data.days)}</div>`;
        } else {
            bodyHtml = `<div class="person-day-timeline-container">${renderHitosHTML(data)}</div>`;
        }
        content.innerHTML = bodyHtml;
    }

    function showLoading(container, message) {
        if (!container) return;
        const content = container.querySelector('[data-timeline-content]') || container;
        content.innerHTML = `
            <div class="person-day-timeline-loading">
                <i class="fas fa-spinner fa-spin fa-lg"></i>
                <p class="mt-2 small mb-0">${escapeHtml(message || t('Cargando historial...'))}</p>
            </div>
        `;
    }

    function showError(container, message) {
        if (!container) return;
        const content = container.querySelector('[data-timeline-content]') || container;
        content.innerHTML = `<div class="person-day-timeline-error">${escapeHtml(message || t('No se pudo cargar el historial.'))}</div>`;
    }

    function fetchTimeline(userId, fechaStr, apiBase) {
        const base = apiBase || DEFAULT_API;
        return fetch(`${base}/${userId}/${fechaStr}`).then(r => r.json());
    }

    function fetchTimelineRange(userId, fromStr, toStr, apiBase) {
        const base = apiBase || DEFAULT_API;
        const params = new URLSearchParams();
        if (fromStr) params.set('from', fromStr);
        if (toStr) params.set('to', toStr);
        return fetch(`${base}/${userId}?${params.toString()}`).then(r => r.json());
    }

    function load(container, userId, fechaStr, options) {
        const opts = options || {};
        showLoading(container, opts.loadingMessage);

        return fetchTimeline(userId, fechaStr, opts.apiBase)
            .then(data => {
                if (!data.success) {
                    showError(container, data.error || t('No se pudo cargar el historial.'));
                    return data;
                }
                renderInto(container, data);
                if (typeof opts.onLoaded === 'function') opts.onLoaded(data);
                return data;
            })
            .catch(() => {
                showError(container, t('Error de conexión al servidor.'));
                return { success: false };
            });
    }

    function loadRange(container, userId, fromStr, toStr, options) {
        const opts = options || {};
        showLoading(container, opts.loadingMessage);

        return fetchTimelineRange(userId, fromStr, toStr, opts.apiBase)
            .then(data => {
                if (!data.success) {
                    showError(container, data.error || t('No se pudo cargar el historial.'));
                    return data;
                }
                renderInto(container, data);
                if (typeof opts.onLoaded === 'function') opts.onLoaded(data);
                return data;
            })
            .catch(() => {
                showError(container, t('Error de conexión al servidor.'));
                return { success: false };
            });
    }

    function applyTextFilter(container, query) {
        if (!container) return;
        const q = (query || '').trim().toLowerCase();
        const days = container.querySelectorAll('.person-day-timeline-day');
        const items = container.querySelectorAll('.person-day-timeline-item');

        if (!q) {
            items.forEach(el => { el.hidden = false; });
            days.forEach(day => {
                day.hidden = false;
                const empty = day.querySelector('.person-day-timeline-empty');
                if (empty) empty.hidden = false;
                const noMatch = day.querySelector('.person-day-timeline-filter-empty');
                if (noMatch) noMatch.remove();
            });
            return;
        }

        items.forEach(el => {
            const blob = (el.getAttribute('data-timeline-search') || '').toLowerCase();
            el.hidden = !blob.includes(q);
        });

        days.forEach(day => {
            const dayItems = day.querySelectorAll('.person-day-timeline-item');
            const visible = Array.from(dayItems).some(el => !el.hidden);
            const hasItems = dayItems.length > 0;
            day.hidden = hasItems ? !visible : true;

            let noMatch = day.querySelector('.person-day-timeline-filter-empty');
            if (hasItems && !visible) {
                day.hidden = false;
                if (!noMatch) {
                    noMatch = document.createElement('div');
                    noMatch.className = 'person-day-timeline-empty person-day-timeline-empty--compact person-day-timeline-filter-empty';
                    noMatch.innerHTML = '<p class="mb-0">' + escapeHtml(t('Sin coincidencias en este día.')) + '</p>';
                    const body = day.querySelector('.person-day-timeline-day-body');
                    if (body) body.appendChild(noMatch);
                }
            } else if (noMatch) {
                noMatch.remove();
            }

            const empty = day.querySelector('.person-day-timeline-empty:not(.person-day-timeline-filter-empty)');
            if (empty) empty.hidden = !!q;
        });
    }

    function openModal(userId, fechaStr, options) {
        const opts = options || {};
        const modalId = opts.modalId || 'modalPersonDayTimeline';
        const modal = document.getElementById(modalId);
        if (!modal) {
            console.error('PersonDayTimeline: modal no encontrado:', modalId);
            return Promise.resolve({ success: false });
        }

        const body = modal.querySelector('[data-person-day-timeline-root]');
        hideResolveButton(modal);
        showLoading(body, opts.loadingMessage);

        if (typeof $ !== 'undefined' && $.fn.modal) {
            $(modal).modal('show');
        } else {
            modal.classList.add('show');
            modal.style.display = 'block';
        }

        const openCtx = {
            userId: userId,
            fechaStr: fechaStr,
            estadoHint: opts.estadoHint || '',
        };
        return load(body, userId, fechaStr, Object.assign({}, opts, {
            onLoaded: wrapOnLoaded(opts, modal, openCtx),
        }));
    }

    function bindFichajeDotClick(containerSelector, options) {
        const root = document.querySelector(containerSelector);
        if (!root) return;

        function openFromDot(dot) {
            const userId = dot.getAttribute('data-user-id');
            let fechaStr = dot.getAttribute('data-fecha');
            if (!fechaStr) {
                const dateInput = document.getElementById('timeline-selected-date');
                fechaStr = dateInput ? dateInput.value : '';
            }
            if (!userId || !fechaStr) return;
            openModal(userId, fechaStr, Object.assign({}, options || {}, {
                estadoHint: dot.getAttribute('data-estado-fichaje') || '',
            }));
        }

        root.addEventListener('mousedown', function (e) {
            const dot = e.target.closest('[data-fichaje-dot]');
            if (dot) e.stopPropagation();
        });

        root.addEventListener('click', function (e) {
            const dot = e.target.closest('[data-fichaje-dot]');
            if (!dot) return;
            e.preventDefault();
            e.stopPropagation();
            openFromDot(dot);
        });

        root.addEventListener('keydown', function (e) {
            if (e.key !== 'Enter' && e.key !== ' ') return;
            const dot = e.target.closest('[data-fichaje-dot]');
            if (!dot) return;
            e.preventDefault();
            e.stopPropagation();
            openFromDot(dot);
        });
    }

    function bindKanbanDotClick(containerSelector, options) {
        bindFichajeDotClick(containerSelector, options);
    }

    function bindRowClick(selector, options) {
        const opts = options || {};
        document.querySelectorAll(selector).forEach(row => {
            row.addEventListener('click', function (e) {
                if (opts.ignoreButtonClick !== false) {
                    if (e.target.tagName === 'BUTTON' || e.target.closest('button')) return;
                    if (e.target.tagName === 'A' || e.target.closest('a')) return;
                }

                const userId = this.getAttribute('data-user-id') || this.dataset.userId;
                const fechaStr = this.getAttribute('data-fecha') || this.dataset.fecha;
                if (!userId || !fechaStr) return;

                openModal(userId, fechaStr, opts);
            });
        });
    }

    return {
        fetchTimeline,
        fetchTimelineRange,
        load,
        loadRange,
        openModal,
        bindRowClick,
        bindKanbanDotClick,
        bindFichajeDotClick,
        buildAuditoriaUrl,
        renderInto,
        renderHitosHTML,
        applyEstadoBadge,
        applyTextFilter,
        showLoading,
        showError,
    };
})();
