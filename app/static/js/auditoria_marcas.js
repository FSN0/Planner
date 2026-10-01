/* Marcas manuales / corrección desde auditoría de fichajes */
(function () {
    var t = window.SP_T || function (key) { return key; };
    var selectedId = null;

    function csrfHeaders() {
        var meta = document.querySelector('meta[name="csrf-token"]');
        var token = meta ? meta.getAttribute('content') : '';
        var h = { 'Content-Type': 'application/json' };
        if (token) h['X-CSRFToken'] = token;
        return h;
    }

    function urls() {
        var root = document.getElementById('modalMarcaManual');
        if (!root) return {};
        return {
            list: root.getAttribute('data-url-list'),
            create: root.getAttribute('data-url-create'),
            fix: root.getAttribute('data-url-fix'),
            cancel: root.getAttribute('data-url-anular'),
        };
    }

    function toast(msg, ok) {
        if (typeof showToast === 'function') showToast(msg, !!ok);
        else alert(msg);
    }

    window.abrirModalMarcaManual = function () {
        selectedId = null;
        var now = new Date();
        var pad = function (n) { return String(n).padStart(2, '0'); };
        var local = now.getFullYear() + '-' + pad(now.getMonth() + 1) + '-' + pad(now.getDate())
            + 'T' + pad(now.getHours()) + ':' + pad(now.getMinutes());
        var el = document.getElementById('marcaOcurrido');
        if (el && !el.value) el.value = local;
        var f = document.getElementById('corrFecha');
        if (f && !f.value) f.value = local.slice(0, 10);
        if (window.jQuery) jQuery('#modalMarcaManual').modal('show');
    };

    window.guardarMarcaManual = function () {
        var u = urls();
        var payload = {
            user_id: parseInt(document.getElementById('marcaUserId').value, 10) || null,
            tipo: document.getElementById('marcaTipo').value,
            ocurrido_en: (document.getElementById('marcaOcurrido').value || '').replace('T', ' '),
            obra_id: parseInt(document.getElementById('marcaObraId').value, 10) || null,
            motivo: document.getElementById('marcaMotivo').value,
        };
        fetch(u.create, { method: 'POST', headers: csrfHeaders(), body: JSON.stringify(payload) })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.success) { toast(t('Marca registrada en el libro'), true); setTimeout(function () { location.reload(); }, 700); }
                else alert(data.error || t('Error'));
            })
            .catch(function () { alert(t('Error de red')); });
    };

    window.cargarMarcasDia = function () {
        var u = urls();
        var uid = document.getElementById('corrUserId').value;
        var fecha = document.getElementById('corrFecha').value;
        var box = document.getElementById('corrLista');
        if (!uid || !fecha) { alert(t('Indica trabajador y día')); return; }
        box.innerHTML = '<span class="text-muted small">' + t('Cargando…') + '</span>';
        fetch(u.list + '?user_id=' + encodeURIComponent(uid) + '&fecha=' + encodeURIComponent(fecha), {
            headers: csrfHeaders(),
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (!data.success) {
                    box.innerHTML = '<span class="text-danger small">' + (data.error || t('Error')) + '</span>';
                    return;
                }
                if (!data.eventos.length) {
                    box.innerHTML = '<span class="text-muted small">' + t('No hay marcas ese día.') + '</span>';
                    return;
                }
                var labels = {
                    entrada: t('Entrada'), salida: t('Salida'), pausa_inicio: t('Pausa'),
                    pausa_fin: t('Fin pausa'), anulacion: t('Anulación'), reasignacion_obra: t('Reasignación'),
                };
                box.innerHTML = data.eventos.map(function (e) {
                    var disabled = e.editable ? '' : 'disabled';
                    var badge = e.anulado ? ' <span class="badge badge-secondary">' + t('anulada') + '</span>' : '';
                    var tip = e.tipo === 'anulacion' ? ' (→ #' + e.evento_anulado_id + ')' : '';
                    return '<label class="d-block mb-1' + (e.anulado ? ' text-muted' : '') + '">'
                        + '<input type="radio" name="marcaSel" value="' + e.id + '" ' + disabled
                        + ' data-obra="' + (e.obra_id || '') + '"'
                        + ' data-local="' + (e.ocurrido_local || '') + '"> '
                        + '<strong>' + (labels[e.tipo] || e.tipo) + '</strong> ' + (e.ocurrido_local || '')
                        + (e.obra_nombre ? ' · ' + e.obra_nombre : '')
                        + ' <span class="text-muted">#' + e.secuencia + ' · ' + e.origen + '</span>'
                        + badge + tip + '</label>';
                }).join('');
                box.querySelectorAll('input[name="marcaSel"]').forEach(function (inp) {
                    inp.addEventListener('change', function () {
                        selectedId = parseInt(inp.value, 10);
                        if (inp.getAttribute('data-obra')) {
                            document.getElementById('corrObraId').value = inp.getAttribute('data-obra');
                        }
                        var loc = inp.getAttribute('data-local');
                        if (loc) document.getElementById('corrOcurrido').value = loc.replace(' ', 'T');
                    });
                });
            })
            .catch(function () { box.innerHTML = '<span class="text-danger small">' + t('Error de red') + '</span>'; });
    };

    window.corregirMarcaSeleccionada = function () {
        var u = urls();
        if (!selectedId) { alert(t('Selecciona una marca editable')); return; }
        var payload = {
            evento_id: selectedId,
            ocurrido_en: (document.getElementById('corrOcurrido').value || '').replace('T', ' ') || null,
            obra_id: document.getElementById('corrObraId').value
                ? parseInt(document.getElementById('corrObraId').value, 10) : null,
            motivo: document.getElementById('corrMotivo').value,
        };
        fetch(u.fix, { method: 'POST', headers: csrfHeaders(), body: JSON.stringify(payload) })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.success) { toast(t('Marca corregida (original anulada)'), true); setTimeout(function () { location.reload(); }, 700); }
                else alert(data.error || t('Error'));
            })
            .catch(function () { alert(t('Error de red')); });
    };

    window.anularMarcaSeleccionada = function () {
        var u = urls();
        if (!selectedId) { alert(t('Selecciona una marca editable')); return; }
        var motivo = document.getElementById('corrMotivo').value;
        if (!motivo || motivo.trim().length < 5) { alert(t('Indica un motivo (mín. 5 caracteres)')); return; }
        if (!confirm(t('¿Anular esta marca? Quedará registrada la anulación en el libro.'))) return;
        fetch(u.cancel, {
            method: 'POST', headers: csrfHeaders(),
            body: JSON.stringify({ evento_id: selectedId, motivo: motivo }),
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.success) { toast(t('Marca anulada'), true); setTimeout(function () { location.reload(); }, 700); }
                else alert(data.error || t('Error'));
            })
            .catch(function () { alert(t('Error de red')); });
    };
})();
