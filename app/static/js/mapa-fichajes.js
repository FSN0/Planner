/* Mapa consultivo de fichajes por obra (solo entradas con GPS). */
window.MapaFichajes = (function () {
    'use strict';

    var cfg = {};
    var map = null;
    var capaObras = null;
    var capaFichajes = null;
    var capaRadio = null;
    var obrasData = { obras: [], sin_ubicacion: [], radio_metros: 150 };
    var obraSeleccionada = null;
    var presetActivo = 'today';
    var marcadoresFichaje = {};

    function hoyIso() {
        return new Date().toISOString().slice(0, 10);
    }

    function rangoDesdePreset(preset) {
        var hasta = hoyIso();
        var d = new Date(hasta + 'T12:00:00');
        if (preset === 'today') {
            return { desde: hasta, hasta: hasta };
        }
        if (preset === '7' || preset === '30') {
            d.setDate(d.getDate() - (parseInt(preset, 10) - 1));
            return { desde: d.toISOString().slice(0, 10), hasta: hasta };
        }
        var desdeEl = document.getElementById('mapaDesde');
        var hastaEl = document.getElementById('mapaHasta');
        return {
            desde: (desdeEl && desdeEl.value) || hasta,
            hasta: (hastaEl && hastaEl.value) || hasta,
        };
    }

    function colorPunto(estado) {
        if (estado === 'coincide') return '#16a34a';
        if (estado === 'dudosa') return '#ea580c';
        return '#64748b';
    }

    function etiquetaEstado(estado) {
        if (estado === 'coincide') return cfg.labels.enRadio;
        if (estado === 'dudosa') return cfg.labels.dudosa;
        return cfg.labels.otro;
    }

    function refreshMapSize() {
        if (!map) return;
        setTimeout(function () {
            map.invalidateSize({ animate: false, pan: false });
        }, 60);
    }

    function ensureMap() {
        if (map) return;
        map = L.map('mapaFichajesMap', { zoomControl: true }).setView([40.4168, -3.7038], 6);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 19,
            attribution: '&copy; OpenStreetMap',
        }).addTo(map);
        capaObras = L.layerGroup().addTo(map);
        capaFichajes = L.layerGroup().addTo(map);
        capaRadio = L.layerGroup().addTo(map);
    }

    function pintarObrasEnMapa() {
        capaObras.clearLayers();
        var bounds = [];
        obrasData.obras.forEach(function (obra) {
            var latlng = [obra.lat, obra.lng];
            bounds.push(latlng);
            var marker = L.marker(latlng, {
                icon: L.divIcon({
                    className: 'mapa-obra-pin',
                    html: '<div style="background:#2563eb;color:#fff;border-radius:50%;width:28px;height:28px;display:flex;align-items:center;justify-content:center;border:2px solid #fff;box-shadow:0 2px 6px rgba(0,0,0,.25);font-size:11px;"><i class="fas fa-hard-hat"></i></div>',
                    iconSize: [28, 28],
                    iconAnchor: [14, 14],
                }),
            });
            marker.obraId = obra.id;
            marker.bindTooltip(obra.nombre, { direction: 'top' });
            marker.on('click', function () {
                seleccionarObra(obra.id, true);
            });
            capaObras.addLayer(marker);
        });
        if (bounds.length === 1) {
            map.setView(bounds[0], 14);
        } else if (bounds.length > 1) {
            map.fitBounds(bounds, { padding: [40, 40], maxZoom: 12 });
        }
    }

    function renderListaObras() {
        var wrap = document.getElementById('mapaObrasList');
        if (!wrap) return;
        if (!obrasData.obras.length && !obrasData.sin_ubicacion.length) {
            wrap.innerHTML = '<p class="mapa-fichajes-empty">' + cfg.labels.sinObras + '</p>';
            return;
        }
        var html = '';
        if (obrasData.obras.length) {
            html += '<div class="mapa-fichajes-section-title">' + cfg.labels.obrasConPin + '</div>';
            obrasData.obras.forEach(function (obra) {
                var sel = obraSeleccionada === obra.id ? ' is-selected' : '';
                html += '<button type="button" class="mapa-fichajes-obra-btn' + sel + '" data-obra-id="' + obra.id + '">'
                    + escapeHtml(obra.nombre)
                    + (obra.codigo ? '<small>' + escapeHtml(obra.codigo) + '</small>' : '')
                    + '</button>';
            });
        }
        if (obrasData.sin_ubicacion.length) {
            html += '<div class="mapa-fichajes-section-title">' + cfg.labels.sinUbicacion + ' (' + obrasData.sin_ubicacion.length + ')</div>';
            obrasData.sin_ubicacion.forEach(function (obra) {
                var url = cfg.editObraUrlBase.replace('__ID__', obra.id);
                html += '<div class="mapa-fichajes-sin-pin">'
                    + '<a href="' + url + '">' + escapeHtml(obra.nombre) + '</a>'
                    + '</div>';
            });
        }
        wrap.innerHTML = html;
        wrap.querySelectorAll('.mapa-fichajes-obra-btn').forEach(function (btn) {
            btn.addEventListener('click', function () {
                seleccionarObra(parseInt(btn.getAttribute('data-obra-id'), 10), true);
            });
        });
    }

    function escapeHtml(text) {
        var d = document.createElement('div');
        d.textContent = text || '';
        return d.innerHTML;
    }

    function seleccionarObra(obraId, cargar) {
        obraSeleccionada = obraId;
        renderListaObras();
        if (cargar) {
            cargarFichajesObra();
        }
    }

    function mostrarPanelDetalle(show) {
        var panel = document.getElementById('mapaDetallePanel');
        if (!panel) return;
        panel.classList.toggle('is-hidden', !show);
        panel.classList.remove('is-collapsed');
        refreshMapSize();
    }

    function cargarFichajesObra() {
        if (!obraSeleccionada) return;
        var rango = rangoDesdePreset(presetActivo);
        var soloDudosos = document.getElementById('mapaSoloDudosos').checked;
        var url = cfg.fichajesUrlBase.replace('__ID__', obraSeleccionada)
            + '?desde=' + encodeURIComponent(rango.desde)
            + '&hasta=' + encodeURIComponent(rango.hasta)
            + (soloDudosos ? '&solo_dudosos=1' : '');

        var titulo = document.getElementById('mapaDetalleTitulo');
        var stats = document.getElementById('mapaDetalleStats');
        var tbody = document.getElementById('mapaDetalleBody');
        mostrarPanelDetalle(true);
        titulo.textContent = cfg.labels.cargando;
        stats.textContent = '';
        tbody.innerHTML = '';

        fetch(url, { credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (!data.success) throw new Error(data.error || 'Error');
                pintarDetalleObra(data);
            })
            .catch(function () {
                titulo.textContent = cfg.labels.seleccionaObra;
                mostrarPanelDetalle(false);
            });
    }

    function pintarDetalleObra(data) {
        var obra = data.obra;
        var puntos = data.puntos || [];
        var st = data.stats || {};
        var radio = data.radio_metros || obrasData.radio_metros || 150;

        document.getElementById('mapaDetalleTitulo').textContent = obra.nombre;
        var statsHtml = st.entradas + ' ' + cfg.labels.entradas
            + ' · <span class="stat-ok">' + (st.coincide || 0) + ' ' + cfg.labels.enRadio + '</span>'
            + ' · <span class="stat-warn">' + (st.dudosa || 0) + ' ' + cfg.labels.dudosa + '</span>';
        if (st.sin_gps) {
            statsHtml += ' · ' + st.sin_gps + ' ' + cfg.labels.sinGps;
        }
        document.getElementById('mapaDetalleStats').innerHTML = statsHtml;

        capaFichajes.clearLayers();
        capaRadio.clearLayers();
        marcadoresFichaje = {};

        if (obra.lat && obra.lng) {
            map.setView([obra.lat, obra.lng], 15);
            L.circle([obra.lat, obra.lng], {
                radius: radio,
                color: '#2563eb',
                fillColor: '#3b82f6',
                fillOpacity: 0.12,
                weight: 2,
            }).addTo(capaRadio);
        }

        var tbody = document.getElementById('mapaDetalleBody');
        if (!puntos.length) {
            tbody.innerHTML = '<tr><td colspan="6" class="text-muted">' + cfg.labels.sinFichajes + '</td></tr>';
            return;
        }

        var rows = '';
        puntos.forEach(function (p) {
            var color = colorPunto(p.geo_estado);
            var dist = p.distancia_metros != null ? Math.round(p.distancia_metros) + ' m' : '—';
            var workerUrl = cfg.workerUrlBase.replace('__ID__', p.user_id);
            rows += '<tr data-event-id="' + p.id + '">'
                + '<td><a href="' + workerUrl + '" class="table-link-primary">' + escapeHtml(p.user_nombre) + '</a></td>'
                + '<td>' + escapeHtml(p.fecha) + '</td>'
                + '<td>' + escapeHtml(p.hora) + '</td>'
                + '<td>' + escapeHtml(etiquetaEstado(p.geo_estado)) + '</td>'
                + '<td>' + dist + '</td>'
                + '<td>' + escapeHtml(p.nota || '—') + '</td>'
                + '</tr>';

            var circle = L.circleMarker([p.lat, p.lng], {
                radius: 7,
                color: '#fff',
                weight: 2,
                fillColor: color,
                fillOpacity: 0.9,
            });
            var popup = '<strong>' + escapeHtml(p.user_nombre) + '</strong><br>'
                + escapeHtml(p.fecha) + ' ' + escapeHtml(p.hora) + '<br>'
                + escapeHtml(etiquetaEstado(p.geo_estado));
            if (p.distancia_metros != null) {
                popup += '<br>' + Math.round(p.distancia_metros) + ' m';
            }
            if (p.nota) {
                popup += '<br><em>' + escapeHtml(p.nota) + '</em>';
            }
            circle.bindPopup(popup);
            circle.eventId = p.id;
            circle.on('click', function () {
                resaltarFila(p.id);
            });
            marcadoresFichaje[p.id] = circle;
            capaFichajes.addLayer(circle);
        });
        tbody.innerHTML = rows;
        tbody.querySelectorAll('tr[data-event-id]').forEach(function (tr) {
            tr.addEventListener('click', function () {
                var eid = parseInt(tr.getAttribute('data-event-id'), 10);
                resaltarFila(eid);
                var m = marcadoresFichaje[eid];
                if (m) {
                    map.setView(m.getLatLng(), Math.max(map.getZoom(), 16));
                    m.openPopup();
                }
            });
        });

        if (puntos.length > 1) {
            var latlngs = puntos.map(function (p) { return [p.lat, p.lng]; });
            if (obra.lat && obra.lng) {
                latlngs.push([obra.lat, obra.lng]);
            }
            map.fitBounds(latlngs, { padding: [50, 50], maxZoom: 16 });
        }
    }

    function resaltarFila(eventId) {
        document.querySelectorAll('#mapaDetalleBody tr').forEach(function (tr) {
            tr.classList.toggle('is-highlight', tr.getAttribute('data-event-id') === String(eventId));
        });
    }

    function togglePanelCollapsed(panel, collapsedTitle) {
        if (!panel) return;
        var collapsed = panel.classList.toggle('is-collapsed');
        var head = panel.querySelector('.mapa-fichajes-float-head h1, .mapa-fichajes-float-head h2');
        if (!head) return;
        if (!head.dataset.fullTitle) {
            head.dataset.fullTitle = head.innerHTML;
        }
        if (collapsed) {
            head.innerHTML = '<i class="fas fa-sliders-h mr-1"></i> ' + escapeHtml(collapsedTitle || cfg.labels.filtros);
        } else {
            head.innerHTML = head.dataset.fullTitle;
        }
        refreshMapSize();
    }

    function bindFloatPanel(panel, head, resizeHandle) {
        if (!panel || !head) return;

        var dragging = false;
        var resizing = false;
        var startX = 0;
        var startY = 0;
        var startLeft = 0;
        var startTop = 0;
        var startWidth = 0;
        var startHeight = 0;
        var viewport = panel.parentElement;

        function clampPanel() {
            if (!viewport) return;
            var rect = panel.getBoundingClientRect();
            var vp = viewport.getBoundingClientRect();
            var left = parseFloat(panel.style.left);
            var top = parseFloat(panel.style.top);
            if (Number.isNaN(left)) left = rect.left - vp.left;
            if (Number.isNaN(top)) top = rect.top - vp.top;
            var maxLeft = Math.max(0, vp.width - rect.width - 8);
            var maxTop = Math.max(0, vp.height - rect.height - 8);
            panel.style.left = Math.min(Math.max(8, left), maxLeft) + 'px';
            panel.style.top = Math.min(Math.max(8, top), maxTop) + 'px';
            panel.style.right = 'auto';
            panel.style.bottom = 'auto';
        }

        function onPointerMove(clientX, clientY) {
            if (dragging) {
                var dx = clientX - startX;
                var dy = clientY - startY;
                panel.style.left = (startLeft + dx) + 'px';
                panel.style.top = (startTop + dy) + 'px';
                panel.style.right = 'auto';
                panel.style.bottom = 'auto';
            } else if (resizing) {
                var newW = Math.max(260, startWidth + (clientX - startX));
                var newH = Math.max(180, startHeight + (clientY - startY));
                panel.style.width = Math.min(newW, viewport.clientWidth - 16) + 'px';
                panel.style.height = Math.min(newH, viewport.clientHeight - 16) + 'px';
                refreshMapSize();
            }
        }

        function endInteraction() {
            if (dragging || resizing) {
                dragging = false;
                resizing = false;
                panel.classList.remove('is-dragging', 'is-resizing');
                clampPanel();
                refreshMapSize();
            }
        }

        head.addEventListener('mousedown', function (e) {
            if (panel.classList.contains('is-collapsed')) return;
            if (e.target.closest('a, button, input, select, label')) return;
            dragging = true;
            panel.classList.add('is-dragging');
            var rect = panel.getBoundingClientRect();
            var vp = viewport.getBoundingClientRect();
            startX = e.clientX;
            startY = e.clientY;
            startLeft = rect.left - vp.left;
            startTop = rect.top - vp.top;
            panel.style.left = startLeft + 'px';
            panel.style.top = startTop + 'px';
            panel.style.right = 'auto';
            panel.style.bottom = 'auto';
            e.preventDefault();
        });

        head.addEventListener('touchstart', function (e) {
            if (panel.classList.contains('is-collapsed')) return;
            if (e.target.closest('a, button, input, select, label')) return;
            var t = e.touches[0];
            dragging = true;
            panel.classList.add('is-dragging');
            var rect = panel.getBoundingClientRect();
            var vp = viewport.getBoundingClientRect();
            startX = t.clientX;
            startY = t.clientY;
            startLeft = rect.left - vp.left;
            startTop = rect.top - vp.top;
            panel.style.left = startLeft + 'px';
            panel.style.top = startTop + 'px';
            panel.style.right = 'auto';
            panel.style.bottom = 'auto';
        }, { passive: true });

        if (resizeHandle) {
            resizeHandle.addEventListener('mousedown', function (e) {
                if (panel.classList.contains('is-collapsed')) return;
                resizing = true;
                panel.classList.add('is-resizing');
                startX = e.clientX;
                startY = e.clientY;
                startWidth = panel.offsetWidth;
                startHeight = panel.offsetHeight;
                e.preventDefault();
                e.stopPropagation();
            });
            resizeHandle.addEventListener('touchstart', function (e) {
                if (panel.classList.contains('is-collapsed')) return;
                var t = e.touches[0];
                resizing = true;
                panel.classList.add('is-resizing');
                startX = t.clientX;
                startY = t.clientY;
                startWidth = panel.offsetWidth;
                startHeight = panel.offsetHeight;
                e.stopPropagation();
            }, { passive: true });
        }

        document.addEventListener('mousemove', function (e) {
            if (!dragging && !resizing) return;
            onPointerMove(e.clientX, e.clientY);
        });
        document.addEventListener('mouseup', endInteraction);
        document.addEventListener('touchmove', function (e) {
            if (!dragging && !resizing) return;
            var t = e.touches[0];
            onPointerMove(t.clientX, t.clientY);
        }, { passive: true });
        document.addEventListener('touchend', endInteraction);

        head.addEventListener('click', function () {
            if (panel.classList.contains('is-collapsed')) {
                panel.classList.remove('is-collapsed');
                var headTitle = panel.querySelector('.mapa-fichajes-float-head h1, .mapa-fichajes-float-head h2');
                if (headTitle && headTitle.dataset.fullTitle) {
                    headTitle.innerHTML = headTitle.dataset.fullTitle;
                }
                refreshMapSize();
            }
        });
    }

    function bindPresets() {
        var customWrap = document.getElementById('mapaCustomRange');
        var desdeEl = document.getElementById('mapaDesde');
        var hastaEl = document.getElementById('mapaHasta');
        var hoy = hoyIso();
        if (desdeEl) desdeEl.value = hoy;
        if (hastaEl) hastaEl.value = hoy;

        document.querySelectorAll('#mapaPresets button').forEach(function (btn) {
            btn.addEventListener('click', function () {
                document.querySelectorAll('#mapaPresets button').forEach(function (b) {
                    b.classList.remove('is-active');
                });
                btn.classList.add('is-active');
                presetActivo = btn.getAttribute('data-preset');
                customWrap.style.display = presetActivo === 'custom' ? '' : 'none';
                if (obraSeleccionada) cargarFichajesObra();
            });
        });

        [desdeEl, hastaEl].forEach(function (el) {
            if (!el) return;
            el.addEventListener('change', function () {
                if (presetActivo === 'custom' && obraSeleccionada) cargarFichajesObra();
            });
        });

        document.getElementById('mapaSoloDudosos').addEventListener('change', function () {
            if (obraSeleccionada) cargarFichajesObra();
        });

        document.getElementById('mapaDetalleCerrar').addEventListener('click', function () {
            mostrarPanelDetalle(false);
            capaFichajes.clearLayers();
            capaRadio.clearLayers();
            obraSeleccionada = null;
            renderListaObras();
        });

        var controlsPanel = document.getElementById('mapaControlsPanel');
        var detailPanel = document.getElementById('mapaDetallePanel');
        document.getElementById('mapaControlsCollapse').addEventListener('click', function (e) {
            e.stopPropagation();
            togglePanelCollapsed(controlsPanel, cfg.labels.filtros);
        });
        document.getElementById('mapaDetalleCollapse').addEventListener('click', function (e) {
            e.stopPropagation();
            togglePanelCollapsed(detailPanel, cfg.labels.detalle);
        });

        bindFloatPanel(
            controlsPanel,
            document.getElementById('mapaControlsHead'),
            document.getElementById('mapaControlsResize')
        );
        bindFloatPanel(
            detailPanel,
            document.getElementById('mapaDetalleHead'),
            document.getElementById('mapaDetalleResize')
        );
    }

    function aplicarQueryInicial() {
        var params = new URLSearchParams(window.location.search);
        var obraId = parseInt(params.get('obra_id') || '', 10);
        var desde = params.get('desde');
        var hasta = params.get('hasta');
        var dudosos = params.get('solo_dudosos');

        if (desde || hasta) {
            presetActivo = 'custom';
            document.querySelectorAll('#mapaPresets button').forEach(function (b) {
                b.classList.toggle('is-active', b.getAttribute('data-preset') === 'custom');
            });
            document.getElementById('mapaCustomRange').style.display = '';
            if (desde) document.getElementById('mapaDesde').value = desde;
            if (hasta) document.getElementById('mapaHasta').value = hasta;
        }
        if (dudosos === '1') {
            document.getElementById('mapaSoloDudosos').checked = true;
        }
        if (obraId) {
            seleccionarObra(obraId, true);
        }
    }

    function cargarObras() {
        return fetch(cfg.obrasUrl, {
            credentials: 'same-origin',
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
        }).then(function (r) { return r.json(); }).then(function (data) {
            if (!data.success) throw new Error('obras');
            obrasData = data;
            pintarObrasEnMapa();
            renderListaObras();
        });
    }

    function init(config) {
        cfg = config || {};
        document.addEventListener('DOMContentLoaded', function () {
            ensureMap();
            bindPresets();
            cargarObras().then(function () {
                aplicarQueryInicial();
                refreshMapSize();
            }).catch(function () {
                document.getElementById('mapaObrasList').innerHTML =
                    '<p class="text-danger">' + cfg.labels.sinObras + '</p>';
            });
            window.addEventListener('resize', refreshMapSize);
        });
    }

    return { init: init };
})();
