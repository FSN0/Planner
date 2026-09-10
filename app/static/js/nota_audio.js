/**
 * Notas por voz: subir / grabar con progreso.
 * Tras encolar el job, el procesado es Celery (segundo plano): se puede salir
 * de la pantalla; al volver se retoma el progreso o aparece la nota.
 */
(function () {
    'use strict';

    var t = window.SP_T || function (key) { return key; };
    var STORAGE_KEY = 'notaAudioActiveJob';
    var mediaRecorder = null;
    var recordedChunks = [];
    var recordStream = null;
    var recordTimer = null;
    var recordStartedAt = 0;
    var pollTimer = null;
    var processStartedAt = 0;
    var lastProgress = 0;
    var busy = false;
    var uploadInFlight = false;
    var activeJobId = null;
    var pollStartedAt = 0;
    var MAX_POLL_MS = 3.5 * 60 * 60 * 1000; // 3.5 h techo UI (audios largos)
    var defaultPromptCache = '';
    var promptLoaded = false;

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

    function persistJob(jobId, duracionSeg, archivoNombre) {
        activeJobId = jobId;
        try {
            sessionStorage.setItem(STORAGE_KEY, JSON.stringify({
                job_id: jobId,
                duracion_segundos: duracionSeg || null,
                archivo_nombre: archivoNombre || null,
                started_at: Date.now(),
            }));
        } catch (err) { /* ignore */ }
    }

    function clearPersistedJob() {
        activeJobId = null;
        try { sessionStorage.removeItem(STORAGE_KEY); } catch (err) { /* ignore */ }
    }

    function readPersistedJob() {
        try {
            var raw = sessionStorage.getItem(STORAGE_KEY);
            if (!raw) return null;
            var data = JSON.parse(raw);
            if (!data || !data.job_id) return null;
            return data;
        } catch (err) {
            return null;
        }
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

    function setBgHint(show) {
        var hint = el('notaAudioBgHint');
        if (hint) hint.classList.toggle('d-none', !show);
    }

    function setCancelVisible(show) {
        var btn = el('btnNotaAudioCancel');
        if (btn) btn.classList.toggle('d-none', !show);
    }

    function setPageBanner(show, mensaje) {
        var banner = el('notaAudioBgBanner');
        if (!banner) return;
        banner.classList.toggle('d-none', !show);
        var text = el('notaAudioBgBannerText');
        if (text && mensaje) text.textContent = mensaje;
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
        if (pctEl) {
            pctEl.textContent = opts.error ? t('Error') : (pct + '%');
        }
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
        setBgHint(false);
        setCancelVisible(false);
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

    function markProcessingBackground(mensaje) {
        setBusy(true);
        setBgHint(true);
        setCancelVisible(!!activeJobId);
        setPageBanner(
            true,
            mensaje || t('Hay una nota por voz procesándose en segundo plano. Puedes seguir trabajando; la nota aparecerá al terminar.')
        );
    }

    function failJobUi(mensaje, opts) {
        opts = opts || {};
        if (pollTimer) clearInterval(pollTimer);
        pollTimer = null;
        clearPersistedJob();
        uploadInFlight = false;
        setPageBanner(false);
        setBgHint(false);
        setCancelVisible(false);
        setBusy(false);
        showPanel(true);
        lastProgress = 0;
        setProgress(0, {
            force: true,
            error: true,
            fase: 'error',
            mensaje: mensaje || t('Ha habido un error al procesar el audio.'),
            detalle: opts.detalle || '',
            etaSeconds: 0,
        });
    }

    function currentSummaryPrompt() {
        var ta = el('notaAudioPrompt');
        if (ta && ta.value.trim()) return ta.value.trim();
        return defaultPromptCache || '';
    }

    function loadSummaryPrompt() {
        return fetch('/notas/audio/prompt')
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (!data || !data.success) return;
                defaultPromptCache = data.default_prompt || '';
                var ta = el('notaAudioPrompt');
                if (ta && !promptLoaded) {
                    ta.value = data.prompt || data.default_prompt || '';
                    promptLoaded = true;
                }
            })
            .catch(function () { /* ignore */ });
    }

    function cancelActiveJob() {
        if (!activeJobId) return;
        var jobId = activeJobId;
        var token = csrfToken();
        var btn = el('btnNotaAudioCancel');
        if (btn) btn.disabled = true;

        fetch('/notas/audio/' + jobId + '/cancelar', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': token || '',
            },
            body: JSON.stringify({ csrf_token: token || '' }),
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (btn) btn.disabled = false;
                if (!data || !data.success) {
                    Swal.fire(
                        t('Cancelar'),
                        (data && data.message) || t('No se pudo cancelar el procesamiento.'),
                        'error'
                    );
                    return;
                }
                failJobUi(t('Procesamiento cancelado.'));
            })
            .catch(function () {
                if (btn) btn.disabled = false;
                Swal.fire(t('Cancelar'), t('Error de conexión al cancelar.'), 'error');
            });
    }

    function uploadBlob(blob, filename) {
        if (busy) return;
        setBusy(true);
        uploadInFlight = true;
        showPanel(true);
        setBgHint(false);
        setCancelVisible(false);
        setPageBanner(false);
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
        var promptText = currentSummaryPrompt();
        if (promptText) form.append('summary_prompt', promptText);
        var saveDefault = el('notaAudioPromptSaveDefault');
        if (saveDefault && saveDefault.checked) {
            form.append('save_prompt_default', '1');
        }
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
            uploadInFlight = false;
            var data;
            try {
                data = JSON.parse(xhr.responseText || '{}');
            } catch (err) {
                data = { success: false, message: t('Respuesta inválida del servidor') };
            }
            if (xhr.status >= 400 || !data.success) {
                failJobUi(
                    data.message || t('Error al subir el audio. Revisa el archivo e inténtalo de nuevo.')
                );
                return;
            }
            if (data.duracion_segundos != null) {
                setFileMeta(data.archivo_nombre || filename, blob.size, data.duracion_segundos);
            }
            persistJob(data.job_id, data.duracion_segundos, data.archivo_nombre || filename);
            markProcessingBackground(
                t('Audio recibido. Sigue procesándose en segundo plano: puedes cerrar esta ventana o salir de Notas.')
            );
            setCancelVisible(true);
            setProgress(15, {
                force: true,
                fase: 'preparando',
                mensaje: t('Audio recibido. Procesando en segundo plano…'),
            });
            pollJob(data.job_id, data.duracion_segundos);
        };

        xhr.onerror = function () {
            failJobUi(t('Fallo de conexión al subir el audio. Comprueba la red e inténtalo de nuevo.'));
        };

        xhr.send(form);
    }

    function pollJob(jobId, duracionSeg) {
        if (pollTimer) clearInterval(pollTimer);
        pollStartedAt = Date.now();
        activeJobId = jobId;
        var consecutivePollFails = 0;

        function tick() {
            if (Date.now() - pollStartedAt > MAX_POLL_MS) {
                clearInterval(pollTimer);
                pollTimer = null;
                // No marcar error fatal: el job puede seguir en Celery.
                markProcessingBackground(
                    t('Sigue procesándose en el servidor. Vuelve más tarde: la nota aparecerá al terminar.')
                );
                setProgress(lastProgress, {
                    fase: 'preparando',
                    mensaje: t('Procesamiento largo en segundo plano. Puedes salir y volver más tarde.'),
                });
                return;
            }

            fetch('/notas/audio/' + jobId + '/estado')
                .then(function (r) {
                    if (r.status === 404) {
                        return {
                            success: false,
                            fatal: true,
                            message: t('No se encontró el trabajo de audio (puede haberse perdido).'),
                        };
                    }
                    return r.json().then(function (data) {
                        data = data || {};
                        data._httpStatus = r.status;
                        return data;
                    });
                })
                .then(function (data) {
                    if (!data || data.fatal || (!data.success && data._httpStatus >= 400)) {
                        consecutivePollFails += 1;
                        if ((data && data.fatal) || consecutivePollFails >= 5) {
                            failJobUi(
                                (data && data.message) ||
                                t('Error al consultar el estado del audio.')
                            );
                            return;
                        }
                        markProcessingBackground(
                            t('Sin conexión momentánea. El audio sigue en el servidor; reintentando…')
                        );
                        return;
                    }
                    if (!data.success) {
                        consecutivePollFails += 1;
                        if (consecutivePollFails >= 5) {
                            failJobUi(data.message || t('Error al consultar el estado del audio.'));
                        }
                        return;
                    }
                    consecutivePollFails = 0;

                    if (data.estado === 'completado') {
                        clearInterval(pollTimer);
                        pollTimer = null;
                        clearPersistedJob();
                        setPageBanner(false);
                        setBgHint(false);
                        setCancelVisible(false);
                        setBusy(false);
                        setProgress(100, {
                            force: true,
                            ok: true,
                            fase: 'completado',
                            mensaje: t('Nota privada creada. Recargando…'),
                            etaSeconds: 0,
                        });
                        setTimeout(function () { window.location.reload(); }, 1400);
                        return;
                    }

                    if (data.estado === 'error' || data.estado === 'cancelado') {
                        failJobUi(
                            data.estado === 'cancelado'
                                ? t('Procesamiento cancelado.')
                                : (data.error || data.mensaje || t('Error al procesar el audio.'))
                        );
                        return;
                    }

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

                    if (data.archivo_nombre) {
                        setFileMeta(data.archivo_nombre, null, data.duracion_segundos);
                    }

                    setCancelVisible(true);
                    markProcessingBackground(
                        t('Procesando nota por voz en segundo plano…') +
                        ' ' + Math.round(pct) + '%'
                    );
                })
                .catch(function () {
                    consecutivePollFails += 1;
                    if (consecutivePollFails >= 8) {
                        failJobUi(
                            t('No se pudo comprobar el estado del audio tras varios intentos. Si el problema continúa, cancela e inténtalo de nuevo.')
                        );
                        return;
                    }
                    markProcessingBackground(
                        t('Sin conexión momentánea. El audio sigue en el servidor; reintentando…')
                    );
                });
        }

        tick();
        pollTimer = setInterval(tick, 2000);
    }

    function resumeActiveJobs() {
        fetch('/notas/audio/activos')
            .then(function (r) { return r.json(); })
            .then(function (data) {
                var jobs = (data && data.jobs) || [];
                var job = jobs[0];
                if (!job) {
                    var stored = readPersistedJob();
                    if (stored) {
                        // Job ya terminó (o no existe): limpiar y no bloquear UI.
                        fetch('/notas/audio/' + stored.job_id + '/estado')
                            .then(function (r) { return r.json(); })
                            .then(function (st) {
                                if (!st.success) {
                                    clearPersistedJob();
                                    return;
                                }
                                if (st.estado === 'completado') {
                                    clearPersistedJob();
                                    window.location.reload();
                                    return;
                                }
                                if (st.estado === 'error' || st.estado === 'cancelado') {
                                    clearPersistedJob();
                                    showPanel(true);
                                    failJobUi(
                                        st.estado === 'cancelado'
                                            ? t('Procesamiento cancelado.')
                                            : (st.error || st.mensaje || t('La nota por voz falló en el último intento.'))
                                    );
                                    return;
                                }
                                beginResume(st);
                            })
                            .catch(function () { /* ignore */ });
                    }
                    return;
                }
                if (job.estado === 'error' || job.estado === 'cancelado') {
                    failJobUi(
                        job.estado === 'cancelado'
                            ? t('Procesamiento cancelado.')
                            : (job.error || job.mensaje || t('Error al procesar el audio.'))
                    );
                    return;
                }
                beginResume(job);
            })
            .catch(function () { /* ignore */ });
    }

    function beginResume(job) {
        if (!job || !job.job_id) return;
        if (pollTimer && activeJobId === job.job_id) return;

        persistJob(job.job_id, job.duracion_segundos, job.archivo_nombre);
        processStartedAt = Date.now();
        lastProgress = 0;
        showPanel(true);
        setFileMeta(job.archivo_nombre || '', null, job.duracion_segundos);
        setProgress(Math.max(15, Number(job.progreso) || 15), {
            force: true,
            fase: job.fase || job.estado,
            mensaje: job.mensaje || t('Retomando procesamiento en segundo plano…'),
        });
        markProcessingBackground(
            t('Hay una nota por voz procesándose en segundo plano. Puedes seguir trabajando; la nota aparecerá al terminar.')
        );
        setCancelVisible(true);
        pollJob(job.job_id, job.duracion_segundos);
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

        var btnCancel = el('btnNotaAudioCancel');
        if (btnCancel) btnCancel.addEventListener('click', cancelActiveJob);

        var promptToggle = el('btnNotaAudioPromptToggle');
        var promptPanel = el('notaAudioPromptPanel');
        if (promptToggle && promptPanel) {
            promptToggle.addEventListener('click', function () {
                var open = promptPanel.classList.toggle('d-none') === false;
                promptToggle.classList.toggle('is-open', open);
                promptToggle.setAttribute('aria-expanded', open ? 'true' : 'false');
                if (open) loadSummaryPrompt();
            });
        }
        var btnResetPrompt = el('btnNotaAudioPromptReset');
        if (btnResetPrompt) {
            btnResetPrompt.addEventListener('click', function () {
                var token = csrfToken();
                fetch('/notas/audio/prompt', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': token || '',
                    },
                    body: JSON.stringify({ reset: true, csrf_token: token || '' }),
                })
                    .then(function (r) { return r.json(); })
                    .then(function (data) {
                        if (!data || !data.success) return;
                        defaultPromptCache = data.default_prompt || defaultPromptCache;
                        var ta = el('notaAudioPrompt');
                        if (ta) ta.value = data.prompt || data.default_prompt || '';
                    })
                    .catch(function () { /* ignore */ });
            });
        }
        loadSummaryPrompt();

        var bannerOpen = el('notaAudioBgBannerOpen');
        if (bannerOpen) {
            bannerOpen.addEventListener('click', function () {
                $('#modalNotaAudio').modal('show');
            });
        }
        var bannerCancel = el('notaAudioBgBannerCancel');
        if (bannerCancel) {
            bannerCancel.addEventListener('click', cancelActiveJob);
        }

        // Solo avisar si se cierra la pestaña a mitad de la subida HTTP.
        window.addEventListener('beforeunload', function (e) {
            if (!uploadInFlight) return;
            e.preventDefault();
            e.returnValue = '';
        });

        $('#modalNotaAudio').on('hidden.bs.modal', function () {
            if (mediaRecorder && mediaRecorder.state === 'recording') {
                stopRecording();
            }
            // Si hay job activo, no resetear: sigue en segundo plano.
            if (activeJobId || pollTimer) {
                markProcessingBackground(
                    t('El audio sigue procesándose en segundo plano. La nota aparecerá cuando termine.')
                );
                return;
            }
            if (!busy) resetUi();
        });

        resumeActiveJobs();
    };
})();
