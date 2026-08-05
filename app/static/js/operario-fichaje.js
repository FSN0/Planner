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
    var mensaje = document.getElementById('mensaje');
    var botones = panel.querySelectorAll('.boton[data-tipo]:not([data-tipo="conforme"])');
    var btnConformar = document.getElementById('btn-conformar');
    var enCurso = false;

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

    /* --- Ubicación ------------------------------------------------------ */

    /* Nunca rechaza: si no hay permiso o el GPS tarda, se ficha igual y el
     * servidor decide si esa ausencia es aceptable según la configuración. */
    function ubicacion() {
        return new Promise(function (resolve) {
            if (modoGeo === 'desactivada' || !navigator.geolocation) {
                resolve({});
                return;
            }

            var resuelto = false;
            function acabar(valor) {
                if (!resuelto) { resuelto = true; resolve(valor); }
            }

            /* Un GPS bajo un forjado puede no fijar nunca. Diez segundos y se
             * sigue adelante: es peor bloquear el fichaje que perder la
             * coordenada. */
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

    /* --- Envío ---------------------------------------------------------- */

    function bloquear(estado) {
        enCurso = estado;
        botones.forEach(function (boton) { boton.disabled = estado; });
    }

    function token() {
        var etiqueta = document.querySelector('meta[name="csrf-token"]');
        return etiqueta ? etiqueta.content : '';
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
        if (modoGeo !== 'desactivada') {
            mostrar(t('Obteniendo tu ubicación…'), 'ok');
        }

        ubicacion().then(function (coordenadas) {
            var cuerpo = Object.assign({ tipo: tipo }, coordenadas);
            if (selector && selector.value) {
                cuerpo.obra_id = selector.value;
            }

            return fetch(urlFichar, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': token(),
                    'X-Requested-With': 'XMLHttpRequest'
                },
                credentials: 'same-origin',
                body: JSON.stringify(cuerpo)
            });
        }).then(function (respuesta) {
            return respuesta.json().then(function (datos) {
                return { ok: respuesta.ok, datos: datos };
            });
        }).then(function (resultado) {
            if (!resultado.ok || !resultado.datos.ok) {
                mostrar(resultado.datos.error || t('No se ha podido fichar.'), 'error');
                bloquear(false);
                return;
            }

            mostrar(t('Fichaje registrado.'), 'ok');
            if (navigator.vibrate) { navigator.vibrate(60); }
            /* Se recarga en lugar de repintar a mano: así los botones que se
             * ofrecen los sigue decidiendo el servidor en un único sitio. */
            window.location.reload();
        }).catch(function () {
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
