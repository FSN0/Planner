/* Pantalla de fichaje.
 *
 * Una decisión importante: fichar exige conexión. Se podría guardar el fichaje
 * en el móvil y enviarlo al recuperar cobertura, pero entonces la hora la
 * pondría el teléfono, que el trabajador puede cambiar. Mientras el registro
 * tenga valor probatorio, la hora la pone el servidor. Si no hay red, se dice
 * claramente que NO ha quedado registrado, que es mucho menos dañino que dejar
 * creer que sí.
 */

(function () {
    'use strict';

    var panel = document.querySelector('.fichaje');
    if (!panel) { return; }

    var t = (typeof window.SP_T === 'function') ? window.SP_T : function (k) { return k; };
    var urlFichar = panel.dataset.urlFichar;
    var urlConformar = panel.dataset.urlConformar;
    var modoGeo = panel.dataset.modoGeo;
    var geocercaActiva = panel.dataset.geocercaActiva === '1';
    var geoExigir = panel.dataset.geoExigir === '1';
    var ultimaObraId = panel.dataset.ultimaObra || '';
    var mensaje = document.getElementById('mensaje');
    var botones = panel.querySelectorAll('.boton[data-tipo]:not([data-tipo="conforme"])');
    var btnConformar = document.getElementById('btn-conformar');
    var enCurso = false;
    var coordsCache = null;

    var obrasGeo = [];
    try {
        var geoNode = document.getElementById('obras-geo-data');
        obrasGeo = geoNode ? JSON.parse(geoNode.textContent || '[]') : [];
    } catch (e) {
        obrasGeo = [];
    }

    var obrasGeoMap = {};
    obrasGeo.forEach(function (o) { obrasGeoMap[String(o.id)] = o; });

    /* --- Reloj ---------------------------------------------------------- */

    var reloj = document.getElementById('reloj-hora');

    function pintarHora() {
        var ahora = new Date();
        reloj.textContent =
            String(ahora.getHours()).padStart(2, '0') + ':' +
            String(ahora.getMinutes()).padStart(2, '0');
    }

    if (reloj) {
        pintarHora();
        setInterval(pintarHora, 10000);
    }

    /* --- Mensajes ------------------------------------------------------- */

    function mostrar(texto, tipo) {
        if (!mensaje) { return; }
        mensaje.textContent = texto;
        mensaje.className = 'mensaje mensaje--' + tipo;
        mensaje.hidden = false;
    }

    function ocultar() {
        if (mensaje) { mensaje.hidden = true; }
    }

    /* --- Geocerca ------------------------------------------------------- */

    function geoActiva() {
        return modoGeo === 'activada';
    }

    function distanciaMetros(lat1, lon1, lat2, lon2) {
        var r = 6371000;
        var phi1 = lat1 * Math.PI / 180;
        var phi2 = lat2 * Math.PI / 180;
        var dphi = (lat2 - lat1) * Math.PI / 180;
        var dlambda = (lon2 - lon1) * Math.PI / 180;
        var a = Math.sin(dphi / 2) * Math.sin(dphi / 2)
            + Math.cos(phi1) * Math.cos(phi2) * Math.sin(dlambda / 2) * Math.sin(dlambda / 2);
        return 2 * r * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    }

    function obraEnRadio(obraId, coords) {
        var meta = obrasGeoMap[String(obraId)];
        if (!meta || !coords || coords.latitud == null) { return false; }
        return distanciaMetros(coords.latitud, coords.longitud, meta.lat, meta.lng) <= meta.radio;
    }

    function idsPlanificadas() {
        var grupo = document.querySelector('#obra optgroup[data-grupo="planificadas"]');
        if (!grupo) { return []; }
        return Array.prototype.map.call(grupo.querySelectorAll('option'), function (o) {
            return o.value;
        });
    }

    function reordenarObras(coords) {
        var selector = document.getElementById('obra');
        if (!selector || !geocercaActiva || !coords || coords.latitud == null) { return; }

        var seleccion = selector.value;
        var opciones = Array.prototype.slice.call(selector.querySelectorAll('option'));
        var cercanas = [];
        var resto = [];

        opciones.forEach(function (opt) {
            if (!opt.value) { return; }
            if (obraEnRadio(opt.value, coords)) {
                cercanas.push(opt);
            } else {
                resto.push(opt);
            }
        });

        while (selector.firstChild) { selector.removeChild(selector.firstChild); }

        if (cercanas.length) {
            var gCerca = document.createElement('optgroup');
            gCerca.label = t('Cerca de ti');
            gCerca.dataset.grupo = 'cerca';
            cercanas.forEach(function (opt) {
                opt.className = 'obra-option--cerca';
                gCerca.appendChild(opt);
            });
            selector.appendChild(gCerca);
        }

        var planIds = idsPlanificadas();
        var planResto = resto.filter(function (opt) { return planIds.indexOf(opt.value) >= 0; });
        var otrasResto = resto.filter(function (opt) { return planIds.indexOf(opt.value) < 0; });

        if (planResto.length) {
            var gPlan = document.createElement('optgroup');
            gPlan.label = t('Tu planificación de hoy');
            gPlan.dataset.grupo = 'planificadas';
            planResto.forEach(function (opt) {
                opt.className = 'obra-option--lejos';
                gPlan.appendChild(opt);
            });
            selector.appendChild(gPlan);
        }

        if (otrasResto.length) {
            var gOtras = document.createElement('optgroup');
            gOtras.label = t('Otras obras');
            gOtras.dataset.grupo = 'otras';
            otrasResto.forEach(function (opt) {
                opt.className = 'obra-option--lejos';
                gOtras.appendChild(opt);
            });
            selector.appendChild(gOtras);
        }

        var preselect = null;
        if (cercanas.length) {
            var idsCerca = cercanas.map(function (o) { return o.value; });
            if (ultimaObraId && idsCerca.indexOf(String(ultimaObraId)) >= 0) {
                preselect = String(ultimaObraId);
            } else {
                for (var i = 0; i < cercanas.length; i++) {
                    if (planIds.indexOf(cercanas[i].value) >= 0) {
                        preselect = cercanas[i].value;
                        break;
                    }
                }
                if (!preselect) { preselect = cercanas[0].value; }
            }
        }

        if (preselect) {
            selector.value = preselect;
        } else if (seleccion && selector.querySelector('option[value="' + seleccion + '"]')) {
            selector.value = seleccion;
        }
    }

    function confirmarUbicacionDudosa(nombreObra) {
        return new Promise(function (resolve) {
            var root = document.getElementById('geo-modal-root');
            if (!root) { resolve({ ok: true, nota: '' }); return; }

            root.hidden = false;
            root.innerHTML =
                '<div class="geo-modal-backdrop" role="dialog" aria-modal="true">'
                + '<div class="geo-modal">'
                + '<p><strong>' + t('Ubicación no coincide') + '</strong></p>'
                + '<p>' + t('Tu ubicación no parece estar en') + ' <em>' + nombreObra + '</em>. '
                + t('¿Quieres continuar con el fichaje?') + '</p>'
                + '<label for="geo-nota">' + t('Nota (opcional)') + '</label>'
                + '<textarea id="geo-nota" maxlength="500"></textarea>'
                + '<div class="geo-modal-actions">'
                + '<button type="button" class="boton" data-accion="cancelar">' + t('Cancelar') + '</button>'
                + '<button type="button" class="boton boton--entrar" data-accion="continuar">' + t('Sí, continuar') + '</button>'
                + '</div></div></div>';

            root.querySelector('[data-accion="cancelar"]').addEventListener('click', function () {
                root.hidden = true;
                root.innerHTML = '';
                resolve({ ok: false });
            });
            root.querySelector('[data-accion="continuar"]').addEventListener('click', function () {
                var nota = (document.getElementById('geo-nota').value || '').trim();
                root.hidden = true;
                root.innerHTML = '';
                resolve({ ok: true, nota: nota });
            });
        });
    }

    /* --- Ubicación ------------------------------------------------------ */

    function ubicacion() {
        return new Promise(function (resolve) {
            if (!geoActiva() || !navigator.geolocation) {
                resolve({});
                return;
            }
            if (coordsCache) {
                resolve(coordsCache);
                return;
            }

            var resuelto = false;
            function acabar(valor) {
                if (!resuelto) {
                    resuelto = true;
                    coordsCache = valor;
                    resolve(valor);
                }
            }

            setTimeout(function () { acabar({}); }, 10000);

            navigator.geolocation.getCurrentPosition(
                function (posicion) {
                    acabar({
                        latitud: posicion.coords.latitude,
                        longitud: posicion.coords.longitude,
                        precision_metros: posicion.coords.accuracy
                    });
                },
                function () { acabar({}); },
                { enableHighAccuracy: true, timeout: 9000, maximumAge: 30000 }
            );
        });
    }

    if (geoActiva() && geocercaActiva) {
        ubicacion().then(function (coords) {
            reordenarObras(coords);
        });
    }

    /* --- Envío ---------------------------------------------------------- */

    function bloquear(estado) {
        enCurso = estado;
        botones.forEach(function (boton) { boton.disabled = estado; });
    }

    function token() {
        var etiqueta = document.querySelector('meta[name="csrf-token"]');
        return etiqueta ? etiqueta.content : '';
    }

    function postFichaje(cuerpo) {
        return fetch(urlFichar, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': token(),
                'X-Requested-With': 'XMLHttpRequest'
            },
            credentials: 'same-origin',
            body: JSON.stringify(cuerpo)
        }).then(function (respuesta) {
            return respuesta.json().then(function (datos) {
                return { ok: respuesta.ok, datos: datos };
            });
        });
    }

    function enviar(tipo) {
        if (enCurso) { return; }

        var selector = document.getElementById('obra');
        if (tipo === 'entrada' && selector && !selector.value) {
            mostrar(t('Elige primero en qué obra vas a trabajar.'), 'error');
            return;
        }

        bloquear(true);
        ocultar();
        if (geoActiva()) {
            mostrar(t('Obteniendo tu ubicación…'), 'ok');
        }

        ubicacion().then(function (coordenadas) {
            if (geoExigir && (coordenadas.latitud == null || coordenadas.longitud == null)) {
                mostrar(t('Esta empresa exige la ubicación para fichar. Actívala en tu móvil.'), 'error');
                bloquear(false);
                return Promise.reject(new Error('geo_requerida'));
            }

            var cuerpo = Object.assign({ tipo: tipo }, coordenadas);
            if (selector && selector.value) {
                cuerpo.obra_id = selector.value;
            }

            if (tipo === 'entrada' && geocercaActiva && selector && selector.value) {
                var meta = obrasGeoMap[String(selector.value)];
                var opt = selector.querySelector('option[value="' + selector.value + '"]');
                var nombre = opt ? (opt.dataset.nombre || opt.textContent) : '';
                if (meta && coordenadas.latitud != null && !obraEnRadio(selector.value, coordenadas)) {
                    return confirmarUbicacionDudosa(nombre).then(function (res) {
                        if (!res.ok) {
                            bloquear(false);
                            return Promise.reject(new Error('cancelado'));
                        }
                        if (res.nota) { cuerpo.nota_ubicacion = res.nota; }
                        return postFichaje(cuerpo);
                    });
                }
            }

            return postFichaje(cuerpo);
        }).then(function (resultado) {
            if (!resultado) { return; }
            if (!resultado.ok || !resultado.datos.ok) {
                mostrar(resultado.datos.error || t('No se ha podido fichar.'), 'error');
                bloquear(false);
                return;
            }

            mostrar(t('Fichaje registrado.'), 'ok');
            if (navigator.vibrate) { navigator.vibrate(60); }
            window.location.reload();
        }).catch(function (err) {
            if (err && (err.message === 'cancelado' || err.message === 'geo_requerida')) {
                return;
            }
            mostrar(
                t('Sin conexión: el fichaje NO ha quedado registrado. Busca cobertura y vuelve a intentarlo.'),
                'error'
            );
            bloquear(false);
        });
    }

    botones.forEach(function (boton) {
        boton.addEventListener('click', function () {
            enviar(boton.dataset.tipo);
        });
    });

    if (btnConformar && urlConformar) {
        btnConformar.addEventListener('click', function () {
            if (enCurso) { return; }
            if (!window.confirm(
                t('¿Confirmas que el registro de hoy (entrada, pausas y salida) es correcto?')
            )) {
                return;
            }
            bloquear(true);
            if (btnConformar) { btnConformar.disabled = true; }
            ocultar();
            fetch(urlConformar, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': token(),
                    'X-Requested-With': 'XMLHttpRequest'
                },
                credentials: 'same-origin',
                body: '{}'
            }).then(function (respuesta) {
                return respuesta.json().then(function (datos) {
                    return { ok: respuesta.ok, datos: datos };
                });
            }).then(function (resultado) {
                if (!resultado.ok || !resultado.datos.ok) {
                    mostrar(resultado.datos.error || t('No se ha podido firmar.'), 'error');
                    bloquear(false);
                    if (btnConformar) { btnConformar.disabled = false; }
                    return;
                }
                mostrar(t('Jornada firmada.'), 'ok');
                if (navigator.vibrate) { navigator.vibrate(60); }
                window.location.reload();
            }).catch(function () {
                mostrar(
                    t('Sin conexión: la firma NO ha quedado registrada. Busca cobertura y vuelve a intentarlo.'),
                    'error'
                );
                bloquear(false);
                if (btnConformar) { btnConformar.disabled = false; }
            });
        });
    }
})();
