/**
 * Módulo reutilizable: línea temporal de actividad operario + día.
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
        el.className = 'badge person-day-timeline-estado badge-secondary';

        if (value.includes('Correcto')) el.classList.add('badge-success');
        else if (value === 'Paracaidista' || value.includes('Movido')) el.classList.add('badge-warning');
        else if (value.includes('Ausencia') || value === 'Conflicto') el.classList.add('badge-danger');
        else if (value.includes('Asignado') || value.includes('RRHH') || value.includes('Actividad')) el.classList.add('badge-info');
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

        return `
            <div class="person-day-timeline-item">
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

    function renderHitosHTML(data) {
        const hitos = data.hitos || data;

        if (!hitos || !hitos.length) {
            return '<div class="person-day-timeline-empty"><i class="fas fa-ghost fa-lg mb-2 d-block"></i><p class="mb-0">Sin eventos para este día.</p></div>';
        }

        if (hitos.length === 1 && hitos[0].titulo === 'Sin actividad') {
            return '<div class="person-day-timeline-empty"><i class="fas fa-ghost fa-lg mb-2 d-block"></i><p class="mb-0">Sin eventos para este día.</p></div>';
        }

        return hitos.map(renderHitoCard).join('');
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
        content.innerHTML = `<div class="person-day-timeline-container">${renderHitosHTML(data)}</div>`;
    }

    function showLoading(container, message) {
        if (!container) return;
        const content = container.querySelector('[data-timeline-content]') || container;
        content.innerHTML = `
            <div class="text-center py-4">
                <i class="fas fa-spinner fa-spin fa-lg text-primary"></i>
                <p class="mt-2 text-muted small mb-0">${escapeHtml(message || 'Cargando historial...')}</p>
            </div>
        `;
    }

    function showError(container, message) {
        if (!container) return;
        const content = container.querySelector('[data-timeline-content]') || container;
        content.innerHTML = `<div class="alert alert-danger border-danger mb-0 small">${escapeHtml(message || 'No se pudo cargar el historial.')}</div>`;
    }

    function fetchTimeline(userId, fechaStr, apiBase) {
        const base = apiBase || DEFAULT_API;
        return fetch(`${base}/${userId}/${fechaStr}`).then(r => r.json());
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
        load,
        openModal,
        bindRowClick,
        renderInto,
        renderHitosHTML,
        applyEstadoBadge,
        showLoading,
        showError,
    };
})();
