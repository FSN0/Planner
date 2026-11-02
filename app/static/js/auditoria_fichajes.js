/* Auditoría de fichajes: Por resolver / Hoy / Cumplimiento / Historial.
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
    hoyLoaded: false,
    hoyFiltro: '',
    hoyData: null,
    hoyFecha: null, // YYYY-MM-DD; null = día calendario actual
    hoyDrawer: { userId: null, fecha: null, open: false },
    sel: null,
    cases: {},
    sort: { key: null, dir: 'asc' },
  };
  var charts = {};
  var TIMELINE_OPTS = {
    modalId: 'modalTimelineFichaje',
    apiBase: U.timeline || '/sync/timeline_dia',
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
    state.hoyLoaded = false;
  }

  function switchTab(name) {
    if (['resolver', 'hoy', 'cumplimiento', 'historial'].indexOf(name) < 0) name = 'resolver';
    state.tab = name;
    $$('.aud-tab').forEach(function (b) { b.classList.toggle('is-active', b.dataset.tab === name); });
    $$('.aud-panel').forEach(function (p) { p.hidden = p.dataset.panel !== name; });
    // El periodo no aplica al roster de hoy.
    var per = $('#audPeriodo');
    if (per) per.hidden = name === 'hoy';
    try {
      var url = new URL(window.location.href);
      url.searchParams.set('tab', name);
      window.history.replaceState(null, '', url.toString());
    } catch (e) { /* ignore */ }
    if (name !== 'hoy') closeHoyDrawer();
    if (name === 'hoy') loadHoy(false);
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
    else if (state.tab === 'hoy') loadHoy(true);
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

  /* ---------- Hoy (roster) ---------- */

  function shiftIsoDate(iso, deltaDays) {
    var p = (iso || '').split('-');
    if (p.length !== 3) return iso;
    var d = new Date(parseInt(p[0], 10), parseInt(p[1], 10) - 1, parseInt(p[2], 10));
    d.setDate(d.getDate() + deltaDays);
    return d.getFullYear() + '-' +
      ('0' + (d.getMonth() + 1)).slice(-2) + '-' +
      ('0' + d.getDate()).slice(-2);
  }

  function syncHoyNav(data) {
    var fecha = data.hoy || state.hoyFecha;
    var cal = data.hoy_calendario || fecha;
    state.hoyFecha = fecha;
    var inp = $('#audHoyFecha');
    if (inp) {
      inp.value = fecha || '';
      inp.max = cal || '';
    }
    var next = $('#audHoyNext');
    if (next) next.disabled = !!(data.es_hoy || (fecha && cal && fecha >= cal));
    var goToday = $('#audHoyToday');
    if (goToday) goToday.hidden = !!data.es_hoy;
    var hint = $('#audHoyHint');
    if (hint && data.hoy_txt) {
      hint.textContent = (T.hoy_hint || 'Planificados el {d}.').replace('{d}', data.hoy_txt);
    }
  }

  function loadHoy(force) {
    if (state.hoyLoaded && !force) {
      renderHoy();
      return;
    }
    var body = $('#audHoyBody');
    if (body) body.innerHTML = '<div class="aud-loading">' + escapeHtml(T.loading || 'Cargando…') + '</div>';
    var params = { q: sharedQ() };
    if (state.hoyFecha) params.fecha = state.hoyFecha;
    getJson(U.hoy, params).then(function (data) {
      if (!data || !data.success) {
        if (body) body.innerHTML = '<div class="aud-empty"><div class="aud-empty-title">' +
          escapeHtml((data && data.error) || T.http_fail || 'Error') + '</div></div>';
        return;
      }
      state.hoyData = data;
      state.hoyLoaded = true;
      state.hoyFecha = data.hoy || state.hoyFecha;
      var cnt = $('#audHoyTabCount');
      if (cnt) cnt.textContent = (data.totales && data.totales.personas) || 0;
      syncHoyNav(data);
      renderHoy();
    }).catch(function () {
      if (body) body.innerHTML = '<div class="aud-empty"><div class="aud-empty-title">' +
        escapeHtml(T.network || 'Error de red') + '</div></div>';
    });
  }

  function renderHoy() {
    var data = state.hoyData;
    var body = $('#audHoyBody');
    if (!body || !data) return;
    var tot = data.totales || {};
    var setN = function (id, n) { var el = $(id); if (el) el.textContent = n || 0; };
    setN('#audHoyFAll', tot.personas);
    setN('#audHoyFSin', tot.sin_fichar);
    setN('#audHoyFAud', (tot.auditar || 0) + (tot.desvio || 0) + (tot.otra || 0));
    setN('#audHoyFOk', tot.ok);
    setN('#audHoyFFal', tot.falta);

    function chipsOf(p) {
      return (p.plan || p.plazas || []).concat(p.fichajes || p.extras || []);
    }
    var filas = (data.personas || []).filter(function (p) {
      if (!state.hoyFiltro) return true;
      if (state.hoyFiltro === 'auditar') {
        return !!p.tiene_problema ||
          chipsOf(p).some(function (c) {
            return c.chip === 'auditar' || c.chip === 'desvio' || c.chip === 'otra';
          });
      }
      if (state.hoyFiltro === 'sin_fichar') {
        return (p.plan || p.plazas || []).some(function (c) { return c.chip === 'sin_fichar'; });
      }
      if (state.hoyFiltro === 'ok') return p.resumen_chip === 'ok';
      if (state.hoyFiltro === 'falta') {
        return (p.plan || p.plazas || []).some(function (c) { return c.chip === 'falta'; });
      }
      return true;
    });

    if (!filas.length) {
      body.innerHTML = '<div class="aud-empty"><div class="aud-empty-title">' +
        escapeHtml(T.hoy_empty || 'Nadie planificado hoy en tu alcance.') +
        '</div></div>';
      return;
    }

    var html = '<div class="aud-hoy-list">';
    html += '<div class="aud-hoy-head" aria-hidden="true">' +
      '<div></div><div>' + escapeHtml(T.hoy_plan || 'Planificación') + '</div>' +
      '<div>' + escapeHtml(T.hoy_fichaje || 'Fichaje') + '</div></div>';
    filas.forEach(function (p) {
      var tono = p.tono_fila || (p.tiene_problema ? 'problema'
        : (p.resumen_chip === 'ok' ? 'ok' : ''));
      var toneCls = tono ? ' is-' + tono.replace('_', '-') : '';
      // sin_marca → is-sin-marca; parcial → is-parcial
      if (tono === 'sin_marca') toneCls = ' is-sin-marca';
      else if (tono === 'parcial') toneCls = ' is-parcial';
      else if (tono === 'problema') toneCls = ' is-problem';
      else if (tono === 'ok') toneCls = ' is-ok';
      html += '<div class="aud-hoy-row' + toneCls + ' js-aud-hoy-dia" data-user-id="' +
        p.user_id + '" data-fecha="' + escapeHtml(p.fecha || data.hoy || '') +
        '" data-resumen="' + escapeHtml(p.resumen_chip || '') +
        '" title="' + escapeHtml(T.hoy_timeline || 'Ver historial del día') + '">';
      html += '<div class="aud-hoy-person">';
      html += linkHtml('worker', p.user_id, p.nombre, 'aud-strong');
      if (p.categoria) html += '<span class="aud-muted"> · ' + escapeHtml(p.categoria) + '</span>';
      html += '</div>';
      html += '<div class="aud-hoy-col"><div class="aud-hoy-col-label">' +
        escapeHtml(T.hoy_plan || 'Planificación') + '</div><div class="aud-hoy-plazas">';
      (p.plan || p.plazas || []).forEach(function (c) { html += chipHtml(c, false); });
      if (!(p.plan || p.plazas || []).length) {
        html += '<span class="aud-muted">' + escapeHtml(T.hoy_sin_plan || '—') + '</span>';
      }
      html += '</div></div>';
      html += '<div class="aud-hoy-col"><div class="aud-hoy-col-label">' +
        escapeHtml(T.hoy_fichaje || 'Fichaje') + '</div><div class="aud-hoy-plazas">';
      (p.fichajes || []).forEach(function (c) { html += chipHtml(c, !c.en_plan); });
      if (!(p.fichajes || []).length) {
        html += '<span class="aud-hoy-chip aud-hoy-chip--sin_fichar aud-hoy-chip--ghost">' +
          '<span class="aud-hoy-chip-st">' + escapeHtml(T.hoy_sin_marca || 'Sin marca') +
          '</span></span>';
      }
      html += '</div></div></div>';
    });
    html += '</div>';
    body.innerHTML = html;
    markHoyRowSelected();
  }

  function obraLabel(c) {
    var nom = (c.obra || '').trim();
    var cod = (c.codigo || '').trim();
    if (cod && nom) return cod + ' · ' + nom;
    return nom || cod || '';
  }

  function chipHtml(c, fueraPlan) {
    var chip = c.chip === 'otra' ? 'desvio' : (c.chip || 'sin_fichar');
    var cls = 'aud-hoy-chip aud-hoy-chip--' + chip;
    if (fueraPlan) cls += ' aud-hoy-chip--extra';
    var titulo = obraLabel(c);
    var label = escapeHtml(c.label || '');
    var entrada = c.entrada ? ' · ' + escapeHtml(c.entrada) : '';
    var inner = '<span class="aud-hoy-chip-obra">' +
      (c.obra_id ? linkHtml('obra', c.obra_id, titulo) : escapeHtml(titulo)) +
      '</span><span class="aud-hoy-chip-st">' + label + entrada + '</span>';
    var dest = c.destino || (c.caso_id ? 'resolver' : '');
    var rid = c.registro_id || c.caso_id;
    if (rid && dest) {
      var tip = dest === 'resolver'
        ? (T.hoy_goto || 'Ver en Por resolver')
        : (T.hoy_goto_hist || 'Ver en Historial');
      return '<button type="button" class="' + cls + ' js-aud-hoy-caso" data-registro-id="' +
        rid + '" data-destino="' + escapeHtml(dest) + '" title="' + escapeHtml(tip) + '">' +
        inner + '</button>';
    }
    return '<div class="' + cls + '">' + inner + '</div>';
  }

  function openRegistroDesdeHoy(registroId, destino) {
    var id = parseInt(registroId, 10);
    if (!id) return;
    // Chip de obra → Por resolver (o Historial). El cajón inferior solo al clicar la fila.
    if (destino === 'resolver') {
      closeHoyDrawer();
      switchTab('resolver');
      if (state.cases[id]) {
        selectCase(id, true);
        return;
      }
      // Puede estar fuera del rango cargado: fuerza refresh y reintenta.
      refreshCola().then(function () {
        if (state.cases[id]) selectCase(id, true);
        else openRegistroDesdeHoy(id, 'historial');
      });
      return;
    }
    var qEl = $('#audSearch');
    if (qEl) qEl.value = String(id);
    state.q = String(id);
    var auto = $('#audHistAuto');
    if (auto) auto.checked = true;
    state.hist.page = 1;
    state.hist.origen = '';
    state.hist.loaded = false;
    $$('.js-aud-origen').forEach(function (b) {
      b.classList.toggle('is-active', (b.dataset.origen || '') === '');
    });
    switchTab('historial');
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

  var QUE_HACER = {
    no_ficho: 'd_no_fichar', otra_obra: 'd_otra_obra', sin_planificar: 'd_sin_plan', disputa: 'd_disputa',
  };

  function horario(c) {
    if (!c.entrada) return '';
    return c.entrada + (c.salida ? '–' + c.salida : '');
  }

  function detailHtml(c, opts) {
    opts = opts || {};
    var h = '';
    h += '<div class="aud-d-block" data-caso-id="' + c.id + '">';
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
    if (!opts.hideDayLink) {
      h += '<button type="button" class="aud-d-link js-aud-dia" data-user-id="' + c.user_id + '" data-fecha="' + escapeHtml(c.fecha_iso) +
        '"><i class="far fa-calendar-alt"></i> ' + escapeHtml(T.d_day) + '</button>';
    }
    h += '</div>';
    return h;
  }

  function renderDetail(c) {
    var box = $('#audDetail');
    if (!box) return;
    if (!c) {
      box.innerHTML = '<div class="aud-d-empty">' + escapeHtml(state.sel === null && !Object.keys(state.cases).length
        ? T.d_all_done : T.d_empty) + '</div>';
      return;
    }
    box.innerHTML = detailHtml(c);
  }

  /* ---------- Cajón Hoy: timeline + acciones ---------- */

  var HOY_DRAWER_H_KEY = 'audHoyDrawerH';

  function hoyDrawerHeightBounds() {
    var vh = window.innerHeight || 800;
    return { min: Math.round(vh * 0.16), max: Math.round(vh * 0.75) };
  }

  function applyHoyDrawerHeight(px, persist) {
    var b = hoyDrawerHeightBounds();
    var h = Math.max(b.min, Math.min(b.max, Math.round(Number(px) || b.min)));
    state.hoyDrawerPx = h;
    document.documentElement.style.setProperty('--aud-hoy-drawer-h', h + 'px');
    var drawer = $('#audHoyDrawer');
    if (drawer) drawer.style.height = h + 'px';
    if (persist) {
      try { localStorage.setItem(HOY_DRAWER_H_KEY, String(h)); } catch (e) { /* ignore */ }
    }
  }

  function restoreHoyDrawerHeight() {
    var saved = NaN;
    try { saved = parseInt(localStorage.getItem(HOY_DRAWER_H_KEY), 10); } catch (e) { /* ignore */ }
    if (saved && saved > 0) {
      applyHoyDrawerHeight(saved, false);
      return;
    }
    var fallback = Math.min(300, Math.round((window.innerHeight || 800) * 0.34));
    applyHoyDrawerHeight(fallback, false);
  }

  function bindHoyDrawerResize() {
    var handle = $('#audHoyDrawerResize');
    if (!handle || handle.dataset.bound === '1') return;
    handle.dataset.bound = '1';
    var startY = 0;
    var startH = 0;

    function clientY(e) {
      if (e.touches && e.touches[0]) return e.touches[0].clientY;
      if (e.changedTouches && e.changedTouches[0]) return e.changedTouches[0].clientY;
      return e.clientY;
    }
    function onMove(e) {
      if (e.cancelable) e.preventDefault();
      applyHoyDrawerHeight(startH + (startY - clientY(e)), false);
    }
    function onUp() {
      document.body.classList.remove('aud-hoy-drawer-resizing');
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      document.removeEventListener('touchmove', onMove);
      document.removeEventListener('touchend', onUp);
      if (state.hoyDrawerPx) applyHoyDrawerHeight(state.hoyDrawerPx, true);
    }
    function onDown(e) {
      var drawer = $('#audHoyDrawer');
      if (!drawer || drawer.hidden) return;
      e.preventDefault();
      startY = clientY(e);
      startH = drawer.getBoundingClientRect().height;
      document.body.classList.add('aud-hoy-drawer-resizing');
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
      document.addEventListener('touchmove', onMove, { passive: false });
      document.addEventListener('touchend', onUp);
    }
    handle.addEventListener('mousedown', onDown);
    handle.addEventListener('touchstart', onDown, { passive: false });
  }

  function closeHoyDrawer() {
    state.hoyDrawer = { userId: null, fecha: null, open: false };
    var drawer = $('#audHoyDrawer');
    if (drawer) drawer.hidden = true;
    document.body.classList.remove('aud-hoy-drawer-open');
    document.body.classList.remove('aud-hoy-drawer-resizing');
    $$('.aud-hoy-row.is-selected').forEach(function (r) { r.classList.remove('is-selected'); });
  }

  function refreshHoyDrawer() {
    if (!state.hoyDrawer.open || !state.hoyDrawer.userId || !state.hoyDrawer.fecha) return;
    openHoyDrawer(state.hoyDrawer.userId, state.hoyDrawer.fecha, true, {
      focusCasoId: state.hoyDrawer.focusCasoId,
    });
  }

  function openHoyDrawer(userId, fecha, keepScroll, opts) {
    opts = opts || {};
    var focusCasoId = opts.focusCasoId ? parseInt(opts.focusCasoId, 10) : null;
    var drawer = $('#audHoyDrawer');
    var actions = $('#audHoyActions');
    var root = $('#audHoyTimelineRoot');
    if (!drawer || !actions || !root) return;

    state.hoyDrawer = {
      userId: String(userId),
      fecha: String(fecha),
      open: true,
      focusCasoId: focusCasoId || null,
    };
    drawer.hidden = false;
    document.body.classList.add('aud-hoy-drawer-open');

    $$('.aud-hoy-row').forEach(function (r) {
      r.classList.toggle('is-selected',
        String(r.dataset.userId) === String(userId) && String(r.dataset.fecha) === String(fecha));
    });
    var sel = $('.aud-hoy-row.is-selected');
    if (!keepScroll && sel) sel.scrollIntoView({ block: 'nearest' });

    var title = $('#audHoyDrawerTitle');
    if (title) {
      var who = '';
      if (sel) {
        var whoEl = sel.querySelector('.aud-hoy-person .aud-link, .aud-hoy-person a, .aud-hoy-person');
        if (whoEl) who = (whoEl.textContent || '').trim().split('·')[0].trim();
      }
      title.textContent = who
        ? who + ' · ' + fecha
        : (T.hoy_drawer_title || 'Día {d}').replace('{d}', fecha);
    }

    actions.innerHTML = '<div class="aud-loading">' + escapeHtml(T.loading || 'Cargando…') + '</div>';
    if (window.PersonDayTimeline && typeof window.PersonDayTimeline.load === 'function') {
      window.PersonDayTimeline.load(root, userId, fecha, {
        apiBase: TIMELINE_OPTS.apiBase,
        loadingMessage: TIMELINE_OPTS.loadingMessage,
        canResolveAudit: false,
      });
    } else {
      var content = root.querySelector('[data-timeline-content]');
      if (content) {
        content.innerHTML = '<div class="aud-d-empty">' + escapeHtml(T.load_fail || 'Error') + '</div>';
      }
    }

    getJson(U.casos_dia, { user_id: userId, fecha: fecha }).then(function (data) {
      if (!state.hoyDrawer.open ||
          String(state.hoyDrawer.userId) !== String(userId) ||
          String(state.hoyDrawer.fecha) !== String(fecha)) {
        return;
      }
      if (!data || !data.success) {
        actions.innerHTML = '<div class="aud-d-empty">' +
          escapeHtml((data && data.error) || T.load_fail || 'Error') + '</div>';
        return;
      }
      var casos = data.casos || [];
      // Merge into state.cases so resolver() / refreshCola siguen funcionando.
      casos.forEach(function (c) { state.cases[c.id] = c; });
      if (!casos.length) {
        actions.innerHTML = '<div class="aud-d-empty">' +
          escapeHtml(T.hoy_sin_acciones || 'Nada pendiente de auditar este día.') + '</div>';
        return;
      }
      actions.innerHTML = casos.map(function (c) {
        return detailHtml(c, { hideDayLink: true });
      }).join('');
      if (focusCasoId) {
        var block = actions.querySelector('.aud-d-block[data-caso-id="' + focusCasoId + '"]');
        if (block) {
          block.classList.add('is-focus');
          block.scrollIntoView({ block: 'nearest' });
        }
      }
    }).catch(function () {
      actions.innerHTML = '<div class="aud-d-empty">' + escapeHtml(T.network || 'Error de red') + '</div>';
    });
  }

  function markHoyRowSelected() {
    if (!state.hoyDrawer.open) return;
    $$('.aud-hoy-row').forEach(function (r) {
      r.classList.toggle('is-selected',
        String(r.dataset.userId) === String(state.hoyDrawer.userId) &&
        String(r.dataset.fecha) === String(state.hoyDrawer.fecha));
    });
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

  function setHoySinMarcaKpi(n) {
    if (n == null) return;
    var el = $('[data-kpi="hoy"]');
    if (el) el.textContent = n;
    var box = $('#audKpiSinMarca');
    if (box) box.classList.toggle('aud-kpi--alert', Number(n) > 0);
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
      setCounters(data.count, data.resueltos_7d);
      setHoySinMarcaKpi(data.planificados_sin_marca);
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
        state.hoyLoaded = false;
        // Tanto si se cierra como si queda a medias (falta el otro lado), se repinta la cola.
        return refreshCola().then(function () {
          if (state.tab === 'hoy') {
            loadHoy(true);
            if (state.hoyDrawer.open) refreshHoyDrawer();
          }
        });
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

  function lanzarSyncFichajes(dias) {
    var d = String(dias == null ? '7' : dias);
    window.showToast(d === '0' ? T.sync_today : (T.sync_days || '').replace('{n}', d), false);
    fetch(U.sync, { method: 'POST', headers: csrfHeaders(), body: JSON.stringify({ dias: d }) })
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
  }

  window.forzarSyncFichajes = function () {
    var opts = [
      { v: '0', t: T.sync_opt_0 || 'Solo hoy' },
      { v: '7', t: T.sync_opt_7 || 'Últimos 7 días' },
      { v: '15', t: T.sync_opt_15 || 'Últimos 15 días' },
      { v: '30', t: T.sync_opt_30 || 'Último mes' },
      { v: '60', t: T.sync_opt_60 || 'Dos meses' },
    ];
    if (typeof Swal === 'undefined') {
      var raw = window.prompt(T.sync_ask || '¿Cuántos días atrás sincronizar? (0 = solo hoy)', '7');
      if (raw == null) return;
      var n = parseInt(String(raw).trim(), 10);
      if (isNaN(n) || n < 0) n = 7;
      lanzarSyncFichajes(n);
      return;
    }
    var radios = opts.map(function (o, i) {
      return '<label class="d-block text-left mb-2">' +
        '<input type="radio" name="audSyncDias" value="' + o.v + '"' + (i === 1 ? ' checked' : '') + '> ' +
        escapeHtml(o.t) + '</label>';
    }).join('');
    Swal.fire({
      title: T.sync_title || 'Sincronizar fichajes',
      html: '<p class="text-muted small mb-3 text-left">' +
        escapeHtml(T.sync_ask || '¿Cuántos días hacia atrás quieres sincronizar?') + '</p>' +
        '<div class="text-left">' + radios + '</div>',
      icon: 'question',
      showCancelButton: true,
      confirmButtonText: T.sync_go || 'Sincronizar',
      cancelButtonText: T.cancel || 'Cancelar',
      confirmButtonColor: '#0f172a',
      preConfirm: function () {
        var sel = document.querySelector('input[name="audSyncDias"]:checked');
        return sel ? sel.value : '7';
      },
    }).then(function (res) {
      if (res.isConfirmed) lanzarSyncFichajes(res.value);
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

    $$('.js-aud-hoy-filtro').forEach(function (b) {
      b.addEventListener('click', function () {
        state.hoyFiltro = b.dataset.hoyFiltro || '';
        $$('.js-aud-hoy-filtro').forEach(function (x) {
          x.classList.toggle('is-active', x === b);
        });
        renderHoy();
      });
    });
    var hoyPrev = $('#audHoyPrev');
    if (hoyPrev) {
      hoyPrev.addEventListener('click', function () {
        var base = state.hoyFecha || (state.hoyData && state.hoyData.hoy);
        if (!base) return;
        closeHoyDrawer();
        state.hoyFecha = shiftIsoDate(base, -1);
        state.hoyLoaded = false;
        loadHoy(true);
      });
    }
    var hoyNext = $('#audHoyNext');
    if (hoyNext) {
      hoyNext.addEventListener('click', function () {
        var base = state.hoyFecha || (state.hoyData && state.hoyData.hoy);
        var max = (state.hoyData && state.hoyData.hoy_calendario) || base;
        if (!base || base >= max) return;
        closeHoyDrawer();
        state.hoyFecha = shiftIsoDate(base, 1);
        state.hoyLoaded = false;
        loadHoy(true);
      });
    }
    var hoyFecha = $('#audHoyFecha');
    if (hoyFecha) {
      hoyFecha.addEventListener('change', function () {
        var v = (hoyFecha.value || '').trim();
        if (!v) return;
        var max = hoyFecha.max || v;
        closeHoyDrawer();
        state.hoyFecha = v > max ? max : v;
        state.hoyLoaded = false;
        loadHoy(true);
      });
    }
    var hoyToday = $('#audHoyToday');
    if (hoyToday) {
      hoyToday.addEventListener('click', function () {
        closeHoyDrawer();
        state.hoyFecha = (state.hoyData && state.hoyData.hoy_calendario) || null;
        state.hoyLoaded = false;
        loadHoy(true);
      });
    }
    document.addEventListener('click', function (e) {
      var chip = e.target.closest('.js-aud-hoy-caso');
      if (chip) {
        if (e.target.closest('a')) return; // enlace a obra/persona: dejar navegar
        e.preventDefault();
        e.stopPropagation();
        openRegistroDesdeHoy(chip.dataset.registroId, chip.dataset.destino || 'resolver');
        return;
      }
      if (e.target.closest('a, button, input')) return;
      var row = e.target.closest('.js-aud-hoy-dia');
      if (row) {
        openHoyDrawer(row.dataset.userId, row.dataset.fecha, false);
      }
    });
    var drawerClose = $('#audHoyDrawerClose');
    if (drawerClose) drawerClose.addEventListener('click', closeHoyDrawer);
    restoreHoyDrawerHeight();
    bindHoyDrawerResize();

    // Teclado: ↑/↓ en Por resolver; Escape cierra el cajón de Hoy.
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && state.hoyDrawer.open) {
        e.preventDefault();
        closeHoyDrawer();
        return;
      }
      if (state.tab !== 'resolver') return;
      if (e.target.closest('input, select, textarea') || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === 'ArrowDown') { e.preventDefault(); moveSelection(1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); moveSelection(-1); }
    });
    window.addEventListener('resize', debounce(function () {
      fitSplit();
      if (state.hoyDrawerPx) applyHoyDrawerHeight(state.hoyDrawerPx, false);
    }, 120));

    loadCases();
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
