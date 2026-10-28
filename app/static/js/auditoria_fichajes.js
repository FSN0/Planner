/* Auditoría de fichajes: pestañas Por resolver / Cumplimiento / Historial.
 * Configuración y textos llegan en window.AUD_CFG (los pinta la plantilla). */
(function () {
  'use strict';

  var CFG = window.AUD_CFG || {};
  var T = CFG.i18n || {};
  var U = CFG.urls || {};

  var state = {
    tab: 'resolver',
    q: '',
    rango: CFG.rango || '30',
    tipo: '',
    geo: false,
    hist: { page: 1, per: 25, sort: 'fecha', dir: 'desc', origen: '', loaded: false },
    cumpLoaded: false,
    sel: null,
    cases: {},
    sort: { key: null, dir: 'asc' },
  };
  var charts = {};
  var TIMELINE_OPTS = {
    modalId: 'modalTimelineFichaje',
    apiBase: '/sync/timeline_dia',
    loadingMessage: T.timeline_loading,
    canResolveAudit: !!CFG.can_resolve,
    auditUrl: U.auditoria,
  };

  /* ---------- utilidades ---------- */

  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }

  function escapeHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function urlFor(kind, id) {
    var tpl = U[kind];
    if (!tpl || id == null || id === '') return '';
    return String(tpl).replace('__ID__', String(id));
  }

  function linkHtml(kind, id, label, cls) {
    var txt = escapeHtml(label || '');
    if (!txt) return '';
    var href = urlFor(kind, id);
    if (!href) return txt;
    return '<a class="aud-link' + (cls ? ' ' + cls : '') + '" href="' + escapeHtml(href) +
      '" target="_blank" rel="noopener" onclick="event.stopPropagation()">' + txt + '</a>';
  }

  function debounce(fn, ms) {
    var t;
    return function () {
      var args = arguments, ctx = this;
      clearTimeout(t);
      t = setTimeout(function () { fn.apply(ctx, args); }, ms);
    };
  }

  function csrfHeaders() {
    var headers = { 'Content-Type': 'application/json' };
    var meta = document.querySelector('meta[name="csrf-token"]');
    var token = meta ? meta.getAttribute('content') : '';
    if (!token) {
      var parts = ('; ' + document.cookie).split('; csrf_token=');
      if (parts.length === 2) token = parts.pop().split(';').shift();
    }
    if (token) headers['X-CSRFToken'] = token;
    return headers;
  }

  var toastTimer = null;
  window.showToast = function (message, isSuccess) {
    var toast = document.getElementById('customToast');
    var icon = document.getElementById('toastIcon');
    var text = document.getElementById('toastMsg');
    if (!toast) return;
    toast.classList.add('show');
    text.innerText = message;
    icon.className = isSuccess ? 'fas fa-check-circle text-success' : 'fas fa-spinner fa-spin text-info';
    clearTimeout(toastTimer);
    if (isSuccess) toastTimer = setTimeout(hideToast, 3500);
  };
  function hideToast() {
    var toast = document.getElementById('customToast');
    if (toast) toast.classList.remove('show');
  }

  function getJson(url, params) {
    var qs = Object.keys(params || {})
      .filter(function (k) { return params[k] !== '' && params[k] != null; })
      .map(function (k) { return encodeURIComponent(k) + '=' + encodeURIComponent(params[k]); })
      .join('&');
    return fetch(url + (qs ? '?' + qs : ''), { credentials: 'same-origin', headers: { 'Accept': 'application/json' } })
      .then(function (res) {
        return res.json().catch(function () { return { success: false, error: T.invalid }; });
      });
  }

  /* ---------- pestañas ---------- */

  function sharedQ() {
    return (($('#audSearch') || {}).value || '').trim();
  }

  function invalidateLazy() {
    state.hist.loaded = false;
    state.cumpLoaded = false;
  }

  function switchTab(name) {
    if (['resolver', 'cumplimiento', 'historial'].indexOf(name) < 0) name = 'resolver';
    state.tab = name;
    $$('.aud-tab').forEach(function (b) { b.classList.toggle('is-active', b.dataset.tab === name); });
    $$('.aud-panel').forEach(function (p) { p.hidden = p.dataset.panel !== name; });
    try {
      var url = new URL(window.location.href);
      url.searchParams.set('tab', name);
      window.history.replaceState(null, '', url.toString());
    } catch (e) { /* ignore */ }
    if (name === 'cumplimiento' && !state.cumpLoaded) loadCumplimiento();
    if (name === 'historial' && !state.hist.loaded) loadHistorial();
    if (name === 'resolver') {
      applyColaFilters();
      fitSplit();
    }
  }

  function onSharedSearch() {
    state.q = sharedQ();
    invalidateLazy();
    if (state.tab === 'resolver') applyColaFilters();
    else if (state.tab === 'historial') {
      state.hist.page = 1;
      loadHistorial();
    } else if (state.tab === 'cumplimiento') {
      loadCumplimiento();
    }
  }

  function onSharedPeriod() {
    var sel = $('#audPeriodo');
    state.rango = (sel && sel.value) || '30';
    invalidateLazy();
    if (state.tab === 'resolver') refreshCola();
    else if (state.tab === 'historial') {
      state.hist.page = 1;
      loadHistorial();
    } else if (state.tab === 'cumplimiento') {
      loadCumplimiento();
    }
  }

  /* ---------- Por resolver ---------- */

  function applyColaFilters() {
    var q = sharedQ().toLowerCase();
    var counts = { '': 0, no_ficho: 0, otra_obra: 0, sin_planificar: 0, disputa: 0 };
    var geoCount = 0;
    $$('#audCases .aud-case').forEach(function (c) {
      var okQ = !q || (c.dataset.search || '').indexOf(q) !== -1;
      var esGeo = c.dataset.geo === 'dudosa';
      if (okQ && esGeo) geoCount++;
      var okGeo = !state.geo || esGeo;
      if (okQ && okGeo) {
        counts['']++;
        if (counts[c.dataset.tipo] !== undefined) counts[c.dataset.tipo]++;
      }
      var okT = !state.tipo || c.dataset.tipo === state.tipo;
      c.style.display = (okQ && okGeo && okT) ? '' : 'none';
    });
    $$('[data-count-tipo]').forEach(function (el) {
      el.textContent = counts[el.dataset.countTipo] || 0;
    });
    var g = $('[data-count-geo]');
    if (g) g.textContent = geoCount;
    // Si lo seleccionado queda oculto por el filtro, pasa al primero visible.
    var cur = state.sel && document.getElementById('row-' + state.sel);
    if (!cur || cur.style.display === 'none') selectCase(firstVisibleId(), false);
    // «Desacuerdo · oficina» solo se muestra si hay alguno (es raro).
    $$('.js-aud-tipo[data-tipo="disputa"]').forEach(function (p) {
      p.hidden = (counts.disputa || 0) <= 0 && state.tipo !== 'disputa';
    });
  }

  /* ----- selección y panel de detalle ----- */

  function visibleRows() {
    return $$('#audCases tbody tr').filter(function (r) { return r.style.display !== 'none'; });
  }

  function firstVisibleId() {
    var rows = visibleRows();
    return rows.length ? parseInt(rows[0].dataset.caseId, 10) : null;
  }

  function loadCases() {
    state.cases = {};
    var node = document.getElementById('audCasosData');
    if (!node) return;
    try {
      JSON.parse(node.textContent || '[]').forEach(function (c) { state.cases[c.id] = c; });
    } catch (e) { console.error('audCasosData', e); }
  }

  function syncHoy() {
    var src = $('.aud-hoy-src');
    var pop = $('#audHoyPop');
    if (!src || !pop) return;
    pop.innerHTML = src.innerHTML;
    var n = $('#audHoyCount');
    if (n) n.textContent = src.dataset.count || '0';
  }

  var QUE_HACER = {
    no_ficho: 'd_no_fichar', otra_obra: 'd_otra_obra', sin_planificar: 'd_sin_plan', disputa: 'd_disputa',
  };

  function horario(c) {
    if (!c.entrada) return '';
    return c.entrada + (c.salida ? '–' + c.salida : '');
  }

  function renderDetail(c) {
    var box = $('#audDetail');
    if (!box) return;
    if (!c) {
      box.innerHTML = '<div class="aud-d-empty">' + escapeHtml(state.sel === null && !Object.keys(state.cases).length
        ? T.d_all_done : T.d_empty) + '</div>';
      return;
    }
    var h = '';
    h += '<div class="aud-d-head"><div><div class="aud-d-who">' +
      linkHtml('worker', c.user_id, c.user_nombre) + '</div>' +
      '<div class="aud-d-sub">' + escapeHtml(c.fecha_txt) +
      (c.user_categoria ? ' · ' + escapeHtml(c.user_categoria) : '') + '</div></div>' +
      '<span class="aud-chip aud-chip--' + escapeHtml(c.tipo) + '">' + escapeHtml(c.tipo_label) + '</span></div>';

    h += '<div class="aud-d-cols">' +
      '<div class="aud-d-col"><div class="aud-d-k">' + escapeHtml(T.d_planned) + '</div>' +
      '<div class="aud-d-v">' +
        (c.plan ? linkHtml('obra', c.plan.id, c.plan.nombre) : escapeHtml(T.d_unplanned)) +
      '</div>' +
      (c.jefe_plan
        ? '<div class="aud-d-line">' + escapeHtml(T.d_boss) + ': ' + linkHtml('worker', c.jefe_plan_id, c.jefe_plan) + '</div>'
        : '') +
      '</div>' +
      '<div class="aud-d-col"><div class="aud-d-k">' + escapeHtml(T.d_clocked) + '</div>' +
      '<div class="aud-d-v">' +
        (c.real ? linkHtml('obra', c.real.id, c.real.nombre) : escapeHtml(T.d_nopunch)) +
      '</div>' +
      (c.real && horario(c) ? '<div class="aud-d-line">' + escapeHtml(horario(c)) + '</div>' : '') +
      (c.jefe_real
        ? '<div class="aud-d-line">' + escapeHtml(T.d_boss) + ': ' + linkHtml('worker', c.jefe_real_id, c.jefe_real) + '</div>'
        : '') +
      '</div></div>';

    if (c.geo_dudosa) {
      h += '<div class="aud-d-note"><span class="aud-geo"><i class="fas fa-map-marker-alt"></i> ' + escapeHtml(T.d_geo) +
        (c.geo_distancia ? ' · ' + Math.round(c.geo_distancia) + ' m' : '') + '</span></div>';
    }
    if (c.detalle) h += '<div class="aud-d-note"><i class="fas fa-info-circle"></i> ' + escapeHtml(c.detalle) + '</div>';
    if (c.nota) h += '<div class="aud-d-note"><i class="far fa-comment-alt"></i> ' + escapeHtml(c.nota) + '</div>';
    if (c.ack_plan || c.ack_real) {
      h += '<div class="aud-d-progress">' +
        '<span class="' + (c.ack_plan ? 'is-done' : '') + '"><i class="fas fa-' + (c.ack_plan ? 'check-circle' : 'circle') + '"></i> ' +
        escapeHtml(c.ack_plan_label || T.d_planned) + (c.ack_plan_por ? ' · ' + escapeHtml(c.ack_plan_por) : '') + '</span>' +
        '<span class="' + (c.ack_real ? 'is-done' : '') + '"><i class="fas fa-' + (c.ack_real ? 'check-circle' : 'circle') + '"></i> ' +
        escapeHtml(c.ack_real_label || T.d_clocked) + (c.ack_real_por ? ' · ' + escapeHtml(c.ack_real_por) : '') + '</span></div>';
    }

    h += '<div class="aud-d-todo"><div class="aud-d-k">' + escapeHtml(T.d_todo) + '</div>';
    if (c.acciones && c.acciones.length) {
      h += '<p>' + escapeHtml(T[QUE_HACER[c.tipo]] || '') + '</p><div class="aud-d-actions">';
      c.acciones.forEach(function (a, i) {
        h += '<button type="button" class="aud-btn aud-btn--block aud-btn--' +
          (i === 0 ? 'primary' : (a.estilo === 'danger' ? 'danger' : 'ghost')) + ' js-audit-resolve" ' +
          'data-registro-id="' + c.id + '" data-accion="' + escapeHtml(a.accion) + '" title="' + escapeHtml(a.title) + '">' +
          escapeHtml(a.label) + '</button>';
      });
      h += '</div>';
    } else {
      h += '<p>' + escapeHtml(c.esperando || (CFG.can_resolve ? T.d_other : T.d_readonly)) + '</p>';
    }
    h += '</div>';
    h += '<button type="button" class="aud-d-link js-aud-dia" data-user-id="' + c.user_id + '" data-fecha="' + escapeHtml(c.fecha_iso) +
      '"><i class="far fa-calendar-alt"></i> ' + escapeHtml(T.d_day) + '</button>';
    box.innerHTML = h;
  }

  function selectCase(id, scroll) {
    state.sel = id || null;
    $$('#audCases tbody tr').forEach(function (r) {
      r.classList.toggle('is-selected', id != null && parseInt(r.dataset.caseId, 10) === id);
    });
    renderDetail(id != null ? state.cases[id] : null);
    if (scroll && id != null) {
      var row = document.getElementById('row-' + id);
      if (row) row.scrollIntoView({ block: 'nearest' });
    }
  }

  function moveSelection(delta) {
    var rows = visibleRows();
    if (!rows.length) return;
    var idx = rows.findIndex(function (r) { return parseInt(r.dataset.caseId, 10) === state.sel; });
    idx = Math.max(0, Math.min(rows.length - 1, idx < 0 ? 0 : idx + delta));
    selectCase(parseInt(rows[idx].dataset.caseId, 10), true);
  }

  function nextIdAfter(id) {
    var rows = visibleRows();
    var idx = rows.findIndex(function (r) { return parseInt(r.dataset.caseId, 10) === id; });
    if (idx < 0) return null;
    var nxt = rows[idx + 1] || rows[idx - 1];
    return nxt ? parseInt(nxt.dataset.caseId, 10) : null;
  }

  function sortCases(key) {
    var s = state.sort;
    s.dir = (s.key === key && s.dir === 'asc') ? 'desc' : 'asc';
    s.key = key;
    var tbody = $('#audCases tbody');
    if (!tbody) return;
    var rows = $$('tr', tbody);
    var num = (key === 'peso');
    rows.sort(function (a, b) {
      var va = key === 'fecha' ? a.dataset.fecha : (num ? parseInt(a.dataset.peso, 10) : a.dataset[key]);
      var vb = key === 'fecha' ? b.dataset.fecha : (num ? parseInt(b.dataset.peso, 10) : b.dataset[key]);
      var r = va < vb ? -1 : (va > vb ? 1 : 0);
      return s.dir === 'asc' ? r : -r;
    });
    rows.forEach(function (r) { tbody.appendChild(r); });
  }

  function fitSplit() {
    var el = $('#audSplit');
    if (!el || el.offsetParent === null || window.innerWidth <= 991) return;
    var top = el.getBoundingClientRect().top;
    el.style.height = Math.max(360, window.innerHeight - top - 16) + 'px';
  }

  function setCounters(count, resueltos) {
    var tc = $('#audTabCount');
    if (tc) {
      tc.textContent = count;
      tc.classList.toggle('is-alert', count > 0);
    }
    var k = $('#audKpiPorResolver');
    if (k) {
      $('[data-kpi="count"]', k).textContent = count;
      k.classList.toggle('aud-kpi--alert', count > 0);
      k.classList.toggle('aud-kpi--ok', count === 0);
    }
    var r = $('[data-kpi="resueltos"]');
    if (r && resueltos != null) r.textContent = resueltos;
  }

  function focusCase() {
    var f = CFG.focus || {};
    var el = null;
    if (f.registro_id) el = document.getElementById('row-' + f.registro_id);
    if (!el && f.user_id && f.fecha) {
      el = $('.aud-case[data-user-id="' + f.user_id + '"][data-fecha="' + f.fecha + '"]');
    }
    if (!el) return false;
    selectCase(parseInt(el.dataset.caseId, 10), true);
    return true;
  }

  function refreshCola() {
    return getJson(U.cola, { rango: state.rango }).then(function (data) {
      if (!data || !data.success) {
        window.showToast((data && data.error) || T.load_fail, false);
        return;
      }
      var previa = state.sel;
      var siguiente = state.pendingNext;
      var resuelto = state.pendingId;
      state.pendingNext = null;
      state.pendingId = null;
      $('#audColaBody').innerHTML = data.html;
      loadCases();
      syncHoy();
      setCounters(data.count, data.resueltos_7d);
      state.sort.key = null;
      state.sel = null;
      applyColaFilters();
      // Tras decidir, se salta al siguiente caso; si no, se conserva la selección.
      var objetivo = (resuelto != null && document.getElementById('row-' + resuelto))
        ? resuelto  // sigue pendiente (falta el otro lado): se queda en el mismo caso
        : (siguiente != null ? siguiente : previa);
      var fila = objetivo != null && document.getElementById('row-' + objetivo);
      if (fila && fila.style.display !== 'none') selectCase(objetivo, true);
      fitSplit();
    });
  }

  /* ---------- resolver / reabrir ---------- */

  function restoreCase(row) {
    state.pendingId = null;
    state.pendingNext = null;
    if (row) row.classList.remove('is-busy');
  }

  function resolver(id, accion, extra) {
    extra = extra || {};
    if ((accion === 'liberar_plaza' || accion === 'borrar_planificacion') && !extra._desasignPromptDone) {
      promptDesasignar(id, accion);
      return;
    }
    var row = document.getElementById('row-' + id);
    if (row) row.classList.add('is-busy');
    state.pendingId = id;
    state.pendingNext = nextIdAfter(id);
    var payload = { registro_id: id, accion: accion };
    if (extra.scope) payload.scope = extra.scope;
    if (extra.notas) payload.notas = extra.notas;
    if (extra.force) payload.force = true;

    fetch(U.resolver, { method: 'POST', headers: csrfHeaders(), body: JSON.stringify(payload) })
      .then(function (res) {
        return res.text().then(function (raw) {
          var data = null;
          try { data = raw ? JSON.parse(raw) : null; } catch (e) { data = null; }
          return { ok: res.ok, status: res.status, data: data || {} };
        });
      })
      .then(function (result) {
        var data = result.data;
        if (!result.ok) {
          throw new Error(data.error || ((T.http_fail || 'Error') + ' (HTTP ' + result.status + ')'));
        }
        if (!data.success) {
          restoreCase(row);
          alert((T.error_prefix || 'Error:') + ' ' + (data.error || T.invalid || 'Error'));
          return;
        }
        if (data.requested) {
          restoreCase(row);
          var msg = data.message || T.request_text;
          if (typeof Swal !== 'undefined') Swal.fire({ icon: 'success', title: T.request_created, text: msg });
          else alert(msg);
          return;
        }
        if (data.message) window.showToast(data.message, true);
        state.hist.loaded = false;
        state.cumpLoaded = false;
        // Tanto si se cierra como si queda a medias (falta el otro lado), se repinta la cola.
        return refreshCola();
      })
      .catch(function (err) {
        console.error('Error crítico:', err);
        restoreCase(row);
        alert((T.error_prefix || 'Error:') + ' ' + ((err && err.message) ? err.message : (T.network || 'Error de red')));
      });
  }
  window.resolver = resolver;

  function promptDesasignar(id, accion) {
    var notasHint = CFG.pide_solicitud ? T.notes_hint_request : T.notes_hint;

    function continuar(scope, notas, force) {
      resolver(id, accion, { scope: scope, notas: notas, force: !!force, _desasignPromptDone: true });
    }

    function confirmarForzado(scope, notas) {
      if (typeof Swal === 'undefined') {
        if (window.confirm(T.force_text)) continuar(scope, notas, true);
        return;
      }
      Swal.fire({
        title: T.force_title,
        html: '<p class="text-left small mb-0">' + escapeHtml(T.force_text) + '</p>',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: '#b91c1c',
        confirmButtonText: T.force_yes,
        cancelButtonText: T.cancel,
      }).then(function (res) { if (res.isConfirmed) continuar(scope, notas, true); });
    }

    if (typeof Swal === 'undefined') {
      var futuro = window.confirm(T.unassign_q);
      var notas = futuro ? (window.prompt(notasHint, '') || '') : '';
      var force = futuro && CFG.can_force_past && window.confirm(T.force_adv);
      continuar(futuro ? 'future' : 'day', notas, !!force);
      return;
    }

    var forceHtml = CFG.can_force_past
      ? '<label class="d-block text-left small mt-3 mb-0"><input type="checkbox" id="audDesasignForce" class="mr-1"> ' +
        escapeHtml(T.force_adv) + '</label>'
      : '';

    Swal.fire({
      title: T.unassign,
      html:
        '<p class="text-muted small mb-3">' + escapeHtml(T.unassign_q) + '</p>' +
        '<div class="text-left mb-2">' +
        '<label class="d-block mb-2"><input type="radio" name="audDesasignScope" value="day" checked> ' + escapeHtml(T.only_day) + '</label>' +
        '<label class="d-block"><input type="radio" name="audDesasignScope" value="future"> ' + escapeHtml(T.day_future) + '</label>' +
        '</div>' + forceHtml +
        '<label class="d-block text-left text-muted small mt-3 mb-1" for="audDesasignNotas">' + escapeHtml(T.notes) + '</label>' +
        '<textarea id="audDesasignNotas" class="form-control" rows="2" maxlength="500" placeholder="' +
        escapeHtml(notasHint) + '"></textarea>',
      icon: 'question',
      showCancelButton: true,
      confirmButtonColor: '#d97706',
      confirmButtonText: T['continue'],
      cancelButtonText: T.cancel,
      preConfirm: function () {
        var checked = document.querySelector('input[name="audDesasignScope"]:checked');
        var scope = checked ? checked.value : 'day';
        var notasEl = document.getElementById('audDesasignNotas');
        var forceEl = document.getElementById('audDesasignForce');
        return {
          scope: scope,
          notas: notasEl ? (notasEl.value || '').trim() : '',
          force: !!(forceEl && forceEl.checked && scope === 'future'),
        };
      },
    }).then(function (result) {
      if (!result.isConfirmed || !result.value) return;
      if (result.value.force) confirmarForzado(result.value.scope, result.value.notas);
      else continuar(result.value.scope, result.value.notas, false);
    });
  }

  function reabrir(id, btn) {
    if (!window.confirm(T.reopen_confirm || '?')) return;
    if (btn) btn.disabled = true;
    fetch(U.reabrir, { method: 'POST', headers: csrfHeaders(), body: JSON.stringify({ registro_id: id }) })
      .then(function (res) {
        return res.text().then(function (raw) {
          var data = null;
          try { data = raw ? JSON.parse(raw) : null; } catch (e) { data = null; }
          return { ok: res.ok, data: data || {} };
        });
      })
      .then(function (result) {
        var data = result.data;
        if (result.ok && data.success) {
          window.showToast(data.aviso || T.reopened, true);
          state.cumpLoaded = false;
          refreshCola();
          loadHistorial();
          return;
        }
        alert((T.error_prefix || 'Error:') + ' ' + (data.error || T.reopen_fail));
        if (btn) btn.disabled = false;
      })
      .catch(function (err) {
        console.error(err);
        alert(T.reopen_network);
        if (btn) btn.disabled = false;
      });
  }

  /* ---------- Historial ---------- */

  function historialParams() {
    var h = state.hist;
    var desde = '';
    if (state.rango && state.rango !== 'todo') {
      var d = new Date();
      d.setDate(d.getDate() - (parseInt(state.rango, 10) || 30));
      desde = d.getFullYear() + '-' + ('0' + (d.getMonth() + 1)).slice(-2) + '-' + ('0' + d.getDate()).slice(-2);
    }
    return {
      page: h.page, per_page: h.per, sort: h.sort, dir: h.dir, origen: h.origen,
      q: sharedQ(),
      desde: desde,
      incluir_auto: ($('#audHistAuto') || {}).checked ? '1' : '',
    };
  }

  function renderPager(data) {
    var el = $('#audHistPager');
    if (!el) return;
    var first = data.total ? (data.page - 1) * data.per_page + 1 : 0;
    var last = Math.min(data.total, data.page * data.per_page);
    el.innerHTML =
      '<span>' + first + '–' + last + ' ' + escapeHtml(T.rows_of) + ' ' + data.total + '</span>' +
      '<span class="aud-spacer"></span>' +
      '<button type="button" class="aud-btn aud-btn--ghost aud-btn--sm" data-page="' + (data.page - 1) + '"' +
      (data.page <= 1 ? ' disabled' : '') + '>' + escapeHtml(T.prev) + '</button>' +
      '<span>' + escapeHtml(T.page) + ' ' + data.page + ' / ' + data.pages + '</span>' +
      '<button type="button" class="aud-btn aud-btn--ghost aud-btn--sm" data-page="' + (data.page + 1) + '"' +
      (data.page >= data.pages ? ' disabled' : '') + '>' + escapeHtml(T.next) + '</button>';
  }

  function renderSortMarks() {
    $$('#audHistTable th[data-sort]').forEach(function (th) {
      var base = th.textContent.replace(/[ ▲▼]+$/, '');
      th.textContent = base + (th.dataset.sort === state.hist.sort ? (state.hist.dir === 'asc' ? ' ▲' : ' ▼') : '');
    });
  }

  function loadHistorial() {
    var body = $('#audHistBody');
    if (!body) return;
    state.hist.loaded = true;
    getJson(U.historial, historialParams()).then(function (data) {
      if (!data || !data.success) {
        body.innerHTML = '<tr><td colspan="6" class="aud-table-empty">' + escapeHtml((data && data.error) || T.load_fail) + '</td></tr>';
        return;
      }
      body.innerHTML = data.html;
      state.hist.page = data.page;
      renderPager(data);
      renderSortMarks();
      var conteos = data.conteos;
      $$('[data-count-origen]').forEach(function (el) {
        var k = el.dataset.countOrigen;
        if (!conteos) { el.textContent = ''; return; }
        var v = k === '' ? Object.keys(conteos).reduce(function (s, o) { return s + conteos[o]; }, 0) : conteos[k];
        el.textContent = v;
      });
    });
  }

  /* ---------- Cumplimiento ---------- */

  function pctTxt(v) { return v == null ? '—' : v + '%'; }

  function kpiHtml(label, value, sub, cls) {
    return '<div class="aud-kpi ' + (cls || '') + '"><div class="aud-kpi-label">' + escapeHtml(label) + '</div>' +
      '<div class="aud-kpi-value">' + escapeHtml(value) + '</div>' +
      (sub ? '<div class="aud-kpi-sub">' + escapeHtml(sub) + '</div>' : '') + '</div>';
  }

  function drawChart(key, canvasId, cfg) {
    if (charts[key]) { charts[key].destroy(); charts[key] = null; }
    var canvas = document.getElementById(canvasId);
    if (!canvas || typeof Chart === 'undefined') return;
    charts[key] = new Chart(canvas.getContext('2d'), cfg);
  }

  function renderCumplimiento(d) {
    var k = d.kpis || {};
    var jefes = d.jefes || [];
    var personas = d.personas || [];
    var html = '';

    html += '<div class="aud-kpis" style="grid-template-columns:repeat(5,minmax(0,1fr))">' +
      kpiHtml(T.k_planificados, k.planificados, '', '') +
      kpiHtml(T.k_cumplen, pctTxt(k.cumplimiento), '', (k.cumplimiento != null && k.cumplimiento >= 93) ? 'aud-kpi--ok' : '') +
      kpiHtml(T.k_sinplan, k.sin_planificar, '', k.sin_planificar ? '' : '') +
      kpiHtml(T.k_corr, k.correcciones, '', '') +
      kpiHtml(T.k_faltas, k.faltas, '', k.faltas ? 'aud-kpi--alert' : '') +
      '</div>';

    html += '<div class="aud-grid-2">' +
      '<div class="aud-card"><div class="aud-card-title">' + escapeHtml(T.c_cumpl_title) + '</div>' +
      '<div class="aud-card-sub">' + escapeHtml(T.c_cumpl_sub) + '</div><div class="aud-chart"><canvas id="audChartCumpl"></canvas></div></div>' +
      '<div class="aud-card"><div class="aud-card-title">' + escapeHtml(T.c_corr_title) + '</div>' +
      '<div class="aud-card-sub">' + escapeHtml(T.c_corr_sub) + '</div><div class="aud-chart"><canvas id="audChartCorr"></canvas></div></div>' +
      '</div>';

    html += '<div class="aud-card"><div class="aud-card-title">' + escapeHtml(T.t_jefes_title) + '</div>' +
      '<div class="aud-card-sub">' + escapeHtml(T.t_jefes_sub) + '</div>';
    if (!jefes.length) {
      html += '<div class="aud-table-empty">' + escapeHtml(T.no_data) + '</div>';
    } else {
      html += '<table class="aud-table"><thead><tr><th>' + escapeHtml(T.th_jefe) + '</th><th>' + escapeHtml(T.th_obras) +
        '</th><th class="aud-num">' + escapeHtml(T.th_plan) + '</th><th class="aud-num">' + escapeHtml(T.th_cumpl) +
        '</th><th class="aud-num">' + escapeHtml(T.th_sinplan) + '</th><th class="aud-num">' + escapeHtml(T.th_corr) +
        '</th><th>' + escapeHtml(T.th_lectura) + '</th></tr></thead><tbody>';
      jefes.forEach(function (j) {
        html += '<tr><td class="aud-strong">' + linkHtml('worker', j.jefe_id, j.jefe) + '</td><td class="aud-muted">' + escapeHtml(j.obras) +
          '</td><td class="aud-num">' + j.planificados + '</td><td class="aud-num">' + pctTxt(j.cumplimiento) +
          '</td><td class="aud-num">' + j.sin_planificar + '</td><td class="aud-num">' + j.correcciones +
          '</td><td><span class="aud-tone aud-tone--' + escapeHtml(j.tono) + '">' + escapeHtml(j.lectura) + '</span></td></tr>';
      });
      html += '</tbody></table>';
    }
    html += '</div>';

    html += '<div class="aud-card"><div class="aud-card-title">' + escapeHtml(T.t_pers_title) + '</div>' +
      '<div class="aud-card-sub">' + escapeHtml(T.t_pers_sub) + '</div>';
    if (!personas.length) {
      html += '<div class="aud-table-empty">' + escapeHtml(T.no_data) + '</div>';
    } else {
      html += '<table class="aud-table"><thead><tr><th>' + escapeHtml(T.th_persona) + '</th><th class="aud-num">' +
        escapeHtml(T.th_faltas) + '</th><th class="aud-num">' + escapeHtml(T.th_otra) + '</th><th class="aud-num">' +
        escapeHtml(T.th_sinplan) + '</th></tr></thead><tbody>';
      personas.forEach(function (p) {
        html += '<tr><td class="aud-strong">' + linkHtml('worker', p.user_id, p.persona) + '</td><td class="aud-num">' + p.faltas +
          '</td><td class="aud-num">' + p.otra_obra + '</td><td class="aud-num">' + p.sin_planificar + '</td></tr>';
      });
      html += '</tbody></table>';
    }
    html += '</div>';

    $('#audCumpBody').innerHTML = html;

    var s = d.serie || {};
    drawChart('cumpl', 'audChartCumpl', {
      type: 'line',
      data: {
        labels: d.semanas,
        datasets: [{
          data: s.cumplimiento, borderColor: '#0f172a', backgroundColor: 'rgba(15,23,42,0.08)',
          tension: 0.25, fill: true, spanGaps: true, pointRadius: 3,
        }],
      },
      options: {
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { y: { min: 0, max: 100, ticks: { callback: function (v) { return v + '%'; } } } },
      },
    });
    drawChart('corr', 'audChartCorr', {
      type: 'bar',
      data: {
        labels: d.semanas,
        datasets: [
          { label: T.c_cambio, data: s.cambio_obra, backgroundColor: '#475569' },
          { label: T.c_borrado, data: s.borrado, backgroundColor: '#94a3b8' },
          { label: T.c_alta, data: s.alta_no_planificada, backgroundColor: '#cbd5e1' },
        ],
      },
      options: {
        maintainAspectRatio: false,
        plugins: { legend: { position: 'bottom' } },
        scales: { x: { stacked: true }, y: { stacked: true, beginAtZero: true, ticks: { precision: 0 } } },
      },
    });
  }

  function loadCumplimiento() {
    var body = $('#audCumpBody');
    state.cumpLoaded = true;
    body.innerHTML = '<div class="aud-loading">' + escapeHtml(T.loading) + '</div>';
    getJson(U.cumplimiento, { dias: state.rango || '30', q: sharedQ() }).then(function (data) {
      if (!data || !data.success) {
        state.cumpLoaded = false;
        body.innerHTML = '<div class="aud-loading">' + escapeHtml((data && data.error) || T.load_fail) + '</div>';
        return;
      }
      renderCumplimiento(data);
    });
  }

  /* ---------- sincronización con Odoo ---------- */

  window.forzarSyncFichajes = function () {
    var dias = document.getElementById('diasSync').value;
    window.showToast(dias === '0' ? T.sync_today : (T.sync_days || '').replace('{n}', dias), false);
    fetch(U.sync, { method: 'POST', headers: csrfHeaders(), body: JSON.stringify({ dias: dias }) })
      .then(function (res) { return res.json(); })
      .then(function (data) {
        if (data.success) {
          window.showToast(T.sync_ok, true);
          setTimeout(function () { window.location.reload(); }, 800);
        } else {
          alert(T.sync_err + ' ' + data.error);
          hideToast();
        }
      })
      .catch(function (err) {
        console.error('Error en Fetch:', err);
        alert(T.sync_net);
        hideToast();
      });
  };

  /* ---------- eventos ---------- */

  document.addEventListener('DOMContentLoaded', function () {
    $$('.aud-tab').forEach(function (b) {
      b.addEventListener('click', function () { switchTab(b.dataset.tab); });
    });

    // Resolver (captura: antes de que el clic llegue a la navegación por fila).
    document.addEventListener('click', function (e) {
      var btn = e.target.closest('.js-audit-resolve');
      if (!btn) return;
      e.preventDefault();
      e.stopPropagation();
      var id = parseInt(btn.getAttribute('data-registro-id'), 10);
      var accion = btn.getAttribute('data-accion');
      if (id && accion) resolver(id, accion);
    }, true);

    document.addEventListener('click', function (e) {
      var rb = e.target.closest('.js-aud-reabrir');
      if (rb) {
        e.preventDefault();
        e.stopPropagation();
        reabrir(parseInt(rb.getAttribute('data-registro-id'), 10), rb);
        return;
      }
      var rg = e.target.closest('.js-aud-rango');
      if (rg) {
        e.preventDefault();
        state.rango = rg.dataset.rango;
        var sel = $('#audPeriodo');
        if (sel) sel.value = state.rango;
        onSharedPeriod();
      }
    }, true);

    // Búsqueda y periodo compartidos
    var search = $('#audSearch');
    if (search) {
      state.q = (search.value || '').trim();
      search.addEventListener('input', debounce(onSharedSearch, 280));
    }
    var periodo = $('#audPeriodo');
    if (periodo) {
      state.rango = periodo.value || state.rango;
      periodo.addEventListener('change', onSharedPeriod);
    }

    // Filtros de la cola
    $$('.js-aud-tipo').forEach(function (p) {
      p.addEventListener('click', function () {
        state.tipo = p.dataset.tipo;
        $$('.js-aud-tipo').forEach(function (x) { x.classList.toggle('is-active', x === p); });
        applyColaFilters();
      });
    });
    var geo = $('#audGeoPill');
    if (geo) {
      geo.addEventListener('click', function () {
        state.geo = !state.geo;
        geo.classList.toggle('is-active', state.geo);
        applyColaFilters();
      });
    }

    // Historial
    function resetHist() { state.hist.page = 1; loadHistorial(); }
    $$('.js-aud-origen').forEach(function (p) {
      p.addEventListener('click', function () {
        state.hist.origen = p.dataset.origen;
        $$('.js-aud-origen').forEach(function (x) { x.classList.toggle('is-active', x === p); });
        resetHist();
      });
    });
    var histAuto = $('#audHistAuto');
    if (histAuto) histAuto.addEventListener('change', resetHist);
    var hp = $('#audHistPer');
    if (hp) {
      hp.addEventListener('change', function () { state.hist.per = parseInt(hp.value, 10) || 25; resetHist(); });
    }
    $$('#audHistTable th[data-sort]').forEach(function (th) {
      th.addEventListener('click', function () {
        var s = th.dataset.sort;
        if (state.hist.sort === s) state.hist.dir = state.hist.dir === 'asc' ? 'desc' : 'asc';
        else { state.hist.sort = s; state.hist.dir = 'desc'; }
        resetHist();
      });
    });
    var pager = $('#audHistPager');
    if (pager) {
      pager.addEventListener('click', function (e) {
        var b = e.target.closest('[data-page]');
        if (!b || b.disabled) return;
        state.hist.page = parseInt(b.dataset.page, 10) || 1;
        loadHistorial();
      });
    }

    // Historial del día de la persona: filas del Historial y avisos de hoy.
    if (window.PersonDayTimeline) {
      window.PersonDayTimeline.bindRowClick('.fila-fichaje-auditoria', TIMELINE_OPTS);
    }

    // Por resolver: clic en una fila = detalle a la derecha.
    var lista = $('#audColaBody');
    lista.addEventListener('click', function (e) {
      var th = e.target.closest('th[data-csort]');
      if (th) { sortCases(th.dataset.csort); return; }
      if (e.target.closest('.no-row-nav, a, button')) return;
      var tr = e.target.closest('tr.aud-case');
      if (tr) selectCase(parseInt(tr.dataset.caseId, 10), false);
    });
    document.addEventListener('click', function (e) {
      var dia = e.target.closest('.js-aud-dia');
      if (dia && window.PersonDayTimeline) {
        window.PersonDayTimeline.openModal(dia.dataset.userId, dia.dataset.fecha, TIMELINE_OPTS);
      }
    });

    // «Hoy en curso» como desplegable.
    var hoyBtn = $('#audHoyBtn');
    var hoyPop = $('#audHoyPop');
    if (hoyBtn && hoyPop) {
      hoyBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        hoyPop.hidden = !hoyPop.hidden;
      });
      document.addEventListener('click', function (e) {
        if (!hoyPop.hidden && !e.target.closest('#audHoyPop') && !e.target.closest('#audHoyBtn')) hoyPop.hidden = true;
      });
    }

    // Teclado: ↑/↓ recorren los casos sin soltar el ratón.
    document.addEventListener('keydown', function (e) {
      if (state.tab !== 'resolver') return;
      if (e.target.closest('input, select, textarea') || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === 'ArrowDown') { e.preventDefault(); moveSelection(1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); moveSelection(-1); }
    });
    window.addEventListener('resize', debounce(fitSplit, 120));

    loadCases();
    syncHoy();
    applyColaFilters();

    var f = CFG.focus || {};
    var tab = CFG.tab || 'resolver';
    if (tab === 'resolver' && (f.registro_id || (f.user_id && f.fecha))) {
      var found = focusCase();
      if (!found && f.registro_id) {
        // Ya no está pendiente: se enseña su rastro en el historial.
        var qEl = $('#audSearch');
        if (qEl) qEl.value = String(f.registro_id);
        state.q = String(f.registro_id);
        tab = 'historial';
      }
    }
    switchTab(tab);
    if (tab === 'resolver') focusCase();
  });
})();
