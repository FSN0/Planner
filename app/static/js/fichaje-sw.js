/* Service worker del área de fichaje.
 *
 * Su único cometido es que la aplicación abra rápido y siga abriendo con mala
 * cobertura. No cachea respuestas de fichaje ni sirve datos viejos como si
 * fueran actuales: un trabajador que ve una pantalla cacheada podría creer que
 * ha fichado cuando no lo ha hecho.
 *
 * Al cambiar los ficheros de la lista hay que subir VERSION o los móviles se
 * quedarán con la versión anterior.
 */

var VERSION = 'fichaje-v1';

var RECURSOS = [
    '/static/css/operario.css',
    '/static/js/operario-fichaje.js',
    '/static/img/fichaje-icon.svg'
];

self.addEventListener('install', function (evento) {
    evento.waitUntil(
        caches.open(VERSION)
            .then(function (cache) { return cache.addAll(RECURSOS); })
            .then(function () { return self.skipWaiting(); })
    );
});

self.addEventListener('activate', function (evento) {
    evento.waitUntil(
        caches.keys().then(function (nombres) {
            return Promise.all(nombres.map(function (nombre) {
                if (nombre !== VERSION) { return caches.delete(nombre); }
            }));
        }).then(function () { return self.clients.claim(); })
    );
});

self.addEventListener('fetch', function (evento) {
    var peticion = evento.request;

    // Fichar siempre va contra el servidor. Si falla, tiene que fallar.
    if (peticion.method !== 'GET') { return; }

    var url = new URL(peticion.url);
    if (url.origin !== self.location.origin) { return; }

    // Los recursos estáticos sí: no cambian entre versiones del cache.
    if (url.pathname.startsWith('/static/')) {
        evento.respondWith(
            caches.match(peticion).then(function (guardado) {
                return guardado || fetch(peticion).then(function (respuesta) {
                    if (respuesta.ok) {
                        var copia = respuesta.clone();
                        caches.open(VERSION).then(function (cache) {
                            cache.put(peticion, copia);
                        });
                    }
                    return respuesta;
                });
            })
        );
        return;
    }

    // Las páginas, red primero. Solo se cae al cache si no hay red, y en ese
    // caso lo que se ve es la última pantalla conocida, nunca un fichaje nuevo.
    if (peticion.mode === 'navigate') {
        evento.respondWith(
            fetch(peticion).then(function (respuesta) {
                if (respuesta.ok) {
                    var copia = respuesta.clone();
                    caches.open(VERSION).then(function (cache) {
                        cache.put(peticion, copia);
                    });
                }
                return respuesta;
            }).catch(function () {
                return caches.match(peticion).then(function (guardado) {
                    return guardado || new Response(
                        '<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">' +
                        '<meta name="viewport" content="width=device-width,initial-scale=1">' +
                        '<title>Sin conexión</title></head>' +
                        '<body style="font-family:system-ui;background:#0f172a;color:#f1f5f9;' +
                        'padding:32px;text-align:center">' +
                        '<h1>Sin conexión</h1>' +
                        '<p>No se ha podido contactar con el servidor. ' +
                        'Ningún fichaje se registra sin conexión.</p></body></html>',
                        { headers: { 'Content-Type': 'text/html; charset=utf-8' } }
                    );
                });
            })
        );
    }
});
