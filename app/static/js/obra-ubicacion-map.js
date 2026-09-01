/* Mapa Leaflet para ubicar obras (pin + geocerca global). */
(function () {
    'use strict';

    var block = document.getElementById('obraGeoBlock');
    if (!block) { return; }

    var panel = document.getElementById('obraGeoPanel');
    var toggleBtn = document.getElementById('obraGeoToggle');
    var preview = document.getElementById('obraGeoPreview');
    var statusEl = document.getElementById('obraGeoStatus');
    var inputDir = document.getElementById('obraGeoDireccion');
    var inputUbic = document.getElementById('obraGeoUbicacion');
    var inputLat = document.getElementById('obraGeoLat');
    var inputLng = document.getElementById('obraGeoLng');
    var btnBuscar = document.getElementById('obraGeoBuscar');
    var btnLimpiar = document.getElementById('obraGeoLimpiar');
    var btnGuardar = document.getElementById('obraGeoGuardar');
    var saveUrl = block.dataset.saveUrl || '';
    var csrfToken = block.dataset.csrf || '';

    var defaultRadio = parseInt(block.dataset.radioDefault || '150', 10) || 150;
    var labelExpand = block.dataset.labelExpand || 'Ampliar mapa';
    var labelCollapse = block.dataset.labelCollapse || 'Ocultar mapa';
    var lat = parseFloat(block.dataset.lat);
    var lng = parseFloat(block.dataset.lng);
    var hasPin = !isNaN(lat) && !isNaN(lng);

    var map = null;
    var marker = null;
    var circle = null;
    var mapReady = false;
    var reverseTimer = null;
    var UBICACION_MAX = 100;

    function truncarUbicacion(texto) {
        if (!texto) { return ''; }
        texto = String(texto).trim();
        return texto.length > UBICACION_MAX ? texto.slice(0, UBICACION_MAX) : texto;
    }

    function setStatus(msg, kind) {
        if (!statusEl) { return; }
        statusEl.textContent = msg || '';
        statusEl.classList.remove('is-ok', 'is-error');
        if (kind) { statusEl.classList.add(kind === 'ok' ? 'is-ok' : 'is-error'); }
    }

    function syncHiddenDir() {
        if (inputUbic && inputDir) {
            inputUbic.value = inputDir.value.trim();
        }
    }

    function updatePreview(text) {
        if (preview) {
            preview.textContent = text || 'Sin ubicación fijada';
        }
    }

    function ensureMap() {
        if (mapReady || typeof L === 'undefined') { return; }
        var mapEl = document.getElementById('obraGeoMap');
        if (!mapEl) { return; }

        var center = hasPin ? [lat, lng] : [40.4168, -3.7038];
        var zoom = hasPin ? 16 : 6;
        map = L.map(mapEl, { scrollWheelZoom: true }).setView(center, zoom);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 19,
            attribution: '&copy; OpenStreetMap'
        }).addTo(map);

        map.on('click', function (e) {
            fijarPin(e.latlng, false, true);
        });

        if (hasPin) {
            fijarPin(L.latLng(lat, lng), false, false);
        }

        mapReady = true;
        setTimeout(function () { map.invalidateSize(); }, 150);
    }

    function pintarCirculo(latlng) {
        if (!map) { return; }
        if (circle) { map.removeLayer(circle); }
        circle = L.circle(latlng, {
            radius: defaultRadio,
            color: '#2563eb',
            fillColor: '#3b82f6',
            fillOpacity: 0.15,
            weight: 2
        }).addTo(map);
    }

    function guardarCoords(latVal, lngVal, moverVista, reverse) {
        if (inputLat) { inputLat.value = latVal.toFixed(6); }
        if (inputLng) { inputLng.value = lngVal.toFixed(6); }
        hasPin = true;
        lat = latVal;
        lng = lngVal;

        if (map) {
            var latlng = L.latLng(latVal, lngVal);
            pintarCirculo(latlng);
            if (moverVista) {
                map.setView(latlng, Math.max(map.getZoom(), 15));
            }
        }

        if (reverse) {
            reverseGeocode(latVal, lngVal);
        } else {
            syncHiddenDir();
            updatePreview((inputDir && inputDir.value.trim()) || 'Pin fijado (sin dirección)');
        }
    }

    function fijarPin(latlng, moverVista, reverse) {
        if (!map) { return; }
        if (marker) { map.removeLayer(marker); }
        marker = L.marker(latlng, { draggable: true }).addTo(map);
        marker.on('dragend', function () {
            var pos = marker.getLatLng();
            guardarCoords(pos.lat, pos.lng, false, true);
        });
        guardarCoords(latlng.lat, latlng.lng, moverVista, reverse);
    }

    function limpiarPin() {
        if (marker && map) { map.removeLayer(marker); marker = null; }
        if (circle && map) { map.removeLayer(circle); circle = null; }
        if (inputLat) { inputLat.value = ''; }
        if (inputLng) { inputLng.value = ''; }
        if (inputDir) { inputDir.value = ''; }
        syncHiddenDir();
        hasPin = false;
        updatePreview('Sin ubicación fijada');
        setStatus('');
    }

    function nominatimHeaders() {
        return { 'Accept-Language': document.documentElement.lang || 'es' };
    }

    function reverseGeocode(latVal, lngVal) {
        if (reverseTimer) { clearTimeout(reverseTimer); }
        reverseTimer = setTimeout(function () {
            fetch('https://nominatim.openstreetmap.org/reverse?format=json&lat='
                + encodeURIComponent(latVal) + '&lon=' + encodeURIComponent(lngVal), {
                headers: nominatimHeaders()
            }).then(function (r) { return r.json(); }).then(function (hit) {
                var label = (hit && hit.display_name) ? truncarUbicacion(hit.display_name) : '';
                if (inputDir && label) {
                    inputDir.value = label;
                }
                syncHiddenDir();
                updatePreview(label || 'Pin fijado (sin dirección)');
            }).catch(function () {
                syncHiddenDir();
                updatePreview((inputDir && inputDir.value.trim()) || 'Pin fijado (sin dirección)');
            });
        }, 350);
    }

    function buscarDireccion() {
        var q = (inputDir && inputDir.value || '').trim();
        if (!q) { return; }
        ensureMap();
        syncHiddenDir();
        btnBuscar.disabled = true;
        setStatus('Buscando…');
        fetch('https://nominatim.openstreetmap.org/search?format=json&limit=1&q='
            + encodeURIComponent(q), {
            headers: nominatimHeaders()
        }).then(function (r) { return r.json(); }).then(function (resultados) {
            if (!resultados || !resultados.length) {
                setStatus('No se encontró la dirección.', 'error');
                return;
            }
            var hit = resultados[0];
            fijarPin(L.latLng(parseFloat(hit.lat), parseFloat(hit.lon)), true, false);
            if (inputDir && hit.display_name) {
                inputDir.value = truncarUbicacion(hit.display_name);
                syncHiddenDir();
                updatePreview(inputDir.value);
            }
            setStatus('');
        }).catch(function () {
            setStatus('Error al buscar la dirección.', 'error');
        }).finally(function () {
            btnBuscar.disabled = false;
        });
    }

    function payloadUbicacion(limpiar) {
        return {
            latitud: limpiar ? null : (hasPin ? lat : null),
            longitud: limpiar ? null : (hasPin ? lng : null),
            ubicacion: truncarUbicacion(inputDir && inputDir.value) || null,
            limpiar: !!limpiar
        };
    }

    function guardarUbicacionServidor(limpiar) {
        if (!saveUrl) { return; }
        if (!limpiar && !hasPin) {
            setStatus('Marca un punto en el mapa antes de guardar.', 'error');
            return;
        }
        if (btnGuardar) { btnGuardar.disabled = true; }
        setStatus('Guardando…');
        fetch(saveUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify(payloadUbicacion(limpiar))
        }).then(function (r) {
            return r.json().then(function (data) {
                if (!r.ok || !data.success) {
                    throw new Error(data.error || 'No se pudo guardar');
                }
                return data;
            });
        }).then(function (data) {
            if (inputDir && data.ubicacion !== undefined) {
                inputDir.value = data.ubicacion || '';
            }
            updatePreview((data.ubicacion && data.ubicacion.trim()) || (limpiar ? 'Sin ubicación fijada' : 'Pin fijado (sin dirección)'));
            setStatus('Ubicación guardada', 'ok');
        }).catch(function (err) {
            setStatus(err.message || 'Error al guardar', 'error');
        }).finally(function () {
            if (btnGuardar) { btnGuardar.disabled = false; }
        });
    }

    if (toggleBtn && panel) {
        toggleBtn.addEventListener('click', function () {
            var open = panel.classList.toggle('d-none') === false;
            toggleBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
            toggleBtn.innerHTML = open
                ? '<i class="fas fa-compress-alt"></i> ' + labelCollapse
                : '<i class="fas fa-map-marked-alt"></i> ' + labelExpand;
            if (open) {
                ensureMap();
                setTimeout(function () { if (map) { map.invalidateSize(); } }, 200);
            }
        });
    }

    if (inputDir) {
        inputDir.addEventListener('change', syncHiddenDir);
        inputDir.addEventListener('blur', syncHiddenDir);
    }
    if (btnBuscar) { btnBuscar.addEventListener('click', buscarDireccion); }
    if (btnLimpiar) {
        btnLimpiar.addEventListener('click', function () {
            limpiarPin();
            if (saveUrl) { guardarUbicacionServidor(true); }
        });
    }
    if (btnGuardar) {
        btnGuardar.addEventListener('click', function () {
            guardarUbicacionServidor(false);
        });
    }
})();
