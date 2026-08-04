/**
 * Módulo reutilizable: línea temporal de actividad operario + día / rango.
 */
window.PersonDayTimeline = (function () {
    const DEFAULT_API = '/api/v6/person-day-timeline';

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text || '';
        return div.innerHTML;
    }

    function renderEmpleadoLink(name, url) {
        if (!name) return '—';
        if (!url) return escapeHtml(name);
        return `<a href="${escapeHtml(url)}" class="pdt-link pdt-link-user" target="_blank" rel="noopener">${escapeHtml(name)}</a>`;
    }

    function applyEstadoBadge(el, estado) {
        if (!el) return;
        const value = (estado || 'Sin registro').replace(/_/g, ' ');
        el.textContent = value;
        el.className = 'badge-soft person-day-timeline-estado badge-soft-gray';
        if (value.includes('Correcto') || value.startsWith('Resuelto')) el.className = 'badge-soft person-day-timeline-estado badge-soft-green';
        else if (value === 'Paracaidista' || value === 'Conflicto') el.className = 'badge-soft person-day-timeline-estado badge-soft-amber';
        else if (value.includes('Ausencia') || value === 'Conflicto') el.className = 'badge-soft person-day-timeline-estado badge-soft-red';
        else if (value.includes('Asignado') || value.includes('RRHH') || value.includes('Actividad') || value.includes('día')) {
            el.className = 'badge-soft person-day-timeline-estado badge-soft-blue';
        }
    }

    function renderActor(hito) {
        const autor = hito.autor || '-';
        const isSystem = autor === 'Sistema Automático' || autor === 'Sistema';
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
            <div class="person-day-timeline-item" data-timeline-search="${escapeHtml(searchBlob)}">
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
        return hitos.length === 1 && hitos[0].titulo === 'Sin actividad';
    }

    function renderHitosHTML(data) {
        const hitos = data.hitos || data;

        if (isEmptyHitos(hitos)) {
            return '<div class="person-day-timeline-empty person-day-timeline-empty--compact"><i class="fas fa-ghost fa-lg mb-2 d-block"></i><p class="mb-0">Sin actividad</p></div>';
        }

        return hitos.map(renderHitoCard).join('');
    }

    function renderDaySection(day) {
        const estado = (day.estado_actual || '').replace(/_/g, ' ');
        let estadoClass = 'badge-soft person-day-timeline-estado badge-soft-gray';
        if (estado.includes('Correcto') || estado.startsWith('Resuelto')) estadoClass = 'badge-soft person-day-timeline-estado badge-soft-green';
        else if (estado === 'Paracaidista' || estado === 'Conflicto') estadoClass = 'badge-soft person-day-timeline-estado badge-soft-amber';
        else if (estado.includes('Ausencia') || estado === 'Conflicto') estadoClass = 'badge-soft person-day-timeline-estado badge-soft-red';
        else if (estado.includes('Asignado') || estado.includes('RRHH') || estado.includes('Actividad')) {
            estadoClass = 'badge-soft person-day-timeline-estado badge-soft-blue';
        }

        return `
            <section class="person-day-timeline-day" data-fecha-iso="${escapeHtml(day.fecha_iso || '')}">
                <header class="person-day-timeline-day-header">
                    <span class="person-day-timeline-day-date">
                        <i class="fas fa-calendar-day mr-1"></i>${escapeHtml(day.fecha || '')}
                    </span>
                    <span class="${estadoClass}">${escapeHtml(estado || '—')}</span>
                </header>
                <div class="person-day-timeline-day-body">
                    ${renderHitosHTML(day)}
                </div>
            </section>
        `;
    }

    function renderDaysHTML(days) {
        if (!days || !days.length) {
            return '<div class="person-day-timeline-empty"><i class="fas fa-ghost fa-lg mb-2 d-block"></i><p class="mb-0">Sin eventos en el periodo.</p></div>';
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
            applyEstadoBadge(estadoEl, data.estado_actual);
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
                <p class="mt-2 small mb-0">${escapeHtml(message || 'Cargando historial...')}</p>
            </div>
        `;
    }

    function showError(container, message) {
        if (!container) return;
        const content = container.querySelector('[data-timeline-content]') || container;
        content.innerHTML = `<div class="person-day-timeline-error">${escapeHtml(message || 'No se pudo cargar el historial.')}</div>`;
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
                    showError(container, data.error || 'No se pudo cargar el historial.');
                    return data;
                }
                renderInto(container, data);
                if (typeof opts.onLoaded === 'function') opts.onLoaded(data);
                return data;
            })
            .catch(() => {
                showError(container, 'Error de conexión al servidor.');
                return { success: false };
            });
    }

    function loadRange(container, userId, fromStr, toStr, options) {
        const opts = options || {};
        showLoading(container, opts.loadingMessage);

        return fetchTimelineRange(userId, fromStr, toStr, opts.apiBase)
            .then(data => {
                if (!data.success) {
                    showError(container, data.error || 'No se pudo cargar el historial.');
                    return data;
                }
                renderInto(container, data);
                if (typeof opts.onLoaded === 'function') opts.onLoaded(data);
                return data;
            })
            .catch(() => {
                showError(container, 'Error de conexión al servidor.');
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
                    noMatch.innerHTML = '<p class="mb-0">Sin coincidencias en este día.</p>';
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
        showLoading(body, opts.loadingMessage);

        if (typeof $ !== 'undefined' && $.fn.modal) {
            $(modal).modal('show');
        } else {
            modal.classList.add('show');
            modal.style.display = 'block';
        }

        return load(body, userId, fechaStr, opts);
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
        renderInto,
        renderHitosHTML,
        applyEstadoBadge,
        applyTextFilter,
        showLoading,
        showError,
    };
})();
