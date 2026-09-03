/**
 * Notas por voz: subir / grabar con progreso de subida y de procesamiento.
 */
(function () {
    'use strict';

    var t = window.SP_T || function (key) { return key; };
    var mediaRecorder = null;
    var recordedChunks = [];
    var recordStream = null;
    var recordTimer = null;
    var recordStartedAt = 0;
    var pollTimer = null;
    var processStartedAt = 0;
    var lastProgress = 0;
    var busy = false;
    var pollStartedAt = 0;
    var MAX_POLL_MS = 70 * 60 * 1000; // 70 min techo UI

    var STEPS = [
        { id: 'subida', label: 'Subida' },
        { id: 'preparando', label: 'Preparación' },
        { id: 'transcribiendo', label: 'Transcripción' },
        { id: 'resumiendo', label: 'Resumen' },
        { id: 'guardando', label: 'Guardado' },
    ];

    function csrfToken() {
        var parts = ('; ' + document.cookie).split('; csrf_token=');
        if (parts.length === 2) return parts.pop().split(';').shift();
        return '';
    }

    function formatDuration(seconds) {
        seconds = Math.max(0, Math.floor(Number(seconds) || 0));
        var h = Math.floor(seconds / 3600);
        var m = Math.floor((seconds % 3600) / 60);
        var s = seconds % 60;
        if (h > 0) {
            return h + ':' + String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0');
        }
        return m + ':' + String(s).padStart(2, '0');
    }

    function formatBytes(bytes) {
        if (!bytes && bytes !== 0) return '';
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
        return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    }

    function canRecord() {
        return !!(navigator.mediaDevices && window.MediaRecorder);
    }

    function el(id) {
        return document.getElementById(id);
    }

    function setBusy(isBusy) {
        busy = !!isBusy;
        var actions = el('notaAudioActions');
        var drop = el('notaAudioDropzone');
        if (actions) actions.classList.toggle('is-disabled', busy);
        if (drop) drop.classList.toggle('is-disabled', busy);
        var input = el('notaAudioFile');
        if (input) input.disabled = busy;
        var btnGrabar = el('btnNotaAudioGrabar');
        if (btnGrabar) btnGrabar.disabled = busy;
    }

    function showPanel(show) {
        var panel = el('notaAudioProgressPanel');
        if (panel) panel.classList.toggle('d-none', !show);
        var idle = el('notaAudioIdleHint');
        if (idle) idle.classList.toggle('d-none', !!show);
    }

    function setStepActive(fase) {
        var map = {
            subida: 'subida',
            pendiente: 'preparando',
            encola: 'preparando',
            preparando: 'preparando',
            transcribiendo: 'transcribiendo',
            resumiendo: 'resumiendo',
            vinculando: 'resumiendo',
            guardando: 'guardando',
            completado: 'guardando',
            error: null,
        };
        var active = map[fase] || null;
        var activeIdx = active ? STEPS.findIndex(function (s) { return s.id === active; }) : -1;

        STEPS.forEach(function (step, idx) {
            var node = el('notaAudioStep_' + step.id);
            if (!node) return;
            node.classList.remove('is-active', 'is-done');
            if (fase === 'completado') {
                node.classList.add('is-done');
                return;
            }
            if (activeIdx < 0) return;
            if (idx < activeIdx) node.classList.add('is-done');
            else if (idx === activeIdx) node.classList.add('is-active');
        });
    }

    function setProgress(pct, opts) {
        opts = opts || {};
        pct = Math.max(0, Math.min(100, Math.round(Number(pct) || 0)));
        if (pct < lastProgress && !opts.force) pct = lastProgress;
        lastProgress = pct;

        var fill = el('notaAudioBarFill');
        var pctEl = el('notaAudioPct');
        var msgEl = el('notaAudioMsg');
        var etaEl = el('notaAudioEta');
        var elapsedEl = el('notaAudioElapsed');
        var detailEl = el('notaAudioDetail');

        if (fill) fill.style.width = pct + '%';
        if (pctEl) pctEl.textContent = pct + '%';
        if (msgEl && opts.mensaje) msgEl.textContent = opts.mensaje;
        if (detailEl) {
            detailEl.textContent = opts.detalle || '';
            detailEl.classList.toggle('d-none', !opts.detalle);
        }

        if (processStartedAt && elapsedEl) {
            var elapsed = (Date.now() - processStartedAt) / 1000;
            elapsedEl.textContent = t('Transcurrido') + ': ' + formatDuration(elapsed);
        }

        if (etaEl) {
            if (opts.etaSeconds != null && opts.etaSeconds >= 0 && pct < 100) {
                etaEl.textContent = t('Quedan ~') + ' ' + formatDuration(opts.etaSeconds);
                etaEl.classList.remove('d-none');
            } else if (pct >= 100) {
                etaEl.textContent = t('Completado');
                etaEl.classList.remove('d-none');
            } else {
                etaEl.classList.add('d-none');
            }
        }

        var panel = el('notaAudioProgressPanel');
        if (panel) {
            panel.classList.toggle('is-error', !!opts.error);
            panel.classList.toggle('is-ok', !!opts.ok);
        }
        setStepActive(opts.fase || (opts.ok ? 'completado' : 'preparando'));
    }

    function estimateEta(progreso, duracionSeg) {
        if (!processStartedAt || progreso <= 8) return null;
        var elapsed = (Date.now() - processStartedAt) / 1000;
        var rate = progreso / Math.max(elapsed, 1);
        if (rate <= 0.01) return null;
        var remainingByRate = (100 - progreso) / rate;

        // Heurística por duración del audio (Whisper ~0.15–0.4× realtime + margen)
        var remainingByAudio = null;
        if (duracionSeg && progreso < 75) {
            var expectedTotal = Math.max(40, duracionSeg * 0.35 + 25);
            remainingByAudio = Math.max(0, expectedTotal - elapsed);
        }

        if (remainingByAudio != null) {
            return Math.round((remainingByRate * 0.55) + (remainingByAudio * 0.45));
        }
        return Math.round(remainingByRate);
    }

    function setFileMeta(name, size, duration) {
        var meta = el('notaAudioFileMeta');
        if (!meta) return;
        var parts = [];
        if (name) parts.push(name);
        if (size) parts.push(formatBytes(size));
        if (duration != null) parts.push(formatDuration(duration));
        meta.textContent = parts.join(' · ');
        meta.classList.toggle('d-none', !parts.length);
    }

    function resetUi() {
        if (pollTimer) clearInterval(pollTimer);
        pollTimer = null;
        lastProgress = 0;
        processStartedAt = 0;
        setBusy(false);
        showPanel(false);
        setProgress(0, { force: true, mensaje: '', fase: 'subida' });
        setFileMeta('', null, null);
        var recLabel = el('notaAudioRecTimer');
        if (recLabel) {
            recLabel.textContent = '0:00';
            recLabel.classList.add('d-none');
        }
        var btnGrabar = el('btnNotaAudioGrabar');
        var btnParar = el('btnNotaAudioParar');
        if (btnGrabar) btnGrabar.classList.remove('d-none');
        if (btnParar) btnParar.classList.add('d-none');
    }

    function uploadBlob(blob, filename) {
        if (busy) return;
        setBusy(true);
        showPanel(true);
        lastProgress = 0;
        processStartedAt = Date.now();
        setFileMeta(filename, blob.size, null);
        setProgress(2, {
            force: true,
            fase: 'subida',
            mensaje: t('Subiendo audio…'),
        });

        var form = new FormData();
        form.append('audio', blob, filename);
        var token = csrfToken();
        if (token) form.append('csrf_token', token);

        var xhr = new XMLHttpRequest();
        xhr.open('POST', '/notas/audio/subir');
        if (token) xhr.setRequestHeader('X-CSRFToken', token);

        xhr.upload.onprogress = function (e) {
            if (!e.lengthComputable) return;
            var upPct = Math.round((e.loaded / e.total) * 12); // 0–12%
            setProgress(Math.max(2, upPct), {
                fase: 'subida',
                mensaje: t('Subiendo audio…') + ' ' + Math.round((e.loaded / e.total) * 100) + '%',
            });
        };

        xhr.onload = function () {
            var data;
            try {
                data = JSON.parse(xhr.responseText || '{}');
            } catch (err) {
                data = { success: false, message: t('Respuesta inválida del servidor') };
            }
            if (xhr.status >= 400 || !data.success) {
                setBusy(false);
                setProgress(lastProgress, {
                    error: true,
                    fase: 'error',
                    mensaje: data.message || t('Error al subir el audio'),
                });
                return;
            }
            if (data.duracion_segundos != null) {
                setFileMeta(data.archivo_nombre || filename, blob.size, data.duracion_segundos);
            }
            setProgress(15, {
                fase: 'preparando',
                mensaje: t('Audio recibido. Procesando…'),
            });
            pollJob(data.job_id, data.duracion_segundos);
        };

        xhr.onerror = function () {
            setBusy(false);
            setProgress(lastProgress, {
                error: true,
                fase: 'error',
                mensaje: t('Fallo de conexión al subir el audio'),
            });
        };

        xhr.send(form);
    }

    function pollJob(jobId, duracionSeg) {
        if (pollTimer) clearInterval(pollTimer);
        pollStartedAt = Date.now();

        function tick() {
            if (Date.now() - pollStartedAt > MAX_POLL_MS) {
                clearInterval(pollTimer);
                pollTimer = null;
                setBusy(false);
                setProgress(lastProgress, {
                    error: true,
                    fase: 'error',
                    mensaje: t('El procesamiento está tardando demasiado. Revisa los logs de Celery o inténtalo de nuevo.'),
                });
                return;
            }

            fetch('/notas/audio/' + jobId + '/estado')
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    if (!data.success) throw new Error(data.message || t('Error de estado'));

                    var pct = Number(data.progreso) || 0;
                    if (data.estado === 'pendiente' || data.estado === 'procesando') {
                        pct = Math.max(pct, 15);
                    }
                    var detalle = '';
                    if (data.meta && data.meta.trozo_actual && data.meta.trozos_total) {
                        detalle = t('Trozo') + ' ' + data.meta.trozo_actual +
                            ' / ' + data.meta.trozos_total;
                    }
                    var eta = estimateEta(pct, duracionSeg || data.duracion_segundos);

                    setProgress(pct, {
                        fase: data.fase || data.estado,
                        mensaje: data.mensaje || t('Procesando…'),
                        detalle: detalle,
                        etaSeconds: eta,
                    });

                    if (data.estado === 'completado') {
                        clearInterval(pollTimer);
                        pollTimer = null;
                        setProgress(100, {
                            force: true,
                            ok: true,
                            fase: 'completado',
                            mensaje: t('Nota privada creada. Recargando…'),
                            etaSeconds: 0,
                        });
                        setTimeout(function () { window.location.reload(); }, 1400);
                    } else if (data.estado === 'error') {
                        clearInterval(pollTimer);
                        pollTimer = null;
                        setBusy(false);
                        setProgress(pct, {
                            error: true,
                            fase: 'error',
                            mensaje: data.error || data.mensaje || t('Error al procesar el audio'),
                        });
                    }
                })
                .catch(function (err) {
                    clearInterval(pollTimer);
                    pollTimer = null;
                    setBusy(false);
                    setProgress(lastProgress, {
                        error: true,
                        fase: 'error',
                        mensaje: err.message || t('Error de conexión'),
                    });
                });
        }

        tick();
        pollTimer = setInterval(tick, 1500);
    }

    function startRecording() {
        if (busy) return;
        recordedChunks = [];
        navigator.mediaDevices.getUserMedia({ audio: true })
            .then(function (stream) {
                recordStream = stream;
                var mime = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
                    ? 'audio/webm;codecs=opus'
                    : 'audio/webm';
                mediaRecorder = new MediaRecorder(stream, { mimeType: mime });
                mediaRecorder.ondataavailable = function (e) {
                    if (e.data && e.data.size > 0) recordedChunks.push(e.data);
                };
                mediaRecorder.onstop = function () {
                    if (recordStream) {
                        recordStream.getTracks().forEach(function (tr) { tr.stop(); });
                        recordStream = null;
                    }
                    if (recordTimer) {
                        clearInterval(recordTimer);
                        recordTimer = null;
                    }
                    var blob = new Blob(recordedChunks, { type: mime });
                    uploadBlob(blob, 'grabacion.webm');
                };
                mediaRecorder.start(1000);
                recordStartedAt = Date.now();
                var recLabel = el('notaAudioRecTimer');
                if (recLabel) {
                    recLabel.classList.remove('d-none');
                    recLabel.textContent = '0:00';
                }
                recordTimer = setInterval(function () {
                    var secs = Math.floor((Date.now() - recordStartedAt) / 1000);
                    if (recLabel) recLabel.textContent = formatDuration(secs);
                }, 250);

                el('btnNotaAudioGrabar').classList.add('d-none');
                el('btnNotaAudioParar').classList.remove('d-none');
                showPanel(true);
                setProgress(0, {
                    force: true,
                    fase: 'subida',
                    mensaje: t('Grabando… pulsa Parar cuando termines.'),
                });
                var panel = el('notaAudioProgressPanel');
                if (panel) panel.classList.add('is-recording');
            })
            .catch(function () {
                Swal.fire(t('Micrófono'), t('No se pudo acceder al micrófono.'), 'error');
            });
    }

    function stopRecording() {
        var panel = el('notaAudioProgressPanel');
        if (panel) panel.classList.remove('is-recording');
        if (mediaRecorder && mediaRecorder.state !== 'inactive') {
            mediaRecorder.stop();
        }
        el('btnNotaAudioParar').classList.add('d-none');
        el('btnNotaAudioGrabar').classList.remove('d-none');
    }

    function bindDropzone() {
        var zone = el('notaAudioDropzone');
        var input = el('notaAudioFile');
        if (!zone || !input) return;

        zone.addEventListener('click', function (e) {
            if (busy || e.target.closest('button')) return;
            input.click();
        });

        ['dragenter', 'dragover'].forEach(function (evt) {
            zone.addEventListener(evt, function (e) {
                e.preventDefault();
                e.stopPropagation();
                if (!busy) zone.classList.add('is-dragover');
            });
        });
        ['dragleave', 'drop'].forEach(function (evt) {
            zone.addEventListener(evt, function (e) {
                e.preventDefault();
                e.stopPropagation();
                zone.classList.remove('is-dragover');
            });
        });
        zone.addEventListener('drop', function (e) {
            if (busy) return;
            var file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
            if (file) uploadBlob(file, file.name);
        });
    }

    window.initNotaAudioUI = function () {
        var input = el('notaAudioFile');
        var btnGrabar = el('btnNotaAudioGrabar');
        var btnParar = el('btnNotaAudioParar');
        var iosHint = el('notaAudioIosHint');
        if (!input) return;

        var isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) && !window.MSStream;
        if (isIOS && iosHint) iosHint.classList.remove('d-none');
        if (!canRecord()) {
            var recCard = el('notaAudioRecCard');
            if (recCard) recCard.classList.add('d-none');
            if (btnGrabar) btnGrabar.classList.add('d-none');
        }

        bindDropzone();

        input.addEventListener('change', function () {
            var file = input.files && input.files[0];
            if (!file) return;
            uploadBlob(file, file.name);
            input.value = '';
        });

        if (btnGrabar) btnGrabar.addEventListener('click', startRecording);
        if (btnParar) btnParar.addEventListener('click', stopRecording);

        $('#modalNotaAudio').on('hidden.bs.modal', function () {
            if (mediaRecorder && mediaRecorder.state === 'recording') {
                stopRecording();
            }
            if (!busy) resetUi();
        });
    };
})();
