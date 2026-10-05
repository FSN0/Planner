document.addEventListener('DOMContentLoaded', function() {
    const t = window.SP_T || function (key) { return key; };
    
    window.hiddenGroups = new Set();
    window.allGroupsMaster = [];
    window.allEventsMaster = [];
    /** Estado confirmado en BD (solo se actualiza tras loadTimelineData). Evita que onMoving contamine old_obra_id. */
    window.committedEventState = {};
    window.currentSidebarWidth = 250;
    
    window.AppGroups = new vis.DataSet();
    window.AppItems = new vis.DataSet();
    window.currentSelectedItem = null; // <-- NUEVO: Para guardar qué trabajador hemos pinchado
    window.planificadorHideInercia = !(window.SPInerciaPref
        ? window.SPInerciaPref.get('planificador', true)
        : true);

    function syncPlanificadorInerciaBtn() {
        var btn = document.getElementById('btnToggleInerciaPlanif');
        if (!btn) return;
        var showing = !window.planificadorHideInercia;
        btn.classList.toggle('is-on', showing);
        btn.setAttribute('aria-pressed', showing ? 'true' : 'false');
        var label = showing ? t('Ocultar inercia') : t('Mostrar inercia');
        btn.setAttribute('title', label);
    }
    var btnInerciaPlanif = document.getElementById('btnToggleInerciaPlanif');
    if (btnInerciaPlanif) {
        btnInerciaPlanif.addEventListener('click', function () {
            window.planificadorHideInercia = !window.planificadorHideInercia;
            if (window.SPInerciaPref) {
                window.SPInerciaPref.set('planificador', !window.planificadorHideInercia);
            }
            syncPlanificadorInerciaBtn();
            var loaded = window._planifLoaded;
            if (window.planificadorHideInercia) {
                if (typeof window.renderItems === 'function') window.renderItems();
            } else if (loaded && !loaded.inercia && typeof window.loadTimelineData === 'function') {
                window.loadTimelineData();
            } else if (typeof window.renderItems === 'function') {
                window.renderItems();
            }
        });
        syncPlanificadorInerciaBtn();
    }

    window.toggleEye = function(groupId) {
        let idStr = String(groupId);
        if (window.hiddenGroups.has(idStr)) window.hiddenGroups.delete(idStr);
        else window.hiddenGroups.add(idStr);
        
        let g = window.allGroupsMaster.find(x => String(x.id) === idStr);
        if (g && window.AppGroups) {
            window.AppGroups.update({ id: g.id, _refresh: Date.now() }); 
        }
        window.renderItems();
    };

    function hidePlanificadorOverlays() {
        var popover = document.getElementById('worker-popover');
        if (popover) popover.classList.add('d-none');
        var tip = document.getElementById('planificador-item-tooltip');
        if (tip) {
            tip.classList.add('d-none');
            tip.setAttribute('aria-hidden', 'true');
        }
    }

    function isPlanificadorGhost(item) {
        if (!item) return false;
        if (item.isGhost) return true;
        return String(item.id || '').indexOf('ghost_') === 0;
    }

    function isPlanificadorInercia(item) {
        if (!item) return false;
        if (item.inercia) return true;
        return String(item.className || '').indexOf('inercia-item') !== -1;
    }

    function isCopyablePlanifItem(item) {
        if (!item || item.type === 'background') return false;
        if (isPlanificadorGhost(item)) return false;
        var w = String(item.worker_id == null ? '' : item.worker_id);
        if (!w || w === 'SYSTEM' || w === 'REQUEST' || w === 'NEW' || w === 'GENERICO') return false;
        return true;
    }

    function collectPlanifGhosts() {
        if (!window.AppItems) return [];
        return window.AppItems.get({
            filter: function (i) { return isPlanificadorGhost(i); },
        }) || [];
    }

    function fitPlanificadorTimelineToGroups() {
        var last = document.querySelector('#planificador-calendar .vis-labelset .vis-label:last-child');
        var timeline = document.querySelector('#planificador-calendar .vis-timeline');
        if (!timeline) return;
        var page = document.querySelector('.planificador-page');
        var top = timeline.getBoundingClientRect().top;
        var fill = 200;
        if (page && timeline) {
            var pageRect = page.getBoundingClientRect();
            var calTopInPage = timeline.getBoundingClientRect().top - pageRect.top + page.scrollTop;
            fill = Math.floor(page.clientHeight - calTopInPage - 2);
        }
        var content = 160;
        if (last) {
            content = Math.ceil(last.getBoundingClientRect().bottom - top + 10);
        }
        var needed = Math.max(content, fill, 200);
        var current = Math.round(timeline.getBoundingClientRect().height);
        if (Math.abs(current - needed) <= 2) return;
        timeline.style.height = needed + 'px';
    }

    function tuckAddObraIntoTimelineGap() {
        var btn = document.querySelector('.planificador-add-obra');
        if (!btn) return;
        btn.style.marginTop = '';
        var leftW = window.currentSidebarWidth || 250;
        btn.style.width = leftW + 'px';
    }

    function refreshPlanificadorLayout() {
        if (window.AppTimeline) {
            window.AppTimeline.redraw();
        }
        fitPlanificadorTimelineToGroups();
        tuckAddObraIntoTimelineGap();
        updateStickyHeader();
        updateResizerPosition();
    }

    var planifLaneTimer = null;

    function planifIsPackableWorker(wid) {
        var w = String(wid == null ? '' : wid);
        return !!(w && w !== 'SYSTEM' && w !== 'REQUEST' && w !== 'NEW' && w !== 'GENERICO');
    }

    function planifIsRequestItem(it) {
        if (!it) return false;
        if (it.solicitud_id) return true;
        return String(it.worker_id) === 'REQUEST';
    }

    function planifMs(v) {
        var t = new Date(v).getTime();
        return isFinite(t) ? t : 0;
    }

    function planifRangesOverlap(a0, a1, b0, b1) {
        return a0 < b1 && b0 < a1;
    }

    function planifMergeIntervals(intervals) {
        if (!intervals.length) return [];
        intervals.sort(function (a, b) { return a.start - b.start; });
        var out = [{ start: intervals[0].start, end: intervals[0].end }];
        for (var i = 1; i < intervals.length; i++) {
            var last = out[out.length - 1];
            if (intervals[i].start <= last.end) {
                if (intervals[i].end > last.end) last.end = intervals[i].end;
            } else {
                out.push({ start: intervals[i].start, end: intervals[i].end });
            }
        }
        return out;
    }

    function planifWorkerHitsLane(worker, laneWorkers) {
        for (var i = 0; i < laneWorkers.length; i++) {
            var iv = laneWorkers[i].intervals;
            for (var x = 0; x < worker.intervals.length; x++) {
                for (var y = 0; y < iv.length; y++) {
                    if (planifRangesOverlap(worker.intervals[x].start, worker.intervals[x].end, iv[y].start, iv[y].end)) {
                        return true;
                    }
                }
            }
        }
        return false;
    }

    function planifAssignLanes(workers) {
        workers.sort(function (a, b) {
            var as = a.intervals.length ? a.intervals[0].start : 0;
            var bs = b.intervals.length ? b.intervals[0].start : 0;
            if (as !== bs) return as - bs;
            return a.order.localeCompare(b.order);
        });
        var lanes = [];
        workers.forEach(function (w) {
            var lane = -1;
            for (var i = 0; i < lanes.length; i++) {
                if (!planifWorkerHitsLane(w, lanes[i])) {
                    lane = i;
                    break;
                }
            }
            if (lane < 0) {
                lane = lanes.length;
                lanes.push([]);
            }
            lanes[lane].push(w);
            w.lane = lane;
        });
    }

    function planifVisibleRangeMs() {
        if (!window.AppTimeline || typeof window.AppTimeline.getWindow !== 'function') return null;
        try {
            var w = window.AppTimeline.getWindow();
            return { start: +new Date(w.start), end: +new Date(w.end) };
        } catch (errW) {
            return null;
        }
    }

    function planifRelayoutLanes() {
        if (!window.AppItems) return;
        var items = window.AppItems.get() || [];
        var byGroup = {};
        var requestLaneByGroup = {};
        items.forEach(function (it) {
            if (!it || it.type === 'background') return;
            if (it.group != null && planifIsRequestItem(it)) {
                // Carril de solicitudes siempre arriba (aunque aún no haya operarios).
                requestLaneByGroup[String(it.group)] = -1;
            }
            if (!planifIsPackableWorker(it.worker_id) || it.group == null) return;
            var gid = String(it.group);
            var key = String(it.worker_id);
            if (!byGroup[gid]) byGroup[gid] = {};
            if (!byGroup[gid][key]) {
                byGroup[gid][key] = {
                    key: key,
                    order: (it.empresa_nombre || 'ZZ_Sin_Empresa') + '\t' + (it.title || '') + '\t' + key,
                };
            }
        });

        // Un subgrupo estable por operario (W{id}): hecho + fantasma comparten
        // siempre la misma altura. No empaquetar por huecos temporales.
        var orderByGroupWorker = {};
        Object.keys(byGroup).forEach(function (gid) {
            var list = Object.keys(byGroup[gid]).map(function (k) {
                return byGroup[gid][k];
            });
            list.sort(function (a, b) {
                return a.order.localeCompare(b.order);
            });
            var map = {};
            list.forEach(function (w, idx) {
                map[w.key] = idx;
            });
            orderByGroupWorker[gid] = map;
        });

        var updates = [];
        items.forEach(function (it) {
            if (!it || it.type === 'background' || it.id == null) return;
            if (planifIsRequestItem(it)) {
                var reqLane = requestLaneByGroup[String(it.group)];
                if (reqLane == null) reqLane = -1;
                if (it.subgroup !== 'R' || it.subgroupOrder !== reqLane) {
                    updates.push({ id: it.id, subgroup: 'R', subgroupOrder: reqLane });
                }
                return;
            }
            // Borrador «Nueva asignación» / phantom: debajo de solicitud y operarios.
            // Si no, Vis lo mete en el carril de arriba y tapa la solicitud naranja.
            var isDraftNew = String(it.worker_id) === 'NEW' || (
                isPlanificadorGhost(it) && !planifIsPackableWorker(it.worker_id)
            );
            if (isDraftNew) {
                var workerMap = orderByGroupWorker[String(it.group)] || {};
                var draftOrd = 0;
                Object.keys(workerMap).forEach(function (k) {
                    if (workerMap[k] >= draftOrd) draftOrd = workerMap[k] + 1;
                });
                if (it.subgroup !== 'N' || it.subgroupOrder !== draftOrd) {
                    updates.push({ id: it.id, subgroup: 'N', subgroupOrder: draftOrd });
                }
                return;
            }
            if (!planifIsPackableWorker(it.worker_id)) {
                if (it.subgroup != null) {
                    updates.push({ id: it.id, subgroup: null, subgroupOrder: 0 });
                }
                return;
            }
            var map = orderByGroupWorker[String(it.group)] || {};
            var wid = String(it.worker_id);
            var ord = map[wid];
            if (ord == null) ord = 0;
            var sg = 'W' + wid;
            if (it.subgroup !== sg || it.subgroupOrder !== ord) {
                updates.push({ id: it.id, subgroup: sg, subgroupOrder: ord });
            }
        });
        if (updates.length) window.AppItems.update(updates);
        // Cinturón: tras el stack de vis, forzar misma altura hecho+fantasma.
        planifAlignSameWorkerTops();
    }

    function planifAlignSameWorkerTops() {
        var itemSet = window.AppTimeline && window.AppTimeline.itemSet;
        if (!itemSet || !itemSet.groups) return;
        var groupMap = itemSet.groups;
        Object.keys(groupMap).forEach(function (gid) {
            var g = groupMap[gid];
            if (!g || !g.items) return;
            var byWorker = {};
            Object.keys(g.items).forEach(function (iid) {
                var vi = g.items[iid];
                if (!vi || !vi.data || vi.data.type === 'background') return;
                if (!planifIsPackableWorker(vi.data.worker_id)) return;
                if (typeof vi.top !== 'number') return;
                var key = String(vi.data.worker_id);
                if (!byWorker[key]) byWorker[key] = [];
                byWorker[key].push(vi);
            });
            Object.keys(byWorker).forEach(function (wid) {
                var list = byWorker[wid];
                if (list.length < 2) return;
                var top = list[0].top;
                for (var i = 1; i < list.length; i++) {
                    if (list[i].top < top) top = list[i].top;
                }
                list.forEach(function (vi) {
                    if (vi.top === top) return;
                    vi.top = top;
                    if (typeof vi.repositionY === 'function') {
                        try { vi.repositionY(); } catch (errY) { /* ignore */ }
                    } else if (vi.dom && vi.dom.box) {
                        vi.dom.box.style.top = top + 'px';
                    }
                });
            });
        });
    }

    function planifScheduleLaneLayout() {
        if (planifLaneTimer) clearTimeout(planifLaneTimer);
        planifLaneTimer = setTimeout(function () {
            planifRelayoutLanes();
            // Tras cambiar subgroups, Vis tiene que recalcular alturas de fila
            // (si no, la asignación queda recortada debajo de la FALTA).
            if (window.AppTimeline && typeof window.AppTimeline.redraw === 'function') {
                try { window.AppTimeline.redraw(); } catch (errR) { /* ignore */ }
            }
            planifEnsureRequestLaneSpace();
            fitPlanificadorTimelineToGroups();
            if (planifViewPin) planifRestoreViewPin();
        }, 200);
    }

    function planifEnsureRequestLaneSpace() {
        // Cada obra con solicitud + operarios necesita al menos 2 carriles visibles.
        if (!window.AppItems || !window.AppTimeline) return;
        var items = window.AppItems.get() || [];
        var byGroup = {};
        items.forEach(function (it) {
            if (!it || it.type === 'background' || it.group == null) return;
            var g = String(it.group);
            if (!byGroup[g]) byGroup[g] = { req: false, workers: 0 };
            if (planifIsRequestItem(it)) byGroup[g].req = true;
            else if (planifIsPackableWorker(it.worker_id)) byGroup[g].workers += 1;
        });
        var itemSet = window.AppTimeline.itemSet;
        if (!itemSet || !itemSet.groups) return;
        Object.keys(byGroup).forEach(function (gid) {
            var info = byGroup[gid];
            if (!info.req) return;
            // 1 carril solicitud (≈22) + N operarios (≈20 c/u) + margen
            var need = 26 + Math.max(1, info.workers || 1) * 22;
            var g = itemSet.groups[gid];
            if (!g) return;
            if (typeof g.setHeight === 'function') {
                try {
                    var cur = (typeof g.height === 'number') ? g.height : 0;
                    if (cur < need) g.setHeight(need);
                } catch (errH) { /* ignore */ }
            }
            if (g.dom && g.dom.foreground) {
                g.dom.foreground.style.minHeight = need + 'px';
            }
            if (g.dom && g.dom.label) {
                g.dom.label.style.minHeight = need + 'px';
            }
        });
    }

    window.renderItems = function() {
        let visible = window.allEventsMaster.filter(function (ev) {
            if (window.hiddenGroups.has(String(ev.group))) return false;
            if (ev.inercia && window.planificadorHideInercia) return false;
            return true;
        });
        if (window.AppItems) {
            var extras = window.AppItems.get({
                filter: function (i) {
                    return i && (isPlanificadorGhost(i) || i.worker_id === 'NEW');
                },
            }) || [];
            var selectedIds = [];
            try {
                if (window.AppTimeline && typeof window.AppTimeline.getSelection === 'function') {
                    selectedIds = window.AppTimeline.getSelection() || [];
                }
            } catch (errSel) { selectedIds = []; }
            window.AppItems.clear();
            window.AppItems.add(visible);
            if (extras.length) window.AppItems.add(extras);
            planifRelayoutLanes();
            if (selectedIds.length && window.AppTimeline && typeof window.AppTimeline.setSelection === 'function') {
                setTimeout(function () {
                    try { window.AppTimeline.setSelection(selectedIds); } catch (errRest) { /* ignore */ }
                }, 0);
            }
        }
        setTimeout(refreshPlanificadorLayout, 50);
        var mobileDay = document.getElementById('planificador-mobile-day');
        if (mobileDay && mobileDay.offsetParent !== null &&
            typeof window.renderPlanificadorMobileDay === 'function') {
            window.renderPlanificadorMobileDay();
        }
    };

    function pmdEsc(s) {
        return String(s || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function pmdObraLabel(g) {
        var codigo = String((g && g.codigo) || '').trim();
        var nombre = String((g && g.title) || '').trim();
        if (codigo && nombre && nombre !== codigo) return codigo + ' / ' + nombre;
        return nombre || codigo || String((g && g.id) || '');
    }

    function pmdShift(days) {
        var input = document.getElementById('pmd-date');
        if (!input || typeof moment === 'undefined') return;
        var d = moment(input.value || undefined);
        d.add(days, 'days');
        input.value = d.format('YYYY-MM-DD');
        window.renderPlanificadorMobileDay();
    }

    function pmdFichajeDotHtml(workerId, fechaIso, estado) {
        if (!window.PLANIFICADOR_SHOW_FICHAJES || !workerId || !fechaIso) return '';
        var st = estado || 'Sin_Registro';
        var fe = window.SPFichajeEstado;
        var color = fe ? fe.colorDeEstado(st) : '#94a3b8';
        var label = fe ? fe.labelDeEstado(st) : st;
        var hint = t('Clic para ver el historial del día');
        return '<span class="pmd-fichaje-dot status-dot-kanban status-dot-kanban--interactive" ' +
            'data-fichaje-dot="1" data-user-id="' + pmdEsc(String(workerId)) + '" ' +
            'data-fecha="' + pmdEsc(fechaIso) + '" data-estado-fichaje="' + pmdEsc(st) + '" ' +
            'style="background:' + color + ';" role="button" tabindex="0" ' +
            'title="' + pmdEsc(label + ' — ' + hint) + '" ' +
            'aria-label="' + pmdEsc(label + ' — ' + hint) + '"></span>';
    }

    function fetchPmdFichajes(fechaIso) {
        if (!window.PLANIFICADOR_SHOW_FICHAJES) return Promise.resolve({});
        return fetch('/admin/api/planificador/fichajes-estado?fecha=' + encodeURIComponent(fechaIso))
            .then(function (r) { return r.json(); })
            .then(function (data) { return (data && data.estados) || {}; })
            .catch(function () { return {}; });
    }

    window.renderPlanificadorMobileDay = function() {
        var list = document.getElementById('pmd-list');
        var input = document.getElementById('pmd-date');
        if (!list || typeof moment === 'undefined') return;
        if (input && !input.value) input.value = moment().format('YYYY-MM-DD');
        var day = moment((input && input.value) || undefined).startOf('day');
        var dayEnd = day.clone().add(1, 'day');
        var fechaIso = day.format('YYYY-MM-DD');
        var events = window.allEventsMaster || [];
        var groups = window.allGroupsMaster || [];

        var byGroup = {};
        events.forEach(function (ev) {
            if (!ev || ev.type === 'background') return;
            var start = moment(ev.start);
            var end = moment(ev.end);
            if (!start.isValid() || !end.isValid()) return;
            if (!start.isBefore(dayEnd) || !end.isAfter(day)) return;
            var gid = String(ev.group || ev.resourceId || '');
            if (!gid) return;
            if (!byGroup[gid]) byGroup[gid] = [];
            byGroup[gid].push(ev);
        });

        if (!groups.length) {
            list.innerHTML = '<p class="pmd-empty">' + t('Nadie asignado este día con los filtros actuales.') + '</p>';
            return;
        }

        fetchPmdFichajes(fechaIso).then(function (estados) {
            window.planificadorFichajeEstado = estados;

            var sortedGroups = groups.slice().sort(function (a, b) {
                var aCount = (byGroup[String(a.id)] || []).length;
                var bCount = (byGroup[String(b.id)] || []).length;
                if (aCount > 0 && bCount === 0) return -1;
                if (aCount === 0 && bCount > 0) return 1;
                if (aCount !== bCount) return bCount - aCount;
                var ta = pmdObraLabel(a);
                var tb = pmdObraLabel(b);
                return ta.localeCompare(tb);
            });

            list.innerHTML = sortedGroups.map(function (g) {
                var gid = String(g.id);
                var evs = byGroup[gid] || [];
                var people = evs.map(function (ev) {
                    var name = ev.title || ('#' + (ev.worker_id || ''));
                    var ds = moment(ev.start).format('DD/MM');
                    var de = moment(ev.end).subtract(1, 'day');
                    if (!de.isValid() || de.isBefore(moment(ev.start), 'day')) de = moment(ev.start);
                    var dates = ds === de.format('DD/MM') ? ds : (ds + ' – ' + de.format('DD/MM'));
                    var body = ev.worker_id
                        ? '<a href="/admin/worker_panel/' + encodeURIComponent(ev.worker_id) + '">' + pmdEsc(name) + '</a>'
                        : pmdEsc(name);
                    var wid = ev.worker_id ? String(ev.worker_id) : '';
                    var estado = wid ? (estados[wid] || 'Sin_Registro') : '';
                    var dot = pmdFichajeDotHtml(wid, fechaIso, estado);
                    return '<div class="pmd-person"><span class="pmd-person-name">' + body +
                        '</span><span class="pmd-person-meta">' + dot +
                        '<span class="pmd-person-dates">' + pmdEsc(dates) + '</span></span></div>';
                }).join('');
                var obraHref = '/admin/obra_panel/' + encodeURIComponent(gid);
                var obraTitle = pmdEsc(pmdObraLabel(g));
                var assignBtn = '';
                if (window.PLANIFICADOR_CAN_EDIT) {
                    assignBtn = '<button type="button" class="pmd-btn-assign" data-obra-id="' + pmdEsc(gid) +
                        '" data-obra-name="' + obraTitle + '" title="' + pmdEsc(t('Asignar operario')) +
                        '" aria-label="' + pmdEsc(t('Asignar operario')) + '"><i class="fas fa-plus"></i></button>';
                }
                var emptyNote = evs.length ? '' : '<p class="pmd-empty-inline">' + t('Nadie asignado este día.') + '</p>';
                return '<article class="pmd-obra' + (evs.length ? '' : ' pmd-obra--empty') + '"><div class="pmd-obra-title"><a href="' +
                    obraHref + '">' + obraTitle + '</a><span class="pmd-obra-title-actions">' +
                    '<span class="pmd-obra-count">' + evs.length + '</span>' + assignBtn + '</span></div>' +
                    (people || emptyNote) + '</article>';
            }).join('');
        });
    };

    (function bindPmd() {
        var input = document.getElementById('pmd-date');
        var prev = document.getElementById('pmd-prev');
        var next = document.getElementById('pmd-next');
        var todayBtn = document.getElementById('pmd-today');
        if (!input) return;
        if (!input.value && typeof moment !== 'undefined') input.value = moment().format('YYYY-MM-DD');
        input.addEventListener('change', function () { window.renderPlanificadorMobileDay(); });
        if (prev) prev.addEventListener('click', function () { pmdShift(-1); });
        if (next) next.addEventListener('click', function () { pmdShift(1); });
        if (todayBtn) {
            todayBtn.addEventListener('click', function () {
                if (typeof moment !== 'undefined') input.value = moment().format('YYYY-MM-DD');
                window.renderPlanificadorMobileDay();
            });
        }
    })();

    document.body.addEventListener('click', function(e) {
        let btn = e.target.closest('.btn-ojo-magico');
        if (btn) {
            e.preventDefault();
            e.stopPropagation();
            window.toggleEye(btn.getAttribute('data-group-id'));
        }
    }, true);

    document.body.addEventListener('mousedown', function(e) {
        if (e.target.closest('.btn-ojo-magico')) {
            e.stopPropagation(); 
        }
    }, true);

    let resizer = document.getElementById('col-resizer');
    let ghost = document.getElementById('col-resizer-ghost');
    let isResizing = false;

    // NUEVO CÓDIGO (Ejecución única y bajo demanda):
    function updateResizerPosition() {
        let leftPanel = document.querySelector('.vis-panel.vis-left');
        if (leftPanel && resizer && !isResizing) {
            resizer.style.left = leftPanel.offsetWidth + 'px';
        }
    }
    // Inicializar después de que cargue el timeline
    setTimeout(updateResizerPosition, 500); 

    window.setSidebarWidth = function(width) {
        window.currentSidebarWidth = width;
        let style = document.getElementById('dynamic-sidebar-style');
        if (style) {
            style.innerHTML = `
                .vis-panel.vis-left, .vis-labelset, .vis-label {
                    width: ${width}px !important;
                    min-width: ${width}px !important;
                    max-width: ${width}px !important;
                }
            `;
        }
        updateResizerPosition();
    };
    resizer.addEventListener('mousedown', function(e) {
        isResizing = true;
        resizer.classList.add('is-resizing');
        document.body.style.cursor = 'ew-resize';
        let leftPanel = document.querySelector('.vis-panel.vis-left');
        if(leftPanel) ghost.style.left = leftPanel.offsetWidth + 'px';
        ghost.style.display = 'block';
        e.preventDefault();
    });

    document.addEventListener('mousemove', function(e) {
        if (!isResizing) return;
        let rect = document.getElementById('planificador-calendar').getBoundingClientRect();
        let newWidth = e.clientX - rect.left;
        if (newWidth < 120) newWidth = 120; 
        if (newWidth > 600) newWidth = 600; 
        ghost.style.left = newWidth + 'px';
    });

    document.addEventListener('mouseup', function(e) {
        if (isResizing) {
            isResizing = false;
            resizer.classList.remove('is-resizing');
            document.body.style.cursor = 'default';
            ghost.style.display = 'none';
            
            let rect = document.getElementById('planificador-calendar').getBoundingClientRect();
            let newWidth = e.clientX - rect.left;
            if (newWidth < 120) newWidth = 120; 
            if (newWidth > 600) newWidth = 600; 
            
            window.setSidebarWidth(newWidth);
            if (window.AppTimeline) window.AppTimeline.redraw();
        }
    });

    // =========================================================
    // CABECERA FLOTANTE + SCROLL DE PÁGINA (columna obras / Ctrl+rueda)
    // =========================================================
    const planificadorScrollRoot = document.querySelector('.planificador-page')
        || document.querySelector('.admin-main');

    function updateStickyHeader() {
        const pageEl = document.querySelector('.planificador-page');
        const timelineEl = document.querySelector('.vis-timeline');
        const topPanel = document.querySelector('.vis-panel.vis-top');
        if (!timelineEl) return;

        const rect = timelineEl.getBoundingClientRect();
        const headerH = topPanel ? topPanel.getBoundingClientRect().height : 36;
        const pinned = rect.top < 0 && rect.bottom > headerH + 8;

        if (pinned) {
            document.documentElement.style.setProperty('--sticky-top', Math.abs(rect.top) + 'px');
        } else {
            document.documentElement.style.setProperty('--sticky-top', '0px');
        }
        if (pageEl) {
            pageEl.classList.toggle('is-date-header-pinned', pinned);
        }
    }

    function bindStickyHeaderScroll() {
        updateStickyHeader();
        if (planificadorScrollRoot) {
            planificadorScrollRoot.addEventListener('scroll', updateStickyHeader, { passive: true });
        }
        window.addEventListener('scroll', updateStickyHeader, { passive: true });
    }

    function scrollPlanificadorPage(deltaY) {
        if (!deltaY) return;
        var roots = [];
        if (planificadorScrollRoot) roots.push(planificadorScrollRoot);
        var mainEl = document.querySelector('.admin-main');
        if (mainEl && roots.indexOf(mainEl) === -1) roots.push(mainEl);
        var scrolled = false;
        for (var i = 0; i < roots.length; i++) {
            var el = roots[i];
            if (!el) continue;
            var max = el.scrollHeight - el.clientHeight;
            if (max <= 1) continue;
            var before = el.scrollTop;
            el.scrollTop = Math.max(0, Math.min(max, before + deltaY));
            if (el.scrollTop !== before) {
                scrolled = true;
                break;
            }
        }
        if (!scrolled && planificadorScrollRoot) {
            planificadorScrollRoot.scrollTop += deltaY;
        }
        updateStickyHeader();
    }

    var planifPointer = {
        mode: null,
        lastY: 0,
        startX: 0,
        startY: 0,
        moved: false,
        lastEvent: null,
        confirming: false,
        clipboard: null,
    };

    function planifOrderedGroupIds() {
        if (!window.AppGroups) return [];
        var groups = window.AppGroups.get({
            order: function (a, b) { return (a.orden || 0) - (b.orden || 0); },
        }) || [];
        return groups.map(function (g) { return g.id; });
    }

    function planifGroupIndex(groupId) {
        var ids = planifOrderedGroupIds();
        var want = String(groupId);
        for (var i = 0; i < ids.length; i++) {
            if (String(ids[i]) === want) return i;
        }
        return 0;
    }

    function planifIsTypingTarget(el) {
        if (!el) return false;
        var tag = (el.tagName || '').toLowerCase();
        if (tag === 'input' || tag === 'textarea' || tag === 'select') return true;
        if (el.isContentEditable) return true;
        return !!el.closest('.select2-container, .select2-dropdown, .swal2-container, .modal');
    }

    function planifEnsureMarquee() {
        var el = document.getElementById('planificador-marquee');
        if (el) return el;
        el = document.createElement('div');
        el.id = 'planificador-marquee';
        el.className = 'planificador-marquee d-none';
        document.body.appendChild(el);
        return el;
    }

    function planifSetMarqueeBox(x1, y1, x2, y2) {
        var el = planifEnsureMarquee();
        var left = Math.min(x1, x2);
        var top = Math.min(y1, y2);
        var w = Math.abs(x2 - x1);
        var h = Math.abs(y2 - y1);
        el.style.left = left + 'px';
        el.style.top = top + 'px';
        el.style.width = w + 'px';
        el.style.height = h + 'px';
        el.classList.toggle('d-none', w < 2 && h < 2);
    }

    function planifHideMarquee() {
        var el = document.getElementById('planificador-marquee');
        if (el) el.classList.add('d-none');
    }

    function planifItemDomList() {
        var out = [];
        var itemSet = window.AppTimeline && window.AppTimeline.itemSet;
        var items = itemSet && itemSet.items;
        if (items) {
            Object.keys(items).forEach(function (key) {
                var visItem = items[key];
                if (!visItem || visItem.data && visItem.data.type === 'background') return;
                var el = visItem.dom && (visItem.dom.box || visItem.dom.point);
                if (!el) return;
                out.push({ id: visItem.id, el: el });
            });
        }
        return out;
    }

    function planifSelectIds(ids) {
        if (!window.AppTimeline || typeof window.AppTimeline.setSelection !== 'function') return;
        try { window.AppTimeline.setSelection(ids || []); } catch (errSel) { /* ignore */ }
    }

    function planifGetSelectedCopyables() {
        var ids = [];
        try {
            ids = (window.AppTimeline && window.AppTimeline.getSelection()) || [];
        } catch (errSel) { ids = []; }
        var items = [];
        ids.forEach(function (id) {
            var item = window.AppItems && window.AppItems.get(id);
            if (isCopyablePlanifItem(item)) items.push(item);
        });
        if (!items.length && window.currentSelectedItem && isCopyablePlanifItem(window.currentSelectedItem)) {
            items.push(window.currentSelectedItem);
        }
        return items;
    }

    function planifGetSelectedInercia() {
        var ids = [];
        try {
            ids = (window.AppTimeline && window.AppTimeline.getSelection()) || [];
        } catch (errSel) { ids = []; }
        var items = [];
        var seen = {};
        function push(item) {
            if (!item || isPlanificadorGhost(item) || !isPlanificadorInercia(item)) return;
            var id = String(item.id);
            if (seen[id]) return;
            seen[id] = true;
            items.push(item);
        }
        ids.forEach(function (id) {
            push(window.AppItems && window.AppItems.get(id));
        });
        if (!items.length) push(window.currentSelectedItem);
        return items;
    }

    function planifObraTitle(groupId) {
        if (window.AppGroups) {
            var g = window.AppGroups.get(groupId);
            if (g && g.title) return g.title;
        }
        var list = window.allGroupsMaster || [];
        for (var i = 0; i < list.length; i++) {
            if (String(list[i].id) === String(groupId)) return list[i].title || ('#' + groupId);
        }
        return String(groupId);
    }

    function planifUnassignSelection(items) {
        if (window.PLANIFICADOR_CAN_EDIT === false) {
            if (typeof Swal !== 'undefined') {
                Swal.fire(t('Sin permiso'), t('No tienes permisos de escritura en el planificador.'), 'warning');
            }
            return;
        }
        items = (items || []).filter(isCopyablePlanifItem);
        if (!items.length) return;

        var hoy = moment().startOf('day');
        var actionable = [];
        var skippedPast = 0;
        var anyClipped = false;

        items.forEach(function (item) {
            var startDate = moment(item.start);
            var endDate = moment(item.end).subtract(1, 'days');
            if (!endDate.isValid()) endDate = startDate.clone();
            if (endDate.isBefore(hoy)) {
                skippedPast += 1;
                return;
            }
            var startToErase = startDate.isBefore(hoy) ? hoy.clone() : startDate.clone();
            var dates = [];
            var current = startToErase.clone();
            while (current.isSameOrBefore(endDate)) {
                dates.push(current.format('YYYY-MM-DD'));
                current.add(1, 'days');
            }
            if (!dates.length) return;
            var clipped = startDate.isBefore(hoy);
            if (clipped) anyClipped = true;
            actionable.push({
                workerId: item.worker_id,
                obraId: item.group,
                title: item.title || '',
                obraTitle: planifObraTitle(item.group),
                dates: dates,
                startLabel: startToErase.format('DD/MM'),
                endLabel: endDate.format('DD/MM'),
                clipped: clipped,
            });
        });

        if (!actionable.length) {
            Swal.fire(
                t('Histórico Protegido'),
                skippedPast
                    ? t('Los bloques seleccionados pertenecen íntegramente al pasado y no se pueden borrar.')
                    : t('No hay asignaciones que desasignar.'),
                'info'
            );
            return;
        }

        var totalDays = 0;
        actionable.forEach(function (row) {
            totalDays += row.dates.length;
        });

        var maxLines = 20;
        var lines = actionable.slice(0, maxLines).map(function (row) {
            return '<li><strong>' + pmdEsc(row.title) + '</strong> · '
                + pmdEsc(row.obraTitle) + ' · '
                + row.startLabel + ' – ' + row.endLabel
                + ' <span class="text-muted">(' + row.dates.length + ' '
                + t('días') + ')</span></li>';
        });
        if (actionable.length > maxLines) {
            lines.push('<li class="text-muted">+' + (actionable.length - maxLines) + ' ' + t('más') + '…</li>');
        }

        var html = '<p class="mb-2">'
            + t('Se van a desasignar') + ' <strong>' + actionable.length + '</strong> '
            + t('bloques') + ' (' + totalDays + ' ' + t('días') + ').'
            + '</p>'
            + '<ul class="text-left mb-2 pl-3" style="max-height:14rem;overflow:auto;font-size:0.85rem;">'
            + lines.join('')
            + '</ul>'
            + '<p class="text-muted small mb-0">' + t('Esta acción es inmediata.') + '</p>';
        if (anyClipped) {
            html += '<p class="text-info small mb-0 mt-2"><i class="fas fa-info-circle"></i> '
                + t('Se conservará el histórico anterior a hoy.') + '</p>';
        }
        if (skippedPast) {
            html += '<p class="text-muted small mb-0 mt-1">'
                + skippedPast + ' ' + t('bloque(s) del pasado se omiten.') + '</p>';
        }

        hidePlanificadorOverlays();

        var swalOpts = {
            title: t('¿Confirmar desasignación?'),
            html: html,
            icon: 'warning',
            showCancelButton: true,
            focusConfirm: true,
            allowEnterKey: true,
            confirmButtonColor: '#d33',
            cancelButtonColor: '#3085d6',
            confirmButtonText: t('Sí, desasignar'),
            cancelButtonText: t('Cancelar'),
            customClass: {
                confirmButton: 'admin-swal-btn admin-swal-btn-danger',
                cancelButton: 'admin-swal-btn admin-swal-btn-ghost',
            },
            didOpen: function () {
                var btn = typeof Swal.getConfirmButton === 'function' ? Swal.getConfirmButton() : null;
                if (btn) btn.focus();
            },
        };
        var fire = (typeof window.adminSwal === 'function')
            ? window.adminSwal(swalOpts)
            : Swal.fire(swalOpts);

        fire.then(function (result) {
            if (!result || !result.isConfirmed) return;

            var buckets = {};
            actionable.forEach(function (row) {
                var key = String(row.workerId) + '|' + String(row.obraId);
                if (!buckets[key]) {
                    buckets[key] = { workerId: row.workerId, obraId: row.obraId, dates: [] };
                }
                row.dates.forEach(function (d) {
                    if (buckets[key].dates.indexOf(d) === -1) buckets[key].dates.push(d);
                });
            });
            var queue = Object.keys(buckets).map(function (k) { return buckets[k]; });
            var okCount = 0;
            var failMsg = '';

            Swal.fire({
                title: t('Desasignando…'),
                allowOutsideClick: false,
                allowEscapeKey: false,
                showConfirmButton: false,
                didOpen: function () { Swal.showLoading(); },
            });

            function finish() {
                if (typeof window.loadTimelineData === 'function') window.loadTimelineData();
                if (okCount && !failMsg) {
                    Swal.fire({
                        toast: true, position: 'top-end', icon: 'success',
                        title: t('Desasignado'),
                        showConfirmButton: false, timer: 1800,
                    });
                } else if (okCount && failMsg) {
                    Swal.fire(t('Parcial'), failMsg, 'warning');
                } else {
                    Swal.fire(t('Error'), failMsg || t('Ocurrió un error'), 'error');
                }
            }

            function next() {
                if (!queue.length) {
                    finish();
                    return;
                }
                var job = queue.shift();
                fetch('/api/v6/unassign_worker', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrf_token') },
                    body: JSON.stringify({
                        worker_id: job.workerId,
                        obra_id: job.obraId,
                        dates: job.dates,
                        mode: 'selected',
                    }),
                })
                    .then(function (r) { return r.json(); })
                    .then(function (data) {
                        if (data && data.success) {
                            okCount += 1;
                            next();
                        } else {
                            failMsg = (data && (data.message || data.error)) || t('Ocurrió un error');
                            next();
                        }
                    })
                    .catch(function () {
                        failMsg = t('Fallo de conexión.');
                        next();
                    });
            }
            next();
        });
    }

    function planifRectsOverlap(a, b) {
        return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
    }

    function planifFinishMarquee(x1, y1, x2, y2) {
        planifHideMarquee();
        var w = Math.abs(x2 - x1);
        var h = Math.abs(y2 - y1);
        var box = {
            left: Math.min(x1, x2),
            top: Math.min(y1, y2),
            right: Math.max(x1, x2),
            bottom: Math.max(y1, y2),
        };
        if (w < 4 && h < 4) {
            var props = window.AppTimeline && planifPointer.lastEvent
                ? window.AppTimeline.getEventProperties(planifPointer.lastEvent)
                : null;
            if (props && props.item) {
                var cur = [];
                try { cur = window.AppTimeline.getSelection() || []; } catch (errCur) { cur = []; }
                var sid = props.item;
                var next = cur.filter(function (id) { return String(id) !== String(sid); });
                if (next.length === cur.length) next.push(sid);
                planifSelectIds(next);
            }
            return;
        }
        var hit = [];
        planifItemDomList().forEach(function (entry) {
            var item = window.AppItems && window.AppItems.get(entry.id);
            if (!isCopyablePlanifItem(item) && !isPlanificadorGhost(item)) return;
            var r = entry.el.getBoundingClientRect();
            if (planifRectsOverlap(box, r)) hit.push(entry.id);
        });
        planifSelectIds(hit);
    }

    function planifEnsureGhostBar() {
        var bar = document.getElementById('planificador-ghost-bar');
        if (bar) return bar;
        bar = document.createElement('div');
        bar.id = 'planificador-ghost-bar';
        bar.className = 'planificador-ghost-bar d-none';
        bar.innerHTML =
            '<i class="fas fa-clone"></i>' +
            '<span id="planificador-ghost-bar-text"></span>' +
            '<div class="planificador-ghost-bar-actions">' +
                '<button type="button" class="btn-admin btn-admin-primary" id="planificador-ghost-confirm">' + t('Confirmar') + '</button>' +
                '<button type="button" class="btn-admin btn-admin-ghost" id="planificador-ghost-cancel">' + t('Cancelar') + '</button>' +
            '</div>';
        document.body.appendChild(bar);
        bar.querySelector('#planificador-ghost-confirm').addEventListener('click', function (e) {
            e.preventDefault();
            planifConfirmGhosts();
        });
        bar.querySelector('#planificador-ghost-cancel').addEventListener('click', function (e) {
            e.preventDefault();
            planifClearGhosts();
        });
        return bar;
    }

    function planifFestivoSet() {
        if (planifPointer._festivosSet) return planifPointer._festivosSet;
        var raw = window.PLANIFICADOR_FESTIVOS || [];
        var set = {};
        (raw || []).forEach(function (d) {
            if (d) set[String(d)] = true;
        });
        planifPointer._festivosSet = set;
        return set;
    }

    function planifIsNonLaborable(dayMoment) {
        if (!dayMoment || !dayMoment.isValid()) return true;
        var wd = dayMoment.day(); // 0=domingo … 6=sábado
        if (wd === 0 || wd === 6) return true;
        return !!planifFestivoSet()[dayMoment.format('YYYY-MM-DD')];
    }

    /** Avanza al siguiente día laborable (lun–vie no festivo). */
    function planifSnapToLaborable(dayMoment, maxDays) {
        var m = moment(dayMoment).startOf('day');
        var limit = typeof maxDays === 'number' ? maxDays : 14;
        var i = 0;
        while (i < limit && planifIsNonLaborable(m)) {
            m.add(1, 'days');
            i += 1;
        }
        return m;
    }

    function planifUpdateGhostBar() {
        var ghosts = collectPlanifGhosts();
        var bar = planifEnsureGhostBar();
        var text = document.getElementById('planificador-ghost-bar-text');
        if (!ghosts.length) {
            bar.classList.add('d-none');
            return;
        }
        bar.classList.remove('d-none');
        if (text) {
            text.textContent = planifPointer.confirming
                ? t('Guardando asignaciones…')
                : (t('Borrador') + ' · ' + ghosts.length + ' ' + t('asignaciones') + ' · ' + t('Enter confirma · Esc cancela'));
        }
        var confirmBtn = document.getElementById('planificador-ghost-confirm');
        var cancelBtn = document.getElementById('planificador-ghost-cancel');
        if (confirmBtn) confirmBtn.disabled = !!planifPointer.confirming;
        if (cancelBtn) cancelBtn.disabled = !!planifPointer.confirming;
    }

    function planifClearGhosts() {
        var ghosts = collectPlanifGhosts();
        if (ghosts.length && window.AppItems) {
            window.AppItems.remove(ghosts.map(function (g) { return g.id; }));
        }
        planifPointer.confirming = false;
        planifUpdateGhostBar();
    }

    function planifCopySelection() {
        var items = planifGetSelectedCopyables();
        if (!items.length) {
            if (typeof Swal !== 'undefined') {
                Swal.fire({
                    toast: true, position: 'top-end', icon: 'info',
                    title: t('No hay asignaciones seleccionadas'),
                    showConfirmButton: false, timer: 1800,
                });
            }
            return;
        }
        items.sort(function (a, b) {
            var gi = planifGroupIndex(a.group) - planifGroupIndex(b.group);
            if (gi) return gi;
            return moment(a.start).valueOf() - moment(b.start).valueOf();
        });
        var originStart = moment(items[0].start).startOf('day');
        var originGroup = planifGroupIndex(items[0].group);
        planifPointer.clipboard = items.map(function (item) {
            var start = moment(item.start).startOf('day');
            var end = moment(item.end);
            return {
                worker_id: item.worker_id,
                title: item.title,
                color: item.color,
                style: item.style,
                empresa_nombre: item.empresa_nombre,
                empresa_id: item.empresa_id,
                categoria: item.categoria,
                especialidad: item.especialidad,
                nota: item.nota,
                relStartDays: start.diff(originStart, 'days'),
                durationDays: Math.max(1, end.diff(start, 'days')),
                relGroupOffset: planifGroupIndex(item.group) - originGroup,
            };
        });
        if (typeof Swal !== 'undefined') {
            Swal.fire({
                toast: true, position: 'top-end', icon: 'success',
                title: planifPointer.clipboard.length + ' ' + t('asignaciones copiadas'),
                showConfirmButton: false, timer: 1600,
            });
        }
    }

    function planifPasteClipboard() {
        if (window.PLANIFICADOR_CAN_EDIT === false) {
            if (typeof Swal !== 'undefined') {
                Swal.fire(t('Sin permiso'), t('No tienes permisos de escritura en el planificador.'), 'warning');
            }
            return;
        }
        var clip = planifPointer.clipboard;
        if (!clip || !clip.length) {
            if (typeof Swal !== 'undefined') {
                Swal.fire({
                    toast: true, position: 'top-end', icon: 'info',
                    title: t('No hay nada copiado'),
                    showConfirmButton: false, timer: 1800,
                });
            }
            return;
        }
        if (!window.AppTimeline || !window.AppItems) return;

        planifClearGhosts();

        var props = null;
        try {
            if (planifPointer.lastEvent) props = window.AppTimeline.getEventProperties(planifPointer.lastEvent);
        } catch (errProps) { props = null; }

        var groupIds = planifOrderedGroupIds();
        if (!groupIds.length) return;
        var anchorGroup = (props && props.group != null) ? props.group : groupIds[0];
        var anchorStart = moment((props && props.time) || window.AppTimeline.getWindow().start).startOf('day');
        var hoy = moment().startOf('day');
        if (anchorStart.isBefore(hoy)) anchorStart = hoy.clone();
        anchorStart = planifSnapToLaborable(anchorStart);
        var anchorIdx = planifGroupIndex(anchorGroup);

        var ghostIds = [];
        var stamp = Date.now();
        clip.forEach(function (piece, i) {
            var gIdx = anchorIdx + piece.relGroupOffset;
            if (gIdx < 0) gIdx = 0;
            if (gIdx >= groupIds.length) gIdx = groupIds.length - 1;
            var start = anchorStart.clone().add(piece.relStartDays, 'days');
            if (start.isBefore(hoy)) start = hoy.clone();
            start = planifSnapToLaborable(start);
            var end = start.clone().add(piece.durationDays, 'days');
            var gid = 'ghost_' + stamp + '_' + i;
            window.AppItems.add({
                id: gid,
                isGhost: true,
                group: groupIds[gIdx],
                start: start.toDate(),
                end: end.toDate(),
                worker_id: piece.worker_id,
                title: piece.title,
                color: piece.color,
                style: piece.style,
                empresa_nombre: piece.empresa_nombre,
                empresa_id: piece.empresa_id,
                categoria: piece.categoria,
                especialidad: piece.especialidad,
                nota: piece.nota,
                className: 'planificador-ghost',
                editable: { updateTime: true, updateGroup: true, remove: false },
            });
            ghostIds.push(gid);
        });
        planifSelectIds(ghostIds);
        planifUpdateGhostBar();
        planifRelayoutLanes();
    }

    function planifCommitAssignmentItems(items, opts) {
        opts = opts || {};
        if (planifPointer.confirming) return;
        if (window.PLANIFICADOR_CAN_EDIT === false) {
            if (typeof Swal !== 'undefined') {
                Swal.fire(t('Sin permiso'), t('No tienes permisos de escritura en el planificador.'), 'warning');
            }
            return;
        }
        var hoy = moment().startOf('day');
        var queue = [];
        var skippedWeekend = 0;
        (items || []).forEach(function (g) {
            if (!g || g.group == null) return;
            var w = String(g.worker_id == null ? '' : g.worker_id);
            if (!w || w === 'SYSTEM' || w === 'REQUEST' || w === 'NEW' || w === 'GENERICO') return;
            var start = moment(g.start).startOf('day');
            var end = moment(g.end).subtract(1, 'days').startOf('day');
            if (!start.isValid() || !end.isValid()) return;
            if (start.isBefore(hoy)) start = hoy.clone();
            // Sin fines de semana: no mandar rangos que solo caen en sáb/dom/festivo
            // (pegado con el cursor en finde → «El rango no contiene días laborables»).
            var spanDays = Math.max(0, end.diff(start, 'days'));
            start = planifSnapToLaborable(start);
            end = start.clone().add(spanDays, 'days');
            // Si el tramo sigue sin laborables (p.ej. solo festivos), saltar
            var probe = start.clone();
            var hasLab = false;
            var guard = 0;
            while (!probe.isAfter(end) && guard < 40) {
                if (!planifIsNonLaborable(probe)) { hasLab = true; break; }
                probe.add(1, 'days');
                guard += 1;
            }
            if (!hasLab) {
                skippedWeekend += 1;
                return;
            }
            if (end.isBefore(start)) return;
            queue.push({
                worker_id: g.worker_id,
                target_obra_id: g.group,
                start_date: start.format('YYYY-MM-DD'),
                end_date: end.format('YYYY-MM-DD'),
                include_weekends: false,
                overwrite_mode: 'check',
                continue_on_noop: true,
                _removeId: opts.removeOnSuccess ? g.id : null,
            });
        });
        if (!queue.length) {
            if (typeof Swal !== 'undefined') {
                Swal.fire(
                    t('Error'),
                    skippedWeekend
                        ? t('El rango no contiene días laborables válidos.')
                        : t('No hay asignaciones que confirmar.'),
                    'error'
                );
            }
            return;
        }

        planifPointer.confirming = true;
        planifUpdateGhostBar();
        hidePlanificadorOverlays();

        function finishOk() {
            planifPointer.confirming = false;
            if (opts.clearGhosts) planifClearGhosts();
            else planifUpdateGhostBar();
            if (typeof window.loadTimelineData === 'function') window.loadTimelineData();
            if (typeof Swal !== 'undefined') {
                Swal.fire({
                    toast: true, position: 'top-end', icon: 'success',
                    title: opts.successTitle || t('Asignaciones confirmadas'),
                    showConfirmButton: false, timer: 1800,
                });
            }
        }

        function finishStop() {
            planifPointer.confirming = false;
            planifUpdateGhostBar();
        }

        function next() {
            if (!queue.length) {
                finishOk();
                return;
            }
            var job = queue.shift();
            pendingAction = job;
            pendingRevert = finishStop;
            ejecutarAccionAPI(pendingRevert, function () {
                if (job._removeId && window.AppItems) {
                    try { window.AppItems.remove(job._removeId); } catch (errRm) { /* ignore */ }
                }
                next();
            });
        }
        next();
    }

    function planifConfirmGhosts() {
        planifCommitAssignmentItems(collectPlanifGhosts(), {
            removeOnSuccess: true,
            clearGhosts: true,
            successTitle: t('Asignaciones confirmadas'),
        });
    }

    function planifConfirmInercia(items) {
        planifCommitAssignmentItems(items || planifGetSelectedInercia(), {
            successTitle: t('Inercia convertida en asignación'),
        });
    }

    window.confirmarInerciaDesdePop = function () {
        var item = window.currentSelectedItem;
        hidePlanificadorOverlays();
        window.currentSelectedItem = null;
        if (item && isPlanificadorInercia(item)) {
            planifConfirmInercia([item]);
        } else {
            planifConfirmInercia();
        }
    };

    var PLANIF_MS_DAY = 1000 * 60 * 60 * 24;
    var PLANIF_ZOOM_MIN = PLANIF_MS_DAY * 7;
    var PLANIF_ZOOM_MAX = PLANIF_MS_DAY * 365 * 20;
    var planifViewPin = null;
    var planifPinTimer = null;
    var planifPinRestoring = false;

    function planifScrollRootEl() {
        return planificadorScrollRoot || document.querySelector('.admin-main');
    }

    function planifAttrEscape(val) {
        var s = String(val);
        if (window.CSS && typeof CSS.escape === 'function') return CSS.escape(s);
        return s.replace(/\\/g, '\\\\').replace(/"/g, '\\"');
    }

    function planifRowAnchor(groupId) {
        if (groupId == null || groupId === '') return null;
        var btn = document.querySelector(
            '#planificador-calendar .btn-ojo-magico[data-group-id="' + planifAttrEscape(groupId) + '"]'
        );
        return btn ? (btn.closest('.vis-label') || btn) : null;
    }

    function planifLabelAtY(clientY) {
        var labels = document.querySelectorAll('#planificador-calendar .vis-labelset .vis-label');
        var last = null;
        for (var i = 0; i < labels.length; i++) {
            var r = labels[i].getBoundingClientRect();
            if (r.height < 2) continue;
            var btn = labels[i].querySelector('.btn-ojo-magico');
            var info = {
                el: labels[i],
                groupId: btn ? btn.getAttribute('data-group-id') : null,
                top: r.top,
            };
            if (clientY >= r.top && clientY <= r.bottom) return info;
            if (r.top <= clientY) last = info;
        }
        return last;
    }

    function planifAbandonViewPin() {
        planifViewPin = null;
        if (planifPinTimer) {
            clearTimeout(planifPinTimer);
            planifPinTimer = null;
        }
    }

    function planifClearViewPin() {
        planifAbandonViewPin();
        fitPlanificadorTimelineToGroups();
    }

    function planifCaptureViewPin(event, props) {
        var hit = planifLabelAtY(event.clientY);
        if (!hit || !hit.groupId) {
            var center = document.querySelector('#planificador-calendar .vis-panel.vis-center');
            if (center) {
                var cr = center.getBoundingClientRect();
                var y = event.clientY;
                if (y < cr.top || y > cr.bottom) y = cr.top + Math.min(cr.height * 0.35, 120);
                hit = planifLabelAtY(y);
            }
        }
        var groupId = (hit && hit.groupId) || (props && props.group);
        if (groupId == null || groupId === '') {
            var labels = document.querySelectorAll('#planificador-calendar .vis-labelset .vis-label');
            var cal = document.querySelector('#planificador-calendar .vis-panel.vis-center')
                || document.getElementById('planificador-calendar');
            var vr = cal ? cal.getBoundingClientRect() : { top: 0, bottom: window.innerHeight };
            for (var i = 0; i < labels.length; i++) {
                var lr = labels[i].getBoundingClientRect();
                if (lr.bottom <= vr.top || lr.top >= vr.bottom) continue;
                var btn = labels[i].querySelector('.btn-ojo-magico');
                if (!btn) continue;
                hit = { el: labels[i], groupId: btn.getAttribute('data-group-id'), top: lr.top };
                groupId = hit.groupId;
                break;
            }
        }
        var rowEl = planifRowAnchor(groupId) || (hit && hit.el);
        var top = rowEl ? rowEl.getBoundingClientRect().top : event.clientY;
        planifViewPin = {
            groupId: groupId,
            offsetInGroup: event.clientY - top,
            clientY: event.clientY,
        };
    }

    function planifRestoreViewPin() {
        var pin = planifViewPin;
        if (!pin || pin.groupId == null || planifPinRestoring) return;
        planifPinRestoring = true;
        try {
            var el = planifRowAnchor(pin.groupId);
            var root = planifScrollRootEl();
            if (!el || !root) return;
            var rootRect = root.getBoundingClientRect();
            var elRect = el.getBoundingClientRect();
            var off = pin.offsetInGroup;
            if (elRect.height > 1) off = Math.max(0, Math.min(off, elRect.height - 1));
            var groupContentY = elRect.top - rootRect.top + root.scrollTop;
            var pointContentY = groupContentY + off;
            var target = pointContentY - (pin.clientY - rootRect.top);
            var max = Math.max(0, root.scrollHeight - root.clientHeight);
            target = Math.max(0, Math.min(max, Math.round(target)));
            if (Math.abs(root.scrollTop - target) >= 1) {
                root.scrollTop = target;
            }
            updateStickyHeader();
        } finally {
            planifPinRestoring = false;
        }
    }

    function planifKeepViewPin(ms) {
        planifRestoreViewPin();
        if (planifPinTimer) clearTimeout(planifPinTimer);
        var until = Date.now() + (ms || 450);
        function tick() {
            if (!planifViewPin) return;
            planifRestoreViewPin();
            if (Date.now() < until) planifPinTimer = setTimeout(tick, 50);
            else planifClearViewPin();
        }
        planifPinTimer = setTimeout(tick, 50);
    }

    function planifZoomAroundPointer(event) {
        var tl = window.AppTimeline;
        if (!tl || typeof tl.getWindow !== 'function') return;
        var win = tl.getWindow();
        var tStart = new Date(win.start).getTime();
        var tEnd = new Date(win.end).getTime();
        var interval = tEnd - tStart;
        if (!interval || !isFinite(interval)) return;

        var props = null;
        try { props = tl.getEventProperties(event); } catch (errProps) { props = null; }
        var pivot = (props && props.time) ? new Date(props.time).getTime() : NaN;
        if (!isFinite(pivot)) {
            var center = document.querySelector('#planificador-calendar .vis-panel.vis-center');
            var rect = (center || document.getElementById('planificador-calendar')).getBoundingClientRect();
            var fracX = rect.width ? (event.clientX - rect.left) / rect.width : 0.5;
            fracX = Math.max(0, Math.min(1, fracX));
            pivot = tStart + interval * fracX;
        }

        var steps = event.deltaY;
        if (event.deltaMode === 1) steps = event.deltaY;
        else if (event.deltaMode === 2) steps = event.deltaY * 4;
        else steps = event.deltaY / 100;
        var factor = Math.pow(1.12, steps);
        var newInterval = Math.min(PLANIF_ZOOM_MAX, Math.max(PLANIF_ZOOM_MIN, interval * factor));
        if (Math.abs(newInterval - interval) < 1) return;

        var frac = (pivot - tStart) / interval;
        if (!isFinite(frac)) frac = 0.5;
        frac = Math.max(0, Math.min(1, frac));
        var newStart = pivot - newInterval * frac;
        var newEnd = newStart + newInterval;

        planifCaptureViewPin(event, props);
        tl.setWindow(new Date(newStart), new Date(newEnd), { animation: false });
        planifRestoreViewPin();
        planifKeepViewPin(500);
    }

    function setupPlanificadorWheelScroll() {
        const calendarRoot = document.getElementById('planificador-calendar');
        if (!calendarRoot) return;

        calendarRoot.addEventListener('wheel', function(event) {
            if (Math.abs(event.deltaY) <= Math.abs(event.deltaX)) return;

            // Columna de nombres de obra: scroll vertical de página, no zoom del timeline.
            var onObraLabels = !!(event.target && event.target.closest &&
                event.target.closest('.vis-panel.vis-left, .vis-labelset, .vis-label'));

            event.preventDefault();
            event.stopPropagation();
            event.stopImmediatePropagation();

            if (onObraLabels || event.ctrlKey || event.metaKey) {
                planifAbandonViewPin();
                scrollPlanificadorPage(event.deltaY);
                return;
            }
            planifZoomAroundPointer(event);
        }, { passive: false, capture: true });
    }

    function setupPlanificadorDragPan() {
        const calendarRoot = document.getElementById('planificador-calendar');
        if (!calendarRoot) return;

        function isOnItem(el) {
            return !!(el && el.closest && el.closest('.vis-item, .vis-drag-center, .vis-item-overflow, .vis-drag-left, .vis-drag-right'));
        }

        function isOnUiChrome(el) {
            return !!(el && el.closest && el.closest('#col-resizer, .btn-ojo-magico, button, a, input, select, textarea, .planificador-ghost-bar'));
        }

        function isOnTimeline(el) {
            return !!(el && el.closest && el.closest('#planificador-calendar'));
        }

        calendarRoot.addEventListener('pointerdown', function (e) {
            if (e.button !== 0) return;
            if (isOnUiChrome(e.target)) return;
            planifPointer.lastEvent = e;

            if (e.shiftKey) {
                e.preventDefault();
                e.stopImmediatePropagation();
                planifPointer.mode = 'marquee';
                planifPointer.startX = e.clientX;
                planifPointer.startY = e.clientY;
                planifPointer.moved = false;
                planifSetMarqueeBox(e.clientX, e.clientY, e.clientX, e.clientY);
                calendarRoot.classList.add('is-planif-pointer', 'is-planif-selecting');
                try { calendarRoot.setPointerCapture(e.pointerId); } catch (errCap) { /* ignore */ }
                hidePlanificadorOverlays();
                return;
            }

            if (e.ctrlKey || e.metaKey || e.altKey) return;
            if (isOnItem(e.target)) return;
            if (!isOnTimeline(e.target)) return;

            planifPointer.mode = 'pan';
            planifPointer.lastY = e.clientY;
            planifPointer.moved = false;
            calendarRoot.classList.add('is-planif-pointer');
        }, true);

        window.addEventListener('pointermove', function (e) {
            if (e.target && calendarRoot.contains(e.target)) planifPointer.lastEvent = e;
            if (planifPointer.mode === 'pan') {
                var dy = e.clientY - planifPointer.lastY;
                planifPointer.lastY = e.clientY;
                if (!dy) return;
                planifPointer.moved = true;
                planifAbandonViewPin();
                scrollPlanificadorPage(-dy);
            } else if (planifPointer.mode === 'marquee') {
                planifPointer.lastEvent = e;
                if (Math.abs(e.clientX - planifPointer.startX) > 2 || Math.abs(e.clientY - planifPointer.startY) > 2) {
                    planifPointer.moved = true;
                }
                planifSetMarqueeBox(planifPointer.startX, planifPointer.startY, e.clientX, e.clientY);
            }
        }, true);

        function endPointer(e) {
            var mode = planifPointer.mode;
            if (!mode) return;
            if (e) planifPointer.lastEvent = e;
            calendarRoot.classList.remove('is-planif-pointer', 'is-planif-selecting');
            if (mode === 'marquee') {
                planifFinishMarquee(
                    planifPointer.startX,
                    planifPointer.startY,
                    e ? e.clientX : planifPointer.startX,
                    e ? e.clientY : planifPointer.startY
                );
                window.__planificadorDidDrag = true;
            } else if (mode === 'pan' && planifPointer.moved) {
                window.__planificadorDidDrag = true;
            }
            planifPointer.mode = null;
            planifPointer.moved = false;
        }

        window.addEventListener('pointerup', endPointer, true);
        window.addEventListener('pointercancel', endPointer, true);
    }

    function bindVisPanFallback() {
        if (!window.AppTimeline || window.AppTimeline.__planifPanBound) return;
        window.AppTimeline.__planifPanBound = true;
        window.AppTimeline.on('mouseDown', function (props) {
            if (planifPointer.mode) return;
            var ev = props && props.event;
            if (!ev || (ev.button != null && ev.button !== 0)) return;
            if (ev.shiftKey || ev.ctrlKey || ev.metaKey || ev.altKey) return;
            if (props.what === 'item') return;
            planifPointer.mode = 'pan';
            planifPointer.lastY = ev.clientY != null ? ev.clientY : props.pageY;
            planifPointer.moved = false;
            var calendarRoot = document.getElementById('planificador-calendar');
            if (calendarRoot) calendarRoot.classList.add('is-planif-pointer');
        });
        window.AppTimeline.on('mouseMove', function (props) {
            if (props && props.event) planifPointer.lastEvent = props.event;
        });
        var lastHammerY = null;
        function onVisPanMove(ev) {
            if (planifPointer.mode === 'pan' || planifPointer.mode === 'marquee') {
                lastHammerY = ev && ev.center ? ev.center.y : lastHammerY;
                return;
            }
            var itemSet = window.AppTimeline.itemSet;
            if (itemSet && itemSet.touchParams && itemSet.touchParams.itemIsDragging) {
                lastHammerY = ev && ev.center ? ev.center.y : lastHammerY;
                return;
            }
            var y = ev && ev.center ? ev.center.y : null;
            if (y == null && ev && ev.srcEvent) y = ev.srcEvent.clientY;
            if (y == null) return;
            if (lastHammerY != null && y !== lastHammerY) {
                planifAbandonViewPin();
                scrollPlanificadorPage(-(y - lastHammerY));
                window.__planificadorDidDrag = true;
            }
            lastHammerY = y;
        }
        try {
            window.AppTimeline.on('panstart', function (ev) {
                lastHammerY = ev && ev.center ? ev.center.y : null;
            });
            window.AppTimeline.on('panmove', onVisPanMove);
            window.AppTimeline.on('panend', function () { lastHammerY = null; });
        } catch (errPan) { /* ignore */ }
    }

    bindStickyHeaderScroll();
    setupPlanificadorWheelScroll();
    setupPlanificadorDragPan();
    setTimeout(updateStickyHeader, 300);
    window.addEventListener('resize', function () {
        refreshPlanificadorLayout();
    });
    
    // Solo lo ejecutamos cuando el usuario hace scroll, usando un listener "passive" muy ligero


    var calendarDiv = document.getElementById('planificador-calendar');

    function planifLang() {
        return (window.SP_lang ? window.SP_lang() : String(window.SP_LOCALE || 'es').slice(0, 2)).toLowerCase();
    }

    function planifDate(d) {
        if (!d) return new Date();
        if (d instanceof Date) return d;
        if (typeof d.toDate === 'function') return d.toDate();
        return new Date(d.valueOf ? d.valueOf() : d);
    }

    function planifFmt(date, scale, major) {
        var d = planifDate(date);
        var loc = window.SP_dateLocale ? window.SP_dateLocale() : 'es-ES';
        var opts;
        if (!major) {
            switch (scale) {
                case 'millisecond':
                    opts = { second: 'numeric', fractionalSecondDigits: 3 };
                    break;
                case 'second':
                    opts = { second: 'numeric' };
                    break;
                case 'minute':
                case 'hour':
                    opts = { hour: '2-digit', minute: '2-digit', hour12: false };
                    break;
                case 'weekday':
                    opts = { weekday: 'short', day: 'numeric' };
                    break;
                case 'day':
                    opts = { day: 'numeric' };
                    break;
                case 'week':
                    if (window.moment) return window.moment(d).locale(planifLang()).format('w');
                    opts = { day: 'numeric' };
                    break;
                case 'month':
                    opts = { month: 'short' };
                    break;
                case 'year':
                    opts = { year: 'numeric' };
                    break;
                default:
                    opts = { day: 'numeric', month: 'short' };
            }
        } else {
            switch (scale) {
                case 'millisecond':
                    opts = { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false };
                    break;
                case 'second':
                    opts = { day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit', hour12: false };
                    break;
                case 'minute':
                case 'hour':
                    opts = { weekday: 'short', day: 'numeric', month: 'long' };
                    break;
                case 'weekday':
                case 'day':
                case 'week':
                    opts = { month: 'long', year: 'numeric' };
                    break;
                case 'month':
                    opts = { year: 'numeric' };
                    break;
                case 'year':
                    return '';
                default:
                    opts = { month: 'long', year: 'numeric' };
            }
        }
        try {
            return new Intl.DateTimeFormat(loc, opts).format(d);
        } catch (errFmt) {
            return new Intl.DateTimeFormat('es-ES', opts).format(d);
        }
    }

    if (window.moment && typeof window.moment.locale === 'function') {
        try { window.moment.locale(planifLang()); } catch (eLoc) { /* ignore */ }
    }

    var options = {
        orientation: 'top',
        groupHeightMode: 'auto',
        verticalScroll: false,
        stack: true,
        stackSubgroups: true,
        subgroupOrder: 'subgroupOrder',
        multiselect: true,
        selectable: true,
        groupEditable: true,
        groupOrder: 'orden',
        margin: { item: { horizontal: 2, vertical: 4 }, axis: 5 },
        throttleRedraw: 120,
        preferZoom: true,
        zoomable: false,
        showTooltips: false,
        editable: (window.PLANIFICADOR_CAN_EDIT === false)
            ? false
            : { add: false, updateTime: true, updateGroup: true, remove: false },
        zoomMin: PLANIF_ZOOM_MIN,
        zoomMax: PLANIF_ZOOM_MAX,
        locale: planifLang(),
        locales: {
            es: { current: 'hoy', time: 'hora' },
            en: { current: 'current', time: 'time' },
            pt: { current: 'atual', time: 'hora' },
            fr: { current: 'actuel', time: 'heure' },
        },
        format: {
            minorLabels: function (date, scale) { return planifFmt(date, scale, false); },
            majorLabels: function (date, scale) { return planifFmt(date, scale, true); },
        },

        order: function(a, b) {
            // Solicitudes en su carril arriba; borrador NEW al final.
            var aReq = planifIsRequestItem(a);
            var bReq = planifIsRequestItem(b);
            if (aReq !== bReq) return aReq ? -1 : 1;

            var aDraft = String(a.worker_id) === 'NEW';
            var bDraft = String(b.worker_id) === 'NEW';
            if (aDraft !== bDraft) return aDraft ? 1 : -1;

            let empA = a.empresa_nombre || "ZZ_Sin_Empresa";
            let empB = b.empresa_nombre || "ZZ_Sin_Empresa";
            
            if (empA !== empB) {
                return empA.localeCompare(empB);
            }
            
            let nameA = a.title || "";
            let nameB = b.title || "";
            if (nameA !== nameB) {
                return nameA.localeCompare(nameB);
            }
            
            return (new Date(a.start).getTime() - new Date(b.start).getTime());
        },

        groupTemplate: function(group) {
            var container = document.createElement('div');
            container.style.position = 'relative'; 
            container.style.width = '100%';
            container.style.height = '100%';
            container.style.minHeight = '36px'; 
            container.style.padding = '4px 55px 4px 24px';
            container.style.boxSizing = 'border-box';
            container.style.borderLeft = '4px solid #3b82f6';
            container.style.display = 'flex';
            container.style.flexDirection = 'column';
            container.style.justifyContent = 'center';
            
            var isHidden = window.hiddenGroups.has(String(group.id));
            if (isHidden) container.style.opacity = '0.5';

            var dragHandle = document.createElement('div');
            dragHandle.innerHTML = '<i class="fas fa-grip-vertical" style="color: #cbd5e1; font-size: 14px;"></i>';
            dragHandle.style.position = 'absolute';
            dragHandle.style.left = '6px';
            dragHandle.style.top = '50%';
            dragHandle.style.transform = 'translateY(-50%)';
            dragHandle.style.pointerEvents = 'none';

            var titleEl = document.createElement('a');
            titleEl.href = '/admin/obra_panel/' + group.id; 
            titleEl.target = '_blank'; 
            titleEl.textContent = group.title || '';
            titleEl.style.display = 'block';
            titleEl.style.fontSize = '12px'; 
            titleEl.style.fontWeight = 'bold';
            titleEl.style.lineHeight = '1.2';
            titleEl.style.color = '#2563eb'; 
            titleEl.style.textDecoration = 'none';
            titleEl.style.whiteSpace = 'nowrap';
            titleEl.style.textOverflow = 'ellipsis';
            titleEl.style.overflow = 'hidden';

            var codeEl = document.createElement('small');
            codeEl.style.display = 'block';
            codeEl.style.fontSize = '9px'; 
            codeEl.style.color = '#64748b';
            codeEl.style.whiteSpace = 'nowrap';
            codeEl.style.textOverflow = 'ellipsis';
            codeEl.style.overflow = 'hidden';
            codeEl.style.marginTop = '2px';
            
            let htmlStr = group.codigo || '';
            if (group.fecha_fin) {
                if (htmlStr) htmlStr += ' | ';
                htmlStr += '<span style="color:#64748b; font-weight:bold;"><i class="fas fa-flag-checkered mr-1"></i> Fin: ' + group.fecha_fin + '</span>';
            }
            codeEl.innerHTML = htmlStr;

            var btn = document.createElement('div');
            btn.className = 'btn-ojo-magico';
            btn.setAttribute('data-group-id', group.id);
            btn.title = t('Mostrar / Ocultar operarios');
            btn.style.position = 'absolute';
            btn.style.right = '4px';
            btn.style.top = '50%';
            btn.style.transform = 'translateY(-50%)';
            btn.style.width = '20px';
            btn.style.height = '20px';
            btn.style.background = '#f8fafc';
            btn.style.border = '1px solid #e2e8f0';
            btn.style.borderRadius = '4px';
            btn.style.cursor = 'pointer';
            btn.style.display = 'flex';
            btn.style.alignItems = 'center';
            btn.style.justifyContent = 'center';
            btn.style.zIndex = '10';

            var icon = document.createElement('i');
            icon.className = isHidden ? 'fas fa-eye-slash' : 'fas fa-eye';
            icon.style.color = isHidden ? '#94a3b8' : '#3b82f6';
            icon.style.fontSize = '10px';
            btn.appendChild(icon);

            container.appendChild(dragHandle);
            container.appendChild(titleEl);
            container.appendChild(codeEl);
            container.appendChild(btn);

            return container;
        },
        
        template: function(item) {
            if (item.worker_id === 'NEW' || item.worker_id === 'SYSTEM') return item.content || '';
            
            // Estilo para las Solicitudes (quitamos el color:white para que use el del style del backend)
            if (item.worker_id === 'REQUEST') {
                return `<div class="operario-micro" style="font-weight:bold; font-size:11px;">
                            <i class="fas fa-exclamation-triangle mr-1"></i>${item.title}
                        </div>`;
            }
            
            // Estilo para Operarios normales (tooltip vía itemover)
            const emp = formatEmpresaLabel(item.empresa_nombre);
            const icon = item.inercia ? 'fa-ghost' : (item.es_falta ? 'fa-user-slash' : 'fa-user');
            return `<div class="operario-micro" data-empresa="${emp.replace(/"/g, '&quot;')}"><i class="fas ${icon}"></i>${item.title}</div>`;
        },
        onUpdate: function (item, callback) {
            if (isPlanificadorGhost(item)) {
                callback(item);
                return;
            }
            if (item.worker_id === 'NEW') {
                let startStr = moment(item.start).format('YYYY-MM-DD');
                let endStr = moment(item.end).format('YYYY-MM-DD');
                let obraId = item.group;
                let obraObj = window.allGroupsMaster.find(x => String(x.id) === String(obraId));
                let obraNombre = obraObj ? obraObj.title : 'Obra';

                // 1. CANCELAMOS LA ACCIÓN DE VIS.JS INMEDIATAMENTE
                callback(null); 

                // 2. RETRASAMOS 50ms LA APERTURA DEL MODAL
                // Esto permite que el navegador lance el evento nativo 'mouseup' 
                // y Vis.js suelte el arrastre del fondo correctamente.
                setTimeout(() => {
                    if (window.AppItems) window.AppItems.remove('phantom_new');

                    let modalTitle = document.querySelector('#quickCalendarModal .modal-title');
                    if (modalTitle) modalTitle.innerHTML = `<i class="fas fa-calendar-alt mr-2 text-warning"></i> ${t('Gestión de Asignaciones')}`;

                    $('#quickCalendarModal').modal('show');
                    
                    setTimeout(() => {
                        if (window.quickCalendar) window.quickCalendar.destroy(); 
                        
                        window.quickCalendar = new UniversalCalendarManager('modal-calendar-container', {
                            context: 'obra',
                            id: obraId,
                            entityName: obraNombre,
                            mode: 'empresas',
                            embedded: true,
                        });
                        
                        window.quickCalendar.createGhostEventRange(startStr, endStr);
                    }, 200);
                }, 50);

            } else {
                callback(item); 
            }
        },

        onMoving: function (item, callback) {
            window.__planificadorDidDrag = true;
            hidePlanificadorOverlays();
            let hoy = moment().startOf('day').toDate();

            if (isPlanificadorGhost(item) || item.worker_id === 'NEW') {
                if (item.start < hoy) item.start = hoy;
                callback(item);
                return;
            }

            let oldItem = window.allEventsMaster.find(e => e.id === item.id);
            if (oldItem) {
                let oldStart = moment(oldItem.start).toDate();
                if (oldStart < hoy) {
                    if (item.start.getTime() !== oldStart.getTime()) {
                        item.start = oldStart; 
                    }
                } else {
                    if (item.start < hoy) {
                        item.start = hoy;
                    }
                }
            }
            callback(item);
        },

        onMove: function (item, callback) {
            if (isPlanificadorGhost(item) || item.worker_id === 'NEW') {
                callback(item);
                return;
            }

            let hoy = moment().startOf('day');
            let startReal = moment(item.start); 
            let endReal = moment(item.end).subtract(1, 'days');

            // Origen = último estado confirmado en BD (no el group contaminado por onMoving).
            let committed = (window.committedEventState && window.committedEventState[item.id]) || null;
            let oldItem = window.allEventsMaster.find(e => e.id === item.id);
            let oldGroup = committed
                ? committed.group
                : (oldItem ? oldItem.group : item.group);
            let oldStart = committed
                ? moment(committed.start)
                : (oldItem ? moment(oldItem.start) : startReal);
            let oldEnd = committed
                ? moment(committed.end).subtract(1, 'days')
                : (oldItem ? moment(oldItem.end).subtract(1, 'days') : endReal);

            if (endReal.isBefore(hoy)) {
                Swal.fire(t('Acción inválida'), t('La fecha de fin de la asignación debe ser al menos hoy.'), 'warning');
                callback(null);
                return;
            }

            let startStr = startReal.format('YYYY-MM-DD');
            let endStr = endReal.format('YYYY-MM-DD');
            let sameObra = String(oldGroup) === String(item.group);
            // Siempre check: si pisa otra obra debe salir el pop-up de conflicto
            // (pluri / quitar la otra / solo libres / cancelar). Nunca overwrite silencioso.
            let moveMode = 'check';

            pendingAction = { 
                worker_id: item.worker_id, 
                target_obra_id: item.group, 
                old_obra_id: oldGroup, 
                start_date: startStr, 
                end_date: endStr,
                original_start: oldStart.format('YYYY-MM-DD'),
                original_end: oldEnd.format('YYYY-MM-DD'),
                overwrite_mode: moveMode
            };
            
            pendingRevert = function() { callback(null); loadTimelineData(); };

            function commitMove() {
                // No confiar en el item local: recargar desde BD.
                callback(null);
                loadTimelineData();
            }

            if (!sameObra) {
                Swal.fire({ 
                    title: t('¿Trasladar a otra Obra?'),
                    text: `${t('Vas a reasignar al operario del')} ${moment(startStr).format('DD/MM')} ${t('al')} ${moment(endStr).format('DD/MM')}. ${t('Se quitará de la obra anterior en esas fechas.')}`, 
                    icon: 'question', 
                    showCancelButton: true, 
                    confirmButtonText: t('Sí, mover')
                }).then((result) => { 
                    if (result.isConfirmed) ejecutarAccionAPI(pendingRevert, commitMove); 
                    else callback(null); 
                });
            } else { 
                ejecutarAccionAPI(pendingRevert, commitMove); 
            }
        }
    };

    function formatEmpresaLabel(nombre) {
        if (!nombre || nombre === 'ZZ_Sin_Empresa') return t('Sin empresa');
        return nombre;
    }

    function setupPlanificadorItemTooltip() {
        const tooltipEl = document.getElementById('planificador-item-tooltip');
        if (!tooltipEl || !window.AppTimeline) return;

        function hideTooltip() {
            tooltipEl.classList.add('d-none');
            tooltipEl.setAttribute('aria-hidden', 'true');
        }

        function showTooltip(item, clientX, clientY) {
            if (!item || !item.title) return;
            if (['NEW', 'SYSTEM', 'REQUEST'].includes(String(item.worker_id))) return;
            if (isPlanificadorGhost(item)) return;
            const emp = formatEmpresaLabel(item.empresa_nombre);
            let extra = '';
            if (item.es_falta) {
                extra = '<span class="planificador-tt-falta"><i class="fas fa-user-slash"></i> '
                    + (item.tooltipText || (t('Falta') + ' — ' + t('debía acudir y no fichó')))
                    + '</span>';
            } else if (item.inercia) {
                extra = '<span class="planificador-tt-empresa"><i class="fas fa-ghost"></i> ' + t('Inercia') + '</span>';
            }
            tooltipEl.innerHTML =
                '<strong>' + item.title + '</strong>' +
                '<span class="planificador-tt-empresa"><i class="fas fa-building"></i> ' + emp + '</span>' +
                extra;
            tooltipEl.classList.remove('d-none');
            tooltipEl.setAttribute('aria-hidden', 'false');
            let x = clientX + 14;
            let y = clientY + 14;
            if (x + 200 > window.innerWidth) x -= 220;
            if (y + 60 > window.innerHeight) y -= 70;
            tooltipEl.style.left = x + 'px';
            tooltipEl.style.top = y + 'px';
        }

        window.AppTimeline.on('itemover', function(props) {
            if (!props.item || !props.event) return;
            const item = window.AppItems.get(props.item);
            showTooltip(item, props.event.clientX, props.event.clientY);
        });

        window.AppTimeline.on('itemout', hideTooltip);

        calendarDiv.addEventListener('mousemove', function(e) {
            if (tooltipEl.classList.contains('d-none')) return;
            let x = e.clientX + 14;
            let y = e.clientY + 14;
            if (x + 200 > window.innerWidth) x -= 220;
            if (y + 60 > window.innerHeight) y -= 70;
            tooltipEl.style.left = x + 'px';
            tooltipEl.style.top = y + 'px';
        });

        planificadorScrollRoot && planificadorScrollRoot.addEventListener('scroll', hideTooltip, { passive: true });
    }

    try {
        window.AppTimeline = new vis.Timeline(calendarDiv, window.AppItems, window.AppGroups, options);
    } catch (err) {
        options.locale = planifLang();
        window.AppTimeline = new vis.Timeline(calendarDiv, window.AppItems, window.AppGroups, options);
    }
    window.AppTimeline.setWindow(moment().subtract(1, 'weeks').toDate(), moment().add(3, 'months').toDate());
    setupPlanificadorItemTooltip();
    bindVisPanFallback();
    window.AppTimeline.on('changed', function () {
        if (planifViewPin) planifRestoreViewPin();
        planifAlignSameWorkerTops();
    });
    window.AppTimeline.on('rangechange', function () {
        if (planifViewPin) planifRestoreViewPin();
    });

    calendarDiv.addEventListener('mousedown', function (e) {
        if (e.target && e.target.closest && e.target.closest('.vis-item')) {
            hidePlanificadorOverlays();
        }
    }, true);

    window.AppTimeline.on('click', function(props) {
        let popover = document.getElementById('worker-popover');
        if (window.__planificadorDidDrag) {
            window.__planificadorDidDrag = false;
            if (popover) popover.classList.add('d-none');
            return;
        }
        if (props.event && (props.event.shiftKey || props.event.ctrlKey || props.event.metaKey)) {
            if (popover) popover.classList.add('d-none');
            return;
        }
        
        if (props.item && props.item !== 'phantom_new') {
            let item = window.AppItems.get(props.item);
            
            if (!item || item.worker_id === 'SYSTEM') return;
            if (isPlanificadorGhost(item)) {
                if (popover) popover.classList.add('d-none');
                return;
            } 
            
            window.currentSelectedItem = item; // <-- GUARDAMOS EL ITEM

            // ==========================================================
            // --- NUEVO: LÓGICA SI HACEMOS CLIC EN UNA SOLICITUD ---
            // ==========================================================
            if (item.worker_id === 'REQUEST') {
                // 1. Adaptamos la info visual del popover
                document.getElementById('wp-avatar').textContent = '⚠️';
                document.getElementById('wp-avatar').style.backgroundColor = item.color || '#f59e0b';
                
                document.getElementById('wp-name').textContent = item.title;
                document.getElementById('wp-name').href = `/admin/solicitudes/${item.solicitud_id}`;
                
                let compEl = document.getElementById('wp-company');
                compEl.textContent = t('Solicitud de Personal');
                compEl.href = '#';
                compEl.style.pointerEvents = 'none';
                compEl.className = 'text-muted';
                
                document.getElementById('wp-role').textContent = t('Haz clic en el botón inferior para gestionarla.');
                let ratingClear = document.getElementById('wp-rating');
                if (ratingClear) ratingClear.innerHTML = '';

                // 2. Ocultamos automáticamente los botones de "Desasignar" (¡SIN usar la palabra button!)
                let btnsDesasignar = popover.querySelectorAll('[onclick*="desasignarDesdePop"]');
                btnsDesasignar.forEach(b => b.style.display = 'none');
                
                // 3. Creamos o mostramos nuestro botón dedicado de "Ver Solicitud"
                let btnVerSol = document.getElementById('btn-ver-solicitud');
                if (!btnVerSol) {
                    btnVerSol = document.createElement('a');
                    btnVerSol.id = 'btn-ver-solicitud';
                    btnVerSol.className = 'btn btn-warning btn-sm btn-block mt-3 font-weight-bold text-white';
                    btnVerSol.innerHTML = '<i class="fas fa-external-link-alt mr-1"></i> ' + t('Ver Solicitud');
                    popover.appendChild(btnVerSol); // Lo inyectamos al final del popover
                }
                btnVerSol.href = `/admin/solicitudes/${item.solicitud_id}`;
                btnVerSol.style.display = 'block';
                
                // Ocultamos el botón del calendario universal si existe
                let btnVerCal = document.getElementById('btn-ver-calendario');
                if (btnVerCal) btnVerCal.style.display = 'none';
                var btnInercia = document.getElementById('btn-confirmar-inercia');
                if (btnInercia) btnInercia.classList.add('d-none');

            } else {
            // ==========================================================
            // --- LÓGICA SI HACEMOS CLIC EN UN OPERARIO NORMAL ---
            // ==========================================================
                let initials = item.title.substring(0, 2).toUpperCase();
                document.getElementById('wp-avatar').textContent = initials;
                document.getElementById('wp-avatar').style.backgroundColor = item.color || '#3b82f6';
                
                document.getElementById('wp-name').textContent = item.title;
                document.getElementById('wp-name').href = `/admin/worker_panel/${item.worker_id}`;
                
                let compEl = document.getElementById('wp-company');
                compEl.textContent = item.empresa_nombre || t('Sin Empresa');
                if (item.empresa_id && item.empresa_id > 0) {
                    compEl.href = `/admin/company_panel/${item.empresa_id}`;
                    compEl.style.pointerEvents = 'auto';
                    compEl.classList.add('text-primary');
                    compEl.classList.remove('text-muted');
                } else {
                    compEl.href = '#';
                    compEl.style.pointerEvents = 'none';
                    compEl.classList.remove('text-primary');
                    compEl.classList.add('text-muted');
                }
                
                let roleText = item.categoria || t('Sin categoría especificada');
                if (item.especialidad) roleText += ` (${item.especialidad})`;
                if (item.inercia) {
                    roleText = t('Sigue en esta obra (inercia)')
                        + ' · ' + t('Enter la convierte en asignación');
                }
                document.getElementById('wp-role').textContent = roleText;
                
               let ratingEl = document.getElementById('wp-rating');
                if (ratingEl) {
                // Comprobamos que nota exista de verdad (así permitimos el 0 y los números negativos)
                if (item.nota !== null && item.nota !== undefined && item.nota !== "") {
                    
                    // Le ponemos un "+" delante si es positivo para que quede clara la escala -3 a +3
                    let displayNota = item.nota > 0 ? "+" + item.nota : item.nota;
                    
                    // (Opcional) Damos color al texto: verde si > 0, rojo si < 0, oscuro si es 0
                    let colorClass = item.nota > 0 ? 'text-success' : (item.nota < 0 ? 'text-danger' : 'text-dark');
                    
                    ratingEl.innerHTML = `<strong class="${colorClass}">${displayNota}</strong> <span class="text-primary ml-1" style="font-size:0.75rem;">(${t('Ver notas')})</span>`;
                } else {
                    ratingEl.innerHTML = `<span class="text-muted">${t('Sin valoraciones')}</span>`;
                }
                ratingEl.href = `/admin/worker/${item.worker_id}/ratings_history`;
                }

                // 1. Ocultamos el botón de "Ver Solicitud" si estuviera visible
                let btnVerSol = document.getElementById('btn-ver-solicitud');
                if (btnVerSol) btnVerSol.style.display = 'none';

                // 2. Restauramos los botones de desasignar (solo si hay W)
                let btnsDesasignar = popover.querySelectorAll('[onclick*="desasignarDesdePop"]');
                btnsDesasignar.forEach(b => {
                    b.style.display = (window.PLANIFICADOR_CAN_EDIT === false) ? 'none' : '';
                });
                
                // 3. NUEVO: BOTÓN DE VER CALENDARIO UNIVERSAL
                let btnVerCal = document.getElementById('btn-ver-calendario');
                if (!btnVerCal) {
                    btnVerCal = document.createElement('a');
                    btnVerCal.id = 'btn-ver-calendario';
                    btnVerCal.className = 'btn btn-info btn-sm btn-block mt-2 font-weight-bold text-white shadow-sm';
                    btnVerCal.innerHTML = '<i class="fas fa-calendar-alt mr-1"></i> ' + t('Ver Calendario');
                    btnVerCal.style.cursor = 'pointer';
                    popover.appendChild(btnVerCal); 
                    
                    btnVerCal.addEventListener('click', function(e) {
                        e.preventDefault();
                        
                        document.getElementById('worker-popover').classList.add('d-none');

                        $('#quickCalendarModal').modal('show');
                        
                        setTimeout(() => {
                            if (window.quickCalendar) window.quickCalendar.destroy(); 
                            
                            window.quickCalendar = new UniversalCalendarManager('modal-calendar-container', {
                                context: 'worker',
                                id: parseInt(window.currentSelectedItem.worker_id, 10),
                                entityName: window.currentSelectedItem.title,
                                mode: 'obras',
                                embedded: true,
                                showFichajes: !!window.PLANIFICADOR_SHOW_FICHAJES,
                            });
                        }, 200);
                    });
                }
                btnVerCal.style.display = 'block';
                var btnInerciaOk = document.getElementById('btn-confirmar-inercia');
                if (btnInerciaOk) {
                    var canConfirm = window.PLANIFICADOR_CAN_EDIT !== false && !!item.inercia;
                    btnInerciaOk.classList.toggle('d-none', !canConfirm);
                }
            }

            // --- CÁLCULO DE POSICIÓN Y MOSTRAR POPOVER ---
            let x = props.event.clientX + 15;
            let y = props.event.clientY + 15;
            
            if (x + 280 > window.innerWidth) x -= 310;
            if (y + 160 > window.innerHeight) y -= 190;

            popover.style.left = x + 'px';
            popover.style.top = y + 'px';
            popover.classList.remove('d-none');
            return; 
        }

        popover.classList.add('d-none');
    });

    window.AppTimeline.on('doubleClick', function(props) {
        if (props.item && window.AppItems) {
            var clicked = window.AppItems.get(props.item);
            if (clicked && isPlanificadorGhost(clicked)) return;
            if (clicked && clicked.worker_id === 'NEW' && typeof options.onUpdate === 'function') {
                options.onUpdate(clicked, function () {});
                return;
            }
        }
        if (!props.item && props.group && props.time) {
            let clickedDate = moment(props.time).startOf('day');
            let hoy = moment().startOf('day');
            
            if (clickedDate.isBefore(hoy)) {
                Swal.fire(t('Atención'), t('Haz doble clic en un día a partir de hoy.'), 'info');
                return;
            }

            if (window.AppItems) {
                let existings = window.AppItems.get({ filter: function(i) { return i.worker_id === 'NEW'; } });
                window.AppItems.remove(existings);

                let newItem = {
                    id: 'phantom_new',
                    group: props.group,
                    content: `<i class="fas fa-plus-circle mr-1"></i> ${t('Arrastra y Doble Clic')}`,
                    start: clickedDate.toDate(),
                    end: clickedDate.clone().add(1, 'days').toDate(),
                    worker_id: 'NEW',
                    // Debajo del carril de solicitudes (R) y de operarios.
                    subgroup: 'N',
                    subgroupOrder: 1000,
                    className: 'phantom-item',
                    editable: (window.PLANIFICADOR_CAN_EDIT === false)
                        ? false
                        : { updateTime: true, updateGroup: true, remove: true }
                };
                window.AppItems.add(newItem);
                window.AppTimeline.setSelection('phantom_new');
                planifScheduleLaneLayout();
            }
        }
    });

    // --- LÓGICA DE CARGA DE DATOS ---
    function mapPlanifEvent(e) {
        var base = {
            id: e.id,
            start: e.start,
            end: e.end,
            worker_id: e.worker_id,
            solicitud_id: e.solicitud_id,
        };
        if (e.resourceId) base.group = e.resourceId;
        if (e.type === 'background') {
            base.type = e.type;
            base.content = e.content;
            base.className = e.className;
            base.style = e.color ? 'background-color: ' + e.color + ' !important;' : '';
        } else {
            base.title = e.title;
            base.style = e.style ? e.style : (e.color ? 'background-color: ' + e.color + ';' : '');
            base.color = e.color;
            base.empresa_nombre = e.empresa_nombre || 'ZZ_Sin_Empresa';
            base.empresa_id = e.empresa_id;
            base.categoria = e.categoria;
            base.especialidad = e.especialidad;
            base.nota = e.nota;
            if (e.inercia) {
                base.inercia = true;
                base.editable = false;
                base.className = (e.className ? e.className + ' ' : '') + 'inercia-item';
            }
            if (e.es_falta) {
                base.es_falta = true;
                base.className = (base.className ? base.className + ' ' : '') + 'falta-item';
                base.tooltipText = e.tooltipText || (t('Falta') + ' — ' + t('debía acudir y no fichó'));
            } else if (e.tooltipText) {
                base.tooltipText = e.tooltipText;
            }
            if (e.solicitud_id || e.worker_id === 'REQUEST') {
                base.className = (base.className ? base.className + ' ' : '') + 'solicitud-item';
                base.subgroup = 'R';
                base.subgroupOrder = -1;
            } else if (planifIsPackableWorker(e.worker_id)) {
                // Misma altura desde el primer pintado (hecho + fantasma).
                base.subgroup = 'W' + String(e.worker_id);
                base.subgroupOrder = 0;
            }
        }
        return base;
    }

    function rememberCommitted(ev) {
        if (!ev || ev.type === 'background') return;
        window.committedEventState[ev.id] = {
            group: ev.group,
            start: ev.start,
            end: ev.end,
            worker_id: ev.worker_id,
        };
    }

    function applyPlanificadorPayload(data, evData) {
        if (!data.length) {
            window.allGroupsMaster = [];
            window.AppGroups.clear();
            window.allEventsMaster = [];
            window.renderItems();
            return;
        }

        var activeGroupIds = new Set();
        evData.forEach(function (e) {
            var groupId = e.resourceId || e.group;
            if (groupId && e.type !== 'background') {
                activeGroupIds.add(String(groupId));
            }
        });

        data.sort(function (a, b) {
            var aActive = activeGroupIds.has(String(a.id)) ? 1 : 0;
            var bActive = activeGroupIds.has(String(b.id)) ? 1 : 0;
            if (aActive !== bActive) return bActive - aActive;
            var titleA = a.title || '';
            var titleB = b.title || '';
            return titleA.localeCompare(titleB);
        });

        window.allGroupsMaster = data;
        window.AppGroups.clear();
        window.AppGroups.add(data.map(function (g, index) {
            return {
                id: g.id,
                title: g.title,
                codigo: g.codigo,
                fecha_fin: g.fecha_fin,
                fecha_inicio: g.fecha_inicio || '',
                fecha_fin_iso: g.fecha_fin_iso || '',
                orden: index,
                // R: solicitudes arriba; N: borrador nueva asignación abajo;
                // W{id}: operarios (hecho+fantasma a la misma altura).
                subgroupStack: { R: true, N: true },
                subgroupOrder: 'subgroupOrder',
            };
        }));

        window.allEventsMaster = (evData || []).map(mapPlanifEvent);
        window.committedEventState = {};
        window.allEventsMaster.forEach(rememberCommitted);
        window.renderItems();
        // Misma regla que «Ordenar vista»: activas en la ventana visible arriba.
        setTimeout(function () {
            if (typeof window.reordenarPorVentanaVisible === 'function') {
                window.reordenarPorVentanaVisible({ silent: true });
            }
            planifScheduleLaneLayout();
        }, 0);
    }

    function planifFilterParams() {
        var params = new URLSearchParams();
        var obrasIds = $('#obrasSelect').val() || [];
        var jefeId = $('#jefeSelect').val() || null;
        var workerIds = $('#workersSelect').val() || [];
        var totalEmpresas = $('.chk-empresa-filter').length;
        var checkedEmpresas = $('.chk-empresa-filter:checked').length;
        var companyIds = [];
        if (checkedEmpresas < totalEmpresas) {
            $('.chk-empresa-filter:checked').each(function() {
                companyIds.push($(this).val());
            });
            if (companyIds.length === 0) companyIds = [-1];
        }
        if (jefeId) params.append('jefe_id', jefeId);
        obrasIds.forEach(function (id) { params.append('obra_ids[]', id); });
        companyIds.forEach(function (id) { params.append('company_ids[]', id); });
        workerIds.forEach(function (id) { params.append('worker_ids[]', id); });
        return params;
    }

    function mergePlanificadorResources(data) {
        if (!data || !data.length) return false;
        var have = {};
        (window.allGroupsMaster || []).forEach(function (g) {
            have[String(g.id)] = true;
        });
        var added = [];
        data.forEach(function (g) {
            if (!have[String(g.id)]) added.push(g);
        });
        if (!added.length) return false;
        var orden0 = window.allGroupsMaster.length;
        added.forEach(function (g, index) {
            window.allGroupsMaster.push(g);
            window.AppGroups.add({
                id: g.id,
                title: g.title,
                codigo: g.codigo,
                fecha_fin: g.fecha_fin,
                fecha_inicio: g.fecha_inicio || '',
                fecha_fin_iso: g.fecha_fin_iso || '',
                orden: orden0 + index,
                subgroupStack: { R: true, N: true },
                subgroupOrder: 'subgroupOrder',
            });
        });
        return true;
    }

    function mergePlanificadorEvents(evData) {
        var mapped = (evData || []).map(mapPlanifEvent);
        var have = {};
        window.allEventsMaster.forEach(function (e) {
            have[String(e.id)] = true;
        });
        var fresh = mapped.filter(function (e) { return !have[String(e.id)]; });
        if (!fresh.length) return false;
        window.allEventsMaster = window.allEventsMaster.concat(fresh);
        fresh.forEach(rememberCommitted);
        var toShow = fresh.filter(function (ev) {
            if (window.hiddenGroups.has(String(ev.group))) return false;
            if (ev.inercia && window.planificadorHideInercia) return false;
            return true;
        });
        if (toShow.length && window.AppItems) window.AppItems.add(toShow);
        planifScheduleLaneLayout();
        return true;
    }

    window._planifLoaded = null;
    window._planifReloadQueued = false;
    window._planifExtending = false;

    function planifInitialRange() {
        return {
            start: moment().subtract(12, 'months').startOf('day'),
            end: moment().add(6, 'months').endOf('day'),
        };
    }

    function planifFetchSlice(start, end, withInercia) {
        var params = planifFilterParams();
        params.append('start', start.toISOString());
        params.append('end', end.toISOString());
        params.append('inercia', withInercia ? '1' : '0');
        params.append('compact', '0');
        var qs = params.toString();
        return Promise.all([
            fetch('/admin/api/planificador/resources?' + qs).then(function (r) { return r.json(); }),
            fetch('/admin/api/planificador/events?' + qs).then(function (r) { return r.json(); }),
        ]);
    }

    function planifExtendIfNeeded() {
        if (window.planificadorLoading || window._planifExtending) return;
        var loaded = window._planifLoaded;
        if (!loaded || !window.AppTimeline) return;
        var w;
        try { w = window.AppTimeline.getWindow(); } catch (errW) { return; }
        var visStart = moment(w.start).subtract(1, 'month').startOf('day');
        var visEnd = moment(w.end).add(1, 'month').endOf('day');
        var needPast = visStart.isBefore(loaded.start);
        var needFuture = visEnd.isAfter(loaded.end);
        if (!needPast && !needFuture) return;

        var start;
        var end;
        var goingPast = needPast;
        if (goingPast) {
            end = loaded.start.clone().subtract(1, 'days').endOf('day');
            start = visStart.clone();
            if (start.isBefore(loaded.start.clone().subtract(5, 'years'))) {
                start = loaded.start.clone().subtract(5, 'years').startOf('day');
            }
        } else {
            start = loaded.end.clone().add(1, 'days').startOf('day');
            end = visEnd.clone();
            if (end.isAfter(loaded.end.clone().add(5, 'years'))) {
                end = loaded.end.clone().add(5, 'years').endOf('day');
            }
        }
        if (!start.isBefore(end)) return;

        window._planifExtending = true;
        planifFetchSlice(start, end, false).then(function (results) {
            var addedGroups = mergePlanificadorResources(results[0] || []);
            mergePlanificadorEvents(results[1] || []);
            if (goingPast) loaded.start = start.clone();
            else loaded.end = end.clone();
            if (addedGroups) {
                setTimeout(function () {
                    planifRelayoutLanes();
                    fitPlanificadorTimelineToGroups();
                    if (planifViewPin) planifRestoreViewPin();
                }, 40);
            } else {
                planifScheduleLaneLayout();
            }
            if (planifViewPin) planifKeepViewPin(700);
        }).catch(function () {
            if (goingPast) loaded.start = start.clone();
            else loaded.end = end.clone();
        }).finally(function () {
            window._planifExtending = false;
            planifExtendIfNeeded();
        });
    }

    window.loadTimelineData = function() {
        if (window.planificadorLoading) {
            window._planifReloadQueued = true;
            return;
        }
        window.planificadorLoading = true;
        var range = planifInitialRange();
        var wantInercia = !window.planificadorHideInercia;
        planifFetchSlice(range.start, range.end, wantInercia).then(function (results) {
            window._planifLoaded = {
                start: range.start.clone(),
                end: range.end.clone(),
                compact: false,
                inercia: wantInercia,
            };
            applyPlanificadorPayload(results[0], results[1]);
        }).catch(function () {
            window.allGroupsMaster = [];
            window.AppGroups.clear();
            window.allEventsMaster = [];
            window.renderItems();
        }).finally(function () {
            window.planificadorLoading = false;
            if (window._planifReloadQueued) {
                window._planifReloadQueued = false;
                window.loadTimelineData();
            }
        });
    };

  function setupSelect2ChipRemoveAnimation($select) {
    $select.on('select2:unselecting', function (e) {
      const text = e.params.args.data.text;
      const $chip = $select.next('.select2-container').find('.select2-selection__choice').filter(function () {
        return $(this).attr('title') === text;
      });
      if ($chip.length) $chip.addClass('select2-chip-removing');
    });
  }

    if ($('#workersSelect').length) {
        let $workersSelect = $('#workersSelect');
        $workersSelect.select2({
            placeholder: t('Buscar operarios…'),
            allowClear: true,
            width: '100%',
            minimumInputLength: 0,
            dropdownParent: $(document.body),
            dropdownCssClass: 'planificador-select2-dropdown admin-select2-dropdown planificador-workers-dropdown',
            ajax: {
                url: '/admin/api/planificador/search_workers',
                dataType: 'json',
                delay: 250,
                data: function(params) {
                    return { q: params.term || '', plain: '1' };
                },
                processResults: function(data) {
                    return { results: data.results || [] };
                },
            },
            templateResult: function (item) {
                if (!item || item.loading) return item && item.text;
                if (item.children) return item.text;
                var tags = item.etiquetas || [];
                if (!tags.length) return item.text;
                var chipFn = window.spEtiquetaChipHtml || function (n) { return n; };
                var $wrap = $('<div class="univ-worker-option"></div>');
                $wrap.append($('<div class="univ-worker-option-name"></div>').text(item.text || ''));
                var $tags = $('<div class="univ-worker-option-tags"></div>');
                tags.forEach(function (e) {
                    $tags.append($(chipFn(e.nombre || '', e.color || '')));
                });
                $wrap.append($tags);
                return $wrap;
            },
            templateSelection: function (item) {
                if (!item || !item.id) return item && item.text;
                var tags = item.etiquetas || [];
                if (!tags.length) return item.text;
                var names = tags.map(function (e) { return e.nombre || ''; }).filter(Boolean).join(', ');
                return names ? (item.text + ' · ' + names) : item.text;
            },
            escapeMarkup: function (m) { return m; },
        });
        setupSelect2ChipRemoveAnimation($workersSelect);
        if (window.SignaPlanSelect2) {
            window.SignaPlanSelect2.bindFixedDropdown($workersSelect, [planificadorScrollRoot, document.querySelector('.admin-main')].filter(Boolean));
        }
        $workersSelect.on('change', function() {
            loadTimelineData();
        });
    }

    if ($('#obrasSelect').length) {
        let $obrasSelect = $('#obrasSelect');
        let $jefeSelect = $('#jefeSelect');
        
        $obrasSelect.select2({
            placeholder: t('Buscar obras…'),
            allowClear: true,
            width: '100%',
            dropdownParent: $(document.body),
            dropdownCssClass: 'planificador-select2-dropdown admin-select2-dropdown',
        });
        setupSelect2ChipRemoveAnimation($obrasSelect);
        if (window.SignaPlanSelect2) {
            window.SignaPlanSelect2.bindFixedDropdown($obrasSelect, [planificadorScrollRoot, document.querySelector('.admin-main')].filter(Boolean));
        }

        if ($jefeSelect.is(':visible') && $jefeSelect.find('option').length > 1) {
            $jefeSelect.select2({
                placeholder: t('Todos los jefes'),
                allowClear: true,
                width: '100%',
                minimumResultsForSearch: 6,
                dropdownParent: $(document.body),
                dropdownCssClass: 'planificador-select2-dropdown admin-select2-dropdown planificador-jefe-dropdown',
            });
            if (window.SignaPlanSelect2) {
                window.SignaPlanSelect2.bindFixedDropdown($jefeSelect, [planificadorScrollRoot, document.querySelector('.admin-main')].filter(Boolean));
            }
        }

        let isUpdating = false;

        $jefeSelect.on('change', function() {
            if (isUpdating) return;
            isUpdating = true;
            $obrasSelect.val(null).trigger('change.select2');
            loadTimelineData();
            isUpdating = false;
        });

        $obrasSelect.on('change', function () {
            if (isUpdating) return;
            isUpdating = true;
            if ($(this).val() && $(this).val().length > 0) {
                $jefeSelect.val(null).trigger('change.select2');
            }
            loadTimelineData();
            isUpdating = false;
        });

        const urlJefeId = new URLSearchParams(window.location.search).get('jefe_id');
        if (urlJefeId && $jefeSelect.length) {
            isUpdating = true;
            $jefeSelect.val(urlJefeId).trigger('change.select2');
            loadTimelineData();
            isUpdating = false;
        }

        // ==========================================
        // LÓGICA DEL DROPDOWN (A prueba de fallos sin Popper.js)
        // ==========================================
        
        // 1. Abrir y cerrar el menú manualmente al hacer clic en el botón
        const $empresasBtn = $('#dropdownEmpresas');
        const $empresasMenu = $empresasBtn.next('.dropdown-menu');
        let empresasMenuHome = null;

        function positionEmpresasMenu() {
            if (!$empresasMenu.hasClass('show')) return;
            const rect = $empresasBtn[0].getBoundingClientRect();
            $empresasMenu.css({
                position: 'fixed',
                top: (rect.bottom + 6) + 'px',
                left: rect.left + 'px',
                minWidth: Math.max(rect.width, 288) + 'px',
                zIndex: 10050,
            });
        }

        $empresasBtn.on('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            const willOpen = !$empresasMenu.hasClass('show');
            $('.dropdown-menu').removeClass('show');
            if (willOpen) {
                if (!empresasMenuHome) {
                    empresasMenuHome = $empresasMenu.parent();
                }
                $('body').append($empresasMenu);
                $empresasMenu.addClass('show');
                positionEmpresasMenu();
            } else {
                $empresasMenu.removeClass('show');
                if (empresasMenuHome) empresasMenuHome.append($empresasMenu);
            }
        });

        $(window).on('resize', function() {
            if ($empresasMenu.hasClass('show')) positionEmpresasMenu();
        });
        if (planificadorScrollRoot) {
            planificadorScrollRoot.addEventListener('scroll', function() {
                if ($empresasMenu.hasClass('show')) positionEmpresasMenu();
            }, { passive: true });
        }

        // 2. Cerrar el menú si hacemos clic en cualquier otro lado de la pantalla
        $(document).on('click', function(e) {
            if (!$(e.target).closest('#dropdownEmpresas').length && !$(e.target).closest('.planificador-empresas-menu').length) {
                if ($empresasMenu.hasClass('show')) {
                    $empresasMenu.removeClass('show');
                    if (empresasMenuHome) empresasMenuHome.append($empresasMenu);
                }
            }
            if (!$(e.target).closest('.dropdown').length) {
                $('.dropdown-menu').not('.planificador-empresas-menu').removeClass('show');
            }
        });

        // 3. Evitar que se cierre al hacer clic dentro del menú de empresas
        $empresasMenu.on('click', function(e) {
            e.stopPropagation();
        });

        // 4. Actualizar el texto del botón según lo marcado
        function updateEmpresasBtnText() {
            let total = $('.chk-empresa-filter').length;
            let checked = $('.chk-empresa-filter:checked').length;
            let $btnText = $('#empresas-btn-text');
            
            if (checked === total) {
                $btnText.text(t('Todas las empresas'));
            } else if (checked === 0) {
                $btnText.text(t('Ninguna seleccionada'));
            } else if (checked === 1) {
                let name = $('.chk-empresa-filter:checked').next('label').text().trim().replace('⭐', '');
                $btnText.text(name);
            } else {
                $btnText.text(checked + ' ' + t('seleccionadas'));
            }
        }

        // 5. Click en "Seleccionar Todas"
        $('#chk-empresa-todas').on('change', function() {
            let isChecked = $(this).is(':checked');
            $('.chk-empresa-filter').prop('checked', isChecked);
            updateEmpresasBtnText();
            if (!isUpdating) loadTimelineData();
        });

        // 6. Click en cualquier empresa individual
        $('.chk-empresa-filter').on('change', function() {
            let total = $('.chk-empresa-filter').length;
            let checked = $('.chk-empresa-filter:checked').length;
            
            $('#chk-empresa-todas').prop('checked', total === checked);
            
            updateEmpresasBtnText();
            if (!isUpdating) loadTimelineData();
        });

   
    }

    loadTimelineData();


    function ejecutarAccionAPI(revertFunc, successCallback) {
        if (!pendingAction) return;
        if (!pendingAction.overwrite_mode) pendingAction.overwrite_mode = 'check';
        pendingAction.check_conflicts = true;

        $.ajax({
            url: "/api/v6/planificador/action",
            type: "POST",
            contentType: "application/json",
            data: JSON.stringify(pendingAction),
            success: function(data) {
                if (data.success) {
                    // No-op del servidor: la UI NO debe “confirmar” el drag.
                    if (data.noop || data.unchanged) {
                        Swal.fire({
                            toast: true,
                            position: 'top-end',
                            icon: 'info',
                            title: data.message || t('Sin cambios'),
                            showConfirmButton: false,
                            timer: 2000,
                        });
                        var continueOnNoop = !!(pendingAction && pendingAction.continue_on_noop);
                        pendingAction = null;
                        pendingRevert = null;
                        if (continueOnNoop) {
                            if (successCallback) successCallback();
                        } else if (revertFunc) {
                            revertFunc();
                        }
                        return;
                    }
                    Swal.fire({toast: true, position: 'top-end', icon: 'success', title: data.message || t('Guardado'), showConfirmButton: false, timer: 1500});
                    pendingAction = null; 
                    pendingRevert = null;
                    if (successCallback) successCallback();
                } else if (data.conflict) {
                    // LLAMADA A LA FUNCIÓN GLOBAL: Código limpio
                    window.resolverConflictoAsignacion(data, pendingAction, 
                        (nuevoPayload) => { pendingAction = nuevoPayload; ejecutarAccionAPI(revertFunc, successCallback); }, 
                        revertFunc
                    );
                } else {
                    Swal.fire(t('Error'), data.error || data.message, 'error');
                    if (revertFunc) revertFunc();
                }
            },
            error: function(xhr) {
                Swal.fire(t('Error'), t('Error de conexión'), 'error');
                if (revertFunc) revertFunc();
            }
        });
    }

    // CORREGIDO: Eliminamos la función duplicada
    window.resolveConflicto = function(mode) { 
        pendingAction.overwrite_mode = mode;
        pendingAction.conflict_resolved = true;
        $('#modalConflicto').modal('hide'); 
        ejecutarAccionAPI(null, loadTimelineData); 
    };
    
    $('#modalConflicto').on('hidden.bs.modal', function () { 
        if (pendingRevert) { pendingRevert(); pendingRevert = null; } 
    });
    
    function getCookie(name) { 
        let value = "; " + document.cookie; 
        let parts = value.split("; " + name + "="); 
        if (parts.length === 2) return parts.pop().split(";").shift(); 
        return ""; 
    }

    window.addEventListener('scroll', function() {
        let popover = document.getElementById('worker-popover');
        if (popover && !popover.classList.contains('d-none')) { popover.classList.add('d-none'); }
    }, { capture: true, passive: true });

    var planifExtendTimer = null;
    window.AppTimeline.on('rangechanged', function() {
        let popover = document.getElementById('worker-popover');
        if (popover && !popover.classList.contains('d-none')) { popover.classList.add('d-none'); }
        if (planifExtendTimer) clearTimeout(planifExtendTimer);
        planifExtendTimer = setTimeout(function () {
            planifRelayoutLanes();
            fitPlanificadorTimelineToGroups();
            if (planifViewPin) planifRestoreViewPin();
            planifExtendIfNeeded();
        }, 220);
    });

    /**
     * Oculta obras cuya fecha de fin ya quedó fuera de la ventana visible
     * (y las que aún no han empezado). Al ir hacia atrás en el tiempo vuelven a salir.
     */
    window.filtrarObrasPorVentana = function () {
        if (!window.AppTimeline || !window.allGroupsMaster || !window.AppGroups) return;
        if (!window.allGroupsMaster.length) return;

        let windowRange = window.AppTimeline.getWindow();
        let vs = moment(windowRange.start).startOf('day');
        let ve = moment(windowRange.end).startOf('day');

        let filtered = window.allGroupsMaster.filter(function (g) {
            let fi = g.fecha_inicio ? moment(g.fecha_inicio, 'YYYY-MM-DD') : null;
            let ff = g.fecha_fin_iso
                ? moment(g.fecha_fin_iso, 'YYYY-MM-DD')
                : (g.fecha_fin ? moment(g.fecha_fin, 'DD/MM/YY') : null);
            if (ff && ff.isValid() && ff.isBefore(vs, 'day')) return false;
            if (fi && fi.isValid() && fi.isAfter(ve, 'day')) return false;
            return true;
        });

        let wantIds = {};
        filtered.forEach(function (g, index) {
            wantIds[String(g.id)] = true;
            let existing = window.AppGroups.get(g.id);
            if (existing) {
                window.AppGroups.update({
                    id: g.id,
                    orden: index,
                    fecha_inicio: g.fecha_inicio || '',
                    fecha_fin_iso: g.fecha_fin_iso || '',
                    fecha_fin: g.fecha_fin,
                });
            } else {
                window.AppGroups.add({
                    id: g.id,
                    title: g.title,
                    codigo: g.codigo,
                    fecha_fin: g.fecha_fin,
                    fecha_inicio: g.fecha_inicio || '',
                    fecha_fin_iso: g.fecha_fin_iso || '',
                    orden: index,
                });
            }
        });

        (window.AppGroups.getIds() || []).forEach(function (id) {
            if (!wantIds[String(id)]) {
                try { window.AppGroups.remove(id); } catch (e) { /* ignore */ }
            }
        });
    };

    // Copiar / pegar, Esc, Enter, y Suprimir sobre el bloque seleccionado
    document.addEventListener('keydown', function (e) {
        if (planifIsTypingTarget(e.target)) return;
        if (typeof Swal !== 'undefined' && Swal.isVisible && Swal.isVisible()) return;
        const calModal = document.getElementById('quickCalendarModal');
        if (calModal && calModal.classList.contains('show')) return;
        const calPanel = document.getElementById('modal-calendar-container-bottom-panel');
        if (calPanel && calPanel.style.display !== 'none') return;

        var isMod = e.ctrlKey || e.metaKey;
        if (isMod && (e.key === 'c' || e.key === 'C')) {
            var selectedText = window.getSelection ? String(window.getSelection()) : '';
            if (selectedText) return;
            e.preventDefault();
            planifCopySelection();
            return;
        }
        if (isMod && (e.key === 'v' || e.key === 'V')) {
            e.preventDefault();
            planifPasteClipboard();
            return;
        }
        if (e.key === 'Escape') {
            if (collectPlanifGhosts().length) {
                e.preventDefault();
                planifClearGhosts();
                return;
            }
            planifSelectIds([]);
            hidePlanificadorOverlays();
            return;
        }
        if (e.key === 'Enter') {
            if (collectPlanifGhosts().length) {
                e.preventDefault();
                planifConfirmGhosts();
                return;
            }
            var inercias = planifGetSelectedInercia();
            if (inercias.length) {
                e.preventDefault();
                planifConfirmInercia(inercias);
                return;
            }
        }

        if (e.key !== 'Delete' && e.key !== 'Backspace') return;
        if (window.PLANIFICADOR_CAN_EDIT === false) return;

        var selectedGhosts = [];
        try {
            var sel = (window.AppTimeline && window.AppTimeline.getSelection()) || [];
            sel.forEach(function (id) {
                var it = window.AppItems && window.AppItems.get(id);
                if (isPlanificadorGhost(it)) selectedGhosts.push(it.id);
            });
        } catch (errDel) { selectedGhosts = []; }
        if (!selectedGhosts.length && window.currentSelectedItem && isPlanificadorGhost(window.currentSelectedItem)) {
            selectedGhosts.push(window.currentSelectedItem.id);
        }
        if (selectedGhosts.length) {
            e.preventDefault();
            if (window.AppItems) window.AppItems.remove(selectedGhosts);
            planifUpdateGhostBar();
            return;
        }

        var toUnassign = planifGetSelectedCopyables();
        if (!toUnassign.length) return;
        e.preventDefault();
        planifUnassignSelection(toUnassign);
    });

    // --- NUEVO: FUNCIÓN PARA DESASIGNAR DIRECTAMENTE DESDE EL POPOVER ---
    window.desasignarDesdePop = function(mode) {
        if (window.PLANIFICADOR_CAN_EDIT === false) {
            if (typeof Swal !== 'undefined') {
                Swal.fire(t('Sin permiso'), t('No tienes permisos de escritura en el planificador.'), 'warning');
            }
            return;
        }
        if (!window.currentSelectedItem) return;

        let item = window.currentSelectedItem;
        let workerId = item.worker_id;
        let obraId = item.group; 
        
        let startDate = moment(item.start);
        let endDate = moment(item.end).subtract(1, 'days');
        
        // LA CLAVE: Definimos "HOY" para el motor de JavaScript
        let hoy = moment().startOf('day'); 
        
        if (mode === 'periodo') {
            // 1. Si TODO el bloque está en el pasado, lo bloqueamos de raíz
            if (endDate.isBefore(hoy)) {
                Swal.fire(t('Histórico Protegido'), t('Este bloque pertenece íntegramente al pasado y no se puede borrar.'), 'info');
                return;
            }

            // 2. Si empezó en el pasado pero pisa el presente, "recortamos" el inicio para que empiece hoy
            let startToErase = startDate.isBefore(hoy) ? hoy.clone() : startDate.clone();

            let dates = [];
            let current = startToErase.clone();
            while (current.isSameOrBefore(endDate)) {
                dates.push(current.format('YYYY-MM-DD'));
                current.add(1, 'days');
            }
            if (dates.length === 0) return;

            // Igual que baja definitiva: quitar el panel antes del confirm (si no, se queda colgado).
            hidePlanificadorOverlays();

            // 3. Avisamos visualmente de que le estamos salvando el histórico
            let msjExtra = startDate.isBefore(hoy) 
                ? `<br><br><small class="text-info"><i class="fas fa-info-circle"></i> ${t('Se conservará el histórico de trabajo desde el')} ${startDate.format('DD/MM')} ${t('hasta ayer.')}</small>` 
                : '';
            
            lanzarConfirmacionBaja(workerId, obraId, dates, `${t('Se van a eliminar')} ${dates.length} ${t('días de asignación.')}` + msjExtra, '');
            
        } else if (mode === 'futuro') {
            let maxEnd = endDate.clone();
            window.allEventsMaster.forEach(e => {
                if (e.worker_id === workerId && e.group === obraId) {
                    let eEnd = moment(e.end).subtract(1, 'days');
                    if (eEnd.isAfter(maxEnd)) maxEnd = eEnd;
                }
            });

            if (maxEnd.isBefore(hoy)) {
                Swal.fire(t('Atención'), t('Este trabajador no tiene asignaciones futuras en esta obra. No hay nada que dar de baja.'), 'info');
                return;
            }

            hidePlanificadorOverlays();

            let hoyStr = hoy.format('YYYY-MM-DD');
            
            Swal.fire({
                title: t('Seleccionar Fecha de Baja'),
                html: `
                    <p class="mb-3 text-muted small">${t('Elige a partir de qué día (incluido) quieres eliminar las asignaciones futuras.')}</p>
                    <input type="date" id="input-fecha-baja" class="form-control text-center font-weight-bold" value="${hoyStr}" min="${hoyStr}">
                    <label class="d-block text-left text-muted small mt-3 mb-1" for="input-notas-baja">${t('Notas / comentario')}</label>
                    <textarea id="input-notas-baja" class="form-control" rows="2" maxlength="500"
                              placeholder="${t('Opcional. Si la baja genera una solicitud, este texto irá en la solicitud.')}"></textarea>
                `,
                icon: 'question',
                showCancelButton: true,
                confirmButtonColor: '#d33',
                cancelButtonColor: '#3085d6',
                confirmButtonText: t('Continuar'),
                cancelButtonText: t('Cancelar'),
                preConfirm: () => {
                    let val = document.getElementById('input-fecha-baja').value;
                    if (!val) {
                        Swal.showValidationMessage(t('Debes seleccionar una fecha válida'));
                        return false;
                    } else if (moment(val).startOf('day').isBefore(hoy)) {
                        Swal.showValidationMessage(t('No puedes dar de baja en una fecha pasada'));
                        return false;
                    }
                    let notasEl = document.getElementById('input-notas-baja');
                    return {
                        fecha: val,
                        notas: notasEl ? (notasEl.value || '').trim() : ''
                    };
                }
            }).then((result) => {
                if (result.isConfirmed) {
                    let selectedDate = moment(result.value.fecha).startOf('day');
                    let notasBaja = result.value.notas || '';
                    
                    if (selectedDate.isAfter(maxEnd)) {
                        Swal.fire(t('Aviso'), t('La fecha seleccionada es posterior al último día que tiene asignado. No hay nada que borrar.'), 'info');
                        return;
                    }

                    let dates = [];
                    let current = selectedDate.clone();
                    while (current.isSameOrBefore(maxEnd)) {
                        dates.push(current.format('YYYY-MM-DD'));
                        current.add(1, 'days');
                    }

                    lanzarConfirmacionBaja(
                        workerId, obraId, dates,
                        `${t('Se van a eliminar')} ${dates.length} ${t('días de asignación a partir del')} ${selectedDate.format('DD/MM/YYYY')}.`,
                        notasBaja
                    );
                }
            });
        }
    };

    // Función auxiliar para no repetir código de borrado
    function lanzarConfirmacionBaja(workerId, obraId, dates, mensajeTexto, notas) {
        hidePlanificadorOverlays();
        Swal.fire({
            title: t('¿Confirmar Desasignación?'),
            html: mensajeTexto + ' ' + t('Esta acción es inmediata.'),
            icon: 'warning',
            showCancelButton: true,
            confirmButtonColor: '#d33',
            cancelButtonColor: '#3085d6',
            confirmButtonText: t('Sí, desasignar'),
            cancelButtonText: t('Cancelar')
        }).then((result) => {
            if (result.isConfirmed) {
                hidePlanificadorOverlays();
                window.currentSelectedItem = null;

                fetch('/api/v6/unassign_worker', { // URL NUEVA UNIFICADA
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrf_token') },
                    body: JSON.stringify({
                        worker_id: workerId,
                        obra_id: obraId,
                        dates: dates,
                        mode: 'selected',
                        notas: notas || ''
                    })
                })
                .then(response => response.json())
                .then(data => {
                    hidePlanificadorOverlays();
                    window.currentSelectedItem = null;
                    if (data.success) {
                        Swal.fire(t('Completado'), data.message, 'success');
                        window.loadTimelineData(); 
                    } else {
                        Swal.fire(t('Error'), data.message || t('Ocurrió un error'), 'error');
                    }
                })
                .catch(error => {
                    console.error('Error:', error);
                    hidePlanificadorOverlays();
                    Swal.fire(t('Error'), t('Fallo de conexión.'), 'error');
                });
            }
        });
    }
    window.reordenarPorVentanaVisible = function(opts) {
        opts = opts || {};
        if (!window.AppTimeline || !window.allGroupsMaster || !window.allEventsMaster) return;

        // 1. Obtener la ventana de fechas que el usuario está viendo en pantalla
        let windowRange = window.AppTimeline.getWindow();
        let visibleStart = moment(windowRange.start);
        let visibleEnd = moment(windowRange.end);

        // 2. Comprobar qué obras tienen trabajadores en esta ventana específica
        let activeGroupIds = new Set();
        window.allEventsMaster.forEach(e => {
            let groupId = e.resourceId || e.group;
            
            // Ignorar eventos de fondo como los festivos y barreras rojas de fin de obra
            if (groupId && e.type !== 'background') {
                let evStart = moment(e.start);
                // Restamos 1 día a la fecha de fin porque vis.js/Fullcalendar trata el fin como exclusivo (00:00 del día siguiente)
                let evEnd = e.end ? moment(e.end).subtract(1, 'days') : evStart.clone();

                // Lógica de solapamiento: empieza antes de que acabe la pantalla y acaba después de que empiece la pantalla
                if (evStart.isSameOrBefore(visibleEnd) && evEnd.isSameOrAfter(visibleStart)) {
                    activeGroupIds.add(String(groupId));
                }
            }
        });

        // 3. Reordenar nuestro array maestro (las obras activas en pantalla suben)
        window.allGroupsMaster.sort((a, b) => {
            let aActive = activeGroupIds.has(String(a.id)) ? 1 : 0;
            let bActive = activeGroupIds.has(String(b.id)) ? 1 : 0;

            if (aActive !== bActive) {
                return bActive - aActive; 
            }
            // Desempate por orden alfabético
            let titleA = a.title || "";
            let titleB = b.title || "";
            return titleA.localeCompare(titleB);
        });

        // 4. Actualizar los grupos visualmente cambiando su atributo 'orden'
        let updatedGroups = window.allGroupsMaster.map((g, index) => {
            return {
                id: g.id,
                orden: index 
            };
        });

        window.AppGroups.update(updatedGroups);

        // 5. Toast solo si el usuario pulsa el botón (no en carga automática)
        if (!opts.silent) {
            Swal.fire({
                toast: true,
                position: 'top-end',
                icon: 'success',
                title: t('Vista ordenada'),
                showConfirmButton: false,
                timer: 1500
            });
        }
    };
});